"""Los ayudantes del guion de escena (F6.2b): elementos didácticos, piezas que se mecen y recortes en las pausas.

Vienen de `canal/scripts/ayudas.py` y de la parte genérica de `canal/scripts/cierre.py` del experimento video_1.
Cada ayudante escribe un elemento con su **estructura** (el HTML y sus clases: `tarjeta`, `chip`, `verbo`,
`nota`, `contador`, `capitulo`, `repaso`, `etiqueta`, `grito`, `lupa`, `tablero`, `mini`…) y deja todo lo demás
al canal:

- **el estilo** (colores, tipografías, bordes) lo pone el CSS del canal sobre esas clases;
- **la disposición** (dónde va, qué tamaño tiene, cuánto dura, cómo entra y qué suena) llega en cada llamada,
  como argumentos con nombre y sin valor por omisión. Lo normal es que el canal los envuelva con los suyos
  (`tarjeta(g, palabra, dibujo, t0, **TARJETA_IZQ)`), y así sus tramos se escriben tan cortos como en video_1;
- **los textos fijos** («NEW WORD», «PAST SIMPLE», el título del repaso, la unidad de un contador en singular
  y en plural) también son del canal: dependen de su idioma y de su didáctica.

`sonido` es None o {"nombre", "volumen", "desfase_s" (opcional)}: el efecto de sonido que acompaña al elemento,
en su t0 más el desfase. Qué efecto y a qué volumen es del canal.

Aquí no hay personajes, alturas, sets ni vocabulario: todo eso es del canal (F6.3).
"""

from __future__ import annotations

import html
from collections.abc import Mapping

from lib.escena.escena import Elemento, ErrorDeEscena, Guion, Plano


def _e(texto) -> str:
    return html.escape(str(texto), quote=True)


def _pon(g: Guion, sonido: Mapping | None, t: float) -> None:
    g.suena(sonido, t)


# ------------------------------------------------------------------ didácticos
def tarjeta(
    g: Guion,
    palabra: str,
    dibujo: str,
    t0: float,
    *,
    dur: float,
    x: float,
    y: float,
    w: float,
    h: float,
    etiqueta: str,
    anim: Mapping,
    sonido: Mapping | None,
    articulo: str = "",
) -> Elemento:
    """Tarjeta de vocabulario: su etiqueta, el dibujo de la propia historia y la palabra (con su artículo aparte)."""
    art = f'<span class="art">{_e(articulo)} </span>' if articulo else ""
    contenido = (
        f'<div class="tarjeta"><div class="etq">{_e(etiqueta)}</div><div class="ico">{g.dibujo(dibujo)}</div>'
        f'<div class="pal">{art}{_e(palabra)}</div></div>'
    )
    _pon(g, sonido, t0)
    return g.el("pantalla", contenido, x, y, w, h, t0, t0 + dur, movible=True, **anim)


def chip(
    g: Guion,
    texto: str,
    t0: float,
    *,
    dur: float,
    x: float,
    y: float,
    w: float,
    h: float,
    anim: Mapping,
    sonido: Mapping | None,
    clase: str = "chip",
    icono: str | None = None,
) -> Elemento:
    """Un texto corto en una cápsula, con un dibujo delante si se le da `icono`."""
    ico = f'<span class="chip-ico">{g.dibujo(icono)}</span>' if icono else ""
    _pon(g, sonido, t0)
    return g.el(
        "pantalla", f'<div class="{_e(clase)}">{ico}<span>{_e(texto)}</span></div>', x, y, w, h, t0, t0 + dur,
        movible=True, **anim,
    )  # fmt: skip


def numero(
    g: Guion,
    texto: str,
    t0: float,
    *,
    dur: float,
    x: float,
    y: float,
    w: float,
    h: float,
    anim: Mapping,
    sonido: Mapping | None,
) -> Elemento:
    """Un número del cuento tal como se dice («2 seconds»): un chip con la clase `numero`."""
    return chip(g, texto, t0, dur=dur, x=x, y=y, w=w, h=h, anim=anim, sonido=sonido, clase="chip numero")


def verbo(
    g: Guion,
    forma: str,
    base: str,
    t0: float,
    *,
    dur: float,
    x: float,
    y: float,
    w: float,
    h: float,
    etiqueta: str,
    anim: Mapping,
    sonido: Mapping | None,
) -> Elemento:
    """La forma que se oye y la forma de la que sale («sat ← sit»), con su etiqueta («PAST SIMPLE»)."""
    contenido = (
        f'<div class="verbo"><span class="etq">{_e(etiqueta)}</span><b>{_e(forma)}</b>'
        f'<span class="flecha">←</span><span class="base">{_e(base)}</span></div>'
    )
    _pon(g, sonido, t0)
    return g.el("pantalla", contenido, x, y, w, h, t0, t0 + dur, movible=True, **anim)


def nota(
    g: Guion,
    etiqueta: str,
    texto: str,
    t0: float,
    *,
    dur: float,
    x: float,
    y: float,
    w: float,
    h: float,
    anim: Mapping,
    sonido: Mapping | None,
) -> Elemento:
    """Una nota: una etiqueta pequeña y un ejemplo del propio cuento."""
    contenido = f'<div class="nota"><span class="etq">{_e(etiqueta)}</span><b>{_e(texto)}</b></div>'
    _pon(g, sonido, t0)
    return g.el("pantalla", contenido, x, y, w, h, t0, t0 + dur, movible=True, **anim)


def contador(
    g: Guion,
    de: int,
    a: int,
    t0: float,
    *,
    dur: float,
    x: float,
    y: float,
    tam: float,
    unidad: tuple[str, str] | None,
    empieza_s: float,
    acaba_antes_s: float,
    anim: Mapping,
    sonido: Mapping | None,
) -> Elemento:
    """Un número que cuenta de `de` a `a` entre t0 + `empieza_s` y `acaba_antes_s` antes de irse.

    `unidad` es (singular, plural): el director escribe la que toca según la cuenta. Va en dos formas y no se
    deriva quitando una «s», que es una regla del inglés y no del estudio.
    """
    ud = ""
    if unidad:
        uno, varios = unidad
        ud = f'<div class="ud" data-uno="{_e(uno)}" data-varios="{_e(varios)}">{_e(varios)}</div>'
    cuenta = {"de": de, "a": a, "t": empieza_s, "d": max(0.1, dur - empieza_s - acaba_antes_s)}
    _pon(g, sonido, t0)
    return g.el(
        "pantalla", f'<div class="contador"><div class="cuenta">{int(de)}</div>{ud}</div>', x, y, tam, tam, t0,
        t0 + dur, movible=True, contador=cuenta, **anim,
    )  # fmt: skip


def capitulo(
    g: Guion,
    parte: str,
    titulo: str,
    t0: float,
    t1: float,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    anim: Mapping,
    sonido: Mapping | None,
) -> Elemento:
    """El rótulo de una parte: su número o etiqueta y su título."""
    contenido = (
        f'<div class="capitulo"><div class="cap-parte">{_e(parte)}</div>'
        f'<div class="cap-titulo">{_e(titulo)}</div></div>'
    )
    _pon(g, sonido, t0)
    return g.el("pantalla", contenido, x, y, w, h, t0, t1, **anim)


def repaso(
    g: Guion,
    palabras: list[tuple[str, str]],
    t0: float,
    t1: float,
    *,
    titulo: str,
    x: float,
    y: float,
    h: float,
    ancho_item: float,
    margen: float,
    ancho_max: float,
    anim: Mapping,
    sonido: Mapping | None,
) -> Elemento:
    """Las palabras de una parte, cada una con su dibujo, en una fila (su ancho crece con cuántas son)."""
    if not palabras:
        raise ErrorDeEscena("un repaso sin palabras no repasa nada")
    items = "".join(
        f'<div class="rit"><div class="rimg">{g.dibujo(d)}</div><div class="rpal">{_e(p)}</div></div>'
        for p, d in palabras
    )
    ancho = min(ancho_max, margen + ancho_item * len(palabras))
    contenido = f'<div class="repaso"><div class="rtit">{_e(titulo)}</div><div class="rfila">{items}</div></div>'
    _pon(g, sonido, t0)
    return g.el("pantalla", contenido, x, y, ancho, h, t0, t1, **anim)


def etiqueta(
    g: Guion,
    plano: Plano,
    texto: str,
    x: float,
    y: float,
    t0: float,
    t1: float,
    *,
    ancho: float,
    alto_texto: float,
    sube: float,
    tam: float,
    z: int,
    anim: Mapping,
    sonido: Mapping | None,
    grande: bool = False,
) -> Elemento:
    """Un rótulo en el fondo del plano con una flecha que se dibuja y apunta a (x, y) («pavement», «kerb»).

    La flecha va en un SVG de `ancho` × (`alto_texto` + `sube`) unidades escalado por `tam`: así el grosor de su
    trazo, que pone el CSS del canal (`.etiqueta .flecha`), crece con el rótulo. La forma de la curva y de la
    punta es la de video_1 y es del estudio: es el dibujo de este ayudante, no un estilo.
    """
    w0, h0 = ancho, alto_texto + sube
    w, h = w0 * tam, h0 * tam
    medio = w0 / 2
    flecha = (
        f'<svg width="{w:.0f}" height="{h:.0f}" viewBox="0 0 {w0:.0f} {h0:.0f}">'
        f'<path class="trazo flecha" d="M{medio:.0f},{alto_texto - 6:.0f} C{medio + 40:.0f},{h0 * 0.55:.0f} '
        f'{medio - 30:.0f},{h0 * 0.75:.0f} {medio:.0f},{h0 - 14:.0f}"/>'
        f'<path class="punta flecha" d="M{medio - 22:.0f},{h0 - 44:.0f} L{medio:.0f},{h0 - 8:.0f} '
        f'L{medio + 22:.0f},{h0 - 44:.0f}"/></svg>'
    )
    txt = (
        f'<div class="txt{" grande" if grande else ""}" style="transform:translateX(-50%) scale({tam:.2f});'
        f'transform-origin:50% 0">{_e(texto)}</div>'
    )
    _pon(g, sonido, t0)
    return g.el(
        plano.id, f'<div class="etiqueta">{flecha}{txt}</div>', x, y - h / 2, w, h, t0, t1, z=z, trazo=True, **anim
    )


def efecto(
    g: Guion,
    capa: str,
    dibujo: str,
    x: float,
    y: float,
    t0: float,
    *,
    dur: float,
    tam: float,
    anim: Mapping,
    sonido: Mapping | None,
) -> Elemento:
    """Un dibujo pasajero (un corazón, una interrogación) en pantalla o pegado a un plano."""
    _pon(g, sonido, t0)
    return g.el(capa, g.dibujo(dibujo), x, y, tam, tam, t0, t0 + dur, clase="fx", **anim)


def grito(
    g: Guion,
    texto: str,
    t0: float,
    *,
    dur: float,
    x: float,
    y: float,
    w: float,
    h: float,
    anim: Mapping,
    sonido: Mapping | None,
    clase: str = "grito",
) -> Elemento:
    """Lo que grita un personaje, en grande. Queda marcado como grito para ponerlo junto a quien lo dice."""
    _pon(g, sonido, t0)
    return g.el("pantalla", f'<div class="{_e(clase)}">{_e(texto)}</div>', x, y, w, h, t0, t0 + dur, grito=True, **anim)


def lupa(
    g: Guion,
    dibujo: str,
    t0: float,
    t1: float,
    *,
    x: float,
    y: float,
    tam: float,
    anim: Mapping,
    sonido: Mapping | None,
) -> Elemento:
    """Un detalle ampliado en un círculo."""
    _pon(g, sonido, t0)
    return g.el("pantalla", f'<div class="lupa">{g.dibujo(dibujo)}</div>', x, y, tam, tam, t0, t1, movible=True, **anim)


def tablero(
    g: Guion,
    items: list[tuple[str, str, float]],
    t0: float,
    t1: float,
    *,
    columnas: int,
    filas: int,
    origen: tuple[float, float],
    paso: tuple[float, float],
    mini: tuple[float, float],
    caja: tuple[float, float, float, float],
    anim_mini: Mapping,
    anim_tablero: Mapping,
    sonido: Mapping | None,
    sonido_cada: int,
) -> list[Elemento]:
    """El tablero de repaso: cada cosa (palabra, dibujo, instante) aparece como mini tarjeta y se queda.

    Las minis van en una rejilla de `columnas` × `filas` desde `origen` (centro de la primera) cada `paso`, de
    tamaño `mini`; el tablero es la `caja` (centro x, centro y, ancho, alto). Tapan a los personajes a
    propósito, así que no cuentan para la comprobación de textos sobre caras. Suena `sonido` en una de cada
    `sonido_cada` minis.
    """
    if len(items) > columnas * filas:
        raise ErrorDeEscena(
            f"el tablero tiene sitio para {columnas * filas} minis y el resumen trae {len(items)}: con una fila "
            "más, las minis bajarían al karaoke"
        )
    puestos = []
    for i, (palabra, dibujo, t) in enumerate(items):
        col, fila = i % columnas, i // columnas
        contenido = f'<div class="mini"><div class="mini-ico">{g.dibujo(dibujo)}</div><div>{_e(palabra)}</div></div>'
        puestos.append(
            g.el(
                "pantalla",
                contenido,
                origen[0] + col * paso[0],
                origen[1] + fila * paso[1],
                mini[0],
                mini[1],
                t,
                t1,
                z=3,
                tapa_caras=True,
                **anim_mini,
            )  # fmt: skip
        )
        if i % sonido_cada == 0:
            _pon(g, sonido, t)
    cx, cy, w, h = caja
    puestos.append(
        g.el("pantalla", '<div class="tablero"></div>', cx, cy, w, h, t0, t1, z=1, tapa_caras=True, **anim_tablero)
    )
    return puestos


# ------------------------------------------------------------------ pausas
def recorta_en_pausas(g: Guion, huecos: list[tuple[float, float]]) -> int:
    """Lo de pantalla que venía de la parte anterior termina donde empieza su pausa. Devuelve cuántos tocó.

    Una tarjeta puesta al final de una parte, con su duración fija, seguía encima del título de la parte
    siguiente. Se llama antes de poner lo de las pausas: así solo toca lo de las partes.
    `huecos` son las pausas de la línea de tiempo (`[linea.hueco(k) for k in …]`).
    """
    tocados = 0
    for a, _ in huecos:
        for e in g.elementos:
            if e.capa == "pantalla" and e.t0 < a < e.t1:
                e.t1 = round(a, 3)
                tocados += 1
    return tocados


# ------------------------------------------------------------------ posturas y piezas
def punto_de_postura(
    escala: float, postura: Mapping, punto: tuple[float, float], *, s: float = 1.0, flip: float = 0
) -> tuple[float, float]:
    """Dónde cae, en px del fondo y respecto al apoyo del actor, un punto de su postura.

    `punto` va en px de la imagen respecto a su apoyo (ax, ay), así que aguanta un recorte nuevo, que mueve el
    origen de la imagen pero no el apoyo. Divide por la k de la postura, como el motor, multiplica por la s del
    actor y refleja con el flip. `escala` es la del actor (la calcula el canal con sus alturas).
    """
    e = escala * s / postura.get("k", 1)
    return (-punto[0] if flip > 0.5 else punto[0]) * e, punto[1] * e


def piezas_de_postura(g: Guion, piezas: Mapping[str, tuple[float, float, bool]]) -> int:
    """Da vida a las piezas separadas de una postura (una cola, una cadena): se mecen todo el plano.

    `piezas` es {sufijo: (grados, vaivenes por segundo, va delante del cuerpo)} y la declara el canal. Donde un
    actor usa una postura `n` y el catálogo tiene `n_<sufijo>` (con su `off`, el desplazamiento de la pieza
    respecto al apoyo en px de su imagen), la pieza se pone como hija del actor que solo se ve mientras él está
    en esa postura, con el fundido de postura del GUION. Si el catálogo tiene `n_base` (la postura sin la
    pieza), el actor pasa a usarla. Se llama con el guion ya escrito; devuelve cuántas piezas puso.
    """
    cat = g.catalogo
    fundido = g.escena["fundido"]
    planos = {p.id: p for p in g.planos}
    puestas = 0
    for p in list(g.planos):
        for a in list(p.actores):
            usadas = list(dict.fromkeys(a.posturas + [k["post"] for k in a.claves if "post" in k]))
            con = {n: [s for s in piezas if f"{n}_{s}" in cat] for n in usadas}
            con = {n: s for n, s in con.items() if s}
            if not con:
                continue
            nueva = {n: f"{n}_base" if f"{n}_base" in cat else n for n in con}
            a.posturas = [nueva.get(n, n) for n in a.posturas]
            for k in a.claves:
                if k.get("post") in nueva:
                    k["post"] = nueva[k["post"]]
            cambios = sorted((k["t"], k["post"], k.get("fp", fundido)) for k in a.claves if "post" in k)
            for n, sufijos in con.items():
                tramos, desde = [], None  # (inicio, fundido de entrada, fin, fundido de salida)
                for t, post, fp in cambios:
                    if post == nueva[n] and desde is None:
                        desde = (t, fp)
                    elif post != nueva[n] and desde is not None:
                        tramos.append((*desde, t, fp))
                        desde = None
                if desde is not None:
                    tramos.append((*desde, planos[a.plano].t1, fundido))
                for s in sufijos:
                    d = cat[f"{n}_{s}"]
                    if "off" not in d:
                        raise ErrorDeEscena(f"la pieza «{n}_{s}» no declara `off` en el catálogo")
                    e = a.escala / d.get("k", 1)  # «off» va en px de la imagen, que el motor divide por k
                    grados, ritmo, delante = piezas[s]
                    pieza = g.actor(
                        p, f"{n}_{s}", d["off"][0] * e, d["off"][1] * e, padre=a, escala=a.escala,
                        z=a.z + (1 if delante else -1), op=0, pieza=True,
                    )  # fmt: skip
                    for t0, fp0, t1, fp1 in tramos:  # con el fundido de postura del padre
                        pieza.clave(max(t0, 0.0), fp0, op=1)
                        pieza.clave(t1, fp1, op=0)
                    pieza.ev("menea", p.t0, p.t1 - p.t0, a=grados, f=ritmo)
                    puestas += 1
    return puestas
