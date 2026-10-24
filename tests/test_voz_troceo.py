"""El troceo de la narración, que decide cómo suena la voz del canal.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_voz_troceo.py

**De dónde salen estas pruebas.** El piloto de un canal (05-09) produjo un audio que se describió
como «distorsionada y robótica» comparándolo con una muestra que sí gustó. No era distorsión —el
WAV tenía el mismo pico, el mismo rms y la misma tasa de saltos que la muestra—: era que el motor
**estira los fonemas cuando el trozo que sintetiza es corto**, y la narración iba frase a frase, con
trozos de 5,9 palabras. Sobre el MISMO texto, la voz tarda 8,20 s en una llamada y 10,76 s troceada:
un 31 % más lenta y con la entonación plana de quien lee una línea suelta.

**Lo que estas pruebas protegen es la frontera, no el sonido.** Si agrupar suena mejor o peor lo
decide el usuario escuchando; lo que no puede pasar es que un canal herede en silencio la política de
otro, que es la regla de F4.9. Por eso la clave es obligatoria y `0` es una respuesta explícita.
"""

import pytest

from lib.voice_client import VoiceError, split_narration

TEXTO = (
    "It was Saturday morning. The house was very quiet. Ollie opened his eyes. "
    "He remembered something important. Today was Mum's birthday!"
)


def test_sin_agrupar_sale_una_frase_por_trozo():
    """El comportamiento de un canal, que no debe cambiar porque otro estrene otra política."""
    trozos = split_narration(TEXTO, 20)
    assert len(trozos) == 5
    assert trozos[0] == "It was Saturday morning."
    assert trozos[-1] == "Today was Mum's birthday!"


def test_agrupar_junta_frases_hasta_el_techo():
    trozos = split_narration(TEXTO, 20, agrupa_hasta=21)
    assert len(trozos) < 5, "con techo 21 las cinco frases tienen que caber en menos trozos"
    for trozo in trozos:
        assert len(trozo.split()) <= 21


def test_agrupar_NO_parte_ninguna_frase():
    """Agrupar solo pega; si partiera, el karaoke perdería el emparejamiento con el guion."""
    trozos = split_narration(TEXTO, 20, agrupa_hasta=21)
    unido = " ".join(trozos)
    assert unido == " ".join(TEXTO.split())
    frases = [f + "." for f in TEXTO.split(". ")]
    for trozo in trozos:
        # cada trozo empieza donde empieza una frase del original
        assert any(trozo.startswith(f.split(".")[0]) for f in frases)


def test_el_techo_de_agrupar_no_puede_estar_por_debajo_del_de_partir():
    """Si cupiera menos que una frase larga, esa frase no cabría ni en su propio grupo."""
    with pytest.raises(VoiceError, match="agrupa_hasta_palabras"):
        split_narration(TEXTO, 20, agrupa_hasta=12)


def test_agrupar_baja_el_numero_de_llamadas_al_motor():
    """La cifra que importa: menos llamadas es más contexto de prosodia en cada una."""
    sueltas = split_narration(TEXTO, 20)
    agrupadas = split_narration(TEXTO, 20, agrupa_hasta=21)
    palabras_por_llamada = len(TEXTO.split()) / len(agrupadas)
    assert palabras_por_llamada > len(TEXTO.split()) / len(sueltas)
    assert palabras_por_llamada >= 10, f"solo {palabras_por_llamada:.1f} palabras por llamada"


def test_cada_receta_declara_si_agrupa():
    """La frontera de F4.9: cada canal DICE su política, ninguno la hereda.

    Se leen todas las recetas, no la del canal activo: lo que se protege es justamente que una no
    arrastre a otra. `0` es una respuesta (frase a frase); lo que no vale es callarse.
    """
    import json

    from canales_de_prueba import recetas_a_comprobar

    for receta in recetas_a_comprobar():
        datos = json.loads(receta.read_text(encoding="utf-8"))
        if "segmentacion" in datos:
            valor = datos["segmentacion"].get("agrupa_hasta_palabras")
            assert isinstance(valor, int) and valor >= 0, f"{receta.name}: agrupa_hasta_palabras = {valor!r}"


def test_control_las_dos_recetas_de_prueba_agrupan_distinto():
    """Sin esto, la guarda de arriba podría pasar con dos recetas que dicen lo mismo y no probar la frontera."""
    import json

    from canales_de_prueba import RECETA_DOCUMENTAL, RECETA_FICCION

    agrupa = {
        r.name: json.loads(r.read_text(encoding="utf-8"))["segmentacion"]["agrupa_hasta_palabras"]
        for r in (RECETA_DOCUMENTAL, RECETA_FICCION)
    }
    assert agrupa == {RECETA_DOCUMENTAL.name: 0, RECETA_FICCION.name: 21}
