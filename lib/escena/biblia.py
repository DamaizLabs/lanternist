"""La biblioteca de imágenes de un canal en el motor de escena, y cómo entra en un run (F6.3).

Un canal reutiliza entre episodios lo que ya dibujó: las posturas de sus personajes, sus fondos, sus objetos. Viene de
`canal/biblioteca.json` + `biblioteca.py` del experimento video_1, con una diferencia de fondo: allí la
imagen se copiaba de un capítulo a otro sin procedencia; aquí **cada fichero lleva su registro y su sha256**, y
entra en el run como cualquier otro asset (decisión 5).

**Crece sola tras la parada 1** (`incorpora`, decisión del 29-09, addendum fila 208): cuando un episodio pasa
la parada 1 —el usuario vio sus imágenes nuevas y se sigue con la etapa `escena`—, lo que el episodio generó entra en la
biblioteca con su procedencia y su sha256, y un episodio siguiente lo trae en vez de generarlo otra vez.

La biblioteca vive en la capa del canal, `canales/<id>/escena/biblioteca/` (`config.biblioteca_del_canal`):

- `img/`: las imágenes ya recortadas;
- `catalogo.json`: `{imagenes: {nombre: entrada}}`, con el esquema del catálogo de un run (`src`, `w`, `h`, `ax`,
  `ay`, `k`, `cabeza`, `cabeza_px`, `vista`, `off`…) y el `src` que tendrá dentro de la composición;
- `procedencia.json`: `{ficheros: {"img/<fichero>": {sha256, fuente, modelo, licencia, url, origen, …}}}`, uno por
  FICHERO (varias entradas del catálogo pueden compartir imagen);
- `indice.json`: qué es cada imagen (`tipo`, `pj`, `vista`, `que`, `de`…), para buscarla al escribir un guion.

**Cómo entra en un run** (`trae`): el guion de escena del episodio dice qué nombres usa (`Lote.biblioteca`) y la
etapa `activos` los copia a `<run>/activos/img/`, pone su entrada en el catálogo del run y escribe su registro en el
`generacion-imagenes.json` de esa carpeta, que es donde `provenance.sync` ya los busca. Con cada figura viajan sus
piezas (su `_base` y lo que se mece con ella, `off`). Si el fichero ya no es el del sha256 apuntado, o su registro no
dice de dónde sale, **para**: un fichero cambiado sin cambiar su registro llevaría al vídeo algo cuya procedencia no
ha escrito nadie.

Aquí no hay nada de ningún canal (F4.9): la carpeta llega como parámetro.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lib import config, provenance
from lib.escena import obrero

CATALOGO = "catalogo.json"
PROCEDENCIA = "procedencia.json"
INDICE = "indice.json"
IMG = "img"


class ErrorDeBiblioteca(ValueError):
    """La biblioteca del canal no tiene lo que el episodio pide, o no dice de dónde sale: el mensaje dice qué."""


@dataclass(frozen=True)
class Biblioteca:
    carpeta: Path
    catalogo: dict
    procedencia: dict
    indice: dict

    def fichero(self, nombre: str) -> Path:
        return self.carpeta / IMG / Path(str(self.catalogo[nombre]["src"])).name


def _lee(ruta: Path, clave: str) -> dict:
    if not ruta.is_file():
        raise ErrorDeBiblioteca(f"no está {ruta}: la biblioteca del canal necesita su {ruta.name}")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, dict) or not isinstance(datos.get(clave), dict):
        raise ErrorDeBiblioteca(f"{ruta} no tiene la forma esperada: {{'{clave}': {{...}}}}")
    return datos[clave]


def lee(canal_dir: str | Path) -> Biblioteca:
    """La biblioteca del canal: su catálogo, su procedencia y su índice."""
    carpeta = config.biblioteca_del_canal(canal_dir)
    return Biblioteca(
        carpeta=carpeta,
        catalogo=_lee(carpeta / CATALOGO, "imagenes"),
        procedencia=_lee(carpeta / PROCEDENCIA, "ficheros"),
        indice=_lee(carpeta / INDICE, "imagenes") if (carpeta / INDICE).is_file() else {},
    )


def es_pieza(nombre: str, entrada: dict) -> bool:
    """Una pieza separada de una figura (lo que se mece con ella, o la figura sin esa pieza): viaja con la figura."""
    return "off" in entrada or nombre.endswith("_base")


def piezas(bib: Biblioteca, nombre: str) -> list[str]:
    """Las piezas de una figura: las entradas que empiezan por su nombre y son piezas."""
    return [n for n, e in bib.catalogo.items() if n.startswith(nombre + "_") and es_pieza(n, e)]


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def registro(bib: Biblioteca, nombre: str, copia: Path) -> dict:
    """El registro de procedencia de la copia en el run de una imagen de la biblioteca, comprobado.

    Para si el fichero no está, si su registro no dice fuente, modelo, licencia y url (la url puede faltar solo si
    no hay modelo: una forma dibujada por geometría), o si su sha256 ya no es el apuntado.
    """
    origen = bib.fichero(nombre)
    clave = f"{IMG}/{origen.name}"
    if not origen.is_file():
        raise ErrorDeBiblioteca(f"«{nombre}»: no está su imagen en la biblioteca del canal ({origen})")
    ficha = bib.procedencia.get(clave) or {}
    faltan = [c for c in ("fuente", "modelo", "licencia", "sha256") if not ficha.get(c)]
    if "url" not in ficha or (not ficha.get("url") and not str(ficha.get("modelo", "")).startswith("ninguno")):
        faltan.append("url")
    if faltan:
        raise ErrorDeBiblioteca(
            f"«{nombre}» ({clave}) no tiene {faltan} en {bib.carpeta / PROCEDENCIA}: sin procedencia no entra en un "
            "vídeo"
        )
    sha = _sha256(origen)
    if sha != ficha["sha256"]:
        raise ErrorDeBiblioteca(
            f"«{nombre}» ({clave}) ha cambiado desde que se apuntó su procedencia (sha256 {sha[:12]}… frente a "
            f"{str(ficha['sha256'])[:12]}…): actualiza su registro antes de usarlo"
        )
    try:
        desde = origen.resolve().relative_to(config.BASE_DIR).as_posix()
    except ValueError:
        desde = origen.name  # una biblioteca fuera del repositorio: sin rutas personales en el registro
    detalle = {k: v for k, v in ficha.items() if k not in ("fuente", "modelo", "licencia", "url", "origen", "bytes")}
    return {
        "file": str(copia),
        "fuente": f"biblioteca del canal ({desde}): {ficha['fuente']}",
        "modelo": ficha["modelo"],
        "licencia": ficha["licencia"],
        "url": ficha.get("url"),
        "origen": ficha.get("origen") or "",
        "desde_la_biblioteca": desde,
        **detalle,
    }


def trae(canal_dir: str | Path, nombres: Iterable[str], dir_activos: str | Path) -> list[str]:
    """Copia al run las imágenes `nombres` de la biblioteca del canal, con sus piezas, su catálogo y su registro.

    Devuelve los nombres traídos (las piezas incluidas), en orden. Una imagen que el catálogo del run ya tiene con el
    mismo `src` y el mismo contenido se vuelve a apuntar igual: traer dos veces da lo mismo.
    """
    bib = lee(canal_dir)
    dir_activos = Path(dir_activos)
    pedidos = list(dict.fromkeys(nombres))
    faltan = [n for n in pedidos if n not in bib.catalogo]
    if faltan:
        raise ErrorDeBiblioteca(
            f"el episodio pide {len(faltan)} imagen(es) que no están en la biblioteca del canal "
            f"({bib.carpeta / CATALOGO}): {faltan[:10]}"
        )
    todos = list(dict.fromkeys(n for p in pedidos for n in (p, *piezas(bib, p))))
    catalogo = obrero.lee_catalogo(dir_activos)
    destino = dir_activos / obrero.IMG
    destino.mkdir(parents=True, exist_ok=True)
    registros: dict[str, dict] = {}
    for n in todos:
        origen = bib.fichero(n)
        copia = destino / origen.name
        if origen.name not in registros:
            registros[origen.name] = registro(bib, n, copia)
            if not copia.is_file() or _sha256(copia) != registros[origen.name]["sha256"]:
                shutil.copy2(origen, copia)
        catalogo["imagenes"][n] = dict(bib.catalogo[n])
    provenance.anade_registros(destino / obrero.REGISTRO, list(registros.values()))
    obrero.guarda_catalogo(dir_activos, catalogo)
    return todos


# ------------------------------------------------------------------------------------------ la biblioteca crece
# Lo que se copia del registro del crudo (la imagen que generó el modelo) a la ficha de la biblioteca: con esto la
# imagen se puede regenerar aunque el crudo se quede en el run, fuera de git, como las que se importaron en F6.3.
# Y lo que el canal sabe de la figura (de quién es, de qué lado, si está de pie), para el índice.
_DEL_CRUDO = (
    "workflow",
    "pesos",
    "seed",
    "prompt",
    "resolucion",
    "referencia",
    "lienzo",
    "activo",
    "tipo_activo",
    "que",
    "pj",
    "vista",
    "de_pie",
    "base",
)


def _escribe(ruta: Path, clave: str, datos: Mapping) -> None:
    """Un JSON de la biblioteca, con el formato de los que importó F6.3, y sin quedarse a medias."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".json.tmp")
    temporal.write_text(json.dumps({clave: dict(datos)}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    temporal.replace(ruta)


def _lee_o_vacia(canal_dir: str | Path) -> Biblioteca:
    """La biblioteca del canal, o una vacía si el canal todavía no tiene (la crea su primer episodio)."""
    carpeta = config.biblioteca_del_canal(canal_dir)
    if not (carpeta / CATALOGO).is_file() and not (carpeta / PROCEDENCIA).is_file():
        return Biblioteca(carpeta=carpeta, catalogo={}, procedencia={}, indice={})
    return lee(canal_dir)


def _ficha_de(bib: Biblioteca, nombre: str) -> dict:
    return bib.procedencia.get(f"{IMG}/{bib.fichero(nombre).name}") or {}


def _de_quien(bib: Biblioteca, nombre: str) -> str:
    """De dónde salió una imagen de la biblioteca, para decirlo en un mensaje."""
    indice = bib.indice.get(nombre) or {}
    return str(
        _ficha_de(bib, nombre).get("episodio") or indice.get("episodio") or indice.get("capitulo") or "otro origen"
    )


def _es_del_episodio(ficha: Mapping | None, episodio: str) -> bool:
    return bool(ficha) and ficha.get("episodio") == episodio


def ajenas(canal_dir: str | Path, nombres: Iterable[str], *, episodio: str) -> dict[str, str]:
    """De `nombres`, las que la biblioteca del canal ya tiene y no puso ESTE episodio: {nombre: de dónde salen}.

    La etapa `activos` lo mira antes de generar: pedir a Qwen una imagen que ya está en la biblioteca gasta GPU y da
    otra versión con el mismo nombre, que además no podría entrar en la biblioteca sin pisar la que ya está. Las que
    puso este mismo episodio no cuentan: rehacerlas es corregirlas, y al pasar otra vez la parada 1 se actualizan.
    """
    bib = _lee_o_vacia(canal_dir)
    return {
        n: _de_quien(bib, n)
        for n in dict.fromkeys(nombres)
        if n in bib.catalogo and not _es_del_episodio(_ficha_de(bib, n), episodio)
    }


def _que_le_falta(reg: Mapping) -> str | None:
    """Por qué el registro de una imagen del run no basta para la biblioteca (decisión 5), o None si basta.

    Es lo que `registro` exige al traer: fuente, modelo, licencia y url (que solo puede faltar si no hubo modelo). Y
    una licencia «desconocida» (un derivado cuyo origen no tenía registro) tampoco entra: en el run queda entre las
    licencias por cerrar, y en la biblioteca se heredaría episodio tras episodio sin que nadie la cerrase.
    """
    faltan = [c for c in ("fuente", "modelo", "licencia") if not reg.get(c)]
    if not reg.get("url") and not str(reg.get("modelo", "")).startswith("ninguno"):
        faltan.append("url")
    if faltan:
        return f"su registro de procedencia en el run no dice {faltan}"
    if str(reg["licencia"]).lower().startswith("desconocida"):
        return f"su licencia está por cerrar ({reg['licencia']})"
    return None


def _crudo_de(reg: Mapping, run_dir: Path) -> tuple[Path | None, dict]:
    """La imagen que generó el modelo y de la que deriva esta, siguiendo `derivado_de`, con su registro.

    Un recorte deriva de su crudo; una pieza que separó SAM, del recorte, y este del crudo.
    """
    ruta, actual, vistos = None, dict(reg), set()
    while actual.get("derivado_de") and actual["derivado_de"] not in vistos:
        vistos.add(actual["derivado_de"])
        ruta = run_dir / str(actual["derivado_de"])
        siguiente = obrero.registro_de_origen(ruta)
        if siguiente is None:
            return ruta, {}
        actual = siguiente
    return (ruta, actual) if ruta is not None else (None, {})


def _ficha(reg: Mapping, archivo: Path, sha: str, run_dir: Path, episodio: str, cuando: str) -> dict:
    """La ficha de procedencia en la biblioteca de una imagen del episodio: su registro en el run y su crudo."""
    ficha = {
        "sha256": sha,
        "bytes": archivo.stat().st_size,
        "resolucion": reg.get("resolucion"),
        "fuente": f"generada en el episodio {episodio} y aprobada en su parada 1; {reg['fuente']}",
        "modelo": reg["modelo"],
        "licencia": reg["licencia"],
        "url": reg.get("url"),
        "origen": reg.get("origen") or "",
        "episodio": episodio,
        "entra": f"{cuando}, al seguir tras la parada 1 del episodio (lib/escena/biblia.py → incorpora)",
    }
    # `derivado_de` no se copia: es una ruta dentro del run del episodio, y en el run que la traiga no existiría. De
    # dónde sale lo dice `crudo`.
    ficha.update({c: reg[c] for c in ("seed", "operacion") if c in reg})
    ruta, crudo = _crudo_de(reg, run_dir)
    if ruta is not None:
        ficha["crudo"] = {
            "fichero": ruta.name,
            "sha256": _sha256(ruta) if ruta.is_file() else None,
            "donde": (
                f"{obrero.muestra(ruta, run_dir)} del run del episodio {episodio} (fuera del repositorio; se regenera "
                "con su prompt, su semilla y sus pesos)"
            ),
            **{c: crudo[c] for c in _DEL_CRUDO if c in crudo},
        }
    return ficha


def _entrada_del_indice(entrada: Mapping, ficha: Mapping) -> dict:
    """Qué es la imagen, para buscarla al escribir el guion de otro episodio (el esquema de `indice.json`).

    El `episodio` es el de la ficha de su fichero, el que lo generó: un nombre nuevo que apunta a un fichero idéntico
    de otro episodio dice ese otro, como su procedencia (revisión de F6.4b, R5). Un fichero importado sin episodio
    (F6.3) no lo lleva.
    """
    crudo = ficha.get("crudo") or {}
    # El tipo sale del activo que la generó; una pieza separada con SAM lleva `de` en su entrada, y un fondo lo dice
    # la operación del obrero que lo hizo.
    if entrada.get("de"):
        tipo = "pieza"
    elif ficha.get("operacion") == "fondo":
        tipo = "fondo"
    else:
        tipo = crudo.get("tipo_activo") or "imagen"
    salida = {"episodio": ficha["episodio"]} if ficha.get("episodio") else {}
    salida["tipo"] = tipo
    for campo in ("pj", "vista", "de_pie", "base", "de", "que"):
        valor = entrada.get(campo, crudo.get(campo))
        if valor is not None:
            salida[campo] = valor
    if crudo.get("fichero"):
        salida["crudo"] = crudo["fichero"]
    return salida


def incorpora(canal_dir: str | Path, dir_activos: str | Path, *, episodio: str, usadas: Iterable[str]) -> dict:
    """Las imágenes NUEVAS de un episodio entran en la biblioteca del canal, con su procedencia y su sha256.

    Es la decisión del 29-09 (addendum fila 208): lo que el usuario aprueba en la parada 1 se queda para los
    episodios siguientes. **La llama la etapa `escena`**, que solo corre tras la parada 1 (`pipeline._exige_parada`):
    antes de esa parada no entra nada.

    **Solo entra lo que usa el guion de escena** (`usadas`, `Guion.usadas`), con las piezas de cada figura usada (la
    misma regla con que `trae` las hace viajar). El catálogo de un run solo se fusiona —ni el obrero ni `trae` quitan
    nada—, así que una imagen que el usuario rechazó en la parada 1 y que el guion ya no pide sigue en él; sin este
    filtro entraría en la biblioteca como aprobada (revisión de F6.4b, R4). Sale en `no_entran` con su motivo.

    Qué es nuevo: cada imagen del catálogo del run (`dir_activos`) que no llegó de la biblioteca (lo que trae `trae`
    lleva `desde_la_biblioteca` en su registro). Para cada una:

    - **no estaba**: entran el fichero en `img/`, su ficha en `procedencia.json` (la de su registro en el run, con el
      crudo del que sale, su prompt y su semilla, y el `episodio`) y su entrada en `catalogo.json` e `indice.json`;
    - **ya estaba igual** (el mismo fichero y la misma entrada): no se duplica ni se reescribe;
    - **la puso este mismo episodio y ha cambiado** (se rehizo y volvió a pasar la parada 1): se actualiza;
    - **la biblioteca tiene otra con ese nombre, o su fichero es el de otra imagen**, y no la puso este episodio: no
      se pisa, y se dice en `no_entran`. Tampoco entra lo que no tiene su procedencia completa (decisión 5).

    Devuelve {"carpeta", "entran", "actualizadas", "ya_estaban", "no_entran": {nombre: motivo}}.
    """
    if not isinstance(episodio, str) or not episodio:
        raise ErrorDeBiblioteca("incorpora necesita el episodio (su run_id): es lo que la ficha apunta como origen")
    dir_activos = Path(dir_activos)
    run_dir = dir_activos.parent
    bib = _lee_o_vacia(canal_dir)
    catalogo, procedencia, indice = dict(bib.catalogo), dict(bib.procedencia), dict(bib.indice)
    cuando = datetime.now().isoformat(timespec="seconds")
    resultado: dict = {"carpeta": bib.carpeta, "entran": [], "actualizadas": [], "ya_estaban": [], "no_entran": {}}
    copias: dict[Path, Path] = {}
    catalogo_run = obrero.lee_catalogo(dir_activos)["imagenes"]
    usa = set(usadas)
    usa |= {m for n in list(usa) for m, e in catalogo_run.items() if m.startswith(n + "_") and es_pieza(m, e)}
    for nombre, entrada in catalogo_run.items():
        archivo = obrero.archivo_de(dir_activos, entrada)
        reg = obrero.registro_de_origen(archivo) if archivo.is_file() else None
        if reg is not None and reg.get("desde_la_biblioteca"):
            resultado["ya_estaban"].append(nombre)  # la trajo `trae`: es de la biblioteca, no de este episodio
            continue
        if nombre not in usa:
            resultado["no_entran"][nombre] = (
                "el guion de escena no la usa (rechazada en la parada 1, o ya no sale en el episodio)"
            )
            continue
        if entrada.get("del_episodio"):
            resultado["no_entran"][nombre] = (
                "sale de una lámina de este episodio (`obrero.fondo(..., del_episodio=True)`): no vale para otro, "
                "y se queda en el run"
            )
            continue
        if not archivo.is_file():
            resultado["no_entran"][nombre] = f"su imagen no está en el run ({archivo.name})"
            continue
        motivo = "no tiene registro de procedencia en el run" if reg is None else _que_le_falta(reg)
        if motivo:
            resultado["no_entran"][nombre] = motivo
            continue
        sha = _sha256(archivo)
        clave = f"{IMG}/{archivo.name}"
        destino = bib.carpeta / IMG / archivo.name
        if nombre in catalogo:
            previo = bib.carpeta / IMG / Path(str(catalogo[nombre]["src"])).name
            if previo == destino and previo.is_file() and _sha256(previo) == sha and catalogo[nombre] == entrada:
                resultado["ya_estaban"].append(nombre)
                continue
            if not _es_del_episodio(procedencia.get(f"{IMG}/{previo.name}"), episodio):
                resultado["no_entran"][nombre] = (
                    f"la biblioteca ya tiene otra «{nombre}» (de {_de_quien(bib, nombre)}) y no se pisa: esta se queda "
                    "solo en este episodio. Si tiene que entrar, dale otro nombre"
                )
                continue
            estado = "actualizadas"
        else:
            estado = "entran"
        igual = destino.is_file() and _sha256(destino) == sha
        if destino.is_file() and not igual and not _es_del_episodio(procedencia.get(clave), episodio):
            resultado["no_entran"][nombre] = f"su fichero {clave} es el de otra imagen de la biblioteca y no se pisa"
            continue
        if not igual:
            copias[archivo] = destino
        if not (igual and clave in procedencia):
            procedencia[clave] = _ficha(reg, archivo, sha, run_dir, episodio, cuando)
        catalogo[nombre] = dict(entrada)
        indice[nombre] = _entrada_del_indice(entrada, procedencia[clave])
        resultado[estado].append(nombre)
    if resultado["entran"] or resultado["actualizadas"]:
        # Primero los ficheros y su procedencia; el catálogo, lo último: es lo que hace visible un nombre a `trae`.
        (bib.carpeta / IMG).mkdir(parents=True, exist_ok=True)
        for origen, destino in copias.items():
            shutil.copy2(origen, destino)
        _escribe(bib.carpeta / PROCEDENCIA, "ficheros", procedencia)
        _escribe(bib.carpeta / INDICE, "imagenes", indice)
        _escribe(bib.carpeta / CATALOGO, "imagenes", catalogo)
    return resultado
