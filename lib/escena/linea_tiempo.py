"""La línea de tiempo de un episodio: de la narración del run a los tiempos del vídeo (F6.2b).

Viene de `canal/scripts/linea_tiempo.py` del experimento video_1, generalizado para el estudio. Lo
que allí eran constantes del canal (la intro de 5 s, la pausa de 6,5 s, el CTA de 20 s, los personajes, el
largo de las líneas del karaoke) aquí son el bloque `escena` del perfil (`lib/escena/ajustes.py`), sin
defecto. Y lo que allí era un emparejador propio (`difflib`) aquí es el del estudio, `lib/alineacion.py`: el
mismo que ya usan los subtítulos, la limpieza de voz y la integridad de la narración.

**Cómo se arma el tiempo.** La narración es un wav por lámina del run (`audio/slide-NN.wav`). Cada lámina dura
un número entero de fotogramas (su duración redondeada a `fps`), y el vídeo intercala silencios:

- `pausas.intro_s` antes de la primera palabra,
- `pausas.entre_partes_s` entre cada par de láminas de voz (una menos que láminas),
- `pausas.cola_s` tras la última palabra.

Así, la lámina k (0, 1…) empieza en `intro + k · pausa + (lo que duran las anteriores)`, y un tiempo de su
alineación (relativo a su wav) pasa al vídeo sumándole eso. La duración total se redondea hacia arriba a un
fotograma entero.

**Las palabras** son las del guion (`slides.json → narration`, sin etiquetas `<…>` y como se pintan:
`alineacion.texto_para_pintar`), con el tiempo que les da el emparejador sobre las marcas del alineador
(`subtitulos/alineacion-resultado.json`) y tres correcciones del motor de escena para que ninguna se encienda en
silencio antes de decirse (`tiempos_de_palabras`, F6.3b). Del audio solo se toman los tiempos: el texto es el del
guion. Quién dice cada una sale de `slides.json → hablantes` (tramos de índices de palabra, los mismos que usa el
karaoke quemado) y del `reparto` del canal.

**Dos agrupaciones distintas, y a propósito:**

1. Los **cues** anclan los tiempos del guion de escena (`C(n)`, `P(n, "palabra")`, en `anclas.py`). Salen solo
   del TEXTO —`split_narration`, el mismo troceo que el `.srt`—, así que regenerar la voz no los renumera y
   un tramo escrito contra el cue 12 sigue valiendo.
2. Los **grupos de karaoke** son lo que se ve junto en pantalla. Se cortan por frases, por pausas largas y por
   cambio de lámina, se unen si son muy cortos y se parten por el mejor punto si no caben (`_parte`).
"""

from __future__ import annotations

import json
import math
import re
import struct
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from lib import alineacion, config
from lib.escena import ajustes
from lib.voice_client import VoiceError, split_narration
from lib.voice_worker import RecortadorPorTexto


class ErrorDeLinea(ValueError):
    """La línea de tiempo no se puede armar: falta un audio, una alineación o un personaje del reparto."""


def duracion_wav(ruta: str | Path) -> float:
    """La duración de un wav leyendo su cabecera RIFF a mano.

    Los wav de la voz son PCM en coma flotante de 32 bits (formato 3), que el módulo `wave` de la biblioteca
    estándar no abre; esto lee `fmt ` y `data` de cualquier wav sin comprimir.
    """
    datos = Path(ruta).read_bytes()
    if datos[:4] != b"RIFF" or datos[8:12] != b"WAVE":
        raise ErrorDeLinea(f"{ruta} no es un wav (RIFF/WAVE)")
    pos, bytes_por_segundo, tamano = 12, 0, None
    while pos + 8 <= len(datos):
        nombre, largo = datos[pos : pos + 4], struct.unpack("<I", datos[pos + 4 : pos + 8])[0]
        if nombre == b"fmt ":
            bytes_por_segundo = struct.unpack("<I", datos[pos + 16 : pos + 20])[0]
        elif nombre == b"data":
            tamano = largo
        pos += 8 + largo + (largo & 1)
    if not bytes_por_segundo or tamano is None:
        raise ErrorDeLinea(f"{ruta}: el wav no tiene «fmt » o «data»")
    return tamano / bytes_por_segundo


# ------------------------------------------------------------------------------------------ marcas
# Umbrales del ESTUDIO para leer las marcas de whisper (F6.3b), medidos sobre los 17 runs con audio en disco del
# 29-09 (los dos canales): `experimentos/motor-escena/f63b-karaoke/`.
MARCA_NULA_S = 0.01  # una marca más corta no es una palabra oída: es el bucle que whisper alucina (0 s)
# Un hueco de al menos esto delante de una palabra de marca corta es una pausa y no la palabra dicha deprisa. De las
# 47 palabras con marca real y corta de esos runs (`cortas.json`), las 16 con un hueco de 0,10 a 0,42 s quedan más
# cerca de donde vuelve la voz repartidas (10) que con su marca (5; una empata), así que ahí sigue el reparto de
# siempre. Las 4 con un hueco de 0,52 s o más quedan todas más cerca con su marca, entre 0,16 y 0,62 s. Entre 0,42 y
# 0,52 s no hay ningún caso: 0,5 es un punto de esa franja vacía, no una medida. Quien lo recalibre, que lo sepa.
HUECO_DE_PAUSA_S = 0.5


def _duracion(marca: Mapping) -> float:
    return float(marca["hasta"]) - float(marca["desde"])


def _la_mas_ajustada(j: int, marcas: list[dict], libres: list[int], siguiente: str | None) -> int:
    """La marca con que se queda la palabra emparejada a `marcas[j]`: la suya, o una más ajustada del mismo sonido.

    Whisper transcribe a veces dos veces el mismo tramo: tras alucinar vuelve atrás y lo repite, y cada pasada
    pega las pausas a una palabra distinta. El emparejador del estudio se queda con una de las dos (la que le deja
    la matriz al recorrerla desde el final) sin mirar cuál es mejor. Aquí se mira: si otra marca que el
    emparejador no le dio a nadie oyó la MISMA palabra, es real y más corta, y además es el mismo sonido, la larga
    se ha tragado una pausa y la corta es la que dice dónde suena. Es el mismo sonido en dos casos:

    - **Cae en su mayor parte dentro** de la emparejada. Es «because» en el episodio de la bici: la emparejada va
      de 452,32 a 454,04 s y se traga el silencio de 1,5 s de delante; la otra pasada la oyó de 453,84 a 454,10 s.
    - **Empieza dentro** de la emparejada, aunque apenas se solapen, **salvo si la palabra siguiente del guion es
      la misma** (`siguiente`, ya normalizada). Es «He» en «the kite is in the tree», lámina 1 (revisión de F6.3b,
      §4): la emparejada va de 45,46 a 46,06 s y la otra pasada la oyó de 46,04 a 46,10 s, así que solo se tocan
      0,02 s. La excepción es un nombre dicho dos veces seguidas en «now one side is shorter», lámina 5: ahí la
      marca que empieza al final de la del primero es la del segundo, y tomarla encendería el primero 1,1 s tarde.
    """
    elegida = j
    desde, hasta = float(marcas[j]["desde"]), float(marcas[j]["hasta"])
    texto = alineacion._normaliza(marcas[j]["texto"])
    for k in libres:
        otra = marcas[k]
        duracion = _duracion(otra)
        if duracion < MARCA_NULA_S or duracion >= _duracion(marcas[elegida]):
            continue
        if alineacion._normaliza(otra["texto"]) != texto:
            continue
        dentro = min(float(otra["hasta"]), hasta) - max(float(otra["desde"]), desde)
        empieza_dentro = desde < float(otra["desde"]) < hasta
        if dentro > duracion / 2 or (empieza_dentro and siguiente != texto):
            elegida = k
    return elegida


def _rescata_de_las_nulas(palabras: list[str], marcas: list[dict], elegida: dict[int, int], libres: set[int]) -> None:
    """Palabras sin marca real que sí se oyeron: les da la marca real y libre de la MISMA palabra que hay en su hueco.

    Cuando whisper alucina un bucle («and she sat on it» repetido con 0 s en el episodio de la bici), el emparejador
    ata las palabras del guion a esas marcas nulas y el reparto las extiende a partes iguales por el hueco, así que
    alguna cae en silencio («and», 0,26 s antes de sonar). Pero la primera pasada sí las oyó con su tiempo, y esas
    marcas se quedaron libres. Para cada racha de palabras sin marca real, entre la última palabra con marca real
    y la siguiente, se buscan en orden las marcas reales y libres que caen en ese hueco y dicen lo mismo que el
    guion, sin sustituir ninguna palabra por otra. Las que no encuentran la suya siguen repartiéndose.
    """

    def real(i: int) -> bool:
        return i in elegida and _duracion(marcas[elegida[i]]) >= MARCA_NULA_S

    i = 0
    while i < len(palabras):
        if real(i):
            i += 1
            continue
        j = i
        while j < len(palabras) and not real(j):
            j += 1
        if any(k in elegida for k in range(i, j)):  # hay alguna atada a una marca nula
            cota = float(marcas[elegida[i - 1]]["hasta"]) if i > 0 else -math.inf
            techo = float(marcas[elegida[j]]["desde"]) if j < len(palabras) else math.inf
            huecas = sorted(
                (k for k in libres if _duracion(marcas[k]) >= MARCA_NULA_S),
                key=lambda k: float(marcas[k]["desde"]),
            )
            huecas = [k for k in huecas if float(marcas[k]["desde"]) >= cota and float(marcas[k]["hasta"]) <= techo]
            cursor = 0
            for w in range(i, j):
                for c in range(cursor, len(huecas)):
                    if alineacion._normaliza(marcas[huecas[c]]["texto"]) == alineacion._normaliza(palabras[w]):
                        elegida[w] = huecas[c]
                        libres.discard(huecas[c])
                        cursor = c + 1
                        break
        i = j


def _casa_las_cifras(palabras: list[str], marcas: list[dict], elegida: dict[int, int], libres: set[int]) -> dict:
    """Las cifras que whisper escribe en dígitos: cada palabra de la cifra toma un trozo de su marca (F7.10).

    El emparejador del estudio casa una palabra con una marca, y una cifra dicha con palabras («one hundred
    ninety-seven dollars») sale de whisper en UNA marca («$197»). Así que una de sus palabras se quedaba la marca y las
    demás se repartían a ojo entre sus vecinas, con las anclas del guion y el `.srt` de esas palabras. En un canal de
    cifras, como el de economía de la fila 256, eso deja una lámina con 10 de 60 palabras sin marca propia, por
    debajo de la cobertura mínima.

    El criterio es el del recorte por texto (`RecortadorPorTexto._canon` y `_casan`, fila 262): la cifra tiene que
    valer lo mismo («197usd»), y la holgura del «$» que whisper deduce. Para cada marca con dígitos se busca, entre las
    palabras que hay entre su vecina anterior y su siguiente ya emparejadas, el tramo que dice esa cifra. **Solo si es
    uno**: con dos candidatos no se elige. Y una palabra que ya tenía esa marca y casa sola se queda como estaba.
    Devuelve {palabra: (desde, hasta)}, el trozo de la marca que le toca a cada una, a partes iguales.
    """
    norma = [RecortadorPorTexto._normaliza(p) for p in palabras]
    tiempos: dict[int, tuple[float, float]] = {}
    for j, marca in enumerate(marcas):
        oido = RecortadorPorTexto._normaliza(marca["texto"])
        if not any(c.isdigit() for c in oido) or _duracion(marca) < MARCA_NULA_S:
            continue
        atadas = sorted(w for w, k in elegida.items() if k == j)
        lo = max((w + 1 for w, k in elegida.items() if k < j), default=0)
        hi = min((w for w, k in elegida.items() if k > j), default=len(palabras))
        if atadas and not (lo <= atadas[0] and atadas[-1] < hi):
            continue
        canon = RecortadorPorTexto._canon([oido])
        candidatos = []
        for s in range(lo, hi):
            for e in range(s + 1, min(hi, s + RecortadorPorTexto.PALABRAS_POR_CIFRA) + 1):
                tramo = norma[s:e]
                if e - s > 1 and not RecortadorPorTexto._cabe_en_una_cifra(tramo):
                    break
                detras = norma[e] if e < len(norma) else ""
                if RecortadorPorTexto._casan(RecortadorPorTexto._canon(tramo), canon, detras):
                    candidatos.append((s, e))
        if atadas:
            candidatos = [(s, e) for s, e in candidatos if s <= atadas[0] and atadas[-1] < e]
        if len(candidatos) != 1:
            continue
        s, e = candidatos[0]
        if e - s == 1 and atadas == [s]:
            continue
        desde, hasta = float(marca["desde"]), float(marca["hasta"])
        paso = (hasta - desde) / (e - s)
        for k, w in enumerate(range(s, e)):
            elegida[w] = j
            tiempos[w] = (desde + paso * k, desde + paso * (k + 1))
        libres.discard(j)
    return tiempos


def _reparte_colapsadas(alineado: list[dict], conserva: set[int]) -> int:
    """`alineacion.reparte_tiempos_colapsados`, salvo para las palabras de `conserva`, que no se reparten.

    Con `conserva` vacío es exactamente aquel reparto (lo comprueba `tests/escena/test_karaoke_en_silencio.py`).
    Devuelve cuántas palabras tocó.
    """
    minima = alineacion.DURACION_MINIMA_PALABRA_S

    def sin_tiempo(k: int) -> bool:
        return k not in conserva and alineado[k]["hasta"] - alineado[k]["desde"] < minima

    tocadas, i = 0, 0
    while i < len(alineado):
        if not sin_tiempo(i):
            i += 1
            continue
        j = i
        while j < len(alineado) and sin_tiempo(j):
            j += 1
        arranca = alineado[i - 1]["hasta"] if i else alineado[i]["desde"]
        acaba = alineado[j]["desde"] if j < len(alineado) else alineado[j - 1]["hasta"]
        paso = max((acaba - arranca) / (j - i), minima)
        for k in range(i, j):
            alineado[k]["desde"] = arranca + paso * (k - i)
            alineado[k]["hasta"] = arranca + paso * (k - i + 1)
            alineado[k]["anclada"] = False
            tocadas += 1
        i = j
    for anterior, palabra in zip(alineado, alineado[1:]):
        if palabra["desde"] < anterior["hasta"]:
            palabra["hasta"] = max(palabra["hasta"], anterior["hasta"] + minima)
            palabra["desde"] = anterior["hasta"]
            tocadas += 1
    return tocadas


def tiempos_de_palabras(palabras: list[str], marcas: list[dict]) -> tuple[list[dict], int]:
    """El tiempo de cada palabra del guion para el karaoke de la escena, y cuántas hubo que repartir (F6.3b).

    Es el camino de siempre —`alineacion.empareja` y `reparte_tiempos_colapsados`, con las mismas parejas— con
    tres correcciones para que ninguna palabra se encienda en silencio antes de decirse:

    1. **La otra pasada de whisper** (`_la_mas_ajustada`): «because» y «He» en el episodio de la bici.
    2. **El bucle alucinado** (`_rescata_de_las_nulas`): las palabras atadas a marcas nulas recuperan la marca real
       que la primera pasada les dio, si está libre y dice lo mismo.
    2b. **Las cifras en dígitos** (`_casa_las_cifras`, F7.10): «one hundred ninety-seven dollars» se reparte la marca
       «$197» en vez de quedarse con ella una sola palabra.
    3. **Una marca corta tras una pausa conserva su inicio.** El reparto lleva a toda palabra de menos de
       `DURACION_MINIMA_PALABRA_S` al final de la anterior. Si el hueco de delante es la palabra dicha deprisa
       («one side»), eso acierta; si es una pausa (≥ `HUECO_DE_PAUSA_S`), la enciende en el silencio. Es el «and»
       de «stopped, and»: su marca está en 565,47 s y el reparto lo encendía en 564,57 s. Una marca nula
       (`MARCA_NULA_S`) no es una palabra oída y se reparte como siempre.

    **Por qué no se hizo como video_1** (quitar las marcas nulas y las que retroceden, y quedarse con la primera
    pasada): acierta en la bici, pero en otros episodios la primera pasada es la mala. En «everything turns blue»
    encendía una frase entera 2,9 s tarde, y sin las marcas nulas diecisiete palabras de otra lámina se
    apiñaban en un segundo (`progress/impl_F6.3b.md`).

    Solo lo usa el motor de escena: `lib/alineacion.py` no cambia para la voz ni para el motor viejo.
    """
    if not palabras:
        return [], 0  # como `alineacion.empareja`: sin palabras no hay nada que alinear
    if not marcas:
        raise alineacion.AlineacionError("no hay ni una marca de tiempo: la alineación no produjo nada")
    marca_de = alineacion._empareja_indices(palabras, marcas)
    libres = set(range(len(marcas))) - set(marca_de.values())
    elegida: dict[int, int] = {}
    for i, j in sorted(marca_de.items()):
        siguiente = alineacion._normaliza(palabras[i + 1]) if i + 1 < len(palabras) else None
        elegida[i] = _la_mas_ajustada(j, marcas, sorted(libres), siguiente)
        libres.discard(elegida[i])
    _rescata_de_las_nulas(palabras, marcas, elegida, libres)
    cifras = _casa_las_cifras(palabras, marcas, elegida, libres)
    alineado, reales = [], set()
    for i, palabra in enumerate(palabras):
        j = elegida.get(i)
        if j is not None and _duracion(marcas[j]) >= MARCA_NULA_S:
            reales.add(i)
        desde, hasta = cifras.get(i) or (
            (float(marcas[j]["desde"]), float(marcas[j]["hasta"])) if j is not None else (None, None)
        )
        alineado.append({"palabra": palabra, "desde": desde, "hasta": hasta, "anclada": j is not None})
    alineacion._rellena_huecos(alineado)
    # Las de marca real con una pausa delante; si además son cortas, el reparto no las toca.
    conserva = {i for i in reales if i > 0 and alineado[i]["desde"] - alineado[i - 1]["hasta"] >= HUECO_DE_PAUSA_S}
    return alineado, _reparte_colapsadas(alineado, conserva)


# ------------------------------------------------------------------------------------------ piezas
@dataclass
class Palabra:
    texto: str
    ini: float  # s en el vídeo
    fin: float
    lamina: int  # posición (0, 1…) entre las láminas de voz
    anclada: bool  # el tiempo viene de una marca del alineador, no de un reparto
    hablante: str  # su clase en el karaoke: el narrador o el id del personaje
    pj: str | None  # el personaje que la dice, o None si es del narrador
    cue: int = 0
    personaje: str | None = None  # su nombre en slides.json → hablantes (el que el `.srt` pone delante)
    abre: bool = False  # la primera palabra de un diálogo: donde el `.srt` escribe «Nombre: »


@dataclass
class Cue:
    n: int  # 1, 2… en todo el episodio
    lamina: int
    palabras: list[Palabra] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palabras)

    @property
    def ini(self) -> float:
        return self.palabras[0].ini

    @property
    def fin(self) -> float:
        return self.palabras[-1].fin


# Fin de frase: punto, cierre de exclamación o de pregunta, o puntos suspensivos, con su comilla de cierre.
FIN_FRASE = re.compile(r"""([.!?]|\.\.\.|…)["”»’']?$""")
# Pesos de `_parte`, del ESTUDIO: es el algoritmo de corte, no un gusto de canal (qué palabras son conjunciones
# o artículos sí lo es, y lo declara su perfil). Vienen de video_1, donde se ajustaron mirando las líneas.
_MIN_IZQ, _MIN_DER = 14, 10  # caracteres que tiene que tener cada lado de un corte
_PREMIO_SIGNO = 30  # cortar tras una coma, dos puntos, punto y coma o puntos suspensivos
_PREMIO_CONJUNCION = 12  # cortar antes de una conjunción
_CASTIGO_NO_CIERRA = 40  # dejar un artículo o una preposición colgando al final de la línea


def _texto(palabras: list[Palabra]) -> str:
    return " ".join(p.texto for p in palabras)


def _parte_por_caracteres(grupo: list[Palabra], limite: int) -> list[list[Palabra]]:
    """Parte un cue que no cabe en `limite` caracteres, por palabras y sin reordenar (como el `.srt` del estudio)."""
    if len(_texto(grupo)) <= limite:
        return [grupo]
    partido: list[list[Palabra]] = [[]]
    for p in grupo:
        if partido[-1] and len(_texto(partido[-1] + [p])) > limite:
            partido.append([p])
        else:
            partido[-1].append(p)
    return [t for t in partido if t]


class LineaDeTiempo:
    """Los tiempos de un episodio: dónde cae cada lámina de voz, cada palabra, cada cue y cada grupo de karaoke.

    - `laminas`: las láminas de VOZ en su orden, cada una {"numero", "narration", "hablantes" (opcional)}.
    - `duraciones`: los segundos de su wav, en el mismo orden.
    - `marcas`: {numero: [{texto, desde, hasta}]}, las marcas del alineador, relativas a su wav.
    - `escena`: el bloque `escena` del perfil del canal; `idioma`: el de sus subtítulos.

    Para un run en disco, `LineaDeTiempo.del_run(run, escena=..., idioma=...)`.
    """

    def __init__(
        self,
        *,
        laminas: list[Mapping],
        duraciones: list[float],
        marcas: Mapping[int, list[dict]],
        escena: Mapping,
        idioma: str,
    ) -> None:
        self.escena = ajustes.valida_bloque(escena)
        if not laminas:
            raise ErrorDeLinea("no hay ni una lámina con narración")
        if len(laminas) != len(duraciones):
            raise ErrorDeLinea(f"{len(laminas)} láminas y {len(duraciones)} duraciones")
        self.fps = self.escena["fps"]
        self.laminas = [int(lamina["numero"]) for lamina in laminas]
        self.tramos = [self._a_fotogramas(d) for d in duraciones]
        if any(t <= 0 for t in self.tramos):
            raise ErrorDeLinea(f"hay láminas sin audio (duraciones {duraciones})")
        pausas = self.escena["pausas"]
        self.intro = self._a_fotogramas(pausas["intro_s"])
        self.pausa = self._a_fotogramas(pausas["entre_partes_s"])
        self.cola = self._a_fotogramas(pausas["cola_s"])
        n = len(self.tramos)
        self.inicio = [self.intro + k * self.pausa + sum(self.tramos[:k]) for k in range(n)]
        bruto = self.intro + sum(self.tramos) + (n - 1) * self.pausa + self.cola
        self.total = math.ceil(bruto * self.fps - 1e-6) / self.fps
        self.palabras: list[Palabra] = []
        self.cues: list[Cue] = []
        self.por_lamina: list[dict] = []
        for k, lamina in enumerate(laminas):
            self._lamina(k, lamina, marcas, idioma)

    def _a_fotogramas(self, segundos: float) -> float:
        return round(float(segundos) * self.fps) / self.fps

    @classmethod
    def del_run(cls, run_dir: str | Path, *, escena: Mapping, idioma: str) -> LineaDeTiempo:
        """Arma la línea desde un run: `slides.json`, sus wav y la alineación por palabra (rutas de `lib/config.py`)."""
        run = Path(run_dir)
        slides = json.loads((run / "slides.json").read_text(encoding="utf-8")).get("slides") or []
        ruta = config.alineacion_del_run(run)
        if not ruta.is_file():
            raise ErrorDeLinea(f"falta la alineación por palabra del run: {ruta}")
        items = {i["id"]: i["marcas"] for i in json.loads(ruta.read_text(encoding="utf-8"))["items"]}
        laminas, duraciones, marcas = [], [], {}
        for numero, slide in enumerate(slides, start=1):
            if not (slide.get("narration") or "").strip():
                continue  # una lámina sin narración no tiene voz: no entra en la línea de la voz
            audio = config.audio_de_lamina(run, numero)
            if not audio.is_file():
                raise ErrorDeLinea(f"la lámina {numero} tiene narración y no está su audio: {audio}")
            if f"slide-{numero:02d}" not in items:
                raise ErrorDeLinea(f"la lámina {numero} no está en la alineación ({ruta})")
            laminas.append({"numero": numero, "narration": slide["narration"], "hablantes": slide.get("hablantes")})
            duraciones.append(duracion_wav(audio))
            marcas[numero] = items[f"slide-{numero:02d}"]
        return cls(laminas=laminas, duraciones=duraciones, marcas=marcas, escena=escena, idioma=idioma)

    # ------------------------------------------------------------------ palabras y cues
    def _lamina(self, k: int, lamina: Mapping, marcas: Mapping[int, list[dict]], idioma: str) -> None:
        numero = int(lamina["numero"])
        texto = alineacion.texto_para_pintar(lamina.get("narration") or "", idioma)
        palabras = texto.split()
        if not palabras:
            raise ErrorDeLinea(f"la lámina {numero} no tiene ni una palabra que decir")
        if numero not in marcas:
            raise ErrorDeLinea(f"la lámina {numero} no tiene marcas del alineador")
        try:
            alineado, colapsadas = tiempos_de_palabras(palabras, marcas[numero])
            alineacion.marca_hablantes(alineado, lamina.get("hablantes"))
        except alineacion.AlineacionError as error:
            raise ErrorDeLinea(f"lámina {numero}: {error}") from error
        reparto, narrador = self.escena["reparto"], self.escena["narrador"]
        propias = []
        for p in alineado:
            personaje = p.get("personaje")
            if personaje is not None and personaje not in reparto:
                raise ErrorDeLinea(
                    f"lámina {numero}: «{personaje}» dice un diálogo (slides.json → hablantes) y no está en el "
                    f"reparto del canal (escena.reparto: {sorted(reparto)}). Añádelo con el id de su personaje."
                )
            pj = reparto[personaje] if personaje is not None else None
            propias.append(
                Palabra(
                    texto=p["palabra"],
                    ini=self.inicio[k] + p["desde"],
                    fin=self.inicio[k] + p["hasta"],
                    lamina=k,
                    anclada=bool(p["anclada"]),
                    hablante=pj or narrador,
                    pj=pj,
                    personaje=personaje,
                    abre=bool(p.get("abre_dialogo")),
                )
            )
        # Los cues: el troceo del texto (el de la voz y el `.srt`) y, si no caben, partidos por caracteres.
        cues = self.escena["cues"]
        try:
            fragmentos = split_narration(texto, int(cues["max_palabras"]))
        except VoiceError as error:
            raise ErrorDeLinea(f"lámina {numero}: {error}") from error
        cursor = 0
        for fragmento in fragmentos:
            cuantas = len(fragmento.split())
            grupo, cursor = propias[cursor : cursor + cuantas], cursor + cuantas
            for trozo in _parte_por_caracteres(grupo, int(cues["max_caracteres"])):
                cue = Cue(n=len(self.cues) + 1, lamina=k, palabras=trozo)
                for p in trozo:
                    p.cue = cue.n
                self.cues.append(cue)
        if cursor != len(propias):
            raise ErrorDeLinea(
                f"lámina {numero}: los cues cubren {cursor} palabras de {len(propias)}. Si split_narration ha "
                "cambiado su política, el troceo de los cues hay que revisarlo."
            )
        self.palabras.extend(propias)
        ancladas = sum(p.anclada for p in propias)
        self.por_lamina.append(
            {
                "lamina": numero,
                "palabras": len(propias),
                "ancladas": ancladas,
                "cobertura": round(ancladas / len(propias), 4),
                "colapsadas": colapsadas,
                "inicio_s": round(self.inicio[k], 3),
                "dura_s": round(self.tramos[k], 3),
            }
        )

    # ------------------------------------------------------------------ consultas
    def a_video(self, k: int, t_lamina: float) -> float:
        """Un tiempo relativo al wav de la lámina de voz k → el tiempo del vídeo."""
        return self.inicio[k] + t_lamina

    def cue(self, n: int) -> Cue:
        if not 1 <= n <= len(self.cues):
            raise ErrorDeLinea(f"no hay cue {n}: el episodio tiene {len(self.cues)}")
        return self.cues[n - 1]

    def hueco(self, k: int) -> tuple[float, float]:
        """La pausa que sigue a la lámina de voz k (0 … N−2): (inicio, fin) en el vídeo."""
        if not 0 <= k < len(self.tramos) - 1:
            raise ErrorDeLinea(f"no hay pausa tras la lámina {k}: hay {len(self.tramos) - 1} pausas (0…)")
        return self.inicio[k] + self.tramos[k], self.inicio[k + 1]

    # ------------------------------------------------------------------ karaoke y habla
    def _parte(self, palabras: list[Palabra]) -> list[list[Palabra]]:
        """Parte una frase que no cabe por su mejor punto: tras un signo, antes de una conjunción y a partes iguales."""
        k = self.escena["karaoke"]
        maximo = int(k["max_caracteres"])
        conjunciones = {alineacion._normaliza(w) for w in k["conjunciones"]}
        no_cierran = {alineacion._normaliza(w) for w in k["no_cierran"]}
        texto = _texto(palabras)
        if len(texto) <= maximo or len(palabras) < 4:
            return [palabras]
        mejor, coste_mejor = None, float("inf")
        for i in range(1, len(palabras)):
            izq = len(_texto(palabras[:i]))
            der = len(texto) - izq - 1
            if izq < _MIN_IZQ or der < _MIN_DER:
                continue
            coste = abs(izq - der)
            if palabras[i - 1].texto.endswith((",", ":", ";", "...", "…")):
                coste -= _PREMIO_SIGNO
            if alineacion._normaliza(palabras[i].texto) in conjunciones:
                coste -= _PREMIO_CONJUNCION
            if alineacion._normaliza(palabras[i - 1].texto) in no_cierran:
                coste += _CASTIGO_NO_CIERRA
            if coste < coste_mejor:
                mejor, coste_mejor = i, coste
        if mejor is None:
            return [palabras]
        return self._parte(palabras[:mejor]) + self._parte(palabras[mejor:])

    def grupos(self) -> list[list[Palabra]]:
        """Las palabras en grupos de una o dos líneas que se ven juntos.

        Primero corta en frases (fin de frase, pausa larga o cambio de lámina), une las muy cortas con la
        siguiente si caben y no hay pausa larga, y parte las que no caben por su mejor punto.
        """
        k = self.escena["karaoke"]
        maximo = int(k["max_caracteres"])
        frases: list[list[Palabra]] = [[]]
        for p in self.palabras:
            if frases[-1]:
                ant = frases[-1][-1]
                if p.lamina != ant.lamina or p.ini - ant.fin > k["pausa_corte_s"] or FIN_FRASE.search(ant.texto):
                    frases.append([])
            frases[-1].append(p)
        unidas: list[list[Palabra]] = []
        for f in frases:
            if (
                unidas
                and len(_texto(unidas[-1])) < k["une_menos_de_caracteres"]
                and len(_texto(unidas[-1] + f)) <= maximo
                and f[0].ini - unidas[-1][-1].fin < k["une_pausa_menor_s"]
                and f[0].lamina == unidas[-1][-1].lamina
            ):
                unidas[-1] = unidas[-1] + f
            else:
                unidas.append(f)
        return [trozo for f in unidas for trozo in self._parte(f)]

    def karaoke(self) -> list[dict]:
        """Los grupos de karaoke del GUION: {id, t, t1, w: [[inicio, fin, texto, hablante], …]}."""
        k = self.escena["karaoke"]
        grupos = self.grupos()
        salida = []
        for i, g in enumerate(grupos):
            ini = max(0.0, g[0].ini - k["antes_s"])
            fin = g[-1].fin + k["despues_s"]
            if i + 1 < len(grupos):
                fin = min(fin, grupos[i + 1][0].ini - k["separacion_s"])
            fin = max(fin, ini + k["minimo_s"])
            salida.append(
                {
                    "id": f"k{i}",
                    "t": round(ini, 3),
                    "t1": round(fin, 3),
                    "w": [
                        [round(p.ini, 3), round(max(p.fin, p.ini + k["palabra_minima_s"]), 3), p.texto, p.hablante]
                        for p in g
                    ],
                }
            )
        return salida

    def habla(self) -> dict[str, list[dict]]:
        """Los tramos en que habla cada personaje ({pj: [{t, t1}]}), para que rebote mientras suena su frase."""
        h = self.escena["habla"]
        salida: dict[str, list[dict]] = {}
        for p in self.palabras:
            if p.pj is None:
                continue
            a, b = p.ini, max(p.fin, p.ini + h["minimo_s"])
            lista = salida.setdefault(p.pj, [])
            if lista and a - lista[-1]["t1"] < h["une_s"]:
                lista[-1]["t1"] = round(b, 3)
            else:
                lista.append({"t": round(a, 3), "t1": round(b, 3)})
        return salida

    def lineas_de_subtitulo(self) -> list[list[dict]]:
        """Los cues como líneas del `.srt`: una por cue, con sus palabras en el formato de `lib/subtitulos.py`.

        Es lo que hace que los cues de la escena y el `.srt` salgan de UNA sola fuente (auditoría de F6.2b,
        recomendación 5): el `.srt` del motor de escena no se trocea otra vez, son estos cues con sus tiempos del
        vídeo. Son copias: recortar un solape en el `.srt` no mueve el cue al que se ancla la escena.
        """
        return [
            [
                {"palabra": p.texto, "desde": p.ini, "hasta": p.fin, "personaje": p.personaje, "abre_dialogo": p.abre}
                for p in cue.palabras
            ]
            for cue in self.cues
        ]

    def informe(self) -> dict:
        """Lo que hay que mirar: cuánto ancla el alineador por lámina, y los tiempos del episodio."""
        total = len(self.palabras)
        ancladas = sum(p.anclada for p in self.palabras)
        return {
            "laminas": len(self.laminas),
            "palabras": total,
            "ancladas": ancladas,
            "cobertura": round(ancladas / total, 4) if total else None,
            "por_lamina": self.por_lamina,
            "cues": len(self.cues),
            "intro_s": self.intro,
            "pausa_s": self.pausa,
            "cola_s": self.cola,
            "total_s": self.total,
        }
