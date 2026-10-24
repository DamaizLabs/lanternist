"""La limpieza del audio por las marcas del alineador, y por qué el nivel solo no bastaba.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_limpia_voz.py

**De dónde sale.** Cuatro vueltas de audio, y el mismo muro cada vez: lo que suena en las
pausas es lo que Chatterbox genera al quedarse sin texto, y **por nivel es indistinguible del final
de una palabra**. Los dos son flojos, duran un par de décimas y mueren contra el silencio. El filtro
por decibelios del 06-09 se comió la «nt» de «important» —«dice "importa" y el "nt" no lo
pronuncia»— y la medición lo confirmó al milisegundo: 6,86 a 7,16 s de la lámina 1.

Lo que sí los separa es saber dónde hay palabras. Estas pruebas fijan las dos mitades: que la cola
se calla y que **la «nt» no**, porque cae dentro de una palabra que el alineador reconoció.
"""

import pytest

torch = pytest.importorskip("torch")

from lib.limpia_worker import fuera_de_la_voz, limpia, voz  # noqa: E402

SR = 24000
# **Los mismos números que se entregan, y eso no es cosmética.** Este bloque decía
# `cola_minima_ms: 500` y `cabeza_minima_ms: 300` mientras la receta de un canal entregaba 700 y 150, así
# que los controles negativos certificaban un filtro que no era el que sale en el vídeo — la
# auditoría del 06-09 midió el hueco: a 150 se atenúan 20 cabezas y a 300, cuatro. Cuando un control
# depende del umbral, además, se ejecuta con el de CADA receta declarada (ver `recetas_declaradas`).
AJUSTES = {
    "margen_ms": 120,
    "techo_db": -18,
    "minimo_ms": 250,
    "cola_caida_db": 20,
    "cola_minima_ms": 700,
    "cabeza_minima_ms": 500,
    "isla_techo_db": -22,
    "isla_minima_ms": 200,
    "muletilla_maxima_ms": 2500,
}


def recetas_declaradas():
    """Las limpiezas que los canales entregan de verdad, para probar contra ellas y no contra un ideal."""
    import json

    salida = []
    from canales_de_prueba import recetas_a_comprobar

    for ruta in recetas_a_comprobar():
        ajustes = json.loads(ruta.read_text(encoding="utf-8"))["segmentacion"].get("limpieza_por_marcas")
        if ajustes:
            salida.append(pytest.param(ajustes, id=ruta.parent.parent.name))

    # **Desde el 14-09-2026 puede no haber NINGUNA, y es una decisión.** El único canal que lo
    # declaraba (`limpieza_por_marcas`) lo retiró ese día: el filtro borró 5,6 s de narración de
    # un episodio ya subido (la frase «Then they heard feet…» de la lámina 5), porque calla lo que
    # el guion no dice y depende de que el reconocedor ancle bien. El otro nunca lo usó.
    #
    # **El mecanismo sigue en `lib/limpia_voz.py` y hay que seguir probándolo**: está disponible
    # para el canal que lo necesite, y los umbrales retirados se conservaban en la receta de ese canal
    # (`_umbrales_del_filtro_retirado_14_09`) por si vuelve.
    #
    # Lo que cambia es de dónde salen los ajustes de prueba: **del propio fichero de pruebas y no de
    # la configuración de un canal**. Que las pruebas de una pieza del ESTUDIO dependieran de lo que
    # un canal declare es la misma fuga de capa que F5.6 cerró en el verificador de guion — aquí se
    # veía como una suite entera que deja de coleccionar porque un canal cambió de opinión.
    if not salida:
        salida.append(pytest.param(AJUSTES_DE_REFERENCIA, id="referencia-del-estudio"))

    # **Sin casos no hay control, y eso NO puede salir en verde.** pytest colecciona cero casos de
    # una prueba parametrizada con lista vacía y la da por buena, que es el mismo modo de fallo que
    # este fichero lleva dos rondas persiguiendo: un control que no existe se ve igual que uno que
    # pasa. La guarda se queda, aunque ahora sea imposible llegar a ella con el respaldo de arriba.
    assert salida, "sin ajustes de limpieza no hay control negativo de la cabeza"
    return salida


# Los diez umbrales con los que el filtro funcionaba, tal como los declaraba ese canal hasta el 14-09-2026
# (conservados en su receta bajo `_umbrales_del_filtro_retirado_14_09`). Viven aquí para que las
# pruebas del mecanismo no dependan de que algún canal lo tenga activo.
AJUSTES_DE_REFERENCIA = {
    "modelo_alineacion": "openai/whisper-small",
    "margen_ms": 120,
    "techo_db": -18,
    "minimo_ms": 250,
    "cola_caida_db": 20,
    "cola_minima_ms": 700,
    "isla_techo_db": -22,
    "isla_minima_ms": 200,
    "cabeza_minima_ms": 500,
    "muletilla_maxima_ms": 2500,
}


def tono(segundos, amplitud=0.5):
    n = int(SR * segundos)
    t = torch.arange(n, dtype=torch.float32) / SR
    return amplitud * torch.sin(2 * torch.pi * 220 * t)


def silencio(segundos):
    return torch.zeros(int(SR * segundos), dtype=torch.float32)


def nivel(x):
    return float(x.abs().max())


# --- los tramos de voz ---------------------------------------------------------------------------


def test_las_palabras_se_ensanchan_con_margen():
    """Las marcas recortan por donde baja la energía, así que el borde real cae FUERA de la marca.

    Sin margen, la «s» que se apaga y la oclusiva que arranca quedan desprotegidas — y son justo lo
    que suena flojo, que es lo que el filtro busca.
    """
    tramos = voz([{"desde": 1.0, "hasta": 1.5}], margen=0.12, hasta_el_final=10.0)
    assert tramos == [(pytest.approx(0.88), pytest.approx(1.62))]


def test_dos_palabras_seguidas_se_funden_en_un_tramo():
    """Entre dos palabras de una misma frase no hay nada que callar."""
    marcas = [{"desde": 1.0, "hasta": 1.5}, {"desde": 1.55, "hasta": 2.0}]
    assert len(voz(marcas, margen=0.12, hasta_el_final=10.0)) == 1


def test_el_margen_no_se_sale_del_audio():
    tramos = voz([{"desde": 0.0, "hasta": 0.3}], margen=0.12, hasta_el_final=0.35)
    assert tramos[0][0] == 0.0 and tramos[0][1] == pytest.approx(0.35)


def test_lo_que_queda_entre_palabras_es_el_complemento():
    huecos = fuera_de_la_voz([(1.0, 2.0), (3.0, 4.0)], total=5.0)
    assert huecos == [(0.0, 1.0), (2.0, 3.0), (4.0, 5.0)]


# --- la limpieza ---------------------------------------------------------------------------------


def test_una_cola_fuera_de_toda_palabra_se_calla():
    """El caso que se oyó: suena flojo, dura medio segundo y el alineador no reconoció nada ahí."""
    señal = torch.cat([tono(1.0), tono(0.6, amplitud=0.5 * 10 ** (-25 / 20)), silencio(0.4)])
    marcas = [{"desde": 0.0, "hasta": 1.0}]
    limpio, tramos = limpia(señal, SR, marcas, AJUSTES)
    assert nivel(limpio[int(SR * 1.3) : int(SR * 1.5)]) == 0.0
    assert any(t["callado"] for t in tramos)


def test_la_NT_DE_IMPORTANT_no_se_toca():
    """**El control que da sentido a todo esto.**

    Es el mismo audio que el caso anterior —flojo, largo, muriendo contra el silencio— y aquí NO se
    calla, porque el alineador sí reconoció la palabra que lo contiene. Ese es el dato que el nivel
    no tiene y que hizo fracasar los dos filtros anteriores.
    """
    # 220 ms es lo que mide de verdad la «nt» de «important» en el audio del episodio
    señal = torch.cat([tono(1.0), tono(0.22, amplitud=0.5 * 10 ** (-25 / 20)), silencio(0.4)])
    marcas = [{"desde": 0.0, "hasta": 1.22}]  # la marca cubre la palabra entera, cola incluida
    limpio, tramos = limpia(señal, SR, marcas, AJUSTES)
    assert torch.equal(limpio[: int(SR * 1.22)], señal[: int(SR * 1.22)])
    assert not any(t["callado"] and t["desde"] < 1.22 for t in tramos)


def test_una_COLA_larga_dentro_de_la_palabra_si_se_apaga():
    """**El ruido que sobrevivió a todo lo demás**, y el contraste con la prueba de arriba.

    Es el mismo audio —flojo, dentro de la marca de una palabra— y aquí sí se apaga, porque dura
    más de `cola_minima_ms`. Whisper marcaba «Mum.» hasta el segundo 5,68 y la palabra sonaba hasta
    4,86: lo de en medio era 1,44 s de murmullo. Un fonema final no dura eso: la «nt» de «important»
    mide 220 ms y la de «quiet.» 400, mientras que las colas van de 520 a 1860.
    """
    señal = torch.cat([tono(1.0), tono(0.9, amplitud=0.5 * 10 ** (-25 / 20)), silencio(0.4)])
    marcas = [{"desde": 0.0, "hasta": 1.9}]
    limpio, _ = limpia(señal, SR, marcas, AJUSTES)
    assert nivel(limpio[int(SR * 1.8) : int(SR * 1.9)]) < 0.001, "el final de la cola llega apagado"
    assert torch.equal(limpio[: int(SR * 1.0)], señal[: int(SR * 1.0)]), "y la palabra, intacta"


def test_un_tramo_que_suena_FUERTE_fuera_de_las_palabras_se_respeta():
    """Ahí es donde el reconocedor se perdió, y perder habla es peor que dejar un ruido.

    En este mismo episodio whisper colapsó nueve palabras en un instante (addendum fila 83). Si el
    filtro se fiara solo de «no hay marca», se habría comido esas nueve.
    """
    señal = torch.cat([tono(1.0), tono(0.6), silencio(0.4)])
    limpio, tramos = limpia(señal, SR, [{"desde": 0.0, "hasta": 1.0}], AJUSTES)
    assert torch.equal(limpio, señal)
    assert [t for t in tramos if not t["callado"]], "y queda anotado para poder mirarlo"


def test_un_hueco_CORTO_no_se_toca():
    """Por debajo del mínimo puede ser el desvanecido de una sílaba que la marca no cubrió."""
    señal = torch.cat([tono(1.0), tono(0.1, amplitud=0.5 * 10 ** (-25 / 20)), tono(1.0)])
    limpio, _ = limpia(señal, SR, [{"desde": 0.0, "hasta": 1.0}, {"desde": 1.1, "hasta": 2.1}], AJUSTES)
    assert torch.equal(limpio, señal)


def test_la_limpieza_NO_cambia_la_duracion():
    """Silencia, no corta: si moviera el audio, el karaoke que se alinea después se descuadraría."""
    señal = torch.cat([tono(1.0), tono(0.6, amplitud=0.01), silencio(0.4)])
    limpio, _ = limpia(señal, SR, [{"desde": 0.0, "hasta": 1.0}], AJUSTES)
    assert limpio.numel() == señal.numel()


def test_sin_marcas_no_se_toca_nada():
    """Control negativo: si el alineador no devuelve nada, callarlo todo borraría la lámina entera."""
    señal = torch.cat([tono(1.0), silencio(0.5)])
    limpio, tramos = limpia(señal, SR, [], AJUSTES)
    assert torch.equal(limpio, señal) and tramos == []


def test_las_recetas_de_los_dos_canales_declaran_su_limpieza():
    """F4.9: sin defecto. Un canal con Kokoro, que no deja colas; heredar el filtro solo añadiría riesgo.

    **Y la lista de claves no se escribe aquí.** Sale de `limpia_voz.CLAVES_DE_LIMPIEZA`, que es la
    que lee el filtro: escrita a mano, esta prueba y el guardián de `voice_client` se quedaron
    cortos por separado —a él le faltaban las tres que gobiernan borrado de audio— y una lista corta
    es un umbral que no llega al worker, que es el defecto de la fila 98.
    """
    import json

    from canales_de_prueba import recetas_a_comprobar

    from lib.limpia_voz import CLAVES_DE_LIMPIEZA

    for ruta in recetas_a_comprobar():
        segmentacion = json.loads(ruta.read_text(encoding="utf-8"))["segmentacion"]
        assert "limpieza_por_marcas" in segmentacion, f"{ruta} no declara `limpieza_por_marcas`"
        ajustes = segmentacion["limpieza_por_marcas"]
        if ajustes:
            assert set(ajustes) >= set(CLAVES_DE_LIMPIEZA), ruta


def test_las_claves_declaradas_son_LAS_QUE_EL_CODIGO_LEE():
    """Cruza `CLAVES_DE_LIMPIEZA` con los `ajustes["..."]` que aparecen en el código, leyendo el AST.

    **Es el vigilante que convierte la fila 98 en rojo antes del commit.** Ese defecto —un umbral
    nuevo que no llega al worker y un filtro apagado en silencio— se arregló pasando los ajustes
    enteros, y la lista de claves obligatorias quedó como el sitio donde se puede volver a colar:
    quien añada un umbral al worker y no lo declare aquí deja al canal sin obligación de escribirlo,
    y el run revienta con `KeyError` en mitad de una etapa en vez de parar en el `--check`.

    Mismo patrón que `tests/test_capas.py`: la regla escrita no basta, la hace cumplir una prueba
    que lee el código.
    """
    import ast
    from pathlib import Path

    from lib.limpia_voz import CLAVES_DE_LIMPIEZA

    leidas = set()
    for fichero in ("lib/limpia_worker.py", "lib/limpia_voz.py"):
        arbol = ast.parse(Path(fichero).read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if (
                isinstance(nodo, ast.Subscript)
                and isinstance(nodo.value, ast.Name)
                and nodo.value.id == "ajustes"
                and isinstance(nodo.slice, ast.Constant)
                and isinstance(nodo.slice.value, str)
            ):
                leidas.add(nodo.slice.value)

    assert leidas == set(CLAVES_DE_LIMPIEZA), (
        f"el código lee {sorted(leidas)} y la receta obliga a declarar {sorted(CLAVES_DE_LIMPIEZA)}; "
        "lo que sobra es un número que nadie usa y lo que falta es un filtro que se apagará en silencio"
    )


# --- la muletilla que el motor se inventa ---------------------------------------------------------


def _como_en_produccion(guion: str, marcas: list[dict]) -> dict:
    """Arma el trabajo del worker **por el mismo camino que el pipeline**, no a mano.

    Es la corrección que pidió la auditoría del 06-09, y no es un detalle de estilo: la prueba
    anterior construía `marcas` sin la marca del sobrante y `sobrantes` aparte, un estado que
    `_un_item` **no puede producir** —si el alineador oyó el «Um…», su marca está en `marcas`—. Con
    el estado real, el tramo del sobrante caía dentro de la zona protegida, no había hueco ahí y la
    rama que lo calla no llegaba a evaluarse: **15 muletillas de 15 seguían sonando en el vídeo** y
    la prueba pasaba en verde.
    """
    from lib.limpia_voz import _un_item

    return _un_item({"audio": "x.wav"}, marcas, guion, minimo_s=0.25, techo_muletilla_s=2.5)


def _muletillas_de(trabajo: dict) -> list[str]:
    """Solo las muletillas: `_un_item` añade además la cola del final, que aquí no es lo que se mira."""
    return [s["texto"] for s in trabajo["sobrantes"] if not s["texto"].startswith("(")]


def test_una_marca_que_el_guion_NO_tiene_se_calla_aunque_suene_fuerte():
    """**El caso que resolvió el problema**, ahora por el camino real.

    El «Um…» de la lámina 4 duraba 1,82 s y sonaba a −0,8 dB: casi a plena voz. Ningún filtro por
    decibelios lo caza, porque suena tan fuerte como la narración. Lo que lo delata es que el guion
    no lo tiene — es la señal que se describió al hablar de video-use: «detecta muletillas».
    """
    señal = torch.cat([tono(1.0), tono(0.5, amplitud=0.9), tono(1.0)])
    marcas = [
        {"texto": "Ollie", "desde": 0.0, "hasta": 1.0},
        {"texto": "Um…", "desde": 1.0, "hasta": 1.5},
        {"texto": "opened", "desde": 1.5, "hasta": 2.5},
    ]
    trabajo = _como_en_produccion("Ollie opened", marcas)

    assert _muletillas_de(trabajo) == ["Um…"], "el guion no dice «Um…» en ninguna parte"
    assert [m["texto"] for m in trabajo["marcas"]] == ["Ollie", "opened"], (
        "y su marca SALE de la zona protegida: si no, el worker no ve el hueco y no la calla nunca"
    )

    limpio, tramos = limpia(señal, SR, trabajo["marcas"], AJUSTES, trabajo["sobrantes"])
    assert nivel(limpio[int(SR * 1.2) : int(SR * 1.35)]) == 0.0, "la muletilla tiene que callarse"
    assert any(t["callado"] for t in tramos)


def test_una_palabra_DEL_GUION_mal_casada_no_se_calla():
    """**El control negativo que faltaba, y lo trajo el episodio real.**

    De los 15 sobrantes del piloto, **13 eran fallos del reconocedor sobre habla que sí existe**: en
    «She laughed and laughed» whisper oye un «laughed» más de los que el guion tiene, y el cupo de
    `marcas_sobrantes` lo declara sobrante. Callarlo sería borrar narración — el desastre de la «nt»
    de «important» por un camino nuevo. La guarda es la pertenencia: si el guion dice esa palabra en
    alguna parte, se respeta aunque sobre en la cuenta.
    """
    marcas = [
        {"texto": "She", "desde": 0.0, "hasta": 0.4},
        {"texto": "laughed", "desde": 0.4, "hasta": 0.8},
        {"texto": "and", "desde": 0.8, "hasta": 1.1},
        {"texto": "laughed", "desde": 1.1, "hasta": 1.5},
        {"texto": "laughed", "desde": 1.5, "hasta": 1.9},
    ]
    trabajo = _como_en_produccion("She laughed and laughed", marcas)

    assert _muletillas_de(trabajo) == [], "una palabra que el guion dice no es una muletilla del motor"
    assert len(trabajo["marcas"]) == 5, "y sigue entera dentro de la zona protegida"


def test_una_ALUCINACION_larga_del_reconocedor_no_se_calla():
    """**El otro control que faltaba**, y el que más audio salva.

    En la lámina 1 del piloto, whisper transcribió «Thank you very much for your time.» ocupando
    **29,94 s** encima de narración real —su alucinación de manual sobre audio largo—. Ese texto no
    está en el guion, así que la pertenencia no lo salva: lo salva la duración. Una muletilla es
    corta; treinta segundos es el reconocedor perdido, y ahí no se toca nada.
    """
    marcas = [
        {"texto": "Ollie", "desde": 0.0, "hasta": 1.0},
        {"texto": "Thank", "desde": 1.0, "hasta": 31.0},
        {"texto": "opened", "desde": 31.0, "hasta": 32.0},
    ]
    trabajo = _como_en_produccion("Ollie opened", marcas)

    assert _muletillas_de(trabajo) == [], "30 s no son una muletilla: son una alucinación sobre habla"
    assert len(trabajo["marcas"]) == 3, "la zona protegida se queda entera"


def test_callar_una_muletilla_NO_ensancha_al_hueco_entero():
    """**El último camino por el que se podía comer habla**, medido por la re-auditoría del 06-09.

    Lo que se apaga en esta rama es el hueco entero entre las dos palabras protegidas vecinas, y con
    el chequeo de nivel desactivado. Para un hueco sin guion o para la cola del final eso es
    inofensivo —el guion demuestra que en TODO el tramo no falta narración—, pero para una muletilla
    el argumento solo alcanza a lo que ella ocupa: una marca sobrante de 0,40 s entre dos palabras
    separadas 2 s silenciaba **1,76 s**, y 1,36 de ellos no tenían más evidencia que estar cerca.
    """
    señal = torch.cat([tono(1.0), tono(2.0, amplitud=0.9), tono(1.0)])
    marcas = [{"texto": "Ollie", "desde": 0.0, "hasta": 1.0}, {"texto": "opened", "desde": 3.0, "hasta": 4.0}]
    muletilla = [{"desde": 1.6, "hasta": 2.0, "texto": "Um…", "tipo": "muletilla"}]

    _, tramos = limpia(señal, SR, marcas, AJUSTES, muletilla)
    callado = [t for t in tramos if t["callado"] and t.get("por_texto")]
    assert len(callado) == 1
    largo = callado[0]["hasta"] - callado[0]["desde"]
    assert largo == pytest.approx(0.64, abs=0.01), (
        f"se callan {largo:.2f}s: la muletilla (0,40 s) más el margen por los dos lados, no el hueco entero"
    )


def test_un_hueco_SIN_GUION_si_se_calla_entero():
    """Control negativo del anterior: ahí el recorte **no** se aplica, y es la diferencia que importa.

    Entre dos palabras seguidas del guion no falta narración en NINGÚN punto del hueco, así que el
    tramo entero es del motor. Es el ruido de 1,46 s entre «hold it.» y «He held it».
    """
    señal = torch.cat([tono(1.0), tono(2.0, amplitud=0.9), tono(1.0)])
    marcas = [{"texto": "Ollie", "desde": 0.0, "hasta": 1.0}, {"texto": "opened", "desde": 3.0, "hasta": 4.0}]
    hueco = [{"desde": 1.0, "hasta": 3.0, "texto": "(sin guion)", "tipo": "hueco"}]

    _, tramos = limpia(señal, SR, marcas, AJUSTES, hueco)
    callado = [t for t in tramos if t["callado"] and t.get("por_texto")]
    assert len(callado) == 1
    largo = callado[0]["hasta"] - callado[0]["desde"]
    assert largo == pytest.approx(1.76, abs=0.01), f"el hueco entre las dos palabras va entero: {largo:.2f}s"


def test_sin_lista_de_sobrantes_lo_fuerte_se_respeta():
    """Control negativo del anterior: sin evidencia de texto, un sonido fuerte no se toca.

    Es la diferencia entre las dos señales. Sin la lista, ese mismo tramo es «el reconocedor se
    perdió aquí», y borrar habla es peor que dejar un ruido.
    """
    señal = torch.cat([tono(1.0), tono(0.5, amplitud=0.9), tono(1.0)])
    marcas = [{"desde": 0.0, "hasta": 1.0}, {"desde": 1.5, "hasta": 2.5}]
    limpio, _ = limpia(señal, SR, marcas, AJUSTES, [])
    assert torch.equal(limpio, señal)


def test_marcas_sobrantes_encuentra_la_muletilla_y_solo_esa():
    """Sobre el caso real: «Um…» sobra, y una palabra mal oída («Olly» por «Ollie») NO.

    La alineación de secuencias trata una palabra mal transcrita como sustitución y la empareja; una
    comparación por texto exacto habría marcado como inventadas 202 marcas del episodio, y casi todas
    eran la misma palabra mal oída. De las 1.028 del guion, la alineación dejó fuera **tres**.
    """
    from lib.alineacion import marcas_sobrantes

    guion = "Ollie opened his eyes and looked at the clock on the wall".split()
    palabras = ["Olly", "opened", "his", "eyes", "and", "looked", "at", "the", "clock", "on", "the", "wall"]
    marcas = [{"texto": w, "desde": i * 0.3, "hasta": i * 0.3 + 0.25} for i, w in enumerate(palabras)]
    marcas.insert(5, {"texto": "Um…", "desde": 1.45, "hasta": 3.2})

    sobrantes = marcas_sobrantes(guion, marcas)
    assert [s["texto"] for s in sobrantes] == ["Um…"], "«Olly» empareja con «Ollie» por sustitución"


def test_sin_marcas_ni_guion_no_sobra_nada():
    """Control negativo: sin una de las dos secuencias no hay nada que comparar, y no se inventa."""
    from lib.alineacion import marcas_sobrantes

    assert marcas_sobrantes([], [{"texto": "Um…", "desde": 0.0, "hasta": 1.0}]) == []
    assert marcas_sobrantes(["hola"], []) == []


# --- el hueco donde el guion no tiene nada ---------------------------------------------------------


def test_un_hueco_entre_palabras_SEGUIDAS_del_guion_es_ruido():
    """**El último ruido del episodio, y el que ninguna otra señal cazaba.**

    Entre «Ollie tried to hold it.» y «He held it for one second» había 1,46 s en los que el
    alineador no transcribió nada y sin embargo sonaba algo fuerte: no hay marca que sobre porque no
    hay marca, y el nivel lo protege. Pero las dos palabras son seguidas en el guion, así que ahí no
    falta narración por colocar.
    """
    from lib.alineacion import huecos_sin_guion

    guion = "hold it He held".split()
    marcas = [
        {"texto": "hold", "desde": 0.0, "hasta": 0.3},
        {"texto": "it", "desde": 0.3, "hasta": 0.6},
        {"texto": "He", "desde": 2.1, "hasta": 2.3},
        {"texto": "held", "desde": 2.3, "hasta": 2.6},
    ]
    huecos = huecos_sin_guion(guion, marcas, minimo_s=0.25)
    assert len(huecos) == 1
    assert huecos[0]["desde"] == pytest.approx(0.6) and huecos[0]["hasta"] == pytest.approx(2.1)


def test_si_FALTA_una_palabra_del_guion_el_hueco_se_respeta():
    """**El control que protege del fallo del reconocedor.**

    En la lámina 2 de este mismo episodio whisper colapsó nueve palabras en un instante. Cuando eso
    pasa, las palabras a los lados del hueco NO son consecutivas —falta gente en medio— y el hueco
    puede contener narración: no se toca.
    """
    from lib.alineacion import huecos_sin_guion

    guion = "hold it very slowly He held".split()  # «very slowly» no se reconoció
    marcas = [
        {"texto": "hold", "desde": 0.0, "hasta": 0.3},
        {"texto": "it", "desde": 0.3, "hasta": 0.6},
        {"texto": "He", "desde": 2.1, "hasta": 2.3},
        {"texto": "held", "desde": 2.3, "hasta": 2.6},
    ]
    assert huecos_sin_guion(guion, marcas, minimo_s=0.25) == []


def test_un_hueco_CON_marcas_dentro_no_lo_decide_esta_regla():
    """Si el reconocedor oyó algo con forma de palabra ahí, de eso se encarga `marcas_sobrantes`.

    Sin esta condición, el hueco entre «She» y «laughed» —que contiene el «laughed and» de «She
    laughed and laughed»— se llevaría por delante habla real.
    """
    from lib.alineacion import huecos_sin_guion

    guion = "She laughed and laughed".split()
    # el reconocedor oye una repetición de más, y la sobrante cae en el hueco entre dos emparejadas
    marcas = [
        {"texto": "She", "desde": 0.0, "hasta": 0.3},
        {"texto": "laughed", "desde": 0.7, "hasta": 1.0},
        {"texto": "and", "desde": 1.0, "hasta": 1.2},
        {"texto": "laughed", "desde": 1.2, "hasta": 1.5},
        {"texto": "and", "desde": 1.5, "hasta": 1.7},
        {"texto": "laughed", "desde": 1.7, "hasta": 2.0},
    ]
    huecos = huecos_sin_guion(guion, marcas, minimo_s=0.25)
    assert all(not (0.3 <= h["desde"] < 0.7) for h in huecos), "el hueco con marcas dentro no se toca"


def test_una_repeticion_que_CABE_en_el_guion_se_respeta():
    """Si el reconocedor oye lo mismo que el guion pide, no sobra nada aunque la alineación baile.

    «She laughed and laughed» tiene dos «laughed»: el emparejamiento puede colocar uno y dejar el
    otro fuera, y ese otro **sí es habla**. Callarlo borraría narración.
    """
    from lib.alineacion import marcas_sobrantes

    guion = "She laughed and laughed".split()
    marcas = [
        {"texto": "She", "desde": 0.0, "hasta": 0.3},
        {"texto": "laughed", "desde": 0.3, "hasta": 0.6},
        {"texto": "and", "desde": 0.6, "hasta": 0.8},
        {"texto": "laughed", "desde": 0.8, "hasta": 1.1},
    ]
    assert marcas_sobrantes(guion, marcas) == [], "todas caben en la cuenta del guion"


def test_una_repeticion_DE_MAS_del_motor_si_sobra():
    """**El último defecto del episodio.**

    El guion dice «She laughed and laughed» y el motor dijo «laughed and laughed and laughed»: una
    vez de más. El texto está en el guion, así que un filtro por pertenencia lo deja pasar y el audio
    acaba diciendo algo distinto de lo que el karaoke muestra. Lo que lo separa de una repetición
    legítima mal alineada es **contar**: si el guion tiene dos y suenan tres, sobra una.
    """
    from lib.alineacion import marcas_sobrantes

    guion = "She laughed and laughed".split()
    marcas = [
        {"texto": "She", "desde": 0.0, "hasta": 0.3},
        {"texto": "laughed", "desde": 0.3, "hasta": 0.6},
        {"texto": "and", "desde": 0.6, "hasta": 0.8},
        {"texto": "laughed", "desde": 0.8, "hasta": 1.1},
        {"texto": "and", "desde": 1.1, "hasta": 1.3},
        {"texto": "laughed", "desde": 1.3, "hasta": 1.6},
    ]
    sobran = sorted(x["texto"] for x in marcas_sobrantes(guion, marcas))
    assert sobran == ["and", "laughed"], f"sobra un «and» y un «laughed», y salió {sobran}"


def test_no_queda_una_ISLA_de_sonido_entre_dos_silencios():
    """**El último ruido, y lo creaba la propia limpieza.**

    Con el margen respetado tal cual, la cola de la última palabra quedaba sonando entre el silencio
    de antes y el de después: 18 islas de 150-800 ms a −22/−49 dB en el episodio, y **todas dentro de
    una palabra del guion** («room.», «birthday.», «know.»). Se oían como ruido. Lo que suena
    mal no es la cola sino el corte en seco contra el silencio digital, así que el margen se funde.
    """
    from lib.limpia_worker import limpia

    # una palabra que decae, un hueco largo sin marcas, y otra palabra
    decae = tono(0.4) * torch.linspace(1.0, 0.05, int(SR * 0.4))
    señal = torch.cat([tono(0.6), decae, silencio(0.8), tono(0.6)])
    marcas = [{"desde": 0.0, "hasta": 0.75}, {"desde": 2.4, "hasta": 3.0}]
    limpio, _ = limpia(señal, SR, marcas, AJUSTES)

    # se buscan islas: tramos que suenan con silencio absoluto a los dos lados
    v = int(SR * 0.01)
    picos = [float(limpio[i : i + v].abs().max()) for i in range(0, limpio.numel() - v, v)]
    mudo = [x == 0.0 for x in picos]
    islas, i = 0, 0
    while i < len(picos):
        if mudo[i]:
            i += 1
            continue
        j = i
        while j < len(picos) and not mudo[j]:
            j += 1
        if i > 0 and mudo[i - 1] and j < len(picos):
            islas += 1
        i = j
    assert islas == 0, f"quedan {islas} islas de sonido flotando entre silencios"


def test_una_isla_tenue_entre_dos_silencios_se_apaga():
    """**El remate**, y la firma que se describió sin saberlo dando seis minutos.

    En todos ellos el perfil es el mismo: habla, silencio absoluto, 300-900 ms de algo a −25/−45 dB,
    silencio absoluto, habla. Es seguro apagarlo porque **esos silencios los puso el pipeline**, no
    el motor: solo se ponen donde el guion no pide nada o donde hay una pausa de verdad. El habla es
    continua — una palabra no acaba aislada entre dos silencios absolutos.
    """
    from lib.limpia_worker import apaga_islas

    señal = torch.cat([tono(0.5), silencio(0.4), tono(0.4, amplitud=0.03), silencio(0.4), tono(0.5)])
    apagadas = apaga_islas(señal, señal.clone(), SR, AJUSTES, [])
    assert apagadas, "la isla tiene que detectarse"
    centro = señal[int(SR * 1.2) : int(SR * 1.3)]
    assert nivel(centro) == 0.0, "y quedar apagada"


def test_el_habla_entre_dos_silencios_NO_se_apaga():
    """Control negativo: una frase entre dos pausas es lo más normal del audio.

    Lo que separa una isla de una frase es el nivel: la narración de este canal va a −6/−15 dB y las
    islas no pasan de −22. Sin esta condición, el remate se llevaría por delante frases enteras.
    """
    from lib.limpia_worker import apaga_islas

    señal = torch.cat([tono(0.5), silencio(0.4), tono(0.6), silencio(0.4), tono(0.5)])
    copia = señal.clone()
    assert apaga_islas(señal, señal.clone(), SR, AJUSTES, []) == []
    assert torch.equal(señal, copia)


def test_una_PALABRA_ENTERA_entre_dos_silencios_no_es_una_isla():
    """**El cinturón que pidió la auditoría, y la medición que eligió su forma.**

    El argumento de esta regla —«el habla es continua, una palabra no queda aislada entre dos
    silencios»— tiene un hueco: los silencios los pone este pipeline **en los bordes de los trozos
    de habla**, así que una frase corta y floja entre dos pausas calladas encaja en la definición.
    Exigir que la isla no pise NINGUNA marca habría sido peor que el defecto: las 7 islas del
    episodio pisan la marca de una palabra, porque una cola vive dentro de la marca de la última
    palabra de su frase, y el filtro se habría apagado entero. Lo que separa los dos casos es si la
    palabra cabe DENTRO de la isla.
    """
    from lib.limpia_worker import apaga_islas

    # El tono fuerte del principio fija el pico: sin él, la isla floja ES el pico y ningún techo
    # relativo la ve — que es como se mide en un audio real, donde el pico lo pone la narración.
    señal = torch.cat([tono(0.5), silencio(0.4), tono(0.5, amplitud=0.03), silencio(0.4)])
    marcas = [{"texto": "hello", "desde": 0.92, "hasta": 1.38}]
    assert apaga_islas(señal.clone(), señal.clone(), SR, AJUSTES, marcas) == [], (
        "hay una palabra entera ahí dentro: es habla floja, no una cola"
    )
    assert apaga_islas(señal.clone(), señal.clone(), SR, AJUSTES, []) != [], (
        "y sin marcas la misma señal SÍ se apaga: la prueba mide el cinturón, no otra cosa"
    )


def test_una_isla_CORTA_no_se_apaga():
    """Por debajo de `isla_minima_ms` puede ser el resto de una consonante que la marca no cubrió."""
    from lib.limpia_worker import apaga_islas

    señal = torch.cat([tono(0.5), silencio(0.4), tono(0.1, amplitud=0.03), silencio(0.4), tono(0.5)])
    copia = señal.clone()
    assert apaga_islas(señal, señal.clone(), SR, AJUSTES, []) == []
    assert torch.equal(señal, copia)


def test_el_worker_recibe_TODOS_los_umbrales_de_la_receta():
    """Un umbral que no llega al worker es un filtro que no hace nada, y en silencio.

    Pasó: la lista de claves estaba escrita a mano con cuatro nombres, y al añadir el apagado de
    colas y el de islas sus umbrales se quedaron fuera. El informe seguía saliendo verde porque los
    tramos que sí se callaban eran los de siempre.
    """
    import inspect

    from lib import limpia_voz

    fuente = inspect.getsource(limpia_voz.limpia_lote)
    assert '"ajustes": {k: v for k, v in ajustes.items()' in fuente, (
        "los ajustes tienen que pasarse enteros, no con una lista de claves que se queda corta"
    )


def test_una_CABEZA_de_segmento_tambien_se_apaga():
    """**El último ruido del episodio**, y el mismo defecto que la cola pero al revés.

    La revisión: «en el minuto 5:04 se escucha el único ruido de todo el vídeo». Ahí hay 580 ms a −31/−47
    dB entre el silencio y la primera palabra: Chatterbox genera relleno antes de arrancar igual que
    lo genera al acabar. El filtro solo miraba el final, así que no lo veía.
    """
    from lib.limpia_worker import apaga_colas

    señal = torch.cat([tono(0.5, amplitud=0.5 * 10 ** (-25 / 20)), tono(1.0), silencio(0.3)])
    salida = señal.clone()
    tocadas = apaga_colas(salida, señal, SR, [{"desde": 0.0, "hasta": 1.5}], AJUSTES)
    assert any(t.get("cabeza") for t in tocadas), "la cabeza tiene que detectarse"
    assert nivel(salida[: int(SR * 0.1)]) < nivel(señal[: int(SR * 0.1)]), "y quedar atenuada"
    assert torch.equal(salida[int(SR * 0.5) : int(SR * 1.5)], señal[int(SR * 0.5) : int(SR * 1.5)]), (
        "la palabra, intacta"
    )


@pytest.mark.parametrize("ajustes", recetas_declaradas())
def test_un_ATAQUE_normal_no_es_una_cabeza(ajustes):
    """Control negativo, **ejecutado con el umbral que cada canal ENTREGA**.

    Lo que separa un ataque de una cabeza es lo que dura. El ataque más largo medido sobre el
    episodio real son **220 ms** —«They», «She»—, y la cabeza que justifica el filtro medía **580**.
    Entre medias hay que elegir, y el número se eligió mal: `cabeza_minima_ms` valía **150**, así que
    atenuaba 20 cabezas de las que 16 caían sobre palabras del guion, ocho con sonido audible de −30
    a −43 dBFS. Es el síntoma que se describió — «la primera palabra empieza en un volumen bajo y
    sube de forma repentina».

    **Por eso esta prueba se parametriza con las recetas reales** en vez de con un ajuste de
    laboratorio: un canal que declare un umbral por debajo del ataque más largo medido rompe aquí, y
    no en el oído del usuario tres vueltas después.
    """
    from lib.limpia_worker import apaga_colas

    señal = torch.cat([tono(0.22, amplitud=0.5 * 10 ** (-25 / 20)), tono(1.0), silencio(0.3)])
    salida = señal.clone()
    tocadas = apaga_colas(salida, señal, SR, [{"desde": 0.0, "hasta": 1.22}], ajustes)
    assert not any(t.get("cabeza") for t in tocadas), (
        f"con cabeza_minima_ms={ajustes['cabeza_minima_ms']} se ataca el arranque de una palabra real"
    )
    assert torch.equal(salida, señal)


def test_lo_que_suena_TRAS_LA_ULTIMA_palabra_del_guion_se_calla():
    """**El último ruido del episodio.**

    Al acabar la lámina 5, después de «Happy birthday, Mum.» quedaban 790 ms sonando a −5 dB. El
    filtro los respetaba por su regla de seguridad —suena fuerte fuera de las palabras, luego el
    reconocedor se perdió—, que es buena en mitad de una lámina y no vale al final: ahí el guion se
    ha terminado y lo que suene lo puso el motor.
    """
    from lib.limpia_voz import _cola_del_final

    guion = "Happy birthday Mum".split()
    marcas = [
        {"texto": "Happy", "desde": 0.0, "hasta": 0.3},
        {"texto": "birthday", "desde": 0.3, "hasta": 0.8},
        {"texto": "Mum", "desde": 0.8, "hasta": 1.2},
    ]
    cola = _cola_del_final(guion, marcas)
    assert cola and cola[0]["desde"] == pytest.approx(1.2)


def test_si_el_reconocedor_perdio_el_FINAL_no_se_toca_nada():
    """**El control que mantiene la garantía.**

    Si la última palabra del guion no está anclada, puede quedar narración sin colocar ahí y borrarla
    sería perder habla — que es peor que dejar un ruido.
    """
    from lib.limpia_voz import _cola_del_final

    guion = "Happy birthday Mum".split()
    marcas = [
        {"texto": "Happy", "desde": 0.0, "hasta": 0.3},
        {"texto": "birthday", "desde": 0.3, "hasta": 0.8},
    ]
    assert _cola_del_final(guion, marcas) == []
