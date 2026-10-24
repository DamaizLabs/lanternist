"""El resolutor: comprueba que un identificador existe antes de aceptarlo (F2.9).

**Esta es la pieza central del módulo, no un accesorio.** El principio que sostiene todo lo demás
es que el módulo no se apoya en que el agente prometa no inventar, se apoya en que no pueda: toda
fuente trae un identificador y aquí se resuelve contra la API. Lo que no resuelve, no entra en una
ficha; y lo que no está en una ficha, no entra en un guion.

No es una precaución hipotética. Al construir esto se probaron **dos** identificadores escritos de
memoria por el agente:

- un DOI que resolvió correctamente… **a un artículo distinto** del que se creía citar (pedí algo
  de procedimiento inquisitorial y devolvió *«After Thirty Years of 'new' Labour History…»*);
- otro DOI con la forma perfecta que devolvió **404**.

Dos de dos. La memoria de un modelo produce identificadores bien formados y con el contenido
equivocado, y de los dos modos de fallo el primero es el peligroso: la cita *parece* verificada.
De ahí la segunda mitad de este archivo, `compara_titulo`: resolver no basta si nadie mira si lo
resuelto es lo que se pedía.
"""

from __future__ import annotations

import re
import unicodedata

from lib.fuentes.base import FuentesError, LedgerLlamadas, Proveedor, Referencia, parte_identificador

# Por debajo de este parecido entre el título propuesto y el que devuelve la API, se considera
# que el identificador apunta a **otra obra**. No es un umbral fino: separar «el mismo título con
# otro subtítulo» de «un artículo completamente distinto» no necesita precisión, y ante la duda
# la discrepancia se anota para que la lea una persona.
UMBRAL_PARECIDO = 0.55


def _normaliza(texto: str) -> list[str]:
    """Palabras significativas, sin acentos ni puntuación, para comparar títulos."""
    plano = "".join(c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c))
    return [p for p in re.split(r"[^a-z0-9]+", plano) if len(p) > 2]


def parecido_de_titulo(propuesto: str, devuelto: str) -> float:
    """Jaccard sobre palabras significativas. 1.0 = mismas palabras; 0.0 = nada en común."""
    a, b = set(_normaliza(propuesto)), set(_normaliza(devuelto))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def compara_titulo(propuesto: str | None, referencia: Referencia) -> dict | None:
    """Compara el título que proponía el agente con el que devolvió la API.

    Devuelve `None` si no había propuesta o si coinciden. Si no coinciden, devuelve la
    discrepancia **con el veredicto explícito**: `gana` es siempre la API.

    Sin esto, el modo de fallo que se midió —un DOI que resuelve a otra obra— pasaría el filtro,
    porque técnicamente el identificador existe.
    """
    if not propuesto:
        return None
    parecido = parecido_de_titulo(propuesto, referencia.titulo)
    if parecido >= UMBRAL_PARECIDO:
        return None
    return {
        "titulo_propuesto_por_el_agente": propuesto,
        "titulo_devuelto_por_la_api": referencia.titulo,
        "parecido": round(parecido, 2),
        "umbral": UMBRAL_PARECIDO,
        "gana": "la API",
        "aviso": (
            "el identificador existe pero apunta a otra obra: es el modo de fallo peligroso, porque "
            "la cita parece verificada. Revisar a mano antes de usarla."
        ),
    }


def resuelve(
    identificador: str, proveedores: list[Proveedor], ledger: LedgerLlamadas
) -> tuple[Referencia | None, list[str]]:
    """Resuelve un identificador con el primer proveedor que sepa y lo encuentre.

    Devuelve (referencia o None, proveedores consultados). Se prueban en el orden en que los
    declara el perfil del nicho, y **solo** los que declaran ese esquema: probar todos con todo
    es la heurística que acaba aceptando una coincidencia casual.
    """
    esquema, _ = parte_identificador(identificador)
    capaces = [p for p in proveedores if esquema in p.esquemas]
    if not capaces:
        raise FuentesError(
            f"ningún proveedor del nicho resuelve el esquema {esquema!r} (de {identificador!r}). "
            f"Esquemas disponibles: {sorted({e for p in proveedores for e in p.esquemas})}"
        )
    consultados = []
    for proveedor in capaces:
        consultados.append(proveedor.nombre)
        referencia = proveedor.resuelve(identificador, ledger)
        if referencia is not None:
            return referencia, consultados
    return None, consultados


def verifica(peticiones: list[dict], proveedores: list[Proveedor], ledger: LedgerLlamadas) -> list[dict]:
    """Verifica una lista de `{identificador, titulo_propuesto?}` y devuelve el veredicto de cada una.

    El veredicto es un dict con `resuelto` booleano, la referencia si la hay y la discrepancia de
    título si la hay. No lanza excepción por un identificador que no existe: **eso es un resultado
    válido y es justo el que hay que ver escrito**.
    """
    veredictos = []
    for peticion in peticiones:
        identificador = (peticion.get("identificador") or "").strip()
        propuesto = peticion.get("titulo_propuesto")
        try:
            referencia, consultados = resuelve(identificador, proveedores, ledger)
        except FuentesError as exc:
            veredictos.append(
                {"identificador": identificador, "resuelto": False, "motivo": str(exc), "consultados": []}
            )
            continue
        if referencia is None:
            veredictos.append(
                {
                    "identificador": identificador,
                    "resuelto": False,
                    "motivo": "NO EXISTE: ningún proveedor lo encuentra. No puede entrar en una ficha.",
                    "consultados": consultados,
                }
            )
            continue
        veredicto = {
            "identificador": identificador,
            "resuelto": True,
            "consultados": consultados,
            "referencia": referencia.a_dict(),
        }
        discrepancia = compara_titulo(propuesto, referencia)
        if discrepancia:
            veredicto["discrepancia_de_titulo"] = discrepancia
        veredictos.append(veredicto)
    return veredictos
