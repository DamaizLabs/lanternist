"""CLI del módulo de fuentes con autoridad (F2.9).

Mismo lugar y mismo estilo que `metricas.py` y `canal.py`: un comando por tarea, salida JSON
donde la salida importa, y nada de interfaz gráfica (la interfaz es la conversación).

    .venv\\Scripts\\python fuentes.py --nichos
    .venv\\Scripts\\python fuentes.py --buscar "pillory punishment England"
    .venv\\Scripts\\python fuentes.py --buscar "invention of the zipper" --nicho ejemplo-sin-cifras
    .venv\\Scripts\\python fuentes.py --verificar doi:10.1017/s0738248000004272 gbif:104790737
    .venv\\Scripts\\python fuentes.py --fichas

Las cifras de un nicho que las exige (F7.12, filas 273-275), en tres pasos:

    .venv\\Scripts\\python fuentes.py --verificar url:https://…/annual-report.pdf
    .venv\\Scripts\\python fuentes.py --guarda borrador.json
    .venv\\Scripts\\python fuentes.py --comprueba-cifras <ficha>      # descarga, busca y abre la página
    .venv\\Scripts\\python fuentes.py --confirma <ficha> <cifra>… --dijo "<palabras del usuario>"

`<ficha>` es el id de una ficha del canal activo o la ruta de un `.json`.

El nicho por defecto es el que declara el canal activo (`nicho.id` de su perfil), así que en el
uso normal no hay que nombrarlo. `--nicho` sirve para trabajar contra otro dominio — y es lo que
demuestra que el módulo no está atado al canal del MVP.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from lib.fuentes import base, cifras, ficha, registro, verificacion


def _proveedores(nicho: str | None) -> tuple[str, dict, list, list[dict]]:
    """Resuelve nicho → perfil → proveedores usables, con el motivo de cada exclusión."""
    elegido = nicho or registro.nicho_del_canal()
    if not elegido:
        raise base.FuentesError(
            "no se sabe con qué nicho trabajar: no hay canal activo y no se pasó --nicho. "
            f"Nichos con perfil: {registro.nichos_disponibles() or 'ninguno'}"
        )
    perfil = registro.carga_perfil(elegido)
    usables, excluidos = registro.proveedores_de(perfil)
    return elegido, perfil, usables, excluidos


def cmd_nichos() -> int:
    """Qué dominios sabe verificar el estudio, y con qué autoridades."""
    nichos = registro.nichos_disponibles()
    if not nichos:
        print(f"No hay perfiles de autoridad en {registro.AUTORIDADES_DIR}")
        return 1
    activo = registro.nicho_del_canal()
    print(f"Perfiles de autoridad en {registro.AUTORIDADES_DIR.relative_to(registro.AUTORIDADES_DIR.parent.parent)}:\n")
    for nombre in nichos:
        perfil = registro.carga_perfil(nombre)
        marca = "  <- del canal activo" if nombre == activo else ""
        print(f"  {nombre}{marca}")
        print(f"      proveedores: {', '.join(perfil['proveedores'])}")
        print(f"      jerarquía:   {' > '.join(perfil['jerarquia'])}")
        print(f"      obligatorios en la ficha: {', '.join(perfil['campos_obligatorios'])}")
        if perfil.get("es_prueba_de_universalidad"):
            print("      (perfil de prueba: existe para demostrar que un nicho nuevo es solo este JSON)")
    return 0


def cmd_buscar(consulta: str, nicho: str | None, limite: int, salida: str | None) -> int:
    elegido, perfil, proveedores, excluidos = _proveedores(nicho)
    ledger = base.LedgerLlamadas()
    print(f"Nicho {elegido!r} · {len(proveedores)} proveedor(es) · consulta: {consulta!r}\n")
    for entrada in excluidos:
        print(f"  (excluido {entrada['proveedor']}: {entrada['motivo']})")

    resultados: list[dict] = []
    for proveedor in proveedores:
        referencias = proveedor.busca(consulta, limite, ledger)
        print(f"  {proveedor.nombre:<12} {len(referencias)} resultado(s)")
        for referencia in referencias:
            autores = ", ".join(referencia.autores[:2]) or "sin autor"
            anio = referencia.anio or "s.f."
            print(f"      [{referencia.tipo}] {referencia.titulo[:78]}")
            print(f"        {referencia.identificador}  ·  {autores}  ·  {anio}")
            resultados.append(referencia.a_dict())

    # Lo que se busca NO está verificado todavía: es una candidatura. Se dice aquí para que nadie
    # copie un identificador de esta salida a una ficha sin pasar por --verificar.
    print(
        f"\n{len(resultados)} candidata(s). NINGUNA está verificada: son resultados de búsqueda.\n"
        f"El paso siguiente es --verificar con sus identificadores; solo lo resuelto entra en una ficha."
    )
    print(f"Ledger: {json.dumps(ledger.resumen(), ensure_ascii=False)}")

    if salida:
        payload = {
            "nicho": elegido,
            "consulta": consulta,
            "estado": "SIN VERIFICAR (resultados de búsqueda)",
            "candidatas": resultados,
            "ledger": ledger.resumen(),
        }
        from pathlib import Path

        Path(salida).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Escrito: {salida}")
    return 0


def cmd_verificar(identificadores: list[str], nicho: str | None, titulo: str | None) -> int:
    """El comando que importa: resuelve identificadores contra las APIs."""
    elegido, perfil, proveedores, _ = _proveedores(nicho)
    ledger = base.LedgerLlamadas()
    peticiones = [{"identificador": i} for i in identificadores]
    if titulo and len(peticiones) == 1:
        peticiones[0]["titulo_propuesto"] = titulo

    veredictos = verificacion.verifica(peticiones, proveedores, ledger)
    print(f"Nicho {elegido!r} · {len(veredictos)} identificador(es)\n")
    fallos = 0
    for veredicto in veredictos:
        if veredicto["resuelto"]:
            referencia = veredicto["referencia"]
            print(f"  RESUELVE  {veredicto['identificador']}")
            print(f"            titulo (de la API): {referencia['titulo']}")
            print(
                f"            {referencia['tipo']} · {', '.join(referencia['autores'][:3]) or 'sin autor'}"
                f" · {referencia['anio'] or 's.f.'} · via {veredicto['consultados'][-1]}"
            )
            extra = referencia.get("extra") or {}
            if extra.get("sha256"):
                # Un documento (`url:`): lo que hará falta para escribir su fuente y sus cifras en la ficha
                texto = (
                    "da texto"
                    if extra.get("da_texto")
                    else "NO da texto: sus cifras serán de lectura manual"
                    if extra.get("legible")
                    else "el código NO puede abrirlo: sus cifras no se podrán confirmar; busca otra URL"
                )
                print(
                    f"            {extra.get('formato')} · {extra.get('paginas')} página(s) · "
                    f"{extra.get('caracteres_de_texto')} caracteres · {texto} · sha256 {extra['sha256'][:16]}…"
                )
                if extra.get("aviso"):
                    print(f"            aviso: {extra['aviso']}")
            if "discrepancia_de_titulo" in veredicto:
                d = veredicto["discrepancia_de_titulo"]
                print(f"            !! DISCREPANCIA (parecido {d['parecido']}): el identificador existe pero")
                print(f"               apunta a otra obra. Propuesto: {d['titulo_propuesto_por_el_agente'][:60]}")
                print("               Gana la API. Revisar a mano antes de usarla.")
                fallos += 1
        else:
            fallos += 1
            print(f"  NO EXISTE {veredicto['identificador']}")
            print(f"            {veredicto['motivo']}")
    print(f"\n{len(veredictos) - fallos} de {len(veredictos)} utilizable(s) en una ficha.")
    print(f"Ledger: {json.dumps(ledger.resumen(), ensure_ascii=False)}")
    return 1 if fallos else 0


def cmd_fichas() -> int:
    resumen = ficha.listado()
    if not resumen:
        print(f"No hay fichas en {ficha.fichas_dir()}: se crean con `fuentes.py --buscar` y `--verificar`")
        return 0
    print(f"{len(resumen)} ficha(s) en {ficha.fichas_dir()}:\n")
    for entrada in resumen:
        aviso = "" if entrada["fuentes"] == entrada["resueltas"] else "  <- TIENE FUENTES SIN RESOLVER"
        print(
            f"  {entrada['id']:<24} {entrada['certeza']:<18} "
            f"{entrada['resueltas']}/{entrada['fuentes']} fuentes resueltas{aviso}"
        )
        print(f"      periodo: {entrada['periodo']}")
    return 0


def cmd_indice(articulo: str, nicho: str | None, verificar: bool) -> int:
    """Wikipedia como índice: saca los identificadores que cita un artículo y los resuelve.

    Es el flujo que se pidió el 25-08 al echar en falta Wikipedia, y va en dos pasos a
    propósito: el artículo aporta los **candidatos** (sus plantillas de cita llevan ISBN y DOI en
    campos con nombre) y el resolutor dice cuáles existen de verdad. Wikipedia nunca acaba siendo
    la fuente de la afirmación — acaba siendo cómo se encontró la fuente.

    Se llama con `es:Tortura en España` o `en:Spanish Inquisition`; sin prefijo se asume `en`.
    """
    from lib.fuentes.proveedores import Wikipedia

    elegido, perfil, proveedores, _ = _proveedores(nicho)
    ledger = base.LedgerLlamadas()
    wiki = Wikipedia()

    identificador = articulo if articulo.startswith("wikipedia:") else f"wikipedia:{articulo}"
    hallazgo = wiki.identificadores_citados(identificador, ledger)
    if "error" in hallazgo:
        print(f"[FAIL] {hallazgo['error']}", file=sys.stderr)
        return 2

    candidatos = hallazgo["candidatos"]
    print(
        f"Artículo {hallazgo['wiki']}:{hallazgo['articulo']!r} · "
        f"{hallazgo['plantillas_de_cita']} plantilla(s) de cita · {len(candidatos)} identificador(es) citados\n"
    )
    if not candidatos:
        print("El artículo no cita ni un ISBN ni un DOI en sus plantillas: como índice no aporta nada aquí.")
        return 0

    if not verificar:
        for c in candidatos:
            print(f"  {c}")
        print(
            f"\n{len(candidatos)} candidato(s) SIN verificar. Que Wikipedia cite un identificador no prueba "
            "que exista: añade --verificar-indice para resolverlos."
        )
        print(f"Ledger: {json.dumps(ledger.resumen(), ensure_ascii=False)}")
        return 0

    veredictos = verificacion.verifica([{"identificador": c} for c in candidatos], proveedores, ledger)
    resueltos = [v for v in veredictos if v["resuelto"]]
    for veredicto in veredictos:
        if veredicto["resuelto"]:
            referencia = veredicto["referencia"]
            autores = ", ".join(referencia["autores"][:2]) or "sin autor"
            print(f"  RESUELVE  {veredicto['identificador']}")
            print(f"            {referencia['titulo'][:78]}")
            print(f"            {autores} · {referencia['anio'] or 's.f.'} · {referencia['tipo']}")
        else:
            print(f"  NO EXISTE {veredicto['identificador']}")
    print(
        f"\n{len(resueltos)} de {len(candidatos)} resuelven y pueden entrar en una ficha. "
        f"Wikipedia queda como el camino, no como la cita."
    )
    print(f"Ledger: {json.dumps(ledger.resumen(), ensure_ascii=False)}")
    return 0


def cmd_bibliografia(ids: list[str]) -> int:
    """Genera el bloque de bibliografía para la descripción del vídeo, DESDE las fichas.

    No es una plantilla que alguien rellena: se construye con lo que las fichas ya tienen
    verificado, así que **no puede citar algo que no haya resuelto**. Si una ficha lleva fuentes
    sin resolver no llegaría aquí, porque `guarda()` no la habría escrito.

    Sirve dos veces, y por eso vale la pena: es señal de autoridad para el espectador y es
    defensa documentada si alguna vez hay una reclamación sobre el contenido.
    """
    lineas: list[str] = []
    pendientes: list[str] = []
    disclaimers: list[str] = []
    for id_ficha in ids:
        datos = ficha.carga(id_ficha)
        if (datos.get("disclaimer") or "").strip():
            disclaimers.append(f"{datos['nombre_es']}: {datos['disclaimer']}")
        lineas.append(f"— {datos['nombre_en']} ({datos['nombre_es']}) —")
        for fuente in datos.get("fuentes", []):
            # La misma línea que el usuario confirma en la página de las cifras (F7.12): una sola función.
            lineas.append(f"  {cifras.cita(fuente)}")
        # El nivel EFECTIVO y no el declarado (F7.12): `cifras_confirmadas` no lleva este aviso, pero una
        # ficha que lo declara con una huella que ya no casa vuelve a `solo_citas_verificadas`.
        if ficha.nivel_efectivo(datos) == "solo_citas_verificadas":
            pendientes.append(datos["id"])
        lineas.append("")

    if disclaimers:
        # El desmentido va PRIMERO, no en una nota al pie. Es la condición con la que se admitieron
        # las piezas ficticias en el catálogo (25-08): entran, pero no entran solas.
        print("AVISO SOBRE LAS PIEZAS DE ESTE VÍDEO — va arriba en la descripción\n")
        for texto in disclaimers:
            print(f"  {texto}\n")
        print("-" * 78 + "\n")

    print("\n".join(lineas))
    print("Las fuentes citadas se han verificado una a una contra el registro de su editor o archivo.")
    if pendientes:
        # Aviso para quien prepare la descripción, NO texto para el espectador: decir «verificadas»
        # es cierto (existen) y decir «documentado» no lo sería si nadie ha leído la fuente.
        print(
            f"\n[AVISO, no publicar esta línea] {len(pendientes)} ficha(s) con nivel "
            f"'solo_citas_verificadas': {', '.join(pendientes)}. Las citas existen y tratan del tema, "
            "pero nadie ha leído las obras: el guion no puede presentar esas afirmaciones como "
            "documentadas sin que una persona lea al menos una fuente por ficha."
        )
    return 0


# --- F7.12: las cifras con su origen (filas 273-275, progress/spec_F7.12.md) ----------------------


def _ruta_de_ficha(argumento: str) -> Path:
    """La ruta de la ficha: un `.json` que se nombra, o el id de una ficha del canal activo."""
    if argumento.endswith(".json"):
        ruta = Path(argumento)
    else:
        ruta = ficha.fichas_dir() / f"{argumento}.json"
    if not ruta.exists():
        raise base.FuentesError(f"no existe la ficha {argumento!r} ({ruta})")
    return ruta


def _perfil_de_la_ficha(datos: dict, nicho: str | None) -> tuple[str, dict]:
    """El perfil del nicho de la ficha. Si la ficha lo declara y `--nicho` dice otro, no se adivina cuál vale."""
    declarado = datos.get("nicho") or None
    if declarado and nicho and declarado != nicho:
        raise base.FuentesError(f"la ficha es del nicho {declarado!r} y --nicho dice {nicho!r}")
    elegido = declarado or nicho or registro.nicho_del_canal()
    if not elegido:
        raise base.FuentesError(
            "no se sabe de qué nicho es la ficha: no lo declara, no hay canal activo y falta --nicho"
        )
    return elegido, registro.carga_perfil(elegido)


def _lo_que_escribe_el_codigo(borrador: ficha.Ficha, destino: Path) -> list[str]:
    """Las cifras del borrador que traen `comprobacion` o `confirmacion` que no salen de la ficha en disco.

    Esos dos campos los escriben `--comprueba-cifras` y `--confirma`, nunca una persona: la confirmación es
    del usuario, y la comprobación es lo que el código vio en el documento. Un borrador puede traerlos solo si
    son los mismos que ya tiene la ficha guardada (para poder corregir otro campo sin perderlos).
    """
    guardadas = {}
    if destino.exists():
        guardadas = {
            c.get("id"): c
            for c in json.loads(destino.read_text(encoding="utf-8")).get("cifras") or []
            if isinstance(c, dict)
        }
    ajenas = []
    for cifra in borrador.cifras:
        if not isinstance(cifra, dict):
            continue
        for campo in ficha.CAMPOS_DEL_CODIGO_EN_UNA_CIFRA:
            if campo in cifra and cifra[campo] != (guardadas.get(cifra.get("id")) or {}).get(campo):
                ajenas.append(f"cifra {cifra.get('id')}: `{campo}`")
    return ajenas


def cmd_guarda(borrador: str, nicho: str | None, carpeta: str | None) -> int:
    """Valida un borrador de ficha y lo escribe con `ficha.guarda`. No escribe nada que no valide."""
    datos = json.loads(Path(borrador).read_text(encoding="utf-8"))
    nueva = ficha.desde_dict(datos)
    elegido, perfil = _perfil_de_la_ficha(datos, nicho)
    nueva.nicho = nueva.nicho or elegido
    destino_dir = Path(carpeta) if carpeta else ficha.fichas_dir()
    ajenas = _lo_que_escribe_el_codigo(nueva, destino_dir / f"{nueva.id}.json")
    if ajenas:
        raise base.FuentesError(
            "el borrador trae campos que solo escribe el código y no coinciden con la ficha guardada: "
            f"{ajenas}. `comprobacion` la escribe --comprueba-cifras y `confirmacion`, --confirma"
        )
    for problema in ficha.valida(nueva, perfil):
        if problema.startswith("AVISO"):
            print(f"  [{problema}]")
    ruta = ficha.guarda(nueva, perfil, carpeta=destino_dir)
    print(f"[OK] ficha {nueva.id!r} guardada en {ruta} · nivel {nueva.nivel_de_respaldo}")
    if nueva.cifras:
        print("     El paso siguiente es --comprueba-cifras: descarga cada origen y busca cada frase.")
    return 0


def cmd_comprueba_cifras(argumento: str, nicho: str | None, abrir: bool) -> int:
    """Descarga cada origen UNA vez, busca cada frase, escribe `comprobacion` y genera la página."""
    from lib.fuentes import pagina
    from lib.fuentes.proveedores import documento

    ruta = _ruta_de_ficha(argumento)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    actual = ficha.desde_dict(datos)
    _, perfil = _perfil_de_la_ficha(datos, nicho)
    if not actual.cifras:
        raise base.FuentesError(f"la ficha {actual.id!r} no lleva cifras que comprobar")

    ledger = base.LedgerLlamadas()
    lecturas: dict[str, documento.Lectura] = {}
    fuentes = {f.get("identificador"): f for f in actual.fuentes}
    print(f"Ficha {actual.id!r} · {len(actual.cifras)} cifra(s)\n")
    for cifra in actual.cifras:
        identificador = cifra.get("fuente") or ""
        if identificador not in fuentes or not identificador.startswith("url:"):
            raise base.FuentesError(f"la cifra {cifra.get('id')!r} no apunta a una fuente `url:` de la ficha")
        if identificador not in lecturas:
            lecturas[identificador] = documento.lee(identificador.removeprefix("url:"), ledger)
            lectura = lecturas[identificador]
            estado = (
                lectura.error or f"{lectura.formato}, {len(lectura.paginas)} página(s), {lectura.caracteres} caracteres"
            )
            print(f"  descargado {identificador[:90]}\n      HTTP {lectura.http} · {estado}")
        cifra["comprobacion"] = cifras.comprueba_frase(cifra, lecturas[identificador])
        comprobacion = cifra["comprobacion"]
        # La cita que la página le enseña al usuario: si después cambia, su confirmación deja de contar.
        comprobacion["cita"] = cifras.cita(fuentes[identificador])
        if comprobacion["encontrada"]:
            donde = f" (página {comprobacion['pagina']})" if comprobacion["pagina"] else ""
            print(f"  ENCONTRADA  {cifra.get('id')}: {cifra.get('valor')}{donde}")
        elif comprobacion["lectura"] == "manual":
            print(f"  MANUAL      {cifra.get('id')}: {comprobacion['motivo']}")
        else:
            print(f"  NO          {cifra.get('id')}: {comprobacion['motivo']}")

    for cambio in ficha.recalcula_respaldo(actual):
        print(f"  [{cambio}]")
    ficha.escribe(actual, perfil, ruta)
    destino = ruta.with_name(f"{ruta.stem}.confirmacion.html")
    destino.write_text(pagina.pagina_de_confirmacion(actual.a_dict()), encoding="utf-8")
    print(f"\nFicha actualizada: {ruta}\nPágina de confirmación: {destino}")
    print(f"Ledger: {json.dumps(ledger.resumen(), ensure_ascii=False)}")
    if abrir:
        from lib.pagina_local import abre

        abre(destino)
    return 0


def cmd_confirma(argumentos: list[str], dijo: str | None, nicho: str | None) -> int:
    """Registra la confirmación del usuario, con sus palabras, la fecha y la huella de cada cifra."""
    if len(argumentos) < 2:
        raise base.FuentesError("--confirma pide la ficha y al menos una cifra: --confirma <ficha> <cifra>…")
    if not (dijo or "").strip():
        raise base.FuentesError('--confirma necesita --dijo "<las palabras literales del usuario>"')
    ruta = _ruta_de_ficha(argumentos[0])
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    actual = ficha.desde_dict(datos)
    _, perfil = _perfil_de_la_ficha(datos, nicho)
    por_id = {c.get("id"): c for c in actual.cifras if isinstance(c, dict)}
    pedidas = list(dict.fromkeys(argumentos[1:]))
    desconocidas = [i for i in pedidas if i not in por_id]
    if desconocidas:
        raise base.FuentesError(f"la ficha no tiene las cifras {desconocidas}; tiene {sorted(por_id)}")
    # Todas o ninguna: una confirmación a medias dejaría la ficha en un estado que nadie pidió.
    rechazadas = [f"{i}: {motivo}" for i in pedidas if (motivo := cifras.se_puede_confirmar(por_id[i]))]
    fuentes = {f.get("identificador"): f for f in actual.fuentes if isinstance(f, dict)}
    rechazadas += [
        f"{i}: la cita de su fuente cambió después de la página que vio el usuario; vuelve a lanzar --comprueba-cifras"
        for i in pedidas
        if not cifras.se_puede_confirmar(por_id[i]) and not cifras.cita_al_dia(por_id[i], fuentes)
    ]
    if rechazadas:
        raise base.FuentesError(
            "no se confirma ninguna, porque estas no se pueden confirmar:\n  - " + "\n  - ".join(rechazadas)
        )
    for identificador in pedidas:
        cifra = por_id[identificador]
        cifra["confirmacion"] = {
            "por": "el usuario",
            "el": date.today().isoformat(),
            "dijo": dijo.strip(),
            "huella": cifras.huella(cifra),
        }
        print(f"  CONFIRMADA  {identificador}: {cifra.get('valor')}")
    for cambio in ficha.recalcula_respaldo(actual):
        print(f"  [{cambio}]")
    ficha.escribe(actual, perfil, ruta)
    pendientes = [i for i, c in por_id.items() if not cifras.confirmacion_vale(c)]
    print(f"\nFicha {actual.id!r}: nivel {actual.nivel_de_respaldo} · sin confirmar: {pendientes or 'ninguna'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fuentes con autoridad: buscar, verificar identificadores y listar fichas",
        epilog="Principio del módulo: una cita que no resuelve, no existe.",
    )
    parser.add_argument("--nichos", action="store_true", help="lista los perfiles de autoridad del estudio")
    parser.add_argument("--fichas", action="store_true", help="lista las fichas verificadas del canal activo")
    parser.add_argument(
        "--bibliografia", nargs="+", metavar="FICHA", help="bloque de bibliografía para la descripción del vídeo"
    )
    parser.add_argument(
        "--indice",
        metavar="ARTICULO",
        help="Wikipedia como índice: identificadores que cita un artículo (p. ej. 'es:Tortura en España')",
    )
    parser.add_argument(
        "--verificar-indice",
        action="store_true",
        dest="verificar_indice",
        help="con --indice: resuelve además cada identificador citado",
    )
    parser.add_argument("--buscar", metavar="CONSULTA", help="busca candidatas en los proveedores del nicho")
    parser.add_argument("--verificar", nargs="+", metavar="ID", help="resuelve identificadores (esquema:valor)")
    parser.add_argument("--titulo", help="con --verificar de UN id: título que se creía citar, para cotejarlo")
    parser.add_argument("--nicho", help="nicho a usar; por defecto, el del canal activo")
    parser.add_argument("--limite", type=int, default=5, help="resultados por proveedor en --buscar (5)")
    parser.add_argument("--salida", help="con --buscar: archivo JSON donde volcar las candidatas")
    parser.add_argument("--guarda", metavar="BORRADOR", help="valida un borrador de ficha (.json) y lo guarda")
    parser.add_argument(
        "--carpeta", help="con --guarda: carpeta donde escribir la ficha; por defecto, la de fichas del canal activo"
    )
    parser.add_argument(
        "--comprueba-cifras",
        dest="comprueba_cifras",
        metavar="FICHA",
        help="descarga el origen de cada cifra, busca su frase exacta y abre la página de confirmación",
    )
    parser.add_argument(
        "--no-abrir", action="store_true", dest="no_abrir", help="con --comprueba-cifras: no abre la página"
    )
    parser.add_argument(
        "--confirma",
        nargs="+",
        metavar="FICHA CIFRA",
        help='registra la confirmación del usuario de esas cifras: --confirma <ficha> <cifra>… --dijo "…"',
    )
    parser.add_argument("--dijo", help="con --confirma: las palabras literales del usuario en la conversación")
    args = parser.parse_args()

    try:
        if args.guarda:
            return cmd_guarda(args.guarda, args.nicho, args.carpeta)
        if args.comprueba_cifras:
            return cmd_comprueba_cifras(args.comprueba_cifras, args.nicho, not args.no_abrir)
        if args.confirma:
            return cmd_confirma(args.confirma, args.dijo, args.nicho)
        if args.nichos:
            return cmd_nichos()
        if args.buscar:
            return cmd_buscar(args.buscar, args.nicho, args.limite, args.salida)
        if args.verificar:
            return cmd_verificar(args.verificar, args.nicho, args.titulo)
        if args.fichas:
            return cmd_fichas()
        if args.bibliografia:
            return cmd_bibliografia(args.bibliografia)
        if args.indice:
            return cmd_indice(args.indice, args.nicho, args.verificar_indice)
        parser.print_help()
        return 0
    except base.FuentesError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"[FAIL] el fichero no es JSON válido: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
