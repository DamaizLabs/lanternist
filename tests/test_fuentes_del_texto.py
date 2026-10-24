"""Las fuentes del texto de la miniatura y del banner: las declara el canal y viajan con su licencia (OC1.4).

Correr: .venv\\Scripts\\python -m pytest -q tests/test_fuentes_del_texto.py

**Por qué.** Hasta OC1.4, `lib/miniatura.py` dibujaba el texto con la primera fuente de una lista de Windows (Impact,
Segoe UI Black o Arial), y el banner del canal usaba la misma. Era el estudio eligiendo la letra del canal (F4.9), la
letra no llegaba a `assets.json` (decisión 5) y no se podía redistribuir. Es el caso que OC1.2 arregló con Georgia en
los rótulos, y se arregla igual: el perfil nombra un fichero de `datos/escena/fuentes/`, con su licencia y su
`CREDITOS.json`, y la etapa que dibuja el texto copia la fuente a su carpeta con su registro.

Cada prueba que acepta tiene su control que se niega: sin la clave, con una fuente del sistema, con una fuente sin
procedencia o con una copia cambiada.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from PIL import Image

from lib import canal_marca, config, miniatura, provenance
from lib.escena import audio

RAIZ = Path(__file__).resolve().parent.parent
PERFILES = sorted((RAIZ / "canales").glob("*/perfil.json"))
CLAVES = (miniatura.CLAVE_FUENTE, canal_marca.CLAVE_FUENTE_DEL_BANNER)
ANTON = "Anton-Regular.ttf"


def _perfil(ruta: str, valor) -> dict:
    """Un perfil con solo `ruta` declarada."""
    perfil: dict = {}
    *bloques, clave = ruta.split(".")
    nodo = perfil
    for bloque in bloques:
        nodo = nodo.setdefault(bloque, {})
    nodo[clave] = valor
    return perfil


# ── Las declara el perfil ──────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ruta", PERFILES, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("clave", CLAVES)
def test_cada_canal_declara_sus_dos_fuentes_de_la_biblioteca(ruta: Path, clave: str):
    perfil = json.loads(ruta.read_text(encoding="utf-8"))
    fuente = miniatura.fuente_declarada(perfil, clave)
    assert fuente.parent == config.ESCENA_FUENTES_DIR and fuente.is_file()


@pytest.mark.parametrize("clave", CLAVES)
def test_la_fuente_declarada_sale_de_la_biblioteca(clave):
    assert miniatura.fuente_declarada(_perfil(clave, ANTON), clave) == config.ESCENA_FUENTES_DIR / ANTON


@pytest.mark.parametrize("clave", CLAVES)
def test_control_sin_la_clave_no_hay_fuente_por_defecto(clave):
    with pytest.raises(ValueError, match=re.escape(clave)) as error:
        miniatura.fuente_declarada({}, clave)
    assert ANTON in str(error.value), "el mensaje dice qué fuentes hay para escribir"


@pytest.mark.parametrize(
    "valor",
    [
        "impact.ttf",  # una fuente de Windows: no está en la biblioteca
        "C:/Windows/Fonts/impact.ttf",  # ni con su ruta
        f"../fuentes/{ANTON}",  # ni saliendo de la carpeta
        "",
        42,
    ],
)
def test_control_una_fuente_que_no_es_de_la_biblioteca_se_niega(valor):
    with pytest.raises(ValueError, match=re.escape(miniatura.CLAVE_FUENTE)):
        miniatura.fuente_declarada(_perfil(miniatura.CLAVE_FUENTE, valor), miniatura.CLAVE_FUENTE)


def _biblioteca_de_prueba(tmp_path: Path, monkeypatch, *, con_entrada: bool = True) -> Path:
    """Una copia de la biblioteca de fuentes con Anton, para poder estropearla sin tocar la de verdad."""
    carpeta = tmp_path / "fuentes"
    carpeta.mkdir()
    shutil.copy(config.ESCENA_FUENTES_DIR / ANTON, carpeta / ANTON)
    creditos = json.loads((config.ESCENA_FUENTES_DIR / config.ESCENA_CREDITOS).read_text(encoding="utf-8"))
    ficheros = {ANTON: creditos["ficheros"][ANTON]} if con_entrada else {}
    (carpeta / config.ESCENA_CREDITOS).write_text(json.dumps({"ficheros": ficheros}), encoding="utf-8")
    monkeypatch.setattr(config, "ESCENA_FUENTES_DIR", carpeta)
    return carpeta


def test_control_una_fuente_sin_su_entrada_de_procedencia_se_niega(tmp_path, monkeypatch):
    _biblioteca_de_prueba(tmp_path, monkeypatch, con_entrada=False)
    with pytest.raises(ValueError, match="CREDITOS.json"):
        miniatura.fuente_declarada(_perfil(miniatura.CLAVE_FUENTE, ANTON), miniatura.CLAVE_FUENTE)


def test_el_banner_para_con_su_clave_antes_de_generar_nada():
    with pytest.raises(canal_marca.MarcaError, match=re.escape("marca.banner.fuente")):
        canal_marca.fuente_del_banner({"marca": {"banner": {"escena": "a shelf"}}})


# ── Llega a assets.json con su licencia ──────────────────────────────────────────────────────────────────────────


def test_la_copia_de_la_fuente_entra_en_el_assets_json_del_run_con_su_licencia(tmp_path):
    """La condición real de la etapa: la copia en su carpeta del run y `provenance.sync` sobre el run entero."""
    run = tmp_path / "run"
    run.mkdir()
    registro = miniatura.copia_la_fuente(
        config.ESCENA_FUENTES_DIR / ANTON, run / miniatura.CARPETA_DE_LA_FUENTE, etapa="thumbnail"
    )
    assert registro["sha256"] == audio._sha256(config.ESCENA_FUENTES_DIR / ANTON)
    conteo = provenance.sync(run, verbose=False)
    assert conteo["cuadra"], conteo
    (entrada,) = provenance.read_ledger(run)["assets"]
    assert entrada["id"] == f"{miniatura.CARPETA_DE_LA_FUENTE}/{ANTON}"
    assert entrada["tipo"] == "fuente" and entrada["etapa"] == "thumbnail"
    assert entrada["licencia"].startswith("SIL Open Font License 1.1")
    assert entrada["url"].startswith("https://github.com/google/fonts/")
    assert entrada["modelo"].startswith("no aplica"), "una letra no la genera ningún modelo: fuera de la declaración"


def test_la_carpeta_de_la_fuente_se_rehace_y_solo_queda_la_ultima(tmp_path):
    carpeta = tmp_path / miniatura.CARPETA_DE_LA_FUENTE
    miniatura.copia_la_fuente(config.ESCENA_FUENTES_DIR / "Gelasio-VariableFont_wght.ttf", carpeta, etapa="thumbnail")
    miniatura.copia_la_fuente(config.ESCENA_FUENTES_DIR / ANTON, carpeta, etapa="thumbnail")
    registros = json.loads((carpeta / provenance.LIBRARY_RECORDS_FILENAME).read_text(encoding="utf-8"))
    assert sorted(p.name for p in carpeta.iterdir() if p.suffix == ".ttf") == [ANTON]
    assert [Path(r["file"]).name for r in registros] == [ANTON]


def test_control_una_fuente_cambiada_desde_su_entrada_no_se_copia(tmp_path, monkeypatch):
    biblioteca = _biblioteca_de_prueba(tmp_path, monkeypatch)
    with open(biblioteca / ANTON, "ab") as f:
        f.write(b"\0")
    with pytest.raises(audio.ErrorDeAudio, match="ha cambiado"):
        miniatura.copia_la_fuente(biblioteca / ANTON, tmp_path / "run" / "copia", etapa="thumbnail")


# ── Se dibuja con ella ───────────────────────────────────────────────────────────────────────────────────────────


def test_la_miniatura_se_compone_con_la_fuente_declarada(tmp_path):
    lienzo = tmp_path / "miniatura.png"
    Image.new("RGB", (1280, 720), (120, 110, 100)).save(lienzo)
    medido = miniatura.compon_texto(lienzo, "HOW A ZIP WORKS", fuente=config.ESCENA_FUENTES_DIR / ANTON)
    veredicto = miniatura.comprueba(lienzo, texto="HOW A ZIP WORKS", medido_texto=medido)
    assert medido["fuente"] == ANTON and veredicto["cumple"], veredicto["fallos"]


def test_el_banner_se_compone_con_la_fuente_declarada(tmp_path):
    lienzo = tmp_path / "banner.png"
    Image.new("RGB", canal_marca.BANNER, (200, 190, 170)).save(lienzo)
    medido = canal_marca.compon_texto_del_banner(
        lienzo, "Lantern Slides", "Small stories of everyday inventions.", fuente=config.ESCENA_FUENTES_DIR / ANTON
    )
    assert medido["fuente"] == ANTON
    nombre = medido["lineas"][0]
    assert nombre["cabe_en_el_area_segura"] and nombre["cumple_altura"] and nombre["cumple_contraste"]


# ── Ninguna letra de lo que se entrega sale de Windows ──────────────────────────────────────────────────────────

_FUENTE_DE_WINDOWS = re.compile(r"[A-Za-z]:[\\/]+Windows[\\/]+Fonts", re.IGNORECASE)
# Lo que dibuja algo que se publica: la miniatura, el banner, el avatar y la marca de agua.
DIBUJAN_LO_QUE_SE_PUBLICA = ("lib/miniatura.py", "lib/canal_marca.py")


@pytest.mark.parametrize("ruta", DIBUJAN_LO_QUE_SE_PUBLICA)
def test_nada_de_lo_que_se_publica_lee_una_fuente_de_windows(ruta):
    assert not _FUENTE_DE_WINDOWS.search((RAIZ / ruta).read_text(encoding="utf-8"))


def test_control_la_lista_de_antes_de_OC1_4_se_caza():
    assert _FUENTE_DE_WINDOWS.search('TIPOGRAFIAS = ("C:/Windows/Fonts/impact.ttf",)')
