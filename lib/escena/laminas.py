"""El formato «láminas» del motor de escena (F6.8, fila 233): la cámara recorre la lámina entera.

Es el movimiento de lienzo del motor de láminas (`lib/motion.py`, F2.6) llevado al motor de escena, que lo retiró en
F6.7: este módulo es ya la única copia de su catálogo y de su reparto. Nace porque animar una lámina a tinta por
piezas la deforma (filas 230 y 233). Lo que hace:

- **Cada lámina se parte en tomas** de unos `toma_s` segundos, nunca de menos de `toma_minima_s`. Una lámina de 30 s
  rinde así tres encuadres distintos.
- **Cada toma lleva un movimiento del catálogo** (`MOVIMIENTOS`): un acercamiento, un barrido, un descenso… Se reparten
  con un paso coprimo con el tamaño del catálogo, así que dos tomas seguidas nunca repiten movimiento. Una variación
  determinista (el «jitter») mueve su intensidad y su punto focal, para que dos tomas con el mismo movimiento no salgan
  calcadas. Todo sale de dos claves de texto: el título del vídeo y la descripción de cada lámina. El mismo episodio da
  siempre el mismo montaje.
- **Cada toma entra con una transición**: suave entre dos tomas de la misma lámina y de tinta entre dos láminas
  (`TRANSICIONES`). Las que el canal tacha (`transiciones_excluidas`) no salen. Si a una toma le toca una tachada,
  avanza a la siguiente del catálogo, sin mover el sorteo de las demás.
- **La cámara nunca enseña el borde**: el zoom parte de `zoom_base` > 1, que deja fuera el margen de la propia lámina,
  y el punto focal se recorta contra el recorrido que deja cada zoom. El motor, además, no deja salir la vista del
  fondo (`Motor.camara`).

**Es el algoritmo del motor de láminas, número a número**: con las mismas entradas da los mismos movimientos, zooms,
puntos focales, curvas y transiciones. `tests/escena/test_laminas.py` lo compara con el montaje que aquel motor hizo
del capítulo publicado de la pera (`tests/escena/datos/pera-publicada.json`). Tres diferencias, y las tres son del
motor de escena:

1. **El zoom se interpola en escala logarítmica** (`Motor.camara`), y el motor viejo lo hacía en línea recta. Entre
   1,15 y 1,30 se separan menos de un 0,3 %.
2. **`parallax_deriva` es un movimiento más**: el motor viejo lo hacía con dos capas desenfocadas de la lámina, que se
   desplazaban a velocidades distintas. Aquí la lámina va entera, con el mismo recorrido.
3. **Las pausas del motor de escena** (`escena.pausas`) alargan cada lámina, y con ellas puede cambiar cuántas tomas
   rinde. Una lámina se ve desde que acaba la voz de la anterior hasta que acaba la suya; la primera, desde el
   principio, y la última, hasta el final de la cola.

Qué es de quién (F4.9): el catálogo, el reparto y la conversión a la cámara son del estudio. El canal declara en su
perfil (`escena.laminas`) el zoom base y el máximo, cuánto dura una toma, lo que dura una transición, las transiciones
que tacha y las fuentes de sus rótulos (OC1.2), que salen de la biblioteca del estudio. Ninguno tiene valor por
omisión.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from lib.escena import tinta
from lib.escena.escena import Guion

# ---------------------------------------------------------------------------------------------- el catálogo
# `zoom`: recorrido del zoom, en múltiplos de `zoom_base`. `pan`: desplazamiento del punto focal, en fracción del
# recorrido disponible a ese zoom (±1 = hasta el borde); positivo = el encuadre se va a la derecha o hacia abajo.
# `curva`: la del motor de láminas (linear, ease_in, ease_out, ease_in_out). Son los trece de su `_MOVES`.
MOVIMIENTOS: tuple[dict, ...] = (
    {"nombre": "acercamiento_lento", "zoom": (1.00, 1.16), "pan": (0.12, -0.10), "curva": "ease_in_out"},
    {"nombre": "barrido_derecha", "zoom": (1.24, 1.24), "pan": (-0.92, 0.0), "curva": "ease_in_out"},
    {"nombre": "alejamiento_revelacion", "zoom": (1.26, 1.00), "pan": (0.55, 0.35), "curva": "ease_out"},
    {"nombre": "detalle_derecha", "zoom": (1.02, 1.34), "pan": (0.70, 0.12), "curva": "ease_in"},
    {"nombre": "descenso", "zoom": (1.18, 1.18), "pan": (0.0, 0.88), "curva": "ease_in_out"},
    {"nombre": "deriva_diagonal", "zoom": (1.08, 1.22), "pan": (0.45, -0.35), "curva": "ease_in_out"},
    {"nombre": "barrido_izquierda", "zoom": (1.24, 1.24), "pan": (0.92, 0.0), "curva": "ease_in_out"},
    {"nombre": "detalle_izquierda", "zoom": (1.02, 1.34), "pan": (-0.70, 0.14), "curva": "ease_in"},
    {"nombre": "ascenso_revelacion", "zoom": (1.30, 1.10), "pan": (-0.25, -0.80), "curva": "ease_out"},
    {"nombre": "parallax_deriva", "zoom": (1.10, 1.22), "pan": (0.40, 0.0), "curva": "ease_in_out"},
    {"nombre": "empuje_lateral", "zoom": (1.16, 1.16), "pan": (0.60, -0.10), "curva": "ease_in_out"},
    {"nombre": "respiracion", "zoom": (1.08, 1.15), "pan": (0.30, 0.20), "curva": "ease_in_out"},
    {"nombre": "acercamiento_rapido", "zoom": (1.06, 1.28), "pan": (-0.20, 0.18), "curva": "ease_out"},
)
# Coprimo con 13: dos tomas seguidas nunca repiten movimiento y el ciclo entero dura 13 tomas.
PASO_MOVIMIENTO = 5

# Las curvas del motor viejo en el motor de escena (`Motor.EASE`): `ease_in` es p², `ease_out` 1 − (1 − p)² y
# `ease_in_out` el smoothstep.
CURVAS = {"linear": "lineal", "ease_in": "acelera", "ease_out": "frena", "ease_in_out": "suave"}

# Cada transición del motor de láminas (su `TRANSITIONS`, con xfade) como entrada de plano del motor de escena
# (`compone.ENTRADAS_DE_PLANO`). Los nombres son los del motor viejo, que son los que tacha un perfil.
# `plate_reveal` (revealright: la lámina vieja se va por la derecha y descubre la nueva) es la única aproximada: aquí
# la nueva entra empujando desde la izquierda, con el `barrido` del motor. El primer canal que usa el formato la tacha.
TRANSICIONES: dict[str, dict] = {
    "dissolve": {"tipo": "funde"},
    "ink_bleed": {"tipo": "calado"},
    "ink_wipe_right": {"tipo": "cortina", "dir": "derecha"},
    "ink_wipe_left": {"tipo": "cortina", "dir": "izquierda"},
    "ink_wipe_up": {"tipo": "cortina", "dir": "arriba"},
    "ink_streak_right": {"tipo": "viento", "dir": "derecha"},
    "ink_streak_left": {"tipo": "viento", "dir": "izquierda"},
    "ink_blot": {"tipo": "mancha"},
    "paper_flash": {"tipo": "papel"},
    "plate_reveal": {"tipo": "barrido", "dir": -1},
}
# Entre dos tomas de la MISMA lámina el cambio es entre encuadres del mismo grabado: transiciones suaves.
SUAVES = ("dissolve", "ink_bleed", "ink_wipe_up", "dissolve", "ink_wipe_right")
# Entre dos láminas, el gesto de tinta.
DE_TINTA = (
    "ink_wipe_right",
    "ink_bleed",
    "ink_streak_right",
    "ink_blot",
    "ink_wipe_left",
    "plate_reveal",
    "paper_flash",
)
PASO_SUAVE = 2  # coprimo con 5
PASO_TINTA = 3  # coprimo con 7

# Lo que el canal declara en `perfil.json → escena.laminas`, sin defecto: clave → qué es.
AJUSTES = {
    "zoom_base": "el zoom mínimo, > 1: deja fuera de cuadro el margen de la propia lámina (1,06 en el motor viejo)",
    "zoom_maximo": "el techo del zoom (1,45 en el motor viejo)",
    "toma_s": "lo que dura una toma, en segundos (10)",
    "toma_minima_s": "lo que dura como mínimo (5)",
    "transicion_s": "lo que dura una transición, en segundos (2,0: MOTION_SEGUNDOS_TRANSICION del .env de producción)",
    "transiciones_excluidas": f"las del catálogo que el canal no quiere, [] para ninguna ({', '.join(TRANSICIONES)})",
    "fuentes_de_los_rotulos": (
        '{papel: fichero} de las fuentes con que la capa del canal escribe sus rótulos a tinta, p. ej. {"redonda": …, '
        '"cursiva": …}; cada una, de la biblioteca del estudio (datos/escena/fuentes/), con su licencia'
    ),
}


class ErrorDeLaminas(ValueError):
    """El formato no se puede montar así: el mensaje dice qué falta o qué está mal."""


def ajustes(escena: Mapping) -> dict:
    """El bloque `laminas` del bloque `escena` del perfil, comprobado. Para y dice qué escribir si falta algo."""
    bloque = escena.get("laminas") if isinstance(escena, Mapping) else None
    if not isinstance(bloque, Mapping):
        raise ErrorDeLaminas(
            "el perfil del canal no declara `escena.laminas`, lo que el formato «láminas» necesita y no tiene valor "
            "por defecto: " + "; ".join(f"`{k}`: {que}" for k, que in AJUSTES.items())
        )
    faltan = [k for k in AJUSTES if k not in bloque]
    if faltan:
        raise ErrorDeLaminas(
            "a `escena.laminas` le faltan "
            + "; ".join(f"`{k}` ({AJUSTES[k]})" for k in faltan)
            + ". No tienen valor por defecto."
        )
    a = {k: bloque[k] for k in AJUSTES}
    for k in ("zoom_base", "zoom_maximo", "toma_s", "toma_minima_s", "transicion_s"):
        if not isinstance(a[k], (int, float)) or isinstance(a[k], bool) or not a[k] > 0:
            raise ErrorDeLaminas(f"`escena.laminas.{k}` tiene que ser un número positivo, no {a[k]!r}")
    if not 1 < a["zoom_base"] <= a["zoom_maximo"]:
        raise ErrorDeLaminas(
            f"`escena.laminas`: el zoom base ({a['zoom_base']}) tiene que ser mayor que 1 y no pasar del máximo "
            f"({a['zoom_maximo']}): con 1 el borde de la lámina entra en cuadro al desplazarse"
        )
    if a["toma_minima_s"] > a["toma_s"]:
        raise ErrorDeLaminas("`escena.laminas`: la toma mínima no puede durar más que la toma")
    excluidas = a["transiciones_excluidas"]
    if not isinstance(excluidas, list) or not all(isinstance(n, str) for n in excluidas):
        raise ErrorDeLaminas(f"`escena.laminas.transiciones_excluidas` es una lista de nombres, no {excluidas!r}")
    desconocidas = sorted(set(excluidas) - set(TRANSICIONES))
    if desconocidas:
        raise ErrorDeLaminas(
            f"`escena.laminas.transiciones_excluidas` nombra transiciones que no existen: {desconocidas}. Una "
            f"exclusión mal escrita dejaría pasar la que se quería tachar. Catálogo: {', '.join(TRANSICIONES)}"
        )
    for catalogo, nombre in ((SUAVES, "suave"), (DE_TINTA, "de tinta")):
        if set(catalogo) <= set(excluidas):
            raise ErrorDeLaminas(f"`escena.laminas` tacha todas las transiciones del catálogo {nombre}: deja una")
    a["transiciones_excluidas"] = frozenset(excluidas)
    fuentes = a["fuentes_de_los_rotulos"]
    if not (
        isinstance(fuentes, Mapping)
        and fuentes
        and all(isinstance(k, str) and k and isinstance(v, str) and v for k, v in fuentes.items())
    ):
        raise ErrorDeLaminas(
            f"`escena.laminas.fuentes_de_los_rotulos` es un {{papel: fichero}} con al menos una fuente, no {fuentes!r}"
        )
    a["fuentes_de_los_rotulos"] = dict(fuentes)
    return a


def fuentes_de_los_rotulos(ajustes_: Mapping, css: str) -> dict[str, Path]:
    """{papel: ruta} de las fuentes de los rótulos del canal (OC1.2): las de su perfil, de la biblioteca del estudio.

    Para si una no está en la biblioteca o si el CSS del canal no la declara: sin eso la letra saldría en el vídeo sin
    su licencia en `assets.json` (`tinta.fuente_de_la_biblioteca`). Hasta OC1.2 la capa del canal leía Georgia de
    Windows, que no se puede redistribuir.
    """
    try:
        return {p: tinta.fuente_de_la_biblioteca(n, css) for p, n in ajustes_["fuentes_de_los_rotulos"].items()}
    except tinta.ErrorDeTinta as e:
        raise ErrorDeLaminas(f"`escena.laminas.fuentes_de_los_rotulos`: {e}") from e


# ---------------------------------------------------------------------------------------------- determinismo
def _hash(texto: str) -> int:
    """Hash estable entre procesos (el del motor de láminas). md5 no es aquí criptografía: `hash()` lleva sal."""
    return int(hashlib.md5(texto.encode("utf-8")).hexdigest()[:8], 16)


def _unidad(texto: str, sal: str) -> float:
    """Un valor determinista en [0, 1) que sale del texto: la variación de cada toma."""
    return (_hash(f"{sal}|{texto}") % 10_000) / 10_000.0


# ---------------------------------------------------------------------------------------------- el reparto
@dataclass(frozen=True)
class Lamina:
    """Una lámina del episodio: su número, cuántos fotogramas se ve y la clave de su variación (su descripción)."""

    numero: int
    fotogramas: int
    clave: str


@dataclass(frozen=True)
class Toma:
    """Un encuadre animado sobre una lámina, con la transición con la que entra (None en la primera del vídeo).

    `zoom` y `foco` son los del motor viejo: el zoom sobre la lámina recortada a 16:9 y el punto focal en fracción
    de ella, al principio y al final de la toma.
    """

    lamina: int
    indice: int  # su orden dentro de la lámina (0 = la primera)
    inicio: int  # fotograma del vídeo en que empieza
    fotogramas: int
    movimiento: str
    curva: str
    zoom: tuple[float, float]
    foco: tuple[tuple[float, float], tuple[float, float]]
    transicion: str | None


def _cuantas(fotogramas: int, fps: int, a: Mapping) -> int:
    """Cuántas tomas rinde una lámina: ~`toma_s` cada una y nunca menos de `toma_minima_s`."""
    segundos = fotogramas / fps
    if segundos < 2 * a["toma_minima_s"]:
        return 1
    n = max(1, round(segundos / a["toma_s"]))
    while n > 1 and segundos / n < a["toma_minima_s"]:
        n -= 1
    return n


def _reparte(fotogramas: int, partes: int) -> list[int]:
    """El reparto exacto: la suma es siempre `fotogramas`, sin deriva contra el audio."""
    base, extra = divmod(fotogramas, partes)
    return [base + (1 if i < extra else 0) for i in range(partes)]


def _transicion(desplazamiento: int, ordinal: int, misma_lamina: bool, excluidas: frozenset[str]) -> str:
    catalogo, paso = (SUAVES, PASO_SUAVE) if misma_lamina else (DE_TINTA, PASO_TINTA)
    inicio = (desplazamiento + ordinal * paso) % len(catalogo)
    for salto in range(len(catalogo)):
        candidata = catalogo[(inicio + salto) % len(catalogo)]
        if candidata not in excluidas:
            return candidata
    raise ErrorDeLaminas("todas las transiciones del catálogo están tachadas")  # `ajustes` ya lo impide


def _recorrido(zoom: float, a: Mapping) -> float:
    """Cuánto se puede desviar el punto focal del centro, a ese zoom, sin pisar el margen de la lámina."""
    return max(0.0, (1.0 / a["zoom_base"] - 1.0 / zoom) / 2)


def _toma(lamina: Lamina, indice: int, inicio: int, fotogramas: int, desplazamiento: int, ordinal: int,
          transicion: str | None, a: Mapping) -> Toma:  # fmt: skip
    """Una toma, con la aritmética del motor de láminas (su `_build_shot`) para el modo ken_burns."""
    mov = MOVIMIENTOS[(desplazamiento + ordinal * PASO_MOVIMIENTO) % len(MOVIMIENTOS)]
    intensidad = 0.85 + 0.30 * _unidad(lamina.clave, f"intensity{indice}")
    intensidad = max(0.0, min(1.6, intensidad))
    base, techo = a["zoom_base"], a["zoom_maximo"]
    z0 = min(max(base * (1 + (mov["zoom"][0] - 1) * intensidad), 1.0), techo)
    z1 = min(max(base * (1 + (mov["zoom"][1] - 1) * intensidad), 1.0), techo)
    r0, r1 = _recorrido(z0, a), _recorrido(z1, a)
    variacion = max(r0, r1) * 0.35
    ax = 0.5 + (_unidad(lamina.clave, f"fx{indice}") - 0.5) * variacion
    ay = 0.5 + (_unidad(lamina.clave, f"fy{indice}") - 0.5) * variacion
    px = max(-1.0, min(1.0, mov["pan"][0] * intensidad))
    py = max(-1.0, min(1.0, mov["pan"][1] * intensidad))

    def encuadra(ancla: float, pan: float, recorrido: float) -> float:
        return min(max(ancla + pan * recorrido, 0.5 - recorrido), 0.5 + recorrido)

    foco = ((encuadra(ax, -px, r0), encuadra(ay, -py, r0)), (encuadra(ax, px, r1), encuadra(ay, py, r1)))
    return Toma(lamina.numero, indice, inicio, fotogramas, mov["nombre"], mov["curva"], (z0, z1), foco, transicion)


def planifica(laminas: Sequence[Lamina], *, clave_del_video: str, fps: int, ajustes_: Mapping) -> list[Toma]:
    """Las tomas del vídeo, en orden. `clave_del_video` es su título (`slides.json → title`)."""
    if not laminas:
        raise ErrorDeLaminas("no hay láminas que montar")
    desplazamiento = _hash(clave_del_video)
    tomas: list[Toma] = []
    ordinal, inicio = 0, 0
    for lamina in laminas:
        if lamina.fotogramas <= 0:
            raise ErrorDeLaminas(f"la lámina {lamina.numero} no dura ningún fotograma")
        partes = _reparte(lamina.fotogramas, _cuantas(lamina.fotogramas, fps, ajustes_))
        for indice, fotogramas in enumerate(partes):
            transicion = (
                None
                if not tomas
                else _transicion(desplazamiento, ordinal, indice > 0, ajustes_["transiciones_excluidas"])
            )
            tomas.append(_toma(lamina, indice, inicio, fotogramas, desplazamiento, ordinal, transicion, ajustes_))
            ordinal += 1
            inicio += fotogramas
    return tomas


# ---------------------------------------------------------------------------------------------- a la cámara
def _cola(siguiente: Toma | None, fps: int, a: Mapping) -> int:
    """Los fotogramas de más que una toma sigue viéndose debajo de la transición de la siguiente."""
    if siguiente is None:
        return 0
    return max(1, round(a["transicion_s"] * fps))


def prolonga(toma: Toma, cola: int, a: Mapping) -> tuple[tuple[float, float], tuple[tuple[float, float], ...]]:
    """El zoom y el foco del final de la toma alargada `cola` fotogramas: el movimiento SIGUE bajo la transición.

    Es lo que hacía el motor de láminas (su `render_shot`): una toma que se queda quieta debajo de la transición delata
    el truco.
    **Con una diferencia**: allí el zoom de un alejamiento alargado bajaba del zoom base y el margen de la lámina
    asomaba bajo la transición. Aquí no baja del zoom base.
    """
    if cola == 0:
        return toma.zoom, toma.foco
    k = (toma.fotogramas + cola) / toma.fotogramas
    z1 = min(a["zoom_maximo"], max(a["zoom_base"], toma.zoom[0] + (toma.zoom[1] - toma.zoom[0]) * k))
    r = _recorrido(z1, a)
    f1 = tuple(min(max(s + (e - s) * k, 0.5 - r), 0.5 + r) for s, e in zip(toma.foco[0], toma.foco[1]))
    return (toma.zoom[0], z1), (toma.foco[0], f1)


def en_la_lamina(foco: tuple[float, float], ancho: float, alto: float, marco: Mapping) -> tuple[float, float]:
    """Un punto focal del motor viejo, en px del fondo del motor de escena.

    El motor viejo recortaba la lámina al 16:9 del marco por el centro y medía el foco en fracción de ese recorte; el
    motor de escena mide en px del fondo entero, y su zoom 1 es «el fondo entero a lo ancho», el mismo que allí.
    """
    proporcion = marco["w"] / marco["h"]
    if ancho / alto >= proporcion:  # la lámina es más ancha que el marco: se recortan los lados
        w, h = alto * proporcion, alto
    else:  # más alta: se recorta arriba y abajo
        w, h = ancho, ancho / proporcion
    return (ancho - w) / 2 + foco[0] * w, (alto - h) / 2 + foco[1] * h


def pon_en_escena(g: Guion, tomas: Sequence[Toma], sets: Mapping[int, str], *, ajustes_: Mapping) -> list:
    """Un plano por toma, sobre el set de su lámina, con su transición y su cámara. Devuelve los planos.

    `sets` es {número de lámina: set registrado en el guion}. La cámara va del encuadre del principio al del final de
    la toma alargada bajo la transición siguiente, con la curva de su movimiento.
    """
    fps, marco = g.escena["fps"], g.escena["marco"]
    d = ajustes_["transicion_s"]
    planos = []
    for i, toma in enumerate(tomas):
        if toma.lamina not in sets:
            raise ErrorDeLaminas(f"la lámina {toma.lamina} no tiene set en el guion")
        fondo = g.imagen(g.fondos[sets[toma.lamina]].img)
        t0, t1 = toma.inicio / fps, (toma.inicio + toma.fotogramas) / fps
        if toma.transicion is None:
            p = g.plano(sets[toma.lamina], t0, t1)
        else:
            entra = TRANSICIONES[toma.transicion]
            p = g.plano(sets[toma.lamina], t0, t1, entra=entra["tipo"], d=d, dir=entra.get("dir"))
        cola = _cola(tomas[i + 1] if i + 1 < len(tomas) else None, fps, ajustes_)
        zoom, foco = prolonga(toma, cola, ajustes_)
        (x0, y0), (x1, y1) = (en_la_lamina(f, fondo["w"], fondo["h"], marco) for f in foco)
        dura = (toma.fotogramas + cola) / fps
        p.cam(t0, x0, y0, zoom[0], tr=0)
        p.cam(t0 + 0.01, x1, y1, zoom[1], tr=dura - 0.01, e=CURVAS[toma.curva])
        planos.append(p)
    return planos


def laminas_del_episodio(linea, slides: Sequence[Mapping]) -> list[Lamina]:
    """Las láminas del episodio con lo que se ve cada una, sobre la línea de tiempo de su voz.

    Una lámina se ve desde que acaba la voz de la anterior hasta que acaba la suya, así que la pausa que hay entre dos
    láminas es ya de la siguiente; la primera empieza en 0 (la intro) y la última llega al final (la cola). Su clave es
    la descripción de la lámina (`image_prompt`), la del motor viejo.
    """
    fps = linea.fps
    por_numero = {int(s.get("slide_number", i + 1)): s for i, s in enumerate(slides)}
    cortes = [0] + [round((linea.inicio[k] - linea.pausa) * fps) for k in range(1, len(linea.laminas))]
    cortes.append(round(linea.total * fps))
    salida = []
    for k, numero in enumerate(linea.laminas):
        s = por_numero.get(numero, {})
        clave = s.get("image_prompt") or s.get("narration") or f"slide-{k}"
        salida.append(Lamina(numero, cortes[k + 1] - cortes[k], clave))
    return salida
