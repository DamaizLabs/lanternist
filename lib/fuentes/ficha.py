"""La ficha: ata UNA afirmación a sus fuentes verificadas (F2.9).

No es un resumen del tema, es **la unidad que el gate 1 comprueba**. Y su regla dura: una ficha
solo puede guardarse si **todas** sus fuentes están resueltas. Sin eso el módulo entero sería
decorativo — bastaría escribir una ficha con una cita bonita sin pasar por el resolutor.

El campo que más importa es `certeza`, porque decide **cómo se cuenta, no si se cuenta**:

- `documentado` — se cuenta como historia, con su periodo y su ámbito exactos.
- `disputado` — se cuenta diciendo qué se sabe y qué no. La incertidumbre es contenido.
- `invencion_moderna` — se cuenta como lo que es, y suele ser el vídeo más interesante: quién la
  fabricó, para qué museo y por qué su época necesitaba esa historia. Lo que no se hace nunca es
  presentarla como pieza de época.

Las fichas son del CANAL (`canales/<id>/datos/fuentes/`): son su catálogo, no del dominio.

**Desde F7.12 (esquema `ficha-fuentes/1.1`) una ficha puede llevar además sus cifras** (filas 273-275):
`inspiracion` (qué vídeos del nicho sirvieron de mapa, sin transcripciones), `cifras` (cada una con su
frase exacta en su origen, la comprobación del código y la confirmación del usuario) y `cuentas` (las
cifras que salen de una aritmética escrita en el guion). Los tres son opcionales y una ficha de 1.0
valida igual. Una cifra puede llevar `se_dice`, cómo se narra redondeada (filas 277 y 280). La mecánica
está en `lib/fuentes/cifras.py`; aquí, cuándo se exige.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path

from lib.config import CANAL_DATOS_DIR
from lib.fuentes import cifras as _cifras
from lib.fuentes.base import FuentesError, parte_identificador

# Grados de certeza. Deciden CÓMO se cuenta una pieza, no si se cuenta — y esa distinción es una
# decisión del 25-08: «soy consciente de que hay torturas ficticias para propaganda y
# museos como la doncella de hierro; estas torturas también las metemos pero con el disclaimer de
# que no existieron, o si existieron nunca se aplicaron. Si no, no tendremos contenido suficiente».
#
# Es una decisión de negocio con motivo declarado: el catálogo verificable de este nicho es
# pequeño, y la mitad de su iconografía popular es de fabricación decimonónica. Excluirla dejaría
# al canal sin material; contarla como real sería el error que este módulo existe para impedir.
# El acuerdo es la tercera vía: entra TODO, y lo que no está documentado lleva su desmentido
# dentro del contenido.
#
# `sin_uso_documentado` es la categoría que abre esa decisión: piezas que existen físicamente o
# están descritas en su época, pero sin constancia de haberse aplicado nunca.
CERTEZAS = ("documentado", "disputado", "sin_uso_documentado", "invencion_moderna")

# Las certezas que NO pueden ir sin desmentido explícito en el contenido. Que el disclaimer sea
# obligatorio por código y no una buena intención es justamente lo que se pidió: la pieza entra,
# pero no entra sola.
EXIGEN_DISCLAIMER = ("disputado", "sin_uso_documentado", "invencion_moderna")

# Qué se ha comprobado de CADA fuente, que no es lo mismo que si existe.
#
# Este es el límite honesto del módulo y conviene que esté en el modelo de datos y no en una nota
# al pie: el resolutor demuestra que **la referencia existe y que su título es el que dice**. No
# demuestra que respalde la afirmación de la ficha — para eso hay que leerla. Sin esta distinción
# el sistema daría una falsa seguridad peor que no tener sistema, porque una ficha llena de citas
# resueltas *parece* documentada.
PERTINENCIAS = {
    "existe": "el identificador resuelve; nadie ha comprobado que la obra respalde la afirmación",
    "por_titulo": "el título de la obra trata del tema de la afirmación; no se ha leído el contenido",
    "leido": "alguien ha leído la obra y respalda la afirmación",
    # F7.12. **Por qué no `leido`**: `leido` dice que alguien leyó la obra, y el usuario habrá leído una frase.
    "cifra_confirmada": "el usuario confirmó la frase de la obra que da la cifra; no se ha leído el resto de la obra",
}

# Y qué puede decir el guion con lo que hay. Es lo que el gate 1 comprueba.
NIVELES_DE_RESPALDO = {
    "solo_citas_verificadas": (
        "las fuentes existen y tratan del tema, pero NADIE ha leído ninguna. La afirmación se apoya "
        "en el conocimiento del modelo, no en las fuentes: el guion no puede presentarla como "
        "documentada sin que una persona lea al menos una"
    ),
    "leido_parcial": "al menos una fuente leída respalda la afirmación",
    "leido": "las fuentes principales están leídas y respaldan la afirmación",
    # F7.12 (fila 275). Lo da `fuentes.py --confirma` al confirmar la última cifra, no Claude a mano.
    "cifras_confirmadas": (
        "cada cifra de la ficha tiene su frase exacta en su origen y el usuario la confirmó; el guion puede dar "
        "esas cifras como hechos, con su año y su ámbito, pero no presentar como documentado lo que la "
        "ficha diga más allá de sus cifras si sus otras fuentes solo están verificadas por título"
    ),
}

# Esquema de los archivos de ficha. Es uno de los JSON versionados de doc/versionado.md. La 1.1 (F7.12)
# añade campos opcionales, así que una ficha de la 1.0 se sigue leyendo tal cual.
SCHEMA = "ficha-fuentes/1.1"
ESQUEMAS_LEIBLES = ("ficha-fuentes/1.0", SCHEMA)

# Lo que escribe el código y no la persona que redacta la ficha: `a_dict` lo recalcula al guardar.
CAMPOS_DERIVADOS = ("schema", "que_significa_ese_nivel")

# El mapa de un tema (spec §3.1). **No hay campo para la transcripción, y es a propósito**: ninguna se
# guarda, ni en git ni en la ficha, y una clave que no está en esta lista no se acepta.
CLAVES_DE_INSPIRACION = ("videos", "preguntas_que_responden", "cifras_que_dan")
CAMPOS_DE_VIDEO = ("video_id", "canal", "channel_id", "titulo", "consultado_el")

# Una cifra (spec §3.3): lo que escribe Claude, lo que puede escribir (`se_dice`, el redondeo con que se
# narra, fila 277) y lo que escribe el código.
CAMPOS_DE_CIFRA = ("id", "valor", "anio", "ambito", "fuente", "ubicacion", "frase_exacta")
CAMPOS_OPCIONALES_DE_CIFRA = ("se_dice",)
CAMPOS_DEL_CODIGO_EN_UNA_CIFRA = ("comprobacion", "confirmacion")
LECTURAS = ("automatica", "manual")
CAMPOS_DE_CUENTA = ("id", "expresion", "datos", "resultado", "se_dice", "redondeo")

# El id de una ficha es su nombre de fichero: sin barras ni puntos, no puede escribir fuera de su carpeta.
_ID_VALIDO = re.compile(r"[a-z0-9][a-z0-9-]*")


def fichas_dir() -> Path:
    if CANAL_DATOS_DIR is None:
        raise FuentesError("no hay canal activo: las fichas son del canal (canales/<id>/datos/fuentes/)")
    destino = CANAL_DATOS_DIR / "fuentes"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


@dataclass
class Ficha:
    """Una afirmación con su respaldo. Los campos siguen `doc/fuente-de-autoridad.md`."""

    id: str
    nombre_en: str
    nombre_es: str
    afirmacion: str
    certeza: str
    periodo_documentado: str
    ambito: str
    evidencia: str
    tratamiento_editorial: str
    fuentes: list[dict] = field(default_factory=list)
    mitos_asociados: list[str] = field(default_factory=list)
    lineas_rojas: str = ""
    disclaimer: str = ""
    verificado_el: str = ""
    nicho: str = ""
    nivel_de_respaldo: str = "solo_citas_verificadas"
    # F7.12: opcionales. Una ficha sin cifras no los escribe, así que una de la 1.0 sale igual.
    inspiracion: dict | None = None
    cifras: list[dict] = field(default_factory=list)
    cuentas: list[dict] = field(default_factory=list)

    def a_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "id": self.id,
            "nombre_en": self.nombre_en,
            "nombre_es": self.nombre_es,
            "nicho": self.nicho,
            "afirmacion": self.afirmacion,
            "certeza": self.certeza,
            "periodo_documentado": self.periodo_documentado,
            "ambito": self.ambito,
            "evidencia": self.evidencia,
            "mitos_asociados": self.mitos_asociados,
            "tratamiento_editorial": self.tratamiento_editorial,
            "lineas_rojas": self.lineas_rojas,
            "disclaimer": self.disclaimer,
            "fuentes": self.fuentes,
            **({"inspiracion": self.inspiracion} if self.inspiracion is not None else {}),
            **({"cifras": self.cifras} if self.cifras else {}),
            **({"cuentas": self.cuentas} if self.cuentas else {}),
            "nivel_de_respaldo": self.nivel_de_respaldo,
            "que_significa_ese_nivel": NIVELES_DE_RESPALDO.get(self.nivel_de_respaldo, "nivel desconocido"),
            "verificado_el": self.verificado_el or date.today().isoformat(),
        }


def desde_dict(datos: dict) -> Ficha:
    """La ficha de un JSON (una ficha guardada o un borrador). Una clave que no conoce, no la ignora.

    Ignorarla sería perder en silencio lo que alguien quiso escribir: un `cifra` por `cifras` dejaría la
    ficha sin cifras y nadie lo vería. Los campos que recalcula `a_dict` (`CAMPOS_DERIVADOS`) se aceptan
    y se descartan.
    """
    if not isinstance(datos, dict):
        raise FuentesError(f"una ficha es un objeto JSON, y esto es {type(datos).__name__}")
    esquema = datos.get("schema")
    if esquema is not None and esquema not in ESQUEMAS_LEIBLES:
        raise FuentesError(f"esquema {esquema!r} desconocido; se leen {list(ESQUEMAS_LEIBLES)}")
    campos = {f.name: f for f in fields(Ficha)}
    desconocidas = sorted(set(datos) - set(campos) - set(CAMPOS_DERIVADOS))
    if desconocidas:
        raise FuentesError(
            f"la ficha lleva claves que no son de una ficha: {desconocidas}. Admitidas: {sorted(campos)}"
        )
    # El constructor dice qué campo obligatorio falta: su mensaje ya lo nombra.
    try:
        return Ficha(**{k: v for k, v in datos.items() if k in campos})
    except TypeError as exc:
        raise FuentesError(f"a la ficha le falta un campo: {exc}") from exc


def valida(ficha: Ficha, perfil: dict) -> list[str]:
    """Devuelve los problemas de una ficha. Lista vacía = se puede guardar.

    Comprueba tres cosas distintas y la tercera es la que da valor al módulo:

    1. Los campos obligatorios **que declara el perfil del nicho** (en historia no son los mismos
       que en entomología: `periodo_documentado` frente a `rango_taxonomico`).
    2. Que `certeza` sea una de las tres, porque de ella depende el tratamiento editorial.
    3. Que **toda fuente esté resuelta**. Si el perfil exige identificador, una fuente sin
       `resuelto: true` invalida la ficha: es la diferencia entre citar y parecer que se cita.
    """
    problemas = []
    valores = ficha.a_dict()

    for campo in perfil.get("campos_obligatorios", []):
        if not str(valores.get(campo) or "").strip():
            problemas.append(f"falta el campo obligatorio del nicho: {campo!r}")

    if ficha.certeza not in CERTEZAS:
        problemas.append(f"certeza {ficha.certeza!r} no es una de {list(CERTEZAS)}")

    if not ficha.fuentes:
        problemas.append("sin ni una fuente: una afirmación sin respaldo no entra en el catálogo")

    if perfil.get("exige_identificador", True):
        for numero, fuente in enumerate(ficha.fuentes, start=1):
            if not fuente.get("identificador"):
                problemas.append(f"fuente {numero} sin identificador, y el nicho lo exige")
            elif not fuente.get("resuelto"):
                problemas.append(
                    f"fuente {numero} ({fuente.get('identificador')}) NO está resuelta: "
                    "una cita que no resuelve, no existe"
                )

    if ficha.certeza in EXIGEN_DISCLAIMER and not ficha.disclaimer.strip():
        problemas.append(
            f"certeza {ficha.certeza!r} exige 'disclaimer': la pieza puede entrar en el catálogo, pero no "
            "sin el desmentido que va DENTRO del contenido (decisión del 25-08)"
        )

    if ficha.nivel_de_respaldo not in NIVELES_DE_RESPALDO:
        problemas.append(f"nivel_de_respaldo {ficha.nivel_de_respaldo!r} no es uno de {list(NIVELES_DE_RESPALDO)}")
    for numero, fuente in enumerate(ficha.fuentes, start=1):
        pertinencia = fuente.get("pertinencia")
        if pertinencia not in PERTINENCIAS:
            problemas.append(
                f"fuente {numero} sin 'pertinencia' válida ({pertinencia!r}); admitidas: {list(PERTINENCIAS)}. "
                "Que una cita resuelva prueba que existe, no que respalde la afirmación, y esa "
                "diferencia no se deja implícita."
            )
    # Coherencia entre lo que dicen las fuentes y lo que declara la ficha: si ninguna está leída,
    # la ficha no puede reclamar respaldo de lectura. Es el fallo que haria el modulo decorativo.
    leidas = sum(1 for f in ficha.fuentes if f.get("pertinencia") == "leido")
    if ficha.nivel_de_respaldo in ("leido", "leido_parcial") and not leidas:
        problemas.append(
            f"la ficha declara nivel_de_respaldo {ficha.nivel_de_respaldo!r} pero ninguna fuente "
            "está marcada como 'leido'"
        )

    # Wikipedia no puede ser la fuente de una afirmación, y esto lo BLOQUEA en vez de avisarlo.
    # Su sitio es el índice: `fuentes.py --indice` saca los identificadores que cita un artículo y
    # el resolutor dice cuáles existen. La lista negra del nicho ya lo dice con palabras («wikis
    # como FUENTE de una afirmación»); aquí se hace cumplir, porque una regla que solo vive en
    # prosa se salta sin querer — de hecho se saltó al crear la ficha de la tortura española.
    for numero, fuente in enumerate(ficha.fuentes, start=1):
        if fuente.get("tipo") == "indice_de_fuentes":
            problemas.append(
                f"fuente {numero} ({fuente.get('identificador')}) es un ÍNDICE, no una fuente: "
                "Wikipedia sirve para descubrir identificadores citables, no para respaldar una "
                "afirmación. Usa `fuentes.py --indice <articulo> --verificar-indice` y cita lo que resuelva."
            )

    jerarquia = perfil.get("jerarquia") or []
    for numero, fuente in enumerate(ficha.fuentes, start=1):
        tipo = fuente.get("tipo")
        if jerarquia and tipo and tipo not in jerarquia:
            # Aviso, no error: la jerarquía ordena por fiabilidad y un tipo que la API devuelve y
            # el perfil no contempla es información sobre el perfil, no necesariamente un fallo.
            problemas.append(f"AVISO fuente {numero}: tipo {tipo!r} no está en la jerarquía del nicho {jerarquia}")

    # F7.12. Una ficha sin cifras, sin cuentas y sin mapa, en un nicho que no declara `cifras`, no pasa
    # por aquí ninguna comprobación nueva: así las fichas del primer canal validan igual que antes.
    problemas.extend(_valida_cifras(ficha, perfil))
    return problemas


# --- F7.12: las cifras, las cuentas y el mapa ------------------------------------------------------


def reglas_de_cifras(perfil: dict) -> tuple[dict | None, list[str]]:
    """El bloque `cifras` del perfil del nicho, comprobado: (reglas, problemas). (None, []) si no lo declara.

    **Sin valor por defecto** (F4.9): si el bloque existe y le falta una clave, se dice cuál y qué
    escribir. Un nicho que no declara el bloque no exige nada de esto, y así el primer canal sigue igual.
    """
    if "cifras" not in perfil:
        return None, []
    nicho = perfil.get("nicho")
    bloque = perfil["cifras"]
    ejemplo = (
        '"cifras": {"exige_frase_confirmada": true, "mapa": {"minimo_videos": 3, "minimo_canales": 2}, '
        '"redondeo": {"error_maximo_pct": 5}}'
    )
    if not isinstance(bloque, dict):
        return None, [f"el perfil del nicho {nicho!r} declara `cifras` y no es un objeto. P. ej. {ejemplo}"]
    problemas = []
    if not isinstance(bloque.get("exige_frase_confirmada"), bool):
        problemas.append(
            f"el perfil del nicho {nicho!r} declara `cifras` sin `exige_frase_confirmada` (true o false): "
            f"dice si cada cifra necesita su frase exacta confirmada por el usuario. P. ej. {ejemplo}"
        )
    mapa = bloque.get("mapa")
    if not isinstance(mapa, dict):
        problemas.append(f"el perfil del nicho {nicho!r} declara `cifras` sin `mapa`. P. ej. {ejemplo}")
    else:
        for clave in ("minimo_videos", "minimo_canales"):
            valor = mapa.get(clave)
            if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
                problemas.append(
                    f"el perfil del nicho {nicho!r} declara `cifras.mapa` sin un `{clave}` entero y positivo "
                    f"(tiene {valor!r}). P. ej. {ejemplo}"
                )
    # Fila 280: lo más que puede alejarse del valor confirmado el número que se narra redondeado.
    redondeo = bloque.get("redondeo")
    tope = redondeo.get("error_maximo_pct") if isinstance(redondeo, dict) else None
    if isinstance(tope, bool) or not isinstance(tope, (int, float)) or not 0 < tope < 100:
        problemas.append(
            f"el perfil del nicho {nicho!r} declara `cifras` sin un `redondeo.error_maximo_pct` entre 0 y 100 "
            f"(tiene {tope!r}): lo más que se puede alejar una cifra redondeada de su valor. P. ej. {ejemplo}"
        )
    return (None if problemas else bloque), problemas


def tope_de_redondeo(reglas: dict | None) -> float | None:
    """El `error_maximo_pct` de unas reglas ya comprobadas por `reglas_de_cifras`, o `None` si no las hay."""
    return reglas["redondeo"]["error_maximo_pct"] if reglas else None


def _valida_inspiracion(inspiracion, reglas: dict | None, perfil_lo_declara: bool) -> list[str]:
    """El mapa del tema (spec §3.1): vídeos de varios canales y notas propias, nunca transcripciones."""
    if not isinstance(inspiracion, dict):
        return [f"`inspiracion` tiene que ser un objeto con {list(CLAVES_DE_INSPIRACION)}"]
    problemas = []
    sobran = sorted(set(inspiracion) - set(CLAVES_DE_INSPIRACION))
    if sobran:
        problemas.append(
            f"`inspiracion` lleva {sobran} y solo admite {list(CLAVES_DE_INSPIRACION)}. Ninguna transcripción "
            "se guarda: de los vídeos se sacan notas propias"
        )
    videos = inspiracion.get("videos")
    if not isinstance(videos, list) or not videos:
        problemas.append("`inspiracion.videos` tiene que ser la lista de los vídeos que hicieron de mapa")
        videos = []
    for numero, video in enumerate(videos, start=1):
        if not isinstance(video, dict):
            problemas.append(f"vídeo {numero} del mapa: tiene que ser un objeto con {list(CAMPOS_DE_VIDEO)}")
            continue
        faltan = [c for c in CAMPOS_DE_VIDEO if not str(video.get(c) or "").strip()]
        if faltan:
            problemas.append(f"vídeo {numero} del mapa: le falta {faltan}")
        extra = sorted(set(video) - set(CAMPOS_DE_VIDEO))
        if extra:
            problemas.append(f"vídeo {numero} del mapa: lleva {extra} y solo admite {list(CAMPOS_DE_VIDEO)}")
    for clave in ("preguntas_que_responden", "cifras_que_dan"):
        notas = inspiracion.get(clave)
        if not isinstance(notas, list) or not all(isinstance(n, str) and n.strip() for n in notas):
            problemas.append(f"`inspiracion.{clave}` tiene que ser una lista de notas propias, en texto")
    if not perfil_lo_declara:
        problemas.append(
            "la ficha lleva `inspiracion` y el perfil del nicho no declara `cifras.mapa`: sin sus mínimos no "
            "se puede comprobar que el mapa sea de varios vídeos de varios canales"
        )
    elif reglas is not None:
        con_dict = [v for v in videos if isinstance(v, dict)]
        distintos = {v.get("video_id") for v in con_dict if v.get("video_id")}
        canales = {v.get("channel_id") for v in con_dict if v.get("channel_id")}
        minimo_videos, minimo_canales = reglas["mapa"]["minimo_videos"], reglas["mapa"]["minimo_canales"]
        if len(distintos) < minimo_videos:
            problemas.append(
                f"el mapa tiene {len(distintos)} vídeo(s) distinto(s) y el nicho pide {minimo_videos}: un tema se "
                "mira en varios vídeos, nunca en uno"
            )
        if len(canales) < minimo_canales:
            problemas.append(
                f"el mapa tiene {len(canales)} canal(es) distinto(s) por `channel_id` y el nicho pide "
                f"{minimo_canales}: lo que sale de un solo canal es analizarlo a él"
            )
    return problemas


def _valida_cifra(numero: int, cifra, fuentes: dict[str, dict], vistas: set, tope: float | None) -> list[str]:
    """Una cifra (spec §3.3): sus campos, su fuente, su valor dentro de su frase, su redondeo (fila 277) y lo
    que escribió el código. `tope` es el `cifras.redondeo.error_maximo_pct` del nicho (fila 280)."""
    if not isinstance(cifra, dict):
        return [f"cifra {numero}: tiene que ser un objeto con {list(CAMPOS_DE_CIFRA)}"]
    etiqueta = f"cifra {numero} ({cifra.get('id')})"
    problemas = []
    faltan = [c for c in CAMPOS_DE_CIFRA if not str(cifra.get(c) or "").strip()]
    if faltan:
        problemas.append(f"{etiqueta}: le falta {faltan}")
    extra = sorted(
        set(cifra) - set(CAMPOS_DE_CIFRA) - set(CAMPOS_OPCIONALES_DE_CIFRA) - set(CAMPOS_DEL_CODIGO_EN_UNA_CIFRA)
    )
    if extra:
        problemas.append(f"{etiqueta}: lleva {extra}, que no son campos de una cifra")
    if cifra.get("id") in vistas:
        problemas.append(f"{etiqueta}: el id está repetido en la ficha")
    vistas.add(cifra.get("id"))

    fuente = cifra.get("fuente")
    if fuente and fuente not in fuentes:
        problemas.append(f"{etiqueta}: su fuente {fuente!r} no es una de las `fuentes` de la ficha")
    elif fuente:
        try:
            esquema, _ = parte_identificador(fuente)
        except FuentesError as exc:
            esquema = None
            problemas.append(f"{etiqueta}: {exc}")
        if esquema is not None and esquema != "url":
            problemas.append(
                f"{etiqueta}: su fuente es {fuente!r} y el origen de una cifra es un documento (`url:https://…`), "
                "que el código descarga para buscar la frase"
            )

    valor, frase = str(cifra.get("valor") or ""), str(cifra.get("frase_exacta") or "")
    if valor and _cifras.una_cantidad(valor) is None:
        problemas.append(
            f"{etiqueta}: el valor {valor!r} tiene que decir UNA cantidad, como la da el documento («$5,323 million», "
            "«7%»); si se narra redondeada, eso va en `se_dice`"
        )
    elif valor:
        redondeo = _cifras.comprueba_redondeo(cifra, tope)
        if redondeo:
            problemas.append(f"{etiqueta}: {redondeo}")
    if valor and frase:
        ausentes = _cifras.digitos_del_valor_en_la_frase(valor, frase)
        if ausentes:
            problemas.append(
                f"{etiqueta}: el valor {valor!r} no está en su frase (no aparece {ausentes}): la frase exacta "
                "es la que da la cifra"
            )

    comprobacion = cifra.get("comprobacion")
    if comprobacion is not None:
        if (
            not isinstance(comprobacion, dict)
            or not isinstance(comprobacion.get("encontrada"), bool)
            or comprobacion.get("lectura") not in (*LECTURAS, None)
        ):
            problemas.append(
                f"{etiqueta}: `comprobacion` la escribe `fuentes.py --comprueba-cifras` y esta no tiene su forma"
            )
    if cifra.get("confirmacion") is not None and not _cifras.confirmacion_vale(cifra):
        problemas.append(
            f"AVISO {etiqueta}: su confirmación no casa con su huella (cambió el valor, la frase, la fuente, "
            "el documento, el año o el ámbito): no cuenta, y el usuario tiene que volver a confirmarla"
        )
    if isinstance(comprobacion, dict) and fuente in fuentes and not _cifras.cita_al_dia(cifra, fuentes):
        problemas.append(
            f"AVISO {etiqueta}: la cita de su fuente cambió después de comprobarla (título, editor, año o URL): "
            "vuelve a lanzar `--comprueba-cifras`, y el usuario tiene que volver a ver la página"
        )
    return problemas


def _confirmada(cifra: dict, fuentes: dict[str, dict]) -> bool:
    """Una cifra cuenta como confirmada si su huella casa y la cita que vio el usuario es la que se publica."""
    return _cifras.confirmacion_vale(cifra) and _cifras.cita_al_dia(cifra, fuentes)


def _valida_cifras(ficha: Ficha, perfil: dict) -> list[str]:
    reglas, problemas = reglas_de_cifras(perfil)
    exige = bool(reglas and reglas["exige_frase_confirmada"])

    if ficha.inspiracion is not None:
        problemas += _valida_inspiracion(ficha.inspiracion, reglas, "cifras" in perfil)
    elif exige:
        problemas.append(
            "el nicho exige el mapa del tema: `inspiracion` con los vídeos que se miraron (al menos "
            f"{reglas['mapa']['minimo_videos']} de {reglas['mapa']['minimo_canales']} canales), "
            "sus preguntas y sus cifras"
        )

    if not isinstance(ficha.cifras, list) or not isinstance(ficha.cuentas, list):
        return [*problemas, "`cifras` y `cuentas` tienen que ser listas"]
    if exige and not ficha.cifras:
        problemas.append("el nicho exige al menos una cifra con su frase exacta en su origen (`cifras`)")
    fuentes = {f.get("identificador"): f for f in ficha.fuentes if isinstance(f, dict)}
    for numero, fuente in enumerate(ficha.fuentes, start=1):
        # El título de los metadatos de un documento no sirve para publicar («printmgr file»): el que sale en
        # la bibliografía lo escribe Claude, en el idioma del canal, y el usuario lo ve en la página con las cifras.
        if isinstance(fuente, dict) and fuente.get("proveedor") == "documento":
            if not str(fuente.get("titulo_publicado") or "").strip():
                problemas.append(
                    f"fuente {numero} ({fuente.get('identificador')}) es un documento y le falta `titulo_publicado`: "
                    f"el título de sus metadatos ({fuente.get('titulo')!r}) no es el que se publica"
                )
    vistas: set = set()
    for numero, cifra in enumerate(ficha.cifras, start=1):
        problemas += _valida_cifra(numero, cifra, fuentes, vistas, tope_de_redondeo(reglas))

    con_dict = [c for c in ficha.cifras if isinstance(c, dict)]
    declara_confirmadas = ficha.nivel_de_respaldo == "cifras_confirmadas"
    vistas_cuentas: set = set()
    for numero, cuenta in enumerate(ficha.cuentas, start=1):
        if not isinstance(cuenta, dict):
            problemas.append(f"cuenta {numero}: tiene que ser un objeto con {list(CAMPOS_DE_CUENTA)}")
            continue
        faltan = [c for c in CAMPOS_DE_CUENTA if c not in cuenta]
        if faltan:
            problemas.append(f"cuenta {numero} ({cuenta.get('id')}): le falta {faltan}")
            continue
        if cuenta["id"] in vistas_cuentas:
            problemas.append(f"cuenta {numero} ({cuenta['id']}): el id está repetido en la ficha")
        vistas_cuentas.add(cuenta["id"])
        revision = _cifras.comprueba_cuenta(cuenta, con_dict)
        problemas += revision.problemas
        # Un dato real con su cifra sin confirmar no impide guardar la ficha (se guarda ANTES de que el usuario
        # confirme), pero sí que suba de nivel.
        problemas += [p if declara_confirmadas else f"AVISO {p}" for p in revision.pendientes]

    confirmadas = [c for c in con_dict if _confirmada(c, fuentes)]
    if declara_confirmadas:
        sin_confirmar = [str(c.get("id")) for c in con_dict if c not in confirmadas]
        if not ficha.cifras:
            problemas.append("la ficha declara 'cifras_confirmadas' y no lleva ni una cifra")
        elif sin_confirmar or len(con_dict) < len(ficha.cifras):
            problemas.append(
                f"la ficha declara 'cifras_confirmadas' y {len(ficha.cifras) - len(confirmadas)} de "
                f"{len(ficha.cifras)} cifra(s) no están confirmadas con su huella: {sin_confirmar}. Ese nivel "
                "lo da `fuentes.py --confirma` al confirmar la última"
            )
    de_confirmadas = {c.get("fuente") for c in confirmadas}
    for numero, fuente in enumerate(ficha.fuentes, start=1):
        if fuente.get("pertinencia") == "cifra_confirmada" and fuente.get("identificador") not in de_confirmadas:
            problemas.append(
                f"fuente {numero} ({fuente.get('identificador')}) es 'cifra_confirmada' y ninguna cifra "
                "confirmada sale de ella"
            )
    return problemas


def nivel_efectivo(datos: dict) -> str:
    """El nivel que la ficha puede reclamar HOY: `cifras_confirmadas` cae si alguna huella ya no casa."""
    nivel = datos.get("nivel_de_respaldo") or ""
    if nivel != "cifras_confirmadas":
        return nivel
    cifras = [c for c in datos.get("cifras") or [] if isinstance(c, dict)]
    fuentes = {f.get("identificador"): f for f in datos.get("fuentes") or [] if isinstance(f, dict)}
    if cifras and len(cifras) == len(datos.get("cifras") or []) and all(_confirmada(c, fuentes) for c in cifras):
        return nivel
    return "solo_citas_verificadas"


def recalcula_respaldo(ficha: Ficha) -> list[str]:
    """Sube o baja el nivel y las pertinencias según las confirmaciones que casan hoy. Devuelve qué cambió.

    Lo llaman `--confirma` (al confirmar la última cifra, la ficha pasa a `cifras_confirmadas`) y
    `--comprueba-cifras` (si una huella deja de casar, la ficha baja a `solo_citas_verificadas` y la
    fuente que se quedó sin cifras confirmadas vuelve a `existe`). Solo toca esas dos transiciones: un
    nivel `leido` o una pertinencia `leido` no los decide una confirmación de cifras.
    """
    cambios = []
    fuentes = {f.get("identificador"): f for f in ficha.fuentes if isinstance(f, dict)}
    confirmadas = [c for c in ficha.cifras if isinstance(c, dict) and _confirmada(c, fuentes)]
    de_confirmadas = {c.get("fuente") for c in confirmadas}
    for fuente in ficha.fuentes:
        identificador, pertinencia = fuente.get("identificador"), fuente.get("pertinencia")
        if identificador in de_confirmadas and pertinencia in ("existe", "por_titulo"):
            fuente["pertinencia"] = "cifra_confirmada"
            cambios.append(f"fuente {identificador}: {pertinencia} → cifra_confirmada")
        elif identificador not in de_confirmadas and pertinencia == "cifra_confirmada":
            fuente["pertinencia"] = "existe"
            cambios.append(f"fuente {identificador}: cifra_confirmada → existe (ya no le queda una cifra confirmada)")
    todas = bool(ficha.cifras) and len(confirmadas) == len(ficha.cifras)
    if todas and ficha.nivel_de_respaldo == "solo_citas_verificadas":
        ficha.nivel_de_respaldo = "cifras_confirmadas"
        cambios.append("nivel: solo_citas_verificadas → cifras_confirmadas")
    elif not todas and ficha.nivel_de_respaldo == "cifras_confirmadas":
        ficha.nivel_de_respaldo = "solo_citas_verificadas"
        cambios.append("nivel: cifras_confirmadas → solo_citas_verificadas (hay cifras sin confirmación que case)")
    return cambios


def escribe(ficha: Ficha, perfil: dict, ruta: Path) -> Path:
    """Valida y escribe la ficha en `ruta`. **No escribe nada que no pase la validación.**"""
    problemas = [p for p in valida(ficha, perfil) if not p.startswith("AVISO")]
    if problemas:
        raise FuentesError(f"la ficha {ficha.id!r} no se guarda porque no valida:\n  - " + "\n  - ".join(problemas))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(ficha.a_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return ruta


def guarda(ficha: Ficha, perfil: dict, carpeta: Path | None = None) -> Path:
    """Valida y escribe la ficha en la carpeta de fichas del canal (o en `carpeta`, para pruebas)."""
    if not isinstance(ficha.id, str) or not _ID_VALIDO.fullmatch(ficha.id):
        raise FuentesError(
            f"id de ficha {ficha.id!r} no válido: minúsculas, dígitos y guiones (es su nombre de fichero)"
        )
    return escribe(ficha, perfil, (carpeta or fichas_dir()) / f"{ficha.id}.json")


def carga(id_ficha: str) -> dict:
    ruta = fichas_dir() / f"{id_ficha}.json"
    if not ruta.exists():
        raise FuentesError(f"no existe la ficha {id_ficha!r} ({ruta})")
    return json.loads(ruta.read_text(encoding="utf-8"))


def listado() -> list[dict]:
    """Resumen de las fichas del canal, para el CLI y para el checklist del gate 1."""
    resumen = []
    for ruta in sorted(fichas_dir().glob("*.json")):
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        resumen.append(
            {
                "id": datos.get("id"),
                "certeza": datos.get("certeza"),
                "periodo": datos.get("periodo_documentado"),
                "fuentes": len(datos.get("fuentes") or []),
                "resueltas": sum(1 for f in datos.get("fuentes") or [] if f.get("resuelto")),
                "archivo": ruta.name,
            }
        )
    return resumen
