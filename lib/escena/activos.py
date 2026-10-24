"""Las imágenes del motor de escena: hojas de personaje, lienzos de referencia, posturas, variantes y objetos (F6.2c).

Viene de `canal/scripts/activos.py` del experimento video_1, donde salieron así 124 imágenes. Todo pasa por
**Qwen-Image-Edit**, un solo modelo sin recargas entre imágenes, a través de `lib/comfy_client.py` y del workflow
`qwen-edit-lienzo` (una referencia y un lienzo aparte; su porqué, en `workflows/README.md`).

**Tres capas de consistencia**, las de video_1:

1. **Estilo**: el del canal (`Estilo`), dentro de cada instrucción.
2. **Biblia**: cada personaje se dibuja UNA vez, en una hoja de frente y de perfil, con una lámina del canal de
   referencia (`hoja`). De la hoja salen sus **lienzos de referencia** (`prepara_lienzos`): cada figura sobre
   croma, a la altura que el canal le da, de pie a la misma distancia del borde.
3. **Posturas**: cada una se pide con su lienzo de referencia **como referencia Y como lienzo**, así todas salen a
   la misma escala (`postura`). Las **variantes** son ediciones de la postura limpia en su sitio (`variante`), así
   que pasar de una a otra es un fundido. Los **objetos** salen de sustituir al personaje por ellos en su hoja
   (`objeto`, `objetos`): heredan el estilo y el croma limpio. De texto, Qwen los hacía como juguetes en 3D
   sobre un suelo rosa.

**Lo que aprendió video_1 y está en las plantillas**: Qwen dibuja lo que se nombra, aunque se le diga que no. La
pose describe solo el cuerpo («los puños cerrados hacia delante», no «como si sujetara el manillar»).

**Del canal** (parámetros, sin defecto, F4.9): su `Estilo`, sus `Personaje` (descripción canónica, alto en el
lienzo, en qué vistas de la hoja está de pie y si su cabeza se mide), las poses, los cambios, los objetos y las
semillas. **Del estudio**: las plantillas de instrucción, el croma, el tamaño de los lienzos y el sitio de los pies.

**Dónde va cada cosa** dentro de la carpeta de activos (la de un run es `config.activos_del_run`):

- `crudo/<nombre>-<semilla>.png`: lo que genera Qwen, con su registro en `generacion-imagenes.json`: modelo,
  workflow, semilla, instrucción, referencia, lienzo, licencia y url (decisión 5).
- `ref/<personaje>_<vista>_<forma>.png`: los lienzos de referencia, con su registro de derivado.
- `img/` y `catalogo.json`: los recortes (`recorta_elegidas`, que usa `lib/escena/obrero.py`).
- `elegidas.json`: la semilla elegida de cada activo que tiene varias. Elegir es de la revisión, no de aquí.

Y en la carpeta de trabajo (`config.trabajo_de_activos`, que es un `WORK_DIR`): los lienzos de croma lisos.

**La GPU va de una en una**: si ComfyUI no está vivo, antes de arrancarlo se comprueba que la tarjeta está libre;
si lo estaba (la instalación es compartida), al acabar se le pide que descargue el modelo, para que el obrero, que
viene después, tenga la memoria.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from lib import comfy_client as cc
from lib import config, provenance
from lib.escena import obrero, recorte
from lib.escena.render import ErrorDeRender, exige_gpu_libre

CRUDO = "crudo"
REF = "ref"
ELEGIDAS = "elegidas.json"

# El tamaño del lienzo de una hoja de personaje (dos figuras, lado a lado) y los de los lienzos de referencia de
# las posturas: «alto» para una figura de pie, «ancho» para una que se agacha, se sienta o corre. Son tamaños que
# Qwen-Image-Edit acepta sin recortar (múltiplos de 32) y los que usó video_1.
LIENZO_HOJA = (1664, 928)
LIENZOS = {"alto": (704, 960), "ancho": (1152, 960)}
# Los pies de cada figura, a esta distancia del borde de abajo en todos los lienzos de referencia.
PIES_AL_BORDE = 70
# Las dos figuras de una hoja, de izquierda a derecha, y cómo se nombran sus recortes: «<personaje>_<vista>».
VISTAS_DE_LA_HOJA = ("frente", "perfil")
# Cómo se pide la hoja de una persona. Es la plantilla del estudio: un canal la pasa tal cual en `Personaje.vistas`
# o escribe la suya (un perro que en la hoja está sentado de frente). Tiene que dejar las dos figuras en el orden
# de VISTAS_DE_LA_HOJA.
VISTAS_DE_PIE = (
    "the same character drawn twice, side by side and not overlapping: on the left, full body facing the viewer; "
    "on the right, full body in side view facing right; standing, relaxed, arms down"
)
# El color del pelo con que se mide la cabeza sale de la figura de perfil de la hoja: de perfil se ve más pelo.
VISTA_DEL_PELO = "perfil"


def _hex(color: Sequence[int]) -> str:
    return "#" + "".join(f"{int(v):02X}" for v in color)


# El fondo que pide cada imagen: el croma que `recorte.quita_magenta` sabe quitar. Sin suelo ni sombra, que
# se recortarían como parte de la figura.
FONDO_DE_CROMA = (
    f"Isolated on a completely flat, solid, pure magenta ({_hex(recorte.CROMA)}) background. "
    "No floor, no ground line, no cast shadow, nothing else in the picture."
)

_ID = re.compile(r"^[a-z0-9_]+$")


class ErrorDeActivos(ValueError):
    """Un activo no se puede generar o preparar tal como viene: el mensaje dice qué falta."""


def _texto(valor, que: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorDeActivos(f"falta {que}: es del canal y no tiene valor por defecto")
    return valor.strip()


def _id(valor, que: str) -> str:
    if not isinstance(valor, str) or not _ID.match(valor):
        raise ErrorDeActivos(f"{que} «{valor}» no vale como nombre de fichero: minúsculas, cifras y «_»")
    return valor


def _semillas(semillas) -> tuple[int, ...]:
    if not semillas or not all(isinstance(s, int) and not isinstance(s, bool) and s >= 0 for s in semillas):
        raise ErrorDeActivos(f"las semillas tienen que ser enteros ≥ 0, y al menos una: {semillas!r}")
    return tuple(semillas)


@dataclass(frozen=True)
class Estilo:
    """El estilo del canal en las instrucciones a Qwen.

    - `prefijo`: el estilo de las figuras sueltas (sin nada del fondo: ni desenfoque ni encuadre).
    - `igual`: la frase que pide el mismo estilo, las mismas caras y los mismos colores que la referencia.
    - `conserva`: la frase que pide conservar el estilo al sustituir a un personaje por objetos.
    """

    prefijo: str
    igual: str
    conserva: str

    def __post_init__(self):
        for campo in ("prefijo", "igual", "conserva"):
            _texto(getattr(self, campo), f"el estilo del canal: {campo}")


@dataclass(frozen=True)
class Personaje:
    """Un personaje del canal.

    - `id`: su nombre en ficheros y en el catálogo.
    - `descripcion`: la canónica del canal, siempre la misma y sin sinónimos.
    - `alto`: px de alto de su figura de pie en los lienzos de referencia (un perro de perfil es más ancho que
      alto: a la altura de una persona no cabría).
    - `de_pie`: en qué vistas de la hoja está de pie (de VISTAS_DE_LA_HOJA). La primera fija la escala.
    - `vistas`: cómo se le pide la hoja (VISTAS_DE_PIE, o la del canal).
    - `mide_cabeza`: False si su cabeza no se puede medir por el pelo (un perro, cuyo pelo es todo el cuerpo).
    """

    id: str
    descripcion: str
    alto: int
    de_pie: tuple[str, ...]
    vistas: str
    mide_cabeza: bool

    def __post_init__(self):
        _id(self.id, "el personaje")
        _texto(self.descripcion, f"la descripción de {self.id}")
        _texto(self.vistas, f"cómo se pide la hoja de {self.id}")
        if not isinstance(self.alto, int) or isinstance(self.alto, bool) or self.alto <= 0:
            raise ErrorDeActivos(f"{self.id}: su alto en el lienzo tiene que ser un entero de px > 0, no {self.alto!r}")
        if not self.de_pie or not set(self.de_pie) <= set(VISTAS_DE_LA_HOJA):
            raise ErrorDeActivos(f"{self.id}: de_pie tiene que nombrar vistas de la hoja {VISTAS_DE_LA_HOJA}")
        if not isinstance(self.mide_cabeza, bool):
            raise ErrorDeActivos(f"{self.id}: mide_cabeza es True o False, y lo declara el canal")


@dataclass(frozen=True)
class Activo:
    """Una imagen que genera Qwen-Image-Edit.

    - `referencia`: un fichero (Path) o el nombre de otro activo (su imagen elegida).
    - `lienzo`: None si el lienzo es la propia referencia (misma escala y encuadre); (ancho, alto) para un lienzo de
      croma liso de ese tamaño.
    - `piezas`: los nombres de sus figuras por orden de lectura, si tiene varias (una hoja, una lámina de objetos).
    - `pj`, `vista`, `de_pie` y `base` (la postura limpia de una variante): lo que la escala de cabezas necesita.
    """

    nombre: str
    tipo: str
    prompt: str
    referencia: Path | str
    lienzo: tuple[int, int] | None
    semillas: tuple[int, ...]
    que: str
    piezas: tuple[str, ...] = ()
    pj: str | None = None
    vista: str | None = None
    de_pie: bool | None = None
    base: str | None = None


# ---------------------------------------------------------------------------------------------------------------
# Las fábricas: plantillas del estudio, contenido del canal
# ---------------------------------------------------------------------------------------------------------------
def hoja(personaje: Personaje, estilo: Estilo, *, referencia: str | Path, semillas: Sequence[int]) -> Activo:
    """La hoja de un personaje: dos figuras (VISTAS_DE_LA_HOJA) sobre croma liso, con una lámina de referencia."""
    prompt = (
        f"{estilo.prefijo} Draw {personaje.descripcion}, the character from the picture, alone, as a character model "
        f"sheet: {personaje.vistas}. {estilo.igual} {FONDO_DE_CROMA}"
    )
    return Activo(
        nombre=f"hoja_{personaje.id}",
        tipo="hoja",
        prompt=prompt,
        referencia=Path(referencia),
        lienzo=LIENZO_HOJA,
        semillas=_semillas(semillas),
        que=f"hoja de personaje: {personaje.descripcion}",
        piezas=tuple(f"{personaje.id}_{v}" for v in VISTAS_DE_LA_HOJA),
        pj=personaje.id,
    )


def postura(
    nombre: str,
    personaje: Personaje,
    estilo: Estilo,
    *,
    vista: str,
    forma: str,
    pose: str,
    de_pie: bool,
    lienzos: str | Path,
    semillas: Sequence[int],
) -> Activo:
    """Una postura: su lienzo de referencia como referencia y como lienzo. `pose` describe solo el cuerpo."""
    _id(nombre, "la postura")
    if vista not in VISTAS_DE_LA_HOJA or forma not in LIENZOS:
        raise ErrorDeActivos(f"{nombre}: vista en {VISTAS_DE_LA_HOJA} y forma en {tuple(LIENZOS)}")
    pose = _texto(pose, f"la pose de {nombre}")
    prompt = (
        f"{estilo.prefijo} Redraw exactly the same character as in the picture, now {pose}. "
        "Same face, same hair, same clothes and colours, same proportions and the same size in the picture, only one "
        f"character and no objects, the whole body visible. {personaje.descripcion}. {FONDO_DE_CROMA}"
    )
    return Activo(
        nombre=nombre,
        tipo="postura",
        prompt=prompt,
        referencia=Path(lienzos) / f"{personaje.id}_{vista}_{forma}.png",
        lienzo=None,
        semillas=_semillas(semillas),
        que=pose,
        pj=personaje.id,
        vista=vista,
        de_pie=bool(de_pie),
    )


def variante(nombre: str, de: Activo, estilo: Estilo, *, cambio: str, semillas: Sequence[int]) -> Activo:
    """Una edición de una postura en su sitio (misma pose, mismo encuadre, un solo cambio): una mancha, un gesto."""
    _id(nombre, "la variante")
    if de.tipo not in ("postura", "variante"):
        raise ErrorDeActivos(f"{nombre}: una variante sale de una postura, no de un {de.tipo}")
    prompt = (
        f"{estilo.prefijo} Edit this picture: {_texto(cambio, f'el cambio de {nombre}')}. Keep everything else exactly "
        f"the same: the same pose, face, clothes, colours, size and position. {FONDO_DE_CROMA}"
    )
    return Activo(
        nombre=nombre,
        tipo="variante",
        prompt=prompt,
        referencia=de.nombre,
        lienzo=None,
        semillas=_semillas(semillas),
        que=cambio,
        pj=de.pj,
        vista=de.vista,
        de_pie=de.de_pie,
        base=de.base or de.nombre,
    )


def objeto(
    nombre: str,
    estilo: Estilo,
    *,
    que: str,
    en: str | Path,
    quien: str,
    semillas: Sequence[int],
    piezas: Sequence[str] | None = None,
) -> Activo:
    """Uno o varios objetos, sustituyendo a `quien` (lo que hay en la hoja, «both girls») en la hoja `en`."""
    _id(nombre, "el objeto")
    prompt = (
        f"{estilo.prefijo} Edit this picture: replace {_texto(quien, f'a quién sustituye {nombre}')} with "
        f"{_texto(que, f'qué es {nombre}')}. Nobody in the picture. {estilo.conserva}, and the same flat solid "
        "magenta background, with no floor and no shadow."
    )
    return Activo(
        nombre=nombre,
        tipo="objeto",
        prompt=prompt,
        referencia=en if isinstance(en, str) else Path(en),
        lienzo=None,
        semillas=_semillas(semillas),
        que=que,
        piezas=tuple(piezas or ()),
    )


def objetos(
    nombre: str,
    estilo: Estilo,
    *,
    lista: str,
    piezas: Sequence[str],
    en: str | Path,
    quien: str,
    semillas: Sequence[int],
) -> Activo:
    """Una lámina de varios objetos separados; `piezas` los nombra por orden de lectura."""
    if not piezas:
        raise ErrorDeActivos(f"{nombre}: una lámina de objetos nombra cada uno (piezas, por orden de lectura)")
    que = (
        "several separate objects, apart from each other, evenly spaced, not touching, each one whole and clearly "
        f"drawn: {_texto(lista, f'la lista de {nombre}')}"
    )
    return objeto(nombre, estilo, que=que, en=en, quien=quien, semillas=semillas, piezas=piezas)


# ---------------------------------------------------------------------------------------------------------------
# Las semillas y la imagen elegida
# ---------------------------------------------------------------------------------------------------------------
def crudo(dir_activos: str | Path, nombre: str, semilla: int) -> Path:
    return Path(dir_activos) / CRUDO / f"{nombre}-{semilla}.png"


def lee_elegidas(dir_activos: str | Path) -> dict[str, int]:
    ruta = Path(dir_activos) / ELEGIDAS
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}


def elige(dir_activos: str | Path, nombre: str, semilla: int) -> None:
    """Apunta la semilla elegida de un activo (lo decide la revisión: aquí solo se guarda)."""
    if not crudo(dir_activos, nombre, semilla).exists():
        raise ErrorDeActivos(f"{nombre}: no hay imagen generada con la semilla {semilla}")
    elegidas = lee_elegidas(dir_activos)
    elegidas[nombre] = semilla
    (Path(dir_activos) / ELEGIDAS).write_text(json.dumps(elegidas, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def elegida(dir_activos: str | Path, activo: Activo) -> Path:
    """La imagen elegida de un activo: la de `elegidas.json` o, si solo tiene una semilla, esa."""
    semilla = lee_elegidas(dir_activos).get(activo.nombre)
    if semilla is None:
        if len(activo.semillas) != 1:
            raise ErrorDeActivos(
                f"{activo.nombre}: tiene {len(activo.semillas)} semillas {activo.semillas} y falta elegir una"
            )
        semilla = activo.semillas[0]
    ruta = crudo(dir_activos, activo.nombre, semilla)
    if not ruta.exists():
        raise ErrorDeActivos(f"{activo.nombre}: no está generada su imagen con la semilla {semilla} ({ruta.name})")
    return ruta


def _resuelve(referencia: Path | str, por_nombre: Mapping[str, Activo], dir_activos: Path) -> Path:
    if isinstance(referencia, Path):
        if not referencia.is_file():
            raise ErrorDeActivos(f"no existe la referencia {referencia}")
        return referencia
    if referencia not in por_nombre:
        raise ErrorDeActivos(f"la referencia «{referencia}» no es ningún activo del lote")
    return elegida(dir_activos, por_nombre[referencia])


def lienzo_de_croma(dir_trabajo: str | Path, ancho: int, alto: int) -> Path:
    """Un lienzo liso de croma de ese tamaño (material de trabajo: no es un asset)."""
    ruta = Path(dir_trabajo) / f"lienzo-croma-{ancho}x{alto}.png"
    if not ruta.exists():
        ruta.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (ancho, alto), recorte.CROMA).save(ruta)
    return ruta


# ---------------------------------------------------------------------------------------------------------------
# Generar
# ---------------------------------------------------------------------------------------------------------------
def genera(
    activos: Sequence[Activo], dir_activos: str | Path, dir_trabajo: str | Path, *, solo: Iterable[str] | None = None
) -> list[dict]:
    """Genera lo que falte de un lote, EN SERIE, y devuelve los registros de lo generado.

    Relanzar solo genera lo que no está en disco. Un activo que parte de otro (una variante de una postura, un
    objeto en una hoja del lote) va después de él en `activos`, y si ese otro tiene varias semillas hay que
    haberle elegido una. Las referencias se comprueban antes de tocar la GPU: una que falta para aquí, no a los
    diez minutos de lote.
    """
    dir_activos, dir_trabajo = Path(dir_activos), Path(dir_trabajo)
    por_nombre: dict[str, Activo] = {}
    for a in activos:
        if a.nombre in por_nombre:
            raise ErrorDeActivos(f"dos activos con el mismo nombre: {a.nombre}")
        por_nombre[a.nombre] = a
    elegir = set(solo) if solo is not None else None
    pendientes = [
        (a, s)
        for a in activos
        if elegir is None or a.nombre in elegir
        for s in a.semillas
        if not crudo(dir_activos, a.nombre, s).exists()
    ]
    if not pendientes:
        return []
    antes = set()
    elegidas = lee_elegidas(dir_activos)
    for a, _ in pendientes:
        if isinstance(a.referencia, Path):
            _resuelve(a.referencia, por_nombre, dir_activos)
        elif a.referencia not in por_nombre:
            raise ErrorDeActivos(f"{a.nombre}: su referencia «{a.referencia}» no es ningún activo del lote")
        else:
            de = por_nombre[a.referencia]
            if len(de.semillas) > 1 and de.nombre not in elegidas:
                raise ErrorDeActivos(
                    f"{a.nombre}: parte de «{de.nombre}», que tiene {len(de.semillas)} semillas y ninguna elegida"
                )
            if de.nombre not in antes and not any(crudo(dir_activos, de.nombre, s).exists() for s in de.semillas):
                raise ErrorDeActivos(f"{a.nombre}: parte de «{de.nombre}», que no está generado ni va antes en el lote")
        antes.add(a.nombre)
    workflow = cc.load_workflow(config.ESCENA_WORKFLOW_EDICION)
    if not cc.server_is_alive():
        try:
            exige_gpu_libre()
        except ErrorDeRender as e:
            raise ErrorDeActivos(str(e)) from None
    registros: list[dict] = []
    with cc.comfy_server() as arrancado:
        subidas: dict[Path, str] = {}
        try:
            for numero, (a, semilla) in enumerate(pendientes, start=1):
                referencia = _resuelve(a.referencia, por_nombre, dir_activos)
                lienzo = referencia if a.lienzo is None else lienzo_de_croma(dir_trabajo, *a.lienzo)
                for ruta in (referencia, lienzo):
                    if ruta not in subidas:
                        subidas[ruta] = cc.sube_imagen(ruta)
                with Image.open(lienzo) as im:
                    ancho, alto = im.size
                salida = crudo(dir_activos, a.nombre, semilla)
                salida.parent.mkdir(parents=True, exist_ok=True)
                print(f"  [{numero}/{len(pendientes)}] {a.nombre} · semilla {semilla}", flush=True)
                registro = cc.render(
                    workflow,
                    a.prompt,
                    str(salida),
                    width=ancho,
                    height=alto,
                    seed=semilla,
                    overrides={"referencia": subidas[referencia], "lienzo": subidas[lienzo]},
                )
                registro.update(
                    {
                        "url": workflow["modelo"].get("url"),
                        "activo": a.nombre,
                        "tipo_activo": a.tipo,
                        "que": a.que,
                        "referencia": obrero.muestra(referencia, dir_activos.parent),
                        "lienzo": "la propia referencia" if a.lienzo is None else f"croma liso {ancho}x{alto}",
                        **{c: getattr(a, c) for c in ("pj", "vista", "de_pie", "base") if getattr(a, c) is not None},
                    }
                )
                # Se vuelca en cada vuelta: si el proceso muere a mitad, lo generado conserva su procedencia.
                provenance.anade_registros(salida.parent / provenance.IMAGE_RECORDS_FILENAME, [registro])
                registros.append(registro)
                print(f"      {registro['segundos']} s · {salida.name}", flush=True)
        finally:
            cc.borra_subidas(subidas.values())
            if not arrancado:
                # El ComfyUI ya estaba vivo (compartido): se le pide que suelte el modelo para el trabajo siguiente.
                cc.free_memory()
    return registros


# ---------------------------------------------------------------------------------------------------------------
# Los lienzos de referencia
# ---------------------------------------------------------------------------------------------------------------
def prepara_lienzos(personaje: Personaje, hoja_png: str | Path, destino: str | Path) -> dict[str, Path]:
    """Los lienzos de referencia de un personaje: cada figura de su hoja sobre croma liso, a su alto de pie.

    La escala sale de la figura de pie que fija la escala (la primera de `de_pie`) y se aplica igual a las dos
    vistas, para que de frente y de perfil midan lo mismo. Cada figura va centrada y con los pies a PIES_AL_BORDE
    del borde de abajo en los dos formatos (LIENZOS). Sin GPU: Pillow y el recorte por croma.
    """
    hoja_png, destino = Path(hoja_png), Path(destino)
    with Image.open(hoja_png) as im:
        rgba = recorte.quita_magenta(np.asarray(im.convert("RGB")).astype(np.float32))
    cajas = recorte.orden_lectura(recorte.piezas(rgba))
    if len(cajas) != len(VISTAS_DE_LA_HOJA):
        raise ErrorDeActivos(
            f"{hoja_png.name}: una hoja tiene {len(VISTAS_DE_LA_HOJA)} figuras ({', '.join(VISTAS_DE_LA_HOJA)}) y esta "
            f"tiene {len(cajas)}. Elige otra semilla o límpiala"
        )
    figuras = dict(zip(VISTAS_DE_LA_HOJA, cajas))
    de_pie = figuras[personaje.de_pie[0]]
    k = personaje.alto / (de_pie[3] - de_pie[1])
    destino.mkdir(parents=True, exist_ok=True)
    hechos: dict[str, Path] = {}
    registros = []
    for vista, caja in figuras.items():
        figura = Image.fromarray(rgba, "RGBA").crop(caja)
        figura = figura.resize((round(figura.width * k), round(figura.height * k)), Image.LANCZOS)
        for forma, (ancho, alto) in LIENZOS.items():
            x, y = (ancho - figura.width) // 2, alto - PIES_AL_BORDE - figura.height
            if x < 0 or y < 0:
                raise ErrorDeActivos(
                    f"{personaje.id} de {vista} no cabe en el lienzo «{forma}» {ancho}x{alto} a {personaje.alto} px de "
                    f"alto (mide {figura.width}x{figura.height}): baja su alto en el canal"
                )
            lienzo = Image.new("RGBA", (ancho, alto), (*recorte.CROMA, 255))
            lienzo.alpha_composite(figura, (x, y))
            ruta = destino / f"{personaje.id}_{vista}_{forma}.png"
            lienzo.convert("RGB").save(ruta)
            hechos[f"{vista}_{forma}"] = ruta
            registros.append(
                obrero.registro_derivado(
                    ruta,
                    hoja_png,
                    quien="lib/escena/activos.py con Pillow y el recorte por croma, en .venv",
                    que_hace=(
                        f"la figura de {vista} recortada por croma, escalada ×{k:.4f} para que de pie mida "
                        f"{personaje.alto} px y puesta sobre croma liso {ancho}x{alto} con los pies a "
                        f"{PIES_AL_BORDE} px del borde"
                    ),
                    usadas=[],
                    detalle={"personaje": personaje.id, "vista": vista, "forma": forma, "escala": round(k, 5)},
                    ancla=destino.parent.parent,
                )
            )
    provenance.anade_registros(destino / provenance.IMAGE_RECORDS_FILENAME, registros)
    return hechos


# ---------------------------------------------------------------------------------------------------------------
# Recortar y escalar lo elegido (el obrero)
# ---------------------------------------------------------------------------------------------------------------
def operaciones_de_recorte(
    activos: Sequence[Activo], personajes: Mapping[str, Personaje], dir_activos: str | Path
) -> list[dict]:
    """Las operaciones del obrero para recortar la imagen elegida de cada activo.

    - Una hoja: sus dos figuras, y la k de las dos sale de la de pie que fija la escala del personaje: k = su alto
      recortado / (ESCALA_RECORTE · alto en el lienzo). Una postura, que ya sale a la escala del lienzo, tiene k = 1.
    - Una lámina de objetos: sus figuras por orden de lectura.
    - Lo demás: una figura.
    """
    ops = []
    for a in activos:
        origen = elegida(dir_activos, a)
        if a.tipo == "hoja":
            pj = personajes.get(a.pj)
            if pj is None:
                raise ErrorDeActivos(f"{a.nombre}: su personaje «{a.pj}» no está entre los del canal")
            ops.append(
                obrero.recorta(
                    a.nombre,
                    origen,
                    piezas=a.piezas,
                    k_de=f"{pj.id}_{pj.de_pie[0]}",
                    alto_k=recorte.ESCALA_RECORTE * pj.alto,
                )
            )
        elif a.piezas:
            ops.append(obrero.recorta(a.nombre, origen, piezas=a.piezas))
        else:
            ops.append(obrero.recorta(a.nombre, origen))
    return ops


def recorta_elegidas(
    activos: Sequence[Activo], personajes: Mapping[str, Personaje], dir_activos: str | Path, dir_trabajo: str | Path
) -> dict:
    """Recorta con el obrero la imagen elegida de cada activo y la apunta en el catálogo y en la procedencia."""
    return obrero.ejecuta(operaciones_de_recorte(activos, personajes, dir_activos), dir_activos, dir_trabajo)


def figuras(activos: Sequence[Activo], personajes: Mapping[str, Personaje]) -> dict[str, obrero.Figura]:
    """Lo que la escala de cabezas necesita de cada figura con personaje: las de las hojas y las posturas."""
    salida: dict[str, obrero.Figura] = {}
    for a in activos:
        if a.pj is None:
            continue
        pj = personajes.get(a.pj)
        if pj is None:
            raise ErrorDeActivos(f"{a.nombre}: su personaje «{a.pj}» no está entre los del canal")
        if a.tipo == "hoja":
            for vista, nombre in zip(VISTAS_DE_LA_HOJA, a.piezas):
                salida[nombre] = obrero.Figura(pj.id, vista, vista in pj.de_pie, None, pj.mide_cabeza)
        else:
            salida[a.nombre] = obrero.Figura(pj.id, a.vista, bool(a.de_pie), a.base, pj.mide_cabeza)
    return salida


def escala(activos: Sequence[Activo], personajes: Mapping[str, Personaje], dir_activos: str | Path) -> list[str]:
    """Iguala las cabezas de las posturas con las de pie de su personaje (`obrero.escala`). Devuelve el informe."""
    colores = {pj.id: f"{pj.id}_{VISTA_DEL_PELO}" for pj in personajes.values() if pj.mide_cabeza}
    return obrero.escala(dir_activos, figuras(activos, personajes), colores)
