"""Quién dice cada línea del guion, que es lo que decide de qué color se pinta.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_hablantes.py

**De dónde salen estas pruebas.** El episodio 1 de un canal se quemó con cinco líneas del color
equivocado, y las cinco eran del mismo tipo: una pregunta que hace el OTRO personaje. La peor,
«Stop cleaning. You are making it worse.» — la dice Nora y salía en el azul de Ollie. Un color
equivocado confunde más que ninguno: el espectador no tiene forma de saber que el vídeo miente.

**La condición que las hace valer** es que los casos son literales del guion aprobado, no ejemplos
inventados que el parser resuelve fácil. Y cada regla lleva su control negativo: sin él, «pasa» no
distingue entre «la regla acierta» y «este ejemplo no la ejercita».
"""

import pytest

from scripts.hablantes import tramos

# El reparto llega como {nombre: pronombre}, tal y como lo declara el perfil del canal.
REPARTO = {"Ollie": "he", "Nora": "she", "Mum": "she", "Dad": "he"}


def atribuye(texto, parrafos=None):
    """{cita: personaje} para poder afirmar sobre el texto y no sobre índices."""
    return {t["_texto"]: t["personaje"] for t in tramos(texto, REPARTO, parrafos)}


def cortes(*parrafos):
    """Índices de palabra donde arranca cada párrafo, y el texto aplanado que los acompaña."""
    indices, acumulado = [], 1
    for p in parrafos:
        indices.append(acumulado)
        acumulado += len(p.split())
    return " ".join(parrafos), indices


def test_la_atribucion_de_DELANTE_es_la_normal():
    assert atribuye('Ollie shouted, "Nora! Wake up!"') == {"Nora! Wake up!": "Ollie"}


def test_la_atribucion_de_DETRAS_solo_vale_si_la_cita_acaba_en_coma():
    """En inglés la coma va DENTRO de las comillas, y ese es el único caso en que lo de detrás manda.

    Sin esa condición, con el guion escrito con la atribución delante, lo que hay detrás de una cita
    es la atribución de la SIGUIENTE — que es como «Stop cleaning. You are making it worse.» acabó
    pintada de Ollie.
    """
    assert atribuye('"Get a cloth," said Mum, and she smiled.') == {"Get a cloth,": "Mum"}


def test_lo_que_hay_DETRAS_de_una_cita_cerrada_NO_la_atribuye():
    """Control negativo del anterior, y el defecto exacto que llegó al vídeo."""
    texto, indices = cortes(
        'Nora said, "Stop." "Stop cleaning. You are making it worse."',
        'Ollie said, "I know."',
    )
    dicho = atribuye(texto, indices)
    assert dicho["Stop cleaning. You are making it worse."] == "Nora"
    assert dicho["I know."] == "Ollie"


def test_una_cita_seguida_en_el_MISMO_parrafo_la_dice_el_mismo():
    """Es como se escribe un diálogo corrido: «Ollie said, "I know." "I can see that."»"""
    texto, indices = cortes('Ollie said, "I know." "I can see that."')
    assert atribuye(texto, indices) == {"I know.": "Ollie", "I can see that.": "Ollie"}


def test_una_cita_en_PARRAFO_NUEVO_es_el_turno_del_otro():
    """La misma forma en texto plano, y el significado contrario. Lo único que los separa es el corte.

    «How do you know that?» la pregunta Ollie, y sin la frontera de párrafo se pintaba de Nora
    porque venía justo detrás de dos citas suyas.
    """
    texto, indices = cortes(
        'Nora said, "First we take the flour off." "Then we use water."',
        '"How do you know that?"',
    )
    dicho = atribuye(texto, indices)
    assert dicho["Then we use water."] == "Nora"
    assert dicho["How do you know that?"] is None, "el parser no lo sabe, y NO se lo inventa"


def test_sin_los_parrafos_el_parser_se_equivoca():
    """Control negativo del anterior: demuestra que la frontera es lo que aporta la información.

    Si esta prueba pasara a acertar sin `parrafos`, sería que el acierto viene de otra cosa y la
    regla del párrafo estaría sin ejercitar.
    """
    texto, _ = cortes(
        'Nora said, "First we take the flour off." "Then we use water."',
        '"How do you know that?"',
    )
    assert atribuye(texto)["How do you know that?"] == "Nora", "sin la frontera, se la traga"


def test_una_accion_delante_tambien_atribuye():
    """«Ollie looked at the clock. "Mum usually wakes up at nine."» no lleva verbo de decir."""
    texto, indices = cortes('Ollie looked at the clock. "Mum usually wakes up at nine."')
    assert atribuye(texto, indices) == {"Mum usually wakes up at nine.": "Ollie"}


def test_un_nombre_DENTRO_de_una_cita_no_atribuye_nada():
    """Control negativo de la regla anterior: «Ollie said, "Mum." "Mum is coming."» la dice Ollie.

    Sin quitar las citas antes de buscar el nombre, la regla de acción se quedaba con «Mum», que es
    de quien se HABLA y no quien habla.
    """
    texto, indices = cortes('Ollie said, "Mum." "Mum is coming."')
    assert atribuye(texto, indices) == {"Mum.": "Ollie", "Mum is coming.": "Ollie"}


def test_el_pronombre_resuelve_una_cita_sin_nombre():
    """«"I know," she said» no nombra a nadie: la dice la última mujer nombrada."""
    texto, indices = cortes('Nora sat up slowly. "I know," she said.')
    assert atribuye(texto, indices) == {"I know,": "Nora"}


def test_el_pronombre_sale_del_PERFIL_y_no_de_una_tabla_del_estudio():
    """F4.9: el estudio conoce la gramática, no sabe quién es Nora.

    Con el reparto declarando a Nora en masculino, la regla del pronombre tiene que seguir al perfil
    aunque el resultado chirríe — que es la prueba de que el dato manda y no hay tabla escondida.
    """
    texto, indices = cortes('Nora sat up slowly. "I know," he said.')
    assert {t["_texto"]: t["personaje"] for t in tramos(texto, {"Nora": "he"}, indices)} == {"I know,": "Nora"}


def test_lo_que_no_se_puede_atribuir_se_marca_y_no_se_adivina():
    """Un `¿?` se resuelve mirando el guion; un color inventado se queda en el vídeo."""
    texto, indices = cortes("The house was very quiet.", '"Is there a cake in the oven?"')
    assert atribuye(texto, indices) == {"Is there a cake in the oven?": None}


@pytest.mark.parametrize(
    "texto",
    [
        "It was Saturday morning. The house was very quiet.",
        "Biscuit sat down. He looked very happy. He was completely white.",
    ],
)
def test_la_narracion_sin_dialogo_no_produce_tramos(texto):
    """Control negativo global: si el parser marcara narración, teñiría el vídeo de colores falsos."""
    assert tramos(texto, REPARTO, [1]) == []
