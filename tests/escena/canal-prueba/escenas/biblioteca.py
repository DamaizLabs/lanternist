"""Guion de escena de prueba que reutiliza la biblioteca del canal ficticio (F6.3).

Es el episodio de prueba de `utiles_escena` sobre un run SIN imágenes propias: `activos(ep)` no genera nada y pide a
la biblioteca del canal (`<canal>/escena/biblioteca/`) las imágenes que usa, y la etapa `activos` las trae al run con su
procedencia. `puesta(ep)` compone con el catálogo del run, que ya las tiene.
"""

from utiles_escena import CATALOGO_PRUEBA, guion_de_prueba

from lib.escena.episodio import Lote, Puesta


def activos(ep):
    return Lote(activos=(), personajes={}, biblioteca=tuple(CATALOGO_PRUEBA))


def puesta(ep):
    return Puesta(
        guion=guion_de_prueba(ep.linea(), catalogo=ep.catalogo(), escena=ep.escena),
        css=ep.canal_dir / "escena" / "estilo.css",
        franja_karaoke_y=ep.escena["franja_karaoke_y"],
    )
