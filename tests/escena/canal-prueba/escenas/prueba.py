"""Guion de escena del episodio de prueba del canal ficticio (F6.2d).

Las pruebas lo copian a `<canal>/datos/escenas/<run_id>/escena.py`, que es donde el pipeline busca el guion de escena
de un episodio (`lib/escena/episodio.py`). Es el contrato en su forma mínima:

- `puesta(ep)`: el episodio de prueba de `utiles_escena` (dos planos, dos personajes que hablan, tarjeta, etiqueta,
  grito y transición) sobre la línea de tiempo y el catálogo del run, el CSS del canal ficticio y dónde empieza su
  karaoke en pantalla.
- Sin `activos`: el catálogo ya está en el run, así que la parada 1 enseña los recortes sin generar nada.
"""

from utiles_escena import guion_de_prueba

from lib.escena.episodio import Puesta


def puesta(ep):
    return Puesta(
        guion=guion_de_prueba(ep.linea(), catalogo=ep.catalogo(), escena=ep.escena),
        css=ep.canal_dir / "escena" / "estilo.css",
        franja_karaoke_y=860,
    )
