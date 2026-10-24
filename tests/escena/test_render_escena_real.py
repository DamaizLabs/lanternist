"""Un episodio de segundo y medio, de verdad, por las etapas del motor de escena (F6.2d): Chrome, GPU y HyperFrames.

Lo único falso es whisper (la voz de la prueba es silencio, así que no hay nada que reconocer: se usa la alineación
que deja el run). Todo lo demás corre como en producción: la sonda y los fotogramas de la parada 2 con `snapshot`,
el render con la guarda de red y el Chrome con WebGPU, el sonido mezclado por HyperFrames. Se mira lo que el
contrato promete: `montaje.json`, el `final.mp4` en `subir-al-canal/`, el efecto de sonido dentro del vídeo y la
procedencia del run entera.

Necesita la GPU libre (como las pruebas de render de F6.2a). Con `ESCENA_PRUEBA_EVIDENCIA=<carpeta>` deja allí el
vídeo, su `montaje.json`, la página de la parada 2 y un `medido.json`.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from utiles_escena import falta_para_el_navegador
from utiles_pipeline import canal_de_prueba, guion_en_el_canal, perfil_de_prueba, prepara_run

from lib import alineador, config, provenance
from lib.escena import etapas
from lib.escena.episodio import Episodio

FALTA = falta_para_el_navegador()
pytestmark = pytest.mark.skipif(FALTA is not None, reason=FALTA or "")

RUN_ID = "2026-09-29_000001_render-corto"
PAUSAS = {"intro_s": 0.25, "entre_partes_s": 0.5, "cola_s": 0.25}


def _ffprobe(ruta: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate,nb_frames,channels"]
        + ["-show_entries", "format=duration", "-of", "json", str(ruta)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(r.stdout)


def _rms_db(video: Path, desde: float, hasta: float) -> float:
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-f", "s16le", "-ac", "1", "-ar", "48000", "-"],
        capture_output=True,
        check=True,
    )
    x = np.frombuffer(r.stdout, "<i2").astype(np.float64) / 32768
    trozo = x[int(desde * 48000) : int(hasta * 48000)]
    return 20 * math.log10(max(float(np.sqrt(np.mean(trozo**2))), 1e-9))


def test_un_episodio_corto_de_verdad_deja_su_video_y_su_montaje(tmp_path, monkeypatch, marca_falsa):
    perfil = perfil_de_prueba(pausas=PAUSAS)
    canal = canal_de_prueba(tmp_path / "canal", perfil)
    run = prepara_run(tmp_path / "videos" / RUN_ID, [{"narration": "Ana walked.", "dura": 1.0}])
    guion_en_el_canal(canal, RUN_ID, "corta")
    ep = Episodio(run_dir=run, run_id=RUN_ID, canal_dir=canal, perfil=perfil, idioma="en")
    monkeypatch.setattr(
        alineador,
        "alinea",
        lambda items, trabajo, cfg: json.loads((Path(trabajo) / "alineacion-resultado.json").read_text("utf-8")),
    )

    etapas.alinea(ep)
    etapas.activos(ep)
    escena = etapas.escena(ep)
    hecho = etapas.render(ep, huella_composicion=escena["huella_composicion"], huella_guion=escena["huella_guion"])

    final = hecho["salida"]
    montaje = json.loads((run / "montaje.json").read_text(encoding="utf-8"))
    sonda = _ffprobe(final)
    video = next(s for s in sonda["streams"] if s["codec_type"] == "video")
    sonido = next(s for s in sonda["streams"] if s["codec_type"] == "audio")
    # El contrato de montaje.json: una entrada por lámina de voz, su inicio tras la intro y la duración del GUION.
    assert montaje["salida"] == "subir-al-canal/final.mp4" and final == run / "subir-al-canal" / "final.mp4"
    assert montaje["duracion_s"] == pytest.approx(1.5, abs=1e-3)
    assert montaje["detalle"] == [
        {
            "plano": 1,
            "slide": 1,
            "inicio_s": 0.25,
            "segundos": 1.0,
            "fin_s": 1.25,
            "silencio_tras_s": 0.25,
            "planos_de_escena": [montaje["detalle"][0]["planos_de_escena"][0]],
        }
    ]
    # El vídeo: el marco y los fps del bloque `escena` del canal, 36 fotogramas y un sonido.
    assert (video["width"], video["height"], video["r_frame_rate"]) == (1920, 1080, "24/1")
    assert int(video["nb_frames"]) == 36
    assert int(sonido["channels"]) >= 1, "el vídeo lleva sonido"
    assert float(sonda["format"]["duration"]) == pytest.approx(1.5, abs=0.05)
    # El efecto de sonido (pop en t = 0,4, de la biblioteca del estudio) está dentro: la voz de la prueba es silencio,
    # así que el control es el mismo vídeo medio segundo después, cuando el pop ya ha acabado.
    con_pop, sin_pop = _rms_db(final, 0.45, 0.75), _rms_db(final, 1.2, 1.45)
    assert con_pop > sin_pop + 20, (con_pop, sin_pop)
    # La procedencia del run entera cuadra, y el vídeo se describe como lo que es.
    informe = provenance.sync(run, verbose=False)
    assert informe["cuadra"], informe
    entrada = next(a for a in provenance.read_ledger(run)["assets"] if a["tipo"] == "video")
    assert "motor de escena" in entrada["origen"] and entrada["detalle"]["herramientas"]["hyperframes"] == "0.8.78"

    evidencia = os.getenv("ESCENA_PRUEBA_EVIDENCIA")
    if evidencia:
        destino = Path(evidencia)
        destino.mkdir(parents=True, exist_ok=True)
        for origen in (final, run / "montaje.json", escena["pagina"], run / "assets.json"):
            shutil.copy2(origen, destino / origen.name)
        (destino / "medido.json").write_text(
            json.dumps(
                {
                    "ffprobe": sonda,
                    "rms_db": {"con_pop_0.45-0.75": round(con_pop, 1), "sin_pop_1.2-1.45": round(sin_pop, 1)},
                    "conteo": informe,
                    "render_s": montaje["cronometraje"]["render_s"],
                    "defectos": escena["defectos"],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    assert config.revision_del_run(run).joinpath("fotogramas.html").is_file()
