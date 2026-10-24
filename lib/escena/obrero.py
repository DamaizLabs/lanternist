"""El cliente del obrero de activos del motor de escena (F6.2c): prepara el trabajo, lanza `.venv-escena` y apunta.

Mismo patrón que `lib/voice_client.py` + `lib/voice_worker.py`: este módulo corre en el `.venv` del pipeline, arma
un trabajo en JSON y lanza `lib/escena/obrero_worker.py` con el intérprete de `.venv-escena` (torch, Real-ESRGAN,
SAM 2.1). Lo que vuelve lo apunta en dos sitios:

- **El catálogo** (`<activos>/catalogo.json`): una entrada por imagen con el esquema que consume `compone.py`
  (`src`, `w`, `h`, `ax`, `ay`, `ox`, `oy`, `k` y, tras `escala`, `k0`, `cabeza`, `cabeza_px` y `vista`).
  Las imágenes quedan en `<activos>/img/` y su `src` es `assets/img/<nombre>`, su sitio en la composición:
  `archivos_para_compone` da el mapa que pide `compone.compone`.
- **La procedencia** (decisión 5): cada imagen que escribe el obrero es un DERIVADO de otra (la que generó Qwen,
  o un recorte que luego separa SAM), así que se anota en `generacion-imagenes.json` junto a ella, con su
  origen, las herramientas que la tocaron, la licencia de cada una y de dónde salen sus pesos.
  `provenance.sync` la recoge sin saber que existe, igual que los derivados de la marca del canal.

**La escala de las cabezas corre aquí y no en el trabajador**: no necesita GPU, solo las imágenes ya recortadas y
lo que el canal sabe de cada figura (de quién es, de qué lado se ve, si está de pie), que llega como `Figura`.

**La GPU va de una en una** (regla 5 del plan de F6.2): antes de lanzar el trabajador se comprueba con
`nvidia-smi` que no hay otro trabajo del estudio en la tarjeta y que queda la memoria del umbral.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from lib import config, provenance
from lib.escena import recorte
from lib.escena.comprobaciones import UMBRAL_ESCALA_CABEZA
from lib.escena.encuadre import ALTO_CABEZA
from lib.escena.render import ErrorDeRender, exige_gpu_libre, suelta_cerrojo, toma_cerrojo

CATALOGO = "catalogo.json"
IMG = "img"
# El sitio de las imágenes dentro de la composición de HyperFrames (`compone` copia cada una a su `src`).
SRC_DIR = "assets/img"
REGISTRO = provenance.IMAGE_RECORDS_FILENAME

# Los modelos que usa el obrero: su licencia y de dónde salen sus pesos (decisión 5).
# - Real-ESRGAN: el `.pth` es el que publica el repositorio de su autor (xinntao) y el mismo que usa ComfyUI; su
#   licencia es la del repositorio, BSD-3-Clause.
# - SAM 2.1: pesos y código de Meta bajo Apache-2.0, bajados a la caché de Hugging Face (`facebook/sam2.1-hiera-
#   large`) el 26-09 para video_1.
MODELOS = {
    "esrgan": {
        "nombre": "Real-ESRGAN x4plus anime 6B",
        "licencia": "BSD-3-Clause",
        "url": "https://github.com/xinntao/Real-ESRGAN",
    },
    "sam": {
        "nombre": "SAM 2.1 hiera-large",
        "licencia": "Apache-2.0",
        "url": "https://huggingface.co/facebook/sam2.1-hiera-large",
    },
    # - OpenCV: no es un modelo sino el algoritmo de Telea (`cv2.inpaint`), que rellena el hueco de una pieza separada
    #   de un fondo (F6.6). Va en el paquete opencv-python de los dos entornos, bajo Apache-2.0.
    "opencv": {
        "nombre": "OpenCV inpaint (Telea)",
        "licencia": "Apache-2.0",
        "url": "https://github.com/opencv/opencv",
    },
}
# Las operaciones que sabe hacer el trabajador (`obrero_worker.OPERACIONES`, que no se importa aquí: vive en otro
# entorno). Las claves de HERRAMIENTAS son más, porque una base rellenada se apunta con su propia procedencia.
OPERACIONES = ("recorta", "fondo", "separa")
# Qué modelos toca cada operación, y qué hace, para la procedencia.
HERRAMIENTAS = {
    "recorta": ("esrgan",),
    "fondo": ("esrgan",),
    "separa": ("sam",),
    "separa_rellena": ("sam", "opencv"),
    "separa_rellena_con": ("sam",),
    "separa_rellena_desplazada": ("sam",),
}
QUE_HACE = {
    "recorta": "ampliada ×4 con Real-ESRGAN, bajada a ×2, fondo de croma quitado por tono y recortada con su apoyo",
    "fondo": "ampliada ×4 con Real-ESRGAN y bajada a su ancho de trabajo, sin recortar",
    "separa": "pieza o base separada con SAM 2.1 por caja y puntos, borde afinado con filtro guiado",
    "separa_rellena": (
        "base sin las piezas que separó SAM 2.1 por caja y puntos, con su hueco pintado otra vez con lo que lo rodea "
        "(OpenCV, inpaint de Telea)"
    ),
    "separa_rellena_con": (
        "base sin las piezas que separó SAM 2.1 por caja y puntos, con su hueco tomado de una lámina limpia (la misma "
        "sin esas piezas) y fundido en el borde"
    ),
    "separa_rellena_desplazada": (
        "base sin las piezas que separó SAM 2.1 por caja y puntos, con su hueco tomado de la misma imagen a unos px "
        "(un tampón de clonar) y fundido en el borde"
    ),
}


class ErrorDelObrero(RuntimeError):
    """El obrero no pudo hacer el trabajo, o se le pide algo que no sabe hacer. No se reintenta."""


@dataclass(frozen=True)
class Figura:
    """Lo que el canal sabe de una figura para medir su cabeza (lo declara el canal, sin defecto).

    - `pj`: de qué personaje es.
    - `vista`: «frente» o «perfil»; de frente se ve menos pelo que de perfil y no se comparan entre sí.
    - `de_pie`: las figuras de pie son la referencia de su personaje y vista.
    - `base`: la postura limpia de la que sale una variante (hereda su factor), o None.
    - `mide_cabeza`: False si su cabeza no se puede medir por el pelo (un perro, cuyo pelo es todo el cuerpo);
      entonces su `cabeza_px` va a null, que la comprobación de escala entiende como «no se mide».
    """

    pj: str
    vista: str
    de_pie: bool
    base: str | None
    mide_cabeza: bool


# ---------------------------------------------------------------------------------------------------------------
# Las operaciones
# ---------------------------------------------------------------------------------------------------------------
def recorta(
    nombre: str,
    origen: str | Path,
    *,
    piezas: Sequence[str] | None = None,
    sitios: Mapping[str, Sequence[float]] | None = None,
    k_de: str | None = None,
    alto_k: float | None = None,
    centradas: Sequence[str] | None = None,
    anclas: Mapping[str, Sequence[float]] | None = None,
) -> dict:
    """Recortar una imagen generada sobre croma.

    - Sin `piezas` ni `sitios`: UNA figura, `nombre`, con k = 1 (las posturas ya salen a la escala del lienzo).
    - `piezas`: varias figuras, nombradas por orden de lectura (una hoja de personaje: de frente y de perfil).
    - `sitios`: varias figuras, cada una por el centro que el canal le da, en px de la imagen generada.
    - `k_de` + `alto_k`: la k de todas sale de la altura de esa figura: k = alto / `alto_k` (la figura de pie de
      una hoja, contra lo que mide de pie una postura recortada).
    """
    if piezas and sitios:
        raise ErrorDelObrero(f"{nombre}: o piezas por orden de lectura o por su sitio, no las dos")
    if (k_de is None) != (alto_k is None):
        raise ErrorDelObrero(f"{nombre}: la k de una figura necesita las dos cosas, `k_de` y `alto_k`")
    nombres = list(piezas or sitios or [nombre])
    if k_de is not None and k_de not in nombres:
        raise ErrorDelObrero(f"{nombre}: la k sale de «{k_de}», que no es ninguna de sus figuras ({nombres})")
    op = {"op": "recorta", "nombre": nombre, "origen": str(origen)}
    if piezas:
        op["piezas"] = list(piezas)
    if sitios:
        op["sitios"] = {n: [float(x), float(y)] for n, (x, y) in sitios.items()}
    if k_de is not None:
        op.update(k_de=k_de, alto_k=float(alto_k))
    if centradas:
        op["centradas"] = list(centradas)
    if anclas:
        op["anclas"] = {n: [float(x), float(y)] for n, (x, y) in anclas.items()}
    return op


def fondo(nombre: str, origen: str | Path, *, ancho: int | None = None, del_episodio: bool = False) -> dict:
    """Un fondo entero, ampliado y sin recortar. Sin `ancho`, a ESCALA_RECORTE veces el generado.

    `del_episodio` (F6.6): el fondo es una lámina de ESTE run (un canal que pone en escena sus láminas) y no vale
    para otro episodio. Su entrada de catálogo lo lleva, y también la de lo que se separe de él, así que
    `biblia.incorpora` no los mete en la biblioteca del canal, que está en git.
    """
    op = {"op": "fondo", "nombre": nombre, "origen": str(origen)}
    if ancho is not None:
        op["ancho"] = int(ancho)
    if del_episodio:
        op["del_episodio"] = True
    return op


def separa(
    nombre: str,
    archivo: str,
    base: Mapping,
    piezas: Sequence[Mapping],
    *,
    quita_de_la_base: bool,
    rellena_base: bool = False,
    relleno: str | None = None,
    relleno_desplazado: tuple[int, int] | None = None,
) -> dict:
    """Separar con SAM piezas que se mueven solas de una imagen ya recortada (`<activos>/img/<archivo>`).

    Cada pieza: `nombre`, `caja` [x0, y0, x1, y1], `pos` y `neg` (puntos [x, y] a favor y en contra) y `pivote`
    [x, y], todo en px de esa imagen. `base` es su entrada de catálogo. Con `quita_de_la_base`, sale además
    `<nombre>_base`: la imagen sin las piezas. Cada pieza y la base llevan `de: <nombre>` en su entrada.

    `rellena_base` (F6.6): el hueco de la base se pinta con lo que lo rodea en vez de quedar transparente. Es para
    un FONDO: la lámina sigue a la vista detrás de la pieza que se mueve (un primer término con paralaje, una hoja
    que se abre), y un hueco transparente dejaría ver el color del plano.

    `relleno`: el hueco se toma de esa imagen de `<activos>/img/` en vez de pintarlo con OpenCV. Es la misma lámina
    sin las piezas (una edición de Qwen en su sitio, ampliada con `fondo`), del mismo tamaño que la base. Implica
    `rellena_base`.

    `relleno_desplazado` (dx, dy): el hueco se toma de la misma imagen a esa distancia, como un tampón de clonar. Para
    un resto pequeño pegado a un contorno oscuro, donde Telea arrastra el oscuro y la lámina limpia trae lo suyo (el
    nudo de una mesa junto a la pera cerrada, F6.6). Implica `rellena_base`. Los bordes dan la vuelta: la fuente
    tiene que caer dentro de la imagen.
    """
    rellenos = [r for r in (relleno, relleno_desplazado) if r]
    if (rellena_base or rellenos) and not quita_de_la_base:
        raise ErrorDelObrero(f"{nombre}: rellenar la base exige quitarle las piezas (quita_de_la_base)")
    if len(rellenos) > 1:
        raise ErrorDelObrero(f"{nombre}: el hueco se toma de una lámina limpia o de la misma desplazada, no de las dos")
    for p in piezas:
        falta = [c for c in ("nombre", "caja", "pivote") if c not in p]
        if falta:
            raise ErrorDelObrero(f"{nombre}: a una pieza le falta {falta}")
        if not (p.get("pos") or p.get("neg")) and not p.get("caja"):
            raise ErrorDelObrero(f"{nombre}/{p['nombre']}: SAM necesita una caja o puntos")
    return {
        "op": "separa",
        "nombre": nombre,
        "archivo": archivo,
        "base": dict(base),
        "piezas": [dict(p) for p in piezas],
        "quita_de_la_base": bool(quita_de_la_base),
        **({"rellena_base": True} if rellena_base or rellenos else {}),
        **({"relleno": str(relleno)} if relleno else {}),
        **(
            {"relleno_desplazado": [int(relleno_desplazado[0]), int(relleno_desplazado[1])]}
            if relleno_desplazado
            else {}
        ),
    }


# ---------------------------------------------------------------------------------------------------------------
# El catálogo
# ---------------------------------------------------------------------------------------------------------------
def lee_catalogo(dir_activos: str | Path) -> dict:
    ruta = Path(dir_activos) / CATALOGO
    if not ruta.exists():
        return {"imagenes": {}}
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, dict) or not isinstance(datos.get("imagenes"), dict):
        raise ErrorDelObrero(f"{ruta} no tiene la forma de un catálogo ({{'imagenes': {{...}}}})")
    return datos


def guarda_catalogo(dir_activos: str | Path, catalogo: Mapping) -> Path:
    ruta = Path(dir_activos) / CATALOGO
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".json.tmp")
    temporal.write_text(json.dumps(catalogo, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    temporal.replace(ruta)
    return ruta


def archivo_de(dir_activos: str | Path, entrada: Mapping) -> Path:
    """El fichero de una entrada del catálogo en la carpeta de activos."""
    return Path(dir_activos) / IMG / Path(str(entrada["src"])).name


def archivos_para_compone(dir_activos: str | Path) -> dict[str, Path]:
    """{src: fichero} de todo el catálogo: el mapa de assets que pide `compone.compone`."""
    return {d["src"]: archivo_de(dir_activos, d) for d in lee_catalogo(dir_activos)["imagenes"].values()}


# ---------------------------------------------------------------------------------------------------------------
# La procedencia de lo que escribe el obrero
# ---------------------------------------------------------------------------------------------------------------
def muestra(ruta: Path, ancla: Path | None = None) -> str:
    """Una ruta para el registro, sin rutas personales: relativa a `ancla` (el run), al repositorio o solo el nombre.

    El run puede vivir fuera del repositorio (`RUTA_VIDEOS`), y entonces «relativa al run» es lo que dice de qué
    imagen del mismo run sale un derivado.
    """
    for base in (ancla, config.BASE_DIR):
        if base is None:
            continue
        try:
            return Path(ruta).resolve().relative_to(Path(base).resolve()).as_posix()
        except ValueError:
            continue
    return Path(ruta).name


def registro_de_origen(origen: Path) -> dict | None:
    """El registro de procedencia de una imagen, en el `generacion-imagenes.json` de su carpeta, o None."""
    sidecar = origen.parent / REGISTRO
    if not sidecar.exists():
        return None
    try:
        registros = json.loads(sidecar.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    candidatos = [r for r in registros if isinstance(r, dict) and Path(str(r.get("file", ""))).name == origen.name]
    return candidatos[-1] if candidatos else None


def registro_derivado(
    archivo: Path,
    origen: Path,
    *,
    quien: str,
    que_hace: str,
    usadas: Sequence[Mapping],
    detalle: Mapping,
    ancla: Path | None = None,
) -> dict:
    """El registro de procedencia de una imagen DERIVADA de `origen` en local, con la forma de `comfy_client`.

    - `quien`: qué la produjo (un proceso del estudio, sin red); `que_hace`: qué se le hizo.
    - `usadas`: los modelos que tocaron sus píxeles (de `MODELOS`), con su licencia y su url; vacío si solo fue
      Pillow o numpy.
    - La licencia empieza por la del ORIGEN: si el origen no tiene registro, dice «desconocida» y el conteo de
      `provenance` la lista entre las licencias por cerrar, en vez de esconderla detrás de la de una herramienta.
    - La url es la del origen (el modelo que dibujó la imagen) y detrás la de cada herramienta.
    - `ancla`: la carpeta respecto a la que se escribe de dónde sale (el run); sin ella, el repositorio.
    """
    previo = registro_de_origen(origen)
    if previo is None:
        modelo_origen = "origen sin registro de procedencia"
        licencia_origen = f"desconocida: {origen.name} no tiene registro de procedencia"
        urls = []
    else:
        modelo_origen = str(previo.get("modelo") or "desconocido")
        licencia_origen = str(previo.get("licencia") or "desconocida")
        urls = [u for u in str(previo.get("url") or "").split(" · ") if u]
    urls += [m["url"] for m in usadas if m["url"] not in urls]
    with Image.open(archivo) as im:
        resolucion = f"{im.size[0]}x{im.size[1]}"
    herramientas = " + ".join(m["nombre"] for m in usadas) or "derivación local sin modelo"
    licencia = licencia_origen + (
        " · herramientas: " + ", ".join(f"{m['nombre']} ({m['licencia']})" for m in usadas) if usadas else ""
    )
    return {
        "file": str(archivo),
        "fuente": f"derivado en local de {muestra(origen, ancla)} por {quien} (sin red)",
        "modelo": f"{modelo_origen} → {herramientas}",
        "licencia": licencia,
        "url": " · ".join(urls) or None,
        "origen": f"derivado de {origen.name}: {que_hace}",
        "derivado_de": muestra(origen, ancla),
        "resolucion": resolucion,
        **dict(detalle),
        **({"seed": previo["seed"]} if previo and "seed" in previo else {}),
        "metadatos_png": "guardado sin metadatos de generación",
    }


def registro_del_derivado(
    archivo: Path, origen: Path, operacion: str, herramientas: Mapping, ancla: Path | None = None
) -> dict:
    """El registro de una imagen que escribió el obrero con una de sus operaciones."""
    return registro_derivado(
        archivo,
        origen,
        quien="el obrero de escena (lib/escena/obrero.py en .venv-escena)",
        que_hace=QUE_HACE[operacion],
        usadas=[MODELOS[m] for m in HERRAMIENTAS[operacion]],
        detalle={
            "operacion": operacion,
            "herramientas": {m: dict(herramientas.get(m) or {}) for m in HERRAMIENTAS[operacion]},
        },
        ancla=ancla,
    )


def base_rellenada(op: Mapping) -> bool:
    """Si una operación deja una base con el hueco rellenado: la misma condición con que rellena el trabajador."""
    return (
        op.get("op") == "separa"
        and bool(op.get("quita_de_la_base"))
        and bool(op.get("rellena_base") or op.get("relleno") or op.get("relleno_desplazado"))
    )


def _con_relleno(registro: dict, relleno: Path, ancla: Path) -> dict:
    """El registro de una base cuyo hueco viene de otra imagen: suma la licencia y la url de esa imagen (decisión 5).

    Sin registro de la imagen limpia, su licencia queda «desconocida» y el conteo de `provenance` la lista entre las
    licencias por cerrar, igual que un origen sin registro.
    """
    previo = registro_de_origen(relleno)
    licencia = str(previo.get("licencia") or "desconocida") if previo else f"desconocida: {relleno.name} sin registro"
    urls = [u for u in str(registro.get("url") or "").split(" · ") if u]
    urls += [u for u in str((previo or {}).get("url") or "").split(" · ") if u and u not in urls]
    return {
        **registro,
        "licencia": f"{registro['licencia']} · relleno ({relleno.name}): {licencia}",
        "url": " · ".join(urls) or None,
        "relleno_con": muestra(relleno, ancla),
    }


def apunta(resultado: Mapping, operaciones: Sequence[Mapping], dir_activos: Path) -> list[str]:
    """Mete lo que hizo el obrero en el catálogo y en la procedencia. Devuelve los nombres apuntados.

    Los registros se escriben operación a operación: si un trabajo recorta una figura y la siguiente operación
    parte de ese recorte, el derivado encuentra ya el registro de su origen.
    """
    catalogo = lee_catalogo(dir_activos)
    apuntados = []
    for hecho in resultado.get("operaciones") or []:
        op = operaciones[hecho["indice"]]
        origen = Path(op["origen"]) if op["op"] != "separa" else Path(dir_activos) / IMG / op["archivo"]
        registros = []
        # Un fondo del episodio (una lámina del run) lo dice en su entrada, y lo que se separa de él lo hereda: por la
        # `base` que le pasa el canal o por la entrada de la imagen de la que parte, que una operación anterior del
        # mismo trabajo ya apuntó (revisión del commit de F6.6, R1).
        del_episodio = op.get("del_episodio") or (
            op["op"] == "separa"
            and (
                dict(op.get("base") or {}).get("del_episodio")
                or catalogo["imagenes"].get(Path(op["archivo"]).stem, {}).get("del_episodio")
            )
        )
        for nombre, e in hecho["entradas"].items():
            if del_episodio:
                e = {**e, "del_episodio": True}
            catalogo["imagenes"][nombre] = e
            # La base rellenada la tocó también OpenCV, o lleva píxeles de una lámina limpia, y su procedencia lo
            # dice; las piezas, solo SAM. La condición es la misma con que rellena el trabajador (R2).
            rellenada = base_rellenada(op) and nombre == f"{op['nombre']}_base"
            operacion = op["op"]
            if rellenada:
                operacion = (
                    "separa_rellena_con"
                    if op.get("relleno")
                    else "separa_rellena_desplazada"
                    if op.get("relleno_desplazado")
                    else "separa_rellena"
                )
            registro = registro_del_derivado(
                Path(hecho["archivos"][nombre]),
                origen,
                operacion,
                resultado.get("modelos") or {},
                ancla=Path(dir_activos).parent,
            )
            if rellenada and op.get("relleno"):
                registro = _con_relleno(registro, Path(dir_activos) / IMG / op["relleno"], Path(dir_activos).parent)
            registros.append(registro)
            apuntados.append(nombre)
        provenance.anade_registros(Path(dir_activos) / IMG / REGISTRO, registros)
    guarda_catalogo(dir_activos, catalogo)
    return apuntados


# ---------------------------------------------------------------------------------------------------------------
# Lanzar el trabajador
# ---------------------------------------------------------------------------------------------------------------
def _sello() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _lanza(trabajo: Path, resultado: Path, log: Path) -> int:
    """Lanza el trabajador en `.venv-escena`, sin las claves del `.env` y sin red. Devuelve su código.

    Mientras corre, su proceso tiene tomado el cerrojo del obrero (`config.ESCENA_CERROJO_OBRERO`): así otro obrero,
    un render o una generación que se lancen a la vez lo ven en `render.trabajos_de_gpu_en_marcha` y no arrancan
    encima (auditoría de F6.2c, recomendación 3). El cerrojo se suelta aunque el trabajador falle o se pase de tiempo,
    y si el proceso muere sin soltarlo, el siguiente que mire ve que su pid ya no vive y lo borra.
    """
    with open(log, "w", encoding="utf-8") as salida:
        proceso = subprocess.Popen(
            [
                config.ESCENA_PYTHON,
                str(config.OBRERO_ESCENA_WORKER),
                "--trabajo",
                str(trabajo),
                "--resultado",
                str(resultado),
            ],
            stdout=salida,
            stderr=subprocess.STDOUT,
            env=config.entorno_para_terceros(
                {"PYTHONUNBUFFERED": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
            ),
            cwd=str(config.BASE_DIR),
        )
        toma_cerrojo(config.ESCENA_CERROJO_OBRERO, proceso.pid, f"obrero de escena: {trabajo.name}")
        try:
            return proceso.wait(timeout=config.ESCENA_OBRERO_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proceso.kill()
            proceso.wait()
            raise
        finally:
            suelta_cerrojo(config.ESCENA_CERROJO_OBRERO, proceso.pid)


def ejecuta(operaciones: Sequence[Mapping], dir_activos: str | Path, dir_trabajo: str | Path) -> dict:
    """Hace las operaciones en `.venv-escena`, en serie, y las apunta en el catálogo y la procedencia.

    Sin reintentos: si el trabajador falla, se apunta lo que llegó a hacer (su resultado se vuelca tras cada
    operación, y sus imágenes ya están en disco: sin registro, el conteo de la decisión 5 las daría por assets
    sin procedencia) y se para con el final de su log.
    """
    if not operaciones:
        return {"operaciones": []}
    desconocidas = sorted({op.get("op") for op in operaciones} - set(OPERACIONES))
    if desconocidas:
        raise ErrorDelObrero(f"operaciones que el obrero no sabe hacer: {desconocidas}")
    if not Path(config.ESCENA_PYTHON).is_file():
        raise ErrorDelObrero(
            f"no está .venv-escena ({config.ESCENA_PYTHON}): se crea con los tres pasos de "
            "spikes/requirements-escena.txt"
        )
    if any(op["op"] in ("recorta", "fondo") for op in operaciones) and not Path(config.ESCENA_ESRGAN_PESO).is_file():
        raise ErrorDelObrero(f"no está el peso de Real-ESRGAN: {config.ESCENA_ESRGAN_PESO}")
    # Lo que escribe cada operación en img/: una separación puede partir de lo que escribe otra del mismo trabajo
    # (F6.6: la lámina que amplía `fondo` y de la que SAM separa una pieza), y el trabajador las hace en orden.
    producidos: set[str] = set()
    for op in operaciones:
        origen = Path(op["origen"]) if op["op"] != "separa" else Path(dir_activos) / IMG / op["archivo"]
        if not (op["op"] == "separa" and op["archivo"] in producidos) and not origen.is_file():
            raise ErrorDelObrero(
                f"{op['nombre']}: no existe la imagen de origen {origen}"
                + (" (una separación parte de un recorte que ya está en el catálogo)" if op["op"] == "separa" else "")
            )
        relleno = op.get("relleno")
        if relleno and relleno not in producidos and not (Path(dir_activos) / IMG / relleno).is_file():
            raise ErrorDelObrero(
                f"{op['nombre']}: no existe la lámina limpia del relleno, {relleno} (amplíala con `fondo` antes)"
            )
        if op["op"] == "fondo":
            producidos.add(f"{op['nombre']}.jpg")
        elif op["op"] == "recorta":
            producidos |= {f"{n}.png" for n in (op.get("piezas") or list(op.get("sitios") or []) or [op["nombre"]])}
        else:  # separa: sus piezas y, si la quita, su base (de la que otra separación puede quitar algo más)
            producidos |= {f"{op['nombre']}_{p['nombre']}.png" for p in op["piezas"]}
            if op.get("quita_de_la_base"):
                producidos.add(f"{op['nombre']}_base.png")
    try:
        exige_gpu_libre()
    except ErrorDeRender as e:
        raise ErrorDelObrero(str(e)) from None

    dir_activos, dir_trabajo = Path(dir_activos), Path(dir_trabajo)
    dir_trabajo.mkdir(parents=True, exist_ok=True)
    sello = _sello()
    trabajo = dir_trabajo / f"obrero-{sello}-trabajo.json"
    resultado_ruta = dir_trabajo / f"obrero-{sello}-resultado.json"
    log = dir_trabajo / f"obrero-{sello}.log"
    trabajo.write_text(
        json.dumps(
            {
                "esrgan": {
                    "peso": str(config.ESCENA_ESRGAN_PESO),
                    "tesela": config.ESCENA_ESRGAN_TESELA,
                    "solape": config.ESCENA_ESRGAN_SOLAPE,
                },
                "sam": {"modelo": config.ESCENA_SAM_MODELO},
                "img_dir": str(dir_activos / IMG),
                "src_dir": SRC_DIR,
                "operaciones": list(operaciones),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    codigo = _lanza(trabajo, resultado_ruta, log)
    resultado = json.loads(resultado_ruta.read_text(encoding="utf-8")) if resultado_ruta.exists() else {}
    apunta(resultado, operaciones, dir_activos)
    if codigo != 0:
        cola = log.read_text(encoding="utf-8", errors="replace")[-1500:] if log.exists() else ""
        hechas = len(resultado.get("operaciones") or [])
        raise ErrorDelObrero(
            f"el obrero falló (código {codigo}) tras {hechas} de {len(operaciones)} operaciones; lo hecho queda "
            f"apuntado. No se reintenta. Log: {log}\n{cola}"
        )
    resultado["log"] = str(log)
    return resultado


# ---------------------------------------------------------------------------------------------------------------
# La escala de las cabezas (sin GPU)
# ---------------------------------------------------------------------------------------------------------------
def _aplica(catalogo: dict, nombre: str, factor: float) -> None:
    """k = k0 · factor en la figura y en lo que SAM separó de ella: las entradas con `de: <nombre>`.

    Antes se reconocían por el prefijo `<nombre>_` y una figura llamada `a` pasaba su factor a `a_manos_base`, que
    es la base de OTRA figura (auditoría de F6.2c, recomendación 5). El obrero escribe `de` en cada pieza y en la
    base que separa; una entrada sin `de` (de un catálogo anterior a F6.2d) no hereda nada.
    """
    for n, d in catalogo.items():
        if n == nombre or d.get("de") == nombre:
            k0 = d.get("k0", d.get("k", 1.0))
            if abs(factor - 1) > 1e-6:
                d["k0"], d["k"] = k0, round(k0 * factor, 5)
            else:
                d.pop("k0", None)
                d["k"] = k0


def escala(dir_activos: str | Path, figuras: Mapping[str, Figura], color_de: Mapping[str, str]) -> list[str]:
    """Iguala la cabeza de cada postura con la de su personaje de pie, y apunta la caja y la medida de cada cabeza.

    - `figuras`: {nombre en el catálogo: Figura}.
    - `color_de`: {personaje: nombre de la figura de la que sale el color de su pelo}. Hace falta para todo
      personaje con `mide_cabeza`.

    Escribe en cada entrada `vista`, `cabeza` (su caja, para que los textos no tapen caras), `cabeza_px` (la raíz
    del área de pelo en px de su imagen, o null) y, si la corrige, `k0` (la k del recorte) y la `k` nueva. Correrla
    dos veces da lo mismo: parte siempre de `k0`. Devuelve el informe, una línea por cambio o por lo que no pudo
    medir.
    """
    catalogo = lee_catalogo(dir_activos)
    imagenes = catalogo["imagenes"]
    informe: list[str] = []
    colores: dict[str, object] = {}
    datos: dict[str, dict] = {}
    for nombre, fig in figuras.items():
        if nombre not in imagenes:
            informe.append(f"{nombre}: no está en el catálogo, no se mide")
            continue
        d = imagenes[nombre]
        figura = recorte.abre_figura(archivo_de(dir_activos, d))
        d["vista"] = fig.vista
        d["cabeza"] = recorte.caja_de_cabeza(figura, ALTO_CABEZA)
        if fig.mide_cabeza:
            if fig.pj not in colores:
                referencia = color_de.get(fig.pj)
                if referencia not in imagenes:
                    raise ErrorDelObrero(
                        f"{fig.pj}: su color de pelo sale de «{referencia}», que no está en el catálogo. "
                        "Recorta antes su hoja de personaje (o declara mide_cabeza=False)"
                    )
                colores[fig.pj] = recorte.color_de_pelo(
                    recorte.abre_figura(archivo_de(dir_activos, imagenes[referencia]))
                )
            d["cabeza_px"] = round(recorte.medida_de_cabeza(figura, colores[fig.pj]), 2)
        else:
            d["cabeza_px"] = None
        datos[nombre] = {
            "pj": fig.pj,
            "vista": fig.vista,
            "de_pie": fig.de_pie,
            "base": fig.base,
            "k0": d.get("k0", d.get("k", 1.0)),
            "cabeza_px": d["cabeza_px"],
        }
    factores, lineas = recorte.corrige_escalas(datos, UMBRAL_ESCALA_CABEZA)
    informe += lineas
    for nombre, f in factores.items():
        _aplica(imagenes, nombre, f)
        base = imagenes.get(f"{nombre}_base")
        if base is not None and base.get("de") == nombre:
            for campo in ("vista", "cabeza", "cabeza_px"):
                base[campo] = imagenes[nombre][campo]
        if f != 1.0:
            informe.append(f"{nombre}: k {imagenes[nombre]['k0']} → {imagenes[nombre]['k']}")
    guarda_catalogo(dir_activos, catalogo)
    return informe
