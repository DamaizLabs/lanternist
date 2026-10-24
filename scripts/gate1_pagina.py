r"""Compone la página del gate 1 de un run, LEYENDO su `slides.json`.

Correr, con el canal en el entorno del proceso:
    $env:CANAL_ACTIVO='<id>'; .venv\Scripts\python scripts/gate1_pagina.py --run-id <run>

## Por qué lee el `slides.json` y no el informe

Porque el `slides.json` **es lo que se produce**. La versión anterior de este script parseaba
el informe de gate 1 de un episodio, y su propio docstring decía la razón por la que eso no vale: «un guion
copiado a mano es la vía por la que se aprueba una versión y se produce otra». Leer el informe tenía
exactamente ese defecto — el informe es una copia. Lo que el usuario lee aquí es, byte a byte, la
narración que va a locutar el motor.

## Qué se corrigió el 14-09-2026

El script estaba **cableado a un solo episodio de un solo canal** (la ruta de su
informe, el título del canal y hasta las cifras «191 frases» y
«~9:02» tecleadas dentro). Era una página de un solo uso disfrazada de herramienta del estudio, y
`scripts/` es capa de estudio por `doc/06`: la misma fuga que F4.9 prohíbe en `lib/`, anotada como
deuda en el addendum fila 126. Consecuencia mientras duró: el gate 1 del primer canal no tuvo página.

Ahora **no hay ningún dato de canal en este fichero**: el título, el reparto, los colores de los
personajes y las cifras salen del `slides.json` y del perfil del canal activo.
"""

import argparse
import html
import json
import re
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import CANAL_ACTIVO, CANAL_PERFIL, CANAL_VIDEOS_DIR  # noqa: E402

COPIA = (
    "navigator.clipboard.writeText(this.previousElementSibling.textContent).then(()=>{this.textContent='copiado ✓'})"
)


def _limpia(texto: str) -> str:
    """Escapa el texto y deja visibles las etiquetas emocionales como marca, no como palabra.

    Se ven a propósito: son parte de lo que el usuario aprueba —dicen dónde va a reírse el narrador— y
    en el vídeo NO se pintan (`lib/subtitulos.py` las quita antes).
    """
    escapado = html.escape(texto)
    return re.sub(r"&lt;(\w+)&gt;", r'<span class="etq">\1</span>', escapado)


def _parrafos(narracion: str) -> list[str]:
    """Parte la narración en párrafos legibles, sin tocar una coma de lo que se va a locutar."""
    frases = re.split(r"(?<=[.!?…])\s+", narracion.strip())
    parrafos, actual = [], []
    for frase in frases:
        actual.append(frase)
        if len(" ".join(actual).split()) >= 45:
            parrafos.append(" ".join(actual))
            actual = []
    if actual:
        parrafos.append(" ".join(actual))
    return parrafos


def compone(ruta_slides: Path) -> Path:
    datos = json.loads(ruta_slides.read_text(encoding="utf-8"))
    slides = datos.get("slides") or []
    perfil = CANAL_PERFIL or {}
    formato = perfil.get("formato") or {}
    ritmo = ((perfil.get("voz") or {}).get("palabras_por_segundo")) or 0

    total = sum(len(s.get("narration", "").split()) for s in slides)
    minutos = total / ritmo / 60 if ritmo else 0
    banda = formato.get("duracion_objetivo_min") or []

    personajes = ((perfil.get("subtitulos") or {}).get("personajes")) or {}
    leyenda = "".join(
        f'<span class="p" style="border-color:{html.escape(str(d.get("color", "#888")))}">{html.escape(n)}</span>'
        for n, d in personajes.items()
    )

    bloques = []
    for s in slides:
        narracion = s.get("narration", "")
        cuenta = len(narracion.split())
        es_cierre = s.get("tipo") == "cierre"
        marca = ' <span class="cierre">despedida</span>' if es_cierre else ""
        miniatura = (
            ' <span class="mini">miniatura</span>' if s.get("slide_number") == datos.get("thumbnail_lamina") else ""
        )
        bloques.append(
            f"""  <section class="bloque">
    <h2>Lámina {s.get("slide_number")}{marca}{miniatura} <span class="t">{cuenta} palabras</span></h2>
    {"".join(f"<p>{_limpia(p)}</p>" for p in _parrafos(narracion))}
    <details><summary>el prompt de su ilustración</summary>
    <p class="pr">{html.escape(s.get("image_prompt", ""))}</p></details>
  </section>"""
        )

    titulo = datos.get("title", "")
    aviso_largo = "" if len(titulo) <= 60 else f' <span class="mal">{len(titulo)} caracteres</span>'
    html_doc = f"""<!doctype html><meta charset=utf-8>
<title>Gate 1 · {html.escape(perfil.get("nombre") or CANAL_ACTIVO or "")}</title>
<style>
 body{{font:16px/1.65 Georgia,serif;margin:0 auto;padding:26px 18px 80px;
   max-width:760px;color:#241d16;background:#faf7f2}}
 h1{{font-size:24px;margin:0 0 2px}} h2{{font-size:15px;margin:0 0 10px;color:#7a6a58;font-weight:normal}}
 .g{{color:#7a6a58;font-size:14px}}
 .cifras{{display:flex;flex-wrap:wrap;gap:18px;margin:16px 0 4px;padding:12px 14px;
   background:#fff;border:1px solid #e2d9cc}}
 .cifras div{{font-size:13px;color:#7a6a58}} .cifras b{{display:block;font-size:19px;color:#241d16}}
 .titulo{{background:#fff;border:1px solid #e2d9cc;padding:12px 14px;margin:14px 0}}
 .titulo code{{font:15px/1.5 Georgia,serif}}
 button{{font:13px Georgia,serif;margin-left:10px;padding:3px 10px;cursor:pointer;
   background:#f3ece1;border:1px solid #c8b89f}}
 .bloque{{margin:26px 0;padding-top:16px;border-top:1px solid #e2d9cc}}
 .bloque p{{margin:0 0 12px}}
 .t{{float:right;font-size:12px;color:#a0917c}}
 .etq{{font-size:11px;letter-spacing:.06em;text-transform:uppercase;background:#efe6d6;
   border-radius:3px;padding:1px 6px;color:#8a6a3a}}
 .cierre,.mini{{font-size:11px;background:#e4ecdf;padding:2px 7px;border-radius:3px;
   color:#3f6b4a;text-transform:uppercase;letter-spacing:.05em}}
 .mini{{background:#efe0e6;color:#8a3a5a}}
 .mal{{color:#a3402c;font-weight:bold}}
 .p{{display:inline-block;font-size:12px;padding:1px 8px;margin-right:6px;border-left:4px solid;background:#fff}}
 details{{margin-top:8px}} summary{{font-size:12px;color:#a0917c;cursor:pointer}}
 .pr{{font-size:12.5px;color:#6b5c4a;background:#fff;padding:10px 12px;border:1px solid #e9e1d5}}
 footer{{margin-top:40px;padding-top:16px;border-top:2px solid #c8b89f;font-size:14px}}
</style>
<h1>Gate 1 · {html.escape(perfil.get("nombre") or "")}</h1>
<h2>{html.escape(ruta_slides.parent.name)}</h2>

<div class=cifras>
  <div>láminas<b>{len(slides)}</b></div>
  <div>palabras<b>{total:,}</b></div>
  <div>duración estimada<b>{minutos:.1f} min</b></div>
  <div>objetivo del canal<b>{"-".join(str(x) for x in banda)} min</b></div>
  <div>ritmo del canal<b>{ritmo} pal/s</b></div>
</div>

<div class=titulo>
  <div class=g>título — {len(titulo)} caracteres{aviso_largo}</div>
  <code>{html.escape(titulo)}</code><button onclick="{COPIA}">copiar</button>
</div>

<p class=g>Quién habla se distingue por el color del subtítulo: {leyenda}</p>

{chr(10).join(bloques)}

<footer>
<b>Esto es el gate 1 y lo firmas tú.</b> El verificador ya dio 0 fallos, pero solo mide lo que se
puede contar: longitudes, campos y palabras prohibidas. Lo que hay que leer es el criterio — que cada
ilustración represente lo que dice su narración, que el tono y el nivel sean los de tu canal y que nada
cruce sus líneas rojas.
</footer>
"""
    destino = ruta_slides.parent / "gate1.html"
    destino.write_text(html_doc, encoding="utf-8")
    return destino


def main() -> int:
    parser = argparse.ArgumentParser(description="Página del gate 1 de un run, desde su slides.json")
    parser.add_argument("--run-id", help="el run del canal activo; si no, se pasa --slides")
    parser.add_argument("--slides", type=Path, help="ruta directa a un slides.json")
    parser.add_argument("--sin-abrir", action="store_true")
    args = parser.parse_args()

    if args.slides:
        ruta = args.slides
    elif args.run_id:
        ruta = Path(CANAL_VIDEOS_DIR) / args.run_id / "slides.json"
    else:
        print("[FAIL] hace falta --run-id o --slides", file=sys.stderr)
        return 1
    if not ruta.exists():
        print(f"[FAIL] no existe {ruta}", file=sys.stderr)
        return 1

    destino = compone(ruta)
    print(destino)
    if not args.sin_abrir:
        webbrowser.open(destino.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
