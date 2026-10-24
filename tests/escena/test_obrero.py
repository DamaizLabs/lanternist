"""El obrero de activos sin GPU (F6.2c): el cliente, las guardas del trabajador, las teselas y la procedencia.

- El cliente se prueba con un trabajador FALSO (`_lanza` sustituido) que escribe lo que escribiría el de verdad: así
  se mira lo que hace el cliente con lo que vuelve —catálogo, procedencia, fallos a medias— sin la GPU.
- Las guardas del trabajador (sin red, CUDA obligatoria, operación desconocida) se prueban lanzándolo de verdad en
  un subproceso, que es como corre.
- Las teselas de Real-ESRGAN se prueban en CPU con una ampliación de referencia en lugar del modelo.

Con la GPU y los modelos de verdad: `test_obrero_gpu.py`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from utiles_activos import catalogo_de, figura_rgba, registro_de_qwen

from lib import config, provenance
from lib.escena import comprobaciones, obrero, obrero_worker, recorte
from lib.escena.render import ErrorDeRender

RAIZ = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------------------------------ el trabajador falso
def _run(tmp_path: Path) -> tuple[Path, Path, Path]:
    run = tmp_path / "run"
    return run, config.activos_del_run(run), config.trabajo_de_activos(run)


def _crudo(dir_activos: Path, nombre: str, con_registro: bool = True) -> Path:
    """Una imagen «generada por Qwen» en crudo/, con su registro como el de `activos.genera`."""
    ruta = dir_activos / "crudo" / f"{nombre}-7.png"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), recorte.CROMA).save(ruta)
    if con_registro:
        sidecar = ruta.parent / provenance.IMAGE_RECORDS_FILENAME
        previos = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.exists() else []
        sidecar.write_text(json.dumps(previos + [registro_de_qwen(ruta)]), encoding="utf-8")
    return ruta


@pytest.fixture
def falso(monkeypatch, tmp_path):
    """Sustituye el lanzamiento del trabajador por uno que escribe sus imágenes y su resultado sin GPU.

    `falso["falla_tras"] = n` hace que muera después de n operaciones, con código 1, como el de verdad.
    """
    estado = {"falla_tras": None, "trabajos": []}
    peso = tmp_path / "esrgan.pth"
    peso.write_bytes(b"peso")
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    monkeypatch.setattr(config, "ESCENA_PYTHON", str(python))
    monkeypatch.setattr(config, "ESCENA_ESRGAN_PESO", peso)
    monkeypatch.setattr(obrero, "exige_gpu_libre", lambda *a, **k: 6973)

    def lanza(trabajo: Path, resultado: Path, log: Path) -> int:
        job = json.loads(trabajo.read_text(encoding="utf-8"))
        estado["trabajos"].append(job)
        img = Path(job["img_dir"])
        img.mkdir(parents=True, exist_ok=True)
        hecho = {"modelos": {"esrgan": {"sha256": "abc"}, "sam": {"revision": "665f8e2"}}, "operaciones": []}
        for i, op in enumerate(job["operaciones"]):
            if estado["falla_tras"] is not None and i >= estado["falla_tras"]:
                log.write_text("Traceback: falló a propósito\n", encoding="utf-8")
                return 1
            nombres = op.get("piezas") or list(op.get("sitios") or []) or [op["nombre"]]
            if op["op"] == "separa":
                nombres = [f"{op['nombre']}_{p['nombre']}" for p in op["piezas"]]
                nombres += [f"{op['nombre']}_base"] if op.get("quita_de_la_base") else []
            entradas, archivos = {}, {}
            for n in nombres:
                Image.fromarray(figura_rgba(120, 12), "RGBA").save(img / f"{n}.png")
                entradas[n] = {
                    "src": f"{job['src_dir']}/{n}.png",
                    "w": 64,
                    "h": 152,
                    "ax": 32,
                    "ay": 136,
                    "ox": 0,
                    "oy": 0,
                    "k": 1.0,
                    # Como el trabajador de verdad (F6.2d): lo que separa SAM dice de qué figura sale.
                    **({"de": op["nombre"]} if op["op"] == "separa" else {}),
                }
                archivos[n] = str(img / f"{n}.png")
            hecho["operaciones"].append(
                {
                    "indice": i,
                    "op": op["op"],
                    "nombre": op["nombre"],
                    "entradas": entradas,
                    "archivos": archivos,
                    "segundos": 0.1,
                }
            )
            resultado.write_text(json.dumps(hecho), encoding="utf-8")
        log.write_text("ok\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(obrero, "_lanza", lanza)
    return estado


# ------------------------------------------------------------------------------------------ el cliente
def test_el_obrero_apunta_catalogo_y_procedencia_con_fuente_licencia_y_url(falso, tmp_path):
    """El criterio de F6.2c: cada asset con fuente, licencia y url en assets.json, y el conteo cuadra."""
    run, activos, trabajo = _run(tmp_path)
    ops = [
        obrero.recorta("a_saluda", _crudo(activos, "a_saluda")),
        obrero.recorta(
            "hoja_a", _crudo(activos, "hoja_a"), piezas=["a_frente", "a_perfil"], k_de="a_frente", alto_k=1640
        ),
    ]
    obrero.ejecuta(ops, activos, trabajo)

    cat = obrero.lee_catalogo(activos)["imagenes"]
    assert set(cat) == {"a_saluda", "a_frente", "a_perfil"}
    assert falso["trabajos"][0]["operaciones"][1]["k_de"] == "a_frente"
    informe = provenance.sync(run, verbose=False)
    assert informe["cuadra"], informe
    assert informe["licencias_por_cerrar"] == []
    for asset in provenance.read_ledger(run)["assets"]:
        assert asset["fuente"] and asset["licencia"] and asset["url"], asset["id"]
    recorte_ = next(a for a in provenance.read_ledger(run)["assets"] if a["id"] == "activos/img/a_saluda.png")
    assert recorte_["licencia"].startswith("Apache-2.0"), "la licencia empieza por la del modelo que la dibujó"
    assert "BSD-3-Clause" in recorte_["licencia"]
    assert recorte_["url"].split(" · ") == [
        "https://huggingface.co/Qwen/Qwen-Image-Edit-2511",
        "https://github.com/xinntao/Real-ESRGAN",
    ]
    assert recorte_["detalle"]["seed"] == 7 and recorte_["detalle"]["derivado_de"] == "activos/crudo/a_saluda-7.png"


def test_control_un_origen_sin_registro_deja_la_licencia_por_cerrar(falso, tmp_path):
    run, activos, trabajo = _run(tmp_path)
    obrero.ejecuta([obrero.recorta("x", _crudo(activos, "x", con_registro=False))], activos, trabajo)
    informe = provenance.sync(run, verbose=False)
    assert "activos/img/x.png" in informe["licencias_por_cerrar"]


def test_control_un_recorte_sin_su_registro_no_cuadra(falso, tmp_path):
    """Lo que el conteo cruzado vería si el obrero no anotara lo que escribe."""
    run, activos, trabajo = _run(tmp_path)
    obrero.ejecuta([obrero.recorta("x", _crudo(activos, "x"))], activos, trabajo)
    (activos / "img" / provenance.IMAGE_RECORDS_FILENAME).unlink()
    informe = provenance.sync(run, verbose=False)
    assert not informe["cuadra"] and informe["sin_registrar"] == ["activos/img/x.png"]


def test_los_lienzos_de_croma_del_trabajo_no_son_assets(falso, tmp_path):
    run, activos, trabajo = _run(tmp_path)
    obrero.ejecuta([obrero.recorta("x", _crudo(activos, "x"))], activos, trabajo)
    Image.new("RGB", (8, 8), recorte.CROMA).save(trabajo / "lienzo-croma-8x8.png")
    informe = provenance.sync(run, verbose=False)
    assert informe["cuadra"] and informe["intermedios_de_montaje"] >= 1


def test_si_el_obrero_muere_a_mitad_lo_hecho_queda_apuntado_y_se_para(falso, tmp_path):
    run, activos, trabajo = _run(tmp_path)
    falso["falla_tras"] = 1
    ops = [obrero.recorta("x", _crudo(activos, "x")), obrero.recorta("y", _crudo(activos, "y"))]
    with pytest.raises(obrero.ErrorDelObrero, match="tras 1 de 2"):
        obrero.ejecuta(ops, activos, trabajo)
    assert set(obrero.lee_catalogo(activos)["imagenes"]) == {"x"}
    assert provenance.sync(run, verbose=False)["cuadra"]


def test_una_separacion_parte_de_un_recorte_con_registro(falso, tmp_path):
    run, activos, trabajo = _run(tmp_path)
    obrero.ejecuta([obrero.recorta("calle", _crudo(activos, "calle"))], activos, trabajo)
    base = obrero.lee_catalogo(activos)["imagenes"]["calle"]
    pieza = {"nombre": "arbol", "caja": [0, 0, 10, 10], "pos": [[5, 5]], "neg": [], "pivote": [5, 9]}
    obrero.ejecuta([obrero.separa("calle", "calle.png", base, [pieza], quita_de_la_base=False)], activos, trabajo)
    assert provenance.sync(run, verbose=False)["cuadra"]
    arbol = next(a for a in provenance.read_ledger(run)["assets"] if a["id"] == "activos/img/calle_arbol.png")
    assert "SAM 2.1" in arbol["modelo"] and "Real-ESRGAN" in arbol["modelo"], "hereda la cadena de su recorte"
    assert arbol["url"].endswith("https://huggingface.co/facebook/sam2.1-hiera-large")
    assert provenance.sync(run, verbose=False)["cuadra"]


def test_la_base_rellenada_dice_que_la_toco_opencv_y_la_pieza_no(falso, tmp_path):
    """F6.6: la base de un fondo con el hueco rellenado lleva OpenCV en su procedencia; la pieza, solo SAM."""
    run, activos, trabajo = _run(tmp_path)
    obrero.ejecuta([obrero.recorta("sala", _crudo(activos, "sala"))], activos, trabajo)
    base = obrero.lee_catalogo(activos)["imagenes"]["sala"]
    pieza = {"nombre": "peana", "caja": [0, 0, 10, 10], "pos": [[5, 5]], "neg": [], "pivote": [5, 9]}
    op = obrero.separa("sala", "sala.png", base, [pieza], quita_de_la_base=True, rellena_base=True)
    assert op["rellena_base"] is True
    obrero.ejecuta([op], activos, trabajo)
    assert provenance.sync(run, verbose=False)["cuadra"]
    assets = {a["id"]: a for a in provenance.read_ledger(run)["assets"]}
    fondo, peana = assets["activos/img/sala_base.png"], assets["activos/img/sala_peana.png"]
    assert "OpenCV" in fondo["modelo"] and "Apache-2.0" in fondo["licencia"]
    assert fondo["url"].endswith("https://github.com/opencv/opencv")
    assert "OpenCV" not in peana["modelo"], "la pieza no la tocó el relleno"


def test_control_sin_rellenar_la_base_no_nombra_opencv(falso, tmp_path):
    run, activos, trabajo = _run(tmp_path)
    obrero.ejecuta([obrero.recorta("sala", _crudo(activos, "sala"))], activos, trabajo)
    base = obrero.lee_catalogo(activos)["imagenes"]["sala"]
    pieza = {"nombre": "peana", "caja": [0, 0, 10, 10], "pos": [[5, 5]], "neg": [], "pivote": [5, 9]}
    op = obrero.separa("sala", "sala.png", base, [pieza], quita_de_la_base=True)
    assert "rellena_base" not in op
    obrero.ejecuta([op], activos, trabajo)
    assert provenance.sync(run, verbose=False)["cuadra"]
    fondo = next(a for a in provenance.read_ledger(run)["assets"] if a["id"] == "activos/img/sala_base.png")
    assert "OpenCV" not in fondo["modelo"]


def test_un_fondo_del_episodio_lo_dice_en_su_entrada_y_lo_que_se_separa_de_el_tambien(falso, tmp_path):
    """F6.6: una lámina del run y sus piezas llevan `del_episodio`, para que la biblioteca del canal no las coja."""
    run, activos, trabajo = _run(tmp_path)
    lamina = _crudo(activos, "lamina")
    obrero.ejecuta(
        [obrero.fondo("lamina_01", lamina, del_episodio=True), obrero.fondo("otro", lamina)], activos, trabajo
    )
    cat = obrero.lee_catalogo(activos)["imagenes"]
    assert cat["lamina_01"]["del_episodio"] is True
    assert "del_episodio" not in cat["otro"], "control: un fondo sin la marca no la lleva"
    pieza = {"nombre": "peana", "caja": [0, 0, 10, 10], "pos": [[5, 5]], "neg": [], "pivote": [5, 9]}
    obrero.ejecuta(
        [obrero.separa("lamina_01", "lamina_01.png", cat["lamina_01"], [pieza], quita_de_la_base=True)],
        activos,
        trabajo,
    )
    cat = obrero.lee_catalogo(activos)["imagenes"]
    assert cat["lamina_01_peana"]["del_episodio"] is True and cat["lamina_01_base"]["del_episodio"] is True


def test_una_separacion_puede_partir_de_la_lamina_que_amplia_el_mismo_trabajo(falso, tmp_path):
    """F6.6: `fondo` y `separa` de esa lámina van en un solo trabajo; el trabajador los hace en orden."""
    _, activos, trabajo = _run(tmp_path)
    lamina = _crudo(activos, "lamina")
    pieza = {"nombre": "peana", "caja": [0, 0, 10, 10], "pos": [[5, 5]], "neg": [], "pivote": [5, 9]}
    obrero.ejecuta(
        [
            obrero.fondo("lamina_01", lamina),
            obrero.separa("lamina_01", "lamina_01.jpg", {}, [pieza], quita_de_la_base=False),
        ],
        activos,
        trabajo,
    )
    assert "lamina_01_peana" in obrero.lee_catalogo(activos)["imagenes"]
    # Y otra separación puede partir de la base que deja la anterior, en el mismo trabajo.
    mas = obrero.separa("lamina_02", "lamina_02.jpg", {}, [pieza], quita_de_la_base=True)
    resto = obrero.separa("lamina_02_base", "lamina_02_base.png", {}, [pieza], quita_de_la_base=True, rellena_base=True)
    obrero.ejecuta([obrero.fondo("lamina_02", lamina), mas, resto], activos, trabajo)
    assert "lamina_02_base_base" in obrero.lee_catalogo(activos)["imagenes"]
    # Control: una separación de algo que nadie escribe antes sigue parando antes de lanzar.
    with pytest.raises(obrero.ErrorDelObrero, match="no existe la imagen de origen"):
        obrero.ejecuta([obrero.separa("otra", "otra.jpg", {}, [pieza], quita_de_la_base=False)], activos, trabajo)


def test_la_base_rellenada_con_una_lamina_limpia_lleva_su_procedencia(falso, tmp_path):
    """F6.6: el hueco viene de la sala limpia de Qwen, así que su licencia y su url van en el registro de la base."""
    run, activos, trabajo = _run(tmp_path)
    recortes = [obrero.recorta("sala", _crudo(activos, "sala")), obrero.recorta("limpia", _crudo(activos, "limpia"))]
    obrero.ejecuta(recortes, activos, trabajo)
    base = obrero.lee_catalogo(activos)["imagenes"]["sala"]
    pieza = {"nombre": "barrera", "caja": [0, 0, 10, 10], "pos": [[5, 5]], "neg": [], "pivote": [5, 9]}
    op = obrero.separa("sala", "sala.png", base, [pieza], quita_de_la_base=True, relleno="limpia.png")
    assert op["rellena_base"] is True and op["relleno"] == "limpia.png"
    obrero.ejecuta([op], activos, trabajo)
    assert provenance.sync(run, verbose=False)["cuadra"]
    regs = {
        Path(r["file"]).name: r
        for r in json.loads((activos / "img" / provenance.IMAGE_RECORDS_FILENAME).read_text("utf-8"))
    }
    fondo, barrera = regs["sala_base.png"], regs["sala_barrera.png"]
    assert fondo["relleno_con"] == "activos/img/limpia.png" and "relleno (limpia.png): Apache-2.0" in fondo["licencia"]
    assert "lámina limpia" in fondo["origen"] and "OpenCV" not in fondo["modelo"]
    assert "relleno_con" not in barrera, "la pieza no lleva píxeles de la lámina limpia"


def test_control_un_relleno_que_no_existe_para_antes_de_lanzar(falso, tmp_path):
    _, activos, trabajo = _run(tmp_path)
    obrero.ejecuta([obrero.recorta("sala", _crudo(activos, "sala"))], activos, trabajo)
    pieza = {"nombre": "barrera", "caja": [0, 0, 10, 10], "pos": [[5, 5]], "neg": [], "pivote": [5, 9]}
    op = obrero.separa("sala", "sala.png", {}, [pieza], quita_de_la_base=True, relleno="no-esta.jpg")
    lanzados = len(falso["trabajos"])
    with pytest.raises(obrero.ErrorDelObrero, match="lámina limpia del relleno"):
        obrero.ejecuta([op], activos, trabajo)
    assert len(falso["trabajos"]) == lanzados, "no llega a lanzar el trabajador"
    # Si la amplía un `fondo` del mismo trabajo, sí vale.
    obrero.ejecuta([obrero.fondo("no-esta", _crudo(activos, "x")), op], activos, trabajo)


def test_el_relleno_con_una_lamina_limpia_toma_el_hueco_de_ella():
    """El hueco sale de la lámina limpia, lo lejano queda como estaba y el alfa no cambia."""
    rgba = np.zeros((120, 160, 4), np.uint8)
    rgba[..., :3], rgba[..., 3] = (200, 180, 140), 255
    rgba[40:80, 60:100, :3] = (20, 20, 20)  # la pieza que se separa
    limpia = np.zeros((120, 160, 4), np.uint8)
    limpia[..., :3], limpia[..., 3] = (90, 120, 160), 255  # la sala sin ella, de otro color para verlo
    hueco = np.zeros((120, 160), np.float32)
    hueco[40:80, 60:100] = 1.0
    lleno = obrero_worker.rellena_con(rgba, hueco, limpia)
    assert np.abs(lleno[50:70, 70:90, :3].astype(int) - np.array([90, 120, 160])).max() <= 1, "dentro, la limpia"
    assert (lleno[0:10, 0:10, :3] == rgba[0:10, 0:10, :3]).all(), "lejos del hueco, la base tal cual"
    assert (lleno[..., 3] == 255).all()
    with pytest.raises(ValueError, match="mide"):
        obrero_worker.rellena_con(rgba, hueco, limpia[:60])


def test_el_tampon_de_clonar_toma_el_hueco_de_la_misma_imagen_a_unos_px():
    """F6.6: el nudo junto a la pera cerrada se tapa con la mesa que hay 110 px a su derecha."""
    rgba = np.zeros((60, 200, 4), np.uint8)
    rgba[..., 3] = 255
    rgba[:, :100, :3] = (30, 30, 30)  # el contorno oscuro de la pera, a la izquierda
    rgba[:, 100:, :3] = (210, 190, 150)  # la mesa
    rgba[20:40, 100:120, :3] = (90, 90, 90)  # el resto pegado al contorno
    hueco = np.zeros((60, 200), np.float32)
    hueco[20:40, 100:120] = 1.0
    copia = obrero_worker.desplazada(rgba, 60, 0)
    assert (copia[30, 105, :3] == rgba[30, 165, :3]).all(), "en cada píxel, lo que había 60 px a la derecha"
    lleno = obrero_worker.rellena_con(rgba, hueco, copia)
    assert np.abs(lleno[25:35, 108:112, :3].astype(int) - np.array([210, 190, 150])).max() <= 1, "dentro, la mesa"
    # Control: Telea tira del contorno oscuro de la izquierda, que es lo que pasó con el nudo.
    pytest.importorskip("cv2")

    class Taller:
        modelos: dict = {}

    telea = obrero_worker.rellena(rgba, hueco, Taller())
    assert telea[30, 102, :3].astype(int).mean() < 150


def test_el_relleno_desplazado_se_apunta_como_tampon_y_no_se_junta_con_una_lamina(falso, tmp_path):
    run, activos, trabajo = _run(tmp_path)
    obrero.ejecuta([obrero.recorta("sala", _crudo(activos, "sala"))], activos, trabajo)
    base = obrero.lee_catalogo(activos)["imagenes"]["sala"]
    pieza = {"nombre": "nudo", "caja": [0, 0, 10, 10], "pos": [[5, 5]], "neg": [], "pivote": [5, 9]}
    op = obrero.separa("sala", "sala.png", base, [pieza], quita_de_la_base=True, relleno_desplazado=(110, 0))
    assert op["rellena_base"] is True and op["relleno_desplazado"] == [110, 0]
    obrero.ejecuta([op], activos, trabajo)
    regs = {
        Path(r["file"]).name: r
        for r in json.loads((activos / "img" / provenance.IMAGE_RECORDS_FILENAME).read_text("utf-8"))
    }
    assert "tampón de clonar" in regs["sala_base.png"]["origen"]
    with pytest.raises(obrero.ErrorDelObrero, match="no de las dos"):
        obrero.separa(
            "sala", "sala.png", base, [pieza], quita_de_la_base=True, relleno="x.jpg", relleno_desplazado=(1, 0)
        )


@pytest.mark.parametrize("relleno", [{"rellena_base": True}, {"relleno": "limpia.jpg"}, {"relleno_desplazado": (9, 0)}])
def test_rellenar_la_base_exige_quitarle_las_piezas(relleno):
    with pytest.raises(obrero.ErrorDelObrero, match="quita_de_la_base"):
        obrero.separa("x", "x.png", {}, [{"nombre": "p", "caja": [0, 0, 1, 1], "pivote": [0, 0]}],
                      quita_de_la_base=False, **relleno)  # fmt: skip


def test_lo_que_se_separa_de_un_fondo_del_episodio_lo_hereda_aunque_la_base_no_lo_diga(falso, tmp_path):
    """Revisión del commit de F6.6, R1: con `base={}`, la marca llega por la imagen de la que parte la separación."""
    _, activos, trabajo = _run(tmp_path)
    lamina = _crudo(activos, "lamina")
    pieza = {"nombre": "peana", "caja": [0, 0, 10, 10], "pos": [[5, 5]], "neg": [], "pivote": [5, 9]}
    sep = obrero.separa("lamina_01", "lamina_01.jpg", {}, [pieza], quita_de_la_base=True)
    obrero.ejecuta([obrero.fondo("lamina_01", lamina, del_episodio=True), sep], activos, trabajo)
    cat = obrero.lee_catalogo(activos)["imagenes"]
    assert cat["lamina_01_peana"]["del_episodio"] is True and cat["lamina_01_base"]["del_episodio"] is True
    # Control: desde un fondo sin la marca, nada la lleva.
    otra = obrero.separa("lamina_02", "lamina_02.jpg", {}, [pieza], quita_de_la_base=True)
    obrero.ejecuta([obrero.fondo("lamina_02", lamina), otra], activos, trabajo)
    cat = obrero.lee_catalogo(activos)["imagenes"]
    assert "del_episodio" not in cat["lamina_02_peana"] and "del_episodio" not in cat["lamina_02_base"]


def test_un_relleno_sin_rellena_base_se_apunta_igual_que_lo_hace_el_trabajador(falso, tmp_path):
    """R2: un dict hecho a mano con `relleno` y sin `rellena_base` lleva igual la licencia de la lámina limpia."""
    run, activos, trabajo = _run(tmp_path)
    recortes = [obrero.recorta("sala", _crudo(activos, "sala")), obrero.recorta("limpia", _crudo(activos, "limpia"))]
    obrero.ejecuta(recortes, activos, trabajo)
    base = obrero.lee_catalogo(activos)["imagenes"]["sala"]
    pieza = {"nombre": "barrera", "caja": [0, 0, 10, 10], "pos": [[5, 5]], "neg": [], "pivote": [5, 9]}
    op = obrero.separa("sala", "sala.png", base, [pieza], quita_de_la_base=True, relleno="limpia.png")
    op.pop("rellena_base")
    assert obrero.base_rellenada(op)
    obrero.ejecuta([op], activos, trabajo)
    regs = {
        Path(r["file"]).name: r
        for r in json.loads((activos / "img" / provenance.IMAGE_RECORDS_FILENAME).read_text("utf-8"))
    }
    assert regs["sala_base.png"]["relleno_con"] == "activos/img/limpia.png"


def test_el_relleno_pinta_el_hueco_con_lo_que_lo_rodea():
    """El hueco de una pieza, sobre un fondo liso, sale del color del fondo y opaco (la lámina sigue opaca)."""
    pytest.importorskip("cv2")

    class Taller:
        modelos: dict = {}

    rgba = np.zeros((120, 160, 4), np.uint8)
    rgba[..., :3], rgba[..., 3] = (200, 180, 140), 255  # un pergamino liso
    rgba[40:80, 60:100, :3] = (20, 20, 20)  # la pieza, oscura, que se separa
    hueco = np.zeros((120, 160), np.float32)
    hueco[40:80, 60:100] = 1.0
    lleno = obrero_worker.rellena(rgba, hueco, Taller())
    dentro = lleno[45:75, 65:95, :3].astype(int)
    assert np.abs(dentro - np.array([200, 180, 140])).max() <= 6, "el hueco toma el color de lo que lo rodea"
    assert (lleno[..., 3] == 255).all(), "el alfa no cambia"
    assert np.abs(rgba[45:75, 65:95, :3].astype(int) - np.array([200, 180, 140])).max() > 150, "control: era oscuro"
    assert Taller.modelos["opencv"]["metodo"] == "inpaint Telea"


@pytest.mark.parametrize(
    "rompe, motivo",
    [
        (lambda a: [{"op": "baila", "nombre": "x"}], "no sabe hacer"),
        (lambda a: [obrero.recorta("x", a / "no-existe.png")], "no existe"),
        (
            lambda a: [
                obrero.separa(
                    "x", "x.png", {}, [{"nombre": "p", "caja": [0, 0, 1, 1], "pivote": [0, 0]}], quita_de_la_base=True
                )
            ],
            "ya está en el catálogo",
        ),
    ],
)
def test_lo_que_no_se_puede_hacer_para_antes_de_lanzar(falso, tmp_path, rompe, motivo):
    _, activos, trabajo = _run(tmp_path)
    with pytest.raises(obrero.ErrorDelObrero, match=motivo):
        obrero.ejecuta(rompe(activos), activos, trabajo)
    assert falso["trabajos"] == []


def test_sin_venv_escena_o_con_la_gpu_ocupada_no_se_lanza(falso, monkeypatch, tmp_path):
    _, activos, trabajo = _run(tmp_path)
    ops = [obrero.recorta("x", _crudo(activos, "x"))]
    monkeypatch.setattr(config, "ESCENA_PYTHON", str(tmp_path / "no-hay" / "python.exe"))
    with pytest.raises(obrero.ErrorDelObrero, match="requirements-escena"):
        obrero.ejecuta(ops, activos, trabajo)
    monkeypatch.setattr(config, "ESCENA_PYTHON", str(tmp_path / "python.exe"))

    def ocupada(*a, **k):
        raise ErrorDeRender("hay otro trabajo del estudio en la GPU (llama-server.exe)")

    monkeypatch.setattr(obrero, "exige_gpu_libre", ocupada)
    with pytest.raises(obrero.ErrorDelObrero, match="llama-server"):
        obrero.ejecuta(ops, activos, trabajo)
    assert falso["trabajos"] == []


def test_las_operaciones_mal_pedidas_paran_al_construirlas():
    with pytest.raises(obrero.ErrorDelObrero, match="no las dos"):
        obrero.recorta("x", "o.png", piezas=["a"], sitios={"a": (1, 2)})
    with pytest.raises(obrero.ErrorDelObrero, match="las dos cosas"):
        obrero.recorta("x", "o.png", piezas=["a", "b"], k_de="a")
    with pytest.raises(obrero.ErrorDelObrero, match="ninguna de sus figuras"):
        obrero.recorta("x", "o.png", piezas=["a", "b"], k_de="c", alto_k=10)


def test_el_trabajador_se_lanza_sin_las_claves_del_env_y_sin_red(monkeypatch, tmp_path):
    visto = {}

    class Proceso:
        """Lo que devuelve `subprocess.Popen`, sin lanzar nada: `_lanza` lo espera con su techo de tiempo."""

        pid = 999_999_991

        def __init__(self, args, **kwargs):
            visto.update(args=args, **kwargs)

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(obrero.subprocess, "Popen", Proceso)
    monkeypatch.setattr(config, "ESCENA_CERROJO_OBRERO", tmp_path / "obrero.cerrojo")
    monkeypatch.setenv("UNA_API_KEY_DE_PRUEBA", "secreto")
    obrero._lanza(tmp_path / "t.json", tmp_path / "r.json", tmp_path / "l.log")
    assert visto["args"][:2] == [config.ESCENA_PYTHON, str(config.OBRERO_ESCENA_WORKER)]
    assert visto["env"]["HF_HUB_OFFLINE"] == "1" and visto["env"]["TRANSFORMERS_OFFLINE"] == "1"
    assert "UNA_API_KEY_DE_PRUEBA" not in visto["env"]


def test_archivos_para_compone_mapea_cada_src_a_su_fichero(falso, tmp_path):
    _, activos, trabajo = _run(tmp_path)
    obrero.ejecuta([obrero.recorta("x", _crudo(activos, "x"))], activos, trabajo)
    mapa = obrero.archivos_para_compone(activos)
    assert mapa == {"assets/img/x.png": activos / "img" / "x.png"} and mapa["assets/img/x.png"].is_file()


# ------------------------------------------------------------------------------------------ la escala de cabezas
def _figuras_de_escala(tmp_path: Path) -> tuple[Path, dict]:
    activos = tmp_path / "activos"
    catalogo_de(
        activos,
        {
            "a_frente": (figura_rgba(180, 18), 0.9),
            "a_perfil": (figura_rgba(180, 18), 0.9),
            "a_saluda": (figura_rgba(200, 20), 1.0),
            "a_sentado": (figura_rgba(170, 29), 1.0),
            "a_sentado_s": (figura_rgba(170, 29), 1.0),
            "a_agacha": (figura_rgba(170, 20.6), 1.0),
            "b_frente": (figura_rgba(120, 30), 1.0),
        },
    )
    figuras = {
        "a_frente": obrero.Figura("a", "frente", True, None, True),
        "a_perfil": obrero.Figura("a", "perfil", True, None, True),
        "a_saluda": obrero.Figura("a", "frente", True, None, True),
        "a_sentado": obrero.Figura("a", "frente", False, None, True),
        "a_sentado_s": obrero.Figura("a", "frente", False, "a_sentado", True),
        "a_agacha": obrero.Figura("a", "frente", False, None, True),
        "b_frente": obrero.Figura("b", "frente", False, None, False),
    }
    return activos, figuras


def _datos_para_la_comprobacion(cat: dict, nombres: list[str]) -> dict:
    return {"planos": [{"actores": [{"id": "a1", "pj": "a", "posturas": {n: cat[n] for n in nombres}}]}]}


def test_la_escala_iguala_la_cabeza_y_la_comprobacion_de_f62b_la_da_por_buena(tmp_path):
    activos, figuras = _figuras_de_escala(tmp_path)
    informe = obrero.escala(activos, figuras, {"a": "a_perfil"})
    cat = obrero.lee_catalogo(activos)["imagenes"]
    assert cat["a_sentado"]["k0"] == 1.0 and cat["a_sentado"]["k"] == pytest.approx(1.45, rel=0.04)
    assert cat["a_sentado_s"]["k"] == cat["a_sentado"]["k"], "la variante hereda el factor"
    assert "k0" not in cat["a_agacha"] and cat["a_agacha"]["k"] == 1.0, "a un 3 % no se toca"
    assert cat["b_frente"]["cabeza_px"] is None and cat["b_frente"]["k"] == 1.0, "quien no se mide no se corrige"
    assert all(cat[n]["vista"] == figuras[n].vista and len(cat[n]["cabeza"]) == 4 for n in figuras)
    assert any("a_sentado" in linea for linea in informe)
    nombres = ["a_frente", "a_saluda", "a_sentado", "a_sentado_s", "a_agacha"]
    assert comprobaciones.escala_de_cabeza(_datos_para_la_comprobacion(cat, nombres)) == []
    # Control: la misma cabeza SIN la k corregida es el defecto que la comprobación de F6.2b tiene que ver.
    sin_corregir = {n: {**cat[n], "k": cat[n].get("k0", cat[n]["k"])} for n in nombres}
    defectos = comprobaciones.escala_de_cabeza(_datos_para_la_comprobacion(sin_corregir, nombres))
    assert {d.donde.split("/")[1] for d in defectos} == {"a_sentado", "a_sentado_s"}


def test_la_escala_dos_veces_da_lo_mismo(tmp_path):
    activos, figuras = _figuras_de_escala(tmp_path)
    obrero.escala(activos, figuras, {"a": "a_perfil"})
    una = obrero.lee_catalogo(activos)
    obrero.escala(activos, figuras, {"a": "a_perfil"})
    assert obrero.lee_catalogo(activos) == una


def test_la_escala_pide_la_figura_del_color_de_pelo(tmp_path):
    activos, figuras = _figuras_de_escala(tmp_path)
    with pytest.raises(obrero.ErrorDelObrero, match="color de pelo"):
        obrero.escala(activos, figuras, {"a": "a_de_otra_hoja"})


# ------------------------------------------------------------------------------------------ las teselas de ESRGAN
def _nearest_x4(t):
    import torch

    return torch.nn.functional.interpolate(t, scale_factor=4, mode="nearest")


def test_las_teselas_no_dejan_costuras():
    """Con una ampliación que no depende del contexto, trocear y fundir da exactamente la imagen entera ampliada."""
    pytest.importorskip("torch")  # no está en requirements.txt: sin él la prueba se salta, no falla (F6.2c, rec. 2)
    rng = np.random.default_rng(3)
    img = Image.fromarray(rng.integers(0, 256, (70, 100, 3), dtype=np.uint8))
    por_teselas = np.asarray(obrero_worker.escala_x4(img, _nearest_x4, 40, 8, "cpu", False))
    entera = np.asarray(img.resize((400, 280), Image.NEAREST))
    assert por_teselas.shape == entera.shape
    assert np.abs(por_teselas.astype(int) - entera.astype(int)).max() <= 1


def test_control_una_tesela_mal_colocada_se_nota():
    """Un «modelo» cuya salida depende de dónde cae la tesela (lo que haría un desplazamiento mal calculado)."""
    torch = pytest.importorskip("torch")

    def desplazado(t):
        x = _nearest_x4(t)
        return torch.roll(x, shifts=3, dims=3) if t.shape[-1] < 40 else x

    rng = np.random.default_rng(3)
    img = Image.fromarray(rng.integers(0, 256, (70, 100, 3), dtype=np.uint8))
    por_teselas = np.asarray(obrero_worker.escala_x4(img, desplazado, 40, 8, "cpu", False))
    entera = np.asarray(img.resize((400, 280), Image.NEAREST))
    assert np.abs(por_teselas.astype(int) - entera.astype(int)).max() > 10


def test_una_tesela_menor_que_dos_solapes_no_se_admite():
    pytest.importorskip("torch")
    with pytest.raises(ValueError):
        obrero_worker.escala_x4(Image.new("RGB", (10, 10)), _nearest_x4, 40, 20, "cpu", False)


# ------------------------------------------------------------------------------------------ las guardas del trabajador
def _python(codigo: str, python: str = sys.executable, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([python, "-c", codigo], capture_output=True, text=True, cwd=str(RAIZ), timeout=120, env=env)


def test_sin_red_corta_lo_que_no_es_loopback_y_deja_loopback():
    codigo = (
        "import socket\n"
        "from lib.escena.obrero_worker import _sin_red\n"
        "_sin_red()\n"
        "srv = socket.socket(); srv.bind(('127.0.0.1', 0)); srv.listen(1)\n"
        "c = socket.create_connection(srv.getsockname(), timeout=5); c.close(); print('LOOPBACK-OK')\n"
        "for destino in (('192.0.2.1', 80), ('example.com', 443)):\n"
        "    try:\n"
        "        socket.create_connection(destino, timeout=2); print('SALIO', destino)\n"
        "    except OSError as e:\n"
        "        print('CORTADA' if '[sin-red]' in str(e) else 'OTRO: ' + str(e))\n"
    )
    r = _python(codigo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["LOOPBACK-OK", "CORTADA", "CORTADA"], r.stdout


def test_una_operacion_desconocida_para_antes_de_cargar_nada(tmp_path):
    trabajo = tmp_path / "t.json"
    trabajo.write_text(json.dumps({"operaciones": [{"op": "baila", "nombre": "x"}]}), encoding="utf-8")
    r = subprocess.run(
        [
            sys.executable,
            str(config.OBRERO_ESCENA_WORKER),
            "--trabajo",
            str(trabajo),
            "--resultado",
            str(tmp_path / "r"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode != 0 and "no sabe hacer" in r.stderr


@pytest.mark.skipif(
    not Path(config.ESCENA_PYTHON).is_file(), reason="no está .venv-escena (spikes/requirements-escena.txt)"
)
def test_sin_cuda_el_trabajador_no_arranca(tmp_path):
    """En `.venv-escena` con la GPU escondida: el trabajador se niega en vez de ir a CPU a paso de tortuga."""
    trabajo = tmp_path / "t.json"
    trabajo.write_text(
        json.dumps({"operaciones": [{"op": "recorta", "nombre": "x", "origen": "x.png"}]}), encoding="utf-8"
    )
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1"}
    r = subprocess.run(
        [
            config.ESCENA_PYTHON,
            str(config.OBRERO_ESCENA_WORKER),
            "--trabajo",
            str(trabajo),
            "--resultado",
            str(tmp_path / "r.json"),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    assert r.returncode != 0 and "torch.cuda.is_available() == False" in r.stderr


# ------------------------------------------------------------------------------ el factor de escala, exacto (F6.2d)
def _catalogo_con_piezas() -> dict:
    """La figura `a` con lo que SAM separó de ella, y la figura `a_manos` con su base: dos figuras, una por delante."""
    return {
        "a": {"k": 1.0},
        "a_base": {"k": 1.0, "de": "a"},
        "a_cola": {"k": 1.0, "off": [10, -40], "de": "a"},
        "a_manos": {"k": 1.0},
        "a_manos_base": {"k": 1.0, "de": "a_manos"},
    }


def test_el_factor_de_una_figura_va_a_sus_piezas_y_a_nada_mas():
    cat = _catalogo_con_piezas()
    obrero._aplica(cat, "a", 1.2)
    assert {n: d["k"] for n, d in cat.items()} == {
        "a": 1.2,
        "a_base": 1.2,
        "a_cola": 1.2,
        "a_manos": 1.0,
        "a_manos_base": 1.0,
    }
    assert cat["a"]["k0"] == 1.0 and "k0" not in cat["a_manos_base"]


def test_control_por_el_prefijo_el_factor_se_colaba_en_la_base_de_otra_figura():
    """Auditoría de F6.2c, recomendación 5: la regla de antes (prefijo `a_` y `_base` u `off`) tocaba `a_manos_base`."""

    def regla_de_antes(n: str, d: dict) -> bool:
        return n == "a" or (n.startswith("a_") and ("off" in d or n.endswith("_base")))

    tocadas_antes = {n for n, d in _catalogo_con_piezas().items() if regla_de_antes(n, d)}
    assert "a_manos_base" in tocadas_antes
    cat = _catalogo_con_piezas()
    obrero._aplica(cat, "a", 1.2)
    assert {n for n, d in cat.items() if d["k"] != 1.0} == tocadas_antes - {"a_manos_base"}


def test_lo_que_separa_el_obrero_dice_de_que_figura_sale(falso, tmp_path):
    _, activos, trabajo = _run(tmp_path)
    obrero.ejecuta([obrero.recorta("calle", _crudo(activos, "calle"))], activos, trabajo)
    base = obrero.lee_catalogo(activos)["imagenes"]["calle"]
    pieza = {"nombre": "arbol", "caja": [0, 0, 10, 10], "pivote": [5, 10]}
    obrero.ejecuta([obrero.separa("calle", "calle.png", base, [pieza], quita_de_la_base=False)], activos, trabajo)
    assert obrero.lee_catalogo(activos)["imagenes"]["calle_arbol"]["de"] == "calle"


# ------------------------------------------------------------------------------ el cerrojo del obrero (F6.2d)
def test_mientras_corre_el_trabajador_tiene_tomado_el_cerrojo_y_al_acabar_lo_suelta(tmp_path, monkeypatch):
    """Auditoría de F6.2c, recomendación 3, con un trabajador de verdad (un Python que mira el cerrojo y acaba)."""
    cerrojo = tmp_path / "obrero.cerrojo"
    trabajador = tmp_path / "trabajador.py"
    trabajador.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "trabajo = json.loads(Path(sys.argv[sys.argv.index('--trabajo') + 1]).read_text(encoding='utf-8'))\n"
        "cerrojo = Path(trabajo['cerrojo'])\n"
        "visto = {'existe': cerrojo.exists(), 'datos': json.loads(cerrojo.read_text()) if cerrojo.exists() else None}\n"
        "Path(sys.argv[sys.argv.index('--resultado') + 1]).write_text(json.dumps(visto), encoding='utf-8')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "ESCENA_PYTHON", sys.executable)
    monkeypatch.setattr(config, "OBRERO_ESCENA_WORKER", trabajador)
    monkeypatch.setattr(config, "ESCENA_CERROJO_OBRERO", cerrojo)
    trabajo, resultado = tmp_path / "t.json", tmp_path / "r.json"
    trabajo.write_text(json.dumps({"cerrojo": str(cerrojo)}), encoding="utf-8")
    assert obrero._lanza(trabajo, resultado, tmp_path / "l.log") == 0
    visto = json.loads(resultado.read_text(encoding="utf-8"))
    assert visto["existe"] and visto["datos"]["que"].startswith("obrero de escena")
    assert not cerrojo.exists(), "al acabar, el cerrojo se suelta"
