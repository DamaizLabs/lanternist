"""Lo que necesitan todos los tests antes de importar nada del proyecto.

1. **La raíz del repo en el path**, una vez para todos (antes cada fichero lo repetía).
2. **El canal activo es el de ejemplo** (`canales/example/`), salvo que el entorno ya traiga otro.
   `lib/config.py` lee `CANAL_ACTIVO` al importarse, así que tiene que estar puesto aquí, antes que
   cualquier `from lib import ...`. Sin esto la suite dependía del `.env` de quien la corre: en un clon
   recién descargado no hay `.env`, el canal quedaba vacío y 32 pruebas fallaban por eso
   (`progress/impl_OC1.0.md`). Con un `.env` que nombra otro canal, la suite sigue usando el de ejemplo:
   `load_dotenv` no pisa una variable que ya está en el entorno, y así el resultado no depende de la
   máquina. Quien quiera correrla contra su canal lo exporta en la consola antes de lanzarla.
"""

import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

CANAL_DE_EJEMPLO = "example"
os.environ.setdefault("CANAL_ACTIVO", CANAL_DE_EJEMPLO)


@pytest.fixture
def marca_falsa(monkeypatch):
    """La marca de IA (OC1.5) sin GPU ni `.venv-escena`, para las pruebas de las etapas que la llaman.

    Sustituye a `marca_ia.marca_video` y a `marca_ia.marca_imagen`: copia el fichero tal cual y devuelve un registro con
    la forma del de verdad (y su sha256, que es lo que mira la guarda de la subida). `registro(ruta)` da ese registro
    para escribirlo a mano en un `montaje.json` o un `miniatura.json`. La marca de verdad se prueba en
    `tests/test_marca_ia.py`.
    """
    import shutil

    from lib import marca_ia

    def registro(ruta) -> dict:
        ruta = Path(ruta)
        sha = marca_ia.sha256_de(ruta)
        comprobacion = {
            "file": ruta.name,
            "sha256": sha,
            "device": "cpu",
            "c2pa": {
                "supported": True,
                "manifest": True,
                "state": "Valid",
                "failures": ["signingCredential.untrusted"],
                "generator": "Lanternist prueba",
                "signer": "Lanternist local signer",
                "ai": True,
                "error": None,
            },
            "image": {"bits": 256, "matches": 256, "p_value": marca_ia.p_valor(256, 256), "frames": 1},
            "audio": None,
            "seconds": 0.0,
        }
        modelos = {
            clave: {k: marca_ia.MODELOS[clave][k] for k in ("nombre", "licencia", "fuente", "sha256")}
            for clave in marca_ia.MODELOS
        }
        return {
            "fichero": ruta.name,
            "sha256": sha,
            "detectada": True,
            "modelos": modelos,
            "comprobacion": comprobacion,
            "segundos": 0.0,
            "prueba": "marca falsa: el fichero no lleva la marca de verdad",
        }

    def marca(origen, destino, **_):
        if Path(origen).resolve() != Path(destino).resolve():
            shutil.copyfile(origen, destino)
        marca.hechas.append(Path(destino).name)
        return registro(destino)

    marca.hechas = []
    marca.registro = registro
    monkeypatch.setattr(marca_ia, "marca_video", marca)
    monkeypatch.setattr(marca_ia, "marca_imagen", marca)
    return marca
