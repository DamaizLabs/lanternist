"""El conteo cruzado de la procedencia (decisión 5), vigilado por el arnés.

Correr: .venv\\Scripts\\python -m pytest -q tests

**Por qué existe este fichero.** Hasta F4.11 no había **ni una** prueba de `lib/provenance.py`
—el módulo que hace cumplir la decisión 5— y eso se pagó: la etapa de la onda estrenó el
directorio `onda/` sin declararlo en `WORK_DIRS`, así que el montaje que aparta ahí contaba como
**asset sin procedencia** y `conteo.cuadra` se quedaba en `false`. El gate estaba en verde y lo
cazó la revisión de F4.11 a mano.

Lo que se vigila no es la lista de directorios —eso envejece— sino **el mecanismo**: que un
intermedio declarado se cuente como intermedio, que uno sin declarar se grite, y que las dos
direcciones del conteo sigan mirándose. La prueba de abajo falla en rojo la próxima vez que una
etapa estrene carpeta sin decirlo, que es exactamente cuando hace falta.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from lib import provenance

RAIZ = Path(__file__).resolve().parent.parent

# Los directorios que las etapas usan para apartar el vídeo a medio hacer, escritos **a mano** y
# no leídos de `provenance.WORK_DIRS`. La diferencia no es estilo: parametrizar desde la lista que
# se quiere vigilar es una tautología —quitar `onda` de `WORK_DIRS` no rompería nada, solo
# borraría el caso de prueba— y es el mismo fallo que la auditoría de F4.8 ya cazó una vez. Aquí
# la lista es la afirmación: si una etapa deja de declarar su carpeta, esto se pone en rojo.
INTERMEDIOS_ESPERADOS = {
    "montaje": "los planos por separado y las placas de parálaje, antes de encadenarlos",
    "musica": "los tramos de ACE-Step y el vídeo previo a la mezcla del lecho",
    "onda": "el montaje previo a dibujar la onda de ecualizador (F4.11)",
    "subtitulos": "el ASS y el vídeo previo al quemado",
    "crudo": (
        "Lo que sale del motor de voz ANTES del post-proceso (06-09). Se guarda para no repetir "
        "diez minutos de GPU cuando solo cambia un umbral de las pausas o de la limpieza: el "
        "post-proceso es determinista y no necesita motor. El asset publicable es el wav final, "
        "que si lleva su `generacion-voz.json` con motor, semilla y parametros — el crudo es un "
        "paso reversible del mismo audio ya registrado, igual que `montaje/` lo es del video."
    ),
    "limpieza": (
        "El trabajo de la limpieza de voz por marcas (06-09): la alineacion que dice donde hay "
        "palabras y el informe de que se callo. No produce ningun medio nuevo — reescribe los wav "
        "que ya estan registrados—, asi que aqui dentro no hay nada publicable."
    ),
    "activos-trabajo": (
        "El trabajo de los activos del motor de escena (F6.2c): los lienzos de croma lisos que se le pasan "
        "a Qwen como lienzo y los trabajos y logs del obrero. Un lienzo liso es un color de un tamaño, "
        "que el registro de la imagen generada ya nombra; lo que tiene procedencia vive en `activos/`."
    ),
    "composicion": (
        "La composición de HyperFrames del motor de escena (F6.2d): `index.html` y sus `assets/`, que son COPIAS de "
        "los recortes de `activos/`, de la biblioteca del run y del sonido de `sonido/`, igual que los planos de "
        "`montaje/` lo son de las láminas."
    ),
    "sonido": (
        "El sonido derivado del motor de escena (F6.2d): la narración con sus pausas (los wav de `audio/` uno tras "
        "otro con silencios), el lecho ya apartado bajo la voz (derivado de `lecho.wav`, que tiene su registro) y el "
        "vídeo antes de normalizar su sonoridad."
    ),
    "revision": (
        "Las páginas de las dos paradas del usuario (F6.2d), los fotogramas de `snapshot` y los logs de HyperFrames: "
        "son para mirar, no entran en el vídeo."
    ),
}

# Los directorios que un módulo de `lib/` crea dentro del run y que **no** son intermedios: lo
# que hay dentro son assets publicables, con su procedencia registrada. Están aquí para que la
# prueba de abajo pueda distinguirlos de los de trabajo — que es la clasificación que importa.
DIRECTORIOS_DE_ASSETS = {
    "slides": "las láminas que genera el adaptador de imagen",
    "audio": "los .wav de la narración",
    "activos": (
        "los activos del motor de escena (F6.2c): lo que genera Qwen, los lienzos de referencia y los "
        "recortes del obrero, cada uno con su registro en generacion-imagenes.json"
    ),
    "biblioteca": (
        "la copia de los efectos y las fuentes del estudio que usa un episodio del motor de escena (F6.2d), con su "
        "registro en biblioteca-escena.json: son de terceros (Pixabay, OFL) y entran en el vídeo"
    ),
    "sfx": "dentro de `biblioteca/`: los efectos de sonido del episodio (lib/escena/audio.py)",
    "fuentes": "dentro de `biblioteca/`: las fuentes que pide el CSS del canal (lib/escena/audio.py)",
}


def _directorios_del_run_en_lib() -> dict[str, list[str]]:
    """Los directorios que `lib/` construye dentro de un run, leídos del AST.

    Se busca `<algo con «run» u «out» en el nombre> / "<literal sin extensión>"`, que es la forma
    en que los módulos arman sus rutas de trabajo. Es la parte que **ata la prueba al código**:
    sin esto, las dos listas de arriba se vigilarían entre sí y una etapa nueva que no apareciera
    en ninguna pasaría en verde (recomendación 6 de `review_F4.11`).
    """
    hallados: dict[str, list[str]] = {}
    for py in sorted((RAIZ / "lib").rglob("*.py")):
        for nodo in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if not (isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.Div)):
                continue
            derecha = nodo.right
            if not (isinstance(derecha, ast.Constant) and isinstance(derecha.value, str)):
                continue
            nombre = derecha.value
            # Un literal con punto, barra o `%` es un fichero o una plantilla, no un directorio.
            if not nombre or any(c in nombre for c in "./%\\"):
                continue
            izquierda = ast.unparse(nodo.left).lower()
            if "run" in izquierda or izquierda in {"out", "salida"}:
                hallados.setdefault(nombre, []).append(f"{py.name}:{nodo.lineno}")
    return hallados


# Un asset y su entrada, que es el mínimo con el que el conteo cuadra.
LAMINA = "slides/slide-01.png"
ENTRADA = {
    "id": LAMINA,
    "tipo": "imagen",
    "fuente": "Qwen-Lightning local",
    "licencia": "Apache-2.0",
    "url": "local",
    "registro": provenance.ADAPTER_REGISTRO,
}


def _run(tmp_path: Path, extras: tuple[str, ...] = ()) -> Path:
    """Un run de juguete: una lámina registrada y los ficheros que se le pidan."""
    run = tmp_path / "run"
    (run / "slides").mkdir(parents=True)
    (run / LAMINA).write_bytes(b"png")
    for relativo in extras:
        destino = run / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"mp4")
    return run


def test_un_run_limpio_cuadra(tmp_path: Path):
    """El caso base, para que los de abajo signifiquen algo."""
    informe = provenance.audit(_run(tmp_path), [ENTRADA])

    assert informe["cuadra"]
    assert informe["archivos_medios"] == 1
    assert informe["sin_registrar"] == []


def test_las_etapas_que_apartan_video_tienen_su_carpeta_declarada():
    """El corazón de esta prueba: la lista escrita a mano contra la del código.

    Lo que esto habría cazado el día que se escribió: `onda/` fuera de `WORK_DIRS`, con el
    `conteo.cuadra` de cada run de un canal en `false` por un fichero que no es un asset.
    """
    faltan = {c: por_que for c, por_que in INTERMEDIOS_ESPERADOS.items() if c not in provenance.WORK_DIRS}
    assert not faltan, (
        f"estas carpetas guardan vídeo a medio hacer y no están en provenance.WORK_DIRS: {faltan}. "
        "Sin declararlas, su .mp4 cuenta como asset sin procedencia y el conteo cruzado de la "
        "decisión 5 se queda en rojo para siempre."
    )

    de_mas = provenance.WORK_DIRS - set(INTERMEDIOS_ESPERADOS)
    assert not de_mas, (
        f"`WORK_DIRS` declara carpetas que esta prueba no conoce: {sorted(de_mas)}. Si una etapa "
        "nueva aparta vídeo ahí, añádela a INTERMEDIOS_ESPERADOS con su motivo; si lo que hay "
        "dentro son assets publicables, no puede ser un intermedio — es la lección de F4.0, que "
        "declaró `trabajo/` y dejó la marca del canal sin registrar."
    )


def test_todo_directorio_del_run_que_crea_lib_esta_clasificado():
    """La prueba atada al código: un directorio nuevo tiene que decir de qué lado está.

    Las dos listas de este fichero se vigilan entre sí, pero eso deja un hueco que señaló la
    revisión de F4.11: **una etapa nueva que no aparezca en ninguna de las dos pasa en verde**.
    Aquí los candidatos salen del AST de `lib/`, así que estrenar un directorio en el run obliga
    a clasificarlo — intermedio de trabajo o directorio de assets— y el que se olvide sale en
    rojo con su fichero y su línea.

    Es el mismo patrón que `tests/test_capas.py`, que lee el AST de `config.py` en vez de
    fiarse de una lista escrita.
    """
    encontrados = _directorios_del_run_en_lib()
    assert encontrados, "el AST no encontró ningún directorio del run: la heurística se ha roto"

    conocidos = set(INTERMEDIOS_ESPERADOS) | set(DIRECTORIOS_DE_ASSETS)
    sin_clasificar = {n: sitios for n, sitios in encontrados.items() if n not in conocidos}
    assert not sin_clasificar, (
        f"estos directorios del run no están clasificados: {sin_clasificar}. Si guardan vídeo a "
        "medio hacer, van a INTERMEDIOS_ESPERADOS **y** a provenance.WORK_DIRS; si guardan assets "
        "publicables, a DIRECTORIOS_DE_ASSETS y con su procedencia registrada. Lo que no vale es "
        "dejarlo sin decidir: el conteo cruzado de la decisión 5 lo dará por asset sin procedencia."
    )


@pytest.mark.parametrize("carpeta", sorted(INTERMEDIOS_ESPERADOS))
def test_cada_directorio_de_trabajo_cuenta_como_intermedio_y_no_como_asset(tmp_path: Path, carpeta: str):
    """Un `.mp4` apartado por una etapa no es un asset: es el mismo vídeo antes de un paso.

    `onda/` es el que faltaba (F4.11), y va en la misma prueba que los otros tres porque el
    fallo no fue de ese directorio: fue de que nadie comprobaba la lista.
    """
    run = _run(tmp_path, [f"{carpeta}/final-sin-algo.mp4"])

    informe = provenance.audit(run, [ENTRADA])

    assert informe["cuadra"], f"el intermedio de {carpeta}/ se está contando como asset sin procedencia"
    assert informe["intermedios_de_montaje"] == 1
    assert informe["archivos_medios"] == 1, "el intermedio no suma a los medios publicables"
    assert informe["sin_registrar"] == []


def test_un_medio_en_una_carpeta_no_declarada_se_grita(tmp_path: Path):
    """El contrapeso: sin esto, la prueba de arriba pasaría con `WORK_DIRS` = todo.

    Es el modo de fallo real de F4.11 reproducido: una etapa estrena carpeta, mete ahí un `.mp4`
    y el conteo se queda en `false` — en el `assets.json` del run **y en la copia que entra en
    git**, que es lo que lo hacía bloqueante.
    """
    run = _run(tmp_path, ["onda_nueva/final-sin-algo.mp4"])

    informe = provenance.audit(run, [ENTRADA])

    assert not informe["cuadra"]
    assert informe["sin_registrar"] == ["onda_nueva/final-sin-algo.mp4"]
    assert informe["intermedios_de_montaje"] == 0
    assert "PROCEDENCIA INCOMPLETA" in provenance.format_report(informe, etapa="onda")


def test_una_entrada_sin_su_archivo_tambien_se_grita(tmp_path: Path):
    """La otra dirección del conteo: el registro promete un asset que ya no está."""
    run = _run(tmp_path)
    fantasma = {**ENTRADA, "id": "slides/slide-99.png"}

    informe = provenance.audit(run, [ENTRADA, fantasma])

    assert not informe["cuadra"]
    assert informe["sin_archivo"] == ["slides/slide-99.png"]


def test_los_metadatos_no_son_medios(tmp_path: Path):
    """Los JSON de cada etapa viven en el run y no son assets: se cuentan aparte."""
    run = _run(tmp_path)
    (run / "montaje.json").write_text(json.dumps({"detalle": []}), encoding="utf-8")

    informe = provenance.audit(run, [ENTRADA])

    assert informe["cuadra"]
    assert informe["archivos_no_medios"] == 1
    assert informe["archivos_medios"] == 1


# ── Un run archivado no estropea su registro (fila 224) ──────────────────────────────────────────
# `scripts/archiva_run.py` se lleva los medios a D: y deja el expediente. Auditar ese run daba «no cuadra» y
# reescribía la copia versionada que cuadraba (deuda de la auditoría del commit del 10-09).


def _run_con_registro(tmp_path: Path, monkeypatch, *laminas: str) -> tuple[Path, Path]:
    """Un run con sus láminas registradas a mano, sincronizado una vez cuando todo estaba en disco."""
    espejo = tmp_path / "espejo"
    monkeypatch.setattr(provenance, "ASSETS_MIRROR_DIR", espejo)
    run = tmp_path / "run"
    entradas = []
    for lamina in laminas:
        (run / lamina).parent.mkdir(parents=True, exist_ok=True)
        (run / lamina).write_bytes(b"png")
        entradas.append({**ENTRADA, "id": lamina, "registro": provenance.MANUAL_REGISTRO})
    provenance._write_json(provenance.ledger_path(run), {"esquema": provenance.SCHEMA, "assets": entradas})
    assert provenance.sync(run, run_id="r1", verbose=False)["cuadra"]
    return run, espejo / "r1.json"


def test_un_run_archivado_conserva_la_copia_versionada_que_cuadraba(tmp_path: Path, monkeypatch):
    run, espejo = _run_con_registro(tmp_path, monkeypatch, LAMINA, "slides/slide-02.png")
    antes_espejo = espejo.read_bytes()
    for lamina in (LAMINA, "slides/slide-02.png"):
        (run / lamina).unlink()

    informe = provenance.sync(run, run_id="r1", verbose=False)

    assert informe["archivos_medios"] == 0 and not informe["cuadra"], "el informe dice la verdad"
    assert espejo.read_bytes() == antes_espejo, "la copia versionada no se toca"
    # El registro del run SÍ se reescribe: lo leen la subida y la lista de la marca, y un run sin medios no
    # puede salir como «cuadra» (auditoría del commit del 01-10, recomendación 1).
    local = json.loads(provenance.ledger_path(run).read_text(encoding="utf-8"))
    assert local["conteo"]["cuadra"] is False
    with pytest.raises(provenance.ProvenanceError):
        provenance.require_complete(run)


def test_la_segunda_auditoria_de_un_run_archivado_tampoco_toca_la_copia(tmp_path: Path, monkeypatch):
    """Tras la primera, el registro del run ya dice «no cuadra»: la guarda se fía de la copia, no de él."""
    run, espejo = _run_con_registro(tmp_path, monkeypatch, LAMINA)
    antes_espejo = espejo.read_bytes()
    (run / LAMINA).unlink()
    provenance.sync(run, run_id="r1", verbose=False)
    provenance.sync(run, run_id="r1", verbose=False)
    assert espejo.read_bytes() == antes_espejo


def test_control_si_falta_solo_una_parte_el_registro_se_degrada(tmp_path: Path, monkeypatch):
    """Que falte UNA lámina de dos es una pérdida real: se escribe y se ve."""
    run, espejo = _run_con_registro(tmp_path, monkeypatch, LAMINA, "slides/slide-02.png")
    (run / "slides/slide-02.png").unlink()

    informe = provenance.sync(run, run_id="r1", verbose=False)

    assert not informe["cuadra"] and informe["archivos_medios"] == 1
    assert json.loads(espejo.read_text(encoding="utf-8"))["conteo"]["cuadra"] is False


def test_control_un_run_que_nunca_cuadro_se_escribe_aunque_no_tenga_medios(tmp_path: Path, monkeypatch):
    """La guarda conserva un registro BUENO; no oculta un run que nunca tuvo sus medios."""
    monkeypatch.setattr(provenance, "ASSETS_MIRROR_DIR", tmp_path / "espejo")
    run = tmp_path / "run"
    run.mkdir()
    entrada = {**ENTRADA, "registro": provenance.MANUAL_REGISTRO}
    provenance._write_json(provenance.ledger_path(run), {"esquema": provenance.SCHEMA, "assets": [entrada]})

    provenance.sync(run, run_id="r1", verbose=False)

    espejo = json.loads((tmp_path / "espejo" / "r1.json").read_text(encoding="utf-8"))
    assert espejo["conteo"]["cuadra"] is False


# La URL de cada pieza (OC1.4): las láminas, la narración, el lecho musical y el `.srt` la llevan a `assets.json` desde
# su registro. Hasta OC1.4 las cuatro daban `url: null`, aunque la procedencia pide fuente, licencia y URL.
URL = "https://huggingface.co/ejemplo/modelo"
NORMALIZADORES = {
    "imagen": (provenance._image_entry, "file", "slides/slide-01.png"),
    "narración": (provenance._audio_entry, "file", "audio/slide-01.wav"),
    "música": (provenance._music_entry, "file", "lecho.wav"),
    "subtítulos": (provenance._subtitle_entry, "srt", "subir-al-canal/subtitulos.en.srt"),
}


@pytest.mark.parametrize("pieza", NORMALIZADORES)
def test_la_url_del_registro_llega_a_su_entrada(tmp_path: Path, pieza: str):
    normaliza, clave, ruta = NORMALIZADORES[pieza]
    entrada = normaliza(tmp_path, {clave: str(tmp_path / ruta), "licencia": "Apache-2.0", "url": URL})
    assert entrada["url"] == URL
    assert "url" not in entrada["detalle"], "la URL va en su campo, no repetida en el detalle"


@pytest.mark.parametrize("pieza", NORMALIZADORES)
def test_control_un_registro_sin_url_sigue_dando_none(tmp_path: Path, pieza: str):
    """Un registro anterior a OC1.4 no trae URL: la entrada lo dice con None, no se la inventa."""
    normaliza, clave, ruta = NORMALIZADORES[pieza]
    assert normaliza(tmp_path, {clave: str(tmp_path / ruta), "licencia": "Apache-2.0"})["url"] is None
