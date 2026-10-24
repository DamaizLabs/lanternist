"""Limpia el audio narrado usando las marcas de palabra del alineador (06-09).

**El problema, en una frase**: lo que suena en las pausas es lo que Chatterbox genera cuando ya no
le queda texto, y por NIVEL es indistinguible del final de una palabra. Los dos son flojos, duran
un par de décimas y mueren contra el silencio. Un filtro por decibelios se comió la «nt» de
«important» y se oyó al momento (addendum, filas 88 y 90).

**La solución**: saber dónde hay palabras. El pipeline ya lo sabe — `whisper-small` produce marcas
por palabra en cada run para el karaoke (F2.13) — y aquí esas marcas se usan para otra cosa mucho
más simple: separar voz de no-voz. Es el mecanismo de `video-use`, que transcribe con ElevenLabs
Scribe para lo mismo, pero **con el reconocedor que ya está en esta máquina**: en local, sin clave
y sin que el audio salga del PC (decisión 6).

**Dónde encaja.** Corre al final de la etapa `tts`, sobre los wav recién generados y antes de que el
montaje los meta en el vídeo. El alineador se lanza aquí una vez (~2 min) y **no sustituye** al de
los subtítulos: aquel corre después, sobre el audio ya limpio, y sus marcas son las que sincronizan
el karaoke.

**Es del canal** (F4.9): un canal declara `segmentacion.limpieza_por_marcas` en su receta de voz, o
lo pone a `null` si su motor no deja colas — un canal que use Kokoro, que no alucina sonido al quedarse sin
texto.
"""

import json
import subprocess
from pathlib import Path

from lib.alineador import alinea
from lib.config import VOICE_PYTHON, VOICE_TIMEOUT

LIMPIA_WORKER = Path(__file__).resolve().parent / "limpia_worker.py"

# **Las claves que el filtro lee de verdad, en un solo sitio.** Estaban escritas a mano en dos
# ficheros y las dos listas se quedaron cortas: la del trabajo apagó dos filtros en silencio
# (addendum fila 98) y la del guardián de la receta olvidó las tres que gobiernan borrado de audio.
# Se derivan de aquí, y quien añada un umbral al worker tiene que añadirlo aquí para que el canal
# esté obligado a declararlo. `rampa_ms` NO está: el worker funde con `margen_ms` y un número que
# nadie lee invita a ajustarlo sin efecto.
CLAVES_DE_LIMPIEZA = (
    "modelo_alineacion",
    "margen_ms",
    "techo_db",
    "minimo_ms",
    "cola_caida_db",
    "cola_minima_ms",
    "cabeza_minima_ms",
    "isla_techo_db",
    "isla_minima_ms",
    "muletilla_maxima_ms",
)
_RECORDS_FILENAME = "limpieza-voz.json"


class LimpiezaError(RuntimeError):
    """La limpieza por marcas no pudo completarse. No se reintenta."""


def _muletillas(sobrantes: list[dict], palabras: list[str], techo_s: float) -> list[dict]:
    """De lo que el alineador oyó y el guion no coloca, lo que de verdad puso el MOTOR.

    **La distinción es la que salva el episodio, y la trajo una auditoría.** `marcas_sobrantes()`
    devuelve todo lo que el emparejamiento no supo colocar, y eso mezcla dos cosas muy distintas:
    una muletilla que el motor se inventó, y un fallo del reconocedor sobre habla que sí existe.
    Medido sobre el episodio 1 de un canal —15 sobrantes—, **13 eran lo segundo**:

    - **una alucinación de 29,94 s** en la lámina 1: whisper transcribe «Thank you very much for your
      time.» encima de treinta segundos de narración real, con las seis palabras siguientes
      colapsadas en el mismo instante. Es su alucinación de manual sobre audio largo.
    - **palabras del guion mal casadas**: «The», «on», «family.» — el cupo de `marcas_sobrantes` se
      agota cuando el reconocedor oye una vez más de las que el guion tiene, y entonces sobra una
      aparición legítima.

    Callarlas habría borrado **33,28 s de narración**, que es exactamente el desastre de las filas
    85 y 90 por un camino nuevo. Así que la evidencia de texto se exige por partida doble:

    1. **El texto no aparece NI UNA VEZ en el guion de la lámina.** Un «Um…» no está en ninguna
       parte; un «laughed» que el motor repite, sí. Con esto la repetición añadida se respeta —queda
       sonando— y ese es el lado seguro del error: dejar un ruido es peor que comerse una palabra,
       pero comerse una palabra es mucho peor que dejar un ruido.
    2. **Dura menos que `muletilla_maxima_ms`.** Una muletilla es corta —la que originó todo esto
       medía 1,82 s— y treinta segundos no son una muletilla: son el reconocedor perdido.
    """
    from lib.alineacion import _normaliza

    del_guion = {_normaliza(p) for p in palabras}
    fuera = []
    for s in sobrantes:
        if float(s["hasta"]) - float(s["desde"]) <= 0:
            continue  # marca colapsada: no ocupa audio, no hay nada que callar
        if float(s["hasta"]) - float(s["desde"]) > techo_s:
            continue  # demasiado larga para ser una muletilla: el reconocedor se perdió ahí
        if _normaliza(s["texto"]) in del_guion:
            continue  # el guion dice esa palabra: si sobra, es que el emparejamiento falló
        fuera.append(s)
    return fuera


def _cola_del_final(palabras: list[str], marcas: list[dict]) -> list[dict]:
    """Lo que suene DESPUÉS de la última palabra del guion. Ahí ya no hay narración que perder.

    **Es el último ruido que se oyó** —«en el minuto 5:04 se escucha el único ruido de todo el
    vídeo»—: al acabar la lámina 5, después de «Happy birthday, Mum.» quedaban 790 ms sonando a
    −5 dB. El filtro los vio y **decidió respetarlos**, aplicando su regla de seguridad: «suena
    fuerte fuera de las palabras, luego el reconocedor se perdió ahí, y borrar habla es peor que
    dejar un ruido».

    Esa regla es buena en mitad de una lámina y no vale al final, porque ahí **el guion se ha
    terminado**: si la última palabra está anclada, no queda texto por colocar y lo que suene
    después lo puso el motor. La condición de la última palabra es lo que mantiene la garantía — si
    el reconocedor perdió el final, no se toca nada.
    """
    if not palabras or not marcas:
        return []
    from lib.alineacion import _empareja_indices

    emparejadas = _empareja_indices(palabras, marcas)
    if len(palabras) - 1 not in emparejadas:
        return []  # la última palabra no está anclada: puede quedar narración sin colocar
    ultima = float(marcas[emparejadas[len(palabras) - 1]]["hasta"])
    return [{"desde": round(ultima, 3), "hasta": 1e9, "texto": "(después de la última palabra)"}]


def _un_item(item: dict, marcas: list[dict], texto: str, minimo_s: float, techo_muletilla_s: float) -> dict:
    """Separa lo que el alineador reconoció DEL GUION de lo que se inventó.

    Las marcas construyen la zona protegida —donde no se toca nada—. Lo que sale de aquí como
    `sobrantes` es evidencia de TEXTO, y llega por tres caminos:

    - **`_muletillas`**: el alineador lo oyó y el guion **no lo dice en ninguna parte**. Es el «Um…»
      de la lámina 4, que sonaba a -0,8 dB —casi a plena voz—, así que ningún techo lo habría
      cazado. La pertenencia al guion y el techo de duración son la guarda que impide confundirlo
      con un fallo del reconocedor, que es lo mayoritario cuando algo no empareja.
    - **`huecos_sin_guion`**: entre dos palabras SEGUIDAS del guion, donde por definición no falta
      narración. Es el ruido de 1,46 s entre «hold it.» y «He held it», que el alineador ni siquiera
      transcribió — no había marca que pudiera sobrar.
    - **`_cola_del_final`**: lo que suene tras la última palabra del guion, si esa palabra está
      anclada. Fue el último ruido que se oyó, en el minuto 5:04.

    Las tres se callan sin mirar el nivel, porque en las tres la evidencia es el texto. Y las dos
    que nacen de una marca **salen además de la zona protegida**: si no, el worker no las ve.
    """
    from lib.alineacion import huecos_sin_guion, marcas_sobrantes

    palabras = " ".join(texto.split()).split()
    muletillas = _muletillas(marcas_sobrantes(palabras, marcas), palabras, techo_muletilla_s)
    cola = _cola_del_final(palabras, marcas)
    # Las tres listas se tratan igual —callar sin mirar el nivel— porque las tres son evidencia de
    # TEXTO: la primera dice «esto lo oyó y el guion no lo dice en ninguna parte», la segunda «aquí
    # el guion no tiene nada» y la tercera «aquí el guion ya se ha terminado».
    # **Cada tramo dice de qué señal viene, y el worker lo necesita para no ensanchar de más.** Las
    # tres se callan sin mirar el nivel, pero solo dos pueden permitirse callar el HUECO ENTERO en el
    # que caen: en un hueco sin guion y después de la última palabra, el guion demuestra que no falta
    # narración en ningún punto del hueco. Para una muletilla el argumento solo alcanza a lo que ella
    # ocupa; lo que haya alrededor vuelve a pasar por el techo de nivel.
    fuera = [{"desde": s["desde"], "hasta": s["hasta"], "texto": s["texto"], "tipo": "muletilla"} for s in muletillas]
    fuera += [dict(h, tipo="hueco") for h in huecos_sin_guion(palabras, marcas, minimo_s)]
    fuera += [dict(c, tipo="cola") for c in cola]
    # **Lo declarado sobrante NO puede ser a la vez zona protegida, y eso dejó un filtro MUERTO en
    # producción.** El worker calla un sobrante en la rama que recorre los HUECOS entre palabras; si
    # su marca sigue en la lista de marcas no hay hueco ahí, así que la rama no se evalúa nunca: 15
    # de 15 muletillas seguían sonando y el informe salía verde. Lo cazó la auditoría del 06-09 y es
    # el patrón de la fila 98 por otro camino — un arreglo que apaga otro filtro sin decirlo.
    # Se quitan por ÍNDICE, que es exacto, y **solo las dos señales que no pueden pisar narración**:
    # la muletilla que el guion no dice en ninguna parte y lo que suene tras la última palabra.
    tras_el_final = float(cola[0]["desde"]) if cola else None
    sobra = {s["indice"] for s in muletillas}
    protegidas = [
        m
        for j, m in enumerate(marcas)
        if j not in sobra and (tras_el_final is None or float(m["desde"]) < tras_el_final)
    ]
    return {
        "audio": item["audio"],
        # **Todas las marcas MENOS lo ya declarado sobrante.** Filtrar por «casa con el guion»
        # dejaba sin proteger lo que el alineador oyo y el emparejamiento no supo colocar, y eso es
        # habla: el arranque de 99 palabras se quedo hundido y varios en silencio absoluto. Se
        # oyo — «cuando comienza una frase la primera palabra la empieza en un volumen bajo y sube de
        # forma repentina». Por eso la zona protegida sigue siendo TODO lo que se oyo, salvo los dos
        # casos en los que el guion demuestra que ahi no puede haber narracion.
        "marcas": protegidas,
        "sobrantes": fuera,
    }


def limpia_lote(audios: list[str], textos: list[str], trabajo_dir: Path, ajustes: dict | None) -> dict:
    """Alinea cada audio con su texto y calla lo que suena fuera de las palabras.

    Devuelve el informe, que se guarda al lado del audio: cuántos tramos se callaron, cuántos
    segundos, y **cuáles se respetaron por sonar fuerte** — esos últimos son la señal de que el
    reconocedor se perdió ahí, y verlos es lo que permite ajustar el techo con datos.
    """
    if not ajustes:
        return {"aplicada": False, "motivo": "el canal no declara `limpieza_por_marcas`"}

    trabajo_dir = Path(trabajo_dir)
    trabajo_dir.mkdir(parents=True, exist_ok=True)
    items = [{"id": Path(a).stem, "audio": str(a)} for a in audios]

    print(f"  [LIMPIEZA] alineando {len(items)} audio(s) con {ajustes['modelo_alineacion']}", flush=True)
    alineacion = alinea(items, trabajo_dir, {"modelo_alineacion": ajustes["modelo_alineacion"]})
    por_id = {i["id"]: i for i in alineacion["items"]}

    trabajo = trabajo_dir / "limpieza-trabajo.json"
    resultado = trabajo_dir / "limpieza-resultado.json"
    trabajo.write_text(
        json.dumps(
            {
                # **Todos los ajustes menos el modelo**, y no una lista escrita a mano: una lista
                # se queda corta en cuanto se añade un umbral, y eso ya pasó — `apaga_colas` y
                # `apaga_islas` no recibían los suyos y no hacían nada, en silencio.
                "ajustes": {k: v for k, v in ajustes.items() if k != "modelo_alineacion"},
                "items": [
                    _un_item(
                        item,
                        por_id[item["id"]]["marcas"],
                        texto,
                        float(ajustes["minimo_ms"]) / 1000,
                        float(ajustes["muletilla_maxima_ms"]) / 1000,
                    )
                    for item, texto in zip(items, textos)
                    if item["id"] in por_id
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    proceso = subprocess.run(
        [VOICE_PYTHON, str(LIMPIA_WORKER), "--trabajo", str(trabajo), "--resultado", str(resultado)],
        timeout=VOICE_TIMEOUT,
    )
    if proceso.returncode != 0 or not resultado.exists():
        raise LimpiezaError(
            f"la limpieza por marcas falló (código {proceso.returncode}). No se reintenta: un fallo "
            "del runtime local es un dato, no algo que se disimule repitiendo la llamada."
        )

    informe = json.loads(resultado.read_text(encoding="utf-8"))
    tramos = sum(i["tramos_callados"] for i in informe["items"])
    segundos = round(sum(i["segundos_callados"] for i in informe["items"]), 2)
    respetados = sum(len(i["sonaban_fuerte_y_se_respetan"]) for i in informe["items"])
    print(
        f"  [LIMPIEZA] {tramos} tramos callados ({segundos}s) · {respetados} respetados por sonar "
        f"por encima de {ajustes['techo_db']} dB",
        flush=True,
    )

    from collections import Counter

    por_regla = Counter(c["regla"] for i in informe["items"] for c in i.get("callados", []))
    informe.update(
        {
            "aplicada": True,
            # **El desglose por regla, para que el informe se pueda auditar sin reproducir el filtro.**
            # Publicaba dos conteos y con eso una señal apagada pasa inadvertida: es lo que ocurrió
            # con la señal por texto, muerta en producción con el informe en verde.
            "callados_por_regla": dict(por_regla),
            "ajustes": ajustes,
            "tramos_callados": tramos,
            "segundos_callados": segundos,
            "respetados_por_sonar_fuerte": respetados,
            "_que_es_esto": (
                "Lo que suena FUERA de las palabras que reconoció el alineador, callado con rampa. "
                "Las tres condiciones se exigen a la vez —fuera de palabra, por debajo del techo y "
                "más largo que el mínimo— porque un reconocedor falla, y en este mismo episodio "
                "falló: para comerse habla harían falta las tres. Los tramos "
                "`sonaban_fuerte_y_se_respetan` son justo donde el alineador se perdió, y se dejan "
                "sonando a propósito."
            ),
        }
    )
    (trabajo_dir / _RECORDS_FILENAME).write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding="utf-8")
    return informe
