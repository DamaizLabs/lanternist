"""Lo que cada canal declara y lo que es del estudio, sin defectos en medio (F5.14, addendum filas 195 y 196).

Antes de montar el tercer canal se cerraron cuatro sitios por donde un canal heredaba decisiones de otro sin
saberlo: los `DEFECTOS` de subtítulos y música (eran los del primero), la categoría de YouTube («22» para
todos), los umbrales del kill switch copiados en cada perfil (el kill switch salió de la fábrica en OC1.4), y las
variables propias de cada canal que `init.mjs` no veía. Cada prueba de aquí tiene su control: el mismo perfil con
una pieza de menos o de más tiene que PARAR, no seguir con un valor de otro canal.
"""

import json
from pathlib import Path

import pytest

from lib import config, musica, onda, subtitulos, youtube_client
from lib.youtube_client import CATEGORY_NAMES

RAIZ = Path(__file__).resolve().parent.parent
PERFILES = sorted((RAIZ / "canales").glob("*/perfil.json"))
BASE = config.base_del_estudio()

SUBS_COMPLETOS = {
    "activos": True,
    "srt": True,
    "fuente": "Georgia",
    "cuerpo": 60,
    "max_palabras_por_linea": 12,
    "margen_inferior_px": 150,
    "margen_lateral_px": 200,
    "traducciones": [],
}
MUSICA_COMPLETA = {
    "activa": True,
    "escena": "quiet study, soft piano",
    "volumen_db": -17.0,
    "tramo_segundos": 45.0,
    "solape_segundos": 4.0,
    "sonoridad_por_tramo": None,
    "umbral_ducking": 0.05,
    "ratio_ducking": 6.0,
    "ataque_ms": 20,
    "suelta_ms": 500,
    "semilla_base": None,
}


def _perfil(monkeypatch, perfil: dict) -> None:
    monkeypatch.setattr(config, "CANAL_PERFIL", perfil)
    monkeypatch.setattr(subtitulos, "CANAL_PERFIL", perfil)
    monkeypatch.setattr(musica, "CANAL_PERFIL", perfil)


# ── Subtítulos ────────────────────────────────────────────────────────────────────────────────


def test_subtitulos_completos_dan_lo_del_canal_mas_lo_del_estudio(monkeypatch):
    _perfil(monkeypatch, {"subtitulos": dict(SUBS_COMPLETOS)})
    cfg = subtitulos.ajustes()
    assert cfg["fuente"] == "Georgia" and cfg["cuerpo"] == 60
    assert "quemar" not in cfg and "crf" not in cfg, "el interruptor y la calidad del quemado salieron en F6.7"
    assert cfg["modelo_alineacion"] == BASE["produccion"]["karaoke"]["modelo_alineacion"]


@pytest.mark.parametrize("falta", subtitulos.DEL_CANAL)
def test_control_un_valor_de_subtitulos_de_menos_para_y_dice_cual(monkeypatch, falta):
    sin = {k: v for k, v in SUBS_COMPLETOS.items() if k != falta}
    _perfil(monkeypatch, {"subtitulos": sin})
    with pytest.raises(subtitulos.SubtitulosError, match=falta):
        subtitulos.ajustes()


def test_un_canal_sin_subtitulos_solo_declara_que_no_los_lleva(monkeypatch):
    _perfil(monkeypatch, {"subtitulos": {"activos": False}})
    assert subtitulos.ajustes()["activos"] is False
    # y la onda guardada no lee cuerpo ni margen que el canal no tiene
    assert onda.holgura_con_subtitulos(object())["activo"] is False


def test_forzar_subtitulos_por_entorno_en_un_canal_sin_ellos_pide_su_tipografia(monkeypatch):
    # Auditoría de F5.14: `SUBTITULOS=1` sobre `activos: false` daba un KeyError sin explicación.
    _perfil(monkeypatch, {"subtitulos": {"activos": False}})
    monkeypatch.setenv("SUBTITULOS", "1")
    with pytest.raises(subtitulos.SubtitulosError, match="forzando por entorno"):
        subtitulos.ajustes()
    monkeypatch.setenv("SUBTITULOS", "0")  # y apagarlos en un run no pide nada
    _perfil(monkeypatch, {"subtitulos": dict(SUBS_COMPLETOS)})
    assert subtitulos.activa() is False


def test_control_sin_decir_si_lleva_subtitulos_para(monkeypatch):
    _perfil(monkeypatch, {"subtitulos": {"fuente": "Georgia"}})
    with pytest.raises(subtitulos.SubtitulosError, match="subtitulos.activos"):
        subtitulos.ajustes()


@pytest.mark.parametrize("del_estudio", subtitulos.DEL_ESTUDIO)
def test_control_un_perfil_que_declara_un_valor_del_estudio_para(monkeypatch, del_estudio):
    _perfil(monkeypatch, {"subtitulos": {**SUBS_COMPLETOS, del_estudio: 23}})
    with pytest.raises(subtitulos.SubtitulosError, match="es del estudio"):
        subtitulos.ajustes()


# ── Música ────────────────────────────────────────────────────────────────────────────────────


def test_musica_completa_da_lo_del_canal_mas_lo_del_estudio(monkeypatch):
    _perfil(monkeypatch, {"musica": dict(MUSICA_COMPLETA)})
    cfg = musica.ajustes()
    assert cfg["semilla_base"] is None  # null es una respuesta válida: se escribe, no se hereda
    assert cfg["objetivo_lufs"] == BASE["produccion"]["lecho_musical"]["objetivo_lufs"]
    assert cfg["workflow"] == BASE["produccion"]["lecho_musical"]["workflow"]


@pytest.mark.parametrize("falta", musica.DEL_CANAL)
def test_control_un_valor_de_musica_de_menos_para_y_dice_cual(monkeypatch, falta):
    sin = {k: v for k, v in MUSICA_COMPLETA.items() if k != falta}
    _perfil(monkeypatch, {"musica": sin})
    with pytest.raises(musica.MusicaError, match=falta):
        musica.ajustes()


@pytest.mark.parametrize("nula", [k for k in musica.DEL_CANAL if k not in musica.PUEDEN_SER_NULL])
def test_control_un_valor_de_musica_a_null_para_al_principio(monkeypatch, nula):
    # Auditoría de F5.14: con `volumen_db: null` el fallo llegaba a ffmpeg como `volume=NonedB`,
    # después de generar el lecho en la GPU. Solo `semilla_base` y `sonoridad_por_tramo` pueden valer null.
    _perfil(monkeypatch, {"musica": {**MUSICA_COMPLETA, nula: None}})
    with pytest.raises(musica.MusicaError, match=nula):
        musica.ajustes()


def test_los_que_pueden_ser_null_son_solo_dos():
    """Que un null sea válido es una decisión que se escribe; ampliar la lista la cambia para todos los canales."""
    assert set(musica.PUEDEN_SER_NULL) == {"semilla_base", "sonoridad_por_tramo"}


# F6.5b (fila 210): igualar cada tramo antes de encadenarlo, y el ataque y la suelta del compresor, eran del primer
# canal y estaban fijos en lib/musica.py. Ahora los declara cada canal, sin defecto.
IGUALA_V3 = {"lufs": -22, "rango_lu": 6, "pico_dbtp": -2}


def test_la_sonoridad_por_tramo_declarada_llega_al_filtro_y_null_no_anade_nada(monkeypatch):
    _perfil(monkeypatch, {"musica": {**MUSICA_COMPLETA, "sonoridad_por_tramo": dict(IGUALA_V3)}})
    assert musica.filtro_de_sonoridad_por_tramo(musica.ajustes()) == "loudnorm=I=-22:LRA=6:TP=-2,aresample=48000,"
    # Control: con null no hay igualado, y la cadena queda como antes de F6.5b.
    _perfil(monkeypatch, {"musica": dict(MUSICA_COMPLETA)})
    assert musica.filtro_de_sonoridad_por_tramo(musica.ajustes()) == ""


@pytest.mark.parametrize(
    "mala",
    [
        {"lufs": -22, "rango_lu": 6},  # falta una
        {"lufs": -22, "rango_lu": 6, "pico_dbtp": -2, "extra": 1},  # sobra una
        {"lufs": "-22", "rango_lu": 6, "pico_dbtp": -2},  # no es un número
        {"lufs": True, "rango_lu": 6, "pico_dbtp": -2},  # un booleano no es un número
        -22,  # no es un objeto
    ],
)
def test_control_una_sonoridad_por_tramo_mal_escrita_para_antes_de_la_gpu(monkeypatch, mala):
    _perfil(monkeypatch, {"musica": {**MUSICA_COMPLETA, "sonoridad_por_tramo": mala}})
    with pytest.raises(musica.MusicaError, match="sonoridad_por_tramo"):
        musica.ajustes()


def test_el_ataque_y_la_suelta_del_canal_llegan_al_compresor(monkeypatch):
    _perfil(monkeypatch, {"musica": {**MUSICA_COMPLETA, "ataque_ms": 30, "suelta_ms": 1200.0}})
    assert "attack=30:release=1200:" in musica.filtro_de_ducking(musica.ajustes())
    # Control: los del primer canal dan exactamente la cadena que estaba fija antes de F6.5b.
    _perfil(monkeypatch, {"musica": dict(MUSICA_COMPLETA)})
    assert musica.filtro_de_ducking(musica.ajustes()) == (
        "sidechaincompress=threshold=0.05:ratio=6.0:attack=20:release=500:makeup=1"
    )


def test_un_canal_sin_musica_solo_declara_que_no_la_lleva(monkeypatch):
    _perfil(monkeypatch, {"musica": {"activa": False}})
    assert musica.activa() is False


@pytest.mark.parametrize("del_estudio", musica.DEL_ESTUDIO)
def test_control_un_perfil_que_declara_un_valor_de_musica_del_estudio_para(monkeypatch, del_estudio):
    _perfil(monkeypatch, {"musica": {**MUSICA_COMPLETA, del_estudio: -9.0}})
    with pytest.raises(musica.MusicaError, match="es del estudio"):
        musica.ajustes()


# ── Los perfiles reales ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ruta", PERFILES, ids=lambda p: p.parent.name)
def test_los_perfiles_reales_cumplen_el_reparto(ruta, monkeypatch):
    perfil = json.loads(ruta.read_text(encoding="utf-8"))
    _perfil(monkeypatch, perfil)
    subtitulos.ajustes()
    musica.ajustes()
    assert (perfil.get("publicacion") or {}).get("categoria_youtube") in CATEGORY_NAMES


def test_el_workflow_de_musica_del_estudio_no_lleva_estilo_de_ningun_canal():
    """F6.5b: el `prefijo_estilo` de ace-step-lecho era el estilo del primer canal y se anteponía a todas."""
    from lib import comfy_client

    workflow = comfy_client.load_workflow(BASE["produccion"]["lecho_musical"]["workflow"])
    assert not (workflow.get("prefijo_estilo") or "").strip()
    for ruta in PERFILES:
        bloque = json.loads(ruta.read_text(encoding="utf-8")).get("musica") or {}
        if bloque.get("activa"):
            # Lo que recibe ACE-Step es la escena del canal, entera y sin nada del estudio delante.
            assert comfy_client._compose_prompt(workflow, bloque["escena"]) == bloque["escena"], ruta.parent.name


# ── Categoría de YouTube ──────────────────────────────────────────────────────────────────────


class _Interceptada(Exception):
    pass


def _cuerpo_de_la_subida(monkeypatch, tmp_path) -> dict:
    capturado = {}

    def post_falso(url, **kwargs):
        capturado["json"] = kwargs.get("json")
        raise _Interceptada

    monkeypatch.setattr(youtube_client, "get_access_token", lambda: "token-de-mentira")
    monkeypatch.setattr(youtube_client.requests, "post", post_falso)
    video = tmp_path / "final.mp4"
    video.write_bytes(b"no se llega a leer")
    with pytest.raises(_Interceptada):
        youtube_client.upload_video(file_path=str(video), title="T", description="AI DISCLOSURE: local.")
    return capturado["json"]


def test_la_subida_manda_la_categoria_del_perfil(monkeypatch, tmp_path):
    monkeypatch.setattr(youtube_client, "CATEGORIA_YOUTUBE", "27")
    assert _cuerpo_de_la_subida(monkeypatch, tmp_path)["snippet"]["categoryId"] == "27"


def test_control_una_categoria_que_youtube_no_conoce_para_antes_de_pedir_el_token(monkeypatch, tmp_path):
    monkeypatch.setattr(youtube_client, "CATEGORIA_YOUTUBE", "999")

    def no_toca_la_red():
        raise AssertionError("pidió el token antes de validar la categoría")

    monkeypatch.setattr(youtube_client, "get_access_token", no_toca_la_red)
    video = tmp_path / "final.mp4"
    video.write_bytes(b"no se llega a leer")
    with pytest.raises(RuntimeError, match="categoria_youtube"):
        youtube_client.upload_video(file_path=str(video), title="T", description="AI DISCLOSURE: local.")
