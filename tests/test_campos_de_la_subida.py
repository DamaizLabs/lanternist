"""Los campos que el usuario rellenaba a mano en Studio y ahora van en la subida.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_campos_de_la_subida.py

**De dónde sale.** El 15-09-2026, tras dar por bueno el episodio de un canal, llegó una captura de
la pantalla «Detalles del vídeo» con seis casillas que había habido que rellenar a mano, y la petición: «busca
todos los campos que puedas implementar y los rellenas tú, y que sea por igual para todos los
canales». Cuatro de los seis son escribibles en `videos.insert` con el scope que ya hay; los otros
dos —certificación de subtítulos y ubicación— no existen en la API.

**Y estas pruebas no llaman a YouTube.** Se intercepta `requests.post` y se mira el cuerpo que se
iba a enviar, que es donde vive lo que se quiere comprobar. Sin red, sin credenciales y sin subir
nada a un canal real.
"""

import pytest

from lib import config, youtube_client

DESCRIPCION = "A short story in slow English.\n\nAI DISCLOSURE: voice and images generated locally."


class _Interceptada(Exception):
    """Corta la subida justo después de capturar el cuerpo: lo que sigue ya es red."""


@pytest.fixture
def cuerpo(monkeypatch, tmp_path):
    """El JSON que `upload_video` manda al abrir la subida reanudable."""
    capturado = {}

    def post_falso(url, **kwargs):
        capturado["url"] = url
        capturado["json"] = kwargs.get("json")
        raise _Interceptada

    monkeypatch.setattr(youtube_client, "get_access_token", lambda: "token-de-mentira")
    monkeypatch.setattr(youtube_client.requests, "post", post_falso)

    video = tmp_path / "final.mp4"
    video.write_bytes(b"no importa: no se llega a leer")
    with pytest.raises(_Interceptada):
        youtube_client.upload_video(
            file_path=str(video),
            title="Un título",
            description=DESCRIPCION,
            tags=["a"],
            fecha_de_grabacion="2026-09-14T00:00:00Z",
        )
    return capturado


def test_los_dos_idiomas_salen_del_CANAL_y_no_de_un_literal(cuerpo):
    """Un defecto «en» declararía mal el idioma de un canal en español, y eso cambia a quién se le recomienda."""
    snippet = cuerpo["json"]["snippet"]
    assert snippet["defaultLanguage"] == config.NARRATION_LANG
    assert snippet["defaultAudioLanguage"] == config.NARRATION_LANG


def test_la_licencia_el_insertado_y_las_estadisticas_son_del_ESTUDIO(cuerpo):
    """«Que sea por igual para todos los canales»: los tres son constantes, no claves de perfil."""
    estado = cuerpo["json"]["status"]
    assert estado["license"] == youtube_client.LICENCIA == "youtube"
    assert estado["embeddable"] is youtube_client.INSERTABLE is True
    assert estado["publicStatsViewable"] is youtube_client.ESTADISTICAS_PUBLICAS is True


def test_la_fecha_de_grabacion_viaja_y_el_part_la_nombra(cuerpo):
    """Sin `recordingDetails` en `part`, la fecha va en el cuerpo y la API la ignora EN SILENCIO."""
    assert cuerpo["json"]["recordingDetails"] == {"recordingDate": "2026-09-14T00:00:00Z"}
    assert "recordingDetails" in cuerpo["url"]


def test_CONTROL_NEGATIVO_el_video_sigue_entrando_PRIVADO_y_sin_fecha_de_publicacion(cuerpo):
    """La decisión 2 es lo único que estos campos nuevos no pueden rozar.

    `status.publishAt` también es escribible en el insert, y ponerlo aquí sería publicar por regla
    en vez de por el clic del usuario. Que no esté es tan importante como que estén los demás.
    """
    estado = cuerpo["json"]["status"]
    assert estado["privacyStatus"] == "private"
    assert "publishAt" not in estado
    assert estado["containsSyntheticMedia"] is True


def test_sin_fecha_el_bloque_va_vacio_y_no_se_inventa_ninguna(monkeypatch, tmp_path):
    """Un run viejo sin `created_at` no puede acabar declarando la fecha de hoy como la de grabación."""
    capturado = {}

    def post_falso(url, **kwargs):
        capturado["json"] = kwargs.get("json")
        raise _Interceptada

    monkeypatch.setattr(youtube_client, "get_access_token", lambda: "token-de-mentira")
    monkeypatch.setattr(youtube_client.requests, "post", post_falso)
    video = tmp_path / "final.mp4"
    video.write_bytes(b"x")
    with pytest.raises(_Interceptada):
        youtube_client.upload_video(file_path=str(video), title="T", description=DESCRIPCION)
    assert capturado["json"]["recordingDetails"] == {}


# --- La fecha, que la calcula el pipeline desde el expediente del run ----------------------------


def _fecha(state: dict) -> str:
    import pipeline

    return pipeline._fecha_de_grabacion(state)


def test_la_fecha_sale_del_created_at_del_run_con_la_hora_a_cero():
    assert _fecha({"created_at": "2026-09-14T17:41:04.610176"}) == "2026-09-14T00:00:00Z"


@pytest.mark.parametrize("state", [{}, {"created_at": ""}, {"created_at": "ayer por la tarde"}])
def test_un_estado_sin_fecha_usable_devuelve_vacio(state):
    """Vacío significa «no mandes el campo», que es exactamente lo que hacía antes de existir."""
    assert _fecha(state) == ""


# --- Los dos idiomas de la subida respetan la anulación por entorno (auditoría del 15-09, ALTO 2) ---


def test_CONTROL_la_subida_respeta_IDIOMA_NARRACION_del_entorno():
    """La voz, la declaración de IA y la descripción leen `NARRATION_LANG`, que acepta `IDIOMA_NARRACION`
    del `.env`. La subida tiene que leer LA MISMA constante: con la variable puesta a `es`, decir «en» a
    YouTube declara el vídeo en un idioma y narra en otro.

    Va en un proceso aparte porque el idioma se resuelve al importar `lib.config`: cambiar el entorno
    dentro de este intérprete mediría otra cosa. Contra el código del 15-09 por la mañana FALLA —la
    subida leía `IDIOMA_NARRACION`, una constante gemela sin la anulación—, que es lo que la convierte
    en control y no en decorado.
    """
    import os
    import subprocess
    import sys

    programa = (
        "import lib.youtube_client as yc\n"
        "class Corta(Exception): pass\n"
        "capturado = {}\n"
        "def post(url, **kw):\n"
        "    capturado['json'] = kw.get('json'); raise Corta\n"
        "yc.get_access_token = lambda: 't'\n"
        "yc.requests.post = post\n"
        "try:\n"
        "    yc.upload_video(file_path='x.mp4', title='T', description='AI DISCLOSURE: local.')\n"
        "except Corta:\n"
        "    pass\n"
        "s = capturado['json']['snippet']\n"
        "print(s['defaultLanguage'], s['defaultAudioLanguage'])\n"
    )
    entorno = {**os.environ, "IDIOMA_NARRACION": "es", "PYTHONIOENCODING": "utf-8"}
    salida = subprocess.run(
        [sys.executable, "-c", programa], capture_output=True, text=True, env=entorno, cwd=os.getcwd(), timeout=120
    )
    assert salida.returncode == 0, salida.stderr[-800:]
    # La ÚLTIMA línea: `upload_video` imprime «iniciando subida reanudable…» antes de llegar al post.
    ultima = salida.stdout.strip().splitlines()[-1] if salida.stdout.strip() else ""
    assert ultima == "es es", f"la subida no respeta IDIOMA_NARRACION: dijo {ultima!r}"
