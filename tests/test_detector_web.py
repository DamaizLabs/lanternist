"""El detector de la marca en una página local (OC1.13): el servidor, sin GPU y con el trabajador simulado.

Cada prueba lleva su control, para que sepa fallar:

- la respuesta: el veredicto es el de `marca_ia.veredicto`, línea a línea, con el informe firmado; sin marca, «not
  marked» con su salvedad;
- el token y el `Host`: sin ellos, 403 y el detector no se entera; con ellos, 200;
- el tope: lo que lo pasa se niega sin leer el cuerpo; lo que cabe, entra;
- la carpeta temporal: se borra al acabar, vaya bien, falle el detector o no se pueda leer el fichero;
- un fichero que no es un medio se niega con el motivo de ffprobe, sin llegar al detector;
- un fallo del detector es «not checked», nunca «not marked», y también un fichero sin ninguna capa que mirar (un
  `.srt`), que sí trae su veredicto;
- una detección cada vez (la GPU de 8 GB no se reparte);
- el nombre del fichero no sale de su carpeta;
- solo escucha en 127.0.0.1;
- la página no carga nada de fuera.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from lib import config, marca_ia
from lib.escena import render

sys.path.insert(0, str(config.BASE_DIR / "scripts"))
import detector_web  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffprobe") is None, reason="sin ffprobe en el PATH")

MARCADO = {
    "file": "final.png",
    "sha256": "a" * 64,
    "c2pa": {
        "supported": True,
        "manifest": True,
        "state": "Valid",
        "failures": ["signingCredential.untrusted"],
        "generator": "Lanternist 2.0.0-rc.1",
        "signer": "Lanternist local signer",
        "ai": True,
        "error": None,
    },
    "image": {"bits": 256, "matches": 256, "p_value": 8.6e-78, "frames": 1},
    "audio": None,
}
SIN_MARCA = {
    "file": "final.png",
    "sha256": "b" * 64,
    "c2pa": {"supported": True, "manifest": False},
    "image": {"bits": 256, "matches": 117, "p_value": 0.92, "frames": 1},
    "audio": None,
}
INFORME = '{"report": {"verdict": "..."}, "signature": {"alg": "ES256"}}\n'


@pytest.fixture
def png(tmp_path) -> bytes:
    """Una imagen de verdad, que ffprobe lee."""
    ruta = tmp_path / "muestra.png"
    Image.new("RGB", (32, 32), (200, 120, 40)).save(ruta)
    return ruta.read_bytes()


@pytest.fixture
def srv(tmp_path, monkeypatch):
    """El servidor en un hilo, con el trabajador simulado y la carpeta temporal del sistema en `tmp_path/temporal`."""
    monkeypatch.setattr(render, "trabajos_de_gpu_en_marcha", lambda: [])  # sin preguntar al nvidia-smi de verdad
    temporal = tmp_path / "temporal"
    temporal.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temporal))
    visto = {"llamadas": 0, "codigo": 0, "deteccion": MARCADO, "espera": 0.0, "a_la_vez": 0, "max_a_la_vez": 0}

    def lanza(trabajo, resultado, log, *, gpu):
        """Hace lo que el trabajador de verdad: lee el trabajo, escribe el informe firmado y el resultado."""
        job = json.loads(Path(trabajo).read_text(encoding="utf-8"))
        visto["llamadas"] += 1
        visto["a_la_vez"] += 1
        visto["max_a_la_vez"] = max(visto["max_a_la_vez"], visto["a_la_vez"])
        visto.update(
            job=job, origen_en_temporal=Path(job["origen"]).is_file() and temporal in Path(job["origen"]).parents
        )
        time.sleep(visto["espera"])
        visto["a_la_vez"] -= 1
        # Como el log del trabajador de verdad con una imagen falsa: la traza acaba en el error de Pillow, que
        # escribe la ruta como un repr.
        traza = "Traceback (most recent call last):\n  ...\nPIL.UnidentifiedImageError: cannot identify image "
        Path(log).write_text(traza + f"file {job['origen']!r}\n", encoding="utf-8")
        if visto["codigo"]:
            return visto["codigo"]
        Path(job["informe"]).write_text(INFORME, encoding="utf-8")
        deteccion = {**visto["deteccion"], "file": Path(job["origen"]).name}
        Path(resultado).write_text(json.dumps({"deteccion": deteccion}), encoding="utf-8")
        return 0

    servidor = detector_web.Servidor(lanza=lanza)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    yield {"s": servidor, "visto": visto, "temporal": temporal}
    servidor.shutdown()
    servidor.server_close()


def _pide(s, metodo: str, ruta: str, cuerpo: bytes | None = None, *, token=None, host=None, nombre="final.png"):
    """Una petición como las de la página: el `Host` de 127.0.0.1, el token de la sesión y el nombre del fichero."""
    conexion = http.client.HTTPConnection("127.0.0.1", s.server_port, timeout=30)
    cabeceras = {"Host": host or f"127.0.0.1:{s.server_port}"}
    if metodo == "POST":
        cabeceras["X-Lanternist-Token"] = s.token if token is None else token
        cabeceras["X-File-Name"] = nombre
    conexion.request(metodo, ruta, body=cuerpo, headers=cabeceras)
    respuesta = conexion.getresponse()
    datos = respuesta.read()
    conexion.close()
    return respuesta, datos


def _detecta(s, cuerpo: bytes, **k):
    respuesta, datos = _pide(s, "POST", "/detect", cuerpo, **k)
    return respuesta.status, json.loads(datos)


# ------------------------------------------------------------------------------------------ la respuesta
def test_el_veredicto_es_el_del_detector_linea_a_linea_con_su_informe_firmado(srv, png):
    estado, datos = _detecta(srv["s"], png)
    assert estado == 200 and datos["marked"] is True
    assert datos["lines"] == marca_ia.veredicto(MARCADO).splitlines()
    assert datos["lines"][-1].startswith("Verdict: MARKED")
    assert datos["report"] == INFORME and datos["report_name"] == "final.lanternist-report.json"
    job = srv["visto"]["job"]
    assert job["op"] == "detecta" and Path(job["informe"]).parent == Path(job["origen"]).parent
    # Control: el mismo fichero sin marca da «not marked», con la salvedad de que eso no prueba nada.
    srv["visto"]["deteccion"] = SIN_MARCA
    estado, datos = _detecta(srv["s"], png)
    assert estado == 200 and datos["marked"] is False
    assert datos["lines"] == marca_ia.veredicto(SIN_MARCA).splitlines()
    assert datos["lines"][-1].startswith("Verdict: NOT MARKED") and "does not prove" in datos["lines"][-1]


# ------------------------------------------------------------------------------------------ el token y el Host
def test_la_pagina_pide_el_token_de_la_sesion_y_el_host_de_127_0_0_1(srv):
    s = srv["s"]
    puerto = s.server_port
    for ruta, host in [
        ("/", None),  # sin token
        ("/?token=otro", None),
        (f"/?token={s.token}x", None),
        (f"/?token={s.token}", f"rebinding.example:{puerto}"),  # DNS rebinding: otro nombre que apunta a 127.0.0.1
        (f"/?token={s.token}", f"localhost:{puerto}"),
        (f"/?token={s.token}", "127.0.0.1:1"),
    ]:
        respuesta, _ = _pide(s, "GET", ruta, host=host)
        assert respuesta.status == 403, (ruta, host)
    # Control: con los dos, la página.
    respuesta, datos = _pide(s, "GET", f"/?token={s.token}")
    assert respuesta.status == 200 and b"Lanternist AI mark detector" in datos


def test_sin_el_token_o_con_otro_host_el_fichero_no_llega_al_detector(srv, png):
    s = srv["s"]
    assert _detecta(s, png, token="")[0] == 403
    assert _detecta(s, png, token="no-es-el-token")[0] == 403
    assert _detecta(s, png, host=f"rebinding.example:{s.server_port}")[0] == 403
    assert srv["visto"]["llamadas"] == 0 and not any(srv["temporal"].iterdir())
    # Control: con los dos, sí llega.
    assert _detecta(s, png)[0] == 200 and srv["visto"]["llamadas"] == 1


# ------------------------------------------------------------------------------------------ el tope
def _solo_cabeceras(s, longitud: int) -> str:
    """Un POST que declara `longitud` bytes y no manda ninguno: si el servidor intentara leerlos, no contestaría."""
    with socket.create_connection(("127.0.0.1", s.server_port), timeout=10) as conexion:
        cabeceras = [
            "POST /detect HTTP/1.1",
            f"Host: 127.0.0.1:{s.server_port}",
            f"X-Lanternist-Token: {s.token}",
            "X-File-Name: grande.mp4",
            f"Content-Length: {longitud}",
        ]
        conexion.sendall(("\r\n".join(cabeceras) + "\r\n\r\n").encode())
        respuesta = b""
        while trozo := conexion.recv(65536):
            respuesta += trozo
    return respuesta.decode()


def test_lo_que_pasa_del_tope_se_niega_sin_leerlo(srv, png):
    s = srv["s"]
    respuesta = _solo_cabeceras(s, 3 * 1024**3)
    assert respuesta.startswith("HTTP/1.0 413") and "more than the limit of 2 GB" in respuesta
    assert srv["visto"]["llamadas"] == 0 and not any(srv["temporal"].iterdir())
    # Un byte por encima del tope, tampoco; con el tope justo, la imagen entra (el control).
    s.tope = len(png) - 1
    assert _solo_cabeceras(s, len(png)).startswith("HTTP/1.0 413") and srv["visto"]["llamadas"] == 0
    s.tope = len(png)
    assert _detecta(s, png)[0] == 200 and srv["visto"]["llamadas"] == 1


# ------------------------------------------------------------------------------------------ la carpeta temporal
def test_la_carpeta_temporal_se_borra_vaya_bien_falle_el_detector_o_no_se_pueda_leer(srv, png):
    temporal = srv["temporal"]
    assert _detecta(srv["s"], png)[0] == 200
    # El control de que «vacía» no es trivial: mientras el detector miraba, el fichero estaba ahí dentro.
    assert srv["visto"]["origen_en_temporal"] is True
    assert not any(temporal.iterdir()), "vaya bien"
    srv["visto"]["codigo"] = 1
    assert _detecta(srv["s"], png)[0] == 500
    assert srv["visto"]["origen_en_temporal"] is True and not any(temporal.iterdir()), "falle el detector"
    assert _detecta(srv["s"], b"no es un medio", nombre="notas.md")[0] == 422
    assert not any(temporal.iterdir()), "o no se pueda leer"


# ------------------------------------------------------------------------------------------ los negativos
def test_un_fichero_que_no_es_un_medio_se_niega_con_su_motivo(srv, png):
    for nombre in ("notas.md", "falso.mp4", "falso.wav"):
        estado, datos = _detecta(srv["s"], b"esto es texto, no un medio\n", nombre=nombre)
        assert estado == 422 and "lines" not in datos, nombre
        assert datos["error"].startswith(f"{nombre} is not a video, an image or an audio file that can be read (")
        assert str(srv["temporal"]) not in datos["error"], "el motivo no lleva la ruta temporal"
    assert srv["visto"]["llamadas"] == 0
    # Control: una imagen de verdad sí llega al detector.
    assert _detecta(srv["s"], png)[0] == 200 and srv["visto"]["llamadas"] == 1


def test_si_el_detector_falla_es_not_checked_y_nunca_not_marked(srv, png):
    srv["visto"]["codigo"] = 1
    estado, datos = _detecta(srv["s"], png)
    assert estado == 500 and "marked" not in datos and "lines" not in datos
    # Una imagen falsa pasa ffprobe y la niega el trabajador: su motivo es la última línea de su error, sin la ruta.
    assert datos["error"].startswith("the detector could not look at final.png (PIL.UnidentifiedImageError: cannot ")
    assert "cannot identify image file 'final.png')" in datos["error"] and "lanternist-detector-" not in datos["error"]
    # Control: el mismo fichero, con el detector bien, da su veredicto.
    srv["visto"]["codigo"] = 0
    estado, datos = _detecta(srv["s"], png)
    assert estado == 200 and datos["marked"] is True


def test_un_fichero_sin_ninguna_capa_que_mirar_es_not_checked_con_su_veredicto(srv):
    """Un `.srt` pasa ffprobe, pero no tiene imagen ni sonido y no admite C2PA: la página lo da como no comprobado."""
    srv["visto"]["deteccion"] = {
        "file": "subtitulos.en.srt",
        "sha256": "c" * 64,
        "c2pa": {"supported": False, "manifest": False},
        "image": None,
        "signpost": None,
        "audio": None,
    }
    srt = b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"
    estado, datos = _detecta(srv["s"], srt, nombre="subtitulos.en.srt")
    assert estado == 200 and datos["marked"] is False and datos["checked"] is False
    assert datos["lines"][-1].startswith("Verdict: NOT CHECKED") and srv["visto"]["llamadas"] == 1
    # Control: con una capa que mirar, «not marked».
    srv["visto"]["deteccion"] = SIN_MARCA
    estado, datos = _detecta(srv["s"], srt, nombre="subtitulos.en.srt")
    assert datos["checked"] is True and datos["lines"][-1].startswith("Verdict: NOT MARKED")


def test_la_pagina_pinta_el_not_checked_como_no_comprobado(srv):
    respuesta, datos = _pide(srv["s"], "GET", f"/?token={srv['s'].token}")
    html = datos.decode("utf-8")
    assert 'data.marked ? "marked" : data.checked ? "notmarked" : "notchecked"' in html and ".notchecked {" in html


def test_una_deteccion_cada_vez(srv, png):
    """Dos ficheros a la vez: el segundo espera a que acabe el primero. El control quita el cerrojo y los ve juntos."""

    def dos_a_la_vez():
        srv["visto"].update(espera=0.5, max_a_la_vez=0)
        hilos = [threading.Thread(target=_detecta, args=(srv["s"], png)) for _ in range(2)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()
        return srv["visto"]["max_a_la_vez"]

    assert dos_a_la_vez() == 1
    srv["s"].una_cada_vez = contextlib.nullcontext()
    assert dos_a_la_vez() == 2


def test_el_nombre_del_fichero_no_sale_de_su_carpeta(srv, png, tmp_path):
    assert detector_web.nombre_seguro("..\\..\\escapa.png") == "escapa.png"
    assert detector_web.nombre_seguro("../../escapa.png") == "escapa.png"
    assert detector_web.nombre_seguro("D:/descargas/final.mp4") == "final.mp4"
    assert detector_web.nombre_seguro("a:b*c?.png") == "a_b_c_.png"
    assert detector_web.nombre_seguro("con.png") == "_con.png" and detector_web.nombre_seguro("NUL") == "_NUL"
    assert detector_web.nombre_seguro("..") == "file" and detector_web.nombre_seguro("") == "file"
    assert detector_web.nombre_seguro("lámina 3 (copia).png") == "lámina 3 (copia).png", "el resto, tal cual"
    estado, datos = _detecta(srv["s"], png, nombre="..%2F..%2Fescapa.png")
    assert estado == 200 and datos["lines"][0].startswith("File: escapa.png")
    assert not list(tmp_path.rglob("escapa.png"))


# ------------------------------------------------------------------------------------------ la red
def _llega(ip: str, puerto: int) -> bool:
    try:
        socket.create_connection((ip, puerto), timeout=3).close()
    except OSError:
        return False
    return True


def _ip_de_la_red() -> str | None:
    """La IP de este PC en su red, sin mandar nada: un socket UDP «conectado» solo elige la interfaz."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.connect(("192.0.2.1", 9))  # TEST-NET-1: una dirección que no existe
            ip = udp.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") or ip == "0.0.0.0" else ip


def test_solo_escucha_en_127_0_0_1(srv):
    """Escuchando en todas las interfaces (0.0.0.0), se llegaría también por 127.0.0.2 y por la IP de la red.

    El control escucha en 127.0.0.2, y no en 0.0.0.0, para no abrir un puerto a la red ni el aviso del cortafuegos de
    Windows al pasar la suite.
    """
    s = srv["s"]
    assert s.server_address[0] == "127.0.0.1"
    assert _llega("127.0.0.1", s.server_port)
    assert not _llega("127.0.0.2", s.server_port)
    ip = _ip_de_la_red()
    assert ip is None or not _llega(ip, s.server_port)
    # Control: a lo que sí escucha en 127.0.0.2 se llega por ahí.
    with socket.socket() as otro:
        otro.bind(("127.0.0.2", 0))
        otro.listen()
        assert _llega("127.0.0.2", otro.getsockname()[1])


def _carga_de_fuera(html: str) -> list[str]:
    return re.findall(r"https?://|//[a-z0-9.-]+\.[a-z]{2,}/|\bsrc\s*=|@import|\burl\(", html, re.I)


def test_la_pagina_no_carga_nada_de_fuera(srv):
    s = srv["s"]
    respuesta, datos = _pide(s, "GET", f"/?token={s.token}")
    html = datos.decode("utf-8")
    assert _carga_de_fuera(html) == []
    csp = respuesta.getheader("Content-Security-Policy")
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    assert html.count(f'nonce="{nonce}"') == 2, "el estilo y el código, los únicos que la CSP deja correr"
    # El marcador entero, no «__» suelto: el token y el nonce son base64 de URL y a veces lo traen (R1 de la revisión).
    assert s.token in html and not re.search(r"__(NONCE|TOKEN|TOPE_BYTES|TOPE)__", html), "sin marcadores sin rellenar"
    # Control: la comprobación ve una página que carga algo de fuera.
    assert _carga_de_fuera(html.replace("</head>", '<script src="https://cdn.example/x.js"></script></head>'))


def test_al_arrancar_se_barren_solo_las_carpetas_viejas(tmp_path):
    vieja = tmp_path / f"{detector_web.PREFIJO_TEMPORAL}vieja"
    nueva = tmp_path / f"{detector_web.PREFIJO_TEMPORAL}nueva"
    ajena = tmp_path / "otra-cosa"
    for carpeta in (vieja, nueva, ajena):
        carpeta.mkdir()
    hace_un_dia = time.time() - 24 * 3600
    os.utime(vieja, (hace_un_dia, hace_un_dia))
    os.utime(ajena, (hace_un_dia, hace_un_dia))
    # La reciente, de hace un minuto: recién creada, su mtime puede ir por delante de time.time() y el control con
    # cero horas fallaba a veces.
    hace_un_minuto = time.time() - 60
    os.utime(nueva, (hace_un_minuto, hace_un_minuto))
    detector_web.barre_temporales(tmp_path)
    # La de otra ventana abierta (reciente) se queda, y lo que no es del detector no se toca.
    assert not vieja.exists() and nueva.exists() and ajena.exists()
    # Control: con un umbral de cero horas, la reciente también se va.
    detector_web.barre_temporales(tmp_path, horas=0)
    assert not nueva.exists()
