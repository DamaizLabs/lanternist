"""La miniatura del vídeo: recorte al objeto, texto compuesto y las comprobaciones que suspenden.

## Dos cosas que el modelo NO hace, y por eso se hacen fuera de él

**No escribe texto.** El contrato de prompt de imagen del primer canal ya lo tenía medido entre los
defectos: «**garabatos que imitan texto** en fachadas y suelo, pese al `no text, no watermark` del
prefijo», y la auditoría de F2.5 los encontró en las ocho láminas de un run. Confirmado otra vez el
28-08 en la primera miniatura de F3.6: garabatos en las dos esquinas inferiores y en la superior
derecha, con `no text, no letters, no numbers` en el prompt. Así que el texto se **compone después**
con tipografía real — y eso, además, es lo que hace comprobable la regla de los 168 px: si el tamaño
lo pone el estudio, se puede exigir en vez de estimarlo.

**No reencuadra.** El prompt de miniatura pide «the artefact fills most of the frame» y «background
almost empty», y el modelo devolvió la plaza entera con dos edificios, el empedrado y un marco
decorativo. Así que el encuadre se hace **recortando**, y el recorte sabe dónde está el objeto por una
propiedad del canal —no del estudio—: **el artefacto es lo único con color**. La mancha de acento más
grande ES el objeto. Recortar a ella resuelve tres cosas de una: encuadra, quita el marco y **se lleva
los garabatos de las esquinas**.

**Que esa premisa valga lo decide el canal, y se LEE de `perfil.json → imagen.acento_de_color`**
(`canal_tiene_acento()`): con la clave en falso no se recorta. Hace falta esa comprobación además de la
del propio localizador, porque son cosas distintas: `caja_del_objeto()` detecta «esta imagen no tiene
acento», y en un canal a color la máscara de saturación **sí encuentra manchas** y devolvería una caja
arbitraria como si fuera el objeto. La auditoría de F3.6 cazó justo eso: la documentación prometía la
comprobación fuerte y el código hacía la débil.

## Qué suspende un run y qué solo se anota: cuatro métricas probadas, ninguna de encuadre sobrevive

Esta parte se midió antes de escribirla y **las cuatro candidatas para juzgar el encuadre fallaron**.
Queda escrito porque el resultado es más útil que cualquier umbral: dice qué se puede automatizar aquí
y qué no. Todas las cifras salen del run `2026-08-27_181546_sprint-2-closure-run-all-one-pass` y se
re-derivan con `fraccion_de_acento()` y `caja_del_objeto()` sobre las láminas de los runs de ese canal.

1. **Desviación típica del gris al reducir a 168 px**, y es la que **apunta al revés**. Las 8 láminas
   van de **62,3** (`slide-03`) a **72,8** (`slide-02`). La miniatura **antes de componer el texto**
   da **61,7**: por DEBAJO de todas, porque el recorte se lleva los edificios y el marco, que son
   detalle, y menos detalle es menos desviación. O sea que un umbral «que supere a sus láminas»
   **rechazaría precisamente la miniatura bien recortada**. Después del texto sube a **73,5**, por
   encima de todas, pero eso mide **el texto**, que ya tiene su propio gate. Las dos se publican
   (`desviacion_a_168px_sin_texto` y `desviacion_a_168px`) para que esto se compruebe en vez de
   creerse.
2. **Fracción de acento**, que es la medida que el contrato pedía «medir y no estimar»: las láminas
   van de **3,2 %** (`slide-04`) a **35,6 %** (`slide-02`), mediana 9,3. La miniatura da **16,8 %**:
   dentro del rango y muy por debajo de `slide-02`. Medirlo es exactamente lo que la descartó.
3. **Área de la caja del objeto sobre el cuadro.** Discriminaba en la dirección correcta, pero el
   umbral quedaba **pegado al techo geométrico**: un objeto casi cuadrado dentro de un cuadro 16:9 no
   puede pasar de `1/1,778` = 56,3 % de área. Un margen de décimas no es un gate, es una lotería. Y el
   rango tampoco ayuda: láminas de **5,7 %** a **74,5 %**, miniatura **52,0 %**, otra vez dentro.
4. **Alto del objeto sobre el alto del cuadro**, la única sin techo por aspecto. Láminas de **28,3 %**
   (`slide-06`) a **92,7 %** (`slide-08`), mediana **69,7 %**; miniatura **78,2 %**. Está dentro, y
   `slide-08` es **más** retrato de objeto que la propia miniatura.

**Las láminas de este canal YA son retratos de objeto**, así que la premisa de que una miniatura se
distingue por el encuadre es aquí solo débilmente cierta. Lo que de verdad la separa es **el texto** y
la ausencia de escena alrededor.

Por eso el reparto final:

- **SUSPENDE**: el **texto** — presente, hasta 5 palabras, cabiendo entero en el cuadro, con altura de
  mayúscula ≥ 9 px al reducir a 168 × 94 y contraste ≥ 4,5:1 sobre su fondo. Los cuatro se miden.
  `pipeline.py` marca la etapa `blocked` y lanza cuando `cumple` es falso, igual que con las líneas
  rojas: no es un aviso.
- **SUSPENDE**: las **líneas rojas** del canal. No las mira este módulo: las llama `pipeline.py` con
  `lib/lineas_rojas.py`, igual que sobre las láminas.
- **SE ANOTA, no suspende**: el alto del objeto, su ocupación, el acento y las dos desviaciones, todo
  frente a la mediana de las láminas del propio run. Sirven para comparar dos candidatas y para ver si
  el recorte hizo algo; **no para aprobar**, porque su rango se solapa con el de las láminas y un
  umbral ahí sería un gate falso que aprueba láminas y suspende miniaturas buenas.

El **recorte al objeto sí se mantiene**, no como gate sino como transformación: mide, mejora la
ocupación y sobre todo **se lleva el marco decorativo y los garabatos de las esquinas**, que es donde
el modelo los pone.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from lib import provenance

# ── Umbrales, cada uno con su derivación ──────────────────────────────────────────────────────
TAMANO_SUGERIDOS = (168, 94)  # la lista de sugeridos: el peor caso realista del contrato
ALTURA_MAYUSCULA_MINIMA_PX = 9  # a 168×94, por debajo de esto un texto no se lee
CONTRASTE_MINIMO = 4.5  # WCAG para texto normal: el único criterio público y medible
ACENTO_MARGEN_SATURACION = 40  # cuánto ha de superar la mediana para contar como acento
# Cuánto más que las láminas del propio run se busca que ocupe el objeto AL RECORTAR. Es el objetivo
# de una transformación, no un umbral de aprobación: el gate del encuadre se retiró porque su rango se
# solapa con el de las láminas (ver el docstring del módulo). 1,43 = el 1,3 que se probó como gate por
# el 10 % de holgura que llevaba pegado aparte en `pipeline.py`, ahora en un solo sitio.
OBJETIVO_DEL_RECORTE = 1.43
MARGEN_RECORTE = 1.25  # cuánto aire se deja alrededor del objeto al recortar
# **Es una CONVENCIÓN del contrato del canal, no una derivación**, y conviene que esté dicho porque las
# dos veces que intenté derivarla del tamaño de letra me salió mal. Contar palabras **no predice la
# legibilidad**: lo que fija el cuerpo es **el ancho del texto al pintarlo**, del que los caracteres son
# buen proxy y las palabras no. Medido con `_mayor_cuerpo_que_cabe()` sobre 1280×720:
# `THE HINGE THAT NEVER CLOSED` (5 palabras, 27 caracteres) da 9,3 px de mayúscula a 168, pero
# `MEDIEVAL IRON MAIDEN NEVER EXISTED` (5 palabras, 34) cae a **7,4**, por debajo del suelo; y
# `IS IT A MYTH OR NO` (6 palabras, 18) da **15,3**, de sobra. O sea que el máximo falla en las dos
# direcciones como criterio de legibilidad. Y ni siquiera los caracteres bastan: `IT NEVER EXISTED` y
# `PUBLIC BY DESIGN` tienen los dos **16** y dan cuerpos **154** y **152**.
#
# **Lo que protege la legibilidad es `ALTURA_MAYUSCULA_MINIMA_PX`, que se mide texto a texto** y caza
# el caso de 7,4. El máximo de 5 se queda por lo que dice el contrato del canal —que la miniatura lleve
# un gancho y no el título, que ya va al lado—, y por lo mismo el **mínimo de 3 se retiró**: rechazaba
# `MYTH?` y `THE HINGE`, dos de los tres ejemplos del propio contrato. Si otro canal quiere otro
# número, esto baja al perfil; hoy no hay segundo canal (decisión 12).
PALABRAS_MAXIMAS = 5

# El texto no puede ocupar el cuadro entero: el contrato pone el objeto como retrato y el texto debajo.
# El techo sale de lo medido, no de un gusto: el objeto de la miniatura recortada del 28-08 llega al
# **78,2 %** del alto (`miniatura.json → reportado_no_es_gate.alto_del_objeto`), así que lo que queda
# libre para el texto es el ~20 % de abajo.
ALTO_MAXIMO_DEL_TEXTO = 0.20
ANCHO_MAXIMO_DEL_TEXTO = 0.86  # deja aire a los lados: pegado al borde se lee peor al reducir
MARGEN_INFERIOR_DEL_TEXTO = 0.04  # y no pegado abajo, que es donde YouTube pinta la barra de tiempo

# Lo que admite `thumbnails.set` de YouTube: 2 MB como mucho, y 1280×720 es el tamaño que recomienda. Un fotograma
# del vídeo sale a 1920×1080, y en PNG ronda 1,6 MB antes de llevar el texto (la bici a 420 s, 02-10). Por eso un
# fotograma se reduce a 1280×720, y el peso se comprueba en todas, salga de donde salga la miniatura.
PESO_MAXIMO_BYTES = 2 * 1024 * 1024
TAMANO_DE_FOTOGRAMA = (1280, 720)

# ── La fuente del texto: la declara el canal y sale de la biblioteca del estudio (OC1.4) ────────────────────────────
# Hasta OC1.4 aquí había una lista de reserva de fuentes de Windows (Impact, Segoe UI Black y Arial): el estudio elegía
# la letra del canal (F4.9), la letra no llegaba a `assets.json` y no se podía redistribuir. Es lo que OC1.2 arregló
# con Georgia en los rótulos, y se arregla igual: el perfil nombra un fichero de `datos/escena/fuentes/`, que viaja con
# su licencia y su `CREDITOS.json`, y la etapa que dibuja el texto copia la fuente a su carpeta con su registro.
# Para la miniatura lo dice `imagen.fuente_de_la_miniatura`; para el banner, `marca.banner.fuente`
# (`lib/canal_marca.py`).
# Conviene una letra de peso alto y estrecha: el texto tiene que sobrevivir a la reducción a 168 px.
CLAVE_FUENTE = "imagen.fuente_de_la_miniatura"
# Dónde queda la copia de la fuente dentro del run, con su registro de procedencia.
CARPETA_DE_LA_FUENTE = "fuente-de-la-miniatura"


def fuente_declarada(perfil: dict, ruta: str) -> Path:
    """La fuente que el perfil declara en `ruta` («imagen.fuente_de_la_miniatura»), de la biblioteca del estudio.

    Para, y dice qué escribir, si el perfil no la declara (no tiene defecto, F4.9), si no es un fichero de
    `datos/escena/fuentes/` o si no tiene su entrada en el `CREDITOS.json` de esa carpeta: sin procedencia no entra en
    una imagen que se publica (decisión 5).
    """
    from lib import config
    from lib.escena import audio  # aquí y no arriba: arrastra la música y la procedencia

    carpeta = config.ESCENA_FUENTES_DIR
    creditos = audio.lee_creditos(carpeta)
    disponibles = ", ".join(
        sorted(n for n in creditos if (carpeta / n).is_file() and Path(n).suffix in (".ttf", ".otf"))
    )
    nodo = config.en_el_perfil(perfil, ruta)
    if not isinstance(nodo, str) or not nodo.strip():
        raise ValueError(
            f"el perfil del canal no declara `{ruta}`: el fichero de la fuente con que se escribe el texto. Escribe "
            f"uno de la biblioteca del motor ({carpeta}): {disponibles}. No tiene valor por defecto: la letra es "
            "del canal"
        )
    nombre = nodo.strip()
    if Path(nombre).name != nombre or not (carpeta / nombre).is_file():
        raise ValueError(
            f"`{ruta}` vale {nombre!r} y no es una fuente de la biblioteca del estudio ({carpeta}). Una fuente del "
            f"sistema no vale: no tiene licencia de redistribución ni procedencia. Las que hay: {disponibles}"
        )
    if nombre not in creditos:
        raise ValueError(
            f"la fuente {nombre!r} de `{ruta}` no tiene su entrada en {carpeta / config.ESCENA_CREDITOS}: sin fuente, "
            "licencia y url no entra en una imagen que se publica"
        )
    return carpeta / nombre


def copia_la_fuente(fuente: Path, carpeta: Path, etapa: str) -> dict:
    """Copia la fuente a `carpeta` con su registro de procedencia, que es lo que la lleva a `assets.json`.

    `carpeta` se rehace entera en cada llamada: queda solo la fuente que se usó la última vez, igual que la biblioteca
    de un episodio (`lib/escena/audio.biblioteca`). La copia es la de la biblioteca si su sha256 es el apuntado; si no,
    para (`audio.de_la_biblioteca`). Devuelve el registro.
    """
    import shutil

    from lib import config
    from lib.escena import audio

    carpeta = Path(carpeta)
    if carpeta.exists():
        shutil.rmtree(carpeta)
    creditos = audio.lee_creditos(config.ESCENA_FUENTES_DIR)
    registro = audio.de_la_biblioteca(config.ESCENA_FUENTES_DIR, Path(fuente).name, "fuente", carpeta, creditos)
    registro["etapa"] = etapa
    provenance.anade_registros(carpeta / provenance.LIBRARY_RECORDS_FILENAME, [registro])
    return registro


def _lee(ruta: str | Path):
    """Lee una imagen con OpenCV sin morir por los acentos de la ruta (Windows)."""
    img = cv2.imdecode(np.fromfile(str(ruta), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"no se puede leer la imagen: {ruta}")
    return img


def _luminancia_relativa(rgb) -> float:
    """Luminancia relativa de la WCAG: hace falta para el contraste, el gris a secas no vale."""
    canales = []
    for c in rgb:
        c = c / 255.0
        canales.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * canales[0] + 0.7152 * canales[1] + 0.0722 * canales[2]


def contraste(rgb_a, rgb_b) -> float:
    """Razón de contraste WCAG entre dos colores: de 1 (igual) a 21 (negro sobre blanco)."""
    la, lb = _luminancia_relativa(rgb_a), _luminancia_relativa(rgb_b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def desviacion_a_168px(ruta: str | Path) -> float:
    """Desviación típica del gris al reducir al tamaño de la lista de sugeridos.

    Se publica, no aprueba: ver el punto 1 del docstring del módulo.
    """
    pequena = Image.open(ruta).convert("RGB").resize(TAMANO_SUGERIDOS, Image.Resampling.LANCZOS)
    return float(np.asarray(pequena.convert("L"), dtype=np.float64).std())


def caja_del_objeto(ruta: str | Path) -> tuple[tuple[int, int, int, int], float, bool]:
    """Localiza el objeto por su acento de color: (caja, fracción del cuadro, si lo encontró).

    **La premisa es del CANAL, no del estudio**: que el artefacto sea lo único con color es cierto en
    el primer canal (`perfil.json → imagen.acento_de_color`) y falso en un canal a color. Por eso el
    tercer valor no es un adorno: cuando no hay ninguna mancha de acento, esto devolvía **el cuadro
    entero como si fuera el objeto** y todo lo que se apoyara en ello quedaba mintiendo en silencio.
    Ahora el llamador se entera y decide.

    Se cierra con morfología antes de etiquetar porque el rayado a plumilla parte la mancha en trozos,
    y sin cerrar el «objeto» saldría troceado.
    """
    img = _lee(ruta)
    h, w = img.shape[:2]
    sat = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 1].astype(np.int16)
    mascara = (sat > (np.median(sat) + ACENTO_MARGEN_SATURACION)).astype(np.uint8)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mascara, connectivity=8)
    if n <= 1:
        return (0, 0, w, h), 0.0, False
    k = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
    x, y = int(stats[k, cv2.CC_STAT_LEFT]), int(stats[k, cv2.CC_STAT_TOP])
    bw, bh = int(stats[k, cv2.CC_STAT_WIDTH]), int(stats[k, cv2.CC_STAT_HEIGHT])
    return (x, y, bw, bh), float(bw * bh / (w * h)), True


def fraccion_de_acento(ruta: str | Path) -> float:
    """Qué parte del cuadro pasa el umbral de acento. Es la MEDIDA del «acento sobre el monocromo».

    Está aquí porque el contrato pide que el acento «se mida, no se estime», y medirlo es lo que
    demostró que **no vale de gate** (punto 2 del docstring del módulo). Se reporta con esa advertencia
    en vez de callarla.
    """
    img = _lee(ruta)
    sat = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 1].astype(np.int16)
    return float((sat > (np.median(sat) + ACENTO_MARGEN_SATURACION)).mean())


def canal_tiene_acento(perfil: dict) -> bool:
    """`perfil.json → imagen.acento_de_color`. Sin perfil o sin la clave, se asume que NO.

    Se asume que no **a propósito**: este localizador se apoya en que el artefacto sea lo único con
    color, y en un canal que no lo cumpla la máscara de saturación **sí encuentra manchas** y devuelve
    una caja arbitraria con `encontrado=True`. O sea que el `n <= 1` del localizador no cubre ese caso:
    detecta «esta imagen no tiene acento», no «este canal no funciona así». Son condiciones distintas
    y la diferencia la cazó la auditoría de F3.6, donde la documentación prometía la fuerte y el código
    hacía la débil. Por eso la decisión es del perfil y el defecto es no recortar.
    """
    return bool((perfil.get("imagen") or {}).get("acento_de_color"))


def recorta_al_objeto(
    ruta: str | Path,
    ruta_salida: str | Path | None = None,
    aspecto: float = 16 / 9,
    objetivo: float | None = None,
    hay_acento: bool = True,
) -> dict:
    """Recorta al objeto conservando 16:9, y devuelve lo que hizo.

    El modelo no reencuadra por prompt —comprobado—, así que el encuadre se hace aquí. De paso se
    lleva el marco decorativo y los garabatos de las esquinas, que es donde el modelo los pone.

    **El recorte PERSIGUE la ocupación objetivo**, no un margen fijo. Con un margen constante el
    resultado depende de lo lejos que el modelo haya puesto el objeto —medido: la misma escena dio
    56,1 % una vez y 28,1 % otra—, o sea que el encuadre final sería lotería del modelo. Con
    `objetivo`, el área del recorte se calcula para que el objeto la ocupe.

    **Si no hay acento, no recorta**: recortar al «objeto» que devuelve un localizador que no encontró
    nada sería recortar al azar. Se dice y se devuelve la imagen intacta.
    """
    imagen = Image.open(ruta).convert("RGB")
    w, h = imagen.size
    (x, y, bw, bh), antes, encontrado = caja_del_objeto(ruta)
    if not hay_acento or not encontrado:
        return {
            "recortado": False,
            "por_que_no": (
                "el canal no declara acento de color (perfil.json → imagen.acento_de_color), así que "
                "este localizador no aplica: la mancha más saturada de una imagen a color no es el "
                "objeto"
                if not hay_acento
                else "no se ha encontrado ninguna mancha de acento en esta imagen, así que no se sabe "
                "dónde está el objeto y recortar sería recortar al azar"
            ),
            "ocupacion_antes": round(antes, 4),
            "ocupacion_despues": round(antes, 4),
            "salida": str(Path(ruta_salida or ruta)),
        }
    cx, cy = x + bw // 2, y + bh // 2

    if objetivo and objetivo > 0:
        area = (bw * bh) / min(0.9, objetivo)
        alto = int((area / aspecto) ** 0.5)
    else:
        alto = max(int(bh * MARGEN_RECORTE), int(bw * MARGEN_RECORTE / aspecto))
    # Nunca más pequeño que el objeto ni más grande que la imagen
    alto = min(h, max(alto, bh, int(bw / aspecto)))
    ancho = min(w, int(alto * aspecto))
    alto = int(ancho / aspecto)
    x1 = max(0, min(w - ancho, cx - ancho // 2))
    y1 = max(0, min(h - alto, cy - alto // 2))

    recortada = imagen.crop((x1, y1, x1 + ancho, y1 + alto)).resize((w, h), Image.Resampling.LANCZOS)
    destino = Path(ruta_salida or ruta)
    recortada.save(destino)
    _, despues, _ = caja_del_objeto(destino)
    return {
        "recortado": True,
        "caja_del_objeto": [x, y, bw, bh],
        "recorte": [x1, y1, ancho, alto],
        "ocupacion_antes": round(antes, 4),
        "ocupacion_despues": round(despues, 4),
        "objetivo": round(objetivo, 4) if objetivo else None,
        "salida": str(destino),
    }


# Lo que el estudio pide de CUALQUIER miniatura, sea del canal que sea: un retrato del objeto, sin
# escena, sin marco y sin letras. El acabado —el rayado, el acento— es del canal y llega por
# `clausulas_del_canal`, igual que el prefijo de las láminas viaja por `slides.json`.
CLAUSULAS_DEL_ESTUDIO_ANTES = (
    "framed as a PORTRAIT of the object: the artefact fills most of the frame, centred",
    "background almost empty and plain, no buildings, no architecture, no ground detail",
)
CLAUSULAS_DEL_ESTUDIO_DESPUES = (
    "no frame, no border, no passepartout around the image",
    "no text, no letters, no numbers, no watermark, no signature anywhere",
)


def prompt_de_miniatura(prompt_de_escena: str, clausulas_del_canal: list[str] | None = None) -> str:
    """Convierte una descripción de escena en el prompt de MINIATURA.

    **LA ETAPA YA NO LA LLAMA** (addendum fila 156): desde el 12-09 la miniatura sale siempre de una
    lámina del run, así que `stage_thumbnail` no genera ninguna imagen. Se conserva porque sigue siendo
    la herramienta con la que se comparan candidatas **a mano**, fuera del pipeline, como en
    `experimentos/ep1-miniatura-2026-09-10/`.

    Se pide el encuadre y el fondo vacío **aunque el modelo no obedezca**: cuando obedece a medias, el
    recorte tiene menos que corregir. Lo que no se hace es dar por hecho que obedece.

    **Las cláusulas del acabado son del canal**, no de aquí: «rayado a plumilla más grueso» o «el
    acento saturado» describen a un canal y no a un estudio. Llegan de
    `perfil.json → imagen.miniatura_clausulas`, que es lo mismo que hizo F3.4 con el idioma y el estilo
    de `script-to-slides` — dejarlas incrustadas era repetir esa deriva a la semana siguiente.
    """
    base = prompt_de_escena.strip().rstrip(".")
    partes = [
        base,
        *CLAUSULAS_DEL_ESTUDIO_ANTES,
        *[c.strip().rstrip(".") for c in (clausulas_del_canal or []) if c.strip()],
        *CLAUSULAS_DEL_ESTUDIO_DESPUES,
    ]
    return ". ".join(partes) + "."


def tipografia(fuente: Path, tamano: int) -> ImageFont.FreeTypeFont:
    """La fuente declarada por el canal (`fuente_declarada`), al cuerpo pedido.

    Es pública porque **la comparte el banner del canal** (`lib/canal_marca.py`, F4.0): el problema es
    el mismo —texto que tiene que sobrevivir a una reducción fuerte—. Lo que NO se comparte es el encaje,
    que tiene reglas distintas en cada sitio (ver `_mayor_cuerpo_que_cabe`).
    """
    return ImageFont.truetype(str(fuente), tamano)


def altura_mayuscula(fuente: ImageFont.FreeTypeFont) -> int:
    """Altura de la caja de una «H»: es la medida que decide si un texto se lee al reducir."""
    caja = fuente.getbbox("H")
    return caja[3] - caja[1]


def grosor_del_contorno(tamano: int) -> int:
    """Grosor del contorno del texto. Pública por el mismo motivo que `tipografia`."""
    return max(2, tamano // 18)


def _mayor_cuerpo_que_cabe(texto: str, ancho: int, alto: int, fuente: Path) -> tuple[int, ImageFont.FreeTypeFont]:
    """El cuerpo más grande cuyo texto CABE, contorno incluido, a lo ancho y a lo alto.

    Se crece desde abajo y se para al primero que no cabe, así que el elegido **siempre cabe**. La
    versión anterior hacía lo contrario —crecía a saltos y una de sus dos ramas se saltaba el límite de
    ancho— y por eso certificaba como legible un texto que se salía del cuadro por los dos lados: la
    auditoría de F3.6 lo midió con tres de los ejemplos del propio contrato.
    """
    limite_ancho = ancho * ANCHO_MAXIMO_DEL_TEXTO
    limite_alto = alto * ALTO_MAXIMO_DEL_TEXTO
    elegido: tuple[int, ImageFont.FreeTypeFont] | None = None
    tamano = 8
    while tamano < alto:
        letra = tipografia(fuente, tamano)
        caja = letra.getbbox(texto)
        contorno = grosor_del_contorno(tamano)
        if (caja[2] - caja[0]) + 2 * contorno > limite_ancho:
            break
        if (caja[3] - caja[1]) + 2 * contorno > limite_alto:
            break
        elegido = (tamano, letra)
        tamano += 2
    if elegido is None:
        raise ValueError(
            f"el texto {texto!r} no cabe en un cuadro de {ancho}×{alto} ni con el cuerpo más pequeño. "
            "Acórtalo: la miniatura lleva un gancho, no una frase"
        )
    return elegido


def revisa_texto(texto: str) -> list[str]:
    """Lo que se puede saber del texto SIN la imagen. Lanza si no vale; devuelve las palabras.

    Está aparte porque se comprueba **dos veces y a propósito**: `pipeline.py` la llama antes de
    generar —70 s de GPU que no se tiran por una cadena que ya se sabe mala— y `compon_texto` la
    vuelve a llamar, porque es una función pública y nadie garantiza que quien la use haya pasado por
    la etapa. La regla vive en un solo sitio.
    """
    palabras = texto.split()
    if not palabras:
        raise ValueError("la miniatura necesita texto: sin él es una lámina más")
    if len(palabras) > PALABRAS_MAXIMAS:
        raise ValueError(
            f"el texto de la miniatura tiene {len(palabras)} palabras y el máximo del contrato del "
            f"canal es {PALABRAS_MAXIMAS}: la miniatura lleva un gancho, y el título ya va AL LADO. "
            f"(Que se lea es otra comprobación distinta y esa sí se mide: altura de mayúscula "
            f"≥ {ALTURA_MAYUSCULA_MINIMA_PX} px a 168.) Texto recibido: {texto!r}"
        )
    return palabras


def compon_texto(ruta_imagen: str | Path, texto: str, ruta_salida: str | Path | None = None, *, fuente: Path) -> dict:
    """Compone el texto con la fuente del canal (`fuente_declarada`), del mayor tamaño que quepa entero en el cuadro."""
    palabras = revisa_texto(texto)

    imagen = Image.open(ruta_imagen).convert("RGB")
    ancho, alto = imagen.size
    escala = alto / TAMANO_SUGERIDOS[1]
    mayusculas = texto.upper()

    tamano, letra = _mayor_cuerpo_que_cabe(mayusculas, ancho, alto, fuente)
    contorno_px = grosor_del_contorno(tamano)
    caja = letra.getbbox(mayusculas)
    ancho_texto, alto_texto = caja[2] - caja[0], caja[3] - caja[1]

    # Anclado ABAJO y centrado: el contrato pone el objeto como retrato, así que el texto va debajo.
    # Se calcula desde el borde inferior en vez de con un porcentaje fijo, que era lo que sacaba el
    # texto por debajo del cuadro cuando el cuerpo crecía.
    arriba = alto - int(alto * MARGEN_INFERIOR_DEL_TEXTO) - contorno_px - alto_texto
    izquierda = (ancho - ancho_texto) // 2
    x, y = izquierda - caja[0], arriba - caja[1]

    # El color no se elige a ojo: se mide el fondo bajo la caja y gana el de más contraste.
    region = np.asarray(imagen)[arriba : arriba + alto_texto, izquierda : izquierda + ancho_texto]
    fondo = tuple(float(v) for v in region.reshape(-1, 3).mean(axis=0)) if region.size else (128.0,) * 3
    blanco, negro = (255, 255, 255), (0, 0, 0)
    color = blanco if contraste(blanco, fondo) >= contraste(negro, fondo) else negro
    contorno = negro if color == blanco else blanco

    ImageDraw.Draw(imagen).text(
        (x, y),
        mayusculas,
        font=letra,
        fill=color,
        stroke_width=contorno_px,
        stroke_fill=contorno,
    )
    destino = Path(ruta_salida or ruta_imagen)
    imagen.save(destino)

    razon = contraste(color, fondo)
    cabe = (
        izquierda - contorno_px >= 0
        and izquierda + ancho_texto + contorno_px <= ancho
        and arriba - contorno_px >= 0
        and arriba + alto_texto + contorno_px <= alto
    )
    return {
        "texto": mayusculas,
        "palabras": len(palabras),
        "fuente": Path(fuente).name,
        "cuerpo_px": tamano,
        "altura_mayuscula_px": altura_mayuscula(letra),
        "altura_mayuscula_a_168": round(altura_mayuscula(letra) / escala, 1),
        "cumple_altura": altura_mayuscula(letra) / escala >= ALTURA_MAYUSCULA_MINIMA_PX,
        # Lo que la versión anterior no publicaba, y por eso el texto se salía sin que nadie lo viera.
        "ancho_del_texto_pct": round((ancho_texto + 2 * contorno_px) / ancho, 4),
        "caja_del_texto": [izquierda, arriba, ancho_texto, alto_texto],
        "cabe_en_el_cuadro": cabe,
        "color": "blanco" if color == blanco else "negro",
        "contraste_con_el_fondo": round(razon, 2),
        "cumple_contraste": razon >= CONTRASTE_MINIMO,
        "salida": str(destino),
    }


def comprueba(
    ruta_imagen: str | Path,
    texto: str = "",
    laminas: list[str | Path] | None = None,
    medido_texto: dict | None = None,
    desviacion_sin_texto: float | None = None,
) -> dict:
    """Comprueba la miniatura contra el contrato. Las láminas del run son la referencia.

    **`cumple: false` suspende el run**: quien llama marca la etapa `blocked` y lanza, igual que con
    las líneas rojas. No es un aviso — lo era, y con eso una miniatura sin texto se subía igual.
    """
    fallos: list[str] = []

    peso = Path(ruta_imagen).stat().st_size
    if peso > PESO_MAXIMO_BYTES:
        fallos.append(
            f"la miniatura pesa {peso / 1024 / 1024:.2f} MB y YouTube admite {PESO_MAXIMO_BYTES // 1024 // 1024} MB "
            "(thumbnails.set): la subida no la pondría"
        )
    if not texto:
        fallos.append("la miniatura no lleva texto, y el contrato del canal lo exige: sin él es una lámina más")
    elif medido_texto:
        if not medido_texto.get("cumple_altura"):
            fallos.append(
                f"el texto mide {medido_texto['altura_mayuscula_a_168']} px de mayúscula a 168 px y "
                f"hacen falta {ALTURA_MAYUSCULA_MINIMA_PX}: no se leería en la lista de sugeridos"
            )
        if not medido_texto.get("cumple_contraste"):
            fallos.append(
                f"el texto contrasta {medido_texto['contraste_con_el_fondo']}:1 con su fondo y el "
                f"mínimo es {CONTRASTE_MINIMO}:1 (WCAG para texto normal)"
            )
        if not medido_texto.get("cabe_en_el_cuadro", True):
            fallos.append(
                f"el texto NO cabe entero en el cuadro: ocupa el "
                f"{medido_texto.get('ancho_del_texto_pct', 0) * 100:.1f} % del ancho y su caja es "
                f"{medido_texto.get('caja_del_texto')}. Un texto cortado no se lee aunque sea grande"
            )

    # El encuadre y el acento se MIDEN pero no suspenden: ver el docstring del módulo. Su rango se
    # solapa con el de las láminas porque en este canal las láminas ya son retratos de objeto, y un
    # umbral ahí sería un gate falso.
    #
    # **Límite conocido, para cuando haya un segundo canal**: estas medidas se calculan siempre, tenga
    # el canal acento de color o no, y en un canal sin acento no significan nada — la mancha más
    # saturada de una imagen a color no es el objeto. Hoy no confunde a nadie porque el bloque lleva su
    # `_por_que` y el `recorte.por_que_no` va al lado diciendo que no se recortó; con un segundo canal
    # (decisión 12: hoy no lo hay) hay que omitirlas o marcarlas.
    imagen = Image.open(ruta_imagen).convert("RGB")
    ancho, alto = imagen.size
    (_, _, _, bh), ocupacion, encontrado = caja_del_objeto(ruta_imagen)
    ref_ocupacion = ref_alto = ref_acento = ref_desviacion = None
    if laminas:
        medidas = [(caja_del_objeto(p), Image.open(p).size[1]) for p in laminas]
        ref_ocupacion = float(np.median([m[0][1] for m in medidas]))
        ref_alto = float(np.median([m[0][0][3] / m[1] for m in medidas]))
        ref_acento = float(np.median([fraccion_de_acento(p) for p in laminas]))
        ref_desviacion = float(np.median([desviacion_a_168px(p) for p in laminas]))

    def _r(v, d=4):
        return round(v, d) if v is not None else None

    return {
        "cumple": not fallos,
        "fallos": fallos,
        "medido": {
            "tamano": [ancho, alto],
            "peso_bytes": peso,
            "texto": medido_texto or {"texto": texto or None},
        },
        "reportado_no_es_gate": {
            "_por_que": (
                "ni el encuadre ni el acento sirven de gate en este canal, y está medido: en alto del "
                "objeto, ocupación y acento la miniatura cae DENTRO del rango de sus propias láminas, "
                "así que un umbral aprobaría láminas y suspendería miniaturas buenas; y la desviación "
                "apunta al revés —sin el texto queda por DEBAJO de todas las láminas, porque el "
                "recorte quita detalle—, así que exigirle superarlas rechazaría la miniatura bien "
                "recortada. Se dan para comparar dos candidatas y para ver si el recorte hizo algo, "
                "nunca como aval. El porqué de cada una, en el docstring de lib/miniatura.py"
            ),
            "objeto_localizado_por_su_acento": encontrado,
            "alto_del_objeto": _r(bh / alto),
            "alto_del_objeto_en_las_laminas": _r(ref_alto),
            "el_objeto_ocupa": _r(ocupacion),
            "ocupacion_en_las_laminas": _r(ref_ocupacion),
            "acento_en_el_cuadro": _r(fraccion_de_acento(ruta_imagen)),
            "acento_en_las_laminas": _r(ref_acento),
            # Las dos desviaciones, porque miden cosas distintas: la de después incluye el texto, que
            # ya tiene su propio gate, así que sola no dice nada del encuadre.
            "desviacion_a_168px_sin_texto": _r(desviacion_sin_texto, 1),
            "desviacion_a_168px": _r(desviacion_a_168px(ruta_imagen), 1),
            "desviacion_en_las_laminas": _r(ref_desviacion, 1),
        },
        "umbrales_que_suspenden": {
            "altura_mayuscula_minima_a_168px": ALTURA_MAYUSCULA_MINIMA_PX,
            "contraste_minimo_texto": CONTRASTE_MINIMO,
            "palabras_maximas": PALABRAS_MAXIMAS,
            "peso_maximo_bytes": PESO_MAXIMO_BYTES,
            "_lineas_rojas": "las comprueba pipeline.py con lib/lineas_rojas.py, no este módulo",
        },
    }


def texto_de_slides(slides_json: dict) -> str:
    """El texto sale de `slides.json → thumbnail_text`. Deducirlo del título sería inventar el gancho."""
    return str(slides_json.get("thumbnail_text", "")).strip()


CLAVE_LAMINA = "thumbnail_lamina"
# El sidecar de procedencia de las imágenes. **No se vuelve a escribir el literal**: lo declara el
# adaptador que lo produce (`lib/comfy_client._RECORDS_FILENAME`, convención de todos los adaptadores)
# y lo publica el módulo que lo lee. Este módulo es un consumidor, y tenía su propia copia del nombre:
# tres definiciones del mismo fichero (auditoría del 10-09, BAJO).
REGISTRO_DE_IMAGENES = provenance.IMAGE_RECORDS_FILENAME


def lamina_declarada(slides_json: dict) -> int | None:
    """El número de lámina que el guion manda usar como miniatura, o `None` si no lo declara.

    **Desde el 12-09 `None` para el run.** La decisión: «hazlo obligatorio, la miniatura siempre de una
    lámina», después de que el episodio 2 repitiera el fallo del 1 (addendum fila 156). Esta función
    sigue siendo un LECTOR y no lanza por ausencia —así se puede consultar el campo sin montar la
    etapa—; quien convierte el `None` en parada es `pipeline.stage_thumbnail`.

    Nace de una decisión del 10-09, después de rechazar la miniatura generada del episodio 1
    («no es un ataúd, es una caja de hierro con un candado»): «No te compliques con la miniatura, coge
    una imagen de una de las láminas, conviértela en miniatura y ponle el título. Mucho más fácil y no
    tienes que generar nada, por ejemplo la lámina 1 podría servir de miniatura».

    **Y revierte a propósito lo que él mismo pidió el 28-08** («la has sacado del mismo vídeo subido… la
    idea de la miniatura es generar una imagen exclusiva»). Lo que cambió en medio está medido: generar
    una imagen aparte le da al modelo el objeto sin el contexto que lo hacía reconocible, y en este
    episodio salió un mueble. Una lámina del run **ya pasó por sus ojos** en el gate de láminas, así que
    es la única imagen del vídeo de la que se sabe que representa la pieza.

    Es del GUION y no del perfil (F4.9 no aplica: no es una decisión de canal sino de episodio) porque
    **qué lámina sirve de miniatura depende de lo que cuente ese vídeo**, igual que `thumbnail_text`.
    """
    valor = slides_json.get(CLAVE_LAMINA)
    # `valor in (None, "", False)` parecía lo mismo y no lo es: en Python `0 == False`, así que un
    # `thumbnail_lamina: 0` se colaba como «no declarado» y la etapa generaba una imagen en silencio
    # en vez de decir que las láminas empiezan en 1. Lo cazó `test_miniatura_desde_lamina`.
    if valor is None or valor is False or (isinstance(valor, str) and not valor.strip()):
        return None
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        raise ValueError(
            f"`slides.json → {CLAVE_LAMINA}` vale {valor!r} y tiene que ser el NÚMERO de la lámina que se "
            "usa como miniatura, por ejemplo 1. Es obligatorio desde el 12-09: la miniatura sale siempre "
            "de una lámina del run."
        ) from None
    if numero < 1:
        raise ValueError(f"`slides.json → {CLAVE_LAMINA}` vale {numero} y las láminas se numeran desde 1.")
    return numero


def desde_lamina(run_dir: str | Path, numero: int, destino: str | Path) -> dict:
    """Copia la lámina `numero` del run como miniatura y deja su procedencia derivada.

    No recorta ni compone nada: de eso siguen ocupándose `recorta_al_objeto` y `compon_texto`, que es lo
    que hace que una miniatura sacada de una lámina pase por el MISMO gate que una generada — el texto
    medido a 168 px, el contraste y las líneas rojas. Lo único que cambia es de dónde sale el píxel.

    La procedencia se escribe aquí y no en el pipeline a propósito (decisión cerrada 5): la entrada de
    `thumbnail.png` que dejó una generación anterior describe un fichero que ya no existe, así que se
    **sustituye** en vez de acumularse, y la nueva hereda modelo, pesos y licencia de la lámina de la que
    sale, con su `origen` diciendo de cuál. Es el mismo patrón con el que se registró la lámina de cierre
    del episodio 1, que también es una copia.
    """
    run = Path(run_dir)
    origen = run / "slides" / f"slide-{numero:02d}.png"
    if not origen.exists():
        disponibles = sorted(p.name for p in (run / "slides").glob("slide-*.png"))
        raise FileNotFoundError(
            f"`{CLAVE_LAMINA}` pide la lámina {numero} y no hay `{origen.name}` en {run / 'slides'}. "
            f"Láminas en el run: {', '.join(disponibles) or 'ninguna'}."
        )
    salida = Path(destino)
    Image.open(origen).convert("RGB").save(salida)

    registro_laminas = _lee_registro(run / "slides" / REGISTRO_DE_IMAGENES)
    de_la_lamina = next((e for e in registro_laminas if Path(str(e.get("file", ""))).name == origen.name), {})
    entrada = {
        k: v
        for k, v in de_la_lamina.items()
        if k in ("workflow", "modelo", "pesos", "licencia", "url", "prompt", "seed")
    }
    entrada["file"] = str(salida)
    entrada["origen"] = f"copia de slides/{origen.name} recortada y rotulada como miniatura (Pillow, sin generación)"
    # `fuente` la deriva `provenance._image_entry()` del workflow, así que sin esto una miniatura copiada
    # decía «generación local (ComfyUI)» y quien leyera solo ese campo entendería que se generó aparte
    # (recomendación del auditor, 10-09). No es falso —el píxel salió de ahí— pero se puede decir mejor.
    entrada["fuente"] = f"copia de una lámina del run (slides/{origen.name}), no una generación nueva"
    if not entrada.get("licencia"):
        entrada["licencia"] = "derivada de una lámina del run; ver su entrada en slides/" + REGISTRO_DE_IMAGENES

    _sustituye_en_el_registro(run, entrada)
    return {"lamina": numero, "origen": str(origen), "salida": str(salida), "procedencia": entrada}


CLAVE_SEGUNDO = "thumbnail_segundo"


def segundo_declarado(slides_json: dict) -> float | None:
    """El instante del vídeo del que sale la miniatura de un rehecho, en segundos, o `None` si no lo declara.

    **Solo lo usan los rehechos** (02-10, fila 246): su lámina es la del vídeo viejo, así que una miniatura
    sacada de ella sería la que ya se vio. Qué run es un rehecho lo decide `pipeline.stage_thumbnail`, no este lector.

    Vale un número (`420`, `421.5`) o el reloj con el que el usuario señala un momento del vídeo (`"7:00"`,
    `"1:02:03"`). Es un LECTOR, como `lamina_declarada`: no lanza por ausencia. Si el instante cae dentro del vídeo lo
    sabe la composición, no el guion, y lo comprueba `lib/escena/etapas.fotogramas_sin_karaoke`.
    """
    valor = slides_json.get(CLAVE_SEGUNDO)
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    error = ValueError(
        f"`slides.json → {CLAVE_SEGUNDO}` vale {valor!r} y tiene que ser el instante del vídeo del que sale la "
        'miniatura: un número de segundos (420) o un reloj ("7:00", "1:02:03").'
    )
    # `bool` es un `int` en Python: `True` pasaría por el segundo 1 sin que nadie lo hubiera escrito.
    if isinstance(valor, bool):
        raise error
    if isinstance(valor, int | float):
        segundos = float(valor)
    elif isinstance(valor, str):
        partes = valor.strip().split(":")
        try:
            numeros = [float(p) for p in partes]
        except ValueError:
            raise error from None
        if len(numeros) > 3 or any(n < 0 or n >= 60 for n in numeros[1:]):
            raise error
        segundos = sum(n * 60**k for k, n in enumerate(reversed(numeros)))
    else:
        raise error
    if not math.isfinite(segundos) or segundos < 0:
        raise error
    return segundos


def desde_fotograma(
    run_dir: str | Path,
    fotograma: str | Path,
    segundo: float,
    destino: str | Path,
    *,
    huella_composicion: str,
    herramientas: dict | None = None,
) -> dict:
    """Pone un fotograma de la escena del run como miniatura, a 1280×720, y deja su procedencia (fila 246).

    Hace lo mismo que `desde_lamina` y nada más: no recorta ni compone, así que la miniatura pasa por el mismo gate, y
    la entrada de `thumbnail.png` se sustituye. Lo que cambia es de dónde sale el píxel: no de una lámina, sino de la
    composición del run, que junta muchas imágenes. Por eso la entrada hereda los modelos y las licencias de todas
    ellas (`modelos_de_la_escena`), igual que la de una lámina hereda los de su lámina.

    **El modelo no puede ser «ninguno»**: `lib/publicacion.declaracion_de_ia` descarta esos registros, y la
    declaración de IA del vídeo callaría que la miniatura es IA (decisión 7; lo cazó la revisión de F7.0b). Un
    fotograma no se genera, pero lo que se ve en él sí. Que no es una generación nueva lo dicen `fuente` y `origen`.
    """
    origen = Path(fotograma)
    if not origen.is_file():
        raise FileNotFoundError(f"no está el fotograma del que sale la miniatura: {origen}")
    run = Path(run_dir)
    modelos, licencias = modelos_de_la_escena(run)
    imagen = Image.open(origen).convert("RGB")
    ancho, alto = imagen.size
    objetivo = TAMANO_DE_FOTOGRAMA[0] / TAMANO_DE_FOTOGRAMA[1]
    if abs(ancho / alto - objetivo) > 0.01:
        raise ValueError(
            f"el fotograma mide {ancho}×{alto} y la miniatura es 16:9: reducirlo a "
            f"{TAMANO_DE_FOTOGRAMA[0]}×{TAMANO_DE_FOTOGRAMA[1]} lo deformaría"
        )
    salida = Path(destino)
    imagen.resize(TAMANO_DE_FOTOGRAMA, Image.Resampling.LANCZOS).save(salida)
    entrada = {
        "file": str(salida),
        "modelo": "los de las imágenes de la escena: " + "; ".join(modelos),
        # Sin licencia registrada se dice «desconocida», que es lo que el conteo de assets.json lista como pendiente.
        "licencia": (
            "derivada de las imágenes de la escena: " + "; ".join(licencias)
            if licencias
            else "desconocida: las imágenes de la escena no registran su licencia"
        ),
        "fuente": f"fotograma de la escena del run (segundo {segundo:g}), no una generación nueva",
        "origen": (
            f"fotograma de la composición renderizada en el segundo {segundo:g}, capturado sin la capa del karaoke "
            f"(HyperFrames snapshot), reducido a {TAMANO_DE_FOTOGRAMA[0]}×{TAMANO_DE_FOTOGRAMA[1]} y rotulado como "
            "miniatura (Pillow, sin generación)"
        ),
        "segundo": segundo,
        "huella_composicion": huella_composicion,
    }
    if herramientas:
        entrada["herramientas"] = dict(herramientas)
    _sustituye_en_el_registro(run, entrada)
    return {"segundo": segundo, "origen": str(origen), "salida": str(salida), "procedencia": entrada}


# Lo que no generó ningún modelo empieza así en `assets.json`, y la declaración de IA lo salta con este mismo criterio
# (`lib/publicacion._modelos_por_tipo`).
_SIN_MODELO = ("ninguno", "no aplica")


def modelos_de_la_escena(run_dir: str | Path) -> tuple[list[str], list[str]]:
    """Los modelos generativos y las licencias de las imágenes de la escena del run, leídos de su `assets.json`.

    Son las de `activos/`: la composición saca de ahí todas sus imágenes, y las láminas de `slides/` son el guion
    gráfico, que no sale en el vídeo. Se dejan fuera las que no generó ningún modelo (la geometría, el banner partido).
    **Sin ningún modelo, para**: una miniatura de escena sin modelo registrado dejaría la declaración de IA corta.
    """
    from lib import config

    run = Path(run_dir)
    carpeta = config.activos_del_run(run).relative_to(run).as_posix() + "/"
    modelos: list[str] = []
    licencias: list[str] = []
    for a in provenance.read_ledger(run).get("assets", []):
        modelo = str(a.get("modelo") or "").strip()
        if a.get("tipo") != "imagen" or not str(a.get("id", "")).startswith(carpeta):
            continue
        if not modelo or modelo.lower().startswith(_SIN_MODELO):
            continue
        if modelo not in modelos:
            modelos.append(modelo)
        licencia = str(a.get("licencia") or "").strip()
        if licencia and licencia not in licencias:
            licencias.append(licencia)
    if not modelos:
        raise ValueError(
            f"el assets.json de {run} no registra ningún modelo para las imágenes de la escena ({carpeta}), así que la "
            "miniatura no puede decir con qué se generó lo que se ve y la declaración de IA saldría corta. "
            "La procedencia se escribe en las etapas activos, escena y render: vuelve a lanzarlas."
        )
    return modelos, licencias


def apunta_la_marca(run_dir: str | Path, miniatura: str | Path, marca: dict) -> None:
    """Añade el registro de la marca de IA (OC1.5) a la entrada de la miniatura en el registro de imágenes del run.

    De ahí lo lee `provenance` y lo deja en `assets.json → detalle.marca_ia`, sin que la procedencia tenga que saber
    nada de la marca. La entrada la escribió `desde_lamina` o `desde_fotograma`, así que una miniatura nueva llega sin
    la marca de la anterior. Video Seal toca sus píxeles, así que su licencia y su url se suman a las de la entrada
    (decisión 5), como las herramientas del obrero; el modelo sigue siendo el que dibujó la imagen.
    """
    run = Path(run_dir)
    nombre = Path(miniatura).name
    previas = _lee_registro(run / REGISTRO_DE_IMAGENES)
    entrada = next((e for e in previas if Path(str(e.get("file", ""))).name == nombre), None)
    if entrada is None:
        raise ValueError(f"la miniatura {nombre} no tiene entrada en {REGISTRO_DE_IMAGENES}: vuelve a lanzar la etapa")
    modelos = list((marca.get("modelos") or {}).values())
    licencia = str(entrada.get("licencia") or "desconocida")
    if modelos:
        licencia += " · marca de agua: " + ", ".join(f"{m.get('nombre')} ({m.get('licencia')})" for m in modelos)
    urls = [u for u in str(entrada.get("url") or "").split(" · ") if u]
    # Sin repetir: los tres ficheros de TrustMark comparten su fuente (revisión de OC1.12, hallazgo 2).
    urls = list(dict.fromkeys(urls + [m["fuente"] for m in modelos if m.get("fuente")]))
    _sustituye_en_el_registro(
        run, {**entrada, "licencia": licencia, "url": " · ".join(urls) or None, "marca_ia": dict(marca)}
    )


def _sustituye_en_el_registro(run: Path, entrada: dict) -> None:
    """Escribe la entrada de la miniatura en el registro del run, en lugar de la que hubiera para el mismo fichero."""
    ruta_registro = run / REGISTRO_DE_IMAGENES
    nombre = Path(entrada["file"]).name
    previas = [e for e in _lee_registro(ruta_registro) if Path(str(e.get("file", ""))).name != nombre]
    ruta_registro.write_text(json.dumps(previas + [entrada], indent=2, ensure_ascii=False), encoding="utf-8")


def _lee_registro(ruta: Path) -> list[dict]:
    if not ruta.exists():
        return []
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [e for e in datos if isinstance(e, dict)] if isinstance(datos, list) else []


def clausulas_del_canal(perfil: dict) -> list[str]:
    """Las cláusulas de acabado de la miniatura, del perfil del canal. Sin perfil, ninguna."""
    imagen = perfil.get("imagen") or {}
    return [str(c) for c in (imagen.get("miniatura_clausulas") or [])]


def informe(datos: dict, destino: str | Path) -> Path:
    """Guarda lo medido al lado de la miniatura, para que ningún informe teclee estas cifras."""
    p = Path(destino)
    p.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return p
