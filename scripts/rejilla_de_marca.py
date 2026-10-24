r"""Las pasadas del avatar y el banner de un canal nuevo, lado a lado, para elegir su semilla (`crea-canal`, paso 3).

Correr:
  .venv\Scripts\python scripts/rejilla_de_marca.py --guarda --canal <id> --semilla 11 --etiqueta <canal>
  .venv\Scripts\python scripts/rejilla_de_marca.py --carpetas experimentos/marca-<c>-s11 experimentos/marca-<c>-s22

## Por qué existe

La semilla de un canal nuevo no tiene defecto: se elige viendo lo que dibuja (1234 era la del primer canal, y el segundo
la heredó sin medirla). En `crea-canal` se elige al generar la marca, pero `canal.py --generar --rehacer` borra todo lo
que había en `canales/<id>/marca/` antes de generar con otra semilla. Así que cada pasada se **guarda** fuera
(`--guarda`, que la copia a `experimentos/marca-<etiqueta>-s<semilla>/`) y luego se **comparan** en una rejilla, que es
como el usuario compara imágenes: cada pieza en una fila y cada semilla en una columna. La página lleva las imágenes
dentro.

No genera nada ni toca el perfil: la semilla elegida la escribe quien lleva la skill, con su motivo.
"""

from __future__ import annotations

import argparse
import html
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


class RejillaError(RuntimeError):
    pass


def guarda(canal: str, semilla: int, etiqueta: str, raiz: Path = RAIZ) -> Path:
    origen = raiz / "canales" / canal / "marca"
    pngs = sorted(origen.rglob("*.png")) if origen.exists() else []
    if not pngs:
        raise RejillaError(f"no hay imágenes en {origen}: genera antes con `canal.py --generar --seed {semilla}`")
    destino = raiz / "experimentos" / f"marca-{etiqueta}-s{semilla}"
    if destino.exists():
        raise RejillaError(f"ya existe {destino}: esa pasada ya está guardada")
    for png in pngs:
        copia = destino / png.relative_to(origen)
        copia.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(png, copia)
    return destino


def rejilla(carpetas: list[Path], destino: Path) -> Path:
    from lib.pagina_local import imagen_embebida

    for c in carpetas:
        if not c.is_dir():
            raise RejillaError(f"no existe la carpeta {c}")
    piezas = sorted({p.relative_to(c).as_posix() for c in carpetas for p in c.rglob("*.png")})
    if not piezas:
        raise RejillaError("ninguna de las carpetas tiene imágenes")
    e = html.escape
    cabecera = "".join(f"<th>{e(c.name)}</th>" for c in carpetas)
    filas = []
    for pieza in piezas:
        celdas = []
        for c in carpetas:
            png = c / pieza
            celdas.append(
                f"<td><img src='{imagen_embebida(png, 640, 85)}' alt=''></td>" if png.exists() else "<td>falta</td>"
            )
        filas.append(f"<tr><th>{e(pieza)}</th>{''.join(celdas)}</tr>")
    estilo = (
        ":root{--fondo:#fbfaf7;--texto:#1d1d1b;--linea:#ddd}"
        "@media (prefers-color-scheme: dark){:root{--fondo:#161614;--texto:#ecebe6;--linea:#333}}"
        "body{background:var(--fondo);color:var(--texto);font:15px/1.45 system-ui,sans-serif;margin:0;padding:16px}"
        "table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--linea);padding:8px;"
        "vertical-align:top;text-align:left}img{width:100%;max-width:640px;border-radius:6px}"
    )
    doc = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Marca: semillas</title>'
        f"<style>{estilo}</style></head><body><h1>La marca con cada semilla</h1>"
        f"<table><tr><th>pieza</th>{cabecera}</tr>{''.join(filas)}</table></body></html>"
    )
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(doc, encoding="utf-8")
    return destino


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guarda y compara las pasadas de la marca de un canal nuevo")
    parser.add_argument("--guarda", action="store_true", help="copia la marca actual del canal fuera de marca/")
    parser.add_argument("--canal")
    parser.add_argument("--semilla", type=int)
    parser.add_argument("--etiqueta", default="canal-nuevo")
    parser.add_argument("--carpetas", nargs="+", type=Path, help="las pasadas guardadas, una por semilla")
    parser.add_argument("--salida", type=Path, help="por defecto experimentos/marca-<etiqueta>-rejilla.html")
    parser.add_argument("--no-abrir", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.guarda:
            if not args.canal or args.semilla is None:
                raise RejillaError("--guarda necesita --canal y --semilla")
            print(f"Guardada en {guarda(args.canal, args.semilla, args.etiqueta)}")
            return 0
        if not args.carpetas:
            raise RejillaError("hacen falta --carpetas (o --guarda)")
        destino = rejilla(args.carpetas, args.salida or RAIZ / "experimentos" / f"marca-{args.etiqueta}-rejilla.html")
    except RejillaError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print(f"Página: {destino}")
    if not args.no_abrir:
        from lib.pagina_local import abre

        abre(destino)
    return 0


if __name__ == "__main__":
    sys.exit(main())
