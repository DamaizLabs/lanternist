"""El `.srt` traducido y la declaración del formato «pizarra» (F7.11, filas 257, 265 y 268).

Correr: .venv\\Scripts\\python -m pytest -q tests/test_traduccion_srt.py

Lo que fijan estas pruebas, cada una con su control negativo:

1. **La declaración del formato «pizarra»** sale del `assets.json` del run, que dice el formato del vídeo. Un run sin
   `formato` declara lo de antes, y los 31 runs de los dos primeros canales que había en git declaraban BYTE A BYTE
   lo mismo que antes de F7.11 (`tests/datos/declaraciones_antes_de_F7.11.json`, sacada con el código de `main`).
2. **Cada canal declara sus traducciones** (`subtitulos.traducciones`), sin defecto.
3. **`saca` y `escribe`**: los mismos cues y los mismos tiempos; un cue de menos o de más, un número cambiado, un tiempo
   tocado, un texto vacío, una línea larga o un `.srt` de origen cambiado paran `escribe` sin escribir nada.
4. **La subida para antes de gastar cuota** si falta una traducción o si el `.srt` de origen cambió después, y lista
   todos los `.srt` que el usuario adjunta a mano.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from lib import config, provenance, publicacion, subtitulos, traduccion, youtube_client
from lib.escena import ajustes

RAIZ = Path(__file__).resolve().parent.parent
PERFIL_PRUEBA = RAIZ / "tests" / "escena" / "canal-prueba" / "perfil.json"
RUN_ID = "2026-10-05_000000_prueba-f711"

LINEA_PIZARRA_EN = (
    "• Chalkboard drawings: AI-generated illustrations, revealed piece by piece. The handwriting, numbers and charts "
    "are drawn by code, not by AI."
)
LINEA_PIZARRA_ES = (
    "• Dibujos de pizarra: ilustraciones generadas con IA que aparecen por partes. La letra, las cifras y las gráficas "
    "las dibuja el código, no la IA."
)
LINEA_TRADUCCION_EN = "Spanish subtitles: translated from the English script with AI."

SRT_EN = (
    "1\n00:00:01,000 --> 00:00:03,520\nHello, and welcome to Coins and Pencils...\n\n"
    "2\n00:00:03,520 --> 00:00:06,180\nwhere we draw how money really works.\n\n"
    "3\n00:00:06,220 --> 00:00:07,960\nToday's question...\n\n"
    "4\n00:00:07,960 --> 00:00:09,660\nThe only extra ingredient was time.\n"
)
TEXTOS_ES = [
    "Hola, y bienvenidos a Coins and Pencils...",
    "donde dibujamos cómo funciona el dinero.",
    "La pregunta de hoy...",
    "El único ingrediente extra fue el tiempo.",
]


def _perfil(traducciones=("es",), *, max_caracteres: int = 42) -> dict:
    perfil = json.loads(PERFIL_PRUEBA.read_text(encoding="utf-8"))
    perfil["escena"]["cues"]["max_caracteres"] = max_caracteres
    perfil["subtitulos"] = {
        "activos": True,
        "srt": True,
        "fuente": "Verdana",
        "cuerpo": 60,
        "max_palabras_por_linea": 10,
        "margen_inferior_px": 90,
        "margen_lateral_px": 200,
        "traducciones": list(traducciones),
        "personajes": {},
    }
    return perfil


@pytest.fixture
def run(tmp_path, monkeypatch) -> Path:
    """Un run con el `.srt` en inglés que deja `alinea` y su registro de procedencia. La copia de git, a tmp."""
    monkeypatch.setattr(provenance, "ASSETS_MIRROR_DIR", tmp_path / "copia-versionada")
    run_dir = tmp_path / "videos" / RUN_ID
    srt = config.dir_subir_al_canal(run_dir, crear=True) / "subtitulos.en.srt"
    srt.write_text(SRT_EN, encoding="utf-8")
    registro = {
        "modelo_alineacion": "openai/whisper-small",
        "licencia": subtitulos.LICENCIA_ALINEADOR,
        "origen": "alineación en local",
        "idioma": "en",
        "srt": str(srt),
    }
    (run_dir / provenance.SUBTITLE_RECORDS_FILENAME).write_text(json.dumps([registro]), encoding="utf-8")
    return run_dir


def _traduce(run_dir: Path, textos=TEXTOS_ES, *, muta=None) -> Path:
    """Lo que hace Claude en la sesión: lee el JSON de `saca`, traduce cada texto y lo guarda con otro nombre."""
    sacado = json.loads(traduccion.saca(run_dir, _perfil(), origen="en").read_text(encoding="utf-8"))
    for cue, texto in zip(sacado["cues"], textos):
        cue["texto"] = texto
    if muta:
        muta(sacado)
    destino = run_dir / "subtitulos" / "cues.es.json"
    destino.write_text(json.dumps(sacado, ensure_ascii=False), encoding="utf-8")
    return destino


def _escribe(run_dir: Path, ruta: Path, *, perfil=None, idioma="es") -> dict:
    return traduccion.escribe(
        run_dir,
        perfil or _perfil(),
        run_id=RUN_ID,
        idioma=idioma,
        origen="en",
        idioma_de_la_declaracion="en",
        traduccion=ruta,
    )


# ------------------------------------------------------------------------------------------ 1. el formato del vídeo
@pytest.mark.parametrize(
    ("escena", "formato"),
    [({"laminas": {}}, "laminas"), ({}, "personajes"), ({"pizarra": {}}, "pizarra")],
)
def test_el_formato_de_cada_canal_sale_de_su_perfil(escena, formato):
    """Los tres formatos del catálogo, cada uno con la forma de bloque `escena` que lo declara."""
    assert ajustes.formato({"escena": escena}) == formato


def test_el_canal_de_ejemplo_produce_en_laminas():
    perfil = json.loads((RAIZ / "canales" / "example" / "perfil.json").read_text(encoding="utf-8"))
    assert ajustes.formato(perfil) == "laminas"


def test_control_un_perfil_con_dos_formatos_para():
    perfil = {"escena": {"laminas": {}, "pizarra": {}}}
    with pytest.raises(ajustes.ErrorDeAjustes, match="dos formatos"):
        ajustes.formato(perfil)


def test_el_registro_del_video_lleva_el_formato_solo_si_el_montaje_lo_dice(tmp_path):
    resumen = {"motor": "escena", "salida": "subir-al-canal/final.mp4", "actores": 0}
    viejo = provenance._video_entry(tmp_path, resumen, [])
    nuevo = provenance._video_entry(tmp_path, {**resumen, "formato": "pizarra"}, [])
    assert "formato" not in viejo["detalle"], "un run anterior a F7.11 se queda como estaba al volver a sincronizarlo"
    assert nuevo["detalle"]["formato"] == "pizarra"


def _assets(carpeta: Path, *, formato=None, actores=0, subtitulos_extra=()) -> Path:
    video = {"id": "subir-al-canal/final.mp4", "tipo": "video", "modelo": "ninguno: render", "detalle": {}}
    video["detalle"].update({"motor": "escena", "actores": actores})
    if formato:
        video["detalle"]["formato"] = formato
    datos = {
        "assets": [
            {"id": "audio/slide-01.wav", "tipo": "audio", "modelo": "Orpheus TTS 3B"},
            {"id": "activos/img/pizarra_01.jpg", "tipo": "imagen", "modelo": "Qwen-Image"},
            {"id": "subir-al-canal/subtitulos.en.srt", "tipo": "subtitulos", "modelo": "openai/whisper-small"},
            *subtitulos_extra,
            video,
        ]
    }
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "assets.json").write_text(json.dumps(datos), encoding="utf-8")
    return carpeta


@pytest.mark.parametrize(("idioma", "linea"), [("en", LINEA_PIZARRA_EN), ("es", LINEA_PIZARRA_ES)])
def test_un_video_en_pizarra_declara_la_linea_firmada(tmp_path, idioma, linea):
    texto, avisos = publicacion.declaracion_de_ia(_assets(tmp_path, formato="pizarra"), idioma)
    assert linea in texto.split("\n") and avisos == []
    assert publicacion.PIEZAS[idioma]["imagen_camara"] not in texto


def test_control_el_mismo_video_sin_formato_declara_lo_de_antes(tmp_path):
    texto, _ = publicacion.declaracion_de_ia(_assets(tmp_path), "en")
    assert "Still illustrations: AI-generated, shown with camera movement." in texto and "Chalkboard" not in texto


def test_control_una_pizarra_con_figuras_que_se_mueven_no_se_queda_corta(tmp_path):
    texto, _ = publicacion.declaracion_de_ia(_assets(tmp_path, formato="pizarra", actores=2), "en")
    assert "Animated scenes" in texto and "Chalkboard" not in texto


def test_los_otros_formatos_siguen_eligiendo_por_las_figuras(tmp_path):
    texto, avisos = publicacion.declaracion_de_ia(_assets(tmp_path, formato="laminas"), "en")
    assert "shown with camera movement" in texto and avisos == []
    texto, _ = publicacion.declaracion_de_ia(_assets(tmp_path / "b", formato="personajes", actores=3), "en")
    assert "Animated scenes" in texto


def test_un_formato_que_el_catalogo_no_conoce_se_avisa(tmp_path):
    _, avisos = publicacion.declaracion_de_ia(_assets(tmp_path, formato="mapas"), "en")
    assert any("mapas" in a for a in avisos)


def test_cada_formato_con_linea_propia_es_del_catalogo():
    assert set(publicacion.PIEZA_DEL_FORMATO) <= set(ajustes.FORMATOS)
    for pieza in publicacion.PIEZA_DEL_FORMATO.values():
        assert all(pieza in publicacion.PIEZAS[i] for i in publicacion.PIEZAS)


# ------------------------------------------------------------------------------------------ 2. el perfil de cada canal
@pytest.mark.parametrize("ruta", sorted((RAIZ / "canales").glob("*/perfil.json")), ids=lambda p: p.parent.name)
def test_cada_canal_declara_sus_traducciones(ruta):
    """Cada canal del repositorio declara la clave y es válida: `[]` es una respuesta (el de ejemplo no traduce)."""
    perfil = json.loads(ruta.read_text(encoding="utf-8"))
    assert isinstance(subtitulos.traducciones(perfil, origen=perfil["idioma"]["subtitulos"]), list)


def test_control_un_perfil_sin_la_clave_para_y_dice_que_escribir():
    perfil = _perfil()
    del perfil["subtitulos"]["traducciones"]
    with pytest.raises(subtitulos.SubtitulosError, match=r"traducciones.*\[\]"):
        subtitulos.traducciones(perfil, origen="en")


@pytest.mark.parametrize(
    ("valor", "dice"),
    [("es", "lista"), (["ES"], "minúscula"), (["spa"], "dos"), (["es", "es"], "repite"), (["en"], "origen")],
)
def test_control_una_lista_de_traducciones_mal_escrita_para(valor, dice):
    perfil = _perfil()
    perfil["subtitulos"]["traducciones"] = valor
    with pytest.raises(subtitulos.SubtitulosError, match=dice):
        subtitulos.traducciones(perfil, origen="en")


def test_un_canal_sin_srt_no_traduce_nada_y_no_puede_declararlo():
    assert subtitulos.traducciones({"subtitulos": {"activos": False}}, origen="en") == []
    with pytest.raises(subtitulos.SubtitulosError, match="no lleva .srt"):
        subtitulos.traducciones({"subtitulos": {"activos": False, "traducciones": ["es"]}}, origen="en")


# ------------------------------------------------------------------------------------------ 3. saca y escribe
def test_saca_deja_los_cues_con_numero_tiempos_texto_y_la_huella_del_srt(run):
    ruta = traduccion.saca(run, _perfil(), origen="en")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert ruta == run / "subtitulos" / "cues.en.json"
    assert datos["cues"][0] == {
        "n": 1,
        "inicio": "00:00:01,000",
        "fin": "00:00:03,520",
        "texto": "Hello, and welcome to Coins and Pencils...",
    }
    assert [c["n"] for c in datos["cues"]] == [1, 2, 3, 4]
    srt = run / "subir-al-canal" / "subtitulos.en.srt"
    assert datos["origen"] == {
        "srt": "subir-al-canal/subtitulos.en.srt",
        "idioma": "en",
        "sha256": hashlib.sha256(srt.read_bytes()).hexdigest(),
    }
    assert datos["max_caracteres_por_linea"] == 42 and datos["max_lineas"] == 2


def test_escribe_deja_el_srt_traducido_con_los_mismos_tiempos_y_su_procedencia(run):
    srt_en = run / "subir-al-canal" / "subtitulos.en.srt"
    antes = srt_en.read_bytes()
    hecho = _escribe(run, _traduce(run))
    es = run / "subir-al-canal" / "subtitulos.es.srt"
    assert hecho["srt"] == es and hecho["cues"] == 4
    assert srt_en.read_bytes() == antes, "el .srt de origen no se toca"
    en_cues, es_cues = subtitulos.lee_srt(srt_en), subtitulos.lee_srt(es)
    assert [(c["n"], c["inicio"], c["fin"]) for c in es_cues] == [(c["n"], c["inicio"], c["fin"]) for c in en_cues]
    assert [c["texto"] for c in es_cues] == TEXTOS_ES
    subtitulos.valida_srt(es)
    # La procedencia: un asset de tipo `subtitulos` que dice quién tradujo, el idioma, de qué .srt sale y su huella.
    assert hecho["conteo"]["cuadra"], hecho["conteo"]
    entrada = next(a for a in provenance.read_ledger(run)["assets"] if a["id"] == "subir-al-canal/subtitulos.es.srt")
    assert entrada["tipo"] == "subtitulos" and entrada["modelo"] == traduccion.TRADUCTOR
    assert entrada["detalle"]["idioma"] == "es" and entrada["detalle"]["idioma_origen"] == "en"
    assert entrada["detalle"]["traducido_de"] == "subir-al-canal/subtitulos.en.srt"
    assert entrada["detalle"]["sha256_origen"] == hashlib.sha256(antes).hexdigest()
    assert (provenance.ASSETS_MIRROR_DIR / f"{RUN_ID}.json").is_file(), "la copia de git se pone al día"


def test_una_linea_larga_puede_partirse_en_dos(run):
    textos = [*TEXTOS_ES[:1], "donde dibujamos cómo funciona\nde verdad el dinero, paso a paso.", *TEXTOS_ES[2:]]
    _escribe(run, _traduce(run, textos))
    es = subtitulos.lee_srt(run / "subir-al-canal" / "subtitulos.es.srt")
    assert es[1]["texto"] == "donde dibujamos cómo funciona\nde verdad el dinero, paso a paso."


def _quita_uno(d):
    d["cues"].pop()


def _anade_uno(d):
    d["cues"].append({"n": 5, "inicio": "00:00:09,660", "fin": "00:00:10,000", "texto": "Sobra."})


def _cambia_el_orden(d):
    d["cues"][1], d["cues"][2] = d["cues"][2], d["cues"][1]


def _toca_un_tiempo(d):
    d["cues"][2]["fin"] = "00:00:08,000"


def _vacia_un_texto(d):
    d["cues"][3]["texto"] = "   "


def _linea_larga(d):
    d["cues"][0]["texto"] = "Hola, y muy bienvenidos todos a Coins and Pencils, el canal..."


def _tres_lineas(d):
    d["cues"][0]["texto"] = "Hola,\ny bienvenidos\na Coins and Pencils..."


@pytest.mark.parametrize(
    ("muta", "dice"),
    [
        (_quita_uno, "tiene 3 cues"),
        (_anade_uno, "tiene 5 cues"),
        (_cambia_el_orden, "lleva el número 3"),
        (_toca_un_tiempo, "los tiempos no se tocan"),
        (_vacia_un_texto, "no tiene texto"),
        (_linea_larga, "caben 42"),
        (_tres_lineas, "3 líneas"),
    ],
)
def test_control_escribe_para_y_no_escribe_nada(run, muta, dice):
    ruta = _traduce(run, muta=muta)
    with pytest.raises(traduccion.ErrorDeTraduccion, match=dice):
        _escribe(run, ruta)
    assert not (run / "subir-al-canal" / "subtitulos.es.srt").exists()
    assert not (run / provenance.TRANSLATION_RECORDS_FILENAME).exists()


def test_control_una_traduccion_que_no_traduce_nada_para(run):
    ingles = [c["texto"] for c in subtitulos.lee_srt(run / "subir-al-canal" / "subtitulos.en.srt")]
    with pytest.raises(traduccion.ErrorDeTraduccion, match="no está traducido"):
        _escribe(run, _traduce(run, ingles))


def test_control_un_idioma_que_el_canal_no_declara_para(run):
    with pytest.raises(traduccion.ErrorDeTraduccion, match="no traduce su .srt a «fr»"):
        _escribe(run, _traduce(run), idioma="fr")


def test_control_un_srt_de_origen_cambiado_despues_de_sacarlo_para(run):
    ruta = _traduce(run)
    srt = run / "subir-al-canal" / "subtitulos.en.srt"
    srt.write_text(SRT_EN.replace("Today's question", "The question"), encoding="utf-8")
    with pytest.raises(traduccion.ErrorDeTraduccion, match="ha cambiado desde que se sacaron"):
        _escribe(run, ruta)
    assert not (run / "subir-al-canal" / "subtitulos.es.srt").exists()


def test_el_script_hace_los_dos_pasos(run, monkeypatch, capsys):
    """La orden que lleva `produce-semana`: `saca` y `escribe` sobre el canal activo."""
    import importlib

    traduce_srt = importlib.import_module("scripts.traduce_srt")
    monkeypatch.setattr(config, "CANAL_ERROR", None)
    monkeypatch.setattr(config, "CANAL_VIDEOS_DIR", run.parent)
    monkeypatch.setattr(config, "CANAL_PERFIL", _perfil())
    monkeypatch.setattr(subtitulos, "CANAL_PERFIL", _perfil())
    monkeypatch.setattr(config, "SUBTITLE_LANG", "en")
    monkeypatch.setattr(config, "NARRATION_LANG", "en")
    assert traduce_srt.main(["saca", "--run-id", RUN_ID]) == 0
    ruta = _traduce(run)
    assert traduce_srt.main(["escribe", "--run-id", RUN_ID, "--idioma", "es", "--traduccion", str(ruta)]) == 0
    assert (run / "subir-al-canal" / "subtitulos.es.srt").is_file()
    with pytest.raises(SystemExit, match="no traduce su .srt a «fr»"):
        traduce_srt.main(["escribe", "--run-id", RUN_ID, "--idioma", "fr", "--traduccion", str(ruta)])


# ------------------------------------------------------------------------------------------ 4. la subida y su guía
def test_la_subida_lista_los_dos_srt_cuando_estan_al_dia(run):
    _escribe(run, _traduce(run))
    srts = traduccion.exige_al_dia(run, _perfil(), origen="en")
    assert [p.name for p in srts] == ["subtitulos.en.srt", "subtitulos.es.srt"]


def test_control_falta_la_traduccion_declarada(run):
    with pytest.raises(traduccion.ErrorDeTraduccion, match="falta la traducción a «es»"):
        traduccion.exige_al_dia(run, _perfil(), origen="en")


def test_control_el_srt_de_origen_cambio_despues_de_traducirlo(run):
    _escribe(run, _traduce(run))
    srt = run / "subir-al-canal" / "subtitulos.en.srt"
    srt.write_text(SRT_EN.replace("Today's question", "The question"), encoding="utf-8")
    with pytest.raises(traduccion.ErrorDeTraduccion, match="ha cambiado desde que se tradujo"):
        traduccion.exige_al_dia(run, _perfil(), origen="en")


def test_control_la_traduccion_se_toco_despues_de_escribirla(run):
    _escribe(run, _traduce(run))
    es = run / "subir-al-canal" / "subtitulos.es.srt"
    es.write_text(es.read_text(encoding="utf-8").replace("Hola", "Buenas"), encoding="utf-8")
    with pytest.raises(traduccion.ErrorDeTraduccion, match="ha cambiado desde que se escribió"):
        traduccion.exige_al_dia(run, _perfil(), origen="en")


def test_un_canal_sin_traducciones_sube_como_siempre_y_no_admite_otras(run):
    assert [p.name for p in traduccion.exige_al_dia(run, _perfil(()), origen="en")] == ["subtitulos.en.srt"]
    _escribe(run, _traduce(run))
    with pytest.raises(traduccion.ErrorDeTraduccion, match="no declara"):
        traduccion.exige_al_dia(run, _perfil(()), origen="en")


def test_control_un_perfil_sin_la_clave_para_la_subida(run):
    perfil = _perfil()
    del perfil["subtitulos"]["traducciones"]
    with pytest.raises(subtitulos.SubtitulosError, match="traducciones"):
        traduccion.exige_al_dia(run, perfil, origen="en")


@pytest.fixture
def subida_espiada(run, monkeypatch, tmp_path):
    """`stage_upload` sobre el run de prueba, con credenciales de mentira y espías en todo lo que gasta cuota."""
    import pipeline
    from lib import state as run_state
    from scripts import compone_descripcion

    (config.dir_subir_al_canal(run) / "final.mp4").write_bytes(b"video")
    (run / "slides.json").write_text(json.dumps({"title": "T", "slides": []}), encoding="utf-8")
    estado = {
        "run_id": RUN_ID,
        "motor": run_state.MOTOR,
        "title": "T",
        "output_dir": str(run),
        "stages": {"assembly": {"output": str(run / "subir-al-canal" / "final.mp4")}, "thumbnail": {}},
    }
    llamadas = []
    monkeypatch.setattr(run_state, "load_run", lambda _id: copy.deepcopy(estado))
    monkeypatch.setattr(run_state, "update_stage", lambda *a, **k: llamadas.append(("estado", a)))
    for clave in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.setattr(config, clave, "de-mentira")
    # La subida por la API, encendida: desde OC1.8 las tres claves solas ya no la encienden.
    monkeypatch.setattr(config, "YOUTUBE_SUBIDA_API", "1")
    monkeypatch.setattr(config, "CANAL_PERFIL", _perfil())
    monkeypatch.setattr(subtitulos, "CANAL_PERFIL", _perfil())
    monkeypatch.setattr(config, "SUBTITLE_LANG", "en")
    monkeypatch.setattr(run_state, "update_run", lambda *a, **k: llamadas.append(("run", a)))
    monkeypatch.setattr(
        compone_descripcion, "compon", lambda *a, **k: llamadas.append(("compon", a)) or {"compuesta": False}
    )
    monkeypatch.setattr(youtube_client, "get_access_token", lambda: llamadas.append(("token",)) or "x")
    subido = {"video_id": "abc", "studio_url": "https://studio", "pendiente_a_mano": []}
    monkeypatch.setattr(youtube_client, "upload_video", lambda **k: llamadas.append(("sube", k)) or dict(subido))
    return pipeline, llamadas


def test_la_subida_para_antes_de_gastar_cuota_si_falta_la_traduccion(subida_espiada):
    pipeline, llamadas = subida_espiada
    with pytest.raises(traduccion.ErrorDeTraduccion, match="no se ha gastado cuota"):
        pipeline.stage_upload(RUN_ID)
    assert llamadas == [], f"la subida hizo algo antes de parar: {llamadas}"


def test_control_con_la_traduccion_al_dia_la_subida_sigue_y_pasa_los_dos_srt(subida_espiada, run, marca_falsa):
    """Sin esto, la prueba de arriba no distingue «para por la traducción» de «el arnés de la prueba no deja subir»."""
    pipeline, llamadas = subida_espiada
    _escribe(run, _traduce(run))
    montaje = {"motor": "escena", "salida": "subir-al-canal/final.mp4", "actores": 0, "formato": "pizarra"}
    # El vídeo lleva su marca de IA (OC1.5): sin ella la subida se niega antes de gastar cuota.
    montaje["marca_ia"] = marca_falsa.registro(config.dir_subir_al_canal(run) / "final.mp4")
    (run / provenance.ASSEMBLY_SUMMARY_FILENAME).write_text(json.dumps(montaje), encoding="utf-8")
    pipeline.stage_upload(RUN_ID)
    sube = [k for que, *k in llamadas if que == "sube"]
    assert len(sube) == 1
    assert [Path(s).name for s in sube[0][0]["srt_paths"]] == ["subtitulos.en.srt", "subtitulos.es.srt"]
    assert LINEA_TRADUCCION_EN in sube[0][0]["description"]


def test_la_guia_lista_todos_los_srt_y_dice_cual_es_traduccion(run):
    _escribe(run, _traduce(run))
    html = publicacion.guia_de_subida(run, titulo="T", descripcion="D").read_text(encoding="utf-8")
    assert "subtitulos.en.srt" in html and "subtitulos.es.srt" in html
    assert "los subtítulos en inglés" in html and "los subtítulos en español" in html
    assert "traducción con IA de <code>subtitulos.en.srt</code>" in html


def test_el_resultado_de_la_subida_pide_adjuntar_todos_los_srt(run, monkeypatch, tmp_path):
    """`upload_video` sin red: lo que devuelve en `pendiente_a_mano` es lo que el LEEME lista para Studio."""
    _escribe(run, _traduce(run))

    class _Respuesta:
        def __init__(self, cuerpo=None):
            self.headers, self._cuerpo, self.text = {"Location": "https://subida"}, cuerpo or {}, ""

        def raise_for_status(self):
            return None

        def json(self):
            return self._cuerpo

    monkeypatch.setattr(youtube_client, "get_access_token", lambda: "x")
    monkeypatch.setattr(youtube_client.requests, "post", lambda *a, **k: _Respuesta())
    monkeypatch.setattr(youtube_client.requests, "put", lambda *a, **k: _Respuesta({"id": "abc"}))
    monkeypatch.setattr(youtube_client, "_verifica_lo_subido", lambda *a, **k: {"verificado": True})
    video = tmp_path / "final.mp4"
    video.write_bytes(b"v")
    srts = traduccion.exige_al_dia(run, _perfil(), origen="en")
    hecho = youtube_client.upload_video(
        file_path=str(video), title="T", description="AI DISCLOSURE: x", srt_paths=[str(s) for s in srts]
    )
    pendientes = [p["archivo"] for p in hecho["pendiente_a_mano"]]
    assert [Path(p).name for p in pendientes] == ["subtitulos.en.srt", "subtitulos.es.srt"]


# ------------------------------------------------------------------------------------------ la declaración traducida
def test_la_declaracion_dice_que_los_subtitulos_en_espanol_son_una_traduccion(run):
    _escribe(run, _traduce(run))
    texto, avisos = publicacion.declaracion_de_ia(run, "en")
    lineas = texto.split("\n")
    assert lineas[-2:] == [publicacion.NOTA_SUBTITULOS["en"], LINEA_TRADUCCION_EN] and avisos == []
    texto_es, _ = publicacion.declaracion_de_ia(run, "es")
    assert texto_es.split("\n")[-1] == "Subtítulos en español: traducidos con IA a partir del guion en inglés."


def test_control_sin_srt_traducido_no_hay_linea_de_traduccion(run):
    provenance.sync(run, verbose=False)
    texto, _ = publicacion.declaracion_de_ia(run, "en")
    assert "translated" not in texto and texto.split("\n")[-1] == publicacion.NOTA_SUBTITULOS["en"]


def test_el_nombre_del_idioma_es_el_de_verdad(tmp_path):
    frances = {
        "id": "subir-al-canal/subtitulos.fr.srt",
        "tipo": "subtitulos",
        "modelo": traduccion.TRADUCTOR,
        "detalle": {"idioma": "fr", "idioma_origen": "en", "traducido_de": "subir-al-canal/subtitulos.en.srt"},
    }
    texto, _ = publicacion.declaracion_de_ia(_assets(tmp_path, subtitulos_extra=[frances]), "en")
    assert "French subtitles: translated from the English script with AI." in texto and "Spanish" not in texto


def test_control_un_idioma_que_la_declaracion_no_sabe_nombrar_para(tmp_path):
    raro = {
        "id": "subir-al-canal/subtitulos.xx.srt",
        "tipo": "subtitulos",
        "modelo": traduccion.TRADUCTOR,
        "detalle": {"idioma": "xx", "idioma_origen": "en", "traducido_de": "subir-al-canal/subtitulos.en.srt"},
    }
    with pytest.raises(ValueError, match="no sabe nombrar el idioma 'xx'"):
        publicacion.declaracion_de_ia(_assets(tmp_path, subtitulos_extra=[raro]), "en")
