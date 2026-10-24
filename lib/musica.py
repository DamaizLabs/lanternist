"""Lecho musical del vídeo: generación local con ACE-Step y mezcla con la narración.

**De dónde salen los números de este módulo.** No de criterio propio: de medir el vídeo de
referencia de producción (`progress/analisis_referencia_produccion.md`). El primer intento fue un
lecho de osciladores sintetizado con FFmpeg y se rechazó —«no se escucha nada de fondo»—. La
medición le dio la razón y explicó por qué:

    referencia   graves 80-250 Hz  -15,2 dB   ·  voz 250-3400 Hz  -17,3 dB  ->  graves +2,1 dB
    nuestro      graves            -30,8 dB   ·  voz             -28,6 dB   ->  graves -2,2 dB

Su música **no está por debajo de la voz en energía**: está en otra banda. Lo que evita el solape no
es el volumen bajo, es la separación de frecuencias más un ducking que aparta la música cuando hay
habla. Nuestro vídeo además entregaba a -26,22 LUFS frente a sus -8,91: sonaba susurrado.

**Por qué se genera y no se descarga.** Se propuso música Creative Commons de biblioteca. CC **no
protege de Content ID** —muchas pistas CC están registradas por distribuidoras— y un reclamo es
*parada total del sistema* por precedencia de paradas. La música generada en local es original: no
hay nada que reclamar, ni atribución que arrastrar en cada descripción.

**Dos trampas medidas al montar la mezcla**, por si alguien toca los parámetros:

1. La voz venía a -26 dB de media. Con el umbral del compresor por debajo de eso, el sidechain queda
   disparado permanentemente: no es ducking, es compresión constante. Hay que normalizar la voz
   **antes** de usarla como señal de control.
2. Un `loudnorm` sobre la mezcla ya comprimida **aplana** lo que el compresor acaba de hacer. El
   nivel final se cierra con `loudnorm` pero el ducking se aplica antes, no después.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from lib import comfy_client as cc
from lib.config import CANAL_PERFIL, COMFY_ROOT, base_del_estudio, bloque_del_canal
from lib.medios import get_audio_duration

# Hasta el 25-09-2026 aquí había un `DEFECTOS` con once valores que rellenaban lo que el canal no
# declaraba (`progress/plan_aislar_canales.md`). Ahora cada valor tiene UN dueño y ninguno defecto:
#
# - DEL ESTUDIO: `datos/base-del-estudio.json → produccion.lecho_musical` (motor, LUFS de YouTube, techo).
# - DEL CANAL, en `perfil.json → musica`: `activa` siempre, y el resto si `activa` es true.
#   `semilla_base` puede valer null —derivada del run— pero se escribe: fijarla repite el mismo lecho.
#   `sonoridad_por_tramo` también puede valer null —cada tramo entra con la sonoridad que da ACE-Step—, y también se
#   escribe. Ella, `ataque_ms` y `suelta_ms` estaban fijos aquí hasta F6.5b (addendum fila 210): eran la mezcla del
#   primer canal, y el segundo recupera la del v3 de la bici, que iguala cada tramo antes de encadenarlo y suelta
#   en 1,2 s.
DEL_ESTUDIO = ("workflow", "objetivo_lufs", "pico_max_dbtp")
DEL_CANAL = (
    "escena",
    "volumen_db",
    "tramo_segundos",
    "solape_segundos",
    "sonoridad_por_tramo",
    "umbral_ducking",
    "ratio_ducking",
    "ataque_ms",
    "suelta_ms",
    "semilla_base",
)
PUEDEN_SER_NULL = ("semilla_base", "sonoridad_por_tramo")
# Las tres claves de `sonoridad_por_tramo` cuando no es null: el `loudnorm` que iguala cada tramo antes de encadenarlo.
CLAVES_SONORIDAD_POR_TRAMO = ("lufs", "rango_lu", "pico_dbtp")

_RECORDS_FILENAME = "generacion-musica.json"


class MusicaError(RuntimeError):
    """Fallo al generar o mezclar el lecho musical."""


def ajustes(perfil: dict | None = None) -> dict:
    """Ajustes de música del canal activo: lo del estudio más lo que declara el canal, sin defectos.

    Las reglas, compartidas con los subtítulos, están en `lib/config.bloque_del_canal`. Lo propio de
    aquí: `semilla_base` (derivada del run) y `sonoridad_por_tramo` (sin igualar) son las únicas que pueden
    valer null, pero se escriben. Y la forma de `sonoridad_por_tramo` se comprueba aquí, antes de la GPU:
    un `loudnorm` mal escrito fallaría en ffmpeg después de generar todos los tramos.

    `perfil` es el del canal activo si no se pasa otro: el motor de escena (F6.2d) pasa el del episodio.
    """
    cfg = bloque_del_canal(
        (CANAL_PERFIL if perfil is None else perfil).get("musica"),
        bloque="musica",
        interruptor="activa",
        base=base_del_estudio()["produccion"]["lecho_musical"],
        donde_en_la_base="produccion.lecho_musical",
        del_estudio=DEL_ESTUDIO,
        del_canal=DEL_CANAL,
        que_es="son su sonido, y heredar el lecho de otro canal es ponerle el suyo",
        error=MusicaError,
        aviso="MUSICA",
        pueden_ser_null=PUEDEN_SER_NULL,
    )
    _valida_sonoridad_por_tramo(cfg.get("sonoridad_por_tramo"))
    return cfg


def _es_numero(valor) -> bool:
    return isinstance(valor, int | float) and not isinstance(valor, bool)


def _valida_sonoridad_por_tramo(valor) -> None:
    """null, o un objeto con `lufs`, `rango_lu` y `pico_dbtp` numéricos (y nada más)."""
    if valor is None:
        return
    claves = set(valor) if isinstance(valor, dict) else set()
    if (
        not isinstance(valor, dict)
        or claves != set(CLAVES_SONORIDAD_POR_TRAMO)
        or not all(_es_numero(valor[c]) for c in CLAVES_SONORIDAD_POR_TRAMO)
    ):
        raise MusicaError(
            f"`musica.sonoridad_por_tramo` vale {valor!r}: tiene que ser null (cada tramo entra con la sonoridad que "
            f"da ACE-Step) o un objeto con {', '.join(CLAVES_SONORIDAD_POR_TRAMO)} numéricos, por ejemplo "
            '{"lufs": -22, "rango_lu": 6, "pico_dbtp": -2}.'
        )


def _num(valor) -> str:
    """Un número para un filtro de ffmpeg sin decimales de sobra: 20 y 20.0 dan «20»; 0.5, «0.5»."""
    return f"{float(valor):g}"


def filtro_de_sonoridad_por_tramo(cfg: dict) -> str:
    """El `loudnorm` que iguala cada tramo ANTES de encadenarlo, o "" si el canal no iguala (null).

    Existe por el v3 de la bici (`canal/scripts/musica.py` del experimento video_1), que lo justifica así:
    «ACE-Step deja pasajes 5 dB más fuertes, y con ellos la música igualaba a la voz aun con el compresor». Termina en
    `aresample=48000` porque `loudnorm` saca la señal a 192 kHz (lo mismo que se cuenta en `filtro_de_nivel_final`).
    Con null devuelve "", y la cadena de filtros queda carácter a carácter como antes de F6.5b.
    """
    valor = cfg.get("sonoridad_por_tramo")
    if valor is None:
        return ""
    return (
        f"loudnorm=I={_num(valor['lufs'])}:LRA={_num(valor['rango_lu'])}:TP={_num(valor['pico_dbtp'])},aresample=48000,"
    )


def activa() -> bool:
    return bool(ajustes()["activa"])


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *args], check=True)


def _duracion(ruta: str | Path) -> float:
    """Duración del contenedor. Reutiliza la utilidad del montaje en vez de duplicarla."""
    return get_audio_duration(str(ruta))


def _genera_tramo(workflow: dict, escena: str, segundos: float, seed: int, destino: Path) -> dict:
    """Una pasada de ACE-Step. El nodo de salida devuelve `audio`, no `images`."""
    # `segundos` viaja como override por el punto de inyección del workflow. Antes se
    # escribía a mano con `_set_input` porque la inyección estaba inerte (auditoría de F2.12).
    grafo = cc.build_prompt_graph(
        workflow, escena, seed=seed, filename_prefix=destino.stem, overrides={"segundos": float(segundos)}
    )
    prompt_id = cc.submit_prompt(grafo)
    entrada = cc.wait_for_prompt(prompt_id, timeout=1800)

    salidas = entrada.get("outputs", {}).get(str(workflow["nodo_salida"]), {})
    piezas = salidas.get("audio") or salidas.get("images") or []
    if not piezas:
        raise MusicaError(
            f"El nodo {workflow['nodo_salida']} de '{workflow['id']}' no devolvió audio "
            f"(claves: {sorted(salidas)}). Revisa que el checkpoint de ACE-Step esté instalado."
        )
    pieza = piezas[0]
    final = destino.with_suffix(Path(pieza["filename"]).suffix)
    final.write_bytes(cc._download_image(pieza))
    cc._cleanup_server_copy(pieza)
    return {"archivo": final, "seed": seed, "segundos_pedidos": segundos}


def genera_lecho(
    duracion: float,
    output_dir: str | Path,
    escena: str | None = None,
    semilla_base: int | None = None,
    perfil: dict | None = None,
) -> dict:
    """Genera un lecho de `duracion` segundos y devuelve su ruta y procedencia.

    Se genera **por tramos con solape** en vez de una sola pasada: ACE-Step rinde bien en
    tramos cortos, y un lecho corto repetido en bucle se delata al oído en un long-form.
    `perfil`: el del canal activo si no se pasa otro (el motor de escena pasa el del episodio).
    """
    cfg = ajustes(perfil)
    out = Path(output_dir)
    # Los tramos son intermedios: van a `musica/`, que la procedencia trata como directorio
    # de trabajo. El lecho encadenado sí es un asset y se queda en la raíz del run.
    trabajo = out / "musica"
    trabajo.mkdir(parents=True, exist_ok=True)
    workflow = cc.load_workflow(cfg["workflow"])
    escena_final = escena if escena is not None else cfg["escena"]

    tramo = float(cfg["tramo_segundos"])
    solape = float(cfg["solape_segundos"])
    utiles = tramo - solape
    n = max(1, int(-(-max(duracion - solape, 0.1) // utiles)))  # techo de la división

    # La semilla base sale del RUN, no de una constante. ACE-Step es determinista y nada más
    # varía entre vídeos —la escena está en el perfil, los pasos en el workflow—, así que con una
    # semilla fija los cinco vídeos de la cohorte del Sprint 4 llevarían el mismo lecho byte a
    # byte. Con las imágenes la semilla fija sí tiene sentido (da consistencia de estilo mientras
    # el prompt cambia por lámina); aquí no cambiaría nada.
    if semilla_base is None:
        semilla_base = cfg.get("semilla_base")
    if semilla_base is None:
        semilla_base = int(hashlib.sha1(out.name.encode("utf-8")).hexdigest()[:8], 16) % 1_000_000
        origen_semilla = "derivada del run"
    else:
        semilla_base = int(semilla_base)
        origen_semilla = "fijada en el perfil del canal"
    print(
        f"  [MUSICA] {duracion:.1f} s de lecho en {n} tramo(s) de {tramo:.0f} s "
        f"(semilla base {semilla_base}, {origen_semilla})",
        flush=True,
    )
    tramos = []
    for i in range(n):
        # Semilla distinta por tramo: dos tramos con la misma semilla son la misma música.
        r = _genera_tramo(workflow, escena_final, tramo, semilla_base + i * 1111, trabajo / f"lecho-{i:02d}")
        tramos.append(r)
        print(f"    tramo {i + 1}/{n}: {r['archivo'].name}", flush=True)

    lecho = out / "lecho.wav"
    # Cada tramo, a la sonoridad que declara el canal antes de encadenarlo; "" si no la declara (null).
    iguala = filtro_de_sonoridad_por_tramo(cfg)
    if len(tramos) == 1:
        _ffmpeg(
            [
                "-i",
                str(tramos[0]["archivo"]),
                "-af",
                f"{iguala}atrim=0:{duracion:.3f},afade=t=in:d=3,afade=t=out:st={max(duracion - 5, 0):.3f}:d=5",
                "-c:a",
                "pcm_s16le",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(lecho),
            ]
        )
    else:
        entradas: list[str] = []
        filtros: list[str] = []
        for i, t in enumerate(tramos):
            entradas += ["-i", str(t["archivo"])]
            desplazamiento = int(i * utiles * 1000)
            cadena = f"[{i}:a]{iguala}"
            if i > 0:
                cadena += f"afade=t=in:d={solape:.1f},"
            if i < len(tramos) - 1:
                cadena += f"afade=t=out:st={utiles:.1f}:d={solape:.1f},"
            cadena += f"adelay={desplazamiento}|{desplazamiento}[t{i}]"
            filtros.append(cadena)
        mezcla = "".join(f"[t{i}]" for i in range(len(tramos)))
        filtros.append(
            f"{mezcla}amix=inputs={len(tramos)}:normalize=0,atrim=0:{duracion:.3f},"
            f"afade=t=in:d=3,afade=t=out:st={max(duracion - 5, 0):.3f}:d=5[out]"
        )
        _ffmpeg(
            [
                *entradas,
                "-filter_complex",
                ";".join(filtros),
                "-map",
                "[out]",
                "-c:a",
                "pcm_s16le",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(lecho),
            ]
        )

    registro = {
        "file": str(lecho),
        "workflow": workflow["id"],
        "modelo": workflow["modelo"]["nombre"],
        "pesos": workflow["modelo"].get("pesos", []),
        "licencia": workflow["modelo"].get("licencia", "desconocida"),
        # La URL de los pesos la declara el workflow (`modelo.url`) y llega a `assets.json` (OC1.4).
        "url": workflow["modelo"].get("url"),
        "origen": "generado en local con ComfyUI (127.0.0.1); música original, sin Content ID de terceros",
        "prompt": cc._compose_prompt(workflow, escena_final),
        "tramos": [{"seed": t["seed"], "segundos": t["segundos_pedidos"]} for t in tramos],
        "duracion_s": round(duracion, 2),
        "semilla_base": semilla_base,
        # Los parámetros EFECTIVOS, no los del workflow. `segundos` varía por tramo y ya consta
        # en `tramos`: dejarlo aquí con el valor por defecto del JSON hacía que el registro se
        # contradijera consigo mismo (`segundos: 30` junto a `tramos: [{segundos: 45}]`), y un
        # registro de procedencia que se contradice no defiende nada.
        "parametros": {clave: valor for clave, valor in workflow.get("parametros", {}).items() if clave != "segundos"},
        "segundos_por_tramo": tramo,
        # Cómo se encadenaron: el lecho no es la salida del modelo tal cual si cada tramo se igualó antes.
        "solape_segundos": solape,
        "sonoridad_por_tramo": cfg["sonoridad_por_tramo"],
    }
    (out / _RECORDS_FILENAME).write_text(json.dumps([registro], indent=2, ensure_ascii=False), encoding="utf-8")
    return registro


# La voz normalizada ANTES de usarse como señal de control del ducking (trampa 1 del docstring). La usan la mezcla de
# aquí y la del motor de escena (`lib/escena/audio.py`, F6.2d): el mismo reparto entre voz y lecho en los dos motores.
NORMA_DE_LA_VOZ = "loudnorm=I=-16:TP=-3:LRA=11"


def filtro_de_ducking(cfg: dict) -> str:
    """El compresor que aparta el lecho cuando hay habla: la voz (su segunda entrada) lo controla.

    Umbral, ratio, ataque y suelta son del canal. El ataque y la suelta estaban fijos aquí (20 y 500 ms, los del primer
    canal) hasta F6.5b: la suelta decide cuánto tarda la música en volver tras una frase, y el v3 de la bici la quiere
    larga (1,2 s) para que no suba y baje entre frase y frase.
    """
    return (
        f"sidechaincompress=threshold={cfg['umbral_ducking']}:"
        f"ratio={cfg['ratio_ducking']}:attack={_num(cfg['ataque_ms'])}:release={_num(cfg['suelta_ms'])}:makeup=1"
    )


def filtro_de_nivel_final(cfg: dict, baja_db: float = 0.0) -> str:
    """El nivel de la mezcla ya apartada (pasos 4 y 5 de `mezcla`): `loudnorm` al objetivo y el techo garantizado.

    `baja_db` baja la ganancia DESPUÉS del limitador. Lo usa `escena.audio.normaliza_video` cuando el AAC saca el pico
    por encima del objetivo (fila 253). Se baja la ganancia y no el limitador porque el pico del AAC no sigue al
    limitador: con las ráfagas de ruido de `tests/escena/test_audio.py`, bajarlo 0,5, 1 y 1,5 dB dejó el pico en −1,52,
    −1,29 y −1,51 dBTP, y bajar la ganancia lo mismo lo dejó en −1,70, −2,26 y −3,18. Con 0, la cadena es la de siempre.
    """
    ganancia = f"volume=-{baja_db:.2f}dB," if baja_db > 0 else ""
    return (
        # 4. El nivel final, DESPUÉS del ducking (trampa 2). Y se cierra la cadena con
        #    `aresample`: `loudnorm` renegocia la frecuencia de muestreo y sin esto la salida
        #    subía a 96 kHz —el doble de la entrada— gastando bitrate en banda que nadie sirve.
        f"loudnorm=I={cfg['objetivo_lufs']}:TP={cfg['pico_max_dbtp']}:LRA=9,"
        # 5. El techo, GARANTIZADO en vez de pedido. El `TP` de loudnorm es un objetivo que su
        #    pasada única estima, y se le escapa: al cambiar la voz a Kokoro (F2.16) la misma
        #    cadena pasó de -2,3 a -1,4 dBTP con el objetivo en -1,5. `alimiter` lo impone por
        #    construcción. `level=disabled` es obligatorio: su auto-nivelado por defecto
        #    renormaliza a 0 dB y desharía el loudnorm de la línea anterior.
        f"alimiter=limit={10 ** (float(cfg['pico_max_dbtp']) / 20):.4f}:level=disabled,"
        f"{ganancia}aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    )


def mezcla(video: str | Path, lecho: str | Path, destino: str | Path) -> dict:
    """Mezcla el lecho bajo la narración del vídeo, con ducking, y cierra el nivel.

    El vídeo se copia sin recodificar: solo se toca el audio.
    """
    cfg = ajustes()
    filtro = (
        # 1. La voz, normalizada ANTES de usarse como señal de control (trampa 1 del docstring)
        f"[0:a]{NORMA_DE_LA_VOZ},asplit=2[voz][ctrl];"
        f"[1:a]volume={cfg['volumen_db']}dB[lecho];"
        # 2. El ducking: la música se aparta cuando hay habla y vuelve en los silencios
        f"[lecho][ctrl]{filtro_de_ducking(cfg)}[duck];"
        # 3. La voz sube a estéreo ANTES de mezclar. La narración viene mono del montaje
        #    (F2.6) y el lecho se genera estéreo: mezclarlos sin más colapsaba el lecho a mono,
        #    o sea se generaban dos canales para tirar uno. Y la anchura es justo lo que hace que
        #    un lecho se perciba «de fondo» y no «encima». Es un cambio deliberado del formato
        #    del archivo que se publica: el vídeo pasa a ser estéreo.
        "[voz]aformat=channel_layouts=stereo[voz_st];"
        "[voz_st][duck]amix=inputs=2:normalize=0:dropout_transition=0[mez];"
        # 4 y 5. El nivel final y el techo, en `filtro_de_nivel_final`.
        f"[mez]{filtro_de_nivel_final(cfg)}[out]"
    )
    _ffmpeg(
        [
            "-i",
            str(video),
            "-i",
            str(lecho),
            "-filter_complex",
            filtro,
            "-map",
            "0:v",
            "-map",
            "[out]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(destino),
        ]
    )
    return medicion(destino)


def nivel_del_lecho(video_sin_musica: str | Path, lecho: str | Path) -> float | None:
    """Cuántos dB por debajo de la narración se asienta el lecho, tras volumen y ducking.

    Se renderizan las dos ramas del filtro por separado y se comparan sus sonoridades. Es lo
    que convierte «hay música» en un número: la comparación por bandas de la mezcla completa
    no distingue un lecho audible de uno inaudible.
    """
    cfg = ajustes()
    with tempfile.TemporaryDirectory() as tmp:
        solo_lecho = Path(tmp) / "lecho-duck.wav"
        _ffmpeg(
            [
                "-i",
                str(video_sin_musica),
                "-i",
                str(lecho),
                "-filter_complex",
                f"[0:a]{NORMA_DE_LA_VOZ}[ctrl];"
                f"[1:a]volume={cfg['volumen_db']}dB[l];"
                f"[l][ctrl]{filtro_de_ducking(cfg)}[o]",
                "-map",
                "[o]",
                "-c:a",
                "pcm_s16le",
                str(solo_lecho),
            ]
        )
        solo_voz = Path(tmp) / "voz-norm.wav"
        _ffmpeg(
            [
                "-i",
                str(video_sin_musica),
                "-vn",
                "-af",
                NORMA_DE_LA_VOZ,
                "-c:a",
                "pcm_s16le",
                str(solo_voz),
            ]
        )
        a, b = medicion(solo_voz).get("lufs"), medicion(solo_lecho).get("lufs")
    return round(a - b, 1) if (a is not None and b is not None) else None


def medicion(ruta: str | Path) -> dict:
    """Sonoridad, pico y reparto por bandas — la vara con la que se comparó la referencia."""
    proceso = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(ruta), "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    bloque = proceso.stderr[proceso.stderr.rfind("{") : proceso.stderr.rfind("}") + 1]
    datos: dict = {}
    try:
        medido = json.loads(bloque)
        datos["lufs"] = float(medido["input_i"])
        datos["pico_dbtp"] = float(medido["input_tp"])
        datos["rango_lu"] = float(medido["input_lra"])
    except (ValueError, KeyError):
        datos.update({"lufs": None, "pico_dbtp": None, "rango_lu": None})

    for etiqueta, banda in (("graves_db", "highpass=f=80,lowpass=f=250"), ("voz_db", "highpass=f=250,lowpass=f=3400")):
        salida = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", str(ruta), "-vn", "-af", f"{banda},volumedetect", "-f", "null", "-"],
            capture_output=True,
            text=True,
        ).stderr
        encontrado = re.search(r"mean_volume:\s*(-?[\d.]+)", salida)
        datos[etiqueta] = float(encontrado.group(1)) if encontrado else None
    if datos.get("graves_db") is not None and datos.get("voz_db") is not None:
        datos["graves_menos_voz_db"] = round(datos["graves_db"] - datos["voz_db"], 1)
    return datos


# Margen de la medición: el pico se mide sobre el AAC ya codificado, y la codificación puede
# añadir picos inter-muestra que el filtro no ve. Por debajo de esto, cumplir es cumplir.
TOLERANCIA_PICO_DB = 0.3
# Techo duro. Pasado esto ya no es «se desvía del objetivo», es que el vídeo publicado satura.
PICO_INACEPTABLE_DBTP = -0.1


def verifica_techo(medido: dict, cfg: dict) -> dict:
    """Cruza el pico MEDIDO con el objetivo declarado, y lo deja escrito.

    Existe porque durante F2.12 el pico se medía, se imprimía y **nadie lo comparaba con su
    objetivo**: la mezcla salió a -1,4 dBTP con `pico_max_dbtp` en -1,5 y el run se cerró como
    correcto. Una cifra que se imprime sin su criterio no es una verificación.

    No falla por desviarse —un pico de -1,4 no daña nada—, pero sí por saturar, porque eso no
    se arregla después de publicar.
    """
    objetivo = float(cfg["pico_max_dbtp"])
    pico = medido.get("pico_dbtp")
    if pico is None:
        return {"objetivo_dbtp": objetivo, "medido_dbtp": None, "cumple": None, "detalle": "no se pudo medir el pico"}

    resultado = {
        "objetivo_dbtp": objetivo,
        "medido_dbtp": pico,
        "tolerancia_db": TOLERANCIA_PICO_DB,
        "cumple": pico <= objetivo + TOLERANCIA_PICO_DB,
    }
    if pico > PICO_INACEPTABLE_DBTP:
        raise MusicaError(
            f"La mezcla satura: pico {pico} dBTP (techo duro {PICO_INACEPTABLE_DBTP}). "
            "No se publica un audio con clipping; revisa `volumen_db` y `objetivo_lufs` del perfil del canal."
        )
    if not resultado["cumple"]:
        print(
            f"  [MUSICA] AVISO: pico {pico} dBTP por encima del objetivo {objetivo} "
            f"(+{round(pico - objetivo, 2)} dB, tolerancia {TOLERANCIA_PICO_DB}). No satura, pero el margen "
            "para la recodificación de YouTube es menor del previsto.",
            flush=True,
        )
    return resultado


def aplica(video: str | Path, output_dir: str | Path) -> dict | None:
    """Genera el lecho de la duración del vídeo y lo mezcla. `None` si el canal no lo usa.

    Deja el vídeo original como `final-sin-musica.mp4`: si la mezcla no convence, el montaje
    no hay que repetirlo, y comparar los dos es cómo se comprobó que el lecho se oye.
    """
    if not activa():
        return None
    video = Path(video)
    out = Path(output_dir)
    duracion = _duracion(video)

    with cc.comfy_server():
        registro = genera_lecho(duracion, out, None)
        cc.free_memory()

    trabajo = out / "musica"
    trabajo.mkdir(parents=True, exist_ok=True)
    sin_musica = trabajo / ("final-sin-musica" + video.suffix)
    video.replace(sin_musica)
    medido = mezcla(sin_musica, registro["file"], video)
    registro["medicion"] = medido
    # El nivel del LECHO respecto a la narración. Es la cifra que demuestra que la música está
    # y a qué distancia; el reparto por bandas de la mezcla completa (`medicion`) sirve para
    # comparar contra la referencia pero **no discrimina** con música de sin música: la
    # auditoría de F2.12 midió 0,7 dB de diferencia entre las dos, y el lecho de osciladores
    # rechazado por inaudible ya caía dentro de la banda objetivo.
    registro["medicion"]["lecho_bajo_narracion_db"] = nivel_del_lecho(sin_musica, registro["file"])
    registro["medicion"]["comparacion_sin_musica"] = medicion(sin_musica)
    registro["medicion"]["techo"] = verifica_techo(medido, ajustes())
    (out / _RECORDS_FILENAME).write_text(json.dumps([registro], indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"  [MUSICA] mezclado: {medido.get('lufs')} LUFS · pico {medido.get('pico_dbtp')} dBTP · "
        f"graves-voz {medido.get('graves_menos_voz_db')} dB",
        flush=True,
    )
    return registro


def preflight() -> list[dict]:
    """¿Podría este adaptador poner música AHORA? Lo consume `pipeline.py --check`.

    Sin esto, con el checkpoint ausente de la instalación **compartida** —que es de otro
    proyecto y nadie garantiza que no se limpie— `--check` decía «Listo para producir» y el
    fallo aparecía en la ÚLTIMA etapa: después de las láminas (~40 min de GPU en un
    long-form), la voz (~33 min) y el montaje (~16 min). El trabajo no se pierde, pero la
    tarde sí.
    """
    cfg = ajustes()
    if not cfg["activa"]:
        return [
            {
                "nombre": "música",
                "ok": True,
                "detalle": "desactivada en el perfil del canal (musica.activa=false): el vídeo va solo con voz",
                "obligatorio": False,
            }
        ]

    checks: list[dict] = []
    try:
        # Cargar el workflow valida de paso la lista blanca de nodos y la generación en serie.
        workflow = cc.load_workflow(cfg["workflow"])
        checks.append(
            {
                "nombre": "workflow de música",
                "ok": True,
                "detalle": f"{workflow['id']} → {workflow['modelo']['nombre']}",
                "obligatorio": True,
            }
        )
    except cc.ComfyError as exc:
        return [{"nombre": "workflow de música", "ok": False, "detalle": str(exc), "obligatorio": True}]

    faltan = [peso for peso in workflow["modelo"].get("pesos", []) if not (COMFY_ROOT / "models" / peso).is_file()]
    checks.append(
        {
            "nombre": "pesos de música",
            "ok": not faltan,
            "detalle": (
                f"{len(workflow['modelo'].get('pesos', []))} peso(s) presentes en {COMFY_ROOT / 'models'}"
                if not faltan
                else f"FALTAN en la instalación compartida: {faltan}. Se descargan de HuggingFace "
                "(ver workflows/README.md); son 7,17 GiB."
            ),
            "obligatorio": True,
        }
    )
    return checks
