r"""El detector de la marca de IA en una página local, para quien no usa un terminal (OC1.13; sub-medida 2.1.2 del
Código de buenas prácticas).

    detector.cmd                                     # doble clic: arranca el servidor y abre la página
    .venv\Scripts\python scripts\detector_web.py     # lo mismo desde un terminal

Arranca un servidor web pequeño, solo con la biblioteca estándar, y abre su página en el navegador. Quien la usa
arrastra un vídeo, una imagen o un audio, lee el veredicto en inglés llano, con una línea por capa, y puede bajar el
resultado firmado. El detector es el de `scripts/detecta_marca.py` (`lib/marca_ia.py → detecta` y `veredicto`): la
página enseña lo que dicen, sin lógica propia.

**Nada sale del PC.**

- El servidor solo escucha en `127.0.0.1`, en un puerto libre que elige el sistema.
- Solo contesta a las peticiones que traen el `Host` de esa dirección, contra el *DNS rebinding* (una web de fuera
  cuyo nombre apunta a 127.0.0.1), y el token aleatorio de la sesión, que solo conoce la página que abrió, contra otra
  web abierta en el mismo navegador.
- La página lleva dentro su estilo y su código, y su CSP (`default-src 'none'`) no deja al navegador cargar ni mandar
  nada a otro sitio.
- El fichero va a una carpeta temporal del sistema, que se borra al acabar, también si el detector falla. El resultado
  firmado vuelve a la página en la misma respuesta y no se queda en disco.

**Una detección cada vez**: la GPU tiene 8 GB y no se reparte. `detecta` ya decide si va en la GPU o en la CPU.

Cerrar la ventana de `detector.cmd` para el servidor.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import marca_ia  # noqa: E402

HOST = "127.0.0.1"
# El tope del fichero. Un minuto de `final.mp4` pesa unos 86 MB (el episodio de ejemplo: 78 MB en 54,5 s), así que
# caben unos 23 minutos; lo que baja de YouTube pesa mucho menos. La página lo dice y lo comprueba antes de mandar nada.
TOPE_BYTES = 2 * 1024**3
PREFIJO_TEMPORAL = "lanternist-detector-"
# Los nombres que Windows reserva a un dispositivo: un fichero con ese nombre no se escribiría en la carpeta.
RESERVADOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}


def nombre_seguro(nombre: str) -> str:
    """El nombre del fichero subido, sin carpetas ni caracteres que Windows no admite.

    Conserva la extensión, que dice al detector si es una imagen, y el resto del nombre, que el informe firmado guarda
    como `file`.
    """
    base = re.sub(r"[^\w.()\- ]", "_", nombre.replace("\\", "/").rsplit("/", 1)[-1]).strip(" .")
    ruta = Path(base or "file")
    raiz = ruta.stem[:100]
    if raiz.split(".")[0].upper() in RESERVADOS:
        raiz = f"_{raiz}"
    return raiz + ruta.suffix[:12]


def motivo_si_no_se_lee(ruta: Path) -> str | None:
    """Por qué el detector no puede leer `ruta`, en inglés y detrás de su nombre, o None si ffprobe la lee.

    El trabajador lee los vídeos y los audios con ffprobe y falla con una traza si no puede: aquí se pregunta antes,
    para negar el fichero con el motivo que da ffprobe. Una imagen la lee Pillow en el trabajador, y ffprobe abre sin
    quejarse un texto llamado `.png`: esa la niega el trabajador, y su motivo es la última línea de su error.
    """
    from lib.config import entorno_para_terceros

    try:
        hecho = subprocess.run(
            ["ffprobe", "-v", "error", str(ruta)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=entorno_para_terceros(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"could not be read: ffprobe, the program that reads it, did not run ({error})"
    if hecho.returncode == 0:
        return None
    return f"is not a video, an image or an audio file that can be read ({_ultima_linea(hecho.stderr, ruta.parent)})"


def _ultima_linea(texto: str, carpeta: Path) -> str:
    """La última línea de un error (la de la excepción, en una traza), sin la ruta de la carpeta temporal: tampoco la
    que escribe un `repr`, con las barras dobladas."""
    lineas = [linea.strip() for linea in texto.splitlines() if linea.strip()]
    ultima = lineas[-1] if lineas else "no detail"
    for prefijo in (f"{carpeta}{os.sep}", f"{carpeta}{os.sep}".replace("\\", "\\\\")):
        ultima = ultima.replace(prefijo, "")
    return ultima


def _en_gb(n: int) -> str:
    return f"{n / 1024**3:.3g} GB"


def _recibe(entrada, ruta: Path, longitud: int) -> bool:
    """Copia a `ruta` los `longitud` bytes del cuerpo de la petición, a trozos. False si la conexión se corta antes."""
    with open(ruta, "wb") as f:
        while longitud:
            trozo = entrada.read(min(longitud, 1 << 20))
            if not trozo:
                return False
            f.write(trozo)
            longitud -= len(trozo)
    return True


class _Peticion(BaseHTTPRequestHandler):
    server: Servidor
    # Un socket que se calla (la preconexión de un navegador) suelta su hilo pasado este tiempo.
    timeout = 60

    def log_message(self, formato, *args) -> None:
        """La consola es de quien usa el detector: solo dice qué fichero se ha comprobado (`_comprueba`)."""

    def _permitida(self, token: str | None) -> bool:
        host_local = self.headers.get("Host") == f"{HOST}:{self.server.server_port}"
        return host_local and hmac.compare_digest((token or "").encode(), self.server.token.encode())

    def _responde(self, estado: int, tipo: str, cuerpo: bytes, extra: dict[str, str] | None = None) -> None:
        self.send_response(estado)
        cabeceras = {
            "Content-Type": tipo,
            "Content-Length": str(len(cuerpo)),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            **(extra or {}),
        }
        for clave, valor in cabeceras.items():
            self.send_header(clave, valor)
        self.end_headers()
        self.wfile.write(cuerpo)

    def _json(self, estado: int, datos: dict) -> None:
        self._responde(estado, "application/json; charset=utf-8", json.dumps(datos, ensure_ascii=False).encode())

    def do_GET(self) -> None:
        partes = urlsplit(self.path)
        if not self._permitida((parse_qs(partes.query).get("token") or [None])[0]):
            texto = "Forbidden. Open the detector with detector.cmd: its address changes every time it starts.\n"
            return self._responde(403, "text/plain; charset=utf-8", texto.encode())
        if partes.path != "/":
            return self._responde(404, "text/plain; charset=utf-8", b"Not found.\n")
        nonce = secrets.token_urlsafe(16)
        csp = (
            f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        pagina = (
            PAGINA.replace("__NONCE__", nonce)
            .replace("__TOKEN__", self.server.token)
            .replace("__TOPE_BYTES__", str(self.server.tope))
            .replace("__TOPE__", _en_gb(self.server.tope))
        )
        self._responde(200, "text/html; charset=utf-8", pagina.encode(), {"Content-Security-Policy": csp})

    def do_POST(self) -> None:
        if not self._permitida(self.headers.get("X-Lanternist-Token")):
            return self._json(403, {"error": "forbidden. Open the detector again with detector.cmd."})
        if self.path != "/detect":
            return self._json(404, {"error": "not found."})
        try:
            longitud = int(self.headers.get("Content-Length", ""))
        except ValueError:
            longitud = -1
        if longitud < 0:
            return self._json(411, {"error": "the request did not say how big the file is."})
        if longitud > self.server.tope:
            # Se contesta sin leer el cuerpo: lo que pasa del tope no llega al disco.
            return self._json(
                413, {"error": f"the file is {_en_gb(longitud)}, more than the limit of {_en_gb(self.server.tope)}."}
            )
        nombre = nombre_seguro(unquote(self.headers.get("X-File-Name") or ""))
        # La carpeta se borra al salir del bloque: vaya bien, falle el detector o se corte la conexión.
        with tempfile.TemporaryDirectory(prefix=PREFIJO_TEMPORAL) as carpeta:
            ruta = Path(carpeta) / nombre
            if not _recibe(self.rfile, ruta, longitud):
                return
            estado, datos = self._comprueba(Path(carpeta), ruta)
        self._json(estado, datos)

    def _comprueba(self, carpeta: Path, ruta: Path) -> tuple[int, dict]:
        motivo = motivo_si_no_se_lee(ruta)
        if motivo:
            print(f"Not checked: {ruta.name} {motivo}", flush=True)
            return 422, {"error": f"{ruta.name} {motivo}."}
        informe = carpeta / "report.json"
        with self.server.una_cada_vez:
            try:
                resultado = marca_ia.detecta(
                    ruta, informe=informe, trabajo=carpeta / "trabajo", lanza=self.server.lanza
                )
            # Como detecta_marca.py: un fallo cualquiera es «no he podido mirar», nunca «no marcado». El error entero,
            # con la cola del log del trabajador, que se borra con la carpeta, va a la consola; a la página, su última
            # línea, que en una traza es la excepción: de una imagen falsa, «cannot identify image file».
            except Exception as error:  # noqa: BLE001
                texto = str(error) if isinstance(error, marca_ia.ErrorDeMarca) else f"{type(error).__name__}: {error}"
                print(f"Not checked: {ruta.name}: {texto}", flush=True)
                return 500, {
                    "error": f"the detector could not look at {ruta.name} ({_ultima_linea(texto, carpeta)}). "
                    "The full error is in the detector's window."
                }
        marcado = marca_ia.de_lanternist(resultado)
        # Un fichero sin ninguna capa que mirar (un `.srt`) es «no comprobado», como un fallo, pero con su veredicto.
        mirado = not marca_ia.sin_mirar(resultado)
        print(f"Checked {ruta.name}: {'MARKED' if marcado else 'NOT MARKED' if mirado else 'NOT CHECKED'}", flush=True)
        return 200, {
            "marked": marcado,
            "checked": mirado,
            "lines": marca_ia.veredicto(resultado).splitlines(),
            "report": informe.read_text(encoding="utf-8"),
            "report_name": f"{ruta.stem}.lanternist-report.json",
        }


class Servidor(ThreadingHTTPServer):
    """El servidor de la página, en 127.0.0.1 y un puerto libre, con el token de la sesión.

    `lanza` sustituye al trabajador en las pruebas sin GPU (como en `marca_ia.detecta`); `tope` es el tamaño máximo del
    fichero, en bytes.
    """

    daemon_threads = True
    # En Windows, SO_REUSEADDR deja que otro proceso se ponga a escuchar en el mismo puerto: aquí no hace falta.
    allow_reuse_address = False

    def __init__(self, *, lanza=None, tope: int = TOPE_BYTES):
        super().__init__((HOST, 0), _Peticion)
        self.token = secrets.token_urlsafe(32)
        self.lanza = lanza
        self.tope = tope
        self.una_cada_vez = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.server_port}/?token={self.token}"


def barre_temporales(carpeta: Path | None = None, horas: float = 6) -> None:
    """Borra lo que dejó una sesión cuya ventana se cerró a mitad de una detección, que no llega a borrarse sola.

    Solo las carpetas de hace más de `horas`: una más nueva puede ser de otra ventana del detector que sigue abierta
    (R2 de la revisión de OC1.13)."""
    for vieja in Path(carpeta or tempfile.gettempdir()).glob(f"{PREFIJO_TEMPORAL}*"):
        with contextlib.suppress(OSError):
            if time.time() - vieja.stat().st_mtime > horas * 3600:
                shutil.rmtree(vieja, ignore_errors=True)


def main() -> int:
    # Como detecta_marca.py: la consola de Windows no es UTF-8, y los mensajes llevan tildes y «…».
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    barre_temporales()
    servidor = Servidor()
    print("Lanternist AI mark detector", flush=True)
    print(f"The page is opening in your browser. If it does not, open this address: {servidor.url}", flush=True)
    print("The files you check stay on this computer. Close this window to stop the detector.", flush=True)
    webbrowser.open(servidor.url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0


# La página: en inglés llano y sin nada de fuera. El nombre del fichero y el veredicto van con `textContent`, nunca
# como HTML.
PAGINA = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lanternist AI mark detector</title>
<style nonce="__NONCE__">
  body { font: 16px/1.5 system-ui, sans-serif; max-width: 46rem; margin: 2rem auto; padding: 0 1rem;
         color: #1b1b1b; background: #fafafa; }
  h1 { font-size: 1.5rem; }
  #drop { display: block; border: 2px dashed #888; border-radius: 12px; padding: 2.5rem 1rem; text-align: center;
          cursor: pointer; background: #fff; }
  #drop.over { border-color: #1a5fb4; background: #eef4fc; }
  #drop:focus-within { outline: 3px solid #1a5fb4; outline-offset: 2px; }
  #file { position: absolute; width: 1px; height: 1px; opacity: 0; }
  .verdict { font-weight: 600; padding: .75rem 1rem; border-radius: 8px; margin: 1.25rem 0 .5rem; }
  .marked { background: #e6f4ea; border-left: 6px solid #1e7e34; }
  .notmarked { background: #f1f1f1; border-left: 6px solid #6b6b6b; }
  .notchecked { background: #fdecea; border-left: 6px solid #b3261e; }
  li { margin: .4rem 0; }
  .small { color: #555; font-size: .9rem; }
  button { font: inherit; padding: .5rem 1rem; border-radius: 8px; border: 1px solid #1a5fb4; background: #1a5fb4;
           color: #fff; cursor: pointer; }
</style>
</head>
<body>
<h1>Was this file made with AI by Lanternist?</h1>
<p>Check a video, an image or an audio file for the marks that Lanternist puts in everything it makes: signed C2PA
metadata, two invisible watermarks in the picture (one says "AI", the other which detector to use) and another in the
sound.</p>
<p class="small">The file stays on this computer. This page talks only to the detector running in its own window on
this PC, and loads nothing from the internet. Close that window to stop the detector.</p>
<label id="drop" for="file">
  <input id="file" type="file" accept="video/*,image/*,audio/*">
  <strong>Drop a file here</strong>, or click to choose one.<br>
  <span class="small">One file at a time, up to __TOPE__.</span>
</label>
<div id="result" aria-live="polite"></div>
<script nonce="__NONCE__">
const TOKEN = "__TOKEN__";
const LIMIT = __TOPE_BYTES__;
const zone = document.getElementById("drop");
const input = document.getElementById("file");
const out = document.getElementById("result");

function add(tag, text, cls) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (cls) node.className = cls;
  out.appendChild(node);
  return node;
}

function show(data) {
  out.replaceChildren();
  if (data.error) {
    add("p", "NOT CHECKED: " + data.error, "verdict notchecked");
    add("p", "This is not a \\"not marked\\" result: the detector could not look at the file.", "small");
    return;
  }
  const lines = data.lines;
  add("p", lines[lines.length - 1], "verdict " + (data.marked ? "marked" : data.checked ? "notmarked" : "notchecked"));
  const list = add("ul", "");
  for (const line of lines.slice(1, -1)) {
    const item = document.createElement("li");
    item.textContent = line;
    list.appendChild(item);
  }
  add("p", lines[0], "small");
  const button = add("button", "Download the signed result (JSON)");
  button.type = "button";
  button.addEventListener("click", () => {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([data.report], { type: "application/json" }));
    link.download = data.report_name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
  });
  add("p", "The signed result records the file's SHA-256, every finding and this verdict, signed with this " +
    "installation's key, so anyone can check that it has not been edited.", "small");
}

function check(file) {
  if (!file) return;
  out.replaceChildren();
  if (file.size > LIMIT) {
    show({ error: file.name + " is bigger than the limit of __TOPE__." });
    return;
  }
  add("p", "Checking " + file.name + "… A video can take up to a minute.");
  fetch("/detect", {
    method: "POST",
    body: file,
    headers: { "X-Lanternist-Token": TOKEN, "X-File-Name": encodeURIComponent(file.name) },
  })
    .then((response) => response.json())
    .then(show)
    .catch(() => show({ error: "the detector stopped answering. Is its window still open? If not, start it " +
      "again with detector.cmd." }));
}

input.addEventListener("change", () => {
  check(input.files[0]);
  input.value = "";
});
zone.addEventListener("dragover", (event) => {
  event.preventDefault();
  zone.classList.add("over");
});
zone.addEventListener("dragleave", () => zone.classList.remove("over"));
zone.addEventListener("drop", (event) => {
  event.preventDefault();
  zone.classList.remove("over");
  check(event.dataTransfer.files[0]);
});
// Un fichero soltado fuera de la zona no hace que el navegador lo abra en vez de la página.
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
