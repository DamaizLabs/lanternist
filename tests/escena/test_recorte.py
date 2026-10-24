"""El núcleo del obrero de activos, sin GPU (F6.2c): croma, figuras, apoyo, catálogo, cabeza y máscara de SAM.

Cada comprobación lleva su control negativo: la versión rota a propósito de lo que se prueba tiene que fallar, para
que «pasa» signifique «funciona» y no «la prueba no sabe fallar». Las imágenes son sintéticas y pequeñas
(`utiles_activos.py`); lo mismo contra las imágenes reales de video_1 está medido en
`experimentos/motor-escena/f62c-real/` (informe de F6.2c).
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from utiles_activos import CUERPO, NEGRO_TENIDO, fondo_de_croma, persona

from lib.escena import recorte

RAIZ = Path(__file__).resolve().parents[2]


def _figura_sobre_croma(**extra) -> np.ndarray:
    """Un cuerpo naranja de 40×80 sobre croma con degradado, en una imagen de 120×140."""
    im = fondo_de_croma(120, 140)
    d = ImageDraw.Draw(im)
    d.rectangle([40, 30, 79, 109], fill=CUERPO)
    for caja, color in extra.get("manchas", []):
        d.rectangle(caja, fill=color)
    return np.asarray(im).astype(np.float32)


# ------------------------------------------------------------------------------------------ el fondo de croma
def test_el_fondo_de_croma_se_vuelve_transparente_y_la_figura_no():
    rgba = recorte.quita_magenta(_figura_sobre_croma())
    assert rgba[5, 5, 3] == 0 and rgba[130, 110, 3] == 0, "el fondo, con su degradado, tiene que quedar transparente"
    assert (rgba[40:100, 50:70, 3] == 255).all(), "el interior de la figura tiene que quedar opaco"


def test_la_sombra_de_croma_apagado_que_toca_el_borde_es_fondo():
    """La viñeta y las sombras: croma apagado (saturación 0,25) que llega al borde de la imagen."""
    rgba = recorte.quita_magenta(_figura_sobre_croma(manchas=[([0, 110, 119, 139], (150, 110, 150))]))
    assert (rgba[120:140, 0:30, 3] == 0).all()


def test_lo_negro_tenido_de_croma_no_se_toma_por_fondo():
    """El caso de video_1: la bomba negra de un personaje se volvía transparente porque Qwen le corrió croma."""
    rgba = recorte.quita_magenta(_figura_sobre_croma(manchas=[([50, 50, 69, 69], NEGRO_TENIDO)]))
    assert (rgba[52:68, 52:68, 3] == 255).all()


def test_control_con_el_umbral_viejo_lo_negro_tenido_se_pierde(monkeypatch):
    """Reproduce el fallo a propósito: con el brillo mínimo de antes (0,1), el negro teñido desaparece."""
    monkeypatch.setattr(recorte, "OSCURO", 0.1)
    rgba = recorte.quita_magenta(_figura_sobre_croma(manchas=[([50, 50, 69, 69], NEGRO_TENIDO)]))
    assert (rgba[52:68, 52:68, 3] == 0).all()


def test_control_y_un_croma_con_brillo_dentro_de_la_figura_si_es_fondo():
    """El otro lado del umbral: el mismo tono con brillo es un hueco (entre los dedos) y queda transparente."""
    rgba = recorte.quita_magenta(_figura_sobre_croma(manchas=[([50, 50, 69, 69], (200, 40, 200))]))
    assert (rgba[54:66, 54:66, 3] == 0).all()


def test_una_mota_de_croma_dentro_de_la_figura_es_ruido_y_no_hueco():
    rgba = recorte.quita_magenta(_figura_sobre_croma(manchas=[([55, 55, 56, 56], recorte.CROMA)]))
    assert rgba[55, 55, 3] == 255, "4 px de croma dentro de la figura no son un hueco"
    rgba = recorte.quita_magenta(_figura_sobre_croma(manchas=[([55, 55, 60, 60], recorte.CROMA)]))
    assert rgba[57, 57, 3] == 0, "control: 36 px sí son un hueco"


def test_el_borde_se_descontamina_de_croma():
    """Un píxel de borde con un poco de croma mezclado sale semitransparente y con el color de la figura, no rosa.

    Control: el mismo color dentro de la figura, lejos del fondo, no se toca (la franja es solo el borde).
    """
    gris = np.array([100.0, 100.0, 100.0])
    im = fondo_de_croma(120, 140)
    ImageDraw.Draw(im).rectangle([40, 30, 79, 109], fill=(100, 100, 100))
    rgb = np.asarray(im).astype(np.float32)
    mezcla = 0.93 * gris + 0.07 * rgb[60, 20]
    rgb[60, 40] = mezcla
    rgb[60, 60] = mezcla
    rgba = recorte.quita_magenta(rgb)
    assert 200 < rgba[60, 40, 3] < 250, "el borde queda semitransparente"
    assert np.abs(rgba[60, 40, :3].astype(float) - gris).max() <= 4, "sin el croma mezclado vuelve a ser gris"
    assert rgba[60, 60, 3] == 255 and np.abs(rgba[60, 60, :3].astype(float) - mezcla).max() <= 1


# ------------------------------------------------------------------------------------------ figuras y apoyo
def _rgba_con(cajas: list[tuple[int, int, int, int]], ancho: int = 400, alto: int = 300) -> np.ndarray:
    a = np.zeros((alto, ancho, 4), np.uint8)
    for x0, y0, x1, y1 in cajas:
        a[y0:y1, x0:x1] = (200, 100, 50, 255)
    return a


def test_piezas_separa_figuras_y_une_lo_que_esta_a_menos_de_la_junta():
    rgba = _rgba_con([(200, 50, 260, 200), (20, 50, 80, 200), (84, 60, 90, 70)])
    cajas = recorte.piezas(rgba)
    assert len(cajas) == 2, "la mancha a 4 px de la primera figura es parte de ella (un mechón suelto)"
    assert cajas[0][0] < cajas[1][0], "de izquierda a derecha"
    assert cajas[0][2] >= 90 + recorte.JUNTA_PX - 1, "la caja de la primera llega hasta el mechón"


def test_control_lo_que_esta_lejos_es_otra_figura_y_lo_diminuto_no_cuenta():
    rgba = _rgba_con([(20, 50, 80, 200), (140, 60, 200, 200), (330, 10, 332, 12)])
    assert len(recorte.piezas(rgba)) == 2, "la mota de 4 px está por debajo del área mínima"
    rgba = _rgba_con([(20, 50, 80, 200), (140, 60, 200, 200), (300, 10, 340, 60)])
    assert len(recorte.piezas(rgba)) == 3


def test_orden_de_lectura_por_filas():
    arriba = [(300, 10, 350, 60), (10, 12, 60, 58), (150, 8, 200, 62)]
    abajo = [(200, 150, 250, 210), (40, 155, 90, 200)]
    orden = recorte.orden_lectura(arriba + abajo)
    assert [c[0] for c in orden] == [10, 150, 300, 40, 200]


def test_el_apoyo_es_el_centro_de_los_pies_aunque_un_brazo_sobresalga():
    im = Image.new("RGBA", (200, 220), (0, 0, 0, 0))
    persona(ImageDraw.Draw(im), 120, 200, 180, 20)
    ImageDraw.Draw(im).rectangle([0, 60, 110, 70], fill=(10, 10, 10, 255))  # un brazo muy largo a la izquierda
    rgba = np.asarray(im)
    ax, ay = recorte.apoyo(rgba, centrado=False)
    assert ay == 200 and abs(ax - 120) <= 2, "el apoyo está entre los pies"
    cx, _ = recorte.apoyo(rgba, centrado=True)
    assert abs(cx - 120) > 20, "control: el centro de la figura sí se lo lleva el brazo"


def test_recorta_caja_con_margen_y_sin_colarse_la_vecina():
    rgba = _rgba_con([(20, 50, 80, 200), (84, 50, 120, 200)])
    solo_la_primera = np.zeros(rgba.shape[:2], bool)
    solo_la_primera[50:200, 20:80] = True
    trozo, donde = recorte.recorta_caja(rgba, (20, 50, 80, 200), solo_la_primera)
    assert donde == (4, 34, 96, 216)
    assert trozo[:, 80 - 4 :, 3].max() == 0, "la vecina, dentro del margen, no se cuela"
    trozo, _ = recorte.recorta_caja(rgba, (20, 50, 80, 200))
    assert trozo[:, 80 - 4 :, 3].max() == 255, "control: sin la máscara, la vecina sí se ve"


def test_la_entrada_de_catalogo_tiene_el_esquema_de_compone():
    trozo = np.zeros((30, 20, 4), np.uint8)
    e = recorte.entrada("assets/img/x.png", trozo, (5, 6, 25, 36), (10.04, 29.0), 0.92)
    assert e == {"src": "assets/img/x.png", "w": 20, "h": 30, "ax": 10.0, "ay": 29.0, "ox": 5, "oy": 6, "k": 0.92}


# ------------------------------------------------------------------------------------------ la cabeza
def test_la_medida_de_la_cabeza_crece_con_el_pelo_y_no_con_el_cuerpo():
    from utiles_activos import figura_rgba

    color = recorte.color_de_pelo(figura_rgba(200, 20))
    base = recorte.medida_de_cabeza(figura_rgba(200, 20), color)
    grande = recorte.medida_de_cabeza(figura_rgba(200, 29), color)
    assert grande / base == pytest.approx(29 / 20, rel=0.05)
    ancha = figura_rgba(200, 20, ancho=160)
    assert recorte.medida_de_cabeza(ancha, color) == pytest.approx(base, rel=0.01), (
        "control: más lienzo no es más cabeza"
    )


def test_la_caja_de_la_cabeza_no_se_ensancha_con_un_brazo():
    from utiles_activos import figura_rgba

    rgba = figura_rgba(200, 20, ancho=200)
    x0, y0, x1, y1 = recorte.caja_de_cabeza(rgba, 0.32)
    brazo = rgba.copy()
    brazo[16 + 60 : 16 + 64, 0:200] = (10, 10, 10, 255)  # a la altura del final de la franja de la cabeza
    assert recorte.caja_de_cabeza(brazo, 0.32) == [x0, y0, x1, y1]
    assert x1 - x0 <= 44, "la cabeza mide su pelo (40 px), no la imagen"


def test_corrige_escalas_con_referencia_de_pie_y_variantes_que_heredan():
    figuras = {
        "a_frente": {"pj": "a", "vista": "frente", "de_pie": True, "base": None, "k0": 0.9, "cabeza_px": 18.0},
        "a_saluda": {"pj": "a", "vista": "frente", "de_pie": True, "base": None, "k0": 1.0, "cabeza_px": 20.0},
        "a_sentado": {"pj": "a", "vista": "frente", "de_pie": False, "base": None, "k0": 1.0, "cabeza_px": 29.0},
        "a_sentado_s": {
            "pj": "a",
            "vista": "frente",
            "de_pie": False,
            "base": "a_sentado",
            "k0": 1.0,
            "cabeza_px": 30.0,
        },
        "a_agacha": {"pj": "a", "vista": "frente", "de_pie": False, "base": None, "k0": 1.0, "cabeza_px": 20.8},
        "a_tumbado": {"pj": "a", "vista": "perfil", "de_pie": False, "base": None, "k0": 1.0, "cabeza_px": 25.0},
        "b_sentado": {"pj": "b", "vista": "frente", "de_pie": False, "base": None, "k0": 1.0, "cabeza_px": None},
    }
    factores, informe = recorte.corrige_escalas(figuras, 0.06)
    assert factores["a_sentado"] == pytest.approx(1.45)
    assert factores["a_sentado_s"] == factores["a_sentado"], "la variante hereda el factor de su postura limpia"
    assert factores["a_agacha"] == 1.0, "a un 4 % de la referencia no se toca"
    assert factores["a_frente"] == factores["a_saluda"] == 1.0
    assert factores["a_tumbado"] == 1.0 and any("a_tumbado" in linea for linea in informe), "sin referencia de perfil"
    assert factores["b_sentado"] == 1.0
    factores, _ = recorte.corrige_escalas(figuras, 0.0)
    assert factores["a_agacha"] == pytest.approx(1.04), "control: sin tolerancia, sí se corrige"


# ------------------------------------------------------------------------------------------ la máscara de SAM
def test_la_mascara_se_queda_con_lo_grande_rellena_huecos_y_quita_motas():
    logits = np.full((100, 120), -5.0, np.float32)
    logits[20:80, 20:70] = 5.0
    logits[45:55, 40:50] = -5.0  # un hueco dentro
    logits[5:6, 110:111] = 5.0  # una mota suelta
    logits[30:45, 85:100] = 5.0  # un mechón suelto: 225 px, más del 2 % de 3000
    m = recorte.mascara_afinada(logits, np.full((100, 120), 0.5, np.float32))
    assert m[50, 45] > 0.9, "el hueco se rellena"
    assert m[5, 110] < 0.1, "la mota se va"
    assert m[37, 92] > 0.9, "control: el mechón, que es grande, se queda"
    with pytest.raises(recorte.ErrorDeRecorte):
        recorte.mascara_afinada(logits, np.zeros((10, 10), np.float32))


def test_separa_pieza_da_su_pivote_su_off_y_hereda_la_k():
    rgba = np.zeros((200, 150, 4), np.uint8)
    rgba[..., 3] = 255
    m = np.zeros((200, 150), np.float32)
    m[20:60, 90:130] = 1.0
    base = {"ax": 75.0, "ay": 190.0, "ox": 100, "oy": 40, "k": 1.3, "k0": 1.0}
    trozo, e = recorte.separa_pieza(rgba, m, (110, 58), base, "assets/img/x_cola.png")
    assert (e["w"], e["h"]) == trozo.shape[1::-1] == (56, 56)
    assert (e["ax"], e["ay"]) == (110 - 82, 58 - 12)
    assert e["off"] == [110 - 75.0, 58 - 190.0]
    assert (e["ox"], e["oy"], e["k"], e["k0"]) == (182, 52, 1.3, 1.0)
    with pytest.raises(recorte.ErrorDeRecorte):
        recorte.separa_pieza(rgba, np.zeros_like(m), (0, 0), base, "x")


# ------------------------------------------------------------------------------------------ el módulo
def test_el_nucleo_no_importa_nada_del_repositorio():
    """El trabajador lo importa en `.venv-escena`, donde `lib.config` no carga (le falta python-dotenv)."""
    permitidos = {"__future__", "math", "collections", "statistics", "numpy", "PIL", "scipy"}
    arbol = ast.parse((RAIZ / "lib" / "escena" / "recorte.py").read_text(encoding="utf-8"))
    importados = {
        (n.module or "").split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
        for n in ast.walk(arbol)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert importados <= permitidos, f"recorte.py importa {sorted(importados - permitidos)}"
    assert "lib" not in importados
    paquete = (RAIZ / "lib" / "escena" / "__init__.py").read_text(encoding="utf-8")
    assert not [n for n in ast.walk(ast.parse(paquete)) if isinstance(n, (ast.Import, ast.ImportFrom))], (
        "lib/escena/__init__.py no puede importar nada: el trabajador lo carga al importar recorte"
    )


# ------------------------------------------------------------------------------------------ piezas por su sitio (F6.2d)
def _dos_figuras() -> list:
    """Dos figuras con su máscara: la de la izquierda centrada en (50, 50) y la de la derecha en (250, 50)."""
    uno, dos = np.zeros((100, 300), bool), np.zeros((100, 300), bool)
    uno[20:80, 20:80], dos[20:80, 220:280] = True, True
    return [((20, 20, 80, 80), uno), ((220, 20, 280, 80), dos)]


def test_cada_nombre_se_lleva_la_figura_de_su_sitio():
    elegidas = recorte.reparte_por_sitios(_dos_figuras(), {"llave": (25, 25), "pano": (125, 25)}, escala=2)
    assert [(n, caja) for n, caja, _ in elegidas] == [("llave", (20, 20, 80, 80)), ("pano", (220, 20, 280, 80))]


def test_control_dos_nombres_en_la_misma_figura_paran():
    """Auditoría de F6.2c, recomendación 4: antes salían dos recortes iguales con dos nombres, sin aviso."""
    with pytest.raises(recorte.ErrorDeRecorte, match="llave y pano caen en la misma figura"):
        recorte.reparte_por_sitios(_dos_figuras(), {"llave": (25, 25), "pano": (40, 30)}, escala=2)
