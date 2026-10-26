#!/usr/bin/env python3
r"""
YT Video Factory — Pipeline Orchestrator

Usage (called by the AI agent, not directly by users):

    # Check dependencies
    python3 pipeline.py --check

    # Run individual stages for a run (motor de escena; after `activos` and after `escena` it STOPS)
    python3 pipeline.py --run-id <run_id> --stage images
    python3 pipeline.py --run-id <run_id> --stage tts
    python3 pipeline.py --run-id <run_id> --stage alinea
    python3 pipeline.py --run-id <run_id> --stage activos     # parada 1
    python3 pipeline.py --run-id <run_id> --stage escena      # parada 2
    python3 pipeline.py --run-id <run_id> --stage render
    python3 pipeline.py --run-id <run_id> --stage thumbnail
    python3 pipeline.py --run-id <run_id> --stage upload

    # Advance to the next stop, or finish after the render (thumbnail → upload)
    python3 pipeline.py --run-id <run_id> --run-all

    # Create a new run (agent writes slides.json first, then calls this)
    .venv\Scripts\python pipeline.py --create --title "Video Title" --voice neutro

El motor de escena es el único del estudio desde el 02-10-2026 (F6.7). Los runs del motor de láminas, anteriores, se
siguen LEYENDO (`--list`, `--assets-audit`, métricas, archivo), pero sus etapas de producción se niegan con el motivo.

    # List runs
    python3 pipeline.py --list

    # Rebuild assets.json and cross-count it against the run files (exit 1 if it does not add up)
    python3 pipeline.py --run-id <run_id> --assets-audit

Cada etapa que produce assets escribe la procedencia en `<run>/assets.json` (fuente, licencia,
URL/origen y modelo real de cada uno): decisión cerrada 5, integrada en las etapas y no como
paso final. Ver `lib/provenance.py`.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# --- `--canal` se resuelve ANTES de importar nada de `lib/`, y tiene que ser así ---
#
# **El problema que cierra.** El canal salía solo de `CANAL_ACTIVO` del `.env`, o sea de **ambiente
# que sobrevive entre sesiones**: con cinco canales, lanzar el pipeline producía para el que quedó
# escrito la última vez, en silencio. La skill `produce-semana` lo mitigaba pidiendo «dilo en voz
# alta», que es una convención y no una guarda — el mismo patrón que la auditoría del 08-09 nombró
# como dominante: «está protegido donde lo que protege es prosa». Con `--canal` el canal pasa a ser
# un **argumento explícito de cada invocación**, y el `.env` queda como comodidad de una sola sesión.
#
# **Por qué aquí arriba y no en el `argparse` de `main()`.** `lib/config.py` lee `CANAL_ACTIVO` al
# importarse (`config.py:43`) y de ahí derivan el perfil, la receta de voz, las rutas del canal y
# `CANAL_ERROR`. Cuando `argparse` corre ya es tarde: la configuración está resuelta. Así que se
# mira `sys.argv` a mano, antes de la primera importación de `lib`. El flag se registra igual en el
# parser, para que salga en `--help` y para que un valor mal escrito dé el error de siempre.
if "--canal" in sys.argv:
    _i = sys.argv.index("--canal")
    if _i + 1 < len(sys.argv):
        os.environ["CANAL_ACTIVO"] = sys.argv[_i + 1].strip()

from lib import (  # noqa: E402
    comfy_client,
    lineas_rojas,
    musica,
    provenance,
    subtitulos,
    voice_client,
)
from lib import state as run_state  # noqa: E402

# Adaptadores LOCALES (decisiones cerradas 4 y 10: coste marginal 0 € y el pipeline no
# conoce modelos). Firmas idénticas a las del cliente de pago del fork, eliminado del
# repositorio en F2.3 junto con sus claves.
# `generate_thumbnail` sigue existiendo en el adaptador —es parte del contrato de la decisión 10— pero
# el pipeline ya no lo llama: desde el 12-09 la miniatura sale siempre de una lámina (fila 156).
from lib.comfy_client import generate_images_batch
from lib.voice_client import generate_tts_batch

# Binarios del sistema que el pipeline invoca por su cuenta: FFmpeg mezcla y normaliza el sonido y
# recorta el clip de referencia de voz, y ffprobe mide lo que sale. yt-dlp ya no: el motor no descarga
# vídeos de YouTube (fila 319).
REQUIRED_BINARIES = ("ffmpeg", "ffprobe")


def _print_check(nombre: str, ok: bool, detalle: str) -> None:
    print(f"  {'✓' if ok else '✗'} {nombre}: {detalle}")


def check_dependencies():
    """Comprueba lo que el pipeline necesita DE VERDAD para producir un vídeo hoy.

    Cinco bloques: el canal activo, los binarios del sistema, los adaptadores locales
    (cada uno responde por lo suyo con su `preflight()`, que el pipeline no interpreta), el motor de escena
    (`_comprueba_el_motor_de_escena`) y la subida a YouTube: a mano no pide nada, y por la API exige el OAuth
    completo (`_comprueba_la_subida`).
    """
    import shutil

    from lib.config import BASE_DIR, CANAL_ACTIVO, CANAL_ERROR, CANAL_PERFIL, CANAL_PERFIL_PATH

    all_ok = True

    # El canal va primero: sin él no hay estilo, ni voz, ni idioma, ni datos — todo lo que
    # sigue depende de su perfil (F2.11, doc/06-arquitectura-estudio-canales.md).
    print("\nCanal activo:")
    if CANAL_ERROR:
        _print_check("CANAL_ACTIVO", False, CANAL_ERROR)
        all_ok = False
    else:
        # Sin asumir la forma del perfil: se edita a mano, y escribir
        # `"nicho": "ejemplo-sin-cifras"` en vez del objeto es la simplificación que
        # cualquiera haría. Un diagnóstico no puede morir por eso.
        bloque_nicho = CANAL_PERFIL.get("nicho")
        if isinstance(bloque_nicho, dict):
            nicho = bloque_nicho.get("id") or "sin nicho declarado"
        elif isinstance(bloque_nicho, str) and bloque_nicho.strip():
            nicho = bloque_nicho.strip()
        else:
            nicho = "sin nicho declarado"
        nombre = CANAL_PERFIL.get("nombre")
        _print_check(
            CANAL_ACTIVO,
            True,
            f"{nombre if isinstance(nombre, str) and nombre else CANAL_ACTIVO} · "
            f"nicho '{nicho}' · perfil en {CANAL_PERFIL_PATH.relative_to(BASE_DIR)}",
        )
        # Una decisión de canal que viene del `.env` NO es un error —sirve para un experimento de un
        # run— pero tampoco puede ser invisible: el `.env` es uno solo para todo el estudio, así que
        # esa línea decide por TODOS los canales a la vez (F4.9, R1 de la revisión).
        from lib.config import _CANAL_DESDE_ENTORNO

        for anulado in _CANAL_DESDE_ENTORNO:
            _print_check("anulado por el entorno", True, anulado.replace("`", ""))

        # La audiencia declarada y la categoría se comprueban AQUI y no en la subida: allí el vídeo ya
        # está montado y el problema se descubre con la GPU gastada (F4.9, R6). La misma comprobación la
        # usa `scripts/comprueba_canal.py`.
        from lib.youtube_client import comprobaciones_del_canal

        for check in comprobaciones_del_canal():
            _print_check(check["nombre"], check["ok"], check["detalle"])
            if not check["ok"]:
                all_ok = False

        # El buzón de ideas (F5.11), que es lo único que puede quedarse olvidado meses: un `.txt`
        # que el usuario pega y nadie normaliza no da ningún error en ninguna parte. **No es un fallo y
        # por eso no toca `all_ok`**: producir con el buzón lleno es perfectamente válido.
        from lib.config import CANAL_DIR
        from lib.ideas import pendientes_en

        sin_leer = pendientes_en(CANAL_DIR) if CANAL_DIR else []
        if sin_leer:
            print(
                f"  ⚠ buzón de ideas: {len(sin_leer)} .txt sin leer "
                f"({', '.join(p.name for p in sin_leer[:3])}{' …' if len(sin_leer) > 3 else ''}) — "
                "léelos con `ideas.py --leer-buzon`"
            )

    print("\nBinarios del sistema:")
    for name in REQUIRED_BINARIES:
        path = shutil.which(name)
        _print_check(name, bool(path), path or "NO ENCONTRADO en el PATH")
        all_ok = all_ok and bool(path)

    # Las herramientas locales no tienen ruta por defecto (OC1.3): cada una la escribe quien usa el motor en su
    # `.env`. Aquí se dice cuál falta y qué escribir; los adaptadores de abajo miran después si arrancan.
    from lib.config import RUTAS_DE_HERRAMIENTAS

    print("\nRutas de las herramientas locales (.env):")
    for variable, que_es in RUTAS_DE_HERRAMIENTAS.items():
        valor = os.getenv(variable, "").strip()
        existe = bool(valor) and Path(valor).exists()
        if not valor:
            detalle = f"falta en el .env: escribe {variable}=<{que_es}>"
        else:
            detalle = valor if existe else f"{valor} no existe: corrige {variable} en el .env"
        _print_check(variable, existe, detalle)
        all_ok = all_ok and existe

    # La onda de ecualizador (`lib/onda.py`) no está: se guarda para un canal futuro (fila 214) y ningún paso del
    # pipeline la aplica, así que comprobarla aquí diría «lista» de algo que no se produce. Lo que el motor de escena
    # necesita por su cuenta (Chrome con WebGPU, `.venv-escena` y el peso de Real-ESRGAN) va al final, en su bloque.
    for etiqueta, adapter in (
        ("Adaptador de imagen", comfy_client),
        ("Adaptador de voz", voice_client),
        ("Lecho musical", musica),
        ("Subtítulos", subtitulos),
    ):
        print(f"\n{etiqueta}:")
        try:
            checks = adapter.preflight()
        except Exception as exc:  # amplio a propósito: un chequeo no debe romperse, debe informar
            _print_check("preflight", False, f"{type(exc).__name__}: {exc}")
            all_ok = False
            continue
        for check in checks:
            _print_check(check["nombre"], check["ok"], check["detalle"])
            if check["obligatorio"] and not check["ok"]:
                all_ok = False

    all_ok = _comprueba_el_motor_de_escena() and all_ok
    all_ok = _comprueba_la_subida() and all_ok

    print(f"\n{'Listo para producir.' if all_ok else 'FALTAN dependencias obligatorias (arriba, con ✗).'}")
    return all_ok


def _comprueba_el_motor_de_escena() -> bool:
    """El bloque del motor de escena de `--check`: lo que necesita y no mira ningún adaptador.

    Tres cosas, las tres obligatorias: el Chrome con WebGPU, con el sha256 de cada fichero contra su manifiesto;
    `.venv-escena`, con el torch de CUDA y lo que importa el obrero; y el peso de Real-ESRGAN. Hasta OC1.7 lo miraba
    `node init.mjs`, que es del arnés del dueño y no viaja al repositorio público (R3 de `progress/review_OC1.3.md`).
    Lo que falte lo instala `py -3.12 instala.py`.
    """
    import subprocess

    from lib import config
    from lib.marca_ia import sha256_de as sha256

    print("\nMotor de escena:")
    instala = "py -3.12 instala.py --paso escena"
    manifiesto = Path(config.CHROME_WEBGPU_MANIFIESTO)
    try:
        datos = json.loads(manifiesto.read_text(encoding="utf-8"))
        carpeta = Path(datos["exe"]).parent
        esperados = dict(datos["sha256"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        chrome_ok, detalle = False, f"no se puede leer su manifiesto ({manifiesto}: {exc}): {instala}"
    else:
        faltan = [f for f in ("chrome-headless-shell.exe", "dxil.dll", "dxcompiler.dll") if f not in esperados]
        distintos = [f for f, h in esperados.items() if not (carpeta / f).is_file() or sha256(carpeta / f) != h]
        chrome_ok = not faltan and not distintos
        detalle = (
            f"{datos.get('chrome_headless', '?')} con las DXC de {datos.get('dxc_de', '?')}, sha256 comprobado"
            if chrome_ok
            else f"{', '.join(faltan + distintos)} no está o no cuadra con su manifiesto: {instala}"
        )
    _print_check("Chrome con WebGPU", chrome_ok, detalle)

    python = Path(config.ESCENA_PYTHON)
    if not python.is_file():
        venv_ok, detalle = False, f"no está ({python}): py -3.12 instala.py --paso entornos"
    else:
        codigo = "import torch, spandrel, transformers; print(torch.__version__, torch.version.cuda)"
        r = subprocess.run([str(python), "-c", codigo], capture_output=True, text=True, timeout=300)
        version, _, cuda = (r.stdout.strip().splitlines() or [""])[-1].partition(" ")
        venv_ok = r.returncode == 0 and cuda not in ("", "None")
        if venv_ok:
            detalle = f"torch {version} con CUDA {cuda}"
        elif r.returncode == 0:
            detalle = f"torch {version} SIN CUDA: pip trajo el de CPU (la trampa de spikes/requirements-escena.txt)"
        else:
            detalle = f"no importa torch, spandrel y transformers: {(r.stderr or '').strip().splitlines()[-1:]}"
    _print_check(".venv-escena", venv_ok, detalle)

    esrgan = Path(config.ESCENA_ESRGAN_PESO)
    esrgan_ok = esrgan.is_file()
    detalle = str(esrgan) if esrgan_ok else f"no está ({esrgan}): py -3.12 instala.py --paso pesos"
    _print_check("peso de Real-ESRGAN", esrgan_ok, detalle)
    return chrome_ok and venv_ok and esrgan_ok


def _comprueba_la_subida() -> bool:
    """El bloque de la subida de `--check`: qué modo está activo y, con la API encendida, si el OAuth está completo.

    A mano es lo de serie y no pide nada (OC1.8). Sale en rojo lo que pararía la etapa de subida: un
    `YOUTUBE_SUBIDA_API` que no se entiende, o la API encendida sin el OAuth completo. El motivo es el de la etapa.
    """
    from lib.config import YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
    from lib.youtube_client import GUIA_DE_LA_SUBIDA, SubidaNoConfigurada, subida_por_la_api

    print("\nSubida a YouTube (siempre borrador privado; el modo lo elige YOUTUBE_SUBIDA_API en el .env):")
    try:
        por_la_api = subida_por_la_api()
    except SubidaNoConfigurada as exc:
        _print_check("subida por la API", False, str(exc))
        return False
    if por_la_api:
        _print_check("subida por la API", True, f"encendida, con el OAuth completo ({GUIA_DE_LA_SUBIDA})")
        return True
    _print_check(
        "subida a mano en Studio",
        True,
        "es lo de serie. El run deja en subir-al-canal/ el vídeo, la miniatura, los .srt y LEEME.html con los pasos, "
        f"sin pedir ninguna clave de Google. Para que suba el motor: YOUTUBE_SUBIDA_API=1 y {GUIA_DE_LA_SUBIDA}",
    )
    if all([YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN]):
        print("  ⚠ las claves OAuth están en el .env, pero no se usan hasta que escribas YOUTUBE_SUBIDA_API=1")
    return True


def _relativa_al_run(ruta: str | Path, run_dir: str | Path) -> str:
    """La ruta relativa al run, o tal cual si cae fuera de él.

    El expediente de un run se escribe con rutas relativas (`provenance` hace lo mismo) para que siga
    siendo legible si el run cambia de carpeta — que ya pasó dos veces, con la reorganización del 30-08 y
    con la migración del repo a `C:` del 06-09. Una ruta absoluta ahí es además una ruta personal en un
    JSON que puede acabar en git.
    """
    try:
        return Path(ruta).relative_to(Path(run_dir)).as_posix()
    except ValueError:
        return str(ruta)


def _sync_assets(state: dict, etapa: str) -> dict:
    """Actualiza `assets.json` del run y hace el conteo cruzado (decisión cerrada 5).

    Las etapas la llaman en un `finally`: la procedencia se escribe también cuando la etapa
    se rompe a mitad, que es cuando más falta hace. Es idempotente —se reconstruye desde los
    registros que dejan los adaptadores— así que repetirla no duplica nada.
    """
    return provenance.sync(
        state["output_dir"],
        run_id=state["run_id"],
        titulo=state.get("title", ""),
        etapa=etapa,
    )


def stage_images(run_id: str):
    """Generate all slide images with the local image adapter (ComfyUI)."""
    state = run_state.load_run(run_id)
    _exige_motor_de_escena(state, "images")
    run_dir = state["output_dir"]
    slides_path = Path(run_dir) / "slides.json"

    if not slides_path.exists():
        raise FileNotFoundError(f"slides.json not found at {slides_path}. Agent must create it first.")

    # **`encoding="utf-8"` no es adorno: sin él, Windows decodifica con cp1252.** El guion del
    # episodio 1 de un canal llegaba a memoria ya roto —la raya larga y los puntos suspensivos como
    # `â€"` y `â€¦`— y de ahí pasaban al karaoke quemado y al `.srt`. Se vio en el vídeo.
    # El `.ass` se escribe bien desde el 05-09 y aun así salía mal: el fichero no era el problema,
    # lo era esta línea.
    slides_json = json.loads(slides_path.read_text(encoding="utf-8"))
    slides = slides_json["slides"]

    run_state.update_stage(run_id, "images", "in_progress")
    print(f"\n[IMAGES] Generating {len(slides)} slide images...")

    prompts = []
    for slide in slides:
        item = {
            "prompt": slide["image_prompt"],
            "filename": f"slide-{slide['slide_number']:02d}.png",
        }
        # Semilla por lámina, opcional. El contrato de prompt del canal la pide justamente
        # para esto: la semilla del perfil define el acabado de TODO el canal y no se toca,
        # así que rescatar una lámina que salió mal se hace variando la suya y anotándolo.
        if slide.get("seed") is not None:
            item["seed"] = int(slide["seed"])
        # El acabado de UNA lámina, opcional: sustituye al `prefijo_estilo` del workflow solo para ella. Nace en
        # OC1.4: la lámina 3 del canal de ejemplo solo dibujó un único tirador con el prompt entero en español.
        if slide.get("prefijo_estilo"):
            item["prefijo_estilo"] = str(slide["prefijo_estilo"])
        prompts.append(item)

    slides_dir = str(Path(run_dir) / "slides")
    try:
        results = generate_images_batch(prompts, slides_dir)
    finally:
        _sync_assets(state, "images")

    for i, path in enumerate(results):
        run_state.set_slide_asset(run_id, slides[i]["slide_number"], "image", path)

    # Guarda de líneas rojas ANTES de dar la etapa por buena. Hasta F2.5 la única defensa era
    # la frase «no injury, no blood» del prompt positivo, y en el primer run real falló en 1
    # de 8 láminas: se montó un vídeo con un charco de sangre nueve segundos en pantalla, y
    # ningún `ffprobe` lo habría notado. Se para aquí, no después del montaje.
    try:
        informe = lineas_rojas.exige(results, etapa="images")
    except lineas_rojas.LineaRojaError as exc:
        run_state.update_stage(run_id, "images", "blocked", str(exc).splitlines()[0])
        raise
    # Decir «sin hallazgos» cuando el canal no declara guardianes sería mentir por omisión: no es
    # que estén limpias, es que nadie las miró (F4.8 · R4 de la revisión).
    _guardas = informe.get("guardianes") or []
    print(
        f"[IMAGES] Líneas rojas: {informe['revisadas']} láminas revisadas contra "
        f"{len(_guardas)} guardián(es) del canal ({', '.join(_guardas)}), sin hallazgos"
        if _guardas
        else f"[IMAGES] Líneas rojas: el canal no declara ningún guardián de color, "
        f"así que no hay nada que medir sobre las {informe['revisadas']} láminas"
    )

    # Con motivo explícito: `update_stage` no borra el `output` anterior, así que sin esto un
    # bloqueo previo dejaba «LÍNEA ROJA CRUZADA» pegado al estado ya en `complete` — y ese
    # archivo se versiona como prueba del run.
    run_state.update_stage(
        run_id,
        "images",
        "complete",
        f"{len(results)} láminas · líneas rojas: "
        + (f"sin hallazgos con {len(_guardas)} guardián(es)" if _guardas else "el canal no declara guardianes"),
    )
    print(f"[IMAGES] Done — {len(results)} images generated")
    return results


def stage_tts(run_id: str):
    """Generate voiceover audio for all slides with the local voice adapter (Orpheus)."""
    state = run_state.load_run(run_id)
    _exige_motor_de_escena(state, "tts")
    run_dir = state["output_dir"]
    voice = state["voice"]
    slides_path = Path(run_dir) / "slides.json"

    slides_json = json.loads(slides_path.read_text(encoding="utf-8"))
    slides = slides_json["slides"]

    run_state.update_stage(run_id, "tts", "in_progress")
    print(f"\n[TTS] Generating {len(slides)} voiceovers with voice '{voice}'...")

    items = []
    for slide in slides:
        items.append(
            {
                "text": slide["narration"],
                "filename": f"slide-{slide['slide_number']:02d}.wav",
            }
        )

    audio_dir = str(Path(run_dir) / "audio")
    try:
        results = generate_tts_batch(items, audio_dir, voice)
    finally:
        _sync_assets(state, "tts")

    # **La limpieza va aquí y no después del montaje**, sobre los wav recién generados: es lo que
    # calla lo que el motor produce cuando ya no le queda texto, y por nivel eso no se distingue del
    # final de una palabra — hacen falta las marcas del alineador (addendum filas 88 y 90).
    from lib.limpia_voz import limpia_lote
    from lib.voice_client import ajustes_de_limpieza

    limpia_lote(
        results,
        [item["text"] for item in items],
        Path(run_dir) / "limpieza",
        ajustes_de_limpieza(),
    )

    for i, path in enumerate(results):
        run_state.set_slide_asset(run_id, slides[i]["slide_number"], "audio", path)

    run_state.update_stage(run_id, "tts", "complete")
    print(f"[TTS] Done — {len(results)} audio files generated")
    return results


def _exige_fichas_de_la_bibliografia(run_id: str, slides_json: dict) -> list[str]:
    """Los ids de ficha con los que se compone `<<BIBLIOGRAFIA>>`, o para el run si faltan.

    **No se deducen.** El canal tiene once fichas verificadas y cada vídeo cita las suyas; quien sabe
    cuáles es quien escribió el guion en el gate 1. Elegirlas aquí —por el título, por el nicho, por lo
    que sea— publicaría una bibliografía que nadie eligió, y eso rompe el principio del módulo de
    fuentes: una cita que no resuelve, no existe.

    Si la descripción ya está compuesta no hace falta ninguna, así que un run viejo sin el campo se
    puede volver a subir sin tocarlo.
    """
    from scripts.compone_descripcion import fichas_del_guion

    fichas = fichas_del_guion(slides_json)
    if not fichas and "<<BIBLIOGRAFIA>>" in (slides_json.get("description") or ""):
        run_state.update_stage(run_id, "upload", "blocked", "slides.json sin `fuentes`")
        raise ValueError(
            "la descripción lleva `<<BIBLIOGRAFIA>>` y el guion no declara `fuentes`: la bibliografía sale "
            "de las fichas con las que se escribió el guion y NO se deduce aquí, porque publicaría citas "
            'que nadie eligió. Escribe `"fuentes": ["<id-de-ficha>"]` en slides.json —los ids son los '
            "nombres de los ficheros de `canales/<canal>/datos/fuentes/` sin la extensión— y vuelve a "
            "lanzar la etapa."
        )
    return fichas


def stage_assembly(run_id: str):
    """La etapa del montaje del motor de láminas, retirado el 02-10-2026 (F6.7): solo dice qué hacer en su lugar.

    Se conserva el nombre para que `--stage assembly` no responda «etapa desconocida», que no explica nada. En el
    estado de cada run la etapa `assembly` sigue existiendo: ahí deja `render` la ruta del vídeo final, que es donde la
    leen la subida y el panel de la semana.
    """
    state = run_state.load_run(run_id)
    _exige_motor_de_escena(state, "assembly")
    raise MotorRetirado(
        "la etapa `assembly` era el montaje del motor de láminas, retirado el 02-10-2026. En el motor de "
        "escena el vídeo lo hace `render`, tras las dos paradas del usuario: alinea → activos (parada 1) → escena "
        "(parada 2) → render."
    )


# --- El motor de escena (Loop 6, F6.2d) ---------------------------------------------------------------------------
#
# El único motor del estudio desde F6.7. Sus etapas, con DOS PARADAS del usuario:
#
#   images → tts → alinea → activos ⏸ parada 1 → escena ⏸ parada 2 → render → thumbnail → upload
#
# En cada parada el pipeline se DETIENE y abre la página de revisión (las imágenes nuevas del episodio; los
# fotogramas clave antes del render). Se sigue con `--stage escena` y `--stage render`, y es la única forma de
# seguir: `--run-all` nunca pasa una parada, y `escena` y `render` se niegan si la etapa de antes no está hecha. Lo
# que hacen está en `lib/escena/etapas.py`; aquí vive el estado del run, la procedencia y las paradas.
class MotorRetirado(RuntimeError):
    """Una etapa que se niega por el motor de láminas, retirado en F6.7. `main` imprime el motivo, sin traza.

    Es una negativa prevista, no un fallo: la traza solo tapaba el motivo (R2 de `progress/review_F6.7.md`).
    """


def _exige_motor_de_escena(state: dict, etapa: str) -> None:
    """Para si el run es del motor de láminas: se retiró en F6.7 y sus runs se leen, pero ya no se producen.

    Leer es todo lo que no fabrica el vídeo: `--list`, `--assets-audit`, las métricas, la foto de los 30 días, el
    archivado. Producir es cualquier etapa que hace el vídeo, la miniatura o la subida, y esas fallan aquí con el
    motivo en vez de a mitad.
    """
    if run_state.motor_de(state) != run_state.MOTOR:
        raise MotorRetirado(
            f"el run {state.get('run_id')} es del motor de láminas, retirado el 02-10-2026: se sigue leyendo "
            f"(métricas, procedencia, archivo), pero ya no se produce. La etapa `{etapa}` no corre sobre él; para "
            "rehacer ese vídeo, crea un run nuevo con `--create`, que es del motor de escena."
        )


def _episodio(state: dict):
    """El episodio del motor de escena para este run, con el canal activo. Para si el run es de otro canal."""
    from lib import config
    from lib.escena.episodio import Episodio

    canal = state.get("canal")
    if canal and canal != config.CANAL_ACTIVO:
        raise RuntimeError(
            f"el run {state.get('run_id')} es del canal {canal} y el activo es {config.CANAL_ACTIVO}: su guion de "
            f"escena y su perfil son los de su canal. Lánzalo con `--canal {canal}`."
        )
    return Episodio(
        run_dir=state["output_dir"],
        run_id=state["run_id"],
        canal_dir=config.CANAL_DIR,
        perfil=config.CANAL_PERFIL,
        idioma=config.SUBTITLE_LANG,
    )


def _hecha(state: dict, etapa: str) -> bool:
    return ((state.get("stages") or {}).get(etapa) or {}).get("status") == "complete"


def _exige_parada(run_id: str, state: dict, antes: str, etapa: str, parada: str) -> None:
    """La etapa `etapa` solo corre tras `antes`: es la parada `parada` del usuario, y no se salta."""
    if not _hecha(state, antes):
        mensaje = (
            f"[{etapa.upper()}] NO se sigue: la etapa `{antes}` no está hecha, y tras ella va la {parada} (el "
            f"usuario mira su página antes de seguir). Lanza antes `--stage {antes}`."
        )
        run_state.update_stage(run_id, etapa, "blocked", mensaje)
        raise RuntimeError(mensaje)


def _invalida(run_id: str, etapas: tuple[str, ...], motivo: str) -> None:
    """Lo que dependía de una etapa que se acaba de rehacer ya no vale: vuelve a pendiente, con el motivo."""
    state = run_state.load_run(run_id)
    for etapa in etapas:
        if ((state["stages"].get(etapa) or {}).get("status") or "pending") != "pending":
            run_state.update_stage(run_id, etapa, "pending", motivo)


def _corre(run_id: str, state: dict, etapa: str, cuerpo):
    """Corre una etapa del motor de escena con su estado y su procedencia (también si se rompe a mitad)."""
    run_state.update_stage(run_id, etapa, "in_progress")
    try:
        return cuerpo()
    except Exception as exc:
        run_state.update_stage(run_id, etapa, "blocked", (str(exc).splitlines() or [type(exc).__name__])[0][:300])
        raise
    finally:
        _sync_assets(state, etapa)


def _para_en(run_id: str, etapa: str, pagina, sigue_con: str, cual: str) -> None:
    """El pipeline se detiene: deja escrita la parada en el estado del run, abre su página y dice cómo seguir."""
    from lib import pagina_local

    run_state.update_run(
        run_id,
        {"status": "en_parada", "parada": {"cual": cual, "tras": etapa, "pagina": str(pagina), "sigue_con": sigue_con}},
    )
    print(f"\n[{cual.upper()}] El pipeline se DETIENE aquí: {pagina}")
    from lib import config

    print(
        f"  Cuando la página esté revisada, sigue con: "
        f"pipeline.py --canal {config.CANAL_ACTIVO} --run-id {run_id} --stage {sigue_con}"
    )
    pagina_local.abre(Path(pagina))


def stage_alinea(run_id: str) -> dict:
    """Alinea la narración con whisper, arma la línea de tiempo y escribe el `.srt` con los cues del karaoke."""
    state = run_state.load_run(run_id)
    _exige_motor_de_escena(state, "alinea")
    from lib.escena import etapas

    ep = _episodio(state)
    print("\n[ALINEA] Marcas por palabra, línea de tiempo y .srt...")
    info = _corre(run_id, state, "alinea", lambda: etapas.alinea(ep))
    salida = info["srt"] or info["alineacion"]
    run_state.update_stage(run_id, "alinea", "complete", _relativa_al_run(salida, state["output_dir"]))
    _invalida(
        run_id, ("escena", "render", "assembly"), "la alineación se rehízo: la escena hay que componerla otra vez"
    )
    print(
        f"[ALINEA] Done — {info['cues']} cues · cobertura {info['informe']['cobertura']} · "
        f"guion por partes en {info['guion_por_partes']}"
    )
    return info


def stage_activos(run_id: str) -> dict:
    """Las imágenes nuevas del guion de escena. Termina en la PARADA 1: el pipeline se detiene y abre su página."""
    state = run_state.load_run(run_id)
    _exige_motor_de_escena(state, "activos")
    from lib.escena import etapas

    ep = _episodio(state)
    print("\n[ACTIVOS] Las imágenes nuevas del episodio...")
    info = _corre(run_id, state, "activos", lambda: etapas.activos(ep))
    if info["faltan"]:
        # La página se abre igual: es donde se ve entre qué semillas hay que elegir.
        from lib import pagina_local

        mensaje = f"falta elegir semilla: {'; '.join(info['faltan'])}"
        run_state.update_stage(run_id, "activos", "blocked", mensaje[:300])
        pagina_local.abre(Path(info["pagina"]))
        raise RuntimeError(
            f"[ACTIVOS] {mensaje}. Escríbela en `Lote.elegidas` del guion de escena y vuelve a lanzar la etapa "
            f"(página: {info['pagina']})"
        )
    run_state.update_stage(run_id, "activos", "complete", _relativa_al_run(info["pagina"], state["output_dir"]))
    _invalida(
        run_id, ("escena", "render", "assembly"), "los activos se rehicieron: la escena hay que componerla otra vez"
    )
    print(
        f"[ACTIVOS] Done — {info['generados']} imagen(es) generada(s) · {info['recortados']} activo(s) recortado(s) · "
        f"{info['traidas']} traída(s) de la biblioteca del canal"
    )
    _para_en(run_id, "activos", info["pagina"], "escena", "parada 1")
    return info


def stage_escena(run_id: str) -> dict:
    """Pasa la PARADA 1 y termina en la 2: lo aprobado entra en la biblioteca del canal, y luego sonido, puesta en
    escena, comprobaciones, composición y los fotogramas clave."""
    state = run_state.load_run(run_id)
    _exige_motor_de_escena(state, "escena")
    _exige_parada(run_id, state, "activos", "escena", "parada 1")
    from lib.escena import etapas

    ep = _episodio(state)
    print("\n[ESCENA] Sonido, puesta en escena, comprobaciones y composición...")
    info = _corre(run_id, state, "escena", lambda: etapas.escena(ep))
    run_state.update_stage(run_id, "escena", "complete", _relativa_al_run(info["pagina"], state["output_dir"]))
    # En un rehecho la miniatura es un fotograma de esta composición (fila 246): si se rehace, la de antes ya no vale.
    rehecho = ("thumbnail",) if state.get("rehace") else ()
    _invalida(run_id, ("render", "assembly", *rehecho), "la escena se rehízo: hay que renderizarla otra vez")
    # Lo que la parada 2 enseñó, para que `render` compruebe que renderiza eso mismo.
    run_state.update_run(
        run_id,
        {
            "escena": {
                "huella_composicion": info["huella_composicion"],
                "huella_guion": info["huella_guion"],
                "defectos": sum(len(v) for v in info["defectos"].values()),
            }
        },
    )
    print(
        f"[ESCENA] Done — {info['planos']} planos · {info['audios']} pistas de audio · "
        f"{info['fotogramas']} fotogramas · {sum(len(v) for v in info['defectos'].values())} defecto(s) en las "
        "comprobaciones"
    )
    # Lo que la parada 1 aprobó ya está en la biblioteca del canal (fila 208): se dice, y lo que no entró, con motivo.
    bib = info["biblioteca"]
    print(
        f"[ESCENA] Biblioteca del canal: {len(bib['entran'])} imagen(es) nueva(s) · {len(bib['actualizadas'])} "
        f"actualizada(s) · {len(bib['no_entran'])} que no entra(n)"
        + (f" — van en git con el guion de escena: {bib['carpeta']}" if bib["entran"] or bib["actualizadas"] else "")
    )
    for nombre, motivo in bib["no_entran"].items():
        print(f"  · {nombre} no entra: {motivo}")
    _para_en(run_id, "escena", info["pagina"], "render", "parada 2")
    return info


def stage_render(run_id: str) -> str:
    """Renderiza la composición revisada en la parada 2 y deja `subir-al-canal/final.mp4` y `montaje.json`."""
    state = run_state.load_run(run_id)
    _exige_motor_de_escena(state, "render")
    _exige_parada(run_id, state, "escena", "render", "parada 2")
    from lib.escena import etapas

    ep = _episodio(state)
    huellas = state.get("escena") or {}
    print("\n[RENDER] Renderizando la composición revisada...")
    info = _corre(
        run_id,
        state,
        "render",
        lambda: etapas.render(
            ep,
            huella_composicion=huellas.get("huella_composicion") or "",
            huella_guion=huellas.get("huella_guion") or "",
        ),
    )
    final = str(info["salida"])
    run_state.update_stage(run_id, "render", "complete", final)
    # `assembly` es donde la subida y el panel de la semana buscan el vídeo final, lo haga el motor que lo haga.
    run_state.update_stage(run_id, "assembly", "complete", final)
    run_state.update_run(run_id, {"status": "assembled", "parada": None})
    resumen = info["montaje"]
    print(
        f"[RENDER] Done — {final} · {resumen['duracion_s']} s · {resumen['laminas']} láminas de voz · "
        f"{resumen['cronometraje']['factor_tiempo_real']}x tiempo real"
    )
    return final


def _avanza_escena(run_id: str) -> bool:
    """`--run-all` de un run del motor de escena: avanza hasta la siguiente parada. True si el vídeo ya está hecho.

    **Reanuda**: salta las etapas ya hechas, porque cada parada corta el run en dos llamadas y la voz o las láminas
    no se rehacen por volver a lanzarlo. Para rehacer una, `--stage`. **Nunca pasa una parada**: con los activos
    hechos y la escena sin hacer, o con la escena hecha y sin render, solo recuerda dónde está y vuelve a abrir la
    página; seguir es `--stage escena` o `--stage render`.
    """
    state = run_state.load_run(run_id)
    if not _hecha(state, "activos"):
        for etapa, funcion in (
            ("images", stage_images),
            ("tts", stage_tts),
            ("alinea", stage_alinea),
            ("activos", stage_activos),
        ):
            if not _hecha(run_state.load_run(run_id), etapa):
                funcion(run_id)
        return False
    for antes, etapa, cual in (("activos", "escena", "parada 1"), ("escena", "render", "parada 2")):
        if not _hecha(state, etapa):
            pagina = (state["stages"].get(antes) or {}).get("output") or ""
            print(f"\n[{cual.upper()}] El run sigue en la {cual}: --run-all no la pasa.")
            _para_en(run_id, antes, Path(state["output_dir"]) / pagina, etapa, cual)
            return False
    return True


def _fotograma_como_miniatura(state: dict, segundo: float, destino: str) -> dict:
    """El fotograma del segundo `segundo` de la escena renderizada, sin el karaoke, puesto como miniatura (fila 246)."""
    from lib.escena import etapas
    from lib.miniatura import desde_fotograma

    huella = (state.get("escena") or {}).get("huella_composicion") or ""
    foto = etapas.fotogramas_sin_karaoke(state["output_dir"], [segundo], huella_composicion=huella)
    return desde_fotograma(
        state["output_dir"],
        foto["fotogramas"][0],
        segundo,
        destino,
        huella_composicion=huella,
        herramientas=foto["herramientas"],
    )


def stage_thumbnail(run_id: str):
    """Compone la miniatura a partir de la lámina que declara el guion, o de un fotograma de la escena en un rehecho.
    NO genera ninguna imagen.

    Copia `slides/slide-NN.png` —o, en un rehecho, el fotograma del segundo `thumbnail_segundo` sin el karaoke
    (fila 246)—, la recorta al objeto y le compone el texto con tipografía real; el adaptador de imagen no interviene.
    Por qué no se genera, en el comentario de la guarda y en la fila 156 del addendum. Cuando ha pasado sus
    comprobaciones, lleva la marca de IA (OC1.5).
    """
    state = run_state.load_run(run_id)
    _exige_motor_de_escena(state, "thumbnail")
    run_dir = state["output_dir"]
    slides_path = Path(run_dir) / "slides.json"

    slides_json = json.loads(slides_path.read_text(encoding="utf-8"))

    # LA MINIATURA SALE SIEMPRE DE UNA LÁMINA DEL RUN — decisión del 12-09: «hazlo obligatorio, la miniatura
    # siempre de una lámina». Generarla aparte era la otra rama y se cerró después de medirla dos
    # episodios seguidos (addendum fila 156): es la única imagen del vídeo que **no** pasa por el
    # pipeline de la fila 147 —al modelo se le pide la pieza sin la referencia real y devuelve su
    # arquetipo, una jaula de pájaro donde va una jaula de gibbet— y tampoco pasa por ningún gate
    # humano. El gate automático no la cubre y está medido: `lineas_rojas` mide manchas de COLOR, así
    # que aprobó con `cumple: true` una figura humana decapitada en tinta sepia (fila 155). Una lámina
    # del run ya pasó por los ojos del usuario en el gate de láminas, y esa es toda la garantía.
    #
    # EN UN REHECHO SALE DE UN FOTOGRAMA DE SU ESCENA, NO DE LA LÁMINA (02-10, fila 246): la
    # lámina es la del vídeo viejo, así que su miniatura sería la que ya se vio. Sigue saliendo del run, que es
    # el motivo de la regla, y la escena también pasó por sus ojos, en la parada 2. Qué run es un rehecho lo
    # dice su estado (`rehace`, que escribía el script de rehechos del estudio, borrado en OC1.1), no el canal; en los
    # demás, la lámina.
    from lib.miniatura import CLAVE_SEGUNDO, desde_lamina, lamina_declarada, segundo_declarado

    rehace = state.get("rehace") or None
    try:
        segundo = segundo_declarado(slides_json)
        lamina_miniatura = None if rehace else lamina_declarada(slides_json)
    except ValueError as exc:
        run_state.update_stage(run_id, "thumbnail", "blocked", str(exc)[:300])
        raise

    if rehace and segundo is None:
        run_state.update_stage(run_id, "thumbnail", "blocked", f"slides.json sin {CLAVE_SEGUNDO}")
        raise ValueError(
            f"este run rehace {rehace.get('video_id') or 'un vídeo ya subido'}, y su miniatura sale de un fotograma de "
            f'su escena, no de la lámina, que es la del vídeo viejo. Escribe `"{CLAVE_SEGUNDO}": <segundo>` '
            'en slides.json con el instante del vídeo (420 o "7:00"), elegido con '
            "canales/<id>/contrato-miniatura.md, y vuelve a lanzar la etapa. Los segundos de cada fotograma de la "
            "parada 2 están en revision/fotogramas/."
        )
    if rehace and not _hecha(state, "render"):
        run_state.update_stage(run_id, "thumbnail", "blocked", "sin render no hay fotograma")
        raise ValueError(
            "la miniatura de un rehecho sale de un fotograma de la escena renderizada, y este run aún no tiene la "
            "etapa `render` hecha: renderízalo antes (tras la parada 2) y vuelve a lanzar la miniatura."
        )
    if not rehace and segundo is not None:
        run_state.update_stage(run_id, "thumbnail", "blocked", f"{CLAVE_SEGUNDO} fuera de un rehecho")
        raise ValueError(
            f"`slides.json` declara `{CLAVE_SEGUNDO}`, y la miniatura solo sale de un fotograma en los rehechos de "
            "un vídeo ya subido. Este run no rehace ningún vídeo, así que la saca de su lámina: quita la "
            "clave y declara `thumbnail_lamina`."
        )

    # Antes de esto la etapa aceptaba `thumbnail_prompt` como alternativa; y antes aún se marcaba
    # `skipped` y `run_all` subía el vídeo **sin miniatura y en silencio**. Las dos veces el defecto
    # fue el mismo: dejar que la pieza que decide el clic saliera sin que nadie la mirara.
    if not rehace and lamina_miniatura is None:
        disponibles = sorted(q.name for q in (Path(run_dir) / "slides").glob("slide-*.png"))
        run_state.update_stage(run_id, "thumbnail", "blocked", "slides.json sin thumbnail_lamina")
        raise ValueError(
            "`slides.json` no declara `thumbnail_lamina` y la miniatura sale SIEMPRE de una lámina del "
            'run. Escribe `"thumbnail_lamina": <número>` con la lámina que mejor represente la pieza y '
            "vuelve a lanzar la etapa. "
            + (f"Láminas de este run: {', '.join(disponibles)}." if disponibles else "Este run aún no tiene láminas.")
            + " `thumbnail_prompt` ya NO es una alternativa: lo fue hasta el 12-09 y con él salieron dos "
            "miniaturas seguidas rechazadas por dibujar otra pieza."
        )

    # F3.6: la miniatura NO es una lámina más. El prompt de escena se convierte al de MINIATURA
    # según `canales/<id>/contrato-miniatura.md` —objeto como retrato, fondo casi vacío, acento
    # saturado, rayado más grueso— y el texto se compone DESPUÉS con tipografía real, porque el
    # modelo hace garabatos en vez de letras (medido, ver el docstring de lib/miniatura.py).
    from lib import config
    from lib.config import CANAL_PERFIL
    from lib.miniatura import (
        CARPETA_DE_LA_FUENTE,
        CLAVE_FUENTE,
        canal_tiene_acento,
        compon_texto,
        comprueba,
        copia_la_fuente,
        desviacion_a_168px,
        fuente_declarada,
        informe,
        recorta_al_objeto,
        revisa_texto,
        texto_de_slides,
    )

    # Se comprueba ANTES de generar, y eso son 70 s de GPU que no se tiran: sin `thumbnail_text` la
    # miniatura no puede cumplir el contrato, así que generarla para suspenderla después solo gasta la
    # tarjeta. Antes se avisaba y se seguía, y con eso una miniatura sin texto se subía igual — que es
    # exactamente el defecto que se señaló y que esta feature venía a cerrar.
    texto = texto_de_slides(slides_json)
    if not texto:
        run_state.update_stage(run_id, "thumbnail", "blocked", "slides.json sin thumbnail_text")
        raise ValueError(
            "`slides.json` no trae `thumbnail_text` y la miniatura lo necesita: el contrato del canal "
            "pide un gancho de hasta 5 palabras que NO repita el título (canales/<id>/contrato-miniatura.md). "
            "sale del guion aprobado en el gate 1 — quien escribe el slides.json es quien sabe qué "
            "pregunta hace el vídeo—, así que no se deduce aquí. Añádelo y vuelve a lanzar la etapa."
        )
    try:
        revisa_texto(texto)
        # La letra del texto la declara el canal y sale de la biblioteca del estudio (OC1.4): sin ella no hay miniatura,
        # y se sabe antes de tocar nada.
        fuente = fuente_declarada(CANAL_PERFIL, CLAVE_FUENTE)
    except ValueError as exc:
        run_state.update_stage(run_id, "thumbnail", "blocked", str(exc)[:300])
        raise

    run_state.update_stage(run_id, "thumbnail", "in_progress")
    # Con el vídeo y el `.srt`, en `subir-al-canal/` (10-09).
    thumb_path = str(config.dir_subir_al_canal(run_dir, crear=True) / "thumbnail.png")
    if rehace:
        print(
            f"\n[THUMBNAIL] La miniatura sale del fotograma del segundo {segundo:g} de la escena, sin el karaoke "
            "(rehecho); no se genera ninguna"
        )
    else:
        print(f"\n[THUMBNAIL] La miniatura sale de la lámina {lamina_miniatura} del run, no se genera ninguna")

    try:
        try:
            if rehace:
                copiada = _fotograma_como_miniatura(state, segundo, thumb_path)
            else:
                copiada = desde_lamina(run_dir, lamina_miniatura, thumb_path)
        except Exception as exc:
            # En un rehecho falla también lo que toca la GPU (Chrome ocupado, la sonda): la etapa se queda parada con el
            # motivo, no a medias.
            run_state.update_stage(
                run_id, "thumbnail", "blocked", (str(exc).splitlines() or [type(exc).__name__])[0][:300]
            )
            raise
        print(f"  copiada de {Path(copiada['origen']).name} · el recorte y el texto van igual que siempre")
        # El modelo NO reencuadra por prompt (comprobado el 28-08: devolvió la plaza entera con
        # dos edificios y un marco decorativo). El encuadre se hace recortando al acento, que en
        # este canal ES el objeto — y de paso se lleva el marco y los garabatos de las esquinas.
        # El objetivo sale de las láminas del propio run, que es lo que hace el recorte comparable
        # entre canales sin tocar un número absoluto.
        import statistics

        from lib.miniatura import OBJETIVO_DEL_RECORTE, caja_del_objeto

        # Que el objeto se pueda localizar por su color lo decide el CANAL, no esta etapa: con
        # `imagen.acento_de_color` en falso no se recorta, porque la mancha más saturada de una imagen
        # a color no es el objeto y el recorte saldría al azar.
        acento = canal_tiene_acento(CANAL_PERFIL)
        previas = sorted(str(q) for q in (Path(run_dir) / "slides").glob("slide-*.png"))
        objetivo = None
        if previas and acento:
            objetivo = statistics.median(caja_del_objeto(q)[1] for q in previas) * OBJETIVO_DEL_RECORTE
        recorte = recorta_al_objeto(thumb_path, objetivo=objetivo, hay_acento=acento)
        if recorte["recortado"]:
            print(
                f"  recortado al objeto: ocupaba el {recorte['ocupacion_antes'] * 100:.1f} % del "
                f"cuadro y ahora el {recorte['ocupacion_despues'] * 100:.1f} %"
            )
        else:
            print(f"  NO se ha recortado: {recorte['por_que_no']}")

        # La desviación se mide AQUÍ, antes de componer el texto: medida después incluye el texto —que
        # ya tiene su propio gate— y entonces no dice nada del encuadre. Las dos van al informe.
        desviacion_sin_texto = desviacion_a_168px(thumb_path)

        # La letra sale en la imagen que se publica, así que su copia entra en la procedencia del run (decisión 5).
        copia_la_fuente(fuente, Path(run_dir) / CARPETA_DE_LA_FUENTE, etapa="thumbnail")
        medido_texto = compon_texto(thumb_path, texto, fuente=fuente)
        print(
            f"  texto compuesto: {medido_texto['texto']!r} · {medido_texto['fuente']} · cuerpo "
            f"{medido_texto['cuerpo_px']} px"
        )
        print(
            f"  altura de mayúscula: {medido_texto['altura_mayuscula_px']} px "
            f"(={medido_texto['altura_mayuscula_a_168']} px a 168) · "
            f"contraste {medido_texto['contraste_con_el_fondo']}:1 · ocupa el "
            f"{medido_texto['ancho_del_texto_pct'] * 100:.1f} % del ancho"
        )
    finally:
        _sync_assets(state, "thumbnail")

    # Lo que suspende es el TEXTO —que quepa, que se lea y que contraste, los tres medidos—, no el
    # encuadre: las láminas de este canal ya son retratos de objeto, así que su rango se solapa con el
    # de la miniatura y el umbral que se probó era un gate falso (las cuatro métricas, en el docstring
    # de lib/miniatura.py). El encuadre se mide y se publica.
    laminas = sorted(str(p) for p in (Path(run_dir) / "slides").glob("slide-*.png"))
    veredicto = comprueba(
        thumb_path,
        texto=texto,
        laminas=laminas,
        medido_texto=medido_texto,
        desviacion_sin_texto=desviacion_sin_texto,
    )
    veredicto["recorte"] = recorte
    # De dónde salió el píxel, en el mismo fichero que lo medido: una miniatura sacada de una lámina y
    # una generada aparte se distinguen aquí sin abrir el registro de procedencia.
    # La ruta va RELATIVA al run, como el resto del expediente (recomendación del auditor): así el
    # `miniatura.json` se sigue leyendo si el run cambia de carpeta.
    if rehace:
        veredicto["de_donde_sale"] = {
            "fotograma_del_run_s": copiada["segundo"],
            "origen": _relativa_al_run(copiada["origen"], run_dir),
            "sin_karaoke": True,
            "huella_composicion": copiada["procedencia"]["huella_composicion"],
            "rehace": rehace.get("video_id"),
        }
    else:
        veredicto["de_donde_sale"] = {
            "lamina_del_run": copiada["lamina"],
            "origen": _relativa_al_run(copiada["origen"], run_dir),
        }
    informe(veredicto, Path(run_dir) / "miniatura.json")
    medido = veredicto["reportado_no_es_gate"]
    print(
        f"  [MEDIDO, no suspende] el objeto alcanza el {medido['alto_del_objeto'] * 100:.1f} % del "
        f"alto del cuadro y en las láminas del run "
        f"{(medido['alto_del_objeto_en_las_laminas'] or 0) * 100:.1f} %"
    )
    for fallo in veredicto["fallos"]:
        print(f"  [CONTRATO] {fallo}")
    # Suspende de verdad, igual que las líneas rojas. Avisar y seguir era lo que dejaba subir una
    # miniatura ilegible: `run_all` llama a la subida justo después de esta etapa.
    if not veredicto["cumple"]:
        run_state.update_stage(run_id, "thumbnail", "blocked", "; ".join(veredicto["fallos"])[:300])
        raise ValueError(
            "la miniatura NO cumple el contrato del canal y por eso el run se para aquí:\n  - "
            + "\n  - ".join(veredicto["fallos"])
            + f"\nLo medido está en {Path(run_dir) / 'miniatura.json'}. Ajusta `thumbnail_text` en "
            "slides.json (hasta 5 palabras) o cambia `thumbnail_lamina` por otra lámina del run, y "
            "vuelve a lanzar la etapa."
        )

    # La miniatura es la pieza MÁS pública del vídeo y la única imagen del run que no pasa
    # por el lote de `stage_images`, así que necesita su propia guarda: es justamente la que
    # decide la restricción por edad en el feed.
    try:
        lineas_rojas.exige([thumb_path], etapa="thumbnail")
    except lineas_rojas.LineaRojaError as exc:
        run_state.update_stage(run_id, "thumbnail", "blocked", str(exc).splitlines()[0])
        raise

    # LA MARCA DE IA (OC1.5, art. 50.2 del AI Act). La miniatura ya ha pasado el contrato y las líneas rojas, así que se
    # marca con Video Seal y se firma con C2PA en su sitio. Su registro va a `miniatura.json` y, por la entrada de la
    # miniatura en el registro de imágenes del run, a `assets.json`. La subida se niega sin él.
    from lib import marca_ia
    from lib.miniatura import PESO_MAXIMO_BYTES, apunta_la_marca

    try:
        marca = marca_ia.marca_imagen(thumb_path, thumb_path)
        peso = Path(thumb_path).stat().st_size
        if peso > PESO_MAXIMO_BYTES:
            raise marca_ia.ErrorDeMarca(
                f"la miniatura marcada pesa {peso / 1024 / 1024:.2f} MB y YouTube admite "
                f"{PESO_MAXIMO_BYTES // 1024 // 1024} MB: cambia `thumbnail_lamina` por otra lámina del run"
            )
        apunta_la_marca(run_dir, thumb_path, marca)
    except marca_ia.ErrorDeMarca as exc:
        run_state.update_stage(run_id, "thumbnail", "blocked", (str(exc).splitlines() or ["marca de IA"])[0][:300])
        raise
    finally:
        _sync_assets(state, "thumbnail")
    veredicto["marca_ia"] = marca
    informe(veredicto, Path(run_dir) / "miniatura.json")
    print(
        f"  marca de IA: C2PA {marca['comprobacion']['c2pa']['state']} · Video Seal "
        f"{marca['comprobacion']['image']['matches']}/256 bits · señal {marca_ia.SENAL} · {marca['segundos']} s"
    )

    run_state.update_stage(run_id, "thumbnail", "complete", thumb_path)
    print(f"[THUMBNAIL] Done — {thumb_path}")
    return thumb_path


def _fecha_de_grabacion(state: dict) -> str:
    """La «Fecha de grabación» de Studio, en RFC 3339, sacada de cuándo se creó el run.

    **Un vídeo sintético no se «graba», así que hay que elegir qué significa esa fecha**, y lo que
    tiene sentido es cuándo se produjo. El run lleva su `created_at`, que es el instante en que
    empezó a producirse: sale del propio expediente, no de un reloj suelto, así que dos subidas del
    mismo run declaran la misma fecha aunque se suban con días de diferencia.

    Solo la fecha, con la hora a cero: YouTube muestra el día y la hora no dice nada aquí. Si el
    estado no la trae —un run muy viejo, un fichero editado a mano— se devuelve cadena vacía y el
    campo no se manda, que es lo que hacía antes.
    """
    crudo = str(state.get("created_at") or "").strip()
    if not crudo:
        return ""
    try:
        return datetime.fromisoformat(crudo).strftime("%Y-%m-%dT00:00:00Z")
    except ValueError:
        return ""


def _registro_de_la_marca(run_dir: str | Path, expediente: str) -> dict | None:
    """El registro de la marca de IA que apuntó su etapa: `montaje.json` (el vídeo) o `miniatura.json`."""
    try:
        datos = json.loads((Path(run_dir) / expediente).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return datos.get("marca_ia") if isinstance(datos, dict) else None


def _exige_la_marca(run_dir: str | Path, video: str, miniatura: str) -> None:
    """Para la subida si el vídeo, o la miniatura que va con él, no lleva su marca de IA detectada (OC1.5).

    La miniatura se mira si va a subir: la misma condición que usa `youtube_client.upload_video`. Dice qué etapa volver
    a lanzar. Lo comprueba también `set_thumbnail`.
    """
    from lib import marca_ia

    if video:
        marca_ia.exige_marcado(
            video, _registro_de_la_marca(run_dir, provenance.ASSEMBLY_SUMMARY_FILENAME), rehacer="`--stage render`"
        )
    if miniatura and Path(miniatura).exists():
        marca_ia.exige_marcado(
            miniatura, _registro_de_la_marca(run_dir, "miniatura.json"), rehacer="`--stage thumbnail`"
        )


def stage_upload(run_id: str, forzar: bool = False):
    """Prepara la subida y, si `YOUTUBE_SUBIDA_API=1`, sube el vídeo a YouTube como borrador privado. Idempotente.

    **Dos modos y una sola preparación** (OC1.8, fila 315). Lo que se hace en local corre en los dos: los `.srt` al día,
    los metadatos traducidos, la descripción compuesta, la marca de IA, la procedencia y la declaración de IA. Después:

    - **a mano**, que es lo de serie: ni token ni red. La etapa queda `skipped` y `subir-al-canal/LEEME.html` lleva la
      descripción compuesta y los pasos de Studio. Así el primer vídeo no depende de configurar Google Cloud;
    - **por la API**: sube el borrador privado con `containsSyntheticMedia`. Sin el OAuth completo se niega antes de
      preparar nada (`youtube_client.subida_por_la_api`).

    La guarda del principio no es prudencia: subir es **irreversible**, y rehacer el montaje tras un
    arreglo y relanzar `--run-all` es el flujo normal de este proyecto. Sin ella, el segundo
    `--run-all` deja un borrador DUPLICADO en el canal, y eso además roza el punto de la lista negra
    sobre repetir llamadas contra la API de YouTube. Lo cazó la auditoría de F3.3: en la primera
    subida real el duplicado lo evitó el cuidado del operador, no el código.
    """
    # `.get` en cadena y no índices: un estado editado a mano puede venir sin `stages` o con la
    # etapa como texto, y la guarda de idempotencia es lo ÚLTIMO que puede reventar aquí — si se cae,
    # se sube un segundo borrador al canal (auditoría del 10-09, MEDIO).
    estado = run_state.load_run(run_id)
    # Un run del motor retirado no se sube, ni con `--forzar-subida`: sería resubir un vídeo viejo (R3 de F6.7).
    _exige_motor_de_escena(estado, "upload")
    etapas = estado.get("stages") or {}
    ya_subido = etapas.get("upload")
    if not isinstance(ya_subido, dict):
        ya_subido = {}
    if ya_subido.get("status") == "complete" and not forzar:
        try:
            previo = json.loads(ya_subido.get("output") or "{}")
        except (json.JSONDecodeError, TypeError):
            previo = {}
        if isinstance(previo, dict) and previo.get("video_id"):
            print("\n[UPLOAD] Este run YA está subido: no se sube otra vez.")
            print(f"  vídeo  : {previo.get('url', '(sin url en el estado)')}")
            print(f"  Studio : {previo.get('studio_url', '')}")
            print("  si de verdad quieres un segundo borrador, usa --forzar-subida")
            return previo

    # El modo va antes de preparar nada: un interruptor que no se entiende, o la API encendida sin el OAuth completo,
    # paran aquí con su motivo, antes de componer la descripción y sin tocar el estado del run, porque lo que falla es
    # el `.env` y no el run.
    from lib.youtube_client import subida_por_la_api

    por_la_api = subida_por_la_api()
    # Un run ya subido solo llega hasta aquí con `--forzar-subida`, que pide un segundo borrador POR LA API. A mano no
    # hay segundo borrador que hacer, y reescribir el LEEME sin su enlace de Studio invitaría a subir un duplicado
    # (R3 de progress/review_OC1.8.md).
    if not por_la_api and ya_subido.get("status") == "complete":
        try:
            previo = json.loads(ya_subido.get("output") or "{}")
        except (json.JSONDecodeError, TypeError):
            previo = {}
        if isinstance(previo, dict) and previo.get("video_id"):
            print(
                "\n[UPLOAD] Este run YA está subido por la API, y la subida por la API está apagada: no se hace nada."
            )
            print(f"  vídeo  : {previo.get('url', '(sin url en el estado)')}")
            print("  --forzar-subida hace un segundo borrador por la API: necesita YOUTUBE_SUBIDA_API=1")
            return previo

    state = run_state.load_run(run_id)
    run_dir = state["output_dir"]
    slides_path = Path(run_dir) / "slides.json"

    slides_json = json.loads(slides_path.read_text(encoding="utf-8"))

    final_video = state["stages"]["assembly"].get("output", "")
    if not final_video or not Path(final_video).exists():
        raise FileNotFoundError("Final video not found. Run assembly stage first.")

    # LOS `.srt` QUE EL USUARIO ADJUNTA A MANO (F7.11, fila 265): el del guion y las traducciones del canal. Se
    # comprueba aquí, antes de componer la descripción y de gastar cuota: si falta una traducción, si el `.srt` de
    # origen cambió después de traducirlo o si una traducción se tocó después de escribirla, no se sube nada.
    from lib import traduccion
    from lib.config import CANAL_PERFIL, NARRATION_LANG, SUBTITLE_LANG
    from lib.publicacion import exige_metadatos_traducidos

    srts = traduccion.exige_al_dia(run_dir, CANAL_PERFIL, origen=SUBTITLE_LANG)
    # EL TÍTULO Y LA DESCRIPCIÓN TRADUCIDOS (fila 285), con el mismo criterio: si el canal los declara y el guion no los
    # trae enteros, no se compone nada ni se gasta cuota. El original está en el idioma de la narración.
    traducidos = exige_metadatos_traducidos(slides_json, CANAL_PERFIL, origen=NARRATION_LANG)

    # LA DESCRIPCIÓN SE COMPONE AQUÍ, y hasta el 12-09 era el paso 8 del skill, hecho a mano
    # (addendum fila 154): ninguna etapa llamaba a `scripts/compone_descripcion.py`, así que con la
    # subida activada el run moría en `revisa_descripcion` con `<<CAPITULOS>>` y `<<BIBLIOGRAFIA>>`
    # literales. La guarda hacía su trabajo; lo que faltaba era el paso anterior. Va en la subida y no
    # en el montaje porque los capítulos salen de `montaje.json` ya escrito, y aquí vale igual para
    # `--stage upload` suelto que dentro de `--run-all`. Es idempotente: un reintento no vuelve a
    # componer.
    from scripts.compone_descripcion import compon

    fichas = _exige_fichas_de_la_bibliografia(run_id, slides_json)
    medido = compon(run_id, fichas, traducidos=traducidos)
    if medido["compuesta"]:
        print(
            f"\n[UPLOAD] Descripción compuesta: {medido['capitulos']} capítulos con el minutaje real y "
            f"{medido['caracteres']} caracteres"
        )
        for aviso in medido["avisos"] + medido["avisos_internos"]:
            print(f"  [AVISO] {aviso}")
        for disclaimer in medido["disclaimers"]:
            print(f"  [DISCLAIMER de ficha — el guion tiene que decirlo en los primeros 30 s] {disclaimer}")
    for idioma, suyo in (medido.get("traducidas") or {}).items():
        print(f"[UPLOAD] Descripción en «{idioma}» compuesta con el mismo minutaje: {suyo['caracteres']} caracteres")
    # Las descripciones viven en `slides.json`, así que lo que hay en memoria acaba de quedarse viejo. Se relee siempre:
    # la traducida puede componerse aunque la original ya lo estuviera.
    slides_json = json.loads(slides_path.read_text(encoding="utf-8"))

    title = slides_json.get("title", state["title"])
    tags = slides_json.get("tags", [])
    thumb_path = state["stages"]["thumbnail"].get("output", "")

    # Nada sube sin su marca de IA detectada (OC1.5, art. 50.2 del AI Act), ni con `--forzar-subida`: es local y
    # no gasta cuota, así que va antes de todo lo que sí la gasta.
    _exige_la_marca(run_dir, final_video, thumb_path)

    # Aquí es donde el registro de procedencia tiene dientes: subir un vídeo cuyo material no
    # se puede justificar es el modo de fallo que la decisión cerrada 5 quiere evitar (un
    # error de licencia replicado a volumen). Si no cuadra, no se sube.
    provenance.require_complete(run_dir, run_id=run_id, titulo=title)

    # La descripción conforme se DERIVA del assets.json que acaba de pasar ese control: de ahí
    # salen los modelos reales que hay que declarar (decisión 7). No es una plantilla.
    # Los idiomas salen de `lib.config`, que ya aplica la precedencia entorno > perfil > defecto.
    # Rederivarlos del perfil crudo tenía dos fallos silenciosos, los dos cazados por la auditoría:
    # con `IDIOMA_SUBTITULOS` puesto, el `.srt` no se encontraba y desaparecía del recordatorio; y la
    # declaración legal podía salir en un idioma distinto al de la narración SIN disparar su aviso.
    from lib.publicacion import (
        avisa_de_narracion,
        descripcion_conforme,
        descripciones_traducidas,
        guia_de_subida,
        incidencias_del_run,
    )

    perfil = CANAL_PERFIL
    description, avisos = descripcion_conforme(
        base=slides_json.get("description", ""),
        run_dir=run_dir,
        perfil=perfil,
        idioma=NARRATION_LANG,
    )
    # La versión traducida, con su declaración de IA en su idioma, se prepara ANTES de subir: si falla, falla sin cuota.
    # No viaja a YouTube (fila 285): va al LEEME, para pegarla a mano en Studio.
    traducidas, avisos_traducidos = descripciones_traducidas(
        slides_json, run_dir=run_dir, perfil=perfil, idiomas=traducidos
    )
    for aviso in avisos + [a for a in avisos_traducidos if a not in avisos]:
        print(f"  [AVISO] {aviso}")
    # Una descripción con `<<CAPITULOS>>` literal tampoco se pega a mano: la guarda que la API pasa antes del token
    # vale para los dos modos.
    from lib.youtube_client import revisa_descripcion

    revisa_descripcion(description)

    if not por_la_api:
        # A MANO (lo de serie): todo lo de arriba ya se ha comprobado, y aquí no se pide token ni se sale a la red. El
        # LEEME lleva la descripción compuesta, con la declaración de IA, y los pasos de Studio. `run_all` no la pisa.
        from lib.config import YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
        from lib.youtube_client import campos_de_studio

        incidencias = incidencias_del_run(run_dir)
        avisa_de_narracion(incidencias)
        guia_de_subida(
            run_dir,
            titulo=title,
            descripcion=description,
            incidencias=incidencias,
            traducidas=traducidas,
            a_mano=campos_de_studio(),
        )
        print("\n[UPLOAD] Listo para subirlo a mano en Studio: el motor no ha hablado con YouTube")
        # Hasta OC1.8 estas tres claves encendían la subida solas: quien las tenga puestas tiene que enterarse.
        if all([YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN]):
            print(
                "  [AVISO] las claves OAuth están en el .env y YOUTUBE_SUBIDA_API está vacío: para que suba el motor, "
                "escribe YOUTUBE_SUBIDA_API=1"
            )
        # Con motivo: los dos caminos que dejan la etapa en `skipped` —este y `--sin-subida`— tienen que distinguirse
        # en el estado del run, o el resumen final se atribuye el ajeno. Si el run ya estaba subido (solo se llega con
        # `--forzar-subida`), `update_stage` no pisa su `video_id`.
        run_state.update_stage(
            run_id, "upload", "skipped", "a mano en Studio (YOUTUBE_SUBIDA_API vacío): los pasos, en LEEME.html"
        )
        return None

    run_state.update_stage(run_id, "upload", "in_progress")

    from lib.youtube_client import upload_video as yt_direct_upload

    canal = (perfil.get("publicacion") or {}).get("canal_youtube") or "(canal sin registrar)"
    print(f"\n[UPLOAD] Subiendo a YouTube como borrador privado — canal {canal}")

    # Los .srt no se pueden subir por API con nuestros permisos; se pasan para que el resultado los
    # señale y no se olvide adjuntarlos en Studio (ver docstring de lib/youtube_client.py). Son los que
    # `traduccion.exige_al_dia` dio por buenos arriba: el de SUBTITLE_LANG y sus traducciones.
    result = yt_direct_upload(
        file_path=final_video,
        title=title,
        description=description,
        tags=tags,
        thumbnail_path=thumb_path,
        srt_paths=[str(s) for s in srts],
        fecha_de_grabacion=_fecha_de_grabacion(state),
    )
    if avisos:
        result["avisos"] = avisos

    run_state.update_stage(run_id, "upload", "complete", json.dumps(result))
    run_state.update_run(run_id, {"status": "uploaded"})
    # La carpeta de lo publicable se explica a sí misma: qué archivo es cuál y qué queda a mano
    # (10-09). Se escribe DESPUÉS de subir porque hasta aquí no se conoce el `video_id` ni
    # la descripción compuesta, que son lo que el usuario necesita copiar.
    incidencias = incidencias_del_run(run_dir)
    avisa_de_narracion(incidencias)
    guia_de_subida(
        run_dir,
        titulo=title,
        descripcion=description,
        video_id=result.get("video_id", ""),
        pendiente_a_mano=result.get("pendiente_a_mano"),
        incidencias=incidencias,
        traducidas=traducidas,
    )
    print("[UPLOAD] Hecho — borrador privado con el flag del Art. 50")
    print(f"  revísalo en Studio: {result['studio_url']}")
    return result


def set_thumbnail(run_id: str) -> bool:
    """Pone la miniatura del run en el vídeo que ya subió, sin volver a subir el vídeo.

    Existe porque la subida es idempotente a propósito y la miniatura falla por causas que se
    arreglan DESPUÉS: el canal necesita estar verificado por teléfono, y eso suele pasar tras la
    primera subida. Sin esta puerta, la única salida era arrastrar el fichero en Studio.

    **No toca la visibilidad**: el vídeo sigue siendo el borrador privado que era, así que esto no
    roza el gate 2. Y las líneas rojas se vuelven a comprobar aquí porque la miniatura puede haberse
    regenerado desde la etapa que las comprobó — es la imagen más pública del vídeo.
    """
    state = run_state.load_run(run_id)
    try:
        subido = json.loads(state["stages"]["upload"].get("output") or "{}")
    except json.JSONDecodeError:
        subido = {}
    video_id = subido.get("video_id")
    if not video_id:
        print(f"[MINIATURA] El run {run_id} no tiene vídeo subido: nada que hacer.")
        return False

    # Pone la miniatura por la API, así que obedece al mismo interruptor que la subida: apagada, ni token ni red (R2 de
    # progress/review_OC1.8.md).
    from lib.youtube_client import SubidaNoConfigurada, subida_por_la_api

    try:
        por_la_api = subida_por_la_api()
    except SubidaNoConfigurada as e:
        print(f"[MINIATURA] {e}")
        return False
    if not por_la_api:
        print(
            "[MINIATURA] La subida por la API está apagada (YOUTUBE_SUBIDA_API vacío): pon la miniatura a mano en "
            "Studio, o escribe YOUTUBE_SUBIDA_API=1 para que la ponga el motor."
        )
        return False

    thumb = state["stages"]["thumbnail"].get("output", "")
    if not thumb or not Path(thumb).exists():
        print("[MINIATURA] No hay miniatura en el run: lanza antes --stage thumbnail.")
        return False

    lineas_rojas.exige([thumb], etapa="thumbnail")
    # Y su marca de IA (OC1.5): la miniatura se puede haber rehecho después de subir el vídeo.
    _exige_la_marca(state["output_dir"], "", thumb)

    from lib.youtube_client import pon_miniatura

    print(f"\n[MINIATURA] Poniéndola en {subido.get('url', video_id)} (sigue siendo privado)")
    puesta, pendiente = pon_miniatura(video_id, thumb)

    # El estado se actualiza para que el recordatorio de «pendiente a mano» deje de mentir.
    subido["miniatura_puesta"] = puesta
    restantes = [p for p in subido.get("pendiente_a_mano", []) if p.get("que") != "miniatura"]
    if pendiente:
        restantes.append(pendiente)
    subido["pendiente_a_mano"] = restantes
    run_state.update_stage(run_id, "upload", "complete", json.dumps(subido))

    if puesta:
        print(f"  compruébala en Studio: {subido.get('studio_url', '')}")
    return puesta


def rehace_guia(run_id: str) -> bool:
    """Reescribe `subir-al-canal/LEEME.html` de un run YA subido, sin volver a subirlo (fila 285).

    Existe para los runs subidos antes de que el LEEME llevara el título y la descripción traducidos: se añaden los
    campos traducidos a su `slides.json` y esto recompone las descripciones y reescribe la página. **No llama a la API
    de YouTube ni toca el estado del run**: el título y el `video_id` salen de lo que la subida dejó escrito, y la
    descripción original se vuelve a derivar igual que al subir. Si no coincide con la que enseñaba el LEEME anterior,
    que es la que se subió, lo avisa: el `assets.json` ha cambiado desde la subida.
    """
    from lib.config import CANAL_PERFIL, NARRATION_LANG
    from lib.publicacion import (
        descripcion_conforme,
        descripcion_del_leeme,
        descripciones_traducidas,
        exige_metadatos_traducidos,
        guia_de_subida,
        incidencias_del_run,
    )
    from scripts.compone_descripcion import compon, fichas_del_guion

    state = run_state.load_run(run_id)
    try:
        subido = json.loads(((state.get("stages") or {}).get("upload") or {}).get("output") or "{}")
    except (json.JSONDecodeError, TypeError):
        subido = {}
    if not isinstance(subido, dict) or not subido.get("video_id"):
        print(f"[LEEME] El run {run_id} no está subido: su LEEME lo escribe la etapa de subida.")
        return False

    run_dir = state["output_dir"]
    slides_path = Path(run_dir) / "slides.json"
    slides_json = json.loads(slides_path.read_text(encoding="utf-8"))
    traducidos = exige_metadatos_traducidos(slides_json, CANAL_PERFIL, origen=NARRATION_LANG)
    medido = compon(run_id, fichas_del_guion(slides_json), traducidos=traducidos)
    for idioma, suyo in medido["traducidas"].items():
        print(f"[LEEME] Descripción en «{idioma}» compuesta con el mismo minutaje: {suyo['caracteres']} caracteres")
    slides_json = json.loads(slides_path.read_text(encoding="utf-8"))

    descripcion, avisos = descripcion_conforme(
        base=slides_json.get("description", ""), run_dir=run_dir, perfil=CANAL_PERFIL, idioma=NARRATION_LANG
    )
    traducidas, avisos_traducidos = descripciones_traducidas(
        slides_json, run_dir=run_dir, perfil=CANAL_PERFIL, idiomas=traducidos
    )
    anterior = descripcion_del_leeme(run_dir)
    if anterior is not None and anterior != descripcion:
        avisos.append(
            "la descripción original que sale ahora NO es la del LEEME anterior, que es la que se subió: el run ha "
            "cambiado desde la subida. En YouTube sigue la de antes"
        )
    for aviso in avisos + [a for a in avisos_traducidos if a not in avisos]:
        print(f"  [AVISO] {aviso}")

    guia_de_subida(
        run_dir,
        titulo=subido.get("title") or slides_json.get("title", state["title"]),
        descripcion=descripcion,
        video_id=subido["video_id"],
        pendiente_a_mano=subido.get("pendiente_a_mano"),
        incidencias=incidencias_del_run(run_dir),
        traducidas=traducidas,
    )
    return True


def _abre_la_guia(state: dict) -> None:
    """Abre `subir-al-canal/LEEME.html` en el navegador al terminar un `--run-all`, si existe.

    Regla del 31-08 (addendum fila 40): donde interviene una persona se le da un entregable que
    se abre con doble clic — y el 12-09, al acordar «el pipeline siempre termina», la revisión pasa a
    ser UNA, al final, sobre esa página. Que se abra sola es lo que convierte «ya está» en «míralo».
    Solo en Windows y nunca falla: un run desatendido no puede morir por no tener escritorio.
    """
    try:
        from lib import config

        ruta = config.dir_subir_al_canal(state["output_dir"], crear=False) / "LEEME.html"
        if not ruta.exists():
            return
        print(f"  guía del episodio: {ruta}")
        import os

        if hasattr(os, "startfile"):
            os.startfile(str(ruta))  # noqa: S606 — abrir un HTML local para el operador
    except Exception as e:  # abrir la guía es cortesía, no una etapa
        print(f"  [AVISO] la guía no se pudo abrir sola: {e}")


def run_all(run_id: str, sin_subida: bool = False, forzar_subida: bool = False):
    """Execute all stages in sequence.

    **`forzar_subida` existe porque el flag se aceptaba y NO hacía nada** (14-09-2026). El CLI
    declaraba `--forzar-subida`, `--run-all` lo admitía sin protestar y aquí dentro se llamaba a
    `stage_upload(run_id)` sin él, así que la guarda de idempotencia paraba la subida y el vídeo
    rehecho se quedaba en disco mientras el canal conservaba el viejo. Se descubrió rehaciendo un
    episodio entero: 25 min de máquina y el log diciendo «Este run YA está subido». Un flag inerte
    es peor que uno ausente — con uno ausente el comando falla y te enteras.

    `sin_subida` produce el vídeo y **no toca la etapa de subida**. Hasta F2.5 la subida se
    saltaba sola por no haber credenciales OAuth, lo cual funciona pero no es una garantía:
    en cuanto el Sprint 3 configure el OAuth, un `--run-all` a secas volvería a intentarla.
    Con el flag, «producir sin publicar» es una operación explícita, que es lo que pide el
    «Hecho cuando» del Sprint 2 y lo que la decisión cerrada 2 espera del sistema — nada
    sale sin un clic humano, y la subida es siempre borrador privado.
    """
    state = run_state.load_run(run_id)
    print(f"\n{'=' * 60}")
    print("YT VIDEO FACTORY — Full Pipeline")
    print(f"Run: {run_id}")
    print(f"Title: {state['title']}")
    print(f"Voice: {state['voice']} | Motor: {run_state.motor_de(state)}")
    _exige_motor_de_escena(state, "run-all")
    if not sin_subida:
        # El modo de la subida se mira ANTES de renderizar: con la API encendida y el OAuth incompleto, la negativa
        # llegaba después del render entero (R5 de progress/review_OC1.8.md). `stage_upload` lo vuelve a mirar.
        from lib.youtube_client import subida_por_la_api

        subida_por_la_api()
    if sin_subida:
        # La ruta sale de `config`, que ya la resuelve para el canal activo: escrita a mano decía
        # la del primer canal produjeras donde produjeras.
        from lib.config import CANAL_VIDEOS_DIR

        print(f"Subida: OMITIDA por --sin-subida (el vídeo se queda en {CANAL_VIDEOS_DIR})")
    print(f"{'=' * 60}")

    run_state.update_run(run_id, {"status": "in_progress"})

    # El motor de escena se detiene en sus dos paradas: `_avanza_escena` llega hasta la siguiente y solo deja seguir
    # hacia la miniatura y la subida cuando el render ya está hecho (F6.2d).
    if not _avanza_escena(run_id):
        return
    stage_thumbnail(run_id)
    if sin_subida:
        # `--sin-subida` NO puede pisar una subida que ya ocurrió. El registro de la etapa es el
        # ÚNICO sitio máquina-legible donde vive el `video_id`, y es lo que lee la guarda de
        # `stage_upload`: sobrescribirlo con `skipped` borra la memoria de que este run ya está en
        # el canal y **el siguiente `--run-all` sube un duplicado**. Cazado en la segunda pasada de
        # la auditoría de F3.3, con la ironía de que el que caía era el operador prudente: quien usa
        # `--sin-subida` lo hace precisamente para no volver a subir.
        # Se lee igual que en `stage_upload`: con `.get` en cadena y tolerando un estado editado a
        # mano. Es el hermano de esa guarda —el auditor del 10-09 lo encontró sin arreglar— y está en
        # el camino que existe precisamente para NO duplicar un borrador.
        etapas = run_state.load_run(run_id).get("stages") or {}
        ya = etapas.get("upload")
        if not isinstance(ya, dict):
            ya = {}
        try:
            previo = json.loads(ya.get("output") or "{}")
        except (json.JSONDecodeError, TypeError):
            previo = {}
        if not isinstance(previo, dict):
            previo = {}
        if ya.get("status") == "complete" and previo.get("video_id"):
            print("\nSubida: ya estaba subida antes, y --sin-subida NO borra ese registro")
            print(f"  vídeo: {previo.get('url', '(sin url en el estado)')}")
        else:
            run_state.update_stage(run_id, "upload", "skipped", "omitida a propósito con --sin-subida")
    else:
        stage_upload(run_id, forzar=forzar_subida)

    # `uploaded` dice más que `complete` y no se pisa: es el marcador que leerá `metricas.py` para
    # saber qué runs tienen vídeo en el canal. Degradarlo a `complete` no causaba duplicados —la
    # guarda mira la etapa, no el run— pero borraba información. Cazado en la auditoría de F3.3.
    if run_state.load_run(run_id).get("status") != "uploaded":
        run_state.update_run(run_id, {"status": "complete"})
    state = run_state.load_run(run_id)

    upload_status = state["stages"]["upload"].get("status", "unknown")
    # El mensaje sale del MOTIVO registrado, no del status: `skipped` lo escriben los dos
    # caminos —el flag y la falta de credenciales— y decidirlo por el status hacía que un
    # `--run-all` sin flag dijera «skipped on purpose (--sin-subida)» sin que nadie lo pasara.
    upload_motivo = state["stages"]["upload"].get("output", "")

    # «EL PIPELINE SIEMPRE TERMINA» (12-09; addendum fila 152). La guía de la carpeta con el
    # informe de incidencias —«esto salió peor de lo pedido»— tiene que existir SIEMPRE, se suba o
    # no: es el único sitio donde el usuario revisa el episodio, y hasta hoy solo la escribía la etapa de
    # subida, así que un `--sin-subida` la dejaba sin escribir. Si la subida ya la escribió, trae el
    # `video_id` y la descripción compuesta y no se pisa. Y se ABRE sola: los entregables que toca
    # una persona se abren, no se le da una ruta para buscar.
    # Desde OC1.8 la etapa la escribe en los dos modos, también a mano (`skipped`, con la descripción compuesta y los
    # pasos de Studio): esta de reserva, con la descripción en bruto del guion, queda solo para `--sin-subida`.
    if sin_subida and upload_status != "complete":
        try:
            from lib.publicacion import avisa_de_narracion, guia_de_subida, incidencias_del_run

            run_dir = state["output_dir"]
            try:
                descripcion = json.loads((Path(run_dir) / "slides.json").read_text(encoding="utf-8")).get(
                    "description", ""
                )
            except (OSError, json.JSONDecodeError):
                descripcion = ""
            incidencias = incidencias_del_run(run_dir)
            avisa_de_narracion(incidencias)
            guia_de_subida(
                run_dir,
                titulo=state["title"],
                descripcion=descripcion,
                incidencias=incidencias,
            )
        except Exception as e:  # la guía nunca puede tumbar un run que ya terminó
            print(f"  [AVISO] la guía de la carpeta no se pudo escribir: {e}")
    _abre_la_guia(state)

    if upload_status == "complete":
        yt_msg = "uploaded as private draft"
    elif upload_status == "skipped":
        yt_msg = f"skipped — {upload_motivo}" if upload_motivo else "skipped"
    else:
        yt_msg = f"not uploaded ({upload_status})"

    print(f"\n{'=' * 60}")
    print("COMPLETE")
    print(f"  Video: {state['stages']['assembly'].get('output', '')}")
    print(f"  Thumbnail: {state['stages']['thumbnail'].get('output', 'skipped')}")
    print(f"  YouTube: {yt_msg}")
    print(f"{'=' * 60}")


def listar_canales() -> list[dict]:
    """Los canales del estudio, con lo que decide si cada uno puede producir hoy.

    **Existe para que elegir canal no sea adivinar.** Con más de un canal, la pregunta «¿en cuál
    produzco?» necesita algo más que una lista de carpetas: lo que decide es si tiene **fichas de
    fuentes** —cuando su nicho las lleva— y si tiene **OAuth**, sin el cual el vídeo se monta pero
    no llega a borrador privado.

    **Todos los canales están activos** (decisión 12, reformulada el 16-09-2026: un canal por
    nicho). Que uno tenga menos vídeos publicados que otro no lo hace menos activo; lo que este
    listado responde es si puede producir HOY.

    **Todo lo que decide sale del `perfil.json` y nada se deduce del id** (F4.9). Tres defectos
    corregidos el 16-09-2026, los tres por deducir en vez de leer:

    - El OAuth se buscaba en `YOUTUBE_REFRESH_TOKEN_<SUFIJO DEL ID>`, inventando el nombre de la
      variable a partir del nombre de la carpeta. El perfil lo declara en
      `publicacion.refresh_token_env`, y un canal que lo tenía en `YOUTUBE_REFRESH_TOKEN_2` salía
      «sin OAuth» con el token vivo en el `.env`.
    - La falta de fichas se contaba como carencia en todos los canales. Un nicho que declara
      `nicho.sin_fuentes_verificadas` no tiene citas que comprobar: es su formato, no un hueco.
    - El motor de voz se leía de `perfil.voz.modelo`, que **no puede existir**: el motor es del
      estudio (`lib.config.MOTOR_DE_VOZ`) y `tests/test_capas.py` falla en rojo si un perfil lo
      declara. El campo valía «?» por construcción, así que se informa una vez y del estudio.

    No importa `lib.config` para leer cada perfil: `config` resuelve UN canal, el activo, así que
    preguntarle por los demás no funcionaría. Se leen los `perfil.json` directamente.
    """
    from lib.config import CANAL_ACTIVO, CANALES_DIR, YOUTUBE_SUBIDA_API
    from lib.youtube_client import ENCENDIDA

    fuera = []
    for directorio in sorted(p for p in CANALES_DIR.glob("*") if (p / "perfil.json").exists()):
        try:
            perfil = json.loads((directorio / "perfil.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            fuera.append(
                {
                    "id": directorio.name,
                    "nombre": "(perfil ilegible)",
                    "estado": "?",
                    "fichas": 0,
                    "lleva_fichas": True,
                    "variable_oauth": None,
                    "tiene_oauth": False,
                    "es_el_activo": directorio.name == CANAL_ACTIVO,
                    "veredicto": f"NO puede producir: su perfil.json no se puede leer ({e})",
                }
            )
            continue
        fichas = len(list((directorio / "datos" / "fuentes").glob("*.json")))
        # Un nicho de ficción no tiene citas que verificar. Lo dice el perfil; no se deduce del
        # conteo, porque «cero fichas» y «este nicho no lleva fichas» son cosas distintas.
        lleva_fichas = not (perfil.get("nicho") or {}).get("sin_fuentes_verificadas")
        # El token de subida es de CADA canal y su variable la nombra el perfil: el token de un
        # canal da 403 sobre otro (addendum fila 159). Sin la clave declarada no hay nada que leer.
        variable_oauth = ((perfil.get("publicacion") or {}).get("refresh_token_env") or "").strip()
        tiene_oauth = bool(variable_oauth and os.getenv(variable_oauth, "").strip())
        faltan = []
        if lleva_fichas and not fichas:
            faltan.append("sin fichas de fuentes (el gate 1 exige una por afirmación)")
        if not variable_oauth:
            faltan.append("su perfil no declara publicacion.refresh_token_env (no se sabe qué token es el suyo)")
        elif not tiene_oauth and YOUTUBE_SUBIDA_API == ENCENDIDA:
            # Solo con la subida por la API pedida (OC1.8): a mano, que es lo de serie, el token no hace falta.
            faltan.append(f"sin OAuth: {variable_oauth} no está en el .env y YOUTUBE_SUBIDA_API pide la API")
        fuera.append(
            {
                "id": directorio.name,
                "nombre": perfil.get("nombre") or "(sin nombre)",
                "estado": perfil.get("estado") or "?",
                "fichas": fichas,
                "lleva_fichas": lleva_fichas,
                "variable_oauth": variable_oauth or None,
                "tiene_oauth": tiene_oauth,
                "es_el_activo": directorio.name == CANAL_ACTIVO,
                "veredicto": "listo para producir" if not faltan else "NO listo: " + " · ".join(faltan),
            }
        )
    return fuera


def main():
    # Un canal mal configurado se dice ANTES de hacer nada. Sin esto, `--create` o `--run-all`
    # arrancaban con valores en None y el fallo salía tres etapas más adelante, con otra cara
    # (F4.9, R8 de la revisión). `--check` lo enumera con detalle; aquí solo se para.
    from lib.config import CANAL_ERROR as _canal_error

    if _canal_error and "--check" not in sys.argv:
        print(f"[FAIL] {_canal_error}")
        print("       `pipeline.py --check` lo enumera con detalle.")
        return 1

    parser = argparse.ArgumentParser(description="YT Video Factory Pipeline")
    parser.add_argument(
        "--canal",
        type=str,
        default="",
        help=(
            "id del canal (carpeta de canales/). Manda sobre CANAL_ACTIVO del .env y es la forma "
            "recomendada de invocar el pipeline con más de un canal: hace el canal explícito en "
            "cada comando en vez de heredarlo del entorno de la sesión anterior"
        ),
    )
    parser.add_argument("--canales", action="store_true", help="Lista los canales de esta instalación y sale")
    parser.add_argument("--check", action="store_true", help="Check dependencies")
    parser.add_argument("--create", action="store_true", help="Create a new run")
    parser.add_argument("--title", type=str, default="", help="Video title")
    parser.add_argument(
        "--voice",
        type=str,
        default="",
        help="perfil tonal de la receta de voz (neutro | grave); vacío = el que fije la receta",
    )
    parser.add_argument("--mode", type=str, default="manual", help="channel or folder or manual")
    parser.add_argument("--channel-url", type=str, default="", help="YouTube channel URL")
    parser.add_argument("--run-id", type=str, default="", help="Run ID to operate on")
    parser.add_argument(
        "--stage",
        type=str,
        default="",
        help=(
            "Stage to run: images|tts|alinea|activos|escena|render|thumbnail|upload (tras activos y tras escena el "
            "pipeline se detiene: se sigue con --stage)"
        ),
    )
    parser.add_argument("--run-all", action="store_true", help="Run all stages")
    parser.add_argument(
        "--sin-subida",
        action="store_true",
        help="con --run-all: produce el vídeo y OMITE la etapa de subida (no depende de que falten credenciales)",
    )
    parser.add_argument(
        "--forzar-subida",
        action="store_true",
        help=(
            "sube OTRA VEZ un run que ya está subido, dejando un segundo borrador en el canal. "
            "Sin este flag la etapa es idempotente a propósito: subir es irreversible"
        ),
    )
    parser.add_argument(
        "--set-thumbnail",
        action="store_true",
        help=(
            "pone la miniatura de un run en el vídeo que ya subió, sin volver a subir el vídeo. "
            "Para cuando la miniatura falló en la subida (canal sin verificar por teléfono) o se "
            "ha regenerado después. No cambia la visibilidad: sigue siendo borrador privado"
        ),
    )
    parser.add_argument(
        "--rehace-leeme",
        action="store_true",
        help=(
            "reescribe subir-al-canal/LEEME.html de un run ya subido, con el título y la descripción traducidos que "
            "declare el canal. No sube nada, no llama a la API de YouTube y no toca el estado del run"
        ),
    )
    parser.add_argument("--list", action="store_true", help="List all runs")
    parser.add_argument(
        "--assets-audit",
        action="store_true",
        help="Rebuild assets.json from the adapter provenance records and cross-count it against the run files",
    )

    args = parser.parse_args()

    if args.canales:
        lista = listar_canales()
        if not lista:
            print("No hay ningún canal en canales/.")
            return
        from lib.config import MOTOR_DE_VOZ

        print(f"Canales de esta instalación ({len(lista)}), todos ACTIVOS — un canal por nicho:\n")
        for c in lista:
            marca = " ← CANAL_ACTIVO del .env" if c["es_el_activo"] else ""
            print(f"  {c['id']}{marca}")
            print(f"     {c['nombre']}  ·  estado: {c['estado']}")
            # El nicho decide si las fichas son un requisito: en uno de ficción no hay citas que
            # verificar, y un «0» a secas se lee como carencia cuando es el formato del canal.
            fichas = (
                f"fichas de fuentes: {c['fichas']}"
                if c["lleva_fichas"]
                else "sin aparato de fuentes (así lo declara su nicho)"
            )
            oauth = f"sí ({c['variable_oauth']})" if c["tiene_oauth"] else "NO"
            print(f"     {fichas}  ·  OAuth: {oauth}")
            print(f"     {c['veredicto']}\n")
        # El motor es del ESTUDIO y no de cada canal (decisión 13, F4.9): se dice una vez.
        print(f"Motor de voz: {MOTOR_DE_VOZ} (el mismo para todos los canales).")
        print("Para producir en uno concreto: pipeline.py --canal <id> ...")
        print("El `--canal` manda sobre el .env y es la forma recomendada con más de un canal.")
        return

    if args.check:
        ok = check_dependencies()
        sys.exit(0 if ok else 1)

    if args.list:
        runs = run_state.list_runs()
        if not runs:
            print("No runs found.")
        for r in runs:
            print(f"  {r['run_id']} — {r['status']} — {r['title']}")
        return

    if args.create:
        if not args.title:
            print("Error: --title required for --create")
            sys.exit(1)
        state = run_state.create_run(
            title=args.title,
            mode=args.mode,
            voice=args.voice,
            channel_url=args.channel_url,
        )
        from lib import config

        print(f"Created run: {state['run_id']} (motor de escena)")
        print(f"Output dir: {state['output_dir']}")
        print(
            "Guion de escena del episodio (lo escribe quien pone en escena, contrato en lib/escena/episodio.py): "
            f"{config.guion_de_escena(config.CANAL_DIR, state['run_id']) / config.ESCENA_GUION}"
        )
        print(json.dumps(state, indent=2))
        return

    if not args.run_id:
        print("Error: --run-id required")
        sys.exit(1)

    if args.assets_audit:
        # Auditoría a demanda: reconstruye la procedencia de un run (por ejemplo, después de
        # reanudarlo o de que una etapa se rompiera) y sale con 1 si el conteo no cuadra.
        state = run_state.load_run(args.run_id)
        report = _sync_assets(state, "auditoría")
        sys.exit(0 if report["cuadra"] else 1)

    if args.set_thumbnail:
        sys.exit(0 if set_thumbnail(args.run_id) else 1)

    if args.rehace_leeme:
        from lib.publicacion import ErrorDeMetadatos

        try:
            sys.exit(0 if rehace_guia(args.run_id) else 1)
        except ErrorDeMetadatos as e:
            print(f"[FAIL] {e}")
            sys.exit(1)

    from lib.youtube_client import SubidaNoConfigurada

    try:
        _produce(args)
    except (MotorRetirado, SubidaNoConfigurada) as e:
        print(f"[FAIL] {e}")
        sys.exit(1)


def _produce(args) -> None:
    """`--run-all` o `--stage`: lo que fabrica el vídeo. Aparte de `main` para que su negativa salga sin traza."""
    if args.run_all:
        run_all(args.run_id, sin_subida=args.sin_subida, forzar_subida=args.forzar_subida)
    elif args.stage:
        stage_map = {
            "images": stage_images,
            "tts": stage_tts,
            # Se siguen de una en una, porque tras `activos` y tras `escena` el pipeline para (F6.2d).
            "alinea": stage_alinea,
            "activos": stage_activos,
            "escena": stage_escena,
            "render": stage_render,
            # La del motor de láminas, retirada en F6.7: dice qué hacer en su lugar (ver `stage_assembly`).
            "assembly": stage_assembly,
            "thumbnail": stage_thumbnail,
            "upload": stage_upload,
        }
        if args.stage not in stage_map:
            print(f"Error: unknown stage '{args.stage}'. Options: {list(stage_map.keys())}")
            sys.exit(1)
        if args.stage == "upload":
            # La unica etapa con una accion irreversible es la unica que acepta forzarse
            stage_upload(args.run_id, forzar=args.forzar_subida)
        else:
            stage_map[args.stage](args.run_id)
    else:
        print("Error: specify --stage or --run-all")
        sys.exit(1)


if __name__ == "__main__":
    main()
