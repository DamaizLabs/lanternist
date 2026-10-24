"""Comprueba un `slides.json` contra el contrato del canal ANTES de gastar GPU.

Correr:  .venv\\Scripts\\python scripts/verifica_guion.py <ruta al slides.json> [...]

## Qué comprueba y qué NO

Comprueba **lo que se puede medir**: la longitud de cada lámina, el número de láminas, la forma de
los capítulos, los campos de la miniatura, la lista negra de adjetivos del contrato de prompt y los
colores que el guardián de líneas rojas leería como sangre.

**No comprueba el criterio**, y conviene decirlo para que nadie confunda un verde de aquí con un
guion aprobado: que cada `image_prompt` represente lo que dice SU narración, que el desmentido esté
en los primeros treinta segundos, que la postura de una figura respete la frontera del gate 0 §8.1 y
que el guion no cuente un mito como un hecho **son cosas que hay que leer**. Eso es el gate 1, y lo
firma el usuario.

## Por qué existe

Porque los cuatro fallos que este script sí caza cuestan una producción entera cuando se descubren
tarde: una lámina de 120 palabras desequilibra el montaje, un `thumbnail_text` ausente deja la etapa
`thumbnail` en `blocked` después de 34 minutos de GPU, y un acento en caoba **detiene la producción**
al pasar por `lib/lineas_rojas.py` (la tabla del contrato de prompt mide caoba, ladrillo y terracota
en 6,7-12,0 grados de tono, por debajo del umbral de 12 que marca la sangre).

## De quién es cada regla: del ESTUDIO o del CANAL (F5.6)

**Hasta el 14-09-2026 este fichero llevaba siete decisiones del primer canal escritas como constantes del
ESTUDIO**, así que ningún guion de otro canal podía dar «0 fallos» — y «0 fallos» es la condición de
entrega de la skill `produce-semana`. Medido ese día sobre el único episodio del segundo canal: **18 fallos, y
quince eran de capa** — 6 por la palabra `red` en un canal que declara `guardianes_de_color: []` a
propósito, 5 por una banda de palabras derivada del ritmo y del formato del primero, 2 por marcadores de
descripción que ese canal no escribe, 1 por capítulos que no lleva y 1 por el número de láminas.

Es la misma fuga de capa que F4.9 cerró en `lib/`, entrando por la puerta de `scripts/`. El reparto,
que es el de `doc/06-arquitectura-estudio-canales.md`:

- **Del CANAL, y sin defecto**: el ritmo medido de su voz, su banda de duración, sus láminas
  estimadas, las palabras de prompt que dispararían sus guardianes de color, su lista negra de
  materialidad, si lleva capítulos y si tiene aparato de fuentes. Todo eso vive en su `perfil.json`.
  **Si el perfil no lo declara, el verificador lo dice y NO evalúa** la regla que dependía de ello:
  nunca la rellena con la decisión de otro canal, que es literalmente lo que F4.9 prohíbe.
- **Del ESTUDIO**: el mecanismo entero, la anchura de las bandas (cuánto puede apartarse una lámina
  del ritmo que el canal se fijó), las fórmulas de respaldo, los delatores de castellano, la regla de
  bienvenida y despedida y los límites de la miniatura, que los mide `lib/miniatura.py` igual para
  todos.

Salida: exit 0 si todo pasa, 1 si hay algún fallo. Los avisos no tumban el exit code.

**TRAMPA CONOCIDA (21-09-2026): sobre el `slides.json` de un run YA SUBIDO da un FALLO FALSO.**
La etapa de subida sustituye `<<CAPITULOS>>` por el índice real con minutaje, así que la copia del
run ya no trae el marcador y este verificador lo pide. El guion que hay que juzgar es el **borrador**
—`canales/<id>/calendario/borradores/`—, que lo conserva. Lo descubrieron por separado los cuatro
agentes que reescribieron los prompts de la W39, uno por episodio: si cuesta cuatro veces averiguarlo,
es más barato escribirlo aquí.

## Las cifras de un nicho que las exige (F7.12, filas 273-275)

Solo en los canales cuyo perfil de NICHO (`datos/autoridades/<nicho>.json`) declara
`cifras.exige_frase_confirmada` —como el de ejemplo, `ejemplo-con-cifras`—, el verificador comprueba además:

- que cada ficha que declara el guion en `fuentes` valide y esté en `cifras_confirmadas` (cada cifra con
  su frase exacta en su origen y la confirmación del usuario con su huella);
- que cada cantidad de dinero, porcentaje, punto porcentual o cantidad con «million», «billion» o
  «trillion» de la narración, en dígitos o dicha con palabras, sea el `valor` de una cifra confirmada o su
  `se_dice` (el redondeo que comprueba el código, filas 277 y 280), o el `se_dice` o un dato de una cuenta
  de esas fichas. Si no lo es, **FALLO**;
- que el resultado de una cuenta lleve sus datos en la misma lámina: la cuenta se escribe en el guion
  (fila 274), y un «about $197» sin el «$100 al 7 % durante 10 años» no es una cuenta escrita.

Los años y los números sin unidad van como aviso. Lo que lleva moneda, porcentaje o una escala abreviada
y no se lee («$4.1bn», «45bn») es **FALLO**. Las cifras dichas con palabras las lee la gramática del
canonizador de la voz (`lib/fuentes/cifras.py → cantidades`), la misma que usa el recorte de Orpheus.
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_RAIZ = Path(__file__).resolve().parent.parent


def _canal_de_la_ruta(argv: list[str]) -> str:
    """El canal al que pertenece el primer guion de la línea de órdenes, o cadena vacía.

    Un `slides.json` vive siempre dentro de `canales/<id>/`, así que **la ruta ya dice de qué canal
    es** y no hace falta que nadie lo recuerde. Es deliberadamente una deducción de la RUTA y no del
    contenido: el guion no declara canal, y si lo declarara sería un sitio más donde equivocarse.
    """
    for arg in argv:
        if arg.startswith("-"):
            continue
        try:
            partes = Path(arg).resolve().relative_to(_RAIZ / "canales").parts
        except (ValueError, OSError):
            continue
        if partes:
            return partes[0]
    return ""


# **El canal se resuelve ANTES de importar `lib/`, y tiene que ser así** — mismo motivo que en
# `pipeline.py`: `lib/config.py` lee `CANAL_ACTIVO` al importarse y de ahí derivan el perfil, la
# receta de voz y todas las bandas. Cuando `argparse` corre ya es tarde.
#
# **Qué cierra.** F5.6 hizo que este fichero derivara del perfil todo lo que juzga, pero dejó fuera
# *de qué canal* es ese perfil: salía del `.env`, o sea de ambiente que sobrevive entre sesiones.
# Medido el 16-09-2026 sobre el último guion de un canal con `CANAL_ACTIVO` apuntando a otro: **24 fallos, todos
# falsos** —banda de 40 láminas, ritmo 2,44, bibliografía obligatoria, la bienvenida de otro canal—
# y ninguno decía que el problema fuera de capa. Con la deducción por ruta, medir el guion de un
# canal con el perfil de otro deja de ser posible sin escribirlo a mano.
if "--canal" in sys.argv:
    _i = sys.argv.index("--canal")
    if _i + 1 < len(sys.argv):
        os.environ["CANAL_ACTIVO"] = sys.argv[_i + 1].strip()
else:
    _deducido = _canal_de_la_ruta(sys.argv[1:])
    if _deducido:
        os.environ["CANAL_ACTIVO"] = _deducido

from lib import lineas_rojas  # noqa: E402
from lib.config import CANAL_ACTIVO, CANAL_PERFIL, MOTOR_DE_VOZ, NARRATION_LANG  # noqa: E402
from lib.fuentes import cifras as fuentes_cifras  # noqa: E402
from lib.fuentes import ficha as fuentes_ficha  # noqa: E402
from lib.fuentes import registro as fuentes_registro  # noqa: E402
from lib.fuentes.base import FuentesError  # noqa: E402
from lib.miniatura import PALABRAS_MAXIMAS  # noqa: E402
from lib.voice_client import VoiceError, load_recipe, revisa_etiquetas_emocionales, sin_etiquetas  # noqa: E402

# --- Lo que es del ESTUDIO: vale igual para cualquier canal ------------------------------------
#
# **Lo invariable es SEGUNDOS por lámina, no palabras.** Las palabras son la banda derivada: se
# obtienen multiplicando los segundos por el ritmo del motor de voz. Confundirlo costó el episodio
# 1 del primer canal (addendum fila 121), así que la derivación queda escrita aquí y no en la cabeza de
# quien la mantenga.
#
# Lo que el estudio pone es la ANCHURA de la banda —cuánto puede apartarse una lámina del ritmo que
# el canal se fijó—, en fracción de ese ritmo. El CENTRO es del canal: sale de dividir su duración
# objetivo entre sus láminas estimadas, y eso cambia con el nicho.
#
# Los números conservan la proporción del primer canal al céntimo y por eso se escriben como la división de
# la que salen, no como un decimal redondeado: sus bandas eran 25,7-35,0 s (objetivo) y 16,4-42,1 s
# (límite duro) sobre un centro de 30 s (20 min ÷ 40 láminas). Con ellas, ese canal sigue dando 63-85 y
# 40-103 exactamente, que es la regresión que F5.6 tenía que respetar.
FRACCION_OBJETIVO = (25.7 / 30.0, 35.0 / 30.0)
FRACCION_DURA = (16.4 / 30.0, 42.1 / 30.0)

# Cuánto puede apartarse el número de láminas de un guion del que su canal estima.
TOLERANCIA_LAMINAS = 0.25

# Fórmulas que un guion NO puede usar mientras las fichas estén en `solo_citas_verificadas`:
# las citas existen y tratan del tema, pero nadie ha leído las obras (checklist del gate 1 §A).
#
# **Es del ESTUDIO, pero solo aplica donde HAY fichas** (F5.6): son afirmaciones de respaldo
# documental, así que en un canal de ficción didáctica no hay nada que respaldar y la regla no dice
# nada. Quién tiene aparato de fuentes lo declara cada canal en su perfil.
FORMULAS_DE_RESPALDO = (
    r"\bit is documented\b",
    r"\bthe records show\b",
    r"\brecords show\b",
    r"\bhistorians have proven\b",
    r"\bhas been proven\b",
    r"\bevidence shows\b",
    r"\bstudies show\b",
    r"\bwe know for certain\b",
)

# Palabras que delatan que se ha colado castellano en la narración. El castellano es el idioma de
# trabajo del estudio —esta misma documentación lo está—, así que el riesgo existe en cualquier
# canal que narre en otro idioma, no solo en inglés.
#
# **Ojo si algún día hay un canal en otra lengua romance**: «que», «para» y «como» son palabras
# nativas del portugués y del gallego, así que ahí este detector daría falsos positivos y habría que
# rehacer la lista. Cuesta poco tenerlo presente porque es un AVISO y no tumba el exit code.
DELATORES_ES = (r"\bque\b", r"\bpara\b", r"\bcomo\b", r"\bpero\b", r"\bcon el\b", r"\bde la\b")
IDIOMA_DEL_ESTUDIO = "es"

# Onomatopeyas que el motor de voz **PRONUNCIA como palabra** en vez de sonar.
#
# **Es del ESTUDIO y no de un canal**: es una propiedad de cómo un TTS lee texto, igual que la regla
# de las etiquetas emocionales. Ningún canal puede escribirlas y que suenen bien.
#
# Nace de que se oyeron en el vídeo (15-09-2026): «"Then... it fell. <gasp> ¡Poof! The kitchen
# disappeared" … lo verbaliza y queda muy mal en el vídeo». El motor hace lo correcto —«Poof» es una
# palabra inglesa y la lee—; lo que estaba mal era esperar que sonara.
#
# **Solo se caza la onomatopeya AISLADA**, la que forma una frase entera («¡Poof!», «Bang!»). Una
# onomatopeya usada como verbo o sustantivo es inglés normal y se lee bien: «the door banged», «a
# loud crash». Cazar la palabra suelta daría falsos positivos en media narración.
ONOMATOPEYAS = frozenset(
    """poof bang boom crash splash whoosh thud bam wham pow zap smash pop clank clang swoosh
    plop splat crack whack ping bonk thump whump screech vroom""".split()
)

CLAVE_LAMINA_MINIATURA = "thumbnail_lamina"
# Los dos límites de la miniatura son del ESTUDIO y no del canal: los mide `lib/miniatura.py` con
# la misma tipografía y el mismo lienzo para cualquier canal. Del canal es el ACABADO de la imagen
# (`perfil.json → imagen.miniatura_clausulas`), no cuántas palabras caben a 168 px.
#
# **Se IMPORTA de `lib/miniatura.py` en vez de repetir el número** (auditoría de F5.6, §6.4): los dos
# tienen que ser el mismo por construcción, porque este verificador existe para cazar en el gate 1 lo
# que esa etapa suspendería **después de la GPU**. Copiado, nada impedía que se separaran, y
# separados el gate barato dejaría pasar lo que el caro tumba.
MAX_PALABRAS_MINIATURA = PALABRAS_MAXIMAS
# El suelo real es la altura de mayúscula a 168 px, que mide el pipeline. Los caracteres son el
# proxy: 27 dan 9,3 px y 34 caen a 7,4 (contrato-miniatura.md). 24 deja margen sin ser un gate.
CARACTERES_COMODOS_MINIATURA = 24

# La clave que cada guardián de color añade para este verificador: qué palabras de un prompt lo
# dispararían. El guardián mide PÍXELES de la lámina ya generada; esto caza la palabra que los
# produce, que es 60 s de GPU antes.
CLAVE_PALABRAS_DEL_GUARDIAN = "palabras_del_prompt"


# Palabras que el modelo de imagen dibuja CON FUEGO, midan lo que midan los guardianes de color.
#
# **Medido el 16-09-2026**: `a small torch` —linterna, en inglés británico— salió como una antorcha
# encendida dentro de un salón, en tres láminas de un episodio infantil, con los niños alrededor. El
# guardián de líneas rojas no lo vio porque mide color, y una llama naranja no destaca en una paleta
# cálida.
#
# **Es del ESTUDIO** porque describe lo que el modelo hace con esas palabras; **lo que decide si
# aplica es el canal**: solo se exige donde el perfil declara líneas rojas de situación. Un canal de
# historia medieval quiere antorchas, y ahí la palabra es correcta.
PALABRAS_QUE_ARDEN = {
    "torch": "en inglés británico es «linterna», pero el modelo dibuja una ANTORCHA ENCENDIDA. "
    "Escribe `flashlight` y descríbela: «a short plastic flashlight with a white beam»",
    "lantern": "sale con llama dentro. Si es de pilas, dilo: «a camping lantern with a white LED light»",
    "candle": "es fuego por definición: si no lo quieres encendido, no lo pongas en la escena",
    "campfire": "fuego abierto",
    "bonfire": "fuego abierto",
    "fireplace": "sale encendida aunque la escena sea de verano",
    "matches": "fuego en manos de alguien",
    "lighter": "fuego en manos de alguien",
}


# Figuras retóricas que el modelo de imagen cobra en OBJETOS, no en parecidos.
#
# **Medido el 16-09-2026**: «a mountain of white foam coming over the top of the bucket» puso una
# montaña nevada al fondo de un jardín, en un episodio sobre bañar al perro. Es el mismo mecanismo
# que hace que `cage` arrastre la jaula de pájaro en el primer canal, entrando por una comparación en vez de
# por un sustantivo.
#
# **Es del ESTUDIO y no de un canal**: es un límite del modelo de imagen, y cambiaría el día que se
# cambie de modelo, no el día que se abra un canal. Avisa, no falla: «a cloud of dust» sobre una
# escena polvorienta puede ser exactamente lo que se quiere, y una lista así nunca está completa.
METAFORAS_QUE_SE_DIBUJAN = (
    "a mountain of",
    "mountains of",
    "a sea of",
    "an ocean of",
    "a river of",
    "a lake of",
    "a wall of",
    "a forest of",
    "a tower of",
    "a carpet of",
    "a blanket of",
    "a storm of",
)


@dataclass
class ContratoDelCanal:
    """Lo que el canal activo declara y este verificador necesita para juzgar un guion.

    **Ningún campo tiene valor por defecto** (F4.9): un defecto aquí sería la decisión de otro canal
    heredada en silencio, que es el defecto que F5.6 vino a arreglar. Lo que el perfil no declara
    queda en `None`, se anota en `carencias` y la regla que dependía de ello **no se evalúa**.
    """

    duracion_objetivo_min: list | None = None
    laminas_estimadas: int | None = None
    palabras_por_segundo: float | None = None
    banda_objetivo: tuple[int, int] | None = None
    banda_dura: tuple[int, int] | None = None
    colores_prohibidos: tuple[str, ...] | None = None
    # ¿Este canal prohíbe el fuego en sus escenas? Lo declara `lineas_rojas.sin_fuego`, y sin
    # declarar significa que no le importa —una respuesta válida, no un olvido—: entonces las
    # palabras que el modelo dibuja con llama solo avisan.
    sin_fuego: bool = False
    adjetivos_prohibidos: tuple[str, ...] | None = None
    lleva_capitulos: bool | None = None
    lleva_fichas: bool | None = None
    # F7.12: el perfil del NICHO del canal y su bloque `cifras`. `None` si el canal no tiene fichas o si
    # su nicho no declara el bloque, y entonces no se comprueba ninguna cifra (así el primer canal sigue igual).
    perfil_del_nicho: dict | None = None
    reglas_de_cifras: dict | None = None
    carencias: list[str] = field(default_factory=list)


def _exige(perfil: dict, ruta: str, ejemplo: str, carencias: list[str], tipo=None, positivo=False, largo=0):
    """Lee un valor del perfil del canal **sin defecto** y anota la carencia si no está (F4.9).

    `ruta` navega el perfil con puntos (`"formato.capitulos"`). El mensaje dice **qué escribir y
    dónde**, como los de `lib/voice_client.py`: un error que solo dice «falta algo» manda a leer
    código, y quien escribe un perfil no debería tener que hacerlo.

    Un valor VACÍO que sea legítimo —la lista negra vacía de un canal que no tiene— pasa: lo que no
    pasa es `null` ni la cadena vacía, que no distinguen la decisión del olvido.

    **`positivo` y `largo` cierran el hueco del valor DEGENERADO** (auditoría de F5.6, §6.2). Un `0`
    no es `None` ni `""`, así que pasaba por aquí; y como las guardas de la derivación preguntan por
    verdad booleana, ese `0` caía por el lado de «no evaluar» y **apagaba la regla sin decir nada**.
    Medido inyectando perfiles: `voz.palabras_por_segundo: 0` dejaba el guion sin banda y **sin gate
    de duración** con 0 carencias, y un `-2` daba bandas negativas `(-102, -261)`. Ninguno de los dos
    perfiles reales lo tiene, pero «un requisito que solo avisa no es un requisito» —lo dice este
    mismo fichero sobre el gate de duración— y uno que **ni siquiera avisa**, menos.

    **Por qué esto no se unifica con `lib/config._del_canal`**, que es la pregunta que se hace solo
    quien pasa por aquí (auditoría §6.3): aquel **devuelve su defecto** y no admite inyectar un
    perfil, y las dos cosas son justo lo que aquí no vale — sin defecto por F4.9, y con perfil
    inyectable para poder probar los dos canales sin montar dos procesos. Es el mismo motivo que
    `lib/lineas_rojas.guardianes_del_canal` escribe en su comentario.
    """
    nodo = perfil
    for parte in ruta.split("."):
        if not isinstance(nodo, dict) or parte not in nodo:
            carencias.append(f"el perfil del canal no declara `{ruta}`: {ejemplo}")
            return None
        nodo = nodo[parte]
    if nodo is None or nodo == "":
        carencias.append(f"el perfil del canal deja `{ruta}` sin valor: {ejemplo}")
        return None
    if tipo is not None and not isinstance(nodo, tipo):
        carencias.append(f"el perfil del canal declara `{ruta}` como {type(nodo).__name__}: {ejemplo}")
        return None
    if positivo and not (isinstance(nodo, int | float) and nodo > 0):
        carencias.append(f"el perfil del canal declara `{ruta}` como {nodo!r}, y tiene que ser > 0: {ejemplo}")
        return None
    if largo and len(nodo) != largo:
        carencias.append(
            f"el perfil del canal declara `{ruta}` con {len(nodo)} elemento(s) y hacen falta {largo}: {ejemplo}"
        )
        return None
    return nodo


def _palabras_de_los_guardianes(perfil: dict | None, carencias: list[str]) -> tuple[str, ...] | None:
    """Las palabras de prompt que dispararían un guardián de color de ESTE canal.

    La lista de guardianes se lee con la guarda que ya existe (`lib/lineas_rojas.py`), que falla
    cerrada si el canal no la declara: una lista **vacía** es una decisión válida —«este canal no
    tiene ninguna línea roja de color»— y entonces aquí no hay ninguna palabra prohibida. Es el caso
    de un canal cuyas líneas rojas son de situación y cuyo perro lleva collar rojo en el banner.
    """
    try:
        guardianes = lineas_rojas.guardianes_del_canal(perfil)
    except lineas_rojas.LineaRojaError as error:
        carencias.append(str(error).splitlines()[0])
        return None
    p = CANAL_PERFIL if perfil is None else perfil
    crudos = (p.get("lineas_rojas") or {}).get("guardianes_de_color") or []
    palabras: list[str] = []
    completo = True
    for guardian, crudo in zip(guardianes, crudos, strict=True):
        declaradas = crudo.get(CLAVE_PALABRAS_DEL_GUARDIAN)
        if not isinstance(declaradas, list):
            completo = False
            carencias.append(
                f"el guardián de color «{guardian.nombre}» no declara `{CLAVE_PALABRAS_DEL_GUARDIAN}`: "
                "son las palabras que un prompt no puede usar porque producen el color que este "
                'guardián detiene, p. ej. ["red", "crimson", "mahogany"]. Sin ellas, el verificador '
                "tendría que adivinar el vocabulario de la paleta de este canal"
            )
            continue
        palabras.extend(str(palabra).strip().lower() for palabra in declaradas if str(palabra).strip())
    return tuple(dict.fromkeys(palabras)) if completo else None


def _lleva_fichas(perfil: dict, carencias: list[str]) -> bool | None:
    """¿Tiene este canal aparato de fuentes verificadas?

    Se DERIVA de lo que el perfil ya declara en vez de pedir una clave nueva: un canal apunta a su
    catálogo con `nicho.fichas_verificadas` y otro escribe por qué no lo tiene en
    `nicho.sin_fuentes_verificadas`. Lo que no vale es el silencio —ni las dos a la vez—, porque
    entonces no se distingue la decisión del olvido.
    """
    nicho = perfil.get("nicho") or {}
    con = bool(nicho.get("fichas_verificadas"))
    sin = bool(nicho.get("sin_fuentes_verificadas"))
    if con == sin:
        carencias.append(
            "el perfil del canal no dice si tiene aparato de fuentes: declara `nicho.fichas_verificadas` "
            "con la ruta de su catálogo, o `nicho.sin_fuentes_verificadas` con el motivo de no tenerlo. "
            "De ahí salen la bibliografía de la descripción y las fórmulas de respaldo que un guion no "
            "puede usar, y ninguna de las dos se deduce del silencio"
        )
        return None
    return con


def _reglas_de_cifras(perfil: dict, lleva_fichas: bool | None, carencias: list[str]) -> tuple[dict | None, dict | None]:
    """(perfil del nicho, bloque `cifras`) del canal, si tiene fichas (F7.12).

    El bloque es del NICHO —capa de estudio, `datos/autoridades/<nicho>.json`— y no del canal: dice qué
    cuenta como cifra respaldada en un dominio. El canal solo dice qué nicho usa (`nicho.id`). Un perfil de
    nicho al que le falte una clave del bloque se dice como carencia, sin rellenarla (F4.9).
    """
    if not lleva_fichas:
        return None, None
    nicho = (perfil.get("nicho") or {}).get("id")
    if not nicho:
        carencias.append(
            "el perfil del canal tiene fichas y no declara `nicho.id`: es el perfil de autoridad con el que se "
            "validan (datos/autoridades/<nicho>.json)"
        )
        return None, None
    try:
        perfil_del_nicho = fuentes_registro.carga_perfil(nicho)
    except FuentesError as error:
        carencias.append(str(error))
        return None, None
    reglas, problemas = fuentes_ficha.reglas_de_cifras(perfil_del_nicho)
    carencias.extend(problemas)
    return perfil_del_nicho, reglas


def contrato_del_canal(perfil: dict | None = None) -> ContratoDelCanal:
    """Junta en un objeto todo lo que este verificador necesita del canal activo.

    Admite un `perfil` inyectado —igual que `lineas_rojas.guardianes_del_canal`— para que las
    pruebas puedan comprobar la derivación de los dos canales sin montar dos procesos.
    """
    p = CANAL_PERFIL if perfil is None else perfil
    contrato = ContratoDelCanal()
    carencias = contrato.carencias

    contrato.duracion_objetivo_min = _exige(
        p,
        "formato.duracion_objetivo_min",
        "es la banda que firmó su gate 0 y no tiene valor por defecto. Escríbela, p. ej. "
        '"duracion_objetivo_min": [15, 25]',
        carencias,
        tipo=list,
        largo=2,
    )
    contrato.laminas_estimadas = _exige(
        p,
        "formato.laminas_por_video_estimadas",
        "cuántas láminas lleva un vídeo de este canal. De ahí sale su ritmo visual y, con la duración, "
        'los segundos de narración por lámina. P. ej. "laminas_por_video_estimadas": 40',
        carencias,
        tipo=int,
        positivo=True,
    )
    contrato.palabras_por_segundo = _exige(
        p,
        "voz.palabras_por_segundo",
        "el ritmo MEDIDO de la narración de este canal, con SU estilo de guion y SU receta de voz "
        "(palabras habladas ÷ segundos de audio de un episodio ya producido). De él salen la duración "
        'estimada y la banda de palabras por lámina. P. ej. "palabras_por_segundo": 2.44',
        carencias,
        tipo=(int, float),
        positivo=True,
    )
    contrato.adjetivos_prohibidos = _exige(
        p,
        "imagen.adjetivos_prohibidos",
        "la lista negra de materialidad de su contrato de prompt: los adjetivos que describen la "
        "SUPERFICIE de un material en vez de su forma y rompen el acabado de este canal. Una lista "
        'vacía es una decisión válida («aquí no hay lista negra»). P. ej. "adjetivos_prohibidos": '
        '["heavy", "worn", "rough"]',
        carencias,
        tipo=list,
    )
    if contrato.adjetivos_prohibidos is not None:
        contrato.adjetivos_prohibidos = tuple(
            str(adjetivo).strip().lower() for adjetivo in contrato.adjetivos_prohibidos if str(adjetivo).strip()
        )

    lleva = _exige(
        p,
        "formato.capitulos",
        "si los vídeos de este canal llevan índice de capítulos. `true` obliga a declarar al menos 3 "
        "y a dejar el marcador <<CAPITULOS>> en la descripción; `false` es una decisión igual de "
        'válida y entonces no se exige ninguno. P. ej. "capitulos": true',
        carencias,
        tipo=bool,
    )
    contrato.lleva_capitulos = None if lleva is None else bool(lleva)
    contrato.lleva_fichas = _lleva_fichas(p, carencias)
    contrato.perfil_del_nicho, contrato.reglas_de_cifras = _reglas_de_cifras(p, contrato.lleva_fichas, carencias)
    contrato.colores_prohibidos = _palabras_de_los_guardianes(perfil, carencias)
    contrato.sin_fuego = bool(((perfil or CANAL_PERFIL).get("lineas_rojas") or {}).get("sin_fuego"))

    ritmo, laminas, duracion = contrato.palabras_por_segundo, contrato.laminas_estimadas, contrato.duracion_objetivo_min
    if ritmo and laminas and duracion:
        # El centro de la banda: los segundos de narración que le tocan a una lámina si el vídeo dura
        # lo que el canal quiere y lleva las láminas que estima. Para el primer canal son los 30 s de siempre
        # (20 min ÷ 40), y multiplicados por 2,44 dan las 63-85 palabras que ya pedía.
        segundos_por_lamina = (sum(duracion[:2]) / 2 * 60) / laminas
        centro = segundos_por_lamina * ritmo
        contrato.banda_objetivo = (round(centro * FRACCION_OBJETIVO[0]), round(centro * FRACCION_OBJETIVO[1]))
        contrato.banda_dura = (round(centro * FRACCION_DURA[0]), round(centro * FRACCION_DURA[1]))
    return contrato


class Resultado:
    def __init__(self, ruta: Path):
        self.ruta = ruta
        self.fallos: list[str] = []
        self.avisos: list[str] = []

    def falla(self, texto: str) -> None:
        self.fallos.append(texto)

    def avisa(self, texto: str) -> None:
        self.avisos.append(texto)


def _palabras(texto: str) -> int:
    """Palabras HABLADAS: las etiquetas emocionales (`<groan>`) son sonido, no palabras, y no cuentan."""
    return len([p for p in re.split(r"\s+", sin_etiquetas(texto).strip()) if p])


def _onomatopeyas_sueltas(narracion: str) -> list[str]:
    """Las onomatopeyas que forman una FRASE ENTERA, que son las que el motor lee en voz alta.

    Se parte por puntuación fuerte y se mira si lo que queda, quitando todo lo que no sea letra, es
    exactamente una onomatopeya. Así «¡Poof!» se caza y «the door banged» no — que es justo la
    diferencia entre una interjección que habría que OÍR y una palabra inglesa que hay que leer.
    """
    sueltas = []
    for trozo in re.split(r"[.!?…¡¿\n]+", sin_etiquetas(narracion)):
        desnudo = re.sub(r"[^a-zA-Z]", "", trozo).lower()
        if desnudo and desnudo in ONOMATOPEYAS:
            sueltas.append(trozo.strip() or desnudo)
    return sueltas


@dataclass
class RespaldoDeCifras:
    """Lo que las fichas de un guion dejan decir (F7.12): sus cifras confirmadas y sus cuentas."""

    # Cada cifra confirmada, una vez por cada forma de decirla: su valor y su `se_dice` (fila 277).
    cifras: list[tuple[str, fuentes_cifras.Cantidad]] = field(default_factory=list)
    # Cada cuenta: su id («ficha/cuenta»), lo que se dice de su resultado, sus datos y lo que no casa.
    # Cada dato: su valor, la cantidad de su cifra (`None` si es de ejemplo) y las formas de decir su cifra.
    cuentas: list[dict] = field(default_factory=list)


def dice_el_dato(dicha: fuentes_cifras.Cantidad, dato: tuple) -> bool:
    """¿Dice `dicha` un dato de una cuenta? Con su valor, o con el redondeo de su cifra («$5.3 billion»)."""
    valor, de_su_cifra, formas = dato
    return fuentes_cifras.dato_casa_con(valor, dicha, de_su_cifra) or any(dicha.casa_con(f) for f in formas)


def respaldo_de_las_fichas(
    ids: list[str], perfil_del_nicho: dict, carpeta: Path, resultado: Resultado
) -> RespaldoDeCifras:
    """Lee las fichas del guion y apunta lo que permiten decir. Una ficha que no está en `cifras_confirmadas`
    —con sus huellas recalculadas hoy, no con lo que declara— es un FALLO: el gate 1 de un nicho con cifras
    no deja pasar un guion cuyas cifras no ha confirmado el usuario (spec §3.6)."""
    respaldo = RespaldoDeCifras()
    reglas, _ = fuentes_ficha.reglas_de_cifras(perfil_del_nicho)
    tope = fuentes_ficha.tope_de_redondeo(reglas)
    for id_ficha in ids:
        ruta = carpeta / f"{id_ficha}.json"
        if not ruta.exists():
            continue  # ya lo dice la comprobación de `fuentes` contra el disco
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            leida = fuentes_ficha.desde_dict(datos)
        except (json.JSONDecodeError, FuentesError) as error:
            resultado.falla(f"la ficha `{id_ficha}` no se puede leer: {error}")
            continue
        for problema in fuentes_ficha.valida(leida, perfil_del_nicho):
            if not problema.startswith("AVISO"):
                resultado.falla(f"la ficha `{id_ficha}` no valida: {problema}")
        nivel = fuentes_ficha.nivel_efectivo(datos)
        if nivel != "cifras_confirmadas":
            resultado.falla(
                f"la ficha `{id_ficha}` está en `{nivel}` y el nicho pide `cifras_confirmadas`: cada cifra con su "
                "frase en su origen (`fuentes.py --comprueba-cifras`) y confirmada por el usuario (`--confirma`)"
            )
        cifras = [c for c in leida.cifras if isinstance(c, dict)]
        formas = {cifra.get("id"): fuentes_cifras.formas_de_decir(cifra, tope) for cifra in cifras}
        for cifra in cifras:
            if fuentes_cifras.confirmacion_vale(cifra):
                respaldo.cifras += [(f"{id_ficha}/{cifra.get('id')}", forma) for forma in formas[cifra.get("id")]]
        for cuenta in leida.cuentas:
            if not isinstance(cuenta, dict):
                continue
            revision = fuentes_cifras.comprueba_cuenta(cuenta, cifras)
            datos = {}
            for nombre, dato in (cuenta.get("datos") or {}).items():
                if not isinstance(dato, dict) or not isinstance(dato.get("valor"), int | float):
                    continue
                de_la_cifra = formas.get(dato.get("cifra"), []) if dato.get("tipo") == "real" else []
                datos[nombre] = (dato["valor"], de_la_cifra[0] if de_la_cifra else None, de_la_cifra)
            respaldo.cuentas.append(
                {
                    "id": f"{id_ficha}/{cuenta.get('id')}",
                    "dicho": fuentes_cifras.una_cantidad(str(cuenta.get("se_dice") or "")),
                    "datos": datos,
                    "problemas": revision.problemas + revision.pendientes,
                }
            )
    return respaldo


def comprueba_cantidades(indice: int, narracion: str, respaldo: RespaldoDeCifras, resultado: Resultado) -> None:
    """Cada cantidad de la narración de una lámina tiene que estar en las fichas del guion (spec §3.8)."""
    dichas = fuentes_cifras.cantidades(sin_etiquetas(narracion))
    sueltas: list[str] = []
    for dicha in dichas:
        if dicha.unidad == fuentes_cifras.ILEGIBLE:
            resultado.falla(
                f"slide {indice}: «{dicha.texto}» lleva moneda, porcentaje o una escala abreviada y no se lee como "
                "cantidad: escríbela como se dirá («$4.1 billion», «seven percent»), que es también como la lee la voz"
            )
            continue
        if any(dicha.casa_con(cantidad) for _, cantidad in respaldo.cifras):
            continue
        # ¿Es el resultado de una cuenta, o uno de sus datos?
        cuenta = next((c for c in respaldo.cuentas if c["dicho"] is not None and dicha.casa_con(c["dicho"])), None)
        con_ese_dato = next(
            (c for c in respaldo.cuentas if any(dice_el_dato(dicha, d) for d in c["datos"].values())),
            None,
        )
        usada = cuenta if cuenta is not None else con_ese_dato
        if usada is not None:
            if usada["problemas"]:
                resultado.falla(
                    f"slide {indice}: «{dicha.texto}» sale de la cuenta `{usada['id']}`, que no casa: "
                    + usada["problemas"][0]
                )
            if cuenta is not None:
                faltan = [
                    nombre
                    for nombre, dato in cuenta["datos"].items()
                    if not any(dice_el_dato(otra, dato) for otra in dichas if otra is not dicha)
                ]
                if faltan:
                    resultado.falla(
                        f"slide {indice}: «{dicha.texto}» es el resultado de la cuenta `{cuenta['id']}` y la lámina no "
                        f"dice sus datos {faltan}: la cuenta se escribe en el guion, en la misma lámina"
                    )
            continue
        if dicha.comprobable:
            resultado.falla(
                f"slide {indice}: «{dicha.texto}» no está en las fichas del guion: no es una cifra confirmada, ni su "
                "redondeo (`se_dice`), ni sale de una cuenta. Cada cantidad de dinero, porcentaje o «million/billion» "
                "se respalda"
            )
        else:
            sueltas.append(dicha.texto)
    if sueltas:
        resultado.avisa(
            f"slide {indice}: números sin unidad que el gate 1 no exige en la ficha (años, recuentos): "
            + ", ".join(f"«{s}»" for s in dict.fromkeys(sueltas))
        )


def verifica(ruta: Path) -> Resultado:
    resultado = Resultado(ruta)
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception as error:  # noqa: BLE001
        resultado.falla(f"no es JSON válido: {error}")
        return resultado

    # Lo que el canal no declara sale como fallo ANTES que nada: un guion no puede dar «0 fallos»
    # mientras su canal esté a medio declarar, porque entonces media comprobación no se ha hecho.
    contrato = contrato_del_canal()
    for carencia in contrato.carencias:
        resultado.falla(carencia)

    for clave in ("title", "description", "tags", "thumbnail_lamina", "thumbnail_text", "slides"):
        if not datos.get(clave):
            resultado.falla(f"falta la clave obligatoria `{clave}`")

    slides = datos.get("slides") or []
    if not slides:
        return resultado

    # `thumbnail_lamina` se comprueba CONTRA las láminas de este guion, no solo que esté: un 99 o un
    # "trece" pasaban el gate 1 y mataban la etapa `thumbnail` después de los 34 min de GPU de las
    # láminas, que es justo el coste que la fila 156 dice evitar (recomendación del auditor, 12-09).
    # **`fuentes` NO es obligatorio en todos los canales** (13-09). Lo es donde haya
    # bibliografía que componer, y eso lo dice la propia descripción: si el guion pide
    # `<<BIBLIOGRAFIA>>`, alguien tiene que decir de qué fichas sale. Un canal de ficción didáctica
    # —que declara `nicho.sin_fuentes_verificadas`— no tiene citas que comprobar, no escribe el
    # marcador y no necesita el campo. Exigirlo siempre lo rompía sin motivo.
    if "<<BIBLIOGRAFIA>>" in (datos.get("description") or "") and not (datos.get("fuentes") or []):
        resultado.falla(
            "la descripción pide `<<BIBLIOGRAFIA>>` y el guion no declara `fuentes`: di de qué fichas "
            "sale, porque no se deduce en el pipeline"
        )

    # Las fichas de la bibliografía se comprueban CONTRA el disco: `stage_upload` las pasa a
    # `fuentes.py --bibliografia`, y un id mal escrito ahí sale como un bloque de citas vacío en la
    # descripción de un vídeo ya montado. Aquí cuesta un renglón.
    from lib.config import CANAL_DATOS_DIR

    for ficha in datos.get("fuentes") or []:
        if not (CANAL_DATOS_DIR / "fuentes" / f"{ficha}.json").exists():
            resultado.falla(
                f"`fuentes` cita la ficha `{ficha}` y no existe en {CANAL_DATOS_DIR / 'fuentes'}: "
                "la bibliografía se genera desde las fichas verificadas del canal"
            )

    # Las cifras, solo donde el nicho las exige (F7.12), como el de ejemplo, `ejemplo-con-cifras`.
    respaldo = None
    if contrato.reglas_de_cifras and contrato.reglas_de_cifras["exige_frase_confirmada"]:
        respaldo = respaldo_de_las_fichas(
            [str(f) for f in datos.get("fuentes") or []],
            contrato.perfil_del_nicho,
            CANAL_DATOS_DIR / "fuentes",
            resultado,
        )

    lamina = datos.get(CLAVE_LAMINA_MINIATURA)
    if lamina is not None:
        try:
            numero = int(lamina)
        except (TypeError, ValueError):
            resultado.falla(f"`{CLAVE_LAMINA_MINIATURA}` vale {lamina!r} y tiene que ser el NÚMERO de una lámina")
        else:
            if not 1 <= numero <= len(slides):
                resultado.falla(
                    f"`{CLAVE_LAMINA_MINIATURA}` pide la lámina {numero} y el guion tiene {len(slides)}: "
                    "la miniatura sale de una lámina de ESTE vídeo"
                )

    # --- láminas -------------------------------------------------------------------------------
    if contrato.laminas_estimadas:
        esperadas = contrato.laminas_estimadas
        minimo = round(esperadas * (1 - TOLERANCIA_LAMINAS))
        maximo = round(esperadas * (1 + TOLERANCIA_LAMINAS))
        if not minimo <= len(slides) <= maximo:
            resultado.falla(
                f"{len(slides)} láminas, fuera de la banda {minimo}-{maximo} "
                f"(±{round(TOLERANCIA_LAMINAS * 100)} % de {esperadas})"
            )

    # --- etiquetas emocionales: solo las que declara la receta del canal (fila 115) -------------
    # Lo que el motor no reconoce **lo PRONUNCIA**: una etiqueta sin declarar acaba en el vídeo
    # como una palabra. La lista es del canal y sin defecto (F4.9); la vacía significa «este canal
    # no escribe etiquetas» y entonces cualquiera es un fallo.
    try:
        permitidas = list(load_recipe()["etiquetas_emocionales"]["permitidas"])
    except VoiceError as error:
        resultado.falla(f"no se pudo leer la receta de voz del canal: {str(error).splitlines()[0]}")
        permitidas = []
    etiquetas_usadas = 0
    narraciones: list[str] = []

    conteos: list[int] = []
    for indice, slide in enumerate(slides, start=1):
        if int(slide.get("slide_number", -1)) != indice:
            resultado.falla(f"slide {indice}: `slide_number` es {slide.get('slide_number')} y debería ser {indice}")
        narracion = slide.get("narration") or ""
        prompt = slide.get("image_prompt") or ""
        if not narracion:
            resultado.falla(f"slide {indice}: sin narración")
        if not prompt:
            resultado.falla(f"slide {indice}: sin `image_prompt`")

        cuenta = _palabras(narracion)
        conteos.append(cuenta)
        narraciones.append(narracion)
        try:
            etiquetas_usadas += len(revisa_etiquetas_emocionales(narracion, permitidas, f"slide {indice}"))
        except VoiceError as error:
            resultado.falla(str(error).splitlines()[0])
        if contrato.banda_dura and contrato.banda_objetivo:
            if not contrato.banda_dura[0] <= cuenta <= contrato.banda_dura[1]:
                resultado.falla(
                    f"slide {indice}: {cuenta} palabras, fuera del límite duro "
                    f"{contrato.banda_dura[0]}-{contrato.banda_dura[1]}"
                )
            elif not contrato.banda_objetivo[0] <= cuenta <= contrato.banda_objetivo[1]:
                resultado.avisa(
                    f"slide {indice}: {cuenta} palabras, fuera de la banda objetivo {contrato.banda_objetivo}"
                )

        bajo = prompt.lower()
        for adjetivo in contrato.adjetivos_prohibidos or ():
            if re.search(rf"\b{re.escape(adjetivo)}\b", bajo):
                resultado.falla(f"slide {indice}: el prompt usa «{adjetivo}», de la lista negra de materialidad")
        for figura in METAFORAS_QUE_SE_DIBUJAN:
            if re.search(rf"\b{figura}\b", bajo):
                resultado.avisa(
                    f"slide {indice}: el prompt dice «{figura}…», y el modelo dibuja la metáfora LITERAL. "
                    "Describe lo que se ve"
                )
        # **Quién decide que el fuego sea un fallo: el CANAL.** El estudio sabe qué palabras
        # dibuja el modelo con llama; si eso es un problema lo dice `lineas_rojas.sin_fuego`.
        # La primera versión de esta guarda fallaba en cuanto el canal declaraba cualquier línea
        # roja, y con eso le prohibía `torch` a un canal de justicia medieval, donde una antorcha
        # en un pasillo es lo que se quiere. Lo cazó un control negativo, no una revisión.
        for palabra, consejo in PALABRAS_QUE_ARDEN.items():
            if not re.search(rf"\b{palabra}\b", bajo):
                continue
            dicho = f"slide {indice}: el prompt dice «{palabra}» y el modelo lo dibuja CON FUEGO. {consejo}"
            if contrato.sin_fuego:
                resultado.falla(dicho + " · este canal declara `lineas_rojas.sin_fuego`")
            else:
                resultado.avisa(dicho)
        for color in contrato.colores_prohibidos or ():
            if re.search(rf"\b{re.escape(color)}\b", bajo):
                resultado.falla(
                    f"slide {indice}: el prompt nombra «{color}», que la guarda de líneas rojas lee como sangre"
                )
        if re.search(r"\bno (blood|injury|wound|body|corpse)\b", bajo):
            resultado.falla(
                f"slide {indice}: el prompt NIEGA un elemento («no blood/injury/…») y la negación no funciona "
                "en difusión: hay que quitar del encuadre la superficie donde el modelo lo pinta"
            )

        if contrato.lleva_fichas:
            for patron in FORMULAS_DE_RESPALDO:
                encaje = re.search(patron, narracion, flags=re.IGNORECASE)
                if encaje:
                    resultado.falla(
                        f"slide {indice}: la narración dice «{encaje.group(0)}» y las fichas están en "
                        "`solo_citas_verificadas` (nadie ha leído las obras)"
                    )
        if respaldo is not None:
            comprueba_cantidades(indice, narracion, respaldo, resultado)

        for suelta in _onomatopeyas_sueltas(narracion):
            resultado.falla(
                f"slide {indice}: «{suelta}» es una onomatopeya SOLA, y el motor de voz la lee como "
                "palabra en vez de sonar (se oyó así el 15-09). Cuéntalo con la acción: en vez "
                "de «¡Poof! The kitchen disappeared», «The bag burst, and the kitchen disappeared». "
                "Usada como verbo o sustantivo no pasa nada: «the door banged» se lee bien"
            )

        if NARRATION_LANG != IDIOMA_DEL_ESTUDIO:
            for patron in DELATORES_ES:
                if re.search(patron, narracion, flags=re.IGNORECASE):
                    resultado.avisa(f"slide {indice}: posible castellano en la narración ({patron})")
                    break

    # --- ¿está escrito para el motor que entona? -------------------------------------------------
    # **Orpheus lee plano lo que está escrito plano.** El episodio 1 (08-09) era Orpheus en los 33
    # audios y se oyó como Kokoro: 0 etiquetas, 0 puntos suspensivos y 160 frases con
    # puntuación de escuela. Su regla del 07-09: «no uses mayúsculas automáticas ni puntuación
    # perfecta de escuela… separando las ideas con comas o puntos suspensivos», y las etiquetas.
    # El criterio es laxo a propósito —cero de las DOS cosas— para no dar falsos positivos: caza el
    # guion que ignoró el brief entero, no el que dosifica. Solo aplica al motor que entona.
    puntos_suspensivos = sum(n.count("...") + n.count("…") for n in narraciones)
    if MOTOR_DE_VOZ == "orpheus" and narraciones and etiquetas_usadas == 0 and puntos_suspensivos == 0:
        resultado.falla(
            "guion con puntuación de escuela para un motor que entona por la escritura: 0 etiquetas "
            f"emocionales y 0 puntos suspensivos en {len(narraciones)} láminas. Orpheus lo leerá plano "
            "(episodio 1, 08-09). Cómo se escribe: .claude/skills/produce-semana/references/"
            "encargo-guionista.md → «Cómo se escribe para Orpheus»"
        )

    total = sum(conteos)

    # **La banda de duración y el ritmo son del CANAL y no se rellenan** (F4.9): aquí hubo un
    # `or [15, 25]` —la decisión de gate 0 del primer canal heredada por cualquier canal nuevo— y, hasta
    # F5.6, un `PALABRAS_POR_SEGUNDO = 2.44` que era su ritmo con SU estilo de guion. El segundo
    # narra a 1,80 con la narración A2 elegida el 14-09: estimar su duración con el ritmo
    # del primero la daba un 36 % más corta de lo que dura.
    ritmo = contrato.palabras_por_segundo
    rango = contrato.duracion_objetivo_min
    segundos = total / ritmo if ritmo else 0.0
    if ritmo and rango:
        if not (rango[0] * 60) <= segundos <= (rango[1] * 60):
            # **Es FALLO y no aviso desde el 08-09, por instrucción del usuario** («para el resto de vídeos
            # lo tenemos que tener en cuenta para que cumpla el requisito de long-video»). Era un aviso,
            # y el checklist de entrega solo exige «0 fallos»: el episodio 1 salió a 13:54 con el aviso
            # delante y nadie se paró. Un requisito que solo avisa no es un requisito.
            objetivo = int(rango[0] * 60 * ritmo)
            falta = objetivo - total
            resultado.falla(
                f"duración estimada {segundos / 60:.1f} min, fuera del objetivo {rango[0]}-{rango[1]} min "
                f"({total} palabras a {ritmo} palabras/s). Para el suelo de {rango[0]} min "
                f"hacen falta {objetivo} palabras"
                + (f", o sea {falta} más ({falta / max(len(slides), 1):.0f} por lámina)" if falta > 0 else "")
            )
    else:
        segundos = 0.0

    # --- miniatura -----------------------------------------------------------------------------
    texto_miniatura = (datos.get("thumbnail_text") or "").strip()
    if texto_miniatura:
        cuenta_miniatura = _palabras(texto_miniatura)
        if cuenta_miniatura > MAX_PALABRAS_MINIATURA:
            resultado.falla(
                f"`thumbnail_text` tiene {cuenta_miniatura} palabras y el contrato permite {MAX_PALABRAS_MINIATURA}"
            )
        if len(texto_miniatura) > CARACTERES_COMODOS_MINIATURA:
            resultado.avisa(
                f"`thumbnail_text` mide {len(texto_miniatura)} caracteres: por encima de "
                f"{CARACTERES_COMODOS_MINIATURA} el pipeline puede suspender el run por altura de mayúscula"
            )
        if texto_miniatura.lower() in (datos.get("title") or "").lower():
            resultado.falla("`thumbnail_text` repite parte del título, que ya sale al lado de la miniatura")

    # --- descripción y capítulos ---------------------------------------------------------------
    #
    # **Los dos marcadores dependen de lo que el canal LLEVE** (F5.6): `<<CAPITULOS>>` solo si tiene
    # índice de capítulos y `<<BIBLIOGRAFIA>>` solo si tiene fichas que citar. Exigirlos siempre
    # obligaba a un canal de ficción didáctica a escribir un bloque de citas vacío, y a uno sin
    # capítulos un índice de uno solo.
    descripcion = datos.get("description") or ""
    marcadores = []
    if contrato.lleva_capitulos:
        marcadores.append("<<CAPITULOS>>")
    if contrato.lleva_fichas:
        marcadores.append("<<BIBLIOGRAFIA>>")
    for marcador in marcadores:
        if marcador not in descripcion:
            resultado.falla(f"la descripción no trae el marcador {marcador}")

    capitulos = datos.get("capitulos") or []
    if contrato.lleva_capitulos:
        if len(capitulos) < 3:
            resultado.falla(f"{len(capitulos)} capítulos: YouTube necesita al menos 3 y el gate 0 los exige")
        else:
            if int(capitulos[0].get("slide_inicial", 0)) != 1:
                resultado.falla("el primer capítulo no arranca en el slide 1")
            anteriores = [int(c.get("slide_inicial", 0)) for c in capitulos]
            if anteriores != sorted(anteriores) or len(set(anteriores)) != len(anteriores):
                resultado.falla("los capítulos no van en orden creciente de slide, o repiten slide")
            if anteriores[-1] > len(slides):
                resultado.falla(f"un capítulo arranca en el slide {anteriores[-1]} y solo hay {len(slides)}")
    elif capitulos and contrato.lleva_capitulos is False:
        resultado.falla(
            f"el guion trae {len(capitulos)} capítulos y el perfil declara `formato.capitulos: false`: "
            "o los quita el guion, o el canal cambia su decisión y la escribe"
        )

    # --- bienvenida y despedida, que son del ESTUDIO ----------------------------------------------
    #
    # El 09-09: «ahora el vídeo queda muy seco», y el 13-09 se subió a regla de todos los canales.
    # Estaba escrita desde entonces **solo en el brief del guionista**, así que un guion sin despedida
    # pasaba por aquí en verde: exactamente el patrón que este proyecto llama su defecto dominante,
    # «está protegido donde lo que protege es prosa».
    #
    # Se comprueba lo que se puede medir sin falsos positivos. La despedida es una LÁMINA, así que se
    # busca por su marca. La bienvenida va dentro de la narración de la primera, con los marcadores ya
    # rellenados, así que no se compara la plantilla entera: solo su trozo literal más largo, que es lo
    # único que el guionista no puede haber cambiado legítimamente.
    formato = (CANAL_PERFIL or {}).get("formato") or {}
    if formato.get("despedida") and not any(s.get("tipo") == "cierre" for s in slides):
        resultado.falla(
            'sin lámina de despedida: la última tiene que llevar `"tipo": "cierre"` con el texto de '
            "`perfil.json → formato.despedida`. Todos los vídeos la llevan (09-09)"
        )
    plantilla = formato.get("bienvenida") or ""
    if plantilla and slides:
        # Se compara el TEXTO, no la puntuación: el guion mete `¡` y `¿` a propósito para que Orpheus
        # entone (10-09), y los subtítulos ya los quitan antes de pintar. Sin esta normalización
        # la comprobación daba un falso positivo en el episodio 3, que escribe «¡the museum…».
        def _desnudo(texto: str) -> str:
            return re.sub(r"\s+", " ", re.sub(r"[¡¿!?.,;:—–\-]", "", texto)).strip().lower()

        literal = max(re.split(r"\{[a-z_]+\}", plantilla), key=len).strip()
        if literal and _desnudo(literal) not in _desnudo(slides[0].get("narration") or ""):
            resultado.falla(
                "la lámina 1 no abre con la bienvenida del canal: su narración tiene que empezar por el "
                f"texto de `perfil.json → formato.bienvenida` («{literal[:48]}…»)"
            )

    resultado.estadistica = {
        "laminas": len(slides),
        "palabras": total,
        "minimo": min(conteos),
        "mediana": sorted(conteos)[len(conteos) // 2],
        "maximo": max(conteos),
        "minutos": round(segundos / 60, 1),
    }
    return resultado


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifica un slides.json contra el contrato del canal")
    parser.add_argument("rutas", nargs="+", type=Path)
    parser.add_argument(
        "--canal",
        type=str,
        default="",
        help=(
            "id del canal contra cuyo perfil se mide. Por defecto se deduce de la ruta del guion "
            "(vive dentro de canales/<id>/) y, si tampoco sale de ahí, del .env"
        ),
    )
    args = parser.parse_args()

    # Se dice SIEMPRE con qué perfil se está midiendo. Sin esta línea, medir el guion de un canal
    # con el perfil de otro se ve exactamente igual que un guion malo: 24 fallos y ninguna pista.
    print(f"Midiendo contra el perfil de: {CANAL_ACTIVO}")

    total_fallos = 0
    for ruta in args.rutas:
        resultado = verifica(ruta)
        estadistica = getattr(resultado, "estadistica", None)
        print(f"\n=== {ruta.name} ===")
        if estadistica:
            print(
                f"  {estadistica['laminas']} láminas · {estadistica['palabras']} palabras · "
                f"~{estadistica['minutos']} min · palabras/lámina min {estadistica['minimo']}, "
                f"mediana {estadistica['mediana']}, máx {estadistica['maximo']}"
            )
        for fallo in resultado.fallos:
            print(f"  [FALLO] {fallo}")
        for aviso in resultado.avisos:
            print(f"  [aviso] {aviso}")
        if not resultado.fallos:
            print(f"  [OK] sin fallos mecánicos ({len(resultado.avisos)} aviso(s))")
        total_fallos += len(resultado.fallos)

    print(f"\nTotal de fallos: {total_fallos}")
    print("Recuerda: esto NO es el gate 1. El criterio (prompt↔narración, líneas rojas, desmentido")
    print("en los primeros 30 s, mitos contados como mitos) se lee, y lo firma el usuario.")
    return 1 if total_fallos else 0


if __name__ == "__main__":
    sys.exit(main())
