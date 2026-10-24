"""Valida y renderiza una composición del motor de escena (F6.2a).

Envuelve tres órdenes de la CLI de HyperFrames 0.8.78 (`lint`, `snapshot` y `render`) y la sonda propia
(`motor/sonda.cjs`). Cada orden:

- se lanza con `node --require motor/sin-red.cjs` (decisión 6: la CLI sale a GitHub en cada orden si no se
  la corta, medido en F6.0) y con el Chrome con WebGPU de `CHROME_WEBGPU_MANIFIESTO` (F6.1), que se le
  pasa en `HYPERFRAMES_BROWSER_PATH`;
- recibe el entorno sin nada del `.env` ni nada que huela a credencial (`config.entorno_para_terceros`):
  entre otras cosas, así `snapshot` no manda fotogramas a Gemini aunque haya una `GEMINI_API_KEY` suelta;
- deja su salida entera en el directorio de log que le pasen (el del run), un fichero por ejecución.

**El render para, con `ErrorDeRender`, en vez de sacar un vídeo roto**:

- si `lint` da algún error;
- si la sonda ve una petición remota (la corta: no sale), `data-mallas-error`, un error de consola o una
  composición que no registra su línea de tiempo;
- si el propio render escribe en su log un error de las mallas o de la página (`[mallas]`,
  `[Browser:ERROR]`, `[Browser:PAGEERROR]`): la sonda solo ve la carga y el primer fotograma, y un fallo
  de la GPU a mitad de vídeo solo aparece aquí. En ese caso el MP4 se borra: sin mallas no se entrega.

Antes de abrir Chrome con la GPU se comprueba con `nvidia-smi` que queda memoria libre: la tarjeta de
8 GB admite un trabajo de GPU cada vez (regla 5 del plan de F6.2).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from lib import config
from lib.escena import compone as _compone

# La calidad del render: `looks` (CRF 16), la de video_1 (doc/inventario-herramientas-y-proceso.md §9).
# Es del estudio: vale igual para cualquier canal.
CALIDAD = "looks"
# Lo que, escrito en el log del render, significa que el vídeo no vale. HyperFrames reenvía la consola de
# Chrome con estos prefijos, y malla-webgpu.js escribe los suyos con «[mallas]». `[FrameCapture:` es su aviso de
# un medio que no cargó o no estuvo listo: con `--no-best-effort` ya para el render, y aquí se caza también por
# si algún día se quita el interruptor.
MARCAS_DE_ERROR = ("[mallas]", "[Browser:ERROR]", "[Browser:PAGEERROR]", "[FrameCapture:")


class ErrorDeRender(RuntimeError):
    """La composición no está lista para renderizar, o el render no ha dado un vídeo válido."""


# ------------------------------------------------------------------------------------------ herramientas
def node_exe() -> str:
    """El Node del motor: `NODE_EXE`, el primero del PATH o el alias por defecto de fnm."""
    if config.NODE_EXE:
        return config.NODE_EXE
    en_path = shutil.which("node")
    if en_path:
        return en_path
    fnm = Path(os.environ.get("APPDATA", "")) / "fnm" / "aliases" / "default" / "node.exe"
    if fnm.exists():
        return str(fnm)
    raise ErrorDeRender("no encuentro node: instálalo con fnm en la versión de .node-version, o pon NODE_EXE")


def chrome_webgpu() -> Path:
    """El ejecutable del Chrome con WebGPU, leído de su manifiesto (F6.1, fila 201)."""
    manifiesto = config.CHROME_WEBGPU_MANIFIESTO
    if not manifiesto.is_file():
        raise ErrorDeRender(
            f"no está el manifiesto del Chrome con WebGPU ({manifiesto}): instálalo con "
            "scripts\\instala_chrome_webgpu.ps1 (el de HyperFrames no trae las librerías DXC)"
        )
    exe = Path(json.loads(manifiesto.read_text(encoding="utf-8"))["exe"])
    if not exe.is_file():
        raise ErrorDeRender(f"el manifiesto apunta a {exe}, que no existe: scripts\\instala_chrome_webgpu.ps1")
    return exe


def memoria_libre_gpu_mb() -> int:
    """Memoria libre de la GPU en MB, según nvidia-smi."""
    nvsmi = shutil.which("nvidia-smi")
    if not nvsmi:
        raise ErrorDeRender("no está nvidia-smi: sin él no se puede comprobar que la GPU está libre")
    r = subprocess.run(
        [nvsmi, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise ErrorDeRender(f"nvidia-smi falló (código {r.returncode}): {r.stderr.strip()[:200]}")
    return int(r.stdout.strip().splitlines()[0])


def procesos_de_gpu() -> list[str]:
    """Los ejecutables que nvidia-smi da como procesos de cómputo en la GPU (rutas completas en Windows)."""
    nvsmi = shutil.which("nvidia-smi")
    if not nvsmi:
        raise ErrorDeRender("no está nvidia-smi: sin él no se puede comprobar que la GPU está libre")
    r = subprocess.run(
        [nvsmi, "--query-compute-apps=process_name", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0:
        raise ErrorDeRender(f"nvidia-smi falló (código {r.returncode}): {r.stderr.strip()[:200]}")
    return [linea.strip() for linea in r.stdout.splitlines() if linea.strip()]


def proceso_vivo(pid: int) -> bool:
    """¿Sigue vivo el proceso `pid`? Sin psutil, que no está entre las dependencias del pipeline.

    En Windows no vale `os.kill(pid, 0)`: allí `os.kill` con cualquier señal que no sea Ctrl+C TERMINA el proceso.
    Se pregunta al sistema por su código de salida: 259 (STILL_ACTIVE) es que no ha acabado.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        manejador = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not manejador:
            return False
        try:
            codigo = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(manejador, ctypes.byref(codigo))) and codigo.value == 259
        finally:
            kernel32.CloseHandle(manejador)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def cerrojo_vivo(ruta: Path) -> dict | None:
    """El cerrojo de un trabajo de GPU del estudio si su proceso sigue vivo; si murió sin soltarlo, se borra.

    Es cómo se reconoce al obrero de `.venv-escena` (auditoría de F6.2c, recomendación 3): nvidia-smi lo da como el
    intérprete de Python del sistema, que no se distingue de cualquier otro Python, y su pico (2.864 MB,
    `experimentos/motor-escena/f62c-real/gpu.json → esrgan.vram_pico_mb`) queda por debajo del umbral de memoria.
    """
    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        pid = int(datos["pid"])
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        datos, pid = {}, 0
    if proceso_vivo(pid):
        return datos
    Path(ruta).unlink(missing_ok=True)  # su proceso ya no existe: el cerrojo es un resto de un corte
    return None


def toma_cerrojo(ruta: Path, pid: int, que: str) -> None:
    """Deja escrito que el proceso `pid` está usando la GPU para `que`. Lo suelta `suelta_cerrojo`."""
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    Path(ruta).write_text(
        json.dumps({"pid": int(pid), "que": que, "desde": datetime.now().isoformat(timespec="seconds")}),
        encoding="utf-8",
    )


def suelta_cerrojo(ruta: Path, pid: int) -> None:
    """Borra el cerrojo si es de `pid` (el de otro trabajo no se toca)."""
    try:
        if int(json.loads(Path(ruta).read_text(encoding="utf-8")).get("pid", -1)) == int(pid):
            Path(ruta).unlink(missing_ok=True)
    except (OSError, ValueError, TypeError):
        pass


def trabajos_de_gpu_en_marcha() -> list[str]:
    """Los trabajos de GPU del estudio que están en la tarjeta ahora, reconocidos por su ejecutable o su cerrojo.

    - `llama-server` (Orpheus): nvidia-smi lo da con su ruta (medido: `experimentos/motor-escena/f62a-vram/
      vram.json → orpheus_cargado.procesos_de_computo`).
    - ComfyUI: si nvidia-smi da un ejecutable dentro de su carpeta. Su Python de venv puede aparecer como el
      intérprete base y entonces no se le reconoce por aquí; con un modelo cargado lo caza el umbral de memoria.
    - El obrero de `.venv-escena`: por su cerrojo (`config.ESCENA_CERROJO_OBRERO`), que toma mientras corre.
    - El marcado de la marca de IA (OC1.5), también en `.venv-escena`: por el suyo (`config.MARCA_CERROJO`).
    """
    llama = config.LLAMA_SERVER.name.lower()
    comfy = str(config.COMFY_ROOT).lower()
    en_marcha = [p for p in procesos_de_gpu() if Path(p).name.lower() == llama or p.lower().startswith(comfy)]
    for cerrojo, quien in ((config.ESCENA_CERROJO_OBRERO, "obrero de escena"), (config.MARCA_CERROJO, "marca de IA")):
        tomado = cerrojo_vivo(cerrojo)
        if tomado is not None:
            en_marcha.append(f"{quien} (pid {tomado.get('pid')}, desde {tomado.get('desde')})")
    return en_marcha


def exige_gpu_libre(minimo_mb: int | None = None) -> int:
    """Para si otro trabajo del estudio está en la GPU o si no queda la memoria que pide el motor.

    Devuelve los MB libres. Mira las dos cosas porque ninguna basta sola: el umbral no ve un modelo pequeño y
    el nombre del proceso no ve a ComfyUI cuando corre con el intérprete base (auditoría de F6.2a).
    """
    en_marcha = trabajos_de_gpu_en_marcha()
    if en_marcha:
        raise ErrorDeRender(
            f"hay otro trabajo del estudio en la GPU ({', '.join(en_marcha)}). La GPU va de una en una: espera a "
            "que acabe (o apaga el servidor) antes de renderizar."
        )
    minimo = config.ESCENA_VRAM_LIBRE_MIN_MB if minimo_mb is None else minimo_mb
    libre = memoria_libre_gpu_mb()
    if libre < minimo:
        raise ErrorDeRender(
            f"la GPU tiene {libre} MB libres y el motor de escena pide {minimo}: hay otro trabajo de GPU en "
            "marcha (ComfyUI, llama-server, un obrero). La GPU va de una en una: espera a que acabe."
        )
    return libre


def _sello() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _entorno() -> dict[str, str]:
    """El entorno de la CLI: sin credenciales, sin telemetría y sin vigilar a los procesos que la lanzaron.

    `HYPERFRAMES_RENDER_DETACHED=1` (piloto de F6.8): al empezar, el render de HyperFrames apunta TODA la cadena de
    procesos que lo lanzó y se cancela si muere cualquiera (`render_cancelled_parent_exited`). Las etapas de GPU se
    lanzan como proceso independiente (`Start-Process`), así que en esa cadena está la consola que las lanzó, y al
    cerrarse canceló un render de 17 min al 52 %. Quien espera al render es este proceso (`subprocess.run` con su
    `timeout`), y el vídeo solo llega a su sitio si salió bien (`render`), así que la vigilancia no protege de nada.
    """
    return config.entorno_para_terceros(
        {
            "HYPERFRAMES_BROWSER_PATH": str(chrome_webgpu()),
            "HYPERFRAMES_NO_TELEMETRY": "1",
            "HYPERFRAMES_NO_UPDATE_CHECK": "1",
            "HYPERFRAMES_NO_AUTO_INSTALL": "1",
            "HYPERFRAMES_RENDER_DETACHED": "1",
            "DO_NOT_TRACK": "1",
            "NO_COLOR": "1",
        }
    )


def _cli(orden: list[str], carpeta: Path, dir_log: Path, nombre: str, timeout: int) -> tuple[str, Path, int]:
    """Lanza la CLI de HyperFrames con la guarda y deja su salida en `dir_log`. Devuelve (salida, log, código)."""
    if not config.HYPERFRAMES_CLI.is_file():
        raise ErrorDeRender(f"no está la CLI de HyperFrames ({config.HYPERFRAMES_CLI}): cd motor; npm ci")
    dir_log.mkdir(parents=True, exist_ok=True)
    log = dir_log / f"{nombre}-{_sello()}.log"
    args = [node_exe(), "--require", str(config.MOTOR_ESCENA_GUARDA), str(config.HYPERFRAMES_CLI), *orden]
    r = subprocess.run(
        args,
        cwd=carpeta,
        env=_entorno(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    log.write_text(
        f"$ {' '.join(args)}\n# codigo_salida = {r.returncode}\n--- stdout\n{r.stdout}\n--- stderr\n{r.stderr}",
        encoding="utf-8",
    )
    return f"{r.stdout}\n{r.stderr}", log, r.returncode


def errores_del_log(texto: str) -> list[str]:
    """Las líneas del log de HyperFrames que dicen que el vídeo no vale (ver `MARCAS_DE_ERROR`)."""
    return [linea.strip() for linea in texto.splitlines() if any(m in linea for m in MARCAS_DE_ERROR)]


def _fps(carpeta: Path) -> str:
    fps = _compone.lee_guion(carpeta / "index.html")["fps"]
    if not float(fps).is_integer():
        raise ErrorDeRender(f"el GUION pide {fps} fps; el envoltorio solo pasa fps enteros a la CLI")
    return str(int(fps))


# ------------------------------------------------------------------------------------------ órdenes
def lint(carpeta: str | Path, dir_log: str | Path) -> dict:
    """`hyperframes lint --json`. Para si hay algún error; los avisos se quedan en el log."""
    carpeta, dir_log = Path(carpeta), Path(dir_log)
    salida, log, codigo = _cli(["lint", "--json", str(carpeta)], carpeta, dir_log, "lint", timeout=600)
    inicio = salida.find("{")
    try:
        datos = json.JSONDecoder().raw_decode(salida[inicio:])[0] if inicio >= 0 else None
    except json.JSONDecodeError:
        datos = None
    if not isinstance(datos, dict):
        raise ErrorDeRender(f"hyperframes lint no devolvió su JSON (código {codigo}); la salida está en {log}")
    errores = [f for f in datos.get("findings", []) if f.get("severity") == "error"]
    if errores or datos.get("errorCount"):
        detalle = " · ".join(f"{f.get('code')}: {str(f.get('message'))[:140]}" for f in errores[:5])
        raise ErrorDeRender(
            f"hyperframes lint da {datos.get('errorCount', len(errores))} error(es): {detalle} (log: {log})"
        )
    return datos


def ejecuta_sonda(carpeta: str | Path, dir_log: str | Path, permite: tuple[str, ...] = ()) -> dict:
    """Pasa la sonda y devuelve su informe, sin juzgarlo (lo juzga `comprueba_sonda`).

    `permite` solo existe para el control negativo de la suite: añade otro origen de loopback a lo que la
    sonda deja pasar, y la propia sonda rechaza cualquiera que no sea 127.0.0.0/8.
    """
    carpeta, dir_log = Path(carpeta), Path(dir_log)
    dir_log.mkdir(parents=True, exist_ok=True)
    args = [
        node_exe(),
        "--require",
        str(config.MOTOR_ESCENA_GUARDA),
        str(config.MOTOR_ESCENA_SONDA),
        str(carpeta),
        "--chrome",
        str(chrome_webgpu()),
        "--timeout",
        str(config.ESCENA_SONDA_TIMEOUT_MS),
    ]
    for origen in permite:
        args += ["--permite", origen]
    r = subprocess.run(
        args,
        cwd=config.MOTOR_ESCENA_DIR,
        env=config.entorno_para_terceros({"NO_COLOR": "1"}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=config.ESCENA_SONDA_TIMEOUT_MS * 3 // 1000 + 120,
    )
    lineas = [linea for linea in r.stdout.splitlines() if linea.strip().startswith("{")]
    try:
        informe = json.loads(lineas[-1])
    except (IndexError, json.JSONDecodeError):
        informe = {"ok": False, "fallo": f"la sonda no devolvió su JSON (código {r.returncode})"}
    informe["codigo_salida"] = r.returncode
    ruta = dir_log / f"sonda-{_sello()}.json"
    informe["_log"] = str(ruta)
    ruta.write_text(
        json.dumps({**informe, "_stderr": r.stderr[-4000:]}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return informe


def comprueba_sonda(informe: dict) -> None:
    """Para con `ErrorDeRender` si el informe de la sonda tiene cualquier problema."""
    problemas = []
    if informe.get("fallo"):
        problemas.append(f"la sonda no pudo probar: {informe['fallo']}")
    if informe.get("remotas"):
        problemas.append(
            f"la composición pide {len(informe['remotas'])} recurso(s) de fuera (la sonda los cortó y no "
            f"salieron): {informe['remotas'][:5]}"
        )
    if informe.get("mallas_error"):
        problemas.append(f"la página marcó data-mallas-error: {informe['mallas_error']}")
    if informe.get("errores_consola"):
        problemas.append(f"errores de consola: {informe['errores_consola'][:5]}")
    if informe.get("imagenes_rotas"):
        problemas.append(f"imágenes que no decodifican: {informe['imagenes_rotas'][:5]}")
    if not informe.get("fallo") and not informe.get("timeline"):
        problemas.append("la composición no registró window.__timelines.main")
    mallas = informe.get("mallas") or {}
    if (mallas.get("adaptador") or {}).get("fallback"):
        problemas.append(f"las mallas usan un adaptador WebGPU de respaldo: {mallas['adaptador']}")
    if problemas:
        raise ErrorDeRender("la sonda para el render: " + " · ".join(problemas) + f" (informe: {informe.get('_log')})")


def sonda(carpeta: str | Path, dir_log: str | Path) -> dict:
    """Comprueba la GPU, pasa la sonda y para si encuentra algo. Devuelve el informe."""
    exige_gpu_libre()
    informe = ejecuta_sonda(carpeta, dir_log)
    comprueba_sonda(informe)
    return informe


def valida(carpeta: str | Path, dir_log: str | Path) -> dict:
    """`lint` y la sonda: lo que tiene que pasar una composición antes de fotografiarse."""
    return {"lint": lint(carpeta, dir_log), "sonda": sonda(carpeta, dir_log)}


def snapshot(carpeta: str | Path, dir_log: str | Path, tiempos: list[float], salida: str | Path) -> list[Path]:
    """Capturas de revisión en los instantes `tiempos` (s), en `salida`. Valida antes."""
    carpeta, dir_log, salida = Path(carpeta), Path(dir_log), Path(salida)
    if not tiempos:
        raise ErrorDeRender("snapshot sin instantes: pasa al menos uno")
    valida(carpeta, dir_log)
    exige_gpu_libre()
    en = ",".join(f"{t:g}" for t in tiempos)
    orden = ["snapshot", str(carpeta), "--at", en, "--no-end", "--browser-gpu", "-o", str(salida)]
    texto, log, codigo = _cli(orden, carpeta, dir_log, "snapshot", timeout=1800)
    errores = errores_del_log(texto)
    if codigo != 0 or errores:
        raise ErrorDeRender(f"snapshot falló (código {codigo}): {errores[:5]} (log: {log})")
    return sorted(salida.glob("frame-*.png"))


def render(carpeta: str | Path, salida: str | Path, dir_log: str | Path, workers: int | None = None) -> Path:
    """Renderiza la composición a `salida` (MP4) con los fps de su GUION. Valida antes y revisa el log después.

    `workers` es el número de procesos de Chrome; sin él, el que elija HyperFrames. Todos comparten la misma
    GPU dentro de este único trabajo.

    **HyperFrames escribe en una ruta corta** (`config.ESCENA_RENDER_TMP`) y el vídeo se mueve a `salida` solo si
    salió bien: la carpeta de trabajo que HyperFrames crea junto a su salida no cabe en MAX_PATH dentro de un run
    (F6.3). De paso, un vídeo parcial nunca llega a `salida`.
    """
    carpeta, salida, dir_log = Path(carpeta), Path(salida), Path(dir_log)
    fps = _fps(carpeta)
    valida(carpeta, dir_log)
    exige_gpu_libre()
    salida.parent.mkdir(parents=True, exist_ok=True)
    config.ESCENA_RENDER_TMP.mkdir(parents=True, exist_ok=True)
    trabajo = Path(tempfile.mkdtemp(prefix="hf-", dir=config.ESCENA_RENDER_TMP))
    temporal = trabajo / salida.name
    # `--no-best-effort`: un medio que no carga o no está listo PARA el render. Por defecto HyperFrames entrega
    # el vídeo sin ese medio y con un aviso (medido en F6.2a con una imagen que no decodifica: código 0 y MP4).
    orden = [
        "render",
        str(carpeta),
        "--fps",
        fps,
        "--quality",
        CALIDAD,
        "--browser-gpu",
        "--strict",
        "--no-best-effort",
        "-o",
        str(temporal),
    ]
    if workers:
        orden += ["--workers", str(workers)]
    try:
        texto, log, codigo = _cli(orden, carpeta, dir_log, "render", timeout=config.ESCENA_RENDER_TIMEOUT_S)
        errores = errores_del_log(texto)
        # Un vídeo parcial, sin mallas o con la página rota no se entrega, y tampoco se deja donde una etapa
        # idempotente lo daría por hecho: se queda en la carpeta de trabajo, que se borra, y el log guarda la evidencia.
        if codigo != 0 or errores or not temporal.is_file():
            raise ErrorDeRender(f"el render no dio un vídeo válido (código {codigo}): {errores[:5]} (log: {log})")
        salida.unlink(missing_ok=True)
        shutil.move(str(temporal), str(salida))
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)
    return salida
