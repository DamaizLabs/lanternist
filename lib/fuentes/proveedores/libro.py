"""Proveedores de libro y facsímil: Open Library e Internet Archive (F2.9).

Cubren lo que el académico no: **libros con ISBN** y **obra antigua digitalizada**. Para un nicho
histórico el segundo es el más valioso de todos, porque una fuente primaria de época —un manual de
procedimiento, un impreso del XVII— suele estar ahí escaneada y no en un repositorio con DOI.

Campos verificados contra la respuesta real de cada API el 25-08.
"""

from __future__ import annotations

from lib.fuentes.base import LedgerLlamadas, Proveedor, Referencia, parte_identificador, pide_json


class OpenLibrary(Proveedor):
    """Libros e ISBN. Sin clave. Resuelve `isbn:` y `olid:` (su propio identificador de obra)."""

    nombre = "openlibrary"
    esquemas = ("isbn", "olid")
    BUSQUEDA = "https://openlibrary.org/search.json"

    @staticmethod
    def _referencia(doc: dict, identificador: str = "") -> Referencia:
        clave = (doc.get("key") or "").rsplit("/", 1)[-1]
        return Referencia(
            identificador=identificador or (f"olid:{clave}" if clave else ""),
            tipo="libro",
            titulo=(doc.get("title") or "(sin título en la API)").strip(),
            proveedor="openlibrary",
            autores=list(doc.get("author_name") or []),
            anio=doc.get("first_publish_year"),
            url=f"https://openlibrary.org{doc.get('key')}" if doc.get("key") else None,
            extra={
                # `ia` es el puente al facsímil: si está, la obra se puede LEER, no solo citar.
                "facsimil_archive": (doc.get("ia") or [None])[0],
                "ediciones": doc.get("edition_count"),
                "texto_completo": doc.get("has_fulltext"),
                "isbn": (doc.get("isbn") or [None])[0],
            },
        )

    def busca(self, consulta: str, limite: int, ledger: LedgerLlamadas) -> list[Referencia]:
        datos = pide_json(
            self.nombre,
            self.BUSQUEDA,
            {
                "q": consulta,
                "limit": limite,
                "fields": "key,title,author_name,first_publish_year,ia,edition_count,has_fulltext,isbn",
            },
            ledger,
        )
        if not datos:
            return []
        return [ref for ref in (self._referencia(d) for d in (datos.get("docs") or [])) if ref.identificador]

    def resuelve(self, identificador: str, ledger: LedgerLlamadas) -> Referencia | None:
        esquema, valor = parte_identificador(identificador)
        if esquema == "isbn":
            # Búsqueda por ISBN exacto: si el ISBN no existe, `numFound` es 0 y eso es la respuesta
            datos = pide_json(self.nombre, self.BUSQUEDA, {"isbn": valor, "limit": 1}, ledger)
            docs = (datos or {}).get("docs") or []
            if not docs:
                return None
            referencia = self._referencia(docs[0], identificador=f"isbn:{valor}")
            referencia.resuelto = True
            return referencia
        if esquema == "olid":
            datos = pide_json(self.nombre, f"https://openlibrary.org/works/{valor}.json", {}, ledger)
            if not datos or not datos.get("title"):
                return None
            referencia = Referencia(
                identificador=identificador,
                tipo="libro",
                titulo=datos["title"].strip(),
                proveedor="openlibrary",
                url=f"https://openlibrary.org/works/{valor}",
                resuelto=True,
                extra={"descripcion": str(datos.get("description") or "")[:200] or None},
            )
            return referencia
        return None


class InternetArchive(Proveedor):
    """Facsímiles y obra antigua digitalizada. Sin clave. Resuelve `archive:<identificador>`.

    Es el proveedor de **fuente primaria** del nicho histórico: lo que devuelve no es una
    referencia a un libro, es el libro escaneado.
    """

    nombre = "archive"
    esquemas = ("archive",)
    BUSQUEDA = "https://archive.org/advancedsearch.php"
    METADATOS = "https://archive.org/metadata"

    @staticmethod
    def _anio(doc: dict) -> int | None:
        crudo = str(doc.get("year") or doc.get("date") or "")[:4]
        return int(crudo) if crudo.isdigit() else None

    @classmethod
    def _referencia(cls, doc: dict) -> Referencia:
        identificador = doc.get("identifier") or ""
        creador = doc.get("creator")
        autores = creador if isinstance(creador, list) else ([creador] if creador else [])
        return Referencia(
            identificador=f"archive:{identificador}" if identificador else "",
            tipo="facsimil",
            titulo=(doc.get("title") or "(sin título en la API)").strip(),
            proveedor="archive",
            autores=autores,
            anio=cls._anio(doc),
            url=f"https://archive.org/details/{identificador}" if identificador else None,
            extra={"tipo_medio": doc.get("mediatype"), "idioma": doc.get("language")},
        )

    def busca(self, consulta: str, limite: int, ledger: LedgerLlamadas) -> list[Referencia]:
        datos = pide_json(
            self.nombre,
            self.BUSQUEDA,
            {
                # `mediatype:texts` deja fuera audio y vídeo: aquí se buscan documentos
                "q": f"({consulta}) AND mediatype:(texts)",
                "fl[]": ["identifier", "title", "creator", "year", "date", "mediatype", "language"],
                "rows": limite,
                "page": 1,
                "output": "json",
            },
            ledger,
        )
        if not datos:
            return []
        docs = (datos.get("response") or {}).get("docs") or []
        return [ref for ref in (self._referencia(d) for d in docs) if ref.identificador]

    def resuelve(self, identificador: str, ledger: LedgerLlamadas) -> Referencia | None:
        esquema, valor = parte_identificador(identificador)
        if esquema not in self.esquemas:
            return None
        datos = pide_json(self.nombre, f"{self.METADATOS}/{valor}", {}, ledger)
        # Un identificador que no existe devuelve 200 con un objeto VACÍO, no un 404: comprobar
        # solo el estado HTTP daría por resuelto cualquier cosa.
        if not datos or not datos.get("metadata"):
            return None
        meta = datos["metadata"]
        referencia = self._referencia({**meta, "identifier": valor})
        referencia.resuelto = True
        return referencia
