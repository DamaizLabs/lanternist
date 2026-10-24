"""La biblioteca del canal crece sola tras la parada 1 (F6.4b, decisión del 29-09, addendum fila 208).

Con un canal ficticio en una carpeta temporal y sin GPU: ComfyUI, el obrero, whisper, las capturas y el render son
los falsos de las otras pruebas del motor de escena. Ningún perfil ni ninguna biblioteca de verdad se toca.

Lo que se prueba, cada cosa con su control negativo:

- **Por el pipeline**: un episodio genera tres imágenes y su escena usa dos; hasta que pasa la parada 1
  (`--stage escena`) la biblioteca no cambia —ni con otro `--run-all`— y el episodio siguiente no las encuentra; al
  pasarla entran las dos que usa la escena, con su procedencia y su sha256, y **la tercera no**, como una imagen
  rechazada en la parada 1 que el guion ya no pide (revisión de F6.4b, R4). El episodio siguiente las trae sin pedir
  nada a Qwen. Volver a lanzar la etapa no duplica nada.
- **Lo que ya está no se vuelve a pedir**: un guion que pide a Qwen una imagen de la biblioteca para antes de la GPU;
  el episodio que la puso sí puede rehacerla.
- **`biblia.incorpora` a solas**: solo entra lo que usa el guion, con las piezas de sus figuras; lo rehecho por el
  mismo episodio se actualiza; lo de otro episodio con el mismo nombre o el mismo fichero no se pisa; lo que no tiene
  procedencia completa no entra; y un canal sin biblioteca la crea con su primer episodio, que otro puede traer.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image
from test_activos import comfy  # noqa: F401  (ComfyUI falso)
from test_biblia import PIEZA, biblioteca_de_prueba
from test_etapas import gpu  # noqa: F401  (whisper, capturas y render falsos)
from test_obrero import falso  # noqa: F401  (el obrero falso)
from utiles_activos import registro_de_qwen
from utiles_escena import CATALOGO_PRUEBA, LAMINAS_PRUEBA
from utiles_pipeline import canal_de_prueba, guion_en_el_canal, perfil_de_prueba, prepara_run

from lib import config, pagina_local, provenance
from lib import state as run_state
from lib.escena import biblia, etapas, obrero, recorte

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="el sonido del motor de escena usa ffmpeg")

# Lo que genera el guion `nuevas.py`, y lo que usa su escena: `o_boli` se generó y el guion ya no la pide.
EN_LA_ESCENA = ["o_taza", "o_llave"]
NO_LA_USA = "o_boli"
ESRGAN = "https://github.com/xinntao/Real-ESRGAN"


def _sha(ruta: Path) -> str:
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def foto(carpeta: Path) -> dict[str, str]:
    """El sha256 de cada fichero de una carpeta: si algo se añade, se quita o cambia un byte, la foto cambia."""
    if not carpeta.exists():
        return {}
    return {p.relative_to(carpeta).as_posix(): _sha(p) for p in sorted(carpeta.rglob("*")) if p.is_file()}


def _estado(run_id: str) -> dict:
    return {e: d["status"] for e, d in run_state.load_run(run_id)["stages"].items()}


# ------------------------------------------------------------------------------------------ por el pipeline
@pytest.fixture
def estudio(tmp_path, monkeypatch, gpu, comfy, falso):  # noqa: F811
    """El pipeline con el canal ficticio, su biblioteca de partida y una hoja para sustituir por objetos."""
    import pipeline

    perfil = perfil_de_prueba()
    canal = canal_de_prueba(tmp_path / "canal", perfil)
    monkeypatch.setattr(run_state, "STATE_DIR", tmp_path / "estado")
    monkeypatch.setattr(run_state, "CANAL_VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(run_state, "CANAL_ACTIVO", "canal-de-prueba")
    for nombre, valor in (("CANAL_DIR", canal), ("CANAL_PERFIL", perfil), ("SUBTITLE_LANG", "en")):
        monkeypatch.setattr(config, nombre, valor)
    monkeypatch.setattr(config, "CANAL_ACTIVO", "canal-de-prueba")
    monkeypatch.setattr(provenance, "ASSETS_MIRROR_DIR", tmp_path / "copia-versionada")
    monkeypatch.setattr(pagina_local, "abre", lambda ruta: True)

    def hecha(nombre):
        return lambda run_id: run_state.update_stage(run_id, nombre, "complete", "hecha en la prueba")

    for nombre in ("images", "tts", "thumbnail"):
        monkeypatch.setattr(pipeline, f"stage_{nombre}", hecha(nombre))
    monkeypatch.setattr(pipeline, "_abre_la_guia", lambda state: None)
    hoja = config.escena_del_canal(canal) / "biblia" / "hoja.png"
    hoja.parent.mkdir(parents=True)
    Image.new("RGB", (320, 200), recorte.CROMA).save(hoja)

    def nuevo_run(plantilla: str, titulo: str) -> tuple[str, Path]:
        """Un episodio con su voz y su alineación, sin imágenes propias: lo que use lo genera o lo trae."""
        state = run_state.create_run(titulo, "manual", "")
        run = prepara_run(Path(state["output_dir"]), LAMINAS_PRUEBA)
        if not (config.biblioteca_del_canal(canal) / "catalogo.json").is_file():
            biblioteca_de_prueba(canal, run)  # la biblioteca de partida: las imágenes de siempre del episodio de prueba
        else:
            shutil.rmtree(config.activos_del_run(run))
        guion_en_el_canal(canal, state["run_id"], plantilla)
        return state["run_id"], run

    return {"pipeline": pipeline, "canal": canal, "nuevo_run": nuevo_run, "comfy": comfy}


def test_la_biblioteca_crece_al_pasar_la_parada_1_y_el_episodio_siguiente_la_reutiliza(estudio):
    p, canal, comfy_ = estudio["pipeline"], estudio["canal"], estudio["comfy"]
    run_a, dir_a = estudio["nuevo_run"]("nuevas", "Episodio que genera")
    run_b, dir_b = estudio["nuevo_run"]("reutiliza", "Episodio siguiente")
    carpeta = config.biblioteca_del_canal(canal)
    antes, catalogo_antes = foto(carpeta), biblia.lee(canal).catalogo

    # El episodio A llega a la parada 1 con sus tres imágenes nuevas (dos generaciones: un objeto y una lámina de dos).
    p.run_all(run_a, sin_subida=True)
    assert _estado(run_a)["activos"] == "complete" and _estado(run_a)["escena"] == "pending"
    assert len(comfy_["grafos"]) == 2
    assert {*EN_LA_ESCENA, NO_LA_USA} <= set(obrero.lee_catalogo(config.activos_del_run(dir_a))["imagenes"])
    # Control: sin pasar la parada 1 no entra nada, tampoco con otro --run-all...
    assert foto(carpeta) == antes
    p.run_all(run_a, sin_subida=True)
    assert foto(carpeta) == antes
    # ...y el episodio siguiente no las encuentra: la biblioteca aún no las tiene.
    with pytest.raises(biblia.ErrorDeBiblioteca, match="no están en la biblioteca"):
        p.run_all(run_b, sin_subida=True)
    assert _estado(run_b)["activos"] == "blocked"

    # A pasa la parada 1: las imágenes nuevas que usa su escena entran en la biblioteca, cada una con su procedencia.
    info = p.stage_escena(run_a)
    hecho = info["biblioteca"]
    assert hecho["entran"] == EN_LA_ESCENA and hecho["actualizadas"] == []
    # Control (R4): la que el guion ya no usa se queda fuera, y se dice.
    assert list(hecho["no_entran"]) == [NO_LA_USA] and "no la usa" in hecho["no_entran"][NO_LA_USA]
    assert set(hecho["ya_estaban"]) == set(CATALOGO_PRUEBA) | set(PIEZA), "lo que trajo no cuenta como nuevo"
    bib = biblia.lee(canal)
    assert NO_LA_USA not in bib.catalogo and not (carpeta / "img" / f"{NO_LA_USA}.png").exists()
    catalogo_a = obrero.lee_catalogo(config.activos_del_run(dir_a))["imagenes"]
    for nombre in EN_LA_ESCENA:
        fichero = bib.fichero(nombre)
        ficha = bib.procedencia[f"img/{fichero.name}"]
        assert (
            ficha["sha256"]
            == _sha(fichero)
            == _sha(obrero.archivo_de(config.activos_del_run(dir_a), catalogo_a[nombre]))
        )
        assert ficha["licencia"].startswith("Apache-2.0") and "BSD-3-Clause" in ficha["licencia"]
        assert ficha["url"].startswith("https://huggingface.co/") and ficha["url"].endswith(ESRGAN)
        assert ficha["fuente"].startswith(f"generada en el episodio {run_a}") and ficha["episodio"] == run_a
        assert ficha["modelo"].endswith("Real-ESRGAN x4plus anime 6B")
        # El crudo se queda en el run (fuera de git): su sha256, su semilla y su prompt, para poder regenerarlo.
        crudo = config.activos_del_run(dir_a) / "crudo" / ficha["crudo"]["fichero"]
        assert ficha["crudo"]["sha256"] == _sha(crudo) and ficha["crudo"]["seed"] == 7
        assert "Nobody in the picture" in ficha["crudo"]["prompt"]
        assert bib.catalogo[nombre] == catalogo_a[nombre]
        assert bib.indice[nombre]["tipo"] == "objeto" and bib.indice[nombre]["episodio"] == run_a
    assert "o_varios" not in bib.catalogo, "la lámina de objetos no es una imagen: lo son sus piezas"
    # Lo que ya estaba sigue igual y no se duplica: las mismas imágenes con los mismos bytes, más las dos nuevas.
    despues = foto(carpeta)
    assert {k: v for k, v in antes.items() if k.startswith("img/")}.items() <= despues.items()
    assert len([k for k in despues if k.startswith("img/")]) == len([k for k in antes if k.startswith("img/")]) + 2
    assert all(bib.catalogo[n] == e for n, e in catalogo_antes.items())
    pagina = info["pagina"].read_text(encoding="utf-8")
    assert "Biblioteca del canal (2 nueva(s), 0 actualizada(s))" in pagina and f"<b>{NO_LA_USA}</b> no entra" in pagina
    # Volver a lanzar la etapa (una corrección tras la parada 2) no duplica ni reescribe nada.
    otra = p.stage_escena(run_a)["biblioteca"]
    assert otra["entran"] == otra["actualizadas"] == [] and set(EN_LA_ESCENA) <= set(otra["ya_estaban"])
    assert foto(carpeta) == despues

    # El episodio B las trae de la biblioteca y no pide nada a Qwen.
    grafos = len(comfy_["grafos"])
    p.run_all(run_b, sin_subida=True)
    assert _estado(run_b)["activos"] == "complete" and len(comfy_["grafos"]) == grafos
    catalogo_b = obrero.lee_catalogo(config.activos_del_run(dir_b))["imagenes"]
    assert all(catalogo_b[n] == bib.catalogo[n] for n in EN_LA_ESCENA)
    informe = provenance.sync(dir_b, verbose=False)
    assert informe["cuadra"] and informe["licencias_por_cerrar"] == [], informe
    taza = next(a for a in provenance.read_ledger(dir_b)["assets"] if a["id"] == "activos/img/o_taza.png")
    assert "biblioteca del canal" in taza["fuente"] and taza["licencia"].startswith("Apache-2.0")
    assert taza["url"].endswith(ESRGAN)
    # Y al pasar su propia parada 1 no vuelve a meter lo que trajo.
    assert p.stage_escena(run_b)["biblioteca"]["entran"] == []
    assert foto(carpeta) == despues


def test_lo_que_ya_esta_en_la_biblioteca_no_se_pide_a_qwen_y_el_episodio_que_lo_puso_si_puede_rehacerlo(estudio):
    p, comfy_ = estudio["pipeline"], estudio["comfy"]
    run_a, _ = estudio["nuevo_run"]("nuevas", "Episodio que genera")
    p.run_all(run_a, sin_subida=True)
    p.stage_escena(run_a)
    grafos = len(comfy_["grafos"])
    # Otro episodio con el mismo guion pediría a Qwen otra vez las dos que entraron: para antes de tocar la GPU.
    run_c, _ = estudio["nuevo_run"]("nuevas", "Episodio que repite")
    with pytest.raises(etapas.ErrorDeEtapa, match="ya están en la biblioteca del canal") as error:
        p.run_all(run_c, sin_subida=True)
    assert all(f"{n} (de {run_a})" in str(error.value) for n in EN_LA_ESCENA) and "Lote.biblioteca" in str(error.value)
    assert NO_LA_USA not in str(error.value), "la que no entró se puede pedir: la biblioteca no la tiene"
    assert len(comfy_["grafos"]) == grafos and _estado(run_c)["activos"] == "blocked"
    # Control: el episodio que las puso sí puede rehacer su etapa de activos (es corregirlas).
    p.stage_activos(run_a)
    assert _estado(run_a)["activos"] == "complete"


# ------------------------------------------------------------------------------------------ biblia.incorpora a solas
def imagen_del_episodio(run: Path, nombre: str, color: tuple, *, fichero: str | None = None, origen: bool = True):
    """Una imagen como la deja la etapa activos: su crudo con el registro de Qwen y su recorte con el del obrero."""
    dir_activos = config.activos_del_run(run)
    crudo = dir_activos / "crudo" / f"{nombre}-7.png"
    crudo.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), recorte.CROMA).save(crudo)
    if origen:
        registro = {**registro_de_qwen(crudo), "activo": nombre, "tipo_activo": "postura", "que": "waving"}
        provenance.anade_registros(crudo.parent / provenance.IMAGE_RECORDS_FILENAME, [registro])
    img = dir_activos / "img" / (fichero or f"{nombre}.png")
    img.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (40, 60), (*color, 255)).save(img)
    provenance.anade_registros(
        img.parent / provenance.IMAGE_RECORDS_FILENAME,
        [obrero.registro_del_derivado(img, crudo, "recorta", {}, ancla=run)],
    )
    catalogo = obrero.lee_catalogo(dir_activos)
    catalogo["imagenes"][nombre] = {"src": f"assets/img/{img.name}", "w": 40, "h": 60, "ax": 20, "ay": 60, "k": 1.0}
    obrero.guarda_catalogo(dir_activos, catalogo)
    return img


def _incorpora(canal: Path, run: Path, episodio: str, usadas) -> dict:
    return biblia.incorpora(canal, config.activos_del_run(run), episodio=episodio, usadas=usadas)


def test_un_canal_sin_biblioteca_la_crea_con_su_primer_episodio_y_otro_la_trae(tmp_path):
    canal, run = tmp_path / "canal", tmp_path / "videos" / "ep-1"
    imagen_del_episodio(run, "ana_saluda", (200, 80, 40))
    assert not config.biblioteca_del_canal(canal).exists()
    hecho = _incorpora(canal, run, "ep-1", ["ana_saluda"])
    assert hecho["entran"] == ["ana_saluda"]
    bib = biblia.lee(canal)
    assert bib.indice["ana_saluda"] == {
        "episodio": "ep-1",
        "tipo": "postura",
        "que": "waving",
        "crudo": "ana_saluda-7.png",
    }
    # El formato de los JSON es el de los que importó F6.3 (indent=1): un diff de git legible.
    assert (bib.carpeta / "catalogo.json").read_text(encoding="utf-8").startswith('{\n "imagenes": {\n  "ana_saluda"')
    # Lo que entra se puede traer: la ficha tiene todo lo que `trae` exige (decisión 5).
    otro = tmp_path / "videos" / "ep-2"
    assert biblia.trae(canal, ["ana_saluda"], config.activos_del_run(otro)) == ["ana_saluda"]
    assert provenance.sync(otro, verbose=False)["cuadra"]


def test_solo_entra_lo_que_usa_el_guion_con_las_piezas_de_sus_figuras(tmp_path):
    """R4 de la revisión: el catálogo del run solo crece, así que una imagen rechazada sigue en él."""
    canal, run = tmp_path / "canal", tmp_path / "videos" / "ep-1"
    imagen_del_episodio(run, "ana_saluda", (200, 80, 40))
    imagen_del_episodio(run, "ana_saluda_cola", (10, 10, 200))  # una pieza que SAM separó de ana_saluda...
    catalogo = obrero.lee_catalogo(config.activos_del_run(run))
    catalogo["imagenes"]["ana_saluda_cola"].update(off=[5, -20], de="ana_saluda")  # ...y que se mece con ella
    obrero.guarda_catalogo(config.activos_del_run(run), catalogo)
    imagen_del_episodio(run, "ana_rechazada", (90, 90, 90))  # el usuario la rechazó y el guion ya no la pide
    hecho = _incorpora(canal, run, "ep-1", ["ana_saluda"])
    assert hecho["entran"] == ["ana_saluda", "ana_saluda_cola"], "la pieza viaja con su figura, como en `trae`"
    assert list(hecho["no_entran"]) == ["ana_rechazada"] and "no la usa" in hecho["no_entran"]["ana_rechazada"]
    bib = biblia.lee(canal)
    assert "ana_rechazada" not in bib.catalogo and "img/ana_rechazada.png" not in bib.procedencia
    assert bib.indice["ana_saluda_cola"]["tipo"] == "pieza"
    # Control: con el guion que sí la usa, entra.
    assert _incorpora(canal, run, "ep-1", ["ana_saluda", "ana_rechazada"])["entran"] == ["ana_rechazada"]


def test_lo_que_sale_de_una_lamina_del_episodio_no_entra_en_la_biblioteca(tmp_path):
    """F6.6: un canal en tinta pone en escena las láminas de cada run; no valen para otro episodio y no van a git."""
    canal, run = tmp_path / "canal", tmp_path / "videos" / "ep-1"
    imagen_del_episodio(run, "lamina_01", (200, 180, 140))
    imagen_del_episodio(run, "lamina_01_peana", (90, 90, 90))
    catalogo = obrero.lee_catalogo(config.activos_del_run(run))
    for nombre in ("lamina_01", "lamina_01_peana"):
        catalogo["imagenes"][nombre]["del_episodio"] = True
    obrero.guarda_catalogo(config.activos_del_run(run), catalogo)
    hecho = _incorpora(canal, run, "ep-1", ["lamina_01", "lamina_01_peana"])
    assert hecho["entran"] == [] and set(hecho["no_entran"]) == {"lamina_01", "lamina_01_peana"}
    assert "lámina de este episodio" in hecho["no_entran"]["lamina_01"]
    assert not config.biblioteca_del_canal(canal).exists(), "no se crea ni la carpeta"
    # Control: sin la marca, la misma imagen entra.
    catalogo["imagenes"]["lamina_01"].pop("del_episodio")
    obrero.guarda_catalogo(config.activos_del_run(run), catalogo)
    assert _incorpora(canal, run, "ep-1", ["lamina_01"])["entran"] == ["lamina_01"]


def test_lo_que_rehace_el_mismo_episodio_se_actualiza(tmp_path):
    canal, run = tmp_path / "canal", tmp_path / "videos" / "ep-1"
    imagen_del_episodio(run, "ana_saluda", (200, 80, 40))
    _incorpora(canal, run, "ep-1", ["ana_saluda"])
    # el usuario pidió otra semilla en la parada 2; el episodio rehízo la imagen y volvió a pasar la parada 1.
    img = imagen_del_episodio(run, "ana_saluda", (40, 80, 200))
    hecho = _incorpora(canal, run, "ep-1", ["ana_saluda"])
    assert hecho["actualizadas"] == ["ana_saluda"] and hecho["entran"] == []
    bib = biblia.lee(canal)
    assert _sha(bib.fichero("ana_saluda")) == _sha(img) == bib.procedencia["img/ana_saluda.png"]["sha256"]


def test_control_lo_de_otro_episodio_con_el_mismo_nombre_o_el_mismo_fichero_no_se_pisa(tmp_path):
    canal = tmp_path / "canal"
    uno, dos = tmp_path / "videos" / "ep-1", tmp_path / "videos" / "ep-2"
    imagen_del_episodio(uno, "ana_saluda", (200, 80, 40))
    _incorpora(canal, uno, "ep-1", ["ana_saluda"])
    carpeta = config.biblioteca_del_canal(canal)
    antes = foto(carpeta)
    # Otro episodio con OTRA ana_saluda, y otra imagen cuyo fichero se llama como el de la primera.
    imagen_del_episodio(dos, "ana_saluda", (40, 80, 200))
    imagen_del_episodio(dos, "bo_saluda", (10, 200, 10), fichero="ana_saluda.png")
    hecho = _incorpora(canal, dos, "ep-2", ["ana_saluda", "bo_saluda"])
    assert hecho["entran"] == [] and set(hecho["no_entran"]) == {"ana_saluda", "bo_saluda"}
    assert "ya tiene otra «ana_saluda» (de ep-1)" in hecho["no_entran"]["ana_saluda"]
    assert "img/ana_saluda.png es el de otra imagen" in hecho["no_entran"]["bo_saluda"]
    assert foto(carpeta) == antes, "la biblioteca no cambia ni un byte"
    # Y lo que la etapa activos mira antes de generar: para ep-2 es ajena; para ep-1, no (es suya).
    assert biblia.ajenas(canal, ["ana_saluda", "nueva"], episodio="ep-2") == {"ana_saluda": "ep-1"}
    assert biblia.ajenas(canal, ["ana_saluda"], episodio="ep-1") == {}


def test_un_nombre_nuevo_con_el_fichero_identico_de_otro_episodio_dice_ese_episodio_en_el_indice(tmp_path):
    """R5 de la revisión: el índice y la procedencia dicen lo mismo de quién generó el fichero."""
    canal = tmp_path / "canal"
    uno, dos = tmp_path / "videos" / "ep-1", tmp_path / "videos" / "ep-2"
    imagen_del_episodio(uno, "ana_saluda", (200, 80, 40))
    _incorpora(canal, uno, "ep-1", ["ana_saluda"])
    imagen_del_episodio(dos, "ana_saluda_otra", (200, 80, 40), fichero="ana_saluda.png")  # los mismos bytes
    assert _incorpora(canal, dos, "ep-2", ["ana_saluda_otra"])["entran"] == ["ana_saluda_otra"]
    bib = biblia.lee(canal)
    assert bib.indice["ana_saluda_otra"]["episodio"] == bib.procedencia["img/ana_saluda.png"]["episodio"] == "ep-1"


@pytest.mark.parametrize("rompe", ["sin_registro", "origen_sin_registro", "sin_url"])
def test_control_lo_que_no_tiene_procedencia_completa_no_entra(tmp_path, rompe):
    canal, run = tmp_path / "canal", tmp_path / "videos" / "ep-1"
    img = imagen_del_episodio(run, "ana_saluda", (200, 80, 40), origen=rompe != "origen_sin_registro")
    sidecar = img.parent / provenance.IMAGE_RECORDS_FILENAME
    if rompe == "sin_registro":
        sidecar.unlink()
    elif rompe == "sin_url":
        registros = json.loads(sidecar.read_text(encoding="utf-8"))
        registros[-1]["url"] = None
        sidecar.write_text(json.dumps(registros), encoding="utf-8")
    hecho = _incorpora(canal, run, "ep-1", ["ana_saluda"])
    motivo = {"sin_registro": "no tiene registro", "origen_sin_registro": "por cerrar", "sin_url": "url"}[rompe]
    assert hecho["entran"] == [] and motivo in hecho["no_entran"]["ana_saluda"]
    assert not config.biblioteca_del_canal(canal).exists(), "sin nada que entre, ni se crea la biblioteca"
