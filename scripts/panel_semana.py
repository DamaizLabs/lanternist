"""Panel de observación de `produce-semana`: cómo avanza cada episodio de la semana y qué espera al usuario.

Correr:  .venv\\Scripts\\python scripts/panel_semana.py [--canal <id>] [--semana 2026-W37]
                                                        [--vigilar 10] [--no-abrir]

## Qué es y qué no es

Petición del 08-09-2026: «lo único que quiero es tener un control visual de cómo avanza el proceso del skill
produce-semana y si se puede que pueda lanzar los vídeos desde el html para no buscarlos». Eso y nada
más: **una página que se mira y un clic que reproduce**. Sin botón de aprobar, sin publicar nada, sin
servidor. Los gates siguen siendo suyos y se firman donde siempre (decisión cerrada 2).

Sigue el patrón de `scripts/pagina_calendario.py`: el entregable se abre con doble clic (criterio del
31-08, addendum fila 40), **se queda en local** (decisión cerrada 6: el `<video>` apunta con
`file://` al mp4 del run, nada sube a ningún sitio) y **se regenera entera en cada pasada**, sin
estado propio, así que no puede contradecir al estado del run.

## Por qué la barra se pesa por minutos y no por etapas

Contar etapas daría 1/6 al acabar las láminas y 2/6 al acabar la voz, cuando esas dos son el 70 % del
tiempo real. La barra se pesa con las **duraciones medidas** del 07/08-09 sobre la 3060 Ti (constantes
`PESOS_MIN`, con su dirección en el comentario de cada una) y, dentro de las dos etapas largas, cuenta
**lo que hay en disco**: `slides/slide-*.png` frente a las láminas del `slides.json`, y
`audio/slide-*.wav` igual. Así dice «lámina 18 de 33» en vez de quedarse quieta 33 minutos.

Los pesos son del ESTUDIO y no del canal: miden la máquina y los motores, no una identidad. Por eso
viven aquí con valor y no en el perfil (F4.9 protege lo contrario: decisiones de canal en `lib/`).

## De dónde sale cada dato

- El plan, de `canales/<id>/calendario/<semana>.json` (`--semana`, o el más reciente del directorio).
- El estado de cada run, de `canales/<id>/datos/estado/<run>.json` (`lib/state.py`): `stages` con
  `status`, `output` y `updated_at`. Es la fuente de verdad; la página no infiere nada que el estado
  no diga, salvo el conteo de ficheros para afinar la fracción de una etapa en marcha.
- Las citas, del JSON de la ficha en `canales/<id>/datos/fuentes/<ficha>.json`. Se listan tal cual
  vienen: si una clave falta, se omite, no se inventa.
- La firma del gate 1, del informe que nombra el calendario (`gate1`): su casilla `## APROBADO` la escribe el usuario y
  la plantilla deja `*(pendiente)*` hasta entonces. Detectar ese texto es una heurística sobre la
  plantilla, no una verdad del pipeline, y se dice así en la página.

Todo texto que viene de un JSON pasa por `html.escape`: los títulos son DATOS (convención A-9).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

# --- `--canal` se resuelve ANTES de importar nada de `lib/`, copiando el patrón de `pipeline.py` ---
# `lib/config.py` lee `CANAL_ACTIVO` al importarse y de ahí derivan las rutas del canal; cuando
# `argparse` corre ya es tarde. El flag se registra igual en el parser para que salga en `--help`.
if "--canal" in sys.argv:
    _i = sys.argv.index("--canal")
    if _i + 1 < len(sys.argv):
        os.environ["CANAL_ACTIVO"] = sys.argv[_i + 1].strip()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import config  # noqa: E402
from lib.config import (  # noqa: E402
    BASE_DIR,
    CANAL_ACTIVO,
    CANAL_DATOS_DIR,
    CANAL_DIR,
    CANAL_PERFIL,
    CANAL_PERFIL_PATH,
    CANAL_VIDEOS_DIR,
    STATE_DIR,
)

# --- Pesos de la barra, en MINUTOS medidos (del estudio: miden la máquina, no un canal) ------------
# Cada cifra lleva su dirección, como pide la convención de «cifras con dirección»:
#   images    33,0 → 33 láminas × 60 s/lámina de Qwen-Lightning sobre la 3060 Ti
#               (CLAUDE.md «Imagen, decidida»; `generacion-imagenes.json` del run del ep. 1).
#   tts       36,4 → narración del episodio 1 con Orpheus sobre llama.cpp Q8_0
#               (addendum fila 113 da 20,6 min de motor; los 36,4 son el reloj de la etapa entera
#               del 08-09, `stages.tts.updated_at` menos el arranque, con la referencia y el recorte).
#   assembly  30,0 → montaje 15 + subtítulos 5 + música 10, reloj del 08-09 sobre el ep. 1.
#   thumbnail  1,2 → una lámina de Qwen más la composición del texto (`miniatura.json` del ep. 1).
#   upload     1,0 → subida del borrador privado del 28-08 (F3.3).
#   slides_json  0 → lo escribe la conversación, no la máquina: no consume reloj del run.
# Son medidas de UN episodio de 33 láminas: otro largo escala, y la barra sigue siendo honesta
# porque dentro de las etapas largas cuenta ficheros, no minutos.
PESOS_MIN: dict[str, float] = {
    "slides_json": 0.0,
    "images": 33.0,
    "tts": 36.4,
    "assembly": 30.0,
    "thumbnail": 1.2,
    "upload": 1.0,
}
# Declarado aparte y comprobado en `tests/test_panel_semana.py`: si alguien toca un peso y no este
# total, la prueba lo dice antes que la barra.
TOTAL_MIN = 101.6

# Orden de ejecución del pipeline (`lib/state.py → create_run`). La fase «siguiente» se busca en él.
ORDEN_ETAPAS = ("slides_json", "images", "tts", "assembly", "thumbnail", "upload")

# Qué se cuenta en disco por etapa: (subdirectorio del run, patrón). Solo las dos largas lo tienen;
# el resto no deja un fichero por unidad de trabajo que se pueda contar.
CONTABLES: dict[str, tuple[str, str]] = {
    "images": ("slides", "slide-*.png"),
    "tts": ("audio", "slide-*.wav"),
}

# Textos de fase. `activa` es lo que se muestra con la etapa `in_progress`, `nombre` el sustantivo
# para «Bloqueado en …» y «siguiente: …».
ETIQUETAS: dict[str, dict[str, str]] = {
    "slides_json": {"activa": "Escribiendo el guion por láminas", "nombre": "guion por láminas"},
    "images": {"activa": "Generando láminas", "nombre": "láminas"},
    "tts": {"activa": "Narrando", "nombre": "narración"},
    "assembly": {"activa": "Montando", "nombre": "montaje"},
    "thumbnail": {"activa": "Miniatura", "nombre": "miniatura"},
    "upload": {"activa": "Subiendo como borrador privado", "nombre": "subida"},
}

# Fracción de una etapa en marcha cuando no hay nada que contar en disco: ni 0 (parecería parada)
# ni 1 (parecería hecha). Es la única cifra de la barra que no está medida, y por eso es constante
# con nombre y no un número suelto.
FRACCION_SIN_CONTEO = 0.5


# ================================ La función pura: estado + disco → progreso ==========================


def _laminas_declaradas(run_dir: Path) -> int | None:
    """Cuántas láminas dice el `slides.json` del run, o None si no existe o no se puede leer.

    Es el denominador del conteo: sin él, la barra no puede decir «18 de 33» y recurre a
    `FRACCION_SIN_CONTEO`. Se tolera un JSON roto porque el panel es observación: no debe caerse
    mientras el pipeline escribe.
    """
    ruta = run_dir / "slides.json"
    if not ruta.exists():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    slides = datos.get("slides") if isinstance(datos, dict) else None
    return len(slides) if isinstance(slides, list) and slides else None


def _contados(run_dir: Path, etapa: str, desde: str | None = None) -> int | None:
    """Ficheros producidos por una etapa contable, o None si la etapa no es contable.

    `desde` es el `updated_at` de la etapa (ISO local) cuando está en marcha o bloqueada: solo
    cuentan los ficheros escritos DESPUÉS de que arrancara. Sin ese filtro, regenerar la voz de un
    run que ya tenía sus 33 wav se pintaba como «Narrando (33/33)» desde el primer segundo —visto el
    08-09 con el episodio 1—, porque contaba los wav viejos que la etapa aún no había sobrescrito.
    Dos segundos de holgura por el redondeo del reloj de ficheros; sin `desde`, cuenta todo.
    """
    if etapa not in CONTABLES:
        return None
    sub, patron = CONTABLES[etapa]
    carpeta = run_dir / sub
    if not carpeta.is_dir():
        return 0
    ficheros = list(carpeta.glob(patron))
    if desde:
        try:
            corte = datetime.fromisoformat(desde).timestamp() - 2.0
        except ValueError:
            corte = None
        if corte is not None:
            ficheros = [f for f in ficheros if f.stat().st_mtime >= corte]
    return len(ficheros)


def _fraccion(etapa: str, status: str, hechos: int | None, total: int | None) -> float:
    """Cuánto de su peso aporta una etapa a la barra, entre 0 y 1.

    - `complete` y `skipped` aportan el peso entero: el run no va a hacer nada más ahí. La diferencia
      entre las dos la cuenta la FASE, no la barra («Terminado sin subir», no «Subido»).
    - `in_progress` y `blocked` aportan lo medido en disco cuando la etapa es contable —18 láminas
      hechas son trabajo real aunque la etapa se haya bloqueado en la 19— y, si no lo es,
      `FRACCION_SIN_CONTEO` en marcha y 0 bloqueada.
    - `pending` (o cualquier otro valor) aporta 0.
    """
    if status in ("complete", "skipped"):
        return 1.0
    if status in ("in_progress", "blocked"):
        if hechos is not None and total:
            return min(hechos / total, 1.0)
        return FRACCION_SIN_CONTEO if status == "in_progress" else 0.0
    return 0.0


def _primera_linea(texto) -> str:
    return str(texto or "").strip().splitlines()[0] if str(texto or "").strip() else ""


def progreso(estado: dict, run_dir: Path) -> dict:
    """Progreso y fase de un run a partir de su estado y de lo que hay en su directorio.

    Es la función que prueban los tests y la única con lógica: lo demás es HTML. No lee nada fuera
    de `run_dir` ni depende de la hora, para que un directorio sintético en `tmp_path` baste.

    Devuelve:
      pct        → 0-100, pesado con `PESOS_MIN` y afinado con el conteo de ficheros.
      fase       → una línea: «Generando láminas (18/33)», «Bloqueado en montaje: …», «Sin empezar»…
      bloqueado  → True si alguna etapa está `blocked` (la barra se pinta en rojo).
      terminado  → True si todas las etapas con peso están `complete` o `skipped`.
      subido     → True si la subida está `complete` (borrador privado en el canal).
      updated_at → el `updated_at` más reciente de las etapas (ISO local), o None.
      etapas     → por etapa: status, fracción y el conteo (hechos, total) cuando lo hay.
    """
    stages = estado.get("stages") or {}
    total_laminas = _laminas_declaradas(run_dir)

    etapas: dict[str, dict] = {}
    minutos = 0.0
    for etapa in ORDEN_ETAPAS:
        datos = stages.get(etapa) or {}
        status = str(datos.get("status") or "pending")
        # En marcha o bloqueada, solo cuentan los ficheros posteriores a su arranque (regeneraciones).
        desde = datos.get("updated_at") if status in ("in_progress", "blocked") else None
        hechos = _contados(run_dir, etapa, desde)
        fraccion = _fraccion(etapa, status, hechos, total_laminas)
        minutos += PESOS_MIN[etapa] * fraccion
        etapas[etapa] = {
            "status": status,
            "fraccion": fraccion,
            "conteo": (hechos, total_laminas) if hechos is not None else None,
            "output": _primera_linea(datos.get("output")),
            "updated_at": datos.get("updated_at"),
        }

    pct = round(100.0 * minutos / TOTAL_MIN, 1) if TOTAL_MIN else 0.0
    con_peso = [e for e in ORDEN_ETAPAS if PESOS_MIN[e] > 0]
    bloqueadas = [e for e in ORDEN_ETAPAS if etapas[e]["status"] == "blocked"]
    en_marcha = [e for e in ORDEN_ETAPAS if etapas[e]["status"] == "in_progress"]
    terminado = all(etapas[e]["status"] in ("complete", "skipped") for e in con_peso)
    subido = etapas["upload"]["status"] == "complete"
    nada_hecho = all(etapas[e]["status"] == "pending" for e in con_peso)

    if bloqueadas:
        e = bloqueadas[0]
        motivo = etapas[e]["output"] or "sin motivo registrado en el estado"
        fase = f"Bloqueado en {ETIQUETAS[e]['nombre']}: {motivo}"
    elif en_marcha:
        e = en_marcha[0]
        fase = ETIQUETAS[e]["activa"]
        conteo = etapas[e]["conteo"]
        if conteo and conteo[1]:
            fase += f" ({conteo[0]}/{conteo[1]})"
    elif subido:
        fase = "Subido como borrador privado"
    elif terminado:
        motivo = etapas["upload"]["output"] or "subida omitida"
        fase = f"Terminado sin subir: {motivo}"
    elif nada_hecho:
        fase = "Sin empezar"
    else:
        # Algo hecho, nada en marcha ni bloqueado: el pipeline está entre etapas (o parado a mano).
        siguiente = next((e for e in con_peso if etapas[e]["status"] not in ("complete", "skipped")), None)
        fase = f"En espera · siguiente: {ETIQUETAS[siguiente]['nombre']}" if siguiente else "En espera"

    marcas = [d["updated_at"] for d in etapas.values() if d["updated_at"]]
    return {
        "pct": pct,
        "fase": fase,
        "bloqueado": bool(bloqueadas),
        "terminado": terminado,
        "subido": subido,
        "updated_at": max(marcas) if marcas else None,
        "etapas": etapas,
    }


# ===================================== Lectura del canal (con rutas de config) ======================


def _estado_del_run(run_id: str | None) -> dict:
    """El estado real del run, o un diccionario vacío si aún no existe o no se puede leer."""
    if not run_id:
        return {}
    ruta = STATE_DIR / f"{run_id}.json"
    if not ruta.exists():
        return {}
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # El pipeline escribe el fichero entero con `json.dump`: leerlo a medias da un JSON roto y eso
        # no es un error del panel, es una foto entre dos escrituras. La siguiente pasada lo verá bien.
        return {}


def _ficha(nombre: str | None) -> dict:
    if not nombre or CANAL_DATOS_DIR is None:
        return {}
    ruta = CANAL_DATOS_DIR / "fuentes" / f"{nombre}.json"
    if not ruta.exists():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return datos if isinstance(datos, dict) else {}


def _firma_gate1(ruta_relativa: str | None) -> str:
    """`firmado`, `sin firmar`, `sin casilla`, `sin informe` o `sin ruta`, leído del informe del gate 1.

    Se busca la FIRMA, no la ausencia de un marcador. La convención la escribe la skill produce-semana
    (paso 6): la aprobación va por escrito en el informe, con la fecha y la cita literal del usuario. Así
    que la casilla `## APROBADO` cuenta como firmada cuando,
    quitados los comentarios HTML, contiene una fecha `dd-mm-aaaa` **y** una cita entre «comillas»
    (un ejemplo real: «**Nombre, 04-09-2026: «Go al guion».**»).

    Por qué no se busca el marcador de «pendiente»: la primera versión buscaba `*(pendiente)*` y los
    cuatro informes de la W37 dejan la casilla vacía con CUATRO textos distintos (`*(pendiente)*`,
    `_Vacío a propósito._`, `_Casilla vacía a propósito._`…), así que tres salían «firmados» sin que
    el usuario hubiera escrito una línea. Buscar la firma falla del lado seguro: un informe raro sale como
    «sin firmar», nunca como firmado. Sigue siendo una lectura del informe, no una verdad del
    pipeline, y la página lo dice.
    """
    if not ruta_relativa:
        return "sin ruta"
    ruta = BASE_DIR / ruta_relativa
    if not ruta.exists():
        return "sin informe"
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError:
        return "sin informe"
    if "## APROBADO" not in texto:
        return "sin casilla"
    casilla = texto.split("## APROBADO", 1)[1].split("\n## ", 1)[0]
    casilla = re.sub(r"<!--.*?-->", "", casilla, flags=re.DOTALL)
    tiene_fecha = re.search(r"\b\d{1,2}-\d{2}-\d{4}\b", casilla) is not None
    tiene_cita = re.search(r"«[^»]+»", casilla) is not None
    return "firmado" if (tiene_fecha and tiene_cita) else "sin firmar"


def _hora_local(iso: str | None) -> str:
    """`updated_at` del estado (ISO naive, hora local de la máquina) como `dd-mm HH:MM:SS`."""
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d-%m %H:%M:%S")
    except ValueError:
        return html.escape(iso)


def _hace(iso: str | None, ahora: datetime) -> str:
    if not iso:
        return ""
    try:
        delta = ahora - datetime.fromisoformat(iso)
    except ValueError:
        return ""
    s = int(delta.total_seconds())
    if s < 0:
        return ""
    if s < 60:
        return f"hace {s} s"
    if s < 3600:
        return f"hace {s // 60} min"
    if s < 86400:
        return f"hace {s // 3600} h {(s % 3600) // 60} min"
    return f"hace {s // 86400} d"


# ============================================== HTML ==================================================

# Misma paleta y tipografía que `scripts/pagina_calendario.py`, para que las dos páginas del canal se
# lean como una sola. Se copia y no se importa: importar aquel módulo ejecutaría su `argparse` y sus
# rutas, y una vista no debería arrastrar a otra.
ESTILO = """
:root { color-scheme: light dark; --tinta:#1c1a17; --papel:#f4f1ea; --linea:#d8d2c4;
        --acento:#8a6a2f; --apagado:#6b6459; --barra:#2c5d33; --rojo:#7a2f2f; --tarjeta:rgba(128,128,128,.06); }
@media (prefers-color-scheme: dark) { :root { --tinta:#ece7dc; --papel:#17150f;
        --linea:#3a352b; --acento:#c9a961; --apagado:#9a9285; --barra:#4f8f5a; --rojo:#b04a4a; } }
* { box-sizing:border-box; }
body { margin:0; padding:32px; background:var(--papel); color:var(--tinta);
       font:15px/1.55 Georgia,'Times New Roman',serif; }
h1 { font-size:26px; margin:0 0 4px; letter-spacing:.2px; }
h2 { font-size:18px; margin:32px 0 10px; border-bottom:1px solid var(--linea); padding-bottom:6px; }
h3 { font-size:17px; margin:0 0 4px; }
.sub { color:var(--apagado); margin:0 0 24px; }
a { color:var(--acento); }
code { font-family:Consolas,monospace; font-size:13px; background:rgba(128,128,128,.13);
       padding:1px 5px; border-radius:3px; }
.pill { display:inline-block; padding:2px 9px; border-radius:11px; font-size:12px; border:1px solid var(--linea); }
.ok { background:#2c5d33; color:#fff; border-color:#2c5d33; }
.no { background:#7a2f2f; color:#fff; border-color:#7a2f2f; }
.wait { background:#7a5f2f; color:#fff; border-color:#7a5f2f; }
.aviso { border-left:3px solid var(--acento); padding:10px 16px; margin:18px 0; background:rgba(138,106,47,.07); }
.episodio { border:1px solid var(--linea); border-radius:6px; padding:18px 20px; margin:0 0 18px;
            background:var(--tarjeta); }
.cabecera { display:flex; gap:14px; align-items:baseline; flex-wrap:wrap; }
.n { color:var(--apagado); font-size:13px; }
.meta { color:var(--apagado); font-size:13px; margin:4px 0 0; }
.barra { position:relative; height:22px; border:1px solid var(--linea); border-radius:4px; margin:14px 0 6px;
         background:rgba(128,128,128,.10); overflow:hidden; }
.barra > .relleno { height:100%; background:var(--barra); transition:width .4s; }
.barra.roja > .relleno { background:var(--rojo); }
.barra > .pct { position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
                font-size:13px; font-weight:bold; mix-blend-mode:difference; color:#fff; }
.fase { font-size:15px; margin:0; }
.fase.roja { color:var(--rojo); font-weight:bold; }
.cuerpo { display:grid; grid-template-columns: minmax(0,1.3fr) minmax(0,1fr); gap:22px; margin-top:16px; }
@media (max-width: 900px) { .cuerpo { grid-template-columns: 1fr; } }
video { width:100%; max-width:640px; border:1px solid var(--linea); background:#000; display:block; }
img.thumb { width:220px; height:auto; border:1px solid var(--linea); display:block; margin-top:8px; }
ul.citas { margin:6px 0 0; padding-left:18px; font-size:13.5px; }
ul.citas li { margin:0 0 4px; }
ul.enlaces { list-style:none; padding:0; margin:8px 0 0; font-size:14px; }
ul.enlaces li { margin:0 0 4px; }
table { border-collapse:collapse; width:100%; margin:0 0 8px; }
th,td { text-align:left; padding:10px 12px; border-bottom:1px solid var(--linea); vertical-align:top; }
th { font-size:12px; text-transform:uppercase; letter-spacing:.6px; color:var(--apagado); font-weight:normal; }
.etapas { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }
.etapas span { font-size:12px; padding:1px 8px; border-radius:10px; border:1px solid var(--linea);
               color:var(--apagado); }
.etapas span.hecha { border-color:var(--barra); color:var(--barra); }
.etapas span.marcha { border-color:var(--acento); color:var(--acento); }
.etapas span.rota { border-color:var(--rojo); color:var(--rojo); }
"""


def _pastilla(texto: str, clase: str) -> str:
    return f'<span class="pill {clase}">{html.escape(texto)}</span>'


def _e(texto) -> str:
    return html.escape(str(texto if texto is not None else ""))


def _uri(ruta: Path) -> str:
    return html.escape(ruta.resolve().as_uri())


def _citas_html(ficha: dict) -> str:
    """Las citas de la ficha, con lo que traigan: título, autores, año, identificador con enlace."""
    fuentes = ficha.get("fuentes")
    if not isinstance(fuentes, list) or not fuentes:
        return '<div class="meta">la ficha no trae citas</div>'
    items = []
    for f in fuentes:
        if not isinstance(f, dict):
            continue
        partes = []
        if f.get("titulo"):
            partes.append(f"<em>{_e(f['titulo'])}</em>")
        autores = f.get("autores")
        if isinstance(autores, list) and autores:
            partes.append(_e(", ".join(str(a) for a in autores)))
        if f.get("anio"):
            partes.append(_e(f["anio"]))
        ident = f.get("identificador")
        if ident:
            url = f.get("url")
            ident_html = f"<code>{_e(ident)}</code>"
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                ident_html = f'<a href="{_e(url)}" target="_blank" rel="noopener">{ident_html}</a>'
            partes.append(ident_html)
        items.append(f"<li>{' · '.join(partes) or '<span class=meta>cita sin campos legibles</span>'}</li>")
    return f'<ul class="citas">{"".join(items)}</ul>' if items else '<div class="meta">la ficha no trae citas</div>'


def _etapas_html(etapas: dict) -> str:
    trozos = []
    for nombre in ORDEN_ETAPAS:
        d = etapas[nombre]
        clase = {"complete": "hecha", "skipped": "hecha", "in_progress": "marcha", "blocked": "rota"}.get(
            d["status"], ""
        )
        texto = ETIQUETAS[nombre]["nombre"]
        if d["conteo"] and d["conteo"][1] and d["status"] in ("in_progress", "blocked"):
            texto += f" {d['conteo'][0]}/{d['conteo'][1]}"
        elif d["status"] == "skipped":
            texto += " (omitida)"
        trozos.append(f'<span class="{clase}" title="{_e(d["status"])}">{_e(texto)}</span>')
    return f'<div class="etapas">{"".join(trozos)}</div>'


def _episodio_html(ep: dict, ahora: datetime) -> str:
    run_id = ep.get("run_id")
    estado = _estado_del_run(run_id)
    run_dir = CANAL_VIDEOS_DIR / run_id if run_id else None
    prog = progreso(estado, run_dir) if (estado and run_dir) else None
    ficha_id = ep.get("ficha")
    ficha = _ficha(ficha_id)
    firma = _firma_gate1(ep.get("gate1"))

    # --- Barra y fase ---
    if prog:
        roja = " roja" if prog["bloqueado"] else ""
        barra = (
            f'<div class="barra{roja}"><div class="relleno" style="width:{prog["pct"]:.1f}%"></div>'
            f'<div class="pct">{prog["pct"]:.0f} %</div></div>'
            f'<p class="fase{roja}">{_e(prog["fase"])}</p>'
            f'<div class="meta">run <code>{_e(run_id)}</code> · última escritura del estado: '
            f"{_hora_local(prog['updated_at'])} {_e(_hace(prog['updated_at'], ahora))}</div>"
            + _etapas_html(prog["etapas"])
        )
    elif run_id:
        barra = (
            '<div class="barra"><div class="relleno" style="width:0%"></div><div class="pct">0 %</div></div>'
            f'<p class="fase">Sin estado de run todavía</p><div class="meta">run <code>{_e(run_id)}</code> · '
            f"aún no existe <code>{_e(STATE_DIR.name)}/{_e(run_id)}.json</code></div>"
        )
    else:
        barra = (
            '<div class="barra"><div class="relleno" style="width:0%"></div><div class="pct">0 %</div></div>'
            '<p class="fase">Sin run: el orquestador aún no lo ha creado</p>'
        )

    # --- Enlaces y vídeo ---
    enlaces = []
    video_html = ""
    if run_dir:
        mp4 = config.ruta_publicable(run_dir, "final.mp4")
        if mp4.exists():
            video_html = f'<video controls preload="metadata" src="{_uri(mp4)}"></video>'
            enlaces.append(f'<li><a href="{_uri(mp4)}">abrir <code>final.mp4</code> con el reproductor</a></li>')
        miniatura = config.ruta_publicable(run_dir, "thumbnail.png")
        if miniatura.exists() and not mp4.exists():
            video_html = f'<img class="thumb" src="{_uri(miniatura)}" alt="miniatura">'
        laminas = (CANAL_DIR / "revision" / run_id / "laminas.html") if CANAL_DIR else None
        if laminas and laminas.exists():
            enlaces.append(f'<li><a href="{_uri(laminas)}" target="_blank">revisión de láminas</a></li>')
        if run_dir.exists():
            enlaces.append(f'<li><a href="{_uri(run_dir)}">carpeta del run</a></li>')
    gate1 = ep.get("gate1")
    if gate1 and (BASE_DIR / gate1).exists():
        enlaces.append(f'<li><a href="{_uri(BASE_DIR / gate1)}">informe del gate 1</a> · {_e(firma)}</li>')
    elif gate1:
        enlaces.append(f"<li>informe del gate 1 <code>{_e(gate1)}</code>: {_e(firma)}</li>")
    if ficha_id and CANAL_DATOS_DIR:
        ruta_ficha = CANAL_DATOS_DIR / "fuentes" / f"{ficha_id}.json"
        if ruta_ficha.exists():
            enlaces.append(f'<li><a href="{_uri(ruta_ficha)}">ficha <code>{_e(ficha_id)}</code></a></li>')
        else:
            enlaces.append(f"<li>ficha <code>{_e(ficha_id)}</code>: no existe en <code>datos/fuentes/</code></li>")

    subida_txt = ""
    if prog and prog["subido"]:
        try:
            subida = json.loads((estado.get("stages", {}).get("upload", {}) or {}).get("output") or "{}")
        except json.JSONDecodeError:
            subida = {}
        if isinstance(subida, dict) and subida.get("studio_url"):
            enlaces.append(
                f'<li><a href="{_e(subida["studio_url"])}" target="_blank" rel="noopener">abrir en Studio</a></li>'
            )
        subida_txt = _pastilla("subido · privado", "ok")

    tipo = _pastilla(str(ep.get("tipo", "—")), "wait")
    firma_pill = {"firmado": _pastilla("gate 1 firmado", "ok")}.get(firma, _pastilla(f"gate 1 {firma}", "no"))
    respaldo = ficha.get("nivel_de_respaldo")
    respaldo_txt = f" · {_e(respaldo)}" if respaldo else ""

    return f"""<section class="episodio">
  <div class="cabecera">
    <span class="n">Episodio {_e(ep.get("numero", "?"))}</span>
    <h3>{_e(ep.get("titulo", "(sin título)"))}</h3>
    {tipo} {firma_pill} {subida_txt}
  </div>
  <div class="meta">fecha propuesta {_e(ep.get("fecha_propuesta", "—"))} · acento {_e(ep.get("acento_de_color", "—"))}
    · ficha <code>{_e(ficha_id or "—")}</code>{" · " + _e(ficha.get("certeza")) if ficha.get("certeza") else ""}</div>
  {barra}
  <div class="cuerpo">
    <div>
      {video_html}
      <ul class="enlaces">{"".join(enlaces) or "<li>sin ficheros todavía</li>"}</ul>
    </div>
    <div>
      <div class="meta"><strong>Citas de la ficha</strong>{respaldo_txt}</div>
      {_citas_html(ficha)}
    </div>
  </div>
</section>"""


def _espera_html(calendario: dict) -> str:
    filas = []
    for ep in calendario.get("episodios", []):
        firma = _firma_gate1(ep.get("gate1"))
        if firma != "firmado":
            filas.append(
                f"<tr><td><strong>Gate 1 · episodio {_e(ep.get('numero'))}</strong>: el guion está {_e(firma)}. "
                "Se firma en la casilla <code>## APROBADO</code> del informe, con cita y fecha.</td>"
                f"<td><code>{_e(ep.get('gate1') or '—')}</code></td></tr>"
            )
        estado = _estado_del_run(ep.get("run_id"))
        run_dir = CANAL_VIDEOS_DIR / ep["run_id"] if ep.get("run_id") else None
        if estado and run_dir:
            prog = progreso(estado, run_dir)
            if prog["subido"]:
                filas.append(
                    f"<tr><td><strong>Gate 2 · episodio {_e(ep.get('numero'))}</strong>: está subido como borrador "
                    "privado. Publicarlo, o aprobarlo y fijarle fecha con <code>publishAt</code>, es tuyo y se "
                    "hace en Studio. El <code>.srt</code> se adjunta a mano allí.</td><td>YouTube Studio</td></tr>"
                )
            elif prog["bloqueado"]:
                filas.append(
                    f"<tr><td><strong>Run bloqueado · episodio {_e(ep.get('numero'))}</strong>: {_e(prog['fase'])}. "
                    "Un run bloqueado no avanza solo.</td>"
                    f"<td><code>{_e(STATE_DIR.name)}/{_e(ep.get('run_id'))}.json</code></td></tr>"
                )
    if not filas:
        filas.append(
            "<tr><td>Nada por ahora: los runs están en marcha o esperando a que el pipeline avance.</td><td>—</td></tr>"
        )
    return "<table><tr><th>Qué</th><th>Dónde</th></tr>" + "".join(filas) + "</table>"


def construye(calendario: dict, refresco_s: int | None, ahora: datetime | None = None) -> str:
    ahora = ahora or datetime.now()
    canal = CANAL_PERFIL.get("nombre", CANAL_ACTIVO) if isinstance(CANAL_PERFIL, dict) else CANAL_ACTIVO
    semana = calendario.get("semana_iso", "?")
    episodios = calendario.get("episodios", [])
    meta_refresh = f'<meta http-equiv="refresh" content="{int(refresco_s)}">' if refresco_s else ""
    modo = (
        f"se regenera cada {int(refresco_s)} s mientras corra <code>--vigilar</code> y el navegador recarga solo"
        if refresco_s
        else "generada una vez; para verla avanzar, lánzala con <code>--vigilar</code>"
    )
    cuerpo = "\n".join(_episodio_html(ep, ahora) for ep in episodios)

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">{meta_refresh}
<title>Panel {_e(semana)} · {_e(canal)}</title>
<style>{ESTILO}</style></head><body>
<h1>Panel de la semana · {_e(semana)}</h1>
<p class="sub">{_e(canal)} · {_e(calendario.get("desde", "—"))} a {_e(calendario.get("hasta", "—"))}
 · {len(episodios)} episodios · generada a las {ahora.strftime("%H:%M:%S")} · {modo}</p>

<div class="aviso">
<strong>Esto solo observa.</strong> No aprueba, no publica y no toca ningún run: la barra se calcula del
estado de cada run y de los ficheros de su carpeta, y el vídeo se reproduce desde tu disco. Los gates
se firman donde siempre. Ningún vídeo está público ni puede llegar a estarlo sin ti (gate 2).
</div>

<h2>Los episodios</h2>
{cuerpo}

<h2>Lo que espera tu decisión</h2>
{_espera_html(calendario)}

<p class="sub">Barra pesada por minutos medidos (<code>PESOS_MIN</code> en <code>scripts/panel_semana.py</code>:
láminas {PESOS_MIN["images"]:g} · narración {PESOS_MIN["tts"]:g} · montaje {PESOS_MIN["assembly"]:g} ·
miniatura {PESOS_MIN["thumbnail"]:g} · subida {PESOS_MIN["upload"]:g}, total {TOTAL_MIN:g} min); dentro de láminas y
narración se cuentan los ficheros del run. La firma del gate 1 se lee de la casilla del informe, no del
pipeline. Esta página no guarda nada: <code>.venv\\Scripts\\python scripts/panel_semana.py</code> la rehace.</p>
</body></html>"""


# ============================================== CLI ===================================================


def _calendario_mas_reciente(directorio: Path) -> Path | None:
    candidatos = sorted(p for p in directorio.glob("*.json") if p.is_file())
    return candidatos[-1] if candidatos else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Panel de observación de produce-semana (solo lectura)")
    parser.add_argument("--canal", help="id del canal (canales/<id>/); si falta, CANAL_ACTIVO del .env")
    parser.add_argument("--semana", help="semana ISO del calendario, p. ej. 2026-W37; si falta, la más reciente")
    parser.add_argument(
        "--vigilar",
        nargs="?",
        const=10,
        type=int,
        metavar="N",
        help="regenera cada N segundos (defecto 10) hasta Ctrl+C; la página recarga sola con el mismo N",
    )
    parser.add_argument("--no-abrir", action="store_true", help="no abre el navegador la primera vez")
    args = parser.parse_args()

    if CANAL_DIR is None or CANAL_PERFIL_PATH is None or not CANAL_PERFIL_PATH.exists():
        raise SystemExit(
            "[FAIL] no hay canal usable: pásalo con --canal <id> o pon CANAL_ACTIVO en el .env "
            f"(CANAL_ACTIVO={CANAL_ACTIVO!r}). Los ids son los directorios de canales/ con perfil.json."
        )
    if args.vigilar is not None and args.vigilar <= 0:
        raise SystemExit("[FAIL] --vigilar necesita un número de segundos mayor que 0")

    directorio = CANAL_DIR / "calendario"
    if args.semana:
        origen = directorio / f"{args.semana}.json"
    else:
        origen = _calendario_mas_reciente(directorio) if directorio.is_dir() else None
    if origen is None or not origen.exists():
        raise SystemExit(
            f"[FAIL] el canal {CANAL_ACTIVO!r} no tiene calendario"
            + (f" {args.semana}" if args.semana else "")
            + f" en {directorio}. Lo escribe la skill produce-semana (paso 4); este panel solo lo lee."
        )

    destino = CANAL_DIR / "panel-semana.html"
    primera = True
    try:
        while True:
            try:
                calendario = json.loads(origen.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                # En vigilancia, un calendario a medio escribir no tumba el bucle: se avisa y se reintenta.
                if args.vigilar is None:
                    raise SystemExit(f"[FAIL] {origen} no se puede leer como JSON: {exc}") from None
                print(f"[AVISO] {origen.name} no se pudo leer ({exc}); se reintenta en {args.vigilar} s")
                time.sleep(args.vigilar)
                continue
            destino.write_text(construye(calendario, args.vigilar), encoding="utf-8")
            marca = datetime.now().strftime("%H:%M:%S")
            print(
                f"[OK] {marca} {destino}"
                + (f" · vigilando cada {args.vigilar} s (Ctrl+C para parar)" if primera and args.vigilar else "")
            )
            if primera and not args.no_abrir:
                webbrowser.open(destino.resolve().as_uri())
            primera = False
            if args.vigilar is None:
                break
            time.sleep(args.vigilar)
    except KeyboardInterrupt:
        print("\n[OK] vigilancia parada; la última página generada se queda en", destino)
    return 0


if __name__ == "__main__":
    sys.exit(main())
