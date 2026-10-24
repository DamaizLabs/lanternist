"""Guion de escena de un episodio de segundo y medio del canal ficticio: el del render real con GPU (F6.2d).

Una lámina de voz («Ana walked.», un segundo) con las pausas cortas que declara su perfil, un plano del parque con
Ana, su karaoke y un efecto de sonido de la biblioteca del estudio. Lo justo para que el render real tenga imagen,
karaoke, voz, un efecto y una fuente de la biblioteca, en 36 fotogramas.
"""

from lib.escena.episodio import Puesta
from lib.escena.escena import Guion


def puesta(ep):
    linea = ep.linea()
    g = Guion(titulo="Render corto", idioma="en", escena=ep.escena, catalogo=ep.catalogo(), iconos={}, linea=linea)
    g.fondo("parque", img="parque", suelo=[(0, 1080), (2400, 1080), (2400, 1350), (0, 1350)], px_u=500)
    p = g.plano("parque", 0, linea.total)
    p.cam(0, 1200, 760, 1.0, tr=0)
    g.actor(p, ["ana_pie"], 900, 1200, escala=1.2, pj="ana")
    g.sfx("pop", 0.4, 0.3)
    return Puesta(
        guion=g,
        css=ep.canal_dir / "escena" / "estilo.css",
        franja_karaoke_y=860,
        momentos=[(0.5, "Ana en el parque")],
    )
