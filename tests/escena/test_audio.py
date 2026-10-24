"""El sonido del motor de escena (F6.2d): narración con pausas, lecho apartado bajo la voz, efectos y biblioteca.

Todo con FFmpeg y ficheros sintéticos, sin GPU. Cada medida lleva su control negativo:

- la narración pone cada lámina donde dice la línea de tiempo, y otra pausa declarada la mueve;
- el lecho baja cuando habla la voz, y sin compresor no baja;
- la sonoridad final llega al objetivo del estudio, y sin normalizar no llega;
- la biblioteca copia con su procedencia, y un fichero sin entrada o cambiado para.
"""

from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest
from utiles_escena import LAMINAS_PRUEBA, crea_run, escena_prueba

from lib import config, musica, provenance
from lib.escena import ajustes, audio
from lib.escena.linea_tiempo import LineaDeTiempo

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sin ffmpeg no hay audio que medir")

MUESTRAS = audio.MUESTRAS_POR_SEGUNDO


# ------------------------------------------------------------------------------------------ utilidades
def tono(ruta: Path, segundos: float, *, hz: float = 440.0, amplitud: float = 0.5, muestras: int = 24000) -> Path:
    """Un wav PCM de 16 bits con un tono de `hz`, de esa duración exacta."""
    n = round(segundos * muestras)
    t = np.arange(n) / muestras
    datos = (np.sin(2 * math.pi * hz * t) * amplitud * 32767).astype("<i2").tobytes()
    fmt = struct.pack("<HHIIHH", 1, 1, muestras, muestras * 2, 2, 16)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(
        b"RIFF" + struct.pack("<I", 36 + len(datos)) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt
        + b"data" + struct.pack("<I", len(datos)) + datos
    )  # fmt: skip
    return ruta


def muestras_de(ruta: Path, canales: int = 1) -> np.ndarray:
    """Las muestras de un audio a 48 kHz, en float, leídas con ffmpeg (sirve para wav y para el audio de un mp4)."""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(ruta), "-f", "s16le", "-ac", str(canales), "-ar", str(MUESTRAS), "-"],
        capture_output=True,
        check=True,
    )
    # Entrelazadas si son varios canales: una fila por instante y la media de los canales, para medir en el tiempo.
    return (np.frombuffer(r.stdout, "<i2").astype(np.float64) / 32768).reshape(-1, canales).mean(axis=1)


def rms_db(x: np.ndarray, desde: float, hasta: float) -> float:
    trozo = x[int(desde * MUESTRAS) : int(hasta * MUESTRAS)]
    return 20 * math.log10(max(float(np.sqrt(np.mean(trozo**2))), 1e-9))


def linea_con_tono(carpeta: Path, pausas: dict | None = None) -> tuple[LineaDeTiempo, list[Path]]:
    """La línea de tiempo del episodio de prueba con cada wav cambiado por un tono de su misma duración."""
    escena = escena_prueba()
    if pausas:
        escena["pausas"] = pausas
    run = crea_run(carpeta, LAMINAS_PRUEBA)
    wavs = [config.audio_de_lamina(run, n + 1) for n in range(len(LAMINAS_PRUEBA))]
    for wav, lam in zip(wavs, LAMINAS_PRUEBA):
        tono(wav, lam["dura"])
    return LineaDeTiempo.del_run(run, escena=escena, idioma="en"), wavs


# ------------------------------------------------------------------------------------------ la narración
def test_la_narracion_pone_cada_lamina_donde_dice_la_linea_de_tiempo(tmp_path):
    linea, wavs = linea_con_tono(tmp_path / "run")
    hecho = audio.narracion(linea, wavs, tmp_path / "narracion.wav", normaliza=False)
    x = muestras_de(hecho["archivo"])
    # Dura exactamente lo que el GUION (a la muestra), no lo que sumen los wav.
    assert len(x) == round(linea.total * MUESTRAS)
    assert hecho["duracion_s"] == pytest.approx(linea.total, abs=1e-3)
    # La intro, la pausa y la cola callan; cada lámina suena en su tramo. Se mide dejando 50 ms en cada borde.
    fin_1, inicio_2 = linea.hueco(0)
    silencios = [(0, linea.intro), (fin_1, inicio_2), (linea.inicio[1] + linea.tramos[1], linea.total)]
    voces = [(linea.inicio[k], linea.inicio[k] + linea.tramos[k]) for k in range(2)]
    for a, b in silencios:
        assert rms_db(x, a + 0.05, b - 0.05) < -80, f"suena algo en el silencio {a}-{b}"
    for a, b in voces:
        assert rms_db(x, a + 0.05, b - 0.05) > -12, f"no suena la lámina en {a}-{b}"
    assert not hecho["normalizada"]


def test_control_otra_pausa_declarada_mueve_la_segunda_lamina(tmp_path):
    """Si la pausa no saliera del perfil del canal, cambiarla no movería nada."""
    corta, wavs = linea_con_tono(tmp_path / "a", pausas={"intro_s": 1.0, "entre_partes_s": 0.5, "cola_s": 1.5})
    x = muestras_de(audio.narracion(corta, wavs, tmp_path / "a.wav", normaliza=False)["archivo"])
    larga, wavs_l = linea_con_tono(tmp_path / "b")
    y = muestras_de(audio.narracion(larga, wavs_l, tmp_path / "b.wav", normaliza=False)["archivo"])
    # A los 12,5 s: con la pausa de 0,5 s ya habla la lámina 2; con la de 2 s (la del perfil) aún es la pausa.
    assert rms_db(x, 12.3, 12.7) > -12
    assert rms_db(y, 12.3, 12.7) < -80
    assert len(x) < len(y)


def test_sin_pausas_declaradas_no_hay_linea_de_tiempo_y_se_para():
    """El control de la regla: el estudio no pone las pausas. Sin ellas, para y dice qué escribir."""
    escena = escena_prueba()
    del escena["pausas"]
    with pytest.raises(ajustes.ErrorDeAjustes, match="pausas.intro_s"):
        ajustes.valida_bloque(escena)


def test_con_musica_la_voz_entra_normalizada(tmp_path):
    linea, wavs = linea_con_tono(tmp_path / "run")
    for wav, lam in zip(wavs, LAMINAS_PRUEBA):
        tono(wav, lam["dura"], amplitud=0.02)  # una voz muy baja: -37 dBFS de pico
    cruda = musica.medicion(audio.narracion(linea, wavs, tmp_path / "cruda.wav", normaliza=False)["archivo"])
    norm = musica.medicion(audio.narracion(linea, wavs, tmp_path / "norm.wav", normaliza=True)["archivo"])
    assert norm["lufs"] > cruda["lufs"] + 10, (cruda, norm)
    assert norm["lufs"] == pytest.approx(-16, abs=2.5), "el objetivo de la voz de lib/musica.py (NORMA_DE_LA_VOZ)"


# ------------------------------------------------------------------------------------------ el lecho
CFG_LECHO = {"volumen_db": -6, "umbral_ducking": 0.05, "ratio_ducking": 8, "ataque_ms": 20, "suelta_ms": 500}


def _voz_a_ratos(ruta: Path) -> Path:
    """Seis segundos: calla, habla (un tono fuerte de 1 kHz) de 2 a 4 s, calla."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000:duration=2"]
        + ["-filter_complex", "[0:a]volume=0.8,adelay=2000,apad=whole_dur=6[o]", "-map", "[o]", "-ac", "1", str(ruta)],
        check=True,
    )
    return ruta


def _lecho_de_prueba(ruta: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=6"]
        + ["-af", "volume=0.5", "-ac", "2", str(ruta)],
        check=True,
    )
    return ruta


def test_el_lecho_se_aparta_cuando_habla_la_voz(tmp_path):
    voz, lecho = _voz_a_ratos(tmp_path / "voz.wav"), _lecho_de_prueba(tmp_path / "lecho.wav")
    hecho = audio.mezcla_lecho(voz, lecho, tmp_path / "apartado.wav", CFG_LECHO, 6.0)
    x = muestras_de(hecho["archivo"], canales=2)
    callada, hablando = rms_db(x, 0.5, 1.5), rms_db(x, 2.7, 3.7)
    assert callada - hablando > 6, f"el lecho no se aparta: {callada:.1f} dB callada, {hablando:.1f} dB hablando"
    assert hecho["duracion_s"] == pytest.approx(6.0, abs=0.01)


def test_control_sin_compresor_el_lecho_no_se_aparta(tmp_path):
    """Con ratio 1 el compresor no hace nada: la medida de arriba tiene que dejar de ver la diferencia."""
    voz, lecho = _voz_a_ratos(tmp_path / "voz.wav"), _lecho_de_prueba(tmp_path / "lecho.wav")
    hecho = audio.mezcla_lecho(voz, lecho, tmp_path / "apartado.wav", {**CFG_LECHO, "ratio_ducking": 1}, 6.0)
    x = muestras_de(hecho["archivo"], canales=2)
    assert abs(rms_db(x, 0.5, 1.5) - rms_db(x, 2.7, 3.7)) < 1


def _vuelta_tras_la_voz(tmp_path: Path, suelta_ms: float, nombre: str) -> float:
    """dB a los que está el lecho justo después de callar la voz (4,05-4,2 s), frente a antes de hablar (0,5-1,5 s)."""
    voz, lecho = _voz_a_ratos(tmp_path / "voz.wav"), _lecho_de_prueba(tmp_path / "lecho.wav")
    cfg = {**CFG_LECHO, "suelta_ms": suelta_ms}
    x = muestras_de(audio.mezcla_lecho(voz, lecho, tmp_path / nombre, cfg, 6.0)["archivo"], canales=2)
    return rms_db(x, 4.05, 4.2) - rms_db(x, 0.5, 1.5)


def test_la_suelta_del_canal_decide_cuanto_tarda_el_lecho_en_volver(tmp_path):
    """F6.5b: la suelta era 500 ms fija; la del canal llega al compresor. Con 1,2 s (la del v3 de la bici) el lecho
    sigue abajo 50-200 ms después de callar la voz (-7,3 dB medidos); con 50 ms ya ha vuelto (0,0)."""
    larga = _vuelta_tras_la_voz(tmp_path, 1200, "larga.wav")
    corta = _vuelta_tras_la_voz(tmp_path, 50, "corta.wav")
    assert corta > -1, f"con 50 ms de suelta el lecho tendría que haber vuelto: {corta:.1f} dB"
    assert larga < -5, f"con 1200 ms de suelta el lecho tendría que seguir abajo: {larga:.1f} dB"


def test_control_la_misma_suelta_da_la_misma_vuelta(tmp_path):
    """Sin esto, la diferencia de arriba podría ser ruido de la medida y no la suelta."""
    a = _vuelta_tras_la_voz(tmp_path, 500, "a.wav")
    b = _vuelta_tras_la_voz(tmp_path, 500, "b.wav")
    assert a == pytest.approx(b, abs=0.01)


def _video_bajo(ruta: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=4"]
        + ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4"]
        + ["-filter_complex", "[1:a]volume=0.02[a]", "-map", "0:v", "-map", "[a]"]
        + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(ruta)],
        check=True,
    )
    return ruta


def test_la_normalizacion_final_llega_al_objetivo_del_estudio_sin_tocar_la_imagen(tmp_path):
    cfg = _cfg_del_estudio()
    entrada = _video_bajo(tmp_path / "bajo.mp4")
    antes = musica.medicion(entrada)
    medido = audio.normaliza_video(entrada, tmp_path / "final.mp4", cfg)
    # Control: el de entrada está lejos del objetivo; el de salida, en él (± 1,5 LU) y bajo el techo.
    assert abs(antes["lufs"] - cfg["objetivo_lufs"]) > 10
    assert medido["lufs"] == pytest.approx(cfg["objetivo_lufs"], abs=1.5)
    assert medido["techo"]["cumple"] is True
    # Un vídeo que ya cumplía sale de una sola pasada, sin bajar la ganancia: igual que antes de la fila 253.
    assert (medido["techo"]["pasadas"], medido["techo"]["ganancia_bajada_db"]) == (1, 0.0)
    assert _md5_de_la_imagen(tmp_path / "final.mp4") == _md5_de_la_imagen(entrada), "la imagen no se recodifica"


def _cfg_del_estudio() -> dict:
    base = config.base_del_estudio()["produccion"]["lecho_musical"]
    return {"objetivo_lufs": base["objetivo_lufs"], "pico_max_dbtp": base["pico_max_dbtp"]}


# Una ráfaga de 80 ms cada medio segundo, sobre un fondo 20 dB más bajo.
RAFAGAS = "volume='if(lt(mod(t,0.5),0.08),1,0.1)':eval=frame"


def _video_que_el_aac_saca_del_techo(ruta: Path) -> Path:
    """Ráfagas de ruido blanco con semilla fija: con una sola pasada, el AAC deja el pico en −0,81 dBTP (03-10)."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=160x90:r=24:d=6"]
        + ["-f", "lavfi", "-i", "anoisesrc=d=6:c=white:r=48000:a=0.6:s=11," + RAFAGAS]
        + ["-map", "0:v", "-map", "1:a", "-ac", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p"]
        + ["-c:a", "aac", "-b:a", "192k", str(ruta)],
        check=True,
    )
    return ruta


def test_el_techo_se_mide_sobre_el_aac_y_se_corrige(tmp_path):
    """Fila 253: «Blue» salió a −1,02 dBTP con el objetivo en −1,5, porque el AAC sube el pico después del limitador."""
    cfg = _cfg_del_estudio()
    medido = audio.normaliza_video(_video_que_el_aac_saca_del_techo(tmp_path / "rafagas.mp4"), tmp_path / "f.mp4", cfg)
    assert medido["techo"]["medido_dbtp"] <= cfg["pico_max_dbtp"]
    assert medido["techo"]["pasadas"] >= 2
    assert medido["techo"]["ganancia_bajada_db"] > 0
    assert medido["lufs"] == pytest.approx(cfg["objetivo_lufs"], abs=1.5)


def test_control_con_una_sola_pasada_el_aac_saca_el_pico_del_objetivo(tmp_path, monkeypatch):
    """Sin la corrección, la misma señal se pasa del objetivo: la prueba de arriba sabe fallar."""
    monkeypatch.setattr(audio, "PASADAS_DEL_TECHO", 1)
    cfg = _cfg_del_estudio()
    medido = audio.normaliza_video(_video_que_el_aac_saca_del_techo(tmp_path / "rafagas.mp4"), tmp_path / "f.mp4", cfg)
    assert medido["techo"]["medido_dbtp"] > cfg["pico_max_dbtp"]
    assert medido["techo"]["pasadas"] == 1


def test_sin_margen_la_cadena_es_la_de_siempre():
    """La primera pasada no cambia la cadena: un vídeo que ya cumplía sale idéntico. Con margen, baja la ganancia."""
    cfg = {"objetivo_lufs": -14.0, "pico_max_dbtp": -1.5}
    assert "alimiter=limit=0.8414:level=disabled,aresample=48000" in musica.filtro_de_nivel_final(cfg)
    assert "alimiter=limit=0.8414:level=disabled,volume=-1.00dB,aresample" in musica.filtro_de_nivel_final(cfg, 1.0)


def _md5_de_la_imagen(video: Path) -> list[str]:
    """El md5 de cada fotograma de la IMAGEN (sin el audio, que sí cambia al normalizar)."""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-map", "0:v:0", "-f", "framemd5", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [linea.rsplit(",", 1)[1].strip() for linea in r.stdout.splitlines() if linea and not linea.startswith("#")]


# ------------------------------------------------------------------------------------------ la biblioteca
def test_toda_la_biblioteca_del_estudio_tiene_su_procedencia():
    """Cada fichero de `datos/escena/` tiene fuente, licencia, url y el sha256 que tiene de verdad."""
    # Las fuentes van en woff2 y, desde F7.10, también en ttf: la tinta lee los contornos de una ttf con fontTools.
    carpetas = ((config.ESCENA_SFX_DIR, ("*.mp3",)), (config.ESCENA_FUENTES_DIR, ("*.woff2", "*.ttf")))
    for carpeta, extensiones in carpetas:
        creditos = audio.lee_creditos(carpeta)
        ficheros = sorted(p.name for ext in extensiones for p in carpeta.glob(ext))
        assert ficheros and sorted(creditos) == ficheros, f"{carpeta}: {ficheros} frente a {sorted(creditos)}"
        for nombre in ficheros:
            ficha = creditos[nombre]
            assert ficha["fuente"] and ficha["licencia"] and ficha["url"].startswith("https://"), nombre
            assert audio._sha256(carpeta / nombre) == ficha["sha256"], nombre


def _biblioteca_falsa(tmp_path: Path, monkeypatch) -> Path:
    """Una copia de la biblioteca de efectos en una carpeta temporal, para estropearla sin tocar la de verdad."""
    copia = tmp_path / "sfx"
    shutil.copytree(config.ESCENA_SFX_DIR, copia)
    monkeypatch.setattr(config, "ESCENA_SFX_DIR", copia)
    return copia


def test_los_efectos_y_la_fuente_van_al_run_con_su_procedencia_y_en_pistas_que_no_se_pisan(tmp_path):
    run = tmp_path / "run"
    sonidos = [
        {"nombre": "pop", "t": 0.1, "vol": 0.2},
        {"nombre": "whoosh", "t": 0.2, "vol": 0.3},  # a la vez que el pop: otra pista
        {"nombre": "pop", "t": 2.0, "vol": 0.2},  # ya libre la primera: la reutiliza
        {"nombre": "chime", "t": 4.97, "vol": 0.2},  # empezaría tras el final
    ]
    css = "@font-face { src: url(assets/fuentes/fredoka-latin-700-normal.woff2); }"
    hecho = audio.biblioteca(run, sonidos, css, total=5.0)
    assert [(a["src"], a["pista"]) for a in hecho["audios"]] == [
        ("assets/sfx/pop.mp3", 11),
        ("assets/sfx/whoosh.mp3", 12),
        ("assets/sfx/pop.mp3", 11),
    ]
    assert hecho["descartados"] and "chime" in hecho["descartados"][0]
    assert hecho["audios"][0]["d"] == pytest.approx(0.72, abs=0.01), "la duración del fichero, medida"
    assert set(hecho["assets"]) == {
        "assets/sfx/pop.mp3",
        "assets/sfx/whoosh.mp3",
        "assets/fuentes/fredoka-latin-700-normal.woff2",
    }
    informe = provenance.sync(run, verbose=False)
    assert informe["cuadra"], informe
    assert informe["por_tipo"] == {"fuente": 1, "sonido": 2}
    for a in provenance.read_ledger(run)["assets"]:
        assert a["fuente"] and a["licencia"] and a["url"].startswith("https://"), a["id"]
        assert a["modelo"].startswith("no aplica"), "un efecto o una fuente no entran en la declaración de IA"
    assert json.loads((run / "biblioteca" / provenance.LIBRARY_RECORDS_FILENAME).read_text(encoding="utf-8"))


def test_control_un_efecto_copiado_sin_su_registro_no_cuadra(tmp_path):
    run = tmp_path / "run"
    audio.biblioteca(run, [{"nombre": "pop", "t": 0.1, "vol": 0.2}], "", total=5.0)
    (run / "biblioteca" / provenance.LIBRARY_RECORDS_FILENAME).unlink()
    informe = provenance.sync(run, verbose=False)
    assert not informe["cuadra"] and informe["sin_registrar"] == ["biblioteca/sfx/pop.mp3"]


def test_una_segunda_pasada_no_deja_lo_que_el_episodio_ya_no_usa(tmp_path):
    run = tmp_path / "run"
    audio.biblioteca(run, [{"nombre": "pop", "t": 0.1, "vol": 0.2}, {"nombre": "chime", "t": 1, "vol": 0.2}], "", 5.0)
    audio.biblioteca(run, [{"nombre": "pop", "t": 0.1, "vol": 0.2}], "", 5.0)
    assert sorted(p.name for p in (run / "biblioteca" / "sfx").iterdir()) == ["pop.mp3"]


def test_control_un_efecto_que_no_esta_en_la_biblioteca_para(tmp_path):
    with pytest.raises(audio.ErrorDeAudio, match="no está en la biblioteca"):
        audio.biblioteca(tmp_path / "run", [{"nombre": "trueno", "t": 0.1, "vol": 0.2}], "", total=5.0)


def test_control_un_efecto_sin_entrada_en_creditos_para(tmp_path, monkeypatch):
    copia = _biblioteca_falsa(tmp_path, monkeypatch)
    shutil.copy2(copia / "pop.mp3", copia / "nuevo.mp3")
    with pytest.raises(audio.ErrorDeAudio, match="no tiene"):
        audio.biblioteca(tmp_path / "run", [{"nombre": "nuevo", "t": 0.1, "vol": 0.2}], "", total=5.0)


def test_control_un_efecto_cambiado_sin_actualizar_su_entrada_para(tmp_path, monkeypatch):
    copia = _biblioteca_falsa(tmp_path, monkeypatch)
    (copia / "pop.mp3").write_bytes((copia / "pop.mp3").read_bytes() + b"\x00")
    with pytest.raises(audio.ErrorDeAudio, match="ha cambiado"):
        audio.biblioteca(tmp_path / "run", [{"nombre": "pop", "t": 0.1, "vol": 0.2}], "", total=5.0)


def test_control_una_fuente_que_no_esta_en_la_biblioteca_para(tmp_path):
    css = "@font-face { src: url('assets/fuentes/comic-sans.woff2'); }"
    assert audio.fuentes_del_css(css) == ["comic-sans.woff2"]
    with pytest.raises(audio.ErrorDeAudio, match="comic-sans"):
        audio.biblioteca(tmp_path / "run", [], css, total=5.0)


def test_control_con_el_control_de_musica_mezcla_el_lecho_sale_corto(tmp_path):
    """La razón de remuestrear y rellenar la señal de control: sin eso, la rama apartada dura menos que el lecho."""
    voz, lecho = _voz_a_ratos(tmp_path / "voz.wav"), _lecho_de_prueba(tmp_path / "lecho.wav")
    corto = tmp_path / "corto.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(lecho), "-i", str(voz), "-filter_complex"]
        + [f"[1:a]{musica.NORMA_DE_LA_VOZ}[c];[0:a]volume=-6dB[l];[l][c]{musica.filtro_de_ducking(CFG_LECHO)}[o]"]
        + ["-map", "[o]", str(corto)],
        check=True,
    )
    assert audio.get_audio_duration(str(corto)) < 5.5
