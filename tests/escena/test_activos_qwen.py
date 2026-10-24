"""Los activos con Qwen-Image-Edit de verdad (F6.2c): de la lámina a la hoja, de la hoja a una postura, y al catálogo.

**Se pide a mano**: cada generación son unos dos minutos de GPU y arranca ComfyUI si no está vivo. Corre solo con
`ESCENA_PRUEBA_QWEN=1`, y con las imágenes de video_1 (el experimento del que salió el motor de escena, que solo se
lee), en la carpeta que diga `ESCENA_PRUEBA_QWEN_VIDEO_1`. Con `ESCENA_PRUEBA_QWEN_EVIDENCIA=<carpeta>` deja allí
las imágenes y un `qwen.json` con lo medido.

Dos generaciones, las justas:

1. **La hoja** de un personaje, con la lámina del canal de referencia y un lienzo de croma APARTE: es lo que el
   workflow nuevo (`qwen-edit-lienzo`) añade al de tinta. Con el mismo estilo, descripción, semilla y modelo que
   video_1, se compara con su `hoja_nora-7.png`.
2. **Una postura** sobre el lienzo de referencia que el estudio saca de esa hoja (referencia Y lienzo).

Y sin Qwen, lo que viene detrás: el obrero recorta las dos (Real-ESRGAN), mide las cabezas y la procedencia de
todo el run tiene que cuadrar con fuente, licencia y url en cada asset. ComfyUI tiene que quedar como estaba: sin
nada nuestro en su `input/`.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lib import comfy_client as cc
from lib import config, provenance
from lib.escena import activos, obrero
from lib.escena.render import exige_gpu_libre

V1 = Path(os.getenv("ESCENA_PRUEBA_QWEN_VIDEO_1") or "(falta ESCENA_PRUEBA_QWEN_VIDEO_1)")
LAMINA = V1 / "canal" / "biblia" / "lamina-original.png"
CRUDO_V1 = V1 / "recursos" / "01-the-bike-is-in-two-pieces" / "crudo"

pytestmark = [
    pytest.mark.skipif(
        os.getenv("ESCENA_PRUEBA_QWEN") != "1", reason="se pide a mano: ESCENA_PRUEBA_QWEN=1 (≈5 min de GPU)"
    ),
    pytest.mark.skipif(not LAMINA.is_file(), reason=f"no está la lámina de video_1 ({LAMINA})"),
]

# El estilo y la descripción con que video_1 generó su biblia (su activos.py): son del canal, y aquí son datos.
ESTILO = activos.Estilo(
    prefijo=(
        "flat vector illustration, soft warm palette of dusty orange and cream, clean rounded shapes, gentle "
        "gradients, no outlines, friendly modern character design, calm low-contrast lighting, no text, no watermark."
    ),
    igual="Exactly the same flat style, the same faces and the same colours as in the picture.",
    conserva="Keep the same flat vector style, without outlines and without 3D shading",
)
NINA = activos.Personaje(
    id="nora",
    descripcion="Nora, a girl of about six, dark hair in two short braids, a green dress with white sleeves",
    alto=820,
    de_pie=("frente", "perfil"),
    vistas=activos.VISTAS_DE_PIE,
    mide_cabeza=True,
)


def _subidas_nuestras() -> list[str]:
    carpeta = config.COMFY_ROOT / "input" / config.COMFY_OUTPUT_SUBFOLDER
    return sorted(p.name for p in carpeta.iterdir()) if carpeta.exists() else []


def test_de_la_lamina_a_la_hoja_a_la_postura_y_al_catalogo(tmp_path):
    evidencia = Path(os.environ["ESCENA_PRUEBA_QWEN_EVIDENCIA"]) if os.getenv("ESCENA_PRUEBA_QWEN_EVIDENCIA") else None
    # Con evidencia, el run vive en ella: si algo falla después de generar, relanzar no vuelve a gastar GPU
    # (`genera` salta lo que ya está en disco).
    run = (evidencia or tmp_path) / "run"
    exige_gpu_libre()
    dir_activos, dir_trabajo = config.activos_del_run(run), config.trabajo_de_activos(run)
    medido: dict = {}
    hoja = activos.hoja(NINA, ESTILO, referencia=LAMINA, semillas=(7,))
    postura = activos.postura(
        "nora_manos",
        NINA,
        ESTILO,
        vista="frente",
        forma="alto",
        pose="standing facing the viewer with her hands clasped together in front of her chest, looking up hopefully",
        de_pie=True,
        lienzos=dir_activos / "ref",
        semillas=(7,),
    )

    t0 = time.perf_counter()
    with cc.comfy_server() as arrancado:
        medido["comfy_arrancado_por_la_prueba"] = arrancado
        r_hoja = activos.genera([hoja], dir_activos, dir_trabajo)
        activos.prepara_lienzos(NINA, activos.elegida(dir_activos, hoja), dir_activos / "ref")
        r_postura = activos.genera([hoja, postura], dir_activos, dir_trabajo)
    medido["qwen_reloj_s"] = round(time.perf_counter() - t0, 1)
    medido["qwen_segundos"] = {r["activo"]: r["segundos"] for r in r_hoja + r_postura}
    assert _subidas_nuestras() == [], "lo subido a ComfyUI se borra"

    crudo_hoja, crudo_postura = activos.elegida(dir_activos, hoja), activos.elegida(dir_activos, postura)
    assert Image.open(crudo_hoja).size == activos.LIENZO_HOJA
    assert Image.open(crudo_postura).size == activos.LIENZOS["alto"]
    rh, rp = r_hoja[0], r_postura[0]
    assert (rh["workflow"], rh["seed"], rh["lienzo"]) == ("qwen-edit-lienzo", 7, "croma liso 1664x928")
    assert rh["referencia"] == "lamina-original.png" and rh["url"].startswith("https://")
    assert rp["lienzo"] == "la propia referencia" and rp["referencia"].endswith("ref/nora_frente_alto.png")
    # La hoja, contra la de video_1: mismo estilo, descripción, semilla, modelo y grafo.
    suya = np.asarray(Image.open(CRUDO_V1 / "hoja_nora-7.png").convert("RGB")).astype(int)
    mia = np.asarray(Image.open(crudo_hoja).convert("RGB")).astype(int)
    medido["hoja_frente_a_video_1"] = {
        "dif_media": round(float(np.abs(mia - suya).mean()), 3),
        "px_distintos_mas_de_16": int((np.abs(mia - suya).max(axis=2) > 16).sum()),
        "px": int(mia.shape[0] * mia.shape[1]),
    }
    suya = np.asarray(Image.open(CRUDO_V1 / "nora_manos-7.png").convert("RGB")).astype(int)
    mia = np.asarray(Image.open(crudo_postura).convert("RGB")).astype(int)
    medido["postura_frente_a_video_1"] = {"dif_media": round(float(np.abs(mia - suya).mean()), 3)}

    # Sin Qwen: el obrero recorta las dos y mide las cabezas.
    t0 = time.perf_counter()
    r_obrero = activos.recorta_elegidas([hoja, postura], {"nora": NINA}, dir_activos, dir_trabajo)
    medido["obrero_reloj_s"] = round(time.perf_counter() - t0, 1)
    medido["obrero_segundos"] = {o["nombre"]: o["segundos"] for o in r_obrero["operaciones"]}
    medido["obrero_vram_pico_mb"] = r_obrero["vram_pico_mb"]
    medido["escala"] = activos.escala([hoja, postura], {"nora": NINA}, dir_activos)
    cat = obrero.lee_catalogo(dir_activos)["imagenes"]
    assert set(cat) == {"nora_frente", "nora_perfil", "nora_manos"}
    assert cat["nora_frente"]["k"] == pytest.approx(0.92, abs=0.02) and cat["nora_manos"].get("k0", 1.0) == 1.0
    assert all(cat[n]["cabeza_px"] > 0 and len(cat[n]["cabeza"]) == 4 for n in cat)
    medido["catalogo"] = cat

    informe = provenance.sync(run, verbose=False)
    medido["procedencia"] = {
        k: informe[k] for k in ("cuadra", "archivos_medios", "entradas", "por_tipo", "licencias_por_cerrar")
    }
    assert informe["cuadra"] and informe["licencias_por_cerrar"] == []
    for a in provenance.read_ledger(run)["assets"]:
        assert a["fuente"] and a["licencia"].startswith("Apache-2.0") and a["url"].startswith("https://"), a["id"]
    medido["assets"] = [
        {c: a[c] for c in ("id", "fuente", "modelo", "licencia", "url")} for a in provenance.read_ledger(run)["assets"]
    ]

    if evidencia:
        evidencia.mkdir(parents=True, exist_ok=True)
        for ruta in [
            crudo_hoja,
            crudo_postura,
            *(dir_activos / "img").glob("*.png"),
            *(dir_activos / "ref").glob("*.png"),
        ]:
            shutil.copy2(ruta, evidencia / f"{ruta.parent.name}-{ruta.name}")
        shutil.copy2(provenance.ledger_path(run), evidencia / "assets.json")
        (evidencia / "qwen.json").write_text(json.dumps(medido, indent=1, ensure_ascii=False), encoding="utf-8")
