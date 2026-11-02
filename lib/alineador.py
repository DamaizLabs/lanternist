"""Marcas de tiempo por palabra: el lanzador del alineador que corre en `.venv-voz`.

Vive aparte de `lib/subtitulos.py` porque **lo usan dos etapas**. Nacio para el karaoke (F2.13),
donde las marcas dicen cuando se pinta cada palabra; desde el 06-09 las usa tambien la limpieza de
voz (`lib/limpia_voz.py`), donde dicen algo distinto y mas simple: **donde hay voz y donde no**.

El worker vive en `lib/alineador_worker.py` y se lanza como subproceso con el interprete de
`.venv-voz`, por el mismo cruce de entornos que el motor de voz: `transformers` y `torch` no estan
en el `.venv` del pipeline.
"""

import json
import subprocess
from pathlib import Path

from lib.config import ALINEADOR_WORKER, VOICE_PYTHON, VOICE_TIMEOUT
from lib.voice_worker import RecortadorPorTexto

# El troceo de whisper de una pasada normal, en segundos. Una lámina mal alineada con él se reintenta con otros
# (`lib/escena/etapas.py → TROCEOS_DE_REINTENTO_S`, OC2.4); un ítem del trabajo puede traer el suyo.
TROCEO_S = 30


class AlineadorError(RuntimeError):
    """El alineador no pudo producir marcas. No se reintenta."""


def une_pegadas(marcas: list[dict]) -> list[dict]:
    """Las marcas con cada palabra partida por whisper en una sola, como las une el recorte de la voz (OC2.4).

    El obrero marca con `pegada` el trozo que continúa la palabra anterior («.4%.» tras « 38»). Aquí se le devuelve el
    espacio que el obrero quitó a las demás y se pasan por `RecortadorPorTexto._une_trozos`, la misma unión de
    `_prepara`: «38.4%.», de donde empieza «38» a donde acaba «.4%.». Sin marcas pegadas, devuelve las mismas.
    """
    if not any(m.get("pegada") for m in marcas):
        return marcas
    trozos = [
        {"text": ("" if m.get("pegada") else " ") + m["texto"], "timestamp": (m["desde"], m["hasta"])} for m in marcas
    ]
    return [{"texto": t.strip(), "desde": a, "hasta": b} for t, (a, b) in RecortadorPorTexto._une_trozos(trozos)]


def alinea(items: list[dict], trabajo_dir: Path, cfg: dict) -> dict:
    """Lanza el alineador en `.venv-voz` y devuelve su resultado, con las palabras partidas ya unidas.

    Un ítem con `chunk_length_s` se alinea con ese troceo en vez de `TROCEO_S`. Si el obrero falla, no se relanza: el
    reintento de la etapa `alinea` es otra cosa, una lámina que salió mal medida y se prueba con otro troceo.
    """
    trabajo_dir.mkdir(parents=True, exist_ok=True)
    trabajo = trabajo_dir / "alineacion-trabajo.json"
    resultado = trabajo_dir / "alineacion-resultado.json"
    trabajo.write_text(
        json.dumps(
            {"modelo": cfg["modelo_alineacion"], "device": "cuda", "chunk_length_s": TROCEO_S, "items": items},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    proceso = subprocess.run(
        [VOICE_PYTHON, str(ALINEADOR_WORKER), "--trabajo", str(trabajo), "--resultado", str(resultado)],
        timeout=VOICE_TIMEOUT,
    )
    if proceso.returncode != 0 or not resultado.exists():
        raise AlineadorError(
            f"el alineador falló (código {proceso.returncode}). No se reintenta: un fallo del runtime "
            "local es un dato, no algo que se disimule repitiendo la llamada."
        )
    datos = json.loads(resultado.read_text(encoding="utf-8"))
    unidas = [une_pegadas(item["marcas"]) for item in datos["items"]]
    if any(u is not item["marcas"] for u, item in zip(unidas, datos["items"])):
        for u, item in zip(unidas, datos["items"]):
            item["marcas"] = u
        # Lo que leen la línea de tiempo y la integridad de la narración es el fichero: se reescribe ya unido
        resultado.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    return datos
