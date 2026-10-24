"""Un episodio del motor de escena: su guion de escena, dónde vive y qué le pide el pipeline (F6.2d).

**El guion de escena lo escribe Claude** (la skill que lo guía es de F6.4) y vive en git, junto a los datos del
canal, porque es texto y no se regenera:

    canales/<canal>/datos/escenas/<run_id>/escena.py      (`config.guion_de_escena` + `config.ESCENA_GUION`)

Lo que el pipeline hace con él —la composición, el sonido, las páginas de revisión y el vídeo— vive en el run, que
está fuera de git (`config.composicion_del_run`, `sonido_del_run`, `revision_del_run`).

**El contrato.** El módulo define dos funciones que reciben el `Episodio`:

- `puesta(ep) -> Puesta` (obligatoria): el `Guion` del episodio (`lib/escena/escena.py`), escrito sobre la línea de
  tiempo de `ep.linea()` y el catálogo de `ep.catalogo()`; el CSS del canal; y dónde empieza su karaoke en pantalla
  (`franja_karaoke_y`), que es lo que `encuadre.aparta_de_caras` no puede pisar, o None para no apartar nada.
- `activos(ep) -> Lote` (opcional): las imágenes nuevas del episodio (`lib/escena/activos.py`), con los personajes
  que necesitan las hojas y la escala de cabezas, y la semilla elegida de lo que se generó con varias. Sin esta
  función el episodio no genera ninguna imagen y usa el catálogo que ya tiene el run.

**Qué es del canal y qué del episodio.** El estilo, los personajes, sus alturas, el CSS y el bloque `escena` del
perfil son del canal (F6.3 los pone en `canales/<id>/escena/` y en su `perfil.json`); este guion los usa y añade lo
del episodio: sus planos, sus imágenes nuevas y sus momentos. Aquí no vive ninguno de esos valores (F4.9).

**El guion puede ser varios ficheros** (F6.3): su carpeta se carga como un paquete, así que `escena.py` importa lo
suyo con `from . import tramos` (los tramos de la historia, los recortes a medida del episodio…). Y la **capa del
canal** es otro paquete, `canales/<id>/escena/`, que el estudio carga con el nombre fijo
`config.ESCENA_PAQUETE_DEL_CANAL` (`escena_del_canal`): el guion la importa con `from escena_del_canal import
lugares` o la pide con `ep.canal()`. El nombre es fijo para que el guion se escriba igual en cualquier canal; el
paquete que hay detrás es el del canal del episodio, y se cambia si el episodio es de otro.

**La huella del guion** (lo que la parada 2 apunta y el render comprueba) cubre la carpeta entera del episodio, no
solo `escena.py`: un tramo cambiado después de revisar también es un guion cambiado.

**Las elecciones de semilla viven en el guion** (`Lote.elegidas`), no en el run: elegir entre dos imágenes es una
decisión que se revisa, y el run está fuera de git.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.machinery
import importlib.util
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from lib import config
from lib.escena import ajustes
from lib.escena.activos import Activo, Personaje
from lib.escena.escena import Guion


class ErrorDeEpisodio(ValueError):
    """El episodio no está listo para esta etapa: el mensaje dice qué falta y dónde."""


@dataclass(frozen=True)
class Lote:
    """Las imágenes nuevas de un episodio.

    - `activos`: lo que genera Qwen-Image-Edit, en orden (lo que parte de otro va detrás de él).
    - `personajes`: {id: Personaje} de los que salen en `activos` (las hojas y la escala de cabezas los necesitan).
    - `elegidas`: {nombre: semilla} de los activos generados con varias semillas.
    - `extra`: operaciones del obrero que no salen de un activo (`obrero.fondo`, `obrero.separa`), en orden.
    - `biblioteca`: los nombres de la biblioteca del canal que usa el episodio (`lib/escena/biblia.py`). La etapa
      `activos` los trae al run con sus piezas y su procedencia; no se generan otra vez.
    - `pizarras`: las pizarras que se separan en tiza y piezas (`pizarra.separacion`, formato «pizarra», F7.10), en
      orden. Van detrás de `extra`, que es donde el obrero las amplía, y sin GPU.
    """

    activos: Sequence[Activo]
    personajes: Mapping[str, Personaje]
    elegidas: Mapping[str, int] = field(default_factory=dict)
    extra: Sequence[dict] = field(default_factory=tuple)
    biblioteca: Sequence[str] = field(default_factory=tuple)
    pizarras: Sequence[dict] = field(default_factory=tuple)


@dataclass(frozen=True)
class Puesta:
    """La puesta en escena de un episodio, lista para componerse.

    - `guion`: el `Guion` del episodio, con la línea de tiempo de `ep.linea()`.
    - `css`: el CSS del canal (su estilo: colores, tipografías, rótulos, el color de cada hablante).
    - `franja_karaoke_y`: dónde empieza el karaoke en pantalla (px), que ningún texto apartado de una cara puede
      pisar; None si el episodio no quiere que se aparten textos. Sin defecto: depende del CSS del canal.
    - `momentos`: [(segundo, etiqueta)] para la hoja de fotogramas de la parada 2; None = el medio de cada plano.
    - `assets`: {ruta en la composición: fichero} de lo que el CSS o el guion piden y no está en el catálogo. Tiene
      que ser un fichero del run con su entrada en `assets.json` (decisión 5); si no, la etapa para.
    """

    guion: Guion
    css: Path
    franja_karaoke_y: float | None
    momentos: Sequence[tuple[float, str]] | None = None
    assets: Mapping[str, Path] = field(default_factory=dict)


class Episodio:
    """Lo que el guion de escena necesita del run y del canal. Lo arma el pipeline; las pruebas, con su canal ficticio.

    - `run_dir`, `run_id`: el run.
    - `canal_dir`: `canales/<id>/`, donde vive el guion de escena del episodio.
    - `perfil`: el `perfil.json` del canal, ya leído. Su bloque `escena` se exige aquí, al crearlo: sin él (sin sus
      pausas, sin su ritmo) no hay línea de tiempo, y es mejor saberlo antes de gastar la GPU.
    - `idioma`: el de los subtítulos del canal (`config.SUBTITLE_LANG`): el del texto que se pinta y del `.srt`.
    """

    def __init__(self, *, run_dir: str | Path, run_id: str, canal_dir: str | Path, perfil: Mapping, idioma: str):
        if not isinstance(idioma, str) or not idioma:
            raise ErrorDeEpisodio("el episodio necesita el idioma de los subtítulos del canal (idioma.subtitulos)")
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self.canal_dir = Path(canal_dir)
        self.perfil = dict(perfil)
        self.idioma = idioma
        try:
            self.escena = ajustes.exige(self.perfil)
        except ajustes.ErrorDeAjustes as error:
            raise ErrorDeEpisodio(str(error)) from None
        self._linea = None

    # ------------------------------------------------------------------ rutas
    @property
    def guion_dir(self) -> Path:
        return config.guion_de_escena(self.canal_dir, self.run_id)

    @property
    def guion_py(self) -> Path:
        return self.guion_dir / config.ESCENA_GUION

    @property
    def dir_activos(self) -> Path:
        return config.activos_del_run(self.run_dir)

    @property
    def dir_trabajo(self) -> Path:
        return config.trabajo_de_activos(self.run_dir)

    # ------------------------------------------------------------------ lo que el guion lee
    def linea(self):
        """La línea de tiempo del episodio (necesita la etapa `alinea`). Se arma una vez por episodio."""
        if self._linea is None:
            from lib.escena.linea_tiempo import ErrorDeLinea, LineaDeTiempo

            try:
                self._linea = LineaDeTiempo.del_run(self.run_dir, escena=self.escena, idioma=self.idioma)
            except ErrorDeLinea as error:
                raise ErrorDeEpisodio(
                    f"la línea de tiempo no se puede armar: {error}. ¿Pasó la etapa alinea?"
                ) from None
        return self._linea

    def catalogo(self) -> dict:
        """El catálogo de imágenes del episodio (`activos/catalogo.json → imagenes`), vacío si aún no hay."""
        from lib.escena import obrero

        return obrero.lee_catalogo(self.dir_activos)["imagenes"]

    def biblioteca(self) -> dict:
        """El catálogo de la biblioteca del canal (`lib/escena/biblia.py`), solo para leer: con él se escribe un guion
        antes de que sus imágenes estén en el run (la etapa `activos` las trae después)."""
        from lib.escena import biblia

        return biblia.lee(self.canal_dir).catalogo

    def canal(self):
        """La capa de canal del motor de escena (`canales/<id>/escena/`), cargada como `escena_del_canal`."""
        return carga_canal(self.canal_dir)

    def huella_del_guion(self) -> str:
        """El sha256 del guion de escena: la parada 2 lo apunta y el render comprueba que no ha cambiado.

        Cubre toda la carpeta del episodio (`escena.py` y lo que importa de ella), sin las cachés de Python.
        """
        return huella_de_carpeta(self.guion_dir, sin=("__pycache__",))


def huella_de_carpeta(carpeta: str | Path, *, sin: Sequence[str]) -> str:
    """Un sha256 de todos los ficheros de una carpeta: cambia si cambia, se añade o se quita cualquiera de ellos.

    Recorre los ficheros en orden de su ruta relativa y mezcla la ruta y el contenido de cada uno. `sin`: nombres de
    carpeta que no cuentan (una caché).
    """
    carpeta = Path(carpeta)
    h = hashlib.sha256()
    for f in sorted(p for p in carpeta.rglob("*") if p.is_file() and not set(p.relative_to(carpeta).parts) & set(sin)):
        relativa = f.relative_to(carpeta).as_posix()
        h.update(relativa.encode("utf-8") + b"\0" + hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def _paquete(nombre: str, carpeta: Path, *, reemplaza: bool):
    """Carga `carpeta` como un paquete llamado `nombre` (su `__init__.py` si lo tiene), para los `import` de dentro.

    Con `reemplaza`, el paquete y sus submódulos se descargan antes: así se lee lo que hay hoy en disco y no lo que se
    cargó en otra llamada (un guion editado entre dos etapas, u otro canal en el mismo proceso).
    """
    if reemplaza:
        for clave in [k for k in sys.modules if k == nombre or k.startswith(nombre + ".")]:
            del sys.modules[clave]
    init = carpeta / "__init__.py"
    if init.is_file():
        especificacion = importlib.util.spec_from_file_location(nombre, init, submodule_search_locations=[str(carpeta)])
    else:  # una carpeta sin __init__.py: un paquete vacío con esa ruta
        especificacion = importlib.machinery.ModuleSpec(nombre, None, is_package=True)
        especificacion.submodule_search_locations = [str(carpeta)]
    modulo = importlib.util.module_from_spec(especificacion)
    sys.modules[nombre] = modulo
    if especificacion.loader is not None:
        especificacion.loader.exec_module(modulo)
    return modulo


def carga_canal(canal_dir: str | Path):
    """La capa de canal del motor de escena como el paquete `config.ESCENA_PAQUETE_DEL_CANAL`.

    Se vuelve a cargar cada vez: un guion puede cambiar entre la parada 1 y la 2, y el paquete de otro canal no puede
    quedarse con el nombre. Para si el canal no tiene capa de escena.
    """
    carpeta = config.escena_del_canal(canal_dir)
    if not (carpeta / "__init__.py").is_file():
        raise ErrorDeEpisodio(
            f"el canal no tiene capa de escena ({carpeta / '__init__.py'}): su estilo, sus personajes, sus sets y su "
            "CSS viven ahí, no en el motor"
        )
    return _paquete(config.ESCENA_PAQUETE_DEL_CANAL, carpeta, reemplaza=True)


def carga_guion(ep: Episodio):
    """Carga el guion de escena del episodio. Para si no existe o no define `puesta`.

    La carpeta del episodio se carga como un paquete (así `escena.py` importa sus tramos con `from . import …`) y,
    antes, la capa del canal si la tiene (así el guion la importa como `escena_del_canal`).
    """
    ruta = ep.guion_py
    if not ruta.is_file():
        raise ErrorDeEpisodio(
            f"no está el guion de escena del episodio ({ruta}). Lo escribe quien pone en escena (la skill "
            "pone-en-escena): un escena.py con `puesta(ep) -> Puesta` y, si el episodio genera imágenes, "
            "`activos(ep) -> Lote` (contrato en lib/escena/episodio.py)"
        )
    if (config.escena_del_canal(ep.canal_dir) / "__init__.py").is_file():
        carga_canal(ep.canal_dir)
    paquete = "escena_del_episodio_" + hashlib.sha1(str(ruta.parent.resolve()).encode("utf-8")).hexdigest()[:12]
    _paquete(paquete, ruta.parent, reemplaza=True)
    modulo = importlib.import_module(f"{paquete}.{ruta.stem}")
    if not callable(getattr(modulo, "puesta", None)):
        raise ErrorDeEpisodio(f"{ruta} no define `puesta(ep) -> Puesta`: es lo único obligatorio del contrato")
    return modulo


def lote_de(ep: Episodio, modulo) -> Lote:
    """El lote de imágenes nuevas del episodio, o uno vacío si el guion no define `activos`."""
    if not hasattr(modulo, "activos"):
        return Lote(activos=(), personajes={})
    lote = modulo.activos(ep)
    if not isinstance(lote, Lote):
        raise ErrorDeEpisodio(f"`activos(ep)` de {ep.guion_py} devuelve {type(lote).__name__} y tiene que ser un Lote")
    return lote


def puesta_de(ep: Episodio, modulo) -> Puesta:
    """La puesta en escena del episodio, comprobada antes de componer nada."""
    puesta = modulo.puesta(ep)
    if not isinstance(puesta, Puesta):
        raise ErrorDeEpisodio(
            f"`puesta(ep)` de {ep.guion_py} devuelve {type(puesta).__name__} y tiene que ser una Puesta"
        )
    if not isinstance(puesta.guion, Guion) or puesta.guion.linea is None:
        raise ErrorDeEpisodio("la Puesta necesita un Guion escrito sobre la línea de tiempo del episodio (ep.linea())")
    if not Path(puesta.css).is_file():
        raise ErrorDeEpisodio(f"no está el CSS del canal que pide la puesta: {puesta.css}")
    if puesta.franja_karaoke_y is not None and not isinstance(puesta.franja_karaoke_y, (int, float)):
        raise ErrorDeEpisodio(f"franja_karaoke_y es un número de px o None, no {puesta.franja_karaoke_y!r}")
    return puesta
