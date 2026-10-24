r"""¿Siguen al día las skills que automatizan el estudio? La guarda de la fila 271.

Correr:  .venv\Scripts\python scripts/comprueba_skills.py

## Por qué existe

`crea-canal` y `produce-semana` automatizan el estudio, junto con las skills a las que llaman: `pone-en-escena` y
`script-to-slides` (`descubre-estilos` era la quinta, y se borró con el buscador en OC1.1). La regla del
06-10-2026 (fila 271) dice que un cambio de canal, motor, formato o módulo no se cierra sin mirarlas. Una regla se
olvida, así que esto la convierte en una guarda para lo que se puede medir. Nació de la revisión de ese día:
`script-to-slides` no conocía el formato «pizarra», que había entrado en el catálogo el 05-10, y `produce-semana`
mandaba correr scripts sobre el canal del `.env`.

## Qué comprueba

1. **Formatos**: cada formato del motor (`lib/escena/ajustes.py → FORMATOS`) tiene su ficha en el catálogo público,
   `docs/formats.md`, que es el único sitio con el estado de cada formato (OC1.11). Y lo nombran, como `nombre` o
   «nombre», las skills que producen (`SKILLS_QUE_PRODUCEN`). La que propone el formato de un vídeo
   (`SKILL_QUE_ELIGE_FORMATO`) no los nombra uno a uno: lee el catálogo, y lo que se le pide es que lo cite.
2. **Canales**: el formato de cada canal de `canales/` tiene ficha en el catálogo, y la ficha lo cuenta en su línea
   «**Channels**» (el catálogo está en inglés).
3. **Órdenes y rutas** de todas las skills del proyecto: cada script que una skill manda correr con `python` existe, y
   cada opción `--algo` que le pasa está escrita en su código; cada ruta del repositorio que cita existe. Una ruta con
   un hueco (`canales/<id>/…`) no se comprueba, ni las que ignora el `.gitignore` (`experimentos/`, los vídeos de cada
   canal, las páginas generadas), que en un clon limpio no tienen por qué estar.
4. **El arnés del dueño** (OC1.6): las skills que viajan al repositorio público (las que nombra
   `exportacion/lista-blanca.txt`, o todas donde no hay lista) no citan `doc/`, `progress/`, `CHECKPOINTS.md` ni las
   filas del addendum, porque allí no existen. El porqué se dice en palabras, o se cita `docs/` o el código.

## Qué NO comprueba

Si lo que dice una skill sigue siendo cierto: que un canal no declare etiquetas de voz, por ejemplo. Eso sigue siendo la
regla, y lo mira quien cierra el cambio.

No sale a la red ni toca la GPU: lee ficheros. Código de salida 0 si no hay hallazgos.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections.abc import Sequence
from fnmatch import fnmatchcase
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

SKILLS = Path(".claude") / "skills"
CATALOGO = Path("docs") / "formats.md"
# Las skills que producen un episodio y tienen que saber qué cambia en cada formato.
SKILLS_QUE_PRODUCEN = ("produce-semana", "pone-en-escena", "script-to-slides")
# La que propone el formato de un vídeo pegado (OC1.11): lo busca en el catálogo, así que basta con que lo cite. Hasta
# OC1.11 era `crea-canal`. La historia interna de los formatos (`doc/10-catalogo-de-formatos.md`) no viaja al
# repositorio público, así que ninguna skill que viaja la cita (`ARNES_DEL_DUENO`).
SKILL_QUE_ELIGE_FORMATO = "propone-formato"
# Lo que dice qué skills viajan al repositorio público. Allí no existe: todas las que lleva son públicas.
LISTA_BLANCA = Path("exportacion") / "lista-blanca.txt"
# El arnés del dueño, que no viaja: una skill pública que lo cita manda a quien la usa a un fichero que no tiene.
ARNES_DEL_DUENO = (
    ("doc/", re.compile(r"(?<![\w./-])doc/")),
    ("progress/", re.compile(r"(?<![\w./-])progress/")),
    ("CHECKPOINTS.md", re.compile(r"\bCHECKPOINTS\b")),
    ("una fila del addendum", re.compile(r"\bfilas? \d+", re.I)),
)

# Las carpetas del repositorio cuyas rutas se comprueban. `experimentos/` y `logs/` no están: git las ignora enteras.
# `descubrimiento/` se borró con el buscador en OC1.1 y se queda aquí a propósito: una skill que aún la cite sale como
# ruta muerta en vez de pasar sin mirar.
RAICES = (
    r"\.claude",
    "canales",
    "datos",
    "descubrimiento",
    "doc",
    "lib",
    "motor",
    "progress",
    "scripts",
    "spikes",
    "tests",
    "workflows",
)
RUTA = re.compile(r"(?<![\w./\\<>-])((?:%s)/[\w./-]*[\w/])" % "|".join(RAICES))
# Lo que sigue a una ruta hasta el final de su palabra: si lleva un hueco, la ruta entera es una plantilla.
COLA = re.compile(r"[^\s`'\")\]]*")
# Una plantilla, no una ruta: `canales/<id>/…`, `{x}`, `*.json`, `auditoria-AAAA-MM-DD.md`, `gate0_C00N.md`, `X.py`.
HUECO = re.compile(r"[<{*…]|AAAA|C00N|(?<![\w-])X\.py")
# Rutas que una skill cita sabiendo que no existen, cada una con su motivo. Se añade aquí, nunca se silencia sin él.
NO_SON_RUTAS = {
    "workflows/archivo": "audit-proyecto comprueba que NO existe: un workflow retirado se borra",
}
REFERENCIA = re.compile(r"(?<![\w/.-])references/([\w.-]+\.md)")
# Una orden: `python <script>.py …` (también `.venv\Scripts\python …`). `python -m …` no se comprueba.
ORDEN = re.compile(r"python(?:\.exe)?\s+(?!-)([\w./\\-]+\.py)\b")
OPCION = re.compile(r"(?<![\w-])--([a-z][\w-]*)")
# Donde acaba la orden en la línea: un comentario, otra orden encadenada o el cierre del código en línea.
FIN_DE_ORDEN = re.compile(r"\s#|;|\||&&|`")


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)).lower()


def _ficheros_de(skill: Path) -> list[Path]:
    """El `SKILL.md` de una skill y sus `references/*.md`, que es lo que lee quien la usa."""
    return [f for f in (skill / "SKILL.md", *sorted((skill / "references").glob("*.md"))) if f.is_file()]


def _nombra(texto: str, formato: str) -> bool:
    """¿Nombra el texto este formato como formato? Como `pizarra` o «pizarra»; «láminas» vale por `laminas`."""
    t = _sin_tildes(texto)
    return f"`{formato}`" in t or f"«{formato}»" in t


def _fichas_del_catalogo(texto: str) -> dict[str, str]:
    """{formato: su sección del catálogo}. Una ficha empieza en «### `nombre`» y acaba en el título siguiente."""
    fichas = {}
    for trozo in re.split(r"(?m)^### ", texto)[1:]:
        m = re.match(r"`([\w-]+)`", trozo)
        if m:
            fichas[m.group(1)] = re.split(r"(?m)^##? ", trozo)[0]
    return fichas


def _formatos_y_canales(raiz: Path, formatos: Sequence[str]) -> list[str]:
    from lib.escena import ajustes

    hallazgos = []
    ruta_catalogo = raiz / CATALOGO
    fichas = _fichas_del_catalogo(ruta_catalogo.read_text(encoding="utf-8")) if ruta_catalogo.is_file() else {}
    for formato in formatos:
        if formato not in fichas:
            hallazgos.append(f"{CATALOGO.as_posix()}: el formato `{formato}` no tiene ficha («### `{formato}`»)")
        for nombre in SKILLS_QUE_PRODUCEN:
            skill = raiz / SKILLS / nombre
            if not any(_nombra(f.read_text(encoding="utf-8"), formato) for f in _ficheros_de(skill)):
                hallazgos.append(
                    f"{nombre}: no nombra el formato `{formato}`, y produce episodios en él: di qué cambia en ese "
                    "formato"
                )
    elige = raiz / SKILLS / SKILL_QUE_ELIGE_FORMATO
    if not any(CATALOGO.as_posix() in f.read_text(encoding="utf-8") for f in _ficheros_de(elige)):
        hallazgos.append(
            f"{SKILL_QUE_ELIGE_FORMATO}: no cita el catálogo ({CATALOGO.as_posix()}), del que elige el formato"
        )

    for carpeta in sorted((raiz / "canales").glob("*/perfil.json")):
        canal = carpeta.parent.name
        try:
            formato = ajustes.formato(json.loads(carpeta.read_text(encoding="utf-8")))
        except (ValueError, ajustes.ErrorDeAjustes) as error:
            hallazgos.append(f"canales/{canal}/perfil.json: no se sabe su formato: {error}")
            continue
        codigo = canal.split("-")[0]
        ficha = fichas.get(formato)
        if ficha is None:
            hallazgos.append(f"canales/{canal}: produce en `{formato}`, y el catálogo no tiene su ficha")
        elif not re.search(rf"\*\*Channels\*\*:[^\n]*\b{re.escape(codigo)}\b", ficha):
            hallazgos.append(
                f"{CATALOGO.as_posix()}: la ficha de `{formato}` no cuenta {codigo} en su línea «**Channels**», y "
                f"{canal} produce en ella"
            )
    return hallazgos


def _patrones_ignorados(raiz: Path) -> list[str]:
    """Los patrones del `.gitignore` del repositorio, sin los comentarios ni las excepciones (`!…`)."""
    try:
        lineas = (raiz / ".gitignore").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [p.strip().strip("/").replace("**/", "*") for p in lineas if p.strip() and not p.startswith(("#", "!"))]


def _ignorada(ruta: str, patrones: Sequence[str]) -> bool:
    """¿La ignora git? Una página o un vídeo que se generan no tienen por qué estar en un clon limpio.

    Se lee el `.gitignore` y no una lista copiada aquí, que se quedaría vieja. Un patrón sin «/» vale en cualquier
    carpeta (`*.wav`), y uno con «/» se compara con la ruta y con cada carpeta que la contiene (`canales/*/videos/`).
    """
    partes = ruta.rstrip("/").split("/")
    prefijos = ["/".join(partes[:i]) for i in range(1, len(partes) + 1)]
    for patron in patrones:
        if "/" in patron:
            if any(fnmatchcase(p, patron) for p in prefijos):
                return True
        elif any(fnmatchcase(parte, patron) for parte in partes):
            return True
    return False


def _ordenes_y_rutas(raiz: Path) -> list[str]:
    hallazgos = []
    ignorados = _patrones_ignorados(raiz)
    referencias = {f.name for f in (raiz / SKILLS).glob("*/references/*.md")}
    for skill in sorted(p for p in (raiz / SKILLS).iterdir() if p.is_dir()):
        for fichero in _ficheros_de(skill):
            donde = fichero.relative_to(raiz / SKILLS).as_posix()
            for n, linea in enumerate(fichero.read_text(encoding="utf-8").splitlines(), start=1):
                hallazgos += _revisa_ordenes(raiz, linea, f"{donde}:{n}")
                hallazgos += _revisa_rutas(raiz, skill, linea, f"{donde}:{n}", ignorados)
                for m in REFERENCIA.finditer(linea):
                    # Una skill cita a veces las referencias de otra:
                    # «`pone-en-escena`, `references/formato-pizarra.md`».
                    if m.group(1) not in referencias:
                        hallazgos.append(f"{donde}:{n}: cita references/{m.group(1)} y no existe en ninguna skill")
    return hallazgos


def _revisa_ordenes(raiz: Path, linea: str, donde: str) -> list[str]:
    hallazgos = []
    ordenes = list(ORDEN.finditer(linea))
    for i, m in enumerate(ordenes):
        script = m.group(1).replace("\\", "/")
        if HUECO.search(script):
            continue
        # Una orden se lanza desde la raíz del repositorio, así que su script se busca solo ahí.
        ruta = raiz / script
        if not ruta.is_file():
            hallazgos.append(f"{donde}: manda correr {script} y no existe")
            continue
        resto = linea[m.end() : ordenes[i + 1].start() if i + 1 < len(ordenes) else len(linea)]
        corte = FIN_DE_ORDEN.search(resto)
        resto = resto[: corte.start()] if corte else resto
        codigo = ruta.read_text(encoding="utf-8")
        for opcion in OPCION.findall(resto):
            if f'"--{opcion}"' not in codigo and f"'--{opcion}'" not in codigo:
                hallazgos.append(f"{donde}: pasa --{opcion} a {script}, y {script} no conoce esa opción")
    return hallazgos


def _revisa_rutas(raiz: Path, skill: Path, linea: str, donde: str, ignorados: Sequence[str]) -> list[str]:
    hallazgos = []
    for m in RUTA.finditer(linea):
        ruta = m.group(1)
        palabra = ruta + COLA.match(linea, m.end()).group(0)
        if HUECO.search(palabra) or _ignorada(ruta, ignorados) or ruta.rstrip("/") in NO_SON_RUTAS:
            continue
        # El script de una orden ya lo revisa `_revisa_ordenes`: contarlo otra vez sería el mismo fallo dos veces.
        if any(ruta == m.group(1).replace("\\", "/") for m in ORDEN.finditer(linea)):
            continue
        if not any(_existe(base, ruta) for base in (raiz, skill)):
            hallazgos.append(f"{donde}: cita {ruta} y no existe")
    return hallazgos


def _existe(base: Path, ruta: str) -> bool:
    """¿Existe la ruta bajo `base`? También en las dos formas cortas que usa el proyecto al citar.

    - `lib/traduccion.exige_al_dia`: un módulo y algo de dentro, en la notación de Python.
    - `doc/07`: un documento por su número, que es como el proyecto abrevia `doc/07-guia-…md`.
    """
    camino = base / ruta.rstrip("/")
    if camino.exists():
        return True
    modulo = ruta.rpartition(".")[0]
    if modulo and (base / f"{modulo}.py").is_file():
        return True
    return camino.parent.is_dir() and any(camino.parent.glob(f"{camino.name}-*"))


def _skills_publicas(raiz: Path) -> list[Path]:
    """Las skills que viajan al repositorio público: las que nombra la lista blanca, o todas donde no la hay."""
    skills = sorted(p for p in (raiz / SKILLS).iterdir() if p.is_dir())
    if not (raiz / LISTA_BLANCA).is_file():
        return skills
    from scripts.guarda_datos_personales import en_la_lista_blanca, lee_lista_blanca

    lista = lee_lista_blanca(raiz)
    return [s for s in skills if en_la_lista_blanca((s / "SKILL.md").relative_to(raiz).as_posix(), lista)]


def _arnes_del_dueno(raiz: Path) -> list[str]:
    hallazgos = []
    for skill in _skills_publicas(raiz):
        for fichero in _ficheros_de(skill):
            donde = fichero.relative_to(raiz / SKILLS).as_posix()
            for n, linea in enumerate(fichero.read_text(encoding="utf-8").splitlines(), start=1):
                hallazgos += [
                    f"{donde}:{n}: cita {que}, que es del arnés del dueño y no viaja al repositorio público: dilo en "
                    "palabras, o cita docs/ o el código"
                    for que, patron in ARNES_DEL_DUENO
                    if patron.search(linea)
                ]
    return hallazgos


def comprueba(raiz: Path = RAIZ, formatos: Sequence[str] | None = None) -> list[str]:
    """Todos los hallazgos, uno por línea («dónde: qué»). Vacío si las skills están al día con el código."""
    if formatos is None:
        from lib.escena.ajustes import FORMATOS

        formatos = FORMATOS
    return _formatos_y_canales(raiz, formatos) + _ordenes_y_rutas(raiz) + _arnes_del_dueno(raiz)


def main() -> int:
    hallazgos = comprueba()
    for h in hallazgos:
        print(h)
    if hallazgos:
        print(f"[FAIL] {len(hallazgos)} desfase(s) entre las skills y el código")
        return 1
    print("[OK] las skills nombran todos los formatos y canales, y sus órdenes y rutas existen")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(RAIZ))
    sys.exit(main())
