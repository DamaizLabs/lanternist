"""El sonido del motor de escena (F6.2d): la narración con sus pausas, el lecho apartado bajo la voz y los efectos.

Viene de `canal/scripts/audio.py` y `canal/scripts/musica.py` del experimento video_1, generalizado para el
estudio. Lo que allí era del canal (la pausa de 6,5 s, la intro de 5 s, el volumen de la música) aquí lo declara el
canal, sin defecto; y lo que allí era un grafo propio de ACE-Step aquí es `lib/musica.py`, el mismo del motor viejo.

**Las pistas de la composición.** HyperFrames mezcla los `<audio>` de la página al renderizar, cada uno con su
volumen, así que el sonido llega a la composición en pistas separadas:

1. **La narración** (`narracion`): los wav del run, cada uno ajustado a su tramo de la línea de tiempo (un número
   entero de fotogramas) y con los silencios que declara el canal en `escena.pausas` (intro, entre partes y cola).
   Sin esas pausas declaradas no hay línea de tiempo y la etapa para antes de llegar aquí (`lib/escena/ajustes.py`).
2. **El lecho** (`mezcla_lecho`), si el canal lleva música (`musica.activa`): lo genera `lib/musica.genera_lecho` con
   ACE-Step y aquí se aparta bajo la voz con un compresor que escucha la narración (*sidechain*): la música baja
   sola cuando se habla y vuelve en las pausas. Es el filtro de `lib/musica.py`, con los ajustes del canal.
3. **Los efectos** (`efectos`): los que el guion de escena hace sonar (`Guion.sonidos`), de la biblioteca del
   estudio (`datos/escena/sfx/`), cada uno en la primera pista libre en su instante.

**La sonoridad, como en el motor viejo.** Con música, la voz entra normalizada (`musica.NORMA_DE_LA_VOZ`) y, tras el
render, el vídeo entero se lleva al objetivo del estudio con el techo garantizado (`normaliza_video`, el paso final
de `musica.mezcla`). Sin música, la narración entra tal cual y no se toca después: es lo que hacía el montaje con un
canal sin lecho, así que un canal no cambia de sonoridad por cambiar de motor.

**La biblioteca, con su procedencia** (decisión 5). Los efectos y las fuentes que usa un episodio se copian a
`<run>/biblioteca/` y se apuntan en su registro (`provenance.LIBRARY_RECORDS_FILENAME`) con la fuente, la licencia y
la url de su `CREDITOS.json`. Un fichero sin entrada, o que ya no tiene el sha256 apuntado, para la etapa.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from lib import config, musica, provenance
from lib.medios import get_audio_duration

# Las pistas de audio de la composición (`data-track-index`), por encima de las de imagen de `compone.py`.
PISTA_LECHO = 9
PISTA_NARRACION = 10
PRIMERA_PISTA_DE_EFECTOS = 11
# Dónde va cada cosa dentro de la composición.
SRC_NARRACION = "assets/audio/narracion.wav"
SRC_LECHO = "assets/audio/lecho.wav"
SRC_SFX = "assets/sfx"
SRC_FUENTES = "assets/fuentes"
# Un efecto que empezaría a menos de esto del final no llega a oírse: se descarta, y se dice (video_1 hacía lo mismo).
COLA_MINIMA_S = 0.05
MUESTRAS_POR_SEGUNDO = 48000


class ErrorDeAudio(ValueError):
    """El sonido del episodio no se puede montar así: el mensaje dice qué falta."""


def _ffmpeg(args: list[str]) -> None:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise ErrorDeAudio(f"ffmpeg falló (código {r.returncode}): {r.stderr.strip()[-600:]}")


# ------------------------------------------------------------------------------------------ la narración
def narracion(linea, audios: Sequence[str | Path], destino: str | Path, *, normaliza: bool) -> dict:
    """La narración del episodio en un wav mono a 48 kHz: cada lámina en su sitio y los silencios del canal.

    - `linea`: la `LineaDeTiempo` del episodio (sus tramos, sus pausas y su duración total).
    - `audios`: el wav de cada lámina de voz, en el orden de `linea.laminas`.
    - `normaliza`: la voz a `musica.NORMA_DE_LA_VOZ` (con música, como en el motor viejo) o tal cual.

    Cada lámina se ajusta a su tramo (su duración redondeada a fotogramas) y el total se rellena hasta
    `linea.total`, así que la pista dura exactamente lo que el GUION.
    """
    audios = [Path(a) for a in audios]
    if len(audios) != len(linea.tramos):
        raise ErrorDeAudio(f"la línea de tiempo tiene {len(linea.tramos)} láminas de voz y llegan {len(audios)} wav")
    faltan = [str(a) for a in audios if not a.is_file()]
    if faltan:
        raise ErrorDeAudio(f"faltan audios de la narración: {faltan}")
    entradas: list[str] = []
    filtros: list[str] = []
    orden: list[str] = []

    def silencio(etiqueta: str, segundos: float) -> None:
        if segundos > 0:
            filtros.append(f"anullsrc=r={MUESTRAS_POR_SEGUNDO}:cl=mono,atrim=duration={segundos:.6f}[{etiqueta}]")
            orden.append(f"[{etiqueta}]")

    silencio("intro", linea.intro)
    for k, audio in enumerate(audios):
        entradas += ["-i", str(audio)]
        filtros.append(
            f"[{k}:a]aresample={MUESTRAS_POR_SEGUNDO},aformat=channel_layouts=mono,apad,"
            f"atrim=duration={linea.tramos[k]:.6f}[n{k}]"
        )
        orden.append(f"[n{k}]")
        if k < len(audios) - 1:
            silencio(f"p{k}", linea.pausa)
    silencio("cola", linea.cola)
    voz = f",{musica.NORMA_DE_LA_VOZ},aresample={MUESTRAS_POR_SEGUNDO}" if normaliza else ""
    filtros.append(
        f"{''.join(orden)}concat=n={len(orden)}:v=0:a=1,apad,atrim=duration={linea.total:.6f}{voz}"
        f",aformat=sample_fmts=s16:channel_layouts=mono[fuera]"
    )
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg([*entradas, "-filter_complex", ";".join(filtros), "-map", "[fuera]", "-c:a", "pcm_s16le", str(destino)])
    return {"archivo": destino, "duracion_s": round(get_audio_duration(str(destino)), 3), "normalizada": normaliza}


# ------------------------------------------------------------------------------------------ el lecho
def mezcla_lecho(narracion_wav: str | Path, lecho: str | Path, destino: str | Path, cfg: Mapping, total: float) -> dict:
    """El lecho apartado bajo la voz, en estéreo a 48 kHz y de `total` segundos: la pista de música de la composición.

    `cfg` son los ajustes de música del canal (`musica.ajustes`): su volumen y su compresor
    (`musica.filtro_de_ducking`). La voz se normaliza antes de usarse como señal de control, que es la trampa 1 de
    `lib/musica.py`: con la voz baja el compresor quedaría disparado siempre, y eso no es apartarse, es comprimir.

    **La señal de control se remuestrea a 48 kHz en estéreo y se rellena hasta el final.** `loudnorm` la saca a 192
    kHz y se queda con sus últimos segundos (su ventana), y con el control tal cual (el de `musica.mezcla`) la rama
    apartada sale más corta que el lecho: 57,344 s de 60 y 4,352 s de 6 con señales sintéticas
    (`experimentos/motor-escena/f62d-audio/mide.json → 60s/6s.duracion_control_de_musica_mezcla_s`). En el montaje
    de siempre esos segundos de menos caerían dentro del fundido final de 5 s del lecho (no se ha medido sobre un
    episodio real); aquí el lecho es una pista de la composición y tiene que durar lo que el episodio. Con el
    control así, las mismas señales dan 60,0 y 6,0 s y el lecho baja 8,8 dB mientras se habla (`… →
    duracion_nuevo_s`, `apartado_db`; la prueba, con su control sin compresor, en `tests/escena/test_audio.py`).
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    formato = f"aresample={MUESTRAS_POR_SEGUNDO},aformat=sample_fmts=fltp:channel_layouts=stereo"
    filtro = (
        f"[1:a]{musica.NORMA_DE_LA_VOZ},{formato},apad[ctrl];"
        f"[0:a]{formato},volume={cfg['volumen_db']}dB[l];"
        f"[l][ctrl]{musica.filtro_de_ducking(cfg)},atrim=0:{total:.6f},"
        "aformat=sample_fmts=s16:channel_layouts=stereo[fuera]"
    )
    _ffmpeg(
        ["-i", str(lecho), "-i", str(narracion_wav), "-filter_complex", filtro, "-map", "[fuera]"]
        + ["-c:a", "pcm_s16le", str(destino)]
    )
    return {"archivo": destino, "duracion_s": round(get_audio_duration(str(destino)), 3)}


# El AAC sube el pico DESPUÉS del limitador: «Blue» (F7.3) salió a −1,02 dBTP con el objetivo en −1,5 (fila 253). Si el
# pico medido sobre el AAC pasa del objetivo, la ganancia baja lo que sobra más este colchón y se codifica otra vez.
COLCHON_DEL_TECHO_DB = 0.1
PASADAS_DEL_TECHO = 3


def normaliza_video(entrada: str | Path, destino: str | Path, cfg: Mapping) -> dict:
    """El vídeo con su sonido al objetivo del estudio y el techo garantizado; la imagen se copia sin recodificar.

    Es el paso final de `musica.mezcla` (`musica.filtro_de_nivel_final`) sobre el sonido que ya mezcló HyperFrames.
    Devuelve la medición y el techo comprobado (`musica.verifica_techo`, que para si el vídeo satura).

    **El techo se comprueba sobre el AAC, no sobre el filtro.** El limitador deja las muestras en el objetivo, pero la
    codificación añade picos que él no ve. Así que se mide el fichero codificado y, si se pasa, se repite con la
    ganancia más baja: como mucho `PASADAS_DEL_TECHO` veces. El techo apunta cuántas hicieron falta y cuánto bajó, que
    es lo que el vídeo pierde de sonoridad.
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    objetivo = float(cfg["pico_max_dbtp"])
    margen = 0.0
    for pasada in range(1, PASADAS_DEL_TECHO + 1):
        _ffmpeg(
            ["-i", str(entrada), "-filter_complex", f"[0:a]{musica.filtro_de_nivel_final(cfg, margen)}[fuera]"]
            + ["-map", "0:v", "-map", "[fuera]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(destino)]
        )
        medido = musica.medicion(destino)
        pico = medido.get("pico_dbtp")
        if pico is None or pico <= objetivo or pasada == PASADAS_DEL_TECHO:
            break
        margen += pico - objetivo + COLCHON_DEL_TECHO_DB
    medido["techo"] = musica.verifica_techo(medido, cfg)
    medido["techo"]["pasadas"] = pasada
    medido["techo"]["ganancia_bajada_db"] = round(margen, 2)
    return medido


# ------------------------------------------------------------------------------------------ la biblioteca
def lee_creditos(carpeta: str | Path) -> dict[str, dict]:
    """Las entradas del `CREDITOS.json` de una carpeta de la biblioteca: {fichero: {fuente, licencia, url, sha256…}}."""
    ruta = Path(carpeta) / config.ESCENA_CREDITOS
    if not ruta.is_file():
        raise ErrorDeAudio(f"no está {ruta}: sin él no se sabe de dónde sale nada de esa carpeta")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    ficheros = datos.get("ficheros") if isinstance(datos, dict) else None
    if not isinstance(ficheros, dict):
        raise ErrorDeAudio(f"{ruta} no tiene la forma esperada: {{'ficheros': {{nombre: {{fuente, licencia, url}}}}}}")
    return ficheros


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def de_la_biblioteca(carpeta: str | Path, nombre: str, tipo: str, destino: str | Path, creditos: Mapping) -> dict:
    """Copia `nombre` de una carpeta de la biblioteca a `destino` y devuelve su registro de procedencia.

    Para si el fichero no está, si su entrada no dice fuente, licencia y url, o si su sha256 ya no es el apuntado:
    un fichero cambiado sin cambiar su entrada llevaría al vídeo algo cuya procedencia nadie ha escrito.
    """
    origen = Path(carpeta) / nombre
    if not origen.is_file():
        como = ""
        if nombre in creditos and Path(carpeta) == config.ESCENA_SFX_DIR:
            como = (
                ". Los efectos no viajan en el repositorio: se instalan con `cd motor; npm ci` y "
                "`scripts/instala_efectos.py`"
            )
        raise ErrorDeAudio(f"«{nombre}» no está en la biblioteca del estudio ({carpeta}){como}")
    ficha = creditos.get(nombre)
    faltan = [c for c in ("fuente", "licencia", "url", "sha256") if not (ficha or {}).get(c)]
    if faltan:
        raise ErrorDeAudio(
            f"«{nombre}» no tiene {faltan} en {Path(carpeta) / config.ESCENA_CREDITOS}: sin procedencia no entra en "
            "un vídeo"
        )
    sha = _sha256(origen)
    if sha != ficha["sha256"]:
        raise ErrorDeAudio(
            f"«{nombre}» ha cambiado desde que se apuntó en {config.ESCENA_CREDITOS} (sha256 {sha[:12]}… frente a "
            f"{str(ficha['sha256'])[:12]}…): actualiza su entrada con su procedencia antes de usarlo"
        )
    copia = Path(destino) / nombre
    copia.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origen, copia)
    try:
        desde = origen.resolve().relative_to(config.BASE_DIR).as_posix()
    except ValueError:
        desde = origen.name  # una biblioteca fuera del repositorio: sin rutas personales en el registro
    return {
        "file": str(copia),
        "tipo": tipo,
        "fuente": ficha["fuente"],
        "licencia": ficha["licencia"],
        "url": ficha["url"],
        "autor": ficha.get("autor") or "",
        "sha256": sha,
        "notas": ficha.get("notas") or "",
        "desde": desde,
        "origen": f"copiado de la biblioteca del estudio ({desde})",
    }


_URL_DE_FUENTE = re.compile(r"""url\(\s*(['"]?)(assets/fuentes/[^'")\s]+)\1\s*\)""", re.IGNORECASE)


def fuentes_del_css(css: str) -> list[str]:
    """Los ficheros de `assets/fuentes/` que pide el CSS del canal (sus `@font-face`), en orden y sin repetir."""
    return list(dict.fromkeys(Path(m.group(2)).name for m in _URL_DE_FUENTE.finditer(css)))


def _pistas(tramos: Sequence[tuple[float, float]]) -> list[int]:
    """La pista de cada efecto: la primera que esté libre en su instante (dos efectos a la vez no comparten pista)."""
    libres_desde: list[float] = []
    salida = []
    for t0, t1 in tramos:
        for i, fin in enumerate(libres_desde):
            if fin <= t0 + 1e-6:
                libres_desde[i] = t1
                salida.append(PRIMERA_PISTA_DE_EFECTOS + i)
                break
        else:
            libres_desde.append(t1)
            salida.append(PRIMERA_PISTA_DE_EFECTOS + len(libres_desde) - 1)
    return salida


def biblioteca(run_dir: str | Path, sonidos: Sequence[Mapping], css: str, total: float) -> dict:
    """Los efectos y las fuentes del episodio: copiados al run con su registro, y listos para la composición.

    - `sonidos`: los del guion de escena (`Guion.sonidos`: `nombre`, `t`, `vol` y, si se corta antes, `dur`).
    - `css`: el CSS del canal; las fuentes que pide en `assets/fuentes/` salen de la biblioteca.
    - `total`: la duración del episodio.

    Devuelve `audios` (las pistas de efectos para el GUION), `assets` (lo que `compone` tiene que copiar) y
    `descartados` (efectos que empezarían tras el final). `<run>/biblioteca/` se rehace entera en cada llamada: lo
    que el episodio ya no usa no se queda con una procedencia que no le corresponde.
    """
    dir_run = config.biblioteca_del_run(run_dir)
    if dir_run.exists():
        shutil.rmtree(dir_run)
    registros: list[dict] = []
    assets: dict[str, Path] = {}
    audios: list[dict] = []
    descartados: list[str] = []
    creditos_sfx = lee_creditos(config.ESCENA_SFX_DIR) if sonidos else {}
    duraciones: dict[str, float] = {}
    usables = []
    for s in sorted(sonidos, key=lambda s: s["t"]):
        if s["t"] >= total - COLA_MINIMA_S:
            descartados.append(f"{s['nombre']} en t={s['t']}: empieza tras el final del episodio ({total:.3f} s)")
            continue
        fichero = f"{s['nombre']}.mp3"
        if fichero not in duraciones:
            registro = de_la_biblioteca(config.ESCENA_SFX_DIR, fichero, "sonido", dir_run / "sfx", creditos_sfx)
            registros.append(registro)
            assets[f"{SRC_SFX}/{fichero}"] = Path(registro["file"])
            duraciones[fichero] = get_audio_duration(registro["file"])
        d = min(duraciones[fichero], s.get("dur") or duraciones[fichero], total - s["t"])
        usables.append((s, fichero, round(d, 3)))
    for i, ((s, fichero, d), pista) in enumerate(zip(usables, _pistas([(s["t"], s["t"] + d) for s, _, d in usables]))):
        audios.append(
            {"id": f"sfx{i}", "src": f"{SRC_SFX}/{fichero}", "t": s["t"], "d": d, "pista": pista, "volumen": s["vol"]}
        )
    nombres_de_fuente = fuentes_del_css(css)
    if nombres_de_fuente:
        creditos_fuentes = lee_creditos(config.ESCENA_FUENTES_DIR)
        for fichero in nombres_de_fuente:
            registro = de_la_biblioteca(
                config.ESCENA_FUENTES_DIR, fichero, "fuente", dir_run / "fuentes", creditos_fuentes
            )
            registros.append(registro)
            assets[f"{SRC_FUENTES}/{fichero}"] = Path(registro["file"])
    provenance.anade_registros(dir_run / provenance.LIBRARY_RECORDS_FILENAME, registros)
    return {"audios": audios, "assets": assets, "descartados": descartados, "registros": registros}


def pista_entera(src: str, total: float, numero: int, ident: str) -> dict:
    """Una pista que suena de principio a fin (la narración o el lecho), con el volumen tal cual se mezcló."""
    return {"id": ident, "src": src, "t": 0.0, "d": round(total, 3), "pista": numero, "volumen": 1}
