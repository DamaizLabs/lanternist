"""El worker comprueba lo que el segmento DIJO, no solo cuánto duró (F5.9).

Correr: .venv\\Scripts\\python -m pytest -q tests/test_voz_se_comio_texto.py

**De dónde sale.** El 15-09 se oyó que la lámina 5 del episodio de un canal decía «Biscuit.» donde el
guion pedía «Biscuit! No! Sit!». El audio se montó igual: las dos guardas que había miden el TIEMPO
—ritmo implausible y saturación— y el recorte por texto mira dónde ACABA la frase, no si se dijo
entera. El gate de narración tampoco lo vio (addendum fila 174), así que el único que lo cazó fue su
oído.

**Los dos umbrales están medidos, no elegidos**, sobre los 2.325 segmentos con cobertura registrada
en la procedencia de los 12 episodios producidos: mediana 100 %, p5 88,9 %, p1 80 %, **mínimo 60 % —
que es exactamente ese segmento, 3 de 5 palabras**. Con `faltan>=2 Y fracción<0,75` disparan 9 de los
2.325 (0,4 %, menos de uno por episodio) y el caso del «Biscuit» entra; con `faltan>=3` no entra.

Los motores y recortadores son falsos: esto prueba la POLÍTICA, no a Orpheus ni a whisper.
"""

import pytest

torch = pytest.importorskip("torch")

from lib import voice_worker as vw  # noqa: E402

SR = 24_000
TEXTO_5 = 'Nora said, "Biscuit! No! Sit!"'  # las 5 palabras del caso real


def _habla(segundos: float, nivel: float = 0.5):
    g = torch.Generator().manual_seed(7)
    return ((torch.rand(int(SR * segundos), generator=g) * 2 - 1) * nivel).unsqueeze(0)


class _Motor:
    sr = SR

    def __init__(self, wav):
        self._wav, self._seed, self.llamadas = wav, 1234, 0

    def generate(self, texto):
        self.llamadas += 1
        return self._wav


class _Recortador:
    """Casa siempre, pero localiza las palabras que se le digan. `por_intento` permite variarlo."""

    def __init__(self, *por_intento: tuple[int, int]):
        self._por_intento, self.veces = list(por_intento), 0

    def corta(self, wav, sr, texto):
        casadas, pedidas = self._por_intento[min(self.veces, len(self._por_intento) - 1)]
        self.veces += 1
        return wav, {
            "recortado": True,
            "palabras": f"{casadas}/{pedidas}",
            "casadas": casadas,
            "pedidas": pedidas,
            "fraccion_casada": round(casadas / pedidas, 3),
            "sin_casar_seguidas": pedidas - casadas,
            "segundos_utiles": 3.0,
        }


# --- La regla, en sus fronteras -------------------------------------------------------------


def test_el_caso_REAL_del_biscuit_dispara():
    """3 de 5 palabras: el mínimo de los 2.325 segmentos medidos, y el que originó la feature."""
    assert vw._se_comio_texto({"recortado": True, "pedidas": 5, "casadas": 3}) is True


@pytest.mark.parametrize(
    ("casadas", "pedidas", "espera", "por_que"),
    [
        (20, 21, False, "una palabra suelta es el reconocedor, no el motor"),
        (6, 8, False, "faltan 2 pero cubre el 75 %: es la frontera, y la frontera NO dispara"),
        (5, 8, True, "faltan 3 y cubre el 62,5 %"),
        (4, 5, False, "falta UNA sola palabra, por baja que sea la fracción"),
        (3, 6, True, "faltan 3 y cubre la mitad"),
    ],
)
def test_las_fronteras_de_la_regla(casadas, pedidas, espera, por_que):
    assert vw._se_comio_texto({"recortado": True, "pedidas": pedidas, "casadas": casadas}) is espera, por_que


def test_lo_que_NO_puede_medir_no_lo_reintenta():
    """CONTROL NEGATIVO: donde el número no mide al motor, la guarda calla en vez de inventar.

    Los tres caminos, y el tercero lo destapó la auditoría de F5.9 midiendo en vez de leer el
    docstring: **el respaldo por silencio SÍ arrastra `casadas`/`pedidas`** con `{**informe, ...}`,
    así que sin la salida por `respaldo` un 3/10 que no casó volvería a gastar cuatro generaciones
    por un número que mide al reconocedor y no al motor.
    """
    assert vw._se_comio_texto({"recortado": True, "segundos_utiles": 3.0}) is False, "canal sin recorte"
    assert vw._se_comio_texto({"recortado": False, "pedidas": 5, "casadas": 1}) is False, "manda sin_recortar"
    assert vw._se_comio_texto({}) is False
    respaldo = {"recortado": True, "respaldo": "silencio", "pedidas": 10, "casadas": 3, "segundos_utiles": 3.0}
    assert vw._se_comio_texto(respaldo) is False, "el respaldo por silencio no se vuelve a reintentar"
    assert vw._se_comio_texto({**respaldo, "respaldo": None}) is True, "y sin él, esos mismos números SÍ disparan"


# --- La política: qué hace el generador con eso ---------------------------------------------


def test_si_se_comio_texto_REINTENTA_con_otra_semilla():
    wav = _habla(2.0)  # 5 palabras en 2 s = 150 wpm: el ritmo está en banda, así que no es eso
    motor = _Motor(wav)
    recortador = _Recortador((3, 5))  # se lo come en todos los intentos
    _out, intento, informe = vw._genera_con_plausibilidad(motor, TEXTO_5, None, 1, 1, recortador)
    assert motor.llamadas == vw.REINTENTOS_MAXIMOS + 1, "agota los reintentos antes de rendirse"
    assert intento == 0, "los cuatro salen igual de mal, así que se queda el primero — pero se montó igual"
    assert "se comió texto" in informe["implausible"], "y el episodio lleva la incidencia escrita"
    assert motor._seed == 1234, "la semilla vuelve a la base al terminar"


def test_si_un_reintento_lo_arregla_se_queda_con_ese():
    wav = _habla(2.0)
    motor = _Motor(wav)
    recortador = _Recortador((3, 5), (5, 5))  # el segundo intento sí lo dice entero
    _out, intento, informe = vw._genera_con_plausibilidad(motor, TEXTO_5, None, 1, 1, recortador)
    assert intento == 1
    assert motor.llamadas == 2, "en cuanto sale bien, para"
    assert "implausible" not in informe


def test_el_MEJOR_intento_es_el_que_mas_dijo():
    """Sin el peso por palabra, `distancia` valía 0 en los cuatro y se quedaba el PRIMERO.

    Aquí el primer intento dice 2 de 5 y el tercero 4 de 5, los dos con el ritmo en banda: el que se
    monta tiene que ser el segundo, no el que llegó antes.
    """
    motor = _Motor(_habla(2.0))
    recortador = _Recortador((2, 5), (2, 5), (4, 5), (2, 5))
    _out, _intento, informe = vw._genera_con_plausibilidad(motor, TEXTO_5, None, 1, 1, recortador)
    assert informe["casadas"] == 4, "se monta el intento que más palabras dijo"


def test_CONTROL_NEGATIVO_un_segmento_completo_no_reintenta():
    """Si disparara siempre, cada episodio pagaría cuatro veces la voz entera."""
    motor = _Motor(_habla(2.0))
    _out, intento, informe = vw._genera_con_plausibilidad(motor, TEXTO_5, None, 1, 1, _Recortador((5, 5)))
    assert intento == 0
    assert motor.llamadas == 1
    assert "implausible" not in informe


def test_el_informe_del_recortador_trae_con_que_decidir():
    """Los campos son nuevos (F5.9): antes solo iba `palabras` como texto, que nadie comparaba."""
    recortador = _Recortador((3, 5))
    _wav, informe = recortador.corta(None, SR, TEXTO_5)
    assert {"casadas", "pedidas", "fraccion_casada", "sin_casar_seguidas"} <= set(informe)


# --- La racha, que es el único cálculo nuevo y se probaba sobre el doble ---------------------


@pytest.mark.parametrize(
    ("marcas", "espera", "por_que"),
    [
        ([1, 2, 3], 0, "todas casan"),
        ([], 0, "sin marcas no hay racha"),
        ([None, None, None], 3, "no casa ninguna"),
        ([1, None, 2, None, 3], 1, "dos fallos SUELTOS son ruido del reconocedor"),
        ([1, None, None, None, 2], 3, "tres seguidos son una frase perdida"),
        ([None, None, 1, None, None, None], 3, "se queda con la MAYOR, no con la primera"),
        ([1, 2, None, None], 2, "una racha que acaba en el final del segmento cuenta igual"),
    ],
)
def test_la_racha_mide_lo_SEGUIDO_y_no_el_total(marcas, espera, por_que):
    """`sin_casar_seguidas` distingue una frase perdida de palabras sueltas mal transcritas.

    Se prueba sobre `lib.voice_worker._racha_sin_casar`, que es el código real: hasta que se extrajo
    a función, el bucle vivía dentro de `RecortadorPorTexto.corta` y **nadie lo cubría** — la prueba
    de arriba comprueba el doble de esta suite, no al recortador (lo apuntó la auditoría de F5.9).
    """
    assert vw._racha_sin_casar(marcas) == espera, por_que


def test_la_racha_no_es_lo_mismo_que_contar_los_fallos():
    """CONTROL: dos listas con las MISMAS palabras sin casar y rachas distintas."""
    sueltas = [1, None, 2, None, 3, None, 4]
    seguidas = [1, 2, 3, 4, None, None, None]

    assert sum(1 for m in sueltas if m is None) == sum(1 for m in seguidas if m is None) == 3
    assert vw._racha_sin_casar(sueltas) == 1
    assert vw._racha_sin_casar(seguidas) == 3
