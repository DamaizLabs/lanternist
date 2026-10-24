"""Página del calendario editorial: qué hay producido, qué está subido y qué espera al usuario.

Correr:  .venv\\Scripts\\python scripts/pagina_calendario.py [--semana 2026-W37] [--no-abrir]

## Por qué una página y no un JSON

Criterio del 31-08 (addendum fila 40): **la consola es la interfaz, pero donde interviene
una persona se le da un entregable que se abre con doble clic**. Un `perfil.json` y un comando de
terminal «no son nada accesibles» cuando lo que hay que hacer es mirar cuatro miniaturas y decidir.
El patrón es el mismo de `marca/identidad-del-canal.html`: tabla de qué falta, imágenes a la vista y
enlace a cada pantalla.

**Se queda en local** (decisión cerrada 6) y **se regenera entera** en cada ejecución: no guarda
estado propio, así que no puede contradecir al estado del run como ya pasó una vez con el checklist
de la marca.

## De dónde sale cada dato

- El plan editorial, de `canales/<id>/calendario/<semana>.json`.
- **Lo producido y lo subido, del estado del run** (`canales/<id>/datos/estado/<run>.json`), que es
  la fuente de verdad. El `video_id` no se teclea aquí: sale de la salida de la etapa `upload`.
- La duración, de `<run>/montaje.json`.

Lo que la página NO puede decir es si el vídeo está público, y es a propósito: el scope
`youtube.upload` no permite leer un vídeo propio (403 medido el 28-08). Lo único que se afirma es lo
que el pipeline garantiza por construcción, que la subida es **privada**.
"""

import argparse
import html
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import config  # noqa: E402
from lib.config import CANAL_ACTIVO, CANAL_DIR, CANAL_PERFIL, CANAL_VIDEOS_DIR, STATE_DIR  # noqa: E402

ESTILO = """
:root { color-scheme: light dark; --tinta:#1c1a17; --papel:#f4f1ea; --linea:#d8d2c4;
        --acento:#8a6a2f; --apagado:#6b6459; }
@media (prefers-color-scheme: dark) { :root { --tinta:#ece7dc; --papel:#17150f;
        --linea:#3a352b; --acento:#c9a961; --apagado:#9a9285; } }
* { box-sizing:border-box; }
body { margin:0; padding:32px; background:var(--papel); color:var(--tinta);
       font:15px/1.55 Georgia,'Times New Roman',serif; }
h1 { font-size:26px; margin:0 0 4px; letter-spacing:.2px; }
h2 { font-size:18px; margin:32px 0 10px; border-bottom:1px solid var(--linea); padding-bottom:6px; }
.sub { color:var(--apagado); margin:0 0 24px; }
table { border-collapse:collapse; width:100%; margin:0 0 8px; }
th,td { text-align:left; padding:10px 12px; border-bottom:1px solid var(--linea); vertical-align:top; }
th { font-size:12px; text-transform:uppercase; letter-spacing:.6px; color:var(--apagado); font-weight:normal; }
td.n { width:34px; color:var(--apagado); }
img.thumb { width:200px; height:auto; border:1px solid var(--linea); display:block; }
.pill { display:inline-block; padding:2px 9px; border-radius:11px; font-size:12px; border:1px solid var(--linea); }
.ok { background:#2c5d33; color:#fff; border-color:#2c5d33; }
.no { background:#7a2f2f; color:#fff; border-color:#7a2f2f; }
.wait { background:#7a5f2f; color:#fff; border-color:#7a5f2f; }
.apartado { background:#4a4a52; color:#fff; border-color:#4a4a52; }
.aviso-apartado { margin-top:.4rem; padding:.5rem .6rem; border-left:3px solid #4a4a52; background:#f4f4f6;
                  font-size:.86rem; line-height:1.35; }
a { color:var(--acento); }
.aviso { border-left:3px solid var(--acento); padding:10px 16px; margin:18px 0; background:rgba(138,106,47,.07); }
code { font-family:Consolas,monospace; font-size:13px; background:rgba(128,128,128,.13);
       padding:1px 5px; border-radius:3px; }
.titulo-video { font-size:16px; }
.por-que { color:var(--apagado); font-size:13px; margin-top:6px; }
"""


def _pastilla(texto: str, clase: str) -> str:
    return f'<span class="pill {clase}">{html.escape(texto)}</span>'


def _estado_del_run(run_id: str | None) -> dict:
    """Lee el estado real del run. Devuelve un diccionario vacío si aún no existe."""
    if not run_id:
        return {}
    ruta = STATE_DIR / f"{run_id}.json"
    if not ruta.exists():
        return {}
    estado = json.loads(ruta.read_text(encoding="utf-8"))

    salida = (estado.get("stages", {}).get("upload", {}) or {}).get("output") or ""
    subida: dict = {}
    if salida:
        try:
            subida = json.loads(salida)
        except json.JSONDecodeError:
            subida = {}
    estado["_subida"] = subida

    montaje = CANAL_VIDEOS_DIR / run_id / "montaje.json"
    if montaje.exists():
        estado["_duracion_s"] = json.loads(montaje.read_text(encoding="utf-8")).get("duracion_s")
    return estado


def fila(episodio: dict) -> str:
    run_id = episodio.get("run_id")
    estado = _estado_del_run(run_id)
    subida = estado.get("_subida", {})
    video_id = subida.get("video_id")

    miniatura = ""
    if run_id:
        # La miniatura vive en `subir-al-canal/` desde el 10-09; los runs de antes la tienen en la
        # raíz, así que se busca con `ruta_publicable` y el `src` se deriva de dónde se encontró.
        ruta = config.ruta_publicable(CANAL_VIDEOS_DIR / run_id, "thumbnail.png")
        if ruta.exists():
            relativa = ruta.relative_to(CANAL_VIDEOS_DIR).as_posix()
            miniatura = f'<img class="thumb" src="../videos/{html.escape(relativa)}" alt="miniatura">'

    # Un episodio APARTADO por decisión del usuario se ve como tal aunque su run tenga etapas hechas: sin
    # esto, la decisión vivía en el JSON y en el addendum, y la página —que es lo que él mira— seguía
    # enseñándolo como uno más de la semana (deriva del 10-09, y el caso es el episodio 4).
    apartado = episodio.get("_apartado")
    if video_id:
        # **Publicado no es lo mismo que subido, y el estado no lo dice donde parece.** `visibility`
        # guarda la respuesta de la API en el momento de la subida, que siempre es `private` por
        # construcción (decisión 2); que el usuario haya cruzado el gate 2 vive en el bloque
        # `publicacion.publicado_el` que se anota al verificarlo. Sin esto, la página —lo que él mira—
        # decía «privado» del episodio 1 el mismo día que lo publicó (10-09).
        publicado_el = (subida.get("publicacion") or {}).get("publicado_el")
        if publicado_el:
            estado_html = _pastilla(f"PÚBLICO desde {publicado_el[:10]}", "ok")
        else:
            estado_html = _pastilla("subido · privado", "ok")
        enlaces = (
            f'<div><a href="{html.escape(subida.get("studio_url", ""))}" target="_blank">abrir en Studio</a></div>'
            f'<div><a href="{html.escape(subida.get("url", ""))}" target="_blank">ver el vídeo</a></div>'
            f"<div><code>{html.escape(video_id)}</code></div>"
        )
    elif estado:
        etapas = estado.get("stages", {})
        hechas = [nombre for nombre, datos in etapas.items() if datos.get("status") == "complete"]
        estado_html = _pastilla(f"producido: {', '.join(hechas) or 'nada aún'}", "wait")
        enlaces = "<div>sin subir todavía</div>"
    else:
        estado_html = _pastilla("sin producir", "no")
        enlaces = "—"

    if apartado:
        estado_html = _pastilla("APARTADO", "apartado") + estado_html

    duracion = estado.get("_duracion_s")
    duracion_txt = f"{int(duracion // 60)}:{int(duracion % 60):02d}" if duracion else "—"
    aviso = f'<div class="aviso-apartado">{html.escape(apartado)}</div>' if apartado else ""

    # La ficha y el acento de color son DE CANAL y puede no haberlos: un canal puede declarar
    # `nicho.sin_fuentes_verificadas` y `imagen.acento_de_color: false`, y entonces su calendario no
    # los trae y hasta el 16-09-2026 esta línea moría con KeyError sobre `episodio["ficha"]`.
    # Se pinta lo que el episodio declare y nada más — un «—» en su sitio diría que falta algo.
    detalle = []
    if episodio.get("ficha"):
        detalle.append(f"ficha <code>{html.escape(episodio['ficha'])}</code>")
    if episodio.get("tipo"):
        detalle.append(html.escape(episodio["tipo"]))
    if episodio.get("escenario"):
        detalle.append(html.escape(episodio["escenario"]))
    if episodio.get("acento_de_color"):
        detalle.append(f"acento {html.escape(episodio['acento_de_color'])}")
    detalle.append(f"gate 1 en <code>{html.escape(episodio.get('gate1', '—'))}</code>")
    detalle_html = " · ".join(detalle)

    return f"""<tr>
  <td class="n">{episodio["numero"]}</td>
  <td>{miniatura}</td>
  <td>
    <div class="titulo-video">{html.escape(episodio["titulo"])}</div>
    <div class="por-que">{html.escape(episodio.get("por_que", ""))}</div>
    <div class="por-que">{detalle_html}</div>
    {aviso}
  </td>
  <td>{html.escape(episodio["fecha_propuesta"])}<div class="por-que">{duracion_txt}</div></td>
  <td>{estado_html}<div class="por-que">{enlaces}</div></td>
</tr>"""


def _limite_del_contenido(cuantos: int) -> str:
    """El aviso sobre las fuentes, que **es del canal y no del estudio** (F4.9).

    Hasta el 16-09-2026 este bloque estaba escrito fijo en la plantilla y decía «las once fichas
    del canal están en `solo_citas_verificadas`». Es verdad en un canal con fichas y **falso en uno**
    **que declara `nicho.sin_fuentes_verificadas`** y no tiene ninguna ficha — y esta página se le
    entrega al usuario para que decida, así que una frase inventada sobre sus fuentes no es un detalle.

    Un canal de ficción no tiene aviso que dar: devuelve cadena vacía y la sección no aparece.
    """
    if (CANAL_PERFIL.get("nicho") or {}).get("sin_fuentes_verificadas"):
        return ""
    fichas = sorted((CANAL_DIR / "datos" / "fuentes").glob("*.json"))
    if not fichas:
        return ""
    # El conteo lo da el directorio, nunca una cifra tecleada: es la regla de «toda cifra lleva su
    # dirección», y este mismo bloque decía «once» sin haberlas contado.
    return f"""<h2>Un límite del contenido que conviene tener presente</h2>
<p>Las {len(fichas)} fichas del canal están en <code>solo_citas_verificadas</code>: las citas existen,
resuelven y tratan del tema, pero <strong>nadie ha leído las obras</strong>. Los {cuantos} guiones se han
escrito respetando eso y no dicen «está documentado» ni «los registros muestran» en ninguna afirmación.
Para poder decirlo haría falta que una persona leyera al menos una fuente por ficha.</p>"""


def construye(calendario: dict) -> str:
    filas = "\n".join(fila(episodio) for episodio in calendario["episodios"])
    canal = CANAL_PERFIL.get("nombre", CANAL_ACTIVO)
    url_canal = (CANAL_PERFIL.get("publicacion") or {}).get("canal_youtube", "")
    subidos = sum(
        1 for e in calendario["episodios"] if _estado_del_run(e.get("run_id")).get("_subida", {}).get("video_id")
    )
    cuantos = len(calendario["episodios"])
    limite_del_contenido = _limite_del_contenido(cuantos)

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Calendario {html.escape(calendario["semana_iso"])} · {html.escape(canal)}</title>
<style>{ESTILO}</style></head><body>
<h1>Calendario editorial · {html.escape(calendario["semana_iso"])}</h1>
<p class="sub">{html.escape(canal)} · <a href="{html.escape(url_canal)}" target="_blank">{html.escape(url_canal)}</a>
 · {html.escape(calendario["desde"])} a {html.escape(calendario["hasta"])}
 · <strong>{subidos} de {len(calendario["episodios"])}</strong> subidos por la API como borrador privado</p>

<div class="aviso">
<strong>Ninguno de estos vídeos está público, y ninguno puede llegar a estarlo sin ti.</strong>
Por defecto la subida es tuya, a mano en YouTube Studio, con lo que deja cada run en <code>subir-al-canal/</code>.
Si encendiste la subida por la API (<code>YOUTUBE_SUBIDA_API=1</code>), el vídeo llega como borrador privado.
Pasar uno a público es el <strong>gate 2</strong> y se decide vídeo a vídeo.
</div>

<h2>Los {cuantos} vídeos de la semana</h2>
<table>
<tr><th></th><th>Miniatura</th><th>Vídeo</th><th>Fecha · duración</th><th>Estado</th></tr>
{filas}
</table>

<h2>Lo que espera tu decisión</h2>
<table>
<tr><th>Qué</th><th>Dónde</th></tr>
<tr><td><strong>Gate 1 · los guiones.</strong> Cada uno lleva su lista recorrida punto por punto. Apruébalos uno
a uno: un episodio no se produce hasta que su guion está aprobado.</td>
<td><code>canales/&lt;canal&gt;/calendario/gate1_&lt;semana&gt;_ep01.md</code> …</td></tr>
<tr><td><strong>Gate 2 · publicar.</strong> Uno a uno. Puedes además aprobar uno y fijarle fecha con
<code>publishAt</code>, que la API solo acepta sobre un vídeo privado.</td>
<td>YouTube Studio</td></tr>
<tr><td><strong>Los subtítulos <code>.srt</code> se adjuntan a mano.</strong> Subirlos por la API exigiría
el permiso <code>force-ssl</code>, que da escritura total sobre la cuenta, y el motor no lo pide.</td>
<td>Studio → Subtítulos, el <code>.srt</code> está en la carpeta de cada run</td></tr>
</table>

{limite_del_contenido}

<p class="sub">Esta página se regenera entera con
<code>.venv\\Scripts\\python scripts/pagina_calendario.py</code>. No guarda nada: todo lo que dice
sale del estado de cada run.</p>
</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera la página del calendario editorial")
    parser.add_argument("--semana", default="2026-W37")
    parser.add_argument("--no-abrir", action="store_true")
    args = parser.parse_args()

    directorio = CANAL_DIR / "calendario"
    origen = directorio / f"{args.semana}.json"
    if not origen.exists():
        raise SystemExit(f"[FAIL] no existe {origen}")

    calendario = json.loads(origen.read_text(encoding="utf-8"))
    destino = directorio / f"{args.semana}.html"
    destino.write_text(construye(calendario), encoding="utf-8")
    print(f"[OK] {destino}")

    if not args.no_abrir:
        webbrowser.open(destino.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
