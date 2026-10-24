"""`motor/motor.js` es determinista y lee del GUION lo que antes llevaba fijo (F6.2a).

Criterio de F6.2a: «motor.js determinista en Node: el mismo t da el mismo estado». Se comprueba recorriendo
todos los fotogramas del GUION mínimo en tres órdenes y con motores nuevos y reutilizados
(`determinismo.cjs`). Cada prueba lleva su control: un motor que depende de su historia sale distinto, y
un motor con el umbral de video_1 escrito a mano no hace girar la rueda a otros fps.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from utiles_escena import GUION_MIN, node

AQUI = Path(__file__).parent
MOTOR = AQUI.parents[1] / "motor" / "motor.js"
NODE = node()
pytestmark = pytest.mark.skipif(NODE is None, reason="no hay node en esta máquina (lo instala fnm, ver .node-version)")


def _corre(script: str, *args: str) -> dict:
    r = subprocess.run([NODE, str(AQUI / script), *args], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _evalua(codigo: str) -> dict:
    """Ejecuta `codigo` en Node con `Motor` y `G` (el GUION mínimo) ya cargados; imprime lo que devuelva."""
    prologo = (
        f"const Motor = require({json.dumps(str(MOTOR))});"
        f"const G = JSON.parse(require('node:fs').readFileSync({json.dumps(str(GUION_MIN))}, 'utf8'));"
    )
    r = subprocess.run(
        [NODE, "-e", prologo + f"process.stdout.write(JSON.stringify((() => {{ {codigo} }})()));"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_el_mismo_t_da_el_mismo_estado_en_cualquier_orden():
    d = _corre("determinismo.cjs", str(GUION_MIN))
    assert d["fotogramas"] == 37  # 1,5 s a 24 fps, del 0 al 36
    assert d["distintos_al_reves"] == 0
    assert d["distintos_barajado"] == 0
    assert d["distintos_mismo_motor_otra_vez"] == 0
    # Y la escena se mueve en todos: si los estados fueran iguales, «0 distintos» no probaría nada.
    assert d["estados_diferentes_en_el_tiempo"] == d["fotogramas"]


def test_control_un_motor_que_depende_de_su_historia_sale_distinto():
    d = _corre("determinismo.cjs", str(GUION_MIN), "--mutante")
    assert d["distintos_al_reves"] > 0
    assert d["distintos_barajado"] > 0
    assert d["distintos_mismo_motor_otra_vez"] > 0


def test_el_paso_de_integracion_sale_de_los_fps_del_guion():
    """750 px rodados con una rueda de radio 50 son 15 rad (859,4°), a 12, 24 o 48 fps."""
    esperado = 750 / 50 * 180 / 3.141592653589793
    for fps in ("12", "24", "48"):
        giro = _corre("paso.cjs", str(GUION_MIN), fps)["giro"]
        assert giro == pytest.approx(esperado, rel=0.01), f"a {fps} fps la rueda giró {giro:.1f}°"


def test_control_con_el_umbral_de_video_1_fijo_la_rueda_no_gira_a_12_fps():
    giro = _corre("paso.cjs", str(GUION_MIN), "12", "--salto-fijo")["giro"]
    assert giro < 0.5 * (750 / 50 * 180 / 3.141592653589793), giro


@pytest.mark.parametrize("clave", ["fps", "marco", "fundido", "camara_en_mano", "movimiento", "planos"])
def test_sin_una_decision_del_guion_el_motor_para_y_dice_cual(clave):
    d = _evalua(
        f"delete G[{json.dumps(clave)}]; try {{ Motor.crea(G); return {{ lanza: false }}; }} "
        "catch (e) { return { lanza: true, mensaje: e.message }; }"
    )
    assert d["lanza"], f"sin «{clave}» el motor arrancó igual: tendría un defecto escondido"
    assert f"«{clave}»" in d["mensaje"]


def test_la_camara_en_mano_la_decide_el_guion():
    """Con 0 la cámara está donde dicen sus claves; con 1 se mueve (el control de que el mando llega)."""
    d = _evalua(
        "const quieta = Motor.crea({ ...G, camara_en_mano: 0 }).camara(G.planos[0], 0.8);"
        "const en_mano = Motor.crea({ ...G, camara_en_mano: 1 }).camara(G.planos[0], 0.8);"
        "return { quieta, en_mano };"
    )
    # En t=0,8 la clave 2 del plano 1 ya ha llegado: centro (1300, 700), z 1,3; el fondo mide 2400 de ancho.
    s = 1920 / 2400 * 1.3
    assert d["quieta"]["s"] == pytest.approx(s)
    assert d["quieta"]["tx"] == pytest.approx(960 - 1300 * s)
    assert d["quieta"]["ty"] == pytest.approx(540 - 700 * s)
    assert d["en_mano"]["tx"] != pytest.approx(d["quieta"]["tx"], abs=0.5)


@pytest.mark.parametrize(
    ("cambio", "nombre"),
    [
        ("G.rig.piezas.cuerpo.tipo = 'perro';", "«perro»"),
        ("G.planos[0].actores[0].eventos[0].tipo = 'baile';", "«baile»"),
    ],
)
def test_un_tipo_desconocido_no_se_ignora_en_silencio(cambio, nombre):
    """Auditoría de F6.2a, recomendación 4: antes la pieza salía rígida y el evento no hacía nada."""
    d = _evalua(
        f"{cambio} try {{ Motor.crea(G); return {{ lanza: false }}; }} "
        "catch (e) { return { lanza: true, mensaje: e.message }; }"
    )
    assert d["lanza"] and nombre in d["mensaje"]


def test_control_con_los_tipos_conocidos_el_motor_arranca():
    assert _evalua("Motor.crea(G); return { ok: true };") == {"ok": True}


def test_compone_y_el_motor_conocen_los_mismos_tipos():
    """compone.py los comprueba antes de escribir y motor.js al arrancar: si divergen, uno de los dos miente."""
    from lib.escena import compone

    d = _evalua("return { malla: Motor.TIPOS_DE_MALLA, evento: Motor.TIPOS_DE_EVENTO };")
    assert tuple(d["malla"]) == compone.TIPOS_DE_MALLA
    assert tuple(d["evento"]) == compone.TIPOS_DE_EVENTO


# ------------------------------------------------------------------ F6.2b: el movimiento lo declara el GUION
# Auditoría de F6.2a, recomendación 5: lo que rebota quien habla, la respiración, el balanceo y la amplitud de cada
# evento salían de calibrar a los personajes de video_1 y eran la decisión de un canal heredada en silencio.
@pytest.mark.parametrize("ruta", ["anda.v", "habla.rebote", "respira.periodo", "eventos.menea.f", "elementos.campana"])
def test_sin_una_magnitud_del_movimiento_el_motor_para_y_dice_cual(ruta):
    *camino, ultima = ruta.split(".")
    acceso = "G.movimiento" + "".join(f"[{json.dumps(p)}]" for p in camino)
    d = _evalua(
        f"delete {acceso}[{json.dumps(ultima)}]; try {{ Motor.crea(G); return {{ lanza: false }}; }} "
        "catch (e) { return { lanza: true, mensaje: e.message }; }"
    )
    assert d["lanza"] and f"«{ruta}»" in d["mensaje"]


def test_compone_y_el_motor_piden_el_mismo_movimiento_y_conocen_los_mismos_nombres():
    from lib.escena import compone

    d = _evalua(
        "return { mv: Object.keys(Motor.MOVIMIENTO), entradas: Motor.ENTRADAS, salidas: Motor.SALIDAS, "
        "bucles: Motor.BUCLES, planos: Motor.ENTRADAS_DE_PLANO };"
    )
    assert tuple(d["mv"]) == compone.MOVIMIENTO
    assert (tuple(d["entradas"]), tuple(d["salidas"]), tuple(d["bucles"]), tuple(d["planos"])) == (
        compone.ENTRADAS,
        compone.SALIDAS,
        compone.BUCLES,
        compone.ENTRADAS_DE_PLANO,
    )


@pytest.mark.parametrize(
    ("cambio", "nombre"),
    [
        ("G.elementos[0].entra = 'zoom';", "«zoom»"),
        ("G.elementos[0].sale = 'explota';", "«explota»"),
        ("G.elementos[0].bucle = 'baila';", "«baila»"),
        ("G.planos[1].entra.tipo = 'cortinilla';", "«cortinilla»"),
        ("delete G.rig.piezas.cuerpo.cola_amp;", "cola_amp"),
    ],
)
def test_un_nombre_desconocido_de_elemento_o_de_plano_no_cae_en_el_caso_por_omision(cambio, nombre):
    d = _evalua(
        f"{cambio} try {{ Motor.crea(G); return {{ lanza: false }}; }} "
        "catch (e) { return { lanza: true, mensaje: e.message }; }"
    )
    assert d["lanza"] and nombre in d["mensaje"]


def test_las_magnitudes_del_guion_llegan_al_movimiento_y_el_actor_puede_sobrescribirlas():
    """Control: con otro rebote al hablar, el actor que habla sube distinto; con su rasgo `charla`, manda el suyo."""
    d = _evalua(
        "const rebote = (G2, t) => { const M = Motor.crea(G2); return M.mundo('a3', t).y - M.actor('a3', t).y; };"
        "const t = 1.2;"  # a3 habla de 1,0 a 1,4 (G.habla.voz2)
        "const base = rebote(G, t);"
        "const MV = G.movimiento;"
        "const doble = rebote({ ...G, movimiento: { ...MV, habla: { ...MV.habla, rebote: 14 } } }, t);"
        "const G3 = JSON.parse(JSON.stringify(G)); G3.planos[1].actores[0].rasgos.charla = 0;"
        "return { base, doble, propio: rebote(G3, t) };"
    )
    assert d["base"] != 0
    assert d["doble"] - d["base"] == pytest.approx(d["base"] - _evalua_risa_sin_rebote())
    assert d["propio"] == pytest.approx(_evalua_risa_sin_rebote())


def _evalua_risa_sin_rebote() -> float:
    """Lo que sube a3 en t = 1,2 solo por su risa (sin rebote al hablar): la parte que no depende de `charla`."""
    return _evalua(
        "const G3 = JSON.parse(JSON.stringify(G)); G3.habla = {};"
        "const M = Motor.crea(G3); return M.mundo('a3', 1.2).y - M.actor('a3', 1.2).y;"
    )


# ------------------------------------------------------------------ auditoría de F6.2b, recomendación 1
# Con `??` un 0 ya no cae en el valor por omisión, y seis magnitudes del movimiento (más `anda.v`) dividen: con 0,
# `Motor.elemento(...).o` y `Motor.actor(...).y` salían NaN, y `clamp` no filtra NaN.
def _crea_con(cambio: str) -> dict:
    return _evalua(
        f"{cambio} try {{ const M = Motor.crea(G); "
        "return { lanza: false, o: M.elemento(G.elementos[0], 0.2).o, y: M.actor('a1', 0.4).y }; } "
        "catch (e) { return { lanza: true, mensaje: e.message }; }"
    )


@pytest.mark.parametrize("ruta", ["anda.v", "habla.sube", "habla.baja", "respira.periodo", "elementos.entra",
                                  "elementos.trazo", "elementos.campana"])  # fmt: skip
def test_una_magnitud_que_divide_a_cero_la_rechaza_el_motor(ruta):
    *camino, ultima = ruta.split(".")
    acceso = "G.movimiento" + "".join(f"[{json.dumps(p)}]" for p in camino) + f"[{json.dumps(ultima)}]"
    d = _crea_con(f"{acceso} = 0;")
    assert d["lanza"] and f"«{ruta}»" in d["mensaje"] and "mayores que 0" in d["mensaje"]
    # Control: con un valor positivo, por pequeño que sea, arranca y todo sale finito.
    bueno = _crea_con(f"{acceso} = 0.001;")
    assert not bueno["lanza"] and all(isinstance(v, (int, float)) for v in (bueno["o"], bueno["y"]))


@pytest.mark.parametrize(
    ("cambio", "nombre"),
    [
        ("G.planos[0].actores[0].rasgos.v_anda = 0;", "v_anda"),
        ("G.elementos[0].di = 0;", "di"),
        ("G.elementos[1].trazo_d = 0;", "trazo_d"),
        ("G.elementos[0].campana = true; G.elementos[0].campana_p = 0;", "campana_p"),
    ],
)
def test_lo_que_un_actor_o_un_elemento_sobrescribe_tampoco_puede_ser_cero(cambio, nombre):
    d = _crea_con(cambio)
    assert d["lanza"] and nombre in d["mensaje"]
    assert not _crea_con(cambio.replace("= 0;", "= 0.5;"))["lanza"]


def test_compone_y_el_motor_conocen_los_mismos_divisores():
    from lib.escena import compone

    d = _evalua("return [Motor.DIVISORES, Motor.RASGOS_DIVISORES, Motor.CAMPOS_DIVISORES_DE_ELEMENTO];")
    assert [tuple(x) for x in d] == [compone.DIVISORES, compone.RASGOS_DIVISORES, compone.CAMPOS_DIVISORES_DE_ELEMENTO]


# ------------------------------------------------------------------ F6.8: las entradas de tinta del motor de láminas
# Las transiciones de `lib/motion.py → TRANSITIONS` (el xfade de FFmpeg), portadas como entradas de plano. Cada una con
# su dirección cuando la pide, y lo que el motor calcula se compara con la fórmula escrita aquí en Python.
ENTRADAS_DE_TINTA = [
    ("cortina", "derecha"),
    ("cortina", "izquierda"),
    ("cortina", "arriba"),
    ("mancha", None),
    ("calado", None),
    ("viento", "derecha"),
    ("viento", "izquierda"),
    ("papel", None),
]


def _con_entrada(tmp_path: Path, tipo: str, direccion: str | None, d: float = 0.5) -> Path:
    """El GUION mínimo con el plano 2 entrando con `tipo` durante `d` s (su t0 es 0,9)."""
    g = json.loads(GUION_MIN.read_text(encoding="utf-8"))
    g["planos"][1]["entra"] = {"tipo": tipo, "d": d, **({"dir": direccion} if direccion else {})}
    ruta = tmp_path / f"guion-{tipo}-{direccion}.json"
    ruta.write_text(json.dumps(g), encoding="utf-8")
    return ruta


@pytest.mark.parametrize(("tipo", "direccion"), ENTRADAS_DE_TINTA)
def test_cada_entrada_de_tinta_es_determinista(tmp_path, tipo, direccion):
    d = _corre("determinismo.cjs", str(_con_entrada(tmp_path, tipo, direccion)))
    assert (d["distintos_al_reves"], d["distintos_barajado"], d["distintos_mismo_motor_otra_vez"]) == (0, 0, 0)
    assert d["estados_diferentes_en_el_tiempo"] == d["fotogramas"]


@pytest.mark.parametrize(("tipo", "direccion"), ENTRADAS_DE_TINTA)
def test_control_cada_entrada_de_tinta_con_un_motor_que_depende_de_su_historia_sale_distinta(tmp_path, tipo, direccion):
    d = _corre("determinismo.cjs", str(_con_entrada(tmp_path, tipo, direccion)), "--mutante")
    assert d["distintos_al_reves"] > 0 and d["distintos_barajado"] > 0


def _entradas(tmp_path: Path, tipo: str, direccion: str | None, us: list[float]) -> list[dict]:
    """`Motor.entradaPlano` del plano 2 en cada progreso u (la entrada dura 0,5 s desde t0 = 0,9)."""
    ruta = _con_entrada(tmp_path, tipo, direccion)
    codigo = (
        f"const G2 = JSON.parse(require('node:fs').readFileSync({json.dumps(str(ruta))}, 'utf8'));"
        "const M = Motor.crea(G2), p = G2.planos[1];"
        f"return {json.dumps(us)}.map((u) => M.entradaPlano(p, p.t0 + u * p.entra.d));"
    )
    return _evalua(codigo)


def _suave(p: float) -> float:
    return p * p * (3 - 2 * p)


# La forma de cada umbral, escrita aquí de nuevo desde su definición (lib/motion.py y el xfade de FFmpeg): alfa =
# clamp(pendiente·F + corte), y en motor.js la calcula su propio código.
UMBRAL_ESPERADO = {
    "mancha": lambda u: (-1 / 0.18, (u * 1.2 - 0.1) / 0.18 + 0.5),
    "calado": lambda u: (-1 / 0.025, (u * 1.05 - 0.025) / 0.025),
    "viento": lambda u: (-1 / 0.2, u * 1.2 / 0.2),
}
# El último, pasado el final (el motor lo recorta a 1): justo en t0 + d, la suma en coma flotante deja u en 0,99999….
US = [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.999, 1.05]


@pytest.mark.parametrize(("tipo", "direccion"), [("mancha", None), ("calado", None), ("viento", "derecha")])
def test_el_umbral_de_cada_entrada_es_el_de_su_formula(tmp_path, tipo, direccion):
    for u, e in zip(US, _entradas(tmp_path, tipo, direccion, US)):
        assert (e["op"], e["x"], e["iris"], e["cortina"], e["papel"]) == (1, 0, None, None, None)
        if u > 1:
            assert e["umbral"] is None, "cuando ha entrado, el plano va sin máscara"
            continue
        pendiente, corte = UMBRAL_ESPERADO[tipo](u)
        assert e["umbral"]["pendiente"] == pytest.approx(pendiente) and e["umbral"]["corte"] == pytest.approx(corte)
        # En u = 0 no se ve nada del plano entrante, sea cual sea el gris del campo (F ∈ [0, 1]); casi al final, casi
        # todo; y la fórmula llega al plano entero justo en u = 1.
        alfas = [pendiente * f + corte for f in (0.0, 1.0)]
        if u == 0.0:
            assert max(alfas) <= 0
        if u == 0.999:
            assert min(alfas) > 0.95
    pendiente, corte = UMBRAL_ESPERADO[tipo](1.0)
    assert pendiente + corte == pytest.approx(1) or pendiente + corte > 1


@pytest.mark.parametrize(("direccion", "hacia"), [("derecha", "right"), ("izquierda", "left"), ("arriba", "top")])
def test_la_cortina_es_una_rampa_del_ancho_del_lado_que_avanza_hacia_su_direccion(tmp_path, direccion, hacia):
    for u, e in zip(US, _entradas(tmp_path, "cortina", direccion, US)):
        if u > 1:
            assert e["cortina"] is None
            continue
        assert e["cortina"]["hacia"] == hacia
        assert e["cortina"]["opaco"] == pytest.approx((2 * u - 1) * 100)
        assert e["cortina"]["transparente"] == pytest.approx(2 * u * 100)


def test_el_papel_sube_con_el_velo_opaco_y_luego_el_velo_baja(tmp_path):
    for u, e in zip(US, _entradas(tmp_path, "papel", None, US)):
        if u < 0.5:
            assert (e["op"], e["papel"]) == (pytest.approx(_suave(u / 0.5)), 1)
        else:
            assert (e["op"], e["papel"]) == (1, pytest.approx(1 - _suave(min(1, (u - 0.5) / 0.5))))
    assert e["papel"] == 0  # al acabar, el velo no se ve


@pytest.mark.parametrize(
    ("tipo", "direccion", "nombre"),
    [
        ("cortina", None, "«cortina»"),
        ("cortina", "abajo", "«cortina»"),
        ("viento", "arriba", "«viento»"),
        ("mancha", "derecha", "no lleva dirección"),
        ("funde", "izquierda", "no lleva dirección"),
        ("barrido", 2, "1 o -1"),
    ],
)
def test_una_direccion_que_falta_o_no_vale_para_el_motor(tmp_path, tipo, direccion, nombre):
    ruta = _con_entrada(tmp_path, tipo, direccion)
    d = _evalua(
        f"const G2 = JSON.parse(require('node:fs').readFileSync({json.dumps(str(ruta))}, 'utf8'));"
        "try { Motor.crea(G2); return { lanza: false }; } catch (e) { return { lanza: true, mensaje: e.message }; }"
    )
    assert d["lanza"] and nombre in d["mensaje"] and "«p2»" in d["mensaje"]


def test_control_con_su_direccion_cada_entrada_arranca(tmp_path):
    for tipo, direccion in [*ENTRADAS_DE_TINTA, ("barrido", -1), ("barrido", None)]:
        ruta = _con_entrada(tmp_path, tipo, direccion)
        assert _evalua(
            f"Motor.crea(JSON.parse(require('node:fs').readFileSync({json.dumps(str(ruta))}, 'utf8')));"
            "return { ok: true };"
        ) == {"ok": True}, (tipo, direccion)


def test_compone_el_lenguaje_y_el_motor_conocen_las_mismas_direcciones_umbrales_y_curvas():
    from lib.escena import compone, escena

    d = _evalua(
        "return { dirs: Motor.DIRECCIONES_DE_ENTRADA, umbral: Motor.ENTRADAS_DE_UMBRAL, "
        "curvas: Object.keys(Motor.EASE) };"
    )
    assert {k: tuple(v) for k, v in d["dirs"].items()} == compone.DIRECCIONES_DE_ENTRADA
    assert tuple(d["umbral"]) == compone.ENTRADAS_DE_UMBRAL
    assert tuple(d["curvas"]) == escena.CURVAS


def test_acelera_y_frena_son_el_ease_in_y_el_ease_out_del_motor_de_laminas():
    """`lib/motion.py → _easing_expr`: ease_in = p², ease_out = 1 − (1 − p)²."""
    d = _evalua("return [0, 0.3, 0.5, 0.8, 1].map((p) => [Motor.EASE.acelera(p), Motor.EASE.frena(p)]);")
    for p, (acelera, frena) in zip([0, 0.3, 0.5, 0.8, 1], d):
        assert acelera == pytest.approx(p**2) and frena == pytest.approx(1 - (1 - p) ** 2)
