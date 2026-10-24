"""Rehace láminas de un run por EDICIÓN POR INSTRUCCIÓN sobre una foto real de la pieza.

Es el paso (3) de la regla del estudio de la fila 147 del addendum: cuando el modelo no conoce un
objeto —lo sustituye por el arquetipo que sí conoce— no se insiste con el prompt, se parte de una
imagen real y se replica con `Qwen-Image-Edit` (`workflows/qwen-edit-tinta.json`).

**Por qué existe este script y no se sigue haciendo a mano.** La regla está escrita desde el 11-09 y
se ha aplicado dos veces —la jaula de gibbet y la brida de regaño—, las dos con código de usar y
tirar que ya no está. La tercera vez fue la pera de la angustia, con **20 de 33 láminas dibujando un
objeto inventado** que llegó hasta un borrador subido. Un paso del pipeline del estudio que solo
existe en la memoria de una sesión se vuelve a improvisar cada vez.

Entrada: el `instrucciones.json` que prepara Claude en sesión, con la forma del precedente:

    {
      "_cola_comun": "lo que se repite en todas: estilo, acento y las negativas del canal",
      "referencias": {"alias": "fichero.jpg"},          # dentro de la carpeta de referencias
      "laminas": {"7": {"referencia": "alias", "instruccion": "..."}}
    }

Las tres reglas medidas que gobiernan ese JSON —la pose de la referencia gana sobre el texto, una
sola referencia hace todas las láminas iguales, y hay palabras que arrastran el arquetipo malo
(`cage`, `pear`)— son del que lo escribe, no de este script, que solo ejecuta.

Uso:
    .venv\\Scripts\\python scripts/edita_laminas.py --run <run_id> \\
        --instrucciones experimentos/pera-laminas-edit-2026-09-17/instrucciones.json \\
        --referencias experimentos/pera-referencia-2026-09-17
    ... --seco        # construye los grafos y NO toca la GPU: para comprobar antes de gastar
    ... --solo 2,7    # solo esas láminas
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import comfy_client as cc  # noqa: E402
from lib.config import (  # noqa: E402
    CANAL_VIDEOS_DIR,
    COMFY_ROOT,
    IMAGE_GEN_HEIGHT,
    IMAGE_GEN_WIDTH,
    IMAGE_SEED,
)

WORKFLOW = "qwen-edit-tinta"


def carga(ruta: Path) -> dict:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"no existe {ruta}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{ruta} no es JSON válido: {exc}") from None


def encaja_en_lienzo(origen_ruta: Path, destino_ruta: Path) -> tuple[int, int]:
    """Encaja la referencia ENTERA en un lienzo del tamaño de una lámina del canal.

    **Sin esto, cada lámina sale con la forma de su foto.** Medido el 17-09: el grafo de edición
    codifica la referencia tal cual (`VAEEncode` cuelga de `LoadImage`), así que el latente hereda
    su tamaño y la salida también. Las ocho primeras láminas de la pera salieron en 0.77, 1.50 y
    1.36 de proporción — verticales y cuadradas— para un vídeo que es 16:9, y eso no lo arregla
    ningún recorte posterior sin comerse la composición.

    Se encaja entera (no se recorta) y el hueco se rellena con el color del borde, que es lo que
    menos estorba: el modelo reinterpreta la escena de todas formas y la instrucción ya le dice qué
    hay alrededor. Recortar a 16:9 una foto vertical partiría la pieza, que es justo lo que se
    viene a arreglar.
    """
    from PIL import Image  # local: solo hace falta aquí, y el script se usa poco

    with Image.open(origen_ruta) as im:
        im = im.convert("RGB")
        escala = min(IMAGE_GEN_WIDTH / im.width, IMAGE_GEN_HEIGHT / im.height)
        nuevo = (max(1, round(im.width * escala)), max(1, round(im.height * escala)))
        pieza = im.resize(nuevo, Image.LANCZOS)
        borde = im.resize((1, 1), Image.LANCZOS).getpixel((0, 0))
        lienzo = Image.new("RGB", (IMAGE_GEN_WIDTH, IMAGE_GEN_HEIGHT), borde)
        lienzo.paste(pieza, ((IMAGE_GEN_WIDTH - nuevo[0]) // 2, (IMAGE_GEN_HEIGHT - nuevo[1]) // 2))
        lienzo.save(destino_ruta)
    return nuevo


def copia_referencias(referencias: dict, origen: Path) -> dict:
    """Deja cada referencia en el `input/` de ComfyUI, que es de donde la lee `LoadImage`.

    Se copian con un prefijo propio para no pisar nada de ComfyUI ni depender de lo que hubiera
    allí de una sesión anterior, y **encajadas en el lienzo del canal** (ver `encaja_en_lienzo`).
    """
    # COMFY_ROOT no tiene valor por defecto (OC1.3): sin él, el `mkdir` crearía una carpeta suelta donde se lance esto.
    if not COMFY_ROOT.is_dir():
        raise SystemExit(f"no está ComfyUI en {COMFY_ROOT}: escribe COMFY_ROOT en el .env (`pipeline.py --check`)")
    destino_dir = COMFY_ROOT / "input"
    destino_dir.mkdir(parents=True, exist_ok=True)
    mapa = {}
    for alias, fichero in referencias.items():
        origen_ruta = origen / fichero
        if not origen_ruta.is_file():
            raise SystemExit(f"la referencia «{alias}» apunta a {origen_ruta}, que no existe")
        nombre = f"ref-{alias}.png"
        dentro = encaja_en_lienzo(origen_ruta, destino_dir / nombre)
        lienzo = f"{IMAGE_GEN_WIDTH}x{IMAGE_GEN_HEIGHT}"
        print(f"  referencia «{alias}»: {fichero} → {dentro[0]}x{dentro[1]} dentro de {lienzo}")
        mapa[alias] = nombre
    return mapa


def main() -> int:
    p = argparse.ArgumentParser(description="Rehace láminas por edición por instrucción")
    p.add_argument("--run", required=True, help="run_id cuyas láminas se rehacen")
    p.add_argument("--instrucciones", required=True)
    p.add_argument("--referencias", required=True, help="carpeta con las imágenes y su fichas.json")
    p.add_argument("--solo", default="", help="lista de láminas separadas por comas")
    p.add_argument("--seco", action="store_true", help="construye los grafos y no toca la GPU")
    args = p.parse_args()

    plan = carga(Path(args.instrucciones))
    # **El estilo va en la CABECERA, no en la cola**, y no es un detalle de formato: medido el
    # 17-09 con la pera de la angustia, la misma frase de estilo al final de una cola larga dio 8
    # láminas fotográficas seguidas —la referencia ES una foto y el modelo la conserva—. Lo primero
    # pesa más en un modelo de edición. La cola se queda con lo que describe la escena.
    cabecera = (plan.get("_cabecera_comun") or "").strip()
    cola = (plan.get("_cola_comun") or "").strip()
    laminas = plan.get("laminas") or {}
    if not laminas:
        raise SystemExit("el plan no trae ninguna lámina")

    pedidas = [n.strip() for n in args.solo.split(",") if n.strip()] if args.solo else list(laminas)
    faltan = [n for n in pedidas if n not in laminas]
    if faltan:
        raise SystemExit(f"el plan no tiene instrucción para la(s) lámina(s) {faltan}")

    origen = Path(args.referencias)
    mapa = copia_referencias(plan["referencias"], origen)

    # El canal sale de `CANAL_ACTIVO`, como en todo el pipeline: para editar las láminas de otro
    # canal se fija la variable en el entorno del proceso, no con un flag propio de este script.
    destino = CANAL_VIDEOS_DIR / args.run / "slides"
    if not destino.is_dir():
        raise SystemExit(f"no existe la carpeta de láminas del run: {destino}")

    workflow = cc.load_workflow(WORKFLOW)
    print(f"{len(pedidas)} lámina(s) · workflow {WORKFLOW} · referencias en {origen}")
    print(f"destino: {destino}\n")

    if args.seco:
        # El control de que el plan es ejecutable SIN gastar GPU: si un punto de inyección se queda
        # sin valor o una referencia no existe, salta aquí y no a los veinte minutos de tanda.
        for numero in pedidas:
            entrada = laminas[numero]
            texto = " ".join(x for x in (cabecera, entrada["instruccion"], cola) if x)
            cc.build_prompt_graph(
                workflow,
                texto,
                seed=IMAGE_SEED,
                filename_prefix=f"slide-{int(numero):02d}",
                overrides={"imagen": mapa[entrada["referencia"]]},
            )
            print(f"  [seco] lámina {int(numero):02d} · {entrada['referencia']} · {len(texto)} caracteres")
        print("\nEn seco: los grafos se construyen. Quita --seco para generar.")
        return 0

    registros, fallos = [], []
    with cc.comfy_server():
        for i, numero in enumerate(pedidas, 1):
            entrada = laminas[numero]
            texto = " ".join(x for x in (cabecera, entrada["instruccion"], cola) if x)
            salida = destino / f"slide-{int(numero):02d}.png"
            print(f"  [{i}/{len(pedidas)}] slide-{int(numero):02d}.png — {entrada['referencia']}")
            arranque = time.perf_counter()
            try:
                registro = cc.render(
                    workflow,
                    texto,
                    str(salida),
                    seed=IMAGE_SEED,
                    overrides={"imagen": mapa[entrada["referencia"]]},
                )
            except Exception as exc:  # noqa: BLE001 — una lámina que falla no tumba el lote
                fallos.append({"lamina": numero, "error": str(exc)})
                print(f"      [FALLO] {exc}")
                continue
            registro["lamina"] = int(numero)
            registro["referencia"] = entrada["referencia"]
            registro["referencia_archivo"] = plan["referencias"][entrada["referencia"]]
            registros.append(registro)
            print(f"      {round(time.perf_counter() - arranque, 1)}s · {salida}")

    if registros:
        # Se escribe junto a las láminas y con el mismo nombre que usan los demás adaptadores, para
        # que la procedencia del run recoja estas igual que las generadas desde texto (decisión 5).
        cc._dump_records(destino, registros)

    print(f"\n{len(registros)} lámina(s) rehecha(s)" + (f" · {len(fallos)} fallo(s)" if fallos else ""))
    for f in fallos:
        print(f"  lámina {f['lamina']}: {f['error']}")
    print(
        "\nSIGUIENTE PASO: mirar las láminas rehechas, y si el run ya estaba montado, relanzar "
        "assembly y thumbnail — la miniatura sale de una lámina y puede ser una de estas."
    )
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
