r"""Cata del ritmo de narración de un canal: palabras por segundo con su voz real (skill `crea-canal`, paso 4).

Correr (usa la GPU a través de `llama-server`: como proceso independiente de Windows):
  .venv\Scripts\python scripts/cata_ritmo.py --canal <id> --texto-de <parrafo.txt>

## Por qué existe

`scripts/verifica_guion.py` deriva la banda de palabras por lámina de `perfil.json →
voz.palabras_por_segundo`, así que el primer guion de un canal ya la necesita. No se puede copiar de
otro canal: el ritmo depende de la receta, del estilo del guion y del motor, y el del primer canal (2,44)
medía mal los guiones del segundo (fila 164). Tampoco se estima a ojo: un párrafo con la voz real sí lo mide.

## Qué mide y qué no

Narra el párrafo con Orpheus y la receta del canal —la misma llamada que la etapa de voz,
`voice_client.generate_tts`— y divide las palabras que se leen entre los segundos del audio. Las
etiquetas emocionales no cuentan como palabras. **Es una previsión**: en un canal la cata dio 1,80 y el
episodio entero, 1,885 (lo anotó su `perfil.json → voz._palabras_por_segundo_por_que`).
Por eso el valor entra en el perfil como provisional y se remide sobre el primer episodio.

El audio queda en la caché de voz, fuera del repo. En `experimentos/` queda solo el JSON de la
medición, que es la dirección de la cifra.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if "--canal" in sys.argv:
    _i = sys.argv.index("--canal")
    if _i + 1 < len(sys.argv):
        os.environ["CANAL_ACTIVO"] = sys.argv[_i + 1].strip()
sys.path.insert(0, str(RAIZ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cata del ritmo de narración de un canal")
    parser.add_argument("--canal", required=True)
    parser.add_argument("--texto-de", type=Path, required=True)
    args = parser.parse_args(argv)
    if os.environ.get("CANAL_ACTIVO") != args.canal:
        raise SystemExit("[FAIL] --canal tiene que ir en la línea de órdenes: se lee antes de importar lib.config")

    from lib.config import BASE_DIR, CANAL_ERROR, VOICE_CACHE_DIR, VOICE_RECIPE_PATH
    from lib.medios import get_audio_duration
    from lib.voice_client import generate_tts, sin_etiquetas

    if CANAL_ERROR:
        raise SystemExit(f"[FAIL] el canal no está usable todavía: {CANAL_ERROR}")
    texto = args.texto_de.read_text(encoding="utf-8").strip()
    palabras = len(sin_etiquetas(texto).split())
    if palabras < 60:
        raise SystemExit(f"[FAIL] el párrafo tiene {palabras} palabras: con menos de 60 la medida no dice nada")

    marca = f"{datetime.now():%Y-%m-%d-%H%M%S}"
    wav = (VOICE_CACHE_DIR / "catas" / args.canal / f"cata-{marca}.wav").resolve()
    # Como `referencia_voz.py` y `muestras_voz.py`: ningún audio de voz dentro del repo (lista negra).
    if wav.is_relative_to(Path(BASE_DIR).resolve()):
        raise SystemExit(f"[FAIL] la caché de voz apunta dentro del repo ({wav}): el audio vive fuera")
    wav.parent.mkdir(parents=True, exist_ok=True)
    generate_tts(texto, output_path=str(wav))
    segundos = float(get_audio_duration(str(wav)))
    ritmo = round(palabras / segundos, 3)

    medida = {
        "canal": args.canal,
        "receta": Path(VOICE_RECIPE_PATH).name,
        "fecha": marca,
        "palabras": palabras,
        "segundos": round(segundos, 2),
        "palabras_por_segundo": ritmo,
        "texto": texto,
        "audio": str(wav),
        "_que_es": "previsión sobre un párrafo; se remide sobre el primer episodio entero",
    }
    salida = RAIZ / "experimentos" / f"cata-ritmo-{args.canal}-{marca}.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(medida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{palabras} palabras en {segundos:.2f} s → {ritmo} palabras/s")
    print(f"Medida: {salida}")
    print(
        "Para el perfil: voz.palabras_por_segundo = "
        f"{ritmo}, con `_palabras_por_segundo_por_que` citando esta medida y que es provisional."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
