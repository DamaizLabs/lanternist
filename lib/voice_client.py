r"""Adaptador de voz local — sustituye al TTS de pago que traía el fork.

Expone **el mismo contrato** que aquel cliente (`generate_tts_batch`, `generate_tts`)
porque el pipeline no conoce modelos (decisión cerrada 10). Todo ocurre en esta máquina: sin
red, sin claves y a coste marginal 0 € (decisiones 4 y 6).

**Dos motores** (F2.16, 25-08; Orpheus sustituye a Chatterbox el 07-09), y el que manda es el
que declare la receta del canal:

- `kokoro` — voz nativa de catálogo, sin grabación de referencia. Y **el origen de la voz de
  cualquier canal**: es donde se elige el timbre y donde se fabrica el clip que el otro clona.
- `orpheus` — el motor de CLONADO. Recibe ese clip como ejemplo y narra con él, poniendo la
  entonación y las etiquetas emocionales que Kokoro no da.

**Chatterbox era el motor de clonado y ya no está** (07-09). Se descartó comparando los dos, y
la decisión de borrarlo dice: «los resultados son mucho mejores con Orpheus… podemos eliminar completamente
chatterbox porque no lo vamos a usar más». Los comentarios de este archivo que lo nombran cuentan
de dónde salió una guarda, no ofrecen un motor.

Invariantes que este módulo hace cumplir por código, no por confianza:

- **La receta manda.** La que nombre el perfil del canal en `voz.receta`
  (`canales/<canal>/datos/<receta>.json`) es la única fuente de motor, parámetros, semilla,
  segmentación y —si el motor la usa— referencia de voz. Aquí **no hay ni un valor
  duplicado**: si a la receta le falta un campo, el adaptador falla y lo dice, no lo suple con
  un valor propio.
- **Perfil tonal como parámetro**, con el neutro por defecto: `voice` (o el `PERFIL_VOZ` del
  `.env`) nombra un perfil de `perfiles_tonales`. Añadir el registro grave de F2.2b es añadir
  una entrada a ese objeto de la receta — **sin tocar este archivo**; el formato admitido está
  en `_extension_perfiles` de la propia receta.
- **Cruce de venvs explícito.** Los motores de voz pinean torch 2.6.0+cu126, incompatible con
  el `.venv` del pipeline (torch 2.13): la generación
  ocurre en `lib/voice_worker.py`, lanzado como **subproceso** con
  `.venv-voz\Scripts\python.exe`. Este archivo no importa torch ni ningún motor.
- **Generación EN SERIE** (invariante de los 8 GB de la 3060 Ti): un `generate` en vuelo, un
  único subproceso por lote, el modelo cargado una sola vez.
- **Ninguna grabación personal entra en el repo** (lista negra). Todo clip de referencia se lee
  de la variable de entorno que declara la receta y su recorte se cachea en `RUTA_CACHE_VOZ`,
  fuera del árbol del repositorio y en `C:` (NVMe). Los registros de procedencia guardan el
  nombre de la variable y el offset, jamás la ruta personal.
- **NINGÚN motor marca ya el audio como sintético.** Chatterbox traía `perth` y se fue con él;
  ni Kokoro ni Orpheus marcan nada. La declaración de contenido de IA de la subida (flag Art. 50,
  decisión cerrada 7) queda **sin red de seguridad técnica debajo**, y por eso no es opcional.

La procedencia real de cada wav queda en `generacion-voz.json` junto al audio y en
`generation_records()`, que es lo que consumirá `assets.json` (F2.4, decisión cerrada 5).
"""

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import NamedTuple

from lib import provenance
from lib.config import (
    LLAMA_BASE_URL,
    LLAMA_CONTEXTO,
    LLAMA_HOST,
    LLAMA_MODELO_GGUF,
    LLAMA_PORT,
    LLAMA_SERVER,
    LLAMA_STARTUP_TIMEOUT,
    MOTOR_DE_VOZ,
    NARRATION_LANG,
    PRESET_VOICES,
    VOICE_CACHE_DIR,
    VOICE_PROFILE,
    VOICE_PYTHON,
    VOICE_RECIPE_PATH,
    VOICE_TIMEOUT,
    VOICE_WORKER,
    entorno_para_terceros,
)

# Claves de la receta que un perfil tonal puede sobrescribir (el resto es estructura o notas).
# `voz` entra con F2.16: un perfil de Kokoro puede querer otra mezcla, que es su equivalente
# de lo que `referencia_de_voz` es para un motor que clona. `motor` NO está y no debe estar: cambiar de
# motor es una decisión de canal con fila en el addendum, no un matiz de registro tonal.
OVERRIDABLE_KEYS = (
    "modelo",
    "parametros",
    "seed",
    "segmentacion",
    "referencia_de_voz",
    "voz",
    "post_proceso_ffmpeg",
)

# La lengua de la grabación que se clona NO vive aquí (OC1.4): la declara la receta de cada canal en
# `referencia_de_voz.idioma_de_la_referencia`, sin defecto. Hasta OC1.4 era una constante, `"es"`, que era la lengua de
# la grabación del dueño del estudio: cualquier canal la heredaba sin decirlo. Es el eje de la decisión cerrada 13.

# Idiomas que Kokoro cubre, con su `lang_code` y cuántas voces trae. **Verificado el 25-08
# contra el repo del modelo** (`hexgrad/Kokoro-82M`, directorio `voices/`: 54 archivos), no de
# memoria — que es la trampa en la que ya se cayó con una licencia y con un DOI.
# El conteo importa porque la decisión 13 es fuerte donde hay catálogo: en inglés se pudo elegir
# entre 28 y mezclar dos; en francés hay UNA voz, así que ahí la regla no da margen.
KOKORO_IDIOMAS = {
    "en": {"lang_code": "a/b", "voces": 28},
    "es": {"lang_code": "e", "voces": 3},
    "fr": {"lang_code": "f", "voces": 1},
    "hi": {"lang_code": "h", "voces": 4},
    "it": {"lang_code": "i", "voces": 2},
    "ja": {"lang_code": "j", "voces": 5},
    "pt": {"lang_code": "p", "voces": 3},
    "zh": {"lang_code": "z", "voces": 8},
}

# Qué exige cada motor en la raíz de la receta, y si necesita una grabación de referencia.
# La tabla existe para que añadir un motor sea una entrada aquí, no un `if` por el archivo.
MOTORES = {
    "kokoro": {
        "claves": ("modelo", "voz", "parametros", "seed", "segmentacion", "perfiles_tonales"),
        "necesita_referencia": False,
    },
    # Orpheus clona del MISMO bloque `referencia_de_voz` que usaba Chatterbox y del mismo clip de
    # Kokoro; lo que anade es `recorte_por_texto` en la segmentacion, porque es el motor que divaga.
    "orpheus": {
        "claves": ("modelo", "parametros", "seed", "referencia_de_voz", "segmentacion", "perfiles_tonales"),
        "necesita_referencia": True,
    },
}


@contextlib.contextmanager
def motor_de_voz_vivo(motor: str):
    """Garantiza un `llama-server` sirviendo el GGUF declarado durante el bloque.

    Cede `True` si lo arrancó este adaptador —y entonces lo apaga al salir— y `False` si ya había
    uno vivo con el modelo correcto. Es el mismo contrato que `comfy_server()`, con **una diferencia
    dura**: allí, un servidor vivo es de otro proyecto del usuario y no se toca; aquí, un servidor vivo
    puede estar sirviendo **otro** GGUF —el estudio tenía dos en su carpeta de pesos, Q8_0 y Q4_K_M— y
    aprovecharlo sin mirar cuál haría que `assets.json` mienta sobre qué produjo el audio, que es
    exactamente lo que la decisión 5 existe para evitar.

    Con un motor que no sea `orpheus` no hace nada: Kokoro no necesita servidor.
    """
    if motor != "orpheus":
        yield False
        return
    esperado = Path(LLAMA_MODELO_GGUF)
    servido = _modelo_que_sirve()
    if servido is not None:
        if Path(servido).name != esperado.name:
            raise VoiceError(
                f"Hay un llama-server vivo en {LLAMA_BASE_URL} sirviendo {Path(servido).name!r}, "
                f"pero la receta produce audio con {esperado.name!r}. Se para en vez de aprovecharlo: "
                "usar el modelo equivocado dejaría un `assets.json` que miente sobre qué generó el "
                "audio. Apaga ese servidor o cambia LLAMA_MODELO_GGUF."
            )
        print(f"  llama-server ya estaba vivo con {esperado.name}: no se apagará al terminar", flush=True)
        yield False
        return
    if not Path(LLAMA_SERVER).exists():
        raise VoiceError(
            f"Falta el binario de llama.cpp: {LLAMA_SERVER}. Es el runtime de Orpheus y vive fuera del repo, "
            "como herramienta compartida. Instálalo con `py -3.12 instala.py` o apunta LLAMA_SERVER a donde lo "
            "tengas."
        )
    if not esperado.exists():
        raise VoiceError(
            f"Falta el modelo cuantizado: {esperado}. Es el GGUF Q8_0 de Orpheus (3,3 GB). "
            "Descárgalo o apunta LLAMA_MODELO_GGUF a donde lo tengas."
        )
    proc = subprocess.Popen(  # noqa: S603 — binario local declarado en config, sin shell
        [
            str(LLAMA_SERVER),
            "-m",
            str(esperado),
            "-c",
            str(LLAMA_CONTEXTO),
            "-ngl",
            "99",
            "--host",
            LLAMA_HOST,
            "--port",
            str(LLAMA_PORT),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # Sin las credenciales del `.env`: es un binario de terceros y no necesita ninguna.
        env=entorno_para_terceros(),
    )
    arranque = time.perf_counter()
    try:
        while True:
            if proc.poll() is not None:
                raise VoiceError(f"llama-server murió al arrancar (código {proc.returncode}).")
            if _modelo_que_sirve() is not None:
                break
            if time.perf_counter() - arranque > LLAMA_STARTUP_TIMEOUT:
                raise VoiceError(f"llama-server no respondió en {LLAMA_STARTUP_TIMEOUT}s cargando {esperado.name}.")
            time.sleep(1.0)
        print(
            f"  llama-server arrancado con {esperado.name} en {time.perf_counter() - arranque:.0f}s",
            flush=True,
        )
        yield True
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("  llama-server apagado", flush=True)


def _modelo_que_sirve() -> str | None:
    """Ruta del modelo que sirve el servidor, o `None` si no hay ninguno escuchando.

    Se pregunta a `/props` en vez de dar por vivo lo que abre el puerto: «algo responde» no es
    «responde el modelo que espero», y esa distinción es la que protege la procedencia.
    """
    try:
        with urllib.request.urlopen(f"{LLAMA_BASE_URL}/props", timeout=3) as r:
            props = json.load(r)
    except OSError:
        return None
    ajustes = props.get("default_generation_settings") or {}
    return props.get("model_path") or ajustes.get("model") or ""


# Una etiqueta emocional es una marca entre ángulos DENTRO del texto del guion —`<groan>`— que el
# motor convierte en sonido en vez de leerla. **Lo que el motor no reconoce no lo ignora: lo
# PRONUNCIA.** Medido el 08-09 sobre Orpheus Q8_0 con seis semillas por variante y una etiqueta
# inventada como control negativo (addendum fila 115): `<blorp>` produce sonido en el hueco en **6 de
# 6** pasadas, mete una palabra que no está en el guion en **5 de 6**, y en **4 de 6** esa palabra es
# la etiqueta leída —«Blurp!», «Boar!», «Blahp!», «Blurp,»—. O sea que una errata en el guion es el
# narrador diciéndola en voz alta dentro del vídeo.
# Por eso qué etiquetas valen lo declara el canal y se comprueba ANTES de gastar GPU.
#
# **El límite de esta guarda, dicho aquí para que nadie la crea completa**: solo ve la forma
# `<etiqueta>`. `[gasp]`, `(sighs)` y `*sigh*` pasan de largo, y el motor los pronunciaría igual. No
# se amplía a propósito: «(sighs)» es prosa legítima en inglés, y bloquearla sería un falso positivo
# peor que el fallo que evita.
_ETIQUETA_EN_TEXTO = re.compile(r"<([^<>\s]{1,40})>")


def sin_etiquetas(texto: str) -> str:
    """La narración SIN sus etiquetas emocionales: lo que se pinta en pantalla y lo que se cuenta.

    Las etiquetas (`<groan>`) son **sonido, no palabras**: el motor las convierte en una
    vocalización y no las lee. Todo lo que trate el texto como palabras habladas tiene que
    quitarlas antes — los subtítulos (que si no quemarían «groan» en el vídeo, prerequisito de la
    fila 115), el conteo de palabras del verificador y el recorte por texto, que ya lo hace por su
    cuenta en `voice_worker.py`. La regla vive aquí para que los tres usen la MISMA expresión
    regular que decide qué es una etiqueta.
    """
    return " ".join(_ETIQUETA_EN_TEXTO.sub(" ", texto).split())


# Registro en memoria de la procedencia de cada audio generado en el proceso (F2.4)
_GENERATION_RECORDS: list[dict] = []
_RECORDS_FILENAME = "generacion-voz.json"

# Cortes de frase: puntuación final seguida de espacio (comillas y paréntesis de cierre incluidos)
# **Los puntos suspensivos NO cierran frase** (08-09). «It reproduces... an idea about the past» es UNA
# frase con una pausa dentro, y la pausa la interpreta el motor: partir ahí la convertía en dos
# llamadas con 250 ms de silencio pegado —se perdía justo la pausa dramática que el guion de Orpheus
# pide— y dejaba fragmentos de 2 palabras que ni el motor sostiene ni la transcripción localiza
# (episodio 1, lámina 15, segmento «<groan> It reproduces...»: 1/2 palabras, tres reintentos, FAIL).
# Hasta entonces la clase incluía «…» y «...» casaba por acabar en punto. El `(?<!\.\.)` excluye el
# punto que cierra unos puntos suspensivos; el «…» de un solo carácter simplemente ya no está.
# El `»` entra con F5.8: sin él, «wake up.» ␣She…» no tenía final de frase **en ninguna parte** —el
# `\s+` no casa porque detrás del punto hay un signo que la clase no contempla—, así que una cita
# latina se tragaba la narración de después. Es un añadido puro: donde no hay `»` no cambia nada.
_SENTENCE_END = re.compile(r"(?<=[.!?])(?<!\.\.)[\"'”’»)\]]*\s+")
# Cortes de cláusula para frases que pasan del máximo de palabras de la receta. Los puntos
# suspensivos valen aquí —y solo aquí—: si la frase es demasiado larga, partirla en la pausa es el
# corte más natural que hay.
_CLAUSE_END = re.compile(r"(?<=[,;:—–])\s+|(?<=\.\.\.)\s+|(?<=…)\s+")
# Un fragmento de una o dos palabras suelto suena a error de montaje: se pega al anterior
# Mínimo de palabras HABLADAS por llamada al motor en el contrato «frase a frase»: un fragmento de
# 1-2 palabras suelto suena a error de montaje y se pega al vecino. **Se cuentan palabras habladas,
# no tokens** desde el 08-09: «<groan> It reproduces...» son 3 tokens y 2 palabras, y contar tokens
# es lo que lo dejó pasar. Este valor NO se sube para todos los motores: con 5, el texto A2 de un canal
# («It was Saturday morning. The house was very quiet.») se fundía en una sola llamada de 21
# palabras, o sea el estudio imponiendo a un canal la política de agrupado que cada receta declara.
_MIN_WORDS_PER_SEGMENT = 3
# Lo que sí necesita más es ORPHEUS, y es una propiedad del motor —del estudio, fila 119—, no una
# preferencia de canal: divaga, y el recorte por transcripción tiene que anclar la última palabra
# del segmento. En la pasada del 08-09 las seis veces que no casó, el segmento tenía 2 o 3 palabras,
# y el que tumbó la etapa tenía 2 (fila 127). Por debajo de 5 el clon además es inestable (decisión 13).
_MIN_WORDS_ORPHEUS = 5


def min_palabras_por_llamada(motor: str) -> int:
    """Palabras habladas mínimas por llamada según el motor: 5 con Orpheus, 3 con los demás."""
    return _MIN_WORDS_ORPHEUS if (motor or "").strip().lower() == "orpheus" else _MIN_WORDS_PER_SEGMENT


class VoiceError(RuntimeError):
    """Fallo del runtime de voz: receta incompleta, referencia ausente o generación fallida.

    `parcial` lleva el resultado que el subproceso alcanzó a volcar antes de morir (vuelca en
    cada archivo terminado). Es lo que permite registrar la procedencia de los audios que SÍ
    se locutaron en una etapa interrumpida, en vez de dejar wav sin origen: `assets.json` tiene
    que cuadrar con lo que hay en disco (F2.4, decisión cerrada 5).
    """

    def __init__(self, *args, parcial: dict | None = None):
        super().__init__(*args)
        self.parcial = parcial


# --------------------------------------------------------------------------------------
# Receta y perfiles tonales
# --------------------------------------------------------------------------------------


def _require(source: dict, key: str, where: str):
    """Lee una clave obligatoria de la receta o falla diciendo dónde falta."""
    if key not in source or source[key] is None:
        raise VoiceError(
            f"La receta de voz ({VOICE_RECIPE_PATH.name}) no declara '{key}' en {where}. "
            "El adaptador no inventa valores: la receta es la fuente."
        )
    return source[key]


def load_recipe() -> dict:
    """Lee la receta de voz y comprueba sus invariantes antes de devolverla."""
    if not VOICE_RECIPE_PATH.exists():
        raise VoiceError(
            f"No existe la receta de voz: {VOICE_RECIPE_PATH}. En un canal nuevo la crea `crea-canal` en su paso 4"
        )
    recipe = json.loads(VOICE_RECIPE_PATH.read_text(encoding="utf-8"))

    if recipe.get("pendiente_confirmacion_usuario"):
        raise VoiceError(
            f"{VOICE_RECIPE_PATH.name} está marcada 'pendiente_confirmacion_usuario': la elección de voz "
            "es del usuario (G1.4), no del pipeline. No se produce audio con una receta sin confirmar."
        )
    motor = _require(recipe, "motor", "la raíz de la receta")
    if motor not in MOTORES:
        raise VoiceError(
            f"La receta declara motor {motor!r}, que este adaptador no implementa. "
            f"Admitidos: {sorted(MOTORES)}. Añadir uno es una entrada en MOTORES más su clase "
            "en lib/voice_worker.py."
        )
    for key in MOTORES[motor]["claves"]:
        _require(recipe, key, "la raíz de la receta")
    _exige_la_lengua_de_la_referencia(recipe, motor)

    # **Qué etiquetas emocionales admite el guion de este canal, y sin defecto (F4.9).** Se
    # comprueba la presencia en vez de con `_require` porque **la lista vacía es una respuesta
    # legítima**: «este canal no escribe etiquetas» es una decisión, y `_require` rechaza los
    # valores falsos. La clave es obligatoria para los dos motores a propósito: el riesgo no es de
    # Orpheus, es de cualquier motor al que le llegue una marca que no sabe convertir en sonido.
    if "etiquetas_emocionales" not in recipe:
        raise VoiceError(
            f"La receta de voz ({VOICE_RECIPE_PATH.name}) no declara 'etiquetas_emocionales' en su "
            "raíz. Tiene que llevar `permitidas` con las marcas que el guion puede escribir entre "
            'ángulos: `{"permitidas": ["groan"]}` si el canal las usa, o `{"permitidas": []}` si '
            "no escribe ninguna. No tiene defecto porque lo que el motor no reconoce **lo dice en "
            "voz alta** dentro del vídeo, y qué emociones marca un guion es del canal."
        )
    etiquetas = recipe["etiquetas_emocionales"] or {}
    permitidas = etiquetas.get("permitidas")
    if "permitidas" not in etiquetas or not isinstance(permitidas, list):
        raise VoiceError(
            f"'etiquetas_emocionales' de la receta ({VOICE_RECIPE_PATH.name}) no declara "
            "'permitidas' como lista. Lista vacía = este canal no escribe etiquetas."
        )
    # El criterio es el mismo que exige `tests/test_voz_etiquetas.py`: **ni un ángulo ni un espacio**.
    # Rechazar solo el patrón completo `<x>` dejaba pasar `"groan>"`, `"<groan"` y `"gro an"`, que son
    # entradas MUERTAS —la regex nunca produce nombres así, así que jamás casarían— y además salían
    # deformes en el mensaje de error («admitidas: <groan>>»).
    for etiqueta in permitidas:
        if not isinstance(etiqueta, str) or not etiqueta.strip() or re.search(r"[<>\s]", etiqueta):
            raise VoiceError(
                f"'etiquetas_emocionales.permitidas' trae {etiqueta!r}: se escriben SIN ángulos "
                '("groan", no "<groan>"), que es como se comparan contra el texto del guion.'
            )

    paquete = _require(recipe["modelo"], "paquete", "modelo")
    # **Se compara contra `motor`, NO contra el nombre del paquete.** Buscar `voz.modelo` dentro de
    # la cadena del paquete funcionaba de casualidad mientras los motores se llamaban como su
    # librería —«kokoro» está dentro de «kokoro 0.9.4»—, y se rompe con Orpheus, cuyo paquete es
    # «transformers 5.2.0 + snac 1.2.1»: un canal perfectamente coherente fallaría el `--check`.
    # Dos motores pueden compartir librería (Kokoro y Orpheus comparten `.venv-voz`) y un motor
    # puede cambiar de librería sin dejar de ser el mismo, así que el paquete nunca fue el campo.
    # **La receta declara para qué motor está escrita; el ESTUDIO declara cuál está en uso.** Si no
    # coinciden, se para. La clave `motor` de la receta dejó de ser una elección del canal el 08-09
    # (addendum fila 119) y pasó a ser una declaración comprobable: sirve para que apuntar a la
    # receta equivocada dé este mensaje en vez de un error oscuro sobre una clave que falta.
    if motor.strip().lower() != MOTOR_DE_VOZ.strip().lower():
        raise VoiceError(
            f"La receta {VOICE_RECIPE_PATH.name} está escrita para el motor {motor!r} (paquete "
            f"{paquete}) y el motor del estudio es {MOTOR_DE_VOZ!r}. **El motor NO es una decisión "
            "de canal**: un canal declara su voz semilla, su velocidad, su idioma y el texto de su "
            "referencia, no quién clona. Apunta `perfil.json → voz.receta` a la "
            f"receta de {MOTOR_DE_VOZ}, o cambia el motor del estudio en `lib/config.py` "
            "(`MOTOR_DE_VOZ`)."
        )
    modo = (recipe.get("generacion") or {}).get("modo", "en serie")
    if modo != "en serie":
        raise VoiceError(
            f"La receta pide generación '{modo}': prohibido. Los lotes NUNCA se paralelizan en GPU "
            "(invariante de los 8 GB de la 3060 Ti)."
        )
    return recipe


def _exige_la_lengua_de_la_referencia(recipe: dict, motor: str) -> None:
    """Un motor que clona necesita saber en qué lengua habla su grabación de referencia. Para si la receta no lo dice.

    La decisión cerrada 13 compara esa lengua con la de la narración (`revisa_politica_de_idioma`): clonar una voz en
    una lengua que su grabación no contiene interpola fonemas que nunca oyó. No tiene defecto (F4.9): un defecto sería
    la lengua de la grabación de otro, y hasta OC1.4 lo era (`"es"`, la del dueño del estudio).
    """
    if not MOTORES[motor]["necesita_referencia"]:
        return
    idioma = (recipe.get("referencia_de_voz") or {}).get("idioma_de_la_referencia")
    if not isinstance(idioma, str) or not idioma.strip():
        raise VoiceError(
            f"La receta de voz ({VOICE_RECIPE_PATH.name}) no declara `referencia_de_voz.idioma_de_la_referencia`: la "
            "lengua que se habla en la grabación de referencia que clona el motor, en ISO 639-1. Escríbela, por "
            'ejemplo `"idioma_de_la_referencia": "en"` si la referencia es una voz inglesa del catálogo de Kokoro. '
            "No tiene defecto: la política de voz por idioma la compara con la lengua de la narración del canal."
        )


def available_profiles(recipe: dict | None = None) -> list[str]:
    """Perfiles tonales disponibles en la receta (el neutro y los que añada F2.2b)."""
    return sorted((recipe or load_recipe())["perfiles_tonales"])


def default_profile(recipe: dict) -> str:
    """Perfil por defecto: el que declare la receta (hoy, el registro neutro de narración)."""
    profile_id = _require(recipe, "perfil_por_defecto", "la raíz de la receta")
    if profile_id not in recipe["perfiles_tonales"]:
        raise VoiceError(
            f"'perfil_por_defecto' apunta a '{profile_id}', que no está en perfiles_tonales "
            f"({available_profiles(recipe)})"
        )
    return profile_id


def resolve_profile(recipe: dict, voice: str | None = None, profile: str | None = None) -> str:
    """Decide el perfil tonal: `profile` explícito > `voice` > PERFIL_VOZ del .env > el neutro."""
    profiles = recipe["perfiles_tonales"]
    for candidate, origen in (
        (profile, "el argumento profile"),
        (voice, "el argumento voice"),
        (VOICE_PROFILE, "PERFIL_VOZ del .env"),
    ):
        name = (candidate or "").strip()
        if not name:
            continue
        if name in profiles:
            return name
        if name in PRESET_VOICES:
            # Herencia del cliente de pago: «josh» y compañía eran sus voces preset.
            # El adaptador local trabaja con la voz del canal y perfiles tonales.
            print(
                f"  Aviso: '{name}' era una voz preset del TTS de pago; se usa el perfil tonal por defecto",
                flush=True,
            )
            continue
        raise VoiceError(
            f"Perfil tonal desconocido en {origen}: '{name}'. Disponibles en {VOICE_RECIPE_PATH.name}: "
            f"{available_profiles(recipe)}. Un perfil nuevo se añade a la receta (ver '_extension_perfiles'), "
            "no al código."
        )
    return default_profile(recipe)


def resolve_recipe(recipe: dict, profile_id: str) -> dict:
    """Aplica el perfil tonal sobre la receta base y devuelve los valores efectivos.

    La mezcla es parcial por sección: un perfil puede tocar una sola sección de la receta y hereda
    el resto, así que un registro nuevo se añade escribiendo únicamente en el JSON.
    """
    profile = recipe["perfiles_tonales"][profile_id]
    overrides = profile.get("sobrescribe") or {}
    unknown = sorted(set(overrides) - set(OVERRIDABLE_KEYS))
    if unknown:
        raise VoiceError(
            f"El perfil tonal '{profile_id}' sobrescribe claves no admitidas: {unknown}. "
            f"Admitidas: {list(OVERRIDABLE_KEYS)} (ver '_extension_perfiles' en la receta)."
        )
    resolved: dict = {"perfil": profile_id, "descripcion_perfil": profile.get("descripcion", "")}
    for key in OVERRIDABLE_KEYS:
        base, over = recipe.get(key), overrides.get(key)
        if isinstance(base, dict) and isinstance(over, dict):
            resolved[key] = {**base, **over}
        else:
            resolved[key] = base if over is None else over
    return resolved


# --------------------------------------------------------------------------------------
# Segmentación del guion (política de la receta: frase a frase)
# --------------------------------------------------------------------------------------


# --------------------------------------------------------------------------------------
# Diálogo: la línea de un personaje llega al motor SOLA (F5.8)
# --------------------------------------------------------------------------------------
# **Por qué, medido el 15-09 con las cuatro variantes de una cata de diálogo de un canal**, todas
# generadas por el camino real del estudio. El motor entona cada llamada con UN registro, así que un
# grito metido en el mismo bocado que la narración de alrededor sale con la voz del narrador. El
# «wake up» del episodio 1 de ese canal da **165,5 Hz** dentro de su bocado de 17 palabras (variante A, la
# de producción) y **240,0 Hz** cuando el segmento es solo suyo (variante B) — **+6,4 semitonos**, y
# Se eligió la B escuchando las cuatro. Las cifras están en el `medicion-tono.json` de esa cata,
# en `experimentos/` (fuera de git).
#
# Dos resultados de esa cata son el diseño de esto, no un adorno:
#
# - **La atribución va CON la cita.** La cita sola, sin «Ollie shouted,», se quedó en 208,7 Hz
#   (variante C, descartada): la atribución no estorba, ayuda. Por eso el trozo que se aísla
#   es la FRASE entera que contiene la cita, no la cita recortada.
# - **No se toca cómo se escriben los guiones.** La variante D —la misma cita con más énfasis
#   escrito— dio el MISMO tono que la B y se descartó: «se distorsiona la voz y la hace más
#   robótica». Esto es un cambio de TROCEO y solo de troceo.
#
# **La comilla simple no está y no puede estar**: en inglés `'` y `’` son apóstrofo —«It's»,
# «Mum's»—, y tomarlos por cita partiría la narración por donde no habla nadie.
_COMILLAS = {'"': '"', "“": "”", "«": "»"}


class _Trozo(NamedTuple):
    """Un trozo de narración y a qué cita pertenece (`None` = narración, no habla nadie).

    **Es un identificador y no un sí/no a propósito.** Con una marca booleana, dos líneas seguidas
    de personajes DISTINTOS cuentan como «del mismo tipo» y se funden en un bocado —medido en la
    lámina 2 del episodio 1 de un canal: «Then he said, "But we don't know how to make a cake." Nora
    replied, "It's easy...» salía en una sola llamada—, que es el mismo defecto que esta feature
    arregla, solo que entre dos personajes en vez de entre personaje y narrador.

    La marca vive **solo dentro del troceo**: `split_narration` devuelve cadenas, igual que siempre.
    Un canal no declara nada para que esto funcione (F5.8, criterio 5): el troceo es mecanismo del
    estudio, y quién habla lo dice el propio texto del guion.
    """

    texto: str
    cita: int | None

    @property
    def dialogo(self) -> bool:
        return self.cita is not None


def _une(uno: _Trozo, otro: _Trozo) -> _Trozo:
    """Pega dos trozos. El resultado hereda la cita del primero que tenga una.

    Así un trozo que acabe con diálogo dentro nunca vuelve a agruparse como si fuera narración, que
    es lo único que la marca decide a partir de aquí.
    """
    return _Trozo(f"{uno.texto} {otro.texto}", uno.cita if uno.cita is not None else otro.cita)


def _tramos_citados(texto: str) -> list[tuple[int, int]]:
    """Posiciones (apertura, cierre) de cada cita, ambas incluidas.

    **Una comilla sin cerrar no abre nada**: se ignora y el texto se trocea como si no estuviera.
    Es deliberado (criterio 8 de F5.8) — sin cierre no hay dónde acabar la línea del personaje, y dar
    por citado «de aquí al final» convertiría el resto de la lámina en un solo bocado, que es peor
    que el defecto que esto arregla. Con la comilla recta, que abre y cierra igual, las parejas se
    hacen por orden de aparición: es la única lectura posible cuando el signo no dice de qué lado va.
    """
    tramos: list[tuple[int, int]] = []
    i = 0
    while i < len(texto):
        cierre = _COMILLAS.get(texto[i])
        if cierre is None:
            i += 1
            continue
        fin = texto.find(cierre, i + 1)
        if fin == -1:  # comilla sin pareja: no es una cita
            i += 1
            continue
        tramos.append((i, fin))
        i = fin + 1
    return tramos


def _corta_en_frases(texto: str, intocables: list[tuple[int, int]]) -> list[str]:
    """Trocea por finales de frase, saltándose los cortes que caigan dentro de un tramo intocable.

    Dos detalles que no son evidentes leyendo `_SENTENCE_END`:

    1. **El corte va ENTRE `start()` y `end()`.** Cae dentro de la cita si lo que sigue al separador
       sigue siendo parte de ella: por eso el `!` de «wake up!» no corta y el punto de «birthday."»
       sí, porque su comilla ya cerró.
    2. **El signo de cierre se queda con su frase.** El separador se come las comillas y los
       paréntesis de cierre, así que hasta F5.8 el motor recibía «...birthday.» sin cerrar: **29
       veces** en el episodio 1 de un canal (contado sobre el `slides.json` de su run del 14-09) y **0 veces** en
       los seis runs de otro, que no escriben ni una comilla.
    """
    piezas: list[str] = []
    inicio = 0
    for corte in _SENTENCE_END.finditer(texto):
        if any(a < corte.end() <= b for a, b in intocables):
            continue
        pieza = texto[inicio : corte.start() + len(corte.group(0).rstrip())].strip()
        if pieza:
            piezas.append(pieza)
        inicio = corte.end()
    resto = texto[inicio:].strip()
    if resto:
        piezas.append(resto)
    return piezas


def _frases(texto: str) -> list[_Trozo]:
    """Frases del texto, marcando cuáles llevan una cita dentro; dentro de una cita no se corta.

    «Ollie shouted, "¡Nora, wake up! It's Mum's birthday."» es UNA frase para el motor aunque lleve
    un `!` y un `.` dentro. Partirla ahí repartiría al personaje entre dos llamadas, cada una
    entonada por su cuenta, que es justo lo que suena a narrador (criterio 4 de F5.8: la cita de
    varias frases se mantiene entera).

    **Lo que esta función no sabe distinguir, dicho para que nadie la crea más lista**: una cita de
    diálogo de un término entrecomillado («the records call it a "bridle"»). Las dos se aíslan igual.
    Separarlas exigiría juzgar el significado, y la consecuencia de confundirlas es pequeña y de un
    solo lado: esa frase no se agrupa con sus vecinas. Nunca parte una frase que hoy no se parta.
    """
    return [
        _Trozo(pieza, numero if _tramos_citados(pieza) else None)
        for numero, pieza in enumerate(_corta_en_frases(texto, _tramos_citados(texto)))
    ]


def _hard_split(words: list[str], max_words: int) -> list[str]:
    return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)]


def _split_long_sentence(sentence: str, max_words: int) -> list[str]:
    """Parte una frase que pasa del máximo por cláusulas y, en último recurso, por palabras."""
    if len(sentence.split()) <= max_words:
        return [sentence]
    pieces, current = [], []
    for clause in _CLAUSE_END.split(sentence):
        clause_words = clause.split()
        if len(clause_words) > max_words:
            if current:
                pieces.append(" ".join(current))
                current = []
            pieces.extend(_hard_split(clause_words, max_words))
            continue
        if len(current) + len(clause_words) > max_words:
            pieces.append(" ".join(current))
            current = []
        current.extend(clause_words)
    if current:
        pieces.append(" ".join(current))
    return pieces


def _parte_si_pasa(frase: _Trozo, max_words: int) -> list[str]:
    """Trocea la frase si pasa del techo de palabras, por donde menos se note.

    En una frase normal, por cláusulas (`_split_long_sentence`). **En una cita, primero por las
    frases de DENTRO**, que es el corte natural de una línea larga de un personaje: partir por comas
    dejaba cosas como «Nora replied, "It's easy. Flour, eggs, sugar,» · «butter. You mix them...»
    (episodio 1 de un canal, lámina 2, cita de 21 palabras contra un techo de 20). El techo manda igual
    —por encima de él el motor acelera, medido en F1.2c: 210 wpm a 60 palabras—, así que una cita que
    no cabe se parte; lo que elige esto es dónde.
    """
    if len(frase.texto.split()) <= max_words:
        return [frase.texto]
    if frase.dialogo:
        piezas = _corta_en_frases(frase.texto, [])
        if len(piezas) > 1:
            return [trozo for pieza in piezas for trozo in _split_long_sentence(pieza, max_words)]
    return _split_long_sentence(frase.texto, max_words)


def _merge_tiny(segments: list[_Trozo], max_words: int, min_words: int = _MIN_WORDS_PER_SEGMENT) -> list[_Trozo]:
    """Funde cada fragmento de menos de `min_words` palabras HABLADAS con un vecino.

    Se pega al anterior; si no hay anterior, se guarda y se antepone al siguiente. **Se funde aunque
    el resultado pase de `max_words`**: la versión anterior solo pegaba «cuando cupiera», y un
    fragmento que no cabía se quedaba suelto, que es el peor de los dos males — una llamada de 24
    palabras es inocua y una de 2 palabras es la que no se sostiene ni se puede recortar. Cuenta
    palabras habladas, sin etiquetas emocionales: «<groan> It reproduces...» son tres tokens y dos
    palabras, y contar tokens es lo que dejó pasar ese fragmento el 08-09.

    **Con qué vecino, desde F5.8**: con el de la MISMA cita si hay elección — y narración con
    narración. Una frase corta de narración detrás de una línea de diálogo —«He said nothing.»— se
    pegaba al bocado del personaje y le metía narración detrás, que es medio defecto que esta feature
    arregla. Se mira primero el anterior y luego el siguiente; **si ninguno vale, se funde igual con
    el anterior**, porque el mínimo por llamada es del MOTOR (5 palabras con Orpheus, fila 127: los
    segmentos de 2-3 palabras son los que no casan en el recorte por transcripción y tumbaron la
    etapa) y eso manda sobre una preferencia de prosodia.

    En un texto sin diálogo todos los trozos son narración, así que la preferencia nunca entra y el
    resultado es **exactamente** el de antes de F5.8 (criterio 6, el control negativo).
    """
    del max_words  # se conserva la firma; el techo ya lo aplicó `_split_long_sentence` a cada pieza

    def habladas(texto: str) -> int:
        return len(sin_etiquetas(texto).split())

    result: list[_Trozo] = []
    pendiente: _Trozo | None = None  # un fragmento sin anterior (o que espera a uno de su tipo)
    for indice, segment in enumerate(segments):
        if pendiente is not None:
            segment = _une(pendiente, segment)
            pendiente = None
        if habladas(segment.texto) >= min_words:
            result.append(segment)
            continue
        siguiente = segments[indice + 1] if indice + 1 < len(segments) else None
        if result and result[-1].cita == segment.cita:
            result[-1] = _une(result[-1], segment)
        elif siguiente is not None and siguiente.cita == segment.cita:
            pendiente = segment
        elif result:
            result[-1] = _une(result[-1], segment)
        else:
            pendiente = segment
    if pendiente is not None:  # todo el texto era corto: va tal cual, no se pierde nada
        result.append(pendiente)
    return result


def _agrupa(segments: list[_Trozo], techo: int) -> list[_Trozo]:
    """Junta frases seguidas hasta el techo de palabras, sin partir ninguna.

    **Por qué existe, medido el 05-09 en el piloto de un canal.** El motor estira los fonemas cuando el
    trozo que sintetiza es corto, y la narración frase a frase le da trozos de 6 palabras. Sobre el
    MISMO texto —las 21 palabras del arranque del episodio 1— la voz tarda **10,76 s** troceada
    frase a frase y **8,20 s** en una sola llamada: un 31 % más lenta, con la entonación plana de
    quien lee una línea suelta. Se oyó antes de que nadie lo midiera: «la del vídeo se escucha
    distorsionada y robótica».

    Y la idea de quitar el troceo entero **está medida y es peor**: la aceleración ocurre DENTRO del
    trozo, así que un párrafo largo empieza a 128 palabras por minuto de voz y acaba a 230. Agrupar
    hasta un techo fijo da lo mejor de los dos: prosodia de varias frases seguidas y el mismo tamaño
    de trozo en todo el vídeo, o sea ritmo parejo.

    El techo lo pone el canal en su receta (`segmentacion.agrupa_hasta_palabras`) y no tiene defecto
    en el estudio: `null` significa «frase a frase», que es lo que hacía el primer canal.

    **Lo que NO se agrupa desde F5.8: el diálogo.** Un trozo con una cita dentro no se junta con
    nadie —ni con narración ni con otra cita—, porque el motor entona cada llamada con un registro y
    juntar dos voces en un bocado es lo que hacía que el grito de Ollie sonara a narrador (165,5 Hz
    agrupado contra 240,0 Hz solo). Dos líneas seguidas de personajes distintos tampoco se juntan,
    por el mismo motivo.
    """
    grupos: list[_Trozo] = []
    for segmento in segments:
        cabe = grupos and len(grupos[-1].texto.split()) + len(segmento.texto.split()) <= techo
        if cabe and not grupos[-1].dialogo and not segmento.dialogo:
            grupos[-1] = _une(grupos[-1], segmento)
        else:
            grupos.append(segmento)
    return grupos


def split_narration(
    text: str, max_words: int, agrupa_hasta: int | None = None, min_words: int = _MIN_WORDS_PER_SEGMENT
) -> list[str]:
    """Trocea la narración según la política de la receta.

    Dos pasos, y el segundo es opcional:

    1. **Frase a frase**, partiendo por cláusulas las que pasan de `max_words`. Medido en la palanca
       C de F1.2c: una frase de 60 palabras se acelera a 210 wpm (fuera de la banda de narración
       documental) mientras que las de 7-16 palabras se quedan en 149 wpm.
    2. **Agrupando** frases seguidas hasta `agrupa_hasta` palabras, si el canal lo declara. El
       porqué está en `_agrupa`: sin agrupar, el motor estira los fonemas y suena a máquina.

    `agrupa_hasta=None` deja el troceo en el paso 1, que es el comportamiento de siempre.

    **Y el diálogo va aparte en los dos pasos** (F5.8, ver `_frases`): la frase que lleva una cita no
    se parte por dentro y no se agrupa con sus vecinas, para que el personaje llegue al motor en su
    propio bocado. Una cita que pase de `max_words` sí se parte por cláusulas, como cualquier frase
    larga: el techo de palabras manda, porque por encima el motor acelera.
    """
    flat = " ".join((text or "").split())
    if not flat:
        raise VoiceError("Texto de narración vacío: no hay nada que locutar")
    segments: list[_Trozo] = []
    for frase in _frases(flat):
        segments.extend(_Trozo(pieza, frase.cita) for pieza in _parte_si_pasa(frase, max_words))
    segments = _merge_tiny(segments, max_words, min_words)
    if agrupa_hasta:
        if agrupa_hasta < max_words:
            raise VoiceError(
                f"`segmentacion.agrupa_hasta_palabras` ({agrupa_hasta}) es menor que "
                f"`max_palabras_por_frase` ({max_words}): el techo de agrupar no puede estar por "
                "debajo del techo de partir, porque entonces una frase larga ya no cabría en su "
                "propio grupo."
            )
        segments = _agrupa(segments, agrupa_hasta)
    return [trozo.texto for trozo in segments]


# --------------------------------------------------------------------------------------
# Clip de referencia (la grabación vive FUERA del repo)
# --------------------------------------------------------------------------------------


def _require_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise VoiceError("ffmpeg no está en el PATH: hace falta para recortar el clip de referencia")
    return exe


def resolve_recording(spec: dict) -> tuple[str, Path]:
    """Localiza la grabación de referencia por la variable de entorno que nombra la receta (nunca por ruta).

    `variable_entorno` es el nombre de UNA variable. Hasta el 01-10-2026 admitía una lista por orden de
    preferencia, que solo pedía el perfil de voz grave de F2.2b (`RUTA_VOZ_GRAVE`); se retiró al cancelar
    D2.1 (fila 227), y ninguna receta la usaba.
    """
    name = _require(spec, "variable_entorno", "referencia_de_voz")
    if not isinstance(name, str):
        raise VoiceError(
            f"`referencia_de_voz.variable_entorno` tiene que ser el nombre de UNA variable de entorno, no {name!r}"
        )
    raw = os.getenv(name, "").strip().strip('"')
    if raw and Path(raw).exists():
        return name, Path(raw)
    raise VoiceError(
        f"No hay grabación de referencia utilizable ({name}: {'sin valor' if not raw else 'el archivo no existe'}). "
        "Se lee SIEMPRE del entorno: una grabación de voz jamás entra en el repositorio (lista negra)."
    )


def prepare_reference(spec: dict) -> tuple[Path, dict]:
    """Recorta el clip que pide la receta y lo deja en la caché de `C:`, fuera del repo."""
    env_name, recording = resolve_recording(spec)
    option_id = _require(spec, "opcion_activa", "referencia_de_voz")
    option = spec.get(option_id)
    if not isinstance(option, dict):
        raise VoiceError(f"'opcion_activa' apunta a '{option_id}', que no es una opción de referencia_de_voz")
    offset = float(_require(option, "offset_segundos", f"referencia_de_voz.{option_id}"))
    seconds = float(_require(option, "duracion_segundos", f"referencia_de_voz.{option_id}"))
    fmt = _require(spec, "formato_clip", "referencia_de_voz")

    meta = {
        "variable_entorno": env_name,
        "opcion": option_id,
        "id": option.get("id", option_id),
        "offset_segundos": offset,
        "duracion_segundos": seconds,
        "nota": "la grabación vive fuera del repo; aquí solo su procedencia, nunca la ruta",
    }
    # El nombre del clip es determinista (opción + tramo + hash de la ruta de origen): se
    # reutiliza entre runs sin volver a tocar la grabación.
    tag = hashlib.sha1(str(recording.resolve()).encode("utf-8")).hexdigest()[:8]
    VOICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    clip = VOICE_CACHE_DIR / f"ref-{meta['id']}-{offset:g}s-{seconds:g}s-{tag}.wav"
    if clip.exists() and clip.stat().st_size > 0:
        return clip, meta

    subprocess.run(
        [
            _require_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{offset:.2f}",
            "-i",
            str(recording),
            "-t",
            f"{seconds:.2f}",
            "-ac",
            str(_require(fmt, "canales", "referencia_de_voz.formato_clip")),
            "-ar",
            str(_require(fmt, "sample_rate_hz", "referencia_de_voz.formato_clip")),
            "-c:a",
            str(_require(fmt, "codec", "referencia_de_voz.formato_clip")),
            str(clip),
        ],
        check=True,
    )
    print(
        f"  Clip de referencia listo ({env_name}, {meta['id']}: {offset:g}s +{seconds:g}s) en la caché de C:",
        flush=True,
    )
    return clip, meta


# --------------------------------------------------------------------------------------
# Subproceso de generación (el único que ve torch y los motores de voz)
# --------------------------------------------------------------------------------------


def _log_tail(path: Path, lines: int = 15) -> str:
    """Últimas líneas del log del subproceso, para que el error no obligue a abrir el archivo."""
    if not path.exists():
        return "(sin log)"
    with contextlib.suppress(OSError, UnicodeDecodeError):
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    return "(log ilegible)"


def _run_worker(job: dict) -> dict:
    """Lanza `lib/voice_worker.py` con el intérprete de `.venv-voz` y devuelve su resultado.

    Sin reintentos: un fallo del runtime local se propaga tal cual. El stdout del hijo se
    hereda (avance frase a frase) y su stderr va a un log, porque el motor escupe ahí una
    barra de progreso por frase que ahogaría el registro de un guion largo; si falla, el error
    se cita desde ese log.
    """
    python = Path(VOICE_PYTHON)
    if not python.exists():
        raise VoiceError(
            f"No existe el intérprete del venv de voz: {python}. Se crea con "
            "`py -3.12 -m venv .venv-voz` + `spikes/requirements-voz.txt` (torch 2.6.0+cu126, setuptools<81)."
        )
    if not VOICE_WORKER.exists():
        raise VoiceError(f"Falta el generador de voz: {VOICE_WORKER}")

    jobs_dir = VOICE_CACHE_DIR / "trabajos"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    job_path = jobs_dir / f"trabajo-{stamp}.json"
    result_path = jobs_dir / f"resultado-{stamp}.json"
    log_path = jobs_dir / f"log-{stamp}.txt"
    job_path.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"  Generando con {python.parent.parent.name} (subproceso); log del modelo en {log_path}", flush=True)
    try:
        with open(log_path, "wb") as log:
            proc = subprocess.run(  # noqa: S603 — intérprete local del propio repo, sin shell
                [str(python), str(VOICE_WORKER), "--trabajo", str(job_path), "--resultado", str(result_path)],
                stderr=log,
                timeout=VOICE_TIMEOUT,
                check=False,
            )
    except subprocess.TimeoutExpired as expired:
        raise VoiceError(
            f"El generador de voz pasó de {VOICE_TIMEOUT}s y se ha matado (trabajo en {job_path}). "
            f"Últimas líneas:\n{_log_tail(log_path)}",
            parcial=_read_partial(result_path),
        ) from expired
    if proc.returncode != 0:
        raise VoiceError(
            f"El generador de voz falló (código {proc.returncode}). No hay reintento automático: "
            f"trabajo en {job_path}, log en {log_path}. Últimas líneas:\n{_log_tail(log_path)}",
            parcial=_read_partial(result_path),
        )
    if not result_path.exists():
        raise VoiceError(f"El generador de voz no dejó resultado en {result_path}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def _read_partial(result_path: Path) -> dict | None:
    """Resultado que el subproceso alcanzó a volcar antes de morir, si queda algo legible.

    El generador escribe su resultado tras CADA archivo terminado, así que esto es la lista
    de audios que existen de verdad en disco cuando la etapa se rompe a media tanda.
    """
    if not result_path.exists():
        return None
    with contextlib.suppress(OSError, json.JSONDecodeError):
        return json.loads(result_path.read_text(encoding="utf-8"))
    return None


def _apply_post_processing(path: Path, spec) -> str | None:
    """Aplica la cadena de filtros de ffmpeg que declare el perfil tonal (palanca 3 de F2.2b)."""
    filters = spec if isinstance(spec, str) else (spec or {}).get("filtros")
    if isinstance(filters, list):
        filters = ",".join(filters)
    if not filters:
        return None
    if "://" in filters:
        raise VoiceError(
            f"El post-proceso del perfil declara una fuente remota ({filters!r}): prohibido, nada entra ni sale del PC."
        )
    processed = path.with_name(f"{path.stem}-post{path.suffix}")
    subprocess.run(
        [
            _require_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-af",
            filters,
            str(processed),
        ],
        check=True,
    )
    processed.replace(path)
    return filters


# --------------------------------------------------------------------------------------
# Procedencia (la consume assets.json en F2.4)
# --------------------------------------------------------------------------------------


def generation_records() -> list[dict]:
    """Procedencia real de los audios generados en este proceso."""
    return list(_GENERATION_RECORDS)


def _dump_records(output_dir: Path, new_entries: list[dict]) -> None:
    """Deja la procedencia de los audios junto a ellos: `provenance.anade_registros` (una sola puerta, F6.2d)."""
    provenance.anade_registros(Path(output_dir) / _RECORDS_FILENAME, new_entries)


def _register_records(result: dict, pending: list[dict], out_dir: Path, context: dict) -> list[dict]:
    """Convierte el resultado del generador en registros de procedencia y los deja en disco.

    Se usa igual en el camino bueno y en el rescate de un lote roto, así que empareja por
    índice **sin exigir el mismo número** (`strict=False`): el resultado parcial trae menos
    audios que los pedidos, y registrar los que existen es justo lo que se quiere. Quien
    necesite el lote completo lo comprueba después (lo hace `generate_tts_batch`).
    """
    job = context["job"]
    modelo = context["modelo"]
    records: list[dict] = []

    # Identidad de la voz en el registro de procedencia. Se separa por motor porque los dos no
    # tienen los mismos campos, y uno de ellos NO es cosmetico: **ninguno de los dos marca el audio
    # como sintetico**, y hasta el 07-09 si lo hacia uno (el `perth` de Chatterbox). Callarlo aqui
    # dejaria un assets.json que afirma un watermark inexistente, justo en el archivo que es la
    # defensa documental (decision 5).
    if job["motor"] == "orpheus":
        identidad = {
            "modelo": f"{job['modelo']['repo_id']} (clonado zero-shot)",
            "language_id": None,
            "referencia_de_voz": context["referencia"],
            "watermark": (
                "NINGUNO: Orpheus no marca el audio como sintético, igual que Kokoro y al revés que "
                "Chatterbox, que traía `perth`. Lo que lo declara como IA es la declaración "
                "de contenido de IA de la subida (flag Art. 50), que por eso NO es opcional. **Este "
                "motor RETIRA la red de seguridad técnica que el canal tenía cuando clonaba con "
                "Chatterbox**, y decirlo aquí es el motivo de que esta identidad se separe."
            ),
        }
    else:
        identidad = {
            "modelo": f"{job['modelo']['repo_id']} · voz {job['voz']['id']}",
            "voz": job["voz"],
            "language_id": job["modelo"]["lang_code"],
            "referencia_de_voz": None,
            "watermark": (
                "NINGUNO: Kokoro no marca el audio como sintético. Lo que lo declara como IA "
                "es la declaración de contenido de IA de la subida (flag Art. 50), que por eso deja de "
                "tener red de seguridad técnica y NO es opcional."
            ),
        }
    for entry, item in zip(result.get("items", []), pending, strict=False):
        audio_path = Path(entry["file"])
        # `audio_segundos` del registro es la duración que midió el generador, ANTES del
        # post-proceso del perfil: quien necesite la duración final la lee del archivo
        # (`lib/medios.get_audio_duration`, con ffprobe).
        filters = _apply_post_processing(audio_path, context["post_proceso"])
        record = {
            "file": str(audio_path),
            "tipo": "audio",
            "motor": job["motor"],
            "paquete": modelo["paquete"],
            "licencia": modelo.get("licencia", "desconocida"),
            # La URL de los pesos la declara la receta (`modelo.url`) y llega a `assets.json` (OC1.4).
            "url": modelo.get("url"),
            "origen": f"generado en local con {job['motor']} en .venv-voz (sin red, coste 0 €)",
            "perfil_tonal": context["perfil"],
            "receta": VOICE_RECIPE_PATH.name,
            "parametros": job["parametros"],
            "seed": job["seed"],
            **identidad,
            "segmentacion": {
                "frases": entry["segmentos"],
                "max_palabras_por_frase": context["max_palabras"],
                "silencio_ms": context["silencio_ms"],
                "recorte_bordes": job.get("recorte_bordes"),
            },
            "texto": item["texto"],
            "sample_rate": result.get("sample_rate"),
            "audio_segundos": entry["audio_seconds"],
            "segundos": entry["seconds"],
            "rtf": entry["rtf"],
            "post_proceso_ffmpeg": filters,
            # Lo que el worker mide del motor que divaga y que hasta el 12-09 se PERDIA aqui: los
            # tres campos existian en su resultado y ninguno llegaba al assets.json. Sin ellos la
            # procedencia no podia decir que un segmento se corto por silencio, ni cuantos reintentos
            # costo, ni cuanto audio inventado se tiro — y eso es lo que la revision final necesita
            # leer para saber que escuchar. `.get` porque un resultado rescatado de un worker viejo
            # puede no traerlos.
            "reintentos_por_ritmo_implausible": entry.get("reintentos_por_ritmo_implausible", []),
            "recortes_por_divagacion": entry.get("recortes_por_divagacion", []),
            "incidencias_no_bloqueantes": entry.get("incidencias_no_bloqueantes", []),
        }
        records.append(record)
        _GENERATION_RECORDS.append(record)
        print(f"  Saved: {audio_path} ({entry['audio_seconds']}s de audio, rtf {entry['rtf']})", flush=True)

    _dump_records(out_dir, records)
    return records


def revisa_etiquetas_emocionales(texto: str, permitidas: list[str], procedencia: str) -> list[str]:
    """Para el run si el guion trae una marca entre ángulos que el canal no ha declarado.

    Devuelve las etiquetas encontradas y admitidas, para que quien llame pueda registrarlas.

    **Por qué existe, medido y no supuesto.** El 08-09 se midieron cuatro etiquetas sobre Orpheus
    Q8_0 con seis semillas cada una y una etiqueta inventada como control negativo. `<groan>` mete
    una vocalización con tono en 4 de 6 pasadas; `<gasp>` no hace nada en 6 de 6; y `<blorp>`, que
    el modelo no ha visto nunca, produce sonido en 6 de 6, mete una palabra ajena al guion en 5 de 6
    y **se lee en voz alta** en 4 de 6: «Blurp!», «Boar!», «Blahp!», «Blurp,».

    **Las tres cifras no son la misma medida y por eso van separadas.** «Sonido» sale de
    `huecos.json → resumen.<variante>.con_sonido`; «palabra ajena» de comparar la transcripción con
    el guion, y ese criterio tiene **suelo de ruido propio** —da 1 de 6 en `<gasp>` y 2 de 6 en
    `<sigh>` solo por errores del reconocedor, «media» por «medieval» o «IM» por «iron»—, así que lo
    que decide es el 4 de 6 en que la palabra ES la etiqueta.

    Así que el modo de fallo no es que la etiqueta se ignore —eso sería inocuo—, es que **el
    narrador la pronuncia**, y eso llega al vídeo publicado sin que ninguna guarda lo cace: el
    audio suena perfectamente bien, dura lo que toca y hasta pasa el recorte por transcripción,
    porque la palabra extra va DENTRO del texto pedido y no detrás.

    **Se para en vez de limpiar la etiqueta por nuestra cuenta.** Borrarla sería decidir por el
    canal que esa emoción no importaba, y dejarla pasar sería publicar una palabra inventada. Lo
    que hay es una errata en el guion, y el guion es del gate 1: lo arregla una persona.
    """
    encontradas = [m.group(1) for m in _ETIQUETA_EN_TEXTO.finditer(texto)]
    if not encontradas:
        return []
    # **La comparación distingue mayúsculas a propósito.** `<GASP>` no son los mismos tokens que
    # `<gasp>`, así que el motor no tiene por qué convertirla en sonido — y si no la convierte, la
    # dice. Aceptarla por parecerse sería colar justo el fallo que esto existe para cazar.
    validas = {e.strip() for e in permitidas}
    intrusas = sorted(set(encontradas) - validas)
    if intrusas:
        lista = ", ".join(f"<{e}>" for e in intrusas)
        admitidas = ", ".join(f"<{e}>" for e in sorted(validas)) or "ninguna"
        raise VoiceError(
            f"El texto de {procedencia} trae {lista}, que la receta de voz "
            f"({VOICE_RECIPE_PATH.name}) no declara en 'etiquetas_emocionales.permitidas' "
            f"(admitidas: {admitidas}). **El motor no ignora lo que no reconoce: lo PRONUNCIA** "
            "—medido el 08-09 con seis semillas: una etiqueta inventada sale LEÍDA en voz alta en "
            "4 de 6 pasadas y mete algún sonido en 6 de 6—, así que esto acabaría en el vídeo como "
            "una palabra que nadie escribió. Arregla el guion, o añade la etiqueta a la receta si "
            "de verdad la quieres (y mídela antes: declarar una que el motor no convierta en "
            "sonido es justo lo que hace que se lea)."
        )
    return sorted(set(encontradas))


# --------------------------------------------------------------------------------------
# Contrato público — idéntico al del cliente de pago que sustituye
# --------------------------------------------------------------------------------------


def generate_tts_batch(items: list[dict], output_dir: str, voice: str = "", *, profile: str | None = None) -> list[str]:
    """Locuta el lote EN SERIE. Cada dict: {text, filename}; `voice` nombra el perfil tonal.

    Salta los archivos ya generados (reanudación: un guion largo son minutos de GPU) y
    devuelve las rutas **en el orden de entrada**, porque las etapas del pipeline emparejan
    por índice con `slides.json`.
    """
    recipe = load_recipe()
    profile_id = resolve_profile(recipe, voice=voice, profile=profile)
    resolved = resolve_recipe(recipe, profile_id)

    segmentation = resolved["segmentacion"]
    max_words = int(_require(segmentation, "max_palabras_por_frase", "segmentacion"))
    silence_ms = int(_require(segmentation, "silencio_entre_frases_ms", "segmentacion"))
    # La clave tiene que ESTAR, y **0 significa «frase a frase»**: el canal tiene que DECIR si
    # agrupa o no, porque suena distinto y es una decisión suya. Lo que no puede es callarse y
    # heredar la de otro canal (F4.9). Se comprueba la presencia en vez de usar `_require` porque
    # ese rechaza los valores falsos, y aquí el 0 es una respuesta legítima, no un hueco.
    if "agrupa_hasta_palabras" not in segmentation:
        raise VoiceError(
            f"La receta de voz ({VOICE_RECIPE_PATH.name}) no declara 'agrupa_hasta_palabras' en "
            "segmentacion. Es el techo de palabras con el que se juntan frases seguidas en una "
            "sola llamada al motor: **0 = frase a frase**, y un número agrupa hasta "
            "ahí (21 en un canal, medido contra la muestra aprobada). No tiene defecto porque "
            "cambia cómo suena la voz del canal."
        )
    agrupa = segmentation["agrupa_hasta_palabras"]
    agrupa_hasta = int(agrupa) if agrupa else None
    # Igual que la anterior: la clave tiene que ESTAR y `null` significa «este canal no ensancha las
    # pausas». Cambia cómo suena la narración, así que es del canal y no tiene defecto (F4.9).
    if "respiracion" not in segmentation:
        raise VoiceError(
            f"La receta de voz ({VOICE_RECIPE_PATH.name}) no declara 'respiracion' en segmentacion. "
            "Es cuánto aire se mete en las pausas que el motor ya deja dentro del habla, sin tocar "
            "la velocidad de las palabras: `null` para no ensanchar nada, o "
            '`{"umbral_db": -38, "pausa_desde_ms": 300, "pausa_minima_ms": 550, "pausa_maxima_ms": 1500, '
            '"factor": 1.6, "fundido_ms": 150}`. No tiene '
            "defecto "
            "porque un canal para escuchar y uno para leer no respiran igual."
        )
    respiracion = segmentation["respiracion"]
    if "colas" not in segmentation:
        raise VoiceError(
            f"La receta de voz ({VOICE_RECIPE_PATH.name}) no declara 'colas' en segmentacion. "
            "Es lo que el motor genera cuando ya no le queda texto —suena flojo, dura mucho y no "
            "dice nada—: `null` para no quitarlas, o "
            '`{"techo_db": -18, "minimo_ms": 300, "rampa_ms": 25}`. No tiene defecto porque '
            "depende de cuanto silencio deje el motor del canal."
        )
    if "recorte_por_texto" not in segmentation:
        raise VoiceError(
            f"La receta de voz ({VOICE_RECIPE_PATH.name}) no declara 'recorte_por_texto' en "
            "segmentacion. Es lo que corta lo que el motor dice DESPUES de acabar el texto: se "
            "transcribe el segmento, se emparejan sus palabras con las pedidas y se corta al final "
            "de la ultima. `null` cuando el motor no divaga (Kokoro), o "
            '`{"modelo": "openai/whisper-small", "margen_s": 0.15}` cuando si (Orpheus). No tiene '
            "defecto porque cortar por transcripcion en un motor que no lo necesita solo anade el "
            "riesgo de comerse el final de una palabra."
        )
    recorte_por_texto = segmentation["recorte_por_texto"]
    if recorte_por_texto:
        for clave in ("modelo", "margen_s"):
            if clave not in recorte_por_texto:
                raise VoiceError(f"'recorte_por_texto' de la receta no declara '{clave}'.")
    if respiracion:
        for clave in (
            "umbral_db",
            "pausa_desde_ms",
            "pausa_minima_ms",
            "pausa_maxima_ms",
            "factor",
            "fundido_ms",
        ):
            if clave not in respiracion:
                raise VoiceError(f"'respiracion' de la receta no declara '{clave}'.")

    # **Antes de gastar un segundo de GPU**: si el guion trae una marca entre ángulos que este canal
    # no ha declarado, el motor la diría en voz alta dentro del vídeo. Se revisa TODO el lote, no
    # solo lo pendiente, porque un wav ya cacheado se montaría igual con la palabra intrusa dentro.
    permitidas = recipe["etiquetas_emocionales"]["permitidas"]
    for item in items:
        revisa_etiquetas_emocionales(item["text"], permitidas, item.get("filename") or "un item del lote")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = [str(out_dir / item["filename"]) for item in items]

    pending = []
    for item in items:
        out_path = out_dir / item["filename"]
        # **El wav ya hecho solo se salta si NO hay crudo del que rehacerlo.** Saltarlo teniendo
        # crudo salía carísimo y en silencio: la limpieza por marcas corre después, sobre los wav de
        # la carpeta, así que una segunda pasada de la etapa **limpiaba un audio ya limpio** y
        # devolvía cifras que no eran las del filtro (medido el 06-09: 29 tramos sobre limpio contra
        # 37 sobre el post-proceso recién hecho). Con crudo, rehacerlo cuesta ~1,3 s y la etapa pasa
        # a ser reproducible: el mismo run dos veces da el mismo audio.
        # La ruta la fija `voice_worker._sintetiza` (`out.parent.parent / "crudo" / out.name`), y se
        # repite aquí porque el worker **no puede importar nada del repo**: corre en `.venv-voz`, que
        # no tiene `python-dotenv`. Si allí cambia, cambia aquí.
        # **Y si alguien borra `crudo/` para recuperar disco, vuelve el defecto**: el wav se salta,
        # la limpieza corre otra vez sobre audio ya limpio y las cifras dejan de ser las del filtro.
        # `crudo/` vive bajo `videos/`, que va ignorado en git y es lo primero que se poda, así que
        # queda dicho aquí: lo que se poda es el RUN entero, no la caché de dentro.
        crudo = out_dir.parent / "crudo" / out_path.name
        hay_crudo = crudo.exists() and crudo.with_suffix(".json").exists()
        if out_path.exists() and out_path.stat().st_size > 0 and not hay_crudo:
            print(f"  Skipping {item['filename']} (already exists)", flush=True)
            continue
        pending.append(
            {
                "salida": str(out_path),
                # El mínimo por llamada lo pone el MOTOR (5 con Orpheus, fila 127), no la receta.
                "segmentos": split_narration(
                    item["text"], max_words, agrupa_hasta, min_words=min_palabras_por_llamada(recipe["motor"])
                ),
                "texto": " ".join(item["text"].split()),
            }
        )
    if not pending:
        return results

    motor = recipe["motor"]
    modelo = resolved["modelo"]
    job = {
        "motor": motor,
        "parametros": resolved["parametros"],
        "seed": _require(resolved, "seed", "la receta resuelta"),
        "silencio_entre_frases_ms": silence_ms,
        # Opcional y sin valor por defecto propio: si la receta no lo declara, no se recorta.
        "recorte_bordes": segmentation.get("recorte_bordes"),
        "respiracion": respiracion,
        "colas": segmentation["colas"],
        "recorte_por_texto": recorte_por_texto,
        "items": [{"salida": p["salida"], "segmentos": p["segmentos"]} for p in pending],
    }

    # Lo único que separa a los motores: de dónde sale la voz. Kokoro la trae de su catálogo;
    # Orpheus la clona de un clip que prepara el mecanismo del estudio (antes lo hacía Chatterbox,
    # con el mismo bloque de receta).
    reference_meta = None
    if motor == "orpheus":
        spec_ref = resolved["referencia_de_voz"]
        reference, reference_meta = prepare_reference(spec_ref)
        job["referencia"] = str(reference)
        # **El texto del clip lo declara la receta y no se deduce.** Orpheus clona con un EJEMPLO
        # (texto + audio): necesita saber qué dice el trozo EXACTO que se le pasa, y ese trozo es
        # una ventana de la referencia —`opcion_activa`, con su offset y su duración—, no el texto
        # entero. Recortar el texto «en proporción» al audio, que es lo que hacía la prueba, parte
        # palabras por la mitad; aquí la ventana cae en frontera de frase y su texto va escrito.
        opcion = _require(spec_ref, "opcion_activa", "referencia_de_voz")
        job["referencia_texto"] = _require(
            spec_ref[opcion], "texto", f"referencia_de_voz.{opcion} (lo exige el motor orpheus)"
        )
        # **`device` ya no se le pide a la receta, y eso es el cierre de la fila 119.** Con
        # `transformers` era el `.to("cuda")` del canal; con llama.cpp las capas que van a la
        # tarjeta las decide el servidor, que lo arranca el ESTUDIO. Un canal declara su voz
        # semilla, su velocidad, su idioma y el texto de su referencia — no elige runtime.
        #
        # `repo_id` y `decodificador` SÍ siguen viniendo de la receta porque son lo que lee la
        # procedencia (decisión 5): identifican qué modelo produjo el audio de un run concreto, y
        # eso tiene que quedar escrito en su `assets.json` aunque el estudio cambie de runtime.
        job["modelo"] = {
            "repo_id": _require(modelo, "repo_id", "modelo"),
            "decodificador": _require(modelo, "decodificador", "modelo"),
            # La URL la arma el estudio y viaja en el job: el worker corre en `.venv-voz` y **no
            # puede importar nada del repo**, así que no puede leerla de `lib/config.py`.
            "servidor": LLAMA_BASE_URL,
            "cuantizacion": Path(LLAMA_MODELO_GGUF).name,
        }
        etiqueta = f"orpheus/clon de {Path(reference).name}"
    elif MOTORES[motor]["necesita_referencia"]:
        reference, reference_meta = prepare_reference(resolved["referencia_de_voz"])
        job["referencia"] = str(reference)
        job["modelo"] = {
            "clase": _require(modelo, "clase", "modelo"),
            "language_id": modelo.get("language_id"),
            "device": _require(modelo, "device", "modelo"),
        }
        etiqueta = job["modelo"]["clase"].rsplit(".", 1)[-1]
    else:
        job["voz"] = resolved["voz"]
        job["modelo"] = {
            "repo_id": _require(modelo, "repo_id", "modelo"),
            "lang_code": _require(modelo, "lang_code", "modelo"),
            "device": _require(modelo, "device", "modelo"),
        }
        etiqueta = f"{motor}/{_require(resolved['voz'], 'id', 'voz')}"

    total_segments = sum(len(p["segmentos"]) for p in pending)
    print(
        f"  Voz local en serie · perfil '{profile_id}' · {etiqueta} "
        f"· {len(pending)} archivo(s), {total_segments} frase(s)"
    )

    context = {
        "job": job,
        "modelo": modelo,
        "perfil": profile_id,
        "referencia": reference_meta,
        "max_palabras": max_words,
        "silencio_ms": silence_ms,
        "post_proceso": resolved.get("post_proceso_ffmpeg"),
    }
    try:
        # El servidor de voz se arranca AQUÍ y no dentro del worker, por la misma razón que
        # ComfyUI: el worker es un subproceso deliberadamente tonto que no conoce el repo, y el
        # ciclo de vida de un proceso que ocupa la tarjeta es del adaptador. Si ya había uno vivo
        # con el modelo correcto se aprovecha y NO se apaga; con otro modelo, se para el run.
        with motor_de_voz_vivo(motor):
            result = _run_worker(job)
    except VoiceError as error:
        # Rescate de procedencia: si el generador murió a media tanda, los audios que ya
        # están en disco se registran igual (F2.4). El fallo se propaga tal cual —no hay
        # reintento automático— pero la etapa no deja wav huérfanos de origen.
        if error.parcial and error.parcial.get("items"):
            rescued = _register_records(error.parcial, pending, out_dir, context)
            print(
                f"  Procedencia rescatada de {len(rescued)} audio(s) generados antes del fallo",
                flush=True,
            )
        raise

    records = _register_records(result, pending, out_dir, context)
    if len(records) != len(pending):
        raise VoiceError(
            f"El generador devolvió {len(records)} audios para {len(pending)} pedidos: el lote está "
            "incompleto. Lo generado queda registrado en la procedencia; repite la etapa para el resto."
        )
    audio_total = round(sum(r["audio_segundos"] for r in records), 1)
    compute_total = round(sum(r["segundos"] for r in records), 1)
    print(
        f"  Total: {audio_total}s de audio en {compute_total}s de GPU (carga {result.get('load_seconds')}s)",
        flush=True,
    )
    return results


def generate_tts(text: str, voice: str = "", output_path: str = "", *, profile: str | None = None) -> str:
    """Locuta un único texto. Misma firma que el cliente de pago, con el perfil tonal opcional."""
    out = Path(output_path)
    generate_tts_batch([{"text": text, "filename": out.name}], str(out.parent), voice, profile=profile)
    return output_path


def revisa_politica_de_idioma(recipe: dict) -> dict:
    """Cruza el idioma de la narración con el motor de voz: decisión cerrada 13.

    Decisión del 25-08 en el estudio: fuera de la lengua de la grabación de referencia, la voz clonada no vale. La
    regla no es una preferencia de sonido, tiene una causa medible: aquella grabación **no contenía una sola palabra en
    inglés**, así que el clonado interpolaba fonemas que nunca oyó. Eso vale igual para cualquier idioma que la
    grabación no contenga, y es lo que hace que la regla sea predictiva y no un gusto. La lengua de la grabación la
    declara la receta (`referencia_de_voz.idioma_de_la_referencia`, OC1.4), no este módulo.

    Esta función existe para que la norma no dependa de que alguien recuerde leerla. Devuelve un
    check del formato de `preflight`, y **no es bloqueante**: es política de producto, no
    licencia ni seguridad, y quien quiera experimentar debe poder — enterándose.
    """
    idioma = NARRATION_LANG.strip().lower()
    motor = recipe["motor"]
    cobertura = KOKORO_IDIOMAS.get(idioma)

    # **La regla 13 mira la CAUSA, no el nombre del motor.** Su motivo escrito es que la grabación
    # de referencia no contiene el idioma que se narra, así que el clonado interpola fonemas que nunca
    # oyó. Si la receta declara que su referencia es nativa en ese idioma —un canal que clona una voz
    # sintética inglesa del catálogo de Kokoro, no a una persona—, esa causa no existe y la regla
    # no aplica (addendum fila 72).
    referencia = recipe.get("referencia_de_voz") or {}
    idioma_referencia = str(referencia.get("idioma_de_la_referencia") or "").strip().lower()
    # **La pregunta es «¿este motor CLONA?», no «¿se llama chatterbox?»**, y la diferencia dejó de
    # ser teórica el 07-09, cuando Orpheus entró como segundo motor de clonado: con el nombre
    # cableado, un canal que clonara con Orpheus se saltaba la decisión 13 en silencio. Quién
    # clona lo dice la tabla de motores, que es donde ya está escrito.
    clona = MOTORES[motor]["necesita_referencia"]
    if clona and not idioma_referencia:
        # `load_recipe` ya para así; esto cubre una receta que llegue sin pasar por ella, y bloquea igual.
        return {
            "nombre": "política de voz por idioma",
            "ok": False,
            "detalle": (
                f"la receta clona con {motor} y no declara `referencia_de_voz.idioma_de_la_referencia`, la lengua "
                "de su grabación de referencia: sin ella la política de voz por idioma no se puede comprobar. "
                'Escríbela, por ejemplo "en"'
            ),
            "obligatorio": True,
        }
    if clona and idioma_referencia == idioma:
        return {
            "nombre": "política de voz por idioma",
            "ok": True,
            "detalle": (
                f"narración en '{idioma}' con voz clonada, y la referencia declara ser nativa en ese "
                f"idioma ({referencia.get('origen', 'origen sin declarar')}). La política de voz por idioma protege "
                "contra clonar una voz en un idioma que su grabación no contiene, y aquí no es el caso"
            ),
            "obligatorio": False,
        }

    if clona:
        return {
            "nombre": "política de voz por idioma",
            "ok": False,
            "detalle": (
                f"el canal narra en '{idioma}' con voz clonada por {motor}, y la referencia de su receta habla "
                f"'{idioma_referencia}'. La política de voz por idioma reserva la voz clonada para la lengua de su "
                f"grabación, porque la grabación no contiene la de la narración: usa una referencia en '{idioma}'"
                + (f" (Kokoro trae {cobertura['voces']} voces en '{idioma}')" if cobertura else "")
            ),
            "obligatorio": False,
        }

    if motor == "kokoro" and cobertura is None:
        return {
            "nombre": "política de voz por idioma",
            "ok": False,
            "detalle": (
                f"el canal narra en '{idioma}' y Kokoro NO trae voces de ese idioma "
                f"(cubre {sorted(KOKORO_IDIOMAS)}). La política de voz por idioma no alcanza aquí: hay que elegir "
                "motor de nuevo"
            ),
            "obligatorio": True,
        }

    detalle = f"narración en '{idioma}' con motor {motor}"
    if motor == "kokoro" and cobertura:
        detalle += f" · {cobertura['voces']} voces disponibles en ese idioma"
        if cobertura["voces"] < 3:
            detalle += " (catálogo corto: poco margen para elegir registro)"
    return {"nombre": "política de voz por idioma", "ok": True, "detalle": detalle, "obligatorio": False}


def revisa_runtime_del_motor(motor: str) -> list[dict]:
    """Comprueba que el RUNTIME del motor está en el disco y sirve el modelo declarado.

    **Por qué hace falta, medido por la auditoría del 08-09.** El preflight de voz comprobaba las
    ENTRADAS del motor —el intérprete de `.venv-voz`, el worker, la receta, la política de idioma, el
    clip de referencia— y **nunca el motor**: un `.venv-voz` sin el modelo pasaba el `--check` en
    verde y el run moría después. Con `llama.cpp` el hueco pasa de incómodo a estructural, porque el
    binario y el GGUF viven **fuera del repo y fuera del venv**, así que ni `requirements` ni el
    árbol del proyecto dicen nada de ellos.

    Los mensajes dicen **qué escribir**, no solo qué falta, que es el estilo de la casa.

    Con Kokoro no comprueba nada: no tiene runtime propio, va dentro del venv.
    """
    if motor != "orpheus":
        return []
    binario, gguf = Path(LLAMA_SERVER), Path(LLAMA_MODELO_GGUF)
    checks = [
        {
            "nombre": "binario de llama.cpp",
            "ok": binario.exists(),
            "detalle": (
                f"{binario}"
                if binario.exists()
                else f"falta {binario}. Es el runtime de Orpheus y "
                "vive fuera del repo como herramienta compartida, igual que ComfyUI. Instálalo con "
                "`py -3.12 instala.py` o pon LLAMA_SERVER=<ruta> en el .env"
            ),
            "obligatorio": True,
        },
        {
            "nombre": "modelo cuantizado",
            "ok": gguf.exists(),
            "detalle": (
                f"{gguf.name}, {gguf.stat().st_size / 2**30:.2f} GB"
                if gguf.exists()
                else f"falta {gguf}. Es el GGUF Q8_0 de Orpheus (~3,3 GB). Descárgalo o pon "
                "LLAMA_MODELO_GGUF=<ruta> en el .env"
            ),
            "obligatorio": True,
        },
        {
            # **El loopback no se comprueba aquí: ya lo asegura `lib/config.py` al importarse.** Se
            # publica para que salga en el `--check` y se vea que la decisión 6 está atada por
            # código y no por convención, que es lo que la auditoría del 08-09 echó en falta.
            "nombre": "el motor de voz solo escucha en local",
            "ok": True,
            "detalle": f"{LLAMA_BASE_URL} — loopback asegurado al importar config",
            "obligatorio": True,
        },
    ]
    # Un servidor VIVO con otro GGUF no es un aviso: es un run que produciría audio y escribiría una
    # procedencia falsa. Se distingue de «no hay servidor», que es lo normal y lo arranca el adaptador.
    servido = _modelo_que_sirve()
    if servido is None:
        detalle, ok = "ninguno vivo: lo arranca el adaptador al locutar", True
    elif Path(servido).name == gguf.name:
        detalle, ok = f"vivo con {gguf.name}: se reutilizará y no se apagará", True
    else:
        detalle, ok = (
            f"hay uno vivo sirviendo {Path(servido).name!r} y la receta produce con {gguf.name!r}: "
            "el run se pararía, porque usar el modelo equivocado dejaría un assets.json que miente. "
            "Apaga ese servidor o ajusta LLAMA_MODELO_GGUF",
            False,
        )
    checks.append({"nombre": "servidor de voz", "ok": ok, "detalle": detalle, "obligatorio": True})
    return checks


def preflight() -> list[dict]:
    """Comprueba que este adaptador podría locutar AHORA, sin generar audio.

    Lo consume `pipeline.py --check` con el mismo contrato que el adaptador de imagen:
    `{nombre, ok, detalle, obligatorio}`. No se imprime la ruta de la grabación de voz,
    solo el nombre de la variable que la declara (lista negra: nada derivado de esa
    grabación se filtra a un log del repo).
    """
    checks: list[dict] = []

    python = Path(VOICE_PYTHON)
    checks.append(
        {
            "nombre": "venv de voz",
            "ok": python.exists() and VOICE_WORKER.exists(),
            "detalle": (
                f"{python} + {VOICE_WORKER.name}"
                if python.exists() and VOICE_WORKER.exists()
                else f"falta el intérprete o el worker (python={python}, worker={VOICE_WORKER}): "
                "ver spikes/requirements-voz.txt"
            ),
            "obligatorio": True,
        }
    )

    try:
        recipe = load_recipe()
    except VoiceError as exc:
        checks.append({"nombre": "receta de voz", "ok": False, "detalle": str(exc), "obligatorio": True})
        return checks

    # El perfil que se comprueba es el que USARÍA el pipeline (PERFIL_VOZ del .env o el
    # neutro por defecto), no el default a secas: cada perfil puede pedir otra grabación.
    profile_id = resolve_profile(recipe)
    checks.append(
        {
            "nombre": "receta de voz",
            "ok": True,
            "detalle": (
                f"{VOICE_RECIPE_PATH.name}: motor {recipe['motor']}, {recipe['modelo'].get('paquete', '?')}, "
                f"perfil '{profile_id}' de {available_profiles(recipe)}"
            ),
            "obligatorio": True,
        }
    )

    checks.append(revisa_politica_de_idioma(recipe))
    checks.extend(revisa_runtime_del_motor(recipe["motor"]))

    if not MOTORES[recipe["motor"]]["necesita_referencia"]:
        # Con un motor de voz nativa no hay grabación que comprobar: lo que se comprueba es
        # que la voz esté declarada. Que este check dijera OK mirando un clip que el motor no
        # usa sería exactamente el fallo de verificar la entrada en vez de lo que se ejecuta.
        voz = resolve_recipe(recipe, profile_id).get("voz") or {}
        componentes = voz.get("componentes") or ([voz["id"]] if voz.get("id") else [])
        checks.append(
            {
                "nombre": "voz declarada",
                "ok": bool(componentes),
                "detalle": (
                    f"{voz.get('id')} = {' + '.join(componentes)}"
                    if componentes
                    else f"la receta no declara 'voz.id' ni 'voz.componentes' para el motor {recipe['motor']}"
                ),
                "obligatorio": True,
            }
        )
        return checks

    try:
        env_name, _ = resolve_recording(resolve_recipe(recipe, profile_id)["referencia_de_voz"])
        detalle = f"declarada en {env_name} y el archivo existe (fuera del repo)"
        ok = True
    except VoiceError as exc:
        detalle = str(exc)
        ok = False
    checks.append({"nombre": "grabación de referencia", "ok": ok, "detalle": detalle, "obligatorio": True})

    return checks


def ajustes_de_limpieza() -> dict | None:
    """Cómo limpia este canal el audio con las marcas del alineador. **Lo declara la receta.**

    `null` es una respuesta: un canal que narre con Kokoro no alucina sonido al quedarse sin texto,
    asi que no tiene colas que callar; un canal lo llevaba activo porque su video se produjo con un motor
    que si las dejaba. Sin defecto en el estudio (F4.9): un canal que herede en silencio el filtro
    de otro se arriesga a que le corten el final de una palabra, que es lo que paso el 06-09 con
    «important».
    """
    receta = load_recipe()
    segmentacion = resolve_recipe(receta, resolve_profile(receta))["segmentacion"]
    if "limpieza_por_marcas" not in segmentacion:
        raise VoiceError(
            f"La receta de voz ({VOICE_RECIPE_PATH.name}) no declara 'limpieza_por_marcas' en "
            "segmentacion. Es lo que calla lo que suena FUERA de las palabras que reconoce el "
            "alineador: `null` para no limpiar, o "
            '`{"modelo_alineacion": "openai/whisper-small", "margen_ms": 120, "techo_db": -18, '
            '"minimo_ms": 250, ...}` con las claves de `limpia_voz.CLAVES_DE_LIMPIEZA`. No tiene '
            "defecto porque depende del motor del canal."
        )
    ajustes = segmentacion["limpieza_por_marcas"]
    if ajustes:
        # La lista vive en `lib/limpia_voz.py`, que es quien sabe qué lee el filtro. Escrita a mano
        # aquí se quedó corta: faltaban `cabeza_minima_ms`, `isla_techo_db` e `isla_minima_ms`, las
        # tres que gobiernan borrado de audio, y este guardián existe justo para eso.
        from lib.limpia_voz import CLAVES_DE_LIMPIEZA

        for clave in CLAVES_DE_LIMPIEZA:
            if clave not in ajustes:
                raise VoiceError(f"'limpieza_por_marcas' de la receta no declara '{clave}'.")
    return ajustes
