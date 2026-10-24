"""Construye la descripcion conforme de un video: declaracion de IA y enlace de afiliado.

## Por que la declaracion se DERIVA y no se teclea

La decision cerrada 7 exige el flag del Art. 50 y una declaracion de IA en cada subida. Escribir esa
declaracion a mano en una constante crea el mismo modo de fallo que la auditoria caza una y otra vez
en los informes: el texto se copia, los modelos cambian y nadie vuelve a leerlo. El dia que la voz
paso de Chatterbox a Kokoro (addendum fila 16), una constante habria seguido diciendo Chatterbox.

Asi que la declaracion se construye leyendo el `assets.json` del run, que es el registro de
procedencia que la decision cerrada 5 ya obliga a tener completo antes de subir: de ahi salen los
tipos de asset y el modelo real de cada uno. **Si el pipeline cambia de modelo, la declaracion cambia
con el, sin que nadie se acuerde de actualizarla.**

## Lo que esta declaracion NO dice

No dice nada sobre las fuentes historicas. Las 7 fichas del canal estan en `solo_citas_verificadas`
—las citas existen y tratan del tema, pero nadie las ha leido—, asi que afirmar «documentado» aqui
seria exactamente la afirmacion que `doc/fuente-de-autoridad.md` prohibe.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Como se nombra cada tipo de asset en la declaracion, por idioma de narracion del canal. El texto
# va en el idioma del ESPECTADOR, no en el del repositorio: es una declaracion legal dirigida a el.
PIEZAS = {
    "en": {
        "audio": "Narration: synthetic voice, no human voice actor",
        "imagen": "Still illustrations: AI-generated",
        "imagen_escena": (
            "Animated scenes: the characters, objects and backgrounds are AI-generated illustrations, "
            "moved by an animation engine"
        ),
        "imagen_camara": "Still illustrations: AI-generated, shown with camera movement",
        # El formato «pizarra» (fila 268, texto firmado el 05-10-2026). El punto final lo pone la viñeta.
        "imagen_pizarra": (
            "Chalkboard drawings: AI-generated illustrations, revealed piece by piece. "
            "The handwriting, numbers and charts are drawn by code, not by AI"
        ),
        "miniatura": "Thumbnail: AI-generated",
        "cinemagraph": "Some shots are animated with AI-generated video",
        "musica": "Background music: AI-generated, original — not library music",
    },
    "es": {
        "audio": "Narración: voz sintética, sin locutor humano",
        "imagen": "Ilustraciones fijas: generadas con IA",
        "imagen_escena": (
            "Escenas animadas: los personajes, los objetos y los fondos son ilustraciones generadas con IA, "
            "movidas por un motor de animación"
        ),
        "imagen_camara": "Ilustraciones fijas: generadas con IA, con movimiento de cámara",
        "imagen_pizarra": (
            "Dibujos de pizarra: ilustraciones generadas con IA que aparecen por partes. "
            "La letra, las cifras y las gráficas las dibuja el código, no la IA"
        ),
        "miniatura": "Miniatura: generada con IA",
        "cinemagraph": "Algunos planos están animados con vídeo generado por IA",
        "musica": "Música de fondo: generada con IA, original — no de biblioteca",
    },
}

ENCABEZADO = {
    "en": "AI DISCLOSURE — this video was produced with generative AI:",
    "es": "DECLARACIÓN DE IA — este vídeo se ha producido con IA generativa:",
}

# Los subtitulos merecen su propia linea porque el dato relevante es el contrario del que se supone:
# el TEXTO es el del guion aprobado y de la IA solo vienen las marcas de tiempo.
NOTA_SUBTITULOS = {
    "en": "Subtitles use the text of the written script; only their timings come from an alignment model.",
    "es": "Los subtítulos usan el texto del guion; de un modelo de alineación solo vienen las marcas de tiempo.",
}

# Un `.srt` traducido (F7.11, fila 265) dice lo contrario que la nota de arriba: su TEXTO sí viene de la IA. Lleva su
# propia línea, una por idioma, con el nombre del idioma de verdad. El texto inglés es el de la fila 268, y el español,
# el que se firmó en la fila 270.
NOTA_TRADUCCION = {
    "en": "{idioma} subtitles: translated from the {origen} script with AI.",
    "es": "Subtítulos en {idioma}: traducidos con IA a partir del guion en {origen}.",
}

# Cómo se nombra cada idioma en la declaración, según el idioma en que va la declaración. Es gramática, no una decisión
# de canal: qué idiomas traduce cada canal lo declara su perfil (`subtitulos.traducciones`). Un idioma que no esté aquí
# para la declaración en vez de dejarla con un código que el espectador no entiende.
NOMBRE_DEL_IDIOMA = {
    "en": {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese"},
    "es": {"en": "inglés", "es": "español", "fr": "francés", "de": "alemán", "it": "italiano", "pt": "portugués"},
}

# Los formatos del catálogo cuya línea de imagen la decide el formato y no las figuras que se mueven. «láminas» y
# «personajes» no están: su línea sigue saliendo de `detalle.actores`, como antes de F7.11, porque es la que no se queda
# corta si un vídeo de láminas lleva un objeto que se mueve.
PIEZA_DEL_FORMATO = {"pizarra": "imagen_pizarra"}

# Orden de lectura: primero lo que un espectador nota antes.
#
# **`cinemagraph` se queda aunque el cinemagraph se retiró en F6.7**: la declaración se deriva del `assets.json` de
# CADA run, y los runs del motor de láminas que llevaron clips de Kaggle los tienen registrados con ese tipo. Sin esta
# pieza, la declaración de uno de ellos los callaría y solo lo diría un aviso, que es la declaración incompleta que
# la decisión 7 no admite. Un run del motor de escena no tiene ningún asset de ese tipo, así que no le cambia nada.
ORDEN = ("audio", "imagen", "cinemagraph", "musica", "miniatura")


def _tiene_modelo(modelo) -> bool:
    """¿Declara este registro un modelo generativo? El montaje lleva «ninguno» y la biblioteca «no aplica»."""
    modelo = (modelo or "").strip()
    return bool(modelo) and not modelo.lower().startswith(("ninguno", "no aplica"))


def _modelos_por_tipo(assets: list[dict]) -> dict[str, list[str]]:
    """Agrupa los modelos reales que aparecen en el assets.json, por tipo de asset."""
    fuera: dict[str, list[str]] = {}
    for a in assets:
        tipo, modelo = a.get("tipo", ""), (a.get("modelo") or "").strip()
        # El montaje se registra como asset de tipo `video` con modelo «ninguno»: es FFmpeg, no
        # generativo, y meterlo en la declaracion seria declarar IA donde no hay.
        if not _tiene_modelo(modelo):
            continue
        fuera.setdefault(tipo, [])
        if modelo not in fuera[tipo]:
            fuera[tipo].append(modelo)
    return fuera


def nombre_del_idioma(codigo: str, en: str) -> str:
    """El nombre del idioma `codigo` tal como se escribe en el idioma `en` («es» en inglés es «Spanish»).

    Para si no lo sabe: una declaración que dijera «es subtitles» no la entiende el espectador, y una que callara la
    traducción se quedaría corta (decisión 7).
    """
    nombre = (NOMBRE_DEL_IDIOMA.get(en) or {}).get(codigo)
    if not nombre:
        raise ValueError(
            f"la declaración de IA no sabe nombrar el idioma '{codigo}' en '{en}': añádelo a NOMBRE_DEL_IDIOMA en "
            "lib/publicacion.py antes de subir un .srt en ese idioma"
        )
    return nombre


def _lineas_de_traduccion(subtitulos: list[dict], idioma: str) -> list[str]:
    """Una línea por idioma de los `.srt` traducidos con IA, en orden de idioma (F7.11, fila 265)."""
    por_idioma: dict[str, str] = {}
    for a in subtitulos:
        detalle = a.get("detalle") or {}
        if detalle.get("traducido_de"):
            por_idioma[str(detalle.get("idioma"))] = str(detalle.get("idioma_origen"))
    return [
        NOTA_TRADUCCION[idioma].format(
            idioma=nombre_del_idioma(destino, idioma), origen=nombre_del_idioma(origen, idioma)
        )
        for destino, origen in sorted(por_idioma.items())
    ]


def declaracion_de_ia(run_dir: str | Path, idioma: str) -> tuple[str, list[str]]:
    """Devuelve (texto de la declaracion, avisos) leyendo el assets.json del run.

    `idioma` es OBLIGATORIO y sin valor por defecto a proposito. La auditoria de F3.3 cazo que tener
    un defecto aqui («en») distinto del de `lib/config.py` («es») abria un fallo silencioso: con
    `IDIOMA_NARRACION` puesto, la narracion salia en un idioma y esta declaracion legal en otro **sin
    disparar el aviso**, porque el valor que llegaba si estaba traducido. Quien llama resuelve el
    idioma con `lib.config.NARRATION_LANG`, que aplica la precedencia entorno > perfil > defecto.

    Si el idioma del canal no esta traducido aqui, cae a ingles y lo avisa: es mejor una declaracion
    en ingles con un aviso que ninguna declaracion, porque sin ella la decision 7 se queda sin
    cumplir —y desde F2.16, sin red, porque Kokoro no marca el audio como sintetico.
    """
    avisos: list[str] = []
    if idioma not in PIEZAS:
        avisos.append(
            f"la declaración de IA no está traducida al idioma del canal ('{idioma}'): se emite en "
            "inglés. Traducirla es un cambio de una línea en lib/publicacion.py"
        )
        idioma = "en"

    ruta = Path(run_dir) / "assets.json"
    if not ruta.exists():
        raise FileNotFoundError(f"no hay assets.json en {run_dir}: la declaración de IA se deriva de él, no se teclea")
    assets = json.loads(ruta.read_text(encoding="utf-8")).get("assets", [])
    por_tipo = _modelos_por_tipo(assets)
    # **Un vídeo del motor de escena no son ilustraciones fijas** (auditoría de F6.2d, recomendación 5): sus imágenes
    # de IA (personajes, objetos, fondos) se mueven en pantalla. Se sabe por el propio registro: el vídeo del run
    # (`provenance._video_entry`) declara `detalle.motor = "escena"` cuando lo hizo ese motor. Sin eso —el montaje de
    # siempre— la línea sigue siendo la de las láminas fijas.
    de_escena = [
        a.get("detalle") or {}
        for a in assets
        if isinstance(a, dict) and a.get("tipo") == "video" and (a.get("detalle") or {}).get("motor") == "escena"
    ]
    # **Y uno sin ninguna figura que se mueva tampoco son escenas animadas** (formato «láminas», F6.8): son las
    # ilustraciones fijas con la cámara moviéndose sobre ellas. Lo dice el montaje (`detalle.actores`). Si no lo dice
    # (un montaje anterior a F6.8), se declara lo que más mueve, las escenas animadas: es la declaración que no se queda
    # corta.
    solo_camara = bool(de_escena) and all(d.get("actores") == 0 for d in de_escena)
    pieza_de_imagen = "imagen_camara" if solo_camara else "imagen_escena" if de_escena else "imagen"
    # **Y el formato del vídeo, si el montaje lo dice** (F7.11, fila 268). Una pizarra tampoco son láminas con
    # cámara: sus ilustraciones aparecen por partes y la letra y las gráficas las dibuja el código. Su línea manda solo
    # si ninguna figura se mueve; con alguna, se queda la de escenas animadas, que es la que no se queda corta. Un
    # montaje anterior a F7.11 no lleva `formato`, y su declaración es la de siempre.
    formatos = {d.get("formato") for d in de_escena}
    if solo_camara and len(formatos) == 1 and next(iter(formatos)) in PIEZA_DEL_FORMATO:
        pieza_de_imagen = PIEZA_DEL_FORMATO[next(iter(formatos))]
    from lib.escena.ajustes import FORMATOS

    desconocidos = sorted(f for f in formatos if f is not None and f not in FORMATOS)
    if desconocidos:
        avisos.append(
            f"el vídeo dice que su formato es {desconocidos} y el catálogo no lo conoce (lib/escena/ajustes.py → "
            "FORMATOS): la declaración ha elegido su línea de imagen por las figuras que se mueven"
        )

    # QUE se declara sale del assets.json; los NOMBRES de modelo se quedan fuera del texto a
    # proposito, por dos razones. Una: el Art. 50 obliga a declarar que el contenido es generado,
    # no a publicar el escandallo tecnico. Dos, y es la que decidio: los nombres del assets.json
    # estan escritos en español —«voz mix_onyx_lewis», «8 pasos»— y esta declaracion la lee un
    # espectador en ingles. Traducirlos seria inventar sobre un registro de procedencia. El
    # escandallo completo sigue donde debe estar, en `assets.json` de cada run.
    lineas = [ENCABEZADO[idioma]]
    for tipo in ORDEN:
        if tipo in por_tipo:
            pieza = pieza_de_imagen if tipo == "imagen" else tipo
            lineas.append(f"• {PIEZAS[idioma][pieza]}.")
    # Los subtítulos son de dos clases (F7.11): los del guion, con los tiempos de un alineador, y los traducidos con
    # IA (`detalle.traducido_de`, que escribe `lib/traduccion.py`). Cada clase lleva su línea. Un run anterior solo
    # tiene la primera, así que su declaración no cambia.
    subtitulos = [
        a for a in assets if isinstance(a, dict) and a.get("tipo") == "subtitulos" and _tiene_modelo(a.get("modelo"))
    ]
    if any(not (a.get("detalle") or {}).get("traducido_de") for a in subtitulos):
        lineas.append(NOTA_SUBTITULOS[idioma])
    lineas += _lineas_de_traduccion(subtitulos, idioma)

    # Un tipo con modelo que no sabemos nombrar no se traga en silencio: se avisa, porque una
    # declaracion incompleta es peor que ausente — afirma haber declarado todo.
    # `video` ya NO esta exento: el montaje con FFmpeg no llega hasta aqui —su modelo empieza por
    # «ninguno» y `_modelos_por_tipo` lo filtra—, asi que un asset de tipo `video` que SI traiga
    # modelo generativo es exactamente el caso que hay que cantar. Hueco cazado en la auditoria.
    for tipo in por_tipo:
        if tipo not in ORDEN and tipo != "subtitulos":
            avisos.append(
                f"el assets.json trae un asset de tipo '{tipo}' generado por "
                f"{por_tipo[tipo]} y la declaración no sabe nombrarlo: añádelo a PIEZAS"
            )

    if len(lineas) == 1:
        raise ValueError(
            "el assets.json no declara ningún modelo generativo: revisa el run antes de subir, "
            "porque la declaración de IA quedaría vacía"
        )
    return "\n".join(lineas), avisos


def descripcion_conforme(
    base: str,
    run_dir: str | Path,
    perfil: dict,
    idioma: str,
) -> tuple[str, list[str]]:
    """Monta la descripcion final: la del guion, la declaracion de IA y el afiliado si lo hay.

    **EL MVP NO LLEVA AFILIACION**, por la decision del 30-08 (addendum filas 32 y 33): sale
    del alcance del MVP y pasa a las versiones finales, con la instruccion expresa de no reflotarla.
    Eso deroga **para el MVP** la decision cerrada 11 —«enlace de afiliado desde el video 1»—, que
    ademas era una de tres afirmaciones que no podian ser ciertas a la vez, con el aplazamiento del
    28-08 y el «Hecho cuando» del Sprint 4.

    Asi que la ausencia de enlace **no es una anomalia: es el estado normal del MVP**, y por eso el
    aviso lo dice en vez de sonar a alarma. **Este codigo se queda a proposito** aunque hoy no se use:
    no estorba, no se ejecuta sin enlace, y el dia que se retome basta rellenar
    `perfil.json → publicacion.afiliacion` para que la descripcion lo incluya sola.
    """
    # El idioma NO se rededuce del perfil: lo resuelve `lib.config` y lo pasa quien llama, para que
    # los overrides del `.env` valgan aqui igual que en la voz y en los subtitulos.
    declaracion, avisos = declaracion_de_ia(run_dir, idioma)

    bloques = [base.strip()] if base.strip() else []
    bloques.append(declaracion)

    afiliacion = (perfil.get("publicacion") or {}).get("afiliacion")
    if afiliacion:
        bloques.append(str(afiliacion).strip())
    else:
        avisos.append(
            "sin enlace de afiliado, que es LO NORMAL: el canal no lo declara. No bloquea nada "
            "y no hay que hacer nada. Si algún día lo quieres, el enlace va en "
            "perfil.json → publicacion.afiliacion y este aviso desaparece solo"
        )

    return "\n\n".join(bloques), avisos


# ------------------------------------------------------------------ el título y la descripción traducidos (fila 285)
# Decisión del 07-10-2026: el LEEME lleva también el título y la descripción en español, versión SEO, para pegarlos
# a mano en Studio (Subtítulos → Añadir idioma → «Título y descripción»). **No se suben por la API**: harían falta
# `localizations`, y la fila 285 no amplía el scope de OAuth.
#
# Los idiomas los declara el canal en `perfil.json → publicacion.metadatos_traducidos`, con códigos de dos letras.
# **Un canal que no la declara no lleva versión traducida y no se le exige nada**: es la subida de siempre, y su LEEME
# sale igual byte a byte. Los textos los escribe el guionista en `slides.json`, en tres campos por idioma:
# `title_<idioma>`, `description_<idioma>` (con los mismos marcadores que la original) y `capitulos[].titulo_<idioma>`.
CLAVE_METADATOS_TRADUCIDOS = "metadatos_traducidos"

_CODIGO_DE_IDIOMA = re.compile(r"[a-z]{2}")
_MARCADOR = re.compile(r"<<[A-Z_]+>>")


class ErrorDeMetadatos(ValueError):
    """La versión traducida del título o de la descripción no está lista: el mensaje dice qué escribir y dónde."""


def campo_traducido(campo: str, idioma: str) -> str:
    """El nombre del campo de `slides.json` con la versión de `campo` en `idioma`: `title` y `es` dan `title_es`."""
    return f"{campo}_{idioma}"


def idiomas_de_los_metadatos(perfil: dict, *, origen: str) -> list[str]:
    """Los idiomas a los que el canal traduce su título y su descripción (fila 285), o `[]` si no lo declara.

    `origen` es el idioma del título y de la descripción originales (`config.NARRATION_LANG`): traducir a él no es
    traducir. Para si la declaración no se entiende, o si un idioma no tiene escrita la declaración de IA (`PIEZAS`)
    o su nombre en el LEEME (`NOMBRE_DEL_IDIOMA`): la descripción traducida lleva la declaración en su idioma.
    """
    valor = (perfil.get("publicacion") or {}).get(CLAVE_METADATOS_TRADUCIDOS)
    if valor is None:
        return []
    donde = f"perfil.json → publicacion.{CLAVE_METADATOS_TRADUCIDOS}"
    if not isinstance(valor, list) or not all(isinstance(i, str) and _CODIGO_DE_IDIOMA.fullmatch(i) for i in valor):
        raise ErrorDeMetadatos(
            f"{donde} vale {valor!r}: tiene que ser una lista de códigos de idioma de dos letras en minúscula, como "
            '["es"]. Si el canal no traduce su título y su descripción, se quita la clave.'
        )
    if len(set(valor)) != len(valor):
        raise ErrorDeMetadatos(f"{donde} repite un idioma: {valor!r}")
    if origen in valor:
        raise ErrorDeMetadatos(f"{donde} incluye «{origen}», que es el idioma del título y la descripción originales")
    for idioma in valor:
        if idioma not in PIEZAS or idioma not in NOMBRE_DEL_IDIOMA["es"]:
            raise ErrorDeMetadatos(
                f"{donde} pide «{idioma}» y lib/publicacion.py no tiene escrita la declaración de IA en ese idioma "
                "(PIEZAS, ENCABEZADO y las notas) o su nombre (NOMBRE_DEL_IDIOMA): la descripción traducida la lleva"
            )
    return list(valor)


def faltan_metadatos(slides_json: dict, idiomas: list[str]) -> list[str]:
    """Lo que le falta a `slides.json` para la versión traducida: una línea por campo, que dice qué escribir."""
    fallos: list[str] = []
    for idioma in idiomas:
        nombre = nombre_del_idioma(idioma, "es")
        for campo, que in (
            ("title", f"el título en {nombre}, versión SEO"),
            ("description", f"la descripción en {nombre}, con los mismos marcadores que `description`"),
        ):
            clave = campo_traducido(campo, idioma)
            if not isinstance(slides_json.get(clave), str) or not slides_json[clave].strip():
                fallos.append(f"falta `{clave}`: {que}")
        clave = campo_traducido("titulo", idioma)
        for numero, capitulo in enumerate(slides_json.get("capitulos") or [], start=1):
            capitulo = capitulo if isinstance(capitulo, dict) else {}
            if not isinstance(capitulo.get(clave), str) or not capitulo[clave].strip():
                titulo = capitulo.get("titulo", "?")
                fallos.append(f"al capítulo {numero} («{titulo}») le falta `{clave}`: su frase SEO en {nombre}")
    return fallos


def exige_metadatos_traducidos(slides_json: dict, perfil: dict, *, origen: str) -> list[str]:
    """Los idiomas traducidos del canal, si `slides.json` los trae todos. Para si no, ANTES de gastar cuota.

    Es el hermano de `lib/traduccion.exige_al_dia` para el `.srt`: la subida lo llama antes de componer la descripción
    y de pedir el token. Un canal que no declara traducciones devuelve `[]` sin mirar el `slides.json`.
    """
    idiomas = idiomas_de_los_metadatos(perfil, origen=origen)
    fallos = faltan_metadatos(slides_json, idiomas)
    if fallos:
        raise ErrorDeMetadatos(
            f"no se sube nada, y no se ha gastado cuota: el canal traduce su título y su descripción a {idiomas!r} "
            f"(perfil.json → publicacion.{CLAVE_METADATOS_TRADUCIDOS}) y al slides.json del run le falta:\n  - "
            + "\n  - ".join(fallos)
        )
    return idiomas


def descripciones_traducidas(
    slides_json: dict, *, run_dir: str | Path, perfil: dict, idiomas: list[str]
) -> tuple[dict[str, dict], list[str]]:
    """El título y la descripción final de cada idioma traducido, para el LEEME, y los avisos.

    La descripción es la del guion ya compuesta (`scripts/compone_descripcion.py`) más la declaración de IA **en su
    idioma**, la misma que lleva la original: la lee quien ve la página en ese idioma (decisión 7). Para si todavía
    lleva un marcador sin sustituir, que es el texto de relleno que `youtube_client.revisa_descripcion` no deja subir.
    """
    fuera: dict[str, dict] = {}
    avisos: list[str] = []
    for idioma in idiomas:
        base = slides_json.get(campo_traducido("description", idioma)) or ""
        presentes = sorted(set(_MARCADOR.findall(base)))
        if presentes:
            raise ErrorDeMetadatos(
                f"`{campo_traducido('description', idioma)}` todavía lleva {', '.join(presentes)} sin sustituir: "
                "compón la descripción (scripts/compone_descripcion.py) antes de escribir el LEEME"
            )
        texto, suyos = descripcion_conforme(base=base, run_dir=run_dir, perfil=perfil, idioma=idioma)
        fuera[idioma] = {"titulo": slides_json[campo_traducido("title", idioma)].strip(), "descripcion": texto}
        avisos += [a for a in suyos if a not in avisos]
    return fuera, avisos


def descripcion_del_leeme(run_dir: str | Path) -> str | None:
    """La descripción original que enseña el LEEME que ya hay en el run, o `None` si no hay LEEME que leer.

    La guarda la subida al escribirlo, y es la que se subió: sirve para comprobar que un LEEME rehecho enseña la misma.
    """
    import html as _html

    from lib.config import dir_subir_al_canal

    try:
        texto = (dir_subir_al_canal(run_dir) / "LEEME.html").read_text(encoding="utf-8")
    except OSError:
        return None
    hallado = re.search(r'<textarea id="d" rows="\d+" readonly>(.*?)</textarea>', texto, re.S)
    return _html.unescape(hallado.group(1)) if hallado else None


def _seccion_traducida(traducidas: dict[str, dict] | None) -> str:
    """La parte del LEEME con el título y la descripción traducidos, para copiar. Vacía si el canal no los declara.

    Empieza por un salto de línea y no lo deja fuera: así un LEEME sin ella es byte a byte el de antes de la fila 285.
    """
    partes = []
    for idioma, textos in (traducidas or {}).items():
        nombre = nombre_del_idioma(idioma, "es")
        ident = _e(idioma)
        partes.append(
            f"""
<h2>Título y descripción en {_e(nombre)} (SEO)</h2>
<p>Se pegan a mano en Studio: <b>Subtítulos → Añadir idioma → {_e(nombre.capitalize())}</b>, en «Título y descripción».
No se suben por la API, como los <code>.srt</code>.</p>
<h3>Título en {_e(nombre)}</h3>
<textarea id="t-{ident}" rows="2" readonly>{_e(textos["titulo"])}</textarea>
<button onclick="c('t-{ident}')">copiar el título en {_e(nombre)}</button>
<h3>Descripción en {_e(nombre)}</h3>
<textarea id="d-{ident}" rows="14" readonly>{_e(textos["descripcion"])}</textarea>
<button onclick="c('d-{ident}')">copiar la descripción en {_e(nombre)}</button>"""
        )
    return "".join(partes)


def _seccion_a_mano(a_mano: dict | None) -> str:
    """Los pasos para subir el vídeo a mano en Studio (OC1.8). Vacía sin `a_mano`, y así la página es la de siempre.

    Son los campos que la subida por la API rellena sola (`youtube_client.upload_video`): privado, la declaración de
    contenido sintético, la audiencia y la categoría del perfil. Y la miniatura y los `.srt`, que aquí van a mano.
    """
    if not a_mano:
        return ""
    ninos = "sí" if a_mano["hecho_para_ninos"] else "no"
    return f"""<h2>Cómo subirlo a mano en Studio</h2>
<p>El motor no ha hablado con YouTube: la subida por la API está apagada (<code>YOUTUBE_SUBIDA_API</code> vacío en el
<code>.env</code>). Si quieres que suba él, la guía es <code>docs/youtube-upload.md</code>.</p>
<ol>
 <li><b>Primero, privado.</b> Sube <code>final.mp4</code> en
 <a href="https://studio.youtube.com" target="_blank">YouTube Studio</a>, en tu canal, y déjalo en <b>Privado</b> hasta
 haberlo revisado. Publicarlo es otra decisión, y es tuya.</li>
 <li><b>Título y descripción</b>: cópialos de abajo. La descripción lleva al final la declaración de IA: no la
 quites.</li>
 <li><b>Contenido alterado o sintético: sí.</b> La voz y las imágenes están generadas con IA. Es lo mismo que declara
 la subida por la API (<code>containsSyntheticMedia</code>).</li>
 <li><b>Audiencia</b>: <b>{ninos}</b> es contenido creado para niños, como declara el perfil del canal
 (<code>publicacion.hecho_para_ninos</code>).</li>
 <li><b>Categoría</b>: {_e(a_mano["categoria"])}, la del perfil (<code>publicacion.categoria_youtube</code>).</li>
 <li><b>Miniatura</b>: <code>thumbnail.png</code>. Studio solo deja poner una miniatura propia si el canal está
 verificado por teléfono.</li>
 <li><b>Subtítulos</b>: cada <code>.srt</code> de la tabla, con su idioma (Subtítulos → Añadir idioma → Subir
 archivo, con tiempos).</li>
</ol>
"""


def guia_de_subida(
    run_dir: str | Path,
    *,
    titulo: str,
    descripcion: str,
    video_id: str = "",
    pendiente_a_mano: list[dict] | None = None,
    incidencias: dict | None = None,
    traducidas: dict[str, dict] | None = None,
    a_mano: dict | None = None,
) -> Path:
    """Escribe `subir-al-canal/LEEME.html`: qué hay en la carpeta y qué hacer con cada cosa.

    **Por qué existe.** La carpeta se pidió el 10-09 —«una carpeta que diga "subir al canal", y
    todos los assets que son para subir a YT colocarlos allí»— después de buscar el `.srt` en
    `subtitulos/` y encontrar el `.ass`, que Studio no acepta. Una carpeta ordenada arregla dónde
    están los archivos; lo que no arregla es **cuál es cuál**, y eso es justo lo que le costó la
    vuelta. Así que la carpeta se explica a sí misma, y en el formato que pide la convención del
    proyecto para lo que toca una persona: una página que se abre con doble clic, con el título y la
    descripción en un cuadro con botón de copiar.

    No decide nada ni sube nada: es el índice de lo que ya produjeron las etapas.

    `traducidas` es lo que devuelve `descripciones_traducidas`: el título y la descripción de cada idioma que el canal
    declara (fila 285). Sin ellas, la página es la de siempre.

    `a_mano` lo pasa la subida a mano (OC1.8): la audiencia y la categoría del canal, de
    `youtube_client.campos_de_studio`. Con él, la página lleva los pasos para subirlo en Studio. Sin él, es la de
    siempre byte a byte.
    """
    from lib.config import DIR_SUBIR_AL_CANAL, dir_subir_al_canal

    destino = dir_subir_al_canal(run_dir, crear=True)
    miniatura = (
        "Studio → Miniatura: súbela tú (los pasos, abajo)."
        if a_mano
        else "Studio → Miniatura. La pone el pipeline al subir; esta es la copia local."
    )
    piezas = [
        ("final.mp4", "el vídeo", f"Se sube tal cual. {_que_lleva_el_video(run_dir)}"),
        ("thumbnail.png", "la miniatura", miniatura),
        *_filas_de_srt(run_dir, destino),
    ]
    filas = []
    for nombre, que, como in piezas:
        ruta = destino / nombre
        marca = "" if ruta.exists() else " <span class='falta'>(no está en este run)</span>"
        tamano = f"{ruta.stat().st_size / 1e6:.1f} MB" if ruta.exists() else "—"
        filas.append(
            f"<tr><td><code>{_e(nombre)}</code>{marca}</td><td>{_e(que)}</td>"
            f"<td class='num'>{tamano}</td><td>{como}</td></tr>"
        )

    pendientes = "".join(f"<li>{_e(p.get('que', ''))}: {_e(p.get('como', ''))}</li>" for p in (pendiente_a_mano or []))
    # La versión traducida también se hace a mano, así que entra en la lista; el cómo va en su sección, más abajo.
    pendientes += "".join(
        f"<li>título y descripción en {_e(nombre_del_idioma(idioma, 'es'))}: están más abajo, para copiarlos</li>"
        for idioma in (traducidas or {})
    )
    if video_id:
        enlace = (
            f"<p><a href='https://studio.youtube.com/video/{_e(video_id)}/edit' target='_blank'>"
            f"abrir este vídeo en Studio ({_e(video_id)})</a></p>"
        )
    elif a_mano:
        enlace = "<p>Todavía no se ha subido, y lo subes tú: los pasos de Studio están más abajo.</p>"
    else:
        enlace = "<p>Todavía no se ha subido: cuando se suba, aquí aparecerá su enlace de Studio.</p>"
    html = f"""<!doctype html><meta charset="utf-8"><title>Subir al canal — {_e(titulo)}</title>
<style>
 body{{font:15px/1.5 system-ui;margin:32px;max-width:900px}}
 h1{{font-size:22px;margin-bottom:4px}} .sub{{color:#666;margin-top:0}}
 table{{border-collapse:collapse;margin:18px 0;width:100%}}
 td,th{{border:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}}
 th{{background:#f6f6f6}} .num{{text-align:right;white-space:nowrap}}
 .falta{{color:#b00}} code{{background:#f2f2f2;padding:1px 4px;border-radius:3px}}
 .inc{{border-left:4px solid #b00;background:#fff5f5;padding:10px 14px;margin:16px 0}}
 .inc h2{{margin:0 0 6px;color:#b00;font-size:17px}} .inc ul{{margin:6px 0 0 18px}}
 .ok{{border-left:4px solid #2c6a3f;background:#f3faf5;padding:10px 14px;margin:16px 0;color:#2c6a3f}}
 textarea{{width:100%;font:13px ui-monospace,monospace;padding:8px}}
 button{{font:14px system-ui;padding:6px 12px;margin-top:6px;cursor:pointer}}
</style>
<h1>Subir al canal</h1>
<p class="sub">{_e(titulo)}</p>
{enlace}
{_seccion_incidencias(incidencias)}
<table><tr><th>archivo</th><th>qué es</th><th>tamaño</th><th>qué hacer con él</th></tr>{"".join(filas)}</table>
{"<h2>A mano en Studio</h2><ul>" + pendientes + "</ul>" if pendientes else ""}
{_seccion_a_mano(a_mano)}<h2>Título</h2>
<textarea id="t" rows="2" readonly>{_e(titulo)}</textarea>
<button onclick="c('t')">copiar el título</button>
<h2>Descripción</h2>
<textarea id="d" rows="14" readonly>{_e(descripcion)}</textarea>
<button onclick="c('d')">copiar la descripción</button>{_seccion_traducida(traducidas)}
<p class="sub">Lo que NO está aquí: los JSON del run (procedencia, montaje, guion) se quedan en la
carpeta del run porque son su expediente, y los intermedios viven en <code>composicion/</code>,
<code>sonido/</code>, <code>activos/</code>, <code>musica/</code> y <code>subtitulos/</code>.</p>
<script>
 function c(id){{const e=document.getElementById(id);e.select();document.execCommand('copy');
 e.setSelectionRange(0,0);}}
</script>
"""
    salida = destino / "LEEME.html"
    salida.write_text(html, encoding="utf-8")
    print(f"  guía de la carpeta {DIR_SUBIR_AL_CANAL}/: {salida}")
    return salida


def _que_lleva_el_video(run_dir: str | Path) -> str:
    """Si `final.mp4` lleva karaoke quemado y música, leído del run y no supuesto (fila 257, F7.11).

    Hasta F7.11 la guía decía siempre «Ya lleva los subtítulos karaoke quemados y la música», y en un canal sin karaoke
    es falso: va sin karaoke y sus subtítulos son solo los `.srt`. El karaoke sale de la composición que se renderizó
    (su GUION lleva los grupos de karaoke, vacío si el guion va `sin_karaoke`), y la música, de `assets.json`. Lo que no
    se puede leer se dice «sin comprobar» en vez de suponerlo. Nunca lanza: la guía no puede tumbar un run ya hecho.
    """
    from lib.config import composicion_del_run
    from lib.escena import compone

    try:
        karaoke = bool(compone.lee_guion(composicion_del_run(run_dir) / "index.html").get("karaoke"))
        subtitulos = (
            "Lleva los subtítulos karaoke quemados."
            if karaoke
            else "No lleva subtítulos quemados: los subtítulos van solo en los <code>.srt</code>."
        )
    except (OSError, ValueError, AttributeError):  # ErrorDeComposicion y un JSON roto son ValueError
        subtitulos = "Sin comprobar si lleva subtítulos quemados: el run no tiene la composición del motor de escena."
    try:
        assets = json.loads((Path(run_dir) / "assets.json").read_text(encoding="utf-8")).get("assets", [])
        musica = (
            "Lleva la música."
            if any(isinstance(a, dict) and a.get("tipo") == "musica" for a in assets)
            else "No lleva música."
        )
    except (OSError, ValueError, AttributeError, TypeError):
        musica = "Sin comprobar si lleva música: el run no tiene <code>assets.json</code>."
    return f"{subtitulos} {musica}"


def _filas_de_srt(run_dir: str | Path, carpeta: Path) -> list[tuple[str, str, str]]:
    """Una fila de la guía por cada `.srt` de la carpeta: el usuario los adjunta todos a mano en Studio (F7.11).

    Hasta F7.11 había una sola fila, la del primer `.srt` que encontraba. Con la traducción (fila 265) puede haber
    varios, y la fila de cada uno dice su idioma y, si es una traducción, de qué `.srt` sale. Sin ninguno, la fila se
    queda para que se vea que falta.
    """
    from lib.provenance import TRANSLATION_RECORDS_FILENAME

    traducidos: dict[str, str] = {}
    try:
        registros = json.loads((Path(run_dir) / TRANSLATION_RECORDS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        registros = []
    for r in registros if isinstance(registros, list) else []:
        if isinstance(r, dict) and r.get("file"):
            traducidos[Path(str(r["file"])).name] = str(r.get("traducido_de") or "")

    encontrados = sorted(carpeta.glob("subtitulos.*.srt"))
    if not encontrados:
        return [("subtitulos.<idioma>.srt", "los subtítulos", "Studio → Subtítulos → Añadir idioma → Subir archivo.")]
    filas = []
    for srt in encontrados:
        codigo = srt.name.split(".")[1]
        idioma = (NOMBRE_DEL_IDIOMA["es"]).get(codigo, codigo)
        de_donde = (
            f" Es una traducción con IA de <code>{_e(Path(traducidos[srt.name]).name)}</code>, con sus mismos tiempos."
            if traducidos.get(srt.name)
            else ""
        )
        filas.append(
            (
                srt.name,
                f"los subtítulos en {idioma}",
                f"Studio → Subtítulos → Añadir idioma ({_e(idioma)}) → Subir archivo, con tiempos.{de_donde}",
            )
        )
    return filas


def _e(texto) -> str:
    import html as _html

    return _html.escape(str(texto))


# Un recorte por texto que tiró más de esto ya no es «la cola de la frase»: el motor inventó una
# frase entera detrás. Se lista aparte, como aviso menor, no como incidencia.
DIVAGACION_GRANDE_S = 1.0


def incidencias_del_run(run_dir: str | Path) -> dict:
    """Lo que salió PEOR de lo pedido en un run, reunido para que el usuario lo revise en diez minutos.

    **Por qué existe** (12-09, con su go): «el pipeline siempre termina». Ninguna etapa intermedia
    para el episodio; cada pieza probabilística tiene respaldo, el fallo se ANOTA, y la única revisión
    humana es al final sobre el vídeo montado. Esta función es la mitad «se anota»: recoge de la
    procedencia lo que antes mataba el run y ahora se monta con una marca.

    **De dónde lee y qué no inventa.**
    - Voz: `audio/generacion-voz.json`, que es una LISTA que acumula una entrada por pasada —30
      registros para 10 audios en el episodio 2, medido—, así que se queda con el ÚLTIMO registro
      de cada archivo. De él saca `incidencias_no_bloqueantes` (recorte por silencio, sin recorte,
      mejor intento implausible) y los `recortes_por_divagacion` que tiraron más de
      `DIVAGACION_GRANDE_S`.
    - Miniatura: `miniatura.json` si existe: sus `fallos` y su `reportado_no_es_gate`, que la etapa ya
      mide y publica; aquí solo se enlaza.
    - **Narración**: `lib/integridad_narracion.py` compara el guion con lo que se oye en el audio ya
      montado (F5.7). Es lo único de aquí que MIDE en vez de recoger lo que otro anotó, y existe
      porque el defecto que lo motivó —5,6 s de narración borrados el 14-09— no lo anotó nadie: los
      tres gates dieron verde y se encontró escuchando.

    Nunca lanza: un run sin procedencia de voz devuelve listas vacías, que es lo que pasa cuando la
    etapa no ha corrido.
    """
    import json

    run = Path(run_dir)
    # Hasta F6.7 también enumeraba las láminas con cinemagraph (`slides.json → animacion`): salió con el motor de
    # láminas, y en un run del motor de escena la lista era siempre «ninguna».
    fuera: dict = {"voz": [], "divagacion_grande": [], "miniatura": None, "narracion": None}

    registro = run / "audio" / "generacion-voz.json"
    if registro.exists():
        try:
            entradas = json.loads(registro.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            entradas = []
        ultimo: dict[str, dict] = {}
        for e in entradas if isinstance(entradas, list) else []:
            if isinstance(e, dict) and e.get("file"):
                ultimo[Path(e["file"]).name] = e  # el último de cada archivo manda
        for nombre in sorted(ultimo):
            e = ultimo[nombre]
            lamina = nombre.replace("slide-", "").replace(".wav", "")
            for inc in e.get("incidencias_no_bloqueantes") or []:
                if inc.get("respaldo") == "silencio":
                    que = "recortado por SILENCIO: la transcripción no localizó el final del texto"
                elif inc.get("respaldo") == "sin_recorte":
                    que = (
                        "SIN RECORTAR: ni la transcripción ni el silencio dieron un corte; "
                        "puede haber divagación al final"
                    )
                elif inc.get("implausible"):
                    que = f"se montó el mejor de varios intentos aunque {inc.get('implausible')}"
                else:
                    que = "incidencia sin clasificar"
                fuera["voz"].append(
                    {"lamina": lamina, "segmento": inc.get("segmento"), "texto": inc.get("texto", ""), "que_paso": que}
                )
            for rec in e.get("recortes_por_divagacion") or []:
                if float(rec.get("divagacion_s") or 0) >= DIVAGACION_GRANDE_S:
                    fuera["divagacion_grande"].append(
                        {"lamina": lamina, "segmento": rec.get("segmento"), "segundos": rec.get("divagacion_s")}
                    )

    mini = run / "miniatura.json"
    if mini.exists():
        try:
            m = json.loads(mini.read_text(encoding="utf-8"))
            fuera["miniatura"] = {"fallos": m.get("fallos") or [], "reportado": m.get("reportado_no_es_gate")}
        except (OSError, json.JSONDecodeError):
            pass

    # El guion contra lo que se oye. Va envuelto porque esto se llama al cerrar un run que YA
    # terminó: si la comprobación se rompiera, el episodio se quedaría sin su guía de subida.
    try:
        from lib.integridad_narracion import revisa_run

        fuera["narracion"] = revisa_run(run)
    except Exception as e:  # noqa: BLE001 — cualquier fallo aquí es un aviso, nunca una parada
        fuera["narracion"] = {"aviso": f"la comprobación de la narración no pudo correr: {e}"}
    return fuera


def _items_de_narracion(narracion: dict | None) -> list[str]:
    """Las líneas del LEEME que dicen dónde escuchar (F5.7): lámina, minuto y texto.

    **El minuto es lo que convierte «revisa el vídeo» en «escucha el 5:47»**, y por eso se da el del
    vídeo montado cuando `montaje.json` deja calcularlo, no el segundo dentro de la lámina.

    Las faltas van primero y en rojo: son narración perdida. Los sobrantes van después porque son
    otra cosa —divagación que el recorte no cortó— y molestan menos que un agujero. Los que llegan
    aquí ya vienen medidos: el reconocedor repitiéndose se queda fuera, en `descartados`, porque sus
    palabras no caben en su propia ventana (decisión 4 de `lib/integridad_narracion.py`).
    """
    if not narracion:
        return []
    from lib.integridad_narracion import explica

    fuera: list[str] = []
    for f in narracion.get("faltan") or []:
        donde = f"en el vídeo hacia el <b>{_e(f['en_el_video'])}</b>" if f.get("en_el_video") else ""
        cuando = f"segundo {_e(f.get('desde_s'))} de la lámina"
        fuera.append(
            f"<li><b>Lámina {_e(f['lamina'])} — NO SE OYE esto que el guion sí dice</b> ({cuando}"
            f"{', ' + donde if donde else ''}): {_e(explica(f))}.<br><code>{_e(f['texto'])}</code></li>"
        )
    for s in narracion.get("sobran") or []:
        donde = f" (hacia el {_e(s['en_el_video'])})" if s.get("en_el_video") else ""
        # La medición solo se cita si el tramo la trae: `explica()` sin motivo habla de otra cosa.
        medido = f" — {_e(explica(s))}" if s.get("motivo") else ""
        fuera.append(
            f"<li>Lámina {_e(s['lamina'])}{donde}: el audio dice <b>{_e(s['palabras'])} palabras</b> que el "
            f"guion no tiene{medido}.<br><code>{_e(s['texto'][:200])}</code></li>"
        )
    return fuera


def _nota_de_narracion(narracion: dict | None) -> str:
    """Qué se comprobó de la narración y qué no. Va SIEMPRE, haya hallazgos o no.

    Sin esta línea, un run al que la comprobación no le pudo correr —sin alineación, o con el audio
    regenerado después— se leería como un run comprobado y limpio. Decir «no se ha comprobado» es
    información; callarlo es afirmar lo contrario de lo que se sabe.
    """
    if narracion is None:
        return ""
    if not narracion.get("origen"):
        motivo = narracion.get("aviso") or "no hay alineación en el run"
        return f"Narración: <b>sin comprobar</b> ({_e(motivo)})."
    nota = f"Narración: {_e(narracion.get('laminas_comparadas', 0))} lámina(s) comparadas con {_e(narracion['origen'])}"
    descartados = narracion.get("descartados") or []
    if descartados:
        # Se cuentan POR MOTIVO: los dos descartes dicen cosas distintas y meterlos en un solo
        # número obligaría a abrir el JSON para saber cuál es cuál.
        cuenta: dict[str, int] = {}
        for d in descartados:
            cuenta[d.get("veredicto") or "sin_clasificar"] = cuenta.get(d.get("veredicto") or "sin_clasificar", 0) + 1
        dice = {
            "suena_voz": "que el reconocedor no colocó pero donde el audio sí habla",
            "no_es_audio": "que el reconocedor transcribió dos veces: no son audio, son marcas repetidas",
            # F5.9: este descarte SÍ ocupa segundos de audio reales —cabe hablado— y por eso no vale
            # la frase de arriba: lo que se repitió es el texto, no el tiempo.
            "repeticion_del_reconocedor": "cuyo texto ya estaba en la narración de su lámina, dicho una sola vez",
            "sin_clasificar": "sin clasificar",
        }
        partes = [f"{_e(n)} {_e(dice.get(v, v))}" for v, n in sorted(cuenta.items())]
        nota += f", y {_e(len(descartados))} tramo(s) medidos y descartados: {'; '.join(partes)} — no son incidencias"
    if narracion.get("aviso"):
        nota += f". OJO: {_e(narracion['aviso'])}"
    return nota + "."


def avisa_de_narracion(incidencias: dict | None) -> None:
    """Escribe en la consola lo que el audio no dice, al cerrar el run (F5.7).

    El sitio donde esto se decide es el LEEME, que es lo que el usuario abre; esta línea existe para que
    **no haga falta abrirlo** para enterarse de que hay algo que escuchar. No devuelve nada ni
    cambia nada: el pipeline siempre termina (addendum fila 152).
    """
    narracion = (incidencias or {}).get("narracion") or {}
    faltan, sobran = narracion.get("faltan") or [], narracion.get("sobran") or []
    if not faltan and not sobran:
        return
    print(f"\n  [NARRACIÓN] {len(faltan)} tramo(s) que el guion dice y el audio no · {len(sobran)} sobrante(s)")
    for f in faltan:
        donde = f" (vídeo ~{f['en_el_video']})" if f.get("en_el_video") else ""
        print(f"    lámina {f['lamina']}, segundo {f.get('desde_s')}{donde}: «{f['texto'][:70]}»")
    print("    el detalle, en el LEEME de subir-al-canal/")


def _seccion_incidencias(incidencias: dict | None) -> str:
    """El bloque del LEEME que dice qué escuchar antes de subir. En verde si no hay nada."""
    if incidencias is None:
        return ""
    voz = incidencias.get("voz") or []
    div = incidencias.get("divagacion_grande") or []
    mini = incidencias.get("miniatura") or {}
    fallos_mini = mini.get("fallos") or []
    narracion = _items_de_narracion(incidencias.get("narracion"))
    nota = _nota_de_narracion(incidencias.get("narracion"))
    if not voz and not div and not fallos_mini and not narracion:
        return (
            "<div class='ok'><b>Ninguna incidencia.</b> Todos los segmentos de voz se recortaron por texto "
            f"a la primera o con un reintento. {nota}</div>"
        )
    items = list(narracion)
    for v in voz:
        items.append(
            f"<li><b>Lámina {_e(v['lamina'])}, segmento {_e(v['segmento'])}</b> — {_e(v['que_paso'])}"
            f"<br><code>{_e(v['texto'])}</code></li>"
        )
    for d in div:
        items.append(
            f"<li>Lámina {_e(d['lamina'])}, segmento {_e(d['segmento'])}: el recorte por texto tiró "
            f"<b>{_e(d['segundos'])} s</b> de audio inventado detrás de la frase. Conviene oír el corte.</li>"
        )
    for f in fallos_mini:
        items.append(f"<li>Miniatura: {_e(f)}</li>")
    return (
        "<div class='inc'><h2>Esto salió peor de lo pedido — escúchalo antes de subir</h2>"
        "<p>Cada punto es algo que antes del 12-09 habría parado el episodio y ahora se montó y se anotó. "
        "El vídeo está completo; lo que decides es si esto se oye o se rehace.</p>"
        f"<ul>{''.join(items)}</ul>"
        f"<p class='sub'>{nota}</p></div>"
    )
