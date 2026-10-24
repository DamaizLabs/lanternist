"""Retención de la caché de voz: borra los recortes de referencia que ninguna receta declara.

    .venv\\Scripts\\python scripts\\purga_cache_voz.py            # dice qué borraría (no borra)
    .venv\\Scripts\\python scripts\\purga_cache_voz.py --aplica   # lo borra
    .venv\\Scripts\\python scripts\\purga_cache_voz.py --dias 15  # y los trabajos de más de 15 días

**Por qué existe (auditoría del 10-09, bloque 8, MEDIO).** `lib/voice_client` guarda en
`~/.cache/lanternist-voz` un recorte por cada referencia de clonado que usa, con el nombre
`ref-<id>-<offset>-<duración>-<tag>.wav`, donde `tag` son los 8 primeros dígitos del **sha1 de la ruta
absoluta de la grabación de origen**. Nada los borraba nunca (`grep rmtree|unlink` sobre
`VOICE_CACHE_DIR` daba 0), así que la caché conservaba cuatro recortes de **una grabación de voz
real** hechos el 24-08 desde una ruta que ya no se usa: dato biométrico derivado de una persona, con
retención indefinida y sin que nadie lo hubiera decidido.

**La regla de retención, que es lo que faltaba escrito.** Un recorte solo se conserva mientras alguna
receta de canal versionada declare la grabación de la que salió. Cuando el canal cambia de referencia
—o cuando la grabación era de una persona y hoy las referencias son sintéticas, que es el caso de este
proyecto desde la decisión 13— el recorte deja de tener función y se borra. La caché se regenera sola:
lo que se borra cuesta segundos de CPU, no una decisión.

Los `trabajos/` son otra cosa: los JSON de cada lote enviado al worker, con rutas absolutas dentro.
Solo son útiles para depurar el run en marcha, así que caducan por días.

**Nada de esto sale del PC ni toca el repo.** El script no llama a ninguna API.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import config  # noqa: E402

RECORTE = re.compile(r"^ref-.+-(?P<tag>[0-9a-f]{8})\.wav$")


def tag_de(ruta: Path) -> str:
    """El mismo tag que compone `lib/voice_client`: sha1 de la ruta absoluta, 8 dígitos."""
    return hashlib.sha1(str(ruta.resolve()).encode("utf-8")).hexdigest()[:8]


def referencias_declaradas() -> dict[str, list[str]]:
    """Tag → quién lo declara, leyendo TODAS las recetas de voz versionadas de todos los canales.

    Se recorren los canales del disco y no solo el activo: purgar mirando un canal borraría los
    recortes del otro. La ruta sale de la variable de entorno que declara la receta (`RUTA_VOZ_*`),
    que es cómo el proyecto mantiene las rutas de audio fuera de git.
    """
    vivas: dict[str, list[str]] = {}
    for receta in sorted((config.BASE_DIR / "canales").glob("*/datos/voz-*.json")):
        try:
            datos = json.loads(receta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"  aviso: {receta.name} no se puede leer ({type(exc).__name__}): se ignora")
            continue
        ref = (datos.get("referencia_de_voz") or {}) if isinstance(datos, dict) else {}
        variable = ref.get("variable_entorno") or ref.get("_variable_entorno") or ""
        ruta = ref.get("ruta") or (os.getenv(variable, "") if variable else "")
        if not ruta:
            continue
        quien = f"{receta.parent.parent.name}/{receta.name}" + (f" ({variable})" if variable else "")
        vivas.setdefault(tag_de(Path(ruta)), []).append(quien)
    return vivas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--aplica", action="store_true", help="sin esto solo se dice qué se borraría")
    parser.add_argument("--dias", type=int, default=30, help="edad máxima de trabajos/ (por defecto 30)")
    args = parser.parse_args()

    cache = config.VOICE_CACHE_DIR
    if not cache.exists():
        print(f"No hay caché de voz en {cache}: nada que purgar.")
        return 0

    vivas = referencias_declaradas()
    print(f"Caché: {cache}")
    print(f"Referencias declaradas hoy: {len(vivas)}")
    for tag, quien in sorted(vivas.items()):
        print(f"  {tag} ← {', '.join(quien)}")

    huerfanos = [f for f in sorted(cache.glob("*.wav")) if (m := RECORTE.match(f.name)) and m["tag"] not in vivas]
    print(f"\nRecortes huérfanos: {len(huerfanos)}")
    liberado = 0
    for f in huerfanos:
        liberado += f.stat().st_size
        print(f"  {'borrado' if args.aplica else 'se borraría'}: {f.name} ({f.stat().st_size / 1e6:.1f} MB)")
        if args.aplica:
            f.unlink()

    trabajos = cache / "trabajos"
    viejos = []
    if trabajos.exists():
        limite = time.time() - args.dias * 86400
        viejos = [f for f in sorted(trabajos.iterdir()) if f.is_file() and f.stat().st_mtime < limite]
        print(f"\nTrabajos de más de {args.dias} días: {len(viejos)} de {len(list(trabajos.iterdir()))}")
        for f in viejos:
            liberado += f.stat().st_size
            if args.aplica:
                f.unlink()

    print(f"\n{'Liberado' if args.aplica else 'Se liberaría'}: {liberado / 1e6:.1f} MB")
    if not args.aplica and (huerfanos or viejos):
        print("Nada se ha borrado. Repite con --aplica.")
    if args.aplica and huerfanos:
        print(
            "Los recortes borrados se regeneran solos la próxima vez que se use su referencia "
            "(segundos de CPU): la caché no es un archivo."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
