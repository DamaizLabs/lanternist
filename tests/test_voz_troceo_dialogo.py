r"""El diálogo llega al motor en su propio bocado, y la narración se trocea como siempre (F5.8).

Correr: .venv\Scripts\python -m pytest -q tests/test_voz_troceo_dialogo.py

**De dónde sale.** El 15-09, escuchando el episodio 1 de un canal: «en la lámina 1 "¡Nora, wake up!
It's Mum's birthday." lo entona, pero chatterbox lo entonaba más y parecía que realmente era Ollie el
que chillaba, aquí parece más parte de la voz en off del narrador». La causa es el troceo: con
`agrupa_hasta_palabras: 21`, el grito viajaba en el mismo bocado que la narración de alrededor y el
motor entona cada llamada con UN registro. Medido con las cuatro variantes de
la cata de diálogo (`medicion-tono.json`, en `experimentos/`): **165,5 Hz** agrupado contra **240,0 Hz** en
segmento propio, y se eligió la segunda escuchándolas.

Los dos riesgos que estas pruebas vigilan, y son de signo contrario:

1. **Que se rompa lo que ya sonaba bien.** El agrupado existe por una medición (`_agrupa`: 10,76 s
   frase a frase contra 8,20 s agrupado sobre el mismo texto), así que un texto SIN diálogo tiene que
   trocearse **exactamente** igual que antes de F5.8. El control es literal: una copia del troceo
   viejo, corrida sobre narración sin diálogo.
2. **Que el arreglo se quede corto.** Que el bocado del personaje traiga narración pegada, que traiga
   a otro personaje, o que una comilla sin cerrar se trague la lámina entera.
"""

import json
from pathlib import Path

import pytest
from canales_de_prueba import RECETA_DOCUMENTAL, RECETA_FICCION

from lib.voice_client import _SENTENCE_END, _frases, _split_long_sentence, sin_etiquetas, split_narration

# Los parámetros de producción viven en la receta de cada canal: se leen de ahí para que la prueba mida el
# camino real y no una llamada cómoda con los valores por defecto. Desde OC1.1 son las dos recetas de prueba
# (`tests/canales_de_prueba.py`): la de ficción agrupa hasta 21 palabras, como el canal donde nació F5.8, y la
# documental va frase a frase.
# El mínimo por llamada de Orpheus, que es el motor del estudio (`lib/config.MOTOR_DE_VOZ`).
MIN_ORPHEUS = 5

# El grito de la lámina 1 tal como se aprobó en la cata: la variante B de
# su `variantes.json` (en `experimentos/`), con el punto del guion real en vez de la
# exclamación que llevaba la prueba.
# Reescrito el 15-09: la orden va en tres golpes con su apertura, que es la convención del
# estudio (addendum fila 133). El troceo NO la parte por dentro aunque cada `!` sea frontera:
# la regla del diálogo manda sobre la de la puntuación, y por eso llega entera en un bocado.
GRITO = "Ollie shouted, \"¡Nora! ¡Wake up! ¡It's Mum's birthday!\""

# Láminas de un episodio de ficción, escritas aquí y no leídas de un run: los guiones de producción no viajan con
# git. La primera es la del grito tal como sonaba mal —con su narración delante y detrás, la variante A de la
# cata—; las otras traen una pregunta, una cita con su atribución detrás y una de tres palabras.
LAMINAS_CON_DIALOGO = [
    f"He opened the door of her room. {GRITO} Nora sat up very slowly. She looked at the clock on the wall.",
    'Nora said, "What time is it?" Ollie looked at the clock on the wall. "It is seven," he said. '
    "They went down to the kitchen very slowly, without a sound.",
    "Mum was still asleep. The kitchen was very quiet, and the sun was on the table. "
    'Ollie said, "Yes." Nora took a big bowl from the cupboard and put it on the table.',
]
LAMINAS_SIN_DIALOGO = [
    "The zip has two rows of small metal teeth. A slider joins them, one pair at a time, and the rows lock. "
    "The first patent is more than a hundred years old, and for a long time nobody wanted it.",
]


def _receta(ruta: Path) -> dict:
    seg = json.loads(ruta.read_text(encoding="utf-8"))["segmentacion"]
    return {
        "max_words": int(seg["max_palabras_por_frase"]),
        "agrupa_hasta": int(seg["agrupa_hasta_palabras"]) or None,
    }


def _troceo_previo_a_F58(texto: str, max_words: int, agrupa_hasta: int | None = None, min_words: int = 3) -> list[str]:
    """El troceo TAL COMO ESTABA antes de F5.8. Copiado a propósito, no importado.

    Es el control negativo del criterio 6: si el cambio tocara la narración corrida, esta copia y
    `split_narration` dejarían de coincidir sobre los guiones del primer canal. Llama al `_split_long_sentence`
    de hoy para que el control aísle **lo que F5.8 cambió** —el corte por frases, la fusión de
    fragmentos y el agrupado— y no se rompa si algún día se toca el reparto por cláusulas.
    """
    plano = " ".join(texto.split())
    piezas: list[str] = []
    for frase in _SENTENCE_END.split(plano):
        frase = frase.strip()
        if frase:
            piezas.extend(_split_long_sentence(frase, max_words))

    resultado: list[str] = []
    pendiente: str | None = None
    for pieza in piezas:
        if pendiente is not None:
            pieza = f"{pendiente} {pieza}"
            pendiente = None
        if len(sin_etiquetas(pieza).split()) >= min_words:
            resultado.append(pieza)
        elif resultado:
            resultado[-1] = f"{resultado[-1]} {pieza}"
        else:
            pendiente = pieza
    if pendiente is not None:
        resultado.append(pendiente)

    if agrupa_hasta:
        grupos: list[str] = []
        for pieza in resultado:
            if grupos and len(grupos[-1].split()) + len(pieza.split()) <= agrupa_hasta:
                grupos[-1] = f"{grupos[-1]} {pieza}"
            else:
                grupos.append(pieza)
        resultado = grupos
    return resultado


# --------------------------------------------------------------------------------------
# Control negativo: sin diálogo, nada cambia
# --------------------------------------------------------------------------------------


def test_una_narracion_corrida_no_nota_el_cambio():
    """Criterio 6 y 7: sin diálogo, el troceo es idéntico al de antes de F5.8, segmento a segmento.

    Se prueba frase a frase y con el agrupado de 21, que es la rama que este cambio toca.
    """
    texto = (
        "It was Saturday morning. The house was very quiet. Outside, the birds were singing. "
        "Inside, nobody was talking. Ollie opened his eyes."
    )
    for agrupa in (None, 21):
        assert split_narration(texto, 20, agrupa_hasta=agrupa, min_words=MIN_ORPHEUS) == _troceo_previo_a_F58(
            texto, 20, agrupa_hasta=agrupa, min_words=MIN_ORPHEUS
        )


def test_el_apostrofo_ingles_no_es_una_comilla():
    """«It's» y «Mum's» aparecen en cada lámina: si contaran como cita, partirían la narración entera."""
    texto = (
        "Today was Mum's birthday. It's the day he got out of bed very fast. "
        "He didn't look for his shoes. There wasn't time."
    )
    assert split_narration(texto, 20, agrupa_hasta=21, min_words=MIN_ORPHEUS) == _troceo_previo_a_F58(
        texto, 20, agrupa_hasta=21, min_words=MIN_ORPHEUS
    )


# --------------------------------------------------------------------------------------
# El diálogo, solo y con su atribución
# --------------------------------------------------------------------------------------


def test_el_grito_de_la_lamina_1_llega_al_motor_SOLO():
    """El caso que se oyó, con los parámetros de producción de la receta de ficción (max 20, agrupa 21)."""
    receta = _receta(RECETA_FICCION)
    trozos = split_narration(LAMINAS_CON_DIALOGO[0], min_words=MIN_ORPHEUS, **receta)
    assert GRITO in trozos, trozos
    # Y el defecto medido ya no aparece: el grito iba con «He opened the door.» delante y «Nora sat up
    # very slowly.» detrás, que es la variante A de la cata (165,5 Hz).
    assert not [t for t in trozos if "wake up" in t and t != GRITO], trozos


def test_lo_unico_que_acompana_a_una_cita_es_lo_que_no_cabe_solo():
    """Las láminas con diálogo de arriba, con los parámetros de producción.

    El invariante no es «una cita nunca comparte bocado» —eso sería falso y lo taparía—, es que
    **cuando comparte, uno de los dos no se sostenía solo**: por debajo de `MIN_ORPHEUS` palabras
    habladas, el recorte por transcripción no ancla y la etapa se cae (fila 127), y ese mínimo es del
    MOTOR. Si algún día un bocado junta una cita y una narración que SÍ cabrían por separado, esto se
    pone rojo.

    Medido sobre dos episodios de producción el 15-09: **53 bocados con cita limpios**, 8 que son trozos
    de una cita que no cabía en el techo, 4 con un apunte de narración de 4 palabras y 1 con dos
    personajes porque uno de ellos dice tres palabras (`Ollie said, "Yes."`, que está arriba).
    """
    receta = _receta(RECETA_FICCION)

    def habladas(fragmento: str) -> int:
        return len(sin_etiquetas(fragmento).split())

    for numero, texto in enumerate(LAMINAS_CON_DIALOGO, start=1):
        citadas = [f.texto for f in _frases(texto) if f.dialogo]
        for trozo in split_narration(texto, min_words=MIN_ORPHEUS, **receta):
            if not any(c in trozo for c in ('"', "“", "«")):
                continue
            dentro = [c for c in citadas if c in trozo]
            if not dentro:  # trozo de una cita que no cabía en el techo: se comprueba aparte
                continue
            sobra = trozo
            for cita in dentro:
                sobra = sobra.replace(cita, " ")
            corta = min(habladas(c) for c in dentro)
            for resto in (p.strip() for p in sobra.split("  ")):
                if resto:
                    assert min(habladas(resto), corta) < MIN_ORPHEUS, (numero, trozo, resto)


def test_la_atribucion_viaja_con_la_cita_delante_o_detras():
    """Criterio 2: la cita SOLA da 208,7 Hz (variante C, descartada) y con atribución 240,0 (variante B)."""
    delante = 'He opened the door of her room. Ollie shouted, "Nora, wake up!" Nora sat up very slowly.'
    trozos = split_narration(delante, 20, agrupa_hasta=21, min_words=MIN_ORPHEUS)
    assert 'Ollie shouted, "Nora, wake up!"' in trozos, trozos

    detras = 'She looked at the window. "Get a cloth," said Mum, and she smiled. So they cleaned it up.'
    trozos = split_narration(detras, 20, agrupa_hasta=21, min_words=MIN_ORPHEUS)
    assert '"Get a cloth," said Mum, and she smiled.' in trozos, trozos


def test_un_apunte_de_narracion_que_no_llega_al_minimo_se_pega_a_la_cita_vecina():
    """**El límite de esta feature, y es una decisión, no un descuido.**

    «Ollie looked at her.» son 4 palabras y va entre dos líneas de personaje (lámina 2 del episodio
    de un canal, del 04-09): no tiene ningún vecino de narración al que pegarse, así que acaba en el
    bocado de uno de los dos. La alternativa sería mandarlo solo al motor, y el mínimo por llamada es
    del MOTOR —medido, con una etapa caída detrás (fila 127)—, no una preferencia de esta feature.

    Lo que sí se arregla desde el guion: escribir ese apunte con cinco palabras o más. Por eso la
    prueba deja la cifra a la vista en vez de esconder el caso.
    """
    texto = 'Nora said, "We are going to make a cake for Mum." Ollie looked at her. "But we cannot cook a cake."'
    trozos = split_narration(texto, 20, agrupa_hasta=21, min_words=MIN_ORPHEUS)
    assert any("Ollie looked at her." in t and '"' in t for t in trozos), trozos
    # Con el apunte escrito un poco más largo, el diálogo queda limpio a los dos lados.
    largo = texto.replace("Ollie looked at her.", "Ollie looked at her for a moment.")
    trozos = split_narration(largo, 20, agrupa_hasta=21, min_words=MIN_ORPHEUS)
    assert "Ollie looked at her for a moment." in trozos, trozos


def test_la_comilla_de_cierre_llega_al_motor():
    """Hasta F5.8 el separador de frase se la comía: 29 veces en el episodio 1 de un canal."""
    trozos = split_narration('Ollie shouted, "Nora, wake up." Nora sat up very slowly.', 20, min_words=3)
    assert trozos[0] == 'Ollie shouted, "Nora, wake up."'


@pytest.mark.parametrize(
    "abre,cierra",
    [('"', '"'), ("“", "”"), ("«", "»")],
    ids=["recta", "tipografica", "latina"],
)
def test_las_tres_comillas_se_tratan_igual(abre, cierra):
    """Criterio 8. Un guion escrito en Word trae `“ ”` sin que nadie lo decida."""
    texto = (
        f"He opened the door of her room. Ollie shouted, {abre}Nora, wake up! It is time.{cierra} "
        "She sat up very slowly."
    )
    trozos = split_narration(texto, 20, agrupa_hasta=21, min_words=MIN_ORPHEUS)
    assert f"Ollie shouted, {abre}Nora, wake up! It is time.{cierra}" in trozos, trozos


def test_una_cita_de_varias_frases_se_mantiene_entera():
    """Criterio 4: no se parte por el punto de dentro mientras quepa en el techo de palabras."""
    texto = 'Nora smiled at her brother. Nora said, "I know. I have a plan." Under the bed, something moved.'
    trozos = split_narration(texto, 20, agrupa_hasta=21, min_words=MIN_ORPHEUS)
    assert 'Nora said, "I know. I have a plan."' in trozos, trozos


def test_una_cita_que_no_cabe_se_parte_por_sus_frases_y_no_por_las_comas():
    """El techo manda (por encima el motor acelera), pero el corte va donde menos se note.

    Caso real: la cita de 21 palabras de la lámina 2 del episodio 1 de un canal contra un techo de 20.
    Partiendo por cláusulas salía «Nora replied, "It's easy. Flour, eggs, sugar,» · «butter...».
    """
    texto = (
        "Nora replied, \"It's easy. Flour, eggs, sugar, butter. You mix them. "
        "You put them in the oven. You wait. That's all.\""
    )
    trozos = split_narration(texto, 20, agrupa_hasta=21, min_words=MIN_ORPHEUS)
    assert len(trozos) == 2, trozos
    assert not any(t.rstrip().endswith(",") for t in trozos), trozos
    assert trozos[0].startswith("Nora replied, \"It's easy.")


def test_dos_personajes_seguidos_no_comparten_bocado():
    """Con una marca de sí/no bastaba para mezclarlos: son «del mismo tipo» y se fundían."""
    texto = (
        'Then he said, "But we do not know how to make a cake." '
        'Nora replied, "It is easy. You only need flour and eggs and time."'
    )
    trozos = split_narration(texto, 20, agrupa_hasta=21, min_words=MIN_ORPHEUS)
    assert len(trozos) == 2, trozos
    assert trozos[0].startswith("Then he said,") and trozos[1].startswith("Nora replied,")


@pytest.mark.parametrize("sitio", ["principio", "medio", "final"])
def test_el_dialogo_se_aisla_este_donde_este_en_la_lamina(sitio):
    narracion_antes = "It was Saturday morning. The house was very quiet. He opened the door."
    narracion_despues = "Nora sat up very slowly. She looked at her brother. She said nothing."
    cita = 'Ollie shouted, "Nora, wake up!"'
    texto = {
        "principio": f"{cita} {narracion_antes} {narracion_despues}",
        "medio": f"{narracion_antes} {cita} {narracion_despues}",
        "final": f"{narracion_antes} {narracion_despues} {cita}",
    }[sitio]
    trozos = split_narration(texto, 20, agrupa_hasta=21, min_words=MIN_ORPHEUS)
    assert cita in trozos, trozos


def test_una_comilla_sin_cerrar_no_se_traga_la_lamina():
    """Criterio 8. Sin cierre no hay dónde acabar la línea, así que no se aísla nada: se trocea como antes.

    **La primera frase tiene 7 palabras a propósito, y esa es la prueba entera** (auditoría de F5.8,
    R1). Con «He opened the door.» —4 palabras— este control **no sabía fallar**: por debajo del
    mínimo de Orpheus, `_merge_tiny` funde esa frase con su vecina *sea cual sea* su marca de cita,
    así que los dos troceos daban el mismo bocado único y la comparación pasaba **también con el
    defecto puesto**. Demostrado con el mutante que hace justo lo que este criterio prohíbe —que una
    comilla sin pareja se trague el resto de la lámina—: la suite entera seguía en verde.

    Con siete palabras, el troceo sin defecto da 1 segmento y el mutado da 2, y la comparación se
    pone roja. Sin control negativo, «pasa» no distingue entre que funcione y que la prueba no sepa
    fallar.
    """
    texto = 'He opened the door of her room. Ollie shouted, "Nora, wake up! Nora sat up very slowly. She said nothing.'
    assert split_narration(texto, 20, agrupa_hasta=21, min_words=MIN_ORPHEUS) == _troceo_previo_a_F58(
        texto, 20, agrupa_hasta=21, min_words=MIN_ORPHEUS
    )


# --------------------------------------------------------------------------------------
# Lo que no puede romperse nunca
# --------------------------------------------------------------------------------------


def test_el_troceo_no_pierde_ni_inventa_una_sola_palabra():
    """La alineación empareja las palabras del guion con las marcas de la voz contando palabras: si el
    troceo perdiera un token, el karaoke y el `.srt` se descuadrarían enteros."""
    for receta in (RECETA_DOCUMENTAL, RECETA_FICCION):
        parametros = _receta(receta)
        for numero, texto in enumerate(LAMINAS_CON_DIALOGO + LAMINAS_SIN_DIALOGO, start=1):
            trozos = split_narration(texto, min_words=MIN_ORPHEUS, **parametros)
            assert " ".join(trozos).split() == texto.split(), (receta.name, numero)


def test_ningun_segmento_baja_del_minimo_del_motor():
    """El mínimo por llamada es del MOTOR (fila 127) y manda sobre aislar el diálogo: un segmento de
    2-3 palabras es el que no casa en el recorte por transcripción y tumbó la etapa el 08-09."""
    receta = _receta(RECETA_FICCION)
    cortos = []
    for numero, texto in enumerate(LAMINAS_CON_DIALOGO, start=1):
        for trozo in split_narration(texto, min_words=MIN_ORPHEUS, **receta):
            if len(sin_etiquetas(trozo).split()) < MIN_ORPHEUS:
                cortos.append((numero, trozo))
    assert not cortos, cortos
