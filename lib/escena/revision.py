"""Las páginas de las dos paradas del usuario en el motor de escena (F6.2d), y el guion por partes.

Vienen de `canal/scripts/revisa.py`, `fotogramas.py` y `entrega.py` del experimento video_1, generalizados:

- **Parada 1, tras `activos`** (`pagina_de_activos`): las imágenes nuevas del episodio, en crudo (cada semilla, con
  la elegida marcada) y recortadas, sobre un damero para ver la transparencia; lo que falta por elegir; la escala.
- **Parada 2, tras `escena`** (`pagina_de_fotogramas`): los fotogramas clave de la composición sacados con
  `hyperframes snapshot` antes del render (segundos por fotograma frente a los minutos del render), con su
  etiqueta; los defectos que encontraron las comprobaciones; las correcciones de encuadre; el sonido.
- **El guion por partes** (`guion_por_partes`): cada lámina de voz con sus cues numerados, que es con lo que se
  escribe el guion de escena (`P(12, "palabra")`). Es el `doc/guion.md` que escribía `nuevo.py` en video_1.

Todo va a `<run>/revision/`, que es material de trabajo (`provenance.WORK_DIRS`). Las imágenes van DENTRO de la
página (`data:`), así que se abre sola con doble clic y no depende de que los ficheros sigan ahí.

**Sin un color ni una tipografía del estudio**: la página usa los colores del sistema (`Canvas`, `CanvasText`…) y el
modo claro u oscuro del navegador. La regla de `tests/test_capas.py` para `lib/escena/` vale también aquí.

Los textos de los guiones son DATOS (convención del proyecto): todo lo que llega de un guion se escapa.
"""

from __future__ import annotations

import base64
import html
import io
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from PIL import Image

from lib import config

# Lo ancho que va cada imagen dentro de la página: basta para mirarla y la página no pesa cientos de MB.
ANCHO_EN_LA_PAGINA = 640
ANCHO_DEL_RECORTE = 360
# La hoja numerada de una pizarra va a lo ancho: con ella se eligen las piezas por su número.
ANCHO_DE_LA_HOJA = 1600

CSS_DE_REVISION = """
:root { color-scheme: light dark; }
body { margin: 0; background: Canvas; color: CanvasText; font-size: 16px; line-height: 1.5; }
main { max-width: 1400px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { margin: 0 0 4px; font-size: 26px; }
h2 { margin: 28px 0 8px; font-size: 20px; }
.meta { margin: 0 0 12px; }
.sigue { padding: 10px 14px; border: 2px solid CanvasText; border-radius: 10px; }
.sigue code { font-size: 15px; }
.rejilla { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }
figure { margin: 0; border: 1px solid GrayText; border-radius: 12px; overflow: hidden; }
figure img { width: 100%; display: block; }
figure.elegida { border: 3px solid CanvasText; }
.damero { background: repeating-conic-gradient(Canvas 0 25%, ButtonFace 0 50%) 0 0 / 24px 24px; }
.damero img { max-height: 320px; width: auto; max-width: 100%; margin: 0 auto; }
figcaption { padding: 8px 10px 10px; font-size: 14px; }
.defecto { border-left: 4px solid CanvasText; padding: 4px 10px; margin: 4px 0; }
.nada { color: GrayText; }
"""


def _e(texto) -> str:
    return html.escape(str(texto), quote=True)


def mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _embebida(ruta: Path, ancho: int, transparente: bool) -> str:
    """La imagen como `data:`: PNG si tiene transparencia que enseñar (un recorte), JPEG si no (crudo o fotograma)."""
    with Image.open(ruta) as im:
        im = im.convert("RGBA" if transparente else "RGB")
        im.thumbnail((ancho, ancho * 4))
        buf = io.BytesIO()
        if transparente:
            im.save(buf, "PNG", optimize=True)
            return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        im.save(buf, "JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _figura(src: str, pie: str, *, clase: str = "") -> str:
    return f'<figure class="{clase}"><img src="{src}" alt=""><figcaption>{pie}</figcaption></figure>'


def _pagina(titulo: str, cuerpo: str) -> str:
    return (
        f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{_e(titulo)}</title>'
        f"<style>{CSS_DE_REVISION}</style></head><body><main>{cuerpo}</main></body></html>\n"
    )


def _orden(ep, etapa: str) -> str:
    """La orden para seguir tras una parada: con el canal explícito, como pide el pipeline con varios canales."""
    return f".venv\\Scripts\\python pipeline.py --canal {ep.canal_dir.name} --run-id {ep.run_id} --stage {etapa}"


def _escribe(ep, nombre: str, texto: str) -> Path:
    destino = config.revision_del_run(ep.run_dir) / nombre
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    return destino


# ------------------------------------------------------------------------------------------ parada 1
def pagina_de_activos(
    ep,
    *,
    lote,
    faltan: Sequence[str],
    escala: Sequence[str],
    traidas: Sequence[str],
    hojas: Sequence[tuple[Path, str]] | None = None,
) -> Path:
    """La página de la parada 1: las imágenes nuevas del episodio, en crudo y recortadas. Devuelve su ruta.

    Lo que el episodio trae de la biblioteca del canal (`traidas`) no se enseña imagen a imagen: ya se revisó cuando
    se hizo. Se lista por su nombre, y sus recortes salen entre los del catálogo del run.

    `hojas` son las hojas numeradas de las pizarras separadas (formato «pizarra», F7.10): [(png, pie)], o None si no
    hay ninguna. Van enteras y a lo ancho, porque con ellas se eligen las piezas, y las piezas sueltas no se repiten
    entre los recortes.
    """
    from lib.escena import activos, obrero

    elegidas = activos.lee_elegidas(ep.dir_activos)
    crudos = []
    for a in lote.activos:
        for semilla in a.semillas:
            ruta = activos.crudo(ep.dir_activos, a.nombre, semilla)
            if not ruta.is_file():
                continue
            elegida = elegidas.get(a.nombre) == semilla or len(a.semillas) == 1
            pie = f"<b>{_e(a.nombre)}</b> · semilla {semilla}{' · elegida' if elegida else ''}<br>{_e(a.que)}"
            crudos.append(_figura(_embebida(ruta, ANCHO_EN_LA_PAGINA, False), pie, clase="elegida" if elegida else ""))
    hojas = list(hojas or [])
    recortes = []
    for nombre, d in sorted(obrero.lee_catalogo(ep.dir_activos)["imagenes"].items()):
        ruta = obrero.archivo_de(ep.dir_activos, d)
        if not ruta.is_file() or (hojas and d.get("pizarra") and d.get("numero")):
            continue
        datos = f"{d.get('w')}×{d.get('h')}" + (f" · k {d['k']}" if d.get("k") is not None else "")
        if d.get("cabeza_px") is not None:
            datos += f" · cabeza {d['cabeza_px']} px"
        recortes.append(
            f'<figure><div class="damero"><img src="{_embebida(ruta, ANCHO_DEL_RECORTE, True)}" alt=""></div>'
            f"<figcaption><b>{_e(nombre)}</b> · {_e(datos)}</figcaption></figure>"
        )
    si_falta = (
        "<h2>Falta elegir</h2>"
        + "".join(f'<div class="defecto">{_e(f)}</div>' for f in faltan)
        + "<p>Escribe la semilla elegida en <code>Lote.elegidas</code> del guion de escena y vuelve a lanzar "
        f"<code>{_e(_orden(ep, 'activos'))}</code>.</p>"
        if faltan
        else ""
    )
    sigue = (
        '<p class="sigue">Si las imágenes valen, sigue con<br>'
        f"<code>{_e(_orden(ep, 'escena'))}</code><br>Al seguir, las imágenes nuevas de este episodio entran en la "
        f"biblioteca del canal (<code>{_e(config.biblioteca_del_canal(ep.canal_dir))}</code>) con su procedencia, y "
        "los episodios siguientes las reutilizan sin generarlas otra vez.<br>Si alguna no vale, cambia su semilla o su "
        f"pose en el guion de escena (<code>{_e(ep.guion_py)}</code>) y vuelve a lanzar la etapa "
        "<code>activos</code>.</p>"
        if not faltan
        else ""
    )
    escala_html = (
        "<h2>Escala de las cabezas</h2>" + "".join(f'<div class="defecto">{_e(linea)}</div>' for linea in escala)
        if escala
        else ""
    )
    vacio = '<p class="nada">Este episodio no genera ninguna imagen nueva: usa el catálogo que ya tiene el run.</p>'
    de_la_biblioteca = (
        f"<h2>Traídas de la biblioteca del canal ({len(traidas)})</h2><p>Ya revisadas cuando se hicieron; entran en el "
        f"run con su procedencia: {_e(', '.join(traidas))}.</p>"
        if traidas
        else ""
    )
    de_las_pizarras = (
        f"<h2>Pizarras: las piezas numeradas ({len(hojas)})</h2><p>La tiza de cada pieza sobre la pizarra limpia, con "
        "su caja y su número: el guion de escena las pide por número.</p>"
        + "".join(_figura(_embebida(Path(png), ANCHO_DE_LA_HOJA, False), _e(pie)) for png, pie in hojas)
        if hojas
        else ""
    )
    cuerpo = (
        f"<h1>Parada 1 de 2 · imágenes nuevas del episodio</h1>"
        f'<p class="meta">{_e(ep.run_id)} · {datetime.now():%d-%m-%Y %H:%M}</p>{sigue}{si_falta}'
        f"<h2>Generadas ({len(crudos)})</h2>"
        + (f'<div class="rejilla">{"".join(crudos)}</div>' if crudos else vacio)
        + de_las_pizarras
        + de_la_biblioteca
        + f"<h2>Recortadas ({len(recortes)})</h2>"
        + (f'<div class="rejilla">{"".join(recortes)}</div>' if recortes else '<p class="nada">Ninguna.</p>')
        + escala_html
    )
    return _escribe(ep, "activos.html", _pagina(f"Parada 1 · {ep.run_id}", cuerpo))


# ------------------------------------------------------------------------------------------ parada 2
def pagina_de_fotogramas(
    ep,
    *,
    fotos: Sequence[tuple[float, str, Path]],
    defectos: Mapping[str, Sequence[str]],
    correcciones: Sequence[str],
    sonido: Mapping,
    avisos: Sequence[str],
    biblioteca: Mapping | None = None,
) -> Path:
    """La página de la parada 2: los fotogramas clave de la composición antes del render. Devuelve su ruta.

    `avisos`: lo que el guion avisó al escribirse (dos claves a la vez, una palabra que estaba en el cue de al lado,
    la revisión didáctica del canal). No son defectos: son cosas que mirar. `biblioteca`: lo que `biblia.incorpora`
    hizo al empezar la etapa (qué imágenes del episodio entraron en la biblioteca del canal y cuáles no, y por qué).
    """
    biblioteca_html = ""
    if biblioteca is not None:
        cambios = [*biblioteca["entran"], *biblioteca["actualizadas"]]
        biblioteca_html = (
            f"<h2>Biblioteca del canal ({len(biblioteca['entran'])} nueva(s), {len(biblioteca['actualizadas'])} "
            "actualizada(s))</h2>"
            + (
                f"<p>Entraron con su procedencia en <code>{_e(biblioteca['carpeta'])}</code>: "
                f"{_e(', '.join(cambios))}. Van en git con el guion de escena del episodio.</p>"
                if cambios
                else '<p class="nada">Ninguna imagen nueva de este episodio: la biblioteca no cambia.</p>'
            )
            + "".join(
                f'<div class="defecto"><b>{_e(n)}</b> no entra: {_e(m)}</div>'
                for n, m in biblioteca["no_entran"].items()
            )
        )
    celdas = "".join(
        _figura(_embebida(png, ANCHO_EN_LA_PAGINA, False), f"<b>{mmss(t)}</b> {_e(etiqueta)}")
        for t, etiqueta, png in fotos
    )
    hallados = [(que, d) for que, lista in defectos.items() for d in lista]
    defectos_html = (
        "".join(f'<div class="defecto"><b>{_e(que)}</b>: {_e(d)}</div>' for que, d in hallados)
        if hallados
        else '<p class="nada">Ninguno: las seis comprobaciones pasan.</p>'
    )
    correcciones_html = (
        "".join(f'<div class="defecto">{_e(c)}</div>' for c in correcciones)
        if correcciones
        else '<p class="nada">Ninguna.</p>'
    )
    sonido_html = "".join(f"<li><b>{_e(k)}</b>: {_e(v)}</li>" for k, v in sonido.items())
    avisos_html = (
        "".join(f'<div class="defecto">{_e(a)}</div>' for a in avisos) if avisos else '<p class="nada">Ninguno.</p>'
    )
    cuerpo = (
        "<h1>Parada 2 de 2 · fotogramas clave antes del render</h1>"
        f'<p class="meta">{_e(ep.run_id)} · {datetime.now():%d-%m-%Y %H:%M}</p>'
        '<p class="sigue">Si la escena vale, renderiza con<br>'
        f"<code>{_e(_orden(ep, 'render'))}</code><br>Si algo no vale, corrige el guion de escena "
        f"(<code>{_e(ep.guion_py)}</code>) y vuelve a lanzar la etapa <code>escena</code>: el render se niega a "
        "renderizar un guion o una composición que hayan cambiado desde esta página.</p>"
        f"<h2>Defectos que encontraron las comprobaciones ({len(hallados)})</h2>{defectos_html}"
        f"<h2>Correcciones de encuadre aplicadas ({len(correcciones)})</h2>{correcciones_html}"
        f"<h2>Avisos del guion ({len(avisos)})</h2>{avisos_html}"
        f"<h2>Sonido</h2><ul>{sonido_html}</ul>"
        f"{biblioteca_html}"
        f'<h2>Fotogramas ({len(fotos)})</h2><div class="rejilla">{celdas}</div>'
    )
    return _escribe(ep, "fotogramas.html", _pagina(f"Parada 2 · {ep.run_id}", cuerpo))


def guarda_comprobaciones(
    ep, defectos: Mapping[str, Sequence[str]], correcciones: Sequence[str], avisos: Sequence[str]
) -> Path:
    """Lo que encontraron las comprobaciones, en JSON junto a la página (para leerlo sin abrirla)."""
    texto = json.dumps(
        {
            "defectos": {k: list(v) for k, v in defectos.items()},
            "correcciones": list(correcciones),
            "avisos": list(avisos),
        },
        indent=2,
        ensure_ascii=False,
    )
    return _escribe(ep, "comprobaciones.json", texto + "\n")


# ------------------------------------------------------------------------------------------ el guion por partes
def guion_por_partes(ep, linea, slides: Sequence[Mapping]) -> Path:
    """Cada lámina de voz con sus cues numerados y sus tiempos: con esto se escribe el guion de escena."""
    capitulos = {}
    try:
        crudo = json.loads((ep.run_dir / "slides.json").read_text(encoding="utf-8"))
        capitulos = {int(c["slide_inicial"]): c.get("titulo", "") for c in crudo.get("capitulos") or []}
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        capitulos = {}
    lineas = [
        f"# Guion por partes · {ep.run_id}",
        "",
        f"{len(linea.laminas)} láminas de voz · {mmss(linea.total)} · intro {linea.intro} s, pausa {linea.pausa} s, "
        f'cola {linea.cola} s. Cada línea es un cue: `C12` se ancla con `C(12)`, `F(12)` o `P(12, "palabra")`.',
        "",
    ]
    for k, numero in enumerate(linea.laminas):
        slide = slides[numero - 1] if 0 < numero <= len(slides) else {}
        ini = linea.inicio[k]
        lineas += [
            f"## Lámina {numero}" + (f" · {capitulos[numero]}" if capitulos.get(numero) else ""),
            "",
            f"Vídeo {mmss(ini)} – {mmss(ini + linea.tramos[k])}.",
            "",
        ]
        if slide.get("image_prompt"):
            lineas += [f"> Lámina del run: {slide['image_prompt']}", ""]
        hablan = sorted({h.get("personaje") for h in slide.get("hablantes") or [] if h.get("personaje")})
        if hablan:
            lineas += [f"Hablan: {', '.join(hablan)}.", ""]
        lineas += [f"- `C{c.n}` ({mmss(c.ini)}) {c.texto}" for c in linea.cues if c.lamina == k]
        lineas.append("")
    return _escribe(ep, "guion-por-partes.md", "\n".join(lineas))
