"""Cada comprobación de `lib/escena/comprobaciones.py` caza su defecto, con su control negativo (F6.2b).

Criterio de F6.2b: «cada comprobación (cabeza fuera de cuadro, texto sobre cara, pies sin suelo, escala,
karaoke) caza su defecto con un control negativo». El punto de partida es el episodio de prueba, que pasa las
seis (`test_extremo_a_extremo.py`); cada control lo estropea a propósito de UNA forma y exige que salte SU
comprobación. Donde hay una válvula legítima (la cámara `libre`, el texto que `tapa_caras`, el set sin suelo,
la cabeza que no se mide) se prueba también que la válvula no se come el defecto de al lado.
"""

from __future__ import annotations

import copy

import pytest
from utiles_escena import LAMINAS_PRUEBA, guion_de_prueba, linea_de_prueba, marcas_uniformes

from lib.escena import comprobaciones as c
from lib.escena import encuadre
from lib.escena.encuadre import Geometria


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    linea = linea_de_prueba(tmp_path_factory.mktemp("comprobaciones") / "run")
    return linea, guion_de_prueba(linea).datos()


@pytest.fixture
def datos(base):
    return copy.deepcopy(base[1])


@pytest.fixture
def linea(base):
    return base[0]


def _p1(datos):
    return datos["planos"][0]


def _actor(datos, pj, plano=0):
    return next(a for a in datos["planos"][plano]["actores"] if a["pj"] == pj)


def _elemento(datos, clase_html):
    return next(e for e in datos["elementos"] if f'class="{clase_html}"' in e["html"])


def test_el_episodio_de_partida_no_tiene_ningun_defecto(datos, linea):
    assert all(v == [] for v in c.todas(datos, linea).values())


# ------------------------------------------------------------------ cabezas
def _plano_de_pies(datos):
    """La primera clave de cámara del parque, cerrada sobre los pies de Ana: su cabeza queda fuera por arriba."""
    datos["planos"][0]["camara"][0].update(cx=850, cy=1250, z=3.0)
    return datos


def test_control_una_cabeza_cortada_la_caza(datos):
    defectos = c.cabezas_en_cuadro(_plano_de_pies(datos))
    ana = _actor(datos, "ana")["id"]
    assert [d.donde for d in defectos] == [f"p1/{ana}"]
    assert defectos[0].comprobacion == "cabeza_fuera" and defectos[0].t < 5


def test_la_clave_libre_corta_la_cabeza_a_proposito(datos):
    _plano_de_pies(datos)["planos"][0]["camara"][0]["libre"] = True
    assert c.cabezas_en_cuadro(datos) == []


def test_corrige_abre_el_encuadre_y_la_comprobacion_lo_da_por_bueno(datos):
    _plano_de_pies(datos)
    cambios = encuadre.corrige(datos)
    assert len(cambios) == 1 and cambios[0].startswith("p1 t=0.0")
    assert datos["planos"][0]["camara"][0]["z"] < 3.0  # abre, nunca acerca
    assert c.cabezas_en_cuadro(datos) == []


# ------------------------------------------------------------------ textos sobre caras
def _sobre_la_cara(datos, e, pj="ana"):
    """Pone el elemento `e` centrado en la cara del personaje, en el instante en que empieza."""
    geo = Geometria(datos)
    cara = geo.a_pantalla("p1", e["t0"] + 0.5, geo.cabeza(_actor(datos, pj)["id"], e["t0"] + 0.5))
    e["x"] = (cara[0] + cara[2]) / 2 - e["w"] / 2
    e["y"] = (cara[1] + cara[3]) / 2 - e["h"] / 2
    return e


def test_control_una_tarjeta_sobre_una_cara_la_caza(datos):
    tarjeta = _sobre_la_cara(datos, _elemento(datos, "tarjeta"))
    defectos = c.textos_fuera_de_las_caras(datos)
    assert [d.donde for d in defectos] == [tarjeta["id"]]
    assert defectos[0].comprobacion == "texto_sobre_cara"


def test_aparta_de_caras_la_mueve_y_la_comprobacion_la_da_por_buena(datos):
    tarjeta = _sobre_la_cara(datos, _elemento(datos, "tarjeta"))
    antes = (tarjeta["x"], tarjeta["y"])
    assert len(encuadre.aparta_de_caras(datos, franja_inferior_y=860)) == 1
    assert (tarjeta["x"], tarjeta["y"]) != antes
    assert c.textos_fuera_de_las_caras(datos) == []


def test_un_texto_que_tapa_caras_a_proposito_no_cuenta_pero_otro_si(datos):
    tarjeta = _sobre_la_cara(datos, _elemento(datos, "tarjeta"))
    tarjeta["tapa_caras"] = True
    assert c.textos_fuera_de_las_caras(datos) == []
    # La válvula es de ESE elemento: el grito, puesto también sobre una cara, sigue saltando.
    grito = _elemento(datos, "grito")
    geo = Geometria(datos)
    bo = _actor(datos, "bo", plano=1)["id"]
    cara = geo.a_pantalla(datos["planos"][1]["id"], grito["t0"] + 0.5, geo.cabeza(bo, grito["t0"] + 0.5))
    grito.update(x=(cara[0] + cara[2]) / 2 - grito["w"] / 2, y=(cara[1] + cara[3]) / 2 - grito["h"] / 2)
    assert [d.donde for d in c.textos_fuera_de_las_caras(datos)] == [grito["id"]]


def test_un_dibujo_sin_texto_sobre_una_cara_no_es_un_texto(datos):
    tarjeta = _sobre_la_cara(datos, _elemento(datos, "tarjeta"))
    tarjeta["html"] = '<svg viewBox="0 0 10 10"><circle class="trazo" cx="5" cy="5" r="4"/></svg>'
    assert c.textos_fuera_de_las_caras(datos) == []


def test_control_una_etiqueta_del_fondo_sobre_una_cara_tambien(datos):
    """La etiqueta va en px del FONDO del plano: la comprobación la lleva a pantalla con la cámara."""
    etiqueta = _elemento(datos, "etiqueta")
    ana = _actor(datos, "ana")["id"]
    geo = Geometria(datos)
    cabeza = geo.cabeza(ana, etiqueta["t0"] + 0.5)  # en px del fondo
    etiqueta["x"] = (cabeza[0] + cabeza[2]) / 2 - etiqueta["w"] / 2
    etiqueta["y"] = (cabeza[1] + cabeza[3]) / 2 - etiqueta["h"] / 2
    assert [d.donde for d in c.textos_fuera_de_las_caras(datos)] == [etiqueta["id"]]


# ------------------------------------------------------------------ pies
def test_control_un_personaje_que_flota_lo_caza(datos):
    bo = _actor(datos, "bo")
    bo["pista"][0]["y"] = 900  # el suelo del parque empieza en y = 1080
    defectos = c.pies_en_el_suelo(datos)
    assert [d.donde for d in defectos] == [f"p1/{bo['id']}"]
    assert defectos[0].comprobacion == "pies_sin_suelo"


def test_un_set_sin_suelo_declarado_no_se_puede_comprobar_y_lo_dice(datos):
    del _p1(datos)["fondo"]["suelo"]
    defectos = c.pies_en_el_suelo(datos)
    assert [d.donde for d in defectos] == ["p1"] and "no declara su suelo" in defectos[0].detalle


def test_un_set_que_declara_que_no_tiene_suelo_no_se_mira(datos):
    _p1(datos)["fondo"]["suelo"] = None
    _actor(datos, "bo")["pista"][0]["y"] = 900
    assert c.pies_en_el_suelo(datos) == []


def test_un_objeto_solo_pisa_si_lo_dice(datos):
    """Un objeto (sin pj) no se apoya por omisión; con el rasgo `pisa`, sí, y entonces flota."""
    bo = _actor(datos, "bo")
    bo["pj"] = None
    bo["pista"][0]["y"] = 900
    assert c.pies_en_el_suelo(datos) == []
    bo["rasgos"]["pisa"] = True
    assert len(c.pies_en_el_suelo(datos)) == 1


# ------------------------------------------------------------------ escala de cabeza
def test_control_una_postura_con_la_cabeza_grande_la_caza(datos):
    """El caso de video_1: de rodillas, la cabeza salía un 45 % mayor que de pie."""
    _actor(datos, "ana")["posturas"]["ana_brazos"]["cabeza_px"] = 80 * 1.45
    _actor(datos, "ana")["posturas"]["ana_pie"]["cabeza_px"] = 80
    _actor(datos, "bo")["posturas"]["bo_pie"]["cabeza_px"] = 80
    defectos = c.escala_de_cabeza(datos)
    assert len(defectos) == 2  # con dos posturas, las dos se apartan de su mediana más de un 6 %
    assert {d.donde for d in defectos} == {"ana/ana_pie", "ana/ana_brazos"}


def test_una_k_que_la_corrige_la_deja_pasar(datos):
    """Lo que hace el obrero de escala (F6.2c): la k reduce la postura y con ella su cabeza."""
    brazos = _actor(datos, "ana")["posturas"]["ana_brazos"]
    brazos.update(cabeza_px=80 * 1.45, k=1.45)
    assert c.escala_de_cabeza(datos) == []
    brazos["cabeza_px"] = 80 * 1.04 * 1.45  # dentro del 6 %
    assert c.escala_de_cabeza(datos) == []


def test_una_postura_sin_medida_de_cabeza_no_se_puede_comprobar(datos):
    del _actor(datos, "ana")["posturas"]["ana_brazos"]["cabeza_px"]
    assert [d.donde for d in c.escala_de_cabeza(datos)] == [f"{_actor(datos, 'ana')['id']}/ana_brazos"]
    _actor(datos, "ana")["posturas"]["ana_brazos"]["cabeza_px"] = None  # declarado: esta figura no se mide
    assert c.escala_de_cabeza(datos) == []


def test_de_frente_y_de_perfil_no_se_comparan(datos):
    posturas = _actor(datos, "ana")["posturas"]
    posturas["ana_brazos"].update(cabeza_px=80 * 1.45, vista="perfil")
    posturas["ana_pie"]["vista"] = "frente"
    assert c.escala_de_cabeza(datos) == []


# ------------------------------------------------------------------ karaoke
def test_control_una_palabra_que_falta_en_el_karaoke_la_caza(datos, linea):
    quitada = datos["karaoke"][2]["w"].pop(1)
    defectos = c.karaoke(datos, linea)
    assert len(defectos) == 1 and repr(quitada[2]) in defectos[0].detalle


def test_control_un_karaoke_que_retrocede_lo_caza(datos, linea):
    w = datos["karaoke"][1]["w"]
    w[1][0], w[2][0] = w[2][0], w[1][0]
    assert [d.comprobacion for d in c.karaoke(datos, linea)] == ["karaoke"]


def test_control_una_lamina_mal_anclada_la_caza(tmp_path):
    """El reconocedor pierde 8 de las 25 palabras de la lámina 1 (68 % ancladas, como el peor caso medido)."""
    laminas = copy.deepcopy(LAMINAS_PRUEBA)
    laminas[0]["marcas"] = marcas_uniformes(laminas[0]["narration"], quita=range(8, 16))
    linea = linea_de_prueba(tmp_path / "run", laminas)
    datos = {"karaoke": linea.karaoke()}
    defectos = c.karaoke(datos, linea)
    assert [d.donde for d in defectos] == ["lámina 1"]
    assert "17 de 25" in defectos[0].detalle


# ------------------------------------------------------------------ duración
def test_control_un_guion_que_no_dura_lo_que_su_audio_lo_caza(datos, linea):
    assert c.duracion(datos, linea) == []
    datos["duracion"] = linea.total + 1 / 24  # un fotograma de más
    assert [d.comprobacion for d in c.duracion(datos, linea)] == ["duracion"]


def test_control_un_audio_que_se_sale_del_guion_lo_caza(datos, linea):
    datos["audios"] = [{"id": "sfx0", "t": linea.total - 0.2, "d": 1.0}]
    assert [d.donde for d in c.duracion(datos, linea)] == ["sfx0"]


def test_la_cabeza_de_un_actor_volteado_va_al_otro_lado_de_su_apoyo(datos):
    """Como en el motor, que voltea con scale(−1) sobre el apoyo: [c0 − ax, c1 − ax] pasa a [ax − c1, ax − c0]."""
    ana = _actor(datos, "ana")
    ana["posturas"]["ana_pie"]["cabeza"] = [0, 10, 50, 60]  # a la izquierda del apoyo (ax = 100)
    geo = Geometria(datos)
    x = geo.mundo(ana["id"], 0.5)["x"]
    derecha = geo.cabeza(ana["id"], 0.5)
    assert (derecha[0] - x, derecha[2] - x) == (pytest.approx(-120), pytest.approx(-60))  # escala 1,2
    ana["pista"][0]["flip"] = 1
    volteada = Geometria(datos).cabeza(ana["id"], 0.5)
    assert (volteada[0] - x, volteada[2] - x) == (pytest.approx(60), pytest.approx(120))
