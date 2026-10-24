"""La traducción del `.srt` de un run (F7.11, fila 265): la saca, la comprueba, la escribe y la exige al subir.

**Quién traduce.** Claude, en la sesión de `produce-semana` (05-10-2026, fila 265; las otras opciones eran
opus-mt en CPU y un LLM local con llama.cpp). No sale nada nuevo del PC: el guion en inglés ya lo escribe Claude. Este
módulo no traduce. Prepara lo que Claude traduce y comprueba lo que devuelve.

**Los dos pasos**, con `scripts/traduce_srt.py`, después de la etapa `alinea`:

1. `saca`: los cues del `.srt` de origen (`subir-al-canal/subtitulos.<origen>.srt`) en un JSON del run
   (`subtitulos/cues.<origen>.json`): su número, sus tiempos y su texto, más el sha256 del `.srt`.
2. `escribe`: Claude devuelve ese JSON con cada `texto` traducido. Se comprueba y se escribe
   `subir-al-canal/subtitulos.<idioma>.srt` con los MISMOS tiempos del de origen, que no se toca. Su procedencia entra
   en `assets.json` (decisión 5) con quién tradujo, el idioma, el `.srt` del que sale y su sha256.

**Qué para `escribe`**: un idioma que el canal no declara (`perfil.json → subtitulos.traducciones`); un cue de más o de
menos; un número fuera de su sitio; un tiempo distinto del de origen; un texto vacío; una línea más larga que la de los
cues del canal (`escena.cues.max_caracteres`) o más de `MAX_LINEAS` líneas en un cue; una traducción que no traduce
nada; y un `.srt` de origen que ha cambiado desde que se sacaron sus cues.

**Qué exige la subida** (`exige_al_dia`), antes de gastar cuota: que esté cada traducción que el canal declara, que el
`.srt` de origen sea el mismo que se tradujo (su sha256) y que la traducción sea la que se escribió. Devuelve todos los
`.srt` que el usuario adjunta a mano en Studio.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lib import config, provenance, subtitulos

# Quién traduce y con qué derechos: lo decidió el estudio para todos sus canales (fila 265), no un canal.
TRADUCTOR = "Claude (Anthropic), en la sesión de produce-semana de Claude Code"
# No afirma más de lo que se sabe (auditoría de F7.11, `progress/review_F7.11.md` §1). Los términos de Anthropic ceden
# sus derechos sobre lo que genera Claude «if any», a quien sea titular de la cuenta según los términos que apliquen
# (de consumo o comerciales), y nadie ha leído aún la versión vigente. Cuando el usuario la lea, «sin comprobar» se
# cambia por el documento y su fecha, con su fila en el addendum, como con Kaggle en la fila 20.
LICENCIA = (
    "traducción del guion del canal hecha con Claude. Según los términos de Anthropic que apliquen a la cuenta de "
    "Claude Code, Anthropic cede a su titular los derechos que tenga sobre lo que genera Claude, si tiene alguno "
    "(versión de los términos sin comprobar)"
)
ORIGEN = (
    "Claude la escribió en la sesión sobre los cues que saca scripts/traduce_srt.py; no sale nada nuevo del PC, "
    "porque el guion ya lo escribe Claude"
)

# Líneas que puede tener un cue traducido. El de origen lleva una, partida con el troceo de cues del canal; la
# traducción suele ser más larga (en español, en torno a un 20 %), así que puede partirse en dos, que es lo que admite
# un subtítulo que se lee de un vistazo. Es del estudio: vale igual para cualquier canal.
MAX_LINEAS = 2


class ErrorDeTraduccion(RuntimeError):
    """La traducción no se puede escribir o la subida no puede seguir: el mensaje dice qué falta y qué hacer."""


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def srt_de_origen(run_dir: str | Path, origen: str) -> Path:
    """El `.srt` que escribe la etapa `alinea`, en el idioma de los subtítulos del canal."""
    return config.ruta_publicable(run_dir, f"subtitulos.{origen}.srt")


def srt_traducido(run_dir: str | Path, idioma: str) -> Path:
    """Dónde va el `.srt` traducido: junto al de origen, en `subir-al-canal/`."""
    return config.dir_subir_al_canal(run_dir) / f"subtitulos.{idioma}.srt"


def ruta_de_cues(run_dir: str | Path, origen: str) -> Path:
    """El JSON con los cues que saca `saca`. Vive en `subtitulos/`, que es material de trabajo del run."""
    return Path(run_dir) / "subtitulos" / f"cues.{origen}.json"


def limite_de_linea(perfil: dict) -> int:
    """Los caracteres de una línea del `.srt` del canal: los de sus cues (`escena.cues.max_caracteres`), sin defecto."""
    from lib.escena import ajustes

    try:
        return int(ajustes.exige(perfil)["cues"]["max_caracteres"])
    except ajustes.ErrorDeAjustes as error:
        raise ErrorDeTraduccion(f"no sé cuánto puede medir una línea del .srt de este canal: {error}") from None


def _cues_de_origen(srt: Path) -> list[dict]:
    if not srt.is_file():
        raise ErrorDeTraduccion(f"no está el .srt de origen ({srt}): falta la etapa alinea")
    try:
        return subtitulos.lee_srt(srt)
    except subtitulos.SubtitulosError as error:
        raise ErrorDeTraduccion(f"el .srt de origen no se puede traducir: {error}") from None


def saca(run_dir: str | Path, perfil: dict, *, origen: str) -> Path:
    """Escribe en el run los cues del `.srt` de origen, para que Claude los traduzca. Devuelve la ruta del JSON."""
    srt = srt_de_origen(run_dir, origen)
    cues = _cues_de_origen(srt)
    limite = limite_de_linea(perfil)
    datos = {
        "_que_hacer": (
            "Traduce el `texto` de cada cue y guarda este mismo JSON con otro nombre (cues.<idioma>.json). No toques "
            "`n`, `inicio`, `fin` ni `origen`: los tiempos son los del .srt de origen. Una línea más larga que "
            f"{limite} caracteres se parte en dos con \\n, y un cue no puede tener más de {MAX_LINEAS} líneas."
        ),
        "origen": {
            "srt": provenance.asset_id(Path(run_dir), srt),
            "idioma": origen,
            "sha256": _sha256(srt),
        },
        "max_caracteres_por_linea": limite,
        "max_lineas": MAX_LINEAS,
        "cues": cues,
    }
    destino = ruta_de_cues(run_dir, origen)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destino


def comprueba(origen: list[dict], traduccion: list, *, limite: int) -> list[str]:
    """Todo lo que falla de una traducción frente a los cues de origen. Vacío si se puede escribir.

    Devuelve TODOS los fallos, no solo el primero: Claude corrige la traducción entera de una vez.
    """
    if not isinstance(traduccion, list):
        return ["`cues` no es una lista"]
    fallos = []
    if len(traduccion) != len(origen):
        fallos.append(f"la traducción tiene {len(traduccion)} cues y el .srt de origen {len(origen)}")
    for posicion, (o, t) in enumerate(zip(origen, traduccion), start=1):
        if not isinstance(t, dict):
            fallos.append(f"el cue {posicion} no es un objeto")
            continue
        if t.get("n") != o["n"]:
            fallos.append(f"el cue {posicion} lleva el número {t.get('n')!r} y en el origen es el {o['n']}")
        if (t.get("inicio"), t.get("fin")) != (o["inicio"], o["fin"]):
            fallos.append(
                f"el cue {o['n']} va de {t.get('inicio')} a {t.get('fin')} y en el origen de {o['inicio']} a "
                f"{o['fin']}: los tiempos no se tocan"
            )
        texto = t.get("texto")
        if not isinstance(texto, str) or not texto.strip():
            fallos.append(f"el cue {o['n']} no tiene texto")
            continue
        lineas = texto.strip().split("\n")
        if len(lineas) > MAX_LINEAS:
            fallos.append(f"el cue {o['n']} tiene {len(lineas)} líneas y caben {MAX_LINEAS}")
        for linea in lineas:
            if not linea.strip():
                fallos.append(f"el cue {o['n']} tiene una línea vacía")
            elif len(linea.strip()) > limite:
                fallos.append(
                    f"una línea del cue {o['n']} mide {len(linea.strip())} caracteres y caben {limite}: "
                    f"«{linea.strip()}». Pártela en dos con \\n"
                )
    if (
        origen
        and len(traduccion) == len(origen)
        and all(
            isinstance(t, dict) and str(t.get("texto", "")).strip() == o["texto"].strip()
            for o, t in zip(origen, traduccion)
        )
    ):
        fallos.append("ningún cue cambia respecto al origen: esto no está traducido")
    return fallos


def _registros_por_idioma(run_dir: str | Path) -> dict[str, dict]:
    """El último registro de traducción de cada idioma del run."""
    ruta = Path(run_dir) / provenance.TRANSLATION_RECORDS_FILENAME
    if not ruta.exists():
        return {}
    fuera: dict[str, dict] = {}
    for r in provenance.lee_registro_o_aparta(ruta):
        if isinstance(r, dict) and r.get("idioma"):
            fuera[str(r["idioma"])] = r
    return fuera


def escribe(
    run_dir: str | Path,
    perfil: dict,
    *,
    run_id: str,
    idioma: str,
    origen: str,
    idioma_de_la_declaracion: str,
    traduccion: str | Path,
) -> dict:
    """Comprueba la traducción de Claude y escribe `subtitulos.<idioma>.srt` con los tiempos del de origen.

    No escribe nada si algo falla. Si sale bien, registra su procedencia y vuelve a sincronizar `assets.json` (con su
    copia en git, como hacen las etapas).
    """
    from lib.publicacion import nombre_del_idioma

    declarados = subtitulos.traducciones(perfil, origen=origen)
    if idioma not in declarados:
        raise ErrorDeTraduccion(
            f"el canal no traduce su .srt a «{idioma}»: perfil.json → subtitulos.traducciones = {declarados!r}. Si "
            "debe hacerlo, se declara allí primero."
        )
    # La declaración de IA tiene que saber nombrar los dos idiomas; se comprueba aquí y no al subir.
    try:
        nombre_del_idioma(idioma, idioma_de_la_declaracion)
        nombre_del_idioma(origen, idioma_de_la_declaracion)
    except ValueError as error:
        raise ErrorDeTraduccion(str(error)) from None

    srt = srt_de_origen(run_dir, origen)
    cues = _cues_de_origen(srt)
    sha_origen = _sha256(srt)
    try:
        datos = json.loads(Path(traduccion).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ErrorDeTraduccion(f"no se puede leer la traducción {traduccion}: {error}") from None
    if not isinstance(datos, dict):
        raise ErrorDeTraduccion(f"la traducción {traduccion} no es el JSON que saca `saca`")
    sha_sacado = (datos.get("origen") or {}).get("sha256")
    if sha_sacado != sha_origen:
        raise ErrorDeTraduccion(
            f"el .srt de origen ({srt.name}) ha cambiado desde que se sacaron sus cues, o la traducción no dice de "
            "cuál sale: vuelve a sacarlos con `saca` y tradúcelos otra vez"
        )
    fallos = comprueba(cues, datos.get("cues"), limite=limite_de_linea(perfil))
    if fallos:
        raise ErrorDeTraduccion(f"la traducción a «{idioma}» no se escribe:\n  - " + "\n  - ".join(fallos))

    destino = srt_traducido(run_dir, idioma)
    destino.parent.mkdir(parents=True, exist_ok=True)
    traducidos = [
        {**o, "texto": "\n".join(linea.strip() for linea in t["texto"].strip().split("\n"))}
        for o, t in zip(cues, datos["cues"])
    ]
    try:
        subtitulos.escribe_cues(traducidos, destino)
    except subtitulos.SubtitulosError as error:
        raise ErrorDeTraduccion(str(error)) from None

    registro = {
        "file": str(destino),
        "idioma": idioma,
        "idioma_origen": origen,
        "traducido_de": provenance.asset_id(Path(run_dir), srt),
        "sha256_origen": sha_origen,
        "sha256": _sha256(destino),
        "cues": len(traducidos),
        "traductor": TRADUCTOR,
        "licencia": LICENCIA,
        "origen": ORIGEN,
        "tiempos": "los del .srt de origen, copiados sin tocar",
    }
    sidecar = Path(run_dir) / provenance.TRANSLATION_RECORDS_FILENAME
    provenance.quita_registros(sidecar, [destino])
    provenance.anade_registros(sidecar, [registro])
    informe = provenance.sync(run_dir, run_id=run_id, etapa="traducción del .srt")
    return {"srt": destino, "cues": len(traducidos), "registro": registro, "conteo": informe}


def exige_al_dia(run_dir: str | Path, perfil: dict, *, origen: str) -> list[Path]:
    """Los `.srt` que el usuario adjunta a mano en Studio, si todos están al día. Para si no, ANTES de gastar cuota.

    Para si falta una traducción que el canal declara, si el `.srt` de origen no es el que se tradujo, si una traducción
    ha cambiado desde que se escribió, o si en la carpeta hay un `.srt` en un idioma que el canal no declara. Un canal
    sin traducciones devuelve solo el de origen, si lo hay: es la subida de siempre.
    """
    idiomas = subtitulos.traducciones(perfil, origen=origen)
    de_origen = srt_de_origen(run_dir, origen)
    carpeta = config.dir_subir_al_canal(run_dir)
    presentes = sorted(carpeta.glob("subtitulos.*.srt")) if carpeta.is_dir() else []
    sobran = [p.name for p in presentes if p.name.split(".")[1] not in {origen, *idiomas}]
    if sobran:
        raise ErrorDeTraduccion(
            f"en {config.DIR_SUBIR_AL_CANAL}/ hay subtítulos en idiomas que el canal no declara ({', '.join(sobran)}; "
            f"perfil.json → subtitulos.traducciones = {idiomas!r}). Bórralos o declara el idioma: no se sube nada."
        )
    if not idiomas:
        return [de_origen] if de_origen.is_file() else []
    if not de_origen.is_file():
        raise ErrorDeTraduccion(
            f"el canal traduce su .srt a {idiomas!r} y el run no tiene el de origen ({de_origen.name}): falta la etapa "
            "alinea. No se sube nada."
        )
    sha = _sha256(de_origen)
    registros = _registros_por_idioma(run_dir)
    fallos = []
    for idioma in idiomas:
        destino = srt_traducido(run_dir, idioma)
        registro = registros.get(idioma)
        if not destino.is_file() or registro is None:
            fallos.append(
                f"falta la traducción a «{idioma}» ({destino.name}): sácala y escríbela con scripts/traduce_srt.py"
            )
        elif registro.get("sha256_origen") != sha:
            fallos.append(
                f"{de_origen.name} ha cambiado desde que se tradujo a «{idioma}»: vuelve a sacar sus cues y a "
                "traducirlos"
            )
        elif _sha256(destino) != registro.get("sha256"):
            fallos.append(
                f"{destino.name} ha cambiado desde que se escribió, así que su registro ya no dice quién lo hizo: "
                "vuelve a escribirlo con scripts/traduce_srt.py escribe"
            )
    if fallos:
        raise ErrorDeTraduccion("no se sube nada, y no se ha gastado cuota:\n  - " + "\n  - ".join(fallos))
    return [de_origen, *(srt_traducido(run_dir, i) for i in idiomas)]
