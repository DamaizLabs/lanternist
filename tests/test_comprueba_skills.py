"""La guarda de la fila 271: las skills que automatizan el estudio, al día con el código.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_comprueba_skills.py

Cada prueba monta un repositorio mínimo en `tmp_path` que está al día, rompe una sola cosa y mira que la guarda la
caza, y solo esa. La última pasa la guarda sobre el repositorio real: si alguien añade un formato o un canal sin
contárselo a las skills, la suite se pone en rojo.
"""

import json
from pathlib import Path

from scripts.comprueba_skills import comprueba

FORMATOS = ("personajes", "laminas", "pizarra")
CATALOGO = """# Catálogo

## Formatos hechos

### `personajes` — Characters
- **Channels**: C102.

### `laminas` — Slides
- **Channels**: C101.

### `pizarra` — Chalkboard
- **Channels**: C103.

## Por construir
"""
QUE_PRODUCE = "En `personajes`, en «láminas» y en `pizarra` cambia esto.\n"
CODIGO = 'import argparse\np = argparse.ArgumentParser()\np.add_argument("--canal")\n'
# Las skills que viajan al repositorio público, como en la lista de verdad: `audit-proyecto` es del dueño y no está.
LISTA_BLANCA = "lib/*\n" + "".join(
    f".claude/skills/{n}/*\n"
    for n in ("crea-canal", "produce-semana", "pone-en-escena", "script-to-slides", "propone-formato")
)
# Una línea que cita las cuatro cosas del arnés del dueño. Las rutas existen o son plantillas: solo cuenta el arnés.
CITA_EL_ARNES = "Mira `doc/07-guia.md`, `progress/gate1_<canal>.md`, CHECKPOINTS.md y la fila 271.\n"


def _escribe(ruta: Path, texto: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")


def _repo(raiz: Path) -> Path:
    """Un repositorio al día: tres canales, uno por formato, las cuatro skills que la guarda mira y su lista blanca."""
    _escribe(raiz / "exportacion" / "lista-blanca.txt", LISTA_BLANCA)
    _escribe(raiz / "docs" / "formats.md", CATALOGO)
    _escribe(raiz / "doc" / "07-guia.md", "guía\n")
    _escribe(raiz / ".gitignore", "canales/*/videos/\nprogress/*.html\n*.wav\n")
    _escribe(raiz / "scripts" / "hola.py", CODIGO)
    _escribe(raiz / "lib" / "modulo.py", "VALOR = 1\n")
    perfiles = {
        "C101-a": {"escena": {"laminas": {}}},
        "C102-b": {"escena": {}},
        "C103-c": {"escena": {"pizarra": {}}},
    }
    for canal, perfil in perfiles.items():
        _escribe(raiz / "canales" / canal / "perfil.json", json.dumps(perfil))
    for nombre in ("produce-semana", "pone-en-escena", "script-to-slides"):
        _escribe(raiz / ".claude" / "skills" / nombre / "SKILL.md", QUE_PRODUCE)
    _escribe(raiz / ".claude" / "skills" / "propone-formato" / "SKILL.md", "Elige en `docs/formats.md`.\n")
    return raiz


def _skill(raiz: Path, texto: str, nombre: str = "produce-semana") -> None:
    _escribe(raiz / ".claude" / "skills" / nombre / "SKILL.md", QUE_PRODUCE + texto)


def test_un_repositorio_al_dia_no_da_ningun_hallazgo(tmp_path):
    assert comprueba(_repo(tmp_path), FORMATOS) == []


def test_caza_una_skill_que_produce_y_no_nombra_un_formato(tmp_path):
    raiz = _repo(tmp_path)
    _escribe(raiz / ".claude" / "skills" / "script-to-slides" / "SKILL.md", "En `personajes` y en «láminas».\n")
    (hallazgo,) = comprueba(raiz, FORMATOS)
    assert hallazgo.startswith("script-to-slides: no nombra el formato `pizarra`")


def test_una_referencia_de_la_skill_cuenta_y_la_palabra_suelta_no(tmp_path):
    """El formato puede estar en un `references/*.md`; «pizarra» sin comillas ni código es la palabra, no el formato."""
    raiz = _repo(tmp_path)
    skill = raiz / ".claude" / "skills" / "pone-en-escena"
    _escribe(skill / "SKILL.md", "En `personajes`, en `laminas` y en la pizarra de clase.\n")
    (hallazgo,) = comprueba(raiz, FORMATOS)
    assert hallazgo.startswith("pone-en-escena: no nombra el formato `pizarra`")
    _escribe(skill / "references" / "formato-pizarra.md", "El formato «pizarra».\n")
    assert comprueba(raiz, FORMATOS) == []


def test_caza_un_formato_sin_ficha_y_un_canal_que_su_ficha_no_cuenta(tmp_path):
    raiz = _repo(tmp_path)
    _escribe(raiz / "docs" / "formats.md", CATALOGO.replace("- **Channels**: C103.", "- **Channels**: none yet."))
    assert comprueba(raiz, FORMATOS) == [
        "docs/formats.md: la ficha de `pizarra` no cuenta C103 en su línea «**Channels**», y C103-c produce en ella"
    ]
    _escribe(raiz / "docs" / "formats.md", CATALOGO.replace("### `pizarra`", "### pizarra"))
    hallazgos = comprueba(raiz, FORMATOS)
    assert "docs/formats.md: el formato `pizarra` no tiene ficha («### `pizarra`»)" in hallazgos
    assert "canales/C103-c: produce en `pizarra`, y el catálogo no tiene su ficha" in hallazgos


def test_caza_un_canal_con_dos_formatos(tmp_path):
    raiz = _repo(tmp_path)
    _escribe(raiz / "canales" / "C104-d" / "perfil.json", json.dumps({"escena": {"laminas": {}, "pizarra": {}}}))
    (hallazgo,) = comprueba(raiz, FORMATOS)
    assert hallazgo.startswith("canales/C104-d/perfil.json: no se sabe su formato")


def test_caza_que_propone_formato_deje_de_citar_el_catalogo(tmp_path):
    """La historia interna (`doc/10-catalogo-de-formatos.md`) no es el catálogo: citarla no basta, y no viaja."""
    raiz = _repo(tmp_path)
    _escribe(raiz / "doc" / "10-catalogo-de-formatos.md", "La historia.\n")
    _escribe(raiz / ".claude" / "skills" / "propone-formato" / "SKILL.md", "Mira `doc/10-catalogo-de-formatos.md`.\n")
    assert comprueba(raiz, FORMATOS) == [
        "propone-formato: no cita el catálogo (docs/formats.md), del que elige el formato",
        "propone-formato/SKILL.md:1: cita doc/, que es del arnés del dueño y no viaja al repositorio público: dilo en "
        "palabras, o cita docs/ o el código",
    ]


def test_caza_un_script_que_no_existe_y_una_opcion_que_no_conoce(tmp_path):
    raiz = _repo(tmp_path)
    _skill(
        raiz,
        "```powershell\n"
        "$env:CANAL_ACTIVO='<id>'; .venv\\Scripts\\python scripts/hola.py --canal x   # --esto es un comentario\n"
        ".venv\\Scripts\\python scripts/hola.py --inventada\n"
        ".venv\\Scripts\\python scripts/adios.py --canal x\n"
        "```\n",
    )
    assert comprueba(raiz, FORMATOS) == [
        "produce-semana/SKILL.md:4: pasa --inventada a scripts/hola.py, y scripts/hola.py no conoce esa opción",
        "produce-semana/SKILL.md:5: manda correr scripts/adios.py y no existe",
    ]


def test_las_ordenes_de_plantilla_y_las_de_modulo_no_se_comprueban(tmp_path):
    raiz = _repo(tmp_path)
    _skill(raiz, "todo `python X.py` existe; `python -m scripts.otra --lo-que-sea`\n")
    assert comprueba(raiz, FORMATOS) == []


def test_caza_una_ruta_que_no_existe_y_una_referencia_que_no_existe(tmp_path):
    raiz = _repo(tmp_path)
    _skill(raiz, "Lee `lib/borrado.py` y `references/no-esta.md`.\n")
    assert comprueba(raiz, FORMATOS) == [
        "produce-semana/SKILL.md:2: cita lib/borrado.py y no existe",
        "produce-semana/SKILL.md:2: cita references/no-esta.md y no existe en ninguna skill",
    ]


def test_las_rutas_que_no_son_un_fallo(tmp_path):
    """Plantillas, lo que ignora git, las formas cortas del proyecto y lo que la skill lleva dentro.

    En una skill del dueño, que puede citar su arnés: las rutas se comprueban igual en todas las skills.
    """
    raiz = _repo(tmp_path)
    _escribe(raiz / ".claude" / "skills" / "audit-proyecto" / "scripts" / "propio.py", "")
    _skill(
        raiz,
        "`canales/<id>/perfil.json`, `progress/gate1_<canal>.md`, `datos/voz-<x>.json`, `doc/auditoria-AAAA-MM-DD.md`\n"
        "`canales/C102-b/videos/run/final.mp4`, `progress/gate1_v1.html`, `scripts/grabacion.wav`\n"
        "`doc/07 §A.9`, `lib/modulo.VALOR`, `scripts/propio.py`, `workflows/archivo/` no existe\n",
        nombre="audit-proyecto",
    )
    assert comprueba(raiz, FORMATOS) == []


def test_la_ruta_que_ignora_git_cuenta_solo_si_el_gitignore_la_ignora(tmp_path):
    """Control de la anterior: sin su línea en el `.gitignore`, la misma página sí es un fallo."""
    raiz = _repo(tmp_path)
    _escribe(raiz / ".gitignore", "canales/*/videos/\n")
    _skill(raiz, "`progress/gate1_v1.html`\n", nombre="audit-proyecto")
    assert comprueba(raiz, FORMATOS) == ["audit-proyecto/SKILL.md:2: cita progress/gate1_v1.html y no existe"]


def test_caza_que_una_skill_publica_cite_el_arnes_del_dueno(tmp_path):
    """Las cuatro cosas del arnés, en una skill que viaja: una por hallazgo, y ninguna ruta muerta de más."""
    raiz = _repo(tmp_path)
    _skill(raiz, CITA_EL_ARNES)
    sufijo = (
        ", que es del arnés del dueño y no viaja al repositorio público: dilo en palabras, o cita docs/ o el código"
    )
    assert comprueba(raiz, FORMATOS) == [
        f"produce-semana/SKILL.md:2: cita {que}{sufijo}"
        for que in ("doc/", "progress/", "CHECKPOINTS.md", "una fila del addendum")
    ]


def test_control_una_skill_del_dueno_puede_citar_su_arnes(tmp_path):
    """La misma línea en `audit-proyecto`, que la lista blanca deja fuera, no es un fallo."""
    raiz = _repo(tmp_path)
    _skill(raiz, CITA_EL_ARNES, nombre="audit-proyecto")
    assert comprueba(raiz, FORMATOS) == []


def test_sin_lista_blanca_todas_las_skills_viajan(tmp_path):
    """El repositorio público no lleva la lista: allí todas sus skills son públicas, y la del dueño también se mira."""
    raiz = _repo(tmp_path)
    (raiz / "exportacion" / "lista-blanca.txt").unlink()
    _skill(raiz, CITA_EL_ARNES, nombre="audit-proyecto")
    assert len(comprueba(raiz, FORMATOS)) == 4


def test_docs_y_las_palabras_parecidas_no_son_el_arnes(tmp_path):
    """`docs/` es la documentación pública; una fila de botones o una URL con /doc/ no citan el addendum ni doc/."""
    raiz = _repo(tmp_path)
    _escribe(raiz / "docs" / "scene-script.md", "guía\n")
    _skill(raiz, "Lee `docs/scene-script.md`: una fila de botones, https://ejemplo.org/doc/x y las filas.\n")
    assert comprueba(raiz, FORMATOS) == []


def test_el_repositorio_real_esta_al_dia():
    """La guarda sobre el repositorio de verdad. Si falla, el mensaje dice qué skill retocar (con skill-creator)."""
    assert comprueba() == []
