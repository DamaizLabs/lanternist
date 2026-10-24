r"""La guarda de licencias (OC1.2): en el repositorio solo entra lo que su licencia deja redistribuir.

    .venv\Scripts\python scripts\guarda_licencias.py              # sobre lo versionado en git
    .venv\Scripts\python scripts\guarda_licencias.py <carpeta>    # sobre una carpeta: la exportación (OC1.9)

**Qué comprueba.**

1. **Cada fichero con autor propio** figura en el `CREDITOS.json` de su carpeta con fuente, licencia, url y el sha256
   que tiene de verdad: un asset (fuente, audio, imagen, icono o vídeo), un peso de modelo (`.gguf`, `.pt`, `.onnx`…) o
   un paquete (`.zip`, `.7z`). Y su licencia es de las que dejan redistribuir (`LIBRES`). Los efectos de Pixabay no: su
   licencia no deja distribuirlos sueltos, así que se instalan (`scripts/instala_efectos.py`). Los pesos, igual: los
   baja `instala.py` desde su origen.
2. **Cada fuente OFL lleva al lado el texto de su licencia**, el que nombra `texto_de_la_licencia` en su entrada: la
   OFL lo pide al redistribuir la fuente.
3. **Ningún JavaScript ni ninguna página HTML llevan GSAP dentro**: su licencia, la «Standard No Charge», no da permiso
   para redistribuirlo, y se instala con npm. Se reconoce por la URL de esa licencia, que va en su cabecera, también
   cuando se pega dentro de un `<script>` de una página.
4. **`THIRD_PARTY_NOTICES.md` existe** y nombra lo que tiene que nombrar: el fork de origen con su commit, «Built with
   Llama», GSAP, Pixabay y cada peso que piden los workflows de imagen y música (`workflows/*.json → modelo.pesos`).
   Un workflow con un peso nuevo no pasa hasta que el aviso diga de dónde sale y con qué licencia.

**Qué no comprueba.** Si la licencia apuntada es la verdadera: eso se comprueba en su fuente oficial, nunca de memoria,
y se escribe con su fecha en `THIRD_PARTY_NOTICES.md` y en el `CREDITOS.json` de cada carpeta.

Sobre una carpeta, recorre todos sus ficheros salvo `.git`, `node_modules`, los entornos y las cachés de Python: lo
que hay, y no lo que git dice. No usa la red. Código de salida 0 si no hay hallazgos.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CREDITOS = "CREDITOS.json"
AVISOS = "THIRD_PARTY_NOTICES.md"

# Lo que tiene autor y licencia propios: lo que puede salir en un vídeo o en una imagen (fuentes, audio, imágenes,
# iconos y vídeo), los pesos de un modelo y los paquetes, que pueden llevar cualquiera de las dos cosas dentro.
ASSET = re.compile(
    r"\.(ttf|otf|woff2?|wav|mp3|flac|m4a|ogg|opus|aac|aiff?|wma|png|jpe?g|webp|gif|bmp|tiff?|svg|ico|mp4|mov|webm|mkv"
    r"|gguf|pt|pth|onnx|safetensors|ckpt|bin|zip|7z)$",
    re.I,
)
FUENTE = re.compile(r"\.(ttf|otf|woff2?)$", re.I)
# Las licencias que dejan redistribuir el fichero tal cual, por cómo empieza la licencia apuntada.
LIBRES = ("SIL Open Font License", "CC0", "MIT", "Apache-2.0", "BSD")
OFL = "SIL Open Font License"
# La cabecera de GSAP: «Subject to the terms at https://gsap.com/standard-license».
GSAP = "gsap.com/standard-license"
# Donde puede ir GSAP: un JavaScript suelto o el `<script>` de una página.
CON_SCRIPT = re.compile(r"\.(m?js|cjs|html?)$", re.I)
# Lo que el aviso tiene que nombrar siempre, con el motivo.
EN_EL_AVISO = {
    "yashaiguy-dev": "el titular del fork de origen (MIT)",
    "e92c845": "el commit del fork de origen",
    "Built with Llama": "la atribución que pide la licencia de Llama 3.2 por Orpheus",
    "Llama 3.2 Community License": "la licencia de Orpheus",
    "GSAP": "GSAP y su licencia «Standard No Charge»",
    "Pixabay": "los efectos de sonido y su licencia",
}
# Carpetas que no son del repositorio: dependencias instaladas, entornos y cachés.
FUERA = {".git", "node_modules", "__pycache__", ".venv", ".venv-voz", ".venv-escena", ".pytest_cache", ".ruff_cache"}


def ficheros_de_git(raiz: Path) -> list[str]:
    """Lo versionado (`git ls-files`), con rutas relativas y barras normales."""
    salida = subprocess.run(["git", "ls-files"], cwd=raiz, capture_output=True, text=True, check=True).stdout
    return [linea for linea in salida.splitlines() if linea]


def ficheros_de_la_carpeta(raiz: Path) -> list[str]:
    """Todo lo que hay en la carpeta, salvo `FUERA`."""
    return sorted(
        p.relative_to(raiz).as_posix()
        for p in raiz.rglob("*")
        if p.is_file() and not FUERA.intersection(p.relative_to(raiz).parts)
    )


def _creditos(raiz: Path, carpeta: str, cache: dict) -> dict | None:
    if carpeta not in cache:
        ruta = raiz / carpeta / CREDITOS
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else None
        except ValueError:
            datos = None
        cache[carpeta] = datos.get("ficheros") if isinstance(datos, dict) else None
    return cache[carpeta]


def _assets(raiz: Path, ficheros: list[str]) -> list[str]:
    hallazgos, cache = [], {}
    presentes = set(ficheros)
    for rel in ficheros:
        if not ASSET.search(rel):
            continue
        carpeta, nombre = Path(rel).parent.as_posix(), Path(rel).name
        ficha = (_creditos(raiz, carpeta, cache) or {}).get(nombre)
        if not isinstance(ficha, dict):
            hallazgos.append(f"{rel}: no figura en {carpeta}/{CREDITOS}, así que nadie ha escrito de dónde sale")
            continue
        faltan = [c for c in ("fuente", "licencia", "url", "sha256") if not ficha.get(c)]
        if faltan:
            hallazgos.append(f"{rel}: a su entrada de {CREDITOS} le falta {', '.join(faltan)}")
            continue
        licencia = str(ficha["licencia"]).strip()
        if not licencia.startswith(LIBRES):
            hallazgos.append(
                f"{rel}: su licencia («{licencia[:60]}») no deja redistribuirlo; se instala desde su origen con su "
                "sha256 (como los efectos de Pixabay, `scripts/instala_efectos.py`) y no entra en el repositorio"
            )
            continue
        if hashlib.sha256((raiz / rel).read_bytes()).hexdigest() != ficha["sha256"]:
            hallazgos.append(f"{rel}: su sha256 no es el de {CREDITOS}; el fichero cambió sin cambiar su procedencia")
        if FUENTE.search(rel) and licencia.startswith(OFL):
            texto = ficha.get("texto_de_la_licencia")
            if not texto or f"{carpeta}/{texto}" not in presentes:
                hallazgos.append(f"{rel}: es OFL y no lleva al lado el texto de su licencia (`texto_de_la_licencia`)")
    return hallazgos


def _gsap(raiz: Path, ficheros: list[str]) -> list[str]:
    return [
        f"{rel}: lleva GSAP dentro, y su licencia no deja redistribuirlo; se instala con `cd motor; npm ci`"
        for rel in ficheros
        if CON_SCRIPT.search(rel) and GSAP in (raiz / rel).read_text(encoding="utf-8", errors="replace")
    ]


def _aviso(raiz: Path, ficheros: list[str]) -> list[str]:
    if AVISOS not in ficheros:
        return [f"{AVISOS}: no está, y es donde se declaran las licencias de terceros"]
    texto = (raiz / AVISOS).read_text(encoding="utf-8")
    hallazgos = [
        f"{AVISOS}: no nombra «{clave}» ({por_que})" for clave, por_que in EN_EL_AVISO.items() if clave not in texto
    ]
    for rel in ficheros:
        if not (rel.startswith("workflows/") and rel.endswith(".json")):
            continue
        try:
            pesos = json.loads((raiz / rel).read_text(encoding="utf-8")).get("modelo", {}).get("pesos", [])
        except (ValueError, AttributeError):
            continue
        for peso in pesos:
            if Path(peso).name not in texto:
                hallazgos.append(f"{AVISOS}: no dice de dónde sale ni con qué licencia el peso «{peso}» ({rel})")
    return hallazgos


def hallazgos(raiz: Path, ficheros: list[str]) -> list[str]:
    """Lo que la guarda no deja pasar en `ficheros` (rutas relativas a `raiz`), cada uno con su motivo."""
    raiz = Path(raiz)
    return _assets(raiz, ficheros) + _gsap(raiz, ficheros) + _aviso(raiz, ficheros)


def main(argv: list[str]) -> int:
    if argv:
        raiz = Path(argv[0]).resolve()
        ficheros = ficheros_de_la_carpeta(raiz)
    else:
        raiz = RAIZ
        ficheros = ficheros_de_git(raiz)
    encontrados = hallazgos(raiz, ficheros)
    for h in encontrados:
        print(f"[FAIL] {h}")
    if encontrados:
        return 1
    print(f"[OK] licencias: {len(ficheros)} ficheros, ninguno sin permiso para redistribuirlo")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
