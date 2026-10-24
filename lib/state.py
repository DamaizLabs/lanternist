import json
from datetime import datetime
from pathlib import Path

from lib.config import CANAL_ACTIVO, CANAL_VIDEOS_DIR, STATE_DIR

# Con qué motor se hace el vídeo de un run. Desde F6.7 (02-10-2026) hay uno, el de escena (`lib/escena/`):
# alinea → activos (parada 1) → escena (parada 2) → render.
MOTOR = "escena"
# El de los runs creados antes de F6.2d, que no llevan el campo `motor`: el de láminas con movimiento de lienzo,
# retirado en F6.7. Sus runs se siguen LEYENDO (métricas, procedencia, archivo) y sus etapas de producción se niegan
# (`pipeline._exige_motor_de_escena`).
MOTOR_RETIRADO = "montaje"
# Las etapas de un run, en su orden. `assembly` sigue en la lista porque es donde `render` deja el vídeo final: la
# subida y el panel de la semana lo leen de ahí.
ETAPAS = (
    "slides_json",
    "images",
    "tts",
    "alinea",
    "activos",
    "escena",
    "render",
    "assembly",
    "thumbnail",
    "upload",
)


def motor_de(state: dict) -> str:
    """El motor de un run. Los creados antes de F6.2d no lo dicen y son del motor de láminas, ya retirado."""
    return state.get("motor") or MOTOR_RETIRADO


class EstadoRoto(ValueError):
    """El fichero de estado de un run no se puede leer. Hereda de ValueError a propósito.

    **Por qué existe (auditoría del 10-09, MEDIO).** El estado se edita a mano más de lo que parece
    —un `output` corregido, un bloque de publicación añadido— y hasta hoy un JSON a medias mataba el
    pipeline con una traza de `json.JSONDecodeError` que no decía ni qué fichero era. Sigue parando,
    porque sin estado no se puede seguir, pero ahora dice cuál y qué hacer.
    """


def create_run(title: str, mode: str, voice: str, channel_url: str = "") -> dict:
    """Un run nuevo, del motor de escena (el único desde F6.7).

    Hasta F6.7 se elegía el motor (`motor`) y, en el de láminas, cómo se animaba (`animacion`: «kaggle» o «lienzo»).
    Los dos argumentos salieron con aquel motor; los estados viejos que llevan `animacion` se siguen leyendo igual.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    slug = _slugify(title)
    run_id = f"{timestamp}_{slug}"

    run_dir = CANAL_VIDEOS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "slides").mkdir(exist_ok=True)
    (run_dir / "audio").mkdir(exist_ok=True)

    run_state = {
        "run_id": run_id,
        # Canal del estudio que produce este run. `channel_url` (más abajo) es otra cosa:
        # el canal de REFERENCIA que viene del fork, no el destino (F2.11).
        "canal": CANAL_ACTIVO,
        "title": title,
        "mode": mode,
        "voice": voice,
        # Se escribe aunque sea el único: un estado sin `motor` es, por definición, del motor retirado (`motor_de`).
        "motor": MOTOR,
        "channel_url": channel_url,
        "status": "created",
        "created_at": datetime.now().isoformat(),
        "stages": {etapa: {"status": "pending"} for etapa in ETAPAS},
        "slide_assets": {},
        "output_dir": str(run_dir),
    }

    _save_state(run_id, run_state)
    return run_state


def load_run(run_id: str) -> dict:
    state_file = STATE_DIR / f"{run_id}.json"
    return _lee_estado(state_file)


def _lee_estado(state_file: Path) -> dict:
    """Lee un fichero de estado en UTF-8 y falla diciendo cuál si no se puede.

    **El `encoding` explícito no es cosmético.** Sin él, Windows abre en cp1252: un título con
    acentos escrito por otra herramienta en UTF-8 —la migración a `subir-al-canal/` del 10-09 lo
    hacía— se lee como mojibake («Ñandú» → «Ã‘andÃº») y ese texto viaja al título del vídeo.
    """
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise EstadoRoto(
            f"no existe el estado {state_file.name}: los runs vivos se listan con `pipeline.py --list`"
        ) from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EstadoRoto(
            f"el estado {state_file.name} no se puede leer ({type(exc).__name__}: {exc}). Es la memoria del "
            f"run: arréglalo a mano en {state_file} —suele ser una edición a medias— antes de seguir."
        ) from None


def _registra_una_subida(output: str) -> bool:
    """True si el `output` de una etapa guarda el id de un vídeo ya subido a YouTube."""
    try:
        return bool(json.loads(output or "{}").get("video_id"))
    except (json.JSONDecodeError, AttributeError, TypeError):
        # El `output` de una etapa es texto libre: el motivo de un `skipped` no es JSON, y eso
        # no es un error, solo significa que ahí no hay ninguna subida registrada.
        return False


def update_stage(run_id: str, stage: str, status: str, output: str = "") -> dict:
    """Actualiza una etapa del run. NUNCA degrada una etapa que ya registró una subida.

    El invariante vive aquí, y no en quien llama, porque la auditoría de F3.3 encontró el MISMO
    fallo por tres puertas distintas: `stage_upload`, la rama de `--sin-subida` de `run_all` y el
    camino de credenciales ausentes. Las tres escribían `skipped` sobre una etapa que ya tenía el
    `video_id` del vídeo subido —y el motivo del `skipped` viaja en el mismo campo `output` que el
    JSON del resultado, así que lo pisaba—, con lo que la guarda que evita duplicados perdía su
    memoria y el siguiente `--run-all` subía un segundo borrador al canal.

    Parchear cada puerta habría dejado la cuarta abierta. La regla, en una frase: **un `output` que
    guarda un `video_id` solo lo puede sustituir otro que también lo tenga.** Un `--forzar-subida`
    legítimo sigue funcionando: su escritura final trae el id nuevo, y mientras llega se conserva el
    viejo, que es estrictamente mejor que quedarse sin ninguno.
    """
    state = load_run(run_id)
    etapa = state["stages"][stage]

    if _registra_una_subida(etapa.get("output", "")) and not _registra_una_subida(output):
        print(
            f"  [ESTADO] la etapa '{stage}' ya registra un vídeo subido: no se degrada a "
            f"'{status}'. Lo pedido se ignora para no perder el id (lib/state.py)"
        )
        return state

    etapa["status"] = status
    if output:
        etapa["output"] = output
    etapa["updated_at"] = datetime.now().isoformat()
    _save_state(run_id, state)
    return state


def update_run(run_id: str, updates: dict) -> dict:
    state = load_run(run_id)
    state.update(updates)
    _save_state(run_id, state)
    return state


def set_slide_asset(run_id: str, slide_num: int, asset_type: str, path: str) -> dict:
    state = load_run(run_id)
    key = str(slide_num)
    if key not in state["slide_assets"]:
        state["slide_assets"][key] = {}
    state["slide_assets"][key][asset_type] = path
    _save_state(run_id, state)
    return state


def list_runs(status_filter: str = "") -> list:
    """Los runs del canal. Un estado ilegible se IGNORA con aviso, no tumba la lista.

    Listar es lo primero que se hace al abrir el proyecto, y un solo fichero a medias dejaba sin
    inventario a los otros nueve (auditoría del 10-09). `metricas.videos_del_pipeline` ya lo hacía
    así; aquí faltaba.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    runs = []
    for f in sorted(STATE_DIR.glob("*.json"), reverse=True):
        try:
            state = _lee_estado(f)
        except EstadoRoto as exc:
            print(f"  [ESTADO] {exc} Se ignora en el listado.")
            continue
        if not status_filter or state.get("status") == status_filter:
            runs.append(state)
    return runs


def _save_state(run_id: str, state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"{run_id}.json"
    # UTF-8 explícito y `ensure_ascii` por defecto: el fichero queda en ASCII puro, así que ninguna
    # herramienta que lo relea con otra codificación puede estropear un título con acentos.
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = "".join(c if c.isalnum() or c in (" ", "-") else "" for c in slug)
    slug = slug.replace(" ", "-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:50].strip("-")
