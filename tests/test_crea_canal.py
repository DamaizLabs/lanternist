"""Las herramientas de la skill `crea-canal` (F5.15), sin GPU y sin tocar nada real.

`comprueba_canal.py` es la que dice si un canal está creado y configurado: se prueba sobre los canales
del repositorio (tienen que salir limpios de lo que es del repo) y con copias del canal activo —el de
ejemplo, en la suite— a las que les falta una pieza (tienen que cazarla). Las muestras de voz y la cata del
ritmo son del paso 4 de `crea-canal` (fila 258) y usan GPU; aquí se prueba lo que hacen antes y después:
validar la entrada sin crear nada y montar la página.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from canales_de_prueba import RECETA_DOCUMENTAL

RAIZ = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
sys.path.insert(0, str(RAIZ / "scripts"))

import cata_ritmo  # noqa: E402
import comprueba_canal  # noqa: E402
import muestras_voz  # noqa: E402
import rejilla_de_marca  # noqa: E402

from lib import config  # noqa: E402

CANALES = sorted(p.parent.name for p in (RAIZ / "canales").glob("*/perfil.json"))


# ── comprueba_canal ───────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("canal", CANALES)
def test_los_canales_reales_no_tienen_nada_pendiente_del_repo(canal):
    r = subprocess.run(
        [PYTHON, str(RAIZ / "scripts" / "comprueba_canal.py"), "--canal", canal, "--json"],
        capture_output=True, text=True, encoding="utf-8", cwd=RAIZ,
    )  # fmt: skip
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    datos = json.loads(r.stdout[: r.stdout.rindex("]") + 1])
    pendientes = [x for x in datos if not x["ok"] and x["quien"] == "claude"]
    assert pendientes == []


def _copia_del_canal_activo(
    tmp_path, monkeypatch, sin: tuple[str, ...] = (), contratos: bool = True, retoca=None, con_receta: bool = False
) -> str:
    canal = config.CANAL_ACTIVO
    origen = RAIZ / "canales" / canal
    destino = tmp_path / "canales" / canal
    destino.mkdir(parents=True)
    perfil = json.loads((origen / "perfil.json").read_text(encoding="utf-8"))
    for clave in sin:
        perfil.pop(clave)
    if retoca:
        retoca(perfil)
    (destino / "perfil.json").write_text(json.dumps(perfil, ensure_ascii=False), encoding="utf-8")
    if contratos:
        for c in ("contrato-prompt-imagen.md", "contrato-miniatura.md"):
            shutil.copy(origen / c, destino / c)
    if con_receta:  # un canal que ya produce: su receta de voz existe
        (destino / "datos").mkdir()
        receta = perfil["voz"]["receta"]
        # La del canal si ya la tiene; si no (el de ejemplo, hasta OC1.4), una de prueba con ese nombre.
        de_donde = origen / "datos" / receta
        shutil.copy(de_donde if de_donde.is_file() else RECETA_DOCUMENTAL, destino / "datos" / receta)
    monkeypatch.setattr(comprueba_canal, "RAIZ", tmp_path)
    return canal


def _por_nombre(resultados: list[dict]) -> dict:
    return {r["nombre"]: r for r in resultados}


def test_la_copia_entera_del_canal_activo_pasa(tmp_path, monkeypatch):
    canal = _copia_del_canal_activo(tmp_path, monkeypatch)
    r = _por_nombre(comprueba_canal.comprueba(canal))
    assert r["buzón de ideas"]["ok"] and r["esquema del perfil"]["ok"] and r["contrato-miniatura.md"]["ok"]


@pytest.mark.parametrize(
    ("falta", "comprobacion"),
    [("ideas", "buzón de ideas"), ("musica", "esquema del perfil"), ("marca", "bloque `marca`")],
)
def test_control_una_pieza_de_menos_se_caza(tmp_path, monkeypatch, falta, comprobacion):
    canal = _copia_del_canal_activo(tmp_path, monkeypatch, sin=(falta,))
    r = _por_nombre(comprueba_canal.comprueba(canal))
    assert r[comprobacion]["ok"] is False and r[comprobacion]["quien"] == "claude"


def test_sin_ritmo_de_voz_queda_pendiente_de_la_voz_y_no_bloquea(tmp_path, monkeypatch):
    # Es lo que tiene un canal a medio crear: su voz la monta el paso 4 de crea-canal (fila 258).
    canal = _copia_del_canal_activo(tmp_path, monkeypatch, retoca=lambda p: p["voz"].pop("palabras_por_segundo", None))
    r = _por_nombre(comprueba_canal.comprueba(canal))
    ritmo = r["ritmo de la voz (voz.palabras_por_segundo)"]
    assert ritmo["ok"] is False and ritmo["quien"] == "voz"
    assert r["claves que exige el verificador de guiones"]["ok"] is True  # el resto sí está
    monkeypatch.setenv("CANAL_ACTIVO", canal)
    assert comprueba_canal.main(["--canal", canal]) == 0


def test_control_con_la_receta_escrita_el_ritmo_que_falta_es_del_repo(tmp_path, monkeypatch):
    # Con la receta escrita, la voz ya no está «sin montar»: un fallo tiene que bloquear.
    canal = _copia_del_canal_activo(
        tmp_path, monkeypatch, retoca=lambda p: p["voz"].pop("palabras_por_segundo", None), con_receta=True
    )
    r = _por_nombre(comprueba_canal.comprueba(canal))
    assert r["ritmo de la voz (voz.palabras_por_segundo)"]["quien"] == "claude"
    monkeypatch.setenv("CANAL_ACTIVO", canal)
    assert comprueba_canal.main(["--canal", canal]) == 1


@pytest.mark.parametrize(("con_receta", "quien"), [(False, "voz"), (True, "claude")])
def test_un_fallo_de_voz_es_de_la_voz_sin_montar_solo_si_la_receta_no_existe(tmp_path, monkeypatch, con_receta, quien):
    from lib import voice_client

    fallo = [{"nombre": "receta de voz", "ok": False, "detalle": "no existe", "obligatorio": True}]
    monkeypatch.setattr(voice_client, "preflight", lambda: fallo)
    canal = _copia_del_canal_activo(tmp_path, monkeypatch, con_receta=con_receta)
    r = _por_nombre(comprueba_canal.comprueba(canal))
    assert r["receta de voz"]["quien"] == quien


def test_los_pasos_del_usuario_salen_aunque_falte_una_decision_del_perfil(tmp_path, monkeypatch):
    # Sin esto, un CANAL_ERROR hacía que la página dijera «nada pendiente» con el canal sin crear.
    canal = _copia_del_canal_activo(tmp_path, monkeypatch, retoca=lambda p: p["publicacion"].pop("canal_id"))
    monkeypatch.setattr(config, "CANAL_ERROR", "falta `imagen.seed`")
    r = _por_nombre(comprueba_canal.comprueba(canal))
    assert r["decisiones del canal sin defecto"]["ok"] is False
    assert r["canal creado"]["ok"] is False and r["canal creado"]["quien"] == "usuario"


def test_main_sale_con_1_si_falta_algo_del_repo(tmp_path, monkeypatch, capsys):
    canal = _copia_del_canal_activo(tmp_path, monkeypatch, sin=("ideas",))
    monkeypatch.setenv("CANAL_ACTIVO", canal)
    assert comprueba_canal.main(["--canal", canal]) == 1
    assert "faltan 1 del repo" in capsys.readouterr().out


def test_main_sale_con_0_si_solo_falta_lo_del_usuario(tmp_path, monkeypatch, capsys):
    def sin_canal_ni_token(perfil):
        perfil["publicacion"].pop("canal_id")
        perfil["publicacion"]["refresh_token_env"] = "TOKEN_QUE_NO_EXISTE"
        perfil["publicacion"]["verificado_por_telefono"] = True  # el tercer paso del usuario, ya dado

    canal = _copia_del_canal_activo(tmp_path, monkeypatch, retoca=sin_canal_ni_token)
    monkeypatch.setenv("CANAL_ACTIVO", canal)
    # El token solo se le pide con la subida por la API (OC1.8): a mano no es un paso pendiente.
    monkeypatch.setattr(config, "YOUTUBE_SUBIDA_API", "1")
    assert comprueba_canal.main(["--canal", canal]) == 0  # lo del usuario no depende del repo
    assert "faltan 0 del repo y 2 del usuario" in capsys.readouterr().out


def test_control_sin_contratos_se_caza(tmp_path, monkeypatch):
    canal = _copia_del_canal_activo(tmp_path, monkeypatch, contratos=False)
    r = _por_nombre(comprueba_canal.comprueba(canal))
    assert r["contrato-prompt-imagen.md"]["ok"] is False and r["contrato-miniatura.md"]["ok"] is False


def test_un_canal_sin_perfil_lo_dice_y_para(tmp_path, monkeypatch):
    monkeypatch.setattr(comprueba_canal, "RAIZ", tmp_path)
    (resultado,) = comprueba_canal.comprueba("C999-no-existe")
    assert resultado["nombre"] == "perfil.json" and resultado["ok"] is False


def test_la_pagina_escapa_y_solo_pide_al_usuario_lo_que_le_falta(tmp_path):
    resultados = [
        {"grupo": "YouTube", "nombre": "canal creado", "ok": True, "detalle": "UC123", "quien": "usuario"},
        {"grupo": "YouTube", "nombre": "token OAuth del canal", "ok": False, "detalle": "<script>x</script>",
         "quien": "usuario"},
        {"grupo": "YouTube", "nombre": "verificado por teléfono", "ok": False, "detalle": "falta", "quien": "usuario"},
    ]  # fmt: skip
    texto = comprueba_canal.pagina("C103", resultados, tmp_path / "alta.html").read_text(encoding="utf-8")
    assert "<script>x</script>" not in texto and "&lt;script&gt;" in texto
    assert "OAuth Playground" in texto and "youtube.com/verify" in texto
    assert "Crear el canal</b>" not in texto  # ya está creado: no se le pide


# ── canal.py --checklist con el canal todavía sin crear ─────────────────────────────────────────


def test_la_pagina_de_identidad_sale_con_el_canal_sin_crear(tmp_path):
    """Hasta que el usuario crea el canal, `handle` y `canal_id` valen `null`, y la página se caía con un
    `AttributeError` (primera ejecución real de la skill, 26-09-2026)."""
    from lib import canal_marca

    perfil = json.loads((RAIZ / "canales" / CANALES[0] / "perfil.json").read_text(encoding="utf-8"))
    perfil["publicacion"].update(handle=None, canal_id=None, canal_youtube=None)
    lista = canal_marca.checklist(perfil, {}, None, tmp_path)
    texto = canal_marca.pagina_del_checklist(lista, perfil, tmp_path).read_text(encoding="utf-8")
    assert "None" not in texto
    assert "studio.youtube.com/channel/UC" in texto  # Studio abre el canal que el usuario tenga elegido


# ── rejilla_de_marca ──────────────────────────────────────────────────────────────────────────


def _marca_de_prueba(raiz: Path, canal: str) -> None:
    from PIL import Image

    for nombre in ("banner/banner.png", "avatar/avatar.png"):
        destino = raiz / "canales" / canal / "marca" / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (400, 300), "white").save(destino)


def test_guardar_una_pasada_la_copia_fuera_de_marca_y_no_la_pisa(tmp_path):
    _marca_de_prueba(tmp_path, "C999")
    destino = rejilla_de_marca.guarda("C999", 11, "C999", raiz=tmp_path)
    assert (destino / "banner" / "banner.png").exists() and (destino / "avatar" / "avatar.png").exists()
    with pytest.raises(rejilla_de_marca.RejillaError, match="ya existe"):
        rejilla_de_marca.guarda("C999", 11, "C999", raiz=tmp_path)


def test_guardar_sin_haber_generado_para(tmp_path):
    with pytest.raises(rejilla_de_marca.RejillaError, match="genera antes"):
        rejilla_de_marca.guarda("C999", 11, "C999", raiz=tmp_path)


def test_la_rejilla_pone_cada_semilla_en_una_columna_y_dice_lo_que_falta(tmp_path):
    _marca_de_prueba(tmp_path, "C999")
    s11 = rejilla_de_marca.guarda("C999", 11, "C999", raiz=tmp_path)
    s22 = rejilla_de_marca.guarda("C999", 22, "C999", raiz=tmp_path)
    (s22 / "avatar" / "avatar.png").unlink()
    texto = rejilla_de_marca.rejilla([s11, s22], tmp_path / "rejilla.html").read_text(encoding="utf-8")
    assert texto.count("data:image/jpeg;base64,") == 3 and texto.count(">falta<") == 1
    assert "marca-C999-s11" in texto and "marca-C999-s22" in texto


# ── muestras_voz ──────────────────────────────────────────────────────────────────────────────


def test_una_voz_que_no_esta_en_la_cache_para_sin_crear_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(muestras_voz, "voces_en_cache", lambda: ["am_onyx", "bm_lewis"])
    monkeypatch.setattr(config, "VOICE_CACHE_DIR", tmp_path)
    with pytest.raises(muestras_voz.MuestrasError, match="zz_nadie"):
        muestras_voz._prepara(["am_onyx+zz_nadie"], "hola", "a", 1.0, "C103")
    assert not (tmp_path / "muestras").exists()


def test_la_pagina_de_voces_tiene_un_reproductor_por_voz(tmp_path):
    (tmp_path / "trabajo.json").write_text(json.dumps({"texto": "<b>hola</b>", "lang_code": "a", "speed": 1.0}))
    (tmp_path / "resultado.json").write_text(
        json.dumps([{"voz": v, "fichero": f"{v}.wav", "segundos": 20.0, "wpm": 150.0} for v in ("am_onyx", "bm_lewis")])
    )
    texto = muestras_voz.pagina(tmp_path, "C103").read_text(encoding="utf-8")
    assert texto.count("<audio") == 2 and "&lt;b&gt;hola" in texto


# ── cata_ritmo ────────────────────────────────────────────────────────────────────────────────


def test_la_cata_se_niega_con_un_parrafo_corto_antes_de_gastar_gpu(tmp_path, monkeypatch):
    # Dentro del proceso y con la voz sustituida: si alguien quitara la guarda, esta prueba no puede
    # arrancar llama-server ni Orpheus en la GPU (auditoría de F5.15), falla sin más.
    from lib import voice_client

    def no_gasta_gpu(*_a, **_k):
        raise AssertionError("la cata llegó a narrar: la guarda de palabras no paró")

    monkeypatch.setattr(voice_client, "generate_tts", no_gasta_gpu)
    monkeypatch.setenv("CANAL_ACTIVO", config.CANAL_ACTIVO)
    parrafo = tmp_path / "p.txt"
    parrafo.write_text("Money is a story we agree to believe.", encoding="utf-8")
    with pytest.raises(SystemExit, match="palabras"):
        cata_ritmo.main(["--canal", config.CANAL_ACTIVO, "--texto-de", str(parrafo)])
