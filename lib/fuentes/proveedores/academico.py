"""Proveedores académicos: Crossref y OpenAlex (F2.9).

Van juntos porque resuelven **el mismo esquema** —`doi`— y se complementan: Crossref es el
registro de la agencia que asigna los DOI, así que es la autoridad para *resolver*; OpenAlex
indexa por encima y suele buscar mejor por tema. El resolutor los prueba en orden.

Campos verificados contra la respuesta real de cada API el 25-08, no de memoria.
"""

from __future__ import annotations

from lib.fuentes.base import LedgerLlamadas, Proveedor, Referencia, parte_identificador, pide_json


def _anio_crossref(item: dict) -> int | None:
    """El año sale de varias claves según el tipo de obra; se prueban en orden de fiabilidad."""
    for clave in ("published-print", "published-online", "published", "created", "issued"):
        partes = (item.get(clave) or {}).get("date-parts") or []
        if partes and partes[0] and partes[0][0]:
            return int(partes[0][0])
    return None


def _tipo_crossref(item: dict) -> str:
    """Traduce el `type` de Crossref al vocabulario de la jerarquía de autoridad del nicho."""
    crudo = (item.get("type") or "").lower()
    if crudo in ("book", "monograph", "book-chapter", "edited-book", "reference-book"):
        return "libro_academico"
    if crudo in ("journal-article", "proceedings-article", "posted-content"):
        return "academica_revisada"
    return crudo or "academica_revisada"


def _referencia_crossref(item: dict) -> Referencia:
    titulos = item.get("title") or []
    autores = [
        " ".join(filter(None, [a.get("given"), a.get("family")])).strip()
        for a in (item.get("author") or [])
        if a.get("family") or a.get("given")
    ]
    doi = (item.get("DOI") or "").strip()
    isbn = [entrada.get("value") for entrada in (item.get("isbn-type") or []) if entrada.get("value")]
    return Referencia(
        identificador=f"doi:{doi}" if doi else "",
        tipo=_tipo_crossref(item),
        # El título es lo que dice la API. Crossref lo da como lista y puede venir vacío.
        titulo=(titulos[0].strip() if titulos else "(la API no devuelve título para este DOI)"),
        proveedor="crossref",
        autores=autores,
        anio=_anio_crossref(item),
        url=f"https://doi.org/{doi}" if doi else None,
        extra={
            "editorial": item.get("publisher"),
            "contenedor": (item.get("container-title") or [None])[0],
            "isbn": isbn or None,
            "tipo_crossref": item.get("type"),
        },
    )


class Crossref(Proveedor):
    """Artículos y libros académicos con DOI. Sin clave. **Es quien resuelve un DOI.**"""

    nombre = "crossref"
    esquemas = ("doi",)
    BUSQUEDA = "https://api.crossref.org/works"

    def busca(self, consulta: str, limite: int, ledger: LedgerLlamadas) -> list[Referencia]:
        datos = pide_json(self.nombre, self.BUSQUEDA, {"query": consulta, "rows": limite}, ledger)
        if not datos:
            return []
        items = (datos.get("message") or {}).get("items") or []
        return [ref for ref in (_referencia_crossref(i) for i in items) if ref.identificador]

    def resuelve(self, identificador: str, ledger: LedgerLlamadas) -> Referencia | None:
        esquema, valor = parte_identificador(identificador)
        if esquema not in self.esquemas:
            return None
        # El DOI va en la ruta, no como parámetro: hay que escaparlo porque lleva barras.
        from urllib.parse import quote

        datos = pide_json(self.nombre, f"{self.BUSQUEDA}/{quote(valor, safe='')}", {}, ledger)
        if not datos or not isinstance(datos.get("message"), dict):
            return None
        referencia = _referencia_crossref(datos["message"])
        referencia.resuelto = True
        return referencia


class OpenAlex(Proveedor):
    """Catálogo académico abierto. Sin clave. Busca mejor por tema; también resuelve DOI."""

    nombre = "openalex"
    esquemas = ("doi", "openalex")
    BUSQUEDA = "https://api.openalex.org/works"

    @staticmethod
    def _referencia(item: dict) -> Referencia:
        doi = (item.get("doi") or "").replace("https://doi.org/", "").strip()
        identificador = f"doi:{doi}" if doi else f"openalex:{(item.get('id') or '').rsplit('/', 1)[-1]}"
        autores = [
            (a.get("author") or {}).get("display_name")
            for a in (item.get("authorships") or [])
            if (a.get("author") or {}).get("display_name")
        ]
        tipo = (item.get("type") or "").lower()
        return Referencia(
            identificador=identificador,
            tipo="libro_academico" if tipo in ("book", "book-chapter") else "academica_revisada",
            titulo=(item.get("title") or item.get("display_name") or "(sin título en la API)").strip(),
            proveedor="openalex",
            autores=[a for a in autores if a],
            anio=item.get("publication_year"),
            url=item.get("doi") or item.get("id"),
            extra={
                "tipo_openalex": item.get("type"),
                "acceso_abierto": (item.get("open_access") or {}).get("is_oa"),
                "citas": item.get("cited_by_count"),
            },
        )

    def busca(self, consulta: str, limite: int, ledger: LedgerLlamadas) -> list[Referencia]:
        datos = pide_json(self.nombre, self.BUSQUEDA, {"search": consulta, "per-page": limite}, ledger)
        if not datos:
            return []
        return [self._referencia(i) for i in (datos.get("results") or [])]

    def resuelve(self, identificador: str, ledger: LedgerLlamadas) -> Referencia | None:
        esquema, valor = parte_identificador(identificador)
        if esquema == "doi":
            ruta = f"{self.BUSQUEDA}/https://doi.org/{valor}"
        elif esquema == "openalex":
            ruta = f"{self.BUSQUEDA}/{valor}"
        else:
            return None
        datos = pide_json(self.nombre, ruta, {}, ledger)
        if not datos or not datos.get("id"):
            return None
        referencia = self._referencia(datos)
        referencia.resuelto = True
        return referencia
