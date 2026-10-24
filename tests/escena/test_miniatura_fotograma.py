"""La miniatura de un rehecho sale de un fotograma de su escena, sin el karaoke (02-10, fila 246).

Correr: .venv\\Scripts\\python -m pytest -q tests/escena/test_miniatura_fotograma.py

**Por qué.** Un rehecho reutiliza las láminas del vídeo viejo, así que una miniatura sacada de su lámina sería la que
ya se vio. Sale de la escena, que es lo nuevo, y sigue saliendo del run: nunca se genera aparte (fila 156).

**Por qué no del vídeo.** `final.mp4` lleva el karaoke quemado abajo, justo donde va el texto de la miniatura, y en los
silencios solo salen las tarjetas de capítulo. Así que el fotograma sale de la misma composición que se renderizó,
fotografiada con una regla más que esconde la capa del karaoke.

Lo que fijan estas pruebas, cada cosa con su control negativo:

1. La copia que se fotografía es la página renderizada con una sola regla más, y la composición del run no se toca.
2. Un instante fuera del vídeo, una composición que ya no es la renderizada o una página sin la capa del karaoke paran
   **antes** de tocar la GPU.
3. La procedencia dice que es un fotograma del run, no una generación, y sustituye a la entrada anterior.
4. La etapa elige por el ESTADO del run: un rehecho exige `thumbnail_segundo` y el render; un run que no lo es sigue con
   la lámina, y se le niega el fotograma.

El `snapshot` es falso aquí: la prueba con Chrome de verdad es la de la bici (`progress/impl_F7.0b.md`).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from lib import config, lineas_rojas, marca_ia, miniatura, provenance
from lib import state as run_state
from lib.escena import etapas
from lib.escena import render as escena_render

# El GUION mínimo dura 1,5 s a 24 fps: su último fotograma está en el 1,5 − 1/24.
ULTIMO = 1.5 - 1 / 24


def _snapshot_falso(llamadas: list, tamano=(1920, 1080)):
    """Un `render.snapshot` sin Chrome: apunta qué página le llegó y deja un PNG por instante, como HyperFrames."""

    def snapshot(carpeta, dir_log, tiempos, salida):
        carpeta = Path(carpeta)
        llamadas.append({"carpeta": carpeta, "tiempos": list(tiempos), "index": (carpeta / "index.html").read_bytes()})
        salida = Path(salida)
        salida.mkdir(parents=True, exist_ok=True)
        for i, _ in enumerate(tiempos):
            Image.new("RGB", tamano, (90, 120, 150)).save(salida / f"frame-{i:02d}-at-{i}s.png")
        return sorted(salida.glob("frame-*.png"))

    return snapshot


@pytest.fixture
def run(tmp_path, composicion, monkeypatch):
    """Un run con la composición del GUION mínimo en su sitio y su huella. El trabajo temporal, dentro de tmp_path."""
    carpeta = tmp_path / "run"
    shutil.copytree(composicion, config.composicion_del_run(carpeta))
    monkeypatch.setattr(config, "ESCENA_RENDER_TMP", tmp_path / "tmp")
    llamadas: list = []
    monkeypatch.setattr(escena_render, "snapshot", _snapshot_falso(llamadas))
    return {
        "dir": carpeta,
        "huella": etapas.huella_de_composicion(config.composicion_del_run(carpeta)),
        "snapshot": llamadas,
    }


# --- 1. la copia que se fotografía ------------------------------------------------------------------------------


def test_la_copia_esconde_el_karaoke_y_la_composicion_del_run_no_se_toca(run):
    index = config.composicion_del_run(run["dir"]) / "index.html"
    antes = index.read_bytes()
    assert antes.count(b'<div id="karaoke">') == 1, "la composición de prueba tiene que llevar su karaoke"

    hecho = etapas.fotogramas_sin_karaoke(run["dir"], [0.5], huella_composicion=run["huella"])

    [llamada] = run["snapshot"]
    assert llamada["tiempos"] == [0.5]
    assert llamada["carpeta"].resolve() != config.composicion_del_run(run["dir"]).resolve(), "se fotografía una copia"
    assert b"#karaoke { display: none !important; }" in llamada["index"]
    # La copia es la página renderizada con UNA regla más y nada más, ni un final de línea.
    assert llamada["index"].replace(b"<style>#karaoke { display: none !important; }</style>\n", b"") == antes
    assert index.read_bytes() == antes
    assert etapas.huella_de_composicion(config.composicion_del_run(run["dir"])) == run["huella"]
    [foto] = hecho["fotogramas"]
    assert foto == config.revision_del_run(run["dir"]) / "miniatura" / "fotograma-0.5s.png" and foto.is_file()
    assert not llamada["carpeta"].exists(), "la copia de trabajo se borra"


@pytest.mark.parametrize("segundos", [[-1.0], [1.5], [ULTIMO + 0.01], [0.5, 9.0], []])
def test_un_instante_fuera_del_video_para_antes_de_la_gpu(run, segundos):
    with pytest.raises(etapas.ErrorDeEtapa, match="dura 1.5 s"):
        etapas.fotogramas_sin_karaoke(run["dir"], segundos, huella_composicion=run["huella"])
    assert run["snapshot"] == []


def test_CONTROL_NEGATIVO_el_ultimo_fotograma_y_el_primero_si_valen(run):
    """Sin esto, la de arriba no distingue «el límite está bien puesto» de «todo instante se rechaza»."""
    etapas.fotogramas_sin_karaoke(run["dir"], [0.0, ULTIMO], huella_composicion=run["huella"])
    assert run["snapshot"][0]["tiempos"] == [0.0, ULTIMO]


def test_una_composicion_que_cambio_desde_el_render_para(run):
    """Su fotograma no sería del vídeo: lo que se renderizó es lo de la huella apuntada en la parada 2."""
    with pytest.raises(etapas.ErrorDeEtapa, match="ha cambiado"):
        etapas.fotogramas_sin_karaoke(run["dir"], [0.5], huella_composicion="0" * 64)
    assert run["snapshot"] == []


def test_un_run_sin_composicion_para(tmp_path, monkeypatch):
    monkeypatch.setattr(escena_render, "snapshot", _snapshot_falso([]))
    with pytest.raises(etapas.ErrorDeEtapa, match="no está la composición"):
        etapas.fotogramas_sin_karaoke(tmp_path / "vacio", [0.5], huella_composicion="")


def test_una_pagina_sin_la_capa_del_karaoke_para_en_vez_de_dejarla_en_la_miniatura(run):
    """Si `compone` cambiara cómo escribe la capa, la regla no escondería nada y el karaoke saldría sin avisar."""
    index = config.composicion_del_run(run["dir"]) / "index.html"
    index.write_bytes(index.read_bytes().replace(b'<div id="karaoke">', b'<div id="subtitulos">'))
    huella = etapas.huella_de_composicion(config.composicion_del_run(run["dir"]))
    with pytest.raises(etapas.ErrorDeEtapa, match="capa del karaoke"):
        etapas.fotogramas_sin_karaoke(run["dir"], [0.5], huella_composicion=huella)
    assert run["snapshot"] == []


def test_si_snapshot_no_da_un_png_por_instante_para(run, monkeypatch):
    monkeypatch.setattr(escena_render, "snapshot", lambda carpeta, dir_log, tiempos, salida: [])
    with pytest.raises(etapas.ErrorDeEtapa, match="snapshot dio 0"):
        etapas.fotogramas_sin_karaoke(run["dir"], [0.5], huella_composicion=run["huella"])


# --- 2. el instante declarado ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valor", "segundos"),
    [(420, 420.0), (421.5, 421.5), ("420", 420.0), ("7:00", 420.0), ("07:01.5", 421.5), ("1:02:03", 3723.0), (0, 0.0)],
)
def test_el_instante_vale_en_segundos_o_en_reloj(valor, segundos):
    assert miniatura.segundo_declarado({"thumbnail_segundo": valor}) == segundos


def test_sin_declaracion_el_lector_devuelve_None():
    assert miniatura.segundo_declarado({}) is None
    assert miniatura.segundo_declarado({"thumbnail_segundo": None}) is None
    assert miniatura.segundo_declarado({"thumbnail_segundo": "  "}) is None


@pytest.mark.parametrize("valor", [True, -3, "-1", "7:60", "1:2:3:4", "siete", "7:xx", "nan", "inf", [420], {}])
def test_un_instante_que_no_es_un_instante_se_rechaza(valor):
    with pytest.raises(ValueError, match="thumbnail_segundo"):
        miniatura.segundo_declarado({"thumbnail_segundo": valor})


# --- 3. la copia y su procedencia --------------------------------------------------------------------------------

QWEN_EDIT = "Qwen-Image-Edit-2511 GGUF Q6_K + LoRA Lightning 8 pasos → Real-ESRGAN x4plus anime 6B"
QWEN = "Qwen-Image GGUF Q6_K + LoRA Lightning 8 pasos → Real-ESRGAN x4plus anime 6B + SAM 2.1 hiera-large"
LICENCIA = "Apache-2.0 (Qwen-Image-Edit y Qwen-Image-Lightning) - uso comercial permitido"


def _registro_de_la_escena(run: Path, *, con_modelos: bool = True) -> None:
    """El `assets.json` de un run de escena: imágenes de `activos/` con su modelo, una de geometría y las láminas."""
    activos = [
        {"id": "activos/nora.png", "tipo": "imagen", "modelo": QWEN_EDIT, "licencia": LICENCIA},
        {"id": "activos/papa.png", "tipo": "imagen", "modelo": QWEN_EDIT, "licencia": LICENCIA},
        {"id": "activos/acera.png", "tipo": "imagen", "modelo": QWEN, "licencia": LICENCIA},
    ]
    otros = [
        {"id": "activos/rueda.png", "tipo": "imagen", "modelo": "ninguno: geometría (Pillow y NumPy), sin modelo"},
        # Las láminas son el guion gráfico: no salen en el vídeo, así que su modelo no es el de la escena.
        {"id": "slides/slide-01.png", "tipo": "imagen", "modelo": "Qwen-Image 2512 de la lámina", "licencia": "otra"},
    ]
    (run / "assets.json").write_text(
        json.dumps({"assets": (activos if con_modelos else []) + otros}, ensure_ascii=False), encoding="utf-8"
    )


def _fotograma(run: Path, tamano=(1920, 1080)) -> Path:
    foto = run / "revision" / "miniatura" / "fotograma-420s.png"
    foto.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", tamano, (200, 80, 40)).save(foto)
    return foto


def test_el_fotograma_se_reduce_a_1280x720_y_hereda_los_modelos_de_la_escena(tmp_path):
    _registro_de_la_escena(tmp_path)
    foto = _fotograma(tmp_path)
    (tmp_path / miniatura.REGISTRO_DE_IMAGENES).write_text(
        json.dumps(
            [
                {"file": str(tmp_path / "subir-al-canal" / "thumbnail.png"), "origen": "copia de slides/slide-05.png"},
                {"file": str(tmp_path / "otra-cosa.png"), "origen": "generado en local con ComfyUI (127.0.0.1)"},
            ]
        ),
        encoding="utf-8",
    )
    destino = config.dir_subir_al_canal(tmp_path, crear=True) / "thumbnail.png"

    hecho = miniatura.desde_fotograma(tmp_path, foto, 420.0, destino, huella_composicion="abc", herramientas={"x": 1})

    assert Image.open(destino).size == miniatura.TAMANO_DE_FOTOGRAMA
    entradas = json.loads((tmp_path / miniatura.REGISTRO_DE_IMAGENES).read_text(encoding="utf-8"))
    [entrada] = [e for e in entradas if Path(e["file"]).name == "thumbnail.png"]
    assert "fotograma" in entrada["origen"] and "sin generación" in entrada["origen"] and "karaoke" in entrada["origen"]
    assert entrada["fuente"].endswith("no una generación nueva")
    # Los dos modelos de `activos/`, una vez cada uno; ni la geometría ni el de las láminas.
    assert entrada["modelo"] == f"los de las imágenes de la escena: {QWEN_EDIT}; {QWEN}"
    assert entrada["licencia"] == f"derivada de las imágenes de la escena: {LICENCIA}"
    assert entrada["segundo"] == 420.0 and entrada["huella_composicion"] == "abc"
    assert any(Path(e["file"]).name == "otra-cosa.png" for e in entradas), "no se toca lo ajeno"
    assert hecho["procedencia"] == entrada


def test_la_declaracion_de_ia_de_un_rehecho_dice_que_la_miniatura_es_IA(tmp_path):
    """Decisión 7. Lo cazó la revisión de F7.0b: con el modelo «ninguno», la línea de la miniatura desaparecía."""
    from lib import provenance, publicacion

    _registro_de_la_escena(tmp_path)
    destino = config.dir_subir_al_canal(tmp_path, crear=True) / "thumbnail.png"
    hecho = miniatura.desde_fotograma(tmp_path, _fotograma(tmp_path), 420.0, destino, huella_composicion="abc")
    escena = json.loads((tmp_path / "assets.json").read_text(encoding="utf-8"))["assets"]
    video = {
        "id": "subir-al-canal/final.mp4",
        "tipo": "video",
        "modelo": "ninguno: render",
        "detalle": {"motor": "escena"},
    }
    linea = f"• {publicacion.PIEZAS['en']['miniatura']}."

    def declara(entrada: dict) -> str:
        (tmp_path / "assets.json").write_text(json.dumps({"assets": [*escena, video, entrada]}), encoding="utf-8")
        return publicacion.declaracion_de_ia(tmp_path, "en")[0]

    assert linea in declara(provenance._image_entry(tmp_path, hecho["procedencia"]))
    # Control negativo: la entrada que escribía la primera versión, con el modelo «ninguno», la pierde.
    vieja = {**hecho["procedencia"], "modelo": "ninguno: es un fotograma de la composición del run"}
    assert linea not in declara(provenance._image_entry(tmp_path, vieja))


def test_sin_modelos_registrados_para_la_escena_no_hay_miniatura(tmp_path):
    """Escribir «ninguno» o callarlo dejaría corta la declaración de IA: mejor parar y decir qué falta."""
    _registro_de_la_escena(tmp_path, con_modelos=False)
    destino = config.dir_subir_al_canal(tmp_path, crear=True) / "thumbnail.png"
    with pytest.raises(ValueError, match="declaración de IA"):
        miniatura.desde_fotograma(tmp_path, _fotograma(tmp_path), 420.0, destino, huella_composicion="")
    assert not destino.exists()


def test_un_fotograma_que_no_es_16_9_no_se_deforma(tmp_path):
    _registro_de_la_escena(tmp_path)
    destino = config.dir_subir_al_canal(tmp_path, crear=True) / "thumbnail.png"
    with pytest.raises(ValueError, match="16:9"):
        miniatura.desde_fotograma(tmp_path, _fotograma(tmp_path, (1080, 1080)), 1.0, destino, huella_composicion="")
    assert not destino.exists()


def test_sin_el_fotograma_no_hay_miniatura(tmp_path):
    with pytest.raises(FileNotFoundError, match="fotograma"):
        miniatura.desde_fotograma(tmp_path, tmp_path / "no-esta.png", 1.0, tmp_path / "t.png", huella_composicion="")


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


# --- 4. la etapa elige por el estado del run ---------------------------------------------------------------------


@pytest.fixture
def etapa(run, monkeypatch, marca_falsa):
    """`stage_thumbnail` sobre el run de prueba, con el estado en memoria y sin perfil ni guardianes de verdad."""
    import pipeline

    estado = {
        "run_id": "run-x",
        "output_dir": str(run["dir"]),
        "motor": run_state.MOTOR,
        "stages": {"render": {"status": "complete"}},
        "escena": {"huella_composicion": run["huella"]},
        "rehace": {"run_id": "viejo", "video_id": "vid3Ejemplo"},
    }
    escritos: list = []
    monkeypatch.setattr(run_state, "load_run", lambda _rid: estado)
    monkeypatch.setattr(run_state, "update_stage", lambda *a, **k: escritos.append(a))
    monkeypatch.setattr(pipeline, "_sync_assets", lambda *a, **k: None)
    monkeypatch.setattr(lineas_rojas, "exige", lambda rutas, etapa: escritos.append(("lineas_rojas", etapa)))
    # La fuente del texto la declara el perfil, de la biblioteca del estudio (OC1.4): la del canal de ejemplo.
    perfil = {"imagen": {"acento_de_color": False, "fuente_de_la_miniatura": "Anton-Regular.ttf"}}
    monkeypatch.setattr(config, "CANAL_PERFIL", perfil)
    _registro_de_la_escena(run["dir"])
    # Dos láminas de verdad en el run: son la referencia de lo medido, y la que se usaría si no fuera un rehecho.
    (run["dir"] / "slides").mkdir()
    for n in (1, 2):
        Image.new("RGB", (1344, 768), (40 * n, 60, 90)).save(run["dir"] / "slides" / f"slide-{n:02d}.png")

    def corre(slides: dict):
        (run["dir"] / "slides.json").write_text(json.dumps(slides), encoding="utf-8")
        return pipeline.stage_thumbnail("run-x")

    corre.estado, corre.escritos, corre.snapshot, corre.dir = estado, escritos, run["snapshot"], run["dir"]
    corre.perfil = perfil
    return corre


def test_un_rehecho_sin_instante_PARA_y_dice_que_escribir(etapa):
    with pytest.raises(ValueError, match="thumbnail_segundo") as error:
        etapa({"thumbnail_lamina": 5, "thumbnail_text": "A2 OIL EVERYWHERE"})
    assert "vid3Ejemplo" in str(error.value)
    assert etapa.escritos[-1][1:3] == ("thumbnail", "blocked")
    assert etapa.snapshot == [], "la lámina del vídeo viejo NO es la alternativa"


def test_un_rehecho_sin_render_PARA(etapa):
    etapa.estado["stages"]["render"]["status"] = "pending"
    with pytest.raises(ValueError, match="render"):
        etapa({"thumbnail_segundo": 0.5, "thumbnail_text": "A2 OIL EVERYWHERE"})
    assert etapa.escritos[-1][1:3] == ("thumbnail", "blocked") and etapa.snapshot == []


def test_un_instante_fuera_del_video_PARA_la_etapa_con_su_motivo(etapa):
    with pytest.raises(etapas.ErrorDeEtapa, match="fuera"):
        etapa({"thumbnail_segundo": 99, "thumbnail_text": "A2 OIL EVERYWHERE"})
    assert etapa.escritos[-1][1:3] == ("thumbnail", "blocked") and etapa.snapshot == []


def test_un_run_que_no_es_un_rehecho_no_puede_sacarla_de_un_fotograma(etapa):
    del etapa.estado["rehace"]
    with pytest.raises(ValueError, match="solo sale de un fotograma en los rehechos"):
        etapa({"thumbnail_lamina": 1, "thumbnail_segundo": 0.5, "thumbnail_text": "A2 OIL EVERYWHERE"})
    assert etapa.snapshot == []


def test_CONTROL_NEGATIVO_un_rehecho_con_instante_y_render_pasa_las_guardas(etapa):
    """Pasa las tres de arriba y se para en la SIGUIENTE, la del texto: es la prueba de que dejan pasar."""
    with pytest.raises(ValueError, match="thumbnail_text"):
        etapa({"thumbnail_segundo": "0:00.5"})
    assert etapa.snapshot == []


def test_el_rehecho_saca_la_miniatura_del_fotograma_de_principio_a_fin(etapa):
    salida = etapa({"thumbnail_lamina": 5, "thumbnail_segundo": "0:00.5", "thumbnail_text": "A2 OIL EVERYWHERE"})

    assert [c["tiempos"] for c in etapa.snapshot] == [[0.5]]
    assert Image.open(salida).size == miniatura.TAMANO_DE_FOTOGRAMA
    medido = json.loads((etapa.dir / "miniatura.json").read_text(encoding="utf-8"))
    assert medido["cumple"], medido["fallos"]
    assert medido["de_donde_sale"]["fotograma_del_run_s"] == 0.5 and medido["de_donde_sale"]["sin_karaoke"] is True
    assert medido["de_donde_sale"]["rehace"] == "vid3Ejemplo"
    assert medido["de_donde_sale"]["origen"] == "revision/miniatura/fotograma-0.5s.png"
    assert "lamina_del_run" not in medido["de_donde_sale"]
    assert ("lineas_rojas", "thumbnail") in etapa.escritos, "la guarda de las líneas rojas sigue pasando"
    assert etapa.escritos[-1][1:3] == ("thumbnail", "complete")
    # La letra es la que declara el perfil, y su copia queda en el run con su registro de procedencia (OC1.4).
    assert medido["medido"]["texto"]["fuente"] == "Anton-Regular.ttf"
    carpeta = etapa.dir / miniatura.CARPETA_DE_LA_FUENTE
    assert (carpeta / "Anton-Regular.ttf").is_file()
    (registro,) = json.loads((carpeta / "biblioteca-escena.json").read_text(encoding="utf-8"))
    assert registro["etapa"] == "thumbnail" and registro["licencia"].startswith("SIL Open Font License")


def test_sin_la_fuente_de_la_miniatura_en_el_perfil_la_etapa_PARA_y_dice_que_escribir(etapa):
    """Control negativo (OC1.4): sin `imagen.fuente_de_la_miniatura` no hay letra por defecto, ni de Windows."""
    del etapa.perfil["imagen"]["fuente_de_la_miniatura"]
    with pytest.raises(ValueError, match="imagen.fuente_de_la_miniatura") as error:
        etapa({"thumbnail_lamina": 5, "thumbnail_segundo": "0:00.5", "thumbnail_text": "A2 OIL EVERYWHERE"})
    assert "Anton-Regular.ttf" in str(error.value), "el mensaje dice qué fuentes hay para escribir"
    assert etapa.escritos[-1][1:3] == ("thumbnail", "blocked") and etapa.snapshot == []
    assert not (etapa.dir / miniatura.CARPETA_DE_LA_FUENTE).exists()


def test_un_run_que_no_es_un_rehecho_sigue_sacandola_de_la_lamina(etapa):
    """Los runs que no son rehechos no cambian: la lámina, sin GPU y sin fotograma (fila 246)."""
    del etapa.estado["rehace"]
    etapa({"thumbnail_lamina": 2, "thumbnail_text": "A2 OIL EVERYWHERE"})

    assert etapa.snapshot == []
    medido = json.loads((etapa.dir / "miniatura.json").read_text(encoding="utf-8"))
    assert medido["de_donde_sale"] == {"lamina_del_run": 2, "origen": "slides/slide-02.png"}
    assert medido["medido"]["tamano"] == [1344, 768]
    assert etapa.escritos[-1][1:3] == ("thumbnail", "complete")


def test_la_miniatura_sale_con_su_marca_de_ia_y_la_apunta(etapa, marca_falsa):
    """OC1.5: cuando la miniatura ha pasado el contrato y las líneas rojas, se marca en su sitio. Su registro va a
    `miniatura.json` y a su entrada del registro de imágenes, de donde `provenance` lo lleva a `assets.json`."""
    del etapa.estado["rehace"]
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
    del etapa.estado["rehace"]

    def falla(origen, destino, **_):
        raise marca_ia.ErrorDeMarca("no está .venv-escena")

    monkeypatch.setattr(marca_ia, "marca_imagen", falla)
    with pytest.raises(marca_ia.ErrorDeMarca, match="venv-escena"):
        etapa({"thumbnail_lamina": 2, "thumbnail_text": "A2 OIL EVERYWHERE"})
    assert etapa.escritos[-1][1:3] == ("thumbnail", "blocked")
    assert "marca_ia" not in json.loads((etapa.dir / "miniatura.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("rehecho", [True, False], ids=["rehecho", "run-normal"])
def test_rehacer_la_escena_de_un_rehecho_invalida_su_miniatura(tmp_path, monkeypatch, rehecho):
    """Su miniatura es un fotograma de la composición: si la escena se rehace, la de antes ya no es del vídeo.

    En un run normal la miniatura sale de una lámina, que no depende de la escena, así que se queda como estaba.
    """
    import pipeline

    estado = {
        "run_id": "run-x",
        "output_dir": str(tmp_path),
        "motor": run_state.MOTOR,
        "stages": {e: {"status": "complete"} for e in ("activos", "escena", "render", "assembly", "thumbnail")},
    }
    if rehecho:
        estado["rehace"] = {"video_id": "vid3Ejemplo"}
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
    assert ("thumbnail" in pendientes) is rehecho
