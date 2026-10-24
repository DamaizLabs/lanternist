"""Lo que `verifica_guion.py` exige NO es lo mismo en todos los canales.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_verifica_guion_por_canal.py

**De dónde sale.** El 12-09 subí `fuentes` a clave obligatoria del guion, junto a `thumbnail_lamina`,
al meter la composición de la descripción dentro del pipeline (addendum fila 154). Eso rompía el canal
de ficción sin motivo, y se cazó el 13-09: «las fuentes no son obligatorias en todos los canales».
Un canal de ficción didáctica declara `nicho.sin_fuentes_verificadas` y no tiene citas que comprobar,
así que ni escribe `<<BIBLIOGRAFIA>>` ni necesita el campo.

La regla que queda, y es la que estas pruebas fijan: **`fuentes` se exige donde hay bibliografía que
componer, y eso lo dice la propia descripción del guion**, no el canal ni una lista en el código.

**Contra qué canales se mide desde OC1.1.** Contra dos canales inventados que deciden distinto
(`tests/canales_de_prueba.py`): el documental, con fichas, guardián de sangre, lista negra de adjetivos
y capítulos, y el de ficción, sin nada de eso y con otro ritmo. Tienen la forma de los dos primeros
canales del estudio, sin sus datos: así estas pruebas no se rompen cuando un canal real produce.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from canales_de_prueba import escribe_canal, perfil_documental, perfil_ficcion

from lib import config

VERIFICADOR = config.BASE_DIR / "scripts" / "verifica_guion.py"

BASE = {
    "title": "Un título de prueba que no dice nada",
    "tags": ["a", "b"],
    "thumbnail_lamina": 1,
    "thumbnail_text": "TRES PALABRAS AQUI",
    "slides": [{"slide_number": 1, "narration": "x " * 70, "image_prompt": "a plain wall"}],
}


@pytest.fixture(scope="module")
def canales(tmp_path_factory) -> dict[str, Path]:
    """Los dos canales inventados, escritos una vez por módulo: {"documental": carpeta, "ficcion": carpeta}."""
    raiz = tmp_path_factory.mktemp("canales")
    return {
        "documental": escribe_canal(raiz, "documental", perfil_documental()),
        "ficcion": escribe_canal(raiz, "ficcion", perfil_ficcion()),
    }


@pytest.fixture
def documental(canales) -> Path:
    return canales["documental"]


@pytest.fixture
def ficcion(canales) -> Path:
    return canales["ficcion"]


def _verifica(tmp_path: Path, datos: dict, canal: Path | None = None, entorno: dict | None = None) -> str:
    """Corre el verificador REAL, en un proceso, con el canal que se le diga.

    **En un proceso y no llamando a `verifica()`**: el canal activo se resuelve al importar
    `lib.config`, así que cambiarlo dentro del mismo intérprete mediría otra cosa. Esta es la
    condición del caso de uso — un agente lanza el comando con el `CANAL_ACTIVO` de su canal. Sin
    `canal`, mide contra el canal de ejemplo, que es el que fija `tests/conftest.py`.
    """
    ruta = tmp_path / "slides.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    env = {**os.environ}
    if canal:
        env["CANAL_ACTIVO"] = str(canal)
    env.update(entorno or {})
    r = subprocess.run(
        [sys.executable, str(VERIFICADOR), str(ruta)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=config.BASE_DIR,
        env=env,
    )
    return (r.stdout or "") + (r.stderr or "")


_MODULO = None


def _verificador():
    """El módulo del verificador, para probar la DERIVACIÓN sin montar un proceso por caso."""
    global _MODULO
    if _MODULO is None:
        spec = importlib.util.spec_from_file_location("verifica_guion", VERIFICADOR)
        _MODULO = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MODULO)
    return _MODULO


def test_los_canales_de_prueba_se_leen_de_verdad(tmp_path, documental, ficcion):
    """Control de todo el fichero: el verificador mide contra el canal que se le pasa, no contra otro.

    Si la ruta absoluta dejara de llegar a `lib.config`, los dos medirían contra el canal de ejemplo y las
    comparaciones de abajo pasarían o fallarían por casualidad.
    """
    for canal in (documental, ficcion):
        assert f"Midiendo contra el perfil de: {canal}" in _verifica(tmp_path, BASE, canal=canal)


def test_sin_bibliografia_NO_se_exigen_fuentes(tmp_path):
    """El caso del canal de ficción: sin citas y sin el marcador."""
    salida = _verifica(tmp_path, {**BASE, "description": "Una historia para aprender inglés."})
    assert "falta la clave obligatoria `fuentes`" not in salida
    assert "no declara `fuentes`" not in salida


def test_CON_bibliografia_y_SIN_fuentes_falla_y_dice_por_que(tmp_path):
    """El caso del canal documental: si pides bibliografía, alguien tiene que decir de qué fichas sale."""
    salida = _verifica(tmp_path, {**BASE, "description": "Un episodio.\n\n<<BIBLIOGRAFIA>>"})
    assert "no declara `fuentes`" in salida
    assert "no se deduce" in salida


def test_CONTROL_con_bibliografia_y_CON_fuentes_ya_no_se_queja(tmp_path):
    """Sin esto, la prueba de arriba no distingue «la guarda funciona» de «siempre falla»."""
    salida = _verifica(
        tmp_path,
        {**BASE, "description": "Un episodio.\n\n<<BIBLIOGRAFIA>>", "fuentes": ["una-ficha"]},
    )
    assert "no declara `fuentes`" not in salida


@pytest.mark.parametrize("ficha", ["no-existe-esta-ficha", "inventada"])
def test_una_ficha_que_no_esta_en_disco_se_caza_en_el_gate_1(tmp_path, ficha):
    """Un id mal escrito publicaría un bloque de citas vacío en un vídeo ya montado."""
    salida = _verifica(tmp_path, {**BASE, "description": "Un episodio.\n\n<<BIBLIOGRAFIA>>", "fuentes": [ficha]})
    assert ficha in salida and "no existe" in salida


# --- bienvenida y despedida: regla del ESTUDIO desde el 13-09 ------------------------------------


def _bienvenida_del_canal(canal: Path) -> str:
    """La plantilla del perfil del canal, con sus marcadores rellenados como haría el guionista.

    Se lee del perfil en vez de copiarla aquí: una copia a mano se queda corta —la primera versión de
    esta prueba se dejó el final de la bienvenida— y entonces el test mide otra cosa.
    """
    perfil = json.loads((canal / "perfil.json").read_text(encoding="utf-8"))
    return re.sub(r"\{[a-z_]+\}", "un título cualquiera", perfil["formato"]["bienvenida"])


def _con_cierre(narracion_1: str) -> dict:
    """Un guion mínimo que sí cumple, para variar una sola cosa cada vez."""
    return {
        **BASE,
        "description": "Un episodio.",
        "slides": [
            {"slide_number": 1, "narration": narracion_1 + " " + "x " * 60, "image_prompt": "a plain wall"},
            {"slide_number": 2, "tipo": "cierre", "narration": "y " * 70, "image_prompt": "a plain wall"},
        ],
    }


def test_sin_lamina_de_cierre_falla(tmp_path, documental):
    """El 09-09: «ahora el vídeo queda muy seco». Hasta el 13-09 esto pasaba en verde."""
    guion = _con_cierre(_bienvenida_del_canal(documental))
    guion["slides"][1].pop("tipo")
    assert "sin lámina de despedida" in _verifica(tmp_path, guion, canal=documental)


def test_sin_la_bienvenida_del_canal_falla(tmp_path, documental):
    salida = _verifica(tmp_path, _con_cierre("Today we look at a thing."), canal=documental)
    assert "no abre con la bienvenida" in salida


def test_CONTROL_con_las_dos_no_se_queja(tmp_path, documental):
    salida = _verifica(tmp_path, _con_cierre(_bienvenida_del_canal(documental)), canal=documental)
    assert "sin lámina de despedida" not in salida
    assert "no abre con la bienvenida" not in salida


def test_los_signos_de_entonacion_NO_cuentan_como_diferencia(tmp_path, documental):
    """El guion mete `¡` y `¿` a propósito para que Orpheus entone (10-09).

    Un episodio escribió «¡the museum…» y la primera versión de esta guarda lo daba por incumplido:
    un falso positivo que habría mandado a reescribir un guion correcto.
    """
    con_signos = _bienvenida_del_canal(documental).replace("the workshop", "¡the workshop")
    assert "¡the workshop" in con_signos, "la bienvenida del canal de prueba tiene que llevar el trozo que se cambia"
    assert "no abre con la bienvenida" not in _verifica(tmp_path, _con_cierre(con_signos), canal=documental)


# --- F5.6: siete reglas que eran de un canal y ahora son de cada canal ----------------------------
#
# **Cada regla se prueba DOS veces y en los DOS canales**, porque «el de ficción pasa» no distingue
# entre haber arreglado la capa y haber apagado la regla. El par es siempre el mismo: el canal que SÍ
# tiene la regla sigue fallando (control negativo), y el que no la tiene deja de fallar.
#
# Corren el binario con `CANAL_ACTIVO` puesto, que es la condición del caso de uso: un guion de un
# canal lo verifica un agente con ese canal activo, no con el del estudio por defecto.


def test_CONTROL_NEGATIVO_un_prompt_con_red_sigue_fallando_en_el_documental(tmp_path, documental):
    """La regla no se ha apagado: donde hay guardián de sangre, `red` sigue deteniendo el guion.

    Es el control que pide el criterio 9 de F5.6. Sin él, la prueba de abajo solo demuestra que la
    comprobación ya no se hace en ningún sitio.
    """
    guion = {**BASE, "description": "Un episodio.", "slides": [{**BASE["slides"][0], "image_prompt": "a red kite"}]}
    assert "nombra «red»" in _verifica(tmp_path, guion, canal=documental)


def test_el_mismo_prompt_con_red_NO_falla_en_el_de_ficcion(tmp_path, ficcion):
    """El de ficción declara `guardianes_de_color: []` a propósito: «red» en un prompt suyo no es un fallo."""
    guion = {**BASE, "description": "Un episodio.", "slides": [{**BASE["slides"][0], "image_prompt": "a red kite"}]}
    assert "nombra «red»" not in _verifica(tmp_path, guion, canal=ficcion)


def test_CONTROL_NEGATIVO_un_adjetivo_de_materialidad_sigue_fallando(tmp_path, documental):
    """La lista negra bajó al perfil, no desapareció: `weathered` sigue rompiendo el acabado."""
    guion = {
        **BASE,
        "description": "Un episodio.",
        "slides": [{**BASE["slides"][0], "image_prompt": "a weathered wall"}],
    }
    assert "de la lista negra de materialidad" in _verifica(tmp_path, guion, canal=documental)


def test_sin_el_adjetivo_la_misma_prueba_pasa(tmp_path, documental):
    """Contrapeso del de arriba: la prueba sabe distinguir, no siempre falla."""
    guion = {**BASE, "description": "Un episodio.", "slides": [{**BASE["slides"][0], "image_prompt": "a plain wall"}]}
    assert "de la lista negra de materialidad" not in _verifica(tmp_path, guion, canal=documental)


def test_CONTROL_NEGATIVO_los_capitulos_siguen_siendo_obligatorios_en_el_documental(tmp_path, documental):
    guion = {**BASE, "description": "Un episodio.\n\n<<CAPITULOS>>\n<<BIBLIOGRAFIA>>", "fuentes": []}
    assert "capítulos: YouTube necesita al menos 3" in _verifica(tmp_path, guion, canal=documental)


def test_lo_que_se_exige_de_capitulos_sale_del_perfil_del_canal(tmp_path, ficcion):
    """**Lo que se exige sale del perfil del canal**, y por eso la prueba lee el perfil en vez de repetir
    el valor: el día que un canal los apague, sigue valiendo."""
    lleva = json.loads((ficcion / "perfil.json").read_text(encoding="utf-8"))["formato"]["capitulos"]
    guion = {**BASE, "description": "Un episodio."}
    salida = _verifica(tmp_path, guion, canal=ficcion)
    assert ("capítulos: YouTube necesita al menos 3" in salida) is bool(lleva)


def test_un_guion_con_capitulos_en_un_canal_que_no_los_lleva_se_caza():
    """La otra punta de la regla, medida sobre el CONTRATO: el perfil entra, el contrato sale, y
    `verifica()` actúa sobre eso."""
    perfil = perfil_ficcion()
    perfil["formato"]["capitulos"] = False
    assert _verificador().contrato_del_canal(perfil).lleva_capitulos is False


@pytest.mark.parametrize("marcador", ["<<CAPITULOS>>", "<<BIBLIOGRAFIA>>"])
def test_CONTROL_NEGATIVO_los_dos_marcadores_se_siguen_exigiendo_en_el_documental(tmp_path, documental, marcador):
    salida = _verifica(tmp_path, {**BASE, "description": "Un episodio sin marcadores."}, canal=documental)
    assert f"la descripción no trae el marcador {marcador}" in salida


@pytest.mark.parametrize("marcador", ["<<CAPITULOS>>", "<<BIBLIOGRAFIA>>"])
def test_al_de_ficcion_se_le_exige_el_marcador_QUE_LE_TOCA_y_solo_ese(tmp_path, ficcion, marcador):
    """Lleva capítulos pero no fichas: un marcador sí y el otro no.

    Es el caso que mejor prueba F5.6: los dos marcadores se deciden por separado y con claves
    distintas del mismo perfil.
    """
    perfil = json.loads((ficcion / "perfil.json").read_text(encoding="utf-8"))
    toca = {"<<CAPITULOS>>": bool(perfil["formato"]["capitulos"]), "<<BIBLIOGRAFIA>>": False}[marcador]
    salida = _verifica(tmp_path, {**BASE, "description": "Un episodio sin marcadores."}, canal=ficcion)
    assert (f"la descripción no trae el marcador {marcador}" in salida) is toca


def test_CONTROL_NEGATIVO_las_formulas_de_respaldo_siguen_prohibidas_donde_hay_fichas(tmp_path, documental):
    """Un canal con fichas tiene sus citas en `solo_citas_verificadas`: nadie ha leído las obras (gate 1 §A)."""
    narracion = "it is documented that the piece existed. " + "x " * 60
    guion = {**BASE, "description": "Un episodio.", "slides": [{**BASE["slides"][0], "narration": narracion}]}
    assert "`solo_citas_verificadas`" in _verifica(tmp_path, guion, canal=documental)


def test_un_canal_sin_fichas_no_tiene_citas_que_respaldar(tmp_path, ficcion):
    """El de ficción declara `nicho.sin_fuentes_verificadas`: no hay nada que citar."""
    narracion = "it is documented that the cake was white. " + "x " * 120
    guion = {**BASE, "description": "Un episodio.", "slides": [{**BASE["slides"][0], "narration": narracion}]}
    assert "`solo_citas_verificadas`" not in _verifica(tmp_path, guion, canal=ficcion)


def test_los_delatores_de_castellano_no_se_aplican_a_una_narracion_en_castellano(tmp_path, documental):
    """El detector busca palabras ESPAÑOLAS: en un canal que narre en español serían todas suyas.

    Se fuerza con `IDIOMA_NARRACION`, la variable que el propio perfil declara como su anulación,
    porque no hay ningún canal en español con el que medirlo.
    """
    narracion = "la pieza que se usaba para castigar, como cualquier otra de la sala. " + "x " * 55
    guion = {**BASE, "description": "Un episodio.", "slides": [{**BASE["slides"][0], "narration": narracion}]}
    assert "posible castellano" in _verifica(tmp_path, guion, canal=documental), "CONTROL: en inglés sí avisa"
    en_castellano = _verifica(tmp_path, guion, canal=documental, entorno={"IDIOMA_NARRACION": "es"})
    assert "posible castellano" not in en_castellano


def test_las_bandas_de_palabras_son_las_del_canal_y_no_las_del_otro(tmp_path, documental, ficcion):
    """70 palabras por lámina están DENTRO en el documental y FUERA en el de ficción. Misma lámina, mismo comando.

    Es lo que el verificador no distinguía antes de F5.6, y la propiedad no depende de los números
    concretos: **no se fija el texto de la banda del de ficción** porque esa cifra se re-mide cada vez
    que un canal cambia de ritmo o de formato, y re-medirla es lo correcto.
    """
    guion = {**BASE, "description": "Un episodio."}
    assert "fuera del límite duro" not in _verifica(tmp_path, guion, canal=documental)
    assert "fuera del límite duro" in _verifica(tmp_path, guion, canal=ficcion)


# --- la derivación, sin montar un proceso por caso ------------------------------------------------


def test_el_documental_deriva_exactamente_las_bandas_de_su_formato():
    """La regresión de F5.6 en una línea: 63-85 y 40-103, los mismos números que había cableados.

    Salen de 20 min ÷ 40 láminas = 30 s por lámina × 2,44 palabras/s, y las fracciones del estudio.
    Si esta prueba se pone en rojo, la fórmula de las bandas ha cambiado.
    """
    contrato = _verificador().contrato_del_canal(perfil_documental())
    assert contrato.carencias == []
    assert contrato.palabras_por_segundo == 2.44
    assert contrato.banda_objetivo == (63, 85)
    assert contrato.banda_dura == (40, 103)


def test_el_de_ficcion_deriva_las_suyas_desde_SU_formato_y_SU_ritmo():
    """Las bandas del de ficción salen de SU duración, SUS láminas y SU ritmo — los tres de su perfil.

    **No se copia el número**, se deriva de las mismas tres claves: lo que se comprueba es la
    propiedad, no la foto.
    """
    verificador = _verificador()
    perfil = perfil_ficcion()
    contrato = verificador.contrato_del_canal(perfil)
    assert contrato.carencias == []

    minutos = perfil["formato"]["duracion_objetivo_min"]
    laminas = perfil["formato"]["laminas_por_video_estimadas"]
    ritmo = perfil["voz"]["palabras_por_segundo"]
    assert contrato.palabras_por_segundo == ritmo
    centro = (sum(minutos) / 2 * 60 / laminas) * ritmo
    for banda, fraccion in (
        (contrato.banda_objetivo, verificador.FRACCION_OBJETIVO),
        (contrato.banda_dura, verificador.FRACCION_DURA),
    ):
        assert banda == (round(centro * fraccion[0]), round(centro * fraccion[1]))

    # Y lo que de verdad importaba de F5.6: que NO sean las del documental.
    assert contrato.banda_dura != _verificador().contrato_del_canal(perfil_documental()).banda_dura
    assert contrato.colores_prohibidos == ()
    assert contrato.lleva_capitulos is perfil["formato"]["capitulos"]
    assert contrato.lleva_fichas is False


def test_el_documental_sigue_teniendo_su_guardian_y_sus_fichas():
    """Contrapeso del de arriba: que los valores del de ficción no salgan de haber vaciado la lectura."""
    contrato = _verificador().contrato_del_canal(perfil_documental())
    assert "red" in contrato.colores_prohibidos and "mahogany" in contrato.colores_prohibidos
    assert "weathered" in contrato.adjetivos_prohibidos
    assert contrato.lleva_capitulos is True
    assert contrato.lleva_fichas is True


@pytest.mark.parametrize(
    "ruta, trozo_del_mensaje",
    [
        ("voz.palabras_por_segundo", "palabras habladas ÷ segundos de audio"),
        ("formato.duracion_objetivo_min", "la banda que firmó su gate 0"),
        ("formato.laminas_por_video_estimadas", "cuántas láminas lleva un vídeo"),
        ("formato.capitulos", "si los vídeos de este canal llevan índice"),
        ("imagen.adjetivos_prohibidos", "la lista negra de materialidad"),
    ],
)
def test_lo_que_un_canal_no_declara_NO_se_hereda_del_otro(ruta, trozo_del_mensaje):
    """F4.9 en el verificador: sin defecto, y el mensaje dice qué escribir y dónde.

    Se quita UNA clave cada vez del perfil documental —variando las cinco dimensiones, no solo la
    cómoda— y se comprueba que el verificador lo dice en vez de rellenarlo.
    """
    perfil = perfil_documental()
    rama, hoja = ruta.split(".")
    perfil[rama].pop(hoja)
    contrato = _verificador().contrato_del_canal(perfil)
    carencias = "\n".join(contrato.carencias)
    assert f"no declara `{ruta}`" in carencias
    assert trozo_del_mensaje in carencias


def test_sin_ritmo_NO_se_inventa_ninguna_banda():
    """Lo importante no es solo que avise: es que la regla que dependía del valor NO se evalúe.

    Si el verificador avisara y además derivara la banda con el ritmo de otro canal, el canal nuevo
    seguiría juzgado con la vara del viejo — que es el defecto entero de F5.6.
    """
    perfil = perfil_ficcion()
    perfil["voz"].pop("palabras_por_segundo")
    contrato = _verificador().contrato_del_canal(perfil)
    assert contrato.banda_objetivo is None and contrato.banda_dura is None


def test_un_guardian_sin_sus_palabras_para_el_gate_en_vez_de_usar_las_de_otro():
    """Un canal con guardián de color tiene que decir qué palabras lo disparan."""
    perfil = perfil_documental()
    perfil["lineas_rojas"]["guardianes_de_color"][0].pop("palabras_del_prompt")
    contrato = _verificador().contrato_del_canal(perfil)
    assert any("palabras_del_prompt" in c for c in contrato.carencias)
    assert contrato.colores_prohibidos is None


def test_un_canal_que_no_dice_si_tiene_fichas_no_se_deduce_del_silencio():
    perfil = perfil_ficcion()
    perfil["nicho"].pop("sin_fuentes_verificadas")
    contrato = _verificador().contrato_del_canal(perfil)
    assert any("aparato de fuentes" in c for c in contrato.carencias)
    assert contrato.lleva_fichas is None


# --- el valor DEGENERADO, que es el hueco que dejó F5.6 (auditoría §6.2) --------------------------


@pytest.mark.parametrize(
    "rama, hoja, valor, trozo",
    [
        ("voz", "palabras_por_segundo", 0, "tiene que ser > 0"),
        ("voz", "palabras_por_segundo", -2, "tiene que ser > 0"),
        ("formato", "laminas_por_video_estimadas", 0, "tiene que ser > 0"),
        ("formato", "duracion_objetivo_min", [14], "hacen falta 2"),
    ],
)
def test_un_valor_degenerado_se_DICE_en_vez_de_apagar_la_regla(rama, hoja, valor, trozo):
    """Un `0` no es `None`, así que pasaba la guarda de F4.9 y apagaba la regla **sin decir nada**.

    Es distinto de la fuga de F5.6 —no se hereda la decisión de nadie— pero es peor de encontrar: el
    verificador daba **0 carencias** y el guion se quedaba sin banda y sin gate de duración. Con un
    `-2` llegaba a derivar bandas negativas, `(-102, -261)`, y las comparaba con ellas.

    La causa era doble: `_exige` solo rechazaba `None` y `""`, y las guardas de la derivación
    preguntan por verdad booleana, así que el `0` caía por el lado de «no evaluar». Lo caza ahora
    `_exige` con `positivo=` y `largo=`.
    """
    perfil = perfil_ficcion()
    perfil[rama][hoja] = valor
    contrato = _verificador().contrato_del_canal(perfil)
    carencias = "\n".join(contrato.carencias)
    assert f"`{rama}.{hoja}`" in carencias, "el valor degenerado tiene que DECIRSE"
    assert trozo in carencias
    assert contrato.banda_objetivo is None and contrato.banda_dura is None


def test_CONTROL_el_mismo_perfil_con_valores_buenos_no_se_queja():
    """Sin este control, la prueba de arriba pasaría aunque `_exige` rechazara cualquier cosa."""
    contrato = _verificador().contrato_del_canal(perfil_ficcion())
    assert contrato.carencias == []
    # Que HAYA banda y sea creciente, no cuál: el número es del perfil y se re-mide.
    assert contrato.banda_dura is not None
    assert 0 < contrato.banda_dura[0] < contrato.banda_dura[1]


def test_el_limite_de_palabras_de_la_miniatura_es_el_MISMO_que_el_del_pipeline():
    """Los dos tienen que coincidir por construcción: este gate existe para cazar antes lo que
    `lib/miniatura.py` suspendería después de la GPU. Copiado, nada impedía que se separaran."""
    from lib.miniatura import PALABRAS_MAXIMAS

    assert _verificador().MAX_PALABRAS_MINIATURA == PALABRAS_MAXIMAS
