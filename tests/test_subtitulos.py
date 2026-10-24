"""Lo que se queda de los subtítulos del estudio: el reparto del canal y el `.srt` (F2.13, F6.7).

Correr: .venv\\Scripts\\python -m pytest -q tests/test_subtitulos.py

Las pruebas del karaoke quemado —la ruta larga de Windows que rompía `libass`, el BOM del `.ass`, el
relleno `\\k` de cada línea, los colores por personaje y el corte de las líneas que no cabían— salieron
con él el 02-10-2026 (F6.7). Su historia está en el addendum de `doc/02-decisiones-tecnicas.md`
(filas 74 y 83) y en `progress/impl_F2.13.md`. Lo que queda aquí es lo que el motor de escena usa
para escribir el `.srt`, que son también las correcciones que encontró aquel auditor.
"""

import pytest

from lib import alineacion, subtitulos


def _palabras(pares):
    return [{"palabra": w, "desde": a, "hasta": b, "anclada": True} for w, a, b in pares]


def test_el_canal_tiene_que_declarar_su_reparto():
    """F4.9: sin defecto. Heredar el reparto de otro canal pintaría a personajes que no existen."""
    import lib.subtitulos as modulo

    original = modulo.CANAL_PERFIL
    try:
        modulo.CANAL_PERFIL = {"subtitulos": {"activos": True}}
        with pytest.raises(subtitulos.SubtitulosError, match="personajes"):
            modulo.personajes()
        modulo.CANAL_PERFIL = {"subtitulos": {"personajes": {}}}
        assert modulo.personajes() == {}, "un canal sin diálogos declara {} y eso es una respuesta"
        modulo.CANAL_PERFIL = {"subtitulos": {"personajes": {"Ollie": {"color": "azul"}}}}
        with pytest.raises(subtitulos.SubtitulosError, match="hexadecimal"):
            modulo.personajes()
    finally:
        modulo.CANAL_PERFIL = original


# --- solapes ---------------------------------------------------------------------------------


def _dos_lineas(fin_a, inicio_b):
    a = _palabras([("uno", 0.0, 0.4), ("dos", 0.5, fin_a)])
    b = _palabras([("tres", inicio_b, inicio_b + 0.4)])
    return [(a, 0.0), (b, 0.0)]


def test_una_linea_termina_cuando_empieza_la_siguiente():
    """El episodio 1 quemó 3 pares encimados, de 0,05 a 0,30 s: dos textos a la vez en pantalla."""
    lineas = _dos_lineas(fin_a=1.20, inicio_b=1.00)
    assert subtitulos.recorta_solapes(lineas) == 1
    assert lineas[0][0][-1]["hasta"] == pytest.approx(1.00)


def test_dos_lineas_CRUZADAS_se_arreglan_empujando_la_segunda():
    """`Biscuit sat down.` / `He looked very happy.`: la segunda empezaba ANTES que la primera.

    Ahí no sobra el final de la primera —el alineador ancló mal el principio de la segunda—, así que
    recortar la primera dejaba el solape intacto y además la reducía a 0,1 s de parpadeo.
    """
    lineas = _dos_lineas(fin_a=1.20, inicio_b=-0.30)
    assert subtitulos.recorta_solapes(lineas) == 1
    assert lineas[1][0][0]["desde"] == pytest.approx(1.20), "la segunda arranca donde acaba la primera"
    assert lineas[0][0][-1]["hasta"] == pytest.approx(1.20), "y la primera conserva su duración"


def test_sin_solape_NO_se_toca_nada():
    """Control negativo: si recortara siempre, movería 196 líneas para arreglar 3."""
    lineas = _dos_lineas(fin_a=1.00, inicio_b=1.20)
    assert subtitulos.recorta_solapes(lineas) == 0
    assert lineas[0][0][-1]["hasta"] == pytest.approx(1.00)


def test_el_reparto_tiene_que_declarar_el_pronombre_de_cada_personaje():
    """Sin él no se puede atribuir «"I know," she said», y es del canal: el estudio no sabe quién es Nora."""
    import lib.subtitulos as modulo

    original = modulo.CANAL_PERFIL
    try:
        modulo.CANAL_PERFIL = {"subtitulos": {"personajes": {"Nora": {"color": "#3E9E5B"}}}}
        with pytest.raises(subtitulos.SubtitulosError, match="pronombre"):
            modulo.personajes()
        modulo.CANAL_PERFIL = {"subtitulos": {"personajes": {"Nora": {"color": "#3E9E5B", "pronombre": "she"}}}}
        assert modulo.personajes()["Nora"]["pronombre"] == "she"
    finally:
        modulo.CANAL_PERFIL = original


def test_recortar_NUNCA_deja_una_linea_en_un_parpadeo():
    """«Biscuit went with them.» duró 50 ms en el montaje del 05-09, y lo cazó el auditor.

    El solape era tan grande que recortar la primera línea la dejaba sin tiempo de leerse. Cuando
    pasa eso, lo que se mueve es la línea siguiente, igual que en el caso de las cruzadas.
    """
    lineas = _dos_lineas(fin_a=1.20, inicio_b=0.10)
    assert subtitulos.recorta_solapes(lineas) == 1
    duracion = lineas[0][0][-1]["hasta"] - lineas[0][0][0]["desde"]
    assert duracion >= subtitulos.DURACION_MINIMA_S, f"la línea se quedó en {duracion:.2f}s"
    assert lineas[1][0][0]["desde"] == pytest.approx(1.20), "la que se mueve es la siguiente"


# --- cuando el alineador se pierde (`lib/alineacion.py`, que lo hace para el `.srt` y el karaoke) ----------


def test_las_palabras_sin_marca_se_reparten_el_hueco():
    """En el segundo 58 del montaje del 05-09, whisper dejó nueve palabras en el MISMO instante.

    En pantalla: una línea de 0 s que parpadea y el relleno parado casi seis segundos sobre la
    siguiente. Repartir no inventa sincronía —no la hay—, pero convierte el parpadeo en un karaoke
    que avanza mientras se oyen esas palabras.
    """
    alineado = _palabras([("uno", 0.0, 0.50), ("dos", 0.50, 0.50), ("tres", 0.50, 0.50), ("cuatro", 2.50, 3.00)])
    assert alineacion.reparte_tiempos_colapsados(alineado) == 2
    assert alineado[1]["desde"] == pytest.approx(0.50)
    assert alineado[2]["hasta"] == pytest.approx(2.50)
    for palabra in alineado:
        assert palabra["hasta"] - palabra["desde"] >= alineacion.DURACION_MINIMA_PALABRA_S


def test_las_marcas_CRUZADAS_se_ordenan():
    """`down` empezaba antes que `They`, y dos palabras cruzadas enciman dos líneas."""
    alineado = _palabras([("They", 0.55, 0.60), ("down", 0.23, 0.49)])
    alineacion.reparte_tiempos_colapsados(alineado)
    assert alineado[1]["desde"] >= alineado[0]["hasta"]


def test_una_alineacion_SANA_no_se_toca():
    """Control negativo: si repartiera siempre, destruiría la sincronía que el alineador sí acierta."""
    alineado = _palabras([("uno", 0.0, 0.40), ("dos", 0.45, 0.90), ("tres", 1.00, 1.50)])
    copia = [dict(p) for p in alineado]
    assert alineacion.reparte_tiempos_colapsados(alineado) == 0
    assert alineado == copia


# --- La línea que parpadea: el caso de «birthday!"» (15-09-2026) ---------------------------------
#
# `recorta_solapes` vigila el SOLAPE, no la duración, así que una línea puede quedarse en nada sin
# que nadie la toque mientras no pise a la vecina. En el episodio de un canal, la última palabra del
# grito de Ollie se quedó con **0,06 s** detrás de una línea de 8,3 s, y pareció que el motor de
# voz se había comido la palabra: en el audio está, entre los segundos 60,3 y 63,3.


def test_una_linea_de_parpadeo_se_alarga_robando_a_la_anterior():
    larga = _palabras([("Ollie", 0.0, 4.0), ("shouted", 4.0, 8.30)])
    corta = _palabras([('birthday!"', 8.30, 8.36)])
    lineas = [(larga, 0.0), (corta, 0.0)]

    assert subtitulos.estira_lineas_cortas(lineas) == 1
    duracion = lineas[1][0][-1]["hasta"] - lineas[1][0][0]["desde"]
    assert duracion == pytest.approx(subtitulos.DURACION_MINIMA_S), "la corta llega al mínimo"
    assert lineas[0][0][-1]["hasta"] == pytest.approx(lineas[1][0][0]["desde"]), "y no se solapan"


def test_si_a_la_anterior_NO_le_sobra_no_se_le_roba():
    """Control negativo: robarle a una línea que ya está en el límite crea el defecto contrario."""
    justa = _palabras([("uno", 0.0, subtitulos.DURACION_MINIMA_S)])
    corta = _palabras([("dos", subtitulos.DURACION_MINIMA_S, subtitulos.DURACION_MINIMA_S + 0.06)])
    lineas = [(justa, 0.0), (corta, 0.0)]

    assert subtitulos.estira_lineas_cortas(lineas) == 0
    assert lineas[0][0][-1]["hasta"] == pytest.approx(subtitulos.DURACION_MINIMA_S)


def test_las_lineas_que_ya_duran_lo_suficiente_NO_se_tocan():
    """Segundo control negativo: sin él, «pasa» no distingue arreglar de mover todo."""
    lineas = _dos_lineas(fin_a=1.00, inicio_b=1.20)
    assert subtitulos.estira_lineas_cortas(lineas) == 0
    assert lineas[1][0][0]["desde"] == pytest.approx(1.20)
