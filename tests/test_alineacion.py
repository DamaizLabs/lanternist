"""El emparejador vive en `lib/alineacion.py` y todos lo importan de ahí (F6.2b).

Criterio de F6.2b: «limpia_voz e integridad_narracion importan de lib/alineacion.py y su suite sigue en verde».
La suite de cada uno sigue en su fichero (`test_limpia_voz.py`, `test_integridad_narracion.py`, `test_subtitulos.py`)
sin tocar una línea; lo que se prueba aquí es de DÓNDE importan, con el AST, y que el karaoke quemado —que se
retira en F6.7— se lleva su parte y no esta.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from lib import alineacion, subtitulos

RAIZ = Path(__file__).resolve().parent.parent


def _importa(fuente: str) -> dict[str, set[str]]:
    """{módulo: nombres} de cada `from X import …` del código, incluidos los que van dentro de una función."""
    salida: dict[str, set[str]] = {}
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, ast.ImportFrom) and nodo.module:
            salida.setdefault(nodo.module, set()).update(a.name for a in nodo.names)
        elif isinstance(nodo, ast.Import):
            for a in nodo.names:
                salida.setdefault(a.name, set())
    return salida


def _de_subtitulos(importa: dict[str, set[str]]) -> bool:
    return "lib.subtitulos" in importa or "subtitulos" in importa.get("lib", set())


@pytest.mark.parametrize(
    ("fichero", "nombres"),
    [
        ("lib/limpia_voz.py", {"_normaliza", "_empareja_indices", "huecos_sin_guion", "marcas_sobrantes"}),
        ("lib/integridad_narracion.py", {"_normaliza"}),
        ("lib/escena/linea_tiempo.py", {"alineacion"}),
    ],
)
def test_importan_el_emparejador_de_alineacion_y_no_de_subtitulos(fichero, nombres):
    importa = _importa((RAIZ / fichero).read_text(encoding="utf-8"))
    assert nombres <= importa.get("lib.alineacion", set()) | importa.get("lib", set())
    assert not _de_subtitulos(importa), f"{fichero} sigue importando de lib/subtitulos.py"


def test_control_la_comprobacion_ve_la_importacion_vieja():
    """Las líneas de antes de F6.2b, tal cual: la prueba de arriba tiene que verlas."""
    for vieja in (
        "def f():\n    from lib.subtitulos import _normaliza\n",
        "from lib.subtitulos import huecos_sin_guion, marcas_sobrantes\n",
        "from lib import subtitulos\n",
    ):
        assert _de_subtitulos(_importa(vieja)), vieja


def test_alineacion_no_depende_del_karaoke_quemado():
    """F6.7 borra la parte ASS de lib/subtitulos.py: lo que se queda no puede necesitarla."""
    assert not _de_subtitulos(_importa((RAIZ / "lib" / "alineacion.py").read_text(encoding="utf-8")))


def test_la_parte_ass_y_el_quemado_salieron_de_subtitulos_y_el_emparejador_es_solo_de_alineacion():
    """F6.7: lo que se llevó el karaoke quemado ya no está, y `lib/subtitulos.py` no reexporta el emparejador.

    Hasta F6.7 reexportaba `_normaliza`, `huecos_sin_guion`, `marcas_sobrantes`… para sus usuarios de entonces; hoy
    todos importan de `lib/alineacion.py` (la prueba de arriba), así que una segunda puerta sería otra fuente.
    """
    for retirado in ("cabecera_ass", "linea_ass", "verifica_eventos", "quema", "quema_conservando_el_montaje", "aplica",
                     "agrupa", "caracteres_por_linea", "_offsets_por_lamina", "empareja", "marca_hablantes",
                     "_normaliza", "huecos_sin_guion", "marcas_sobrantes", "reparte_tiempos_colapsados"):  # fmt: skip
        assert not hasattr(subtitulos, retirado), f"lib/subtitulos.py sigue teniendo {retirado}"
    # Control: lo que se queda sigue ahí, y el emparejador sigue en su sitio.
    for vivo in ("ajustes", "personajes", "recorta_solapes", "estira_lineas_cortas", "escribe_srt", "valida_srt"):
        assert callable(getattr(subtitulos, vivo))
    assert callable(alineacion.empareja) and callable(alineacion.reparte_tiempos_colapsados)


def test_el_emparejador_lanza_su_propio_error():
    with pytest.raises(alineacion.AlineacionError, match="ni una marca"):
        alineacion.empareja(["hola"], [])
    with pytest.raises(alineacion.AlineacionError, match="se sale del guion"):
        alineacion.marca_hablantes([{"palabra": "a"}], [{"desde": 0, "hasta": 3, "personaje": "X"}])


def test_el_texto_que_se_pinta_pide_su_idioma():
    """En `lib/alineacion.py` el idioma no tiene defecto; en `lib/subtitulos.py`, el del canal activo, como antes."""
    assert alineacion.texto_para_pintar("¡Hola! <sigh> ¿Ves?", "en") == "Hola! Ves?"
    assert alineacion.texto_para_pintar("¡Hola! <sigh> ¿Ves?", "es") == "¡Hola! ¿Ves?"
    with pytest.raises(TypeError):
        alineacion.texto_para_pintar("hola")  # type: ignore[call-arg]
