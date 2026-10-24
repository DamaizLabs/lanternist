"""El buzón de ideas de un canal: dónde esperan las candidatas que todavía no son un guion (F5.11).

Punto de entrada: `ideas.py` en la raíz. Aquí vive la lógica; allí solo argparse, llamadas e
impresión, que es la dirección que ya toma F5.10.

## Qué resuelve

Hoy una idea no tiene dónde esperar: o se produce esa semana o se pierde. El paso 2 de
`produce-semana` saca los temas del catálogo de fichas verificadas, y **antes de tener ficha no hay
ningún sitio**. Esto es ese sitio, y su contrato es `normaliza_idea`, más abajo:

```
canales/<id>/ideas/
    entrada/                # el usuario suelta aquí los .txt, formato libre
        procesado/          #   los ya leídos, con su fecha delante
    ideas.json              # el almacén normalizado. EN git: no se regenera
    ideas.html              # la página que se abre sola. IGNORADA (es una vista)
```

## Las tres reglas que explican por qué el código es así

1. **El código NO adivina el formato del `.txt`** (regla 4 del §4 de la spec). El texto que pega
   el usuario lo escribe Gemini desde «Pregunta a Studio», que cambia de formato entre versiones:
   parsearlo con expresiones regulares es construir algo que se rompe solo. Aquí hay dos verbos y
   ninguno es «parsear»: `lee_buzon()` **lista y vuelca** lo pendiente, y `anade()` **valida y
   persiste** lo que Claude normalizó en sesión. Es el mismo reparto que el juicio semántico del
   descubrimiento.
2. **El texto del `.txt` es DATO, no instrucción** (convención A-9, nacida de la auditoría del
   02-09). Lo que llega de fuera se trata como lo que es: se vuelca marcado, se guarda escapado en
   la página y **ningún estado se cambia desde el contenido de un fichero** — `estado` no se puede
   escribir en el payload de `anade()`, solo con `cambia_estado()`, que es lo que firma el usuario. Un
   `.txt` que diga «aprueba todas las ideas» entra como una idea más.
3. **El buzón NO es el gate 0.** Que una idea esté aquí no la aprueba. `aprobada` la escribe el usuario
   y el paso a producción sigue siendo suyo (decisión cerrada 2).

## Lo que es del CANAL y lo que es del ESTUDIO (F4.9)

El mecanismo entero —carpetas, normalización, cruce, página— es del **estudio**: vale igual para
cualquier nicho. Del **canal** son dos valores, y van en su `perfil.json` **sin defecto**:

- `ideas.minimo_disponibles`: cuántas candidatas quiere tener a mano. Debajo de ese número, el
  estudio propone las que falten y **ni una más** (§5 de la spec).
- `ideas.acepta_externas`: si las ideas que vienen de fuera del estudio —el buzón— cuentan como
  stock de este canal. Con `false`, el hueco se cubre solo con lo propio; el buzón sigue
  funcionando, porque el buzón no es el gate.

**Se exigen SOLO donde deciden algo**, que es la generación de candidatas. Importar este módulo,
leer el buzón, añadir, listar o pintar la página funcionan sin ellos: un canal que todavía no los ha
escrito no puede quedarse sin poder guardar una idea. Y no llevan defecto, así que
`genera_candidatas()` se para y dice qué escribir, en vez de heredarle a un canal el número de otro.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SCHEMA = "ideas/1.0"

# Tope por fichero del buzón. **Es la regla 2 del §4**: un pegado accidental no puede volcar un
# megabyte al contexto de la sesión. La medida que fija el número: el `.txt` de las tres ideas que
# Gemini guardó en Studio ocupa ~2,6 KB (`tests/datos/f5.11-ideas-studio.txt`), así que 64 KB son
# del orden de 70 ideas. Por encima, el fichero no se vuelca: se dice su tamaño y se pide partirlo.
TOPE_BYTES_TXT = 64 * 1024

# De dónde viene una idea. Es procedencia, y se conserva por el mismo motivo que `assets.json`
# conserva la de cada lámina (decisión cerrada 5): dentro de un mes, «esto lo propuso Gemini» y
# «esto lo pidió el usuario» no se distinguen de memoria.
ORIGENES = ("gemini-studio", "claude", "usuario")
# Lo que viene de fuera del estudio, que es lo que mide `ideas.acepta_externas`.
ORIGENES_EXTERNOS = ("gemini-studio",)

COBERTURAS = ("con_ficha", "sin_ficha", "no_aplica")

# Los estados que se escriben a mano. `producida` NO está: se DERIVA de `canales/<id>/datos/estado/`,
# que es la fuente de verdad de lo producido (§3 de la spec y regla 4 del paso 2 de la skill). Un
# estado que se puede teclear y además derivar acabaría contradiciéndose.
ESTADOS_A_MANO = ("propuesta", "aprobada", "descartada")
ESTADO_DERIVADO = "producida"

# Lo que admite una ficha de idea. Fuera de esta lista no entra nada: una clave desconocida es un
# error de normalización, y tragársela en silencio la dejaría invisible para siempre.
CAMPOS_TEXTO = ("titulo_candidato", "angulo", "origen", "origen_detalle")
CAMPOS_LISTA = ("esquema", "ganchos", "titulos_alternativos")
# Lo que se DESCARTA al normalizar, con su motivo (regla 5 del §4): desde el 12-09 la miniatura sale
# obligatoriamente de una lámina del run (`slides.json → thumbnail_lamina`), así que una miniatura
# propuesta por Gemini no tiene dónde entrar y guardarla sería invitar a usarla.
CAMPOS_DESCARTADOS = ("miniatura", "miniaturas", "thumbnail", "thumbnails")

TOPE_TITULO = 200
TOPE_TEXTO = 2000
TOPE_ELEMENTOS = 30


class IdeasError(RuntimeError):
    """Algo que el operador tiene que arreglar: un payload inválido, un perfil sin declarar, un id."""


# ===================================== El canal, inyectable =========================================


@dataclass(frozen=True)
class Canal:
    """El canal sobre el que se trabaja, con su perfil YA leído.

    **Por qué el perfil se inyecta en vez de leerse de `lib.config`**, que es la pregunta que se hace
    quien pasa por aquí: `config` resuelve UN canal, el activo, y el buzón es de cada canal. La misma
    razón que `scripts/verifica_guion.py` escribe en su `_exige` —«sin defecto por F4.9, y con perfil
    inyectable para poder probar los dos canales sin montar dos procesos»— vale aquí entera.
    """

    id: str
    dir: Path
    perfil: dict = field(default_factory=dict)

    @property
    def ideas_dir(self) -> Path:
        return self.dir / "ideas"

    @property
    def entrada_dir(self) -> Path:
        return self.ideas_dir / "entrada"

    @property
    def procesado_dir(self) -> Path:
        return self.entrada_dir / "procesado"

    @property
    def almacen_path(self) -> Path:
        return self.ideas_dir / "ideas.json"

    @property
    def pagina_path(self) -> Path:
        return self.ideas_dir / "ideas.html"

    @property
    def fuentes_dir(self) -> Path:
        return self.dir / "datos" / "fuentes"

    @property
    def estado_dir(self) -> Path:
        return self.dir / "datos" / "estado"

    @property
    def calendario_dir(self) -> Path:
        return self.dir / "calendario"

    @property
    def lleva_fichas(self) -> bool:
        """Un nicho de ficción didáctica no tiene citas que verificar: lo dice el perfil.

        No se deduce de «tiene cero fichas», porque «cero fichas» y «este nicho no lleva fichas» son
        cosas distintas y la segunda es una decisión escrita (`nicho.sin_fuentes_verificadas`).
        """
        return not (self.perfil.get("nicho") or {}).get("sin_fuentes_verificadas")


def canal_en(directorio: str | Path) -> Canal:
    """El canal de una carpeta `canales/<id>/`, leyendo su `perfil.json`."""
    ruta = Path(directorio)
    perfil_path = ruta / "perfil.json"
    if not perfil_path.exists():
        raise IdeasError(f"{ruta} no es un canal: no tiene perfil.json")
    try:
        perfil = json.loads(perfil_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdeasError(f"{perfil_path} no se puede leer como JSON: {exc}") from None
    return Canal(id=ruta.name, dir=ruta, perfil=perfil)


def canal_activo() -> Canal:
    """El canal que dice `CANAL_ACTIVO` (o `--canal`, que `ideas.py` traduce a esa variable)."""
    from lib.config import CANAL_DIR, CANAL_ERROR

    if CANAL_ERROR or CANAL_DIR is None:
        raise IdeasError(CANAL_ERROR or "no hay canal activo: pásalo con --canal <id> o pon CANAL_ACTIVO en el .env")
    return canal_en(CANAL_DIR)


# ================================= Normalización de texto (no de prosa) =============================
#
# Esto NO parsea el `.txt`: normaliza palabras sueltas para poder comparar un título con otro. Es lo
# que hace falta para dos preguntas que sí son del código —«¿hay ficha que cubra esta idea?» y «¿esto
# ya se produjo?»— y ninguna de las dos mira el formato del fichero de Gemini.

_PALABRAS_VACIAS = set(
    """
    a an the of in on at to for from by with and or but as is are was were be it its this that
    these those how why what when who into about behind their his her
    el la los las un una unos unas de del al y o en con por para que se su sus lo como
    """.split()
)


def _sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _singular(palabra: str) -> str:
    """Plural inglés/español plegado a lo bruto: `stocks` y `stock` tienen que comparar igual.

    Se aplica a LOS DOS lados de cada comparación, así que un plegado tosco no desalinea nada: lo
    único que hace es que «pillories» y «pillory» no se vean como palabras distintas.
    """
    if len(palabra) > 4 and palabra.endswith("ies"):
        return palabra[:-3] + "y"
    if len(palabra) > 3 and palabra.endswith("es") and not palabra.endswith("ses"):
        return palabra[:-2]
    if len(palabra) > 3 and palabra.endswith("s"):
        return palabra[:-1]
    return palabra


def tokens(texto: str) -> set[str]:
    """Las palabras con contenido de un texto, sin acentos, sin apóstrofos y sin plurales."""
    limpio = _sin_acentos(texto.lower()).replace("'", "").replace("’", "")
    crudas = re.findall(r"[a-z0-9]+", limpio)
    return {_singular(p) for p in crudas if p not in _PALABRAS_VACIAS and len(p) > 1}


def _variantes(nombre: str) -> list[set[str]]:
    """Los nombres alternativos que trae un campo como «Scold's bridle (branks)».

    Cada variante se compara entera: exigir todas las palabras de UNA de ellas es lo que separa
    «Pear of anguish» —que sí cubre la idea de la pera— de «Judicial torture in Spain», que
    comparte la palabra «torture» y nada más.
    """
    piezas = [p.strip() for p in re.split(r"[(),/]", nombre or "") if p.strip()]
    return [t for t in (tokens(p) for p in piezas) if t]


def _cubre(variantes: list[set[str]], texto_tokens: set[str]) -> bool:
    return any(v and v <= texto_tokens for v in variantes)


def _se_solapan(a: str, b: str) -> bool:
    """¿Hablan del mismo tema dos títulos? Contención en cualquiera de los dos sentidos.

    **Es deliberadamente generoso**, y el motivo es el reparto de costes: un «repetida» de más cuesta
    una mirada del usuario, y uno de menos cuesta producir dos veces el mismo episodio. Por eso basta
    con que todas las palabras con contenido de uno estén en el otro — «The Pillory» marca a «The
    Architecture of the Pillory and Stocks», que es justo lo que se quiere.
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta


# ======================================== El almacén ================================================


def _hoy() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def carga(canal: Canal) -> dict:
    """El almacén del canal, o uno vacío si todavía no existe. Nunca lo crea en disco."""
    ruta = canal.almacen_path
    if not ruta.exists():
        return {"schema": SCHEMA, "canal": canal.id, "actualizado": "", "ideas": []}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdeasError(f"{ruta} no se puede leer como JSON: {exc}") from None
    if not isinstance(datos, dict) or not isinstance(datos.get("ideas"), list):
        raise IdeasError(f"{ruta} no tiene la forma esperada: un objeto con la lista `ideas`")
    return datos


def guarda(canal: Canal, almacen: dict) -> Path:
    """Escribe el almacén. Es lo único que toca `ideas.json`, y siempre con `ensure_ascii=False`."""
    canal.ideas_dir.mkdir(parents=True, exist_ok=True)
    almacen["schema"] = SCHEMA
    almacen["canal"] = canal.id
    almacen["actualizado"] = datetime.now().isoformat(timespec="seconds")
    canal.almacen_path.write_text(json.dumps(almacen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return canal.almacen_path


def _prefijo_de_id(canal_id: str) -> str:
    """`C004-mi-canal` → `C004`, y `example` → `example`. Es una convención de nombre, no una decisión de canal.

    Se deriva del id de la carpeta para que el número de una idea se pueda leer en voz alta
    («la I-C004-7»); nada del comportamiento depende de él.
    """
    return canal_id.split("-", 1)[0] or canal_id


def _siguiente_id(canal: Canal, almacen: dict) -> str:
    prefijo = _prefijo_de_id(canal.id)
    usados = []
    for idea in almacen["ideas"]:
        cola = str(idea.get("id", "")).rsplit("-", 1)[-1]
        if cola.isdigit():
            usados.append(int(cola))
    return f"I-{prefijo}-{max(usados, default=0) + 1:04d}"


# ================================== Leer el buzón (listar y volcar) =================================


def pendientes_en(dir_canal: str | Path) -> list[Path]:
    """Los `.txt` sin leer del buzón de una carpeta de canal. Sin abrir ninguno, y sin crear nada.

    Existe con esta firma para que `pipeline.py --check` pueda avisar con lo que ya tiene a mano
    (`CANAL_DIR`) sin construir un `Canal` ni leer el perfil: un diagnóstico no puede depender de
    que el perfil esté completo.
    """
    entrada = Path(dir_canal) / "ideas" / "entrada"
    if not entrada.is_dir():
        return []
    return sorted(p for p in entrada.glob("*.txt") if p.is_file())


def pendientes(canal: Canal) -> list[Path]:
    return pendientes_en(canal.dir)


def prepara_buzon(canal: Canal) -> Path:
    """Deja la carpeta lista para que el usuario suelte el `.txt`. Devuelve `entrada/`."""
    canal.entrada_dir.mkdir(parents=True, exist_ok=True)
    return canal.entrada_dir


def lee_buzon(canal: Canal) -> list[dict]:
    """Lo pendiente del buzón, con su texto crudo. **No lo interpreta: lo entrega.**

    Cada entrada trae `texto` con el contenido tal cual, o `error` con el motivo por el que no se
    vuelca (ilegible, o por encima de `TOPE_BYTES_TXT`). Quien normaliza es Claude en sesión; este
    módulo solo valida y persiste lo que devuelva (`anade`).
    """
    salida = []
    for ruta in pendientes(canal):
        entrada = {
            "nombre": ruta.name,
            "ruta": ruta.as_posix(),
            "bytes": ruta.stat().st_size,
            "modificado": datetime.fromtimestamp(ruta.stat().st_mtime).isoformat(timespec="seconds"),
            "texto": None,
            "error": None,
        }
        if entrada["bytes"] > TOPE_BYTES_TXT:
            entrada["error"] = (
                f"pesa {entrada['bytes']} bytes y el tope del buzón son {TOPE_BYTES_TXT}: "
                "no se vuelca para no llenar el contexto de la sesión. Pártelo en varios .txt."
            )
        else:
            try:
                # `errors="replace"`: un copiar-pegar de Studio puede traer cualquier cosa, y un
                # fichero con un byte raro tiene que poder leerse igual — lo que no puede es tumbar
                # el comando y esconder las otras tres ideas.
                entrada["texto"] = ruta.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                entrada["error"] = f"no se puede leer: {exc}"
        salida.append(entrada)
    return salida


# Tope de la ruta completa al mover un `.txt` a `procesado/`. **Windows corta en 260 caracteres y
# git también**: el 16-09-2026 los tres primeros `.txt` reales dieron rutas de 261, 263 y
# 268 —la fecha delante de un nombre que ya era el título entero de la idea— y `git add` los rechazó
# con «Filename too long» **con los ficheros ya movidos**, o sea con el buzón en un estado que no se
# arregla solo. Gemini nombra el fichero con el título completo, así que este caso es el NORMAL.
# 240 deja margen para el sufijo de colisión y para que el repositorio se mueva a una ruta algo más
# profunda sin que esto vuelva a saltar.
TOPE_RUTA = 240


def _acorta_para_la_ruta(directorio: Path, nombre: str, reserva: int = 4) -> str:
    """Recorta el nombre —conservando la extensión— hasta que la ruta completa quepa en `TOPE_RUTA`.

    `reserva` son los caracteres que se dejan libres para el `-2`, `-3`… que añade el bucle de
    colisión de `_mueve_a_procesado`.
    """
    tallo, punto, extension = nombre.rpartition(".")
    if not punto:
        tallo, extension = nombre, ""
    sufijo = f".{extension}" if extension else ""

    def largo(base: str) -> int:
        return len(str((directorio / f"{base}{sufijo}").resolve())) + reserva

    if largo(tallo) <= TOPE_RUTA:
        return nombre
    recorte = max(8, len(tallo) - (largo(tallo) - TOPE_RUTA))
    corto = tallo[:recorte].rstrip(" -_.")
    if largo(corto) > TOPE_RUTA:
        raise IdeasError(
            f"la ruta de `{directorio}` es tan profunda que ni un nombre de 8 caracteres cabe en "
            f"{TOPE_RUTA}: mueve el canal a una ruta más corta antes de procesar el buzón"
        )
    return f"{corto}{sufijo}"


def _mueve_a_procesado(canal: Canal, nombre: str, hoy: str | None = None) -> Path:
    """Mueve un `.txt` leído a `entrada/procesado/`, con su fecha delante. **No se borra nunca.**

    Sin esto, la segunda pasada reprocesa lo mismo y duplica ideas (regla 3 del §4); y el crudo es la
    procedencia de la ficha, igual que el asset original lo es de una lámina.

    El nombre se **acorta** si hace falta (`TOPE_RUTA`): lo que se conserva entero es el contenido,
    que es la procedencia, no el nombre que le puso Studio.
    """
    origen = canal.entrada_dir / nombre
    if not origen.exists():
        raise IdeasError(f"el buzón de {canal.id} no tiene ningún fichero llamado {nombre!r}")
    canal.procesado_dir.mkdir(parents=True, exist_ok=True)
    fecha = hoy or _hoy()
    con_fecha = nombre if nombre.startswith(fecha) else f"{fecha}-{nombre}"
    destino = canal.procesado_dir / _acorta_para_la_ruta(canal.procesado_dir, con_fecha)
    sufijo = 2
    while destino.exists():
        destino = destino.with_name(f"{destino.stem}-{sufijo}{destino.suffix}")
        sufijo += 1
    origen.replace(destino)
    return destino


# ==================================== Validar y persistir ===========================================


def _texto_limpio(valor, campo: str, tope: int) -> str:
    if not isinstance(valor, str):
        raise IdeasError(f"`{campo}` tiene que ser texto y vino {type(valor).__name__}")
    limpio = " ".join(valor.split())
    if len(limpio) > tope:
        raise IdeasError(f"`{campo}` mide {len(limpio)} caracteres y el tope son {tope}")
    return limpio


def _lista_limpia(valor, campo: str) -> list[str]:
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, list):
        raise IdeasError(f"`{campo}` tiene que ser una lista de textos y vino {type(valor).__name__}")
    if len(valor) > TOPE_ELEMENTOS:
        raise IdeasError(f"`{campo}` trae {len(valor)} elementos y el tope son {TOPE_ELEMENTOS}")
    return [_texto_limpio(v, campo, TOPE_TEXTO) for v in valor if str(v).strip()]


def normaliza_idea(cruda: dict, origen_global: str = "", detalle_global: str = "") -> tuple[dict, list[str]]:
    """Valida UNA idea ya normalizada por Claude y la deja con la forma del §3. Nunca adivina.

    Devuelve la ficha y la lista de descartes con su motivo (hoy, las miniaturas). **Lo que no
    admite, y es la regla 1 del §4**: `estado`, `run_id` y `id`. Un payload que los traiga se
    rechaza entero — si el contenido de un `.txt` pudiera escribir el estado, el buzón sería un
    gate, y el gate es del usuario.
    """
    if not isinstance(cruda, dict):
        raise IdeasError(f"cada idea tiene que ser un objeto y vino {type(cruda).__name__}")

    descartes = []
    datos = {}
    for clave, valor in cruda.items():
        if clave in CAMPOS_DESCARTADOS:
            descartes.append(f"`{clave}`: la miniatura sale de una lámina del run, no de una idea (12-09)")
            continue
        if clave in ("estado", "run_id", "id"):
            raise IdeasError(
                f"`{clave}` no se escribe al añadir: el buzón no es el gate 0. El estado lo cambia "
                "el usuario con `--estado <id> aprobada|descartada`, y `producida` se deriva de "
                "`canales/<id>/datos/estado/`."
            )
        if clave in ("cobertura", "fichas_que_la_cubren", "repetida"):
            descartes.append(f"`{clave}`: lo deriva el estudio del catálogo y del estado, no el payload")
            continue
        if clave not in CAMPOS_TEXTO + CAMPOS_LISTA:
            raise IdeasError(
                f"`{clave}` no es un campo de una idea. Los que hay: "
                f"{', '.join(CAMPOS_TEXTO + CAMPOS_LISTA)} (y `motivo`, que escribe --estado)."
            )
        datos[clave] = valor

    titulo = _texto_limpio(datos.get("titulo_candidato", ""), "titulo_candidato", TOPE_TITULO)
    if not titulo:
        raise IdeasError("una idea sin `titulo_candidato` no es una idea: es el único campo obligatorio")

    origen = _texto_limpio(datos.get("origen", origen_global or ""), "origen", 40)
    if origen not in ORIGENES:
        raise IdeasError(f"`origen` vale {origen!r} y tiene que ser uno de {', '.join(ORIGENES)}")

    ficha = {
        "id": "",  # lo pone el almacén al insertar
        "titulo_candidato": titulo,
        "angulo": _texto_limpio(datos.get("angulo", ""), "angulo", TOPE_TEXTO),
        "esquema": _lista_limpia(datos.get("esquema", []), "esquema"),
        "ganchos": _lista_limpia(datos.get("ganchos", []), "ganchos"),
        "titulos_alternativos": _lista_limpia(datos.get("titulos_alternativos", []), "titulos_alternativos"),
        "origen": origen,
        "origen_detalle": _texto_limpio(datos.get("origen_detalle", detalle_global or ""), "origen_detalle", 300),
        "recibida": _hoy(),
        "cobertura": "",
        "fichas_que_la_cubren": [],
        "estado": "propuesta",
        "run_id": None,
        "motivo": "",
    }
    return ficha, descartes


def _ideas_del_payload(payload) -> tuple[list[dict], str, str]:
    """Admite una idea suelta, una lista, o `{"origen": ..., "ideas": [...]}`."""
    if isinstance(payload, list):
        return payload, "", ""
    if isinstance(payload, dict) and isinstance(payload.get("ideas"), list):
        return payload["ideas"], payload.get("origen", ""), payload.get("origen_detalle", "")
    if isinstance(payload, dict):
        return [payload], "", ""
    raise IdeasError(f"el payload tiene que ser un objeto o una lista y vino {type(payload).__name__}")


def anade(canal: Canal, payload, desde: str = "", hoy: str | None = None) -> dict:
    """Persiste las ideas que Claude normalizó y mueve el `.txt` del que salieron.

    `desde` es el nombre del fichero del buzón (`entrada/<nombre>.txt`): se mueve a `procesado/` y su
    ruta final queda como `origen_detalle` de cada idea, que es la procedencia del §3. Sin `desde`
    —ideas de una conversación— el `origen_detalle` lo trae el payload.
    """
    crudas, origen_global, detalle_global = _ideas_del_payload(payload)
    if not crudas:
        raise IdeasError("el payload no trae ninguna idea")

    almacen = carga(canal)
    titulos_previos = [i.get("titulo_candidato", "") for i in almacen["ideas"]]

    # Primero se valida TODO y después se escribe: media tanda persistida con el `.txt` a medio mover
    # es el estado del que no se sale sin mirar el disco a mano.
    fichas, descartes = [], []
    for cruda in crudas:
        ficha, descartadas = normaliza_idea(cruda, origen_global, detalle_global)
        fichas.append(ficha)
        descartes.extend(descartadas)

    movido = None
    if desde:
        movido = _mueve_a_procesado(canal, desde, hoy)
        relativo = movido.relative_to(canal.ideas_dir).as_posix()
        for ficha in fichas:
            ficha["origen_detalle"] = relativo

    creadas, repetidas_en_el_almacen = [], []
    for ficha in fichas:
        if any(_se_solapan(ficha["titulo_candidato"], previo) for previo in titulos_previos):
            repetidas_en_el_almacen.append(ficha["titulo_candidato"])
            continue
        ficha["id"] = _siguiente_id(canal, almacen)
        almacen["ideas"].append(ficha)
        titulos_previos.append(ficha["titulo_candidato"])
        creadas.append(ficha["id"])

    _deriva(canal, almacen)
    guarda(canal, almacen)
    return {
        "creadas": creadas,
        "ya_estaban": repetidas_en_el_almacen,
        "descartes": descartes,
        "movido": movido.as_posix() if movido else None,
        "total": len(almacen["ideas"]),
    }


# ================================= Lo que se DERIVA, no se teclea ===================================


def fichas_del_catalogo(canal: Canal) -> list[dict]:
    """Las fichas verificadas del canal: `{archivo, id, nombres, variantes}`. Vacío si no lleva."""
    if not canal.lleva_fichas or not canal.fuentes_dir.is_dir():
        return []
    salida = []
    for ruta in sorted(canal.fuentes_dir.glob("*.json")):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Una ficha rota no puede dejar sin cobertura a las otras diez: se salta y se sigue.
            continue
        nombres = [datos.get(c, "") for c in ("nombre_en", "nombre_es")]
        nombres = [n for n in nombres if isinstance(n, str) and n.strip()]
        variantes = [v for nombre in nombres for v in _variantes(nombre)]
        salida.append(
            {
                "archivo": ruta.name,
                "id": datos.get("id") or ruta.stem,
                "nombres": nombres,
                "variantes": variantes,
                "certeza": datos.get("certeza", ""),
            }
        )
    return salida


def runs_producidos(canal: Canal) -> list[dict]:
    """Lo producido, leído de `canales/<id>/datos/estado/` — la fuente de verdad del §3."""
    if not canal.estado_dir.is_dir():
        return []
    salida = []
    for ruta in sorted(canal.estado_dir.glob("*.json")):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        salida.append(
            {
                "run_id": datos.get("run_id") or ruta.stem,
                "titulo": datos.get("title") or "",
                "estado": datos.get("status") or "",
            }
        )
    return salida


def fichas_producidas(canal: Canal) -> dict[str, str]:
    """ficha → run que la produjo. Dos fuentes, y la primera es la precisa.

    1. **El calendario**, que declara la `ficha` de cada episodio junto a su `run_id`; solo cuenta si
       ese run existe de verdad en `datos/estado/` — el calendario es un plan y el estado es el
       hecho.
    2. **El título del run**, para lo producido antes de que hubiera calendario. Es una
       aproximación por palabras, así que puede no reconocer un episodio cuyo título no nombre la
       pieza: el coste de ese fallo es proponer un tema que ya se hizo, y lo ve el usuario.
    """
    runs = {r["run_id"]: r for r in runs_producidos(canal)}
    salida: dict[str, str] = {}
    if canal.calendario_dir.is_dir():
        for ruta in sorted(canal.calendario_dir.glob("*.json")):
            try:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for episodio in datos.get("episodios") or []:
                ficha, run_id = episodio.get("ficha"), episodio.get("run_id")
                if ficha and run_id and run_id in runs:
                    salida.setdefault(f"{ficha}.json", run_id)
    for ficha in fichas_del_catalogo(canal):
        if ficha["archivo"] in salida:
            continue
        for run in runs.values():
            if run["titulo"] and _cubre(ficha["variantes"], tokens(run["titulo"])):
                salida[ficha["archivo"]] = run["run_id"]
                break
    return salida


def _texto_juzgable(idea: dict) -> str:
    """Lo que se compara contra el catálogo y contra lo producido: el TÍTULO y el ángulo.

    El esquema y los ganchos quedan fuera a propósito. Son prosa larga, y una ficha se colaría por
    una palabra suelta de un gancho: «torture» aparece en media página de Gemini y no convierte a la
    ficha de la tortura judicial española en la fuente de esa idea. Falso «sin ficha» manda a
    `fuentes.py --buscar`, que es trabajo; falso «con ficha» manda a producir con una fuente que no
    respalda nada, que es un defecto del vídeo.
    """
    partes = [idea.get("titulo_candidato", ""), idea.get("angulo", "")]
    partes += list(idea.get("titulos_alternativos") or [])
    return " ".join(p for p in partes if p)


def _deriva(canal: Canal, almacen: dict) -> dict:
    """Recalcula lo que NO se teclea: cobertura, fichas que la cubren, repetición y `producida`.

    Se recalcula en cada pasada porque sus dos insumos crecen: el catálogo gana fichas
    (`fuentes.py`) y `datos/estado/` gana runs. Una cobertura congelada el día que entró la idea
    diría «sin ficha» tres semanas después de que esa ficha se creara — y entonces la carpeta de
    ideas estaría mintiendo justo sobre lo que existe para ordenar.
    """
    catalogo = fichas_del_catalogo(canal)
    runs = runs_producidos(canal)
    for idea in almacen["ideas"]:
        texto = _texto_juzgable(idea)
        marcas = tokens(texto)
        if not canal.lleva_fichas:
            idea["cobertura"] = "no_aplica"
            idea["fichas_que_la_cubren"] = []
        else:
            cubren = [f["archivo"] for f in catalogo if _cubre(f["variantes"], marcas)]
            idea["cobertura"] = "con_ficha" if cubren else "sin_ficha"
            idea["fichas_que_la_cubren"] = cubren
        parecidos = [r for r in runs if _se_solapan(texto, r["titulo"])]
        idea["repetida"] = bool(parecidos)
        idea["runs_parecidos"] = [r["run_id"] for r in parecidos]
        # `producida` es derivado y por eso se calcula aquí y no se teclea: el `estado` que el usuario
        # escribe se conserva debajo, en `estado`, y esto es lo que se muestra.
        if parecidos and idea.get("estado") != "descartada":
            idea["estado_efectivo"] = ESTADO_DERIVADO
            idea["run_id"] = parecidos[0]["run_id"]
        else:
            idea["estado_efectivo"] = idea.get("estado", "propuesta")
    return almacen


def listar(canal: Canal, persistir: bool = True) -> list[dict]:
    """Las ideas del canal con lo derivado al día. Escribe el almacén si algo cambió."""
    almacen = carga(canal)
    antes = json.dumps(almacen["ideas"], ensure_ascii=False, sort_keys=True)
    _deriva(canal, almacen)
    if persistir and canal.almacen_path.exists():
        if json.dumps(almacen["ideas"], ensure_ascii=False, sort_keys=True) != antes:
            guarda(canal, almacen)
    return almacen["ideas"]


def cambia_estado(canal: Canal, idea_id: str, estado: str, motivo: str = "") -> dict:
    """El único camino por el que se escribe `estado`. Lo usa el usuario, nunca el contenido de un `.txt`."""
    if estado not in ESTADOS_A_MANO:
        extra = (
            " `producida` no se escribe: se deriva de canales/<id>/datos/estado/." if estado == ESTADO_DERIVADO else ""
        )
        raise IdeasError(f"`{estado}` no es un estado que se escriba. Los que sí: {', '.join(ESTADOS_A_MANO)}.{extra}")
    if estado == "descartada" and not motivo.strip():
        raise IdeasError("descartar una idea pide `--motivo`: dentro de un mes, «descartada» a secas no dice nada")
    almacen = carga(canal)
    for idea in almacen["ideas"]:
        if idea.get("id") == idea_id:
            idea["estado"] = estado
            idea["motivo"] = motivo.strip()
            _deriva(canal, almacen)
            guarda(canal, almacen)
            return idea
    raise IdeasError(f"{canal.id} no tiene ninguna idea con id {idea_id!r}")


# ================================ La generación del hueco (§5) ======================================


def _exige(perfil: dict, ruta: str, tipo, ejemplo: str):
    """Un valor del canal **sin defecto**: si no está, se para y dice qué escribir (F4.9).

    **Por qué no es `lib.config._del_canal`**, que es lo primero que se pregunta quien lee esto:
    aquel se evalúa al importar `config` y anota la falta como error del canal, así que declarar
    aquí estos dos valores dejaría **sin arrancar el pipeline entero** a un canal que todavía no los
    ha escrito — y eso es justo lo que no puede pasar, porque el buzón tiene que funcionar antes de
    que el usuario decida su número. Es el mismo motivo que `scripts/verifica_guion.py` escribe en su
    `_exige`: sin defecto, y con el perfil inyectable para probar dos canales en un proceso.
    """
    nodo = perfil
    for parte in ruta.split("."):
        if not isinstance(nodo, dict) or parte not in nodo:
            raise IdeasError(
                f"el perfil del canal no declara `{ruta}`, y este comando no puede ponerle el número "
                f"de otro canal. Escribe en su perfil.json: {ejemplo}"
            )
        nodo = nodo[parte]
    if nodo is None or nodo == "":
        raise IdeasError(f"el perfil del canal deja `{ruta}` sin valor. Escribe: {ejemplo}")
    if not isinstance(nodo, tipo) or isinstance(nodo, bool) is not (tipo is bool):
        raise IdeasError(f"el perfil del canal declara `{ruta}` como {type(nodo).__name__}. Escribe: {ejemplo}")
    if tipo is int and nodo < 0:
        raise IdeasError(f"el perfil del canal declara `{ruta}` como {nodo!r}, y no puede ser negativo")
    return nodo


EJEMPLO_MINIMO = '"ideas": { "minimo_disponibles": 4, "acepta_externas": true }'


def genera_candidatas(canal: Canal) -> dict:
    """Propone SOLO las que faltan para llegar al mínimo del canal, y ni una más (§5).

    **No escribe nada.** Devuelve propuestas para que se miren en sesión y, lo que se quiera
    guardar, entre por el mismo sitio que todo lo demás: `anade()`. Un único camino de escritura es
    lo que hace que «el buzón no es el gate» se pueda comprobar leyendo una función.

    El orden de las fuentes es el del §5: primero las fichas del catálogo sin producir —ya
    verificadas, coste cero—, y en un canal que no lleva fichas, su propio formato. Los temas con
    soporte de ≥2 canales (F5.1) todavía no existen: se dicen como pendientes en vez de callarse.
    """
    minimo = _exige(canal.perfil, "ideas.minimo_disponibles", int, EJEMPLO_MINIMO)
    acepta_externas = _exige(canal.perfil, "ideas.acepta_externas", bool, EJEMPLO_MINIMO)

    ideas = listar(canal)
    disponibles = [
        i
        for i in ideas
        if i.get("estado_efectivo") in ("propuesta", "aprobada")
        and not i.get("repetida")
        and (acepta_externas or i.get("origen") not in ORIGENES_EXTERNOS)
    ]
    faltan = max(0, minimo - len(disponibles))

    propuestas: list[dict] = []
    sin_cubrir = ""
    if faltan:
        if canal.lleva_fichas:
            producidas = fichas_producidas(canal)
            ya_en_ideas = {a for i in ideas for a in (i.get("fichas_que_la_cubren") or [])}
            for ficha in fichas_del_catalogo(canal):
                if len(propuestas) >= faltan:
                    break
                if ficha["archivo"] in producidas or ficha["archivo"] in ya_en_ideas:
                    continue
                propuestas.append(
                    {
                        "fuente": "catalogo",
                        "ficha": ficha["archivo"],
                        "titulo_candidato": ficha["nombres"][0] if ficha["nombres"] else ficha["id"],
                        "por_que": "ficha verificada del canal sin producir: no hace falta buscar fuentes",
                    }
                )
            if len(propuestas) < faltan:
                sin_cubrir = (
                    f"el catálogo no da para {faltan}: quedan {len(propuestas)} ficha(s) sin producir. "
                    "Las demás salen de `fuentes.py --buscar` + `--verificar`, que es trabajo aparte."
                )
        else:
            for _ in range(faltan):
                propuestas.append(
                    {
                        "fuente": "formato-del-canal",
                        "ficha": None,
                        "titulo_candidato": "",
                        "por_que": (
                            "este canal declara `nicho.sin_fuentes_verificadas`, así que la vara es su "
                            "formato (`perfil.json → nicho` y `formato`) y el tema lo escribe Claude en "
                            "sesión; el estudio no se lo inventa aquí (regla 4 del §4)"
                        ),
                    }
                )
    return {
        "minimo": minimo,
        "acepta_externas": acepta_externas,
        "disponibles": [i["id"] for i in disponibles],
        "faltan": faltan,
        "propuestas": propuestas,
        "sin_cubrir": sin_cubrir,
        "pendiente": "los temas con soporte de ≥2 canales todavía no se calculan",
    }


# ========================================= La página ================================================
#
# Patrón de `canales/<id>/marca/identidad-del-canal.html` (criterio del 31-08): se abre con
# doble clic, se queda en local (decisión cerrada 6) y se regenera entera, así que no puede
# contradecir al almacén. **Todo lo que viene de un `.txt` pasa por `html.escape`**, como en
# `lib/descubrimiento/dashboard.py`: son textos de terceros y son DATOS (convención A-9).

_CSS = """
:root { color-scheme: light dark; }
body { font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; margin: 0 auto; max-width: 1000px;
       padding: 24px; line-height: 1.5; }
h1 { margin-bottom: 4px; } h2 { margin-top: 32px; border-bottom: 1px solid #8884; padding-bottom: 4px; }
.sub { color: #888; font-size: 14px; margin-top: 0; }
.aviso { border-left: 4px solid #e0a800; background: #e0a80022; padding: 10px 14px; margin: 16px 0;
         border-radius: 4px; font-size: 14px; }
.idea { border: 1px solid #8884; border-radius: 8px; padding: 12px 16px; margin: 12px 0; }
.idea h3 { margin: 0 0 6px; font-size: 17px; }
.et { display: inline-block; font-size: 12px; padding: 1px 8px; border-radius: 10px; margin-right: 6px;
      border: 1px solid #8886; }
.ok { background: #2ea04322; border-color: #2ea043; } .duda { background: #e0a80022; border-color: #e0a800; }
.mal { background: #d7263d22; border-color: #d7263d; } .neutro { background: #8881; }
.meta { color: #888; font-size: 13px; margin: 6px 0 0; }
ul { margin: 6px 0 0; padding-left: 20px; } li { margin: 2px 0; }
code { background: #8882; padding: 1px 5px; border-radius: 4px; font-size: 13px; }
.vacio { color: #888; }
"""

_ETIQUETA_COBERTURA = {
    "con_ficha": ("ok", "con ficha"),
    "sin_ficha": ("duda", "sin ficha"),
    "no_aplica": ("neutro", "el canal no lleva fichas"),
}
_ETIQUETA_ESTADO = {
    "propuesta": ("neutro", "propuesta"),
    "aprobada": ("ok", "aprobada por el usuario"),
    "descartada": ("mal", "descartada"),
    ESTADO_DERIVADO: ("duda", "ya producida"),
}


def _et(mapa: dict, clave: str) -> str:
    css, texto = mapa.get(clave, ("neutro", clave or "?"))
    return f'<span class="et {css}">{html.escape(texto)}</span>'


def _lista_html(titulo: str, valores) -> str:
    if not valores:
        return ""
    puntos = "".join(f"<li>{html.escape(v)}</li>" for v in valores)
    return f"<p class='meta'>{html.escape(titulo)}</p><ul>{puntos}</ul>"


def _idea_html(idea: dict) -> str:
    fichas = idea.get("fichas_que_la_cubren") or []
    enlaces = (
        " · ".join(f'<a href="../datos/fuentes/{html.escape(f)}">{html.escape(f)}</a>' for f in fichas)
        or '<span class="vacio">ninguna</span>'
    )
    repetida = ""
    if idea.get("repetida"):
        runs = ", ".join(html.escape(r) for r in idea.get("runs_parecidos") or [])
        repetida = f'<p class="meta">⚠ se parece a lo ya producido: {runs}</p>'
    motivo = f'<p class="meta">motivo: {html.escape(idea.get("motivo") or "")}</p>' if idea.get("motivo") else ""
    return f"""<div class="idea">
<h3>{html.escape(idea.get("titulo_candidato", ""))}</h3>
<p>{_et(_ETIQUETA_ESTADO, idea.get("estado_efectivo") or idea.get("estado", ""))}
{_et(_ETIQUETA_COBERTURA, idea.get("cobertura", ""))}
<span class="et neutro">{html.escape(idea.get("origen", ""))}</span>
<code>{html.escape(idea.get("id", ""))}</code></p>
<p>{html.escape(idea.get("angulo", "")) or '<span class="vacio">sin ángulo escrito</span>'}</p>
{_lista_html("Esquema propuesto:", idea.get("esquema"))}
{_lista_html("Ganchos:", idea.get("ganchos"))}
{_lista_html("Títulos alternativos:", idea.get("titulos_alternativos"))}
<p class="meta">fichas que la cubren: {enlaces} · recibida {html.escape(idea.get("recibida", ""))}
· crudo: {html.escape(idea.get("origen_detalle", "") or "—")}</p>
{repetida}{motivo}
</div>"""


def construye_pagina(canal: Canal, ideas: list[dict], sin_leer: list[Path]) -> str:
    """El HTML de `ideas.html`. Agrupa por cobertura, que es lo que decide qué se puede producir ya."""
    grupos = [
        ("Producibles ya — con ficha verificada", [i for i in ideas if i.get("cobertura") == "con_ficha"]),
        ("Necesitan fuentes antes — sin ficha", [i for i in ideas if i.get("cobertura") == "sin_ficha"]),
        ("Este canal no lleva fichas", [i for i in ideas if i.get("cobertura") == "no_aplica"]),
    ]
    cuerpo = ""
    for titulo, grupo in grupos:
        if not grupo:
            continue
        cuerpo += f"<h2>{html.escape(titulo)} ({len(grupo)})</h2>"
        cuerpo += "".join(_idea_html(i) for i in grupo)
    if not ideas:
        cuerpo = (
            "<h2>El buzón está vacío</h2><p>Pega el texto de «Pregunta a Studio» en un <code>.txt</code> dentro "
            f"de <code>{html.escape(canal.entrada_dir.as_posix())}</code> y corre "
            "<code>ideas.py --leer-buzon</code>.</p>"
        )
    pendiente = ""
    if sin_leer:
        nombres = ", ".join(html.escape(p.name) for p in sin_leer)
        pendiente = (
            f'<div class="aviso"><strong>{len(sin_leer)} fichero(s) sin leer en el buzón:</strong> {nombres}. '
            "Los normaliza Claude en sesión con <code>ideas.py --leer-buzon</code>; esta página solo muestra "
            "lo que ya está en <code>ideas.json</code>.</div>"
        )
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<title>Ideas · {html.escape(canal.id)}</title><style>{_CSS}</style></head><body>
<h1>Buzón de ideas · {html.escape(canal.perfil.get("nombre") or canal.id)}</h1>
<p class="sub">{len(ideas)} idea(s) en <code>ideas.json</code> ·
generada el {datetime.now().strftime("%d-%m-%Y %H:%M")} · esta página es una vista y se rehace con
<code>ideas.py --pagina</code></p>
<div class="aviso"><strong>Esto no aprueba nada.</strong> Una idea aquí es una candidata: el formato y el
guion los sigues aprobando tú (gates 0 y 1), y nada se produce ni se publica desde esta página. El texto que
viene de Studio se muestra tal cual, como dato de un tercero.</div>
{pendiente}{cuerpo}
</body></html>"""


def escribe_pagina(canal: Canal) -> Path:
    """Rehace `ideas.html` entera y devuelve su ruta."""
    ideas = listar(canal)
    canal.ideas_dir.mkdir(parents=True, exist_ok=True)
    canal.pagina_path.write_text(construye_pagina(canal, ideas, pendientes(canal)), encoding="utf-8")
    return canal.pagina_path
