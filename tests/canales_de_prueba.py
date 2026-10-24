"""Canales y recetas de voz inventados para las pruebas: ninguno es de nadie ni vive en `canales/`.

Desde OC1.1 (fila 302) el repositorio solo trae el canal de ejemplo, que no lleva fichas, ni guardián de color, ni
receta de voz todavía. Las pruebas que comparan dos canales que deciden distinto —uno documental, con fichas,
guardián, lista negra de adjetivos y capítulos; otro de ficción, sin nada de eso y con otro ritmo— los crean aquí, en
una carpeta temporal. Antes usaban los canales del estudio, y se rompían cada vez que uno de ellos producía una semana.

**Cómo se nombra un canal que no está en `canales/`.** Por su RUTA ABSOLUTA, en `CANAL_ACTIVO` o en `--canal`.
`lib/config.py` arma la carpeta del canal con `CANALES_DIR / CANAL_ACTIVO`, y pathlib, al unir una ruta absoluta, se
queda con ella. Así cada herramienta corre de verdad, en su proceso y con su `lib.config`, contra un perfil inventado.
Si esa unión dejara de funcionar, el canal no se encontraría y las pruebas que comparan los dos canales fallarían: no
pueden pasar en silencio.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RECETAS = Path(__file__).resolve().parent / "datos" / "recetas"
RECETA_DOCUMENTAL = RECETAS / "voz-orpheus-documental.json"
RECETA_FICCION = RECETAS / "voz-orpheus-ficcion.json"


def patron_de_id_de_canal(raiz: Path = RAIZ) -> re.Pattern:
    """Lo que delata un id de canal completo dentro de código o de prosa.

    Dos formas: la numerada de los canales del estudio (`C00N-<nombre>`, y cualquier `C<3 cifras>-<nombre>`) y el
    nombre de cada carpeta de `canales/` que existe hoy, como palabra entera de una ruta (el de ejemplo es
    `example`). Sin la segunda, las guardas que buscaban `C00N-…` no verían el id del canal de ejemplo.
    """
    ids = sorted(p.parent.name for p in (raiz / "canales").glob("*/perfil.json"))
    de_carpeta = "|".join(re.escape(i) for i in ids)
    numerado = r"C\d{3}-[a-z-]+"
    return re.compile(numerado + (rf"|(?<![\w.-])(?:{de_carpeta})(?![\w.-])" if de_carpeta else ""))


def recetas_a_comprobar() -> list[Path]:
    """Las recetas de los canales del repositorio y las dos de prueba.

    Las guardas del tipo «toda receta declara X» (F4.9) recorren esto: con solo las de `canales/` quedarían vacías
    mientras el canal de ejemplo no tenga voz, y una guarda vacía pasa sin comprobar nada.
    """
    return sorted((RAIZ / "canales").glob("*/datos/voz-*.json")) + [RECETA_DOCUMENTAL, RECETA_FICCION]


_BASE = {
    "imagen": {"modelo": "qwen-2512-lightning-tinta", "seed": 1234, "acento_de_color": False},
    "idioma": {"narracion": "en", "subtitulos": "en"},
    "publicacion": {"hecho_para_ninos": False, "categoria_youtube": "27", "canal_id": None},
    "subtitulos": {
        "activos": True,
        "srt": True,
        "fuente": "Patrick Hand SC",
        "cuerpo": 60,
        "max_palabras_por_linea": 12,
        "margen_inferior_px": 150,
        "margen_lateral_px": 200,
        "traducciones": [],
        "personajes": {},
    },
    "musica": {"activa": False},
    "ideas": {"minimo_disponibles": 4, "acepta_externas": True},
}

# El canal documental: el de las reglas. Sus cifras son las de un long-form de 15-25 min a 40 láminas y 2,44
# palabras/s, que dan las bandas de 63-85 y 40-103 palabras por lámina.
_DOCUMENTAL = {
    "id": "documental-de-prueba",
    "nombre": "Canal documental de prueba",
    "nicho": {"id": "ejemplo-sin-cifras", "fichas_verificadas": "datos/fuentes/"},
    "formato": {
        "duracion_objetivo_min": [15, 25],
        "capitulos": True,
        "laminas_por_video_estimadas": 40,
        "bienvenida": "Hello, and welcome to the workshop... where famous objects come apart! <chuckle> Today on the "
        "bench... {titulo}.",
        "despedida": "And that... is {tema}. {lo_visto} If you enjoyed it, subscribe. See you at the next bench!",
    },
    "voz": {"receta": RECETA_DOCUMENTAL.name, "palabras_por_segundo": 2.44},
    "lineas_rojas": {
        "guardianes_de_color": [
            {
                "nombre": "sangre",
                "que_evita": "sangre o heridas",
                "palabras_del_prompt": ["red", "crimson", "scarlet", "mahogany", "brick", "blood"],
                "hue_max": 12.0,
                "sat_min": 0.35,
                "val_min": 0.15,
                "val_max": 0.85,
                "umbral_celda": 64,
                "umbral_grueso": 96,
                "umbral_total": 250,
                "ventana_fina": 16,
                "ventana_gruesa": 48,
            }
        ]
    },
}
_DOCUMENTAL_IMAGEN = {"adjetivos_prohibidos": ["heavy", "worn", "rough", "weathered", "grainy"]}
_DOCUMENTAL_PUBLICACION = {"refresh_token_env": "YOUTUBE_REFRESH_TOKEN"}

# El canal de ficción: el que no tiene ninguna de esas reglas, otro ritmo y otra variable de token.
_FICCION = {
    "id": "ficcion-de-prueba",
    "nombre": "Canal de ficción de prueba",
    "nicho": {"id": "ficcion-didactica", "sin_fuentes_verificadas": "ficción: no hay nada que citar"},
    "formato": {"duracion_objetivo_min": [14, 17], "capitulos": True, "laminas_por_video_estimadas": 10},
    "voz": {"receta": RECETA_FICCION.name, "palabras_por_segundo": 1.885},
    "lineas_rojas": {"guardianes_de_color": []},
}
_FICCION_IMAGEN = {"adjetivos_prohibidos": []}
_FICCION_PUBLICACION = {"refresh_token_env": "YOUTUBE_REFRESH_TOKEN_2"}


def _junta(propio: dict, imagen: dict, publicacion: dict) -> dict:
    perfil = copy.deepcopy(_BASE)
    perfil.update(copy.deepcopy(propio))
    perfil["imagen"].update(imagen)
    perfil["publicacion"].update(publicacion)
    return perfil


def perfil_documental() -> dict:
    """Un perfil completo de canal documental: con fichas, guardián de sangre, lista negra y capítulos."""
    return _junta(_DOCUMENTAL, _DOCUMENTAL_IMAGEN, _DOCUMENTAL_PUBLICACION)


def perfil_ficcion() -> dict:
    """Un perfil completo de canal de ficción: sin fichas, sin guardianes, sin lista negra y con otro ritmo."""
    return _junta(_FICCION, _FICCION_IMAGEN, _FICCION_PUBLICACION)


def escribe_canal(raiz: Path, nombre: str, perfil: dict, *, fichas: dict[str, dict] | None = None) -> Path:
    """Escribe el canal en `raiz/<nombre>/`: su perfil, sus fichas y, si existe una de prueba con ese nombre, su receta.

    Devuelve la carpeta, que es lo que se pasa como `CANAL_ACTIVO` o `--canal` (ruta absoluta).
    """
    carpeta = Path(raiz).resolve() / nombre
    (carpeta / "datos" / "fuentes").mkdir(parents=True, exist_ok=True)
    (carpeta / "perfil.json").write_text(json.dumps(perfil, ensure_ascii=False, indent=2), encoding="utf-8")
    for archivo, datos in (fichas or {}).items():
        (carpeta / "datos" / "fuentes" / archivo).write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    receta = RECETAS / ((perfil.get("voz") or {}).get("receta") or "")
    if receta.is_file():
        (carpeta / "datos" / receta.name).write_text(receta.read_text(encoding="utf-8"), encoding="utf-8")
    return carpeta
