"""El obrero de activos con la GPU de verdad (F6.2c): Real-ESRGAN y SAM 2.1 en `.venv-escena`.

Se saltan, con el motivo, si falta `.venv-escena`, el peso de Real-ESRGAN, SAM 2.1 en la caché de Hugging Face,
nvidia-smi, o si la GPU está ocupada por otro trabajo del estudio (la GPU va de una en una). Las imágenes son
sintéticas y pequeñas; lo mismo con las de video_1 está medido en `experimentos/motor-escena/f62c-real/gpu.py`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from utiles_activos import fondo_de_croma, persona, registro_de_qwen

from lib import config, provenance
from lib.escena import obrero, recorte
from lib.escena.render import ErrorDeRender, exige_gpu_libre

CACHE_SAM = Path.home() / ".cache" / "huggingface" / "hub" / "models--facebook--sam2.1-hiera-large"


def falta_para_el_obrero() -> str | None:
    if not Path(config.ESCENA_PYTHON).is_file():
        return "no está .venv-escena (spikes/requirements-escena.txt)"
    if not Path(config.ESCENA_ESRGAN_PESO).is_file():
        return f"no está el peso de Real-ESRGAN ({config.ESCENA_ESRGAN_PESO})"
    if not any(CACHE_SAM.glob("snapshots/*/model.safetensors")):
        return "SAM 2.1 no está en la caché de Hugging Face (el obrero no lo descarga)"
    if shutil.which("nvidia-smi") is None:
        return "no hay nvidia-smi: sin GPU NVIDIA no hay obrero"
    try:
        exige_gpu_libre()
    except ErrorDeRender as e:
        return f"la GPU está ocupada: {e}"
    return None


FALTA = falta_para_el_obrero()
pytestmark = pytest.mark.skipif(FALTA is not None, reason=FALTA or "")


def test_recorta_con_real_esrgan_una_figura_sobre_croma(tmp_path):
    run = tmp_path / "run"
    activos, trabajo = config.activos_del_run(run), config.trabajo_de_activos(run)
    origen = activos / "crudo" / "ana-7.png"
    origen.parent.mkdir(parents=True)
    im = fondo_de_croma(160, 200)
    persona(ImageDraw.Draw(im), 80, 180, 150, 18)
    im.save(origen)
    (origen.parent / provenance.IMAGE_RECORDS_FILENAME).write_text(json.dumps([registro_de_qwen(origen)]), "utf-8")

    resultado = obrero.ejecuta([obrero.recorta("ana", origen)], activos, trabajo)

    e = obrero.lee_catalogo(activos)["imagenes"]["ana"]
    figura = np.asarray(Image.open(activos / "img" / "ana.png"))
    assert (e["w"], e["h"]) == (figura.shape[1], figura.shape[0]) and e["k"] == 1.0
    assert figura[0, 0, 3] == 0 and figura[-1, -1, 3] == 0, "el croma queda transparente"
    assert figura[2 * 100 - e["oy"], int(e["ax"]), 3] == 255, "el cuerpo (y = 100 en la generada) es opaco"
    assert e["oy"] + e["ay"] == pytest.approx(2 * 180, abs=3), "los pies, a ×2 de donde se dibujaron"
    peso = hashlib.sha256(Path(config.ESCENA_ESRGAN_PESO).read_bytes()).hexdigest()
    assert resultado["modelos"]["esrgan"]["sha256"] == peso
    assert resultado["vram_pico_mb"] > 0 and resultado["gpu"]
    # Control: sin Real-ESRGAN (Lanczos ×2 a secas) el recorte sale distinto: el modelo ha trabajado.
    lanczos = recorte.quita_magenta(np.asarray(im.resize((320, 400), Image.LANCZOS)).astype(np.float32))
    x0, y0 = e["ox"], e["oy"]
    trozo = lanczos[y0 : y0 + e["h"], x0 : x0 + e["w"], :3].astype(int)
    opaco = figura[..., 3] == 255
    assert np.abs(trozo[opaco] - figura[..., :3][opaco].astype(int)).mean() > 0.5
    informe = provenance.sync(run, verbose=False)
    assert informe["cuadra"]
    registro = json.loads((activos / "img" / provenance.IMAGE_RECORDS_FILENAME).read_text(encoding="utf-8"))[0]
    assert registro["herramientas"]["esrgan"]["sha256"] == peso and "Real-ESRGAN" in registro["modelo"]


def test_separa_con_sam_cada_pieza_por_su_caja_y_sus_puntos(tmp_path):
    """Dos piezas en la misma imagen: la máscara de cada una sigue a SU caja y SUS puntos (y no a la otra)."""
    activos = tmp_path / "activos"
    (activos / "img").mkdir(parents=True)
    im = Image.new("RGBA", (320, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([140, 150, 300, 250], fill=(170, 110, 60, 255))  # la «base»: una caja marrón
    d.ellipse([20, 20, 130, 130], fill=(60, 150, 70, 255))  # una copa verde, aparte
    d.rectangle([180, 40, 260, 120], fill=(220, 200, 40, 255))  # un cartel amarillo
    im.save(activos / "img" / "calle.png")
    base = {"src": "assets/img/calle.png", "w": 320, "h": 256, "ax": 220.0, "ay": 250.0, "ox": 0, "oy": 0, "k": 1.0}
    obrero.guarda_catalogo(activos, {"imagenes": {"calle": base}})
    piezas = [
        {"nombre": "copa", "caja": [10, 10, 140, 140], "pos": [[75, 75]], "neg": [[220, 80]], "pivote": [75, 130]},
        {"nombre": "cartel", "caja": [170, 30, 270, 130], "pos": [[220, 80]], "neg": [[75, 75]], "pivote": [220, 120]},
    ]
    obrero.ejecuta([obrero.separa("calle", "calle.png", base, piezas, quita_de_la_base=True)], activos, tmp_path / "t")

    cat = obrero.lee_catalogo(activos)["imagenes"]
    copa = np.asarray(Image.open(activos / "img" / "calle_copa.png"))
    cartel = np.asarray(Image.open(activos / "img" / "calle_cartel.png"))
    resto = np.asarray(Image.open(activos / "img" / "calle_base.png"))
    c, k = cat["calle_copa"], cat["calle_cartel"]
    assert copa[int(c["ay"]) - 55, int(c["ax"]), 3] > 230, "el centro de la copa está en su pieza"
    assert cartel[int(k["ay"]) - 40, int(k["ax"]), 3] > 230, "el centro del cartel está en la suya"
    assert c["w"] < 140 and k["w"] < 110, "ninguna pieza se lleva a la otra"
    assert c["off"] == [75 - 220.0, 130 - 250.0] and k["off"] == [0.0, 120 - 250.0]
    # Lo que SAM separa dice de qué figura sale (F6.2d): la escala le pasa el factor de esa y de ninguna otra.
    assert c["de"] == k["de"] == cat["calle_base"]["de"] == "calle"
    assert resto[75, 75, 3] < 20 and resto[80, 220, 3] < 20, "la base se queda sin las dos piezas"
    assert resto[200, 220, 3] == 255, "control: lo que no se pidió sigue en la base"
