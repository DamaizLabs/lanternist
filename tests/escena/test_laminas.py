"""El formato «láminas» (F6.8): el reparto de tomas y movimientos es el del motor viejo, número a número.

La prueba fuerte es el capítulo publicado de la pera: con sus láminas y sus fotogramas, el planificador nuevo tiene que
dar los mismos 100 planos que montó `lib/motion.py` el 16-09 (`datos/pera-publicada.json`). Hasta F6.7 se comparaba
además con `lib/motion.py` en directo, con otras duraciones; aquel motor se retiró y este planificador es ya su única
copia, así que lo que lo ata al publicado es el plan guardado.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.escena import laminas as lam

PERA = json.loads((Path(__file__).parent / "datos" / "pera-publicada.json").read_text(encoding="utf-8"))
# Los valores con los que se montó: los de lib/config.py de entonces y el MOTION_SEGUNDOS_TRANSICION=2.0 del .env.
AJUSTES = {
    "zoom_base": 1.06,
    "zoom_maximo": 1.45,
    "toma_s": 10,
    "toma_minima_s": 5,
    "transicion_s": 2.0,
    "transiciones_excluidas": ["plate_reveal"],
    # OC1.2: no cambia el reparto; las del canal de ejemplo, de la biblioteca del estudio.
    "fuentes_de_los_rotulos": {
        "redonda": "Gelasio-VariableFont_wght.ttf",
        "cursiva": "Gelasio-Italic-VariableFont_wght.ttf",
    },
}


def plan(titulo=PERA["titulo"], excluidas=("plate_reveal",), fotogramas=None):
    a = lam.ajustes({"laminas": {**AJUSTES, "transiciones_excluidas": list(excluidas)}})
    laminas = [
        lam.Lamina(x["numero"], fotogramas[i] if fotogramas else x["fotogramas"], x["image_prompt"])
        for i, x in enumerate(PERA["laminas"])
    ]
    return lam.planifica(laminas, clave_del_video=titulo, fps=24, ajustes_=a)


def resumen(t: lam.Toma) -> dict:
    return {
        "slide": t.lamina,
        "movimiento": t.movimiento,
        "easing": t.curva,
        "zoom": [round(t.zoom[0], 4), round(t.zoom[1], 4)],
        "focal": [[round(v, 4) for v in t.foco[0]], [round(v, 4) for v in t.foco[1]]],
        "segundos": round(t.fotogramas / 24, 3),
        "transicion_entrada": t.transicion,
    }


def test_reproduce_los_100_planos_del_capitulo_publicado():
    tomas = plan()
    assert len(tomas) == len(PERA["planos"]) == 100
    distintos = [(i, resumen(t), p) for i, (t, p) in enumerate(zip(tomas, PERA["planos"])) if resumen(t) != p]
    assert not distintos, distintos[:3]


def test_control_negativo_otro_titulo_da_otro_montaje():
    otro = [resumen(t) for t in plan(titulo="Otro título")]
    assert sum(a != b for a, b in zip(otro, PERA["planos"])) > 50


def test_tachar_una_transicion_solo_cambia_las_tomas_a_las_que_les_tocaba():
    con, sin = plan(), plan(excluidas=())
    cambian = [i for i, (a, b) in enumerate(zip(con, sin)) if a != b]
    assert cambian and all(sin[i].transicion == "plate_reveal" for i in cambian)
    assert all(t.transicion != "plate_reveal" for t in con)


def test_el_foco_nunca_deja_ver_el_margen_de_la_lamina():
    for t in plan():
        for z, (fx, fy) in zip(t.zoom, t.foco):
            medio = (1 / AJUSTES["zoom_base"] - 1 / z) / 2
            assert abs(fx - 0.5) <= medio + 1e-9 and abs(fy - 0.5) <= medio + 1e-9


def test_la_cola_prolonga_el_movimiento_sin_salir_del_margen():
    a = lam.ajustes({"laminas": AJUSTES})
    for t in plan()[:20]:
        zoom, foco = lam.prolonga(t, 48, a)
        assert zoom[0] == t.zoom[0] and AJUSTES["zoom_base"] <= zoom[1] <= AJUSTES["zoom_maximo"]
        # Va más lejos que la toma, salvo contra el techo o contra el zoom base (un alejamiento que acaba en él).
        assert abs(zoom[1] - t.zoom[0]) >= abs(t.zoom[1] - t.zoom[0]) - 1e-9
        medio = (1 / AJUSTES["zoom_base"] - 1 / zoom[1]) / 2
        assert all(abs(v - 0.5) <= medio + 1e-9 for v in foco[1])


def test_el_foco_pasa_a_px_del_fondo_recortando_la_lamina_al_marco():
    marco = {"w": 1920, "h": 1080}
    # La lámina ampliada del primer canal, 2688×1536, es más alta que 16:9: el motor viejo recortaba 12 px arriba
    # y abajo.
    assert lam.en_la_lamina((0.5, 0.5), 2688, 1536, marco) == (1344, 768)
    assert lam.en_la_lamina((0, 0), 2688, 1536, marco) == pytest.approx((0, 12))
    assert lam.en_la_lamina((1, 1), 2688, 1536, marco) == pytest.approx((2688, 1524))
    # Y una más ancha que el marco recorta los lados.
    assert lam.en_la_lamina((0, 0.5), 2400, 1080, marco) == pytest.approx((240, 540))


@pytest.mark.parametrize(
    "bloque, dice",
    [
        (None, "no declara `escena.laminas`"),
        ({k: v for k, v in AJUSTES.items() if k != "transicion_s"}, "transicion_s"),
        ({**AJUSTES, "zoom_base": 1.0}, "mayor que 1"),
        ({**AJUSTES, "transiciones_excluidas": ["plate_revael"]}, "no existen"),
        ({**AJUSTES, "transiciones_excluidas": list(lam.SUAVES)}, "suave"),
        ({**AJUSTES, "toma_s": True}, "número positivo"),
        ({k: v for k, v in AJUSTES.items() if k != "fuentes_de_los_rotulos"}, "fuentes_de_los_rotulos"),
        ({**AJUSTES, "fuentes_de_los_rotulos": {}}, "al menos una fuente"),
        ({**AJUSTES, "fuentes_de_los_rotulos": "Gelasio-VariableFont_wght.ttf"}, "papel: fichero"),
        ({**AJUSTES, "fuentes_de_los_rotulos": {"redonda": ""}}, "papel: fichero"),
    ],
)
def test_los_ajustes_del_canal_no_tienen_defecto(bloque, dice):
    with pytest.raises(lam.ErrorDeLaminas, match=dice):
        lam.ajustes({} if bloque is None else {"laminas": bloque})


# ------------------------------------------------------------------------------------------ las fuentes de los rótulos
CSS_GELASIO = (
    "@font-face { font-family: r; src: url(assets/fuentes/Gelasio-VariableFont_wght.ttf); } "
    "@font-face { font-family: c; src: url(assets/fuentes/Gelasio-Italic-VariableFont_wght.ttf); }"
)


def test_el_canal_de_ejemplo_declara_las_fuentes_de_sus_rotulos_y_salen_de_la_biblioteca():
    """OC1.2: la fuente de los rótulos la declara el perfil (F4.9), es libre y entra en el run con su licencia."""
    from lib import config
    from lib.escena import audio

    perfil = json.loads((config.BASE_DIR / "canales" / "example" / "perfil.json").read_text(encoding="utf-8"))
    a = lam.ajustes(perfil["escena"])
    rutas = lam.fuentes_de_los_rotulos(a, CSS_GELASIO)
    assert set(rutas) == {"redonda", "cursiva"} and all(r.parent == config.ESCENA_FUENTES_DIR for r in rutas.values())
    creditos = audio.lee_creditos(config.ESCENA_FUENTES_DIR)
    for ruta in rutas.values():
        assert creditos[ruta.name]["licencia"].startswith("SIL Open Font License")
        assert (config.ESCENA_FUENTES_DIR / creditos[ruta.name]["texto_de_la_licencia"]).is_file()


@pytest.mark.parametrize(
    ("fuentes", "css", "dice"),
    [
        (
            {"redonda": "georgia.ttf"},
            "@font-face { src: url(assets/fuentes/georgia.ttf); }",
            "no está en la biblioteca",
        ),
        ({"redonda": "Gelasio-VariableFont_wght.ttf"}, ".tinta { fill: none; }", "no declara la fuente"),
    ],
)
def test_control_una_fuente_de_windows_o_que_el_css_no_declara_para(fuentes, css, dice):
    a = lam.ajustes({"laminas": {**AJUSTES, "fuentes_de_los_rotulos": fuentes}})
    with pytest.raises(lam.ErrorDeLaminas, match=dice):
        lam.fuentes_de_los_rotulos(a, css)
