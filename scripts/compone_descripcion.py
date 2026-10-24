"""Compone la descripción final de un vídeo: capítulos con tiempos reales y bibliografía verificada.

Correr:  .venv\\Scripts\\python scripts/compone_descripcion.py --run-id <run_id> --fichas <id> [<id>...]

## Por qué existe

El `slides.json` que sale del gate 1 no puede traer ni los capítulos ni las citas ya escritos, y
son dos motivos distintos:

- **Los capítulos necesitan el minutaje real**, y ese no se sabe hasta que el audio está generado y
  el montaje planificado. Escribirlos antes es inventarlos.
- **Las citas no se teclean nunca.** Es el principio del módulo de fuentes: una cita que no resuelve,
  no existe. Aquí se toman de `fuentes.py --bibliografia`, que las lee de las fichas verificadas, y
  se copian tal cual salen.

Así que quien escribe el guion deja dos marcadores en `description` —`<<CAPITULOS>>` y
`<<BIBLIOGRAFIA>>`— y este script los sustituye antes de la subida.

## De dónde salen los tiempos

De `<run>/montaje.json -> detalle`, que es el plan real del vídeo: cada plano trae su `slide` y sus
`segundos`. El inicio de un slide es la suma de los planos anteriores. **Las transiciones no
desplazan el reloj**: medido sobre el run del 27-08, la suma de los planos da 105,336 s contra los
105,333 s de `duracion_s`, o sea 3 milésimas de redondeo.

No se suman las duraciones de los WAV a mano: el montaje es quien decide, y si algún día una etapa
mete un plano de más, esa cuenta se enteraría y la de los audios no.

## La única traducción que hace este script, y por qué no rompe la regla

`fuentes.py` emite sus ETIQUETAS FIJAS en español —el encabezado de las citas y la línea de cierre—
y un canal puede narrar en inglés, así que publicar su salida entera metería español en la
descripción de un vídeo inglés. Lo que se traduce son **las etiquetas del generador**, que están en
la tabla `ETIQUETAS` de aquí abajo. **Las citas se copian byte a byte** y el nombre de cada ficha
sale de su propio campo (`nombre_en` / `nombre_es`), no de una traducción.

La línea `[AVISO, no publicar esta línea]` se descarta, que es para lo que está marcada, pero se
imprime en consola: es información para quien prepara la descripción.

## La descripción traducida (fila 285)

Si el canal declara `perfil.json → publicacion.metadatos_traducidos`, cada `description_<idioma>` del `slides.json` se
compone igual y con el mismo minutaje. Los títulos de sus capítulos tampoco se traducen aquí: los escribe el guionista
en `capitulos[].titulo_<idioma>`. De este script solo salen, en ese idioma, los rótulos de `ETIQUETAS` y el nombre de
cada ficha.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import BASE_DIR, CANAL_DATOS_DIR, CANAL_PERFIL, CANAL_VIDEOS_DIR, NARRATION_LANG  # noqa: E402
from lib.publicacion import (  # noqa: E402
    ErrorDeMetadatos,
    campo_traducido,
    faltan_metadatos,
    idiomas_de_los_metadatos,
)

# Etiquetas fijas del bloque, por idioma de narración del canal. No son contenido: son rótulos.
ETIQUETAS = {
    "es": {
        "capitulos": "Capítulos",
        "fuentes": "Fuentes",
        "pie": "Las fuentes citadas se han verificado una a una contra el registro de su editor o archivo.",
    },
    "en": {
        "capitulos": "Chapters",
        "fuentes": "Sources",
        "pie": (
            "Every source listed here was resolved and checked one by one against the publisher "
            "or archive record it comes from."
        ),
    },
}

# YouTube solo activa los capítulos si hay al menos tres, el primero empieza en 00:00 y ninguno
# dura menos de diez segundos. Son sus reglas, no un criterio de este proyecto.
MINIMO_CAPITULOS = 3
MINIMO_SEGUNDOS_CAPITULO = 10.0

MARCA_AVISO_INTERNO = "[AVISO, no publicar esta línea]"


def _reloj(segundos: float) -> str:
    """Formatea para YouTube: `MM:SS` o `H:MM:SS` cuando el vídeo pasa de la hora."""
    total = int(round(segundos))
    horas, resto = divmod(total, 3600)
    minutos, segs = divmod(resto, 60)
    if horas:
        return f"{horas}:{minutos:02d}:{segs:02d}"
    return f"{minutos:02d}:{segs:02d}"


def inicios_por_slide(montaje: dict) -> dict[int, float]:
    """Segundo en el que empieza cada slide, derivado del plan de montaje.

    Si el montaje dice dónde empieza cada plano (`inicio_s`), manda eso: es el caso del motor de escena (F6.2d),
    donde entre lámina y lámina hay pausas que ningún plano cubre, y sumar los planos anteriores daría un inicio
    falso. El montaje de siempre no lo trae y sus planos van pegados: se suman, como siempre.
    """
    planos = sorted(montaje["detalle"], key=lambda p: p["plano"])
    inicios: dict[int, float] = {}
    if planos and all("inicio_s" in plano for plano in planos):
        for plano in planos:
            inicios.setdefault(int(plano["slide"]), float(plano["inicio_s"]))
        return inicios
    reloj = 0.0
    for plano in planos:
        slide = int(plano["slide"])
        if slide not in inicios:
            inicios[slide] = reloj
        reloj += float(plano["segundos"])
    return inicios


def bloque_capitulos(capitulos: list[dict], inicios: dict[int, float], idioma: str) -> tuple[str, list[str]]:
    """Devuelve el bloque de capítulos y los avisos que haya que decir en voz alta."""
    avisos: list[str] = []
    if len(capitulos) < MINIMO_CAPITULOS:
        raise SystemExit(
            f"[FAIL] {len(capitulos)} capítulo(s): YouTube necesita al menos {MINIMO_CAPITULOS} "
            "para activarlos, así que con menos no se ven."
        )

    lineas = [ETIQUETAS[idioma]["capitulos"]]
    marcas: list[float] = []
    for indice, capitulo in enumerate(capitulos):
        slide = int(capitulo["slide_inicial"])
        if slide not in inicios:
            raise SystemExit(
                f"[FAIL] el capítulo «{capitulo['titulo']}» arranca en el slide {slide}, que no existe en el montaje."
            )
        # El primero SIEMPRE en 00:00: YouTube descarta la lista entera si no.
        inicio = 0.0 if indice == 0 else inicios[slide]
        marcas.append(inicio)
        lineas.append(f"{_reloj(inicio)} {capitulo['titulo']}")

    for indice in range(1, len(marcas)):
        hueco = marcas[indice] - marcas[indice - 1]
        if hueco < MINIMO_SEGUNDOS_CAPITULO:
            avisos.append(
                f"el capítulo «{capitulos[indice]['titulo']}» empieza {hueco:.1f} s después del "
                f"anterior y YouTube pide {MINIMO_SEGUNDOS_CAPITULO:.0f} s: no los activará"
            )
    if marcas != sorted(marcas):
        raise SystemExit("[FAIL] los capítulos no van en orden creciente de tiempo.")

    return "\n".join(lineas), avisos


def _lanza_fuentes(fichas: list[str]) -> str:
    """Llama a `fuentes.py --bibliografia` y devuelve su salida cruda."""
    entorno = dict(os.environ, PYTHONIOENCODING="utf-8")
    proceso = subprocess.run(
        [sys.executable, str(BASE_DIR / "fuentes.py"), "--bibliografia", *fichas],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=entorno,
        cwd=str(BASE_DIR),
    )
    if proceso.returncode != 0:
        raise SystemExit(f"[FAIL] fuentes.py salió con {proceso.returncode}:\n{proceso.stdout}\n{proceso.stderr}")
    return proceso.stdout


def bloque_bibliografia(fichas: list[str], idioma: str) -> tuple[str, list[str], list[str]]:
    """Extrae SOLO las citas de la salida de `fuentes.py`, con el nombre de cada ficha en su idioma.

    Devuelve el bloque, los disclaimers que hay que decir en el vídeo y los avisos internos.

    **Un canal SIN fichas no tiene bibliografía que componer, y eso no es un caso raro**: un canal de
    ficción didáctica y declara `nicho.sin_fuentes_verificadas`. Hasta el 15-09 esto no se notaba
    porque su descripción tampoco traía marcadores, así que el componedor ni se lanzaba; en cuanto
    se le activaron los capítulos, la subida murió con `fuentes.py: error: argument --bibliografia:
    expected at least one argument`. Sin fichas se devuelve el bloque vacío **sin lanzar el
    proceso**: preguntar por las citas de una lista vacía no tiene respuesta que valga.
    """
    if not fichas:
        return "", [], []
    crudo = _lanza_fuentes(fichas)
    avisos = [linea.strip() for linea in crudo.splitlines() if MARCA_AVISO_INTERNO in linea]

    # Las citas son las líneas indentadas que van bajo un encabezado «— Nombre (Nombre) —».
    citas_por_ficha: list[list[str]] = []
    dentro = False
    for linea in crudo.splitlines():
        limpia = linea.rstrip("\r")
        if limpia.startswith("—") and limpia.rstrip().endswith("—"):
            dentro = True
            citas_por_ficha.append([])
            continue
        if dentro:
            if limpia.startswith("  ") and limpia.strip():
                citas_por_ficha[-1].append(limpia.strip())
            elif not limpia.strip():
                continue
            else:
                dentro = False

    if len(citas_por_ficha) != len(fichas):
        raise SystemExit(
            f"[FAIL] se esperaban {len(fichas)} bloques de citas y se encontraron {len(citas_por_ficha)}. "
            "El formato de fuentes.py ha cambiado y este script lo estaría leyendo mal."
        )

    lineas = [ETIQUETAS[idioma]["fuentes"]]
    disclaimers: list[str] = []
    for ficha_id, citas in zip(fichas, citas_por_ficha):
        datos = json.loads((CANAL_DATOS_DIR / "fuentes" / f"{ficha_id}.json").read_text(encoding="utf-8"))
        nombre = datos.get("nombre_en") if idioma == "en" else datos.get("nombre_es")
        lineas.append("")
        lineas.append(f"— {nombre or ficha_id} —")
        lineas.extend(f"  {cita}" for cita in citas)
        if (datos.get("disclaimer") or "").strip():
            disclaimers.append(f"{ficha_id}: {datos['disclaimer'].strip()}")
        if not citas:
            raise SystemExit(f"[FAIL] la ficha {ficha_id} no aportó ninguna cita.")

    lineas.append("")
    lineas.append(ETIQUETAS[idioma]["pie"])
    return "\n".join(lineas), disclaimers, avisos


CLAVE_FICHAS = "fuentes"


def fichas_del_guion(slides_json: dict) -> list[str]:
    """Los ids de ficha con los que se escribió el guion, o `[]` si no los declara.

    **Es del GUION y no del canal** (F4.9 no aplica al revés: no es una decisión de identidad sino de
    episodio): el canal tiene once fichas y cada vídeo cita las suyas. Quien lo sabe es quien escribió
    el guion en el gate 1, así que aquí se lee y no se deduce — deducirlo sería publicar una
    bibliografía que nadie eligió.
    """
    valor = slides_json.get(CLAVE_FICHAS) or []
    if isinstance(valor, str):
        valor = [valor]
    return [str(f).strip() for f in valor if str(f).strip()]


MARCADORES = ("<<CAPITULOS>>", "<<BIBLIOGRAFIA>>")


def _pendiente(descripcion: str) -> bool:
    """¿Le queda algún marcador por sustituir?"""
    return any(m in descripcion for m in MARCADORES)


def _bloques(descripcion: str, idioma: str) -> set[str]:
    """Qué bloques lleva una descripción: por su marcador si está sin componer, o por su rótulo si ya se compuso.

    El rótulo hace falta para comparar una descripción traducida con la original cuando la original ya se compuso, que
    es el caso de un run subido antes de la fila 285. Los rótulos son de `ETIQUETAS` y solo los escribe este script.
    """
    rotulos = ETIQUETAS[idioma]
    fuera = set()
    if "<<CAPITULOS>>" in descripcion or f"{rotulos['capitulos']}\n00:00 " in descripcion:
        fuera.add("<<CAPITULOS>>")
    if "<<BIBLIOGRAFIA>>" in descripcion or rotulos["pie"] in descripcion:
        fuera.add("<<BIBLIOGRAFIA>>")
    return fuera


def _sustituye(descripcion: str, capitulos: str, bibliografia: str) -> str:
    final = descripcion.replace("<<CAPITULOS>>", capitulos).replace("<<BIBLIOGRAFIA>>", bibliografia)
    if re.search(r"<<[A-Z_]+>>", final):
        raise RuntimeError("quedan marcadores sin sustituir en la descripción.")
    return final


def _exige_las_traducidas(slides_json: dict, traducidos: list[str], idioma: str, fichas: list[str]) -> None:
    """Para, sin escribir nada, si una descripción traducida no puede componerse igual que la original (fila 285).

    Tiene que traer sus tres campos, llevar los mismos bloques que la original —un marcador olvidado la dejaría sin
    capítulos o sin fuentes, y nadie lo vería— y tener fichas si pide bibliografía.
    """
    fallos = faltan_metadatos(slides_json, traducidos)
    original = _bloques(slides_json.get("description", ""), idioma)
    for destino in traducidos:
        if destino not in ETIQUETAS:
            fallos.append(f"este script no tiene los rótulos de la descripción en «{destino}»: añádelos a ETIQUETAS")
            continue
        texto = slides_json.get(campo_traducido("description", destino)) or ""
        if not texto.strip():
            continue  # ya lo dice `faltan_metadatos`
        suyos = _bloques(texto, destino)
        if suyos != original:
            fallos.append(
                f"`{campo_traducido('description', destino)}` lleva {sorted(suyos) or 'ningún marcador'} y "
                f"`description` {sorted(original) or 'ninguno'}: tienen que llevar los mismos"
            )
        if "<<BIBLIOGRAFIA>>" in texto and not fichas:
            fallos.append(
                f"`{campo_traducido('description', destino)}` lleva `<<BIBLIOGRAFIA>>` y el guion no declara `fuentes`"
            )
    if fallos:
        raise ErrorDeMetadatos("la descripción traducida no se compone:\n  - " + "\n  - ".join(fallos))


def compon(run_id: str, fichas: list[str], *, traducidos: list[str]) -> dict:
    """Sustituye `<<CAPITULOS>>` y `<<BIBLIOGRAFIA>>` en la descripción del `slides.json` y en sus traducciones.

    **Es idempotente**: si la descripción ya está compuesta devuelve `compuesta: False` en vez de
    fallar, porque la llama `stage_upload` y esa etapa se relanza (un reintento de subida no puede
    morir por haber compuesto bien la primera vez).

    `traducidos` son los idiomas de `perfil.json → publicacion.metadatos_traducidos` (fila 285), y es obligatorio para
    que quien llama no se olvide de ellos: `[]` si el canal no traduce. Cada `description_<idioma>` se compone con el
    MISMO minutaje que la original, los `capitulos[].titulo_<idioma>` y la bibliografía con los rótulos y el nombre de
    cada ficha en ese idioma. Se compone aunque la original ya lo esté: así se rehace el LEEME de un run ya subido.

    Los capítulos salen de `montaje.json`, que es el plan real del vídeo, así que el montaje tiene que
    estar hecho. Devuelve lo medido y los avisos para que el llamador los imprima.
    """
    idioma = NARRATION_LANG if NARRATION_LANG in ETIQUETAS else "en"
    run_dir = CANAL_VIDEOS_DIR / run_id
    slides_path = run_dir / "slides.json"
    montaje_path = run_dir / "montaje.json"

    for ruta in (slides_path, montaje_path):
        if not ruta.exists():
            raise RuntimeError(f"falta {ruta}. El montaje tiene que estar hecho: los capítulos salen de él.")

    slides_json = json.loads(slides_path.read_text(encoding="utf-8"))
    montaje = json.loads(montaje_path.read_text(encoding="utf-8"))
    descripcion = slides_json.get("description", "")

    _exige_las_traducidas(slides_json, traducidos, idioma, fichas)
    por_traducir = [i for i in traducidos if _pendiente(slides_json[campo_traducido("description", i)])]
    medido: dict = {"compuesta": False, "motivo": "la descripción ya estaba compuesta", "caracteres": len(descripcion)}
    if not _pendiente(descripcion) and not por_traducir:
        return {**medido, "traducidas": {}}

    capitulos = slides_json.get("capitulos") or []
    inicios = inicios_por_slide(montaje)
    if _pendiente(descripcion):
        texto_capitulos, avisos_capitulos = bloque_capitulos(capitulos, inicios, idioma)
        texto_biblio, disclaimers, avisos_internos = bloque_bibliografia(fichas, idioma)
        final = _sustituye(descripcion, texto_capitulos, texto_biblio)
        slides_json["description"] = final
        medido = {
            "compuesta": True,
            "caracteres": len(final),
            "duracion_s": montaje["duracion_s"],
            "laminas": len(inicios),
            "capitulos": len(capitulos),
            "texto_capitulos": texto_capitulos,
            "avisos": avisos_capitulos,
            "avisos_internos": avisos_internos,
            "disclaimers": disclaimers,
        }

    # Los avisos de la traducción son los mismos que los de la original (los mismos tiempos, las mismas fichas): no se
    # devuelven otra vez.
    medido["traducidas"] = {}
    for destino in por_traducir:
        clave = campo_traducido("titulo", destino)
        suyos = [{"slide_inicial": c["slide_inicial"], "titulo": c[clave]} for c in capitulos]
        texto_capitulos, _ = bloque_capitulos(suyos, inicios, destino)
        texto_biblio, _, _ = bloque_bibliografia(fichas, destino)
        final = _sustituye(slides_json[campo_traducido("description", destino)], texto_capitulos, texto_biblio)
        slides_json[campo_traducido("description", destino)] = final
        medido["traducidas"][destino] = {"caracteres": len(final), "texto_capitulos": texto_capitulos}

    slides_path.write_text(json.dumps(slides_json, ensure_ascii=False, indent=1), encoding="utf-8")
    return medido


def main() -> int:
    parser = argparse.ArgumentParser(description="Compone la descripción final de un run")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fichas", nargs="+", metavar="FICHA", help="por defecto, las de `slides.json → fuentes`")
    parser.add_argument("--dry-run", action="store_true", help="enseña el resultado sin tocar el slides.json")
    args = parser.parse_args()

    slides_path = CANAL_VIDEOS_DIR / args.run_id / "slides.json"
    if not slides_path.exists():
        raise SystemExit(f"[FAIL] falta {slides_path}")
    fichas = args.fichas or fichas_del_guion(json.loads(slides_path.read_text(encoding="utf-8")))
    if not fichas:
        raise SystemExit(
            f"[FAIL] ni `--fichas` ni `slides.json → {CLAVE_FICHAS}`: la bibliografía sale de las fichas "
            "con las que se escribió el guion y no se deduce."
        )

    traducidos = idiomas_de_los_metadatos(CANAL_PERFIL, origen=NARRATION_LANG)
    if args.dry_run:
        antes = slides_path.read_text(encoding="utf-8")
        try:
            medido = compon(args.run_id, fichas, traducidos=traducidos)
        finally:
            slides_path.write_text(antes, encoding="utf-8")
        print("--- dry-run: el slides.json se ha dejado como estaba ---")
    else:
        medido = compon(args.run_id, fichas, traducidos=traducidos)

    for idioma, suyo in medido["traducidas"].items():
        print(f"Descripción en «{idioma}» compuesta: {suyo['caracteres']} caracteres\n")
        print(suyo["texto_capitulos"])
        print()
    if not medido["compuesta"]:
        print(f"[OK] la original, nada que hacer: {medido['motivo']} ({medido['caracteres']} caracteres)")
        return 0

    print(f"Run: {args.run_id}")
    print(
        f"Duración del montaje: {medido['duracion_s']:.1f} s · {medido['laminas']} láminas · "
        f"{medido['capitulos']} capítulos"
    )
    print(f"Descripción compuesta: {medido['caracteres']} caracteres\n")
    print("--- capítulos ---")
    print(medido["texto_capitulos"])
    print()

    for aviso in medido["avisos"]:
        print(f"[AVISO] {aviso}")
    for aviso in medido["avisos_internos"]:
        print(f"[INTERNO, no se publica] {aviso}")
    for disclaimer in medido["disclaimers"]:
        print(f"[DISCLAIMER de ficha — comprueba que el GUION lo dice en los primeros 30 s] {disclaimer}")
    print(f"\n[OK] {slides_path} actualizado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
