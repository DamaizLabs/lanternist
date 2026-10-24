"""La frontera entre el ESTUDIO y el CANAL, vigilada por el arnés (F4.9).

Correr: .venv\\Scripts\\python -m pytest -q tests

**Por qué estas pruebas existen y no basta la regla escrita.** La separación de capas está en
`doc/06-arquitectura-estudio-canales.md` desde F2.11, y aun así se violó CUATRO veces: el idioma
incrustado en la skill (F3.4), las cláusulas de miniatura en `lib/miniatura.py` (F3.6),
`selfDeclaredMadeForKids` en `lib/youtube_client.py`, y el guardián de líneas rojas entero, que
llevaba la premisa del primer canal dentro del estudio (F4.8). Las cuatro se encontraron **a posteriori**,
tres de ellas por auditoría y la última porque un canal nuevo no pudo generar su marca.

Regla del 03-09: «las decisiones tomadas para cada canal no pueden estar dentro de lib/
sino cada canal tiene que tener su propio setup». Escribirla por quinta vez no la haría más
fuerte; esto sí, porque falla en rojo antes del commit.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
from canales_de_prueba import patron_de_id_de_canal
from PIL import ImageColor

from lib import onda

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "lib" / "config.py"

# Lo que un canal declara en su perfil y el estudio NO puede decidir por él. La lista es
# explícita a propósito: si alguien añade un valor de canal nuevo, esta prueba no lo detecta
# sola —lo detecta la de abajo, que mira los defectos— y así queda claro qué se está protegiendo.
DECISIONES_DE_CANAL = {
    "imagen.modelo",
    "imagen.seed",
    "voz.receta",
    "idioma.narracion",
    "idioma.subtitulos",
    "publicacion.hecho_para_ninos",
    "publicacion.categoria_youtube",
}

# Lo que SÍ es del estudio aunque se lea con el mismo mecanismo: vale igual para cualquier canal
# y por eso puede llevar defecto. Cada entrada necesita su motivo escrito aquí.
DEL_ESTUDIO_CON_DEFECTO: dict[str, str] = {}


def _llamadas_del_canal() -> list[tuple[str, bool, int]]:
    """(ruta, tiene_defecto, línea) de cada `_del_canal(...)` de config.py, leído del AST.

    Se analiza el árbol y no con una expresión regular: un `grep` no distingue un defecto
    posicional de una palabra clave, y es justo la diferencia que esta prueba vigila.
    """
    arbol = ast.parse(CONFIG.read_text(encoding="utf-8"))
    salida = []
    for nodo in ast.walk(arbol):
        if not (isinstance(nodo, ast.Call) and getattr(nodo.func, "id", "") == "_del_canal"):
            continue
        ruta = nodo.args[0].value if nodo.args and isinstance(nodo.args[0], ast.Constant) else "?"
        # El tercer posicional es `defecto`; por clave, `defecto=`.
        # `k.arg is None` es un `**{...}`: no se puede saber qué lleva dentro, así que cuenta como
        # defecto. Mutante E de la revisión de F4.9.
        tiene = len(nodo.args) >= 3 or any(k.arg in (None, "defecto") for k in nodo.keywords)
        salida.append((ruta, tiene, nodo.lineno))
    return salida


def test_ninguna_decision_de_canal_tiene_defecto_en_lib():
    """El corazón de F4.9: un defecto en `lib/` es la decisión de otro canal, heredada en silencio.

    Lo que esto habría cazado el día que se escribió: `idioma.narracion` con defecto "es",
    `voz.receta` apuntando al fichero del primer canal, su semilla 1234 y su región ES — los cuatro con un
    comentario encima que decía «es del canal».
    """
    con_defecto = [(r, ln) for r, tiene, ln in _llamadas_del_canal() if tiene and r in DECISIONES_DE_CANAL]
    assert not con_defecto, (
        "estas decisiones de canal tienen un defecto en lib/config.py, así que un canal que no las "
        f"declare hereda la de otro: {con_defecto}. Quita el defecto y pon `ejemplo=` para que el "
        "mensaje diga qué escribir."
    )


def test_todo_defecto_que_quede_esta_justificado_como_del_estudio():
    """Un defecto nuevo no entra sin decir por qué vale para CUALQUIER canal."""
    sin_justificar = [
        (r, ln)
        for r, tiene, ln in _llamadas_del_canal()
        if tiene and r not in DECISIONES_DE_CANAL and r not in DEL_ESTUDIO_CON_DEFECTO
    ]
    assert not sin_justificar, (
        f"defectos sin justificar en config.py: {sin_justificar}. Si el valor es del ESTUDIO, "
        "añádelo a DEL_ESTUDIO_CON_DEFECTO con su motivo; si es del canal, quítale el defecto."
    )


def test_las_siete_decisiones_de_canal_se_siguen_leyendo_del_perfil():
    """Contrapeso de la prueba de arriba: que no se 'arregle' borrando la lectura del perfil."""
    leidas = {r for r, _, _ in _llamadas_del_canal()}
    faltan = DECISIONES_DE_CANAL - leidas
    assert not faltan, f"config.py ya no lee del perfil: {faltan}"


def test_el_esquema_del_perfil_describe_las_mismas_siete():
    """OC1.4: el esquema (`config.DECISIONES_OBLIGATORIAS`) es el sitio único del que leen el validador y la orden que
    crea un canal. Si gana o pierde una decisión, esta lista explícita se entera."""
    from lib import config

    assert set(config.DECISIONES_OBLIGATORIAS) == DECISIONES_DE_CANAL


@pytest.mark.parametrize("perfil", sorted((RAIZ / "canales").glob("*/perfil.json")))
def test_cada_canal_declara_sus_propias_decisiones(perfil: Path):
    """Todo canal del repo declara sus siete decisiones. Sin esto, F4.9 lo pararía en seco."""
    d = json.loads(perfil.read_text(encoding="utf-8"))
    faltan = []
    for ruta in sorted(DECISIONES_DE_CANAL):
        nodo = d
        for parte in ruta.split("."):
            if not isinstance(nodo, dict) or parte not in nodo:
                faltan.append(ruta)
                break
            nodo = nodo[parte]
    assert not faltan, f"{perfil.parent.name} no declara: {faltan}"


@pytest.mark.parametrize("perfil", sorted((RAIZ / "canales").glob("*/perfil.json")))
def test_cada_canal_declara_sus_guardianes_de_color(perfil: Path):
    """F4.8: la lista puede estar VACÍA —es una decisión válida— pero tiene que existir."""
    d = json.loads(perfil.read_text(encoding="utf-8"))
    assert "guardianes_de_color" in (d.get("lineas_rojas") or {}), (
        f"{perfil.parent.name} no declara lineas_rojas.guardianes_de_color. Una lista vacía es "
        "válida y significa «este canal no tiene línea roja de color»; lo que no vale es omitirla, "
        "porque entonces no se distingue de un olvido."
    )


@pytest.mark.parametrize("perfil", sorted((RAIZ / "canales").glob("*/perfil.json")))
def test_el_aspecto_de_la_onda_lo_declara_el_canal_o_no_hay_onda(perfil: Path):
    """F4.11: los nueve valores del aspecto son del CANAL, y aquí se vigilan como los demás.

    **Por qué esta prueba está en este fichero y no solo en `tests/test_onda.py`.** Los nueve
    campos no pasan por `config._del_canal`, así que el vigilante que lee el AST de `config.py`
    no los ve; y `guardianes_de_color` (F4.8), que está en el mismo caso, sí tiene su
    comprobación por perfil aquí. La asimetría la señaló la 3.ª revisión de F4.11: el fichero
    que lleva la regla del 03-09 —«ninguna decisión de canal vive en `lib/`»— tiene que llevarla
    entera, y no repartida entre el suyo y el de cada capa.

    **No declarar la onda es una decisión válida** y significa «este canal no lleva onda»: su
    vídeo se monta sin ella. Lo que no vale es declararla a medias, porque entonces `lib/onda.py`
    tendría que rellenar el hueco con el gusto de otro canal.
    """
    nodo = ((json.loads(perfil.read_text(encoding="utf-8")).get("formato") or {}).get("composicion") or {}).get(
        "onda_de_ecualizador"
    )
    if nodo is None:
        return  # este canal no lleva onda, que es una decisión y no un olvido

    assert isinstance(nodo, dict), (
        f"{perfil.parent.name} declara `onda_de_ecualizador` como {type(nodo).__name__} y tiene "
        "que ser un objeto con los nueve valores del aspecto. Un `true` pelado dice que sí sin "
        "decir cómo, y entonces el aspecto lo elegiría el estudio."
    )
    faltan = sorted(set(onda.OBLIGATORIOS) - set(nodo))
    assert not faltan, (
        f"{perfil.parent.name} declara la onda a medias: faltan {faltan}. Cada uno de esos valores "
        "es una decisión de este canal —el color, la caja, el grosor de la cápsula— y `lib/onda.py` "
        "no puede tener un defecto para ellos sin heredarle a un canal el gusto de otro (F4.9)."
    )
    # El nombre viejo del eje no puede quedar dormido en el perfil: la guarda de migración de
    # `lib/onda.py` lo rechaza, y aquí se vigila antes de llegar a un run.
    assert onda.CAMPO_RENOMBRADO[0] not in nodo, (
        f"{perfil.parent.name} conserva `{onda.CAMPO_RENOMBRADO[0]}`, que es como se llamaba el eje "
        f"cuando la onda tenía base fija. Hoy se llama `{onda.CAMPO_RENOMBRADO[1]}` y el valor NO se "
        "copia tal cual."
    )


def test_ningun_modulo_del_estudio_nombra_a_un_canal_para_decidir():
    """Un id de canal dentro de `lib/` solo puede estar en un comentario, nunca en código.

    El primer canal se cita mucho en la documentación de `lib/` —es el ejemplo calibrado y su historia
    es lo que explica los umbrales— y eso está bien. Lo que no puede es aparecer en una línea de código,
    porque ahí ya no es un ejemplo: es el estudio decidiendo por un canal concreto.
    """
    patron = patron_de_id_de_canal()
    culpables = []
    for py in sorted((RAIZ / "lib").rglob("*.py")):
        arbol = ast.parse(py.read_text(encoding="utf-8"))
        docstrings = {
            id(n.body[0].value)
            for n in ast.walk(arbol)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)
        }
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str) and id(nodo) not in docstrings:
                if patron.search(nodo.value):
                    culpables.append(f"{py.relative_to(RAIZ)}:{nodo.lineno}: {nodo.value[:70]}")
    assert not culpables, (
        "un id de canal aparece en código de lib/ (no en un docstring), así que el estudio está "
        f"decidiendo por un canal concreto: {culpables}"
    )


# Los siete nombres que `config.py` expone como decisión del canal. Se listan aquí para poder exigir
# lo que las pruebas de arriba no ven: que cada uno se asigne UNA vez y SIN adornos.
NOMBRES_DE_CANAL = {
    "MODELO_IMAGEN",
    "IMAGE_SEED",
    "_RECETA_NOMBRE",
    "HECHO_PARA_NINOS",
    "CATEGORIA_YOUTUBE",
    "SUBTITLE_LANG",
    "NARRATION_LANG",
}


def _asignaciones_de_config() -> dict[str, list[ast.AST]]:
    """nombre -> lista de valores que se le asignan en `config.py` (a nivel de módulo)."""
    arbol = ast.parse(CONFIG.read_text(encoding="utf-8"))
    salida: dict[str, list[ast.AST]] = {}
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign):
            for destino in nodo.targets:
                if isinstance(destino, ast.Name) and destino.id in NOMBRES_DE_CANAL:
                    salida.setdefault(destino.id, []).append(nodo.value)
    return salida


def test_cada_valor_de_canal_sale_de_del_canal_y_de_nada_mas():
    """Cierra el mutante J: la fuga 3 (`HECHO_PARA_NINOS = False`) volviendo por donde vino.

    Las pruebas de arriba comprueban «ningún defecto **en `_del_canal`**», que no es lo mismo que
    «ninguna decisión de canal en `lib/`»: un valor cableado directamente no pasa por ese mecanismo
    y se les escapa. Esta lo mira por el otro lado — el nombre asignado.
    """
    asignaciones = _asignaciones_de_config()
    faltan = NOMBRES_DE_CANAL - set(asignaciones)
    assert not faltan, f"config.py ya no asigna estos valores de canal: {sorted(faltan)}"

    cableados = [
        n
        for n, valores in asignaciones.items()
        if not (
            len(valores) == 1
            and isinstance(valores[0], ast.Call)
            and getattr(valores[0].func, "id", "") == "_del_canal"
        )
    ]
    assert not cableados, (
        f"estos valores de canal no salen de una llamada pelada a `_del_canal`: {sorted(cableados)}. "
        "Un valor cableado, un `or` de respaldo o una segunda asignación son la decisión de un canal "
        "escrita en el estudio, que es justo lo que F4.9 prohíbe."
    )


def test_ninguna_lectura_de_texto_se_fia_de_la_codificacion_del_sistema():
    """`read_text()` sin `encoding` usa la del sistema, y en Windows es cp1252.

    **Esto llegó al vídeo** (05-09): `pipeline.py` leía el `slides.json` sin declarar codificación,
    así que el guion entraba a memoria ya roto —la raya larga como `â€"` y los puntos suspensivos
    como `â€¦`— y de ahí pasaba al karaoke quemado, al `.srt` y al audio, porque las tres etapas leen
    el mismo fichero. Se vio en el vídeo. Poner el BOM en el `.ass` arreglaba otro síntoma
    distinto; la causa era esta línea.

    Se comprueba con el AST y no con un `grep` porque las llamadas de varias líneas —que las hay—
    engañan a cualquier expresión regular.
    """
    import ast

    raiz = Path(__file__).resolve().parent.parent
    ficheros = [raiz / "pipeline.py", *sorted((raiz / "lib").rglob("*.py")), *sorted((raiz / "scripts").glob("*.py"))]
    culpables = []
    for fichero in ficheros:
        arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call) or not isinstance(nodo.func, ast.Attribute):
                continue
            if nodo.func.attr not in ("read_text", "write_text"):
                continue
            # La codificación vale por palabra clave o como PRIMER POSICIONAL, que es lo que
            # `Path.read_text(encoding, errors, newline)` acepta: `read_text("utf8")` es correcto y
            # la primera versión de esta prueba lo marcaba como culpable. Una prueba que señala
            # código bueno se desactiva sola, porque enseña a ignorarla.
            tiene_encoding = any(k.arg == "encoding" for k in nodo.keywords) or bool(nodo.args)
            if not tiene_encoding:
                culpables.append(f"{fichero.relative_to(raiz)}:{nodo.lineno} · .{nodo.func.attr}()")
    assert not culpables, "lecturas o escrituras de texto sin codificacion declarada:\n  " + "\n  ".join(culpables)


def test_el_MOTOR_de_voz_NO_lo_declara_ningun_canal():
    """El espejo de F4.9: una decisión de ESTUDIO metida en la capa de canal es igual de mala.

    Hasta el 08-09 el motor era `_del_canal("voz.modelo")`, y el defecto no era teórico: un canal
    clonaba con `kokoro` y otro con `orpheus` — dos canales del mismo estudio con motores distintos,
    y nada lo impedía (addendum fila 119). Esta prueba impide que vuelva, y por eso mira las DOS
    puntas: que `config.py` no lo lea del perfil, y que ningún perfil lo declare.

    **Lo que sigue siendo del canal** y esta prueba no toca: `voz.receta`, que elige QUÉ receta
    —con su voz semilla, su velocidad, su idioma y el texto de su referencia—, no QUIÉN clona.
    """
    rutas = {ruta for ruta, _, _ in _llamadas_del_canal()}
    assert "voz.modelo" not in rutas, (
        "config.py vuelve a leer el motor de voz del perfil del canal: es una decisión de ESTUDIO "
        "(addendum fila 119). El motor está en `MOTOR_DE_VOZ`."
    )
    assert re.search(r"^MOTOR_DE_VOZ\s*=", CONFIG.read_text(encoding="utf-8"), flags=re.M), (
        "falta `MOTOR_DE_VOZ` en config.py: es donde el estudio declara quién clona"
    )
    culpables = []
    for perfil in sorted((RAIZ / "canales").glob("*/perfil.json")):
        voz = json.loads(perfil.read_text(encoding="utf-8")).get("voz") or {}
        if "modelo" in voz:
            culpables.append(f"{perfil.parent.name} declara voz.modelo={voz['modelo']!r}")
    assert not culpables, (
        f"un perfil de canal declara el motor de voz, que es del estudio (addendum fila 119): {culpables}"
    )


# --- F5.6: la MISMA frontera, en `scripts/` ------------------------------------------------------
#
# **La fuga volvió por otra puerta.** Las pruebas de arriba vigilan `lib/config.py`, y
# `scripts/verifica_guion.py` —que es el gate 1 automático— llevaba SIETE decisiones del primer canal escritas
# como constantes del ESTUDIO: el ritmo de su voz, sus dos bandas de palabras por lámina, el
# vocabulario de color de su guardián de líneas rojas, la lista negra de materialidad de su contrato
# de prompt, las fórmulas de respaldo de sus fichas, sus capítulos y sus dos marcadores de
# descripción.
#
# **La consecuencia era medible y se midió** (14-09-2026): el único episodio del segundo canal pasado por ese
# verificador daba **18 fallos y quince eran de capa**, así que ningún guion de ese canal podía dar
# «0 fallos» — y «0 fallos» es la condición de entrega de la skill `produce-semana`.
#
# Por eso estas pruebas están en ESTE fichero y no solo en el del verificador: el que lleva la regla
# del 03-09 —«ninguna decisión de canal vive en el estudio»— tiene que llevarla entera, y no repartida
# entre la capa que ya se vigilaba y la que no.

VERIFICADOR = RAIZ / "scripts" / "verifica_guion.py"

# Los cinco nombres con los que esas decisiones estuvieron cableadas. Se listan por su nombre viejo:
# si alguno vuelve a aparecer como asignación a nivel de módulo, esta prueba falla.
CONSTANTES_DE_CANAL_PROSCRITAS = {
    "PALABRAS_POR_SEGUNDO",
    "BANDA_OBJETIVO",
    "BANDA_DURA",
    "COLORES_PROHIBIDOS",
    "ADJETIVOS_PROHIBIDOS",
}

# Lo que el verificador lee del perfil del canal, con su ruta. Es el contrapeso: sin esto, la prueba
# de arriba se «arregla» borrando la lectura y dejando la regla sin aplicar.
RUTAS_DEL_PERFIL_EN_EL_VERIFICADOR = {
    "formato.duracion_objetivo_min",
    "formato.laminas_por_video_estimadas",
    "formato.capitulos",
    "voz.palabras_por_segundo",
    "imagen.adjetivos_prohibidos",
}

# Las únicas funciones del verificador que tocan el perfil. Que sean pocas y con nombre es lo que
# permite exigirles a ellas —y solo a ellas— que no rellenen ningún hueco.
FUNCIONES_QUE_LEEN_EL_PERFIL = ("_exige", "_palabras_de_los_guardianes", "_lleva_fichas", "contrato_del_canal")


def _arbol_del_verificador() -> ast.Module:
    return ast.parse(VERIFICADOR.read_text(encoding="utf-8"))


def _llamadas_a_exige() -> list[ast.Call]:
    return [
        n
        for n in ast.walk(_arbol_del_verificador())
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_exige"
    ]


def _literal_no_vacio(nodo: ast.AST) -> bool:
    """¿Es un literal con contenido? `""`, `[]`, `{}` y `None` no lo son: rellenan con nada."""
    if isinstance(nodo, ast.Constant):
        return bool(nodo.value)
    if isinstance(nodo, (ast.List, ast.Tuple, ast.Set)):
        return bool(nodo.elts)
    if isinstance(nodo, ast.Dict):
        return bool(nodo.keys)
    return False


def test_el_verificador_no_lleva_ninguna_constante_de_canal():
    """El corazón de F5.6, y lo que habría cazado el día que se escribió.

    `PALABRAS_POR_SEGUNDO = 2.44` era el ritmo del primer canal con SU estilo de guion; el segundo narra a 1,80 con
    la narración A2 del 14-09. `COLORES_PROHIBIDOS` era el vocabulario del guardián de sangre de
    primero, y el perro del segundo lleva collar rojo en el banner de su canal.
    """
    culpables = [
        f"{destino.id} (línea {nodo.lineno})"
        for nodo in _arbol_del_verificador().body
        if isinstance(nodo, ast.Assign)
        for destino in nodo.targets
        if isinstance(destino, ast.Name) and destino.id in CONSTANTES_DE_CANAL_PROSCRITAS
    ]
    assert not culpables, (
        f"scripts/verifica_guion.py vuelve a llevar decisiones de canal como constantes: {culpables}. "
        "Van al perfil de cada canal, y aquí se leen con `_exige` sin defecto."
    )


def test_el_verificador_lee_el_perfil_sin_defecto():
    """`_exige` no admite un valor de respaldo: ni por firma ni por llamada.

    Es la misma propiedad que `_del_canal` de `config.py`, escrita para el otro fichero. Un defecto
    aquí no se ve en el resultado —el guion pasa— y es justo por eso por lo que hace falta la prueba.
    """
    firma = next(n for n in ast.walk(_arbol_del_verificador()) if isinstance(n, ast.FunctionDef) and n.name == "_exige")
    argumentos = {a.arg for a in firma.args.args + firma.args.kwonlyargs + firma.args.posonlyargs}
    assert "defecto" not in argumentos, (
        "`_exige` ha ganado un parámetro `defecto`: eso es la decisión de un canal escrita en el "
        "estudio, con otro nombre (F4.9)"
    )
    # **Los tres permitidos DESCRIBEN lo que se acepta; ninguno aporta un VALOR.** Es la frontera
    # que importa: `tipo=`, `positivo=` y `largo=` solo pueden hacer que el verificador rechace más
    # cosas, nunca que rellene una que falta. `positivo` y `largo` entraron el 14-09 para cerrar el
    # hueco del valor degenerado (auditoría de F5.6, §6.2), que es endurecer, no ablandar.
    # Un nombre nuevo aquí se añade a conciencia: si algún día uno de ellos pudiera SUSTITUIR el
    # valor leído, esta lista deja de proteger nada.
    DESCRIBEN_SIN_APORTAR_VALOR = {"tipo", "positivo", "largo"}
    con_adornos = [
        f"línea {llamada.lineno}: {sorted(k.arg or '**kwargs' for k in llamada.keywords)}"
        for llamada in _llamadas_a_exige()
        if any(k.arg not in DESCRIBEN_SIN_APORTAR_VALOR for k in llamada.keywords)
    ]
    assert not con_adornos, f"llamadas a `_exige` con algo más que {sorted(DESCRIBEN_SIN_APORTAR_VALOR)}: {con_adornos}"

    # **El contrapeso de la lista blanca**, porque una lista de nombres se puede ampliar sin pensar:
    # lo que de verdad hay que impedir es que `_exige` DEVUELVA algo que no haya leído del perfil.
    # Sus únicos `return` legítimos son `None` (carencia) y el nodo leído; un `return 40` o un
    # `return valor_o_defecto` es la decisión de un canal escrita en el estudio, se llame como se
    # llame el parámetro.
    devueltos = [
        n.value
        for n in ast.walk(firma)
        if isinstance(n, ast.Return) and n.value is not None and not isinstance(n.value, ast.Name)
    ]
    constantes = [d for d in devueltos if not (isinstance(d, ast.Constant) and d.value is None)]
    assert not constantes, (
        "`_exige` devuelve algo que no ha leído del perfil: eso es un defecto, con o sin parámetro "
        "que se llame `defecto` (F4.9)"
    )


def test_el_verificador_sigue_leyendo_del_perfil_lo_que_le_toca():
    """Contrapeso: que la prueba de arriba no se cumpla dejando de mirar el perfil."""
    leidas = {
        llamada.args[1].value
        for llamada in _llamadas_a_exige()
        if len(llamada.args) > 1 and isinstance(llamada.args[1], ast.Constant)
    }
    assert leidas == RUTAS_DEL_PERFIL_EN_EL_VERIFICADOR, (
        f"el verificador lee {sorted(leidas)} y debería leer {sorted(RUTAS_DEL_PERFIL_EN_EL_VERIFICADOR)}"
    )


def test_ninguna_lectura_del_verificador_se_rellena_con_un_literal():
    """Un `or 40` detrás de una lectura del perfil es un defecto con otro disfraz.

    Es exactamente lo que había: `laminas_por_video_estimadas` se leía con `or 40`, así que un canal
    que no lo declarase heredaba las 40 láminas del primer canal **y la banda de palabras por lámina que se
    deriva de ellas**. Un `or []` o un `or ""` sí valen: rellenan con nada.
    """
    culpables = [
        f"línea {nodo.lineno}: or {ast.unparse(valor)}"
        for nodo in ast.walk(_arbol_del_verificador())
        if isinstance(nodo, ast.BoolOp) and isinstance(nodo.op, ast.Or)
        for valor in nodo.values[1:]
        if _literal_no_vacio(valor)
    ]
    assert not culpables, f"respaldos con literal en scripts/verifica_guion.py: {culpables}"


def test_ninguna_lectura_del_perfil_lleva_un_get_con_defecto():
    """La otra forma de colar un respaldo: `perfil.get("x", lo_del_primer_canal)`."""
    arbol = _arbol_del_verificador()
    funciones = {
        n.name: n for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef) and n.name in FUNCIONES_QUE_LEEN_EL_PERFIL
    }
    faltan = set(FUNCIONES_QUE_LEEN_EL_PERFIL) - set(funciones)
    assert not faltan, f"el verificador ya no tiene estas funciones, así que esta prueba no vigila nada: {faltan}"
    culpables = [
        f"{nombre}, línea {hijo.lineno}: .get(..., {ast.unparse(hijo.args[1])}) de respaldo"
        for nombre, funcion in funciones.items()
        for hijo in ast.walk(funcion)
        if isinstance(hijo, ast.Call)
        and isinstance(hijo.func, ast.Attribute)
        and hijo.func.attr == "get"
        and len(hijo.args) > 1
    ]
    assert not culpables, f"lecturas del perfil con defecto: {culpables}"


def test_el_verificador_no_nombra_a_un_canal_para_decidir():
    """Lo mismo que se le exige a `lib/`: un id de canal solo puede estar en un docstring."""
    patron = patron_de_id_de_canal()
    arbol = _arbol_del_verificador()
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(arbol)
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
        and isinstance(n.body[0].value.value, str)
    }
    culpables = [
        f"línea {n.lineno}: {n.value[:70]}"
        for n in ast.walk(arbol)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in docstrings
        and patron.search(n.value)
    ]
    assert not culpables, f"el verificador nombra un canal en código: {culpables}"


def lo_que_le_falta_al_verificador(perfil: Path) -> list[str]:
    """Las rutas que el verificador lee y el perfil no declara.

    **Salvo el ritmo en un canal sin voz montada** (addendum filas 197 y 258): `crea-canal` nombra la
    receta en su paso 2b y la escribe en su paso 4, y `voz.palabras_por_segundo` sale de la cata de ese
    mismo paso 4. Es el mismo criterio que `scripts/comprueba_canal.py`: en
    cuanto la receta existe, el ritmo se exige como siempre.
    """
    d = json.loads(perfil.read_text(encoding="utf-8"))
    receta = (d.get("voz") or {}).get("receta") or ""
    sin_voz_montada = not (receta and (perfil.parent / "datos" / receta).is_file())
    faltan = []
    for ruta in sorted(RUTAS_DEL_PERFIL_EN_EL_VERIFICADOR):
        if ruta == "voz.palabras_por_segundo" and sin_voz_montada:
            continue
        nodo = d
        for parte in ruta.split("."):
            if not isinstance(nodo, dict) or parte not in nodo:
                faltan.append(ruta)
                break
            nodo = nodo[parte]
    return faltan


@pytest.mark.parametrize("perfil", sorted((RAIZ / "canales").glob("*/perfil.json")))
def test_cada_canal_declara_lo_que_el_verificador_le_pide(perfil: Path):
    """Sin esto, F5.6 pararía el gate 1 del canal en vez de dejarlo pasar con la regla de otro."""
    faltan = lo_que_le_falta_al_verificador(perfil)
    assert not faltan, f"{perfil.parent.name} no declara: {faltan}"


@pytest.mark.parametrize("con_receta", [False, True])
def test_el_ritmo_se_perdona_solo_mientras_la_receta_no_existe(tmp_path, con_receta):
    # Control: un canal recién creado (receta nombrada sin fichero) pasa sin ritmo; con la receta
    # escrita, el mismo perfil sin ritmo falla. La guarda no se afloja para los canales que ya producen.
    origen = sorted((RAIZ / "canales").glob("*/perfil.json"))[0]
    d = json.loads(origen.read_text(encoding="utf-8"))
    d["voz"].pop("palabras_por_segundo", None)
    carpeta = tmp_path / "canales" / "C999-prueba"
    (carpeta / "datos").mkdir(parents=True)
    (carpeta / "perfil.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    if con_receta:
        (carpeta / "datos" / d["voz"]["receta"]).write_text("{}", encoding="utf-8")
    faltan = lo_que_le_falta_al_verificador(carpeta / "perfil.json")
    assert ("voz.palabras_por_segundo" in faltan) is con_receta


@pytest.mark.parametrize("perfil", sorted((RAIZ / "canales").glob("*/perfil.json")))
def test_cada_guardian_de_color_dice_que_palabras_lo_disparan(perfil: Path):
    """El guardián mide PÍXELES; el verificador caza la palabra que los produce, 60 s de GPU antes.

    Un canal sin guardianes no tiene nada que declarar aquí, y eso ya es una decisión escrita
    en su `_por_que_ningun_guardian_de_color`.
    """
    d = json.loads(perfil.read_text(encoding="utf-8"))
    sin_palabras = [
        g.get("nombre", "(sin nombre)")
        for g in (d.get("lineas_rojas") or {}).get("guardianes_de_color") or []
        if not isinstance(g.get("palabras_del_prompt"), list)
    ]
    assert not sin_palabras, (
        f"{perfil.parent.name}: estos guardianes no declaran `palabras_del_prompt`: {sin_palabras}. "
        "Son las palabras que un prompt no puede usar porque producen el color que ese guardián "
        "detiene; sin ellas el estudio tendría que adivinar la paleta de este canal."
    )


@pytest.mark.parametrize("perfil", sorted((RAIZ / "canales").glob("*/perfil.json")))
def test_cada_canal_dice_si_tiene_aparato_de_fuentes(perfil: Path):
    """Se DERIVA de lo que el perfil ya declara, y por eso no vale el silencio ni las dos a la vez.

    De aquí salen dos reglas: si la descripción lleva `<<BIBLIOGRAFIA>>` y si un guion puede decir
    «it is documented». Un canal de ficción didáctica no tiene ninguna de las dos cosas.
    """
    nicho = json.loads(perfil.read_text(encoding="utf-8")).get("nicho") or {}
    con, sin = bool(nicho.get("fichas_verificadas")), bool(nicho.get("sin_fuentes_verificadas"))
    assert con != sin, (
        f"{perfil.parent.name} tiene que declarar UNA de las dos: `nicho.fichas_verificadas` con la "
        "ruta de su catálogo, o `nicho.sin_fuentes_verificadas` con el motivo de no tenerlo"
    )


# --- El motor de escena (Loop 6, F6.2a) -----------------------------------------------------------------
# El motor sale de video_1, un experimento de UN canal: su `compone.py` llevaba dentro los colores
# de cada hablante, el rótulo del canal y los nombres de los personajes. Al pasar al estudio no puede
# quedar nada de eso en `motor/` ni en `lib/escena/` (plan de F6.2, regla 1): lo del canal llega como
# parámetro (su CSS) o en el GUION. Aquí se mira el fichero ENTERO, comentarios incluidos, porque en JS no
# hay docstrings que separar y porque un nombre de personaje en un comentario del motor ya es una pista
# de que el código se escribió pensando en ese canal.
MOTOR_DE_ESCENA = sorted([*(RAIZ / "motor").glob("*.js"), *(RAIZ / "motor").glob("*.cjs")]) + sorted(
    (RAIZ / "lib" / "escena").glob("*.py")
)


def _lo_que_nombra_a_un_canal(raiz: Path = RAIZ) -> set[str]:
    """Ids, nombres y personajes de todos los canales, leídos de sus perfiles (no de una lista a mano)."""
    nombres: set[str] = set()
    for perfil in sorted((raiz / "canales").glob("*/perfil.json")):
        d = json.loads(perfil.read_text(encoding="utf-8"))
        nombres |= {perfil.parent.name, d.get("id") or "", d.get("nombre") or ""}
        for bloque in ((d.get("nicho") or {}).get("personajes"), (d.get("subtitulos") or {}).get("personajes")):
            nombres |= {k for k in (bloque or {}) if not k.startswith("_")}
    return {n for n in nombres if n}


def _colores_de_los_canales(raiz: Path = RAIZ) -> set[str]:
    colores: set[str] = set()
    for perfil in sorted((raiz / "canales").glob("*/perfil.json")):
        colores |= {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}\b", perfil.read_text(encoding="utf-8"))}
    return colores


# Los 148 colores con nombre de CSS («gold», «white»…), de la tabla de Pillow. Se buscan solo como VALOR de una
# propiedad de color: como palabra suelta darían falsos positivos («red» es la red en castellano).
_COLORES_CON_NOMBRE = "|".join(sorted(ImageColor.colormap, key=len, reverse=True))
_PROPIEDAD_DE_COLOR = (
    r"(?:(?:background|border|outline|text-decoration|column-rule|caret)(?:-[a-z]+)?-?color|color|background"
    r"|border(?:-[a-z]+)?|outline|fill|stroke|box-shadow|text-shadow|fillStyle|strokeStyle|--[\w-]+)"
)
_COLOR_CON_NOMBRE = re.compile(
    rf"(?<![\w-]){_PROPIEDAD_DE_COLOR}\s*[:=]\s*[\"'`]?[^;\"'`}}\n]*?\b({_COLORES_CON_NOMBRE})\b", re.IGNORECASE
)


def _decisiones_de_canal_en(texto: str, nombres: set[str], colores: set[str]) -> list[str]:
    halladas = [m.group(0) for m in re.finditer(r"\bC0\d\d\b", texto)]
    for n in nombres:
        halladas += [m.group(0) for m in re.finditer(rf"\b{re.escape(n)}\b", texto, re.IGNORECASE)]
    # El estilo es del canal: el estudio no escribe ni un color ni una tipografía.
    halladas += [c for c in re.findall(r"#[0-9a-fA-F]{3,8}\b", texto) if c.lower() in colores or len(c) in (4, 7, 9)]
    halladas += re.findall(r"rgba?\([^)]*\)|hsla?\([^)]*\)|font-family\s*:|\bfont\s*:", texto)
    halladas += [m.group(0) for m in _COLOR_CON_NOMBRE.finditer(texto)]
    return halladas


def test_los_ficheros_del_motor_de_escena_existen():
    """Que la prueba de abajo no pase por no encontrar nada que mirar."""
    nombres = {p.name for p in MOTOR_DE_ESCENA}
    assert {"motor.js", "director.js", "malla-webgpu.js", "sonda.cjs", "compone.py", "render.py"} <= nombres
    # F6.2b: el lenguaje de escena, la línea de tiempo, el encuadre y las comprobaciones.
    assert {"ajustes.py", "escena.py", "anclas.py", "ayudas.py", "linea_tiempo.py", "encuadre.py"} <= nombres
    assert "comprobaciones.py" in nombres
    # F6.2c: los activos, el obrero y su núcleo.
    assert {"activos.py", "obrero.py", "obrero_worker.py", "recorte.py"} <= nombres
    # F6.2d: el sonido, el episodio, las etapas del pipeline y las páginas de las paradas.
    assert {"audio.py", "episodio.py", "etapas.py", "revision.py"} <= nombres


@pytest.mark.parametrize("fichero", MOTOR_DE_ESCENA, ids=lambda p: p.name)
def test_ninguna_decision_de_canal_en_el_motor_de_escena(fichero: Path):
    halladas = _decisiones_de_canal_en(
        fichero.read_text(encoding="utf-8"), _lo_que_nombra_a_un_canal(), _colores_de_los_canales()
    )
    assert not halladas, (
        f"{fichero.relative_to(RAIZ)} lleva decisiones de canal: {sorted(set(halladas))}. El motor de escena es "
        "del estudio: los personajes, los colores y los textos de un canal viven en canales/<id>/ y llegan "
        "como parámetro (el CSS del canal) o en el GUION (F4.9, plan de F6.2 regla 1)."
    )


def test_control_la_comprobacion_del_motor_caza_lo_que_traia_video_1(tmp_path):
    """Líneas reales del `compone.py` de video_1: la comprobación tiene que verlas todas.

    Los nombres y colores salen de un canal con personajes escrito en `tmp_path` —con la forma del canal del
    que salió video_1—, y no de `canales/`: el canal de ejemplo no tiene personajes, y sin ellos el control no
    sabría si la comprobación los caza.
    """
    perfil = {
        "id": "C004-otro-canal",
        "nombre": "Otro Canal",
        "subtitulos": {"personajes": {"Nora": {"color": "#7BE495"}, "Papa": {"color": "#86CBFF"}}},
    }
    (tmp_path / "canales" / "C004-otro-canal").mkdir(parents=True)
    (tmp_path / "canales" / "C004-otro-canal" / "perfil.json").write_text(json.dumps(perfil), encoding="utf-8")
    nombres, colores = _lo_que_nombra_a_un_canal(tmp_path), _colores_de_los_canales(tmp_path)
    video_1 = [
        'COLORES_HABLANTE = {"narrador": "#FFE45C", "nora": "#7BE495", "papa": "#86CBFF"}',
        '.tit-marca { font: 700 36px/1 "Baloo 2"; }  /* OTRO CANAL */',
        "// la falda de Nora sobre su muslo",
        '#root { font-family: "Fredoka", sans-serif; }',
        "canales/C004-otro-canal/escena/",
    ]
    for linea in video_1:
        assert _decisiones_de_canal_en(linea, nombres, colores), f"no caza: {linea}"


def test_control_el_id_del_canal_de_ejemplo_tambien_se_caza():
    """El canal que hay hoy en `canales/` es el de ejemplo, y su id no tiene la forma `C00N-…`."""
    assert _decisiones_de_canal_en("canales/example/escena/", _lo_que_nombra_a_un_canal(), set())


@pytest.mark.parametrize(
    "linea",
    [
        '.tit-marca { font: 700 36px/1 "Baloo 2"; }',
        ".chip { color: gold; }",
        ".caja { background: white; }",
        ".tr.puntos circle { fill: Tomato; }",
        ".w.h-uno { --c: rebeccapurple; }",
        'ctx.fillStyle = "white";',
        "nodo.style.color = 'navy';",
        ".x { border: 5px solid darkslategray; }",
    ],
)
def test_control_la_comprobacion_caza_el_estilo_sin_nombre_de_canal(linea):
    """Auditoría de F6.2a, recomendación 7: el control de arriba pasaba porque sus líneas traen además el nombre
    del canal. Estas no traen ninguno: solo estilo, que en el estudio tampoco puede ir."""
    assert _decisiones_de_canal_en(linea, set(), set()), f"no caza: {linea}"


@pytest.mark.parametrize(
    "linea",
    [
        "// la guarda de red corta la conexión",
        'n.style.maskImage = "radial-gradient(circle at 50% 50%, transparent 10%, black 11%)";',
        ".w .f { position: absolute; color: var(--c); opacity: var(--a); }",
        "# el tipo de letra lo pone el canal",
    ],
)
def test_control_y_no_ve_estilo_donde_no_lo_hay(linea):
    """La otra cara: la palabra suelta, una máscara de alfa o el color que llega por variable no son estilo."""
    assert _decisiones_de_canal_en(linea, set(), set()) == []


# --- F6.2b: el lenguaje de escena no trae la disposición de ningún canal -------------------------------------------
# Los ayudantes de video_1 llevaban dentro dónde va una tarjeta (x = 250), cuánto dura (3,6 s), qué dice («NEW WORD»),
# cuánto tarda la cámara en moverse (1,2 s) o a qué volumen suena un efecto (0,3). Son decisiones del canal que, como
# valor por omisión de una función del estudio, cualquier otro canal heredaría sin saberlo (F4.9). Aquí solo pueden
# quedar los valores NEUTROS: los que dejan las cosas como están (nada, cero, uno, sin clase) y tres nombres que son
# la estructura del motor, no un gusto («inout» es su curva por omisión, «corte» es no hacer transición, y «chip» y
# «grito» son las clases de sus ayudantes).
LENGUAJE_DE_ESCENA = [
    RAIZ / "lib" / "escena" / f
    for f in (
        "escena.py",
        "ayudas.py",
        "anclas.py",
        "linea_tiempo.py",
        "encuadre.py",
        "comprobaciones.py",
        "ajustes.py",
        # F6.2c: las fábricas de activos y el obrero tampoco traen lo de ningún canal como valor por omisión (el
        # estilo, los personajes, sus alturas, las semillas o los sitios de los objetos llegan como parámetro).
        "activos.py",
        "obrero.py",
        # F6.2d: el sonido, el episodio y las etapas tampoco traen lo de un canal (sus pausas, su volumen, su CSS, su
        # franja del karaoke, qué efecto suena y cuándo): todo llega del perfil o del guion de escena del episodio.
        "audio.py",
        "episodio.py",
        "etapas.py",
        "revision.py",
        # F6.3: la biblioteca de un canal llega como carpeta; qué imágenes trae un episodio lo dice su guion.
        "biblia.py",
        # F7.10: el formato «pizarra» toma del perfil la separación, los tiempos, la fuente y los tamaños, y del guion
        # dónde va cada cosa.
        "pizarra.py",
    )
]
VALORES_NEUTROS = (None, False, 0, 1, "", "inout", "corte", "chip", "grito")


def _defectos_de_estilo(fuente: str) -> list[str]:
    """`funcion(parametro=valor)` de cada parámetro con un valor por omisión que no es neutro."""
    salida = []
    for nodo in ast.walk(ast.parse(fuente)):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        a = nodo.args
        posicionales = a.posonlyargs + a.args
        pares = list(zip(posicionales[len(posicionales) - len(a.defaults) :], a.defaults))
        pares += [(arg, d) for arg, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
        for arg, defecto in pares:
            try:
                valor = ast.literal_eval(defecto)
            except ValueError:
                salida.append(f"{nodo.name}({arg.arg}={ast.unparse(defecto)})")
                continue
            if not any(valor is v or (type(valor) is type(v) and valor == v) for v in VALORES_NEUTROS) and not (
                isinstance(valor, float) and valor in (0.0, 1.0)
            ):
                salida.append(f"{nodo.name}({arg.arg}={valor!r})")
    return salida


@pytest.mark.parametrize("fichero", LENGUAJE_DE_ESCENA, ids=lambda p: p.name)
def test_el_lenguaje_de_escena_no_trae_disposicion_por_omision(fichero: Path):
    halladas = _defectos_de_estilo(fichero.read_text(encoding="utf-8"))
    assert not halladas, (
        f"{fichero.relative_to(RAIZ)} trae valores por omisión que no son neutros: {halladas}. Dónde va, cuánto dura, "
        "qué dice y cómo suena un elemento es del canal: que lo pase quien llama (sus envoltorios), sin defecto."
    )


def test_control_la_comprobacion_de_disposicion_caza_las_firmas_de_video_1():
    """Firmas reales de `canal/scripts/ayudas.py` y `escena.py` de video_1: cada una tiene que saltar."""
    video_1 = [
        'def tarjeta(g, palabra, dibujo, t0, dur=3.6, lado="izq", articulo="", etiqueta="NEW WORD"): pass',
        "def cam(self, t, cx, cy, z, tr=1.2, e='inout', sigue=None, libre=False): pass",
        "def sfx(self, nombre, t, vol=0.3, dur=None): pass",
        "def transicion(self, tipo, t, d=1.1, sonido=True): pass",
        "def contador(g, de, a, t0, dur, unidad='', x=1920 - 220, y=250, tam=250, sonido=True): pass",
    ]
    for firma in video_1:
        assert _defectos_de_estilo(firma), f"no caza: {firma}"
    # Y los neutros no saltan: una prueba que marca código bueno se desactiva sola.
    assert _defectos_de_estilo("def f(a, tr=0.0, e='inout', op=1.0, clase='', z=None, *, grande=False): pass") == []


# --- F6.2d: el núcleo del obrero tampoco trae valores de un canal (auditoría de F6.2c, recomendación 6) ---------------
# `recorte.py` y `obrero_worker.py` quedaban fuera de la lista de arriba a propósito: sus valores por omisión son
# umbrales de la técnica de croma (la franja del borde, el área mínima de una figura, la junta), declarados como
# constantes del ESTUDIO con su porqué al principio de `recorte.py`. Aquí se les pide lo mismo que a los demás, con esa
# única excepción escrita: un valor por omisión es neutro o es el NOMBRE de una constante de su propio módulo. Un
# número suelto (`umbral=0.35`) o un nombre que no está en el módulo (`alto=ALTO_DE_UN_PERSONAJE`) salta.
NUCLEO_DEL_OBRERO = [RAIZ / "lib" / "escena" / f for f in ("recorte.py", "obrero_worker.py")]


def _defectos_del_nucleo(fuente: str) -> list[str]:
    arbol = ast.parse(fuente)
    constantes = {
        nodo.targets[0].id
        for nodo in arbol.body
        if isinstance(nodo, ast.Assign) and isinstance(nodo.targets[0], ast.Name) and nodo.targets[0].id.isupper()
    }
    salida = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        a = nodo.args
        posicionales = a.posonlyargs + a.args
        pares = list(zip(posicionales[len(posicionales) - len(a.defaults) :], a.defaults))
        pares += [(arg, d) for arg, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
        for arg, defecto in pares:
            if isinstance(defecto, ast.Name) and defecto.id in constantes:
                continue
            restante = _defectos_de_estilo(f"def {nodo.name}({arg.arg}={ast.unparse(defecto)}): pass")
            salida += restante
    return salida


@pytest.mark.parametrize("fichero", NUCLEO_DEL_OBRERO, ids=lambda p: p.name)
def test_el_nucleo_del_obrero_no_trae_valores_de_un_canal(fichero: Path):
    halladas = _defectos_del_nucleo(fichero.read_text(encoding="utf-8"))
    assert not halladas, (
        f"{fichero.relative_to(RAIZ)} trae valores por omisión que no son neutros ni constantes del estudio de su "
        f"módulo: {halladas}. Un umbral de la técnica va como constante con su porqué; lo de un canal, como parámetro."
    )


def test_control_la_comprobacion_del_nucleo_caza_un_numero_suelto_y_un_nombre_de_fuera():
    fuente = "\n".join(
        [
            "FRANJA = 5",
            "def quita(rgb, franja=FRANJA): pass",
            "def junta(rgba, junta=12): pass",
            "def figura(rgba, alto=ALTO_DE_UN_PERSONAJE): pass",
        ]
    )
    assert _defectos_del_nucleo(fuente) == ["junta(junta=12)", "figura(alto=ALTO_DE_UN_PERSONAJE)"]


# ------------------------------------------------------------------ F6.3: la capa de escena de un canal
# La capa de canal del motor de escena (`canales/<id>/escena/`: personajes, sets, apertura, cierre, didáctica, CSS) la
# importa el guion de un episodio como `escena_del_canal`; el estudio la CARGA (`lib/escena/episodio.carga_canal`) pero
# nunca la importa por su nombre: si lo hiciera, `lib/` dependería de lo que decide un canal.
_IMPORTA_LA_CAPA_DEL_CANAL = re.compile(r"^\s*(from|import)\s+escena_del_canal\b", re.MULTILINE)


def _importan_la_capa_del_canal(ficheros) -> list[str]:
    return [
        str(f.relative_to(RAIZ)) for f in ficheros if _IMPORTA_LA_CAPA_DEL_CANAL.search(f.read_text(encoding="utf-8"))
    ]


def test_el_estudio_no_importa_la_capa_de_escena_de_ningun_canal():
    ficheros = [RAIZ / "pipeline.py", *sorted((RAIZ / "lib").rglob("*.py")), *sorted((RAIZ / "scripts").glob("*.py"))]
    assert _importan_la_capa_del_canal(ficheros) == [], (
        "un módulo del estudio importa la capa de escena de un canal: lo del canal llega como parámetro o lo carga "
        "lib/escena/episodio.carga_canal para el guion del episodio (F4.9)"
    )


def test_control_el_guion_de_un_episodio_si_la_importa():
    """El guion de un episodio la importa así, y la comprobación lo ve; un comentario que la nombra, no.

    Así no es una comprobación que no sepa fallar. Las dos líneas son las de la cabecera del guion de un episodio
    del formato «personajes» (el canal de ejemplo aún no tiene episodios con guion: llegan con OC1.4).
    """
    importa = "from lib.escena.ayudas import Tarjeta\nfrom escena_del_canal import estilo\n"
    assert _IMPORTA_LA_CAPA_DEL_CANAL.search(importa)
    assert not _IMPORTA_LA_CAPA_DEL_CANAL.search("# la capa del canal se carga como escena_del_canal\n")
