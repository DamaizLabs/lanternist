#!/usr/bin/env python3
r"""Lee la YouTube Analytics API y escribe `canales/<id>/datos/metricas-<fecha>-<hora>.json`.

    .venv\Scripts\python metricas.py
    .venv\Scripts\python metricas.py --ctr 7-BhtoLpmqk=4.6 --tiempo 7-BhtoLpmqk=26
    .venv\Scripts\python metricas.py --desde 2026-09-01 --curva 7-BhtoLpmqk

Es una FOTO de las métricas del canal: las vistas, la retención y los suscriptores del canal y de cada vídeo que subió
este pipeline, más lo que la API no sirve y se copia de Studio a mano. No juzga nada. **El kill switch salió de la
fábrica en OC1.4**: era la regla con la que se autorizó el estudio de vídeo del que nace este motor (umbrales de
retención y de CTR sobre una cohorte de cinco vídeos, con un plazo de 90 días), no una regla del motor. Quien use
Lanternist decide qué hace con sus cifras.

## UN FICHERO POR EJECUCIÓN, y la bandera `completa` DENTRO

La primera versión escribía uno por día, y la auditoría demostró el agujero de la forma más
directa: **la segunda pasada del 28-08 machacó la evidencia que el informe citaba**. Una foto de un
día pasado no se puede regenerar, así que nada la sobrescribe.

Quien compare fotos **filtra por `completa: true` y ordena por `extraido`**. Un sufijo
`-parcial` en el nombre no servía: si la primera pasada del día falla, los datos parciales van al
nombre limpio, y un `max()` sobre nombres elige el parcial de un día posterior.

## Los campos manuales se ARRASTRAN de la última foto que los traiga

Sin eso, una pasada sin `--ctr` escribe `null` sobre el valor que alguien copió ayer de Studio, y hay
que re-teclear todos los vídeos en cada extracción sin que nada lo advierta. Lo heredado se marca
**campo a campo** con su `*_heredado_de`, para que no se confunda con lo medido.

**Y el arrastre NO se filtra por `completa`**: un campo manual no es un hueco causado por un HTTP. Con
el filtro puesto, un CTR teclado en una pasada que tuvo un 500 no se heredaba nunca y la foto limpia
siguiente resucitaba el valor viejo marcándolo como heredado.

## Lo que este módulo NO puede darte

**El CTR no existe como métrica de la Analytics API.** Medido el 28-08 contra la API real:
`impressions`, `impressionsClickThroughRate`, `impression`, `impressionClickThroughRate`,
`thumbnailImpressions` y `thumbnailImpressionsCtr` responden **400 «Unknown identifier»**;
`impressionBasedCpm` también, y `adImpressions` da 401 porque es de monetización, otra cosa. Esas
cifras **solo existen en YouTube Studio**, y por eso entran a mano: `--ctr <video>=<pct>`.

## De dónde salen los vídeos, y por qué no de la API

De `datos/estado/*.json`, o sea de **lo que este pipeline subió**, no de lo que YouTube devuelve. Dos razones
medidas: `dimensions=video` **omite los vídeos con 0 vistas** (con un borrador subido, `por_video`
vuelve vacío), y un `--curva` con un id que no es nuestro responde **200 con 0 filas**, igual que uno nuestro sin
vistas — indistinguible contra la API, pero trivial contra el estado local.

## Lo que se reutiliza, y lo que se rechaza a propósito

- `lib.youtube_client.get_access_token()`: el canje ya está resuelto ahí.
- **NO** el `QuotaLedger` de `lib/cuota.py`: su tabla de costes y su `DAILY_QUOTA = 10_000`
  son de la **Data API v3**, y reutilizarlo daría cifras de gasto inventadas. Lo que sí se hereda es su
  regla, que además está en la lista negra: **jamás un reintento automático**.

## Dos requisitos de la API que no dicen qué falta

1. `dimensions=video` **exige `sort` y `maxResults`**. Sin ellos, 400 «The query is not supported».
2. La curva de retención **exige `filters=video==<id>`**. A nivel de canal, 400.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from lib.config import CANAL_ACTIVO, CANAL_DATOS_DIR, CANAL_ERROR, CANAL_PERFIL, STATE_DIR
from lib.youtube_client import get_access_token

REPORTS = "https://youtubeanalytics.googleapis.com/v2/reports"

# El esquema de la foto. **4 desde OC1.4**: salieron las claves del kill switch del estudio (la cohorte, los umbrales,
# el plazo, el suelo de vistas y los campos de coste y retrabajo de la cohorte). No es un cambio aditivo
# (`doc/versionado.md`), así que quien lea fotos de antes las distingue por este número.
ESQUEMA = 4

METRICAS_CANAL = (
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "subscribersGained",
    "subscribersLost",
)
METRICAS_VIDEO = ("views", "averageViewPercentage", "averageViewDuration", "subscribersGained")

# Rastro de lo que se probó, para que nadie repita el barrido creyendo que se nos pasó. La cuenta
# que aparece en el docstring y en los mensajes sale de `len()` de esta tupla, no de un teclado.
NO_EXISTEN_EN_LA_API = (
    "impressions",
    "impressionsClickThroughRate",
    "impression",
    "impressionClickThroughRate",
    "thumbnailImpressions",
    "thumbnailImpressionsCtr",
    "impressionBasedCpm",
)

# Por encima de esto, un CTR es casi seguro un dedazo (42 por 4,2). Se avisa, no se rechaza.
CTR_INVEROSIMIL = 20.0


def _pide(token: str, params: dict) -> dict:
    """Una llamada a Analytics. SIN reintento: registra y devuelve, la decisión es de quien lee."""
    r = requests.get(
        REPORTS,
        headers={"Authorization": f"Bearer {token}"},
        params={"ids": "channel==MINE", **params},
        timeout=60,
    )
    salida = {"http": r.status_code, "params": dict(params)}
    if r.status_code == 200:
        cuerpo = r.json()
        salida["columnas"] = [c["name"] for c in cuerpo.get("columnHeaders", [])]
        salida["filas"] = cuerpo.get("rows", [])
        return salida
    # El cuerpo de un error NO siempre es JSON: un 502/503 de la infraestructura de Google llega en
    # HTML, y `r.json()` a secas sustituiría por un traceback el aviso del 5xx que este módulo
    # escribe a propósito. Cazado en la auditoría.
    try:
        salida["error"] = str(r.json().get("error", {}).get("message", ""))[:300]
    except ValueError:
        salida["error"] = f"cuerpo no JSON ({len(r.text)} bytes): {r.text[:120]!r}"
    return salida


def _filas_como_dicts(respuesta: dict) -> list[dict]:
    """Convierte las filas de una respuesta en [{columna: valor}]. Sirve para 0, 1 o N filas."""
    columnas = respuesta.get("columnas") or []
    return [dict(zip(columnas, fila, strict=False)) for fila in respuesta.get("filas") or []]


def videos_del_pipeline() -> tuple[list[dict], list[str]]:
    """Los vídeos que este pipeline subió, en orden de producción. Devuelve (lista, avisos).

    **El orden va por `created_at` del run, que es inmutable.** La primera versión ordenaba por
    `stages.upload.updated_at`, y `lib/state.py` lo reescribe en CADA `update_stage` — incluido el
    `--forzar-subida` que el propio pipeline declara legítimo: el orden de producción cambiaba al reintentar una
    subida. Un estado sin `updated_at` se colaba además en el puesto 1 con su cadena vacía, y dos estados con el mismo
    `video_id` contaban dos veces el mismo vídeo.
    """
    avisos: list[str] = []
    encontrados: list[dict] = []
    vistos: dict[str, str] = {}
    for fichero in sorted(Path(STATE_DIR).glob("*.json")):
        try:
            estado = json.loads(fichero.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            avisos.append(f"{fichero.name} no se puede leer ({type(e).__name__}): se ignora")
            continue
        etapa = (estado.get("stages") or {}).get("upload") or {}
        try:
            resultado = json.loads(etapa.get("output") or "{}")
        except ValueError:
            continue
        vid = resultado.get("video_id")
        if not vid:
            continue
        run_id = estado.get("run_id", fichero.stem)
        if vid in vistos:
            avisos.append(f"el vídeo {vid} aparece en dos runs ({vistos[vid]} y {run_id}): se cuenta UNA vez")
            continue
        vistos[vid] = run_id
        encontrados.append(
            {
                "video_id": vid,
                "run_id": run_id,
                "titulo": estado.get("title", ""),
                "creado": estado.get("created_at", ""),
                "subido": etapa.get("updated_at", ""),
                "url": resultado.get("url", ""),
            }
        )
    sin_fecha = [v["run_id"] for v in encontrados if not v["creado"]]
    if sin_fecha:
        avisos.append(
            f"{len(sin_fecha)} run(s) sin created_at ({', '.join(sin_fecha[:3])}): se ordenan al FINAL "
            "por su run_id, que lleva la fecha en el nombre, en vez de colarse en el puesto 1"
        )
    # Sin `created_at` se cae al `run_id`, que empieza por AAAA-MM-DD_HHMMSS. Y el prefijo "~" empuja
    # al final en vez de al principio, que es donde una cadena vacía habría caído.
    encontrados.sort(key=lambda v: v["creado"] or f"~{v['run_id']}")
    for orden, v in enumerate(encontrados, 1):
        v["orden_de_produccion"] = orden
    return encontrados, avisos


def _campo_manual(vid: str, ctr: dict[str, float], tiempo: dict[str, float], heredados: dict, desde: str) -> dict:
    """Los campos manuales de un vídeo, con la procedencia declarada CAMPO A CAMPO."""
    previo = heredados.get(vid) or {}
    valor_ctr = ctr.get(vid, previo.get("ctr_pct"))
    valor_tiempo = tiempo.get(vid, previo.get("tiempo_humano_min"))
    return {
        "ctr_pct": valor_ctr,
        "ctr_pct_heredado_de": desde if vid not in ctr and valor_ctr is not None else None,
        "tiempo_humano_min": valor_tiempo,
        "tiempo_humano_min_heredado_de": (desde if vid not in tiempo and valor_tiempo is not None else None),
    }


def _campos_manuales_anteriores() -> tuple[dict, str]:
    """Los campos manuales por vídeo de la ÚLTIMA foto que los traiga, completa o no, y el nombre de esa foto.

    Sin arrastre, una pasada sin `--ctr` escribe `null` sobre el valor que alguien copió ayer de
    Studio, y hay que re-teclear todos los vídeos en cada extracción sin que nada lo advierta.

    **Y NO se filtra por `completa`**, que es lo que hacía la primera versión: un campo manual **no es
    un hueco causado por un HTTP**. La auditoría midió la consecuencia — un `--ctr 7.7` teclado en una
    pasada que tuvo un 500 no se heredaba nunca, y la foto limpia siguiente **resucitaba el 4,6 viejo
    marcándolo como heredado**. Lo que `completa: false` invalida son los datos de la API, no lo que
    alguien copió a mano.
    """
    if CANAL_DATOS_DIR is None:
        return {}, ""
    for foto in sorted(CANAL_DATOS_DIR.glob("metricas-*.json"), reverse=True):
        try:
            datos = json.loads(foto.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        campos = datos.get("campos_manuales_por_video") or {}
        con_algo = {
            vid: v
            for vid, v in campos.items()
            if isinstance(v, dict) and (v.get("ctr_pct") is not None or v.get("tiempo_humano_min") is not None)
        }
        if con_algo:
            return con_algo, foto.name
    return {}, ""


def _pares(valores: list[str], etiqueta: str, minimo: float, maximo: float) -> dict[str, float]:
    """Interpreta los `--ctr id=valor`, con rango: un dedazo no puede entrar en la foto como si fuera un dato."""
    fuera: dict[str, float] = {}
    for bruto in valores or []:
        if "=" not in bruto:
            raise SystemExit(f"[FAIL] --{etiqueta} se escribe <video_id>=<valor>, no {bruto!r}")
        vid, _, crudo = bruto.partition("=")
        vid = vid.strip()
        if not vid:
            raise SystemExit(f"[FAIL] --{etiqueta} {bruto!r}: falta el id del vídeo antes del '='")
        if vid in fuera:
            # `action="append"` deja pasar el mismo id dos veces y el último ganaría en silencio.
            raise SystemExit(f"[FAIL] --{etiqueta} {vid}: repetido. Ya se dio el valor {fuera[vid]}; decide cuál es")
        try:
            valor = float(crudo)
        except ValueError as e:
            raise SystemExit(f"[FAIL] --{etiqueta} {bruto!r}: {crudo!r} no es un número") from e
        if not (minimo <= valor <= maximo):
            raise SystemExit(
                f"[FAIL] --{etiqueta} {bruto!r}: {valor} está fuera del rango {minimo}-{maximo}. "
                "Si de verdad es ese valor, revísalo en Studio antes de forzarlo"
            )
        fuera[vid] = valor
    return fuera


def main() -> int:
    parser = argparse.ArgumentParser(description="Analytics del canal -> datos/metricas-<fecha>.json")
    parser.add_argument("--desde", default="", help="AAAA-MM-DD; por defecto, 90 días atrás")
    parser.add_argument("--hasta", default="", help="AAAA-MM-DD; por defecto, hoy")
    parser.add_argument("--curva", default="", help="id de vídeo para su curva de retención")
    parser.add_argument(
        "--ctr",
        action="append",
        metavar="VIDEO=PCT",
        help="CTR en %% copiado A MANO de Studio, POR VÍDEO: la API no lo sirve. Repetible",
    )
    parser.add_argument(
        "--tiempo",
        action="append",
        metavar="VIDEO=MIN",
        help="minutos de trabajo humano que costó publicar el vídeo, POR VÍDEO. Repetible",
    )
    args = parser.parse_args()

    if CANAL_ERROR:
        print(f"[FAIL] {CANAL_ERROR}")
        return 2
    if CANAL_DATOS_DIR is None:
        print("[FAIL] sin canal activo: no hay dónde escribir")
        return 2

    ctr_por_video = _pares(args.ctr, "ctr", 0.0, 100.0)
    tiempo_por_video = _pares(args.tiempo, "tiempo", 0.0, 24 * 60)

    # El rango 0-100 no basta: el dedazo típico es escribir 42 por 4,2, y 42 es un porcentaje válido. Un CTR por
    # encima del 20 % no existe en YouTube en la práctica, así que se AVISA en vez de rechazar: negarse a aceptar un
    # valor extremo real sería peor, pero dejarlo pasar en silencio falsearía la foto.
    for vid, valor in ctr_por_video.items():
        if valor > CTR_INVEROSIMIL:
            print(f"  [OJO] --ctr {vid}={valor}: un CTR del {valor} % es extraordinario en YouTube.")
            print(f"        Si de verdad es ese, ignora el aviso; si querías {valor / 10:g}, corrígelo.")

    hasta = args.hasta or date.today().isoformat()
    desde = args.desde or (date.today() - timedelta(days=90)).isoformat()

    videos, avisos = videos_del_pipeline()
    conocidos = {v["video_id"] for v in videos}
    for aviso in avisos:
        print(f"  [VÍDEOS] {aviso}")

    for etiqueta, mapa in (("--ctr", ctr_por_video), ("--tiempo", tiempo_por_video)):
        for vid in mapa:
            if vid not in conocidos:
                print(f"  [AVISO] {etiqueta} {vid}: ese vídeo no lo subió este pipeline (datos/estado/)")
    if args.curva and args.curva not in conocidos:
        # La API responde 200 con 0 filas tanto para un id ajeno como para uno nuestro sin vistas:
        # indistinguible allí, trivial aquí. Medido en la auditoría.
        print(f"  [AVISO] --curva {args.curva}: no está en datos/estado/, así que no lo subió este pipeline.")
        print("          La API devolvería 200 con 0 filas igual que si fuera nuestro sin vistas.")

    print(f"Canal {CANAL_ACTIVO} · ventana {desde} → {hasta} · {len(videos)} vídeo(s) subidos por el pipeline")
    avisos_previos = len(avisos)  # los ya impresos: lo que se añada después se imprime aparte

    token = get_access_token()
    llamadas = []
    canal = _pide(token, {"startDate": desde, "endDate": hasta, "metrics": ",".join(METRICAS_CANAL)})
    llamadas.append(canal)
    por_video = _pide(
        token,
        {
            "startDate": desde,
            "endDate": hasta,
            "metrics": ",".join(METRICAS_VIDEO),
            "dimensions": "video",
            "sort": "-views",
            # 200 es el techo del informe. Sin paginar: con más de 200 vídeos con vistas, uno nuestro con pocas
            # podría no venir, y su fila diría «sin vistas» con HTTP 200. Se avisa si el listado llega al techo, y
            # un vídeo AUSENTE del listado se distingue de uno con 0.
            "maxResults": 200,
        },
    )
    llamadas.append(por_video)
    curva = None
    if args.curva:
        curva = _pide(
            token,
            {
                "startDate": desde,
                "endDate": hasta,
                "metrics": "audienceWatchRatio",
                "dimensions": "elapsedVideoTimeRatio",
                "filters": f"video=={args.curva}",
            },
        )
        llamadas.append(curva)

    fallos = [c for c in llamadas if c["http"] != 200]
    for c in fallos:
        print(f"  [ERROR] http {c['http']} · {c.get('error', '')[:160]}")
        print("          NO se reintenta: es de la lista negra del proyecto. Vuelve a lanzarlo tú.")
        if c["http"] >= 500:
            # Medido el 28-08: la llamada por vídeo dio 500 y al repetirla con los MISMOS parámetros
            # —maxResults de 10 a 200— respondió 200 en los cuatro casos.
            print("          Un 5xx aquí suele ser TRANSITORIO de la API, no de la consulta: se ha")
            print("          medido que la misma llamada responde 200 al repetirla. NO cambies los")
            print("          parámetros antes de reintentar a mano.")

    # Arrastre de los campos manuales: sin esto, una pasada sin `--ctr` escribe `null` sobre el 4,6
    # de ayer y hay que re-teclear todos en cada extracción sin que nada lo diga. Se lee la
    # última foto QUE LOS TRAIGA, **completa o no** —un campo manual no es un hueco causado por un
    # HTTP—, y lo heredado se marca CAMPO A CAMPO con su `*_heredado_de`, para no confundirlo con
    # lo medido.
    heredados, heredado_desde = _campos_manuales_anteriores()
    if heredados:
        print(f"  [ARRASTRE] campos manuales heredados de {heredado_desde}: {len(heredados)} vídeo(s)")

    filas_video = _filas_como_dicts(por_video)
    medido_por_video = {f["video"]: f for f in filas_video if "video" in f}
    if len(filas_video) >= 200:
        avisos.append(
            "el listado por vídeo llegó al techo de 200 filas: puede faltar algún vídeo con vistas, "
            "y un ausente NO es un cero. Acota la ventana con --desde/--hasta"
        )
    ausentes = [v["video_id"] for v in videos if v["video_id"] not in medido_por_video]
    if ausentes and filas_video:
        avisos.append(
            f"{len(ausentes)} vídeo(s) del pipeline no vienen en el listado de la API "
            f"({', '.join(ausentes[:5])}): con 0 vistas es lo esperado, pero NO se puede afirmar que "
            "tengan 0 sin comprobarlo con --curva"
        )
    agregado = (_filas_como_dicts(canal) or [{}])[0]

    datos = {
        "esquema": ESQUEMA,
        "canal": CANAL_ACTIVO,
        "canal_youtube": (CANAL_PERFIL.get("publicacion") or {}).get("canal_youtube"),
        "extraido": datetime.now().isoformat(timespec="seconds"),
        "ventana": {"desde": desde, "hasta": hasta},
        "videos_del_pipeline": {
            "videos": videos,
            "_de_donde_salen": (
                "de datos/estado/*.json, o sea de lo que este pipeline subió: `dimensions=video` OMITE los "
                "vídeos con 0 vistas, y un id ajeno responde 200 con 0 filas igual que uno nuestro sin vistas"
            ),
            # En stdout no basta: quien lea esta foto otro día no ve la consola de hoy.
            "avisos": avisos,
        },
        "agregado_del_canal": agregado,
        "por_video_segun_la_api": filas_video,
        "curva_de_retencion": curva,
        "completa": not fallos,
        "_completa_por_que": (
            "true solo si TODAS las llamadas devolvieron 200. Quien compare fotos debe filtrar por "
            "`completa: true` y ordenar por `extraido`: una extracción con fallos tiene huecos que parecen ceros"
        ),
        # De TODOS los vídeos del pipeline. La procedencia va POR CAMPO: marcar solo cuando se heredó el CTR
        # presentaba un `tiempo_humano_min` heredado como si estuviera medido.
        "campos_manuales_por_video": {
            v["video_id"]: _campo_manual(v["video_id"], ctr_por_video, tiempo_por_video, heredados, heredado_desde)
            for v in videos
        },
        "_campos_manuales_por_que": {
            "ctr_pct": (
                f"El CTR no existe en la Analytics API: {len(NO_EXISTEN_EN_LA_API)} identificadores "
                "probados, todos 400 «Unknown identifier». Se copia de Studio y se pasa con --ctr"
            ),
            "tiempo_humano_min": (
                "Los minutos de trabajo humano que costó publicar el vídeo: los apunta quien lo publica, con "
                "--tiempo. Si no se anotan al publicar, el dato se pierde"
            ),
        },
        "llamadas": llamadas,
    }

    # UN FICHERO POR EJECUCIÓN, con la hora en el nombre. La primera versión era por DÍA, y la
    # auditoría demostró el agujero de la forma más directa posible: la segunda pasada del 28-08
    # machacó la evidencia que este mismo informe citaba. Una foto pasada no se regenera, así que nada la puede
    # sobrescribir.
    #
    # Y la bandera `completa` va DENTRO del JSON, no en el nombre: un sufijo `-parcial` tenía tres
    # agujeros que el auditor midió — si la PRIMERA pasada del día falla, los datos parciales van al
    # nombre limpio; un `max()` sobre los nombres elige el parcial de un día posterior; y quien lee no
    # sabe qué mirar. Quien compare fotos filtra por `completa: true` y ordena por `extraido`.
    CANAL_DATOS_DIR.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    destino = CANAL_DATOS_DIR / f"metricas-{marca}.json"
    destino.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")

    # Los avisos que se descubren DESPUÉS del bucle de fallos (techo del listado y vídeos ausentes)
    # iban solo al JSON: quien opera necesita verlos ahora, no al releer la foto.
    for aviso in avisos[avisos_previos:]:
        print(f"  [VÍDEOS] {aviso}")

    print(f"\nEscrito: {destino}")
    print(f"  vistas del canal en la ventana: {agregado.get('views', 'sin datos')}")
    print(f"  vídeos del pipeline: {len(videos)} · con datos en la API: {len(filas_video)}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
