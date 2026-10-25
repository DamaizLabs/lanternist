r"""La guarda de datos personales (OC1.3): al repositorio público no va nada del dueño de esta fábrica.

    .venv\Scripts\python scripts\guarda_datos_personales.py              # lo que nombra la lista blanca, en git
    .venv\Scripts\python scripts\guarda_datos_personales.py <carpeta>    # sobre una carpeta: la exportación (OC1.9)

**Qué busca**, en el texto de cada fichero y en su ruta:

1. **Patrones genéricos**, que valen en cualquier repositorio (`GENERICOS`): una clave con su formato real, un id de
   canal de YouTube (`UC` y 22 caracteres), un email, una carpeta de usuario de Windows y la carpeta de herramientas
   compartidas de este PC.
2. **Las cadenas personales** de `exportacion/datos-personales.json`: el nombre, el usuario de Windows y el email del
   dueño, y los ids, los handles y los nombres de los canales del estudio. No se escriben aquí porque esta guarda viaja
   al repositorio público: escritas dentro, las publicaría. Una cadena de varias palabras se caza también con otros
   separadores, o sin ninguno, y partida en dos líneas (`Una_Cadena`, `UnaCadena`, `Una` y `# Cadena`).

**Las excepciones decididas** van en el mismo fichero privado, en `se_permite`: un fichero y el texto exacto que puede
llevar aunque contenga una cadena personal. Hoy hay una: la línea de copyright de `LICENSE`, cuyo titular es la marca
con la que se publica el motor. En cualquier otro fichero, o con otro texto, la cadena sigue contando.

**Falla cerrada.** En esta fábrica, que se reconoce por su arnés (`MARCAS_DE_LA_FABRICA`), no corre sin el fichero de
cadenas personales. En el repositorio público, donde ese fichero no existe, corre solo con los genéricos.

**Qué recorre.** Sobre git, lo versionado y lo nuevo que git no ignora, filtrado por la lista blanca
(`exportacion/lista-blanca.txt`); donde no hay lista blanca (el repositorio público), todo lo versionado, y nada de
lo que aún no tiene commit: los runs de quien usa el motor guardan la carpeta de su usuario. Sobre una carpeta, todos
sus ficheros salvo `.git`, las dependencias, los entornos y las cachés: los mismos que mira la guarda de licencias.

**Qué no comprueba.** Los binarios (fuentes e imágenes): lo que llevan dentro es de su autor, y su procedencia la vigila
la guarda de licencias. El texto en UTF-16 sí se lee, con BOM o sin él: es lo que escribe `>` en PowerShell 5. Tampoco
mira el historial de git: por eso el repositorio público nace sin historial.

No usa la red. Código de salida: 0 sin hallazgos, 1 con hallazgos, 2 si falta el fichero de cadenas personales y 3 si,
sin carpeta, no puede preguntarle a git (fuera de un repositorio, o sin git instalado).
"""

from __future__ import annotations

import codecs
import json
import re
import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from scripts.guarda_licencias import ficheros_de_la_carpeta  # noqa: E402

LISTA_BLANCA = "exportacion/lista-blanca.txt"
CADENAS_PERSONALES = "exportacion/datos-personales.json"
# El arnés del dueño. Si está en la raíz, esto es la fábrica y no el repositorio público, que nunca lo lleva.
MARCAS_DE_LA_FABRICA = ("exportacion", "progress", "CHECKPOINTS.md")

# Cada patrón, con lo que es. Están escritos de forma que su texto no los cumple: la guarda se recorre a sí misma.
_BARRA = r"(?:\\\\|\\|/)"
GENERICOS = (
    ("una clave de Google (API key)", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("un secreto de cliente OAuth de Google", re.compile(r"GOCSPX-[0-9A-Za-z_\-]{15,}")),
    ("un token de acceso de Google", re.compile(r"ya29\.[0-9A-Za-z_\-]{30,}")),
    ("un refresh token de Google", re.compile(r"1//0[0-9A-Za-z_\-]{25,}")),
    ("una clave de OpenAI o de Anthropic", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("un token de Hugging Face", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("un token de GitHub", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,})")),
    ("un token de Apify", re.compile(r"\bapify_api_[0-9A-Za-z]{20,}")),
    ("una URL con usuario y contraseña", re.compile(r"https?://[^\s/@:]+:[^\s/@]+@")),
    ("una clave privada", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("un id de canal de YouTube", re.compile(r"(?<![A-Za-z0-9_\-])UC[A-Za-z0-9_\-]{22}(?![A-Za-z0-9_\-])")),
    ("un email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")),
    # Una carpeta de usuario con nombre, también como la escriben Git Bash y WSL (`/c/Users/…`): `<usuario>` o
    # `%USERNAME%` no cuentan, porque no son de nadie.
    (
        "una carpeta de usuario de Windows",
        re.compile(rf"(?:\b[A-Za-z]:{_BARRA}|/[A-Za-z]/)Users{_BARRA}[A-Za-z0-9]", re.I),
    ),
    ("la carpeta de herramientas de este PC", re.compile(rf"\b[Cc]:{_BARRA}IA(?:{_BARRA}|\b)", re.I)),
)
# Los emails de terceros que pueden viajar: van en el texto de la licencia de su obra, que obliga a llevarlo.
EMAILS_DE_TERCEROS = {"mail@patrickwagesreiter.at"}  # Patrick Hand SC (OFL-PatrickHandSC.txt y su CREDITOS.json)


def lee_lista_blanca(raiz: Path = RAIZ) -> tuple[list[str], list[str]]:
    """Los patrones que meten y los que sacan (los de `!`), tal como los explica la cabecera de la lista."""
    lineas = [linea.strip() for linea in (raiz / LISTA_BLANCA).read_text(encoding="utf-8").splitlines()]
    patrones = [linea for linea in lineas if linea and not linea.startswith("#")]
    return [p for p in patrones if not p.startswith("!")], [p[1:] for p in patrones if p.startswith("!")]


def en_la_lista_blanca(rel: str, lista: tuple[list[str], list[str]]) -> bool:
    mete, saca = lista
    return any(fnmatchcase(rel, p) for p in mete) and not any(fnmatchcase(rel, p) for p in saca)


def ficheros_de_git(raiz: Path, lista: tuple[list[str], list[str]] | None) -> list[str]:
    """Rutas relativas. Con la lista blanca (la fábrica), lo versionado y lo nuevo que git no ignora, filtrado por
    ella: lo nuevo se caza antes de su commit. Sin ella (el repositorio público), solo lo versionado, como la guarda
    de licencias: lo que produce quien usa el motor, como el estado de un run con la carpeta de su usuario, no viaja
    mientras no haga commit."""
    orden = ["git", "ls-files", "-z", "--cached"]
    if lista is not None:
        orden += ["--others", "--exclude-standard"]
    salida = subprocess.run(orden, cwd=raiz, capture_output=True, check=True).stdout.decode("utf-8")
    rutas = sorted({r for r in salida.split("\0") if r and (raiz / r).is_file()})
    return [r for r in rutas if lista is None or en_la_lista_blanca(r, lista)]


def _fichero_privado(raiz: Path) -> dict:
    """El contenido de `CADENAS_PERSONALES`, o `{}` en el repositorio público. Falla cerrada si falta en la fábrica."""
    ruta = raiz / CADENAS_PERSONALES
    if not ruta.is_file():
        if any((raiz / marca).exists() for marca in MARCAS_DE_LA_FABRICA):
            raise FileNotFoundError(
                f"falta {CADENAS_PERSONALES}, y esto es la fábrica (lleva su arnés): sin las cadenas personales la "
                "guarda daría por limpio lo que no ha mirado"
            )
        return {}
    return json.loads(ruta.read_text(encoding="utf-8"))


def patron_de(texto: str, solo_palabra: bool = False) -> re.Pattern:
    """Una cadena como patrón: sin distinguir mayúsculas, y con sus palabras unidas por cualquier separador o ninguno.

    Así `Una Cadena` caza también `Una_Cadena`, `una-cadena`, `UnaCadena` y la cadena partida en dos líneas, aunque la
    segunda empiece por un `#` o un `//` de comentario.
    """
    palabras = [p for p in re.split(r"[\W_]+", texto) if p]
    patron = r"[\W_]*".join(re.escape(p) for p in palabras) if len(palabras) > 1 else re.escape(texto)
    if solo_palabra:
        patron = rf"(?<![0-9A-Za-z]){patron}(?![0-9A-Za-z])"
    return re.compile(patron, re.I)


def cadenas_personales(raiz: Path = RAIZ) -> list[tuple[str, re.Pattern]]:
    """Las cadenas de `CADENAS_PERSONALES`, cada una como patrón. Falla cerrada si falta en la fábrica."""
    return [
        (entrada["que_es"], patron_de(entrada["texto"], bool(entrada.get("solo_palabra"))))
        for entrada in _fichero_privado(raiz).get("cadenas", [])
    ]


def se_permite(raiz: Path = RAIZ) -> dict[str, list[str]]:
    """Las excepciones decididas de `CADENAS_PERSONALES`: por fichero, los textos exactos que puede llevar."""
    return _fichero_privado(raiz).get("se_permite", {})


def _fragmento(texto: str) -> str:
    """Lo encontrado, recortado: basta para localizarlo y no copia entera una clave en la consola."""
    return texto if len(texto) <= 12 else texto[:12] + "…"


def texto_de(contenido: bytes) -> str | None:
    """El texto de un fichero, o None si es binario. Lee UTF-8 y UTF-16, este con su BOM o sin él.

    Sin BOM, un UTF-16 se reconoce porque casi todos los bytes altos de sus caracteres son cero: así es el texto
    latino. Una fuente o una imagen también llevan bytes nulos, pero no en una posición de cada dos.
    """
    if contenido.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return contenido.decode("utf-16", errors="replace")
    if b"\0" not in contenido:
        return contenido.decode("utf-8", errors="replace")
    if len(contenido) % 2 == 0:
        for altos, codificacion in ((contenido[1::2], "utf-16-le"), (contenido[0::2], "utf-16-be")):
            if altos.count(0) >= 0.9 * len(altos):
                return contenido.decode(codificacion, errors="replace")
    return None


def hallazgos(
    raiz: Path,
    ficheros: list[str],
    cadenas: list[tuple[str, re.Pattern]],
    permitidos: dict[str, list[str]] | None = None,
) -> list[str]:
    """«ruta:línea: qué es («fragmento»)» por cada dato personal en `ficheros` (rutas relativas a `raiz`).

    `permitidos` son las excepciones decididas (`se_permite`): en ese fichero, su texto exacto no cuenta para las
    cadenas personales. Los patrones genéricos lo miran igual.
    """
    raiz = Path(raiz)
    permitidos = permitidos or {}
    encontrados = []
    for rel in ficheros:
        for que_es, patron in [*GENERICOS, *cadenas]:
            if m := patron.search(rel):
                encontrados.append(f"{rel}: su ruta lleva {que_es} («{_fragmento(m.group(0))}»)")
        texto = texto_de((raiz / rel).read_bytes())
        if texto is None:  # binario
            continue
        # El texto permitido se tapa con espacios del mismo largo: no cambia ni las líneas ni las posiciones.
        sin_lo_permitido = texto
        for permitido in permitidos.get(rel, []):
            sin_lo_permitido = sin_lo_permitido.replace(permitido, " " * len(permitido))
        for patrones, donde in ((GENERICOS, texto), (cadenas, sin_lo_permitido)):
            for que_es, patron in patrones:
                for m in patron.finditer(donde):
                    if que_es == "un email" and m.group(0) in EMAILS_DE_TERCEROS:
                        continue
                    linea = donde.count("\n", 0, m.start()) + 1
                    encontrados.append(f"{rel}:{linea}: {que_es} («{_fragmento(m.group(0))}»)")
    return encontrados


def main(argv: list[str]) -> int:
    try:
        cadenas, permitidos = cadenas_personales(RAIZ), se_permite(RAIZ)
    except FileNotFoundError as error:
        print(f"[FAIL] {error}")
        return 2
    if argv:
        raiz = Path(argv[0]).resolve()
        ficheros = ficheros_de_la_carpeta(raiz)
    else:
        raiz = RAIZ
        lista = lee_lista_blanca(RAIZ) if (RAIZ / LISTA_BLANCA).is_file() else None
        try:
            ficheros = ficheros_de_git(raiz, lista)
        except (OSError, subprocess.CalledProcessError):
            print(
                f"[FAIL] {raiz} no es un repositorio de git, o git no está instalado: pásale la carpeta que quieres "
                "mirar (`guarda_datos_personales.py <carpeta>`)"
            )
            return 3
    encontrados = hallazgos(raiz, ficheros, cadenas, permitidos)
    for h in encontrados:
        print(f"[FAIL] {h}")
    if encontrados:
        return 1
    print(
        f"[OK] datos personales: {len(ficheros)} ficheros, {len(GENERICOS)} patrones genéricos y {len(cadenas)} "
        "cadenas personales, sin ningún hallazgo"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
