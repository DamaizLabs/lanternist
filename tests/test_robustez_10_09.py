"""Lo que la auditoría del 10-09 rompió a propósito: entrada corrupta en el camino de producción.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_robustez_10_09.py

**Cada prueba de aquí es un control negativo que fallaba antes del arreglo.** Los tres defectos los
encontró la auditoría ejecutando el código contra ficheros roto a propósito, no leyéndolo, y los tres
tenían la misma forma: un fichero que nadie había roto nunca.

1. **`_dump_records` borraba la procedencia previa** si el registro no parseaba (ALTO). Era pérdida de
   datos de la decisión 5: ese fichero es la única fuente de `assets.json`, así que las 33 láminas
   anteriores solo se recuperaban regenerándolas.
2. **La quema de subtítulos dejaba el run sin `final.mp4`** si ffmpeg fallaba (ALTO). Sus pruebas
   salieron con el karaoke quemado en F6.7 (02-10-2026).
3. **`escribe_srt` validaba después de escribir** (MEDIO), así que el `.srt` inválido se quedaba en
   `subir-al-canal/`, que es la carpeta que el usuario abre para adjuntarlo en Studio.
"""

import json
from pathlib import Path

import pytest

from lib import comfy_client, voice_client
from lib.subtitulos import SubtitulosError, escribe_srt

MODULOS = pytest.mark.parametrize("modulo", [comfy_client, voice_client], ids=["imagen", "voz"])

PREVIAS = [
    {"id": "PREVIA-1", "file": "slides/01.png", "seed": 111},
    {"id": "PREVIA-2", "file": "slides/02.png", "seed": 222},
]
NUEVA = [{"id": "NUEVA", "file": "slides/03.png", "seed": 333}]


def _registro(modulo, dir_: Path) -> Path:
    return dir_ / modulo._RECORDS_FILENAME


def _apartados(modulo, dir_: Path) -> list[Path]:
    return sorted(dir_.glob(f"{modulo._RECORDS_FILENAME}.roto-*"))


# --- 1 · el registro de procedencia ---------------------------------------------------------------


@MODULOS
def test_un_registro_truncado_no_borra_la_procedencia_previa(modulo, tmp_path):
    """EL CONTROL NEGATIVO DEL ALTO: antes esto dejaba 1 entrada y PREVIA-1/2 desaparecían."""
    entero = json.dumps(PREVIAS, indent=2)
    _registro(modulo, tmp_path).write_text(entero[: len(entero) // 2], encoding="utf-8")

    modulo._dump_records(tmp_path, NUEVA)

    apartado = _apartados(modulo, tmp_path)
    assert len(apartado) == 1, "el registro ilegible tiene que quedar en disco, no sobrescribirse"
    assert "PREVIA-1" in apartado[0].read_text(encoding="utf-8")
    assert [e["id"] for e in json.loads(_registro(modulo, tmp_path).read_text(encoding="utf-8"))] == ["NUEVA"]


@MODULOS
def test_un_registro_que_es_un_diccionario_se_aparta_en_vez_de_reventar(modulo, tmp_path):
    _registro(modulo, tmp_path).write_text(json.dumps({"esto": "no es una lista"}), encoding="utf-8")

    modulo._dump_records(tmp_path, NUEVA)

    assert len(_apartados(modulo, tmp_path)) == 1
    assert [e["id"] for e in json.loads(_registro(modulo, tmp_path).read_text(encoding="utf-8"))] == ["NUEVA"]


@MODULOS
def test_un_registro_con_bytes_que_no_son_utf8_se_aparta(modulo, tmp_path):
    _registro(modulo, tmp_path).write_bytes(b'[{"id": "\xff\xfe roto"}]')

    modulo._dump_records(tmp_path, NUEVA)

    assert len(_apartados(modulo, tmp_path)) == 1
    assert json.loads(_registro(modulo, tmp_path).read_text(encoding="utf-8"))[0]["id"] == "NUEVA"


@MODULOS
def test_un_registro_sano_se_conserva_y_la_nueva_entrada_se_anade_al_final(modulo, tmp_path):
    """El camino bueno: sin esto, la prueba de arriba pasaría con un módulo que apartara SIEMPRE."""
    _registro(modulo, tmp_path).write_text(json.dumps(PREVIAS), encoding="utf-8")

    modulo._dump_records(tmp_path, NUEVA)

    assert not _apartados(modulo, tmp_path)
    ids = [e["id"] for e in json.loads(_registro(modulo, tmp_path).read_text(encoding="utf-8"))]
    assert ids == ["PREVIA-1", "PREVIA-2", "NUEVA"]


@MODULOS
def test_sin_registro_previo_escribe_solo_lo_nuevo(modulo, tmp_path):
    modulo._dump_records(tmp_path, NUEVA)

    assert not _apartados(modulo, tmp_path)
    assert [e["id"] for e in json.loads(_registro(modulo, tmp_path).read_text(encoding="utf-8"))] == ["NUEVA"]


# --- 3 · el .srt no se escribe si no vale ---------------------------------------------------------


def _grupo(palabra: str, desde: float, hasta: float) -> list[dict]:
    return [{"palabra": palabra, "desde": desde, "hasta": hasta}]


def test_un_srt_invalido_no_llega_a_escribirse(tmp_path):
    """EL CONTROL NEGATIVO DEL MEDIO: antes el fichero malo quedaba en `subir-al-canal/`."""
    destino = tmp_path / "subtitulos.en.srt"

    with pytest.raises(SubtitulosError):
        escribe_srt([(_grupo("hola", 2.0, 1.0), 0.0)], destino)

    assert not destino.exists(), "un .srt que Studio rechaza no puede quedarse en la carpeta de subida"


def test_un_srt_invalido_no_pisa_el_que_ya_estaba_bien(tmp_path):
    destino = tmp_path / "subtitulos.en.srt"
    escribe_srt([(_grupo("hello", 0.0, 1.5), 0.0)], destino)
    bueno = destino.read_text(encoding="utf-8")

    with pytest.raises(SubtitulosError):
        escribe_srt([(_grupo("hola", 2.0, 1.0), 0.0)], destino)

    assert destino.read_text(encoding="utf-8") == bueno


def test_un_srt_bien_formado_se_escribe_con_sus_tiempos(tmp_path):
    destino = tmp_path / "subtitulos.en.srt"

    escribe_srt([(_grupo("hello", 0.0, 1.5), 0.0), (_grupo("world", 1.5, 2.25), 0.0)], destino)

    assert destino.read_text(encoding="utf-8").startswith("1\n00:00:00,000 --> 00:00:01,500\nhello")
    assert "2\n00:00:01,500 --> 00:00:02,250\nworld" in destino.read_text(encoding="utf-8")


# --- 4 · el estado del run: codificación y lectores tolerantes ------------------------------------


@pytest.fixture
def estados(tmp_path, monkeypatch):
    """Un directorio de estados propio, para no tocar el del canal activo."""
    directorio = tmp_path / "estado"
    directorio.mkdir()
    monkeypatch.setattr("lib.state.STATE_DIR", directorio)
    return directorio


def test_un_titulo_con_acentos_sobrevive_a_la_ida_y_vuelta(estados):
    """EL CONTROL NEGATIVO: `open()` sin encoding lee en cp1252 y devolvía «Ã‘andÃº»."""
    from lib import state

    state._save_state("r1", {"run_id": "r1", "title": "Ñandú — acentos y comillas «así»"})

    assert state.load_run("r1")["title"] == "Ñandú — acentos y comillas «así»"
    assert not [b for b in (estados / "r1.json").read_bytes() if b > 127], "el estado se guarda en ASCII escapado"


def test_un_estado_escrito_en_utf8_por_otra_herramienta_se_lee_bien(estados):
    """Lo que hacía la migración a `subir-al-canal/`: UTF-8 sin escapar."""
    from lib import state

    (estados / "r2.json").write_text(
        json.dumps({"run_id": "r2", "title": "Ñandú"}, ensure_ascii=False), encoding="utf-8"
    )

    assert state.load_run("r2")["title"] == "Ñandú"


def test_un_estado_roto_no_tumba_el_listado_de_los_demas(estados, capsys):
    from lib import state

    state._save_state("bueno", {"run_id": "bueno", "status": "created"})
    (estados / "zz-roto.json").write_text('{"run_id": "zz-roto", "sta', encoding="utf-8")

    runs = state.list_runs()

    assert [r["run_id"] for r in runs] == ["bueno"]
    assert "zz-roto.json" in capsys.readouterr().out


def test_un_estado_roto_al_cargarlo_dice_cual_es_y_que_hacer(estados):
    from lib import state

    (estados / "roto.json").write_text('{"run_id": "roto"', encoding="utf-8")

    with pytest.raises(state.EstadoRoto) as exc:
        state.load_run("roto")

    assert "roto.json" in str(exc.value) and "a mano" in str(exc.value)


def test_un_estado_que_no_existe_tambien_lo_dice_por_su_nombre(estados):
    from lib import state

    with pytest.raises(state.EstadoRoto) as exc:
        state.load_run("no-existe")

    assert "no-existe.json" in str(exc.value)


# --- 5 · el otro lector frágil (el del montaje.json lo leía el CTA del motor de láminas, retirado en F6.7) ---


def test_un_sidecar_de_procedencia_que_es_un_diccionario_se_ignora_con_aviso(tmp_path, capsys):
    """EL CONTROL NEGATIVO: antes iteraba las CLAVES y moría con AttributeError."""
    from lib import provenance

    slides = tmp_path / "slides"
    slides.mkdir()
    (slides / provenance.IMAGE_RECORDS_FILENAME).write_text('{"no": "es una lista"}', encoding="utf-8")

    entradas = provenance.entries_from_adapters(tmp_path)

    assert entradas == []
    assert "se ignora" in capsys.readouterr().out
