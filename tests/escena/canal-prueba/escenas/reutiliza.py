"""Guion de escena de prueba del episodio SIGUIENTE (F6.4b): usa las imágenes que generó `nuevas.py`.

No pide nada a Qwen. Pide a la biblioteca del canal las de siempre y las dos que entraron cuando el episodio de
`nuevas.py` pasó su parada 1 (las dos que usa su escena), que es como la skill `pone-en-escena` manda escribirlo: a
`Lote.activos` solo lo que la biblioteca no tiene.
"""

from utiles_escena import CATALOGO_PRUEBA, guion_de_prueba

from lib.escena.episodio import Lote, Puesta

DEL_EPISODIO_ANTERIOR = ("o_taza", "o_llave")


def activos(ep):
    return Lote(activos=(), personajes={}, biblioteca=(*CATALOGO_PRUEBA, *DEL_EPISODIO_ANTERIOR))


def puesta(ep):
    return Puesta(
        guion=guion_de_prueba(ep.linea(), catalogo=ep.catalogo(), escena=ep.escena),
        css=ep.canal_dir / "escena" / "estilo.css",
        franja_karaoke_y=ep.escena["franja_karaoke_y"],
    )
