r"""Subtítulos del estudio: los ajustes de cada canal, el `.srt` para YouTube y su validación (F2.13, F6.7).

Petición del 24-08: «subtítulos, pero atractivos tipo karaoke», con luz verde explícita al `.srt` aparte. El
karaoke lo pinta hoy el motor de escena en la composición (`lib/escena/linea_tiempo.py` y el CSS del canal), y la etapa
`alinea` escribe con los mismos cues el `.srt` (`lib/escena/etapas.py`). Este módulo es lo que comparten:

- **los ajustes del canal** (`ajustes`): lo del estudio más lo que declara el perfil, sin defectos (F4.9);
- **el reparto** (`personajes`): quién habla en el canal, con su color y su pronombre;
- **el `.srt`** (`recorta_solapes`, `estira_lineas_cortas`, `escribe_srt`) y su validación (`valida_srt`).

**El texto en pantalla es el del guion, nunca el que el reconocedor cree oír.** Del audio solo se extraen *tiempos*;
el emparejamiento por alineación de secuencias vive en `lib/alineacion.py` desde F6.2b.

**Lo que se retiró el 02-10-2026 (F6.7)**: el karaoke quemado del motor de láminas, con su fichero ASS (etiquetas
`\k`, colores por personaje, contorno), el quemado con `libass` y el agrupado de palabras en líneas que lo
alimentaba. Su historia está en el addendum de `doc/02-decisiones-tecnicas.md` (filas 74, 83 y siguientes) y en
`progress/impl_F2.13.md`.

El `.srt` no es redundante con el karaoke: YouTube **indexa** los subtítulos para búsqueda y son accesibilidad,
alcance que un vídeo con el texto pintado encima no da.
"""

import os
import re
from pathlib import Path

from lib import alineacion as _alineacion
from lib.config import (
    ALINEADOR_WORKER,
    CANAL_PERFIL,
    SUBTITLE_LANG,
    VOICE_PYTHON,
    base_del_estudio,
    bloque_del_canal,
)

# La licencia del alineador tal como va en el registro del `.srt`. La escribe la etapa `alinea` del motor de escena
# (`lib/escena/etapas.py`).
LICENCIA_ALINEADOR = "openai/whisper-small — Apache-2.0 (uso solo para marcas de tiempo, no genera contenido)"
# La de sus pesos, como en `THIRD_PARTY_NOTICES.md` (sección 5): llega a `assets.json` con el `.srt` (OC1.4).
URL_ALINEADOR = "https://huggingface.co/openai/whisper-small"


class SubtitulosError(RuntimeError):
    """Fallo de los subtítulos: un perfil a medias o un `.srt` que YouTube Studio no aceptaría."""


# Hasta el 25-09-2026 aquí había un `DEFECTOS` con diez valores, y eran los del primer canal: el segundo se pintaba
# en Georgia cuerpo 60 con los márgenes de un museo medieval sin haberlo decidido nunca
# (`progress/plan_aislar_canales.md`). Ahora cada valor tiene UN dueño y ninguno tiene defecto:
#
# - DEL ESTUDIO, iguales para todos: `datos/base-del-estudio.json → produccion.karaoke`.
# - DEL CANAL, en `perfil.json → subtitulos`: `activos` siempre, y el resto si `activos` es true.
#
# `quemar` y `crf` (el interruptor y la calidad del karaoke quemado) salieron con él en F6.7. La tipografía y los
# márgenes se quedan porque la onda guardada (`lib/onda.py → holgura_con_subtitulos`) mide contra `cuerpo` y
# `margen_inferior_px`. En el motor de escena no entran en el vídeo: el karaoke lo dibuja la escena (fila 249).
#
# `traducciones` (F7.11, fila 265) son los idiomas a los que se traduce el `.srt` del canal: `[]` si a ninguno. La lee
# y la comprueba `traducciones()`.
DEL_ESTUDIO = ("modelo_alineacion",)
DEL_CANAL = (
    "srt",
    "fuente",
    "cuerpo",
    "max_palabras_por_linea",
    "margen_inferior_px",
    "margen_lateral_px",
    "traducciones",
)


# Pronombres con los que un guion en ingles retoma a un personaje. El estudio conoce la GRAMATICA;
# quien es «she» en este canal lo dice el perfil.
PRONOMBRES = frozenset({"he", "she", "they"})


def personajes() -> dict:
    """Quien habla en este canal y de que color se pinta su dialogo. **Lo declara el canal.**

    Petición del 05-09: «a nivel de subtitulos de karaoke, hemos de diferenciar quien habla. Por ejemplo
    cuando habla ollie: Ollie: [su dialogo] y en un color diferente por ejemplo azul y lo mismo con
    Nora con otro color por ejemplo verde como su vestido». Y con una decision al lado que evita el
    trabajo de mas: **una sola voz** —«no nos liemos buscando voces para los personajes»—, asi que
    quien habla se distingue LEYENDO, no oyendo.

    **Sin defecto en el estudio** (F4.9): un canal sin dialogos declara `{}` y eso es una respuesta,
    no un olvido. Heredar el reparto de otro canal pintaria de azul a un personaje que no existe.
    """
    perfil = (CANAL_PERFIL or {}).get("subtitulos")
    if not isinstance(perfil, dict) or "personajes" not in perfil:
        raise SubtitulosError(
            "El perfil del canal no declara `subtitulos.personajes`. Es el reparto que el karaoke "
            "pinta de color: `{}` si este canal no tiene dialogos, o "
            '`{"Ollie": {"color": "#4A90D9"}}` con un color por personaje. No tiene defecto porque '
            "heredar el reparto de otro canal pintaria a personajes que aqui no existen."
        )
    reparto = perfil["personajes"] or {}
    for nombre, ficha in reparto.items():
        color = (ficha or {}).get("color", "")
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            raise SubtitulosError(
                f"El personaje '{nombre}' declara color {color!r} y hace falta un hexadecimal #RRGGBB."
            )
        # El pronombre lo usa quien ATRIBUYE las lineas del guion (`scripts/hablantes.py`), porque
        # «"I know," she said» solo se resuelve sabiendo que Nora es «she». Se valida aqui para que
        # el reparto tenga una sola puerta de entrada y el fallo salte al abrir el perfil, no a mitad
        # de un run.
        if (ficha or {}).get("pronombre") not in PRONOMBRES:
            raise SubtitulosError(
                f"El personaje '{nombre}' no declara `pronombre` "
                f"({' | '.join(sorted(PRONOMBRES))}). Hace falta para atribuir el dialogo que el "
                "guion no firma con un nombre, y es del canal: el estudio no sabe quien es Nora."
            )
    return reparto


# Claves del bloque `subtitulos` del perfil que NO son ajustes de esta función y las lee otra.
# Sin esta lista, `ajustes()` avisaba de que `personajes` «no se está aplicando», que es falso: lo
# lee `personajes()`. Un aviso que miente es peor que no avisar, porque enseña a ignorar los avisos.
LEIDAS_APARTE = frozenset({"personajes"})


def _por_entorno() -> bool | None:
    """`SUBTITULOS` del entorno, que manda para ESTE run: None si no se ha puesto."""
    crudo = os.getenv("SUBTITULOS", "").strip().lower()
    if not crudo:
        return None
    return crudo not in ("0", "false", "no", "off")


def ajustes(perfil: dict | None = None) -> dict:
    """Ajustes de subtítulos del canal activo: lo del estudio más lo que declara el canal, sin defectos.

    Las reglas, compartidas con la música, están en `lib/config.bloque_del_canal`. Lo propio de aquí:
    `SUBTITULOS=1` puede forzarlos en un canal que declara `activos: false`, y entonces también hacen
    falta su tipografía y su sitio en pantalla (antes, un `KeyError` sin explicación).

    `perfil` es el del canal activo si no se pasa otro: el motor de escena (F6.2d) pasa el del episodio.
    """
    return bloque_del_canal(
        ((CANAL_PERFIL if perfil is None else perfil) or {}).get("subtitulos"),
        bloque="subtitulos",
        interruptor="activos",
        base=base_del_estudio()["produccion"]["karaoke"],
        donde_en_la_base="produccion.karaoke",
        del_estudio=DEL_ESTUDIO,
        del_canal=DEL_CANAL,
        que_es=(
            "son su tipografía, su sitio en pantalla y los idiomas a los que se traduce su .srt (`traducciones`: [] "
            'si a ninguno, ["es"] para el español), y heredar los de otro canal es decidir por él'
        ),
        error=SubtitulosError,
        aviso="SUBS",
        leidas_aparte=LEIDAS_APARTE,
        forzado=_por_entorno() is True,
    )


def activa() -> bool:
    """¿Lleva subtítulos este vídeo?

    El perfil decide para el CANAL y la variable `SUBTITULOS` para ESTE run, que es lo que pide
    la aceptación de F2.13: poder quitarlos en un vídeo concreto sin editar el perfil. Se lee de
    forma explícita porque `bool("0")` es `True` y un `SUBTITULOS=0` que activara los subtítulos
    sería peor que no tener la palanca.
    """
    forzado = _por_entorno()
    return forzado if forzado is not None else bool(ajustes()["activos"])


# Un código de idioma ISO 639-1: dos letras en minúscula. Es el que va en el nombre del `.srt` (`subtitulos.es.srt`) y
# el que la declaración de IA sabe nombrar (`lib/publicacion.py → NOMBRE_DEL_IDIOMA`).
_CODIGO_DE_IDIOMA = re.compile(r"[a-z]{2}")


def traducciones(perfil: dict | None = None, *, origen: str) -> list[str]:
    """Los idiomas a los que se traduce el `.srt` del canal (F7.11, fila 265). Los declara el canal, sin defecto.

    `perfil.json → subtitulos.traducciones` es una lista de códigos de dos letras: `[]` si el canal sube solo el `.srt`
    de su guion, `["es"]` si añade otro en español. Está en `DEL_CANAL`, así que un canal que lleva `.srt` y no la
    declara para en `ajustes()`, que dice qué escribir. Un canal sin `.srt` no tiene nada que traducir y devuelve `[]`;
    si aun así declara idiomas, para, porque no habría de dónde sacarlos.

    `origen` es el idioma del `.srt` de origen (`config.SUBTITLE_LANG`): traducir a él no es traducir.
    """
    cfg = ajustes(perfil)
    idiomas = cfg.get("traducciones")
    if not (cfg["activos"] and cfg.get("srt")):
        if idiomas:
            raise SubtitulosError(
                f"`subtitulos.traducciones` declara {idiomas!r}, pero el canal no lleva .srt (`activos` o `srt` en "
                "false): no hay de dónde traducir. Pon `[]` o activa el .srt."
            )
        return []
    if not isinstance(idiomas, list) or not all(isinstance(i, str) and _CODIGO_DE_IDIOMA.fullmatch(i) for i in idiomas):
        raise SubtitulosError(
            f"`subtitulos.traducciones` vale {idiomas!r}: tiene que ser una lista de códigos de idioma de dos "
            'letras en minúscula, como ["es"], o [] si el canal no traduce su .srt.'
        )
    if len(set(idiomas)) != len(idiomas):
        raise SubtitulosError(f"`subtitulos.traducciones` repite un idioma: {idiomas!r}")
    if origen in idiomas:
        raise SubtitulosError(
            f"`subtitulos.traducciones` incluye «{origen}», que es el idioma del .srt de origen: ese no se traduce."
        )
    return list(idiomas)


# Lo menos que puede durar una linea del `.srt` sin que sea un parpadeo: una linea de 50 ms aparece y
# desaparece sin que de tiempo a leerla.
DURACION_MINIMA_S = 0.30


def recorta_solapes(lineas: list[tuple[list[dict], float]]) -> int:
    """Acorta cada línea para que termine cuando empieza la siguiente. Devuelve cuántas tocó.

    El fin de una línea es el fin de su última palabra, y el principio de la siguiente es el
    principio de la suya: las dos las decide el alineador por separado, así que nada garantiza que
    la primera acabe antes de que empiece la segunda. Cuando no lo hace, **el reproductor pinta las dos
    a la vez**, una encima de otra. En el episodio 1 de un canal pasó 3 veces, de 0,05 a 0,30 s — poco
    tiempo, pero es un parpadeo de texto doble justo en el cambio de frase.

    Se recorta el `hasta` de la última palabra y no el fin de la línea: así la línea sigue acabando
    donde acaba su última palabra.
    """
    tocadas = 0
    for (grupo, desplazamiento), (siguiente, desplazamiento_siguiente) in zip(lineas, lineas[1:]):
        fin = grupo[-1]["hasta"] + desplazamiento
        arranque = siguiente[0]["desde"] + desplazamiento_siguiente
        if fin <= arranque:
            continue
        tocadas += 1
        if arranque - (grupo[0]["desde"] + desplazamiento) >= DURACION_MINIMA_S:
            grupo[-1]["hasta"] = arranque - desplazamiento
        else:
            # **Recortar dejaría la línea sin tiempo de leerse, así que se empuja la siguiente.**
            # Son dos casos que acaban igual: líneas CRUZADAS —la siguiente empieza antes que la
            # actual, como `Biscuit sat down.` / `He looked very happy.`, 0,25 s— y solapes tan
            # grandes que al recortar la primera se queda en nada. El segundo se coló en el montaje
            # del 05-09: «Biscuit went with them.» duró **50 ms**, un parpadeo, y lo cazó el auditor
            # del karaoke quemado de entonces. La siguiente se desplaza esa fracción, que no se nota;
            # una línea que parpadea, sí.
            siguiente[0]["desde"] = fin - desplazamiento_siguiente
    return tocadas


def estira_lineas_cortas(lineas: list[tuple[list[dict], float]]) -> int:
    """Alarga hacia atrás las líneas que no llegan al mínimo. Devuelve cuántas tocó.

    **`recorta_solapes` vigila el solape y no la duración**, así que una línea puede quedarse en un
    parpadeo sin que nadie la toque, siempre que no pise a su vecina. Es lo que le pasó a la última
    palabra del grito de Ollie en el episodio de un canal (15-09): `birthday!"` se quedó con una ventana
    de **0,06 s** —de 1:04,460 a 1:04,520— mientras la línea anterior duraba 8,3 s. Se vio en
    el vídeo y pareció que el motor de voz se había comido la palabra; el audio la dice perfectamente
    entre los segundos 60,3 y 63,3. Lo que falla es el reparto de tiempos del alineador.

    **Se roba tiempo a la línea ANTERIOR, no a la siguiente**, y solo si a ella le sobra: adelantar
    el arranque de una línea la deja visible antes de que se pronuncie, que es el error benigno —el
    espectador lee un poco antes—, mientras que retrasar su final la mantiene después de que el
    audio haya seguido, y eso desincroniza el karaoke de lo que se oye.

    Si a la anterior no le sobra, se coge lo que haya: una línea de 0,2 s sigue siendo mejor que una
    de 0,06. Y una línea suelta sin anterior se deja como está, porque no hay de dónde sacar.
    """
    tocadas = 0
    for indice in range(1, len(lineas)):
        grupo, desplazamiento = lineas[indice]
        anterior, desplazamiento_anterior = lineas[indice - 1]
        arranque = grupo[0]["desde"] + desplazamiento
        duracion = grupo[-1]["hasta"] + desplazamiento - arranque
        if duracion >= DURACION_MINIMA_S:
            continue

        inicio_anterior = anterior[0]["desde"] + desplazamiento_anterior
        sobra = (arranque - inicio_anterior) - DURACION_MINIMA_S
        if sobra <= 0:
            continue
        robado = min(DURACION_MINIMA_S - duracion, sobra)
        grupo[0]["desde"] = arranque - robado - desplazamiento
        anterior[-1]["hasta"] = arranque - robado - desplazamiento_anterior
        tocadas += 1
    return tocadas


def texto_para_pintar(texto: str, idioma: str = SUBTITLE_LANG) -> str:
    """La narración tal como se PINTA (`lib/alineacion.texto_para_pintar`), con el idioma del canal activo.

    La regla —sin etiquetas y sin «¡¿» fuera del español— vive en `lib/alineacion.py` desde F6.2b,
    porque el motor de escena cuenta sobre este mismo texto los índices de `hablantes`.
    """
    return _alineacion.texto_para_pintar(texto, idioma)


def _tiempo_srt(segundos: float) -> str:
    horas, resto = divmod(max(0.0, segundos), 3600)
    minutos, seg = divmod(resto, 60)
    return f"{int(horas):02d}:{int(minutos):02d}:{seg:06.3f}".replace(".", ",")


def escribe_srt(lineas: list[tuple[list[dict], float]], destino: Path) -> Path:
    """El `.srt` para YouTube: sin karaoke (el formato no lo tiene), con el texto y sus tiempos."""
    bloques = []
    for numero, (grupo, desplazamiento) in enumerate(lineas, start=1):
        inicio = grupo[0]["desde"] + desplazamiento
        fin = grupo[-1]["hasta"] + desplazamiento
        texto = " ".join(p["palabra"] for p in grupo)
        if grupo[0].get("abre_dialogo") and grupo[0].get("personaje"):
            # El `.srt` no tiene colores, asi que aqui el nombre es lo UNICO que distingue a
            # quien habla. Con mas razon que en el karaoke, que ademas tiene el color.
            texto = f"{grupo[0]['personaje']}: {texto}"
        bloques.append(f"{numero}\n{_tiempo_srt(inicio)} --> {_tiempo_srt(fin)}\n{texto}\n")
    # Se comprueba ANTES de escribir. Al revés —como estaba hasta la auditoría del 10-09— la guarda
    # gritaba pero el fichero inválido se quedaba en `subir-al-canal/`, que es la carpeta que el usuario
    # abre para adjuntarlo en Studio: un .srt que YouTube rechaza es peor que ninguno.
    _comprueba_srt("\n".join(bloques), destino.name)
    destino.write_text("\n".join(bloques), encoding="utf-8")
    return destino


_BLOQUE_SRT = re.compile(
    r"^(?P<n>\d+)\r?\n"
    r"(?P<h1>\d{2}):(?P<m1>\d{2}):(?P<s1>\d{2}),(?P<ms1>\d{3})"
    r" --> "
    r"(?P<h2>\d{2}):(?P<m2>\d{2}):(?P<s2>\d{2}),(?P<ms2>\d{3})\r?\n"
    r"(?P<texto>.+)$",
    re.S,
)


def valida_srt(ruta: Path) -> dict:
    """Comprueba que el `.srt` es de los que YouTube acepta, y falla si no.

    **Por qué existe.** El `.srt` es el único entregable de subtítulos que una persona adjunta a mano
    en Studio (`captions.insert` exige un scope que se descartó el 28-08), así que si sale mal nadie
    se entera hasta que el usuario lo intenta subir. Pasó el 10-09: «Los subtítulos en .ass no me los reconoce,
    tienen que ser en .srt y con tiempos». El `.ass` **no era el fichero para Studio** —era el karaoke
    quemado del motor de láminas, retirado en F6.7—, pero eso no se veía por ninguna parte, así que la
    comprobación se acompañó de que la subida dijera cuál es cuál.

    Lo que exige, que es lo que Studio rechaza cuando falta: numeración desde 1 y consecutiva, tiempos
    `HH:MM:SS,mmm` **con coma** (el punto es formato de otro estándar y se rechaza), fin después de
    inicio, bloques en orden y sin solapes, y **ningún resto de etiquetas ASS** (`{\\k42}`), que serían
    texto visible en pantalla.

    Desde que `escribe_srt` comprueba el TEXTO antes de escribir (10-09), **el pipeline no la llama**:
    es la herramienta para revisar un `.srt` que ya está en disco —el de un run viejo, o el que alguien
    editó a mano—, y así encontró un solape de 68 ms en un run del 07-09. No la podes por muerta:
    `tests/test_srt_adjuntable.py` la ejercita con un control negativo por regla.
    """
    return _comprueba_srt(ruta.read_text(encoding="utf-8-sig"), ruta.name) | {"ruta": str(ruta)}


def _comprueba_srt(texto: str, nombre: str) -> dict:
    """El cuerpo de `valida_srt`, sobre el TEXTO: así se comprueba antes de escribir el fichero."""
    bloques = [b for b in re.split(r"\r?\n\r?\n", texto) if b.strip()]
    if not bloques:
        raise SubtitulosError(f"el .srt {nombre} no tiene ni un bloque: no hay nada que adjuntar en Studio")

    fallos: list[str] = []
    fin_previo = -1.0
    inicio_previo = -1.0
    for esperado, bruto in enumerate(bloques, start=1):
        casa = _BLOQUE_SRT.match(bruto.strip())
        if not casa:
            fallos.append(f"bloque {esperado}: no tiene la forma «número / tiempos / texto» ({bruto.strip()[:60]!r})")
            continue
        if int(casa["n"]) != esperado:
            fallos.append(f"bloque {esperado}: está numerado como {casa['n']}; la numeración va de 1 en 1")
        inicio = int(casa["h1"]) * 3600 + int(casa["m1"]) * 60 + int(casa["s1"]) + int(casa["ms1"]) / 1000
        fin = int(casa["h2"]) * 3600 + int(casa["m2"]) * 60 + int(casa["s2"]) + int(casa["ms2"]) / 1000
        if fin <= inicio:
            fallos.append(f"bloque {esperado}: termina en {fin:.3f} s y empieza en {inicio:.3f} s")
        if inicio < inicio_previo:
            fallos.append(f"bloque {esperado}: empieza en {inicio:.3f} s, antes que el anterior")
        if inicio + 1e-3 < fin_previo:
            fallos.append(f"bloque {esperado}: empieza en {inicio:.3f} s y el anterior acaba en {fin_previo:.3f} s")
        inicio_previo, fin_previo = inicio, fin
    restos = re.findall(r"\{\\[^}]*\}", texto)
    if restos:
        fallos.append(f"quedan {len(restos)} etiqueta(s) de ASS en el texto ({restos[0]!r}): se verían escritas")

    if fallos:
        raise SubtitulosError(f"el .srt {nombre} no lo aceptaría YouTube Studio:\n  - " + "\n  - ".join(fallos[:8]))
    return {"bloques": len(bloques), "hasta_s": round(fin_previo, 3)}


def lee_srt(ruta: Path) -> list[dict]:
    """Los bloques de un `.srt` válido, en orden: `n`, `inicio`, `fin` y `texto` (F7.11).

    Los tiempos se quedan como el texto `HH:MM:SS,mmm` del fichero, sin pasar por segundos: así una traducción lleva
    exactamente los mismos, y compararlos es comparar texto. Para si el `.srt` no es de los que Studio acepta
    (`valida_srt`): no se traduce un fichero roto.
    """
    texto = Path(ruta).read_text(encoding="utf-8-sig")
    _comprueba_srt(texto, Path(ruta).name)
    cues = []
    for bruto in (b for b in re.split(r"\r?\n\r?\n", texto) if b.strip()):
        casa = _BLOQUE_SRT.match(bruto.strip())
        cues.append(
            {
                "n": int(casa["n"]),
                "inicio": f"{casa['h1']}:{casa['m1']}:{casa['s1']},{casa['ms1']}",
                "fin": f"{casa['h2']}:{casa['m2']}:{casa['s2']},{casa['ms2']}",
                "texto": "\n".join(linea.strip() for linea in casa["texto"].strip().splitlines()),
            }
        )
    return cues


def escribe_cues(cues: list[dict], destino: Path) -> Path:
    """Escribe un `.srt` con estos bloques tal cual (`n`, `inicio`, `fin`, `texto`), con el formato de `escribe_srt`.

    Lo usa la traducción (F7.11), que copia los tiempos del `.srt` de origen sin tocarlos. Se comprueba antes de
    escribir, igual que `escribe_srt`: un `.srt` que Studio rechaza no llega a `subir-al-canal/`.
    """
    bloques = [f"{c['n']}\n{c['inicio']} --> {c['fin']}\n{c['texto']}\n" for c in cues]
    _comprueba_srt("\n".join(bloques), Path(destino).name)
    Path(destino).write_text("\n".join(bloques), encoding="utf-8")
    return Path(destino)


def preflight() -> list[dict]:
    """¿Podría esta etapa subtitular AHORA? Lo consume `pipeline.py --check`."""
    checks: list[dict] = []
    if not activa():
        return [
            {
                "nombre": "subtítulos",
                "ok": True,
                "detalle": "desactivados en el perfil del canal (subtitulos.activos = false)",
                "obligatorio": False,
            }
        ]

    ajustes()  # para aquí si el perfil del canal está a medias
    python = Path(VOICE_PYTHON)
    checks.append(
        {
            "nombre": "alineador de subtítulos",
            "ok": python.exists() and ALINEADOR_WORKER.exists(),
            "detalle": (
                f"{ALINEADOR_WORKER.name} sobre .venv-voz"
                if python.exists() and ALINEADOR_WORKER.exists()
                else f"falta el intérprete o el worker (python={python}, worker={ALINEADOR_WORKER})"
            ),
            "obligatorio": True,
        }
    )

    return checks
