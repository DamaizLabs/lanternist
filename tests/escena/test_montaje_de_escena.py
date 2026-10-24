"""La declaración de IA del vídeo de un run del motor de escena, según lo que dice su `montaje.json` (F6.3, F6.8).

Recomendación 5 de `progress/review_F6.2d.md`, con su control negativo: la declaración de un vídeo del motor de escena
no dice «Still illustrations» si sus ilustraciones se mueven. Las recomendaciones 1 y 2 (que `cta.ventana`,
`subtitulos._offsets_por_lamina` y `scripts/mide_costuras.py` leyeran ese `montaje.json`) se probaban aquí y salieron
con el motor de láminas en F6.7: eran lectores suyos.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import publicacion


# ------------------------------------------------------------------------------------------ 5. la declaración de IA
def _assets(tmp_path: Path, motor: str | None, actores: int | None = None) -> Path:
    video = {"id": "subir-al-canal/final.mp4", "tipo": "video", "modelo": "ninguno: render", "detalle": {}}
    if motor:
        video["detalle"]["motor"] = motor
    if actores is not None:
        video["detalle"]["actores"] = actores
    datos = {
        "assets": [
            {"id": "audio/slide-01.wav", "tipo": "audio", "modelo": "Orpheus TTS 3B"},
            {"id": "activos/img/nora.png", "tipo": "imagen", "modelo": "Qwen-Image-Edit-2511"},
            video,
        ]
    }
    (tmp_path / "assets.json").write_text(json.dumps(datos), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("idioma", ["en", "es"])
def test_la_declaracion_de_un_video_de_escena_dice_que_sus_ilustraciones_se_mueven(tmp_path, idioma):
    texto, avisos = publicacion.declaracion_de_ia(_assets(tmp_path, "escena"), idioma)
    assert publicacion.PIEZAS[idioma]["imagen_escena"] in texto and avisos == []
    assert publicacion.PIEZAS[idioma]["imagen"] not in texto


@pytest.mark.parametrize("idioma", ["en", "es"])
def test_sin_figuras_que_se_muevan_son_ilustraciones_fijas_con_camara(tmp_path, idioma):
    """El formato «láminas» (F6.8): la cámara recorre la lámina y ninguna figura se mueve."""
    texto, avisos = publicacion.declaracion_de_ia(_assets(tmp_path, "escena", actores=0), idioma)
    assert publicacion.PIEZAS[idioma]["imagen_camara"] in texto and avisos == []
    assert publicacion.PIEZAS[idioma]["imagen_escena"] not in texto


@pytest.mark.parametrize("actores", [3, None])
def test_control_con_figuras_o_sin_saberlo_se_declaran_escenas_animadas(tmp_path, actores):
    # Con figuras que se mueven, o en un montaje anterior a F6.8 que no las contaba: la que no se queda corta.
    texto, _ = publicacion.declaracion_de_ia(_assets(tmp_path, "escena", actores=actores), "en")
    assert publicacion.PIEZAS["en"]["imagen_escena"] in texto and "camera movement" not in texto


def test_control_la_del_montaje_de_siempre_sigue_siendo_de_ilustraciones_fijas(tmp_path):
    texto, _ = publicacion.declaracion_de_ia(_assets(tmp_path, None), "en")
    assert "Still illustrations: AI-generated" in texto and "Animated scenes" not in texto


def test_una_imagen_del_catalogo_que_va_como_elemento_cuenta_como_figura():
    """Revisión de F6.8, R2: un objeto que entra o flota (`Guion.dibujo`) es una imagen de IA que se mueve."""
    from utiles_escena import CATALOGO_PRUEBA, escena_prueba

    from lib.escena import etapas
    from lib.escena.escena import Guion

    g = Guion(titulo="Prueba", idioma="en", escena=escena_prueba(), catalogo=CATALOGO_PRUEBA, iconos={})
    # Lo que busca el recuento en la página es justo lo que escribe `Guion.dibujo` para una imagen del catálogo…
    assert g.dibujo("rueda").startswith(etapas.OBJETO_DEL_CATALOGO)
    # …y un icono del canal (un SVG suyo, sin imagen de IA) no lo lleva.
    g2 = Guion(titulo="Prueba", idioma="en", escena=escena_prueba(), catalogo=CATALOGO_PRUEBA,
               iconos={"flecha": "<svg></svg>"})  # fmt: skip
    assert etapas.OBJETO_DEL_CATALOGO not in g2.dibujo("flecha")


def test_con_un_objeto_que_se_mueve_ya_no_son_ilustraciones_fijas(tmp_path):
    texto, _ = publicacion.declaracion_de_ia(_assets(tmp_path, "escena", actores=1), "en")
    assert publicacion.PIEZAS["en"]["imagen_escena"] in texto
