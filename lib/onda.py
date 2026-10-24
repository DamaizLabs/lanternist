"""Onda de ecualizador sobre el fondo del vídeo (F4.11): cápsulas dibujadas, sin GPU y sin modelo.

Por qué existe
--------------
El formato llegó con una captura de un canal del nicho: **fondo animado + onda de
ecualizador + subtítulos karaoke**. El karaoke existe desde F2.12 y el fondo en bucle desde
F4.10; la onda no existía.

Cómo se dibuja, y por qué NO es un filtro de FFmpeg
---------------------------------------------------
**La forma se eligió el 04-09 mirando seis variantes**: cápsulas discretas de ancho
uniforme, puntas redondeadas, simétricas sobre un eje horizontal y de punta a punta del
fotograma («la forma es la perfecta e incluso las cápsulas un poco más anchas estaría bien»).
Ningún filtro de FFmpeg dibuja eso: `showfreqs` pinta columnas rectas con base fija —«veo una
onda muy sencilla y muy cuadrada… yo intentaría montar una onda que se mueva tanto por arriba
como por abajo y no como ahora que tiene una base fija»— y `showwaves` una traza fina. Las
máscaras con `geq` recortan, no redondean.

Así que la capa se **dibuja** con `PIL.ImageDraw.rounded_rectangle` —una llamada por cápsula y
por fotograma— y se le pasa a FFmpeg **en crudo por tubería** (`-f rawvideo -pix_fmt rgba`), que
la superpone en una sola pasada. No hay miles de PNG en disco ni una segunda recodificación.

Y por qué la altura sale de la FFT y no de la envolvente
--------------------------------------------------------
La primera versión de estas cápsulas usó una **ventana deslizante de la envolvente de amplitud**:
96 barras = los últimos 4,3 s de audio. Se rechazó al verlo en movimiento, y con razón:
«lo que hace es desplazarse hacia la izquierda con diferente amplitud de onda pero no se ve
moverse la onda». Es un scroll, no un ecualizador.

Aquí cada barra es una **banda de frecuencia** y su altura es la energía de esa banda **en el
instante del fotograma** (FFT de una ventana centrada en él). Consecuencia visible, que es
exactamente lo que se pedía: la barra **no se mueve de sitio**, sube y baja donde está. Lo
vigilan dos pruebas con un tono puro (`tests/test_onda.py`): con la frecuencia fija, el máximo se
queda en la misma barra fotograma tras fotograma; si la frecuencia cambia, el máximo cambia de
barra.

Qué es del ESTUDIO y qué es del CANAL
-------------------------------------
**Este módulo es el MECANISMO.** Sabe convertir audio en alturas, dibujar las cápsulas,
componerlas encima y medir que no ha estropeado el montaje. **No sabe qué aspecto tiene la onda
de un canal**: el color, la opacidad, la caja, el eje, cuántas cápsulas hay, su grosor y su radio
los declara cada canal en su `perfil.json → formato.composicion.onda_de_ecualizador`. Es la regla
de F4.9 («las decisiones tomadas para cada canal no pueden estar dentro de lib/») y el patrón es
el mismo que `lib/lineas_rojas.py` con sus guardianes de color.

**El grosor y el radio subieron al perfil en este rework, y estaba escrito que pasaría**: la
versión con `showfreqs` dejó `FRACCION_BARRA = 0.7` aquí con el aviso «si se piden barras más
gruesas o con las puntas redondeadas, esto sube al perfil». Lo pidió, y sube — no se edita una
constante del estudio para cambiar el aspecto de un canal.

**Falla cerrada si el canal la declara a medias.** Un `onda_de_ecualizador: true` dice que sí sin
decir cómo, y eso no se rellena con el aspecto de otro canal: se detiene nombrando los campos que
faltan. Lo que **no** es un fallo es no declararla — un canal sin onda monta exactamente como
antes de esta feature.

El eje NO es una base, y eso cambió el nombre de un campo
---------------------------------------------------------
Las cápsulas crecen hacia arriba **y hacia abajo** desde el eje, así que la caja va de
`eje_y_px - alto_px/2` a `eje_y_px + alto_px/2`. El campo se llamaba `linea_base_y_px` cuando la
onda tenía base fija; mantener el nombre con el significado cambiado habría dejado la trampa
servida —una onda que baja media caja por debajo de donde el perfil dice que «se apoya»—, así que
se renombró y la guarda **reconoce el nombre viejo** para decir qué hay que reescribir.

Consecuencia para los subtítulos: `holgura_con_subtitulos` mide desde el **borde inferior** de la
caja, no desde el eje. Con la misma declaración, la holgura de un canal baja `alto_px/2`.

Las cinco decisiones del análisis que NO son del canal, con su medición
-----------------------------------------------------------------------
Todas se midieron sobre la narración real del montaje de cierre del Sprint 2 (105,3 s de Kokoro,
`subtitulos/final-sin-subtitulos.mp4`) con 96 barras, y están regeneradas en el informe de la
feature. El material siempre es el mismo —una voz narrada— y por eso son del estudio.

1. **Ventana de 1024 muestras a 24 kHz, centrada en el fotograma.** Son 42,7 ms, justo lo que
   dura un fotograma a 24 fps, así que la barra enseña el sonido de *su* fotograma. Centrada y no
   hacia atrás: una ventana que acaba en el fotograma va medio fotograma por detrás de la voz.
2. **Bandas repartidas en logaritmo entre 80 Hz y 8 kHz.** Es el rango donde vive una voz; con
   todo el espectro (0-12 kHz) el tercio derecho de la onda no se movería nunca.
3. **Compensación de pendiente espectral (+6 dB/octava, `COMPENSA_PENDIENTE = 1.0`).** Una voz
   pierde energía con la frecuencia, así que sin compensar la onda sale escorada a la izquierda —
   lo que se vio con `showfreqs`. Medido, altura mediana de las 16 cápsulas de la izquierda /
   del centro / de la derecha: **0,458 / 0,191 / 0,079 sin compensar** y **0,314 / 0,246 / 0,190
   con ella**. La correlación con el volumen del instante apenas se resiente (0,887 → 0,863).
4. **Escala de amplitud `cbrt`** sobre la energía normalizada al percentil 99,5 del propio vídeo.
   Lo que decide es **cuánto se ve la onda en un instante normal**: altura mediana de la cápsula
   sobre el alto de la caja, `lin` **0,019** (la onda es la línea de puntos, o sea invisible),
   `sqrt` 0,139, `cbrt` **0,268**. El recorrido no sirve para elegir aquí y conviene decirlo: con
   la compensación puesta, las tres escalas mueven 95-96 de las 96 cápsulas. El percentil y no el
   máximo: un golpe aislado no debe achatar el resto del vídeo.
5. **Caída máxima de 0,25 por fotograma.** La subida es instantánea y la bajada limitada, como un
   vúmetro: recorta el parpadeo (salto p95 entre fotogramas **0,326 → 0,265**) sin perder reacción
   (correlación con el volumen 0,863 → 0,862). A tope de escala, una cápsula tarda 4 fotogramas
   (167 ms) en volver al mínimo. Apretarla más sí cuesta: con 0,08 el parpadeo baja a 0,232 pero
   la correlación cae a 0,798 y la onda se queda inflada (mediana 0,334).

Las cinco están regeneradas en `experimentos/verif-F4.11-v2/analisis.json`, que las recalcula con
este mismo código cambiando una constante por columna.

Y una guarda que no se deduce, se cuenta: `aplica` mide el vídeo con `ffprobe` **antes y
después**. Si la cadencia, la duración o el número de fotogramas cambian, deja el montaje como
estaba y aborta. El criterio de aceptación de la ficha —«el vídeo mantiene la duración y el
fps»— es una comprobación del código, no una promesa del informe.

El contraste se MIDE y se PUBLICA, y no aprueba
-----------------------------------------------
El color es del canal y la revisión de F4.11 midió que el de un canal desaparece sobre su fondo
(1,586:1 de mediana, 95,9 % del área por debajo de 3:1). La causa **no es la opacidad** —sobre un
gris medio es casi neutra, 1,279 → 1,269— sino la luminancia del color. Así que cada run publica
el contraste real de la cápsula pintada contra el fondo que tapa en `generacion-onda.json →
contraste`, y `--check` publica la luminancia del color declarado. **No es un gate**: el color lo
decide el usuario y suspender su montaje por su decisión sería el estudio decidiendo por el canal.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter

import numpy as np
from PIL import Image, ImageDraw

from lib import config
from lib.config import VIDEO_HEIGHT, VIDEO_WIDTH

CLAVE_PERFIL = "formato.composicion.onda_de_ecualizador"
_RECORDS_FILENAME = "generacion-onda.json"

# Todo lo que define el aspecto de la onda de un canal. Van los nueve o no va ninguno: media
# declaración es un canal que cree tener una onda distinta de la que se le pinta.
OBLIGATORIOS = (
    "barras",
    "ancho_px",
    "alto_px",
    "x_px",
    "eje_y_px",
    "grosor_px",
    "radio_px",
    "color",
    "opacidad",
    "acabado",
)

# El nombre que tenía el eje cuando la onda tenía base fija. Se reconoce para poder decir qué
# reescribir, porque el valor **no** se puede copiar tal cual: lo que era el suelo de la onda
# ahora es su mitad, y dejarlo igual mete la onda `alto_px/2` px dentro de los subtítulos.
CAMPO_RENOMBRADO = ("linea_base_y_px", "eje_y_px")

# --- Lo que SÍ es del estudio, con su medición en el encabezado del módulo ------------------
# Tasa de análisis: la nativa de Kokoro, que es de donde sale la narración. Remuestrear a 48 kHz
# no añadiría ninguna banda por debajo de 8 kHz, que es donde se mira.
TASA_ANALISIS = 24000
VENTANA_FFT = 1024
BANDA_MIN_HZ = 80.0
BANDA_MAX_HZ = 8000.0
COMPENSA_PENDIENTE = 1.0
ESCALA_AMPLITUD = "cbrt"
REFERENCIA_PERCENTIL = 99.5
CAIDA_MAXIMA_POR_FOTOGRAMA = 0.25
# Por debajo de esta referencia el vídeo no tiene narración que dibujar: es silencio o ruido de
# fondo, y normalizarlo pintaría una onda inventada a tope de escala. La narración real da 3,61
# con estas constantes (`generacion-onda.json → mecanismo.referencia`), o sea 360 veces este piso.
PISO_REFERENCIA = 0.01
# Fotogramas que se muestrean para medir el contraste de la cápsula contra su fondo. Ocho
# repartidos por el vídeo: el fondo se desplaza con el lienzo de F4.10, así que un solo fotograma
# no lo describe. Cada muestra es un `-ss` con búsqueda de entrada (~0,3 s); decodificar el vídeo
# entero para esto costaría más que dibujar la onda.
MUESTRAS_CONTRASTE = 8
# Misma calidad que el quemado de subtítulos, que es la otra pasada que recodifica el vídeo.
CRF = 18
# Cuántos fotogramas de audio se analizan de una vez. La FFT vectorizada de un vídeo de 25 min
# entero pediría ~300 MB de complejos; por lotes se queda en decenas de MB y tarda lo mismo.
LOTE_ANALISIS = 2048


ACABADO_OPACO = "opaco"
ACABADO_CRISTAL = "cristal"
ACABADOS = (ACABADO_OPACO, ACABADO_CRISTAL)

# Campos que SOLO tienen sentido con el cristal. Se exigen cuando el canal lo pide y se rechazan
# cuando no, por el mismo motivo por el que la separacion entre capsulas se deriva en vez de
# declararse: un valor dormido en el perfil acaba contradiciendo al que manda.
CAMPOS_DEL_CRISTAL = ("color_del_filo", "translucidez", "desenfoque_px")


class OndaError(RuntimeError):
    """La onda del canal está mal declarada o la composición no ha salido. Detiene la etapa."""


@dataclass(frozen=True)
class Onda:
    """El aspecto de la onda de UN canal. Todo sale de su `perfil.json`."""

    barras: int
    ancho_px: int
    alto_px: int
    x_px: int
    eje_y_px: int
    grosor_px: int
    radio_px: int
    color: str
    opacidad: float
    acabado: str
    color_del_filo: str
    translucidez: float
    desenfoque_px: float
    velo_del_fondo: float

    @property
    def es_cristal(self) -> bool:
        return self.acabado == ACABADO_CRISTAL

    @property
    def rgb_del_filo(self) -> tuple[int, int, int]:
        crudo = (self.color_del_filo or self.color).lstrip("#")
        return (int(crudo[0:2], 16), int(crudo[2:4], 16), int(crudo[4:6], 16))

    @property
    def media_altura_px(self) -> float:
        """Lo que mide media cápsula a tope de escala: la onda es simétrica sobre el eje."""
        return self.alto_px / 2

    @property
    def y_px(self) -> int:
        """Borde superior de la caja.

        El ancla es el EJE y no la esquina a propósito: subir el techo de la onda (`alto_px`) no
        debe moverla de sitio, sino hacerla crecer por los dos lados a la vez.
        """
        return int(round(self.eje_y_px - self.media_altura_px))

    @property
    def borde_inferior_px(self) -> int:
        """Lo más abajo que puede llegar una cápsula. Es lo que limita con los subtítulos."""
        return self.y_px + self.alto_px

    @property
    def paso_px(self) -> float:
        """Distancia de centro a centro de dos cápsulas, con su aire incluido."""
        return self.ancho_px / self.barras

    @property
    def separacion_px(self) -> float:
        """Aire entre dos cápsulas. **Es derivada, no declarada**, y por eso se publica.

        El canal declara cuántas cápsulas hay, cuánto ocupan a lo ancho y qué grosor tienen: con
        esos tres, la separación ya está decidida. Declararla además sería un cuarto valor que
        puede contradecir a los otros tres, y entonces habría que elegir a quién obedecer.
        """
        return self.paso_px - self.grosor_px

    @property
    def rgb(self) -> tuple[int, int, int]:
        crudo = self.color.lstrip("#")
        return (int(crudo[0:2], 16), int(crudo[2:4], 16), int(crudo[4:6], 16))

    @property
    def alfa(self) -> int:
        return int(round(max(0.0, min(1.0, self.opacidad)) * 255))

    @property
    def luminancia_relativa(self) -> float:
        """Luminancia WCAG del color declarado. Es la palanca real del contraste, no la opacidad."""
        return float(_luminancia(np.array(self.rgb, dtype=np.float64)))


def _falta_declaracion(detalle: str) -> OndaError:
    """El mensaje del fail-closed dice QUÉ escribir, no solo que falta algo."""
    return OndaError(
        f"El canal '{config.CANAL_ACTIVO or '(ninguno)'}' declara la onda de ecualizador a medias: {detalle}\n"
        f"La guarda falla cerrada a propósito: el aspecto de la onda es del CANAL y el motor no "
        f"lo rellena, porque un valor por defecto sería el aspecto de otro canal.\n"
        f"Qué hacer: en canales/<id>/perfil.json, `{CLAVE_PERFIL}` es un objeto con "
        f"{', '.join(OBLIGATORIOS)}.\n"
        f"  · `barras` es cuántas cápsulas se ven y `grosor_px`/`radio_px` cuánto miden de ancho y de "
        f"redondeo; `ancho_px`/`alto_px`/`x_px`/`eje_y_px` son la caja sobre el fotograma de "
        f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}, con las cápsulas creciendo **hacia arriba Y hacia abajo** desde "
        f"`eje_y_px`, o sea que la caja va de `eje_y_px - alto_px/2` a `eje_y_px + alto_px/2`; `color` va en "
        f"hexadecimal (#RRGGBB) y `opacidad` entre 0 y 1.\n"
        f"  · Un canal que NO quiera onda no declara la clave: entonces su vídeo se monta igual que antes "
        f"de F4.11. Lo que no vale es decir que sí sin decir cómo."
    )


def _nodo_de_composicion(perfil: dict | None) -> dict:
    """El bloque que contiene la declaración, navegado sin suponer que el perfil lo tenga."""
    nodo = config.CANAL_PERFIL if perfil is None else perfil
    for parte in CLAVE_PERFIL.split(".")[:-1]:
        if not isinstance(nodo, dict):
            return {}
        nodo = nodo.get(parte) or {}
    return nodo if isinstance(nodo, dict) else {}


def declarada(perfil: dict | None = None) -> bool:
    """¿Este canal lleva onda? Es la única palanca, y vive en el perfil.

    Se mira la clave y no solo su valor: `false` es una decisión escrita («este canal no la
    quiere») y se distingue de la ausencia, que es un canal anterior a esta feature. Las dos
    montan igual, pero solo una de las dos está decidida.
    """
    nodo = _nodo_de_composicion(perfil)
    clave = CLAVE_PERFIL.split(".")[-1]
    if clave not in nodo:
        return False
    return bool(nodo[clave])


def _entero(valores: dict, campo: str) -> int:
    try:
        return int(valores[campo])
    except (TypeError, ValueError):
        raise _falta_declaracion(f"`{campo}` vale {valores[campo]!r} y tiene que ser un número entero") from None


def _color_hex(crudo) -> str:
    """Normaliza el color del canal a `#RRGGBB`.

    Se exige hexadecimal y no un nombre de color: el nombre habría que resolverlo con una tabla
    que este módulo no tiene, y un color mal escrito no puede descubrirse al renderizar.

    **El negro puro ya vale, y antes no**: con `showfreqs` el fondo de la onda se recortaba con
    una clave de color negra, así que una onda negra se borraba a sí misma. La capa se dibuja
    ahora en RGBA con su propio canal alfa y no hay nada que recortar.
    """
    texto = str(crudo).strip().lstrip("#")
    if texto.lower().startswith("0x"):
        texto = texto[2:]
    if len(texto) != 6 or any(c not in "0123456789abcdefABCDEF" for c in texto):
        raise _falta_declaracion(f"`color` vale {crudo!r} y tiene que ser hexadecimal de 6 dígitos (#RRGGBB)")
    return "#" + texto.upper()


def _opacidad(crudo) -> float:
    try:
        return float(crudo)
    except (TypeError, ValueError):
        raise _falta_declaracion(f"`opacidad` vale {crudo!r} y tiene que ser un número entre 0 y 1") from None


def _eje_sugerido(crudo: dict) -> str:
    """Qué eje deja la onda donde la dejaba la base vieja. Solo para el mensaje de migración."""
    viejo = CAMPO_RENOMBRADO[0]
    try:
        return str(int(crudo[viejo]) - int(crudo["alto_px"]) // 2)
    except (KeyError, TypeError, ValueError):
        return "(la base menos alto_px/2)"


def aspecto_del_canal(perfil: dict | None = None) -> Onda | None:
    """El aspecto de la onda del canal activo, o `None` si no la lleva. Falla cerrada a medias.

    Un canal no puede heredar el aspecto de otro: la única fuente es el perfil que `config` cargó
    para `CANAL_ACTIVO`, y se admite inyectarlo para las pruebas y para diagnosticar otro perfil.
    """
    if perfil is None and config.CANAL_ERROR:
        # Sin perfil cargado el problema es OTRO, y mandar a editar el bloque de la onda taparía
        # el diagnóstico que `config` ya tiene escrito.
        raise OndaError(f"No se puede componer la onda del canal: {config.CANAL_ERROR}")
    if not declarada(perfil):
        return None

    crudo = _nodo_de_composicion(perfil)[CLAVE_PERFIL.split(".")[-1]]
    if not isinstance(crudo, dict):
        raise _falta_declaracion(f"`{CLAVE_PERFIL}` vale {crudo!r} y tiene que ser un objeto con el aspecto de la onda")
    viejo, nuevo = CAMPO_RENOMBRADO
    if viejo in crudo and nuevo in crudo:
        # Con los DOS nombres puestos, el viejo se ignoraría en silencio y quedaría un valor
        # contradictorio dormido en el perfil. Es el mismo motivo por el que la separación entre
        # cápsulas se deriva en vez de declararse —dos sitios donde decir lo mismo acaban
        # diciendo cosas distintas—, así que aquí se aplica el mismo criterio y se para.
        raise _falta_declaracion(
            f"el perfil trae `{viejo}` y `{nuevo}` a la vez, y solo uno decide: `{nuevo}`. Quita "
            f"`{viejo}` del perfil — si lo que quieres es el valor que sale de él, el eje "
            f"equivalente es {_eje_sugerido(crudo)}"
        )
    if viejo in crudo and nuevo not in crudo:
        raise _falta_declaracion(
            f"`{viejo}` es como se llamaba el eje cuando la onda tenía base fija, y ahora es `{nuevo}`. "
            f"**El valor no se copia tal cual**: las cápsulas crecen hacia los dos lados, así que lo que era el "
            f"suelo de la onda pasa a ser su mitad y la caja baja `alto_px/2` px más. Con la base en "
            f"{crudo[viejo]}, el eje que deja la onda donde estaba es {_eje_sugerido(crudo)}"
        )
    faltan = [k for k in OBLIGATORIOS if k not in crudo]
    if faltan:
        raise _falta_declaracion(f"faltan los campos: {', '.join(faltan)}")

    onda = Onda(
        barras=_entero(crudo, "barras"),
        ancho_px=_entero(crudo, "ancho_px"),
        alto_px=_entero(crudo, "alto_px"),
        x_px=_entero(crudo, "x_px"),
        eje_y_px=_entero(crudo, "eje_y_px"),
        grosor_px=_entero(crudo, "grosor_px"),
        radio_px=_entero(crudo, "radio_px"),
        color=_color_hex(crudo["color"]),
        opacidad=_opacidad(crudo["opacidad"]),
        acabado=_acabado(crudo["acabado"]),
        color_del_filo=_color_hex(crudo["color_del_filo"]) if crudo.get("color_del_filo") else "",
        translucidez=_fraccion(crudo.get("translucidez"), "translucidez"),
        desenfoque_px=float(crudo.get("desenfoque_px") or 0.0),
        velo_del_fondo=_fraccion(crudo.get("velo_del_fondo"), "velo_del_fondo"),
    )
    _valida_acabado(crudo, onda)
    _valida_geometria(onda)
    return onda


def _acabado(crudo) -> str:
    if crudo not in ACABADOS:
        raise _falta_declaracion(
            f"`acabado` vale {crudo!r} y solo entiende {' | '.join(ACABADOS)}. "
            f"`{ACABADO_OPACO}` es la capsula de color plano; `{ACABADO_CRISTAL}` la deja "
            "translucida, con el fondo desenfocado viendose a traves y un filo del mismo tono"
        )
    return crudo


def _fraccion(crudo, campo: str) -> float:
    """Una fraccion 0-1 declarada por el canal. Ausente vale 0, presente y fuera de rango se para."""
    if crudo is None:
        return 0.0
    if not isinstance(crudo, (int, float)) or isinstance(crudo, bool) or not 0.0 <= float(crudo) <= 1.0:
        raise _falta_declaracion(f"`{campo}` vale {crudo!r} y tiene que ser un numero entre 0 y 1")
    return float(crudo)


def _valida_acabado(crudo: dict, onda: Onda) -> None:
    """Los campos del cristal se exigen con cristal y se rechazan sin el.

    Un `color_del_filo` dormido en un perfil que dibuja capsulas opacas es una decision que alguien
    escribio y que nadie aplica: el dia que se cambie el acabado, el aspecto saltara a un valor que
    nadie ha vuelto a mirar. Es el mismo criterio que la separacion derivada.
    """
    if onda.es_cristal:
        faltan = [c for c in CAMPOS_DEL_CRISTAL if crudo.get(c) in (None, "")]
        if faltan:
            raise _falta_declaracion(
                f"con `acabado: {ACABADO_CRISTAL}` hacen falta ademas: {', '.join(faltan)}. "
                "`color_del_filo` es el borde de la capsula (el mismo tono, mas fuerte), "
                "`translucidez` cuanto pesa el color frente al fondo que se ve a traves (0-1) y "
                "`desenfoque_px` el sigma del desenfoque de ese fondo"
            )
        return
    sobran = [c for c in CAMPOS_DEL_CRISTAL if crudo.get(c) not in (None, "")]
    if sobran:
        raise _falta_declaracion(
            f"con `acabado: {ACABADO_OPACO}` sobran: {', '.join(sobran)}. Son del cristal y aqui no "
            "se aplican, asi que quedarian escritos sin efecto"
        )


def _valida_geometria(onda: Onda) -> None:
    """Lo que no cabe en el fotograma no se descubre en el vídeo: se descubre aquí.

    Una caja fuera de cuadro no hace fallar a FFmpeg — `overlay` recorta lo que sobra y el vídeo
    sale sin onda, o con media. Después de montar.
    """
    if onda.barras < 4:
        raise _falta_declaracion(f"`barras` vale {onda.barras} y hacen falta al menos 4 para que sea una onda")
    if onda.grosor_px < 2:
        raise _falta_declaracion(f"`grosor_px` vale {onda.grosor_px} y una cápsula de menos de 2 px no se ve")
    if onda.radio_px < 0 or onda.radio_px * 2 > onda.grosor_px:
        raise _falta_declaracion(
            f"`radio_px` vale {onda.radio_px} sobre un grosor de {onda.grosor_px} px: el redondeo no puede pasar "
            f"de la mitad del grosor ({onda.grosor_px // 2}), que es cuando la punta ya es un semicírculo"
        )
    if onda.ancho_px < 1 or onda.separacion_px < 1:
        raise _falta_declaracion(
            f"`barras` vale {onda.barras} sobre {onda.ancho_px} px de ancho, o sea {onda.paso_px:.1f} px de paso, "
            f"y con `grosor_px` {onda.grosor_px} quedan {onda.separacion_px:.1f} px de aire: las cápsulas se "
            "tocarían y la onda se leería como una silueta maciza. Baja el número de barras, adelgázalas o "
            "ensancha la caja."
        )
    if not 0 < onda.opacidad <= 1:
        raise _falta_declaracion(f"`opacidad` vale {onda.opacidad} y tiene que estar entre 0 (excluido) y 1")
    if onda.alto_px % 2:
        raise _falta_declaracion(
            f"`alto_px` vale {onda.alto_px} y tiene que ser par: la onda es simétrica, así que hacen falta los "
            f"mismos píxeles a cada lado del eje. Con un alto impar sobra uno y la onda queda descentrada. "
            f"Pon {onda.alto_px - 1} o {onda.alto_px + 1}"
        )
    if onda.alto_px < 2 * onda.grosor_px:
        raise _falta_declaracion(
            f"`alto_px` vale {onda.alto_px} y el mínimo con `grosor_px` {onda.grosor_px} es {2 * onda.grosor_px}: "
            "una cápsula en silencio ya mide su grosor de alto, así que por debajo de eso la onda no tiene "
            "recorrido que enseñar"
        )
    fuera = []
    if onda.x_px < 0 or onda.x_px + onda.ancho_px > VIDEO_WIDTH:
        fuera.append(f"horizontal, x={onda.x_px} más ancho={onda.ancho_px} no cabe en {VIDEO_WIDTH}")
    if onda.y_px < 0 or onda.borde_inferior_px > VIDEO_HEIGHT:
        fuera.append(
            f"vertical, la caja va de y={onda.y_px} a y={onda.borde_inferior_px} (eje {onda.eje_y_px} ± "
            f"{onda.media_altura_px:.0f}) y el fotograma mide {VIDEO_HEIGHT}"
        )
    if fuera:
        raise _falta_declaracion("la caja de la onda se sale del fotograma — " + " · ".join(fuera))


def holgura_con_subtitulos(onda: Onda) -> dict:
    """Píxeles entre la onda y la banda donde se queman los subtítulos. **Se mide y se publica.**

    No es un gate, y la distinción es la misma que la del encuadre de la miniatura en F3.6: las
    dos capas las dibuja el estudio, así que puede decir si se pisan, pero **cuántas líneas ocupa
    el texto depende del guion** y suspender un montaje por una estimación produciría falsos
    positivos. Se supone el peor caso razonable, dos líneas de subtítulo.

    **Se mide desde el borde inferior de la caja, no desde el eje**, porque la onda es simétrica:
    con la misma declaración, la holgura de un canal es `alto_px/2` px menor que cuando las
    barras tenían base fija.
    """
    from lib import subtitulos

    if not subtitulos.activa():
        # Sin subtítulos no hay franja que respetar, y el perfil tampoco declara cuerpo ni margen.
        return {"activo": False, "holgura_px": None, "reportado_no_es_gate": "el canal no lleva subtítulos"}
    cfg = subtitulos.ajustes()
    lineas = 2
    alto_texto = int(round(float(cfg["cuerpo"]) * 1.2 * lineas))
    techo_del_texto = VIDEO_HEIGHT - int(cfg["margen_inferior_px"]) - alto_texto
    return {
        "activo": subtitulos.activa(),
        "techo_estimado_del_texto_px": techo_del_texto,
        "eje_de_la_onda_px": onda.eje_y_px,
        "borde_inferior_de_la_onda_px": onda.borde_inferior_px,
        "holgura_px": techo_del_texto - onda.borde_inferior_px,
        "lineas_supuestas": lineas,
        "reportado_no_es_gate": "estimación con 2 líneas de subtítulo; el número real lo pone el guion",
    }


# --- El análisis del audio: una banda de frecuencia por cápsula -----------------------------


def _fps(cadencia: str) -> float:
    """La cadencia de `ffprobe` viene como fracción (`24/1`), y aquí hace falta el número."""
    texto = str(cadencia).strip()
    try:
        if "/" in texto:
            arriba, abajo = texto.split("/", 1)
            return float(arriba) / float(abajo)
        return float(texto)
    except (TypeError, ValueError, ZeroDivisionError):
        raise OndaError(f"Cadencia ilegible: {cadencia!r}") from None


def _muestras_mono(medio: str | Path) -> np.ndarray:
    """El audio del medio, mono y a `TASA_ANALISIS`, en flotante entre -1 y 1.

    Se decodifica con FFmpeg y no con el módulo `wave` de la biblioteca estándar: los `.wav` de
    Kokoro son float32 (formato 3, IEEE float) y `wave` solo lee PCM entero. Y aquí la entrada
    normal no es un `.wav` sino el propio montaje.
    """
    resultado = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(medio),
         "-ac", "1", "-ar", str(TASA_ANALISIS), "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        capture_output=True, timeout=7200,
    )  # fmt: skip
    if resultado.returncode != 0 or not resultado.stdout:
        raise OndaError(f"No se pudo leer el audio de {medio}: {resultado.stderr.decode('utf-8', 'replace')[-2000:]}")
    return np.frombuffer(resultado.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def banco_de_bandas(barras: int) -> tuple[np.ndarray, np.ndarray]:
    """(matriz de pesos `barras × bins`, frecuencias centrales) del banco de filtros.

    Cada cápsula es una banda, y las bandas se reparten en **logaritmo** entre `BANDA_MIN_HZ` y
    `BANDA_MAX_HZ` porque así se oye: de 80 a 160 Hz hay la misma distancia musical que de 4 a
    8 kHz. Los pesos son triángulos solapados, como un banco mel, y cada fila suma 1 antes de la
    compensación de pendiente.

    **La trampa que resuelve el respaldo**: con ventana de 1024 a 24 kHz, un bin mide 23,44 Hz, y
    las bandas de abajo son más estrechas que eso —la primera mide **8,0 Hz** de base y la última
    724,7—. Su triángulo puede no contener ningún bin y saldría a cero: con 96 bandas le pasa a
    **9** (el 9,4 %), y hay **23** cuya base es más estrecha que un bin. Cuando pasa se interpola
    linealmente entre los dos bins vecinos, que es lo que hace que la primera cápsula no sea un
    calco de la segunda.

    **Las dos cifras llevan su dirección porque la primera versión de este docstring decía 19 y
    ese número no medía nada**: era `96 // 5`, o sea la frase «la quinta parte» convertida en
    dato. Lo cazó la 3.ª revisión de F4.11, y al re-derivarlo me equivoqué yo también —reconstruí
    los bordes con `barras + 1` en vez de los `barras + 2` que usa esta función, y con el
    triángulo de `b` a `b + 1` en vez de a `b + 2`—, lo que daba 20 y 38. Regenerar las dos, con
    la fórmula de aquí y no con una parecida:

        bordes = np.geomspace(BANDA_MIN_HZ, BANDA_MAX_HZ, barras + 2)
        # rescatadas: las bandas cuyo triángulo (bordes[b] .. bordes[b+2]) no contiene ningún bin
        # base estrecha: las bandas con bordes[b+2] - bordes[b] < (frecuencias[1] - frecuencias[0])
    """
    frecuencias = np.fft.rfftfreq(VENTANA_FFT, 1.0 / TASA_ANALISIS)
    bordes = np.geomspace(BANDA_MIN_HZ, BANDA_MAX_HZ, barras + 2)
    matriz = np.zeros((barras, len(frecuencias)), dtype=np.float32)
    for b in range(barras):
        bajo, centro, alto = bordes[b], bordes[b + 1], bordes[b + 2]
        triangulo = np.clip(
            np.minimum((frecuencias - bajo) / (centro - bajo), (alto - frecuencias) / (alto - centro)), 0, None
        )
        if triangulo.sum() <= 0:
            k = int(min(max(np.searchsorted(frecuencias, centro), 1), len(frecuencias) - 1))
            peso = (centro - frecuencias[k - 1]) / (frecuencias[k] - frecuencias[k - 1])
            triangulo = np.zeros_like(frecuencias)
            triangulo[k - 1], triangulo[k] = 1 - peso, peso
        matriz[b] = triangulo / triangulo.sum()
    centros = bordes[1:-1]
    ganancia = (centros / centros[0]) ** COMPENSA_PENDIENTE
    # Media 1: así la escala de los valores no depende de la compensación ni del número de
    # cápsulas, y `PISO_REFERENCIA` sigue significando lo mismo para cualquier canal.
    matriz *= (ganancia / ganancia.mean()).astype(np.float32)[:, None]
    return matriz, centros


def energia_por_banda(medio: str | Path, barras: int, fotogramas: int, fps: float) -> tuple[np.ndarray, dict]:
    """Altura de cada cápsula en cada fotograma, entre 0 y 1, más las medidas del análisis.

    Devuelve una matriz `(fotogramas, barras)`. **Cada fila es el espectro del instante de ese
    fotograma**, y eso es lo que hace que la cápsula suba y baje sin moverse de sitio.
    """
    muestras = _muestras_mono(medio)
    matriz, centros = banco_de_bandas(barras)
    ventana = np.hanning(VENTANA_FFT).astype(np.float32)
    mitad = VENTANA_FFT // 2
    centros_muestra = (np.arange(max(fotogramas, 0)) / fps * TASA_ANALISIS).astype(np.int64)
    # Relleno por delante para poder centrar la ventana en el primer fotograma, y por detrás
    # hasta cubrir el último: **un audio más corto que el vídeo es normal** —el montaje puede
    # acabar en negro— y sin este relleno la indexación se saldría del array.
    hace_falta = (int(centros_muestra[-1]) + VENTANA_FFT) if len(centros_muestra) else VENTANA_FFT
    cola = max(0, hace_falta - (mitad + len(muestras)))
    relleno = np.concatenate([np.zeros(mitad, np.float32), muestras, np.zeros(cola, np.float32)])
    desplazamiento = np.arange(VENTANA_FFT)

    bandas = np.zeros((fotogramas, barras), dtype=np.float32)
    for desde in range(0, fotogramas, LOTE_ANALISIS):
        hasta = min(desde + LOTE_ANALISIS, fotogramas)
        bloques = relleno[centros_muestra[desde:hasta, None] + desplazamiento[None, :]]
        espectro = np.abs(np.fft.rfft(bloques * ventana, axis=1)).astype(np.float32)
        bandas[desde:hasta] = espectro @ matriz.T

    referencia = float(np.percentile(bandas, REFERENCIA_PERCENTIL)) if bandas.size else 0.0
    silencio = referencia < PISO_REFERENCIA
    if silencio:
        # Sin narración no se inventa una onda: todas las cápsulas al mínimo, que es un punto.
        valores = np.zeros_like(bandas)
    else:
        valores = np.cbrt(np.clip(bandas / referencia, 0.0, 1.0))
        # Caída limitada: sube de golpe y baja como un vúmetro. El bucle recorre fotogramas y
        # cada paso es una operación vectorial de `barras` elementos, así que cuesta milisegundos.
        for n in range(1, len(valores)):
            np.maximum(valores[n], valores[n - 1] - CAIDA_MAXIMA_POR_FOTOGRAMA, out=valores[n])

    recorrido = np.percentile(valores, 95, axis=0) - np.percentile(valores, 5, axis=0) if len(valores) else np.zeros(1)
    medidas = {
        "tasa_hz": TASA_ANALISIS,
        "ventana_fft": VENTANA_FFT,
        "banda_hz": [BANDA_MIN_HZ, BANDA_MAX_HZ],
        "compensa_pendiente": COMPENSA_PENDIENTE,
        "escala_amplitud": ESCALA_AMPLITUD,
        "referencia_percentil": REFERENCIA_PERCENTIL,
        "referencia": round(referencia, 5),
        "caida_maxima_por_fotograma": CAIDA_MAXIMA_POR_FOTOGRAMA,
        "sin_narracion": bool(silencio),
        "muestras_de_audio": int(len(muestras)),
        "duracion_audio_s": round(len(muestras) / TASA_ANALISIS, 3),
        "centro_hz_primera_ultima": [round(float(centros[0]), 1), round(float(centros[-1]), 1)],
        "altura_mediana": round(float(np.median(valores)), 3) if valores.size else 0.0,
        "altura_maxima": round(float(valores.max()), 3) if valores.size else 0.0,
        "capsulas_con_recorrido": int((recorrido > 0.15).sum()),
    }
    return valores, medidas


# --- El dibujo: una cápsula por banda y por fotograma ---------------------------------------


def capa(valores: np.ndarray, onda: Onda) -> Image.Image:
    """La capa RGBA de UN fotograma, del tamaño exacto de la caja de la onda.

    Se dibuja solo la caja y no el fotograma entero: a 1920x1080 la tubería movería 8,3 MB por
    fotograma en vez de los 2 MB de una caja de 1920x260, y el resto serían píxeles
    transparentes. El prototipo dibujaba el fotograma completo.

    Las coordenadas de PIL son **inclusivas**, así que una cápsula de `grosor_px` px de ancho va
    de `x0` a `x0 + grosor_px - 1`. El prototipo usaba `centro ± grosor//2`, que da un píxel más.
    """
    imagen = Image.new("RGBA", (onda.ancho_px, onda.alto_px), (0, 0, 0, 0))
    lapiz = ImageDraw.Draw(imagen)
    relleno = (*onda.rgb, onda.alfa)
    eje = onda.alto_px // 2
    minimo = onda.grosor_px / 2
    for i, valor in enumerate(valores):
        izquierda = int((i + 0.5) * onda.paso_px) - onda.grosor_px // 2
        # **La media altura se redondea a un entero antes de dibujar**, y no es cosmético: con
        # 8,35 px a cada lado, PIL redondea el borde de arriba y el de abajo por separado y la
        # cápsula sale 1 px descentrada. La simetría es la petición literal del usuario, así que se
        # cuantiza la altura para conservarla — un píxel de altura no se ve, un eje torcido sí.
        media = min(eje, int(round(max(minimo, float(valor) * eje))))
        lapiz.rounded_rectangle(
            [izquierda, eje - media, izquierda + onda.grosor_px - 1, eje + media - 1],
            radius=onda.radio_px,
            fill=relleno,
        )
    return imagen


def mascara(valores: np.ndarray, onda: Onda) -> Image.Image:
    """La FORMA de las capsulas en gris, que es lo unico que cruza la tuberia con cristal.

    Con acabado opaco por la tuberia va la capa RGBA ya pintada; con cristal va solo la silueta,
    porque el color, el desenfoque y el filo los hace FFmpeg en C sobre el fotograma que ya tiene.
    Son 2 MB por fotograma en vez de 8 MB, y el dibujo en Python se queda en lo unico que Python
    hace mejor: la capsula de punta redonda.
    """
    imagen = Image.new("L", (onda.ancho_px, onda.alto_px), 0)
    lapiz = ImageDraw.Draw(imagen)
    eje = onda.alto_px // 2
    minimo = onda.grosor_px / 2
    for i, valor in enumerate(valores):
        izquierda = int((i + 0.5) * onda.paso_px) - onda.grosor_px // 2
        media = min(eje, int(round(max(minimo, float(valor) * eje))))
        lapiz.rounded_rectangle(
            [izquierda, eje - media, izquierda + onda.grosor_px - 1, eje + media - 1],
            radius=onda.radio_px,
            fill=255,
        )
    return imagen


def gradiente_del_reflejo(onda: Onda) -> Image.Image:
    """El brillo de dentro de la capsula: mas claro en los bordes de arriba y abajo que en el centro.

    Es el `linear-gradient` con el que un cristal se dibuja en CSS, cocinado una vez y constante en
    todo el video: no depende del audio, solo de la altura de la caja.
    """
    columna = np.linspace(-1, 1, onda.alto_px)
    perfil = ((np.abs(columna) ** 1.4) * 30 + 10).astype(np.uint8)
    return Image.fromarray(np.tile(perfil[:, None], (1, onda.ancho_px)), "L").convert("RGB")


def _grafo_cristal(onda: Onda, cadencia: str) -> str:
    """El cristal: cuatro ingredientes, todos en una pasada de FFmpeg.

    1. **el fondo atenuado**, que es lo que se ve alrededor de la capsula;
    2. **la refraccion**: dentro de la capsula se ve el fondo SIN atenuar, desenfocado y tenido —
       Se pidio asi con dos frases seguidas, «el fondo mas tenue» y «no hay que atenuarlas
       [las ondas] solo el fondo», y la unica lectura que cumple las dos es esta;
    3. **el filo**, la mascara menos su erosion, del mismo tono en version fuerte;
    4. **el reflejo**, el gradiente recortado por la forma.

    El desenfoque se hace a un cuarto de escala y se vuelve a subir: `gblur` con sigma grande sobre
    1920 px cuesta, y el resultado es indistinguible porque lo que se busca es justamente perder
    detalle.
    """
    # **Toda fuente `color=` lleva su `r=`, y no es cosmético**: sin `rate` FFmpeg las crea a
    # **25 fps**, y al entrar en un `blend` o un `maskedmerge` el framesync arrastra la salida a
    # esa cadencia. Lo cazó la guarda de `aplica` en el primer montaje del episodio 1: el vídeo
    # pasaba de 24/1 y 9.992 fotogramas a 25/1 y 10.398, con el audio ya sincronizado a los
    # primeros. La guarda dejó el montaje intacto y por eso esto se arregló antes de estrenarse.
    ancho, alto = onda.ancho_px, onda.alto_px
    r, g, b = onda.rgb
    fr, fg, fb = onda.rgb_del_filo
    # El velo cubre el FOTOGRAMA entero, asi que su fuente tiene que medir lo que el video y no lo
    # que la caja: se resuelve con `scale2ref` para no tener que conocer aqui el tamano del montaje.
    velo = (
        (
            f"color=c=white:s=16x16:r={cadencia},format=gbrp[velo_semilla];"
            f"[velo_semilla][entero_a]scale2ref[velo_estirado][entero_ref];"
            # **`setsar=1` no es cosmetico: sin el, el video sale CUADRADO.** `scale2ref` estira la
            # semilla al tamano del fotograma y, para conservar la proporcion de ese cuadrado de
            # 16x16, le reescribe el `sample_aspect_ratio` a 9:16. Ese SAR se propaga por el `blend`
            # hasta el fichero final: 1920x1080 de pixeles, pero cualquier reproductor lo muestra a
            # 1080x1080. Se vio en el episodio 1 —«lo has generado en 4:3 en vez de 16:9»— y no
            # lo cazo ninguna guarda porque las que habia comparan cadencia, fotogramas y duracion,
            # que estaban intactos. Ahora la proporcion tambien se compara (`sonda`).
            f"[velo_estirado]setsar=1[velo_src];"
            f"[velo_src][entero_ref]blend=all_mode=normal:all_opacity={onda.velo_del_fondo}[base_full];"
        )
        if onda.velo_del_fondo
        else "[entero_a]null[base_full];"
    )
    return (
        f"[0:v]split[entero_a][para_banda];"
        f"{velo}"
        f"[base_full]split[base][base_banda_src];"
        f"[base_banda_src]crop={ancho}:{alto}:{onda.x_px}:{onda.y_px},format=gbrp[base_banda];"
        f"[para_banda]crop={ancho}:{alto}:{onda.x_px}:{onda.y_px},format=gbrp[banda];"
        f"[banda]scale={max(2, ancho // 4)}:{max(2, alto // 4)},gblur=sigma={onda.desenfoque_px},"
        f"scale={ancho}:{alto}:flags=bilinear[borrosa];"
        f"color=c=0x{r:02X}{g:02X}{b:02X}:s={ancho}x{alto}:r={cadencia},format=gbrp[tinte];"
        f"[tinte][borrosa]blend=all_mode=normal:all_opacity={onda.translucidez},format=gbrp[vidrio];"
        f"[1:v]format=gray,split=3[m_forma][m_borde][m_refl];"
        f"[base_banda][vidrio][m_forma]maskedmerge,format=gbrp[cristal];"
        f"[m_borde]split[m1][m2];[m2]erosion=coordinates=255,erosion=coordinates=255[erosionada];"
        f"[m1][erosionada]blend=all_mode=subtract,format=gray[contorno];"
        f"[2:v]format=gray[gradiente];"
        f"[gradiente][m_refl]blend=all_mode=multiply:shortest=1,format=gray[refl];"
        f"color=c=0x{fr:02X}{fg:02X}{fb:02X}:s={ancho}x{alto}:r={cadencia},format=gbrp[filo];"
        f"[cristal][filo][contorno]maskedmerge,format=gbrp[con_filo];"
        f"color=c=white:s={ancho}x{alto}:r={cadencia},format=gbrp[brillo];"
        f"[con_filo][brillo][refl]maskedmerge,format=yuv420p[lista];"
        f"[base][lista]overlay=x={onda.x_px}:y={onda.y_px}:eof_action=pass[vid]"
    )


def grafo(onda: Onda, cadencia: str) -> str:
    """El `-filter_complex` completo, construido y **legible sin lanzar FFmpeg**.

    Es una línea porque el dibujo ya no lo hace FFmpeg: la capa entra por la segunda entrada y
    solo hay que ponerla en su sitio. `eof_action=pass` y no el `repeat` por defecto: si la capa
    acabara antes que el vídeo, lo que queda es fondo limpio y no la última onda congelada.
    """
    # `cadencia` no se usa aquí: la capa llega por tubería ya a la cadencia del vídeo, así que
    # el grafo no la necesita. Se conserva en la firma porque el mensaje de la guarda de
    # `aplica` manda a leer esta función cuando el montaje cambia de cadencia, y una firma que
    # no la nombrara haría pensar que el dato no llega hasta aquí.
    if onda.es_cristal:
        # Con cristal la cadencia SÍ se usa: las fuentes `color=` la necesitan (ver `_grafo_cristal`).
        return _grafo_cristal(onda, cadencia)
    del cadencia
    return f"[0:v][1:v]overlay=x={onda.x_px}:y={onda.y_px}:eof_action=pass[vid]"


def comando(
    entrada: str | Path,
    salida: str | Path,
    onda: Onda,
    cadencia: str,
    reflejo: str | Path | None = None,
    fotogramas: int | None = None,
) -> list[str]:
    """La orden de FFmpeg completa, separada de su ejecución para poder comprobarla sin renderizar.

    La capa entra como `rawvideo` **con la cadencia del vídeo**, no con la que traiga por
    defecto: si no coinciden, FFmpeg reparte los fotogramas de la capa por el tiempo que le toca
    y la onda va desincronizada con la voz.

    **Y la salida lleva `-frames:v`, que es un CINTURÓN y no el arreglo del origen** (06-09).

    Componer llegó a devolver **un fotograma de más** —al episodio de un canal le pasó de 8.984 a 8.985,
    y la guarda de `aplica` abortó el montaje entero—, y lo que se sabe del porqué es esto:

    - **Es intermitente sobre bytes idénticos**: la misma orden sobre el mismo fichero da 121
      fotogramas 1 de cada 12 veces y 120 las otras once. Eso descarta un cálculo del muxer.
    - **Depende del ACABADO, no del audio**: con `cristal` sale 1/12 y con `opaco` 0/12 sobre el
      mismo material. Y el audio de este episodio dura **menos** que su vídeo (374,333000 contra
      374,333333 s), así que la primera explicación que se escribió aquí —que el AAC copiado se
      pasaba de largo y el muxer rellenaba— **era falsa**.
    - Lo que la evidencia sostiene: el grafo del cristal tiene **fuentes sin fin** —el `color=` del
      velo y el reflejo con `-loop 1`— que siguen vivas mientras `-c:a copy` lee la entrada 0. No se
      ha podido atribuir a un filtro concreto.

    Fijar el conteo no recorta nada real: `-frames:v` es un techo, nunca rellena, y el fotograma que
    corta es una **repetición del último** (diferencia media entre consecutivos dentro de la caja:
    10,06 y 14,61 entre fotogramas reales, **0,10** contra el extra).
    """
    if onda.es_cristal and reflejo is None:
        raise OndaError(
            "el acabado `cristal` necesita el gradiente del reflejo como tercera entrada: lo cocina "
            "`gradiente_del_reflejo(onda)` y `compone` lo deja en un fichero temporal"
        )
    entrada_del_reflejo = ["-loop", "1", "-framerate", str(cadencia), "-i", str(reflejo)] if onda.es_cristal else []
    return [
        "ffmpeg", "-hide_banner", "-v", "error", "-y",
        "-i", str(entrada),
        "-f", "rawvideo", "-pix_fmt", "gray" if onda.es_cristal else "rgba",
        "-s", f"{onda.ancho_px}x{onda.alto_px}",
        "-framerate", str(cadencia), "-i", "-",
        *entrada_del_reflejo,
        "-filter_complex", grafo(onda, cadencia),
        "-map", "[vid]", "-map", "0:a",
        "-c:v", "libx264", "-crf", str(CRF), "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        *(["-frames:v", str(fotogramas)] if fotogramas else []),
        "-movflags", "+faststart",
        str(salida),
    ]  # fmt: skip


def compone(
    entrada: str | Path,
    salida: str | Path,
    onda: Onda,
    cadencia: str,
    fotogramas: int | None = None,
    valores: np.ndarray | None = None,
) -> dict:
    """Compone la onda sobre `entrada` y escribe `salida`. Devuelve el grafo y las medidas.

    El audio se **copia** tal cual: esta pasada solo dibuja. Es la misma economía que el quemado
    de subtítulos, que recodifica vídeo y copia audio para que cada pista pase por el codificador
    una sola vez.
    """
    if fotogramas is None:
        fotogramas = sonda(entrada)["fotogramas"]
    # Un desajuste entre las filas que se dibujan y los fotogramas que se piden falla de dos maneras
    # distintas según el signo —si sobran, FFmpeg cierra la tubería y se sale por `BrokenPipeError`;
    # si faltan, la salida queda corta y aborta la guarda de `aplica`—, así que se dice aquí. Ningún
    # camino de producción lo hace: `aplica` pasa el mismo número que alimenta el análisis.
    if valores is not None and len(valores) != fotogramas:
        raise OndaError(
            f"se van a dibujar {len(valores)} fotogramas y se piden {fotogramas}: la capa y el vídeo "
            "tienen que durar lo mismo, o la onda va desincronizada con la voz"
        )
    medidas: dict = {}
    if valores is None:
        empezado = perf_counter()
        valores, medidas = energia_por_banda(entrada, onda.barras, fotogramas, _fps(cadencia))
        medidas["analisis_s"] = round(perf_counter() - empezado, 2)

    # Con cristal por la tuberia va la SILUETA y el gradiente entra como tercera entrada; con
    # opaco va la capa RGBA ya pintada y no hay tercera entrada. Es la unica diferencia de esta
    # funcion entre los dos acabados.
    with tempfile.TemporaryDirectory(prefix="lanternist-onda-") as taller:
        reflejo = None
        if onda.es_cristal:
            reflejo = Path(taller) / "reflejo.png"
            gradiente_del_reflejo(onda).save(reflejo)
        dibuja = mascara if onda.es_cristal else capa
        return _pasa_por_ffmpeg(entrada, salida, onda, cadencia, valores, medidas, dibuja, reflejo, fotogramas)


def _pasa_por_ffmpeg(entrada, salida, onda, cadencia, valores, medidas, dibuja, reflejo, fotogramas=None) -> dict:
    args = comando(entrada, salida, onda, cadencia, reflejo, fotogramas)
    with tempfile.TemporaryFile() as errores:
        proceso = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errores)
        empezado = perf_counter()
        try:
            for fila in valores:
                try:
                    proceso.stdin.write(dibuja(fila, onda).tobytes())
                except BrokenPipeError:
                    # FFmpeg ha muerto: el motivo está en su stderr y lo cuenta el `returncode`.
                    break
            dibujado = perf_counter() - empezado
            proceso.stdin.close()
            codigo = proceso.wait(timeout=14400)
        except BaseException:
            # Un Ctrl+C a mitad dejaría a FFmpeg terminando un vídeo truncado, y el rollback de
            # `aplica` compara con el original: se mata el proceso antes de propagar.
            proceso.kill()
            proceso.wait()
            raise
        if codigo != 0:
            errores.seek(0)
            detalle = errores.read().decode("utf-8", "replace")[-3000:]
            raise OndaError(f"FFmpeg falló al componer la onda: {detalle}")
    return {
        "grafo": grafo(onda, cadencia),
        "fotogramas_dibujados": int(len(valores)),
        "dibujo_s": round(dibujado, 2),
        "analisis": medidas,
    }


# --- El contraste de la cápsula contra su fondo: se mide y se publica ------------------------

# La rampa de grises, para traducir una luminancia relativa a «esto es como un gris N».
_ESCALA_GRISES = np.repeat(np.arange(256)[:, None], 3, axis=1)


def _luminancia(rgb) -> np.ndarray:
    """Luminancia relativa WCAG de un color (o de un array de colores) en 0-255."""
    canal = np.asarray(rgb, dtype=np.float64) / 255.0
    lineal = np.where(canal <= 0.04045, canal / 12.92, ((canal + 0.055) / 1.055) ** 2.4)
    return np.tensordot(lineal, np.array([0.2126, 0.7152, 0.0722]), axes=([-1], [0]))


def _contraste(l1, l2):
    """Razón de contraste WCAG entre dos luminancias, en el orden que sea."""
    claro, oscuro = np.maximum(l1, l2), np.minimum(l1, l2)
    return (claro + 0.05) / (oscuro + 0.05)


def gris_equivalente(luminancia: float) -> float:
    """Qué gris de 0 a 255 tiene esa luminancia. Es la forma legible de dar el diagnóstico."""
    return float(np.interp(luminancia, _luminancia(_ESCALA_GRISES), np.arange(256)))


# **EL AVISO QUE HABÍA AQUÍ ESTÁ ATENDIDO** (05-09). Decía: «antes de integrar el liquid glass,
# leer esto — esta función tiene cableado el modelo de mezcla del `overlay` de hoy, y con glass la
# cifra dejaría de describir lo que se ve sin que nada falle». Se cumplió al pie de la letra: el
# cristal entró el 05-09 y el modelo se cambió con él, que es lo que el aviso pedía. Se conserva
# escrito porque la lección es la que vale — **una medida con un modelo dentro caduca cuando cambia
# lo que modela, y no se entera nadie**: por eso el modelo se elige aquí por `acabado` y no se
# supone.
def contraste_medido(video: str | Path, onda: Onda, muestras: int = MUESTRAS_CONTRASTE) -> dict:
    """Contraste real de la cápsula PINTADA contra el fondo que tapa. **No es un gate.**

    Se mide sobre el vídeo **sin onda** —el fondo tal cual— en `muestras` instantes repartidos,
    porque el lienzo de F4.10 se desplaza y un solo fotograma no lo describe. La cápsula pintada
    es el color del canal mezclado con el fondo a su opacidad, que es lo que hace `overlay`, así
    que la cifra es la que se ve y no la del color puro.

    Se mide sobre **toda la caja** y no solo sobre los píxeles de una cápsula: la cápsula sube y
    baja, y lo que interesa es si hay zonas de la caja donde desaparecería.
    """
    empezado = perf_counter()
    duracion = float(sonda(video)["duracion_s"])
    tiempos = [round(duracion * (i + 0.5) / muestras, 3) for i in range(muestras)]
    esperado = onda.ancho_px * onda.alto_px * 3
    fondos = []
    for t in tiempos:
        salida = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
             "-vf", f"crop={onda.ancho_px}:{onda.alto_px}:{onda.x_px}:{onda.y_px}",
             "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
            capture_output=True, timeout=600,
        )  # fmt: skip
        if salida.returncode == 0 and len(salida.stdout) == esperado:
            fondos.append(np.frombuffer(salida.stdout, dtype=np.uint8).reshape(onda.alto_px, onda.ancho_px, 3))
    if not fondos:
        return {"medido": False, "motivo": "no se pudo extraer ningún fotograma de la caja de la onda"}

    fondo = np.stack(fondos).astype(np.float64)
    # **Cuánto pesa el color dentro de la cápsula depende del acabado**, y con el cristal no es la
    # opacidad: es la `translucidez`, porque lo que hay debajo del color es el fondo desenfocado.
    # El desenfoque no mueve la luminancia media de una zona —promediar no cambia el promedio—, así
    # que para esta medida el fondo borroso vale lo mismo que el fondo. Lo que la medida NO incluye
    # es el filo ni el reflejo: son unos pocos píxeles del borde y siempre suman brillo, así que la
    # cifra publicada es el caso peor de la cápsula, no su media.
    peso = onda.translucidez if onda.es_cristal else onda.opacidad
    pintado = np.array(onda.rgb, dtype=np.float64) * peso + fondo * (1.0 - peso)
    razon = _contraste(_luminancia(pintado), _luminancia(fondo))
    return {
        "medido": True,
        "muestras": len(fondos),
        "instantes_s": tiempos[: len(fondos)],
        "color": onda.color,
        "acabado": onda.acabado,
        "peso_del_color": round(peso, 3),
        "opacidad": onda.opacidad,
        "luminancia_relativa_del_color": round(onda.luminancia_relativa, 4),
        "gris_equivalente_0_255": round(gris_equivalente(onda.luminancia_relativa), 1),
        "fondo_luminancia_mediana": round(float(np.median(_luminancia(fondo))), 4),
        "contraste_mediana": round(float(np.median(razon)), 3),
        "contraste_minimo": round(float(razon.min()), 3),
        "contraste_maximo": round(float(razon.max()), 3),
        "area_bajo_3_1_pct": round(float((razon < 3.0).mean() * 100), 1),
        "area_bajo_4_5_pct": round(float((razon < 4.5).mean() * 100), 1),
        "computo_s": round(perf_counter() - empezado, 2),
        "reportado_no_es_gate": (
            "el color y el acabado son del CANAL: esto se publica para que se decidan mirando un "
            "número, no para suspender el montaje. **Y con el acabado de cristal la cifra vale menos "
            "que con el opaco**: la cápsula es translúcida a propósito, así que su luminancia se "
            "parece a la del fondo por diseño y lo que separa la onda del dibujo es el TONO y el "
            "filo, que esta medida —solo luminancia— no ve. Se mide igual para saber si algún día "
            "se va a un extremo."
        ),
    }


# --- Medir el montaje antes y después -------------------------------------------------------


def _ffprobe_flujo(video: str | Path, campos: str, contando: bool) -> dict:
    """Los `campos` del flujo de vídeo, pedidos en JSON.

    La salida se pide en JSON y no en columnas: `ffprobe` **no respeta el orden** en que se le
    piden los campos —los devuelve en el orden de la estructura interna— y leer por posición
    daba la duración donde se esperaba el conteo de fotogramas.
    """
    cuenta = ["-count_frames"] if contando else []
    salida = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", *cuenta,
         "-show_entries", f"stream={campos}", "-of", "json", str(video)],
        capture_output=True, text=True, timeout=3600,
    )  # fmt: skip
    flujos = json.loads(salida.stdout or "{}").get("streams") or []
    if not flujos:
        raise OndaError(f"No se pudo medir {video}: ffprobe no devolvió flujo de vídeo ({salida.stderr[-500:]})")
    return flujos[0]


def sonda(video: str | Path) -> dict:
    """Cadencia, fotogramas y duración de un vídeo. Es lo que se compara antes y después.

    **Los fotogramas salen de la cabecera (`nb_frames`) y solo se cuentan uno a uno si falta.**
    La primera versión iba siempre con `-count_frames`, que decodifica el vídeo entero: la
    revisión de F4.11 midió **12,1 s por llamada** sobre 105 s de montaje, y son dos por etapa,
    o sea que la guarda costaba más que dibujar la onda (19,2 s). Con la cabecera son **0,06 s**
    y da el mismo número —2.528 en los dos ficheros del run real—, porque el contenedor lo
    escribe el mismo FFmpeg que acaba de montar. El respaldo se queda para el caso en que no
    esté: un `.ts` o un `.mkv` no traen el campo, y sin respaldo la guarda quedaría inútil — que
    es el motivo de esta función.

    **El límite de fiarse de la cabecera, medido**: un `.mp4` truncado declara 72 fotogramas y
    decodifica 37, así que la cabecera puede mentir. Aquí eso no abre un agujero porque para
    llegar a este punto FFmpeg ha tenido que devolver 0 sobre el fichero que acaba de escribir,
    y cualquier `returncode != 0` dispara el rollback antes de medir nada.
    """
    campos = _ffprobe_flujo(video, "r_frame_rate,nb_frames,duration,width,height,sample_aspect_ratio", contando=False)
    crudo = str(campos.get("nb_frames") or "").strip()
    if not crudo.isdigit() or int(crudo) <= 0:
        campos = _ffprobe_flujo(
            video, "r_frame_rate,nb_read_frames,duration,width,height,sample_aspect_ratio", contando=True
        )
        crudo = str(campos.get("nb_read_frames") or "").strip()
    try:
        return {
            "cadencia": str(campos["r_frame_rate"]),
            "fotogramas": int(crudo),
            "duracion_s": round(float(campos["duration"]), 3),
            # **La PROPORCIÓN entra aquí desde el 05-09, y por un fallo que llegó al vídeo.** El
            # `scale2ref` del velo dejaba el `sample_aspect_ratio` en 9:16: el fichero medía
            # 1920x1080 de píxeles pero cualquier reproductor lo mostraba **cuadrado**. Los tres
            # campos que esta guarda comparaba —cadencia, fotogramas y duración— estaban intactos,
            # así que no saltó nada y lo tuvo que ver el usuario: «lo has generado en 4:3 en vez de
            # 16:9». Un vídeo puede salir deformado sin cambiar ni un fotograma ni un segundo.
            "tamano": f"{campos.get('width')}x{campos.get('height')}",
            "sar": str(campos.get("sample_aspect_ratio") or "1:1"),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise OndaError(f"No se pudo medir {video}: {type(exc).__name__} sobre {campos!r}") from None


def _tiene_audio(video: str | Path) -> bool:
    salida = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    return "audio" in (salida.stdout or "")


def aplica(video: str | Path, run_dir: str | Path) -> dict | None:
    """Compone la onda del canal sobre el vídeo montado. `None` si el canal no la lleva.

    Deja el montaje sin onda en `onda/final-sin-onda.mp4`, igual que hacen la música y los
    subtítulos: comparar los dos es cómo se ve qué ha puesto esta etapa, y volver atrás no
    obliga a montar de nuevo.
    """
    aspecto = aspecto_del_canal()
    if aspecto is None:
        return None
    video = Path(video)
    if not _tiene_audio(video):
        raise OndaError(
            f"{video.name} no tiene pista de audio, y la onda se genera de la narración: sin audio no hay "
            "onda que dibujar. Monta el vídeo con su narración antes de componerla."
        )

    # El reloj de la etapa arranca aquí, no en `compone`: la primera revisión de F4.11 midió que
    # la cifra publicada contaba el 43 % del coste real porque dejaba fuera las sondas.
    empezado_etapa = perf_counter()
    antes = sonda(video)
    trabajo = Path(run_dir) / "onda"
    trabajo.mkdir(parents=True, exist_ok=True)
    sin_onda = trabajo / ("final-sin-onda" + video.suffix)
    video.replace(sin_onda)

    empezado_compone = perf_counter()
    try:
        hecho = compone(sin_onda, video, aspecto, antes["cadencia"], fotogramas=antes["fotogramas"])
    except BaseException:
        # Sin esto, un fallo a mitad deja el run sin `final.mp4` y con el montaje escondido en un
        # subdirectorio: el vídeo vuelve a su sitio y la etapa falla con el montaje intacto.
        # Se atrapa `BaseException` y no `Exception` a propósito: la codificación de un fondo de
        # nueve minutos dura minutos, así que **el fallo más probable es un Ctrl+C**, y
        # `KeyboardInterrupt` no es una `Exception`. Se deshace y se vuelve a lanzar.
        video.unlink(missing_ok=True)
        sin_onda.replace(video)
        raise
    compuesto_s = perf_counter() - empezado_compone

    despues = sonda(video)
    # Se comparan TODAS las claves de la sonda y no una lista escrita aparte: una lista aparte
    # es lo que dejó fuera la proporción, porque añadir un campo a `sonda` no bastaba.
    #
    # **Con `-frames:v` puesto, esta guarda ya NO vigila el conteo por arriba**: producir de más es
    # imposible por construcción. Lo que sigue viva es la mitad de abajo —producir de MENOS, si el
    # grafo se queda corto— más la cadencia, el tamaño y el SAR. Conviene saberlo antes de citarla
    # como prueba de algo que ya no comprueba.
    cambios = {k: (antes[k], despues[k]) for k in antes if antes[k] != despues[k]}
    if cambios:
        video.unlink(missing_ok=True)
        sin_onda.replace(video)
        raise OndaError(
            f"Componer la onda ha cambiado el montaje y no debía: {cambios} (antes, después). El vídeo se ha "
            "dejado como estaba: mira el grafo de `lib/onda.grafo` y la orden de `lib/onda.comando`, empezando "
            "por lo que remuestrea (`framerate`) o recorta (`overlay`, `shortest`). **La cadencia de la capa NO "
            "es la causa de este error**: componer con la cadencia equivocada deja intactos los tres campos que "
            "esta guarda compara y solo desincroniza la onda de la voz; de eso se ocupa "
            "`tests/test_onda.py::test_la_capa_entra_con_la_cadencia_del_video`."
        )

    contraste = contraste_medido(sin_onda, aspecto)
    total_s = perf_counter() - empezado_etapa
    registro = {
        "aspecto": asdict(aspecto),
        "aspecto_declarado_en": f"canales/{config.CANAL_ACTIVO}/perfil.json → {CLAVE_PERFIL}",
        "derivado": {
            "paso_px": round(aspecto.paso_px, 3),
            "separacion_px": round(aspecto.separacion_px, 3),
            "caja": {
                "x": aspecto.x_px,
                "y": aspecto.y_px,
                "ancho": aspecto.ancho_px,
                "alto": aspecto.alto_px,
                "borde_inferior": aspecto.borde_inferior_px,
            },
        },
        "mecanismo": {
            "dibujo": "cápsulas con PIL.ImageDraw.rounded_rectangle, simétricas sobre el eje",
            "altura": "energía por banda de frecuencia (FFT) en el instante del fotograma",
            "composicion": "una pasada de FFmpeg con la capa RGBA por tubería",
            **hecho["analisis"],
        },
        "montaje": {"antes": antes, "despues": despues, "intactos": True},
        "subtitulos": holgura_con_subtitulos(aspecto),
        "contraste": contraste,
        "fotogramas_dibujados": hecho["fotogramas_dibujados"],
        # El reparto entero, para que nadie tenga que volver a medir de dónde sale el coste.
        "reparto_s": {
            "analisis_del_audio": hecho["analisis"].get("analisis_s"),
            "dibujo_y_codificacion": hecho["dibujo_s"],
            "contraste": contraste.get("computo_s"),
            "sondas_y_guarda": round(total_s - compuesto_s - float(contraste.get("computo_s") or 0.0), 2),
        },
        "computo_s": round(total_s, 2),
        "factor_tiempo_real": round(total_s / antes["duracion_s"], 3) if antes["duracion_s"] else 0.0,
        "grafo": hecho["grafo"],
        "sin_onda": str(sin_onda),
    }
    (Path(run_dir) / _RECORDS_FILENAME).write_text(
        json.dumps([registro], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"  [ONDA] {aspecto.barras} cápsulas de {aspecto.grosor_px} px · caja {aspecto.ancho_px}x{aspecto.alto_px} "
        f"sobre el eje y={aspecto.eje_y_px} · {registro['factor_tiempo_real']}x tiempo real",
        flush=True,
    )
    if contraste.get("medido") and contraste["contraste_mediana"] < 3.0:
        print(
            f"  [ONDA] AVISO: la cápsula pintada contrasta {contraste['contraste_mediana']}:1 con su fondo "
            f"({contraste['area_bajo_3_1_pct']}% del área por debajo de 3:1). La palanca es la luminancia de "
            f"`color` —{aspecto.color} equivale a un gris {contraste['gris_equivalente_0_255']:.0f}—, no la "
            "opacidad. Es del canal: se decide en su perfil.",
            flush=True,
        )
    holgura = registro["subtitulos"]
    if holgura["activo"] and holgura["holgura_px"] < 0:
        print(
            f"  [ONDA] AVISO: la onda baja {-holgura['holgura_px']} px dentro de la banda donde se queman los "
            f"subtítulos (estimada con {holgura['lineas_supuestas']} líneas). Sube `eje_y_px` o baja `alto_px` "
            "en el perfil del canal, o baja `subtitulos.margen_inferior_px`.",
            flush=True,
        )
    return registro


def preflight() -> list[dict]:
    """¿Podría esta etapa componer la onda AHORA? Lo consume `pipeline.py --check`.

    Aquí y no al montar: una onda mal declarada descubierta en la etapa de montaje cuesta las
    láminas y la voz ya generadas, que es el mismo motivo por el que el resto de adaptadores
    tienen su preflight.
    """
    try:
        aspecto = aspecto_del_canal()
    except OndaError as exc:
        return [{"nombre": "onda de ecualizador", "ok": False, "detalle": str(exc), "obligatorio": True}]
    if aspecto is None:
        return [
            {
                "nombre": "onda de ecualizador",
                "ok": True,
                "detalle": f"este canal no la declara ({CLAVE_PERFIL}): el vídeo se monta sin ella",
                "obligatorio": False,
            }
        ]
    checks = [
        {
            "nombre": "onda de ecualizador",
            "ok": True,
            "detalle": (
                f"{aspecto.barras} cápsulas de {aspecto.grosor_px} px (radio {aspecto.radio_px}, aire "
                f"{aspecto.separacion_px:.1f}) · caja {aspecto.ancho_px}x{aspecto.alto_px} en "
                f"({aspecto.x_px}, {aspecto.y_px}) sobre el eje y={aspecto.eje_y_px} · {aspecto.color} al "
                f"{aspecto.opacidad:.0%}"
            ),
            "obligatorio": True,
        },
        {
            # Se publica y no aprueba: el color es del canal. Lo que sí se puede decir sin ver el
            # vídeo es a qué gris equivale, que es la causa medida del contraste bajo.
            "nombre": "luminancia del color de la onda",
            "ok": True,
            "detalle": (
                f"{aspecto.color} tiene luminancia relativa {aspecto.luminancia_relativa:.4f}, la de un gris "
                f"{gris_equivalente(aspecto.luminancia_relativa):.0f}: sobre un fondo de ese gris la cápsula "
                "desaparece. El contraste real de cada run se publica en generacion-onda.json → contraste"
            ),
            "obligatorio": False,
        },
    ]
    salida = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    tiene = " overlay " in (salida.stdout or "")
    checks.append(
        {
            "nombre": "filtros de FFmpeg",
            "ok": tiene,
            "detalle": (
                "overlay disponible; la onda la dibuja PIL y entra por tubería en crudo"
                if tiene
                else "este ffmpeg no trae overlay: no se puede componer la onda sobre el montaje"
            ),
            "obligatorio": True,
        }
    )
    holgura = holgura_con_subtitulos(aspecto)
    if holgura["activo"]:
        checks.append(
            {
                "nombre": "holgura con los subtítulos",
                "ok": holgura["holgura_px"] >= 0,
                "detalle": (
                    f"{holgura['holgura_px']} px entre el borde inferior de la onda "
                    f"({holgura['borde_inferior_de_la_onda_px']}) y el techo estimado del texto "
                    f"({holgura['techo_estimado_del_texto_px']}, con {holgura['lineas_supuestas']} líneas)"
                ),
                # Se mide y se publica; no aprueba ni suspende, porque las líneas las pone el guion.
                "obligatorio": False,
            }
        )
    return checks


__all__ = [
    "CLAVE_PERFIL",
    "OBLIGATORIOS",
    "Onda",
    "OndaError",
    "aplica",
    "aspecto_del_canal",
    "banco_de_bandas",
    "capa",
    "comando",
    "compone",
    "contraste_medido",
    "declarada",
    "energia_por_banda",
    "grafo",
    "gris_equivalente",
    "holgura_con_subtitulos",
    "preflight",
    "sonda",
]
