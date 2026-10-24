"""El troceo de la narración con un guion escrito para Orpheus: puntos suspensivos y fragmentos.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_voz_troceo_orpheus.py

**De dónde sale.** El 08-09 la etapa de voz del episodio 1 se cayó en la lámina 15 tras tres
reintentos: el segmento «<groan> It reproduces...» tenía dos palabras habladas y whisper localizó una.
Dos defectos del troceo, no del motor ni del guion: `_SENTENCE_END` partía en los puntos suspensivos
—que en un guion para Orpheus son la pausa dramática, no el final de la frase— y `_merge_tiny` contaba
la etiqueta como palabra, así que un fragmento de 2 palabras pasaba por uno de 3. Las seis veces que
esa pasada no pudo recortar, el segmento tenía 2 o 3 palabras.

La lámina 15 real es el control negativo: con el troceo viejo daba un segmento de 2 palabras.
"""

from lib.voice_client import min_palabras_por_llamada, sin_etiquetas, split_narration


def _habladas(segmento: str) -> int:
    return len(sin_etiquetas(segmento).split())


def test_los_puntos_suspensivos_NO_cierran_la_frase():
    trozos = split_narration(
        "Not a copy of something real... because there was no original to copy. Think about it.", 20
    )
    assert trozos[0] == "Not a copy of something real... because there was no original to copy."
    assert len(trozos) == 2


def test_el_caracter_de_puntos_suspensivos_tampoco():
    assert split_narration("It reproduces… an idea about the past.", 20) == ["It reproduces… an idea about the past."]


def test_las_frases_normales_siguen_partiendo():
    """Control negativo del arreglo: si el regex nuevo dejara de partir en los puntos, todo sería un trozo."""
    trozos = split_narration(
        "One two three four five six. Seven eight nine ten eleven twelve! Thirteen fourteen fifteen sixteen?", 20
    )
    assert len(trozos) == 3


def test_un_fragmento_con_etiqueta_se_funde_contando_palabras_habladas():
    texto = (
        "So what does the maiden reproduce? Not an object. Not an object at all. "
        "<groan> It reproduces... an idea about the past."
    )
    trozos = split_narration(texto, 20, min_words=min_palabras_por_llamada("orpheus"))
    assert all(_habladas(t) >= 5 for t in trozos), trozos
    assert any("<groan> It reproduces... an idea" in t for t in trozos), trozos


def test_un_arranque_corto_se_antepone_al_siguiente():
    trozos = split_narration("Nobody. Not one line. The trail simply is not there, and it never was.", 20, min_words=5)
    assert trozos == ["Nobody. Not one line. The trail simply is not there, and it never was."]


def test_una_frase_larga_SI_se_parte_en_los_puntos_suspensivos():
    """Solo cuando se pasa del máximo: ahí la pausa es el corte más natural."""
    larga = (
        "one two three four five six seven eight nine ten eleven twelve... "
        "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twenty-one twenty-two."
    )
    trozos = split_narration(larga, 20)
    assert len(trozos) == 2 and trozos[0].endswith("twelve...")


def test_un_texto_entero_corto_no_se_pierde():
    assert split_narration("Nobody.", 20) == ["Nobody."]


def test_el_minimo_por_llamada_lo_pone_el_MOTOR_y_no_sube_para_los_demas():
    """Orpheus necesita 5 (divaga y el recorte ancla la última palabra); el contrato frase a frase de los
    demás sigue en 3 — con 5 para todos, el texto A2 de un canal se fundía en una sola llamada (gate del 08-09)."""
    assert min_palabras_por_llamada("orpheus") == 5
    assert min_palabras_por_llamada("kokoro") == 3
    texto_a2 = "It was Saturday morning. The house was very quiet. Ollie opened his eyes."
    assert len(split_narration(texto_a2, 20)) == 3
