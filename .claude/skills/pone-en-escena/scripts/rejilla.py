"""Una rejilla numerada sobre una imagen del catálogo, para MEDIR dónde tiene que tocar algo (skill `pone-en-escena`).

Cuando una mano tiene que caer en un mango, un culete en un muro o unos pies en un escalón, el punto se mide, no se
estima: colocado a ojo, un personaje del primer episodio con personajes quedó 88 px por debajo del muro en que se
sentaba. Esta ayuda dibuja la rejilla en las MISMAS coordenadas que usa el guion de escena:

- **Una postura, un objeto o una pieza** (cualquier imagen con apoyo): px de SU imagen respecto a su apoyo (`ax`,
  `ay` del catálogo), sin dividir por su `k`. Es lo que espera `punto_de_postura` (`lib/escena/ayudas.py`), que ya
  divide por `k`. La cruz roja es el apoyo (0, 0); y crece hacia abajo, así que lo que está por encima de los pies es
  negativo.
- **Un fondo** (apoyo en 0, 0): px del fondo, que son los de las claves de los actores (`x`, `y`) y de la cámara. Si
  el catálogo coloca la imagen del fondo desplazada o escalada dentro de su marco (`img`), la rejilla la pinta igual
  que `lib/escena/compone.py → _plano_dom`.

Deja un PNG por imagen en `<run>/revision/rejillas/` (material de trabajo del run: no cuenta en la procedencia ni en la
huella de la parada 2) e imprime su ruta. Con `--zona` recorta una región, en esas mismas coordenadas, para medir de
cerca: una imagen entera de 3.584 px se lee reducida y la precisión cae.

No usa GPU ni red, y no escribe nada fuera de `rejillas/`.

Uso (desde la raíz del repositorio):

    .venv\\Scripts\\python .claude/skills/pone-en-escena/scripts/rejilla.py --canal <id> --run-id <run> <postura>
    ... <fondo> --zona 2000,700,3400,1100 --paso 25

Ejemplo, sobre la primera lámina ampliada del episodio del canal de ejemplo:

    .venv\\Scripts\\python .claude/skills/pone-en-escena/scripts/rejilla.py --canal example \\
        --run-id 2026-10-15_115251_how-does-a-zip-work lamina_01 --zona 0,0,800,600 --paso 25
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[4]
ROJO, LINEA, FUERTE, TEXTO, FONDO_TEXTO = (230, 30, 30), (0, 150, 255), (0, 90, 200), (255, 255, 255), (0, 0, 0)


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rejilla numerada sobre imágenes del catálogo, en coordenadas del guion.")
    p.add_argument("--canal", required=True, help="el id del canal del run")
    p.add_argument("--run-id", required=True, help="el run del episodio (la rejilla se guarda en su revision/)")
    p.add_argument("nombres", nargs="+", help="nombres del catálogo: posturas, objetos, piezas o fondos")
    p.add_argument("--paso", type=int, default=50, help="px entre líneas (cada dos, una más fuerte con su número)")
    p.add_argument("--zona", help="x0,y0,x1,y1 en las coordenadas de la rejilla: recorta esa región")
    p.add_argument("--salida", help="otra carpeta para los PNG (por omisión, <run>/revision/rejillas/)")
    return p.parse_args()


def _zona(texto: str | None) -> tuple[float, float, float, float] | None:
    if not texto:
        return None
    partes = [float(v) for v in texto.split(",")]
    if len(partes) != 4 or partes[2] <= partes[0] or partes[3] <= partes[1]:
        raise SystemExit(f"--zona es x0,y0,x1,y1 con x1 > x0 e y1 > y0, no {texto!r}")
    return partes[0], partes[1], partes[2], partes[3]


def _lienzo(entrada: dict, fichero: Path):
    """La imagen en el marco de sus coordenadas: (lienzo, ox, oy, unidades), con píxel = coordenada + o."""
    from PIL import Image

    imagen = Image.open(fichero).convert("RGBA")
    es_fondo = not entrada.get("ax") and not entrada.get("ay")
    if es_fondo:
        w, h = int(entrada["w"]), int(entrada["h"])
        caja = entrada.get("img") or {"x": 0, "y": 0, "w": w, "h": h}
        lienzo = Image.new("RGBA", (w, h), (128, 128, 128, 255))
        pintada = imagen.resize((round(caja["w"]), round(caja["h"])))
        lienzo.alpha_composite(pintada, (round(caja["x"]), round(caja["y"])))
        return lienzo, 0.0, 0.0, "px del fondo"
    fondo = Image.new("RGBA", imagen.size, (235, 235, 235, 255))  # gris claro: lo transparente se distingue
    fondo.alpha_composite(imagen)
    return fondo, float(entrada["ax"]), float(entrada["ay"]), "px de la imagen respecto al apoyo (sin dividir por k)"


def _encuadra(lienzo, ox: float, oy: float, zona):
    """Recorta `zona` (en coordenadas, limitada a la imagen) y la amplía para leerla de cerca.

    Devuelve (imagen, x0, y0, escala): la coordenada c cae en el píxel (c - x0) * escala de la imagen devuelta.
    """
    from PIL import Image

    w, h = lienzo.size
    if not zona:
        return lienzo, -ox, -oy, 1.0
    x0, y0 = max(zona[0], -ox), max(zona[1], -oy)
    x1, y1 = min(zona[2], w - ox), min(zona[3], h - oy)
    if x1 <= x0 or y1 <= y0:
        raise SystemExit(f"--zona cae fuera de la imagen: sus coordenadas van de ({-ox}, {-oy}) a ({w - ox}, {h - oy})")
    recorte = lienzo.crop((round(x0 + ox), round(y0 + oy), round(x1 + ox), round(y1 + oy)))
    escala = max(1.0, 1400 / max(recorte.size))  # de cerca se lee mejor, y la rejilla sigue en coordenadas
    if escala > 1:
        recorte = recorte.resize((round(recorte.width * escala), round(recorte.height * escala)), Image.LANCZOS)
    return recorte, x0, y0, escala


def _dibuja(imagen, x0: float, y0: float, escala: float, paso: int):
    """Las líneas cada `paso` (una de cada dos, más fuerte y con su número) y la cruz roja del cero."""
    from PIL import ImageDraw, ImageFont

    d = ImageDraw.Draw(imagen)
    w, h = imagen.size
    grosor = max(1, round(max(w, h) / 1500))
    cuerpo = max(14, round(max(w, h) / 90))
    letra = ImageFont.load_default(size=cuerpo)
    for eje, desde, largo in (("x", x0, w), ("y", y0, h)):
        v = (int(desde) // paso) * paso
        while (v - desde) * escala <= largo:
            p = (v - desde) * escala
            fuerte = (v // paso) % 2 == 0
            color, ancho = (FUERTE, grosor * 2) if fuerte else (LINEA, grosor)
            linea = [(p, 0), (p, h)] if eje == "x" else [(0, p), (w, p)]
            d.line(linea, fill=color, width=ancho)
            # Los números de y no entran en la franja de arriba, que es la de los números de x.
            if fuerte and p >= 0 and (eje == "x" or p > cuerpo * 1.5):
                sitio = (p + 3, 3) if eje == "x" else (3, p + 3)
                d.text(sitio, str(v), font=letra, fill=TEXTO, stroke_width=3, stroke_fill=FONDO_TEXTO)
            v += paso
    cero_x, cero_y = -x0 * escala, -y0 * escala
    if 0 <= cero_x <= w:
        d.line([(cero_x, 0), (cero_x, h)], fill=ROJO, width=grosor * 3)
    if 0 <= cero_y <= h:
        d.line([(0, cero_y), (w, cero_y)], fill=ROJO, width=grosor * 3)
    return imagen


def main() -> int:
    args = _argumentos()
    zona = _zona(args.zona)
    os.environ["CANAL_ACTIVO"] = args.canal  # antes de importar lib/, como pipeline.py
    sys.path.insert(0, str(RAIZ))

    from lib import config
    from lib import state as run_state
    from lib.escena import biblia, obrero

    if config.CANAL_ERROR:
        print(f"El canal {args.canal} no se puede usar: {config.CANAL_ERROR}")
        return 1
    run_dir = Path(run_state.load_run(args.run_id)["output_dir"])
    dir_activos = config.activos_del_run(run_dir)
    del_run = obrero.lee_catalogo(dir_activos)["imagenes"]
    bib = biblia.lee(config.CANAL_DIR) if config.biblioteca_del_canal(config.CANAL_DIR).is_dir() else None
    salida = Path(args.salida) if args.salida else config.revision_del_run(run_dir) / "rejillas"
    salida.mkdir(parents=True, exist_ok=True)

    codigo = 0
    for nombre in args.nombres:
        if nombre in del_run:
            entrada, fichero = del_run[nombre], dir_activos / obrero.IMG / Path(str(del_run[nombre]["src"])).name
        elif bib is not None and nombre in bib.catalogo:
            entrada, fichero = bib.catalogo[nombre], bib.fichero(nombre)
        else:
            print(f"{nombre}: no está en el catálogo del run ni en la biblioteca del canal")
            codigo = 1
            continue
        if not fichero.is_file():
            print(f"{nombre}: su imagen no está en disco ({fichero})")
            codigo = 1
            continue
        lienzo, ox, oy, unidades = _lienzo(entrada, fichero)
        imagen, x0, y0, escala = _encuadra(lienzo, ox, oy, zona)
        imagen = _dibuja(imagen, x0, y0, escala, args.paso)
        destino = salida / f"{nombre}{'-zona' if zona else ''}.png"
        imagen.convert("RGB").save(destino)
        k = entrada.get("k", 1)
        print(f"{nombre}: {destino}  ({unidades}; k = {k}; {entrada['w']}×{entrada['h']} px)")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
