"""Lo que comparten las pruebas del motor de escena (F6.2a): el GUION mínimo, sus imágenes y las herramientas.

Se llama así, y no `conftest.py`, porque las pruebas lo importan: dos `conftest` en carpetas sin
`__init__.py` comparten nombre de módulo y el `import` cogería el que pytest cargara el último.

Las imágenes se dibujan aquí, con formas y rayas, en vez de guardarse en git: así no hay binarios en el
repositorio y cada una tiene algo que se ve moverse (la rueda sus radios, las mallas sus rayas, los
fondos sus bloques), que es lo que necesitan las pruebas de determinismo para no comparar lienzos lisos.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from lib import config
from lib.escena import render

AQUI = Path(__file__).parent
GUION_MIN = AQUI / "guion-min.json"
CSS_PRUEBA = AQUI / "canal-prueba.css"


def guion_min() -> dict:
    """Una copia nueva del GUION mínimo, para que cada prueba pueda tocarla sin afectar a las demás."""
    return json.loads(GUION_MIN.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------ imágenes
def _fondo(w: int, h: int, base: tuple[int, int, int]) -> Image.Image:
    im = Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(im)
    for i in range(0, w, 160):
        for j in range(0, h, 160):
            if (i // 160 + j // 160) % 2:
                d.rectangle([i, j, i + 159, j + 159], fill=tuple(min(255, c + 40) for c in base))
    d.ellipse([w // 3, h // 4, w // 3 + 300, h // 4 + 300], fill=(240, 200, 90))
    return im


def _figura(color: tuple[int, int, int], brazos: bool) -> Image.Image:
    im = Image.new("RGBA", (200, 400), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([60, 10, 140, 90], fill=color + (255,), outline=(20, 20, 20, 255), width=4)
    d.rectangle([70, 90, 130, 300], fill=color + (255,), outline=(20, 20, 20, 255), width=4)
    d.rectangle([75, 300, 95, 398], fill=(40, 40, 60, 255))
    d.rectangle([105, 300, 125, 398], fill=(40, 40, 60, 255))
    if brazos:
        d.line([70, 120, 10, 40], fill=(20, 20, 20, 255), width=10)
        d.line([130, 120, 190, 40], fill=(20, 20, 20, 255), width=10)
    return im


def _rueda() -> Image.Image:
    im = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([4, 4, 96, 96], outline=(30, 30, 30, 255), width=8)
    for x0, y0, x1, y1 in ((50, 6, 50, 94), (6, 50, 94, 50), (18, 18, 82, 82)):
        d.line([x0, y0, x1, y1], fill=(30, 30, 30, 255), width=6)
    return im


def _cinta() -> Image.Image:
    im = Image.new("RGBA", (80, 160), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for j in range(0, 160, 20):
        d.rectangle([25, j, 55, j + 9], fill=(200, 60, 60, 255))
        d.rectangle([25, j + 10, 55, j + 19], fill=(250, 250, 250, 255))
    return im


def _rayas(w: int, h: int, color: tuple[int, int, int]) -> Image.Image:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for j in range(0, h, 16):
        d.rectangle([4, j, w - 5, j + 7], fill=color + (255,))
    return im


def dibuja_assets(carpeta: Path) -> dict[str, Path]:
    """Dibuja las imágenes que pide el GUION mínimo en `carpeta` y devuelve el mapa de assets de compone."""
    carpeta.mkdir(parents=True, exist_ok=True)
    imagenes = {
        "assets/img/fondo-a.png": _fondo(2400, 1350, (70, 110, 160)),
        "assets/img/fondo-b.png": _fondo(1920, 1080, (120, 90, 70)),
        "assets/img/figura-a.png": _figura((230, 120, 80), brazos=False),
        "assets/img/figura-b.png": _figura((230, 120, 80), brazos=True),
        "assets/img/rueda.png": _rueda(),
        "assets/rig/cinta.png": _cinta(),
        "assets/rig/pierna.png": _rayas(60, 120, (50, 70, 160)),
        "assets/rig/cuerpo.png": _rayas(60, 210, (60, 150, 90)),
    }
    mapa = {}
    for rel, im in imagenes.items():
        ruta = carpeta / rel.replace("/", "_")
        im.save(ruta)
        mapa[rel] = ruta
    return mapa


# ------------------------------------------------------------------------------------------ herramientas
def node() -> str | None:
    try:
        return render.node_exe()
    except render.ErrorDeRender:
        return None


def falta_para_el_navegador() -> str | None:
    """Por qué no se pueden correr aquí las pruebas con Chrome y GPU, o None si se puede."""
    if node() is None:
        return "no hay node (lo instala fnm, ver .node-version)"
    if not config.HYPERFRAMES_CLI.is_file():
        return "no está la CLI de HyperFrames en motor/ (cd motor; npm ci)"
    try:
        render.chrome_webgpu()
    except render.ErrorDeRender as e:
        return f"no está el Chrome con WebGPU: {e}"
    if shutil.which("nvidia-smi") is None:
        return "no hay nvidia-smi: sin GPU NVIDIA no hay render de hardware"
    if shutil.which("ffmpeg") is None:
        return "no hay ffmpeg para comparar fotogramas"
    return None


def inyecta(index: Path, *, cabeza: str = "", cuerpo: str = "") -> None:
    """Mete código en una composición YA escrita, saltándose a propósito la revisión estática de compone.

    Es como se fabrican los controles negativos de la sonda y del render: lo que la revisión estática no puede
    ver (una URL que se arma en JavaScript, un fallo de la GPU a mitad de vídeo) tiene que cazarlo la
    siguiente barrera.
    """
    texto = index.read_text(encoding="utf-8")
    if cabeza:
        texto = texto.replace("</head>", cabeza + "\n</head>", 1)
    if cuerpo:
        texto = texto.replace("</body>", cuerpo + "\n</body>", 1)
    index.write_text(texto, encoding="utf-8")


def md5_por_fotograma(video: Path) -> list[str]:
    """El md5 de cada fotograma DECODIFICADO (ffmpeg framemd5): compara imágenes, no bytes del contenedor."""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-f", "framemd5", "-"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert r.returncode == 0, r.stderr
    return [linea.rsplit(",", 1)[1].strip() for linea in r.stdout.splitlines() if linea and not linea.startswith("#")]


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


# ------------------------------------------------------------------------------------------ F6.2b: un run de prueba
# El canal ficticio de las pruebas: su perfil solo lleva el bloque `escena` (ver su `_que_es`).
PERFIL_PRUEBA = AQUI / "canal-prueba" / "perfil.json"


def escena_prueba() -> dict:
    """Una copia nueva del bloque `escena` del canal de prueba."""
    return json.loads(PERFIL_PRUEBA.read_text(encoding="utf-8"))["escena"]


def escribe_wav(ruta: Path, segundos: float, *, flotante: bool = False, muestras_por_segundo: int = 24000) -> Path:
    """Un wav de silencio de esa duración: PCM de 16 bits o, con `flotante`, coma flotante de 32 bits (formato 3),
    que es como los escribe la voz del estudio y lo que el módulo `wave` no sabe abrir."""
    n = round(segundos * muestras_por_segundo)
    ancho = 4 if flotante else 2
    datos = bytes(n * ancho)
    fmt = struct.pack(
        "<HHIIHH", 3 if flotante else 1, 1, muestras_por_segundo, muestras_por_segundo * ancho, ancho, 8 * ancho
    )
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(
        b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(datos)) + b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", len(datos)) + datos
    )  # fmt: skip
    return ruta


def marcas_uniformes(texto: str, *, desde: float = 0.3, paso: float = 0.4, dura: float = 0.3, quita=()) -> list[dict]:
    """Marcas como las de whisper para cada palabra de `texto` (como se pinta), una cada `paso` s.

    `quita` son índices de palabra que el «reconocedor» no oye: así se fabrica una lámina mal anclada.
    """
    from lib.alineacion import texto_para_pintar

    return [
        {"texto": w, "desde": round(desde + i * paso, 3), "hasta": round(desde + i * paso + dura, 3)}
        for i, w in enumerate(texto_para_pintar(texto, "en").split())
        if i not in set(quita)
    ]


def crea_run(carpeta: Path, laminas: list[dict]) -> Path:
    """Un run mínimo en disco: `slides.json`, un wav por lámina y la alineación, en las rutas de `lib/config.py`.

    Cada lámina: {"narration", "dura" (s del wav), "marcas" (opcional: si no, uniformes), "hablantes" (opcional)}.
    """
    slides, items = [], []
    for n, lam in enumerate(laminas, start=1):
        slide = {"slide_number": n, "narration": lam["narration"]}
        if lam.get("hablantes") is not None:
            slide["hablantes"] = lam["hablantes"]
        slides.append(slide)
        if not lam["narration"].strip():
            continue
        escribe_wav(config.audio_de_lamina(carpeta, n), lam["dura"], flotante=lam.get("flotante", True))
        marcas = lam.get("marcas") or marcas_uniformes(lam["narration"])
        items.append({"id": f"slide-{n:02d}", "marcas": marcas})
    (carpeta / "slides.json").write_text(json.dumps({"slides": slides}, ensure_ascii=False), encoding="utf-8")
    ruta = config.alineacion_del_run(carpeta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return carpeta


# El episodio de prueba: dos láminas con diálogo de los dos personajes del canal ficticio.
NARRACION_1 = (
    'Ana walked to the park with her red kite. She said, "Look at the kite, it is so big!" '
    "Bo laughed and ran after her."
)
NARRACION_2 = 'The kite flew over the trees. Bo said, "Wait for me!" Then they both sat on the grass.'
# Índices de palabra (sobre el texto como se pinta) de cada cita, como los escribe scripts/hablantes.py.
HABLANTES_1 = [{"desde": 11, "hasta": 19, "personaje": "Ana"}]
HABLANTES_2 = [{"desde": 8, "hasta": 11, "personaje": "Bo"}]
LAMINAS_PRUEBA = [
    {"narration": NARRACION_1, "dura": 10.5, "hablantes": HABLANTES_1},
    {"narration": NARRACION_2, "dura": 7.8, "hablantes": HABLANTES_2},
]

# El catálogo del episodio: las imágenes de `dibuja_assets` con su apoyo y la caja y el tamaño de su cabeza (la
# cabeza de `_figura` es la elipse [60, 10, 140, 90], así que su raíz del área es 80).
_CABEZA = {"cabeza": [60, 10, 140, 90], "cabeza_px": 80}
CATALOGO_PRUEBA = {
    "parque": {"src": "assets/img/fondo-a.png", "w": 2400, "h": 1350},
    "cielo": {"src": "assets/img/fondo-b.png", "w": 1920, "h": 1080},
    "ana_pie": {"src": "assets/img/figura-a.png", "w": 200, "h": 400, "ax": 100, "ay": 400, "k": 1, **_CABEZA},
    "ana_brazos": {"src": "assets/img/figura-b.png", "w": 200, "h": 400, "ax": 100, "ay": 400, "k": 1, **_CABEZA},
    "bo_pie": {"src": "assets/img/figura-a.png", "w": 200, "h": 400, "ax": 100, "ay": 400, "k": 1, **_CABEZA},
    "rueda": {"src": "assets/img/rueda.png", "w": 100, "h": 100, "ax": 50, "ay": 50, "k": 1},
}
# Lo que el canal de prueba haría con sus envoltorios: la disposición de sus ayudantes.
TARJETA_PRUEBA = {
    "dur": 3.0, "x": 250, "y": 200, "w": 330, "h": 300, "etiqueta": "NEW WORD",
    "anim": {"entra": "pop", "sale": "pop", "bucle": "flota", "amp": 0.6},
    "sonido": {"nombre": "pop", "volumen": 0.22},
}  # fmt: skip
GRITO_PRUEBA = {
    "dur": 1.6, "x": 1500, "y": 150, "w": 700, "h": 160, "anim": {"entra": "pop", "sale": "pop", "bucle": "late"},
    "sonido": None,
}  # fmt: skip


def linea_de_prueba(carpeta: Path, laminas: list[dict] | None = None):
    """La línea de tiempo del episodio de prueba (o de otras láminas), sobre un run escrito en `carpeta`."""
    from lib.escena.linea_tiempo import LineaDeTiempo

    return LineaDeTiempo.del_run(crea_run(carpeta, laminas or LAMINAS_PRUEBA), escena=escena_prueba(), idioma="en")


def cue_con_palabra(linea, palabra: str) -> int:
    """El primer cue que dice `palabra` (para escribir los tramos de prueba sin contar cues a mano)."""
    from lib.alineacion import _normaliza

    return next(c.n for c in linea.cues if any(_normaliza(p.texto) == _normaliza(palabra) for p in c.palabras))


def guion_de_prueba(linea, *, catalogo=None, escena=None):
    """El episodio de prueba escrito con el lenguaje de escena, como lo escribiría un canal. Devuelve el Guion.

    Dos planos: el parque (con suelo) y el cielo (sin suelo). Ana anda y cambia de postura cuando habla, Bo la
    mira; una tarjeta, una etiqueta con flecha, un grito, una transición y la cámara siguiendo lo que se dice.
    `catalogo` y `escena` son los del canal de prueba si no se pasan otros (el guion de escena de un run de prueba,
    F6.2d, pasa el catálogo de su run y el bloque `escena` de su perfil).
    """
    from lib.escena import anclas, ayudas
    from lib.escena.escena import Guion

    A = anclas.usa(linea)
    g = Guion(
        titulo="Episodio de prueba",
        idioma="en",
        escena=escena if escena is not None else escena_prueba(),
        catalogo=catalogo if catalogo is not None else CATALOGO_PRUEBA,
        iconos={},
        linea=linea,
    )
    g.fondo("parque", img="parque", suelo=[(0, 1080), (2400, 1080), (2400, 1350), (0, 1350)], px_u=500)
    g.fondo("cielo", img="cielo", suelo=None)
    fin_1, _ = A.HUECO(0)

    p1 = g.plano("parque", 0, fin_1)
    p1.cam(0, 1200, 760, 1.0, tr=0)
    p1.cam(A.P(cue_con_palabra(linea, "Look"), "Look") - 0.3, 1100, 800, 1.3, tr=1.0)
    ana = g.actor(p1, ["ana_pie", "ana_brazos"], 700, 1200, escala=1.2, pj="ana", anda=True)
    ana.clave(A.P(1, "walked"), 2.0, "inout", x=1000)
    ana.clave(A.P(cue_con_palabra(linea, "Look"), "Look") - 0.2, 0, post="ana_brazos")
    bo = g.actor(p1, "bo_pie", 1500, 1230, escala=1.2, pj="bo", flip=1)
    bo.ev("risa", A.P(cue_con_palabra(linea, "laughed"), "laughed"), 0.8)
    ayudas.tarjeta(g, "kite", "rueda", A.P(1, "kite"), **TARJETA_PRUEBA)
    ayudas.etiqueta(
        g, p1, "park", 2000, 1150, A.P(1, "park"), A.P(1, "park") + 3, ancho=500, alto_texto=90, sube=200, tam=0.8,
        z=900, anim={"entra": "pop", "sale": "fade", "trazo_t": 0.15, "trazo_d": 0.5}, sonido=None,
    )  # fmt: skip

    p2 = g.plano("cielo", fin_1, linea.total, entra="funde", d=0.5)
    p2.cam(fin_1, 960, 540, 1.0, tr=0)
    g.actor(p2, "bo_pie", 960, 1000, escala=1.0, pj="bo")
    ayudas.grito(g, "Wait for me!", A.P(cue_con_palabra(linea, "Wait"), "Wait"), **GRITO_PRUEBA)
    g.transicion("destello", fin_1 - 0.3, 0.6, sonido={"nombre": "whoosh", "volumen": 0.3, "desfase_s": 0.15})
    return g
