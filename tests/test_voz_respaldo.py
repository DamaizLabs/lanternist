"""La voz NUNCA para el run: respaldo por silencio y «mejor intento» en vez de SystemExit.

**Lo que se prueba y por qué.** Hasta el 12-09, agotar los reintentos del generador era `SystemExit`
y el episodio moría. Cuatro pasadas de la voz del episodio 2 murieron así, las cuatro por una palabra
del nicho que whisper no localiza —`fanlight`, `assize`— y que el reintento con otra semilla no puede
arreglar porque no es azar del muestreo. Un fallo en el 0,2 % del audio no puede costar el episodio.

Tres cosas tienen que ser ciertas a la vez, y las tres tienen control:

1. Cuando la transcripción no casa, el corte por silencio encuentra el cierre de la frase — y NO
   confunde una pausa dramática temprana con el cierre (control negativo).
2. El generador **nunca** lanza `SystemExit`: ni sin recorte, ni con ritmo implausible.
3. El caso normal no cambia: si casa a la primera, intento 0 y sin incidencia. Sin esto, «no falla»
   podría significar «ya no distingue nada».

Los motores y recortadores son falsos a propósito: esto prueba la POLÍTICA, no a Orpheus ni a whisper.
"""

import pytest

torch = pytest.importorskip("torch")

from lib import voice_worker as vw  # noqa: E402

SR = 24_000


def _habla(segundos: float, nivel: float = 0.5):
    g = torch.Generator().manual_seed(7)
    return (torch.rand(int(SR * segundos), generator=g) * 2 - 1) * nivel


def _silencio(segundos: float):
    return torch.zeros(int(SR * segundos))


def _audio(*trozos):
    return torch.cat(trozos).unsqueeze(0)


# ---------------------------------------------------------------------------------------------
# 1. El corte por silencio
# ---------------------------------------------------------------------------------------------


def test_corta_en_el_primer_silencio_largo_despues_de_la_duracion_esperada():
    """10 palabras a 2,44 p/s son ~4,1 s. Habla 4 s, silencio 0,5 s, divagación 3 s: corta en el silencio."""
    wav = _audio(_habla(4.0), _silencio(0.5), _habla(3.0))
    resultado = vw._corta_por_silencio(wav, SR, palabras=10)
    assert resultado is not None
    cortado, segundos = resultado
    # arranca el silencio a los 4,0 s; el corte deja 100 ms de margen
    assert 4.0 <= segundos <= 4.15
    # una muestra de tolerancia: `segundos` es corte/sr en coma flotante y deshacerlo no es exacto
    assert abs(cortado.shape[-1] - segundos * SR) <= 1


def test_no_corta_en_una_pausa_dramatica_temprana():
    """CONTROL NEGATIVO. Un silencio largo en el primer 40 % del texto es una pausa, no el cierre.

    10 palabras -> 4,1 s esperados -> no se busca antes de 3,07 s (el 75 %). Una pausa de 0,5 s a
    los 1,5 s tiene que IGNORARSE; el corte va al silencio de los 4,5 s.
    """
    wav = _audio(_habla(1.5), _silencio(0.5), _habla(2.5), _silencio(0.5), _habla(2.0))
    resultado = vw._corta_por_silencio(wav, SR, palabras=10)
    assert resultado is not None
    _, segundos = resultado
    assert segundos > 4.0, f"cortó en la pausa dramática de los 1,5 s: {segundos:.2f}s"


def test_devuelve_none_si_no_hay_silencio_donde_cortar():
    """CONTROL NEGATIVO. Habla continua sin pausa: no hay corte que dar, y se dice, no se inventa."""
    wav = _audio(_habla(8.0))
    assert vw._corta_por_silencio(wav, SR, palabras=10) is None


def test_devuelve_none_si_el_unico_silencio_es_el_final_natural():
    """El audio acaba en silencio porque la frase acaba: eso no es divagación, es el final."""
    wav = _audio(_habla(4.0), _silencio(0.4))
    assert vw._corta_por_silencio(wav, SR, palabras=10) is None


# La forma del episodio 2 de un canal de economía, lámina 15, segmento 3 (07-10-2026): «Fast food went from about 184 to
# about 255... a rise of about 38.4%.», 14 pedidas. El recorte por texto casó 13 de 14: todas menos la cifra, partida en
# dos trozos por whisper (el log de la voz de ese episodio). El respaldo buscó el silencio desde el 75 % de lo esperado
# (4,30 s), encontró la pausa de los puntos suspensivos y se comió «a rise of about 38.4%». Aquí: habla hasta «255» (4,6
# s), la pausa, «a rise of about» hasta los 6,2 s y la cifra hasta los 7,0 s, el cierre y una divagación.
_PAUSA_ANTES_DE_LA_CIFRA = (_habla(4.6), _silencio(0.4), _habla(2.0), _silencio(0.5), _habla(2.0))
_TEXTO_LAMINA_15 = "Fast food went from about 184 to about 255... a rise of about 38.4%."  # 14 palabras


def test_la_pausa_antes_de_la_cifra_no_es_el_cierre_si_quedan_palabras_por_decir():
    """«about» casó a los 6,2 s y falta una pedida detrás: la pausa de los 4,6 s no puede ser el cierre."""
    wav = _audio(*_PAUSA_ANTES_DE_LA_CIFRA)
    resultado = vw._corta_por_silencio(wav, SR, palabras=14, ultima_casada_s=6.2, pedidas_detras=1)
    assert resultado is not None
    _, segundos = resultado
    assert 7.0 <= segundos <= 7.15, f"tiene que cortar en el cierre de los 7,0 s, no en la pausa: {segundos:.2f}s"


def test_CONTROL_sin_la_guarda_el_respaldo_se_come_la_cifra():
    """La prueba de arriba sabe fallar: sin los datos de la última casada, el corte cae en la pausa de los 4,6 s."""
    wav = _audio(*_PAUSA_ANTES_DE_LA_CIFRA)
    _, segundos = vw._corta_por_silencio(wav, SR, palabras=14)
    assert segundos < 4.8, f"sin la guarda tendría que cortar en la pausa (el fallo del 07-10): {segundos:.2f}s"


# ---------------------------------------------------------------------------------------------
# 2. El generador nunca para el run
# ---------------------------------------------------------------------------------------------


class _Motor:
    """Motor falso: devuelve siempre el mismo audio. Lo que se prueba es la política de arriba."""

    sr = SR

    def __init__(self, wav):
        self._wav = wav
        self._seed = 1234
        self.llamadas = 0

    def generate(self, texto):
        self.llamadas += 1
        return self._wav


class _RecortadorQueNuncaCasa:
    """Como whisper con `fanlight`: no localiza la última palabra, nunca, con ninguna semilla."""

    def corta(self, wav, sr, texto):
        return wav, {"recortado": False, "palabras": "4/6"}


class _RecortadorQueCasaHastaLaPausa:
    """Como whisper en la lámina 15 de ese episodio: casa 13 de 14, hasta «about» (6,2 s); falta la cifra."""

    def corta(self, wav, sr, texto):
        return wav, {"recortado": False, "palabras": "13/14", "ultima_casada_s": 6.2, "pedidas_detras": 1}


class _RecortadorQueCasa:
    def corta(self, wav, sr, texto):
        return wav, {"recortado": True, "palabras": "6/6", "segundos_utiles": 4.0}


TEXTO_10 = "a fanlight over a panelled door and something more here"  # 10 palabras


def test_sin_recorte_por_texto_NO_muere_y_corta_por_silencio():
    wav = _audio(_habla(4.0), _silencio(0.5), _habla(3.0))  # hay silencio de cierre a los 4 s
    motor = _Motor(wav)
    out, intento, informe = vw._genera_con_plausibilidad(motor, TEXTO_10, None, 1, 1, _RecortadorQueNuncaCasa())
    assert informe["recortado"] is True
    assert informe["respaldo"] == "silencio"
    assert out.shape[-1] < wav.shape[-1], "el respaldo tiene que haber cortado la divagación"
    assert intento == 1, "UN reintento contra el azar, y luego el respaldo — no tres"
    assert motor._seed == 1234, "la semilla vuelve a la base al terminar"


def test_el_generador_pasa_la_ultima_casada_al_respaldo():
    """De punta a punta: el informe del recorte por texto llega al respaldo y el corte no se come la cifra."""
    wav = _audio(*_PAUSA_ANTES_DE_LA_CIFRA)
    motor = _Motor(wav)
    out, _, informe = vw._genera_con_plausibilidad(
        motor, _TEXTO_LAMINA_15, None, 1, 1, _RecortadorQueCasaHastaLaPausa()
    )
    assert informe["respaldo"] == "silencio"
    assert out.shape[-1] / SR >= 7.0, "el audio montado tiene que llegar hasta el cierre, cifra incluida"


def test_sin_recorte_ni_silencio_NO_muere_y_lo_anota():
    wav = _audio(_habla(4.5))  # habla continua: ni texto ni silencio dan un corte
    out, intento, informe = vw._genera_con_plausibilidad(_Motor(wav), TEXTO_10, None, 1, 1, _RecortadorQueNuncaCasa())
    assert informe["respaldo"] == "sin_recorte"
    assert informe["recortado"] is False
    assert out.shape[-1] == wav.shape[-1], "sin corte posible, el audio se monta entero"


def test_ritmo_implausible_persistente_NO_muere_y_se_queda_el_mejor():
    """CONTROL: antes esto era SystemExit. 10 palabras en 40 s son 15 wpm, fuera de [40, 320]."""
    wav = _audio(_habla(40.0))
    motor = _Motor(wav)
    out, intento, informe = vw._genera_con_plausibilidad(motor, TEXTO_10, None, 1, 1, _RecortadorQueCasa())
    assert "implausible" in informe and "wpm" in informe["implausible"]
    assert motor.llamadas == vw.REINTENTOS_MAXIMOS + 1, "agota los reintentos antes de rendirse"
    assert out.shape[-1] == wav.shape[-1]


def test_el_caso_normal_no_cambia():
    """CONTROL NEGATIVO de todo lo anterior: si casa a la primera, intento 0 y ninguna incidencia."""
    wav = _audio(_habla(4.0))  # 10 palabras en 4 s = 150 wpm, dentro de banda
    motor = _Motor(wav)
    out, intento, informe = vw._genera_con_plausibilidad(motor, TEXTO_10, None, 1, 1, _RecortadorQueCasa())
    assert intento == 0
    assert motor.llamadas == 1
    assert "respaldo" not in informe and "implausible" not in informe


def test_ninguna_ruta_lanza_system_exit():
    """La afirmación central, dicha en una sola prueba: sea lo que sea el audio, se devuelve algo."""
    casos = [
        (_audio(_habla(4.0), _silencio(0.5), _habla(3.0)), _RecortadorQueNuncaCasa()),
        (_audio(_habla(4.5)), _RecortadorQueNuncaCasa()),
        (_audio(_habla(40.0)), _RecortadorQueCasa()),
        (_audio(_habla(0.3)), _RecortadorQueCasa()),  # 10 palabras en 0,3 s: ritmo absurdo por arriba
    ]
    for wav, recortador in casos:
        out, _, informe = vw._genera_con_plausibilidad(_Motor(wav), TEXTO_10, None, 1, 1, recortador)
        assert out is not None and informe is not None
