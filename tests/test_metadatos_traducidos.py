"""El título y la descripción en español (SEO) del LEEME, y la orden que lo rehace (addendum fila 285).

Correr: .venv\\Scripts\\python -m pytest -q tests/test_metadatos_traducidos.py

Petición del 07-10-2026: «Cuando produzcas tanto el título como la descripción y lo generes en el Leeme.html, también
añade la versión SEO en español del título y la descripción». Lo que fijan estas pruebas, cada una con su control
negativo:

1. **El canal lo declara** (`perfil.json → publicacion.metadatos_traducidos`). Un canal que no lo declara no lleva
   versión traducida, no se le exige nada y su LEEME no cambia.
2. **La descripción en español sale con el minutaje de la inglesa**, los `titulo_es` de los capítulos, la bibliografía
   con sus rótulos y el nombre de cada ficha en español, y la declaración de IA en español.
3. **La subida para antes de gastar cuota** si falta `title_es`, `description_es` o el `titulo_es` de un capítulo, o si
   la descripción en español no lleva los mismos marcadores que la inglesa. Nada de esto viaja a la API de YouTube.
4. **El LEEME** enseña los dos textos para copiar, escapados, y dice dónde se pegan.
5. **`--rehace-leeme`** reescribe el LEEME de un run ya subido sin llamar a la API ni tocar su estado.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from lib import config, marca_ia, provenance, publicacion, subtitulos, youtube_client
from lib.publicacion import ErrorDeMetadatos
from scripts import compone_descripcion

RAIZ = Path(__file__).resolve().parent.parent
PERFIL_PRUEBA = RAIZ / "tests" / "escena" / "canal-prueba" / "perfil.json"
RUN_ID = "2026-10-07_000000_prueba-fila285"
FICHA = "costco-cuotas"
CITA = "Costco Wholesale Corporation (2025). Form 10-K. https://www.sec.gov/x <b>&</b>"

# La salida de `fuentes.py --bibliografia` (el formato que lee `bloque_bibliografia`), sin lanzar el proceso.
SALIDA_FUENTES = (
    "— Why Costco Barely Profits (Por qué Costco apenas gana) —\n"
    f"  {CITA}\n\n"
    "Las fuentes citadas se han verificado una a una contra el registro de su editor o archivo.\n"
)

DESCRIPCION_EN = "Costco sells a lot.\n\n<<CAPITULOS>>\n\n<<BIBLIOGRAFIA>>"
DESCRIPCION_ES = "Costco vende mucho.\n\n<<CAPITULOS>>\n\n<<BIBLIOGRAFIA>>"
CAPITULOS = [
    {"slide_inicial": 1, "titulo": "How Does Costco Make Money?", "titulo_es": "¿Cómo gana dinero Costco?"},
    {"slide_inicial": 4, "titulo": "Revenue vs Profit", "titulo_es": "¿Qué diferencia hay entre ingresos y beneficio?"},
    {"slide_inicial": 8, "titulo": "The Fee", "titulo_es": "¿Cuánto ingresa Costco por las cuotas?"},
]
SRT_EN = "1\n00:00:01,000 --> 00:00:03,000\nHello.\n"


def _slides(**cambios) -> dict:
    slides = {
        "title": "Why Costco Barely Profits",
        "title_es": "Por qué Costco apenas gana dinero",
        "description": DESCRIPCION_EN,
        "description_es": DESCRIPCION_ES,
        "fuentes": [FICHA],
        "capitulos": copy.deepcopy(CAPITULOS),
        "slides": [],
    }
    slides.update(cambios)
    return slides


def _perfil(metadatos=("es",)) -> dict:
    """El perfil del canal de prueba, con `.srt` sin traducciones y, si se pide, la declaración de la fila 285."""
    perfil = json.loads(PERFIL_PRUEBA.read_text(encoding="utf-8"))
    perfil["subtitulos"] = {
        "activos": True,
        "srt": True,
        "fuente": "Verdana",
        "cuerpo": 60,
        "max_palabras_por_linea": 10,
        "margen_inferior_px": 90,
        "margen_lateral_px": 200,
        "traducciones": [],
        "personajes": {},
    }
    if metadatos is not None:
        perfil.setdefault("publicacion", {})["metadatos_traducidos"] = list(metadatos)
    return perfil


@pytest.fixture
def run(tmp_path, monkeypatch, marca_falsa) -> Path:
    """Un run del motor de escena: `montaje.json` con huecos entre láminas, `slides.json`, el `.srt` y la ficha."""
    monkeypatch.setattr(provenance, "ASSETS_MIRROR_DIR", tmp_path / "copia-versionada")
    monkeypatch.setattr(compone_descripcion, "CANAL_VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(compone_descripcion, "CANAL_DATOS_DIR", tmp_path / "datos")
    monkeypatch.setattr(compone_descripcion, "NARRATION_LANG", "en")
    monkeypatch.setattr(compone_descripcion, "_lanza_fuentes", lambda _fichas: SALIDA_FUENTES)
    fichas = tmp_path / "datos" / "fuentes"
    fichas.mkdir(parents=True)
    (fichas / f"{FICHA}.json").write_text(
        json.dumps({"nombre_en": "Why Costco Barely Profits", "nombre_es": "Por qué Costco apenas gana"}),
        encoding="utf-8",
    )
    run_dir = tmp_path / "videos" / RUN_ID
    carpeta = config.dir_subir_al_canal(run_dir, crear=True)
    (carpeta / "final.mp4").write_bytes(b"video")
    srt = carpeta / "subtitulos.en.srt"
    srt.write_text(SRT_EN, encoding="utf-8")
    registro = {
        "modelo_alineacion": "openai/whisper-small",
        "licencia": subtitulos.LICENCIA_ALINEADOR,
        "origen": "alineación en local",
        "idioma": "en",
        "srt": str(srt),
    }
    (run_dir / provenance.SUBTITLE_RECORDS_FILENAME).write_text(json.dumps([registro]), encoding="utf-8")
    # Cada lámina dura 40 s y entre una y otra hay 1,5 s de silencio que ningún plano cubre: el minutaje sale de
    # `inicio_s`, no de sumar planos (y así la prueba distingue las dos cuentas).
    detalle = [
        {"plano": n, "slide": n, "inicio_s": 1.0 + (n - 1) * 41.5, "segundos": 40.0, "fin_s": 41.0 + (n - 1) * 41.5}
        for n in range(1, 11)
    ]
    montaje = {"motor": "escena", "formato": "pizarra", "salida": "subir-al-canal/final.mp4", "actores": 0}
    montaje.update(duracion_s=416.0, detalle=detalle)
    # El vídeo lleva su marca de IA (OC1.5): sin ella la subida se niega antes de gastar cuota.
    montaje["marca_ia"] = marca_falsa.registro(carpeta / "final.mp4")
    (run_dir / provenance.ASSEMBLY_SUMMARY_FILENAME).write_text(json.dumps(montaje), encoding="utf-8")
    _escribe_slides(run_dir, _slides())
    return run_dir


def _escribe_slides(run_dir: Path, slides: dict) -> None:
    (run_dir / "slides.json").write_text(json.dumps(slides, ensure_ascii=False), encoding="utf-8")


def _lee_slides(run_dir: Path) -> dict:
    return json.loads((run_dir / "slides.json").read_text(encoding="utf-8"))


def _tiempos(descripcion: str) -> list[str]:
    return re.findall(r"^(\d\d:\d\d) ", descripcion, re.M)


# ------------------------------------------------------------------------------------------ 1. lo declara el canal
def test_un_canal_que_no_lo_declara_no_exige_nada():
    """Un canal que no lo declara: su subida es la de siempre aunque el guion no traiga ningún campo traducido."""
    assert publicacion.exige_metadatos_traducidos({"title": "T"}, _perfil(None), origen="en") == []


def test_control_un_canal_que_lo_declara_si_lo_exige():
    with pytest.raises(ErrorDeMetadatos, match="title_es"):
        publicacion.exige_metadatos_traducidos({"title": "T"}, _perfil(), origen="en")
    assert publicacion.exige_metadatos_traducidos(_slides(), _perfil(), origen="en") == ["es"]


@pytest.mark.parametrize(
    ("valor", "dice"),
    [
        ("es", "lista de códigos"),
        (["ES"], "lista de códigos"),
        (["es", "es"], "repite"),
        (["en"], "idioma del título"),
        (["fr"], "declaración de IA"),
    ],
)
def test_una_declaracion_que_no_se_entiende_para(valor, dice):
    perfil = _perfil()
    perfil["publicacion"]["metadatos_traducidos"] = valor
    with pytest.raises(ErrorDeMetadatos, match=dice):
        publicacion.idiomas_de_los_metadatos(perfil, origen="en")


def test_cada_perfil_del_repositorio_se_entiende():
    """Cada canal declara sus metadatos traducidos de una forma que se entiende; no declararlos es `[]`."""
    for ruta in sorted((RAIZ / "canales").glob("*/perfil.json")):
        perfil = json.loads(ruta.read_text(encoding="utf-8"))
        assert isinstance(publicacion.idiomas_de_los_metadatos(perfil, origen="en"), list), ruta.parent.name


# ------------------------------------------------------------------------------------------ 2. la composición
def test_la_descripcion_en_espanol_lleva_el_minutaje_de_la_inglesa_y_sus_titulos(run):
    medido = compone_descripcion.compon(RUN_ID, [FICHA], traducidos=["es"])
    slides = _lee_slides(run)
    en, es = slides["description"], slides["description_es"]
    assert medido["compuesta"] and medido["traducidas"]["es"]["caracteres"] == len(es)
    # El minutaje: 00:00 (el primero siempre), 02:06 (lámina 4, 125,5 s) y 04:52 (lámina 8, 291,5 s), sacados de
    # `inicio_s`; sumando planos saldrían 02:00 y 04:40.
    assert _tiempos(es) == _tiempos(en) == ["00:00", "02:06", "04:52"]
    assert "Capítulos\n00:00 ¿Cómo gana dinero Costco?\n02:06 ¿Qué diferencia hay entre ingresos y beneficio?" in es
    assert "How Does Costco Make Money?" not in es and "Chapters" not in es
    assert "Costco vende mucho." in es and "<<" not in es and "<<" not in en


def test_la_bibliografia_en_espanol_lleva_sus_rotulos_y_las_mismas_citas(run):
    compone_descripcion.compon(RUN_ID, [FICHA], traducidos=["es"])
    slides = _lee_slides(run)
    en, es = slides["description"], slides["description_es"]
    assert "Fuentes\n\n— Por qué Costco apenas gana —" in es
    assert "Las fuentes citadas se han verificado una a una" in es
    assert "Sources" not in es and "Why Costco Barely Profits —" not in es
    # Las citas se copian byte a byte en los dos idiomas: no se traducen.
    assert f"  {CITA}" in es and f"  {CITA}" in en


def test_con_la_inglesa_ya_compuesta_solo_se_compone_la_espanola(run):
    """El run ya subido (episodio 1 de un canal de economía): la inglesa se queda tal cual y la española sale con
    su mismo minutaje."""
    compone_descripcion.compon(RUN_ID, [FICHA], traducidos=[])
    antes = _lee_slides(run)
    assert "<<CAPITULOS>>" in antes["description_es"], "un canal sin traducciones no toca description_es"
    medido = compone_descripcion.compon(RUN_ID, [FICHA], traducidos=["es"])
    despues = _lee_slides(run)
    assert medido["compuesta"] is False and list(medido["traducidas"]) == ["es"]
    assert despues["description"] == antes["description"]
    assert _tiempos(despues["description_es"]) == _tiempos(despues["description"])
    # Y la tercera vez no hay nada que hacer: es idempotente, como la inglesa.
    assert compone_descripcion.compon(RUN_ID, [FICHA], traducidos=["es"])["traducidas"] == {}


@pytest.mark.parametrize("inglesa_compuesta", [False, True])
def test_un_marcador_olvidado_en_la_espanola_para_sin_escribir_nada(run, inglesa_compuesta):
    """Sin `<<CAPITULOS>>` la española saldría sin índice y nadie lo vería. Con la inglesa sin componer o compuesta."""
    if inglesa_compuesta:
        compone_descripcion.compon(RUN_ID, [FICHA], traducidos=[])
    slides = _lee_slides(run)
    slides["description_es"] = "Costco vende mucho.\n\n<<BIBLIOGRAFIA>>"
    _escribe_slides(run, slides)
    with pytest.raises(ErrorDeMetadatos, match="los mismos"):
        compone_descripcion.compon(RUN_ID, [FICHA], traducidos=["es"])
    assert _lee_slides(run) == slides


def test_control_con_los_mismos_marcadores_compone(run):
    """Sin esto, la prueba de arriba no distingue «para por el marcador» de «siempre para»."""
    compone_descripcion.compon(RUN_ID, [FICHA], traducidos=[])
    assert compone_descripcion.compon(RUN_ID, [FICHA], traducidos=["es"])["traducidas"]["es"]["caracteres"] > 0


# ------------------------------------------------------------------------------------------ 3. la subida
@pytest.fixture
def subida(run, monkeypatch):
    """`stage_upload` sobre el run de prueba, con credenciales de mentira y espías en todo lo que gasta cuota."""
    import pipeline
    from lib import state as run_state

    estado = {
        "run_id": RUN_ID,
        "motor": run_state.MOTOR,
        "title": "T",
        "output_dir": str(run),
        "stages": {"assembly": {"output": str(run / "subir-al-canal" / "final.mp4")}, "thumbnail": {}},
    }
    llamadas: list = []
    monkeypatch.setattr(run_state, "load_run", lambda _id: copy.deepcopy(estado))
    monkeypatch.setattr(run_state, "update_stage", lambda *a, **k: llamadas.append(("estado", a)))
    monkeypatch.setattr(run_state, "update_run", lambda *a, **k: llamadas.append(("run", a)))
    for clave in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.setattr(config, clave, "de-mentira")
    # La subida por la API, encendida: desde OC1.8 las tres claves solas ya no la encienden.
    monkeypatch.setattr(config, "YOUTUBE_SUBIDA_API", "1")
    monkeypatch.setattr(config, "SUBTITLE_LANG", "en")
    monkeypatch.setattr(config, "NARRATION_LANG", "en")
    monkeypatch.setattr(youtube_client, "get_access_token", lambda: llamadas.append(("token",)) or "x")
    subido = {"video_id": "abc123", "studio_url": "https://studio", "pendiente_a_mano": []}
    monkeypatch.setattr(youtube_client, "upload_video", lambda **k: llamadas.append(("sube", k)) or dict(subido))

    def con_perfil(perfil: dict):
        monkeypatch.setattr(config, "CANAL_PERFIL", perfil)
        monkeypatch.setattr(subtitulos, "CANAL_PERFIL", perfil)
        return pipeline, llamadas

    return con_perfil


@pytest.mark.parametrize(
    "quita",
    [
        lambda s: s.pop("title_es"),
        lambda s: s.pop("description_es"),
        lambda s: s.update(title_es="   "),
        lambda s: s["capitulos"][2].pop("titulo_es"),
    ],
    ids=["sin-title_es", "sin-description_es", "title_es-vacio", "capitulo-sin-titulo_es"],
)
def test_la_subida_para_antes_de_gastar_cuota_si_falta_un_campo(subida, run, quita):
    pipeline, llamadas = subida(_perfil())
    slides = _slides()
    quita(slides)
    _escribe_slides(run, slides)
    with pytest.raises(ErrorDeMetadatos, match="no se ha gastado cuota"):
        pipeline.stage_upload(RUN_ID)
    assert llamadas == [], f"la subida hizo algo antes de parar: {llamadas}"
    assert _lee_slides(run) == slides, "la subida compuso algo antes de parar"


def test_control_con_los_campos_la_subida_sigue_y_el_espanol_no_viaja_a_youtube(subida, run):
    pipeline, llamadas = subida(_perfil())
    pipeline.stage_upload(RUN_ID)
    sube = [k for que, *k in llamadas if que == "sube"]
    assert len(sube) == 1
    enviado = sube[0][0]
    assert set(enviado) == {
        "file_path",
        "title",
        "description",
        "tags",
        "thumbnail_path",
        "srt_paths",
        "fecha_de_grabacion",
    }, "la subida manda algo nuevo a la API: la fila 285 no sube `localizations`"
    assert enviado["title"] == "Why Costco Barely Profits"
    assert "Costco vende mucho" not in enviado["description"] and "DECLARACIÓN DE IA" not in enviado["description"]
    html = (run / "subir-al-canal" / "LEEME.html").read_text(encoding="utf-8")
    assert "<h2>Título y descripción en español (SEO)</h2>" in html
    descripcion_es = re.search(r'<textarea id="d-es" rows="14" readonly>(.*?)</textarea>', html, re.S).group(1)
    assert "DECLARACIÓN DE IA — este vídeo se ha producido con IA generativa:" in descripcion_es
    assert "AI DISCLOSURE" not in descripcion_es
    assert _tiempos(descripcion_es) == _tiempos(enviado["description"]) == ["00:00", "02:06", "04:52"]


def test_un_canal_que_no_lo_declara_sube_y_escribe_el_leeme_de_siempre(subida, run):
    """Sin la clave, ni `title_es` ni `description_es` hacen falta y el LEEME no lleva la sección."""
    pipeline, llamadas = subida(_perfil(None))
    _escribe_slides(run, {k: v for k, v in _slides().items() if not k.endswith("_es")})
    pipeline.stage_upload(RUN_ID)
    assert len([1 for que, *_ in llamadas if que == "sube"]) == 1
    html = (run / "subir-al-canal" / "LEEME.html").read_text(encoding="utf-8")
    assert "SEO" not in html and 'id="d-es"' not in html and "<h2>A mano en Studio</h2>" not in html


@pytest.mark.parametrize("forzar", [False, True], ids=["normal", "forzada"])
def test_la_subida_se_niega_sin_la_marca_de_ia_del_video(subida, run, forzar):
    """OC1.5: un vídeo sin su registro de marca detectada no sube, ni con `--forzar-subida`, y no gasta cuota."""
    pipeline, llamadas = subida(_perfil())
    montaje = json.loads((run / provenance.ASSEMBLY_SUMMARY_FILENAME).read_text(encoding="utf-8"))
    del montaje["marca_ia"]
    (run / provenance.ASSEMBLY_SUMMARY_FILENAME).write_text(json.dumps(montaje), encoding="utf-8")
    with pytest.raises(marca_ia.ErrorDeMarca, match="final.mp4 no tiene su registro.*--stage render"):
        pipeline.stage_upload(RUN_ID, forzar=forzar)
    assert [que for que, *_ in llamadas if que in ("token", "sube")] == []


def test_la_subida_se_niega_con_una_miniatura_sin_marca(subida, run, monkeypatch, marca_falsa):
    """La miniatura que va con el vídeo también lleva la suya; con su registro, la subida sigue (control)."""
    from lib import state as run_state

    pipeline, llamadas = subida(_perfil())
    miniatura = run / "subir-al-canal" / "thumbnail.png"
    miniatura.write_bytes(b"png")
    estado = copy.deepcopy(run_state.load_run(RUN_ID))
    estado["stages"]["thumbnail"] = {"output": str(miniatura)}
    monkeypatch.setattr(run_state, "load_run", lambda _id: copy.deepcopy(estado))
    with pytest.raises(marca_ia.ErrorDeMarca, match="thumbnail.png no tiene su registro.*--stage thumbnail"):
        pipeline.stage_upload(RUN_ID)
    assert [que for que, *_ in llamadas if que in ("token", "sube")] == []
    (run / "miniatura.json").write_text(json.dumps({"marca_ia": marca_falsa.registro(miniatura)}), encoding="utf-8")
    # Y su procedencia, que la subida también exige (decisión 5).
    registro = {"file": str(miniatura), "modelo": "Qwen-Image (prueba)", "licencia": "Apache-2.0", "url": "https://x"}
    (run / provenance.IMAGE_RECORDS_FILENAME).write_text(json.dumps([registro]), encoding="utf-8")
    pipeline.stage_upload(RUN_ID)
    assert len([1 for que, *_ in llamadas if que == "sube"]) == 1


# ------------------------------------------------------------------------------------------ 4. el LEEME
def test_el_leeme_ensena_el_titulo_y_la_descripcion_en_espanol_y_donde_se_pegan(run):
    traducidas = {"es": {"titulo": 'Por qué <b>Costco</b> & "más"', "descripcion": "Ingresos < beneficio\n00:00 x"}}
    html = publicacion.guia_de_subida(run, titulo="T", descripcion="D", traducidas=traducidas).read_text(
        encoding="utf-8"
    )
    assert "<h2>Título y descripción en español (SEO)</h2>" in html
    assert "Subtítulos → Añadir idioma → Español" in html
    assert "<button onclick=\"c('t-es')\">copiar el título en español</button>" in html
    assert "<button onclick=\"c('d-es')\">copiar la descripción en español</button>" in html
    assert "<li>título y descripción en español: están más abajo, para copiarlos</li>" in html
    # Los textos son datos (convención A-9): escapados, nunca HTML.
    assert "<b>Costco</b>" not in html and "Por qué &lt;b&gt;Costco&lt;/b&gt; &amp; &quot;más&quot;" in html
    assert "Ingresos &lt; beneficio" in html


def test_control_sin_traducidas_el_leeme_es_el_de_siempre(run):
    """Sin la versión traducida, la página es la misma byte a byte, pasen `None`, `{}` o nada."""
    paginas = []
    for extra in ({}, {"traducidas": None}, {"traducidas": {}}):
        ruta = publicacion.guia_de_subida(run, titulo="T", descripcion="D", **extra)
        paginas.append(ruta.read_bytes())
    assert paginas[0] == paginas[1] == paginas[2]
    assert b"SEO" not in paginas[0]


# ------------------------------------------------------------------------------------------ 5. rehacer el LEEME
@pytest.fixture
def subido(run, monkeypatch):
    """El run ya subido antes de la fila 285: su LEEME sin la sección y su estado con el `video_id`."""
    import pipeline
    from lib import state as run_state

    perfil = _perfil()
    monkeypatch.setattr(config, "CANAL_PERFIL", perfil)
    monkeypatch.setattr(config, "NARRATION_LANG", "en")
    compone_descripcion.compon(RUN_ID, [FICHA], traducidos=[])
    provenance.sync(run, run_id=RUN_ID, etapa="subida de prueba")  # el assets.json que deja la subida
    descripcion, _ = publicacion.descripcion_conforme(
        base=_lee_slides(run)["description"], run_dir=run, perfil=perfil, idioma="en"
    )
    publicacion.guia_de_subida(run, titulo="Why Costco Barely Profits", descripcion=descripcion, video_id="abc123")
    salida = {"video_id": "abc123", "title": "Why Costco Barely Profits", "pendiente_a_mano": []}
    estado = {
        "run_id": RUN_ID,
        "motor": run_state.MOTOR,
        "title": "T",
        "output_dir": str(run),
        "stages": {"upload": {"status": "complete", "output": json.dumps(salida)}},
    }
    monkeypatch.setattr(run_state, "load_run", lambda _id: copy.deepcopy(estado))

    def prohibido(*_a, **_k):  # pragma: no cover - si se llama, la prueba falla
        raise AssertionError("rehacer el LEEME no puede tocar el estado ni la API")

    for modulo, nombre in (
        (run_state, "update_stage"),
        (run_state, "update_run"),
        (youtube_client, "get_access_token"),
        (youtube_client, "upload_video"),
        (youtube_client, "pon_miniatura"),
    ):
        monkeypatch.setattr(modulo, nombre, prohibido)
    return pipeline, descripcion, estado


def test_rehacer_el_leeme_anade_el_espanol_sin_api_ni_estado(subido, run, capsys):
    pipeline, descripcion, _ = subido
    assert pipeline.rehace_guia(RUN_ID) is True
    html = (run / "subir-al-canal" / "LEEME.html").read_text(encoding="utf-8")
    assert "<h2>Título y descripción en español (SEO)</h2>" in html and "abc123" in html
    assert publicacion.descripcion_del_leeme(run) == descripcion, "la descripción inglesa no es la que se subió"
    descripcion_es = re.search(r'<textarea id="d-es" rows="14" readonly>(.*?)</textarea>', html, re.S).group(1)
    assert _tiempos(descripcion_es) == _tiempos(descripcion) and "Capítulos" in descripcion_es
    assert "[AVISO] la descripción original" not in capsys.readouterr().out


def test_control_rehacer_avisa_si_la_inglesa_ya_no_es_la_que_se_subio(subido, run, capsys):
    """Si el run cambió después de subir, el LEEME rehecho enseñaría otra descripción: se dice."""
    pipeline, _, _ = subido
    leeme = run / "subir-al-canal" / "LEEME.html"
    leeme.write_text(leeme.read_text(encoding="utf-8").replace("Costco sells a lot.", "Otra cosa."), encoding="utf-8")
    assert pipeline.rehace_guia(RUN_ID) is True
    assert "[AVISO] la descripción original que sale ahora NO es la del LEEME anterior" in capsys.readouterr().out


def test_rehacer_un_run_sin_subir_no_escribe_nada(subido, run, monkeypatch):
    pipeline, _, estado = subido
    from lib import state as run_state

    sin_subir = copy.deepcopy(estado)
    sin_subir["stages"] = {}
    monkeypatch.setattr(run_state, "load_run", lambda _id: copy.deepcopy(sin_subir))
    antes = (run / "subir-al-canal" / "LEEME.html").read_bytes()
    assert pipeline.rehace_guia(RUN_ID) is False
    assert (run / "subir-al-canal" / "LEEME.html").read_bytes() == antes


def test_rehacer_para_si_falta_un_campo_y_no_toca_el_leeme(subido, run):
    pipeline, _, _ = subido
    slides = _lee_slides(run)
    slides.pop("title_es")
    _escribe_slides(run, slides)
    antes = (run / "subir-al-canal" / "LEEME.html").read_bytes()
    with pytest.raises(ErrorDeMetadatos, match="title_es"):
        pipeline.rehace_guia(RUN_ID)
    assert (run / "subir-al-canal" / "LEEME.html").read_bytes() == antes


def test_el_cli_acepta_rehace_leeme():
    """La orden existe en el CLI y no pasa por `_produce`, que fabrica el vídeo."""
    texto = (RAIZ / "pipeline.py").read_text(encoding="utf-8")
    assert '"--rehace-leeme"' in texto and "rehace_guia(args.run_id)" in texto
