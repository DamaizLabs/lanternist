"""La tinta que escribe (F6.8): las letras de una fuente como contornos que el motor dibuja (`lib/escena/tinta.py`).

Con las fuentes de la biblioteca del estudio, que viajan en el repositorio con su licencia (OC1.2): Gelasio, la de los
rótulos del canal de ejemplo, y Patrick Hand SC, la única con versalitas. Hasta OC1.2 era Georgia, leída de Windows, y
las pruebas se saltaban donde no estaba.
"""

from __future__ import annotations

import re

import pytest

from lib import config
from lib.escena import compone, tinta

GELASIO = config.ESCENA_FUENTES_DIR / "Gelasio-VariableFont_wght.ttf"
PATRICK = config.ESCENA_FUENTES_DIR / "PatrickHandSC-Regular.ttf"
CSS_GELASIO = "@font-face { font-family: rotulo; src: url('assets/fuentes/Gelasio-VariableFont_wght.ttf'); }"


def linea(texto, tam=92, espaciado=0.0, versalitas=False, fuente=GELASIO):
    return tinta.compone_linea(texto, fuente, tam, espaciado_px=espaciado, versalitas=versalitas)


def test_cada_letra_lleva_sus_contornos_y_los_espacios_no_llevan_tinta():
    ln = linea("lo i")
    assert [x.caracter for x in ln.letras] == ["l", "o", "i"]
    # La «l» es un contorno; la «o», el de fuera y el del ojo; la «i», el palo y el punto.
    assert [len(x.contornos) for x in ln.letras] == [1, 2, 2]
    assert all(c.startswith("M") for x in ln.letras for c in x.contornos)


def test_una_letra_compuesta_se_descompone_en_sus_contornos():
    """La «i», la «j» y los dos puntos de Gelasio son glifos compuestos (palo + punto): cada pieza es su trazo."""
    ln = linea("ij:")
    assert [len(x.contornos) for x in ln.letras] == [2, 2, 2]
    assert len(set(ln.letras[0].contornos)) == 2, "el palo y el punto son dos trazos distintos"


def test_las_letras_avanzan_y_el_espaciado_se_suma_entre_caracteres_no_detras_del_ultimo():
    sin, con = linea("The Pear"), linea("The Pear", espaciado=10)
    xs = [x.x for x in sin.letras]
    assert xs == sorted(xs) and len(set(xs)) == len(xs)
    # 8 caracteres, espacio incluido: 7 espaciados entre ellos.
    assert con.ancho == pytest.approx(sin.ancho + 7 * 10)


def test_las_versalitas_salen_de_la_funcion_smcp_de_la_fuente():
    # Patrick Hand SC tiene `smcp`, pero solo para las cifras y algún signo: sus minúsculas ya son versalitas.
    assert tinta._versalitas(str(PATRICK))["one"] == "one.smcp"
    # Ninguna fuente de la biblioteca lleva versalitas de letras (Georgia sí, y era de Windows): se prueba el mecanismo
    # con una función `smcp` que lleva la «a» a la «A» (la prueba siguiente).


def test_una_minuscula_en_versalitas_se_escribe_con_el_glifo_que_da_smcp(monkeypatch):
    monkeypatch.setattr(tinta, "_versalitas", lambda ruta: {"a": "A"})
    assert linea("a", versalitas=True).letras[0].contornos == linea("A").letras[0].contornos
    assert linea("a", versalitas=True).letras[0].contornos != linea("a").letras[0].contornos
    # Control: una minúscula que esa función no lleva a su versalita para, con su nombre.
    with pytest.raises(tinta.ErrorDeTinta, match="no tiene la versalita de «b»"):
        linea("ab", versalitas=True)


def test_control_una_fuente_sin_versalitas_para_en_vez_de_inventarlas():
    with pytest.raises(tinta.ErrorDeTinta, match="no tiene versalitas"):
        linea("a", versalitas=True)


def test_el_interletraje_se_lee_de_la_tabla_kern_y_un_par_sin_ajuste_no_se_mueve():
    # Gelasio solo ajusta la «L» seguida del punto volado catalán (l·l): −300 unidades de 2048.
    assert tinta._ajuste(str(GELASIO), "L", "periodcentered.loclCAT") == -300
    # Control: el punto volado de siempre no tiene ajuste.
    assert tinta._ajuste(str(GELASIO), "L", "periodcentered") == 0


def test_el_interletraje_se_aplica_entre_letras_y_no_tras_un_espacio(monkeypatch):
    sin = linea("Ta b", tam=2048)
    monkeypatch.setattr(tinta, "_ajuste", lambda ruta, a, b: -100.0)
    con = linea("Ta b", tam=2048)
    # «T»→«a» se ajusta; «a»→espacio no, y tras el espacio tampoco (`anterior` vuelve a None).
    assert con.ancho == pytest.approx(sin.ancho - 100)
    assert con.letras[1].x == pytest.approx(sin.letras[1].x - 100)


def test_una_letra_que_la_fuente_no_tiene_para_con_su_nombre():
    with pytest.raises(tinta.ErrorDeTinta, match="U\\+6F22"):
        linea("The 漢")
    with pytest.raises(tinta.ErrorDeTinta, match="no hay texto"):
        linea("   ")


def test_parte_en_lineas_como_el_navegador_y_para_si_una_palabra_no_cabe():
    entera = linea("The Museum Piece With No Medieval Past", tam=36)
    lineas = tinta.parte_en_lineas(
        "The Museum Piece With No Medieval Past", entera.ancho / 2, GELASIO, 36, espaciado_px=0, versalitas=False
    )
    assert len(lineas) >= 2 and all(x.ancho <= entera.ancho / 2 for x in lineas)
    assert " ".join(x.texto for x in lineas) == entera.texto
    with pytest.raises(tinta.ErrorDeTinta, match="no cabe"):
        tinta.parte_en_lineas("Anguish", 50, GELASIO, 92, espaciado_px=0, versalitas=False)


def test_el_trazo_va_normalizado_a_la_longitud_que_dibuja_el_motor():
    ln = linea("o")
    svg = tinta.trazo_svg(ln.letras[0], (400, 200), (10, 120), "tinta titulo")
    assert svg.count('class="trazo"') == 2
    assert svg.count(f'pathLength="{tinta.LARGO_DEL_TRAZO}"') == 2
    # El motor lleva el trazo de 1000 a 0 con el `stroke-dasharray` del CSS del estudio: tienen que ser el mismo.
    assert re.search(r"\.el \.trazo \{ stroke-dasharray: (\d+); \}", compone.CSS_ESTUDIO).group(1) == str(
        tinta.LARGO_DEL_TRAZO
    )
    relleno = tinta.relleno_svg(ln.letras[0], (400, 200), (10, 120), "tinta titulo")
    assert relleno.count("<path") == 1 and 'class="relleno"' in relleno and "trazo" not in relleno


def test_el_texto_no_llega_a_la_pagina_solo_sus_contornos():
    # Un título es un dato (A-9): ni sus caracteres ni su marcado llegan al SVG.
    ln = linea("<b>&</b>")
    svgs = "".join(tinta.trazo_svg(x, (900, 200), (0, 120), "tinta") for x in ln.letras)
    assert "<b>" not in svgs and "&" not in svgs
    assert set(re.findall(r"<(\w+)", svgs)) == {"svg", "g", "path"}


# ------------------------------------------------------------------------------------------ de dónde sale la fuente
def test_la_fuente_sale_de_la_biblioteca_si_el_css_del_canal_la_declara():
    assert tinta.fuente_de_la_biblioteca(GELASIO.name, CSS_GELASIO) == GELASIO


@pytest.mark.parametrize(
    ("nombre", "css", "dice"),
    [
        ("georgia.ttf", "@font-face { src: url(assets/fuentes/georgia.ttf); }", "no está en la biblioteca"),
        ("../sfx/CREDITOS.json", "", "no está en la biblioteca"),
        ("", "", "no está en la biblioteca"),
        (GELASIO.name, ".tinta { fill: none; }", "no declara la fuente"),
    ],
)
def test_control_una_fuente_del_sistema_o_sin_declarar_en_el_css_para(nombre, css, dice):
    """Georgia (de Windows) ya no se puede leer: no tiene procedencia ni se puede redistribuir (OC1.2)."""
    with pytest.raises(tinta.ErrorDeTinta, match=dice):
        tinta.fuente_de_la_biblioteca(nombre, css)


def test_la_tinta_ya_no_lee_fuentes_de_windows():
    assert not hasattr(tinta, "fuente_del_sistema")
    assert "WINDIR" not in (config.BASE_DIR / "lib" / "escena" / "tinta.py").read_text(encoding="utf-8")
