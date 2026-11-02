"""La etapa `thumbnail` de un run del motor de escena: la miniatura sale de la lámina que declara el guion.

Correr: .venv\\Scripts\\python -m pytest -q tests/escena/test_etapa_miniatura.py

Hasta OC2.2 la etapa tenía otra rama: en un rehecho, la miniatura salía de un fotograma de la escena (fila 246). Solo
la usaba el script de rehechos del estudio, que se borró en OC1.1, así que nadie podía llegar a ella y se retiró con sus
pruebas (fila 336).

Lo que fijan estas pruebas, cada cosa con su control negativo:

1. La miniatura es la lámina declarada, con la fuente del perfil copiada al run con su procedencia.
2. Sin la fuente en el perfil, la etapa para y dice qué escribir.
3. La miniatura sale con su marca de IA y la apunta; si la marca falla, la etapa para.
4. Una miniatura de más de 2 MB suspende aunque su texto cumpla.
5. Rehacer la escena no invalida la miniatura: sale de una lámina, que no depende de la escena.
"""

from __future__ import annotations

import json

import pytest
from PIL import Image

from lib import config, lineas_rojas, marca_ia, miniatura, provenance
from lib import state as run_state
from lib.escena import etapas


@pytest.fixture
def etapa(tmp_path, monkeypatch, marca_falsa):
    """`stage_thumbnail` sobre un run de prueba, con el estado en memoria y sin perfil ni guardianes de verdad."""
    import pipeline

    carpeta = tmp_path / "run"
    estado = {
        "run_id": "run-x",
        "output_dir": str(carpeta),
        "motor": run_state.MOTOR,
        "stages": {"render": {"status": "complete"}},
    }
    escritos: list = []
    monkeypatch.setattr(run_state, "load_run", lambda _rid: estado)
    monkeypatch.setattr(run_state, "update_stage", lambda *a, **k: escritos.append(a))
    monkeypatch.setattr(pipeline, "_sync_assets", lambda *a, **k: None)
    monkeypatch.setattr(lineas_rojas, "exige", lambda rutas, etapa: escritos.append(("lineas_rojas", etapa)))
    # La fuente del texto la declara el perfil, de la biblioteca del estudio (OC1.4): la del canal de ejemplo.
    perfil = {"imagen": {"acento_de_color": False, "fuente_de_la_miniatura": "Anton-Regular.ttf"}}
    monkeypatch.setattr(config, "CANAL_PERFIL", perfil)
    # Dos láminas de verdad en el run: la declarada y la referencia de lo medido.
    (carpeta / "slides").mkdir(parents=True)
    for n in (1, 2):
        Image.new("RGB", (1344, 768), (40 * n, 60, 90)).save(carpeta / "slides" / f"slide-{n:02d}.png")

    def corre(slides: dict):
        (carpeta / "slides.json").write_text(json.dumps(slides), encoding="utf-8")
        return pipeline.stage_thumbnail("run-x")

    corre.estado, corre.escritos, corre.dir, corre.perfil = estado, escritos, carpeta, perfil
    return corre


def test_la_miniatura_es_la_lamina_declarada_con_la_fuente_del_perfil(etapa):
    etapa({"thumbnail_lamina": 2, "thumbnail_text": "A2 OIL EVERYWHERE"})

    medido = json.loads((etapa.dir / "miniatura.json").read_text(encoding="utf-8"))
    assert medido["cumple"], medido["fallos"]
    assert medido["de_donde_sale"] == {"lamina_del_run": 2, "origen": "slides/slide-02.png"}
    assert medido["medido"]["tamano"] == [1344, 768]
    assert ("lineas_rojas", "thumbnail") in etapa.escritos, "la guarda de las líneas rojas sigue pasando"
    assert etapa.escritos[-1][1:3] == ("thumbnail", "complete")
    # La letra es la que declara el perfil, y su copia queda en el run con su registro de procedencia (OC1.4).
    assert medido["medido"]["texto"]["fuente"] == "Anton-Regular.ttf"
    carpeta = etapa.dir / miniatura.CARPETA_DE_LA_FUENTE
    assert (carpeta / "Anton-Regular.ttf").is_file()
    (registro,) = json.loads((carpeta / "biblioteca-escena.json").read_text(encoding="utf-8"))
    assert registro["etapa"] == "thumbnail" and registro["licencia"].startswith("SIL Open Font License")


def test_control_sin_lamina_declarada_la_etapa_para_y_dice_cuales_hay(etapa):
    with pytest.raises(ValueError, match="thumbnail_lamina") as error:
        etapa({"thumbnail_text": "A2 OIL EVERYWHERE"})
    assert "slide-01.png, slide-02.png" in str(error.value)
    assert etapa.escritos[-1][1:3] == ("thumbnail", "blocked")


def test_sin_la_fuente_de_la_miniatura_en_el_perfil_la_etapa_PARA_y_dice_que_escribir(etapa):
    """Control negativo (OC1.4): sin `imagen.fuente_de_la_miniatura` no hay letra por defecto, ni de Windows."""
    del etapa.perfil["imagen"]["fuente_de_la_miniatura"]
    with pytest.raises(ValueError, match="imagen.fuente_de_la_miniatura") as error:
        etapa({"thumbnail_lamina": 2, "thumbnail_text": "A2 OIL EVERYWHERE"})
    assert "Anton-Regular.ttf" in str(error.value), "el mensaje dice qué fuentes hay para escribir"
    assert etapa.escritos[-1][1:3] == ("thumbnail", "blocked")
    assert not (etapa.dir / miniatura.CARPETA_DE_LA_FUENTE).exists()


def test_la_miniatura_sale_con_su_marca_de_ia_y_la_apunta(etapa, marca_falsa):
    """OC1.5: cuando la miniatura ha pasado el contrato y las líneas rojas, se marca en su sitio. Su registro va a
    `miniatura.json` y a su entrada del registro de imágenes, de donde `provenance` lo lleva a `assets.json`."""
    salida = etapa({"thumbnail_lamina": 2, "thumbnail_text": "A2 OIL EVERYWHERE"})
    assert marca_falsa.hechas == ["thumbnail.png"]
    assert etapa.escritos.index(("lineas_rojas", "thumbnail")) < len(etapa.escritos) - 1, "la marca va tras la guarda"
    medido = json.loads((etapa.dir / "miniatura.json").read_text(encoding="utf-8"))
    assert medido["marca_ia"]["detectada"] is True and medido["marca_ia"]["sha256"] == marca_ia.sha256_de(salida)
    (entrada,) = [e for e in provenance.entries_from_adapters(etapa.dir) if e["tipo"] == "miniatura"]
    assert entrada["detalle"]["marca_ia"] == medido["marca_ia"]
    # Video Seal toca sus píxeles: su licencia y su url van con las de la lámina; el modelo es el que la dibujó.
    assert "marca de agua: Video Seal 1.0" in entrada["licencia"] and "facebookresearch/videoseal" in entrada["url"]
    assert etapa.escritos[-1][1:3] == ("thumbnail", "complete")


def test_control_si_la_marca_de_la_miniatura_falla_la_etapa_para(etapa, monkeypatch):
    def falla(origen, destino, **_):
        raise marca_ia.ErrorDeMarca("no está .venv-escena")

    monkeypatch.setattr(marca_ia, "marca_imagen", falla)
    with pytest.raises(marca_ia.ErrorDeMarca, match="venv-escena"):
        etapa({"thumbnail_lamina": 2, "thumbnail_text": "A2 OIL EVERYWHERE"})
    assert etapa.escritos[-1][1:3] == ("thumbnail", "blocked")
    assert "marca_ia" not in json.loads((etapa.dir / "miniatura.json").read_text(encoding="utf-8"))


def test_una_miniatura_de_mas_de_2_MB_suspende_aunque_su_texto_cumpla(tmp_path):
    """YouTube no la pondría (thumbnails.set), y la subida va justo después de esta etapa."""
    import numpy as np

    ruido = tmp_path / "ruido.png"
    Image.fromarray(np.random.default_rng(0).integers(0, 256, (1080, 1920, 3), dtype=np.uint8)).save(ruido)
    assert ruido.stat().st_size > miniatura.PESO_MAXIMO_BYTES
    veredicto = miniatura.comprueba(
        str(ruido), texto="A2 OIL", medido_texto={"cumple_altura": True, "cumple_contraste": True}
    )
    assert not veredicto["cumple"] and any("2 MB" in f for f in veredicto["fallos"])

    # Control negativo: la misma comprobación con una imagen ligera no suspende por el peso.
    liso = tmp_path / "liso.png"
    Image.new("RGB", (1280, 720), (90, 120, 150)).save(liso)
    veredicto = miniatura.comprueba(
        str(liso), texto="A2 OIL", medido_texto={"cumple_altura": True, "cumple_contraste": True}
    )
    assert veredicto["cumple"], veredicto["fallos"]


def test_rehacer_la_escena_invalida_el_render_y_no_la_miniatura(tmp_path, monkeypatch):
    """La miniatura sale de una lámina, que no depende de la escena, así que se queda como estaba."""
    import pipeline

    estado = {
        "run_id": "run-x",
        "output_dir": str(tmp_path),
        "motor": run_state.MOTOR,
        "stages": {e: {"status": "complete"} for e in ("activos", "escena", "render", "assembly", "thumbnail")},
    }
    escritos: list = []
    monkeypatch.setattr(run_state, "load_run", lambda _rid: estado)
    monkeypatch.setattr(run_state, "update_stage", lambda *a, **k: escritos.append(a))
    monkeypatch.setattr(run_state, "update_run", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_episodio", lambda state: None)
    monkeypatch.setattr(pipeline, "_sync_assets", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_para_en", lambda *a, **k: None)
    biblioteca = {"entran": [], "actualizadas": [], "no_entran": {}, "carpeta": ""}
    info = {
        "pagina": tmp_path / "revision" / "fotogramas.html",
        "huella_composicion": "h",
        "huella_guion": "g",
        "defectos": {},
        "planos": 1,
        "audios": 1,
        "fotogramas": 1,
        "biblioteca": biblioteca,
    }
    monkeypatch.setattr(etapas, "escena", lambda ep: info)

    pipeline.stage_escena("run-x")

    pendientes = {a[1] for a in escritos if a[2] == "pending"}
    assert {"render", "assembly"} <= pendientes
    assert "thumbnail" not in pendientes
