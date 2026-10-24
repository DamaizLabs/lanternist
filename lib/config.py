import json
import os
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

RUTA_ENV = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(RUTA_ENV)

if sys.platform != "win32":
    _EXTRA_PATHS = ["/opt/homebrew/bin", "/usr/local/bin"]
    for _p in _EXTRA_PATHS:
        if _p not in os.environ.get("PATH", ""):
            os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")
else:
    # La consola cp1252 de Windows no soporta los símbolos ✓/✗/⚠ que imprime el pipeline
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Qué entorno reciben los procesos de TERCEROS (auditoría del 08 y 10-09) -------------------
# `load_dotenv` mete las seis credenciales del proyecto en `os.environ`, y un `Popen` que hereda el
# entorno completo se las entrega enteras al hijo. Dos hijos no son código nuestro: **ComfyUI**, que
# carga nodos de terceros, y **llama-server**, un binario de llama.cpp. Ninguno de los dos necesita
# ni una clave del `.env` para funcionar, así que no las ven.
#
# **Por qué se filtra por las claves del `.env` y no con una lista blanca cerrada.** Una lista blanca
# pura («solo PATH y SystemRoot») es más estricta sobre el papel, pero en Windows el arranque de esos
# dos procesos depende de una docena de variables del sistema —APPDATA, LOCALAPPDATA, TEMP, COMSPEC,
# PATHEXT, las de CUDA— que no se pueden enumerar sin que un día falle el arranque por una que
# faltaba. La propiedad que de verdad hay que garantizar es más estrecha y se comprueba entera: **de
# lo que declara el `.env`, nada llega al hijo**. Y se comprueba, en
# `tests/test_entorno_de_terceros.py`, con un control negativo que falla si una clave se cuela.
_PATRONES_DE_SECRETO = ("TOKEN", "SECRET", "KEY", "PASSWORD", "REFRESH")


def claves_del_env() -> set[str]:
    """Los NOMBRES que declara el `.env` (nunca los valores). Vacío si no hay fichero."""
    if not RUTA_ENV.exists():
        return set()
    return {k for k in dotenv_values(RUTA_ENV) if k}


def entorno_para_terceros(extra: dict[str, str] | None = None) -> dict[str, str]:
    """El entorno del proceso actual sin nada del `.env` ni nada que huela a credencial.

    Se le pasa a `subprocess.Popen(env=...)` de ComfyUI y de llama-server. `extra` es lo que el hijo
    sí necesita (p. ej. `PYTHONUNBUFFERED`), y se aplica DESPUÉS del filtro a propósito: lo que se
    repone es explícito y se lee en la llamada.
    """
    fuera = claves_del_env() | {clave for clave in os.environ if any(p in clave.upper() for p in _PATRONES_DE_SECRETO)}
    limpio = {k: v for k, v in os.environ.items() if k not in fuera}
    limpio.update(extra or {})
    return limpio


# Material de las pruebas y los spikes: pesa, no se publica y no es de ningún canal.
EXPERIMENTOS_DIR = BASE_DIR / "experimentos"
# Bitácora de los adaptadores (ComfyUI). Fuera de git y fuera del canal: es del proceso.
LOGS_DIR = BASE_DIR / "logs"

# --- Las dos capas del estudio (F2.11, doc/06-arquitectura-estudio-canales.md) ------------
# Es de la CAPA DE ESTUDIO lo que no cambia al cambiar de nicho (pipeline, adaptadores,
# motor de escena, cuota de la API de lectura); es de la CAPA DE CANAL lo que define
# una identidad (nicho, estilo visual, voz, idioma y formato).
DATOS_ESTUDIO_DIR = BASE_DIR / "datos"
# Lo que comparten TODOS los canales, y solo eso (regla del 16-09-2026). Se lee aquí y en
# ningún otro sitio: un módulo que lo abriera por su cuenta sería otra copia de la frontera.
BASE_DEL_ESTUDIO_PATH = DATOS_ESTUDIO_DIR / "base-del-estudio.json"
_BASE_DEL_ESTUDIO: dict | None = None


def base_del_estudio() -> dict:
    """`datos/base-del-estudio.json`, leído una vez. Sin él el estudio no sabe qué es común: se para."""
    global _BASE_DEL_ESTUDIO
    if _BASE_DEL_ESTUDIO is None:
        try:
            _BASE_DEL_ESTUDIO = json.loads(BASE_DEL_ESTUDIO_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"No se puede leer {BASE_DEL_ESTUDIO_PATH}: {exc}. Es la base que comparten todos los "
                "canales (karaoke, lecho musical, publicación) y no tiene sustituto."
            ) from exc
    return _BASE_DEL_ESTUDIO


def bloque_del_canal(
    perfil_bloque,
    *,
    bloque: str,
    interruptor: str,
    base: dict,
    donde_en_la_base: str,
    del_estudio: tuple[str, ...],
    del_canal: tuple[str, ...],
    que_es: str,
    error: type[Exception],
    aviso: str,
    pueden_ser_null: tuple[str, ...] = (),
    leidas_aparte: frozenset[str] = frozenset(),
    forzado: bool = False,
) -> dict:
    """Un bloque del perfil con dos dueños: lo del estudio sale de la base; lo del canal, sin defecto.

    Lo usan `lib/subtitulos.py` y `lib/musica.py` desde F5.14 (fila 196). Eran dos funciones casi
    iguales, y la auditoría midió que ya se habían separado en lo que importa: música dejaba pasar un
    `null`, que llegaba a ffmpeg como `volume=NonedB` después de gastar la GPU en el lecho. Para con
    un mensaje que dice qué escribir en cuatro casos: el perfil no dice si el canal lleva el bloque;
    lo lleva (o se fuerza por entorno) y le falta un valor, o lo tiene a `null` sin poder serlo; o
    declara un valor del estudio, que sería una segunda copia capaz de divergir. Una clave desconocida
    se avisa en vez de ignorarse en silencio.
    """
    if not isinstance(perfil_bloque, dict) or not isinstance(perfil_bloque.get(interruptor), bool):
        raise error(
            f"El perfil del canal no declara `{bloque}.{interruptor}` (true o false). Si lo lleva, declara "
            f"además {', '.join(del_canal)}. No hay valor por defecto: {que_es}."
        )
    declarados_del_estudio = sorted(k for k in del_estudio if k in perfil_bloque)
    if declarados_del_estudio:
        raise error(
            f"El perfil del canal declara {declarados_del_estudio} en `{bloque}`, y es del estudio: vive en "
            f"`datos/base-del-estudio.json → {donde_en_la_base}`. Quítalo del perfil."
        )
    valores = {clave: base[clave] for clave in del_estudio}
    valores[interruptor] = perfil_bloque[interruptor]
    if perfil_bloque[interruptor] or forzado:
        faltan = [
            k for k in del_canal if k not in perfil_bloque or (perfil_bloque[k] is None and k not in pueden_ser_null)
        ]
        if faltan:
            por_que = (
                f"Este canal declara `{bloque}.{interruptor}: false` y se está forzando por entorno: para "
                f"forzarlo hace falta declarar igualmente {faltan}"
                if not perfil_bloque[interruptor]
                else f"El canal lleva {bloque} (`{bloque}.{interruptor}: true`) y su perfil no declara {faltan}"
            )
            nulos = f"; solo {', '.join(pueden_ser_null)} puede valer null" if pueden_ser_null else ""
            raise error(f"{por_que}. No tienen valor por defecto: {que_es}{nulos}.")
    valores.update({clave: perfil_bloque[clave] for clave in del_canal if clave in perfil_bloque})
    conocidas = {interruptor, *del_canal, *leidas_aparte}
    desconocidas = sorted(k for k in perfil_bloque if k not in conocidas and not k.startswith("_"))
    if desconocidas:
        print(
            f"  [{aviso}] AVISO: el perfil del canal declara claves que este módulo no conoce y que NO se "
            f"están aplicando: {desconocidas}. Las válidas son {sorted(conocidas)}.",
            flush=True,
        )
    return valores


CANALES_DIR = BASE_DIR / "canales"

CANAL_ACTIVO = os.getenv("CANAL_ACTIVO", "").strip()
CANAL_DIR = CANALES_DIR / CANAL_ACTIVO if CANAL_ACTIVO else None
CANAL_PERFIL_PATH = CANAL_DIR / "perfil.json" if CANAL_DIR else None
CANAL_DATOS_DIR = CANAL_DIR / "datos" if CANAL_DIR else None

# Motivo de que el canal no esté usable, o None. No se lanza excepción al importar: este
# módulo lo importa todo el proyecto, incluido el propio `--check` que debe informar del
# problema en vez de morir con un rastro de pila.
CANAL_ERROR: str | None = None
CANAL_PERFIL: dict = {}
if not CANAL_ACTIVO:
    CANAL_ERROR = (
        "CANAL_ACTIVO está vacío en el .env. Cada canal del estudio vive en canales/<id>/ con su "
        "perfil.json: mira qué ids hay en ese directorio y pon uno, o crea el tuyo con `canal.py --nuevo <id>`."
    )
elif not CANAL_PERFIL_PATH.exists():
    CANAL_ERROR = f"CANAL_ACTIVO={CANAL_ACTIVO!r} pero no existe {CANAL_PERFIL_PATH}"
else:
    try:
        CANAL_PERFIL = json.loads(CANAL_PERFIL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as _e:
        CANAL_ERROR = f"{CANAL_PERFIL_PATH} no se puede leer como JSON: {_e}"
    else:
        # Parsear no basta: una lista o un escalar tambien son JSON valido, y quien lea el
        # perfil despues asumiria que es un objeto. El diagnostico se da aqui, no en una
        # traza tres modulos mas adelante.
        if not isinstance(CANAL_PERFIL, dict):
            CANAL_ERROR = (
                f"{CANAL_PERFIL_PATH} no es un objeto JSON, es "
                f"{type(CANAL_PERFIL).__name__}: el perfil del canal tiene que ser un objeto"
            )
            CANAL_PERFIL = {}


# Valores del perfil con el tipo equivocado. Se acumulan en vez de lanzar: el perfil se
# edita a mano y un `"seed": "pendiente"` no puede tumbar el import de este módulo, que es
# justo el que alimenta al `--check` encargado de diagnosticarlo.
_CANAL_AVISOS: list[str] = []

# NINGUNA DECISIÓN DE CANAL TIENE DEFECTO EN `lib/` (F4.9, regla del 03-09: «las
# decisiones tomadas para cada canal no pueden estar dentro de lib/ sino cada canal tiene que
# tener su propio setup»). Este centinela marca los valores que son del CANAL: si su perfil no
# los declara, no se rellenan con nada — se anotan aquí y el `--check` los enumera.
#
# Nació de medir cuatro fugas de la misma familia (idioma en F3.4, cláusulas de miniatura en
# F3.6, `selfDeclaredMadeForKids` y el guardián de color en F4.8) y, sobre todo, de que este
# mismo módulo tenía CUATRO defectos que decidían por el canal mientras el comentario de encima
# decía «es del canal»: el idioma en "es", la receta de voz del primer canal, su semilla y su región.
# La regla ya estaba escrita en doc/06 desde F2.11 y se violó igual, así que ahora la vigila
# `tests/test_capas.py` en vez de la buena voluntad.
_SIN_DEFECTO = object()
_CANAL_SIN_DECLARAR: list[str] = []
# Anulaciones por variable de entorno de valores que son del CANAL. Se permiten a propósito —sirven
# para un experimento de un run, como barrer semillas sin editar el perfil— pero NO en silencio: el
# `.env` es uno solo para todo el estudio, así que una línea `IDIOMA_NARRACION=es` decidiría por
# TODOS los canales a la vez, que es la misma fuga que F4.9 saca de `lib/` movida de sitio. Con esto
# el `--check` dice de dónde viene cada valor que no salió del perfil.
_CANAL_DESDE_ENTORNO: list[str] = []

# --- El esquema del perfil: lo que todo canal declara sí o sí (OC1.4) --------------------------------------------------
# **Un solo sitio describe las decisiones obligatorias de un canal.** Lo leen tres: `problemas_del_perfil`, que dice qué
# falta y qué escribir; `canal.py --nuevo`, que crea un canal mínimo con ellas; y `_del_canal`, que pone el ejemplo en su
# mensaje. `tests/test_capas.py` comprueba que su lista de siete es esta.
#
# Cada entrada: ruta en el perfil → (tipo, qué es, un ejemplo de qué escribir). Ninguna tiene defecto (F4.9).
DECISIONES_OBLIGATORIAS: dict[str, tuple[type, str, str]] = {
    "imagen.modelo": (
        str,
        "el workflow del estilo de imagen: un fichero de workflows/, sin el .json",
        "qwen-2512-lightning-tinta",
    ),
    "imagen.seed": (int, "la semilla de imagen del canal, elegida para él y no copiada de otro", "2026"),
    "voz.receta": (
        str,
        "el nombre de la receta de voz del canal, que vive en canales/<id>/datos/",
        "voz-orpheus-<id>.json",
    ),
    "idioma.narracion": (str, "el idioma de la narración, en ISO 639-1", "en"),
    "idioma.subtitulos": (str, "el idioma de los subtítulos, en ISO 639-1", "en"),
    "publicacion.hecho_para_ninos": (bool, "si el canal es PARA niños, como lo clasifica YouTube", "false"),
    "publicacion.categoria_youtube": (str, "la categoría de YouTube de sus vídeos (snippet.categoryId)", "27"),
}
# Los interruptores de los bloques que un canal puede llevar o no. Un `true` obliga después a declarar el resto del
# bloque, y eso lo exigen `lib/musica.py` y `lib/subtitulos.py` cuando se usan.
INTERRUPTORES: dict[str, tuple[type, str, str]] = {
    "musica.activa": (bool, "si el canal lleva lecho musical", "true"),
    "subtitulos.activos": (bool, "si el canal lleva subtítulos", "true"),
}
# El tercer interruptor es el del motor de escena, el único del estudio: no dice si se usa, sino en qué formato del
# catálogo. Lo da el bloque `escena` (`lib/escena/ajustes.py → formato`): `escena.laminas` es «laminas»,
# `escena.pizarra` es «pizarra», y sin ninguno de los dos, «personajes».
FORMATO_DE_ESCENA = "escena (formato)"


def en_el_perfil(perfil, ruta: str):
    """El valor de `ruta` («imagen.seed») en el perfil, o `_SIN_DEFECTO` si falta algún tramo."""
    nodo = perfil
    for parte in ruta.split("."):
        if not isinstance(nodo, dict) or parte not in nodo:
            return _SIN_DEFECTO
        nodo = nodo[parte]
    return nodo


def _es_del_tipo(valor, tipo: type) -> bool:
    """`bool` no cuenta como entero (`True` no es una semilla) y un texto vacío no cuenta como texto."""
    if tipo is bool:
        return isinstance(valor, bool)
    if tipo is int:
        return isinstance(valor, int) and not isinstance(valor, bool)
    return isinstance(valor, str) and bool(valor.strip())


NOMBRE_DEL_TIPO = {bool: "true o false", int: "un número entero", str: "un texto"}


def problemas_del_perfil(perfil) -> list[str]:
    """Lo que le falta a un perfil para cumplir el esquema: las siete decisiones, los interruptores y el formato.

    Devuelve una línea por problema, cada una con la clave, qué es y qué escribir. Una lista vacía es un perfil que
    cumple. No mira el resto de los bloques (la marca, la voz, la escena entera): eso lo exigen sus módulos al usarlos
    y lo junta `scripts/comprueba_canal.py`.
    """
    if not isinstance(perfil, dict):
        return [f"el perfil tiene que ser un objeto JSON, y es {type(perfil).__name__}"]
    problemas = []
    for ruta, (tipo, que, ejemplo) in {**DECISIONES_OBLIGATORIAS, **INTERRUPTORES}.items():
        valor = en_el_perfil(perfil, ruta)
        if valor is _SIN_DEFECTO or valor is None:
            problemas.append(f"falta `{ruta}`: {que}. Escribe {NOMBRE_DEL_TIPO[tipo]}, por ejemplo {ejemplo}")
        elif not _es_del_tipo(valor, tipo):
            problemas.append(f"`{ruta}` vale {valor!r} y tiene que ser {NOMBRE_DEL_TIPO[tipo]}, por ejemplo {ejemplo}")
    # Aquí y no arriba: `lib.escena.ajustes` importa el motor de escena, que importa este módulo.
    from lib.escena import ajustes

    escena = perfil.get("escena")
    formatos = ", ".join(ajustes.FORMATOS)
    if not isinstance(escena, dict):
        problemas.append(
            f"falta el bloque `escena`: el motor de escena es el único del estudio y su bloque dice en qué formato "
            f"produce el canal ({formatos}). Escribe `escena` con un bloque `laminas` o `pizarra`, o sin ninguno "
            "para «personajes»"
        )
    else:
        try:
            ajustes.formato(perfil)
        except ajustes.ErrorDeAjustes as error:
            problemas.append(str(error))
    return problemas


def _del_canal(ruta: str, variable_entorno: str = "", defecto=_SIN_DEFECTO, tipo=None, ejemplo: str = ""):
    """Valor de configuración del canal activo.

    Precedencia: variable de entorno > perfil del canal > defecto. `ruta` navega el perfil
    con puntos (`"imagen.modelo"`), así que el perfil puede agrupar por área sin que los
    consumidores conozcan su forma.

    **Sin `defecto` explícito, el valor es OBLIGATORIO en el perfil del canal**, que es lo
    normal: casi todo lo que se lee de aquí es una decisión de identidad. Un `defecto=` solo
    se pone cuando el valor es del ESTUDIO y vale igual para cualquier canal.

    `tipo` valida lo que venga del perfil (`int` coacciona, `str` exige cadena). Un valor
    del tipo equivocado **no revienta**: se anota en `_CANAL_AVISOS`, se devuelve el
    defecto, y el `--check` lo reporta. Sin esto, `"seed": "pendiente"` —que el propio
    perfil se plantea, porque la semilla está pendiente de verificar en Qwen— rompía el
    import de `lib/config.py` con un `ValueError` y se llevaba por delante el diagnóstico.
    """
    if variable_entorno:
        crudo = os.getenv(variable_entorno, "").strip()
        if crudo:
            if defecto is _SIN_DEFECTO:
                _CANAL_DESDE_ENTORNO.append(f"`{ruta}` viene de {variable_entorno}, no del perfil del canal")
            return _coacciona(ruta, crudo, defecto, tipo, origen=f"la variable {variable_entorno}", del_entorno=True)
    nodo = CANAL_PERFIL
    for parte in ruta.split("."):
        if not isinstance(nodo, dict) or parte not in nodo:
            return _sin_valor(ruta, defecto, ejemplo)
        nodo = nodo[parte]
    if nodo in (None, ""):
        return _sin_valor(ruta, defecto, ejemplo)
    return _coacciona(ruta, nodo, defecto, tipo, origen="el perfil del canal")


def _sin_valor(ruta: str, defecto, ejemplo: str):
    """El perfil no lo declara: o hay defecto del estudio, o el canal tiene que escribirlo."""
    if defecto is not _SIN_DEFECTO:
        return defecto
    # El ejemplo de una decisión obligatoria sale del esquema, que es donde está escrito una sola vez.
    ejemplo = ejemplo or DECISIONES_OBLIGATORIAS.get(ruta, (None, "", ""))[2]
    # Solo se anota si hay un canal que pueda declararlo: sin canal activo el error ya es otro,
    # y enumerar quince campos que faltan taparía el diagnóstico de verdad.
    if CANAL_ACTIVO and not CANAL_ERROR:
        _CANAL_SIN_DECLARAR.append(f"`{ruta}`" + (f" (por ejemplo: {ejemplo})" if ejemplo else ""))
    return None


def _coacciona(ruta: str, valor, defecto, tipo, origen: str, del_entorno: bool = False):
    """Aplica `tipo` a `valor`; si no encaja, anota el aviso y devuelve el defecto."""
    if tipo is None:
        return valor
    if tipo is str:
        if isinstance(valor, str):
            return valor
    else:
        try:
            return tipo(valor)
        except (TypeError, ValueError):
            pass
    # Un valor del canal con el tipo equivocado es lo mismo que no declararlo: no hay defecto
    # del estudio con el que taparlo, y devolver el centinela se lo colaría al consumidor.
    if defecto is _SIN_DEFECTO:
        _CANAL_AVISOS.append(
            f"'{ruta}' en {origen} vale {valor!r} y se esperaba {tipo.__name__}; el canal tiene que corregirlo"
        )
        # Con el valor malo en el ENTORNO el perfil puede estar impecable: registrarlo como «no
        # declarado» mandaría a corregir un fichero que está bien (medido con la copia del perfil de
        # un canal y SEED_IMAGEN=abc). El aviso de tipo ya dice la verdad.
        return None if del_entorno else _sin_valor(ruta, defecto, "")
    _CANAL_AVISOS.append(f"'{ruta}' en {origen} vale {valor!r} y se esperaba {tipo.__name__}; se usa {defecto!r}")
    return defecto


# Base de datos de canal cuando no hay canal activo: nombra el problema en cualquier
# mensaje de error, en vez de apuntar a un `datos/` que ya no contiene esos archivos.
SIN_CANAL_DIR = CANALES_DIR / "(sin-canal-activo)"
SIN_CANAL_DATOS = SIN_CANAL_DIR / "datos"

# --- Lo que un canal genera: pesado, ignorado por git y dentro de su propia carpeta -------
# Reorganización del 30-08: antes esto vivía en `outputs/<run_id>` y
# `canales/<id>/marca` colgando de la raíz. Un run es de UN canal —su estado ya lo dice en
# el campo `canal` y `assets.json` también—, así que vive con él. `.gitignore` ignora
# `canales/*/videos/` y `canales/*/marca/`, no `canales/` entera: el perfil, las fichas de
# fuentes, la procedencia y las fotos de métricas no se pueden regenerar y sí van a git.
# **`RUTA_VIDEOS` mueve lo pesado a otro disco, y nace de una medición (06-09).**
#
# La primera medida fue incompleta: escritura SECUENCIAL —175 MB/s en un disco duro contra 2250 en
# un SSD, 13×— y con eso el disco no parecía el problema. La segunda midió lo que de verdad hace un
# montaje —escrituras pequeñas y salteadas con `fsync`— y ahí la diferencia es **6,4 MB/s contra
# 444,9: setenta veces**. Un plato sufre en el I/O aleatorio, no en el secuencial, y la primera
# prueba no lo tocaba.
#
# El repo puede quedarse en un disco duro: lo que ejecuta modelos vive en el SSD, y aquí los modelos
# son de herramientas que viven fuera del repo. Lo que se mueve es SOLO `videos/`, que ya
# está ignorado por git y es donde caen los intermedios: los planos del montaje, la onda, el vídeo
# sin subtítulos y los wav. Si la variable no está, todo sigue donde estaba.
_VIDEOS_FUERA = os.getenv("RUTA_VIDEOS", "").strip()
CANAL_VIDEOS_DIR = (
    Path(_VIDEOS_FUERA) / (CANAL_ACTIVO or "(sin-canal-activo)")
    if _VIDEOS_FUERA
    else (CANAL_DIR or SIN_CANAL_DIR) / "videos"
)
CANAL_MARCA_DIR = (CANAL_DIR or SIN_CANAL_DIR) / "marca"
# Estado de cada run. Es del canal —lo dice su propio campo `canal`— y **se queda en git**: el
# `video_id` del borrador subido solo existe aquí, y de aquí sale la cohorte que mide
# `metricas.py` (la Analytics API omite los vídeos con 0 vistas). Por eso NO se metió dentro
# de `videos/<run_id>/`, que está ignorado: habría sacado de git el único registro de que la
# cohorte existe. El motivo largo está en `progress/impl_reorganiza-arbol.md`.
STATE_DIR = (CANAL_DATOS_DIR or SIN_CANAL_DATOS) / "estado"

# --- Lo que se sube al canal, junto y en su carpeta (10-09) ---------------------------------
#
# **Es del ESTUDIO y no de un canal**: subir a YouTube un vídeo, su miniatura y su `.srt` es lo
# mismo en cualquier canal, así que aquí no se decide por nadie (F4.9 no aplica).
#
# Nace de una confusión medida: el `.srt` que el usuario tiene que adjuntar a mano vivía en la RAÍZ
# del run y el `.ass` del karaoke —que Studio no acepta— en la carpeta `subtitulos/`, así que lo buscó
# donde decía «subtitulos» y encontró el que no vale. La petición: «tendrías que generar por
# contrato una carpeta que diga "subir al canal", y todos los assets que son para subir a YT
# colocarlos allí… dejarlo todo en la raíz teniendo carpetas no lo veo coherente».
#
# Lo que va aquí son los TRES entregables de la publicación: `final.mp4`, `thumbnail.png` y el
# `.srt`, más un `LEEME.html` con el título y la descripción para copiar. Lo que NO va: los JSON de
# trazabilidad (`assets.json`, `montaje.json`, `slides.json`, `miniatura.json`, los
# `generacion-*.json`), que son el expediente del run y se quedan en su raíz, ni los intermedios de
# `WORK_DIRS` (`montaje/`, `musica/`, `onda/`, `subtitulos/`, `crudo/`, `limpieza/`).
DIR_SUBIR_AL_CANAL = "subir-al-canal"


def dir_subir_al_canal(run_dir: str | Path, crear: bool = False) -> Path:
    """La carpeta de lo publicable de un run. Con `crear`, la deja hecha."""
    destino = Path(run_dir) / DIR_SUBIR_AL_CANAL
    if crear:
        destino.mkdir(parents=True, exist_ok=True)
    return destino


def ruta_publicable(run_dir: str | Path, nombre: str) -> Path:
    """Dónde está (o dónde irá) un entregable del run, tolerando los runs anteriores al 10-09.

    Devuelve la ruta dentro de `subir-al-canal/` si el archivo está ahí; si no está pero SÍ existe
    en la raíz del run, devuelve esa —los runs producidos antes de esta organización siguen siendo
    legibles sin migrarlos, y el `stages.*.output` de su estado apunta a la raíz—; y si no existe en
    ninguna de las dos, devuelve la nueva, que es donde el pipeline lo va a escribir.
    """
    nueva = dir_subir_al_canal(run_dir) / nombre
    if nueva.exists():
        return nueva
    vieja = Path(run_dir) / nombre
    return vieja if vieja.exists() else nueva


def datos_del_canal(nombre: str) -> Path:
    """Ruta de un archivo de datos del canal activo, sin que el consumidor arme rutas.

    Falla con mensaje propio si no hay canal: llegar aquí sin canal es un error de
    configuración, no un caso que el código deba sortear con un valor por defecto.
    """
    if CANAL_DATOS_DIR is None:
        raise RuntimeError(f"No hay canal activo, así que no hay datos de canal ({nombre}). {CANAL_ERROR}")
    # Se crea si falta, en vez de fallar: un canal recién dado de alta no debería obligar a
    # preparar el directorio a mano, y el modo de fallo que esto cierra es caro — nació en
    # `detector.py --descubrir` (retirado el 25-09), que escribía la salida al FINAL, después de los
    # `search.list` a 100 unidades, así que un canal sin `datos/` perdía la cuota del día. El typo en
    # `CANAL_ACTIVO` ya lo caza `CANAL_ERROR` antes de llegar aquí, porque exige el perfil.
    CANAL_DATOS_DIR.mkdir(parents=True, exist_ok=True)
    return CANAL_DATOS_DIR / nombre


VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
ASPECT_RATIO = "16:9"
IMAGE_GEN_WIDTH = 1344
IMAGE_GEN_HEIGHT = 768
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720

WORDS_PER_SECOND = 2.5
DEFAULT_SLIDE_DURATION = 4
MIN_SLIDE_DURATION = 3
# El long-form firmado en el gate 0 vive de láminas largas (20-30 s de narración por
# ilustración): el techo de 10 s del fork era de un formato de <4 min.
MAX_SLIDE_DURATION = 40
FPS = 24

# La capa de movimiento del montaje (F2.6: `MOTION_*`, supermuestreo, zooms, planos y transiciones) salió con el motor de
# láminas en F6.7. El formato «láminas» del motor de escena lleva sus valores en el perfil de cada canal
# (`perfil.json → escena.laminas`), sin defecto.

# --- Las rutas de las herramientas locales: salen del `.env` de quien usa el motor (OC1.3) ---
# ComfyUI, llama.cpp con el peso de Orpheus y el Chrome con WebGPU viven fuera del repositorio, donde
# los instaló el usuario. Por eso no tienen valor por defecto: uno escrito aquí sería la ruta de un PC
# concreto. Si falta una, importar este módulo no rompe —lo importa todo, y la suite corre sin `.env`—:
# la ruta apunta a un nombre que dice qué falta, y `pipeline.py --check` dice qué escribir.
RUTAS_DE_HERRAMIENTAS = {
    "COMFY_ROOT": "la carpeta de tu ComfyUI, la que tiene main.py y models/",
    "LLAMA_SERVER": "el llama-server.exe de tu llama.cpp",
    "LLAMA_MODELO_GGUF": "el GGUF de Orpheus, orpheus-3b-Q8_0.gguf",
    "CHROME_WEBGPU_MANIFIESTO": "el manifiesto.json que escribe scripts/instala_chrome_webgpu.ps1",
}


def _ruta_de_herramienta(variable: str) -> Path:
    """La ruta que declara el `.env`, o un nombre que dice qué falta si no la declara."""
    valor = os.getenv(variable, "").strip()
    return Path(valor) if valor else Path(f"(falta {variable} en el .env)")


# --- Adaptador de imagen local sobre ComfyUI (F2.1, addendum de doc/02 fila 5) ---
# La instalación puede ser compartida con otros proyectos del usuario: el adaptador arranca el
# servidor solo si no hay ninguno vivo y lo apaga solo si fue él quien lo arrancó.
COMFY_HOST = os.getenv("COMFY_HOST", "127.0.0.1")
COMFY_PORT = int(os.getenv("COMFY_PORT", "8188"))
COMFY_BASE_URL = f"http://{COMFY_HOST}:{COMFY_PORT}"
# El adaptador de imagen es la ÚNICA salida de red del pipeline de producción, y tiene que
# seguir siendo local: la decisión cerrada 6 dice que nada sale de este PC salvo la subida a
# YouTube. Hasta ahora eso era un comentario en el .env.example («nunca una URL remota»), o
# sea una convención. Aquí es una aserción: apuntar COMFY_HOST fuera de loopback deja de ser
# un despiste silencioso.
if COMFY_HOST not in ("localhost",):
    import ipaddress as _ip

    try:
        if not _ip.ip_address(COMFY_HOST).is_loopback:
            raise ValueError(
                f"COMFY_HOST={COMFY_HOST!r} no es loopback. El adaptador de imagen solo habla con "
                "un ComfyUI local (nada sale de este PC salvo la subida)."
            )
    except ValueError as _e:
        raise ValueError(str(_e)) from None
COMFY_ROOT = _ruta_de_herramienta("COMFY_ROOT")
COMFY_PYTHON = os.getenv("COMFY_PYTHON", str(COMFY_ROOT / ".venv" / "Scripts" / "python.exe"))
COMFY_STARTUP_TIMEOUT = int(os.getenv("COMFY_STARTUP_TIMEOUT", "300"))
COMFY_IMAGE_TIMEOUT = int(os.getenv("COMFY_IMAGE_TIMEOUT", "1200"))
COMFY_POLL_INTERVAL = 1.0
# VRAM que ComfyUI deja libre al cargar el modelo, en GB (su flag `--reserve-vram`).
#
# **Es un parámetro de MÁQUINA, no de canal**, y por eso vive aquí con defecto: lo fija la tarjeta
# (3060 Ti de 8 GB), no la identidad de ningún canal. Poner 0 quita el flag.
#
# **Por qué existe, medido el 07-09-2026.** Sin reserva, ComfyUI 0.33.0 carga el Qwen GGUF
# parcialmente (5.598 MB dentro, 3.668 MB fuera) y al terminar los 8 pasos necesita sitio para el
# VAE, así que descarga parte del modelo. Esa descarga parcial de un GGUF **mata el proceso** con
# «Windows fatal exception: access violation» en `ComfyUI-GGUF/ops.py:58` vía
# `model_patcher.partially_unload`. El pipeline lo ve como una conexión rechazada tres capas más
# abajo, que no se parece nada a la causa. Con 1,6 GB reservados el VAE ya tiene su hueco desde el
# principio, no hay descarga parcial y no hay crash: 33 láminas seguidas donde antes moría en la 1.
COMFY_RESERVA_VRAM_GB = float(os.getenv("COMFY_RESERVA_VRAM_GB", "1.6"))
# Subcarpeta propia dentro del output de ComfyUI: el adaptador se lleva la imagen y
# borra su copia del servidor compartido, sin tocar nada más de esa instalación.
COMFY_OUTPUT_SUBFOLDER = "lanternist"
WORKFLOWS_DIR = BASE_DIR / "workflows"
# Estilo/workflow del canal: es su identidad visual, así que vive en su perfil
MODELO_IMAGEN = _del_canal("imagen.modelo", "MODELO_IMAGEN", tipo=str)
# Seed fija: la consistencia de estilo entre imágenes depende de ella, y por eso es del CANAL —
# sin defecto desde F4.9. Lo que sigue es la evidencia de por qué el primer canal eligió la suya:
# 1234 es la semilla del acabado aprobado el 24-08 en el contrato de prompt de imagen de ese canal:
# entre las tres láminas de la pasada `estructura` solo cambiaba la semilla, y el control con
# otra escena confirma que esta transporta el trazo fino y el tono claro. El 42 anterior venía
# del zoo-test y no tenía criterio detrás.
IMAGE_SEED = _del_canal("imagen.seed", "SEED_IMAGEN", tipo=int)

# --- Adaptador de voz local (F2.2; motores kokoro + orpheus desde el 07-09) ---
# El stack de voz vive en un venv APARTE porque es incompatible con el del pipeline:
# `.venv-voz` pinea torch 2.6.0+cu126 y el `.venv` del pipeline va con torch 2.13. El
# adaptador lo cruza invocando `lib/voice_worker.py` como subproceso con ese intérprete;
# en el `.venv` del pipeline no se instala nada de voz.
VOICE_PYTHON = os.getenv("PYTHON_VOZ", str(BASE_DIR / ".venv-voz" / "Scripts" / "python.exe"))
VOICE_WORKER = BASE_DIR / "lib" / "voice_worker.py"
# El alineador de subtitulos (F2.13) cruza el mismo limite de venv y por el mismo motivo:
# transformers y torch viven en .venv-voz. Comparte interprete y techo de tiempo con la voz.
ALINEADOR_WORKER = BASE_DIR / "lib" / "alineador_worker.py"
# Receta de voz: declara el MOTOR, sus parámetros, la semilla, la segmentación y los perfiles
# tonales. Es del canal: otro nicho puede querer otra voz, otro idioma u otro registro. En
# el primer canal apuntaba a `voz-kokoro-en.json` desde el 25-08 (la mezcla elegida ese día).
# `voz-chatterbox-en.json` se borró el 07-09 con el motor; su relevo es `voz-orpheus-en.json`,
# que clona ESA misma mezcla en vez de sustituirla.
_RECETA_NOMBRE = _del_canal("voz.receta", tipo=str)
# El nombre puede faltar desde F4.9 (es del canal y ya no tiene defecto), y este módulo NO puede
# lanzar al importarse: se apunta a un nombre que nombra el problema, y `CANAL_ERROR` —que ya lleva
# la lista de lo no declarado— es quien lo cuenta. Un `TypeError` aquí se llevaría por delante el
# `--check`, que es justo el encargado de diagnosticarlo.
VOICE_RECIPE_PATH = Path(
    os.getenv("RECETA_VOZ", "").strip()
    or (CANAL_DATOS_DIR or SIN_CANAL_DATOS) / (_RECETA_NOMBRE or "(voz.receta-sin-declarar).json")
)
# Perfil tonal por defecto; vacío = el `perfil_por_defecto` de la receta (el neutro)
VOICE_PROFILE = os.getenv("PERFIL_VOZ", "")
# Los recortes de cualquier clip de referencia se cachean FUERA del repo y en C:\ (NVMe):
# una grabación de voz y todo lo derivado de ella jamás entran en git (lista negra)
VOICE_CACHE_DIR = Path(os.getenv("RUTA_CACHE_VOZ", str(Path.home() / ".cache" / "lanternist-voz")))
# Techo de tiempo del subproceso de voz. **Subido de 2 h a 12 h el 07-09**, cuando se creía que
# Orpheus iba a 33× tiempo real y un episodio eran ~11 h.
#
# **Esa cifra era FALSA por un factor de 29** y el episodio cuesta **20,6 min** medidos de reloj
# (addendum fila 113; venía de extrapolar dos segmentos no representativos y de medir en bf16, que
# ahoga los 8 GB). La auditoría del 08-09 encontró que la cifra vieja seguía viva aquí cuando ya se
# había corregido en cuatro sitios: es el patrón de «la cifra tecleada a mano en prosa se pudre».
#
# **El techo se queda en 12 h de todas formas, y ahora por otro motivo**: no es un presupuesto, es
# el límite que distingue «este motor es lento» de «algo se ha colgado». Con el episodio en 20 min,
# 12 h son tres órdenes de holgura y eso es exactamente lo que se quiere de un techo: que solo salte
# cuando de verdad no va a acabar nunca.
VOICE_TIMEOUT = int(os.getenv("VOZ_TIMEOUT", "43200"))

# --- Runtime de Orpheus: llama.cpp con el GGUF cuantizado (addendum filas 116 y 119) ---
# **Todo este bloque es del ESTUDIO y NINGUNA de sus claves va en la receta de un canal.** Es la
# precisión del 08-09 (addendum fila 119): «Kokoro será nuestra fábrica de voces y Orpheus será nuestro motor
# de voces para todos los canales, por lo tanto esto está a nivel de estudio y no de canal». Un
# canal declara su voz semilla, su velocidad, su idioma y el texto de su referencia; **no elige
# runtime ni cuantización**, igual que no elige la versión de FFmpeg.
#
# Y por eso va aquí y no en `_del_canal`: metido en la capa de canal, dos canales del mismo estudio
# podrían clonar con motores distintos — que es exactamente lo que pasaba (fila 119).
#
# El binario y los pesos viven fuera del repo, donde los instaló el usuario (`RUTAS_DE_HERRAMIENTAS`),
# igual que ComfyUI: lo que ejecuta modelos no se mete dentro del repo.
LLAMA_HOST = os.getenv("LLAMA_HOST", "127.0.0.1")
LLAMA_PORT = int(os.getenv("LLAMA_PORT", "8199"))
LLAMA_BASE_URL = f"http://{LLAMA_HOST}:{LLAMA_PORT}"
# **Loopback por aserción y no por convención**, copiando lo que ya se hizo con `COMFY_HOST`. La
# auditoría del 08-09 encontró que la fila 116 del addendum afirmaba «el servidor solo escucha en
# 127.0.0.1» y **no había una línea de código que lo atara**: era prosa. Aquí apuntar el motor de
# voz fuera de loopback deja de ser posible (decisión cerrada 6).
if LLAMA_HOST:
    import ipaddress as _ip_llama

    try:
        if not _ip_llama.ip_address(LLAMA_HOST).is_loopback:
            raise ValueError(
                f"LLAMA_HOST={LLAMA_HOST!r} no es loopback. El motor de voz solo habla con un "
                "llama.cpp local (nada sale de este PC salvo la subida)."
            )
    except ValueError as _e_llama:
        raise ValueError(str(_e_llama)) from None
LLAMA_SERVER = _ruta_de_herramienta("LLAMA_SERVER")
# El GGUF **Q8_0 y no Q4_K_M**, por la decisión del 08-09: Q4 va un 50 % más rápido pero Q8 es
# casi sin pérdida, y lo que se pidió fue calidad. A 20,6 min por episodio no hace falta apurar más.
LLAMA_MODELO_GGUF = _ruta_de_herramienta("LLAMA_MODELO_GGUF")
# Contexto por ranura. **Tiene que cubrir el ejemplo de voz MÁS el techo de tokens del segmento**:
# el ejemplo del clonado son 2.704 tokens y el techo del segmento más largo del episodio 1 fue
# 1.146, así que 8.192 deja holgura de sobra. No es una decisión de canal: el canal declara su
# ventana de referencia y su holgura, y el contexto necesario se DERIVA de eso.
LLAMA_CONTEXTO = int(os.getenv("LLAMA_CONTEXTO", "8192"))
LLAMA_STARTUP_TIMEOUT = int(os.getenv("LLAMA_STARTUP_TIMEOUT", "300"))
# --- El MOTOR de voz es del ESTUDIO, y esta es la línea que lo dice (addendum fila 119) ---
#
# **Precisión del 08-09**: «Kokoro será nuestra fábrica de voces y Orpheus será nuestro
# motor de voces para todos los canales, por lo tanto esto está a nivel de estudio y no de canal».
#
# **Hasta ese día esto era `_del_canal("voz.modelo", ...)`, y el defecto no era teórico**: un canal
# clonaba con `kokoro` y otro con `orpheus` — dos canales del mismo estudio con motores distintos, y
# nada lo impedía. Es el **espejo de F4.9**: aquella regla nació de cinco decisiones de CANAL metidas
# en `lib/`, y esto era una de ESTUDIO metida en la capa de canal. Igual de mala, y por el mismo
# motivo: permite que dos canales divergan en silencio y con ello se cae la promesa de que el
# pipeline de voz es del estudio.
#
# **Lo que sigue siendo del canal**: su voz semilla del catálogo de Kokoro, su velocidad, su idioma
# y el texto de su referencia, todo en su receta. Lo que deja de serlo es **quién clona**.
#
# Es una constante y no una variable de entorno a propósito: cambiar el motor del estudio es una
# decisión con fila en el addendum, no un flag del `.env`.
MOTOR_DE_VOZ = "orpheus"

# --- Motor de escena (Loop 6, addendum filas 199-201; F6.2a) ---------------------------------
# Todo este bloque es del ESTUDIO: el motor, su guarda de red, la CLI de HyperFrames y el Chrome con
# WebGPU valen igual para cualquier canal. Lo del canal (su CSS, sus personajes, su estilo) llega a
# `lib/escena/compone.py` como parámetro y nunca vive aquí (F4.9).
MOTOR_ESCENA_DIR = BASE_DIR / "motor"
# Los JS que `compone.py` mete en la página, EN ESTE ORDEN: el motor define `Motor`, las mallas definen
# `Mallas` y el director usa los dos. GSAP va antes, en su propia etiqueta.
MOTOR_ESCENA_JS = tuple(MOTOR_ESCENA_DIR / f for f in ("motor.js", "malla-webgpu.js", "director.js"))
# GSAP 3.14.2, instalado con `cd motor; npm ci` (`motor/package.json`) y no copiado en el repositorio: su licencia,
# la «Standard No Charge» de GreenSock, no da permiso para redistribuirlo (OC1.2, `THIRD_PARTY_NOTICES.md`).
MOTOR_ESCENA_GSAP = MOTOR_ESCENA_DIR / "node_modules" / "gsap" / "dist" / "gsap.min.js"
# La guarda de red (decisión 6): toda orden de Node del motor se lanza con `node --require` de esto.
MOTOR_ESCENA_GUARDA = MOTOR_ESCENA_DIR / "sin-red.cjs"
# La sonda que abre la composición en el Chrome de WebGPU antes de renderizar (F6.2a).
MOTOR_ESCENA_SONDA = MOTOR_ESCENA_DIR / "sonda.cjs"
# La CLI de HyperFrames fijada en `motor/package.json` (se instala con `cd motor; npm ci`).
HYPERFRAMES_CLI = MOTOR_ESCENA_DIR / "node_modules" / "hyperframes" / "dist" / "cli.js"
# El Chrome headless con las librerías DXC que necesita WebGPU (F6.1, fila 201): vive fuera del repo,
# como ComfyUI. Su manifiesto dice qué ejecutable usar y el sha256 de cada fichero.
CHROME_WEBGPU_MANIFIESTO = _ruta_de_herramienta("CHROME_WEBGPU_MANIFIESTO")
# Node: el de `.node-version` (lo instala fnm). Vacío = el primero del PATH o el alias por defecto de fnm.
NODE_EXE = os.getenv("NODE_EXE", "").strip()
# Memoria libre de la GPU que se exige antes de abrir Chrome con la GPU (sonda, snapshot y render).
# **Es un parámetro de MÁQUINA, no de canal**, como `COMFY_RESERVA_VRAM_GB`: lo fija la tarjeta de 8 GB, en
# la que solo cabe un trabajo de GPU a la vez. Si hay menos libre, es que otro trabajo la está usando, y el
# render no arranca encima. **Por qué 4096, medido el 29-09** (`experimentos/motor-escena/f62a-vram/vram.json`):
# en reposo quedan 6.973 MB libres; con Orpheus cargado en llama-server, 2.517 (ocupa 4.456), y con Qwen en
# ComfyUI menos aún (5.598 MB dentro, addendum fila 106). El umbral viejo, 2048, dejaba pasar a Orpheus. Un
# render del GUION de prueba gasta 219 MB. `lib/escena/render.py` mira además el nombre del proceso.
ESCENA_VRAM_LIBRE_MIN_MB = int(os.getenv("ESCENA_VRAM_LIBRE_MIN_MB", "4096"))
# Techo de la sonda para que la composición registre su línea de tiempo, en ms.
ESCENA_SONDA_TIMEOUT_MS = int(os.getenv("ESCENA_SONDA_TIMEOUT_MS", "30000"))
# Lo que el director deja al compositor de Chrome después de cada búsqueda de HyperFrames y antes de la
# captura, en ms. **Parámetro de MÁQUINA, no de canal.** Medido el 29-09 (F6.2a, progress/impl_F6.2a.md,
# cifras en experimentos/motor-escena/f62a-determinismo/resultados.json): con WebGPU en la página,
# HyperFrames en Windows captura por pantallazo y a veces fotografía una capa de texto que se escala (un
# rótulo con «pop») antes de que el compositor la haya vuelto a rasterizar, así que dos renders del mismo
# GUION salían distintos. De 4 renders sin espera salen al menos 3 resultados distintos; con 16 ms y con 50 ms,
# los 4 son iguales. Se deja en 50, el triple del mínimo que funcionó. Cuesta esos 50 ms en cada fotograma de
# cada proceso de Chrome.
ESCENA_ESPERA_COMPOSITOR_MS = int(os.getenv("ESCENA_ESPERA_COMPOSITOR_MS", "50"))
# Techo del render, en s. No es un presupuesto: distingue «tarda» de «se ha colgado». El episodio de 16 min
# de video_1 tardó 20 min 19 s (doc/inventario-herramientas-y-proceso.md), así que 4 h es holgura de sobra.
ESCENA_RENDER_TIMEOUT_S = int(os.getenv("ESCENA_RENDER_TIMEOUT_S", "14400"))
# Dónde escribe HyperFrames el vídeo mientras lo renderiza (F6.3). HyperFrames crea con `mkdtemp` una carpeta de
# trabajo JUNTO al fichero de salida (`.final.hf-transaction-XXXXXX`), y en Windows eso falla con ENOENT si la ruta
# pasa de 260 caracteres (MAX_PATH): la de un run de un canal con el título de un episodio llega a 274 (medido en la
# puerta de reproducción de F6.3: `render` falló así antes de fotografiar un solo fotograma). El render escribe en
# una carpeta de esta ruta corta y el vídeo se mueve después a su sitio del run. Es una ruta local de la máquina.
ESCENA_RENDER_TMP = Path(os.getenv("ESCENA_RENDER_TMP", tempfile.gettempdir()))

# --- Los activos del motor de escena (F6.2c)---------------------------------------------------------------
# También del ESTUDIO: con qué se generan y se recortan las figuras. Lo del canal (su estilo, sus personajes, sus
# alturas) llega a `lib/escena/activos.py` como parámetro.
#
# El obrero (Real-ESRGAN, SAM 2.1) corre en su propio venv, con el Python del sistema, por el mismo cruce de
# entornos que la voz: torch con CUDA, spandrel y transformers no están en el `.venv` del pipeline. Se crea con los
# tres pasos de `spikes/requirements-escena.txt`.
ESCENA_PYTHON = os.getenv("PYTHON_ESCENA", str(BASE_DIR / ".venv-escena" / "Scripts" / "python.exe"))
OBRERO_ESCENA_WORKER = BASE_DIR / "lib" / "escena" / "obrero_worker.py"
# El peso de Real-ESRGAN se LEE de la carpeta de modelos de ComfyUI, que no se modifica: es el mismo `.pth` que usó
# video_1, y copiarlo al repo o a otra carpeta sería tener dos copias de un peso que no cambia.
ESCENA_ESRGAN_PESO = Path(
    os.getenv("ESCENA_ESRGAN_PESO", str(COMFY_ROOT / "models" / "upscale_models" / "RealESRGAN_x4plus_anime_6B.pth"))
)
# SAM 2.1 sale de la caché de Hugging Face (`~/.cache/huggingface`); el obrero no la descarga (decisión 6).
ESCENA_SAM_MODELO = "facebook/sam2.1-hiera-large"
# Las teselas de Real-ESRGAN, en px de la imagen de entrada, y lo que se solapan. **Parámetros de MÁQUINA**: los fija
# la VRAM de la tarjeta de 8 GB (con teselas de 384 cabe aunque ComfyUI tenga algo cargado), no un canal. Son los
# de video_1, que recortó así sus 117 imágenes.
ESCENA_ESRGAN_TESELA = int(os.getenv("ESCENA_ESRGAN_TESELA", "384"))
ESCENA_ESRGAN_SOLAPE = int(os.getenv("ESCENA_ESRGAN_SOLAPE", "24"))
# Techo del obrero, en s. Como el del render: distingue «tarda» de «se ha colgado», no es un presupuesto.
ESCENA_OBRERO_TIMEOUT_S = int(os.getenv("ESCENA_OBRERO_TIMEOUT_S", "7200"))
# El cerrojo que toma el obrero mientras corre (F6.2d, auditoría de F6.2c, recomendación 3): nvidia-smi lo da como el
# Python del sistema, así que `lib/escena/render.trabajos_de_gpu_en_marcha` lo reconoce por aquí. Es del ESTUDIO y uno
# solo para todos los runs: dos obreros de runs distintos también se estorban en la tarjeta.
ESCENA_CERROJO_OBRERO = LOGS_DIR / "obrero-escena.cerrojo"
# El workflow de Qwen-Image-Edit con el que se generan hojas, posturas, variantes y objetos: una referencia y un
# lienzo aparte (`workflows/qwen-edit-lienzo.json`, con su porqué en `workflows/README.md`).
ESCENA_WORKFLOW_EDICION = "qwen-edit-lienzo"

# --- La marca de IA (OC1.5, filas 309, 311 y 312) -------------------------------------------------------------------
# El marcado y el detector corren en `.venv-escena` (`lib/marca_ia_worker.py`), como el obrero. Todo esto es del
# ESTUDIO: la marca es la misma para cualquier canal.
MARCA_IA_WORKER = BASE_DIR / "lib" / "marca_ia_worker.py"
# Dónde guarda cada instalación su certificado C2PA y su clave: fuera del repositorio, en la carpeta del usuario, para
# que nunca viajen con el código (reglas del motor público). Es una constante y no una variable de entorno: cambiarla
# es una decisión, no un ajuste. Las pruebas la redirigen a una carpeta temporal.
MARCA_CLAVES_DIR = Path.home() / ".lanternist" / "c2pa"
# El cerrojo que toma el marcado mientras usa la GPU: como el del obrero, nvidia-smi lo da como un Python cualquiera.
MARCA_CERROJO = LOGS_DIR / "marca-ia.cerrojo"
# Los trabajos, resultados y logs del marcado y del detector, y sus temporales mientras corren.
MARCA_TRABAJO_DIR = LOGS_DIR / "marca-ia"
# Techo del trabajador, en s. Distingue «tarda» de «se ha colgado»: marcar cuesta ~0,45 s por segundo de vídeo en la
# GPU (`progress/spike_OC1.5.md`), así que un episodio de 16 min son unos 7 min.
MARCA_TIMEOUT_S = 7200


# Dentro de un run, dónde van los activos del motor de escena (F6.2c). `activos/` guarda lo que tiene procedencia:
# lo que genera Qwen (`crudo/`), los lienzos de referencia (`ref/`), los recortes (`img/`) y el catálogo.
# `activos-trabajo/` es material de trabajo (lienzos de croma lisos, los trabajos y logs del obrero) y por eso
# está en `provenance.WORK_DIRS`.
def activos_del_run(run_dir: str | Path) -> Path:
    return Path(run_dir) / "activos"


def trabajo_de_activos(run_dir: str | Path) -> Path:
    return Path(run_dir) / "activos-trabajo"


# --- El sonido, la biblioteca y las etapas del motor de escena (F6.2d) ----------------------------------------------
# La biblioteca del ESTUDIO: los efectos de sonido y las fuentes que cualquier canal puede usar, cada fichero con su
# entrada en el `CREDITOS.json` de su carpeta (fuente, licencia, url y sha256). Qué efecto suena y qué fuente se ve lo
# deciden el guion de escena y el CSS del canal; aquí solo están los ficheros (`datos/escena/CREDITOS.md`).
ESCENA_BIBLIOTECA_DIR = DATOS_ESTUDIO_DIR / "escena"
ESCENA_SFX_DIR = ESCENA_BIBLIOTECA_DIR / "sfx"
# De dónde se instalan esos efectos (OC1.2): la copia que trae HyperFrames, que `npm ci` deja en `motor/node_modules`.
# Son de Pixabay y su licencia no deja redistribuirlos sueltos, así que no viajan en el repositorio:
# `scripts/instala_efectos.py` los copia de aquí a `ESCENA_SFX_DIR` si su sha256 es el de `CREDITOS.json`.
HYPERFRAMES_SFX_DIR = (
    MOTOR_ESCENA_DIR / "node_modules" / "hyperframes" / "dist" / "skills" / "media-use" / "audio" / "assets" / "sfx"
)
ESCENA_FUENTES_DIR = ESCENA_BIBLIOTECA_DIR / "fuentes"
ESCENA_CREDITOS = "CREDITOS.json"
# El guion de escena de un episodio: lo escribe Claude y vive en git, junto a los datos del canal, porque es texto y
# no se regenera. Su contrato está en `lib/escena/episodio.py`.
ESCENA_GUION = "escena.py"


def guion_de_escena(canal_dir: str | Path, run_id: str) -> Path:
    """La carpeta del guion de escena de un episodio: `canales/<canal>/datos/escenas/<run_id>/`."""
    return Path(canal_dir) / "datos" / "escenas" / run_id


# La capa de CANAL del motor de escena (F6.3): `canales/<canal>/escena/`. Es un paquete de Python (su estilo, sus
# personajes, sus sets, su apertura y su cierre, su didáctica, su CSS) que el estudio carga con el nombre fijo
# `ESCENA_PAQUETE_DEL_CANAL` para que el guion de un episodio lo importe; y guarda la biblioteca de imágenes del
# canal (`biblioteca/`), que se reutiliza entre episodios y entra en cada run con su procedencia
# (`lib/escena/biblia.py`).
ESCENA_PAQUETE_DEL_CANAL = "escena_del_canal"
ESCENA_BIBLIOTECA_DEL_CANAL = "biblioteca"


def escena_del_canal(canal_dir: str | Path) -> Path:
    """La capa de canal del motor de escena: `canales/<canal>/escena/`."""
    return Path(canal_dir) / "escena"


def biblioteca_del_canal(canal_dir: str | Path) -> Path:
    """Las imágenes ya recortadas del canal, con su catálogo, su índice y su procedencia."""
    return escena_del_canal(canal_dir) / ESCENA_BIBLIOTECA_DEL_CANAL


# Dentro de un run del motor de escena. Las tres primeras son material de trabajo (`provenance.WORK_DIRS`): copias o
# derivados de assets que ya tienen su procedencia. La biblioteca, no: guarda la copia de los efectos y las fuentes
# del estudio que usa el episodio, con su registro.
def composicion_del_run(run_dir: str | Path) -> Path:
    """La composición de HyperFrames: `index.html` y sus `assets/`."""
    return Path(run_dir) / "composicion"


def sonido_del_run(run_dir: str | Path) -> Path:
    """La narración con sus pausas, el lecho ya apartado bajo la voz y el vídeo antes de normalizar su sonoridad."""
    return Path(run_dir) / "sonido"


def revision_del_run(run_dir: str | Path) -> Path:
    """Las páginas de las dos paradas del usuario, los fotogramas de `snapshot` y los logs de HyperFrames."""
    return Path(run_dir) / "revision"


def biblioteca_del_run(run_dir: str | Path) -> Path:
    """La copia de los efectos y las fuentes del estudio que usa el episodio, con su registro de procedencia."""
    return Path(run_dir) / "biblioteca"


# Dentro de un run, lo que lee la línea de tiempo del motor de escena (F6.2b). Son las rutas que escriben las etapas
# de voz (`pipeline.py → stage_tts`) y de alineación (la etapa `alinea`, `lib/escena/etapas.py`, F6.2d; hasta F6.7
# también la escribía el karaoke quemado del motor de láminas). Si cambian, se cambian aquí y en ningún otro sitio.
def audio_de_lamina(run_dir: str | Path, numero: int) -> Path:
    """El wav de la narración de la lámina `numero` (1, 2…) de un run."""
    return Path(run_dir) / "audio" / f"slide-{int(numero):02d}.wav"


def alineacion_del_run(run_dir: str | Path) -> Path:
    """Las marcas por palabra de todas las láminas del run: `items[{id: "slide-NN", marcas[{texto, desde, hasta}]}]`."""
    return Path(run_dir) / "subtitulos" / "alineacion-resultado.json"


# --- Registro de procedencia por run (F2.4, decisión cerrada 5) ---
# `assets.json` vive junto al vídeo, dentro del run, pero `canales/*/videos/` está en .gitignore y
# doc/02 Punto 5 exige que la procedencia llegue a git (es la defensa ante Content ID):
# cada registro se espeja aquí, que sí se versiona. Un JSON por run, ~2 KB por lámina.
ASSETS_MIRROR_DIR = (CANAL_DATOS_DIR or SIN_CANAL_DATOS) / "assets"

# El servicio de imagen/voz de pago que traía el fork (claves y endpoint) se eliminó en
# F2.3: imagen y voz son locales (decisión cerrada 4, coste marginal 0 €). No vuelve.

# Audiencia declarada del canal (`status.selfDeclaredMadeForKids` de videos.insert). Estaba
# CABLEADA a False en lib/youtube_client.py, que es capa de estudio: para un museo de la justicia
# medieval el valor es obvio, pero para un canal con niños protagonistas ya no, y la clasificación
# «hecho para niños» quita comentarios, notificaciones y anuncios personalizados. Es del canal, y
# sin defecto como el resto (F4.9). Se lee sin `tipo` a propósito: `bool("false")` es True, así que
# coaccionar aquí convertiría un perfil mal escrito en un sí silencioso — lo valida el consumidor.
HECHO_PARA_NINOS = _del_canal("publicacion.hecho_para_ninos")

# Categoría del vídeo en YouTube (`snippet.categoryId`). Era «22» (People & Blogs) fijo en
# `lib/youtube_client.py` para todos los canales desde el fork: un canal de negocios y uno de historia
# no se clasifican igual. Es del canal y sin defecto (F4.9; addendum fila 196). Se lee como texto
# porque es lo que manda la API; lo valida `youtube_client` contra las categorías conocidas.
CATEGORIA_YOUTUBE = _del_canal("publicacion.categoria_youtube", tipo=str)

# Clave de lectura de la Data API v3 (foto semanal, canal.py y metricas.py); la subida usa el OAuth de abajo.
# ESTA es del ESTUDIO: una sola clave y 10.000 unidades/día compartidas entre todos los
# canales. Con más de un canal habrá que repartir el ledger; hoy no hace falta.
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")

# **El refresh token es POR CANAL, y el canal dice en qué variable vive — no cuál es.** El OAuth se
# concede canal a canal: el token de un canal devuelve 403 sobre cualquier otro (medido el 28-08). Con dos
# canales produciendo desde el 13-09, un único `YOUTUBE_REFRESH_TOKEN` ya no sirve.
#
# Lo que viaja en git es el NOMBRE de la variable (`YOUTUBE_REFRESH_TOKEN_2`), nunca el token: el
# secreto se queda en el `.env`, que no entra en el repositorio. Y va en el perfil y no aquí porque es
# una decisión de canal (F4.9): sin declararlo, el canal no sube y lo dice.
_REFRESH_ENV = _del_canal(
    "publicacion.refresh_token_env",
    tipo=str,
    ejemplo='"YOUTUBE_REFRESH_TOKEN" o, en un segundo canal, "YOUTUBE_REFRESH_TOKEN_2"',
)
YOUTUBE_REFRESH_TOKEN = os.getenv(_REFRESH_ENV, "") if _REFRESH_ENV else ""

# **La subida por la API está APAGADA por defecto** (OC1.8, fila 315). Vacía, el run deja el vídeo listo para subirlo a
# mano en Studio y no pide ninguna clave de Google. Con `1`, la etapa de subida lo sube por la API con el OAuth de quien
# usa el motor (`docs/youtube-upload.md`). Cualquier otro valor para el run: lo comprueba
# `lib/youtube_client.subida_por_la_api`. Hasta OC1.8 la subida se encendía sola al estar las tres claves de arriba.
YOUTUBE_SUBIDA_API = os.getenv("YOUTUBE_SUBIDA_API", "").strip()

# Idioma de subtítulos/transcripciones; el fork lo traía hardcodeado a "en" y este módulo lo
# traía por defecto en "es", que era la misma fuga con otro valor: SIN DEFECTO desde F4.9, el
# canal lo declara. El inglés fue vinculante para el primer canal (addendum fila 8), no para el estudio.
SUBTITLE_LANG = _del_canal("idioma.subtitulos", "IDIOMA_SUBTITULOS", tipo=str)
# Idioma de la NARRACIÓN, que no es lo mismo que el de los subtítulos: decide qué motor de voz
# corresponde (decisión cerrada 13, 25-08) y lo comprueba el preflight de lib/voice_client.py.
# **Y es la ÚNICA constante que lee esta ruta**: la subida a YouTube (`defaultLanguage` y
# `defaultAudioLanguage`), la declaración de IA y la descripción la leen de aquí, con la misma
# anulación por entorno. El 15-09 hubo una gemela sin esa anulación (`IDIOMA_NARRACION`) durante una
# hora y el manifiesto (A-27) la caza si vuelve.
NARRATION_LANG = _del_canal("idioma.narracion", "IDIOMA_NARRACION", tipo=str)

# Nombres de las voces preset del TTS de pago del fork. Se conservan SOLO para que el
# adaptador local los reconozca y avise al recibirlos (una llamada antigua o un
# `--voice josh` heredado no debe reventar): ya no nombran nada que exista.
PRESET_VOICES = ["josh", "koko", "pixxy", "prof", "rochie", "spraky"]

DEFAULT_STYLE = "documentary"

YT_DLP_MAX_VIDEOS = 20


# --- Cierre de la capa de canal --------------------------------------------------------
# Los avisos de tipo se resuelven al final, cuando ya se han leído todos los valores: así
# el `--check` los enumera juntos en vez de morir en el primero.
_PROBLEMAS: list[str] = []
if _CANAL_SIN_DECLARAR and not CANAL_ERROR:
    _PROBLEMAS.append(
        f"el perfil de '{CANAL_ACTIVO}' no declara "
        f"{len(_CANAL_SIN_DECLARAR)} decisión(es) que son SUYAS: " + " · ".join(_CANAL_SIN_DECLARAR) + ". "
        "El motor no las rellena con un valor por defecto, porque ese valor sería la decisión de "
        "otro canal. Escríbelas en "
        f"canales/{CANAL_ACTIVO}/perfil.json — cualquier otro perfil de canales/ sirve de ejemplo "
        "completo."
    )
if _CANAL_AVISOS and not CANAL_ERROR:
    _PROBLEMAS.append("el perfil del canal tiene valores con el tipo equivocado — " + " · ".join(_CANAL_AVISOS))
# Se concatenan y no se elige uno: con el valor malo en el entorno, el aviso de tipo era el
# diagnóstico bueno y quedaba tapado por el de «no declarado», que corre antes.
if _PROBLEMAS and not CANAL_ERROR:
    CANAL_ERROR = " || ".join(_PROBLEMAS)
