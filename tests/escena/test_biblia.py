"""La biblioteca de imágenes de un canal y cómo entra en un run (F6.3), con un canal ficticio y sin GPU.

Lo que se prueba, cada cosa con su control negativo:

- `biblia.trae`: copia cada imagen pedida y sus piezas al run, con su entrada de catálogo y su registro de procedencia
  (fuente, licencia y url, decisión 5); y PARA si la imagen cambió después de apuntar su sha256, si su registro no
  dice de dónde sale o si el episodio pide una que no está.
- La etapa `activos` con `Lote.biblioteca`: el episodio compone con lo que trajo, y la procedencia del run cuadra.
- El guion de un episodio como paquete (sus tramos se importan con `from . import`) y la capa del canal como
  `escena_del_canal`; la huella del guion cubre toda su carpeta.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from test_etapas import RUN_ID, gpu  # noqa: F401  (la fixture de la GPU falsa)
from utiles_escena import CATALOGO_PRUEBA, LAMINAS_PRUEBA
from utiles_pipeline import canal_de_prueba, guion_en_el_canal, perfil_de_prueba, prepara_run

from lib import config, provenance
from lib.escena import biblia, etapas, obrero
from lib.escena.episodio import Episodio, ErrorDeEpisodio, carga_canal, carga_guion

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="el sonido del motor de escena usa ffmpeg")

URL = "https://huggingface.co/Qwen/Qwen-Image-Edit-2511"
# Una pieza que se mece con `ana_pie` (su cola): viaja con ella aunque el episodio no la nombre.
PIEZA = {
    "ana_pie_cola": {"src": "assets/img/rueda.png", "w": 100, "h": 100, "ax": 50, "ay": 50, "k": 1, "off": [10, -300]}
}


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def biblioteca_de_prueba(canal: Path, run: Path) -> Path:
    """Pasa las imágenes del run de prueba a la biblioteca del canal (con su catálogo y su procedencia) y las quita del
    run: el episodio las tendrá que traer."""
    carpeta = config.biblioteca_del_canal(canal)
    (carpeta / "img").mkdir(parents=True, exist_ok=True)
    origen = config.activos_del_run(run)
    procedencia = {}
    for f in sorted((origen / "img").glob("*.png")):
        shutil.copy2(f, carpeta / "img" / f.name)
        procedencia[f"img/{f.name}"] = {
            "sha256": _sha(f),
            "fuente": "generada en local con ComfyUI (prueba)",
            "modelo": "Qwen-Image-Edit-2511 GGUF Q6_K + LoRA Lightning 8 pasos",
            "licencia": "Apache-2.0",
            "url": URL,
            "origen": "una imagen de prueba",
            "seed": 7,
        }
    (carpeta / "catalogo.json").write_text(
        json.dumps({"imagenes": {**CATALOGO_PRUEBA, **PIEZA}}, ensure_ascii=False), encoding="utf-8"
    )
    (carpeta / "procedencia.json").write_text(json.dumps({"ficheros": procedencia}), encoding="utf-8")
    shutil.rmtree(origen)
    return carpeta


@pytest.fixture
def con_biblioteca(tmp_path, gpu):  # noqa: F811
    perfil = perfil_de_prueba()
    canal = canal_de_prueba(tmp_path / "canal", perfil)
    run = prepara_run(tmp_path / "videos" / RUN_ID, LAMINAS_PRUEBA)
    carpeta = biblioteca_de_prueba(canal, run)
    guion_en_el_canal(canal, RUN_ID, "biblioteca")
    ep = Episodio(run_dir=run, run_id=RUN_ID, canal_dir=canal, perfil=perfil, idioma="en")
    return {"ep": ep, "biblioteca": carpeta, "gpu": gpu}


# ------------------------------------------------------------------------------------------ biblia.trae
def test_trae_copia_cada_imagen_con_sus_piezas_su_catalogo_y_su_procedencia(con_biblioteca):
    ep = con_biblioteca["ep"]
    traidas = biblia.trae(ep.canal_dir, ["ana_pie", "parque"], ep.dir_activos)
    assert traidas == ["ana_pie", "ana_pie_cola", "parque"], "la cola de ana_pie viaja con ella"
    catalogo = ep.catalogo()
    assert catalogo["ana_pie_cola"]["off"] == [10, -300] and set(catalogo) == set(traidas)
    registros = json.loads((ep.dir_activos / "img" / provenance.IMAGE_RECORDS_FILENAME).read_text(encoding="utf-8"))
    assert {Path(r["file"]).name for r in registros} == {"figura-a.png", "rueda.png", "fondo-a.png"}
    assert all(
        r["licencia"] == "Apache-2.0" and r["url"] == URL and "biblioteca del canal" in r["fuente"] for r in registros
    )
    # En el assets.json del run, cada imagen con su fuente, su licencia y su url, y el conteo cuadra.
    informe = provenance.sync(ep.run_dir, verbose=False)
    assert informe["cuadra"], informe
    imagenes = [a for a in provenance.read_ledger(ep.run_dir)["assets"] if a["id"].startswith("activos/img/")]
    assert len(imagenes) == 3 and all(a["url"] == URL and a["licencia"] == "Apache-2.0" for a in imagenes)
    # Traer otra vez da lo mismo (una entrada por fichero en el assets.json, la última).
    biblia.trae(ep.canal_dir, ["ana_pie", "parque"], ep.dir_activos)
    assert provenance.sync(ep.run_dir, verbose=False)["cuadra"]


def test_control_una_imagen_cambiada_tras_apuntar_su_sha256_no_entra(con_biblioteca):
    ep, carpeta = con_biblioteca["ep"], con_biblioteca["biblioteca"]
    ruta = carpeta / "img" / "fondo-a.png"
    ruta.write_bytes(ruta.read_bytes() + b"\0")
    with pytest.raises(biblia.ErrorDeBiblioteca, match="ha cambiado"):
        biblia.trae(ep.canal_dir, ["parque"], ep.dir_activos)
    assert not (ep.dir_activos / "img" / "fondo-a.png").exists()


@pytest.mark.parametrize("quita", ["licencia", "fuente", "url", "sha256"])
def test_control_una_imagen_sin_procedencia_completa_no_entra(con_biblioteca, quita):
    ep, carpeta = con_biblioteca["ep"], con_biblioteca["biblioteca"]
    datos = json.loads((carpeta / "procedencia.json").read_text(encoding="utf-8"))
    del datos["ficheros"]["img/fondo-a.png"][quita]
    (carpeta / "procedencia.json").write_text(json.dumps(datos), encoding="utf-8")
    with pytest.raises(biblia.ErrorDeBiblioteca, match=quita):
        biblia.trae(ep.canal_dir, ["parque"], ep.dir_activos)


def test_una_forma_sin_modelo_puede_no_tener_url_y_una_de_un_modelo_no(con_biblioteca):
    """La url es la del modelo que dibujó la imagen: una cadena dibujada por geometría no tiene ninguna."""
    ep, carpeta = con_biblioteca["ep"], con_biblioteca["biblioteca"]
    datos = json.loads((carpeta / "procedencia.json").read_text(encoding="utf-8"))
    ficha = datos["ficheros"]["img/rueda.png"]
    ficha.update(url=None, modelo="ninguno: geometría, sin modelo generativo", licencia="obra propia del estudio")
    (carpeta / "procedencia.json").write_text(json.dumps(datos), encoding="utf-8")
    assert biblia.trae(ep.canal_dir, ["rueda"], ep.dir_activos) == ["rueda"]
    # Control: la misma ficha con un modelo generativo y sin url no entra.
    ficha["modelo"] = "Qwen-Image-Edit-2511"
    (carpeta / "procedencia.json").write_text(json.dumps(datos), encoding="utf-8")
    with pytest.raises(biblia.ErrorDeBiblioteca, match="url"):
        biblia.trae(ep.canal_dir, ["rueda"], ep.dir_activos)


def test_control_un_nombre_que_no_esta_en_la_biblioteca_para(con_biblioteca):
    ep = con_biblioteca["ep"]
    with pytest.raises(biblia.ErrorDeBiblioteca, match="no están en la biblioteca"):
        biblia.trae(ep.canal_dir, ["parque", "nora_mira"], ep.dir_activos)
    assert obrero.lee_catalogo(ep.dir_activos)["imagenes"] == {}


# ------------------------------------------------------------------------------------------ en la etapa activos
def test_el_episodio_compone_con_lo_que_trae_de_la_biblioteca(con_biblioteca):
    ep = con_biblioteca["ep"]
    etapas.alinea(ep)
    activos = etapas.activos(ep)
    assert activos["traidas"] == len(CATALOGO_PRUEBA) + 1 and activos["generados"] == 0 and activos["faltan"] == []
    assert "Traídas de la biblioteca del canal" in activos["pagina"].read_text(encoding="utf-8")
    escena = etapas.escena(ep)
    assert escena["defectos"] == {k: [] for k in escena["defectos"]}
    informe = provenance.sync(ep.run_dir, verbose=False)
    assert informe["cuadra"], informe
    # Los cinco ficheros del catálogo de prueba: fondo-a, fondo-b, figura-a, figura-b y rueda (que es también el de la
    # pieza ana_pie_cola). El lote pide el catálogo entero, así que llegan todos, cada uno con su registro.
    assert informe["por_tipo"]["imagen"] == 5
    # La composición lleva las imágenes que trajo; ninguna de fuera de la carpeta del run.
    assert (config.composicion_del_run(ep.run_dir) / "assets" / "img" / "figura-b.png").is_file()


def test_control_sin_traerlas_el_episodio_no_compone(con_biblioteca, monkeypatch):
    """Con el catálogo del run vacío, el guion no encuentra sus imágenes.

    La biblioteca del canal no se usa a escondidas: solo entra lo que trae la etapa de activos.
    """
    ep = con_biblioteca["ep"]
    etapas.alinea(ep)
    with pytest.raises(Exception, match="no está en el catálogo"):
        etapas.escena(ep)
    assert not (config.composicion_del_run(ep.run_dir) / "index.html").exists()


# ------------------------------------------------------------------------------------------ paquetes y huella
def _canal_con_capa(tmp_path: Path, nombre: str, valor: str) -> Path:
    canal = tmp_path / nombre
    capa = config.escena_del_canal(canal)
    capa.mkdir(parents=True)
    (capa / "__init__.py").write_text("from . import estilo\n", encoding="utf-8")
    (capa / "estilo.py").write_text(f"VALOR = {valor!r}\n", encoding="utf-8")
    return canal


def test_la_capa_del_canal_se_carga_como_escena_del_canal_y_cambia_con_el_canal(tmp_path):
    a = carga_canal(_canal_con_capa(tmp_path, "uno", "del canal uno"))
    assert sys.modules[config.ESCENA_PAQUETE_DEL_CANAL] is a and a.estilo.VALOR == "del canal uno"
    from escena_del_canal import estilo  # el nombre fijo con que la importa el guion de un episodio

    assert estilo.VALOR == "del canal uno"
    # Control: otro canal en el mismo proceso no se queda con los módulos del primero.
    b = carga_canal(_canal_con_capa(tmp_path, "dos", "del canal dos"))
    from escena_del_canal import estilo as otro

    assert b.estilo.VALOR == otro.VALOR == "del canal dos"


def test_un_canal_sin_capa_de_escena_para(tmp_path):
    with pytest.raises(ErrorDeEpisodio, match="no tiene capa de escena"):
        carga_canal(tmp_path / "sin-capa")


def test_el_guion_es_un_paquete_y_su_huella_cubre_toda_su_carpeta(tmp_path):
    perfil = perfil_de_prueba()
    canal = _canal_con_capa(tmp_path, "canal", "azul")
    run = prepara_run(tmp_path / "videos" / RUN_ID, LAMINAS_PRUEBA)
    carpeta = config.guion_de_escena(canal, RUN_ID)
    carpeta.mkdir(parents=True)
    (carpeta / "tramos.py").write_text("from escena_del_canal import estilo\nCOLOR = estilo.VALOR\n", encoding="utf-8")
    (carpeta / config.ESCENA_GUION).write_text(
        "from . import tramos\n\ndef puesta(ep):\n    return tramos.COLOR\n", encoding="utf-8"
    )
    ep = Episodio(run_dir=run, run_id=RUN_ID, canal_dir=canal, perfil=perfil, idioma="en")
    assert carga_guion(ep).puesta(ep) == "azul"
    huella = ep.huella_del_guion()
    # Una caché de Python no es el guion.
    (carpeta / "__pycache__").mkdir(exist_ok=True)
    (carpeta / "__pycache__" / "x.pyc").write_bytes(b"cache")
    assert ep.huella_del_guion() == huella
    # Control: cambiar un TRAMO (no escena.py) cambia la huella, y el guion recargado ve el cambio.
    (carpeta / "tramos.py").write_text("COLOR = 'rojo'\n", encoding="utf-8")
    assert ep.huella_del_guion() != huella
    assert carga_guion(ep).puesta(ep) == "rojo"
