"""La identidad visual del canal: banner, avatar y marca de agua, y la frontera de lo automatizable.

Es **capa de ESTUDIO** (`doc/06-arquitectura-estudio-canales.md`): aquí viven los tamaños, las
comprobaciones, el alfa y el checklist, que no cambian al cambiar de nicho. Lo que define una
identidad —las escenas, el acabado, la descripción, las palabras clave— vive en
`canales/<id>/perfil.json → marca`, y este módulo **no tiene ni un texto de canal dentro**: la fuga de
capa es lo que la auditoría cazó dos veces (F3.4 con el idioma, F3.6 con las cláusulas de miniatura).

## La frontera de lo automatizable está MEDIDA, no supuesta

Medido el 30-08 contra el documento de descubrimiento de la API y contra el token real del `.env`
(addendum de `doc/02` fila 36). La tabla es la razón de que este módulo haga unas cosas y guíe otras:

| Acción | ¿Existe en la API? | ¿Con nuestro scope `youtube.upload`? |
|---|---|---|
| `watermarks.set` | sí | **SÍ** |
| `channelBanners.insert` (sube los bytes, devuelve una URL) | sí | **SÍ** |
| `channels.update` (aplicar el banner, la descripción, las palabras clave) | sí | **NO** |
| Avatar / imagen de perfil | **NO EXISTE** | — |
| Pronombres, información de contacto | **NO existen** en `ChannelBrandingSettings` | — |

Dos consecuencias que conviene tener claras antes de leer el código:

1. **El banner NO se puede poner por API entero.** `channelBanners.insert` sube los bytes y devuelve
   una URL, pero aplicarla exige `channels.update`, que el scope no cubre. O sea que la mitad
   automatizable no termina el trabajo: el camino real del banner es Studio. La función existe igual
   —es lo que el scope sí permite y lo que promete `doc/05-bucles.md`— y **devuelve lo que queda a
   mano**, que es el mismo patrón que ya usa `lib/youtube_client.py` con el `.srt`.
2. **Ampliar el scope no es decisión de un agente.** Se aplazó a después del MVP, coherente con
   el rechazo del `force-ssl` del 28-08. No se propone aquí.

## Y la subida real no la lanza el pipeline

`watermarks.set` y `channelBanners.insert` son **irreversibles a la vista del público**: no hay
borrador privado de un banner. Por eso este módulo los deja escritos y a un comando, y ese comando lo
ejecuta el usuario con `--confirmo`, igual que el gate 2. La bandera no es burocracia: es lo que impide que
un agente toque el canal público por reflejo.

## Qué se genera, y por qué a esos tamaños

- **Banner 2048×1152**, generado a **1280×720** y reescalado ×1,6. No se genera a 2048 directo por el
  invariante de 8 GB de VRAM (la generación es en serie y 2048×1152 son 2,36 Mpx frente a los 0,92 de
  1280×720, que es el tamaño que la etapa de miniatura ya ejercita en producción). **El texto se
  compone DESPUÉS del reescalado**, a resolución nativa, así que lo que se lee no pasa por el
  interpolador.
- **Avatar**: se genera a **1024×1024** y se entregan **800×800** y **150×150**. Se pidió 150; se
  genera grande porque **una imagen grande siempre se puede reducir y al revés no**, y el avatar se
  muestra a varios tamaños a la vez (la lista de vídeos lo pinta a ~98 px y la cabecera del canal
  mucho más grande). El 800 es además lo que YouTube recomienda subir.
- **Marca de agua 150×150 con alfa real**, derivada del MISMO dibujo del avatar cuando el perfil no
  declara escena propia: la marca de agua **es el logo**, y dos emblemas distintos en un canal son un
  error de identidad, no una variación.

## El área segura del banner, que es lo que más se equivoca

YouTube recorta el banner **muy agresivamente** y lo que se ve depende del dispositivo: en televisor
se ve entero, en escritorio una franja y en móvil solo el centro. Lo único garantizado en todos es el
área central. La especificación de YouTube la da sobre el lienzo recomendado de 2560×1440, donde el
área segura de texto y logo es de **1546×423** centrada; a nuestro lienzo de 2048×1152 le corresponde
la misma escala (2048/2560 = 0,8), o sea **1237×338**. Todo lo legible se compone ahí dentro y los
bordes son sangrado.

De ahí sale la medida de legibilidad: el área segura se pinta en un móvil a unos 360 px de ancho, o
sea a **0,291** de nuestro lienzo, y sobre esa reducción se exige la misma altura de mayúscula que ya
derivó F3.6 para la miniatura (`ALTURA_MAYUSCULA_MINIMA_PX`). No es un umbral nuevo: es el mismo, en
la reducción que le toca a este asset.

## Qué suspende y qué solo se mide

**SUSPENDE** (`comprueba()['cumple']` en falso; los comandos de subida se niegan a correr):

- que falte cualquiera de los tres assets, o que su tamaño no sea el exigido;
- el **peso y el formato** contra los límites de la API — banner 6.291.456 B, marca de agua
  10.485.760 B, PNG o JPEG—, comprobados **antes** de subir nada;
- que la marca de agua **no tenga alfa por debajo de 255**, o sea que sea un PNG opaco disfrazado;
- el **texto del banner**: que quepa entero en el área segura, que llegue a la altura mínima de
  mayúscula en la reducción de móvil y que contraste ≥ 4,5:1 (WCAG) contra el fondo que de verdad
  tiene debajo;
- las **líneas rojas** del canal sobre los tres assets. La identidad del canal la ve quien no eligió
  nada —es más pública que un vídeo—, así que pasa la misma guarda que las láminas.

**SE MIDE Y SE PUBLICA, no suspende**: la ocupación del objeto en el avatar antes y después del
recorte, la altura de mayúscula del eslogan, el reparto del alfa de la marca de agua y los caracteres
de la descripción y las palabras clave contra sus límites. El motivo es el mismo que en F3.6: un
umbral cuyo rango se solapa con lo legítimo es un gate falso, y aquí además no hay corpus con el que
calibrarlo — hay un banner, no cuarenta láminas.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw

from lib import lineas_rojas
from lib.comfy_client import generate_images_batch, load_workflow
from lib.config import BASE_DIR, CANAL_ACTIVO, CANAL_MARCA_DIR, CANALES_DIR, MODELO_IMAGEN, YOUTUBE_API_KEY
from lib.miniatura import (
    ALTURA_MAYUSCULA_MINIMA_PX,
    CONTRASTE_MINIMO,
    altura_mayuscula,
    canal_tiene_acento,
    contraste,
    copia_la_fuente,
    fuente_declarada,
    grosor_del_contorno,
    recorta_al_objeto,
    tipografia,
)

# ── Tamaños, cada uno con su derivación (ver el docstring del módulo) ─────────────────────────
BANNER = (2048, 1152)
BANNER_GENERACION = (1280, 720)  # el tamaño que la etapa de miniatura ya ejercita en producción
# Área segura de texto y logo: 1546×423 sobre el lienzo de 2560×1440 de la especificación, a la
# escala 2048/2560 = 0,8 que le corresponde a nuestro lienzo. La cifra que YouTube publica para el
# mínimo de 2048×1152 es 1235×338, o sea que la derivación **concuerda con ella salvo 2 px de ancho**;
# se deja la derivada porque es la que se puede rehacer si algún día cambia el lienzo, y los 2 px no
# cambian nada: el texto se encaja al 92 % del ancho del área y su caja se publica medida.
AREA_SEGURA = (1237, 338)
# Ancho al que un móvil pinta esa área segura. 360 px es el viewport estrecho habitual, o sea el
# peor caso realista — el mismo criterio con el que F3.6 eligió los 168 px de la lista de sugeridos.
ANCHO_MOVIL_PX = 360
AVATAR = 800
AVATAR_PEQUENO = 150
AVATAR_GENERACION = 1024
MARCA_DE_AGUA = 150

# Cuánto del cuadro se busca que ocupe el objeto al recortar el avatar. Es el objetivo de una
# transformación, no un umbral de aprobación (misma distinción que `OBJETIVO_DEL_RECORTE` en F3.6):
# a 98 px de lado, un objeto que ocupe el 55 % del área abarca ~74 % del lado y se reconoce; uno al
# 20 % es una mancha. El modelo NO reencuadra por prompt —medido en F3.6—, así que esto lo hace el
# recorte, que además se lleva los garabatos de las esquinas.
OBJETIVO_DEL_AVATAR = 0.55

# ── Límites de la API, leídos del documento de descubrimiento el 30-08 ────────────────────────
LIMITE_BYTES_BANNER = 6_291_456
LIMITE_BYTES_MARCA_DE_AGUA = 10_485_760
FORMATOS_ACEPTADOS = ("PNG", "JPEG")
# Límites de los textos del canal. **No están medidos contra la API**: son los que YouTube documenta
# para la descripción del canal y las palabras clave, y no se pueden comprobar desde aquí porque
# `channels.update` está fuera del scope. Se miden nuestras cadenas contra ellos, que es lo que sí
# está en nuestra mano, y el checklist dice de dónde sale cada número.
LIMITE_DESCRIPCION = 1000
LIMITE_PALABRAS_CLAVE = 500

# ── Reparto del área segura entre las dos líneas del banner ───────────────────────────────────
# El nombre manda: es lo que tiene que leerse en un móvil. El eslogan es segunda línea y se mide,
# pero no suspende (ver el docstring). Las tres fracciones suman 0,83 y dejan aire arriba y abajo.
ALTO_DEL_NOMBRE = 0.55
ALTO_DEL_ESLOGAN = 0.22
HUECO_ENTRE_LINEAS = 0.06
ANCHO_MAXIMO_DEL_TEXTO = 0.92  # del área segura, para que no quede pegado a su borde
# Escalones de la banda de contraste. Se prueba sin banda primero: una banda que no hace falta
# ensucia el dibujo. Cada escalón se MIDE después de componerlo, no se estima.
BANDAS_DE_CONTRASTE = (0.0, 0.45, 0.65, 0.85)

# ── Puntos de entrada de la API ───────────────────────────────────────────────────────────────
# El host es el de SUBIDA, no el de API — la misma trampa que costó un `400 mediaBodyRequired` en la
# miniatura de F3.3 y que está documentada en lib/youtube_client.py.
WATERMARK_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/watermarks/set"
BANNER_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/channelBanners/insert"
CHANNELS_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"

INFORME = "marca.json"
# La fuente del nombre y del eslogan del banner la declara el canal (OC1.4), de la biblioteca del estudio, igual que la
# de la miniatura (`lib/miniatura.py → fuente_declarada`). Su copia, con su registro, queda en esta carpeta de la marca.
CLAVE_FUENTE_DEL_BANNER = "marca.banner.fuente"
CARPETA_DE_LA_FUENTE = "fuente-del-banner"
CLAUSULAS_DEL_ESTUDIO_BANNER = (
    "a wide banner plate: the pieces are spread across the full width",
    "the background is plain and uncluttered, especially across the centre of the image",
    "no frame, no border, no passepartout around the image",
    "no text, no letters, no numbers, no watermark, no signature anywhere",
)
CLAUSULAS_DEL_ESTUDIO_CUADRADO = (
    # El `prefijo_estilo` del workflow dice «wide 16:9 composition». Desde OC1.4 una lámina puede traer
    # el suyo (`generate_images_batch`), pero la marca usa el del workflow. Para los cuadrados se
    # contrarresta aquí, y el latente ya es
    # cuadrado de todas formas: lo que se corrige es el sesgo del texto, no la geometría.
    "square composition, ONE single object centred, filling most of the frame",
    "the background is completely plain and empty",
    "no frame, no border, no passepartout around the image",
    "no text, no letters, no numbers, no watermark, no signature anywhere",
)


class MarcaError(RuntimeError):
    """La identidad del canal no se puede generar o no cumple lo que se le exige."""


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Lo que el canal declara
# ══════════════════════════════════════════════════════════════════════════════════════════════


def fuente_del_banner(perfil: dict) -> Path:
    """La fuente del banner que declara el perfil (`marca.banner.fuente`). Para y dice qué escribir si no vale.

    Se pide ANTES de generar nada: sin ella el texto no se puede componer, y descubrirlo después de la GPU es tirarla.
    """
    try:
        return fuente_declarada(perfil, CLAVE_FUENTE_DEL_BANNER)
    except ValueError as error:
        raise MarcaError(str(error)) from None


def copia_fuente_del_banner(fuente: Path, destino: Path) -> dict:
    """La copia de la fuente en la carpeta de la marca, con su registro: así llega a su `assets.json` (decisión 5)."""
    return copia_la_fuente(fuente, destino / CARPETA_DE_LA_FUENTE, etapa="marca")


def directorio(canal: str = "") -> Path:
    """Dónde viven los assets de marca de un canal: `canales/<id>/marca/`, ignorado por git.

    Sin argumento devuelve el del canal activo, que es lo que `lib/config.py` ya resuelve. Con
    argumento sirve a otro canal del estudio sin cambiar `CANAL_ACTIVO`, que es lo que permitía
    la ruta anterior (`canales/<id>/marca`) y no se pierde en la reorganización del 30-08.
    """
    if not canal or canal == CANAL_ACTIVO:
        return CANAL_MARCA_DIR
    return CANALES_DIR / canal / "marca"


def registro_id(canal: str = "") -> str:
    """Identificador del registro de procedencia. No es un run de vídeo y el nombre lo dice."""
    return f"marca-{canal or CANAL_ACTIVO or 'sin-canal'}"


def textos_del_canal(perfil: dict) -> dict:
    """Los textos que el usuario pega en Studio, con su medida contra el límite documentado.

    Salen del perfil y de ningún otro sitio: `nombre` y `publicacion.eslogan` ya existían —el eslogan
    estaba escrito y **no lo usaba nadie**— y la descripción y las palabras clave se añadieron en el
    bloque `marca`. Inventarlos aquí sería meter la identidad de un canal en la capa de estudio.
    """
    marca = perfil.get("marca") or {}
    publicacion = perfil.get("publicacion") or {}
    palabras = [str(k).strip() for k in (marca.get("palabras_clave") or []) if str(k).strip()]
    descripcion = str(marca.get("descripcion") or "")
    return {
        "nombre": str(perfil.get("nombre") or ""),
        "eslogan": str(publicacion.get("eslogan") or ""),
        "handle": str(publicacion.get("handle") or ""),
        "canal_youtube": str(publicacion.get("canal_youtube") or ""),
        "canal_id": str(publicacion.get("canal_id") or ""),
        "descripcion": descripcion,
        "descripcion_caracteres": len(descripcion),
        "descripcion_limite": LIMITE_DESCRIPCION,
        "descripcion_cabe": len(descripcion) <= LIMITE_DESCRIPCION,
        "palabras_clave": palabras,
        # YouTube entrecomilla las palabras clave que llevan espacio y las separa por espacios: esa
        # cadena es la que cuenta contra el límite, no la suma de las palabras sueltas.
        "palabras_clave_como_las_cuenta_youtube": _palabras_clave_en_una_linea(palabras),
        "palabras_clave_caracteres": len(_palabras_clave_en_una_linea(palabras)),
        "palabras_clave_limite": LIMITE_PALABRAS_CLAVE,
        "palabras_clave_caben": len(_palabras_clave_en_una_linea(palabras)) <= LIMITE_PALABRAS_CLAVE,
    }


def _palabras_clave_en_una_linea(palabras: list[str]) -> str:
    return " ".join(f'"{p}"' if " " in p else p for p in palabras)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Dónde va cada archivo, y por qué hay dos carpetas
# ══════════════════════════════════════════════════════════════════════════════════════════════
# Se pidió el 30-08, al abrir `canales/<id>/marca/` y encontrarse **cuatro avatares** sin saber
# cuál subir: la base que salió del modelo, el recorte intermedio, el de 800 y el de 150. La regla
# queda en una línea: **lo que está en `subir-al-canal/` se sube; lo demás, no.**
#
# **La segunda carpeta NO es un `WORK_DIR`, y ese fue mi error de diseño en la primera versión.**
# La llamé `trabajo/` y la metí en la lista de intermedios de `lib/provenance.py` junto a `montaje/`
# y `musica/`. La auditoría midió el precio: dentro hay **dos cosas de clases distintas**.
#
#   - `avatar-recortado.png` **sí** es material de trabajo: una transformación local que se rehace en
#     milisegundos desde la base.
#   - `banner-base.png` y `avatar-base.png` **NO**: son **la salida del modelo**, y eran el único sitio
#     del repo donde vivían el prompt, la semilla y la lista de pesos. Al declararlos intermedios, el
#     registro versionado pasó de 7 entradas a 4 y **nadie podía volver a generar el banner del canal**.
#     La defensa de licencia sobrevivía —los entregables declaran modelo y licencia—, pero la
#     reproducibilidad que promete el docstring de `lib/provenance.py` no.
#
# Por eso se llama `material/` y **lleva procedencia como cualquier entregable**: son imágenes que
# costaron GPU y que permiten rehacer el canal sin volver a gastarla. En los vídeos el equivalente es
# `slides/`, que tampoco es un `WORK_DIR` por el mismo motivo.
SUBIR = "subir-al-canal"
TRABAJO = "material"

# El avatar entregable se llama `avatar.png` **sin sufijo, a propósito**: en la carpeta de subir no hay
# con qué confundirlo, y el nombre sin adorno es el que se usa. El de 150 conserva el suyo porque es la
# alternativa, no el bueno.
BANNER_FINAL = f"{SUBIR}/banner.png"
AVATAR_FINAL = f"{SUBIR}/avatar.png"
AVATAR_150_FINAL = f"{SUBIR}/avatar-150.png"
MARCA_DE_AGUA_FINAL = f"{SUBIR}/marca-de-agua.png"

BANNER_BASE = f"{TRABAJO}/banner-base.png"
AVATAR_BASE = f"{TRABAJO}/avatar-base.png"
AVATAR_RECORTADO = f"{TRABAJO}/avatar-recortado.png"
MARCA_DE_AGUA_BASE = f"{TRABAJO}/marca-de-agua-base.png"


def prompt_de_marca(escena: str, clausulas_del_canal: list[str] | None, cuadrado: bool) -> str:
    """Convierte una escena del perfil en el prompt del asset de marca.

    Mismo reparto que `lib/miniatura.prompt_de_miniatura`, y por el mismo motivo: del **estudio** es
    el encuadre y el «sin texto, sin marco»; del **canal**, el acabado. El acabado de fondo —la tinta,
    el pergamino— no se pide aquí: lo pone el `prefijo_estilo` del workflow.
    """
    base = escena.strip().rstrip(".")
    if not base:
        raise MarcaError(
            "el perfil del canal no declara la escena de este asset (perfil.json → marca.<asset>.escena). "
            "Sin ella no hay nada que generar, y describirla aquí sería meter la identidad del canal en "
            "la capa de estudio."
        )
    estudio = CLAUSULAS_DEL_ESTUDIO_CUADRADO if cuadrado else CLAUSULAS_DEL_ESTUDIO_BANNER
    partes = [
        base,
        *estudio[:2],
        *[c.strip().rstrip(".") for c in (clausulas_del_canal or []) if c.strip()],
        *estudio[2:],
    ]
    return ". ".join(partes) + "."


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Generación
# ══════════════════════════════════════════════════════════════════════════════════════════════


def _licencia_del_modelo() -> tuple[str, str]:
    """Modelo y licencia reales del workflow activo, para la procedencia de los derivados."""
    try:
        workflow = load_workflow(MODELO_IMAGEN)
    except Exception:  # noqa: BLE001 — sin workflow legible la procedencia lo dice, no revienta
        return ("desconocido", "desconocida")
    modelo = workflow.get("modelo") or {}
    return (str(modelo.get("nombre") or MODELO_IMAGEN), str(modelo.get("licencia") or "desconocida"))


def registra_derivado(destino: Path, archivo: Path, de: Path, como: str) -> None:
    """Anota en `generacion-imagenes.json` un asset DERIVADO de otro ya generado.

    Los derivados —el banner reescalado con su texto, el avatar a 800 y a 150, la marca de agua con
    alfa— no los escribe ComfyUI, así que sin esto quedarían como archivos sin procedencia y el conteo
    cruzado de `lib/provenance.py` los cantaría (decisión cerrada 5). Se escribe en el MISMO archivo
    que usa el adaptador de imagen y con su misma forma, así que `provenance.sync` los normaliza sin
    saber que existen.
    """
    modelo, licencia = _licencia_del_modelo()
    ruta = destino / "generacion-imagenes.json"
    registros = []
    if ruta.exists():
        try:
            registros = json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            registros = []
    with Image.open(archivo) as im:
        resolucion = f"{im.size[0]}x{im.size[1]}"
    registros.append(
        {
            "file": str(archivo),
            "fuente": "derivado en local de una imagen generada por ComfyUI (Pillow, sin red)",
            "modelo": f"{modelo} + derivación local",
            "licencia": licencia,
            "origen": f"derivado de {de.name} por lib/canal_marca.py: {como}",
            "resolucion": resolucion,
            "derivado_de": de.name,
            "metadatos_png": "limpiados en el original; el derivado no añade ninguno",
        }
    )
    ruta.write_text(json.dumps(registros, indent=2, ensure_ascii=False), encoding="utf-8")


def genera_bases(perfil: dict, destino: Path, seed: int | None = None) -> dict:
    """Genera las láminas base con el adaptador local, EN SERIE y en una sola sesión de ComfyUI.

    Devuelve `{asset: ruta}`. Reutiliza `generate_images_batch`, que arranca el servidor una vez, salta
    lo que ya existe y deja la procedencia junto a las imágenes; el invariante de 8 GB (nada en
    paralelo en GPU) lo valida el propio adaptador al cargar el workflow.
    """
    marca = perfil.get("marca") or {}
    # Las dos subcarpetas las crea ESTO, no el operador. En la primera versión existían solo porque
    # yo había movido los ficheros a mano: un `git clone` + `--generar` reventaba con
    # `FileNotFoundError`, y el segundo canal también. `marca/` está en `.gitignore`, así que el clon
    # nunca las trae.
    for sub in ("", SUBIR, TRABAJO):
        (destino / sub).mkdir(parents=True, exist_ok=True)
    lote = [
        {
            "prompt": prompt_de_marca(
                str((marca.get("banner") or {}).get("escena") or ""),
                (marca.get("banner") or {}).get("clausulas"),
                cuadrado=False,
            ),
            "filename": BANNER_BASE,
            "width": BANNER_GENERACION[0],
            "height": BANNER_GENERACION[1],
        },
        {
            "prompt": prompt_de_marca(
                str((marca.get("avatar") or {}).get("escena") or ""),
                (marca.get("avatar") or {}).get("clausulas"),
                cuadrado=True,
            ),
            "filename": AVATAR_BASE,
            "width": AVATAR_GENERACION,
            "height": AVATAR_GENERACION,
        },
    ]
    # La marca de agua solo se genera aparte si el canal declara SU PROPIA escena. Sin ella deriva del
    # avatar, que es lo correcto: la marca de agua es el logo, no un segundo emblema.
    escena_agua = str((marca.get("marca_de_agua") or {}).get("escena") or "").strip()
    if escena_agua:
        lote.append(
            {
                "prompt": prompt_de_marca(
                    escena_agua, (marca.get("marca_de_agua") or {}).get("clausulas"), cuadrado=True
                ),
                "filename": MARCA_DE_AGUA_BASE,
                "width": AVATAR_GENERACION,
                "height": AVATAR_GENERACION,
            }
        )
    if seed is not None:
        for item in lote:
            item["seed"] = int(seed)

    generate_images_batch(lote, str(destino))
    return {
        "banner": destino / BANNER_BASE,
        "avatar": destino / AVATAR_BASE,
        # Sin escena propia, la marca de agua parte del MISMO dibujo del avatar: es el logo del canal.
        "marca_de_agua": destino / (MARCA_DE_AGUA_BASE if escena_agua else AVATAR_BASE),
        "_generadas": [str(destino / item["filename"]) for item in lote],
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════
# El banner: reescalado y texto en el área segura
# ══════════════════════════════════════════════════════════════════════════════════════════════


def area_segura(ancho: int, alto: int) -> tuple[int, int, int, int]:
    """La caja central garantizada en todos los dispositivos: (x, y, ancho, alto)."""
    sw, sh = AREA_SEGURA
    return ((ancho - sw) // 2, (alto - sh) // 2, sw, sh)


def mayor_cuerpo_que_cabe(texto: str, ancho_max: int, alto_max: int, fuente: Path):
    """El cuerpo más grande cuyo texto cabe, contorno incluido, en una caja de píxeles ABSOLUTOS.

    Crece desde abajo y se para en el primero que no cabe, así que el elegido **siempre cabe**: es la
    misma regla que `lib/miniatura._mayor_cuerpo_que_cabe`, que nació de que la versión anterior
    certificaba como legible un texto que se salía del cuadro.

    Está separada de aquella **a propósito y no por descuido**: allí los límites son fracciones fijas
    del cuadro (0,86 de ancho y 0,20 de alto, porque en una miniatura el objeto es el retrato y el
    texto va debajo); aquí el límite es una caja concreta —el área segura— porque en un banner **el
    texto ES el sujeto**. Compartir la función obligaría a parametrizar las dos semánticas en una, y lo
    que de verdad se comparte —cómo se abre la fuente, el grosor del contorno, la altura de
    mayúscula— sí se importa de allí en vez de repetirse.
    """
    elegido = None
    tamano = 8
    while tamano < alto_max * 4:
        letra = tipografia(fuente, tamano)
        caja = letra.getbbox(texto)
        contorno = grosor_del_contorno(tamano)
        if (caja[2] - caja[0]) + 2 * contorno > ancho_max:
            break
        if (caja[3] - caja[1]) + 2 * contorno > alto_max:
            break
        elegido = (tamano, letra)
        tamano += 2
    if elegido is None:
        raise MarcaError(
            f"el texto {texto!r} no cabe en el área segura del banner ({ancho_max}×{alto_max} px) ni con "
            "el cuerpo más pequeño. Acórtalo en el perfil del canal: lo que no cabe en el centro no se "
            "ve en un móvil."
        )
    return elegido


def _media_del_fondo(imagen: Image.Image, caja: tuple[int, int, int, int]) -> tuple[float, float, float]:
    x, y, ancho, alto = caja
    region = np.asarray(imagen.convert("RGB"))[y : y + alto, x : x + ancho]
    if region.size == 0:
        return (128.0, 128.0, 128.0)
    return tuple(float(v) for v in region.reshape(-1, 3).mean(axis=0))


def _con_banda(imagen: Image.Image, caja: tuple[int, int, int, int], alfa: float) -> Image.Image:
    """Devuelve una copia con una banda oscura sobre `caja`, a la opacidad pedida."""
    if alfa <= 0:
        return imagen.copy()
    base = imagen.convert("RGBA")
    banda = Image.new("RGBA", base.size, (0, 0, 0, 0))
    x, y, ancho, alto = caja
    ImageDraw.Draw(banda).rectangle([x, y, x + ancho, y + alto], fill=(0, 0, 0, int(round(255 * alfa))))
    return Image.alpha_composite(base, banda).convert("RGB")


def compon_texto_del_banner(
    ruta: str | Path, nombre: str, eslogan: str = "", ruta_salida=None, *, fuente: Path
) -> dict:
    """Compone el nombre del canal (y opcionalmente el eslogan) dentro del área segura, y lo mide.

    `fuente` es la que declara el canal (`fuente_del_banner`), de la biblioteca del estudio.

    El texto se compone con tipografía real y no se le pide al modelo, por lo que F3.6 dejó medido: el
    modelo escribe garabatos que imitan letras. Y componerlo aquí es lo que hace **comprobable** la
    legibilidad, en vez de estimarla.
    """
    imagen = Image.open(ruta).convert("RGB")
    ancho, alto = imagen.size
    sx, sy, sw, sh = area_segura(ancho, alto)
    escala_movil = ANCHO_MOVIL_PX / sw

    nombre = nombre.strip().upper()
    if not nombre:
        raise MarcaError("el banner necesita el nombre del canal, y sale de perfil.json → nombre")
    eslogan = eslogan.strip()

    ancho_max = int(sw * ANCHO_MAXIMO_DEL_TEXTO)
    alto_nombre = int(sh * (ALTO_DEL_NOMBRE if eslogan else ALTO_DEL_NOMBRE + ALTO_DEL_ESLOGAN))
    cuerpo_nombre, fuente_nombre = mayor_cuerpo_que_cabe(nombre, ancho_max, alto_nombre, fuente)
    lineas = [{"texto": nombre, "cuerpo": cuerpo_nombre, "fuente": fuente_nombre, "papel": "nombre"}]
    if eslogan:
        cuerpo_eslogan, fuente_eslogan = mayor_cuerpo_que_cabe(eslogan, ancho_max, int(sh * ALTO_DEL_ESLOGAN), fuente)
        lineas.append({"texto": eslogan, "cuerpo": cuerpo_eslogan, "fuente": fuente_eslogan, "papel": "eslogan"})

    # Cajas: la pila se centra verticalmente en el área segura y cada línea se centra a lo ancho.
    hueco = int(sh * HUECO_ENTRE_LINEAS) if eslogan else 0
    for linea in lineas:
        caja = linea["fuente"].getbbox(linea["texto"])
        linea["ancho"] = caja[2] - caja[0]
        linea["alto"] = caja[3] - caja[1]
        linea["bbox"] = caja
        linea["contorno"] = grosor_del_contorno(linea["cuerpo"])
    total = sum(linea["alto"] for linea in lineas) + hueco * (len(lineas) - 1)
    cursor = sy + (sh - total) // 2
    for linea in lineas:
        linea["x"] = sx + (sw - linea["ancho"]) // 2
        linea["y"] = cursor
        cursor += linea["alto"] + hueco

    # La banda de contraste se decide MIDIENDO, escalón a escalón: primero sin banda, y solo se sube si
    # el fondo real no da los 4,5:1. Una banda que no hace falta ensucia el dibujo.
    margen = max(linea["contorno"] for linea in lineas) * 2
    caja_banda = (
        0,
        max(0, lineas[0]["y"] - margen),
        ancho,
        min(alto, lineas[-1]["y"] + lineas[-1]["alto"] + margen) - max(0, lineas[0]["y"] - margen),
    )
    blanco, negro = (255, 255, 255), (0, 0, 0)
    compuesta = imagen
    alfa_banda = 0.0
    for alfa in BANDAS_DE_CONTRASTE:
        compuesta = _con_banda(imagen, caja_banda, alfa)
        alfa_banda = alfa
        peor = None
        for linea in lineas:
            fondo = _media_del_fondo(compuesta, (linea["x"], linea["y"], linea["ancho"], linea["alto"]))
            color = blanco if contraste(blanco, fondo) >= contraste(negro, fondo) else negro
            linea["fondo"] = fondo
            linea["color"] = color
            linea["contraste"] = contraste(color, fondo)
            peor = linea["contraste"] if peor is None else min(peor, linea["contraste"])
        if peor is not None and peor >= CONTRASTE_MINIMO:
            break

    dibujo = ImageDraw.Draw(compuesta)
    for linea in lineas:
        contorno_color = negro if linea["color"] == blanco else blanco
        dibujo.text(
            (linea["x"] - linea["bbox"][0], linea["y"] - linea["bbox"][1]),
            linea["texto"],
            font=linea["fuente"],
            fill=linea["color"],
            stroke_width=linea["contorno"],
            stroke_fill=contorno_color,
        )
    salida = Path(ruta_salida or ruta)
    compuesta.save(salida)

    medido = []
    for linea in lineas:
        cap = altura_mayuscula(linea["fuente"])
        cabe = (
            linea["x"] - linea["contorno"] >= sx
            and linea["x"] + linea["ancho"] + linea["contorno"] <= sx + sw
            and linea["y"] - linea["contorno"] >= sy
            and linea["y"] + linea["alto"] + linea["contorno"] <= sy + sh
        )
        medido.append(
            {
                "papel": linea["papel"],
                "texto": linea["texto"],
                "cuerpo_px": linea["cuerpo"],
                "altura_mayuscula_px": cap,
                "altura_mayuscula_en_movil": round(cap * escala_movil, 1),
                "cumple_altura": cap * escala_movil >= ALTURA_MAYUSCULA_MINIMA_PX,
                "caja": [linea["x"], linea["y"], linea["ancho"], linea["alto"]],
                "cabe_en_el_area_segura": cabe,
                "color": "blanco" if linea["color"] == blanco else "negro",
                "contraste_con_el_fondo": round(linea["contraste"], 2),
                "cumple_contraste": linea["contraste"] >= CONTRASTE_MINIMO,
            }
        )
    return {
        "salida": str(salida),
        "fuente": Path(fuente).name,
        "area_segura": [sx, sy, sw, sh],
        "escala_a_movil": round(escala_movil, 4),
        "ancho_de_movil_px": ANCHO_MOVIL_PX,
        "banda_de_contraste": alfa_banda,
        "_banda_por_que": (
            "0 = no hizo falta. La banda oscura solo se aplica si el fondo real no daba el contraste "
            "mínimo, y el escalón elegido se midió sobre la imagen ya compuesta, no se estimó"
        ),
        "lineas": medido,
    }


def prepara_banner(base: Path, destino: Path, nombre: str, eslogan: str, *, fuente: Path) -> dict:
    """Reescala la lámina base a 2048×1152 y compone el texto encima, a resolución nativa, con la fuente del canal."""
    salida = destino / BANNER_FINAL
    with Image.open(base) as imagen:
        origen = imagen.size
        imagen.convert("RGB").resize(BANNER, Image.Resampling.LANCZOS).save(salida)
    registra_derivado(
        destino,
        salida,
        base,
        f"reescalado LANCZOS {origen[0]}x{origen[1]}→{BANNER[0]}x{BANNER[1]} y texto compuesto con {Path(fuente).name}",
    )
    medido = compon_texto_del_banner(salida, nombre, eslogan, fuente=fuente)
    medido["reescalado"] = {
        "de": list(origen),
        "a": list(BANNER),
        "factor": round(BANNER[0] / origen[0], 3),
        "_por_que": (
            "generar a 2048×1152 son 2,36 Mpx en una tarjeta de 8 GB donde la generación es en serie; "
            "1280×720 es el tamaño que la etapa de miniatura ya ejercita. El texto se compone DESPUÉS "
            "del reescalado, así que lo que se lee no pasa por el interpolador"
        ),
    }
    return medido


# ══════════════════════════════════════════════════════════════════════════════════════════════
# El avatar y la marca de agua
# ══════════════════════════════════════════════════════════════════════════════════════════════


def prepara_avatar(base: Path, destino: Path, perfil: dict) -> dict:
    """Recorta al objeto, y entrega 800×800 y 150×150."""
    recortado = destino / AVATAR_RECORTADO
    acento = canal_tiene_acento(perfil)
    recorte = recorta_al_objeto(base, recortado, aspecto=1.0, objetivo=OBJETIVO_DEL_AVATAR, hay_acento=acento)
    fuente = recortado if recorte["recortado"] else base

    salidas = {}
    for lado, nombre in ((AVATAR, AVATAR_FINAL), (AVATAR_PEQUENO, AVATAR_150_FINAL)):
        ruta = destino / nombre
        with Image.open(fuente) as imagen:
            imagen.convert("RGB").resize((lado, lado), Image.Resampling.LANCZOS).save(ruta)
        registra_derivado(destino, ruta, base, f"recorte al objeto (aspecto 1:1) y reducción LANCZOS a {lado}×{lado}")
        salidas[str(lado)] = str(ruta)
    if recorte["recortado"]:
        registra_derivado(destino, recortado, base, "recorte al objeto localizado por su acento de color (aspecto 1:1)")
    return {
        "recorte": recorte,
        "objetivo_del_recorte": OBJETIVO_DEL_AVATAR,
        "salidas": salidas,
        "_por_que_dos_tamanos": (
            "Se pidió 150. Se genera a 1024 y se entrega también 800 porque una imagen grande se "
            "puede reducir y al revés no, y el avatar se muestra a varios tamaños a la vez: ~98 px en "
            "la lista de vídeos y mucho más grande en la cabecera del canal. 800×800 es además lo que "
            "YouTube recomienda subir"
        ),
    }


def prepara_marca_de_agua(
    base: Path, destino: Path, opacidad: float, perfil: dict, recorte_previo: Path | None = None
) -> dict:
    """Marca de agua 150×150 con alfa REAL derivado de la tinta del dibujo.

    El alfa no es un valor plano: se saca de la luminancia, así que **el trazo queda visible y el
    pergamino desaparece**. Los dos extremos de la rampa son percentiles de la propia imagen y se
    publican, para que el resultado se pueda re-derivar en vez de creerse.

    `recorte_previo` es para el caso normal —la marca de agua deriva del avatar— y no es una
    optimización: reusar **el mismo recorte** es lo que garantiza que el logo del canal y su marca de
    agua sean el mismo encuadre del mismo dibujo. Volver a recortar daba un archivo idéntico byte a
    byte con otro nombre, o sea 1,3 MB y una duda («¿por qué hay dos recortes?») a cambio de nada.
    """
    salida = destino / MARCA_DE_AGUA_FINAL
    acento = canal_tiene_acento(perfil)
    if recorte_previo is not None and Path(recorte_previo).exists():
        fuente = Path(recorte_previo)
        recorte = {"recortado": True, "reutilizado_de": fuente.name}
    else:
        recortado = destino / "marca-de-agua-recortada.png"
        recorte = recorta_al_objeto(base, recortado, aspecto=1.0, objetivo=OBJETIVO_DEL_AVATAR, hay_acento=acento)
        fuente = recortado if recorte["recortado"] else base

    with Image.open(fuente) as imagen:
        pequena = imagen.convert("RGB").resize((MARCA_DE_AGUA, MARCA_DE_AGUA), Image.Resampling.LANCZOS)
    luz = np.asarray(pequena.convert("L"), dtype=np.float32)
    oscuro = float(np.percentile(luz, 2))  # la tinta más densa
    claro = float(np.percentile(luz, 70))  # el pergamino
    if claro - oscuro < 1.0:
        raise MarcaError(
            "la marca de agua no tiene contraste interno: el percentil 2 y el 70 de su luminancia "
            f"están a {claro - oscuro:.2f} niveles. Sin rango no hay de dónde sacar el alfa."
        )
    rampa = np.clip((claro - luz) / (claro - oscuro), 0.0, 1.0)
    alfa = (rampa * float(opacidad) * 255.0).round().astype(np.uint8)
    rgba = pequena.convert("RGBA")
    rgba.putalpha(Image.fromarray(alfa, mode="L"))
    rgba.save(salida)
    registra_derivado(
        destino,
        salida,
        base,
        f"recorte al objeto, reducción LANCZOS a {MARCA_DE_AGUA}×{MARCA_DE_AGUA} y canal alfa derivado de la "
        f"luminancia a opacidad {opacidad}",
    )
    if recorte["recortado"] and not recorte.get("reutilizado_de"):
        registra_derivado(destino, fuente, base, "recorte al objeto localizado por su acento de color (aspecto 1:1)")
    return {
        "salida": str(salida),
        "opacidad_pedida": float(opacidad),
        "rampa_de_alfa": {
            "percentil_2_de_luminancia": round(oscuro, 1),
            "percentil_70_de_luminancia": round(claro, 1),
            "_como": (
                "alfa = clip((p70 − luminancia) / (p70 − p2), 0, 1) × opacidad × 255: el pergamino cae a "
                "0 y la tinta sube a la opacidad pedida. Los percentiles son de ESTA imagen, así que la "
                "rampa se adapta a lo que el modelo haya devuelto"
            ),
        },
        "recorte": recorte,
        "alfa": alfa_medido(salida),
    }


def alfa_medido(ruta: str | Path) -> dict:
    """Mide el canal alfa. Es el criterio de aceptación de la marca de agua: no se supone, se mide."""
    with Image.open(ruta) as imagen:
        modo = imagen.mode
        if "A" not in imagen.getbands():
            return {
                "modo": modo,
                "tiene_canal_alfa": False,
                "semitransparente": False,
                "_por_que": "sin canal alfa la marca de agua tapa el vídeo: es un PNG opaco",
            }
        canal = np.asarray(imagen.getchannel("A"), dtype=np.uint8)
        rgba = imagen.convert("RGBA")
    return {
        "modo": modo,
        "tiene_canal_alfa": True,
        "alfa_maximo": int(canal.max()),
        "alfa_minimo": int(canal.min()),
        "alfa_medio": round(float(canal.mean()), 1),
        "opaco_pct": round(float((canal == 255).mean()) * 100, 2),
        "transparente_pct": round(float((canal == 0).mean()) * 100, 2),
        # El criterio, y por qué es este: un PNG con canal alfa puede estar entero a 255, o sea ser
        # opaco con disfraz. Lo que demuestra la semitransparencia es que el MÁXIMO quede por debajo.
        "semitransparente": bool(canal.max() < 255),
        # Y esto es la prueba de que el alfa hace su trabajo sobre un vídeo real: se compone sobre tres
        # fondos planos y se mide la luminancia media. Si tapara, las tres medias serían iguales entre
        # sí; si fuera invisible, cada una sería su fondo. Que se separen en las dos direcciones es lo
        # que significa «semitransparente» en la práctica, y no hay que creérselo: está en el informe.
        "luminancia_compuesta": {
            str(fondo): round(float(np.asarray(_compuesta(rgba, fondo), dtype=np.float32).mean()), 1)
            for fondo in (0, 128, 255)
        },
    }


def _compuesta(rgba: Image.Image, fondo: int) -> Image.Image:
    base = Image.new("RGBA", rgba.size, (fondo, fondo, fondo, 255))
    return Image.alpha_composite(base, rgba).convert("L")


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Comprobación: tamaños, pesos, alfa, texto y líneas rojas
# ══════════════════════════════════════════════════════════════════════════════════════════════


def _mide_archivo(ruta: Path, exigido: tuple[int, int], limite_bytes: int | None, base: Path | None = None) -> dict:
    """Mide un asset. `ruta` se publica RELATIVA a `base`, no como nombre suelto.

    Con `ruta.name` a secas se perdía la subcarpeta, y desde que los entregables viven en
    `subir-al-canal/` eso hacía que `comprueba()` reconstruyera `destino / "banner.png"` —una ruta que
    ya no existe— y que la guarda de líneas rojas fallara cerrada sobre un archivo que sí estaba.
    """
    etiqueta = ruta.relative_to(base).as_posix() if base else ruta.name
    if not ruta.exists():
        return {"ruta": etiqueta, "existe": False, "tamano_exigido": list(exigido)}
    with Image.open(ruta) as imagen:
        tamano = list(imagen.size)
        formato = imagen.format or ""
    bytes_ = ruta.stat().st_size
    medida = {
        "ruta": etiqueta,
        "existe": True,
        "tamano": tamano,
        "tamano_exigido": list(exigido),
        "tamano_correcto": tamano == list(exigido),
        "bytes": bytes_,
        "formato": formato,
        "formato_aceptado": formato.upper() in FORMATOS_ACEPTADOS,
    }
    if limite_bytes is not None:
        medida["limite_bytes"] = limite_bytes
        medida["dentro_del_limite"] = bytes_ <= limite_bytes
        medida["margen_bytes"] = limite_bytes - bytes_
    return medida


def comprueba(destino: Path, perfil: dict, medido_previo: dict | None = None) -> dict:
    """Comprueba los tres assets contra lo que el estudio exige. `cumple: false` bloquea la subida."""
    fallos: list[str] = []
    banner = _mide_archivo(destino / BANNER_FINAL, BANNER, LIMITE_BYTES_BANNER, destino)
    avatar_800 = _mide_archivo(destino / AVATAR_FINAL, (AVATAR, AVATAR), None, destino)
    avatar_150 = _mide_archivo(destino / AVATAR_150_FINAL, (AVATAR_PEQUENO, AVATAR_PEQUENO), None, destino)
    agua = _mide_archivo(
        destino / MARCA_DE_AGUA_FINAL, (MARCA_DE_AGUA, MARCA_DE_AGUA), LIMITE_BYTES_MARCA_DE_AGUA, destino
    )
    if agua["existe"]:
        agua["alfa"] = alfa_medido(destino / MARCA_DE_AGUA_FINAL)

    assets = {"banner": banner, "avatar_800": avatar_800, "avatar_150": avatar_150, "marca_de_agua": agua}
    for clave, medida in assets.items():
        if not medida["existe"]:
            fallos.append(
                f"falta {clave}: no existe {_relativa(destino / medida['ruta'])}. Lánzalo con `canal.py --generar`"
            )
            continue
        if not medida["tamano_correcto"]:
            fallos.append(f"{clave} mide {medida['tamano']} px y se exige {medida['tamano_exigido']}")
        if not medida["formato_aceptado"]:
            fallos.append(f"{clave} está en {medida['formato']!r} y la API acepta {list(FORMATOS_ACEPTADOS)}")
        if medida.get("dentro_del_limite") is False:
            fallos.append(f"{clave} pesa {medida['bytes']} B y el límite de la API es {medida['limite_bytes']} B")
    if agua["existe"] and not agua["alfa"]["semitransparente"]:
        fallos.append(
            "la marca de agua NO es semitransparente: su alfa máximo es "
            f"{agua['alfa'].get('alfa_maximo')} y tiene que quedar por debajo de 255. Opaca tapa el vídeo"
        )

    # El texto del banner: se lee de lo medido al componerlo, que es cuando se conoce el fondo real.
    texto = (medido_previo or {}).get("banner", {}) if medido_previo else {}
    if texto:
        for linea in texto.get("lineas", []):
            if linea["papel"] != "nombre":
                continue  # el eslogan se mide y se publica, no suspende (ver el docstring)
            if not linea["cabe_en_el_area_segura"]:
                fallos.append(
                    f"el nombre del canal NO cabe en el área segura del banner: su caja es {linea['caja']} "
                    f"y el área segura {texto.get('area_segura')}. Fuera de ahí, un móvil no lo enseña"
                )
            if not linea["cumple_altura"]:
                fallos.append(
                    f"el nombre del canal mide {linea['altura_mayuscula_en_movil']} px de mayúscula en un "
                    f"móvil y hacen falta {ALTURA_MAYUSCULA_MINIMA_PX}"
                )
            if not linea["cumple_contraste"]:
                fallos.append(
                    f"el nombre del canal contrasta {linea['contraste_con_el_fondo']}:1 con su fondo y el "
                    f"mínimo es {CONTRASTE_MINIMO}:1 (WCAG)"
                )
    elif banner["existe"]:
        fallos.append(
            "no hay medida del texto del banner: vuelve a lanzar `canal.py --generar`, que es quien la "
            "produce al componerlo (marca.json → banner.lineas)"
        )

    presentes = [destino / m["ruta"] for m in assets.values() if m["existe"]]
    # Sin ningún asset en disco no hay nada que revisar, y la guarda **no** se da por pasada en
    # silencio: el veredicto ya suspende por «falta <asset>», que es el fallo de verdad.
    rojas = (
        # El perfil llega por argumento, así que el guardián sale de ÉL y no del canal activo
        # global: es la costura por la que un proceso que mire dos canales juzgaría los assets de
        # uno con los umbrales del otro (F4.8, criterio de aceptación 7).
        lineas_rojas.revisa_lote(presentes, lineas_rojas.guardianes_del_canal(perfil))
        if presentes
        else {"pasa": True, "revisadas": 0, "fallos": [], "detalle": []}
    )
    if not rojas["pasa"]:
        for f in rojas["fallos"]:
            fallos.append(f"{f['archivo']} cruza la línea roja del canal [{f['motivo']}]")

    textos = textos_del_canal(perfil)
    avisos = []
    if not textos["descripcion_cabe"]:
        avisos.append(
            f"la descripción del canal tiene {textos['descripcion_caracteres']} caracteres y el límite "
            f"documentado son {LIMITE_DESCRIPCION}"
        )
    if not textos["palabras_clave_caben"]:
        avisos.append(
            f"las palabras clave suman {textos['palabras_clave_caracteres']} caracteres y el límite "
            f"documentado son {LIMITE_PALABRAS_CLAVE}"
        )

    return {
        "cumple": not fallos,
        "fallos": fallos,
        "avisos_de_texto": avisos,
        "_avisos_por_que": (
            "avisan y no suspenden porque su límite NO está medido contra la API: `channels.update` está "
            "fuera del scope, así que nadie puede comprobarlo desde aquí. Lo que sí se mide es nuestra "
            "cadena; el límite es el que YouTube documenta"
        ),
        "assets": assets,
        "lineas_rojas": {
            "pasa": rojas["pasa"],
            "revisadas": rojas["revisadas"],
            "fallos": rojas["fallos"],
            # El detalle por archivo va al informe y no solo el veredicto: «pasa: true» no dice si pasó
            # con 1 píxel o con 249, y el margen es justo lo que hay que mirar cuando se cambia el
            # acento de color de un canal (la tabla de tonos de contrato-prompt-imagen.md).
            "detalle": rojas.get("detalle", []),
            "umbrales": {
                "celda_16px": rojas.get("umbral_celda"),
                "ventana_48px": rojas.get("umbral_grueso"),
                "total": rojas.get("umbral_total"),
            },
            "_por_que": (
                "la identidad del canal la ve quien no eligió nada, así que pasa la misma guarda que las "
                "láminas. OJO con el umbral por total: está calibrado sobre láminas de 1344×768, así que "
                "sobre un banner de 2048×1152 es proporcionalmente MÁS estricto — falla cerrada, que es "
                "la dirección correcta"
            ),
        },
        "limites_de_la_api": {
            "banner_bytes": LIMITE_BYTES_BANNER,
            "marca_de_agua_bytes": LIMITE_BYTES_MARCA_DE_AGUA,
            "formatos": list(FORMATOS_ACEPTADOS),
            "_de_donde": "documento de descubrimiento de la Data API v3, leído el 30-08",
        },
        "textos_del_canal": textos,
    }


def informe(datos: dict, destino: Path) -> Path:
    """Deja lo medido junto a los assets, para que ningún informe teclee estas cifras a mano."""
    ruta = Path(destino) / INFORME
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return ruta


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Lo que sí se puede hacer contra la API — y lo lanza el usuario
# ══════════════════════════════════════════════════════════════════════════════════════════════


def estado_publico_del_canal(canal_id: str, ledger=None) -> dict:
    """Lee del canal lo que la API deja ver con la CLAVE PÚBLICA. Cuesta 1 unidad de cuota.

    Sirve para que el checklist distinga lo hecho de lo pendiente **también en la parte del usuario**: el
    banner aplicado y la descripción se ven desde fuera aunque `channels.update` no esté en el scope.
    Va por el ledger de cuota como cualquier llamada a la Data API (decisión cerrada 8) y **no
    reintenta**: lo prohíbe la lista negra.
    """
    if not YOUTUBE_API_KEY:
        return {"leido": False, "motivo": "no hay YOUTUBE_API_KEY en el .env"}
    if not canal_id:
        return {"leido": False, "motivo": "el perfil no declara publicacion.canal_id"}
    params = {"part": "snippet,brandingSettings", "id": canal_id, "key": YOUTUBE_API_KEY}
    try:
        resp = requests.get(CHANNELS_ENDPOINT, params=params, timeout=30)
    except requests.exceptions.RequestException as e:
        if ledger is not None:
            ledger.record_call("channels.list", f"id={canal_id}", None, error=str(e)[:200])
        return {"leido": False, "motivo": f"la llamada falló: {str(e)[:200]}"}
    if ledger is not None:
        ledger.record_call("channels.list", f"id={canal_id}", resp.status_code)
    if resp.status_code != 200:
        return {"leido": False, "motivo": f"channels.list respondió {resp.status_code}", "http": resp.status_code}
    items = resp.json().get("items", [])
    if not items:
        return {"leido": False, "motivo": f"channels.list no devuelve el canal {canal_id}"}
    snippet = items[0].get("snippet") or {}
    branding = (items[0].get("brandingSettings") or {}).get("channel") or {}
    imagen = (items[0].get("brandingSettings") or {}).get("image") or {}
    return {
        "leido": True,
        "titulo": snippet.get("title"),
        "descripcion_caracteres": len((snippet.get("description") or "")),
        "tiene_descripcion": bool((snippet.get("description") or "").strip()),
        "banner_puesto": bool(imagen.get("bannerExternalUrl")),
        "palabras_clave_visibles": branding.get("keywords"),
        "_palabras_clave_por_que": (
            "con clave pública YouTube suele NO devolver las keywords —son del propietario—, así que un "
            "null aquí no significa que no estén puestas: significa que desde fuera no se ven"
        ),
        "avatar_url": ((snippet.get("thumbnails") or {}).get("high") or {}).get("url"),
        "_avatar_por_que": (
            "el avatar NO existe en la API como acción, y su URL la devuelve YouTube tanto si es propio "
            "como si es el genérico: sirve para mirarlo, no para dar por hecho que está puesto"
        ),
    }


def _token():
    from lib.youtube_client import get_access_token

    return get_access_token()


def sube_marca_de_agua(ruta: str | Path, canal_id: str) -> dict:
    """`watermarks.set`: pone la marca de agua en el canal. **Irreversible a la vista del público.**

    Entra en el scope `youtube.upload` (medido el 30-08). Se envía como `multipart/related` porque la
    referencia describe el método con un recurso `InvideoBranding` **y** el medio; el recurso va vacío
    a propósito, para que YouTube aplique sus valores por defecto (marca visible durante todo el vídeo)
    en vez de que este código decida un `timing` que nadie ha pedido.

    **Escrita y NO ejercitada**: la primera ejecución es del usuario, porque esto se ve en el canal en
    cuanto responde 200 y no hay borrador privado de una marca de agua. Sin reintento automático.
    """
    archivo = Path(ruta)
    if not archivo.exists():
        raise MarcaError(f"no existe la marca de agua que se quiere subir: {archivo}")
    if not canal_id:
        raise MarcaError("no hay canal_id: sale de perfil.json → publicacion.canal_id")
    cuerpo, content_type = _multipart_relacionado({}, archivo, "image/png")
    resp = requests.post(
        f"{WATERMARK_ENDPOINT}?channelId={canal_id}&uploadType=multipart",
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": content_type},
        data=cuerpo,
        timeout=120,
    )
    return {
        "http": resp.status_code,
        "ok": resp.status_code in (200, 204),
        "respuesta": resp.text[:500],
        "archivo": str(archivo),
        "que_hace_falta_si_falla": (
            "no se reintenta automáticamente (lista negra). Si responde 403, comprueba que el token del "
            ".env es del canal correcto; si responde 400, la alternativa documentada es ponerla a mano en "
            "Studio → Personalización → Imagen de marca"
        ),
    }


def sube_banner(ruta: str | Path) -> dict:
    """`channelBanners.insert`: sube los BYTES del banner y devuelve una URL. **No lo aplica.**

    Y esa es la parte importante: aplicar la URL exige `brandingSettings.image.bannerExternalUrl` por
    `channels.update`, que **no** entra en nuestro scope (medido el 30-08). O sea que esta llamada sola
    no pone el banner en el canal. Existe porque es la mitad que el scope sí cubre, y devuelve lo que
    queda a mano — el mismo patrón que `lib/youtube_client.upload_video` usa con el `.srt`.
    """
    archivo = Path(ruta)
    if not archivo.exists():
        raise MarcaError(f"no existe el banner que se quiere subir: {archivo}")
    resp = requests.post(
        f"{BANNER_ENDPOINT}?uploadType=media",
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "image/png"},
        data=archivo.read_bytes(),
        timeout=300,
    )
    url = ""
    if resp.status_code == 200:
        # `channelBanners.insert` devuelve `{"kind": ..., "url": ...}`. Se saca defendido: si la
        # respuesta no fuera JSON, quedarse sin la URL no puede tapar el hecho de que los bytes
        # subieron —el `resp.text` va en el resultado— ni reventar en la cara de quien lo lanzó.
        try:
            url = str((resp.json() or {}).get("url") or "")
        except ValueError:
            url = ""
    return {
        "http": resp.status_code,
        "ok": resp.status_code == 200,
        "url_del_banner": url,
        "respuesta": resp.text[:500],
        "pendiente_a_mano": [
            {
                "que": "aplicar el banner al canal",
                "por_que": (
                    "exige channels.update (brandingSettings.image.bannerExternalUrl) y nuestro scope es "
                    "youtube.upload: medido el 30-08 contra el token real"
                ),
                "como": "Studio → Personalización → Imagen de marca → Banner, arrastrando el PNG",
            }
        ],
    }


def _multipart_relacionado(recurso: dict, archivo: Path, tipo_medio: str) -> tuple[bytes, str]:
    """Arma un cuerpo `multipart/related`: recurso JSON + medio, que es lo que pide la API de subida."""
    frontera = "lanternist-marca-de-canal"
    cuerpo = b"".join(
        [
            f"--{frontera}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
            json.dumps(recurso).encode("utf-8"),
            f"\r\n--{frontera}\r\nContent-Type: {tipo_medio}\r\n\r\n".encode(),
            archivo.read_bytes(),
            f"\r\n--{frontera}--\r\n".encode(),
        ]
    )
    return cuerpo, f"multipart/related; boundary={frontera}"


# ══════════════════════════════════════════════════════════════════════════════════════════════
# El checklist, que es la otra mitad de la feature
# ══════════════════════════════════════════════════════════════════════════════════════════════


def _studio(canal_id: str, cola: str) -> str:
    return f"https://studio.youtube.com/channel/{canal_id or 'UC'}{cola}"


def _relativa(ruta: Path) -> Path:
    """Ruta relativa al repositorio si está dentro. La absoluta ocupa media línea y no aporta nada."""
    try:
        return ruta.resolve().relative_to(BASE_DIR)
    except ValueError:
        return ruta


def _conteo_del_registro(ruta_base: Path) -> dict:
    """`assets.json → conteo`, o vacío si no hay registro. No lanza: esto alimenta un checklist."""
    try:
        return json.loads((ruta_base / "assets.json").read_text(encoding="utf-8")).get("conteo") or {}
    except (OSError, ValueError):
        return {}


def _conteo_cuadra(ruta_base: Path) -> bool:
    return bool(_conteo_del_registro(ruta_base).get("cuadra"))


def _detalle_del_conteo(ruta_base: Path) -> str:
    """Las dos cifras del conteo, que son las que dicen QUÉ ha pasado cuando no cuadra."""
    conteo = _conteo_del_registro(ruta_base)
    if not conteo:
        return f"{ruta_base / 'assets.json'} — todavía no existe"
    cuenta = f"{conteo.get('entradas', 0)} entrada(s) para {conteo.get('archivos_medios', 0)} archivo(s)"
    if conteo.get("cuadra"):
        return f"{ruta_base / 'assets.json'} · {cuenta} · copia versionada en canales/<id>/datos/assets/"
    sueltos = conteo.get("sin_registrar") or []
    return (
        f"NO CUADRA: {cuenta}"
        + (f" · sin procedencia: {', '.join(sueltos[:3])}" if sueltos else "")
        + ". Bórralos o decláralos: `require_complete()` bloquea la subida hasta que cuadre"
    )


def checklist(perfil: dict, veredicto: dict, estado: dict | None = None, destino: Path | None = None) -> dict:
    """Qué hace el código, qué hace el usuario, y **por qué cada cosa cae de un lado o del otro**.

    El porqué no es adorno: es lo único que evita que dentro de un mes alguien "automatice" la mitad
    manual sin darse cuenta de que ya se midió que no se puede. Cada punto del usuario lleva la acción que
    la API no cubre y el enlace a la pantalla donde se hace.

    Los enlaces de Studio llevan el `canal_id` del perfil. **No están comprobados desde aquí** —hacen
    falta ojos y sesión, y ninguna de las dos cosas tiene un agente—, así que cada uno va con la ruta
    de navegación al lado: si el enlace directo cambia, la ruta sigue valiendo.
    """
    textos = textos_del_canal(perfil)
    canal_id = textos["canal_id"]
    assets = veredicto.get("assets", {})
    ruta_base = _relativa(Path(destino or directorio()))

    def _hecho(clave: str) -> bool:
        medida = assets.get(clave) or {}
        return bool(medida.get("existe")) and bool(medida.get("tamano_correcto", False))

    codigo = [
        {
            "que": "generar el banner 2048×1152 con el contrato visual del canal",
            "estado": "hecho" if _hecho("banner") else "pendiente",
            "detalle": f"{ruta_base / BANNER_FINAL} · medido en marca.json → assets.banner",
            "archivos": [str(ruta_base / BANNER_FINAL)],
            "comando": r".venv\Scripts\python canal.py --generar",
        },
        {
            "que": "generar el avatar y entregarlo a 800×800 y a 150×150",
            "estado": "hecho" if _hecho("avatar_800") and _hecho("avatar_150") else "pendiente",
            "detalle": f"{ruta_base / AVATAR_FINAL} · {ruta_base / AVATAR_150_FINAL}",
            "archivos": [str(ruta_base / AVATAR_FINAL), str(ruta_base / AVATAR_150_FINAL)],
            "comando": r".venv\Scripts\python canal.py --generar",
        },
        {
            "que": "generar la marca de agua 150×150 con alfa real",
            "estado": "hecho" if _hecho("marca_de_agua") else "pendiente",
            "detalle": (
                f"{ruta_base / MARCA_DE_AGUA_FINAL} · alfa máximo "
                f"{((assets.get('marca_de_agua') or {}).get('alfa') or {}).get('alfa_maximo', '—')} "
                "(marca.json → assets.marca_de_agua.alfa)"
            ),
            "archivos": [str(ruta_base / MARCA_DE_AGUA_FINAL)],
            "comando": r".venv\Scripts\python canal.py --generar",
        },
        {
            "que": "comprobar tamaño, peso, formato, alfa, texto y líneas rojas ANTES de subir nada",
            "estado": "hecho" if veredicto.get("cumple") else "pendiente",
            "detalle": (
                "todo verde"
                if veredicto.get("cumple")
                else f"{len(veredicto.get('fallos', []))} fallo(s): " + " · ".join(veredicto.get("fallos", [])[:3])
            ),
            "comando": r".venv\Scripts\python canal.py --comprobar",
        },
        {
            "que": "registrar los assets en assets.json con su procedencia",
            # Lo que decide esto es `conteo.cuadra`, NO que el fichero exista. La primera versión
            # miraba `exists()` y daba «hecho» con el registro roto —comprobado: tres PNG sueltos en el
            # directorio lo descuadran y el checklist seguía en verde—. Es el defecto por el que F3.6
            # tuvo que reescribirse (addendum fila 30): enseñarle al operador que está todo bien cuando
            # no lo está. La guarda dura de `require_complete()` aguantaba, pero el checklist existe
            # precisamente para separar lo hecho de lo pendiente.
            "estado": "hecho" if _conteo_cuadra(ruta_base) else "pendiente",
            "detalle": _detalle_del_conteo(ruta_base),
            "comando": r".venv\Scripts\python canal.py --generar",
        },
        {
            "que": "poner la marca de agua en el canal (watermarks.set)",
            "estado": "lo lanza el usuario",
            "detalle": (
                "SÍ entra en el scope youtube.upload, pero es irreversible a la vista del público: no hay "
                "borrador privado de una marca de agua, así que el disparo es humano como el gate 2"
            ),
            "comando": r".venv\Scripts\python canal.py --subir-marca-de-agua --confirmo",
        },
        {
            "que": "subir los bytes del banner (channelBanners.insert) — NO lo aplica",
            "estado": "lo lanza el usuario",
            "detalle": (
                "sube el archivo y devuelve una URL, pero aplicarla exige channels.update, que NO está en "
                "el scope. Por eso el banner se pone en Studio; este comando solo existe porque es la "
                "mitad que el scope cubre"
            ),
            "comando": r".venv\Scripts\python canal.py --subir-banner --confirmo",
        },
    ]

    leido = (estado or {}).get("leido")
    del_usuario = [
        {
            "que": "poner el banner en el canal",
            "por_que_no_lo_hace_el_codigo": (
                "aplicar el banner es channels.update, y el scope youtube.upload no lo cubre (medido el "
                "30-08 contra el token real)"
            ),
            "estado": _estado_remoto(leido, (estado or {}).get("banner_puesto")),
            "donde": _studio(canal_id, "/editing/images"),
            "ruta": "Studio → Personalización → Imagen de marca → Banner",
            "que_subir": str(ruta_base / BANNER_FINAL),
            "archivos": [str(ruta_base / BANNER_FINAL)],
        },
        {
            "que": "poner el avatar (imagen de perfil)",
            "por_que_no_lo_hace_el_codigo": (
                "el avatar NO EXISTE en la API: no hay endpoint, no es cuestión de permisos. Ampliar el "
                "scope no lo resolvería"
            ),
            "estado": "no comprobable",
            "donde": _studio(canal_id, "/editing/images"),
            "ruta": "Studio → Personalización → Imagen de marca → Imagen",
            "que_subir": f"{ruta_base / AVATAR_FINAL} (el de 150 es el mismo dibujo, por si lo pide pequeño)",
            "archivos": [str(ruta_base / AVATAR_FINAL)],
        },
        {
            "que": "pegar la descripción del canal",
            "por_que_no_lo_hace_el_codigo": "es channels.update: fuera del scope",
            "estado": _estado_remoto(leido, (estado or {}).get("tiene_descripcion")),
            "donde": _studio(canal_id, "/editing/details"),
            "ruta": "Studio → Personalización → Información básica → Descripción",
            "que_pegar": (
                f"perfil.json → marca.descripcion ({textos['descripcion_caracteres']} caracteres de "
                f"{LIMITE_DESCRIPCION}); sale también en `canal.py --textos`"
            ),
        },
        {
            "que": "pegar las palabras clave del canal",
            "por_que_no_lo_hace_el_codigo": "es channels.update: fuera del scope",
            "estado": "no comprobable",
            "por_que_no_se_comprueba": "con clave pública YouTube no devuelve las keywords: son del propietario",
            "donde": _studio(canal_id, "/settings/channel/advanced"),
            "ruta": "Studio → Configuración → Canal → Información básica → Palabras clave",
            "que_pegar": (
                f"perfil.json → marca.palabras_clave ({textos['palabras_clave_caracteres']} caracteres de "
                f"{LIMITE_PALABRAS_CLAVE} contando las comillas)"
            ),
        },
        {
            "que": "rellenar pronombres e información de contacto, si los quiere",
            "por_que_no_lo_hace_el_codigo": (
                "no están en ChannelBrandingSettings: no existen en la API, como el avatar"
            ),
            "estado": "no comprobable",
            "donde": _studio(canal_id, "/editing/details"),
            "ruta": "Studio → Personalización → Información básica",
            "que_pegar": "decisión suya: el perfil no los declara porque no son identidad de producción",
        },
        {
            "que": "mirar el resultado en el canal, que es lo único que cierra esto",
            "por_que_no_lo_hace_el_codigo": (
                "el recorte del banner depende del dispositivo y no hay forma de verlo desde aquí: se comprueba "
                "con los ojos, como la miniatura"
            ),
            "estado": "de sus ojos",
            "donde": textos["canal_youtube"] or _studio(canal_id, ""),
            "ruta": "abrir el canal en el móvil y en el escritorio",
            "que_mirar": "que el nombre se lea entero en el móvil, donde solo se ve el área segura central",
        },
    ]
    return {
        "canal": perfil.get("id"),
        "cumple_lo_automatizable": bool(veredicto.get("cumple")),
        "codigo": codigo,
        "usuario": del_usuario,
        "estado_del_canal_leido": estado or {"leido": False, "motivo": "no se ha consultado (usa --contra-el-canal)"},
        "_frontera": (
            "Lo de arriba lo hace el código porque la API lo permite con el scope youtube.upload; lo de "
            "abajo NO, y cada punto dice cuál de los tres motivos es: channels.update fuera del scope, la "
            "acción no existe en la API, o hacen falta ojos humanos. Medido el 30-08"
        ),
    }


def _estado_remoto(leido, valor) -> str:
    """Lo que se sabe del canal REAL: hecho, pendiente, o nadie lo ha mirado."""
    if not leido:
        return "sin comprobar"
    return "hecho en el canal" if valor else "pendiente en el canal"


# Estados del checklist que AFIRMAN que el archivo ya está en disco. Los demás —`pendiente`,
# `sin comprobar`, `no comprobable`, `de sus ojos`— citan a propósito el sitio **donde irá**, que en un
# clon recién hecho todavía está vacío porque `canales/<id>/marca/` está en `.gitignore`.
_ESTADOS_CON_ARCHIVO = ("hecho", "lo lanza el usuario")


def rutas_que_no_existen(lista: dict) -> list[str]:
    r"""Archivos que el checklist da por PRESENTES y que no están en disco. Vacío = todo cuadra.

    **Existe porque el mismo fallo se coló tres veces**: al mover los assets a `subir-al-canal/`
    quedaron cadenas apuntando a los sitios viejos —primero en `que_subir`, luego en `detalle`— y el
    checklist mandaba al usuario a un archivo inexistente. Las tres veces lo comprobé con un `grep` del
    texto viejo y las tres se me escapó algo: una por buscar con `/` cuando la ruta lleva `\`, otra por
    un regex que capturaba las URI `file://` partidas por el `%20` de «En curso». Comprobar la
    **propiedad** no depende de acertar el patrón, y por eso esto es código.

    **Solo mira las filas cuyo estado afirma que el archivo existe** (`_ESTADOS_CON_ARCHIVO`), y esa
    acotación no es prudencia: la primera versión miraba todas y **rompía el caso más normal de todos**.
    Una fila `pendiente` cita el sitio donde el archivo *irá*, así que sobre un clon recién hecho
    —donde `marca/` no existe— el guardián declaraba fantasma el estado esperado, `canal.py` salía con
    1 y no llegaba ni a escribir la página. Lo cazó la auditoría, y de paso el otro falso positivo que
    traía: `detalle` puede listar los archivos **sin procedencia**, que vienen en rutas relativas al run
    y no al directorio de trabajo, así que se resolvían mal.
    """
    faltan: list[str] = []
    for grupo in ("codigo", "usuario"):
        for item in lista.get(grupo) or []:
            if not str(item.get("estado", "")).startswith(_ESTADOS_CON_ARCHIVO):
                continue
            for ruta in item.get("archivos") or []:
                if not Path(ruta).exists():
                    faltan.append(str(ruta))
    return sorted(set(faltan))


def texto_del_checklist(datos: dict) -> str:
    """El checklist como salida del programa, que es lo que se pidió: no un .md suelto."""
    lineas = [
        "=" * 92,
        f"CHECKLIST DE IDENTIDAD DEL CANAL · {datos.get('canal')}",
        "=" * 92,
        "",
        "LO QUE HACE EL CÓDIGO (la API lo permite con el scope youtube.upload)",
        "-" * 92,
    ]
    for item in datos["codigo"]:
        lineas.append(f"  [{item['estado']:^14}] {item['que']}")
        lineas.append(f"      {item['detalle']}")
        lineas.append(f"      $ {item['comando']}")
    lineas += ["", "LO QUE TIENE QUE HACER EL USUARIO (y por qué el código no puede)", "-" * 92]
    for item in datos["usuario"]:
        lineas.append(f"  [{item['estado']:^14}] {item['que']}")
        lineas.append(f"      por qué:  {item['por_que_no_lo_hace_el_codigo']}")
        if item.get("por_que_no_se_comprueba"):
            lineas.append(f"      sin ver:  {item['por_que_no_se_comprueba']}")
        lineas.append(f"      dónde:    {item['donde']}")
        lineas.append(f"      ruta:     {item['ruta']}")
        for clave in ("que_subir", "que_pegar", "que_mirar"):
            if item.get(clave):
                lineas.append(f"      {clave.replace('_', ' ')}: {item[clave]}")
    if not (datos.get("estado_del_canal_leido") or {}).get("leido"):
        lineas += [
            "",
            "  Los estados «sin comprobar» son los que SÍ se pueden mirar desde fuera (banner puesto,",
            "  descripción rellenada). Para verlos: `canal.py --checklist --contra-el-canal` — cuesta",
            "  1 unidad de cuota de la Data API v3 y se apunta en el ledger.",
        ]
    lineas += ["", "-" * 92, datos["_frontera"], "=" * 92]
    return "\n".join(lineas)


# La pagina del checklist. Nace de una petición del 30-08: «no son nada accesible… tenia que ser una tabla
# indicando el texto a copiar y pegar directamente y los enlaces a las imagenes. Es mucho mas facil
# que no buscar en un .json o lanzar un comando por la terminal».
#
# **Se queda EN LOCAL, y no es pereza**: la decision cerrada 6 dice que nada sale del PC salvo la
# subida a YouTube, y aqui van el banner y la descripcion del canal. Un `file://` cumple el encargo
# —doble clic y a copiar— sin publicar nada.
NOTA_BANNER = "2048×1152 · lo importante va en el centro: YouTube recorta los bordes según el dispositivo"
NOTA_AGUA = "150×150 · semitransparente: sobre blanco casi no se ve, y es lo correcto"

_CSS_CHECKLIST = """
  :root { --tinta:#1c1a17; --papel:#faf7f2; --borde:#d8d2c6; --acento:#8a5a2b;
          --ok:#2e6b3e; --pend:#a8461f; }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) { --tinta:#eae6df; --papel:#171614; --borde:#3a352d;
                                      --acento:#c89b6a; --ok:#7fc08f; --pend:#e8956e; }
  }
  :root[data-theme="dark"] { --tinta:#eae6df; --papel:#171614; --borde:#3a352d;
                             --acento:#c89b6a; --ok:#7fc08f; --pend:#e8956e; }
  body { background:var(--papel); color:var(--tinta); margin:0;
         font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif; }
  .caja { max-width:960px; margin:0 auto; padding:32px 20px 64px; }
  h1 { font-size:1.6rem; margin:0 0 4px; }
  h2 { font-size:1.15rem; margin:40px 0 8px; padding-bottom:6px; border-bottom:2px solid var(--borde); }
  h3 { font-size:1rem; margin:24px 0 4px; }
  .sub { color:var(--acento); margin:0 0 24px; }
  .donde { margin:2px 0 8px; font-size:.88rem; opacity:.8; }
  .cuenta { font-weight:400; font-size:.8rem; opacity:.6; }
  .copia { display:flex; gap:8px; align-items:flex-start; }
  textarea { flex:1; font:13px/1.5 ui-monospace,Consolas,monospace; padding:10px;
             border:1px solid var(--borde); border-radius:6px; resize:vertical;
             background:var(--papel); color:var(--tinta); }
  button { padding:9px 16px; border:1px solid var(--acento); border-radius:6px;
           background:var(--acento); color:var(--papel); cursor:pointer;
           font-size:.9rem; white-space:nowrap; }
  button:hover { opacity:.85; }
  figure { margin:16px 0; }
  figcaption { font-size:.85rem; opacity:.8; margin-top:6px; }
  table { border-collapse:collapse; width:100%; margin:8px 0 24px; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--borde);
           vertical-align:top; font-size:.92rem; }
  th { font-size:.78rem; text-transform:uppercase; letter-spacing:.04em; opacity:.65; }
  .ok { color:var(--ok); font-weight:600; }
  .pendiente { color:var(--pend); font-weight:600; }
  .lanza { color:var(--acento); font-weight:600; }
  .porque { font-size:.85rem; opacity:.75; }
  .nose { opacity:.6; }
  .aviso { border-left:3px solid var(--acento); padding:8px 14px; margin:20px 0;
           background:color-mix(in srgb, var(--acento) 8%, transparent); font-size:.9rem; }
  a { color:var(--acento); }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:20px; }
"""


def _marca_estado(estado: str) -> str:
    """Pinta el estado que YA decidió `checklist()`. No lo re-deriva: solo le pone color.

    Los literales son los del modelo (`hecho`, `pendiente`, `lo lanza el usuario`, `sin comprobar`,
    `no comprobable`, `de sus ojos`), y **cualquier otro se pinta en gris en vez de perderse**: si
    mañana `checklist()` añade uno, la página lo enseña igual aunque no sepa colorearlo.
    """
    clase = {"hecho": "ok", "pendiente": "pendiente", "lo lanza el usuario": "lanza"}.get(estado, "nose")
    return f'<span class="{clase}">{html.escape(estado)}</span>'


def _figura(destino: Path, nombre: str, titulo: str, nota: str) -> str:
    """Una imagen de la marca. Si el archivo no está, se dice — no se pinta un hueco roto."""
    ruta = destino / nombre
    if not ruta.exists():
        return (
            f"<figure><figcaption><b>{html.escape(titulo)}</b> · "
            f"<span class='nose'>todavía no generada</span> · "
            f"<code>canal.py --generar</code></figcaption></figure>"
        )
    uri = ruta.as_uri()
    return (
        f'<figure><img src="{uri}" alt="{html.escape(titulo)}" style="max-width:100%">'
        f"<figcaption><b>{html.escape(titulo)}</b> · {nota} "
        f'<a href="{uri}" download>descargar</a></figcaption></figure>'
    )


def _bloque_copiable(id_: str, titulo: str, texto: str, limite: int, donde: str, url: str) -> str:
    filas = max(3, texto.count("\n") + 3)
    return (
        f"<section><h3>{titulo} "
        f'<span class="cuenta">{len(texto)} / {limite} caracteres</span></h3>'
        f'<p class="donde">{html.escape(donde)} — '
        f'<a href="{url}" target="_blank">abrir en Studio</a></p>'
        f'<div class="copia"><textarea id="{id_}" readonly rows="{filas}">'
        f"{html.escape(texto)}</textarea>"
        f"<button onclick=\"copiar('{id_}', this)\">Copiar</button></div></section>"
    )


def _fila_de_codigo(item: dict) -> str:
    comando = item.get("comando", "")
    return (
        f"<tr><td>{html.escape(item['que'])}</td>"
        f"<td>{_marca_estado(item.get('estado', ''))}</td>"
        f"<td>{html.escape(item.get('detalle', ''))}"
        + (f"<br><code>{html.escape(comando)}</code>" if comando else "")
        + "</td></tr>"
    )


def _fila_del_usuario(item: dict) -> str:
    donde = item.get("donde", "")
    ruta = html.escape(item.get("ruta", ""))
    enlace = f'<a href="{donde}" target="_blank">{ruta or "abrir en Studio"}</a>' if donde else ruta
    extra = ""
    if item.get("que_subir"):
        extra += f"<br><b>sube:</b> {html.escape(item['que_subir'])}"
    if item.get("que_pegar"):
        extra += f"<br><b>pega:</b> {html.escape(item['que_pegar'])}"
    if item.get("sin_ver"):
        extra += f"<br><i>{html.escape(item['sin_ver'])}</i>"
    return (
        f"<tr><td>{html.escape(item['que'])}</td>"
        f"<td>{_marca_estado(item.get('estado', ''))}</td>"
        f"<td>{enlace}{extra}</td>"
        f"<td class='porque'>{html.escape(item.get('por_que_no_lo_hace_el_codigo', ''))}</td></tr>"
    )


def pagina_del_checklist(lista: dict, perfil: dict, destino: Path, datos: dict | None = None) -> Path:
    """El checklist como página HTML local, con el texto copiable y las imágenes a la vista.

    Nace de una petición del 30-08: «no son nada accesible… tenía que ser una tabla indicando el texto a copiar
    y pegar directamente y los enlaces a las imágenes».

    **Consume el modelo de `checklist()`, no lo reconstruye**, igual que `texto_del_checklist()`. La
    primera versión sí lo rehacía y la auditoría midió el precio: en un día, las dos copias ya se
    contradecían en tres puntos —la marca de agua pasaba de «la lanza el código» a «pégalo en Studio»,
    los estados cambiaban de nombre y se perdía `_frontera`—. Un checklist que se contradice consigo
    mismo es peor que no tenerlo.

    **La página no sale del PC**: la decisión cerrada 6 dice que nada lo hace salvo la subida a
    YouTube, y aquí van el banner y la descripción del canal. Se abre con doble clic.
    """
    marca = perfil.get("marca") or {}
    pub = perfil.get("publicacion") or {}
    # `or`, no un defecto de `get`: un canal que el usuario aún no ha creado lleva estas claves a `null`.
    studio = _studio(pub.get("canal_id") or "", "")
    estado_canal = (datos or {}).get("estado_del_canal") or {}
    claves = marca.get("palabras_clave") or []
    claves_txt = claves if isinstance(claves, str) else ", ".join(claves)

    leido = estado_canal.get("leido_el") or (
        "todavía no se ha leído el canal · <code>canal.py --checklist --contra-el-canal</code>"
    )
    filas_codigo = "".join(_fila_de_codigo(i) for i in lista.get("codigo", []))
    filas_del_usuario = "".join(_fila_del_usuario(i) for i in lista.get("usuario", []))

    pagina = f"""<title>Identidad del canal · {html.escape(perfil.get("nombre", ""))}</title>
<style>{_CSS_CHECKLIST}</style>
<div class="caja">
<h1>Identidad del canal</h1>
<p class="sub">{html.escape(perfil.get("nombre", ""))} · {html.escape(pub.get("handle") or "")}</p>

<div class="aviso">{html.escape(lista.get("_frontera", ""))}<br>
Estado del canal: {leido}.</div>

<h2>Lo que tienes que hacer tú</h2>
<table>
  <tr><th>Qué</th><th>Estado</th><th>Dónde</th><th>Por qué no lo hace el código</th></tr>
  {filas_del_usuario}
</table>

<h2>Textos, para copiar</h2>
{
        _bloque_copiable(
            "desc",
            "Descripción del canal",
            marca.get("descripcion", ""),
            1000,
            "Studio → Personalización → Información básica → Descripción",
            f"{studio}/editing/details",
        )
    }
{
        _bloque_copiable(
            "keys",
            "Palabras clave",
            claves_txt,
            500,
            "Studio → Configuración → Canal → Información básica → Palabras clave",
            f"{studio}/settings/channel/advanced",
        )
    }

<h2>Imágenes</h2>
{_figura(destino, BANNER_FINAL, "Banner", NOTA_BANNER)}
<div class="grid">
{_figura(destino, AVATAR_FINAL, "Avatar", "800×800 · <b>usa este</b>")}
{_figura(destino, AVATAR_150_FINAL, "Avatar pequeño", "150×150 · solo si Studio lo pide")}
{_figura(destino, MARCA_DE_AGUA_FINAL, "Marca de agua", NOTA_AGUA)}
</div>

<h2>Lo que hace el código</h2>
<table>
  <tr><th>Qué</th><th>Estado</th><th>Dónde queda</th></tr>
  {filas_codigo}
</table>
</div>
<script>
function copiar(id, boton) {{
  const t = document.getElementById(id);
  navigator.clipboard.writeText(t.value).then(() => {{
    const antes = boton.textContent;
    boton.textContent = "Copiado";
    setTimeout(() => {{ boton.textContent = antes; }}, 1400);
  }});
}}
</script>
"""
    # `mkdir` porque `canales/<id>/marca/` está en .gitignore: en un clon recién hecho NO existe, y la
    # primera versión reventaba con FileNotFoundError justo ahí. Las demás funciones del módulo lo
    # aguantaban; esta no. Lo cazó la auditoría reproduciendo el clon.
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / "identidad-del-canal.html"
    ruta.write_text(pagina, encoding="utf-8")
    return ruta
