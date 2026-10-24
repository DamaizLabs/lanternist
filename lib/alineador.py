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


class AlineadorError(RuntimeError):
    """El alineador no pudo producir marcas. No se reintenta."""


def alinea(items: list[dict], trabajo_dir: Path, cfg: dict) -> dict:
    """Lanza el alineador en `.venv-voz` y devuelve su resultado. Sin reintentos."""
    trabajo_dir.mkdir(parents=True, exist_ok=True)
    trabajo = trabajo_dir / "alineacion-trabajo.json"
    resultado = trabajo_dir / "alineacion-resultado.json"
    trabajo.write_text(
        json.dumps(
            {"modelo": cfg["modelo_alineacion"], "device": "cuda", "chunk_length_s": 30, "items": items},
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
    return json.loads(resultado.read_text(encoding="utf-8"))
