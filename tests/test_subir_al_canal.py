"""La carpeta `subir-al-canal/`: qué va dentro, qué no, y que mover no rompe la procedencia.

Correr: .venv\\Scripts\\python -m pytest -q tests/test_subir_al_canal.py

**De dónde sale.** El 10-09, tras buscar el `.srt` en `subtitulos/` y encontrar el `.ass`:
«tendrías que generar por contrato una carpeta que diga "subir al canal", y todos los assets que son
para subir a YT colocarlos allí y así lo tenemos todo más organizado; dejarlo todo en la raíz teniendo
carpetas no lo veo coherente».

Lo que estas pruebas fijan, que es lo que puede romperse sin que se vea:

1. **La carpeta es del ESTUDIO**, no de un canal: `lib/config.py` la declara y `tests/test_capas.py`
   sigue en verde porque no es una decisión de canal.
2. **Mover los entregables no declara el run impublicable.** La procedencia reancla por nombre dentro de
   la carpeta, con control negativo: un archivo que no está en ninguno de los dos sitios sigue faltando.
3. **La carpeta NO es un directorio de trabajo**: lo que hay dentro cuenta como asset publicable y tiene
   que responder de dónde salió (decisión cerrada 5), al revés que `montaje/` o `subtitulos/`.
4. **La guía dice cuál es cuál**, que es el defecto que originó todo esto.
"""

import json
from pathlib import Path

from lib import config, provenance
from lib.publicacion import guia_de_subida


def test_la_carpeta_la_declara_el_estudio_y_es_la_misma_para_todos():
    assert config.DIR_SUBIR_AL_CANAL == "subir-al-canal"
    assert config.dir_subir_al_canal("/tmp/run-x").name == "subir-al-canal"


def test_dir_subir_al_canal_solo_crea_si_se_le_pide(tmp_path):
    assert not config.dir_subir_al_canal(tmp_path).exists()
    creada = config.dir_subir_al_canal(tmp_path, crear=True)
    assert creada.is_dir()


def test_ruta_publicable_prefiere_la_carpeta_pero_tolera_los_runs_viejos(tmp_path):
    """Los runs producidos antes del 10-09 tienen los entregables en la raíz y siguen siendo legibles."""
    # 1. No existe en ninguna parte: se devuelve la nueva, que es donde el pipeline lo escribirá.
    assert config.ruta_publicable(tmp_path, "final.mp4").parent.name == config.DIR_SUBIR_AL_CANAL
    # 2. Solo en la raíz (run viejo): se devuelve la de la raíz.
    (tmp_path / "final.mp4").write_bytes(b"x")
    assert config.ruta_publicable(tmp_path, "final.mp4") == tmp_path / "final.mp4"
    # 3. En las dos: manda la de la carpeta.
    nueva = config.dir_subir_al_canal(tmp_path, crear=True) / "final.mp4"
    nueva.write_bytes(b"y")
    assert config.ruta_publicable(tmp_path, "final.mp4") == nueva


def test_la_carpeta_NO_es_un_directorio_de_trabajo():
    """`montaje/` y `subtitulos/` guardan intermedios; esta guarda lo publicable y se audita."""
    assert config.DIR_SUBIR_AL_CANAL not in provenance.WORK_DIRS


# --- la procedencia sigue encontrando lo que se movió -----------------------------------------


def test_un_asset_movido_a_la_carpeta_se_reancla_por_su_nombre(tmp_path):
    """El caso real: `montaje.json` anotó `final.mp4` en la raíz y el archivo está en la carpeta."""
    movido = config.dir_subir_al_canal(tmp_path, crear=True) / "final.mp4"
    movido.write_bytes(b"video")
    resuelta = provenance._resolve(tmp_path, str(tmp_path / "final.mp4"))
    assert resuelta == movido


def test_lo_que_no_existe_en_ningun_sitio_sigue_faltando(tmp_path):
    """Control negativo: si el reanclaje inventara rutas, el conteo cruzado dejaría de servir."""
    pedida = tmp_path / "no-esta.mp4"
    resuelta = provenance._resolve(tmp_path, str(pedida))
    assert not resuelta.exists()


def test_el_reanclaje_no_confunde_dos_archivos_del_mismo_nombre(tmp_path):
    """Una cola de ruta existente gana sobre la búsqueda por nombre: es la más específica."""
    (tmp_path / "slides").mkdir()
    en_slides = tmp_path / "slides" / "slide-01.png"
    en_slides.write_bytes(b"lamina")
    otro = config.dir_subir_al_canal(tmp_path, crear=True) / "slide-01.png"
    otro.write_bytes(b"otra cosa")
    resuelta = provenance._resolve(tmp_path, str(Path("/otro/sitio/slides/slide-01.png")))
    assert resuelta == en_slides


# --- la guía de la carpeta --------------------------------------------------------------------


def _carpeta_con_entregables(tmp_path: Path) -> Path:
    destino = config.dir_subir_al_canal(tmp_path, crear=True)
    (destino / "final.mp4").write_bytes(b"v" * 2048)
    (destino / "thumbnail.png").write_bytes(b"t")
    (destino / "subtitulos.en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
    return destino


def test_la_guia_lista_los_tres_entregables_y_que_el_srt_es_el_que_studio_acepta(tmp_path):
    _carpeta_con_entregables(tmp_path)
    ruta = guia_de_subida(tmp_path, titulo="The Iron Maiden", descripcion="Una descripción", video_id="abc123")
    html = ruta.read_text(encoding="utf-8")
    assert ruta.name == "LEEME.html" and ruta.parent.name == config.DIR_SUBIR_AL_CANAL
    for nombre in ("final.mp4", "thumbnail.png", "subtitulos.en.srt"):
        assert nombre in html, nombre
    # Hasta F6.7 avisaba de que el `.ass` del karaoke quemado no valía para Studio; ese fichero ya no existe en un run.
    # Desde F7.11 cada `.srt` dice su idioma y dónde se adjunta (`tests/test_traduccion_srt.py`).
    assert "Studio → Subtítulos → Añadir idioma (inglés)" in html and "subtitulos.ass" not in html
    assert "abc123" in html and "The Iron Maiden" in html
    assert "Una descripción" in html


def test_la_guia_dice_que_todavia_no_se_ha_subido_cuando_no_hay_video_id(tmp_path):
    _carpeta_con_entregables(tmp_path)
    html = guia_de_subida(tmp_path, titulo="T", descripcion="D").read_text(encoding="utf-8")
    assert "Todavía no se ha subido" in html and "studio.youtube.com" not in html


def test_la_guia_señala_lo_que_falta_en_vez_de_callarlo(tmp_path):
    """Un run sin `.srt` (canal con subtítulos desactivados) tiene que verse en la guía."""
    destino = config.dir_subir_al_canal(tmp_path, crear=True)
    (destino / "final.mp4").write_bytes(b"v")
    html = guia_de_subida(tmp_path, titulo="T", descripcion="D").read_text(encoding="utf-8")
    assert "no está en este run" in html


def test_la_guia_escapa_el_html_del_titulo_y_de_la_descripcion(tmp_path):
    """El título sale del guion; una comilla o un `<` no pueden romper la página."""
    _carpeta_con_entregables(tmp_path)
    html = guia_de_subida(tmp_path, titulo='<script>alert("x")</script>', descripcion="a < b").read_text(
        encoding="utf-8"
    )
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert "a &lt; b" in html


def _composicion(run: Path, karaoke: list) -> None:
    """Una composición mínima con su GUION dentro, como la escribe `lib/escena/compone.py`."""
    destino = config.composicion_del_run(run)
    destino.mkdir(parents=True)
    guion = json.dumps({"karaoke": karaoke})
    (destino / "index.html").write_text(f'<script id="guion">\nwindow.GUION = {guion};\n</script>', encoding="utf-8")


def _assets(run: Path, tipos: list[str]) -> None:
    assets = [{"tipo": t, "modelo": "m"} for t in tipos]
    (run / "assets.json").write_text(json.dumps({"assets": assets}), encoding="utf-8")


def _fila_del_video(html: str) -> str:
    return html.split("<code>final.mp4</code>")[1].split("</tr>")[0]


def test_la_guia_dice_karaoke_y_musica_solo_si_el_run_los_lleva(tmp_path):
    """Hasta F7.11 la fila del vídeo decía siempre «karaoke quemados y la música», falso en un canal sin karaoke
    (fila 257)."""
    con, sin = tmp_path / "con-karaoke", tmp_path / "sin-karaoke"
    for run, karaoke in ((con, [{"id": "k1"}]), (sin, [])):
        _carpeta_con_entregables(run)
        _composicion(run, karaoke)
        _assets(run, ["audio", "musica"] if run is con else ["audio"])
    fila_con = _fila_del_video(guia_de_subida(con, titulo="T", descripcion="D").read_text(encoding="utf-8"))
    fila_sin = _fila_del_video(guia_de_subida(sin, titulo="T", descripcion="D").read_text(encoding="utf-8"))
    assert "Lleva los subtítulos karaoke quemados." in fila_con and "Lleva la música." in fila_con
    assert "karaoke" not in fila_sin and "No lleva subtítulos quemados" in fila_sin and "No lleva música." in fila_sin


def test_la_guia_dice_sin_comprobar_lo_que_el_run_no_deja_leer(tmp_path):
    """Sin composición ni `assets.json` (o con un GUION roto) no se supone nada: se dice que no se ha comprobado."""
    _carpeta_con_entregables(tmp_path)
    fila = _fila_del_video(guia_de_subida(tmp_path, titulo="T", descripcion="D").read_text(encoding="utf-8"))
    assert "Sin comprobar si lleva subtítulos quemados" in fila and "Sin comprobar si lleva música" in fila
    destino = config.composicion_del_run(tmp_path)
    destino.mkdir()
    (destino / "index.html").write_text("<html>sin GUION</html>", encoding="utf-8")
    fila = _fila_del_video(guia_de_subida(tmp_path, titulo="T", descripcion="D").read_text(encoding="utf-8"))
    assert "Sin comprobar si lleva subtítulos quemados" in fila
