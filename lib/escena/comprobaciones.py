"""Las comprobaciones de un GUION de escena antes de renderizarlo (F6.2b).

Cada una mira un defecto que en video_1 se veía en el vídeo y que se puede medir sobre el GUION, sin render:

| Comprobación | Qué caza |
|---|---|
| `cabezas_en_cuadro` | un personaje a la vista con la cabeza cortada por arriba (con la cámara ya quieta) |
| `textos_fuera_de_las_caras` | un texto (rótulo, tarjeta, grito) que tapa más de UMBRAL_CARA de una cabeza |
| `pies_en_el_suelo` | un personaje que se apoya fuera del suelo del set, con los pies a la vista |
| `escala_de_cabeza` | las posturas de un personaje con cabezas de tamaños distintos (> UMBRAL_ESCALA_CABEZA) |
| `karaoke` | palabras del guion que no están en el karaoke, o láminas donde el alineador ancla poco |
| `duracion` | un GUION que no dura lo que dura su audio |

Todas devuelven una lista de `Defecto` (vacía si no hay ninguno) y ninguna cambia el GUION. `todas` las corre
juntas. Cada una tiene su prueba con un control negativo, un GUION que la viola a propósito
(`tests/escena/test_comprobaciones.py`).

Lo que NO miran, y hay que saberlo al leer un «0 defectos»: el movimiento secundario (un salto, un rebote o la
respiración mueven una figura unos px), el giro de los actores (las cajas van sin girar) y el instante exacto
de un movimiento de cámara (las cabezas se miran con la cámara quieta, que es lo que `encuadre.corrige`
garantiza). Muestrean cada PASO_CONTROL s.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from lib.escena.encuadre import DENTRO_X, PASO_CONTROL, UMBRAL_CARA, Geometria, _choque, tiene_texto

# Parte de la cabeza de un personaje en la que sus posturas pueden diferir. **Del estudio**: 6 % es lo que
# video_1 midió como tolerable (`canal/scripts/escala.py → UMBRAL`); por encima, un personaje de rodillas se
# veía un gigante junto a los demás (una cabeza un 45 % mayor que de pie).
UMBRAL_ESCALA_CABEZA = 0.06

# Parte de las palabras de una lámina que el alineador tiene que anclar a una marca propia. **Del estudio**, y
# medido: en las 371 láminas de voz de los 18 runs con alineación que había en disco el 29-09 (los dos canales),
# 369 anclan el 93,7 % o más y las dos que no se quedan en 89,8 % y 66,3 %
# (`experimentos/motor-escena/f62b-cobertura/cobertura.json → las_seis_peores`, `laminas_por_debajo_de`). El umbral
# cae en ese hueco: una lámina por debajo tiene un tramo en que el karaoke va repartido a ojo, no sincronizado, y
# hay que mirarla.
COBERTURA_MINIMA_POR_LAMINA = 0.92


@dataclass(frozen=True)
class Defecto:
    comprobacion: str
    donde: str
    t: float | None
    detalle: str

    def __str__(self) -> str:
        cuando = f" t={self.t:.2f}" if self.t is not None else ""
        return f"[{self.comprobacion}] {self.donde}{cuando}: {self.detalle}"


def _instantes(t0: float, t1: float) -> list[float]:
    """Cada PASO_CONTROL s de [t0, t1), incluido el último instante antes de t1."""
    n = max(1, math.ceil((t1 - t0) / PASO_CONTROL))
    return sorted({round(t0 + i * (t1 - t0) / n, 4) for i in range(n)} | {round(max(t0, t1 - 1e-3), 4)})


def _pisa(aid_rasgos: Mapping, actor: Mapping) -> bool:
    """¿Se apoya en el suelo? Lo dice su rasgo `pisa`; si no lo declara, un personaje (pj) sí y un objeto no."""
    return bool(aid_rasgos.get("pisa", bool(actor.get("pj"))))


def _dentro(punto: tuple[float, float], poligono: list) -> bool:
    """¿Está el punto dentro del polígono o sobre su borde? (rayo hacia la derecha, par-impar)."""
    x, y = punto
    n = len(poligono)
    for i in range(n):
        (x1, y1), (x2, y2) = poligono[i], poligono[(i + 1) % n]
        # Sobre un lado cuenta como dentro: el suelo declarado incluye su borde.
        if min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9:
            if abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) <= 1e-6 * max(1.0, math.hypot(x2 - x1, y2 - y1)):
                return True
    dentro = False
    for i in range(n):
        (x1, y1), (x2, y2) = poligono[i], poligono[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            dentro = not dentro
    return dentro


# ------------------------------------------------------------------ cabezas
def cabezas_en_cuadro(datos: Mapping) -> list[Defecto]:
    """Un personaje casi entero a la vista (DENTRO_X de su ancho y el centro dentro) con la cabeza fuera por arriba.

    Se mira con la cámara quieta (no durante un movimiento de una clave a otra) y se salta la clave `libre`, que
    corta una cabeza a propósito.
    """
    geo = Geometria(datos)
    vistos: dict[tuple[str, str], Defecto] = {}
    for p in geo.planos:
        for t in _instantes(p["t0"], p["t1"]):
            if geo.en_transito(p["id"], t) or geo.clave_de_camara(p["id"], t).get("libre"):
                continue
            x0, y0, x1, y1 = geo.vista(p["id"], t)
            for a in p["actores"]:
                aid = a["id"]
                if (p["id"], aid) in vistos or not geo.tiene_cabeza(aid, t) or geo.mundo(aid, t)["op"] < 0.5:
                    continue
                bx0, by0, bx1, by1 = geo.caja(aid, t)
                dentro_x = max(0.0, min(bx1, x1) - max(bx0, x0)) / max(bx1 - bx0, 1)
                if dentro_x < DENTRO_X or not y0 < (by0 + by1) / 2 < y1:
                    continue
                cabeza_y = geo.cabeza(aid, t)[1]
                if cabeza_y < y0:
                    vistos[(p["id"], aid)] = Defecto(
                        "cabeza_fuera",
                        f"{p['id']}/{aid}",
                        t,
                        f"la cabeza empieza {y0 - cabeza_y:.0f} px del fondo por encima de lo que se ve",
                    )
    return list(vistos.values())


# ------------------------------------------------------------------ textos sobre caras
def textos_fuera_de_las_caras(datos: Mapping) -> list[Defecto]:
    """Un elemento con texto que pisa más de UMBRAL_CARA de una cabeza visible, en algún instante de su vida.

    Cuentan los que tienen algo que leer (`encuadre.tiene_texto`), en pantalla o pegados a un plano. No cuentan
    los que tapan caras a propósito (`tapa_caras`, un tablero) ni los velos de pantalla completa.
    """
    geo = Geometria(datos)
    entra_por_omision = datos["movimiento"]["elementos"]["entra"]
    salida = []
    for e in datos["elementos"]:
        if e.get("tapa_caras") or e["w"] >= geo.MW - 20 or not tiene_texto(e.get("html", "")):
            continue
        # Desde que ha terminado de entrar: antes aún no se lee, y el instante que se informa tiene que ser uno en
        # el que el defecto se VE (un rótulo que entra con «pop» es invisible en su t0).
        entra = 0.0 if e.get("entra") == "nada" else (e["di"] if e.get("di") is not None else entra_por_omision)
        for t in _instantes(min(e["t0"] + entra, e["t1"] - 1e-3), e["t1"]):
            caja = geo.caja_de_elemento(e, t)
            if caja is None:
                continue
            pisadas = [
                c
                for c in geo.caras(t)
                if c[3] > c[1] and _choque(caja, [c]) > UMBRAL_CARA * (c[2] - c[0]) * (c[3] - c[1])
            ]
            if pisadas:
                c = pisadas[0]
                parte = _choque(caja, [c]) / ((c[2] - c[0]) * (c[3] - c[1]))
                salida.append(Defecto("texto_sobre_cara", e["id"], t, f"tapa el {100 * parte:.0f} % de una cabeza"))
                break
    return salida


# ------------------------------------------------------------------ pies
def pies_en_el_suelo(datos: Mapping) -> list[Defecto]:
    """Quien se apoya (rasgo `pisa`, o un personaje sin padre) tiene los pies dentro del suelo del set.

    Solo cuenta cuando se ve: con opacidad ≥ 0,5 y los pies dentro de la vista. El suelo lo declara el set
    (`plano.fondo.suelo`, un polígono en px del fondo); un set con `suelo: None` declara que no tiene, y no se
    mira. Un set que no lo declara, con alguien apoyado a la vista, es un defecto: no se puede comprobar.
    """
    geo = Geometria(datos)
    salida: dict[tuple[str, str], Defecto] = {}
    for p in geo.planos:
        fondo = p["fondo"]
        for a in p["actores"]:
            if a.get("padre") or not _pisa(a.get("rasgos") or {}, a):
                continue
            for t in _instantes(p["t0"], p["t1"]):
                m = geo.mundo(a["id"], t)
                x0, y0, x1, y1 = geo.vista(p["id"], t)
                if m["op"] < 0.5 or not (x0 <= m["x"] <= x1 and y0 <= m["y"] <= y1):
                    continue
                if "suelo" not in fondo:
                    salida[(p["id"], "")] = Defecto(
                        "pies_sin_suelo", p["id"], t, "el set no declara su suelo (Guion.fondo(..., suelo=...))"
                    )
                    break
                if fondo["suelo"] is None:
                    break
                if not _dentro((m["x"], m["y"]), fondo["suelo"]):
                    salida[(p["id"], a["id"])] = Defecto(
                        "pies_sin_suelo",
                        f"{p['id']}/{a['id']}",
                        t,
                        f"se apoya en ({m['x']:.0f}, {m['y']:.0f}), fuera del suelo del set",
                    )
                    break
    return list(salida.values())


# ------------------------------------------------------------------ escala de cabeza
def escala_de_cabeza(datos: Mapping) -> list[Defecto]:
    """Las posturas de un mismo personaje tienen la cabeza del mismo tamaño en pantalla, ± UMBRAL_ESCALA_CABEZA.

    La medida es `cabeza_px` del catálogo (la raíz del área de la cabeza en px de su imagen, que escribe el
    obrero de activos, F6.2c) dividida por la `k` de la postura, que es lo que la reduce en pantalla. Se compara
    dentro de cada personaje (su `pj`; si no tiene, el actor) y de cada `vista` si la postura la declara, porque
    de frente y de perfil la cabeza no mide lo mismo. Una postura de personaje sin `cabeza_px` es un defecto (no
    se puede comprobar); `cabeza_px: null` declara que esa figura no tiene cabeza que medir.
    """
    grupos: dict[tuple[str, str | None], dict[str, float]] = {}
    salida = []
    for p in datos["planos"]:
        for a in p["actores"]:
            if not a.get("pj"):
                continue
            for nombre, d in a["posturas"].items():
                if "cabeza_px" not in d:
                    salida.append(
                        Defecto("escala_de_cabeza", f"{a['id']}/{nombre}", None, "la postura no declara `cabeza_px`")
                    )
                    continue
                if d["cabeza_px"] is None:
                    continue
                grupos.setdefault((a["pj"], d.get("vista")), {})[nombre] = d["cabeza_px"] / d.get("k", 1)
    for (pj, vista), medidas in grupos.items():
        if len(medidas) < 2:
            continue
        orden = sorted(medidas.values())
        mediana = (
            orden[len(orden) // 2] if len(orden) % 2 else (orden[len(orden) // 2 - 1] + orden[len(orden) // 2]) / 2
        )
        for nombre, m in medidas.items():
            if abs(m / mediana - 1) > UMBRAL_ESCALA_CABEZA:
                salida.append(
                    Defecto(
                        "escala_de_cabeza",
                        f"{pj}/{nombre}",
                        None,
                        f"su cabeza mide ×{m / mediana:.2f} la de sus otras posturas"
                        + (f" de {vista}" if vista else "")
                        + f" (tolerancia ±{100 * UMBRAL_ESCALA_CABEZA:.0f} %): corrige su k",
                    )
                )
    return salida


# ------------------------------------------------------------------ karaoke y duración
def karaoke(datos: Mapping, linea) -> list[Defecto]:
    """El karaoke dice el guion entero, en orden, y el alineador ancla lo bastante en cada lámina.

    - Las palabras del karaoke (en el orden en que salen) son las de la línea de tiempo, una a una.
    - Sus tiempos no retroceden.
    - En cada lámina, la parte de palabras con marca propia llega a COBERTURA_MINIMA_POR_LAMINA.

    Un GUION sin karaoke a propósito (`sin_karaoke`, `Guion.sin_karaoke`, F7.10) no tiene palabras que comparar, pero
    la cobertura se sigue midiendo: de ella dependen las anclas del guion y el `.srt`.
    """
    salida = []
    sin_karaoke = bool(datos.get("sin_karaoke"))
    en_karaoke = [w for g in datos["karaoke"] for w in g["w"]]
    guion = [p.texto for p in linea.palabras]
    textos = [w[2] for w in en_karaoke]
    if sin_karaoke and en_karaoke:
        salida.append(Defecto("karaoke", "GUION", None, "dice que va sin karaoke y lleva grupos de karaoke"))
    if not sin_karaoke and textos != guion:
        i = next((i for i, (a, b) in enumerate(zip(textos, guion)) if a != b), min(len(textos), len(guion)))
        en_k = textos[i] if i < len(textos) else "(falta)"
        en_g = guion[i] if i < len(guion) else "(sobra)"
        salida.append(
            Defecto(
                "karaoke",
                f"palabra {i}",
                None,
                f"el karaoke tiene {len(textos)} palabras y el guion {len(guion)}; la primera que no cuadra: "
                f"{en_k!r} frente a {en_g!r}",
            )
        )
    for a, b in zip(en_karaoke, en_karaoke[1:]):
        if b[0] < a[0] - 1e-6:
            salida.append(Defecto("karaoke", repr(b[2]), b[0], f"empieza antes que la palabra anterior {a[2]!r}"))
            break
    for lamina in linea.por_lamina:
        if lamina["cobertura"] < COBERTURA_MINIMA_POR_LAMINA:
            salida.append(
                Defecto(
                    "karaoke",
                    f"lámina {lamina['lamina']}",
                    None,
                    f"el alineador ancla {lamina['ancladas']} de {lamina['palabras']} palabras "
                    f"({100 * lamina['cobertura']:.1f} %, mínimo {100 * COBERTURA_MINIMA_POR_LAMINA:.0f} %): "
                    + (
                        "hay un tramo con las anclas y el .srt repartidos a ojo"
                        if sin_karaoke
                        else "hay un tramo con el karaoke repartido a ojo"
                    ),
                )
            )
    return salida


def duracion(datos: Mapping, linea) -> list[Defecto]:
    """El GUION dura lo que su audio (± medio fotograma) y ningún audio de la composición se sale de él."""
    salida = []
    medio = 0.5 / datos["fps"]
    if abs(datos["duracion"] - linea.total) > medio:
        salida.append(
            Defecto("duracion", "GUION", None, f"dura {datos['duracion']:.3f} s y su audio {linea.total:.3f} s")
        )
    for au in datos.get("audios") or []:
        if au["t"] + au["d"] > datos["duracion"] + medio:
            salida.append(
                Defecto("duracion", au["id"], au["t"], f"acaba en {au['t'] + au['d']:.3f} s, tras el final del GUION")
            )
    return salida


def todas(datos: Mapping, linea=None) -> dict[str, list[Defecto]]:
    """Las seis comprobaciones (las dos del audio, solo si hay línea de tiempo)."""
    salida = {
        "cabezas_en_cuadro": cabezas_en_cuadro(datos),
        "textos_fuera_de_las_caras": textos_fuera_de_las_caras(datos),
        "pies_en_el_suelo": pies_en_el_suelo(datos),
        "escala_de_cabeza": escala_de_cabeza(datos),
    }
    if linea is not None:
        salida["karaoke"] = karaoke(datos, linea)
        salida["duracion"] = duracion(datos, linea)
    return salida
