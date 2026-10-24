"""El obrero de activos del motor de escena — se ejecuta con el intérprete de `.venv-escena` (F6.2c).

Mismo patrón que `lib/voice_worker.py` y `lib/alineador_worker.py`, y por el mismo motivo: torch, spandrel
(Real-ESRGAN) y transformers (SAM 2.1) viven en `.venv-escena`, no en el `.venv` del pipeline. `lib/escena/
obrero.py` lanza este archivo como subproceso, le pasa un trabajo en JSON y recoge el resultado en otro.

Tres operaciones, las tres sobre la GPU y EN SERIE (una imagen cada vez; los modelos se cargan una sola vez):

- `recorta`: amplía ×4 con Real-ESRGAN por teselas, baja a ×2, quita el fondo de croma por tono y recorta cada
  figura con su punto de apoyo. Una figura, varias por orden de lectura (una hoja de personaje), o varias por
  el sitio de cada una (una lámina de objetos).
- `fondo`: un fondo entero, ampliado igual y sin recortar.
- `separa`: SAM 2.1 por caja y puntos sobre una imagen ya recortada; la pieza que se mueve sola (un árbol que se
  mece, una cola) sale con su pivote, y la base puede quedarse sin ella. El hueco que deja en la base se puede
  rellenar (F6.6) con lo que lo rodea (OpenCV, `rellena_base`), con una lámina limpia (`relleno`) o con la misma
  imagen desplazada (`relleno_desplazado`): la base de una lámina que sigue a la vista detrás de la pieza.

Lo numérico sin GPU (el croma, las figuras, el apoyo, el borde de la máscara) está en `lib/escena/recorte.py`,
que se importa aquí y desde el cliente. Es lo ÚNICO del repositorio que importa este archivo, y no depende de
nada más del repositorio (lo vigila `tests/escena/test_obrero.py`): `lib.config` necesita `python-dotenv`, que en
`.venv-escena` no está.

Contrato (deliberadamente tonto: aquí no se decide nada):

- **No lee el `.env` ni el perfil de ningún canal.** Todo llega en el trabajo: las rutas, los pesos, los nombres
  y las cajas.
- **Sin red** (`_sin_red`): la caché de Hugging Face ya tiene SAM 2.1 y el peso de Real-ESRGAN se lee de la
  carpeta de modelos de ComfyUI. Si falta algo, el error es explícito en vez de una descarga (decisión 6). Y
  además de las variables de entorno, un socket que no vaya a loopback se corta antes de conectar.
- **Exige CUDA**: sin GPU, Real-ESRGAN y SAM tardarían minutos por imagen y el lote parecería colgado.
- **Sin reintentos**: si una operación falla, el proceso muere con código distinto de 0 y el cliente lo propaga.
  Lo ya hecho queda en el resultado, que se vuelca tras cada operación.

Uso (lo invoca el cliente, no una persona):

    .venv-escena\\Scripts\\python.exe lib/escena/obrero_worker.py --trabajo <job.json> --resultado <res.json>

Formato del trabajo:

    {
      "esrgan": {"peso": "<.pth>", "tesela": 384, "solape": 24},
      "sam": {"modelo": "facebook/sam2.1-hiera-large"},
      "img_dir": "<carpeta donde van las imágenes recortadas>",
      "src_dir": "assets/img",
      "operaciones": [
        {"op": "recorta", "nombre": "x", "origen": "<png generado>"},
        {"op": "recorta", "nombre": "hoja", "origen": "...", "piezas": ["a_frente", "a_perfil"],
         "k_de": "a_frente", "alto_k": 1640},
        {"op": "recorta", "nombre": "objetos", "origen": "...", "sitios": {"llave": [300, 420]}},
        {"op": "fondo", "nombre": "calle", "origen": "...", "ancho": 3584},
        {"op": "separa", "nombre": "calle", "archivo": "calle.jpg", "base": {<su entrada de catálogo>},
         "piezas": [{"nombre": "arbol", "caja": [x0, y0, x1, y1], "pos": [[x, y]], "neg": [[x, y]],
                     "pivote": [x, y]}], "quita_de_la_base": false}
      ]
    }

Opcionales de `recorta`: `centradas` (nombres que giran sobre su centro, como una rueda) y `anclas` ({nombre:
[x, y]} en la imagen ampliada completa, un apoyo fijado a mano).
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import socket
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

if __package__ in (None, ""):
    # Lanzado como script: la raíz del repositorio no está en sys.path, y `recorte` vive en `lib/escena/`.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.escena import recorte  # noqa: E402

MARCA_SIN_RED = "[sin-red]"


# ---------------------------------------------------------------------------------------------------------------
# Las dos guardas: sin red y con GPU
# ---------------------------------------------------------------------------------------------------------------
def _es_local(host) -> bool:
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return str(host).lower() == "localhost"


def _es_literal(host) -> bool:
    try:
        ipaddress.ip_address(str(host).split("%")[0])
        return True
    except ValueError:
        return False


def _sin_red() -> None:
    """Prohíbe la descarga silenciosa de pesos y corta cualquier conexión que no sea a loopback.

    - `HF_HUB_OFFLINE` y `TRANSFORMERS_OFFLINE` a 1, como `_sin_red()` de `lib/voice_worker.py`: si falta un
      peso en la caché, `from_pretrained` falla en vez de salir a huggingface.co.
    - Y un segundo cinturón que el de voz no tiene: `socket.connect` y `getaddrinfo` rechazan todo lo que no sea
      loopback, antes de que salga un solo paquete. Así ni una biblioteca que ignore esas variables ni una
      resolución de nombres saca nada del PC (decisión 6). Se prueba en `tests/escena/test_obrero.py`, con el
      control de que loopback sí conecta.
    """
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if getattr(socket.socket.connect, "_sin_red", False):
        return

    def _corta(destino) -> OSError:
        return OSError(f"{MARCA_SIN_RED} el obrero de escena no sale del PC: conexión a {destino!r}")

    connect, connect_ex, getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def _connect(self, direccion):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _es_local(direccion[0]):
            raise _corta(direccion)
        return connect(self, direccion)

    def _connect_ex(self, direccion):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _es_local(direccion[0]):
            raise _corta(direccion)
        return connect_ex(self, direccion)

    def _getaddrinfo(host, *args, **kwargs):
        if host is not None and not _es_local(host) and not _es_literal(host):
            raise _corta(host)
        return getaddrinfo(host, *args, **kwargs)

    for f in (_connect, _connect_ex, _getaddrinfo):
        f._sin_red = True  # type: ignore[attr-defined]
    socket.socket.connect = _connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = _getaddrinfo  # type: ignore[assignment]


def _exige_cuda() -> str:
    import torch

    if not torch.cuda.is_available():
        raise SystemExit(
            "[FAIL] torch.cuda.is_available() == False en .venv-escena: sin GPU, Real-ESRGAN y SAM tardan minutos "
            "por imagen. Reconstruye el venv con torch de CUDA (spikes/requirements-escena.txt)"
        )
    return torch.cuda.get_device_name(0)


# ---------------------------------------------------------------------------------------------------------------
# Real-ESRGAN ×4 por teselas
# ---------------------------------------------------------------------------------------------------------------
def carga_esrgan(peso: str | Path, dispositivo: str):
    """Real-ESRGAN con spandrel, en `dispositivo` y en media precisión si es la GPU."""
    from spandrel import ModelLoader

    modelo = ModelLoader().load_from_file(str(peso))
    if getattr(modelo, "scale", 4) != 4:
        raise SystemExit(f"[FAIL] el peso {Path(peso).name} amplía ×{modelo.scale} y el obrero espera ×4")
    modelo = modelo.to(dispositivo).eval()
    return modelo.half() if dispositivo == "cuda" else modelo


def escala_x4(img: Image.Image, modelo, tesela: int, solape: int, dispositivo: str, medio: bool) -> Image.Image:
    """Amplía ×4 por teselas, para no quedarse sin VRAM, fundiendo el solape con una rampa.

    La rampa hace que el borde de cada tesela (donde el modelo ve menos contexto) pese poco frente al interior de
    la vecina, así que no se ven costuras. `modelo` es cualquier cosa que reciba un tensor NCHW en 0-1 y devuelva
    el mismo ×4: así se prueba en CPU con una ampliación de referencia.
    """
    import torch

    a = np.asarray(img.convert("RGB")).astype(np.float32) / 255
    h, w = a.shape[:2]
    salida = np.zeros((h * 4, w * 4, 3), np.float32)
    peso = np.zeros((h * 4, w * 4, 1), np.float32)
    paso = tesela - 2 * solape
    if paso <= 0:
        raise ValueError(f"la tesela ({tesela}) tiene que ser mayor que dos solapes ({solape})")
    for y0 in range(0, h, paso):
        for x0 in range(0, w, paso):
            ya, xa = max(0, y0 - solape), max(0, x0 - solape)
            yb, xb = min(h, y0 + paso + solape), min(w, x0 + paso + solape)
            t = torch.from_numpy(a[ya:yb, xa:xb]).permute(2, 0, 1)[None].to(dispositivo)
            if medio:
                t = t.half()
            with torch.no_grad():
                r = modelo(t).clamp(0, 1)[0].permute(1, 2, 0).float().cpu().numpy()
            ry = np.minimum(np.arange(r.shape[0]) + 1, np.arange(r.shape[0])[::-1] + 1)
            rx = np.minimum(np.arange(r.shape[1]) + 1, np.arange(r.shape[1])[::-1] + 1)
            m = np.minimum(np.minimum.outer(ry, rx), solape * 4).astype(np.float32)[..., None]
            salida[ya * 4 : yb * 4, xa * 4 : xb * 4] += r * m
            peso[ya * 4 : yb * 4, xa * 4 : xb * 4] += m
    return Image.fromarray((salida / np.maximum(peso, 1e-6) * 255 + 0.5).clip(0, 255).astype(np.uint8))


# ---------------------------------------------------------------------------------------------------------------
# SAM 2.1
# ---------------------------------------------------------------------------------------------------------------
def carga_sam(modelo_id: str, dispositivo: str):
    from transformers import Sam2Model, Sam2Processor

    proc = Sam2Processor.from_pretrained(modelo_id)
    modelo = Sam2Model.from_pretrained(modelo_id).to(dispositivo).eval()
    return proc, modelo


def logits_sam(img: Image.Image, pieza: dict, proc, modelo, dispositivo: str) -> np.ndarray:
    """Logits de SAM para un objeto (caja y puntos a favor y en contra), al tamaño de la imagen."""
    import torch

    puntos = list(pieza.get("pos") or []) + list(pieza.get("neg") or [])
    etiquetas = [1] * len(pieza.get("pos") or []) + [0] * len(pieza.get("neg") or [])
    datos = {"images": img, "input_boxes": [[pieza["caja"]]], "return_tensors": "pt"}
    if puntos:
        datos.update(input_points=[[puntos]], input_labels=[[etiquetas]])
    entrada = proc(**datos).to(dispositivo)
    with torch.no_grad():
        salida = modelo(**entrada, multimask_output=False)
    logits = proc.post_process_masks(salida.pred_masks.cpu(), entrada["original_sizes"].cpu(), binarize=False)[0]
    return logits[0, 0].float().numpy()


# ---------------------------------------------------------------------------------------------------------------
# Las operaciones
# ---------------------------------------------------------------------------------------------------------------
class Taller:
    """Los modelos cargados (una vez, al primer uso) y las carpetas del trabajo."""

    def __init__(self, job: dict, dispositivo: str):
        self.job = job
        self.dispositivo = dispositivo
        self.img_dir = Path(job["img_dir"])
        self.src_dir = str(job["src_dir"]).rstrip("/")
        self._esrgan = None
        self._sam = None
        self.modelos: dict = {}

    @property
    def esrgan(self):
        if self._esrgan is None:
            cfg = self.job["esrgan"]
            t0 = time.perf_counter()
            self._esrgan = carga_esrgan(cfg["peso"], self.dispositivo)
            import spandrel

            self.modelos["esrgan"] = {
                "peso": Path(cfg["peso"]).name,
                "sha256": hashlib.sha256(Path(cfg["peso"]).read_bytes()).hexdigest(),
                "arquitectura": type(self._esrgan.model).__name__,
                "spandrel": spandrel.__version__,
                "carga_s": round(time.perf_counter() - t0, 2),
            }
        return self._esrgan

    @property
    def sam(self):
        if self._sam is None:
            modelo_id = self.job["sam"]["modelo"]
            t0 = time.perf_counter()
            self._sam = carga_sam(modelo_id, self.dispositivo)
            import transformers

            self.modelos["sam"] = {
                "modelo": modelo_id,
                "revision": getattr(self._sam[1].config, "_commit_hash", None),
                "transformers": transformers.__version__,
                "carga_s": round(time.perf_counter() - t0, 2),
            }
        return self._sam

    def amplia(self, img: Image.Image) -> Image.Image:
        cfg = self.job["esrgan"]
        return escala_x4(img, self.esrgan, cfg["tesela"], cfg["solape"], self.dispositivo, self.dispositivo == "cuda")

    def guarda(self, nombre: str, trozo: np.ndarray) -> tuple[str, Path]:
        self.img_dir.mkdir(parents=True, exist_ok=True)
        ruta = self.img_dir / f"{nombre}.png"
        Image.fromarray(trozo, "RGBA").save(ruta, optimize=True)
        return f"{self.src_dir}/{ruta.name}", ruta


def op_recorta(op: dict, taller: Taller) -> dict:
    with Image.open(op["origen"]) as im:
        img = im.convert("RGB")
    e = recorte.ESCALA_RECORTE
    grande = taller.amplia(img).resize((img.width * e, img.height * e), Image.LANCZOS)
    rgba = recorte.quita_magenta(np.asarray(grande).astype(np.float32))
    con_mascaras = recorte.piezas(rgba, con_mascara=True)
    cajas = [c for c, _ in con_mascaras]
    mascaras = dict(con_mascaras)
    if op.get("sitios"):
        try:
            elegidas = recorte.reparte_por_sitios(con_mascaras, op["sitios"], e)
        except recorte.ErrorDeRecorte as error:
            raise recorte.ErrorDeRecorte(f"{op['nombre']}: {error}") from None
    elif op.get("piezas"):
        orden = recorte.orden_lectura(cajas)
        if len(orden) != len(op["piezas"]):
            raise recorte.ErrorDeRecorte(
                f"{op['nombre']}: se esperaban {len(op['piezas'])} figuras ({', '.join(op['piezas'])}) y la imagen "
                f"tiene {len(orden)}. No se reparte a ciegas: revisa la imagen o la lista"
            )
        elegidas = [(n, c, mascaras[c]) for n, c in zip(op["piezas"], orden)]
    else:
        elegidas = [(op["nombre"], recorte.union(cajas), None)]
    k = 1.0
    if op.get("k_de"):
        caja_k = next((c for n, c, _ in elegidas if n == op["k_de"]), None)
        if caja_k is None:
            raise recorte.ErrorDeRecorte(
                f"{op['nombre']}: la k sale de «{op['k_de']}», que no es ninguna de sus figuras"
            )
        k = (caja_k[3] - caja_k[1]) / float(op["alto_k"])
    centradas, anclas = set(op.get("centradas") or []), op.get("anclas") or {}
    entradas, archivos = {}, {}
    for nombre, caja, mascara in elegidas:
        trozo, donde = recorte.recorta_caja(rgba, caja, mascara)
        if nombre in anclas:
            punto = (anclas[nombre][0] - donde[0], anclas[nombre][1] - donde[1])
        else:
            punto = recorte.apoyo(trozo, nombre in centradas)
        src, ruta = taller.guarda(nombre, trozo)
        entradas[nombre] = recorte.entrada(src, trozo, donde, punto, k)
        archivos[nombre] = str(ruta)
    return {"entradas": entradas, "archivos": archivos, "ampliada": f"{grande.width}x{grande.height}"}


def op_fondo(op: dict, taller: Taller) -> dict:
    with Image.open(op["origen"]) as im:
        img = im.convert("RGB")
    grande = taller.amplia(img)
    ancho = int(op.get("ancho") or img.width * recorte.ESCALA_RECORTE)
    grande = grande.resize((ancho, round(grande.height * ancho / grande.width)), Image.LANCZOS)
    taller.img_dir.mkdir(parents=True, exist_ok=True)
    ruta = taller.img_dir / f"{op['nombre']}.jpg"
    grande.save(ruta, quality=92)
    e = {
        "src": f"{taller.src_dir}/{ruta.name}",
        "w": grande.width,
        "h": grande.height,
        "ax": 0,
        "ay": 0,
        "ox": 0,
        "oy": 0,
    }
    return {"entradas": {op["nombre"]: e}, "archivos": {op["nombre"]: str(ruta)}}


def rellena(rgba: np.ndarray, hueco: np.ndarray, taller: Taller) -> np.ndarray:
    """La imagen con el hueco que dejan las piezas pintado otra vez con lo que lo rodea (OpenCV, inpaint de Telea).

    Para la base de un FONDO (F6.6): una pieza que se separa de una lámina para moverse aparte (un primer término
    que da paralaje, una hoja que se abre) deja detrás un hueco, y con la cámara o la pieza en movimiento se
    vería. El hueco se ensancha `RELLENO_MARGEN_PX` para que el borde suavizado de la pieza no deje un halo. El
    alfa no cambia: una base opaca sigue opaca.
    """
    import cv2
    from scipy import ndimage

    mascara = ndimage.binary_dilation(hueco > 0.02, iterations=RELLENO_MARGEN_PX).astype(np.uint8) * 255
    rgb = np.ascontiguousarray(rgba[..., :3])
    lleno = cv2.inpaint(rgb, mascara, RELLENO_RADIO_PX, cv2.INPAINT_TELEA)
    taller.modelos.setdefault("opencv", {"version": cv2.__version__, "metodo": "inpaint Telea"})
    salida = rgba.copy()
    salida[..., :3] = lleno
    return salida


def rellena_con(rgba: np.ndarray, hueco: np.ndarray, limpia: np.ndarray) -> np.ndarray:
    """La imagen con el hueco de las piezas tomado de `limpia`: la misma lámina sin ellas, del mismo tamaño (F6.6).

    Telea emborrona un hueco grande o con textura: en la muestra de F6.6 dejó «una sombra borrosa al lado de la cuerda y
    cerca de la cortina» (la revisión de la muestra). Si hay una lámina limpia —la misma sala sin esas piezas, editada
    por Qwen en su sitio—, el hueco se toma de ella. El borde se funde en `RELLENO_FUNDIDO_PX` para que no se vea la
    costura, y el hueco se ensancha como en `rellena`. El alfa no cambia.
    """
    from scipy import ndimage

    if limpia.shape[:2] != rgba.shape[:2]:
        raise ValueError(
            f"la lámina limpia mide {limpia.shape[1]}x{limpia.shape[0]} y la base {rgba.shape[1]}x{rgba.shape[0]}"
        )
    zona = ndimage.binary_dilation(hueco > 0.02, iterations=RELLENO_MARGEN_PX).astype(np.float32)
    a = np.clip(ndimage.gaussian_filter(zona, RELLENO_FUNDIDO_PX), 0, 1)[..., None]
    salida = rgba.copy()
    mezcla = rgba[..., :3].astype(np.float32) * (1 - a) + limpia[..., :3].astype(np.float32) * a
    salida[..., :3] = np.clip(np.rint(mezcla), 0, 255).astype(np.uint8)
    return salida


def desplazada(rgba: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """La imagen corrida: en cada píxel, lo que había a (dx, dy) px. Un tampón de clonar para `rellena_con`.

    Los bordes dan la vuelta (`np.roll`): un desplazamiento que lleve la fuente fuera del cuadro trae píxeles del lado
    contrario. Lo elige quien escribe el guion, sobre la rejilla, dentro de la imagen.
    """
    return np.roll(rgba, shift=(-int(dy), -int(dx)), axis=(0, 1))


# El hueco de una pieza se ensancha esto antes de rellenarlo, y el inpaint mira a esta distancia (px de la base).
RELLENO_MARGEN_PX = 6
RELLENO_RADIO_PX = 12
# Con una lámina limpia, el paso de la base a ella se funde en esta anchura (sigma del desenfoque, px de la base).
RELLENO_FUNDIDO_PX = 3.0


def op_separa(op: dict, taller: Taller) -> dict:
    ruta = taller.img_dir / op["archivo"]
    rgba = recorte.abre_figura(ruta)
    alfa = rgba[..., 3].astype(np.float32) / 255
    plano = recorte.plano_gris(rgba)
    guia = plano.mean(axis=2) / 255
    vista = Image.fromarray(plano.astype(np.uint8))
    proc, modelo = taller.sam
    base = dict(op["base"])
    resto = rgba.copy()
    hueco = np.zeros(alfa.shape, np.float32)
    entradas, archivos = {}, {}
    for pieza in op["piezas"]:
        logits = logits_sam(vista, pieza, proc, modelo, taller.dispositivo)
        m = recorte.suaviza(recorte.mascara_afinada(logits, guia) * alfa)
        nombre = f"{op['nombre']}_{pieza['nombre']}"
        trozo, e = recorte.separa_pieza(rgba, m, tuple(pieza["pivote"]), base, "")
        src, destino = taller.guarda(nombre, trozo)
        # De qué figura sale: la escala de cabezas le pasa el factor de ESA figura y de ninguna otra (auditoría de
        # F6.2c, recomendación 5). Por el prefijo del nombre, «a» se lo pasaba también a «a_manos_base».
        e["src"], e["de"] = src, op["nombre"]
        entradas[nombre], archivos[nombre] = e, str(destino)
        resto[..., 3] = (resto[..., 3].astype(np.float32) * (1 - m)).astype(np.uint8)
        hueco = np.maximum(hueco, m)
    if op.get("quita_de_la_base"):
        nombre = f"{op['nombre']}_base"
        if op.get("relleno"):
            resto = rellena_con(rgba, hueco, recorte.abre_figura(taller.img_dir / op["relleno"]))
        elif op.get("relleno_desplazado"):
            resto = rellena_con(rgba, hueco, desplazada(rgba, *op["relleno_desplazado"]))
        elif op.get("rellena_base"):
            resto = rellena(rgba, hueco, taller)
        src, destino = taller.guarda(nombre, resto)
        entradas[nombre], archivos[nombre] = {**base, "src": src, "de": op["nombre"]}, str(destino)
    return {"entradas": entradas, "archivos": archivos}


OPERACIONES = {"recorta": op_recorta, "fondo": op_fondo, "separa": op_separa}


def main() -> int:
    parser = argparse.ArgumentParser(description="Obrero de activos del motor de escena (se ejecuta en .venv-escena)")
    parser.add_argument("--trabajo", required=True)
    parser.add_argument("--resultado", required=True)
    args = parser.parse_args()

    job = json.loads(Path(args.trabajo).read_text(encoding="utf-8"))
    desconocidas = sorted({op.get("op") for op in job["operaciones"]} - set(OPERACIONES))
    if desconocidas:
        raise SystemExit(f"[FAIL] operaciones que el obrero no sabe hacer: {desconocidas} ({', '.join(OPERACIONES)})")
    _sin_red()
    gpu = _exige_cuda()

    import torch

    taller = Taller(job, "cuda")
    resultado = {"dispositivo": "cuda", "gpu": gpu, "torch": torch.__version__, "modelos": taller.modelos}
    resultado["operaciones"] = []
    destino = Path(args.resultado)
    destino.parent.mkdir(parents=True, exist_ok=True)
    for numero, op in enumerate(job["operaciones"], start=1):
        t0 = time.perf_counter()
        hecho = OPERACIONES[op["op"]](op, taller)
        torch.cuda.synchronize()
        hecho.update(indice=numero - 1, op=op["op"], nombre=op["nombre"], origen=op.get("origen") or op.get("archivo"))
        hecho["segundos"] = round(time.perf_counter() - t0, 2)
        resultado["operaciones"].append(hecho)
        resultado["vram_pico_mb"] = round(torch.cuda.max_memory_reserved() / 1024**2)
        print(f"  [{numero}/{len(job['operaciones'])}] {op['op']} {op['nombre']}: {hecho['segundos']} s", flush=True)
        # Se vuelca en cada vuelta: si el proceso muere, lo ya hecho queda contabilizado.
        destino.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
