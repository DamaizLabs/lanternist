"""Catálogo de proveedores de fuentes (F2.9).

Añadir un proveedor es escribir su clase en este paquete y añadir una línea a `CATALOGO`. Nadie
más lo conoce: el perfil del nicho lo nombra por cadena y el resolutor lo encuentra por el
esquema de identificador que declare.

`necesita_clave` no es informativo: el registro **excluye** de la sesión a los proveedores que
piden clave y no la tienen, y lo dice, en vez de dejar que fallen con un 401 a mitad de una
búsqueda. Dar de alta una credencial está en la lista negra del agente — la hace el usuario.
"""

from lib.fuentes.proveedores.academico import Crossref, OpenAlex
from lib.fuentes.proveedores.documento import Documento
from lib.fuentes.proveedores.enciclopedia import Wikidata, Wikipedia
from lib.fuentes.proveedores.libro import InternetArchive, OpenLibrary
from lib.fuentes.proveedores.taxonomia import GBIF

CATALOGO = {
    Crossref.nombre: Crossref,
    OpenAlex.nombre: OpenAlex,
    OpenLibrary.nombre: OpenLibrary,
    InternetArchive.nombre: InternetArchive,
    GBIF.nombre: GBIF,
    Wikipedia.nombre: Wikipedia,
    Wikidata.nombre: Wikidata,
    Documento.nombre: Documento,
}

__all__ = [
    "CATALOGO",
    "Crossref",
    "Documento",
    "GBIF",
    "InternetArchive",
    "OpenAlex",
    "OpenLibrary",
    "Wikidata",
    "Wikipedia",
]
