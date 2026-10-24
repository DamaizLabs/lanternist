"""¿El audio de un run dice lo que dice su guion? (F5.7, la puerta de mano)

El pipeline ya lo comprueba solo al cerrar cada run y lo escribe en el LEEME de `subir-al-canal/`.
Esto es lo mismo **sobre runs ya producidos**, que es lo que hacía falta para mirar atrás: los cuatro
episodios del primer canal se montaron antes de que este gate existiera y dos de ellos están públicos.

Correr:

    .venv\\Scripts\\python scripts/verifica_narracion.py                    # los runs del canal activo
    .venv\\Scripts\\python scripts/verifica_narracion.py <run_id>           # uno del canal activo
    .venv\\Scripts\\python scripts/verifica_narracion.py --canal example
    .venv\\Scripts\\python scripts/verifica_narracion.py --json informe.json

**No toca nada del run** y no gasta GPU: lee la alineación que el karaoke ya calculó y mide el
silencio con `ffmpeg`. Sale con código 0 siempre que haya podido mirar — esto informa, no bloquea
(addendum fila 152). Código 2 solo si no hay ningún run que mirar, que es un error de uso.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import CANAL_ACTIVO, CANAL_VIDEOS_DIR, CANALES_DIR  # noqa: E402
from lib.integridad_narracion import explica, revisa_run  # noqa: E402


def runs_a_mirar(args) -> list[Path]:
    """Los runs que hay que revisar, en orden. Un run es una carpeta con `slides.json`."""
    if args.run_id:
        return [CANAL_VIDEOS_DIR / args.run_id]
    base = (CANALES_DIR / args.canal / "videos") if args.canal else CANAL_VIDEOS_DIR
    return sorted(p.parent for p in base.glob("*/slides.json"))


def imprime(run: Path, informe: dict) -> None:
    faltan, sobran = informe["faltan"], informe["sobran"]
    print(f"\n=== {run.name}")
    print(
        f"    {informe['laminas_comparadas']} lámina(s) comparadas"
        + (f" con {informe['origen']}" if informe["origen"] else "")
    )
    if informe["aviso"]:
        print(f"    [AVISO] {informe['aviso']}")
    for f in faltan:
        donde = f" · en el vídeo hacia el {f['en_el_video']}" if f.get("en_el_video") else ""
        print(f"    [FALTA] lámina {f['lamina']} · segundo {f['desde_s']} de la lámina{donde}")
        print(f"            «{f['texto']}»")
        print(f"            {explica(f)}")
    for s in sobran:
        donde = f" · hacia el {s['en_el_video']}" if s.get("en_el_video") else ""
        print(f"    [SOBRA] lámina {s['lamina']} · {s['palabras']} palabras que el guion no tiene{donde}")
        print(f"            «{s['texto'][:160]}»")
        if s.get("motivo"):
            print(f"            {explica(s)}")
    for d in informe["descartados"]:
        print(f"    (no es incidencia) lámina {d['lamina']}, {d['palabras']} palabras: {explica(d)}")
    if not faltan and not sobran:
        print("    sin hallazgos")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compara el guion de un run con lo que se oye en su audio")
    parser.add_argument("run_id", nargs="?", default="", help="un run del canal activo; sin él, todos")
    parser.add_argument("--canal", default="", help="id de otro canal (por defecto, CANAL_ACTIVO del .env)")
    parser.add_argument("--json", dest="destino", default="", help="escribe el informe completo en un JSON")
    args = parser.parse_args()

    runs = runs_a_mirar(args)
    if not runs:
        canal = args.canal or CANAL_ACTIVO or "(sin canal activo)"
        print(f"[FAIL] no hay ningún run con slides.json en {canal}")
        return 2

    informes = {}
    for run in runs:
        informe = revisa_run(run)
        informes[run.name] = informe
        imprime(run, informe)

    todas = [f for i in informes.values() for f in i["faltan"]]
    sobran = sum(len(i["sobran"]) for i in informes.values())
    # **Confirmado contra el audio y hallazgo de texto no son lo mismo, y el resumen deja de
    # mezclarlos** (F5.9). Decir «2 tramos de narración que no se oyen» cuando ninguno se ha medido
    # es afirmar más de lo que se sabe: el 18-09 este run archivado —sin su `.wav` en el árbol—
    # reportó dos faltas que el 15-09 se habían comprobado a mano contra el audio y **sí estaban
    # dichas**. El detalle de cada una ya lo decía («nadie lo ha confirmado»); la línea final no.
    sin_confirmar = [f for f in todas if f.get("veredicto") == "sin_audio"]
    confirmadas = len(todas) - len(sin_confirmar)
    resumen = f"\n{len(runs)} run(s) · {confirmadas} tramo(s) de narración que no se oyen"
    if sin_confirmar:
        resumen += f" · {len(sin_confirmar)} hallazgo(s) de texto SIN confirmar (falta el audio del run)"
    print(f"{resumen} · {sobran} sobrante(s)")
    if args.destino:
        Path(args.destino).write_text(json.dumps(informes, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"informe completo: {args.destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
