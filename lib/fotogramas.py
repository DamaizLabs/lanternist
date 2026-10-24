"""Fotogramas de un vídeo local y hojas de contactos: lo que Claude mira para analizar el estilo de un vídeo.

El estilo visual de un vídeo no lo dice ningún metadato, así que se mira. Los fotogramas salen de un fichero que da el
usuario, en local con ffprobe y ffmpeg, y nada se sube a ningún sitio. Del enlace de un vídeo de YouTube no se baja
nada más que su miniatura (`scripts/mira_video.py`): sus términos prohíben descargar el vídeo, así que el motor ya no
usa yt-dlp (fila 319).

Nació en el buscador de estilos del estudio (F5.12) y pasó a la fábrica en OC1.1 (fila 302): lo usa el catálogo de
formatos (OC1.11) para proponer un formato a partir de un vídeo.

Las hojas juntan varias imágenes con su etiqueta debajo: varias imágenes se comparan en rejilla.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from lib.config import entorno_para_terceros

# Cuántos fotogramas se sacan de un vídeo del usuario: dos filas de la hoja, de principio a fin del vídeo.
FOTOGRAMAS_POR_VIDEO = 8


def _fuente(tam: int):
    try:
        return ImageFont.truetype("arial.ttf", tam)
    except OSError:
        return ImageFont.load_default()


def _corre(orden: list[str], timeout: int) -> subprocess.CompletedProcess | None:
    """Lanza ffprobe o ffmpeg sin credenciales. Un cuelgue o un binario ausente dan None, no un traceback: quien llama
    dice qué fotograma falta (auditoría de F5.12)."""
    try:
        return subprocess.run(orden, capture_output=True, text=True, timeout=timeout, env=entorno_para_terceros())
    except (subprocess.TimeoutExpired, OSError):
        return None


def duracion_de(video: Path) -> float | None:
    """La duración del vídeo en segundos, según ffprobe. None si no es un vídeo que ffprobe sepa leer."""
    orden = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)]
    hecho = _corre(orden, timeout=60)
    try:
        duracion = float(hecho.stdout.strip()) if hecho and hecho.returncode == 0 else 0.0
    except ValueError:
        return None
    return duracion if duracion > 0 else None


def fotogramas_de_fichero(video: Path, carpeta: Path, n: int = FOTOGRAMAS_POR_VIDEO) -> list[tuple[Path, float]]:
    """`n` fotogramas repartidos por la duración de un vídeo local: [(ruta, segundo)].

    Cada uno sale del centro de su tramo (el 1 de 8 en el 6 % del vídeo, el 8 en el 94 %), así que ni el negro del
    arranque ni el del final ocupan una celda. Un fotograma que ffmpeg no saca no está en la lista. Vacía si ffprobe
    no lee el vídeo.
    """
    duracion = duracion_de(video)
    if duracion is None:
        return []
    carpeta.mkdir(parents=True, exist_ok=True)
    salida = []
    for i in range(n):
        segundo = round(duracion * (i + 0.5) / n, 2)
        destino = carpeta / f"fotograma-{i + 1:02d}.jpg"
        destino.unlink(missing_ok=True)
        orden = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{segundo}", "-i", str(video), "-frames:v", "1",
                 "-q:v", "3", str(destino)]  # fmt: skip
        _corre(orden, timeout=60)
        if destino.is_file():
            salida.append((destino, segundo))
    return salida


def hoja_por_filas(filas: list[dict], destino: Path, titulo: str = "") -> Path:
    """Una fila por canal: su etiqueta encima y sus fotogramas al lado. `filas`: [{etiqueta, imagenes}]."""
    ancho, alto, etiqueta = 480, 270, 34
    columnas = max([len(f["imagenes"]) for f in filas] + [1])
    arriba = 40 if titulo else 10
    hoja = Image.new("RGB", (columnas * (ancho + 10) + 20, arriba + len(filas) * (alto + etiqueta + 10) + 10), "white")
    d = ImageDraw.Draw(hoja)
    if titulo:
        d.text((10, 12), titulo, fill="black", font=_fuente(18))
    for i, f in enumerate(filas):
        y = arriba + i * (alto + etiqueta + 10)
        d.text((10, y + 6), f["etiqueta"], fill="black", font=_fuente(17))
        for j, ruta in enumerate(f["imagenes"]):
            im = Image.open(ruta).convert("RGB")
            im.thumbnail((ancho, alto))
            hoja.paste(im, (10 + j * (ancho + 10), y + etiqueta))
    destino.parent.mkdir(parents=True, exist_ok=True)
    hoja.save(destino, quality=85)
    return destino


FILAS_POR_HOJA = 7  # más filas y la hoja es tan alta que al mirarla se reduce hasta no distinguir el estilo


def hojas_por_filas(filas: list[dict], destino: Path, titulo: str = "") -> list[Path]:
    """Como `hoja_por_filas`, pero partida en hojas de FILAS_POR_HOJA canales: -1.jpg, -2.jpg…"""
    if len(filas) <= FILAS_POR_HOJA:
        return [hoja_por_filas(filas, destino, titulo)]
    salida = []
    for n, i in enumerate(range(0, len(filas), FILAS_POR_HOJA), start=1):
        parte = destino.with_name(f"{destino.stem}-{n}{destino.suffix}")
        salida.append(hoja_por_filas(filas[i : i + FILAS_POR_HOJA], parte, titulo))
    return salida


def hoja_en_rejilla(celdas: list[dict], destino: Path, titulo: str, columnas: int = 5) -> Path:
    """Rejilla de miniaturas con dos líneas debajo de cada una. `celdas`: [{imagen, linea1, linea2}]."""
    ancho, alto, pie = 320, 180, 36
    filas = (len(celdas) + columnas - 1) // columnas or 1
    hoja = Image.new("RGB", (columnas * (ancho + 8) + 8, 40 + filas * (alto + pie + 8)), "white")
    d = ImageDraw.Draw(hoja)
    d.text((8, 12), titulo, fill="black", font=_fuente(14))
    for i, c in enumerate(celdas):
        x, y = 8 + (i % columnas) * (ancho + 8), 36 + (i // columnas) * (alto + pie + 8)
        if c.get("imagen"):
            im = Image.open(c["imagen"]).convert("RGB")
            im.thumbnail((ancho, alto))
            hoja.paste(im, (x, y))
        d.text((x, y + alto + 2), c.get("linea1", "")[:44], fill="black", font=_fuente(13))
        d.text((x, y + alto + 18), c.get("linea2", "")[:44], fill="#444", font=_fuente(13))
    destino.parent.mkdir(parents=True, exist_ok=True)
    hoja.save(destino, quality=85)
    return destino
