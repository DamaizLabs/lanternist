"""El alineador, sin GPU (OC2.4): el troceo de cada ítem y las palabras que whisper parte en dos trozos.

El obrero (`lib/alineador_worker.py`) corre aquí en el mismo proceso, con un `torch` y un `transformers` falsos: el
whisper falso devuelve los trozos tal cual los da el de verdad, con su espacio delante. La alineación en la GPU, con
whisper de verdad, está en `progress/impl_OC2.4.md`.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from lib import alineador, alineador_worker

# Lo que whisper-small dio palabra a palabra en el episodio 2 de un canal de economía (07-10-2026): la cifra partida en
# dos trozos, y el segundo sin espacio porque continúa la palabra (`tests/test_voz_recorte.py → _LAMINA_15`).
TROZOS = [" a", " rise", " of", " about", " 38", ".4%.", " Then", " more."]


def _whisper_falso(monkeypatch, llamadas: list) -> None:
    def pipeline(tarea, *, model, device, chunk_length_s):
        llamadas.append({"crea": chunk_length_s})

        def asr(audio, **kwargs):
            llamadas.append(kwargs)
            trozos = [{"text": t, "timestamp": (i * 0.4, (i + 1) * 0.4)} for i, t in enumerate(TROZOS)]
            return {"text": "".join(TROZOS), "chunks": trozos}

        return asr

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: 1)))
    monkeypatch.setitem(sys.modules, "transformers", types.SimpleNamespace(pipeline=pipeline))


def _obrero(tmp_path, monkeypatch, items: list[dict]) -> dict:
    trabajo, resultado = tmp_path / "trabajo.json", tmp_path / "resultado.json"
    job = {"modelo": "whisper-falso", "device": "cuda", "chunk_length_s": alineador.TROCEO_S, "items": items}
    trabajo.write_text(json.dumps(job), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["alineador_worker.py", "--trabajo", str(trabajo), "--resultado", str(resultado)])
    assert alineador_worker.main() == 0
    return json.loads(resultado.read_text(encoding="utf-8"))


def test_cada_item_se_alinea_con_su_troceo_y_sin_el_suyo_con_el_de_siempre(tmp_path, monkeypatch):
    wav = tmp_path / "slide-01.wav"
    wav.write_bytes(b"RIFF")
    llamadas = []
    _whisper_falso(monkeypatch, llamadas)
    hecho = _obrero(tmp_path, monkeypatch, [{"id": "slide-01", "audio": str(wav)},
                                            {"id": "slide-01", "audio": str(wav), "chunk_length_s": 25},
                                            {"id": "slide-01", "audio": str(wav), "chunk_length_s": 20}])  # fmt: skip
    assert llamadas[0] == {"crea": 30}, "el modelo se carga una vez, con el troceo del trabajo"
    assert llamadas[1] == {"return_timestamps": "word"}, "sin troceo propio, la llamada de antes, idéntica"
    assert [ll.get("chunk_length_s") for ll in llamadas[2:]] == [25, 20]
    assert [i["chunk_length_s"] for i in hecho["items"]] == [30, 25, 20], "cada ítem dice con qué troceo salió"


def test_el_trozo_que_continua_una_palabra_sale_marcado_y_el_lanzador_lo_une(tmp_path, monkeypatch):
    wav = tmp_path / "slide-01.wav"
    wav.write_bytes(b"RIFF")
    _whisper_falso(monkeypatch, [])
    marcas = _obrero(tmp_path, monkeypatch, [{"id": "slide-01", "audio": str(wav)}])["items"][0]["marcas"]
    assert [m["texto"] for m in marcas] == [t.strip() for t in TROZOS], "el texto se guarda como siempre, sin espacio"
    assert [i for i, m in enumerate(marcas) if m.get("pegada")] == [5], "solo «.4%.» continúa la palabra anterior"
    unidas = alineador.une_pegadas(marcas)
    assert [m["texto"] for m in unidas] == ["a", "rise", "of", "about", "38.4%.", "Then", "more."]
    assert (unidas[4]["desde"], unidas[4]["hasta"]) == pytest.approx((1.6, 2.4)), "de donde empieza «38» al final"


def test_CONTROL_sin_marcas_pegadas_las_marcas_salen_tal_cual():
    """Un episodio sin palabras partidas (el de ejemplo) no cambia: ni se unen dos palabras con espacio entre ellas."""
    marcas = [{"texto": "about", "desde": 0.0, "hasta": 0.4}, {"texto": "38", "desde": 0.4, "hasta": 0.8},
              {"texto": "dollars", "desde": 0.8, "hasta": 1.2}]  # fmt: skip
    assert alineador.une_pegadas(marcas) is marcas


# ------------------------------------------------------------------ el lanzador une lo que deja el obrero
GUION = "a rise of about 38.4%. Then more."


def _marcas_del_obrero(*, pegada: bool) -> list[dict]:
    marcas = [{"texto": t.strip(), "desde": i * 0.4, "hasta": (i + 1) * 0.4} for i, t in enumerate(TROZOS)]
    if pegada:
        marcas[5]["pegada"] = True
    return marcas


def _lanzador(tmp_path, monkeypatch, marcas: list[dict]) -> tuple[dict, str]:
    """`alineador.alinea` con un `subprocess.run` falso que escribe lo que escribiría el obrero.

    Devuelve lo que devuelve `alinea` y el texto del fichero de resultado, que es lo que leen la línea de tiempo, la
    integridad de la narración y la limpieza de voz."""
    escrito = {}

    def run(orden, timeout):
        resultado = orden[orden.index("--resultado") + 1]
        datos = {"modelo": "whisper-falso", "items": [{"id": "slide-01", "audio": "x.wav", "marcas": marcas}]}
        escrito["texto"] = json.dumps(datos, indent=2, ensure_ascii=False)
        Path(resultado).write_text(escrito["texto"], encoding="utf-8")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(alineador.subprocess, "run", run)
    hecho = alineador.alinea([{"id": "slide-01", "audio": "x.wav"}], tmp_path, {"modelo_alineacion": "whisper-falso"})
    disco = (tmp_path / "alineacion-resultado.json").read_text(encoding="utf-8")
    assert json.loads(disco) == hecho, "lo que devuelve y lo que queda en el fichero son lo mismo"
    return hecho, disco if disco != escrito["texto"] else "sin reescribir"


def test_el_lanzador_une_las_pegadas_y_lo_deja_en_el_fichero(tmp_path, monkeypatch):
    """Revisión de OC2.4, recomendación 2: sin la unión dentro de `alinea`, esta prueba falla."""
    from lib.limpia_voz import _un_item

    hecho, disco = _lanzador(tmp_path, monkeypatch, _marcas_del_obrero(pegada=True))
    marcas = hecho["items"][0]["marcas"]
    assert disco != "sin reescribir" and "pegada" not in disco
    assert [m["texto"] for m in marcas] == ["a", "rise", "of", "about", "38.4%.", "Then", "more."]

    # Y la limpieza de voz, que lee estas marcas, ya no toma un trozo de la cifra por una muletilla y lo calla
    def muletillas(marcas_: list[dict]) -> list[str]:
        sobrantes = _un_item({"audio": "x.wav"}, marcas_, GUION, minimo_s=0.25, techo_muletilla_s=2.5)["sobrantes"]
        return [s["texto"] for s in sobrantes if s["tipo"] == "muletilla"]

    assert muletillas(marcas) == []
    # Control: con los trozos sin unir, la limpieza declara muletilla un trozo de la cifra
    assert muletillas(_marcas_del_obrero(pegada=False)) != []


def test_CONTROL_sin_pegadas_el_fichero_queda_como_lo_escribio_el_obrero(tmp_path, monkeypatch):
    hecho, disco = _lanzador(tmp_path, monkeypatch, _marcas_del_obrero(pegada=False))
    assert disco == "sin reescribir" and len(hecho["items"][0]["marcas"]) == len(TROZOS)
