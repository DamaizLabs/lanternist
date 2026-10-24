"""Revisión visual de las láminas de un run: el mosaico y cada lámina junto a su narración.

Correr:  .venv\\Scripts\\python scripts/revisa_laminas.py <run_id> [--no-abrir]

## Por qué existe, y lo que costó no tenerla

**El 07-09-2026 se produjo el episodio 1 de la cohorte de un canal y se rechazó al verlo.** Sus 33
láminas habían pasado todos los gates automáticos en verde:

- `lib/lineas_rojas.py` las revisó una a una y no encontró sangre.
- `scripts/verifica_guion.py` dio 0 fallos sobre el guion y sus prompts.
- `lib/miniatura.py` aprobó la miniatura con sus cuatro frenos.

Y aun así el vídeo no valía, porque **nada del pipeline comprueba que el dibujo sea la pieza de la
que habla el vídeo**. La doncella de hierro, que es un sarcófago vertical de dos metros, salió como
un baúl de sobremesa de unos 50 cm en las 15 láminas donde aparece, y ocho láminas más dibujaban
cosas que su narración no menciona: un proyector de cine, un reloj de péndulo, una torre con farol.

Los gates miden **color** y **palabras**. Nadie miraba **el dibujo**. Eso es lo que cubre esto.

## Lo que produce, y por qué son dos vistas y no una

1. **El mosaico** (`canales/<id>/revision/<run_id>/mosaico.png`): las láminas en una sola imagen,
   numeradas. Sirve
   para ver de golpe lo que una lámina suelta no enseña — que el artefacto cambia de tamaño entre
   láminas, que dos son casi idénticas, que una rompe el estilo del resto.
2. **La página** (`canales/<id>/revision/<run_id>/laminas.html`): cada lámina **junto a la
   narración que ilustra**.
   Es la comprobación que pide la skill de guion y que no se puede automatizar: «¿alguien que mire
   esta imagen sin audio adivinaría de qué se está hablando?». Se abre con doble clic, según el
   criterio del 31-08.

**Esto no aprueba nada y no es un gate.** Es lo que pone el material delante de una persona con el
mínimo esfuerzo. La decisión sigue siendo del gate 1.

## Por qué las salidas NO caen dentro del run

Lo intenté y el arnés lo paró en el primer uso: **`lib/provenance.py` cuenta como asset del run todo
medio que aparezca dentro de él**, así que el mosaico dejaba la procedencia en 71 archivos y 70
registros, y la decisión cerrada 5 **para la subida** cuando el conteo no cuadra. Un fichero de
revisión no es un asset del vídeo y no debe pedir procedencia.

Así que van a `canales/<id>/revision/<run_id>/`, fuera del run y con su regla en `.gitignore`: son
vistas regenerables, como el dashboard del descubrimiento o la página del calendario.
"""

import argparse
import html
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import CANAL_ACTIVO, CANAL_DIR, CANAL_VIDEOS_DIR  # noqa: E402

ANCHO_CELDA = 440
COLUMNAS = 5
ALTO_ROTULO = 22

ESTILO = """
:root { color-scheme: light dark; --tinta:#1c1a17; --papel:#f4f1ea; --linea:#d8d2c4;
        --acento:#8a6a2f; --apagado:#6b6459; }
@media (prefers-color-scheme: dark) { :root { --tinta:#ece7dc; --papel:#17150f;
        --linea:#3a352b; --acento:#c9a961; --apagado:#9a9285; } }
* { box-sizing:border-box; }
body { margin:0; padding:28px; background:var(--papel); color:var(--tinta);
       font:15px/1.55 Georgia,'Times New Roman',serif; }
h1 { font-size:24px; margin:0 0 4px; }
.sub { color:var(--apagado); margin:0 0 22px; }
.aviso { border-left:3px solid var(--acento); padding:10px 16px; margin:0 0 24px;
         background:rgba(138,106,47,.07); }
.lamina { display:grid; grid-template-columns:520px 1fr; gap:20px; padding:18px 0;
          border-bottom:1px solid var(--linea); align-items:start; }
.lamina img { width:100%; height:auto; border:1px solid var(--linea); display:block; }
.n { font-size:13px; text-transform:uppercase; letter-spacing:.6px; color:var(--apagado);
     margin:0 0 6px; }
.narracion { font-size:16px; margin:0 0 12px; }
.prompt { font-size:12.5px; color:var(--apagado); font-family:Consolas,monospace;
          line-height:1.45; max-height:8.6em; overflow:auto; }
.falta { color:#7a2f2f; font-style:italic; }
a { color:var(--acento); }
"""


def monta_mosaico(laminas: list[Path], destino: Path) -> tuple[int, int]:
    """Pega las láminas en una sola imagen, rotuladas. Devuelve su tamaño."""
    from PIL import Image, ImageDraw

    alto_celda = int(ANCHO_CELDA * 768 / 1344)
    filas = (len(laminas) + COLUMNAS - 1) // COLUMNAS
    lienzo = Image.new("RGB", (ANCHO_CELDA * COLUMNAS, (alto_celda + ALTO_ROTULO) * filas), "white")
    dibujo = ImageDraw.Draw(lienzo)

    for indice, ruta in enumerate(laminas):
        imagen = Image.open(ruta).convert("RGB").resize((ANCHO_CELDA, alto_celda))
        x = (indice % COLUMNAS) * ANCHO_CELDA
        y = (indice // COLUMNAS) * (alto_celda + ALTO_ROTULO)
        lienzo.paste(imagen, (x, y + ALTO_ROTULO))
        dibujo.rectangle([x, y, x + ANCHO_CELDA, y + ALTO_ROTULO - 1], fill="black")
        dibujo.text((x + 6, y + 5), ruta.stem, fill="white")

    lienzo.save(destino, optimize=True)
    return lienzo.size


def monta_pagina(slides: list[dict], run_dir: Path, titulo: str, mosaico: Path | None) -> str:
    """Cada lámina al lado de la narración que ilustra."""
    filas = []
    for slide in slides:
        numero = slide.get("slide_number")
        lamina = run_dir / "slides" / f"slide-{numero:02d}.png"
        if lamina.exists():
            relativa = f"../../videos/{run_dir.name}/slides/{lamina.name}"
            imagen = f'<img src="{html.escape(relativa)}" alt="lámina {numero}">'
        else:
            imagen = f'<p class="falta">sin generar todavía ({lamina.name})</p>'
        filas.append(
            f"""<div class="lamina">
  <div>{imagen}</div>
  <div>
    <p class="n">lámina {numero}</p>
    <p class="narracion">{html.escape(slide.get("narration", ""))}</p>
    <div class="prompt">{html.escape(slide.get("image_prompt", ""))}</div>
  </div>
</div>"""
        )

    enlace_mosaico = (
        f'<p class="sub">Vista de conjunto: <a href="{html.escape(mosaico.name)}" target="_blank">'
        f"{html.escape(mosaico.name)}</a></p>"
        if mosaico
        else ""
    )

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Revisión de láminas · {html.escape(titulo)}</title>
<style>{ESTILO}</style></head><body>
<h1>Revisión de láminas</h1>
<p class="sub">{html.escape(titulo)} · {html.escape(CANAL_ACTIVO)} · {len(slides)} láminas</p>
{enlace_mosaico}

<div class="aviso">
<strong>La pregunta que hay que hacerse en cada fila es una sola:</strong> ¿alguien que mire esta
imagen sin oír nada adivinaría de qué habla la frase de al lado? Y en el mosaico: ¿el artefacto
mantiene su tamaño y su forma de una lámina a otra?
<br><br>
Esto <strong>no aprueba nada</strong>. Los gates automáticos miden el color de las láminas y las
palabras del guion; el dibujo lo mira una persona, y esa comprobación es del gate 1.
</div>

{"".join(filas)}
</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Revisión visual de las láminas de un run")
    parser.add_argument("run_id")
    parser.add_argument("--no-abrir", action="store_true")
    args = parser.parse_args()

    run_dir = CANAL_VIDEOS_DIR / args.run_id
    slides_path = run_dir / "slides.json"
    if not slides_path.exists():
        raise SystemExit(f"[FAIL] no existe {slides_path}")

    datos = json.loads(slides_path.read_text(encoding="utf-8"))
    slides = datos.get("slides") or []
    laminas = sorted((run_dir / "slides").glob("slide-*.png"))

    salida = CANAL_DIR / "revision" / args.run_id
    salida.mkdir(parents=True, exist_ok=True)

    mosaico = None
    if laminas:
        mosaico = salida / "mosaico.png"
        ancho, alto = monta_mosaico(laminas, mosaico)
        print(f"[OK] mosaico de {len(laminas)} lámina(s): {mosaico} ({ancho}x{alto})")
    else:
        print("[aviso] no hay ninguna lámina generada: la página saldrá solo con los prompts")

    pagina = salida / "laminas.html"
    pagina.write_text(monta_pagina(slides, run_dir, datos.get("title", args.run_id), mosaico), encoding="utf-8")
    print(f"[OK] página: {pagina}")
    print(f"     {len(slides)} lámina(s) del guion · {len(laminas)} generada(s)")

    if not args.no_abrir:
        webbrowser.open(pagina.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
