"""F6.3b: el karaoke del motor de escena no enciende ninguna palabra en silencio antes de que se diga.

Cada caso es una alineación de whisper fabricada con el defecto que se midió en el episodio de la bici, y la
voz que «suena» en su wav está escrita al lado (`VOZ`: los tramos en que se dice cada palabra). Así cada prueba
tiene su control negativo: con el camino de antes (`alineacion.empareja` + `reparte_tiempos_colapsados`, lo que
sigue usando el motor viejo) la palabra se enciende en un silencio, y con `tiempos_de_palabras` no.

Las otras pruebas son las guardas que salieron de pasar el arreglo por los 17 runs con audio de los dos canales
(`progress/impl_F6.3b.md`): lo que el arreglo NO debe tocar.
"""

from __future__ import annotations

import copy
import struct

import pytest
from utiles_escena import crea_run, escena_prueba

from lib import alineacion, config
from lib.escena import linea_tiempo
from lib.escena.linea_tiempo import LineaDeTiempo, _reparte_colapsadas, tiempos_de_palabras

TOLERANCIA_S = 0.05  # lo que una palabra puede encenderse antes de que su voz empiece sin que se note
COLA_S = 0.1  # la voz que queda tras el inicio y que no es la de esta palabra, sino la cola de la anterior


def _m(texto: str, desde: float, hasta: float) -> dict:
    return {"texto": texto, "desde": desde, "hasta": hasta}


def _palabras(texto: str) -> list[str]:
    return alineacion.texto_para_pintar(texto, "en").split()


def _camino_de_antes(palabras: list[str], marcas: list[dict]) -> list[dict]:
    alineado = alineacion.empareja(palabras, copy.deepcopy(marcas))
    alineacion.reparte_tiempos_colapsados(alineado)
    return alineado


def _en_silencio(t: float, voz: list[tuple[float, float]]) -> bool:
    """La palabra encendida en `t` espera en silencio a su voz.

    Es así si en `t` no suena nada (ni empieza a sonar en TOLERANCIA_S), o si lo único que suena es la cola de la
    palabra anterior (menos de COLA_S). Es el caso de «because»: se encendía justo cuando acababa «them», y luego
    venía 1,5 s de silencio.
    """
    return not any(a - TOLERANCIA_S <= t and b - t >= COLA_S for a, b in voz)


# ------------------------------------------------------------------ los casos del episodio de la bici
# 1. Dos pasadas de whisper: la segunda (tras alucinar «Thank you.» con 0 s) pega la pausa al INICIO de «because» y
#    de «he»; la primera, al final de la palabra anterior. El emparejador se queda con la segunda.
DOS_PASADAS = "They looked at them, because they were black. He put them down."
DOS_PASADAS_MARCAS = (
    [_m("They", 0.30, 0.50), _m("looked", 0.50, 0.80), _m("at", 0.80, 0.95), _m("them.", 0.95, 2.80)]
    + [_m("Because", 2.80, 3.10), _m("they", 3.10, 3.30), _m("were", 3.30, 3.45), _m("black,", 3.45, 4.60)]
    + [_m("he", 4.60, 4.80), _m("put", 4.80, 5.00), _m("them", 5.00, 5.20)]
    + [_m("Thank", 5.20, 5.20), _m("you.", 5.20, 5.20)] * 3
    + [_m("them", 0.95, 1.30), _m("because", 1.30, 3.10), _m("they", 3.10, 3.30), _m("were", 3.30, 3.45)]
    + [_m("black", 3.45, 3.90), _m("he", 3.90, 4.80), _m("put", 4.80, 5.00), _m("them", 5.00, 5.20)]
    + [_m("down.", 5.20, 5.60)]
)
DOS_PASADAS_VOZ = [(0.30, 1.30), (2.80, 3.90), (4.60, 5.60)]  # «…them,» | silencio | «because … black.» | «He …»

# 2. Una palabra corta tras una pausa: «stopped, and». Whisper la oye dos veces; el emparejador le da la marca corta
#    (0,04 s), y el reparto de antes la llevaba al final de «stopped», en mitad de la pausa.
TRAS_PAUSA = "And they all stopped, and in the quiet."
TRAS_PAUSA_MARCAS = [
    _m("And", 0.30, 0.50), _m("they", 0.50, 0.65), _m("all", 0.65, 0.80), _m("stopped", 0.80, 1.20),
    _m("and", 1.20, 2.07), _m("And", 2.10, 2.14), _m("in", 2.14, 2.25), _m("the", 2.25, 2.35),
    _m("quiet.", 2.35, 2.90),
]  # fmt: skip
TRAS_PAUSA_VOZ = [(0.30, 1.20), (2.05, 2.90)]

# 3. El bucle alucinado: «and she sat on it» repetido con 0 s. El emparejador ata el guion a esas marcas nulas y el
#    reparto lo extiende a partes iguales, así que el segundo «and» cae en la pausa que sigue a «it...».
BUCLE = "to the kerb, and she sat on it... and nothing happened."
BUCLE_MARCAS = (
    [_m("to", 0.30, 0.45), _m("the", 0.45, 0.55), _m("curb,", 0.55, 1.00), _m("and", 1.00, 1.10)]
    + [_m("she", 1.10, 1.28), _m("sat", 1.28, 1.62), _m("on", 1.62, 1.86), _m("it,", 1.86, 2.60)]
    + [_m(w, 2.60, 2.60) for w in ["and", "she", "sat", "on", "it,"] * 3]
    + [_m("happened.", 3.05, 3.60)]
)
BUCLE_VOZ = [(0.30, 2.30), (2.60, 3.60)]

# 4. Dos pasadas que solo SE TOCAN (revisión de F6.3b, §4: «the kite is in the tree», lámina 1). La segunda pasada pega
#    la pausa al inicio de «He» (2,94-3,54 s); la primera oyó «He» de 3,52 a 3,58 s. Las dos marcas se solapan
#    0,02 s, menos de la mitad de la corta, y aun así son el mismo sonido: la buena empieza dentro de la mala.
SE_TOCAN = "It was very important. He did not want it."
SE_TOCAN_MARCAS = (
    [_m("It", 0.10, 0.20), _m("was", 0.20, 0.30), _m("very", 0.30, 0.90), _m("important.", 0.90, 2.66)]
    + [_m("He", 3.52, 3.58), _m("did", 3.58, 3.72), _m("not", 3.72, 3.96), _m("want", 3.96, 4.26)]
    + [_m("Thank", 4.26, 4.26), _m("you.", 4.26, 4.26)] * 3
    + [_m("very", 0.28, 0.90), _m("important.", 0.90, 2.94), _m("He", 2.94, 3.54), _m("did", 3.54, 3.70)]
    + [_m("not", 3.70, 3.96), _m("want", 3.96, 4.26), _m("it.", 4.26, 4.80)]
)
SE_TOCAN_VOZ = [(0.10, 1.80), (3.43, 4.80)]


@pytest.mark.parametrize(
    "texto, marcas, voz, cuales",
    [
        (DOS_PASADAS, DOS_PASADAS_MARCAS, DOS_PASADAS_VOZ, {"because", "He"}),
        (TRAS_PAUSA, TRAS_PAUSA_MARCAS, TRAS_PAUSA_VOZ, {"and"}),
        (BUCLE, BUCLE_MARCAS, BUCLE_VOZ, {"and"}),
        (SE_TOCAN, SE_TOCAN_MARCAS, SE_TOCAN_VOZ, {"He"}),
    ],
    ids=["dos-pasadas", "corta-tras-pausa", "bucle-nulo", "dos-pasadas-que-se-tocan"],
)
def test_ninguna_palabra_se_enciende_en_silencio(texto, marcas, voz, cuales):
    palabras = _palabras(texto)
    alineado, _ = tiempos_de_palabras(palabras, copy.deepcopy(marcas))
    en_silencio = [p["palabra"] for p in alineado if _en_silencio(p["desde"], voz)]
    assert en_silencio == []
    # Control negativo: el camino de antes, sobre la MISMA alineación, enciende esas palabras en el silencio.
    antes = [p["palabra"] for p in _camino_de_antes(palabras, marcas) if _en_silencio(p["desde"], voz)]
    assert set(antes) == cuales


def test_las_dos_pasadas_toman_la_marca_de_cada_palabra_que_no_se_traga_la_pausa():
    alineado, _ = tiempos_de_palabras(_palabras(DOS_PASADAS), copy.deepcopy(DOS_PASADAS_MARCAS))
    inicio = {p["palabra"]: p["desde"] for p in alineado}
    assert inicio["because"] == pytest.approx(2.80) and inicio["He"] == pytest.approx(4.60)
    # Las que no se tragaron nada siguen donde estaban, y todas conservan su marca.
    assert inicio["them,"] == pytest.approx(0.95) and inicio["down."] == pytest.approx(5.20)
    assert all(p["anclada"] for p in alineado)


def test_la_otra_pasada_que_empieza_dentro_vale_aunque_solo_se_toquen():
    alineado, _ = tiempos_de_palabras(_palabras(SE_TOCAN), copy.deepcopy(SE_TOCAN_MARCAS))
    he = alineado[4]
    assert he["palabra"] == "He" and he["desde"] == pytest.approx(3.52) and he["anclada"]


def test_la_corta_tras_pausa_conserva_su_marca_y_sigue_contando_como_anclada():
    alineado, _ = tiempos_de_palabras(_palabras(TRAS_PAUSA), copy.deepcopy(TRAS_PAUSA_MARCAS))
    y = alineado[4]
    assert y["palabra"] == "and" and y["desde"] == pytest.approx(2.10) and y["anclada"]


def test_el_bucle_se_rescata_con_las_marcas_reales_de_la_primera_pasada():
    alineado, _ = tiempos_de_palabras(_palabras(BUCLE), copy.deepcopy(BUCLE_MARCAS))
    reales = [(p["palabra"], p["desde"]) for p in alineado[3:8]]
    assert reales == [("and", 1.00), ("she", 1.10), ("sat", 1.28), ("on", 1.62), ("it...", 1.86)]
    # «kerb» no lo dice ninguna marca (whisper oyó «curb»): no se sustituye una palabra por otra, se reparte.
    assert not alineado[2]["anclada"]


# ------------------------------------------------------------------ lo que el arreglo NO toca
def test_sin_palabras_no_hay_nada_que_alinear_como_en_el_estudio():
    assert tiempos_de_palabras([], [_m("He", 0.1, 0.2)]) == ([], 0)
    assert alineacion.empareja([], [_m("He", 0.1, 0.2)]) == []


def test_una_corta_en_habla_seguida_se_reparte_como_siempre():
    """«one side of»: whisper le da a «side» una marca de 0,04 s al final de la palabra. Conservarla la encendería
    0,36 s tarde (medido en «the whole kitchen turns white», lámina 1); repartirla acierta. Con un hueco de
    menos de `HUECO_DE_PAUSA_S` el camino es el de antes."""
    texto = "on one side of her face."
    marcas = [
        _m("on", 0.30, 0.50), _m("one", 0.50, 0.74), _m("side", 1.10, 1.14), _m("of", 1.14, 1.36),
        _m("her", 1.36, 1.50), _m("face.", 1.50, 2.00),
    ]  # fmt: skip
    alineado, _ = tiempos_de_palabras(_palabras(texto), copy.deepcopy(marcas))
    assert alineado == _camino_de_antes(_palabras(texto), marcas)
    assert alineado[2]["desde"] == pytest.approx(0.74)


def test_una_marca_que_solo_roza_la_de_la_palabra_no_es_el_mismo_sonido():
    """«Dad. Dad,» con dos pasadas (medido en «now one side is shorter», lámina 5): la marca libre del segundo
    «Dad» toca la del primero 0,02 s y EMPIEZA dentro de ella. Si contara, el primero se encendería 1,1 s tarde, en
    el segundo. No cuenta por las dos guardas: no cae en su mayor parte dentro, y la palabra siguiente del guion es
    la misma (lo que distingue este caso del de `SE_TOCAN`)."""
    texto = 'He said, "Dad. Dad, is it bad?"'
    marcas = [
        _m("He", 0.10, 0.70), _m("said,", 0.70, 1.76), _m("Dad,", 1.76, 2.92), _m("Dad,", 2.92, 4.00),
        _m("is", 4.00, 4.18), _m("it", 4.18, 4.34), _m("bad?", 4.34, 5.94),
        _m("He", 0.12, 0.72), _m("said,", 0.72, 1.78), _m("dad,", 1.78, 2.94), _m("dad,", 2.94, 4.02),
        _m("is", 4.02, 4.18), _m("it", 4.18, 4.32), _m("bad?", 4.32, 5.98),
    ]  # fmt: skip
    alineado, _ = tiempos_de_palabras(_palabras(texto), copy.deepcopy(marcas))
    assert [round(p["desde"], 2) for p in alineado[2:4]] == [1.78, 2.94]


def test_una_marca_que_el_emparejador_dio_a_otra_palabra_no_se_roba():
    """Una marca larga de más («good.» de 12,5 s, medido en «now one side is shorter», lámina 3) contiene la del
    SEGUNDO «good.» del guion. Esa ya es de otra palabra: si se la quedara la primera, el karaoke se saltaría una
    frase entera. El resultado es el del camino de antes, con su defecto (la cascada tras la marca larga), que no
    es de esta feature."""
    texto = 'Dad said, "It is very good." Nora said, "It is not very good."'
    marcas = [
        _m("Dad", 0.30, 0.90), _m("said,", 0.90, 1.90), _m("It", 1.90, 2.00), _m("is", 2.00, 2.20),
        _m("very", 2.20, 2.50), _m("good.", 2.50, 9.00), _m("Nora", 3.00, 3.10), _m("said,", 3.10, 4.20),
        _m("It", 4.20, 4.50), _m("is", 4.50, 4.70), _m("not", 4.70, 5.00), _m("very", 5.00, 5.40),
        _m("good.", 5.40, 6.40),
    ]  # fmt: skip
    alineado, _ = tiempos_de_palabras(_palabras(texto), copy.deepcopy(marcas))
    assert alineado == _camino_de_antes(_palabras(texto), marcas)
    assert alineado[5]["desde"] == pytest.approx(2.50)


def _alineado(pares: list[tuple[float, float]], ancladas: bool = True) -> list[dict]:
    return [{"palabra": f"w{i}", "desde": a, "hasta": b, "anclada": ancladas} for i, (a, b) in enumerate(pares)]


@pytest.mark.parametrize(
    "pares",
    [
        [(0.0, 0.3), (0.3, 0.6)] + [(0.6, 0.6)] * 9 + [(6.5, 6.8)],  # nueve colapsadas en mitad (el 05-09)
        [(0.0, 0.0), (0.0, 0.0), (1.0, 1.3), (1.3, 1.5)],  # colapsadas al principio
        [(0.0, 0.3), (0.3, 0.6), (0.6, 0.6), (0.6, 0.6)],  # y al final
        [(0.0, 0.4), (0.3, 0.6), (0.2, 0.5), (0.9, 1.2)],  # marcas desordenadas
        [(0.0, 0.3), (0.35, 0.38), (0.38, 0.7)],  # una corta, sin nada que conservar
    ],
)
def test_sin_nada_que_conservar_el_reparto_es_el_del_estudio(pares):
    nuestro, suyo = _alineado(pares), _alineado(pares)
    tocadas = _reparte_colapsadas(nuestro, set())
    assert tocadas == alineacion.reparte_tiempos_colapsados(suyo)
    assert nuestro == suyo


# ------------------------------------------------------------------ en el karaoke de la escena
def _wav_con_voz(ruta, segundos: float, voz: list[tuple[float, float]], sr: int = 8000) -> None:
    """Un wav de coma flotante con un tono donde hay voz y ceros (silencio digital) en las pausas."""
    import math

    muestras = [0.0] * round(segundos * sr)
    for a, b in voz:
        for n in range(round(a * sr), round(b * sr)):
            muestras[n] = 0.3 * math.sin(2 * math.pi * 220 * n / sr)
    datos = struct.pack(f"<{len(muestras)}f", *muestras)
    fmt = struct.pack("<HHIIHH", 3, 1, sr, sr * 4, 4, 32)
    ruta.write_bytes(
        b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(datos)) + b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", len(datos)) + datos
    )  # fmt: skip


def _voz_del_wav(ruta) -> list[tuple[float, float]]:
    """Los tramos con voz del wav, leídos de sus muestras (10 ms), para no fiarse de lo que se escribió."""
    datos = ruta.read_bytes()
    sr = struct.unpack("<I", datos[24:28])[0]
    muestras = struct.unpack(f"<{(len(datos) - 44) // 4}f", datos[44:])
    paso = sr // 100
    tramos, abierto = [], None
    for i in range(0, len(muestras), paso):
        suena = any(abs(x) > 1e-4 for x in muestras[i : i + paso])
        if suena and abierto is None:
            abierto = i / sr
        elif not suena and abierto is not None:
            tramos.append((abierto, i / sr))
            abierto = None
    if abierto is not None:
        tramos.append((abierto, len(muestras) / sr))
    return tramos


@pytest.fixture
def run_dos_pasadas(tmp_path):
    run = crea_run(tmp_path / "run", [{"narration": DOS_PASADAS, "dura": 6.0, "marcas": DOS_PASADAS_MARCAS}])
    _wav_con_voz(config.audio_de_lamina(run, 1), 6.0, DOS_PASADAS_VOZ)
    return run


def _karaoke_en_silencio(linea: LineaDeTiempo, voz: list[tuple[float, float]]) -> list[str]:
    """Las palabras del karaoke del GUION que se encienden en silencio: su inicio, pasado al tiempo de su wav."""
    base = linea.inicio[0]
    return [w[2] for g in linea.karaoke() for w in g["w"] if _en_silencio(w[0] - base, voz)]


def test_el_karaoke_de_la_escena_enciende_cada_palabra_cuando_suena(run_dos_pasadas):
    linea = LineaDeTiempo.del_run(run_dos_pasadas, escena=escena_prueba(), idioma="en")
    voz = _voz_del_wav(config.audio_de_lamina(run_dos_pasadas, 1))
    assert _karaoke_en_silencio(linea, voz) == []


def test_control_con_el_camino_de_antes_el_karaoke_se_adelanta_a_la_voz(run_dos_pasadas, monkeypatch):
    def antes(palabras, marcas):
        alineado = alineacion.empareja(palabras, marcas)
        return alineado, alineacion.reparte_tiempos_colapsados(alineado)

    monkeypatch.setattr(linea_tiempo, "tiempos_de_palabras", antes)
    linea = LineaDeTiempo.del_run(run_dos_pasadas, escena=escena_prueba(), idioma="en")
    voz = _voz_del_wav(config.audio_de_lamina(run_dos_pasadas, 1))
    assert _karaoke_en_silencio(linea, voz) == ["because", "He"]


# ------------------------------------------------------------------ las cifras en dígitos (F7.10, fila 262)
def _marcas_de(*pares):
    t, salida = 0.0, []
    for texto, dura in pares:
        salida.append({"texto": texto, "desde": round(t, 3), "hasta": round(t + dura, 3)})
        t += dura
    return salida


CIFRA = "After ten years, it is about one hundred ninety-seven dollars. Then more."
OIDO_CIFRA = _marcas_de(("After", 0.3), ("10", 0.3), ("years,", 0.4), ("it", 0.2), ("is", 0.2), ("about", 0.4),
                        ("$197.", 1.6), ("Then", 0.3), ("more.", 0.4))  # fmt: skip


def test_una_cifra_en_digitos_reparte_su_marca_entre_las_palabras_que_la_dicen():
    from lib.escena.linea_tiempo import tiempos_de_palabras

    alineado, _ = tiempos_de_palabras(CIFRA.split(), OIDO_CIFRA)
    cifra = alineado[6:10]  # one hundred ninety-seven dollars
    assert all(p["anclada"] for p in cifra)
    assert cifra[0]["desde"] == pytest.approx(1.8) and cifra[-1]["hasta"] == pytest.approx(3.4)
    assert [round(p["hasta"] - p["desde"], 2) for p in cifra] == [0.4, 0.4, 0.4, 0.4]
    assert alineado[1]["desde"] == pytest.approx(0.3), "«ten» sigue con su marca «10», como antes"


def test_CONTROL_una_cifra_distinta_no_se_reparte_la_marca():
    from lib.escena.linea_tiempo import tiempos_de_palabras

    oido = [dict(m, texto="$179.") if m["texto"] == "$197." else m for m in OIDO_CIFRA]
    alineado, _ = tiempos_de_palabras(CIFRA.split(), oido)
    assert sum(p["anclada"] for p in alineado[6:10]) < 4, "179 no es 197: no se reparte su marca"


def test_CONTROL_con_dos_tramos_que_dicen_la_misma_cifra_no_se_elige():
    from lib.escena.linea_tiempo import _casa_las_cifras

    palabras = "seven or seven".split()
    marcas = _marcas_de(("7", 0.3), ("or", 0.2), ("seven", 0.3))
    elegida = {1: 1, 2: 2}  # «or» y el segundo «seven» ya emparejados; el primero no
    assert _casa_las_cifras(palabras, marcas, elegida, {0}) == {0: (0.0, 0.3)}
    # Y si la marca no tiene vecinas que acoten el tramo y la cifra se dice dos veces, no se toca nada.
    assert _casa_las_cifras(["seven", "seven"], _marcas_de(("7", 0.3)), {}, {0}) == {}
