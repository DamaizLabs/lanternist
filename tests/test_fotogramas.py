"""El lector de fotogramas (`lib/fotogramas.py`), sin red: las hojas de contactos y los fotogramas de un vídeo local.

Pasó del buscador del estudio a la fábrica en OC1.1 (fila 302) para el catálogo de formatos (OC1.11). Desde la fila 319
ya no baja nada de YouTube: los fotogramas salen de un vídeo del usuario, aquí uno corto que ffmpeg genera en
`tmp_path`.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest
from PIL import Image

from lib import fotogramas


def _imagen(ruta, color="white"):
    Image.new("RGB", (640, 360), color).save(ruta)
    return ruta


def test_una_hoja_por_filas_lleva_una_fila_por_canal(tmp_path):
    filas = [{"etiqueta": f"canal {n}", "imagenes": [_imagen(tmp_path / f"{n}.jpg")]} for n in range(3)]
    hoja = fotogramas.hoja_por_filas(filas, tmp_path / "hoja.jpg", "título")
    ancho, alto = Image.open(hoja).size
    assert ancho == 480 + 10 + 20 and alto == 40 + 3 * (270 + 34 + 10) + 10


def test_mas_filas_que_el_tope_se_parten_en_varias_hojas(tmp_path):
    imagen = _imagen(tmp_path / "x.jpg")
    filas = [{"etiqueta": str(n), "imagenes": [imagen]} for n in range(fotogramas.FILAS_POR_HOJA + 1)]
    hojas = fotogramas.hojas_por_filas(filas, tmp_path / "vuelta.jpg")
    assert [h.name for h in hojas] == ["vuelta-1.jpg", "vuelta-2.jpg"]


def test_control_con_pocas_filas_sale_una_sola_hoja_con_su_nombre(tmp_path):
    imagen = _imagen(tmp_path / "x.jpg")
    hojas = fotogramas.hojas_por_filas([{"etiqueta": "a", "imagenes": [imagen]}], tmp_path / "vuelta.jpg")
    assert [h.name for h in hojas] == ["vuelta.jpg"]


def test_la_rejilla_deja_hueco_a_una_celda_sin_imagen(tmp_path):
    celdas = [{"imagen": _imagen(tmp_path / "a.jpg"), "linea1": "uno"}, {"linea1": "sin imagen"}]
    hoja = fotogramas.hoja_en_rejilla(celdas, tmp_path / "rejilla.jpg", "búsqueda", columnas=2)
    assert Image.open(hoja).size == (2 * (320 + 8) + 8, 40 + 1 * (180 + 36 + 8))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sin ffmpeg en el PATH")
def test_los_fotogramas_de_un_video_local_se_reparten_por_su_duracion(tmp_path):
    video = tmp_path / "corto.mp4"
    orden = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x180:rate=10",
             "-pix_fmt", "yuv420p", str(video)]  # fmt: skip
    subprocess.run(orden, check=True, capture_output=True, timeout=60)
    sacados = fotogramas.fotogramas_de_fichero(video, tmp_path / "f", n=4)
    assert [segundo for _, segundo in sacados] == [0.25, 0.75, 1.25, 1.75]
    assert all(Image.open(ruta).size == (320, 180) for ruta, _ in sacados)


def test_control_un_fichero_que_no_es_un_video_no_da_fotogramas(tmp_path):
    falso = tmp_path / "falso.mp4"
    falso.write_text("no soy un vídeo", encoding="utf-8")
    assert fotogramas.duracion_de(falso) is None
    assert fotogramas.fotogramas_de_fichero(falso, tmp_path / "f") == []


def test_sin_el_binario_la_orden_da_none_y_no_revienta():
    assert fotogramas._corre(["binario-que-no-existe-en-ningun-path"], timeout=5) is None
