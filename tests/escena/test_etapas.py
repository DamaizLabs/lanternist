"""Las etapas del motor de escena en el pipeline, sin GPU, con un canal ficticio (F6.2d).

Lo que se prueba, cada cosa con su control negativo:

- `alinea`: el `.srt` son los cues de la línea de tiempo (una sola fuente), y no gasta GPU si falta algo.
- De extremo a extremo hasta la composición: alinea → activos → escena (con un `snapshot` sin Chrome) → compone →
  las seis comprobaciones, con la procedencia de todo lo que entra en el vídeo.
- `render` escribe `montaje.json` con su contrato y se niega si lo que se revisó ha cambiado.
- Las DOS PARADAS: el pipeline se detiene, abre su página y no avanza sin `--stage`.
- El motor viejo no cambia: se elige el motor por un parámetro del run.

El whisper, el `snapshot` y el render son falsos aquí (sus pruebas de verdad: `test_render_escena_real.py`, y las de
F6.2a); el canal y el run viven en carpetas temporales y ningún perfil de verdad se toca.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from utiles_escena import LAMINAS_PRUEBA
from utiles_pipeline import (
    FUENTE_PRUEBA,
    canal_de_prueba,
    guion_en_el_canal,
    perfil_de_prueba,
    prepara_run,
    render_falso,
    snapshot_falso,
)

from lib import alineador, config, integridad_narracion, marca_ia, pagina_local, provenance, publicacion
from lib import state as run_state
from lib.escena import compone, etapas
from lib.escena import render as escena_render
from lib.escena.episodio import Episodio, ErrorDeEpisodio
from scripts import compone_descripcion

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="el sonido del motor de escena usa ffmpeg")

RUN_ID = "2026-09-29_000000_episodio-de-prueba"


@pytest.fixture
def gpu(monkeypatch, marca_falsa):
    """Lo que tocaría la GPU, sustituido: whisper devuelve la alineación que dejó el run, la tarjeta está libre y la
    marca de IA es la falsa de `tests/conftest.py`."""
    llamadas = {"gpu": 0, "whisper": 0, "snapshot": [], "render": [], "marca": marca_falsa.hechas}

    def libre(*a, **k):
        llamadas["gpu"] += 1
        return 6973

    def alinea(items, trabajo, cfg):
        llamadas["whisper"] += 1
        return json.loads((Path(trabajo) / "alineacion-resultado.json").read_text(encoding="utf-8"))

    monkeypatch.setattr(escena_render, "exige_gpu_libre", libre)
    monkeypatch.setattr(alineador, "alinea", alinea)
    monkeypatch.setattr(escena_render, "snapshot", snapshot_falso(llamadas["snapshot"]))
    monkeypatch.setattr(escena_render, "render", render_falso(llamadas["render"]))
    return llamadas


def _episodio(tmp_path: Path, perfil: dict | None = None, *, con_registro: bool = True) -> Episodio:
    perfil = perfil or perfil_de_prueba()
    canal = canal_de_prueba(tmp_path / "canal", perfil)
    run = prepara_run(tmp_path / "videos" / RUN_ID, LAMINAS_PRUEBA, con_registro=con_registro)
    guion_en_el_canal(canal, RUN_ID, "prueba")
    return Episodio(run_dir=run, run_id=RUN_ID, canal_dir=canal, perfil=perfil, idioma="en")


def _bloques_srt(ruta: Path) -> list[tuple[float, float, str]]:
    salida = []
    for bloque in re.split(r"\n\n", ruta.read_text(encoding="utf-8").strip()):
        _, tiempos, texto = bloque.split("\n", 2)
        a, b = (
            sum(float(x) * f for x, f in zip(t.replace(",", ".").split(":"), (3600, 60, 1)))
            for t in tiempos.split(" --> ")
        )
        salida.append((a, b, texto))
    return salida


# ------------------------------------------------------------------------------------------ alinea
def test_el_srt_son_los_cues_de_la_escena(tmp_path, gpu):
    ep = _episodio(tmp_path)
    hecho = etapas.alinea(ep)
    bloques = _bloques_srt(hecho["srt"])
    cues = ep.linea().cues
    assert [texto for _, _, texto in bloques] == [c.texto for c in cues], "una línea del .srt por cue, mismo texto"
    assert all(abs(a - c.ini) < 0.35 and abs(b - c.fin) < 0.35 for (a, b, _), c in zip(bloques, cues))
    assert hecho["srt"].name == "subtitulos.en.srt" and hecho["srt"].parent.name == config.DIR_SUBIR_AL_CANAL
    assert gpu == {**gpu, "gpu": 1, "whisper": 1}, "mira la GPU antes de lanzar whisper"
    registro = json.loads((ep.run_dir / provenance.SUBTITLE_RECORDS_FILENAME).read_text(encoding="utf-8"))[0]
    assert registro["srt"] and "cues" in registro["lineas_del_srt"]
    partes = (config.revision_del_run(ep.run_dir) / "guion-por-partes.md").read_text(encoding="utf-8")
    assert [linea for linea in partes.splitlines() if linea.startswith("- `C")] == [
        f"- `C{c.n}` ({int(c.ini // 60)}:{c.ini % 60:04.1f}) {c.texto}" for c in cues
    ], "el guion por partes numera los mismos cues"


def test_control_otro_troceo_de_los_cues_cambia_el_srt_con_ellos(tmp_path, gpu):
    """Si el `.srt` saliera de su propio troceo (el del karaoke quemado), cambiar los cues no lo cambiaría."""
    perfil = perfil_de_prueba()
    perfil["escena"]["cues"] = {"max_palabras": 4, "max_caracteres": 30}
    ep = _episodio(tmp_path, perfil)
    bloques = _bloques_srt(etapas.alinea(ep)["srt"])
    assert len(ep.linea().cues) > 6, "con cues de 4 palabras hay más que los 6 del perfil de prueba"
    assert [texto for _, _, texto in bloques] == [c.texto for c in ep.linea().cues]


def test_sin_su_audio_no_se_gasta_la_gpu(tmp_path, gpu):
    ep = _episodio(tmp_path)
    config.audio_de_lamina(ep.run_dir, 2).unlink()
    with pytest.raises(etapas.ErrorDeEtapa, match="lámina 2"):
        etapas.alinea(ep)
    assert gpu["gpu"] == 0 and gpu["whisper"] == 0


def test_sin_pausas_declaradas_el_episodio_para_antes_de_todo(tmp_path, gpu):
    """El control de «las pausas las declara el canal, sin defecto»: sin ellas no hay episodio, ni GPU, ni whisper."""
    perfil = perfil_de_prueba()
    del perfil["escena"]["pausas"]
    with pytest.raises(ErrorDeEpisodio, match="pausas.entre_partes_s"):
        _episodio(tmp_path, perfil)
    assert gpu["gpu"] == 0 and gpu["whisper"] == 0


# ------------------------------------------------------------------------------------------ de extremo a extremo
@pytest.fixture
def compuesto(tmp_path, gpu):
    ep = _episodio(tmp_path)
    etapas.alinea(ep)
    activos = etapas.activos(ep)
    escena = etapas.escena(ep)
    return {"ep": ep, "activos": activos, "escena": escena, "gpu": gpu}


def test_de_extremo_a_extremo_sin_gpu_hasta_la_composicion(compuesto):
    ep, escena = compuesto["ep"], compuesto["escena"]
    # La parada 1: sin imágenes nuevas (el guion no define `activos`), enseña los recortes del catálogo.
    assert compuesto["activos"]["faltan"] == [] and compuesto["activos"]["generados"] == 0
    catalogo = ep.catalogo()
    assert compuesto["activos"]["pagina"].read_text(encoding="utf-8").count('class="damero"') == len(catalogo) == 6
    # Las seis comprobaciones del episodio de prueba, sin un defecto y sin correcciones (como en F6.2b).
    assert escena["defectos"] == {k: [] for k in escena["defectos"]} and len(escena["defectos"]) == 6
    assert escena["correcciones"] == []
    # La composición: el GUION de la escena, con la narración y los dos efectos (pop de la tarjeta, whoosh de la
    # transición) como pistas de audio, y la fuente que pide el CSS del canal.
    guion = compone.lee_guion(escena["composicion"])
    assert guion["duracion"] == pytest.approx(ep.linea().total)
    pagina = escena["composicion"].read_text(encoding="utf-8")
    audios = re.findall(r'<audio id="([^"]+)" src="([^"]+)"', pagina)
    assert audios == [
        ("narracion", "assets/audio/narracion.wav"),
        ("sfx0", "assets/sfx/pop.mp3"),
        ("sfx1", "assets/sfx/whoosh.mp3"),
    ]
    assert (escena["composicion"].parent / "assets" / "fuentes" / FUENTE_PRUEBA).is_file()
    # La parada 2: un fotograma por plano (el medio de cada uno) y la página con ellos dentro.
    (llamada,) = compuesto["gpu"]["snapshot"]
    planos = sorted(guion["planos"], key=lambda p: p["t0"])
    assert len(llamada["tiempos"]) == len(planos)
    assert all(p["t0"] < t < p["t1"] for t, p in zip(llamada["tiempos"], planos))
    assert escena["pagina"].read_text(encoding="utf-8").count("data:image/jpeg") == len(guion["planos"])
    # Y la procedencia de todo el run cuadra: voz, recortes, efectos, fuente y .srt.
    informe = provenance.sync(ep.run_dir, verbose=False)
    assert informe["cuadra"], informe
    assert informe["por_tipo"] == {"audio": 2, "fuente": 1, "imagen": 5, "sonido": 2, "subtitulos": 1}


def test_control_una_imagen_sin_procedencia_para_la_escena_antes_de_componer(tmp_path, gpu):
    ep = _episodio(tmp_path, con_registro=False)
    etapas.alinea(ep)
    with pytest.raises(etapas.ErrorDeEtapa, match="sin procedencia"):
        etapas.escena(ep)
    assert not (config.composicion_del_run(ep.run_dir) / "index.html").exists()
    assert gpu["snapshot"] == []


# ------------------------------------------------------------------------------------------ render y montaje.json
def test_el_render_escribe_montaje_json_con_su_contrato(compuesto):
    ep, escena = compuesto["ep"], compuesto["escena"]
    hecho = etapas.render(ep, huella_composicion=escena["huella_composicion"], huella_guion=escena["huella_guion"])
    montaje = json.loads((ep.run_dir / "montaje.json").read_text(encoding="utf-8"))
    linea = ep.linea()
    assert montaje["motor"] == "escena"
    # El formato del catálogo, del perfil del canal (F7.11): el de prueba no declara bloque de formato.
    assert montaje["formato"] == "personajes"
    assert montaje["salida"] == "subir-al-canal/final.mp4" and hecho["salida"] == ep.run_dir / montaje["salida"]
    assert montaje["duracion_s"] == pytest.approx(linea.total, abs=1e-3)
    assert [(d["plano"], d["slide"]) for d in montaje["detalle"]] == [(1, 1), (2, 2)]
    for k, d in enumerate(montaje["detalle"]):
        assert d["inicio_s"] == pytest.approx(linea.inicio[k], abs=1e-3)
        assert d["segundos"] == pytest.approx(linea.tramos[k], abs=1e-3)
    assert montaje["silencios"] == {"intro_s": 1.0, "entre_partes_s": 2.0, "cola_s": 1.5}
    assert montaje["herramientas"]["hyperframes"] and montaje["sonido"]["normalizado"] is False
    # El vídeo entra en la procedencia como lo que es: un render del motor de escena, sin modelo generativo.
    informe = provenance.sync(ep.run_dir, verbose=False)
    assert informe["cuadra"], informe
    video = next(a for a in provenance.read_ledger(ep.run_dir)["assets"] if a["tipo"] == "video")
    assert video["id"] == "subir-al-canal/final.mp4"
    assert "motor de escena" in video["origen"] and "Ken Burns" not in video["origen"]
    assert video["modelo"].startswith("ninguno: render determinista con HyperFrames")
    assert video["detalle"]["formato"] == "personajes"
    # Y cuenta las figuras que se mueven, que es lo que decide qué declara la subida (F6.8).
    index = config.composicion_del_run(ep.run_dir) / "index.html"
    actores = sum(len(p["actores"]) for p in compone.lee_guion(index)["planos"])
    objetos = index.read_text(encoding="utf-8").count(etapas.OBJETO_DEL_CATALOGO)
    assert actores > 0 and montaje["actores"] == actores + objetos and video["detalle"]["actores"] == actores + objetos
    assert any(i.startswith("biblioteca/sfx/") for i in video["derivado_de"]), "los efectos están dentro del vídeo"
    # La marca de IA (OC1.5): el render deja el vídeo sin marca en `sonido/`, que no es un asset, y la marca escribe
    # `final.mp4`. Su registro va a `montaje.json` y al del vídeo en `assets.json`, que nombra Video Seal y AudioSeal
    # con su licencia y su url sin dejar de decir que el vídeo no lo generó ningún modelo.
    assert compuesto["gpu"]["marca"] == ["final.mp4"]
    assert (config.sonido_del_run(ep.run_dir) / "final-sin-marca.mp4").is_file()
    assert montaje["marca_ia"]["detectada"] is True and montaje["marca_ia"]["sha256"] == marca_ia.sha256_de(
        hecho["salida"]
    )
    assert video["detalle"]["marca_ia"] == montaje["marca_ia"]
    assert "marca de agua con Video Seal 1.0" in video["modelo"] and "AudioSeal 0.2.0" in video["modelo"]
    assert "facebookresearch/videoseal" in video["url"] and "facebookresearch/audioseal" in video["url"]
    assert video["licencia"].startswith("heredada de los assets") and "(MIT" in video["licencia"]
    assert not any("final-sin-marca" in a["id"] for a in provenance.read_ledger(ep.run_dir)["assets"])
    # La declaración de IA de la subida (decisión 7) se sigue derivando: voz sintética e imágenes generadas, y ni
    # los efectos ni la fuente (sin modelo) ni el vídeo (render, y su marca de agua) se cuelan como IA.
    texto, avisos = publicacion.declaracion_de_ia(ep.run_dir, "en")
    assert "synthetic voice" in texto and "AI-generated" in texto and avisos == []
    # Y describe un vídeo de escena animado, no láminas fijas (auditoría de F6.2d, recomendación 5).
    assert "Animated scenes" in texto and "Still illustrations" not in texto


def test_control_si_la_marca_de_ia_falla_no_queda_final_mp4(compuesto):
    """Un vídeo sin su marca no se entrega (OC1.5): ni el `final.mp4` a medias ni el `montaje.json` que lo daría por
    hecho."""
    ep, escena = compuesto["ep"], compuesto["escena"]

    def falla(origen, destino):
        Path(destino).write_bytes(b"a medias")
        raise marca_ia.ErrorDeMarca("la autocomprobación no encuentra la marca en final.mp4")

    with pytest.raises(etapas.ErrorDeEtapa, match="marca de IA no se pudo poner.*autocomprobación"):
        etapas.render(
            ep, huella_composicion=escena["huella_composicion"], huella_guion=escena["huella_guion"], marca=falla
        )
    assert len(compuesto["gpu"]["render"]) == 1, "el render sí se hizo"
    assert not (ep.run_dir / "subir-al-canal" / "final.mp4").exists()
    assert not (ep.run_dir / "montaje.json").exists()


def test_control_el_render_no_renderiza_lo_que_no_se_reviso(compuesto):
    ep, escena = compuesto["ep"], compuesto["escena"]
    index = escena["composicion"]
    original = index.read_text(encoding="utf-8")
    index.write_text(original + "<!-- tocada después de la parada 2 -->", encoding="utf-8")
    with pytest.raises(etapas.ErrorDeEtapa, match="composición ha cambiado"):
        etapas.render(ep, huella_composicion=escena["huella_composicion"], huella_guion=escena["huella_guion"])
    index.write_text(original, encoding="utf-8")
    ep.guion_py.write_text(ep.guion_py.read_text(encoding="utf-8") + "\n# otro plano\n", encoding="utf-8")
    with pytest.raises(etapas.ErrorDeEtapa, match="guion de escena"):
        etapas.render(ep, huella_composicion=escena["huella_composicion"], huella_guion=escena["huella_guion"])
    assert compuesto["gpu"]["render"] == [] and not (ep.run_dir / "subir-al-canal" / "final.mp4").exists()


def test_control_un_asset_cambiado_tras_la_parada_2_tampoco_se_renderiza(compuesto):
    """La huella de la parada 2 cubre `composicion/assets/` entera (auditoría de F6.2d, recomendación 3)."""
    ep, escena = compuesto["ep"], compuesto["escena"]
    carpeta = escena["composicion"].parent
    imagen = next((carpeta / "assets" / "img").glob("*.png"))
    original = imagen.read_bytes()
    imagen.write_bytes(original + b"\0")
    with pytest.raises(etapas.ErrorDeEtapa, match="composición ha cambiado"):
        etapas.render(ep, huella_composicion=escena["huella_composicion"], huella_guion=escena["huella_guion"])
    assert compuesto["gpu"]["render"] == []
    # Control: lo que no entra en el vídeo (lo que HyperFrames deje junto a la composición) no cuenta, y con la imagen
    # como estaba el render sale.
    imagen.write_bytes(original)
    (carpeta / ".hyperframes").mkdir(exist_ok=True)
    (carpeta / ".hyperframes" / "cache.json").write_text("{}", encoding="utf-8")
    etapas.render(ep, huella_composicion=escena["huella_composicion"], huella_guion=escena["huella_guion"])
    assert len(compuesto["gpu"]["render"]) == 1


def test_los_capitulos_y_la_narracion_leen_donde_empieza_cada_lamina(compuesto):
    """Con pausas entre láminas, sumar la voz de las anteriores da un inicio falso: por eso `inicio_s`."""
    ep, escena = compuesto["ep"], compuesto["escena"]
    etapas.render(ep, huella_composicion=escena["huella_composicion"], huella_guion=escena["huella_guion"])
    montaje = json.loads((ep.run_dir / "montaje.json").read_text(encoding="utf-8"))
    esperado = {1: ep.linea().inicio[0], 2: ep.linea().inicio[1]}
    assert compone_descripcion.inicios_por_slide(montaje) == pytest.approx(esperado, abs=1e-3)
    assert integridad_narracion._del_montaje(ep.run_dir)[0] == pytest.approx(esperado, abs=1e-3)
    # Control: el mismo montaje sin `inicio_s` se suma como el del motor viejo, y la lámina 2 cae 3 s antes.
    for d in montaje["detalle"]:
        del d["inicio_s"]
    sumado = compone_descripcion.inicios_por_slide(montaje)
    assert sumado[2] == pytest.approx(ep.linea().tramos[0], abs=1e-3) and sumado[2] < esperado[2] - 2.9


# ------------------------------------------------------------------------------------------ las paradas, en el pipeline
@pytest.fixture
def pipeline_de_prueba(tmp_path, monkeypatch, gpu):
    """El pipeline con el canal ficticio: su estado, sus vídeos y su procedencia en carpetas temporales."""
    import pipeline

    perfil = perfil_de_prueba()
    canal = canal_de_prueba(tmp_path / "canal", perfil)
    monkeypatch.setattr(run_state, "STATE_DIR", tmp_path / "estado")
    monkeypatch.setattr(run_state, "CANAL_VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(run_state, "CANAL_ACTIVO", "canal-de-prueba")
    for nombre, valor in (("CANAL_DIR", canal), ("CANAL_PERFIL", perfil), ("SUBTITLE_LANG", "en")):
        monkeypatch.setattr(config, nombre, valor)
    monkeypatch.setattr(config, "CANAL_ACTIVO", "canal-de-prueba")
    monkeypatch.setattr(provenance, "ASSETS_MIRROR_DIR", tmp_path / "copia-versionada")
    abiertas: list[str] = []
    monkeypatch.setattr(pagina_local, "abre", lambda ruta: abiertas.append(Path(ruta).name) or True)
    hechas: list[str] = []

    def etapa_falsa(nombre):
        def f(run_id):
            hechas.append(nombre)
            run_state.update_stage(run_id, nombre, "complete", "hecha en la prueba")

        return f

    for nombre in ("images", "tts", "thumbnail"):
        monkeypatch.setattr(pipeline, f"stage_{nombre}", etapa_falsa(nombre))
    monkeypatch.setattr(pipeline, "_abre_la_guia", lambda state: None)
    state = run_state.create_run("Episodio de prueba", "manual", "")
    prepara_run(Path(state["output_dir"]), LAMINAS_PRUEBA)
    guion_en_el_canal(canal, state["run_id"], "prueba")
    return {"pipeline": pipeline, "run_id": state["run_id"], "abiertas": abiertas, "hechas": hechas, "gpu": gpu}


def _estado(run_id: str) -> dict:
    return {e: d["status"] for e, d in run_state.load_run(run_id)["stages"].items()}


def test_el_pipeline_se_detiene_en_las_dos_paradas_y_abre_su_pagina(pipeline_de_prueba):
    p, run_id, abiertas = pipeline_de_prueba["pipeline"], pipeline_de_prueba["run_id"], pipeline_de_prueba["abiertas"]
    # --run-all llega hasta la parada 1 y para: abre la página de las imágenes, y la escena ni se toca.
    p.run_all(run_id, sin_subida=True)
    assert abiertas == ["activos.html"]
    assert _estado(run_id)["activos"] == "complete" and _estado(run_id)["escena"] == "pending"
    assert run_state.load_run(run_id)["status"] == "en_parada"
    assert run_state.load_run(run_id)["parada"]["sigue_con"] == "escena"
    # Control: otro --run-all NO pasa la parada: vuelve a abrir la misma página y no compone nada.
    p.run_all(run_id, sin_subida=True)
    assert abiertas == ["activos.html", "activos.html"]
    assert _estado(run_id)["escena"] == "pending" and pipeline_de_prueba["gpu"]["snapshot"] == []
    # Seguir es --stage escena: compone, saca los fotogramas y para en la parada 2 con su página.
    p.stage_escena(run_id)
    assert abiertas[-1] == "fotogramas.html" and _estado(run_id)["render"] == "pending"
    # Control: --run-all tampoco pasa la parada 2 (ni renderiza ni hace la miniatura).
    p.run_all(run_id, sin_subida=True)
    assert abiertas[-1] == "fotogramas.html"
    assert pipeline_de_prueba["gpu"]["render"] == [] and "thumbnail" not in pipeline_de_prueba["hechas"]
    # Seguir es --stage render: deja el vídeo donde lo buscan la miniatura y la subida (la etapa assembly).
    p.stage_render(run_id)
    estado = run_state.load_run(run_id)
    assert _estado(run_id)["render"] == "complete" and _estado(run_id)["assembly"] == "complete"
    assert estado["stages"]["assembly"]["output"].endswith(str(Path("subir-al-canal") / "final.mp4"))
    assert estado["status"] == "assembled" and estado["parada"] is None
    # Con el render hecho, --run-all sigue como el de siempre: la miniatura, y la subida se omite a propósito.
    p.run_all(run_id, sin_subida=True)
    assert pipeline_de_prueba["hechas"].count("thumbnail") == 1
    assert run_state.load_run(run_id)["stages"]["upload"]["status"] == "skipped"


def test_control_las_paradas_no_se_saltan_con_stage(pipeline_de_prueba):
    p, run_id = pipeline_de_prueba["pipeline"], pipeline_de_prueba["run_id"]
    with pytest.raises(RuntimeError, match="parada 1"):
        p.stage_escena(run_id)
    with pytest.raises(RuntimeError, match="parada 2"):
        p.stage_render(run_id)
    assert _estado(run_id)["escena"] == "blocked" and _estado(run_id)["render"] == "blocked"
    assert pipeline_de_prueba["gpu"]["snapshot"] == [] and pipeline_de_prueba["gpu"]["render"] == []


def test_rehacer_la_escena_obliga_a_renderizar_otra_vez(pipeline_de_prueba):
    """Si la escena se rehace tras el render, el vídeo viejo no puede seguir contando como el del run."""
    p, run_id = pipeline_de_prueba["pipeline"], pipeline_de_prueba["run_id"]
    p.run_all(run_id, sin_subida=True)
    p.stage_escena(run_id)
    p.stage_render(run_id)
    p.stage_escena(run_id)
    assert _estado(run_id)["render"] == "pending" and _estado(run_id)["assembly"] == "pending"


# ------------------------------------------------------------------------------------------ un solo motor (F6.7)
# El estado de un run del motor de láminas, retirado en F6.7, tal como lo dejó `create_run` antes: sin `motor`.
ESTADO_VIEJO = {
    "title": "Uno",
    "mode": "manual",
    "voice": "",
    "animacion": "lienzo",
    "channel_url": "",
    "status": "uploaded",
    "created_at": "2026-09-16T20:56:15",
    "stages": {e: {"status": "complete"} for e in ("slides_json", "images", "tts", "assembly", "thumbnail", "upload")},
    "slide_assets": {},
}


def test_un_run_nuevo_es_del_motor_de_escena_y_uno_viejo_se_lee_pero_no_se_produce(tmp_path, monkeypatch):
    import pipeline

    monkeypatch.setattr(run_state, "STATE_DIR", tmp_path / "estado")
    monkeypatch.setattr(run_state, "CANAL_VIDEOS_DIR", tmp_path / "videos")
    nuevo = run_state.create_run("Dos", "manual", "")
    assert nuevo["motor"] == "escena" and run_state.motor_de(nuevo) == "escena"
    assert "animacion" not in nuevo, "la animación era del motor de láminas"
    assert list(nuevo["stages"]) == list(run_state.ETAPAS)
    # El run viejo, escrito como lo escribía el pipeline antes de F6.7: se LEE (su motor, sus etapas) …
    viejo = {**ESTADO_VIEJO, "run_id": "2026-09-16_205615_uno", "output_dir": str(tmp_path / "videos" / "uno")}
    run_state._save_state(viejo["run_id"], viejo)
    assert run_state.motor_de(run_state.load_run(viejo["run_id"])) == "montaje"
    assert [r["run_id"] for r in run_state.list_runs()] == sorted([viejo["run_id"], nuevo["run_id"]], reverse=True)
    # … y no se produce: cada etapa que hace el vídeo, la miniatura o la subida para con el motivo, antes de tocar
    # nada. La subida, también forzada: sería resubir un vídeo viejo (R3 de la revisión de F6.7).
    for etapa in ("images", "tts", "alinea", "activos", "escena", "render", "assembly", "thumbnail", "upload"):
        with pytest.raises(pipeline.MotorRetirado, match="motor de láminas, retirado el 02-10-2026"):
            getattr(pipeline, f"stage_{etapa}")(viejo["run_id"])
    with pytest.raises(pipeline.MotorRetirado, match="motor de láminas, retirado el 02-10-2026"):
        pipeline.stage_upload(viejo["run_id"], forzar=True)
    with pytest.raises(pipeline.MotorRetirado, match="ya no se produce"):
        pipeline.run_all(viejo["run_id"], sin_subida=True)
    assert run_state.load_run(viejo["run_id"])["stages"] == viejo["stages"], "negarse no toca el estado del run"
    # La etapa del montaje viejo, pedida sobre un run nuevo, dice qué hacer en su lugar.
    with pytest.raises(RuntimeError, match="el vídeo lo hace `render`"):
        pipeline.stage_assembly(nuevo["run_id"])
    assert run_state.load_run(nuevo["run_id"])["stages"]["assembly"]["status"] == "pending"


def test_control_create_run_ya_no_admite_motor_ni_animacion():
    """Control: los dos argumentos del motor de láminas no se aceptan en silencio."""
    with pytest.raises(TypeError):
        run_state.create_run("Tres", "manual", "", animacion="lienzo")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        run_state.create_run("Cuatro", "manual", "", motor="escena")  # type: ignore[call-arg]


def test_la_cli_ya_no_tiene_motor_ni_animacion(monkeypatch, capsys):
    import pipeline

    monkeypatch.setattr(config, "CANAL_ERROR", None)  # que `main` llegue a argparse con cualquier .env
    for flag in ("--motor", "--animacion"):
        monkeypatch.setattr("sys.argv", ["pipeline.py", "--create", "--title", "x", flag, "escena"])
        with pytest.raises(SystemExit) as salida:
            pipeline.main()
        assert salida.value.code == 2 and "unrecognized arguments" in capsys.readouterr().err


def test_la_cli_se_niega_con_un_run_viejo_sin_traza(tmp_path, monkeypatch, capsys):
    """R2 de la revisión de F6.7: la negativa es prevista, así que sale el motivo con exit 1 y sin traceback."""
    import pipeline

    monkeypatch.setattr(config, "CANAL_ERROR", None)
    monkeypatch.setattr(run_state, "STATE_DIR", tmp_path / "estado")
    viejo = {**ESTADO_VIEJO, "run_id": "2026-09-16_205615_uno", "output_dir": str(tmp_path / "videos" / "uno")}
    run_state._save_state(viejo["run_id"], viejo)
    for etapa in ("--stage images", "--stage upload --forzar-subida", "--run-all"):
        monkeypatch.setattr("sys.argv", ["pipeline.py", "--run-id", viejo["run_id"], *etapa.split()])
        with pytest.raises(SystemExit) as salida:
            pipeline.main()
        dicho = capsys.readouterr()
        assert salida.value.code == 1
        assert f"[FAIL] el run {viejo['run_id']} es del motor de láminas, retirado" in dicho.out, dicho.out
        assert "Traceback" not in dicho.out + dicho.err


def test_un_run_de_otro_canal_no_se_mezcla_con_el_activo(tmp_path, monkeypatch):
    import pipeline

    monkeypatch.setattr(config, "CANAL_ACTIVO", "canal-de-prueba")
    with pytest.raises(RuntimeError, match="--canal otro-canal"):
        pipeline._episodio({"run_id": "x", "canal": "otro-canal", "output_dir": str(tmp_path)})


# ------------------------------------------------------------------------------------------ con música
MUSICA_PRUEBA = {
    "activa": True,
    "escena": "calm music for a test",
    "volumen_db": -17.0,
    "tramo_segundos": 30,
    "solape_segundos": 3,
    "sonoridad_por_tramo": None,
    "umbral_ducking": 0.05,
    "ratio_ducking": 8,
    "ataque_ms": 20,
    "suelta_ms": 500,
    "semilla_base": 11,
}


@pytest.fixture
def con_musica(tmp_path, monkeypatch, gpu):
    """Un canal con lecho: ACE-Step sustituido por un tono del largo pedido, con su registro como el de verdad."""
    import contextlib
    import subprocess

    from lib import comfy_client, musica

    generados = []

    def genera_lecho(duracion, output_dir, escena=None, semilla_base=None, perfil=None):
        lecho = Path(output_dir) / "lecho.wav"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=220:duration={duracion}"]
            + ["-ac", "2", "-ar", "48000", str(lecho)],
            check=True,
        )
        registro = {
            "file": str(lecho),
            "modelo": "ACE-Step (prueba)",
            "licencia": "Apache-2.0",
            "duracion_s": round(duracion, 2),
        }
        (Path(output_dir) / provenance.MUSIC_RECORDS_FILENAME).write_text(json.dumps([registro]), encoding="utf-8")
        generados.append(duracion)
        return registro

    monkeypatch.setattr(musica, "genera_lecho", genera_lecho)
    monkeypatch.setattr(comfy_client, "server_is_alive", lambda *a, **k: True)
    monkeypatch.setattr(comfy_client, "comfy_server", contextlib.nullcontext)
    monkeypatch.setattr(comfy_client, "free_memory", lambda: None)
    perfil = perfil_de_prueba()
    perfil["musica"] = dict(MUSICA_PRUEBA)
    ep = _episodio(tmp_path, perfil)
    etapas.alinea(ep)
    etapas.activos(ep)
    return {"ep": ep, "generados": generados, "escena": etapas.escena(ep)}


def test_con_musica_el_lecho_entra_apartado_y_el_video_se_normaliza(con_musica):
    ep, escena = con_musica["ep"], con_musica["escena"]
    pagina = escena["composicion"].read_text(encoding="utf-8")
    assert '<audio id="lecho" src="assets/audio/lecho.wav"' in pagina and 'data-track-index="9"' in pagina
    apartado = config.sonido_del_run(ep.run_dir) / "lecho-apartado.wav"
    assert audio_de(apartado) == pytest.approx(ep.linea().total, abs=0.01), "el lecho dura lo que el episodio"
    # Una segunda pasada por la escena no vuelve a generar el lecho: el del run ya dura lo que hace falta.
    etapas.escena(ep)
    assert con_musica["generados"] == [pytest.approx(ep.linea().total)]
    # Tras el render, el vídeo entero va al objetivo del estudio (como el paso final de musica.mezcla).
    escena = etapas.escena(ep)
    etapas.render(ep, huella_composicion=escena["huella_composicion"], huella_guion=escena["huella_guion"])
    montaje = json.loads((ep.run_dir / "montaje.json").read_text(encoding="utf-8"))
    objetivo = config.base_del_estudio()["produccion"]["lecho_musical"]["objetivo_lufs"]
    assert montaje["sonido"]["normalizado"] is True
    assert montaje["sonido"]["medicion"]["lufs"] == pytest.approx(objetivo, abs=1.5)
    assert (config.sonido_del_run(ep.run_dir) / "final-sin-normalizar.mp4").is_file()
    assert provenance.sync(ep.run_dir, verbose=False)["por_tipo"]["musica"] == 1


def audio_de(ruta: Path) -> float:
    from lib.medios import get_audio_duration

    return get_audio_duration(str(ruta))
