"""`lib/escena/compone.py`: la composición lleva el CSS del canal, nada remoto y nada de `mix-blend-mode` (F6.2a).

Las pruebas no necesitan Chrome: miran el HTML que se escribe. Cada garantía lleva su control negativo, que
mete a propósito lo prohibido y comprueba que compone para en vez de escribir.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from utiles_escena import CSS_PRUEBA, guion_min, sha256

from lib import config
from lib.escena import campos, compone, etapas


class _Pedidos(HTMLParser):
    """Todo `src` y `href` de la página, incluidos los de <script>."""

    def __init__(self) -> None:
        super().__init__()
        self.valores: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.valores += [v for k, v in attrs if k in ("src", "href") and v]


def _css(tmp_path: Path, texto: str) -> Path:
    ruta = tmp_path / "canal.css"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


# ------------------------------------------------------------------------------------------ la buena
def test_la_pagina_lleva_el_css_del_canal_que_se_le_pasa(composicion):
    pagina = (composicion / "index.html").read_text(encoding="utf-8")
    assert CSS_PRUEBA.read_text(encoding="utf-8").strip() in pagina
    assert "marca-del-canal-de-prueba" in pagina
    # El karaoke pinta con la clase del hablante, y el color lo pone ese CSS (.w.h-voz1), no el estudio.
    assert 'class="w h-voz1"' in pagina


def test_la_pagina_no_referencia_nada_remoto(composicion):
    pagina = (composicion / "index.html").read_text(encoding="utf-8")
    # Ni un esquema de red en todo el fichero, código incluido: el motor, las mallas y el director no llevan
    # ninguno, y GSAP (que sí lleva su URL de licencia en un comentario) va aparte.
    assert not re.findall(r"[A-Za-z][A-Za-z0-9+.-]*://", pagina)
    assert not re.search(r"""(src|href)=["']//""", pagina)
    lector = _Pedidos()
    lector.feed(pagina)
    assert lector.valores, "la página no pide nada: la prueba no estaría mirando"
    for valor in lector.valores:
        assert (composicion / valor).is_file(), f"la página pide {valor} y no está en la composición"


def test_con_muchos_planos_ninguno_tapa_la_pantalla(tmp_path, assets_min):
    """El piloto de F6.8 tenía 102 planos: desde el 41, cada uno tapaba los rótulos, el karaoke y las cortinas."""
    g = guion_min()
    base = g["planos"][1]  # el que entra con fundido y lleva un actor
    g["planos"] = g["planos"][:1] + [
        {**base, "id": f"q{i}", "t0": round(0.9 + i * 0.01, 3), "t1": 1.5, "actores": []} for i in range(60)
    ]
    pagina = compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp").read_text(encoding="utf-8")
    ordenes = [int(z) for z in re.findall(r'class="clip plano"[^>]*z-index:(\d+)', pagina)]
    pantalla = int(re.search(r"#pantalla \{[^}]*z-index: (\d+)", compone.CSS_ESTUDIO).group(1))
    # La prueba sabe fallar: con 61 planos el orden de alguno pasa del de la pantalla.
    assert len(ordenes) == 61 and max(ordenes) > pantalla
    # Y aun así ninguno compite con ella: todos van dentro de #planos, que es su contexto de apilado, por debajo.
    dentro = pagina.split('<div id="planos">', 1)[1].split('<div id="pantalla">', 1)[0]
    assert len(re.findall(r'class="clip plano"', dentro)) == 61
    assert re.search(r"#planos \{[^}]*position: absolute;[^}]*z-index: 0;", compone.CSS_ESTUDIO)


def test_la_pagina_no_lleva_mix_blend_mode(composicion):
    assert "mix-blend-mode" not in (composicion / "index.html").read_text(encoding="utf-8").lower()


def test_gsap_va_como_fichero_local_con_su_licencia(composicion):
    copia = composicion / compone.GSAP_EN_LA_COMPOSICION
    assert sha256(copia) == sha256(config.MOTOR_ESCENA_GSAP)
    cabecera = config.MOTOR_ESCENA_GSAP.read_text(encoding="utf-8")[:400]
    assert "GSAP 3.14.2" in cabecera and "@license" in cabecera and "standard-license" in cabecera
    assert f'<script src="{compone.GSAP_EN_LA_COMPOSICION}"></script>' in (composicion / "index.html").read_text(
        encoding="utf-8"
    )


def test_gsap_sale_de_npm_y_no_del_repositorio():
    """Su licencia no deja redistribuirlo (OC1.2): se instala con `npm ci` y el motor lo lee de ahí."""
    assert config.MOTOR_ESCENA_GSAP.relative_to(config.MOTOR_ESCENA_DIR).parts[:2] == ("node_modules", "gsap")
    assert not (config.MOTOR_ESCENA_DIR / "vendor").exists()


def test_control_sin_gsap_instalado_compone_para_y_dice_como_instalarlo(tmp_path, assets_min, monkeypatch):
    monkeypatch.setattr(config, "MOTOR_ESCENA_GSAP", tmp_path / "no-instalado" / "gsap.min.js")
    with pytest.raises(compone.ErrorDeComposicion, match="no está GSAP .*npm ci"):
        compone.compone(guion_min(), assets_min, CSS_PRUEBA, tmp_path / "comp")


def test_el_guion_de_la_pagina_es_el_que_lee_el_motor(composicion):
    g = compone.lee_guion(composicion / "index.html")
    assert g["fps"] == 24 and [p["id"] for p in g["planos"]] == ["p1", "p2"]
    # Lo que solo servía para el DOM no va duplicado en el JSON.
    assert all("html" not in e for e in g["elementos"])
    assert "titulo" not in g and "idioma" not in g
    # El plano 1 se queda en pantalla mientras entra el 2 con su fundido (0,9 + 0,25).
    assert g["planos"][0]["t1"] == pytest.approx(1.15)
    # Hay mallas, así que la composición exige WebGPU de hardware a HyperFrames.
    assert "data-requires-webgpu" in (composicion / "index.html").read_text(encoding="utf-8")


def test_el_css_del_estudio_no_lleva_colores_ni_tipografias():
    """El esqueleto es del estudio; todo lo que se ve de un color o una letra es del canal (F4.9)."""
    css = compone.CSS_ESTUDIO
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    assert not re.search(r"rgba?\(|hsla?\(", css)
    assert "font" not in css
    assert not re.search(r"background\s*:", css)


# ------------------------------------------------------------------------------------------ controles
def test_control_mix_blend_mode_en_el_css_del_canal_para(tmp_path, assets_min):
    css = _css(tmp_path, CSS_PRUEBA.read_text(encoding="utf-8") + "\n.velo { mix-blend-mode: screen; }\n")
    with pytest.raises(compone.ErrorDeComposicion, match="mix-blend-mode"):
        compone.compone(guion_min(), assets_min, css, tmp_path / "comp")
    assert not (tmp_path / "comp" / "index.html").exists()


def test_control_mix_blend_mode_en_el_html_del_guion_para(tmp_path, assets_min):
    g = guion_min()
    g["elementos"][0]["html"] = '<div style="mix-blend-mode:multiply">x</div>'
    with pytest.raises(compone.ErrorDeComposicion, match="mix-blend-mode"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


@pytest.mark.parametrize(
    "html",
    [
        '<img src="https://remoto.invalid/x.png">',
        '<img src="//remoto.invalid/x.png">',
        '<img srcset="assets/img/rueda.png 1x, https://remoto.invalid/x.png 2x">',
        '<script src="https://remoto.invalid/x.js"></script>',
        '<svg><image href="http://remoto.invalid/x.png"/></svg>',
        '<div style="background:url(https://remoto.invalid/x.png)"></div>',
        '<img src="file:///C:/fuera/x.png">',
        '<img src="C:\\fuera\\x.png">',
        '<img src="../fuera.png">',
        '<img src="assets/img/no-esta.png">',
        '<link rel="stylesheet" href="assets/img/rueda.png">',
        '<iframe src="about:blank"></iframe>',
    ],
)
def test_control_una_referencia_que_no_es_de_la_composicion_para(tmp_path, assets_min, html):
    g = guion_min()
    g["elementos"][0]["html"] = html
    with pytest.raises(compone.ErrorDeComposicion):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")
    assert not (tmp_path / "comp" / "index.html").exists()


@pytest.mark.parametrize(
    "regla",
    [
        '@import url("https://remoto.invalid/x.css");',
        "@import '//remoto.invalid/x.css';",
        '@font-face { font-family: "X"; src: url("https://remoto.invalid/x.woff2"); }',
    ],
)
def test_control_el_css_del_canal_no_puede_pedir_nada_de_fuera(tmp_path, assets_min, regla):
    css = _css(tmp_path, regla + "\n" + CSS_PRUEBA.read_text(encoding="utf-8"))
    with pytest.raises(compone.ErrorDeComposicion):
        compone.compone(guion_min(), assets_min, css, tmp_path / "comp")


def test_el_css_del_canal_puede_cargar_sus_fuentes_si_van_en_los_assets(tmp_path, assets_min):
    """La otra cara del control anterior: un url() local y declarado pasa, y se copia."""
    fuente = tmp_path / "letra.woff2"
    fuente.write_bytes(b"wOF2 de prueba")
    css = _css(tmp_path, '@font-face { font-family: "X"; src: url("assets/fonts/letra.woff2"); }\n')
    index = compone.compone(guion_min(), {**assets_min, "assets/fonts/letra.woff2": fuente}, css, tmp_path / "comp")
    assert (index.parent / "assets/fonts/letra.woff2").read_bytes() == b"wOF2 de prueba"


@pytest.mark.parametrize("clave", list(compone.OBLIGATORIOS))
def test_sin_una_decision_del_guion_no_se_compone_y_dice_cual(tmp_path, assets_min, clave):
    g = guion_min()
    del g[clave]
    with pytest.raises(compone.ErrorDeComposicion, match=f"«{clave}»"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


def test_un_fichero_que_pide_el_guion_y_no_esta_en_los_assets_para(tmp_path, assets_min):
    faltan = {k: v for k, v in assets_min.items() if k != "assets/rig/cinta.png"}
    with pytest.raises(compone.ErrorDeComposicion, match="cinta.png"):
        compone.compone(guion_min(), faltan, CSS_PRUEBA, tmp_path / "comp")


def test_un_id_repetido_o_que_no_sirve_de_selector_para(tmp_path, assets_min):
    g = guion_min()
    g["elementos"][0]["id"] = "a1"
    with pytest.raises(compone.ErrorDeComposicion, match="ya lo usa"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")
    g = guion_min()
    g["karaoke"][0]["id"] = "k 0"
    with pytest.raises(compone.ErrorDeComposicion, match="selector"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


def test_el_texto_del_guion_no_puede_cerrar_el_script_del_guion(tmp_path, assets_min):
    """Un texto de karaoke con «</script>» no rompe la página: el JSON va escapado."""
    g = guion_min()
    g["karaoke"][0]["w"][0][2] = "</script><img src=https://remoto.invalid/x>"
    index = compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")
    pagina = index.read_text(encoding="utf-8")
    assert pagina.count("</script>") == 3  # GSAP, el GUION y el motor
    assert compone.lee_guion(index)["karaoke"][0]["w"][0][2] == g["karaoke"][0]["w"][0][2]
    # En el DOM va como texto, así que el navegador no ve ninguna imagen remota.
    lector = _Pedidos()
    lector.feed(pagina)
    assert not [v for v in lector.valores if "remoto" in v]


# ------------------------------------------------------------------------------------------ auditoría de F6.2a
@pytest.mark.parametrize(
    "html",
    [
        "<script>window.x = 1;</script>",
        "<SCRIPT src='assets/img/rueda.png'></SCRIPT>",
        '<img src="assets/img/rueda.png" onerror="window.x = 1">',
        '<div onclick="window.x = 1">x</div>',
        '<svg onload="window.x = 1"></svg>',
        '<div OnMouseOver="window.x = 1">x</div>',
    ],
)
def test_control_el_html_del_guion_no_puede_llevar_codigo(tmp_path, assets_min, html):
    """Recomendación 6: el html de un elemento es texto de datos, y la sonda solo ve lo que corre en t = 0."""
    g = guion_min()
    g["elementos"][0]["html"] = html
    with pytest.raises(compone.ErrorDeComposicion, match="lleva código"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


def test_control_el_extra_de_un_plano_tampoco(tmp_path, assets_min):
    g = guion_min()
    g["planos"][0]["extra"] = '<div class="velo" onanimationend="window.x = 1"></div>'
    with pytest.raises(compone.ErrorDeComposicion, match="extra del plano p1"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


def test_html_sin_codigo_pasa_aunque_diga_script_o_on_en_el_texto(tmp_path, assets_min):
    """La otra cara: la palabra en el TEXTO, o un atributo que solo empieza parecido, no es código."""
    g = guion_min()
    g["elementos"][0]["html"] = '<div class="caja" data-once="1">the script is on the table</div>'
    compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


def test_control_un_tipo_de_malla_desconocido_para(tmp_path, assets_min):
    """Recomendación 4: con el nombre viejo, la pieza habría salido rígida sin que nadie lo viera."""
    g = guion_min()
    g["rig"]["piezas"]["cuerpo"]["tipo"] = "perro"
    with pytest.raises(compone.ErrorDeComposicion, match="«perro»"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


def test_control_un_tipo_de_evento_desconocido_para(tmp_path, assets_min):
    g = guion_min()
    g["planos"][0]["actores"][0]["eventos"][0]["tipo"] = "baile"
    with pytest.raises(compone.ErrorDeComposicion, match="«baile»"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


# ------------------------------------------------------------------ F6.2b
@pytest.mark.parametrize("ruta", ["habla.rebote", "eventos.risa.a", "elementos.entra"])
def test_sin_una_magnitud_del_movimiento_no_se_compone_y_dice_cual(tmp_path, assets_min, ruta):
    g = guion_min()
    *camino, ultima = ruta.split(".")
    nodo = g["movimiento"]
    for parte in camino:
        nodo = nodo[parte]
    del nodo[ultima]
    with pytest.raises(compone.ErrorDeComposicion, match=f"«{ruta}»"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


def test_control_un_booleano_no_es_una_magnitud(tmp_path, assets_min):
    """`True` es un int en Python y en JavaScript no es un número: el motor lo rechazaría en el navegador."""
    g = guion_min()
    g["movimiento"]["habla"]["rebote"] = True
    with pytest.raises(compone.ErrorDeComposicion, match="«habla.rebote»"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


@pytest.mark.parametrize(("campo", "valor"), [("entra", "zoom"), ("sale", "explota"), ("bucle", "baila")])
def test_control_una_animacion_de_elemento_desconocida_para(tmp_path, assets_min, campo, valor):
    g = guion_min()
    g["elementos"][0][campo] = valor
    with pytest.raises(compone.ErrorDeComposicion, match=f"«{valor}»"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


def test_control_un_plano_que_entra_de_una_forma_desconocida_para(tmp_path, assets_min):
    g = guion_min()
    g["planos"][1]["entra"]["tipo"] = "cortinilla"
    with pytest.raises(compone.ErrorDeComposicion, match="«cortinilla»"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


def test_control_un_cuadrupedo_sin_el_meneo_de_su_cola_para(tmp_path, assets_min):
    g = guion_min()
    del g["rig"]["piezas"]["cuerpo"]["cola_freq"]
    with pytest.raises(compone.ErrorDeComposicion, match="cola_freq"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


# Auditoría de F6.2b, recomendación 1: lo que divide no puede ser 0 (el motor daría NaN).
@pytest.mark.parametrize("ruta", list(compone.DIVISORES))
def test_control_una_magnitud_que_divide_a_cero_no_se_compone(tmp_path, assets_min, ruta):
    g = guion_min()
    *camino, ultima = ruta.split(".")
    nodo = g["movimiento"]
    for parte in camino:
        nodo = nodo[parte]
    nodo[ultima] = 0
    with pytest.raises(compone.ErrorDeComposicion, match=f"«{ruta}»"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")
    nodo[ultima] = 0.001  # control: positivo, pasa
    compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


@pytest.mark.parametrize(
    ("donde", "campo"),
    [("actor", "v_anda"), ("elemento", "di"), ("elemento", "trazo_d"), ("elemento", "campana_p")],
)
def test_control_lo_que_se_sobrescribe_tampoco_puede_ser_cero(tmp_path, assets_min, donde, campo):
    g = guion_min()
    nodo = g["planos"][0]["actores"][0]["rasgos"] if donde == "actor" else g["elementos"][0]
    nodo[campo] = 0
    with pytest.raises(compone.ErrorDeComposicion, match=campo):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")
    nodo[campo] = 0.5
    compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")


# ------------------------------------------------------------------ F6.8: las entradas de tinta
# Un plano que entra por umbral lleva su máscara SVG y su campo de gris, que pone el estudio; uno que entra con papel,
# su velo, cuyo color es del canal. Una composición sin ellas sale como antes.
CSS_CON_PAPEL = CSS_PRUEBA.read_text(encoding="utf-8") + "\n.plano > .papel { background: #fbf6ea; }\n"


def _entra(g: dict, tipo: str, direccion=None, d: float = 0.5) -> dict:
    g["planos"][1]["entra"] = {"tipo": tipo, "d": d, **({"dir": direccion} if direccion is not None else {})}
    return g


def test_un_plano_que_entra_con_mancha_lleva_su_mascara_y_su_campo(tmp_path, assets_min):
    index = compone.compone(_entra(guion_min(), "mancha"), assets_min, CSS_PRUEBA, tmp_path / "comp")
    pagina = index.read_text(encoding="utf-8")
    assert '<feFuncA id="p2-umbral" type="linear"' in pagina
    assert '<mask id="p2-m" style="mask-type:alpha" maskUnits="userSpaceOnUse"' in pagina
    assert 'color-interpolation-filters="sRGB"' in pagina and 'type="luminanceToAlpha"' in pagina
    assert '<feImage href="assets/estudio/campo-mancha.png" x="0" y="0" width="1920" height="1080"' in pagina
    # La precarga: HyperFrames espera a las <img> antes de fotografiar.
    assert '<div class="campos" hidden><img src="assets/estudio/campo-mancha.png" alt=""></div>' in pagina
    im = Image.open(index.parent / "assets/estudio/campo-mancha.png")
    assert (im.size, im.mode) == ((campos.ANCHO, campos.ALTO), "L")
    assert np.array_equal(np.asarray(im), campos.gris("mancha"))
    # Solo los campos que usa algún plano.
    assert sorted(p.name for p in (index.parent / "assets/estudio").iterdir()) == ["campo-mancha.png"]


@pytest.mark.parametrize(
    ("tipo", "direccion", "campo"),
    [("mancha", None, "mancha"), ("calado", None, "calado"), ("viento", "derecha", "viento-derecha"),
     ("viento", "izquierda", "viento-izquierda")],
)  # fmt: skip
def test_cada_campo_sale_identico_en_cada_composicion(tmp_path, assets_min, tipo, direccion, campo):
    a = compone.compone(_entra(guion_min(), tipo, direccion), assets_min, CSS_PRUEBA, tmp_path / "a").parent
    b = compone.compone(_entra(guion_min(), tipo, direccion), assets_min, CSS_PRUEBA, tmp_path / "b").parent
    ruta = campos.ruta(campo)
    assert sha256(a / ruta) == sha256(b / ruta)
    assert etapas.huella_de_composicion(a) == etapas.huella_de_composicion(b)


def test_los_campos_tienen_la_forma_de_su_transicion():
    mancha, calado = campos.gris("mancha") / 255, campos.gris("calado") / 255
    derecha, izquierda = campos.gris("viento-derecha") / 255, campos.gris("viento-izquierda") / 255
    assert mancha.min() >= 0 and mancha.max() <= 1 and mancha.std() > 0.15  # manchas, no un gris liso
    # El ruido del calado es uniforme: cada décima del gris tiene su 10 % de puntos.
    reparto = np.histogram(calado, bins=10, range=(0, 1))[0] / calado.size
    assert np.allclose(reparto, 0.1, atol=0.01)
    # El viento avanza en su dirección (el gris sube hacia donde va el frente) y cada fila llega a su hora.
    assert derecha[:, :50].mean() < 0.3 < 0.7 < derecha[:, -50:].mean()
    assert izquierda[:, :50].mean() > 0.7 > 0.3 > izquierda[:, -50:].mean()
    assert np.ptp(derecha[:, 480]) > 0.15 and np.ptp(derecha[100, 470:490]) < 0.05


def test_la_huella_de_la_composicion_cubre_los_campos(tmp_path, assets_min):
    carpeta = compone.compone(_entra(guion_min(), "calado"), assets_min, CSS_PRUEBA, tmp_path / "comp").parent
    antes = etapas.huella_de_composicion(carpeta)
    Image.fromarray(255 - campos.gris("calado")).save(carpeta / campos.ruta("calado"), format="PNG")
    assert etapas.huella_de_composicion(carpeta) != antes


def test_control_sin_entradas_de_tinta_la_pagina_no_lleva_nada_de_ellas(composicion):
    pagina = (composicion / "index.html").read_text(encoding="utf-8")
    assert 'class="tinta"' not in pagina and 'class="papel"' not in pagina and compone.CSS_PAPEL not in pagina
    assert not (composicion / campos.CARPETA).exists()


def test_control_un_campo_que_no_esta_en_la_composicion_lo_para_el_revisor(tmp_path, assets_min):
    """El `href` del feImage pasa la revisión porque el campo está en la composición; sin él, para como cualquier
    otro fichero que la página pida y no esté."""
    pagina = compone.compone(_entra(guion_min(), "mancha"), assets_min, CSS_PRUEBA, tmp_path / "c").read_text("utf-8")
    sin_campo = set(assets_min) | {compone.GSAP_EN_LA_COMPOSICION}
    with pytest.raises(compone.ErrorDeComposicion, match="campo-mancha.png"):
        compone.revisa_pagina(pagina, sin_campo)
    compone.revisa_pagina(pagina, sin_campo | {campos.ruta("mancha")})


def test_control_un_asset_del_canal_no_puede_ir_en_la_carpeta_de_los_campos(tmp_path, assets_min):
    otro = {**assets_min, "assets/estudio/campo-mancha.png": next(iter(assets_min.values()))}
    with pytest.raises(compone.ErrorDeComposicion, match="assets/estudio"):
        compone.compone(_entra(guion_min(), "mancha"), otro, CSS_PRUEBA, tmp_path / "comp")


def test_un_campo_de_otra_composicion_en_la_misma_carpeta_sale(tmp_path, assets_min):
    destino = tmp_path / "comp"
    compone.compone(_entra(guion_min(), "calado"), assets_min, CSS_PRUEBA, destino)
    compone.compone(_entra(guion_min(), "mancha"), assets_min, CSS_PRUEBA, destino)
    assert sorted(p.name for p in (destino / campos.CARPETA).iterdir()) == ["campo-mancha.png"]


def test_el_papel_lleva_su_velo_y_su_color_lo_pone_el_canal(tmp_path, assets_min):
    css = _css(tmp_path, CSS_CON_PAPEL)
    pagina = compone.compone(_entra(guion_min(), "papel"), assets_min, css, tmp_path / "comp").read_text("utf-8")
    assert compone.CSS_PAPEL in pagina
    assert re.search(r'<div id="p2" class="clip plano".*?<div class="papel"></div></div>', pagina, re.DOTALL)
    assert pagina.count('class="papel"') == 1  # solo en el plano que entra con papel


@pytest.mark.parametrize(
    "css_extra",
    [
        "",
        ".tr.papel { background: #fbf6ea; }",  # la cortina de la TRANSICIÓN «papel», no el velo
        ".plano > .papel { opacity: 1; }",  # sin color
        "/* .plano > .papel { background: #fbf6ea; } */",
    ],
)
def test_control_un_plano_que_entra_con_papel_sin_el_color_del_canal_para(tmp_path, assets_min, css_extra):
    css = _css(tmp_path, CSS_PRUEBA.read_text(encoding="utf-8") + "\n" + css_extra + "\n")
    with pytest.raises(compone.ErrorDeComposicion, match=r"\.plano > \.papel \{ background"):
        compone.compone(_entra(guion_min(), "papel"), assets_min, css, tmp_path / "comp")
    assert not (tmp_path / "comp" / "index.html").exists()


@pytest.mark.parametrize(
    ("tipo", "direccion", "mensaje"),
    [
        ("cortina", None, "tiene que decir hacia dónde"),
        ("cortina", "abajo", "tiene que decir hacia dónde"),
        ("viento", "arriba", "tiene que decir hacia dónde"),
        ("calado", "derecha", "no lleva dirección"),
        ("funde", "izquierda", "no lleva dirección"),
        ("barrido", 2, "1 o -1"),
        ("barrido", True, "1 o -1"),
    ],
)
def test_control_una_direccion_que_falta_o_no_vale_no_se_compone(tmp_path, assets_min, tipo, direccion, mensaje):
    with pytest.raises(compone.ErrorDeComposicion, match=f"El plano p2 entra con «{tipo}».*{mensaje}"):
        compone.compone(_entra(guion_min(), tipo, direccion), assets_min, CSS_PRUEBA, tmp_path / "comp")


@pytest.mark.parametrize(
    ("tipo", "direccion"),
    [("cortina", "derecha"), ("cortina", "izquierda"), ("cortina", "arriba"), ("viento", "izquierda"),
     ("barrido", -1), ("barrido", None), ("funde", None)],
)  # fmt: skip
def test_con_su_direccion_cada_entrada_se_compone(tmp_path, assets_min, tipo, direccion):
    compone.compone(_entra(guion_min(), tipo, direccion), assets_min, CSS_PRUEBA, tmp_path / "comp")


def test_control_un_id_que_choca_con_la_mascara_de_un_plano_para(tmp_path, assets_min):
    g = _entra(guion_min(), "viento", "derecha")
    g["elementos"][0]["id"] = "p2-m"
    with pytest.raises(compone.ErrorDeComposicion, match="máscara del plano p2"):
        compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "comp")
