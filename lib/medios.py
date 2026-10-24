"""Utilidades de medios del estudio que no son de ningún motor: hoy, la duración de un audio con `ffprobe`.

`get_audio_duration` vivía en `lib/video_assembler.py`, el montaje del motor de láminas, y la usaban también el sonido
del motor de escena (`lib/escena/audio.py`), el lecho musical (`lib/musica.py`) y la cata del ritmo de voz
(`scripts/cata_ritmo.py`). Se movió aquí sin cambiar una línea cuando F6.7 retiró aquel motor (02-10-2026).
"""

import json
import subprocess


def get_audio_duration(audio_path: str) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])
