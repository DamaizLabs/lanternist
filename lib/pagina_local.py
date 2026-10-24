"""Abrir una página local en el navegador: la regla de que lo que genera el estudio se abre solo.

Vivía en `lib/descubrimiento/dashboard.py` y `canal.py` la importaba de allí; al retirarse ese panel
(F5.12) pasa a un sitio neutro, porque abrir una página no es cosa del descubrimiento.
"""

from __future__ import annotations

import os
from pathlib import Path


def abre(ruta: Path) -> bool:
    """Abre `ruta` en el navegador por defecto. Solo Windows, que es el equipo del proyecto."""
    if os.name != "nt":
        return False
    try:
        os.startfile(ruta)  # noqa: S606 - es exactamente lo que se pidió: «que se abra automáticamente»
        return True
    except OSError:
        return False


def imagen_embebida(ruta: Path, ancho: int = 640, calidad: int = 78) -> str:
    """La imagen como `data:` JPEG reducida a `ancho`: la página no depende de que el fichero siga ahí.

    La usan la página del descubrimiento y la rejilla de la marca (`scripts/rejilla_de_marca.py`).
    """
    import base64
    import io

    from PIL import Image

    with Image.open(ruta) as im:
        im = im.convert("RGB")
        im.thumbnail((ancho, ancho))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=calidad)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
