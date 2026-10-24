"""Las guardas que nacieron del episodio 1 del 08-09, cuando se rechazó al verlo.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_produccion_guardas_08_09.py

**De dónde salen.** El episodio se montó con la voz de Orpheus y se oyó plano («parece
Kokoro»), sin cinemagraph («es la tercera vez») y con la música alta. Los tres defectos tenían
causa estructural, no de descuido, y cada prueba de aquí reproduce uno a propósito (el control
negativo del pre-flight) y comprueba que ahora se para:

1. **Un guion escrito para Kokoro** —sin etiquetas ni puntos suspensivos— ya no pasa el
   verificador cuando el motor es Orpheus, y una etiqueta sin declarar tampoco.
2. **Las etiquetas no llegan a los subtítulos** como palabras, ni cuentan como palabras.

La tercera guarda —el montaje se negaba si el run declaraba `kaggle` y ninguna lámina traía clip— y la
del bucle del cinemagraph pedido por nombre salieron con el motor de láminas en F6.7 (02-10-2026).
"""

import json
import os
import subprocess
import sys

import pytest
from canales_de_prueba import escribe_canal, perfil_documental

from lib import config
from lib.voice_client import sin_etiquetas
from scripts import verifica_guion

# --- 1. el guion tiene que estar escrito para el motor que entona -----------------------------
#
# Hasta OC1.1 estas pruebas aplanaban el guion real del episodio 1 de un canal del estudio, que no viaja con git: en
# un clon limpio se saltaban, y la guarda se quedaba sin probar. Ahora el guion plano se escribe aquí —cinco láminas
# de prosa sin etiquetas ni puntos suspensivos, que es exactamente lo que era aquel guion— y el verificador corre en
# su proceso contra el canal documental de prueba, cuya receta declara `groan` (`tests/canales_de_prueba.py`).
LAMINAS_PLANAS = [
    "The zip has two rows of small metal teeth. A slider joins them, one pair at a time, and the rows lock.",
    "The first patent is more than a hundred years old. Nobody wanted it. Tailors did not trust it.",
    "Then a boot maker tried it on a rubber boot. The teeth held in the rain and the mud.",
    "Soon it moved to jackets and to bags. The slider got smaller, and the teeth got lighter.",
    "Today almost every coat has one. It is so ordinary that nobody looks at it anymore.",
]


@pytest.fixture(scope="module")
def documental(tmp_path_factory):
    return escribe_canal(tmp_path_factory.mktemp("canales"), "documental", perfil_documental())


def _guion_base() -> dict:
    """Un guion plano: cinco láminas, 0 etiquetas y 0 puntos suspensivos, como el guion escrito para Kokoro."""
    return {
        "title": "The Zip",
        "description": "Un episodio.",
        "tags": ["a"],
        "thumbnail_lamina": 1,
        "thumbnail_text": "TRES PALABRAS AQUI",
        "slides": [
            {"slide_number": n, "narration": texto, "image_prompt": "a plain wall"}
            for n, texto in enumerate(LAMINAS_PLANAS, start=1)
        ],
    }


def _fallos(tmp_path, datos: dict, canal) -> str:
    """El verificador en su proceso, con el canal que se le pasa: devuelve su salida, donde van los fallos."""
    ruta = tmp_path / "slides.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(config.BASE_DIR / "scripts" / "verifica_guion.py"), str(ruta)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=config.BASE_DIR,
        env={**os.environ, "CANAL_ACTIVO": str(canal)},
    )
    return r.stdout + r.stderr


def test_un_guion_plano_falla_por_plano(tmp_path, documental):
    """El control negativo: un guion como el que se oyó como Kokoro."""
    assert "puntuación de escuela" in _fallos(tmp_path, _guion_base(), documental)


def test_con_puntos_suspensivos_o_una_etiqueta_declarada_ya_no_es_plano(tmp_path, documental):
    datos = _guion_base()
    datos["slides"][0]["narration"] = datos["slides"][0]["narration"].replace(". ", "... ", 1)
    assert "puntuación de escuela" not in _fallos(tmp_path, datos, documental)

    datos = _guion_base()
    datos["slides"][3]["narration"] += " <groan>"
    salida = _fallos(tmp_path, datos, documental)
    assert "puntuación de escuela" not in salida
    assert "groan" not in salida, "groan está declarada en la receta del canal documental de prueba"


def test_una_etiqueta_SIN_declarar_falla_y_dice_la_lamina(tmp_path, documental):
    """`<blorp>` se pronunciaría en el vídeo: es el hallazgo de la fila 115 hecho guarda."""
    datos = _guion_base()
    datos["slides"][4]["narration"] += " <blorp>"
    salida = _fallos(tmp_path, datos, documental)
    assert "blorp" in salida and "slide 5" in salida, salida[-1500:]


def test_las_etiquetas_no_cuentan_como_palabras():
    assert verifica_guion._palabras("one two <groan> three") == 3
    assert verifica_guion._palabras("<gasp> one") == 1


# --- 2. las etiquetas no llegan a la pantalla --------------------------------------------------


def test_sin_etiquetas_quita_la_marca_y_normaliza_espacios():
    assert sin_etiquetas("It was empty. <groan> Nobody was inside.") == "It was empty. Nobody was inside."
    assert sin_etiquetas("<gasp>Look.") == "Look."


def test_sin_etiquetas_NO_toca_la_prosa_con_signos_de_comparacion():
    """Control negativo: si quitara «a < b», rompería un guion normal."""
    texto = "The ratio was 3 > 2, and a < b held."
    assert sin_etiquetas(texto) == texto
