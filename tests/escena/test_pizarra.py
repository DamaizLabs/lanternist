"""El formato «pizarra» del motor de escena (F7.10, filas 256 y 257): `lib/escena/pizarra.py`.

Cada prueba lleva su control negativo, que demuestra que la prueba sabe fallar:

- la separación recupera el alfa de un trazo conocido, y con un núcleo más estrecho que el trazo no lo recupera;
- una pizarra sin tiza no da ninguna pieza y sale idéntica;
- la pizarra limpia no deja la sombra de un dibujo relleno de oscuro, que la apertura sola sí dejaría;
- una barra con el doble de valor mide el doble, y un valor negativo para la gráfica;
- un ancla a una palabra que no está en la narración falla;
- un perfil sin una clave de `escena.pizarra` falla nombrándola;
- una pieza olvidada, una fuente sin declarar en el CSS o una flecha sin velocidad válida paran;
- un texto que se borraría antes de quedar escrito o después de que la pizarra se vaya para, y el borrador del motor
  barre de 0 a 1 mientras una salida «fade» no barre nada;
- una reserva para con una pieza que ya está, con lo que entra en ella y con otro texto, en los dos órdenes; un texto
  escrito antes de ella o una pieza que entra después, no.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from utiles_escena import GUION_MIN, escena_prueba, linea_de_prueba, node

from lib import config, provenance
from lib.escena import anclas, audio, compone, comprobaciones, obrero, pizarra
from lib.escena.escena import Guion
from lib.escena.linea_tiempo import ErrorDeLinea

# Los valores de un canal ficticio: los de la propuesta del primer canal que usó el formato.
AJUSTES = {
    "separa": {
        "nucleo_px": 21, "umbral": 20, "tiza_plena": 200, "agrupa_px": 10, "umbral_oscuro": 8, "masa_minima_px": 150,
    },
    "pieza": {"funde_s": 0.3},
    "camara": {"zoom": 1.0, "acercamiento": 0.07, "acercamiento_s": 5.0},
    "transicion": {"cambio_de_tema_s": 0.5},
    "texto": {
        "fuente": "PatrickHandSC-Regular.ttf", "letra_s": 0.45, "relleno_tras": 0.5, "relleno_s": 0.25,
        "paso_s": 0.07, "espaciado": 0.02, "interlineado": 1.15, "borra_s": 0.6,
        "tamanos": {"titulo": 120, "etiqueta": 78, "cifra": 88, "nota": 64},
    },
    "flecha": {"velocidad_px_s": 60, "punta_px": 34},
    "grafica": {"hueco": 0.45, "trazo_s": 0.6, "rayado_px": 22},
}  # fmt: skip
SEP = {k: AJUSTES["separa"][k] for k in pizarra.CLAVES_DE_SEPARA}
FONDO = 35.0
BLANCA = np.array([235.0, 235.0, 228.0])
AMARILLA = np.array([235.0, 215.0, 120.0])
CSS_CON_FUENTE = '@font-face { font-family: "Tiza"; src: url("assets/fuentes/PatrickHandSC-Regular.ttf"); }\n'


def _pizarra_vacia(w: int = 400, h: int = 300) -> np.ndarray:
    """Una pizarra gris con un borrón ancho de tiza usada (una campana de 60 px de radio) y un grano fino."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    borron = 18.0 * np.exp(-(((xx - 300) ** 2 + (yy - 80) ** 2) / (2 * 60.0**2)))
    grano = np.random.default_rng(7).normal(0, 1.5, (h, w))
    plano = FONDO + borron + grano
    return np.repeat(plano[..., None], 3, axis=2)


def _pinta(img: np.ndarray, mascara: np.ndarray, color: np.ndarray, alfa: float) -> np.ndarray:
    a = mascara[..., None].astype(np.float32) * alfa
    return img * (1 - a) + color * a


def _raya(h: int, w: int, y: int, x0: int, x1: int, grueso: int) -> np.ndarray:
    m = np.zeros((h, w), dtype=bool)
    m[y - grueso // 2 : y + (grueso + 1) // 2, x0:x1] = True
    return m


def _u8(img: np.ndarray) -> np.ndarray:
    return np.clip(np.round(img), 0, 255).astype(np.uint8)


# ------------------------------------------------------------------------------------------ la separación
def test_una_pizarra_sintetica_recupera_el_alfa_y_el_color_de_su_tiza():
    img = _pizarra_vacia()
    img = _pinta(img, _raya(300, 400, 150, 40, 200, 6), BLANCA, 0.8)
    img = _pinta(img, _raya(300, 400, 220, 40, 200, 6), AMARILLA, 0.9)
    fondo, tiza = pizarra.separa_tiza(_u8(img), nucleo_px=21, umbral=20, tiza_plena=200)
    lum = BLANCA @ np.array([0.299, 0.587, 0.114])
    esperado = 0.8 * (lum - FONDO) / 200  # el exceso de la raya blanca sobre la pizarra, entre la tiza plena
    assert tiza[150, 60:180, 3].mean() / 255 == pytest.approx(esperado, abs=0.05)
    # El amarillo se conserva: rojo y verde altos, azul bajo.
    r, g, b = tiza[220, 60:180, :3].astype(float).mean(axis=0)
    assert r > 200 and g > 185 and b < 160
    # El borrón ancho no es tiza y sigue en la pizarra limpia: 18 niveles por encima de la pizarra, como se pintó.
    assert tiza[80, 290:310, 3].max() == 0
    assert float(fondo[75:86, 295:306].mean()) - float(fondo[240:260, 300:320].mean()) == pytest.approx(18, abs=4)
    # Y bajo la raya, la pizarra limpia es pizarra.
    assert abs(float(fondo[150, 100].mean()) - FONDO) < 6


def test_control_con_un_nucleo_mas_estrecho_que_el_trazo_la_tiza_se_queda_en_la_pizarra():
    img = _pinta(_pizarra_vacia(), _raya(300, 400, 150, 40, 200, 12), BLANCA, 0.8)
    _, tiza = pizarra.separa_tiza(_u8(img), nucleo_px=5, umbral=20, tiza_plena=200)
    assert tiza[150, 60:180, 3].mean() / 255 < 0.2


def test_una_pizarra_sin_tiza_no_da_ninguna_pieza_y_sale_igual():
    img = _u8(_pizarra_vacia())
    s = pizarra.separa_pizarra(img, **SEP)
    assert s.piezas == [] and not s.tiza[..., 3].any()
    assert np.array_equal(s.limpia, img)


def _dos_dibujos() -> np.ndarray:
    """Un aro blanco y un disco relleno de un oscuro más oscuro que la pizarra con su borde de tiza (como los rellena
    Qwen), y una mota suelta lejos de los dos."""
    h, w = 300, 400
    yy, xx = np.mgrid[0:h, 0:w]
    img = _pizarra_vacia(w, h)
    aro = np.abs(np.hypot(xx - 90, yy - 150) - 50) < 3
    disco = np.hypot(xx - 250, yy - 170) < 55
    borde = np.abs(np.hypot(xx - 250, yy - 170) - 55) < 3
    mota = np.hypot(xx - 370, yy - 270) < 2
    img = _pinta(img, aro, BLANCA, 0.9)
    img = _pinta(img, disco, np.array([12.0, 12.0, 12.0]), 1.0)
    img = _pinta(img, borde, AMARILLA, 0.9)
    return _pinta(img, mota, BLANCA, 0.9)


def test_las_piezas_sobre_la_pizarra_limpia_devuelven_la_imagen_y_sin_sombra_del_relleno():
    img = _u8(_dos_dibujos())
    s = pizarra.separa_pizarra(img, **SEP)
    assert [p.numero for p in s.piezas] == [1, 2]
    a = s.tiza[..., 3:4].astype(np.float32) / 255
    junta = s.limpia * (1 - a) + s.tiza[..., :3] * a
    assert np.abs(junta - img).mean() < 1.0
    # Dentro del disco, antes de que llegue su pieza, se ve pizarra y no su relleno oscuro.
    yy, xx = np.mgrid[0:300, 0:400]
    dentro = np.hypot(xx - 250, yy - 170) < 40
    assert abs(float(s.limpia[dentro].mean()) - FONDO) < 5
    # La mota suelta no es pieza: se queda en la pizarra limpia, tal cual.
    assert s.mapa[270, 370] == 0 and s.limpia[270, 370].mean() > 150


def test_control_la_apertura_sola_dejaria_la_sombra_del_relleno():
    fondo, _ = pizarra.separa_tiza(_u8(_dos_dibujos()), nucleo_px=21, umbral=20, tiza_plena=200)
    yy, xx = np.mgrid[0:300, 0:400]
    assert FONDO - float(fondo[np.hypot(xx - 250, yy - 170) < 40].mean()) > 15


def _una_u(ojo: tuple[int, int]) -> np.ndarray:
    """Un dibujo en U (dos palos y la base), un ojo flojo en `ojo` y una mota suelta en una esquina."""
    alfa = np.zeros((200, 300), dtype=np.uint8)
    alfa[40:160, 30:34] = 255
    alfa[40:160, 126:130] = 255
    alfa[156:160, 30:130] = 255
    alfa[ojo[1] : ojo[1] + 3, ojo[0] : ojo[0] + 3] = 255
    alfa[180:183, 280:283] = 255
    return alfa


def test_un_detalle_flojo_dentro_de_la_caja_de_un_dibujo_va_con_el_y_uno_suelto_no():
    piezas, regiones = pizarra.parte_en_piezas(_una_u((78, 99)), agrupa_px=10, masa_minima_px=200)
    assert len(piezas) == 1 and piezas[0].area_px == 1328 + 9
    assert regiones[100, 79] == 1 and regiones[181, 281] == 0


def test_control_un_detalle_fuera_de_la_caja_del_dibujo_no_va_con_el():
    piezas, regiones = pizarra.parte_en_piezas(_una_u((200, 99)), agrupa_px=10, masa_minima_px=200)
    assert len(piezas) == 1 and piezas[0].area_px == 1328 and regiones[100, 201] == 0


# ------------------------------------------------------------------------------------------ separa(), en el run
def _run_con_pizarra(tmp_path, img: np.ndarray):
    activos = tmp_path / "activos"
    (activos / obrero.IMG).mkdir(parents=True)
    ruta = activos / obrero.IMG / "pizarra_01.jpg"
    Image.fromarray(img).save(ruta, quality=95)
    provenance.anade_registros(
        activos / obrero.IMG / obrero.REGISTRO,
        [{"file": str(ruta), "modelo": "prueba", "licencia": "Apache-2.0", "url": "https://ejemplo.invalid"}],
    )
    obrero.guarda_catalogo(
        activos,
        {
            "imagenes": {"pizarra_01": {"src": "assets/img/pizarra_01.jpg", "w": 400, "h": 300, "del_episodio": True}}
        },  # fmt: skip
    )
    return activos


def test_separa_apunta_cada_pieza_con_su_procedencia_y_rehacerla_no_deja_piezas_viejas(tmp_path):
    activos = _run_con_pizarra(tmp_path, _u8(_dos_dibujos()))
    op = pizarra.separacion("pizarra_01", AJUSTES)
    r = pizarra.separa(op, activos, tmp_path / "revision")
    assert r["piezas"] == 2 and r["hoja"].is_file()
    cat = obrero.lee_catalogo(activos)["imagenes"]
    assert {"pizarra_01_limpia", "pizarra_01_p01", "pizarra_01_p02"} <= set(cat)
    assert all(cat[n].get("del_episodio") for n in ("pizarra_01_limpia", "pizarra_01_p01"))
    registros = json.loads((activos / obrero.IMG / obrero.REGISTRO).read_text(encoding="utf-8"))
    del_derivado = [x for x in registros if "pizarra_01_p0" in x["file"]]
    assert len(del_derivado) == 2 and all(x["licencia"].startswith("Apache-2.0") for x in del_derivado)
    # Con un agrupado que junta los dos dibujos sale UNA pieza: la p02 vieja sale del disco, del catálogo y del
    # registro.
    op_junta = pizarra.separacion("pizarra_01", {**AJUSTES, "separa": {**AJUSTES["separa"], "agrupa_px": 80}})
    assert pizarra.separa(op_junta, activos, tmp_path / "revision")["piezas"] == 1
    cat = obrero.lee_catalogo(activos)["imagenes"]
    assert "pizarra_01_p02" not in cat and not (activos / obrero.IMG / "pizarra_01_p02.png").exists()
    registros = json.loads((activos / obrero.IMG / obrero.REGISTRO).read_text(encoding="utf-8"))
    assert all(Path(x["file"]).is_file() for x in registros)


def test_control_separar_una_pizarra_que_no_esta_en_el_catalogo_para(tmp_path):
    activos = _run_con_pizarra(tmp_path, _u8(_dos_dibujos()))
    with pytest.raises(pizarra.ErrorDePizarra, match="pizarra_09"):
        pizarra.separa(pizarra.separacion("pizarra_09", AJUSTES), activos, tmp_path / "revision")


# ------------------------------------------------------------------------------------------ los ajustes
def _rutas(d: dict, prefijo: str = "") -> list[str]:
    salida = []
    for k, v in d.items():
        ruta = f"{prefijo}{k}"
        salida += _rutas(v, ruta + ".") if isinstance(v, dict) and k != "tamanos" else [ruta]
    return salida


def test_control_con_todas_sus_claves_el_bloque_vale():
    assert pizarra.ajustes({"pizarra": AJUSTES})["texto"]["fuente"] == "PatrickHandSC-Regular.ttf"
    assert sorted(_rutas(AJUSTES)) == sorted(pizarra.AJUSTES)


@pytest.mark.parametrize("ruta", sorted(pizarra.AJUSTES))
def test_un_perfil_sin_una_clave_de_pizarra_falla_nombrandola(ruta):
    bloque = copy.deepcopy(AJUSTES)
    *camino, ultima = ruta.split(".")
    nodo = bloque
    for parte in camino:
        nodo = nodo[parte]
    del nodo[ultima]
    with pytest.raises(pizarra.ErrorDePizarra, match=re.escape(f"`escena.pizarra.{ruta}`")):
        pizarra.ajustes({"pizarra": bloque})


def test_un_perfil_sin_bloque_de_pizarra_dice_todo_lo_que_falta():
    with pytest.raises(pizarra.ErrorDePizarra, match="separa.nucleo_px") as error:
        pizarra.ajustes({})
    assert "grafica.rayado_px" in str(error.value)


def test_la_fuente_de_la_pizarra_tiene_que_declararla_el_css_para_tener_procedencia(tmp_path):
    with pytest.raises(pizarra.ErrorDePizarra, match="no declara la fuente"):
        pizarra.fuente(AJUSTES, ".tinta { fill: none; }")
    ruta = pizarra.fuente(AJUSTES, CSS_CON_FUENTE)
    # Y su entrada de la biblioteca del estudio cuadra (fuente, licencia, url y sha256), así que entra en el run.
    creditos = audio.lee_creditos(config.ESCENA_FUENTES_DIR)
    registro = audio.de_la_biblioteca(config.ESCENA_FUENTES_DIR, ruta.name, "fuente", tmp_path, creditos)
    assert registro["licencia"].startswith("SIL Open Font License")


# ------------------------------------------------------------------------------------------ la gráfica
def test_una_barra_con_el_doble_de_valor_mide_el_doble():
    altos = pizarra.barras([100, 200, 50], 400)
    assert altos == [200, 400, 100]
    assert altos[1] == pytest.approx(2 * altos[0])


@pytest.mark.parametrize("valores", [[100, -5], [0, 0], []])
def test_control_una_grafica_con_valores_que_no_se_pueden_medir_para(valores):
    with pytest.raises(pizarra.ErrorDePizarra):
        pizarra.barras(valores, 400)


# ------------------------------------------------------------------------------------------ la puesta en escena
CATALOGO = {
    "pz_limpia": {"src": "assets/img/pz_limpia.jpg", "w": 2688, "h": 1536, "pizarra": "pz"},
    "pz_p01": {"src": "assets/img/pz_p01.png", "w": 200, "h": 100, "pizarra": "pz", "numero": 1,
               "caja": [100, 200, 300, 300]},
    "pz_p02": {"src": "assets/img/pz_p02.png", "w": 100, "h": 100, "pizarra": "pz", "numero": 2,
               "caja": [500, 500, 600, 600]},
}  # fmt: skip


def _guion(tmp_path):
    linea = linea_de_prueba(tmp_path / "run")
    g = Guion(
        titulo="Pizarra de prueba", idioma="en", escena=escena_prueba(), catalogo=CATALOGO, iconos={}, linea=linea
    )
    g.sin_karaoke()
    return g, linea, anclas.usa(linea)


def _pizarra_de_prueba(tmp_path):
    g, linea, a = _guion(tmp_path)
    pz = pizarra.Pizarra(g, "pz", AJUSTES, pizarra.fuente(AJUSTES, CSS_CON_FUENTE))
    pz.abre(0, linea.total, cambio_de_tema=False, de_entrada=[2])
    pz.pieza(1, a.T("kite"), funde=True)
    pz.texto("Compound Interest", 1344, 150, a.T("park"), tam="titulo", clase="tiza", alinea="centro")
    pz.flecha([(300, 250), (600, 300), (520, 520)], a.T("trees"), clase="acento")
    altos = pz.grafica(
        [100, 200], caja=(1400, 600, 2400, 1300), tiempos=[a.T("Bo"), a.T("grass")], cifras=["$100", "$200"],
        etiquetas=["year 0", "year 10"], clase="tiza", clase_cifra="acento", tam_cifra="cifra", tam_etiqueta="nota",
    )  # fmt: skip
    pz.acerca(a.T("Wait"), hacia=(2000, 900))
    return g, pz, altos


def test_una_pizarra_compone_una_pagina_valida_sin_karaoke_y_con_la_flecha_que_fluye(tmp_path):
    g, pz, altos = _pizarra_de_prueba(tmp_path)
    pz.comprueba()
    datos = g.datos()
    assert datos["karaoke"] == [] and datos["sin_karaoke"] is True
    assert altos[1] == pytest.approx(2 * altos[0])
    flechas = [e for e in datos["elementos"] if "fluye" in e]
    assert len(flechas) == 1 and flechas[0]["fluye"] == 60 and 'class="fluye"' in flechas[0]["html"]
    # Las barras: el contorno de la de 200 mide el doble que el de la de 100 (el SVG lleva el alto más su margen).
    contornos = [e for e in datos["elementos"] if 'class="barra' in e["html"] and 'class="trazo"' in e["html"]]
    assert len(contornos) == 2
    assert (contornos[1]["h"] - 12) == pytest.approx(2 * (contornos[0]["h"] - 12))
    # Ninguna letra ni cifra va como texto en la página: son contornos de la tinta.
    assert not any(re.search(r">\s*\$?\d", e["html"]) for e in datos["elementos"])
    # La página se escribe: imágenes y fuente con su sitio en la composición.
    for nombre, (w, h) in {"pz_limpia.jpg": (2688, 1536), "pz_p01.png": (200, 100), "pz_p02.png": (100, 100)}.items():
        Image.new("RGB", (w, h), (30, 30, 30)).save(tmp_path / nombre)
    css = tmp_path / "canal.css"
    css.write_text(CSS_CON_FUENTE, encoding="utf-8")
    assets = {f"assets/img/{n}": tmp_path / n for n in ("pz_limpia.jpg", "pz_p01.png", "pz_p02.png")}
    assets[f"{audio.SRC_FUENTES}/PatrickHandSC-Regular.ttf"] = config.ESCENA_FUENTES_DIR / "PatrickHandSC-Regular.ttf"
    index = compone.compone(datos, assets, css, tmp_path / "composicion")
    assert '<div id="karaoke">\n\n</div>' in index.read_text(encoding="utf-8")
    assert not comprobaciones.karaoke(datos, g.linea)


def test_control_una_pieza_sin_destino_para_la_pizarra(tmp_path):
    g, linea, a = _guion(tmp_path)
    pz = pizarra.Pizarra(g, "pz", AJUSTES, pizarra.fuente(AJUSTES, CSS_CON_FUENTE))
    pz.abre(0, linea.total, cambio_de_tema=False, de_entrada=[])
    pz.pieza(1, a.T("kite"), funde=False)
    with pytest.raises(pizarra.ErrorDePizarra, match=r"sin destino: \[2\]"):
        pz.comprueba()
    with pytest.raises(pizarra.ErrorDePizarra, match="ya tiene su destino"):
        pz.pieza(1, a.T("park"), funde=False)


def test_un_ancla_a_una_palabra_que_no_esta_en_la_narracion_falla(tmp_path):
    _, linea, a = _guion(tmp_path)
    assert a.T("kite") < a.T("kite", a.T("kite") + 0.01)  # la segunda vez que se dice
    with pytest.raises(ErrorDeLinea, match="dragon"):
        a.T("dragon")
    with pytest.raises(ErrorDeLinea, match="kite"):
        a.T("kite", linea.total)  # después del final ya no se dice


def test_control_sin_la_marca_un_guion_sin_karaoke_es_un_defecto(tmp_path):
    g, _, _ = _pizarra_de_prueba(tmp_path)
    datos = g.datos()
    del datos["sin_karaoke"]
    assert any(d.comprobacion == "karaoke" for d in comprobaciones.karaoke(datos, g.linea))


def test_la_marca_sin_karaoke_solo_va_en_el_guion_que_la_pide(tmp_path):
    linea = linea_de_prueba(tmp_path / "run")
    g = Guion(titulo="Con karaoke", idioma="en", escena=escena_prueba(), catalogo=CATALOGO, iconos={}, linea=linea)
    g.fondo("pz", img="pz_limpia", suelo=None)
    g.plano("pz", 0, linea.total).cam(0, 1344, 768, 1.0, tr=0)
    datos = g.datos()
    assert "sin_karaoke" not in datos and datos["karaoke"]


# ------------------------------------------------------------------------------------------ el motor: `fluye`
NODE = node()
MOTOR = GUION_MIN.parents[2] / "motor" / "motor.js"


def _motor(codigo: str) -> dict:
    prologo = (
        f"const Motor = require({json.dumps(str(MOTOR))});"
        f"const G = JSON.parse(require('node:fs').readFileSync({json.dumps(str(GUION_MIN))}, 'utf8'));"
    )
    r = subprocess.run([NODE, "-e", prologo + f"process.stdout.write(JSON.stringify((() => {{ {codigo} }})()));"],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)  # fmt: skip
    return {"codigo": r.returncode, "salida": json.loads(r.stdout) if r.returncode == 0 else None, "error": r.stderr}


@pytest.mark.skipif(NODE is None, reason="no hay node en esta máquina")
def test_los_guiones_de_una_flecha_fluyen_a_su_velocidad_y_sin_ella_no():
    r = _motor(
        "const e = Object.assign({}, G.elementos[0], {id: 'f', fluye: 60, bucle: undefined}); G.elementos.push(e);"
        "const M = Motor.crea(G);"
        "return [M.elemento(e, e.t0 + 0.5).fluye, M.elemento(e, e.t0 + 1.0).fluye, "
        "M.elemento(G.elementos[0], 0.5).fluye];"
    )
    assert r["codigo"] == 0, r["error"]
    a, b, sin = r["salida"]
    assert a == pytest.approx(-30) and b == pytest.approx(-60) and sin is None


@pytest.mark.skipif(NODE is None, reason="no hay node en esta máquina")
def test_control_una_velocidad_que_no_es_un_numero_para_el_motor():
    r = _motor("G.elementos[0].fluye = 'deprisa'; Motor.crea(G); return 1;")
    assert r["codigo"] != 0 and "fluye" in r["error"]


# ------------------------------------------------------------------------------------------ el borrador y la reserva
def _pizarra_abierta(tmp_path, de_entrada=()):
    g, linea, a = _guion(tmp_path)
    pz = pizarra.Pizarra(g, "pz", AJUSTES, pizarra.fuente(AJUSTES, CSS_CON_FUENTE))
    pz.abre(0, linea.total, cambio_de_tema=False, de_entrada=list(de_entrada))
    return g, pz, linea


def test_mide_da_el_bloque_que_escribe_texto_y_lo_que_tarda(tmp_path):
    g, pz, _ = _pizarra_abierta(tmp_path)
    una = pz.mide("Compound Interest", tam="titulo")
    dos = pz.mide("How Does Compound Interest Grow Your Money?", tam="titulo", ancho_max=1600)
    assert (una.lineas, dos.lineas) == (1, 2) and dos.ancho <= 1600
    # Una línea más es el interlineado más (1,15 × 120 px): el alto de una línea es el mismo en los dos.
    assert dos.alto - una.alto == pytest.approx(1.15 * 120)
    # Lo que tarda es lo que devuelve texto(): 16 letras, una cada 0,07 s, y la última tarda lo suyo (0,475 s).
    assert una.escribe_s == pytest.approx(15 * 0.07 + 0.5 * 0.45 + 0.25)
    fin = pz.texto("Compound Interest", 1344, 150, 2.0, tam="titulo", clase="tiza", alinea="centro")
    assert fin == pytest.approx(2.0 + una.escribe_s)


def test_un_texto_que_se_borra_sale_con_el_borrador_y_uno_que_no_se_queda(tmp_path):
    g, pz, linea = _pizarra_abierta(tmp_path)
    escrito = pz.texto("Title", 1344, 700, 1.0, tam="titulo", clase="tiza", alinea="centro", borra=3.0)
    borrado = list(g.elementos)
    pz.texto("Stays", 1344, 300, 4.0, tam="titulo", clase="tiza", alinea="centro")
    queda = g.elementos[len(borrado) :]
    assert escrito <= 3.0 and len(borrado) == 2 * 5  # dos elementos por letra: el trazo y el relleno
    assert all(e.anim["sale"] == "borra" and e.anim["ds"] == 0.6 and e.t1 == pytest.approx(3.6) for e in borrado)
    # Cada letra lleva la caja del bloque entero (aquí, su única línea): el borrador la barre con un solo frente.
    assert len({(e.x, e.y, e.w, e.h) for e in borrado}) == 1
    # El control: el que no se borra se queda hasta que la pizarra se va, sin borrador.
    assert all(e.anim["sale"] == "nada" and "ds" not in e.anim for e in queda)
    fin_del_plano = linea.total + AJUSTES["transicion"]["cambio_de_tema_s"]
    assert all(e.t1 == pytest.approx(fin_del_plano, abs=1e-3) for e in queda)


def test_las_lineas_de_un_bloque_llevan_la_caja_del_bloque_y_el_borrador_un_solo_frente(tmp_path):
    g, pz, _ = _pizarra_abierta(tmp_path)
    texto = "How Does Compound Interest Grow Your Money?"
    bloque = pz.mide(texto, tam="titulo", ancho_max=1600)
    pz.texto(texto, 1344, 600, 1.0, tam="titulo", clase="tiza", alinea="centro", ancho_max=1600, borra=6.0)
    # Las dos líneas, a dos alturas, con la misma caja a lo ancho: la de la línea más ancha, centrada en x.
    assert bloque.lineas == 2 and len({e.y for e in g.elementos}) == 2
    assert len({(e.x, e.w) for e in g.elementos}) == 1
    e = g.elementos[0]
    assert e.w == pytest.approx(bloque.ancho + 2 * 0.25 * 120) and e.x + e.w / 2 == pytest.approx(1344)


def test_control_un_texto_no_se_borra_antes_de_quedar_escrito_ni_despues_de_que_la_pizarra_se_vaya(tmp_path):
    g, pz, linea = _pizarra_abierta(tmp_path)
    dura = pz.mide("Title", tam="titulo").escribe_s
    with pytest.raises(pizarra.ErrorDePizarra, match="no acaba de escribirse"):
        pz.texto("Title", 1344, 700, 1.0, tam="titulo", clase="tiza", alinea="centro", borra=1.0 + dura - 0.05)
    with pytest.raises(pizarra.ErrorDePizarra, match="se va en"):
        pz.texto("Title", 1344, 700, 1.0, tam="titulo", clase="tiza", alinea="centro", borra=linea.total - 0.3)
    assert g.elementos == []  # y no deja nada a medias
    # Justo cuando acaba de escribirse sí se puede borrar.
    pz.texto("Title", 1344, 700, 1.0, tam="titulo", clase="tiza", alinea="centro", borra=1.0 + dura)


def _titulo_en_reserva(pz, t0=1.0, borra=5.0):
    pz.reserva(t0, borra + pz.borra_s)
    return pz.texto("Title", 1344, 700, t0, tam="titulo", clase="tiza", alinea="centro", borra=borra, reservado=True)


def test_una_reserva_deja_la_pizarra_al_titulo_y_lo_de_antes_y_despues_vale(tmp_path):
    g, pz, _ = _pizarra_abierta(tmp_path)
    pz.texto("Coins & Pencils", 120, 60, 0.2, tam="nota", clase="tiza", alinea="izquierda")  # escrito antes: vale
    _titulo_en_reserva(pz, t0=2.0)
    pz.texto("Chapter", 1344, 120, 5.6, tam="titulo", clase="tiza", alinea="centro")  # justo al acabar: vale
    pz.pieza([1, 2], 6.0, funde=True)
    pz.flecha([(300, 250), (600, 300)], 6.5, clase="acento")
    pz.comprueba()


@pytest.mark.parametrize("orden", ["reserva_antes", "reserva_despues"])
def test_control_un_texto_que_aun_se_escribe_cuando_empieza_la_reserva_para(tmp_path, orden):
    """«Coins & Pencils» empieza en 0,2 s y acaba de escribirse en 1,52 s: la pizarra no está vacía en 1,0 s."""
    g, pz, _ = _pizarra_abierta(tmp_path)
    nombre = lambda: pz.texto("Coins & Pencils", 120, 60, 0.2, tam="nota", clase="tiza", alinea="izquierda")  # noqa: E731
    with pytest.raises(pizarra.ErrorDePizarra, match="no acaba de escribirse hasta 1.52 s"):
        if orden == "reserva_antes":
            pz.reserva(1.0, 5.0 + pz.borra_s)
            nombre()
        else:
            nombre()
            pz.reserva(1.0, 5.0 + pz.borra_s)


def _grafica(pz):
    pz.grafica([1, 2], caja=(1400, 600, 2400, 1300), tiempos=[2.0, 2.5], cifras=["1", "2"], etiquetas=["a", "b"],
               clase="tiza", clase_cifra="acento", tam_cifra="cifra", tam_etiqueta="nota")  # fmt: skip


LO_QUE_CHOCA = {
    "pieza que entra": (lambda pz: pz.pieza(1, 3.0, funde=True), "entra en 3.00 s, dentro de la reserva"),
    "pieza que ya está": (lambda pz: pz.pieza(1, 0.5, funde=False), "la pieza 1 ya está en la pizarra"),
    "flecha": (lambda pz: pz.flecha([(300, 250), (600, 300)], 4.0, clase="acento"), "la flecha"),
    "gráfica": (_grafica, "la gráfica"),
    "otro texto": (lambda pz: pz.texto("Other", 1344, 300, 3.0, tam="titulo", clase="tiza", alinea="centro"), "Other"),
}


@pytest.mark.parametrize("orden", ["reserva_antes", "reserva_despues"])
@pytest.mark.parametrize("cual", sorted(LO_QUE_CHOCA))
def test_control_lo_que_choca_con_una_reserva_para_en_los_dos_ordenes(tmp_path, orden, cual):
    pon, dice = LO_QUE_CHOCA[cual]
    g, pz, _ = _pizarra_abierta(tmp_path)
    if orden == "reserva_antes":
        pz.reserva(1.0, 5.6)
        with pytest.raises(pizarra.ErrorDePizarra, match=re.escape(dice)):
            pon(pz)
    else:
        pon(pz)
        with pytest.raises(pizarra.ErrorDePizarra, match=re.escape(dice)):
            pz.reserva(1.0, 5.6)


def test_control_una_pieza_de_entrada_ya_esta_cuando_empieza_la_reserva(tmp_path):
    g, pz, _ = _pizarra_abierta(tmp_path, de_entrada=[2])
    with pytest.raises(pizarra.ErrorDePizarra, match="la pieza 2 ya está en la pizarra"):
        _titulo_en_reserva(pz)


def test_control_el_texto_de_una_reserva_tiene_que_caber_en_ella_y_ser_el_unico(tmp_path):
    g, pz, _ = _pizarra_abierta(tmp_path)
    with pytest.raises(pizarra.ErrorDePizarra, match="llama antes a reserva"):
        pz.texto("Title", 1344, 700, 1.0, tam="titulo", clase="tiza", alinea="centro", borra=5.0, reservado=True)
    with pytest.raises(pizarra.ErrorDePizarra, match="le falta `borra`"):
        pz.texto("Title", 1344, 700, 1.0, tam="titulo", clase="tiza", alinea="centro", reservado=True)
    pz.reserva(1.0, 5.0)
    with pytest.raises(pizarra.ErrorDePizarra, match="lo contiene entero"):  # acabaría de borrarse fuera de ella
        pz.texto("Title", 1344, 700, 1.0, tam="titulo", clase="tiza", alinea="centro", borra=5.0, reservado=True)
    pz.texto("Title", 1344, 700, 1.0, tam="titulo", clase="tiza", alinea="centro", borra=4.4, reservado=True)
    with pytest.raises(pizarra.ErrorDePizarra, match="ya es del texto «Title»"):
        pz.texto("Again", 1344, 300, 1.2, tam="nota", clase="tiza", alinea="centro", borra=4.0, reservado=True)
    with pytest.raises(pizarra.ErrorDePizarra, match="se solapa"):
        pz.reserva(4.5, 6.0)
    with pytest.raises(pizarra.ErrorDePizarra, match="se sale de la pizarra"):
        pz.reserva(5.0, 999.0)


def _suave(p: float) -> float:
    return p * p * (3 - 2 * p)


@pytest.mark.skipif(NODE is None, reason="no hay node en esta máquina")
def test_el_borrador_del_motor_barre_de_0_a_1_y_sin_borrar_no_hay_clip():
    """`Motor.elemento(...).borra`: lo barrido desde el borde izquierdo, con la curva suave, en los últimos `ds` s."""
    r = _motor(
        "const e = Object.assign({}, G.elementos[0], {id: 'b', t0: 0.1, t1: 1.3, sale: 'borra', ds: 0.6, "
        "bucle: undefined}); const f = Object.assign({}, e, {id: 'f', sale: 'fade'}); G.elementos.push(e, f);"
        "const M = Motor.crea(G);"
        "return [0.5, 0.7, 0.85, 1.0, 1.15, 1.3].map((t) => [t, M.elemento(e, t).borra, M.elemento(e, t).o, "
        "M.elemento(f, t).borra, M.elemento(f, t).o]);"
    )
    assert r["codigo"] == 0, r["error"]
    for t, barrido, o, barrido_fade, o_fade in r["salida"]:
        p = (t - 0.7) / 0.6
        if p <= 0:
            assert barrido is None  # sin borrar, el director quita el clip
        else:
            assert barrido == pytest.approx(_suave(min(p, 1.0)), abs=1e-9)
        assert o == 1  # el borrador no desvanece: recorta
        # El control: con «fade» no hay barrido, y la opacidad baja.
        assert barrido_fade is None and (o_fade < 1 if p > 0 else o_fade == 1)
    barridos = {round(x[0], 2): x[1] for x in r["salida"]}
    assert barridos[0.7] is None and barridos[1.0] == pytest.approx(0.5) and barridos[1.3] == 1


def test_el_director_solo_recorta_lo_que_se_borra():
    """El clip-path lo pinta el director en el navegador, y solo en los elementos que salen con «borra»: los demás no
    cambian ni un estilo. Que se ve barrido lo comprueba la hoja de la parada 2 de la muestra del formato."""
    director = (MOTOR.parent / "director.js").read_text(encoding="utf-8")
    assert 'borra: e.sale === "borra"' in director
    assert 'if (x.borra) x.nodo.style.clipPath = r.borra == null ? "none" : `inset(0 0 0 ${' in director
