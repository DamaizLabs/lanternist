"""El instalador (`instala.py`, OC1.7): la lista fija, la descarga reanudable, el sha256 y los pasos ya hechos.

Sin red: la descarga se prueba con un servidor falso que sabe cortar, retomar con `Range` o ignorarlo. La descarga de
verdad (un peso de AudioSeal cortado a mitad y retomado) y la instalación entera en una carpeta limpia están en
`progress/impl_OC1.7.md`. Cada prueba lleva su control: lo mismo con la condición contraria da lo contrario.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path

import pytest

import instala
from lib import config, marca_ia

RAIZ = Path(__file__).resolve().parent.parent
LISTA = json.loads((RAIZ / "datos" / "descargas.json").read_text(encoding="utf-8"))
FICHEROS = LISTA["ficheros"]


# ------------------------------------------------------------------------------------------ la lista fija
def test_cada_fichero_de_la_lista_tiene_url_fija_sha256_tamano_licencia_y_destino():
    for f in FICHEROS:
        assert f["url"].startswith("https://"), f["id"]
        assert re.fullmatch(r"[0-9a-f]{64}", f["sha256"]), f["id"]
        assert isinstance(f["bytes"], int) and f["bytes"] > 0, f["id"]
        assert f["licencia"] and f["fuente"].startswith("https://"), f["id"]
        assert f["paso"] in instala.PASOS, f["id"]
        assert f["destino"].split("/", 1)[0] in {"comfyui", "huggingface", "torch", "herramientas"}, f["id"]
        # A una revisión fija: en Hugging Face, un commit de 40 caracteres; nunca `main`.
        if "huggingface.co" in f["url"]:
            assert re.search(r"/resolve/[0-9a-f]{40}/", f["url"]), f["id"]
        assert "/main/" not in f["url"] and "/master/" not in f["url"], f["id"]
    assert len({f["id"] for f in FICHEROS}) == len(FICHEROS), "un id repetido"
    assert len({f["destino"] for f in FICHEROS}) == len(FICHEROS), "dos ficheros al mismo sitio"


def test_en_la_cache_de_hugging_face_la_revision_de_la_url_es_la_del_destino():
    for f in FICHEROS:
        if f["destino"].startswith("huggingface/"):
            revision = f["destino"].split("/")[3]
            assert f"/resolve/{revision}/" in f["url"], f["id"]


def test_estan_todos_los_pesos_de_los_workflows_y_el_de_esrgan():
    destinos = {f["destino"] for f in FICHEROS}
    for workflow in sorted((RAIZ / "workflows").glob("*.json")):
        for peso in json.loads(workflow.read_text(encoding="utf-8"))["modelo"]["pesos"]:
            assert f"comfyui/models/{peso}" in destinos, f"{workflow.name}: {peso} no está en la lista fija"
    # El de Real-ESRGAN, con el nombre que `lib/config.py` le pone por defecto.
    esrgan = [f for f in FICHEROS if f.get("variable") == "ESCENA_ESRGAN_PESO"]
    assert len(esrgan) == 1 and Path(esrgan[0]["destino"]).name == Path(config.ESCENA_ESRGAN_PESO).name


def test_los_pesos_de_la_marca_salen_de_la_lista_y_su_sha256_vive_en_un_solo_sitio():
    marca = {f["id"]: f for f in FICHEROS if f["paso"] == "marca"}
    assert set(marca) == set(marca_ia.MODELOS) == {"videoseal", "audioseal_generador", "audioseal_detector"}
    for clave, modelo in marca_ia.MODELOS.items():
        assert modelo["sha256"] == marca[clave]["sha256"] and modelo["url"] == marca[clave]["url"]
    codigo = (RAIZ / "lib" / "marca_ia.py").read_text(encoding="utf-8")
    assert not re.search(r"\b[0-9a-f]{64}\b", codigo), "un sha256 escrito a mano en lib/marca_ia.py"


# ------------------------------------------------------------------------------------------ la descarga
CONTENIDO = bytes(range(256)) * 400  # 100 KB


def _fichero(contenido: bytes = CONTENIDO, sha256: str | None = None) -> dict:
    return {
        "id": "prueba",
        "nombre": "prueba",
        "url": "https://ejemplo.invalid/peso.bin",
        "sha256": sha256 or hashlib.sha256(contenido).hexdigest(),
        "bytes": len(contenido),
    }


class Servidor:
    """Un `urlopen` falso: sirve `contenido`, entiende `Range` (o no) y puede cortarse tras `corta` bytes."""

    def __init__(self, contenido: bytes = CONTENIDO, *, admite_range: bool = True, corta: int | None = None):
        self.contenido, self.admite_range, self.corta = contenido, admite_range, corta
        self.peticiones: list[dict] = []

    def __call__(self, peticion, timeout):
        cabeceras = {k.lower(): v for k, v in peticion.header_items()}
        self.peticiones.append(cabeceras)
        desde = 0
        if self.admite_range and "range" in cabeceras:
            desde = int(re.match(r"bytes=(\d+)-", cabeceras["range"]).group(1))
        cuerpo = self.contenido[desde:]
        servidor = self

        class Respuesta(io.BytesIO):
            status = 206 if desde else 200

            def read(self, n=-1):
                if servidor.corta is not None and self.tell() >= servidor.corta:
                    raise ConnectionResetError("cortada a mitad")
                if servidor.corta is not None:
                    n = min(n if n > 0 else len(cuerpo), servidor.corta - self.tell())
                return super().read(n)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return Respuesta(cuerpo)


def test_baja_entero_y_no_deja_el_parcial(tmp_path):
    destino = tmp_path / "peso.bin"
    instala.descarga(_fichero(), destino, abre=Servidor())
    assert destino.read_bytes() == CONTENIDO and not destino.with_name("peso.bin.part").exists()


def test_una_descarga_cortada_deja_el_parcial_y_la_siguiente_sigue_desde_ahi(tmp_path):
    destino = tmp_path / "peso.bin"
    with pytest.raises(instala.ErrorDeInstalacion, match="se cortó"):
        instala.descarga(_fichero(), destino, abre=Servidor(corta=30_000))
    parcial = destino.with_name("peso.bin.part")
    assert parcial.stat().st_size == 30_000 and not destino.exists()
    servidor = Servidor()
    instala.descarga(_fichero(), destino, abre=servidor)
    assert servidor.peticiones[0]["range"] == "bytes=30000-", "retoma, no empieza de cero"
    assert destino.read_bytes() == CONTENIDO and not parcial.exists()


def test_si_el_servidor_no_admite_range_empieza_de_cero_y_el_fichero_sale_bien(tmp_path):
    destino = tmp_path / "peso.bin"
    destino.with_name("peso.bin.part").write_bytes(CONTENIDO[:1000])
    instala.descarga(_fichero(), destino, abre=Servidor(admite_range=False))
    assert destino.read_bytes() == CONTENIDO


def test_lo_que_llega_con_otro_sha256_se_borra_y_no_se_usa(tmp_path):
    destino = tmp_path / "peso.bin"
    otro = _fichero(sha256=hashlib.sha256(b"otra cosa").hexdigest())
    with pytest.raises(instala.ErrorDeInstalacion, match="otro sha256"):
        instala.descarga(otro, destino, abre=Servidor())
    assert list(tmp_path.iterdir()) == [], "ni el fichero ni su parcial"
    # Control: con su sha256 de verdad, el mismo contenido se queda.
    instala.descarga(_fichero(), destino, abre=Servidor())
    assert destino.read_bytes() == CONTENIDO


# ------------------------------------------------------------------------------------------ los pasos ya hechos
@pytest.fixture
def aislado(tmp_path, monkeypatch):
    """Un `.env`, una carpeta de herramientas y las cachés en una carpeta temporal: nada del PC de quien la corre."""
    monkeypatch.setattr(instala, "ENV", tmp_path / ".env")
    monkeypatch.setattr(instala, "HERRAMIENTAS", tmp_path / "herramientas")
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf"))
    monkeypatch.setenv("TORCH_HOME", str(tmp_path / "torch"))
    for nombre in ("COMFY_ROOT", "LLAMA_SERVER", "LLAMA_MODELO_GGUF", "CHROME_WEBGPU_MANIFIESTO", "ESCENA_ESRGAN_PESO"):
        monkeypatch.delenv(nombre, raising=False)
    return tmp_path


def test_lo_que_ya_esta_con_su_sha256_no_se_baja(aislado):
    fichero = {**_fichero(), "destino": "huggingface/models--org--modelo/snapshots/" + "a" * 40 + "/peso.bin"}
    destino = instala.destino_de(fichero)
    destino.parent.mkdir(parents=True)
    destino.write_bytes(CONTENIDO)

    def no_baja(*a, **k):
        pytest.fail("ya estaba: no se baja")

    # La caché de Hugging Face tiene que apuntar su revisión (refs/main), que es la que carga la biblioteca sin red.
    # `--comprueba` lo dice y no escribe nada; la instalación la apunta; y la segunda vez ya no falta nada.
    refs = aislado / "hf" / "models--org--modelo" / "refs" / "main"
    revision = ["la revisión de models--org--modelo en la caché de Hugging Face (refs/main)"]
    assert instala.asegura([fichero], solo_mira=True, abre=no_baja) == revision and not refs.exists()
    assert instala.asegura([fichero], solo_mira=False, abre=no_baja) == revision
    assert refs.read_text() == "a" * 40
    assert instala.asegura([fichero], solo_mira=False, abre=no_baja) == []
    # Control: si no está, sí se baja.
    destino.unlink()
    servidor = Servidor()
    assert instala.asegura([fichero], solo_mira=False, abre=servidor) == ["prueba (0.1 MB)"]
    assert destino.read_bytes() == CONTENIDO and len(servidor.peticiones) == 1


def test_un_fichero_que_ya_esta_con_otro_sha256_no_se_toca(aislado):
    fichero = {**_fichero(), "destino": "herramientas/modelos/peso.bin"}
    destino = instala.destino_de(fichero)
    destino.parent.mkdir(parents=True)
    destino.write_bytes(b"el de otro proyecto")
    with pytest.raises(instala.ErrorDeInstalacion, match="no se tocan"):
        instala.asegura([fichero], solo_mira=False)
    assert destino.read_bytes() == b"el de otro proyecto"


def test_la_variable_del_env_manda_sobre_el_destino_por_defecto(aislado):
    fichero = {**_fichero(), "destino": "herramientas/modelos/orpheus.gguf", "variable": "LLAMA_MODELO_GGUF"}
    assert instala.destino_de(fichero) == aislado / "herramientas" / "modelos" / "orpheus.gguf"
    instala.escribe_env("LLAMA_MODELO_GGUF", str(aislado / "otro" / "mio.gguf"))
    assert instala.destino_de(fichero) == aislado / "otro" / "mio.gguf"


def test_un_entorno_con_su_marca_no_se_rehace_y_uno_con_requisitos_cambiados_si(aislado, monkeypatch):
    requisitos = aislado / "req.txt"
    requisitos.write_text("paquete==1.0\n")
    entorno = aislado / ".venv-prueba"
    instala.python_de(entorno).parent.mkdir(parents=True)
    instala.python_de(entorno).write_text("")
    receta = [["-r", str(requisitos)]]
    ordenes = []
    monkeypatch.setattr(instala, "corre", lambda orden, cwd=None, que="": ordenes.append(orden))
    assert not instala.entorno_hecho(entorno, receta)
    instala.crea_entorno(entorno, receta)
    assert instala.entorno_hecho(entorno, receta) and len(ordenes) == 1, "una orden de pip y su marca"
    # Control: si cambian los requisitos, la marca ya no vale y pip se repite.
    requisitos.write_text("paquete==2.0\n")
    assert not instala.entorno_hecho(entorno, receta)


def test_un_entorno_que_ya_existe_con_otro_python_no_se_toca(aislado, monkeypatch):
    entorno = aislado / ".venv-otro"
    instala.python_de(entorno).parent.mkdir(parents=True)
    instala.python_de(entorno).write_text("")
    ordenes = []
    monkeypatch.setattr(instala, "corre", lambda orden, cwd=None, que="": ordenes.append(orden))
    (entorno / "pyvenv.cfg").write_text("home = C:\\Python314\nversion = 3.14.4\n")
    with pytest.raises(instala.ErrorDeInstalacion, match="es de Python 3.14.4"):
        instala.crea_entorno(entorno, [["paquete"]])
    assert ordenes == [] and not (entorno / instala.MARCA_DE_ENTORNO).exists(), "ni pip ni marca"
    # Control: con el Python del instalador, sigue.
    propio = f"{instala.sys.version_info.major}.{instala.sys.version_info.minor}.0"
    (entorno / "pyvenv.cfg").write_text(f"version_info = {propio}\n")
    instala.crea_entorno(entorno, [["paquete"]])
    assert len(ordenes) == 1


# ------------------------------------------------------------------------------------------ el .env
def test_el_env_se_lee_como_dotenv_y_se_escribe_sin_tocar_el_resto(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# un comentario\nCANAL_ACTIVO=mi-canal\nCOMFY_ROOT=                # OBLIGATORIA\n"
        'CON_COMILLAS="C:\\una ruta # con almohadilla"\n# LLAMA_SERVER=\n',
        encoding="utf-8",
    )
    assert instala.lee_env(env) == {
        "CANAL_ACTIVO": "mi-canal",
        "COMFY_ROOT": "",
        "CON_COMILLAS": "C:\\una ruta # con almohadilla",
    }
    instala.escribe_env("COMFY_ROOT", "D:\\herramientas\\ComfyUI", env)
    instala.escribe_env("LLAMA_SERVER", "D:\\llama\\llama-server.exe", env)
    texto = env.read_text(encoding="utf-8")
    assert "COMFY_ROOT=D:\\herramientas\\ComfyUI\n" in texto and texto.count("COMFY_ROOT") == 1
    assert texto.endswith("LLAMA_SERVER=D:\\llama\\llama-server.exe\n"), "la que no estaba, al final"
    assert "# un comentario\nCANAL_ACTIVO=mi-canal\n" in texto and "# LLAMA_SERVER=\n" in texto


def test_las_claves_no_se_piden_fuera_de_un_terminal(monkeypatch, capsys):
    monkeypatch.setattr(instala.sys.stdin, "isatty", lambda: False, raising=False)
    assert instala.pide_claves() == 1
    assert "en tu terminal" in capsys.readouterr().out


def test_las_claves_se_escriben_en_el_env_y_no_se_imprimen(aislado, capsys):
    (aislado / ".env").write_text("CANAL_ACTIVO=\n", encoding="utf-8")
    respuestas = iter(["id-de-prueba", "secreto-de-prueba", "", ""])
    assert instala.pide_claves(entrada=lambda _texto: next(respuestas)) == 0
    env = instala.lee_env(aislado / ".env")
    assert env["YOUTUBE_CLIENT_ID"] == "id-de-prueba" and env["YOUTUBE_CLIENT_SECRET"] == "secreto-de-prueba"
    assert "YOUTUBE_REFRESH_TOKEN" not in env, "lo que se deja en blanco no se escribe"
    salida = capsys.readouterr().out
    assert "secreto-de-prueba" not in salida and "id-de-prueba" not in salida


# ------------------------------------------------------------------------------------------ pipeline.py --check
def _motor_de_escena_de_mentira(carpeta: Path, monkeypatch, *, cuda: str = "13.0") -> dict:
    """Un Chrome con su manifiesto, un `.venv-escena` que contesta lo que se le diga y un peso de ESRGAN."""
    import subprocess

    chrome = carpeta / "chrome"
    chrome.mkdir(parents=True)
    hashes = {}
    for nombre in ("chrome-headless-shell.exe", "dxil.dll", "dxcompiler.dll"):
        (chrome / nombre).write_bytes(nombre.encode())
        hashes[nombre] = hashlib.sha256(nombre.encode()).hexdigest()
    manifiesto = carpeta / "manifiesto.json"
    exe = str(chrome / "chrome-headless-shell.exe")
    datos = {"chrome_headless": "win64-prueba", "dxc_de": "Chrome prueba", "exe": exe, "sha256": hashes}
    manifiesto.write_text(json.dumps(datos), encoding="utf-8")
    python = carpeta / "python.exe"
    python.write_text("")
    esrgan = carpeta / "esrgan.pth"
    esrgan.write_bytes(b"peso")
    monkeypatch.setattr(config, "CHROME_WEBGPU_MANIFIESTO", manifiesto)
    monkeypatch.setattr(config, "ESCENA_PYTHON", str(python))
    monkeypatch.setattr(config, "ESCENA_ESRGAN_PESO", esrgan)
    contesta = subprocess.CompletedProcess([], 0, stdout=f"2.13.0+cu130 {cuda}", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: contesta)
    return {"chrome": chrome, "python": python, "esrgan": esrgan}


def test_check_mira_el_motor_de_escena_sin_init_mjs(tmp_path, monkeypatch, capsys):
    """Criterio 8 de OC1.7: el Chrome con WebGPU, `.venv-escena` y el peso de ESRGAN, en el propio `--check`."""
    import pipeline

    piezas = _motor_de_escena_de_mentira(tmp_path / "bien", monkeypatch)
    assert pipeline._comprueba_el_motor_de_escena() is True
    salida = capsys.readouterr().out
    assert "✓ Chrome con WebGPU" in salida and "✓ .venv-escena: torch 2.13.0+cu130 con CUDA 13.0" in salida
    assert "init.mjs" not in salida
    # Controles, uno por pieza: cada una que falla pone el bloque en rojo y dice qué hacer.
    (piezas["chrome"] / "dxil.dll").write_bytes(b"otra")
    assert pipeline._comprueba_el_motor_de_escena() is False
    assert "✗ Chrome con WebGPU: dxil.dll no está o no cuadra" in capsys.readouterr().out
    _motor_de_escena_de_mentira(tmp_path / "sin-cuda", monkeypatch, cuda="None")
    assert pipeline._comprueba_el_motor_de_escena() is False
    assert "SIN CUDA" in capsys.readouterr().out
    piezas = _motor_de_escena_de_mentira(tmp_path / "sin-esrgan", monkeypatch)
    piezas["esrgan"].unlink()
    assert pipeline._comprueba_el_motor_de_escena() is False
    assert "✗ peso de Real-ESRGAN: no está" in capsys.readouterr().out
    piezas["python"].unlink()
    assert pipeline._comprueba_el_motor_de_escena() is False
    assert "✗ .venv-escena: no está" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------ la ruta de Lanternist
def test_una_carpeta_demasiado_larga_se_dice_antes_de_instalar():
    """Medido en OC1.7: ComfyUI no arrancó en una carpeta de 194 caracteres (una DLL pasaba de 259)."""
    corta = Path("C:/lanternist")
    assert instala.problema_de_ruta(corta, largas=False) is None
    assert instala.problema_de_ruta(corta, largas=True) is None
    honda = Path("C:/" + "x" * 190)
    assert "no carga una DLL" in instala.problema_de_ruta(honda, largas=True)
    # Sin rutas largas, el límite es el de pip con torch: 40 caracteres; con ellas, esa misma carpeta vale.
    media = Path("C:/" + "y" * 60)
    assert "rutas largas de Windows están apagadas" in instala.problema_de_ruta(media, largas=False)
    assert instala.problema_de_ruta(media, largas=True) is None
