"""La guarda de datos personales (`scripts/guarda_datos_personales.py`, OC1.3) y la lista blanca que recorre.

La prueba buena es el repositorio de verdad: lo que nombra la lista blanca tiene que pasar. Cada clase de dato tiene su
control negativo, sobre una carpeta temporal que empieza siendo buena y se estropea en una sola cosa.

**Las muestras se escriben partidas** (`"C:" + "\\IA"`), y las cadenas personales se leen de su fichero: este fichero
va al repositorio público y la guarda lo recorre, así que no puede llevar dentro lo que ella busca.

**En el repositorio público** no están ni la lista blanca ni el fichero de cadenas personales, que son del arnés del
dueño: las pruebas que los leen se saltan con su motivo, y la prueba buena recorre el repositorio entero.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from scripts import guarda_datos_personales as gd

RAIZ = Path(__file__).resolve().parent.parent
# La lista blanca es del arnés del dueño: en el repositorio público no está.
HAY_LISTA = (RAIZ / gd.LISTA_BLANCA).is_file()
SIN_LISTA = "sin la lista blanca: esto es el repositorio público, que no la lleva"
ENTRADAS = (
    json.loads((RAIZ / gd.CADENAS_PERSONALES).read_text(encoding="utf-8"))["cadenas"]
    if (RAIZ / gd.CADENAS_PERSONALES).is_file()
    else []
)
# Una muestra con el formato real de cada clase genérica, y lo que la guarda dice de ella.
GENERICAS = [
    ("una clave de Google (API key)", "AIza" + "SyD4x9" + "k" * 29),
    ("un secreto de cliente OAuth de Google", "GOCSPX-" + "a1b2c3d4e5f6g7h8i9j0"),
    ("un token de acceso de Google", "ya29." + "a0" * 20),
    ("un refresh token de Google", "1//0" + "g" * 30),
    ("una clave de OpenAI o de Anthropic", "sk-" + "ant-api03-" + "x" * 30),
    ("un token de Hugging Face", "hf_" + "A" * 34),
    ("un token de GitHub", "ghp_" + "B" * 36),
    ("un token de Apify", "apify_api_" + "C" * 25),
    ("una URL con usuario y contraseña", "https://" + "usuario:secreto" + "@localhost/"),
    ("una clave privada", "-----BEGIN " + "PRIVATE KEY-----"),
    ("un id de canal de YouTube", "UC" + "a1B2c3D4e5F6g7H8i9J0kL"),
    ("un email", "alguien" + "@" + "ejemplo.org"),
    ("una carpeta de usuario de Windows", "C:" + "\\Users\\" + "alguien\\Documents"),
    ("una carpeta de usuario de Windows", "D:" + "/Users/" + "alguien/"),
    ("una carpeta de usuario de Windows", "/c" + "/Users/" + "alguien/.cache"),  # Git Bash
    ("una carpeta de usuario de Windows", "/mnt/c" + "/users/" + "alguien/"),  # WSL
    ("la carpeta de herramientas de este PC", "C:" + "\\IA\\" + "ComfyUI"),
    ("la carpeta de herramientas de este PC", "C:" + "\\\\IA\\\\" + "llama.cpp"),
    ("la carpeta de herramientas de este PC", "c:" + "\\ia\\" + "comfyui"),
]


def _arbol_bueno(raiz: Path) -> list[str]:
    """Una carpeta que pasa: código con rutas que no son de nadie y una licencia con el email de su autor."""
    (raiz / "lib").mkdir(parents=True)
    (raiz / "lib" / "limpio.py").write_text(
        'COMFY = "<COMFY_ROOT>\\\\main.py"  # la ruta la escribe el usuario en su .env\n'
        'PERFIL = "C:\\\\Users\\\\<usuario>\\\\.cache"\n'
        'BASH = "/c/Users/<usuario>/.cache"\n'
        "@dataclass\nclass A: ...\n",
        encoding="utf-8",
    )
    (raiz / "datos").mkdir()
    (raiz / "datos" / "OFL.txt").write_text(f"Copyright The Authors ({min(gd.EMAILS_DE_TERCEROS)})\n", encoding="utf-8")
    return gd.ficheros_de_la_carpeta(raiz)


def _con(raiz: Path, texto: str, rel: str = "lib/modulo.py") -> list[str]:
    _arbol_bueno(raiz)
    (raiz / rel).parent.mkdir(parents=True, exist_ok=True)
    (raiz / rel).write_text(f'X = "{texto}"\n', encoding="utf-8")
    return gd.hallazgos(raiz, gd.ficheros_de_la_carpeta(raiz), gd.cadenas_personales())


# ------------------------------------------------------------------------------------------ la buena
def _lo_que_viaja() -> list[str]:
    """En la fábrica, lo que nombra la lista blanca. En el repositorio público, todo lo versionado o, en una exportación
    que aún no es un repositorio, lo que hay en la carpeta."""
    if HAY_LISTA:
        return gd.ficheros_de_git(RAIZ, gd.lee_lista_blanca())
    if (RAIZ / ".git").exists():
        return gd.ficheros_de_git(RAIZ, None)
    return gd.ficheros_de_la_carpeta(RAIZ)


def test_lo_que_nombra_la_lista_blanca_pasa_la_guarda():
    ficheros = _lo_que_viaja()
    assert len(ficheros) > 200, f"solo {len(ficheros)} ficheros: la lista blanca no se está leyendo bien"
    assert gd.hallazgos(RAIZ, ficheros, gd.cadenas_personales(), gd.se_permite()) == []


def test_control_una_carpeta_buena_pasa(tmp_path):
    """Sin esto, los controles de abajo podrían fallar por otra cosa que la que estropean."""
    assert gd.hallazgos(tmp_path, _arbol_bueno(tmp_path), gd.cadenas_personales()) == []


# ------------------------------------------------------------------------------------------ la lista blanca
@pytest.mark.skipif(not HAY_LISTA, reason=SIN_LISTA)
@pytest.mark.parametrize(
    "rel",
    [
        gd.CADENAS_PERSONALES,
        gd.LISTA_BLANCA,
        "progress/history.md",
        "CHECKPOINTS.md",
        "CLAUDE.md",
        "feature_list.json",
        "doc/02-decisiones-tecnicas.md",
        ".claude/agents/implementer.md",
        ".claude/skills/audit-proyecto/SKILL.md",  # audita el arnés del dueño
        ".claude/skills/pone-en-escena/scripts/__pycache__/en_seco.cpython-314.pyc",
        "init.mjs",
        "scripts/audita.py",
        "tests/test_sin_estudio.py",
        "exportacion/exporta.py",  # la exportación (OC1.9) y su prueba
        "tests/test_exporta.py",
    ],
)
def test_la_lista_blanca_deja_fuera_el_arnes_y_las_cadenas_personales(rel):
    assert not gd.en_la_lista_blanca(rel, gd.lee_lista_blanca())


@pytest.mark.skipif(not HAY_LISTA, reason=SIN_LISTA)
@pytest.mark.parametrize(
    "rel",
    [
        "pipeline.py",
        "lib/escena/render.py",
        "canales/example/perfil.json",
        ".env.example",
        "scripts/guarda_datos_personales.py",  # la guarda se recorre a sí misma
        "tests/test_datos_personales.py",
        ".claude/skills/script-to-slides/SKILL.md",  # las cinco skills del motor
        ".claude/skills/pone-en-escena/scripts/en_seco.py",
        "exportacion/CLAUDE.md",  # el manual del motor, que la exportación deja en la raíz
        "detector.cmd",  # el detector de la marca sin terminal (OC1.13), que no cubre ningún patrón
        "scripts/detector_web.py",
        "LICENSE",  # la licencia MIT del motor (OC1.9)
        "README.md",  # la portada de Lanternist y sus plantillas (OC1.10)
        "CONTRIBUTING.md",
        ".github/ISSUE_TEMPLATE/bug.yml",
        "docs/faq.md",
    ],
)
def test_control_la_lista_blanca_mete_el_motor(rel):
    assert gd.en_la_lista_blanca(rel, gd.lee_lista_blanca())


def test_sobre_git_solo_cuenta_la_lista_blanca_y_tambien_lo_nuevo(tmp_path):
    """La condición real: un repositorio con su lista blanca, un fichero fuera de ella y otro aún sin commit."""
    email = "alguien" + "@" + "ejemplo.org"
    (tmp_path / "exportacion").mkdir()
    (tmp_path / gd.LISTA_BLANCA).write_text("# el motor\nlib/*\n!lib/privado.py\n", encoding="utf-8")
    for rel in ("lib/a.py", "lib/privado.py", "progress/informe.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(f"# {email}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    (tmp_path / "lib" / "nuevo.py").write_text(f"# {email}\n", encoding="utf-8")
    ficheros = gd.ficheros_de_git(tmp_path, gd.lee_lista_blanca(tmp_path))
    assert ficheros == ["lib/a.py", "lib/nuevo.py"]
    assert len(gd.hallazgos(tmp_path, ficheros, [])) == 2


def test_en_el_repositorio_publico_lo_que_no_tiene_commit_no_cuenta(tmp_path):
    """Sin lista blanca (el repositorio público), solo lo versionado: el estado del primer run de quien instala, con la
    carpeta de su usuario, no pone la guarda en rojo hasta que lo mete en git (hallazgo del clon limpio, fila 328)."""
    rel = "canales/example/datos/estado/un-run.json"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text('{"output_dir": "C:' + "\\\\Users\\\\" + 'alguien\\\\lanternist"}\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert gd.ficheros_de_git(tmp_path, None) == []
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)  # control: camino del commit, ya cuenta
    assert gd.ficheros_de_git(tmp_path, None) == [rel]
    assert len(gd.hallazgos(tmp_path, [rel], [])) == 1


# ------------------------------------------------------------------------------------------ los controles
@pytest.mark.parametrize(("que_es", "muestra"), GENERICAS, ids=[m[:12] for _, m in GENERICAS])
def test_control_cada_clase_generica_se_caza(tmp_path, que_es, muestra):
    (hallado,) = _con(tmp_path, muestra)
    assert hallado.startswith("lib/modulo.py:1: ") and que_es in hallado


@pytest.mark.parametrize("codificacion", ["utf-16", "utf-16-le", "utf-16-be"])
def test_control_un_texto_en_utf16_tambien_se_lee(tmp_path, codificacion):
    """`>` en PowerShell 5 escribe UTF-16 con BOM (`utf-16`); sin BOM, se reconoce por sus bytes altos a cero."""
    _arbol_bueno(tmp_path)
    linea = "# línea 1\n$correo = '" + "alguien" + "@" + "ejemplo.org'\n"
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "instala.ps1").write_bytes(linea.encode(codificacion))
    (hallado,) = gd.hallazgos(tmp_path, gd.ficheros_de_la_carpeta(tmp_path), [])
    assert hallado.startswith("scripts/instala.ps1:2: un email")


def test_control_un_binario_con_bytes_nulos_sueltos_no_se_lee_como_texto():
    """Lo que no es UTF-16 sigue siendo binario: una imagen con bytes nulos sueltos no se decodifica."""
    binario = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + bytes(range(1, 200)) + b"\0\x01\x02"
    assert gd.texto_de(binario) is None
    assert gd.texto_de("hola".encode("utf-16-le")) == "hola"


@pytest.mark.parametrize(
    "variante",
    [
        "Canal De Prueba",
        "canal_de_prueba",
        "canal-de-prueba",
        "CanalDePrueba",
        "Canal De\n# Prueba",
        "Canal\n// de prueba",
    ],
)
def test_una_cadena_de_varias_palabras_se_caza_con_cualquier_separador(variante):
    assert gd.patron_de("Canal de Prueba").search(f"X = '{variante}'")


@pytest.mark.parametrize("variante", ["Canal Prueba", "Canal de Pruebas", "Canal del Prueba"])
def test_control_otras_palabras_no_son_la_cadena(variante):
    assert not gd.patron_de("Canal de Prueba", solo_palabra=True).search(f"X = '{variante}'")


@pytest.mark.skipif(not ENTRADAS, reason="sin cadenas personales: esto es el repositorio público")
def test_control_cada_cadena_de_varias_palabras_se_caza_partida_y_sin_separadores(tmp_path):
    varias = [e for e in ENTRADAS if len(re.split(r"[\W_]+", e["texto"].strip("_- "))) > 1]
    assert varias, "la lista ya no tiene cadenas de varias palabras: este control no prueba nada"
    sin_cazar = []
    for i, entrada in enumerate(varias):
        palabras = [p for p in re.split(r"[\W_]+", entrada["texto"]) if p]
        for j, variante in enumerate(("_".join(palabras), "".join(palabras), "\n# ".join(palabras))):
            if not any(entrada["que_es"] in h for h in _con(tmp_path / f"{i}-{j}", variante)):
                sin_cazar.append(f"cadena {i} ({entrada['que_es']}), variante {j}")
    assert not sin_cazar


@pytest.mark.skipif(not ENTRADAS, reason="sin cadenas personales: esto es el repositorio público")
def test_control_cada_cadena_personal_se_caza_tambien_en_minusculas(tmp_path):
    sin_cazar = []
    for i, entrada in enumerate(ENTRADAS):
        for j, variante in enumerate((entrada["texto"], entrada["texto"].lower(), "_de_" + entrada["texto"] + "_")):
            if not any(entrada["que_es"] in h for h in _con(tmp_path / f"{i}-{j}", variante)):
                sin_cazar.append(f"cadena {i} ({entrada['que_es']}), variante {j}")
    assert not sin_cazar


@pytest.mark.skipif(not ENTRADAS, reason="sin cadenas personales: esto es el repositorio público")
def test_control_una_cadena_de_palabra_dentro_de_un_hash_no_cuenta(tmp_path):
    """`solo_palabra`: un sha256 puede contener las cuatro letras de un id de canal sin nombrarlo."""
    palabras = [e for e in ENTRADAS if e.get("solo_palabra")]
    assert palabras, "la lista ya no tiene cadenas de palabra: este control no prueba nada"
    for i, entrada in enumerate(palabras):
        assert _con(tmp_path / str(i), "9f" + entrada["texto"].lower() + "e1") == []


@pytest.mark.skipif(not ENTRADAS, reason="sin cadenas personales: esto es el repositorio público")
def test_control_la_ruta_de_un_fichero_tambien_cuenta(tmp_path):
    palabra = next(e for e in ENTRADAS if e.get("solo_palabra"))
    hallados = _con(tmp_path, "nada", rel=f"canales/{palabra['texto']}-algo/perfil.json")
    assert any(h.startswith(f"canales/{palabra['texto']}-algo/perfil.json: su ruta lleva") for h in hallados)


def test_control_la_orden_sale_con_1_si_hay_hallazgos_y_con_0_si_no(tmp_path):
    _con(tmp_path / "mala", "alguien" + "@" + "ejemplo.org")
    _arbol_bueno(tmp_path / "buena")
    assert gd.main([str(tmp_path / "mala")]) == 1
    assert gd.main([str(tmp_path / "buena")]) == 0


def test_sin_carpeta_y_fuera_de_un_repositorio_sale_con_3_y_lo_dice(tmp_path, monkeypatch, capsys):
    """Antes rompía con una traza y salía con 1, el mismo código que «con hallazgos» (R3 de la revisión de OC1.3)."""
    monkeypatch.setattr(gd, "RAIZ", tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert gd.main([]) == 3
    assert "no es un repositorio de git" in capsys.readouterr().out


def test_control_sin_carpeta_y_dentro_de_un_repositorio_corre(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, "RAIZ", tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert gd.main([]) == 0


# ------------------------------------------------------------------------------------------ las excepciones decididas
PERMITIDO = "Copyright (c) 2026 " + "Acme" + "Labs"
CADENA_DE_PRUEBA = [("una marca de prueba", gd.patron_de("Acme"))]


def test_el_texto_permitido_pasa_en_su_fichero(tmp_path):
    (tmp_path / "LICENSE").write_text(f"MIT License\n\n{PERMITIDO}\n", encoding="utf-8")
    assert gd.hallazgos(tmp_path, ["LICENSE"], CADENA_DE_PRUEBA, {"LICENSE": [PERMITIDO]}) == []


@pytest.mark.parametrize(
    ("rel", "texto"),
    [
        ("LICENSE", f"{PERMITIDO}\nMantenido por " + "Acme" + ".\n"),  # otra línea del mismo fichero
        ("lib/modulo.py", f"# {PERMITIDO}\n"),  # el mismo texto en otro fichero
    ],
)
def test_control_la_excepcion_no_vale_fuera_de_su_texto_ni_de_su_fichero(tmp_path, rel, texto):
    (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(texto, encoding="utf-8")
    (hallado,) = gd.hallazgos(tmp_path, [rel], CADENA_DE_PRUEBA, {"LICENSE": [PERMITIDO]})
    assert hallado.startswith(f"{rel}:") and "una marca de prueba" in hallado


def test_control_la_excepcion_no_tapa_los_genericos(tmp_path):
    email = "alguien" + "@" + "ejemplo.org"
    (tmp_path / "LICENSE").write_text(f"{PERMITIDO} <{email}>\n", encoding="utf-8")
    (hallado,) = gd.hallazgos(tmp_path, ["LICENSE"], CADENA_DE_PRUEBA, {"LICENSE": [f"{PERMITIDO} <{email}>"]})
    assert "un email" in hallado


@pytest.mark.skipif(not ENTRADAS, reason="sin cadenas personales: esto es el repositorio público")
@pytest.mark.parametrize("rel", ["LICENSE", ".github/ISSUE_TEMPLATE/config.yml"])
def test_lo_que_nombra_la_marca_pasa_solo_por_su_excepcion(rel):
    """El titular del LICENSE y la URL del repositorio llevan la marca con la que se publica, que es una cadena
    personal: sin la excepción decidida, la guarda los pararía. Así se sabe que la excepción es lo que los deja pasar,
    y no que no los mire."""
    assert gd.hallazgos(RAIZ, [rel], gd.cadenas_personales(), gd.se_permite()) == []
    assert gd.hallazgos(RAIZ, [rel], gd.cadenas_personales(), {}) != []


# ------------------------------------------------------------------------------------------ falla cerrada
@pytest.mark.parametrize("marca", gd.MARCAS_DE_LA_FABRICA)
def test_en_la_fabrica_sin_las_cadenas_personales_no_corre(tmp_path, marca):
    (tmp_path / marca).mkdir()
    with pytest.raises(FileNotFoundError, match="esto es la fábrica"):
        gd.cadenas_personales(tmp_path)


def test_control_en_el_repositorio_publico_corre_con_los_genericos(tmp_path):
    assert gd.cadenas_personales(tmp_path) == []


def test_la_orden_sin_las_cadenas_personales_sale_con_2(monkeypatch, tmp_path):
    """Una fábrica de prueba (con su arnés y sin el fichero privado): vale igual en la fábrica y en el público."""
    (tmp_path / "fabrica" / "progress").mkdir(parents=True)
    monkeypatch.setattr(gd, "RAIZ", tmp_path / "fabrica")
    assert gd.main([str(tmp_path)]) == 2
