"""Cada herramienta del estudio, ejercitada con DOS canales distintos, debe dar resultados distintos.

**Qué cubre esto que el guardia de capas no cubre, y por qué hacían falta los dos.**
`tests/test_capas_fuera_de_lib.py` caza lo que alguien **escribe a mano**: un id de canal en código,
una cifra copiada en un brief, un comentario que contradice a su valor. No caza lo que el código
**deduce**, y esa era la forma de los dos peores defectos del 16-09-2026:

- `pipeline.py` construía el nombre de la variable de OAuth a partir del id de la carpeta
  (`YOUTUBE_REFRESH_TOKEN_` + el número del canal) en vez de leer `publicacion.refresh_token_env`. No
  hay ningún canal escrito ahí: hay una deducción, y acertaba en el primer canal **por coincidencia**.
- `scripts/verifica_guion.py` tomaba el canal de `CANAL_ACTIVO`, o sea del ambiente. Medía el guion
  de un canal con el perfil de otro y daba 24 fallos que no existían.

Los dos comparten síntoma: **el resultado no depende del canal que se le pide, sino de otra cosa**.
Eso solo se ve ejercitando la misma herramienta con dos canales cuyos perfiles difieren.

**Con qué canales, desde OC1.1.** Con dos canales «canario» inventados (`tests/canales_de_prueba.py`):
el repositorio solo trae el canal de ejemplo, y con uno no hay contraste. Difieren en cinco dimensiones
—láminas (40 frente a 10), banda de minutos, ritmo de voz (2,44 frente a 1,885), si llevan fichas y qué
variable guarda su token—, y cada una es una oportunidad de cazar a un módulo decidiendo por su cuenta.
Lo primero que se comprueba es que difieren.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from canales_de_prueba import escribe_canal, perfil_documental, perfil_ficcion

from lib import config

RAIZ = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
CANARIOS = ("documental", "ficcion")
CANAL_DE_EJEMPLO = "example"


@pytest.fixture(scope="module")
def raiz_de_canarios(tmp_path_factory) -> Path:
    """Una carpeta con los dos canales canario, cada uno con una ficha (si la lleva) y un calendario."""
    raiz = tmp_path_factory.mktemp("canales")
    perfiles = {"documental": perfil_documental(), "ficcion": perfil_ficcion()}
    for nombre, perfil in perfiles.items():
        lleva_fichas = not perfil["nicho"].get("sin_fuentes_verificadas")
        fichas = {"una-ficha.json": {"id": "una-ficha", "nombre_en": "One record"}} if lleva_fichas else {}
        carpeta = escribe_canal(raiz, nombre, perfil, fichas=fichas)
        episodio = {"numero": 1, "fecha_propuesta": "2026-10-12", "titulo": "A test episode", "gate1": "—"}
        if lleva_fichas:
            episodio["ficha"] = "una-ficha"
        calendario = {"semana_iso": "2026-W42", "desde": "2026-10-12", "hasta": "2026-10-18", "episodios": [episodio]}
        (carpeta / "calendario").mkdir()
        (carpeta / "calendario" / "2026-W42.json").write_text(json.dumps(calendario), encoding="utf-8")
    return raiz


def perfil_de(raiz: Path, canal: str) -> dict:
    return json.loads((raiz / canal / "perfil.json").read_text(encoding="utf-8"))


def test_los_dos_canales_canario_difieren():
    """Sin dos perfiles distintos, todo lo de abajo pasa sin comprobar nada.

    Es el control negativo del fichero entero: si los dos canales declararan lo mismo, un módulo que
    decide por su cuenta acertaría por casualidad y estos tests se volverían verdes y vacíos.
    """
    perfiles = [perfil_documental(), perfil_ficcion()]
    diferencias = {
        "laminas": {p["formato"].get("laminas_por_video_estimadas") for p in perfiles},
        "minutos": {tuple(p["formato"].get("duracion_objetivo_min") or ()) for p in perfiles},
        "ritmo": {p["voz"].get("palabras_por_segundo") for p in perfiles},
        "fichas": {bool(p["nicho"].get("sin_fuentes_verificadas")) for p in perfiles},
        "token": {p["publicacion"].get("refresh_token_env") for p in perfiles},
    }
    iguales = [nombre for nombre, valores in diferencias.items() if len(valores) == 1]
    assert not iguales, (
        f"los canales canario ya no se diferencian en {iguales}, así que los tests de este fichero pasarían "
        "sin comprobar nada. Devuélveles valores deliberadamente distintos."
    )


def _listado(raiz: Path, monkeypatch) -> dict[str, dict]:
    import pipeline

    monkeypatch.setattr(config, "CANALES_DIR", raiz)
    return {c["id"]: c for c in pipeline.listar_canales()}


@pytest.mark.parametrize("canal", CANARIOS)
def test_el_listado_lee_el_token_del_perfil_y_no_lo_deduce_del_id(raiz_de_canarios, monkeypatch, canal: str):
    """`--canales` tiene que decir la variable que declara el perfil, no una armada con el id.

    El defecto real: la variable armada con el número del canal no existía, la del segundo canal se
    llamaba `YOUTUBE_REFRESH_TOKEN_2`, y el canal salía «sin OAuth» con el token vivo. En el primero la
    deducción acertaba de casualidad, que es lo que lo mantuvo escondido.
    """
    fila = _listado(raiz_de_canarios, monkeypatch)[canal]
    declarada = (perfil_de(raiz_de_canarios, canal)["publicacion"] or {}).get("refresh_token_env")
    assert fila["variable_oauth"] == declarada, (
        f"el listado dice que el token de {canal} está en {fila['variable_oauth']!r} y su perfil "
        f"declara {declarada!r}: lo está deduciendo en vez de leerlo."
    )


@pytest.mark.parametrize("canal", CANARIOS)
def test_el_listado_no_exige_fichas_a_un_canal_cuyo_nicho_no_las_lleva(raiz_de_canarios, monkeypatch, canal: str):
    """«Cero fichas» y «este nicho no tiene aparato de fuentes» no son lo mismo."""
    fila = _listado(raiz_de_canarios, monkeypatch)[canal]
    sin_fuentes = bool(perfil_de(raiz_de_canarios, canal)["nicho"].get("sin_fuentes_verificadas"))
    assert fila["lleva_fichas"] is not sin_fuentes
    if sin_fuentes:
        assert "sin fichas" not in fila["veredicto"], fila["veredicto"]


def test_el_listado_del_repositorio_trae_el_canal_de_ejemplo():
    """El mismo listado, sobre `canales/` de verdad: el canal de ejemplo sale y lee su token del perfil."""
    import pipeline

    fila = next(c for c in pipeline.listar_canales() if c["id"] == CANAL_DE_EJEMPLO)
    perfil = json.loads((RAIZ / "canales" / CANAL_DE_EJEMPLO / "perfil.json").read_text(encoding="utf-8"))
    assert fila["variable_oauth"] == perfil["publicacion"]["refresh_token_env"]
    assert fila["lleva_fichas"] is False


def _verificador(*argumentos: str, entorno: dict | None = None) -> str:
    hecho = subprocess.run(
        [PYTHON, "scripts/verifica_guion.py", *argumentos],
        cwd=RAIZ,
        env={**os.environ, **(entorno or {})},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return hecho.stdout


@pytest.mark.parametrize("canal", CANARIOS)
def test_el_verificador_de_guiones_mide_contra_el_canal_del_GUION_no_contra_el_del_entorno(raiz_de_canarios, canal):
    """El bug de los 24 fallos falsos, convertido en prueba.

    Se lanza el verificador sobre un guion que vive en `canales/example/` con `CANAL_ACTIVO` puesto **a
    otro canal** en el entorno del proceso. Tiene que medir igualmente contra el canal del guion, y
    decirlo. Antes del 16-09 esto medía con el del `.env`, y como «0 fallos» es la condición de entrega
    de `produce-semana`, un canal entero no podía entregar nunca. El guion no hace falta que exista: el
    canal se deduce de su ruta antes de abrirlo.
    """
    guion = RAIZ / "canales" / CANAL_DE_EJEMPLO / "videos" / "run-que-no-existe" / "slides.json"
    salida = _verificador(str(guion), entorno={"CANAL_ACTIVO": str(raiz_de_canarios / canal)})
    assert f"Midiendo contra el perfil de: {CANAL_DE_EJEMPLO}\n" in salida, (
        f"con CANAL_ACTIVO={canal} en el entorno, el verificador debería seguir midiendo el guion del canal "
        f"de ejemplo contra SU perfil. Salida:\n{salida[:600]}"
    )


@pytest.mark.parametrize("canal", CANARIOS)
def test_CONTROL_un_guion_fuera_de_canales_se_mide_con_el_canal_del_entorno(raiz_de_canarios, tmp_path, canal):
    """La otra mitad: si la ruta no dice de qué canal es, manda el entorno. Sin esto, la prueba de arriba
    pasaría con un verificador que midiera siempre contra el canal de ejemplo."""
    guion = tmp_path / "slides.json"
    guion.write_text("{}", encoding="utf-8")
    salida = _verificador(str(guion), entorno={"CANAL_ACTIVO": str(raiz_de_canarios / canal)})
    assert f"Midiendo contra el perfil de: {raiz_de_canarios / canal}" in salida, salida[:600]


@pytest.mark.parametrize("canal", CANARIOS)
def test_el_verificador_estima_la_duracion_con_el_RITMO_DE_SU_CANAL(raiz_de_canarios, tmp_path, canal: str):
    """La duración que imprime tiene que salir del ritmo del perfil, no de una constante.

    Comprobado **con los dos canales a la vez**, que es la única forma de ver que de verdad cambia: con
    2,44 palabras/s frente a 1,885, un verificador que use una sola cifra falla en uno de los dos por un
    30 %. Se ejercita como subproceso, igual que lo usa un guionista: `lib.config` resuelve el canal al
    importarse, y una recarga parcial deja mezclado el perfil de un canal con los guardianes de otro.
    """
    guion = tmp_path / "slides.json"
    narracion = " ".join(["word"] * 600)
    guion.write_text(
        json.dumps({"title": "t", "slides": [{"slide_number": 1, "narration": narracion, "image_prompt": "a wall"}]}),
        encoding="utf-8",
    )
    salida = _verificador("--canal", str(raiz_de_canarios / canal), str(guion))
    medido = re.search(r"(\d+) láminas · (\d+) palabras · ~([\d.]+) min", salida)
    assert medido, f"no se encuentra la línea de estadística en la salida:\n{salida[:600]}"

    palabras, minutos = int(medido.group(2)), float(medido.group(3))
    ritmo = perfil_de(raiz_de_canarios, canal)["voz"]["palabras_por_segundo"]
    esperado = palabras / ritmo / 60
    assert abs(minutos - esperado) < 0.15, (
        f"{canal}: el verificador estima {minutos} min para {palabras} palabras, y con el ritmo de "
        f"su perfil ({ritmo} palabras/s) serían {esperado:.1f}. Está usando otro ritmo."
    )


def _pagina_del_calendario(raiz: Path, canal: str) -> str:
    hecho = subprocess.run(
        [PYTHON, "scripts/pagina_calendario.py", "--semana", "2026-W42", "--no-abrir"],
        cwd=RAIZ,
        env={**os.environ, "CANAL_ACTIVO": str(raiz / canal)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert hecho.returncode == 0, f"la página de {canal} no se genera:\n{hecho.stderr[-800:]}"
    return (raiz / canal / "calendario" / "2026-W42.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("canal", CANARIOS)
def test_la_pagina_del_calendario_se_genera_para_cualquier_canal(raiz_de_canarios, canal: str):
    """No puede reventar porque un canal no declare algo que otro sí.

    El defecto real: la fila del episodio hacía `episodio["ficha"]` con corchetes, así que en un
    canal sin fuentes moría con `KeyError` y la página —que es lo que el usuario mira para decidir— no
    se generaba. El calendario del canal de ficción no trae `ficha`.
    """
    assert "A test episode" in _pagina_del_calendario(raiz_de_canarios, canal)


@pytest.mark.parametrize("canal", CANARIOS)
def test_la_pagina_no_habla_de_fuentes_en_un_canal_que_no_las_tiene(raiz_de_canarios, canal: str):
    """Y al revés: el canal que sí las tiene conserva su aviso, con el conteo del directorio.

    Antes, el bloque «las once fichas del canal están en solo_citas_verificadas» salía **siempre**,
    así que la página de un canal de ficción le contaba al usuario fuentes que no existen.
    """
    html = _pagina_del_calendario(raiz_de_canarios, canal)
    fichas = len(list((raiz_de_canarios / canal / "datos" / "fuentes").glob("*.json")))
    sin_fuentes = bool(perfil_de(raiz_de_canarios, canal)["nicho"].get("sin_fuentes_verificadas"))
    if sin_fuentes or not fichas:
        assert "solo_citas_verificadas" not in html, f"la página de {canal} habla de fichas que no tiene"
    else:
        assert f"Las {fichas} fichas" in html, (
            f"la página de {canal} debería decir sus {fichas} fichas contadas del directorio"
        )
