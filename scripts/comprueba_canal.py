r"""¿Tiene este canal todo lo que necesita para producir? La comprobación de la skill `crea-canal`.

Correr:  .venv\Scripts\python scripts/comprueba_canal.py --canal <id> [--json] [--pagina] [--no-abrir]

## Por qué existe, si ya está `pipeline.py --check`

`--check` revisa los adaptadores —imagen, voz, música y subtítulos— y poco más.
Un canal puede darlo en verde y fallar después, porque hay piezas que no mira: el reparto de
personajes, los guardianes de color, las claves que exige el verificador de guiones, el buzón de ideas,
la marca y sus fuentes, los contratos y los pasos del usuario en YouTube. El inventario del 25-09-2026
las encontró al preparar el tercer canal. Esto las junta todas y **reutiliza** los comprobadores que ya existen, en
vez de escribir otros: los mismos `preflight()` que `--check`, `verifica_guion.contrato_del_canal`,
`lineas_rojas.guardianes_del_canal`, `subtitulos.personajes` y los `ajustes()` de subtítulos y música.

## Qué es de quién

Cada comprobación dice quién la resuelve: **claude** (se escribe en el repo al crear el canal),
**usuario** (crear el canal, el token, el teléfono) o **la voz** (la receta y su ritmo, que monta el paso 4
de `crea-canal` con la voz que elige el usuario: addendum fila 258, que la sacó de `produce-semana`). El código
de salida es 0 si no queda nada obligatorio de claude: lo del usuario ya no depende del repo, y la página
(`--pagina`) se lo da con los enlaces; la voz sin montar es lo esperado en un canal a medio crear, pero
`crea-canal` no termina hasta que tampoco queda.

No sale a la red y no gasta cuota: mira ficheros y variables, nunca valores secretos.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# El canal se fija ANTES de importar `lib.config`, que lo lee al cargarse (igual que `pipeline.py`).
if "--canal" in sys.argv:
    _i = sys.argv.index("--canal")
    if _i + 1 < len(sys.argv):
        os.environ["CANAL_ACTIVO"] = sys.argv[_i + 1].strip()
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from lib import config  # noqa: E402
from lib.youtube_client import ENCENDIDA, GUIA_DE_LA_SUBIDA  # noqa: E402

CLAUDE, USUARIO, VOZ = "claude", "usuario", "voz"
ENLACES = {
    "studio": "https://studio.youtube.com",
    "playground": "https://developers.google.com/oauthplayground",
    "telefono": "https://www.youtube.com/verify",
}


def _c(grupo: str, nombre: str, ok: bool, detalle: str, quien: str = CLAUDE, obligatorio: bool = True) -> dict:
    """Una comprobación. Lo no obligatorio que falle es un aviso: no bloquea, como en `--check`."""
    return {
        "grupo": grupo, "nombre": nombre, "ok": bool(ok), "detalle": detalle, "quien": quien,
        "obligatorio": obligatorio,
    }  # fmt: skip


def _intenta(grupo: str, nombre: str, funcion, detalle_ok: str) -> dict:
    """Ejecuta un comprobador del estudio: si lanza, la comprobación falla con su mensaje, que ya dice qué escribir."""
    try:
        funcion()
    except Exception as exc:  # amplio a propósito: un comprobador no debe romper la lista, debe informar
        return _c(grupo, nombre, False, f"{type(exc).__name__}: {exc}")
    return _c(grupo, nombre, True, detalle_ok)


def comprueba(canal: str) -> list[dict]:
    resultados: list[dict] = []
    carpeta = RAIZ / "canales" / canal
    perfil_path = carpeta / "perfil.json"
    if not perfil_path.exists():
        return [_c("carpeta", "perfil.json", False, f"no existe {perfil_path.relative_to(RAIZ)}")]
    try:
        perfil = json.loads(perfil_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [_c("carpeta", "perfil.json", False, f"no es JSON válido: {exc}")]
    resultados.append(_c("carpeta", "perfil.json", True, "existe y es JSON"))
    for contrato in ("contrato-prompt-imagen.md", "contrato-miniatura.md"):
        existe = (carpeta / contrato).exists()
        resultados.append(_c("carpeta", contrato, existe, "existe" if existe else "falta: lo leen las skills de guion"))

    # El esquema del perfil (OC1.4): las siete decisiones, los interruptores de música y subtítulos y el formato de
    # escena. Se mira sobre el perfil leído, así que dice qué escribir aunque `lib/config.py` no haya podido cargarlo.
    esquema = config.problemas_del_perfil(perfil)
    resultados.append(_c("config", "esquema del perfil", not esquema, "; ".join(esquema) or "cumple"))
    # Lo que `lib/config.py` exige sin defecto: sin ello no arranca ningún run.
    resultados.append(
        _c(
            "config",
            "decisiones del canal sin defecto",
            not config.CANAL_ERROR,
            config.CANAL_ERROR or "todas declaradas",
        )
    )
    # Los pasos del usuario solo leen el perfil y el entorno: se calculan aunque el repo falle, para que la
    # página no le diga «nada pendiente» por un error de configuración (segunda revisión de F5.15).
    del_usuario = _pasos_del_usuario(perfil)
    # La voz es «pendiente del paso 4 de crea-canal» solo mientras su receta no existe: en cuanto existe,
    # un fallo de voz es del repo y tiene que bloquear, como en `--check` (filas 197 y 258).
    receta = (perfil.get("voz") or {}).get("receta") or ""
    voz_de = CLAUDE if receta and (carpeta / "datos" / receta).is_file() else VOZ
    if config.CANAL_ERROR:
        return resultados + del_usuario  # el resto importa módulos que leen esas claves

    # Los adaptadores, con el mismo preflight() que `pipeline.py --check`.
    # La onda (`lib/onda.py`) no está, como en `--check`: se guarda para un canal futuro (fila 214) y nada la aplica.
    from lib import comfy_client, lineas_rojas, musica, subtitulos, voice_client

    for etiqueta, adaptador in (
        ("imagen", comfy_client),
        ("voz", voice_client),
        ("música", musica),
        ("subtítulos", subtitulos),
    ):
        try:
            checks = adaptador.preflight()
        except Exception as exc:  # amplio a propósito, como en `--check`
            resultados.append(_c(etiqueta, "preflight", False, f"{type(exc).__name__}: {exc}"))
            continue
        quien = voz_de if etiqueta == "voz" else CLAUDE
        for chk in checks:
            resultados.append(
                _c(etiqueta, chk["nombre"], chk["ok"], chk["detalle"], quien, obligatorio=chk.get("obligatorio", True))
            )

    # La audiencia y la categoría, con la misma comprobación que `--check`.
    from lib.youtube_client import comprobaciones_del_canal

    for chk in comprobaciones_del_canal():
        resultados.append(_c("publicación", chk["nombre"], chk["ok"], chk["detalle"]))

    # Lo que `--check` no mira.
    resultados.append(_intenta("subtítulos", "personajes", subtitulos.personajes, "reparto declarado (o `{}`)"))
    resultados.append(
        _intenta(
            "líneas rojas",
            "guardianes de color",
            lambda: lineas_rojas.guardianes_del_canal(perfil),
            "declarados y válidos (`[]` es una respuesta)",
        )
    )
    from verifica_guion import contrato_del_canal

    carencias = contrato_del_canal(perfil).carencias
    # El ritmo de la voz se mide en la cata del paso 4 de `crea-canal`: mientras no hay receta, va con la voz.
    del_ritmo = [c for c in carencias if "palabras_por_segundo" in c]
    resto = [c for c in carencias if c not in del_ritmo]
    resultados.append(
        _c("verificador", "claves que exige el verificador de guiones", not resto, "; ".join(resto) or "todas")
    )
    resultados.append(
        _c(
            "verificador",
            "ritmo de la voz (voz.palabras_por_segundo)",
            not del_ritmo,
            "; ".join(del_ritmo) or "medido",
            voz_de,
        )
    )

    ideas = perfil.get("ideas") or {}
    ideas_ok = isinstance(ideas.get("minimo_disponibles"), int) and isinstance(ideas.get("acepta_externas"), bool)
    resultados.append(
        _c(
            "ideas",
            "buzón de ideas",
            ideas_ok,
            "declarado"
            if ideas_ok
            else "falta `ideas.minimo_disponibles` (entero) o `ideas.acepta_externas` (booleano)",
        )
    )

    marca = perfil.get("marca") or {}
    faltan_marca = [k for k in ("banner", "avatar", "marca_de_agua", "descripcion", "palabras_clave") if k not in marca]
    resultados.append(
        _c("identidad", "bloque `marca`", not faltan_marca, f"faltan {faltan_marca}" if faltan_marca else "completo")
    )
    # Las fuentes del texto de la miniatura y del banner (OC1.4): las declara el canal, de la biblioteca del estudio.
    from lib.canal_marca import CLAVE_FUENTE_DEL_BANNER
    from lib.miniatura import CLAVE_FUENTE, fuente_declarada

    for nombre, ruta in (("fuente de la miniatura", CLAVE_FUENTE), ("fuente del banner", CLAVE_FUENTE_DEL_BANNER)):
        resultados.append(
            _intenta(
                "identidad",
                nombre,
                lambda ruta=ruta: fuente_declarada(perfil, ruta),
                f"`{ruta}`: de la biblioteca del estudio, con su licencia",
            )
        )

    return resultados + del_usuario


def _pasos_del_usuario(perfil: dict) -> list[dict]:
    """Lo que solo puede hacer el usuario en YouTube. Lee el perfil y el entorno, nada del repo."""
    resultados: list[dict] = []
    pub = perfil.get("publicacion") or {}
    resultados.append(
        _c(
            "YouTube",
            "canal creado",
            bool(pub.get("canal_id")),
            pub.get("canal_id") or "falta crearlo y apuntar `publicacion.canal_id`",
            USUARIO,
        )
    )
    token_env = pub.get("refresh_token_env") or ""
    # El token solo hace falta con la subida por la API (OC1.8). A mano, que es lo de serie, no se le pide.
    if config.YOUTUBE_SUBIDA_API == ENCENDIDA:
        token_ok = bool(token_env and os.getenv(token_env))
        token_detalle = f"{token_env} " + (
            "está en .env" if token_ok else f"no está en .env ({GUIA_DE_LA_SUBIDA}, «One token per channel»)"
        )
    else:
        token_ok, token_detalle = True, "no hace falta: la subida va a mano en Studio (YOUTUBE_SUBIDA_API vacío)"
    resultados.append(_c("YouTube", "token OAuth del canal", token_ok, token_detalle, USUARIO))
    resultados.append(
        _c(
            "YouTube",
            "verificado por teléfono",
            pub.get("verificado_por_telefono") is True,
            "anotado en el perfil"
            if pub.get("verificado_por_telefono") is True
            else f"falta ({GUIA_DE_LA_SUBIDA}, «Verify the channel by phone»)",
            USUARIO,
        )
    )
    return resultados


def pagina(canal: str, resultados: list[dict], destino: Path) -> Path:
    e = html.escape
    filas = "".join(
        f"<tr class='{'ok' if r['ok'] else 'no'}'><td>{'✓' if r['ok'] else '✗'}</td><td>{e(r['grupo'])}</td>"
        f"<td>{e(r['nombre'])}</td><td>{e(r['detalle'])}</td><td>{e(r['quien'])}</td></tr>"
        for r in resultados
    )
    pasos = []
    pendientes = {r["nombre"] for r in resultados if not r["ok"] and r["quien"] == USUARIO}

    def enlace(clave: str, texto: str) -> str:
        return f"<a href='{ENLACES[clave]}' target='_blank'>{texto}</a>"

    if "canal creado" in pendientes:
        pasos.append(
            f"<li><b>Crear el canal</b> en {enlace('studio', 'YouTube Studio')} con el nombre y el handle "
            "firmados en el gate 0.</li>"
        )
    if "token OAuth del canal" in pendientes:
        pasos.append(
            f"<li><b>El token OAuth</b> en el {enlace('playground', 'OAuth Playground')}, entrando con la cuenta "
            "dueña de ESTE canal. Va a la variable que dice la tabla. Guía: "
            f"<code>{GUIA_DE_LA_SUBIDA}</code>, «One token per channel».</li>"
        )
    if "verificado por teléfono" in pendientes:
        pasos.append(
            f"<li><b>Verificarlo por teléfono</b> en {enlace('telefono', 'youtube.com/verify')}. "
            "Un número vale para 2 canales al año.</li>"
        )
    lo_tuyo = f"<ol>{''.join(pasos)}</ol>" if pasos else "<p>Nada pendiente.</p>"
    estilo = (
        ":root{--fondo:#fbfaf7;--texto:#1d1d1b;--ok:#2e7d4f;--no:#b3261e;--linea:#ddd}"
        "@media (prefers-color-scheme: dark){:root{--fondo:#161614;--texto:#ecebe6;--ok:#6fcf97;"
        "--no:#f28b82;--linea:#333}}"
        "body{background:var(--fondo);color:var(--texto);font:16px/1.5 system-ui,sans-serif;"
        "max-width:1100px;margin:0 auto;padding:16px}"
        "table{border-collapse:collapse;width:100%}"
        "td{border-bottom:1px solid var(--linea);padding:6px 8px;vertical-align:top}"
        "tr.ok td:first-child{color:var(--ok)}tr.no td:first-child{color:var(--no)}a{color:inherit}"
    )
    doc = (
        f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Alta de {e(canal)}</title>'
        f"<style>{estilo}</style></head><body><h1>Alta del canal {e(canal)}</h1>"
        f"<h2>Lo tuyo</h2>{lo_tuyo}<h2>Todo lo que necesita el canal</h2><table>{filas}</table></body></html>"
    )
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(doc, encoding="utf-8")
    return destino


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="¿Tiene este canal todo lo que necesita para producir?")
    parser.add_argument("--canal", required=True)
    parser.add_argument("--json", action="store_true", help="la lista entera en JSON")
    parser.add_argument("--pagina", action="store_true", help="la página con lo que falta y los pasos del usuario")
    parser.add_argument("--no-abrir", action="store_true")
    args = parser.parse_args(argv)
    if os.environ.get("CANAL_ACTIVO") != args.canal:
        raise SystemExit("[FAIL] --canal tiene que ir en la línea de órdenes: se lee antes de importar lib.config")

    resultados = comprueba(args.canal)
    if args.json:
        print(json.dumps(resultados, ensure_ascii=False, indent=2))
    else:
        grupo = None
        for r in resultados:
            if r["grupo"] != grupo:
                grupo = r["grupo"]
                print(f"\n{grupo}:")
            pendiente_de = {USUARIO: "  [usuario]", VOZ: "  [crea-canal, paso 4: la voz]"}.get(r["quien"], "")
            if r["ok"]:
                marca = "✓"
            elif r["quien"] != CLAUDE:
                marca = "·"
            else:
                marca = "✗" if r["obligatorio"] else "!"
            print(f"  {marca} {r['nombre']}: {r['detalle']}" + (pendiente_de if not r["ok"] else ""))
    de_claude = [r for r in resultados if not r["ok"] and r["quien"] == CLAUDE and r["obligatorio"]]
    avisos = [r for r in resultados if not r["ok"] and not r["obligatorio"]]
    del_usuario = [r for r in resultados if not r["ok"] and r["quien"] == USUARIO]
    de_voz = [r for r in resultados if not r["ok"] and r["quien"] == VOZ]
    print(
        f"\n{len(resultados)} comprobaciones · faltan {len(de_claude)} del repo y {len(del_usuario)} del usuario"
        + (f" · {len(de_voz)} de la voz, sin montar (paso 4 de crea-canal)" if de_voz else "")
        + (f" · {len(avisos)} aviso(s) que no bloquean" if avisos else "")
    )
    if args.pagina:
        from lib.pagina_local import abre

        destino = pagina(args.canal, resultados, RAIZ / "canales" / args.canal / "marca" / "alta-del-canal.html")
        print(f"Página: {destino}")
        if not args.no_abrir:
            abre(destino)
    return 1 if de_claude else 0


if __name__ == "__main__":
    sys.exit(main())
