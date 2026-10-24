"""El informe de fin de episodio: lo que salió peor de lo pedido, reunido para revisarlo en diez minutos.

Es la mitad «se anota» de «el pipeline siempre termina» (12-09). Lo que se prueba:

1. Una incidencia de voz registrada aparece en el informe con su lámina, segmento y texto.
2. El registro de voz ACUMULA una entrada por pasada (30 para 10 audios en el episodio 2, medido),
   así que manda el ÚLTIMO registro de cada archivo — control: un registro viejo con incidencia y uno
   nuevo sin ella NO produce incidencia.
3. Un run sin procedencia de voz devuelve listas vacías y no lanza.
4. La guía escribe la sección en rojo si hay algo y «Ninguna incidencia» en verde si no — el control
   negativo del informe: sin él, «no aparece nada» no distinguiría «todo bien» de «no se leyó».
"""

import json
from pathlib import Path

from lib import publicacion


def _run(tmp_path: Path, registros: list[dict], animadas: tuple[int, ...] = ()) -> Path:
    """Un run con su registro de voz. `animadas` pone un bloque `animacion` (cinemagraph) en esas láminas, como los
    runs del motor de láminas: el informe ya no lo lee (F6.7)."""
    run = tmp_path / "run"
    (run / "audio").mkdir(parents=True)
    (run / "audio" / "generacion-voz.json").write_text(json.dumps(registros), encoding="utf-8")
    slides = [{"narration": f"n{i}"} for i in range(1, 6)]
    for n in animadas:
        slides[n - 1]["animacion"] = {"clip": f"animacion/slide-{n:02d}-14B.mp4"}
    (run / "slides.json").write_text(json.dumps({"slides": slides}), encoding="utf-8")
    return run


def _reg(run: Path, lamina: int, **extra) -> dict:
    return {"file": str(run / "audio" / f"slide-{lamina:02d}.wav"), "tipo": "audio", **extra}


def _subir(run_dir, crear: bool = False) -> Path:
    """Doble de `config.dir_subir_al_canal`: la real CREA la carpeta, y sin eso el LEEME no se puede escribir."""
    d = Path(run_dir) / "subir"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_una_incidencia_de_voz_aparece_con_lamina_segmento_y_texto(tmp_path):
    run = _run(tmp_path, [])
    reg = _reg(
        run,
        11,
        incidencias_no_bloqueantes=[
            {"segmento": 7, "texto": "His hands. His iron. His week.", "respaldo": "silencio", "implausible": None}
        ],
    )
    (run / "audio" / "generacion-voz.json").write_text(json.dumps([reg]), encoding="utf-8")
    inc = publicacion.incidencias_del_run(run)
    assert len(inc["voz"]) == 1
    v = inc["voz"][0]
    assert v["lamina"] == "11" and v["segmento"] == 7
    assert "SILENCIO" in v["que_paso"]
    assert "His week" in v["texto"]


def test_manda_el_ultimo_registro_de_cada_archivo(tmp_path):
    """CONTROL: el registro acumula pasadas. Un fallo de una pasada vieja ya arreglado NO se informa."""
    run = _run(tmp_path, [])
    viejo = _reg(run, 2, incidencias_no_bloqueantes=[{"segmento": 3, "texto": "x", "respaldo": "sin_recorte"}])
    nuevo = _reg(run, 2, incidencias_no_bloqueantes=[])
    (run / "audio" / "generacion-voz.json").write_text(json.dumps([viejo, nuevo]), encoding="utf-8")
    inc = publicacion.incidencias_del_run(run)
    assert inc["voz"] == [], "la incidencia de la pasada vieja no puede resucitar"


def test_la_divagacion_grande_se_lista_aparte_y_la_pequena_no(tmp_path):
    run = _run(tmp_path, [])
    reg = _reg(
        run,
        5,
        recortes_por_divagacion=[
            {"segmento": 1, "divagacion_s": 0.3},  # la cola normal de una frase: no se lista
            {"segmento": 2, "divagacion_s": 2.7},  # una frase inventada detras: se lista
        ],
    )
    (run / "audio" / "generacion-voz.json").write_text(json.dumps([reg]), encoding="utf-8")
    inc = publicacion.incidencias_del_run(run)
    assert [d["segmento"] for d in inc["divagacion_grande"]] == [2]


def test_sin_procedencia_de_voz_devuelve_vacio_y_no_lanza(tmp_path):
    run = tmp_path / "vacio"
    run.mkdir()
    inc = publicacion.incidencias_del_run(run)
    assert inc["voz"] == [] and inc["divagacion_grande"] == [] and inc["miniatura"] is None


def test_el_informe_ya_no_enumera_cinemagraphs_ni_los_nombra_en_la_guia(tmp_path, monkeypatch):
    """El cinemagraph salió con el motor de láminas en F6.7: el informe no lo cuenta ni la guía lo menciona.

    Control: el run lleva bloques `animacion` en dos láminas, como los runs viejos, y aun así no aparecen.
    """
    run = _run(tmp_path, [], animadas=(1, 4))
    inc = publicacion.incidencias_del_run(run)
    assert "cinemagraph" not in inc
    from lib import config

    monkeypatch.setattr(config, "dir_subir_al_canal", _subir)
    html = publicacion.guia_de_subida(run, titulo="T", descripcion="D", incidencias=inc).read_text(encoding="utf-8")
    assert "Ninguna incidencia" in html and "cinemagraph" not in html


def test_la_guia_escribe_la_seccion_en_rojo_si_hay_incidencias(tmp_path, monkeypatch):
    run = _run(tmp_path, [])
    from lib import config

    monkeypatch.setattr(config, "dir_subir_al_canal", _subir)
    inc = {
        "voz": [{"lamina": "11", "segmento": 7, "texto": "His week.", "que_paso": "recortado por SILENCIO: prueba"}],
        "divagacion_grande": [],
        "miniatura": None,
    }
    salida = publicacion.guia_de_subida(run, titulo="T", descripcion="D", incidencias=inc)
    html = salida.read_text(encoding="utf-8")
    assert "Esto salió peor de lo pedido" in html
    assert "Lámina 11, segmento 7" in html
    assert "His week." in html


def test_la_guia_dice_ninguna_incidencia_si_no_hay(tmp_path, monkeypatch):
    """CONTROL NEGATIVO del informe: el caso limpio se dice en positivo, no con un hueco."""
    run = _run(tmp_path, [])
    from lib import config

    monkeypatch.setattr(config, "dir_subir_al_canal", _subir)
    inc = {"voz": [], "divagacion_grande": [], "miniatura": None}
    html = publicacion.guia_de_subida(run, titulo="T", descripcion="D", incidencias=inc).read_text(encoding="utf-8")
    assert "Ninguna incidencia" in html
    assert "Esto salió peor" not in html


def test_sin_incidencias_pasadas_la_guia_no_cambia(tmp_path, monkeypatch):
    """Retrocompatibilidad: quien llame como antes (sin `incidencias`) no ve seccion nueva."""
    run = _run(tmp_path, [])
    from lib import config

    monkeypatch.setattr(config, "dir_subir_al_canal", _subir)
    html = publicacion.guia_de_subida(run, titulo="T", descripcion="D").read_text(encoding="utf-8")
    assert "Ninguna incidencia" not in html and "Esto salió peor" not in html
