"""El formato «pizarra» del motor de escena (F7.10, filas 256 y 257): la pizarra que se construye por etapas.

Se imita de Dr. Ares Senior (el gate 0 del canal que lo eligió, §2.9): siempre una pizarra de borde a borde que se
llena por partes al ritmo de la voz, con la cámara casi fija y corte seco entre pizarras. Cada pocos segundos aparece
un dibujo, una etiqueta o una lista; las piezas entran de golpe o con un fundido corto, sin mano. La única
modificación firmada es que **el texto se escribe trazo a trazo** con la tinta del formato «láminas»
(`lib/escena/tinta.py`, F6.8).

Lo que hace este módulo, en el orden del pipeline:

1. **Separa la tiza de la pizarra** (`separa_tiza`), en Python y antes del render, porque el motor no admite
   `mix-blend-mode` (fila 199). La pizarra limpia se estima con una apertura morfológica de núcleo más ancho que un
   trazo: borra las líneas finas y conserva los borrones anchos de tiza usada. La tiza es lo que la imagen tiene de
   más luminoso que esa pizarra limpia: su opacidad sale de ese exceso, y su color se despeja de la mezcla
   (`C = B + (P − B) / α`), así que el amarillo se conserva y la tiza encima de la pizarra limpia vuelve a dar la
   imagen original.
2. **Parte la tiza en piezas** (`parte_en_piezas`): cada mancha suelta, después de engordar la tiza para juntar los
   trazos de un mismo dibujo, es una pieza, numerada en orden de lectura. La tiza de las piezas diminutas se queda en
   la pizarra desde el principio, así que no se pierde nada. `separa` lo escribe en el catálogo del episodio con su
   procedencia, y deja una **hoja numerada** en `revision/` para que quien escribe la escena elija las piezas.
3. **Pone la pizarra en escena** (`Pizarra`): un plano con la cámara fija y, si la pizarra es densa, un acercamiento
   lento; las piezas, los textos, la flecha que fluye y la gráfica, cada uno en el instante que le da el guion (las
   anclas `C`, `F` y `P` de `lib/escena/anclas.py`, a la palabra que lo nombra).
4. **Borra un texto** con el borrador, que barre la tiza de izquierda a derecha (la salida `borra` del motor), y
   **reserva la pizarra** para un solo texto mientras está (F7.10, fila 264): es el título del episodio que el canal
   escribe en el centro de la pizarra vacía y borra antes de empezar la clase. Dónde y cuándo, lo decide el canal.

**Las cifras no salen de Qwen.** El modelo no sabe no escribir y una cifra del prompt acaba dibujada
(el contrato de prompt del primer canal de pizarra, lección 2). Todo texto y toda cifra de la pizarra los
escribe la tinta, y una barra de la gráfica mide su valor porque lo calcula `barras`.

**Qué es de quién** (F4.9). El mecanismo es del estudio. Todos los valores (el núcleo y los umbrales de la
separación, los tiempos de la tinta y del borrador, los fundidos, la cámara, la fuente, sus tamaños, la flecha y la
gráfica) los declara el canal en `perfil.json → escena.pizarra`, sin defecto: un perfil sin una clave para y dice
cuál. Los colores son del CSS del canal, y la disposición de cada pizarra, del guion del episodio.
"""

from __future__ import annotations

import html
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from lib import provenance
from lib.escena import obrero, recorte, tinta
from lib.escena.escena import Elemento, Guion, Plano

NUMERO, TEXTO, MAPA = "número", "texto", "objeto"

# Lo que el canal declara en `perfil.json → escena.pizarra`, sin defecto: ruta → (tipo, qué es).
AJUSTES: dict[str, tuple[str, str]] = {
    "separa.nucleo_px": (NUMERO, "diámetro del núcleo de la apertura, en px de la pizarra ampliada: más ancho que un "
                                 "trazo de tiza y más estrecho que un borrón"),
    "separa.umbral": (NUMERO, "exceso de luminosidad (0-255) sobre la pizarra limpia por debajo del cual no es tiza"),
    "separa.tiza_plena": (NUMERO, "exceso de luminosidad a partir del cual la tiza es opaca"),
    "separa.agrupa_px": (NUMERO, "cuántos px se engorda la tiza para juntar en una pieza los trazos de un dibujo"),
    "separa.umbral_oscuro": (NUMERO, "lo que un px de un dibujo tiene que ser más oscuro que la pizarra limpia para "
                                     "ir con su pieza"),
    "separa.masa_minima_px": (NUMERO, "una mancha con menos px de tiza opaca no es pieza: se queda en la pizarra o va "
                                      "con el dibujo que la rodea"),
    "pieza.funde_s": (NUMERO, "lo que dura el fundido corto de una pieza que no entra de golpe"),
    "camara.zoom": (NUMERO, "el zoom de la cámara fija (1: la pizarra entera a lo ancho)"),
    "camara.acercamiento": (NUMERO, "cuánto se acerca la cámara en una pizarra densa (0,07 es un 7 %)"),
    "camara.acercamiento_s": (NUMERO, "en cuántos segundos"),
    "transicion.cambio_de_tema_s": (NUMERO, "el fundido entre dos pizarras de temas distintos; si no, corte seco"),
    "texto.fuente": (TEXTO, "el fichero de la fuente de tiza en la biblioteca del estudio (datos/escena/fuentes/)"),
    "texto.letra_s": (NUMERO, "lo que tarda el trazo en recorrer el contorno de una letra"),
    "texto.relleno_tras": (NUMERO, "qué parte de la letra lleva recorrida el trazo cuando empieza a rellenarse (0-1)"),
    "texto.relleno_s": (NUMERO, "lo que tarda una letra en rellenarse"),
    "texto.paso_s": (NUMERO, "cuánto espera cada letra a la anterior"),
    "texto.espaciado": (NUMERO, "lo que se añade detrás de cada letra, en fracción del tamaño"),
    "texto.interlineado": (NUMERO, "la distancia entre dos líneas, en fracción del tamaño"),
    "texto.borra_s": (NUMERO, "lo que tarda el borrador en pasar por un texto que se borra"),
    "texto.tamanos": (MAPA, "{nombre: px de la pizarra ampliada} de cada tamaño de letra (título, etiqueta, cifra…)"),
    "flecha.velocidad_px_s": (NUMERO, "lo que corren los guiones de una flecha que fluye, en px de la pizarra por s"),
    "flecha.punta_px": (NUMERO, "el largo de cada trazo de la punta de una flecha"),
    "grafica.hueco": (NUMERO, "la parte de cada columna de la gráfica que queda libre entre dos barras (0-1)"),
    "grafica.trazo_s": (NUMERO, "lo que tarda en dibujarse el contorno de una barra"),
    "grafica.rayado_px": (NUMERO, "la separación entre las rayas de tiza que rellenan una barra"),
}  # fmt: skip
# Las que dividen o fijan un tamaño: tienen que ser > 0.
POSITIVOS = (
    "separa.nucleo_px", "separa.tiza_plena", "pieza.funde_s", "camara.zoom", "camara.acercamiento",
    "camara.acercamiento_s", "transicion.cambio_de_tema_s", "texto.letra_s", "texto.relleno_s", "texto.paso_s",
    "texto.interlineado", "texto.borra_s", "flecha.punta_px", "grafica.trazo_s", "grafica.rayado_px",
)  # fmt: skip
# El margen de los instantes que se comparan (los del guion van redondeados al milisegundo).
EPS = 1e-6
# El margen de px que lleva cada pieza recortada alrededor de su tiza (el borde suave no se corta).
MARGEN_PIEZA = 2
# Los nombres de lo que `separa` escribe en el catálogo del episodio.
SUFIJO_LIMPIA = "_limpia"
# Lo ancha que sale la hoja numerada de una pizarra (es para mirarla en la parada 1, no entra en el vídeo).
ANCHO_DE_LA_HOJA = 1600
# El grano de la pizarra (lo que la imagen tiene de más que su versión desenfocada con este radio, en px) se copia de
# la pizarra de alrededor a la de debajo de cada pieza, para que no se vea una mancha lisa antes de que llegue.
GRANO_SIGMA_PX = 1.2
# Y solo el grano fino: lo que se aparta más que esto de la media es el borde de un borrón, no grano.
GRANO_MAXIMO = 10.0
# De dónde se copia, en fracción del ancho y del alto: el primer desplazamiento que cae en pizarra a la vista.
GRANO_DESPLAZAMIENTOS = ((0, 0.33), (0, -0.33), (0, 0.5), (0, -0.5), (0.3, 0), (-0.3, 0), (0.3, 0.33), (-0.3, -0.33))


class ErrorDePizarra(ValueError):
    """La pizarra no se puede separar o poner en escena así: el mensaje dice qué falta o qué está mal."""


def _en_ruta(nodo, ruta: str):
    for parte in ruta.split("."):
        if not isinstance(nodo, Mapping) or parte not in nodo:
            return None
        nodo = nodo[parte]
    return nodo


def _es_numero(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def ajustes(escena: Mapping) -> dict:
    """El bloque `pizarra` del bloque `escena` del perfil, comprobado. Para y dice qué escribir si falta algo."""
    bloque = escena.get("pizarra") if isinstance(escena, Mapping) else None
    if not isinstance(bloque, Mapping):
        raise ErrorDePizarra(
            "el perfil del canal no declara `escena.pizarra`, lo que el formato «pizarra» necesita y no tiene valor "
            "por defecto: " + "; ".join(f"`{k}` ({que})" for k, (_, que) in AJUSTES.items())
        )
    faltan = []
    for ruta, (tipo, que) in AJUSTES.items():
        v = _en_ruta(bloque, ruta)
        valido = (
            _es_numero(v)
            if tipo == NUMERO
            else isinstance(v, str) and bool(v)
            if tipo == TEXTO
            else isinstance(v, Mapping) and bool(v)
        )
        if not valido:
            faltan.append(f"`escena.pizarra.{ruta}` ({tipo}: {que})")
    if faltan:
        raise ErrorDePizarra("al perfil le falta " + "; ".join(faltan) + ". No tienen valor por defecto.")
    nulos = [f"`escena.pizarra.{r}`" for r in POSITIVOS if not _en_ruta(bloque, r) > 0]
    if nulos:
        raise ErrorDePizarra(f"{', '.join(nulos)} tienen que ser mayores que 0")
    sep = bloque["separa"]
    if not 0 <= sep["umbral"] < sep["tiza_plena"]:
        raise ErrorDePizarra("`escena.pizarra.separa`: el umbral va de 0 a menos que `tiza_plena`")
    if min(sep["agrupa_px"], sep["masa_minima_px"], sep["umbral_oscuro"]) < 0:
        raise ErrorDePizarra(
            "`escena.pizarra.separa`: `agrupa_px`, `masa_minima_px` y `umbral_oscuro` no pueden ser negativos"
        )
    if not 0 <= bloque["texto"]["relleno_tras"] <= 1 or not 0 < bloque["grafica"]["hueco"] < 1:
        raise ErrorDePizarra("`texto.relleno_tras` va de 0 a 1 y `grafica.hueco` entre 0 y 1 (sin llegar)")
    if bloque["camara"]["zoom"] < 1:
        raise ErrorDePizarra("`escena.pizarra.camara.zoom` no baja de 1: con menos, el borde de la pizarra se ve")
    malos = [n for n, v in bloque["texto"]["tamanos"].items() if not (_es_numero(v) and v > 0)]
    if malos:
        raise ErrorDePizarra(f"`escena.pizarra.texto.tamanos`: {malos} no son tamaños en px")
    return {k: (dict(v) if isinstance(v, Mapping) else v) for k, v in bloque.items() if not str(k).startswith("_")}


def fuente(ajustes_: Mapping, css: str) -> Path:
    """La fuente de tiza del canal, en la biblioteca del estudio, que su CSS declara para que tenga procedencia.

    La tinta lee los contornos del fichero y la página no la pinta, pero la letra sale en el vídeo: su licencia tiene
    que estar en `assets.json`. La comprobación es la de la tinta (`tinta.fuente_de_la_biblioteca`), que comparte con
    los rótulos del formato «láminas» desde OC1.2.
    """
    try:
        return tinta.fuente_de_la_biblioteca(ajustes_["texto"]["fuente"], css)
    except tinta.ErrorDeTinta as e:
        raise ErrorDePizarra(str(e)) from e


# ------------------------------------------------------------------------------------------ la separación
def luminancia(rgb: np.ndarray) -> np.ndarray:
    """La luminancia de una imagen RGB (Rec. 601), en float32."""
    p = rgb.astype(np.float32)
    return p[..., 0] * 0.299 + p[..., 1] * 0.587 + p[..., 2] * 0.114


def _impar(n: float) -> int:
    k = max(1, int(round(n)))
    return k if k % 2 else k + 1


def fondo_limpio(rgb: np.ndarray, nucleo_px: float) -> np.ndarray:
    """La pizarra sin la tiza fina: apertura de núcleo `nucleo_px`, suavizada y nunca más clara que la imagen.

    La apertura (erosión y luego dilatación) borra lo claro más estrecho que el núcleo, que es el trazo de tiza, y deja
    lo ancho, que son los borrones. El suavizado quita los escalones del núcleo, y el mínimo con la imagen impide un
    fondo más claro que lo que se ve, que daría una tiza negativa.
    """
    n = _impar(nucleo_px)
    nucleo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (n, n))
    abierto = cv2.morphologyEx(np.ascontiguousarray(rgb, dtype=np.uint8), cv2.MORPH_OPEN, nucleo)
    suave = cv2.GaussianBlur(abierto.astype(np.float32), (0, 0), sigmaX=n / 6.0)
    return np.minimum(suave, rgb.astype(np.float32))


def separa_tiza(
    rgb: np.ndarray, *, nucleo_px: float, umbral: float, tiza_plena: float
) -> tuple[np.ndarray, np.ndarray]:
    """(la pizarra limpia en RGB, la tiza en RGBA), los dos en uint8 y del tamaño de `rgb`.

    La opacidad de la tiza es su exceso de luminosidad sobre la pizarra limpia entre `tiza_plena` (1 a partir de ahí),
    y 0 por debajo de `umbral`. Su color se despeja de la mezcla, así que la tiza sobre la pizarra limpia da la imagen.
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ErrorDePizarra(f"la pizarra tiene que ser RGB (alto × ancho × 3), no {rgb.shape}")
    p = rgb.astype(np.float32)
    b = fondo_limpio(rgb, nucleo_px)
    exceso = luminancia(p) - luminancia(b)
    alfa = np.clip(exceso / float(tiza_plena), 0.0, 1.0)
    alfa[exceso < umbral] = 0.0
    a = alfa[..., None]
    color = np.where(a > 0, b + (p - b) / np.maximum(a, 1e-6), 0.0)
    tiza = np.dstack([np.clip(color, 0, 255), alfa * 255.0])
    return np.round(b).astype(np.uint8), np.round(tiza).astype(np.uint8)


@dataclass(frozen=True)
class Pieza:
    """Una pieza de la pizarra: su número (orden de lectura), la caja de su tiza [x0, y0, x1, y1), sus px de tiza y su
    masa (la suma de su opacidad: los px de tiza opaca a los que equivale)."""

    numero: int
    caja: tuple[int, int, int, int]
    area_px: int
    masa_px: float


def _dentro_de(punto: tuple[float, float], caja: tuple[int, int, int, int]) -> bool:
    return caja[0] <= punto[0] < caja[2] and caja[1] <= punto[1] < caja[3]


def _union(cajas: Sequence[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    return (min(c[0] for c in cajas), min(c[1] for c in cajas), max(c[2] for c in cajas), max(c[3] for c in cajas))


def parte_en_piezas(alfa: np.ndarray, *, agrupa_px: float, masa_minima_px: float) -> tuple[list[Pieza], np.ndarray]:
    """Las piezas de una capa de tiza (opacidad 0-255) y el mapa de la REGIÓN de cada pieza (0: de ninguna).

    - La tiza se engorda `agrupa_px` para que los trazos de un mismo dibujo (las monedas de un montón, las patas de una
      hucha) formen una sola mancha. Cada mancha con al menos `masa_minima_px` de tiza opaca es una pieza.
    - Una mancha más floja cuyo centro cae en la caja de una pieza es un detalle del dibujo (el ojo de la hucha) y va
      con ella; si no, es resto (una mota, una raya de un borrón) y se queda en la pizarra desde el principio.
    - La región de una pieza es su mancha engordada con sus huecos rellenos: la cara de una moneda y también la tripa
      de la hucha, porque Qwen rellena algunos dibujos de un oscuro que no es el de la pizarra, y fuera de la región se
      vería como una sombra antes de que llegara la pieza.
    """
    tiza = alfa > 0
    regiones = np.zeros(alfa.shape, dtype=np.int32)
    if not tiza.any():
        return [], regiones
    engordada = tiza.astype(np.uint8)
    if agrupa_px > 0:
        k = _impar(2 * agrupa_px + 1)
        engordada = cv2.dilate(engordada, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, manchas = cv2.connectedComponents(engordada, connectivity=8)
    de_tiza = np.where(tiza, manchas, 0)
    areas = np.bincount(de_tiza.ravel(), minlength=n)
    masas = np.bincount(de_tiza.ravel(), weights=alfa.ravel().astype(np.float64) / 255.0, minlength=n)
    cajas = {
        i: (s[1].start, s[0].start, s[1].stop, s[0].stop)
        for i, s in enumerate(ndimage.find_objects(de_tiza), start=1)
        if s is not None
    }
    fuertes = [i for i in cajas if masas[i] >= masa_minima_px]
    grupos = {i: [i] for i in fuertes}
    for i, (x0, y0, x1, y1) in cajas.items():
        if i in grupos:
            continue
        centro = ((x0 + x1) / 2, (y0 + y1) / 2)
        candidatas = [j for j in fuertes if _dentro_de(centro, cajas[j])]
        if candidatas:
            j = min(candidatas, key=lambda c: (cajas[c][2] - cajas[c][0]) * (cajas[c][3] - cajas[c][1]))
            grupos[j].append(i)
    por_caja = {_union([cajas[i] for i in ids]): j for j, ids in grupos.items()}
    piezas = []
    for numero, caja in enumerate(recorte.orden_lectura(list(por_caja)), start=1):
        ids = grupos[por_caja[caja]]
        # La región se calcula en la caja de la tiza ensanchada lo que se engordó: la mancha engordada cabe entera.
        m = int(np.ceil(agrupa_px)) + 1
        ex0, ey0 = max(0, caja[0] - m), max(0, caja[1] - m)
        ex1, ey1 = min(alfa.shape[1], caja[2] + m), min(alfa.shape[0], caja[3] + m)
        propia = np.isin(manchas[ey0:ey1, ex0:ex1], ids)
        propia = ndimage.binary_fill_holes(propia)
        trozo = regiones[ey0:ey1, ex0:ex1]
        trozo[propia & (trozo == 0)] = numero
        piezas.append(
            Pieza(numero, tuple(int(v) for v in caja), int(areas[ids].sum()), round(float(masas[ids].sum()), 1))
        )
    return piezas, regiones


def _pizarra_debajo(fondo: np.ndarray, fuera: np.ndarray) -> np.ndarray:
    """La pizarra que hay debajo de los dibujos, rellenada desde la que se ve alrededor (empuja y tira, por pirámide).

    Se baja de resolución la pizarra a la vista con su peso hasta que no quedan huecos, y al subir cada nivel rellena
    solo lo que el más fino no ve: un hueco pequeño toma el tono de sus vecinos inmediatos y uno grande, la media de
    alrededor, sin escalones entre los dos. Fuera de los huecos devuelve la pizarra tal cual.
    """
    m = fuera.astype(np.float32)
    niveles = [(fondo.astype(np.float32) * m[..., None], m)]
    while niveles[-1][1].min() <= 1e-4 and min(niveles[-1][1].shape) > 2:
        valor, peso = niveles[-1]
        niveles.append((cv2.pyrDown(valor), cv2.pyrDown(peso)))
    valor, peso = niveles[-1]
    salida = valor / np.maximum(peso, 1e-6)[..., None]
    if (peso <= 1e-4).any():  # una pizarra sin nada a la vista: su media
        salida[peso <= 1e-4] = fondo[fuera].mean(axis=0) if fuera.any() else fondo.reshape(-1, 3).mean(axis=0)
    for valor, peso in reversed(niveles[:-1]):
        arriba = cv2.pyrUp(salida, dstsize=(peso.shape[1], peso.shape[0]))
        w = np.clip(peso, 0.0, 1.0)[..., None]
        salida = valor + (1 - w) * arriba
    return salida


def _grano(p: np.ndarray, ocupado: np.ndarray, dentro: np.ndarray) -> np.ndarray:
    """El grano de la pizarra para los px de `dentro`, copiado de pizarra a la vista (ni dibujo ni tiza: `ocupado`).

    El grano es lo que la imagen tiene de más que su versión desenfocada (`GRANO_SIGMA_PX`), hasta `GRANO_MAXIMO`.
    Cada px de dentro lo toma
    del primer desplazamiento de `GRANO_DESPLAZAMIENTOS` que cae en pizarra libre; si ninguno, se queda liso.
    """
    grano = np.clip(p - cv2.GaussianBlur(p, (0, 0), GRANO_SIGMA_PX), -GRANO_MAXIMO, GRANO_MAXIMO)
    libre = ~ocupado
    h, w = dentro.shape
    salida = np.zeros_like(p)
    hecho = ~dentro
    for fy, fx in GRANO_DESPLAZAMIENTOS:
        desplaza = (round(fy * h), round(fx * w))
        ok = np.roll(libre, desplaza, axis=(0, 1)) & ~hecho
        salida[ok] = np.roll(grano, desplaza, axis=(0, 1))[ok]
        hecho |= ok
    return salida


@dataclass(frozen=True)
class Separacion:
    """Lo que sale de separar una pizarra.

    - `limpia`: la pizarra sin las piezas (RGB): la imagen tal cual fuera de sus regiones, con la tiza del resto, y la
      pizarra estimada dentro. Es lo que se ve antes de que llegue ninguna.
    - `tiza`: la tiza y la tinta oscura de las piezas (RGBA), transparente fuera de ellas.
    - `piezas` y `mapa`: cada pieza y a qué pieza va cada px de `tiza` (0: a ninguna).
    - `resto_px`: los px de tiza que no son de ninguna pieza y se quedan en `limpia`.
    """

    limpia: np.ndarray
    tiza: np.ndarray
    piezas: list[Pieza]
    mapa: np.ndarray
    resto_px: int


def separa_pizarra(rgb: np.ndarray, *, nucleo_px: float, umbral: float, umbral_oscuro: float, tiza_plena: float,
                   agrupa_px: float, masa_minima_px: float) -> Separacion:  # fmt: skip
    """Separa una pizarra en su pizarra limpia y sus piezas: la limpia con las piezas encima vuelve a dar la imagen.

    1. La tiza clara sale de `separa_tiza` y se parte en piezas (`parte_en_piezas`).
    2. **Fuera de las regiones de las piezas, la pizarra limpia es la imagen tal cual**: su grano, sus borrones y la
       tiza que no es de ninguna pieza (el resto). La apertura solo sirve para encontrar la tiza.
    3. **Debajo de cada pieza la pizarra se estima desde la de alrededor** (`_pizarra_debajo`), con su grano copiado de
       otro sitio (`_grano`), y no desde la apertura: Qwen rellena algunos dibujos de un oscuro más oscuro que la
       pizarra (los huecos de un montón de monedas), y la apertura lo conservaría como pizarra, así que antes de que
       llegara la pieza se vería su sombra.
    4. **Dentro de su región, la pieza lleva también lo oscuro** (`umbral_oscuro`): la tinta que oscurece la pizarra
       entra con la pieza, con su opacidad hacia el negro. Lo claro, como en `separa_tiza`.
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ErrorDePizarra(f"la pizarra tiene que ser RGB (alto × ancho × 3), no {rgb.shape}")
    fondo, tiza0 = separa_tiza(rgb, nucleo_px=nucleo_px, umbral=umbral, tiza_plena=tiza_plena)
    piezas, regiones = parte_en_piezas(tiza0[..., 3], agrupa_px=agrupa_px, masa_minima_px=masa_minima_px)
    p = rgb.astype(np.float32)
    dentro = regiones > 0
    b = p.copy()
    if dentro.any():
        debajo = _pizarra_debajo(fondo.astype(np.float32), ~dentro)
        debajo += _grano(p, dentro | (tiza0[..., 3] > 0), dentro)
        suave = cv2.GaussianBlur(dentro.astype(np.float32), (0, 0), max(1.0, agrupa_px / 2))
        peso = np.maximum(suave, dentro.astype(np.float32))[..., None]
        b = p * (1 - peso) + debajo * peso
    lb = luminancia(b)
    delta = luminancia(p) - lb
    claro = np.where(delta >= umbral, np.clip(delta / float(tiza_plena), 0.0, 1.0), 0.0)
    oscuro = np.where(-delta >= umbral_oscuro, np.clip(-delta / np.maximum(lb, 1.0), 0.0, 1.0), 0.0)
    alfa = np.where(dentro, np.maximum(claro, oscuro), 0.0)
    a = alfa[..., None]
    color = np.where(a > 0, b + (p - b) / np.maximum(a, 1e-6), 0.0)
    tiza = np.round(np.dstack([np.clip(color, 0, 255), alfa * 255.0])).astype(np.uint8)
    tiza[tiza[..., 3] == 0] = 0
    return Separacion(
        limpia=np.clip(np.round(b), 0, 255).astype(np.uint8),
        tiza=tiza,
        piezas=piezas,
        mapa=np.where(tiza[..., 3] > 0, regiones, 0).astype(np.int32),
        resto_px=int(((tiza0[..., 3] > 0) & ~dentro).sum()),
    )


# Lo que `separa_pizarra` toma de `escena.pizarra.separa`.
CLAVES_DE_SEPARA = ("nucleo_px", "umbral", "umbral_oscuro", "tiza_plena", "agrupa_px", "masa_minima_px")


def separacion(nombre: str, ajustes_: Mapping) -> dict:
    """La operación que pide un episodio en `Lote.pizarras`: separar la pizarra `nombre` del catálogo (ya ampliada).

    Va detrás de las del obrero (`Lote.extra`), que es quien la amplía con `obrero.fondo`; la etapa `activos` la hace en
    el `.venv` del pipeline, sin GPU.
    """
    return {"op": "pizarra", "nombre": nombre, "separa": dict(ajustes_["separa"])}


def nombre_de_pieza(pizarra: str, numero: int) -> str:
    return f"{pizarra}_p{numero:02d}"


def _quita_lo_anterior(dir_activos: Path, nombre: str, catalogo: dict) -> None:
    """Lo que dejó una separación anterior de esta pizarra sale del catálogo, del disco y de la procedencia.

    Con otros ajustes salen otras piezas: una pieza vieja que se quedara tendría un número que ya no es el de la hoja.
    """
    viejas = [n for n, d in catalogo["imagenes"].items() if d.get("pizarra") == nombre]
    ficheros = []
    for n in viejas:
        ruta = obrero.archivo_de(dir_activos, catalogo["imagenes"].pop(n))
        ficheros.append(ruta.name)
        ruta.unlink(missing_ok=True)
    provenance.quita_registros(dir_activos / obrero.IMG / obrero.REGISTRO, ficheros)


def _registro(archivo: Path, origen: Path, op: Mapping, pieza: str, run_dir: Path) -> dict:
    return obrero.registro_derivado(
        archivo,
        origen,
        quien="la separación de la pizarra (lib/escena/pizarra.py, en el .venv del pipeline)",
        que_hace=(
            "tiza separada de la pizarra por su exceso de luminosidad sobre una pizarra limpia (apertura morfológica "
            "de OpenCV) y partida en piezas"
            if pieza != "limpia"
            else "pizarra limpia (apertura morfológica de OpenCV, que borra la tiza fina y conserva los borrones), con "
            "la tiza que no forma ninguna pieza"
        ),
        usadas=[{**obrero.MODELOS["opencv"], "nombre": "OpenCV (apertura morfológica)"}],
        detalle={"operacion": "pizarra", "pieza": pieza, "separa": dict(op["separa"])},
        ancla=run_dir,
    )


def hoja(limpia: np.ndarray, tiza: np.ndarray, piezas: Sequence[Pieza], destino: Path) -> Path:
    """La hoja numerada de una pizarra: la tiza de las piezas sobre la pizarra limpia, con la caja y el número de cada
    pieza, para que quien escribe la escena elija cuáles salen y cuándo. Va a `revision/` (es para mirar)."""
    alfa = tiza[..., 3:4].astype(np.float32) / 255.0
    base = limpia.astype(np.float32) * 0.55
    mezcla = base * (1 - alfa) + tiza[..., :3].astype(np.float32) * alfa
    im = Image.fromarray(np.clip(mezcla, 0, 255).astype(np.uint8), "RGB")
    k = ANCHO_DE_LA_HOJA / im.width
    im = im.resize((ANCHO_DE_LA_HOJA, round(im.height * k)), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    letra = ImageFont.load_default(size=26)
    for p in piezas:
        x0, y0, x1, y1 = (round(v * k) for v in p.caja)
        d.rectangle([x0, y0, x1, y1], outline=(255, 90, 160), width=2)
        etiqueta = str(p.numero)
        caja = d.textbbox((0, 0), etiqueta, font=letra)
        tw, th = caja[2] - caja[0] + 10, caja[3] - caja[1] + 8
        tx, ty = x0, max(0, y0 - th)
        d.rectangle([tx, ty, tx + tw, ty + th], fill=(255, 90, 160))
        d.text((tx + 5 - caja[0], ty + 4 - caja[1]), etiqueta, font=letra, fill=(20, 20, 20))
    destino.parent.mkdir(parents=True, exist_ok=True)
    im.save(destino, optimize=True)
    return destino


def separa(op: Mapping, dir_activos: str | Path, dir_revision: str | Path) -> dict:
    """Separa una pizarra del catálogo del episodio y apunta lo que sale. Devuelve su resumen.

    Escribe en `<activos>/img/` la pizarra limpia (`<nombre>_limpia.jpg`, con la tiza que no es pieza) y una imagen por
    pieza (`<nombre>_pNN.png`, con transparencia), cada una con su entrada en el catálogo (su `caja` en px de la
    pizarra y `pizarra: <nombre>`) y su registro de procedencia, derivado del de la pizarra ampliada. La hoja numerada
    va a `<revision>/pizarra-<nombre>.png`.
    """
    dir_activos, dir_revision = Path(dir_activos), Path(dir_revision)
    nombre, sep = op["nombre"], op["separa"]
    catalogo = obrero.lee_catalogo(dir_activos)
    if nombre not in catalogo["imagenes"]:
        raise ErrorDePizarra(
            f"la pizarra «{nombre}» no está en el catálogo del episodio: amplíala antes con `obrero.fondo` en "
            "`Lote.extra`"
        )
    entrada = catalogo["imagenes"][nombre]
    origen = obrero.archivo_de(dir_activos, entrada)
    _quita_lo_anterior(dir_activos, nombre, catalogo)
    with Image.open(origen) as im:
        rgb = np.asarray(im.convert("RGB"))
    s = separa_pizarra(rgb, **{k: sep[k] for k in CLAVES_DE_SEPARA})
    piezas, mapa, tiza = s.piezas, s.mapa, s.tiza
    run_dir = dir_activos.parent
    img = dir_activos / obrero.IMG
    comun = {k: entrada[k] for k in ("del_episodio",) if entrada.get(k)}
    registros = []
    archivo = img / f"{nombre}{SUFIJO_LIMPIA}.jpg"
    Image.fromarray(s.limpia, "RGB").save(archivo, quality=92)
    h, w = rgb.shape[:2]
    catalogo["imagenes"][f"{nombre}{SUFIJO_LIMPIA}"] = {
        "src": f"{obrero.SRC_DIR}/{archivo.name}", "w": w, "h": h, "ax": 0, "ay": 0, "ox": 0, "oy": 0,
        "de": nombre, "pizarra": nombre, "piezas": len(piezas), "resto_px": s.resto_px, **comun,
    }  # fmt: skip
    registros.append(_registro(archivo, origen, op, "limpia", run_dir))
    for p in piezas:
        x0, y0, x1, y1 = p.caja
        x0, y0 = max(0, x0 - MARGEN_PIEZA), max(0, y0 - MARGEN_PIEZA)
        x1, y1 = min(w, x1 + MARGEN_PIEZA), min(h, y1 + MARGEN_PIEZA)
        trozo = tiza[y0:y1, x0:x1].copy()
        trozo[..., 3] = np.where(mapa[y0:y1, x0:x1] == p.numero, trozo[..., 3], 0)
        archivo = img / f"{nombre_de_pieza(nombre, p.numero)}.png"
        Image.fromarray(trozo, "RGBA").save(archivo, optimize=True)
        catalogo["imagenes"][nombre_de_pieza(nombre, p.numero)] = {
            "src": f"{obrero.SRC_DIR}/{archivo.name}", "w": x1 - x0, "h": y1 - y0, "ax": 0, "ay": 0, "ox": 0, "oy": 0,
            "de": nombre, "pizarra": nombre, "numero": p.numero, "caja": [x0, y0, x1, y1], "area_px": p.area_px,
            "masa_px": p.masa_px,
            **comun,
        }  # fmt: skip
        registros.append(_registro(archivo, origen, op, f"p{p.numero:02d}", run_dir))
    provenance.anade_registros(img / obrero.REGISTRO, registros)
    obrero.guarda_catalogo(dir_activos, catalogo)
    destino = hoja(s.limpia, tiza, piezas, dir_revision / f"pizarra-{nombre}.png")
    return {
        "nombre": nombre,
        "piezas": len(piezas),
        "tiza_px": int((tiza[..., 3] > 0).sum()),
        "resto_px": s.resto_px,
        "hoja": destino,
    }


def separa_lote(operaciones: Sequence[Mapping], dir_activos: str | Path, dir_revision: str | Path) -> list[dict]:
    """Separa en serie las pizarras que pide el episodio (`Lote.pizarras`). Para con la primera que no se puede."""
    malas = [op for op in operaciones if op.get("op") != "pizarra"]
    if malas:
        raise ErrorDePizarra(f"`Lote.pizarras` lleva operaciones que no son de pizarra: {malas}")
    return [separa(op, dir_activos, dir_revision) for op in operaciones]


# ------------------------------------------------------------------------------------------ la gráfica
def barras(valores: Sequence[float], alto_max: float) -> list[float]:
    """El alto de cada barra: la mayor mide `alto_max` y cada una lo que su valor, en proporción. Sin valores negativos.

    Es lo que hace que una barra diga lo mismo que su cifra: con el doble de valor mide el doble.
    """
    if not valores:
        raise ErrorDePizarra("una gráfica sin valores no tiene barras")
    if any(not _es_numero(v) or v < 0 for v in valores):
        raise ErrorDePizarra(f"los valores de una gráfica de barras son números ≥ 0: {list(valores)}")
    mayor = max(valores)
    if mayor <= 0 or alto_max <= 0:
        raise ErrorDePizarra("la gráfica necesita algún valor mayor que 0 y un alto positivo")
    return [alto_max * v / mayor for v in valores]


def _rayado(w: float, h: float, paso: float) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Las rayas a 45° que rellenan un rectángulo de w × h, cada `paso` px, recortadas a sus lados."""
    rayas = []
    c = paso
    while c < w + h:
        # La recta x + y = c, dentro del rectángulo [0, w] × [0, h].
        a = (max(0.0, c - h), min(h, c))
        b = (min(w, c), max(0.0, c - w))
        if a != b:
            rayas.append((a, b))
        c += paso
    return rayas


def _n(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


# ------------------------------------------------------------------------------------------ la puesta en escena
@dataclass(frozen=True)
class Bloque:
    """Lo que ocupa un texto escrito con `Pizarra.texto`, con sus líneas ya partidas.

    `ancho` y `alto` van en px de la pizarra: el alto va de lo más alto de la primera línea a lo más bajo de la última,
    que es lo que `texto` pinta debajo de su `y`. `escribe_s` es lo que tarda en quedar escrito desde que empieza.
    """

    ancho: float
    alto: float
    lineas: int
    escribe_s: float


@dataclass(eq=False)
class _Cosa:
    """Algo puesto en la pizarra: qué es, quién es (para el mensaje), cuándo empieza, cuándo acaba de escribirse (un
    texto) y, si se borra, cuándo acaba de borrarse."""

    que: str  # «pieza», «flecha», «gráfica» o «texto»
    quien: str
    t: float
    hasta: float | None = None
    escrito: float | None = None


@dataclass(eq=False)
class _Reserva:
    """Una ventana [t0, t1) en la que la pizarra es de un solo texto (su dueño) y no hay nada más en ella."""

    t0: float
    t1: float
    dueno: _Cosa | None = None


class Pizarra:
    """Una pizarra del episodio en el guion: su plano, sus piezas, sus textos, su flecha y su gráfica.

    - `nombre`: la pizarra en el catálogo del episodio (la que separó `separa`): su set es `<nombre>_limpia` y sus
      piezas, `<nombre>_pNN`.
    - `ajustes_`: `ajustes(perfil["escena"])`; `fuente_`: `fuente(ajustes_, css)`.
    - Las medidas van en px de la pizarra ampliada. Los instantes los da el guion con las anclas a la narración.

    **Cada pieza de la hoja tiene un destino**: entra en su instante (`pieza`) o está desde el principio (`abre(...,
    de_entrada=...)`). `comprueba()` para si alguna se quedó sin ninguno, porque una pieza olvidada no sale nunca y la
    pizarra perdería ese trozo de tiza sin que nadie lo viera.

    **Una reserva deja la pizarra a un solo texto** (`reserva`, F7.10, fila 264): el título del episodio, que se escribe
    en el centro de la pizarra vacía y se borra. Durante la reserva no empieza nada más, y una pieza, una flecha o una
    gráfica que ya estuviera para, porque ninguna se borra. Un texto escrito antes sí vale (el nombre del canal), si ya
    ha acabado de escribirse cuando la reserva empieza.
    """

    def __init__(self, g: Guion, nombre: str, ajustes_: Mapping, fuente_: Path) -> None:
        self.g, self.nombre, self.a, self.fuente = g, nombre, ajustes_, Path(fuente_)
        self.set = f"{nombre}{SUFIJO_LIMPIA}"
        if self.set not in g.fondos:
            g.fondo(self.set, img=self.set, suelo=None)
        im = g.imagen(self.set)
        self.w, self.h = float(im["w"]), float(im["h"])
        self.p: Plano | None = None
        self._zoom = float(ajustes_["camara"]["zoom"])
        self._centro = (self.w / 2, self.h / 2)
        self._puestas: set[int] = set()
        self._cosas: list[_Cosa] = []
        self._reservas: list[_Reserva] = []

    @property
    def borra_s(self) -> float:
        """Lo que tarda el borrador en pasar por un texto que se borra (`escena.pizarra.texto.borra_s`)."""
        return float(self.a["texto"]["borra_s"])

    # ---------------------------------------------------------- la reserva
    def reserva(self, t0: float, t1: float) -> None:
        """De t0 a t1 la pizarra es de un solo texto, el que se escribe con `texto(..., reservado=True)`, y está vacía.

        Para si en la ventana empieza una pieza, una flecha, una gráfica u otro texto; si una pieza, una flecha o una
        gráfica ya está en la pizarra en t0 (también las de `abre(..., de_entrada=...)`), porque no se borran; o si un
        texto empezado antes todavía se está escribiendo en t0. Vale en los dos órdenes: lo que ya está puesto se
        comprueba aquí y lo que se ponga después, al ponerlo.
        """
        p = self._plano()
        if not t1 > t0:
            raise ErrorDePizarra(
                f"la reserva de la pizarra «{self.nombre}» acaba ({t1:.2f} s) antes de empezar ({t0:.2f} s)"
            )
        if t0 < p.t0 - EPS or t1 > p.t1 + EPS:
            raise ErrorDePizarra(
                f"la reserva [{t0:.2f}, {t1:.2f}] s se sale de la pizarra «{self.nombre}» ([{p.t0:.2f}, {p.t1:.2f}] s)"
            )
        for r in self._reservas:
            if t0 < r.t1 - EPS and r.t0 < t1 - EPS:
                raise ErrorDePizarra(
                    f"la reserva [{t0:.2f}, {t1:.2f}] s se solapa con otra de la pizarra «{self.nombre}» "
                    f"([{r.t0:.2f}, {r.t1:.2f}] s)"
                )
        nueva = _Reserva(t0, t1)
        for c in self._cosas:
            self._choca(nueva, c)
        self._reservas.append(nueva)

    def _choca(self, r: _Reserva, c: _Cosa) -> None:
        if c is r.dueno:
            return
        ventana = f"la reserva [{r.t0:.2f}, {r.t1:.2f}] s de la pizarra «{self.nombre}»"
        if c.que == "texto":
            if r.t0 - EPS <= c.t < r.t1 - EPS:
                raise ErrorDePizarra(f"el texto «{c.quien}» se escribe en {c.t:.2f} s, dentro de {ventana}")
            if c.t < r.t0 and c.escrito is not None and c.escrito > r.t0 + EPS:
                raise ErrorDePizarra(
                    f"el texto «{c.quien}» empieza en {c.t:.2f} s y no acaba de escribirse hasta {c.escrito:.2f} s, "
                    f"después de que empiece {ventana}"
                )
        elif c.t <= r.t0 + EPS:
            raise ErrorDePizarra(
                f"{c.que} {c.quien} ya está en la pizarra ({c.t:.2f} s) cuando empieza {ventana}, y no se borra"
            )
        elif c.t < r.t1 - EPS:
            raise ErrorDePizarra(f"{c.que} {c.quien} entra en {c.t:.2f} s, dentro de {ventana}")

    def _anota(self, que: str, quien: str, t: float, *, hasta: float | None = None, escrito: float | None = None,
               reservado: bool = False) -> None:  # fmt: skip
        """Apunta lo que se pone en la pizarra y para si choca con una reserva. `reservado`: es el texto de una."""
        c = _Cosa(que, quien, t, hasta, escrito)
        if reservado:
            fin = math.inf if hasta is None else hasta
            suya = [r for r in self._reservas if r.t0 - EPS <= t and fin <= r.t1 + EPS]
            if not suya:
                raise ErrorDePizarra(
                    f"el texto «{quien}» va en una reserva y ninguna de la pizarra «{self.nombre}» lo contiene entero "
                    f"(de {t:.2f} s a {fin:.2f} s): llama antes a reserva()"
                )
            if suya[0].dueno is not None:
                raise ErrorDePizarra(
                    f"la reserva [{suya[0].t0:.2f}, {suya[0].t1:.2f}] s de la pizarra «{self.nombre}» ya es del texto "
                    f"«{suya[0].dueno.quien}»"
                )
            suya[0].dueno = c
        for r in self._reservas:
            self._choca(r, c)
        self._cosas.append(c)

    # ---------------------------------------------------------- el plano y la cámara
    def abre(self, t0: float, t1: float, *, cambio_de_tema: bool, de_entrada: Sequence[int]) -> Plano:
        """El plano de la pizarra en [t0, t1]: corte seco o, si cambia de tema, el fundido corto. Cámara fija.

        `de_entrada`: las piezas de la hoja que ya están en la pizarra cuando se abre ([] para ninguna).
        """
        if self.p is not None:
            raise ErrorDePizarra(f"la pizarra «{self.nombre}» ya tiene su plano")
        if cambio_de_tema:
            self.p = self.g.plano(self.set, t0, t1, entra="funde", d=self.a["transicion"]["cambio_de_tema_s"])
        else:
            self.p = self.g.plano(self.set, t0, t1)
        self.p.cam(t0, *self._centro, self._zoom, tr=0)
        if de_entrada:
            self.pieza(list(de_entrada), t0, funde=False)
        return self.p

    def piezas_de_la_hoja(self) -> list[int]:
        """Los números de las piezas que `separa` sacó de esta pizarra (las de su hoja)."""
        return sorted(
            int(d["numero"]) for d in self.g.catalogo.values() if d.get("pizarra") == self.nombre and "numero" in d
        )

    def comprueba(self) -> None:
        """Para si alguna pieza de la hoja no tiene destino: ni entra en un instante ni está desde el principio."""
        sin_destino = sorted(set(self.piezas_de_la_hoja()) - self._puestas)
        if sin_destino:
            raise ErrorDePizarra(
                f"la pizarra «{self.nombre}» tiene piezas sin destino: {sin_destino}. Cada una entra con pieza() o "
                "va en abre(..., de_entrada=[...]); si no, no sale nunca"
            )

    def _plano(self) -> Plano:
        if self.p is None:
            raise ErrorDePizarra(f"la pizarra «{self.nombre}» no tiene plano: llama antes a abre()")
        return self.p

    def _fin(self) -> float:
        # Lo que está en la pizarra se queda hasta que el plano se va, también bajo el fundido a la siguiente.
        return self._plano().t1 + self.a["transicion"]["cambio_de_tema_s"]

    def acerca(self, t: float, hacia: tuple[float, float]) -> None:
        """El acercamiento lento de una pizarra densa desde t, hacia `hacia`, sin enseñar el borde de la pizarra."""
        p = self._plano()
        zoom = self._zoom * (1 + self.a["camara"]["acercamiento"])
        marco = self.g.escena["marco"]
        medio_w = self.w / zoom / 2
        medio_h = medio_w * marco["h"] / marco["w"]
        cx = min(max(hacia[0], medio_w), self.w - medio_w)
        cy = min(max(hacia[1], medio_h), self.h - medio_h)
        p.cam(t, *self._centro, self._zoom, tr=0)
        p.cam(t + 0.01, cx, cy, zoom, tr=self.a["camara"]["acercamiento_s"], e="suave")
        self._zoom, self._centro = zoom, (cx, cy)

    # ---------------------------------------------------------- las piezas
    def pieza(self, numeros: int | Sequence[int], t: float, *, funde: bool) -> list[Elemento]:
        """Las piezas `numeros` de la hoja aparecen en t, de golpe o con el fundido corto, en su sitio."""
        p = self._plano()
        salida = []
        for n in [numeros] if isinstance(numeros, int) else list(numeros):
            d = self.g.imagen(nombre_de_pieza(self.nombre, n))
            if d.get("pizarra") != self.nombre or "caja" not in d:
                raise ErrorDePizarra(f"«{nombre_de_pieza(self.nombre, n)}» no es una pieza de la pizarra {self.nombre}")
            if n in self._puestas:
                raise ErrorDePizarra(f"la pieza {n} de la pizarra {self.nombre} ya tiene su destino")
            self._anota("la pieza", str(n), t)
            self._puestas.add(n)
            x0, y0, x1, y1 = d["caja"]
            anim = {"entra": "fade", "di": self.a["pieza"]["funde_s"]} if funde else {"entra": "nada"}
            contenido = f'<img class="pieza" src="{html.escape(d["src"], quote=True)}" alt="">'
            salida.append(
                self.g.el(
                    p.id,
                    contenido,
                    (x0 + x1) / 2,
                    (y0 + y1) / 2,
                    x1 - x0,
                    y1 - y0,
                    t,
                    self._fin(),
                    clase="pieza",
                    sale="nada",
                    z=1,
                    **anim,
                )  # fmt: skip
            )
        return salida

    # ---------------------------------------------------------- el texto, trazo a trazo
    def _lineas(self, texto: str, tam: float, ancho_max: float | None) -> list[tinta.Linea]:
        esp = self.a["texto"]["espaciado"] * tam
        if ancho_max is None:
            return [tinta.compone_linea(texto, self.fuente, tam, espaciado_px=esp, versalitas=False)]
        return tinta.parte_en_lineas(texto, ancho_max, self.fuente, tam, espaciado_px=esp, versalitas=False)

    def _px(self, tam: str) -> float:
        tamanos = self.a["texto"]["tamanos"]
        if tam not in tamanos:
            raise ErrorDePizarra(f"el tamaño «{tam}» no está en `escena.pizarra.texto.tamanos` ({', '.join(tamanos)})")
        return float(tamanos[tam])

    def _escribe_s(self, letras: int) -> float:
        """Lo que tarda en quedar escrito un texto de `letras` letras, desde que empieza la primera."""
        at = self.a["texto"]
        fin = 0.0
        for i in range(letras):
            ti = i * at["paso_s"]
            fin = max(fin, ti + at["letra_s"], ti + at["relleno_tras"] * at["letra_s"] + at["relleno_s"])
        return fin

    def mide(self, texto: str, *, tam: str, ancho_max: float | None = None) -> Bloque:
        """Lo que ocupa `texto` escrito con `texto(...)` con ese tamaño y ese ancho máximo, y lo que tarda en
        escribirse.

        Sirve para colocar un bloque antes de escribirlo: centrarlo en vertical, o comprobar que cabe en sus líneas.
        """
        px = self._px(tam)
        lineas = self._lineas(texto, px, ancho_max)
        if not lineas:
            return Bloque(0.0, 0.0, 0, 0.0)
        ultima = lineas[-1]
        alto = (len(lineas) - 1) * self.a["texto"]["interlineado"] * px + ultima.ascenso + ultima.descenso
        letras = sum(len(linea.letras) for linea in lineas)
        return Bloque(max(linea.ancho for linea in lineas), alto, len(lineas), self._escribe_s(letras))

    def texto(self, texto: str, x: float, y: float, t: float, *, tam: str, clase: str, alinea: str,
              ancho_max: float | None = None, borra: float | None = None,
              reservado: bool = False) -> float:  # fmt: skip
        """Escribe `texto` desde t, letra a letra: el trazo recorre el contorno de cada letra y la letra se rellena.

        (x, y) es la esquina de arriba del bloque: la izquierda con `alinea="izquierda"` y el centro con «centro».
        `tam` es un nombre de `texto.tamanos` y `clase` la del CSS del canal (su color). Con `ancho_max`, el texto se
        parte en líneas de ese ancho como mucho. Devuelve cuándo acaba de escribirse.

        - `borra`: el instante en que el borrador empieza a pasar por el texto, que se va de izquierda a derecha en
          `texto.borra_s`. Sin él, el texto se queda hasta que la pizarra se va. Para si se borraría antes de quedar
          escrito, o después de que la pizarra se vaya.
        - `reservado`: el texto es el de una reserva (`reserva`), y tiene que caber entero en ella, borrado incluido.
        """
        if alinea not in ("izquierda", "centro"):
            raise ErrorDePizarra(f"`alinea` es «izquierda» o «centro», no {alinea!r}")
        px = self._px(tam)
        p, at = self._plano(), self.a["texto"]
        lineas = self._lineas(texto, px, ancho_max)
        fin = t + self._escribe_s(sum(len(linea.letras) for linea in lineas))
        if borra is None:
            if reservado:
                raise ErrorDePizarra(f"el texto «{texto}» es el de una reserva y no se borra: le falta `borra`")
            t1, salida = self._fin(), {"sale": "nada"}
        else:
            if borra < fin - EPS:
                raise ErrorDePizarra(
                    f"el texto «{texto}» se borraría en {borra:.2f} s y no acaba de escribirse hasta {fin:.2f} s"
                )
            t1, salida = borra + self.borra_s, {"sale": "borra", "ds": self.borra_s}
            if t1 > p.t1 + EPS:
                raise ErrorDePizarra(
                    f"el texto «{texto}» acabaría de borrarse en {t1:.2f} s y la pizarra «{self.nombre}» se va en "
                    f"{p.t1:.2f} s"
                )
        self._anota("texto", texto, t, hasta=None if borra is None else t1, escrito=fin, reservado=reservado)
        alto_linea = at["interlineado"] * px
        margen = 0.25 * px
        # Cada letra lleva la caja del bloque entero (lo ancho de su línea más ancha): así el borrador, que barre por
        # porcentaje de la caja, tiene un solo frente en todas las líneas. Centrada, cada línea va en medio de su caja.
        ancho = max((linea.ancho for linea in lineas), default=0.0)
        w = ancho + 2 * margen
        izquierda = x if alinea == "izquierda" else x - ancho / 2
        cx = izquierda - margen + w / 2
        i = 0
        for k, linea in enumerate(lineas):
            hl = linea.ascenso + linea.descenso + 2 * margen
            cy = y + k * alto_linea - margen + hl / 2
            dentro = 0.0 if alinea == "izquierda" else (ancho - linea.ancho) / 2
            origen = (margen + dentro, margen + linea.ascenso)
            for letra in linea.letras:
                ti = t + i * at["paso_s"]
                relleno = ti + at["relleno_tras"] * at["letra_s"]
                self.g.el(p.id, tinta.relleno_svg(letra, (w, hl), origen, f"tinta {clase}"), cx, cy, w, hl, relleno,
                          t1, entra="fade", di=at["relleno_s"], z=3, **salida)  # fmt: skip
                self.g.el(p.id, tinta.trazo_svg(letra, (w, hl), origen, f"tinta {clase}"), cx, cy, w, hl, ti, t1,
                          entra="nada", trazo=True, trazo_t=0, trazo_d=at["letra_s"], z=4, **salida)  # fmt: skip
                i += 1
        return fin

    # ---------------------------------------------------------- la flecha que fluye
    def flecha(self, puntos: Sequence[tuple[float, float]], t: float, *, clase: str) -> Elemento:
        """Una flecha de guiones que fluyen de su primer punto al último (dos puntos: recta; tres: curva), con punta.

        Entra con el fundido corto de las piezas y sus guiones corren `flecha.velocidad_px_s` mientras está (el bucle
        `fluye` del motor). El dibujo de los guiones lo pone el CSS del canal (`.<clase> .fluye { stroke-dasharray }`).
        """
        if len(puntos) not in (2, 3):
            raise ErrorDePizarra(
                f"una flecha va de un punto a otro, recta (2 puntos) o curva (3), no con {len(puntos)}"
            )
        p = self._plano()
        self._anota("la flecha", f"de {tuple(puntos[0])} a {tuple(puntos[-1])}", t)
        largo = self.a["flecha"]["punta_px"]
        margen = largo + 20
        xs, ys = [q[0] for q in puntos], [q[1] for q in puntos]
        x0, y0 = min(xs) - margen, min(ys) - margen
        w, h = max(xs) + margen - x0, max(ys) + margen - y0
        rel = [(q[0] - x0, q[1] - y0) for q in puntos]
        if len(rel) == 2:
            d = f"M{_n(rel[0][0])} {_n(rel[0][1])}L{_n(rel[1][0])} {_n(rel[1][1])}"
            dx, dy = rel[1][0] - rel[0][0], rel[1][1] - rel[0][1]
        else:
            d = f"M{_n(rel[0][0])} {_n(rel[0][1])}Q{_n(rel[1][0])} {_n(rel[1][1])} {_n(rel[2][0])} {_n(rel[2][1])}"
            dx, dy = rel[2][0] - rel[1][0], rel[2][1] - rel[1][1]
        angulo = math.atan2(dy, dx)
        fx, fy = rel[-1]
        alas = [
            (fx - largo * math.cos(angulo + s * math.radians(28)), fy - largo * math.sin(angulo + s * math.radians(28)))
            for s in (-1, 1)
        ]
        punta = f"M{_n(alas[0][0])} {_n(alas[0][1])}L{_n(fx)} {_n(fy)}L{_n(alas[1][0])} {_n(alas[1][1])}"
        svg = (
            f'<svg class="flecha {clase}" viewBox="0 0 {_n(w)} {_n(h)}" width="{_n(w)}" height="{_n(h)}" '
            f'xmlns="http://www.w3.org/2000/svg"><path class="fluye" d="{d}"/><path class="punta" d="{punta}"/></svg>'
        )
        return self.g.el(p.id, svg, x0 + w / 2, y0 + h / 2, w, h, t, self._fin(), entra="fade",
                         di=self.a["pieza"]["funde_s"], sale="nada", fluye=self.a["flecha"]["velocidad_px_s"],
                         z=2)  # fmt: skip

    # ---------------------------------------------------------- la gráfica de barras
    def grafica(self, valores: Sequence[float], *, caja: tuple[float, float, float, float], tiempos: Sequence[float],
                cifras: Sequence[str], etiquetas: Sequence[str], clase: str, clase_cifra: str,
                tam_cifra: str, tam_etiqueta: str) -> list[float]:  # fmt: skip
        """Una gráfica de barras desde sus datos: la raya de la base, y cada barra en su instante con su cifra encima y
        su etiqueta debajo, escritas a tinta.

        `caja` (x0, y0, x1, y1) es el sitio de las barras en la pizarra: la base va en y1 y la barra mayor llega a y0.
        `tiempos[i]` es cuándo se dibuja la barra i (la base, con la primera). Devuelve el alto de cada barra.
        """
        n = len(valores)
        if not (len(tiempos) == len(cifras) == len(etiquetas) == n):
            raise ErrorDePizarra("una gráfica lleva un instante, una cifra y una etiqueta por valor")
        if any(b < a for a, b in zip(tiempos, tiempos[1:])):
            raise ErrorDePizarra(f"las barras se dibujan en orden: {list(tiempos)}")
        x0, y0, x1, y1 = caja
        if not (x1 > x0 and y1 > y0):
            raise ErrorDePizarra(f"la caja de la gráfica no tiene área: {caja}")
        p, ag = self._plano(), self.a["grafica"]
        altos = barras(valores, y1 - y0)
        self._anota("la gráfica", f"de {list(cifras)}", tiempos[0])
        columna = (x1 - x0) / n
        ancho = columna * (1 - ag["hueco"])
        ancho_svg = x1 - x0 + 40
        base = tinta.raya_svg([((20, 20), (ancho_svg - 20, 20))], (ancho_svg, 40), f"tinta raya {clase}")
        self.g.el(p.id, base, (x0 + x1) / 2, y1, ancho_svg, 40, tiempos[0], self._fin(), entra="nada", sale="nada",
                  trazo=True, trazo_t=0, trazo_d=ag["trazo_s"], z=2)  # fmt: skip
        tam_c = self._px(tam_cifra)
        for i, (alto, t) in enumerate(zip(altos, tiempos)):
            bx = x0 + i * columna + (columna - ancho) / 2
            m = 6
            rect = f"M{m} {_n(alto + m)}V{m}H{_n(ancho + m)}V{_n(alto + m)}"
            rayas = "".join(
                f'<path class="raya" d="M{_n(a[0] + m)} {_n(a[1] + m)}L{_n(b[0] + m)} {_n(b[1] + m)}"/>'
                for a, b in _rayado(ancho, alto, ag["rayado_px"])
            )
            caja_svg = (ancho + 2 * m, alto + 2 * m)
            contorno = (
                f'<svg class="barra {clase}" viewBox="0 0 {_n(caja_svg[0])} {_n(caja_svg[1])}" '
                f'width="{_n(caja_svg[0])}" height="{_n(caja_svg[1])}" xmlns="http://www.w3.org/2000/svg">'
                f'<path class="trazo" pathLength="{tinta.LARGO_DEL_TRAZO}" d="{rect}"/></svg>'
            )
            relleno = (
                f'<svg class="barra {clase}" viewBox="0 0 {_n(caja_svg[0])} {_n(caja_svg[1])}" '
                f'width="{_n(caja_svg[0])}" height="{_n(caja_svg[1])}" xmlns="http://www.w3.org/2000/svg">{rayas}</svg>'
            )
            cx, cy = bx + ancho / 2, y1 - alto / 2
            self.g.el(p.id, contorno, cx, cy, caja_svg[0], caja_svg[1], t, self._fin(), entra="nada", sale="nada",
                      trazo=True, trazo_t=0, trazo_d=ag["trazo_s"], z=2)  # fmt: skip
            self.g.el(p.id, relleno, cx, cy, caja_svg[0], caja_svg[1], t + ag["trazo_s"] * 0.6, self._fin(),
                      entra="fade", di=self.a["pieza"]["funde_s"], sale="nada", z=1)  # fmt: skip
            self.texto(cifras[i], cx, y1 - alto - 1.35 * tam_c, t + ag["trazo_s"] * 0.5, tam=tam_cifra,
                       clase=clase_cifra, alinea="centro")  # fmt: skip
            self.texto(etiquetas[i], cx, y1 + 30, t, tam=tam_etiqueta, clase=clase, alinea="centro")
        return altos
