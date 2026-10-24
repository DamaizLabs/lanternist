"""Contrato común de los proveedores de fuentes, HTTP y ledger de llamadas (F2.9).

El módulo entero se apoya en una idea: **una cita que no resuelve, no existe**. Toda referencia
lleva un identificador (DOI, ISBN, id de GBIF, de Internet Archive) y el resolutor lo comprueba
contra la API antes de aceptarla. No es una precaución teórica — al sondear estas APIs puse dos
identificadores de memoria y **ninguno resolvió a lo que yo creía**: uno devolvió un artículo
distinto y el otro un 404. La memoria de un modelo produce identificadores con la forma correcta
y el contenido equivocado, así que el resolutor es la pieza central y no un accesorio.

Reglas que este archivo hace cumplir:

- **Cero reintentos automáticos.** Mismo criterio que el ledger de cuota del detector, que ya se
  pagó con 308 unidades quemadas: un fallo se registra y decide el llamante. Aquí el límite no es
  presupuesto sino **cortesía** —Crossref y OpenAlex no cobran pero penalizan el abuso—, y una
  búsqueda de fuentes son decenas de llamadas, no miles.
- **No se envía ningún dato personal.** El `User-Agent` identifica al proyecto. Crossref y OpenAlex
  ofrecen un «polite pool» a cambio de un correo de contacto: **no se manda el del usuario**, porque
  entregar su dirección a un tercero por una mejora de prioridad no es un intercambio
  que el agente deba hacer por su cuenta. Si algún día conviene, es decisión suya y se declara
  aquí. Lo que sale de este PC son términos de búsqueda e identificadores públicos, nada más.
- **El título lo escribe la API.** `Referencia.titulo` se rellena con lo que devuelve el
  proveedor. Si el agente proponía otro, gana la API y la discrepancia se anota.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

USER_AGENT = "Lanternist/0.1 (catalogacion de fuentes en local)"
TIMEOUT_S = 30


class FuentesError(RuntimeError):
    """Fallo del módulo de fuentes: perfil inválido, proveedor desconocido o red caída."""


@dataclass
class Referencia:
    """Una fuente, tal como la devuelve un proveedor.

    `resuelto` distingue lo comprobado de lo propuesto, y es la diferencia que decide si una
    referencia puede entrar en una ficha. `titulo` viene de la API, nunca del agente.
    """

    identificador: str
    tipo: str
    titulo: str
    proveedor: str
    autores: list[str] = field(default_factory=list)
    anio: int | None = None
    url: str | None = None
    resuelto: bool = False
    extra: dict = field(default_factory=dict)

    def a_dict(self) -> dict:
        return {
            "identificador": self.identificador,
            "tipo": self.tipo,
            "titulo": self.titulo,
            "autores": self.autores,
            "anio": self.anio,
            "proveedor": self.proveedor,
            "url": self.url,
            "resuelto": self.resuelto,
            **({"extra": self.extra} if self.extra else {}),
        }


class LedgerLlamadas:
    """Registro de cada llamada HTTP a un proveedor. Se embebe en la salida.

    No hay presupuesto en unidades como en la YouTube Data API, así que lo que se controla es el
    **número de llamadas por proveedor**: es lo que la cortesía limita. `tope_por_proveedor`
    corta antes de llamar en vez de después, y una llamada que se omite queda anotada — un tope
    que recortara la lista en silencio sería peor que no tenerlo.
    """

    def __init__(self, tope_por_proveedor: int = 40) -> None:
        self.tope_por_proveedor = int(tope_por_proveedor)
        self.llamadas: list[dict] = []
        self.omitidas: list[dict] = []
        self.por_proveedor: dict[str, int] = {}

    def cabe(self, proveedor: str) -> bool:
        return self.por_proveedor.get(proveedor, 0) < self.tope_por_proveedor

    def registra(self, proveedor: str, url: str, estado: int | None, error: str | None = None) -> None:
        self.por_proveedor[proveedor] = self.por_proveedor.get(proveedor, 0) + 1
        self.llamadas.append(
            {
                "proveedor": proveedor,
                "url": url,
                "http": estado,
                "error": error,
                "momento": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )

    def omite(self, proveedor: str, motivo: str) -> None:
        self.omitidas.append({"proveedor": proveedor, "motivo": motivo})

    def resumen(self) -> dict:
        fallidas = [c for c in self.llamadas if c["error"] or (c["http"] or 0) >= 400]
        return {
            "llamadas": len(self.llamadas),
            "por_proveedor": dict(sorted(self.por_proveedor.items())),
            "fallidas": len(fallidas),
            "omitidas": self.omitidas,
            "tope_por_proveedor": self.tope_por_proveedor,
            "politica": "sin reintentos automáticos; el tope corta antes de llamar y lo omitido queda anotado",
        }


def pide_json(proveedor: str, url: str, params: dict, ledger: LedgerLlamadas) -> dict | None:
    """Una petición GET que devuelve JSON, o `None` si falla. **Nunca reintenta.**

    El fallo se registra en el ledger con su estado HTTP y se devuelve `None`: quien llame decide
    si eso es fatal o si sigue con los demás proveedores. Un reintento automático aquí sería el
    mismo error que el proyecto ya decidió no repetir contra la API de YouTube.
    """
    if not ledger.cabe(proveedor):
        ledger.omite(proveedor, f"tope de {ledger.tope_por_proveedor} llamadas alcanzado")
        return None

    completa = url + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    peticion = urllib.request.Request(
        completa,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_S) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
            ledger.registra(proveedor, completa, respuesta.status)
            return datos
    except urllib.error.HTTPError as exc:
        # Un 404 es información, no una avería: significa que el identificador NO EXISTE, que es
        # justo lo que el resolutor necesita saber. Se registra y se devuelve None.
        ledger.registra(proveedor, completa, exc.code, f"HTTPError {exc.code}")
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        ledger.registra(proveedor, completa, None, f"{type(exc).__name__}: {str(exc)[:120]}")
        return None


class Proveedor:
    """Interfaz de un proveedor. Añadir uno es un archivo en `proveedores/`, no tocar el resto.

    `esquemas` declara qué prefijos de identificador sabe resolver (`doi`, `isbn`, `gbif`…), y es
    lo que usa el resolutor para elegir a quién preguntar sin que nadie mantenga un mapa aparte.
    """

    nombre: str = ""
    esquemas: tuple[str, ...] = ()
    necesita_clave: bool = False

    def busca(self, consulta: str, limite: int, ledger: LedgerLlamadas) -> list[Referencia]:
        raise NotImplementedError

    def resuelve(self, identificador: str, ledger: LedgerLlamadas) -> Referencia | None:
        """Devuelve la referencia SI el identificador existe de verdad; `None` si no."""
        raise NotImplementedError


def parte_identificador(identificador: str) -> tuple[str, str]:
    """Separa `doi:10.1017/xxx` en (`doi`, `10.1017/xxx`).

    Sin esquema no se adivina: un identificador desnudo podría ser un DOI, un ISBN o una clave de
    GBIF, y probar con todos es exactamente el tipo de heurística que acaba aceptando una cita
    que no era la que se pedía.
    """
    esquema, separador, valor = identificador.partition(":")
    if not separador or not valor.strip():
        raise FuentesError(
            f"identificador sin esquema: {identificador!r}. Se escribe 'esquema:valor' "
            "(doi:10.xxxx/yyy · isbn:9780123456789 · gbif:104790737 · archive:idnetificador · olid:OL123W)"
        )
    return esquema.strip().lower(), valor.strip()
