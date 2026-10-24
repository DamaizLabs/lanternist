"""La guarda de las etiquetas emocionales del guion.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_voz_etiquetas.py

**De dónde sale.** El 08-09 se midieron las etiquetas de Orpheus sobre el modelo cuantizado con seis
semillas por variante y, como control negativo, una etiqueta inventada: `<blorp>`. El modelo **no la
ignoró: la leyó en voz alta** en 6 de 6 pasadas — «Blurp!», «Boar!», «Blahp!». Ese es el modo de
fallo que estas pruebas protegen, y es peor que el evidente: el audio suena bien, dura lo que toca y
**pasa el recorte por transcripción**, porque la palabra intrusa va dentro del texto pedido y no
detrás. Llegaría al vídeo publicado sin que nada la cazase (addendum fila 115).

**Qué protegen y qué no.** No comprueban que una etiqueta suene bien: eso se mide y lo escucha el usuario.
Comprueban la frontera — que ninguna marca sin declarar llegue al motor, y que la lista sea del canal
y no tenga defecto (F4.9).
"""

import json

import pytest
from canales_de_prueba import RECETA_DOCUMENTAL, recetas_a_comprobar

from lib import config, voice_client
from lib.voice_client import VoiceError, revisa_etiquetas_emocionales

# Las tres del 08-09 más las dos de alegría medidas el 09-09 (receta → medidas_en_Q8_0_el_2026_09_09_alegria).
PERMITIDAS = ["gasp", "sigh", "groan", "laugh", "chuckle"]
FRASE = "You already know what this object looks like. An upright iron case, a hinged front."


def test_una_etiqueta_declarada_pasa_y_se_devuelve():
    assert revisa_etiquetas_emocionales(
        f"{FRASE} <groan> But nobody was ever punished inside one.", PERMITIDAS, "x"
    ) == ["groan"]


def test_un_texto_sin_etiquetas_no_devuelve_ninguna():
    assert revisa_etiquetas_emocionales(FRASE, PERMITIDAS, "x") == []


def test_la_etiqueta_INVENTADA_para_el_run():
    """El control negativo de la medición, convertido en prueba: `<blorp>` se pronunciaría."""
    with pytest.raises(VoiceError, match="blorp"):
        revisa_etiquetas_emocionales(f"{FRASE} <blorp> But nobody was.", PERMITIDAS, "lamina 3")


def test_el_mensaje_dice_de_donde_viene_el_texto():
    """Sin saber QUÉ lámina lo trae, arreglar el guion es buscar a ciegas en 33 pantallas."""
    with pytest.raises(VoiceError, match="lamina 7"):
        revisa_etiquetas_emocionales(f"{FRASE} <whisper>", PERMITIDAS, "lamina 7")


def test_una_errata_de_una_letra_tambien_para():
    """Es el caso realista: nadie escribe `<blorp>`, se escribe `<grone>`."""
    with pytest.raises(VoiceError, match="grone"):
        revisa_etiquetas_emocionales(f"{FRASE} <grone> But nobody was.", PERMITIDAS, "x")


def test_las_mayusculas_NO_valen_por_parecerse():
    """`<GASP>` no son los mismos tokens que `<gasp>`: si el motor no la convierte, la dice."""
    with pytest.raises(VoiceError, match="GASP"):
        revisa_etiquetas_emocionales(f"{FRASE} <GASP>", PERMITIDAS, "x")


def test_con_lista_vacia_cualquier_etiqueta_para():
    """Es el caso de los canales que no escriben etiquetas: la lista vacía es una guarda, no un hueco."""
    with pytest.raises(VoiceError, match="groan"):
        revisa_etiquetas_emocionales(f"{FRASE} <groan>", [], "x")


def test_NO_salta_con_prosa_que_solo_lleva_signos_de_comparacion():
    """Control negativo de la guarda: si saltara con texto normal, el canal la desactivaría."""
    for texto in (
        "The case is smaller than a door: a < b, and the ratio was 3 > 2.",
        "He wrote 1 < 2 on the margin.",
        "Nothing here is a tag <",
    ):
        assert revisa_etiquetas_emocionales(texto, [], "x") == []


def test_todas_las_recetas_declaran_la_lista():
    """F4.9: la clave es obligatoria y sin defecto, también en los canales que no usan etiquetas.

    Recorre las recetas de `canales/` y las dos de prueba, para que la guarda no quede vacía mientras el canal
    de ejemplo no tenga voz.
    """
    recetas = recetas_a_comprobar()
    assert recetas, "no se encontró ninguna receta de voz"
    for ruta in recetas:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        bloque = datos.get("etiquetas_emocionales")
        assert bloque is not None, f"{ruta.name} no declara 'etiquetas_emocionales'"
        assert isinstance(bloque.get("permitidas"), list), f"{ruta.name}: 'permitidas' no es una lista"
        for etiqueta in bloque["permitidas"]:
            assert "<" not in etiqueta and ">" not in etiqueta, f"{ruta.name}: {etiqueta!r} lleva ángulos"


def test_load_recipe_para_si_la_receta_no_declara_la_lista(tmp_path, monkeypatch):
    """Un defecto aquí sería la decisión de otro canal heredada en silencio (F4.9)."""
    base = json.loads(RECETA_DOCUMENTAL.read_text(encoding="utf-8"))
    base.pop("etiquetas_emocionales")
    ruta = tmp_path / "voz-sin-etiquetas.json"
    ruta.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(voice_client, "VOICE_RECIPE_PATH", ruta)
    with pytest.raises(VoiceError, match="etiquetas_emocionales"):
        voice_client.load_recipe()


@pytest.mark.parametrize("mala", ["<groan>", "groan>", "<groan", "gro an", "<>", " "])
def test_load_recipe_rechaza_una_etiqueta_mal_escrita(tmp_path, monkeypatch, mala):
    """Todas son entradas MUERTAS: la regex nunca produce nombres con ángulos ni espacios, así que
    nunca casarían y además saldrían deformes en el mensaje («admitidas: <groan>>»)."""
    base = json.loads(RECETA_DOCUMENTAL.read_text(encoding="utf-8"))
    base["etiquetas_emocionales"] = {"permitidas": [mala]}
    ruta = tmp_path / "voz-mal-escrita.json"
    ruta.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(voice_client, "VOICE_RECIPE_PATH", ruta)
    with pytest.raises(VoiceError, match="SIN ángulos"):
        voice_client.load_recipe()


def test_el_texto_de_la_referencia_no_admite_NINGUNA_etiqueta():
    """El segundo camino a la síntesis (`scripts/referencia_voz.py`), que no pasa por la guarda.

    Ahí la regla es más dura que en el guion y a propósito: una etiqueta en el clip de referencia se
    pronunciaría —Kokoro no las convierte en sonido— y ese clip es justo lo que Orpheus clona, con la
    fila 112 encima («el motor continúa la referencia»). No tiene ningún uso legítimo.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("refvoz", config.BASE_DIR / "scripts/referencia_voz.py")
    refvoz = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(refvoz)
    vale, _ = refvoz.CAMPOS["texto"]
    largo = " ".join(["word"] * 20)
    assert vale(largo), "un texto normal de 20 palabras tiene que valer"
    assert not vale(f"{largo} <groan>")
    assert not vale(f"{largo} <cualquier-cosa>")
    # y las recetas siguen pasando: si no, el clip de referencia no se podría regenerar
    for ruta in recetas_a_comprobar():
        bloque = json.loads(ruta.read_text(encoding="utf-8")).get("referencia_a_generar")
        if bloque and "texto" in bloque:
            assert vale(bloque["texto"]), f"{ruta.name}: su texto de referencia dejaría de valer"
