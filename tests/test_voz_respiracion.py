"""El aire de la narración y el guardián de la saturación, los dos del repaso del 05-09.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_voz_respiracion.py

**De dónde salen.** La revisión del episodio 1 entero trajo dos cosas del audio:

- «en el minuto 2.55 se escuchan ruidos tipo artefactos que dañan el audio» — medido, en 2:55,7 el
  pico salta de 13.500 al techo del formato durante 1,2 s y luego silencio. Es Chatterbox reventando
  al final de un trozo, y **no lo cazaba nada**: la guarda de plausibilidad miraba el ritmo, y el
  ritmo de ese segmento era normal.
- «se podría hacer que fuera más pausada la narración, no quiero decir que se baje la velocidad de
  habla sino más pausado que no corra tanto entre palabra y palabra» — que son dos cosas distintas,
  y la prueba que lo fija es que **el habla no se toca**.
"""

import pytest

torch = pytest.importorskip("torch")

from lib.voice_worker import (  # noqa: E402
    MUESTRAS_SATURADAS_SEGUIDAS,
    limpia_pausas,
    racha_saturada,
)

SR = 24000
RESPIRACION = {
    "umbral_db": -38,
    "pausa_desde_ms": 300,
    "pausa_minima_ms": 550,
    "pausa_maxima_ms": 1500,
    "factor": 1.6,
    "fundido_ms": 60,
}


def tono(segundos, amplitud=0.4):
    n = int(SR * segundos)
    t = torch.arange(n, dtype=torch.float32) / SR
    return amplitud * torch.sin(2 * torch.pi * 220 * t)


def silencio(segundos):
    return torch.zeros(int(SR * segundos), dtype=torch.float32)


def habla(*trozos):
    return torch.cat(trozos).unsqueeze(0)


# --- saturación -------------------------------------------------------------------------------


def test_una_racha_pegada_al_techo_se_detecta():
    """El artefacto real medía 41 muestras al techo; 14 en la ventana de dos segundos."""
    reventon = torch.full((int(SR * 0.01),), 1.0)
    señal = habla(tono(0.5), reventon, tono(0.5))
    assert racha_saturada(señal) >= MUESTRAS_SATURADAS_SEGUIDAS


def test_el_habla_ALTA_no_es_saturacion():
    """Control negativo, y el que importa: sin él, la guarda repetiría cada segmento con voz fuerte.

    Un tono al 99 % del techo es tan alto como puede sonar una voz bien grabada, y no toca el 1,0.
    """
    assert racha_saturada(habla(tono(1.0, amplitud=0.99))) == 0


def test_la_saturacion_se_mide_contra_el_TECHO_y_no_contra_el_pico_del_trozo():
    """La primera versión comparaba con el máximo del propio segmento y no distinguía nada.

    Todo segmento tiene su propio pico «al máximo» por definición, así que el artefacto de 2:55 daba
    la misma cifra que dos segundos de habla limpia: 1 muestra.
    """
    flojo = habla(tono(1.0, amplitud=0.05))
    assert racha_saturada(flojo) == 0, "un segmento flojo no satura por tener un pico"


def test_un_segmento_vacio_no_revienta_la_medicion():
    assert racha_saturada(torch.zeros(1, 0)) == 0


# --- aire -------------------------------------------------------------------------------------


def test_el_habla_NO_se_toca_en_absoluto():
    """**La regresión del 06-09.**

    El fundido estuvo 150 ms fuera de la pausa, y funcionó para apagar la cola y rompió otra cosa:
    caía sobre la primera palabra de la frase siguiente y sobre la última de la anterior:
    «cuando comienza una frase la primera palabra la empieza en un volumen bajo y sube de forma
    repentina... y al final de la frase, en la última palabra pasa lo mismo». El fundido vive DENTRO
    de la pausa; las colas las apagan las funciones que sí saben dónde están las palabras.
    """
    señal = habla(tono(0.5), silencio(0.35), tono(0.5))
    salida = limpia_pausas(señal, SR, RESPIRACION)[0]
    assert torch.equal(salida[: int(SR * 0.5)], señal[0][: int(SR * 0.5)]), "la frase anterior, intacta"
    assert torch.equal(salida[-int(SR * 0.5) :], señal[0][-int(SR * 0.5) :]), "y la siguiente, intacta"
    assert salida.shape[-1] > señal.shape[-1], "y el total sí crece: el aire está en el hueco"


def test_una_pausa_se_estira_EN_PROPORCION():
    """350 ms × 1,6 = 560 ms. Dos pausas, así que el audio crece 420 ms."""
    señal = habla(tono(0.5), silencio(0.35), tono(0.5), silencio(0.35), tono(0.5))
    crecimiento = (limpia_pausas(señal, SR, RESPIRACION).shape[-1] - señal.shape[-1]) / SR
    assert crecimiento == pytest.approx(0.42, abs=0.02)


def test_la_pausa_LARGA_se_estira_mas_que_la_corta():
    """El guion distingue la coma del punto y aparte, y estirar a un valor fijo las igualaría.

    Es el motivo de que sea un factor y no un suelo suelto: 350 ms → 560 y 900 ms → 1440, así que
    la estructura de la narración se conserva y solo se ensancha.
    """
    corta = limpia_pausas(habla(tono(0.5), silencio(0.35), tono(0.5)), SR, RESPIRACION).shape[-1]
    larga = limpia_pausas(habla(tono(0.5), silencio(0.90), tono(0.5)), SR, RESPIRACION).shape[-1]
    assert (corta - int(SR * 1.0)) / SR == pytest.approx(0.56, abs=0.02)
    assert (larga - int(SR * 1.0)) / SR == pytest.approx(1.44, abs=0.02)


def test_una_pausa_por_debajo_del_umbral_de_deteccion_no_se_toca():
    """**El hueco de «Mum's birthday» mide 152 ms en el audio crudo, y no se puede tocar.**

    Por debajo de `pausa_desde_ms` no hay pausas: hay huecos DENTRO de una frase —entre dos palabras,
    o la oclusiva de una consonante—. En 16 s de la lámina 1 hay unos 25 de entre 40 y 290 ms, y
    tratarlos todos fue exactamente el tartamudeo que se oyó.
    """
    señal = habla(tono(0.5), silencio(0.15), tono(0.5))
    assert limpia_pausas(señal, SR, RESPIRACION).shape[-1] == señal.shape[-1]


def test_el_silencio_de_los_BORDES_no_se_ensancha():
    """El borde ya lo trata `_recorta_bordes`, y entre frases se añade el silencio de la receta.

    Ensancharlo aquí también lo sumaría dos veces, que es el defecto que F2.16 midió en 2,6 s de
    relleno por lámina.
    """
    señal = habla(silencio(0.10), tono(0.5), silencio(0.10))
    assert limpia_pausas(señal, SR, RESPIRACION).shape[-1] == señal.shape[-1]


def test_sin_respiracion_declarada_el_audio_sale_IDENTICO():
    """Un canal que declara `null` da una respuesta: su audio no puede cambiar por este código."""
    señal = habla(tono(0.5), silencio(0.10), tono(0.5))
    assert torch.equal(limpia_pausas(señal, SR, None), señal)


def test_todas_las_recetas_declaran_su_respiracion():
    """F4.9: sin defecto, y `null` es una respuesta.

    Un canal de inglés para escuchar respira; uno documental no, porque su karaoke es accesibilidad y no
    producto. Lo que la regla prohíbe es que un canal se calle y herede la cadencia del otro, y eso se
    comprueba en cada receta: las de `canales/` y las dos de prueba, que deciden una cada cosa.
    """
    import json

    from canales_de_prueba import recetas_a_comprobar

    recetas = recetas_a_comprobar()
    assert recetas, "no hay ninguna receta de voz que comprobar"
    for ruta in recetas:
        segmentacion = json.loads(ruta.read_text(encoding="utf-8"))["segmentacion"]
        assert "respiracion" in segmentacion, f"{ruta} no declara `respiracion`"
        aire = segmentacion["respiracion"]
        if aire:
            assert set(aire) >= {
                "umbral_db",
                "pausa_desde_ms",
                "pausa_minima_ms",
                "pausa_maxima_ms",
                "factor",
                "fundido_ms",
            }, ruta
            # **El numero que costo dos regresiones**: por debajo de 300 ms no hay pausas, hay
            # huecos DENTRO de una frase, y tratarlos entrecorta la palabra.
            assert aire["pausa_desde_ms"] >= 300, f"{ruta}: {aire['pausa_desde_ms']} ms entra dentro de las frases"
            assert aire["pausa_minima_ms"] > aire["pausa_desde_ms"], f"{ruta}: el suelo va por encima"


# --- el ruido DENTRO del silencio ---------------------------------------------------------------


def ruido(segundos, amplitud=0.004):
    """Un suelo de ruido como el de Chatterbox: audible en un silencio, invisible bajo el habla."""
    n = int(SR * segundos)
    return amplitud * (torch.rand(n, dtype=torch.float32) * 2 - 1)


def test_la_pausa_queda_MUDA_de_verdad():
    """De las 388 pausas del episodio 1, ninguna lo estaba: todas llevaban un suelo de -44 a -52 dB.

    La revisión: «en las pausas que usa el narrador, durante el silencio hay momentos que se escuchan
    ruidos y eso es lo que daña al vídeo completo».
    """
    señal = habla(tono(0.5), ruido(0.60), tono(0.5))
    limpia = limpia_pausas(señal, SR, RESPIRACION)[0]
    # el centro de la pausa, con margen de sobra por las dos rampas de 25 ms
    centro = limpia[int(SR * 0.70) : int(SR * 1.00)]
    assert float(centro.abs().max()) == 0.0, "en medio de una pausa LARGA no puede quedar nada"


def test_el_ruido_se_apaga_con_RAMPA_y_no_de_golpe():
    """Un corte seco mete un chasquido: sería cambiar un defecto por otro.

    El control es el salto máximo entre dos muestras seguidas, que es exactamente lo que se oye
    como clic. Tiene que ser menor que el que había en el audio original.
    """
    señal = habla(tono(0.5), ruido(0.60), tono(0.5))
    limpia = limpia_pausas(señal, SR, RESPIRACION)[0]
    salto = float((limpia[1:] - limpia[:-1]).abs().max())
    crudo = float((señal[0][1:] - señal[0][:-1]).abs().max())
    assert salto <= crudo, f"el arreglo mete un salto de {salto:.4f}, mayor que el original {crudo:.4f}"


def test_limpiar_la_pausa_solo_toca_el_FUNDIDO_del_habla():
    """El habla va por encima del umbral: lo único que se le hace son los 150 ms de fundido."""
    señal = habla(tono(0.5), ruido(0.60), tono(0.5))
    limpia = limpia_pausas(señal, SR, RESPIRACION)[0]
    intacto = int(SR * (0.5 - 0.15))
    assert torch.equal(limpia[:intacto], señal[0][:intacto])
    assert torch.equal(limpia[-int(SR * 0.35) :], señal[0][-int(SR * 0.35) :])


# --- el techo de salida -------------------------------------------------------------------------


def test_un_pico_por_encima_del_techo_baja_el_archivo_ENTERO():
    """Dos láminas del episodio 1 se guardaron con picos de 1,063 y 1,092.

    Ahí había 25 y 40 muestras por encima de 1,0 —1 y 1,7 ms—, y un recorte a plena escala dura
    exactamente lo que dura un chasquido. Se escala todo el archivo porque recortar la punta deforma
    la onda, que ES el chasquido.
    """
    from lib.voice_worker import TECHO_DE_SALIDA, _bajo_el_techo

    fuerte = habla(tono(0.5, amplitud=1.09), tono(0.5, amplitud=0.2))
    bajado, factor = _bajo_el_techo(fuerte)
    assert float(bajado.abs().max()) == pytest.approx(TECHO_DE_SALIDA, abs=1e-4)
    assert factor == pytest.approx(TECHO_DE_SALIDA / 1.09, rel=1e-3)
    # la parte floja baja en la MISMA proporción: no se comprime, se atenúa
    assert float(bajado[0][-100:].abs().max()) == pytest.approx(0.2 * factor, rel=1e-2)


def test_un_audio_que_YA_cabe_no_se_toca():
    """Control negativo: si atenuara siempre, cada lámina saldría con un volumen distinto."""
    from lib.voice_worker import _bajo_el_techo

    justo = habla(tono(1.0, amplitud=0.9))
    bajado, factor = _bajo_el_techo(justo)
    assert factor == 1.0
    assert torch.equal(bajado, justo)


def test_una_pausa_CORTA_conserva_su_sonido():
    """**La regresión del 06-09, y la prueba que no existía.**

    La revisión: «ahora habla como si tartamudeara la narradora... la frase "Mum's Birthday" es incapaz de
    decirla sin que se entrecorte». Entre «Mum's» y «birthday» hay un hueco de unos 80 ms, y la
    primera versión lo convertía en 160 ms de silencio digital. Una pausa corta se ensancha y **se
    deja sonando**: el suelo de ruido es lo que da continuidad dentro de una frase.
    """
    señal = habla(tono(0.4), ruido(0.09), tono(0.4))
    salida = limpia_pausas(señal, SR, RESPIRACION)[0]
    # la pausa se ha estirado a 210 ms, así que su centro está sobre el segundo 0,5
    centro = salida[int(SR * 0.48) : int(SR * 0.60)]
    assert float(centro.abs().max()) > 0.0, "callar una pausa corta es el tartamudeo"


def test_por_que_la_prueba_vieja_no_cazaba_el_tartamudeo():
    """El control que faltaba: un tono CONSTANTE no tiene huecos internos, y el habla sí.

    Con la señal de antes —tono, silencio, tono— cualquier versión pasaba, porque el único hueco era
    la pausa que se quería tratar. Esta señal tiene huecos DENTRO de la voz, que es donde estaba el
    daño, y cuenta cuántos silencios absolutos nuevos aparecen: los cortos no pueden crecer.
    """
    frase = habla(tono(0.3), ruido(0.08), tono(0.3), ruido(0.08), tono(0.3), ruido(0.60), tono(0.3))
    # las dos pasadas, en el mismo orden que en producción: primero el aire, luego el silenciado
    salida = limpia_pausas(frase, SR, RESPIRACION)[0]

    def rachas_a_cero(x):
        cero, tramos, ini = (x == 0).tolist(), [], None
        for i, c in enumerate(cero + [False]):
            if c and ini is None:
                ini = i
            elif not c and ini is not None:
                tramos.append((i - ini) / SR)
                ini = None
        return tramos

    largos = [x for x in rachas_a_cero(salida) if x > 0.30]
    assert len(largos) == 1, f"solo la pausa larga puede quedar muda, y hay {len(largos)}"
    assert largos[0] > 0.4, "y tiene que ser la larga de verdad"


def test_una_pausa_muy_larga_no_se_dispara():
    """×1,6 sobre 2 s son 3,3 s, y eso es un hueco en pantalla sin subtítulo, no una pausa.

    Lo cantaba el auditor del karaoke quemado (retirado en F6.7) como «más de 3 s sin subtítulo», y en
    el episodio 1 le pasó a 9 de las 135 pausas.
    """
    señal = habla(tono(0.5), silencio(2.0), tono(0.5))
    salida = limpia_pausas(señal, SR, RESPIRACION)
    pausa = (salida.shape[-1] - int(SR * 1.0)) / SR
    assert pausa == pytest.approx(1.5, abs=0.02), "el techo son 1500 ms"


# --- las colas del motor ------------------------------------------------------------------------
#
# El 06-09, con las pausas ya calladas a -78 dB: «siguen habiendo ruidos en las pausas entre
# frases», y dos ejemplos: el minuto 3:12 y el 3:44. Medido en el 3:12: 1,25 s de sonido a -35/-19 dB
# pegado al silencio. Es lo que Chatterbox genera cuando ya no le queda texto que decir.

COLAS = {"techo_db": -18, "minimo_ms": 300, "rampa_ms": 25}


def test_una_cola_de_segmento_se_calla():
    """Suena 600 ms sin pasar de −25 dB y muere contra un silencio: no es una frase."""
    from lib.voice_worker import quita_colas_sin_habla

    señal = habla(tono(0.6), tono(0.6, amplitud=0.4 * 10 ** (-25 / 20)), silencio(0.6))
    salida = quita_colas_sin_habla(señal, SR, COLAS)[0]
    centro = salida[int(SR * 0.75) : int(SR * 1.05)]
    assert float(centro.abs().max()) == 0.0, "la cola tiene que quedar callada"
    assert torch.equal(salida[: int(SR * 0.55)], señal[0][: int(SR * 0.55)]), "y el habla, intacta"


def test_un_tramo_flojo_que_NO_toca_un_silencio_se_respeta():
    """**El control que evita comerse un susurro.**

    El guion tiene «Nora whispered» y «in a very small voice»: un tramo flojo en mitad de una frase
    es habla. Lo que distingue a una cola es que muere contra el silencio de después, no que suene
    bajo. Sin esta condición, el filtro se comería los susurros del guion.
    """
    from lib.voice_worker import quita_colas_sin_habla

    señal = habla(tono(0.6), tono(0.6, amplitud=0.4 * 10 ** (-25 / 20)), tono(0.6))
    assert torch.equal(quita_colas_sin_habla(señal, SR, COLAS), señal)


def test_el_habla_NORMAL_pegada_a_un_silencio_no_se_toca():
    """Control negativo: una frase que acaba y da paso a una pausa es lo más común del audio.

    Si el techo estuviera mal puesto, el filtro se comería el final de cada frase.
    """
    from lib.voice_worker import quita_colas_sin_habla

    señal = habla(tono(0.8), silencio(0.6))
    assert torch.equal(quita_colas_sin_habla(señal, SR, COLAS), señal)


def test_una_cola_CORTA_no_se_toca():
    """Por debajo de `minimo_ms` puede ser el desvanecido natural de la última sílaba."""
    from lib.voice_worker import quita_colas_sin_habla

    señal = habla(tono(0.6), tono(0.15, amplitud=0.4 * 10 ** (-25 / 20)), silencio(0.6))
    assert torch.equal(quita_colas_sin_habla(señal, SR, COLAS), señal)


def test_sin_colas_declaradas_el_audio_sale_IDENTICO():
    """Un canal que declara `null`: su motor es Kokoro, que no alucina sonido al quedarse sin texto."""
    from lib.voice_worker import quita_colas_sin_habla

    señal = habla(tono(0.6), tono(0.6, amplitud=0.02), silencio(0.6))
    assert torch.equal(quita_colas_sin_habla(señal, SR, None), señal)


def test_todas_las_recetas_declaran_sus_colas():
    """F4.9: sin defecto, y `null` es una respuesta."""
    import json

    from canales_de_prueba import recetas_a_comprobar

    for ruta in recetas_a_comprobar():
        segmentacion = json.loads(ruta.read_text(encoding="utf-8"))["segmentacion"]
        assert "colas" in segmentacion, f"{ruta} no declara `colas`"
        if segmentacion["colas"]:
            assert set(segmentacion["colas"]) >= {"techo_db", "minimo_ms", "rampa_ms"}, ruta


# --- el audio crudo reutilizable ------------------------------------------------------------------


def test_la_firma_del_crudo_incluye_todo_lo_que_cambia_el_audio():
    """**La protección que evita el peor fallo silencioso.**

    El crudo se reutiliza para no repetir diez minutos de motor cuando solo cambia un umbral del
    post-proceso. Pero si el guion cambia y el crudo se reutiliza igual, el vídeo sale con el audio
    del guion viejo y los subtítulos del nuevo: suena bien, dura lo que toca y está mal. La firma
    tiene que llevar todo lo que decide qué sale del motor.
    """
    import inspect

    from lib import voice_worker

    fuente = inspect.getsource(voice_worker.synthesize)
    for clave in ("segmentos", "motor", "parametros", "seed", "silencio_entre_frases_ms", "recorte_bordes"):
        assert f'"{clave}"' in fuente.split("ahora = {")[1].split("}")[0], f"la firma no incluye {clave}"


def test_el_post_proceso_esta_separado_del_motor():
    """Es lo que permite repetirlo sin GPU: si volviera a mezclarse, la ganancia desaparece."""
    from lib import voice_worker

    assert hasattr(voice_worker, "_post_proceso")
    import inspect

    assert "engine" not in inspect.signature(voice_worker._post_proceso).parameters


def test_dos_pausas_MUY_SEGUIDAS_no_revientan_el_fundido():
    """El fundido de salida de una pausa adelanta el cursor por delante de la siguiente.

    Sin la guarda, el trozo intermedio salía de longitud negativa y el motor moría con «The size of
    tensor a (0) must match the size of tensor b (312)». Pasó en el episodio 1 en cuanto el fundido
    subió a 150 ms.
    """
    señal = habla(tono(0.4), silencio(0.35), tono(0.05), silencio(0.35), tono(0.4))
    salida = limpia_pausas(señal, SR, RESPIRACION)
    assert salida.shape[-1] > 0
