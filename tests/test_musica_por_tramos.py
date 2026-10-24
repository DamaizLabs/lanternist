"""El lecho por tramos de `lib/musica.genera_lecho` con la sonoridad por tramo del canal (F6.5b, addendum fila 210).

El v3 de la bici iguala cada pista a -22 LUFS antes de encadenarlas, porque ACE-Step deja pasajes más fuertes
que el resto y con ellos la música igualaba a la voz. Aquí ACE-Step se sustituye por dos tramos de ruido rosa a
niveles muy distintos (unos 23 dB), sin GPU:

- con `sonoridad_por_tramo`, los dos salen a la misma sonoridad;
- control: con null, la diferencia se queda, y la cadena es la de antes de F6.5b.
"""

from __future__ import annotations

import math
import shutil
import subprocess

import numpy as np
import pytest

from lib import musica

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sin ffmpeg no hay audio que medir")

MUESTRAS = 48000
MUSICA = {
    "activa": True,
    "escena": "calm music for a test",
    "volumen_db": 0.0,
    "tramo_segundos": 10.0,
    "solape_segundos": 2.0,
    "sonoridad_por_tramo": None,
    "umbral_ducking": 0.05,
    "ratio_ducking": 8,
    "ataque_ms": 20,
    "suelta_ms": 500,
    "semilla_base": 11,
}
IGUALA = {"lufs": -22, "rango_lu": 6, "pico_dbtp": -2}
# El primer tramo, bajo; el segundo, unos 23 dB más fuerte (0,3 / 0,02 en amplitud).
AMPLITUDES = (0.02, 0.3)


@pytest.fixture
def tramos_desiguales(monkeypatch):
    """ACE-Step sustituido por ruido rosa: el tramo i sale con la amplitud AMPLITUDES[i]."""
    pedidos = []

    def falso(workflow, escena, segundos, seed, destino):
        i = int(destino.stem.split("-")[1])
        ruta = destino.with_suffix(".wav")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
             f"anoisesrc=color=pink:amplitude={AMPLITUDES[i]}:duration={segundos}:seed={seed}:sample_rate=44100",
             "-ac", "2", str(ruta)],
            check=True,
        )  # fmt: skip
        pedidos.append(seed)
        return {"archivo": ruta, "seed": seed, "segundos_pedidos": segundos}

    monkeypatch.setattr(musica, "_genera_tramo", falso)
    return pedidos


def _rms_db(ruta: str, desde: float, hasta: float) -> float:
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", ruta, "-f", "s16le", "-ac", "1", "-ar", str(MUESTRAS), "-"],
        capture_output=True, check=True,
    )  # fmt: skip
    x = np.frombuffer(r.stdout, "<i2").astype(np.float64) / 32768
    trozo = x[int(desde * MUESTRAS) : int(hasta * MUESTRAS)]
    return 20 * math.log10(max(float(np.sqrt(np.mean(trozo**2))), 1e-9))


def _salto(registro: dict) -> float:
    """dB del segundo tramo (10,5-12,8 s, antes del fundido final) frente al primero (3,5-7,5 s, tras el de entrada).

    Con tramos de 10 s y 2 de solape, el segundo empieza a los 8 s y acaba su fundido de entrada a los 10.
    """
    return _rms_db(registro["file"], 10.5, 12.8) - _rms_db(registro["file"], 3.5, 7.5)


def test_con_sonoridad_por_tramo_los_tramos_salen_igualados(tmp_path, tramos_desiguales):
    registro = musica.genera_lecho(18.0, tmp_path, perfil={"musica": {**MUSICA, "sonoridad_por_tramo": dict(IGUALA)}})
    assert tramos_desiguales == [11, 1122], "dos tramos, con la semilla base del perfil"
    assert abs(_salto(registro)) < 2, f"los tramos no salen igualados: {_salto(registro):.1f} dB de salto"
    # Y el registro de procedencia dice que el lecho no es la salida del modelo tal cual.
    assert registro["sonoridad_por_tramo"] == IGUALA and registro["solape_segundos"] == 2.0


def test_control_sin_sonoridad_por_tramo_el_salto_se_queda(tmp_path, tramos_desiguales):
    registro = musica.genera_lecho(18.0, tmp_path, perfil={"musica": dict(MUSICA)})
    assert _salto(registro) > 15, f"sin igualar, el segundo tramo tendría que sonar mucho más: {_salto(registro):.1f}"
    assert registro["sonoridad_por_tramo"] is None


def test_con_un_solo_tramo_tambien_se_iguala(tmp_path, tramos_desiguales):
    """La rama de un tramo (un vídeo más corto que el tramo) lleva el mismo igualado que la de varios."""
    con = musica.genera_lecho(9.0, tmp_path / "con", perfil={"musica": {**MUSICA, "sonoridad_por_tramo": dict(IGUALA)}})
    sin = musica.genera_lecho(9.0, tmp_path / "sin", perfil={"musica": dict(MUSICA)})
    # El tramo bajo (amplitud 0,02) sube hacia -22 LUFS con el igualado; sin él, se queda donde estaba.
    assert _rms_db(con["file"], 3.5, 5.0) - _rms_db(sin["file"], 3.5, 5.0) > 6
    assert tramos_desiguales == [11, 11]
