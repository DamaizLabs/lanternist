r"""El instalador de Lanternist: deja el motor listo para producir en un PC con Windows y una NVIDIA (OC1.7).

    py -3.12 instala.py                  # todos los pasos; repetirlo retoma donde se cortó y no rehace nada
    py -3.12 instala.py --comprueba      # qué falta, sin instalar ni bajar nada
    py -3.12 instala.py --paso pesos     # un paso solo (los nombres, en PASOS o con --help)
    py -3.12 instala.py --claves         # las claves de YouTube, escritas en TU terminal: nunca pasan por el chat

**Solo usa la biblioteca estándar**, porque corre antes de que exista ningún entorno. Lanternist usa un solo Python,
el 3.12: con él instalan los tres entornos y el de ComfyUI (`progress/impl_OC1.7.md`).

**Qué baja y adónde.** Lo pesado (ComfyUI, llama.cpp, el GGUF de Orpheus y el Chrome con WebGPU) va por defecto a
`herramientas/`, dentro de esta carpeta y fuera de git. Si el `.env` ya declara una ruta (`COMFY_ROOT`, `LLAMA_SERVER`,
`LLAMA_MODELO_GGUF` o `CHROME_WEBGPU_MANIFIESTO`), se usa esa y no se reinstala nada: solo se comprueban sus pesos. Los
modelos de Hugging Face van a su caché y los pesos de la marca de IA, a la carpeta de pesos de torch. Cada fichero
sale de la lista fija `datos/descargas.json`, con su URL a una revisión fija y su sha256: el usuario no elige nada.

**Repetible y reanudable.** Cada paso mira primero qué falta. Una descarga cortada deja su `.part` y la siguiente vez
sigue desde ahí (cabecera `Range`). Lo que llega con otro sha256 se borra y no se usa. Un fichero que ya estaba con
otro sha256 no se toca: se dice cuál es y se para, porque puede ser de otro proyecto. No se reintenta nada solo.

**Nada de claves en la línea de órdenes.** Ningún paso las necesita: la subida a mano no pide ninguna. `--claves` las
pide con `getpass`, sin eco, y las escribe en el `.env`, que nunca entra en git.
"""

from __future__ import annotations

import argparse
import getpass
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from lib import marca_ia  # noqa: E402  (solo biblioteca estándar: es lo que dice el docstring de lib/marca_ia.py)

HERRAMIENTAS = RAIZ / "herramientas"
LISTA = RAIZ / "datos" / "descargas.json"
REQUISITOS_COMFYUI = RAIZ / "datos" / "comfyui-requisitos.txt"
ENV = RAIZ / ".env"
ENV_EJEMPLO = RAIZ / ".env.example"
VERSION_PYTHON = (3, 12)
INDICE_CU126 = "https://download.pytorch.org/whl/cu126"
INDICE_CU130 = "https://download.pytorch.org/whl/cu130"
# Lo que deja cada entorno al terminar: las órdenes de pip y el sha256 de sus requisitos. Si cambian, se repite pip.
MARCA_DE_ENTORNO = "instalado-por-lanternist.json"
AGENTE = "lanternist-instala"

# Las recetas de los entornos: las de la cabecera de cada fichero de requisitos, en el orden que importa.
ENTORNOS = {
    ".venv": [["-r", "requirements.txt"]],
    ".venv-voz": [
        ["-r", "spikes/requirements-voz.txt", "--extra-index-url", INDICE_CU126],
        ["--no-deps", "snac==1.2.1"],
    ],
    # Primero torch y torchvision de CUDA: si no, spandrel trae el torch de CPU de PyPI (la trampa de su cabecera).
    ".venv-escena": [
        ["torch==2.13.0+cu130", "torchvision==0.28.0+cu130", "--index-url", INDICE_CU130],
        ["-r", "spikes/requirements-escena.txt"],
    ],
}


class ErrorDeInstalacion(RuntimeError):
    """Un paso no puede seguir. El mensaje dice qué falta y qué hacer."""


def _di(texto: str) -> None:
    print(texto, flush=True)


# ---------------------------------------------------------------------------------------------------------------
# El .env: se lee y se escribe sin python-dotenv, que aún no está instalado
# ---------------------------------------------------------------------------------------------------------------
def lee_env(ruta: Path | None = None) -> dict[str, str]:
    """Las claves con valor del `.env`, como las lee python-dotenv: sin comillas y sin el comentario del final."""
    ruta = ruta or ENV
    valores = {}
    if not ruta.is_file():
        return valores
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = (parte.strip() for parte in linea.split("=", 1))
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        elif valor.startswith("#"):
            valor = ""  # `CLAVE=   # comentario` es una clave vacía, como en `.env.example`
        else:
            valor = re.split(r"\s+#", valor, maxsplit=1)[0].strip()
        valores[clave] = valor
    return valores


def escribe_env(clave: str, valor: str, ruta: Path | None = None) -> None:
    """Pone `clave=valor` en el `.env`: sustituye su línea si la hay, o la añade al final. El resto no se toca."""
    ruta = ruta or ENV
    lineas = ruta.read_text(encoding="utf-8").splitlines() if ruta.is_file() else []
    patron = re.compile(rf"^\s*{re.escape(clave)}\s*=")
    for n, linea in enumerate(lineas):
        if patron.match(linea):
            lineas[n] = f"{clave}={valor}"
            break
    else:
        lineas.append(f"{clave}={valor}")
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def variable(nombre: str) -> str:
    """Como `lib/config.py`: el entorno del proceso manda sobre el `.env`."""
    return os.environ.get(nombre, "").strip() or lee_env().get(nombre, "")


# ---------------------------------------------------------------------------------------------------------------
# La lista fija y dónde va cada fichero
# ---------------------------------------------------------------------------------------------------------------
def lista() -> dict:
    return json.loads(LISTA.read_text(encoding="utf-8"))


def ficheros_del_paso(paso: str) -> list[dict]:
    return [f for f in lista()["ficheros"] if f["paso"] == paso]


def raiz_de_comfyui() -> Path:
    return Path(variable("COMFY_ROOT") or HERRAMIENTAS / "ComfyUI")


def cache_de_hugging_face() -> Path:
    """Donde la busca `huggingface_hub`: `HF_HUB_CACHE`, `HF_HOME/hub` o `~/.cache/huggingface/hub`."""
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"]) / "hub"
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "huggingface" / "hub"


def destino_de(fichero: dict) -> Path:
    """La ruta de un fichero de la lista: la de su variable si el `.env` la declara, o la de su tramo `destino`."""
    if fichero.get("variable") and variable(fichero["variable"]):
        return Path(variable(fichero["variable"]))
    base, ruta = fichero["destino"].split("/", 1)
    bases = {
        "comfyui": raiz_de_comfyui,
        "huggingface": cache_de_hugging_face,
        "torch": marca_ia.dir_de_pesos,
        "herramientas": lambda: HERRAMIENTAS,
    }
    if base not in bases:
        raise ErrorDeInstalacion(f"{LISTA.name}: «{fichero['id']}» tiene un destino que no se entiende ({base})")
    return bases[base]() / ruta


def apunta_la_revision(fichero: dict, solo_mira: bool = False) -> str | None:
    """En la caché de Hugging Face, `refs/main` dice qué instantánea carga la biblioteca sin red: la de la lista.

    Si apunta a otra, la corrige (salvo con `solo_mira`) y devuelve el repositorio; si ya está bien, None.
    """
    base, ruta = fichero["destino"].split("/", 1)
    if base != "huggingface":
        return None
    carpeta, _, revision = ruta.split("/")[:3]
    refs = cache_de_hugging_face() / carpeta / "refs" / "main"
    if refs.is_file() and refs.read_text(encoding="utf-8").strip() == revision:
        return None
    if not solo_mira:
        refs.parent.mkdir(parents=True, exist_ok=True)
        refs.write_text(revision, encoding="utf-8")
    return carpeta


# ---------------------------------------------------------------------------------------------------------------
# La descarga: reanudable, con su sha256 al final
# ---------------------------------------------------------------------------------------------------------------
def sha256_de(ruta: Path) -> str:
    return marca_ia.sha256_de(ruta)


def _gb(n: int) -> str:
    return f"{n / 1e9:.2f} GB" if n >= 1e8 else f"{n / 1e6:.1f} MB"


def estado(fichero: dict) -> str:
    """«ok» si está con su sha256, «falta» si no está, «distinto» si está con otro."""
    destino = destino_de(fichero)
    if not destino.is_file():
        return "falta"
    if destino.stat().st_size != fichero["bytes"] or sha256_de(destino) != fichero["sha256"]:
        return "distinto"
    return "ok"


def descarga(fichero: dict, destino: Path, abre=urllib.request.urlopen) -> None:
    """Baja `fichero` a `destino` por un `.part` que se retoma con `Range`. Si llega con otro sha256, no queda nada.

    Un corte (de red o del usuario) deja el `.part` para la siguiente vez. `abre` es `urlopen`; las pruebas le pasan
    uno falso.
    """
    total = int(fichero["bytes"])
    parcial = destino.with_name(destino.name + ".part")
    destino.parent.mkdir(parents=True, exist_ok=True)
    hecho = parcial.stat().st_size if parcial.is_file() else 0
    if hecho > total:
        parcial.unlink()
        hecho = 0
    if hecho < total:
        cabeceras = {"User-Agent": AGENTE}
        if hecho:
            cabeceras["Range"] = f"bytes={hecho}-"
        _di(f"    bajando {destino.name} ({_gb(total)})" + (f", desde {_gb(hecho)}" if hecho else ""))
        try:
            # La URL sale de la lista fija, siempre https, y lo que llega se comprueba por su sha256.
            with abre(urllib.request.Request(fichero["url"], headers=cabeceras), timeout=60) as respuesta:
                if hecho and getattr(respuesta, "status", 200) != 206:
                    hecho = 0  # el servidor no admite seguir: se empieza de cero
                aviso = hecho + total // 10
                with open(parcial, "ab" if hecho else "wb") as salida:
                    for trozo in iter(lambda: respuesta.read(1 << 20), b""):
                        salida.write(trozo)
                        hecho += len(trozo)
                        if hecho >= aviso and hecho < total:
                            _di(f"      {100 * hecho / total:.0f} %")
                            aviso = hecho + total // 10
        except (OSError, http.client.HTTPException) as error:
            raise ErrorDeInstalacion(
                f"la descarga de {destino.name} se cortó ({type(error).__name__}: {error}). Lo bajado se queda en "
                f"{parcial.name}: repite la orden y sigue desde ahí"
            ) from None
    recibido = sha256_de(parcial)
    if recibido != fichero["sha256"]:
        parcial.unlink(missing_ok=True)
        raise ErrorDeInstalacion(
            f"{destino.name} ha llegado con otro sha256 ({recibido[:12]}…, y la lista dice {fichero['sha256'][:12]}…): "
            "no es el fichero comprobado, así que se ha borrado y no se usa. Si al repetir pasa otra vez, la fuente "
            f"ha cambiado: {fichero['url']}"
        )
    parcial.replace(destino)


def asegura(ficheros: list[dict], solo_mira: bool, abre=urllib.request.urlopen) -> list[str]:
    """Que cada fichero esté con su sha256: baja los que faltan. Devuelve lo que faltaba.

    Un fichero que ya está con otro sha256 no se sustituye: puede ser de otro proyecto que comparte la carpeta.
    """
    faltan, distintos, revisiones = [], [], set()
    for fichero in ficheros:
        cual = estado(fichero)
        if cual == "distinto":
            distintos.append(f"{destino_de(fichero)} (se espera el sha256 {fichero['sha256'][:12]}…)")
        elif cual == "falta":
            faltan.append(fichero)
        elif carpeta := apunta_la_revision(fichero, solo_mira):
            revisiones.add(f"la revisión de {carpeta} en la caché de Hugging Face (refs/main)")
    if distintos:
        raise ErrorDeInstalacion(
            "estos ficheros ya están, pero no son los comprobados, y no se tocan: " + "; ".join(distintos) + ". "
            "Muévelos o bórralos y repite, o apunta el .env a una carpeta que no los tenga"
        )
    # Los ficheros de un mismo modelo (las 54 voces de Kokoro) se cuentan juntos: «Kokoro-82M…: 25 ficheros (13 MB)».
    grupos: dict[str, list[dict]] = {}
    for fichero in faltan:
        grupos.setdefault(fichero["nombre"].split(": ")[0], []).append(fichero)
    nombres = [
        f"{v[0]['nombre']} ({_gb(v[0]['bytes'])})"
        if len(v) == 1
        else f"{k}: {len(v)} ficheros ({_gb(sum(f['bytes'] for f in v))})"
        for k, v in grupos.items()
    ] + sorted(revisiones)
    if faltan and not solo_mira:
        _di(f"  faltan {len(faltan)} de {len(ficheros)}: {_gb(sum(f['bytes'] for f in faltan))} por bajar")
        for fichero in faltan:
            descarga(fichero, destino_de(fichero), abre)
            apunta_la_revision(fichero)
    return nombres


# ---------------------------------------------------------------------------------------------------------------
# Órdenes, git y entornos
# ---------------------------------------------------------------------------------------------------------------
def corre(orden: list[str], cwd: Path = RAIZ, que: str = "", env: dict | None = None) -> None:
    """Lanza una orden con su salida a la vista. Si falla, el paso para con su código."""
    _di(f"    $ {' '.join(str(p) for p in orden)}")
    codigo = subprocess.run([str(p) for p in orden], cwd=str(cwd), env=env).returncode
    if codigo != 0:
        raise ErrorDeInstalacion(f"{que or orden[0]} falló (código {codigo}): mira la salida de arriba y repite")


def python_de(entorno: Path) -> Path:
    return entorno / "Scripts" / "python.exe"


def huella_de_receta(receta: list[list[str]], cwd: Path = RAIZ) -> dict:
    """Las órdenes de pip y el sha256 de cada fichero de requisitos que nombran."""
    ficheros = {}
    for argumentos in receta:
        for n, argumento in enumerate(argumentos):
            if argumento == "-r":
                ruta = Path(argumentos[n + 1])
                ficheros[argumentos[n + 1]] = sha256_de(ruta if ruta.is_absolute() else cwd / ruta)
    return {"ordenes": receta, "requisitos": ficheros}


def entorno_hecho(entorno: Path, receta: list[list[str]], cwd: Path = RAIZ) -> bool:
    marca = entorno / MARCA_DE_ENTORNO
    if not python_de(entorno).is_file() or not marca.is_file():
        return False
    return json.loads(marca.read_text(encoding="utf-8")) == huella_de_receta(receta, cwd)


def version_del_entorno(entorno: Path) -> str | None:
    """La versión de Python con que se creó un entorno, de su `pyvenv.cfg`, o None si no la dice."""
    cfg = entorno / "pyvenv.cfg"
    if not cfg.is_file():
        return None
    for linea in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        clave, _, valor = linea.partition("=")
        if clave.strip() in ("version", "version_info"):
            return valor.strip()
    return None


def crea_entorno(entorno: Path, receta: list[list[str]], cwd: Path = RAIZ) -> None:
    """Crea el entorno con este Python (3.12) si no existe, y le pasa cada orden de pip. Deja su marca al acabar.

    Un entorno que ya existe con otro Python no se toca: pasarle la receta lo dejaría a medias y con la marca de
    hecho (R1 de la revisión de OC1.7). Lo borra o lo renombra el usuario, porque no lo creó el instalador."""
    if not python_de(entorno).is_file():
        corre([sys.executable, "-m", "venv", entorno], cwd, f"crear {entorno.name}")
    else:
        version = version_del_entorno(entorno)
        esperada = f"{sys.version_info.major}.{sys.version_info.minor}"
        if version and ".".join(version.split(".")[:2]) != esperada:
            raise ErrorDeInstalacion(
                f"{entorno.name} ya existe y es de Python {version}, y Lanternist lo crea con Python {esperada}: "
                f"bórralo o cámbiale el nombre, y repite. El instalador no borra un entorno que no creó él"
            )
    for argumentos in receta:
        corre(
            [python_de(entorno), "-m", "pip", "install", "--disable-pip-version-check", *argumentos],
            cwd,
            f"pip en {entorno.name}",
        )
    (entorno / MARCA_DE_ENTORNO).write_text(json.dumps(huella_de_receta(receta, cwd), indent=2), encoding="utf-8")


def commit_de(carpeta: Path) -> str | None:
    """El commit de un repositorio de git, o None. Sin `.git` propio no se pregunta: git subiría al de Lanternist."""
    if not (carpeta / ".git").exists():
        return None
    r = subprocess.run(["git", "-C", str(carpeta), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def clona(repo: dict, carpeta: Path) -> None:
    """Trae SOLO el commit fijado (sin historia) y lo deja sacado. Repetible: retoma un `fetch` cortado.

    Con `core.longpaths`: en una carpeta honda, git en Windows no puede escribir sus objetos sin ella (medido en OC1.7).
    """
    carpeta.mkdir(parents=True, exist_ok=True)
    git = ["git", "-c", "core.longpaths=true", "-C", carpeta]
    if not (carpeta / ".git").exists():
        corre(["git", "-c", "core.longpaths=true", "init", "-q", carpeta], RAIZ, "git init")
        corre([*git, "config", "core.longpaths", "true"], RAIZ, "git config")
    remoto = subprocess.run(["git", "-C", str(carpeta), "remote"], capture_output=True, text=True).stdout.split()
    if "origin" not in remoto:
        corre([*git, "remote", "add", "origin", repo["url"]], RAIZ, "git remote")
    corre([*git, "fetch", "-q", "--depth", "1", "origin", repo["commit"]], RAIZ, "git fetch")
    corre([*git, "checkout", "-q", "--detach", repo["commit"]], RAIZ, "git checkout")


def _node() -> Path | None:
    """El node del PATH o el alias por defecto de fnm, como `lib/escena/render.py → node_exe`."""
    en_path = shutil.which("node")
    if en_path:
        return Path(en_path)
    fnm = Path(os.environ.get("APPDATA", "")) / "fnm" / "aliases" / "default" / "node.exe"
    return fnm if fnm.is_file() else None


def _librerias_dxc() -> tuple[Path, Path]:
    """`dxil.dll` y `dxcompiler.dll`, sacadas del Chrome for Testing de la misma versión que el Chrome headless.

    WebGPU las necesita y el headless de HyperFrames no las trae. Hasta OC1.7 se copiaban del Google Chrome del usuario,
    y el Chrome 155 ya no trae `dxil.dll` (medido el 24-10-2026). Devuelve la carpeta que contiene la de las dos DLL,
    que es lo que pide `scripts/instala_chrome_webgpu.ps1 -ChromeSistema`, y el zip, que se borra cuando el Chrome con
    WebGPU ya está: si el script falla, la siguiente vez no se vuelve a bajar.
    """
    zips = [f for f in ficheros_del_paso("escena") if f["destino"].endswith(".zip")]
    asegura(zips, solo_mira=False)
    origen = destino_de(zips[0])
    carpeta = HERRAMIENTAS / "dxc" / origen.stem
    carpeta.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(origen) as z:
        for nombre in ("dxil.dll", "dxcompiler.dll"):
            (carpeta / nombre).write_bytes(z.read(f"chrome-win64/{nombre}"))
    return carpeta.parent, origen


# ---------------------------------------------------------------------------------------------------------------
# Los pasos. Cada uno recibe `solo_mira` y devuelve lo que faltaba; sin `solo_mira`, además lo instala
# ---------------------------------------------------------------------------------------------------------------
# Lo más hondo que crean los entornos dentro de la carpeta de Lanternist, medido el 24-10-2026 (OC1.7): una DLL de
# numpy en `.venv-voz` (123 caracteres) y una licencia dentro de torch en el entorno de ComfyUI (218). Windows no carga
# una DLL de una ruta de más de 259 caracteres aunque las rutas largas estén activas: ComfyUI no arrancaba en una
# carpeta de 194. Y sin las rutas largas activas, pip no puede escribir la licencia de torch.
HONDURA_DE_LAS_DLL = 123
HONDURA_MAXIMA = 218
MAX_PATH = 259
ACTIVA_RUTAS_LARGAS = (
    "New-ItemProperty -Path HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem -Name LongPathsEnabled -Value 1 "
    "-PropertyType DWORD -Force"
)


def rutas_largas_activas() -> bool:
    try:
        import winreg

        clave = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem")
        return winreg.QueryValueEx(clave, "LongPathsEnabled")[0] == 1
    except OSError:
        return False


def problema_de_ruta(raiz: Path, largas: bool) -> str | None:
    """Si la carpeta de Lanternist es demasiado larga para lo que se instala dentro, qué hacer; si no, None."""
    if len(str(raiz)) + 1 + HONDURA_DE_LAS_DLL > MAX_PATH:
        return (
            f"la carpeta de Lanternist ({len(str(raiz))} caracteres) es demasiado larga: Windows no carga una DLL de "
            f"una ruta de más de {MAX_PATH}. Muévela a una corta, como C:\\lanternist, y repite"
        )
    if not largas and len(str(raiz)) + 1 + HONDURA_MAXIMA > MAX_PATH:
        return (
            f"la carpeta de Lanternist tiene {len(str(raiz))} caracteres y las rutas largas de Windows están "
            f"apagadas, así que pip no podrá instalar torch. Muévela a una de {MAX_PATH - 1 - HONDURA_MAXIMA} "
            f"caracteres como mucho (C:\\lanternist), o enciéndelas en una PowerShell de administrador: "
            f"{ACTIVA_RUTAS_LARGAS}"
        )
    return None


def paso_requisitos(solo_mira: bool) -> list[str]:
    """Lo que el instalador no instala: es software del sistema, y ponerlo en el PC de alguien es decisión suya."""
    version_node = (RAIZ / ".node-version").read_text(encoding="utf-8").strip().lstrip("v")
    v = version_node
    fnm = f"winget install -e --id Schniz.fnm; y en una terminal nueva, fnm install {v} y fnm default {v}"
    node = _node()
    faltan = []
    for nombre, encontrado, orden in (
        ("git", shutil.which("git"), "winget install -e --id Git.Git"),
        (f"Node {version_node}", node, fnm),
        ("npm", node and (shutil.which("npm") or (node.parent / "npm.cmd").is_file()), fnm),
        ("ffmpeg y ffprobe", shutil.which("ffmpeg") and shutil.which("ffprobe"), "winget install -e --id Gyan.FFmpeg"),
        ("el controlador de NVIDIA (nvidia-smi)", shutil.which("nvidia-smi"), "el de tu tarjeta: nvidia.com/drivers"),
    ):
        if not encontrado:
            faltan.append(f"{nombre}: {orden}")
    ruta = problema_de_ruta(RAIZ, rutas_largas_activas())
    if ruta:
        faltan.append(ruta)
    if node:
        dice = subprocess.run([str(node), "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
        if dice != version_node:
            _di(f"  aviso: node es {dice} y Lanternist se prueba con {version_node} (.node-version): {fnm}")
    if faltan and not solo_mira:
        raise ErrorDeInstalacion(
            "falta algo del sistema. Resuélvelo, abre una terminal nueva y repite:\n    " + "\n    ".join(faltan)
        )
    return faltan


def paso_env(solo_mira: bool) -> list[str]:
    """El `.env`, copiado de `.env.example` si no existe. Los pasos siguientes escriben en él sus rutas."""
    if ENV.is_file():
        return []
    if not solo_mira:
        shutil.copyfile(ENV_EJEMPLO, ENV)
    return [".env (copia de .env.example)"]


def paso_entornos(solo_mira: bool) -> list[str]:
    """Los tres entornos: el del motor, el de la voz (Kokoro, Orpheus y whisper) y el del obrero y la marca."""
    faltan = [nombre for nombre, receta in ENTORNOS.items() if not entorno_hecho(RAIZ / nombre, receta)]
    if not solo_mira:
        for nombre in faltan:
            _di(f"  {nombre}")
            crea_entorno(RAIZ / nombre, ENTORNOS[nombre])
    return faltan


def paso_comfyui(solo_mira: bool) -> list[str]:
    """ComfyUI 0.33.0 con su nodo GGUF y su entorno, o el ComfyUI que ya declara el `.env`, que no se toca."""
    repos = lista()["repositorios"]
    declarada = variable("COMFY_ROOT")
    if declarada:
        raiz = Path(declarada)
        if not (raiz / "main.py").is_file():
            raise ErrorDeInstalacion(f"COMFY_ROOT={raiz} no es un ComfyUI (no tiene main.py): corrige el .env")
        gguf = raiz / repos["comfyui-gguf"]["destino"]
        if not gguf.is_dir():
            raise ErrorDeInstalacion(
                f"tu ComfyUI ({raiz}) no tiene el nodo ComfyUI-GGUF, y los workflows lo usan. Instálalo tú, en el "
                f"commit {repos['comfyui-gguf']['commit'][:7]} de {repos['comfyui-gguf']['url']}: este instalador "
                "no toca un ComfyUI que no es suyo"
            )
        return []
    raiz = HERRAMIENTAS / "ComfyUI"
    gguf = raiz / repos["comfyui-gguf"]["destino"]
    receta = [["-r", str(REQUISITOS_COMFYUI), "--extra-index-url", INDICE_CU130]]
    faltan = []
    if commit_de(raiz) != repos["comfyui"]["commit"]:
        faltan.append(f"ComfyUI {repos['comfyui']['version']} (commit {repos['comfyui']['commit'][:7]})")
    if commit_de(gguf) != repos["comfyui-gguf"]["commit"]:
        faltan.append(f"el nodo ComfyUI-GGUF (commit {repos['comfyui-gguf']['commit'][:7]})")
    if not entorno_hecho(raiz / ".venv", receta):
        faltan.append("el entorno de ComfyUI (Python 3.12 y torch de CUDA 13.0)")
    faltan.append("COMFY_ROOT en el .env")
    if solo_mira:
        return faltan
    if commit_de(raiz) != repos["comfyui"]["commit"]:
        clona(repos["comfyui"], raiz)
    if commit_de(gguf) != repos["comfyui-gguf"]["commit"]:
        clona(repos["comfyui-gguf"], gguf)
    if not entorno_hecho(raiz / ".venv", receta):
        crea_entorno(raiz / ".venv", receta)
    escribe_env("COMFY_ROOT", str(raiz))
    return faltan


def paso_pesos(solo_mira: bool) -> list[str]:
    """Los pesos de los workflows de imagen y música, y el de Real-ESRGAN, en la carpeta de modelos de ComfyUI."""
    return asegura(ficheros_del_paso("pesos"), solo_mira)


def _llama_cpp(solo_mira: bool) -> list[str]:
    """llama.cpp para CUDA: los dos zips de su release, descomprimidos en `herramientas/llama.cpp`."""
    declarado = variable("LLAMA_SERVER")
    if declarado:
        if not Path(declarado).is_file():
            raise ErrorDeInstalacion(f"LLAMA_SERVER={declarado} no existe: corrige el .env o bórralo para instalarlo")
        return []
    carpeta = HERRAMIENTAS / "llama.cpp"
    servidor = carpeta / "llama-server.exe"
    faltan = [] if servidor.is_file() else ["llama.cpp para CUDA (llama-server)"]
    faltan.append("LLAMA_SERVER en el .env")
    if solo_mira:
        return faltan
    if not servidor.is_file():
        zips = [f for f in ficheros_del_paso("voz") if f["destino"].endswith(".zip")]
        asegura(zips, solo_mira=False)
        # Se descomprime a un lado y se pone en su sitio al final: un corte a mitad no deja un llama.cpp a medias.
        a_medias = carpeta.with_name("llama.cpp.part")
        shutil.rmtree(a_medias, ignore_errors=True)
        for fichero in zips:
            with zipfile.ZipFile(destino_de(fichero)) as z:
                z.extractall(a_medias)
        if not (a_medias / "llama-server.exe").is_file():
            raise ErrorDeInstalacion(f"el zip de llama.cpp no trae llama-server.exe en su raíz ({a_medias})")
        a_medias.replace(carpeta)
        for fichero in zips:
            destino_de(fichero).unlink()
    escribe_env("LLAMA_SERVER", str(servidor))
    return faltan


def paso_voz(solo_mira: bool) -> list[str]:
    """llama.cpp, el GGUF de Orpheus y, en la caché de Hugging Face, Kokoro, el tokenizador, SNAC y whisper."""
    faltan = _llama_cpp(solo_mira)
    gguf = [f for f in ficheros_del_paso("voz") if f.get("variable") == "LLAMA_MODELO_GGUF"]
    resto = [f for f in ficheros_del_paso("voz") if f["destino"].split("/", 1)[0] == "huggingface"]
    sin_variable = not variable("LLAMA_MODELO_GGUF")
    faltan += asegura(gguf, solo_mira)
    if sin_variable:
        faltan.append("LLAMA_MODELO_GGUF en el .env")
        if not solo_mira:
            escribe_env("LLAMA_MODELO_GGUF", str(destino_de(gguf[0])))
    return faltan + asegura(resto, solo_mira)


def _version_instalada(paquete: str) -> str | None:
    ruta = RAIZ / "motor" / "node_modules" / paquete / "package.json"
    return json.loads(ruta.read_text(encoding="utf-8")).get("version") if ruta.is_file() else None


def _efectos_que_faltan() -> list[str]:
    carpeta = RAIZ / "datos" / "escena" / "sfx"
    fichas = json.loads((carpeta / "CREDITOS.json").read_text(encoding="utf-8"))["ficheros"]
    return [n for n, f in fichas.items() if not (carpeta / n).is_file() or sha256_de(carpeta / n) != f["sha256"]]


def manifiesto_valido(ruta: Path) -> bool:
    """El manifiesto del Chrome con WebGPU existe, su ejecutable y las dos DLL están, y cada sha256 cuadra."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        carpeta = Path(datos["exe"]).parent
        hashes = datos["sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return {"chrome-headless-shell.exe", "dxil.dll", "dxcompiler.dll"} <= set(hashes) and all(
        (carpeta / f).is_file() and sha256_de(carpeta / f) == h for f, h in hashes.items()
    )


def paso_escena(solo_mira: bool) -> list[str]:
    """HyperFrames y GSAP (`npm ci`), los efectos de sonido, el Chrome con WebGPU y SAM 2.1."""
    motor = RAIZ / "motor"
    pedidas = json.loads((motor / "package.json").read_text(encoding="utf-8"))["dependencies"]
    faltan = []
    if any(_version_instalada(p) != v for p, v in pedidas.items()):
        faltan.append("HyperFrames y GSAP (npm ci en motor/)")
        if not solo_mira:
            node = _node()
            npm = shutil.which("npm") or (node.parent / "npm.cmd" if node else None)
            if not npm:
                raise ErrorDeInstalacion("no encuentro npm: es el paso requisitos")
            corre([npm, "ci"], motor, "npm ci")
    if _efectos_que_faltan():
        faltan.append("los efectos de sonido (scripts/instala_efectos.py)")
        if not solo_mira:
            corre([python_de(RAIZ / ".venv"), "scripts/instala_efectos.py"], RAIZ, "instala_efectos.py")
    declarado = variable("CHROME_WEBGPU_MANIFIESTO")
    if declarado and not manifiesto_valido(Path(declarado)):
        raise ErrorDeInstalacion(
            f"CHROME_WEBGPU_MANIFIESTO={declarado} no es un Chrome con WebGPU completo (falta un fichero o no cuadra "
            "su sha256). Bórralo del .env para que este paso lo instale en herramientas/, o rehazlo con "
            "scripts/instala_chrome_webgpu.ps1"
        )
    if not declarado:
        faltan.append("el Chrome con WebGPU y CHROME_WEBGPU_MANIFIESTO en el .env")
        if not solo_mira:
            destino = HERRAMIENTAS / "chrome-webgpu"
            manifiesto = destino / "manifiesto.json"
            if not manifiesto_valido(manifiesto):
                node = _node()
                cli = motor / "node_modules" / "hyperframes" / "dist" / "cli.js"
                corre([node, cli, "browser", "ensure"], motor, "hyperframes browser ensure")
                dxc, zip_de_chrome = _librerias_dxc()
                script = RAIZ / "scripts" / "instala_chrome_webgpu.ps1"
                # Sin PSModulePath: lanzado desde una PowerShell 7, Windows PowerShell hereda sus módulos y no encuentra
                # Get-FileHash (medido en la prueba de humo de OC1.7). Sin la variable, rehace la suya.
                entorno = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
                corre(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-Destino", destino,
                     "-ChromeSistema", dxc],
                    RAIZ,
                    "instala_chrome_webgpu.ps1",
                    entorno,
                )  # fmt: skip
                if not manifiesto_valido(manifiesto):
                    raise ErrorDeInstalacion(f"el script del Chrome acabó y {manifiesto} no cuadra")
                shutil.rmtree(dxc)
                zip_de_chrome.unlink()
            escribe_env("CHROME_WEBGPU_MANIFIESTO", str(manifiesto))
    sam = [f for f in ficheros_del_paso("escena") if f["destino"].split("/", 1)[0] == "huggingface"]
    return faltan + asegura(sam, solo_mira)


def paso_marca(solo_mira: bool) -> list[str]:
    """Los tres pesos de la marca de IA (Video Seal y AudioSeal), donde los busca `lib/marca_ia.py`."""
    return asegura(ficheros_del_paso("marca"), solo_mira)


def paso_voz_del_canal(solo_mira: bool) -> list[str]:
    """El clip de referencia que clona Orpheus para el canal activo, si su receta clona (`scripts/referencia_voz.py`).

    Usa la GPU unos segundos (Kokoro), así que va al final, cuando ningún otro paso la usa.
    """
    python = python_de(RAIZ / ".venv")
    if not python.is_file():
        return ["el clip de voz del canal activo (antes, el paso entornos)"]
    r = subprocess.run(
        [python, "scripts/referencia_voz.py", "--ruta"], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8"
    )
    if r.returncode != 0:
        raise ErrorDeInstalacion(f"scripts/referencia_voz.py --ruta: {(r.stderr or r.stdout).strip()[-600:]}")
    datos = json.loads(r.stdout.strip().splitlines()[-1])
    if not datos["variable"]:
        return []
    actual = variable(datos["variable"])
    if actual and Path(actual).is_file():
        return []
    faltan = [f"el clip de voz del canal {datos['canal']} y {datos['variable']} en el .env"]
    if solo_mira:
        return faltan
    if not Path(datos["destino"]).is_file():
        corre([python, "scripts/referencia_voz.py"], RAIZ, "referencia_voz.py")
    escribe_env(datos["variable"], datos["destino"])
    return faltan


def paso_comprueba(solo_mira: bool) -> list[str]:
    """La comprobación del motor, `pipeline.py --check`: tiene que acabar en «Listo para producir.»."""
    python = python_de(RAIZ / ".venv")
    if not python.is_file():
        return ["pipeline.py --check (antes, el paso entornos)"]
    r = subprocess.run([python, "pipeline.py", "--check"], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8")
    salida = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 0 and "Listo para producir." in salida:
        return []
    _di(salida)
    if solo_mira:
        return ["pipeline.py --check no da verde (arriba, con ✗)"]
    raise ErrorDeInstalacion("pipeline.py --check no da verde: arriba, con ✗, lo que falta")


PASOS = {
    "requisitos": (paso_requisitos, "git, Node, ffmpeg y el controlador de NVIDIA, y que la carpeta sea corta"),
    "env": (paso_env, "el .env, desde .env.example"),
    "entornos": (paso_entornos, "los entornos .venv, .venv-voz y .venv-escena, con Python 3.12"),
    "comfyui": (paso_comfyui, "ComfyUI 0.33.0 con el nodo GGUF, o el tuyo si COMFY_ROOT ya lo dice"),
    "pesos": (paso_pesos, "los pesos de imagen, música y Real-ESRGAN, unos 70 GB, en ComfyUI"),
    "voz": (paso_voz, "llama.cpp, Orpheus (3,5 GB) y Kokoro, SNAC y whisper en la caché de Hugging Face"),
    "escena": (paso_escena, "HyperFrames y GSAP, los efectos, el Chrome con WebGPU y SAM 2.1"),
    "marca": (paso_marca, "los tres pesos de la marca de IA (unos 320 MB)"),
    "voz-del-canal": (paso_voz_del_canal, "el clip de voz que clona Orpheus para el canal activo"),
    "comprueba": (paso_comprueba, "pipeline.py --check"),
}


# ---------------------------------------------------------------------------------------------------------------
# Las claves: en el terminal, sin eco
# ---------------------------------------------------------------------------------------------------------------
def pide_claves(entrada=getpass.getpass) -> int:
    """Pide las claves de YouTube sin eco y escribe en el `.env` las que se den. Nunca las imprime."""
    if entrada is getpass.getpass and not sys.stdin.isatty():
        _di("--claves se lanza en tu terminal, a mano: así las claves no pasan por ningún chat ni por ningún registro.")
        return 1
    paso_env(solo_mira=False)
    perfil = RAIZ / "canales" / variable("CANAL_ACTIVO") / "perfil.json"
    token = "YOUTUBE_REFRESH_TOKEN"
    if variable("CANAL_ACTIVO") and perfil.is_file():
        token = json.loads(perfil.read_text(encoding="utf-8")).get("publicacion", {}).get("refresh_token_env") or token
    _di(
        "Las claves de YouTube solo hacen falta para que el motor suba por la API (YOUTUBE_SUBIDA_API=1) o para "
        "metricas.py. Cómo se sacan: docs/youtube-upload.md. Se escriben en tu .env y no salen de este PC.\n"
        "Lo que escribas no se ve. Deja en blanco las que no quieras cambiar."
    )
    for clave, que in (
        ("YOUTUBE_CLIENT_ID", "el Client ID de tu cliente OAuth"),
        ("YOUTUBE_CLIENT_SECRET", "su Client secret"),
        (token, "el refresh token del canal activo"),
        ("YOUTUBE_API_KEY", "opcional: la clave de lectura"),
    ):
        valor = entrada(f"  {clave} ({que}): ").strip()
        if valor:
            escribe_env(clave, valor)
            _di(f"  {clave}: escrita en el .env")
    _di("Para que el motor suba por la API, escribe además YOUTUBE_SUBIDA_API=1 en el .env.")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # la consola cp1252 no sabe escribir ✓ ni ✗
    parser = argparse.ArgumentParser(description="Instala Lanternist en este PC, paso a paso y de forma repetible.")
    parser.add_argument("--comprueba", action="store_true", help="dice qué falta, sin instalar ni bajar nada")
    parser.add_argument("--paso", choices=list(PASOS), help="hace un paso solo")
    parser.add_argument("--claves", action="store_true", help="pide las claves de YouTube en el terminal, sin eco")
    args = parser.parse_args(argv)
    if sys.version_info[:2] != VERSION_PYTHON:
        _di(
            f"Lanternist usa Python {VERSION_PYTHON[0]}.{VERSION_PYTHON[1]}, y esto es {sys.version.split()[0]}. "
            "Si no lo tienes: winget install -e --id Python.Python.3.12. Después: py -3.12 instala.py"
        )
        return 1
    if args.claves:
        return pide_claves()
    inicio = time.monotonic()
    pendientes = 0
    for nombre in [args.paso] if args.paso else list(PASOS):
        funcion, que = PASOS[nombre]
        _di(f"\n[{nombre}] {que}")
        t0 = time.monotonic()
        try:
            faltaba = funcion(args.comprueba)
        except ErrorDeInstalacion as error:
            _di(f"  ✗ {error}")
            if args.comprueba:
                pendientes += 1
                continue
            _di("\nLa instalación se para aquí. Arregla lo de arriba y repite la orden: lo que ya está no se rehace.")
            return 1
        if args.comprueba:
            pendientes += bool(faltaba)
            _di("\n".join(f"  falta: {f}" for f in faltaba) if faltaba else "  ✓ ya está")
        else:
            _di(f"  ✓ {'hecho' if faltaba else 'ya estaba'} ({time.monotonic() - t0:.0f} s)")
    if args.comprueba:
        _di(f"\n{'Falta algo: py -3.12 instala.py lo instala.' if pendientes else 'Todo instalado.'}")
        return 1 if pendientes else 0
    _di(f"\nListo, en {(time.monotonic() - inicio) / 60:.1f} min.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
