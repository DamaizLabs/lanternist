"""El guardián de líneas rojas es POR CANAL (F4.8) — pruebas sin red y sin GPU.

Correr: .venv\\Scripts\\python -m pytest -q tests

Lo que estas pruebas defienden no es el detector, que ya estaba probado en producción desde F2.5:
es la **frontera**. El piloto del segundo canal encontró la especificación del primero metida en `lib/`, y estas
pruebas existen para que no vuelva. La de no regresión es la más importante de las cuatro: mover
siete umbrales de sitio no puede cambiar lo que ve el canal en tinta.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lib import lineas_rojas as lr  # la raíz del repo la pone tests/conftest.py

REPO = Path(__file__).resolve().parent.parent

# Una especificación de trabajo para las pruebas de comportamiento, con la forma de la del primer canal
# del estudio, el de tinta. La prueba que vigilaba su perfil real se fue con él en OC1.1.
SPEC_TINTA = {
    "nombre": "sangre",
    "que_evita": "sangre o heridas",
    "hue_max": 12.0,
    "sat_min": 0.35,
    "val_min": 0.15,
    "val_max": 0.85,
    "umbral_celda": 64,
    "umbral_grueso": 96,
    "umbral_total": 250,
}


def _guardianes(spec=SPEC_TINTA):
    return lr.guardianes_del_canal({"lineas_rojas": {"guardianes_de_color": [spec]}})


def _imagen(tmp_path, nombre: str, pintar) -> "object":
    """Una lámina de papel (blanco) de 200x200 sobre la que `pintar` deja lo que haga falta."""
    arr = np.full((200, 200, 3), 245, dtype=np.uint8)
    pintar(arr)
    ruta = tmp_path / nombre
    Image.fromarray(arr).save(ruta)
    return ruta


# El carmesí de la lámina que se coló en el primer run: hue ~2°, sat 0,75, valor 0,43.
CARMESI = (110, 12, 15)
# El acento de óxido del zoo, que es LEGÍTIMO en el canal en tinta: hue ~20°, mucho más claro.
OXIDO = (181, 96, 14)


def test_una_mancha_en_la_banda_del_canal_suspende(tmp_path):
    """El caso que este módulo existe para cazar: una mancha compacta del color prohibido."""
    ruta = _imagen(tmp_path, "con-mancha.png", lambda a: a.__setitem__((slice(40, 60), slice(40, 60)), CARMESI))
    v = lr.revisa(ruta, _guardianes())

    assert not v["pasa"]
    assert v["motivo"] == "mancha compacta"
    assert v["por_guardian"][0]["guardian"] == "sangre"
    assert v["caja_mancha"] is not None


def test_el_acento_legitimo_del_canal_no_se_confunde_con_lo_prohibido(tmp_path):
    """La regresión que la primera versión del módulo sí tuvo: marcaba el óxido como sangre.

    Es la razón de que el criterio sea el TONO y no «el rojo»: separan por 12° de margen. Y es la
    misma lección que obligó a F4.8 — un umbral de color solo significa algo dentro de una paleta.
    """
    ruta = _imagen(tmp_path, "oxido.png", lambda a: a.__setitem__((slice(40, 90), slice(40, 90)), OXIDO))
    assert lr.revisa(ruta, _guardianes())["pasa"]


def test_un_canal_sin_guardianes_no_hereda_los_de_otro(tmp_path):
    """El mandato del 03-09: cada canal con su guardián y NINGUNA sinergia entre ellos.

    La misma imagen que suspende en el canal en tinta pasa en un canal que no declara guardián de color — que
    es literalmente lo que pasaba con las orejas del perro del segundo canal.
    """
    ruta = _imagen(tmp_path, "carmesi.png", lambda a: a.__setitem__((slice(40, 60), slice(40, 60)), CARMESI))

    assert not lr.revisa(ruta, _guardianes())["pasa"]  # en el canal en tinta suspende

    sin_guardianes = lr.guardianes_del_canal({"lineas_rojas": {"guardianes_de_color": []}})
    v = lr.revisa(ruta, sin_guardianes)
    assert v["pasa"] and v["guardianes"] == 0
    assert "sin guardián de color declarado" in v["regla"]


def test_sin_declaracion_falla_cerrada_y_dice_que_declarar():
    """Un canal nuevo sin el bloque NO pasa de largo: se para y explica qué escribir.

    Es la decisión del 03-09 (fail-closed) y el mismo patrón que el CTR en metricas.py:
    sin dato, «sin evaluar, nunca aprobado» — nunca un verde por omisión.
    """
    with pytest.raises(lr.LineaRojaError) as e:
        lr.guardianes_del_canal({"lineas_rojas": {"resumen": "las de este canal son de situación"}})
    assert lr.CLAVE_PERFIL in str(e.value)
    assert "no un olvido" in str(e.value)

    # Y un guardián a medias tampoco pasa: enumera lo que le falta.
    with pytest.raises(lr.LineaRojaError) as e2:
        lr.guardianes_del_canal({"lineas_rojas": {"guardianes_de_color": [{"nombre": "x", "hue_max": 12}]}})
    assert "le faltan los campos" in str(e2.value) and "umbral_total" in str(e2.value)


def test_el_mensaje_de_exige_usa_la_frase_del_canal_y_no_la_palabra_sangre(tmp_path, monkeypatch):
    """El mensaje lo escribe el canal. Antes decía «en este canal solo puede ser sangre» SIEMPRE."""
    ruta = _imagen(tmp_path, "mancha.png", lambda a: a.__setitem__((slice(40, 60), slice(40, 60)), CARMESI))
    spec = dict(SPEC_TINTA, nombre="tinta corporativa", que_evita="el rojo de otra marca")
    # Los guardianes se construyen ANTES de parchear: si el sustituto llamase al helper, y el
    # helper a la función parcheada, la recursión sería infinita (medido).
    del_canal = _guardianes(spec)
    monkeypatch.setattr(lr, "guardianes_del_canal", lambda *a, **k: del_canal)

    with pytest.raises(lr.LineaRojaError) as e:
        lr.exige([ruta], etapa="prueba")
    assert "tinta corporativa" in str(e.value) and "el rojo de otra marca" in str(e.value)


def test_una_imagen_que_no_se_puede_medir_para_la_etapa(tmp_path):
    """Falla cerrada también aquí: sin poder mirar, no se da nada por bueno."""
    with pytest.raises(lr.LineaRojaError, match="no existe"):
        lr.revisa(tmp_path / "no-esta.png", _guardianes())

    minuscula = tmp_path / "diez.png"
    Image.fromarray(np.full((10, 10, 3), 245, dtype=np.uint8)).save(minuscula)
    with pytest.raises(lr.LineaRojaError, match="no cabe una ventana"):
        lr.revisa(minuscula, _guardianes())


def test_con_varios_guardianes_no_se_publica_un_umbral_del_canal(tmp_path):
    """Dos reglas distintas no tienen un umbral común: publicarlo sería un número inventado."""
    ruta = _imagen(tmp_path, "limpia.png", lambda a: None)
    dos = lr.guardianes_del_canal(
        {"lineas_rojas": {"guardianes_de_color": [SPEC_TINTA, dict(SPEC_TINTA, nombre="otro", umbral_total=900)]}}
    )
    inf = lr.revisa_lote([ruta], dos)
    assert inf["umbral_total"] is None
    assert inf["umbrales_por_guardian"]["sangre"]["total"] == 250
    assert inf["umbrales_por_guardian"]["otro"]["total"] == 900
