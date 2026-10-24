"""Los activos del motor de escena sin GPU (F6.2c): fábricas, semillas, lienzos y el lote con un ComfyUI falso.

Lo que se prueba aquí es lo que hace `activos.py` alrededor del modelo: qué instrucción arma con lo del canal, qué
referencia y qué lienzo le pasa, qué se registra de cada imagen, que lo subido a ComfyUI se borra aunque algo
falle, y que una referencia que falta para antes de tocar la GPU. Con el Qwen de verdad:
`test_activos_qwen.py`, que se pide a mano.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from utiles_activos import hoja_sintetica

from lib import comfy_client as cc
from lib import config, provenance
from lib.escena import activos, recorte

ESTILO = activos.Estilo(prefijo="PREFIJO-DEL-CANAL.", igual="IGUAL-DEL-CANAL.", conserva="CONSERVA-DEL-CANAL")


def _pj(**cambia) -> activos.Personaje:
    datos = {
        "id": "ana",
        "descripcion": "DESCRIPCION-CANONICA",
        "alto": 200,
        "de_pie": ("frente", "perfil"),
        "vistas": activos.VISTAS_DE_PIE,
        "mide_cabeza": True,
    }
    return activos.Personaje(**{**datos, **cambia})


# ------------------------------------------------------------------------------------------ lo del canal, sin defecto
@pytest.mark.parametrize(
    "cambia",
    [
        {"descripcion": " "},
        {"alto": 0},
        {"alto": 820.0},
        {"de_pie": ()},
        {"de_pie": ("espalda",)},
        {"mide_cabeza": None},
        {"id": "Ana López"},
        {"vistas": ""},
    ],
)
def test_un_personaje_mal_declarado_para(cambia):
    with pytest.raises(activos.ErrorDeActivos):
        _pj(**cambia)


def test_un_estilo_incompleto_para():
    with pytest.raises(activos.ErrorDeActivos, match="conserva"):
        activos.Estilo(prefijo="x", igual="y", conserva="")


# ------------------------------------------------------------------------------------------ las fábricas
def test_la_hoja_pide_las_dos_vistas_sobre_croma_con_la_lamina_de_referencia(tmp_path):
    h = activos.hoja(_pj(), ESTILO, referencia=tmp_path / "lamina.png", semillas=(7, 21))
    assert h.nombre == "hoja_ana" and h.lienzo == activos.LIENZO_HOJA and h.referencia == tmp_path / "lamina.png"
    assert h.piezas == ("ana_frente", "ana_perfil")
    for trozo in ("PREFIJO-DEL-CANAL.", "DESCRIPCION-CANONICA", activos.VISTAS_DE_PIE, "IGUAL-DEL-CANAL.", "#FF00FF"):
        assert trozo in h.prompt


def test_la_postura_usa_su_lienzo_de_referencia_como_referencia_y_como_lienzo(tmp_path):
    p = activos.postura(
        "ana_sentada",
        _pj(),
        ESTILO,
        vista="perfil",
        forma="ancho",
        pose="sitting on a step",
        de_pie=False,
        lienzos=tmp_path,
        semillas=(7,),
    )
    assert p.referencia == tmp_path / "ana_perfil_ancho.png" and p.lienzo is None
    assert (p.pj, p.vista, p.de_pie, p.base) == ("ana", "perfil", False, None)
    assert "now sitting on a step." in p.prompt and "DESCRIPCION-CANONICA" in p.prompt and "#FF00FF" in p.prompt


def test_la_variante_edita_en_su_sitio_y_hereda_de_la_postura_limpia(tmp_path):
    p = activos.postura(
        "ana_sentada",
        _pj(),
        ESTILO,
        vista="perfil",
        forma="ancho",
        pose="sitting",
        de_pie=False,
        lienzos=tmp_path,
        semillas=(7,),
    )
    v = activos.variante("ana_sentada_s", p, ESTILO, cambio="make her hands black with oil", semillas=(7,))
    vv = activos.variante("ana_sentada_ss", v, ESTILO, cambio="add a smudge", semillas=(7,))
    assert v.referencia == "ana_sentada" and v.lienzo is None and v.base == "ana_sentada"
    assert vv.referencia == "ana_sentada_s" and vv.base == "ana_sentada", "la base es siempre la postura limpia"
    assert (v.pj, v.vista, v.de_pie) == ("ana", "perfil", False)
    with pytest.raises(activos.ErrorDeActivos):
        activos.variante(
            "x", activos.hoja(_pj(), ESTILO, referencia=tmp_path, semillas=(7,)), ESTILO, cambio="c", semillas=(7,)
        )


def test_el_objeto_sustituye_a_quien_hay_en_la_hoja(tmp_path):
    o = activos.objetos(
        "herramientas",
        ESTILO,
        lista="a spanner, a pump",
        piezas=["o_llave", "o_bomba"],
        en="hoja_ana",
        quien="both girls",
        semillas=(7, 21),
    )
    assert o.referencia == "hoja_ana" and o.lienzo is None and o.piezas == ("o_llave", "o_bomba")
    assert "replace both girls with several separate objects" in o.prompt and "CONSERVA-DEL-CANAL" in o.prompt
    with pytest.raises(activos.ErrorDeActivos):
        activos.objetos("x", ESTILO, lista="a", piezas=[], en="hoja_ana", quien="both girls", semillas=(7,))


@pytest.mark.parametrize("semillas", [(), (7, -1), (7.0,), (True,)])
def test_las_semillas_son_enteros_declarados(semillas, tmp_path):
    with pytest.raises(activos.ErrorDeActivos):
        activos.hoja(_pj(), ESTILO, referencia=tmp_path, semillas=semillas)


# ------------------------------------------------------------------------------------------ elegir semilla
def test_la_imagen_elegida(tmp_path):
    una = activos.postura(
        "a1", _pj(), ESTILO, vista="frente", forma="alto", pose="p", de_pie=True, lienzos=tmp_path, semillas=(7,)
    )
    dos = activos.hoja(_pj(), ESTILO, referencia=tmp_path, semillas=(7, 21))
    for nombre, s in (("a1", 7), ("hoja_ana", 7), ("hoja_ana", 21)):
        ruta = activos.crudo(tmp_path, nombre, s)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(b"png")
    assert activos.elegida(tmp_path, una) == activos.crudo(tmp_path, "a1", 7)
    with pytest.raises(activos.ErrorDeActivos, match="falta elegir"):
        activos.elegida(tmp_path, dos)
    activos.elige(tmp_path, "hoja_ana", 21)
    assert activos.elegida(tmp_path, dos) == activos.crudo(tmp_path, "hoja_ana", 21)
    with pytest.raises(activos.ErrorDeActivos, match="semilla 99"):
        activos.elige(tmp_path, "hoja_ana", 99)


# ------------------------------------------------------------------------------------------ los lienzos de referencia
def _figura_de(ruta: Path) -> tuple[int, int, int, int]:
    rgba = recorte.quita_magenta(np.asarray(Image.open(ruta).convert("RGB")).astype(np.float32))
    ys, xs = np.nonzero(rgba[..., 3] > 128)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def test_los_lienzos_ponen_cada_figura_a_su_alto_con_los_pies_en_su_sitio(tmp_path):
    hoja = hoja_sintetica(tmp_path / "hoja_ana.png", altos=(200, 200))
    hechos = activos.prepara_lienzos(_pj(alto=300), hoja, tmp_path / "activos" / "ref")
    assert sorted(hechos) == ["frente_alto", "frente_ancho", "perfil_alto", "perfil_ancho"]
    for clave, ruta in hechos.items():
        ancho, alto = activos.LIENZOS[clave.split("_")[1]]
        assert Image.open(ruta).size == (ancho, alto)
        x0, y0, x1, y1 = _figura_de(ruta)
        assert alto - 1 - y1 == pytest.approx(activos.PIES_AL_BORDE + recorte.JUNTA_PX * 300 / 224, abs=3)
        assert abs((x0 + x1) / 2 - ancho / 2) <= 2, "centrada"
        assert y1 - y0 == pytest.approx(300 - 2 * recorte.JUNTA_PX * 300 / 224, abs=4), "la figura sin la junta"
    registros = json.loads((tmp_path / "activos" / "ref" / provenance.IMAGE_RECORDS_FILENAME).read_text("utf-8"))
    assert len(registros) == 4 and all(r["derivado_de"] == "hoja_ana.png" for r in registros)
    assert all(r["licencia"].startswith("desconocida") for r in registros), "la hoja de prueba no tiene registro"


def test_la_escala_de_los_lienzos_la_fija_la_figura_de_pie_del_personaje(tmp_path):
    """Un perro sentado de frente y de pie de perfil: la escala sale del perfil, y se aplica igual a las dos.

    La caja de una figura lleva la junta de `recorte.piezas` (12 px por lado), así que la figura de pie mide su
    alto por k = alto / (su alto + 24), como en video_1. Control: con la escala del frente, las dos salen a otra k.
    """
    hoja = hoja_sintetica(tmp_path / "hoja_ana.png", altos=(120, 200))
    alto = {}
    for de_pie in ("perfil", "frente"):
        hechos = activos.prepara_lienzos(_pj(alto=300, de_pie=(de_pie,)), hoja, tmp_path / de_pie)
        for vista in ("frente", "perfil"):
            x0, y0, x1, y1 = _figura_de(hechos[f"{vista}_alto"])
            alto[(de_pie, vista)] = y1 - y0
    j = 2 * recorte.JUNTA_PX
    assert alto[("perfil", "perfil")] == pytest.approx(200 * 300 / (200 + j), abs=4)
    assert alto[("perfil", "frente")] == pytest.approx(120 * 300 / (200 + j), abs=4), "la misma k para las dos"
    assert alto[("frente", "frente")] == pytest.approx(120 * 300 / (120 + j), abs=4), "control: otra figura, otra k"
    assert alto[("frente", "perfil")] == pytest.approx(200 * 300 / (120 + j), abs=6)


def test_una_hoja_que_no_tiene_dos_figuras_o_no_cabe_para(tmp_path):
    from PIL import ImageDraw
    from utiles_activos import fondo_de_croma, persona

    im = fondo_de_croma(420, 300)
    for x in (70, 210, 350):
        persona(ImageDraw.Draw(im), x, 270, 200, 24)
    im.save(tmp_path / "tres.png")
    with pytest.raises(activos.ErrorDeActivos, match="tiene 3"):
        activos.prepara_lienzos(_pj(), tmp_path / "tres.png", tmp_path / "ref")
    hoja = hoja_sintetica(tmp_path / "hoja.png", altos=(200, 200))
    with pytest.raises(activos.ErrorDeActivos, match="no cabe"):
        activos.prepara_lienzos(_pj(alto=1200), hoja, tmp_path / "ref")


# ------------------------------------------------------------------------------------------ el workflow
def test_el_workflow_de_edicion_tiene_la_referencia_y_el_lienzo_aparte():
    """La diferencia con qwen-edit-tinta, que es por lo que existe: el latente sale del LIENZO, no de la referencia."""
    wf = cc.load_workflow(config.ESCENA_WORKFLOW_EDICION)
    g = cc.build_prompt_graph(wf, "instrucción", seed=21, overrides={"referencia": "sub/r.png", "lienzo": "sub/l.png"})
    assert g["5"]["inputs"]["image"] == "sub/r.png" and g["20"]["inputs"]["image"] == "sub/l.png"
    assert g["6"]["inputs"]["image1"] == ["5", 0] and g["8"]["inputs"]["pixels"] == ["20", 0]
    assert g["10"]["inputs"]["seed"] == 21 and g["6"]["inputs"]["prompt"] == "instrucción"
    assert wf["modelo"]["url"].startswith("https://") and wf["prefijo_estilo"] == ""
    tinta = cc.load_workflow("qwen-edit-tinta")["grafo"]
    assert tinta["8"]["inputs"]["pixels"] == ["5", 0], "control: en el hermano, el lienzo es la referencia"
    with pytest.raises(cc.ComfyError, match="lienzo"):
        cc.build_prompt_graph(wf, "x", overrides={"referencia": "r.png"})


# ------------------------------------------------------------------------------------------ el lote, con ComfyUI falso
@pytest.fixture
def comfy(monkeypatch):
    """Un ComfyUI falso: registra lo que se le sube, lo que se le pide y lo que se borra."""
    estado = {"subidas": [], "borradas": [], "grafos": [], "libera": 0, "vivo": True, "falla_en": None}

    @contextlib.contextmanager
    def servidor():
        yield False  # ya estaba vivo: el de la instalación compartida

    def sube(ruta):
        nombre = f"{config.COMFY_OUTPUT_SUBFOLDER}/{len(estado['subidas'])}-{Path(ruta).name}"
        estado["subidas"].append((Path(ruta), nombre))
        return nombre

    def render(workflow, prompt, output_path, *, width, height, seed, overrides):
        if estado["falla_en"] is not None and len(estado["grafos"]) == estado["falla_en"]:
            raise cc.ComfyError("falló a propósito")
        estado["grafos"].append({"prompt": prompt, "seed": seed, "size": (width, height), **overrides})
        Image.new("RGB", (width, height), recorte.CROMA).save(output_path)
        return {
            "file": str(output_path),
            "workflow": workflow["id"],
            "modelo": workflow["modelo"]["nombre"],
            "licencia": workflow["modelo"]["licencia"],
            "prompt": prompt,
            "seed": seed,
            "resolucion": f"{width}x{height}",
            "segundos": 0.1,
        }

    monkeypatch.setattr(cc, "server_is_alive", lambda *a, **k: estado["vivo"])
    monkeypatch.setattr(cc, "comfy_server", servidor)
    monkeypatch.setattr(cc, "sube_imagen", sube)
    monkeypatch.setattr(cc, "render", render)
    monkeypatch.setattr(cc, "borra_subidas", lambda nombres: estado["borradas"].extend(nombres))
    monkeypatch.setattr(cc, "free_memory", lambda: estado.__setitem__("libera", estado["libera"] + 1))
    return estado


def _lote(tmp_path: Path) -> tuple[list[activos.Activo], Path]:
    lamina = tmp_path / "lamina.png"
    Image.new("RGB", (100, 60), (200, 150, 100)).save(lamina)
    lienzos = tmp_path / "ref"
    lienzos.mkdir()
    Image.new("RGB", (704, 960), recorte.CROMA).save(lienzos / "ana_frente_alto.png")
    h = activos.hoja(_pj(), ESTILO, referencia=lamina, semillas=(7,))
    p = activos.postura(
        "ana_saluda",
        _pj(),
        ESTILO,
        vista="frente",
        forma="alto",
        pose="waving",
        de_pie=True,
        lienzos=lienzos,
        semillas=(7, 21),
    )
    v = activos.variante("ana_saluda_s", p, ESTILO, cambio="make her hands black", semillas=(3,))
    return [h, p, v], lamina


def test_el_lote_genera_en_orden_registra_y_borra_lo_subido(comfy, tmp_path):
    lote, lamina = _lote(tmp_path)
    run = tmp_path / "run"
    dir_activos, dir_trabajo = config.activos_del_run(run), config.trabajo_de_activos(run)
    registros = activos.genera(lote[:2], dir_activos, dir_trabajo)
    assert [(g["seed"], g["size"]) for g in comfy["grafos"]] == [(7, (1664, 928)), (7, (704, 960)), (21, (704, 960))]
    hoja_ref, hoja_lienzo = comfy["grafos"][0]["referencia"], comfy["grafos"][0]["lienzo"]
    assert dict((n, p) for p, n in comfy["subidas"])[hoja_ref] == lamina
    assert dict((n, p) for p, n in comfy["subidas"])[hoja_lienzo].name == "lienzo-croma-1664x928.png"
    assert comfy["grafos"][1]["referencia"] == comfy["grafos"][1]["lienzo"], "la postura: su lienzo es la referencia"
    assert sorted(comfy["borradas"]) == sorted(n for _, n in comfy["subidas"]) and comfy["libera"] == 1
    assert {r["activo"] for r in registros} == {"hoja_ana", "ana_saluda"}
    postura = next(r for r in registros if r["activo"] == "ana_saluda")
    assert postura["referencia"] == "ana_frente_alto.png" and postura["lienzo"] == "la propia referencia"
    assert (postura["pj"], postura["vista"], postura["de_pie"]) == ("ana", "frente", True)
    # La variante parte de una postura con dos semillas: sin elegir, para antes de pedir nada.
    with pytest.raises(activos.ErrorDeActivos, match="ninguna elegida"):
        activos.genera(lote, dir_activos, dir_trabajo)
    assert len(comfy["grafos"]) == 3
    activos.elige(dir_activos, "ana_saluda", 21)
    activos.genera(lote, dir_activos, dir_trabajo)
    assert len(comfy["grafos"]) == 4, "lo que ya está en disco no se vuelve a pedir"
    ultima = comfy["subidas"][-1][0]
    assert ultima == activos.crudo(dir_activos, "ana_saluda", 21), "la variante parte de la semilla elegida"
    informe = provenance.sync(run, verbose=False)
    assert informe["cuadra"] and informe["archivos_medios"] == 4 and informe["licencias_por_cerrar"] == []
    for a in provenance.read_ledger(run)["assets"]:
        assert a["fuente"] and a["licencia"].startswith("Apache-2.0") and a["url"].startswith("https://"), a["id"]
        assert a["detalle"]["seed"] in (3, 7, 21) and a["detalle"]["workflow"] == "qwen-edit-lienzo"


def test_si_una_imagen_falla_lo_subido_se_borra_igual(comfy, tmp_path):
    lote, _ = _lote(tmp_path)
    comfy["falla_en"] = 1
    with pytest.raises(cc.ComfyError):
        activos.genera(lote[:2], tmp_path / "a", tmp_path / "t")
    assert comfy["subidas"] and sorted(comfy["borradas"]) == sorted(n for _, n in comfy["subidas"])
    assert comfy["libera"] == 1
    assert (
        json.loads((tmp_path / "a" / "crudo" / provenance.IMAGE_RECORDS_FILENAME).read_text("utf-8"))[0]["activo"]
        == "hoja_ana"
    ), "lo generado antes del fallo conserva su registro"


def test_una_referencia_que_falta_para_antes_de_tocar_comfyui(comfy, tmp_path):
    p = activos.postura(
        "x",
        _pj(),
        ESTILO,
        vista="frente",
        forma="alto",
        pose="p",
        de_pie=True,
        lienzos=tmp_path / "no-hay",
        semillas=(7,),
    )
    with pytest.raises(activos.ErrorDeActivos, match="no existe la referencia"):
        activos.genera([p], tmp_path / "a", tmp_path / "t")
    v = activos.variante("y", p, ESTILO, cambio="c", semillas=(7,))
    with pytest.raises(activos.ErrorDeActivos, match="no está generado"):
        activos.genera([v, p], tmp_path / "a", tmp_path / "t", solo=["y"])
    assert comfy["grafos"] == [] and comfy["subidas"] == []


def test_si_comfyui_no_esta_vivo_se_mira_antes_que_la_gpu_este_libre(comfy, monkeypatch, tmp_path):
    from lib.escena.render import ErrorDeRender

    lote, _ = _lote(tmp_path)
    comfy["vivo"] = False

    def ocupada(*a, **k):
        raise ErrorDeRender("hay otro trabajo del estudio en la GPU (llama-server.exe)")

    monkeypatch.setattr(activos, "exige_gpu_libre", ocupada)
    with pytest.raises(activos.ErrorDeActivos, match="llama-server"):
        activos.genera(lote[:1], tmp_path / "a", tmp_path / "t")
    assert comfy["grafos"] == []


# ------------------------------------------------------------------------------------------ del lote al obrero
def test_las_operaciones_de_recorte_de_cada_tipo(tmp_path):
    lote, _ = _lote(tmp_path)
    objeto = activos.objetos(
        "herr", ESTILO, lista="a, b", piezas=["o_a", "o_b"], en="hoja_ana", quien="both girls", semillas=(7,)
    )
    for a in [*lote, objeto]:
        for s in a.semillas:
            ruta = activos.crudo(tmp_path, a.nombre, s)
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(b"png")
    activos.elige(tmp_path, "ana_saluda", 7)
    ops = {op["nombre"]: op for op in activos.operaciones_de_recorte([*lote, objeto], {"ana": _pj()}, tmp_path)}
    assert ops["hoja_ana"]["piezas"] == ["ana_frente", "ana_perfil"]
    assert ops["hoja_ana"]["k_de"] == "ana_frente" and ops["hoja_ana"]["alto_k"] == recorte.ESCALA_RECORTE * 200
    assert "piezas" not in ops["ana_saluda"] and "k_de" not in ops["ana_saluda"]
    assert ops["herr"]["piezas"] == ["o_a", "o_b"]
    figuras = activos.figuras([*lote, objeto], {"ana": _pj()})
    assert set(figuras) == {"ana_frente", "ana_perfil", "ana_saluda", "ana_saluda_s"}
    assert figuras["ana_saluda_s"].base == "ana_saluda"
