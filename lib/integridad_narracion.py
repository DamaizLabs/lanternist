"""¿El audio montado dice lo que dice el guion? (F5.7)

**El caso que lo motiva.** El 14-09-2026 el episodio 2 de un canal se subió a YouTube con **5,6 s de
narración borrados** en la lámina 5 —«Then they heard feet. Fast feet. Biscuit came into the
kitchen»—, la limpieza por marcas los había callado, y los tres gates automáticos dieron verde.
Se encontró escuchando el vídeo. Un defecto que solo se ve oyendo quince minutos no es
compatible con lo que se pidió ese mismo día: «necesito que tanto el primer canal como el segundo vayan en
piloto automático».

**Y no cuesta GPU.** La transcripción con marcas por palabra ya se calcula en cada run para el
karaoke (F2.13); aquí solo se LEE. Lo único que se mide de nuevo es el silencio con `ffmpeg`, que
cuesta décimas de segundo por hallazgo.

## Las tres decisiones de diseño, con lo que las midió

1. **Se compara con `difflib.SequenceMatcher`, no recorriendo las dos listas a la par.** Un
   contador ingenuo —avanzar el índice solo cuando las palabras coinciden— daba **93,7 % de
   palabras perdidas en tres audios distintos**: un número idéntico para tres entradas distintas es
   la señal de que mide el bucle y no el audio. `SequenceMatcher` alinea los tramos iguales y deja
   los huecos a la vista.

2. **La alineación que vale es la de los SUBTÍTULOS, no la de la limpieza.** Las dos existen y se
   llaman igual. La de `limpieza/` se toma sobre el audio **recién generado**, ANTES de cortarlo, así
   que es ciega por construcción a lo que el corte se lleve; la de `subtitulos/` se toma sobre el
   audio ya limpio, que es el que entra en el vídeo. Medido en el run del defecto: la lámina 5 tiene
   150 palabras transcritas en `limpieza/alineacion-resultado.json` y **143** en
   `subtitulos/alineacion-resultado.json`. Además un canal que no usa `limpieza_por_marcas` no tiene en sus runs
   la primera, y auditarlos exige la segunda.

3. **Una FALTA se CONFIRMA contra el audio, y por eso el gate distingue el par de control.** El
   reconocedor también se pierde: en la lámina 5, sobre el audio BUENO, `whisper-small` transcribe
   «feet. Fast feet. Biscuit came into the kitchen» como tres tokens censurados. Comparando solo
   texto, el gate canta igual con el defecto y sin él —y un gate que no distingue no sirve—. Lo que
   sí los distingue es cuánto SONIDO hay en el hueco: con el filtro puesto quedan 1,99 s de sonido
   para 14 palabras (0,14 s por palabra) y sin él 3,44 s para 8 (0,43 s por palabra). Por debajo de
   `SEGUNDOS_POR_PALABRA_MINIMO` no caben ni hablando al doble de rápido que cualquier canal del
   estudio, así que ahí no hay narración: hay un agujero.

4. **Un SOBRANTE se confirma con la misma vara, y por eso 4 de 5 no se reportan.** «El audio dice
   palabras que el guion no tiene» es un hallazgo de texto hasta que se mira el reloj. De los 5
   sobrantes que salían de los 8 runs que hay en disco, **cuatro son imposibles**: tres ocupan una
   ventana **negativa** y el cuarto mete 47 palabras en 0,34 s, o sea 138 palabras por segundo. No
   son divagación. Son el **solape de la ventana deslizante** del reconocedor, que transcribe dos
   veces los mismos segundos: se ve en la marca donde el tiempo retrocede —en la lámina 9 del
   episodio 2 de un canal, `subtitulos/alineacion-resultado.json → items[8].marcas[223]` acaba en 89,98 s
   y `marcas[224]` empieza en 80,00 s— y el texto duplicado queda fuera del emparejamiento, porque el
   guion no lo dice dos veces. El quinto es el único con ritmo de habla:
   20 palabras en 10,72 s, **0,536 s por palabra**, contra los 0,53 que declara su canal
   (`perfil.json → voz.palabras_por_segundo` = 1,885). Los cuatro primeros van a `descartados` con su
   medición escrita, que es lo contrario de callarlos.

   **Y el quinto TAMPOCO era una divagación: F5.9 lo corrigió el 18-09.** Aquí decía «ese se
   reporta», y se dedujo de su ritmo sin mirar el audio. Al comprobarlo por oído —transcribiendo los
   10-38 s del `slide-07.wav` archivado en UNA sola ventana de `whisper`, o sea sin la ventana
   deslizante que produce el artefacto— la frase sale **una vez**, y en el guion está **una vez**. Su
   alineación salta de 29,98 a 20,00 s justo encima del tramo. Era el mismo duplicado que los otros
   cuatro, con un ritmo que por casualidad cuadra. De ahí sale la pregunta 2 de `confirma_sobrante`:
   **de dónde salió el texto**, que es lo que el reloj no puede contestar.

   **Y un límite de esto que hay que conocer antes de tocar `_texto_de_las_marcas`.** Esa función
   tira las marcas que normalizan a vacío —los guiones sueltos de `whisper`: 27 de 253 en esa misma
   lámina 9—, pero las ventanas se buscan en la lista CRUDA, así que los índices se desfasan. En tres
   de los cuatro descartes da igual (la ventana sigue sin dar: −0,02, −0,10 y −1,10 s con el mapeo
   corregido), pero en el cuarto —lámina 19 de `the-scolds-bridle`— la ventana pasaría de −0,28 s a
   **9,90 s**, o sea 0,521 s por palabra, y volvería a reportarse. Sigue siendo un duplicado del
   solape: esos 9,90 s **son los mismos segundos** que el guion ya tiene emparejados antes del salto,
   y el audio no puede decir dos cosas a la vez. Lo que el reloj no distingue ahí lo distingue hoy la
   pregunta del texto, y **lo distinguiría mejor mirar el solape**: en los tres duplicados reales la
   ventana del sobrante contiene **28, 37 y 39 marcas para 14, 19 y 19 palabras**, o sea segundos que el
   guion **ya tiene emparejados**. Eso es una prueba física y el texto solo un indicio, así que
   `confirma_sobrante` **publica la medida** en `marcas_en_la_ventana` y `se_solapa_con_lo_ya_casado`
   — sin que decidan nada todavía, igual que `sin_casar_seguidas` en el worker—. Construir el
   veredicto sobre ellas es una decisión del usuario, y hasta entonces el dato está en el JSON en vez de
   en la cabeza de nadie. La prueba del caso desfasado sigue en su sitio, para que arreglar el
   desfase obligue a decidirlo en vez de cambiar la salida en silencio.

## Lo que este módulo NO hace

- **No bloquea nada.** «El pipeline siempre termina» (12-09; addendum fila 152). Todo lo que
  encuentra sale por `incidencias_no_bloqueantes` y acaba en el LEEME del run.
- **No decide nada del canal** y no lee el perfil: los umbrales de aquí son propiedades de
  `whisper-small` y del habla humana, no gustos de un nicho (F4.9).
- **No arregla el audio.** Dice dónde escuchar, con lámina y segundo.
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
from pathlib import Path

from lib.alineacion import _normaliza
from lib.voice_client import sin_etiquetas

# --- Umbrales, todos de la capa de ESTUDIO ---------------------------------------------------
# **Tres palabras seguidas.** Con menos, lo que se mide es el reconocedor: `whisper-small` cambia
# «Ollie» por «Olly», «flour» por «flower» y «1752 to 1834» por «17521834» sin que falte un solo
# segundo de audio. Medido sobre los siete runs que había en disco el 14-09, subir el umbral de 1 a
# 3 palabras quita 6 hallazgos de esa familia y no quita ninguno real. No es una decisión de canal:
# un guion no declara cuánto se equivoca el reconocedor.
UMBRAL_PALABRAS_SEGUIDAS = 3

# Lo menos que puede durar una palabra hablada, con margen. Los dos canales del estudio narran a
# 2,44 palabras/s (el primero, Orpheus) y ~1,8 (el segundo, en A2 lento), o sea 0,41 y 0,55 s por palabra; este
# techo es **4 palabras por segundo**, más rápido que cualquier narración que el estudio produzca.
# Por debajo, el hueco no contiene esas palabras ni apurando: falta audio.
SEGUNDOS_POR_PALABRA_MINIMO = 0.25

# Qué cuenta como silencio. La limpieza por marcas escribe ceros (−180 dB medidos), y una pausa
# normal de narración se queda en −30/−40 dB, así que el umbral no es crítico: a −40, −50 y −60 dB
# el silencio del defecto midió 6,08 · 6,07 · 6,06 s. Se usa −50 por estar en medio.
SILENCIO_DB = -50.0
# Tramos de silencio más cortos que esto no se cuentan: son las pausas entre palabras.
SILENCIO_MINIMO_S = 0.2

# Orden de preferencia de la alineación. La de subtítulos describe el audio que entra en el vídeo;
# la de limpieza, el de antes de cortar (ver decisión 2 del docstring).
ALINEACIONES = (
    ("subtitulos", "el audio final, el que entra en el vídeo"),
    ("limpieza", "el audio ANTES de la limpieza por marcas: no ve lo que el corte se llevó"),
)

_SILENCIO = re.compile(r"silence_duration:\s*([\d.]+)")


def palabras_comparables(texto: str) -> list[str]:
    """El texto reducido a lo comparable: sin etiquetas, sin puntuación y en minúsculas.

    `sin_etiquetas` quita los `<laugh>` del guion, que son **sonido y no palabras** — el motor los
    convierte en una vocalización y el reconocedor nunca los escribe, así que contarlos daría una
    falta en cada lámina que lleve una.
    """
    return [p for p in (_normaliza(w) for w in sin_etiquetas(texto).split()) if p]


def _texto_de_las_marcas(marcas: list[dict]) -> list[str]:
    return [p for p in (_normaliza(m.get("texto", "")) for m in marcas) if p]


def tramos(narracion: str, marcas: list[dict], *, minimo: int = UMBRAL_PALABRAS_SEGUIDAS) -> list[dict]:
    """Los tramos en que el guion y lo transcrito no coinciden, con su ventana de tiempo.

    Devuelve dos clases de tramo, que son **dos defectos distintos** y por eso no se mezclan:

    - `falta`: el guion lo dice y el audio no. Es narración perdida, lo grave.
    - `sobra`: el audio dice algo que el guion no. Es divagación que el recorte no cortó, o el
      reconocedor repitiéndose; molesta, pero no se ha perdido nada. Cuál de las dos es lo decide
      `confirma_sobrante` midiendo la ventana: aquí salen los dos casos sin juzgar.

    Un bloque `replace` es las dos cosas a la vez, así que se decide por el **saldo**: si el guion
    pierde tres palabras más de las que el audio añade, es una falta; si es al revés, un sobrante.
    Sin ese saldo, cambios de una palabra como «carters with waggons drovers» → «driver is»
    entrarían como falta de cuatro palabras (medido: 6 falsos positivos de esa familia en los siete
    runs de disco).

    Las ventanas se sacan de las marcas del alineador. Para una falta, la ventana va del final de la
    última palabra anclada al principio de la siguiente: es el trozo de audio donde ese texto
    tendría que sonar. `hasta_s` a `None` significa «hasta el final del audio», que es el caso de un
    guion al que le falta el cierre.
    """
    guion = palabras_comparables(narracion)
    oido = _texto_de_las_marcas(marcas)
    fuera: list[dict] = []
    comparador = difflib.SequenceMatcher(None, guion, oido, autojunk=False)
    for operacion, i1, i2, j1, j2 in comparador.get_opcodes():
        if operacion == "equal":
            continue
        falta, sobra = i2 - i1, j2 - j1
        if falta - sobra >= minimo:
            fuera.append(
                {
                    "tipo": "falta",
                    "palabras": falta,
                    "texto": " ".join(guion[i1:i2]),
                    "desde_s": _fin_de(marcas, j1 - 1),
                    "hasta_s": _principio_de(marcas, j2),
                }
            )
        elif sobra - falta >= minimo:
            fuera.append(
                {
                    "tipo": "sobra",
                    "palabras": sobra,
                    "texto": " ".join(oido[j1:j2]),
                    "desde_s": _principio_de(marcas, j1) or 0.0,
                    "hasta_s": _fin_de(marcas, j2 - 1),
                }
            )
    return fuera


def _fin_de(marcas: list[dict], indice: int) -> float:
    """Dónde acaba la marca `indice`; 0.0 si el tramo empieza antes de la primera palabra."""
    if indice < 0 or indice >= len(marcas):
        return 0.0
    return round(float(marcas[indice].get("hasta") or 0.0), 2)


def _principio_de(marcas: list[dict], indice: int) -> float | None:
    """Dónde empieza la marca `indice`; `None` si el tramo llega hasta el final del audio."""
    if indice < 0 or indice >= len(marcas):
        return None
    return round(float(marcas[indice].get("desde") or 0.0), 2)


def silencio_en(audio: Path | str, desde: float, hasta: float) -> float:
    """Segundos de silencio dentro de una ventana del audio, medidos con `ffmpeg`.

    Sin GPU y sin leer el fichero entero: `-ss`/`-to` recortan antes de filtrar. Devuelve 0.0 si la
    ventana no es válida o si `ffmpeg` no dice nada — **nunca lanza**, porque esto corre al final de
    un run que ya terminó y ninguna medición puede tumbarlo.
    """
    if hasta <= desde:
        return 0.0
    try:
        salida = subprocess.run(
            ["ffmpeg", "-hide_banner", "-ss", f"{desde:.3f}", "-to", f"{hasta:.3f}", "-i", str(audio),
             "-af", f"silencedetect=noise={SILENCIO_DB}dB:d={SILENCIO_MINIMO_S}", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        ).stderr  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return 0.0
    return round(sum(float(x) for x in _SILENCIO.findall(salida)), 2)


def duracion(audio: Path | str) -> float | None:
    """Duración del audio en segundos, o `None` si no se puede medir. Nunca lanza."""
    try:
        salida = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)],
            capture_output=True, text=True, timeout=60,
        )  # fmt: skip
        return round(float(salida.stdout.strip()), 2)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def confirma_falta(tramo: dict, audio: Path | None, *, mide=silencio_en, fin: float | None = None) -> dict:
    """Decide si una falta de texto es narración perdida de verdad. Dos preguntas, en este orden.

    **1. ¿Cabe?** Si la ventana donde ese texto tendría que sonar dura menos de lo que esas palabras
    necesitan, no hay más que hablar: no están. Esto **no necesita el audio**, solo su duración, y
    por eso confirma también los runs viejos, a los que se les borraron los `.wav` el 06-09. Es lo
    que caza el defecto del final de una lámina: en el episodio del gibbet, la última palabra que se
    oye acaba en el segundo 28,98 y la lámina dura 29,00 — «His iron. His week.» no está.

    **2. ¿Suena alguien ahí?** Si la ventana sí da de sí, se mide su sonido —duración menos el
    silencio— y se reparte entre las palabras. Es la pregunta que separa el par de control del
    14-09, porque el reconocedor **también** se equivoca y hay que distinguir las dos cosas.

    Tres veredictos, y los tres se escriben:

    - `perdida`: no cabe, o hay menos sonido del que esas palabras necesitan ni hablando a 4
      palabras/s. Es la incidencia.
    - `suena_voz`: ahí hay audio de sobra, así que lo que falló es el reconocedor. **No se reporta**
      como incidencia: un gate que canta cuando el vídeo está bien deja de leerse.
    - `sin_audio`: no hay `.wav` ni forma de saber cuánto dura la ventana. Se reporta diciendo que
      nadie lo ha confirmado, porque callarlo sería dar por bueno lo que no se ha mirado.
    """
    salida = dict(tramo)
    palabras = max(tramo.get("palabras") or 1, 1)
    desde = float(tramo.get("desde_s") or 0.0)
    hasta = tramo.get("hasta_s")
    if hasta is None:
        hasta = fin
    if hasta is None:
        salida.update({"veredicto": "sin_audio", "ventana_s": None, "sonido_s": None, "segundos_por_palabra": None})
        return salida

    ventana = round(max(float(hasta) - desde, 0.0), 2)
    salida["ventana_s"] = ventana
    if ventana / palabras < SEGUNDOS_POR_PALABRA_MINIMO:
        # No hace falta oírlo: en ese hueco no cabe ese texto ni aunque sonara sin una pausa.
        salida.update({"veredicto": "perdida", "motivo": "no_cabe", "sonido_s": None, "segundos_por_palabra": None})
        return salida
    if audio is None or not Path(audio).exists():
        salida.update({"veredicto": "sin_audio", "motivo": "sin_audio", "sonido_s": None, "segundos_por_palabra": None})
        return salida

    sonido = round(max(ventana - mide(audio, desde, float(hasta)), 0.0), 2)
    por_palabra = round(sonido / palabras, 3)
    callado = por_palabra < SEGUNDOS_POR_PALABRA_MINIMO
    salida.update(
        {
            "veredicto": "perdida" if callado else "suena_voz",
            "motivo": "hueco_callado" if callado else "ahi_habla",
            "sonido_s": sonido,
            "segundos_por_palabra": por_palabra,
        }
    )
    return salida


# Cuánto del sobrante tiene que aparecer en el guion de su propia lámina para llamarlo repetición
# del reconocedor. No es un ajuste fino: los duplicados reales cubren casi el 100 % —son el mismo
# texto— y lo que baja el número es alguna palabra que whisper escribe distinta («olly» por «ollie»).
FRACCION_QUE_YA_ESTA_EN_EL_GUION = 0.8


def es_repeticion_del_guion(texto_sobrante: str, narracion: str) -> dict:
    """¿Lo que «sobra» es texto del propio guion dicho otra vez? (F5.9)

    **Es la firma que distingue los dos sobrantes**, y sale de mirar los del 15-09. Orpheus divaga
    diciendo algo que el guion NO tiene —continúa la referencia, se inventa una frase—; el alineador,
    cuando su ventana deslizante se solapa, emite **dos veces las mismas palabras del guion**. Así
    que la pregunta no es cuánto dura el tramo, es de dónde salió su texto.

    Medido en el episodio de un canal: la lámina 3 «sobraba» *far from the shelf nora said i can't reach
    it you are taller than me olly looked at* — que es, palabra por palabra, lo que su propia
    narración dice. El filtro de ritmo la dejaba pasar (0,557 s por palabra, ritmo de habla humana)
    porque el tiempo que ocupa es real: lo que se repitió fue la transcripción, no el audio.

    Se compara con `SequenceMatcher` y no exigiendo la cadena exacta, porque el reconocedor cambia
    alguna palabra al repetirla y una coincidencia literal se rompería por «olly» en vez de «ollie».
    """
    sobrante = palabras_comparables(texto_sobrante)
    guion = palabras_comparables(narracion)
    if not sobrante or not guion:
        return {"es_repeticion": False, "cubierto": 0.0}
    comparador = difflib.SequenceMatcher(None, sobrante, guion, autojunk=False)
    comunes = sum(bloque.size for bloque in comparador.get_matching_blocks())
    cubierto = round(comunes / len(sobrante), 3)
    return {"es_repeticion": cubierto >= FRACCION_QUE_YA_ESTA_EN_EL_GUION, "cubierto": cubierto}


def marcas_en(marcas: list[dict], desde: float, hasta: float) -> int:
    """Cuántas marcas del alineador empiezan dentro de esa ventana de tiempo (F5.9).

    La ventana de un sobrante la marcan **sus propias palabras**, así que por construcción contiene
    al menos tantas marcas como palabras tiene el tramo. Si contiene bastantes MÁS, esos segundos
    están emparejados dos veces: una con el guion y otra con el texto sobrante.
    """
    if hasta < desde:
        return 0
    return sum(1 for m in marcas if isinstance(m, dict) and desde <= float(m.get("desde", -1)) <= hasta)


# Los veredictos que van a `descartados` en vez de reportarse, y que por eso NECESITAN una frase en
# el LEEME (`lib/publicacion.py`). Se declara aquí, y no en una lista escrita a mano en la prueba,
# porque el defecto que cierra es real y ya ocurrió: `repeticion_del_reconocedor` nació sin frase y
# habría salido en el LEEME con su nombre interno, que es un descarte en silencio con otra cara.
# `tests/test_integridad_narracion.py` falla en rojo si el enrutado emite uno que no esté aquí, o si
# uno de aquí no tiene su frase.
VEREDICTOS_QUE_SE_DESCARTAN = frozenset({"no_es_audio", "repeticion_del_reconocedor", "suena_voz"})


def confirma_sobrante(tramo: dict, narracion: str = "", marcas: list[dict] | None = None) -> dict:
    """Decide si lo que el audio dice de más es habla de verdad. Dos preguntas, sin tocar el `.wav`.

    **¿Cabe?** Es la misma de `confirma_falta`, aplicada al revés y con una ventaja: la ventana de
    un sobrante la marcan **sus propias palabras** —de donde empieza la primera a donde acaba la
    última—, así que no hay que medir silencio para saber si ahí cupo alguien hablando. Si esas
    palabras ocupan menos de `SEGUNDOS_POR_PALABRA_MINIMO` cada una, nadie las pronunció: es el
    reconocedor transcribiendo dos veces los mismos segundos (decisión 4 del docstring).

    La ventana puede salir **negativa**, y eso no es un error que haya que tapar: significa que el
    tramo se midió a caballo del salto de tiempo que hace la ventana deslizante del reconocedor. Se
    guarda con su signo para que el descarte se pueda comprobar leyendo el JSON.

    **¿De dónde salió el texto?** (F5.9) Es la segunda, y existe porque el reloj no la contesta: un
    solape del reconocedor puede caer dentro de una ventana de duración perfectamente humana. Si lo
    que «sobra» es la propia narración de esa lámina dicha otra vez, no hay nada que escuchar.

    Cuatro veredictos, y los cuatro se escriben:

    - `divaga`: cabe hablado y el texto no es del guion. Se reporta: eso está en el audio.
    - `no_es_audio`: no cabe. **No se reporta** como incidencia, va a `descartados` con su medición.
    - `repeticion_del_reconocedor`: cabe, pero el texto ya está en su guion. Tampoco se reporta.
    - `sin_medir`: el tramo no trae con qué medir la ventana. Se reporta, porque descartar lo que no
      se ha mirado sería el error contrario.

    **Y una medida que NO decide nada todavía**: con `marcas` se publica cuántas marcas caen dentro
    de la ventana y si eso implica solape. Es la prueba **física** de un duplicado —el texto solo es
    un indicio—, y en los tres duplicados reales da 28/37/39 marcas para 14/19/19 palabras. No entra en el
    veredicto porque **no hay con qué validarla**: el control positivo del gate está fabricado sobre
    tiempos reales de un duplicado, así que solaparía igual. Construirla en gate es decisión del
    usuario, y hasta entonces el dato está escrito en el JSON.
    """
    salida = dict(tramo)
    palabras = max(tramo.get("palabras") or 1, 1)
    hasta = tramo.get("hasta_s")
    if hasta is None:
        salida.update(
            {"veredicto": "sin_medir", "motivo": "sin_ventana", "ventana_s": None, "segundos_por_palabra": None}
        )
        return salida

    ventana = round(float(hasta) - float(tramo.get("desde_s") or 0.0), 2)
    por_palabra = round(ventana / palabras, 3)
    cabe = por_palabra >= SEGUNDOS_POR_PALABRA_MINIMO
    salida.update(
        {
            "veredicto": "divaga" if cabe else "no_es_audio",
            "motivo": "cabe_hablado" if cabe else "ventana_imposible",
            "ventana_s": ventana,
            "segundos_por_palabra": por_palabra,
        }
    )
    # La segunda pregunta, y solo para lo que el ritmo dejó pasar (F5.9): un tramo que CABE hablado
    # puede seguir sin ser divagación si su texto es el del propio guion repetido. Se mira después y
    # no antes porque lo que no cabe ya está resuelto, y porque así el JSON conserva las dos medidas.
    if cabe and narracion:
        repetido = es_repeticion_del_guion(tramo.get("texto") or "", narracion)
        salida["ya_en_el_guion"] = repetido["cubierto"]
        if repetido["es_repeticion"]:
            salida.update({"veredicto": "repeticion_del_reconocedor", "motivo": "texto_del_propio_guion"})
    if marcas:
        dentro = marcas_en(marcas, float(tramo.get("desde_s") or 0.0), float(hasta))
        salida["marcas_en_la_ventana"] = dentro
        salida["se_solapa_con_lo_ya_casado"] = dentro > palabras
    return salida


def explica(tramo: dict) -> str:
    """La prueba de un hallazgo en una frase, para que el informe y el LEEME digan lo MISMO.

    Cada motivo se explica con las cifras que lo produjeron, no con un adjetivo: quien lo lea tiene
    que poder ir al segundo que se le dice y comprobarlo con sus oídos.
    """
    palabras = tramo.get("palabras")
    motivo = tramo.get("motivo")
    if motivo == "no_cabe":
        return (
            f"el hueco donde iría dura {tramo.get('ventana_s')} s y ahí no caben {palabras} palabras "
            f"ni a 4 palabras por segundo"
        )
    if motivo == "hueco_callado":
        return (
            f"en ese hueco solo hay {tramo.get('sonido_s')} s de sonido para {palabras} palabras "
            f"({tramo.get('segundos_por_palabra')} s por palabra)"
        )
    if motivo == "ahi_habla":
        return (
            f"ahí el audio habla {tramo.get('sonido_s')} s ({tramo.get('segundos_por_palabra')} s por palabra): "
            "lo que falló es el reconocedor, no la narración"
        )
    if motivo == "cabe_hablado":
        return (
            f"esas {palabras} palabras ocupan {tramo.get('ventana_s')} s "
            f"({tramo.get('segundos_por_palabra')} s por palabra): ese es el ritmo de alguien hablando"
        )
    if motivo == "ventana_imposible":
        return (
            f"esas {palabras} palabras ocupan {tramo.get('ventana_s')} s en la alineación "
            f"({tramo.get('segundos_por_palabra')} s por palabra): ahí no cabe ni una, así que el reconocedor "
            "transcribió dos veces los mismos segundos"
        )
    if motivo == "texto_del_propio_guion":
        return (
            f"esas {palabras} palabras ya están en la narración de su lámina "
            f"({tramo.get('ya_en_el_guion'):.0%} del tramo, coincidencia palabra a palabra): el reconocedor las "
            "transcribió dos veces, no es texto de más en el audio"
        )
    if motivo == "sin_ventana":
        return f"el audio dice {palabras} palabras que el guion no tiene, y no hay marcas con las que medir dónde"
    return "no queda audio del run ni duración en el montaje: es un hallazgo de texto, nadie lo ha confirmado"


def _alineacion_del_run(run: Path) -> tuple[dict, str, str]:
    """La alineación que describe el audio final, con de dónde salió y qué avisar de ella."""
    for carpeta, que_es in ALINEACIONES:
        ruta = run / carpeta / "alineacion-resultado.json"
        if not ruta.exists():
            continue
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        aviso = "" if carpeta == ALINEACIONES[0][0] else f"medido sobre {que_es}"
        return datos, f"{carpeta}/alineacion-resultado.json", aviso
    return {}, "", ""


def _del_montaje(run: Path) -> tuple[dict[int, float], dict[int, float]]:
    """De `montaje.json`: dónde empieza cada lámina en el vídeo y cuánto dura.

    Las dos cosas hacen falta. El **comienzo** es lo que convierte «lámina 11, segundo 29» en «el
    5:54 del vídeo», que es lo que el usuario teclea en el reproductor. La **duración** es la del audio de
    esa lámina —el montaje se construye pegado a él— y sirve de última palabra cuando el `.wav` ya
    no está: sin ella, un run vaciado no podría confirmar nada.

    No se reutilizaba el cálculo del karaoke quemado (`_offsets_por_lamina`, retirado en F6.7) a
    propósito: aquel **verificaba** las duraciones contra los `.wav` y lanzaba si no cuadraban, que era lo
    correcto antes de quemar subtítulos y lo contrario de lo que hace falta aquí, donde nada puede tumbar
    el run.
    """
    try:
        planos = json.loads((run / "montaje.json").read_text(encoding="utf-8")).get("detalle") or []
    except (OSError, json.JSONDecodeError):
        return {}, {}
    comienzos: dict[int, float] = {}
    duraciones: dict[int, float] = {}
    acumulado = 0.0
    # El motor de escena (F6.2d) dice dónde empieza cada lámina (`inicio_s`): entre una y otra hay pausas que no son
    # de ningún plano, así que sumar los anteriores daría un minuto falso. El montaje de siempre no lo trae.
    con_inicio = bool(planos) and all(isinstance(plano, dict) and "inicio_s" in plano for plano in planos)
    for plano in planos:
        try:
            lamina, segundos = int(plano["slide"]), float(plano["segundos"])
            inicio = float(plano["inicio_s"]) if con_inicio else acumulado
        except (KeyError, TypeError, ValueError):
            return {}, {}
        comienzos.setdefault(lamina, inicio)
        duraciones[lamina] = duraciones.get(lamina, 0.0) + segundos
        acumulado += segundos
    return comienzos, {k: round(v, 2) for k, v in duraciones.items()}


def minuto(segundos: float) -> str:
    """`347.2` → `5:47`, que es lo que se teclea en el reproductor para ir a escucharlo."""
    total = max(int(round(segundos)), 0)
    return f"{total // 60}:{total % 60:02d}"


def revisa_run(run_dir: str | Path, *, mide=silencio_en) -> dict:
    """Compara lámina a lámina el guion con lo que se oye, y devuelve lo que no cuadra.

    **Nunca lanza.** Un run sin alineación, sin `slides.json` o con un JSON roto devuelve el informe
    vacío con el motivo escrito en `aviso`: esto se llama desde la etapa que escribe el LEEME, que
    tiene que existir siempre.

    El `aviso` también sale cuando el audio es **más nuevo que la alineación**, que es lo que pasa
    en cuanto alguien regenera una lámina a mano: entonces el texto describe un audio y el silencio
    se mide sobre otro, y eso hay que saberlo antes de creerse el resultado.
    """
    run = Path(run_dir)
    informe: dict = {
        "origen": "",
        "aviso": "",
        "laminas_comparadas": 0,
        "faltan": [],
        "sobran": [],
        "descartados": [],
    }

    try:
        slides = json.loads((run / "slides.json").read_text(encoding="utf-8")).get("slides") or []
    except (OSError, json.JSONDecodeError):
        informe["aviso"] = "el run no tiene un slides.json legible: no hay guion contra el que comparar"
        return informe

    alineacion, origen, aviso = _alineacion_del_run(run)
    if not alineacion:
        informe["aviso"] = (
            "este run no tiene alineación (limpieza/ ni subtitulos/), así que no se puede comprobar "
            "si el audio dice lo que dice el guion. No es un fallo del run: los subtítulos pueden "
            "estar desactivados en el canal"
        )
        return informe
    informe["origen"] = origen
    informe["aviso"] = aviso

    items = alineacion.get("items")
    por_id = {i.get("id"): i for i in items if isinstance(i, dict)} if isinstance(items, list) else {}
    comienzos, duraciones = _del_montaje(run)
    ruta_alineacion = run / origen
    audio_mas_nuevo = False

    for numero, lamina in enumerate(slides, start=1):
        clave = f"slide-{numero:02d}"
        item = por_id.get(clave)
        narracion = (lamina.get("narration") or "").strip()
        if not item or not narracion:
            continue
        informe["laminas_comparadas"] += 1
        audio = run / "audio" / f"{clave}.wav"
        if not audio.exists():
            audio = None
        elif audio.stat().st_mtime > ruta_alineacion.stat().st_mtime + 1:
            audio_mas_nuevo = True
        # Dónde acaba el audio de la lámina. Lo dice el MONTAJE, que se construyó pegado a ese audio
        # y ya está leído; el `ffprobe` solo se paga si el montaje no lo trae, porque en un episodio
        # de 34 láminas serían 34 procesos para un dato que casi nunca se usa. Y es este camino —el
        # del montaje— el que deja auditar los episodios ya publicados, a los que se les borró el
        # material pesado.
        fin = duraciones.get(numero) or (duracion(audio) if audio else None)
        for tramo in tramos(narracion, item.get("marcas") or []):
            tramo["lamina"] = numero
            comienzo = comienzos.get(numero)
            if comienzo is not None:
                tramo["en_el_video"] = minuto(comienzo + float(tramo.get("desde_s") or 0.0))
            if tramo["tipo"] == "sobra":
                juzgado = confirma_sobrante(tramo, narracion, item.get("marcas") or [])
                se_descarta = juzgado["veredicto"] in VEREDICTOS_QUE_SE_DESCARTAN
                informe["descartados" if se_descarta else "sobran"].append(juzgado)
                continue
            juzgado = confirma_falta(tramo, audio, mide=mide, fin=fin)
            se_descarta = juzgado["veredicto"] in VEREDICTOS_QUE_SE_DESCARTAN
            informe["descartados" if se_descarta else "faltan"].append(juzgado)

    if audio_mas_nuevo:
        informe["aviso"] = (
            f"{informe['aviso']}; " if informe["aviso"] else ""
        ) + "hay audio más nuevo que la alineación: el texto describe una versión y el silencio se mide sobre otra"
    return informe
