"""Un canal ficticio y un run de prueba para las etapas del motor de escena en el pipeline (F6.2d).

Nada de esto toca los canales de verdad: el canal vive en una carpeta temporal, con el perfil del canal ficticio de
las pruebas (`canal-prueba/perfil.json`) más lo que el pipeline le pide además del bloque `escena` (sus subtítulos y
su música), y el run lleva lo que dejarían las etapas de antes: los wav, la alineación, el catálogo de activos y la
procedencia de todo ello.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from utiles_activos import registro_de_qwen
from utiles_escena import CATALOGO_PRUEBA, CSS_PRUEBA, PERFIL_PRUEBA, crea_run, dibuja_assets

from lib import config, provenance

AQUI = Path(__file__).parent
ESCENAS = AQUI / "canal-prueba" / "escenas"
# Lo que el pipeline lee del bloque `subtitulos` de un canal (`lib/subtitulos.ajustes`): si lleva `.srt`. El resto es
# el aspecto del karaoke quemado del motor de láminas (retirado en F6.7), que el perfil sigue declarando
# (`lib/subtitulos.py → DEL_CANAL`).
SUBTITULOS_PRUEBA = {
    "activos": True,
    "srt": True,
    "fuente": "sans",
    "cuerpo": 60,
    "max_palabras_por_linea": 12,
    "margen_inferior_px": 150,
    "margen_lateral_px": 200,
    "traducciones": [],
    "personajes": {},
}
# Una fuente de la biblioteca del estudio, pedida por el CSS del canal como la pediría uno de verdad.
FUENTE_PRUEBA = "fredoka-latin-700-normal.woff2"
CSS_CON_FUENTE = (
    CSS_PRUEBA.read_text(encoding="utf-8")
    + f'\n@font-face {{ font-family: "Prueba"; src: url(assets/fuentes/{FUENTE_PRUEBA}) format("woff2"); }}\n'
)


def perfil_de_prueba(*, pausas: dict | None = None, musica: bool = False) -> dict:
    perfil = json.loads(PERFIL_PRUEBA.read_text(encoding="utf-8"))
    perfil["subtitulos"] = dict(SUBTITULOS_PRUEBA)
    perfil["musica"] = {"activa": musica}
    if pausas is not None:
        perfil["escena"]["pausas"] = pausas
    return perfil


def canal_de_prueba(carpeta: Path, perfil: dict | None = None) -> Path:
    """Un canal ficticio en `carpeta`: su `perfil.json` y su CSS con una fuente de la biblioteca."""
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "perfil.json").write_text(json.dumps(perfil or perfil_de_prueba(), ensure_ascii=False), encoding="utf-8")
    (carpeta / "escena").mkdir(exist_ok=True)
    (carpeta / "escena" / "estilo.css").write_text(CSS_CON_FUENTE, encoding="utf-8")
    return carpeta


def guion_en_el_canal(canal: Path, run_id: str, plantilla: str) -> Path:
    """Copia el guion de escena de prueba `plantilla` (`canal-prueba/escenas/<plantilla>.py`) al sitio del episodio."""
    destino = config.guion_de_escena(canal, run_id) / config.ESCENA_GUION
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ESCENAS / f"{plantilla}.py", destino)
    return destino


def prepara_run(run: Path, laminas: list[dict], *, con_registro: bool = True) -> Path:
    """Lo que dejarían las etapas anteriores: slides.json, wav y alineación (crea_run), el catálogo de activos con sus
    imágenes y la procedencia de las voces y de los recortes. `con_registro=False` deja los recortes sin ella."""
    crea_run(run, laminas)
    registros_voz = [
        {
            "file": str(w),
            "motor": "orpheus",
            "paquete": "llama.cpp (prueba)",
            "modelo": "Orpheus TTS 3B (prueba)",
            "licencia": "Apache-2.0",
            "origen": "generado en local con orpheus",
        }
        for w in sorted((run / "audio").glob("slide-*.wav"))
    ]
    provenance.anade_registros(run / "audio" / provenance.VOICE_RECORDS_FILENAME, registros_voz)
    img = config.activos_del_run(run) / "img"
    img.mkdir(parents=True, exist_ok=True)
    dibujos = dibuja_assets(run.parent / f"{run.name}-dibujos")
    registros = []
    for rel, origen in dibujos.items():
        if not rel.startswith("assets/img/"):
            continue
        destino = img / Path(rel).name
        shutil.copy2(origen, destino)
        registros.append(registro_de_qwen(destino))
    shutil.rmtree(run.parent / f"{run.name}-dibujos")
    if con_registro:
        provenance.anade_registros(img / provenance.IMAGE_RECORDS_FILENAME, registros)
    (config.activos_del_run(run) / "catalogo.json").write_text(
        json.dumps({"imagenes": CATALOGO_PRUEBA}, ensure_ascii=False), encoding="utf-8"
    )
    return run


def snapshot_falso(llamadas: list):
    """Un `render.snapshot` sin Chrome ni GPU: un PNG gris por instante, con el nombre que da HyperFrames."""
    from PIL import Image

    def snapshot(carpeta, dir_log, tiempos, salida):
        llamadas.append({"carpeta": Path(carpeta), "tiempos": list(tiempos)})
        salida = Path(salida)
        salida.mkdir(parents=True, exist_ok=True)
        for i, _ in enumerate(tiempos):
            Image.new("RGB", (192, 108), (128, 128, 128)).save(salida / f"frame-{i:03d}.png")
        return sorted(salida.glob("frame-*.png"))

    return snapshot


def render_falso(llamadas: list):
    """Un `render.render` sin Chrome ni GPU: un MP4 negro de la duración del GUION con las pistas enteras de la
    composición (la narración y, si la hay, la música) mezcladas, como las mezclaría HyperFrames."""
    from lib.escena import compone

    def render(carpeta, salida, dir_log, workers=None):
        carpeta, salida = Path(carpeta), Path(salida)
        llamadas.append({"carpeta": carpeta, "salida": salida})
        guion = compone.lee_guion(carpeta / "index.html")
        salida.parent.mkdir(parents=True, exist_ok=True)
        pistas = sorted((carpeta / "assets" / "audio").glob("*.wav"))
        entradas = [a for p in pistas for a in ("-i", str(p))]
        mezcla = "".join(f"[{i + 1}:a]" for i in range(len(pistas))) + f"amix=inputs={len(pistas)}:normalize=0[a]"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=24"]
            + entradas
            + ["-filter_complex", mezcla, "-map", "0:v", "-map", "[a]", "-t", f"{guion['duracion']:.3f}"]
            + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(salida)],
            check=True,
        )
        return salida

    return render
