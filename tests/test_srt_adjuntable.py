"""El `.srt` que una persona adjunta en Studio: que sea válido, y que se distinga del `.ass`.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_srt_adjuntable.py

**De dónde sale.** El 10-09, con el episodio 1 ya subido: «Los subtítulos en .ass no me los
reconoce, tienen que ser en .srt y con tiempos». El `.srt` del run estaba bien —464 bloques, tiempos
crecientes, sin solapes—, así que el defecto no era el fichero sino que **el run tiene dos ficheros de
subtítulos y el que se llama como la carpeta es el que Studio NO acepta**: el `.ass` es el karaoke que se
quema en el vídeo y vive en el directorio de trabajo `subtitulos/`.

De ahí dos guardas, y estas pruebas fijan las dos:

1. `subtitulos.valida_srt` comprueba lo que Studio rechaza cuando falta, **con un control negativo por
   cada regla**: sin él, «pasa» no distingue entre «vale» y «la comprobación no sabe fallar».
2. La subida dice **cuál de los dos ficheros es** y cuál no vale, en el estado del run y por pantalla.
"""

from pathlib import Path

import pytest

from lib.subtitulos import SubtitulosError, valida_srt

BUENO = "1\n00:00:00,000 --> 00:00:02,500\nHello, and welcome.\n\n2\n00:00:02,500 --> 00:00:04,000\nToday's exhibit.\n"


def _escribe(tmp_path: Path, texto: str, nombre: str = "subtitulos.en.srt") -> Path:
    ruta = tmp_path / nombre
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def test_un_srt_bien_formado_pasa_y_dice_cuantos_bloques_y_hasta_donde(tmp_path):
    datos = valida_srt(_escribe(tmp_path, BUENO))
    assert datos["bloques"] == 2 and datos["hasta_s"] == 4.0


# --- un control negativo por regla ------------------------------------------------------------


def test_los_tiempos_con_PUNTO_en_vez_de_coma_se_rechazan(tmp_path):
    """El punto es el separador de otro estándar; Studio no lo acepta y es el error más fácil de colar."""
    with pytest.raises(SubtitulosError, match="número / tiempos / texto"):
        valida_srt(_escribe(tmp_path, BUENO.replace(",", ".")))


def test_un_fichero_sin_tiempos_se_rechaza(tmp_path):
    """Literalmente lo que se describió: texto sin marcas de tiempo."""
    with pytest.raises(SubtitulosError, match="número / tiempos / texto"):
        valida_srt(_escribe(tmp_path, "1\nHello, and welcome.\n\n2\nToday's exhibit.\n"))


def test_la_numeracion_saltada_se_rechaza(tmp_path):
    with pytest.raises(SubtitulosError, match="numerado como 7"):
        valida_srt(_escribe(tmp_path, BUENO.replace("\n2\n", "\n7\n")))


def test_un_bloque_que_termina_antes_de_empezar_se_rechaza(tmp_path):
    roto = "1\n00:00:05,000 --> 00:00:02,000\nHello.\n"
    with pytest.raises(SubtitulosError, match="termina en"):
        valida_srt(_escribe(tmp_path, roto))


def test_dos_bloques_solapados_se_rechazan(tmp_path):
    solapado = BUENO.replace("00:00:02,500 --> 00:00:04,000", "00:00:01,000 --> 00:00:04,000")
    with pytest.raises(SubtitulosError, match="el anterior acaba en"):
        valida_srt(_escribe(tmp_path, solapado))


def test_un_resto_de_etiqueta_ASS_se_rechaza(tmp_path):
    """Si el karaoke se cuela en el `.srt`, YouTube pinta «{\\k28}» como texto."""
    con_karaoke = BUENO.replace("Hello, and welcome.", "{\\k28}Hello, {\\k102}and welcome.")
    with pytest.raises(SubtitulosError, match="etiqueta"):
        valida_srt(_escribe(tmp_path, con_karaoke))


def test_un_srt_vacio_se_rechaza(tmp_path):
    with pytest.raises(SubtitulosError, match="ni un bloque"):
        valida_srt(_escribe(tmp_path, "\n\n"))


def test_el_BOM_no_estorba(tmp_path):
    """El `.ass` se escribe con BOM a propósito (libass), así que el validador tiene que tolerarlo aquí."""
    ruta = tmp_path / "con-bom.srt"
    ruta.write_text(BUENO, encoding="utf-8-sig")
    assert valida_srt(ruta)["bloques"] == 2


def test_la_subida_ya_no_avisa_de_un_ass_que_el_motor_de_escena_no_escribe(tmp_path):
    """El `.ass` era el karaoke quemado del motor de láminas, retirado en F6.7: un run de escena no lo tiene.

    Avisar de él contradecía al LEEME, que da el `.srt` como el único fichero de subtítulos del run (R1 de
    `progress/review_F6.7.md`).
    """
    fuente = Path("lib/youtube_client.py").read_text(encoding="utf-8")
    assert "subtítulos .srt" in fuente, "el pendiente_a_mano ya no nombra el .srt"
    assert "subtitulos.ass" not in fuente and "cual_NO" not in fuente


# --- los signos de apertura invertidos NO se pintan en un vídeo que no narra en español ---------
#
# La convención española «¡…!» se eligió el 10-09 porque entona más, y esa decisión es sobre cómo
# SUENA. Un agente revisor cazó el efecto colateral el mismo día: el signo llegaba al subtítulo quemado
# y al `.srt` de un vídeo en inglés. Medido antes del arreglo: 18 láminas de los tres episodios de la
# semana W37 lo llevaban. Es el mismo defecto que la fila 115 arregló para `<groan>`, con otra marca.


def test_el_signo_de_apertura_no_llega_al_subtitulo_en_ingles():
    """EL CONTROL NEGATIVO: `sin_etiquetas` sola deja el «¡», y por eso no basta para pintar."""
    from lib.subtitulos import texto_para_pintar
    from lib.voice_client import sin_etiquetas

    guion = "<groan> ¡Look at it! It is not what the word suggests..."

    assert "¡" in sin_etiquetas(guion), "si esto falla, el control negativo ya no prueba nada"
    pintado = texto_para_pintar(guion, idioma="en")
    assert "¡" not in pintado
    assert pintado == "Look at it! It is not what the word suggests..."


def test_en_un_canal_que_narra_en_espanol_el_signo_se_conserva():
    """No es una lista de canales: lo decide el idioma declarado del canal."""
    from lib.subtitulos import texto_para_pintar

    assert texto_para_pintar("¡Mira esto! ¿Lo ves?", idioma="es") == "¡Mira esto! ¿Lo ves?"
    assert texto_para_pintar("¡Mira esto! ¿Lo ves?", idioma="es-ES") == "¡Mira esto! ¿Lo ves?"


def test_el_signo_de_interrogacion_de_apertura_tambien_se_quita():
    """El código es simétrico y la prueba tiene que fijar las dos mitades, no una."""
    from lib.subtitulos import texto_para_pintar

    assert texto_para_pintar("¿Punishment? ¿Or myth?", idioma="en") == "Punishment? Or myth?"


def test_el_cierre_de_exclamacion_no_se_toca_nunca():
    """El «!» final es correcto en inglés: quitarlo sería quitar la exclamación, no la marca."""
    from lib.subtitulos import texto_para_pintar

    pintado = texto_para_pintar("¡Biscuit! ¡No! ¡Sit!", idioma="en")
    assert pintado == "Biscuit! No! Sit!"
    assert pintado.count("!") == 3
