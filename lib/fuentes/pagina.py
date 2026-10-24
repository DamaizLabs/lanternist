"""La página de confirmación de las cifras de una ficha (F7.12, spec §3.7).

Es lo que el usuario mira antes de decir en la conversación qué cifras confirma: cada cifra con su valor,
su frase con el valor resaltado, el documento, su editor y un enlace a la página exacta. **Todo texto
que viene de fuera va escapado**: el título de un documento, su editor o la frase copiada son datos de
terceros, y una página que los pegara sin escapar ejecutaría lo que dijeran (`CLAUDE.md`, convenciones).

Los colores dicen qué ha comprobado el código, que es justo lo que el usuario necesita saber para decidir
cuánto mirar él:

- **verde**: el código encontró la frase en el documento;
- **ámbar**: el documento no da texto (PDF escaneado, página pintada con JavaScript) y la confirmación
  del usuario es la única comprobación;
- **rojo**: el código la buscó y no la encontró, o no pudo descargar el documento. No se puede confirmar.
"""

from __future__ import annotations

import html
from datetime import datetime

from lib.fuentes import cifras as _cifras

ESTILO = """
body{font-family:'Segoe UI',system-ui,Arial,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;
     color:#1f2328;background:#f6f7f9;line-height:1.45}
h1{margin-bottom:.2rem} h2{margin-top:2.2rem;border-bottom:2px solid #d0d7de;padding-bottom:.3rem}
.meta{color:#57606a} code{background:#eef1f4;padding:0 .3em;border-radius:3px}
.afirmacion{background:#fff;padding:.8rem 1rem;border-radius:6px;border:1px solid #d0d7de}
.cifra{background:#fff;border:1px solid #d0d7de;border-left:10px solid #8c959f;border-radius:6px;
       padding:1rem 1.2rem;margin:1.1rem 0}
.verde{border-left-color:#1a7f37} .ambar{border-left-color:#d4a72c;background:#fff8e1}
.rojo{border-left-color:#cf222e;background:#fff5f5}
.numero{color:#57606a;font-size:.9rem} .valor{font-size:2rem;font-weight:700;margin:.1rem 0}
.frase{font-family:Georgia,'Times New Roman',serif;font-size:1.15rem;margin:.7rem 0;padding:.7rem 1rem;
       background:#f6f8fa;border-left:3px solid #8c959f}
mark{background:#ffd33d;padding:0 .12em;border-radius:2px}
.estado{font-weight:600;margin-top:.5rem} .verde .estado{color:#1a7f37} .ambar .estado{color:#9a6700}
.rojo .estado{color:#cf222e} .confirmacion{margin-top:.3rem;color:#57606a}
table{border-collapse:collapse;margin:.4rem 0} td,th{padding:.3rem .7rem;border-bottom:1px solid #e4e7eb;
      text-align:left;vertical-align:top}
.cuenta{background:#fff;border:1px solid #d0d7de;border-radius:6px;padding:1rem 1.2rem;margin:1rem 0}
.bien{color:#1a7f37;font-weight:600} .mal{color:#cf222e;font-weight:600} .pendiente{color:#9a6700;font-weight:600}
.pie{margin:2.5rem 0 3rem;padding:1.1rem 1.3rem;background:#ddf4ff;border:1px solid #54aeff;border-radius:6px;
     font-size:1.2rem}
"""


def _e(texto) -> str:
    return html.escape(str(texto if texto is not None else ""), quote=True)


def _enlace(url: str | None, pagina: int | None, texto: str) -> str:
    """Un enlace al documento, a su página exacta si es un PDF. Solo `https`: lo demás no se enlaza."""
    if not url or not str(url).lower().startswith("https://"):
        return _e(texto)
    destino = f"{url}#page={pagina}" if pagina else url
    return f'<a href="{_e(destino)}" target="_blank" rel="noopener noreferrer">{_e(texto)}</a>'


def _frase_resaltada(frase: str, valor: str) -> str:
    """La frase escapada, con los números del valor dentro de `<mark>`."""
    partes, ultimo = [], 0
    for inicio, fin in _cifras.tramos_del_valor(valor, frase):
        partes += [_e(frase[ultimo:inicio]), f"<mark>{_e(frase[inicio:fin])}</mark>"]
        ultimo = fin
    partes.append(_e(frase[ultimo:]))
    return "".join(partes)


def _estado(cifra: dict) -> tuple[str, str]:
    """(clase de color, frase de estado) de una cifra según lo que escribió `--comprueba-cifras`."""
    comprobacion = cifra.get("comprobacion") or {}
    cambiada = comprobacion and comprobacion.get("buscado") != _cifras.huella_de_lo_buscado(cifra)
    if cambiada:
        return "rojo", (
            "NO SE PUEDE CONFIRMAR. El valor o la frase cambiaron después de comprobarla: hay que comprobarla otra vez."
        )
    if comprobacion.get("encontrada"):
        donde = f" en la página {comprobacion['pagina']}" if comprobacion.get("pagina") else ""
        return "verde", f"ENCONTRADA. El código encontró la frase{donde} del documento."
    if comprobacion.get("lectura") == "manual":
        return "ambar", (
            "LECTURA MANUAL. El documento no da texto, así que el código no ha podido buscar la frase: "
            "ábrelo y compruébala tú. Tu confirmación es la única comprobación."
        )
    motivo = comprobacion.get("motivo") or "sin comprobar: falta lanzar --comprueba-cifras"
    return "rojo", f"NO SE PUEDE CONFIRMAR. {motivo}."


def _confirmacion(cifra: dict) -> str:
    confirmacion = cifra.get("confirmacion")
    if not confirmacion:
        return "Sin confirmar."
    dicho = f"{_e(confirmacion.get('por'))} el {_e(confirmacion.get('el'))} («{_e(confirmacion.get('dijo'))}»)"
    if _cifras.confirmacion_vale(cifra):
        return f"Confirmada por {dicho}."
    return f"<span class='mal'>La confirmación de {dicho} ya no casa con su huella: no cuenta.</span>"


def _bloque_cifra(numero: int, cifra: dict, fuentes: dict[str, dict]) -> str:
    color, estado = _estado(cifra)
    fuente = fuentes.get(cifra.get("fuente")) or {}
    comprobacion = cifra.get("comprobacion") or {}
    editor = ", ".join(fuente.get("autores") or []) or "editor sin escribir en la ficha"
    titulo = fuente.get("titulo_publicado") or fuente.get("titulo") or cifra.get("fuente") or "(fuente desconocida)"
    pagina = comprobacion.get("pagina")
    enlace = _enlace(fuente.get("url"), pagina, titulo)
    abrir = _enlace(fuente.get("url"), pagina, f"abrir en la página {pagina}" if pagina else "abrir el documento")
    frase = _frase_resaltada(str(cifra.get("frase_exacta") or ""), str(cifra.get("valor") or ""))
    # El usuario confirma también cómo se publica la fuente: la línea de la bibliografía entra en la huella.
    cita = _e(_cifras.cita(fuente)) if "titulo" in fuente else "la fuente no está en la ficha"
    metadatos = ""
    if fuente.get("titulo_publicado") and fuente.get("titulo") != fuente.get("titulo_publicado"):
        metadatos = f"<br><span class='meta'>Título en los metadatos del documento: {_e(fuente.get('titulo'))}</span>"
    # El redondeo no lo confirma el usuario (fila 277): se enseña para que sepa cómo sonará, y lo comprueba el código.
    se_dice = ""
    if "se_dice" in cifra:
        se_dice = (
            f"<div class='meta'>En el vídeo se dirá redondeada: <b>{_e(cifra.get('se_dice'))}</b>. Ese redondeo "
            "lo comprueba el código contra el valor y el tope del nicho; no entra en tu confirmación.</div>"
        )
    return f"""
<div class="cifra {color}">
  <div class="numero">Cifra {numero} · <code>{_e(cifra.get("id"))}</code></div>
  <div class="valor">{_e(cifra.get("valor"))}</div>{se_dice}
  <div>Año: <b>{_e(cifra.get("anio"))}</b> · Ámbito: <b>{_e(cifra.get("ambito"))}</b> ·
       Dónde la sitúa la ficha: {_e(cifra.get("ubicacion"))}</div>
  <blockquote class="frase">{frase}</blockquote>
  <div>Documento: {enlace}<br>Editor: {_e(editor)} · tipo: {_e(fuente.get("tipo"))} · {abrir}{metadatos}</div>
  <div>Se publica así en la bibliografía: <code>{cita}</code></div>
  <div class="estado">{_e(estado)}</div>
  <div class="confirmacion">{_confirmacion(cifra)}</div>
</div>"""


def _bloque_cuenta(cuenta: dict, cifras: list[dict]) -> str:
    revision = _cifras.comprueba_cuenta(cuenta, cifras)
    filas = []
    for nombre, dato in (cuenta.get("datos") or {}).items():
        dato = dato if isinstance(dato, dict) else {}
        origen = "dato de ejemplo (se dice como ejemplo)"
        if dato.get("tipo") == "real":
            cifra = next((c for c in cifras if c.get("id") == dato.get("cifra")), None)
            vale = cifra is not None and _cifras.confirmacion_vale(cifra)
            clase = "bien" if vale else "pendiente"
            origen = (
                f"dato real · cifra <code>{_e(dato.get('cifra'))}</code> · "
                f"<span class='{clase}'>{'confirmada' if vale else 'sin confirmar'}</span>"
            )
        filas.append(f"<tr><td><code>{_e(nombre)}</code></td><td>{_e(dato.get('valor'))}</td><td>{origen}</td></tr>")
    if revision.problemas:
        veredicto = "<br>".join(f"<span class='mal'>{_e(p)}</span>" for p in revision.problemas)
    else:
        veredicto = (
            f"<span class='bien'>La aritmética casa.</span> La expresión da {_e(revision.calculado)}, y "
            f"redondeado a {_e(cuenta.get('redondeo'))} decimal(es) es lo que se dice."
        )
    return f"""
<div class="cuenta">
  <div class="numero">Cuenta <code>{_e(cuenta.get("id"))}</code></div>
  <div class="valor">{_e(cuenta.get("se_dice"))}</div>
  <div>Expresión: <code>{_e(cuenta.get("expresion"))}</code> · resultado guardado: {_e(cuenta.get("resultado"))}</div>
  <table><tr><th>dato</th><th>valor</th><th>de dónde sale</th></tr>{"".join(filas)}</table>
  <div>{veredicto}</div>
</div>"""


def _bloque_mapa(inspiracion: dict | None) -> str:
    if not inspiracion:
        return "<p class='meta'>La ficha no lleva mapa del tema.</p>"
    filas = "".join(
        f"<tr><td>{_e(v.get('canal'))}</td><td>{_e(v.get('titulo'))}</td><td><code>{_e(v.get('video_id'))}</code></td>"
        f"<td>{_e(v.get('consultado_el'))}</td></tr>"
        for v in inspiracion.get("videos") or []
        if isinstance(v, dict)
    )
    preguntas = "".join(f"<li>{_e(p)}</li>" for p in inspiracion.get("preguntas_que_responden") or [])
    dan = "".join(f"<li>{_e(p)}</li>" for p in inspiracion.get("cifras_que_dan") or [])
    return f"""
<p class="meta">Los vídeos son el mapa, no la fuente: de ellos sale de qué hablar;
las cifras salen de su origen.</p>
<table><tr><th>canal</th><th>vídeo</th><th>id</th><th>consultado</th></tr>{filas}</table>
<p><b>Qué preguntas responden</b></p><ul>{preguntas}</ul>
<p><b>Qué cifras dan</b></p><ul>{dan}</ul>"""


def pagina_de_confirmacion(datos: dict) -> str:
    """El HTML completo de la página, a partir de la ficha ya comprobada."""
    cifras = [c for c in datos.get("cifras") or [] if isinstance(c, dict)]
    fuentes = {f.get("identificador"): f for f in datos.get("fuentes") or [] if isinstance(f, dict)}
    bloques = "".join(_bloque_cifra(n, c, fuentes) for n, c in enumerate(cifras, start=1))
    cuentas = "".join(_bloque_cuenta(c, cifras) for c in datos.get("cuentas") or [] if isinstance(c, dict))
    verdes = sum(1 for c in cifras if _estado(c)[0] == "verde")
    ambar = sum(1 for c in cifras if _estado(c)[0] == "ambar")
    rojas = len(cifras) - verdes - ambar
    ahora = datetime.now().strftime("%d-%m-%Y %H:%M")
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Cifras por confirmar · {_e(datos.get("id"))}</title>
<style>{ESTILO}</style></head><body>
<h1>¿Coinciden estas cifras con su origen?</h1>
<p class="meta">Ficha <code>{_e(datos.get("id"))}</code> · nicho {_e(datos.get("nicho"))} ·
nivel de respaldo: <b>{_e(datos.get("nivel_de_respaldo"))}</b> · página generada el {_e(ahora)}</p>
<div class="afirmacion">{_e(datos.get("afirmacion"))}</div>
<h2>Las cifras ({len(cifras)}): {verdes} encontradas, {ambar} de lectura manual, {rojas} sin poder confirmar</h2>
{bloques}
<h2>Las cuentas ({len(datos.get("cuentas") or [])})</h2>
<p class="meta">Una cifra que sale de una cuenta vale con la cuenta escrita en el guion.
El código la ha recalculado.</p>
{cuentas or "<p class='meta'>La ficha no lleva cuentas.</p>"}
<h2>El mapa del tema</h2>
{_bloque_mapa(datos.get("inspiracion"))}
<div class="pie"><b>Dime en la conversación cuáles confirmas.</b> Por ejemplo: «ok a las {len(cifras)}»,
«ok menos la 2». Las rojas no se pueden confirmar.</div>
</body></html>
"""
