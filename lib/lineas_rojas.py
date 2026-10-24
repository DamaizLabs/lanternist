"""Guarda automática de las líneas rojas de color sobre las láminas generadas.

**Este módulo es el MECANISMO; la regla es del canal.** Sabe medir si una imagen tiene una mancha
de una banda de color concreta y detener la etapa si la cruza. **No sabe qué color está prohibido en
qué canal**: eso lo declara cada canal en su `perfil.json → lineas_rojas.guardianes_de_color`, y dos
canales del estudio no comparten nada — ni umbrales, ni nombre de la regla, ni el mensaje de error.

**Por qué existe.** Hasta F2.5 la única defensa de la línea roja firmada en `progress/gate0.md` §6 y
§8.1 (del primer canal) era una frase en el prompt **positivo** («no injury, no blood»). En el primer run
real falló en **1 de 8 láminas**: `slide-04` salió con un charco de sangre a los pies de la figura, y
el vídeo se montó con esos ~9,6 segundos en pantalla. Extrapolado a ~40 láminas por vídeo, del orden
de cinco violaciones por vídeo.

El prompt no puede ser la guarda: `workflows/qwen-2512-lightning-tinta.json` tiene **un solo**
`CLIPTextEncode` (positivo, nodo 5) y `cfg = 1.0`, así que ni hay nodo de prompt negativo ni serviría
de mucho si lo hubiera. La guarda tiene que mirar la **salida**.

**Por qué es POR CANAL desde F4.8, y no un detector de sangre global.** El piloto del segundo canal lo destapó
midiendo: este módulo llevaba dentro la premisa del primero —«sangre en una lámina cuyo único color
autorizado es el acento del material»— y sus siete umbrales estaban calibrados sobre estampas de
tinta **monocromas**. Aplicado al segundo canal, que es ilustración plana a todo color cálido, marcó como
sangre **las orejas del perro** del avatar, el marco del porche y las flores del banner, y abortó la
generación de la identidad del canal. Es el mismo modo de fallo que la nota histórica de más abajo ya
describe con el óxido, y en un canal cálido no tiene arreglo por calibración: el carmesí y un cielo de
atardecer son el mismo tono. Mandato del 03-09: cada canal con su guardián separado y **ninguna
sinergia entre ellos**.

**Falla cerrada, por diseño y en dos sitios distintos.** Si no puede medir una imagen (no existe, o es
más pequeña que la ventana), se detiene. Y si el perfil del canal **no declara** el bloque, también:
así «este canal no necesita guardián de color» queda escrito como decisión en vez de existir por
olvido. Es el mismo patrón que `metricas.py` aplica al CTR — sin dato, *sin evaluar, nunca aprobado*.

**Lo que NO comprueba, y hay que seguir mirando a ojo**: postura y expresión (la lámina de F2.5 tenía
además la figura cabizbaja, que §8.1 tampoco autoriza), y objetos que cambian la lectura de la escena
(de su travesaño colgaba una cadena que hace leer el conjunto como patíbulo). Eso no se mide con
píxeles. Separar la regla por canal **no** hace la guarda más lista: solo evita que la de un canal
juzgue las láminas de otro. La revisión humana del gate 1 sigue siendo obligatoria, y en un canal cuyas
líneas rojas son de situación —peligro real, conflicto adulto— es la **única** defensa.

**Suelo de detección de la especificación del primer canal, dicho con precisión.** Se caza: una mancha compacta
de 16x16 px en cualquier posición, o un total de 250 px repartidos como sea (salpicadura incluida: 40
gotas de 4x4 disparan). **No** se caza, y está medido: un reguero de 3x60 px (182 px) ni una mancha de
8x8 a caballo de dos celdas (66 px). No es un ajuste pendiente sino un límite: hay una lámina legítima
del corpus con 181 px de total, así que bajar el umbral para cazar el reguero produciría falsos
positivos. Por debajo de ese suelo, la red que queda es la revisión humana.

**Límite de estilo, RE-MEDIDO el 03-09 con la especificación del primer canal** (las cifras anteriores eran
de F2.5 y se habían quedado atrás): de las **207** imágenes de `canales/` y `experimentos/` disparan
**14**, y el desglose es lo interesante:

  · **5 son la marca del segundo canal**, que es un canal a todo color — el caso que obligó a F4.8. Con SU
    propia especificación (lista vacía) no dispara ninguna;
  · **6 son las pruebas fotorrealistas** `foto-*` de los spikes de flux y sdxl;
  · **1 es `experimentos/spike/flux/doodle-2.png`**, que no es fotorrealista sino un garabato;
  · **2 son fotogramas de vídeo montado** (`experimentos/verif-F2.13/karaoke-*.png`), justo lo que
    predice el aviso de más abajo sobre el reescalado a 1920x1080.

No son falsos positivos del canal —su estilo firmado es tinta— pero una fotografía real de
una pieza, o un fotograma de i2v, chocaría con la guarda. Para re-derivarlo:
`revisa(p, guardianes_del_canal())["pasa"]` sobre `Path("canales").rglob("*.png")` y `experimentos/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import config

# ── La calibración del primer canal, que AHORA VIVE EN SU PERFIL y aquí solo se documenta ─────
#
# Se conserva escrita porque es la evidencia de por qué esos siete números son esos, y porque
# cualquier canal futuro que necesite un guardián de color va a calibrar el suyo copiando este
# método. Los valores vigentes se leen del perfil; estos son los que se midieron.
#
# EL CRITERIO ES EL TONO, no el rojo genérico. Sobre la lámina con sangre del primer run y sobre
# el acento de óxido del zoo:
#
#   sangre   hue 0,7-5,6°   (mediana 2,4°)  · sat 0,75 · valor 0,43  → carmesí oscuro
#   óxido    hue 18,6-22,3° (mediana 20,7°) · sat 0,92 · valor 0,71  → naranja claro
#
# Separan con más de 12° de margen. Un umbral de rojo genérico NO sirve: la primera versión de
# este módulo usaba proporciones de canal y marcaba el óxido como sangre, que es un acento
# legítimo para el metal según el contrato de prompt de ese canal. La lección que eso dejó es la misma
# que obligó a F4.8: un umbral de color solo significa algo **dentro de una paleta concreta**.
#
# LO QUE DECIDE NO ES EL TOTAL, ES LA CONCENTRACIÓN. Medido sobre las ocho láminas del run y los
# lotes de acento del zoo, con celdas de 16x16 px (256 píxeles máximo):
#
#   láminas legítimas    celda más densa:   0-9 px  (motas sueltas del trazo del grabado)
#   la lámina con sangre celda más densa:  243 px   (la celda prácticamente llena)
#
# El margen real del pico es 3,8x: el peor pico legítimo de las 146 imágenes del repo es 17/256
# (`experimentos/zoo/qwen-lightning-tinta/consistencia-3.png`), no el 9 de este run. La suma va
# sobre ventana DESLIZANTE, no sobre rejilla alineada: una rejilla fija a múltiplos de 16 dejaba
# escapar una mancha de 8x8 a caballo de dos celdas (~2/3 de las posiciones). Con imagen integral
# la ventana se evalúa en cualquier posición al mismo coste.
#
# LA SEGUNDA GUARDA, POR TOTAL, cierra el agujero del pico: la violación real de F2.5 era «charco
# CON SALPICADURAS Y REGUEROS», y medido por inyección sobre una lámina real, un reguero de 3x60
# px o una salpicadura de 100 gotas de 5x5 (2.502 px) **pasan** el pico. Calibración del total
# sobre las 113 láminas de estilo tinta del repo, por modelo:
#
#   qwen (ACTIVO)  peor total legítimo   80 px  ->  margen  3,1x
#   flux                                 62 px  ->         4,0x
#   ideogram                              2 px  ->       125,0x
#   sdxl                                181 px  ->  margen  1,4x   <-- el que aprieta
#
# 250 es el valor más bajo que no da falsos positivos con NINGÚN workflow de ese canal: bajarlo a 160
# bloquearía `experimentos/zoo/sdxl-tinta/consistencia-1.png`, que es una lámina legítima.
# OJO: ese umbral vale para LÁMINAS. Los fotogramas del vídeo montado llegan a ~649 px por el
# reescalado a 1920x1080 y h264; aplicar la guarda al vídeo exige recalibrar.

CLAVE_PERFIL = "lineas_rojas.guardianes_de_color"

# Valores por defecto SOLO de las ventanas de medición, que son geometría del mecanismo y no
# criterio del canal: un canal puede afinarlas, pero si no las declara no está decidiendo nada
# sobre su contenido. Los umbrales y la banda de color NO tienen defecto a propósito — son la
# regla, y la regla es del canal.
VENTANA_FINA_DEF = 16
VENTANA_GRUESA_DEF = 48


class LineaRojaError(RuntimeError):
    """Una lámina cruza una línea roja del canal. No es un aviso: detiene la producción."""


@dataclass(frozen=True)
class Guardian:
    """La regla de color de UN canal. Todo lo que la define sale de su `perfil.json`."""

    nombre: str
    que_evita: str
    hue_max: float
    sat_min: float
    val_min: float
    val_max: float
    umbral_celda: int
    umbral_grueso: int
    umbral_total: int
    ventana_fina: int = VENTANA_FINA_DEF
    ventana_gruesa: int = VENTANA_GRUESA_DEF


_OBLIGATORIOS = (
    "nombre",
    "que_evita",
    "hue_max",
    "sat_min",
    "val_min",
    "val_max",
    "umbral_celda",
    "umbral_grueso",
    "umbral_total",
)


def _falta_declaracion(detalle: str) -> LineaRojaError:
    """El mensaje del fail-closed dice QUÉ declarar, no solo que falta algo."""
    return LineaRojaError(
        f"El canal '{config.CANAL_ACTIVO or '(ninguno)'}' no declara sus guardianes de color: {detalle}\n"
        f"La guarda falla cerrada a propósito: un canal sin guardián tiene que ser una DECISIÓN "
        f"escrita, no un olvido.\n"
        f"Qué hacer: en canales/<id>/perfil.json declara `{CLAVE_PERFIL}` con una lista.\n"
        f"  · Lista VACÍA = este canal no tiene ninguna línea roja de color, y el motivo se escribe al "
        f"lado (por ejemplo, un canal cuyas líneas rojas son de situación y no de color).\n"
        f"  · Con guardianes = un objeto por regla, con {', '.join(_OBLIGATORIOS)}.\n"
        f"    El método para calibrarlos está en el comentario de cabecera de lib/lineas_rojas.py."
    )


def guardianes_del_canal(perfil: dict | None = None) -> list[Guardian]:
    """Los guardianes del canal ACTIVO. Falla cerrada si el perfil no los declara.

    Un canal no puede leer los de otro: la única fuente es el perfil que `config` cargó para
    `CANAL_ACTIVO`, y no hay valor heredado ni global que rellene los huecos.
    """
    if perfil is None and config.CANAL_ERROR:
        # Sin perfil cargado el problema es OTRO, y decir «no declara sus guardianes» mandaría a
        # editar un fichero que quizá ni existe. Se cita el diagnóstico de verdad, que `config` ya
        # tiene escrito. Hoy lo tapa que los entrypoints miren `CANAL_ERROR` antes de llamar aquí,
        # pero eso es suerte del orden de llamada, no una garantía.
        raise LineaRojaError(f"No se puede aplicar la guarda del canal: {config.CANAL_ERROR}")
    # Se navega el perfil a mano y NO con `config._del_canal`, a propósito y por dos razones: aquél
    # devuelve su defecto cuando la clave falta, que es justo la ambigüedad «ausente vs. lista
    # vacía» que esta guarda existe para romper; y no admite inyectar un perfil, que es lo que
    # necesitan las pruebas y lo que `canal_marca.comprueba()` usa para no caer al canal global.
    p = config.CANAL_PERFIL if perfil is None else perfil
    nodo = p.get("lineas_rojas") or {}
    if "guardianes_de_color" not in nodo:
        raise _falta_declaracion(f"falta la clave `{CLAVE_PERFIL}` en su perfil")
    crudos = nodo["guardianes_de_color"]
    if not isinstance(crudos, list):
        raise _falta_declaracion(f"`{CLAVE_PERFIL}` es {type(crudos).__name__} y tiene que ser una lista")

    guardianes = []
    for i, g in enumerate(crudos):
        if not isinstance(g, dict):
            raise _falta_declaracion(f"el guardián #{i + 1} es {type(g).__name__} y tiene que ser un objeto")
        faltan = [k for k in _OBLIGATORIOS if k not in g]
        if faltan:
            raise _falta_declaracion(f"al guardián #{i + 1} le faltan los campos: {', '.join(faltan)}")
        guardianes.append(
            Guardian(
                nombre=str(g["nombre"]),
                que_evita=str(g["que_evita"]),
                hue_max=float(g["hue_max"]),
                sat_min=float(g["sat_min"]),
                val_min=float(g["val_min"]),
                val_max=float(g["val_max"]),
                umbral_celda=int(g["umbral_celda"]),
                umbral_grueso=int(g["umbral_grueso"]),
                umbral_total=int(g["umbral_total"]),
                ventana_fina=int(g.get("ventana_fina", VENTANA_FINA_DEF)),
                ventana_gruesa=int(g.get("ventana_gruesa", VENTANA_GRUESA_DEF)),
            )
        )
    nombres = [g.nombre for g in guardianes]
    repetidos = sorted({n for n in nombres if nombres.count(n) > 1})
    if repetidos:
        # El nombre identifica al guardián en el mensaje de error, así que dos homónimos harían
        # que se publicara la frase del primero para el fallo del segundo. Mejor error temprano.
        raise _falta_declaracion(f"hay guardianes con el mismo `nombre`: {', '.join(repetidos)}")
    return guardianes


def _mide_banda(path: Path, g: Guardian) -> dict:
    """Píxeles en la banda de color del guardián, su concentración máxima y dónde está.

    Hue vectorizado (sin `colorsys` por píxel, inaceptable sobre 1344x768). Solo cuentan los
    píxeles con el rojo dominante: la banda de todos los guardianes conocidos cruza el 0°, que es
    el rojo. Un guardián de otra franja del círculo exigiría generalizar esto, y el día que haga
    falta se verá aquí en vez de dar un resultado silenciosamente vacío.
    """
    import numpy as np
    from PIL import Image

    if not path.is_file():
        raise LineaRojaError(
            f"No se puede revisar {path}: no existe. Una guarda que no puede medir falla "
            "cerrada — la etapa se detiene en vez de dar por buena una lámina sin ver."
        )
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        # `convert("RGB")` DESCARTA el alfa en vez de componer, así que un carmesí totalmente
        # transparente contaba como sangre. Se compone sobre blanco, que es el papel.
        fondo = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(fondo, img.convert("RGBA"))
    arr = np.asarray(img.convert("RGB")).astype(np.float32) / 255.0
    r, gr, b = arr[..., 0], arr[..., 1], arr[..., 2]
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    delta = mx - mn

    dominante = (mx == r) & (delta > 1e-6)
    hue = np.zeros_like(mx)
    with np.errstate(invalid="ignore", divide="ignore"):
        hue[dominante] = (60.0 * ((gr - b) / delta)[dominante]) % 360.0
    sat = np.where(mx > 0, delta / np.maximum(mx, 1e-6), 0.0)

    en_banda = dominante & ((hue <= g.hue_max) | (hue >= 360.0 - g.hue_max))
    mask = en_banda & (sat >= g.sat_min) & (mx >= g.val_min) & (mx <= g.val_max)

    if min(mask.shape) < g.ventana_fina:
        raise LineaRojaError(
            f"{path.name} mide {mask.shape[1]}x{mask.shape[0]} px y no cabe una ventana de "
            f"{g.ventana_fina}x{g.ventana_fina}: la guarda no puede medirla y falla cerrada."
        )

    # Imagen integral: la suma de cualquier ventana sale con cuatro restas.
    integral = np.pad(mask.astype(np.int32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))

    def pico_ventana(w: int):
        if min(mask.shape) < w:
            return 0, None
        s = integral[w:, w:] - integral[:-w, w:] - integral[w:, :-w] + integral[:-w, :-w]
        top = int(s.max())
        y, x = np.unravel_index(int(s.argmax()), s.shape)
        return top, (int(x), int(y), int(x + w), int(y + w))

    pico, caja_fina = pico_ventana(g.ventana_fina)
    pico_grueso, caja_gruesa = pico_ventana(g.ventana_gruesa)

    caja = None
    if pico >= g.umbral_celda:
        caja = caja_fina
    elif pico_grueso >= g.umbral_grueso:
        caja = caja_gruesa

    return {
        "pixeles": int(mask.sum()),
        "pico_celda": pico,
        "pico_grueso": pico_grueso,
        "caja_mancha": caja,
    }


def _veredicto(path: Path, g: Guardian) -> dict:
    """Lo que UN guardián dice de UNA imagen."""
    m = _mide_banda(path, g)
    return {
        "guardian": g.nombre,
        "pixeles_en_banda": m["pixeles"],
        "pico_celda": m["pico_celda"],
        "pico_grueso": m["pico_grueso"],
        "caja_mancha": m["caja_mancha"],
        "pasa": (
            m["pico_celda"] < g.umbral_celda and m["pico_grueso"] < g.umbral_grueso and m["pixeles"] < g.umbral_total
        ),
        "motivo": (
            "mancha compacta"
            if m["pico_celda"] >= g.umbral_celda
            else "reguero o mancha extendida"
            if m["pico_grueso"] >= g.umbral_grueso
            else "salpicadura dispersa"
            if m["pixeles"] >= g.umbral_total
            else ""
        ),
        "umbrales": {
            "celda": g.umbral_celda,
            "grueso": g.umbral_grueso,
            "total": g.umbral_total,
            "ventana_fina_px": g.ventana_fina,
            "ventana_gruesa_px": g.ventana_gruesa,
        },
    }


def revisa(path: str | Path, guardianes: list[Guardian] | None = None) -> dict:
    """Revisa una lámina contra los guardianes del canal. No lanza: quien llama decide.

    Con la lista vacía —un canal sin línea roja de color— pasa y lo dice, en vez de fingir que
    midió algo.
    """
    p = Path(path)
    gs = guardianes_del_canal() if guardianes is None else guardianes
    por_guardian = [_veredicto(p, g) for g in gs]
    fallados = [v for v in por_guardian if not v["pasa"]]
    primero = fallados[0] if fallados else None
    return {
        "archivo": p.name,
        "ruta": str(p),
        "guardianes": len(gs),
        "por_guardian": por_guardian,
        "pasa": not fallados,
        "motivo": primero["motivo"] if primero else "",
        "regla": (
            f"{primero['guardian']}: {next(g.que_evita for g in gs if g.nombre == primero['guardian'])}"
            if primero
            else ("sin guardián de color declarado en el perfil del canal" if not gs else "")
        ),
        # Compatibilidad hacia atrás para los llamadores que leen el veredicto plano: cuando falla,
        # son los números del guardián que falló; cuando pasa, los del primero que mira.
        "pixeles_en_banda": (primero or (por_guardian[0] if por_guardian else {})).get("pixeles_en_banda"),
        "pico_celda": (primero or (por_guardian[0] if por_guardian else {})).get("pico_celda"),
        "pico_grueso": (primero or (por_guardian[0] if por_guardian else {})).get("pico_grueso"),
        "caja_mancha": (primero or (por_guardian[0] if por_guardian else {})).get("caja_mancha"),
    }


def revisa_lote(rutas, guardianes: list[Guardian] | None = None) -> dict:
    """Revisa varias láminas y devuelve el informe agregado."""
    gs = guardianes_del_canal() if guardianes is None else guardianes
    resultados = [revisa(r, gs) for r in rutas]
    fallos = [r for r in resultados if not r["pasa"]]
    # Los umbrales planos solo tienen sentido con UN guardián, que era el caso del primer canal y lo que
    # espera el informe de la marca. Con cero o varios quedan en None y el detalle va por guardián:
    # publicar el umbral «del canal» cuando hay dos reglas distintas sería un número inventado.
    unico = gs[0] if len(gs) == 1 else None
    return {
        "revisadas": len(resultados),
        "fallos": fallos,
        "pasa": not fallos,
        "guardianes": [g.nombre for g in gs],
        "umbrales_por_guardian": {
            g.nombre: {
                "celda": g.umbral_celda,
                "grueso": g.umbral_grueso,
                "total": g.umbral_total,
                "hue_max": g.hue_max,
                "sat_min": g.sat_min,
            }
            for g in gs
        },
        "umbral_celda": unico.umbral_celda if unico else None,
        "umbral_grueso": unico.umbral_grueso if unico else None,
        "umbral_total": unico.umbral_total if unico else None,
        "ventana_fina_px": unico.ventana_fina if unico else None,
        "ventana_gruesa_px": unico.ventana_gruesa if unico else None,
        "detalle": resultados,
    }


def exige(rutas, etapa: str = "images") -> dict:
    """Revisa el lote y **detiene la etapa** si alguna lámina cruza una línea roja del canal.

    Se para aquí a propósito, antes del montaje: una lámina que cruza la línea roja montada en el
    vídeo ya ha costado el tiempo de montaje, y sobre todo hace que el run parezca correcto —el
    `ffprobe` no ve el contenido— cuando no lo es.
    """
    informe = revisa_lote(rutas)
    if not informe["pasa"]:
        # El mensaje enumera SOLO las medidas que fallaron. Antes empezaba siempre por el pico
        # fino, así que un fallo por total salía como «pico 16 … recuadro None» y mandaba al
        # operador a buscar una mancha que no existe.
        def _detalle(f: dict) -> str:
            v = next(x for x in f["por_guardian"] if not x["pasa"])
            u = v["umbrales"]
            partes = [f"{f['archivo']} [{v['guardian']} · {v['motivo']}]"]
            if v["pico_celda"] >= u["celda"]:
                partes.append(
                    f"{v['pico_celda']} px en {u['ventana_fina_px']}x{u['ventana_fina_px']} (umbral {u['celda']})"
                )
            if v["pico_grueso"] >= u["grueso"]:
                partes.append(
                    f"{v['pico_grueso']} px en {u['ventana_gruesa_px']}x{u['ventana_gruesa_px']} (umbral {u['grueso']})"
                )
            if v["pixeles_en_banda"] >= u["total"]:
                partes.append(f"{v['pixeles_en_banda']} px en total (umbral {u['total']})")
            if v["caja_mancha"]:
                partes.append(f"recuadro {v['caja_mancha']}")
            return "  · " + " · ".join(partes)

        lineas = [_detalle(f) for f in informe["fallos"]]
        # La frase que explica QUÉ está mal la pone el canal, no este módulo: es su línea roja.
        reglas = sorted({f["regla"] for f in informe["fallos"] if f["regla"]})
        raise LineaRojaError(
            f"LÍNEA ROJA CRUZADA en la etapa '{etapa}' del canal '{config.CANAL_ACTIVO}': "
            f"{len(informe['fallos'])} de {informe['revisadas']} imágenes la cruzan.\n"
            + "\n".join(lineas)
            + "\n\nRegla del canal: "
            + " · ".join(reglas)
            + f"\n(declarada en canales/{config.CANAL_ACTIVO}/perfil.json → {CLAVE_PERFIL})"
            + "\nQué hacer: regenerar esas imágenes con otra semilla o reencuadre y volver a lanzar la "
            "etapa. NO se sigue al montaje."
        )
    return informe
