"""La guarda de licencias (`scripts/guarda_licencias.py`, OC1.2) y los avisos de terceros.

La prueba buena es el repositorio de verdad: lo versionado tiene que pasar. Cada forma de colar algo sin permiso tiene
su control negativo, sobre una carpeta temporal que empieza siendo buena y se estropea en una sola cosa.

**Sin `.git`** (una exportación antes de su primer commit, o el repositorio bajado en un zip) no hay «lo versionado»: la
carpeta lleva además lo que instala `instala.py` y git ignora, como los efectos de Pixabay, que la guarda pararía con
razón. Ahí la prueba buena se salta, y a la exportación le pasa la guarda `exportacion/exporta.py` antes de instalar
nada.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from lib import config
from scripts import guarda_licencias as gl

AVISO_MINIMO = (
    "yashaiguy-dev e92c845 · Built with Llama · Llama 3.2 Community License · GSAP · Pixabay · qwen-image-Q6_K.gguf"
)
OFL = "SIL Open Font License 1.1 (OFL)"
SIN_GIT = "sin .git: no hay «lo versionado» (una exportación antes de su primer commit, o un zip)"


def _ficha(datos: bytes, licencia: str, **mas) -> dict:
    return {"fuente": "prueba", "licencia": licencia, "url": "https://ejemplo.invalid", **mas,
            "sha256": hashlib.sha256(datos).hexdigest()}  # fmt: skip


def _arbol_bueno(raiz: Path) -> list[str]:
    """Una carpeta que pasa: una fuente OFL con su texto, un workflow con su peso declarado y el aviso."""
    fuentes = raiz / "datos" / "escena" / "fuentes"
    fuentes.mkdir(parents=True)
    (fuentes / "Libre.ttf").write_bytes(b"fuente libre")
    (fuentes / "OFL-Libre.txt").write_text("SIL OPEN FONT LICENSE Version 1.1", encoding="utf-8")
    creditos = {"Libre.ttf": _ficha(b"fuente libre", OFL, texto_de_la_licencia="OFL-Libre.txt")}
    (fuentes / gl.CREDITOS).write_text(json.dumps({"ficheros": creditos}), encoding="utf-8")
    (raiz / "workflows").mkdir()
    workflow = {"modelo": {"pesos": ["unet/qwen-image-Q6_K.gguf"]}}
    (raiz / "workflows" / "plano.json").write_text(json.dumps(workflow), encoding="utf-8")
    (raiz / gl.AVISOS).write_text(AVISO_MINIMO, encoding="utf-8")
    (raiz / "motor").mkdir()
    (raiz / "motor" / "motor.js").write_text("// el reloj lo pone GSAP, instalado con npm\n", encoding="utf-8")
    return gl.ficheros_de_la_carpeta(raiz)


# ------------------------------------------------------------------------------------------ la buena
@pytest.mark.skipif(not (config.BASE_DIR / ".git").exists(), reason=SIN_GIT)
def test_lo_versionado_pasa_la_guarda():
    assert gl.hallazgos(config.BASE_DIR, gl.ficheros_de_git(config.BASE_DIR)) == []


def test_control_una_carpeta_buena_pasa(tmp_path):
    """Sin esto, los controles de abajo podrían fallar por otra cosa que la que estropean."""
    assert gl.hallazgos(tmp_path, _arbol_bueno(tmp_path)) == []


# ------------------------------------------------------------------------------------------ los controles
def test_control_un_efecto_de_pixabay_con_su_procedencia_no_entra(tmp_path):
    _arbol_bueno(tmp_path)
    sfx = tmp_path / "datos" / "escena" / "sfx"
    sfx.mkdir()
    (sfx / "pop.mp3").write_bytes(b"pop")
    ficha = _ficha(b"pop", "Pixabay Content License: uso comercial y modificación permitidos")
    (sfx / gl.CREDITOS).write_text(json.dumps({"ficheros": {"pop.mp3": ficha}}), encoding="utf-8")
    (hallado,) = gl.hallazgos(tmp_path, gl.ficheros_de_la_carpeta(tmp_path))
    assert hallado.startswith("datos/escena/sfx/pop.mp3: su licencia") and "instala_efectos" in hallado


def test_control_una_fuente_ofl_sin_el_texto_de_su_licencia_no_entra(tmp_path):
    _arbol_bueno(tmp_path)
    (tmp_path / "datos" / "escena" / "fuentes" / "OFL-Libre.txt").unlink()
    (hallado,) = gl.hallazgos(tmp_path, gl.ficheros_de_la_carpeta(tmp_path))
    assert "no lleva al lado el texto de su licencia" in hallado


def test_control_una_fuente_cambiada_sin_cambiar_su_procedencia_no_entra(tmp_path):
    _arbol_bueno(tmp_path)
    (tmp_path / "datos" / "escena" / "fuentes" / "Libre.ttf").write_bytes(b"otra fuente")
    (hallado,) = gl.hallazgos(tmp_path, gl.ficheros_de_la_carpeta(tmp_path))
    assert "su sha256 no es el de" in hallado


@pytest.mark.parametrize("fichero", ["canales/example/datos/referencia.png", "datos/escena/fuentes/Georgia.ttf"])
def test_control_un_asset_sin_entrada_en_creditos_no_entra(tmp_path, fichero):
    _arbol_bueno(tmp_path)
    (tmp_path / fichero).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / fichero).write_bytes(b"sin procedencia")
    (hallado,) = gl.hallazgos(tmp_path, gl.ficheros_de_la_carpeta(tmp_path))
    assert hallado.startswith(f"{fichero}: no figura en")


CABECERA_GSAP = "/*!\n * GSAP 3.14.2\n * Subject to the terms at https://gsap.com/standard-license.\n */\n"


def test_control_gsap_copiado_en_el_repositorio_no_entra(tmp_path):
    _arbol_bueno(tmp_path)
    (tmp_path / "motor" / "vendor").mkdir()
    (tmp_path / "motor" / "vendor" / "gsap.min.js").write_text(CABECERA_GSAP, encoding="utf-8")
    (hallado,) = gl.hallazgos(tmp_path, gl.ficheros_de_la_carpeta(tmp_path))
    assert hallado.startswith("motor/vendor/gsap.min.js: lleva GSAP dentro")


@pytest.mark.parametrize("pagina", ["canales/example/escena/composicion.html", "docs/demo.htm"])
def test_control_gsap_pegado_dentro_de_una_pagina_no_entra(tmp_path, pagina):
    """R3 de la revisión de OC1.2: pegado en el `<script>` de una página, pasaba."""
    _arbol_bueno(tmp_path)
    (tmp_path / pagina).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / pagina).write_text(f"<html><script>{CABECERA_GSAP}gsap.to();</script></html>", encoding="utf-8")
    (hallado,) = gl.hallazgos(tmp_path, gl.ficheros_de_la_carpeta(tmp_path))
    assert hallado.startswith(f"{pagina}: lleva GSAP dentro")


def test_control_una_pagina_que_carga_gsap_instalado_entra(tmp_path):
    """Lo que pasa: una página que lo carga de `node_modules`, sin su texto dentro."""
    _arbol_bueno(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "demo.html").write_text(
        '<script src="node_modules/gsap/dist/gsap.min.js"></script>', encoding="utf-8"
    )
    assert gl.hallazgos(tmp_path, gl.ficheros_de_la_carpeta(tmp_path)) == []


@pytest.mark.parametrize(
    "fichero",
    ["docs/icono.svg", "favicon.ico", "modelos/peso.gguf", "lib/red.pt", "lib/red.onnx", "datos/paquete.zip"],
)
def test_control_un_icono_un_peso_o_un_paquete_sin_procedencia_no_entra(tmp_path, fichero):
    """R3 de la revisión de OC1.2: estas extensiones pasaban sin `CREDITOS.json`."""
    _arbol_bueno(tmp_path)
    (tmp_path / fichero).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / fichero).write_bytes(b"de alguien")
    (hallado,) = gl.hallazgos(tmp_path, gl.ficheros_de_la_carpeta(tmp_path))
    assert hallado.startswith(f"{fichero}: no figura en")


def test_control_un_icono_con_su_procedencia_entra(tmp_path):
    """Sin esto, la prueba de arriba también pasaría si la guarda prohibiera los `.svg` sin mirar su procedencia."""
    _arbol_bueno(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "icono.svg").write_bytes(b"<svg/>")
    creditos = {"ficheros": {"icono.svg": _ficha(b"<svg/>", "MIT")}}
    (tmp_path / "docs" / gl.CREDITOS).write_text(json.dumps(creditos), encoding="utf-8")
    assert gl.hallazgos(tmp_path, gl.ficheros_de_la_carpeta(tmp_path)) == []


@pytest.mark.parametrize("quita", sorted(gl.EN_EL_AVISO))
def test_control_un_aviso_que_no_nombra_lo_que_debe_no_pasa(tmp_path, quita):
    _arbol_bueno(tmp_path)
    (tmp_path / gl.AVISOS).write_text(AVISO_MINIMO.replace(quita, "—"), encoding="utf-8")
    assert any(f"no nombra «{quita}»" in h for h in gl.hallazgos(tmp_path, gl.ficheros_de_la_carpeta(tmp_path)))


def test_control_un_peso_nuevo_en_un_workflow_exige_su_aviso(tmp_path):
    _arbol_bueno(tmp_path)
    workflow = {"modelo": {"pesos": ["unet/qwen-image-Q6_K.gguf", "loras/un-lora-nuevo.safetensors"]}}
    (tmp_path / "workflows" / "plano.json").write_text(json.dumps(workflow), encoding="utf-8")
    (hallado,) = gl.hallazgos(tmp_path, gl.ficheros_de_la_carpeta(tmp_path))
    assert "un-lora-nuevo.safetensors" in hallado


def test_control_sin_aviso_no_pasa(tmp_path):
    _arbol_bueno(tmp_path)
    (tmp_path / gl.AVISOS).unlink()
    assert gl.hallazgos(tmp_path, gl.ficheros_de_la_carpeta(tmp_path)) == [
        f"{gl.AVISOS}: no está, y es donde se declaran las licencias de terceros"
    ]


def test_sobre_una_carpeta_no_mira_las_dependencias_ni_los_entornos(tmp_path):
    ficheros = _arbol_bueno(tmp_path)
    for dentro in ("motor/node_modules/gsap/dist/gsap.min.js", ".venv/x.png", ".git/objects/y.mp3"):
        (tmp_path / dentro).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / dentro).write_text(gl.GSAP, encoding="utf-8")
    assert gl.ficheros_de_la_carpeta(tmp_path) == ficheros


# ------------------------------------------------------------------------------------------ lo que viaja
@pytest.mark.parametrize("patron", ["*.gguf", "*.pt", "*.pth", "*.onnx", "*.safetensors", "*.ckpt"])
def test_git_ignora_los_pesos_de_los_modelos(patron):
    """R5 de la revisión de OC1.2: `*.gguf` y `*.pt` no estaban. Un peso no entra en git ni por descuido."""
    lineas = (config.BASE_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert patron in lineas


def _filas_de(seccion: str) -> list[str]:
    """Las filas de la tabla de una sección de `THIRD_PARTY_NOTICES.md` (sin la cabecera ni el separador)."""
    texto = (config.BASE_DIR / gl.AVISOS).read_text(encoding="utf-8")
    cuerpo = texto.split(f"\n## {seccion}", 1)[1].split("\n## ", 1)[0]
    filas = [linea for linea in cuerpo.splitlines() if linea.startswith("|")]
    return filas[2:]


@pytest.mark.parametrize("seccion", ["3. Installed with npm", "4. Tools installed at setup"])
def test_cada_herramienta_del_aviso_lleva_la_fecha_en_que_se_leyo_su_licencia(seccion):
    """R6 de la revisión de OC1.2: la fila del Chrome headless shell era la única sin fecha."""
    filas = _filas_de(seccion)
    assert len(filas) >= 2, f"la sección «{seccion}» ya no tiene tabla: esta prueba no mira nada"
    sin_fecha = [fila[:60] for fila in filas if not re.search(r"\b20\d\d-\d\d-\d\d\b", fila)]
    assert not sin_fecha


def test_el_motor_de_node_y_el_repositorio_llevan_la_misma_licencia_mit():
    """R6 de la revisión de OC1.2: `motor/package.json` decía `UNLICENSED` en un motor MIT."""
    paquete = json.loads((config.BASE_DIR / "motor" / "package.json").read_text(encoding="utf-8"))
    bloqueo = json.loads((config.BASE_DIR / "motor" / "package-lock.json").read_text(encoding="utf-8"))
    assert paquete["license"] == bloqueo["packages"][""]["license"] == "MIT"
    assert (config.BASE_DIR / "LICENSE").read_text(encoding="utf-8").startswith("MIT License\n")


# ------------------------------------------------------------------------------------------ Orpheus
def test_orpheus_lleva_la_licencia_de_llama_y_no_apache():
    """Es un derivado de Llama 3.2 (OC1.2): manda la Llama 3.2 Community License, con «Built with Llama»."""
    codigo = (config.BASE_DIR / "lib" / "voice_worker.py").read_text(encoding="utf-8")
    docstring = codigo.split("class MotorOrpheus:", 1)[1].split('"""')[1]
    assert "Llama 3.2 Community License" in docstring and "Built with Llama" in docstring
    assert "(Apache-2.0)" not in docstring.splitlines()[0]
    aviso = (config.BASE_DIR / gl.AVISOS).read_text(encoding="utf-8")
    assert "Built with Llama" in aviso and "Copyright © Meta Platforms, Inc. All Rights Reserved." in aviso
