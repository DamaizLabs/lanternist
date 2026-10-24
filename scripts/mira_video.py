r"""Mira un vídeo para proponerle un formato del catálogo (OC1.11, fila 319): lo mecánico de la skill `propone-formato`.

    .venv\Scripts\python scripts\mira_video.py [ENLACE] [--capturas F1 F2 ...] [--video FICHERO] [--salida CARPETA]

**Qué mira.**

- **ENLACE**, un vídeo de YouTube (`watch?v=`, `youtu.be/`, `shorts/` o `embed/`). De él solo se pide oEmbed, el
  servicio público con que YouTube deja incrustar sus vídeos: da el título, el canal y la miniatura sin clave y sin
  descargar el vídeo. Sus términos prohíben descargar el vídeo y acceder por medios automatizados (fila 319), así que
  no se baja nada más.
- **`--capturas`**: imágenes que da el usuario. Entran en la hoja tal cual.
- **`--video`**: un fichero de vídeo del usuario. ffmpeg saca 8 fotogramas repartidos por su duración, en local.

Se puede llamar sin ENLACE si hay capturas o vídeo.

**Qué no hace.** La respuesta de oEmbed es dato de terceros: no se sigue ninguna URL que venga en ella, salvo la
miniatura, y solo si su host es `i.ytimg.com`. Tampoco se sigue una redirección. Sin reintentos y con timeout. Un 404
o un 400 quieren decir que el vídeo no existe o es privado, y un 401 que no deja incrustarse.

**Qué deja**, en `experimentos/formatos/<id del vídeo, o «local»>/` (o en `--salida`):

- `hoja.jpg`, la rejilla con todo lo que hay que mirar (`lib/fotogramas.py → hoja_en_rejilla`);
- `miniatura.jpg`, si la hay, y `fotograma-NN.jpg`, si hay vídeo;
- `video.json`: el enlace, el título, el canal y cada imagen con su procedencia;
- `pagina.html`, con la hoja y los datos. El título y el canal van escapados: son textos de terceros.

Imprime una línea con el resumen. Código de salida: 0 si hay algo que mirar, y 2 si se niega, con «NO: <motivo>».
"""

from __future__ import annotations

import argparse
import html
import io
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from lib import fotogramas  # noqa: E402
from lib.config import EXPERIMENTOS_DIR  # noqa: E402

OEMBED = "https://www.youtube.com/oembed"
HOST_DE_MINIATURAS = "i.ytimg.com"
HOSTS_DE_YOUTUBE = {"youtube.com", "www.youtube.com", "m.youtube.com"}
HOST_CORTO = "youtu.be"
# El id de un vídeo de YouTube: 11 caracteres de este alfabeto.
ID_DE_VIDEO = re.compile(r"^[A-Za-z0-9_-]{11}$")
# Las rutas de un canal: `/@nombre`, `/channel/…`, `/c/…` y `/user/…`.
RUTA_DE_CANAL = re.compile(r"^/(?:@[^/]+|channel/|c/|user/)")
TIMEOUT_S = 20
# Lo más que se lee de una respuesta: una miniatura de YouTube pesa unos 30 KB y la respuesta de oEmbed, menos de 1 KB.
MAXIMO_BYTES = 5 * 1024 * 1024
AGENTE = "Lanternist (mira_video)"
SUGERENCIA = "pasa tres o cuatro capturas con --capturas, o el vídeo con --video, sin el enlace"


class Negativa(Exception):
    """Lo que se pide no se puede mirar: el mensaje dice por qué y qué hacer."""


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    """Una redirección es una URL que viene en la respuesta, y no se sigue: queda como un HTTPError 3xx."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_ABRE = urllib.request.build_opener(_SinRedirecciones()).open


def _pide(url: str) -> bytes:
    """Un GET con timeout y sin reintentos. Lanza HTTPError, URLError u OSError, y Negativa si pasa de MAXIMO_BYTES."""
    peticion = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    with _ABRE(peticion, timeout=TIMEOUT_S) as respuesta:
        datos = respuesta.read(MAXIMO_BYTES + 1)
    if len(datos) > MAXIMO_BYTES:
        raise Negativa(f"la respuesta de {urllib.parse.urlsplit(url).hostname} pasa de {MAXIMO_BYTES} bytes")
    return datos


def id_del_enlace(enlace: str) -> str:
    """El id del vídeo que nombra el enlace, o Negativa con el motivo. Una lista con `v=` es su vídeo."""
    texto = enlace.strip()
    partes = urllib.parse.urlsplit(texto)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise Negativa(f"«{texto[:80]}» no es un enlace: pega la URL entera del vídeo, la que empieza por https://")
    host = partes.hostname.lower()
    consulta = urllib.parse.parse_qs(partes.query)
    if host == HOST_CORTO:
        candidato = partes.path.strip("/").split("/")[0]
    elif host in HOSTS_DE_YOUTUBE:
        trozos = [t for t in partes.path.split("/") if t]
        if partes.path.rstrip("/") == "/watch" and consulta.get("v"):
            candidato = consulta["v"][0]
        elif len(trozos) >= 2 and trozos[0] in ("shorts", "embed"):
            candidato = trozos[1]
        elif consulta.get("list"):
            raise Negativa(
                "es una lista de reproducción, no un vídeo: abre uno de sus vídeos y pega su enlace (el que lleva v=)"
            )
        elif RUTA_DE_CANAL.match(partes.path):
            raise Negativa("es un canal, no un vídeo: abre uno de sus vídeos y pega su enlace")
        else:
            raise Negativa(f"no es el enlace de un vídeo de YouTube ({host}{partes.path[:60]})")
    else:
        raise Negativa(f"no es un enlace de YouTube, sino de {host}: si el vídeo está en otra web, {SUGERENCIA}")
    if not ID_DE_VIDEO.match(candidato):
        raise Negativa(f"el enlace no lleva un id de vídeo válido («{candidato[:40]}»)")
    return candidato


def lee_oembed(video_id: str) -> dict:
    """El título, el canal y la miniatura del vídeo según oEmbed. Negativa si no se pueden leer."""
    canonico = f"https://www.youtube.com/watch?v={video_id}"
    url = f"{OEMBED}?{urllib.parse.urlencode({'url': canonico, 'format': 'json'})}"
    try:
        datos = json.loads(_pide(url).decode("utf-8"))
    except urllib.error.HTTPError as error:
        # Un id que YouTube no reconoce da 400 o 404, según el id (medido el 24-10-2026).
        motivos = {
            400: "el vídeo no existe (oEmbed responde 400)",
            404: "el vídeo no existe o es privado (oEmbed responde 404)",
            401: "el vídeo no deja incrustarse, y por eso oEmbed no da sus datos (responde 401)",
        }
        motivo = motivos.get(error.code)
        if motivo is None and 300 <= error.code < 400:
            motivo = f"oEmbed responde con una redirección ({error.code}), y no se sigue"
        raise Negativa(f"{motivo or f'oEmbed responde {error.code}'}: {SUGERENCIA}") from None
    except (urllib.error.URLError, OSError) as error:
        raise Negativa(f"no se pudo hablar con oEmbed ({error}); sin red no se lee el enlace: {SUGERENCIA}") from None
    except ValueError:
        raise Negativa(f"oEmbed no ha devuelto un JSON: {SUGERENCIA}") from None
    if not isinstance(datos, dict) or datos.get("type") != "video":
        raise Negativa(f"oEmbed no lo da como un vídeo: {SUGERENCIA}")
    return {
        "enlace": canonico,
        "titulo": str(datos.get("title") or ""),
        "canal": str(datos.get("author_name") or ""),
        "thumbnail_url": str(datos.get("thumbnail_url") or ""),
    }


def baja_miniatura(url: str, destino: Path) -> tuple[Path | None, str]:
    """La miniatura, solo si su host es `i.ytimg.com` y es una imagen: (ruta o None, qué pasó)."""
    partes = urllib.parse.urlsplit(url)
    if partes.scheme != "https" or (partes.hostname or "").lower() != HOST_DE_MINIATURAS:
        return None, f"no se baja: su host no es {HOST_DE_MINIATURAS} ({(partes.hostname or 'sin host')[:60]})"
    try:
        datos = _pide(url)
        with Image.open(io.BytesIO(datos)) as imagen:
            imagen.convert("RGB").save(destino, quality=90)
    except (urllib.error.URLError, OSError, Negativa) as error:
        # Pillow da OSError (UnidentifiedImageError) si lo bajado no es una imagen.
        return None, f"no se pudo bajar: {error}"
    return destino, f"miniatura de YouTube ({HOST_DE_MINIATURAS}), por la thumbnail_url de oEmbed"


def _pagina(datos: dict, carpeta: Path) -> Path:
    """La página con la hoja y los datos. Todo texto que viene de fuera va escapado."""
    e = html.escape
    filas = "".join(
        f"<tr><td>{e(Path(i['fichero']).name)}</td><td>{e(i['procedencia'])}</td></tr>" for i in datos["imagenes"]
    )
    cabecera = ""
    if datos.get("enlace"):
        cabecera = (
            f"<p><b>{e(datos['titulo'])}</b> · {e(datos['canal'])}<br>"
            f'<a href="{e(datos["enlace"])}">{e(datos["enlace"])}</a></p>'
        )
    pagina = carpeta / "pagina.html"
    pagina.write_text(
        '<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Lo que se mira</title>'
        "<style>body{font-family:sans-serif;margin:2em}img{max-width:100%}td{padding:2px 8px}</style></head><body>"
        f'<h1>Lo que se mira para proponer el formato</h1>{cabecera}<img src="hoja.jpg" alt="hoja">'
        f"<table><tr><th>Imagen</th><th>De dónde sale</th></tr>{filas}</table></body></html>",
        encoding="utf-8",
    )
    return pagina


def mira(enlace: str | None, capturas: list[str], video: str | None, salida: str | None) -> dict:
    """Todo lo de la orden menos imprimir: deja la hoja, la página y `video.json`, y devuelve lo que lleva este último.
    Negativa si no hay nada que mirar. Lo local se comprueba antes de salir a la red."""
    if not enlace and not capturas and not video:
        raise Negativa("no hay nada que mirar: pega el enlace de un vídeo, o pasa --capturas o --video")
    for captura in capturas:
        try:
            with Image.open(captura) as imagen:
                imagen.verify()
        except OSError:
            raise Negativa(f"la captura «{captura}» no existe o no es una imagen") from None
    if video and fotogramas.duracion_de(Path(video)) is None:
        raise Negativa(f"«{video}» no existe o no es un vídeo que ffprobe sepa leer")

    video_id = id_del_enlace(enlace) if enlace else None
    datos = lee_oembed(video_id) if video_id else {"enlace": None, "titulo": "", "canal": "", "thumbnail_url": ""}
    carpeta = Path(salida) if salida else EXPERIMENTOS_DIR / "formatos" / (video_id or "local")
    carpeta.mkdir(parents=True, exist_ok=True)
    for viejo in [carpeta / "miniatura.jpg", *carpeta.glob("fotograma-*.jpg")]:
        viejo.unlink(missing_ok=True)

    # Cada imagen: su fichero, de dónde sale y las dos líneas que lleva debajo en la hoja.
    imagenes, sin_miniatura = [], None
    url_miniatura = datos.pop("thumbnail_url")
    if url_miniatura:
        miniatura, nota = baja_miniatura(url_miniatura, carpeta / "miniatura.jpg")
        if miniatura:
            imagenes.append({"fichero": str(miniatura), "procedencia": nota, "pie": ("miniatura", HOST_DE_MINIATURAS)})
        else:
            sin_miniatura = f"la miniatura {nota}"
    elif video_id:
        sin_miniatura = "oEmbed no da miniatura"
    for n, captura in enumerate(capturas, start=1):
        ruta = Path(captura).resolve()
        imagenes.append(
            {"fichero": str(ruta), "procedencia": f"captura {n} del usuario", "pie": (f"captura {n}", ruta.name)}
        )
    if video:
        sacados = fotogramas.fotogramas_de_fichero(Path(video), carpeta)
        for n, (ruta, segundo) in enumerate(sacados, start=1):
            imagenes.append(
                {
                    "fichero": str(ruta),
                    "procedencia": f"fotograma del vídeo del usuario en el segundo {segundo}, sacado con ffmpeg",
                    "pie": (f"fotograma {n} de {len(sacados)}", f"{segundo} s"),
                }
            )
    if not imagenes:
        raise Negativa(
            f"no hay ninguna imagen que mirar ({sin_miniatura or 'ffmpeg no sacó ningún fotograma'}): {SUGERENCIA}"
        )

    titulo = f"{datos['titulo']} · {datos['canal']}"[:110] if video_id else "Capturas y vídeo del usuario"
    celdas = [{"imagen": i["fichero"], "linea1": i["pie"][0], "linea2": i["pie"][1]} for i in imagenes]
    fotogramas.hoja_en_rejilla(celdas, carpeta / "hoja.jpg", titulo, columnas=min(4, len(celdas)))
    registro = {
        **datos,
        "video_id": video_id,
        "de_donde_salen_los_datos": f"oEmbed de YouTube ({OEMBED}), sin descargar el vídeo" if video_id else None,
        **({"miniatura_no_bajada": sin_miniatura} if sin_miniatura else {}),
        "video_del_usuario": str(Path(video).resolve()) if video else None,
        "imagenes": [{"fichero": i["fichero"], "procedencia": i["procedencia"]} for i in imagenes],
        "hoja": str(carpeta / "hoja.jpg"),
        "pagina": str(_pagina({**datos, "imagenes": imagenes}, carpeta)),
        "momento": datetime.now().isoformat(timespec="seconds"),
    }
    (carpeta / "video.json").write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    return registro


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mira un vídeo para proponerle un formato del catálogo.")
    parser.add_argument("enlace", nargs="?", help="el enlace de un vídeo de YouTube")
    parser.add_argument("--capturas", nargs="+", default=[], metavar="F", help="capturas del vídeo, del usuario")
    parser.add_argument("--video", metavar="FICHERO", help="un fichero de vídeo del usuario")
    parser.add_argument(
        "--salida",
        metavar="CARPETA",
        help=(
            "dónde dejarlo (por defecto, experimentos/formatos/<id>/). Ojo: en esa carpeta se borran los "
            "miniatura.jpg y fotograma-*.jpg que haya, y se sustituyen hoja.jpg, video.json y pagina.html"
        ),
    )
    args = parser.parse_args(argv)
    try:
        hecho = mira(args.enlace, args.capturas, args.video, args.salida)
    except Negativa as negativa:
        print(f"NO: {negativa}")
        return 2
    de_quien = f" de «{hecho['titulo']}» ({hecho['canal']})" if hecho["video_id"] else ""
    print(f"[OK] {len(hecho['imagenes'])} imagen(es) que mirar{de_quien}: {hecho['hoja']} · {hecho['pagina']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
