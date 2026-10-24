"""`lib/escena/linea_tiempo.py` y `lib/escena/anclas.py`: de la narración del run a los tiempos del vídeo (F6.2b).

El run de prueba tiene dos láminas de voz (10,5 s y 7,8 s de wav) y el canal ficticio declara 1 s de intro,
2 s de pausa entre partes y 1,5 s de cola. Con eso cada tiempo se puede calcular a mano, y cada prueba lo hace.
"""

from __future__ import annotations

import copy
import json

import pytest
from utiles_escena import LAMINAS_PRUEBA, crea_run, escena_prueba, escribe_wav, linea_de_prueba, marcas_uniformes

from lib import config
from lib.escena import anclas
from lib.escena.ajustes import ErrorDeAjustes
from lib.escena.linea_tiempo import ErrorDeLinea, LineaDeTiempo, duracion_wav


@pytest.fixture(scope="module")
def linea(tmp_path_factory):
    return linea_de_prueba(tmp_path_factory.mktemp("linea") / "run")


# ------------------------------------------------------------------ wav
@pytest.mark.parametrize("flotante", [True, False])
def test_la_duracion_del_wav_se_lee_de_su_cabecera(tmp_path, flotante):
    """El wav de la voz es de coma flotante (formato 3), que `wave` no abre: aquí se leen los dos."""
    assert duracion_wav(escribe_wav(tmp_path / "a.wav", 3.25, flotante=flotante)) == pytest.approx(3.25)


def test_control_un_fichero_que_no_es_wav_para(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"ID3 esto es un mp3")
    with pytest.raises(ErrorDeLinea, match="no es un wav"):
        duracion_wav(tmp_path / "a.wav")


# ------------------------------------------------------------------ desfases y duración
def test_cada_lamina_empieza_tras_la_intro_las_anteriores_y_sus_pausas(linea):
    assert linea.laminas == [1, 2]
    # 10,5 s son 252 fotogramas justos; 7,8 s son 187,2 → 187 fotogramas (se redondea al más cercano).
    assert linea.tramos == [pytest.approx(10.5), pytest.approx(187 / 24)]
    assert linea.inicio == [pytest.approx(1.0), pytest.approx(1.0 + 10.5 + 2.0)]
    # Total: intro + las dos láminas + una pausa + cola, redondeado hacia arriba a un fotograma.
    assert linea.total == pytest.approx(1.0 + 10.5 + 187 / 24 + 2.0 + 1.5)
    assert round(linea.total * 24, 6) == int(round(linea.total * 24))


def test_una_palabra_cae_en_su_lamina_mas_su_marca(linea):
    """La 1.ª palabra de la lámina 2 tiene su marca en 0,3 s de su wav: en el vídeo, 13,5 + 0,3."""
    primera = next(p for p in linea.palabras if p.lamina == 1)
    assert (primera.texto, primera.ini, primera.fin) == ("The", pytest.approx(13.8), pytest.approx(14.1))
    assert all(p.anclada for p in linea.palabras)


def test_las_pausas_las_declara_el_canal_sin_defecto(tmp_path):
    esc = escena_prueba()
    del esc["pausas"]["entre_partes_s"]
    with pytest.raises(ErrorDeAjustes, match="pausas.entre_partes_s"):
        LineaDeTiempo.del_run(crea_run(tmp_path / "run", LAMINAS_PRUEBA), escena=esc, idioma="en")


def test_otra_pausa_mueve_la_segunda_lamina_y_nada_mas(tmp_path, linea):
    esc = escena_prueba()
    esc["pausas"]["entre_partes_s"] = 5.0
    otra = LineaDeTiempo.del_run(crea_run(tmp_path / "run", LAMINAS_PRUEBA), escena=esc, idioma="en")
    assert otra.inicio[0] == linea.inicio[0] and otra.inicio[1] == pytest.approx(linea.inicio[1] + 3.0)
    assert [c.texto for c in otra.cues] == [c.texto for c in linea.cues]


def test_control_una_lamina_con_narracion_y_sin_audio_para(tmp_path):
    run = crea_run(tmp_path / "run", LAMINAS_PRUEBA)
    config.audio_de_lamina(run, 2).unlink()
    with pytest.raises(ErrorDeLinea, match="lámina 2 tiene narración y no está su audio"):
        LineaDeTiempo.del_run(run, escena=escena_prueba(), idioma="en")


def test_una_lamina_sin_narracion_no_entra_en_la_linea_de_la_voz(tmp_path):
    laminas = [LAMINAS_PRUEBA[0], {"narration": "", "dura": 0}, LAMINAS_PRUEBA[1]]
    linea = LineaDeTiempo.del_run(crea_run(tmp_path / "run", laminas), escena=escena_prueba(), idioma="en")
    assert linea.laminas == [1, 3]


def test_control_sin_alineacion_para(tmp_path):
    run = crea_run(tmp_path / "run", LAMINAS_PRUEBA)
    config.alineacion_del_run(run).unlink()
    with pytest.raises(ErrorDeLinea, match="falta la alineación"):
        LineaDeTiempo.del_run(run, escena=escena_prueba(), idioma="en")


# ------------------------------------------------------------------ cues y anclas
def test_los_cues_salen_del_texto_y_no_de_la_voz(tmp_path, linea):
    """Otra voz (otro ritmo, otra duración) da los mismos cues: un tramo escrito contra el cue 5 sigue valiendo."""
    assert [c.texto for c in linea.cues] == [
        "Ana walked to the park with her red kite.",
        'She said, "Look at the kite, it is so big!"',
        "Bo laughed and ran after her.",
        "The kite flew over the trees.",
        'Bo said, "Wait for me!"',
        "Then they both sat on the grass.",
    ]
    laminas = copy.deepcopy(LAMINAS_PRUEBA)
    for lam in laminas:
        lam["marcas"] = marcas_uniformes(lam["narration"], desde=0.1, paso=0.31, dura=0.25)
        lam["dura"] = 9.0
    otra = linea_de_prueba(tmp_path / "run", laminas)
    assert [c.texto for c in otra.cues] == [c.texto for c in linea.cues]
    assert otra.cue(5).ini != linea.cue(5).ini


def test_un_cue_largo_se_parte_por_caracteres(tmp_path):
    esc = escena_prueba()
    esc["cues"]["max_caracteres"] = 20
    linea = LineaDeTiempo.del_run(crea_run(tmp_path / "run", LAMINAS_PRUEBA), escena=esc, idioma="en")
    assert all(len(c.texto) <= 20 or len(c.palabras) == 1 for c in linea.cues)
    assert " ".join(c.texto for c in linea.cues) == " ".join(p.texto for p in linea.palabras)


def test_las_anclas_dan_los_tiempos_del_video(linea):
    a = anclas.Anclas(linea)
    assert a.C(1) == pytest.approx(1.3)  # intro 1 s + la 1.ª marca, a 0,3 s
    assert a.F(1) == pytest.approx(1.0 + 0.3 + 8 * 0.4 + 0.3)  # «kite.», la 9.ª palabra
    assert a.P(1, "walked") == pytest.approx(1.7)
    assert a.P(2, "kite") == pytest.approx(1.0 + 0.3 + 14 * 0.4)  # la 2.ª «kite» de la lámina
    assert a.P(2, "the", k=0) == pytest.approx(1.0 + 0.3 + 13 * 0.4)
    assert a.HUECO(0) == (pytest.approx(11.5), pytest.approx(13.5))
    assert a.cues_del_tramo(0) == [1, 2, 3] and a.cues_del_tramo(1) == [4, 5, 6]
    assert a.cue_con("grass") == 6
    assert a.avisos == []


def test_una_palabra_del_cue_vecino_se_encuentra_y_se_avisa(linea):
    a = anclas.Anclas(linea)
    assert a.P(1, "laughed") == pytest.approx(a.P(3, "laughed"))
    assert a.avisos == ["P(1, 'laughed') está en el cue 3"]


def test_control_una_palabra_que_no_se_dice_para(linea):
    with pytest.raises(ErrorDeLinea, match="«dragon» no está en el cue 1"):
        anclas.Anclas(linea).P(1, "dragon")
    with pytest.raises(ErrorDeLinea, match="no hay pausa tras la lámina 1"):
        anclas.Anclas(linea).HUECO(1)


def test_las_funciones_sueltas_no_tienen_linea_por_omision(linea):
    anclas._ACTIVAS.clear()
    with pytest.raises(ErrorDeLinea, match="anclas.usa"):
        anclas.P(1, "walked")
    anclas.usa(linea)
    assert anclas.P(1, "walked") == pytest.approx(1.7) and anclas.C(4) == pytest.approx(13.8)


# ------------------------------------------------------------------ karaoke y habla
def test_los_grupos_caben_y_no_cruzan_de_lamina(linea):
    grupos = linea.grupos()
    assert all(len(" ".join(p.texto for p in g)) <= 40 for g in grupos)
    assert all(len({p.lamina for p in g}) == 1 for g in grupos)
    assert [p for g in grupos for p in g] == linea.palabras


def test_el_karaoke_pinta_a_quien_habla_con_su_clase(linea):
    """«Look at the kite, it is so big!» lo dice Ana (índices 11-18) y «Wait for me!», Bo; lo demás, el narrador."""
    clases = {(w[2], w[3]) for g in linea.karaoke() for w in g["w"]}
    assert {('"Look', "ana"), ('big!"', "ana"), ('"Wait', "bo"), ('me!"', "bo"), ("said,", "narrador")} <= clases
    assert sum(w[3] == "ana" for g in linea.karaoke() for w in g["w"]) == 8


def test_la_habla_de_cada_personaje_es_el_tramo_de_su_cita(linea):
    habla = linea.habla()
    assert set(habla) == {"ana", "bo"}
    assert habla["ana"] == [{"t": pytest.approx(1.0 + 0.3 + 11 * 0.4), "t1": pytest.approx(1.0 + 0.3 + 18 * 0.4 + 0.3)}]
    assert len(habla["bo"]) == 1


def test_control_un_personaje_fuera_del_reparto_para(tmp_path):
    laminas = copy.deepcopy(LAMINAS_PRUEBA)
    laminas[0]["hablantes"] = [{"desde": 11, "hasta": 19, "personaje": "Carla"}]
    with pytest.raises(ErrorDeLinea, match="«Carla» dice un diálogo .* no está en el reparto"):
        linea_de_prueba(tmp_path / "run", laminas)


def test_un_tramo_sin_personaje_es_del_narrador(tmp_path):
    """Así lo deja `scripts/hablantes.py` cuando no sabe atribuirlo: sin color, como en el karaoke quemado."""
    laminas = copy.deepcopy(LAMINAS_PRUEBA)
    laminas[0]["hablantes"] = [{"desde": 11, "hasta": 19, "personaje": None}]
    linea = linea_de_prueba(tmp_path / "run", laminas)
    assert "ana" not in linea.habla()
    assert all(p.hablante == "narrador" for p in linea.palabras if p.lamina == 0)


def test_una_palabra_que_el_alineador_no_oye_se_reparte_y_se_cuenta(tmp_path):
    laminas = copy.deepcopy(LAMINAS_PRUEBA)
    laminas[0]["marcas"] = marcas_uniformes(laminas[0]["narration"], quita={4})  # «park»
    linea = linea_de_prueba(tmp_path / "run", laminas)
    park = linea.palabras[4]
    assert park.texto == "park" and not park.anclada
    assert linea.palabras[3].fin <= park.ini < park.fin <= linea.palabras[5].ini
    assert linea.informe()["por_lamina"][0]["ancladas"] == 24


def _corta(tmp_path, esc) -> list[str]:
    frase = "Then we saw the dog run across the long road to the house by the river."
    run = crea_run(tmp_path, [{"narration": frase, "dura": 8.0}])
    return [" ".join(p.texto for p in g) for g in LineaDeTiempo.del_run(run, escena=esc, idioma="en").grupos()]


def test_una_linea_no_se_queda_colgando_de_un_articulo(tmp_path):
    cortes = _corta(tmp_path / "a", escena_prueba())
    assert len(cortes) > 1 and not any(c.split()[-1] in ("the", "a", "to") for c in cortes)


def test_control_sin_las_palabras_del_idioma_el_corte_cae_en_un_articulo(tmp_path):
    """Las listas son del canal (su idioma): sin ellas, el corte más equilibrado deja «the» al final."""
    esc = escena_prueba()
    esc["karaoke"]["no_cierran"] = []
    esc["karaoke"]["conjunciones"] = []
    assert any(c.split()[-1] == "the" for c in _corta(tmp_path / "b", esc))


def test_el_informe_cuenta_lo_que_ancla_cada_lamina(linea):
    informe = linea.informe()
    assert (informe["palabras"], informe["ancladas"], informe["cues"]) == (43, 43, 6)
    assert [x["lamina"] for x in informe["por_lamina"]] == [1, 2]
    json.dumps(informe)  # se puede escribir tal cual en el run
