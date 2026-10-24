"""El emparejador del recorte por texto: qué tolera y, sobre todo, qué NO.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_voz_recorte.py

**De dónde sale.** `RecortadorPorTexto` corta lo que Orpheus dice después de acabar el texto,
localizando la última palabra pedida en la transcripción. Su primer emparejador exigía que **todas**
las palabras casaran exactas y en orden, y solo avanzaba al acertar: un único error del reconocedor
en MEDIO de la frase lo dejaba atascado y perdía todo lo de detrás. Medido sobre los 191 segmentos
del episodio 1: **155 de 191**, y los 36 restantes **matan el run** (`_genera_con_plausibilidad`
levanta `SystemExit` al agotar los reintentos). Addendum fila 114.

**Lo que estas pruebas protegen es la frontera, y la frontera tiene dos lados.** Que recorte más no
es el objetivo: el trabajo del recortador no es cortar, es **saber dónde acaba el texto pedido**. Un
emparejador que tolere lo que sea recortaría el 100 % siendo basura. Medido: la versión tolerante
**sin** exigir la última palabra recupera 190 de 191 pero **falsifica 88 de 191** — recorta el audio
de un segmento usando el texto de otro. Así que aquí se prueban las dos cosas a la vez, y los casos
de «no debe casar» son tan importantes como los de «debe casar».

**Los casos vienen del episodio real**, no inventados: `iron` oído como `IM`, `thirteen hundreds`
como `1300s`, `waxwork` partido en `wax work`.
"""

import pytest

from lib.voice_worker import RecortadorPorTexto

RECORTADOR = RecortadorPorTexto({"modelo": "openai/whisper-small", "margen_s": 0.15})


def marcas(*palabras: str, paso: float = 0.4) -> list[dict]:
    """Trozos con la forma que devuelve whisper, con marcas crecientes y regulares."""
    return [
        {"text": f" {p}", "timestamp": (round(i * paso, 2), round((i + 1) * paso, 2))} for i, p in enumerate(palabras)
    ]


def empareja(texto: str, oido: list[str]):
    """Devuelve (casadas, total, fin) con el criterio de producción."""
    pedidas = [RECORTADOR._normaliza(p) for p in texto.split() if not p.startswith("<")]
    pedidas = [p for p in pedidas if p]
    ms = RECORTADOR._empareja(pedidas, marcas(*oido))
    casadas = sum(1 for m in ms if m is not None)
    return casadas, len(pedidas), (ms[-1] if ms and ms[-1] is not None else None)


# --------------------------------------------------------------------------------------
# Lo que TIENE que casar: los tres fallos reales del episodio
# --------------------------------------------------------------------------------------


def test_un_error_en_medio_ya_no_pierde_el_resto_de_la_frase():
    """El caso que abrió la fila 114: `iron` oído como `IM` daba 2/17 y tiraba 15 palabras."""
    texto = "an upright iron case a hinged front and a story"
    oido = ["an", "upright", "IM", "case", "a", "hinged", "front", "and", "a", "story"]
    casadas, total, fin = empareja(texto, oido)
    assert fin is not None, "con la última palabra localizada tiene que recortar"
    assert casadas == total - 1, f"solo debe perderse la palabra mal transcrita ({casadas}/{total})"


def test_los_siglos_escritos_con_letra_casan_con_sus_digitos():
    """6 de los 7 fallos que quedaban eran esto: el canal escribe siglos, whisper devuelve dígitos."""
    for texto, oido in (
        ("Not the thirteen hundreds.", ["Not", "the", "1300s."]),
        ("Not the fifteen hundreds.", ["not", "the", "1500s."]),
        ("The Middle Ages end around fifteen hundred.", ["Middle", "Ages", "end", "around", "1500."]),
        ("eighteen hundreds.", ["1800"]),
    ):
        _, _, fin = empareja(texto, oido)
        assert fin is not None, f"{texto!r} contra {oido} tendría que casar"


def test_una_palabra_partida_en_dos_casa():
    """`waxwork` sale como `wax work`: dos trozos para una palabra pedida."""
    _, _, fin = empareja("Every film, every waxwork,", ["Every", "film,", "every", "wax", "work."])
    assert fin is not None


def test_el_corte_es_el_final_de_la_ULTIMA_palabra_pedida():
    """No el final del audio: lo que venga después es lo que hay que quitar."""
    texto = "keep one pair of dates"
    oido = ["keep", "one", "pair", "of", "dates", "and", "the", "rest", "is", "inventado"]
    _, _, fin = empareja(texto, oido)
    assert fin == pytest.approx(2.0), "la 5.ª palabra acaba en 2,0 s con paso de 0,4"


# --------------------------------------------------------------------------------------
# Lo que NO puede casar. Estos son los que impiden que el arreglo sea un aflojamiento.
# --------------------------------------------------------------------------------------


def test_CONTROL_NEGATIVO_el_texto_de_otro_segmento_no_recorta():
    """El control que tumbó al candidato tolerante: 88 falsos de 191 sin exigir la última palabra.

    El audio dice una cosa y se le pide otra del MISMO tema —comparten vocabulario, que es el caso
    difícil—: el recortador tiene que negarse, porque no sabe dónde acaba un texto que no se dijo.
    """
    oido = ["The", "iron", "maiden", "is", "not", "a", "medieval", "instrument."]
    for otro in (
        "There is no surviving record of anyone anywhere ever being punished inside one.",
        "By the eighteen hundreds it was an attraction with an admission charge.",
        "Keep one pair of dates.",
    ):
        _, _, fin = empareja(otro, oido)
        assert fin is None, f"no puede recortar con un texto que el audio no dice: {otro!r}"


def test_si_falta_la_ULTIMA_palabra_no_recorta_aunque_case_todo_lo_demas():
    """Es la línea que separa el arreglo del aflojamiento: sin el final no se sabe dónde cortar."""
    texto = "an upright iron case a hinged front"
    oido = ["an", "upright", "iron", "case", "a", "hinged", "FRENTE"]
    casadas, total, fin = empareja(texto, oido)
    assert casadas == total - 1, "casan todas menos la última"
    assert fin is None, "y por eso NO se recorta"


def test_un_audio_vacio_no_recorta():
    _, _, fin = empareja("an upright iron case", [])
    assert fin is None


def test_el_canonizador_iguala_numeros_y_solo_numeros():
    """Los siglos y los números sueltos; nada más.

    El número suelto **no estaba al principio y mató un run**: «the first thirty seconds» sale de
    whisper como «the first 30 seconds», el segmento agotó sus tres reintentos y el episodio murió
    en la lámina 1. Se añadió tras medir que no afloja ninguno de los dos controles (186 -> 187
    aciertos con 0 falsos y 0 cortes tempranos sobre los 191 segmentos reales).
    """
    assert RECORTADOR._canon(["thirteen", "hundreds"]) == "1300"
    assert RECORTADOR._canon(["1300s"]) == "1300"
    assert RECORTADOR._canon(["thirty"]) == "30"
    assert RECORTADOR._canon(["thirty", "seconds"]) == "30seconds"
    # **Los ordinales van en su propio espacio**, y esto es lo que impide el único falso positivo
    # que este canonizador podría introducir: sin el sufijo, «one» y «first» valdrían lo mismo.
    assert RECORTADOR._canon(["eighteenth"]) == "18o"
    assert RECORTADOR._canon(["18th"]) == "18o"
    assert RECORTADOR._canon(["eighteen"]) == "18"
    assert RECORTADOR._canon(["one"]) != RECORTADOR._canon(["first"])
    # lo que NO es número se queda intacto, que es lo que evita casar de más
    assert RECORTADOR._canon(["dates"]) == "dates"
    assert RECORTADOR._canon(["someone"]) == "someone"


def test_el_ordinal_desbloquea_el_segmento_que_mato_el_run_en_la_lamina_2():
    """«the end of the eighteenth century» sale de whisper como «the end of the 18th century»."""
    _, _, fin = empareja(
        "It first appears in the written record at the end of the eighteenth century,",
        "It first appears in the written record at the end of the 18th century.".split(),
    )
    assert fin is not None


def test_el_numero_suelto_desbloquea_el_segmento_que_mato_un_run():
    """El caso literal: lámina 1, segmento 3/7 del episodio 1."""
    _, _, fin = empareja(
        "So let us put the problem in the first thirty seconds.",
        ["So", "let", "us", "put", "the", "problem", "in", "the", "first", "30", "seconds."],
    )
    assert fin is not None, "sin tratar el número suelto, esto agota los reintentos y para el run"


def test_la_ventana_vale_4_y_no_6_por_el_control_negativo():
    """El número no es de gusto: con 6 aparece un falso positivo sobre los 191 segmentos reales."""
    assert RecortadorPorTexto.VENTANA == 4


def test_CONTROL_DE_COLA_una_palabra_final_repetida_NO_adelanta_el_corte():
    """El fallo que una auditoría encontró en la primera versión de `_empareja`, y es el peor de todos.

    Si la tolerancia alcanza la última palabra, un trozo que normalice igual que ella la casa **antes
    de tiempo**: el corte se clava ahí y **se come el resto del habla**. Y no lo caza nada — el audio
    sale más CORTO, así que la banda de ritmo `[40, 320]` wpm no se queja, y `recortado` dice `True`.
    No se oye hasta que el vídeo está montado.

    Medido con el control que lo reproduce a propósito: sin la guarda corta antes en **178 de 179**
    casos derivados de los segmentos reales; con ella, en **0**.

    Este es el caso literal del informe: «charge» aparece dos veces y la primera está justo donde el
    emparejador la va a mirar, porque «with» viene detrás de «attraction» en el guion.
    """
    texto = "it was an attraction with an admission charge"
    oido = ["it", "was", "an", "attraction", "charge", "an", "admission", "charge"]
    _, _, fin = empareja(texto, oido)
    # el habla acaba con el 8.º trozo, en 3,2 s con paso de 0,4
    assert fin is None or fin == pytest.approx(3.2), (
        f"no puede cortar en la PRIMERA «charge» (2,0 s): cortaría en {fin} y se comería 1,2 s de habla"
    )


def test_saltar_a_la_penultima_sigue_permitido():
    """La guarda de la cola no puede llevarse la tolerancia del medio por delante."""
    texto = "a story about medieval justice that everybody has heard"
    oido = ["a", "story", "about", "medieval", "justice", "that", "EVERYBUDDY", "has", "heard"]
    casadas, total, fin = empareja(texto, oido)
    assert fin is not None, "la última palabra casa sin salto, así que tiene que recortar"
    assert casadas == total - 1


# ---------------------------------------------------------------------------------------------
# El canal narra en INGLÉS BRITÁNICO y whisper transcribe en AMERICANO (12-09-2026)
# ---------------------------------------------------------------------------------------------
# El guion del canal narra en británico —`panelled`, `travelled`, `labour`— y whisper escribe en
# americano por defecto cuando el audio no le da indicios. Si una de esas cae en mitad de la frase,
# la última palabra queda inalcanzable (a la última no se le salta) y la etapa entera muere.
#
# OJO con la historia: esto se añadió creyendo que era la causa del run que murió el 12-09 en
# «A fanlight over a panelled door» (4/6). **Medido después, no lo era**: whisper escribe `panelled`
# en británico sin ayuda. La divergencia que cubre esta normalización es real y posible, pero el
# fallo de aquel día quedó sin explicar. No se le atribuye un arreglo que no hizo.


@pytest.mark.parametrize(
    "britanico,americano",
    [
        ("panelled", "paneled"),
        ("travelled", "traveled"),
        ("cancelled", "canceled"),
        ("labelling", "labeling"),
        ("labour", "labor"),
        ("honour", "honor"),
        ("neighbour", "neighbor"),
    ],
)
def test_la_ortografia_britanica_casa_con_la_americana(britanico: str, americano: str) -> None:
    from lib.voice_worker import RecortadorPorTexto

    assert RecortadorPorTexto._normaliza(britanico) == RecortadorPorTexto._normaliza(americano)


@pytest.mark.parametrize(
    "una,otra",
    [
        ("latter", "later"),  # el par que obliga a limitarse a la doble ELE y no a cualquier doble
        ("holly", "holy"),
        ("bitter", "biter"),
        ("filled", "field"),
        ("door", "dour"),
    ],
)
def test_dos_palabras_distintas_siguen_sin_casar(una: str, otra: str) -> None:
    """CONTROL NEGATIVO: sin esto, «tolerar la ortografía» podría degenerar en casar cualquier cosa.

    Casar de más es peor que casar de menos: el emparejador cortaría el audio por donde no toca, y
    eso no se oye hasta que el vídeo está montado.
    """
    from lib.voice_worker import RecortadorPorTexto

    assert RecortadorPorTexto._normaliza(una) != RecortadorPorTexto._normaliza(otra)


# ---------------------------------------------------------------------------------------------
# Las CIFRAS de un explicador de economía (F7.10, fila 262)
# ---------------------------------------------------------------------------------------------
# La cata de un canal de economía dio 4 incidencias en 15 segmentos, todas en frases con cifras (fila 261): el
# guion dice «one hundred ninety-seven dollars» y whisper escribe «$197», y esos segmentos quedaban sin recortar la
# divagación de Orpheus. Los casos de abajo son las transcripciones literales de aquella cata.


@pytest.mark.parametrize(
    "texto,oido",
    [
        (
            "Picture one hundred dollars in a piggy bank that pays interest.",
            ["Picture", "$100", "in", "a", "piggy", "bank", "that", "pays", "interest."],
        ),
        ("One hundred dollars, growing at seven percent a year.", ["$100,", "growing", "at", "7%", "a", "year."]),
        (
            "After ten years, it is about one hundred ninety-seven dollars.",
            ["After", "10", "years,", "it", "is", "about", "$197."],
        ),
        # Sin «dollars» en el guion: el «$» lo pone whisper porque la frase habla de dinero.
        ("After thirty years, about seven hundred sixty-one.", ["after", "30", "years,", "about", "$761."]),
        ("It costs three thousand two hundred dollars.", ["It", "costs", "$3,200."]),
        ("Twenty one of them, and twenty-one more.", ["21", "of", "them,", "and", "21", "more."]),
        ("about a hundred years", ["about", "100", "years"]),
        ("in the twenty-first century", ["in", "the", "21st", "century"]),
        ("one hundred and ninety-seven dollars", ["197", "dollars"]),
    ],
)
def test_las_cifras_dichas_con_palabras_casan_con_sus_digitos(texto, oido):
    _, _, fin = empareja(texto, oido)
    assert fin is not None, f"{texto!r} contra {oido} tendría que casar"


@pytest.mark.parametrize(
    "dicho,oido,por_que",
    [
        ("one hundred ninety-seven", "179", "otra cifra con los mismos dígitos"),
        ("one hundred ninety-seven", "1097", "otra cifra que los contiene"),
        ("seven percent", "$7", "un porcentaje no es dinero"),
        ("seven dollars", "7%", "ni el dinero un porcentaje"),
        ("seven", "7%", "el «%» es una palabra dicha: sin «percent» en el guion no casa"),
        ("one hundred ninety-seven dollars", "197", "si el guion dice «dollars», el trozo sin ellos no basta"),
        ("seven", "7th", "un cardinal no es un ordinal"),
        ("seventh", "7", "ni al revés"),
        ("one hundred", "100th", "una centena no es su ordinal"),
        ("one hundredth", "100", "ni al revés"),
        ("seventy-five percent", "7.5%", "el punto decimal no se pierde al normalizar"),
        ("twenty one", "201", "decena y unidad son UN número, no dos pegados"),
    ],
)
def test_CONTROL_NEGATIVO_una_cifra_distinta_no_casa(dicho, oido, por_que):
    pedidas = [RECORTADOR._normaliza(p) for p in dicho.split()]
    assert not RECORTADOR._casan(RECORTADOR._canon(pedidas), RECORTADOR._canon([RECORTADOR._normaliza(oido)]), ""), (
        por_que
    )


def test_CONTROL_NEGATIVO_el_texto_de_otra_frase_con_cifras_no_recorta():
    """El control de siempre en el terreno nuevo: dos frases de la cata, gemelas salvo por la cifra."""
    oido = ["After", "20", "years,", "about", "$387."]
    for otro in ("After ten years, it is about one hundred ninety-seven dollars.",
                 "After thirty years, about seven hundred sixty-one."):  # fmt: skip
        _, _, fin = empareja(otro, oido)
        assert fin is None, f"no puede recortar con un texto que el audio no dice: {otro!r}"


def test_lo_que_ya_casaba_sigue_igual():
    """Siglos, años dichos en dos números, números sueltos y ordinales: las formas de antes no cambian."""
    assert RECORTADOR._canon(["the", "seventeen", "hundreds"]) == "the1700"
    assert RECORTADOR._canon(["nineteen", "fifty"]) == RECORTADOR._canon(["1950"]) == "1950"
    assert RECORTADOR._canon(["one", "second"]) == "12o"
    assert RECORTADOR._canon(["two", "three"]) == "23"
    assert RECORTADOR._canon(["hundred"]) == "hundred" and RECORTADOR._canon(["a"]) == "a"


def test_una_cifra_larga_solo_vale_si_todo_el_tramo_es_cifra():
    """La holgura de PALABRAS_POR_CIFRA no alcanza a un tramo con palabras normales: ese sigue en 3."""
    assert RECORTADOR._cabe_en_una_cifra(["one", "hundred", "ninetyseven", "dollars"])
    assert not RECORTADOR._cabe_en_una_cifra(["one", "hundred", "ninetyseven", "years"])
    assert not RECORTADOR._cabe_en_una_cifra(["and", "a", "and", "a"]), "sin un número no es una cifra"


# ---------------------------------------------------------------------------------------------
# Las cantidades en DÍGITOS con la unidad aparte (canal de economía, 06-10-2026)
# ---------------------------------------------------------------------------------------------
# El guion de ese canal escribe «92.3%» y «$8.1 billion»; whisper oye lo mismo y lo escribe «92.3 percent» y «8.1
# billion dollars». En el episodio 1 (run 2026-10-06_211205), 8 de las 10 incidencias de la voz eran esto, y una
# recortó por silencio y se comió «$10.4 billion». Los casos son las transcripciones literales de whisper-small
# sobre aquel audio. Aquí se empareja como en producción: con `_prepara`, que une las cantidades a los dos lados.


def empareja_como_en_produccion(texto: str, oido: list[str]):
    """(casadas, total, fin, trozos) pasando por `_prepara`, como `corta`."""
    pedidas, trozos = RECORTADOR._prepara(texto, marcas(*oido))
    ms = RECORTADOR._empareja(pedidas, trozos)
    casadas = sum(1 for m in ms if m is not None)
    return casadas, len(pedidas), (ms[-1] if ms and ms[-1] is not None else None), trozos


@pytest.mark.parametrize(
    "texto,oido",
    [
        (
            "In the United States and Canada, the renewal rate was 92.3%.",
            ["In", "the", "United", "States", "and", "Canada,", "the", "renewal", "rate", "was", "92.3", "percent."],
        ),
        (
            "Divide it by net income for the same year, $8.1 billion.",
            ["Divide", "it", "by", "net", "income", "for", "the", "same", "year,", "8.1", "billion", "dollars."],
        ),
        (
            "Start with operating income for the 2025 fiscal year, $10.4 billion.",
            [
                "Start",
                "with",
                "operating",
                "income",
                "for",
                "the",
                "2025",
                "fiscal",
                "year,",
                "10.4",
                "billion",
                "dollars.",
            ],
        ),  # fmt: skip
        ("The result is about 1.9%.", ["The", "result", "is", "about", "1.9", "percent."]),
        ("The result is about 1.9%.", ["The", "result", "is", "about", "1.9", "per", "cent."]),
        ("A fee of $65.", ["A", "fee", "of", "65", "dollars."]),
        # Lo que ya casaba no se rompe: whisper también escribe la forma del guion.
        (
            "Take the fee revenue for the 2025 fiscal year, $5.3 billion.",
            ["Take", "the", "fee", "revenue", "for", "the", "2025", "fiscal", "year,", "$5.3", "billion."],
        ),
        ("The result is about 1.9%.", ["The", "result", "is", "about", "1.9%."]),
    ],
)
def test_una_cantidad_con_la_unidad_aparte_casa_con_la_del_guion(texto, oido):
    _, _, fin, _ = empareja_como_en_produccion(texto, oido)
    assert fin is not None, f"{texto!r} contra {oido} tendría que casar"


def test_el_corte_cae_detras_de_la_unidad_y_no_antes():
    """Si el corte cayera en «billion», se comería «dollars»: la marca unida acaba donde acababa la unidad."""
    oido = ["Divide", "it", "by", "net", "income", "for", "the", "same", "year,", "8.1", "billion", "dollars.", "and",
            "then", "more"]  # fmt: skip
    _, _, fin, _ = empareja_como_en_produccion("Divide it by net income for the same year, $8.1 billion.", oido)
    assert fin == pytest.approx(12 * 0.4), "«dollars.» es el 12.º trozo y acaba en 4,8 s con paso de 0,4"
    _, _, fin, _ = empareja_como_en_produccion(
        "The result is about 1.9%.", ["The", "result", "is", "about", "1.9", "percent.", "and", "more"]
    )
    assert fin == pytest.approx(6 * 0.4), "«percent.» es el 6.º trozo"


@pytest.mark.parametrize(
    "texto,oido,por_que",
    [
        ("The renewal rate was 92.3%.", ["The", "renewal", "rate", "was", "93.2", "percent."], "otra cifra"),
        ("Net income was $8.1 billion.", ["Net", "income", "was", "8.1", "million", "dollars."], "otra escala"),
        ("The result is about 1.9%.", ["The", "result", "is", "about", "1.9", "dollars."], "dinero no es porcentaje"),
        ("A fee of $65.", ["A", "fee", "of", "65", "percent."], "ni un porcentaje dinero"),
        ("It rose about 7.5%.", ["It", "rose", "about", "75", "percent."], "el decimal no se pierde al unir"),
        (
            "Take the fee revenue for the 2025 fiscal year, $5.3 billion.",
            ["Divide", "it", "by", "net", "income", "for", "the", "same", "year,", "8.1", "billion", "dollars."],
            "el texto de la frase vecina de la misma lámina, con su cifra",
        ),
    ],
)
def test_CONTROL_NEGATIVO_una_cantidad_unida_distinta_no_recorta(texto, oido, por_que):
    _, _, fin, _ = empareja_como_en_produccion(texto, oido)
    assert fin is None, por_que


def trozos_reales(*textos: str, paso: float = 0.4) -> list[dict]:
    """Trozos con el texto TAL CUAL lo da whisper, espacio inicial incluido (a diferencia de `marcas`)."""
    return [{"text": t, "timestamp": (round(i * paso, 2), round((i + 1) * paso, 2))} for i, t in enumerate(textos)]


# Lo que whisper-small devolvió palabra a palabra sobre el episodio 2 de ese canal (07-10-2026): la cifra partida en dos
# trozos, y el segundo sin espacio porque continúa la palabra. Era la última palabra de 7 incidencias de su voz.
_LAMINA_15 = (" Fast", " food", " went", " from", " about", " 184", " to", " about", " 255,", " a", " rise", " of",
              " about", " 38", ".4%.")  # fmt: skip


def test_una_cifra_partida_en_trozos_por_whisper_casa_y_corta_al_final_del_ultimo():
    pedidas, trozos = RECORTADOR._prepara("Fast food went from about 184 to about 255... a rise of about 38.4%.",
                                          trozos_reales(*_LAMINA_15, " and", " more"))  # fmt: skip
    marcas_ = RECORTADOR._empareja(pedidas, trozos)
    assert marcas_[-1] == pytest.approx(15 * 0.4), "«.4%.» es el 15.º trozo: el corte cae al final de la cifra"
    _, trozos = RECORTADOR._prepara("about 38.4%", trozos_reales(" about", " 38", ".4", "%"))
    assert [t["text"] for t in trozos] == ["about", "38p4pct"], "tres trozos de una palabra son una palabra"


def test_CONTROL_NEGATIVO_una_cifra_partida_distinta_no_casa():
    pedidas, trozos = RECORTADOR._prepara("a rise of about 38.4%.", trozos_reales(" a", " rise", " of", " about", " 38",
                                                                                   ".5%."))  # fmt: skip
    assert RECORTADOR._empareja(pedidas, trozos)[-1] is None, "38.5 % no es 38.4 %"


def test_los_trozos_con_espacio_no_se_unen():
    """Solo se une lo que whisper marca como resto de la misma palabra: dos palabras siguen siendo dos."""
    _, trozos = RECORTADOR._prepara("about 38 dollars", trozos_reales(" about", " 38", " dollars"))
    assert [t["text"] for t in trozos] == ["about", "38usd"], "y «38» + «dollars» se une como cantidad, no como trozo"
    _, trozos = RECORTADOR._prepara("the year 2025", trozos_reales(" the", " year", " 2025."))
    assert [t["text"] for t in trozos] == ["the", "year", "2025"]


def test_unir_cantidades_solo_toca_un_numero_y_la_unidad_que_lo_sigue():
    une = RECORTADOR._une_cantidades
    assert une([("2025", None), ("fiscal", None), ("year", None)]) == [
        ("2025", None),
        ("fiscal", None),
        ("year", None),
    ], "un año seguido de una palabra no es una cantidad"
    assert une([("8p1", None), ("billion", None)]) == [("8p1", None), ("billion", None)], "sin moneda no hay usd"
    assert une([("8p1usd", None), ("billion", None)]) == [("8p1usd", None), ("billion", None)], "ya unida"
    assert une([("seven", None), ("percent", None)]) == [("seven", None), ("percent", None)], (
        "las cifras con palabras las sigue juntando `_canon`, como antes"
    )
    assert une([("92p3", (1.0, 1.5)), ("percent", (1.5, 2.0))]) == [("92p3pct", (1.0, 2.0))]
