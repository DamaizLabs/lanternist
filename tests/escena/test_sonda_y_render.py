"""La sonda y el render del motor de escena (F6.2a), con Chrome, WebGPU y la GPU de verdad.

Criterios de F6.2a que se prueban aquí:
- «Un fotograma renderizado dos veces sale idéntico», con el control de un render con un actor movido 2 px;
- «El render falla si la página marca data-mallas-error, si lint da errores o si la composición referencia
  algo remoto; cada caso con su control negativo».

Cada causa de fallo tiene su composición rota a propósito, fabricada DESPUÉS de compone (`inyecta`), porque
lo que se prueba es la barrera siguiente: lo que la revisión estática no puede ver.

Se saltan, con el motivo, si falta node, la CLI de HyperFrames, el Chrome con WebGPU, nvidia-smi o ffmpeg.
**Van en serie y son cortas** (1,5 s de vídeo): la GPU no se reparte (regla 5 del plan de F6.2).
"""

from __future__ import annotations

import http.server
import json
import threading

import pytest
from utiles_escena import CSS_PRUEBA, falta_para_el_navegador, guion_min, inyecta, md5_por_fotograma

from lib.escena import compone, render

FALTA = falta_para_el_navegador()
pytestmark = pytest.mark.skipif(FALTA is not None, reason=FALTA or "")

# Captura el GPUDevice que crea malla-webgpu.js, para poder romperlo desde fuera.
CAPTURA_DISPOSITIVO = (
    "<script>(() => { const o = GPUAdapter.prototype.requestDevice;"
    " GPUAdapter.prototype.requestDevice = async function (...a) {"
    " const d = await o.apply(this, a); window.__dispositivo = d; return d; }; })();</script>"
)
# Destruye el dispositivo al pintar el primer fotograma con t ≥ 0,3 s. La sonda solo pinta t = 0, así que no
# lo ve: es el caso de una GPU que se pierde A MITAD de vídeo, y solo lo puede cazar el log del render.
ROMPE_A_MITAD = (
    "<script>(() => { const pinta = Mallas.pinta.bind(Mallas);"
    " Mallas.pinta = (M, t, v) => { if (t >= 0.3 && window.__dispositivo && !window.__roto) {"
    " window.__roto = true; window.__dispositivo.destroy(); } return pinta(M, t, v); }; })();</script>"
)


class _Contador(http.server.BaseHTTPRequestHandler):
    visitas: list[str] = []
    PNG = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
    )

    def do_GET(self):  # noqa: N802 (nombre de la API de http.server)
        type(self).visitas.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(self.PNG)

    def log_message(self, *args):
        pass


@pytest.fixture
def servidor_127_0_0_2():
    """Un servidor en 127.0.0.2: es del propio PC, pero la sonda no lo tiene por suyo, así que hace de «internet»
    sin salir de la máquina, y cuenta las visitas que recibe."""
    _Contador.visitas = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.2", 0), _Contador)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield f"127.0.0.2:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _informe(ruta_log: str) -> dict:
    return json.loads(open(ruta_log, encoding="utf-8").read())


# ------------------------------------------------------------------------------------------ la buena
def test_la_composicion_buena_pasa_lint_y_sonda_con_webgpu_de_hardware(composicion, tmp_path):
    datos = render.valida(composicion, tmp_path / "log")
    assert datos["lint"]["errorCount"] == 0
    s = datos["sonda"]
    assert s["remotas"] == [] and s["mallas_error"] is None and s["errores_consola"] == [] and s["timeline"]
    assert s["adaptador"]["fallback"] is False
    # Las mallas cargaron en el adaptador de hardware, sin errores.
    assert s["mallas"]["adaptador"]["fallback"] is False and s["mallas"]["errores"] == []


def test_snapshot_saca_las_capturas_pedidas(composicion, tmp_path):
    capturas = render.snapshot(composicion, tmp_path / "log", [0.2, 1.2], tmp_path / "capturas")
    assert [p.name for p in capturas] == ["frame-00-at-0.2s.png", "frame-01-at-1.2s.png"]
    assert list((tmp_path / "log").glob("snapshot-*.log")) and list((tmp_path / "log").glob("sonda-*.json"))


# ------------------------------------------------------------------------------------------ remotas
def test_control_una_imagen_remota_la_caza_la_sonda_y_no_hay_render(composicion, tmp_path):
    inyecta(composicion / "index.html", cuerpo='<img src="https://remoto.invalid/x.png" alt="">')
    salida = tmp_path / "no.mp4"
    with pytest.raises(render.ErrorDeRender, match="de fuera") as e:
        render.render(composicion, salida, tmp_path / "log")
    assert "https://remoto.invalid/x.png" in str(e.value)
    assert not salida.exists()


def test_la_peticion_remota_no_sale_y_su_control_si_llega(composicion, tmp_path, servidor_127_0_0_2):
    """La sonda no solo la apunta: la corta. El servidor de 127.0.0.2 no recibe nada; y cuando se le deja pasar
    (el control), la misma página SÍ llega, así que el «0 visitas» no es un servidor sordo."""
    origen = servidor_127_0_0_2
    inyecta(
        composicion / "index.html",
        cuerpo=(
            f'<img src="http://{origen}/html.png" alt="">'
            # Y una URL que solo existe al ejecutar: la revisión estática de compone no la puede ver.
            f"<script>new Image().src = 'http://' + '{origen}' + '/js.png';</script>"
        ),
    )
    cortada = render.ejecuta_sonda(composicion, tmp_path / "log")
    assert sorted(cortada["remotas"]) == [f"http://{origen}/html.png", f"http://{origen}/js.png"]
    assert _Contador.visitas == []
    with pytest.raises(render.ErrorDeRender, match="de fuera"):
        render.comprueba_sonda(cortada)

    permitida = render.ejecuta_sonda(composicion, tmp_path / "log", permite=(origen,))
    assert permitida["remotas"] == []
    assert sorted(_Contador.visitas) == ["/html.png", "/js.png"]


def test_la_sonda_no_deja_permitir_nada_fuera_de_loopback(composicion, tmp_path):
    informe = render.ejecuta_sonda(composicion, tmp_path / "log", permite=("93.184.216.34:80",))
    assert informe["codigo_salida"] == 2 and "loopback" in informe["fallo"]


# ------------------------------------------------------------------------------------------ mallas
def test_control_una_malla_que_no_carga_marca_data_mallas_error_y_no_hay_render(composicion, tmp_path):
    (composicion / "assets" / "rig" / "cinta.png").unlink()
    salida = tmp_path / "no.mp4"
    with pytest.raises(render.ErrorDeRender, match="data-mallas-error") as e:
        render.render(composicion, salida, tmp_path / "log")
    assert "[mallas] no carga" in str(e.value)
    assert not salida.exists()


def test_control_la_gpu_se_pierde_a_mitad_del_render(composicion, tmp_path):
    """El control que F6.1 dejó pendiente: un error de la GPU provocado DURANTE el render.

    La sonda no lo ve (solo pinta t = 0) y HyperFrames termina con código 0; quien para es render.py, leyendo
    «[mallas]» en el log. El MP4 que HyperFrames dio por bueno se borra.
    """
    inyecta(composicion / "index.html", cabeza=CAPTURA_DISPOSITIVO, cuerpo=ROMPE_A_MITAD)
    assert render.valida(composicion, tmp_path / "log")["sonda"]["ok"]
    salida = tmp_path / "roto.mp4"
    with pytest.raises(render.ErrorDeRender, match=r"\[mallas\] dispositivo perdido") as e:
        render.render(composicion, salida, tmp_path / "log")
    assert "código 0" in str(e.value)
    assert not salida.exists()


# ------------------------------------------------------------------------------------------ lint
def test_control_lint_con_errores_para_antes_de_renderizar(composicion, tmp_path):
    inyecta(composicion / "index.html", cuerpo="<script>window.__azar = Math.random();</script>")
    salida = tmp_path / "no.mp4"
    with pytest.raises(render.ErrorDeRender, match="non_deterministic_code"):
        render.render(composicion, salida, tmp_path / "log")
    assert not salida.exists()


# ------------------------------------------------------------------------------------------ determinismo
def test_un_fotograma_renderizado_dos_veces_sale_identico_y_un_cambio_de_2_px_no(tmp_path, assets_min):
    comp = compone.compone(guion_min(), assets_min, CSS_PRUEBA, tmp_path / "comp").parent
    uno = md5_por_fotograma(render.render(comp, tmp_path / "uno.mp4", tmp_path / "log"))
    dos = md5_por_fotograma(render.render(comp, tmp_path / "dos.mp4", tmp_path / "log"))
    assert len(uno) == 36  # 1,5 s a 24 fps
    assert uno == dos
    assert len(set(uno)) == len(uno), "hay fotogramas repetidos: la escena no se mueve y la prueba no mira nada"

    # Control: el actor del plano 2 (a3, visible desde t = 0,9) movido 2 px. Solo cambian sus fotogramas.
    g = guion_min()
    g["planos"][1]["actores"][0]["pista"][0]["x"] += 2
    movida = compone.compone(g, assets_min, CSS_PRUEBA, tmp_path / "movida").parent
    tres = md5_por_fotograma(render.render(movida, tmp_path / "tres.mp4", tmp_path / "log"))
    distintos = [i for i, (a, b) in enumerate(zip(uno, tres)) if a != b]
    assert distintos, "moviendo un actor 2 px no cambia ningún fotograma: la comparación no sabe fallar"
    assert min(distintos) >= round(0.9 * 24), distintos


# ------------------------------------------------------------------------------------------ auditoría de F6.2a
def test_control_un_tipo_de_malla_desconocido_lo_para_la_sonda(composicion, tmp_path):
    """Recomendación 4, en el navegador: si el GUION llega sin pasar por compone, el motor para al arrancar."""
    index = composicion / "index.html"
    texto = index.read_text(encoding="utf-8")
    assert texto.count('"tipo":"cuadrupedo"') == 1
    index.write_text(texto.replace('"tipo":"cuadrupedo"', '"tipo":"perro"'), encoding="utf-8")
    with pytest.raises(render.ErrorDeRender, match="«perro»"):
        render.sonda(composicion, tmp_path / "log")


def _rompe_la_rueda(composicion) -> None:
    """La imagen existe (lint y la revisión estática la dan por buena) pero no decodifica."""
    (composicion / "assets" / "img" / "rueda.png").write_bytes(b"esto no es un png")


def test_control_una_imagen_que_no_decodifica_la_caza_la_sonda(composicion, tmp_path):
    _rompe_la_rueda(composicion)
    salida = tmp_path / "no.mp4"
    with pytest.raises(render.ErrorDeRender, match="no decodifican"):
        render.render(composicion, salida, tmp_path / "log")
    assert not salida.exists()


def test_sin_la_sonda_la_imagen_rota_la_para_no_best_effort(composicion, tmp_path, monkeypatch):
    """Recomendación 1: la barrera del propio render, probada quitando la sonda de en medio."""
    _rompe_la_rueda(composicion)
    monkeypatch.setattr(render, "valida", lambda *a, **k: {})
    salida = tmp_path / "no.mp4"
    with pytest.raises(render.ErrorDeRender, match="FrameCapture:media_load_failed"):
        render.render(composicion, salida, tmp_path / "log")
    assert not salida.exists()


def test_control_con_best_effort_hyperframes_entrega_el_video_sin_la_imagen(composicion, tmp_path):
    """Lo que `--no-best-effort` evita: la misma orden sin él sale con código 0, MP4 y solo un aviso."""
    _rompe_la_rueda(composicion)
    salida = tmp_path / "con-aviso.mp4"
    orden = ["render", str(composicion), "--fps", "24", "--browser-gpu", "-o", str(salida)]
    texto, _, codigo = render._cli(orden, composicion, tmp_path / "log", "best-effort", timeout=600)
    assert codigo == 0 and salida.is_file()
    assert "[FrameCapture:media_load_failed]" in texto
