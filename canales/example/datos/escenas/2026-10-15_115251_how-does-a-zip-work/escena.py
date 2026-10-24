"""Guion de escena del primer episodio del canal de ejemplo: «How Does a Zip Work?» (OC1.4).

Formato «láminas». Es el ejemplo mínimo de `docs/scene-script.md` con dos añadidos de este episodio:

- el negro del principio, que se abre durante la pausa de entrada, y el del final, que cae durante la cola
  (`perfil.json → escena.pausas`);
- los momentos de la hoja de fotogramas de la parada 2: el centro de la primera toma de cada lámina, la mitad de la
  primera vez que sale cada transición y los dos negros.

La cámara recorre cada una de las tres láminas entera con el planificador del motor (`lib/escena/laminas.py`), que
reparte las tomas, los movimientos y las transiciones con los ajustes de `perfil.json → escena.laminas`. Encima va el
karaoke de una línea, que sale de la línea de tiempo de la voz.

No hay imágenes nuevas: la etapa `activos` solo amplía cada lámina ×2 (`obrero.fondo`), y las ampliaciones son del
episodio, no de la biblioteca del canal. Sin rótulos ni CTA: la capa del canal no los tiene (`canales/example/escena/`).
"""

from __future__ import annotations

import json

from escena_del_canal import CSS

from lib.escena import anclas, laminas, obrero
from lib.escena.episodio import Episodio, Lote, Puesta
from lib.escena.escena import Guion

# El negro del principio se abre en lo que dura la pausa de entrada (escena.pausas.intro_s = 1 s), y el del final cae
# en 1,5 s de los 2 s de cola (escena.pausas.cola_s): la última palabra se oye con la lámina todavía a la vista.
NEGRO_ABRE_S = 1.0
NEGRO_CIERRA_S = 1.5


def _slides(ep: Episodio) -> dict:
    return json.loads((ep.run_dir / "slides.json").read_text(encoding="utf-8"))


def _set(numero: int) -> str:
    return f"lamina_{numero:02d}"


def activos(ep: Episodio) -> Lote:
    """Ninguna imagen nueva: cada lámina del run, ampliada ×2 para que la cámara se acerque sin perder trazo."""
    numeros = [int(s["slide_number"]) for s in _slides(ep)["slides"]]
    ampliadas = [
        obrero.fondo(_set(n), ep.run_dir / "slides" / f"slide-{n:02d}.png", del_episodio=True) for n in numeros
    ]
    return Lote(activos=(), personajes={}, extra=ampliadas)


def construye(ep: Episodio, catalogo: dict) -> tuple[Guion, list[laminas.Toma]]:
    linea = ep.linea()
    anclas.usa(linea)
    slides = _slides(ep)
    g = Guion(titulo=slides["title"], idioma=ep.idioma, escena=ep.escena, catalogo=catalogo, iconos={}, linea=linea)
    sets = {}
    for numero in linea.laminas:
        g.fondo(_set(numero), img=_set(numero), suelo=None)
        sets[numero] = _set(numero)
    ajustes = laminas.ajustes(ep.escena)
    tomas = laminas.planifica(
        laminas.laminas_del_episodio(linea, slides["slides"]),
        clave_del_video=slides["title"],
        fps=linea.fps,
        ajustes_=ajustes,
    )
    laminas.pon_en_escena(g, tomas, sets, ajustes_=ajustes)

    # El negro, encima de todo: quieto en el primer fotograma y abierto cuando empieza la voz; al final, lo contrario.
    g.el("pantalla", '<div class="negro"></div>', 960, 540, 1920, 1080, 0, NEGRO_ABRE_S, entra="nada", sale="fade",
         ds=NEGRO_ABRE_S, z=8)  # fmt: skip
    g.el("pantalla", '<div class="negro"></div>', 960, 540, 1920, 1080, linea.total - NEGRO_CIERRA_S, linea.total,
         entra="fade", sale="nada", di=NEGRO_CIERRA_S, z=8)  # fmt: skip
    return g, tomas


def _momentos(tomas: list[laminas.Toma], fps: int, total: float) -> list[tuple[float, str]]:
    """Lo que enseña la hoja de la parada 2: los dos negros, el centro de la primera toma de cada lámina y la mitad de
    la primera vez que sale cada transición."""
    momentos = [(NEGRO_ABRE_S / 2, "El negro del principio, abriéndose"), (total - 0.5, "El negro del final")]
    vistas: set[str] = set()
    for t in tomas:
        t0 = t.inicio / fps
        if t.indice == 0:
            momentos.append((t0 + t.fotogramas / fps / 2, f"Lámina {t.lamina} · {t.movimiento}"))
        if t.transicion and t.transicion not in vistas:
            vistas.add(t.transicion)
            momentos.append((t0 + 1.0, f"Transición {t.transicion}, a mitad (lámina {t.lamina})"))
    return sorted(momentos)


def puesta(ep: Episodio) -> Puesta:
    g, tomas = construye(ep, ep.catalogo())
    return Puesta(
        guion=g,
        css=CSS,
        franja_karaoke_y=ep.escena["franja_karaoke_y"],
        momentos=_momentos(tomas, g.escena["fps"], g.linea.total),
    )
