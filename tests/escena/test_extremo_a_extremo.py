"""De extremo a extremo, sin GPU: un episodio escrito con el lenguaje de escena llega al motor tal como se escribió.

Criterio 7 del encargo de F6.2b: un guion de prueba escrito con el lenguaje (`guion_de_prueba`) → `Guion.datos()`
→ `compone` → `motor/motor.js` en Node da estados coherentes:

- **los actores están donde dice Python**: `lib/escena/encuadre.Geometria` (lo que usan las comprobaciones) y el
  motor dan la misma posición y la misma cámara en todos los instantes, así que lo que se comprueba es lo que
  se pinta;
- **el karaoke enciende la palabra que suena**: en mitad de cada palabra del guion brilla esa y ninguna otra;
- **quien habla rebota mientras suena su frase** y no fuera de ella.

Cada una lleva su control negativo: un GUION tocado a propósito tiene que hacer fallar la comparación.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from utiles_escena import CSS_PRUEBA, LAMINAS_PRUEBA, crea_run, escena_prueba, guion_de_prueba, guion_min, node

from lib.escena import compone, comprobaciones, encuadre
from lib.escena.encuadre import Geometria
from lib.escena.linea_tiempo import LineaDeTiempo

AQUI = Path(__file__).parent
NODE = node()
pytestmark = pytest.mark.skipif(NODE is None, reason="no hay node en esta máquina (lo instala fnm, ver .node-version)")


@pytest.fixture(scope="module")
def episodio(tmp_path_factory, assets_min):
    """La línea de tiempo, el GUION del lenguaje (con sus correcciones) y el que quedó dentro de la composición."""
    tmp = tmp_path_factory.mktemp("episodio")
    linea = LineaDeTiempo.del_run(crea_run(tmp / "run", LAMINAS_PRUEBA), escena=escena_prueba(), idioma="en")
    datos = guion_de_prueba(linea).datos()
    corregidos = encuadre.corrige(datos)
    apartados = encuadre.aparta_de_caras(datos, franja_inferior_y=860)
    index = compone.compone(datos, assets_min, CSS_PRUEBA, tmp / "comp")
    return {
        "linea": linea,
        "datos": datos,
        "pagina": compone.lee_guion(index),
        "correcciones": (corregidos, apartados),
        "tmp": tmp,
    }


def _consulta(guion: dict, consultas: list[dict], carpeta: Path) -> list:
    (carpeta / "guion.json").write_text(json.dumps(guion), encoding="utf-8")
    (carpeta / "consultas.json").write_text(json.dumps(consultas), encoding="utf-8")
    r = subprocess.run(
        [NODE, str(AQUI / "consulta.cjs"), str(carpeta / "guion.json"), str(carpeta / "consultas.json")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _instantes(p: dict, paso: float = 0.25) -> list[float]:
    n = max(1, int((p["t1"] - p["t0"]) / paso))
    return [round(p["t0"] + i * paso, 4) for i in range(n)]


# ------------------------------------------------------------------ el episodio de prueba es bueno
def test_el_episodio_de_prueba_pasa_las_seis_comprobaciones_sin_correcciones(episodio):
    """Si el episodio de referencia no pasara, los controles negativos de abajo no distinguirían nada."""
    assert episodio["correcciones"] == ([], [])
    defectos = comprobaciones.todas(episodio["datos"], episodio["linea"])
    assert set(defectos) == {
        "cabezas_en_cuadro",
        "textos_fuera_de_las_caras",
        "pies_en_el_suelo",
        "escala_de_cabeza",
        "karaoke",
        "duracion",
    }
    assert all(v == [] for v in defectos.values()), {k: [str(d) for d in v] for k, v in defectos.items() if v}


def test_la_composicion_lleva_lo_que_el_lenguaje_escribio(episodio):
    g = episodio["pagina"]
    assert g["duracion"] == pytest.approx(episodio["linea"].total)
    assert g["movimiento"] == escena_prueba()["movimiento"]
    assert [k["id"] for k in g["karaoke"]] == [k["id"] for k in episodio["datos"]["karaoke"]]
    assert set(g["habla"]) == {"ana", "bo"}
    # El html de los elementos no va en el JSON de la página, pero sí sus clases en el DOM.
    assert all("html" not in e for e in g["elementos"])


# ------------------------------------------------------------------ actores en su sitio
def _consultas_de_sitio(datos: dict) -> list[dict]:
    q = []
    for p in datos["planos"]:
        for t in _instantes(p):
            q.append({"tipo": "camara", "plano": p["id"], "t": t})
            q += [{"tipo": "mundo", "id": a["id"], "t": t} for a in p["actores"]]
    return q


def _discrepancias(datos: dict, respuestas: list, consultas: list[dict]) -> int:
    geo = Geometria(datos)
    malas = 0
    for q, r in zip(consultas, respuestas):
        if q["tipo"] == "camara":
            x, y, s = geo.camara(q["plano"], q["t"])
            esperado = {"tx": geo.MW / 2 - x * s, "ty": geo.MH / 2 - y * s, "s": s}
        else:
            esperado = geo.mundo(q["id"], q["t"])
        malas += any(abs(r[c] - v) > 1e-6 for c, v in esperado.items())
    return malas


def test_los_actores_y_la_camara_estan_donde_dice_python(episodio):
    consultas = _consultas_de_sitio(episodio["datos"])
    respuestas = _consulta(episodio["pagina"], consultas, episodio["tmp"])
    assert len(consultas) > 200  # dos planos, tres actores y la cámara, cada 0,25 s
    assert _discrepancias(episodio["datos"], respuestas, consultas) == 0
    # Y en su sitio de verdad: Ana, que anda hasta x = 1000, ha llegado cuando acaba su clave.
    ana = episodio["datos"]["planos"][0]["actores"][0]
    llegada = ana["pista"][1]["t"] + ana["pista"][1]["tr"] + 0.01
    assert _consulta(episodio["pagina"], [{"tipo": "mundo", "id": ana["id"], "t": llegada}], episodio["tmp"])[0][
        "x"
    ] == pytest.approx(1000)


def test_control_un_actor_movido_en_la_pagina_lo_ve_la_comparacion(episodio):
    """Si la página no fuera lo que calcula Python, la comparación tiene que verlo: se mueve una clave 50 px."""
    tocada = json.loads(json.dumps(episodio["pagina"]))
    tocada["planos"][0]["actores"][0]["pista"][1]["x"] += 50
    consultas = _consultas_de_sitio(episodio["datos"])
    respuestas = _consulta(tocada, consultas, episodio["tmp"])
    assert _discrepancias(episodio["datos"], respuestas, consultas) > 0


# ------------------------------------------------------------------ karaoke
def _palabras_que_brillan(guion: dict, linea, carpeta: Path) -> list[tuple]:
    """En mitad de cada palabra: (la que suena, los textos que brillan > 0,5, cuánto se ve su grupo, dónde brillan, y
    la posición de cada palabra del karaoke)."""
    medios = [(p.ini + p.fin) / 2 for p in linea.palabras]
    respuestas = _consulta(guion, [{"tipo": "karaoke", "t": t} for t in medios], carpeta)
    posiciones = [(g["id"], n) for g in guion["karaoke"] for n in range(len(g["w"]))]
    textos = {(g["id"], n): w[2] for g in guion["karaoke"] for n, w in enumerate(g["w"])}
    salida = []
    for p, grupos in zip(linea.palabras, respuestas):
        brillan = [(g["id"], n) for g in grupos for n, b in enumerate(g["brillo"]) if b > 0.5]
        visible = max((g["visible"] for g in grupos if any(b > 0.5 for b in g["brillo"])), default=0)
        salida.append((p.texto, [textos[x] for x in brillan], visible, brillan, posiciones))
    return salida


def test_el_karaoke_enciende_la_palabra_que_suena(episodio):
    linea = episodio["linea"]
    resultado = _palabras_que_brillan(episodio["pagina"], linea, episodio["tmp"])
    assert len(resultado) == len(linea.palabras) == 43
    for i, (suena, brillan, visible, posicion, posiciones) in enumerate(resultado):
        assert brillan == [suena], f"en mitad de «{suena}» brillan {brillan}"
        assert posicion == [posiciones[i]], "brilla una palabra con el mismo texto, pero no la que suena"
        assert visible > 0, f"«{suena}» brilla en un grupo que no se ve"


def test_control_un_karaoke_desfasado_enciende_otra_palabra(episodio):
    """Si los tiempos del karaoke fueran una palabra por detrás de la voz, la prueba de arriba tiene que fallar."""
    tocada = json.loads(json.dumps(episodio["pagina"]))
    for g in tocada["karaoke"]:
        for w in g["w"]:
            w[0], w[1] = w[0] + 0.4, w[1] + 0.4
    resultado = _palabras_que_brillan(tocada, episodio["linea"], episodio["tmp"])
    assert sum(pos != [posiciones[i]] for i, (_, _, _, pos, posiciones) in enumerate(resultado)) > 30


# ------------------------------------------------------------------ habla
def _rebote(guion: dict, aid: str, tiempos: list[float], carpeta: Path) -> list[float]:
    """Lo que el motor sube a un actor sobre su sitio (y del actor menos y del mundo): el rebote al hablar."""
    consultas = [{"tipo": q, "id": aid, "t": t} for t in tiempos for q in ("actor", "mundo")]
    r = _consulta(guion, consultas, carpeta)
    return [r[2 * i + 1]["y"] - r[2 * i]["y"] for i in range(len(tiempos))]


def test_quien_habla_rebota_mientras_suena_su_frase_y_no_fuera(episodio):
    habla = episodio["pagina"]["habla"]["ana"]
    assert len(habla) == 1  # su cita entera, «Look at the kite, it is so big!», en un tramo
    ana = episodio["datos"]["planos"][0]["actores"][0]["id"]
    tramo = habla[0]
    dentro = [round(tramo["t"] + 0.2 + i * 0.1, 3) for i in range(int((tramo["t1"] - tramo["t"] - 0.4) / 0.1))]
    fuera = [round(tramo["t"] - 1.5 + i * 0.1, 3) for i in range(12)]  # quieta y callada: ya ha llegado andando
    assert max(_rebote(episodio["pagina"], ana, dentro, episodio["tmp"])) > 3
    assert _rebote(episodio["pagina"], ana, fuera, episodio["tmp"]) == [0.0] * len(fuera)


def test_control_sin_habla_no_rebota(episodio):
    tocada = json.loads(json.dumps(episodio["pagina"]))
    tocada["habla"] = {}
    tramo = episodio["pagina"]["habla"]["ana"][0]
    dentro = [round(tramo["t"] + 0.2 + i * 0.1, 3) for i in range(20)]
    ana = episodio["datos"]["planos"][0]["actores"][0]["id"]
    assert _rebote(tocada, ana, dentro, episodio["tmp"]) == [0.0] * len(dentro)


def test_la_geometria_de_python_es_la_del_motor_tambien_con_padres_y_camara_que_sigue(tmp_path):
    """El GUION mínimo de F6.2a varía lo que el episodio de prueba no: un actor hijo de otro (la rueda del a1), una
    cámara que sigue a un actor, la curva «suave», un volteo y un plano que entra con fundido."""
    g = guion_min()
    consultas = _consultas_de_sitio(g)
    assert {q["id"] for q in consultas if q["tipo"] == "mundo"} == {"a1", "a2", "a3"}
    assert _discrepancias(g, _consulta(g, consultas, tmp_path), consultas) == 0
