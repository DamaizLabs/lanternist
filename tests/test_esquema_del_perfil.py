"""El esquema del perfil y la orden que crea un canal mínimo (OC1.4).

Correr: .venv\\Scripts\\python -m pytest -q tests/test_esquema_del_perfil.py

**Qué fija.** Las siete decisiones obligatorias de un canal, los interruptores de música y subtítulos y el formato de
escena viven en un solo sitio (`lib/config.py → DECISIONES_OBLIGATORIAS` e `INTERRUPTORES`). De ahí leen el validador
(`problemas_del_perfil`), que dice qué falta y qué escribir, y `canal.py --nuevo`, que crea un canal con ellas. La orden
no es interactiva: la lanza Claude, que no puede contestar a un `input()`.

Cada prueba que acepta tiene su control que se niega: un perfil al que le falta una decisión, una orden sin decisiones,
un id que no es un slug y un canal que ya existe.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

import canal
from lib import config

RAIZ = Path(__file__).resolve().parent.parent
PERFILES = sorted((RAIZ / "canales").glob("*/perfil.json"))
OBLIGATORIAS = {**config.DECISIONES_OBLIGATORIAS, **config.INTERRUPTORES}

# Un canal completo, como lo pediría Claude desde la skill `crea-canal`: cada decisión con el ejemplo del esquema.
COMPLETO = {
    "imagen.modelo": "qwen-2512-lightning-tinta",
    "imagen.seed": "2026",
    "voz.receta": "voz-orpheus-everyday-inventions.json",
    "idioma.narracion": "en",
    "idioma.subtitulos": "en",
    "publicacion.hecho_para_ninos": "false",
    "publicacion.categoria_youtube": "27",
    "musica.activa": "true",
    "subtitulos.activos": "false",
    "formato": "laminas",
}


def _perfil_valido() -> dict:
    return json.loads(PERFILES[0].read_text(encoding="utf-8"))


def _quita(perfil: dict, ruta: str) -> dict:
    perfil = copy.deepcopy(perfil)
    *bloques, clave = ruta.split(".")
    nodo = perfil
    for bloque in bloques:
        nodo = nodo[bloque]
    del nodo[clave]
    return perfil


# ── El validador ─────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ruta", PERFILES, ids=lambda p: p.parent.name)
def test_cada_perfil_del_repositorio_cumple_el_esquema(ruta: Path):
    assert config.problemas_del_perfil(json.loads(ruta.read_text(encoding="utf-8"))) == []


@pytest.mark.parametrize("ruta", list(OBLIGATORIAS))
def test_control_un_perfil_sin_una_decision_se_niega_con_su_motivo(ruta: str):
    """El control negativo del criterio 9: cada decisión que falta da UNA línea con la clave y qué escribir."""
    (problema,) = config.problemas_del_perfil(_quita(_perfil_valido(), ruta))
    _, _, ejemplo = OBLIGATORIAS[ruta]
    assert f"falta `{ruta}`" in problema and ejemplo in problema


@pytest.mark.parametrize(
    ("ruta", "valor"),
    [
        ("imagen.seed", "2026"),  # un texto no es una semilla
        ("imagen.seed", True),  # y un booleano tampoco, aunque en Python sea un int
        ("publicacion.hecho_para_ninos", "false"),  # `bool("false")` sería True
        ("imagen.modelo", "  "),
        ("musica.activa", 1),
        ("idioma.narracion", None),
    ],
)
def test_control_un_valor_con_el_tipo_equivocado_se_niega(ruta: str, valor):
    perfil = _perfil_valido()
    bloque, clave = ruta.split(".")
    perfil[bloque][clave] = valor
    (problema,) = config.problemas_del_perfil(perfil)
    assert f"`{ruta}`" in problema


def test_el_formato_de_escena_es_el_tercer_interruptor():
    perfil = _perfil_valido()
    assert config.problemas_del_perfil({**perfil, "escena": {}}) == [], "sin bloque de formato es «personajes»"
    (sin_escena,) = config.problemas_del_perfil({k: v for k, v in perfil.items() if k != "escena"})
    assert "`escena`" in sin_escena
    (dos,) = config.problemas_del_perfil({**perfil, "escena": {"laminas": {}, "pizarra": {}}})
    assert "dos formatos" in dos


def test_control_lo_que_no_es_un_objeto_se_niega():
    assert config.problemas_del_perfil(["no", "es", "un", "perfil"]) != []


def test_el_ejemplo_de_lo_que_falta_sale_del_esquema():
    """`_del_canal` ya no lleva sus propios ejemplos: el de cada decisión está escrito una vez, en el esquema."""
    texto = (RAIZ / "lib" / "config.py").read_text(encoding="utf-8")
    for ruta in config.DECISIONES_OBLIGATORIAS:
        llamada = texto[texto.index(f'_del_canal("{ruta}"') :].split("\n", 1)[0]
        assert "ejemplo=" not in llamada, llamada


# ── La orden que crea un canal mínimo ──────────────────────────────────────────────────────────────────────────


def test_con_todas_las_decisiones_crea_un_perfil_que_cumple_el_esquema(tmp_path):
    carpeta, problemas = canal.crea_canal("everyday-inventions", COMPLETO, tmp_path)
    assert problemas == [] and carpeta == tmp_path / "everyday-inventions"
    perfil = json.loads((carpeta / "perfil.json").read_text(encoding="utf-8"))
    assert config.problemas_del_perfil(perfil) == []
    assert perfil["id"] == "everyday-inventions"
    assert perfil["imagen"] == {"modelo": "qwen-2512-lightning-tinta", "seed": 2026}
    assert perfil["publicacion"] == {"hecho_para_ninos": False, "categoria_youtube": "27"}
    assert perfil["musica"] == {"activa": True} and perfil["subtitulos"] == {"activos": False}
    assert perfil["escena"] == {"laminas": {}}
    assert [p.name for p in tmp_path.iterdir()] == ["everyday-inventions"]


def test_control_sin_decisiones_se_niega_las_lista_todas_y_no_crea_nada(tmp_path):
    carpeta, problemas = canal.crea_canal("everyday-inventions", {}, tmp_path)
    assert carpeta is None
    assert len(problemas) == len(OBLIGATORIAS) + 1  # y el formato
    for ruta, (_, _, ejemplo) in OBLIGATORIAS.items():
        assert any(f"falta --{ruta}" in p and f"--{ruta} {ejemplo}" in p for p in problemas), ruta
    assert any("falta --formato" in p for p in problemas)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("falta", [*OBLIGATORIAS, "formato"])
def test_control_con_una_decision_de_menos_se_niega(tmp_path, falta):
    (problema,) = canal.crea_canal("everyday-inventions", {k: v for k, v in COMPLETO.items() if k != falta}, tmp_path)[
        1
    ]
    assert f"--{falta}" in problema
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "Everyday",  # mayúsculas
        "C" + "001-algo",  # el prefijo numerado de los canales del estudio (partido: tests/test_sin_estudio.py)
        "con espacio",
        "../fuera",
        "-delante",
        "doble--guion",
        "con_barra_baja",
    ],
)
def test_control_un_id_que_no_es_un_slug_se_niega(tmp_path, slug):
    carpeta, problemas = canal.crea_canal(slug, COMPLETO, tmp_path)
    assert carpeta is None and any("no vale" in p and "slug" in p for p in problemas)
    assert list(tmp_path.iterdir()) == [] and not (tmp_path.parent / "fuera").exists()


def test_control_un_canal_que_ya_existe_no_se_pisa(tmp_path):
    (tmp_path / "everyday-inventions").mkdir()
    (tmp_path / "everyday-inventions" / "perfil.json").write_text('{"id": "el de antes"}', encoding="utf-8")
    carpeta, problemas = canal.crea_canal("everyday-inventions", COMPLETO, tmp_path)
    assert carpeta is None and any("ya existe" in p for p in problemas)
    assert (tmp_path / "everyday-inventions" / "perfil.json").read_text(encoding="utf-8") == '{"id": "el de antes"}'


@pytest.mark.parametrize(
    ("ruta", "valor"),
    [
        ("imagen.seed", "dos mil"),
        ("musica.activa", "si"),
        ("publicacion.categoria_youtube", "999"),
        ("formato", "tinta"),
    ],
)
def test_control_un_valor_que_no_encaja_se_niega(tmp_path, ruta, valor):
    (problema,) = canal.crea_canal("everyday-inventions", {**COMPLETO, ruta: valor}, tmp_path)[1]
    assert f"--{ruta}" in problema and repr(valor) in problema
    assert list(tmp_path.iterdir()) == []


def _argumentos(slug: str, valores: dict) -> list[str]:
    return ["--nuevo", slug, *[x for ruta, valor in valores.items() for x in (f"--{ruta}", valor)]]


def test_la_orden_de_canal_py_crea_el_canal_sin_preguntar(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(canal, "CANALES_DIR", tmp_path)
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("la orden preguntó algo"))
    assert canal.main(_argumentos("everyday-inventions", COMPLETO)) == 0
    assert (tmp_path / "everyday-inventions" / "perfil.json").is_file()
    assert "scripts/comprueba_canal.py --canal everyday-inventions" in capsys.readouterr().out


def test_control_las_decisiones_sin_nuevo_no_hacen_nada(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(canal, "CANALES_DIR", tmp_path)
    assert canal.main(["--imagen.seed", "2026"]) == 2
    assert "solo valen con --nuevo" in capsys.readouterr().out and list(tmp_path.iterdir()) == []


def test_en_la_condicion_real_la_orden_sin_decisiones_sale_con_2_y_no_escribe_en_canales():
    """Como la lanza Claude: un proceso aparte, sobre el repositorio de verdad. Se niega, así que no escribe nada."""
    slug = "prueba-oc1-4-sin-decisiones"
    r = subprocess.run(
        [sys.executable, str(RAIZ / "canal.py"), "--nuevo", slug],
        capture_output=True, text=True, encoding="utf-8", cwd=RAIZ,
    )  # fmt: skip
    assert r.returncode == 2, r.stdout + r.stderr
    assert "falta --imagen.seed" in r.stdout and "falta --formato" in r.stdout
    assert not (RAIZ / "canales" / slug).exists()
