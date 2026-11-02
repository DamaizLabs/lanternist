"""Las guardas de `lib/escena/render.py` que no necesitan Chrome ni GPU para probarse (F6.2a).

- La GPU ocupada para el trabajo ANTES de abrir nada (regla 5 del plan de F6.2).
- Toda orden de la CLI va con la guarda de red y sin credenciales en el entorno (decisión 6).
- Qué líneas del log de HyperFrames tumban un render, y qué informes de la sonda lo paran.
Cada una con su control: el caso limpio pasa.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lib import config
from lib.escena import render

# Lo que da nvidia-smi como procesos de cómputo con el escritorio abierto: nada del estudio.
ESCRITORIO = [r"C:\Windows\explorer.exe", r"C:\Program Files (x86)\Dropbox\Client\Dropbox.exe"]
# Medido el 29-09 con Orpheus cargado (`experimentos/motor-escena/f62a-vram/vram.json`): memoria libre en
# reposo (`reposo.libre_mb`) y con llama-server y el GGUF Q8_0 (`orpheus_cargado.libre_mb`). nvidia-smi nombra
# cada proceso con su ruta completa (`orpheus_cargado.procesos_de_computo`); las de aquí son inventadas, con la
# forma de una instalación cualquiera, porque las rutas salen del `.env` de quien usa el motor (OC1.3).
LIBRE_EN_REPOSO_MB, LIBRE_CON_ORPHEUS_MB = 6973, 2517
LLAMA_SERVER_VISTO = r"X:\herramientas\llama.cpp\llama-server.exe"
COMFY_ROOT_VISTO = Path(r"X:\herramientas\ComfyUI")


def test_la_gpu_ocupada_para_el_render_antes_de_abrir_nada(monkeypatch, tmp_path):
    monkeypatch.setattr(render, "procesos_de_gpu", lambda: ESCRITORIO)
    monkeypatch.setattr(render, "memoria_libre_gpu_mb", lambda: config.ESCENA_VRAM_LIBRE_MIN_MB - 1)
    lanzados = []
    monkeypatch.setattr(render, "ejecuta_sonda", lambda *a, **k: lanzados.append("sonda") or {})
    with pytest.raises(render.ErrorDeRender, match="otro trabajo de GPU"):
        render.sonda(tmp_path, tmp_path / "log")
    assert lanzados == []


def test_control_con_la_gpu_libre_la_sonda_si_se_lanza(monkeypatch, tmp_path):
    monkeypatch.setattr(render, "procesos_de_gpu", lambda: ESCRITORIO)
    monkeypatch.setattr(render, "memoria_libre_gpu_mb", lambda: config.ESCENA_VRAM_LIBRE_MIN_MB)
    limpio = {"remotas": [], "mallas_error": None, "errores_consola": [], "timeline": True, "_log": "x"}
    monkeypatch.setattr(render, "ejecuta_sonda", lambda *a, **k: limpio)
    assert render.sonda(tmp_path, tmp_path / "log") is limpio


def test_la_cli_va_con_la_guarda_y_sin_credenciales(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "no-debe-llegar")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN_PRUEBA", "tampoco")
    monkeypatch.setattr(render, "chrome_webgpu", lambda: tmp_path / "chrome-headless-webgpu" / "x" / "chrome.exe")
    monkeypatch.setattr(render, "node_exe", lambda: "node")
    monkeypatch.setattr(config, "HYPERFRAMES_CLI", tmp_path / "cli.js")
    (tmp_path / "cli.js").write_text("", encoding="utf-8")
    visto = {}

    def falso_run(args, **kw):
        visto.update(args=args, env=kw["env"])
        return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")

    monkeypatch.setattr(render, "_corre_vigilado", falso_run)
    render._cli(["lint", "--json", str(tmp_path)], tmp_path, tmp_path / "log", "lint", timeout=5)
    assert visto["args"][1:3] == ["--require", str(config.MOTOR_ESCENA_GUARDA)]
    assert visto["env"]["HYPERFRAMES_BROWSER_PATH"].endswith("chrome.exe")
    assert "GEMINI_API_KEY" not in visto["env"]  # snapshot mandaría fotogramas a Gemini con ella
    assert "YOUTUBE_REFRESH_TOKEN_PRUEBA" not in visto["env"]
    assert visto["env"]["HYPERFRAMES_NO_TELEMETRY"] == "1"
    # Sin vigilar la cadena de procesos que la lanzó: al cerrarse la consola de un Start-Process, HyperFrames canceló
    # un render de 17 min al 52 % (piloto de F6.8).
    assert visto["env"]["HYPERFRAMES_RENDER_DETACHED"] == "1"
    # Y deja su log en el directorio que le pasan.
    assert list((tmp_path / "log").glob("lint-*.log"))


def test_que_lineas_del_log_tumban_el_render():
    log = "\n".join(
        [
            "[Browser:WARN] The powerPreference option is currently ignored",
            "[Browser:ERROR] [mallas] dispositivo perdido: destroyed Device was destroyed.",
            "[Browser:PAGEERROR] TypeError: x is undefined",
            "  █████ 100%  Render complete",
        ]
    )
    assert render.errores_del_log(log) == [
        "[Browser:ERROR] [mallas] dispositivo perdido: destroyed Device was destroyed.",
        "[Browser:PAGEERROR] TypeError: x is undefined",
    ]


def test_control_un_log_limpio_no_tumba_nada():
    assert render.errores_del_log("[Browser:WARN] aviso\n[HyperFrames] render runtime fps\nRender complete") == []


LIMPIO = {"remotas": [], "mallas_error": None, "errores_consola": [], "timeline": True, "_log": "sonda.json"}


@pytest.mark.parametrize(
    ("cambio", "motivo"),
    [
        ({"remotas": ["https://remoto.invalid/x.png"]}, "de fuera"),
        ({"mallas_error": "[mallas] no carga: x"}, "data-mallas-error"),
        ({"errores_consola": ["Uncaught TypeError"]}, "errores de consola"),
        ({"timeline": False}, "__timelines.main"),
        ({"mallas": {"adaptador": {"fallback": True}}}, "respaldo"),
        ({"fallo": "no arrancó Chrome"}, "no pudo probar"),
    ],
)
def test_cada_problema_de_la_sonda_para_el_render(cambio, motivo):
    with pytest.raises(render.ErrorDeRender, match=motivo):
        render.comprueba_sonda({**LIMPIO, **cambio})


def test_control_un_informe_limpio_de_la_sonda_pasa():
    render.comprueba_sonda(dict(LIMPIO))


# ---------------------------------------------------------------------------- recomendaciones de la auditoría
def test_orpheus_cargado_no_deja_espacio_para_el_render(monkeypatch):
    """El umbral viejo (2048) dejaba pasar a Orpheus, que deja 2.517 MB libres (recomendación 3)."""
    monkeypatch.setattr(render, "procesos_de_gpu", lambda: ESCRITORIO)
    monkeypatch.setattr(render, "memoria_libre_gpu_mb", lambda: LIBRE_CON_ORPHEUS_MB)
    with pytest.raises(render.ErrorDeRender, match="otro trabajo de GPU"):
        render.exige_gpu_libre()


def test_control_en_reposo_la_gpu_si_se_da_por_libre(monkeypatch):
    monkeypatch.setattr(render, "procesos_de_gpu", lambda: ESCRITORIO)
    monkeypatch.setattr(render, "memoria_libre_gpu_mb", lambda: LIBRE_EN_REPOSO_MB)
    assert render.exige_gpu_libre() == LIBRE_EN_REPOSO_MB


def test_llama_server_en_la_gpu_para_el_render_aunque_sobre_memoria(monkeypatch):
    """Por el nombre del proceso: un GGUF más pequeño dejaría memoria libre de sobra y seguiría en la GPU."""
    monkeypatch.setattr(config, "LLAMA_SERVER", Path(LLAMA_SERVER_VISTO))  # la que declara el `.env`
    monkeypatch.setattr(render, "procesos_de_gpu", lambda: [*ESCRITORIO, LLAMA_SERVER_VISTO])
    monkeypatch.setattr(render, "memoria_libre_gpu_mb", lambda: LIBRE_EN_REPOSO_MB)
    with pytest.raises(render.ErrorDeRender, match="llama-server"):
        render.exige_gpu_libre()


def test_sin_LLAMA_SERVER_en_el_env_se_le_reconoce_por_el_nombre_del_ejecutable(monkeypatch):
    """Sin la ruta en el `.env`, el render solo lo cazaba por el umbral de memoria, y el aviso perdía el motivo."""
    monkeypatch.setattr(config, "LLAMA_SERVER", Path("(falta LLAMA_SERVER en el .env)"))
    monkeypatch.setattr(render, "procesos_de_gpu", lambda: [*ESCRITORIO, LLAMA_SERVER_VISTO])
    # Con memoria de sobra: el aviso del umbral también nombra a llama-server, y aquí solo cuenta el nombre.
    monkeypatch.setattr(render, "memoria_libre_gpu_mb", lambda: LIBRE_EN_REPOSO_MB)
    with pytest.raises(render.ErrorDeRender, match="otro trabajo del estudio.*llama-server"):
        render.exige_gpu_libre()
    # Control: otro ejecutable con «llama» en la ruta no es un llama-server.
    monkeypatch.setattr(render, "procesos_de_gpu", lambda: [*ESCRITORIO, r"X:\llama-server\otro.exe"])
    assert render.trabajos_de_gpu_en_marcha() == []


def test_comfyui_en_la_gpu_para_el_render_si_nvidia_smi_lo_da_con_su_ruta(monkeypatch):
    monkeypatch.setattr(config, "COMFY_ROOT", COMFY_ROOT_VISTO)  # la que declara el `.env`
    comfy = str(COMFY_ROOT_VISTO / ".venv" / "Scripts" / "python.exe")
    monkeypatch.setattr(render, "procesos_de_gpu", lambda: [*ESCRITORIO, comfy])
    monkeypatch.setattr(render, "memoria_libre_gpu_mb", lambda: LIBRE_EN_REPOSO_MB)
    with pytest.raises(render.ErrorDeRender, match="ComfyUI|otro trabajo del estudio"):
        render.exige_gpu_libre()


def _render_falso(monkeypatch, tmp_path, codigo: int, texto: str = "Render complete"):
    """render.render sin Chrome: la validación pasa y la «CLI» deja un MP4 y devuelve `codigo`."""
    monkeypatch.setattr(render, "_fps", lambda carpeta: "24")
    monkeypatch.setattr(render, "valida", lambda *a, **k: {})
    monkeypatch.setattr(render, "exige_gpu_libre", lambda *a, **k: LIBRE_EN_REPOSO_MB)
    ordenes = []

    def cli(orden, carpeta, dir_log, nombre, timeout):
        ordenes.append(orden)
        Path(orden[orden.index("-o") + 1]).write_bytes(b"mp4 a medias")
        return texto, tmp_path / "render.log", codigo

    monkeypatch.setattr(render, "_cli", cli)
    return ordenes


def test_un_render_que_sale_con_error_no_deja_el_mp4_parcial(monkeypatch, tmp_path):
    """Recomendación 2: antes solo se borraba con «[mallas]» o un error de página."""
    _render_falso(monkeypatch, tmp_path, codigo=1)
    salida = tmp_path / "salida.mp4"
    with pytest.raises(render.ErrorDeRender, match="código 1"):
        render.render(tmp_path, salida, tmp_path / "log")
    assert not salida.exists()


def test_control_un_render_limpio_conserva_su_mp4(monkeypatch, tmp_path):
    _render_falso(monkeypatch, tmp_path, codigo=0)
    salida = tmp_path / "salida.mp4"
    assert render.render(tmp_path, salida, tmp_path / "log") == salida
    assert salida.read_bytes() == b"mp4 a medias"


def test_hyperframes_escribe_en_una_ruta_corta_y_el_video_llega_a_su_sitio(monkeypatch, tmp_path):
    """F6.3: la carpeta de trabajo que HyperFrames crea junto a su salida no cabía en MAX_PATH dentro de un run
    (ENOENT en `mkdtemp`, medido en la puerta de reproducción). Escribe en `ESCENA_RENDER_TMP` y el vídeo se mueve."""
    corta = tmp_path / "t"
    monkeypatch.setattr(render.config, "ESCENA_RENDER_TMP", corta)
    ordenes = _render_falso(monkeypatch, tmp_path, codigo=0)
    salida = tmp_path / ("run-" + "x" * 60) / "subir-al-canal" / "final.mp4"
    assert render.render(tmp_path, salida, tmp_path / "log") == salida
    assert salida.read_bytes() == b"mp4 a medias"
    escrito = Path(ordenes[0][ordenes[0].index("-o") + 1])
    assert escrito.parent.parent == corta and escrito != salida
    assert list(corta.iterdir()) == [], "la carpeta de trabajo se borra"


def test_control_un_render_fallido_no_deja_ni_el_video_ni_su_carpeta_de_trabajo(monkeypatch, tmp_path):
    corta = tmp_path / "t"
    monkeypatch.setattr(render.config, "ESCENA_RENDER_TMP", corta)
    _render_falso(monkeypatch, tmp_path, codigo=1)
    salida = tmp_path / "run" / "final.mp4"
    with pytest.raises(render.ErrorDeRender, match="código 1"):
        render.render(tmp_path, salida, tmp_path / "log")
    assert not salida.exists() and list(corta.iterdir()) == []


def test_el_render_va_sin_best_effort(monkeypatch, tmp_path):
    """Recomendación 1: un medio que no carga para el render en vez de salir con un aviso."""
    ordenes = _render_falso(monkeypatch, tmp_path, codigo=0)
    render.render(tmp_path, tmp_path / "salida.mp4", tmp_path / "log")
    assert "--no-best-effort" in ordenes[0]


def test_el_aviso_de_un_medio_sin_cargar_tumba_el_render():
    """Aunque se quitase `--no-best-effort`, el aviso de HyperFrames sigue parando el render."""
    linea = "[FrameCapture:media_load_failed] image media failed to load before capture {}"
    assert render.errores_del_log(linea) == [linea]


# ------------------------------------------------------------------------------ el obrero, por su cerrojo (F6.2d)
def _pid_muerto() -> int:
    """El pid de un proceso que ya ha acabado."""
    proceso = subprocess.Popen([sys.executable, "-c", "pass"])
    proceso.wait()
    return proceso.pid


def test_un_proceso_vivo_y_uno_que_ya_acabo():
    assert render.proceso_vivo(os.getpid())
    assert not render.proceso_vivo(_pid_muerto())
    assert not render.proceso_vivo(0)


def test_el_obrero_en_marcha_para_otro_trabajo_de_gpu_aunque_sobre_memoria(monkeypatch, tmp_path):
    """Auditoría de F6.2c, recomendación 3: nvidia-smi da al obrero como un Python cualquiera y su pico (2.864 MB)
    queda bajo el umbral, así que ni el nombre ni la memoria lo veían. Se le reconoce por su cerrojo."""
    cerrojo = tmp_path / "obrero.cerrojo"
    monkeypatch.setattr(config, "ESCENA_CERROJO_OBRERO", cerrojo)
    monkeypatch.setattr(render, "procesos_de_gpu", lambda: ESCRITORIO + [r"C:\Python314\python.exe"])
    monkeypatch.setattr(render, "memoria_libre_gpu_mb", lambda: LIBRE_EN_REPOSO_MB)
    render.toma_cerrojo(cerrojo, os.getpid(), "obrero de escena: prueba")
    assert any(t.startswith("obrero de escena") for t in render.trabajos_de_gpu_en_marcha())
    with pytest.raises(render.ErrorDeRender, match="obrero de escena"):
        render.exige_gpu_libre()
    render.suelta_cerrojo(cerrojo, os.getpid())
    assert render.exige_gpu_libre() == LIBRE_EN_REPOSO_MB, "control: sin el obrero, la misma GPU está libre"


def test_control_el_cerrojo_de_un_obrero_que_murio_no_bloquea_y_se_borra(monkeypatch, tmp_path):
    cerrojo = tmp_path / "obrero.cerrojo"
    monkeypatch.setattr(config, "ESCENA_CERROJO_OBRERO", cerrojo)
    monkeypatch.setattr(render, "procesos_de_gpu", lambda: ESCRITORIO)
    render.toma_cerrojo(cerrojo, _pid_muerto(), "obrero de escena: cortado a mitad")
    assert render.trabajos_de_gpu_en_marcha() == []
    assert not cerrojo.exists()


def test_soltar_el_cerrojo_de_otro_no_lo_suelta(tmp_path):
    cerrojo = tmp_path / "obrero.cerrojo"
    render.toma_cerrojo(cerrojo, os.getpid(), "obrero de escena: el de verdad")
    render.suelta_cerrojo(cerrojo, os.getpid() + 1)
    assert cerrojo.exists()


# ------------------------------------------------------------------------- el árbol vigilado (OC2.5, deuda 2)
# El Python que hace de etapa: lanza con `_corre_vigilado` un node que lanza un nieto, y se queda esperando. Con
# «sin-job», el mismo código sin el Job Object: el control negativo.
ETAPA = """
import sys
sys.path.insert(0, sys.argv[1])
from lib.escena import render
if sys.argv[4] == "sin-job":
    render._job_que_mata_al_cerrar = lambda pid: None
render._corre_vigilado([sys.argv[2], "-e", sys.argv[3], sys.argv[5]], timeout=600)
"""
# El sustituto de la CLI: node lanza otro node (como lanza Chrome), apunta los dos pid y espera.
HIJO = """
const espera = ["-e", "setInterval(() => {}, 1000)"];
const nieto = require("child_process").spawn(process.execPath, espera, {stdio: "ignore"});
require("fs").writeFileSync(process.argv[1], JSON.stringify({hijo: process.pid, nieto: nieto.pid}));
setInterval(() => {}, 1000);
"""
_SINCRONIZA_Y_MATA = 0x00100000 | 0x1000 | 0x0001  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION | TERMINATE


def _kernel32():
    import ctypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    return k


def _arbol_tras_matar_a_la_etapa(tmp_path: Path, modo: str) -> dict[str, bool]:
    """Lanza la etapa, la mata con `taskkill /F` y dice, 5 s después, qué procesos de su árbol siguen vivos.

    **Solo se toca lo que creó la prueba**: los pid los apuntan el hijo y el nieto, y se abren sus asas antes de matar
    a la etapa. Con el asa abierta, el pid no puede pasar a otro proceso, así que se mira y se mata a ese proceso y no
    a otro que hubiera heredado el número. Lo que sobreviva (el control negativo) se mata por su asa al final.
    """
    from utiles_escena import node

    k = _kernel32()
    pids = tmp_path / f"pids-{modo}.json"
    etapa = subprocess.Popen(
        [sys.executable, "-c", ETAPA, str(config.BASE_DIR), node(), HIJO, modo, str(pids)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    asas = {}
    try:
        for _ in range(300):
            try:
                apuntados = json.loads(pids.read_text(encoding="utf-8"))
                break
            except (OSError, ValueError):
                assert etapa.poll() is None, "la etapa acabó antes de lanzar el árbol"
                time.sleep(0.1)
        else:
            pytest.fail("el hijo no apuntó los pid en 30 s")
        asas = {quien: k.OpenProcess(_SINCRONIZA_Y_MATA, False, pid) for quien, pid in apuntados.items()}
        assert all(asas.values()), f"no se pudo abrir el árbol recién lanzado: {apuntados}"
        subprocess.run(["taskkill", "/F", "/PID", str(etapa.pid)], capture_output=True, check=True)
        etapa.wait(timeout=30)
        # WaitForSingleObject da 0 si el proceso acabó y 258 si sigue vivo al cabo del plazo.
        return {quien: k.WaitForSingleObject(asa, 5000) != 0 for quien, asa in asas.items()}
    finally:
        for asa in asas.values():
            if asa:
                k.TerminateProcess(asa, 1)
                k.CloseHandle(asa)
        if etapa.poll() is None:
            etapa.kill()


@pytest.mark.skipif(os.name != "nt", reason="el Job Object es de Windows, y Lanternist solo corre en Windows")
def test_si_la_etapa_muere_su_node_y_lo_que_lanzo_mueren_con_ella(tmp_path):
    """Deuda 2: con `HYPERFRAMES_RENDER_DETACHED=1`, nada vigilaba a node ni a Chrome si moría la etapa de Python."""
    from utiles_escena import node

    if node() is None:
        pytest.skip("no hay node (lo instala fnm, ver .node-version)")
    assert _arbol_tras_matar_a_la_etapa(tmp_path, "con-job") == {"hijo": False, "nieto": False}


@pytest.mark.skipif(os.name != "nt", reason="el Job Object es de Windows, y Lanternist solo corre en Windows")
def test_control_sin_el_job_el_node_y_lo_que_lanzo_sobreviven_a_la_etapa(tmp_path):
    from utiles_escena import node

    if node() is None:
        pytest.skip("no hay node (lo instala fnm, ver .node-version)")
    assert _arbol_tras_matar_a_la_etapa(tmp_path, "sin-job") == {"hijo": True, "nieto": True}


@pytest.mark.skipif(os.name != "nt", reason="el Job Object es de Windows, y Lanternist solo corre en Windows")
def test_un_timeout_mata_el_arbol_entero_y_no_espera_a_los_nietos(tmp_path):
    """`subprocess.run` solo mataba a node y esperaba las tuberías, que un nieto vivo mantiene abiertas."""
    nieto = tmp_path / "nieto.pid"
    codigo = (
        "import subprocess, sys, time\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open(r'{nieto}', 'w').write(str(p.pid))\n"
        "time.sleep(120)\n"
    )
    inicio = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        render._corre_vigilado([sys.executable, "-c", codigo], timeout=5, text=True)
    assert time.monotonic() - inicio < 30, "esperó al nieto"
    assert not render.proceso_vivo(int(nieto.read_text(encoding="utf-8")))
