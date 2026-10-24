"""Saca del guion los tramos de diálogo y quién los dice, para el karaoke por personaje.

Lo que produce va al `slides.json` del run (`slides[].hablantes`) como tramos de ÍNDICES DE PALABRA:
`{"desde": 12, "hasta": 20, "personaje": "Nora"}`. Se declara ahí y no se adivina en el pipeline
porque quien escribe el guion sabe quién habla, y un parser se equivoca justo en los casos difíciles.

**Este script propone, no decide.** Marca `personaje: null` lo que no puede atribuir con seguridad,
y eso hay que resolverlo mirando el guion antes de producir: un diálogo pintado del color equivocado
confunde más que uno sin color.

Correr:  .venv\\Scripts\\python scripts/hablantes.py <run_id>
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import subtitulos  # noqa: E402
from lib.config import CANAL_VIDEOS_DIR  # noqa: E402

# Verbos con los que un guion atribuye una linea. `said` es el 90 %, pero no el 100.
# El pronombre de cada personaje lo declara el PERFIL DEL CANAL (`subtitulos.personajes[].pronombre`)
# y llega en `reparto`: el estudio conoce la gramatica, no sabe quien es Nora (F4.9).
DECIR = r"(?:said|asked|whispered|shouted|replied|answered|added|cried)"


def tramos(narracion: str, reparto: dict[str, str], parrafos: list[int] | None = None) -> list[dict]:
    """Los tramos entrecomillados con su personaje, en índices de palabra.

    `reparto` es {nombre: pronombre} tal y como lo declara el perfil del canal.

    `parrafos` son los índices de PALABRA donde empieza cada párrafo del guion. Sin ellos el
    parser trabaja a ciegas justo en lo único que distingue «sigue hablando el mismo» de «le
    contesta el otro», porque en el texto aplanado los dos casos se escriben igual:

        mismo turno       Ollie said, "I know." "I can see that."
        turno contrario   Nora said, "...In that order."  ¶  "How do you know that?"

    Sin esa frontera la segunda se pintaba de Nora, y la pregunta la hace Ollie.
    """
    palabras = narracion.split()
    # posición de inicio de cada palabra dentro del texto plano, para pasar de caracteres a índices
    posiciones, cursor = [], 0
    for palabra in palabras:
        cursor = narracion.index(palabra, cursor)
        posiciones.append(cursor)
        cursor += len(palabra)

    def indice_de(caracter: int) -> int:
        return max(0, sum(1 for p in posiciones if p < caracter) - 1)

    nombres = "|".join(sorted(reparto, key=len, reverse=True))
    cortes = sorted(parrafos or [])

    def inicio_del_parrafo(indice: int) -> int:
        """Índice de palabra donde arranca el párrafo que contiene esa palabra."""
        previos = [c for c in cortes if c <= indice]
        return previos[-1] if previos else 0

    salida = []
    for cita in re.finditer(r'"([^"]+)"', narracion):
        ini, fin = cita.span()
        cola = narracion[fin : fin + 60]
        cabeza = narracion[max(0, ini - 60) : ini]
        quien = None
        # **La atribucion de DETRAS solo vale si la cita acaba en coma.** En ingles la coma va dentro
        # de las comillas —`"...," said Nora`— asi que ese es el unico caso en que lo que viene
        # despues pertenece a ESTA cita. Sin esa condicion, con el guion reescrito el 05-09 (la
        # atribucion delante), lo que hay detras de una cita es la atribucion de la SIGUIENTE: la
        # linea «Stop cleaning. You are making it worse.» se pintaba de Ollie porque detras venia
        # «Ollie said, "I know."», y la dice Nora. Un color equivocado confunde mas que ninguno.
        acaba_en_coma = cita.group(1).rstrip().endswith(",")
        despues = None
        if acaba_en_coma:
            despues = re.match(rf"[,.]?\s+{DECIR}\s+({nombres})", cola) or re.match(
                rf"[,.]?\s+({nombres})\s+{DECIR}", cola
            )
        antes = re.search(rf"({nombres})\s+{DECIR}[,:]?\s*$", cabeza)
        if despues:
            quien = despues.group(1)
        elif antes:
            quien = antes.group(1)
        salida.append(
            {
                "desde": indice_de(ini) + 1,
                "hasta": indice_de(fin - 1) + 1,
                "personaje": quien,
                "_texto": cita.group(1)[:64],
                "_cabeza": cabeza,
                "_cola": cola[:40],
                "_ini": ini,
                # La PRIMERA palabra de la cita, en indice 1. No vale `desde`, que apunta a la
                # anterior: con ese desfase, una cita que ABRE un parrafo caia en el parrafo de
                # antes y la continuacion volvia a cruzar el corte que se acababa de poner.
                "_palabra": sum(1 for pos in posiciones if pos < ini) + 1,
                "_fin": fin,
            }
        )

    # --- dos reglas mas, que resuelven la mayoria de los huecos ---
    #
    # 1. PRONOMBRE: «"I know," she said» no nombra a nadie, pero el sujeto es el ultimo personaje
    #    nombrado de ese genero. Es la convencion de cualquier narracion en tercera persona.
    # 2. CONTINUACION: una cita sin atribucion que sigue de cerca a otra ya atribuida, sin que entre
    #    medias se nombre a otro personaje, la dice el mismo. Es como se escribe un dialogo seguido:
    #    «"We are going to make a cake," said Nora. "A big one."»
    genero = reparto
    for i, tramo in enumerate(salida):
        if tramo["personaje"]:
            continue
        pronombre = re.match(rf"[,.]?\s+(he|she)\s+{DECIR}", tramo["_cola"], re.I)
        if pronombre:
            buscado = pronombre.group(1).lower()
            previos = [n for n in re.findall(rf"({nombres})", tramo["_cabeza"]) if genero.get(n) == buscado]
            if previos:
                tramo["personaje"] = previos[-1]
                tramo["_regla"] = "pronombre"
                continue
        # 3. ACCION: «Ollie looked at the clock. "Mum usually wakes up at nine."» no lleva verbo de
        #    decir, pero el guion ya ha puesto a alguien en escena. Vale el ultimo personaje nombrado
        #    DENTRO DEL MISMO PARRAFO: fuera de el ya no esta hablando de quien tiene el turno.
        arranque = inicio_del_parrafo(tramo["_palabra"])
        del_parrafo = " ".join(palabras[arranque - 1 : tramo["_palabra"] - 1])
        # Solo la voz del NARRADOR: un nombre dicho dentro de una cita no atribuye nada. Sin quitar
        # las citas, «Ollie said, "Mum." "Mum is coming."» daba Mum, y habla Ollie.
        narrador = re.sub(r'"[^"]*"?', " ", del_parrafo)
        nombrados = re.findall(rf"({nombres})", narrador)
        if nombrados:
            tramo["personaje"] = nombrados[-1]
            tramo["_regla"] = "accion"
            continue
        if i:
            anterior = salida[i - 1]
            # **La continuacion NO cruza el parrafo.** Es la regla del dialogo seguido —«Ollie said,
            # "I know." "I can see that."»— y un parrafo nuevo es justo la senal contraria: cambio de
            # turno. Sin esta condicion, «How do you know that?» se pintaba de Nora cuando pregunta
            # Ollie, y «Is there a cake in the oven?» de Ollie cuando pregunta Mum.
            mismo_parrafo = inicio_del_parrafo(anterior["_palabra"]) == arranque
            entre = narracion[anterior["_fin"] : tramo["_ini"]]
            otros = {n for n in re.findall(rf"({nombres})", entre) if n != anterior["personaje"]}
            if anterior["personaje"] and mismo_parrafo and len(entre.split()) <= 12 and not otros:
                tramo["personaje"] = anterior["personaje"]
                tramo["_regla"] = "continuacion"

    for tramo in salida:
        for clave in ("_cabeza", "_cola", "_ini", "_fin", "_palabra"):
            tramo.pop(clave, None)
    return salida


if __name__ == "__main__":
    run_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not run_id:
        raise SystemExit("uso: hablantes.py <run_id>")
    run = CANAL_VIDEOS_DIR / run_id
    slides = json.loads((run / "slides.json").read_text(encoding="utf-8"))["slides"]
    reparto = {n: f["pronombre"] for n, f in subtitulos.personajes().items()}
    if not reparto:
        raise SystemExit("[FAIL] el perfil declara `subtitulos.personajes: {}`: este canal no tiene dialogos")

    # **TODAS las laminas.** Nacio con un run de una sola y se quedo leyendo `slides[0]`: con seis
    # revisaba 63 de las 1024 palabras y daba por bueno el resto sin mirarlo. Mismo defecto que tuvo
    # el auditor del .ass, y por el mismo motivo.
    propuesta, sin_atribuir = {}, []
    for slide in slides:
        n = slide["slide_number"]
        # Sobre lo que SE PINTA: los índices de cada tramo se usan luego para colorear palabras del
        # karaoke, y `lib/subtitulos` los cuenta sobre el texto ya limpio de etiquetas y de signos de
        # apertura. Contarlos aquí sobre la narración cruda los desplazaría (10-09; entonces el primer canal no tenía
        # reparto y ningún guion trae un signo suelto como palabra, así que no había daño todavía).
        encontrados = tramos(
            subtitulos.texto_para_pintar(slide.get("narration") or ""), reparto, slide.get("_parrafos")
        )
        propuesta[str(n)] = encontrados
        sin_atribuir += [(n, t) for t in encontrados if not t["personaje"]]
        print(f"lamina {n} · {len(encontrados)} tramos")
        for t in encontrados:
            print(f"  [{t['desde']:4d}-{t['hasta']:4d}] {t['personaje'] or '¿?':<6} «{t['_texto']}»")
        print()

    total = sum(len(v) for v in propuesta.values())
    print(f"{total} tramos de dialogo en {len(slides)} laminas · {len(sin_atribuir)} sin atribuir")
    destino = run / "hablantes-propuesta.json"
    destino.write_text(json.dumps(propuesta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"propuesta en {destino}")
    if sin_atribuir:
        print("REVISA los `¿?` antes de meterlos en slides.json: un color equivocado confunde más que ninguno")
