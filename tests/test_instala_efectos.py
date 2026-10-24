"""`scripts/instala_efectos.py` (OC1.2): los efectos de Pixabay se instalan desde HyperFrames con su sha256.

No viajan en el repositorio porque su licencia no deja distribuirlos sueltos. La prueba buena usa la copia de verdad
que deja `cd motor; npm ci`; los controles, una copia estropeada en una carpeta temporal.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lib import config
from lib.escena import audio
from scripts import instala_efectos as ie

CREDITOS_DE_VERDAD = config.ESCENA_SFX_DIR / config.ESCENA_CREDITOS
SIN_NPM = not config.HYPERFRAMES_SFX_DIR.is_dir()


def _destino(tmp_path: Path) -> Path:
    """Una biblioteca vacía con la lista de verdad: solo su `CREDITOS.json`, como en un clon recién descargado."""
    destino = tmp_path / "sfx"
    destino.mkdir()
    shutil.copy2(CREDITOS_DE_VERDAD, destino / config.ESCENA_CREDITOS)
    return destino


def _origen_falso(tmp_path: Path) -> Path:
    """Un HyperFrames con los ficheros que la lista pide, de contenido inventado, y la lista con sus sha256."""
    origen = tmp_path / "hyperframes-sfx"
    origen.mkdir()
    destino = tmp_path / "sfx"
    destino.mkdir()
    ficheros = {}
    for nombre in ("pop.mp3", "ping.mp3"):
        datos = f"sonido {nombre}".encode()
        (origen / nombre).write_bytes(datos)
        ficheros[nombre] = {"licencia": "Pixabay Content License", "sha256": hashlib.sha256(datos).hexdigest()}
    (destino / config.ESCENA_CREDITOS).write_text(json.dumps({"ficheros": ficheros}), encoding="utf-8")
    return origen


@pytest.mark.skipif(SIN_NPM, reason="HyperFrames no está instalado en motor/ (cd motor; npm ci)")
def test_los_nueve_efectos_se_instalan_desde_hyperframes_con_su_sha256(tmp_path):
    destino = _destino(tmp_path)
    copiados = ie.instala_efectos(config.HYPERFRAMES_SFX_DIR, destino)
    creditos = audio.lee_creditos(destino)
    assert len(creditos) == 9 and sorted(copiados) == sorted(creditos)
    for nombre, ficha in creditos.items():
        assert hashlib.sha256((destino / nombre).read_bytes()).hexdigest() == ficha["sha256"], nombre
    # Se puede repetir: la segunda vez no copia nada.
    assert ie.instala_efectos(config.HYPERFRAMES_SFX_DIR, destino) == []


def test_control_un_sha256_distinto_se_niega_y_no_se_copia_ninguno(tmp_path):
    origen = _origen_falso(tmp_path)
    (origen / "ping.mp3").write_bytes(b"otro sonido, quiza con otra licencia")
    with pytest.raises(ie.ErrorDeInstalacion, match="«ping.mp3» tiene otro sha256"):
        ie.instala_efectos(origen, tmp_path / "sfx")
    assert sorted(p.name for p in (tmp_path / "sfx").iterdir()) == [config.ESCENA_CREDITOS], "ni siquiera pop.mp3"


def test_control_sin_hyperframes_instalado_dice_como_instalarlo(tmp_path):
    origen = _origen_falso(tmp_path)
    (origen / "pop.mp3").unlink()
    with pytest.raises(ie.ErrorDeInstalacion, match="«pop.mp3» no está .*npm ci"):
        ie.instala_efectos(origen, tmp_path / "sfx")


def test_un_efecto_cambiado_en_la_biblioteca_se_sustituye_por_el_comprobado(tmp_path):
    origen = _origen_falso(tmp_path)
    assert ie.instala_efectos(origen, tmp_path / "sfx") == ["ping.mp3", "pop.mp3"]
    (tmp_path / "sfx" / "pop.mp3").write_bytes(b"cambiado a mano")
    assert ie.instala_efectos(origen, tmp_path / "sfx") == ["pop.mp3"]
    assert (tmp_path / "sfx" / "pop.mp3").read_bytes() == b"sonido pop.mp3"


@pytest.mark.skipif(
    not (config.BASE_DIR / ".git").exists(),
    reason="sin .git: una exportación antes de su primer commit, o un zip, no puede preguntarle a git",
)
def test_los_efectos_no_estan_en_git_y_su_lista_si():
    """Lo que viaja es la lista con los sha256; los mp3 los ignora git (`.gitignore`)."""
    raiz = config.BASE_DIR
    sfx = config.ESCENA_SFX_DIR.relative_to(raiz).as_posix()
    en_git = subprocess.run(["git", "ls-files", sfx], cwd=raiz, capture_output=True, text=True, check=True).stdout
    assert en_git.split() == [f"{sfx}/{config.ESCENA_CREDITOS}"]
    ignorado = subprocess.run(["git", "check-ignore", "-q", f"{sfx}/pop.mp3"], cwd=raiz)
    assert ignorado.returncode == 0, "un efecto copiado no puede volver a entrar en git por descuido"
