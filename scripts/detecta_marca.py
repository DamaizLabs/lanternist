r"""El detector gratuito de la marca de IA de Lanternist (OC1.5; medida 2.1 del Código de buenas prácticas).

    .venv\Scripts\python scripts\detecta_marca.py <fichero> [--report salida.json] [--cpu]

Busca en un vídeo, una imagen o un audio las tres capas de la marca: el manifiesto C2PA, la marca de agua de Video Seal
y la de AudioSeal. Imprime una línea por capa y un veredicto, en inglés llano. Corre en local y sin red, en la GPU si la
hay o en la CPU (`--cpu` la fuerza). Con `--report`, deja el resultado firmado con la clave local de esta instalación:
el sha256 del fichero, el detector, la hora UTC, los resultados y el veredicto (sub-medida 2.1.2).

Código de salida: 0 si encuentra la marca de Lanternist en alguna capa, 1 si no, y 2 si no ha podido mirar.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import marca_ia  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    # Como `lib/config.py` en el pipeline: la consola de Windows no es UTF-8, y los mensajes llevan tildes y «…».
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Detects the Lanternist AI mark in a video, image or audio file.")
    parser.add_argument("file", help="the file to check")
    parser.add_argument("--report", help="write the signed result to this JSON file")
    parser.add_argument("--cpu", action="store_true", help="run on the CPU even if there is a GPU")
    args = parser.parse_args(argv)
    try:
        resultado = marca_ia.detecta(args.file, informe=args.report, cpu=args.cpu)
    except marca_ia.ErrorDeMarca as error:
        print(f"[FAIL] {error}")
        return 2
    except Exception as error:  # noqa: BLE001 — cualquier otro fallo es «no he podido mirar», nunca «no marcado» (R4)
        print(f"[FAIL] unexpected error, the file was not checked: {type(error).__name__}: {error}")
        return 2
    print(marca_ia.veredicto(resultado))
    if args.report:
        print(f"Signed report: {args.report}")
    return 0 if marca_ia.de_lanternist(resultado) else 1


if __name__ == "__main__":
    sys.exit(main())
