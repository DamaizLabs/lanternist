"""GBIF: taxonomía y biodiversidad (F2.9).

Este proveedor **no lo necesita el canal del MVP**. Existe porque es la prueba de que el módulo es
universal, que es lo que se encargó: «si en un futuro queremos hacer otro canal de insectos,
tendrá que estar preparado para buscar fuentes con autoridad de insectos». Un nicho de historia
cita monografías; uno de entomología cita el nombre científico aceptado y su clave taxonómica.

Que el segundo nicho tenga proveedor **comprobado** es lo que convierte la universalidad en un
hecho en vez de una promesa de diseño.

Campos verificados contra la respuesta real de la API el 25-08.
"""

from __future__ import annotations

from lib.fuentes.base import LedgerLlamadas, Proveedor, Referencia, parte_identificador, pide_json


class GBIF(Proveedor):
    """Global Biodiversity Information Facility. Sin clave. Resuelve `gbif:<clave>`."""

    nombre = "gbif"
    esquemas = ("gbif",)
    BUSQUEDA = "https://api.gbif.org/v1/species/search"
    FICHA = "https://api.gbif.org/v1/species"

    @staticmethod
    def _referencia(item: dict) -> Referencia:
        clave = item.get("key")
        # `canonicalName` es el nombre sin autoría; `scientificName` lo trae con autor y año, que
        # es la forma citable. Se prefiere la citable y la otra queda en extra.
        return Referencia(
            identificador=f"gbif:{clave}" if clave else "",
            tipo="base_taxonomica",
            titulo=(item.get("scientificName") or item.get("canonicalName") or "(sin nombre en la API)").strip(),
            proveedor="gbif",
            autores=[item.get("authorship")] if item.get("authorship") else [],
            anio=None,
            url=f"https://www.gbif.org/species/{clave}" if clave else None,
            extra={
                "nombre_canonico": item.get("canonicalName"),
                "rango": item.get("rank"),
                "estado_taxonomico": item.get("taxonomicStatus"),
                "reino": item.get("kingdom"),
                "filo": item.get("phylum"),
                "orden": item.get("order"),
                "familia": item.get("family"),
                "genero": item.get("genus"),
                "especie": item.get("species"),
            },
        )

    def busca(self, consulta: str, limite: int, ledger: LedgerLlamadas) -> list[Referencia]:
        datos = pide_json(self.nombre, self.BUSQUEDA, {"q": consulta, "limit": limite}, ledger)
        if not datos:
            return []
        return [ref for ref in (self._referencia(i) for i in (datos.get("results") or [])) if ref.identificador]

    def resuelve(self, identificador: str, ledger: LedgerLlamadas) -> Referencia | None:
        esquema, valor = parte_identificador(identificador)
        if esquema not in self.esquemas or not valor.isdigit():
            return None
        datos = pide_json(self.nombre, f"{self.FICHA}/{valor}", {}, ledger)
        if not datos or not datos.get("key"):
            return None
        referencia = self._referencia(datos)
        referencia.resuelto = True
        return referencia
