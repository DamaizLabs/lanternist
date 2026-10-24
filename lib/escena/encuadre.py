"""Dónde está cada cosa en pantalla, calculado como lo calcula el motor, y las correcciones de encuadre (F6.2b).

Viene de `canal/scripts/encuadre.py` del experimento video_1. Dos cambios de fondo:

1. **La geometría es la del motor, no una aproximación.** video_1 interpolaba las claves en línea recta y movía
   la cámara siempre con la curva suave «porque basta para encuadrar». Aquí `Geometria` repite `motor/motor.js`
   (sus curvas, la posición con el padre, el volteo, el ancho, la cámara que sigue a un actor, la cámara en
   mano y el recorte de la cámara al fondo), y una prueba lo compara con el motor en Node
   (`tests/escena/test_extremo_a_extremo.py`). Lo único que no repite es el movimiento secundario —el rebote,
   la respiración, los eventos—, que mueve la figura unos px sin cambiarla de sitio.
2. **Nada del canal.** El marco sale del GUION; la franja del karaoke, que depende del CSS del canal, llega como
   parámetro; y qué textos se pueden apartar de una cara lo dice cada elemento (`movible`), no una lista de
   clases de un canal.

Las correcciones trabajan sobre el dict de `Guion.datos()` y lo cambian en su sitio:

- `corrige`: abre los encuadres que dejan a un personaje con la cabeza cortada por arriba (nunca acerca).
- `aparta_de_caras`: mueve los textos de pantalla que tapan una cara al sitio libre más cercano.

Las comprobaciones que dicen si el resultado vale están en `comprobaciones.py`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping

TAU = math.pi * 2

# Las constantes de aquí son del ESTUDIO: geometría y márgenes de las correcciones, iguales para cualquier canal.
MARGEN = 0.04  # aire sobre la cabeza, en fracción del alto visible
ALTO_CABEZA = 0.32  # sin «cabeza» en el catálogo, la cabeza es esta franja de arriba de la figura
CABEZA = 0.42  # lo que hay que ver de un cuerpo cortado: la cabeza y el pecho
DENTRO_X = 0.6  # un personaje cuenta como «en el plano» si al menos esta parte de su ancho está a la vista
MARGEN_PANTALLA = 24.0  # px que un texto apartado deja hasta el borde del fotograma
CRECE = 0.05  # lo que crece un texto por cada lado al entrar con rebote (la entrada «pop» llega a escala 1,10)
PASO_CONTROL = 0.25  # s entre dos instantes en que se mira si un texto tapa una cara
UMBRAL_CARA = 0.10  # parte de una cabeza que un texto puede pisar: el cálculo no ve eventos ni rebotes


def _clamp(v: float, a: float, b: float) -> float:
    return min(b, max(a, v))


def _rebote(p: float) -> float:
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2


def _elastico(p: float) -> float:
    if p in (0, 1):
        return p
    return 2 ** (-10 * p) * math.sin((p * 10 - 0.75) * (TAU / 3)) + 1


# Las curvas de `Motor.EASE`, una a una.
EASE = {
    "lineal": lambda p: p,
    "suave": lambda p: p * p * (3 - 2 * p),
    "inout": lambda p: 4 * p * p * p if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2,
    "sale": lambda p: 1 - (1 - p) ** 3,
    "entra": lambda p: p * p * p,
    "rebote": _rebote,
    "elastico": _elastico,
}


def busca(claves: list[Mapping], t: float) -> int:
    """El índice de la última clave con `t` ≤ t, o −1 (`Motor.busca`)."""
    lo, hi, r = 0, len(claves) - 1, -1
    while lo <= hi:
        m = (lo + hi) >> 1
        if claves[m]["t"] <= t:
            r, lo = m, m + 1
        else:
            hi = m - 1
    return r


def pista(claves: list[Mapping], t: float, campos: tuple[str, ...]) -> dict:
    """Los campos de la pista en t, como `pista` de motor.js: cada clave llega a su valor en [t, t + tr]."""
    i = busca(claves, t)
    k = claves[max(0, i)]
    if i <= 0:
        return {c: k[c] for c in campos}
    a = claves[i - 1]
    p = _clamp((t - k["t"]) / k["tr"], 0, 1) if k["tr"] > 0 else 1
    e = EASE[k.get("e") or "inout"](p)
    return {c: a[c] + (k[c] - a[c]) * e for c in campos}


def _choque(caja, otras) -> float:
    x0, y0, x1, y1 = caja
    return sum(max(0.0, min(x1, b[2]) - max(x0, b[0])) * max(0.0, min(y1, b[3]) - max(y0, b[1])) for b in otras)


def tiene_texto(fragmento: str) -> bool:
    """¿Se lee algo en este HTML? Un rótulo sí; un dibujo (un SVG, una imagen) no."""
    return bool(re.sub(r"<[^>]*>", "", re.sub(r"<svg\b.*?</svg>", "", fragmento, flags=re.S | re.I)).strip())


class Geometria:
    """Dónde está cada cosa de un GUION (`Guion.datos()`) en cada instante, en px del fondo y de la pantalla."""

    CAMPOS = ("x", "y", "s", "r", "op", "flip", "ancho")

    def __init__(self, datos: Mapping) -> None:
        self.datos = datos
        self.MW, self.MH = datos["marco"]["w"], datos["marco"]["h"]
        self.mano = datos["camara_en_mano"]
        self.planos = sorted(datos["planos"], key=lambda p: p["t0"])
        self.plano = {p["id"]: p for p in self.planos}
        self.actores = {a["id"]: (a, p) for p in self.planos for a in p["actores"]}

    # ---------------------------------------------------------- actores
    def mundo(self, aid: str, t: float) -> dict:
        """Posición en el fondo con la del padre sumada, como `mundo` de motor.js."""
        a, _ = self.actores[aid]
        k = pista(a["pista"], t, self.CAMPOS)
        if not a.get("padre"):
            return k
        p = self.mundo(a["padre"], t)
        sx = -1 if p["flip"] > 0.5 else 1
        ox, oy, g = sx * k["x"] * p["s"] * p["ancho"], k["y"] * p["s"], p["r"] * math.pi / 180
        c, s = math.cos(g), math.sin(g)
        return {
            "x": p["x"] + ox * c - oy * s,
            "y": p["y"] + ox * s + oy * c,
            "s": k["s"] * p["s"],
            "r": k["r"] + p["r"],
            "op": k["op"] * p["op"],
            "flip": abs(k["flip"] - p["flip"]),
            "ancho": k["ancho"] * p["ancho"],
        }

    def postura(self, aid: str, t: float) -> dict:
        a, _ = self.actores[aid]
        post = a["pista"][max(0, busca(a["pista"], t))]["post"]
        return a["posturas"].get(post) or next(iter(a["posturas"].values()))

    def caja(self, aid: str, t: float) -> tuple[float, float, float, float]:
        """La caja de su postura en el fondo (sin el giro, como video_1: basta para encuadrar)."""
        a, _ = self.actores[aid]
        m, d = self.mundo(aid, t), self.postura(aid, t)
        e = a["escala"] * m["s"] / d.get("k", 1)
        izq, der = d["ax"] * e * m["ancho"], (d["w"] - d["ax"]) * e * m["ancho"]
        if m["flip"] > 0.5:
            izq, der = der, izq
        return m["x"] - izq, m["y"] - d["ay"] * e, m["x"] + der, m["y"] + (d["h"] - d["ay"]) * e

    def tiene_cabeza(self, aid: str, t: float) -> bool:
        """Un personaje, o una postura que lleva uno encima (lo que se monta: «jinete» en el catálogo)."""
        a, _ = self.actores[aid]
        return bool(a.get("pj") or self.postura(aid, t).get("jinete"))

    def cabeza(self, aid: str, t: float) -> tuple[float, float, float, float]:
        """La caja de la cabeza en el fondo: la «cabeza» del catálogo o, si no la hay, la franja de arriba."""
        a, _ = self.actores[aid]
        m, d = self.mundo(aid, t), self.postura(aid, t)
        if not d.get("cabeza"):
            x0, y0, x1, y1 = self.caja(aid, t)
            return x0, y0, x1, y0 + ALTO_CABEZA * (y1 - y0)
        e = a["escala"] * m["s"] / d.get("k", 1)
        c0, f0, c1, f1 = d["cabeza"]
        izq, der = (c0 - d["ax"]) * e * m["ancho"], (c1 - d["ax"]) * e * m["ancho"]
        if m["flip"] > 0.5:
            izq, der = -der, -izq
        return m["x"] + izq, m["y"] + (f0 - d["ay"]) * e, m["x"] + der, m["y"] + (f1 - d["ay"]) * e

    # ---------------------------------------------------------- cámara
    def _centro(self, k: Mapping, t: float) -> tuple[float, float]:
        x, y = k["cx"], k["cy"]
        if k.get("sigue"):
            m = self.mundo(k["sigue"], t)
            x, y = x + m["x"], y + m["y"]
        return x, y

    def clave_de_camara(self, pid: str, t: float) -> Mapping:
        cl = self.plano[pid]["camara"]
        return cl[max(0, busca(cl, t))]

    def en_transito(self, pid: str, t: float) -> bool:
        """¿Se está moviendo la cámara de una clave a la siguiente?"""
        cl = self.plano[pid]["camara"]
        i = max(0, busca(cl, t))
        return i > 0 and cl[i]["tr"] > 0 and t < cl[i]["t"] + cl[i]["tr"]

    def camara(self, pid: str, t: float) -> tuple[float, float, float]:
        """(centro x, centro y, escala) de la cámara, como `camara` de motor.js, con la cámara en mano."""
        p = self.plano[pid]
        W, H, cl = p["fondo"]["w"], p["fondo"]["h"], p["camara"]
        base = self.MW / W
        i = max(0, busca(cl, t))
        k = cl[i]
        (x, y), z = self._centro(k, t), k["z"]
        if i > 0 and k["tr"] > 0 and t < k["t"] + k["tr"]:
            a = cl[i - 1]
            e = EASE[k.get("e") or "inout"](_clamp((t - k["t"]) / k["tr"], 0, 1))
            ax, ay = self._centro(a, t)
            x, y = ax + (x - ax) * e, ay + (y - ay) * e
            z = math.exp(math.log(a["z"]) + (math.log(k["z"]) - math.log(a["z"])) * e)
        x += self.mano * ((14 / z) * math.sin(t * 0.13) + (7 / z) * math.sin(t * 0.31 + 1))
        y += self.mano * (9 / z) * math.sin(t * 0.17 + 2)
        z *= 1 + self.mano * 0.006 * math.sin(t * 0.11)
        s = base * max(z, self.MH / H / base)
        vw, vh = self.MW / s, self.MH / s
        return _clamp(x, vw / 2, W - vw / 2), _clamp(y, vh / 2, H - vh / 2), s

    def vista(self, pid: str, t: float) -> tuple[float, float, float, float]:
        """Lo que se ve del fondo del plano en t, en px del fondo."""
        x, y, s = self.camara(pid, t)
        vw, vh = self.MW / s, self.MH / s
        return x - vw / 2, y - vh / 2, x + vw / 2, y + vh / 2

    def vista_de_clave(self, p: Mapping, cx: float, cy: float, z: float) -> tuple[float, float, float, float]:
        """La vista quieta de una clave de cámara (sin cámara en mano): la que abre `corrige`."""
        W, H = p["fondo"]["w"], p["fondo"]["h"]
        base = self.MW / W
        s = base * max(z, self.MH / H / base)
        vw, vh = self.MW / s, self.MH / s
        cx, cy = _clamp(cx, vw / 2, W - vw / 2), _clamp(cy, vh / 2, H - vh / 2)
        return cx - vw / 2, cy - vh / 2, cx + vw / 2, cy + vh / 2

    def a_pantalla(self, pid: str, t: float, caja) -> tuple[float, float, float, float]:
        x, y, s = self.camara(pid, t)
        mx, my = self.MW / 2, self.MH / 2
        return (caja[0] - x) * s + mx, (caja[1] - y) * s + my, (caja[2] - x) * s + mx, (caja[3] - y) * s + my

    def plano_arriba(self, t: float) -> Mapping | None:
        """El plano que se ve en t (el de encima, si dos se solapan en una entrada)."""
        visibles = [p for p in self.planos if p["t0"] <= t < p["t1"]]
        return visibles[-1] if visibles else None

    def caras(self, t: float) -> list[tuple[float, float, float, float]]:
        """Las cajas en pantalla de las cabezas visibles en t, en el plano de encima."""
        p = self.plano_arriba(t)
        if p is None:
            return []
        salida = []
        for a in p["actores"]:
            if not self.tiene_cabeza(a["id"], t) or self.mundo(a["id"], t)["op"] < 0.5:
                continue
            salida.append(self.a_pantalla(p["id"], t, self.cabeza(a["id"], t)))
        return salida

    def caja_de_elemento(self, e: Mapping, t: float) -> tuple[float, float, float, float] | None:
        """La caja de un elemento en pantalla en t; None si va en un plano que no se ve."""
        dx = dy = 0.0
        if e.get("sigue"):
            m = self.mundo(e["sigue"], t)
            dx, dy = m["x"], m["y"]
        caja = (e["x"] + dx, e["y"] + dy, e["x"] + e["w"] + dx, e["y"] + e["h"] + dy)
        if e["capa"] == "pantalla":
            return caja
        arriba = self.plano_arriba(t)
        if arriba is None or arriba["id"] != e["capa"]:
            return None
        return self.a_pantalla(e["capa"], t, caja)


# ------------------------------------------------------------------ correcciones
def _cortados(geo: Geometria, p: Mapping, v, t: float) -> list[tuple[str, tuple]]:
    """Personajes casi enteros en la vista con la cabeza fuera (o pegada al borde) por arriba."""
    x0, y0, x1, y1 = v
    vh = y1 - y0
    fuera = []
    for a in p["actores"]:
        aid = a["id"]
        if not geo.tiene_cabeza(aid, t) or geo.mundo(aid, t)["op"] < 0.5:
            continue
        bx0, by0, bx1, by1 = geo.caja(aid, t)
        dentro_x = max(0.0, min(bx1, x1) - max(bx0, x0)) / max(bx1 - bx0, 1)
        medio = (by0 + by1) / 2
        if dentro_x >= DENTRO_X and y0 < medio < y1 and by0 < y0 + MARGEN * vh * 0.5:
            fuera.append((aid, (bx0, by0, bx1, by1)))
    return fuera


def corrige(datos: dict) -> list[str]:
    """Abre los encuadres que cortan cabezas: desplaza el centro y, si no basta, aleja el zoom. Nunca acerca.

    Repasa cada clave de cámara (salvo las que siguen a un actor y las `libre`) en tres instantes de su tramo
    quieto, y si un personaje casi entero a la vista tiene la cabeza fuera, amplía la vista hasta que se vean
    su cabeza y su pecho con aire encima. Devuelve una línea por clave cambiada.
    """
    geo = Geometria(datos)
    informe = []
    for p in datos["planos"]:
        W = p["fondo"]["w"]
        claves = p["camara"]
        for i, k in enumerate(claves):
            if k.get("sigue") or k.get("libre"):
                continue
            ta = k["t"] + k.get("tr", 0)
            tb = min(claves[i + 1]["t"] if i + 1 < len(claves) else p["t1"], p["t1"])
            if tb <= p["t0"] or ta >= p["t1"]:
                continue
            ta = max(ta, p["t0"])
            muestras = sorted({ta, (ta + tb) / 2, max(ta, tb - 0.05)}) if tb > ta else [ta]
            antes = (k["cx"], k["cy"], k["z"])
            for _ in range(4):
                v = geo.vista_de_clave(p, k["cx"], k["cy"], k["z"])
                cortes = [c for t in muestras for c in _cortados(geo, p, v, t)]
                if not cortes:
                    break
                vw, vh = v[2] - v[0], v[3] - v[1]
                # Lo que hay que ver: lo que la clave quería enseñar (el centro de su vista) y la cabeza y el
                # pecho de cada personaje cortado.
                r0 = [k["cx"] - 0.3 * vw, k["cx"] + 0.3 * vw]
                r1 = [k["cy"] - 0.3 * vh, k["cy"] + 0.3 * vh]
                for _, (bx0, by0, bx1, by1) in cortes:
                    r0 = [min(r0[0], bx0), max(r0[1], bx1)]
                    r1 = [min(r1[0], by0 - MARGEN * vh), max(r1[1], by0 + CABEZA * (by1 - by0))]
                ancho = max(r0[1] - r0[0], (r1[1] - r1[0]) * geo.MW / geo.MH)
                k["z"] = round(min(k["z"], W / ancho), 3)
                vh2 = W / k["z"] * geo.MH / geo.MW
                k["cx"] = round((r0[0] + r0[1]) / 2, 1)
                # La cabeza arriba con su margen y lo que sobre, abajo: la parte de abajo la tapa a ratos el karaoke.
                k["cy"] = round(r1[0] + vh2 / 2, 1)
            if (k["cx"], k["cy"], k["z"]) != antes:
                informe.append(
                    f"{p['id']} t={k['t']:.1f}: ({antes[0]:.0f}, {antes[1]:.0f}, z {antes[2]:.2f}) -> "
                    f"({k['cx']:.0f}, {k['cy']:.0f}, z {k['z']:.2f})"
                )
    return informe


def caras_durante(geo: Geometria, e: Mapping) -> list[tuple[float, float, float, float]]:
    """Todas las cabezas que se ven mientras vive el elemento, mirando cada PASO_CONTROL s."""
    n = max(1, int((e["t1"] - e["t0"]) / PASO_CONTROL))
    return [c for i in range(n + 1) for c in geo.caras(e["t0"] + (e["t1"] - e["t0"]) * i / n)]


def aparta_de_caras(datos: dict, *, franja_inferior_y: float) -> list[str]:
    """Mueve los textos de pantalla `movible` que tapan una cara al sitio libre más cercano.

    Cada texto se mira cada PASO_CONTROL s de su vida. Si pisa más de UMBRAL_CARA de alguna cabeza, prueba su
    sitio, las cuatro esquinas, arriba en el centro, los lados a media altura y la franja de encima del karaoke,
    y se queda con el que menos pisa caras y otros textos; a igual coste, el más cercano. Los sitios dejan aire
    para lo que crece al entrar. Se recorren por orden de aparición: los ya movidos cuentan para los siguientes.

    `franja_inferior_y` es donde empieza el karaoke (px de pantalla): ningún texto baja de ahí. Depende del CSS
    del canal, así que lo da el canal.
    """
    geo = Geometria(datos)
    MW, MH = geo.MW, geo.MH
    pantalla = [e for e in datos["elementos"] if e["capa"] == "pantalla"]
    informe, movidos = [], []
    for e in sorted(pantalla, key=lambda o: o["t0"]):
        if not e.get("movible") or e["w"] >= MW - 20 or e.get("sigue"):
            continue
        cabezas = caras_durante(geo, e)
        otras = [
            (o["x"], o["y"], o["x"] + o["w"], o["y"] + o["h"])
            for o in pantalla
            if o is not e and o["w"] < MW - 20 and o["t0"] < e["t1"] and o["t1"] > e["t0"] and not o.get("tapa_caras")
        ]
        caja = (e["x"], e["y"], e["x"] + e["w"], e["y"] + e["h"])
        tapa = any(_choque(caja, [c]) > UMBRAL_CARA * (c[2] - c[0]) * (c[3] - c[1]) for c in cabezas if c[3] > c[1])
        vivos = [
            (o["x"], o["y"], o["x"] + o["w"], o["y"] + o["h"])
            for o in movidos
            if o["t0"] < e["t1"] and o["t1"] > e["t0"]
        ]
        pisa_movido = _choque(caja, vivos) > UMBRAL_CARA * e["w"] * e["h"]
        if not tapa and not pisa_movido:
            continue
        w, h = e["w"], e["h"]
        mx, my = MARGEN_PANTALLA + CRECE * w, MARGEN_PANTALLA + CRECE * h
        cx0, cy0 = e["x"] + w / 2, e["y"] + h / 2
        abajo = franja_inferior_y - CRECE * h - h / 2  # el centro más bajo sin rozar el karaoke
        sitios = [
            (cx0, cy0),
            (mx + w / 2, my + h / 2),
            (MW - mx - w / 2, my + h / 2),
            (MW / 2, my + h / 2),
            (mx + w / 2, MH / 2 - 60),
            (MW - mx - w / 2, MH / 2 - 60),
            (mx + w / 2, abajo),
            (MW - mx - w / 2, abajo),
        ]
        mejor = None
        for cx, cy in sitios:
            if cy > abajo + 0.5 or cy - h / 2 < 0:
                continue
            b = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            # Una cara pesa más que un texto, y un texto más que alejarse del sitio de partida.
            coste = 10 * _choque(b, cabezas) + 3 * _choque(b, otras) + 0.5 * math.hypot(cx - cx0, cy - cy0)
            if mejor is None or coste < mejor[0]:
                mejor = (coste, cx, cy)
        if mejor is None:  # tan alto que no cabe en ningún sitio: se queda donde estaba
            continue
        _, cx, cy = mejor
        if (cx, cy) != (cx0, cy0):
            e["x"], e["y"] = round(cx - w / 2, 1), round(cy - h / 2, 1)
            movidos.append(e)
            informe.append(f"t={e['t0']:.1f} {e['id']}: ({cx0:.0f}, {cy0:.0f}) -> ({cx:.0f}, {cy:.0f})")
    return informe
