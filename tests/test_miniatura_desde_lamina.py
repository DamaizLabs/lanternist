"""La miniatura sacada de una LÁMINA del run (10-09), con su procedencia y su gate.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_miniatura_desde_lamina.py

**De dónde sale.** Se rechazó la miniatura generada del episodio 1 —«no es un ataúd, es una caja de
hierro con un candado»— y se decidió el método: «coge una imagen de una de las láminas, conviértela en
miniatura y ponle el título… no tienes que generar nada». **Y el 12-09, después de que el episodio 2
repitiera el fallo —«una jaula de pájaro con un hombre sin cabeza dentro… en el episodio 1 te pasó lo
mismo»—, dejó de ser una opción: «hazlo obligatorio, la miniatura siempre de una lámina».** La etapa se
para sin `thumbnail_lamina` y `thumbnail_prompt` ya no es alternativa (addendum fila 156).

Estas pruebas fijan las tres cosas que hacen que eso no sea un atajo:

1. La lámina se copia y el recorte y el texto **siguen pasando por lo mismo** que una miniatura generada.
2. La procedencia de `thumbnail.png` **se sustituye**, no se acumula: la entrada que dejó una generación
   anterior describe un fichero que ya no existe (decisión cerrada 5).
3. Una lámina que no existe **para la etapa** en vez de dejar el vídeo sin miniatura, que es el defecto
   que originó F3.6.
"""

import json
from pathlib import Path

import pytest
from PIL import Image

from lib import config, miniatura

# La fuente del texto la declara el canal (OC1.4): aquí, la del canal de ejemplo, de la biblioteca del estudio.
ANTON = config.ESCENA_FUENTES_DIR / "Anton-Regular.ttf"


def _run(tmp_path: Path, laminas: int = 2) -> Path:
    """Un run mínimo: sus láminas y el registro de procedencia que dejó el adaptador de imagen."""
    (tmp_path / "slides").mkdir()
    registro = []
    for n in range(1, laminas + 1):
        ruta = tmp_path / "slides" / f"slide-{n:02d}.png"
        Image.new("RGB", (1344, 768), (40 * n, 60, 90)).save(ruta)
        registro.append(
            {
                "file": str(ruta),
                "workflow": "qwen-2512-lightning-tinta",
                "modelo": "Qwen-Image GGUF Q3_K_M + LoRA Lightning 8 pasos",
                "pesos": ["unet/qwen-image-Q3_K_M.gguf"],
                "licencia": "Apache-2.0 (Qwen-Image y Qwen-Image-Lightning) — uso comercial permitido",
                "prompt": f"lámina {n}",
                "origen": "generado en local con ComfyUI (127.0.0.1)",
            }
        )
    (tmp_path / "slides" / miniatura.REGISTRO_DE_IMAGENES).write_text(
        json.dumps(registro, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


# --- la declaración vive en el guion, y se valida ---------------------------------------------


def test_sin_declaracion_el_lector_devuelve_None_y_es_la_etapa_quien_para():
    """`lamina_declarada` sigue siendo un LECTOR: no lanza por ausencia, informa de ella.

    Quien convierte esa ausencia en una parada es `stage_thumbnail`, y está probado más abajo. Separarlo
    es lo que deja leer el campo desde un script o un test sin montar media etapa.
    """
    assert miniatura.lamina_declarada({}) is None
    assert miniatura.lamina_declarada({"thumbnail_lamina": None}) is None
    assert miniatura.lamina_declarada({"thumbnail_lamina": ""}) is None


def test_la_declaracion_es_el_numero_de_lamina():
    assert miniatura.lamina_declarada({"thumbnail_lamina": 1}) == 1
    assert miniatura.lamina_declarada({"thumbnail_lamina": "7"}) == 7


@pytest.mark.parametrize("valor", ["slide-01.png", "la primera", 0, -3, {}])
def test_una_declaracion_que_no_es_un_numero_de_lamina_se_rechaza(valor):
    with pytest.raises(ValueError, match=miniatura.CLAVE_LAMINA):
        miniatura.lamina_declarada({"thumbnail_lamina": valor})


# --- la copia y su procedencia ----------------------------------------------------------------


def test_la_miniatura_es_la_lamina_pedida_pixel_a_pixel(tmp_path):
    run = _run(tmp_path)
    destino = run / "thumbnail.png"
    datos = miniatura.desde_lamina(run, 1, destino)
    assert datos["lamina"] == 1 and Path(datos["origen"]).name == "slide-01.png"
    original = Image.open(run / "slides" / "slide-01.png").convert("RGB")
    assert list(Image.open(destino).convert("RGB").getdata()) == list(original.getdata())


def test_la_procedencia_hereda_el_modelo_de_la_lamina_y_dice_de_cual_sale(tmp_path):
    run = _run(tmp_path)
    miniatura.desde_lamina(run, 2, run / "thumbnail.png")
    entradas = json.loads((run / miniatura.REGISTRO_DE_IMAGENES).read_text(encoding="utf-8"))
    assert len(entradas) == 1
    entrada = entradas[0]
    assert Path(entrada["file"]).name == "thumbnail.png"
    assert "slide-02.png" in entrada["origen"] and "sin generación" in entrada["origen"]
    assert entrada["licencia"].startswith("Apache-2.0")
    assert entrada["pesos"] == ["unet/qwen-image-Q3_K_M.gguf"]


def test_la_entrada_de_una_miniatura_ANTERIOR_se_sustituye_y_no_se_acumula(tmp_path):
    """Control negativo del defecto que se quiere evitar: dos entradas para el mismo fichero, una falsa."""
    run = _run(tmp_path)
    (run / miniatura.REGISTRO_DE_IMAGENES).write_text(
        json.dumps(
            [
                {"file": str(run / "thumbnail.png"), "origen": "generado en local con ComfyUI (127.0.0.1)"},
                {"file": str(run / "otra-cosa.png"), "origen": "generado en local con ComfyUI (127.0.0.1)"},
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    miniatura.desde_lamina(run, 1, run / "thumbnail.png")
    entradas = json.loads((run / miniatura.REGISTRO_DE_IMAGENES).read_text(encoding="utf-8"))
    de_la_miniatura = [e for e in entradas if Path(e["file"]).name == "thumbnail.png"]
    assert len(de_la_miniatura) == 1, "la entrada vieja describía un fichero que ya no existe"
    assert "slide-01.png" in de_la_miniatura[0]["origen"]
    assert any(Path(e["file"]).name == "otra-cosa.png" for e in entradas), "no se toca lo ajeno"


def test_una_lamina_que_no_existe_para_la_etapa_y_dice_las_que_hay(tmp_path):
    run = _run(tmp_path, laminas=2)
    with pytest.raises(FileNotFoundError, match="slide-09.png"):
        miniatura.desde_lamina(run, 9, run / "thumbnail.png")
    with pytest.raises(FileNotFoundError, match="slide-01.png, slide-02.png"):
        miniatura.desde_lamina(run, 9, run / "thumbnail.png")


def test_sin_registro_de_laminas_la_licencia_no_se_inventa(tmp_path):
    """Si no hay registro del que heredar, se dice de dónde sale en vez de firmar una licencia."""
    run = _run(tmp_path)
    (run / "slides" / miniatura.REGISTRO_DE_IMAGENES).unlink()
    datos = miniatura.desde_lamina(run, 1, run / "thumbnail.png")
    assert "ver su entrada" in datos["procedencia"]["licencia"]


# --- sigue pasando por el mismo gate que una generada -----------------------------------------


def test_la_miniatura_de_una_lamina_pasa_por_el_recorte_y_el_texto(tmp_path):
    """No es un atajo: el texto se compone y se mide igual, y por eso puede suspender igual."""
    run = _run(tmp_path)
    destino = run / "thumbnail.png"
    miniatura.desde_lamina(run, 1, destino)
    medido = miniatura.compon_texto(str(destino), "WAS ANYONE INSIDE?", fuente=ANTON)
    assert medido["altura_mayuscula_a_168"] >= miniatura.ALTURA_MAYUSCULA_MINIMA_PX
    veredicto = miniatura.comprueba(str(destino), texto="WAS ANYONE INSIDE?", medido_texto=medido)
    assert veredicto["cumple"], veredicto["fallos"]


def test_venir_de_una_lamina_no_exime_del_gate_del_texto(tmp_path):
    """Control negativo: el mismo píxel con un texto que el contrato no admite sigue suspendiendo."""
    run = _run(tmp_path)
    miniatura.desde_lamina(run, 1, run / "thumbnail.png")
    with pytest.raises(ValueError, match="palabras"):
        miniatura.revisa_texto("MEDIEVAL IRON MAIDEN NEVER EXISTED ANYWHERE")


# --- la etapa EXIGE la lámina (12-09) ----------------------------------------------------------


@pytest.fixture
def etapa(tmp_path, monkeypatch, marca_falsa):
    """Ejecuta `stage_thumbnail` sobre un run de mentira, interceptando el estado en disco.

    La guarda de la lámina es lo primero que hace la etapa —antes de mirar el texto y mucho antes de
    tocar la GPU—, así que esto la ejercita entera sin ComfyUI ni perfil de canal.
    """
    import pipeline
    from lib import state as run_state

    escritos = []
    # Un run del motor de escena: desde F6.7 la miniatura de un run viejo se niega antes de esta guarda.
    monkeypatch.setattr(run_state, "load_run", lambda _rid: {"output_dir": str(tmp_path), "motor": run_state.MOTOR})
    monkeypatch.setattr(run_state, "update_stage", lambda *a, **k: escritos.append(a))

    def corre(slides: dict, laminas: int = 0):
        if laminas:
            _run(tmp_path, laminas)
        elif not (tmp_path / "slides").exists():
            (tmp_path / "slides").mkdir()
        (tmp_path / "slides.json").write_text(json.dumps(slides, ensure_ascii=False), encoding="utf-8")
        pipeline.stage_thumbnail("run-x")

    corre.escritos = escritos
    return corre


def test_un_guion_sin_lamina_PARA_la_etapa_y_dice_que_escribir(etapa):
    """El caso del episodio 2: `thumbnail_prompt` puesto, ninguna lámina declarada, miniatura inventada."""
    with pytest.raises(ValueError, match="thumbnail_lamina"):
        etapa({"thumbnail_prompt": "an iron cage", "thumbnail_text": "NOT MEDIEVAL"}, laminas=2)
    assert etapa.escritos and etapa.escritos[0][1:3] == ("thumbnail", "blocked")


def test_sin_lamina_el_mensaje_LISTA_las_del_run(etapa):
    """Para que elegir una sea mirar la lista, no ir a buscarla al disco."""
    with pytest.raises(ValueError, match=r"slide-01\.png, slide-02\.png"):
        etapa({"thumbnail_text": "NOT MEDIEVAL"}, laminas=2)


def test_un_run_todavia_SIN_laminas_lo_dice_en_vez_de_listar_nada(etapa):
    with pytest.raises(ValueError, match="aún no tiene láminas"):
        etapa({"thumbnail_text": "NOT MEDIEVAL"})


def test_CONTROL_NEGATIVO_con_la_lamina_declarada_la_guarda_deja_pasar(etapa):
    """Sin esto, los tres de arriba no distinguen «la guarda funciona» de «la etapa nunca arranca».

    Con `thumbnail_lamina` puesto la etapa pasa de largo esta guarda y se para en la SIGUIENTE, que es
    la del texto. Que el error sea otro es la prueba de que la primera dejó pasar.
    """
    with pytest.raises(ValueError, match="thumbnail_text"):
        etapa({"thumbnail_lamina": 1}, laminas=2)
    assert etapa.escritos and etapa.escritos[0][1:3] == ("thumbnail", "blocked")
