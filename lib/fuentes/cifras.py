"""Las cifras de una ficha: su frase exacta en el origen, la confirmación del usuario y las cuentas (F7.12).

Nace de las filas 273, 274 y 275 del addendum. En un explicador de economía **las cifras son el
producto**, y la ficha de antes (`ficha.py`) ataba una afirmación a fuentes con DOI o ISBN, sin sitio
para una cifra, su año, su frase ni la confirmación de nadie. Este módulo es la mecánica; `ficha.py`
decide cuándo se exige y `fuentes.py` la expone en la consola. El diseño, en `progress/spec_F7.12.md`.

Seis piezas, cada una contra un modo de fallo concreto:

- **La frase en el documento** (`busca_frase`). Claude copia la frase; el código descarga el documento
  y comprueba que la frase está, después de normalizar espacios, comillas tipográficas y guiones. Sin
  esto, «copié la frase» sería una promesa del agente.
- **Los dígitos del valor en la frase** (`digitos_del_valor_en_la_frase`). Una frase verdadera con un
  valor que no dice («$4.1 billion» sobre una frase que dice «$4.2 billion») pasaría la búsqueda.
- **La huella de la confirmación** (`huella`). El usuario confirma en la conversación; su confirmación queda
  atada al valor, la frase, la fuente, los bytes del documento, la cita, el año y el ámbito. Si cualquiera
  cambia, la huella no casa y la confirmación deja de contar, igual que la huella de una parada del motor
  de escena.
- **El redondeo** (`comprueba_redondeo`, filas 277 y 280). El valor va como lo da el documento
  («$5,323 million») y ningún narrador lo diría así. La cifra declara en `se_dice` cómo se narra
  («$5.3 billion»), y el código comprueba que es un redondeo correcto del valor y que no se aleja más del
  tope del nicho. Como lo comprueba el código, no entra en la huella: el usuario confirma el valor y su frase.
- **Las cantidades de una narración** (`cantidades`). El gate 1 de un nicho con cifras saca de cada
  lámina el dinero, los porcentajes y los «million/billion/trillion». Las cifras dichas con palabras
  las lee **la gramática del canonizador de la voz** (`lib/voice_worker.py → RecortadorPorTexto`, fila
  262), que solo usa la biblioteca estándar al importarse. Reutilizarla y no copiarla es lo que hace que
  el gate y el recorte de la voz lean igual «one hundred ninety-seven dollars».
- **Las cuentas** (`evalua`, `comprueba_cuenta`). Una cifra que sale de una cuenta vale con la cuenta
  escrita (fila 274). La aritmética la recalcula el código **recorriendo el árbol de `ast` con una lista
  cerrada de nodos**: nunca `eval`. Una expresión es texto que escribe un agente, y un `eval` sobre ella
  ejecutaría lo que dijera.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from lib.voice_worker import RecortadorPorTexto as _Canon

# --- La frase en el documento --------------------------------------------------------------------

# Lo que se iguala antes de buscar, y nada más. La lista sale de lo que cambia entre el documento y lo
# que se copia de él sin que cambie la frase: un visor de PDF pone comillas rectas donde el informe las
# tiene curvas, un guion largo se copia como corto y los saltos de línea del PDF son espacios.
_COMILLAS_SIMPLES = "‘’‚‛′`´"
_COMILLAS_DOBLES = "“”„‟″«»"
_GUIONES = "‐‑‒–—―−﹘﹣－"
_TRADUCCION = str.maketrans(
    {**{c: "'" for c in _COMILLAS_SIMPLES}, **{c: '"' for c in _COMILLAS_DOBLES}, **{c: "-" for c in _GUIONES}}
)


def normaliza_texto(texto: str) -> str:
    """El texto con los espacios, las comillas y los guiones igualados, para buscar una frase en él.

    NFKC deshace las ligaduras de un PDF («ﬁ» → «fi») y convierte el espacio duro en espacio. El guion
    blando (U+00AD) se quita, porque no se ve y un PDF lo deja dentro de las palabras. **No se tocan ni
    las mayúsculas ni los dígitos**: la frase es una copia literal, y un dígito distinto tiene que dar
    «no encontrada».
    """
    plano = unicodedata.normalize("NFKC", texto or "").replace("­", "").translate(_TRADUCCION)
    return re.sub(r"\s+", " ", plano).strip()


def busca_frase(frase: str, paginas: list[str]) -> int | None:
    """Número de página (desde 1) donde empieza la frase, o `None` si no está.

    Un HTML es una sola página. Las páginas se unen con un espacio para que una frase que cruza de una
    página a otra también se encuentre; la página que se devuelve es la de su primera letra.
    """
    buscada = normaliza_texto(frase)
    if not buscada:
        return None
    trozos = [normaliza_texto(p) for p in paginas]
    inicios, posicion = [], 0
    for trozo in trozos:
        inicios.append(posicion)
        posicion += len(trozo) + 1
    indice = " ".join(trozos).find(buscada)
    if indice < 0:
        return None
    pagina = 0
    for numero, inicio in enumerate(inicios):
        if inicio <= indice:
            pagina = numero
    return pagina + 1


_NUMERO_CON_SEPARADORES = re.compile(r"\d+(?:[.,]\d+)*")


def _tokens_numericos(texto: str) -> list[str]:
    """Los números escritos con dígitos, sin las comas de los miles: «$4,123.5» → «4123.5»."""
    return [t.replace(",", "") for t in _NUMERO_CON_SEPARADORES.findall(normaliza_texto(texto))]


def digitos_del_valor_en_la_frase(valor: str, frase: str) -> list[str]:
    """Los números del valor que NO están en la frase (lista vacía = todos están).

    Se comparan números enteros, no subcadenas: «7» no está en «1997». Un valor sin ningún dígito
    devuelve su texto, porque un valor se escribe con cifras («7%», «$4.1 billion»).
    """
    del_valor = _tokens_numericos(valor)
    if not del_valor:
        return [valor]
    de_la_frase = set(_tokens_numericos(frase))
    return [n for n in del_valor if n not in de_la_frase]


def tramos_del_valor(valor: str, frase: str) -> list[tuple[int, int]]:
    """Dónde aparecen en la frase los números del valor, para resaltarlos en la página de confirmación."""
    buscados = set(_tokens_numericos(valor))
    return [
        (m.start(), m.end()) for m in _NUMERO_CON_SEPARADORES.finditer(frase) if m.group(0).replace(",", "") in buscados
    ]


def comprueba_frase(cifra: dict, lectura) -> dict:
    """La `comprobacion` de una cifra contra la lectura de su documento (`documento.Lectura`).

    Cinco campos que escribe el código y nunca una persona: `encontrada`, `pagina` (en un PDF),
    `documento_sha256`, `descargado_el` y `lectura` (`automatica` o `manual`). Si no se encontró, va
    además `motivo`, que es lo que la página de confirmación enseña en rojo.

    - **Sin documento o ilegible** (no se pudo descargar, viene con una compresión que el código no abre, o
      es un PDF que `pypdf` no puede leer): `lectura` vacía y el motivo. No se puede confirmar.
    - **El documento no da texto** (se abre, pero es un escaneado o una página pintada con JavaScript):
      `lectura: manual`, `encontrada: false`. Se puede confirmar, y la confirmación del usuario es la única
      comprobación (la página lo marca en ámbar).
    - **Da texto**: se busca la frase. Un dígito distinto, una palabra cambiada o un valor que la frase
      no dice dan `encontrada: false`.
    """
    comprobacion = {
        "encontrada": False,
        "pagina": None,
        "documento_sha256": lectura.sha256,
        "descargado_el": lectura.descargado_el,
        "lectura": None,
        # Qué se buscó: sin esto, un borrador que cambia el valor o la frase conservando la comprobación
        # vieja dejaba confirmar una cifra que el código nunca encontró (auditoría de F7.12, crítico 1).
        "buscado": huella_de_lo_buscado(cifra),
    }
    if lectura.sha256 is None or lectura.formato is None or (lectura.error and not lectura.paginas):
        comprobacion["motivo"] = f"el código no pudo abrir el documento ({lectura.error or 'sin respuesta'})"
        return comprobacion
    if not lectura.da_texto:
        comprobacion["lectura"] = "manual"
        comprobacion["motivo"] = (
            f"el documento no da texto ({lectura.caracteres} caracteres en {len(lectura.paginas)} página(s)"
            f"{'; ' + lectura.error if lectura.error else ''}): la confirmación del usuario es la única comprobación"
        )
        return comprobacion
    comprobacion["lectura"] = "automatica"
    valor, frase = str(cifra.get("valor") or ""), str(cifra.get("frase_exacta") or "")
    ausentes = digitos_del_valor_en_la_frase(valor, frase)
    if ausentes:
        comprobacion["motivo"] = f"el valor «{valor}» no está en su frase (falta {ausentes})"
        return comprobacion
    pagina = busca_frase(frase, lectura.paginas)
    if pagina is None:
        comprobacion["motivo"] = "la frase no está en el documento, ni igualando espacios, comillas y guiones"
        return comprobacion
    comprobacion["encontrada"] = True
    comprobacion["pagina"] = pagina if lectura.formato == "pdf" else None
    return comprobacion


# --- La cita y la huella de la confirmación ------------------------------------------------------


def cita(fuente: dict) -> str:
    """La línea de una fuente en la bibliografía de la descripción, tal como sale publicada.

    `titulo_publicado` lo escribe Claude para un documento: el título de sus metadatos no sirve para
    publicar (el informe anual de Berkshire se llama «printmgr file»). Sin él va el título que devolvió
    el proveedor, como en las fichas del primer canal, que salen idénticas.
    """
    autores = ", ".join(fuente.get("autores") or []) or "s. a."
    anio = fuente.get("anio") or "s. f."
    titulo = fuente.get("titulo_publicado") or fuente["titulo"]
    url = fuente.get("url") or fuente["identificador"]
    return f"{autores} ({anio}). {titulo}. {url}"


def huella(cifra: dict) -> str | None:
    """sha256 de valor, frase_exacta, fuente, documento_sha256, cita, anio y ambito; `None` sin comprobar.

    Van en una lista JSON y no pegados: pegados, «7%» + «a» y «7» + «%a» darían la misma huella. Sin
    `documento_sha256` no hay huella, porque lo que el usuario confirma es una frase **en un documento
    concreto**. La cita (`comprobacion.cita`, la que la página le enseñó) entra porque el usuario confirma
    también cómo se publica la fuente: si después cambia el título o el editor, la confirmación no cuenta.
    El año y el ámbito entran porque la página se los enseña y el guion los dice: «$189 million» de 2025
    en EE. UU. no es la misma cifra que de 2023 en el mundo (revisión de F7.12, recomendación 3). `se_dice`
    no entra: el redondeo lo comprueba el código (fila 277).
    """
    comprobacion = cifra.get("comprobacion") or {}
    documento = comprobacion.get("documento_sha256")
    if not documento:
        return None
    carga = json.dumps(
        [
            cifra.get("valor"),
            cifra.get("frase_exacta"),
            cifra.get("fuente"),
            documento,
            comprobacion.get("cita"),
            cifra.get("anio"),
            cifra.get("ambito"),
        ],
        ensure_ascii=False,
    )
    return hashlib.sha256(carga.encode("utf-8")).hexdigest()


def cita_al_dia(cifra: dict, fuentes: dict[str, dict]) -> bool:
    """¿La cita que se comprobó con la cifra es la que su fuente publica hoy?"""
    fuente = fuentes.get(cifra.get("fuente"))
    comprobada = (cifra.get("comprobacion") or {}).get("cita")
    return fuente is not None and "titulo" in fuente and comprobada == cita(fuente)


def huella_de_lo_buscado(cifra: dict) -> str:
    """sha256 de valor + frase_exacta + fuente: lo que `--comprueba-cifras` buscó en el documento."""
    carga = json.dumps([cifra.get("valor"), cifra.get("frase_exacta"), cifra.get("fuente")], ensure_ascii=False)
    return hashlib.sha256(carga.encode("utf-8")).hexdigest()


def se_puede_confirmar(cifra: dict) -> str | None:
    """`None` si la cifra se puede confirmar; si no, el motivo.

    Se confirma lo que el código encontró en el documento, o lo que el documento no deja leer (lectura
    manual, que la página marca en ámbar). Lo que el código buscó y no encontró no se confirma: la frase
    está mal copiada o el documento no la dice.
    """
    comprobacion = cifra.get("comprobacion")
    if not comprobacion or not comprobacion.get("documento_sha256"):
        return "no está comprobada contra su documento: lanza antes `fuentes.py --comprueba-cifras`"
    if comprobacion.get("buscado") != huella_de_lo_buscado(cifra):
        return (
            "el valor, la frase o la fuente cambiaron después de comprobarla: lo que se buscó en el documento "
            "no es lo que dice la ficha; vuelve a lanzar `fuentes.py --comprueba-cifras`"
        )
    if comprobacion.get("encontrada") or comprobacion.get("lectura") == "manual":
        return None
    motivo = comprobacion.get("motivo") or "la frase no está en el documento"
    return f"el código no la encontró ({motivo}) y no es de lectura manual"


def confirmacion_vale(cifra: dict) -> bool:
    """¿Cuenta la confirmación de esta cifra? Solo si está completa y su huella casa con la de hoy."""
    confirmacion = cifra.get("confirmacion")
    if not isinstance(confirmacion, dict):
        return False
    if not all(str(confirmacion.get(c) or "").strip() for c in ("por", "el", "dijo", "huella")):
        return False
    return se_puede_confirmar(cifra) is None and confirmacion["huella"] == huella(cifra)


# --- Las cantidades de un texto ------------------------------------------------------------------

# Las escalas que hacen de una cifra una «cantidad con million/billion» (spec §3.8). «thousand» con
# dígitos («10 thousand») multiplica pero no la hace comprobable: con palabras ya lo junta el canonizador.
ESCALAS = {
    "thousand": 10**3, "thousands": 10**3,
    "million": 10**6, "millions": 10**6,
    "billion": 10**9, "billions": 10**9,
    "trillion": 10**12, "trillions": 10**12,
}  # fmt: skip
_COMPROBABLES = {"million", "millions", "billion", "billions", "trillion", "trillions"}
# Las monedas que se oyen detrás de un número. «dollars» ya la junta el canonizador cuando el número va
# con palabras; aquí se recoge también detrás de dígitos y de una escala («4.1 billion dollars»), y su
# código de tres letras («5 USD»), que antes se quedaba en un número sin unidad y solo daba aviso.
MONEDAS = {
    "dollar": "usd", "dollars": "usd", "usd": "usd",
    "euro": "eur", "euros": "eur", "eur": "eur",
    "pound": "gbp", "pounds": "gbp", "gbp": "gbp",
    "yen": "jpy", "jpy": "jpy",
    "yuan": "cny", "cny": "cny",
    "cent": "cent", "cents": "cent",
}  # fmt: skip
# Los símbolos que el normalizador de la voz no conoce (solo sabe del «$»).
_SIMBOLOS = {"€": "eur", "£": "gbp"}
_DIGITOS_DICHOS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9",
}  # fmt: skip
_CANONICA = re.compile(r"(\d+)(?:p(\d+))?(usd|pct|o)?")
_SIMBOLO_PEGADO = re.compile(r"[$€£]\s*\d|\d\s*%")
# Una escala abreviada pegada a los dígitos («45bn», «2.3m»), ya normalizada. Sin moneda ni porcentaje
# pasaba en silencio (revisión de F7.12). La «k» se queda fuera a propósito: «10-K» y «401(k)», que salen
# en un canal de economía, se normalizan a «10k» y «401k», y no son cantidades.
_ESCALA_ABREVIADA = re.compile(r"\d+(?:p\d+)?(?:m|mn|mm|b|bn|t|tn|trn)")
# La unidad de una cantidad que la gramática no sabe leer y que no puede pasar en silencio: con moneda
# o porcentaje («$4.1bn», «US$5») o con una escala abreviada («45bn»).
ILEGIBLE = "ilegible"


@dataclass(frozen=True)
class Cantidad:
    """Una cantidad leída de un texto: su número (con la escala aplicada), su unidad y lo que decía.

    `paso` es la precisión con que está escrita, con la escala aplicada: el valor de su último dígito
    escrito. «$5.3 billion» → 10⁸; «$20.00» → 0,01. En un entero, los ceros del final no cuentan:
    «34,000» → 1.000, porque así se escribe un número redondeado a los miles. Es lo que usa
    `comprueba_redondeo` para saber a qué precisión se redondeó.
    """

    numero: Decimal
    unidad: str | None  # usd · eur · gbp · jpy · cny · cent · pct · pp · ilegible · None
    con_escala: bool
    texto: str
    paso: Decimal | None = None

    @property
    def comprobable(self) -> bool:
        """Dinero, porcentaje o «million/billion/trillion»: lo que el gate 1 de un nicho con cifras exige."""
        return self.unidad is not None or self.con_escala

    def casa_con(self, otra: Cantidad) -> bool:
        """¿Dice este número dicho lo mismo que `otra`, que es una cantidad de la ficha?

        El número tiene que ser el mismo. La unidad, la misma, o ninguna en lo dicho: «about three hundred
        eighty-seven», después de hablar de dólares, es el resultado «about $387». Un porcentaje no casa
        nunca con una cantidad de dinero, ni el dólar con el euro.
        """
        return self.numero == otra.numero and (self.unidad is None or self.unidad == otra.unidad)


def _decimal(entero: str, decimales: str | None) -> Decimal:
    return Decimal(f"{entero}.{decimales}") if decimales else Decimal(entero)


def _paso(entero: str, decimales: str | None) -> Decimal:
    """El valor del último dígito escrito, sin la escala: «5.3» → 0,1; «34000» → 1.000; «197» → 1."""
    if decimales:
        return Decimal(1).scaleb(-len(decimales))
    significativo = entero.rstrip("0")
    return Decimal(1).scaleb(len(entero) - len(significativo)) if significativo.strip("0") else Decimal(1)


# Las palabras de número que la gramática de la voz conoce, para rescatarlas de su ortografía común.
_PALABRAS_DE_NUMERO = (
    set(_Canon.NUMEROS) | set(_Canon.ORDINALES) | set(_Canon.COMPUESTOS) | set(_Canon.COMPUESTOS_ORDINALES)
)


def _normaliza(palabra: str) -> str:
    """El normalizador de la voz, con una corrección: un número no pasa por la ortografía común.

    **Medido el 06-10-2026 al construir esto**: `_normaliza("four")` da «for», porque la regla británica
    `-our` → `-or` (labour/labor) también toca a «four», y lo mismo «twenty-four» → «twentyfor». Con eso,
    «four percent» no era una cantidad para la gramática y el gate 1 lo habría dejado pasar sin mirarlo:
    un fallo abierto. Aquí, si la palabra tal cual es un número que la gramática conoce, se queda tal cual.
    En la voz el efecto es otro (un «four dollars» del guion no casa con el «$4» de whisper) y se anota
    para la voz, sin cambiarla desde aquí.
    """
    tal_cual = "".join(c for c in palabra.lower() if c.isalnum())
    return tal_cual if tal_cual in _PALABRAS_DE_NUMERO else _Canon._normaliza(palabra)


def cantidades(texto: str) -> list[Cantidad]:
    """Las cantidades de un texto en inglés, en dígitos o dichas con palabras, en el orden en que salen.

    Cada palabra pasa por el normalizador de la voz, con su corrección de «four» (`_normaliza`: «$197,» →
    «197usd», «7%» → «7pct», «4.1» → «4p1», «1,000» → «1000»), y las cifras con palabras, por su
    gramática (`_cifra`: «one hundred ninety-seven dollars» → «197usd»). Encima se añade lo que el recorte
    de la voz no necesita y el gate sí: la escala («4.1 billion»), la moneda detrás de una escala o de
    dígitos («5 USD», «500 yen»), los símbolos «€» y «£», los puntos porcentuales («3 percentage points»,
    unidad `pp`), el decimal dicho («four point one») y «a million». Los ordinales («first», «21st») no son
    cantidades y no salen. Las etiquetas emocionales (`<sigh>`) se saltan, como en la voz.
    """
    crudas = [w for w in (texto or "").split() if not w.startswith("<")]
    pares = [(w, _normaliza(w)) for w in crudas]
    pares = [(w, n) for w, n in pares if n]
    p = [n for _, n in pares]
    salida: list[Cantidad] = []
    i = 0
    while i < len(p):
        w = p[i]
        dicha = _Canon._cifra(p, i)
        if dicha is not None:
            canonica, j = dicha
        elif _Canon._ORDINAL_EN_DIGITOS.fullmatch(w):
            i += 1
            continue
        elif len(w) > 1 and w[-1] == "s" and w[:-1].isdigit():
            canonica, j = w[:-1], i + 1  # «1990s»: la década, sin la ese
        elif _Canon._DIGITOS.fullmatch(w):
            canonica, j = w, i + 1
        elif w == "a" and i + 1 < len(p) and p[i + 1] in _COMPROBABLES:
            canonica, j = "1", i + 1  # «a million», «a billion»
        else:
            # **Lo que lleva moneda, porcentaje o una escala abreviada y no se lee, no se deja pasar**:
            # «$4.1bn», «US$5» o «45bn» no son una cifra para la gramática, y saltarlos dejaría abierto el
            # gate 1. Salen como `ilegible`.
            numero = _NUMERO_CON_SEPARADORES.search(pares[i][0])
            if numero and (_SIMBOLO_PEGADO.search(pares[i][0]) or _ESCALA_ABREVIADA.fullmatch(w)):
                salida.append(Cantidad(Decimal(numero.group(0).replace(",", "")), ILEGIBLE, False, pares[i][0]))
            i += 1
            continue

        partes = _CANONICA.fullmatch(canonica)
        if partes is None or partes.group(3) == "o":
            i = j  # un ordinal: «the first», «21st»
            continue
        decimales = partes.group(2)
        unidad = {"usd": "usd", "pct": "pct"}.get(partes.group(3) or "")
        for simbolo, moneda in _SIMBOLOS.items():
            if unidad is None and simbolo in pares[i][0]:
                unidad = moneda
        # «four point one billion»: el decimal dicho, solo detrás de un número con palabras y sin unidad
        if dicha is not None and unidad is None and decimales is None and j + 1 < len(p) and p[j] == "point":
            k, cifras_decimales = j + 1, ""
            while k < len(p) and p[k] in _DIGITOS_DICHOS:
                cifras_decimales += _DIGITOS_DICHOS[p[k]]
                k += 1
            if cifras_decimales:
                decimales, j = cifras_decimales, k
        numero, paso = _decimal(partes.group(1), decimales), _paso(partes.group(1), decimales)
        con_escala = False
        if j < len(p) and p[j] in ESCALAS:
            con_escala = p[j] in _COMPROBABLES
            numero, paso, j = numero * ESCALAS[p[j]], paso * ESCALAS[p[j]], j + 1
        if unidad is None and j < len(p):
            if p[j] in MONEDAS:
                unidad, j = MONEDAS[p[j]], j + 1
            elif p[j] == "percent":
                unidad, j = "pct", j + 1
            elif p[j] == "per" and j + 1 < len(p) and p[j + 1] == "cent":
                unidad, j = "pct", j + 2
            elif p[j] == "percentage" and j + 1 < len(p) and p[j + 1] in ("point", "points"):
                unidad, j = "pp", j + 2
        salida.append(Cantidad(numero, unidad, con_escala, " ".join(w for w, _ in pares[i:j]), paso))
        i = j
    return salida


def una_cantidad(texto: str) -> Cantidad | None:
    """La cantidad de un texto que tiene que decir UNA («$4.1 billion», «about $197»), o `None`.

    Una cantidad ilegible («$4.1bn») tampoco vale: un valor se escribe como se dirá.
    """
    encontradas = cantidades(texto)
    return encontradas[0] if len(encontradas) == 1 and encontradas[0].unidad != ILEGIBLE else None


# --- Las cuentas ---------------------------------------------------------------------------------


class CuentaError(ValueError):
    """Una expresión que no se puede calcular: con su motivo, que es lo que se le enseña a quien la escribió."""


# La lista cerrada. Cualquier otro nodo —una llamada, un atributo, un subíndice, una comparación, una
# lambda— falla ANTES de calcular nada. `Load` es el contexto de lectura de un nombre.
NODOS_PERMITIDOS = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd,
)  # fmt: skip
LARGO_MAXIMO_DE_EXPRESION = 300
TIPOS_DE_DATO = ("ejemplo", "real")


def evalua(expresion: str, valores: dict[str, float]) -> float:
    """El valor de una expresión aritmética con nombres, sin `eval`.

    Primero se comprueba **todo** el árbol contra la lista cerrada y solo después se calcula: una
    expresión con una llamada no llega a calcular ni su primera suma. Los números se calculan en coma
    flotante, que convierte un `10 ** 10 ** 10` en un `OverflowError` inmediato en vez de una espera.
    """
    if not isinstance(expresion, str) or not expresion.strip():
        raise CuentaError("la expresión está vacía")
    if len(expresion) > LARGO_MAXIMO_DE_EXPRESION:
        raise CuentaError(f"la expresión mide {len(expresion)} caracteres y el máximo es {LARGO_MAXIMO_DE_EXPRESION}")
    try:
        arbol = ast.parse(expresion.strip(), mode="eval")
    except SyntaxError as exc:
        raise CuentaError(f"no es una expresión aritmética: {exc.msg}") from exc
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, NODOS_PERMITIDOS):
            raise CuentaError(
                f"«{type(nodo).__name__}» no está en la lista cerrada de la cuenta: solo nombres, números, "
                "+ - * /, ** y paréntesis. No se ha calculado nada"
            )
    resultado = _calcula(arbol.body, valores)
    if not math.isfinite(resultado):
        raise CuentaError("el resultado no es un número finito")
    return resultado


def _calcula(nodo: ast.AST, valores: dict[str, float]) -> float:
    if isinstance(nodo, ast.Constant):
        if isinstance(nodo.value, bool) or not isinstance(nodo.value, (int, float)):
            raise CuentaError(f"«{nodo.value!r}» no es un número")
        return float(nodo.value)
    if isinstance(nodo, ast.Name):
        if nodo.id not in valores:
            raise CuentaError(f"el nombre «{nodo.id}» no está en `datos`")
        return float(valores[nodo.id])
    if isinstance(nodo, ast.UnaryOp):
        valor = _calcula(nodo.operand, valores)
        return -valor if isinstance(nodo.op, ast.USub) else valor
    if isinstance(nodo, ast.BinOp):
        izquierda, derecha = _calcula(nodo.left, valores), _calcula(nodo.right, valores)
        if isinstance(nodo.op, ast.Add):
            return izquierda + derecha
        if isinstance(nodo.op, ast.Sub):
            return izquierda - derecha
        if isinstance(nodo.op, ast.Mult):
            return izquierda * derecha
        if isinstance(nodo.op, ast.Div):
            if derecha == 0:
                raise CuentaError("división por cero")
            return izquierda / derecha
        try:
            potencia = izquierda**derecha
        except (OverflowError, ZeroDivisionError) as exc:
            raise CuentaError(f"la potencia no se puede calcular: {exc}") from exc
        if isinstance(potencia, complex):
            raise CuentaError("la potencia da un número complejo")
        return potencia
    raise CuentaError(f"«{type(nodo).__name__}» no está en la lista cerrada de la cuenta")


def redondea(valor: float, decimales: int) -> Decimal:
    """`valor` redondeado a `decimales` (negativos: decenas, miles…), con la mitad hacia arriba.

    Se redondea en `Decimal` y no con `round()`, que en coma flotante da `round(2.675, 2) == 2.67`: «about»
    se dice con el redondeo de la escuela.
    """
    return Decimal(repr(valor)).quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)


def _es_numero(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


def valor_de_la_cifra(cifra: dict) -> Cantidad | None:
    """La cantidad que dice el `valor` de una cifra de la ficha, si dice una."""
    return una_cantidad(str(cifra.get("valor") or ""))


def dato_casa_con(valor: float, dicha: Cantidad, de_su_cifra: Cantidad | None = None) -> bool:
    """¿Es `dicha` la forma de decir el dato `valor` de una cuenta?

    - **Un dato real** (`de_su_cifra`, la cantidad del valor de la cifra a la que apunta) se dice con la
      unidad de su cifra, o sin unidad: «90%» y «90» dicen el dato 90 de la cifra «90%», y «$90» no. Un
      porcentaje se dice también en tanto por uno: «3.4%» dice el dato 0,034 de la cifra «3.4%».
    - **Un dato de ejemplo** no tiene unidad, así que «$100» y «100» dicen el dato 100. Un porcentaje solo
      lo dice en tanto por uno («7%» dice 0,07): «100%» no dice el capital de ejemplo de 100, que antes
      casaba sin mirar la unidad (revisión de F7.12).
    """
    try:
        exacto = Decimal(repr(float(valor)))
    except (InvalidOperation, ValueError):
        return False
    en_tanto_por_uno = dicha.unidad == "pct" and dicha.numero == exacto * 100
    if de_su_cifra is None:
        return en_tanto_por_uno if dicha.unidad == "pct" else dicha.numero == exacto
    if dicha.unidad not in (None, de_su_cifra.unidad):
        return False
    return dicha.numero == exacto or (de_su_cifra.unidad == "pct" and en_tanto_por_uno)


def comprueba_redondeo(cifra: dict, error_maximo_pct: float | None) -> str | None:
    """`None` si el `se_dice` de la cifra es un redondeo correcto de su `valor`; si no, el motivo (filas 277 y 280).

    Una cifra sin `se_dice` no tiene nada que comprobar: se dice su valor. Con él:

    - `se_dice` dice UNA cantidad, con la misma unidad que el valor;
    - es el valor redondeado a la precisión con que está escrito `se_dice` (`Cantidad.paso`), con la mitad
      hacia arriba: «$5.3 billion» es 5.323 M$ redondeado a la centena de millón;
    - no se aleja del valor más de `error_maximo_pct` (el tope del perfil del nicho, fila 280): «$100
      million» es un redondeo correcto de 149 M$, pero se aleja un 33 %.

    Sin tope (`None`, un nicho que no declara `cifras.redondeo`) no se comprueba nada y se dice por qué.
    """
    if "se_dice" not in cifra:
        return None
    se_dice = cifra.get("se_dice")
    if error_maximo_pct is None:
        return (
            "lleva `se_dice` y el perfil del nicho no declara `cifras.redondeo.error_maximo_pct`: sin su tope no se "
            "comprueba un redondeo"
        )
    dicho = una_cantidad(se_dice) if isinstance(se_dice, str) else None
    if dicho is None or dicho.paso is None:
        return f"`se_dice` ({se_dice!r}) tiene que decir UNA cantidad, como se dirá («$5.3 billion», «92%»)"
    valor = valor_de_la_cifra(cifra)
    if valor is None:
        return "su `valor` no dice una cantidad, así que su redondeo no se puede comprobar"
    if dicho.unidad != valor.unidad:
        de_se_dice, del_valor = dicho.unidad or "sin unidad", valor.unidad or "sin unidad"
        return f"`se_dice` («{se_dice}») va en {de_se_dice} y el valor, en {del_valor}"
    try:
        redondeado = (valor.numero / dicho.paso).quantize(Decimal(1), rounding=ROUND_HALF_UP) * dicho.paso
    except InvalidOperation:
        # Más de 28 cifras entre el valor y la precisión de `se_dice`: `Decimal` no lo redondea (auditoría del
        # 06-10). Ningún narrador lo diría; se rechaza con su motivo en vez de con una traza.
        return f"`se_dice` («{se_dice}») tiene más cifras de las que se pueden comprobar: escríbelo como se dirá"
    if dicho.numero != redondeado:
        return (
            f"`se_dice` («{se_dice}») no es un redondeo de «{cifra.get('valor')}»: a su precisión, el valor da "
            f"{_legible(redondeado)}"
        )
    # Con un valor 0, el único redondeo correcto es 0, y ya lo ha comprobado lo de arriba.
    alejamiento = abs(dicho.numero - valor.numero) / abs(valor.numero) * 100 if valor.numero else Decimal(0)
    if alejamiento > Decimal(repr(error_maximo_pct)):
        return (
            f"`se_dice` («{se_dice}») se aleja un {_legible(alejamiento.quantize(Decimal('0.1')))} % de "
            f"«{cifra.get('valor')}» y el tope del nicho es {error_maximo_pct} %: redondea a más cifras"
        )
    return None


def formas_de_decir(cifra: dict, error_maximo_pct: float | None) -> list[Cantidad]:
    """Las cantidades con que el guion puede decir una cifra: su valor y, si el redondeo casa, su `se_dice`."""
    valor = valor_de_la_cifra(cifra)
    if valor is None:
        return []
    formas = [valor]
    if "se_dice" in cifra and comprueba_redondeo(cifra, error_maximo_pct) is None:
        formas.append(una_cantidad(cifra["se_dice"]))
    return formas


def _legible(numero: Decimal) -> str:
    """Un `Decimal` sin notación científica, para un mensaje: 5.3E+9 → «5300000000»."""
    return f"{numero.normalize():f}"


@dataclass
class Revision:
    """Lo que se sabe de una cuenta después de recalcularla."""

    calculado: float | None
    problemas: list[str]
    pendientes: list[str]  # datos reales cuya cifra existe y el usuario aún no ha confirmado


def comprueba_cuenta(cuenta: dict, cifras: list[dict]) -> Revision:
    """Recalcula una cuenta y comprueba lo que dice (spec §3.5).

    - `resultado` es el calculado (tolerancia de redondeo de la coma flotante, nada más);
    - el número de `se_dice` es el resultado redondeado a `redondeo`;
    - un dato `real` lleva `cifra`, el id de una cifra de la ficha, y su valor es el de la cifra (o su
      tanto por uno, si la cifra es un porcentaje). Si esa cifra no está confirmada, va a `pendientes`:
      la ficha puede guardarse antes de que el usuario confirme, pero no subir de nivel.
    """
    problemas: list[str] = []
    pendientes: list[str] = []
    nombre = cuenta.get("id") or "(sin id)"
    datos = cuenta.get("datos")
    if not isinstance(datos, dict) or not datos:
        return Revision(None, [f"cuenta {nombre}: `datos` tiene que ser un objeto con un dato por nombre"], [])
    por_id = {c.get("id"): c for c in cifras}
    valores: dict[str, float] = {}
    for clave, dato in datos.items():
        if not isinstance(dato, dict) or not _es_numero(dato.get("valor")):
            problemas.append(f"cuenta {nombre}: el dato «{clave}» necesita un `valor` numérico")
            continue
        valores[clave] = float(dato["valor"])
        tipo = dato.get("tipo")
        if tipo not in TIPOS_DE_DATO:
            problemas.append(
                f"cuenta {nombre}: el dato «{clave}» tiene `tipo` {tipo!r}; admitidos: {list(TIPOS_DE_DATO)}"
            )
            continue
        if tipo == "ejemplo":
            if "cifra" in dato:
                problemas.append(
                    f"cuenta {nombre}: el dato «{clave}» es de ejemplo y apunta a una cifra; si se presenta "
                    "como real, su `tipo` es «real»"
                )
            continue
        cifra = por_id.get(dato.get("cifra"))
        if cifra is None:
            problemas.append(
                f"cuenta {nombre}: el dato real «{clave}» no apunta a una cifra de la ficha (`cifra`: "
                f"{dato.get('cifra')!r}). Un dato que se presenta como real se respalda como cualquier cifra"
            )
            continue
        cantidad = valor_de_la_cifra(cifra)
        if cantidad is None or not dato_casa_con(dato["valor"], cantidad, cantidad):
            problemas.append(
                f"cuenta {nombre}: el dato real «{clave}» vale {dato['valor']} y su cifra «{cifra.get('id')}» "
                f"dice «{cifra.get('valor')}»"
            )
        elif not confirmacion_vale(cifra):
            pendientes.append(
                f"cuenta {nombre}: el dato real «{clave}» apunta a la cifra «{cifra.get('id')}», sin confirmar"
            )
    if problemas:
        return Revision(None, problemas, pendientes)

    try:
        calculado = evalua(cuenta.get("expresion"), valores)
    except CuentaError as exc:
        return Revision(None, [f"cuenta {nombre}: {exc}"], pendientes)

    resultado = cuenta.get("resultado")
    if not _es_numero(resultado) or not math.isclose(resultado, calculado, rel_tol=1e-9, abs_tol=1e-9):
        problemas.append(f"cuenta {nombre}: `resultado` vale {resultado!r} y la expresión da {calculado!r}")
    decimales = cuenta.get("redondeo")
    dicho = una_cantidad(str(cuenta.get("se_dice") or ""))
    if isinstance(decimales, bool) or not isinstance(decimales, int) or not -12 <= decimales <= 12:
        problemas.append(f"cuenta {nombre}: `redondeo` tiene que ser un entero de decimales (0 = unidades, -3 = miles)")
    elif dicho is None:
        problemas.append(f"cuenta {nombre}: `se_dice` ({cuenta.get('se_dice')!r}) tiene que decir UNA cantidad")
    elif dicho.numero != redondea(calculado, decimales):
        problemas.append(
            f"cuenta {nombre}: `se_dice` dice {dicho.numero} y el resultado redondeado a {decimales} "
            f"decimal(es) es {redondea(calculado, decimales)}"
        )
    return Revision(calculado, problemas, pendientes)
