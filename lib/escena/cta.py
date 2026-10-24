"""El CTA de suscripción del estudio: el banner con su campana, que se balancea y suena (F6.8, fila 236).

Decisión del 02-10-2026: «El estilo del banner CTA [...] tiene que ser a nivel de estudio y no canal». Nació en la capa
de un canal (el cierre de video_1, F6.3) y un segundo canal lo pidió igual (fila 235). Lo que hace, igual en todos:

- **el banner entra con un rebote** (`pop`, `ENTRA_S`) y **late despacio** mientras está (`late`, amplitud `LATIDO`);
- **su campana es una imagen aparte** colocada dentro del banner, que **se balancea** (el `campana` del motor) desde
  que el narrador dice «bell» y otra vez cada `PERIODO_CAMPANA` segundos; con cada balanceo **suena la notificación**
  (la primera, más fuerte), hasta `CALLA_ANTES_S` segundos antes de que el banner se vaya;
- **un clic** (`CLIC`) en el instante que dé el canal.

Los sonidos son de la biblioteca del estudio (`datos/escena/sfx`, Pixabay, uso comercial; los mezcla la etapa de audio).

**Qué pone el canal** (F4.9): su banner sin campana y su campana (los PNG, con su procedencia en el run), dónde va la
campana dentro del banner (`geometria`, en px del PNG del banner), dónde va el banner en pantalla y cuándo sale, el
instante del clic y, si quiere, la sombra del banner (`.cta-caja { filter: … }` en su CSS). **Lo que pone el estudio**,
además del movimiento y el sonido, es la estructura de la caja (`CSS`), que compone añade a la página si lleva un CTA:
así la campana cae en su sitio en cualquier canal sin que su CSS la repita.
"""

from __future__ import annotations

import html
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # escena.py importa compone, y compone importa este módulo
    from lib.escena.escena import Elemento, Guion

ENTRA_S = 0.7  # lo que tarda el rebote de entrada
LATIDO = 0.5  # la amplitud del latido (`Motor.elemento`, bucle «late»: ±5 % × amplitud)
PERIODO_CAMPANA = 4.5  # cada cuánto vuelve a balancearse y a sonar
CLIC = {"nombre": "click-soft", "volumen": 0.6}
NOTIFICACION = "notification"
VOLUMEN_PRIMERA, VOLUMEN_SIGUIENTES = 0.35, 0.25
CALLA_ANTES_S = 1.5  # la última campanada suena al menos esto antes del final del banner

# La estructura de la caja: el banner la llena y la campana va encima, en su sitio, girando desde su asa. Sin colores
# (la sombra, si la hay, es del canal).
CLASE = "cta-caja"
CSS = (
    ".cta-caja { position: relative; width: 100%; height: 100%; }\n"
    ".cta-caja > img { position: absolute; }\n"
    ".cta-banner { left: 0; top: 0; width: 100%; height: 100%; }\n"
    ".cta-campana { transform-origin: 50% 6%; }\n"
)


def _par(v: float) -> int:
    return int(round(v / 2)) * 2


def en_pantalla(cta: Mapping, marco: Mapping) -> tuple[float, float, float, float]:
    """(centro x, centro y, ancho, alto) de un banner centrado en el marco: la cuenta que hacía el motor de láminas.

    `cta` es el `cta.json` de un canal: `banner` ({w, h}, el PNG del banner) y `en_pantalla`, con el ancho del banner
    en porcentaje del marco (`ancho_pct`) y la distancia de su borde de abajo al del marco (`margen_inferior_px`). El
    alto sale del ancho y de la proporción del PNG. Nació en el cierre de un canal (F6.8) y sube al estudio en F7.10,
    cuando un segundo canal lo pide igual.
    """
    sitio = cta["en_pantalla"]
    ancho = _par(marco["w"] * sitio["ancho_pct"] / 100)
    alto = _par(ancho * cta["banner"]["h"] / cta["banner"]["w"])
    y = marco["h"] - sitio["margen_inferior_px"] - alto
    if y < 0:
        raise ValueError(f"con ancho_pct {sitio['ancho_pct']} el banner ({ancho}x{alto}) se sale del marco por arriba")
    return marco["w"] / 2, y + alto / 2, ancho, alto


def caja(banner_src: str, campana_src: str, geometria: Mapping) -> str:
    """El HTML de la caja: el banner y, encima, la campana donde dice `geometria` ({banner: {w, h}, campana: {x, y, w,
    h}}, en px del PNG del banner)."""
    bw, bh, c = geometria["banner"]["w"], geometria["banner"]["h"], geometria["campana"]
    return (
        f'<div class="{CLASE}"><img class="cta-banner" src="{html.escape(banner_src, quote=True)}" alt="">'
        f'<img class="cta-campana campana" src="{html.escape(campana_src, quote=True)}" alt="" '
        f'style="left:{100 * c["x"] / bw:.3f}%;top:{100 * c["y"] / bh:.3f}%;width:{100 * c["w"] / bw:.3f}%;'
        f'height:{100 * c["h"] / bh:.3f}%"></div>'
    )


def pon(g: Guion, *, banner_src: str, campana_src: str, geometria: Mapping, centro: tuple[float, float],
        tamano: tuple[float, float], t0: float, t1: float, t_campana: float, t_clic: float,
        z: int = 0) -> Elemento:  # fmt: skip
    """El banner en pantalla de t0 a t1, centrado en `centro` y de `tamano` px, con su campana desde `t_campana` y su
    clic en `t_clic`. Devuelve el elemento."""
    if not t0 < t_campana < t1:
        raise ValueError(f"la campana suena en {t_campana:.2f} s, fuera del banner ({t0:.2f}–{t1:.2f} s)")
    if not t0 <= t_clic < t1:
        raise ValueError(f"el clic suena en {t_clic:.2f} s, fuera del banner ({t0:.2f}–{t1:.2f} s)")
    (x, y), (w, h) = centro, tamano
    banner = g.el("pantalla", caja(banner_src, campana_src, geometria), x, y, w, h, t0, t1, entra="pop", sale="nada",
                  bucle="late", amp=LATIDO, di=ENTRA_S, clase="cta", campana=True, campana_t=t_campana,
                  campana_p=PERIODO_CAMPANA, z=z)  # fmt: skip
    g.suena(CLIC, t_clic)
    t = t_campana
    while t < t1 - CALLA_ANTES_S:
        g.suena({"nombre": NOTIFICACION, "volumen": VOLUMEN_PRIMERA if t == t_campana else VOLUMEN_SIGUIENTES}, t)
        t += PERIODO_CAMPANA
    return banner
