"""El bloque `escena` del perfil de un canal: qué declara y cómo se exige, sin defecto (F6.2b).

Todo lo que aquí se lista es una decisión de CANAL (F4.9): el ritmo del render, lo que rebota quien habla,
las pausas entre partes, cómo se corta el karaoke, quién habla en sus guiones. El estudio no pone ninguno.
Si el perfil no lo declara, `exige` para y dice qué escribir, y una lista vacía («ninguna conjunción») es
una respuesta válida, no un olvido.

El esquema, tal como lo rellenará F6.3 para el canal de la muestra (los valores de ejemplo son los que video_1 llevaba
dentro de su código):

```json
"escena": {
  "fps": 24,
  "marco": {"w": 1920, "h": 1080},
  "fundido": 0.14,
  "camara_en_mano": 1,
  "movimiento": {
    "anda": {"v": 300, "paso": 2.0, "bote": 18, "balanceo": 2.2},
    "habla": {"rebote": 7, "frecuencia": 3.1, "cabeceo": 1.2, "cabeceo_frecuencia": 1.3, "sube": 0.1, "baja": 0.15},
    "respira": {"amplitud": 0.008, "periodo": 3.3},
    "eventos": {"risa": {"a": 14}, "tiembla": {"a": 8}, "ladea": {"r": 6}, "bote": {"h": 30, "n": 2},
                "asiente": {"a": 6}, "bombea": {"a": 30, "f": 1.1}, "estira": {"a": 0.06},
                "menea": {"a": 12, "f": 2.5}},
    "elementos": {"entra": 0.45, "sale": 0.35, "trazo": 0.8, "campana": 3}
  },
  "pausas": {"intro_s": 5.0, "entre_partes_s": 6.5, "cola_s": 9.75},
  "cues": {"max_palabras": 12, "max_caracteres": 48},
  "karaoke": {"max_caracteres": 62, "pausa_corte_s": 0.85, "une_menos_de_caracteres": 16,
              "une_pausa_menor_s": 0.5, "antes_s": 0.18, "despues_s": 0.45, "separacion_s": 0.2,
              "minimo_s": 0.8, "palabra_minima_s": 0.08,
              "conjunciones": ["and", "but", "because"], "no_cierran": ["the", "a", "of"]},
  "habla": {"une_s": 0.35, "minimo_s": 0.1},
  "reparto": {"Nombre en slides.json → hablantes": "id del personaje (actor.pj y clase .h-<id> del CSS)"},
  "narrador": "narrador",
  "franja_karaoke_y": 860
}
```

Qué hace cada grupo:

- `fps`, `marco`, `fundido`, `camara_en_mano` y `movimiento` van al GUION tal cual (los lee `motor/motor.js`;
  `movimiento` es `Motor.MOVIMIENTO`, y cada actor o evento puede sobrescribir lo suyo).
- `pausas`: el silencio antes de la primera palabra, entre dos láminas de voz y tras la última. Los usa
  `lib/escena/linea_tiempo.py` para colocar cada lámina en el vídeo.
- `cues`: cómo se parte la narración en «cues», las unidades a las que se anclan los tiempos del guion
  (`C(n)`, `P(n, "palabra")`). Salen solo del TEXTO, así que no cambian al regenerar la voz. **Son también las
  líneas del `.srt`** del motor de escena: la etapa `alinea` lo escribe con estos mismos cues
  (`LineaDeTiempo.lineas_de_subtitulo`, F6.2d), así que `C(12)` es el bloque 12 del `.srt` y los dos salen de una
  sola fuente (auditoría de F6.2b, recomendación 5). Por eso aquí se declaran y no se copian de otro sitio: el
  karaoke quemado del montaje (`lib/subtitulos.py`, con su `caracteres_por_linea` derivado del cuerpo y los márgenes)
  no existe en este motor. Para que un canal que cambia de motor conserve el troceo de su `.srt`, `max_palabras` es
  su `subtitulos.max_palabras_por_linea` y `max_caracteres` lo que ese cálculo le daba (48 en el ejemplo).
- `karaoke`: cómo se agrupan las palabras que se ven juntas y cuánto antes y después de su voz se ve cada
  grupo. `conjunciones` son las palabras ante las que es bueno partir una línea y `no_cierran` las que no
  pueden quedar al final (un artículo, una preposición): dependen del idioma del canal.
- `habla`: cómo se juntan las palabras de un personaje en los tramos en que rebota al hablar.
- `reparto` y `narrador`: la clase de hablante de cada palabra del karaoke. `reparto` traduce el nombre con
  que `slides.json → hablantes` atribuye un diálogo al id del personaje (el `pj` de su actor), y
  `narrador` es la clase de todo lo demás. Un canal sin diálogos declara `{}`.
- `franja_karaoke_y`: dónde empieza el karaoke en pantalla (px desde arriba, con dos líneas), que ningún texto
  apartado de una cara puede pisar (`encuadre.aparta_de_caras`). Depende del CSS del canal (su cuerpo de letra,
  su margen de abajo), y por eso lo declara el canal junto al resto de su karaoke (F6.3). El guion del episodio lo
  pasa a su `Puesta`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from lib.escena.compone import DIVISORES, MOVIMIENTO, _en_ruta, _es_numero


class ErrorDeAjustes(ValueError):
    """El perfil no declara lo que el motor de escena necesita: el mensaje dice qué escribir."""


NUMERO, LISTA, MAPA, TEXTO = "número", "lista", "objeto", "texto"

# ruta → (tipo, qué es). El orden es el del esquema del docstring.
CAMPOS: dict[str, tuple[str, str]] = {
    "fps": (NUMERO, "fotogramas por segundo del render (p. ej. 24)"),
    "marco.w": (NUMERO, "ancho del fotograma en px"),
    "marco.h": (NUMERO, "alto del fotograma en px"),
    "fundido": (NUMERO, "segundos del fundido entre dos posturas de un actor"),
    "camara_en_mano": (NUMERO, "amplitud de la cámara en mano (0 la apaga, 1 es la calibrada)"),
    **{
        f"movimiento.{r}": (NUMERO, "magnitud del movimiento (ver Motor.MOVIMIENTO en motor/motor.js)")
        for r in MOVIMIENTO
    },
    "pausas.intro_s": (NUMERO, "segundos antes de la primera palabra"),
    "pausas.entre_partes_s": (NUMERO, "segundos de pausa entre dos láminas de voz"),
    "pausas.cola_s": (NUMERO, "segundos tras la última palabra"),
    "cues.max_palabras": (NUMERO, "palabras como mucho por cue (el troceo de split_narration)"),
    "cues.max_caracteres": (NUMERO, "caracteres como mucho por cue"),
    "karaoke.max_caracteres": (NUMERO, "caracteres como mucho por grupo de karaoke"),
    "karaoke.pausa_corte_s": (NUMERO, "una pausa más larga que esto entre dos palabras abre grupo"),
    "karaoke.une_menos_de_caracteres": (NUMERO, "un grupo más corto que esto se une al siguiente si cabe"),
    "karaoke.une_pausa_menor_s": (NUMERO, "…y si la pausa entre los dos es menor que esto"),
    "karaoke.antes_s": (NUMERO, "segundos que se ve un grupo antes de su primera palabra"),
    "karaoke.despues_s": (NUMERO, "segundos que se ve un grupo después de su última palabra"),
    "karaoke.separacion_s": (NUMERO, "segundos que un grupo deja libres antes del siguiente"),
    "karaoke.minimo_s": (NUMERO, "segundos que se ve un grupo como poco"),
    "karaoke.palabra_minima_s": (NUMERO, "segundos que brilla una palabra como poco"),
    "karaoke.conjunciones": (LISTA, "palabras ante las que conviene partir una línea (del idioma del canal)"),
    "karaoke.no_cierran": (LISTA, "palabras que no pueden quedar al final de una línea (artículos, preposiciones)"),
    "habla.une_s": (NUMERO, "dos palabras de un personaje más cerca que esto van en el mismo tramo de habla"),
    "habla.minimo_s": (NUMERO, "segundos que dura como poco la palabra de un personaje en su tramo de habla"),
    "reparto": (MAPA, "nombre del personaje en slides.json → hablantes: su id (el pj de su actor); {} si no hay"),
    "narrador": (TEXTO, "clase de hablante de lo que no dice ningún personaje (p. ej. «narrador»)"),
    "franja_karaoke_y": (
        NUMERO,
        "px de pantalla donde empieza el karaoke: ningún texto apartado de una cara baja de ahí",
    ),
}

# Los ids de personaje y la clase del narrador acaban en una clase CSS (`.h-<id>`): letras, cifras, «-» y «_».
_CLASE = re.compile(r"^[A-Za-z0-9_-]+$")


def _es(valor, tipo: str) -> bool:
    if tipo == NUMERO:
        return _es_numero(valor)
    if tipo == LISTA:
        return isinstance(valor, list) and all(isinstance(x, str) for x in valor)
    if tipo == MAPA:
        return isinstance(valor, Mapping)
    return isinstance(valor, str) and bool(valor)


def valida_bloque(bloque: Mapping | None) -> dict:
    """Comprueba el bloque `escena` entero y lo devuelve. Para con TODO lo que falta, no solo con lo primero."""
    donde = "perfil.json → escena"
    if not isinstance(bloque, Mapping):
        raise ErrorDeAjustes(
            f"{donde} no existe. El motor de escena necesita que el canal declare su bloque `escena` (ver el "
            "esquema en lib/escena/ajustes.py); no tiene defecto porque heredaría el ritmo y el estilo de otro canal."
        )
    faltan = [
        f"«{ruta}» ({tipo}: {que})" for ruta, (tipo, que) in CAMPOS.items() if not _es(_en_ruta(bloque, ruta), tipo)
    ]
    if faltan:
        raise ErrorDeAjustes(f"{donde} no declara: " + "; ".join(faltan) + ". Sin valor por defecto, a propósito.")
    if not bloque["fps"] > 0 or not (bloque["marco"]["w"] > 0 and bloque["marco"]["h"] > 0):
        raise ErrorDeAjustes(f"{donde}: fps y marco tienen que ser positivos")
    nulos = [f"«movimiento.{r}»" for r in DIVISORES if not _en_ruta(bloque["movimiento"], r) > 0]
    if nulos:
        raise ErrorDeAjustes(
            f"{donde}: {', '.join(nulos)} tienen que ser mayores que 0: el motor divide por ellas (un tiempo de "
            "subida, un periodo, una velocidad de referencia) y con 0 daría NaN, y la figura o el rótulo "
            "desaparecerían sin error"
        )
    malos = [
        v for v in [bloque["narrador"], *bloque["reparto"].values()] if not isinstance(v, str) or not _CLASE.match(v)
    ]
    if malos:
        raise ErrorDeAjustes(
            f"{donde}: {malos} no valen como id de hablante; acaban en una clase CSS (.h-<id>), así que solo "
            "letras, cifras, «-» y «_»"
        )
    if bloque["narrador"] in bloque["reparto"].values():
        raise ErrorDeAjustes(f"{donde}: «{bloque['narrador']}» es a la vez el narrador y un personaje del reparto")
    return dict(bloque)


def exige(perfil: Mapping) -> dict:
    """El bloque `escena` de un `perfil.json` ya leído, comprobado. Para si falta algo."""
    return valida_bloque((perfil or {}).get("escena"))


# Los formatos del catálogo (`docs/formats.md`). Los que tienen ajustes propios los declaran en un bloque
# con su nombre dentro de `escena` (`lib/escena/laminas.py`, `lib/escena/pizarra.py`); «personajes» es el motor sin
# más y no lleva bloque. La declaración de IA tiene una línea para cada uno (`lib/publicacion.py`).
FORMATOS_CON_BLOQUE = ("laminas", "pizarra")
FORMATO_SIN_BLOQUE = "personajes"
FORMATOS = (FORMATO_SIN_BLOQUE, *FORMATOS_CON_BLOQUE)


def formato(perfil: Mapping) -> str:
    """El formato del catálogo en el que produce el canal, leído de su perfil (F7.11).

    Lo dice el bloque `escena`: `escena.pizarra` es «pizarra», `escena.laminas` es «láminas», y sin ninguno de los dos
    es «personajes». No es un defecto del estudio: «personajes» es el motor de escena sin ajustes de formato, y por eso
    no tiene bloque. Lo escribe el render en `montaje.json → formato`, y de ahí lo lee la declaración de IA.

    Para si el perfil declara los dos bloques: un vídeo no tiene dos formatos, y elegir uno sería decidir por el canal.
    """
    escena = (perfil or {}).get("escena")
    propios = [f for f in FORMATOS_CON_BLOQUE if isinstance(escena, Mapping) and isinstance(escena.get(f), Mapping)]
    if len(propios) > 1:
        raise ErrorDeAjustes(
            f"perfil.json → escena declara los bloques de dos formatos ({', '.join(propios)}): un canal produce "
            "en uno. Quita el que no usa."
        )
    return propios[0] if propios else FORMATO_SIN_BLOQUE
