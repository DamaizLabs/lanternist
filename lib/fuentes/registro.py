"""Perfiles de autoridad por nicho: qué cuenta como fuente fiable en un dominio (F2.9).

Esta es la pieza que hace **universal** al módulo, y por eso vive en la **capa de estudio**
(`datos/autoridades/<nicho>.json`, `doc/06-arquitectura-estudio-canales.md`): un perfil de nicho es
una plantilla de dominio reutilizable y **existe sin canal** —los dos perfiles de ejemplo,
`ejemplo-con-cifras` y `ejemplo-sin-cifras`, no son de ningún canal: añadir un nicho es un JSON—,
mientras que las fichas verificadas son del canal, porque son su catálogo.

Lo que un perfil declara, y por qué no puede estar en el código: en historia una autoridad es una
monografía revisada o un impreso de época; en entomología es el nombre científico aceptado de una
base taxonómica. Meter eso en Python obligaría a tocar código por cada nicho nuevo, que es
exactamente lo que el encargo del 24-08 prohíbe.
"""

from __future__ import annotations

import json
from pathlib import Path

from lib.config import DATOS_ESTUDIO_DIR
from lib.fuentes.base import FuentesError, Proveedor
from lib.fuentes.proveedores import CATALOGO

AUTORIDADES_DIR = DATOS_ESTUDIO_DIR / "autoridades"

# Claves que todo perfil debe declarar. Un perfil incompleto no se completa con valores por
# defecto: el defecto silencioso sería «cualquier cosa vale como fuente», que es lo contrario
# de lo que este módulo existe para hacer.
CLAVES_OBLIGATORIAS = ("nicho", "proveedores", "jerarquia", "exige_identificador", "campos_obligatorios")


def nichos_disponibles() -> list[str]:
    """Nichos con perfil de autoridad, leídos del disco (no de una lista mantenida a mano)."""
    if not AUTORIDADES_DIR.is_dir():
        return []
    return sorted(p.stem for p in AUTORIDADES_DIR.glob("*.json"))


def ruta_perfil(nicho: str) -> Path:
    return AUTORIDADES_DIR / f"{nicho}.json"


def carga_perfil(nicho: str) -> dict:
    """Lee y valida el perfil de autoridad de un nicho."""
    ruta = ruta_perfil(nicho)
    if not ruta.exists():
        raise FuentesError(
            f"No hay perfil de autoridad para el nicho {nicho!r} ({ruta}). "
            f"Disponibles: {nichos_disponibles() or 'ninguno'}. Añadir un nicho es crear ese JSON."
        )
    try:
        perfil = json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FuentesError(f"{ruta} no es JSON válido: {exc}") from exc
    if not isinstance(perfil, dict):
        raise FuentesError(f"{ruta} debe ser un objeto JSON, es {type(perfil).__name__}")

    faltan = [clave for clave in CLAVES_OBLIGATORIAS if clave not in perfil]
    if faltan:
        raise FuentesError(f"el perfil {nicho!r} no declara {faltan} (obligatorias: {list(CLAVES_OBLIGATORIAS)})")

    desconocidos = [p for p in perfil["proveedores"] if p not in CATALOGO]
    if desconocidos:
        raise FuentesError(
            f"el perfil {nicho!r} nombra proveedores que este módulo no implementa: {desconocidos}. "
            f"Implementados: {sorted(CATALOGO)}. Añadir uno es una clase en lib/fuentes/proveedores/ "
            "más su línea en CATALOGO."
        )
    return perfil


def proveedores_de(perfil: dict) -> tuple[list[Proveedor], list[dict]]:
    """Instancia los proveedores del perfil. Devuelve (usables, excluidos con su motivo).

    Los que piden clave y no la tienen se **excluyen y se dicen**, en vez de dejarlos entrar para
    que fallen con un 401 en medio de una búsqueda: un proveedor que no puede responder no es un
    fallo de red, es una credencial que el usuario todavía no ha dado de alta.
    """
    usables: list[Proveedor] = []
    excluidos: list[dict] = []
    for nombre in perfil["proveedores"]:
        clase = CATALOGO[nombre]
        if clase.necesita_clave:
            excluidos.append(
                {
                    "proveedor": nombre,
                    "motivo": (
                        "requiere clave gratuita y el alta la hace el usuario: crear credenciales "
                        "está en la lista negra del agente"
                    ),
                }
            )
            continue
        usables.append(clase())
    if not usables:
        raise FuentesError(f"el perfil {perfil['nicho']!r} no deja ni un proveedor usable; excluidos: {excluidos}")
    return usables, excluidos


def nicho_del_canal() -> str | None:
    """El nicho que declara el canal activo en su perfil (`nicho.id`), si hay canal."""
    from lib.config import CANAL_PERFIL

    return ((CANAL_PERFIL or {}).get("nicho") or {}).get("id")
