"""El gate que canta cuando el audio no dice lo que dice el guion (F5.7).

Correr: .venv\\Scripts\\python -m pytest -q tests/test_integridad_narracion.py

**El control negativo es el corazón de este fichero y es material real**: la lámina 5 del episodio 2
de un canal, transcrita por el mismo `whisper-small` del pipeline sobre los DOS audios que existen de
ella — el que se subió a YouTube el 14-09-2026 con 5,6 s de narración borrados, y el mismo segmento
sin ese filtro. Está en `tests/datos/f5.7-lamina-05-con-y-sin-filtro.json` con sus dos
transcripciones, sus marcas y el silencio medido de cada hueco.

Lo que ese par demuestra y ninguna prueba sintética demostraría: **el texto de los dos es casi
igual**, porque el reconocedor falla en el mismo sitio en ambos. Un gate que compare solo texto canta
con las dos versiones, y un gate que canta cuando el vídeo está bien deja de leerse. Lo que los
separa es el audio, y por eso el veredicto lo pone el silencio.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lib import integridad_narracion as gate

DATOS = Path(__file__).resolve().parent / "datos" / "f5.7-lamina-05-con-y-sin-filtro.json"
PAR = json.loads(DATOS.read_text(encoding="utf-8"))
PERDIDO = "biscuit came into the kitchen"


def _mide_con_lo_medido(clave: str):
    """Devuelve el silencio REAL de ese audio cuando se le pregunta por la ventana que se midió.

    No es un `mock` que diga que sí: si el código pidiera otra ventana, este medidor devolvería 0 y
    la prueba se caería. Así la prueba sigue atada a la ventana concreta, que es parte de lo que se
    está verificando.
    """
    m = PAR["silencio_medido_s"][clave]

    def mide(_audio, desde, hasta):
        cerca = abs(desde - m["desde_s"]) < 0.05 and abs(hasta - m["hasta_s"]) < 0.05
        return m["silencio_s"] if cerca else 0.0

    return mide


def _run(tmp_path: Path, clave: str, *, con_audio: bool = True) -> Path:
    """Un run de una lámina con la narración real y la transcripción de uno de los dos audios."""
    run = tmp_path / clave
    (run / "subtitulos").mkdir(parents=True)
    (run / "slides.json").write_text(
        json.dumps({"slides": [{"slide_number": 1, "narration": PAR["narracion"]}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run / "subtitulos" / "alineacion-resultado.json").write_text(
        json.dumps({"items": [{"id": "slide-01", "marcas": PAR[clave]["marcas"]}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    if con_audio:
        # El audio no va en git (pesa y es material de un run). Lo que la prueba necesita de él son
        # su duración y su silencio: la duración se toma del montaje y el silencio se inyecta.
        (run / "montaje.json").write_text(
            json.dumps({"detalle": [{"slide": 1, "segundos": PAR["duracion_audio_s"]}]}), encoding="utf-8"
        )
        (run / "audio").mkdir()
        (run / "audio" / "slide-01.wav").write_bytes(b"")
    return run


# --- EL CONTROL NEGATIVO ----------------------------------------------------------------------


def test_caza_la_narracion_borrada_del_episodio_que_se_subio(tmp_path):
    """Con el filtro puesto, la frase de la lámina 5 no se oye y el gate la señala con su segundo."""
    informe = gate.revisa_run(_run(tmp_path, "con_filtro"), mide=_mide_con_lo_medido("con_filtro"))

    assert len(informe["faltan"]) == 1, informe
    hallazgo = informe["faltan"][0]
    assert PERDIDO in hallazgo["texto"]
    assert hallazgo["veredicto"] == "perdida"
    assert hallazgo["lamina"] == 1
    assert 29 < hallazgo["desde_s"] < 31, "el segundo que se le da al usuario tiene que ser el del hueco"
    # 1,99 s de sonido para 14 palabras: 0,14 s por palabra, la mitad del techo del estudio.
    assert hallazgo["segundos_por_palabra"] < gate.SEGUNDOS_POR_PALABRA_MINIMO


def test_calla_con_el_mismo_texto_cuando_el_audio_si_lo_dice(tmp_path):
    """Sin el filtro, el reconocedor falla IGUAL y el gate no reporta nada, porque ahí se habla."""
    informe = gate.revisa_run(_run(tmp_path, "sin_filtro"), mide=_mide_con_lo_medido("sin_filtro"))

    assert informe["faltan"] == [], "un gate que canta con el vídeo bueno deja de leerse"
    assert len(informe["descartados"]) == 1
    descartado = informe["descartados"][0]
    assert PERDIDO in descartado["texto"]
    assert descartado["veredicto"] == "suena_voz"
    assert descartado["segundos_por_palabra"] > gate.SEGUNDOS_POR_PALABRA_MINIMO


def test_las_dos_transcripciones_se_parecen_tanto_que_el_texto_solo_no_las_distingue():
    """La medición que obliga a mirar el audio: los dos textos fallan en el MISMO sitio.

    Si esto dejara de ser cierto, las dos pruebas de arriba pasarían por el motivo equivocado y el
    control negativo no estaría midiendo nada.
    """
    con = gate.tramos(PAR["narracion"], PAR["con_filtro"]["marcas"])
    sin = gate.tramos(PAR["narracion"], PAR["sin_filtro"]["marcas"])
    assert len(con) == len(sin) == 1
    assert PERDIDO in con[0]["texto"] and PERDIDO in sin[0]["texto"]


# --- QUE LA COMPARACIÓN MIDA EL AUDIO Y NO SU PROPIO BUCLE --------------------------------------


def test_un_guion_que_se_oye_entero_no_da_ni_un_hallazgo():
    marcas = [{"texto": p, "desde": i * 0.4, "hasta": i * 0.4 + 0.3} for i, p in enumerate("uno dos tres".split())]
    assert gate.tramos("Uno, dos... tres.", marcas) == []


def test_tres_entradas_distintas_dan_tres_resultados_distintos():
    """El control negativo del comparador mismo.

    Un contador ingenuo —avanzar el índice solo cuando las palabras coinciden— daba **93,7 % de
    palabras perdidas en tres audios distintos**. Un número idéntico para tres entradas distintas
    mide el bucle, no el audio, así que la prueba exige que las tres se distingan.
    """
    guion = "one two three four five six seven eight nine ten"
    oidos = {
        "entero": guion.split(),
        "sin el medio": "one two three seven eight nine ten".split(),
        "con relleno": "one two three um um um um four five six seven eight nine ten".split(),
    }
    resultados = {}
    for etiqueta, palabras in oidos.items():
        marcas = [{"texto": p, "desde": i * 0.4, "hasta": i * 0.4 + 0.3} for i, p in enumerate(palabras)]
        resultados[etiqueta] = [(t["tipo"], t["palabras"]) for t in gate.tramos(guion, marcas)]
    assert resultados["entero"] == []
    assert resultados["sin el medio"] == [("falta", 3)]
    assert resultados["con relleno"] == [("sobra", 4)]


def test_falta_y_sobra_son_defectos_distintos_y_no_se_mezclan():
    guion = "the cage was hung from a post beside the road for everyone to see"
    faltan = "the cage was hung from a post for everyone to see".split()
    sobran = "the cage was hung from a post beside beside beside beside the road for everyone to see".split()
    for palabras, tipo in ((faltan, "falta"), (sobran, "sobra")):
        marcas = [{"texto": p, "desde": i * 0.4, "hasta": i * 0.4 + 0.3} for i, p in enumerate(palabras)]
        encontrados = gate.tramos(guion, marcas)
        assert [t["tipo"] for t in encontrados] == [tipo], (palabras, encontrados)


def test_un_cambio_de_dos_palabras_no_es_una_falta():
    """«carters with waggons drovers» → «driver is» es el reconocedor, no narración perdida.

    Medido sobre los siete runs que había en disco el 14-09: sin el saldo, seis hallazgos de esta
    familia entraban como faltas.
    """
    guion = "the sentence named carters with waggons drovers and everyone else on that road"
    oido = "the sentence named driver is and everyone else on that road".split()
    marcas = [{"texto": p, "desde": i * 0.4, "hasta": i * 0.4 + 0.3} for i, p in enumerate(oido)]
    assert gate.tramos(guion, marcas) == []


def test_dos_palabras_seguidas_son_ruido_del_reconocedor_y_tres_no():
    guion = "one two three four five six seven eight"
    for cuantas, espera in ((2, 0), (3, 1)):
        oido = guion.split()[: 3 + 0] + guion.split()[3 + cuantas :]
        marcas = [{"texto": p, "desde": i * 0.4, "hasta": i * 0.4 + 0.3} for i, p in enumerate(oido)]
        assert len(gate.tramos(guion, marcas)) == espera, (cuantas, oido)


def test_las_etiquetas_emocionales_no_cuentan_como_palabras():
    """`<laugh>` es sonido, no palabra: el reconocedor nunca lo escribe y el guion sí lo lleva."""
    oido = "he looked at the dog and said nothing".split()
    marcas = [{"texto": p, "desde": i * 0.4, "hasta": i * 0.4 + 0.3} for i, p in enumerate(oido)]
    assert gate.tramos("He looked at the dog <laugh> and said nothing.", marcas) == []


@pytest.mark.parametrize(
    "guion, oido",
    [
        # Tres seguidas: sin quitarlas son tres palabras perdidas justo en el umbral, o sea una falta.
        ("He looked at the dog <laugh> <sigh> <groan> and said nothing.", "he looked at the dog and said nothing"),
        # Una pegada a un cambio de dos palabras: sin quitarla, el saldo pasa de 2 a 3 y entra igual.
        (
            "The sentence named carters with waggons <sigh> drovers and everyone else on that road",
            "the sentence named driver is and everyone else on that road",
        ),
    ],
)
def test_quitar_las_etiquetas_es_lo_que_evita_estas_dos_faltas_inventadas(guion, oido):
    """El caso que SÍ distingue: con una sola etiqueta, la prueba de arriba pasa aunque se quite el
    código que dice probar.

    Lo midió la auditoría de F5.7 (recomendación 2): `_normaliza` convierte `<laugh>` en la palabra
    `laugh`, **una sola** palabra de más, y el umbral de 3 la filtra igual. Aquí la etiqueta cambia
    el resultado: quitar `sin_etiquetas()` de `palabras_comparables` convierte los dos casos en una
    falta que el audio no tiene.
    """
    palabras = oido.split()
    marcas = [{"texto": p, "desde": i * 0.4, "hasta": i * 0.4 + 0.3} for i, p in enumerate(palabras)]
    assert gate.tramos(guion, marcas) == []


# --- «AHÍ NO CABE»: LA RAMA QUE CONFIRMA SIN ESCUCHAR -------------------------------------------
#
# Es la que sostiene el criterio 8 —los 5 runs del primer canal a los que se les borró el `.wav` el 06-09— y
# la que produce el único hallazgo sobre un vídeo público. La auditoría de F5.7 (recomendación 1)
# midió que `if False:` en su sitio dejaba las 22 pruebas en verde.

CORTADO_AL_FINAL = "The cage was made to fit one man. His hands. His iron. His week."
SE_OYE = "the cage was made to fit one man his hands".split()
ULTIMA_MARCA_S = 28.98  # donde acaba la última palabra que el alineador colocó
DURA_LA_LAMINA_S = 29.00  # lo que dice montaje.json: quedan 0,02 s para cuatro palabras


def _run_con_el_final_cortado(tmp_path: Path, *, con_montaje: bool, con_audio: bool) -> Path:
    """Un run con la forma del hallazgo de la lámina 11 del primer canal: el guion sigue y la alineación no.

    Las marcas se construyen **hacia atrás** desde `ULTIMA_MARCA_S` para que la última acabe justo
    ahí: es el dato del que depende todo, y así no queda escrito a ojo.
    """
    run = tmp_path / "final-cortado"
    (run / "subtitulos").mkdir(parents=True)
    marcas = [
        {"texto": p, "desde": round(ULTIMA_MARCA_S - 0.45 * (n + 1), 2), "hasta": round(ULTIMA_MARCA_S - 0.45 * n, 2)}
        for n, p in enumerate(reversed(SE_OYE))
    ][::-1]
    assert marcas[-1]["hasta"] == ULTIMA_MARCA_S
    (run / "slides.json").write_text(
        json.dumps({"slides": [{"slide_number": 1, "narration": CORTADO_AL_FINAL}]}), encoding="utf-8"
    )
    (run / "subtitulos" / "alineacion-resultado.json").write_text(
        json.dumps({"items": [{"id": "slide-01", "marcas": marcas}]}), encoding="utf-8"
    )
    if con_montaje:
        (run / "montaje.json").write_text(
            json.dumps({"detalle": [{"slide": 1, "segundos": DURA_LA_LAMINA_S}]}), encoding="utf-8"
        )
    if con_audio:
        (run / "audio").mkdir()
        (run / "audio" / "slide-01.wav").write_bytes(b"")
    return run


def test_lo_que_no_cabe_en_el_hueco_se_da_por_perdido_sin_medir_el_audio(tmp_path):
    """La lámina dura 29,00 s y la última palabra acaba en 28,98: «His iron. His week.» no está.

    Y se decide **sin tocar el `.wav`**, que es lo que deja auditar los episodios ya publicados. El
    medidor de silencio va de espía: si alguien quita esta rama, el gate se pondría a medir el audio
    y la lista de llamadas dejaría de estar vacía.
    """
    llamadas = []

    def espia(audio, desde, hasta):
        llamadas.append((desde, hasta))
        return 0.0

    informe = gate.revisa_run(_run_con_el_final_cortado(tmp_path, con_montaje=True, con_audio=True), mide=espia)

    assert len(informe["faltan"]) == 1, informe
    hallazgo = informe["faltan"][0]
    assert hallazgo["texto"] == "his iron his week"
    assert hallazgo["veredicto"] == "perdida"
    assert hallazgo["motivo"] == "no_cabe"
    assert hallazgo["ventana_s"] == round(DURA_LA_LAMINA_S - ULTIMA_MARCA_S, 2)
    assert hallazgo["sonido_s"] is None, "no se midió sonido porque no hacía falta"
    assert llamadas == [], "esta rama no puede depender del audio: esos runs ya no lo tienen"
    assert "no caben" in gate.explica(hallazgo)


def test_el_hueco_se_mide_POR_PALABRA_y_no_en_absoluto(tmp_path):
    """1,20 s sobran para una palabra y no dan ni de lejos para ocho.

    Es el mutante que sobrevivió al primer barrido: comparar la ventana entera contra
    `SEGUNDOS_POR_PALABRA_MINIMO` —sin dividirla entre las palabras— seguía cazando el hueco de
    0,02 s del primer canal y dejaba pasar este, que es la forma normal de un corte en medio de una lámina.
    """
    llamadas = []

    def espia(audio, desde, hasta):
        llamadas.append((desde, hasta))
        return 0.0

    guion = [f"w{i}" for i in range(20)]
    oido = [p for i, p in enumerate(guion) if not (6 <= i < 14)]  # se callan ocho del medio
    marcas = [
        {"texto": p, "desde": round(n * 0.4, 2), "hasta": round(n * 0.4 + 0.4, 2)}
        if n < 6
        else {"texto": p, "desde": round(3.6 + (n - 6) * 0.4, 2), "hasta": round(3.6 + (n - 6) * 0.4 + 0.4, 2)}
        for n, p in enumerate(oido)
    ]
    run = tmp_path / "hueco-en-medio"
    (run / "subtitulos").mkdir(parents=True)
    (run / "audio").mkdir()
    (run / "audio" / "slide-01.wav").write_bytes(b"")
    (run / "slides.json").write_text(json.dumps({"slides": [{"narration": " ".join(guion)}]}), encoding="utf-8")
    (run / "subtitulos" / "alineacion-resultado.json").write_text(
        json.dumps({"items": [{"id": "slide-01", "marcas": marcas}]}), encoding="utf-8"
    )
    (run / "montaje.json").write_text(json.dumps({"detalle": [{"slide": 1, "segundos": 20.0}]}), encoding="utf-8")

    informe = gate.revisa_run(run, mide=espia)

    assert len(informe["faltan"]) == 1, informe
    hallazgo = informe["faltan"][0]
    assert hallazgo["palabras"] == 8
    assert hallazgo["ventana_s"] == 1.2, "el hueco entre la sexta palabra y la que la sigue"
    assert hallazgo["motivo"] == "no_cabe"
    assert llamadas == [], "1,20 s para 8 palabras se descarta con el reloj, no con el micrófono"


def test_sin_montaje_ni_wav_el_hueco_del_final_queda_sin_confirmar(tmp_path):
    """Sin duración de la lámina no hay ventana que medir, y callarlo sería darlo por bueno."""
    informe = gate.revisa_run(_run_con_el_final_cortado(tmp_path, con_montaje=False, con_audio=False))

    assert len(informe["faltan"]) == 1, informe
    hallazgo = informe["faltan"][0]
    assert hallazgo["veredicto"] == "sin_audio"
    assert hallazgo["ventana_s"] is None
    assert "nadie lo ha confirmado" in gate.explica(hallazgo)


def test_un_run_al_que_le_borraron_el_wav_no_se_lee_como_un_run_limpio(tmp_path):
    """El otro `sin_audio`: la ventana sí se puede medir, pero no hay audio con el que confirmarla.

    Es el estado de los 5 runs del primer canal vaciados el 06-09. El tramo **sigue en `faltan`** —no se va a
    `descartados`— porque nadie ha comprobado que ahí se hable.
    """
    informe = gate.revisa_run(_run(tmp_path, "con_filtro", con_audio=False))

    assert len(informe["faltan"]) == 1, informe
    hallazgo = informe["faltan"][0]
    assert PERDIDO in hallazgo["texto"]
    assert hallazgo["veredicto"] == "sin_audio"
    assert hallazgo["motivo"] == "sin_audio"
    assert hallazgo["ventana_s"] and hallazgo["sonido_s"] is None
    assert informe["descartados"] == []


# --- LOS SOBRANTES TAMBIÉN SE CONFIRMAN, CON MATERIAL REAL --------------------------------------
#
# Recomendación 3 de la auditoría: 4 de los 5 sobrantes que salían de los 8 runs de disco son
# imposibles. `tests/datos/f5.7-sobrantes-reales.json` trae tres de ellos tal cual salieron del
# alineador — el bueno del segundo canal y un artefacto de cada canal— porque recortar las marcas movería los
# índices y el solape dejaría de reproducirse.

SOBRANTES = json.loads(
    (Path(__file__).resolve().parent / "datos" / "f5.7-sobrantes-reales.json").read_text(encoding="utf-8")
)["casos"]


def _run_de_una_lamina(tmp_path: Path, clave: str) -> Path:
    """La lámina del caso, montada como un run de una sola lámina y sin `.wav`.

    Un sobrante se confirma con la ventana de sus **propias** marcas, así que el audio no hace falta
    y su ausencia no cambia el veredicto. Lo que sí trae el caso es la narración entera del guion:
    sin ella el emparejamiento sería otro.
    """
    caso = SOBRANTES[clave]
    run = tmp_path / clave
    (run / "subtitulos").mkdir(parents=True)
    (run / "slides.json").write_text(
        json.dumps({"slides": [{"slide_number": 1, "narration": caso["narracion"]}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run / "subtitulos" / "alineacion-resultado.json").write_text(
        json.dumps({"items": [{"id": "slide-01", "marcas": caso["marcas"]}]}, ensure_ascii=False), encoding="utf-8"
    )
    return run


def test_el_ritmo_por_si_solo_deja_pasar_este_tramo(tmp_path):
    """EL CONTROL de la recomendación 3 de F5.7, **con su etiqueta corregida el 18-09**.

    F5.7 lo llamó `habla_de_verdad` y dio por hecho que era una divagación real, porque su ritmo
    cuadra: 20 palabras en 10,72 s = 0,536 s por palabra, y el canal declara 0,53 en
    `perfil.json → voz.palabras_por_segundo`. **Era un duplicado del reconocedor.** Se comprobó por
    oído: transcribiendo los 10-38 s del `slide-07.wav` archivado en UNA sola ventana de whisper —sin
    ventana deslizante, o sea sin el artefacto— la frase sale **una vez**, y en el guion está **una
    vez**. La alineación del run salta de 29,98 a 20,0 s justo encima del tramo.

    Lo que esta prueba fija, y por eso se conserva, es **el límite del filtro de ritmo**: por tiempo
    este tramo es indistinguible de alguien hablando, así que si el gate solo midiera el reloj lo
    reportaría. Quien lo descarta es el criterio de texto de F5.9, y eso se comprueba abajo.
    """
    tramos = gate.tramos(SOBRANTES["habla_de_verdad"]["narracion"], SOBRANTES["habla_de_verdad"]["marcas"])
    sobrante = next(t for t in tramos if t["tipo"] == "sobra")

    solo_el_reloj = gate.confirma_sobrante(sobrante)  # sin narración: el filtro de F5.7 tal cual era
    assert solo_el_reloj["veredicto"] == "divaga", "por ritmo, esto se reportaba"
    assert solo_el_reloj["palabras"] == 20
    assert solo_el_reloj["ventana_s"] == 10.72
    assert solo_el_reloj["segundos_por_palabra"] == 0.536
    assert solo_el_reloj["segundos_por_palabra"] > gate.SEGUNDOS_POR_PALABRA_MINIMO
    assert "ritmo de alguien hablando" in gate.explica(solo_el_reloj)

    con_el_texto = gate.revisa_run(_run_de_una_lamina(tmp_path, "habla_de_verdad"))
    assert con_el_texto["sobran"] == [], "y con el criterio de texto, ya no"
    assert con_el_texto["descartados"][0]["veredicto"] == "repeticion_del_reconocedor"


@pytest.mark.parametrize(
    "clave, palabras, ventana",
    [
        ("solape_mums", 47, 0.34),  # 138 palabras por segundo: el «mums» repetido 27 veces
        ("solape_bridle", 19, -0.28),  # ventana NEGATIVA: medida a caballo del salto de tiempo
    ],
)
def test_el_solape_del_reconocedor_no_se_reporta_como_divagacion(tmp_path, clave, palabras, ventana):
    """Lo que el reconocedor transcribe dos veces no es audio, y el reloj lo demuestra solo.

    **Trampa cazada al medir, y por eso está escrita aquí**: el caso `solape_bridle` se descarta con
    la ventana que sale HOY, y esa ventana depende de un desfase de índices —`_texto_de_las_marcas`
    tira las marcas que normalizan a vacío y las ventanas se buscan en la lista cruda—. Con el mapeo
    corregido serían **9,90 s para 19 palabras (0,521 s por palabra)** y este tramo volvería a
    reportarse. Sigue siendo un duplicado: esos 9,90 s son los mismos segundos que el guion ya tiene
    emparejados antes del salto. Si alguien arregla el desfase, esta prueba se pone **roja a
    propósito**: hay que decidir entonces si hace falta mirar el solape, no cambiar la salida en
    silencio. El otro caso, `solape_mums`, no depende de eso: −0,10 s con el mapeo corregido.
    """
    informe = gate.revisa_run(_run_de_una_lamina(tmp_path, clave))

    assert informe["sobran"] == [], informe["sobran"]
    fuera = [d for d in informe["descartados"] if d["tipo"] == "sobra"]
    assert len(fuera) == 1, informe["descartados"]
    assert fuera[0]["veredicto"] == "no_es_audio"
    assert fuera[0]["palabras"] == palabras
    assert fuera[0]["ventana_s"] == ventana
    assert "dos veces los mismos segundos" in gate.explica(fuera[0])


def test_el_solape_se_reconoce_porque_la_alineacion_retrocede_en_el_tiempo():
    """Por qué esas ventanas salen imposibles, medido aparte del gate.

    El reconocedor transcribe por ventanas que se solapan, así que las marcas **vuelven atrás** en
    un punto y el texto repetido queda fuera del emparejamiento. Si esto dejara de ser cierto, el
    filtro de arriba estaría descartando otra cosa y habría que volver a mirarlo.
    """
    for clave, salto in (("solape_mums", (89.98, 80.0)), ("solape_bridle", (29.98, 20.0))):
        marcas = SOBRANTES[clave]["marcas"]
        atras = [(a["hasta"], b["desde"]) for a, b in zip(marcas, marcas[1:]) if b["desde"] < a["desde"]]
        assert atras == [salto], (clave, atras)


def test_un_sobrante_sin_ventana_se_reporta_en_vez_de_descartarse():
    """El filtro falla ABIERTO: lo que no se ha podido medir no se calla."""
    juzgado = gate.confirma_sobrante({"tipo": "sobra", "palabras": 5, "texto": "x", "desde_s": 1.0, "hasta_s": None})

    assert juzgado["veredicto"] == "sin_medir"
    assert juzgado["ventana_s"] is None
    assert "no hay marcas" in gate.explica(juzgado)


# --- LO QUE «SOBRA» PERO YA ESTÁ EN EL GUION (F5.9) ---------------------------------------------
#
# El filtro de ritmo mide si el tramo CABE hablado, y hay un solape que cabe: el reconocedor repite
# palabras dentro de una ventana de duración normal. Esos tramos pasaban el filtro y se reportaban
# como divagación de Orpheus. La segunda pregunta mira de dónde salió el TEXTO.


def test_el_solape_que_CABE_hablado_se_reconoce_por_su_texto(tmp_path):
    """El caso REAL que el filtro de ritmo no cazaba: 0,551 s por palabra, ritmo humano.

    `repite_el_guion` es la lámina 6 de un run de un canal tal como salió. Su sobrante son 19 palabras a
    ritmo de narración —el canal declara 0,53 s por palabra—, así que por tiempo es indistinguible de
    alguien hablando. Lo que lo delata es que el 89,5 % de esas palabras están, en ese orden, en la
    narración de su propia lámina.
    """
    informe = gate.revisa_run(_run_de_una_lamina(tmp_path, "repite_el_guion"))

    assert informe["sobran"] == [], informe["sobran"]
    fuera = [d for d in informe["descartados"] if d["tipo"] == "sobra"]
    assert len(fuera) == 1, informe["descartados"]
    assert fuera[0]["segundos_por_palabra"] == 0.551, "cabe hablado: el ritmo NO es lo que lo descarta"
    assert fuera[0]["segundos_por_palabra"] > gate.SEGUNDOS_POR_PALABRA_MINIMO
    assert fuera[0]["veredicto"] == "repeticion_del_reconocedor"
    assert fuera[0]["ya_en_el_guion"] == 0.895
    assert "ya están en la narración de su lámina" in gate.explica(fuera[0])


def test_CONTROL_NEGATIVO_el_mismo_tramo_contra_OTRO_guion_sigue_siendo_divagacion(tmp_path):
    """Si el criterio dijera «repetición» siempre, sería un verde que no discrimina.

    Mismas 19 palabras y misma ventana; lo único que cambia es la narración con la que se comparan.
    Contra un guion que no las contiene, el veredicto vuelve a ser `divaga` y el tramo se reporta.
    """
    caso = SOBRANTES["repite_el_guion"]
    tramo = {"tipo": "sobra", "palabras": 19, "texto": caso["narracion"][:120], "desde_s": 0.0, "hasta_s": 10.47}

    suyo = gate.confirma_sobrante(tramo, caso["narracion"])
    ajeno = gate.confirma_sobrante(tramo, "the dog washes everyone and the kitchen turns white again")

    assert suyo["veredicto"] == "repeticion_del_reconocedor"
    assert ajeno["veredicto"] == "divaga", "contra otro guion, lo mismo sí es texto de más"
    assert ajeno["ya_en_el_guion"] < gate.FRACCION_QUE_YA_ESTA_EN_EL_GUION < suyo["ya_en_el_guion"]


def test_CONTROL_POSITIVO_una_divagacion_de_verdad_se_sigue_reportando(tmp_path):
    """Que el criterio nuevo no haya cambiado un falso positivo por un falso negativo.

    **Este caso está FABRICADO y se dice**: son las marcas reales de `habla_de_verdad` con el texto
    de sus 20 palabras cambiado por una despedida que el guion no dice, **y los tiempos intactos**.
    Mismo ritmo, 0,536 s por palabra; lo único que cambia es de dónde sale el texto.

    Se fabrica porque **en los 16 runs producidos no queda ni una divagación real**: barridos el
    18-09, sus 12 sobrantes son 9 imposibles por reloj y 3 texto del propio guion. Sin este control,
    la suite no probaría que el gate todavía sabe reportar una, y un gate que solo sabe callar es el
    «verde que no discrimina» de siempre.
    """
    informe = gate.revisa_run(_run_de_una_lamina(tmp_path, "divaga_de_verdad"))

    assert len(informe["sobran"]) == 1, informe
    sobrante = informe["sobran"][0]
    assert sobrante["veredicto"] == "divaga"
    assert sobrante["segundos_por_palabra"] == 0.536, "el reloj dice exactamente lo mismo que en el otro caso"
    assert sobrante["ya_en_el_guion"] < gate.FRACCION_QUE_YA_ESTA_EN_EL_GUION
    assert "ritmo de alguien hablando" in gate.explica(sobrante)


@pytest.mark.parametrize(
    "sobrante, narracion, espera, por_que",
    [
        ("", "the kite is in the tree", False, "sin texto no se afirma nada"),
        ("the kite is in the tree", "", False, "sin guion con qué comparar, tampoco"),
        ("the kite is in the tree", "the kite is in the tree", True, "el mismo texto, palabra por palabra"),
        ("the kite is in the tree", "the kite is in a tree", True, "una palabra distinta no rompe el 80 %"),
        ("the kite is in the tree", "ollie ran across the grass again", False, "texto ajeno"),
        ("the dog sat on the mat", "the dog and the cat", False, "4 de 6 = 66 %: por debajo del umbral"),
    ],
)
def test_las_fronteras_del_criterio_de_repeticion(sobrante, narracion, espera, por_que):
    assert gate.es_repeticion_del_guion(sobrante, narracion)["es_repeticion"] is espera, por_que


def test_la_frontera_EXACTA_del_80_por_ciento():
    """Los dos casos que se tocan en el umbral, medidos: 0,833 dispara y 0,789 no.

    El control positivo fabricado se queda en 0,25, así que demuestra que el criterio sabe decir
    «divaga» pero no dónde está su raya (lo apuntó la auditoría de F5.9). Esto la fija: mismas 15
    palabras del guion, y lo único que cambia es cuánta divagación se les pega detrás.
    """
    guion = "Ollie looked at the shelf and Nora said I can't reach it you are taller than me"
    suyas = "ollie looked at the shelf and nora said i can't reach it you are taller".split()

    justo_encima = gate.es_repeticion_del_guion(" ".join(suyas + ["dog"] * 3), guion)
    justo_debajo = gate.es_repeticion_del_guion(" ".join(suyas + ["dog"] * 4), guion)

    assert (justo_encima["cubierto"], justo_encima["es_repeticion"]) == (0.833, True)
    assert (justo_debajo["cubierto"], justo_debajo["es_repeticion"]) == (0.789, False)
    assert justo_debajo["cubierto"] < gate.FRACCION_QUE_YA_ESTA_EN_EL_GUION <= justo_encima["cubierto"]


def test_el_criterio_no_exige_la_cadena_literal_y_por_eso_aguanta_al_reconocedor():
    """whisper escribe «olly» donde el guion dice «Ollie»: una comparación literal fallaría aquí."""
    dicho = "olly looked at the shelf and nora said i cant reach it"
    guion = "Ollie looked at the shelf, and Nora said: I can't reach it."

    assert dicho != guion
    assert gate.es_repeticion_del_guion(dicho, guion)["es_repeticion"] is True


def test_NINGUN_veredicto_descartado_sale_en_crudo_en_el_leeme():
    """La prueba genérica que faltaba: un descarte sin frase saldría con su nombre interno.

    La de abajo cubre solo `repeticion_del_reconocedor`, así que no habría puesto nada en rojo si
    mañana aparece un cuarto descarte (lo apuntó la auditoría de F5.9). Esta recorre **todos** los
    que el módulo declara en `VEREDICTOS_QUE_SE_DESCARTAN`, que es el contrato con el LEEME.
    """
    from lib.publicacion import _nota_de_narracion

    for veredicto in sorted(gate.VEREDICTOS_QUE_SE_DESCARTAN):
        linea = _nota_de_narracion(
            {
                "origen": "subtitulos/alineacion-resultado.json",
                "aviso": "",
                "laminas_comparadas": 1,
                "faltan": [],
                "sobran": [],
                "descartados": [{"tipo": "sobra", "lamina": 1, "palabras": 9, "veredicto": veredicto}],
            }
        )
        assert veredicto not in linea, f"«{veredicto}» sale en crudo: fáltale su frase en lib/publicacion.py"
        assert "sin clasificar" not in linea, f"«{veredicto}» cae en el cajón de sastre"


def test_CONTROL_un_descarte_sin_frase_SI_sale_en_crudo():
    """Que la prueba de arriba sepa fallar: con un veredicto inventado, el LEEME lo escribe tal cual."""
    from lib.publicacion import _nota_de_narracion

    linea = _nota_de_narracion(
        {
            "origen": "x",
            "aviso": "",
            "laminas_comparadas": 1,
            "faltan": [],
            "sobran": [],
            "descartados": [{"tipo": "sobra", "lamina": 1, "palabras": 9, "veredicto": "eco_del_motor"}],
        }
    )

    assert "eco_del_motor" in linea, "si esto deja de pasar, la prueba de arriba ya no mide nada"


def test_el_modulo_no_puede_descartar_un_veredicto_que_no_haya_declarado():
    """CONTROL del contrato: el enrutado de `revisa_run` lee la constante, no literales sueltos.

    Antes de F5.9 los tres nombres estaban escritos a mano en dos sitios distintos de `revisa_run`,
    así que añadir un descarte no obligaba a tocar nada más — y ese es justo el camino por el que
    `repeticion_del_reconocedor` llegó al LEEME sin frase.
    """
    fuente = Path(gate.__file__).read_text(encoding="utf-8")
    enrutado = fuente.split("for tramo in tramos(narracion")[1]

    for nombre in gate.VEREDICTOS_QUE_SE_DESCARTAN:
        assert f'"{nombre}"' not in enrutado, f"«{nombre}» vuelve a estar escrito a mano en el enrutado"
    assert enrutado.count("VEREDICTOS_QUE_SE_DESCARTAN") == 2, "las dos ramas deciden con la constante"


def test_el_leeme_distingue_el_descarte_nuevo_de_los_dos_viejos():
    """«Nada se descarta en silencio»: un veredicto sin frase saldría con su nombre en crudo."""
    from lib.publicacion import _nota_de_narracion

    linea = _nota_de_narracion(
        {
            "origen": "subtitulos/alineacion-resultado.json",
            "aviso": "",
            "laminas_comparadas": 10,
            "faltan": [],
            "sobran": [],
            "descartados": [{"tipo": "sobra", "lamina": 6, "palabras": 19, "veredicto": "repeticion_del_reconocedor"}],
        }
    )

    assert "repeticion_del_reconocedor" not in linea, "el nombre interno del veredicto no es una explicación"
    assert "ya estaba en la narración de su lámina" in linea


def test_lo_descartado_se_cuenta_en_el_leeme_y_dice_por_que(tmp_path):
    """«Nada se descarta en silencio»: el LEEME publica cuántos y de qué clase, sin abrir el JSON."""
    from lib.publicacion import guia_de_subida

    incidencias = {
        "voz": [],
        "divagacion_grande": [],
        "miniatura": None,
        "narracion": {
            "origen": "subtitulos/alineacion-resultado.json",
            "aviso": "",
            "laminas_comparadas": 10,
            "faltan": [],
            "sobran": [],
            "descartados": [
                {"tipo": "sobra", "lamina": 9, "palabras": 47, "veredicto": "no_es_audio", "ventana_s": 0.34},
                {"tipo": "falta", "lamina": 5, "palabras": 14, "veredicto": "suena_voz", "sonido_s": 5.17},
            ],
        },
    }
    html = guia_de_subida(tmp_path, titulo="T", descripcion="D", incidencias=incidencias).read_text(encoding="utf-8")

    assert "2 tramo(s) medidos y descartados" in html
    assert "1 que el reconocedor transcribió dos veces" in html
    assert "1 que el reconocedor no colocó pero donde el audio sí habla" in html


# --- QUE NO BLOQUEE NADA, PASE LO QUE PASE ------------------------------------------------------


def test_un_run_sin_alineacion_lo_dice_y_no_rompe(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "slides.json").write_text(json.dumps({"slides": [{"slide_number": 1, "narration": "algo"}]}), "utf-8")
    informe = gate.revisa_run(run)
    assert informe["faltan"] == [] and informe["sobran"] == []
    assert "alineación" in informe["aviso"]


@pytest.mark.parametrize(
    "roto",
    [
        {"slides.json": "{no es json", "subtitulos/alineacion-resultado.json": "{}"},
        {"slides.json": '{"slides": []}', "subtitulos/alineacion-resultado.json": "{{{"},
        {"slides.json": '{"slides": [{"narration": "hola"}]}', "subtitulos/alineacion-resultado.json": '{"items": 3}'},
    ],
)
def test_ningun_json_roto_tumba_el_run(tmp_path, roto):
    """«El pipeline siempre termina» (addendum fila 152): esto se llama al cerrar un run."""
    run = tmp_path / "run"
    (run / "subtitulos").mkdir(parents=True)
    for nombre, contenido in roto.items():
        (run / nombre).write_text(contenido, encoding="utf-8")
    informe = gate.revisa_run(run)  # no lanza
    assert informe["faltan"] == []


def test_el_leeme_lleva_la_lamina_el_segundo_y_el_texto_que_falta(tmp_path):
    """Criterio 3: el hallazgo sale en la guía de subida, bajo «esto salió peor de lo pedido»."""
    from lib.publicacion import guia_de_subida

    incidencias = {
        "voz": [],
        "divagacion_grande": [],
        "miniatura": None,
        "narracion": {
            "origen": "subtitulos/alineacion-resultado.json",
            "aviso": "",
            "laminas_comparadas": 10,
            "faltan": [
                {
                    "lamina": 5,
                    "palabras": 14,
                    "texto": "feet fast feet biscuit came into the kitchen",
                    "desde_s": 29.82,
                    "hasta_s": 37.88,
                    "en_el_video": "5:47",
                    "veredicto": "perdida",
                    "motivo": "hueco_callado",
                    "ventana_s": 8.06,
                    "sonido_s": 1.99,
                    "segundos_por_palabra": 0.142,
                }
            ],
            "sobran": [],
            "descartados": [],
        },
    }
    html = guia_de_subida(tmp_path, titulo="T", descripcion="D", incidencias=incidencias).read_text(encoding="utf-8")
    assert "Lámina 5" in html
    assert "5:47" in html, "el minuto es lo que convierte «revisa el vídeo» en «escucha el 5:47»"
    assert "biscuit came into the kitchen" in html
    assert "Esto salió peor de lo pedido" in html


def test_sin_hallazgos_el_leeme_no_pinta_una_alarma(tmp_path):
    from lib.publicacion import guia_de_subida

    incidencias = {
        "voz": [],
        "divagacion_grande": [],
        "miniatura": None,
        "narracion": {
            "origen": "subtitulos/alineacion-resultado.json",
            "aviso": "",
            "laminas_comparadas": 10,
            "faltan": [],
            "sobran": [],
            "descartados": [],
        },
    }
    html = guia_de_subida(tmp_path, titulo="T", descripcion="D", incidencias=incidencias).read_text(encoding="utf-8")
    assert "Ninguna incidencia" in html
    assert "10 lámina(s) comparadas" in html


def test_un_run_sin_comprobar_no_se_lee_como_un_run_limpio(tmp_path):
    """Lo contrario sería afirmar lo que no se ha mirado."""
    from lib.publicacion import guia_de_subida

    incidencias = {"voz": [], "divagacion_grande": [], "miniatura": None, "narracion": {}}
    html = guia_de_subida(tmp_path, titulo="T", descripcion="D", incidencias=incidencias).read_text(encoding="utf-8")
    assert "sin comprobar" in html


# --- LA MEDICIÓN DEL SILENCIO, CON SU PROPIO CONTROL NEGATIVO ----------------------------------

pytestmark_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg es parte del stack")


def _wav(destino: Path, filtro: str, segundos: float) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", filtro, "-t", str(segundos), str(destino)],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip
    return destino


@pytestmark_ffmpeg
def test_el_medidor_de_silencio_encuentra_el_hueco_y_no_lo_inventa(tmp_path):
    """Control negativo del medidor: un audio que habla sin parar no puede dar silencio."""
    concatenado = tmp_path / "con-hueco.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "sine=frequency=220:duration=2",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=3",
         "-f", "lavfi", "-i", "sine=frequency=220:duration=2",
         "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", str(concatenado)],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip
    sin_hueco = _wav(tmp_path / "sin-hueco.wav", "sine=frequency=220:duration=7", 7)

    assert 2.8 < gate.silencio_en(concatenado, 0, 7) < 3.2
    assert gate.silencio_en(sin_hueco, 0, 7) == 0.0


@pytestmark_ffmpeg
def test_el_medidor_nunca_lanza_con_una_ventana_imposible(tmp_path):
    audio = _wav(tmp_path / "a.wav", "sine=frequency=220:duration=1", 1)
    assert gate.silencio_en(audio, 5, 2) == 0.0
    assert gate.silencio_en(tmp_path / "no-existe.wav", 0, 1) == 0.0
    assert gate.duracion(tmp_path / "no-existe.wav") is None


# --- QUE LAS PRUEBAS SEPAN FALLAR ---------------------------------------------------------------


def test_con_el_umbral_a_cero_el_gate_se_llena_de_ruido():
    """Romper el gate a propósito: si el umbral de 3 palabras no hiciera nada, esto pasaría igual.

    Con `minimo=0`, la lámina 5 del par de control pasa de 1 hallazgo a varios, y entran los cambios
    de una palabra —«Ollie»/«Olly», «flour»/«flower»— que son el reconocedor y no el audio.
    """
    con_umbral = gate.tramos(PAR["narracion"], PAR["sin_filtro"]["marcas"])
    sin_umbral = gate.tramos(PAR["narracion"], PAR["sin_filtro"]["marcas"], minimo=0)
    assert len(sin_umbral) > len(con_umbral) + 2, (len(sin_umbral), len(con_umbral))


def test_comparar_contra_el_guion_equivocado_se_nota(tmp_path):
    """El otro control negativo: si el gate comparase con otro texto, tendría que cantar a gritos."""
    run = _run(tmp_path, "sin_filtro")
    otro = json.loads((run / "slides.json").read_text(encoding="utf-8"))
    otro["slides"][0]["narration"] = "The gibbet was built to fit one man and it hung beside the road for years"
    (run / "slides.json").write_text(json.dumps(otro, ensure_ascii=False), encoding="utf-8")

    informe = gate.revisa_run(run, mide=_mide_con_lo_medido("sin_filtro"))
    assert informe["faltan"] or informe["sobran"]


def test_el_minuto_del_video_sale_del_montaje_y_no_del_segundo_de_la_lamina(tmp_path):
    run = _run(tmp_path, "con_filtro")
    (run / "montaje.json").write_text(
        json.dumps({"detalle": [{"slide": 1, "segundos": PAR["duracion_audio_s"]}]}), encoding="utf-8"
    )
    informe = gate.revisa_run(run, mide=_mide_con_lo_medido("con_filtro"))
    assert informe["faltan"][0]["en_el_video"] == "0:30"

    # Y con la lámina precedida de otras cuatro de un minuto, el mismo hueco cae cuatro minutos más tarde
    (run / "slides.json").write_text(
        json.dumps(
            {
                "slides": [{"slide_number": i, "narration": "x"} for i in range(1, 5)]
                + [{"slide_number": 5, "narration": PAR["narracion"]}]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    alineacion = json.loads((run / "subtitulos" / "alineacion-resultado.json").read_text(encoding="utf-8"))
    alineacion["items"][0]["id"] = "slide-05"
    (run / "subtitulos" / "alineacion-resultado.json").write_text(json.dumps(alineacion), encoding="utf-8")
    (run / "montaje.json").write_text(
        json.dumps(
            {"detalle": [{"slide": i, "segundos": 60.0} for i in range(1, 5)] + [{"slide": 5, "segundos": 82.0}]}
        ),
        encoding="utf-8",
    )
    informe = gate.revisa_run(run, mide=_mide_con_lo_medido("con_filtro"))
    assert informe["faltan"][0]["en_el_video"] == "4:30"


def test_el_audio_regenerado_despues_de_la_alineacion_se_avisa(tmp_path):
    """Es el estado real del run del 14-09 tras rehacer la lámina 5: dos versiones, un solo informe."""
    import os
    import time

    run = _run(tmp_path, "con_filtro")
    alineacion = run / "subtitulos" / "alineacion-resultado.json"
    ahora = time.time()
    os.utime(alineacion, (ahora - 600, ahora - 600))
    os.utime(run / "audio" / "slide-01.wav", (ahora, ahora))

    informe = gate.revisa_run(run, mide=_mide_con_lo_medido("con_filtro"))
    assert "más nuevo" in informe["aviso"]
