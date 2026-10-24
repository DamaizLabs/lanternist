"""El guion de escena de un episodio, EN SECO: sin GPU, sin sonido, sin composición y sin tocar el run.

Es la ayuda de la skill `pone-en-escena` para no gastar rondas de capturas. Hace con el guion lo mismo que la etapa
`escena` del pipeline (`lib/escena/etapas.py → escena`) hasta justo antes de componer:

1. carga la capa del canal y el guion del episodio (`lib/escena/episodio.py → carga_guion`);
2. pide la puesta (`puesta(ep)`) y saca su GUION (`Guion.datos()`);
3. le aplica `encuadre.corrige` y, si la puesta da su franja de karaoke, `encuadre.aparta_de_caras`;
4. corre las seis comprobaciones (`lib/escena/comprobaciones.py → todas`).

Y lo cuenta: el tamaño del episodio, las correcciones de encuadre, los defectos de cada comprobación y los avisos del
guion (dos claves en el mismo instante, una palabra que `P()` encontró en otro cue, lo que revise el canal). Tarda unos
segundos; la etapa `escena` compone, mezcla el sonido y saca todas las capturas de la parada 2.

**El catálogo de imágenes.** El guion pide cada imagen por su nombre. Antes de la etapa `activos` el run no tiene
ninguna, así que por omisión se usa la biblioteca del canal y, encima, lo que ya haya en el catálogo del run
(`--catalogo ambos`): es el mismo orden en que la etapa `activos` las junta. Una imagen NUEVA del episodio solo existe
después de la parada 1; si el guion la pide antes, para aquí con su nombre, que es lo esperado.

**Lo que NO hace**: no genera, no compone, no captura y no escribe nada en el run ni en la carpeta del guion (la huella
de la parada 2 cubre esa carpeta). No sustituye a la parada 2: las comprobaciones no ven el dibujo, solo la geometría.

Uso (desde la raíz del repositorio):

    .venv\\Scripts\\python .claude/skills/pone-en-escena/scripts/en_seco.py --canal <id> --run-id <run>
    ... --todo                 lista todos los defectos y avisos, no solo los primeros
    ... --catalogo run         solo las imágenes que ya están en el run (tras la etapa activos)

Sale con 1 si el guion no se puede construir o si la comprobación `duracion` falla (la etapa `escena` pararía ahí), y
con 0 en los demás casos: el resto de defectos los juzga quien pone en escena y, en la parada 2, el usuario.

Ejemplo, sobre el episodio del canal de ejemplo (formato «láminas»): 6 planos, 0 actores y 0 defectos.

    .venv\\Scripts\\python .claude/skills/pone-en-escena/scripts/en_seco.py --canal example \\
        --run-id 2026-10-15_115251_how-does-a-zip-work
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[4]
LIMITE = 20  # cuántas líneas de cada lista se enseñan sin --todo


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="El guion de escena de un episodio, en seco: sin GPU ni render.")
    p.add_argument("--canal", required=True, help="el id del canal del run (canales/<id>/)")
    p.add_argument("--run-id", required=True, help="el run del episodio (su guion vive en datos/escenas/<run>/)")
    p.add_argument(
        "--catalogo",
        choices=("ambos", "biblioteca", "run"),
        default="ambos",
        help="de dónde salen las imágenes: la biblioteca del canal, el catálogo del run o los dos (por omisión)",
    )
    p.add_argument("--todo", action="store_true", help="enseña todas las líneas de cada lista")
    return p.parse_args()


def _lista(titulo: str, lineas: list[str], todo: bool) -> None:
    print(f"{titulo}: {len(lineas)}")
    for linea in lineas if todo else lineas[:LIMITE]:
        print(f"  - {linea}")
    if not todo and len(lineas) > LIMITE:
        print(f"  (y {len(lineas) - LIMITE} más: --todo)")


def main() -> int:
    args = _argumentos()
    # El canal se fija ANTES de importar lib/: `lib/config.py` lee CANAL_ACTIVO al importarse (como `pipeline.py`).
    os.environ["CANAL_ACTIVO"] = args.canal
    sys.path.insert(0, str(RAIZ))

    from lib import config
    from lib import state as run_state
    from lib.escena import biblia, comprobaciones, encuadre
    from lib.escena.episodio import Episodio, ErrorDeEpisodio, carga_guion, puesta_de
    from lib.escena.escena import ErrorDeEscena

    if config.CANAL_ERROR:
        print(f"El canal {args.canal} no se puede usar: {config.CANAL_ERROR}")
        return 1
    try:
        estado = run_state.load_run(args.run_id)
    except (run_state.EstadoRoto, OSError) as error:
        print(f"No se puede leer el estado del run {args.run_id}: {error}")
        return 1

    try:
        ep = Episodio(
            run_dir=estado["output_dir"],
            run_id=args.run_id,
            canal_dir=config.CANAL_DIR,
            perfil=config.CANAL_PERFIL,
            idioma=config.SUBTITLE_LANG,
        )
        catalogo: dict = {}
        if args.catalogo in ("ambos", "biblioteca") and (config.biblioteca_del_canal(ep.canal_dir)).is_dir():
            catalogo.update(biblia.lee(ep.canal_dir).catalogo)
        if args.catalogo in ("ambos", "run"):
            catalogo.update(ep.catalogo())
        ep.catalogo = lambda: catalogo  # en seco: el catálogo que se eligió, como si la etapa activos lo hubiera traído
        modulo = carga_guion(ep)
        linea = ep.linea()
        puesta = puesta_de(ep, modulo)
        datos = puesta.guion.datos()
    except (ErrorDeEpisodio, ErrorDeEscena, biblia.ErrorDeBiblioteca) as error:
        print(f"El guion no se puede construir: {error}")
        return 1

    correcciones = encuadre.corrige(datos)
    if puesta.franja_karaoke_y is not None:
        correcciones += encuadre.aparta_de_caras(datos, franja_inferior_y=puesta.franja_karaoke_y)
    halladas = comprobaciones.todas(datos, linea)
    avisos = list(dict.fromkeys(puesta.guion.avisos))

    actores = sum(len(p["actores"]) for p in datos["planos"])
    print(f"Guion de escena en seco · {args.run_id}")
    print(f"catálogo «{args.catalogo}»: {len(catalogo)} imágenes · guion: {ep.guion_py}")
    print(
        f"duración {datos['duracion']} s (audio {linea.total} s) · {len(datos['planos'])} planos · {actores} actores · "
        f"{len(datos['elementos'])} elementos · {len(datos['karaoke'])} grupos de karaoke · "
        f"{len(datos['transiciones'])} transiciones · {len(puesta.guion.sonidos)} efectos"
    )
    momentos = f"{len(puesta.momentos)} de la puesta" if puesta.momentos else "uno por plano (la puesta no da momentos)"
    print(f"fotogramas de la parada 2: {momentos}")
    print()
    _lista("correcciones de encuadre", list(correcciones), args.todo)
    total = sum(len(v) for v in halladas.values())
    print(f"\ncomprobaciones: {total} defectos")
    for que, lista in halladas.items():
        _lista(f"  {que}", [str(d) for d in lista], args.todo)
    print()
    _lista("avisos del guion", avisos, args.todo)
    return 1 if halladas.get("duracion") else 0


if __name__ == "__main__":
    sys.exit(main())
