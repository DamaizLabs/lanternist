"""Las cuatro etapas del motor de escena (F6.2d): `alinea`, `activos`, `escena` y `render`.

`pipeline.py` las llama con un `Episodio` (`lib/escena/episodio.py`) y lleva el estado del run, la procedencia y las
paradas; aquí está lo que cada etapa hace, sin estado del run, para poder probarlo con un canal ficticio.

- `alinea`: las marcas por palabra con whisper (`lib/alineador.py`, la misma alineación del montaje) y el `.srt`.
  Deja `subtitulos/alineacion-resultado.json`, `subir-al-canal/subtitulos.<idioma>.srt` y
  `revision/guion-por-partes.md`. GPU: whisper.
- `activos`: las imágenes nuevas del guion de escena con Qwen-Image-Edit, el obrero y la escala de cabezas. Deja
  `activos/` y la **parada 1** (`revision/activos.html`). GPU: ComfyUI y el obrero.
- `escena`: la puesta en escena y, en cuanto está construida, **las imágenes nuevas que el usuario aprobó en la parada 1
  y que usa el guion entran en la biblioteca del canal** (`biblia.incorpora`, fila 208); luego su encuadre corregido, el
  sonido, las comprobaciones, la composición y los fotogramas clave. Deja `sonido/`, `biblioteca/`, `composicion/` y la
  **parada 2** (`revision/fotogramas.html`). GPU: ComfyUI (el lecho, si el canal lleva música) y Chrome.
- `render`: el vídeo de la composición revisada, su sonoridad, su marca de IA (OC1.5) y `montaje.json`. Deja
  `subir-al-canal/final.mp4`. GPU: Chrome y, después, la marca (`lib/marca_ia.py`).

Y una pieza de la etapa `thumbnail` del pipeline, porque en un rehecho la miniatura sale de esta escena:
`fotogramas_sin_karaoke`, los fotogramas de la composición renderizada sin la capa del karaoke (fila 246). GPU: Chrome.

**Una sola fuente para los cues y el `.srt`** (auditoría de F6.2b, recomendación 5): el `.srt` de este motor son los
cues de la línea de tiempo (`LineaDeTiempo.lineas_de_subtitulo`), con sus tiempos del vídeo. No se trocea otra vez.

**Lo que se renderiza es lo que se revisó**: la parada 2 apunta el sha256 de la composición y el del guion de
escena, y `render` se niega si cualquiera de los dos ha cambiado desde entonces.

**Toda la composición tiene procedencia** (decisión 5): cada fichero que `compone` copia sale del catálogo de
activos, de la biblioteca del run o del sonido derivado; lo que no, para la etapa antes de componer.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

from lib import config, marca_ia, musica, provenance
from lib.escena import ajustes, audio, compone, comprobaciones, encuadre, revision
from lib.escena import render as _render
from lib.escena.episodio import Episodio, carga_guion, lote_de, puesta_de


class ErrorDeEtapa(RuntimeError):
    """Una etapa del motor de escena no puede seguir: el mensaje dice qué falta y qué hacer."""


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


# Lo que se renderiza de una composición: su página, su configuración y todo lo que la página carga.
_LO_QUE_SE_RENDERIZA = ("index.html", "hyperframes.json")


def huella_de_composicion(carpeta: str | Path) -> str:
    """El sha256 de lo que se renderiza de una composición: `index.html`, `hyperframes.json` y `assets/` entera.

    Es la huella que apunta la parada 2 y que el render comprueba (auditoría de F6.2d, recomendación 3): con solo la
    de `index.html`, una imagen de `assets/` cambiada a mano tras la revisión se habría renderizado sin revisar. Lo
    demás que haya en la carpeta (lo que deje HyperFrames al fotografiarla) no cuenta: no entra en el vídeo.
    """
    carpeta = Path(carpeta)
    h = hashlib.sha256()
    ficheros = [carpeta / n for n in _LO_QUE_SE_RENDERIZA if (carpeta / n).is_file()]
    ficheros += sorted(p for p in (carpeta / "assets").rglob("*") if p.is_file())
    for f in ficheros:
        h.update(f.relative_to(carpeta).as_posix().encode("utf-8") + b"\0" + hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def _slides(ep: Episodio) -> list[dict]:
    try:
        return json.loads((ep.run_dir / "slides.json").read_text(encoding="utf-8")).get("slides") or []
    except (OSError, json.JSONDecodeError) as error:
        raise ErrorDeEtapa(f"no se puede leer el slides.json del run: {error}") from None


def _limpia(carpeta: Path) -> Path:
    """Vacía una carpeta de trabajo: lo que quede de una pasada anterior no se mezcla con esta."""
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    return carpeta


# ------------------------------------------------------------------------------------------ alinea
def alinea(ep: Episodio) -> dict:
    """Las marcas por palabra de la narración, la línea de tiempo y el `.srt` con los mismos cues que el karaoke.

    Comprueba antes de gastar la GPU lo que se puede comprobar sin ella: el bloque `escena` (ya al crear el
    `Episodio`), el de subtítulos del canal (`subtitulos.ajustes`) y que cada lámina con narración tenga su wav.
    """
    from lib import alineador, subtitulos

    cfg = subtitulos.ajustes(ep.perfil)
    # Los idiomas a los que se traducirá este `.srt` (F7.11): una lista mal escrita para aquí, sin GPU, y no en la
    # traducción.
    subtitulos.traducciones(ep.perfil, origen=ep.idioma)
    items = []
    for numero, slide in enumerate(_slides(ep), start=1):
        if not (slide.get("narration") or "").strip():
            continue
        wav = config.audio_de_lamina(ep.run_dir, numero)
        if not wav.is_file():
            raise ErrorDeEtapa(f"la lámina {numero} tiene narración y no está su audio ({wav}): falta la etapa tts")
        items.append({"id": f"slide-{numero:02d}", "audio": str(wav)})
    if not items:
        raise ErrorDeEtapa("el run no tiene ni una lámina con narración y audio: no hay nada que alinear")
    try:
        _render.exige_gpu_libre()
    except _render.ErrorDeRender as error:
        raise ErrorDeEtapa(str(error)) from None
    print(f"  [ALINEA] {len(items)} lámina(s) con {cfg['modelo_alineacion']}", flush=True)
    resultado = alineador.alinea(items, config.alineacion_del_run(ep.run_dir).parent, cfg)
    linea = ep.linea()
    srt = None
    if cfg["activos"] and cfg.get("srt"):
        # Copias de los cues: recortar un solape o alargar una línea corta en el `.srt` no mueve el cue.
        lineas = [(grupo, 0.0) for grupo in linea.lineas_de_subtitulo()]
        subtitulos.recorta_solapes(lineas)
        subtitulos.estira_lineas_cortas(lineas)
        srt = config.dir_subir_al_canal(ep.run_dir, crear=True) / f"subtitulos.{ep.idioma}.srt"
        subtitulos.escribe_srt(lineas, srt)
    registro = {
        "modelo_alineacion": cfg["modelo_alineacion"],
        "licencia": subtitulos.LICENCIA_ALINEADOR,
        "url": subtitulos.URL_ALINEADOR,
        "origen": "alineación en local con .venv-voz, sin red (HF_HUB_OFFLINE=1)",
        "idioma": ep.idioma,
        "ass": None,
        "srt": str(srt) if srt else None,
        "quemado": False,
        "lineas": len(linea.cues),
        "texto": "del guion (slides.json); del audio solo se toman los tiempos",
        "lineas_del_srt": "los cues de la línea de tiempo del motor de escena: una línea por cue, los del karaoke",
        "por_lamina": linea.por_lamina,
        "load_seconds": resultado.get("load_seconds"),
    }
    (ep.run_dir / provenance.SUBTITLE_RECORDS_FILENAME).write_text(
        json.dumps([registro], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    partes = revision.guion_por_partes(ep, linea, _slides(ep))
    return {
        "alineacion": config.alineacion_del_run(ep.run_dir),
        "srt": srt,
        "cues": len(linea.cues),
        "informe": linea.informe(),
        "guion_por_partes": partes,
    }


# ------------------------------------------------------------------------------------------ activos
def activos(ep: Episodio) -> dict:
    """Las imágenes nuevas del guion de escena: genera, recorta lo elegido, iguala cabezas y escribe la parada 1.

    Relanzarla solo genera lo que falta (`activos.genera`); lo elegido se recorta otra vez. Lo que se generó con
    varias semillas y no tiene elegida en `Lote.elegidas` no se recorta: sale en la página como «falta elegir» y la
    etapa no se da por hecha (`faltan`), así que la parada 1 no se puede pasar.
    """
    from lib.escena import activos as act
    from lib.escena import biblia, obrero

    modulo = carga_guion(ep)
    lote = lote_de(ep, modulo)
    # Lo que ya está en la biblioteca del canal no se pide a Qwen (fila 208): se trae con `Lote.biblioteca`. Se mira
    # antes de tocar la GPU. Lo que puso este mismo episodio sí se puede rehacer (es corregirlo), y una imagen que el
    # guion pide en los DOS sitios es una sustitución a propósito, solo para este episodio.
    repetidas = {
        n: de
        for n, de in biblia.ajenas(
            ep.canal_dir, [n for a in lote.activos for n in (a.piezas or (a.nombre,))], episodio=ep.run_id
        ).items()
        if n not in lote.biblioteca
    }
    if repetidas:
        raise ErrorDeEtapa(
            f"el guion pide a Qwen {len(repetidas)} imagen(es) que ya están en la biblioteca del canal: "
            f"{', '.join(f'{n} (de {de})' for n, de in repetidas.items())}. Pídelas en `Lote.biblioteca` y quítalas "
            "de `Lote.activos`: la etapa las trae sin gastar GPU. Si quieres otra versión, dale otro nombre, y entrará "
            "en la biblioteca al pasar la parada 1 sin pisar la que ya está."
        )
    # Lo que el episodio reutiliza de la biblioteca del canal entra antes que lo nuevo: una imagen nueva que se llame
    # igual que una de la biblioteca (pedida en los dos sitios) la sustituye en el catálogo del run.
    traidas = biblia.trae(ep.canal_dir, lote.biblioteca, ep.dir_activos) if lote.biblioteca else []
    generados = act.genera(lote.activos, ep.dir_activos, ep.dir_trabajo) if lote.activos else []
    for nombre, semilla in lote.elegidas.items():
        act.elige(ep.dir_activos, nombre, semilla)
    listos, faltan = [], []
    for a in lote.activos:
        try:
            act.elegida(ep.dir_activos, a)
            listos.append(a)
        except act.ErrorDeActivos as error:
            faltan.append(str(error))
    if listos:
        act.recorta_elegidas(listos, lote.personajes, ep.dir_activos, ep.dir_trabajo)
    if lote.extra and not faltan:
        obrero.ejecuta(list(lote.extra), ep.dir_activos, ep.dir_trabajo)
    # Las pizarras del formato «pizarra» (F7.10) se separan en tiza y piezas cuando el obrero ya las ha ampliado.
    pizarras = []
    if lote.pizarras and not faltan:
        from lib.escena import pizarra

        pizarras = pizarra.separa_lote(lote.pizarras, ep.dir_activos, config.revision_del_run(ep.run_dir))
    escala = act.escala(listos, lote.personajes, ep.dir_activos) if any(a.pj for a in listos) and not faltan else []
    hojas = [(h["hoja"], f"{h['nombre']}: {h['piezas']} piezas numeradas") for h in pizarras]
    pagina = revision.pagina_de_activos(ep, lote=lote, faltan=faltan, escala=escala, traidas=traidas, hojas=hojas)
    return {
        "pagina": pagina,
        "generados": len(generados),
        "recortados": len(listos),
        "traidas": len(traidas),
        "faltan": faltan,
        "pizarras": pizarras,
    }


# ------------------------------------------------------------------------------------------ escena
def _lecho(ep: Episodio, total: float, cfg: Mapping) -> Path:
    """El lecho del episodio: el que ya está si dura lo mismo, o uno nuevo con ACE-Step (`musica.genera_lecho`)."""
    from lib import comfy_client as cc

    lecho = ep.run_dir / "lecho.wav"
    registro = ep.run_dir / provenance.MUSIC_RECORDS_FILENAME
    if lecho.is_file() and registro.is_file():
        previos = json.loads(registro.read_text(encoding="utf-8"))
        if previos and previos[-1].get("duracion_s") == round(total, 2):
            return lecho  # generar otra vez cuesta minutos de GPU y daría el mismo lecho (semilla del run)
    if not cc.server_is_alive():
        try:
            _render.exige_gpu_libre()
        except _render.ErrorDeRender as error:
            raise ErrorDeEtapa(str(error)) from None
    with cc.comfy_server():
        generado = musica.genera_lecho(total, ep.run_dir, None, perfil=ep.perfil)
        cc.free_memory()  # la GPU queda para lo que viene detrás (los fotogramas, el render)
    return Path(generado["file"])


def _momentos_por_plano(datos: Mapping) -> list[tuple[float, str]]:
    """Sin momentos del guion: el medio de cada plano, que enseña cada set y cada encuadre una vez."""
    ultimo = datos["duracion"] - 1 / datos["fps"]
    return [
        (round(min(ultimo, (p["t0"] + p["t1"]) / 2), 3), f"{p['id']} · {Path(p['fondo']['src']).stem}")
        for p in datos["planos"]
    ]


def _exige_procedencia(ep: Episodio, assets: Mapping[str, Path]) -> None:
    """Todo lo que la composición copia tiene su entrada en `assets.json`, salvo el sonido derivado de `sonido/`."""
    informe = provenance.sync(ep.run_dir, verbose=False)
    registrados = {a["id"] for a in provenance.read_ledger(ep.run_dir)["assets"]}
    sonido = config.sonido_del_run(ep.run_dir).resolve()
    sin = []
    for clave, fichero in assets.items():
        ruta = Path(fichero).resolve()
        if ruta.is_relative_to(sonido):
            continue
        if not ruta.is_relative_to(ep.run_dir.resolve()) or provenance.asset_id(ep.run_dir, ruta) not in registrados:
            sin.append(f"{clave} ← {ruta.name}")
    if sin:
        raise ErrorDeEtapa(
            f"la composición usaría {len(sin)} fichero(s) sin procedencia en assets.json: {sin[:8]}. Todo lo que entra "
            "en el vídeo tiene que ser un asset del run con su registro: los activos los registra el "
            f"obrero, los efectos y las fuentes la biblioteca del estudio (conteo del run: cuadra={informe['cuadra']})"
        )


def escena(ep: Episodio, *, snapshot=None) -> dict:
    """La biblioteca que crece, el sonido, la puesta en escena, las comprobaciones, la composición y la parada 2.

    Esta etapa solo corre tras la parada 1 (el pipeline se niega sin `activos` hecha), así que, en cuanto la puesta
    está construida, hace lo que el usuario aprobó allí: las imágenes nuevas que usa el guion de escena entran en la
    biblioteca del canal con su procedencia (`biblia.incorpora`, fila 208). Lo que el guion ya no usa (una imagen
    rechazada en la parada 1) no entra. Volver a lanzarla no duplica nada. `snapshot` es `render.snapshot` (Chrome con
    la GPU); las pruebas sin GPU pasan uno que no la usa.
    """
    from lib.escena import biblia

    snapshot = snapshot or _render.snapshot
    modulo = carga_guion(ep)
    linea = ep.linea()
    puesta = puesta_de(ep, modulo)
    datos = puesta.guion.datos()
    # `datos()` es lo último que pide imágenes al catálogo: con él, `usadas` tiene todas las que salen en el vídeo.
    a_la_biblioteca = biblia.incorpora(ep.canal_dir, ep.dir_activos, episodio=ep.run_id, usadas=puesta.guion.usadas)
    correcciones = encuadre.corrige(datos)
    if puesta.franja_karaoke_y is not None:
        correcciones += encuadre.aparta_de_caras(datos, franja_inferior_y=puesta.franja_karaoke_y)

    # El sonido: la narración con sus pausas, el lecho si el canal lleva música, y los efectos de la biblioteca.
    cfg_musica = musica.ajustes(ep.perfil)
    con_musica = bool(cfg_musica["activa"])
    sonido = _limpia(config.sonido_del_run(ep.run_dir))
    voces = [config.audio_de_lamina(ep.run_dir, n) for n in linea.laminas]
    narr = audio.narracion(linea, voces, sonido / "narracion.wav", normaliza=con_musica)
    pistas = [audio.pista_entera(audio.SRC_NARRACION, linea.total, audio.PISTA_NARRACION, "narracion")]
    assets: dict[str, Path] = {audio.SRC_NARRACION: narr["archivo"]}
    resumen_sonido = {
        "narración": f"{narr['duracion_s']} s ({'normalizada' if con_musica else 'tal cual'})",
        "música": "no (el canal no lleva lecho: musica.activa = false)" if not con_musica else "",
    }
    if con_musica:
        lecho = _lecho(ep, linea.total, cfg_musica)
        apartado = audio.mezcla_lecho(narr["archivo"], lecho, sonido / "lecho-apartado.wav", cfg_musica, linea.total)
        pistas.append(audio.pista_entera(audio.SRC_LECHO, linea.total, audio.PISTA_LECHO, "lecho"))
        assets[audio.SRC_LECHO] = apartado["archivo"]
        voz_lufs, lecho_lufs = musica.medicion(narr["archivo"])["lufs"], musica.medicion(apartado["archivo"])["lufs"]
        bajo = round(voz_lufs - lecho_lufs, 1) if voz_lufs is not None and lecho_lufs is not None else None
        resumen_sonido["música"] = f"sí, {bajo} LU por debajo de la voz una vez apartada"
    css = Path(puesta.css).read_text(encoding="utf-8")
    bib = audio.biblioteca(ep.run_dir, puesta.guion.sonidos, css, linea.total)
    pistas += bib["audios"]
    assets.update(bib["assets"])
    resumen_sonido["efectos"] = f"{len(bib['audios'])} en {len({a['pista'] for a in bib['audios']})} pista(s)"
    if bib["descartados"]:
        resumen_sonido["efectos descartados"] = "; ".join(bib["descartados"])
    datos["audios"] = pistas

    # Las imágenes: el catálogo del episodio y lo que la puesta añada. Todo con procedencia.
    from lib.escena import obrero

    assets.update(obrero.archivos_para_compone(ep.dir_activos))
    assets.update({clave: Path(fichero) for clave, fichero in puesta.assets.items()})
    _exige_procedencia(ep, assets)

    halladas = comprobaciones.todas(datos, linea)
    defectos = {que: [str(d) for d in lista] for que, lista in halladas.items()}
    if defectos.get("duracion"):
        raise ErrorDeEtapa(f"el GUION y su sonido no duran lo mismo: {defectos['duracion']}")
    composicion = _limpia(config.composicion_del_run(ep.run_dir))
    index = compone.compone(datos, assets, puesta.css, composicion)
    huella = huella_de_composicion(composicion)

    momentos = sorted(puesta.momentos or _momentos_por_plano(datos))
    rev = config.revision_del_run(ep.run_dir)
    fotos_dir = _limpia(rev / "fotogramas")
    pngs = snapshot(composicion, rev / "log", [t for t, _ in momentos], fotos_dir)
    if len(pngs) != len(momentos):
        raise ErrorDeEtapa(f"se pidieron {len(momentos)} fotogramas y snapshot dio {len(pngs)} (en {fotos_dir})")
    fotos = [(t, etiqueta, Path(png)) for (t, etiqueta), png in zip(momentos, pngs)]
    # Los avisos del guion (dos claves a la vez, una palabra que estaba en otro cue, lo que revise el canal) no paran
    # nada: se enseñan en la parada 2, que es donde se decide.
    avisos = list(dict.fromkeys(puesta.guion.avisos))
    revision.guarda_comprobaciones(ep, defectos, correcciones, avisos)
    pagina = revision.pagina_de_fotogramas(
        ep,
        fotos=fotos,
        defectos=defectos,
        correcciones=correcciones,
        sonido=resumen_sonido,
        avisos=avisos,
        biblioteca=a_la_biblioteca,
    )
    return {
        "biblioteca": a_la_biblioteca,
        "pagina": pagina,
        "composicion": index,
        "huella_composicion": huella,
        "huella_guion": ep.huella_del_guion(),
        "defectos": defectos,
        "correcciones": correcciones,
        "avisos": avisos,
        "planos": len(datos["planos"]),
        "audios": len(pistas),
        "fotogramas": len(fotos),
    }


# ------------------------------------------------------------------------------------------ render
def _herramientas() -> dict:
    """Con qué se renderizó: versión de HyperFrames (la fijada en `motor/`) y el Chrome del manifiesto (fila 201)."""
    fuera = {"ffmpeg": provenance.ffmpeg_version()}
    try:
        fuera["hyperframes"] = json.loads(
            (config.HYPERFRAMES_CLI.parents[1] / "package.json").read_text(encoding="utf-8")
        )["version"]
    except (OSError, json.JSONDecodeError, KeyError):
        fuera["hyperframes"] = None
    try:
        fuera["chrome"] = json.loads(config.CHROME_WEBGPU_MANIFIESTO.read_text(encoding="utf-8")).get("chrome_headless")
    except (OSError, json.JSONDecodeError):
        fuera["chrome"] = None
    return fuera


OBJETO_DEL_CATALOGO = '<img class="obj"'  # lo que escribe `Guion.dibujo` para una imagen del catálogo


def montaje(
    linea, datos: Mapping, salida: str, render_s: float, sonido: Mapping, *, objetos: int, formato: str
) -> dict:
    """`montaje.json` del motor de escena, con el contrato del motor viejo (regla 7 del plan de F6.2).

    `formato` es el del catálogo en que se hizo el vídeo (`ajustes.formato`, F7.11): la declaración de IA elige su
    línea de imagen con él.

    `detalle[]` va POR LÁMINA DE VOZ: `plano` (su orden), `slide` (su número en slides.json), `segundos` (lo que
    dura su voz) y, además, `inicio_s`: dónde empieza en el vídeo. Hace falta porque aquí entre lámina y lámina hay
    pausas, y sumar los `segundos` de las anteriores (lo que hacen los capítulos y la integridad de la narración con
    el motor viejo, donde no las hay) daría un inicio falso; los dos leen `inicio_s` cuando está.
    """
    detalle = []
    for k, numero in enumerate(linea.laminas):
        ini, dura = linea.inicio[k], linea.tramos[k]
        fin = ini + dura
        detalle.append(
            {
                "plano": k + 1,
                "slide": numero,
                "inicio_s": round(ini, 3),
                "segundos": round(dura, 3),
                "fin_s": round(fin, 3),
                "silencio_tras_s": round((linea.inicio[k + 1] if k + 1 < len(linea.laminas) else linea.total) - fin, 3),
                "planos_de_escena": [p["id"] for p in datos["planos"] if p["t0"] < fin and p["t1"] > ini],
            }
        )
    minutos = linea.total / 60
    return {
        "motor": "escena",
        # El formato del catálogo (F7.11): lo lee la declaración de IA (`lib/publicacion.py → declaracion_de_ia`). Un
        # `montaje.json` anterior no lo lleva y su declaración sigue siendo la de siempre.
        "formato": formato,
        "salida": salida,
        "duracion_s": round(linea.total, 3),
        "fps": datos["fps"],
        "resolucion": f"{datos['marco']['w']}x{datos['marco']['h']}",
        "laminas": len(linea.laminas),
        "planos": len(datos["planos"]),
        # Cuántas imágenes de IA se mueven en la escena: los actores de todos los planos y los elementos que llevan una
        # imagen del catálogo (`Guion.dibujo`: un objeto que entra, flota o se balancea; revisión de F6.8, R2). La
        # declaración de IA lo lee: sin ninguna, el vídeo son ilustraciones fijas con movimiento de cámara (el formato
        # «láminas», F6.8), no escenas animadas (`lib/publicacion.py → declaracion_de_ia`).
        "actores": sum(len(p["actores"]) for p in datos["planos"]) + objetos,
        "laminas_por_minuto": round(len(linea.laminas) / minutos, 2) if minutos else None,
        "detalle": detalle,
        "silencios": {"intro_s": linea.intro, "entre_partes_s": linea.pausa, "cola_s": linea.cola},
        "transiciones": [x["tipo"] for x in datos["transiciones"]],
        "movimientos": [],
        "cronometraje": {
            "render_s": round(render_s, 1),
            "factor_tiempo_real": round(render_s / linea.total, 2) if linea.total else None,
        },
        "herramientas": _herramientas(),
        "sonido": dict(sonido),
    }


def render(ep: Episodio, *, huella_composicion: str, huella_guion: str, renderiza=None, marca=None) -> dict:
    """El vídeo de la composición que se revisó en la parada 2, con su sonoridad, su marca de IA y su `montaje.json`.

    Para si la composición o el guion de escena cambiaron desde la parada 2 (sus sha256 no son los apuntados):
    lo que se renderiza tiene que ser lo que el usuario vio. `renderiza` es `render.render`.

    **La marca de IA va la última** (OC1.5, art. 50.2 del AI Act): el render y la sonoridad dejan
    `sonido/final-sin-marca.mp4`, y `marca` (`marca_ia.marca_video`) escribe `subir-al-canal/final.mp4` con la imagen y
    el audio marcados y firmado con C2PA. Su registro va a `montaje.json → marca_ia`. Si la marca falla, no queda
    `final.mp4`: un vídeo sin marca no se entrega.
    """
    renderiza = renderiza or _render.render
    marca = marca or marca_ia.marca_video
    composicion = config.composicion_del_run(ep.run_dir)
    index = composicion / "index.html"
    if not index.is_file():
        raise ErrorDeEtapa(f"no está la composición ({index}): falta la etapa escena")
    if huella_de_composicion(composicion) != huella_composicion:
        raise ErrorDeEtapa(
            "la composición ha cambiado desde la parada 2 (su index.html o algún fichero de assets/): lo que se "
            "renderizaría no es lo que se revisó. Vuelve a lanzar la etapa escena y mira su página antes de renderizar."
        )
    if not ep.guion_py.is_file() or ep.huella_del_guion() != huella_guion:
        raise ErrorDeEtapa(
            f"el guion de escena ({ep.guion_py}) ha cambiado desde la parada 2: vuelve a lanzar la etapa escena para "
            "componer y revisar lo nuevo antes de renderizar."
        )
    linea = ep.linea()
    datos = compone.lee_guion(index)
    cfg_musica = musica.ajustes(ep.perfil)
    # Antes de gastar la GPU: un perfil con dos formatos para aquí y no después del render.
    try:
        formato = ajustes.formato(ep.perfil)
    except ajustes.ErrorDeAjustes as error:
        raise ErrorDeEtapa(str(error)) from None
    final = config.dir_subir_al_canal(ep.run_dir, crear=True) / "final.mp4"
    # El vídeo antes de la marca es material de trabajo (`sonido/` está en `provenance.WORK_DIRS`): no es un asset.
    sin_marca = config.sonido_del_run(ep.run_dir) / "final-sin-marca.mp4"
    sin_marca.parent.mkdir(parents=True, exist_ok=True)
    rev = config.revision_del_run(ep.run_dir)
    dir_log = rev / "log"
    # El vídeo de una pasada anterior no se queda donde la subida lo tomaría por el nuevo si este render falla.
    final.unlink(missing_ok=True)
    inicio = time.perf_counter()
    if cfg_musica["activa"]:
        sin_normalizar = config.sonido_del_run(ep.run_dir) / "final-sin-normalizar.mp4"
        renderiza(composicion, sin_normalizar, dir_log)
        medido = audio.normaliza_video(sin_normalizar, sin_marca, cfg_musica)
        sonido = {"normalizado": True, "medicion": medido}
    else:
        renderiza(composicion, sin_marca, dir_log)
        sonido = {"normalizado": False, "medicion": musica.medicion(sin_marca)}
    render_s = time.perf_counter() - inicio
    try:
        registro_de_la_marca = marca(sin_marca, final)
    except marca_ia.ErrorDeMarca as error:
        final.unlink(missing_ok=True)
        raise ErrorDeEtapa(f"la marca de IA no se pudo poner, así que no hay final.mp4: {error}") from None
    # Las imágenes del catálogo que van como elemento (`Guion.dibujo`): están en el DOM de la página, no en su GUION.
    objetos = index.read_text(encoding="utf-8").count(OBJETO_DEL_CATALOGO)
    resumen = montaje(
        linea,
        datos,
        f"{config.DIR_SUBIR_AL_CANAL}/final.mp4",
        render_s,
        sonido,
        objetos=objetos,
        formato=formato,
    )
    resumen["marca_ia"] = registro_de_la_marca
    (ep.run_dir / provenance.ASSEMBLY_SUMMARY_FILENAME).write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"salida": final, "montaje": resumen}


# ------------------------------------------------------------------------------------------ miniatura
# La capa que `compone` escribe para el karaoke y la regla que la esconde en la copia que se fotografía. La regla va la
# última de la cabeza, así que gana a la de `CSS_ESTUDIO` sin tocar nada más de la página.
_CAPA_DEL_KARAOKE = b'<div id="karaoke">'
_SIN_KARAOKE = b"<style>#karaoke { display: none !important; }</style>\n</head>"


def fotogramas_sin_karaoke(
    run_dir: str | Path, segundos: list[float], *, huella_composicion: str, snapshot=None
) -> dict:
    """Los fotogramas de la escena renderizada en `segundos`, sin el karaoke: de ellos sale la miniatura (fila 246).

    **No salen de `final.mp4`, y es a propósito.** El vídeo lleva el karaoke quemado abajo, que es justo donde va el
    texto de la miniatura (medido el 02-10 en la bici, a 420 s). Y en los silencios entre partes solo están las tarjetas
    de capítulo. Así que salen de la **misma composición que se renderizó**: su huella tiene que ser la que apuntó la
    parada 2, y se fotografía una copia con una sola regla más, la que esconde `#karaoke`. La composición del run no se
    toca: su huella la protege.

    Para sin GPU y antes de copiar nada si un instante cae fuera del vídeo o si la composición ya no es la renderizada.
    Deja los PNG en `revision/miniatura/`. `snapshot` es `render.snapshot`; las pruebas pasan uno sin Chrome.
    """
    snapshot = snapshot or _render.snapshot
    run_dir = Path(run_dir)
    composicion = config.composicion_del_run(run_dir)
    index = composicion / "index.html"
    if not index.is_file():
        raise ErrorDeEtapa(f"no está la composición ({index}): sin la escena renderizada no hay fotograma")
    if huella_de_composicion(composicion) != huella_composicion:
        raise ErrorDeEtapa(
            "la composición ha cambiado desde la parada 2, así que ya no es la que se renderizó y su fotograma no "
            "sería del vídeo. Vuelve a lanzar las etapas escena y render antes de la miniatura."
        )
    datos = compone.lee_guion(index)
    ultimo = float(datos["duracion"]) - 1 / float(datos["fps"])
    fuera = [t for t in segundos if not 0 <= t <= ultimo]
    if not segundos or fuera:
        raise ErrorDeEtapa(
            f"el vídeo dura {float(datos['duracion']):g} s y su último fotograma está en el {ultimo:g}: "
            + (f"{', '.join(f'{t:g}' for t in fuera)} cae(n) fuera" if fuera else "no se ha pedido ningún instante")
        )
    pagina = index.read_bytes()
    if pagina.count(_CAPA_DEL_KARAOKE) != 1 or pagina.count(b"</head>") != 1:
        raise ErrorDeEtapa(
            f"no encuentro una sola capa del karaoke ({_CAPA_DEL_KARAOKE.decode()}) y una sola cabeza en {index}: si "
            "compone.py ha cambiado cómo la escribe, esta función tiene que saberlo, o el karaoke saldría en la "
            "miniatura"
        )

    rev = config.revision_del_run(run_dir)
    destino = _limpia(rev / "miniatura")
    config.ESCENA_RENDER_TMP.mkdir(parents=True, exist_ok=True)
    trabajo = Path(tempfile.mkdtemp(prefix="mini-", dir=config.ESCENA_RENDER_TMP))
    try:
        copia = trabajo / "composicion"
        shutil.copytree(composicion / "assets", copia / "assets")
        for nombre in _LO_QUE_SE_RENDERIZA:
            if (composicion / nombre).is_file():
                shutil.copy2(composicion / nombre, copia / nombre)
        # En bytes, para que la copia sea la página renderizada con una regla más y nada más (ni los finales de línea).
        (copia / "index.html").write_bytes(pagina.replace(b"</head>", _SIN_KARAOKE))
        pngs = snapshot(copia, rev / "log", list(segundos), trabajo / "fotos")
        if len(pngs) != len(segundos):
            raise ErrorDeEtapa(f"se pidieron {len(segundos)} fotogramas y snapshot dio {len(pngs)}")
        fotos = []
        for t, png in zip(segundos, pngs):
            sale = destino / f"fotograma-{t:g}s.png"
            shutil.move(str(png), str(sale))
            fotos.append(sale)
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)
    return {"fotogramas": fotos, "duracion_s": float(datos["duracion"]), "herramientas": _herramientas()}
