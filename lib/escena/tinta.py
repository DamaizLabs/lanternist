"""Las letras de una fuente como trazos que se dibujan: «la tinta que escribe» (F6.8, fila 233).

Un rótulo escrito a tinta se pinta en dos tiempos: el trazo recorre el contorno de cada letra y después la letra se
rellena. El navegador no sabe recorrer el contorno de un texto, así que aquí se saca de la fuente:

- cada letra se convierte en sus contornos de SVG, un `<path>` por contorno (la «o» tiene dos: el de fuera y el del
  ojo), con `pathLength="1000"`;
- el guion los dibuja con el `trazo` del motor (`Motor.elemento`: `stroke-dashoffset` de 1000 a 0, con el
  `stroke-dasharray: 1000` que pone `compone.CSS_ESTUDIO`). Con la longitud normalizada, cada contorno se cierra en
  el mismo tiempo, mida lo que mida;
- el relleno es la letra entera en un solo `<path>`, para que el canal lo funda cuando el trazo ya ha pasado.

**Qué es del estudio y qué del canal** (F4.9). El estudio pone el mecanismo: leer la fuente, colocar cada letra con su
avance y su interletraje (el `kern` de la tabla GPOS), partir un texto en líneas y escribir el SVG. El canal pone todo
lo demás: la fuente, el tamaño, el espaciado, las versalitas, el color, el grosor del trazo y cuándo se escribe cada
letra. Aquí ningún argumento tiene un valor por omisión que sea un gusto.

**La fuente sale de la biblioteca del estudio, con su procedencia** (`fuente_de_la_biblioteca`, OC1.2). La tinta lee
sus contornos y la composición solo lleva los de las letras del rótulo, pero la letra sale en el vídeo: por eso la
fuente tiene que estar en `datos/escena/fuentes/`, con su licencia, y el CSS del canal tiene que pedirla, que es lo
que la lleva al run y a `assets.json`. Hasta OC1.2 se leía Georgia de la carpeta de fuentes de Windows: ni tenía
procedencia ni se puede redistribuir.

Una letra que la fuente no tiene para aquí, con su nombre: un hueco en un título no se ve hasta el vídeo.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

from lib import config

# La longitud a la que se normaliza cada contorno. Es la del motor: `Motor.elemento` lleva el trazo de 1000 a 0 y
# `compone.CSS_ESTUDIO` pone `stroke-dasharray: 1000`. Si cambia allí, cambia aquí.
LARGO_DEL_TRAZO = 1000


class ErrorDeTinta(ValueError):
    """El texto no se puede escribir con esa fuente: el mensaje dice qué letra o qué medida falla."""


@dataclass(frozen=True)
class Letra:
    """Una letra con tinta: su carácter, sus contornos (`d` de SVG) y dónde empieza su avance.

    Los contornos van en px, con el origen en la línea base al principio de la línea y la y hacia abajo.
    """

    caracter: str
    contornos: tuple[str, ...]
    x: float


@dataclass(frozen=True)
class Linea:
    """Una línea de texto compuesta: sus letras con tinta (los espacios no la llevan) y sus medidas en px.

    - `ancho`: del principio de la primera letra al final del avance de la última, sin el espaciado de detrás.
    - `ascenso` y `descenso`: lo que la fuente sube sobre la línea base y baja por debajo (los dos positivos).
    - `mayusculas`: la altura de una mayúscula, la que se usa para centrar un rótulo a la vista.
    """

    texto: str
    letras: tuple[Letra, ...]
    ancho: float
    ascenso: float
    descenso: float
    mayusculas: float


def fuente_de_la_biblioteca(nombre: str, css: str) -> Path:
    """La ruta de la fuente `nombre` de la biblioteca del estudio, que el CSS del canal tiene que declarar.

    Para si no está en `datos/escena/fuentes/` (una fuente del sistema no vale: no tiene procedencia) o si el CSS no la
    pide con `@font-face { src: url(assets/fuentes/<nombre>) }`: sin eso no entra en el run, y la letra saldría en el
    vídeo sin su licencia en `assets.json` (decisión 5). La etapa `escena` la copia al run con su registro
    (`audio.biblioteca`).
    """
    from lib.escena import audio  # aquí y no arriba: audio arrastra la música y la procedencia

    ruta = config.ESCENA_FUENTES_DIR / str(nombre)
    if not nombre or Path(nombre).name != nombre or not ruta.is_file():
        raise ErrorDeTinta(f"la fuente «{nombre}» no está en la biblioteca del estudio ({config.ESCENA_FUENTES_DIR})")
    if nombre not in audio.fuentes_del_css(css):
        raise ErrorDeTinta(
            f"el CSS del canal no declara la fuente «{nombre}» (`@font-face {{ src: url(assets/fuentes/{nombre}) }}`): "
            "sin eso no entra en el run con su procedencia, y la letra saldría sin licencia en assets.json"
        )
    return ruta


@lru_cache(maxsize=8)
def _fuente(ruta: str) -> TTFont:
    return TTFont(ruta, lazy=True)


@lru_cache(maxsize=8)
def _kern(ruta: str) -> tuple:
    """Los subtablas de interletraje (PairPos) de la función `kern` de GPOS, agrupadas por consulta."""
    f = _fuente(ruta)
    if "GPOS" not in f:
        return ()
    gpos = f["GPOS"].table
    if not gpos.FeatureList or not gpos.LookupList:
        return ()
    indices = sorted(
        {i for fr in gpos.FeatureList.FeatureRecord if fr.FeatureTag == "kern" for i in fr.Feature.LookupListIndex}
    )
    consultas = []
    for i in indices:
        consulta = gpos.LookupList.Lookup[i]
        subtablas = []
        for st in consulta.SubTable:
            if consulta.LookupType == 9:  # extensión: la subtabla de verdad va dentro
                if st.ExtensionLookupType != 2:
                    continue
                st = st.ExtSubTable
            elif consulta.LookupType != 2:
                continue
            subtablas.append((st, {g: n for n, g in enumerate(st.Coverage.glyphs)}))
        consultas.append(tuple(subtablas))
    return tuple(consultas)


def _ajuste(ruta: str, a: str, b: str) -> float:
    """El interletraje entre los glifos a y b, en unidades de la fuente. Cada consulta aplica su primera subtabla."""
    total = 0.0
    for subtablas in _kern(ruta):
        for st, cobertura in subtablas:
            if a not in cobertura:
                continue
            if st.Format == 1:
                registro = next((r for r in st.PairSet[cobertura[a]].PairValueRecord if r.SecondGlyph == b), None)
                if registro is None:
                    continue  # el formato 1 no aplica si el segundo glifo no está: se prueba la subtabla siguiente
                valor = registro.Value1
            else:
                c1 = st.ClassDef1.classDefs.get(a, 0)
                c2 = st.ClassDef2.classDefs.get(b, 0)
                valor = st.Class1Record[c1].Class2Record[c2].Value1
            total += float(getattr(valor, "XAdvance", 0) or 0)
            break
    return total


@lru_cache(maxsize=8)
def _versalitas(ruta: str) -> dict[str, str]:
    """{glifo: su versalita} de la función `smcp` de GSUB: las versalitas que dibujó quien hizo la fuente."""
    f = _fuente(ruta)
    if "GSUB" not in f:
        return {}
    gsub = f["GSUB"].table
    if not gsub.FeatureList or not gsub.LookupList:
        return {}
    indices = sorted(
        {i for fr in gsub.FeatureList.FeatureRecord if fr.FeatureTag == "smcp" for i in fr.Feature.LookupListIndex}
    )
    mapa: dict[str, str] = {}
    for i in indices:
        consulta = gsub.LookupList.Lookup[i]
        for st in consulta.SubTable:
            if consulta.LookupType == 7:  # extensión: la subtabla de verdad va dentro
                if st.ExtensionLookupType != 1:
                    continue
                st = st.ExtSubTable
            elif consulta.LookupType != 1:
                continue
            mapa.update(st.mapping)
    return mapa


def _numero(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _contornos(glifos, nombre: str, escala: float, x: float) -> tuple[str, ...]:
    """Los contornos del glifo como `d` de SVG, escalados, con la y hacia abajo y empezando en x.

    Un glifo compuesto (la «i» de Gelasio es el palo más el punto) se descompone en sus contornos: si no, el palo y el
    punto irían en un solo trazo. Georgia y Patrick Hand SC no tienen letras compuestas: con ellas no cambia nada.
    """
    grabado = DecomposingRecordingPen(glifos)
    glifos[nombre].draw(grabado)
    contornos, actual = [], []
    for operacion, args in grabado.value:
        actual.append((operacion, args))
        if operacion in ("closePath", "endPath"):
            contornos.append(actual)
            actual = []
    if actual:
        contornos.append(actual)
    salida = []
    for contorno in contornos:
        pluma = SVGPathPen(glifos, ntos=_numero)
        transformada = TransformPen(pluma, (escala, 0, 0, -escala, x, 0))
        for operacion, args in contorno:
            getattr(transformada, operacion)(*args)
        salida.append(pluma.getCommands())
    return tuple(salida)


def compone_linea(texto: str, fuente: str | Path, tam_px: float, *, espaciado_px: float, versalitas: bool) -> Linea:
    """Compone `texto` en una línea con la fuente `fuente` a `tam_px` px.

    - `espaciado_px`: lo que se añade detrás de cada carácter, espacios incluidos (el `letter-spacing` de CSS), salvo
      detrás del último: así una línea centrada queda centrada.
    - `versalitas`: True escribe cada minúscula con su versalita, la de la función `smcp` de la fuente (la que usa
      Chrome con `font-variant: small-caps`). Para si la fuente no las tiene: sintetizarlas no es lo mismo.

    El interletraje es el de la función `kern` de la fuente, y se aplica igual que Chrome.
    """
    if not texto or not texto.strip():
        raise ErrorDeTinta("no hay texto que escribir")
    if not tam_px > 0:
        raise ErrorDeTinta(f"el tamaño de la letra tiene que ser positivo, no {tam_px}")
    ruta = str(Path(fuente))
    smcp = _versalitas(ruta) if versalitas else {}
    if versalitas and not smcp:
        raise ErrorDeTinta(f"la fuente {Path(ruta).name} no tiene versalitas (la función smcp de GSUB)")
    f = _fuente(ruta)
    mapa = f.getBestCmap()
    glifos = f.getGlyphSet()
    metricas = f["hmtx"]
    unidades = f["head"].unitsPerEm
    escala = tam_px / unidades
    letras: list[Letra] = []
    x = 0.0
    anterior: str | None = None  # el glifo anterior, para el interletraje
    for c in texto:
        nombre = mapa.get(ord(c))
        if nombre is None:
            raise ErrorDeTinta(f"la fuente {Path(ruta).name} no tiene la letra «{c}» (U+{ord(c):04X})")
        if versalitas and c.islower():
            if nombre not in smcp:
                raise ErrorDeTinta(f"la fuente {Path(ruta).name} no tiene la versalita de «{c}»")
            nombre = smcp[nombre]
        if anterior is not None and not c.isspace():
            x += _ajuste(ruta, anterior, nombre) * escala
        contornos = _contornos(glifos, nombre, escala, x) if not c.isspace() else ()
        if contornos:
            letras.append(Letra(c, contornos, x))
        x += metricas[nombre][0] * escala + espaciado_px
        anterior = None if c.isspace() else nombre
    hhea, os2 = f["hhea"], f["OS/2"]
    mayusculas = getattr(os2, "sCapHeight", 0) or hhea.ascent * 0.7
    return Linea(
        texto=texto,
        letras=tuple(letras),
        ancho=x - espaciado_px,
        ascenso=hhea.ascent * escala,
        descenso=-hhea.descent * escala,
        mayusculas=mayusculas * escala,
    )


def parte_en_lineas(texto: str, ancho_max: float, fuente: str | Path, tam_px: float, *, espaciado_px: float,
                    versalitas: bool) -> list[Linea]:  # fmt: skip
    """`texto` partido por palabras en líneas de `ancho_max` px como mucho, como haría el navegador.

    Para si una sola palabra no cabe: partirla por la mitad no es lo que se espera de un título.
    """
    kw = {"espaciado_px": espaciado_px, "versalitas": versalitas}
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = f"{actual} {palabra}" if actual else palabra
        if compone_linea(prueba, fuente, tam_px, **kw).ancho <= ancho_max:
            actual = prueba
            continue
        if not actual:
            raise ErrorDeTinta(f"«{palabra}» no cabe en {ancho_max:.0f} px a {tam_px:g} px de letra")
        lineas.append(compone_linea(actual, fuente, tam_px, **kw))
        actual = palabra
        if compone_linea(actual, fuente, tam_px, **kw).ancho > ancho_max:
            raise ErrorDeTinta(f"«{palabra}» no cabe en {ancho_max:.0f} px a {tam_px:g} px de letra")
    if actual:
        lineas.append(compone_linea(actual, fuente, tam_px, **kw))
    return lineas


# ------------------------------------------------------------------------------------------ SVG
def _svg(contenido: str, caja: tuple[float, float], clase: str) -> str:
    w, h = caja
    return (
        f'<svg class="{clase}" viewBox="0 0 {_numero(w)} {_numero(h)}" width="{_numero(w)}" height="{_numero(h)}" '
        f'xmlns="http://www.w3.org/2000/svg">{contenido}</svg>'
    )


def trazo_svg(letra: Letra, caja: tuple[float, float], origen: tuple[float, float], clase: str) -> str:
    """El SVG del contorno de una letra que el motor dibuja: un `<path class="trazo">` por contorno.

    `caja` es (ancho, alto) del elemento que lo lleva y `origen` dónde cae en él la línea base del principio de la
    línea. `clase` es la del canal (su color, su grosor).
    """
    dx, dy = origen
    caminos = "".join(f'<path class="trazo" pathLength="{LARGO_DEL_TRAZO}" d="{d}"/>' for d in letra.contornos)
    return _svg(f'<g transform="translate({_numero(dx)} {_numero(dy)})">{caminos}</g>', caja, clase)


def relleno_svg(letra: Letra, caja: tuple[float, float], origen: tuple[float, float], clase: str) -> str:
    """El SVG de la letra rellena, en un solo `<path class="relleno">` (los ojos de la letra quedan huecos)."""
    dx, dy = origen
    camino = f'<path class="relleno" d="{"".join(letra.contornos)}"/>'
    return _svg(f'<g transform="translate({_numero(dx)} {_numero(dy)})">{camino}</g>', caja, clase)


def raya_svg(
    tramos: list[tuple[tuple[float, float], tuple[float, float]]], caja: tuple[float, float], clase: str
) -> str:
    """Rayas rectas que el motor dibuja de su primer punto al segundo: [((x0, y0), (x1, y1))] en px de la caja."""
    caminos = "".join(
        f'<path class="trazo" pathLength="{LARGO_DEL_TRAZO}" '
        f'd="M{_numero(a[0])} {_numero(a[1])}L{_numero(b[0])} {_numero(b[1])}"/>'
        for a, b in tramos
    )
    return _svg(caminos, caja, clase)
