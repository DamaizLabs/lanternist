"""Adaptador de imagen local sobre ComfyUI — sustituye al cliente de imagen de pago del fork.

Expone **el mismo contrato** que aquel cliente (`generate_images_batch`,
`generate_thumbnail`, `generate_image`) porque el pipeline no conoce modelos
(decisión cerrada 10). Todo el trabajo ocurre en `127.0.0.1`: nada sale del PC
(decisiones 4 y 6).

Invariantes que este módulo hace cumplir por código, no por confianza:

- **Servidor compartido**: `lib/config.py → COMFY_ROOT` puede ser una instalación compartida con
  otros proyectos del usuario. `comfy_server()` arranca el servidor **solo si no hay ninguno vivo** y lo
  apaga **solo si fue él quien lo arrancó** (`ensure_server`/`_shutdown`).
- **Solo nodos locales**: cada workflow se valida contra `ALLOWED_NODES`, una lista
  blanca explícita. Los *API nodes* de pago de ComfyUI (`comfy_api_nodes`: ByteDance,
  Minimax/Hailuo, Krea, Ideogram Cloud…) están registrados en el servidor y quedan
  **prohibidos**: cualquier clase fuera de la lista aborta el lote.
- **Generación EN SERIE**: un prompt en vuelo cada vez y `batch_size == 1` obligatorio
  en el grafo (invariante de los 8 GB de la 3060 Ti).
- **Metadatos limpios en el archivo publicable** (addendum de doc/02 fila 7): el PNG se
  reescribe sin el bloque de generación de ComfyUI. El modelo REAL no se falsea: queda
  en `generation_records()` y en `generacion-imagenes.json` junto a las imágenes, que
  es lo que consumirá `assets.json` (F2.4).

Los grafos viven en `workflows/<id>.json`, versionados en git y parametrizados: ver
`workflows/README.md` para el formato y la lista blanca de nodos de terceros.
"""

import contextlib
import hashlib
import io
import json
import subprocess
import time
from pathlib import Path

import requests
from PIL import Image

from lib import provenance
from lib.config import (
    COMFY_BASE_URL,
    COMFY_HOST,
    COMFY_IMAGE_TIMEOUT,
    COMFY_OUTPUT_SUBFOLDER,
    COMFY_POLL_INTERVAL,
    COMFY_PORT,
    COMFY_PYTHON,
    COMFY_RESERVA_VRAM_GB,
    COMFY_ROOT,
    COMFY_STARTUP_TIMEOUT,
    IMAGE_GEN_HEIGHT,
    IMAGE_GEN_WIDTH,
    IMAGE_SEED,
    LOGS_DIR,
    MODELO_IMAGEN,
    THUMBNAIL_HEIGHT,
    THUMBNAIL_WIDTH,
    WORKFLOWS_DIR,
    entorno_para_terceros,
)

# Lista blanca de clases de nodo. Los nodos base de ComfyUI 0.33.0 que usan nuestros
# workflows, más los de terceros de `workflows/README.md` (ComfyUI-GGUF, commit fijado).
# Ampliarla es una decisión consciente: un nodo nuevo aquí es un nodo nuevo auditado.
ALLOWED_NODES = frozenset(
    {
        # Solo los nodos que usa algún workflow vivo de `workflows/` o un grafo que se lanza en LOCAL desde
        # código; los grafos de Kaggle no pasaron nunca por aquí (se retiraron en F6.7). El 01-10-2026 salieron
        # 14 que solo pedían los workflows retirados de Flux, Flux 2, Ideogram y SDXL (fila 223), y 4 más
        # con `wan-i2v-lamina` (fila 226): un nodo permitido que nada usa es superficie abierta sin motivo.
        # Carga de pesos locales
        "CheckpointLoaderSimple",
        "CLIPLoader",
        "VAELoader",
        "LoraLoaderModelOnly",
        # Terceros: city96/ComfyUI-GGUF @ 6ea2651 (ver workflows/README.md)
        "UnetLoaderGGUF",
        # Condicionado
        "CLIPTextEncode",
        "ConditioningZeroOut",
        # Edición por instrucción con Qwen-Image-Edit (fila 147). Es de ComfyUI core y NO es un API
        # node de pago: verificado por grep sobre la instalación compartida — vive en
        # `comfy_extras/nodes_qwen.py`, el módulo no contiene ni una llamada de red, y no aparece en
        # `comfy_api_nodes/`, que es donde están los de pago. Lo pide `workflows/qwen-edit-tinta.json`,
        # que es la única vía que funciona cuando el modelo no conoce la pieza. **Estaba fuera desde
        # el 11-09**, así que las dos veces que se aplicó esa regla hubo que hacerlo a mano.
        "TextEncodeQwenImageEditPlus",
        # Latentes
        "EmptySD3LatentImage",
        "VAEEncode",
        # Muestreo
        "KSampler",
        "ModelSamplingAuraFlow",
        # Salida y utilidades de imagen
        "VAEDecode",
        "SaveImage",
        "LoadImage",
        "ImageScale",
        # --- Audio: ACE-Step para el lecho musical (F2.12) -------------------------
        # Los siete son de ComfyUI core (`comfy_extras`), NINGUNO es API node de pago:
        # auditados uno a uno contra la plantilla oficial
        # `audio_ace_step_1_t2a_instrumentals.json` de la instalación compartida.
        # La generación de música es local y original, que es lo que evita el Content ID
        # que una pista Creative Commons de biblioteca sí puede arrastrar.
        "TextEncodeAceStepAudio",
        "EmptyAceStepLatentAudio",
        "ModelSamplingSD3",
        "LatentOperationTonemapReinhard",
        "LatentApplyOperationCFG",
        "VAEDecodeAudio",
        "SaveAudioMP3",
        # Sin nodos de vídeo desde el 01-10-2026: salieron con `wan-i2v-lamina` (fila 226). Si vuelven, ojo: el
        # catálogo de plantillas de vídeo de este ComfyUI está DOMINADO por servicios de pago —doce plantillas
        # de i2v llevan prefijo `api_` (ByteDance, Kling, Luma, Google, BFL…)—, todas fuera por las decisiones
        # cerradas 4 y 6, y MiniMax/Hailuo prohibido por nombre en el addendum fila 9.
    }
)

# Registro en memoria del modelo REAL de cada imagen generada en el proceso.
# Es la fuente de `assets.json` (decisión cerrada 5): se limpian los metadatos del
# PNG publicable, nunca la procedencia interna.
_GENERATION_RECORDS: list[dict] = []
_RECORDS_FILENAME = "generacion-imagenes.json"


class ComfyError(RuntimeError):
    """Fallo del runtime de imagen (arranque, validación del grafo o ejecución)."""


# --------------------------------------------------------------------------------------
# Workflows: carga, validación e inyección de parámetros
# --------------------------------------------------------------------------------------


def workflow_path(style: str) -> Path:
    return WORKFLOWS_DIR / f"{style}.json"


def available_styles() -> list[str]:
    return sorted(p.stem for p in WORKFLOWS_DIR.glob("*.json"))


def load_workflow(style: str) -> dict:
    """Lee `workflows/<style>.json` y valida el grafo antes de devolverlo."""
    path = workflow_path(style)
    if not path.exists():
        raise ComfyError(f"Workflow '{style}' no existe en {WORKFLOWS_DIR} (disponibles: {available_styles()})")
    workflow = json.loads(path.read_text(encoding="utf-8"))
    for key in ("id", "modelo", "grafo", "inyeccion", "nodo_salida"):
        if key not in workflow:
            raise ComfyError(f"Workflow '{style}' incompleto: falta la clave '{key}'")
    _validate_nodes(workflow)
    _validate_serial(workflow)
    return workflow


def _validate_nodes(workflow: dict) -> None:
    """Prohíbe cualquier clase de nodo fuera de la lista blanca (API nodes de pago incluidos)."""
    used = {node.get("class_type", "?") for node in workflow["grafo"].values()}
    forbidden = sorted(used - ALLOWED_NODES)
    if forbidden:
        raise ComfyError(
            f"Workflow '{workflow['id']}' usa nodos fuera de la lista blanca: {forbidden}. "
            "Los API nodes de pago de ComfyUI están prohibidos (decisiones cerradas 4 y 6); "
            "un nodo local nuevo se añade a ALLOWED_NODES y a workflows/README.md tras auditarlo."
        )


def _validate_serial(workflow: dict) -> None:
    """La 3060 Ti tiene 8 GB: los lotes se generan en serie, nunca en paralelo en GPU."""
    for node_id, node in workflow["grafo"].items():
        batch = node.get("inputs", {}).get("batch_size")
        if isinstance(batch, int) and batch != 1:
            raise ComfyError(
                f"Workflow '{workflow['id']}' nodo {node_id}: batch_size={batch}. "
                "La generación es EN SERIE (invariante de 8 GB de VRAM)."
            )


def _set_input(graph: dict, target: str, value) -> None:
    """Escribe `value` en el input apuntado por «<id_nodo>:<input>»."""
    node_id, _, input_name = target.partition(":")
    if node_id not in graph:
        raise ComfyError(f"Punto de inyección '{target}': el nodo {node_id} no existe en el grafo")
    graph[node_id].setdefault("inputs", {})[input_name] = value


def build_prompt_graph(
    workflow: dict,
    prompt: str,
    *,
    width: int = IMAGE_GEN_WIDTH,
    height: int = IMAGE_GEN_HEIGHT,
    seed: int = IMAGE_SEED,
    filename_prefix: str = "img",
    overrides: dict | None = None,
) -> dict:
    """Copia el grafo del workflow e inyecta prompt, tamaño, seed y parámetros extra.

    `inyeccion` mapea cada parámetro lógico a uno o varios inputs concretos, así que el
    adaptador no necesita conocer la topología de cada modelo.
    """
    graph = json.loads(json.dumps(workflow["grafo"]))  # copia profunda: el original no se toca
    params = dict(workflow.get("parametros", {}))
    params.update(overrides or {})
    values = {
        "prompt": _compose_prompt(workflow, prompt),
        "prompt_negativo": params.get("prompt_negativo", workflow.get("prompt_negativo", "")),
        "width": width,
        "height": height,
        "seed": int(seed),
        "steps": params.get("steps"),
        "cfg": params.get("cfg"),
        "shift": params.get("shift"),
        "denoise": params.get("denoise"),
    }
    # Todo lo que el workflow declare en `parametros` es inyectable si además tiene punto de
    # inyección. Antes esta tabla era CERRADA, así que un parámetro propio de un modelo nuevo
    # —`segundos` y `letra` del lecho musical de ACE-Step— se quedaba **muerto sin avisar**: el
    # grafo usaba el valor escrito a mano en el JSON y la procedencia registraba el de
    # `parametros`, contradiciéndose consigo misma. Los explícitos de arriba siguen ganando.
    for clave, valor in params.items():
        values.setdefault(clave, valor)

    sin_valor = []
    for logical, target in workflow["inyeccion"].items():
        if logical not in values or values[logical] is None:
            sin_valor.append(logical)
            continue
        targets = target if isinstance(target, list) else [target]
        for t in targets:
            _set_input(graph, t, values[logical])
    if sin_valor:
        # Un punto de inyección declarado que no recibe valor es config que miente: quien lo
        # edite no verá efecto ni error. Se falla en vez de seguir en silencio.
        raise ComfyError(
            f"Workflow '{workflow['id']}': los puntos de inyección {sorted(sin_valor)} no tienen "
            "valor. Declara el parámetro en `parametros`, pásalo en `overrides`, o retíralo de "
            "`inyeccion` — lo que no puede quedar es un punto de inyección inerte."
        )
    _set_input(
        graph,
        f"{workflow['nodo_salida']}:filename_prefix",
        f"{COMFY_OUTPUT_SUBFOLDER}/{filename_prefix}",
    )
    return graph


def _compose_prompt(workflow: dict, prompt: str) -> str:
    """Antepone el prefijo de estilo del workflow, si lo declara."""
    prefix = (workflow.get("prefijo_estilo") or "").strip()
    if not prefix:
        return prompt
    return f"{prefix} {prompt}".strip()


# --------------------------------------------------------------------------------------
# Ciclo de vida del servidor compartido
# --------------------------------------------------------------------------------------


def server_is_alive(timeout: float = 3.0) -> bool:
    try:
        resp = requests.get(f"{COMFY_BASE_URL}/system_stats", timeout=timeout)
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


def server_stats() -> dict:
    resp = requests.get(f"{COMFY_BASE_URL}/system_stats", timeout=10)
    resp.raise_for_status()
    return resp.json()


def _spawn_server() -> subprocess.Popen:
    """Arranca ComfyUI headless en la instalación compartida, sin abrir navegador."""
    python = Path(COMFY_PYTHON)
    main = COMFY_ROOT / "main.py"
    if not python.exists() or not main.exists():
        raise ComfyError(
            f"No encuentro la instalación de ComfyUI (python={python}, main={main}). "
            "Revisa COMFY_ROOT / COMFY_PYTHON en el .env."
        )
    cmd = [
        str(python),
        str(main),
        "--listen",
        COMFY_HOST,
        "--port",
        str(COMFY_PORT),
        "--disable-auto-launch",
        # Doble red del addendum fila 7: el servidor tampoco escribe el grafo en el PNG.
        # No basta por sí solo (si el servidor ya estaba vivo no lo controlamos), así que
        # el adaptador limpia además los metadatos en cliente.
        "--disable-metadata",
    ]
    # Sin esta reserva, ComfyUI descarga parcialmente el modelo GGUF para hacer sitio al VAE y el
    # proceso MUERE con un access violation en la primera lámina (medido el 07-09-2026; el porqué
    # completo, en el comentario de COMFY_RESERVA_VRAM_GB). Reservar el hueco del VAE por
    # adelantado evita esa descarga. A 0 se omite el flag, para una tarjeta que no lo necesite.
    if COMFY_RESERVA_VRAM_GB > 0:
        cmd += ["--reserve-vram", str(COMFY_RESERVA_VRAM_GB)]
    # El log va a NUESTRO logs/, no al árbol de la instalación de ComfyUI, que puede ser compartida.
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "comfyui-adaptador.log"
    print(f"  ComfyUI no estaba vivo: lo arranca el adaptador (log: {log_path})")
    log = open(log_path, "ab")  # noqa: SIM115 — se cierra al terminar el proceso hijo
    proc = subprocess.Popen(
        cmd,
        cwd=str(COMFY_ROOT),
        stdout=log,
        stderr=subprocess.STDOUT,
        # Sin las credenciales del `.env`: ComfyUI carga nodos de terceros (auditoría del 08-09).
        env=entorno_para_terceros({"PYTHONUNBUFFERED": "1"}),
    )
    proc._estudio_log = log  # type: ignore[attr-defined]
    return proc


def _wait_until_alive(proc: subprocess.Popen) -> None:
    start = time.time()
    while time.time() - start < COMFY_STARTUP_TIMEOUT:
        if proc.poll() is not None:
            raise ComfyError(f"ComfyUI murió al arrancar (código {proc.returncode}); mira su log en {COMFY_ROOT}")
        if server_is_alive():
            print(f"  ComfyUI listo en {round(time.time() - start, 1)}s")
            return
        time.sleep(2)
    raise ComfyError(f"ComfyUI no respondió en {COMFY_STARTUP_TIMEOUT}s")


def _shutdown(proc: subprocess.Popen) -> None:
    """Apaga SOLO el servidor que arrancó este adaptador."""
    print("  Apagando el ComfyUI que arrancó el adaptador")
    proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    log = getattr(proc, "_estudio_log", None)
    if log is not None:
        log.close()


@contextlib.contextmanager
def comfy_server():
    """Garantiza un servidor vivo durante el bloque.

    Cede `True` si lo arrancó este adaptador (y entonces lo apaga al salir) y `False`
    si ya había uno vivo — ese es de otro proyecto del usuario y **no se toca**.
    """
    if server_is_alive():
        print("  ComfyUI ya estaba vivo: instalación compartida, el adaptador no lo apagará")
        yield False
        return
    proc = _spawn_server()
    try:
        _wait_until_alive(proc)
        yield True
    finally:
        _shutdown(proc)


def free_memory() -> None:
    """Pide a ComfyUI que descargue modelos de VRAM (entre modelos distintos del zoo)."""
    with contextlib.suppress(requests.exceptions.RequestException):
        requests.post(
            f"{COMFY_BASE_URL}/free",
            json={"unload_models": True, "free_memory": True},
            timeout=30,
        )


# --------------------------------------------------------------------------------------
# Ejecución de un prompt
# --------------------------------------------------------------------------------------


def sube_imagen(ruta: str | Path) -> str:
    """Sube una imagen al `input/` de ComfyUI, dentro de NUESTRA subcarpeta, y devuelve el nombre para `LoadImage`.

    La usan los grafos de edición (`qwen-edit-lienzo`), que leen su referencia y su lienzo de ahí. Va por la API
    de subida del propio ComfyUI en 127.0.0.1, no copiando a su carpeta: así escribe lo que el servidor admite y
    donde lo admite. El nombre lleva el sha256 corto del contenido, para que dos referencias con el mismo nombre
    de fichero no se pisen. **Lo subido se borra con `borra_subidas`**: la instalación es compartida y se queda
    como estaba.
    """
    ruta = Path(ruta)
    datos = ruta.read_bytes()
    nombre = f"{hashlib.sha256(datos).hexdigest()[:12]}-{ruta.name}"
    resp = requests.post(
        f"{COMFY_BASE_URL}/upload/image",
        files={"image": (nombre, datos, "image/png")},
        data={"subfolder": COMFY_OUTPUT_SUBFOLDER, "type": "input", "overwrite": "true"},
        timeout=60,
    )
    if resp.status_code != 200:
        raise ComfyError(f"ComfyUI rechazó la subida de {ruta.name} ({resp.status_code}): {resp.text[:500]}")
    subida = resp.json()
    return f"{subida['subfolder']}/{subida['name']}" if subida.get("subfolder") else subida["name"]


def borra_subidas(nombres) -> None:
    """Borra de `input/` lo que subió `sube_imagen` (solo en nuestra subcarpeta) y la subcarpeta si queda vacía."""
    carpeta = COMFY_ROOT / "input" / COMFY_OUTPUT_SUBFOLDER
    for nombre in nombres:
        partes = str(nombre).split("/")
        if len(partes) != 2 or partes[0] != COMFY_OUTPUT_SUBFOLDER:
            continue
        with contextlib.suppress(OSError):
            (carpeta / partes[1]).unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        carpeta.rmdir()  # solo si está vacía: si no, lo que quede no es nuestro de esta vuelta


def submit_prompt(graph: dict) -> str:
    resp = requests.post(f"{COMFY_BASE_URL}/prompt", json={"prompt": graph}, timeout=60)
    if resp.status_code != 200:
        raise ComfyError(f"ComfyUI rechazó el grafo ({resp.status_code}): {resp.text[:2000]}")
    return resp.json()["prompt_id"]


def wait_for_prompt(prompt_id: str, timeout: int = COMFY_IMAGE_TIMEOUT) -> dict:
    """Espera a que el prompt termine y devuelve su entrada de historial.

    Sin reintentos: un fallo del runtime local es un dato del zoo-test, no algo que
    se disimule repitiendo la llamada.
    """
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(f"{COMFY_BASE_URL}/history/{prompt_id}", timeout=30)
        resp.raise_for_status()
        history = resp.json()
        entry = history.get(prompt_id)
        if entry:
            status = entry.get("status", {})
            if status.get("status_str") == "error" or (status.get("completed") is False and status.get("messages")):
                raise ComfyError(f"Ejecución fallida ({prompt_id}): {json.dumps(status)[:2000]}")
            if status.get("completed") or entry.get("outputs"):
                return entry
        time.sleep(COMFY_POLL_INTERVAL)
    raise ComfyError(f"El prompt {prompt_id} no terminó en {timeout}s")


def _collect_images(entry: dict, output_node: str) -> list[dict]:
    outputs = entry.get("outputs", {})
    node_output = outputs.get(output_node) or {}
    images = node_output.get("images") or []
    if not images:
        # Algunos grafos renumeran el nodo de salida: se acepta cualquier nodo con imágenes
        for value in outputs.values():
            images = value.get("images") or []
            if images:
                break
    if not images:
        raise ComfyError(f"La ejecución no devolvió imágenes: {json.dumps(outputs)[:1000]}")
    return images


def _download_image(image: dict) -> bytes:
    params = {
        "filename": image["filename"],
        "subfolder": image.get("subfolder", ""),
        "type": image.get("type", "output"),
    }
    resp = requests.get(f"{COMFY_BASE_URL}/view", params=params, timeout=120)
    resp.raise_for_status()
    return resp.content


def _strip_metadata(raw: bytes) -> bytes:
    """Reescribe el PNG sin metadatos de generación (addendum de doc/02 fila 7)."""
    with Image.open(io.BytesIO(raw)) as img:
        clean = Image.frombytes(img.mode, img.size, img.tobytes())
    buffer = io.BytesIO()
    clean.save(buffer, format="PNG")
    return buffer.getvalue()


def _cleanup_server_copy(image: dict) -> None:
    """Borra la copia que ComfyUI dejó en su carpeta output, solo dentro de la nuestra."""
    subfolder = image.get("subfolder", "")
    if subfolder.split("/")[0] != COMFY_OUTPUT_SUBFOLDER:
        return
    candidate = COMFY_ROOT / "output" / subfolder / image["filename"]
    with contextlib.suppress(OSError):
        candidate.unlink(missing_ok=True)


def _record(entry: dict) -> None:
    _GENERATION_RECORDS.append(entry)


def generation_records() -> list[dict]:
    """Procedencia real de las imágenes generadas en este proceso (la consume F2.4)."""
    return list(_GENERATION_RECORDS)


def _dump_records(output_dir: Path, new_entries: list[dict]) -> None:
    """Deja la procedencia en disco junto a las imágenes, para `assets.json` (F2.4).

    La escritura es la de `provenance.anade_registros` desde F6.2d (una sola puerta para los tres adaptadores).
    """
    provenance.anade_registros(Path(output_dir) / _RECORDS_FILENAME, new_entries)


def render(
    workflow: dict,
    prompt: str,
    output_path: str,
    *,
    width: int = IMAGE_GEN_WIDTH,
    height: int = IMAGE_GEN_HEIGHT,
    seed: int = IMAGE_SEED,
    overrides: dict | None = None,
    timeout: int = COMFY_IMAGE_TIMEOUT,
) -> dict:
    """Genera UNA imagen con el servidor ya en marcha y devuelve su registro."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    graph = build_prompt_graph(
        workflow,
        prompt,
        width=width,
        height=height,
        seed=seed,
        filename_prefix=out.stem,
        overrides=overrides,
    )
    started = time.perf_counter()
    prompt_id = submit_prompt(graph)
    entry = wait_for_prompt(prompt_id, timeout=timeout)
    elapsed = round(time.perf_counter() - started, 1)

    image = _collect_images(entry, str(workflow["nodo_salida"]))[0]
    raw = _download_image(image)
    out.write_bytes(_strip_metadata(raw))
    _cleanup_server_copy(image)

    params = dict(workflow.get("parametros", {}))
    params.update(overrides or {})
    record = {
        "file": str(out),
        "workflow": workflow["id"],
        "modelo": workflow["modelo"].get("nombre", workflow["id"]),
        "pesos": workflow["modelo"].get("pesos", []),
        "licencia": workflow["modelo"].get("licencia", "desconocida"),
        # La URL de los pesos la declara el workflow (`modelo.url`), y `assets.json` la exige (decisión 5). Hasta
        # OC1.4 solo la añadían los activos del motor de escena, y las láminas llegaban con `url: null`.
        "url": workflow["modelo"].get("url"),
        "origen": "generado en local con ComfyUI (127.0.0.1)",
        "prompt": _compose_prompt(workflow, prompt),
        "seed": int(seed),
        "resolucion": f"{width}x{height}",
        "parametros": params,
        "segundos": elapsed,
        "metadatos_png": "limpiados",
    }
    _record(record)
    return record


# --------------------------------------------------------------------------------------
# Contrato público — idéntico al del cliente de pago que sustituye
# --------------------------------------------------------------------------------------


def _resolve_style(style: str | None) -> str:
    chosen = (style or MODELO_IMAGEN or "").strip()
    # Trampa de python-dotenv: en una línea `CLAVE=    # comentario` con la clave vacía, el
    # comentario en línea llega como VALOR. Se trata como «sin fijar» en vez de buscar un
    # workflow con ese nombre, que daría un mensaje incomprensible.
    if chosen.startswith("#"):
        chosen = ""
    if not chosen:
        raise ComfyError(
            "MODELO_IMAGEN no está definido: el valor vive en el perfil del canal activo "
            "(canales/<id>/perfil.json, clave imagen.modelo) y el .env solo lo sobrescribe. "
            f"Workflows disponibles: {available_styles()}"
        )
    return chosen


def generate_image(
    prompt: str,
    output_path: str,
    width: int = IMAGE_GEN_WIDTH,
    height: int = IMAGE_GEN_HEIGHT,
    style: str | None = None,
    seed: int = IMAGE_SEED,
) -> str:
    """Genera una imagen. Misma firma que el cliente de pago, más estilo y seed opcionales."""
    workflow = load_workflow(_resolve_style(style))
    with comfy_server():
        record = render(workflow, prompt, output_path, width=width, height=height, seed=seed)
    _dump_records(Path(output_path).parent, [record])
    print(f"  Image saved: {output_path} ({record['segundos']}s, {record['modelo']})")
    return output_path


def generate_images_batch(prompts: list[dict], output_dir: str, style: str | None = None) -> list[str]:
    """Genera el lote EN SERIE. Cada dict: {prompt, filename, width?, height?, seed?, prefijo_estilo?}.

    Salta los archivos que ya existen (mismo criterio de reanudación que el cliente de
    pago) y arranca el servidor una sola vez para todo el lote. La lista devuelta
    conserva **el orden de entrada**: las etapas del pipeline emparejan por índice con
    `slides.json`, así que mezclar saltadas y nuevas rompería la asignación de assets.
    """
    workflow = load_workflow(_resolve_style(style))
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[str] = [str(out_dir / item["filename"]) for item in prompts]
    pending = []
    for item in prompts:
        out_path = out_dir / item["filename"]
        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"  Skipping {item['filename']} (already exists)")
            continue
        pending.append(item)

    if pending:
        with comfy_server():
            for numero, item in enumerate(pending, start=1):
                out_path = out_dir / item["filename"]
                print(f"  [{numero}/{len(pending)}] {item['filename']} — {workflow['id']}", flush=True)
                # `prefijo_estilo` de un item sustituye al del workflow solo para él (una copia: el resto del lote
                # sigue con el del workflow).
                propio = {**workflow, "prefijo_estilo": item["prefijo_estilo"]} if "prefijo_estilo" in item else None
                record = render(
                    propio or workflow,
                    item["prompt"],
                    str(out_path),
                    width=item.get("width", IMAGE_GEN_WIDTH),
                    height=item.get("height", IMAGE_GEN_HEIGHT),
                    seed=item.get("seed", IMAGE_SEED),
                )
                # Se vuelca en cada vuelta, no al final del lote: si el proceso muere a mitad
                # (o el lote se reanuda en otro proceso, que salta las imágenes ya hechas), lo
                # ya generado conserva su procedencia. Es lo que `assets.json` reconstruye
                # después (F2.4, decisión cerrada 5); un PNG sin registro no se puede defender.
                _dump_records(out_dir, [record])
                print(f"      {record['segundos']}s · {out_path}", flush=True)

    return results


def generate_thumbnail(prompt: str, output_path: str, style: str | None = None) -> str:
    """Miniatura 1280×720 con el mismo modelo local que las diapositivas."""
    return generate_image(
        prompt,
        output_path,
        width=THUMBNAIL_WIDTH,
        height=THUMBNAIL_HEIGHT,
        style=style,
    )


def preflight() -> list[dict]:
    """Comprueba que este adaptador podría generar imágenes AHORA, sin generar ninguna.

    Lo consume `pipeline.py --check`: el pipeline pregunta «¿estás listo?» y no necesita
    saber qué hay detrás (decisión cerrada 10). Cada entrada es
    `{nombre, ok, detalle, obligatorio}`; `ok=False` con `obligatorio=True` hace fallar
    el chequeo. El servidor **no se arranca aquí**: es una instalación compartida y un
    chequeo no debe dejar procesos por detrás.
    """
    checks: list[dict] = []

    try:
        # Valida de paso el grafo entero (lista blanca de nodos y generación en serie):
        # un workflow que no cargaría en producción no puede dar «listo» aquí.
        workflow = load_workflow(_resolve_style(None))
        modelo = workflow["modelo"]
        detalle = f"{workflow['id']} → {modelo['nombre'] if isinstance(modelo, dict) else modelo}"
        ok = True
    except ComfyError as exc:
        detalle = str(exc)
        ok = False
    checks.append({"nombre": "MODELO_IMAGEN", "ok": ok, "detalle": detalle, "obligatorio": True})

    if server_is_alive():
        checks.append(
            {
                "nombre": "ComfyUI",
                "ok": True,
                "detalle": f"vivo en {COMFY_BASE_URL} (compartido: el adaptador no lo apagará)",
                "obligatorio": True,
            }
        )
    else:
        python = Path(COMFY_PYTHON)
        main = COMFY_ROOT / "main.py"
        arrancable = python.exists() and main.exists()
        checks.append(
            {
                "nombre": "ComfyUI",
                "ok": arrancable,
                "detalle": (
                    f"no está vivo en {COMFY_BASE_URL}, pero el adaptador puede arrancarlo ({main})"
                    if arrancable
                    else f"no está vivo y no lo puedo arrancar (python={python}, main={main}): "
                    "revisa COMFY_ROOT / COMFY_PYTHON en el .env"
                ),
                "obligatorio": True,
            }
        )

    return checks
