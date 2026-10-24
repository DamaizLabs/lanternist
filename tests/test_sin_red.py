"""La guarda de red del motor de escena (`motor/sin-red.cjs`, decisión 6) corta lo que debe y deja lo local.

La CLI de HyperFrames sale a GitHub en cada orden (medido el 28-09-2026, addendum fila 199) y arranca procesos
Node hijos sin `--require` (auditoría de F6.0). Estas pruebas no necesitan internet: `127.0.0.2` es local, pero
la guarda no lo tiene por local, así que hace de destino remoto. Cada corte lleva su control: sin guarda, o sin
la herencia por NODE_OPTIONS, la misma conexión PASA — así «cortada» no puede salir de una prueba que no sabe
conectar.
"""

import os
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
GUARDA = RAIZ / "motor" / "sin-red.cjs"
SONDA = Path(__file__).parent / "sin_red" / "sonda.cjs"


def _node() -> str | None:
    encontrado = shutil.which("node")
    if encontrado:
        return encontrado
    por_defecto = Path(os.environ.get("APPDATA", "")) / "fnm" / "aliases" / "default" / "node.exe"
    return str(por_defecto) if por_defecto.exists() else None


NODE = _node()
pytestmark = pytest.mark.skipif(NODE is None, reason="no hay node en esta máquina (lo instala fnm, ver .node-version)")


@pytest.fixture(scope="module")
def servidores():
    """Un servidor TCP en 127.0.0.1 y otro en 127.0.0.2, en el mismo puerto; solo en el bucle local."""
    abiertos = []
    for host in ("127.0.0.1", "127.0.0.2"):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        abiertos.append((host, s))
    abiertos[0][1].bind(("127.0.0.1", 0))
    puerto = abiertos[0][1].getsockname()[1]
    abiertos[1][1].bind(("127.0.0.2", puerto))
    parar = threading.Event()

    def acepta(s):
        s.listen()
        s.settimeout(0.2)
        while not parar.is_set():
            try:
                c, _ = s.accept()
                # Leer la petición y dar una respuesta HTTP mínima: para `fetch`, sin ella la conexión que SÍ
                # llegó sale como error (en Windows, cerrar con datos sin leer manda un reset).
                c.settimeout(0.5)
                try:
                    c.recv(4096)
                except OSError:
                    pass
                c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                c.close()
            except OSError:
                continue

    hilos = [threading.Thread(target=acepta, args=(s,), daemon=True) for _, s in abiertos]
    for h in hilos:
        h.start()
    yield puerto
    parar.set()
    for _, s in abiertos:
        s.close()


def _sonda(modo: str, puerto: int, guarda: bool) -> str:
    entorno = {k: v for k, v in os.environ.items() if k != "NODE_OPTIONS"}
    args = [NODE] + (["--require", str(GUARDA)] if guarda else []) + [str(SONDA), modo, str(puerto)]
    r = subprocess.run(args, capture_output=True, text=True, timeout=30, env=entorno)
    return r.stdout.strip()


def test_sin_guarda_la_sonda_SI_conecta_y_por_eso_sabe_fallar(servidores):
    assert _sonda("tcp", servidores, guarda=False) == "CONECTA"
    assert _sonda("fetch", servidores, guarda=False) == "CONECTA"


def test_con_guarda_se_corta_el_destino_no_local(servidores):
    assert _sonda("tcp", servidores, guarda=True) == "CORTADA"
    assert _sonda("fetch", servidores, guarda=True) == "CORTADA"


def test_con_guarda_lo_local_pasa(servidores):
    # Es la vía del servidor con el que HyperFrames sirve la composición a Chrome.
    assert _sonda("local", servidores, guarda=True) == "CONECTA"


def test_el_hijo_que_arranca_la_CLI_hereda_la_guarda(servidores):
    # La CLI lanza `process.execPath` sin --require en cada render: sin la herencia, ese hijo salía.
    assert _sonda("hijo", servidores, guarda=True) == "CORTADA"


def test_control_sin_la_herencia_el_hijo_conecta(servidores):
    assert _sonda("hijo-sin-opciones", servidores, guarda=True) == "CONECTA"
