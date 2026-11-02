"""El intérprete de voz de verdad (OC2.5): importa lo que importan sus obreros y escribe el WAV como antes.

Las demás pruebas de la voz corren el código de los obreros dentro del `.venv`, con su torch de CPU. Esta es la única
que lanza el intérprete de `PYTHON_VOZ`, el que usa el motor. Nace de una trampa de la subida de torch: desde la 2.9,
`torchaudio.save` pide TorchCodec y las DLL de FFmpeg, así que los obreros leen y escriben con soundfile. El WAV tiene
que salir como lo escribía torchaudio con soundfile: en coma flotante de 32 bits, [canal, tiempo] y sin tocar una
muestra (`experimentos/OC2.5/io-viejo.json`).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from lib import config

SONDA = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import soundfile, torch, torchaudio.functional
from kokoro import KPipeline
from snac import SNAC
from transformers import pipeline
import alineador_worker, limpia_worker, voice_worker
ruta = sys.argv[2]
onda = torch.linspace(-0.5, 0.5, 2400).unsqueeze(0)
voice_worker._guarda_wav(ruta, onda, 24000)
leida, sr = voice_worker._lee_wav(ruta)
print(json.dumps({
    "subtipo": soundfile.info(ruta).subtype,
    "forma": list(leida.shape),
    "dtype": str(leida.dtype),
    "sr": sr,
    "igual": bool(torch.equal(leida, onda)),
    "remuestreada": list(torchaudio.functional.resample(onda, 24000, 16000).shape),
}))
"""


@pytest.mark.skipif(not Path(config.VOICE_PYTHON).is_file(), reason="sin el entorno de voz (instala.py, paso entornos)")
def test_el_interprete_de_voz_importa_sus_motores_y_escribe_el_wav_como_antes(tmp_path):
    ruta = tmp_path / "onda.wav"
    r = subprocess.run(
        [config.VOICE_PYTHON, "-c", SONDA, str(config.BASE_DIR / "lib"), str(ruta)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert json.loads(r.stdout.strip().splitlines()[-1]) == {
        "subtipo": "FLOAT",
        "forma": [1, 2400],
        "dtype": "torch.float32",
        "sr": 24000,
        "igual": True,
        # El pipeline de whisper remuestrea con torchaudio la voz de 24 kHz a sus 16 kHz (el recorte por texto).
        "remuestreada": [1, 1600],
    }
