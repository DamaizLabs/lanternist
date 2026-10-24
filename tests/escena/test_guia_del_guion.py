"""La guía del `escena.py` (`docs/scene-script.md`, OC1.4) dice lo que hace el código: su ejemplo se ejecuta aquí.

Correr: .venv\\Scripts\\python -m pytest -q tests/escena/test_guia_del_guion.py

**Por qué.** La guía es para quien use Lanternist, y su ejemplo mínimo del formato «láminas» es lo primero que copiará.
Una guía que se queda atrás del código enseña a escribir guiones que paran. Esta prueba saca el bloque de código de la
guía tal cual y lo corre contra el contrato real (`lib/escena/episodio.py`) sobre un run de prueba, sin GPU: si el
lenguaje cambia y la guía no, se pone en rojo.
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest
from utiles_escena import LAMINAS_PRUEBA, crea_run, escena_prueba

from lib.escena import laminas
from lib.escena.episodio import Lote, Puesta
from lib.escena.linea_tiempo import LineaDeTiempo

RAIZ = Path(__file__).resolve().parents[2]
GUIA = RAIZ / "docs" / "scene-script.md"
# Los ajustes del formato del canal de ejemplo, que la guía nombra (`escena.laminas`).
LAMINAS = json.loads((RAIZ / "canales" / "example" / "perfil.json").read_text(encoding="utf-8"))["escena"]["laminas"]


def bloque_del_ejemplo(texto: str) -> str:
    """El primer bloque de Python que define `puesta(ep)`: el ejemplo mínimo de la guía."""
    bloques = re.findall(r"```python\n(.*?)```", texto, flags=re.S)
    return next(b for b in bloques if "def puesta(ep)" in b)


@pytest.fixture
def episodio(tmp_path, monkeypatch):
    """Un `ep` con lo que el contrato da: el run de prueba con su título, el bloque `escena` con su formato «láminas»,
    la línea de tiempo y un catálogo con las láminas ampliadas que pide `activos(ep)`."""
    run = crea_run(tmp_path, LAMINAS_PRUEBA)
    slides = json.loads((run / "slides.json").read_text(encoding="utf-8"))
    slides["title"] = "How the zip works"
    (run / "slides.json").write_text(json.dumps(slides), encoding="utf-8")
    escena = {**escena_prueba(), "laminas": LAMINAS}
    catalogo = {f"lamina_{n:02d}": {"src": f"assets/img/lamina_{n:02d}.png", "w": 2688, "h": 1536} for n in (1, 2)}
    css = tmp_path / "estilo.css"
    css.write_text("/* el CSS del canal */", encoding="utf-8")
    # La capa del canal, que el guion importa siempre con el mismo nombre.
    capa = types.ModuleType("escena_del_canal")
    capa.CSS = css
    monkeypatch.setitem(sys.modules, "escena_del_canal", capa)
    ep = types.SimpleNamespace(
        run_dir=run,
        idioma="en",
        escena=escena,
        catalogo=lambda: catalogo,
        linea=lambda: LineaDeTiempo.del_run(run, escena=escena, idioma="en"),
    )
    return ep


def test_el_ejemplo_de_la_guia_cumple_el_contrato(episodio):
    modulo: dict = {}
    exec(compile(bloque_del_ejemplo(GUIA.read_text(encoding="utf-8")), str(GUIA), "exec"), modulo)

    lote = modulo["activos"](episodio)
    assert isinstance(lote, Lote) and lote.activos == ()
    assert [(op["op"], op["nombre"], op.get("del_episodio")) for op in lote.extra] == [
        ("fondo", "lamina_01", True),
        ("fondo", "lamina_02", True),
    ]

    puesta = modulo["puesta"](episodio)
    assert isinstance(puesta, Puesta) and puesta.css == sys.modules["escena_del_canal"].CSS
    assert puesta.franja_karaoke_y == episodio.escena["franja_karaoke_y"]
    assert set(puesta.guion.fondos) == {"lamina_01", "lamina_02"}
    # Los planos son los del formato: los mismos que da el planificador con el mismo título y las mismas láminas.
    linea = episodio.linea()
    slides = json.loads((episodio.run_dir / "slides.json").read_text(encoding="utf-8"))
    a = laminas.ajustes(episodio.escena)
    tomas = laminas.planifica(
        laminas.laminas_del_episodio(linea, slides["slides"]),
        clave_del_video=slides["title"],
        fps=linea.fps,
        ajustes_=a,
    )
    assert len(puesta.guion.planos) == len(tomas) >= 2


def test_control_la_prueba_ve_un_ejemplo_que_ya_no_cumple(episodio):
    """Si la guía escribiera una función que no existe, el ejemplo no correría: la prueba sabe fallar."""
    roto = bloque_del_ejemplo(GUIA.read_text(encoding="utf-8")).replace("laminas.planifica(", "laminas.planea(")
    modulo: dict = {}
    exec(compile(roto, "roto.py", "exec"), modulo)
    with pytest.raises(AttributeError, match="planea"):
        modulo["puesta"](episodio)
