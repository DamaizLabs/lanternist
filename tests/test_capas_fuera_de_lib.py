"""Las dos capas también fuera de `lib/`: en `scripts/`, en los puntos de entrada y en las skills.

**Por qué existe este fichero, medido el 16-09-2026.** `tests/test_capas.py` hace cumplir la regla de
F4.9 —ninguna decisión de canal en el estudio, y ninguna con defecto— pero mira **solo `lib/`**
(`(RAIZ / "lib").rglob("*.py")`). Un `/produce-semana` del segundo canal destapó **ocho** decisiones del primero
viviendo en el estudio, y **las ocho caían fuera de `lib/`**:

- `pipeline.py` inventaba el nombre de la variable de OAuth desde el id del canal, y exigía
  fichas de fuentes sin mirar si el nicho las lleva.
- `scripts/verifica_guion.py` medía el guion con el perfil del canal del `.env`: 24 fallos falsos.
- `scripts/pagina_calendario.py` afirmaba «las once fichas del canal» en un canal sin ninguna, y
  reventaba con `KeyError` si el episodio no declaraba ficha.
- `SKILL.md` y los briefs daban el ritmo del segundo canal desfasado y afirmaban que no llevaba capítulos
  cuando su perfil decía que sí.
- Su `perfil.json` tenía un comentario que decía lo contrario que su propio valor.

Todas son **la misma fuga**, y el patrón que las explica es el de la auditoría del 08-09: «está
protegido donde lo que protege es prosa». La regla estaba escrita en `doc/06`, en el `CLAUDE.md` y en
los briefs; lo que no había era un guardia. Aquí está.

**Lo que NO se prohíbe, porque es la forma correcta de escribir esto**: nombrar un canal para contar
su historia o para poner un ejemplo. Un docstring que explica por qué un umbral vale lo que vale
citando al primer canal es documentación valiosa. Lo que no puede pasar es que el estudio **decida** por un
canal, ni que afirme como vigente un dato que vive en su perfil.
"""

import ast
import json
import re
from pathlib import Path

import pytest
from canales_de_prueba import patron_de_id_de_canal

RAIZ = Path(__file__).resolve().parent.parent

# Un id completo de canal: `C00N-<nombre>`, o el nombre de una carpeta de `canales/` (`example`). El
# número a secas (`C101`) no basta para acusar, porque aparece en frases explicativas legítimas
# («C101 es el ejemplo calibrado»).
ID_DE_CANAL = patron_de_id_de_canal()


# Lo que es ESTUDIO y por tanto no puede decidir por un canal. `tests/` queda fuera a propósito:
# una prueba tiene que poder nombrar el canal que usa de caso.
def _modulos_del_estudio() -> list[Path]:
    fuera = sorted((RAIZ / "lib").rglob("*.py"))
    fuera += sorted((RAIZ / "scripts").rglob("*.py"))
    fuera += sorted(RAIZ.glob("*.py"))
    return fuera


def _docstrings(arbol: ast.AST) -> set[int]:
    return {
        id(n.body[0].value)
        for n in ast.walk(arbol)
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
        and isinstance(n.body[0].value.value, str)
    }


@pytest.mark.parametrize("modulo", _modulos_del_estudio(), ids=lambda p: str(p.relative_to(RAIZ)))
def test_ningun_modulo_del_estudio_nombra_un_canal_en_codigo(modulo: Path):
    """Un id de canal en código del estudio es el estudio decidiendo por un canal concreto.

    Es la misma regla que `test_capas.py` aplica a `lib/`, extendida a `scripts/` y a los puntos de
    entrada de la raíz, que es por donde se coló ocho veces. En un docstring sí puede aparecer: ahí
    es historia, y la historia del primer canal es lo que explica la mitad de los umbrales del proyecto.
    """
    arbol = ast.parse(modulo.read_text(encoding="utf-8"))
    docs = _docstrings(arbol)
    culpables = [
        f"línea {nodo.lineno}: {nodo.value[:90]}"
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Constant)
        and isinstance(nodo.value, str)
        and id(nodo) not in docs
        and ID_DE_CANAL.search(nodo.value)
    ]
    assert not culpables, (
        f"{modulo.relative_to(RAIZ)} nombra un canal en código (no en un docstring), así que el "
        f"estudio está decidiendo por un canal concreto: {culpables}. Si es una ruta, derívala de "
        "`lib.config`; si es un valor, léelo del perfil; si es historia, muévela a un docstring."
    )


# --- Las skills, que es prosa pero manda igual ---------------------------------------------
#
# Un brief de skill es la entrada de un agente: lo que diga, se hace. Dos de los ocho defectos
# venían de ahí —la banda del segundo canal desfasada y «no lleva capítulos» cuando sí— y en los dos
# casos el brief afirmaba **como vigente** un dato que vive en el perfil del canal.
SKILLS = sorted((RAIZ / ".claude" / "skills").rglob("*.md"))

# Una cifra de verdad: decimales, bandas y porcentajes. Se excluyen a propósito los números que
# forman parte de un nombre (`C101`, `W38`, `gate1`, `F4.9`), que no son datos.
CIFRA = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?\s*(?:-\s*\d+(?:[.,]\d+)?)?(?![\w-])")
# Lo que convierte una cifra en legítima: una fecha (es historia, no un dato vigente) o la clave
# del perfil de la que sale (entonces el lector sabe dónde mirar la de verdad).
_POSIBLE_FECHA = re.compile(r"\b(\d{1,2})-(\d{1,2})(?:-(\d{4}))?\b")


def _tiene_fecha(linea: str) -> bool:
    """¿Hay una fecha de verdad en la línea, o solo algo con forma de fecha?

    **Esto lo destapó un control negativo, y es el motivo de que exista la función.** La primera
    versión era un `re.compile(r"\\d{1,2}-\\d{2}(-\\d{4})?")` a secas, y con eso **una banda de
    palabras se cuela por fecha**: en «el canal a 1,80 en láminas de 93 s (143-195)» el trozo `43-19`
    encaja, así que el guardia perdonaba justo la clase de línea que existe para cazar. Reintroducir
    el defecto a propósito fue lo único que lo enseñó — la suite daba verde con él puesto.

    Así que no basta con la forma: el día tiene que caber en un mes y el mes en un año.
    """
    for dia, mes, anio in _POSIBLE_FECHA.findall(linea):
        if 1 <= int(dia) <= 31 and 1 <= int(mes) <= 12 and (not anio or 2020 <= int(anio) <= 2100):
            # Una banda como «14-17 min» seguiría pasando por fecha, así que se exige el año
            # cuando no hay nada más que lo desambigüe. Es la forma que usa el proyecto entero.
            if anio:
                return True
    return False


# Una dirección es cualquier sitio comprobable: una clave del perfil o un fichero del repo.
# «El del primer canal está en `progress/gate0.md` §6» es correcto — dice dónde mirar el dato de verdad.
DIRECCION = re.compile(
    r"perfil\.json|`?nicho\.|`?formato\.|`?voz\.|`?imagen\.|`?publicacion\.|del perfil"
    r"|progress/|doc/|canales/|\.json`|\.md`"
)


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.relative_to(RAIZ / ".claude" / "skills").as_posix())
def test_las_skills_no_dan_por_vigente_un_dato_de_un_canal(skill: Path):
    """En una skill, un canal con una cifra necesita FECHA (es historia) o la clave del perfil.

    **La regla, en una frase**: la skill describe el mecanismo, el perfil guarda los valores. Cuando
    hace falta citar un valor concreto para que se entienda, se dice de dónde sale —y entonces quien
    lo lea puede comprobarlo— o se fecha —y entonces se lee como lo que es, algo que pasó—.

    Lo que esto habría cazado el 14-09: «el canal a 1,80 en láminas de ~93 s (143-195)», una cifra
    copiada del perfil que ya decía 1,885 y que llevaba dos días desfasada en la entrada de los
    guionistas.
    """
    # Se juzga la FRASE, no la línea suelta: estos ficheros van partidos a ~100 columnas, así que
    # «…la cifra sale de» y «`perfil.json → voz.palabras_por_segundo`» caen en renglones distintos
    # muy a menudo. Mirando línea a línea, el guardia acusaba a una frase que sí daba su dirección.
    lineas = skill.read_text(encoding="utf-8").splitlines()
    malas = []
    for numero, linea in enumerate(lineas, 1):
        if not ID_DE_CANAL.search(linea) and not re.search(r"\bC00\d\b", linea):
            continue
        if not CIFRA.search(linea):
            continue
        # El renglón anterior y el siguiente, que es hasta dónde llega una frase partida.
        frase = " ".join(lineas[max(0, numero - 2) : numero + 1])
        if _tiene_fecha(frase) or DIRECCION.search(frase):
            continue
        malas.append(f"línea {numero}: {linea.strip()[:110]}")
    assert not malas, (
        f"{skill.relative_to(RAIZ)} afirma cifras de un canal concreto sin decir de dónde salen ni "
        f"fechar el dato: {malas}. Escribe la clave del perfil que lo guarda (`perfil.json → "
        "voz.palabras_por_segundo`) o fecha la frase si es historia."
    )


# --- Los perfiles, donde el comentario puede contradecir al valor ---------------------------
PERFILES = sorted((RAIZ / "canales").glob("*/perfil.json"))


@pytest.mark.parametrize("perfil", PERFILES, ids=lambda p: p.parent.name)
def test_ningun_comentario_del_perfil_contradice_a_su_valor(perfil: Path):
    """Un `_por_que_sin_X` al lado de un `X: true` es una trampa para el siguiente que lo lea.

    Pasó con los capítulos del segundo canal: se pidieron el 15-09, el valor se puso a `true` y el
    comentario `_por_que_sin_capitulos` se quedó al lado argumentando que «sigue siendo false». El
    guionista lee el perfil antes de escribir, así que un comentario caducado ahí **se aplica**.

    Solo se comprueba la forma más tonta y más real: una clave `_por_que_sin_<algo>` cuando
    `<algo>` es verdadero, y `_por_que_con_<algo>` cuando es falso.
    """
    datos = json.loads(perfil.read_text(encoding="utf-8"))
    choques = []
    for bloque in datos.values():
        if not isinstance(bloque, dict):
            continue
        for clave in bloque:
            for prefijo, esperado in (("_por_que_sin_", True), ("_por_que_con_", False)):
                if clave.startswith(prefijo):
                    nombre = clave[len(prefijo) :]
                    if bloque.get(nombre) is esperado:
                        choques.append(f"`{clave}` al lado de `{nombre}: {esperado}`")
    assert not choques, (
        f"{perfil.relative_to(RAIZ)} tiene comentarios que contradicen a su propio valor: {choques}. "
        "Reescribe el comentario para que explique el valor que hay, no el que hubo."
    )
