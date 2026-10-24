"""Proveedor de documentos: el origen de una cifra, por su URL (F7.12, fila 275).

**Qué cubre que los demás no.** El origen de una cifra de empresa es su informe anual, y el de una
cifra de un país es la nota de su oficina estadística o de su banco central. Ninguno tiene DOI ni
ISBN: son una URL. Hasta F7.12 ningún proveedor los resolvía
(la nota de proveedores del perfil de su nicho lo decía), así que una cifra de
empresa se respaldaba «con la mejor referencia que el módulo sí verifica», que no era su origen.

**Qué hace.** `resuelve("url:https://…")` descarga la URL **una vez**, sin reintentos, con el
`User-Agent` del proyecto (sin correo, como dice `base.py`) y pasando por el `LedgerLlamadas`. Lee el
HTML con la biblioteca estándar (`html.parser`) y el PDF con `pypdf`. Devuelve el título del documento
—el de `<title>` o el de los metadatos del PDF, **nunca el que propone el agente**— y el sha256 de los
bytes, que es lo que ata la confirmación del usuario a ese documento y no a otro.

**Qué no hace.**
- `busca()` no busca nada: una URL no se busca, se resuelve. Devuelve una lista vacía y lo anota en el
  ledger, para que no parezca un proveedor que no encontró resultados.
- No sigue una redirección que salga de `https`, y no acepta un `url:` que no sea `https`.
- No guarda el documento: lo lee en memoria y se queda con el texto, el título y la huella. Lo que sale
  de este PC es la petición GET de una URL pública, igual que con Crossref (decisión 6).

**SEC EDGAR pide un correo de contacto en el `User-Agent`** y este proveedor no manda el del usuario (la
regla de `base.py`). Si EDGAR responde 403, el informe se toma de la web de inversores de la empresa.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser

from lib.fuentes.base import (
    TIMEOUT_S,
    USER_AGENT,
    FuentesError,
    LedgerLlamadas,
    Proveedor,
    Referencia,
    parte_identificador,
)

NOMBRE = "documento"

# Un informe anual en PDF pesa entre 2 y 30 MB. El tope corta la lectura antes de llenar la memoria con
# una URL que no era un documento.
TOPE_DE_BYTES = 80 * 1024 * 1024

# El tope de la descarga entera. `TIMEOUT_S` vale para cada operación del socket, así que un servidor
# que suelta un byte cada 29 s no lo agotaba nunca (revisión de F7.12). 30 MB a 1 MB/s son 30 s: 120 s
# dejan margen a un informe grande sin dejar la consola colgada. Se comprueba entre lectura y lectura
# del socket (`read1`), así que lo más que puede durar es esto más un `TIMEOUT_S`.
TIEMPO_MAXIMO_S = 120
_TROZO = 1024 * 1024

# Por debajo de esto, el documento «no da texto»: un PDF escaneado o una página que pinta su contenido
# con JavaScript. Entonces la cifra se lee a mano y la confirmación del usuario es la única comprobación.
MINIMO_DE_TEXTO = 200


class _SoloHttps(urllib.request.HTTPRedirectHandler):
    """Sigue una redirección solo si sigue en `https`: la descarga no sale del canal cifrado."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise urllib.error.HTTPError(newurl, code, f"redirección fuera de https: {newurl}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_ABRIDOR = urllib.request.build_opener(_SoloHttps)


@dataclass
class Lectura:
    """Lo que se sacó de una URL: el texto de cada página, el título y la huella de los bytes."""

    url: str
    descargado_el: str
    http: int | None = None
    error: str | None = None
    sha256: str | None = None
    formato: str | None = None  # pdf · html · texto · desconocido
    titulo: str | None = None
    paginas: list[str] = field(default_factory=list)
    bytes: int = 0

    @property
    def caracteres(self) -> int:
        return sum(len(p.strip()) for p in self.paginas)

    @property
    def da_texto(self) -> bool:
        return self.caracteres >= MINIMO_DE_TEXTO


class _TextoDeHtml(HTMLParser):
    """El texto visible de una página HTML y su `<title>`, sin scripts ni estilos."""

    SALTA = {"script", "style", "noscript", "template", "svg"}
    BLOQUES = {
        "p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "section",
        "article", "table", "ul", "ol", "dd", "dt", "pre", "blockquote", "header", "footer", "main",
    }  # fmt: skip

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.trozos: list[str] = []
        self.titulo: list[str] = []
        self._saltando = 0
        self._en_titulo = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SALTA:
            self._saltando += 1
        elif tag == "title":
            self._en_titulo = True
        elif tag in self.BLOQUES:
            self.trozos.append(" ")

    def handle_endtag(self, tag):
        if tag in self.SALTA:
            self._saltando = max(0, self._saltando - 1)
        elif tag == "title":
            self._en_titulo = False
        elif tag in self.BLOQUES:
            self.trozos.append(" ")

    def handle_data(self, data):
        if self._en_titulo:
            self.titulo.append(data)
        elif not self._saltando:
            self.trozos.append(data)


def _juego_de_caracteres(datos: bytes, declarado: str | None) -> str:
    if declarado:
        return declarado
    meta = re.search(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9_-]+)", datos[:4096], flags=re.IGNORECASE)
    return meta.group(1).decode("ascii") if meta else "utf-8"


def _lee_html(datos: bytes, juego: str | None) -> tuple[str | None, list[str]]:
    try:
        texto = datos.decode(_juego_de_caracteres(datos, juego), errors="replace")
    except LookupError:
        texto = datos.decode("utf-8", errors="replace")
    lector = _TextoDeHtml()
    lector.feed(texto)
    lector.close()
    titulo = re.sub(r"\s+", " ", "".join(lector.titulo)).strip() or None
    return titulo, ["".join(lector.trozos)]


def _lee_pdf(datos: bytes) -> tuple[str | None, list[str], str | None]:
    """(título, texto de cada página, error) de un PDF. Un PDF que no se deja leer da páginas vacías."""
    from pypdf import PdfReader

    # pypdf avisa por `logging` de cada rareza tipográfica de un informe anual; no son errores.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        lector = PdfReader(io.BytesIO(datos))
        if lector.is_encrypted:
            lector.decrypt("")
        metadatos = lector.metadata
        titulo = (str(metadatos.title).strip() or None) if metadatos and metadatos.title else None
        paginas = []
        for pagina in lector.pages:
            try:
                paginas.append(pagina.extract_text() or "")
            except Exception:  # noqa: BLE001 - una página rota no tumba el documento: queda sin texto
                paginas.append("")
        return titulo, paginas, None
    except Exception as exc:  # noqa: BLE001 - pypdf lanza de todo ante un PDF malformado
        return None, [], f"pypdf no pudo leer el PDF: {type(exc).__name__}: {str(exc)[:120]}"


def _formato(datos: bytes, tipo: str | None) -> str:
    if datos[:5] == b"%PDF-":
        return "pdf"
    cabeza = datos[:1024].lstrip().lower()
    if (tipo or "") in ("text/html", "application/xhtml+xml") or cabeza.startswith((b"<!doctype html", b"<html")):
        return "html"
    if (tipo or "").startswith("text/"):
        return "texto"
    return "desconocido"


def _lee_con_plazo(respuesta, tope: int, plazo_s: float) -> bytes:
    """Hasta `tope` bytes de la respuesta, por trozos, y `TimeoutError` si la descarga entera pasa de `plazo_s`.

    **`read1` y no `read`**: `read(n)` espera a reunir los n bytes, así que un servidor que suelta un byte
    cada poco lo dejaba bloqueado sin mirar el reloj (auditoría del 06-10, reproducido con 1 byte cada
    0,3 s). `read1` vuelve con lo que haya tras una sola lectura del socket.
    """
    limite = time.monotonic() + plazo_s
    trozos, total = [], 0
    while total <= tope:
        if time.monotonic() > limite:
            raise TimeoutError(f"la descarga pasa de {plazo_s:g} s en total")
        trozo = respuesta.read1(min(_TROZO, tope + 1 - total))
        if not trozo:
            break
        trozos.append(trozo)
        total += len(trozo)
    return b"".join(trozos)


def lee(url: str, ledger: LedgerLlamadas) -> Lectura:
    """Descarga `url` UNA vez y saca su texto. **Nunca reintenta**: un fallo queda en `Lectura.error`."""
    lectura = Lectura(url=url, descargado_el=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if not url.lower().startswith("https://"):
        lectura.error = "solo se descargan URL https"
        return lectura
    if not ledger.cabe(NOMBRE):
        ledger.omite(NOMBRE, f"tope de {ledger.tope_por_proveedor} llamadas alcanzado")
        lectura.error = "tope de llamadas del ledger alcanzado"
        return lectura
    peticion = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/pdf, text/html;q=0.9, */*;q=0.5",
            # Sin comprimir. Hay servidores que comprimen igual (medido el 06-10 en una web de inversores
            # tras Sucuri, que sirve brotli con cualquier cabecera): eso lo resuelve `completa`.
            "Accept-Encoding": "identity",
        },
    )
    try:
        with _ABRIDOR.open(peticion, timeout=TIMEOUT_S) as respuesta:
            datos = _lee_con_plazo(respuesta, TOPE_DE_BYTES, TIEMPO_MAXIMO_S)
            lectura.http = respuesta.status
            tipo = respuesta.headers.get_content_type()
            juego = respuesta.headers.get_content_charset()
            codificacion = (respuesta.headers.get("Content-Encoding") or "").strip().lower()
        ledger.registra(NOMBRE, url, lectura.http)
    except urllib.error.HTTPError as exc:
        lectura.http, lectura.error = exc.code, f"HTTP {exc.code}"
        ledger.registra(NOMBRE, url, exc.code, f"HTTPError {exc.code}")
        return lectura
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        lectura.error = f"{type(exc).__name__}: {str(exc)[:120]}"
        ledger.registra(NOMBRE, url, None, lectura.error)
        return lectura

    if len(datos) > TOPE_DE_BYTES:
        lectura.error = f"el documento pasa de {TOPE_DE_BYTES // (1024 * 1024)} MB"
        return lectura
    return completa(lectura, datos, tipo, juego, codificacion)


def _descomprime(datos: bytes, codificacion: str) -> tuple[bytes | None, str | None]:
    """(bytes sin la compresión que declara el servidor, motivo si no se pudo).

    Sin bytes y con motivo si es una compresión que la biblioteca estándar no abre, si sus bytes están
    rotos o si pasa de `TOPE_DE_BYTES` al descomprimirse. **Pasar del tope es un error y no un corte**:
    cortado, el documento se leía a medias sin decirlo, y una frase de la parte cortada salía «no está
    en el documento» (revisión de F7.12). El tope es lo que separa un documento de una bomba de compresión.
    """
    if codificacion in ("", "identity"):
        return datos, None
    if codificacion not in ("gzip", "x-gzip", "deflate"):
        return None, f"el servidor manda el documento comprimido con «{codificacion}», que el código no abre"
    ventanas = [16 + zlib.MAX_WBITS] if codificacion != "deflate" else [zlib.MAX_WBITS, -zlib.MAX_WBITS]
    for ventana in ventanas:  # «deflate» circula con y sin cabecera zlib
        abridor = zlib.decompressobj(ventana)
        try:
            abiertos = abridor.decompress(datos, TOPE_DE_BYTES)
        except zlib.error:
            continue
        if abridor.unconsumed_tail:
            return None, f"el documento pasa de {TOPE_DE_BYTES // (1024 * 1024)} MB al descomprimirse"
        if not abridor.eof:
            return None, f"el documento llega cortado: su «{codificacion}» no termina"
        return abiertos, None
    return None, f"los bytes no se dejan abrir como «{codificacion}»"


def completa(
    lectura: Lectura, datos: bytes, tipo: str | None, juego: str | None = None, codificacion: str = ""
) -> Lectura:
    """Rellena formato, título y texto de una lectura a partir de sus bytes (separado para las pruebas).

    El sha256 es el de los bytes del documento ya descomprimido: un servidor que unas veces comprime y otras
    no sigue sirviendo el mismo documento, y la huella de la confirmación no debe romperse por eso.
    """
    abiertos, motivo = _descomprime(datos, codificacion)
    if abiertos is None:
        # **Ilegible no es «sin texto».** Leer los bytes comprimidos como si fueran HTML daba un «texto» de
        # basura que nunca contiene la frase; marcarlo como lectura manual dejaría confirmar a ojo un
        # documento que el código no ha abierto. Queda en rojo y se busca otra URL (el PDF, por ejemplo).
        lectura.bytes = len(datos)
        lectura.sha256 = hashlib.sha256(datos).hexdigest()
        lectura.error = motivo
        return lectura
    datos = abiertos
    lectura.bytes = len(datos)
    lectura.sha256 = hashlib.sha256(datos).hexdigest()
    lectura.formato = _formato(datos, tipo)
    if lectura.formato == "pdf":
        lectura.titulo, lectura.paginas, error = _lee_pdf(datos)
        lectura.error = lectura.error or error
    elif lectura.formato == "html":
        lectura.titulo, lectura.paginas = _lee_html(datos, juego)
    elif lectura.formato == "texto":
        try:
            lectura.paginas = [datos.decode(juego or "utf-8", errors="replace")]
        except LookupError:
            # Un `charset` que Python no conoce lanzaba aquí un `LookupError` sin capturar (revisión de F7.12).
            # Como en el HTML, se lee como UTF-8: si la frase no casa, sale «no está» y no se confirma.
            lectura.paginas = [datos.decode("utf-8", errors="replace")]
    return lectura


class Documento(Proveedor):
    """Un documento público por su URL: informe anual, estadística oficial, nota de un banco central."""

    nombre = NOMBRE
    esquemas = ("url",)

    def busca(self, consulta: str, limite: int, ledger: LedgerLlamadas) -> list[Referencia]:
        ledger.omite(self.nombre, "una URL no se busca: se resuelve con --verificar url:https://…")
        return []

    def resuelve(self, identificador: str, ledger: LedgerLlamadas) -> Referencia | None:
        esquema, valor = parte_identificador(identificador)
        if esquema not in self.esquemas:
            return None
        if not valor.lower().startswith("https://"):
            raise FuentesError(f"{identificador!r}: el proveedor documento solo descarga URL https")
        lectura = lee(valor, ledger)
        if lectura.error and not lectura.sha256:
            return None
        return referencia_de(identificador, lectura)


def referencia_de(identificador: str, lectura: Lectura) -> Referencia:
    """La referencia de un documento descargado. El `tipo` y los `autores` los escribe Claude en la ficha."""
    return Referencia(
        identificador=identificador,
        # `fuente_primaria` (informe anual) o `institucional` (oficina estadística): el documento no lo
        # dice, y adivinarlo por el dominio sería decidir la jerarquía con una heurística.
        tipo="documento",
        titulo=lectura.titulo or "(sin título en el documento)",
        proveedor=NOMBRE,
        url=lectura.url,
        resuelto=True,
        extra={
            "formato": lectura.formato,
            "sha256": lectura.sha256,
            "paginas": len(lectura.paginas),
            "caracteres_de_texto": lectura.caracteres,
            "da_texto": lectura.da_texto,
            # Ilegible: una compresión que el código no abre o un PDF que pypdf no lee. Sus cifras no se
            # pueden confirmar; las de un documento legible sin texto, sí (lectura manual).
            "legible": lectura.formato is not None and not (lectura.error and not lectura.paginas),
            **({"aviso": lectura.error} if lectura.error else {}),
        },
    )
