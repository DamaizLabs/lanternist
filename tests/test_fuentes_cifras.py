"""Las cifras de un canal de economía con su origen: frase exacta, confirmación con huella, cuentas y gate 1 (F7.12).

Correr: .venv\\Scripts\\python -m pytest -q tests/test_fuentes_cifras.py

**De dónde sale.** Filas 273, 274 y 275 del addendum y `progress/spec_F7.12.md`. En un explicador de
economía las cifras son el producto: cada una se respalda con la frase exacta de su origen, que el
código busca en el documento, y con la confirmación del usuario, atada con una huella.

**Lo que estas pruebas protegen son los controles negativos de la spec §6**, porque un respaldo que no
sabe fallar es decorativo: un dígito cambiado no se encuentra, un valor que no está en su frase se
rechaza, una confirmación deja de contar si cambia la frase, una cuenta mal redondeada falla, un dato
real sin cifra confirmada falla, una expresión con una llamada no se ejecuta, un mapa de un canal falla
y un guion de un canal de economía con una cifra que no está en su ficha da FALLO. La regresión contra
las fichas reales de un canal del estudio salió con ese canal en OC1.1: el repositorio ya no las trae.

**Sin red.** Los documentos son bytes locales (un HTML, un PDF hecho aquí) y la descarga se prueba con
un abridor falso. La condición real, con documentos públicos de verdad, está en `progress/impl_F7.12.md`.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from lib import config
from lib.fuentes import base, cifras, ficha, registro
from lib.fuentes import pagina as pagina_mod
from lib.fuentes.proveedores import CATALOGO, documento

RAIZ = config.BASE_DIR
URL_PDF = "url:https://example.org/informe-anual.pdf"
URL_HTML = "url:https://example.org/estadistica.htm"
FRASE_IPC = "Over the last 12 months, the all items index increased 3.4 percent before seasonal adjustment."
RELLENO = " Esta frase de relleno existe para que el documento dé texto de verdad y no parezca un escaneado." * 4


# --- documentos locales ---------------------------------------------------------------------------


def _pdf(paginas: list[str], titulo: str = "Informe anual de prueba") -> bytes:
    """Un PDF mínimo y válido, con una línea de texto por página, que `pypdf` sabe leer."""
    objetos = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{5 + 2 * i} 0 R' for i in range(len(paginas)))}] /Count {len(paginas)} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Title ({titulo}) >>",
    ]
    for i, texto in enumerate(paginas):
        flujo = f"BT /F1 9 Tf 20 700 Td ({texto}) Tj ET"
        objetos.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 2400 792] /Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {6 + 2 * i} 0 R >>"
        )
        objetos.append(f"<< /Length {len(flujo)} >>\nstream\n{flujo}\nendstream")
    salida, inicios = b"%PDF-1.4\n", []
    for numero, objeto in enumerate(objetos, start=1):
        inicios.append(len(salida))
        salida += f"{numero} 0 obj\n{objeto}\nendobj\n".encode("latin-1")
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    salida += "".join(f"{i:010d} 00000 n \n" for i in inicios).encode()
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R /Info 4 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return salida


def _pdf_sin_texto() -> bytes:
    from pypdf import PdfWriter

    escritor = PdfWriter()
    escritor.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    escritor.write(buf)
    return buf.getvalue()


HTML = (
    "<!doctype html><html><head><title>CPI &amp; prices &mdash; August</title>"
    "<script>var x = 'Over the last 12 months it rose 9.9 percent';</script><style>p{}</style></head>"
    "<body><p>Over the last 12 months, the all&nbsp;items index increased 3.4 percent before seasonal "
    "adjustment.</p><p>The Company&#8217;s float &#8211; the capital we hold &#8211; stood at $176 billion.</p>"
    f"<p>{RELLENO}</p></body></html>"
).encode("utf-8")


def _lectura(datos: bytes, tipo: str, url: str = "https://example.org/x", codificacion: str = "") -> documento.Lectura:
    return documento.completa(
        documento.Lectura(url=url, descargado_el="2026-10-06T10:00:00+00:00"), datos, tipo, None, codificacion
    )


# --- una ficha de economía de prueba ----------------------------------------------------------------


def _perfil() -> dict:
    return registro.carga_perfil("ejemplo-con-cifras")


def _borrador(**cambios) -> dict:
    datos = {
        "id": "prueba-cifras",
        "nombre_en": "Test",
        "nombre_es": "Prueba",
        "nicho": "ejemplo-con-cifras",
        "afirmacion": "Una afirmación de prueba.",
        "certeza": "documentado",
        "periodo_documentado": "2025",
        "ambito": "Estados Unidos",
        "evidencia": "Prueba.",
        "tratamiento_editorial": "Prueba.",
        "fuentes": [
            {"identificador": URL_PDF, "tipo": "fuente_primaria", "titulo": "Informe", "autores": ["Empresa"],
             "titulo_publicado": "Annual Report 2025",
             "url": URL_PDF[4:], "proveedor": "documento", "resuelto": True, "pertinencia": "existe"},
            {"identificador": URL_HTML, "tipo": "institucional", "titulo": "IPC", "autores": ["Oficina"],
             "titulo_publicado": "Consumer Price Index Summary",
             "url": URL_HTML[4:], "proveedor": "documento", "resuelto": True, "pertinencia": "existe"},
        ],
        "inspiracion": {
            "videos": [
                {"video_id": f"v{n}", "canal": f"Canal {c}", "channel_id": f"UC{c}", "titulo": f"Vídeo {n}",
                 "consultado_el": "2026-10-06"}
                for n, c in ((1, "A"), (2, "A"), (3, "B"))
            ],
            "preguntas_que_responden": ["¿Por qué?"],
            "cifras_que_dan": ["la inflación"],
        },
        "cifras": [
            {"id": "ipc", "valor": "3.4%", "anio": 2026, "ambito": "EE. UU.", "fuente": URL_HTML,
             "ubicacion": "párrafo 1", "frase_exacta": FRASE_IPC},
            {"id": "float", "valor": "$176 billion", "anio": 2025, "ambito": "Empresa", "fuente": URL_PDF,
             "ubicacion": "p. 2", "frase_exacta": "Our float stood at $176 billion at year-end."},
        ],
        "cuentas": [
            {"id": "interes", "expresion": "capital * (1 + tasa) ** anios",
             "datos": {"capital": {"valor": 100, "tipo": "ejemplo"}, "tasa": {"valor": 0.07, "tipo": "ejemplo"},
                       "anios": {"valor": 10, "tipo": "ejemplo"}},
             "resultado": 196.71513572895665, "se_dice": "about $197", "redondeo": 0},
            {"id": "cesta", "expresion": "precio * (1 + inflacion)",
             "datos": {"precio": {"valor": 100, "tipo": "ejemplo"},
                       "inflacion": {"valor": 0.034, "tipo": "real", "cifra": "ipc"}},
             "resultado": 103.4, "se_dice": "about $103.40", "redondeo": 2},
        ],
        "nivel_de_respaldo": "solo_citas_verificadas",
    }  # fmt: skip
    datos.update(cambios)
    return json.loads(json.dumps(datos))


PDF_DEL_INFORME = _pdf(["Portada." + RELLENO, "Our float stood at $176 billion at year-end." + RELLENO])
LECTURAS = {
    URL_PDF: lambda: _lectura(PDF_DEL_INFORME, "application/pdf"),
    URL_HTML: lambda: _lectura(HTML, "text/html"),
}


def _comprobada(datos: dict | None = None) -> dict:
    """La ficha con la `comprobacion` que escribiría `--comprueba-cifras` sobre los documentos locales."""
    datos = datos or _borrador()
    fuentes = {f["identificador"]: f for f in datos["fuentes"]}
    for cifra in datos["cifras"]:
        cifra["comprobacion"] = cifras.comprueba_frase(cifra, LECTURAS[cifra["fuente"]]())
        cifra["comprobacion"]["cita"] = cifras.cita(fuentes[cifra["fuente"]])
    return datos


def _confirmada() -> dict:
    datos = _comprobada()
    for cifra in datos["cifras"]:
        cifra["confirmacion"] = {
            "por": "el usuario",
            "el": "2026-10-06",
            "dijo": "ok a las dos",
            "huella": cifras.huella(cifra),
        }
    leida = ficha.desde_dict(datos)
    ficha.recalcula_respaldo(leida)
    return leida.a_dict()


def _duros(datos: dict, perfil: dict | None = None) -> list[str]:
    return [p for p in ficha.valida(ficha.desde_dict(datos), perfil or _perfil()) if not p.startswith("AVISO")]


# --- el proveedor `documento` ---------------------------------------------------------------------------


def test_el_proveedor_esta_en_el_catalogo_y_en_el_perfil_con_cifras():
    assert CATALOGO["documento"] is documento.Documento
    assert documento.Documento.esquemas == ("url",)
    assert "documento" in _perfil()["proveedores"]


def test_el_html_da_su_titulo_y_su_texto_sin_los_scripts():
    lectura = _lectura(HTML, "text/html")
    assert lectura.formato == "html" and lectura.titulo == "CPI & prices — August"
    assert "3.4 percent" in lectura.paginas[0]
    assert "9.9" not in lectura.paginas[0], "el texto de un <script> no es texto del documento"
    assert lectura.sha256 == hashlib.sha256(HTML).hexdigest()


def test_el_pdf_da_su_titulo_y_el_texto_de_cada_pagina():
    lectura = _lectura(_pdf(["Primera." + RELLENO, "Segunda pagina." + RELLENO]), "application/octet-stream")
    assert lectura.formato == "pdf", "un PDF se reconoce por sus bytes aunque el servidor diga otra cosa"
    assert lectura.titulo == "Informe anual de prueba"
    assert len(lectura.paginas) == 2 and "Segunda pagina." in lectura.paginas[1]


def test_un_pdf_sin_texto_es_de_lectura_manual():
    lectura = _lectura(_pdf_sin_texto(), "application/pdf")
    assert lectura.formato == "pdf" and not lectura.da_texto
    comprobacion = cifras.comprueba_frase(_borrador()["cifras"][1], lectura)
    assert comprobacion["lectura"] == "manual" and comprobacion["encontrada"] is False
    assert cifras.se_puede_confirmar({**_borrador()["cifras"][1], "comprobacion": comprobacion}) is None


def test_gzip_se_abre_y_da_la_misma_huella_que_sin_comprimir():
    lectura = _lectura(gzip.compress(HTML), "text/html", codificacion="gzip")
    assert lectura.formato == "html" and "3.4 percent" in lectura.paginas[0]
    assert lectura.sha256 == hashlib.sha256(HTML).hexdigest()


def test_CONTROL_una_compresion_que_no_se_abre_es_ilegible_y_no_lectura_manual():
    """Medido el 06-10 en una web tras Sucuri, que sirve brotli siempre: los bytes comprimidos no son texto."""
    lectura = _lectura(b"\x1b\x00\xf8\x01 bytes de brotli", "text/html", codificacion="br")
    assert lectura.formato is None and "br" in (lectura.error or "")
    comprobacion = cifras.comprueba_frase(_borrador()["cifras"][0], lectura)
    assert comprobacion["lectura"] is None and comprobacion["encontrada"] is False
    assert cifras.se_puede_confirmar({**_borrador()["cifras"][0], "comprobacion": comprobacion}) is not None


class _Respuesta:
    """Una respuesta HTTP falsa que se lee como un flujo: por trozos, y vacía al acabar."""

    def __init__(self, datos: bytes, tipo: str = "text/html"):
        self._flujo, self.status = io.BytesIO(datos), 200
        from email.message import Message

        self.headers = Message()
        self.headers["Content-Type"] = f"{tipo}; charset=utf-8"

    def read(self, tope=-1):
        return self._flujo.read(tope)

    def read1(self, tope=-1):
        return self._flujo.read1(tope)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_la_descarga_es_una_sola_por_el_ledger_y_con_el_user_agent_sin_correo(monkeypatch):
    pedidas = []

    def abre(peticion, timeout):
        pedidas.append(peticion)
        return _Respuesta(HTML)

    monkeypatch.setattr(documento._ABRIDOR, "open", abre)
    ledger = base.LedgerLlamadas()
    referencia = documento.Documento().resuelve(URL_HTML, ledger)
    assert len(pedidas) == 1 and ledger.resumen()["llamadas"] == 1
    assert pedidas[0].get_header("User-agent") == base.USER_AGENT and "@" not in base.USER_AGENT
    assert referencia.resuelto and referencia.titulo == "CPI & prices — August"
    assert referencia.extra["sha256"] == hashlib.sha256(HTML).hexdigest()


def test_un_fallo_de_red_no_se_reintenta(monkeypatch):
    intentos = []

    def falla(peticion, timeout):
        intentos.append(1)
        raise urllib.error.HTTPError(peticion.full_url, 403, "Forbidden", None, None)

    monkeypatch.setattr(documento._ABRIDOR, "open", falla)
    ledger = base.LedgerLlamadas()
    assert documento.Documento().resuelve(URL_HTML, ledger) is None
    assert len(intentos) == 1, "cero reintentos automáticos (base.py)"
    assert ledger.resumen()["fallidas"] == 1


def test_solo_https_y_sin_salir_de_https_al_redirigir(monkeypatch):
    monkeypatch.setattr(documento._ABRIDOR, "open", lambda *a, **k: pytest.fail("no debía llegar a la red"))
    with pytest.raises(base.FuentesError, match="https"):
        documento.Documento().resuelve("url:http://example.org/x.pdf", base.LedgerLlamadas())
    with pytest.raises(urllib.error.HTTPError, match="fuera de https"):
        documento._SoloHttps().redirect_request(None, None, 302, "Found", {}, "http://example.org/x")


def test_buscar_no_busca_y_lo_dice():
    ledger = base.LedgerLlamadas()
    assert documento.Documento().busca("costco", 5, ledger) == []
    assert ledger.omitidas and "no se busca" in ledger.omitidas[0]["motivo"]


# --- la frase en el documento ----------------------------------------------------------------------------


def test_la_frase_se_encuentra_igualando_espacios_comillas_y_guiones():
    lectura = _lectura(HTML, "text/html")
    copiada = "The Company's float - the capital we hold - stood at $176 billion."
    assert cifras.busca_frase(copiada, lectura.paginas) == 1


def test_CONTROL_un_digito_cambiado_no_se_encuentra():
    lectura = _lectura(HTML, "text/html")
    cifra = {**_borrador()["cifras"][0]}
    cifra["frase_exacta"] = cifra["frase_exacta"].replace("3.4", "3.5")
    cifra["valor"] = "3.5%"
    comprobacion = cifras.comprueba_frase(cifra, lectura)
    assert comprobacion["encontrada"] is False and comprobacion["lectura"] == "automatica"
    assert "no está en el documento" in comprobacion["motivo"]


def test_en_un_pdf_se_dice_la_pagina():
    comprobacion = cifras.comprueba_frase(_borrador()["cifras"][1], LECTURAS[URL_PDF]())
    assert comprobacion == {**comprobacion, "encontrada": True, "pagina": 2, "lectura": "automatica"}


@pytest.mark.parametrize(
    "valor, frase, faltan",
    [
        ("7%", "it grew 7 percent", []),
        ("$4,123 million", "sales of $4123 million", []),
        ("7%", "founded in 1997", ["7"]),
        ("$44.5 billion", "operating earnings of $44.6 billion", ["44.5"]),
        ("seven percent", "it grew 7 percent", ["seven percent"]),
    ],
)
def test_los_digitos_del_valor_tienen_que_estar_en_la_frase(valor, frase, faltan):
    assert cifras.digitos_del_valor_en_la_frase(valor, frase) == faltan


def test_CONTROL_un_valor_que_no_esta_en_su_frase_no_se_guarda():
    datos = _borrador()
    datos["cifras"][1]["valor"] = "$177 billion"
    assert any("no está en su frase" in p for p in _duros(datos))


# --- la huella de la confirmación -------------------------------------------------------------------


def test_una_ficha_confirmada_valida_y_sube_de_nivel():
    datos = _confirmada()
    assert datos["nivel_de_respaldo"] == "cifras_confirmadas" == ficha.nivel_efectivo(datos)
    assert {f["pertinencia"] for f in datos["fuentes"]} == {"cifra_confirmada"}
    assert _duros(datos) == []


@pytest.mark.parametrize(
    "campo, nuevo",
    [
        ("valor", "$176.0 billion"),
        ("frase_exacta", "Our float stood at $176 billion at the end of the year."),
        ("fuente", URL_HTML),
        ("documento", "0" * 64),
        # Revisión de F7.12, recomendación 3: la página enseña el año y el ámbito, y el guion los dice.
        ("anio", 2024),
        ("ambito", "Todo el mundo"),
    ],
)
def test_CONTROL_la_confirmacion_deja_de_contar_si_cambia_algo_de_lo_confirmado(campo, nuevo):
    datos = _confirmada()
    cifra = datos["cifras"][1]
    assert cifras.confirmacion_vale(cifra)
    if campo == "documento":
        cifra["comprobacion"]["documento_sha256"] = nuevo
    else:
        cifra[campo] = nuevo
    assert not cifras.confirmacion_vale(cifra)
    assert ficha.nivel_efectivo(datos) == "solo_citas_verificadas"
    assert any("no están confirmadas con su huella" in p for p in _duros(datos))


def test_CONTROL_no_se_declara_cifras_confirmadas_a_mano():
    datos = _comprobada(_borrador(nivel_de_respaldo="cifras_confirmadas"))
    assert any("no están confirmadas con su huella" in p for p in _duros(datos))
    datos = _comprobada()
    datos["fuentes"][0]["pertinencia"] = "cifra_confirmada"
    assert any("ninguna cifra confirmada sale de ella" in p for p in _duros(datos))


def test_si_una_huella_deja_de_casar_la_ficha_baja_de_nivel():
    leida = ficha.desde_dict(_confirmada())
    leida.cifras[0]["frase_exacta"] += " "
    cambios = ficha.recalcula_respaldo(leida)
    assert leida.nivel_de_respaldo == "solo_citas_verificadas"
    assert any("cifra_confirmada → existe" in c for c in cambios)


def test_la_bibliografia_no_avisa_de_solo_citas_con_cifras_confirmadas():
    assert ficha.nivel_efectivo(_confirmada()) == "cifras_confirmadas"
    assert ficha.nivel_efectivo(_comprobada()) == "solo_citas_verificadas"


# --- las cuentas -----------------------------------------------------------------------------------


def _cuenta(**cambios) -> dict:
    cuenta = json.loads(json.dumps(_borrador()["cuentas"][0]))
    cuenta.update(cambios)
    return cuenta


def test_la_cuenta_de_la_muestra_casa():
    revision = cifras.comprueba_cuenta(_cuenta(), [])
    assert revision.problemas == [] and round(revision.calculado, 6) == 196.715136


@pytest.mark.parametrize("se_dice", ["about $196", "about $197.5", "about 197 and 3"])
def test_CONTROL_una_cuenta_con_se_dice_mal_redondeado_falla(se_dice):
    assert cifras.comprueba_cuenta(_cuenta(se_dice=se_dice), []).problemas


def test_CONTROL_un_resultado_que_no_es_el_calculado_falla():
    assert any("la expresión da" in p for p in cifras.comprueba_cuenta(_cuenta(resultado=197), []).problemas)


def test_CONTROL_un_dato_real_sin_cifra_o_sin_cifra_confirmada_falla():
    datos = _comprobada()
    sin_cifra = json.loads(json.dumps(datos["cuentas"][1]))
    del sin_cifra["datos"]["inflacion"]["cifra"]
    assert any("no apunta a una cifra" in p for p in cifras.comprueba_cuenta(sin_cifra, datos["cifras"]).problemas)
    # Con la cifra sin confirmar: pendiente al guardar, y fallo en cuanto la ficha reclama el nivel
    revision = cifras.comprueba_cuenta(datos["cuentas"][1], datos["cifras"])
    assert revision.problemas == [] and revision.pendientes
    datos["nivel_de_respaldo"] = "cifras_confirmadas"
    assert any("sin confirmar" in p for p in _duros(datos))


def test_CONTROL_un_dato_real_con_otro_valor_que_su_cifra_falla():
    datos = _confirmada()
    datos["cuentas"][1]["datos"]["inflacion"]["valor"] = 0.035
    assert any("dice «3.4%»" in p for p in cifras.comprueba_cuenta(datos["cuentas"][1], datos["cifras"]).problemas)


@pytest.mark.parametrize(
    "expresion",
    [
        "__import__('os').remove(RUTA)",
        "capital.real",
        "[capital][0]",
        "capital if tasa else anios",
        "(lambda: 1)()",
        "capital > tasa",
    ],
)
def test_CONTROL_una_expresion_fuera_de_la_lista_cerrada_falla_sin_ejecutarse(tmp_path, expresion):
    testigo = tmp_path / "testigo.txt"
    testigo.write_text("sigo aquí", encoding="utf-8")
    expresion = expresion.replace("RUTA", repr(str(testigo)))
    with pytest.raises(cifras.CuentaError, match="lista cerrada"):
        cifras.evalua(expresion, {"capital": 100, "tasa": 0.07, "anios": 10})
    assert testigo.exists(), "la expresión se ejecutó"


@pytest.mark.parametrize(
    "expresion, motivo",
    [
        ("capital / (tasa - tasa)", "división por cero"),
        ("inventado * 2", "no está en `datos`"),
        ("10.0 ** 400", "potencia"),
    ],
)
def test_una_expresion_que_no_se_puede_calcular_dice_por_que(expresion, motivo):
    with pytest.raises(cifras.CuentaError, match=motivo):
        cifras.evalua(expresion, {"capital": 100, "tasa": 0.07})


# --- el mapa y el perfil del nicho -----------------------------------------------------------------


def test_CONTROL_un_mapa_de_un_video_o_de_un_canal_falla():
    datos = _borrador()
    datos["inspiracion"]["videos"] = datos["inspiracion"]["videos"][:1]
    assert any("vídeo(s) distinto(s)" in p for p in _duros(datos))
    datos = _borrador()
    for video in datos["inspiracion"]["videos"]:
        video["channel_id"] = "UC-uno"
    assert any("canal(es) distinto(s)" in p for p in _duros(datos))
    assert not any("distinto" in p for p in _duros(_borrador())), "control: el mapa de 3 vídeos de 2 canales vale"


def test_el_mapa_no_admite_una_transcripcion():
    datos = _borrador()
    datos["inspiracion"]["transcripcion"] = "texto copiado del vídeo"
    assert any("Ninguna transcripción" in p for p in _duros(datos))
    datos = _borrador()
    datos["inspiracion"]["videos"][0]["transcripcion"] = "texto"
    assert any("solo admite" in p for p in _duros(datos))


def test_el_nicho_que_exige_cifras_pide_el_mapa_y_una_cifra():
    assert any("exige el mapa" in p for p in _duros(_borrador(inspiracion=None)))
    assert any("al menos una cifra" in p for p in _duros(_borrador(cifras=[], cuentas=[])))


@pytest.mark.parametrize(
    "bloque, falta",
    [
        ({"mapa": {"minimo_videos": 3, "minimo_canales": 2}}, "exige_frase_confirmada"),
        ({"exige_frase_confirmada": True}, "sin `mapa`"),
        ({"exige_frase_confirmada": True, "mapa": {"minimo_videos": 3}}, "minimo_canales"),
        ({"exige_frase_confirmada": "sí", "mapa": {"minimo_videos": 0, "minimo_canales": 2}}, "minimo_videos"),
        # Fila 280: el tope del redondeo tampoco tiene valor por defecto.
        ({"exige_frase_confirmada": True, "mapa": {"minimo_videos": 3, "minimo_canales": 2}}, "error_maximo_pct"),
        (
            {"exige_frase_confirmada": True, "mapa": {"minimo_videos": 3, "minimo_canales": 2},
             "redondeo": {"error_maximo_pct": True}},
            "error_maximo_pct",
        ),
        (
            {"exige_frase_confirmada": True, "mapa": {"minimo_videos": 3, "minimo_canales": 2},
             "redondeo": {"error_maximo_pct": 0}},
            "error_maximo_pct",
        ),
    ],
)  # fmt: skip
def test_el_bloque_cifras_del_perfil_no_tiene_valor_por_defecto(bloque, falta):
    reglas, problemas = ficha.reglas_de_cifras({**_perfil(), "cifras": bloque})
    assert reglas is None and any(falta in p for p in problemas)


def test_un_perfil_sin_bloque_cifras_no_exige_nada():
    assert ficha.reglas_de_cifras(registro.carga_perfil("ejemplo-sin-cifras")) == (None, [])


# --- las cantidades de una narración -----------------------------------------------------------------


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("about one hundred ninety-seven dollars", [("197", "usd", False)]),
        ("$4.1 billion", [("4100000000", "usd", True)]),
        ("four point one billion dollars", [("4100000000", "usd", True)]),
        ("seven percent", [("7", "pct", False)]),
        ("four percent", [("4", "pct", False)]),
        ("twenty-four dollars", [("24", "usd", False)]),
        ("3.2 per cent", [("3.2", "pct", False)]),
        ("a million members", [("1000000", None, True)]),
        ("in 2024, the first year", [("2024", None, False)]),
        ("€5 and £10", [("5", "eur", False), ("10", "gbp", False)]),
        # Revisión de F7.12: antes eran números sin unidad y solo daban aviso.
        ("five USD", [("5", "usd", False)]),
        ("500 yen and 20 yuan", [("500", "jpy", False), ("20", "cny", False)]),
        ("up 3 percentage points", [("3", "pp", False)]),
        ("one percentage point", [("1", "pp", False)]),
    ],
)
def test_las_cantidades_se_leen_en_digitos_y_con_palabras(texto, esperado):
    from decimal import Decimal

    leidas = [(c.numero, c.unidad, c.con_escala) for c in cifras.cantidades(texto)]
    assert leidas == [(Decimal(n), u, e) for n, u, e in esperado]


def test_four_no_se_lee_como_for_aunque_la_voz_lo_haga():
    """Medido al construirlo: el normalizador de la voz da «for» para «four» (regla -our → -or), y sin la
    corrección local «four percent» no sería una cantidad y el gate 1 lo dejaría pasar sin mirarlo."""
    assert [c.numero for c in cifras.cantidades("four percent")] == [4]
    assert [c.numero for c in cifras.cantidades("ninety-four dollars")] == [94]


# --- el gate 1 de economía ----------------------------------------------------------------------------


_VG = None


def _verificador():
    global _VG
    if _VG is None:
        spec = importlib.util.spec_from_file_location("verifica_guion_f712", RAIZ / "scripts" / "verifica_guion.py")
        _VG = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_VG)
    return _VG


def _gate(tmp_path: Path, narraciones: list[str], datos: dict | None = None) -> tuple[list[str], list[str]]:
    vg = _verificador()
    datos = datos if datos is not None else _confirmada()
    (tmp_path / f"{datos['id']}.json").write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    resultado = vg.Resultado(tmp_path / "slides.json")
    respaldo = vg.respaldo_de_las_fichas([datos["id"]], _perfil(), tmp_path, resultado)
    for indice, narracion in enumerate(narraciones, start=1):
        vg.comprueba_cantidades(indice, narracion, respaldo, resultado)
    return resultado.fallos, resultado.avisos


def test_el_gate_deja_pasar_las_cifras_confirmadas_y_las_cuentas_escritas(tmp_path):
    fallos, avisos = _gate(
        tmp_path,
        [
            "Prices rose three point four percent in a year, and the float stood at $176 billion.",
            "One hundred dollars at seven percent for ten years is about one hundred ninety-seven dollars.",
            "In 2024, a basket of one hundred dollars now costs about $103.40, with prices up 3.4 percent.",
        ],
    )
    assert fallos == []
    assert any("2024" in a for a in avisos), "los años van como aviso"


def test_CONTROL_un_guion_de_economia_con_una_cifra_que_no_esta_en_la_ficha_falla(tmp_path):
    fallos, _ = _gate(tmp_path, ["The company earned forty-five billion dollars and prices rose 9 percent."])
    assert len(fallos) == 2 and all("no está en las fichas del guion" in f for f in fallos)


@pytest.mark.parametrize(
    "narracion",
    ["Costco made $4.1bn.", "It cost US$5.", "Rates near 4%-ish.", "Revenue hit 45bn.", "It sold 2.3m units."],
)
def test_CONTROL_una_cantidad_que_no_se_lee_no_pasa_en_silencio(tmp_path, narracion):
    fallos, _ = _gate(tmp_path, [narracion])
    assert len(fallos) == 1 and "no se lee como cantidad" in fallos[0]


def test_la_k_no_es_una_escala_abreviada_porque_en_economia_es_un_nombre(tmp_path):
    """Control positivo de «45bn»: «10-K» y «401(k)» se normalizan a «10k» y «401k», y no son cantidades."""
    fallos, _ = _gate(tmp_path, ["Its 10-K says the 401(k) plan grew."])
    assert fallos == []


def test_CONTROL_el_resultado_de_una_cuenta_sin_sus_datos_en_la_lamina_falla(tmp_path):
    fallos, _ = _gate(tmp_path, ["Wait long enough and you have about $197."])
    assert len(fallos) == 1 and "no dice sus datos" in fallos[0]


def test_CONTROL_una_ficha_sin_confirmar_no_pasa_el_gate(tmp_path):
    fallos, _ = _gate(tmp_path, ["The float stood at $176 billion."], datos=ficha.desde_dict(_comprobada()).a_dict())
    assert any("pide `cifras_confirmadas`" in f for f in fallos)


def _verifica_en_proceso(tmp_path: Path, canal: Path, narracion: str) -> str:
    guion = {
        "title": "Un título de prueba",
        "description": "Descripción.",
        "tags": ["a"],
        "thumbnail_lamina": 1,
        "thumbnail_text": "TRES PALABRAS AQUI",
        "slides": [{"slide_number": 1, "narration": narracion, "image_prompt": "a plain wall"}],
    }
    ruta = tmp_path / "slides.json"
    ruta.write_text(json.dumps(guion), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "verifica_guion.py"), str(ruta)],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=RAIZ,
        env={**os.environ, "CANAL_ACTIVO": str(canal)},
    )
    return r.stdout + r.stderr


def test_el_gate_de_un_nicho_con_cifras_da_fallo_y_el_de_otro_nicho_no_las_mira(tmp_path):
    """La condición del caso de uso: el verificador en su proceso, con el canal que lo lanza.

    Dos canales inventados (`tests/canales_de_prueba.py`) que solo se diferencian en el nicho: el de economía
    exige frase confirmada para cada cifra (`datos/autoridades/ejemplo-con-cifras.json → cifras`) y el otro no
    tiene bloque `cifras`.
    """
    from canales_de_prueba import escribe_canal, perfil_documental

    con_cifras = perfil_documental()
    con_cifras["nicho"]["id"] = "ejemplo-con-cifras"
    canal_con = escribe_canal(tmp_path / "canales", "con-cifras", con_cifras)
    canal_sin = escribe_canal(tmp_path / "canales", "sin-cifras", perfil_documental())
    narracion = "Costco earned five billion dollars last year. " + "x " * 60
    assert "no está en las fichas del guion" in _verifica_en_proceso(tmp_path, canal_con, narracion)
    assert "no está en las fichas del guion" not in _verifica_en_proceso(tmp_path, canal_sin, narracion)


# --- la CLI y la página ---------------------------------------------------------------------------------


def _cli(*argumentos: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RAIZ / "fuentes.py"), *argumentos],
        capture_output=True,
        encoding="utf-8",
        cwd=RAIZ,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def test_guarda_escribe_la_ficha_y_rechaza_una_confirmacion_escrita_a_mano(tmp_path):
    borrador = tmp_path / "borrador.json"
    borrador.write_text(json.dumps(_borrador(), ensure_ascii=False), encoding="utf-8")
    hecho = _cli("--guarda", str(borrador), "--carpeta", str(tmp_path / "fichas"))
    assert hecho.returncode == 0, hecho.stderr
    guardada = json.loads((tmp_path / "fichas" / "prueba-cifras.json").read_text(encoding="utf-8"))
    assert guardada["schema"] == "ficha-fuentes/1.1" and len(guardada["cifras"]) == 2

    borrador.write_text(json.dumps(_confirmada(), ensure_ascii=False), encoding="utf-8")
    rechazo = _cli("--guarda", str(borrador), "--carpeta", str(tmp_path / "fichas"))
    assert rechazo.returncode == 2 and "solo escribe el código" in rechazo.stderr


def test_confirma_registra_las_palabras_y_no_confirma_lo_no_encontrado(tmp_path):
    datos = _comprobada()
    datos["cifras"][1]["comprobacion"].update(encontrada=False, motivo="la frase no está")
    ruta = tmp_path / "ficha.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    rechazo = _cli("--confirma", str(ruta), "ipc", "float", "--dijo", "ok a las dos")
    assert rechazo.returncode == 2 and "no se confirma ninguna" in rechazo.stderr
    assert "confirmacion" not in json.loads(ruta.read_text(encoding="utf-8"))["cifras"][0], "todas o ninguna"

    hecho = _cli("--confirma", str(ruta), "ipc", "--dijo", "ok a la uno")
    assert hecho.returncode == 0, hecho.stderr
    confirmada = json.loads(ruta.read_text(encoding="utf-8"))["cifras"][0]
    assert confirmada["confirmacion"]["dijo"] == "ok a la uno" and confirmada["confirmacion"]["por"] == "el usuario"
    assert cifras.confirmacion_vale(confirmada)


def test_comprueba_cifras_escribe_la_comprobacion_y_una_pagina_escapada(tmp_path, monkeypatch):
    import fuentes

    datos = _borrador()
    datos["fuentes"][1]["titulo"] = "<script>alert('x')</script>"
    datos["fuentes"][1]["autores"] = ["<b>Oficina</b>"]
    ruta = tmp_path / "ficha.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    descargas = []

    def lee(url, ledger):
        descargas.append(url)
        return LECTURAS[f"url:{url}"]()

    monkeypatch.setattr(documento, "lee", lee)
    assert fuentes.cmd_comprueba_cifras(str(ruta), None, abrir=False) == 0
    assert sorted(descargas) == sorted(u[4:] for u in (URL_PDF, URL_HTML)), "una descarga por documento"
    escrita = json.loads(ruta.read_text(encoding="utf-8"))
    assert all(c["comprobacion"]["encontrada"] for c in escrita["cifras"])
    html = (tmp_path / "ficha.confirmacion.html").read_text(encoding="utf-8")
    assert "<script>alert" not in html and "&lt;script&gt;" in html and "&lt;b&gt;Oficina" in html
    assert "#page=2" in html and "Dime en la conversación cuáles confirmas" in html


def test_la_pagina_solo_enlaza_https_y_marca_cada_estado():
    datos = _comprobada()
    datos["fuentes"][0]["url"] = "javascript:alert(1)"
    datos["cifras"][0]["comprobacion"].update(encontrada=False, lectura="manual")
    html = pagina_mod.pagina_de_confirmacion(datos)
    assert 'href="javascript' not in html
    assert 'class="cifra ambar"' in html and "LECTURA MANUAL" in html
    datos["cifras"][0]["comprobacion"].update(lectura="automatica", motivo="la frase no está")
    assert 'class="cifra rojo"' in pagina_mod.pagina_de_confirmacion(datos)


# --- el título que se publica (F7.12, tras ver la página: «printmgr file») ------------------------------


def test_la_cita_publica_el_titulo_escrito_y_sin_el_el_del_proveedor():
    fuente = _borrador()["fuentes"][0]
    assert cifras.cita(fuente) == f"Empresa (s. f.). Annual Report 2025. {URL_PDF[4:]}"
    del fuente["titulo_publicado"]
    assert cifras.cita(fuente) == f"Empresa (s. f.). Informe. {URL_PDF[4:]}", "sin él, como las fichas del primer canal"


def test_CONTROL_un_documento_sin_titulo_publicado_no_se_guarda():
    assert not _duros(_borrador())
    datos = _borrador()
    del datos["fuentes"][0]["titulo_publicado"]
    assert any("titulo_publicado" in p for p in _duros(datos))


def test_CONTROL_cambiar_la_cita_despues_de_confirmar_le_quita_el_nivel():
    datos = _confirmada()
    assert ficha.nivel_efectivo(datos) == "cifras_confirmadas"
    datos["fuentes"][0]["titulo_publicado"] = "Otro título"
    assert ficha.nivel_efectivo(datos) == "solo_citas_verificadas"
    avisos = ficha.valida(ficha.desde_dict(datos), _perfil())
    assert any(p.startswith("AVISO") and "la cita de su fuente cambió" in p for p in avisos)


def test_CONTROL_confirma_no_confirma_con_una_cita_cambiada(tmp_path):
    datos = _comprobada()
    datos["fuentes"][1]["titulo_publicado"] = "Otro título, después de la página"
    ruta = tmp_path / "ficha.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    rechazo = _cli("--confirma", str(ruta), "ipc", "--dijo", "ok")
    assert rechazo.returncode == 2 and "la cita de su fuente cambió" in rechazo.stderr

    datos["fuentes"][1]["titulo_publicado"] = "Consumer Price Index Summary"
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    assert _cli("--confirma", str(ruta), "ipc", "--dijo", "ok").returncode == 0


def test_la_pagina_ensena_la_cita_y_el_titulo_de_los_metadatos():
    html = pagina_mod.pagina_de_confirmacion(_comprobada())
    assert "Se publica así en la bibliografía" in html and "Annual Report 2025" in html
    assert "Título en los metadatos del documento: Informe" in html


def test_CONTROL_un_borrador_que_cambia_la_frase_no_se_confirma_con_la_comprobacion_vieja(tmp_path):
    """Crítico 1 de la auditoría: «$999 billion» se confirmaba con la comprobación de «$176 billion»."""
    carpeta = tmp_path / "fichas"
    borrador = tmp_path / "borrador.json"
    borrador.write_text(json.dumps(_borrador(), ensure_ascii=False), encoding="utf-8")
    assert _cli("--guarda", str(borrador), "--carpeta", str(carpeta)).returncode == 0
    ruta = carpeta / "prueba-cifras.json"
    comprobada = _comprobada(json.loads(ruta.read_text(encoding="utf-8")))
    ruta.write_text(json.dumps(comprobada, ensure_ascii=False), encoding="utf-8")
    assert _cli("--confirma", str(ruta), "float", "--dijo", "ok").returncode == 0, "par positivo"

    cambiada = json.loads(ruta.read_text(encoding="utf-8"))
    float_ = next(c for c in cambiada["cifras"] if c["id"] == "float")
    float_.pop("confirmacion")
    cambiada["fuentes"][0]["pertinencia"] = "existe"
    float_["valor"], float_["frase_exacta"] = "$999 billion", "Our float stood at $999 billion at year-end."
    borrador.write_text(json.dumps(cambiada, ensure_ascii=False), encoding="utf-8")
    guardado = _cli("--guarda", str(borrador), "--carpeta", str(carpeta))
    assert guardado.returncode == 0, guardado.stderr
    rechazo = _cli("--confirma", str(ruta), "float", "--dijo", "ok")
    assert rechazo.returncode == 2 and "cambiaron después de comprobarla" in rechazo.stderr
    assert "NO SE PUEDE CONFIRMAR" in pagina_mod.pagina_de_confirmacion(json.loads(ruta.read_text(encoding="utf-8")))


# --- el redondeo que comprueba el código (filas 277 y 280) --------------------------------------------
#
# El valor va como lo da el documento y `se_dice`, como se narra. El código comprueba que es el valor
# redondeado a la precisión con que está escrito y que no se aleja más del tope del nicho (5 %).

TOPE = 5


def _con_se_dice(valor: str, se_dice: str) -> dict:
    return {"id": "x", "valor": valor, "se_dice": se_dice}


@pytest.mark.parametrize(
    "valor, se_dice",
    [
        ("$5,323 million", "$5.3 billion"),
        ("$5,323 million", "five point three billion dollars"),
        ("$5,323 million", "$5.32 billion"),
        ("$269,912 million", "$270 billion"),
        ("81,000 thousand", "81 million"),
        ("33,897", "about 34,000"),
        ("92.3%", "92%"),
        ("$20.00", "$20"),
        ("$189 million", "$189 million"),
    ],
)
def test_un_redondeo_correcto_dentro_del_tope_vale(valor, se_dice):
    assert cifras.comprueba_redondeo(_con_se_dice(valor, se_dice), TOPE) is None


@pytest.mark.parametrize(
    "valor, se_dice, motivo",
    [
        ("$5,323 million", "$5.4 billion", "no es un redondeo"),
        ("$5,323 million", "$5.33 billion", "no es un redondeo"),
        ("$5,323 million", "5.3 billion", "sin unidad"),
        ("92.3%", "$92", "va en usd"),
        ("$5,323 million", "$5.3bn", "UNA cantidad"),
        ("$5,323 million", "$5 billion or $6 billion", "UNA cantidad"),
        ("$5,323 million", "$5.0000000000000000000000000000001 trillion", "más cifras"),
    ],
)
def test_CONTROL_un_redondeo_incorrecto_falla(valor, se_dice, motivo):
    problema = cifras.comprueba_redondeo(_con_se_dice(valor, se_dice), TOPE)
    assert problema and motivo in problema


@pytest.mark.parametrize(
    "valor, se_dice, alejamiento",
    [("$149 million", "$100 million", "32.9"), ("$5,323 million", "$5 billion", "6.1"), ("3.4%", "3%", "11.8")],
)
def test_CONTROL_un_redondeo_correcto_que_se_aleja_mas_del_tope_falla(valor, se_dice, alejamiento):
    """Fila 280: «$100 million» es 149 M$ redondeado a la centena de millón, y se aleja un 33 %."""
    problema = cifras.comprueba_redondeo(_con_se_dice(valor, se_dice), TOPE)
    assert problema and f"se aleja un {alejamiento} %" in problema
    assert cifras.comprueba_redondeo(_con_se_dice(valor, se_dice), 50) is None, "control: con un tope ancho, vale"


def test_la_precision_sale_de_como_esta_escrito():
    from decimal import Decimal

    pasos = {t: cifras.una_cantidad(t).paso for t in ("$5.3 billion", "$20.00", "34,000", "197", "81 million")}
    assert pasos == {
        "$5.3 billion": Decimal(10) ** 8,
        "$20.00": Decimal("0.01"),
        "34,000": 1000,
        "197": 1,
        "81 million": Decimal(10) ** 6,
    }


def test_el_redondeo_no_entra_en_la_huella():
    """Fila 277: el redondeo no lo confirma el usuario, así que escribirlo después no le quita la confirmación."""
    datos = _confirmada()
    datos["cifras"][1]["se_dice"] = "about $180 billion"
    assert cifras.confirmacion_vale(datos["cifras"][1]) and ficha.nivel_efectivo(datos) == "cifras_confirmadas"
    assert _duros(datos) == []


def test_CONTROL_una_ficha_con_un_redondeo_que_no_casa_no_se_guarda():
    datos = _borrador()
    datos["cifras"][1]["se_dice"] = "$200 billion"  # 176 redondeado a la centena, a un 13,6 %
    assert any("cifra 2 (float)" in p and "se aleja" in p for p in _duros(datos))
    datos["cifras"][1]["se_dice"] = "$150 billion"
    assert any("cifra 2 (float)" in p and "no es un redondeo" in p for p in _duros(datos))
    datos["cifras"][1]["se_dice"] = "$176 billion"
    assert _duros(datos) == [], "control: el valor dicho tal cual es un redondeo de sí mismo"


def test_CONTROL_un_nicho_sin_tope_no_deja_redondear():
    datos = _borrador()
    datos["cifras"][1]["se_dice"] = "$180 billion"
    sin_tope = {
        **_perfil(),
        "cifras": {"exige_frase_confirmada": True, "mapa": {"minimo_videos": 3, "minimo_canales": 2}},
    }
    assert any("error_maximo_pct" in p for p in _duros(datos, sin_tope))
    assert cifras.comprueba_redondeo(datos["cifras"][1], None) is not None


def test_el_tope_del_perfil_con_cifras_es_el_5_por_ciento():
    reglas, problemas = ficha.reglas_de_cifras(_perfil())
    assert problemas == [] and ficha.tope_de_redondeo(reglas) == 5


def _con_redondeo() -> dict:
    """La ficha confirmada, con el float dicho redondeado y una cuenta que lo usa como dato real."""
    datos = _confirmada()
    datos["cifras"][1]["se_dice"] = "about $180 billion"
    datos["cuentas"].append(
        {"id": "mitad", "expresion": "flotante / 2",
         "datos": {"flotante": {"valor": 176000000000, "tipo": "real", "cifra": "float"}},
         "resultado": 88000000000.0, "se_dice": "$88 billion", "redondeo": -9}
    )  # fmt: skip
    return datos


def test_el_gate_deja_decir_el_redondeo_de_una_cifra_confirmada(tmp_path):
    fallos, _ = _gate(tmp_path, ["The float stood at about $180 billion."], datos=_con_redondeo())
    assert fallos == []


def test_el_dato_de_una_cuenta_se_puede_decir_redondeado(tmp_path):
    """La cuenta se calcula con el valor exacto; la lámina puede decir su dato con el redondeo de su cifra."""
    fallos, _ = _gate(tmp_path, ["Half of a float of about $180 billion is $88 billion."], datos=_con_redondeo())
    assert fallos == []


def test_CONTROL_el_gate_no_deja_decir_otro_redondeo_ni_el_de_una_cifra_sin_confirmar(tmp_path):
    fallos, _ = _gate(tmp_path, ["The float stood at about $170 billion."], datos=_con_redondeo())
    assert len(fallos) == 1 and "no está en las fichas del guion" in fallos[0]
    sin_confirmar = _comprobada()
    sin_confirmar["cifras"][1]["se_dice"] = "about $180 billion"
    fallos, _ = _gate(tmp_path, ["The float stood at about $180 billion."], datos=sin_confirmar)
    assert any("no está en las fichas del guion" in f for f in fallos)


def test_la_pagina_ensena_el_redondeo_y_que_no_se_confirma():
    datos = _comprobada()
    datos["cifras"][1]["se_dice"] = "<b>about $180 billion</b>"
    html = pagina_mod.pagina_de_confirmacion(datos)
    assert "En el vídeo se dirá redondeada" in html and "no entra en tu confirmación" in html
    assert "<b>about $180" not in html and "&lt;b&gt;about $180 billion" in html


# --- la unidad de los datos de una cuenta (revisión de F7.12) --------------------------------------------


def _c(numero: str, unidad: str | None) -> cifras.Cantidad:
    from decimal import Decimal

    return cifras.Cantidad(Decimal(numero), unidad, False, numero)


@pytest.mark.parametrize(
    "valor, dicha, de_su_cifra, casa",
    [
        (0.07, ("7", "pct"), None, True),  # ejemplo en tanto por uno
        (100, ("100", "usd"), None, True),  # ejemplo sin unidad
        (100, ("100", "pct"), None, False),  # «100%» no es el capital de ejemplo de 100
        (90, ("90", "pct"), ("90", "pct"), True),  # dato real de la cifra «90%»
        (0.034, ("3.4", "pct"), ("3.4", "pct"), True),  # dato real en tanto por uno
        (90, ("90", "usd"), ("90", "pct"), False),  # «$90» no dice un 90 %
        (205000000, ("205000000", None), ("205000000", "usd"), True),
    ],
)
def test_un_dato_se_dice_con_su_unidad(valor, dicha, de_su_cifra, casa):
    cifra = _c(*de_su_cifra) if de_su_cifra else None
    assert cifras.dato_casa_con(valor, _c(*dicha), cifra) is casa


def test_CONTROL_100_por_cien_no_casa_con_el_capital_de_ejemplo(tmp_path):
    fallos, _ = _gate(tmp_path, ["Imagine a 100% return."])
    assert len(fallos) == 1 and "no está en las fichas del guion" in fallos[0]


def test_CONTROL_los_puntos_porcentuales_se_respaldan(tmp_path):
    fallos, _ = _gate(tmp_path, ["Rates rose 3 percentage points."])
    assert len(fallos) == 1 and "no está en las fichas del guion" in fallos[0]


# --- el proveedor `documento`: topes y juegos de caracteres (revisión de F7.12) ---------------------------


def test_CONTROL_pasar_del_tope_al_descomprimir_es_un_error_y_no_un_corte(monkeypatch):
    monkeypatch.setattr(documento, "TOPE_DE_BYTES", len(HTML) // 2)
    lectura = _lectura(gzip.compress(HTML), "text/html", codificacion="gzip")
    assert lectura.formato is None and "al descomprimirse" in (lectura.error or "")
    cifra = _borrador()["cifras"][0]
    assert cifras.se_puede_confirmar({**cifra, "comprobacion": cifras.comprueba_frase(cifra, lectura)}) is not None
    monkeypatch.setattr(documento, "TOPE_DE_BYTES", len(HTML) * 2)
    assert _lectura(gzip.compress(HTML), "text/html", codificacion="gzip").formato == "html", "control"


def test_CONTROL_un_gzip_cortado_o_roto_es_ilegible():
    comprimido = gzip.compress(HTML)
    assert "cortado" in (_lectura(comprimido[: len(comprimido) // 2], "text/html", codificacion="gzip").error or "")
    assert "no se dejan abrir" in (_lectura(b"no es gzip", "text/html", codificacion="deflate").error or "")


def test_un_charset_desconocido_no_revienta():
    lectura = documento.completa(
        documento.Lectura(url="https://example.org/x", descargado_el="2026-10-06T10:00:00+00:00"),
        FRASE_IPC.encode("utf-8"),
        "text/plain",
        "x-juego-inventado",
    )
    assert lectura.formato == "texto" and FRASE_IPC in lectura.paginas[0]


def test_CONTROL_la_descarga_tiene_un_tope_de_tiempo_total(monkeypatch):
    """Un servidor que suelta bytes sin parar no agota el `timeout` del socket, que es por operación.

    El goteo se lee con `read1`, que vuelve con lo que haya. `read(n)` esperaría a reunir los n bytes sin
    mirar el reloj (auditoría del 06-10): por eso aquí falla, y la prueba cae si alguien vuelve a él.
    """

    class _Goteo(_Respuesta):
        def read(self, tope=-1):
            pytest.fail("read(n) espera a reunir n bytes y un goteo lo deja bloqueado: se lee con read1")

        def read1(self, tope=-1):
            return b"x" * 10

    reloj = iter(range(0, 1_000_000, 50))
    monkeypatch.setattr(documento.time, "monotonic", lambda: next(reloj))
    monkeypatch.setattr(documento._ABRIDOR, "open", lambda peticion, timeout: _Goteo(b""))
    ledger = base.LedgerLlamadas()
    assert documento.Documento().resuelve(URL_HTML, ledger) is None
    assert ledger.resumen()["fallidas"] == 1
    assert "en total" in (documento.lee(URL_HTML[4:], base.LedgerLlamadas()).error or "")
