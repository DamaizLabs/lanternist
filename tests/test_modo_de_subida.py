"""La subida, apagada por defecto y encendida con `YOUTUBE_SUBIDA_API=1` (OC1.8, fila 315).

Correr: .venv\\Scripts\\python -m pytest -q tests/test_modo_de_subida.py

Hasta OC1.8 la subida se encendía sola al estar las tres claves de OAuth, y sin ellas se saltaba antes de preparar
nada: la página `LEEME.html` salía con la descripción en bruto del guion, sin capítulos ni declaración de IA, que es
justo la que se pega a mano en Studio. Lo que fijan estas pruebas, sin red (la llamada a YouTube y el token son
dobles que apuntan cada llamada):

1. **A mano, lo de serie**: ni token ni red, la etapa queda `skipped` con su motivo y el LEEME lleva la descripción
   compuesta, con la declaración de IA, y los pasos de Studio. Control negativo: con las tres claves puestas, tampoco.
2. **Por la API sin el OAuth completo**: se niega y dice qué variable falta y dónde se explica, sin preparar nada.
3. **Un valor que no se entiende** para el run.
4. **Por la API con el OAuth**: sube, como antes, un borrador privado con la declaración (control de los dos de arriba).
5. **`run_all` a mano** no pisa el LEEME con la descripción en bruto; con `--sin-subida` sigue como estaba.
6. `--check`, `--canales` y `comprueba_canal.py` dicen el modo y solo piden el token con la API.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lib import config, provenance, publicacion, subtitulos, youtube_client
from lib import state as run_state
from scripts import compone_descripcion

RUN_ID = "2026-10-20_000000_prueba-oc18"
TITULO = "How Does a Zip Work?"
DESCRIPCION_EN_BRUTO = "A zip has two rows of teeth.\n\n<<CAPITULOS>>"
CLAVES_OAUTH = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
GUIA = "docs/youtube-upload.md"


@pytest.fixture
def run(tmp_path, monkeypatch, marca_falsa) -> Path:
    """Un run del motor de escena del canal de ejemplo, con lo que comprueba la subida: el vídeo con su marca de IA,
    el `.srt` con su procedencia, el montaje con sus tiempos y el guion con su descripción por componer."""
    monkeypatch.setattr(provenance, "ASSETS_MIRROR_DIR", tmp_path / "copia-versionada")
    monkeypatch.setattr(compone_descripcion, "CANAL_VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(compone_descripcion, "NARRATION_LANG", "en")
    monkeypatch.setattr(config, "SUBTITLE_LANG", "en")
    monkeypatch.setattr(config, "NARRATION_LANG", "en")
    run_dir = tmp_path / "videos" / RUN_ID
    carpeta = config.dir_subir_al_canal(run_dir, crear=True)
    (carpeta / "final.mp4").write_bytes(b"video")
    srt = carpeta / "subtitulos.en.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello.\n", encoding="utf-8")
    registro = {
        "modelo_alineacion": "openai/whisper-small",
        "licencia": subtitulos.LICENCIA_ALINEADOR,
        "origen": "alineación en local",
        "idioma": "en",
        "srt": str(srt),
    }
    (run_dir / provenance.SUBTITLE_RECORDS_FILENAME).write_text(json.dumps([registro]), encoding="utf-8")
    detalle = [{"plano": n, "slide": n, "inicio_s": (n - 1) * 20.0, "segundos": 20.0} for n in (1, 2, 3)]
    montaje = {"motor": "escena", "formato": "laminas", "salida": "subir-al-canal/final.mp4", "actores": 0}
    montaje.update(duracion_s=60.0, detalle=detalle, marca_ia=marca_falsa.registro(carpeta / "final.mp4"))
    (run_dir / provenance.ASSEMBLY_SUMMARY_FILENAME).write_text(json.dumps(montaje), encoding="utf-8")
    capitulos = [{"slide_inicial": n, "titulo": t} for n, t in ((1, "Two rows"), (2, "The slider"), (3, "The stop"))]
    slides = {"title": TITULO, "description": DESCRIPCION_EN_BRUTO, "capitulos": capitulos, "slides": []}
    (run_dir / "slides.json").write_text(json.dumps(slides), encoding="utf-8")
    return run_dir


@pytest.fixture
def subida(run, monkeypatch):
    """`stage_upload` sobre ese run, con su estado en memoria y dobles en todo lo que saldría a la red.

    Devuelve las llamadas y el estado. El modo y las claves los pone cada prueba (`modo`): por defecto, a mano y sin
    claves, que es como llega quien acaba de instalar el motor.
    """
    import pipeline

    guardado = {
        "run_id": RUN_ID,
        "motor": run_state.MOTOR,
        "title": TITULO,
        "voice": "",
        "status": "assembled",
        "created_at": "2026-10-20T10:00:00",
        "output_dir": str(run),
        "stages": {
            "assembly": {"status": "complete", "output": str(config.dir_subir_al_canal(run) / "final.mp4")},
            "thumbnail": {},
            "upload": {"status": "pending"},
        },
    }
    llamadas: list = []

    def update_stage(_id, etapa, status, output=""):
        guardado["stages"][etapa] = {"status": status, "output": output}

    monkeypatch.setattr(run_state, "load_run", lambda _id: copy.deepcopy(guardado))
    monkeypatch.setattr(run_state, "update_stage", update_stage)
    monkeypatch.setattr(run_state, "update_run", lambda _id, cambios: guardado.update(cambios))
    monkeypatch.setattr(youtube_client, "get_access_token", lambda: llamadas.append(("token",)) or "x")
    subido = {"video_id": "abc123", "studio_url": "https://studio", "pendiente_a_mano": []}
    monkeypatch.setattr(youtube_client, "upload_video", lambda **k: llamadas.append(("sube", k)) or dict(subido))

    def sin_red(*_a, **_k):  # pragma: no cover - si se llama, la prueba falla
        raise AssertionError("la subida ha intentado salir a la red")

    for verbo in ("get", "post", "put"):
        monkeypatch.setattr(youtube_client.requests, verbo, sin_red)

    def modo(valor: str = "", *, claves: tuple[str, ...] = ()):
        monkeypatch.setattr(config, "YOUTUBE_SUBIDA_API", valor)
        for clave in CLAVES_OAUTH:
            monkeypatch.setattr(config, clave, "de-mentira" if clave in claves else "")
        return pipeline, llamadas, guardado

    return modo


def _leeme(run: Path) -> str:
    return (config.dir_subir_al_canal(run) / "LEEME.html").read_text(encoding="utf-8")


def _descripcion_del_leeme(run: Path) -> str:
    """La descripción que enseña el LEEME para copiar, sin el escapado del HTML."""
    return publicacion.descripcion_del_leeme(run)


def _lee_slides(run: Path) -> dict:
    return json.loads((run / "slides.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------ 1. a mano, lo de serie
def test_a_mano_ni_token_ni_red_y_el_leeme_lleva_la_descripcion_compuesta(subida, run):
    pipeline, llamadas, guardado = subida()
    assert pipeline.stage_upload(RUN_ID) is None
    assert llamadas == [], f"la subida a mano ha pedido un token o ha subido: {llamadas}"
    etapa = guardado["stages"]["upload"]
    assert etapa["status"] == "skipped" and "a mano en Studio" in etapa["output"]
    descripcion = _descripcion_del_leeme(run)
    # La compuesta: los capítulos con su minutaje y la declaración de IA, la misma que mandaría la API.
    assert "<<" not in descripcion and "00:00 Two rows" in descripcion and "00:20 The slider" in descripcion
    assert "AI DISCLOSURE — this video was produced with generative AI:" in descripcion
    assert descripcion.startswith("A zip has two rows of teeth.")
    html = _leeme(run)
    assert "<h2>Cómo subirlo a mano en Studio</h2>" in html
    assert "<b>Primero, privado.</b>" in html and "<b>Contenido alterado o sintético: sí.</b>" in html
    # La audiencia y la categoría son las del perfil del canal de ejemplo: no es para niños, y Educación (27).
    assert "<b>no</b> es contenido creado para niños" in html and "Educación (27)" in html
    assert "<code>thumbnail.png</code>" in html and "Subtítulos → Añadir idioma → Subir" in html
    assert "La pone el pipeline al subir" not in html, "a mano, la miniatura no la pone nadie más que el usuario"


def test_CONTROL_NEGATIVO_apagada_con_las_tres_claves_tampoco_pide_token_ni_sube(subida, run, capsys):
    """Hasta OC1.8 las tres claves encendían la subida: ahora no, y quien las tenga puestas se entera."""
    pipeline, llamadas, guardado = subida("", claves=CLAVES_OAUTH)
    assert pipeline.stage_upload(RUN_ID) is None
    assert llamadas == [] and guardado["stages"]["upload"]["status"] == "skipped"
    assert "escribe YOUTUBE_SUBIDA_API=1" in capsys.readouterr().out
    assert "AI DISCLOSURE" in _descripcion_del_leeme(run)


def test_a_mano_tambien_se_niega_sin_la_marca_de_ia(subida, run):
    """La preparación es la misma en los dos modos: un vídeo sin su marca no se deja listo para subir a mano."""
    from lib import marca_ia

    pipeline, llamadas, _ = subida()
    montaje = json.loads((run / provenance.ASSEMBLY_SUMMARY_FILENAME).read_text(encoding="utf-8"))
    del montaje["marca_ia"]
    (run / provenance.ASSEMBLY_SUMMARY_FILENAME).write_text(json.dumps(montaje), encoding="utf-8")
    with pytest.raises(marca_ia.ErrorDeMarca, match="--stage render"):
        pipeline.stage_upload(RUN_ID)
    assert llamadas == [] and not (config.dir_subir_al_canal(run) / "LEEME.html").exists()


# ------------------------------------------------------------------------------------------ 2. la API sin OAuth
@pytest.mark.parametrize("falta", CLAVES_OAUTH)
def test_encendida_sin_el_oauth_completo_se_niega_y_dice_que_falta_y_donde(subida, run, falta):
    pipeline, llamadas, guardado = subida("1", claves=tuple(c for c in CLAVES_OAUTH if c != falta))
    antes = _lee_slides(run)
    with pytest.raises(youtube_client.SubidaNoConfigurada) as negativa:
        pipeline.stage_upload(RUN_ID)
    motivo = str(negativa.value)
    # El token se nombra por la variable que declara el perfil del canal de ejemplo.
    assert f"le falta {falta}." in motivo and GUIA in motivo and "a mano en Studio" in motivo
    assert llamadas == [], "se niega antes de pedir el token"
    assert _lee_slides(run) == antes, "se niega antes de componer la descripción"
    assert not (config.dir_subir_al_canal(run) / "LEEME.html").exists()
    assert guardado["stages"]["upload"] == {"status": "pending"}, "la negativa no toca el estado del run"


def test_encendida_sin_ninguna_clave_las_nombra_todas(subida):
    pipeline, _, _ = subida("1")
    with pytest.raises(youtube_client.SubidaNoConfigurada, match="le falta " + ", ".join(CLAVES_OAUTH) + r"\."):
        pipeline.stage_upload(RUN_ID)


# ------------------------------------------------------------------------------------------ 3. un valor que no vale
@pytest.mark.parametrize("valor", ["si", "true", "0", "yes", "2"])
def test_un_valor_que_no_se_entiende_para_y_dice_que_escribir(subida, valor):
    pipeline, llamadas, guardado = subida(valor, claves=CLAVES_OAUTH)
    with pytest.raises(youtube_client.SubidaNoConfigurada, match=rf"vale '{valor}'.*vacío.*o 1, para que lo suba"):
        pipeline.stage_upload(RUN_ID)
    assert llamadas == [] and guardado["stages"]["upload"] == {"status": "pending"}


# ------------------------------------------------------------------------------------------ 4. la API con OAuth
def test_CONTROL_encendida_con_el_oauth_sube_privado_con_la_declaracion(subida, run):
    """Sin esto, las negativas de arriba no distinguen «se niega por el OAuth» de «el arnés no deja subir nunca»."""
    pipeline, llamadas, guardado = subida("1", claves=CLAVES_OAUTH)
    resultado = pipeline.stage_upload(RUN_ID)
    sube = [k for que, *k in llamadas if que == "sube"]
    assert len(sube) == 1 and resultado["video_id"] == "abc123"
    enviado = sube[0][0]
    assert enviado["title"] == TITULO and "AI DISCLOSURE" in enviado["description"]
    assert guardado["stages"]["upload"]["status"] == "complete" and guardado["status"] == "uploaded"
    html = _leeme(run)
    assert "abc123" in html and "Cómo subirlo a mano en Studio" not in html
    assert _descripcion_del_leeme(run) == enviado["description"], "el LEEME enseña la descripción que se subió"


def test_a_mano_un_run_ya_subido_no_se_toca_ni_con_forzar_subida(subida, run, capsys):
    """`--forzar-subida` pide un segundo borrador por la API. A mano no hay ninguno que hacer, y reescribir el LEEME sin
    su enlace de Studio invitaría a subir un duplicado (R3 de progress/review_OC1.8.md)."""
    pipeline, llamadas, guardado = subida()
    previo = {"video_id": "ya-arriba", "url": "https://youtube.com/watch?v=ya-arriba"}
    guardado["stages"]["upload"] = {"status": "complete", "output": json.dumps(previo)}
    assert pipeline.stage_upload(RUN_ID, forzar=True) == previo
    assert llamadas == [] and not (config.dir_subir_al_canal(run) / "LEEME.html").exists()
    assert guardado["stages"]["upload"]["status"] == "complete"
    assert "necesita YOUTUBE_SUBIDA_API=1" in capsys.readouterr().out


@pytest.mark.parametrize(("valor", "claves", "dice"), [("", (), "pon la miniatura a mano"), ("x", (), "vale 'x'")])
def test_set_thumbnail_obedece_al_interruptor(subida, monkeypatch, capsys, valor, claves, dice):
    """`--set-thumbnail` pone la miniatura por la API: apagada o con un valor que no vale, ni token ni red (R2)."""
    pipeline, llamadas, guardado = subida(valor, claves=claves)
    guardado["stages"]["upload"] = {"status": "complete", "output": json.dumps({"video_id": "ya-arriba"})}
    monkeypatch.setattr(youtube_client, "pon_miniatura", lambda *a: llamadas.append(("miniatura",)) or (True, None))
    assert pipeline.set_thumbnail(RUN_ID) is False
    assert llamadas == [] and dice in capsys.readouterr().out


def test_CONTROL_set_thumbnail_con_la_api_pasa_del_interruptor(subida, capsys):
    """Con la API y el OAuth, la puerta deja pasar: se para después, por no haber miniatura en este run."""
    pipeline, _, guardado = subida("1", claves=CLAVES_OAUTH)
    guardado["stages"]["upload"] = {"status": "complete", "output": json.dumps({"video_id": "ya-arriba"})}
    assert pipeline.set_thumbnail(RUN_ID) is False
    assert "No hay miniatura en el run" in capsys.readouterr().out


def test_la_visibilidad_sigue_siendo_una_constante_privada():
    """La subida por la API no gana ningún parámetro de visibilidad: sigue siendo la decisión cerrada 1."""
    assert youtube_client.VISIBILIDAD == "private"


# ------------------------------------------------------------------------------------------ 5. run_all
@pytest.fixture
def run_all(subida, monkeypatch):
    """`run_all` con el render ya hecho: la miniatura y la escena son dobles, y la página no se abre."""

    def con(valor: str = "", **kw):
        pipeline, llamadas, guardado = subida(valor, **kw)
        monkeypatch.setattr(pipeline, "_avanza_escena", lambda _id: True)
        monkeypatch.setattr(pipeline, "stage_thumbnail", lambda _id: None)
        monkeypatch.setattr(pipeline, "_abre_la_guia", lambda _state: None)
        return pipeline, llamadas, guardado

    return con


def test_run_all_a_mano_no_pisa_el_leeme_con_la_descripcion_en_bruto(run_all, run):
    pipeline, llamadas, guardado = run_all()
    pipeline.run_all(RUN_ID)
    assert llamadas == [] and guardado["stages"]["upload"]["status"] == "skipped"
    descripcion = _descripcion_del_leeme(run)
    assert "AI DISCLOSURE" in descripcion and "<<CAPITULOS>>" not in descripcion
    assert "Cómo subirlo a mano en Studio" in _leeme(run)


def test_run_all_con_la_api_sin_oauth_se_niega_antes_de_renderizar(run_all, monkeypatch):
    """La negativa llegaba después del render entero (R5 de progress/review_OC1.8.md): ahora va antes de la escena."""
    pipeline, llamadas, _ = run_all("1", claves=CLAVES_OAUTH[:2])
    escena = []
    monkeypatch.setattr(pipeline, "_avanza_escena", lambda _id: escena.append(1) or True)
    with pytest.raises(youtube_client.SubidaNoConfigurada, match="le falta YOUTUBE_REFRESH_TOKEN"):
        pipeline.run_all(RUN_ID)
    assert escena == [] and llamadas == []
    pipeline.run_all(RUN_ID, sin_subida=True)
    assert escena == [1], "control: con --sin-subida el modo no se mira y la escena avanza"


def test_CONTROL_con_sin_subida_la_pagina_de_reserva_sigue_como_estaba(run_all, run):
    """`--sin-subida` no prepara nada: su LEEME lleva la descripción en bruto, como antes de OC1.8. Si la prueba de
    arriba no distinguiera las dos páginas, esta no saldría distinta."""
    pipeline, llamadas, guardado = run_all()
    pipeline.run_all(RUN_ID, sin_subida=True)
    assert llamadas == [] and "--sin-subida" in guardado["stages"]["upload"]["output"]
    descripcion = _descripcion_del_leeme(run)
    assert "<<CAPITULOS>>" in descripcion and "AI DISCLOSURE" not in descripcion
    assert "Cómo subirlo a mano en Studio" not in _leeme(run)


# ------------------------------------------------------------------------------------------ 6. lo que dice el modo
@pytest.mark.parametrize(
    ("valor", "claves", "ok", "dice"),
    [
        ("", (), True, "✓ subida a mano en Studio"),
        ("", CLAVES_OAUTH, True, "no se usan hasta que escribas YOUTUBE_SUBIDA_API=1"),
        ("1", CLAVES_OAUTH, True, "✓ subida por la API: encendida, con el OAuth completo"),
        ("1", CLAVES_OAUTH[:2], False, "✗ subida por la API: YOUTUBE_SUBIDA_API=1 enciende"),
        ("si", CLAVES_OAUTH, False, "✗ subida por la API: YOUTUBE_SUBIDA_API vale 'si'"),
    ],
    ids=["a-mano", "a-mano-con-claves", "api", "api-sin-token", "valor-invalido"],
)
def test_check_dice_el_modo_y_sale_en_rojo_si_la_subida_pararia(monkeypatch, capsys, valor, claves, ok, dice):
    import pipeline

    monkeypatch.setattr(config, "YOUTUBE_SUBIDA_API", valor)
    for clave in CLAVES_OAUTH:
        monkeypatch.setattr(config, clave, "de-mentira" if clave in claves else "")
    assert pipeline._comprueba_la_subida() is ok
    assert dice in capsys.readouterr().out


def test_check_completo_cuenta_la_subida_en_su_veredicto(monkeypatch):
    """`check_dependencies` usa ese bloque para su `all_ok`: con la API pedida sin OAuth, el `--check` sale en rojo."""
    import pipeline

    llamado = []
    monkeypatch.setattr(pipeline, "_comprueba_la_subida", lambda: llamado.append(1) or False)
    for adaptador in (pipeline.comfy_client, pipeline.voice_client, pipeline.musica, pipeline.subtitulos):
        monkeypatch.setattr(adaptador, "preflight", lambda: [])
    monkeypatch.setattr("shutil.which", lambda _nombre: "binario")
    monkeypatch.setattr(config, "RUTAS_DE_HERRAMIENTAS", {})
    monkeypatch.setattr(pipeline, "_comprueba_el_motor_de_escena", lambda: True)
    assert pipeline.check_dependencies() is False and llamado == [1]
    monkeypatch.setattr(pipeline, "_comprueba_la_subida", lambda: True)
    assert pipeline.check_dependencies() is True, "control: con la subida en verde, el resto del --check pasa"


@pytest.mark.parametrize(
    ("valor", "pide"), [("", False), ("1", True), ("0", False)], ids=["a-mano", "api", "valor-que-no-vale"]
)
def test_canales_y_comprueba_canal_solo_piden_el_token_con_la_api(monkeypatch, valor, pide):
    import sys

    import pipeline

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import comprueba_canal

    monkeypatch.setattr(config, "YOUTUBE_SUBIDA_API", valor)
    monkeypatch.delenv("YOUTUBE_REFRESH_TOKEN", raising=False)
    ejemplo = next(c for c in pipeline.listar_canales() if c["id"] == "example")
    assert ("sin OAuth" in ejemplo["veredicto"]) is pide, ejemplo["veredicto"]
    perfil = json.loads(
        (Path(__file__).resolve().parent.parent / "canales" / "example" / "perfil.json").read_text(encoding="utf-8")
    )
    token = next(r for r in comprueba_canal._pasos_del_usuario(perfil) if r["nombre"] == "token OAuth del canal")
    assert token["ok"] is not pide, token
    if pide:
        assert GUIA in token["detalle"]
