"""Módulo de fuentes con autoridad, universal por nicho (F2.9).

Encargo del 24-08: «tendríamos que construir un módulo que responda a la búsqueda de
fuentes según necesidad… tiene que ser universal para cualquier nicho». Diseño en
`doc/modulo-fuentes.md`; el problema que lo motiva, en `doc/fuente-de-autoridad.md`.

Cinco piezas, cada una con una responsabilidad:

- `base` — contrato del proveedor, HTTP sin reintentos y ledger de llamadas.
- `proveedores/` — un adaptador por API. Añadir uno es un archivo más y una línea en `CATALOGO`.
- `registro` — carga el perfil de autoridad del nicho (**capa de estudio**) y decide qué
  proveedores entran.
- `verificacion` — el resolutor. La pieza central: lo que no resuelve, no existe.
- `ficha` — la unidad que el gate 1 comprueba (**capa de canal**), con su validación.
"""

from lib.fuentes import base, ficha, registro, verificacion

__all__ = ["base", "ficha", "registro", "verificacion"]
