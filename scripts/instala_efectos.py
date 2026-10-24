"""Instala los efectos de sonido de la biblioteca del estudio desde HyperFrames, comprobando su sha256 (OC1.2).

    cd motor; npm ci; cd ..
    .venv\\Scripts\\python scripts\\instala_efectos.py

**Por qué no viajan en el repositorio.** Los nueve efectos (`datos/escena/sfx/CREDITOS.json`) son de Pixabay, y su
licencia no deja distribuir sus ficheros sueltos, sin una obra encima (análisis §2.1). HyperFrames los trae dentro de
su paquete de npm, byte a byte los mismos. Así que el repositorio guarda solo la lista con el sha256 de cada uno, y
este script los copia a la biblioteca al instalar (fila 303: «se descarga cuando se necesite al instalarlo»). Lo
llamará el instalador (OC1.7).

**Un sha256 distinto se niega.** Si un fichero de HyperFrames no es el que se comprobó, no se copia ninguno: una
versión nueva del paquete podría traer otro sonido con otra licencia, y su procedencia no la ha escrito nadie
(decisión 5). Para aceptarlo hay que comprobarlo y actualizar su entrada en `CREDITOS.json`.

Se puede repetir: lo que ya está con su sha256 no se vuelve a copiar, y lo que está cambiado se sustituye. No usa la
red: lee de `motor/node_modules`.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import config  # noqa: E402
from lib.escena.audio import lee_creditos  # noqa: E402


class ErrorDeInstalacion(RuntimeError):
    """Los efectos no se pueden instalar: el mensaje dice cuál falla y por qué."""


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def instala_efectos(origen: Path = config.HYPERFRAMES_SFX_DIR, destino: Path = config.ESCENA_SFX_DIR) -> list[str]:
    """Copia de `origen` a `destino` cada efecto del `CREDITOS.json` de `destino`. Devuelve los que copió.

    Primero comprueba todos y después copia: si uno falta o tiene otro sha256, para sin copiar ninguno.
    """
    origen, destino = Path(origen), Path(destino)
    creditos = lee_creditos(destino)
    fallos = []
    for nombre, ficha in sorted(creditos.items()):
        fichero = origen / nombre
        esperado = (ficha or {}).get("sha256")
        if not fichero.is_file():
            fallos.append(f"«{nombre}» no está en {origen}: instala HyperFrames con `cd motor; npm ci`")
        elif (sha := _sha256(fichero)) != esperado:
            fallos.append(
                f"«{nombre}» tiene otro sha256 ({sha[:12]}… frente a {str(esperado)[:12]}… de "
                f"{config.ESCENA_CREDITOS}): no es el fichero que se comprobó, así que no se copia"
            )
    if fallos:
        raise ErrorDeInstalacion("; ".join(fallos))
    copiados = []
    for nombre, ficha in sorted(creditos.items()):
        final = destino / nombre
        if final.is_file() and _sha256(final) == ficha["sha256"]:
            continue
        shutil.copyfile(origen / nombre, final)
        copiados.append(nombre)
    return copiados


def main() -> int:
    try:
        copiados = instala_efectos()
    except ErrorDeInstalacion as e:
        print(f"[FAIL] {e}")
        return 1
    total = len(lee_creditos(config.ESCENA_SFX_DIR))
    print(f"[OK] {total} efectos en {config.ESCENA_SFX_DIR}, cada uno con su sha256: {len(copiados)} copiados ahora")
    return 0


if __name__ == "__main__":
    sys.exit(main())
