"""Marcas de tiempo por palabra — se ejecuta con el intérprete de `.venv-voz` (F2.13).

Mismo patrón que `lib/voice_worker.py` y por el mismo motivo: `transformers` y `torch` viven en
`.venv-voz`, no en el `.venv` del pipeline. `lib/subtitulos.py` lanza este archivo como
subproceso, le pasa un trabajo en JSON y recoge el resultado en otro.

**Esto no es transcripción, es alineación.** El texto ya se conoce —es la narración del
`slides.json`— y lo único que falta son los tiempos, porque ningún motor de voz del proyecto los
devuelve. De aquí salen **solo las marcas**; quién empareja esas marcas con el guion es
`lib/subtitulos.py`, y el texto que acaba en pantalla es **siempre el del guion**. Así una
palabra que el reconocedor oiga mal no aparece en el vídeo.

Contrato, igual de tonto que el worker de voz:

- **No importa nada del repositorio** ni lee el `.env`. Todo llega en el trabajo.
- **Sin red**: `HF_HUB_OFFLINE=1`. El modelo ya está en la caché (lo dejó el spike de acento de
  F1.2c); si faltara, el error es explícito en vez de una descarga inesperada (decisión 6).
- **Sin reintentos**: un audio que falle mata el proceso con código distinto de 0.
- **En serie**, un audio a la vez: el modelo se carga una sola vez para todo el lote.

Uso:

    .venv-voz\\Scripts\\python.exe lib/alineador_worker.py --trabajo <job.json> --resultado <res.json>

Formato del trabajo:

    {
      "modelo": "openai/whisper-small",
      "device": "cuda",
      "chunk_length_s": 30,
      "items": [
        {"id": "slide-01", "audio": "<ruta wav>"},
        {"id": "slide-05", "audio": "<ruta wav>", "chunk_length_s": 25}
      ]
    }

**El troceo de un ítem** (OC2.4): un ítem puede traer su propio `chunk_length_s`, que gana al del trabajo. Así la etapa
`alinea` reintenta una lámina mal alineada con 25 y 20 s en el MISMO lanzamiento, con el modelo cargado una vez. El
resultado de cada ítem dice con qué troceo salió.

**Las marcas pegadas** (OC2.4): whisper parte a veces una palabra en dos trozos, « 38» y «.4%.», y el segundo no
empieza por espacio porque continúa la palabra. Aquí se quita ese espacio al guardar el texto, así que el trozo que
continúa lleva `"pegada": true`. No se une aquí, porque el obrero no importa nada del repositorio: la une el lanzador
(`lib/alineador.py → une_pegadas`) con la misma unión del recorte de la voz.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Alineador de palabras de la narración (se ejecuta en .venv-voz)")
    parser.add_argument("--trabajo", required=True)
    parser.add_argument("--resultado", required=True)
    args = parser.parse_args()

    job = json.loads(Path(args.trabajo).read_text(encoding="utf-8"))

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    import torch
    from transformers import pipeline

    device = job.get("device", "cuda")
    if device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("[FAIL] torch.cuda.is_available() == False en .venv-voz (trampa conocida de Windows)")

    started = time.perf_counter()
    asr = pipeline(
        "automatic-speech-recognition",
        model=job["modelo"],
        device=0 if device == "cuda" else -1,
        chunk_length_s=job.get("chunk_length_s", 30),
    )
    resultado = {
        "modelo": job["modelo"],
        "dispositivo": device,
        "load_seconds": round(time.perf_counter() - started, 1),
        "items": [],
    }
    destino = Path(args.resultado)
    destino.parent.mkdir(parents=True, exist_ok=True)

    for numero, item in enumerate(job["items"], start=1):
        audio = item["audio"]
        if not Path(audio).exists():
            raise SystemExit(f"[FAIL] no existe el audio a alinear: {audio}")
        t0 = time.perf_counter()
        # Sin troceo propio, la llamada de siempre: el del trabajo, con el que se creó el pipeline
        troceo = item.get("chunk_length_s")
        salida = asr(audio, return_timestamps="word", **({"chunk_length_s": troceo} if troceo else {}))
        marcas = []
        for trozo in salida.get("chunks", []):
            # Un trozo sin marca de inicio no sirve para nada: se descarta aquí y no aguas abajo
            if not trozo.get("timestamp") or trozo["timestamp"][0] is None or trozo["timestamp"][1] is None:
                continue
            marca = {"texto": trozo["text"].strip(), "desde": trozo["timestamp"][0], "hasta": trozo["timestamp"][1]}
            if marcas and trozo["text"] and not trozo["text"][0].isspace():
                marca["pegada"] = True  # continúa la palabra de la marca anterior
            marcas.append(marca)
        resultado["items"].append(
            {
                "id": item["id"],
                "audio": audio,
                "chunk_length_s": troceo or job.get("chunk_length_s", 30),
                "marcas": marcas,
                "transcripcion": (salida.get("text") or "").strip(),
                "seconds": round(time.perf_counter() - t0, 1),
            }
        )
        con = f" con {troceo} s" if troceo else ""
        print(f"  [{numero}/{len(job['items'])}] {item['id']}{con}: {len(marcas)} palabra(s) marcadas", flush=True)
        # Se vuelca en cada vuelta: si el proceso muere, lo alineado queda contabilizado
        destino.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
