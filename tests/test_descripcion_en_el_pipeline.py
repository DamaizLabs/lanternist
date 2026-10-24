"""La descripción se compone DENTRO del pipeline, y sus fichas las declara el guion.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_descripcion_en_el_pipeline.py

**De dónde sale.** El 12-09, con el gate 2 del episodio 2 aprobado, `pipeline.py --stage upload` falló
antes de tocar la red: la descripción llevaba `<<CAPITULOS>>` y `<<BIBLIOGRAFIA>>` literales y la guarda
de `lib/youtube_client.revisa_descripcion` la paró. La guarda hacía su trabajo; lo que faltaba era el
paso anterior — `scripts/compone_descripcion.py` era el paso 8 del skill, a mano, y ninguna etapa lo
llamaba (addendum fila 154). Con la subida activada, un `--run-all` moría ahí.

Estas pruebas fijan las tres cosas que hacen que eso no vuelva a pasar:

1. La etapa compone sola, y **es idempotente**: una subida se relanza y no puede morir por haber
   compuesto bien la primera vez.
2. Las fichas de la bibliografía **las declara el guion** y no se deducen: deducirlas publicaría citas
   que nadie eligió, que es justo lo contrario del módulo de fuentes.
3. Sin el campo, el run **para y dice qué escribir** — en vez de subir un vídeo con un bloque de citas
   vacío en la página.
"""

import contextlib
import json

import pytest

from lib import state as run_state
from scripts.compone_descripcion import fichas_del_guion

CON_MARCADORES = "Un episodio.\n\n<<CAPITULOS>>\n\n<<BIBLIOGRAFIA>>"


# --- lo que el guion declara -------------------------------------------------------------------


def test_las_fichas_salen_del_guion():
    assert fichas_del_guion({"fuentes": ["jaula-de-gibbet"]}) == ["jaula-de-gibbet"]
    assert fichas_del_guion({"fuentes": ["a", "b"]}) == ["a", "b"]


def test_una_sola_ficha_puede_venir_como_cadena():
    """El campo se escribe a mano en el gate 1: una cadena suelta es el error que cualquiera haría."""
    assert fichas_del_guion({"fuentes": "jaula-de-gibbet"}) == ["jaula-de-gibbet"]


def test_sin_campo_o_con_huecos_no_se_inventa_ninguna():
    assert fichas_del_guion({}) == []
    assert fichas_del_guion({"fuentes": []}) == []
    assert fichas_del_guion({"fuentes": ["", "  "]}) == []


# --- la guarda de la etapa de subida ------------------------------------------------------------


@pytest.fixture
def sin_tocar_el_estado(monkeypatch):
    """La guarda marca la etapa `blocked` en disco: aquí no hay run, se intercepta."""
    escritos = []
    monkeypatch.setattr(run_state, "update_stage", lambda *a, **k: escritos.append(a))
    return escritos


def _pipeline():
    import pipeline

    return pipeline


def test_sin_fuentes_y_con_marcador_la_subida_PARA_y_dice_que_escribir(sin_tocar_el_estado):
    """El caso real: el guion del episodio 2 no declaraba fichas y su descripción pedía bibliografía."""
    with pytest.raises(ValueError, match="fuentes"):
        _pipeline()._exige_fichas_de_la_bibliografia("run-x", {"description": CON_MARCADORES})
    assert sin_tocar_el_estado and sin_tocar_el_estado[0][1:3] == ("upload", "blocked")


def test_CONTROL_NEGATIVO_con_fuentes_declaradas_la_guarda_deja_pasar(sin_tocar_el_estado):
    """Sin esto, la prueba de arriba no distingue «la guarda funciona» de «siempre lanza»."""
    fichas = _pipeline()._exige_fichas_de_la_bibliografia(
        "run-x", {"description": CON_MARCADORES, "fuentes": ["jaula-de-gibbet"]}
    )
    assert fichas == ["jaula-de-gibbet"]
    assert not sin_tocar_el_estado


def test_una_descripcion_YA_compuesta_no_necesita_fichas(sin_tocar_el_estado):
    """Un run viejo se puede volver a subir sin tocarle el guion: sin marcador no hay nada que componer."""
    assert _pipeline()._exige_fichas_de_la_bibliografia("run-x", {"description": "Ya compuesta, sin marcadores"}) == []
    assert not sin_tocar_el_estado


# --- la composición, sobre un run de mentira -----------------------------------------------------


@pytest.fixture
def run_falso(tmp_path, monkeypatch):
    """Un run con su `slides.json` y su `montaje.json`, que es de donde salen los tiempos reales."""
    from scripts import compone_descripcion

    monkeypatch.setattr(compone_descripcion, "CANAL_VIDEOS_DIR", tmp_path)
    run = tmp_path / "run-x"
    run.mkdir()
    (run / "montaje.json").write_text(
        json.dumps(
            {
                "duracion_s": 600.0,
                "detalle": [{"plano": n - 1, "slide": n, "segundos": 60.0} for n in range(1, 11)],
            }
        ),
        encoding="utf-8",
    )

    def escribe(slides: dict):
        (run / "slides.json").write_text(json.dumps(slides, ensure_ascii=False), encoding="utf-8")
        return run

    return escribe


def test_componer_dos_veces_no_falla_la_segunda(run_falso, monkeypatch):
    """La etapa de subida se relanza —un 403, un corte de red—: componer bien no puede ser un error."""
    from scripts import compone_descripcion

    monkeypatch.setattr(compone_descripcion, "bloque_bibliografia", lambda *a, **k: ("Sources\n  x", [], []))
    run = run_falso(
        {
            "description": CON_MARCADORES,
            "capitulos": [{"titulo": f"C{n}", "slide_inicial": n} for n in (1, 4, 7)],
        }
    )

    primera = compone_descripcion.compon("run-x", ["ficha"], traducidos=[])
    assert primera["compuesta"] and primera["capitulos"] == 3

    segunda = compone_descripcion.compon("run-x", ["ficha"], traducidos=[])
    assert segunda["compuesta"] is False
    assert "ya estaba" in segunda["motivo"]
    # y el texto que quedó en disco es el de la primera pasada, no uno recompuesto
    assert "<<" not in json.loads((run / "slides.json").read_text(encoding="utf-8"))["description"]


# --- Un canal sin fichas: capítulos sí, bibliografía no (15-09-2026) -----------------------------


def test_sin_fichas_la_bibliografia_sale_vacia_SIN_lanzar_fuentes(monkeypatch):
    """Un canal sin fichas activó capítulos y la subida murió llamando a `fuentes.py --bibliografia` sin argumentos.

    El componedor solo se lanzaba cuando había marcadores, y ese canal no tenía ninguno; en cuanto tuvo
    el de capítulos, compuso la descripción entera y de paso pidió unas citas que este canal no
    tiene. El error llegó **después** de montar el vídeo y de subir la miniatura.
    """
    from scripts import compone_descripcion

    def no_deberia_lanzarse(_fichas):  # pragma: no cover - si se llama, la prueba falla
        raise AssertionError("no se puede lanzar fuentes.py sin fichas")

    monkeypatch.setattr(compone_descripcion, "_lanza_fuentes", no_deberia_lanzarse)
    assert compone_descripcion.bloque_bibliografia([], "en") == ("", [], [])


def test_CONTROL_NEGATIVO_con_fichas_SI_se_lanza(monkeypatch):
    """Si la guarda devolviera vacío siempre, el canal que SÍ cita perdería su bibliografía callando.

    Se comprueba la LLAMADA y no el texto: componer el bloque lee además las fichas del canal en
    disco, y esta prueba no va de eso — va de que el atajo no se coma el caso con fichas.
    """
    from scripts import compone_descripcion

    lanzadas = []

    def espia(fichas):
        lanzadas.append(list(fichas))
        return ""

    monkeypatch.setattr(compone_descripcion, "_lanza_fuentes", espia)
    # Con una salida vacía el componedor termina en `SystemExit` —una ficha que no da ni una cita es
    # un fallo suyo, y está bien que lo sea—. Aquí eso da igual: lo que se mide es que la llamada
    # LLEGA a hacerse, o sea que el atajo de «sin fichas» no se ha comido el caso con fichas.
    with contextlib.suppress(SystemExit):
        compone_descripcion.bloque_bibliografia(["una-ficha"], "en")
    assert lanzadas == [["una-ficha"]]
