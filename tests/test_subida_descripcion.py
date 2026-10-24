"""La guarda que impide publicar una descripción con los marcadores sin sustituir.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_subida_descripcion.py

**De dónde sale.** Los agentes que escriben el guion dejan `<<CAPITULOS>>` y `<<BIBLIOGRAFIA>>` en
`description` **a propósito**, y el paso de montaje los sustituye por los capítulos reales y por la
bibliografía de las fichas. El diseño es correcto; lo que faltaba es que algo lo obligara. La
auditoría del 08-09 midió que **los cuatro `slides.json` de la semana los llevan literales** y que
el camino de subida no los cazaba: un despiste dejaba «<<CAPITULOS>>» a la vista en la página del
vídeo.

Es la misma clase de protección que `VISIBILIDAD = "private"`: lo que decide qué se publica no
depende de que un agente se acuerde.

**Y estas pruebas no llaman a YouTube.** La guarda corre antes de pedir el token, así que se puede
ejercitar sin red y sin credenciales — que es justo lo que la hace verificable.
"""

import pytest

from lib.youtube_client import MARCADORES_DE_DESCRIPCION, revisa_descripcion

BUENA = (
    "The iron maiden is not a medieval piece.\n\n"
    "00:00 The object everybody has seen\n01:12 What the record says\n\n"
    "SOURCES\n- Nuremberg, 1944 — bombing raid record\n\n"
    "AI DISCLOSURE: voice and images generated locally."
)


def test_una_descripcion_compuesta_pasa():
    revisa_descripcion(BUENA)  # no lanza


@pytest.mark.parametrize("marcador", MARCADORES_DE_DESCRIPCION)
def test_cada_marcador_sin_sustituir_para_la_subida(marcador):
    with pytest.raises(RuntimeError, match=marcador.strip("<>")):
        revisa_descripcion(f"Un resumen del episodio.\n\n{marcador}\n\nAI DISCLOSURE: ...")


def test_el_mensaje_dice_QUE_HACER_y_no_solo_que_falla():
    """El estilo de la casa: el error dice qué escribir, no solo que algo está mal."""
    with pytest.raises(RuntimeError) as e:
        revisa_descripcion(f"x\n\n{MARCADORES_DE_DESCRIPCION[0]}")
    texto = str(e.value)
    assert "montaje" in texto and "bibliografía" in texto.lower()
    assert "etapa de subida" in texto


def test_una_descripcion_vacia_no_dispara_la_guarda():
    """La guarda es sobre marcadores, no sobre calidad: una descripción vacía es otro problema."""
    revisa_descripcion("")
    revisa_descripcion(None)  # type: ignore[arg-type]


# El control que vivia aqui —«los slides.json del repo que HOY llevan marcadores serian rechazados»—
# se quito el 13-09. Su docstring ya decia que hacer: «Si esta prueba deja de encontrarlos es que las
# descripciones ya se compusieron, y entonces hay que quitarla, no relajarla». Eso paso al meter la
# composicion dentro del pipeline (addendum fila 154): ya no queda ningun slides.json con marcadores.
# Lo que demostraba —que la guarda caza el caso real y no uno inventado— lo cubre ahora
# `tests/test_descripcion_en_el_pipeline.py`, que ademas ejercita la etapa entera.
