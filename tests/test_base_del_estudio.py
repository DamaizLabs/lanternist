"""La frontera entre lo que comparten todos los canales y lo que es de cada uno.

**La regla del 16-09-2026**: «el primer canal no tiene que ser referente de ningún canal ni del
estudio… hemos de aislar cada canal con sus métricas y sus configuraciones, y solo compartirán
configuración lo que se establezca como base para todos los canales, como no usar Kaggle ni aplicar
cinemagraph».

`datos/base-del-estudio.json` es esa base, y este fichero la hace cumplir por los dos lados:

- **Ningún canal puede contradecirla.** El cinemagraph y Kaggle, los dos que se nombraron al dar la
  regla, salieron del estudio con su código en F6.7, y con ellos su clave del perfil: un perfil que
  la vuelva a escribir no es una excepción, es una incoherencia, y se ve aquí y no en el vídeo.
- **La base no puede convertirse en un cajón.** Lo que entra tiene que ser una decisión con fecha y
  cita, no «lo que hoy coincide en los dos canales»: que los dos narren en inglés es casualidad de
  sus nichos, y escribirlo como base le complicaría la vida al primer canal en español.
"""

import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
BASE = json.loads((RAIZ / "datos" / "base-del-estudio.json").read_text(encoding="utf-8"))
PERFILES = sorted((RAIZ / "canales").glob("*/perfil.json"))


def perfil_de(ruta: Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


# Las claves del perfil que eran del motor de láminas y salieron con él en F6.7 (02-10-2026). Volver a escribirlas en un
# perfil sería declarar algo que ningún código lee: el cinemagraph de Kaggle, las transiciones que tachaba el montaje
# (las del formato «láminas» van en `escena.laminas`) y el banner que componía `lib/cta.py`.
RETIRADAS_DE_FORMATO = ("cinemagraph", "transiciones_excluidas")
RETIRADAS_DE_COMPOSICION = ("cta_suscripcion",)


@pytest.mark.parametrize("ruta", PERFILES, ids=lambda p: p.parent.name)
def test_ningun_canal_vuelve_a_declarar_lo_que_salio_con_el_motor_de_laminas(ruta: Path):
    """Lo que la base decidió quitar —el cinemagraph, que se nombró al dar la regla— no vuelve por un perfil."""
    formato = perfil_de(ruta).get("formato") or {}
    vueltas = [f"formato.{k}" for k in RETIRADAS_DE_FORMATO if k in formato]
    vueltas += [f"formato.composicion.{k}" for k in RETIRADAS_DE_COMPOSICION if k in (formato.get("composicion") or {})]
    assert not vueltas, (
        f"{ruta.parent.name} vuelve a declarar {vueltas}, que salieron con el motor de láminas en F6.7: ningún código "
        "las lee. Si de verdad vuelven, la decisión es del usuario y va primero a datos/base-del-estudio.json."
    )
    assert "cinemagraph" not in BASE["produccion"] and "usa_kaggle" not in BASE["produccion"]


def test_control_la_comprobacion_ve_una_clave_retirada():
    """Control negativo: el perfil de antes de F6.7 tiene que dar fallo."""
    viejo = {"formato": {"cinemagraph": "no", "transiciones_excluidas": [], "composicion": {"cta_suscripcion": {}}}}
    formato = viejo["formato"]
    assert [k for k in RETIRADAS_DE_FORMATO if k in formato] == ["cinemagraph", "transiciones_excluidas"]
    assert [k for k in RETIRADAS_DE_COMPOSICION if k in formato["composicion"]] == ["cta_suscripcion"]


@pytest.mark.parametrize("ruta", PERFILES, ids=lambda p: p.parent.name)
def test_ningun_canal_declara_el_motor_de_voz(ruta: Path):
    """El motor es del estudio (decisión 13). Un canal elige la voz, nunca quién clona.

    `tests/test_capas.py` ya lo impide en `lib/config.py`; aquí se mira desde el otro lado, que es
    donde lo escribiría alguien: en el perfil del canal.
    """
    voz = perfil_de(ruta).get("voz") or {}
    assert "motor" not in voz and "modelo" not in voz, (
        f"{ruta.parent.name} declara el motor de voz en su perfil, y eso es del estudio "
        f"(`datos/base-del-estudio.json → produccion.motor_de_voz`): {sorted(voz)}"
    )


def test_la_base_no_recoge_coincidencias_entre_los_canales_de_hoy():
    """Lo que está en la base tiene que ser una decisión, no un empate.

    El riesgo de un fichero así es que se llene con «lo que hoy vale igual en los dos», y entonces
    deja de ser una frontera y pasa a ser una foto de los dos primeros canales — justo el referente que la regla
    quiere quitar. Estas son coincidencias de canal, y ninguna debe estar:

    - el **idioma**: los dos narran en inglés por sus nichos, no por una regla;
    - los **capítulos**: los dos los llevaban, uno de ellos desde hacía un día;
    - que lleven **subtítulos** o **música** (`activos`/`activa`): es del formato de cada canal.

    Lo que SÍ está desde el 25-09-2026 —`produccion.karaoke` y `produccion.lecho_musical`— no es una
    coincidencia: son el motor y el listón técnico, decididos para todos (fila 196).
    """
    plano = json.dumps(BASE, ensure_ascii=False)
    for coincidencia in ("narracion", "idioma", "capitulos", "subtitulos", "activos", "activa"):
        assert f'"{coincidencia}"' not in plano, (
            f"la base del estudio declara «{coincidencia}», que hoy coincide en los dos canales pero "
            "no es una decisión del estudio: es de cada canal y va en su perfil."
        )


# --- El kill switch salió de la fábrica (OC1.4) --------------------------------------------------------------------
# Era la regla con la que se autorizó el estudio de vídeo del que nace este motor: umbrales de retención y CTR sobre una
# cohorte de cinco vídeos y un plazo de 90 días. No es una regla del motor, y quien use Lanternist decide qué hace con
# sus métricas (`progress/deudas-del-motor.md`, punto 17). Si vuelve por la base, por un perfil o por el código que
# los lee, se ve aquí.
CLAVES_DEL_KILL_SWITCH = ("kill_switch", "cohorte_y_kill_switch", "fecha_kill_switch", "suelo_de_vistas")
QUIEN_LO_LEIA = ("metricas.py", "scripts/comprueba_canal.py", "lib/config.py")


def _restos_del_kill_switch(base: dict, perfiles: dict[str, dict], codigo: dict[str, str]) -> list[str]:
    restos = [f"datos/base-del-estudio.json: {k}" for k in CLAVES_DEL_KILL_SWITCH if k in base]
    restos += [f"{nombre}: {k}" for nombre, perfil in perfiles.items() for k in CLAVES_DEL_KILL_SWITCH if k in perfil]
    restos += [f"{ruta}: {k}" for ruta, texto in codigo.items() for k in CLAVES_DEL_KILL_SWITCH if f'"{k}"' in texto]
    return restos


def test_el_kill_switch_no_vuelve_a_la_fabrica():
    perfiles = {r.parent.name: perfil_de(r) for r in PERFILES}
    codigo = {ruta: (RAIZ / ruta).read_text(encoding="utf-8") for ruta in QUIEN_LO_LEIA}
    assert _restos_del_kill_switch(BASE, perfiles, codigo) == []


def test_control_el_kill_switch_de_antes_de_OC1_4_se_caza():
    """Control negativo: la base, el perfil y la lectura de `metricas.py` de antes de OC1.4 dan los tres fallo."""
    base = {"kill_switch": {"plazo_dias": 90}}
    perfil = {"cohorte_y_kill_switch": {"fecha_primer_video": None}}
    codigo = {"metricas.py": 'SUELO = base_del_estudio()["kill_switch"]["suelo_de_vistas"]'}
    assert _restos_del_kill_switch(base, {"viejo": perfil}, codigo) == [
        "datos/base-del-estudio.json: kill_switch",
        "viejo: cohorte_y_kill_switch",
        "metricas.py: kill_switch",
        "metricas.py: suelo_de_vistas",
    ]
