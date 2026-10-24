"""El núcleo del obrero de activos: quitar el fondo de croma, separar figuras, apoyarlas, medir su cabeza (F6.2c).

Viene de `canal/scripts/recorte.py`, `prepara.py`, `escala.py` y `sam.py` del experimento video_1, sin
cambiar ni un umbral: lo que aquí se decide ya se midió en las 117 imágenes de su capítulo 1.

**Por qué es un módulo aparte y tan austero.** Lo importan dos procesos en dos entornos: el trabajador
(`obrero_worker.py`, en `.venv-escena`, donde están torch, spandrel y transformers) y el cliente (`obrero.py` y
`activos.py`, en `.venv`). Por eso solo usa numpy, SciPy y Pillow, y **no importa nada de `lib/`**: `lib.config`
necesita `python-dotenv`, que en `.venv-escena` no está. Lo hace cumplir `tests/escena/test_obrero.py`, que lee
las importaciones de este fichero con el AST.

Qué hay aquí, en el orden en que se usa:

- **El fondo de croma** (`quita_magenta`): las figuras se piden sobre magenta y el fondo se quita por TONO, no
  por color exacto, porque el fondo que devuelve Qwen trae degradado, viñeta y sombras del mismo tono. Lo negro
  teñido de magenta no es fondo (`OSCURO`).
- **Las figuras** (`piezas`, `orden_lectura`) y **su punto de apoyo** (`apoyo`): el motor coloca cada actor por
  ese punto, que es el centro de los pies o, en lo que gira (una rueda), el centro de la figura.
- **La entrada de catálogo** (`recorta_caja`, `entrada`): el esquema que consume `compone.py` (`src`, `w`, `h`,
  `ax`, `ay`, `ox`, `oy`, `k`).
- **La cabeza** (`color_de_pelo`, `medida_de_cabeza`, `caja_de_cabeza`, `corrige_escalas`): Qwen dibuja más
  grande a quien no está de pie, y el motor lo corrige con la `k` de cada postura.
- **El borde de una máscara de SAM** (`filtro_guiado`, `mascara_afinada`): la parte de SAM que no necesita GPU.

Aquí no vive ninguna decisión de canal (F4.9): qué personaje se mide y cuál no, sus alturas y sus nombres llegan
como parámetro.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from statistics import median

import numpy as np
from PIL import Image
from scipy import ndimage

# El color de fondo sobre el que se piden las figuras (lo pide `activos.py` en cada prompt). Es del ESTUDIO: es
# la técnica de recorte, no un gusto. Los umbrales de tono de abajo están hechos para él: cambiarlo obliga a
# rehacerlos. Ningún personaje ni objeto de un canal puede llevar este color (se volvería transparente).
CROMA = (255, 0, 255)

# ---------------------------------------------------------------------------------------------------------------
# Umbrales del recorte por tono, medidos en video_1 sobre las imágenes elegidas de su capítulo 1.
# ---------------------------------------------------------------------------------------------------------------
# Por debajo de este brillo (0-1), un píxel de tono magenta es un negro teñido, no fondo: Qwen corre algo de
# magenta sobre lo negro (una bomba de bici, unos dedos con aceite, una cadena) y, tomado por fondo, se volvía
# transparente. El fondo de verdad está por encima de 0,7.
OSCURO = 0.3
# Fondo seguro: el magenta con brillo. El rojo de unas zapatillas queda en ~355° y la piel en ~20°, lejos.
TONO_FONDO = (283.0, 338.0)
SATURACION_FONDO = 0.35
# La viñeta y las sombras bajo los pies son magenta apagado: se aceptan con este criterio más ancho, pero solo
# si tocan el borde de la imagen (nunca dentro de la figura).
TONO_VINETA = (265.0, 345.0)
SATURACION_VINETA = 0.18
# Islas de «fondo» más pequeñas que esto (en px) dentro de la figura son ruido, no huecos.
ISLA_MINIMA_PX = 12
# Ancho de la franja junto al fondo donde el alfa sale de cuánto magenta queda mezclado.
FRANJA_BORDE_PX = 5
# Escalas del relleno del color de fondo local, de grueso a fino.
SIGMAS_FONDO_LOCAL = (24, 8, 3)

# Separar figuras: lo que se une a menos de JUNTA_PX (un mechón suelto, una rueda y su bici) es la misma figura,
# y una pieza por debajo de AREA_MINIMA del total es ruido.
JUNTA_PX = 12
AREA_MINIMA = 0.004
# Margen transparente alrededor de cada recorte.
MARGEN_RECORTE_PX = 16

# Las figuras se recortan a ESCALA_RECORTE veces el tamaño generado (se amplían ×4 con Real-ESRGAN y se bajan).
# Así los primeros planos no se ven borrosos. La `k` de una postura dice cuántos px de su imagen hay por px de la
# escala de referencia, y la escala de referencia es la del lienzo por este factor.
ESCALA_RECORTE = 2

# La cabeza. La MEDIDA es la raíz del área de pelo en esta parte de arriba de la figura, donde solo hay cabeza;
# video_1 la contrastó con SIFT (OpenCV) en dos personajes y las dos medidas coincidieron.
FRANJA_PELO = 0.3
# Tolerancia de color alrededor del color de pelo, y cómo se elige ese color: el más repetido entre los píxeles
# oscuros (suma RGB por debajo de OSCURO_PELO) del cuarto de arriba de la figura de referencia.
TOLERANCIA_PELO = 38.0
OSCURO_PELO = 300
# El ancho de la caja de la cabeza se mide en esta parte de arriba de su franja: al final ya asoman los brazos.
ANCHO_CABEZA = 0.7


class ErrorDeRecorte(ValueError):
    """La imagen no se puede recortar como se pide: el mensaje dice qué ha encontrado."""


# ---------------------------------------------------------------------------------------------------------------
# El fondo de croma
# ---------------------------------------------------------------------------------------------------------------
def magentez(rgb: np.ndarray) -> np.ndarray:
    """Cuánto magenta tiene cada píxel: min(R, B) − G."""
    return np.minimum(rgb[..., 0], rgb[..., 2]) - rgb[..., 1]


def tono_saturacion(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Tono (grados), saturación y valor (0-1) de cada píxel de un RGB en 0-255."""
    r, g, b = (rgb[..., i] / 255 for i in range(3))
    mx, mn = np.maximum(np.maximum(r, g), b), np.minimum(np.minimum(r, g), b)
    d = mx - mn + 1e-6
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    return h, d / (mx + 1e-6), mx


def quita_magenta(rgb: np.ndarray, franja: int = FRANJA_BORDE_PX) -> np.ndarray:
    """RGB (0-255, float) sobre magenta → RGBA uint8 con el fondo transparente.

    - Fondo seguro: tono magenta con brillo por encima de OSCURO (más oscuro es un negro teñido, y es figura).
    - Viñeta y sombras: tono más ancho, pero solo si están conectadas con el borde de la imagen.
    - Los huecos que dejan ver el fondo (entre los dedos, entre los radios de una rueda) son fondo seguro y
      quedan transparentes.
    - Borde: en una franja junto al fondo, el alfa sale de cuánto magenta queda mezclado, comparado con el
      fondo local de ese punto. Al final se le resta ese magenta al color, para que no quede un halo rosa.
    """
    rgb = np.asarray(rgb, dtype=np.float32)
    mg = magentez(rgb)
    h, s, v = tono_saturacion(rgb)
    fondo = (h > TONO_FONDO[0]) & (h < TONO_FONDO[1]) & (s > SATURACION_FONDO) & (v > OSCURO)
    ancho = (h > TONO_VINETA[0]) & (h < TONO_VINETA[1]) & (s > SATURACION_VINETA) & (v > OSCURO)
    etiquetas, _ = ndimage.label(ancho | fondo)
    borde = np.unique(np.concatenate([etiquetas[0], etiquetas[-1], etiquetas[:, 0], etiquetas[:, -1]]))
    fondo |= np.isin(etiquetas, borde[borde > 0])
    etiquetas, n = ndimage.label(fondo)
    if n:
        tamanos = ndimage.sum(fondo, etiquetas, range(1, n + 1))
        fondo = np.isin(etiquetas, 1 + np.flatnonzero(tamanos >= ISLA_MINIMA_PX))
    # Color del fondo local en cada punto: relleno por convolución normalizada, de grueso a fino.
    f = fondo.astype(np.float32)
    local = np.broadcast_to(rgb[fondo].mean(axis=0) if fondo.any() else np.array(CROMA, np.float32), rgb.shape).copy()
    for sigma in SIGMAS_FONDO_LOCAL:
        den = ndimage.gaussian_filter(f, sigma)
        num = np.dstack([ndimage.gaussian_filter(rgb[..., c] * f, sigma) for c in range(3)])
        local = np.where((den > 0.02)[..., None], num / np.maximum(den, 1e-6)[..., None], local)
    mg_local = np.maximum(magentez(local), 1.0)
    alfa = np.clip(1 - mg / mg_local, 0, 1)
    cerca = ndimage.binary_dilation(fondo, iterations=franja)
    alfa = np.where(fondo, 0.0, np.where(cerca, alfa, 1.0))
    # Descontamina: C = a·F + (1 − a)·K  →  F = (C − (1 − a)·K) / a.
    a = alfa[..., None]
    color = np.where(a > 0.02, (rgb - (1 - a) * local) / np.maximum(a, 0.02), 0)
    return np.dstack([np.clip(color, 0, 255), alfa * 255]).astype(np.uint8)


# ---------------------------------------------------------------------------------------------------------------
# Las figuras y su punto de apoyo
# ---------------------------------------------------------------------------------------------------------------
Caja = tuple[int, int, int, int]


def piezas(rgba: np.ndarray, area_min: float = AREA_MINIMA, junta: int = JUNTA_PX, con_mascara: bool = False) -> list:
    """Cajas (x0, y0, x1, y1) de cada figura separada, de izquierda a derecha.

    `junta` une trozos cercanos (un mechón suelto, una rueda y su bici). Con `con_mascara` devuelve también la
    máscara de cada figura, para que al recortar una no se cuele un trozo de la vecina dentro de su caja.
    """
    duro = ndimage.binary_dilation(rgba[..., 3] > 128, iterations=junta)
    etiquetas, _ = ndimage.label(duro)
    total = duro.size
    cajas = []
    for i, sl in enumerate(ndimage.find_objects(etiquetas), start=1):
        if sl is None or (etiquetas[sl] == i).sum() < area_min * total:
            continue
        cajas.append(((sl[1].start, sl[0].start, sl[1].stop, sl[0].stop), i))
    cajas.sort()
    if con_mascara:
        return [(c, etiquetas == i) for c, i in cajas]
    return [c for c, _ in cajas]


def orden_lectura(cajas: Sequence[Caja]) -> list[Caja]:
    """Por filas (centros a menos de media altura media: misma fila) y, dentro de cada fila, de izquierda a derecha."""
    if not cajas:
        return []
    cajas = sorted(cajas, key=lambda c: (c[1] + c[3]) / 2)
    alto = float(np.mean([c[3] - c[1] for c in cajas]))
    filas: list[list[Caja]] = []
    for c in cajas:
        if filas and abs((c[1] + c[3]) / 2 - float(np.mean([(d[1] + d[3]) / 2 for d in filas[-1]]))) < alto / 2:
            filas[-1].append(c)
        else:
            filas.append([c])
    return [c for f in filas for c in sorted(f)]


def union(cajas: Sequence[Caja]) -> Caja:
    """La caja que contiene todas: una figura hecha de varias piezas grandes (una cadena suelta también cuenta)."""
    if not cajas:
        raise ErrorDeRecorte("no hay ninguna figura en la imagen: ¿el fondo no era de croma?")
    return (min(c[0] for c in cajas), min(c[1] for c in cajas), max(c[2] for c in cajas), max(c[3] for c in cajas))


def apoyo(rgba: np.ndarray, centrado: bool) -> tuple[float, float]:
    """El punto por el que el motor coloca la figura: el centro de los pies o, si gira, su centro.

    Los pies son la fila más baja de la figura y lo que queda a menos del 3 % de su alto (4 px como poco) por
    encima; de ahí se toma la mediana en x, así un pie adelantado no arrastra el punto.
    """
    alfa = rgba[..., 3] > 128
    ys, xs = np.nonzero(alfa)
    if not len(ys):
        raise ErrorDeRecorte("la figura está vacía: no tiene ningún píxel opaco")
    if centrado:
        return float((xs.min() + xs.max()) / 2), float((ys.min() + ys.max()) / 2)
    abajo = ys.max()
    fila = xs[ys >= abajo - max(4, int(0.03 * (abajo - ys.min())))]
    return float(np.median(fila)), float(abajo)


def recorta_caja(
    rgba: np.ndarray, caja: Caja, mascara: np.ndarray | None = None, margen: int = MARGEN_RECORTE_PX
) -> tuple[np.ndarray, Caja]:
    """El trozo de la imagen con la figura y un margen, y dónde estaba (x0, y0, x1, y1) en la imagen completa.

    Con `mascara`, lo que cae dentro de la caja y no es de esta figura (un trozo de la vecina) se vuelve
    transparente.
    """
    x0, y0, x1, y1 = caja
    h, w = rgba.shape[:2]
    x0, y0, x1, y1 = max(0, x0 - margen), max(0, y0 - margen), min(w, x1 + margen), min(h, y1 + margen)
    trozo = rgba[y0:y1, x0:x1].copy()
    if mascara is not None:
        trozo[..., 3] = np.where(mascara[y0:y1, x0:x1], trozo[..., 3], 0)
    return trozo, (int(x0), int(y0), int(x1), int(y1))


def entrada(src: str, trozo: np.ndarray, donde: Caja, punto: tuple[float, float], k: float) -> dict:
    """La entrada de catálogo de una figura, con el esquema que consume `compone.py`.

    - `src`, `w`, `h`: la imagen recortada.
    - `ax`, `ay`: su punto de apoyo, en px de esa imagen.
    - `ox`, `oy`: dónde estaba el recorte en la imagen ampliada completa, para volver a juntar piezas que
      salieron de la misma imagen.
    - `k`: px de esta imagen por px de la escala de referencia de las posturas (el motor divide por ella).
    """
    return {
        "src": src,
        "w": int(trozo.shape[1]),
        "h": int(trozo.shape[0]),
        "ax": round(float(punto[0]), 1),
        "ay": round(float(punto[1]), 1),
        "ox": int(donde[0]),
        "oy": int(donde[1]),
        "k": round(float(k), 4),
    }


def pieza_mas_cercana(con_mascaras: Sequence[tuple[Caja, np.ndarray]], x: float, y: float, escala: float) -> tuple:
    """La figura cuyo centro cae más cerca de (x, y), dados en px de la imagen GENERADA (sin ampliar).

    Es como se nombra cada objeto de una lámina de varios: el canal dice dónde está el centro de cada uno.
    """
    if not con_mascaras:
        raise ErrorDeRecorte("no hay ninguna figura en la imagen")
    return min(
        con_mascaras,
        key=lambda cm: (
            ((cm[0][0] + cm[0][2]) / (2 * escala) - x) ** 2 + ((cm[0][1] + cm[0][3]) / (2 * escala) - y) ** 2
        ),
    )


def reparte_por_sitios(
    con_mascaras: Sequence[tuple[Caja, np.ndarray]], sitios: Mapping[str, Sequence[float]], escala: float
) -> list[tuple[str, Caja, np.ndarray]]:
    """(nombre, caja, máscara) de cada figura nombrada por su sitio. Para si dos nombres caen en la misma figura.

    Sin la parada salían dos recortes iguales con dos nombres, sin aviso: el mismo reparto a ciegas que ya se cerró
    para las piezas por orden de lectura (auditoría de F6.2c, recomendación 4). Pasa cuando el canal da dos centros
    que están más cerca de una figura que de la otra, o cuando la imagen tiene menos figuras que nombres.
    """
    elegidas = [(n, *pieza_mas_cercana(con_mascaras, x, y, escala)) for n, (x, y) in sitios.items()]
    por_caja: dict[tuple, list[str]] = {}
    for nombre, caja, _ in elegidas:
        por_caja.setdefault(tuple(caja), []).append(nombre)
    repetidas = [nombres for nombres in por_caja.values() if len(nombres) > 1]
    if repetidas:
        raise ErrorDeRecorte(
            f"{', '.join(' y '.join(n) for n in repetidas)} caen en la misma figura: los sitios no la distinguen "
            f"(la imagen tiene {len(con_mascaras)} figuras para {len(sitios)} nombres). Revisa los centros o la imagen"
        )
    return elegidas


# ---------------------------------------------------------------------------------------------------------------
# La cabeza
# ---------------------------------------------------------------------------------------------------------------
def _filas_opacas(rgba: np.ndarray) -> np.ndarray:
    filas = np.nonzero((rgba[..., 3] > 200).any(axis=1))[0]
    if not len(filas):
        raise ErrorDeRecorte("la figura no tiene ningún píxel opaco")
    return filas


def color_de_pelo(rgba: np.ndarray) -> np.ndarray:
    """El color más repetido entre los píxeles oscuros y opacos del cuarto de arriba (cuantizado de 8 en 8)."""
    a = np.asarray(rgba).astype(int)
    arriba = a[: a.shape[0] // 4]
    oscuros = arriba[(arriba[..., 3] > 200) & (arriba[..., :3].sum(axis=2) < OSCURO_PELO)][:, :3]
    if not len(oscuros):
        raise ErrorDeRecorte(
            "la figura de referencia no tiene pelo oscuro en su cuarto de arriba: no se puede medir la cabeza "
            "por el pelo. Si este personaje no tiene cabeza que medir, el canal lo declara (mide_cabeza=False)"
        )
    valores, cuenta = np.unique(oscuros // 8 * 8 + 4, axis=0, return_counts=True)
    return valores[cuenta.argmax()].astype(np.float32)


def medida_de_cabeza(rgba: np.ndarray, color: np.ndarray) -> float:
    """Raíz del área de pelo en la franja de arriba de la figura, en px de SU imagen (sin dividir por k)."""
    a = np.asarray(rgba).astype(np.float32)
    solido = a[..., 3] > 200
    filas = _filas_opacas(a)
    corte = filas[0] + int((filas[-1] - filas[0]) * FRANJA_PELO)
    pelo = solido & (np.linalg.norm(a[..., :3] - np.asarray(color, np.float32), axis=2) < TOLERANCIA_PELO)
    pelo[corte:] = False
    return float(math.sqrt(float(pelo.sum())))


def caja_de_cabeza(rgba: np.ndarray, alto_cabeza: float) -> list[int]:
    """La caja de la cabeza (px de su imagen): lo opaco de la franja de arriba, con el ancho de su parte alta.

    La franja es `alto_cabeza` del alto de la figura (la de `encuadre.py`); el ancho se mide en su parte de arriba
    (ANCHO_CABEZA), donde no llegan los brazos: con la franja entera, un brazo estirado ensanchaba la cabeza a
    730 px y ninguna tarjeta encontraba sitio sin «pisarle la cara».
    """
    solido = np.asarray(rgba)[..., 3] > 200
    filas = _filas_opacas(np.asarray(rgba))
    y0 = int(filas[0])
    y1 = y0 + int((filas[-1] - filas[0]) * alto_cabeza)
    cols = np.nonzero(solido[y0 : y0 + max(1, int((y1 - y0) * ANCHO_CABEZA))].any(axis=0))[0]
    return [int(cols[0]), y0, int(cols[-1]) + 1, y1]


def corrige_escalas(figuras: Mapping[str, Mapping], umbral: float) -> tuple[dict[str, float], list[str]]:
    """El factor de cada postura para que su cabeza mida lo mismo que de pie. Aritmética pura, sin imágenes.

    `figuras`: {nombre: {pj, vista, de_pie, base, k0, cabeza_px}}, donde `cabeza_px` es la medida en px de su
    imagen (None: no se mide) y `k0` la k con que se recortó.

    - La referencia de cada personaje y vista es la mediana de `cabeza_px / k0` de sus figuras DE PIE y sin base.
    - Una postura que no está de pie se aparta de esa referencia en `f = medida / referencia`; si se aparta
      menos que `umbral`, f = 1 (no se toca).
    - Una variante (con `base`) hereda el factor de su postura limpia.
    - De pie, f = 1: es la referencia.

    Devuelve ({nombre: factor}, informe). Lo que no se puede medir va al informe y queda con factor 1.
    """
    referencias: dict[tuple, list[float]] = {}
    for d in figuras.values():
        if d.get("de_pie") and not d.get("base") and d.get("cabeza_px") is not None:
            referencias.setdefault((d["pj"], d["vista"]), []).append(d["cabeza_px"] / d["k0"])
    factores: dict[str, float] = {}
    informe: list[str] = []
    # Primero las limpias, para que las variantes hereden su factor.
    for nombre in sorted(figuras, key=lambda n: bool(figuras[n].get("base"))):
        d = figuras[nombre]
        if d.get("cabeza_px") is None or d.get("de_pie"):
            factores[nombre] = 1.0
            continue
        base = d.get("base")
        if base:
            if base not in factores:
                informe.append(f"{nombre}: su base {base} no está entre las figuras medidas, se queda como está")
            factores[nombre] = factores.get(base, 1.0)
            continue
        valores = referencias.get((d["pj"], d["vista"]))
        if not valores:
            informe.append(f"{nombre}: sin figuras de pie de {d['pj']} de {d['vista']} con que comparar")
            factores[nombre] = 1.0
            continue
        f = (d["cabeza_px"] / d["k0"]) / median(valores)
        factores[nombre] = 1.0 if abs(f - 1) <= umbral else f
        if factores[nombre] != 1.0:
            informe.append(f"{nombre}: cabeza ×{f:.2f} de la de pie")
    return factores, informe


# ---------------------------------------------------------------------------------------------------------------
# El borde de una máscara de SAM (lo que no necesita GPU)
# ---------------------------------------------------------------------------------------------------------------
# Islas que se conservan junto a la mayor: las de al menos esta parte de su área (un mechón suelto sí; una mota,
# no). Y el filtro guiado que afina el borde contra la imagen.
ISLA_RELATIVA_SAM = 0.02
RADIO_GUIADO = 6
EPS_GUIADO = 1e-3


def _media_caja(a: np.ndarray, r: int) -> np.ndarray:
    return ndimage.uniform_filter(a, size=2 * r + 1, mode="reflect")


def filtro_guiado(guia: np.ndarray, p: np.ndarray, r: int, eps: float) -> np.ndarray:
    """Filtro guiado de He et al.: suaviza `p` respetando los bordes de `guia` (las dos en 0-1)."""
    mi, mp = _media_caja(guia, r), _media_caja(p, r)
    cov = _media_caja(guia * p, r) - mi * mp
    var = _media_caja(guia * guia, r) - mi * mi
    a = cov / (var + eps)
    b = mp - a * mi
    return _media_caja(a, r) * guia + _media_caja(b, r)


def mascara_afinada(logits: np.ndarray, guia: np.ndarray) -> np.ndarray:
    """De los logits de SAM (ya al tamaño de la imagen) a una máscara 0-1 con el borde afinado.

    1. Binariza (logit > 0).
    2. Se queda con la región conexa mayor y con las islas de al menos ISLA_RELATIVA_SAM de su área: SAM deja a
       veces motas sueltas.
    3. Rellena los huecos interiores.
    4. Afina el borde con el filtro guiado contra la imagen, y lo endurece.
    """
    if logits.shape != guia.shape:
        raise ErrorDeRecorte(f"los logits de SAM ({logits.shape}) no tienen el tamaño de la imagen ({guia.shape})")
    duro = (np.asarray(logits) > 0).astype(np.float32)
    etiquetas, n = ndimage.label(duro)
    if n > 1:
        tamanos = ndimage.sum(duro, etiquetas, range(1, n + 1))
        grandes = [i + 1 for i, s in enumerate(tamanos) if s >= ISLA_RELATIVA_SAM * tamanos.max()]
        duro = np.isin(etiquetas, grandes).astype(np.float32)
    duro = ndimage.binary_fill_holes(duro > 0.5).astype(np.float32)
    fino = filtro_guiado(np.asarray(guia, np.float32), duro, r=RADIO_GUIADO, eps=EPS_GUIADO)
    return np.clip((fino - 0.5) * 3 + 0.5, 0, 1)


def plano_gris(rgba: np.ndarray) -> np.ndarray:
    """Una figura con alfa sobre gris medio (RGB float): lo que ve SAM, sin que el fondo transparente cuente."""
    a = np.asarray(rgba).astype(np.float32)
    alfa = a[..., 3:4] / 255
    return a[..., :3] * alfa + 128 * (1 - alfa)


# Una pieza separada lleva este margen, y su borde se suaviza así antes de recortarla.
MARGEN_PIEZA_PX = 8
SUAVIZADO_PIEZA = 0.8


def suaviza(mascara: np.ndarray) -> np.ndarray:
    """El borde de la máscara de una pieza, suavizado para que no se vea el corte al girarla."""
    return np.clip(ndimage.gaussian_filter(np.asarray(mascara, np.float32), SUAVIZADO_PIEZA), 0, 1)


def separa_pieza(
    rgba: np.ndarray, mascara: np.ndarray, pivote: tuple[float, float], base: Mapping, src: str
) -> tuple[np.ndarray, dict]:
    """Una pieza que se mueve sola (un árbol que se mece, una cola), a partir de su máscara sobre su base.

    - `mascara`: 0-1, ya multiplicada por el alfa de la base.
    - `pivote`: dónde gira, en px de la imagen de la base. Es su punto de apoyo.
    - `base`: la entrada de catálogo de la imagen de la que sale. La pieza hereda su `k` (y su `k0`), y `off`
      dice dónde va el pivote respecto al apoyo de la base: en el guion, la pieza es un actor hijo de la base.

    Devuelve (imagen de la pieza, su entrada de catálogo).
    """
    m = np.asarray(mascara, np.float32)
    ys, xs = np.nonzero(m > 0.1)
    if not len(ys):
        raise ErrorDeRecorte("la máscara de la pieza está vacía: la caja o los puntos no caen sobre ella")
    h, w = m.shape
    x0, y0 = max(0, int(xs.min()) - MARGEN_PIEZA_PX), max(0, int(ys.min()) - MARGEN_PIEZA_PX)
    x1, y1 = min(w, int(xs.max()) + MARGEN_PIEZA_PX + 1), min(h, int(ys.max()) + MARGEN_PIEZA_PX + 1)
    trozo = np.asarray(rgba).copy()
    trozo[..., 3] = (m * 255).astype(np.uint8)
    px, py = float(pivote[0]), float(pivote[1])
    e = {
        "src": src,
        "w": x1 - x0,
        "h": y1 - y0,
        "ax": round(px - x0, 1),
        "ay": round(py - y0, 1),
        "ox": int(base.get("ox", 0)) + x0,
        "oy": int(base.get("oy", 0)) + y0,
        "k": base.get("k", 1.0),
        **({"k0": base["k0"]} if "k0" in base else {}),
        "off": [round(px - float(base.get("ax", 0)), 1), round(py - float(base.get("ay", 0)), 1)],
    }
    return trozo[y0:y1, x0:x1], e


def abre_figura(ruta) -> np.ndarray:
    with Image.open(ruta) as im:
        return np.asarray(im.convert("RGBA")).copy()
