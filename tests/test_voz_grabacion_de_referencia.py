"""`lib/voice_client.resolve_recording`: la grabación de referencia sale de UNA variable de entorno.

La lista por orden de preferencia, que solo pedía el perfil de voz grave de F2.2b, se retiró el 01-10-2026 al
cancelar D2.1 (fila 227). La grabación jamás entra en el repositorio (lista negra): se lee siempre del entorno.
"""

from __future__ import annotations

import pytest

from lib import voice_client


def test_una_variable_con_su_archivo_da_la_grabacion(tmp_path, monkeypatch):
    grabacion = tmp_path / "voz.wav"
    grabacion.write_bytes(b"RIFF")
    monkeypatch.setenv("RUTA_VOZ_PRUEBA", str(grabacion))
    assert voice_client.resolve_recording({"variable_entorno": "RUTA_VOZ_PRUEBA"}) == ("RUTA_VOZ_PRUEBA", grabacion)


def test_control_una_lista_de_variables_ya_no_vale(tmp_path, monkeypatch):
    grabacion = tmp_path / "voz.wav"
    grabacion.write_bytes(b"RIFF")
    monkeypatch.setenv("RUTA_VOZ_PRUEBA", str(grabacion))
    with pytest.raises(voice_client.VoiceError, match="UNA variable"):
        voice_client.resolve_recording({"variable_entorno": ["RUTA_VOZ_GRAVE", "RUTA_VOZ_PRUEBA"]})


@pytest.mark.parametrize("valor", [None, "C:/no/existe/voz.wav"])
def test_sin_valor_o_sin_archivo_el_error_nombra_la_variable(monkeypatch, valor):
    if valor is None:
        monkeypatch.delenv("RUTA_VOZ_PRUEBA", raising=False)
    else:
        monkeypatch.setenv("RUTA_VOZ_PRUEBA", valor)
    with pytest.raises(voice_client.VoiceError, match="RUTA_VOZ_PRUEBA"):
        voice_client.resolve_recording({"variable_entorno": "RUTA_VOZ_PRUEBA"})
