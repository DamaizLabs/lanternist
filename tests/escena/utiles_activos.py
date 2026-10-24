"""Imágenes sintéticas para las pruebas de los activos del motor de escena (F6.2c).

Se dibujan aquí, pequeñas, en vez de guardarse en git: una figura sobre croma con lo que el recorte tiene que
saber tratar (un fondo con degradado, una sombra de croma apagado, huecos, un negro teñido de croma) y figuras
con la cabeza de un tamaño conocido para la escala.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from lib.escena import recorte

PIEL = (230, 190, 160)
PELO = (60, 40, 30)
CUERPO = (220, 120, 60)
PIERNAS = (40, 40, 60)
# Un negro al que se le corrió el croma: tono de croma y saturado, pero con poco brillo (0,24 < OSCURO).
NEGRO_TENIDO = (60, 10, 60)


def fondo_de_croma(ancho: int, alto: int) -> Image.Image:
    """Croma con degradado vertical (del 100 al 85 % de brillo), como el que devuelve Qwen."""
    y = np.linspace(1.0, 0.85, alto)[:, None, None]
    a = np.broadcast_to(np.array(recorte.CROMA, np.float32), (alto, ancho, 3)) * y
    return Image.fromarray(a.astype(np.uint8))


def persona(d: ImageDraw.ImageDraw, x: int, pies: int, alto: int, radio_pelo: float) -> None:
    """Una figura de pie centrada en x con los pies en `pies`: pelo, cara, cuerpo y dos piernas."""
    r = radio_pelo
    cabeza_y = pies - alto + r
    d.ellipse([x - r, cabeza_y - r, x + r, cabeza_y + r], fill=PELO)
    d.ellipse([x - 0.7 * r, cabeza_y - 0.3 * r, x + 0.7 * r, cabeza_y + r], fill=PIEL)
    d.rectangle([x - 0.9 * r, cabeza_y + r, x + 0.9 * r, pies - alto * 0.3], fill=CUERPO)
    d.rectangle([x - 0.8 * r, pies - alto * 0.3, x - 0.2 * r, pies], fill=PIERNAS)
    d.rectangle([x + 0.2 * r, pies - alto * 0.3, x + 0.8 * r, pies], fill=PIERNAS)


def figura_rgba(alto: int, radio_pelo: float, ancho: int | None = None) -> np.ndarray:
    """Una persona sobre transparente, con 16 px de margen: lo que deja el recorte."""
    ancho = ancho or int(radio_pelo * 2 + 40)
    im = Image.new("RGBA", (ancho, alto + 32), (0, 0, 0, 0))
    persona(ImageDraw.Draw(im), ancho // 2, alto + 16, alto, radio_pelo)
    return np.asarray(im).copy()


def hoja_sintetica(ruta: Path, altos: tuple[int, int], ancho: int = 420, alto: int = 300) -> Path:
    """Una hoja de personaje: dos figuras sobre croma, de frente (izquierda) y de perfil (derecha)."""
    im = fondo_de_croma(ancho, alto)
    d = ImageDraw.Draw(im)
    persona(d, ancho // 4, alto - 30, altos[0], altos[0] * 0.12)
    persona(d, 3 * ancho // 4, alto - 30, altos[1], altos[1] * 0.12)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    im.save(ruta)
    return ruta


def catalogo_de(dir_activos: Path, figuras: dict[str, tuple[np.ndarray, float]]) -> dict:
    """Guarda figuras (imagen, k) en `<activos>/img/` y escribe su catálogo, como lo dejaría el obrero."""
    img = dir_activos / "img"
    img.mkdir(parents=True, exist_ok=True)
    cat = {}
    for nombre, (rgba, k) in figuras.items():
        Image.fromarray(rgba, "RGBA").save(img / f"{nombre}.png")
        ax, ay = recorte.apoyo(rgba, False)
        cat[nombre] = {
            "src": f"assets/img/{nombre}.png",
            "w": rgba.shape[1],
            "h": rgba.shape[0],
            "ax": ax,
            "ay": ay,
            "ox": 0,
            "oy": 0,
            "k": k,
        }
    (dir_activos / "catalogo.json").write_text(json.dumps({"imagenes": cat}), encoding="utf-8")
    return cat


def registro_de_qwen(ruta: Path, semilla: int = 7) -> dict:
    """Un registro como el que deja `comfy_client.render` + `activos.genera` junto a una imagen generada."""
    return {
        "file": str(ruta),
        "workflow": "qwen-edit-lienzo",
        "modelo": "Qwen-Image-Edit-2511 GGUF Q6_K + LoRA Lightning 8 pasos",
        "licencia": "Apache-2.0 (Qwen-Image-Edit y Qwen-Image-Lightning) - uso comercial permitido",
        "origen": "generado en local con ComfyUI (127.0.0.1)",
        "prompt": "una instrucción",
        "seed": semilla,
        "url": "https://huggingface.co/Qwen/Qwen-Image-Edit-2511",
    }
