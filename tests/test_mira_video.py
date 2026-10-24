"""`scripts/mira_video.py` sin red (OC1.11, fila 319): oEmbed y la miniatura, simulados.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_mira_video.py

Cada forma de enlace da su id, y cada enlace que no es un vídeo se niega sin salir a la red. La respuesta de oEmbed es
dato de terceros: una miniatura de otro host no se pide, y el título va escapado en la página. Con `--video`, los
fotogramas salen de un vídeo corto que ffmpeg genera en `tmp_path`.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import urllib.error
import urllib.request

import pytest
from PIL import Image

from scripts import mira_video

ID = "jNQXAC9IVRw"
MINIATURA = f"https://i.ytimg.com/vi/{ID}/hqdefault.jpg"


def _jpeg() -> bytes:
    salida = io.BytesIO()
    Image.new("RGB", (480, 360), "teal").save(salida, "JPEG")
    return salida.getvalue()


def _oembed(**cambios) -> bytes:
    datos = {"type": "video", "title": "Me at the zoo", "author_name": "jawed", "thumbnail_url": MINIATURA}
    return json.dumps({**datos, **cambios}).encode("utf-8")


@pytest.fixture
def red(monkeypatch):
    """Sustituye al `urlopen` de la orden. `respuestas`: {prefijo de URL: bytes o un código HTTP}. `pedidas`: lo pedido.
    Una URL que no está en `respuestas` hace fallar la prueba: la orden no debe pedir nada más."""

    class Red:
        respuestas: dict = {}
        pedidas: list[str] = []

    def abre(peticion, timeout):
        assert timeout == mira_video.TIMEOUT_S
        url = peticion.full_url
        Red.pedidas.append(url)
        for prefijo, respuesta in Red.respuestas.items():
            if url.startswith(prefijo):
                if isinstance(respuesta, int):
                    raise urllib.error.HTTPError(url, respuesta, "simulado", {}, None)
                return io.BytesIO(respuesta)
        raise AssertionError(f"la orden pidió una URL que no debía: {url}")

    monkeypatch.setattr(mira_video, "_ABRE", abre)
    Red.respuestas, Red.pedidas = {}, []
    return Red


def _captura(tmp_path, nombre="captura.png"):
    ruta = tmp_path / nombre
    Image.new("RGB", (1280, 720), "orange").save(ruta)
    return str(ruta)


@pytest.mark.parametrize(
    "enlace",
    [
        f"https://www.youtube.com/watch?v={ID}",
        f"https://youtube.com/watch?v={ID}&t=10s",
        f"https://m.youtube.com/watch?v={ID}",
        f"https://youtu.be/{ID}?si=abc",
        f"https://www.youtube.com/shorts/{ID}",
        f"https://www.youtube.com/embed/{ID}",
        f"https://www.youtube.com/watch?v={ID}&list=PL0123456789",
        f"  https://www.youtube.com/watch?v={ID}  ",
    ],
)
def test_cada_forma_de_enlace_da_el_id_del_video(enlace):
    assert mira_video.id_del_enlace(enlace) == ID


@pytest.mark.parametrize(
    ("enlace", "motivo"),
    [
        ("mira este vídeo de la cremallera", "no es un enlace"),
        ("www.youtube.com/watch?v=" + ID, "no es un enlace"),
        ("https://www.youtube.com/playlist?list=PL0123456789", "es una lista de reproducción"),
        ("https://www.youtube.com/@uncanal", "es un canal"),
        ("https://www.youtube.com/c/uncanal", "es un canal"),
        ("https://www.youtube.com/feed/trending", "no es el enlace de un vídeo de YouTube"),
        ("https://vimeo.com/123456", "no es un enlace de YouTube, sino de vimeo.com"),
        ("https://www.youtube.com/watch?v=corto", "no lleva un id de vídeo válido"),
    ],
)
def test_lo_que_no_es_un_video_se_niega_sin_salir_a_la_red(red, capsys, enlace, motivo):
    assert mira_video.main([enlace]) == 2
    salida = capsys.readouterr().out
    assert salida.startswith("NO: ") and motivo in salida
    assert red.pedidas == []


def test_sin_nada_que_mirar_se_niega(red, capsys):
    assert mira_video.main([]) == 2
    assert capsys.readouterr().out.startswith("NO: no hay nada que mirar")


@pytest.mark.parametrize(
    ("codigo", "motivo"),
    [
        (404, "no existe o es privado"),
        (400, "no existe (oEmbed responde 400)"),
        (401, "no deja incrustarse"),
        (302, "redirección"),
        (500, "responde 500"),
    ],
)
def test_un_video_que_oembed_no_da_se_niega_y_sugiere_capturas(red, capsys, tmp_path, codigo, motivo):
    red.respuestas = {mira_video.OEMBED: codigo}
    assert mira_video.main([f"https://youtu.be/{ID}", "--salida", str(tmp_path / "s")]) == 2
    salida = capsys.readouterr().out
    assert salida.startswith("NO: ") and motivo in salida and "--capturas" in salida
    assert len(red.pedidas) == 1 and not (tmp_path / "s").exists()


def test_sin_red_se_niega_con_su_motivo(monkeypatch, capsys, tmp_path):
    def sin_red(peticion, timeout):
        raise urllib.error.URLError("getaddrinfo failed")

    monkeypatch.setattr(mira_video, "_ABRE", sin_red)
    assert mira_video.main([f"https://youtu.be/{ID}", "--salida", str(tmp_path)]) == 2
    assert "no se pudo hablar con oEmbed" in capsys.readouterr().out


def test_el_enlace_deja_la_hoja_la_miniatura_y_los_datos_en_su_carpeta(red, capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(mira_video, "EXPERIMENTOS_DIR", tmp_path)
    red.respuestas = {mira_video.OEMBED: _oembed(), MINIATURA: _jpeg()}
    assert mira_video.main([f"https://www.youtube.com/watch?v={ID}&list=PL0123456789"]) == 0
    carpeta = tmp_path / "formatos" / ID
    assert {p.name for p in carpeta.iterdir()} == {"hoja.jpg", "miniatura.jpg", "video.json", "pagina.html"}
    datos = json.loads((carpeta / "video.json").read_text(encoding="utf-8"))
    assert (datos["titulo"], datos["canal"], datos["enlace"]) == (
        "Me at the zoo",
        "jawed",
        f"https://www.youtube.com/watch?v={ID}",
    )
    assert [i["procedencia"].startswith("miniatura de YouTube") for i in datos["imagenes"]] == [True]
    # Solo dos peticiones: oEmbed, con el enlace del vídeo y sin la lista, y la miniatura.
    assert red.pedidas == [
        f"{mira_video.OEMBED}?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D{ID}&format=json",
        MINIATURA,
    ]
    assert capsys.readouterr().out.startswith("[OK] 1 imagen(es) que mirar de «Me at the zoo» (jawed)")


def test_el_titulo_y_el_canal_van_escapados_en_la_pagina(red, tmp_path):
    red.respuestas = {
        mira_video.OEMBED: _oembed(title="<script>alert(1)</script>", author_name='"><img src=x onerror=alert(2)>'),
        MINIATURA: _jpeg(),
    }
    assert mira_video.main([f"https://youtu.be/{ID}", "--salida", str(tmp_path)]) == 0
    pagina = (tmp_path / "pagina.html").read_text(encoding="utf-8")
    assert "<script>" not in pagina and "<img src=x" not in pagina
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in pagina


def test_una_miniatura_de_otro_host_no_se_pide(red, capsys, tmp_path):
    """Control negativo: la `thumbnail_url` es dato de terceros. Sin capturas no queda nada que mirar."""
    red.respuestas = {mira_video.OEMBED: _oembed(thumbnail_url="https://otra.web/espia.jpg")}
    assert mira_video.main([f"https://youtu.be/{ID}", "--salida", str(tmp_path)]) == 2
    salida = capsys.readouterr().out
    assert salida.startswith("NO: no hay ninguna imagen que mirar") and "su host no es i.ytimg.com" in salida
    assert all(not url.startswith("https://otra.web") for url in red.pedidas)

    # Con capturas, se sigue sin la miniatura y queda escrito por qué.
    red.pedidas.clear()
    assert mira_video.main([f"https://youtu.be/{ID}", "--capturas", _captura(tmp_path), "--salida", str(tmp_path)]) == 0
    datos = json.loads((tmp_path / "video.json").read_text(encoding="utf-8"))
    assert "su host no es i.ytimg.com" in datos["miniatura_no_bajada"]
    assert [i["procedencia"] for i in datos["imagenes"]] == ["captura 1 del usuario"]
    assert len(red.pedidas) == 1


def test_una_miniatura_que_no_es_una_imagen_no_se_guarda(red, tmp_path):
    red.respuestas = {mira_video.OEMBED: _oembed(), MINIATURA: b"<html>no soy una imagen</html>"}
    assert mira_video.main([f"https://youtu.be/{ID}", "--capturas", _captura(tmp_path), "--salida", str(tmp_path)]) == 0
    assert not (tmp_path / "miniatura.jpg").exists()
    assert (
        "no se pudo bajar" in json.loads((tmp_path / "video.json").read_text(encoding="utf-8"))["miniatura_no_bajada"]
    )


def test_una_redireccion_no_se_sigue():
    """El manejador de la orden no da una petición nueva para la URL de la redirección; el de serie sí (control)."""
    peticion = urllib.request.Request(MINIATURA)
    args = (peticion, None, 302, "Found", {}, "https://otra.web/")
    assert mira_video._SinRedirecciones().redirect_request(*args) is None
    assert urllib.request.HTTPRedirectHandler().redirect_request(*args).full_url == "https://otra.web/"


def test_las_capturas_sin_enlace_no_salen_a_la_red(red, tmp_path):
    capturas = [_captura(tmp_path, f"c{n}.png") for n in range(3)]
    assert mira_video.main(["--capturas", *capturas, "--salida", str(tmp_path / "s")]) == 0
    datos = json.loads((tmp_path / "s" / "video.json").read_text(encoding="utf-8"))
    assert datos["enlace"] is None and len(datos["imagenes"]) == 3 and red.pedidas == []


def test_una_captura_que_no_existe_o_no_es_imagen_se_niega(red, capsys, tmp_path):
    texto = tmp_path / "nota.png"
    texto.write_text("no soy una imagen", encoding="utf-8")
    for captura in (str(tmp_path / "no-esta.png"), str(texto)):
        assert mira_video.main(["--capturas", captura]) == 2
        assert "no existe o no es una imagen" in capsys.readouterr().out
    assert red.pedidas == []


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sin ffmpeg en el PATH")
def test_el_video_del_usuario_da_ocho_fotogramas_repartidos(red, capsys, tmp_path):
    video = tmp_path / "corto.mp4"
    orden = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=4:size=320x180:rate=10",
             "-pix_fmt", "yuv420p", str(video)]  # fmt: skip
    subprocess.run(orden, check=True, capture_output=True, timeout=60)
    assert mira_video.main(["--video", str(video), "--salida", str(tmp_path / "s")]) == 0
    datos = json.loads((tmp_path / "s" / "video.json").read_text(encoding="utf-8"))
    segundos = [float(i["procedencia"].split("segundo ")[1].split(",")[0]) for i in datos["imagenes"]]
    assert segundos == [0.25, 0.75, 1.25, 1.75, 2.25, 2.75, 3.25, 3.75]
    assert sorted(p.name for p in (tmp_path / "s").glob("fotograma-*.jpg")) == [
        f"fotograma-0{n}.jpg" for n in range(1, 9)
    ]
    assert capsys.readouterr().out.startswith("[OK] 8 imagen(es) que mirar: ")

    # Control negativo: un fichero que no es un vídeo se niega antes de hacer nada.
    falso = tmp_path / "falso.mp4"
    falso.write_text("no soy un vídeo", encoding="utf-8")
    assert mira_video.main(["--video", str(falso), "--salida", str(tmp_path / "f")]) == 2
    assert "no es un vídeo que ffprobe sepa leer" in capsys.readouterr().out
    assert not (tmp_path / "f").exists()
