"""Guion de escena de prueba que GENERA imágenes nuevas y trae el resto de la biblioteca del canal ficticio (F6.4b).

Pide a Qwen un objeto suelto (`o_taza`) y una lámina de dos objetos (`o_llave` y `o_boli`), los dos sustituyendo a
quien hay en una hoja del canal (`escena/biblia/hoja.png`, que pone la prueba). Las pruebas cambian ComfyUI y el
obrero por unos falsos que escriben sus imágenes y sus registros como los de verdad. `puesta(ep)` compone con las
imágenes de la biblioteca, como el guion `biblioteca.py`, y enseña dos de las tres nuevas: `o_boli` se generó pero el
guion no la usa, como una imagen que el usuario rechazó en la parada 1 y que se quitó de la escena. Esa no entra en la
biblioteca.
"""

from utiles_escena import CATALOGO_PRUEBA, guion_de_prueba

from lib.escena import activos as act
from lib.escena.episodio import Lote, Puesta

ESTILO = act.Estilo(prefijo="flat test style.", igual="Same style as the picture.", conserva="Keep the same style")
NUEVAS = ("o_taza", "o_llave", "o_boli")
EN_LA_ESCENA = ("o_taza", "o_llave")


def activos(ep):
    hoja = ep.canal_dir / "escena" / "biblia" / "hoja.png"
    return Lote(
        activos=(
            act.objeto("o_taza", ESTILO, que="a white mug", en=hoja, quien="the character", semillas=(7,)),
            act.objetos(
                "o_varios",
                ESTILO,
                lista="a spanner and a pen",
                piezas=("o_llave", "o_boli"),
                en=hoja,
                quien="the character",
                semillas=(7,),
            ),
        ),
        personajes={},
        biblioteca=tuple(CATALOGO_PRUEBA),
    )


def puesta(ep):
    g = guion_de_prueba(ep.linea(), catalogo=ep.catalogo(), escena=ep.escena)
    for nombre, x in zip(EN_LA_ESCENA, (400, 700)):
        g.el("pantalla", g.dibujo(nombre), x, 300, 200, 200, 0.5, 1.5)
    return Puesta(
        guion=g,
        css=ep.canal_dir / "escena" / "estilo.css",
        franja_karaoke_y=ep.escena["franja_karaoke_y"],
    )
