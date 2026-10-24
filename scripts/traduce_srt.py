"""Traduce el `.srt` de un run en dos pasos: saca sus cues y escribe la traducción que hace Claude (F7.11, fila 265).

Correr, con el canal del run en `CANAL_ACTIVO`, después de la etapa `alinea`:

    .venv\\Scripts\\python scripts/traduce_srt.py saca --run-id <run_id>
    .venv\\Scripts\\python scripts/traduce_srt.py escribe --run-id <run_id> --idioma es --traduccion <cues.es.json>

1. `saca` deja en el run `subtitulos/cues.<origen>.json`: cada cue del `.srt` de origen con su número, sus
   tiempos y su texto, y el sha256 del `.srt`.
2. Claude, en la sesión de `produce-semana`, guarda ese JSON con otro nombre (`cues.es.json`) y cada `texto` traducido.
3. `escribe` lo comprueba y escribe `subir-al-canal/subtitulos.<idioma>.srt` con los mismos tiempos. Si algo falla no
   escribe nada y lista todo lo que hay que corregir.

Qué se comprueba y qué exige después la subida está en `lib/traduccion.py`. El idioma de origen es el de los
subtítulos del canal (`idioma.subtitulos`), y los idiomas a los que se traduce los declara su perfil
(`subtitulos.traducciones`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Traduce el .srt de un run: saca sus cues o escribe la traducción")
    ordenes = parser.add_subparsers(dest="orden", required=True)
    p_saca = ordenes.add_parser("saca", help="escribe en el run los cues del .srt de origen, para traducirlos")
    p_saca.add_argument("--run-id", required=True)
    p_escribe = ordenes.add_parser("escribe", help="comprueba la traducción y escribe subtitulos.<idioma>.srt")
    p_escribe.add_argument("--run-id", required=True)
    p_escribe.add_argument("--idioma", required=True, help="código de dos letras, el del perfil (p. ej. es)")
    p_escribe.add_argument("--traduccion", required=True, help="el JSON de `saca` con cada texto traducido")
    args = parser.parse_args(argv)

    from lib import config, subtitulos, traduccion

    if config.CANAL_ERROR:
        raise SystemExit(f"[FAIL] el canal no está usable: {config.CANAL_ERROR}")
    run_dir = config.CANAL_VIDEOS_DIR / args.run_id
    if not run_dir.is_dir():
        raise SystemExit(f"[FAIL] no existe el run {run_dir} en el canal {config.CANAL_ACTIVO}")

    try:
        if args.orden == "saca":
            ruta = traduccion.saca(run_dir, config.CANAL_PERFIL, origen=config.SUBTITLE_LANG)
            print(f"[OK] cues de subtitulos.{config.SUBTITLE_LANG}.srt para traducir: {ruta}")
            return 0
        hecho = traduccion.escribe(
            run_dir,
            config.CANAL_PERFIL,
            run_id=args.run_id,
            idioma=args.idioma,
            origen=config.SUBTITLE_LANG,
            idioma_de_la_declaracion=config.NARRATION_LANG,
            traduccion=args.traduccion,
        )
    except (traduccion.ErrorDeTraduccion, subtitulos.SubtitulosError) as error:
        raise SystemExit(f"[FAIL] {error}") from None
    print(f"[OK] {hecho['cues']} cues en {hecho['srt']}, con los tiempos de subtitulos.{config.SUBTITLE_LANG}.srt")
    if not hecho["conteo"]["cuadra"]:
        print("[AVISO] el registro de procedencia del run no cuadra (ver arriba): la subida no seguirá así")
    return 0


if __name__ == "__main__":
    sys.exit(main())
