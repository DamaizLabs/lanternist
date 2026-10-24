r"""Registro de procedencia por run: `assets.json` (decisión cerrada 5).

Cada asset que el pipeline genera o usa deja una entrada con **fuente, licencia y
URL/origen**, más el **modelo REAL** que lo produjo. No es un paso final: lo escriben las
propias etapas de `pipeline.py` (imágenes, voz, miniatura, montaje) en un `finally`, así
que un run que muere a media etapa deja el registro coherente con lo que sí se generó, no
un archivo a medias ni un run sin procedencia.

Cómo se construye, y por qué así:

- **La fuente son los adaptadores, no este módulo.** `lib/comfy_client.py` deja
  `generacion-imagenes.json` junto a las láminas y `lib/voice_client.py` deja
  `generacion-voz.json` junto al audio; el render del motor de escena deja `montaje.json` junto
  al vídeo (lo dejaba igual el montaje del motor de láminas, retirado en F6.7, cuyos runs se siguen
  auditando). Aquí se **normalizan** esos tres formatos a un esquema único. Reconstruir el
  registro desde los archivos de procedencia (y no desde variables en memoria) es lo que
  permite reanudar un run en otro proceso —el lote de imágenes salta las que ya existen—
  sin perder de dónde salió cada una.
- **Registro veraz.** El PNG publicable va sin metadatos de generación (addendum de doc/02
  fila 7); `assets.json` sigue diciendo el modelo, los pesos, el prompt y la semilla reales.
  Es la defensa ante un reclamo de Content ID y no se falsea: si un asset no puede demostrar
  su origen, el conteo cruzado lo grita en vez de inventarle una procedencia.
- **Sin rutas personales.** Las rutas se guardan relativas al repositorio (o al run) y
  `_scrub_paths` sustituye cualquier cadena que parezca una ruta absoluta. Una grabación de
  voz se identifica por **nombre de variable de entorno y tramo**, jamás por ruta.
- **Los planos con movimiento NO son assets propios.** Un plano de `montaje/` es una
  transformación determinista de una lámina ya registrada (encuadre, zoom, easing), y sus
  parámetros están en `montaje.json`. Registrarlos triplicaría el inventario y diluiría lo
  que importa: el fotograma viene de `slides/slide-07.png`, generada por tal modelo con tal
  prompt. Se cuentan aparte como `intermedios`, para que nada quede silenciosamente ignorado.
- **Copia versionada.** `assets.json` vive junto al vídeo, pero `canales/*/videos/` está en
  `.gitignore` y doc/02 Punto 5 exige que la procedencia llegue a git; el registro se
  espeja en `canales/<canal>/datos/assets/<run_id>.json`, que sí se versiona.

Uso desde una etapa:

    from lib import provenance
    try:
        ...generar los assets...
    finally:
        provenance.sync(run_dir, run_id=run_id, titulo=titulo, etapa="images")

Un asset que no genere el pipeline (imagen de archivo, música con licencia) se registra con
`register_external(...)`: hoy no hay ninguno, pero la decisión 5 pide fuente, licencia y URL
también para ellos, y sin ese hueco la única salida sería falsear el registro o callar.
"""

import contextlib
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from lib.config import (
    ASSETS_MIRROR_DIR,
    BASE_DIR,
    CANAL_ACTIVO,
    DIR_SUBIR_AL_CANAL,
    FPS,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
)

# Versión del esquema del registro. Es uno de los JSON versionados de doc/versionado.md:
# un cambio no aditivo aquí es cambio menor de versión del producto.
SCHEMA = "assets/1.0"

LEDGER_FILENAME = "assets.json"
IMAGE_RECORDS_FILENAME = "generacion-imagenes.json"
VOICE_RECORDS_FILENAME = "generacion-voz.json"
MUSIC_RECORDS_FILENAME = "generacion-musica.json"
SUBTITLE_RECORDS_FILENAME = "generacion-subtitulos.json"
# Las traducciones del `.srt` (F7.11, fila 265): las escribe `lib/traduccion.py` al dejar `subtitulos.<idioma>.srt`. Van
# en su propio fichero y no en el de los subtítulos porque la etapa `alinea` reescribe aquel entero en cada pasada. Si
# una traducción sigue valiendo lo decide la subida, con el sha256 del `.srt` del que salió.
TRANSLATION_RECORDS_FILENAME = "traduccion-subtitulos.json"
# Los efectos y las fuentes de la biblioteca del estudio que usa un episodio del motor de escena (F6.2d): los
# escribe `lib/escena/audio.py` al copiarlos al run, con la fuente, la licencia y la url de su `CREDITOS.json`.
LIBRARY_RECORDS_FILENAME = "biblioteca-escena.json"
ASSEMBLY_SUMMARY_FILENAME = "montaje.json"

# Extensiones que cuentan como asset en el conteo cruzado. Lo que no es medio (JSON de
# estado, grafo de FFmpeg, logs) se cuenta como metadato y no necesita procedencia.
MEDIA_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
        ".wav",
        ".mp3",
        ".m4a",
        ".aac",
        ".flac",
        ".ogg",
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
        # El .srt entra aquí aunque sea texto: **se sube a YouTube**, así que es un asset
        # publicado y tiene que responder de dónde salió como cualquier otro (decisión 5).
        ".srt",
        # Las fuentes también (F6.2d): el motor de escena pinta con ellas el texto que sale en el vídeo, y una
        # tipografía tiene licencia como una imagen. Solo las lleva un run del motor de escena, en `biblioteca/`
        # con su registro; la copia que va dentro de la composición es un intermedio (`composicion/`).
        ".woff2",
        ".woff",
        ".ttf",
        ".otf",
    }
)

# Subdirectorios del run que son material de trabajo del montaje, no assets: placas
# supermuestreadas y clips por plano, derivados de láminas ya registradas.
# Directorios de trabajo: lo que hay dentro son intermedios, no assets publicables, y se
# cuentan aparte para que nada quede silenciosamente ignorado. `musica/` guarda los tramos
# de ACE-Step y el vídeo previo a la mezcla; el lecho final vive fuera, con su procedencia.
# `subtitulos/` guarda el ASS y el vídeo previo al quemado, por el mismo motivo que `musica/`:
# son pasos reversibles del mismo vídeo ya registrado, no assets publicables. El `.srt` sí vive
# fuera, porque ese se sube y por tanto tiene que responder de dónde salió — desde el 10-09 está
# en `subir-al-canal/` con el vídeo y la miniatura, que es la carpeta de lo publicable y por eso
# NO entra en esta lista.
# **La marca del canal NO añade nada aquí, y es deliberado.** F4.0 metió `trabajo/` en esta lista y
# la auditoría lo revirtió: dentro estaban `banner-base.png` y `avatar-base.png`, que son **la salida
# del modelo** y el único sitio donde viven el prompt, la semilla y los pesos. Declararlos
# intermedios los sacó del registro versionado y dejó el canal **no reproducible**. Ahora esa
# carpeta se llama `material/` y cuenta como cualquier otro asset, igual que `slides/` en un run.
# `onda/` guarda el montaje previo a dibujar la onda de ecualizador (F4.11), por el mismo
# motivo que los dos de arriba. Faltar aquí no era cosmético y lo midió la revisión de F4.11:
# el `.mp4` que aparta la etapa contaba como **asset sin procedencia**, así que `conteo.cuadra`
# se quedaba en `false` en el `assets.json` del run **y en la copia que entra en git**. Un
# guardián que grita en cada montaje es un guardián apagado.
# `crudo/` guarda lo que sale del motor de voz ANTES del post-proceso, para no repetir diez minutos
# de GPU cuando solo cambia un umbral (06-09). Es un intermedio por la misma razón que los otros: el
# asset publicable es el wav final, que sí lleva su `generacion-voz.json` con motor, semilla y
# parámetros — el crudo es un paso reversible del mismo audio ya registrado.
# `activos-trabajo/` es del motor de escena (F6.2c): los lienzos de croma lisos que se le pasan a Qwen como lienzo,
# los trabajos y los logs del obrero. Un lienzo liso no es un asset: es un color de fondo de un tamaño, que el
# registro de la imagen generada ya nombra («lienzo: croma 1664x928»). Lo que SÍ tiene procedencia vive en
# `activos/` (lo que genera Qwen, los lienzos de referencia y los recortes), que por eso no está en esta lista.
# Y tres más del motor de escena (F6.2d), los tres hechos de COPIAS o de derivados deterministas de assets que ya
# tienen su entrada:
# - `composicion/`: la composición de HyperFrames (`index.html` y sus `assets/`, copiados de `activos/img/`,
#   `biblioteca/` y `sonido/`), igual que los planos de `montaje/` lo son de las láminas. Desde F6.8 lleva además
#   `assets/estudio/campo-*.png`, los campos de las transiciones de tinta, que dibuja el código y no son copias
#   (`lib/escena/campos.py`, deterministas, sin modelo);
# - `sonido/`: la narración con sus pausas (los wav de `audio/`, uno detrás de otro con silencios), el lecho ya
#   apartado bajo la voz (`lecho.wav`, con su registro) y el vídeo antes de normalizar su sonoridad;
# - `revision/`: las páginas de las dos paradas del usuario y los fotogramas de `snapshot`, que son para mirar.
# `biblioteca/` NO está: guarda la copia de los efectos y las fuentes del estudio que usa el episodio, y esos sí
# responden de dónde salen, con su registro (`biblioteca-escena.json`).
WORK_DIRS = frozenset(
    {
        "montaje",
        "musica",
        "onda",
        "subtitulos",
        "crudo",
        "limpieza",
        "activos-trabajo",
        "composicion",
        "sonido",
        "revision",
    }
)

# Marca de las entradas que no vienen de un adaptador: las escribe `register_external` y
# `sync` las conserva porque no hay archivo de procedencia del que reconstruirlas.
MANUAL_REGISTRO = "manual"
ADAPTER_REGISTRO = "adaptador"

# Licencias que aún no están cerradas. No bloquean el run (el riesgo de licencias no
# comerciales se asumió por escrito, addendum fila 7) pero se listan en cada conteo.
PENDING_LICENSE_HINTS = ("desconocida", "por verificar", "pendiente", "sin determinar")

POLICY_NOTE = (
    "Procedencia: fuente, licencia y URL/origen de cada asset, integrado en las etapas. "
    "El archivo publicable va sin metadatos de generación; este "
    "registro sí declara el modelo real y no se falsea. Los planos con movimiento son "
    "transformaciones de las láminas (parámetros en montaje.json), no assets propios."
)

# Orden estable de las entradas: hace legible el diff de la copia versionada
_TYPE_ORDER = {
    "imagen": 0,
    "miniatura": 1,
    "audio": 2,
    "video": 3,
    "externo": 4,
    "musica": 5,
    "subtitulos": 6,
    "sonido": 7,
    "fuente": 8,
}

# Cadenas que parecen una ruta absoluta (unidad de Windows, UNC o raíz POSIX)
_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/[^/])")
_OMITTED = "<ruta local omitida>"

_ffmpeg_version_cache = ""


class ProvenanceError(RuntimeError):
    """El registro de procedencia no cuadra con los assets del run."""


# --------------------------------------------------------------------------------------
# Rutas: relativas y sin nombres de usuario
# --------------------------------------------------------------------------------------


def _reanchor(run_dir: Path, path: Path) -> Path | None:
    """Reancla al run una ruta anotada cuando el run estaba en otro sitio, o None si no cuela.

    Prueba las colas de `path` de la más larga a la más corta contra `run_dir` y devuelve la
    primera que existe. La más larga primero porque es la más específica: si un run tiene
    `slides/slide-01.png` y `audio/slide-01.png`, la cola de dos tramos distingue y la de uno no.

    Existe por la reorganización del 30-08: los adaptadores anotaron rutas ABSOLUTAS bajo el
    antiguo `outputs/<run_id>/` de la raíz, y esos archivos de procedencia son la única fuente
    de la que
    `sync` reconstruye `assets.json` (decisión cerrada 5). Medido anulando esta función y
    re-auditando: el run de cierre del Sprint 2 daba `conteo.sin_archivo = 16` de sus
    `conteo.archivos_medios = 22`, y los cuatro runs daban `cuadra: false` — cuatro runs declarados
    impublicables por haber cambiado de carpeta. Sirve igual para la migración a `C:` que
    `CLAUDE.md` deja decidida y diferida.
    """
    partes = path.parts
    for inicio in range(1, len(partes)):
        candidato = run_dir.joinpath(*partes[inicio:])
        if candidato.exists():
            return candidato
    # Y por último, en la carpeta de lo publicable: desde el 10-09 el vídeo, la miniatura y el `.srt`
    # se escriben en `subir-al-canal/` en vez de en la raíz del run (decisión del 10-09), así que un
    # registro anotado antes —o un `montaje.json` que guardó `final.mp4` a secas— apunta a la raíz y
    # sus colas no existen. Sin esto, mover esos tres archivos declara el run impublicable: es el
    # mismo fallo que la reorganización del 30-08, medido entonces en `conteo.sin_archivo = 16`.
    en_publicables = run_dir / DIR_SUBIR_AL_CANAL / path.name
    return en_publicables if en_publicables.exists() else None


def _resolve(run_dir: Path, value: str) -> Path:
    """Ruta absoluta del asset a partir de lo que anotó el adaptador.

    Los adaptadores anotan rutas absolutas, pero `montaje.json` guarda la salida tal como la
    recibió, que puede ser relativa **al repositorio** (así la pasa la prueba de movimiento) o
    al run. Se prueban las dos y gana la que existe, en vez de dar por buena una convención.

    Y si ninguna existe, se reancla al run antes de rendirse: lo anotado puede apuntar a donde
    el run estaba cuando se produjo. Solo se acepta lo que existe, así que esto no inventa
    procedencia: o encuentra el archivo, o el conteo cruzado sigue gritando igual que antes.
    """
    path = Path(value)
    candidatos = (path,) if path.is_absolute() else (run_dir / path, BASE_DIR / path)
    for candidate in candidatos:
        if candidate.exists():
            return candidate
    reanclada = _reanchor(run_dir, path)
    if reanclada is not None:
        return reanclada
    return candidatos[0] if path.is_absolute() else run_dir / path


def asset_id(run_dir: Path, path: Path) -> str:
    """Identidad del asset dentro del run: su ruta relativa al directorio del run.

    Es la clave del registro y la del conteo cruzado, así que no puede depender de dónde
    esté el repositorio ni de quién ejecute el pipeline.
    """
    with contextlib.suppress(ValueError):
        return path.resolve().relative_to(run_dir.resolve()).as_posix()
    return path.name


def _display_path(run_dir: Path, path: Path) -> str:
    """Ruta legible para el registro: relativa al repositorio si está dentro; nunca absoluta."""
    resolved = path.resolve()
    with contextlib.suppress(ValueError):
        return resolved.relative_to(BASE_DIR).as_posix()
    with contextlib.suppress(ValueError):
        return resolved.relative_to(run_dir.resolve()).as_posix()
    return path.name


def _scrub_paths(value):
    """Sustituye recursivamente cualquier cadena con pinta de ruta absoluta.

    Cinturón y tirantes sobre los adaptadores: hoy ninguno anota la ruta de una grabación de
    voz (la identifican por variable de entorno y tramo), pero `assets.json` se copia a git
    y una ruta con el nombre de usuario dentro no aporta nada y sí filtra la máquina.
    """
    if isinstance(value, str):
        return _OMITTED if _ABSOLUTE_PATH.match(value) else value
    if isinstance(value, dict):
        return {key: _scrub_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub_paths(item) for item in value]
    return value


# --------------------------------------------------------------------------------------
# Normalización de los registros de los adaptadores
# --------------------------------------------------------------------------------------


def _read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Un registro de procedencia truncado (proceso muerto mientras escribía) no puede
        # tumbar el run: se avisa y el conteo cruzado dejará el asset como sin registrar.
        print(f"  [ASSETS] Aviso: {path.name} está corrupto y se ignora ({path})", flush=True)
        return None


def _stat(path: Path) -> dict:
    if not path.exists():
        return {"existe": False, "bytes": None}
    return {"existe": True, "bytes": path.stat().st_size}


def _base_entry(run_dir: Path, path: Path, tipo: str, etapa: str) -> dict:
    return {
        "id": asset_id(run_dir, path),
        "tipo": tipo,
        "etapa": etapa,
        "ruta": _display_path(run_dir, path),
        "registro": ADAPTER_REGISTRO,
        **_stat(path),
    }


def _image_entry(run_dir: Path, record: dict) -> dict:
    """Normaliza un registro de `lib/comfy_client.py` (una lámina o la miniatura)."""
    path = _resolve(run_dir, record.get("file", ""))
    ident = asset_id(run_dir, path)
    thumbnail = "thumbnail" in ident.lower() or "miniatura" in ident.lower()
    detalle = {
        key: value
        for key, value in record.items()
        if key not in ("file", "fuente", "modelo", "licencia", "origen", "url")
    }
    entry = _base_entry(run_dir, path, "miniatura" if thumbnail else "imagen", "thumbnail" if thumbnail else "images")
    entry.update(
        {
            # La fuente la puede declarar el registro, y el defecto sigue siendo ComfyUI. Hace falta
            # porque no toda imagen del estudio sale del modelo: los assets de marca (F4.0) incluyen
            # DERIVADOS —el banner reescalado con su texto, el avatar a 150, la marca de agua con
            # alfa— que produce Pillow a partir de una imagen que sí generó ComfyUI. Con la cadena
            # fija, `assets.json` atribuía al modelo un archivo que el modelo no escribió, que es
            # justo el fallo que F2.16 dejó documentado con la voz.
            "fuente": record.get("fuente") or "generación local (ComfyUI en 127.0.0.1, sin servicios de pago)",
            "modelo": record.get("modelo") or "desconocido",
            "licencia": record.get("licencia") or "desconocida",
            # La URL la declara el registro desde F6.2c: los activos del motor de escena dicen de dónde salen los
            # pesos del modelo que los generó y de las herramientas que los tocaron (decisión 5: fuente, licencia y
            # URL de cada asset). Un registro que no la trae sigue dando None, como hasta ahora.
            "url": record.get("url") or None,
            "origen": record.get("origen") or "generado en local con ComfyUI",
            "detalle": _scrub_paths(detalle),
        }
    )
    return entry


# Procedencia por motor de voz, DERIVADA del registro y no escrita a mano. La version anterior
# tenia la cadena de Chatterbox fija, y al cambiar el motor en F2.16 quedo un assets.json que
# atribuia los audios a Chatterbox y afirmaba «voz clonada del operador» cuando el run habia usado
# Kokoro y la voz clonada NO se usa. Lo destapo el primer `--run-all` de una pasada, el 27-08: los
# campos `modelo` y `origen` del registro estaban bien porque se derivan; el unico que fallo es el
# que estaba teclado. Es el mismo patron que la convencion del proyecto ya tenia medido para los
# informes — lo que se regenera sobrevive, lo que se copia se podre — y aqui importa mas, porque
# `assets.json` es la defensa documental de la decision 5.
FUENTES_POR_MOTOR_DE_VOZ = {
    "kokoro": "generación local (Kokoro en .venv-voz, voz del catálogo mezclada, sin red)",
    "orpheus": (
        "generación local (Orpheus TTS 3B en .venv-voz, clonando el clip de referencia que genera Kokoro, sin red)"
    ),
    # **`chatterbox` se queda aquí aunque el motor ya no exista** (borrado el 07-09), y no es
    # un descuido: esta tabla la lee `--assets-audit` sobre runs YA producidos, y el vídeo
    # aprobado de un canal tiene ese motor escrito en su registro. Quitar la fila no borraría ese
    # hecho: le pondría al audio una descripción genérica y peor. La procedencia describe lo
    # que pasó, no lo que hoy se puede hacer (decisión 5).
    "chatterbox": "generación local (Chatterbox en .venv-voz, voz clonada del operador)",
}


def _fuente_de_voz(record: dict) -> str:
    """Describe el origen del audio, PREFIRIENDO lo que el propio registro dice de su runtime.

    **Por qué no basta la tabla de arriba, medido por la auditoría del 08-09.** Estaba indexada solo
    por el nombre del motor y describía el runtime **a mano**: decía «Orpheus TTS 3B en .venv-voz»
    cuando Orpheus pasó a correr en `llama.cpp` con un GGUF cuantizado, así que la frase quedó falsa
    en cada wav. Y editar la fila no era el arreglo: esta tabla la lee `--assets-audit` sobre runs
    **ya producidos**, así que reescribirla le cambiaría la historia a un audio que se generó de otra
    forma — exactamente lo que el comentario de la fila `chatterbox` intenta evitar.

    **El arreglo es no describir el runtime desde fuera.** El registro que escribe el adaptador ya
    trae su `paquete` —«llama.cpp (server) + transformers (tokenizador) + snac (decodificador)»— y
    ese dato **viaja con el run**: un run viejo lleva el suyo y uno nuevo el suyo, sin que nadie
    tenga que acordarse de actualizar una tabla. La tabla se queda como respaldo para los registros
    antiguos que no lo llevan.

    Es el mismo principio que la convención de las cifras: lo que se deriva sobrevive, lo que se
    copia se podre. Y aquí importa más, porque `assets.json` es la defensa documental de la
    decisión 5.
    """
    motor = str(record.get("motor") or "").strip().lower()
    paquete = str(record.get("paquete") or "").strip()
    if paquete:
        return f"generación local ({motor or 'motor sin declarar'} sobre {paquete}, sin red)"
    conocida = FUENTES_POR_MOTOR_DE_VOZ.get(motor)
    if conocida:
        return conocida
    # Un motor nuevo no debe heredar la descripcion de otro: se dice lo que se sabe y nada mas
    return f"generación local ({motor or 'motor sin declarar'}, runtime sin declarar, sin red)"


def _audio_entry(run_dir: Path, record: dict) -> dict:
    """Normaliza un registro de `lib/voice_client.py` (una pista de narración)."""
    path = _resolve(run_dir, record.get("file", ""))
    detalle = {
        key: value
        for key, value in record.items()
        if key not in ("file", "tipo", "modelo", "licencia", "url", "origen")
    }
    entry = _base_entry(run_dir, path, "audio", "tts")
    entry.update(
        {
            "fuente": _fuente_de_voz(record),
            "modelo": record.get("modelo") or "desconocido",
            "licencia": record.get("licencia") or "desconocida",
            # La URL de los pesos la declara la receta de voz desde OC1.4; un registro anterior sigue dando None.
            "url": record.get("url") or None,
            "origen": record.get("origen") or f"generado en local con {record.get('motor') or 'motor sin declarar'}",
            "detalle": _scrub_paths(detalle),
        }
    )
    return entry


def _music_entry(run_dir: Path, record: dict) -> dict:
    """Normaliza un registro de `lib/musica.py` (el lecho musical del vídeo).

    Va con `tipo: "musica"` y no `"audio"` a propósito: en el conteo cruzado interesa
    distinguir la narración del lecho, porque son cosas distintas ante una reclamación —
    la voz es del operador y la música es generada.
    """
    path = _resolve(run_dir, record.get("file", ""))
    detalle = {
        key: value
        for key, value in record.items()
        if key not in ("file", "tipo", "modelo", "licencia", "url", "origen")
    }
    entry = _base_entry(run_dir, path, "musica", "assembly")
    entry.update(
        {
            "fuente": "generación local (ACE-Step en ComfyUI); música ORIGINAL, no de biblioteca",
            "modelo": record.get("modelo") or "desconocido",
            "licencia": record.get("licencia") or "desconocida",
            # La del workflow de música desde OC1.4; un registro anterior sigue dando None.
            "url": record.get("url") or None,
            "origen": record.get("origen") or "generado en local con ACE-Step",
            "detalle": _scrub_paths(detalle),
        }
    )
    return entry


def _subtitle_entry(run_dir: Path, record: dict) -> dict:
    """Normaliza el registro de `lib/subtitulos.py`: el `.srt` que se sube con el vídeo.

    Solo produce entrada si hay `.srt`, porque el ASS y el vídeo previo al quemado viven en
    `subtitulos/` y son intermedios (`WORK_DIRS`). El `.srt` en cambio sale del PC, y su
    procedencia tiene una particularidad que conviene que quede escrita: el modelo de
    reconocimiento **solo aportó marcas de tiempo**; el texto es el del guion aprobado en el
    gate 1. Sin esa distinción, el registro daría a entender que el contenido lo escribió un
    modelo.
    """
    path = _resolve(run_dir, record.get("srt") or "")
    detalle = {key: value for key, value in record.items() if key not in ("srt", "licencia", "url", "origen")}
    entry = _base_entry(run_dir, path, "subtitulos", "assembly")
    entry.update(
        {
            "fuente": "texto del guion aprobado (slides.json); del audio solo las marcas de tiempo",
            "modelo": record.get("modelo_alineacion") or "desconocido",
            "licencia": record.get("licencia") or "desconocida",
            # La del alineador desde OC1.4 (`lib/subtitulos.URL_ALINEADOR`); un registro anterior sigue dando None.
            "url": record.get("url") or None,
            "origen": record.get("origen") or "alineación en local, sin red",
            "detalle": _scrub_paths(detalle),
        }
    )
    return entry


def _translation_entry(run_dir: Path, record: dict) -> dict:
    """Normaliza el registro de una traducción del `.srt` (`lib/traduccion.py`, F7.11): otro `.srt` que se sube.

    Su tipo es `subtitulos`, como el de origen. Lo que cambia es de dónde sale el texto: no es el del guion, sino su
    traducción hecha con IA. Por eso la declaración la nombra aparte, y lo sabe por `detalle.traducido_de`. Los tiempos
    son los del `.srt` de origen, sin tocar.
    """
    path = _resolve(run_dir, record.get("file", ""))
    detalle = {key: value for key, value in record.items() if key not in ("file", "traductor", "licencia", "origen")}
    entry = _base_entry(run_dir, path, "subtitulos", "traduccion")
    entry.update(
        {
            "fuente": (
                f"traducción con IA de {record.get('traducido_de') or 'un .srt sin nombrar'}, cue a cue y con sus "
                "mismos tiempos"
            ),
            "modelo": record.get("traductor") or "desconocido",
            "licencia": record.get("licencia") or "desconocida",
            "url": None,
            "origen": record.get("origen") or "sin declarar en su registro",
            "detalle": _scrub_paths(detalle),
        }
    )
    return entry


def _library_entry(run_dir: Path, record: dict) -> dict:
    """Normaliza un registro de la biblioteca del motor de escena: un efecto de sonido o una fuente (F6.2d).

    No los genera ningún modelo: son ficheros de terceros (Pixabay, fuentes OFL) que el estudio guarda en
    `datos/escena/` con su `CREDITOS.json`, y el run lleva la copia que usa. Por eso su modelo es «no aplica», que
    es también lo que deja fuera de la declaración de IA a un efecto o a una tipografía.

    La etapa es la del registro si la dice (OC1.4: la fuente de la miniatura la copia `thumbnail`, y la del banner,
    `marca`), y si no, `escena`, que es quien copia la biblioteca de un episodio.
    """
    path = _resolve(run_dir, record.get("file", ""))
    tipo = record.get("tipo") or "externo"
    detalle = {
        key: value
        for key, value in record.items()
        if key not in ("file", "tipo", "fuente", "licencia", "url", "origen", "etapa")
    }
    entry = _base_entry(run_dir, path, tipo, record.get("etapa") or "escena")
    entry.update(
        {
            "fuente": record.get("fuente") or "desconocida",
            "modelo": "no aplica (biblioteca del estudio, no lo genera ningún modelo)",
            "licencia": record.get("licencia") or "desconocida",
            "url": record.get("url") or None,
            "origen": record.get("origen") or "copiado de la biblioteca del estudio",
            "detalle": _scrub_paths(detalle),
        }
    )
    return entry


def ffmpeg_version() -> str:
    """Versión de FFmpeg con la que se montó el vídeo (parte de su procedencia)."""
    global _ffmpeg_version_cache
    if _ffmpeg_version_cache:
        return _ffmpeg_version_cache
    _ffmpeg_version_cache = "desconocida"
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=30)
        first = (result.stdout or "").splitlines()[:1]
        if first and first[0].startswith("ffmpeg version"):
            _ffmpeg_version_cache = first[0].split()[2]
    return _ffmpeg_version_cache


def _video_entry(run_dir: Path, summary: dict, sources: list[str]) -> dict:
    """Normaliza el resumen del montaje (`montaje.json`): el vídeo final es un DERIVADO.

    No lleva modelo generativo, así que su licencia es la de sus assets de origen, que van citados en
    `derivado_de`. Cómo se hizo lo dice el motor que lo escribió (`montaje.json → motor`, F6.2d):

    - el de láminas (sin campo `motor`), retirado en F6.7: FFmpeg movía las láminas del run. Sus runs se siguen
      auditando (`--assets-audit`), así que esta rama se queda;
    - el de escena (`lib/escena/etapas.py`, `motor: "escena"`): HyperFrames fotografía en Chrome una composición
      HTML que `motor/motor.js` anima como función pura del tiempo, con los activos del run, y FFmpeg la codifica.
      Tampoco hay modelo generativo: los modelos están en los activos, que tienen su propia entrada.
    """
    path = _resolve(run_dir, summary.get("salida", "final.mp4"))
    entry = _base_entry(run_dir, path, "video", "assembly")
    detalle = {
        "resolucion": f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}",
        "fps": FPS,
        "duracion_s": summary.get("duracion_s"),
        "laminas": summary.get("laminas"),
        "planos": summary.get("planos"),
        "laminas_por_minuto": summary.get("laminas_por_minuto"),
        "movimientos": summary.get("movimientos", []),
        "transiciones": summary.get("transiciones", []),
        "cronometraje": summary.get("cronometraje", {}),
        "detalle_por_plano": f"{ASSEMBLY_SUMMARY_FILENAME} (junto al vídeo)",
    }
    if summary.get("motor") == "escena":
        herramientas = summary.get("herramientas") or {}
        # El marco y los fps son los del bloque `escena` del canal, que el render escribe en su resumen.
        detalle.update(
            {
                "motor": "escena",
                "resolucion": summary.get("resolucion"),
                "fps": summary.get("fps"),
                "silencios": summary.get("silencios", {}),
                "herramientas": herramientas,
                # Las figuras que se mueven en la escena; None en un montaje anterior a F6.8, que no lo contaba.
                "actores": summary.get("actores"),
            }
        )
        # El formato del catálogo (F7.11), del que la declaración de IA saca su línea de imagen. Solo si el montaje lo
        # dice: el registro de un run anterior se queda como estaba, byte a byte, al volver a sincronizarlo.
        if summary.get("formato"):
            detalle["formato"] = summary["formato"]
        fuente = "derivado de los assets de este run (render local del motor de escena, sin red)"
        modelo = (
            "ninguno: render determinista con HyperFrames "
            f"{herramientas.get('hyperframes') or 'de versión sin declarar'} en Chrome con WebGPU "
            f"{herramientas.get('chrome') or '(sin declarar)'} y FFmpeg {ffmpeg_version()} (sin modelo generativo)"
        )
        origen = (
            "motor de escena: composición HTML animada por motor/motor.js sobre los activos, la narración, la música "
            "y los efectos del run, fotografiada fotograma a fotograma"
        )
    else:
        fuente = "derivado de los assets de este run (montaje local con FFmpeg)"
        modelo = f"ninguno: montaje determinista con FFmpeg {ffmpeg_version()} (sin modelo generativo)"
        origen = "montaje local: planos Ken Burns/parálaje y transiciones sobre las láminas del run"
    licencia = "heredada de los assets de origen (ver derivado_de)"
    url = None
    # La marca de IA (OC1.5): Video Seal y AudioSeal tocan los píxeles y el sonido, así que el registro los nombra, con
    # su licencia y su url (decisión 5). Marcan y no generan: el modelo sigue empezando por «ninguno», y la declaración
    # de IA de la subida no los cuenta como IA generativa. Un montaje sin marca (anterior a OC1.5) queda como estaba.
    marca = summary.get("marca_ia")
    if isinstance(marca, dict):
        modelos = list((marca.get("modelos") or {}).values())
        nombres = " y ".join(dict.fromkeys(m.get("nombre", "").split(",")[0] for m in modelos))
        modelo += f"; marca de agua con {nombres} (MIT), que marcan el contenido y no lo generan"
        licencia += " · marca de agua: " + ", ".join(f"{m.get('nombre')} ({m.get('licencia')})" for m in modelos)
        url = " · ".join(dict.fromkeys(m.get("fuente") for m in modelos if m.get("fuente"))) or None
        detalle["marca_ia"] = marca
    entry.update(
        {
            "fuente": fuente,
            "modelo": modelo,
            "licencia": licencia,
            "url": url,
            "origen": origen,
            "derivado_de": sources,
            "detalle": detalle,
        }
    )
    return entry


def _sidecars(run_dir: Path, filename: str) -> list[Path]:
    """Archivos de procedencia del run, saltando el material de trabajo del montaje."""
    found = []
    for path in sorted(run_dir.rglob(filename)):
        relative = path.relative_to(run_dir).parts
        if relative and relative[0] in WORK_DIRS:
            continue
        found.append(path)
    return found


def lee_registro_o_aparta(path: Path) -> list[dict]:
    """Lo que ya hay en un registro de procedencia; si es ilegible, se APARTA en vez de perderse.

    **Por qué no se sobrescribe (auditoría del 10-09, ALTO).** En los adaptadores, un registro que no
    parseaba se trataba como vacío y la siguiente entrada lo reescribía: un corte a media escritura —el
    proceso muere, el disco se llena, un Ctrl+C— borraba en silencio la procedencia de todas las láminas
    anteriores. Y estos ficheros son la ÚNICA fuente desde la que `sync()` reconstruye `assets.json`
    (decisión 5), así que lo perdido solo se recupera regenerando las imágenes o los audios.

    El fichero roto se renombra a `<nombre>.roto-<sello>` y se avisa por consola: la etapa sigue —parar
    dejaría el run a medias con la GPU ya gastada— pero la evidencia queda en disco y `sync()` dirá
    `cuadra: false` nombrando lo que falta, que es la señal para revisarlo.

    **Vive aquí y no en cada adaptador** porque los dos que lo necesitan —`comfy_client` y
    `voice_client`— la tenían byte a byte idéntica, con su docstring incluido, y el auditor del 10-09 lo
    llamó por su nombre: es el mismo «arreglo aplicado a dos hermanos» que acababa de cazar la auditoría.
    Este módulo ya es el dueño del concepto de procedencia y publica los nombres de esos ficheros.
    """
    if not path.exists():
        return []
    try:
        cargado = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        motivo = type(exc).__name__
    else:
        if isinstance(cargado, list):
            return cargado
        motivo = f"contiene un {type(cargado).__name__} y no una lista"
    # Sello al segundo MÁS un contador: `Path.replace` sobrescribe en Windows, así que dos apartados en
    # el mismo segundo se pisarían y el segundo perdería lo que venía a salvar (auditor del 10-09).
    sello = time.strftime("%Y%m%d_%H%M%S")
    apartado = path.with_name(f"{path.name}.roto-{sello}")
    intento = 2
    while apartado.exists():
        apartado = path.with_name(f"{path.name}.roto-{sello}-{intento}")
        intento += 1
    path.replace(apartado)
    print(
        f"  [PROCEDENCIA] OJO: {path.name} no se puede leer ({motivo}). Se aparta como {apartado.name} y se "
        "empieza uno nuevo: la procedencia anterior NO se pierde, pero hay que recuperarla a mano "
        "antes de dar el run por bueno (`pipeline.py --assets-audit`).",
        flush=True,
    )
    return []


def anade_registros(ruta: Path, nuevos: list[dict]) -> None:
    """Añade registros al final de un fichero de procedencia (`ruta`); lo que no se lee se aparta, no se pisa.

    **La única puerta de escritura de los registros de procedencia** (auditoría de F6.2c, recomendación 1): la
    tenían repetida línea a línea `comfy_client`, `voice_client` y `lib/escena/obrero.py`, y los activos llamaban
    a la privada de `comfy_client` desde otro módulo. Todos pasan por aquí; la lectura que aparta un registro roto
    es `lee_registro_o_aparta`, justo debajo del mismo concepto.
    """
    if not nuevos:
        return
    ruta = Path(ruta)
    existentes = lee_registro_o_aparta(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(existentes + list(nuevos), indent=2, ensure_ascii=False), encoding="utf-8")


def quita_registros(ruta: Path, ficheros) -> int:
    """Quita de un fichero de procedencia los registros de esos ficheros (por su nombre). Devuelve cuántos quitó.

    Es la otra mitad de `anade_registros`, para quien BORRA los ficheros que registró: la separación de una pizarra que
    se rehace con otros ajustes (F7.10) deja otras piezas, y las viejas salen del disco. Sin esto sus registros
    seguirían prometiendo un asset que ya no está, y el conteo diría que el run no cuadra. Lo que no se lee se aparta,
    como al añadir.
    """
    nombres = {Path(str(f)).name for f in ficheros}
    ruta = Path(ruta)
    if not nombres or not ruta.exists():
        return 0
    existentes = lee_registro_o_aparta(ruta)
    quedan = [r for r in existentes if Path(str(r.get("file", ""))).name not in nombres]
    if len(quedan) != len(existentes):
        ruta.write_text(json.dumps(quedan, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(existentes) - len(quedan)


def _registros(sidecar: Path) -> list[dict]:
    """Los registros de un archivo de procedencia, o ninguno con aviso si no tiene la forma esperada.

    `_read_json` ya avisa de un JSON corrupto, pero uno **válido con otra forma** —un objeto en vez de
    una lista, que es lo que deja una edición a mano— llegaba a `_image_entry` como una cadena y
    reventaba con `AttributeError` (auditoría del 10-09, MEDIO). El registro que no cuadra se ignora y
    el conteo de `sync` lo delata: `cuadra: false` nombrando el asset sin registrar.
    """
    cargado = _read_json(sidecar)
    if cargado is None:
        return []
    if not isinstance(cargado, list) or not all(isinstance(r, dict) for r in cargado):
        print(f"Aviso: {sidecar.name} no es una lista de registros y se ignora (procedencia sin reconstruir)")
        return []
    return cargado


def entries_from_adapters(run_dir: Path) -> list[dict]:
    """Reconstruye las entradas del registro desde los archivos de procedencia del run."""
    run_dir = Path(run_dir)
    entries: list[dict] = []

    for sidecar in _sidecars(run_dir, IMAGE_RECORDS_FILENAME):
        for record in _registros(sidecar):
            entries.append(_image_entry(run_dir, record))
    for sidecar in _sidecars(run_dir, VOICE_RECORDS_FILENAME):
        for record in _registros(sidecar):
            entries.append(_audio_entry(run_dir, record))
    for sidecar in _sidecars(run_dir, MUSIC_RECORDS_FILENAME):
        for record in _registros(sidecar):
            entries.append(_music_entry(run_dir, record))
    for sidecar in _sidecars(run_dir, SUBTITLE_RECORDS_FILENAME):
        for record in _registros(sidecar):
            if record.get("srt"):  # sin .srt no hay asset publicable: el resto es intermedio
                entries.append(_subtitle_entry(run_dir, record))
    for sidecar in _sidecars(run_dir, TRANSLATION_RECORDS_FILENAME):
        for record in _registros(sidecar):
            entries.append(_translation_entry(run_dir, record))
    for sidecar in _sidecars(run_dir, LIBRARY_RECORDS_FILENAME):
        for record in _registros(sidecar):
            entries.append(_library_entry(run_dir, record))

    # El vídeo va al final: cita como origen las entradas de imagen y audio ya normalizadas (y, en el motor de
    # escena, los efectos y las fuentes de la biblioteca, que también están dentro del vídeo)
    summary = _read_json(run_dir / ASSEMBLY_SUMMARY_FILENAME)
    if isinstance(summary, dict) and summary.get("salida"):
        dentro = ("imagen", "audio", "musica", "sonido", "fuente")
        sources = sorted({entry["id"] for entry in entries if entry["tipo"] in dentro})
        entries.append(_video_entry(run_dir, summary, sources))
    return entries


def _deduplicate(entries: list[dict]) -> list[dict]:
    """Una entrada por asset: gana la última, que es la del archivo que está en disco.

    Los adaptadores **añaden** a su archivo de procedencia, así que regenerar una lámina
    borrada deja dos registros del mismo `id`; el bueno es el último.
    """
    latest: dict[str, dict] = {}
    for entry in entries:
        latest[entry["id"]] = entry
    return sorted(latest.values(), key=lambda item: (_TYPE_ORDER.get(item["tipo"], 9), item["id"]))


# --------------------------------------------------------------------------------------
# Conteo cruzado contra el directorio del run
# --------------------------------------------------------------------------------------


def _license_pending(entry: dict) -> bool:
    """¿La licencia de este asset está sin cerrar?

    Se compara con el **principio** del valor, no con el texto entero: la casilla de licencia
    de un workflow lleva su justificación detrás («Apache-2.0 … la razón por la que el run de
    F2.1 lo dejó como "por verificar"…»), y buscar la coletilla en cualquier posición marcaba
    como pendientes licencias que sí están cerradas.
    """
    licencia = str(entry.get("licencia", "")).strip().lower()
    return not licencia or licencia.startswith(PENDING_LICENSE_HINTS)


def audit(run_dir, entries: list[dict]) -> dict:
    """Compara los medios que hay en el run con las entradas del registro.

    Mira las dos direcciones, porque las dos son fallos:
    un archivo sin procedencia (no se puede defender de dónde salió) y una entrada sin
    archivo (el registro promete un asset que ya no está).
    """
    run_path = Path(run_dir)
    media: dict[str, int] = {}
    intermedios = 0
    metadatos = 0

    for path in sorted(run_path.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(run_path)
        if relative.parts[0] in WORK_DIRS:
            intermedios += 1
            continue
        if path.suffix.lower() in MEDIA_SUFFIXES:
            media[relative.as_posix()] = path.stat().st_size
        else:
            metadatos += 1

    registered = {entry["id"] for entry in entries}
    sin_registrar = sorted(set(media) - registered)
    sin_archivo = sorted(registered - set(media))
    por_tipo: dict[str, int] = {}
    for entry in entries:
        por_tipo[entry["tipo"]] = por_tipo.get(entry["tipo"], 0) + 1

    return {
        "cuadra": not sin_registrar and not sin_archivo,
        "archivos_medios": len(media),
        "entradas": len(entries),
        "por_tipo": dict(sorted(por_tipo.items())),
        "sin_registrar": sin_registrar,
        "sin_archivo": sin_archivo,
        "licencias_por_cerrar": sorted(entry["id"] for entry in entries if _license_pending(entry)),
        "intermedios_de_montaje": intermedios,
        "archivos_no_medios": metadatos,
        "auditado": datetime.now().isoformat(timespec="seconds"),
    }


def format_report(report: dict, etapa: str = "") -> str:
    """Texto del conteo cruzado: una línea si cuadra, un bloque visible si no."""
    where = f" tras la etapa '{etapa}'" if etapa else ""
    detalle = ", ".join(f"{count} {tipo}" for tipo, count in report["por_tipo"].items()) or "ninguno"
    # Se nombran las dos cifras en vez de imprimir «8/7»: cuando no cuadran, cuál es cuál es
    # justo el dato que hace falta para saber qué ha pasado.
    resumen = (
        f"[ASSETS]{where}: {report['archivos_medios']} archivo(s) de medios · {report['entradas']} con procedencia "
        f"({detalle}) · {report['intermedios_de_montaje']} intermedios de montaje"
    )
    if report["cuadra"]:
        pendientes = report["licencias_por_cerrar"]
        if pendientes:
            resumen += f"\n[ASSETS] Licencias por cerrar en {len(pendientes)} asset(s): {', '.join(pendientes[:6])}"
        return resumen

    lines = [
        "=" * 78,
        f"⚠  PROCEDENCIA INCOMPLETA — assets.json no cuadra con los archivos del run{where}",
    ]
    if report["sin_registrar"]:
        lines += [
            f"   Archivos SIN procedencia ({len(report['sin_registrar'])}): {', '.join(report['sin_registrar'][:10])}",
            "     → bórralos y repite su etapa (el adaptador los regenera con su registro), o",
            "       declara su origen con provenance.register_external() si vienen de fuera.",
        ]
    if report["sin_archivo"]:
        lines += [
            f"   Entradas SIN archivo ({len(report['sin_archivo'])}): {', '.join(report['sin_archivo'][:10])}",
            "     → falta un asset que el registro promete: repite la etapa que lo produce.",
        ]
    lines += [
        "   Un asset que no puede demostrar de dónde salió no se publica.",
        "=" * 78,
    ]
    return f"{resumen}\n" + "\n".join(lines)


# --------------------------------------------------------------------------------------
# El registro en disco
# --------------------------------------------------------------------------------------


def ledger_path(run_dir) -> Path:
    return Path(run_dir) / LEDGER_FILENAME


def read_ledger(run_dir) -> dict:
    """Registro actual del run, o el esqueleto vacío si aún no hay ninguno."""
    data = _read_json(ledger_path(run_dir))
    if isinstance(data, dict) and isinstance(data.get("assets"), list):
        return data
    return {"esquema": SCHEMA, "assets": []}


def _write_json(path: Path, data: dict) -> None:
    """Escritura atómica: un run interrumpido no puede dejar un `assets.json` inválido."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporal = path.with_suffix(path.suffix + ".tmp")
    temporal.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporal.replace(path)


def _espejo_cuadraba(run_id: str) -> bool:
    """¿La copia versionada del run cuadraba la última vez que se escribió?"""
    espejo = _read_json(ASSETS_MIRROR_DIR / f"{run_id}.json")
    return isinstance(espejo, dict) and (espejo.get("conteo") or {}).get("cuadra") is True


def _mirror(run_id: str, ledger: dict) -> Path:
    """Copia versionada: `canales/*/videos/` está en .gitignore y doc/02 Punto 5 pide git."""
    path = ASSETS_MIRROR_DIR / f"{run_id}.json"
    _write_json(path, ledger)
    return path


def sync(run_dir, *, run_id: str = "", titulo: str = "", etapa: str = "", verbose: bool = True) -> dict:
    """Reescribe `assets.json` desde los archivos de procedencia y hace el conteo cruzado.

    Es idempotente y no depende del proceso que generó los assets, así que vale como paso
    de etapa y como reparación posterior. Devuelve el informe del conteo; el aviso visible
    del descuadre lo imprime aquí mismo, que es donde se ve.
    """
    run_path = Path(run_dir)
    ledger = read_ledger(run_path)
    manual = [entry for entry in ledger.get("assets", []) if entry.get("registro") == MANUAL_REGISTRO]
    entries = _deduplicate([*manual, *entries_from_adapters(run_path)])
    report = audit(run_path, entries)

    ledger.update(
        {
            "esquema": SCHEMA,
            "run_id": run_id or ledger.get("run_id") or run_path.name,
            # Canal del estudio que produjo el run: la procedencia sin canal no sirve
            # cuando el estudio aloja varios (F2.11).
            "canal": CANAL_ACTIVO or ledger.get("canal", ""),
            "titulo": titulo or ledger.get("titulo", ""),
            "actualizado": datetime.now().isoformat(timespec="seconds"),
            "politica": POLICY_NOTE,
            "conteo": report,
            "assets": entries,
        }
    )
    # El registro del run se escribe SIEMPRE: es lo que leen la subida (`require_complete`) y la lista de la marca
    # (`lib/canal_marca.py`), y tiene que decir la verdad aunque el run se haya quedado sin medios.
    _write_json(ledger_path(run_path), ledger)
    # La copia versionada solo se escribe cuando quien llama identifica el run (lo hacen las
    # etapas de `pipeline.py`): auditar a mano un directorio de spike no debe ensuciar git.
    #
    # Y NO se sustituye una copia que cuadraba cuando el run no tiene ni un medio en disco: es lo que deja
    # `scripts/archiva_run.py` al llevarse los medios a D:, y la copia de git es la prueba de que en su día
    # cuadró (deuda de la auditoría del commit del 10-09, fila 224). Si falta solo una parte, la pérdida es
    # real y se escribe.
    conserva_espejo = bool(run_id) and report["archivos_medios"] == 0 and bool(entries) and _espejo_cuadraba(run_id)
    if run_id and not conserva_espejo:
        _mirror(run_id, ledger)
    if verbose:
        print(format_report(report, etapa), flush=True)
        if conserva_espejo:
            print(
                "[procedencia] el run no tiene ningún medio en disco (¿archivado en D:?): su copia versionada, "
                "que cuadraba, no se sustituye",
                flush=True,
            )
    return report


def register_external(
    run_dir,
    ruta,
    *,
    fuente: str,
    licencia: str,
    url: str,
    autor: str = "",
    notas: str = "",
    tipo: str = "externo",
    run_id: str = "",
    modelo: str = "",
    sync_now: bool = True,
) -> dict:
    """Declara un asset que NO ha generado el pipeline (imagen de archivo, música…).

    Hoy no hay ninguno —todo se genera en local— pero la decisión 5 exige fuente, licencia y
    URL también para lo de fuera, y sin este hueco la única salida sería callar. La entrada
    queda marcada como `manual` y `sync` la conserva: no hay adaptador del que reconstruirla.
    """
    run_path = Path(run_dir)
    path = _resolve(run_path, str(ruta))
    if not path.exists():
        raise ProvenanceError(f"No existe el asset que se quiere registrar: {_display_path(run_path, path)}")
    if not (fuente and licencia and url):
        raise ProvenanceError(
            "Un asset externo necesita fuente, licencia y URL: es lo que pide su procedencia (assets.json)"
        )

    ledger = read_ledger(run_path)
    entry = {
        "id": asset_id(run_path, path),
        "tipo": tipo,
        "etapa": "externo",
        "ruta": _display_path(run_path, path),
        "registro": MANUAL_REGISTRO,
        **_stat(path),
        "fuente": fuente,
        # «Externo» no siempre significa «de archivo»: el clip de cinemagraph lo generamos
        # NOSOTROS con un modelo conocido, solo que en otra maquina (Kaggle, addendum fila 21).
        # Decir «no aplica» perderia justo el dato del que depende la licencia, asi que el
        # modelo se puede declarar y solo se cae al literal cuando de verdad no hay ninguno.
        "modelo": modelo or "no aplica (asset externo, no generado por el pipeline)",
        "licencia": licencia,
        "url": url,
        "origen": f"descargado de {url}" + (f" · autor: {autor}" if autor else ""),
        "detalle": {"autor": autor, "notas": notas, "registrado": datetime.now().isoformat(timespec="seconds")},
    }
    ledger["assets"] = [item for item in ledger.get("assets", []) if item.get("id") != entry["id"]] + [entry]
    _write_json(ledger_path(run_path), ledger)
    # El run_id se hereda del registro si no lo dan: así la copia versionada no se queda
    # atrás respecto al `assets.json` del run cuando se declara un asset externo a mano.
    #
    # `sync_now=False` existe por un fallo real de F2.17: al declarar DOS clips seguidos, el
    # sync del primero veía el segundo ya en disco y sin declarar, y escupía el aviso de
    # «PROCEDENCIA INCOMPLETA — no se publica» para corregirse una línea después. Un aviso
    # grave que aparece y se desvanece enseña a ignorar los avisos graves, que es peor que no
    # tenerlos. Quien registre en lote pasa `sync_now=False` y llama a `sync` al final.
    if sync_now:
        sync(run_path, run_id=run_id or str(ledger.get("run_id") or ""), verbose=True)
    return entry


def require_complete(run_dir, *, run_id: str = "", titulo: str = "") -> dict:
    """Exige un registro que cuadre. La usa la subida: publicar sin procedencia es el fallo.

    Decisión cerrada 5: si un error de licencia no se detecta antes de publicar, se replica
    a volumen. Aquí es donde el registro tiene dientes.
    """
    report = sync(run_dir, run_id=run_id, titulo=titulo, etapa="publicación")
    if not report["cuadra"]:
        raise ProvenanceError(
            "El registro de procedencia no cuadra con los archivos del run: no se sube nada "
            f"(sin procedencia: {report['sin_registrar']} · sin archivo: {report['sin_archivo']}). "
            "Un asset que no puede demostrar de dónde salió no se publica."
        )
    return report
