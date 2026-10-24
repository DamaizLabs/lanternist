"""La marca de IA legible por máquina (OC1.5): el mensaje, el umbral, el veredicto, el cliente y una prueba de verdad.

Lo que se prueba, cada cosa con su control:

- Las funciones puras: los bits del mensaje, el umbral de 167 de 256 bits (166 no basta) y los veredictos de un
  fichero marcado, de uno sin marcar y de los mixtos (el C2PA perdido o roto con la marca de agua presente, la marca
  de AudioSeal de otro).
- El cliente con un lanzador falso: el trabajo que escribe, el error del trabajador, la autocomprobación que no
  encuentra la marca (y entonces no queda el fichero), el `.venv-escena` que falta, el cerrojo de la GPU y la bajada de
  los pesos con su sha256.
- La guarda de la subida (`exige_marcado`) y `--set-thumbnail`.
- **De verdad**, en CPU y sin cerrojo: un clip sintético de 3 s marcado y detectado; el mismo clip sin marcar da «no
  marcado»; el C2PA sale «Valid» con `signingCredential.untrusted` y, con un byte cambiado, «Invalid»; y el informe
  firmado se verifica con la clave pública de su cadena. Se salta si faltan `.venv-escena`, sus paquetes o los pesos.

La etapa `render` y la miniatura con la marca están en `tests/escena/test_etapas.py` y
`tests/escena/test_miniatura_fotograma.py`; la subida que se niega, en `tests/test_metadatos_traducidos.py`.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lib import config, marca_ia
from lib.escena import render

# ------------------------------------------------------------------------------------------ lo puro
MARCADO = {
    "file": "final.mp4",
    "sha256": "a" * 64,
    "c2pa": {
        "supported": True,
        "manifest": True,
        "state": "Valid",
        "failures": ["signingCredential.untrusted"],
        "generator": "Lanternist 2.0.0-rc.1",
        "signer": "Lanternist local signer",
        "ai": True,
        "error": None,
    },
    "image": {"bits": 256, "matches": 256, "p_value": 8.6e-78, "frames": 109},
    "audio": {"bits": 16, "probability": 1.0, "matches": 16},
}
SIN_MARCA = {
    "file": "final-sin-marca.mp4",
    "sha256": "b" * 64,
    "c2pa": {"supported": True, "manifest": False},
    "image": {"bits": 256, "matches": 117, "p_value": 0.92, "frames": 109},
    "audio": {"bits": 16, "probability": 0.006, "matches": 7},
}


def _con(base: dict, **cambios) -> dict:
    return {**json.loads(json.dumps(base)), **cambios}


def test_los_bits_del_mensaje_son_los_del_sha256_de_la_frase():
    bits = marca_ia.bits_del_mensaje(256)
    resumen = hashlib.sha256(b"Lanternist: AI-generated content").digest()
    assert len(bits) == 256 and set(bits) == {0, 1}
    assert int("".join(map(str, bits)), 2) == int.from_bytes(resumen, "big")
    assert marca_ia.bits_del_mensaje(16) == bits[:16], "AudioSeal lleva los 16 primeros"
    for n in (0, 257):
        with pytest.raises(ValueError):
            marca_ia.bits_del_mensaje(n)


def test_el_umbral_de_imagen_es_167_de_256_y_166_no_basta():
    assert marca_ia.p_valor(167, 256) < 1e-6 <= marca_ia.p_valor(166, 256)
    assert marca_ia.p_valor(167, 256) == pytest.approx(6.2e-7, rel=0.01)
    assert marca_ia.p_valor(256, 256) == 2.0**-256 and marca_ia.p_valor(0, 256) == 1.0
    con_167 = _con(SIN_MARCA, image={"bits": 256, "matches": 167, "p_value": 0.0, "frames": 1})
    con_166 = _con(SIN_MARCA, image={"bits": 256, "matches": 166, "p_value": 0.0, "frames": 1})
    assert marca_ia.imagen_de_lanternist(con_167) and marca_ia.de_lanternist(con_167)
    assert not marca_ia.imagen_de_lanternist(con_166) and not marca_ia.de_lanternist(con_166)


def test_el_veredicto_de_un_fichero_marcado_da_una_linea_por_capa():
    texto = marca_ia.veredicto(MARCADO)
    lineas = texto.splitlines()
    assert lineas[0].startswith("File: final.mp4") and len(lineas) == 5
    assert lineas[1].startswith("C2PA metadata: signed by Lanternist 2.0.0-rc.1") and "untrusted" in lineas[1]
    assert lineas[2].startswith("Image watermark (Video Seal): FOUND, 256 of 256")
    assert lineas[3].startswith("Audio watermark (AudioSeal): FOUND")
    assert lineas[4].startswith("Verdict: MARKED") and "missing or broken" not in lineas[4]
    assert marca_ia.de_lanternist(MARCADO) and marca_ia.autocomprobacion(MARCADO) == []


def test_control_el_veredicto_de_un_fichero_sin_marcar_dice_que_eso_no_prueba_nada():
    texto = marca_ia.veredicto(SIN_MARCA)
    assert "C2PA metadata: none in this file" in texto
    assert "Image watermark (Video Seal): not found, 117 of 256" in texto and "needs 167" in texto
    assert "Audio watermark (AudioSeal): not found" in texto
    assert texto.splitlines()[-1].startswith("Verdict: NOT MARKED") and "does not prove" in texto
    assert not marca_ia.de_lanternist(SIN_MARCA)
    assert len(marca_ia.autocomprobacion(SIN_MARCA)) == 3


def test_el_c2pa_perdido_con_la_marca_de_agua_presente_sigue_siendo_de_lanternist():
    """Lo normal tras YouTube o una recodificación: el manifiesto se pierde y la marca de agua sobrevive."""
    sin_c2pa = _con(MARCADO, c2pa={"supported": True, "manifest": False})
    texto = marca_ia.veredicto(sin_c2pa)
    assert marca_ia.de_lanternist(sin_c2pa) and not marca_ia.c2pa_de_lanternist(sin_c2pa)
    assert "Verdict: MARKED" in texto and "missing or broken" in texto
    assert marca_ia.autocomprobacion(sin_c2pa) and "C2PA" in marca_ia.autocomprobacion(sin_c2pa)[0]
    # Un byte cambiado: el manifiesto sigue ahí, pero la firma ya no ata los bytes.
    roto = _con(MARCADO, c2pa={**MARCADO["c2pa"], "state": "Invalid", "failures": ["assertion.bmffHash.mismatch"]})
    assert "INVALID" in marca_ia.veredicto(roto) and "bmffHash.mismatch" in marca_ia.veredicto(roto)
    assert not marca_ia.c2pa_de_lanternist(roto) and marca_ia.de_lanternist(roto)
    # Y solo el C2PA, sin marca de agua (una imagen que el detector no reconoce): basta una capa.
    solo_c2pa = _con(SIN_MARCA, c2pa=MARCADO["c2pa"])
    assert marca_ia.de_lanternist(solo_c2pa) and "Verdict: MARKED" in marca_ia.veredicto(solo_c2pa)


def test_una_marca_de_audioseal_de_otro_no_es_la_de_lanternist():
    otra = _con(SIN_MARCA, audio={"bits": 16, "probability": 0.97, "matches": 9})
    assert marca_ia.audio_con_marca(otra) and not marca_ia.audio_de_lanternist(otra)
    assert "not Lanternist's. The detector responds (probability 0.97), but only 9 of 16" in marca_ia.veredicto(otra)
    assert not marca_ia.de_lanternist(otra)


def test_lo_que_el_fichero_no_tiene_no_se_mira():
    imagen = _con(MARCADO, audio=None, c2pa={"supported": False, "manifest": False})
    texto = marca_ia.veredicto(imagen)
    assert "C2PA metadata: not checked" in texto and "Audio watermark (AudioSeal): not checked" in texto
    assert "missing or broken" not in texto, "un formato sin C2PA no lo ha perdido"
    solo_audio = _con(MARCADO, image=None)
    assert "Image watermark (Video Seal): not checked" in marca_ia.veredicto(solo_audio)
    # La autocomprobación de una imagen no pide audio.
    assert marca_ia.autocomprobacion(_con(MARCADO, audio=None)) == []


def test_un_manifiesto_de_otra_herramienta_no_es_el_de_lanternist():
    otro = _con(SIN_MARCA, c2pa={**MARCADO["c2pa"], "generator": "Otra 1.0"})
    assert not marca_ia.c2pa_de_lanternist(otro) and "signed by Otra 1.0" in marca_ia.veredicto(otro)
    sin_ia = _con(SIN_MARCA, c2pa={**MARCADO["c2pa"], "ai": False})
    assert not marca_ia.c2pa_de_lanternist(sin_ia) and "does NOT say" in marca_ia.veredicto(sin_ia)


# ------------------------------------------------------------------------------------------ el cliente, sin GPU
@pytest.fixture
def cliente(tmp_path, monkeypatch):
    """El cliente con las claves en una carpeta temporal y un lanzador falso que hace lo que se le diga."""
    monkeypatch.setattr(config, "MARCA_CLAVES_DIR", tmp_path / "claves")
    monkeypatch.setattr(config, "MARCA_CERROJO", tmp_path / "marca.cerrojo")
    # La GPU, libre: sin esto el detector preguntaría al nvidia-smi de verdad.
    monkeypatch.setattr(render, "trabajos_de_gpu_en_marcha", lambda: [])
    origen = tmp_path / "final-sin-marca.mp4"
    origen.write_bytes(b"video sin marca")
    destino = tmp_path / "final.mp4"
    visto: dict = {}

    def lanzador(*, codigo=0, comprobacion=None, log="", escribe=True):
        def lanza(trabajo, resultado, ruta_log, *, gpu):
            job = json.loads(Path(trabajo).read_text(encoding="utf-8"))
            visto.update(job=job, gpu=gpu)
            Path(ruta_log).write_text(log, encoding="utf-8")
            if job["op"] != "detecta" and escribe:
                Path(job["destino"]).write_bytes(b"video marcado")
            hecho = {"segundos": 1.0, "dispositivo": job["dispositivo"], "herramientas": {"av": "19.0.1"}}
            if job["op"] == "detecta":
                hecho["deteccion"] = comprobacion
            else:
                sha = marca_ia.sha256_de(job["destino"]) if Path(job["destino"]).exists() else None
                hecho["comprobacion"] = {**(comprobacion or MARCADO), "file": Path(job["destino"]).name, "sha256": sha}
            if codigo == 0:
                Path(resultado).write_text(json.dumps(hecho), encoding="utf-8")
            return codigo

        return lanza

    return {"origen": origen, "destino": destino, "visto": visto, "lanzador": lanzador, "trabajo": tmp_path / "t"}


def test_el_trabajo_va_bien_formado_y_el_registro_dice_lo_que_se_comprobo(cliente):
    c = cliente
    registro = marca_ia.marca_video(c["origen"], c["destino"], trabajo=c["trabajo"], lanza=c["lanzador"]())
    job = c["visto"]["job"]
    assert c["visto"]["gpu"] is True, "el marcado va en la GPU, con su cerrojo"
    assert job["op"] == "video" and job["dispositivo"] == "cuda"
    assert job["origen"] == str(c["origen"]) and job["destino"] == str(c["destino"])
    assert job["c2pa"] == {"claves": str(config.MARCA_CLAVES_DIR), "version": marca_ia.version()}
    assert set(job["pesos"]) == set(marca_ia.MODELOS)
    for clave, peso in job["pesos"].items():
        assert (
            Path(peso["ruta"]).parent == marca_ia.dir_de_pesos() and peso["sha256"] == marca_ia.MODELOS[clave]["sha256"]
        )
    assert registro["detectada"] is True and registro["sha256"] == marca_ia.sha256_de(c["destino"])
    assert registro["fichero"] == "final.mp4" and set(registro["modelos"]) == set(marca_ia.MODELOS)
    assert registro["modelos"]["videoseal"]["licencia"].startswith("MIT")
    assert registro["comprobacion"]["c2pa"]["state"] == "Valid"
    # La miniatura: solo Video Seal.
    imagen = marca_ia.marca_imagen(c["origen"], c["destino"], trabajo=c["trabajo"], lanza=c["lanzador"]())
    assert c["visto"]["job"]["op"] == "imagen" and set(imagen["modelos"]) == {"videoseal"}


def test_si_el_trabajador_falla_se_dice_con_su_log_y_no_se_reintenta(cliente):
    c = cliente
    llamadas = []

    def falla(*a, **k):
        llamadas.append(1)
        return c["lanzador"](codigo=1, log="Traceback ... CUDA out of memory")(*a, **k)

    with pytest.raises(marca_ia.ErrorDeMarca, match="falló \\(código 1\\)") as error:
        marca_ia.marca_video(c["origen"], c["destino"], trabajo=c["trabajo"], lanza=falla)
    assert "CUDA out of memory" in str(error.value) and llamadas == [1], "un intento, sin reintentos"
    assert not c["destino"].exists(), "lo que dejó a medias no se queda"


def test_si_la_autocomprobacion_no_encuentra_la_marca_no_queda_el_fichero(cliente):
    c = cliente
    debil = _con(MARCADO, image={"bits": 256, "matches": 120, "p_value": 0.8, "frames": 6})
    with pytest.raises(marca_ia.ErrorDeMarca, match="autocomprobación") as error:
        marca_ia.marca_video(c["origen"], c["destino"], trabajo=c["trabajo"], lanza=c["lanzador"](comprobacion=debil))
    assert "marca de imagen (120 de 256" in str(error.value)
    assert not c["destino"].exists(), "un fichero sin su marca no se entrega"
    # Control: el mismo trabajo con la marca entera sí deja el fichero.
    marca_ia.marca_video(c["origen"], c["destino"], trabajo=c["trabajo"], lanza=c["lanzador"]())
    assert c["destino"].exists()


def test_sin_venv_escena_se_dice_antes_de_bajar_nada(cliente, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ESCENA_PYTHON", str(tmp_path / "no-esta" / "python.exe"))
    monkeypatch.setattr(marca_ia, "_baja", lambda clave: pytest.fail(f"no se baja nada sin .venv-escena ({clave})"))
    with pytest.raises(marca_ia.ErrorDeMarca, match="no está .venv-escena"):
        marca_ia.marca_video(cliente["origen"], cliente["destino"], trabajo=cliente["trabajo"])
    with pytest.raises(marca_ia.ErrorDeMarca, match="no está .venv-escena"):
        marca_ia.detecta(cliente["origen"], trabajo=cliente["trabajo"])


def test_el_marcado_toma_su_cerrojo_y_el_detector_no(cliente, monkeypatch, tmp_path):
    """Mientras corre el marcado, otro trabajo de GPU lo ve en su cerrojo; al acabar se suelta. Sin las claves del
    `.env` en el entorno del trabajador, y con NO_TORCH_COMPILE para AudioSeal."""
    visto: dict = {"cerrojo": []}
    monkeypatch.setattr(marca_ia, "asegura_pesos", lambda: None)
    monkeypatch.setattr(render, "exige_gpu_libre", lambda *a, **k: visto.setdefault("gpu", 0))
    monkeypatch.setattr(config, "ESCENA_PYTHON", sys.executable)
    monkeypatch.setenv("UNA_API_KEY_DE_PRUEBA", "secreto")

    class Proceso:
        pid = os.getpid()  # un proceso vivo, para que el cerrojo cuente

        def __init__(self, args, **kwargs):
            visto.update(args=args, **kwargs)

        def wait(self, timeout=None):
            visto["cerrojo"].append(render.cerrojo_vivo(config.MARCA_CERROJO))
            return 0

    monkeypatch.setattr(marca_ia.subprocess, "Popen", Proceso)
    trabajo = tmp_path / "t.json"
    assert marca_ia._lanza(trabajo, tmp_path / "r.json", tmp_path / "l.log", gpu=True) == 0
    assert visto["args"][:2] == [config.ESCENA_PYTHON, str(config.MARCA_IA_WORKER)] and "gpu" in visto
    assert visto["env"]["NO_TORCH_COMPILE"] == "1" and "UNA_API_KEY_DE_PRUEBA" not in visto["env"]
    assert visto["cerrojo"][0]["pid"] == os.getpid() and "marca de IA" in visto["cerrojo"][0]["que"]
    assert not config.MARCA_CERROJO.exists(), "el cerrojo se suelta al acabar"
    # El detector: ni comprueba la GPU ni toma el cerrojo.
    visto.clear()
    visto["cerrojo"] = []
    marca_ia._lanza(trabajo, tmp_path / "r.json", tmp_path / "l.log", gpu=False)
    assert "gpu" not in visto and visto["cerrojo"] == [None]


def test_el_detector_corre_sin_gpu_si_se_le_pide(cliente):
    c = cliente
    resultado = marca_ia.detecta(c["origen"], cpu=True, trabajo=c["trabajo"], lanza=c["lanzador"](comprobacion=MARCADO))
    assert resultado == MARCADO and c["visto"]["gpu"] is False and c["visto"]["job"]["dispositivo"] == "cpu"
    assert c["visto"]["job"]["detector"] == {"id": marca_ia.DETECTOR, "version": marca_ia.version()}
    marca_ia.detecta(c["origen"], trabajo=c["trabajo"], lanza=c["lanzador"](comprobacion=MARCADO))
    assert c["visto"]["job"]["dispositivo"] == "auto" and c["visto"]["job"]["informe"] is None


def test_con_la_gpu_ocupada_o_sin_nvidia_smi_el_detector_va_en_la_cpu(cliente, monkeypatch):
    """La tarjeta de 8 GB no se reparte: con otro trabajo en ella, o sin forma de mirarlo, el detector no la toca (R2).
    El control, con la GPU libre, es `test_el_detector_corre_sin_gpu_si_se_le_pide`, que da «auto»."""
    c = cliente
    monkeypatch.setattr(render, "trabajos_de_gpu_en_marcha", lambda: ["ComfyUI (pid 1)"])
    marca_ia.detecta(c["origen"], trabajo=c["trabajo"], lanza=c["lanzador"](comprobacion=MARCADO))
    assert c["visto"]["job"]["dispositivo"] == "cpu"

    def sin_nvidia_smi():
        raise render.ErrorDeRender("no está nvidia-smi")

    monkeypatch.setattr(render, "trabajos_de_gpu_en_marcha", sin_nvidia_smi)
    marca_ia.detecta(c["origen"], trabajo=c["trabajo"], lanza=c["lanzador"](comprobacion=MARCADO))
    assert c["visto"]["job"]["dispositivo"] == "cpu"


def test_si_falla_la_marca_en_su_sitio_tampoco_queda_el_fichero_sin_marcar(cliente):
    """La miniatura se marca en su sitio, en `subir-al-canal/`: si la marca falla, no se queda ahí sin marca (R1)."""
    c = cliente
    miniatura = c["origen"].with_name("thumbnail.png")
    miniatura.write_bytes(b"miniatura sin marca")
    with pytest.raises(marca_ia.ErrorDeMarca, match="falló"):
        marca_ia.marca_imagen(miniatura, miniatura, trabajo=c["trabajo"], lanza=c["lanzador"](codigo=1, escribe=False))
    assert not miniatura.exists()
    # Control: si va bien, se queda, marcada.
    miniatura.write_bytes(b"miniatura sin marca")
    marca_ia.marca_imagen(miniatura, miniatura, trabajo=c["trabajo"], lanza=c["lanzador"]())
    assert miniatura.read_bytes() == b"video marcado"


def test_una_descarga_cortada_no_deja_el_parcial(tmp_path, monkeypatch):
    """`IncompleteRead` es una `HTTPException`, no un `OSError` (R4)."""
    import http.client

    monkeypatch.setenv("TORCH_HOME", str(tmp_path / "torch"))
    monkeypatch.setattr(marca_ia, "MODELOS", {"videoseal": {**marca_ia.MODELOS["videoseal"], "mb": 0}})

    class Cortada(io.BytesIO):
        def read(self, *a):
            raise http.client.IncompleteRead(b"a medias")

    monkeypatch.setattr(marca_ia.urllib.request, "urlopen", lambda url, timeout: Cortada())
    with pytest.raises(marca_ia.ErrorDeMarca, match="no se pudo bajar"):
        marca_ia.asegura_pesos()
    assert not any((tmp_path / "torch").rglob("*.part")), "el parcial se borra"


def test_un_fallo_inesperado_del_detector_no_se_da_por_no_marcado(monkeypatch, capsys):
    """El código 1 dice «no marcado»: un fallo cualquiera es el 2, «no he podido mirar» (R4)."""
    sys.path.insert(0, str(config.BASE_DIR / "scripts"))
    import detecta_marca

    def revienta(*a, **k):
        raise ValueError("algo que nadie esperaba")

    monkeypatch.setattr(marca_ia, "detecta", revienta)
    assert detecta_marca.main(["cualquiera.mp4"]) == 2
    assert "not checked" in capsys.readouterr().out
    # Control: el fallo conocido también es el 2, y un resultado sin marca es el 1.
    monkeypatch.setattr(marca_ia, "detecta", lambda *a, **k: (_ for _ in ()).throw(marca_ia.ErrorDeMarca("no está")))
    assert detecta_marca.main(["cualquiera.mp4"]) == 2
    monkeypatch.setattr(marca_ia, "detecta", lambda *a, **k: SIN_MARCA)
    assert detecta_marca.main(["cualquiera.mp4"]) == 1


def test_los_pesos_van_donde_los_busca_torch_hub():
    torch = pytest.importorskip("torch")
    assert marca_ia.dir_de_pesos() == Path(torch.hub.get_dir()) / "checkpoints" / "lanternist"


def test_un_peso_que_llega_con_otro_sha256_no_se_queda(tmp_path, monkeypatch):
    monkeypatch.setenv("TORCH_HOME", str(tmp_path / "torch"))
    contenido = b"un peso de mentira"
    modelo = {**marca_ia.MODELOS["videoseal"], "sha256": hashlib.sha256(b"otra cosa").hexdigest(), "mb": 0}
    monkeypatch.setattr(marca_ia, "MODELOS", {"videoseal": modelo})
    monkeypatch.setattr(marca_ia.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(contenido))
    with pytest.raises(marca_ia.ErrorDeMarca, match="otro sha256"):
        marca_ia.asegura_pesos()
    assert not any((tmp_path / "torch").rglob("*.jit*")), "ni el peso ni su parcial"
    # Control: con su sha256 de verdad, se queda, y la segunda vez no se baja otra vez.
    modelo["sha256"] = hashlib.sha256(contenido).hexdigest()
    marca_ia.asegura_pesos()
    assert marca_ia.ruta_del_peso("videoseal").read_bytes() == contenido and marca_ia.pesos_que_faltan() == []
    monkeypatch.setattr(marca_ia.urllib.request, "urlopen", lambda *a, **k: pytest.fail("ya estaba: no se baja"))
    marca_ia.asegura_pesos()


# ------------------------------------------------------------------------------------------ la guarda de la subida
def test_la_guarda_de_la_subida_pide_el_registro_y_el_mismo_fichero(tmp_path, marca_falsa):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"marcado")
    registro = marca_falsa.registro(video)
    marca_ia.exige_marcado(video, registro, rehacer="`--stage render`")
    with pytest.raises(marca_ia.ErrorDeMarca, match="no tiene su registro.*--stage render"):
        marca_ia.exige_marcado(video, None, rehacer="`--stage render`")
    with pytest.raises(marca_ia.ErrorDeMarca, match="no tiene su registro"):
        marca_ia.exige_marcado(video, {**registro, "detectada": False}, rehacer="`--stage render`")
    video.write_bytes(b"otro video, sin marcar")
    with pytest.raises(marca_ia.ErrorDeMarca, match="no es el fichero que se marcó"):
        marca_ia.exige_marcado(video, registro, rehacer="`--stage render`")


def test_set_thumbnail_se_niega_con_una_miniatura_sin_marca(tmp_path, monkeypatch, marca_falsa):
    import pipeline
    from lib import lineas_rojas, youtube_client
    from lib import state as run_state

    miniatura = tmp_path / "subir-al-canal" / "thumbnail.png"
    miniatura.parent.mkdir()
    miniatura.write_bytes(b"png")
    estado = {
        "output_dir": str(tmp_path),
        "stages": {"upload": {"output": json.dumps({"video_id": "abc"})}, "thumbnail": {"output": str(miniatura)}},
    }
    puestas = []
    monkeypatch.setattr(run_state, "load_run", lambda _id: estado)
    monkeypatch.setattr(run_state, "update_stage", lambda *a, **k: None)
    monkeypatch.setattr(lineas_rojas, "exige", lambda *a, **k: None)
    monkeypatch.setattr(youtube_client, "pon_miniatura", lambda *a: puestas.append(a) or (True, None))
    # `--set-thumbnail` usa la API, así que obedece a su interruptor (OC1.8): aquí va encendida, con su OAuth.
    monkeypatch.setattr(config, "YOUTUBE_SUBIDA_API", "1")
    for clave in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.setattr(config, clave, "de-mentira")
    with pytest.raises(marca_ia.ErrorDeMarca, match="thumbnail.png no tiene su registro.*--stage thumbnail"):
        pipeline.set_thumbnail("run-x")
    assert puestas == [], "no llega a la API"
    # Control: con su registro, sí.
    (tmp_path / "miniatura.json").write_text(json.dumps({"marca_ia": marca_falsa.registro(miniatura)}), "utf-8")
    assert pipeline.set_thumbnail("run-x") is True and len(puestas) == 1


# ------------------------------------------------------------------------------------------ de verdad, en CPU
def _falta_para_la_prueba_real() -> str | None:
    if not Path(config.ESCENA_PYTHON).is_file():
        return "no está .venv-escena (spikes/requirements-escena.txt)"
    if shutil.which("ffmpeg") is None:
        return "no está ffmpeg"
    # Por sus metadatos, sin importarlos: importar audioseal carga torch.
    nombres = ("audioseal", "c2pa-python", "av", "cryptography")
    mira = f"from importlib.metadata import version as v; [v(p) for p in {nombres!r}]"
    paquetes = subprocess.run([config.ESCENA_PYTHON, "-c", mira], capture_output=True, timeout=120)
    if paquetes.returncode != 0:
        return ".venv-escena no tiene audioseal, c2pa-python, av o cryptography"
    if marca_ia.pesos_que_faltan():
        return f"faltan los pesos de la marca en {marca_ia.dir_de_pesos()} (se bajan en la primera marca)"
    return None


@pytest.fixture(scope="module")
def de_verdad(tmp_path_factory):
    """Un clip sintético de 3 s (imagen de prueba de ffmpeg y un seno), marcado en CPU con las claves en una carpeta
    temporal. Sin cerrojo ni GPU: si el marcado en CPU los tocara, la prueba fallaría."""
    falta = _falta_para_la_prueba_real()
    if falta:
        pytest.skip(falta)
    carpeta = tmp_path_factory.mktemp("marca-de-verdad")
    clip = carpeta / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=3"]
        + ["-f", "lavfi", "-i", "sine=frequency=440:duration=3:sample_rate=48000"]
        + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-shortest", str(clip)],
        check=True,
    )
    parche = pytest.MonkeyPatch()
    parche.setattr(config, "MARCA_CLAVES_DIR", carpeta / "claves")
    parche.setattr(config, "MARCA_CERROJO", carpeta / "marca.cerrojo")
    parche.setattr(render, "exige_gpu_libre", lambda *a, **k: pytest.fail("el marcado en CPU no mira la GPU"))
    trabajo = carpeta / "trabajo"
    marcado = carpeta / "clip-marcado.mp4"
    registro = marca_ia.marca_video(clip, marcado, cpu=True, trabajo=trabajo)
    yield {"carpeta": carpeta, "clip": clip, "marcado": marcado, "registro": registro, "trabajo": trabajo}
    parche.undo()


def test_de_verdad_el_clip_marcado_lleva_las_tres_capas(de_verdad):
    registro = de_verdad["registro"]
    assert registro["detectada"] is True and registro["dispositivo"] == "cpu"
    assert registro["sha256"] == marca_ia.sha256_de(de_verdad["marcado"])
    c2pa = registro["comprobacion"]["c2pa"]
    assert c2pa["state"] == "Valid" and c2pa["failures"] == ["signingCredential.untrusted"]
    assert c2pa["generator"] == f"Lanternist {marca_ia.version()}" and c2pa["ai"] is True
    assert c2pa["signer"] == "Lanternist local signer"
    assert registro["comprobacion"]["image"]["matches"] >= marca_ia.UMBRAL_IMAGEN
    assert registro["comprobacion"]["audio"] == {"bits": 16, "probability": pytest.approx(1.0, abs=0.05), "matches": 16}
    assert (de_verdad["carpeta"] / "claves" / "clave.pem").is_file(), "el certificado se crea donde dice la config"
    assert not list(de_verdad["trabajo"].glob("*sin-firma*")) and not list(de_verdad["trabajo"].glob("*.wav"))


def test_de_verdad_el_detector_encuentra_la_marca_y_no_la_inventa(de_verdad):
    marcado = marca_ia.detecta(de_verdad["marcado"], cpu=True, trabajo=de_verdad["trabajo"])
    assert marca_ia.de_lanternist(marcado) and "Verdict: MARKED" in marca_ia.veredicto(marcado)
    assert marcado["device"] == "cpu"
    # Control negativo: el mismo clip sin marcar.
    limpio = marca_ia.detecta(de_verdad["clip"], cpu=True, trabajo=de_verdad["trabajo"])
    assert not marca_ia.de_lanternist(limpio) and "Verdict: NOT MARKED" in marca_ia.veredicto(limpio)
    assert limpio["c2pa"] == {"supported": True, "manifest": False}
    assert limpio["image"]["matches"] < marca_ia.UMBRAL_IMAGEN and not marca_ia.audio_de_lanternist(limpio)
    # Un tono puro sin marca hace responder al detector de AudioSeal (medido: 0,62 con este seno de 440 Hz). Lo que
    # evita la falsa atribución es el mensaje: sus 16 bits no son los de Lanternist.
    assert limpio["audio"]["matches"] < marca_ia.BITS_AUDIO


def test_de_verdad_un_byte_cambiado_rompe_la_firma_y_no_la_marca_de_agua(de_verdad):
    tocado = de_verdad["carpeta"] / "clip-tocado.mp4"
    datos = bytearray(de_verdad["marcado"].read_bytes())
    datos[len(datos) // 2] ^= 0xFF
    tocado.write_bytes(bytes(datos))
    resultado = marca_ia.detecta(tocado, cpu=True, trabajo=de_verdad["trabajo"])
    assert resultado["c2pa"]["state"] == "Invalid" and "INVALID" in marca_ia.veredicto(resultado)


def test_de_verdad_la_miniatura_se_marca_y_el_informe_se_verifica(de_verdad):
    from PIL import Image

    carpeta = de_verdad["carpeta"]
    imagen = carpeta / "thumbnail.png"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720", "-frames:v", "1", str(imagen)],
        check=True,
    )
    original = imagen.read_bytes()
    registro = marca_ia.marca_imagen(imagen, imagen, cpu=True, trabajo=de_verdad["trabajo"])
    assert (
        registro["comprobacion"]["image"]["matches"] >= marca_ia.UMBRAL_IMAGEN
        and registro["comprobacion"]["audio"] is None
    )
    assert Image.open(imagen).size == (1280, 720) and imagen.read_bytes() != original
    informe = carpeta / "informe.json"
    resultado = marca_ia.detecta(imagen, informe=informe, cpu=True, trabajo=de_verdad["trabajo"])
    assert marca_ia.de_lanternist(resultado)
    firmado = json.loads(informe.read_text(encoding="utf-8"))
    assert firmado["report"]["sha256"] == marca_ia.sha256_de(imagen) and firmado["report"]["lanternist_mark"] is True
    assert firmado["report"]["verdict"] == marca_ia.veredicto(resultado)
    assert firmado["report"]["detector"]["id"] == marca_ia.DETECTOR and firmado["signature"]["alg"] == "ES256"
    # La firma se verifica con la clave pública de la cadena; con el informe tocado, no (control).
    verifica = (
        "import base64, json, sys\n"
        "from cryptography import x509\n"
        "from cryptography.hazmat.primitives import hashes\n"
        "from cryptography.hazmat.primitives.asymmetric import ec\n"
        "from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature\n"
        "d = json.load(open(sys.argv[1], encoding='utf-8'))\n"
        "if sys.argv[2] == 'toca': d['report']['lanternist_mark'] = False\n"
        "datos = json.dumps(d['report'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()\n"
        "firma = base64.b64decode(d['signature']['value'])\n"
        "der = encode_dss_signature(int.from_bytes(firma[:32], 'big'), int.from_bytes(firma[32:], 'big'))\n"
        "hoja = x509.load_pem_x509_certificates(d['signature']['certificate_chain_pem'].encode())[0]\n"
        "try:\n"
        "    hoja.public_key().verify(der, datos, ec.ECDSA(hashes.SHA256())); print('VALIDA')\n"
        "except Exception:\n"
        "    print('NO VALIDA')\n"
    )
    for modo, esperado in (("tal-cual", "VALIDA"), ("toca", "NO VALIDA")):
        r = subprocess.run(
            [config.ESCENA_PYTHON, "-c", verifica, str(informe), modo], capture_output=True, text=True, timeout=120
        )
        assert r.stdout.strip() == esperado, r.stderr
