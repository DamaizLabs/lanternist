r"""Genera el clip de referencia con el que el motor de clonado imita la voz del CANAL ACTIVO.

Correr:  .venv\Scripts\python scripts/referencia_voz.py
         .venv\Scripts\python scripts/referencia_voz.py --ruta   # dónde va el clip y qué variable lo lee, en JSON

## Qué es esto y de dónde viene

**El flujo del estudio, en una línea** (07-09): se elige una voz **inglesa de Kokoro**, se
genera con ella una **muestra suficientemente grande**, y **el motor de clonado la imita** para darle el
punto emocional que Kokoro no da. Vale para todos los canales; lo único que cambia por canal son la
voz, la velocidad, el idioma y el texto.

La decisión (07-09): «en el segundo canal utilizamos el pipeline de crear una voz en Kokoro y luego clonarla en
el motor de clonado. El objetivo es darle temperatura y emoción al narrador, cosa que Kokoro no hace y
el clonado sí, por lo tanto se tendría que hacer esto en todos los canales **a nivel de estudio y
no de canales**». Y sobre el tamaño: «una vez tengamos una muestra suficientemente grande la
clonamos en Chatterbox». **El motor de clonado es Orpheus desde el 07-09** —Chatterbox se
borró del proyecto—, y eso no cambia nada de este script: la referencia se genera igual.

Este archivo **sustituye a `scripts/referencia_emma.py`**, que hacía lo mismo para un solo canal:
llevaba dentro la voz `bf_emma`, la velocidad `0.75`, el `lang_code` `b` y un texto de un cuento
infantil — las cuatro cosas son **decisiones de un canal**, escritas en un script de
la capa de estudio. Es la misma fuga de capa que cerró F4.9, así que el mecanismo se queda aquí y
los datos se van a la receta de voz de cada canal.

## Por qué el clip es SINTÉTICO, y qué parte de la decisión 13 lo exige

**La decisión cerrada 13 se REFORMULÓ el 07-09** (addendum fila 108) y este script es su mecanismo:
Kokoro deja de ser el motor de voz y pasa a ser la **fuente de la referencia** que se clona.
Lo que sigue explica la parte de aquella regla que la reformulación conserva intacta.

El clonado parte de un clip de audio. Ese clip **no es la grabación de una persona**: lo dice Kokoro
con la voz que el canal ya eligió, así que no hay ninguna persona por medio. **Una voz clonada de una
grabación real se queda en el idioma de esa grabación**, y su causa está escrita: si la grabación no
contiene una sola palabra en inglés, el clonado interpolaría fonemas que nunca oyó. Con una referencia nativa y
sintética esa causa no aplica — que es por lo que la reformulación pudo cambiar el motor sin tocar el motivo.

## Por qué se REGENERA en vez de guardarse en git

Porque el clip se reproduce a voluntad y el repositorio no lleva binarios de audio (`*.wav` está en
`.gitignore` por partida doble, lista negra). El clip vive en la caché de voz de `C:`
(`RUTA_CACHE_VOZ`), que es donde ya viven los recortes de referencia, con el **id del canal en el
nombre** para que dos canales no se pisen el clip.

**«Reproducible» no es «byte a byte», y eso está medido — la frase que había aquí era falsa.** El
script viejo y las dos recetas afirman que «Kokoro es determinista: el mismo texto, la misma voz y
la misma velocidad dan el mismo audio». Se comprobó al hacer este refactor, y no: dos pasadas
seguidas de `scripts/referencia_emma.py` dan **sha256 distintos** (`66b64235…` y `cbd67a29…`), y
también en CPU (`4c8b9601…` y `a32094b1…`), así que no es la GPU. Lo que **sí** es determinista es
todo lo que se puede oír: las dos pasadas dan **exactamente 673.200 muestras** (28,05 s), el mismo
pico y el mismo RMS, con una diferencia entre ellas de **0,008181 RMS (−41,7 dBFS)** y correlación
**0,990934**. Ese es el suelo de ruido del motor, y es contra ese suelo —no contra un hash— contra
el que se comprueba que un cambio en el mecanismo no cambia la voz.

## Lo que el canal declara, y qué pasa si no lo declara

En su receta de voz (`canales/<id>/datos/<voz.receta>.json`), bloque `referencia_a_generar`:

    "referencia_a_generar": {
      "componentes": ["bf_emma"], "speed": 0.75, "lang_code": "b", "sample_rate_hz": 24000,
      "texto": "…30 s con declarativas, una pregunta y algún énfasis…",
      "_por_que": "…"
    }

**Sin defectos**: si falta el bloque o uno de sus campos, esto **se para y dice exactamente qué
escribir**. Un defecto aquí sería la decisión de otro canal heredada en silencio, que es la regla
dura del 03-09 (F4.9). `componentes` admite varias voces: Kokoro las promedia, que es
cómo se construyen las mezclas como `mix_onyx_lewis`.

**El texto no es relleno.** De él sale el registro que el clon va a imitar, así que lleva a
propósito frases del propio nicho con declarativas, una pregunta y algún énfasis: sin una pregunta
en la referencia, el clon no tiene de dónde sacar la entonación de una pregunta.

**Cuánto tiene que durar NO lo decide el canal**: es el mínimo del mecanismo, y lo comprueba
`SEGUNDOS_MINIMOS` sobre el clip ya generado. Un texto corto no da un clon malo de forma visible —
da un clon inestable, y eso solo se descubre escuchando el vídeo montado.

## Cruce de venvs, que es por lo que este archivo se ejecuta dos veces

Kokoro vive en `.venv-voz` (torch 2.6.0+cu126, `setuptools<81`), y `lib/config.py` necesita
`python-dotenv`, que **no está** en ese venv. Así que la primera pasada corre en el `.venv` del
pipeline —resuelve el canal, la receta y la ruta—, escribe el trabajo en JSON y se relanza a sí
misma con `.venv-voz\Scripts\python.exe --sintetiza`, que es la única que importa el motor. Es el
mismo patrón de `lib/voice_client.py` → `lib/voice_worker.py`.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# El repositorio del modelo es del MECANISMO, no del canal: la referencia se genera con Kokoro
# porque es lo único determinista y nativo que hay en esta máquina, y eso vale igual para cualquier
# canal. Lo que cambia por canal es la voz, la velocidad, el idioma y el texto.
REPO_KOKORO = "hexgrad/Kokoro-82M"
BLOQUE = "referencia_a_generar"

# **«Una muestra suficientemente grande» es del ESTUDIO** (07-09), así que el número vive
# aquí y no en la receta de ningún canal: no es una decisión de identidad, es lo que el mecanismo
# necesita para que el clon salga estable.
#
# **De dónde sale el 25, con los dos datos que había.** (1) Lo que el consumidor consume de verdad:
# la receta del segundo canal recorta su clip activo con `offset 2,0 s + duración 20,0 s`, o sea **22,0 s** de
# la fuente — por debajo de eso el recorte sale corto o mudo y nadie se entera. (2) Lo que buscaba
# el generador: `scripts/referencia_emma.py` pedía «30 s largos, que es lo que pide un clon estable»
# y el clip aprobado mide **28,05 s** (`soundfile.info` de `emma-fuente.wav`). 25,0 s deja
# 3 s de margen sobre lo que el recorte consume y queda por debajo del clip ya aprobado, así que
# **no invalida nada de lo que ya está decidido**.
SEGUNDOS_MINIMOS = 25.0

# Campo -> (comprobación, ejemplo). El ejemplo se imprime cuando falta, para que el mensaje diga
# qué escribir en vez de dejar a quien lo lea buscando la forma en otro canal.
CAMPOS = {
    "componentes": (
        lambda v: isinstance(v, list) and v and all(isinstance(x, str) and x.strip() for x in v),
        '["am_onyx", "bm_lewis"]',
    ),
    "speed": (lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0, "0.72"),
    "lang_code": (lambda v: isinstance(v, str) and v.strip(), '"b"'),
    "sample_rate_hz": (lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0, "24000"),
    # **Ni una marca entre ángulos, y aquí la regla es más dura que en el guion.** Este es el
    # SEGUNDO camino del proyecto que sintetiza voz, y no pasa por la guarda de
    # `voice_client.revisa_etiquetas_emocionales()` porque lee la receta con `json.loads` y llama a
    # Kokoro en su propio subproceso (lo encontró la auditoría del 08-09). Una `<etiqueta>` aquí se
    # pronunciaría dentro del clip de referencia —Kokoro no las convierte en sonido—, y ese clip es
    # justo lo que Orpheus clona: con la fila 112 encima (el motor «continúa la referencia») la
    # palabra intrusa podría reaparecer en la narración del vídeo. En el guion las etiquetas
    # declaradas son legítimas; en la referencia **no tienen ningún uso legítimo**, así que se
    # prohíben del todo en vez de compararlas contra una lista.
    "texto": (
        lambda v: isinstance(v, str) and len(v.split()) >= 20 and "<" not in v and ">" not in v,
        '"…unos 30 s de narración del propio nicho, sin marcas entre ángulos…"',
    ),
}


class ReferenciaError(RuntimeError):
    """El canal no declara lo suyo, o el entorno no permite generar. No se suple con un defecto."""


def _bloque_de_la_receta(receta_path: Path, canal: str) -> dict:
    """Lee y valida `referencia_a_generar` de la receta del canal. Falla cerrada (F4.9)."""
    if not receta_path.exists():
        raise ReferenciaError(
            f"No existe la receta de voz del canal {canal}: {receta_path}. La nombra su perfil en `voz.receta`."
        )
    receta = json.loads(receta_path.read_text(encoding="utf-8"))
    bloque = receta.get(BLOQUE)
    if not isinstance(bloque, dict):
        ejemplo = ",\n    ".join(f'"{k}": {v[1]}' for k, v in CAMPOS.items())
        raise ReferenciaError(
            f"{receta_path.name} no declara `{BLOQUE}`, que es la decisión de ESTE canal sobre con "
            f"qué voz se genera su clip de referencia. El motor no la rellena: un valor por defecto aquí "
            f"sería la decisión de otro canal heredada en silencio.\n"
            f'Escribe en la raíz de la receta:\n\n  "{BLOQUE}": {{\n    {ejemplo},\n'
            '    "_por_que": "el motivo de estos valores, que es lo que se lee dentro de un mes"\n  }\n\n'
            "`lang_code` es el de Kokoro —a = inglés americano, b = británico, e = español— y manda "
            "sobre el prefijo de las voces."
        )
    faltan = [
        f"`{campo}` (por ejemplo: {ejemplo})"
        for campo, (valido, ejemplo) in CAMPOS.items()
        if campo not in bloque or not valido(bloque[campo])
    ]
    if faltan:
        raise ReferenciaError(
            f"`{BLOQUE}` de {receta_path.name} no declara, o declara con un valor inservible: "
            + " · ".join(faltan)
            + ". Ninguno tiene valor por defecto."
        )
    return bloque


def _minimo_de_segundos(receta_path: Path) -> tuple[float, str]:
    """Cuántos segundos exige el mecanismo, y por qué. Nunca menos de `SEGUNDOS_MINIMOS`.

    El mínimo del estudio puede quedarse corto para un canal concreto, y eso es aritmética, no
    opinión: si su receta recorta el clip con un desplazamiento, la fuente tiene que llegar hasta el
    final del recorte. Así que se exige el mayor de los dos.
    """
    receta = json.loads(receta_path.read_text(encoding="utf-8"))
    spec = receta.get("referencia_de_voz") or {}
    activa = spec.get(spec.get("opcion_activa") or "")
    if isinstance(activa, dict):
        consume = float(activa.get("offset_segundos") or 0) + float(activa.get("duracion_segundos") or 0)
        if consume > SEGUNDOS_MINIMOS:
            return consume, (
                f"su receta recorta `{spec.get('opcion_activa')}` con offset "
                f"{activa.get('offset_segundos')} s + duración {activa.get('duracion_segundos')} s, "
                "y la fuente tiene que llegar hasta el final del recorte"
            )
    return SEGUNDOS_MINIMOS, "mínimo del estudio para que el clon salga estable"


def _variable_de_entorno(receta_path: Path) -> str | None:
    """Qué variable del `.env` consume el clip, según la propia receta.

    Se lee de `referencia_de_voz.variable_entorno` en vez de duplicarla en el bloque nuevo: quien
    consume el clip ya la declara, y dos sitios con el mismo nombre acaban divergiendo. Un canal
    que todavía no clona no la tiene, y entonces esto devuelve `None` y el mensaje lo dice.
    """
    receta = json.loads(receta_path.read_text(encoding="utf-8"))
    declarada = (receta.get("referencia_de_voz") or {}).get("variable_entorno")
    # Una sola variable, la misma regla que `lib/voice_client.resolve_recording` (fila 227): una lista ya no vale
    # y aquí no se reinterpreta.
    if isinstance(declarada, str) and declarada.strip():
        return declarada.strip()
    return None


def _destino(cache_de_voz: Path, canal: str) -> Path:
    """Dónde vive el clip del canal: en la caché de voz, con el id del canal en el nombre."""
    return (Path(cache_de_voz) / f"referencia-{canal}.wav").resolve()


def _ruta() -> int:
    """Sin generar nada: el canal activo, la variable del `.env` que lee su clip y dónde va. Lo usa `instala.py`."""
    from lib.config import CANAL_ACTIVO, CANAL_ERROR, VOICE_CACHE_DIR, VOICE_RECIPE_PATH

    if CANAL_ERROR:
        raise ReferenciaError(f"El canal activo no está usable: {CANAL_ERROR}")
    variable = _variable_de_entorno(VOICE_RECIPE_PATH) if VOICE_RECIPE_PATH.exists() else None
    datos = {"canal": CANAL_ACTIVO, "variable": variable, "destino": str(_destino(VOICE_CACHE_DIR, CANAL_ACTIVO))}
    print(json.dumps(datos))
    return 0


def _prepara() -> int:
    """Primera pasada, en el `.venv` del pipeline: resuelve el canal y lanza la síntesis."""
    # El import va aquí y no arriba a propósito: la segunda pasada corre en `.venv-voz`, donde
    # `python-dotenv` no está instalado y `lib.config` no se puede importar.
    from lib.config import BASE_DIR, CANAL_ACTIVO, CANAL_ERROR, VOICE_CACHE_DIR, VOICE_PYTHON, VOICE_RECIPE_PATH

    if CANAL_ERROR:
        raise ReferenciaError(f"El canal activo no está usable: {CANAL_ERROR}")
    bloque = _bloque_de_la_receta(VOICE_RECIPE_PATH, CANAL_ACTIVO)

    destino = _destino(VOICE_CACHE_DIR, CANAL_ACTIVO)
    # Cinturón y tirantes sobre la lista negra: ningún audio de voz cae dentro del árbol del repo,
    # aunque `RUTA_CACHE_VOZ` apunte mal. `*.wav` está en `.gitignore`, pero un fichero ignorado
    # dentro del repo sigue siendo un fichero dentro del repo.
    if destino.is_relative_to(Path(BASE_DIR).resolve()):
        raise ReferenciaError(
            f"RUTA_CACHE_VOZ apunta dentro del repositorio ({destino}). El audio de voz vive fuera, "
            "en la caché de C: (lista negra)."
        )

    interprete = Path(VOICE_PYTHON)
    if not interprete.exists():
        raise ReferenciaError(
            f"No existe el intérprete del venv de voz: {interprete}. Se crea con "
            "`py -3.12 -m venv .venv-voz` + `spikes/requirements-voz.txt`."
        )

    trabajos = VOICE_CACHE_DIR / "trabajos"
    trabajos.mkdir(parents=True, exist_ok=True)
    trabajo = trabajos / f"referencia-{CANAL_ACTIVO}.json"
    resultado = trabajos / f"referencia-{CANAL_ACTIVO}-resultado.json"
    # **Se genera a un lado y se pone en su sitio al final.** El mínimo de duración se comprueba
    # DESPUÉS de generar —es lo único que se puede medir—, y escribir directo sobre el destino
    # significaría haber destruido un clip bueno para descubrir después que el nuevo no vale.
    parcial = destino.with_name(destino.stem + "-parcial.wav")
    trabajo.write_text(
        json.dumps({**bloque, "repo_id": REPO_KOKORO, "destino": str(parcial)}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Canal {CANAL_ACTIVO} · receta {VOICE_RECIPE_PATH.name}")
    print(f"  voz {'+'.join(bloque['componentes'])} · speed {bloque['speed']} · lang_code {bloque['lang_code']}")
    proceso = subprocess.run(
        [str(interprete), str(Path(__file__).resolve()), "--sintetiza", str(trabajo), "--resultado", str(resultado)]
    )
    if proceso.returncode != 0 or not resultado.exists():
        parcial.unlink(missing_ok=True)
        raise ReferenciaError(
            f"La síntesis de la referencia falló (código {proceso.returncode}). No se reintenta: un "
            "fallo del runtime local es un dato, no algo que se disimule repitiendo la llamada."
        )

    medido = json.loads(resultado.read_text(encoding="utf-8"))
    minimo, motivo = _minimo_de_segundos(VOICE_RECIPE_PATH)
    if medido["segundos"] < minimo:
        parcial.unlink(missing_ok=True)
        raise ReferenciaError(
            f"El clip de {CANAL_ACTIVO} mide {medido['segundos']} s y hacen falta {minimo:g} s "
            f"({motivo}). El motor de clonado parte de este audio: con una muestra corta el clon sale "
            "inestable, y eso no se ve en ningún error — se oye en el vídeo ya montado. Alarga "
            f"`{BLOQUE}.texto` en {VOICE_RECIPE_PATH.name}; hoy tiene {medido['palabras']} palabras "
            f"y da {medido['wpm']} wpm, así que faltan del orden de "
            f"{round((minimo - medido['segundos']) * medido['wpm'] / 60)} palabras. El clip no se ha "
            "guardado: el que hubiera antes sigue intacto."
        )
    # **Si ya había un clip, se dice que se ha sustituido.** No es cosmético: Kokoro no repite el
    # mismo audio byte a byte (ver el docstring), así que volver a correr esto mueve un poco la
    # referencia y con ella la prosodia del clon. Es la misma voz, pero un canal en producción tiene
    # derecho a saber que su referencia ha cambiado en vez de enterarse por el oído.
    sustituye = destino.exists()
    parcial.replace(destino)
    if sustituye:
        print("  Aviso: había un clip y se ha sustituido. Kokoro no repite el audio byte a byte, así")
        print("  que la referencia se mueve un poco y con ella la prosodia del clon (misma voz).")
    print(f"\n{destino}")
    print(
        f"  {medido['segundos']} s · {medido['palabras']} palabras · {medido['wpm']} wpm de audio "
        f"(mínimo del mecanismo: {minimo:g} s)"
    )
    variable = _variable_de_entorno(VOICE_RECIPE_PATH)
    if variable:
        print(f"  apunta {variable} del .env a esta ruta")
    else:
        print(
            f"  la receta de {CANAL_ACTIVO} no declara UNA variable en `referencia_de_voz.variable_entorno`: "
            "o su motor activo todavía no clona, o la clave trae otra cosa que el nombre de una variable. Esa "
            "clave dice qué variable del .env lee este clip."
        )
    return 0


def _sintetiza(trabajo: Path, resultado: Path) -> int:
    """Segunda pasada, en `.venv-voz`: el único sitio donde se importa el motor de voz.

    No lee el `.env`, ni la receta, ni `lib.config`: todo llega en el trabajo. Es el mismo
    contrato deliberadamente tonto de `lib/voice_worker.py` — aquí no se decide nada.
    """
    import os

    # La caché de Hugging Face ya está poblada (vive en C:). Sin esto, un peso ausente saldría a
    # la red en silencio, y la decisión cerrada 6 dice que nada sale de este PC salvo la subida.
    os.environ["HF_HUB_OFFLINE"] = "1"

    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    job = json.loads(trabajo.read_text(encoding="utf-8"))
    destino = Path(job["destino"])
    # Una sola cadena con las voces separadas por coma: `load_voice` promedia los componentes, que
    # es exactamente la mezcla aprobada en el spike F2.15.
    voz = ",".join(job["componentes"])
    sr = int(job["sample_rate_hz"])

    destino.parent.mkdir(parents=True, exist_ok=True)
    pipe = KPipeline(lang_code=job["lang_code"], repo_id=job["repo_id"])
    trozos = [np.asarray(a, dtype=np.float32) for _, _, a in pipe(job["texto"], voice=voz, speed=job["speed"])]
    if not trozos:
        raise ReferenciaError("Kokoro no produjo audio para el texto de referencia")
    audio = np.concatenate(trozos)
    sf.write(destino, audio, sr)

    segundos = len(audio) / sr
    palabras = len(job["texto"].split())
    resultado.parent.mkdir(parents=True, exist_ok=True)
    resultado.write_text(
        json.dumps(
            {
                "destino": str(destino),
                "segundos": round(segundos, 2),
                "palabras": palabras,
                # El ritmo medido del clip. Es el dato con el que se elige el `speed` de la
                # referencia, que no es el de producción: de la referencia sale el CARÁCTER y del
                # `speed` de la receta, el ritmo del vídeo.
                "wpm": round(palabras / segundos * 60, 1) if segundos else None,
                "voz": voz,
                "speed": job["speed"],
                "lang_code": job["lang_code"],
                "sample_rate_hz": sr,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"  {destino.name}: {segundos:.2f} s a {sr} Hz")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Clip de referencia de voz del canal activo")
    parser.add_argument("--sintetiza", help="INTERNO: trabajo JSON, se ejecuta en .venv-voz")
    parser.add_argument("--resultado", help="INTERNO: dónde escribir lo medido")
    parser.add_argument("--ruta", action="store_true", help="solo dice dónde va el clip y qué variable lo lee (JSON)")
    args = parser.parse_args()
    try:
        if args.ruta:
            return _ruta()
        if args.sintetiza:
            if not args.resultado:
                raise ReferenciaError("--sintetiza necesita --resultado (los pone la primera pasada)")
            return _sintetiza(Path(args.sintetiza), Path(args.resultado))
        return _prepara()
    except ReferenciaError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
