"""El núcleo que empareja el texto del guion con las marcas de tiempo del alineador (F6.2b).

**Por qué vive aparte.** Nació dentro de `lib/subtitulos.py` para el karaoke quemado (F2.13), y desde
el 06-09 lo usan otras tres piezas que no pintan subtítulos: la limpieza de voz (`lib/limpia_voz.py`),
la integridad de la narración (`lib/integridad_narracion.py`) y, desde F6.2b, la línea de tiempo del
motor de escena (`lib/escena/linea_tiempo.py`). El karaoke quemado se retira en F6.7 y esto no puede
irse con él. Se extrajo **sin cambiar una línea de comportamiento**: `lib/subtitulos.py` lo reexporta y
su suite sigue igual.

Lo que hay aquí, y nada más:

- `_normaliza`: cómo se comparan dos palabras (sin puntuación ni mayúsculas).
- `_empareja_indices` y `empareja`: Needleman-Wunsch entre las palabras del guion y las oídas, y el
  tiempo de cada palabra del guion (las que no tienen marca lo heredan de sus vecinas).
- `reparte_tiempos_colapsados`: tiempo para las palabras que el alineador dejó en cero.
- `marcas_sobrantes` y `huecos_sin_guion`: lo que el reconocedor oyó y el guion no dice, y los huecos
  entre dos palabras seguidas del guion.
- `marca_hablantes`: quién dice cada palabra, desde los tramos del `slides.json`.
- `texto_para_pintar`: la narración tal como se pinta y se cuenta (sin etiquetas ni «¡¿» fuera del
  español). Los índices de `hablantes` se cuentan sobre este texto, así que todo el que los use tiene
  que partir de aquí.

El lanzador del alineador (el subproceso de `.venv-voz`) no está aquí: es `lib/alineador.py`, que ya
vivía aparte desde el 06-09. Este módulo no lanza nada ni lee el perfil de ningún canal.
"""

from __future__ import annotations

import re
from collections import Counter

from lib.voice_client import sin_etiquetas


class AlineacionError(RuntimeError):
    """No se pudo dar tiempo al guion: ninguna marca, ninguna palabra anclada o un tramo que se sale."""


def _normaliza(palabra: str) -> str:
    """Para comparar palabras: sin puntuación, sin mayúsculas. El texto original no se toca."""
    return re.sub(r"[^\w']", "", palabra).lower()


# Lo menos que puede durar una palabra cantada. Por debajo de esto el karaoke no la pinta: salta.
DURACION_MINIMA_PALABRA_S = 0.06


def reparte_tiempos_colapsados(alineado: list[dict]) -> int:
    """Da tiempo a las palabras que el alineador dejo sin el. Devuelve cuantas tocó.

    **De donde sale** (montaje del 05-09 de un canal, cazado por el auditor). En el segundo 58 whisper
    se perdio durante seis segundos y `empareja` dejo nueve palabras seguidas con `desde == hasta`,
    todas en el instante 58,77 — mas otras con las marcas DESORDENADAS (`down` empezaba antes que
    `They`). El resultado en pantalla: una linea de **0 s** que parpadea, otra de 0,22 s con un
    karaoke de 0,60 s que no cuadra, y el relleno **parado 5,9 s** sobre la linea siguiente.

    Lo que se hace es lo unico honesto cuando no hay marca fiable: **repartir el hueco a partes
    iguales** entre el final de la ultima palabra con tiempo y el principio de la siguiente. No
    inventa sincronia —no la hay—, pero convierte un parpadeo en un relleno que avanza, que es lo
    que el espectador espera ver mientras oye esas palabras.

    Se hace aqui y no en `agrupa` porque el defecto es de la PALABRA: agrupar ya reparte mal si las
    palabras que recibe no tienen duracion.
    """
    tocadas = 0
    i = 0
    while i < len(alineado):
        if alineado[i]["hasta"] - alineado[i]["desde"] >= DURACION_MINIMA_PALABRA_S:
            i += 1
            continue
        # toda la racha seguida de palabras sin tiempo
        j = i
        while j < len(alineado) and alineado[j]["hasta"] - alineado[j]["desde"] < DURACION_MINIMA_PALABRA_S:
            j += 1
        arranca = alineado[i - 1]["hasta"] if i else alineado[i]["desde"]
        acaba = alineado[j]["desde"] if j < len(alineado) else alineado[j - 1]["hasta"]
        hueco = acaba - arranca
        # Sin hueco no hay nada que repartir: se le da el minimo a cada una y que la linea crezca.
        # Es preferible a dejarlas en cero, porque una palabra de 0 s no se llega a pintar.
        paso = max(hueco / (j - i), DURACION_MINIMA_PALABRA_S) if j > i else DURACION_MINIMA_PALABRA_S
        for k in range(i, j):
            alineado[k]["desde"] = arranca + paso * (k - i)
            alineado[k]["hasta"] = arranca + paso * (k - i + 1)
            alineado[k]["anclada"] = False
            tocadas += 1
        i = j
    # Y monotonia: una palabra no puede empezar antes de que acabe la anterior. El alineador las
    # devolvio cruzadas en el mismo tramo, y eso es lo que hacia que dos lineas se encimaran.
    for anterior, palabra in zip(alineado, alineado[1:]):
        if palabra["desde"] < anterior["hasta"]:
            palabra["hasta"] = max(palabra["hasta"], anterior["hasta"] + DURACION_MINIMA_PALABRA_S)
            palabra["desde"] = anterior["hasta"]
            tocadas += 1
    return tocadas


def _empareja_indices(palabras_guion: list[str], marcas: list[dict]) -> dict[int, int]:
    """Qué marca le toca a cada palabra del guion. La clave es el índice de palabra.

    Needleman-Wunsch sobre las palabras normalizadas: coincidencia 0, sustitución/hueco 1. Las
    secuencias son de decenas de palabras, así que el coste cuadrático es irrelevante y compra lo
    que un `zip` no da — que una palabra omitida por el reconocedor no arrastre a las siguientes.
    """
    guion = [_normaliza(p) for p in palabras_guion]
    oido = [_normaliza(m["texto"]) for m in marcas]
    n, m = len(guion), len(oido)

    coste = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        coste[i][0] = i
    for j in range(m + 1):
        coste[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            coste[i][j] = min(
                coste[i - 1][j - 1] + (0 if guion[i - 1] == oido[j - 1] else 1),
                coste[i - 1][j] + 1,
                coste[i][j - 1] + 1,
            )

    # Se recorre la matriz hacia atrás anotando qué marca le toca a cada palabra del guion
    marca_de: dict[int, int] = {}
    i, j = n, m
    while i > 0 and j > 0:
        diagonal = coste[i - 1][j - 1] + (0 if guion[i - 1] == oido[j - 1] else 1)
        if coste[i][j] == diagonal:
            marca_de[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif coste[i][j] == coste[i - 1][j] + 1:
            i -= 1  # palabra del guion que el reconocedor no dijo: queda sin marca
        else:
            j -= 1  # palabra oída que no está en el guion: se ignora
    return marca_de


def marcas_sobrantes(palabras_guion: list[str], marcas: list[dict]) -> list[dict]:
    """Lo que el reconocedor oyó y el guion NO tiene: lo que el motor de voz se inventó.

    **De dónde sale** (06-09). Tras cuatro vueltas buscando el ruido de las pausas por nivel, la
    medición dio la vuelta al problema: los tramos flojos pegados al silencio **no eran ruido**, eran
    los finales de las últimas palabras de cada frase —whisper oye ahí «know.», «eggs.», «pyjamas.»—,
    y por eso el filtro por decibelios se comió la «nt» de «important». Pero entre ellos apareció uno
    distinto: **«Um…», 1,82 s en la lámina 4**, que no está en el guion. Eso sí es del motor.

    El guion se conoce —es la promesa de F2.13— así que la señal está ahí: una marca que no empareja
    con ninguna palabra es una **muletilla**, que es exactamente el defecto que se describió al
    hablar de `video-use` («detecta muletillas, silencios largos, ruidos en las pausas y las
    elimina»). Se usa la MISMA alineación que el karaoke, leída al revés.

    **No decide sola, y su consumidor es MÁS estricto que ella** (06-09): `limpia_voz._muletillas()`
    descarta todo sobrante cuyo texto esté en el guion de la lámina, incluso cuando el cupo de aquí
    dice que sobra una aparición. Así que la repetición añadida —«laughed and laughed and laughed»,
    que el cupo sí caza— **hoy se respeta y queda sonando**, y el audio puede decir una frase dos
    veces mientras el karaoke la muestra una. Es deliberado: en el episodio del piloto, 13 de los 15
    sobrantes eran fallos del reconocedor sobre habla real —una alucinación de 29,94 s entre ellos—,
    y comerse narración es mucho peor que dejar una repetición. Detectarla de verdad pide otra señal
    —dos tramos contiguos que suenan igual—, que está apuntada y sin construir.
    """
    if not palabras_guion or not marcas:
        return []
    emparejadas = set(_empareja_indices(palabras_guion, marcas).values())
    # **Y no basta con que su texto no este en el guion: hay que CONTAR.**
    #
    # Una muletilla como «Um…» no aparece en ninguna parte del guion, y esa es la señal facil. Pero
    # el motor tambien repite: en «She laughed and laughed» dijo «laughed and laughed and laughed»,
    # una vez de mas. Ahi el texto SI esta en el guion, asi que un filtro por pertenencia lo respeta
    # y el audio acaba diciendo algo distinto de lo que el karaoke muestra.
    #
    # Lo que separa una repeticion AÑADIDA de una repeticion legitima mal alineada es cuantas veces
    # suena cada palabra: si el guion tiene dos «laughed» y el reconocedor oye tres, sobra una. Se
    # descartan las que caben en la cuenta del guion, empezando por las primeras.
    cupo = Counter(_normaliza(p) for p in palabras_guion)
    for j in sorted(emparejadas):
        cupo[_normaliza(marcas[j]["texto"])] -= 1

    sobran = []
    for j, m in enumerate(marcas):
        if j in emparejadas:
            continue
        clave = _normaliza(m["texto"])
        if cupo.get(clave, 0) > 0:
            cupo[clave] -= 1  # cabe en el guion: es una repeticion que la alineacion no supo colocar
            continue
        sobran.append(dict(m, indice=j))
    return sobran


def huecos_sin_guion(palabras_guion: list[str], marcas: list[dict], minimo_s: float) -> list[dict]:
    """Los huecos entre dos palabras CONSECUTIVAS del guion. Ahí no puede faltar narración.

    **De dónde sale** (06-09, el último ruido del episodio). Entre «Ollie tried to hold it.» y «He
    held it for one second» hay **1,46 s en los que el alineador no transcribe nada** y sin embargo
    suena algo fuerte. Ninguna de las otras dos señales lo caza: no hay marca que sobre, porque no
    hay marca, y el nivel lo protege por sonar por encima del techo.

    Pero el guion sí lo resuelve, y de forma exacta: si la palabra anterior y la siguiente son
    **seguidas en el guion**, en ese hueco no falta ninguna palabra por colocar — así que lo que
    suene ahí no es narración. Es del motor.

    **Y por eso es seguro donde el nivel no lo era**: cuando el reconocedor se pierde de verdad —como
    en la lámina 2 de este mismo episodio, nueve palabras colapsadas (addendum fila 83)— las palabras
    a los lados del hueco NO son consecutivas, falta gente en medio, y el hueco no entra aquí.
    """
    if not palabras_guion or not marcas:
        return []
    marca_de = _empareja_indices(palabras_guion, marcas)
    salida = []
    for indice in range(len(palabras_guion) - 1):
        aqui, siguiente = marca_de.get(indice), marca_de.get(indice + 1)
        if aqui is None or siguiente is None:
            continue  # falta una palabra por anclar: el hueco puede contener narración
        fin = float(marcas[aqui]["hasta"])
        arranque = float(marcas[siguiente]["desde"])
        # **Y tiene que estar vacio de marcas.** Si el reconocedor oyo algo con forma de palabra ahi
        # dentro, esto no decide: de eso se encarga `marcas_sobrantes`, que mira el texto. Sin esta
        # condicion, el hueco entre «She» y «laughed» —que contiene el «laughed and» de «She laughed
        # and laughed»— se llevaria por delante habla real.
        hay_marcas = any(float(m["hasta"]) > fin and float(m["desde"]) < arranque for m in marcas)
        if arranque - fin >= minimo_s and not hay_marcas:
            salida.append(
                {
                    "desde": round(fin, 3),
                    "hasta": round(arranque, 3),
                    "texto": f"(entre «{palabras_guion[indice]}» y «{palabras_guion[indice + 1]}»)",
                }
            )
    return salida


def empareja(palabras_guion: list[str], marcas: list[dict]) -> list[dict]:
    """Da un tiempo a cada palabra del guion alineando las dos secuencias.

    Needleman-Wunsch sobre las palabras normalizadas: coincidencia 0, sustitución/hueco 1. Las
    secuencias son de decenas de palabras, así que el coste cuadrático es irrelevante y compra
    lo que un `zip` no da — que una palabra omitida por el reconocedor no arrastre a las
    siguientes.

    Una palabra del guion sin marca propia (porque el reconocedor la fundió con otra) hereda el
    tiempo por reparto entre sus vecinas ya ancladas: es mejor que dejarla sin pintar.
    """
    if not palabras_guion:
        return []
    if not marcas:
        raise AlineacionError("no hay ni una marca de tiempo: la alineación no produjo nada")

    marca_de = _empareja_indices(palabras_guion, marcas)

    alineado: list[dict] = []
    for indice, palabra in enumerate(palabras_guion):
        anclada = marca_de.get(indice)
        alineado.append(
            {
                "palabra": palabra,
                "desde": float(marcas[anclada]["desde"]) if anclada is not None else None,
                "hasta": float(marcas[anclada]["hasta"]) if anclada is not None else None,
                "anclada": anclada is not None,
            }
        )

    _rellena_huecos(alineado)
    return alineado


def _rellena_huecos(alineado: list[dict]) -> None:
    """Reparte tiempo entre anclas para las palabras que se quedaron sin marca."""
    anclas = [i for i, p in enumerate(alineado) if p["anclada"]]
    if not anclas:
        raise AlineacionError("ninguna palabra del guion se pudo anclar a una marca de tiempo")

    # Cabeza y cola: se estiran desde la primera y la última ancla
    primera, ultima = anclas[0], anclas[-1]
    for i in range(primera):
        paso = alineado[primera]["desde"] / (primera + 1)
        alineado[i]["desde"], alineado[i]["hasta"] = paso * i, paso * (i + 1)
    for i in range(ultima + 1, len(alineado)):
        anterior = alineado[i - 1]["hasta"]
        alineado[i]["desde"], alineado[i]["hasta"] = anterior, anterior + 0.25

    # Huecos interiores: reparto uniforme entre las dos anclas que los rodean
    for a, b in zip(anclas, anclas[1:], strict=False):
        if b - a < 2:
            continue
        inicio, fin = alineado[a]["hasta"], alineado[b]["desde"]
        cuantas = b - a - 1
        paso = max(0.05, (fin - inicio) / cuantas)
        for k in range(1, cuantas + 1):
            alineado[a + k]["desde"] = inicio + paso * (k - 1)
            alineado[a + k]["hasta"] = inicio + paso * k


def marca_hablantes(alineado: list[dict], hablantes: list[dict] | None) -> list[dict]:
    """Anota en cada palabra quien la dice, a partir de los tramos que declara el `slides.json`.

    Un tramo es `{"desde": i, "hasta": j, "personaje": "Ollie"}` sobre los INDICES DE PALABRA de la
    narracion. Se declara ahi y no se adivina aqui: quien escribe el guion sabe quien habla, y un
    parser de comillas se equivoca justo en los casos dificiles —dialogo sin atribucion, cita dentro
    de cita— que son los que mas confunden al espectador.

    `abre_dialogo` marca la primera palabra del tramo: es donde va la etiqueta con el nombre.
    """
    for palabra in alineado:
        palabra.pop("personaje", None)
        palabra.pop("abre_dialogo", None)
    for tramo in hablantes or []:
        desde, hasta = int(tramo["desde"]), int(tramo["hasta"])
        if not 0 <= desde < hasta <= len(alineado):
            raise AlineacionError(f"El tramo de dialogo {tramo} se sale del guion, que tiene {len(alineado)} palabras.")
        for indice in range(desde, hasta):
            alineado[indice]["personaje"] = tramo["personaje"]
        alineado[desde]["abre_dialogo"] = True
    return alineado


# Signos de apertura invertidos. **Son marca de PROSODIA para Orpheus, no ortografía del idioma del
# vídeo**: la convención española «¡…!» se eligió el 10-09 porque entona más —medido, +12 Hz de tono
# medio y +2,4 dB (addendum fila 133)— y esa decisión es sobre cómo SUENA. Escritos en un subtítulo
# inglés serían un signo que el espectador no espera, que es exactamente el defecto que la fila 115
# arregló para las etiquetas: `<groan>` se quemaba como la palabra «groan».
#
# Lo cazó un agente revisor del 10-09 sobre los guiones de la semana W37, y estaba medido: 18 láminas de
# los tres episodios llevaban un «¡» que habría llegado al vídeo y al `.srt`. En un canal que narre en
# ESPAÑOL el signo sí es ortografía y se conserva: la decisión la toma el idioma declarado del canal,
# no una lista de canales.
_APERTURA_INVERTIDA = str.maketrans({"¡": None, "¿": None})


def texto_para_pintar(texto: str, idioma: str) -> str:
    """La narración tal como se PINTA: sin etiquetas emocionales y sin signos de apertura invertidos.

    `sin_etiquetas` se queda corta para lo que se ve en pantalla, y a propósito: sus otros dos
    consumidores —el conteo de palabras del verificador y el recorte por texto— no necesitan tocar la
    puntuación, así que la regla del pintado vive aquí.

    `idioma` es el del canal y no tiene defecto aquí: `lib/subtitulos.py` pone el suyo al llamar.
    """
    limpio = sin_etiquetas(texto)
    if not (idioma or "").lower().startswith("es"):
        limpio = limpio.translate(_APERTURA_INVERTIDA)
    return " ".join(limpio.split())
