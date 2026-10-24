"""Los campos de gris de las entradas de tinta por umbral (F6.8): `mancha`, `calado` y `viento`.

Vienen de las transiciones del motor de láminas (`lib/motion.py → TRANSITIONS`, retirado en F6.7), que allí hacía
el `xfade` de FFmpeg. Este módulo es ya su única copia.
En el motor de escena, un plano que entra con una de ellas se recorta con una máscara SVG:

    alfa = clamp(pendiente · F + corte, 0, 1)

- F ∈ [0, 1] es el gris de un campo fijo, el que dibuja este módulo;
- {pendiente, corte} los calcula `motor/motor.js → entradaPlano` en cada fotograma, con el progreso lineal de la
  entrada, y el director los escribe en el `feFuncA` de la máscara del plano.

`compone.py` escribe cada campo en la composición (`assets/estudio/campo-<nombre>.png`) solo si algún plano lo usa,
como hace con GSAP. Son del estudio, no de un canal: la forma de cada transición, no un estilo. Y son deterministas
(numpy con semilla fija): el mismo campo sale idéntico byte a byte en cada composición, así que no mueve su huella.

Los campos:

- **mancha** (`ink_blot`): el campo de senos del motor de láminas (su `_INK_BLOT_FIELD`), con x, y normalizados;
- **calado** (`ink_bleed`, el `dissolve` de xfade): ruido uniforme, un umbral distinto por píxel;
- **viento** (`ink_streak_right` y `_left`, el `hrwind` y el `hlwind` de xfade): 0,8 · fx + 0,2 · r(y), con fx la
  coordenada en la dirección del avance (0 donde empieza) y r(y) un ruido por FILA, constante a lo largo de x: cada
  fila llega un poco antes o después, como una racha.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

# El tamaño de los campos. El navegador los estira al marco del GUION (`preserveAspectRatio="none"`), así que valen
# para cualquier marco 16:9; a 1920 × 1080 cada punto del campo cubre 2 × 2 píxeles.
ANCHO, ALTO = 960, 540
# Dónde van dentro de la composición. Es del estudio, como el sitio de GSAP: un asset del canal no puede usarlo.
CARPETA = "assets/estudio"
# Las semillas del ruido: fijas, para que el campo sea el mismo en cada composición.
SEMILLA_CALADO = 6808
SEMILLA_VIENTO = 6809
# El peso del ruido por fila en el viento (el resto, 0,8, es la coordenada del avance).
PESO_FILA_VIENTO = 0.2


def _coordenadas() -> tuple[np.ndarray, np.ndarray]:
    """x, y normalizados en el centro de cada punto del campo, como matrices (ALTO, ANCHO)."""
    x = (np.arange(ANCHO) + 0.5) / ANCHO
    y = (np.arange(ALTO) + 0.5) / ALTO
    return np.meshgrid(x, y)


def _mancha() -> np.ndarray:
    x, y = _coordenadas()
    suma = 0.45 * np.sin(x * 33) * np.sin(y * 25) + 0.30 * np.sin(x * 79 + 1.7) * np.sin(y * 54 + 0.4)
    return (suma + 0.25 * np.sin((x + y) * 19) + 1) / 2


def _calado() -> np.ndarray:
    return np.random.default_rng(SEMILLA_CALADO).random((ALTO, ANCHO))


def _viento(hacia: str) -> np.ndarray:
    x, _ = _coordenadas()
    fx = x if hacia == "derecha" else 1 - x
    fila = np.random.default_rng(SEMILLA_VIENTO).random((ALTO, 1))
    return (1 - PESO_FILA_VIENTO) * fx + PESO_FILA_VIENTO * fila


# Cada campo, por su nombre. El de viento depende de hacia dónde avanza el frente.
CAMPOS = {
    "mancha": _mancha,
    "calado": _calado,
    "viento-derecha": lambda: _viento("derecha"),
    "viento-izquierda": lambda: _viento("izquierda"),
}


def nombre(entra: dict | None) -> str | None:
    """El campo que usa un plano que entra con `entra` ({tipo, d, dir}), o None si su entrada no va por umbral."""
    tipo = (entra or {}).get("tipo")
    if tipo in ("mancha", "calado"):
        return tipo
    if tipo == "viento":
        return f"viento-{entra.get('dir')}"
    return None


def ruta(campo: str) -> str:
    """Dónde va el campo dentro de la composición (una ruta relativa, como las de `assets`)."""
    return f"{CARPETA}/campo-{campo}.png"


def gris(campo: str) -> np.ndarray:
    """El campo en gris de 8 bits, (ALTO, ANCHO): F · 255 redondeado."""
    if campo not in CAMPOS:
        raise KeyError(f"no hay un campo «{campo}» ({', '.join(CAMPOS)})")
    return np.clip(np.rint(CAMPOS[campo]() * 255), 0, 255).astype(np.uint8)


def escribe(campo: str, destino: str | Path) -> Path:
    """Escribe el PNG del campo en `destino` y devuelve su ruta."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(gris(campo)).save(destino, format="PNG")
    return destino
