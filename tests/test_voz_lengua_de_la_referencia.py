"""La lengua de la grabación de referencia la declara la receta del canal, no `lib/voice_client.py` (OC1.4).

Correr: .venv\\Scripts\\python -m pytest -q tests/test_voz_lengua_de_la_referencia.py

**Por qué.** Hasta OC1.4, `voice_client.LENGUA_NATIVA = "es"` era la lengua de la grabación del dueño del estudio, y
la decisión 13 la usaba para cualquier canal: un canal que clonara una voz inglesa sin decirlo recibía el aviso de
otro. Ahora la receta declara `referencia_de_voz.idioma_de_la_referencia`, sin defecto (F4.9): si falta, la receta no
se carga y el run se para antes de la GPU, con el mensaje de qué escribir.

Sin GPU y sin `.venv-voz`: solo se lee la receta.
"""

from __future__ import annotations

import json

import pytest
from canales_de_prueba import RECETA_DOCUMENTAL

from lib import voice_client


def _receta(tmp_path, monkeypatch, idioma=...):
    """La receta de prueba de Orpheus, con la lengua de la referencia cambiada o quitada (`None`)."""
    datos = json.loads(RECETA_DOCUMENTAL.read_text(encoding="utf-8"))
    if idioma is None:
        del datos["referencia_de_voz"]["idioma_de_la_referencia"]
    elif idioma is not ...:
        datos["referencia_de_voz"]["idioma_de_la_referencia"] = idioma
    ruta = tmp_path / "voz-prueba.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(voice_client, "VOICE_RECIPE_PATH", ruta)
    return datos


def test_la_receta_que_declara_su_lengua_se_carga(tmp_path, monkeypatch):
    _receta(tmp_path, monkeypatch)
    assert voice_client.load_recipe()["referencia_de_voz"]["idioma_de_la_referencia"] == "en"


@pytest.mark.parametrize("idioma", [None, "", "   "])
def test_control_una_receta_sin_lengua_de_la_referencia_se_niega_y_dice_que_escribir(tmp_path, monkeypatch, idioma):
    _receta(tmp_path, monkeypatch, idioma)
    with pytest.raises(voice_client.VoiceError, match="idioma_de_la_referencia") as error:
        voice_client.load_recipe()
    assert '"idioma_de_la_referencia": "en"' in str(error.value)


def test_la_politica_compara_la_lengua_de_la_receta_con_la_de_la_narracion(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_client, "NARRATION_LANG", "en")
    misma = voice_client.revisa_politica_de_idioma(_receta(tmp_path, monkeypatch, "en"))
    assert misma["ok"] is True
    # Control: una referencia en otra lengua avisa (decisión 13), sin bloquear, como antes de OC1.4.
    otra = voice_client.revisa_politica_de_idioma(_receta(tmp_path, monkeypatch, "es"))
    assert otra["ok"] is False and otra["obligatorio"] is False and "'es'" in otra["detalle"]


def test_la_lengua_es_la_de_la_receta_y_no_la_del_estudio(tmp_path, monkeypatch):
    """Lo que habría cazado el día que se escribió: con `LENGUA_NATIVA = "es"`, narrar en español con una referencia
    inglesa salía «ok, la lengua nativa de la grabación»."""
    monkeypatch.setattr(voice_client, "NARRATION_LANG", "es")
    resultado = voice_client.revisa_politica_de_idioma(_receta(tmp_path, monkeypatch, "en"))
    assert resultado["ok"] is False and "'en'" in resultado["detalle"]
    assert not hasattr(voice_client, "LENGUA_NATIVA")


def test_control_la_politica_sin_lengua_bloquea(tmp_path, monkeypatch):
    """Si una receta llega sin pasar por `load_recipe`, la política no la da por buena: bloquea y dice qué escribir."""
    monkeypatch.setattr(voice_client, "NARRATION_LANG", "en")
    resultado = voice_client.revisa_politica_de_idioma(_receta(tmp_path, monkeypatch, None))
    assert resultado["ok"] is False and resultado["obligatorio"] is True
    assert "idioma_de_la_referencia" in resultado["detalle"]
