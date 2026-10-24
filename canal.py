#!/usr/bin/env python3
r"""La identidad del canal: genera banner, avatar y marca de agua, y guía lo que la API no permite.

    .venv\Scripts\python canal.py                      # el checklist: qué hay hecho y qué falta
    .venv\Scripts\python canal.py --generar            # los tres assets, medidos y con procedencia
    .venv\Scripts\python canal.py --comprobar          # re-mide lo que hay en disco, sin generar
    .venv\Scripts\python canal.py --checklist --contra-el-canal   # + lo que se ve del canal (1 unidad)
    .venv\Scripts\python canal.py --textos             # descripción y palabras clave para pegar

Y un canal nuevo, mínimo: su `perfil.json` con las decisiones obligatorias y nada más (OC1.4). Lo que le falta para
producir lo dice después `scripts/comprueba_canal.py --canal <id>`:

    .venv\Scripts\python canal.py --nuevo everyday-inventions --imagen.modelo qwen-2512-lightning-tinta ^
        --imagen.seed 2026 --voz.receta voz-orpheus-everyday-inventions.json --idioma.narracion en ^
        --idioma.subtitulos en --publicacion.hecho_para_ninos false --publicacion.categoria_youtube 27 ^
        --musica.activa true --subtitulos.activos true --formato laminas

Y lo que **lanza el usuario**, no el pipeline, porque se ve en el canal en cuanto responde 200:

    .venv\Scripts\python canal.py --subir-marca-de-agua --confirmo
    .venv\Scripts\python canal.py --subir-banner --confirmo

## Por qué existe este punto de entrada y no una etapa de `pipeline.py`

`pipeline.py` orquesta **un run**, o sea un vídeo: sus etapas se identifican por `--run-id` y su
estado vive en `canales/<id>/datos/estado/<run>.json`. La identidad del canal no es de un
vídeo — es de todos a la vez y se genera una vez —, así que colgarla de un run obligaría a
inventar un run falso para producirla.
Va donde van las herramientas de canal: al lado de `fuentes.py` y `metricas.py`.

## La regla que gobierna este archivo

**Generar y medir es del código; tocar el canal público es del usuario.** Los dos comandos de subida
existen, están escritos y funcionan a un solo paso, pero piden `--confirmo` y **ningún agente los
ejecuta**: un banner o una marca de agua se ven en cuanto la API responde, y de eso no hay borrador
privado. Es el mismo reparto del gate 2, por el mismo motivo.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path

from lib import canal_marca, lineas_rojas, provenance
from lib.config import (
    CANAL_ACTIVO,
    CANAL_ERROR,
    CANAL_PERFIL,
    CANALES_DIR,
    DECISIONES_OBLIGATORIAS,
    INTERRUPTORES,
    NOMBRE_DEL_TIPO,
    problemas_del_perfil,
)
from lib.cuota import QuotaLedger
from lib.escena.ajustes import FORMATO_SIN_BLOQUE, FORMATOS

# `abre()` es del estudio: una sola forma de abrir cosas en el proyecto, en vez de un segundo
# `os.startfile` escrito aquí (vivía en el panel del descubrimiento hasta F5.12).
from lib.pagina_local import abre
from lib.youtube_client import CATEGORY_NAMES


def _lee_informe(destino: Path) -> dict:
    ruta = destino / canal_marca.INFORME
    if not ruta.exists():
        return {}
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def genera(destino: Path, seed: int | None, rehacer: bool, fuente: Path) -> dict:
    """Genera los tres assets, los mide y los deja con su procedencia en `assets.json`.

    `fuente` es la del banner, ya comprobada antes de llegar aquí (`canal_marca.fuente_del_banner`): sin ella el texto
    no se podría componer, y descubrirlo después de la GPU sería tirarla.
    """
    if rehacer:
        # Solo lo de ESTE directorio, que es nuestro. `generate_images_batch` salta lo que ya existe
        # —así se reanuda un lote a medias—, así que sin borrar las bases no se regenera nada.
        # `rglob`, no `glob`: desde que los PNG viven en subcarpetas, `glob("*.png")` no encontraba
        # ninguno y `--rehacer` solo borraba el registro de procedencia. O sea que el comando que
        # `_sube()` recomienda para REPARAR la procedencia la tiraba y no regeneraba nada.
        for viejo in sorted(destino.rglob("*.png")) + [destino / provenance.IMAGE_RECORDS_FILENAME]:
            viejo.unlink(missing_ok=True)
        print(f"  --rehacer: borrado lo que había en {destino}")

    print(f"[MARCA] Canal {CANAL_ACTIVO} · generando en {destino}")
    print("  las láminas base se generan EN SERIE (invariante de 8 GB de VRAM)")
    bases = canal_marca.genera_bases(CANAL_PERFIL, destino, seed=seed)

    marca_del_perfil = CANAL_PERFIL.get("marca") or {}
    textos = canal_marca.textos_del_canal(CANAL_PERFIL)
    try:
        # La letra del banner sale en una imagen que se publica, así que entra en la procedencia como las láminas.
        canal_marca.copia_fuente_del_banner(fuente, destino)
        banner = canal_marca.prepara_banner(
            bases["banner"],
            destino,
            textos["nombre"],
            textos["eslogan"] if (marca_del_perfil.get("banner") or {}).get("incluye_eslogan") else "",
            fuente=fuente,
        )
        avatar = canal_marca.prepara_avatar(bases["avatar"], destino, CANAL_PERFIL)
        # Cuando la marca de agua sale del avatar —el caso normal, porque ES el logo— se reutiliza su
        # MISMO recorte: así el emblema del canal y su marca de agua son el mismo encuadre, no dos
        # parecidos. Con escena propia en el perfil, cada uno se recorta por su cuenta.
        agua = canal_marca.prepara_marca_de_agua(
            bases["marca_de_agua"],
            destino,
            float((marca_del_perfil.get("marca_de_agua") or {}).get("opacidad") or 0.55),
            CANAL_PERFIL,
            recorte_previo=(
                (destino / canal_marca.AVATAR_RECORTADO) if bases["marca_de_agua"] == bases["avatar"] else None
            ),
        )
    finally:
        # En un `finally` por lo mismo que las etapas de `pipeline.py`: si algo revienta a mitad, lo
        # que sí se generó conserva su procedencia en vez de quedar como archivos huérfanos.
        procedencia = provenance.sync(
            destino, run_id=canal_marca.registro_id(), titulo="identidad del canal", etapa="marca"
        )

    print(f"  banner: reescalado {banner['reescalado']['de']} → {banner['reescalado']['a']}")
    for linea in banner["lineas"]:
        print(
            f"    [{linea['papel']}] {linea['texto']!r} · cuerpo {linea['cuerpo_px']} px · mayúscula "
            f"{linea['altura_mayuscula_px']} px (={linea['altura_mayuscula_en_movil']} px en móvil) · "
            f"contraste {linea['contraste_con_el_fondo']}:1"
        )
    if banner["banda_de_contraste"]:
        print(f"    banda de contraste aplicada al {banner['banda_de_contraste']:.0%}: el fondo real no llegaba")
    recorte = avatar["recorte"]
    if recorte["recortado"]:
        print(
            f"  avatar: el objeto ocupaba el {recorte['ocupacion_antes'] * 100:.1f} % del cuadro y "
            f"ahora el {recorte['ocupacion_despues'] * 100:.1f} %"
        )
    else:
        print(f"  avatar: NO se ha recortado — {recorte['por_que_no']}")
    alfa = agua["alfa"]
    print(
        f"  marca de agua: alfa máximo {alfa.get('alfa_maximo')} · medio {alfa.get('alfa_medio')} · "
        f"{alfa.get('transparente_pct')} % totalmente transparente"
    )

    # Se ARRANCA de lo que ya había, igual que `comprueba()`. Construir el diccionario desde cero
    # borraba `estado_del_canal`, que es **lo único de este informe que cuesta cuota**: lo lee
    # `channels.list` contra la API real. Con la versión anterior, cada `--generar` obligaba a gastar
    # otra unidad para recuperar un dato que ya se había pagado — la decisión 8 pagando dos veces por
    # lo mismo, y en silencio. Lo cazó la auditoría de F4.0 cuando una corrección mía regeneró el
    # fichero y dejó huérfana la dirección que citaba el informe.
    datos = _lee_informe(destino)
    datos.update(
        {
            "esquema": "marca/1.0",
            "canal": CANAL_ACTIVO,
            "generado": datetime.now().isoformat(timespec="seconds"),
            "seed": seed,
            "banner": banner,
            "avatar": avatar,
            "marca_de_agua": agua,
            "procedencia": procedencia,
        }
    )
    datos["verificacion"] = canal_marca.comprueba(destino, CANAL_PERFIL, datos)
    ruta = canal_marca.informe(datos, destino)
    print(f"  medido en {ruta}")
    return datos


def comprueba(destino: Path) -> dict:
    """Re-mide lo que hay en disco y actualiza el informe, sin tocar la GPU."""
    datos = _lee_informe(destino)
    veredicto = canal_marca.comprueba(destino, CANAL_PERFIL, datos)
    datos["verificacion"] = veredicto
    datos.setdefault("canal", CANAL_ACTIVO)
    datos["comprobado"] = datetime.now().isoformat(timespec="seconds")
    canal_marca.informe(datos, destino)

    for clave, medida in veredicto["assets"].items():
        if not medida["existe"]:
            print(f"  [FALTA]  {clave}: {destino / medida['ruta']}")
            continue
        peso = f"{medida['bytes']} B"
        if medida.get("limite_bytes"):
            peso += f" de {medida['limite_bytes']} B ({'cabe' if medida['dentro_del_limite'] else 'NO CABE'})"
        print(f"  [OK]     {clave}: {medida['tamano']} px · {medida['formato']} · {peso}")
    agua = veredicto["assets"].get("marca_de_agua") or {}
    if agua.get("existe"):
        a = agua["alfa"]
        print(
            f"  [ALFA]   marca de agua: máximo {a.get('alfa_maximo')} (<255 = semitransparente: "
            f"{a.get('semitransparente')})"
        )
    rojas = veredicto["lineas_rojas"]
    print(f"  [ROJAS]  {rojas['revisadas']} asset(s) revisados · pasa: {rojas['pasa']}")
    for aviso in veredicto["avisos_de_texto"]:
        print(f"  [AVISO]  {aviso}")
    for fallo in veredicto["fallos"]:
        print(f"  [FALLO]  {fallo}")
    return veredicto


def _perfil_listo() -> bool:
    if CANAL_ERROR:
        print(f"[FAIL] {CANAL_ERROR}")
        return False
    if not (CANAL_PERFIL.get("marca") or {}):
        print(
            "[FAIL] el perfil del canal no tiene bloque `marca`: ahí viven las escenas, la descripción y "
            "las palabras clave. Sin él no hay identidad que generar, y escribirla en lib/ sería meter "
            "el canal en la capa de estudio."
        )
        return False
    return True


# --- Un canal nuevo, mínimo (OC1.4) ------------------------------------------------------------------------------
# **No pregunta nada, a propósito.** La lanza Claude desde la skill `crea-canal`, y Claude no puede contestar a un
# `input()`. Recibe cada decisión obligatoria como una opción que se llama como su clave en el perfil
# (`--imagen.seed 2026`), y las lee del esquema de `lib/config.py`, que es donde están escritas una sola vez. Si falta
# alguna, si el id no vale o si el canal ya existe, se niega, lo dice todo junto y no crea nada.
#
# **El id es un slug**: minúsculas, cifras y guiones sueltos (`everyday-inventions`). Sin el prefijo numerado de los
# canales del estudio, que `tests/test_sin_estudio.py` da como fallo: el primer canal de un usuario no puede chocar con
# esa guarda (R2 de la revisión de OC1.1).
ID_DE_CANAL = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _convierte(texto: str, tipo: type):
    """El valor de una opción con el tipo que pide el esquema. `ValueError` si no encaja."""
    texto = texto.strip()
    if tipo is bool:
        if texto.lower() not in ("true", "false"):
            raise ValueError(texto)
        return texto.lower() == "true"
    if tipo is int:
        return int(texto)
    if not texto:
        raise ValueError(texto)
    return texto


def crea_canal(slug: str, valores: Mapping[str, str | None], canales_dir: Path) -> tuple[Path | None, list[str]]:
    """Crea `canales_dir/<slug>/perfil.json` con las decisiones obligatorias. Devuelve (carpeta, problemas).

    `valores` lleva el texto de cada decisión por su ruta (`"imagen.seed": "2026"`), los interruptores y `formato`.
    Con algún problema no escribe nada y la carpeta es None. El perfil que escribe cumple `problemas_del_perfil`.
    """
    problemas: list[str] = []
    if not ID_DE_CANAL.match(slug or ""):
        problemas.append(
            f"el id {slug!r} no vale: un canal se llama con un slug de minúsculas, cifras y guiones sueltos, "
            "por ejemplo everyday-inventions"
        )
    elif (canales_dir / slug).exists():
        problemas.append(f"ya existe {canales_dir / slug}: no se pisa un canal. Elige otro id")
    perfil: dict = {
        "_comentario": (
            "Canal creado con `canal.py --nuevo`: solo lleva las decisiones obligatorias del esquema "
            "(`lib/config.py → DECISIONES_OBLIGATORIAS` e `INTERRUPTORES`). Lo que le falta para producir lo dice "
            "`scripts/comprueba_canal.py --canal <id>`."
        ),
        "id": slug,
        "creado": date.today().isoformat(),
    }
    for ruta, (tipo, que, ejemplo) in {**DECISIONES_OBLIGATORIAS, **INTERRUPTORES}.items():
        texto = valores.get(ruta)
        if texto is None or not str(texto).strip():
            problemas.append(f"falta --{ruta}: {que}. Por ejemplo: --{ruta} {ejemplo}")
            continue
        try:
            valor = _convierte(str(texto), tipo)
        except ValueError:
            problemas.append(
                f"--{ruta} {texto!r} no vale: escribe {NOMBRE_DEL_TIPO[tipo]}, por ejemplo --{ruta} {ejemplo}"
            )
            continue
        if ruta == "publicacion.categoria_youtube" and valor not in CATEGORY_NAMES:
            problemas.append(
                f"--{ruta} {valor!r} no es una categoría de YouTube: escribe uno de estos ids, "
                + ", ".join(f"{k} ({n})" for k, n in CATEGORY_NAMES.items())
            )
            continue
        *bloques, clave = ruta.split(".")
        nodo = perfil
        for bloque in bloques:
            nodo = nodo.setdefault(bloque, {})
        nodo[clave] = valor
    formato = valores.get("formato")
    if formato not in FORMATOS:
        problemas.append(
            f"falta --formato: el formato del motor de escena en el que produce el canal, uno de {', '.join(FORMATOS)} "
            "(docs/formats.md). Por ejemplo: --formato laminas"
            if not formato
            else f"--formato {formato!r} no es un formato del catálogo: escribe uno de {', '.join(FORMATOS)}"
        )
    else:
        # Un bloque vacío dice el formato; su contenido lo exigen `lib/escena/ajustes.py` y el módulo del formato.
        perfil["escena"] = {} if formato == FORMATO_SIN_BLOQUE else {formato: {}}
    if not problemas:
        problemas = problemas_del_perfil(perfil)
    if problemas:
        return None, problemas
    carpeta = canales_dir / slug
    carpeta.mkdir(parents=True)
    (carpeta / "perfil.json").write_text(json.dumps(perfil, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return carpeta, []


def _nuevo(args: argparse.Namespace) -> int:
    valores = {ruta: getattr(args, ruta) for ruta in {**DECISIONES_OBLIGATORIAS, **INTERRUPTORES}}
    valores["formato"] = args.formato
    carpeta, problemas = crea_canal(args.nuevo, valores, CANALES_DIR)
    if problemas:
        print(f"[FAIL] no se crea el canal {args.nuevo!r}; no se ha escrito nada:")
        for problema in problemas:
            print(f"  - {problema}")
        return 2
    print(f"[OK] canal creado: {carpeta / 'perfil.json'}")
    print(f"  Lo que le falta para producir: .venv\\Scripts\\python scripts/comprueba_canal.py --canal {args.nuevo}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Identidad del canal: banner, avatar, marca de agua y checklist")
    parser.add_argument("--generar", action="store_true", help="genera los tres assets y los mide")
    parser.add_argument("--rehacer", action="store_true", help="con --generar: borra lo anterior y vuelve a generar")
    parser.add_argument("--seed", type=int, default=None, help="semilla de generación (por defecto, la del perfil)")
    parser.add_argument("--comprobar", action="store_true", help="re-mide lo que hay en disco, sin generar")
    parser.add_argument("--checklist", action="store_true", help="qué hace el código y qué tiene que hacer el usuario")
    parser.add_argument("--sin-abrir", action="store_true", help="no abrir la página en el navegador al terminar")
    parser.add_argument(
        "--contra-el-canal",
        action="store_true",
        help="con --checklist: lee del canal lo que se ve con la clave pública (cuesta 1 unidad de cuota)",
    )
    parser.add_argument("--textos", action="store_true", help="descripción y palabras clave del perfil, para pegar")
    parser.add_argument("--subir-marca-de-agua", action="store_true", help="watermarks.set — LO LANZA EL USUARIO")
    parser.add_argument("--subir-banner", action="store_true", help="channelBanners.insert — LO LANZA EL USUARIO")
    parser.add_argument("--confirmo", action="store_true", help="obligatorio para los dos comandos de subida")
    parser.add_argument(
        "--nuevo", metavar="ID", help="crea canales/<ID>/ con las decisiones obligatorias, sin preguntar"
    )
    for ruta, (_, que, ejemplo) in {**DECISIONES_OBLIGATORIAS, **INTERRUPTORES}.items():
        parser.add_argument(f"--{ruta}", metavar=ejemplo, help=f"con --nuevo: {que}")
    parser.add_argument(
        "--formato", metavar="laminas", help=f"con --nuevo: el formato de escena ({', '.join(FORMATOS)})"
    )
    args = parser.parse_args(argv)

    if args.nuevo is not None:
        return _nuevo(args)
    sueltas = [
        ruta for ruta in [*DECISIONES_OBLIGATORIAS, *INTERRUPTORES, "formato"] if getattr(args, ruta) is not None
    ]
    if sueltas:
        print(f"[FAIL] {', '.join('--' + s for s in sueltas)} solo valen con --nuevo <id>: no se ha hecho nada")
        return 2
    if not _perfil_listo():
        return 2

    destino = canal_marca.directorio()
    textos = canal_marca.textos_del_canal(CANAL_PERFIL)

    if args.textos:
        print(f"# Descripción del canal ({textos['descripcion_caracteres']}/{textos['descripcion_limite']} caracteres)")
        print(textos["descripcion"])
        print(
            f"\n# Palabras clave ({textos['palabras_clave_caracteres']}/{textos['palabras_clave_limite']} caracteres, "
            "tal como las cuenta YouTube)"
        )
        print(textos["palabras_clave_como_las_cuenta_youtube"])
        print("\n# Salen de canales/<id>/perfil.json → marca. Se pegan en Studio: channels.update no está en el scope.")
        return 0 if textos["descripcion_cabe"] and textos["palabras_clave_caben"] else 1

    if args.subir_marca_de_agua or args.subir_banner:
        return _sube(args, destino)

    veredicto = None
    if args.generar:
        try:
            fuente = canal_marca.fuente_del_banner(CANAL_PERFIL)
        except canal_marca.MarcaError as error:
            print(f"[FAIL] {error}")
            return 2
        datos = genera(destino, args.seed, args.rehacer, fuente)
        veredicto = datos["verificacion"]
        for fallo in veredicto["fallos"]:
            print(f"  [FALLO]  {fallo}")
        # Que la procedencia no cuadre NO es un aviso: la decisión cerrada 5 dice que un asset sin
        # origen demostrable no se publica, así que el comando termina en rojo aunque los PNG estén
        # bien. `--rehacer` reconstruye los assets y su registro a la vez, que es la salida.
        if not datos["procedencia"]["cuadra"]:
            veredicto = {**veredicto, "cumple": False}
        # La guarda de líneas rojas se lanza aparte del veredicto, y a propósito: su mensaje dice qué
        # lámina, con qué medida y en qué recuadro, que es lo que hace falta para arreglarlo.
        presentes = [destino / m["ruta"] for m in veredicto["assets"].values() if m["existe"]]
        if presentes:
            lineas_rojas.exige(presentes, etapa="marca")

    if args.comprobar:
        veredicto = comprueba(destino)

    if args.checklist or not (args.generar or args.comprobar):
        if veredicto is None:
            veredicto = canal_marca.comprueba(destino, CANAL_PERFIL, _lee_informe(destino))
        # Sin `--contra-el-canal` se usa **lo último que se leyó**, que ya está guardado y ya se pagó.
        # La primera versión lo tiraba y volvía a poner «sin comprobar» en todo, así que el dato que
        # `marca.json` conserva expresamente «para poder citarlo mañana» no se citaba nunca. Va con su
        # fecha: un estado de hace tres días no es mentira, es un estado de hace tres días.
        estado = (_lee_informe(destino) or {}).get("estado_del_canal")
        if estado and not args.contra_el_canal:
            print(f"  [CANAL] estado leído el {estado.get('leido_el', '?')} · --contra-el-canal para releerlo")
        if args.contra_el_canal:
            ledger = QuotaLedger()
            estado = canal_marca.estado_publico_del_canal(textos["canal_id"], ledger)
            print(f"  [CUOTA] {ledger.total_units} unidad(es) de la Data API v3 · sin reintentos (lista negra)")
            if not estado.get("leido"):
                print(f"  [CANAL] no se ha podido leer el canal: {estado.get('motivo')}")
            # Lo leído se guarda con su hora y su gasto: un «pendiente en el canal» que solo existe en
            # la consola de hoy no se puede citar mañana, y esto cuesta cuota cada vez que se mira.
            datos = _lee_informe(destino)
            if datos:
                datos["estado_del_canal"] = {
                    "leido_el": datetime.now().isoformat(timespec="seconds"),
                    "cuota": ledger.to_dict(),
                    **estado,
                }
                canal_marca.informe(datos, destino)
        lista = canal_marca.checklist(CANAL_PERFIL, veredicto, estado, destino)
        print(canal_marca.texto_del_checklist(lista))
        # Un checklist que manda a un archivo inexistente es peor que no tenerlo: se comprueba que
        # TODO lo que cita está en disco. No lo hace `canal_marca.comprueba()` porque el checklist
        # depende de ella y sería un ciclo. Ver el docstring de `rutas_que_no_existen`.
        fantasmas = canal_marca.rutas_que_no_existen(lista)
        if fantasmas:
            print("\n  [ERROR] el checklist cita archivos que NO existen:")
            for f in fantasmas:
                print(f"      {f}")
            print("      Es un bug del checklist, no del canal. No sigas sus instrucciones.")
            return 1
        # La pagina se regenera SIEMPRE, no con un flag: si hay que acordarse de pedirla, se queda
        # vieja y entonces miente — que es peor que no tenerla. Cuesta milisegundos.
        pagina = canal_marca.pagina_del_checklist(lista, CANAL_PERFIL, destino, _lee_informe(destino))
        print(f"\n  Para copiar y pegar, con las imagenes a la vista: {pagina}")
        print(f"  {pagina.as_uri()}")
        # Y SE ABRE SOLA, como las páginas del descubrimiento. Petición del 04-09: «cuando
        # tengas el html de la marca completo, abrelo siempre de forma automatica, para que yo no
        # tenga que buscar el html en los ficheros». Un entregable que hay que ir a buscar por el
        # arbol no es accesible aunque se abra con doble clic.
        if not args.sin_abrir and abre(pagina):
            print("  (abierto en el navegador)")

    return 0 if (veredicto is None or veredicto["cumple"]) else 1


def _sube(args, destino: Path) -> int:
    """Los dos comandos que tocan el canal público. Nunca los ejecuta un agente."""
    if not args.confirmo:
        print(
            "[PARA] esto se ve en el canal en cuanto la API responde 200, y no hay borrador privado de un\n"
            "       banner ni de una marca de agua. Añade --confirmo si eres el dueño del canal y quieres lanzarlo.\n"
            "       (La bandera existe para que ningún agente toque el canal público por reflejo.)"
        )
        return 2

    veredicto = canal_marca.comprueba(destino, CANAL_PERFIL, _lee_informe(destino))
    if not veredicto["cumple"]:
        print("[PARA] los assets no pasan la comprobación, así que no se sube nada:")
        for fallo in veredicto["fallos"]:
            print(f"   - {fallo}")
        print("       Arréglalo con `canal.py --generar --rehacer` y vuelve a intentarlo.")
        return 1

    # La misma guarda que la subida de un vídeo: un asset que no puede demostrar de dónde salió no se
    # publica (decisión cerrada 5). Aquí importa igual o más, porque el banner y la marca de agua se
    # ven en TODO el canal, no en un vídeo.
    try:
        provenance.require_complete(destino, run_id=canal_marca.registro_id(), titulo="identidad del canal")
    except provenance.ProvenanceError as exc:
        print(f"[PARA] {exc}")
        print("       Repite `canal.py --generar --rehacer`: reconstruye los assets y su procedencia a la vez.")
        return 1

    textos = canal_marca.textos_del_canal(CANAL_PERFIL)
    if args.subir_marca_de_agua:
        resultado = canal_marca.sube_marca_de_agua(destino / canal_marca.MARCA_DE_AGUA_FINAL, textos["canal_id"])
        print(f"[WATERMARK] HTTP {resultado['http']} · ok: {resultado['ok']}")
        if not resultado["ok"]:
            print(f"  respuesta: {resultado['respuesta']}")
            print(f"  {resultado['que_hace_falta_si_falla']}")
            return 1
        print("  puesta. Compruébalo en Studio → Personalización → Imagen de marca")
        return 0

    resultado = canal_marca.sube_banner(destino / canal_marca.BANNER_FINAL)
    print(f"[BANNER] HTTP {resultado['http']} · ok: {resultado['ok']}")
    print(f"  url devuelta: {resultado['url_del_banner'] or '(ninguna)'}")
    for pendiente in resultado["pendiente_a_mano"]:
        print(f"  [A MANO] {pendiente['que']}: {pendiente['por_que']}")
        print(f"           {pendiente['como']}")
    return 0 if resultado["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
