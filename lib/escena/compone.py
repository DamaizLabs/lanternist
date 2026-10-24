"""Escribe la composición de HyperFrames (`index.html`) a partir de un GUION (F6.2a).

Viene de `canal/scripts/compone.py` del experimento video_1, generalizado para el estudio:

- **El CSS del canal llega como parámetro** (una ruta). Aquí solo queda `CSS_ESTUDIO`, el esqueleto que
  el motor necesita para funcionar (posiciones, orígenes de transformación, opacidades de partida), sin
  un solo color ni tipografía: el color de quien habla en el karaoke, los rótulos, las transiciones y los
  fondos son del canal (F4.9). El karaoke y las transiciones se pintan con clases (`h-<hablante>`,
  `punto`, `barra b<i>`) que el CSS del canal colorea.
- **Sin defectos de canal**: lo que el GUION tiene que declarar se exige y, si falta, se para con el
  nombre de lo que falta.
- **Nada remoto y nada de `mix-blend-mode`** (decisión 6 y fila 199): la página se revisa antes de
  escribirse. Toda referencia tiene que ser un fichero de la lista de assets (o un `data:` o un
  fragmento `#id`); `mix-blend-mode` obliga a HyperFrames a la captura lenta y no se admite en ninguna
  parte, tampoco en el CSS del canal.
- El motor, las mallas en WebGPU y el director van dentro de la página, como en video_1. **GSAP va aparte**,
  en `assets/vendor/gsap.min.js` dentro de la composición (también como en video_1): metido en la página,
  `hyperframes lint` da dos errores `non_deterministic_code` por el `Math.random()` y el `Date.now()` de su
  código interno, que el motor no usa. Así la composición no depende de nada fuera de su carpeta.
- **Las entradas de tinta** (F6.8): para un plano que entra con `mancha`, `calado` o `viento` escribe su máscara SVG
  y el campo de gris que lee (`lib/escena/campos.py`, en `assets/estudio/`), y para uno que entra con `papel`, su velo.
  Como GSAP, los campos los pone el estudio y no pasan por `assets`. Una composición sin ellas sale como antes.

El GUION es un dict con el mismo esquema que lee `motor/motor.js` (`window.GUION`) más lo que solo sirve
para escribir el DOM (`titulo`, `idioma`, el `html` de cada elemento, el `extra` de cada plano y los
`audios`), que no se copia a la página.
"""

from __future__ import annotations

import copy
import html
import json
import re
import shutil
from collections.abc import Mapping
from html.parser import HTMLParser
from pathlib import Path

from lib import config
from lib.escena import campos, cta


class ErrorDeComposicion(ValueError):
    """La composición no se puede escribir tal como viene: el mensaje dice qué falta o qué sobra."""


class _Codigo(HTMLParser):
    """Busca código ejecutable en un trozo de HTML del GUION: etiquetas <script> y atributos `on…=`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hallado: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.hallado.append("<script>")
        self.hallado += [f"{k}=" for k, _ in attrs if k.lower().startswith("on")]

    handle_startendtag = handle_starttag


def _sin_codigo(fragmento: str, donde: str) -> None:
    """El html de un elemento o el extra de un plano es DATO: no puede llevar código que ejecute.

    La revisión estática de la página no mira dentro de los <script> (son del estudio) ni juzga los `on…=`, y
    la sonda solo ve lo que se ejecuta en t = 0 (auditoría de F6.2a, recomendación 6).
    """
    lector = _Codigo()
    lector.feed(fragmento)
    lector.close()
    if lector.hallado or re.search(r"<\s*script", fragmento, re.IGNORECASE):
        raise ErrorDeComposicion(
            f"{donde} lleva código ({sorted(set(lector.hallado)) or ['<script>']}): el html del GUION es texto "
            "de datos. Lo que se mueve lo mueve el motor, con los campos del GUION."
        )


# Pistas de HyperFrames (`data-track-index`) de cada capa. Las de audio las declara cada audio del GUION.
PISTA_PLANOS = 1
PISTA_ELEMENTOS_EN_PLANO = 3
PISTA_PANTALLA = 4
PISTA_KARAOKE = 6
PISTA_TRANSICIONES = 7
# Los elementos se dibujan por encima de los actores del plano: el z del GUION se suma a esto.
Z_ELEMENTOS = 500
# Dónde va GSAP dentro de la composición. compone.py lo copia en cada una desde la copia de npm
# (`config.MOTOR_ESCENA_GSAP`, en `motor/node_modules/gsap`).
GSAP_EN_LA_COMPOSICION = "assets/vendor/gsap.min.js"

TIPOS_DE_TRANSICION = ("iris", "luz", "destello", "papel", "puntos", "barras")
# Lo que el motor sabe mover (`Motor.TIPOS_DE_MALLA` y `Motor.TIPOS_DE_EVENTO` en motor.js; una prueba exige que
# coincidan). Un tipo que no esté aquí para la composición en vez de salir rígido o quieto sin que nadie lo vea.
TIPOS_DE_MALLA = ("pierna", "cadena", "cuadrupedo")
TIPOS_DE_EVENTO = ("salto", "risa", "tiembla", "ladea", "bote", "asiente", "bombea", "estira", "menea")
# Lo mismo para cómo entran, salen y se mueven los elementos y cómo entra un plano (`Motor.ENTRADAS`, `SALIDAS`,
# `BUCLES` y `ENTRADAS_DE_PLANO`, F6.2b): un nombre mal escrito caía en el caso por omisión sin que nadie lo viera.
ENTRADAS = ("pop", "sube", "cae", "mancha", "crece", "nada", "fade")
# «borra» (F7.10, fila 264): el borrador que barre la tiza de izquierda a derecha (un clip-path, no un fundido).
SALIDAS = ("pop", "baja", "nada", "fade", "borra")
BUCLES = ("late", "flota", "tiembla", "gira", "balancea", "deriva", "vuela")
ENTRADAS_DE_PLANO = ("corte", "funde", "barrido", "iris", "cortina", "mancha", "calado", "viento", "papel")
# Las entradas de tinta (F6.8, las transiciones del motor de láminas): hacia dónde avanza el frente de las que lo piden
# (`Motor.DIRECCIONES_DE_ENTRADA`), sin defecto, y las que recortan el plano con un umbral sobre un campo de gris
# (`Motor.ENTRADAS_DE_UMBRAL`, ver `lib/escena/campos.py`).
DIRECCIONES_DE_ENTRADA = {"cortina": ("derecha", "izquierda", "arriba"), "viento": ("derecha", "izquierda")}
ENTRADAS_DE_UMBRAL = ("mancha", "calado", "viento")
# Las magnitudes del movimiento que el GUION declara en `movimiento` (`Motor.MOVIMIENTO` en motor.js; una prueba
# exige que coincidan). Todas números, ninguna con defecto (F4.9, auditoría de F6.2a, recomendación 5).
MOVIMIENTO = (
    "anda.v",
    "anda.paso",
    "anda.bote",
    "anda.balanceo",
    "habla.rebote",
    "habla.frecuencia",
    "habla.cabeceo",
    "habla.cabeceo_frecuencia",
    "habla.sube",
    "habla.baja",
    "respira.amplitud",
    "respira.periodo",
    "eventos.risa.a",
    "eventos.tiembla.a",
    "eventos.ladea.r",
    "eventos.bote.h",
    "eventos.bote.n",
    "eventos.asiente.a",
    "eventos.bombea.a",
    "eventos.bombea.f",
    "eventos.estira.a",
    "eventos.menea.a",
    "eventos.menea.f",
    "elementos.entra",
    "elementos.sale",
    "elementos.trazo",
    "elementos.campana",
)
# Las que dividen, y lo que un actor o un elemento sobrescribe de ellas (`Motor.DIVISORES`,
# `RASGOS_DIVISORES` y `CAMPOS_DIVISORES_DE_ELEMENTO`): con 0 el motor daría NaN y la figura o el rótulo
# desaparecerían sin error, así que tienen que ser > 0 (auditoría de F6.2b, recomendación 1).
DIVISORES = (
    "anda.v",
    "habla.sube",
    "habla.baja",
    "respira.periodo",
    "elementos.entra",
    "elementos.trazo",
    "elementos.campana",
)
RASGOS_DIVISORES = ("v_anda",)
CAMPOS_DIVISORES_DE_ELEMENTO = ("di", "trazo_d", "campana_p")
# La rejilla de la transición «puntos»: el director hace crecer cada círculo según su columna.
PUNTOS_COLUMNAS, PUNTOS_FILAS = 16, 9
BARRAS = 8

# Lo que el GUION tiene que declarar para que la composición se pueda escribir, sin defecto (F4.9).
# Lo que exige el propio motor (`Motor.OBLIGATORIOS` en motor.js) va incluido.
OBLIGATORIOS = {
    "titulo": "el título de la página (no sale en el vídeo)",
    "idioma": "el idioma del texto en pantalla, como atributo lang (p. ej. «en»)",
    "duracion": "segundos de la composición",
    "fps": "fotogramas por segundo del render (p. ej. 24)",
    "marco": "tamaño del fotograma, {w, h} en px",
    "fundido": "segundos del fundido entre dos posturas de un actor",
    "camara_en_mano": "amplitud de la cámara en mano (0 la apaga, 1 es la calibrada)",
    "movimiento": "las magnitudes del movimiento secundario, de los eventos y de los elementos (ver MOVIMIENTO)",
    "planos": "la lista de planos",
    "elementos": "la lista de elementos en pantalla (puede ir vacía)",
    "karaoke": "los grupos de karaoke (puede ir vacía)",
    "transiciones": "las transiciones (puede ir vacía)",
}

# Los ids acaban en selectores CSS del director (`"#" + id`): solo letras, cifras, guion y guion bajo.
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_CLASE = re.compile(r"^[A-Za-z0-9_-]+$")
_ESQUEMA = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

# El esqueleto que necesita el motor. **Sin colores ni tipografías**: eso es del canal. La plantilla lleva
# el tamaño del marco, que sale del GUION.
CSS_ESTUDIO = """
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: %(w)dpx; height: %(h)dpx; overflow: hidden; }
#root { position: relative; width: 100%%; height: 100%%; overflow: hidden; }
.plano { position: absolute; inset: 0; overflow: hidden; }
.mundo { position: absolute; left: 0; top: 0; transform-origin: 0 0; }
.mundo > img.fondo { position: absolute; left: 0; top: 0; }
.actor { position: absolute; left: 0; top: 0; width: 0; height: 0; transform-origin: 0 0; }
.actor > .post { position: absolute; opacity: 0; }
.post > img, .post > canvas { position: absolute; }
.el { position: absolute; }
.el > .in { width: 100%%; height: 100%%; transform-origin: 50%% 50%%; opacity: 0; }
.el .trazo { stroke-dasharray: 1000; }
/* Cada plano se apila sobre el anterior con su orden (z-index 1, 2, 3...), y ese orden vale solo entre planos: su
   contenedor es su contexto de apilado. Sin él, desde el plano 41 un plano tapaba #pantalla, y con ella los rótulos,
   el karaoke y las cortinas (medido en un episodio de 102 planos). */
#planos { position: absolute; inset: 0; z-index: 0; }
#pantalla { position: absolute; inset: 0; pointer-events: none; z-index: 40; }
#karaoke { position: absolute; left: 0; right: 0; z-index: 50; }
.kg { position: absolute; left: 0; right: 0; bottom: 0; display: flex; justify-content: center; align-items: flex-end; }
.kin { opacity: 0; }
.w { position: relative; display: inline-block; white-space: nowrap; transform-origin: 50%% 70%%; --a: 0; }
.w .f { position: absolute; left: 0; top: 0; color: var(--c); opacity: var(--a); }
.tr { position: absolute; inset: 0; z-index: 60; opacity: 0; }
.tr.luz { width: 220%%; left: -60%%; }
.tr.papel { opacity: 1; width: 160%%; left: -30%%; transform: translateX(-130%%); }
.tr.puntos, .tr.barras { opacity: 1; }
.tr.barras .barra { position: absolute; top: 0; bottom: 0; transform-origin: 50%% 0; transform: scaleY(0); }
"""
# El velo de la entrada «papel» (F6.8): solo su estructura. Su color es del canal (`.plano > .papel { background: … }`
# en su CSS) y compone para si el canal no se lo da (F4.9). Va aparte de CSS_ESTUDIO y solo entra en la página si algún
# plano entra con papel: así una composición que no lo usa sale idéntica a como salía antes.
CSS_PAPEL = ".plano > .papel { position: absolute; inset: 0; opacity: 0; pointer-events: none; }\n"

# Los atributos que hacen que el navegador pida algo. `xmlns` no está a propósito: es un nombre, no una
# petición.
_ATRIBUTOS_QUE_PIDEN = {
    "src",
    "href",
    "xlink:href",
    "poster",
    "srcset",
    "data",
    "action",
    "formaction",
    "background",
    "manifest",
    "ping",
    "cite",
    "longdesc",
    "usemap",
    "codebase",
    "archive",
    "lowsrc",
    "dynsrc",
}
_URL_CSS = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", re.IGNORECASE)
_IMPORT_CSS = re.compile(r"""@import\s+(?:url\(\s*)?(['"]?)([^'")\s;]+)""", re.IGNORECASE)
# Para saber si el CSS del canal da color al velo de la entrada «papel». `.tr.papel` es otra cosa (la cortina de
# pantalla de la transición «papel»), así que no cuenta.
_COMENTARIO_CSS = re.compile(r"/\*.*?\*/", re.DOTALL)
_REGLA_CSS = re.compile(r"([^{}]+)\{([^{}]*)\}")
_VELO_DE_PAPEL = re.compile(r"(?<!\.tr)\.papel(?![\w-])")
_FONDO_CSS = re.compile(r"(?<![\w-])background(?:-color|-image)?\s*:")


def _el_canal_pinta_el_papel(css: str) -> bool:
    """¿Lleva el CSS del canal una regla que dé fondo al velo de la entrada «papel» (`.plano > .papel`)?"""
    for m in _REGLA_CSS.finditer(_COMENTARIO_CSS.sub("", css)):
        selectores, cuerpo = m.groups()
        if any(_VELO_DE_PAPEL.search(s) for s in selectores.split(",")) and _FONDO_CSS.search(cuerpo):
            return True
    return False


# ------------------------------------------------------------------------------------------ validación
def _exige(guion: Mapping, claves: Mapping[str, str], donde: str) -> None:
    faltan = [k for k in claves if guion.get(k) is None]
    if faltan:
        raise ErrorDeComposicion(
            f"{donde} no declara "
            + ", ".join(f"«{k}» ({claves[k]})" for k in faltan)
            + ". Sin valor por defecto, a propósito: lo escribe quien hace el GUION."
        )


def _en_ruta(nodo, ruta: str):
    """El valor de `ruta` («habla.rebote») dentro de un dict anidado, o None si falta algún tramo."""
    for parte in ruta.split("."):
        if not isinstance(nodo, Mapping) or parte not in nodo:
            return None
        nodo = nodo[parte]
    return nodo


def _es_numero(valor) -> bool:
    """Un número de verdad: `True` es un int en Python y en JavaScript no es un número."""
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def ruta_local(valor: str, donde: str) -> str:
    """Devuelve `valor` si es una ruta relativa dentro de la composición; si no, para.

    Vale `assets/img/fondo.png`. No valen un esquema (`https:`, `file:`, `C:`), una ruta absoluta
    (`/x`, `//host/x`, `\\\\x`), subir de carpeta (`..`) ni la cadena vacía.
    """
    v = str(valor).strip()
    if not v:
        raise ErrorDeComposicion(f"{donde}: ruta vacía")
    if _ESQUEMA.match(v) or v.startswith(("/", "\\")):
        raise ErrorDeComposicion(
            f"{donde}: «{v}» no es una ruta relativa de la composición. Todo lo que la página usa tiene "
            "que estar dentro de su carpeta (nada sale del PC, y un render no depende de nada "
            "de fuera)."
        )
    if ".." in re.split(r"[\\/]", v):
        raise ErrorDeComposicion(f"{donde}: «{v}» sube de carpeta (..): la composición no sale de la suya")
    return v.replace("\\", "/")


def problema_de_direccion(tipo, direccion) -> str | None:
    """Qué falla en la dirección (`dir`) de la entrada de un plano, o None si vale (`Motor.validaDireccion`).

    Las que la piden (`DIRECCIONES_DE_ENTRADA`) la exigen, sin defecto; el barrido conserva la suya de antes, ±1 (su
    sentido) o ninguna; las demás no llevan.
    """
    dirs = DIRECCIONES_DE_ENTRADA.get(tipo)
    if dirs is not None:
        if not (isinstance(direccion, str) and direccion in dirs):
            return f"entra con «{tipo}» y dir {direccion!r}: tiene que decir hacia dónde ({', '.join(dirs)})"
    elif tipo == "barrido":
        if direccion is not None and not (_es_numero(direccion) and direccion in (1, -1)):
            return f"entra con «barrido» y dir {direccion!r}: su dir es 1 o -1 (el sentido)"
    elif direccion is not None:
        return f"entra con «{tipo}», que no lleva dirección, y trae dir {direccion!r}"
    return None


def _ids_de_tinta(p: Mapping) -> tuple[str, ...]:
    """Los ids que compone escribe para la máscara de un plano que entra por umbral (ninguno si no)."""
    if campos.nombre(p.get("entra")) is None:
        return ()
    return (f"{p['id']}-f", f"{p['id']}-m", f"{p['id']}-umbral")


def _id(valor, donde: str) -> str:
    if not isinstance(valor, str) or not _ID.match(valor):
        raise ErrorDeComposicion(
            f"{donde}: el id {valor!r} no vale; el director lo usa como selector CSS, así que empieza por una "
            "letra y solo lleva letras, cifras, «-» y «_»"
        )
    return valor


def _referencias_del_guion(g: Mapping) -> list[tuple[str, str]]:
    """(ruta, dónde) de cada fichero que el GUION pide: fondos, posturas, piezas de malla y audios."""
    refs = []
    for p in g["planos"]:
        refs.append((p["fondo"]["src"], f"plano {p['id']} → fondo"))
        for a in p["actores"]:
            for nombre, d in a["posturas"].items():
                refs.append((d["src"], f"actor {a['id']} → postura {nombre}"))
    for nombre, pz in ((g.get("rig") or {}).get("piezas") or {}).items():
        refs.append((pz["png"], f"rig → pieza {nombre}"))
        for clave in ("base", "encima"):
            if pz.get(clave):
                refs.append((pz[clave], f"rig → pieza {nombre} → {clave}"))
    for au in g.get("audios") or []:
        refs.append((au["src"], f"audio {au['id']}"))
    return refs


def valida(guion: Mapping) -> None:
    """Comprueba el GUION antes de escribir nada. Para con un mensaje que dice qué falta."""
    _exige(guion, OBLIGATORIOS, "El GUION")
    if not (isinstance(guion["fps"], (int, float)) and guion["fps"] > 0):
        raise ErrorDeComposicion(f"El GUION: fps tiene que ser un número positivo, no {guion['fps']!r}")
    if not (guion["duracion"] > 0):
        raise ErrorDeComposicion(f"El GUION: duracion tiene que ser positiva, no {guion['duracion']!r}")
    _exige(guion["marco"], {"w": "ancho en px", "h": "alto en px"}, "El marco del GUION")
    faltan = [r for r in MOVIMIENTO if not _es_numero(_en_ruta(guion["movimiento"], r))]
    if faltan:
        raise ErrorDeComposicion(
            "El GUION no declara en «movimiento» " + ", ".join(f"«{r}»" for r in faltan) + ". Son las magnitudes "
            "del movimiento (lo que rebota quien habla, la respiración, cada evento…), las declara el canal y no "
            "tienen valor por defecto."
        )
    nulos = [r for r in DIVISORES if not _en_ruta(guion["movimiento"], r) > 0]
    if nulos:
        raise ErrorDeComposicion(
            "En el «movimiento» del GUION tienen que ser mayores que 0 "
            + ", ".join(f"«{r}»" for r in nulos)
            + ": el motor divide por ellas y con 0 daría NaN."
        )
    if not guion["planos"]:
        raise ErrorDeComposicion("El GUION no tiene ningún plano")
    vistos: dict[str, str] = {}

    def registra(valor, donde: str) -> None:
        _id(valor, donde)
        if valor in vistos:
            raise ErrorDeComposicion(f"{donde}: el id «{valor}» ya lo usa {vistos[valor]}")
        vistos[valor] = donde

    for p in guion["planos"]:
        registra(p.get("id"), "un plano")
        _exige(
            p,
            {
                "t0": "inicio",
                "t1": "fin",
                "fondo": "{src, w, h}",
                "camara": "claves de cámara",
                "actores": "lista (puede ir vacía)",
            },
            f"El plano {p['id']}",
        )
        _exige(p["fondo"], {"src": "imagen", "w": "ancho", "h": "alto"}, f"El fondo del plano {p['id']}")
        if not p["camara"]:
            raise ErrorDeComposicion(f"El plano {p['id']} no tiene ninguna clave de cámara")
        _sin_codigo(str(p.get("extra") or ""), f"El extra del plano {p['id']}")
        if p.get("entra") and p["entra"].get("tipo") not in ENTRADAS_DE_PLANO:
            raise ErrorDeComposicion(
                f"El plano {p['id']} entra con «{p['entra'].get('tipo')}», que el motor no sabe hacer "
                f"({', '.join(ENTRADAS_DE_PLANO)})"
            )
        if p.get("entra"):
            problema = problema_de_direccion(p["entra"].get("tipo"), p["entra"].get("dir"))
            if problema:
                raise ErrorDeComposicion(f"El plano {p['id']} {problema}")
        for a in p["actores"]:
            registra(a.get("id"), f"un actor del plano {p['id']}")
            _exige(
                a,
                {
                    "z": "orden de apilado",
                    "escala": "escala",
                    "posturas": "sus imágenes",
                    "pista": "claves de posición",
                },
                f"El actor {a['id']}",
            )
            if not a["pista"]:
                raise ErrorDeComposicion(f"El actor {a['id']} no tiene ninguna clave en su pista")
            for nombre, d in a["posturas"].items():
                _exige(
                    d,
                    {"src": "imagen", "w": "ancho", "h": "alto", "ax": "apoyo x", "ay": "apoyo y"},
                    f"La postura {nombre} del actor {a['id']}",
                )
            for r in RASGOS_DIVISORES:
                valor = (a.get("rasgos") or {}).get(r)
                if valor is not None and not (_es_numero(valor) and valor > 0):
                    raise ErrorDeComposicion(
                        f"El actor {a['id']} lleva el rasgo {r} = {valor!r}, y tiene que ser mayor que 0 (el "
                        "motor divide por él)"
                    )
            for ev in a.get("eventos") or []:
                if ev.get("tipo") not in TIPOS_DE_EVENTO:
                    raise ErrorDeComposicion(
                        f"El actor {a['id']} lleva un evento «{ev.get('tipo')}», que el motor no sabe hacer "
                        f"({', '.join(TIPOS_DE_EVENTO)})"
                    )
    capas = {p["id"] for p in guion["planos"]} | {"pantalla"}
    for e in guion["elementos"]:
        registra(e.get("id"), "un elemento")
        _exige(
            e,
            {
                "t0": "inicio",
                "t1": "fin",
                "capa": "«pantalla» o el id de su plano",
                "x": "x",
                "y": "y",
                "w": "ancho",
                "h": "alto",
                "z": "orden",
                "html": "su contenido",
            },
            f"El elemento {e['id']}",
        )
        if e["capa"] not in capas:
            raise ErrorDeComposicion(f"El elemento {e['id']} va en la capa «{e['capa']}», que no existe")
        for clase in str(e.get("clase") or "").split():
            if not _CLASE.match(clase):
                raise ErrorDeComposicion(f"El elemento {e['id']}: la clase {clase!r} no vale")
        _sin_codigo(str(e["html"]), f"El html del elemento {e['id']}")
        for c in CAMPOS_DIVISORES_DE_ELEMENTO:
            if e.get(c) is not None and not (_es_numero(e[c]) and e[c] > 0):
                raise ErrorDeComposicion(
                    f"El elemento {e['id']} lleva {c} = {e[c]!r}, y tiene que ser mayor que 0 (el motor divide por él)"
                )
        for campo, lista in (("entra", ENTRADAS), ("sale", SALIDAS), ("bucle", BUCLES)):
            if e.get(campo) is not None and e[campo] not in lista:
                raise ErrorDeComposicion(
                    f"El elemento {e['id']} lleva {campo} «{e[campo]}», que el motor no sabe hacer ({', '.join(lista)})"
                )
    for nombre, pz in ((guion.get("rig") or {}).get("piezas") or {}).items():
        if pz.get("tipo") not in TIPOS_DE_MALLA:
            raise ErrorDeComposicion(
                f"La pieza de malla «{nombre}» es de tipo «{pz.get('tipo')}», que el motor no sabe mover "
                f"({', '.join(TIPOS_DE_MALLA)}). El tipo «perro» ahora se llama «cuadrupedo»."
            )
        if pz["tipo"] == "cuadrupedo":
            _exige(
                pz,
                {"cola_amp": "grados del meneo de la cola", "cola_freq": "meneos de la cola por segundo"},
                f"La pieza cuadrúpeda «{nombre}»",
            )
    for g in guion["karaoke"]:
        registra(g.get("id"), "un grupo de karaoke")
        _exige(
            g,
            {"t": "inicio", "t1": "fin", "w": "palabras [inicio, fin, texto, hablante]"},
            f"El grupo de karaoke {g['id']}",
        )
        for w in g["w"]:
            if len(w) != 4 or not _CLASE.match(str(w[3])):
                raise ErrorDeComposicion(
                    f"El grupo de karaoke {g['id']}: cada palabra es [inicio, fin, texto, hablante] y el "
                    f"hablante es una clase CSS (el color lo pone el canal con .h-<hablante>); vino {w!r}"
                )
    for x in guion["transiciones"]:
        registra(x.get("id"), "una transición")
        _exige(x, {"t": "inicio", "d": "duración", "tipo": "|".join(TIPOS_DE_TRANSICION)}, f"La transición {x['id']}")
        if x["tipo"] not in TIPOS_DE_TRANSICION:
            raise ErrorDeComposicion(f"La transición {x['id']} es de tipo «{x['tipo']}», que el director no pinta")
    for au in guion.get("audios") or []:
        registra(au.get("id"), "un audio")
        _exige(
            au,
            {"src": "fichero", "t": "inicio", "d": "duración", "pista": "data-track-index", "volumen": "data-volume"},
            f"El audio {au['id']}",
        )
    # La máscara de un plano que entra por umbral lleva ids derivados del suyo: ninguna otra pieza puede usarlos.
    for p in guion["planos"]:
        for derivado in _ids_de_tinta(p):
            if derivado in vistos:
                raise ErrorDeComposicion(
                    f"{vistos[derivado]}: el id «{derivado}» es el de la máscara del plano {p['id']}, que escribe el "
                    "estudio"
                )


# ------------------------------------------------------------------------------------------ DOM
def _attrs(t0: float, t1: float) -> str:
    return f'data-start="{t0:.3f}" data-duration="{max(0.05, t1 - t0):.3f}"'


def _esc(texto) -> str:
    return html.escape(str(texto), quote=True)


def _postura_dom(a: dict, n: str, d: dict, rig: dict) -> str:
    """Una postura: su imagen o, si el rig le da piezas, un envoltorio con la base y sus lienzos.

    Los lienzos van dentro de la postura, en px de su imagen reducidos por k, así que se mueven, giran y
    se funden con ella. Una pieza «detras» va debajo de la base, y la imagen «encima» de una pieza va
    sobre todos los lienzos.
    """
    k = d.get("k", 1)
    caja = f"left:{-d['ax'] / k:.1f}px;top:{-d['ay'] / k:.1f}px;width:{d['w'] / k:.1f}px;height:{d['h'] / k:.1f}px"
    piezas = {nombre: pz for nombre, pz in rig.items() if pz["post"] == n}
    if not piezas:
        return f'<img class="post" data-post="{_esc(n)}" src="{_esc(d["src"])}" alt="" style="{caja}">'
    base = next((pz["base"] for pz in piezas.values() if pz.get("base")), d["src"])
    lienzos = {
        nombre: (
            f'<canvas class="malla" id="m-{a["id"]}-{_esc(nombre)}" data-actor="{a["id"]}" '
            f'data-pieza="{_esc(nombre)}" width="{pz["w"]}" height="{pz["h"]}" '
            f'style="left:{pz["x"] / k:.1f}px;top:{pz["y"] / k:.1f}px;'
            f'width:{pz["w"] / k:.1f}px;height:{pz["h"] / k:.1f}px"></canvas>'
        )
        for nombre, pz in piezas.items()
    }
    detras = "".join(c for nombre, c in lienzos.items() if piezas[nombre].get("detras"))
    delante = "".join(c for nombre, c in lienzos.items() if not piezas[nombre].get("detras"))
    img = f'<img src="{_esc(base)}" alt="" style="left:0;top:0;width:100%;height:100%">' if base else ""
    encima = "".join(
        f'<img src="{_esc(pz["encima"])}" alt="" style="left:0;top:0;width:100%;height:100%">'
        for pz in piezas.values()
        if pz.get("encima")
    )
    return f'<div class="post" data-post="{_esc(n)}" style="{caja}">{detras}{img}{delante}{encima}</div>'


def _plano_dom(p: dict, elementos: str, rig: dict) -> str:
    f = p["fondo"]
    # El desenfoque va en px del fondo: en pantalla crece con el zoom de la cámara.
    filtro = f";filter:blur({p['desenfoque']:.1f}px)" if p.get("desenfoque") else ""
    # Un fondo puede ir colocado con escala y desplazamiento dentro de su plano.
    caja = f.get("img") or {"x": 0, "y": 0, "w": f["w"], "h": f["h"]}
    actores = []
    for a in p["actores"]:
        imgs = "".join(_postura_dom(a, n, d, rig) for n, d in a["posturas"].items())
        actores.append(f'<div id="{a["id"]}" class="actor" style="z-index:{a["z"]}">{imgs}</div>')
    # El velo de la entrada «papel» va encima de todo lo del plano (su color lo pone el CSS del canal).
    velo = '<div class="papel"></div>' if (p.get("entra") or {}).get("tipo") == "papel" else ""
    return (
        f'<div id="{p["id"]}" class="clip plano" {_attrs(p["t0"], p["t1"])} data-track-index="{PISTA_PLANOS}" '
        f'style="z-index:{p["orden"]}"><div class="mundo" style="width:{f["w"]}px;height:{f["h"]}px">'
        f'<img class="fondo" src="{_esc(f["src"])}" alt="" '
        f'style="left:{caja["x"]}px;top:{caja["y"]}px;width:{caja["w"]}px;height:{caja["h"]}px{filtro}">'
        f"{''.join(actores)}{elementos}</div>{p.get('extra', '')}{velo}</div>"
    )


def _tinta_dom(planos: list[dict], marco: Mapping) -> str:
    """Las máscaras SVG de los planos que entran por umbral y la precarga de sus campos; vacío si no hay ninguno.

    Por cada plano:

    - un filtro que lee su campo (`feImage`, estirado al marco), pasa su gris a alfa (`luminanceToAlpha`) y le aplica
      el umbral (`feFuncA`, que el director reescribe en cada fotograma con lo que calcula el motor);
    - una máscara de alfa con un rectángulo del marco que lleva ese filtro. El director la pone en el plano
      (`mask-image: url(#<plano>-m)`) mientras entra.

    Dos detalles medidos en el Chrome del render: sin `mask-type:alpha` la máscara sale vacía (mide la luminancia, y
    el filtro deja el color a 0); y `color-interpolation-filters="sRGB"` hace falta porque con el linearRGB por
    omisión el gris del campo se pasaría a lineal y la forma de la transición cambiaría. Los campos se precargan con un
    <img> oculto: HyperFrames espera a que carguen y se decodifiquen todas las <img> antes de fotografiar.
    """
    w, h = marco["w"], marco["h"]
    defs, usados = [], {}
    for p in planos:
        campo = campos.nombre(p.get("entra"))
        if campo is None:
            continue
        src = campos.ruta(campo)
        usados[src] = None
        i = p["id"]
        defs.append(
            f'<filter id="{i}-f" filterUnits="userSpaceOnUse" x="0" y="0" width="{w}" height="{h}" '
            f'color-interpolation-filters="sRGB"><feImage href="{src}" x="0" y="0" width="{w}" height="{h}" '
            'preserveAspectRatio="none"/><feColorMatrix type="luminanceToAlpha"/><feComponentTransfer>'
            f'<feFuncA id="{i}-umbral" type="linear" slope="0" intercept="0"/></feComponentTransfer></filter>'
            f'<mask id="{i}-m" style="mask-type:alpha" maskUnits="userSpaceOnUse" x="0" y="0" width="{w}" '
            f'height="{h}"><rect x="0" y="0" width="{w}" height="{h}" filter="url(#{i}-f)"/></mask>'
        )
    if not defs:
        return ""
    precarga = "".join(f'<img src="{src}" alt="">' for src in usados)
    return (
        f'<svg class="tinta" width="0" height="0" style="position:absolute" aria-hidden="true"><defs>{"".join(defs)}'
        f'</defs></svg><div class="campos" hidden>{precarga}</div>\n'
    )


def _elemento_dom(e: dict, pista: int) -> str:
    clase = f"clip el {e.get('clase') or ''}".strip()
    return (
        f'<div id="{e["id"]}" class="{clase}" {_attrs(e["t0"], e["t1"])} data-track-index="{pista}" '
        f'style="left:{e["x"]:.1f}px;top:{e["y"]:.1f}px;width:{e["w"]:.1f}px;height:{e["h"]:.1f}px;'
        f'z-index:{e["z"] + Z_ELEMENTOS}"><div class="in">{e["html"]}</div></div>'
    )


def _karaoke_dom(g: dict) -> str:
    spans = "".join(
        f'<span class="w h-{w[3]}"><span class="b">{_esc(w[2])}</span><span class="f">{_esc(w[2])}</span></span>'
        for w in g["w"]
    )
    return (
        f'<div id="{g["id"]}" class="clip kg" {_attrs(g["t"], g["t1"])} data-track-index="{PISTA_KARAOKE}">'
        f'<div class="kin">{spans}</div></div>'
    )


def _transicion_dom(x: dict, marco: Mapping) -> str:
    extra = ""
    if x["tipo"] == "puntos":
        dx, dy = marco["w"] / PUNTOS_COLUMNAS, marco["h"] / PUNTOS_FILAS
        circulos = "".join(
            f'<circle class="punto" cx="{dx / 2 + (i % PUNTOS_COLUMNAS) * dx:.1f}" '
            f'cy="{dy / 2 + (i // PUNTOS_COLUMNAS) * dy:.1f}" r="0"/>'
            for i in range(PUNTOS_COLUMNAS * PUNTOS_FILAS)
        )
        extra = (
            f'<svg viewBox="0 0 {marco["w"]} {marco["h"]}" width="{marco["w"]}" height="{marco["h"]}">{circulos}</svg>'
        )
    elif x["tipo"] == "barras":
        ancho = marco["w"] / BARRAS
        extra = "".join(
            f'<div class="barra b{i}" style="left:{i * ancho:.1f}px;width:{ancho + 1:.1f}px"></div>'
            for i in range(BARRAS)
        )
    return (
        f'<div id="{x["id"]}" class="clip tr {x["tipo"]}" {_attrs(x["t"], x["t"] + x["d"])} '
        f'data-track-index="{PISTA_TRANSICIONES}">{extra}</div>'
    )


def _audio_dom(au: dict) -> str:
    inicio = f' data-media-start="{au["media_start"]:g}"' if au.get("media_start") is not None else ""
    return (
        f'<audio id="{au["id"]}" src="{_esc(au["src"])}" data-start="{au["t"]:.3f}" '
        f'data-duration="{au["d"]:.3f}"{inicio} data-track-index="{au["pista"]}" '
        f'data-volume="{au["volumen"]}"></audio>'
    )


def _para_la_pagina(g: dict) -> dict:
    """El GUION que lee el motor: sin lo que solo servía para escribir el DOM (va duplicado en la página)."""
    datos = {k: v for k, v in g.items() if k not in ("titulo", "idioma", "audios")}
    # Lo que el director espera al compositor tras cada búsqueda es del estudio (una medida de la máquina), no
    # del GUION: si el GUION lo trae, manda el estudio.
    datos["espera_compositor_ms"] = config.ESCENA_ESPERA_COMPOSITOR_MS
    datos["elementos"] = [{k: v for k, v in e.items() if k != "html"} for e in g["elementos"]]
    datos["planos"] = [{k: v for k, v in p.items() if k != "extra"} for p in g["planos"]]
    return datos


# ------------------------------------------------------------------------------------------ revisión
class _Referencias(HTMLParser):
    """Recoge lo que la página pediría al navegador, sin mirar dentro de los <script> (son del estudio)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str]] = []
        self.css: list[str] = []
        self._en_style = False
        self.etiquetas_prohibidas: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("base", "iframe", "object", "embed", "link"):
            # <base> cambiaría a dónde apuntan TODAS las rutas relativas; las demás cargan documentos o
            # recursos que no hacen falta en una composición.
            self.etiquetas_prohibidas.append(tag)
        if tag == "meta" and any(k == "http-equiv" and (v or "").lower() == "refresh" for k, v in attrs):
            self.etiquetas_prohibidas.append("meta http-equiv=refresh")
        for clave, valor in attrs:
            if valor is None:
                continue
            if clave == "srcset":
                for trozo in valor.split(","):
                    if trozo.strip():
                        self.refs.append((trozo.strip().split()[0], f"<{tag} srcset>"))
            elif clave in _ATRIBUTOS_QUE_PIDEN:
                self.refs.append((valor, f"<{tag} {clave}>"))
            elif clave == "style":
                self.css.append(valor)
        self._en_style = tag == "style"

    def handle_endtag(self, tag):
        if tag == "style":
            self._en_style = False

    def handle_data(self, data):
        if self._en_style:
            self.css.append(data)


def _sin_script(pagina: str) -> str:
    """La página sin el CÓDIGO de sus <script>, pero con sus atributos: un `src` se sigue revisando."""
    return re.sub(r"(<script\b[^>]*>).*?(</script>)", r"\1\2", pagina, flags=re.DOTALL | re.IGNORECASE)


def revisa_pagina(pagina: str, disponibles: set[str]) -> None:
    """Para si la página usaría algo de fuera, algo que no está en sus assets o `mix-blend-mode`.

    Es la comprobación estática. La dinámica la hace la sonda (`motor/sonda.cjs`) abriendo la página en
    Chrome y cortando toda petición que no sea local: entre las dos cubren lo que se ve en el HTML y lo que
    solo aparece al ejecutarlo.
    """
    if re.search(r"mix-blend-mode", pagina, re.IGNORECASE):
        raise ErrorDeComposicion(
            "la página lleva «mix-blend-mode», que obliga a HyperFrames a la captura lenta. Quítalo "
            "del CSS del canal o del html del GUION: la mezcla se hace de otra forma (opacidad, degradados)."
        )
    lector = _Referencias()
    lector.feed(_sin_script(pagina))
    lector.close()
    if lector.etiquetas_prohibidas:
        raise ErrorDeComposicion(
            f"la página lleva etiquetas que no caben en una composición: {lector.etiquetas_prohibidas}"
        )
    refs = list(lector.refs)
    for bloque in lector.css:
        refs += [(m.group(2), "url() del CSS") for m in _URL_CSS.finditer(bloque)]
        refs += [(m.group(2), "@import del CSS") for m in _IMPORT_CSS.finditer(bloque)]
    for valor, donde in refs:
        v = valor.strip()
        if v.startswith("#") or v.lower().startswith("data:"):
            continue
        local = ruta_local(v, donde)
        if local.split("#")[0].split("?")[0] not in disponibles:
            raise ErrorDeComposicion(
                f"{donde}: «{v}» no está entre los assets de la composición; pásalo en `assets` para que se copie"
            )


# ------------------------------------------------------------------------------------------ escritura
def pagina(guion: Mapping, css_canal: str) -> str:
    """El HTML de la composición. No valida: eso lo hace `compone`, que es lo que se llama desde fuera."""
    g = copy.deepcopy(dict(guion))
    marco = g["marco"]
    planos = g["planos"]
    # Un plano que entra con fundido, barrido o iris se monta sobre el anterior: el anterior sigue visible
    # hasta que el nuevo ha terminado de entrar.
    for i, p in enumerate(planos):
        p["orden"] = i + 1
        if i + 1 < len(planos):
            sig = planos[i + 1]
            entra = sig.get("entra") or {"tipo": "corte", "d": 0}
            if entra["tipo"] != "corte":
                p["t1"] = max(p["t1"], sig["t0"] + entra["d"])
    # Solo las piezas de malla de las posturas que se usan.
    usadas = {n for p in planos for a in p["actores"] for n in a["posturas"]}
    rig = {n: pz for n, pz in ((g.get("rig") or {}).get("piezas") or {}).items() if pz["post"] in usadas}
    g["rig"] = {"piezas": rig}
    por_capa: dict[str, list[str]] = {}
    for e in g["elementos"]:
        pista = PISTA_PANTALLA if e["capa"] == "pantalla" else PISTA_ELEMENTOS_EN_PLANO
        por_capa.setdefault(e["capa"], []).append(_elemento_dom(e, pista))
    motor = "\n".join(f.read_text(encoding="utf-8") for f in config.MOTOR_ESCENA_JS)
    datos = json.dumps(_para_la_pagina(g), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    webgpu = " data-requires-webgpu" if rig else ""
    css = CSS_ESTUDIO % {"w": marco["w"], "h": marco["h"]}
    if any((p.get("entra") or {}).get("tipo") == "papel" for p in planos):
        css += CSS_PAPEL
    # La estructura del CTA del estudio (`lib/escena/cta.py`, fila 236), si la página lleva uno.
    if any(f'class="{cta.CLASE}"' in (e.get("html") or "") for e in g["elementos"]):
        css += cta.CSS
    tinta = _tinta_dom(planos, marco)
    return f"""<!doctype html>
<html lang="{_esc(g["idioma"])}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width={marco["w"]}, height={marco["h"]}" />
<title>{_esc(g["titulo"])}</title>
<script src="{GSAP_EN_LA_COMPOSICION}"></script>
<style>{css}</style>
<style>
{css_canal}
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-duration="{g["duracion"]:g}" data-start="0" \
data-width="{marco["w"]}" data-height="{marco["h"]}"{webgpu}>
{tinta}<div id="planos">{"".join(_plano_dom(p, "".join(por_capa.get(p["id"], [])), rig) for p in planos)}</div>
<div id="pantalla">
{"".join(por_capa.get("pantalla", []))}
<div id="karaoke">
{"".join(_karaoke_dom(k) for k in g["karaoke"])}
</div>
{"".join(_transicion_dom(x, marco) for x in g["transiciones"])}
</div>
{"".join(_audio_dom(au) for au in g.get("audios") or [])}
</div>
<script id="guion">
window.GUION = {datos};
</script>
<script>
{motor}
</script>
</body>
</html>
"""


_GUION_EN_LA_PAGINA = re.compile(r'<script id="guion">\nwindow\.GUION = (.*);\n</script>', re.DOTALL)


def lee_guion(index_html: str | Path) -> dict:
    """El GUION tal como quedó dentro de una composición (lo usa render.py para saber sus fps)."""
    texto = Path(index_html).read_text(encoding="utf-8")
    m = _GUION_EN_LA_PAGINA.search(texto)
    if not m:
        raise ErrorDeComposicion(f"{index_html} no lleva el GUION que escribe compone.py")
    return json.loads(m.group(1))


def compone(guion: Mapping, assets: Mapping[str, str | Path], css_canal: str | Path, destino: str | Path) -> Path:
    """Escribe `destino/index.html` y copia los assets a su sitio. Devuelve la ruta del `index.html`.

    - `guion`: el GUION (ver el docstring del módulo); se valida entero antes de escribir nada.
    - `assets`: {ruta relativa dentro de la composición: fichero de origen}. Todo lo que la página pide
      —fondos, posturas, piezas de malla, audios y lo que el CSS del canal cargue con `url()`— tiene que
      estar aquí; lo que no, para.
    - `css_canal`: la ruta del CSS del canal. Es su estilo (colores, tipografías, rótulos, el color de
      cada hablante con `.h-<hablante>`), y el estudio no pone ninguno.
    - `destino`: la carpeta de la composición (se crea si no existe).
    """
    valida(guion)
    css_ruta = Path(css_canal)
    if not css_ruta.is_file():
        raise ErrorDeComposicion(f"no está el CSS del canal: {css_ruta}")
    css = css_ruta.read_text(encoding="utf-8")
    if re.search(r"</style", css, re.IGNORECASE):
        raise ErrorDeComposicion(f"el CSS del canal ({css_ruta}) cierra una etiqueta <style>: no es CSS")
    copias: dict[str, Path] = {}
    for clave, origen in assets.items():
        local = ruta_local(clave, "assets")
        ruta = Path(origen)
        if not ruta.is_file():
            raise ErrorDeComposicion(f"assets → «{local}»: no existe el fichero de origen {ruta}")
        copias[local] = ruta
    if GSAP_EN_LA_COMPOSICION in copias:
        raise ErrorDeComposicion(f"assets → «{GSAP_EN_LA_COMPOSICION}» es el sitio de GSAP, que pone el estudio")
    del_estudio = sorted(k for k in copias if k.startswith(f"{campos.CARPETA}/"))
    if del_estudio:
        raise ErrorDeComposicion(
            f"assets → {del_estudio}: «{campos.CARPETA}/» es la carpeta de los campos de las entradas de tinta, que "
            "pone el estudio"
        )
    if not config.MOTOR_ESCENA_GSAP.is_file():
        raise ErrorDeComposicion(f"no está GSAP ({config.MOTOR_ESCENA_GSAP}): cd motor; npm ci")
    copias[GSAP_EN_LA_COMPOSICION] = config.MOTOR_ESCENA_GSAP
    for valor, donde in _referencias_del_guion(guion):
        local = ruta_local(valor, donde)
        if local not in copias:
            raise ErrorDeComposicion(f"{donde}: «{local}» no está entre los assets de la composición")
    con_papel = [p["id"] for p in guion["planos"] if (p.get("entra") or {}).get("tipo") == "papel"]
    if con_papel and not _el_canal_pinta_el_papel(css):
        raise ErrorDeComposicion(
            f"los planos {con_papel} entran con «papel», y el CSS del canal ({css_ruta}) no le da color a su velo: "
            "escribe en él `.plano > .papel { background: <el color de su papel>; }`. Sin valor por defecto, a "
            "propósito: el motor solo pone la estructura del velo."
        )
    # Los campos de las entradas por umbral: los dibuja el estudio, solo los que usa algún plano.
    usados = {campos.ruta(c): c for c in dict.fromkeys(campos.nombre(p.get("entra")) for p in guion["planos"]) if c}
    texto = pagina(guion, css)
    revisa_pagina(texto, set(copias) | set(usados))
    carpeta = Path(destino)
    carpeta.mkdir(parents=True, exist_ok=True)
    for local, origen in copias.items():
        final = carpeta / local
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.resolve() != origen.resolve():
            shutil.copy2(origen, final)
    # Un campo que dejó otra composición en esta carpeta y que esta no usa sale: la huella cubre assets/ entera.
    estudio = carpeta / campos.CARPETA
    if estudio.is_dir():
        for viejo in estudio.iterdir():
            if viejo.is_file() and viejo.relative_to(carpeta).as_posix() not in usados:
                viejo.unlink()
    for local, campo in usados.items():
        campos.escribe(campo, carpeta / local)
    # La configuración mínima del proyecto de HyperFrames, sin el registro remoto que trae `hyperframes init`.
    (carpeta / "hyperframes.json").write_text(
        json.dumps({"paths": {"assets": "assets"}, "media": {"autoProxy": True}}, indent=2) + "\n", encoding="utf-8"
    )
    index = carpeta / "index.html"
    index.write_text(texto, encoding="utf-8")
    return index
