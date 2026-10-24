"""Wikipedia y Wikidata (F2.9b, petición del 25-08).

La petición echó en falta Wikipedia en el módulo y trajo dos enlaces concretos del artículo
«Tortura en España». Tiene razón en el fondo y la respuesta no es meterla como fuente de
autoridad: **es meterla en el papel donde vale mucho más, que es el de índice.**

La diferencia importa y está medida. Un artículo de Wikipedia:

- **NO puede ser la cita de una afirmación** en un canal que se presenta como museo. Su contenido
  cambia sin aviso, no tiene autor responsable, y es exactamente lo que la audiencia informada
  usa para desmentir a un divulgador. Además, la lista negra del nicho ya excluye «wikis sin
  cita» — y esa exclusión sigue en pie.
- **SÍ es el mejor descubridor de fuentes que hay para este nicho.** Sus plantillas de cita
  llevan ISBN y DOI en campos separados, y esos identificadores **el resolutor los puede
  comprobar**. Medido el 25-08: `es:Tortura en España` trae 21 plantillas de cita con 8 ISBN;
  `en:Spanish Inquisition`, 128 plantillas con 39 ISBN y 9 DOI. Eso es un catálogo de partida que
  las búsquedas por palabras clave no daban — y de paso resuelve el ruido que se midió en F2.10
  («stocks punishment» devolvía economía institucional).

Por eso el flujo es en dos pasos: Wikipedia da los identificadores, el resolutor dice cuáles
existen, y solo esos entran en una ficha. Wikipedia nunca aparece como fuente de la afirmación.

**Wikidata es otra cosa y sí es citable**: da un identificador estable de entidad (`Q685366`) con
la clasificación de la propia base. Y en este nicho eso es oro, porque para la doncella de hierro
Wikidata dice literalmente «mythical torture device»: una autoridad enlazable que respalda la
certeza `invencion_moderna` en vez de dejarla en palabra del agente.

**Por qué no un MCP.** Se pidió buscar MCPs de Wikipedia y existen (hay servidores de Wikidata
y de Wikipedia, y Wikimedia Deutschland presentó uno en Wikimania 2026). No se usa ninguno, y el
motivo es concreto: un MCP es un proceso externo con código que este proyecto no audita, y se
saltaría el ledger de llamadas y la política de «sin reintentos» que el módulo hace cumplir. La
API de Wikipedia es pública, sin clave, y el adaptador cabe en este archivo. La decisión cerrada
10 —adaptadores detrás de interfaces estables— apunta en la misma dirección.
"""

from __future__ import annotations

import re
import urllib.parse

from lib.fuentes.base import LedgerLlamadas, Proveedor, Referencia, parte_identificador, pide_json

# Plantillas de cita en el wikitexto, en las dos wikis que interesan. Los identificadores van en
# campos con nombre, así que se extraen por clave y no adivinando dentro del texto.
_ISBN = re.compile(r"\bisbn\s*=\s*([\dXx][\dXx\-\s]{8,18}[\dXx])", re.I)
_DOI = re.compile(r"\bdoi\s*=\s*(10\.\d{4,9}/[^\s|}\]]+)", re.I)


class Wikipedia(Proveedor):
    """Wikipedia como **índice de fuentes**, nunca como fuente de una afirmación.

    `busca` devuelve artículos con el tipo `indice_de_fuentes`, que **no está en la jerarquía de
    autoridad de ningún perfil**: si alguien intentara meterlo en una ficha, la validación lo
    avisaría. Lo que se usa de verdad es `identificadores_citados`.
    """

    nombre = "wikipedia"
    esquemas = ("wikipedia",)

    @staticmethod
    def _api(wiki: str) -> str:
        return f"https://{wiki}.wikipedia.org/w/api.php"

    def busca(self, consulta: str, limite: int, ledger: LedgerLlamadas) -> list[Referencia]:
        """Busca artículos. El idioma sale del prefijo `es:` o `en:` de la consulta (por defecto `en`)."""
        wiki, _, termino = consulta.partition(":")
        if len(wiki) != 2 or not termino.strip():
            wiki, termino = "en", consulta
        datos = pide_json(
            self.nombre,
            self._api(wiki),
            {
                "action": "query",
                "list": "search",
                "srsearch": termino.strip(),
                "srlimit": limite,
                "format": "json",
                "formatversion": "2",
            },
            ledger,
        )
        if not datos:
            return []
        resultados = (datos.get("query") or {}).get("search") or []
        return [
            Referencia(
                identificador=f"wikipedia:{wiki}:{r['title']}",
                tipo="indice_de_fuentes",
                titulo=r["title"],
                proveedor=self.nombre,
                url=f"https://{wiki}.wikipedia.org/wiki/{urllib.parse.quote(r['title'].replace(' ', '_'))}",
                extra={"palabras": r.get("wordcount"), "wiki": wiki},
            )
            for r in resultados
        ]

    def resuelve(self, identificador: str, ledger: LedgerLlamadas) -> Referencia | None:
        """Comprueba que el artículo existe y trae su resumen. **No lo convierte en fuente citable.**"""
        esquema, valor = parte_identificador(identificador)
        if esquema not in self.esquemas:
            return None
        wiki, _, titulo = valor.partition(":")
        if not titulo:
            wiki, titulo = "en", valor
        datos = pide_json(
            self.nombre,
            self._api(wiki),
            {
                "action": "query",
                "titles": titulo,
                "prop": "extracts|info",
                "exintro": "1",
                "explaintext": "1",
                "inprop": "url",
                "format": "json",
                "formatversion": "2",
            },
            ledger,
        )
        paginas = ((datos or {}).get("query") or {}).get("pages") or []
        if not paginas or paginas[0].get("missing"):
            return None
        pagina = paginas[0]
        return Referencia(
            identificador=identificador,
            tipo="indice_de_fuentes",
            titulo=pagina.get("title") or titulo,
            proveedor=self.nombre,
            url=pagina.get("fullurl"),
            resuelto=True,
            extra={
                "resumen": (pagina.get("extract") or "")[:600],
                "pageid": pagina.get("pageid"),
                "advertencia": (
                    "índice, NO fuente: el contenido cambia sin aviso y no tiene autor responsable. "
                    "Sirve para descubrir identificadores citables, que hay que resolver aparte"
                ),
            },
        )

    def identificadores_citados(self, identificador: str, ledger: LedgerLlamadas) -> dict:
        """**Lo que hace útil a este proveedor**: los ISBN y DOI que el artículo cita.

        Se leen del wikitexto, donde las plantillas de cita los llevan en campos con nombre. Se
        probó antes la API REST de referencias, que sería más limpia, y **devuelve 404 en
        es.wikipedia** — de ahí esta vía.

        Lo que sale de aquí son CANDIDATOS: que Wikipedia cite un ISBN no prueba que exista ni que
        respalde nada. El paso siguiente es el resolutor.
        """
        esquema, valor = parte_identificador(identificador)
        if esquema not in self.esquemas:
            return {"error": f"no es un identificador de wikipedia: {identificador!r}"}
        wiki, _, titulo = valor.partition(":")
        if not titulo:
            wiki, titulo = "en", valor
        datos = pide_json(
            self.nombre,
            self._api(wiki),
            {
                "action": "query",
                "titles": titulo,
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "format": "json",
                "formatversion": "2",
            },
            ledger,
        )
        paginas = ((datos or {}).get("query") or {}).get("pages") or []
        if not paginas or paginas[0].get("missing"):
            return {"error": f"el artículo {titulo!r} no existe en {wiki}.wikipedia"}
        texto = ((paginas[0].get("revisions") or [{}])[0].get("slots") or {}).get("main", {}).get("content", "")

        isbns = {re.sub(r"[\s\-]", "", i) for i in _ISBN.findall(texto)}
        dois = {d.rstrip(".,;") for d in _DOI.findall(texto)}
        return {
            "articulo": titulo,
            "wiki": wiki,
            "plantillas_de_cita": len(re.findall(r"\{\{\s*(?:cita|cite)\b", texto, re.I)),
            "candidatos": [f"isbn:{i}" for i in sorted(isbns)] + [f"doi:{d}" for d in sorted(dois)],
        }


class Wikidata(Proveedor):
    """Wikidata: identificador estable de entidad, con la clasificación de la propia base.

    A diferencia de Wikipedia, esto **sí es citable**, y en este nicho vale especialmente: la
    entidad de la doncella de hierro es `Q685366`, descrita por Wikidata como «mythical torture
    device». Una ficha con certeza `invencion_moderna` puede enlazar eso en vez de dejar la
    clasificación en palabra del agente.
    """

    nombre = "wikidata"
    esquemas = ("wikidata",)
    API = "https://www.wikidata.org/w/api.php"

    def busca(self, consulta: str, limite: int, ledger: LedgerLlamadas) -> list[Referencia]:
        datos = pide_json(
            self.nombre,
            self.API,
            {
                "action": "wbsearchentities",
                "search": consulta,
                "language": "en",
                "uselang": "en",
                "type": "item",
                "format": "json",
                "limit": limite,
            },
            ledger,
        )
        if not datos:
            return []
        return [
            Referencia(
                identificador=f"wikidata:{e['id']}",
                tipo="identificador_de_entidad",
                titulo=e.get("label") or e["id"],
                proveedor=self.nombre,
                url=e.get("concepturi") or f"https://www.wikidata.org/wiki/{e['id']}",
                extra={"descripcion": e.get("description")},
            )
            for e in (datos.get("search") or [])
        ]

    def resuelve(self, identificador: str, ledger: LedgerLlamadas) -> Referencia | None:
        esquema, valor = parte_identificador(identificador)
        if esquema not in self.esquemas or not re.fullmatch(r"Q\d+", valor):
            return None
        datos = pide_json(
            self.nombre,
            self.API,
            {
                "action": "wbgetentities",
                "ids": valor,
                "props": "labels|descriptions",
                "languages": "en|es",
                "format": "json",
            },
            ledger,
        )
        entidad = ((datos or {}).get("entities") or {}).get(valor)
        if not entidad or "missing" in entidad:
            return None
        etiquetas = entidad.get("labels") or {}
        descripciones = entidad.get("descripciones") or entidad.get("descriptions") or {}
        etiqueta = (etiquetas.get("en") or etiquetas.get("es") or {}).get("value") or valor
        descripcion = (descripciones.get("en") or descripciones.get("es") or {}).get("value")
        return Referencia(
            identificador=identificador,
            tipo="identificador_de_entidad",
            titulo=etiqueta,
            proveedor=self.nombre,
            url=f"https://www.wikidata.org/wiki/{valor}",
            resuelto=True,
            extra={"descripcion": descripcion},
        )
