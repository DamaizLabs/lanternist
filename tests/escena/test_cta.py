"""El CTA del estudio (F6.8, fila 236): el banner con su campana que se balancea y suena, igual en todo canal."""

from __future__ import annotations

import re

import pytest
from utiles_escena import CATALOGO_PRUEBA, escena_prueba

from lib.escena import compone, cta
from lib.escena.escena import Guion

GEOMETRIA = {"banner": {"w": 1000, "h": 400}, "campana": {"x": 800, "y": 40, "w": 100, "h": 200}}


def _guion() -> Guion:
    return Guion(titulo="Prueba", idioma="en", escena=escena_prueba(), catalogo=CATALOGO_PRUEBA, iconos={})


def _pon(g: Guion, **cambios):
    kw = dict(banner_src="assets/cta/b.png", campana_src="assets/cta/c.png", geometria=GEOMETRIA, centro=(960, 300),
              tamano=(600, 240), t0=10.0, t1=30.0, t_campana=15.0, t_clic=12.0)  # fmt: skip
    return cta.pon(g, **{**kw, **cambios})


def test_el_banner_entra_con_rebote_late_y_su_campana_se_balancea_desde_bell():
    g = _guion()
    e = _pon(g)
    assert (e.t0, e.t1, e.x + e.w / 2, e.y + e.h / 2) == (10.0, 30.0, 960, 300)
    assert e.anim == {"entra": "pop", "sale": "nada", "bucle": "late", "amp": cta.LATIDO, "di": cta.ENTRA_S,
                      "campana": True, "campana_t": 15.0, "campana_p": cta.PERIODO_CAMPANA}  # fmt: skip
    # La campana va en su sitio dentro del banner, en % de él, y gira desde su asa (lo pone el CSS del estudio).
    assert 'class="cta-campana campana"' in e.html
    assert "left:80.000%;top:10.000%;width:10.000%;height:50.000%" in e.html


def test_suena_el_clic_y_la_campana_cada_periodo_hasta_antes_del_final():
    g = _guion()
    _pon(g)
    assert g.sonidos[0] == {"nombre": "click-soft", "t": 12.0, "vol": 0.6}
    campanadas = g.sonidos[1:]
    # Cada 4,5 s desde «bell» (15 s), y la de 28,5 s ya no: cae a menos de 1,5 s del final (30 s).
    assert [s["t"] for s in campanadas] == [15.0, 19.5, 24.0]
    assert {s["nombre"] for s in campanadas} == {"notification"}
    assert [s["vol"] for s in campanadas] == [0.35] + [0.25] * (len(campanadas) - 1)


@pytest.mark.parametrize("cambio", [{"t_campana": 31.0}, {"t_campana": 9.0}, {"t_clic": 30.0}, {"t_clic": 5.0}])
def test_una_campana_o_un_clic_fuera_del_banner_para(cambio):
    with pytest.raises(ValueError, match="fuera del banner"):
        _pon(_guion(), **cambio)


def test_compone_pone_la_estructura_del_cta_solo_si_la_pagina_lo_lleva():
    from utiles_escena import CSS_PRUEBA, guion_min

    g = guion_min()
    sin = compone.pagina(g, CSS_PRUEBA.read_text(encoding="utf-8"))
    assert ".cta-campana { transform-origin" not in sin  # control: sin CTA no va
    g["elementos"][0]["html"] = cta.caja("assets/img/fondo.png", "assets/img/fondo.png", GEOMETRIA)
    con = compone.pagina(g, CSS_PRUEBA.read_text(encoding="utf-8"))
    assert cta.CSS in con
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b|rgba?\(", cta.CSS)  # sin colores: la sombra es del canal


def test_en_pantalla_centra_el_banner_con_el_ancho_y_el_margen_del_canal():
    """La cuenta que hacía el motor de láminas (subida del primer canal al estudio en F7.10): con el banner de dos
    canales del estudio, 30 % del marco y 340 px de margen, el banner mide 576 × 198 y su borde de abajo queda en y =
    740."""
    banner = {"banner": {"w": 6346, "h": 2191}, "en_pantalla": {"ancho_pct": 30, "margen_inferior_px": 340}}
    x, y, w, h = cta.en_pantalla(banner, {"w": 1920, "h": 1080})
    assert (x, y, w, h) == (960, 641, 576, 198) and y + h / 2 == 1080 - 340


def test_control_un_banner_que_se_sale_por_arriba_para():
    banner = {"banner": {"w": 1000, "h": 1000}, "en_pantalla": {"ancho_pct": 80, "margen_inferior_px": 100}}
    with pytest.raises(ValueError, match="se sale del marco por arriba"):
        cta.en_pantalla(banner, {"w": 1920, "h": 1080})
