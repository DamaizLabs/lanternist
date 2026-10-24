"""Reúne imágenes reales de una pieza en Wikimedia Commons, con su ficha de procedencia.

Es el paso (2) de la regla del estudio de la fila 147 del addendum: cuando el modelo no conoce un
objeto, se busca una imagen real y se replica con edición por instrucción. Sin procedencia no se
puede usar nada (decisión 5), así que aquí se baja el archivo Y se anota de dónde sale, quién lo
hizo y con qué licencia.

**Solo entra lo que tiene licencia libre.** Una foto de banco de imágenes o una miniatura de YouTube
no valen por mucho que se parezcan: el vídeo se publica.

Uso (la CATEGORÍA es mejor entrada que el texto: se llama por el nombre inglés de la pieza):
    .venv\\Scripts\\python scripts/reune_referencias.py --categoria "Choke pear" \\
        --salida experimentos/pera-referencia-2026-09-17 --limite 30
    .venv\\Scripts\\python scripts/reune_referencias.py "pear of anguish" --salida <carpeta>
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import requests

API = "https://commons.wikimedia.org/w/api.php"
AGENTE = "Lanternist/1.0 (referencias de imagen en local)"
ANCHO_REFERENCIA = 1600

# Lo que NO se acepta como referencia. El resto de la comprobación es mirar las imágenes: la línea
# roja del canal (restos humanos, cuerpos sufriendo) no la sabe medir ningún campo de metadatos, y en
# el caso de la jaula de gibbet fueron 4 de 14 las que hubo que descartar mirándolas.
LICENCIAS_VETADAS = re.compile(r"non[- ]?commercial|\bnc\b|fair use|no derivative|\bnd\b", re.I)


def pide(url: str, **kwargs) -> requests.Response:
    """GET que respeta el ritmo que pide Wikimedia ante un 429.

    **No es un reintento a ciegas**: solo reacciona al 429, espera lo que diga `Retry-After` —o el
    doble en cada vuelta— y se rinde a la tercera. Wikimedia corta por ritmo con facilidad: el
    17-09 la primera tanda murió a la tercera imagen y la segunda, al consultar la ficha número
    quince, dejando la carpeta a medias. Un fallo así no se arregla apretando la pausa fija,
    porque el corte depende de la carga del servicio, no de nuestra cadencia.
    """
    espera = 2.0
    for intento in (1, 2, 3):
        r = requests.get(url, **kwargs)
        if r.status_code != 429:
            return r
        if intento == 3:
            return r
        segundos = float(r.headers.get("Retry-After") or espera)
        print(f"  [429] Wikimedia pide esperar; {segundos:.0f}s y se reintenta ({intento}/2)")
        time.sleep(segundos)
        espera *= 2
    return r


def busca(consulta: str, limite: int) -> list[str]:
    r = pide(
        API,
        params={
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {consulta}",
            "gsrnamespace": 6,
            "gsrlimit": limite,
        },
        headers={"User-Agent": AGENTE},
        timeout=30,
    )
    r.raise_for_status()
    paginas = (r.json().get("query") or {}).get("pages") or {}
    return [p["title"] for p in paginas.values()]


def de_categoria(categoria: str, limite: int) -> list[str]:
    """Los archivos de una categoría de Commons.

    Es mejor entrada que la búsqueda por texto: `filetype:bitmap pear of anguish` devolvió un manual
    de taquigrafía de 1898 y un grabado de Die Gartenlaube, mientras que la categoría de la pieza
    —`Category:Choke pear`, su nombre en inglés— trae justo sus fotos.
    """
    if not categoria.lower().startswith("category:"):
        categoria = f"Category:{categoria}"
    r = pide(
        API,
        params={
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": categoria,
            "cmtype": "file",
            "cmlimit": limite,
        },
        headers={"User-Agent": AGENTE},
        timeout=30,
    )
    r.raise_for_status()
    return [m["title"] for m in (r.json().get("query") or {}).get("categorymembers", [])]


def ficha(titulo: str) -> dict | None:
    r = pide(
        API,
        params={
            "action": "query",
            "format": "json",
            "titles": titulo,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
            # **Se pide la miniatura, no el original.** Wikimedia devuelve 429 al bajar originales de
            # varios MB seguidos y su propio mensaje de error pide usar los tamaños derivados; con
            # 1600 px sobra para editar una lámina de 1344x768.
            "iiurlwidth": ANCHO_REFERENCIA,
        },
        headers={"User-Agent": AGENTE},
        timeout=30,
    )
    r.raise_for_status()
    paginas = (r.json().get("query") or {}).get("pages") or {}
    for pagina in paginas.values():
        info = (pagina.get("imageinfo") or [{}])[0]
        if not info:
            return None
        meta = info.get("extmetadata") or {}

        def campo(clave: str) -> str:
            return re.sub(r"<[^>]+>", "", str((meta.get(clave) or {}).get("value", ""))).strip()

        return {
            "titulo": titulo,
            "url_archivo": info.get("thumburl") or info.get("url", ""),
            "url_original": info.get("url", ""),
            "url_pagina": info.get("descriptionurl", ""),
            "licencia": campo("LicenseShortName") or campo("License"),
            "licencia_url": campo("LicenseUrl"),
            "autor": campo("Artist"),
            "fuente": campo("Credit"),
            "ancho": info.get("width"),
            "alto": info.get("height"),
            "mime": info.get("mime", ""),
        }
    return None


def descarga(url: str, destino: Path) -> int:
    r = pide(url, headers={"User-Agent": AGENTE}, timeout=60)
    r.raise_for_status()
    destino.write_bytes(r.content)
    return len(r.content)


def main() -> int:
    p = argparse.ArgumentParser(description="Referencias reales de una pieza, con procedencia")
    p.add_argument("consulta", nargs="?", default="", help="búsqueda por texto (opcional si hay --categoria)")
    p.add_argument("--extra", action="append", default=[], help="más consultas (otro idioma, otro nombre)")
    p.add_argument("--categoria", action="append", default=[], help="categoría de Commons; mejor entrada que el texto")
    p.add_argument("--salida", required=True)
    p.add_argument("--limite", type=int, default=10, help="resultados por consulta")
    p.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones (Commons corta por ritmo)")
    args = p.parse_args()

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    titulos: list[str] = []
    for categoria in args.categoria:
        encontrados = de_categoria(categoria, args.limite)
        print(f"categoría «{categoria}» → {len(encontrados)} archivo(s)")
        titulos.extend(t for t in encontrados if t not in titulos)
        time.sleep(args.pausa)
    for consulta in [c for c in [args.consulta, *args.extra] if c]:
        encontrados = busca(consulta, args.limite)
        print(f"«{consulta}» → {len(encontrados)} resultado(s)")
        titulos.extend(t for t in encontrados if t not in titulos)
        time.sleep(args.pausa)

    fichas, descartadas = [], []
    for titulo in titulos:
        # Commons devuelve 429 si se le pide sin respirar: pasó a la tercera imagen del primer intento.
        time.sleep(args.pausa)
        f = ficha(titulo)
        if not f:
            continue
        if not f["licencia"] or LICENCIAS_VETADAS.search(f["licencia"]):
            descartadas.append(
                {"titulo": titulo, "motivo": f"licencia no admisible: {f['licencia'] or 'sin declarar'}"}
            )
            continue
        if not str(f["mime"]).startswith("image/"):
            descartadas.append({"titulo": titulo, "motivo": f"no es imagen: {f['mime']}"})
            continue
        nombre = re.sub(r"[^A-Za-z0-9._-]+", "_", titulo.replace("File:", ""))[:90]
        try:
            bytes_ = descarga(f["url_archivo"], salida / nombre)
        except Exception as exc:  # noqa: BLE001 — una imagen que no baja no tumba la tanda
            descartadas.append({"titulo": titulo, "motivo": f"no se pudo descargar: {exc}"})
            continue
        f["archivo"] = nombre
        f["bytes"] = bytes_
        f["revisada_a_ojo"] = False
        f["_recordatorio"] = "Mirar la imagen antes de usarla: las líneas rojas del canal no las mide ningún metadato"
        fichas.append(f)
        print(f"  [OK] {nombre} · {f['licencia']} · {f['ancho']}x{f['alto']}")

    (salida / "fichas.json").write_text(json.dumps(fichas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if descartadas:
        (salida / "descartadas.json").write_text(
            json.dumps(descartadas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(f"\n{len(fichas)} referencia(s) con procedencia en {salida}")
    print(f"{len(descartadas)} descartada(s)" + (f" → {salida / 'descartadas.json'}" if descartadas else ""))
    print("SIGUIENTE PASO, y no es opcional: mirarlas una a una y marcar `revisada_a_ojo`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
