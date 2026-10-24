"""La marca de IA, el trabajo pesado — se ejecuta con el intérprete de `.venv-escena` (OC1.5).

Mismo patrón que `lib/escena/obrero_worker.py`: torch, AudioSeal, c2pa-python y PyAV viven en `.venv-escena`, no en el
`.venv` del pipeline. `lib/marca_ia.py` lanza este archivo como subproceso, le pasa un trabajo en JSON y recoge el
resultado en otro. Tres operaciones:

- `video`: marca la imagen con Video Seal y el audio con AudioSeal, codifica el MP4 y lo firma con C2PA.
- `imagen`: marca una imagen (la miniatura) con Video Seal y la firma con C2PA.
- `detecta`: lee el manifiesto C2PA, la marca de imagen y la de audio de un fichero. Con `informe`, escribe el resultado
  firmado que pide la sub-medida 2.1.2 del Código.

Marcar es siempre **marca de agua → firma C2PA → comprobación** sobre el fichero ya firmado: la firma va la última
porque ata los bytes, y la comprobación es la misma detección que usa cualquiera. Quien decide si la comprobación pasa
es el cliente (`marca_ia.autocomprobacion`).

Contrato (deliberadamente tonto, como el obrero):

- **No lee el `.env`.** Todo llega en el trabajo: las rutas, los pesos con su sha256, la carpeta de las claves y la
  versión de Lanternist. De `lib/` solo importa la parte pura de `lib/marca_ia.py` (el mensaje, los umbrales y el
  veredicto) y la guarda de red del obrero.
- **Sin red** (`_sin_red` del obrero): los pesos los baja el cliente antes de lanzarlo. Y c2pa-python, que es Rust y no
  pasa por los sockets de Python, corre con la descarga de manifiestos remotos y la consulta OCSP apagadas
  (`_contexto_c2pa`).
- **Ningún peso se carga si su sha256 no es el comprobado** (`_peso`).
- **Sin reintentos**: si algo falla, el proceso muere con código distinto de 0 y el cliente lo propaga.

Uso (lo invoca el cliente, no una persona):

    .venv-escena\\Scripts\\python.exe lib/marca_ia_worker.py --trabajo <job.json> --resultado <res.json>
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import math
import os
import subprocess
import sys
import time
from importlib.metadata import version as version_de
from pathlib import Path

# AudioSeal 0.2 compila su modelo con `torch.compile`, que en Windows pide Triton y falla: se apaga ANTES de importarlo.
os.environ["NO_TORCH_COMPILE"] = "1"

import numpy as np  # noqa: E402

if __package__ in (None, ""):
    # Lanzado como script: la raíz del repositorio no está en sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import marca_ia  # noqa: E402
from lib.escena.obrero_worker import _sin_red  # noqa: E402

# Lo que se lee como imagen (con Pillow); lo demás, con ffmpeg como vídeo o audio.
IMAGENES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
# Fotogramas por trozo al marcar y al detectar: con 32 a 1080p, Video Seal se queda en 3,5 GB de VRAM (spike).
TROZO = 32
# El audio se marca y se detecta por ventanas de 60 s como mucho, para que un episodio largo quepa en la VRAM.
VENTANA_AUDIO_S = 60
SR_AUDIOSEAL = 16000
# Para detectar basta con 2 fotogramas por segundo a 256 × 256, el tamaño al que trabaja el detector, y como mucho
# 240 repartidos por el vídeo: en CPU son 11,6 s para el episodio de ejemplo (spike).
FPS_DETECCION = 2
MAX_FOTOGRAMAS_DETECCION = 240
LADO_DETECCION = 256
# La codificación del vídeo marcado: la misma calidad que el render (CRF 16) y el audio en AAC a 192 kbps.
CODIFICA_VIDEO = ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p"]
CODIFICA_AUDIO = ["-c:a", "aac", "-b:a", "192k"]


# ---------------------------------------------------------------------------------------------------------------
# Los modelos
# ---------------------------------------------------------------------------------------------------------------
def _peso(peso: dict) -> Path:
    """La ruta de un peso, solo si su sha256 es el comprobado: un fichero que no cuadra no se carga nunca."""
    ruta = Path(peso["ruta"])
    if not ruta.is_file():
        raise SystemExit(f"[FAIL] no está el peso {ruta}: el cliente lo baja antes de lanzar el trabajador")
    if marca_ia.sha256_de(ruta) != peso["sha256"]:
        raise SystemExit(
            f"[FAIL] {ruta.name} no tiene el sha256 comprobado ({peso['sha256'][:12]}…): no se carga. Bórralo y vuelve "
            "a lanzar: se baja otra vez"
        )
    return ruta


class Taller:
    """El dispositivo y los modelos, cargados una vez, al primer uso."""

    def __init__(self, job: dict):
        import torch

        self.torch = torch
        # «auto» es el del detector: la GPU si la hay, y si no la CPU. El marcado pide «cuda» y sin GPU no arranca.
        pedido = job["dispositivo"]
        if pedido == "auto":
            pedido = "cuda" if torch.cuda.is_available() else "cpu"
        if pedido == "cuda" and not torch.cuda.is_available():
            raise SystemExit(
                "[FAIL] torch.cuda.is_available() == False en .venv-escena: el marcado va en la GPU. Reconstruye el "
                "venv con torch de CUDA (spikes/requirements-escena.txt)"
            )
        self.dispositivo = pedido
        self.pesos = job["pesos"]
        self._videoseal = self._generador = self._detector = None
        self.mensaje_imagen = torch.tensor(marca_ia.bits_del_mensaje(marca_ia.BITS_IMAGEN), dtype=torch.float32)[None]
        self.mensaje_audio = torch.tensor(marca_ia.bits_del_mensaje(marca_ia.BITS_AUDIO), dtype=torch.long)[None]

    @property
    def videoseal(self):
        if self._videoseal is None:
            ruta = _peso(self.pesos["videoseal"])
            self._videoseal = self.torch.jit.load(str(ruta), map_location=self.dispositivo).eval()
        return self._videoseal

    @property
    def generador(self):
        if self._generador is None:
            from audioseal import AudioSeal

            ruta = _peso(self.pesos["audioseal_generador"])
            self._generador = AudioSeal.load_generator(str(ruta), nbits=marca_ia.BITS_AUDIO).to(self.dispositivo)
            self._generador.eval()
        return self._generador

    @property
    def detector(self):
        if self._detector is None:
            from audioseal import AudioSeal

            ruta = _peso(self.pesos["audioseal_detector"])
            self._detector = AudioSeal.load_detector(str(ruta), nbits=marca_ia.BITS_AUDIO).to(self.dispositivo)
            self._detector.eval()
        return self._detector


def herramientas() -> dict:
    """Las versiones con que se marcó o se detectó, para el registro."""
    return {p: version_de(p) for p in ("torch", "audioseal", "c2pa-python", "av")}


# ---------------------------------------------------------------------------------------------------------------
# Leer el fichero
# ---------------------------------------------------------------------------------------------------------------
def sonda(ruta: Path) -> dict:
    """El primer flujo de vídeo y el primer flujo de audio de un fichero, y su duración, según ffprobe."""
    r = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height,avg_frame_rate,sample_rate,channels",
        ]
        + ["-show_entries", "format=duration", "-of", "json", str(ruta)],
        capture_output=True,
        text=True,
        check=True,
    )
    datos = json.loads(r.stdout)
    flujos = datos.get("streams") or []
    video = next((s for s in flujos if s.get("codec_type") == "video"), None)
    audio = next((s for s in flujos if s.get("codec_type") == "audio"), None)
    return {
        "duracion": float((datos.get("format") or {}).get("duration") or 0.0),
        "video": {"w": video["width"], "h": video["height"], "fps": video["avg_frame_rate"]} if video else None,
        "audio": {"sr": int(audio["sample_rate"]), "canales": int(audio["channels"])} if audio else None,
    }


def lee_audio(ruta: Path, sr: int, canales: int) -> np.ndarray:
    """El primer flujo de audio, en float32, como [canales, muestras]."""
    crudo = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(ruta), "-map", "0:a:0", "-ac", str(canales), "-ar", str(sr)]
        + ["-f", "f32le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(crudo, dtype=np.float32).reshape(-1, canales).T.copy()


def _ventanas(muestras: np.ndarray) -> list[np.ndarray]:
    """Trozos iguales de `VENTANA_AUDIO_S` como mucho: sin un resto diminuto al final, que el modelo no sabría leer."""
    n = max(1, math.ceil(len(muestras) / (VENTANA_AUDIO_S * SR_AUDIOSEAL)))
    return np.array_split(muestras, n)


# ---------------------------------------------------------------------------------------------------------------
# Marcar
# ---------------------------------------------------------------------------------------------------------------
def marca_audio(origen: Path, audio: dict, wav: Path, taller: Taller) -> dict:
    """El audio de `origen` con la marca de AudioSeal, en `wav`, a su frecuencia y con sus canales.

    AudioSeal trabaja a 16 kHz y en mono, y la versión 0.2 ya no remuestrea por dentro: la marca se calcula sobre una
    copia mono a 16 kHz, se sube a la frecuencia del original y se suma a todos sus canales (spike, punto 4).
    """
    from scipy.io import wavfile
    from scipy.signal import resample_poly

    torch = taller.torch
    sr, canales = audio["sr"], audio["canales"]
    original = lee_audio(origen, sr, canales)
    mono = lee_audio(origen, SR_AUDIOSEAL, 1)[0]
    trozos = []
    with torch.no_grad():
        for ventana in _ventanas(mono):
            x = torch.from_numpy(ventana)[None, None].to(taller.dispositivo)
            mensaje = taller.mensaje_audio.to(taller.dispositivo)
            trozos.append(taller.generador.get_watermark(x, message=mensaje)[0, 0].cpu().numpy())
    marca16 = np.concatenate(trozos)
    comun = math.gcd(sr, SR_AUDIOSEAL)
    marca = resample_poly(marca16, sr // comun, SR_AUDIOSEAL // comun)[: original.shape[1]]
    marca = np.pad(marca, (0, original.shape[1] - len(marca))).astype(np.float32)
    marcado = np.clip(original + marca[None], -1.0, 1.0).astype(np.float32)
    wavfile.write(wav, sr, marcado.T)
    energia = float(np.mean(marca**2))
    return {
        "frecuencia_hz": sr,
        "canales": canales,
        # Cuánto queda la marca por debajo del sonido (26,4 dB en el episodio de ejemplo).
        "snr_db": round(10 * math.log10(float(np.mean(original**2)) / energia), 1) if energia > 0 else None,
    }


def escribe_video(origen: Path, destino: Path, wav: Path | None, video: dict, taller: Taller) -> int:
    """Los fotogramas de `origen` con la marca de Video Seal, codificados en `destino` con el audio de `wav`.

    Se decodifica con PyAV dentro del proceso y se escribe por la entrada de ffmpeg: leer 1080p por una tubería de
    ffmpeg desde Python tarda 74 s por 54 s de vídeo en Windows, y con PyAV, 14 (spike, punto 1).
    """
    import av

    torch = taller.torch
    orden = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24"]
    orden += ["-s", f"{video['w']}x{video['h']}", "-r", video["fps"], "-i", "-"]
    orden += ["-i", str(wav), "-map", "0:v", "-map", "1:a", *CODIFICA_AUDIO] if wav else ["-an"]
    orden += [*CODIFICA_VIDEO, "-movflags", "+faststart", str(destino)]
    escritor = subprocess.Popen(orden, stdin=subprocess.PIPE)
    mensaje = taller.mensaje_imagen.to(taller.dispositivo)
    n = 0

    def vuelca(trozo: list[np.ndarray]) -> None:
        x = torch.from_numpy(np.stack(trozo)).to(taller.dispositivo).permute(0, 3, 1, 2).float() / 255
        with torch.no_grad():
            y = taller.videoseal.embed(x, mensaje, is_video=True)
        salida = (y.clamp(0, 1) * 255).round().byte().permute(0, 2, 3, 1).contiguous().cpu().numpy()
        escritor.stdin.write(salida.tobytes())

    try:
        with av.open(str(origen)) as contenedor:
            flujo = contenedor.streams.video[0]
            flujo.thread_type = "AUTO"
            trozo: list[np.ndarray] = []
            for fotograma in contenedor.decode(flujo):
                trozo.append(fotograma.to_ndarray(format="rgb24"))
                n += 1
                if len(trozo) == TROZO:
                    vuelca(trozo)
                    trozo = []
            if trozo:
                vuelca(trozo)
        escritor.stdin.close()
    except BaseException:
        escritor.kill()
        raise
    if escritor.wait() != 0:
        raise SystemExit(f"[FAIL] ffmpeg no pudo codificar el vídeo marcado (código {escritor.returncode})")
    return n


def marca_la_imagen(origen: Path, destino: Path, taller: Taller) -> None:
    from PIL import Image

    torch = taller.torch
    with Image.open(origen) as im:
        rgb = np.array(im.convert("RGB"))
    x = torch.from_numpy(rgb).permute(2, 0, 1)[None].float().div(255).to(taller.dispositivo)
    with torch.no_grad():
        y = taller.videoseal.embed(x, taller.mensaje_imagen.to(taller.dispositivo)).clamp(0, 1)
    Image.fromarray((y[0].permute(1, 2, 0) * 255).round().byte().cpu().numpy()).save(destino)


# ---------------------------------------------------------------------------------------------------------------
# C2PA
# ---------------------------------------------------------------------------------------------------------------
def _contexto_c2pa():
    """Los ajustes de c2pa-python: sin red (ni manifiestos remotos ni OCSP) y sin miniatura dentro del manifiesto.

    La miniatura del manifiesto es una copia en JPEG de la imagen: no la pide el Código y le sumaba ~100 KB a una
    miniatura que YouTube admite hasta 2 MB (spike: 1,57 → 1,68 MB).
    """
    import c2pa

    ajustes = {
        "verify": {"remote_manifest_fetch": False, "ocsp_fetch": False},
        "builder": {"thumbnail": {"enabled": False}},
    }
    return c2pa.Context(settings=c2pa.Settings.from_dict(ajustes))


def credenciales(carpeta: Path) -> tuple[bytes, bytes]:
    """La cadena de certificados y la clave privada de esta instalación; se crean la primera vez que hacen falta.

    Una CA local y un certificado de firma ES256 que cumple el perfil de C2PA (spike, punto 6). Nada personal: el nombre
    es «Lanternist local signer» y la organización «Lanternist user». La clave de la CA no se guarda: solo firma la hoja
    una vez. Viven fuera del repositorio (`config.MARCA_CLAVES_DIR`), así que nunca viajan con el código.
    """
    cadena, clave = carpeta / "cadena.pem", carpeta / "clave.pem"
    if cadena.is_file() and clave.is_file():
        return cadena.read_bytes(), clave.read_bytes()
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    ahora = dt.datetime.now(dt.UTC)
    desde, hasta = ahora - dt.timedelta(minutes=5), ahora + dt.timedelta(days=3650)
    organizacion = x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Lanternist user")
    clave_ca = ec.generate_private_key(ec.SECP256R1())
    nombre_ca = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Lanternist local root"), organizacion])
    usos_ca = x509.KeyUsage(False, False, False, False, False, True, True, False, False)
    ca = (
        x509.CertificateBuilder()
        .subject_name(nombre_ca)
        .issuer_name(nombre_ca)
        .public_key(clave_ca.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(desde)
        .not_valid_after(hasta)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(usos_ca, critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(clave_ca.public_key()), critical=False)
        .sign(clave_ca, hashes.SHA256())
    )
    clave_hoja = ec.generate_private_key(ec.SECP256R1())
    usos_hoja = x509.KeyUsage(True, False, False, False, False, False, False, False, False)
    hoja = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Lanternist local signer"), organizacion]))
        .issuer_name(nombre_ca)
        .public_key(clave_hoja.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(desde)
        .not_valid_after(hasta)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(usos_hoja, critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(clave_hoja.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(clave_ca.public_key()), critical=False)
        .sign(clave_ca, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    carpeta.mkdir(parents=True, exist_ok=True)
    clave.write_bytes(clave_hoja.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cadena.write_bytes(hoja.public_bytes(pem) + ca.public_bytes(pem))
    return cadena.read_bytes(), clave.read_bytes()


def firma(origen: Path, destino: Path, cfg: dict) -> None:
    """Firma `origen` con C2PA en `destino`: un manifiesto que dice que el contenido es IA y quién lo hizo."""
    import c2pa

    cadena, clave = credenciales(Path(cfg["claves"]))
    agente = {"name": marca_ia.GENERADOR, "version": cfg["version"]}
    manifiesto = {
        "claim_generator_info": [agente],
        "title": destino.name,
        "assertions": [
            {
                "label": "c2pa.actions.v2",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "digitalSourceType": marca_ia.ACCION_IA,
                            "softwareAgent": agente,
                            "when": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                        }
                    ]
                },
            }
        ],
    }
    info = c2pa.C2paSignerInfo(c2pa.C2paSigningAlg.ES256, cadena, clave, None)
    with c2pa.Signer.from_info(info) as firmante, c2pa.Builder(manifiesto, context=_contexto_c2pa()) as constructor:
        constructor.sign_file(origen, destino, firmante)


def lee_c2pa(ruta: Path) -> dict:
    """El manifiesto C2PA activo de `ruta`: si el formato lo admite, si lo hay, su estado y lo que dice."""
    import c2pa

    try:
        with c2pa.Reader(str(ruta), context=_contexto_c2pa()) as lector:
            estado = lector.get_validation_state()
            resultados = lector.get_validation_results() or {}
            activo = lector.get_active_manifest() or {}
    except c2pa.C2paError.ManifestNotFound:
        return {"supported": True, "manifest": False}
    except c2pa.C2paError.NotSupported:
        return {"supported": False, "manifest": False}
    except c2pa.C2paError as error:
        return {"supported": True, "manifest": True, "state": None, "error": str(error)[:300]}
    generador = (activo.get("claim_generator_info") or [{}])[0]
    acciones = [
        accion
        for afirmacion in activo.get("assertions") or []
        if str(afirmacion.get("label", "")).startswith("c2pa.actions")
        for accion in (afirmacion.get("data") or {}).get("actions") or []
    ]
    return {
        "supported": True,
        "manifest": True,
        "state": estado,
        "failures": [f.get("code") for f in (resultados.get("activeManifest") or {}).get("failure") or []],
        "generator": " ".join(str(x) for x in (generador.get("name"), generador.get("version")) if x) or None,
        "signer": (activo.get("signature_info") or {}).get("common_name"),
        "ai": any(a.get("digitalSourceType") == marca_ia.ACCION_IA for a in acciones),
        "error": None,
    }


# ---------------------------------------------------------------------------------------------------------------
# Detectar
# ---------------------------------------------------------------------------------------------------------------
def _aciertos(logits, mensaje: list[int]) -> int:
    bits = (logits > 0).int().tolist()
    return sum(int(a == b) for a, b in zip(bits, mensaje))


def detecta_imagen(ruta: Path, info: dict | None, taller: Taller) -> dict | None:
    """La marca de Video Seal: de la imagen entera, o de hasta 240 fotogramas de 256 × 256 repartidos por el vídeo."""
    torch = taller.torch
    mensaje = marca_ia.bits_del_mensaje(marca_ia.BITS_IMAGEN)
    if ruta.suffix.lower() in IMAGENES:
        from PIL import Image

        with Image.open(ruta) as im:
            rgb = np.array(im.convert("RGB"))
        x = torch.from_numpy(rgb).permute(2, 0, 1)[None].float().div(255).to(taller.dispositivo)
        with torch.no_grad():
            logits = taller.videoseal.detect(x)[:, 1:].mean(0).cpu()
        n = 1
    else:
        if not info or not info["video"]:
            return None
        fps = FPS_DETECCION
        if info["duracion"] * fps > MAX_FOTOGRAMAS_DETECCION:
            fps = MAX_FOTOGRAMAS_DETECCION / info["duracion"]
        filtro = f"fps={fps:.6f},scale={LADO_DETECCION}:{LADO_DETECCION}:flags=area"
        crudo = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(ruta), "-map", "0:v:0", "-vf", filtro]
            + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True,
            check=True,
        ).stdout
        fotos = np.frombuffer(crudo, np.uint8).reshape(-1, LADO_DETECCION, LADO_DETECCION, 3)
        if not len(fotos):
            return None
        x = torch.from_numpy(fotos.copy()).permute(0, 3, 1, 2).float() / 255
        with torch.no_grad():
            partes = [taller.videoseal.detect(t.to(taller.dispositivo), is_video=True)[:, 1:] for t in x.split(TROZO)]
        logits = torch.cat(partes).mean(0).cpu()
        n = len(fotos)
    aciertos = _aciertos(logits, mensaje)
    return {
        "bits": marca_ia.BITS_IMAGEN,
        "matches": aciertos,
        "p_value": marca_ia.p_valor(aciertos, marca_ia.BITS_IMAGEN),
        "frames": n,
    }


def detecta_audio(ruta: Path, info: dict | None, taller: Taller) -> dict | None:
    """La marca de AudioSeal, por ventanas: la fracción de instantes marcados y el mensaje promediado.

    Es la cuenta de `AudioSealDetector.detect_watermark`, sumada ventana a ventana para que un audio largo quepa.
    """
    if not info or not info["audio"]:
        return None
    torch = taller.torch
    mono = lee_audio(ruta, SR_AUDIOSEAL, 1)[0]
    if not len(mono):
        return None
    positivos, total = 0, 0
    suma = np.zeros(marca_ia.BITS_AUDIO)
    with torch.no_grad():
        for ventana in _ventanas(mono):
            resultado, mensaje = taller.detector(torch.from_numpy(ventana)[None, None].to(taller.dispositivo))
            instantes = resultado.shape[-1]
            positivos += int((resultado[:, 1, :] > 0.5).sum())
            total += instantes
            suma += mensaje[0].float().cpu().numpy() * instantes
    bits = (suma / total > 0.5).astype(int).tolist()
    esperado = marca_ia.bits_del_mensaje(marca_ia.BITS_AUDIO)
    return {
        "bits": marca_ia.BITS_AUDIO,
        "probability": round(positivos / total, 4),
        "matches": sum(int(a == b) for a, b in zip(bits, esperado)),
    }


def detecta(ruta: Path, taller: Taller) -> dict:
    t0 = time.perf_counter()
    info = None if ruta.suffix.lower() in IMAGENES else sonda(ruta)
    return {
        "file": ruta.name,
        "sha256": marca_ia.sha256_de(ruta),
        "device": taller.dispositivo,
        "c2pa": lee_c2pa(ruta),
        "image": detecta_imagen(ruta, info, taller),
        "audio": detecta_audio(ruta, info, taller),
        "seconds": round(time.perf_counter() - t0, 2),
    }


def informe_firmado(deteccion: dict, job: dict) -> dict:
    """El resultado que se puede descargar firmado (sub-medida 2.1.2): el fichero por su sha256, el detector, la hora
    UTC, los resultados y el veredicto, con la firma ES256 de la clave local sobre su JSON canónico."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    informe = {
        "file": deteccion["file"],
        "sha256": deteccion["sha256"],
        "detector": {
            **job["detector"],
            # Los dos modelos que detectan, por su URL y su sha256: el generador de AudioSeal no interviene.
            "models": {
                marca_ia.MODELOS[clave]["url"]: job["pesos"][clave]["sha256"]
                for clave in ("videoseal", "audioseal_detector")
            },
        },
        "time_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "results": deteccion,
        "lanternist_mark": marca_ia.de_lanternist(deteccion),
        "verdict": marca_ia.veredicto(deteccion),
    }
    cadena, clave_pem = credenciales(Path(job["c2pa"]["claves"]))
    clave = serialization.load_pem_private_key(clave_pem, password=None)
    r, s = decode_dss_signature(clave.sign(marca_ia.json_canonico(informe), ec.ECDSA(hashes.SHA256())))
    return {
        "report": informe,
        "signature": {
            "alg": "ES256",
            "value": base64.b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode("ascii"),
            "signed_bytes": "the `report` object as canonical JSON: keys sorted, separators ',' and ':', UTF-8",
            "certificate_chain_pem": cadena.decode("ascii"),
        },
    }


# ---------------------------------------------------------------------------------------------------------------
# Las operaciones
# ---------------------------------------------------------------------------------------------------------------
def _temporal(job: dict, que: str, sufijo: str) -> Path:
    return Path(job["temporales"]) / f"marca-{job['sello']}-{que}{sufijo}"


def op_video(job: dict, taller: Taller) -> dict:
    origen, destino = Path(job["origen"]), Path(job["destino"])
    sin_firma, wav = _temporal(job, "sin-firma", destino.suffix), _temporal(job, "audio", ".wav")
    try:
        info = sonda(origen)
        if not info["video"]:
            raise SystemExit(f"[FAIL] {origen.name} no tiene imagen: no es un vídeo")
        audio = marca_audio(origen, info["audio"], wav, taller) if info["audio"] else None
        fotogramas = escribe_video(origen, sin_firma, wav if audio else None, info["video"], taller)
        firma(sin_firma, destino, job["c2pa"])
    finally:
        sin_firma.unlink(missing_ok=True)
        wav.unlink(missing_ok=True)
    return {"fotogramas": fotogramas, **({"audio": audio} if audio else {})}


def op_imagen(job: dict, taller: Taller) -> dict:
    origen, destino = Path(job["origen"]), Path(job["destino"])
    sin_firma = _temporal(job, "sin-firma", destino.suffix)
    try:
        marca_la_imagen(origen, sin_firma, taller)
        firma(sin_firma, destino, job["c2pa"])
    finally:
        sin_firma.unlink(missing_ok=True)
    return {}


def op_detecta(job: dict, taller: Taller) -> dict:
    deteccion = detecta(Path(job["origen"]), taller)
    if job.get("informe"):
        destino = Path(job["informe"])
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(informe_firmado(deteccion, job), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return {"deteccion": deteccion}


OPERACIONES = {"video": op_video, "imagen": op_imagen, "detecta": op_detecta}


def main() -> int:
    parser = argparse.ArgumentParser(description="La marca de IA de Lanternist (se ejecuta en .venv-escena)")
    parser.add_argument("--trabajo", required=True)
    parser.add_argument("--resultado", required=True)
    args = parser.parse_args()

    job = json.loads(Path(args.trabajo).read_text(encoding="utf-8"))
    if job.get("op") not in OPERACIONES:
        raise SystemExit(f"[FAIL] operación que la marca no sabe hacer: {job.get('op')!r} ({', '.join(OPERACIONES)})")
    _sin_red()
    taller = Taller(job)
    torch = taller.torch
    t0 = time.perf_counter()
    hecho = OPERACIONES[job["op"]](job, taller)
    hecho["segundos"] = round(time.perf_counter() - t0, 2)
    if job["op"] != "detecta":
        # La comprobación, sobre el fichero ya firmado: la misma detección que hace cualquiera.
        hecho["comprobacion"] = detecta(Path(job["destino"]), taller)
    hecho.update(dispositivo=taller.dispositivo, herramientas=herramientas())
    if taller.dispositivo == "cuda":
        hecho["vram_pico_mb"] = round(torch.cuda.max_memory_reserved() / 1024**2)
    print(f"  [{job['op']}] {hecho['segundos']} s en {taller.dispositivo}", flush=True)
    destino = Path(args.resultado)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(hecho, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
