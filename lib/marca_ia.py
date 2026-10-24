"""La marca de IA legible por máquina en lo que sale de Lanternist (OC1.5; art. 50.2 del AI Act).

Cada `final.mp4` y cada miniatura salen con las dos capas que pide la Sección 1 del Código de buenas prácticas
(filas 309, 311 y 312 del addendum; la prueba técnica, en `progress/spike_OC1.5.md`):

- **Metadatos firmados (C2PA)**: un manifiesto que dice «IA» (`digitalSourceType` = `trainedAlgorithmicMedia`), firmado
  con ES256 por un certificado que crea cada instalación la primera vez que hace falta (`config.MARCA_CLAVES_DIR`).
  Sin sello de tiempo, porque pide red. Los validadores públicos dirán «firmante no de confianza»
  (`signingCredential.untrusted`): el certificado no es de una CA de la lista de C2PA.
- **Marca de agua imperceptible**: Video Seal 1.0 en la imagen del vídeo y en la miniatura (256 bits) y AudioSeal 0.2.0
  en el audio (16 bits). El mensaje es el mismo siempre: los bits del sha256 de `MENSAJE`.

Y un detector gratuito y local (`scripts/detecta_marca.py`), que da una línea por capa y un veredicto.

**Dos procesos, como el obrero de escena** (`lib/escena/obrero.py`): este módulo corre en `.venv` y lanza
`lib/marca_ia_worker.py` con el intérprete de `.venv-escena`, que tiene torch, AudioSeal, c2pa-python y PyAV. El
marcado usa la GPU, así que antes comprueba que está libre y toma su cerrojo; la detección no, porque corre también en
CPU.

**La parte de arriba de este módulo no importa nada del repositorio**, ni siquiera `lib.config`: el trabajador la
importa también, para que el veredicto que firma su informe sea el mismo texto que imprime el detector. Lo que lanza el
trabajador importa `lib.config` dentro de cada función, porque en `.venv-escena` no está python-dotenv.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import os
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------------------------------------------
# Lo puro: el mensaje, los umbrales y el veredicto (lo importa también el trabajador)
# ---------------------------------------------------------------------------------------------------------------
MENSAJE = b"Lanternist: AI-generated content"
BITS_IMAGEN = 256
BITS_AUDIO = 16
# «Marcado» si se aciertan 167 o más de los 256 bits. Acertarlos por azar tiene una probabilidad de 6,2 × 10⁻⁷, menos de
# una entre un millón (con 166 sería 1,2 × 10⁻⁶). Lo marcado del episodio de ejemplo queda en 244 o más, y un clip
# sintético de 320×180 y 10 min, en 185 (`progress/verificacion_OC1.5.json`).
UMBRAL_IMAGEN = 167
# El audio está marcado si el detector de AudioSeal lo da con una probabilidad de 0,5 o más (su umbral por defecto). Es
# la marca de Lanternist si además coinciden los 16 bits del mensaje.
UMBRAL_AUDIO = 0.5
ACCION_IA = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
GENERADOR = "Lanternist"
# Lo que dice el detector en su informe firmado.
DETECTOR = "lanternist-ai-mark-detector"

# Los pesos de la marca de agua: los baja el instalador (`instala.py`, paso `marca`) y, si faltan, el primer uso, a
# `dir_de_pesos()`. Su sha256 se comprueba al bajarlos y al cargarlos. Código y pesos, MIT (comprobado en su fuente:
# `progress/comparacion_OC1.5.md`). Su URL, su sha256 y su licencia viven en la lista fija de descargas
# (`datos/descargas.json`, las entradas del paso `marca`), y se leen de ahí para que cada sha256 esté en un solo sitio.
DESCARGAS = Path(__file__).resolve().parent.parent / "datos" / "descargas.json"


def _modelos() -> dict:
    """Las entradas del paso `marca` de la lista fija, con los nombres de campo que usa este módulo."""
    ficheros = json.loads(DESCARGAS.read_text(encoding="utf-8"))["ficheros"]
    return {
        f["id"]: {
            "nombre": f["nombre"],
            "fichero": f["destino"].split("/", 1)[1],
            "url": f["url"],
            "sha256": f["sha256"],
            "licencia": f["licencia"],
            "fuente": f["fuente"],
            "mb": round(f["bytes"] / 1e6),
        }
        for f in ficheros
        if f["paso"] == "marca"
    }


MODELOS = _modelos()


def bits_del_mensaje(n: int) -> list[int]:
    """Los `n` primeros bits del sha256 de `MENSAJE`, del más significativo al menos: 256 para Video Seal, 16 para
    AudioSeal."""
    if not 1 <= n <= 256:
        raise ValueError(f"el mensaje tiene 256 bits y se piden {n}")
    resumen = hashlib.sha256(MENSAJE).digest()
    return [(byte >> (7 - i)) & 1 for byte in resumen for i in range(8)][:n]


def p_valor(aciertos: int, n: int) -> float:
    """La probabilidad de acertar `aciertos` bits o más de `n` por azar (binomial con p = 0,5)."""
    return sum(math.comb(n, k) for k in range(aciertos, n + 1)) / 2**n


def sha256_de(ruta: str | Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def json_canonico(datos: dict) -> bytes:
    """Los bytes que firma el informe del detector: claves ordenadas, sin espacios y en UTF-8."""
    return json.dumps(datos, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# El resultado de una detección (lo escribe el trabajador; claves en inglés, porque va al informe público):
#   {"file", "sha256", "device", "seconds",
#    "c2pa": {"supported", "manifest", "state", "failures", "generator", "signer", "ai", "error"},
#    "image": {"bits", "matches", "p_value", "frames"} o None si el fichero no tiene imagen,
#    "audio": {"probability", "matches", "bits"} o None si no tiene sonido}
def imagen_de_lanternist(resultado: dict) -> bool:
    imagen = resultado.get("image") or {}
    return int(imagen.get("matches") or 0) >= UMBRAL_IMAGEN


def audio_con_marca(resultado: dict) -> bool:
    """El detector de AudioSeal responde: hay una marca de AudioSeal, sea de quien sea, o una falsa alarma."""
    return float((resultado.get("audio") or {}).get("probability") or 0.0) >= UMBRAL_AUDIO


def audio_de_lanternist(resultado: dict) -> bool:
    return audio_con_marca(resultado) and int(resultado["audio"].get("matches") or 0) == BITS_AUDIO


def c2pa_de_lanternist(resultado: dict) -> bool:
    """Un manifiesto de Lanternist, que dice «IA» y con la firma válida (de confianza o no)."""
    c2pa = resultado.get("c2pa") or {}
    return (
        c2pa.get("state") in ("Valid", "Trusted")
        and str(c2pa.get("generator") or "").split(" ")[0] == GENERADOR
        and bool(c2pa.get("ai"))
    )


def de_lanternist(resultado: dict) -> bool:
    """¿Lleva el fichero alguna de las marcas de Lanternist? Basta una capa: las otras se pierden por el camino."""
    return c2pa_de_lanternist(resultado) or imagen_de_lanternist(resultado) or audio_de_lanternist(resultado)


def autocomprobacion(resultado: dict) -> list[str]:
    """Lo que falta en un fichero que Lanternist acaba de marcar: las capas que se esperan y no aparecen.

    Recién marcado y firmado, el fichero tiene que llevarlas TODAS: el manifiesto C2PA válido, la marca de imagen y, si
    tiene sonido, la de audio. Vacío si está todo.
    """
    faltan = []
    c2pa = resultado.get("c2pa") or {}
    if not c2pa_de_lanternist(resultado):
        faltan.append(f"C2PA (estado {c2pa.get('state')}, fallos {c2pa.get('failures')}, error {c2pa.get('error')})")
    if not imagen_de_lanternist(resultado):
        faltan.append(f"marca de imagen ({(resultado.get('image') or {}).get('matches')} de {BITS_IMAGEN} bits)")
    if resultado.get("audio") is not None and not audio_de_lanternist(resultado):
        audio = resultado["audio"]
        faltan.append(f"marca de audio (probabilidad {audio.get('probability')}, {audio.get('matches')} de 16 bits)")
    return faltan


def _linea_c2pa(c2pa: dict) -> str:
    if not c2pa.get("supported"):
        return "C2PA metadata: not checked (this file type cannot carry C2PA)."
    if not c2pa.get("manifest"):
        return "C2PA metadata: none in this file (re-encoding or uploading to a platform removes it)."
    if c2pa.get("error"):
        return f"C2PA metadata: present but unreadable ({c2pa['error']})."
    generador = c2pa.get("generator") or "an unnamed tool"
    dice = "says the content is AI-generated" if c2pa.get("ai") else "does NOT say the content is AI-generated"
    if c2pa.get("state") not in ("Valid", "Trusted"):
        return (
            f"C2PA metadata: from {generador}, but INVALID: the file changed after it was signed "
            f"({', '.join(c2pa.get('failures') or []) or 'no failure code'})."
        )
    confianza = (
        "the signer is on the C2PA trust list"
        if c2pa.get("state") == "Trusted"
        else "the signer is a local certificate, not on the C2PA trust list (signingCredential.untrusted)"
    )
    return f"C2PA metadata: signed by {generador}; it {dice}. Signature valid; {confianza}."


def _linea_imagen(imagen: dict | None) -> str:
    if imagen is None:
        return "Image watermark (Video Seal): not checked (no image in this file)."
    aciertos, bits = int(imagen["matches"]), int(imagen["bits"])
    azar = f"{p_valor(aciertos, bits):.1e}"
    if aciertos >= UMBRAL_IMAGEN:
        return f"Image watermark (Video Seal): FOUND, {aciertos} of {bits} bits match (chance by luck: {azar})."
    return (
        f"Image watermark (Video Seal): not found, {aciertos} of {bits} bits match (chance by luck: {azar}; "
        f"Lanternist needs {UMBRAL_IMAGEN})."
    )


def _linea_audio(audio: dict | None) -> str:
    if audio is None:
        return "Audio watermark (AudioSeal): not checked (no audio in this file)."
    prob, aciertos = float(audio["probability"]), int(audio["matches"])
    if prob < UMBRAL_AUDIO:
        return f"Audio watermark (AudioSeal): not found (detector probability {prob:.2f})."
    if aciertos == BITS_AUDIO:
        return f"Audio watermark (AudioSeal): FOUND (probability {prob:.2f}, {aciertos} of 16 message bits match)."
    # El detector también responde a un tono puro sin marca (0,62 con un seno de 440 Hz, `tests/test_marca_ia.py`): lo
    # que distingue la marca de Lanternist es su mensaje, así que no se afirma que haya una marca.
    return (
        f"Audio watermark (AudioSeal): not Lanternist's. The detector responds (probability {prob:.2f}), but only "
        f"{aciertos} of 16 message bits match: another AudioSeal mark, or a false alarm."
    )


def veredicto(resultado: dict) -> str:
    """El resultado de una detección en inglés llano: una línea por capa y una conclusión (medida 2.3 del Código)."""
    lineas = [
        f"File: {resultado.get('file')} (sha256 {str(resultado.get('sha256'))[:16]}…)",
        _linea_c2pa(resultado.get("c2pa") or {}),
        _linea_imagen(resultado.get("image")),
        _linea_audio(resultado.get("audio")),
    ]
    marcas = [
        nombre
        for nombre, hay in (
            ("C2PA metadata", c2pa_de_lanternist(resultado)),
            ("image watermark", imagen_de_lanternist(resultado)),
            ("audio watermark", audio_de_lanternist(resultado)),
        )
        if hay
    ]
    if marcas:
        conclusion = (
            f"Verdict: MARKED. This file carries the Lanternist mark ({', '.join(marcas)}): it was generated with AI "
            "by Lanternist."
        )
        if not c2pa_de_lanternist(resultado) and (resultado.get("c2pa") or {}).get("supported"):
            conclusion += (
                " Its C2PA metadata is missing or broken, which is normal after re-encoding, editing or a platform "
                "upload; the watermark survives those."
            )
    else:
        conclusion = (
            "Verdict: NOT MARKED. No Lanternist mark found. This does not prove that the file is not AI-generated: "
            "other tools do not use these marks, and heavy editing can destroy them."
        )
    return "\n".join([*lineas, conclusion])


# ---------------------------------------------------------------------------------------------------------------
# Los pesos (sin torch: `dir_de_pesos` reproduce `torch.hub.get_dir()`)
# ---------------------------------------------------------------------------------------------------------------
class ErrorDeMarca(RuntimeError):
    """La marca no se pudo poner, comprobar o leer. El mensaje dice qué falta y qué hacer. No se reintenta."""


def dir_de_pesos() -> Path:
    """`torch.hub.get_dir()/checkpoints/lanternist`, sin importar torch: `TORCH_HOME`, o `XDG_CACHE_HOME/torch`, o
    `~/.cache/torch`, y `hub` debajo. Fuera del repositorio, como el resto de pesos."""
    torch_home = os.environ.get("TORCH_HOME") or os.path.join(os.environ.get("XDG_CACHE_HOME", "~/.cache"), "torch")
    return Path(os.path.expanduser(torch_home)) / "hub" / "checkpoints" / "lanternist"


def ruta_del_peso(clave: str) -> Path:
    return dir_de_pesos() / MODELOS[clave]["fichero"]


def _baja(clave: str) -> Path:
    """Baja un peso a `dir_de_pesos()`, comprobando su sha256 mientras llega. Lo que no cuadra no se queda."""
    modelo = MODELOS[clave]
    destino = ruta_del_peso(clave)
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".part")
    print(f"  [MARCA] bajando {modelo['nombre']} ({modelo['mb']} MB) de {modelo['url']}", flush=True)
    h = hashlib.sha256()
    try:
        # La URL es una constante de `MODELOS`, siempre https, y lo que llega se comprueba por su sha256.
        with urllib.request.urlopen(modelo["url"], timeout=60) as respuesta, open(parcial, "wb") as f:
            for trozo in iter(lambda: respuesta.read(1 << 20), b""):
                h.update(trozo)
                f.write(trozo)
    except (OSError, http.client.HTTPException) as error:
        # `HTTPException` no es `OSError`: sin ella, una descarga cortada (`IncompleteRead`) dejaba el `.part` (R4).
        parcial.unlink(missing_ok=True)
        raise ErrorDeMarca(
            f"no se pudo bajar {modelo['nombre']} de {modelo['url']}: {error}. No se reintenta"
        ) from None
    if h.hexdigest() != modelo["sha256"]:
        parcial.unlink(missing_ok=True)
        raise ErrorDeMarca(
            f"{modelo['nombre']} ha llegado con otro sha256 ({h.hexdigest()[:12]}… y se espera "
            f"{modelo['sha256'][:12]}…): no es el fichero que se comprobó, así que se borra y no se usa"
        )
    parcial.replace(destino)
    return destino


def asegura_pesos() -> None:
    """Baja los pesos que falten. Los que ya están los comprueba el trabajador al cargarlos (su sha256)."""
    for clave in MODELOS:
        if not ruta_del_peso(clave).is_file():
            _baja(clave)


def pesos_que_faltan() -> list[str]:
    """Los pesos que no están o no son los comprobados (por su sha256), para `init.mjs`."""
    return [
        MODELOS[clave]["nombre"]
        for clave in MODELOS
        if not ruta_del_peso(clave).is_file() or sha256_de(ruta_del_peso(clave)) != MODELOS[clave]["sha256"]
    ]


def version() -> str:
    """La versión de Lanternist (`pyproject.toml → version`), que firma el manifiesto C2PA y el informe."""
    import tomllib

    from lib import config

    return tomllib.loads((config.BASE_DIR / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


# ---------------------------------------------------------------------------------------------------------------
# Lanzar el trabajador
# ---------------------------------------------------------------------------------------------------------------
def _lanza(trabajo: Path, resultado: Path, log: Path, *, gpu: bool) -> int:
    """Lanza `lib/marca_ia_worker.py` en `.venv-escena`, sin las claves del `.env`. Devuelve su código.

    Antes deja listo lo que el trabajador necesita en este PC: su entorno y los pesos (se bajan en la primera marca).
    Con `gpu`, comprueba que la GPU está libre y toma el cerrojo de la marca mientras corre: la tarjeta de 8 GB va de un
    trabajo en uno. El cerrojo se suelta aunque el trabajador falle o se pase de tiempo.
    """
    from lib import config
    from lib.escena import render

    if not Path(config.ESCENA_PYTHON).is_file():
        raise ErrorDeMarca(
            f"no está .venv-escena ({config.ESCENA_PYTHON}): se crea con los pasos de spikes/requirements-escena.txt"
        )
    asegura_pesos()
    if gpu:
        try:
            render.exige_gpu_libre()
        except render.ErrorDeRender as error:
            raise ErrorDeMarca(str(error)) from None
    with open(log, "w", encoding="utf-8") as salida:
        proceso = subprocess.Popen(
            [
                config.ESCENA_PYTHON,
                str(config.MARCA_IA_WORKER),
                "--trabajo",
                str(trabajo),
                "--resultado",
                str(resultado),
            ],
            stdout=salida,
            stderr=subprocess.STDOUT,
            env=config.entorno_para_terceros({"PYTHONUNBUFFERED": "1", "NO_TORCH_COMPILE": "1"}),
            cwd=str(config.BASE_DIR),
        )
        if gpu:
            render.toma_cerrojo(config.MARCA_CERROJO, proceso.pid, f"marca de IA: {trabajo.name}")
        try:
            return proceso.wait(timeout=config.MARCA_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proceso.kill()
            proceso.wait()
            raise ErrorDeMarca(f"el trabajador de la marca pasó de {config.MARCA_TIMEOUT_S} s. Log: {log}") from None
        finally:
            if gpu:
                render.suelta_cerrojo(config.MARCA_CERROJO, proceso.pid)


def _ejecuta(trabajo: dict, *, gpu: bool, dir_trabajo: str | Path | None, lanza) -> dict:
    """Escribe el trabajo, lanza el trabajador y devuelve lo que contestó. Sin reintentos."""
    from lib import config

    dir_trabajo = Path(dir_trabajo or config.MARCA_TRABAJO_DIR)
    dir_trabajo.mkdir(parents=True, exist_ok=True)
    sello = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    ruta_trabajo = dir_trabajo / f"marca-{sello}-trabajo.json"
    ruta_resultado = dir_trabajo / f"marca-{sello}-resultado.json"
    log = dir_trabajo / f"marca-{sello}.log"
    trabajo = {
        **trabajo,
        "pesos": {clave: {"ruta": str(ruta_del_peso(clave)), "sha256": m["sha256"]} for clave, m in MODELOS.items()},
        "c2pa": {"claves": str(config.MARCA_CLAVES_DIR), "version": version()},
        "temporales": str(dir_trabajo),
        "sello": sello,
    }
    ruta_trabajo.write_text(json.dumps(trabajo, indent=2, ensure_ascii=False), encoding="utf-8")
    codigo = (lanza or _lanza)(ruta_trabajo, ruta_resultado, log, gpu=gpu)
    if codigo != 0 or not ruta_resultado.is_file():
        cola = log.read_text(encoding="utf-8", errors="replace")[-1500:] if log.exists() else ""
        raise ErrorDeMarca(f"el trabajador de la marca falló (código {codigo}). No se reintenta. Log: {log}\n{cola}")
    return json.loads(ruta_resultado.read_text(encoding="utf-8"))


def _marca(op: str, origen, destino, *, cpu: bool, trabajo, lanza, capas: dict[str, str], modelos: tuple) -> dict:
    """Marca, firma y comprueba `origen` en `destino`, y devuelve el registro. Si la comprobación falla, no queda
    `destino`: un fichero sin su marca no se entrega."""
    origen, destino = Path(origen), Path(destino)
    if not origen.is_file():
        raise ErrorDeMarca(f"no está el fichero que hay que marcar: {origen}")
    try:
        hecho = _ejecuta(
            {"op": op, "origen": str(origen), "destino": str(destino), "dispositivo": "cpu" if cpu else "cuda"},
            gpu=not cpu,
            dir_trabajo=trabajo,
            lanza=lanza,
        )
    except ErrorDeMarca:
        # Lo que el trabajador dejara a medias no se queda como si estuviera marcado, y tampoco el original si se
        # marcaba en su sitio: `subir-al-canal/` es la carpeta de lo que se entrega, y un fichero sin marca no se
        # entrega. Su etapa lo vuelve a componer (revisión de OC1.5, R1).
        destino.unlink(missing_ok=True)
        raise
    comprobacion = hecho.get("comprobacion") or {}
    faltan = autocomprobacion(comprobacion)
    sha = sha256_de(destino) if destino.is_file() else None
    if not faltan and comprobacion.get("sha256") != sha:
        faltan.append("el fichero comprobado no es el que hay en disco (su sha256 no coincide)")
    if faltan:
        destino.unlink(missing_ok=True)
        raise ErrorDeMarca(
            f"la autocomprobación no encuentra la marca en {destino.name}: falta {'; '.join(faltan)}. No se entrega "
            "el fichero"
        )
    return {
        "fichero": destino.name,
        "sha256": sha,
        "detectada": True,
        "capas": {
            "metadatos": "C2PA firmado con ES256 por el certificado local de esta instalación, sin sello de tiempo",
            **capas,
        },
        "modelos": {
            clave: {k: MODELOS[clave][k] for k in ("nombre", "licencia", "fuente", "sha256")} for clave in modelos
        },
        "herramientas": hecho.get("herramientas") or {},
        "comprobacion": comprobacion,
        "segundos": hecho.get("segundos"),
        "dispositivo": hecho.get("dispositivo"),
        "vram_pico_mb": hecho.get("vram_pico_mb"),
        **({"audio": hecho["audio"]} if hecho.get("audio") else {}),
    }


def marca_video(origen, destino, *, cpu: bool = False, trabajo=None, lanza=None) -> dict:
    """Marca la imagen (Video Seal) y el audio (AudioSeal) de `origen`, lo firma con C2PA en `destino` y lo comprueba.

    Devuelve el registro que va a `montaje.json → marca_ia` y de ahí a `assets.json`. `cpu` es para las pruebas: en
    producción el marcado va en la GPU, con su cerrojo. `lanza` sustituye al lanzador real en las pruebas sin GPU.
    """
    capas = {"imagen": "Video Seal 1.0, 256 bits", "audio": "AudioSeal 0.2.0, 16 bits"}
    modelos = ("videoseal", "audioseal_generador", "audioseal_detector")
    return _marca("video", origen, destino, cpu=cpu, trabajo=trabajo, lanza=lanza, capas=capas, modelos=modelos)


def marca_imagen(origen, destino, *, cpu: bool = False, trabajo=None, lanza=None) -> dict:
    """Marca una imagen (la miniatura) con Video Seal, la firma con C2PA en `destino` y lo comprueba. `origen` y
    `destino` pueden ser el mismo fichero."""
    capas = {"imagen": "Video Seal 1.0, 256 bits"}
    return _marca("imagen", origen, destino, cpu=cpu, trabajo=trabajo, lanza=lanza, capas=capas, modelos=("videoseal",))


def _gpu_ocupada() -> bool:
    """Si el detector debe quedarse en la CPU: hay otro trabajo en la tarjeta de 8 GB, o no hay nvidia-smi para mirarlo
    (un PC sin NVIDIA, el de quien solo quiere comprobar un fichero). En CPU son ~11 s por episodio (revisión, R2)."""
    from lib.escena import render

    try:
        en_marcha = render.trabajos_de_gpu_en_marcha()
    except render.ErrorDeRender:
        return True
    if en_marcha:
        print(f"  [MARCA] la GPU está ocupada ({'; '.join(en_marcha)}): el detector va en la CPU", flush=True)
    return bool(en_marcha)


def detecta(ruta, *, informe=None, cpu: bool = False, trabajo=None, lanza=None) -> dict:
    """Busca las tres capas en `ruta` y devuelve el resultado (ver el esquema junto a `imagen_de_lanternist`).

    Corre en la GPU si la hay y si no en CPU (`cpu` la evita), sin cerrojo: lee poco y no se queda en la tarjeta. Con
    `informe`, el trabajador escribe ahí el resultado firmado que pide la sub-medida 2.1.2 del Código.
    """
    ruta = Path(ruta)
    if not ruta.is_file():
        raise ErrorDeMarca(f"no está el fichero: {ruta}")
    hecho = _ejecuta(
        {
            "op": "detecta",
            "origen": str(ruta),
            "dispositivo": "cpu" if cpu or _gpu_ocupada() else "auto",
            "informe": str(Path(informe).resolve()) if informe else None,
            "detector": {"id": DETECTOR, "version": version()},
        },
        gpu=False,
        dir_trabajo=trabajo,
        lanza=lanza,
    )
    return hecho["deteccion"]


# ---------------------------------------------------------------------------------------------------------------
# La guarda de la subida
# ---------------------------------------------------------------------------------------------------------------
def exige_marcado(ruta, registro, *, rehacer: str) -> None:
    """Para si `ruta` no lleva su marca detectada: sin registro, sin «detectada» o con otro sha256 que el marcado.

    La usa la subida (`pipeline.stage_upload` y `set_thumbnail`), y no se salta con `--forzar-subida`. `rehacer` es la
    etapa que hay que volver a lanzar.
    """
    nombre = Path(ruta).name
    if not isinstance(registro, dict) or registro.get("detectada") is not True:
        raise ErrorDeMarca(
            f"{nombre} no tiene su registro de marca de IA detectada (art. 50.2 del AI Act): no se sube. Vuelve a "
            f"lanzar {rehacer}"
        )
    if not Path(ruta).is_file() or registro.get("sha256") != sha256_de(ruta):
        raise ErrorDeMarca(
            f"{nombre} no es el fichero que se marcó (su sha256 no es el del registro de la marca): no se sube. Vuelve "
            f"a lanzar {rehacer}"
        )
