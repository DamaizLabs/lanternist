"""Subida a YouTube: SIEMPRE borrador privado, SIEMPRE con el flag del Art. 50.

## Dos cosas que aqui no son parametros

**La visibilidad.** La decision cerrada 2 hace el gate 2 estructural: nada se publica sin un clic
humano. Por eso `privacyStatus` no es un argumento de esta funcion — es la constante `VISIBILIDAD`.
Un parametro se puede pasar mal desde cualquier sitio; una constante hay que venir a cambiarla aqui,
donde esta escrito por que no se debe.

**El flag del Art. 50.** `status.containsSyntheticMedia` va a `True` siempre, y no porque sea
prudente: desde F2.16 es la UNICA garantia de la decision cerrada 7. Chatterbox marcaba el audio con
`perth`; Kokoro no marca nada. Si esta declaracion falla, no hay red debajo.

## El limite medido de los subtitulos

El `.srt` del run **no se puede subir con nuestros permisos**. `captions.insert` exige
`youtube.force-ssl` o `youtubepartner`, y el token del `.env` tiene `youtube.upload` +
`yt-analytics.readonly`: medido el 28-08, `captions.list` responde 403 `insufficientPermissions`.
Ampliar el scope es decision del usuario y no es gratis —`force-ssl` da escritura total sobre la cuenta,
incluido borrar videos, sobre un pipeline cuya lista negra prohibe justamente tocar visibilidad—, asi
que esta funcion **senala el `.srt` en su resultado** para adjuntarlo a mano en Studio.
"""

from __future__ import annotations

import os
from pathlib import Path

import requests

from lib.config import (
    CANAL_ACTIVO,
    CATEGORIA_YOUTUBE,
    HECHO_PARA_NINOS,
    NARRATION_LANG,
    YOUTUBE_API_KEY,
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_REFRESH_TOKEN,
)

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
# El host de SUBIDA, no el de API. El fork traía `www.googleapis.com/youtube/v3/thumbnails/set` y
# eso NO acepta cuerpo de imagen: responde 400 `mediaBodyRequired`. El bug estuvo tapado hasta el
# 28-08 porque antes se llegaba primero al 403 de «canal sin verificar»; en cuanto se verificó el
# teléfono, el 403 se convirtió en el 400 que había debajo. Confirmado en la referencia de
# `thumbnails.set`, que documenta exactamente esta URL.
THUMBNAIL_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"

# No es un valor por defecto: es la decision cerrada 2. Ver el docstring del modulo.
VISIBILIDAD = "private"

# Los nombres legibles de las categorías de vídeo de YouTube (`snippet.categoryId`). Son estáticos:
# `videoCategories.list` costaría 1 unidad de cuota por algo que no cambia. Contra esta tabla se valida
# `publicacion.categoria_youtube` del perfil antes de producir. Vivía en el paquete de lectura del
# buscador del estudio (`lib/lectura_youtube/youtube_data.py`) y pasó aquí en OC1.1 (fila 302): la
# subida es su único usuario en la fábrica.
CATEGORY_NAMES = {
    "1": "Film & Animation",
    "2": "Autos",
    "10": "Música",
    "15": "Mascotas",
    "17": "Deportes",
    "19": "Viajes",
    "20": "Gaming",
    "22": "People & Blogs",
    "23": "Comedia",
    "24": "Entretenimiento",
    "25": "Noticias y política",
    "26": "Howto & Style",
    "27": "Educación",
    "28": "Ciencia y tecnología",
    "29": "ONG y activismo",
}

# --- Los campos que Studio pedia a mano (15-09-2026) --------------------------------------------
#
# Tras rellenar a mano los detalles del episodio de un canal: «busca todos los campos que puedas
# implementar y los rellenas tu, y que sea por igual para todos los canales». Estos tres son
# exactamente eso: la postura del ESTUDIO, como `VISIBILIDAD` y el flag del Art. 50, y por eso viven
# aqui y no en un perfil. **No son defectos que tapen una decision de canal** (F4.9): son una
# decision suya, tomada una vez y para todos.
#
# Lo que NO se manda, y por que:
#   · `notifySubscribers` — es parametro de la llamada, no campo, y no hace nada aqui: el video
#     entra PRIVADO, asi que no hay nada que notificar; quien avisa a los suscriptores es Studio el
#     dia que el usuario lo publica.
#   · `status.publishAt` — programar la publicacion es el gate 2 con fecha (decision 2, matizada el
#     30-08). Se rellena por video y con su aprobacion; ponerlo aqui seria publicar por regla.
#   · `localizations` — titulos y descripciones traducidos. Un canal los lleva en espanol (fila 285), pero se
#     pegan a mano en Studio y no se suben por la API.
LICENCIA = "youtube"  # «Licencia estandar de YouTube» en la pantalla de detalles
INSERTABLE = True  # el video se puede incrustar en otras webs: es difusion gratis
ESTADISTICAS_PUBLICAS = True  # el recuento de vistas, visible en la pagina del video


def get_access_token() -> str:
    resp = requests.post(
        TOKEN_ENDPOINT,
        data={
            "client_id": YOUTUBE_CLIENT_ID,
            "client_secret": YOUTUBE_CLIENT_SECRET,
            "refresh_token": YOUTUBE_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _lee_con_api_key(video_id: str) -> dict:
    """Pregunta por el video con la API KEY publica, que no necesita ningun scope.

    Sirve para lo unico que se puede comprobar sin ampliar permisos, y no es poco: **si el video
    saliera aqui, NO seria privado**. `videos.list` con clave devuelve los publicos y los ocultos
    (por eso funcionan los enlaces de «no listado»), y de los privados no devuelve nada. Asi que
    0 items descarta que este publicado. Lo que NO distingue es privado de no listado: para eso
    haria falta el scope `youtube.readonly`, que no tenemos.
    """
    if not YOUTUBE_API_KEY:
        return {"posible": False, "motivo": "no hay YOUTUBE_API_KEY en el .env"}
    r = requests.get(
        VIDEOS_ENDPOINT,
        params={"part": "status", "id": video_id, "key": YOUTUBE_API_KEY},
        timeout=30,
    )
    if r.status_code != 200:
        return {"posible": False, "motivo": f"la API key respondió {r.status_code}"}
    items = r.json().get("items", [])
    return {
        "posible": True,
        "visible_sin_sesion": bool(items),
        "estado_publico": (items[0].get("status", {}) if items else None),
    }


def _hecho_para_ninos() -> bool:
    """La audiencia declarada del canal, validada: un perfil ambiguo NO se interpreta.

    F4.9: este valor era `False` cableado en capa de estudio. Ahora sale del perfil y, si falta o
    no es un booleano, se para — declarar mal la audiencia de un canal no es algo que deba
    resolverse con un defecto, y el error aquí es barato comparado con descubrirlo en Studio.
    """
    v = HECHO_PARA_NINOS
    if not isinstance(v, bool):
        raise RuntimeError(
            f"El perfil de '{CANAL_ACTIVO}' no declara `publicacion.hecho_para_ninos` como "
            f"booleano (vale {v!r}). Es una decisión del canal y el estudio no la rellena: "
            "escríbela como true o false en su perfil.json."
        )
    return v


def _categoria() -> str:
    """La categoría del canal, validada contra las que conoce el estudio. No se interpreta ni se rellena.

    Era «22» fijo para todos los canales. Un id que YouTube no conoce haría fallar la subida con el
    vídeo ya montado, así que se comprueba antes, aquí y en `pipeline.py --check`.
    """
    v = CATEGORIA_YOUTUBE
    if not isinstance(v, str) or v not in CATEGORY_NAMES:
        raise RuntimeError(
            f"El perfil de '{CANAL_ACTIVO}' declara `publicacion.categoria_youtube` = {v!r}, y tiene que ser "
            f"uno de estos ids, como texto: {', '.join(f'{k} ({n})' for k, n in CATEGORY_NAMES.items())}."
        )
    return v


def comprobaciones_del_canal() -> list[dict]:
    """Audiencia y categoría del canal, validadas antes de producir: es donde el error sale barato.

    Las usan `pipeline.py --check` y `scripts/comprueba_canal.py` (antes, `--check` las llevaba dentro y el
    script solo miraba que existieran).
    """
    audiencia_ok = isinstance(HECHO_PARA_NINOS, bool)
    categoria_ok = isinstance(CATEGORIA_YOUTUBE, str) and CATEGORIA_YOUTUBE in CATEGORY_NAMES
    return [
        {
            "nombre": "audiencia declarada del canal",
            "ok": audiencia_ok,
            "detalle": f"publicacion.hecho_para_ninos = {HECHO_PARA_NINOS!r}"
            + ("" if audiencia_ok else " — tiene que ser true o false en el perfil"),
            "obligatorio": True,
        },
        {
            "nombre": "categoría de YouTube del canal",
            "ok": categoria_ok,
            "detalle": f"publicacion.categoria_youtube = {CATEGORIA_YOUTUBE!r}"
            + (f" ({CATEGORY_NAMES[CATEGORIA_YOUTUBE]})" if categoria_ok else " — no es un id de categoría conocido"),
            "obligatorio": True,
        },
    ]


# --- El interruptor de la subida por la API (OC1.8, fila 315) -----------------------------------------------------
#
# El modo de serie es subir a mano en Studio: el primer vídeo de quien instala el motor no puede depender de configurar
# Google Cloud. La subida por la API se enciende con `YOUTUBE_SUBIDA_API=1` en el `.env`, y entonces exige el OAuth del
# propio usuario. La guía de cómo sacarlo va con el motor.
GUIA_DE_LA_SUBIDA = "docs/youtube-upload.md"
ENCENDIDA = "1"


class SubidaNoConfigurada(RuntimeError):
    """El `.env` pide algo que la subida no puede hacer. El mensaje dice qué escribir y dónde se explica.

    Es una negativa prevista y no un fallo: `pipeline.py` la imprime sin traza, como `MotorRetirado`.
    """


def subida_por_la_api() -> bool:
    """¿Sube el motor el vídeo por la API? Vacía, no: se sube a mano en Studio. Con `ENCENDIDA`, sí.

    Para en los dos casos que no se pueden cumplir, y nunca se salta en silencio:

    - **un valor que no se entiende** («si», «true», «0»): adivinar qué quiso decir sería decidir por el usuario si su
      vídeo sale del PC;
    - **la API encendida sin el OAuth completo**: dice qué variable falta.

    Lee `lib.config` en cada llamada, no al importar, para que una prueba pueda cambiar el modo.
    """
    from lib import config

    valor = config.YOUTUBE_SUBIDA_API
    if valor not in ("", ENCENDIDA):
        raise SubidaNoConfigurada(
            f"YOUTUBE_SUBIDA_API vale {valor!r} en el .env, y solo admite dos valores: vacío, para subir el vídeo a "
            f"mano en Studio, que es lo de serie, o {ENCENDIDA}, para que lo suba el motor por la API con tu OAuth "
            f"({GUIA_DE_LA_SUBIDA})."
        )
    if not valor:
        return False
    faltan = [nombre for nombre in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET") if not getattr(config, nombre)]
    if not config.YOUTUBE_REFRESH_TOKEN:
        variable = config.en_el_perfil(config.CANAL_PERFIL, "publicacion.refresh_token_env")
        faltan.append(
            variable
            if isinstance(variable, str) and variable
            else "el token del canal (`publicacion.refresh_token_env`)"
        )
    if faltan:
        raise SubidaNoConfigurada(
            f"YOUTUBE_SUBIDA_API={ENCENDIDA} enciende la subida por la API, y al .env le falta {', '.join(faltan)}. "
            f"No se sube nada, y tampoco se salta: completa tu OAuth ({GUIA_DE_LA_SUBIDA} explica cómo sacar cada "
            "valor) o deja YOUTUBE_SUBIDA_API vacío, y el run dejará el vídeo listo para subirlo a mano en Studio."
        )
    return True


def campos_de_studio() -> dict:
    """La audiencia y la categoría del canal, validadas, para quien sube a mano: las mismas que manda `upload_video`."""
    categoria = _categoria()
    return {"hecho_para_ninos": _hecho_para_ninos(), "categoria": f"{CATEGORY_NAMES[categoria]} ({categoria})"}


def _verifica_lo_subido(video_id: str, headers: dict, descripcion: str) -> dict:
    """Comprueba contra YouTube lo que las decisiones 2 y 7 exigen, hasta donde alcanzan los scopes.

    Se comprueba leyendo de vuelta y no dando por bueno el 200 del PUT: la respuesta de la subida
    devuelve lo que se pidio, no necesariamente lo que YouTube guardo. Es la misma regla que aplico
    `--paso limpia` con Kaggle — confirmar contra el servicio, no contra el codigo de salida.

    **Limite medido el 28-08, y por eso hay dos caminos**: `videos.list` sobre un video PROPIO Y
    PRIVADO responde 403 `insufficientPermissions` con `youtube.upload`, que es un scope de
    escritura. Leer exigiria `youtube.readonly` o `force-ssl`. Cuando ese camino se cierra, queda el
    de la API key, que descarta lo peor —que el video estuviera publico—; el resto se declara como
    NO COMPROBADO en vez de darlo por bueno.
    """
    r = requests.get(
        VIDEOS_ENDPOINT,
        params={"part": "status,snippet", "id": video_id},
        headers=headers,
        timeout=30,
    )

    if r.status_code == 403:
        publico = _lee_con_api_key(video_id)
        no_publicado = publico.get("posible") and not publico["visible_sin_sesion"]
        return {
            "verificado": False,
            "via": "api_key (OAuth no alcanza para leer)",
            "motivo": (
                "el scope youtube.upload no permite leer el vídeo (403 insufficientPermissions), "
                "así que privacyStatus y containsSyntheticMedia NO se han podido confirmar leyendo"
            ),
            "descarta_que_este_publico": bool(no_publicado),
            "detalle_api_key": publico,
            "como_confirmarlo": (
                "el usuario lo ve en Studio, o se amplía el scope a youtube.readonly y esta misma función lo confirma "
                "sola"
            ),
        }

    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return {"verificado": False, "motivo": f"el vídeo {video_id} no se pudo leer tras subirlo"}

    estado = items[0].get("status", {})
    fragmento = items[0].get("snippet", {})
    privado = estado.get("privacyStatus")
    sintetico = estado.get("containsSyntheticMedia")
    # La declaracion se busca por su encabezado, que es lo estable del texto generado
    declarado = "AI DISCLOSURE" in (fragmento.get("description") or "") or "DECLARACIÓN DE IA" in (
        fragmento.get("description") or ""
    )

    fallos = []
    if privado != VISIBILIDAD:
        fallos.append(f"privacyStatus={privado!r}, se esperaba {VISIBILIDAD!r}")
    if sintetico is not True:
        fallos.append(f"containsSyntheticMedia={sintetico!r}, se esperaba True")
    if not declarado:
        fallos.append("la descripción publicada no contiene la declaración de IA")
    if descripcion.strip() and (fragmento.get("description") or "").strip() != descripcion.strip():
        fallos.append("la descripción publicada no coincide con la enviada")

    return {
        "verificado": not fallos,
        "via": "oauth",
        "privacyStatus": privado,
        "containsSyntheticMedia": sintetico,
        "fallos": fallos,
    }


def pon_miniatura(video_id: str, thumbnail_path: str | Path, headers: dict | None = None) -> tuple[bool, dict | None]:
    """Pone la miniatura en un vídeo YA subido. Devuelve (puesta, lo que queda a mano).

    **Está fuera de `upload_video` a propósito, y no es una refactorización cosmética**: la subida
    del vídeo es idempotente por diseño —relanzarla dejaría un borrador duplicado en el canal—, así
    que sin esta función una miniatura que falló la primera vez **no se puede reintentar nunca** por
    código. Y falla la primera vez con facilidad: exige canal verificado por teléfono, y eso suele
    pasar DESPUÉS de la primera subida. Fue justo el caso de `7-BhtoLpmqk` el 28-08.

    Poner una miniatura **no cambia la visibilidad** ni toca el gate 2: el vídeo sigue siendo el
    borrador privado que era.

    **Nunca lanza, y eso depende de `headers`.** La llama `upload_video` después del punto de no
    retorno, donde una excepción dejaría un borrador que el llamador no puede localizar. Todo lo que
    puede fallar aquí está dentro del `try`, **salvo el `get_access_token()` del argumento por
    defecto**, que se evalúa antes de entrar: hoy no se ejecuta nunca desde `upload_video` porque esa
    pasa `headers` no vacío y el `or` cortocircuita. Quien llame desde ahí sin `headers` rompe el
    invariante sin que nada avise.
    """
    ruta = Path(thumbnail_path)
    if not ruta.exists():
        return False, {
            "que": "miniatura",
            "archivo": str(ruta),
            "por_que": "el archivo no existe",
        }
    headers = headers or {"Authorization": f"Bearer {get_access_token()}"}
    print("  subiendo miniatura…")
    try:
        with open(ruta, "rb") as f:
            resp = requests.post(
                f"{THUMBNAIL_ENDPOINT}?videoId={video_id}",
                headers={**headers, "Content-Type": "image/png"},
                data=f,
                timeout=60,
            )
        if resp.status_code == 403:
            # No es un problema de scopes: `youtube.upload` está en la lista de la doc de
            # thumbnails.set. Es el canal, que necesita estar verificado por teléfono para poder
            # poner miniaturas propias. Medido el 28-08 en el canal recién creado: «The
            # authenticated user doesn't have permissions to upload and set custom video
            # thumbnails».
            print("  la miniatura NO se pudo poner: el canal no está verificado por teléfono")
            return False, {
                "que": "miniatura",
                "archivo": str(ruta),
                "por_que": (
                    "YouTube exige canal VERIFICADO POR TELÉFONO para miniaturas propias "
                    "(403 forbidden, no es de permisos OAuth)"
                ),
                "como": (
                    "verificar el canal en youtube.com/verify_phone_number y volver a poner la "
                    "miniatura con `pipeline.py --run-id <id> --set-thumbnail`, o arrastrarla en "
                    "Studio"
                ),
            }
        resp.raise_for_status()
        print("  miniatura puesta")
        return True, None
    except Exception as e:  # el vídeo ya está subido: una miniatura no lo tira
        print(f"  la miniatura falló (el vídeo sigue subido): {e}")
        return False, {"que": "miniatura", "archivo": str(ruta), "por_que": str(e)[:200]}


# Marcadores que los agentes que escriben el guion dejan **a propósito** en `description`, para que
# el paso de montaje los sustituya por los capítulos reales (que salen de las duraciones medidas) y
# por la bibliografía (que sale de las fichas de fuentes verificadas del canal).
MARCADORES_DE_DESCRIPCION = ("<<CAPITULOS>>", "<<BIBLIOGRAFIA>>")


def revisa_descripcion(description: str) -> None:
    """Se niega a subir una descripción con marcadores sin sustituir.

    **Por qué es una guarda y no una comprobación del skill.** El diseño es correcto: quien escribe
    el guion deja `<<CAPITULOS>>` y `<<BIBLIOGRAFIA>>` como marcadores, y el paso de montaje los
    sustituye. Lo que faltaba es que **nada en el código lo obligara**: la auditoría del 08-09 midió
    que los cuatro `slides.json` de la semana los llevan literales y que el camino de subida no los
    caza, así que un despiste en el skill publica «&lt;&lt;CAPITULOS&gt;&gt;» en la página del vídeo.

    Va aquí por la misma razón que `VISIBILIDAD` es una constante y no un argumento: lo que protege
    lo que se publica **no puede depender de que un agente se acuerde**. Y va ANTES de pedir el
    token, para que ni siquiera se abra la sesión con YouTube.
    """
    presentes = [m for m in MARCADORES_DE_DESCRIPCION if m in (description or "")]
    if presentes:
        raise RuntimeError(
            f"La descripción todavía lleva {', '.join(presentes)} sin sustituir: no se sube. "
            "Esos marcadores los deja el agente que escribe el guion y los rellena el montaje — "
            "los capítulos con las duraciones reales de las láminas y la bibliografía con las fichas "
            "de fuentes del canal. Publicarlos literales dejaría el texto de relleno a la vista en "
            "la página del vídeo. Compón la descripción y vuelve a lanzar la etapa de subida."
        )


def upload_video(
    file_path: str,
    title: str,
    description: str,
    tags: list[str] | None = None,
    thumbnail_path: str = "",
    srt_paths: list[str] | tuple[str, ...] = (),
    fecha_de_grabacion: str = "",
) -> dict:
    """Sube el video como borrador privado con el flag del Art. 50, y verifica lo guardado.

    `fecha_de_grabacion` va en formato RFC 3339 (`2026-09-15T00:00:00Z`) y rellena la «Fecha de
    grabacion» de Studio. La pone quien llama, porque la sabe el run y no el cliente.
    """
    revisa_descripcion(description)
    # Del perfil del canal (F4.9), validada ANTES de pedir el token: el error sale igual y sin red.
    categoria = _categoria()
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    metadata = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": categoria,
            # «Idioma del titulo y de la descripcion» en Studio. Del CANAL, y por la MISMA constante
            # que leen la voz y la declaracion de IA: con `IDIOMA_NARRACION=es` en el .env, las tres
            # cosas cambian juntas (auditoria del 15-09, ALTO 2).
            "defaultLanguage": NARRATION_LANG,
            # «Idioma del video». **No aparece en la lista de propiedades que la referencia de
            # `videos.insert` da como escribibles** —solo esta `defaultLanguage`—, pero si existe en
            # el recurso `video`. Se manda porque no cuesta nada y, si la API lo ignora, el campo se
            # queda como estaba; lo unico que no se puede es COMPROBARLO desde aqui, porque el scope
            # `youtube.upload` no permite leer el video. Se mira en Studio la primera vez.
            "defaultAudioLanguage": NARRATION_LANG,
        },
        "recordingDetails": {} if not fecha_de_grabacion else {"recordingDate": fecha_de_grabacion},
        "status": {
            "privacyStatus": VISIBILIDAD,
            # Los tres de abajo son la postura del estudio, igual en todos los canales.
            "license": LICENCIA,
            "embeddable": INSERTABLE,
            "publicStatsViewable": ESTADISTICAS_PUBLICAS,
            # Del CANAL desde F4.9, no del estudio: su perfil lo declara y aquí solo se envía. Se
            # exige un booleano de verdad —no un valor «que parezca»— porque declarar mal la
            # audiencia tiene consecuencias que no se ven hasta que YouTube las aplica.
            "selfDeclaredMadeForKids": _hecho_para_ninos(),
            # El flag del Art. 50. Verificado el 28-08 en la referencia del recurso `video` que el
            # campo existe en `status` y que el scope `youtube.upload` lo cubre.
            "containsSyntheticMedia": True,
        },
    }

    print(f"  iniciando subida reanudable como borrador {VISIBILIDAD}…")
    init_resp = requests.post(
        # `part` tiene que nombrar TODO lo que se escribe: sin `recordingDetails` la fecha de
        # grabacion viaja en el cuerpo y la API la ignora en silencio.
        f"{UPLOAD_ENDPOINT}?uploadType=resumable&part=snippet,status,recordingDetails",
        headers={**headers, "Content-Type": "application/json"},
        json=metadata,
        timeout=30,
    )
    init_resp.raise_for_status()
    upload_url = init_resp.headers["Location"]

    file_size = os.path.getsize(file_path)
    print(f"  subiendo vídeo ({file_size / 1024 / 1024:.1f} MB)…")

    with open(file_path, "rb") as f:
        upload_resp = requests.put(
            upload_url,
            headers={**headers, "Content-Type": "video/*", "Content-Length": str(file_size)},
            data=f,
            timeout=1800,
        )
    upload_resp.raise_for_status()
    # Hasta el `raise_for_status` un fallo significa que la subida no cuajo y lanzar esta bien. A
    # partir del ID ya no: el video existe. Y `.json()["id"]` puede lanzar —cuerpo no JSON, campo
    # ausente— dejando un borrador que nadie sabe localizar, asi que se saca defendido y, si no
    # viene, se dice en vez de reventar. Cazado en la auditoria de F3.3.
    try:
        video_id = upload_resp.json()["id"]
    except (ValueError, KeyError, TypeError) as e:
        raise RuntimeError(
            "YouTube aceptó la subida pero su respuesta no trae el id del vídeo "
            f"({type(e).__name__}). EL VÍDEO PUEDE ESTAR SUBIDO: búscalo en "
            "https://studio.youtube.com/channel/UC/videos/upload antes de repetir, o repetir dejará "
            f"un duplicado. Respuesta cruda: {upload_resp.text[:300]!r}"
        ) from e
    print(f"  subido: https://youtube.com/watch?v={video_id}")

    # ────────────────────────────────────────────────────────────────────────────────────────────
    # A PARTIR DE AQUI NADA PUEDE LANZAR. La subida es irreversible y el `video_id` es el unico
    # hilo que lleva hasta el video: si una miniatura o una comprobacion tira una excepcion, el
    # llamador no llega a guardarlo y queda un borrador huerfano en el canal. Paso el 28-08 en la
    # primera subida real —la miniatura dio 403 y la lectura tambien—, y el traceback hizo parecer
    # que habia fallado todo cuando el video estaba arriba. El resultado se construye YA.
    # ────────────────────────────────────────────────────────────────────────────────────────────
    resultado = {
        "video_id": video_id,
        "url": f"https://youtube.com/watch?v={video_id}",
        "studio_url": f"https://studio.youtube.com/video/{video_id}/edit",
        "title": title,
        "visibility": VISIBILIDAD,
        "art50_flag": True,
        "method": "youtube_direct",
        "pendiente_a_mano": [],
    }

    if thumbnail_path and Path(thumbnail_path).exists():
        puesta, pendiente = pon_miniatura(video_id, thumbnail_path, headers)
        resultado["miniatura_puesta"] = puesta
        if pendiente:
            resultado["pendiente_a_mano"].append(pendiente)

    # El .srt no se puede subir con estos permisos: se senala para que no se olvide en Studio. Desde F7.11 puede haber
    # varios (el del guion y sus traducciones, fila 265), y se senalan TODOS: uno que falte en la lista es uno que no
    # se adjunta.
    adjuntables = [str(s) for s in (srt_paths or ()) if s and Path(s).exists()]
    for srt in adjuntables:
        resultado["pendiente_a_mano"].append(
            {
                "que": f"subtítulos .srt ({Path(srt).name})",
                "archivo": srt,
                "por_que": (
                    "captions.insert exige youtube.force-ssl o youtubepartner; nuestro token tiene "
                    "youtube.upload (403 insufficientPermissions, medido)"
                ),
                "como": "adjuntarlo en Studio → Subtítulos, o ampliar el scope (decisión del usuario)",
            }
        )
    if adjuntables:
        print(
            f"  {len(adjuntables)} .srt quedan pendientes de adjuntar a mano en Studio "
            "(Subtítulos → Añadir idioma → Subir archivo):"
        )
        for srt in adjuntables:
            print(f"    {srt}")

    try:
        comprobacion = _verifica_lo_subido(video_id, headers, description)
    except Exception as e:
        comprobacion = {"verificado": False, "motivo": f"la comprobación falló: {str(e)[:200]}"}
    resultado["verificacion"] = comprobacion

    if comprobacion.get("verificado"):
        print("  verificado leyendo el vídeo: borrador privado y flag Art. 50 marcado")
    else:
        print("  [SIN CONFIRMAR] " + str(comprobacion.get("motivo", "")))
        if comprobacion.get("descarta_que_este_publico"):
            print("    lo que SÍ queda descartado: el vídeo no es público (no sale con API key)")
        for f in comprobacion.get("fallos", []):
            print(f"    - {f}")

    return resultado
