r"""Voces candidatas de Kokoro para un canal nuevo, en una página para escucharlas (skill `crea-canal`, paso 4).

Correr:
  .venv\Scripts\python scripts/muestras_voz.py --listar
  .venv\Scripts\python scripts/muestras_voz.py --voces am_michael,bm_george,am_onyx+bm_lewis
      --texto-de <texto.txt> --lang a --etiqueta <canal>

## Por qué existe

La voz del estudio **se elige en Kokoro y se clona en Orpheus** (decisión 13): de Kokoro sale la voz
semilla del canal, y eso lo decide el usuario escuchando. Para los dos primeros canales las muestras se
hicieron con scripts de experimento de un solo uso. Esto es la herramienta que se repite con cada canal nuevo.

## Cómo funciona, y lo que no hace

Dos pasadas, igual que `scripts/referencia_voz.py`. La primera corre en el `.venv` del pipeline y
prepara el trabajo. La segunda corre en `.venv-voz`, el único sitio donde se importa Kokoro, **sin
red** (`HF_HUB_OFFLINE`: solo sirven las voces que ya están en la caché de Hugging Face, y `--listar`
dice cuáles).

Los audios y su página se escriben en la caché de voz, **fuera del repositorio**: ningún audio de voz
entra en el árbol del repo, aunque sea sintético (lista negra). No toca ninguna receta ni ningún perfil.
`a+b` mezcla dos voces, como la `mix_onyx_lewis`.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# El repo de Kokoro es el de `referencia_voz.py`, que es quien lo decidió: se importa, no se copia.
from referencia_voz import REPO_KOKORO  # noqa: E402

IDIOMAS = {
    "a": "inglés americano",
    "b": "inglés británico",
    "e": "español",
    "f": "francés",
    "h": "hindi",
    "i": "italiano",
    "j": "japonés",
    "p": "portugués",
    "z": "chino",
}


class MuestrasError(RuntimeError):
    pass


def voces_en_cache() -> list[str]:
    raiz = Path(os.getenv("HF_HOME", str(Path.home() / ".cache" / "huggingface"))) / "hub"
    carpeta = raiz / f"models--{REPO_KOKORO.replace('/', '--')}" / "snapshots"
    return sorted({p.stem for p in carpeta.glob("*/voices/*.pt")})


def _prepara(voces: list[str], texto: str, lang: str, speed: float, etiqueta: str) -> Path:
    from lib.config import BASE_DIR, VOICE_CACHE_DIR, VOICE_PYTHON

    disponibles = set(voces_en_cache())
    for voz in voces:
        for componente in voz.split("+"):
            if componente not in disponibles:
                raise MuestrasError(f"la voz «{componente}» no está en la caché de Kokoro; mira --listar")
            if componente[0] != lang:
                print(
                    f"  [AVISO] {componente} es de «{IDIOMAS.get(componente[0], componente[0])}» "
                    f"y el texto va con lang {lang}"
                )
    carpeta = (VOICE_CACHE_DIR / "muestras" / f"{etiqueta}-{datetime.now():%Y-%m-%d-%H%M%S}").resolve()
    if carpeta.is_relative_to(Path(BASE_DIR).resolve()):
        raise MuestrasError(f"la caché de voz apunta dentro del repo ({carpeta}): los audios viven fuera (lista negra)")
    carpeta.mkdir(parents=True, exist_ok=True)
    trabajo = carpeta / "trabajo.json"
    trabajo.write_text(
        json.dumps(
            {"voces": voces, "texto": texto, "lang_code": lang, "speed": speed, "repo_id": REPO_KOKORO},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    interprete = Path(VOICE_PYTHON)
    if not interprete.exists():
        raise MuestrasError(f"no existe el intérprete del venv de voz: {interprete}")
    proceso = subprocess.run([str(interprete), str(Path(__file__).resolve()), "--sintetiza", str(trabajo)])
    if proceso.returncode != 0:
        raise MuestrasError(f"la síntesis falló (código {proceso.returncode}); no se reintenta")
    return pagina(carpeta, etiqueta)


def _sintetiza(trabajo: Path) -> int:
    """Segunda pasada, en `.venv-voz`: no lee el `.env` ni `lib.config`, todo llega en el trabajo."""
    os.environ["HF_HUB_OFFLINE"] = "1"  # decisión 6: nada sale del PC

    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    job = json.loads(trabajo.read_text(encoding="utf-8"))
    pipe = KPipeline(lang_code=job["lang_code"], repo_id=job["repo_id"])
    resultados = []
    palabras = len(job["texto"].split())
    for voz in job["voces"]:
        trozos = [
            np.asarray(a, dtype=np.float32)
            for _, _, a in pipe(job["texto"], voice=voz.replace("+", ","), speed=job["speed"])
        ]
        if not trozos:
            raise MuestrasError(f"Kokoro no produjo audio con {voz}")
        audio = np.concatenate(trozos)
        fichero = trabajo.parent / f"{voz.replace('+', '_')}.wav"
        sf.write(fichero, audio, 24000)
        segundos = len(audio) / 24000
        resultados.append(
            {
                "voz": voz,
                "fichero": fichero.name,
                "segundos": round(segundos, 2),
                "wpm": round(palabras / segundos * 60, 1),
            }
        )
        print(f"  {voz}: {segundos:.1f} s")
    (trabajo.parent / "resultado.json").write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


def pagina(carpeta: Path, etiqueta: str) -> Path:
    e = html.escape
    trabajo = json.loads((carpeta / "trabajo.json").read_text(encoding="utf-8"))
    resultados = json.loads((carpeta / "resultado.json").read_text(encoding="utf-8"))
    filas = "".join(
        f"<div class='voz'><h3>{e(r['voz'])}</h3><audio controls preload='none' src='{e(r['fichero'])}'></audio>"
        f"<p>{r['segundos']} s · {r['wpm']} palabras por minuto</p></div>"
        for r in resultados
    )
    estilo = (
        ":root{--fondo:#fbfaf7;--texto:#1d1d1b;--suave:#666}"
        "@media (prefers-color-scheme: dark){:root{--fondo:#161614;--texto:#ecebe6;--suave:#aaa}}"
        "body{background:var(--fondo);color:var(--texto);font:15px/1.45 system-ui,sans-serif;max-width:900px;"
        "margin:0 auto;padding:16px}.voz{border-bottom:1px solid #8884;padding:8px 0}audio{width:100%}"
        "p,blockquote{color:var(--suave)}"
    )
    doc = (
        f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Voces {e(etiqueta)}</title>'
        f"<style>{estilo}</style></head><body><h1>Voces candidatas · {e(etiqueta)}</h1>"
        f"<p>Kokoro · {e(IDIOMAS.get(trabajo['lang_code'], trabajo['lang_code']))} · velocidad {trabajo['speed']}. "
        "La voz que elijas es la semilla: Orpheus la clona y le da la entonación.</p>"
        f"<blockquote>{e(trabajo['texto'])}</blockquote>{filas}</body></html>"
    )
    destino = carpeta / "pagina.html"
    destino.write_text(doc, encoding="utf-8")
    return destino


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Voces candidatas de Kokoro para un canal nuevo")
    parser.add_argument("--listar", action="store_true", help="las voces que hay en la caché local")
    parser.add_argument("--voces", help="separadas por coma; a+b mezcla dos")
    parser.add_argument("--texto")
    parser.add_argument("--texto-de", type=Path)
    parser.add_argument("--lang", default="a", help="lang_code de Kokoro (a americano, b británico, e español…)")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--etiqueta", default="canal-nuevo")
    parser.add_argument("--sintetiza", type=Path, help="INTERNO: trabajo JSON, se ejecuta en .venv-voz")
    parser.add_argument("--no-abrir", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.sintetiza:
            return _sintetiza(args.sintetiza)
        if args.listar:
            sys.stdout.reconfigure(encoding="utf-8")  # esta rama no importa lib.config, que es quien lo hace
            voces = voces_en_cache()
            for prefijo in sorted({v[0] for v in voces}):
                grupo = [v for v in voces if v[0] == prefijo]
                print(f"{IDIOMAS.get(prefijo, prefijo)} ({prefijo}): {', '.join(grupo)}")
            return 0
        texto = args.texto or (args.texto_de.read_text(encoding="utf-8").strip() if args.texto_de else "")
        if not args.voces or not texto:
            raise MuestrasError("hacen falta --voces y un texto (--texto o --texto-de)")
        destino = _prepara(
            [v.strip() for v in args.voces.split(",") if v.strip()], texto, args.lang, args.speed, args.etiqueta
        )
    except MuestrasError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print(f"Página: {destino}")
    if not args.no_abrir:
        sys.path.insert(0, str(RAIZ))
        from lib.pagina_local import abre

        abre(destino)
    return 0


if __name__ == "__main__":
    if "--sintetiza" not in sys.argv:
        sys.path.insert(0, str(RAIZ))
    sys.exit(main())
