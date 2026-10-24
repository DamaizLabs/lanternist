"""Una lámina puede llevar su propio `prefijo_estilo` en `slides.json` (OC1.4), y solo ella.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_lamina_con_su_estilo.py

**Por qué.** La lámina 3 del canal de ejemplo solo dibujó un único tirador con el prompt entero en español, estilo
incluido. Para que el pipeline la reproduzca, el estilo de esa lámina vive en su entrada de `slides.json`. Lo que no
puede pasar es que ese estilo se cuele en las demás láminas del lote ni en el workflow cargado.
"""

from __future__ import annotations

import contextlib

from lib import comfy_client as cc

WORKFLOW = {"id": "prueba", "modelo": {}, "prefijo_estilo": "pen and ink."}


def _lote(tmp_path, monkeypatch, items):
    usados = {}

    def render(workflow, prompt, salida, **_):
        usados[salida.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]] = cc._compose_prompt(workflow, prompt)
        return {"file": salida, "segundos": 0.0, "modelo": "prueba"}

    monkeypatch.setattr(cc, "load_workflow", lambda _id: WORKFLOW)
    monkeypatch.setattr(cc, "comfy_server", contextlib.nullcontext)
    monkeypatch.setattr(cc, "render", render)
    monkeypatch.setattr(cc, "_dump_records", lambda *_: None)
    cc.generate_images_batch(items, str(tmp_path), style="prueba")
    return usados


def test_el_estilo_de_una_lamina_va_solo_a_ella(tmp_path, monkeypatch):
    usados = _lote(
        tmp_path,
        monkeypatch,
        [
            {"prompt": "a zip", "filename": "slide-01.png"},
            {"prompt": "una cremallera", "filename": "slide-02.png", "prefijo_estilo": "grabado en sepia."},
        ],
    )
    assert usados == {"slide-01.png": "pen and ink. a zip", "slide-02.png": "grabado en sepia. una cremallera"}
    assert WORKFLOW["prefijo_estilo"] == "pen and ink.", "el workflow cargado no cambia"


def test_control_sin_estilo_propio_manda_el_del_workflow(tmp_path, monkeypatch):
    usados = _lote(tmp_path, monkeypatch, [{"prompt": "una cremallera", "filename": "slide-02.png"}])
    assert usados == {"slide-02.png": "pen and ink. una cremallera"}
