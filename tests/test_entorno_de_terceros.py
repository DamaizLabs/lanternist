"""Las credenciales del `.env` no entran en un proceso de terceros.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_entorno_de_terceros.py

**De dónde sale.** La auditoría del 08-09 encontró que `lib/comfy_client.py` arrancaba ComfyUI con
`env={**os.environ, ...}`, o sea con las seis credenciales que `load_dotenv` deja en el entorno, y
ComfyUI carga nodos de terceros. El reportante lo puso ALTO y el verificador BAJO —no hay fuga en
marcha, solo un vector— y quedó como discrepancia para el dueño del estudio. La del 10-09 lo volvió a medir: seguía
igual, y llama-server hacía lo mismo. El go llegó el 10-09.

**Lo que se garantiza, y es más estrecho que «lista blanca»**: de lo que declara el `.env`, nada llega
al hijo. Una lista blanca cerrada sería más estricta sobre el papel pero rompería el arranque en
Windows el día que falte una variable del sistema que nadie anticipó (ver el comentario de
`lib/config.entorno_para_terceros`).

Hay dos pruebas de otra clase al final: **estructurales**, sobre el código. Sin ellas, mañana alguien
escribe otro `Popen` con el entorno completo y estas comprobaciones seguirían en verde.
"""

import ast
import os
from pathlib import Path

import pytest

from lib import config

RAIZ = Path(__file__).resolve().parent.parent

CREDENCIALES = {
    "YOUTUBE_API_KEY": "AIzaFALSA",
    "YOUTUBE_CLIENT_SECRET": "GOCSPX-FALSA",
    "YOUTUBE_REFRESH_TOKEN": "1//FALSA",
    "APIFY_TOKEN": "apify_api_FALSA",
    "KAGGLE_API_TOKEN": "KGATFALSA",
    "RUTA_VOZ_REFERENCIA": r"D:\privado\voz.wav",
}


@pytest.fixture
def env_de_mentira(tmp_path, monkeypatch):
    """Un `.env` con credenciales falsas, cargado en el entorno como lo hace `load_dotenv`."""
    fichero = tmp_path / ".env"
    fichero.write_text("\n".join(f"{k}={v}" for k, v in CREDENCIALES.items()), encoding="utf-8")
    monkeypatch.setattr(config, "RUTA_ENV", fichero)
    for clave, valor in CREDENCIALES.items():
        monkeypatch.setenv(clave, valor)
    return fichero


def test_ninguna_clave_del_env_llega_al_proceso_de_terceros(env_de_mentira):
    entorno = config.entorno_para_terceros()

    colados = sorted(k for k in CREDENCIALES if k in entorno)
    assert colados == [], f"estas claves del .env llegarían a un nodo de terceros: {colados}"


def test_ningun_valor_de_credencial_viaja_con_otro_nombre(env_de_mentira):
    """No basta con quitar la clave: el valor no puede estar en el entorno bajo ningún nombre."""
    entorno = config.entorno_para_terceros()

    assert not [k for k, v in entorno.items() if v in set(CREDENCIALES.values())]


def test_el_control_negativo_demuestra_que_la_prueba_sabe_fallar(env_de_mentira):
    """Lo que hacía el código hasta el 10-09. Si esto NO detecta las claves, la prueba no vale."""
    como_estaba = {**os.environ, "PYTHONUNBUFFERED": "1"}

    colados = sorted(k for k in CREDENCIALES if k in como_estaba)
    assert colados == sorted(CREDENCIALES), "el entorno heredado sí entrega las credenciales: por eso se filtra"


def test_una_credencial_que_no_esta_en_el_env_tambien_se_filtra_por_su_nombre(monkeypatch):
    monkeypatch.setenv("UN_SERVICIO_TOKEN", "secreto")
    monkeypatch.setenv("OTRA_API_KEY", "secreto")
    monkeypatch.setenv("MI_PASSWORD", "secreto")

    entorno = config.entorno_para_terceros()

    assert "UN_SERVICIO_TOKEN" not in entorno
    assert "OTRA_API_KEY" not in entorno
    assert "MI_PASSWORD" not in entorno


def test_lo_que_el_hijo_necesita_para_arrancar_sigue_estando(env_de_mentira):
    """El filtro no puede dejar al hijo sin lo del sistema: en Windows no arrancaría."""
    entorno = config.entorno_para_terceros({"PYTHONUNBUFFERED": "1"})

    assert entorno.get("PATH"), "sin PATH no arranca ni ComfyUI ni llama-server"
    assert entorno["PYTHONUNBUFFERED"] == "1", "lo repuesto explícitamente tiene que llegar"
    # En Windows `os.environ` normaliza los nombres a MAYÚSCULAS, y el dict que sale de aquí los
    # conserva tal cual: la comparación va en mayúsculas o falla por la capitalización (lo cazó esta
    # misma prueba con `SystemRoot`).
    presentes = {k.upper() for k in entorno}
    for clave in ("APPDATA", "LOCALAPPDATA", "TEMP", "SYSTEMROOT", "WINDIR"):
        if any(k.upper() == clave for k in os.environ):
            assert clave in presentes, f"{clave} es del sistema y el hijo la necesita"


def test_sin_fichero_env_no_falla_y_sigue_filtrando_por_nombre(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUTA_ENV", tmp_path / "no-existe.env")
    monkeypatch.setenv("ALGO_SECRET", "x")

    entorno = config.entorno_para_terceros()

    assert config.claves_del_env() == set()
    assert "ALGO_SECRET" not in entorno


def test_claves_del_env_no_devuelve_valores(env_de_mentira):
    """El manifiesto y los informes citan los NOMBRES; los valores no salen de aquí."""
    assert config.claves_del_env() == set(CREDENCIALES)


# --- estructurales: que nadie vuelva a escribir el Popen de antes -----------------------------


def _llamadas_a_subprocess(fuente: str) -> list[ast.Call]:
    arbol = ast.parse(fuente)
    return [
        nodo
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Call)
        and isinstance(nodo.func, ast.Attribute)
        and nodo.func.attr in ("Popen", "run")
        and isinstance(nodo.func.value, ast.Name)
        and nodo.func.value.id == "subprocess"
    ]


@pytest.mark.parametrize("modulo", ["lib/comfy_client.py", "lib/voice_client.py"])
def test_ningun_subproceso_del_modulo_hereda_el_entorno_entero(modulo):
    for llamada in _llamadas_a_subprocess((RAIZ / modulo).read_text(encoding="utf-8")):
        for kw in llamada.keywords:
            if kw.arg != "env":
                continue
            fuente_env = ast.unparse(kw.value)
            assert "os.environ" not in fuente_env, (
                f"{modulo}: un subproceso recibe el entorno completo ({fuente_env[:60]}). "
                "Usa config.entorno_para_terceros() si es un proceso de terceros."
            )


def test_los_dos_procesos_de_terceros_declaran_el_entorno_filtrado():
    """Lo contrario del anterior: no vale con no pasar `env`, hay que pasar el filtrado."""
    for modulo in ("lib/comfy_client.py", "lib/voice_client.py"):
        fuente = (RAIZ / modulo).read_text(encoding="utf-8")
        assert "entorno_para_terceros(" in fuente, f"{modulo} arranca un proceso de terceros sin filtrar el entorno"
