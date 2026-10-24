"""El lenguaje de escena (`lib/escena/escena.py`) y sus ayudantes (`lib/escena/ayudas.py`), F6.2b.

Tres cosas que se prueban aquí:

1. **Lo que escribe es un GUION que el motor acepta**: `Guion.datos()` pasa `compone.valida` (y, en
   `test_extremo_a_extremo.py`, `Motor.crea` en Node).
2. **Sin defecto de canal**: el bloque `escena` se exige entero, y un ayudante sin su disposición no arranca.
3. **Lo que el motor no sabe hacer para al escribirlo**, con su nombre: un evento, una curva, una entrada, un
   rasgo o un campo mal escrito caerían en el caso por omisión del motor sin que nadie lo viera.
"""

from __future__ import annotations

import pytest
from utiles_escena import CATALOGO_PRUEBA, TARJETA_PRUEBA, escena_prueba

from lib.escena import ajustes, ayudas, compone
from lib.escena.escena import ErrorDeEscena, Guion


def _guion(**cambios) -> Guion:
    datos = {"titulo": "Prueba", "idioma": "en", "escena": escena_prueba(), "catalogo": CATALOGO_PRUEBA, "iconos": {}}
    return Guion(**{**datos, **cambios})


def _con_un_plano():
    g = _guion()
    g.fondo("parque", img="parque", suelo=[(0, 1080), (2400, 1080), (2400, 1350), (0, 1350)], px_u=500)
    p = g.plano("parque", 0, 4)
    p.cam(0, 1200, 700, 1.0, tr=0)
    return g, p


# ------------------------------------------------------------------ el GUION que sale
def test_datos_es_un_guion_que_compone_acepta():
    g, p = _con_un_plano()
    a = g.actor(p, ["ana_pie", "ana_brazos"], 800, 1200, escala=1.2, pj="ana", anda=True)
    a.clave(1.0, 0.8, "suave", x=1100).clave(2.0, 0, post="ana_brazos", fp=0)
    a.ev("salto", 2.5, 0.4, h=40)
    ayudas.tarjeta(g, "kite", "rueda", 0.5, **TARJETA_PRUEBA)
    g.transicion("destello", 3.5, 0.4, sonido=None)
    datos = g.datos(duracion=4.0)
    compone.valida(datos)
    assert datos["movimiento"] == escena_prueba()["movimiento"]
    assert datos["planos"][0]["fondo"]["suelo"] == [(0, 1080), (2400, 1080), (2400, 1350), (0, 1350)]


def test_cada_clave_sale_completa_y_lo_que_es_de_una_clave_no_se_arrastra():
    g, p = _con_un_plano()
    a = g.actor(p, ["ana_pie", "ana_brazos"], 800, 1200, escala=1.0)
    a.clave(1.0, 0.5, x=900).clave(2.0, 0, post="ana_brazos", fp=0).clave(3.0, 0.3, y=1150)
    pista = g.datos(duracion=4)["planos"][0]["actores"][0]["pista"]
    assert [(k["x"], k["y"], k["post"]) for k in pista] == [
        (800, 1200, "ana_pie"),
        (900, 1200, "ana_pie"),
        (900, 1200, "ana_brazos"),
        (900, 1150, "ana_brazos"),
    ]
    assert "fp" in pista[2] and "fp" not in pista[3]


def test_dos_claves_a_la_vez_con_transicion_dejan_un_aviso():
    g, p = _con_un_plano()
    g.actor(p, "ana_pie", 800, 1200, escala=1.0).clave(1.0, 0.5, x=900).clave(1.0, 0, x=950)
    g.datos(duracion=4)
    assert len(g.avisos) == 1 and "se pierde" in g.avisos[0]


def test_datos_devuelve_una_copia():
    """`encuadre.corrige` cambia la cámara del GUION: no puede tocar el guion ni el perfil del canal."""
    g, _ = _con_un_plano()
    datos = g.datos(duracion=4)
    datos["planos"][0]["camara"][0]["z"] = 9
    datos["movimiento"]["habla"]["rebote"] = 99
    assert g.planos[0].camara[0]["z"] == 1.0 and g.escena["movimiento"]["habla"]["rebote"] == 7


def test_sin_camara_o_sin_duracion_no_hay_guion():
    g = _guion()
    g.fondo("parque", img="parque", suelo=None)
    g.plano("parque", 0, 4)
    with pytest.raises(ErrorDeEscena, match="no tiene ninguna clave de cámara"):
        g.datos(duracion=4)
    with pytest.raises(ErrorDeEscena, match="hay que dar la duración"):
        _con_un_plano()[0].datos()


# ------------------------------------------------------------------ sin defecto de canal
@pytest.mark.parametrize("ruta", ["movimiento.habla.rebote", "pausas.cola_s", "karaoke.no_cierran", "reparto", "fps"])
def test_sin_una_decision_del_canal_el_guion_no_arranca_y_dice_cual(ruta):
    esc = escena_prueba()
    nodo = esc
    *camino, ultima = ruta.split(".")
    for parte in camino:
        nodo = nodo[parte]
    del nodo[ultima]
    with pytest.raises(ajustes.ErrorDeAjustes, match=f"«{ruta}»"):
        _guion(escena=esc)


def test_el_bloque_de_escena_sale_del_perfil_y_sin_perfil_para():
    assert ajustes.exige({"escena": escena_prueba()})["narrador"] == "narrador"
    with pytest.raises(ajustes.ErrorDeAjustes, match="no existe"):
        ajustes.exige({"idioma": {}})


@pytest.mark.parametrize(
    ("cambio", "error"),
    [
        ({"reparto": {"Ana": "ana gomez"}}, "clase CSS"),
        ({"narrador": "ana"}, "a la vez el narrador"),
        ({"karaoke": {**escena_prueba()["karaoke"], "conjunciones": "and"}}, "karaoke.conjunciones"),
    ],
)
def test_el_reparto_y_las_listas_se_comprueban(cambio, error):
    with pytest.raises(ajustes.ErrorDeAjustes, match=error):
        _guion(escena={**escena_prueba(), **cambio})


def test_un_ayudante_sin_su_disposicion_no_arranca():
    """La disposición es del canal: sin `etiqueta` (el «NEW WORD» de video_1) la tarjeta no se escribe."""
    g, _ = _con_un_plano()
    sin_etiqueta = {k: v for k, v in TARJETA_PRUEBA.items() if k != "etiqueta"}
    with pytest.raises(TypeError, match="etiqueta"):
        ayudas.tarjeta(g, "kite", "rueda", 0.5, **sin_etiqueta)


def test_el_actor_necesita_su_tamano_y_la_camara_su_tiempo():
    g, p = _con_un_plano()
    with pytest.raises(ErrorDeEscena, match="`escala` o `alto`"):
        g.actor(p, "ana_pie", 800, 1200)
    with pytest.raises(TypeError, match="tr"):
        p.cam(1, 1200, 700, 1.2)
    # Con `alto` en unidades del set (px_u = 500): 0,8 unidades de 400 px de imagen → 1,0 px por px.
    assert g.actor(p, "ana_pie", 800, 1200, alto=0.8).escala == pytest.approx(1.0)


# ------------------------------------------------------------------ lo que el motor no sabe hacer
@pytest.mark.parametrize(
    ("accion", "nombre"),
    [
        (lambda g, p, a: a.ev("baile", 1, 1), "baile"),
        (lambda g, p, a: a.ev("salto", 1, 1), "salto"),
        (lambda g, p, a: a.clave(1, 1, "rapida", x=1), "rapida"),
        (lambda g, p, a: a.clave(1, 1, color=1), "color"),
        (lambda g, p, a: g.actor(p, "ana_pie", 1, 1, escala=1, vuela=True), "vuela"),
        (lambda g, p, a: g.el("pantalla", "x", 1, 1, 1, 1, 0, 1, entra="zoom"), "zoom"),
        (lambda g, p, a: g.el("pantalla", "x", 1, 1, 1, 1, 0, 1, velocidad=2), "velocidad"),
        (lambda g, p, a: g.plano("parque", 0, 1, entra="cortinilla"), "cortinilla"),
        (lambda g, p, a: g.transicion("espiral", 1, 1, sonido=None), "espiral"),
        (lambda g, p, a: g.actor(p, "no_existe", 1, 1, escala=1), "no_existe"),
        (lambda g, p, a: g.plano("playa", 0, 1), "playa"),
    ],
)
def test_lo_que_el_motor_no_sabe_hacer_para_al_escribirlo(accion, nombre):
    g, p = _con_un_plano()
    a = g.actor(p, "ana_pie", 800, 1200, escala=1.0)
    with pytest.raises(ErrorDeEscena, match=nombre):
        accion(g, p, a)


def test_un_elemento_en_una_capa_que_no_existe_para_al_sacar_el_guion():
    g, _ = _con_un_plano()
    g.el("p99", "<b>x</b>", 1, 1, 1, 1, 0, 1)
    with pytest.raises(ErrorDeEscena, match="p99"):
        g.datos(duracion=4)


# ------------------------------------------------------------------ ayudantes
def test_los_ayudantes_escriben_estructura_con_clases_y_el_texto_escapado():
    g, p = _con_un_plano()
    comun = {"anim": {"entra": "sube", "sale": "fade"}, "sonido": None}
    caja = {"x": 900, "y": 400, "w": 300, "h": 100}
    ayudas.tarjeta(g, "<b>kite</b>", "rueda", 0.1, articulo="a", **TARJETA_PRUEBA)
    ayudas.verbo(g, "sat", "sit", 0.2, dur=2, etiqueta="PAST SIMPLE", **caja, **comun)
    ayudas.nota(g, "GRAMMAR", "She is six.", 0.3, dur=2, **caja, **comun)
    ayudas.numero(g, "2 seconds", 0.4, dur=2, **caja, **comun)
    ayudas.contador(
        g, 0, 60, 0.5, dur=3, x=900, y=400, tam=200, unidad=("second", "seconds"), empieza_s=0.2, acaba_antes_s=0.5,
        **comun,
    )  # fmt: skip
    ayudas.capitulo(g, "PART 2", "The kite", 0.6, 2, **caja, **comun)
    ayudas.repaso(g, [("kite", "rueda")], 0.7, 2, titulo="WORDS", x=960, y=700, h=300, ancho_item=276, margen=120,
                  ancho_max=1700, **comun)  # fmt: skip
    ayudas.lupa(g, "rueda", 0.8, 2, x=900, y=400, tam=300, **comun)
    htmls = [e.html for e in g.elementos]
    raices = [h.split('"')[1] for h in htmls]
    assert raices == ["tarjeta", "verbo", "nota", "chip numero", "contador", "capitulo", "repaso", "lupa"]
    assert "&lt;b&gt;kite&lt;/b&gt;" in htmls[0] and '<span class="art">a </span>' in htmls[0]
    assert 'data-uno="second" data-varios="seconds"' in htmls[4]
    assert g.elementos[4].anim["contador"] == {"de": 0, "a": 60, "t": 0.2, "d": pytest.approx(2.3)}
    assert not any("style=" in h and ("color" in h or "#" in h) for h in htmls)
    # Los que se pueden apartar de una cara lo dicen ellos, no una lista de clases de un canal.
    assert [e.movible for e in g.elementos] == [True, True, True, True, True, False, False, True]
    compone.valida(g.datos(duracion=4))


def test_la_tarjeta_suena_con_el_sonido_que_le_da_el_canal():
    g, _ = _con_un_plano()
    ayudas.tarjeta(g, "kite", "rueda", 1.0, **TARJETA_PRUEBA)
    ayudas.tarjeta(g, "kite", "rueda", 2.0, **{**TARJETA_PRUEBA, "sonido": None})
    g.transicion("iris", 3.0, 1.0, sonido={"nombre": "whoosh", "volumen": 0.3, "desfase_s": 0.25})
    assert g.sonidos == [{"nombre": "pop", "t": 1.0, "vol": 0.22}, {"nombre": "whoosh", "t": 3.25, "vol": 0.3}]
    with pytest.raises(ErrorDeEscena, match="volumen"):
        g.suena({"nombre": "pop"}, 1)


def test_la_etiqueta_va_en_el_fondo_con_su_flecha_que_se_dibuja():
    g, p = _con_un_plano()
    e = ayudas.etiqueta(
        g, p, "kerb", 1000, 1300, 1, 3, ancho=700, alto_texto=90, sube=260, tam=0.5, z=900,
        anim={"entra": "pop", "sale": "fade"}, sonido=None,
    )  # fmt: skip
    assert e.capa == p.id and e.anim["trazo"] is True
    # La punta de la flecha (el pie del elemento) cae en el punto señalado: (1000, 1300) del fondo.
    assert (e.x + e.w / 2, e.y + e.h) == (pytest.approx(1000), pytest.approx(1300))
    assert 'viewBox="0 0 700 350"' in e.html and 'class="trazo flecha"' in e.html


def test_el_tablero_no_admite_mas_minis_de_las_que_caben_y_tapa_caras_a_proposito():
    g, _ = _con_un_plano()
    disp = {
        "columnas": 2, "filas": 1, "origen": (400, 300), "paso": (300, 230), "mini": (270, 200),
        "caja": (960, 440, 1620, 760), "anim_mini": {"entra": "pop"}, "anim_tablero": {"entra": "fade"},
        "sonido": {"nombre": "pop", "volumen": 0.16}, "sonido_cada": 2,
    }  # fmt: skip
    puestos = ayudas.tablero(g, [("kite", "rueda", 1.0), ("park", "rueda", 1.5)], 0.5, 3, **disp)
    assert all(e.tapa_caras for e in puestos) and len(g.sonidos) == 1
    assert (puestos[1].x + puestos[1].w / 2, puestos[1].y + puestos[1].h / 2) == (700, 300)
    with pytest.raises(ErrorDeEscena, match="sitio para 2"):
        ayudas.tablero(g, [("a", "rueda", 1)] * 3, 0.5, 3, **disp)


def test_lo_de_una_parte_termina_donde_empieza_su_pausa():
    g, _ = _con_un_plano()
    ayudas.tarjeta(g, "kite", "rueda", 1.0, **TARJETA_PRUEBA)  # de 1,0 a 4,0
    ayudas.tarjeta(g, "park", "rueda", 3.0, **TARJETA_PRUEBA)  # empieza después de la pausa: no se toca
    assert ayudas.recorta_en_pausas(g, [(2.5, 3.0)]) == 1
    assert [e.t1 for e in g.elementos] == [2.5, 6.0]


def test_un_punto_de_la_postura_con_su_k_su_escala_y_su_volteo():
    postura = {"k": 2.0}
    assert ayudas.punto_de_postura(1.5, postura, (100, -400)) == (75, -300)
    assert ayudas.punto_de_postura(1.5, postura, (100, -400), s=2, flip=1) == (-150, -600)


def test_las_piezas_de_una_postura_se_mecen_mientras_se_usa():
    catalogo = {
        **CATALOGO_PRUEBA,
        "ana_brazos_cola": {"src": "assets/img/rueda.png", "w": 100, "h": 100, "ax": 50, "ay": 50, "off": [40, -300]},
        "ana_brazos_base": {**CATALOGO_PRUEBA["ana_brazos"]},
    }
    g = _guion(catalogo=catalogo)
    g.fondo("parque", img="parque", suelo=None)
    p = g.plano("parque", 0, 6)
    p.cam(0, 1200, 700, 1.0, tr=0)
    ana = g.actor(p, ["ana_pie", "ana_brazos"], 800, 1200, escala=1.2, pj="ana")
    ana.clave(2.0, 0, post="ana_brazos", fp=0.2).clave(4.0, 0, post="ana_pie", fp=0.1)
    assert ayudas.piezas_de_postura(g, {"cola": (14.0, 2.6, False)}) == 1
    pieza = p.actores[-1]
    assert pieza.padre == ana.id and pieza.rasgos == {"pieza": True} and pieza.z == ana.z - 1
    assert (pieza.claves[0]["x"], pieza.claves[0]["y"]) == (pytest.approx(48), pytest.approx(-360))
    # Visible mientras Ana usa esa postura (de 2 a 4 s), con el fundido de postura de cada cambio.
    assert [(k["t"], k["tr"], k["op"]) for k in pieza.claves[1:]] == [(2.0, 0.2, 1), (4.0, 0.1, 0)]
    assert pieza.eventos == [{"tipo": "menea", "t": 0.0, "d": 6.0, "a": 14.0, "f": 2.6}]
    assert "ana_brazos_base" in [k.get("post") for k in ana.claves]  # usa la postura sin la pieza
    assert ayudas.piezas_de_postura(_guion(), {"cola": (14.0, 2.6, False)}) == 0  # control: sin pieza, nada


@pytest.mark.parametrize("ruta", list(compone.DIVISORES))
def test_el_perfil_no_puede_declarar_a_cero_lo_que_el_motor_divide(ruta):
    """Auditoría de F6.2b, recomendación 1: se para en el perfil, antes del GUION y del navegador."""
    esc = escena_prueba()
    *camino, ultima = ruta.split(".")
    nodo = esc["movimiento"]
    for parte in camino:
        nodo = nodo[parte]
    nodo[ultima] = 0
    with pytest.raises(ajustes.ErrorDeAjustes, match=f"«movimiento.{ruta}»"):
        _guion(escena=esc)
    nodo[ultima] = 0.001  # control: positivo, pasa
    _guion(escena=esc)


# ------------------------------------------------------------------ F6.8: las entradas de tinta y su dirección
def _dos_planos(entra: str, **kw):
    g, p = _con_un_plano()
    g.fondo("cielo", img="cielo", suelo=None)
    q = g.plano("cielo", 4, 6, entra=entra, d=0.6, **kw)
    q.cam(4, 960, 540, 1.0, tr=0)
    return g, q


@pytest.mark.parametrize(
    ("entra", "direccion"),
    [("cortina", "derecha"), ("cortina", "izquierda"), ("cortina", "arriba"), ("mancha", None), ("calado", None),
     ("viento", "derecha"), ("viento", "izquierda"), ("papel", None), ("barrido", -1)],
)  # fmt: skip
def test_un_plano_entra_con_cada_entrada_de_tinta_y_su_direccion(entra, direccion):
    g, _ = _dos_planos(entra, dir=direccion)
    datos = g.datos(duracion=6)
    esperado = {"tipo": entra, "d": 0.6, **({"dir": direccion} if direccion is not None else {})}
    assert datos["planos"][1]["entra"] == esperado
    compone.valida(datos)


def test_control_sin_direccion_la_entrada_sale_como_antes():
    """Un guion que no usa `dir` no cambia: su entrada sigue siendo {tipo, d}."""
    g, _ = _dos_planos("funde")
    assert g.datos(duracion=6)["planos"][1]["entra"] == {"tipo": "funde", "d": 0.6}


@pytest.mark.parametrize(
    ("entra", "direccion", "mensaje"),
    [
        ("cortina", None, "tiene que decir hacia dónde"),
        ("cortina", "abajo", "tiene que decir hacia dónde"),
        ("viento", "arriba", "tiene que decir hacia dónde"),
        ("mancha", "derecha", "no lleva dirección"),
        ("papel", "arriba", "no lleva dirección"),
        ("barrido", 0.5, "1 o -1"),
    ],
)
def test_una_direccion_que_falta_o_no_vale_para_al_escribir_el_plano(entra, direccion, mensaje):
    with pytest.raises(ErrorDeEscena, match=f"«cielo» entra con «{entra}».*{mensaje}"):
        _dos_planos(entra, dir=direccion)


@pytest.mark.parametrize("curva", ["acelera", "frena"])
def test_las_curvas_del_motor_de_laminas_valen_en_la_camara_y_en_las_claves(curva):
    g, p = _con_un_plano()
    p.cam(1, 1300, 700, 1.2, tr=0.8, e=curva)
    g.actor(p, "ana_pie", 800, 1200, escala=1.0).clave(1, 0.5, curva, x=900)
    compone.valida(g.datos(duracion=4))
