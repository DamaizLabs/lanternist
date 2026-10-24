"""La onda de ecualizador (F4.11), mirando los píxeles que salen y no la fórmula.

Correr: .venv\\Scripts\\python -m pytest -q tests

**Por qué estas pruebas renderizan.** Lo que la ficha pide comprobar —«la onda reacciona al audio
real»— no se puede afirmar leyendo el código: una capa mal alimentada produce un vídeo
perfectamente válido con una onda quieta, o con una onda que sube y baja sola. Aquí se compone
sobre un vídeo con **silencio en la primera mitad y tono en la segunda** y se cuentan los píxeles
encendidos en cada una.

**Y por qué hay pruebas del MOVIMIENTO, que son nuevas.** El rework de F4.11 existe porque se
rechazó la primera versión de las cápsulas: «al verla en movimiento es donde ahora falla… lo que
hace es desplazarse hacia la izquierda con diferente amplitud de onda pero no se ve moverse la
onda». Aquello era una ventana deslizante de la envolvente —un scroll— y esto es un ecualizador:
cada cápsula es una banda de frecuencia y **se queda en su sitio**. Un scroll y un ecualizador se
parecen mucho en una captura y son opuestos en movimiento, así que las dos pruebas que los
distinguen usan un **tono puro**: con la frecuencia fija, el máximo se queda en la misma cápsula;
si la frecuencia cambia, el máximo cambia de cápsula. Con la envolvente deslizante, la primera
fallaría.

**Y por qué hay una prueba de que NADA cambia.** La onda es una capa nueva de un formato nuevo.
El canal que ya tiene un vídeo montado no la declara, y si alguien la volviera el comportamiento
por defecto su montaje cambiaría sin que nadie lo hubiera pedido. Esa prueba compara el md5 del
fichero antes y después de pasar por la etapa.

**La otra mitad es la frontera de capas de F4.9**: el aspecto es del canal, así que media
declaración se detiene en vez de heredar el aspecto de otro canal. Cada campo que falta tiene su
caso.
"""

import hashlib
import itertools
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from lib import config, onda

RAIZ = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg 7.1 es parte del stack del proyecto; sin él no hay nada que medir",
)

# El aspecto completo de un canal imaginario, en las medidas del fotograma real (1920x1080).
# Se copia y se rompe campo a campo en las pruebas de la guarda.
ASPECTO = {
    "barras": 64,
    "ancho_px": 1280,
    "alto_px": 240,
    "x_px": 320,
    "eje_y_px": 470,
    "grosor_px": 14,
    "radio_px": 7,
    "color": "#F2C078",
    "opacidad": 0.75,
    # El acabado es obligatorio desde el 05-09: un canal tiene que DECIR si su cápsula es
    # opaca o de cristal, porque se ven distinto y no se hereda del canal de al lado.
    "acabado": "opaco",
}

# El mismo aspecto con el acabado de cristal, para las pruebas del grafo nuevo.
ASPECTO_CRISTAL = {
    **ASPECTO,
    "acabado": "cristal",
    "color_del_filo": "#8A5A18",
    "translucidez": 0.45,
    "desenfoque_px": 2.4,
    "velo_del_fondo": 0.35,
}


def _onda(**campos) -> onda.Onda:
    """Construye un `Onda` rellenando los campos del acabado que la prueba no nombre.

    Existe para que anadir un campo de acabado no obligue a tocar cinco constructores: lo que estas
    pruebas miden es la geometria y el dibujo, no la lista de campos. La lista la vigila
    `test_falta_un_campo_obligatorio`, que se parametriza sola desde `onda.OBLIGATORIOS`.
    """
    base = {"acabado": "opaco", "color_del_filo": "", "translucidez": 0.0, "desenfoque_px": 0.0, "velo_del_fondo": 0.0}
    return onda.Onda(**{**base, **campos})


def _perfil(onda_declarada) -> dict:
    """Un perfil de canal con lo justo: el bloque de composición y nada más."""
    return {"formato": {"composicion": {"onda_de_ecualizador": onda_declarada}}}


def _sin_onda() -> dict:
    """Un canal anterior a F4.11: ni siquiera tiene el bloque de composición."""
    return {"formato": {"duracion_objetivo_min": [8, 10]}}


# --- La frontera de capas: el aspecto es del canal y media declaración se para ---------------


def test_un_canal_que_no_la_declara_no_lleva_onda():
    assert onda.declarada(_sin_onda()) is False
    assert onda.aspecto_del_canal(_sin_onda()) is None


def test_un_canal_que_la_apaga_tampoco_la_lleva():
    """`false` y ausencia montan igual, pero solo una de las dos está decidida."""
    assert onda.declarada(_perfil(False)) is False
    assert onda.aspecto_del_canal(_perfil(False)) is None


def test_declararla_con_un_true_pelado_falla_cerrada_y_dice_que_escribir():
    with pytest.raises(onda.OndaError) as exc:
        onda.aspecto_del_canal(_perfil(True))
    mensaje = str(exc.value)
    # El mensaje tiene que servir para arreglarlo sin abrir el código: los nueve campos y dónde.
    for campo in onda.OBLIGATORIOS:
        assert campo in mensaje
    assert onda.CLAVE_PERFIL in mensaje


@pytest.mark.parametrize("campo", sorted(onda.OBLIGATORIOS))
def test_falta_un_campo_cualquiera_y_se_para_nombrandolo(campo):
    aspecto = {k: v for k, v in ASPECTO.items() if k != campo}
    with pytest.raises(onda.OndaError, match=campo):
        onda.aspecto_del_canal(_perfil(aspecto))


@pytest.mark.parametrize(
    "cambio, esperado",
    [
        ({"color": "rojo"}, "hexadecimal"),
        ({"opacidad": 0}, "opacidad"),
        ({"opacidad": 1.5}, "opacidad"),
        ({"barras": 3}, "barras"),
        ({"barras": 600}, "de aire"),  # 2,1 px de paso con 14 de grosor: se tocarían
        ({"grosor_px": 1}, "grosor_px"),
        ({"grosor_px": 20}, "de aire"),  # 20 px de grosor en un paso de 20: cero aire
        ({"radio_px": 12}, "radio_px"),  # más redondo que un semicírculo
        ({"radio_px": -1}, "radio_px"),
        ({"alto_px": 20}, "alto_px"),  # menos de dos veces el grosor: sin recorrido
        ({"alto_px": 241}, "par"),  # impar: la onda simétrica quedaría 1 px descentrada
        ({"x_px": 900}, "horizontal"),
        ({"eje_y_px": 100}, "vertical"),  # el eje menos media caja se sale por arriba
        ({"eje_y_px": 1000}, "vertical"),  # y por abajo
        ({"ancho_px": "mucho"}, "entero"),
    ],
)
def test_un_aspecto_imposible_se_para_antes_de_montar(cambio, esperado):
    """Cada uno de estos produciría un vídeo SIN error: onda invisible, recortada o maciza."""
    with pytest.raises(onda.OndaError, match=esperado):
        onda.aspecto_del_canal(_perfil({**ASPECTO, **cambio}))


def test_el_negro_ya_es_un_color_valido_y_antes_no():
    """Una restricción que se retira con el mecanismo, no un descuido.

    Con `showfreqs` el fondo de la onda se recortaba con una clave de color negra, así que una
    onda negra **se borraba a sí misma** y el vídeo salía sin onda y sin ningún error por medio;
    por eso la guarda lo rechazaba. La capa se dibuja ahora en RGBA con su propio canal alfa: no
    hay nada que recortar y el negro es un color como cualquier otro — que sobre el cielo pálido
    de un canal puede ser justo el que contrasta.
    """
    negro = onda.aspecto_del_canal(_perfil({**ASPECTO, "color": "#000000"}))
    assert negro is not None and negro.rgb == (0, 0, 0)
    capa = np.asarray(onda.capa(np.full(negro.barras, 0.5), negro))
    assert (capa[:, :, 3] > 0).sum() > 0, "una onda negra tiene que pintarse, no borrarse"


def test_el_nombre_viejo_del_eje_no_se_hereda_en_silencio():
    """`linea_base_y_px` cambió de nombre porque cambió de significado, y eso no se adivina.

    Copiar el valor tal cual mete la onda `alto_px/2` px por debajo de donde el perfil creía que
    se apoyaba, o sea dentro de la banda de los subtítulos. El mensaje da el eje equivalente.
    """
    viejo = {k: v for k, v in ASPECTO.items() if k != "eje_y_px"}
    viejo["linea_base_y_px"] = 520
    with pytest.raises(onda.OndaError) as exc:
        onda.aspecto_del_canal(_perfil(viejo))
    mensaje = str(exc.value)
    assert "eje_y_px" in mensaje and "linea_base_y_px" in mensaje
    assert "400" in mensaje, "tiene que decir qué eje deja la onda donde estaba (520 - 240/2)"


def test_el_aspecto_bueno_se_lee_entero_y_deriva_la_caja():
    a = onda.aspecto_del_canal(_perfil(ASPECTO))
    assert a.color == "#F2C078" and a.rgb == (242, 192, 120)
    assert a.alfa == 191  # el 75 % de 255
    # La caja está centrada en el eje: 470 ± 120.
    assert a.y_px == 350 and a.borde_inferior_px == 590
    assert a.paso_px == 20.0
    assert a.separacion_px == 6.0  # 20 de paso menos 14 de grosor: el aire es derivado


def test_subir_el_alto_crece_a_los_dos_lados_sin_mover_el_eje():
    """El ancla es el EJE, y es lo que protege la banda de los subtítulos de una sorpresa."""
    baja = onda.aspecto_del_canal(_perfil(ASPECTO))
    alta = onda.aspecto_del_canal(_perfil({**ASPECTO, "alto_px": 400}))
    assert baja.eje_y_px == alta.eje_y_px == 470
    assert (alta.y_px, alta.borde_inferior_px) == (270, 670)
    assert baja.eje_y_px - baja.y_px == baja.borde_inferior_px - baja.eje_y_px


def test_ningun_canal_del_repo_declara_la_onda_a_medias():
    """Los perfiles de verdad, no los inventados: si uno se rompe, el piloto se para al montar."""
    for perfil in sorted((RAIZ / "canales").glob("*/perfil.json")):
        d = json.loads(perfil.read_text(encoding="utf-8"))
        onda.aspecto_del_canal(d)  # o devuelve el aspecto, o levanta con el motivo


# --- El análisis: cada cápsula es una banda de frecuencia ------------------------------------

TASA = onda.TASA_ANALISIS


def _wav(destino: Path, expresion: str, duracion: float = 3.0) -> Path:
    """Un `.wav` mono sintético, descrito con la expresión de `aevalsrc`."""
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"aevalsrc='{expresion}':s={TASA}:d={duracion}", "-ac", "1", str(destino)],
        check=True, capture_output=True, timeout=300,
    )  # fmt: skip
    return destino


def _rms_por_fotograma(wav: Path, fotogramas: int, fps: float = 24.0) -> np.ndarray:
    """El volumen del instante de cada fotograma, medido aparte del módulo."""
    crudo = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(wav), "-ac", "1", "-ar", str(TASA),
         "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        capture_output=True, check=True, timeout=300,
    ).stdout  # fmt: skip
    muestras = np.frombuffer(crudo, dtype=np.int16).astype(np.float64) / 32768.0
    por_fotograma = int(TASA / fps)
    salida = []
    for n in range(fotogramas):
        trozo = muestras[n * por_fotograma : (n + 1) * por_fotograma]
        salida.append(float(np.sqrt((trozo**2).mean())) if len(trozo) else 0.0)
    return np.array(salida)


def test_la_altura_de_la_onda_sigue_al_volumen_del_instante(tmp_path):
    """El corazón de la ficha, medido en el análisis: altura de cápsula contra RMS del fotograma.

    El audio es un tono de 400 Hz con la amplitud modulada por una onda lenta, así que sube y
    baja de volumen 1,5 veces en los 3 s. La correlación se mide contra `cbrt` del RMS porque la
    escala de amplitud del módulo es la raíz cúbica: comparar contra el RMS crudo mediría la
    escala, no el seguimiento.
    """
    wav = _wav(tmp_path / "modulado.wav", "sin(2*PI*400*t)*(0.5+0.5*sin(2*PI*0.5*t))")
    fotogramas = 72
    valores, medidas = onda.energia_por_banda(wav, 32, fotogramas, 24.0)
    assert valores.shape == (fotogramas, 32)
    assert medidas["sin_narracion"] is False

    rms = _rms_por_fotograma(wav, fotogramas)
    correlacion = float(np.corrcoef(np.cbrt(rms), valores.max(axis=1))[0, 1])
    assert correlacion > 0.8, f"la onda no sigue al volumen: correlación {correlacion:.3f}"


def test_con_un_tono_fijo_la_capsula_no_se_mueve_de_sitio(tmp_path):
    """Lo que se pidió y la primera versión no hacía: la onda se mueve, no se desplaza.

    Con una frecuencia constante y el volumen cambiando, la energía tiene que quedarse en la
    misma cápsula en **todos** los fotogramas con sonido. Una ventana deslizante de la envolvente
    —el mecanismo que él rechazó— movería el máximo una cápsula por ventana de tiempo.
    """
    wav = _wav(tmp_path / "tono.wav", "sin(2*PI*1000*t)*(0.4+0.6*sin(2*PI*1.5*t))")
    valores, _ = onda.energia_por_banda(wav, 48, 72, 24.0)
    con_sonido = valores[valores.max(axis=1) > 0.5]
    assert len(con_sonido) > 24, "la prueba necesita fotogramas con sonido de sobra"
    picos = set(np.argmax(con_sonido, axis=1).tolist())
    assert len(picos) == 1, f"el máximo se ha movido de cápsula con la frecuencia fija: {sorted(picos)}"


def test_si_cambia_la_frecuencia_cambia_la_capsula(tmp_path):
    """La otra cara: es un ecualizador, así que la posición SÍ depende de la frecuencia.

    Sin esto, la prueba de arriba la pasaría también un mecanismo que pintara siempre la misma
    cápsula.
    """
    wav = _wav(tmp_path / "dos-tonos.wav", "sin(2*PI*200*t)*lt(t\\,1)+sin(2*PI*4000*t)*gt(t\\,2)")
    valores, _ = onda.energia_por_banda(wav, 48, 72, 24.0)
    grave = int(np.argmax(valores[12]))  # t = 0,5 s
    agudo = int(np.argmax(valores[62]))  # t = 2,6 s
    assert grave < agudo, f"el tono agudo tiene que caer más a la derecha: {grave} vs {agudo}"
    assert agudo - grave > 10, f"200 Hz y 4 kHz deberían estar lejos: {grave} vs {agudo}"


def test_el_silencio_no_se_amplifica_hasta_parecer_una_onda(tmp_path):
    """Normalizar el silencio pintaría una onda inventada a tope de escala. Se detecta y se dice."""
    wav = _wav(tmp_path / "silencio.wav", "0")
    valores, medidas = onda.energia_por_banda(wav, 32, 48, 24.0)
    assert medidas["sin_narracion"] is True
    assert float(valores.max()) == 0.0


def test_un_audio_mas_corto_que_el_video_no_revienta_ni_repite(tmp_path):
    """El montaje puede acabar en negro sin voz, y el análisis pide fotogramas que no existen."""
    wav = _wav(tmp_path / "corto.wav", "sin(2*PI*500*t)", duracion=1.0)
    valores, medidas = onda.energia_por_banda(wav, 32, 72, 24.0)  # 3 s de vídeo, 1 s de audio
    assert valores.shape == (72, 32)
    assert medidas["duracion_audio_s"] == pytest.approx(1.0, abs=0.05)
    assert float(valores[-1].max()) == 0.0, "el final sin audio tiene que quedar en el mínimo"


def test_el_analisis_no_depende_del_tamano_del_lote(tmp_path, monkeypatch):
    """El troceado existe para no pedir 300 MB de memoria en un vídeo de 25 min, y no debe verse.

    Sin esta prueba, un error de un fotograma en el corte de los lotes daría una onda con
    hipidos cada `LOTE_ANALISIS` fotogramas y el gate no lo notaría.
    """
    wav = _wav(tmp_path / "voz.wav", "sin(2*PI*600*t)*(0.5+0.5*sin(2*PI*2*t))")
    entero, _ = onda.energia_por_banda(wav, 24, 96, 24.0)
    monkeypatch.setattr(onda, "LOTE_ANALISIS", 7)
    troceado, _ = onda.energia_por_banda(wav, 24, 96, 24.0)
    assert np.allclose(entero, troceado)


def test_las_bandas_de_abajo_no_son_un_calco_de_la_siguiente():
    """La trampa del banco de filtros: una banda más estrecha que un bin saldría a cero.

    Con 96 cápsulas entre 80 Hz y 8 kHz, 19 bandas son más estrechas que los 23,4 Hz de un bin.
    Sin el respaldo de interpolación, 9 de las 96 cápsulas (el 9,4 %) estarían planas: son las
    bandas de abajo, cuya base es más estrecha que el bin de 23,44 Hz de la FFT.
    """
    matriz, centros = onda.banco_de_bandas(96)
    assert matriz.shape[0] == 96
    assert (matriz.sum(axis=1) > 0).all(), "ninguna banda puede quedarse sin peso"
    filas = [tuple(np.nonzero(matriz[b])[0].tolist()) for b in range(96)]
    assert len(set(filas)) > 60, "demasiadas bandas mirando exactamente los mismos bins"
    assert centros[0] < centros[-1]


# --- El dibujo: la forma aprobada, medida en la capa ----------------------------------------

CAPA = _onda(
    barras=24, ancho_px=480, alto_px=120, x_px=100, eje_y_px=300, grosor_px=16, radio_px=8,
    color="#FFFFFF", opacidad=1.0,
)  # fmt: skip


def _columnas(mascara: np.ndarray) -> list[tuple[int, int]]:
    """(inicio, ancho) de cada racha de columnas pintadas. Es dónde está cada cápsula."""
    pintada = mascara.any(axis=0)
    salida, x = [], 0
    for encendida, grupo in itertools.groupby(pintada):
        largo = len(list(grupo))
        if encendida:
            salida.append((x, largo))
        x += largo
    return salida


def test_la_capa_pinta_una_capsula_por_banda_con_el_grosor_del_canal():
    mascara = np.asarray(onda.capa(np.full(CAPA.barras, 0.6), CAPA))[:, :, 3] > 0
    columnas = _columnas(mascara)
    assert len(columnas) == CAPA.barras
    assert {ancho for _, ancho in columnas} == {CAPA.grosor_px}
    # El paso es uniforme: la separación entre inicios es siempre la misma.
    inicios = [x for x, _ in columnas]
    assert set(np.diff(inicios).tolist()) == {int(CAPA.paso_px)}


def test_la_forma_es_de_capsula_y_no_rectangular():
    """La punta es un semicírculo: en la fila de arriba la cápsula es más estrecha que en su eje.

    Si alguien sustituyera el dibujo por un `rectangle`, esta es la prueba que lo caza.
    """
    mascara = np.asarray(onda.capa(np.full(CAPA.barras, 1.0), CAPA))[:, :, 3] > 0
    filas = np.nonzero(mascara.any(axis=1))[0]
    arriba, medio = int(filas[0]), CAPA.alto_px // 2
    ancho_arriba = int(mascara[arriba].sum()) / CAPA.barras
    ancho_medio = int(mascara[medio].sum()) / CAPA.barras
    assert ancho_medio == CAPA.grosor_px
    assert ancho_arriba < ancho_medio / 2, f"la punta no está redondeada: {ancho_arriba} de {ancho_medio}"


def test_en_silencio_la_capsula_es_un_punto_redondo_y_no_desaparece():
    """El suelo del dibujo: media cápsula nunca baja de su radio, así que queda un punto.

    Es lo que se ve en la variante aprobada: la línea de puntos de los tramos callados.
    """
    mascara = np.asarray(onda.capa(np.zeros(CAPA.barras), CAPA))[:, :, 3] > 0
    filas = np.nonzero(mascara.any(axis=1))[0]
    assert len(filas) == CAPA.grosor_px, "en silencio la cápsula mide su grosor de alto: es un círculo"
    assert {ancho for _, ancho in _columnas(mascara)} == {CAPA.grosor_px}


def test_la_onda_es_simetrica_sobre_el_eje():
    """La petición literal: «que se mueva tanto por arriba como por abajo»."""
    valores = np.linspace(0.1, 1.0, CAPA.barras)
    mascara = np.asarray(onda.capa(valores, CAPA))[:, :, 3] > 0
    arriba = mascara[: CAPA.alto_px // 2]
    abajo = mascara[CAPA.alto_px // 2 :]
    assert arriba.sum() == abajo.sum() > 0
    assert np.array_equal(arriba, abajo[::-1]), "la mitad de abajo no es el espejo de la de arriba"


def test_cada_capsula_se_queda_en_su_sitio_aunque_cambie_de_altura():
    """El defecto que rehízo esta feature, medido en la capa: la altura cambia, la columna no."""
    quieta = _columnas(np.asarray(onda.capa(np.full(CAPA.barras, 0.2), CAPA))[:, :, 3] > 0)
    fuerte = _columnas(np.asarray(onda.capa(np.random.default_rng(7).random(CAPA.barras), CAPA))[:, :, 3] > 0)
    assert [x for x, _ in quieta] == [x for x, _ in fuerte]


def test_la_capa_a_tope_de_escala_llena_la_caja_y_no_la_desborda():
    capa = np.asarray(onda.capa(np.full(CAPA.barras, 1.0), CAPA))
    assert capa.shape == (CAPA.alto_px, CAPA.ancho_px, 4)
    filas = np.nonzero((capa[:, :, 3] > 0).any(axis=1))[0]
    assert (int(filas[0]), int(filas[-1])) == (0, CAPA.alto_px - 1)


def test_la_opacidad_y_el_color_del_canal_son_lo_que_se_pinta():
    aspecto = onda.aspecto_del_canal(_perfil(ASPECTO))
    capa = np.asarray(onda.capa(np.full(aspecto.barras, 0.8), aspecto))
    pintados = capa[capa[:, :, 3] > 0]
    assert set(np.unique(pintados[:, 3]).tolist()) == {191}  # 0,75 × 255
    assert tuple(pintados[0][:3].tolist()) == aspecto.rgb


# --- La orden de FFmpeg: lo que se le pide sin renderizar ------------------------------------


def test_la_capa_entra_con_la_cadencia_del_video():
    """La trampa nº 1 de esta etapa: la capa a 25 fps sobre un montaje a 24 va desincronizada.

    No cambia la duración ni el número de fotogramas del vídeo —la guarda de `aplica` no lo
    vería—, solo hace que la onda vaya por detrás de la voz. Por eso se comprueba aquí.
    """
    args = onda.comando("e.mp4", "s.mp4", onda.aspecto_del_canal(_perfil(ASPECTO)), "24/1")
    assert args[args.index("-framerate") + 1] == "24/1"
    assert "25" not in args[args.index("-framerate") + 1]


def test_el_comando_declara_la_capa_del_tamano_exacto_de_la_caja():
    """La tubería es cruda: un tamaño distinto del de la capa desplazaría todos los píxeles."""
    aspecto = onda.aspecto_del_canal(_perfil(ASPECTO))
    args = onda.comando("e.mp4", "s.mp4", aspecto, "24/1")
    assert args[args.index("-s") + 1] == f"{aspecto.ancho_px}x{aspecto.alto_px}"
    assert args[args.index("-pix_fmt") + 1] == "rgba"
    assert np.asarray(onda.capa(np.zeros(aspecto.barras), aspecto)).shape == (
        aspecto.alto_px,
        aspecto.ancho_px,
        4,
    )


def test_el_grafo_compone_donde_dice_el_canal():
    aspecto = onda.aspecto_del_canal(_perfil(ASPECTO))
    grafo = onda.grafo(aspecto, "24/1")
    assert f"overlay=x={aspecto.x_px}:y={aspecto.y_px}" in grafo
    # Si el audio acabara antes que el vídeo, lo que queda es fondo limpio y no la onda congelada.
    assert "eof_action=pass" in grafo


def test_esta_pasada_no_recodifica_el_audio():
    """Cada pista pasa por el codificador una sola vez; esta etapa solo dibuja."""
    args = onda.comando("e.mp4", "s.mp4", onda.aspecto_del_canal(_perfil(ASPECTO)), "24/1")
    assert args[args.index("-c:a") + 1] == "copy"


# --- Lo que se ve: se renderiza y se cuentan los píxeles -------------------------------------

# Vídeo de prueba: fondo gris plano y un audio con SILENCIO en la primera mitad y tono en la
# segunda. El fondo es plano a propósito — así todo píxel que no sea gris es onda.
_FONDO = "color=c=gray:s=640x360:r=24:d=2"
_AUDIO = "aevalsrc='sin(2*PI*300*t)*gt(t\\,1)':s=48000:d=2"
# Caja pequeña, a la medida del vídeo de prueba: la geometría con las medidas reales ya la
# comprueban las pruebas de arriba, y aquí lo que importa es contar cápsulas deprisa.
CAJA = _onda(
    barras=16, ancho_px=400, alto_px=100, x_px=120, eje_y_px=200, grosor_px=12, radio_px=6,
    color="#FF0000", opacidad=1.0,
)  # fmt: skip


def _video_de_prueba(destino: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", _FONDO,
         "-f", "lavfi", "-i", _AUDIO,
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(destino)],
        check=True, capture_output=True,
    )  # fmt: skip
    return destino


def _mascara_de_onda(video: Path, segundo: float, caja: onda.Onda) -> np.ndarray:
    """Máscara de los píxeles de la caja que ya no son el gris del fondo: la onda pintada."""
    from PIL import Image

    png = video.parent / f"f-{segundo}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", str(segundo), "-i", str(video),
         "-frames:v", "1", "-vf", f"crop={caja.ancho_px}:{caja.alto_px}:{caja.x_px}:{caja.y_px}", str(png)],
        check=True, capture_output=True,
    )  # fmt: skip
    a = np.asarray(Image.open(png).convert("RGB")).astype(int)
    # El rojo de la onda contra el gris del fondo: basta con mirar cuánto se separa el canal rojo.
    return (a[:, :, 0] - a[:, :, 2]) > 40


def test_la_onda_sigue_al_audio_y_no_se_mueve_sola(tmp_path):
    """En silencio la onda es una línea de puntos y con sonido sube. Contado sobre el vídeo."""
    entrada = _video_de_prueba(tmp_path / "entrada.mp4")
    salida = tmp_path / "con-onda.mp4"
    onda.compone(entrada, salida, CAJA, "24/1")

    silencio = int(_mascara_de_onda(salida, 0.5, CAJA).sum())
    sonido = int(_mascara_de_onda(salida, 1.5, CAJA).sum())
    # El suelo del dibujo es un punto redondo por cápsula: «plano» no es cero.
    suelo = CAJA.barras * CAJA.grosor_px**2
    assert silencio <= suelo, f"con el audio en silencio la onda ya está crecida: {silencio} px"
    assert sonido > silencio * 2, f"la onda no reacciona al audio: {silencio} px en silencio, {sonido} px con tono"


def test_en_el_video_las_capsulas_ocupan_las_mismas_columnas_en_todo_momento(tmp_path):
    """Lo mismo que la prueba de la capa, pero sobre los píxeles del vídeo montado.

    Es la comprobación de que entre el dibujo y el fotograma final no hay nada que desplace la
    onda: ni el tamaño de la tubería, ni el `overlay`, ni un remuestreo.
    """
    entrada = _video_de_prueba(tmp_path / "entrada.mp4")
    salida = tmp_path / "con-onda.mp4"
    onda.compone(entrada, salida, CAJA, "24/1")

    quieta = _mascara_de_onda(salida, 0.5, CAJA)
    fuerte = _mascara_de_onda(salida, 1.5, CAJA)
    assert [x for x, _ in _columnas(quieta)] == [x for x, _ in _columnas(fuerte)]
    assert fuerte.sum() > quieta.sum(), "la prueba necesita dos alturas distintas para valer"


def test_componer_la_onda_no_cambia_la_duracion_ni_la_cadencia(tmp_path):
    entrada = _video_de_prueba(tmp_path / "entrada.mp4")
    salida = tmp_path / "con-onda.mp4"
    antes = onda.sonda(entrada)
    onda.compone(entrada, salida, CAJA, antes["cadencia"])
    assert onda.sonda(salida) == antes


def test_sondar_un_contenedor_sin_nb_frames_cuenta_los_fotogramas(tmp_path):
    """La rama de respaldo de `sonda()`, que hasta ahora era código que el gate no pisaba.

    `sonda()` lee los fotogramas de la cabecera porque contarlos uno a uno cuesta 12,1 s sobre un
    montaje de 105 s, y son dos medidas por etapa. Pero un `.ts` no trae `nb_frames`, así que hay
    un respaldo con `-count_frames` — y una rama sin probar es exactamente lo que costó el
    bloqueante de esta feature: `onda/` fuera de `WORK_DIRS` pasó el gate porque nada lo tocaba.

    Aquí se remuxa el mismo vídeo a `.ts` (sin recodificar, así que son los mismos fotogramas) y
    se exige la misma cuenta que por la vía rápida.
    """
    mp4 = _video_de_prueba(tmp_path / "entrada.mp4")
    ts = tmp_path / "entrada.ts"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-c", "copy", str(ts)],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip

    # La cabecera del `.ts` no trae el campo: si algún día lo trajera, esta prueba dejaría de
    # ejercitar el respaldo y hay que saberlo.
    crudo = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames",
         "-of", "csv=p=0", str(ts)],
        capture_output=True, text=True, timeout=60,
    ).stdout.strip()  # fmt: skip
    assert not crudo.isdigit(), f"el .ts ya declara nb_frames ({crudo!r}): esta prueba ya no toca el respaldo"

    assert onda.sonda(ts)["fotogramas"] == onda.sonda(mp4)["fotogramas"]


def test_la_onda_solo_pinta_dentro_de_su_caja(tmp_path):
    """Criterio 5 de la ficha por el lado del estudio: lo de fuera de la caja no se toca.

    Es lo que hace que la banda de los subtítulos siga siendo de los subtítulos: la onda no
    puede desbordarse por abajo aunque el audio venga saturado. Con la onda simétrica, el borde
    que hay que vigilar es el de abajo de la caja, que está `alto_px/2` por debajo del eje.
    """
    entrada = _video_de_prueba(tmp_path / "entrada.mp4")
    salida = tmp_path / "con-onda.mp4"
    onda.compone(entrada, salida, CAJA, "24/1")
    debajo = _onda(
        barras=CAJA.barras,
        ancho_px=CAJA.ancho_px,
        alto_px=CAJA.alto_px,
        x_px=CAJA.x_px,
        # La franja de justo debajo del borde inferior, que es donde iría el texto. Cabe entera
        # en el vídeo de prueba (360 px de alto) a propósito: un recorte que se saliera lo
        # devolvería FFmpeg dentro de la caja, y la prueba estaría midiendo la propia onda.
        eje_y_px=CAJA.borde_inferior_px + CAJA.alto_px // 2,
        grosor_px=CAJA.grosor_px,
        radio_px=CAJA.radio_px,
        color=CAJA.color,
        opacidad=CAJA.opacidad,
    )
    assert int(_mascara_de_onda(salida, 1.5, debajo).sum()) == 0


def test_sin_onda_declarada_el_video_no_cambia_ni_un_byte(tmp_path, monkeypatch):
    """El contrato de la ficha: un canal sin onda monta exactamente como hoy."""
    video = _video_de_prueba(tmp_path / "final.mp4")
    antes = hashlib.md5(video.read_bytes()).hexdigest()

    monkeypatch.setattr(config, "CANAL_PERFIL", _sin_onda())
    monkeypatch.setattr(config, "CANAL_ERROR", None)
    assert onda.aplica(video, tmp_path) is None

    assert hashlib.md5(video.read_bytes()).hexdigest() == antes
    assert not (tmp_path / "onda").exists()
    assert not (tmp_path / "generacion-onda.json").exists()


def test_con_onda_declarada_la_etapa_deja_el_montaje_original_y_su_registro(tmp_path, monkeypatch):
    video = _video_de_prueba(tmp_path / "final.mp4")
    antes = hashlib.md5(video.read_bytes()).hexdigest()

    pequena = {**ASPECTO, "barras": 16, "ancho_px": 400, "alto_px": 100, "x_px": 120, "eje_y_px": 200}
    monkeypatch.setattr(config, "CANAL_PERFIL", _perfil(pequena))
    monkeypatch.setattr(config, "CANAL_ERROR", None)
    registro = onda.aplica(video, tmp_path)

    assert registro["montaje"]["antes"] == registro["montaje"]["despues"]
    assert registro["fotogramas_dibujados"] == registro["montaje"]["antes"]["fotogramas"]
    assert hashlib.md5(video.read_bytes()).hexdigest() != antes, "el vídeo tenía que llevar la onda encima"
    # El montaje sin onda se conserva: volver atrás no obliga a montar de nuevo.
    assert hashlib.md5((tmp_path / "onda" / "final-sin-onda.mp4").read_bytes()).hexdigest() == antes
    guardado = json.loads((tmp_path / "generacion-onda.json").read_text(encoding="utf-8"))
    assert guardado[0]["aspecto"]["barras"] == 16
    assert guardado[0]["grafo"].startswith("[0:v][1:v]overlay")
    # El mecanismo se publica para poder auditar por qué la onda salió como salió.
    assert guardado[0]["mecanismo"]["ventana_fft"] == onda.VENTANA_FFT
    assert guardado[0]["mecanismo"]["capsulas_con_recorrido"] >= 1


def test_el_registro_publica_el_contraste_medido_de_la_capsula(tmp_path, monkeypatch):
    """El defecto que midió la revisión no se puede volver a perder de vista: se publica cada run."""
    video = _video_de_prueba(tmp_path / "final.mp4")
    pequena = {**ASPECTO, "barras": 16, "ancho_px": 400, "alto_px": 100, "x_px": 120, "eje_y_px": 200}
    monkeypatch.setattr(config, "CANAL_PERFIL", _perfil(pequena))
    monkeypatch.setattr(config, "CANAL_ERROR", None)
    contraste = onda.aplica(video, tmp_path)["contraste"]
    assert contraste["medido"] is True and contraste["muestras"] >= 1
    assert contraste["contraste_mediana"] >= 1.0
    assert "gris_equivalente_0_255" in contraste
    # Se mide y se publica: no aprueba ni suspende, porque el color es del canal.
    assert "reportado_no_es_gate" in contraste


def test_si_componer_falla_el_montaje_vuelve_intacto(tmp_path, monkeypatch):
    """La rama del rollback, que salva el `final.mp4` de un run de nueve minutos.

    **Funcionaba y ninguna prueba la pisaba** (recomendación 4 de la 3.ª revisión): el único caso
    de fallo de la suite se para en `_tiene_audio`, o sea **antes** del `replace` que aparta el
    montaje, así que nunca entraba en el `try`. Aquí se fuerza el fallo justo donde importa —con
    el vídeo ya apartado en `onda/`— y se exige que vuelva byte a byte y sin dejar registro.
    """
    video = _video_de_prueba(tmp_path / "final.mp4")
    antes = hashlib.md5(video.read_bytes()).hexdigest()
    monkeypatch.setattr(config, "CANAL_PERFIL", _perfil(ASPECTO))
    monkeypatch.setattr(config, "CANAL_ERROR", None)

    def reventar(*_args, **_kwargs):
        raise RuntimeError("FFmpeg se cayó a mitad")

    monkeypatch.setattr(onda, "compone", reventar)

    with pytest.raises(RuntimeError, match="a mitad"):
        onda.aplica(video, tmp_path)

    assert hashlib.md5(video.read_bytes()).hexdigest() == antes, "el montaje no volvió como estaba"
    assert not (tmp_path / "generacion-onda.json").exists(), "no se registra una etapa que falló"
    apartado = tmp_path / "onda" / "final-sin-onda.mp4"
    assert not apartado.exists(), f"el montaje se quedó escondido en {apartado}"


def test_un_ctrl_c_a_mitad_tampoco_deja_el_montaje_escondido(tmp_path, monkeypatch):
    """Y el fallo MÁS probable de todos, que no es una excepción normal.

    Codificar un fondo de nueve minutos dura minutos, así que lo que va a interrumpir esta etapa
    es un Ctrl+C — y `KeyboardInterrupt` no hereda de `Exception`. De ahí el `except BaseException`
    del rollback, que sin esta prueba era una decisión escrita y no verificada.
    """
    video = _video_de_prueba(tmp_path / "final.mp4")
    antes = hashlib.md5(video.read_bytes()).hexdigest()
    monkeypatch.setattr(config, "CANAL_PERFIL", _perfil(ASPECTO))
    monkeypatch.setattr(config, "CANAL_ERROR", None)

    def interrumpir(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(onda, "compone", interrumpir)

    with pytest.raises(KeyboardInterrupt):
        onda.aplica(video, tmp_path)

    assert hashlib.md5(video.read_bytes()).hexdigest() == antes
    assert not (tmp_path / "onda" / "final-sin-onda.mp4").exists()


@pytest.mark.parametrize(
    ("etiqueta", "video_lavfi", "audio_lavfi"),
    [
        # La onda toma la cadencia MEDIDA del montaje, no una constante: a 30 fps el vídeo tiene
        # que salir con sus 30 y sus fotogramas, no remuestreado a 24.
        ("30fps", "color=c=gray:s=640x360:r=30:d=2", "sine=frequency=440:duration=2"),
        # Estéreo: `aformat` lo baja a mono, así que se dibuja UNA onda y no dos superpuestas.
        ("estereo", _FONDO, "sine=frequency=440:duration=2,aformat=channel_layouts=stereo"),
        # Audio más largo que el vídeo: el desajuste venía del contenedor y no se empeora.
        ("audio_largo", "color=c=gray:s=640x360:r=24:d=1", "sine=frequency=440:duration=4"),
    ],
)
def test_los_tres_casos_limite_que_funcionaban_sin_prueba(tmp_path, monkeypatch, etiqueta, video_lavfi, audio_lavfi):
    """Los tres los midió a mano la 3.ª revisión y ninguno tenía prueba.

    El invariante es el mismo de siempre y es el que la etapa promete: **componer la onda no toca
    la cadencia, ni la cuenta de fotogramas, ni la duración del montaje**. Lo que cambia entre los
    tres casos es qué podría romperlo — un remuestreo, una segunda onda, o un audio que se pasa.
    """
    video = tmp_path / "final.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", video_lavfi,
         "-f", "lavfi", "-i", audio_lavfi,
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(video)],
        check=True, capture_output=True,
    )  # fmt: skip
    antes = onda.sonda(video)
    monkeypatch.setattr(config, "CANAL_PERFIL", _perfil(ASPECTO))
    monkeypatch.setattr(config, "CANAL_ERROR", None)

    registro = onda.aplica(video, tmp_path)

    assert registro is not None, f"{etiqueta}: la etapa no compuso nada"
    assert onda.sonda(video) == antes, f"{etiqueta}: componer la onda cambió el montaje"


def test_un_video_sin_narracion_no_se_toca_y_lo_dice(tmp_path, monkeypatch):
    """La onda se genera del audio: sin pista de audio no hay nada que dibujar, y hay que decirlo."""
    mudo = tmp_path / "final.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", _FONDO,
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p", str(mudo)],
        check=True, capture_output=True,
    )  # fmt: skip
    antes = hashlib.md5(mudo.read_bytes()).hexdigest()

    monkeypatch.setattr(config, "CANAL_PERFIL", _perfil(ASPECTO))
    monkeypatch.setattr(config, "CANAL_ERROR", None)
    with pytest.raises(onda.OndaError, match="narración"):
        onda.aplica(mudo, tmp_path)
    assert hashlib.md5(mudo.read_bytes()).hexdigest() == antes


# --- El contraste: la palanca es el color, no la opacidad ------------------------------------


def _sobre_gris(tmp_path: Path, gris: int, color: str, opacidad: float) -> dict:
    """Contraste medido de una cápsula de ese color sobre un fondo gris plano."""
    video = tmp_path / f"gris-{gris}-{color.lstrip('#')}-{opacidad}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"color=c=0x{gris:02X}{gris:02X}{gris:02X}:s=320x180:r=24:d=1",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0", "-pix_fmt", "yuv444p", str(video)],
        check=True, capture_output=True,
    )  # fmt: skip
    caja = _onda(
        barras=8, ancho_px=160, alto_px=40, x_px=40, eje_y_px=90, grosor_px=8, radio_px=4,
        color=color, opacidad=opacidad,
    )  # fmt: skip
    return onda.contraste_medido(video, caja, muestras=2)


def test_el_contraste_medido_distingue_un_color_que_desaparece_de_uno_que_no(tmp_path):
    """Sin esto, la cifra publicada podría ser un número cualquiera y nadie lo notaría.

    Sobre un gris medio (128) el naranja de un canal es casi isoluminante —su luminancia es la de un
    gris 125— y los otros dos no. Medido: naranja **1,038**, teja 2,100, blanco 3,949.
    """
    naranja = _sobre_gris(tmp_path, 128, "#D95024", 1.0)["contraste_mediana"]
    blanco = _sobre_gris(tmp_path, 128, "#FFFFFF", 1.0)["contraste_mediana"]
    teja = _sobre_gris(tmp_path, 128, "#8C2F14", 1.0)["contraste_mediana"]
    assert naranja < 1.2, f"el naranja isoluminante debería desaparecer: {naranja}"
    assert teja > 1.9, f"el teja oscuro tiene que separarse del fondo: {teja}"
    assert blanco > 3.5, f"el blanco tiene que separarse mucho: {blanco}"


def test_el_color_que_salva_el_contraste_depende_del_fondo(tmp_path):
    """Un hallazgo del rework que hay que dejar clavado: **el blanco no es la respuesta siempre.**

    Sobre el gris ~134 del grabado de un canal —el fondo con el que se juzgó el prototipo— el
    blanco contrasta de sobra. Sobre el gris 190 del cielo pálido que declara otro, el orden se
    **invierte**: blanco 1,859 y teja 4,463. Así que «se aprobaron las cápsulas blancas» no
    autoriza a escribir blanco en el perfil de un canal de fondo claro, y esta prueba es el
    recordatorio.
    """
    blanco = _sobre_gris(tmp_path, 190, "#FFFFFF", 1.0)["contraste_mediana"]
    teja = _sobre_gris(tmp_path, 190, "#8C2F14", 1.0)["contraste_mediana"]
    assert blanco < 2.0 < teja, f"sobre fondo claro: blanco {blanco}, teja {teja}"


def test_la_opacidad_no_es_la_palanca_del_contraste_sobre_un_fondo_medio(tmp_path):
    """La corrección que la revisión de F4.11 obligó a escribir, convertida en prueba.

    El primer informe dijo «la causa es la opacidad», y eso invita a subirla a 1,0 — que sobre un
    gris medio **no arregla nada**. La palanca es la luminancia del color. Medido sobre gris 128:
    la opacidad mueve el contraste 0,045 puntos (1,038 → 1,083) y cambiar de color 0,742
    (1,083 → 1,825), o sea **16 veces más**.
    """
    opaco = _sobre_gris(tmp_path, 128, "#D95024", 1.0)["contraste_mediana"]
    translucido = _sobre_gris(tmp_path, 128, "#D95024", 0.75)["contraste_mediana"]
    otro_color = _sobre_gris(tmp_path, 128, "#8C2F14", 0.75)["contraste_mediana"]
    assert abs(opaco - translucido) < 0.15, f"la opacidad mueve el contraste {abs(opaco - translucido):.3f}"
    assert otro_color - translucido > 0.5, "cambiar el color sí tiene que mover el contraste"


def test_el_gris_equivalente_traduce_la_luminancia_a_algo_mirable():
    """El diagnóstico legible: «este naranja es un gris 125», que es por qué desaparece."""
    naranja = onda.aspecto_del_canal(_perfil({**ASPECTO, "color": "#D95024"}))
    assert 120 <= onda.gris_equivalente(naranja.luminancia_relativa) <= 130
    blanco = onda.aspecto_del_canal(_perfil({**ASPECTO, "color": "#FFFFFF"}))
    assert onda.gris_equivalente(blanco.luminancia_relativa) == pytest.approx(255, abs=1)


# --- El preflight, que es lo que ve `pipeline.py --check` ------------------------------------


def test_el_preflight_de_un_canal_sin_onda_no_es_un_fallo(monkeypatch):
    monkeypatch.setattr(config, "CANAL_PERFIL", _sin_onda())
    monkeypatch.setattr(config, "CANAL_ERROR", None)
    checks = onda.preflight()
    assert all(c["ok"] for c in checks)
    assert not any(c["obligatorio"] for c in checks)


def test_el_preflight_caza_la_declaracion_a_medias_antes_de_gastar_la_gpu(monkeypatch):
    monkeypatch.setattr(config, "CANAL_PERFIL", _perfil(True))
    monkeypatch.setattr(config, "CANAL_ERROR", None)
    checks = onda.preflight()
    assert checks[0]["ok"] is False and checks[0]["obligatorio"] is True


def test_el_preflight_publica_la_holgura_con_los_subtitulos_y_no_suspende(monkeypatch):
    """Se mide y se publica, como el encuadre de la miniatura en F3.6: no es un gate."""
    monkeypatch.setattr(config, "CANAL_PERFIL", _perfil({**ASPECTO, "eje_y_px": 940}))
    monkeypatch.setattr(config, "CANAL_ERROR", None)
    holguras = [c for c in onda.preflight() if c["nombre"] == "holgura con los subtítulos"]
    assert holguras and holguras[0]["ok"] is False
    assert holguras[0]["obligatorio"] is False


def test_la_holgura_se_mide_desde_el_borde_de_abajo_y_no_desde_el_eje(monkeypatch):
    """El cambio de significado del campo, medido: la onda simétrica baja media caja más.

    Quien lea `holgura_px` tiene que estar viendo la distancia al borde inferior real, porque es
    el que puede pisar el texto.
    """
    monkeypatch.setattr(config, "CANAL_PERFIL", _perfil(ASPECTO))
    monkeypatch.setattr(config, "CANAL_ERROR", None)
    aspecto = onda.aspecto_del_canal()
    holgura = onda.holgura_con_subtitulos(aspecto)
    assert holgura["borde_inferior_de_la_onda_px"] == aspecto.borde_inferior_px
    assert holgura["holgura_px"] == holgura["techo_estimado_del_texto_px"] - aspecto.borde_inferior_px
    assert holgura["eje_de_la_onda_px"] == aspecto.eje_y_px


def test_el_preflight_publica_la_luminancia_del_color_sin_suspender(monkeypatch):
    """El color es del usuario: el estudio lo mide y lo dice, no lo veta."""
    monkeypatch.setattr(config, "CANAL_PERFIL", _perfil({**ASPECTO, "color": "#D95024"}))
    monkeypatch.setattr(config, "CANAL_ERROR", None)
    luminancias = [c for c in onda.preflight() if c["nombre"] == "luminancia del color de la onda"]
    assert luminancias and luminancias[0]["ok"] is True
    assert luminancias[0]["obligatorio"] is False
    assert "gris 125" in luminancias[0]["detalle"]


# --- El acabado de CRISTAL (05-09) -----------------------------------------------------------
#
# Se pidio senalando una referencia: «te dije que la queria como el ejemplo
# experimentos/onda-glass/pil.png donde se puede ver que a traves de ella se transparenta de forma
# borrosa». Lo que estas pruebas protegen no es que sea bonito —eso lo decide el mirando— sino que
# los campos que lo describen no puedan quedarse a medias ni dormidos.


def test_cristal_sin_sus_campos_se_para_y_dice_cuales_faltan():
    aspecto = {**ASPECTO, "acabado": "cristal"}
    with pytest.raises(onda.OndaError) as exc:
        onda.aspecto_del_canal(_perfil(aspecto))
    for campo in onda.CAMPOS_DEL_CRISTAL:
        assert campo in str(exc.value)


@pytest.mark.parametrize("campo", sorted(onda.CAMPOS_DEL_CRISTAL))
def test_al_cristal_le_falta_UN_campo_y_tambien_se_para(campo):
    aspecto = {k: v for k, v in ASPECTO_CRISTAL.items() if k != campo}
    with pytest.raises(onda.OndaError, match=campo):
        onda.aspecto_del_canal(_perfil(aspecto))


@pytest.mark.parametrize("campo", sorted(onda.CAMPOS_DEL_CRISTAL))
def test_un_campo_de_cristal_en_un_acabado_opaco_NO_se_ignora_en_silencio(campo):
    """Un valor escrito que nadie aplica es una decision dormida: se para en vez de dejarla pasar."""
    aspecto = {**ASPECTO, campo: ASPECTO_CRISTAL[campo]}
    with pytest.raises(onda.OndaError, match=campo):
        onda.aspecto_del_canal(_perfil(aspecto))


def test_el_acabado_solo_entiende_los_dos_nombres():
    with pytest.raises(onda.OndaError, match="acabado"):
        onda.aspecto_del_canal(_perfil({**ASPECTO, "acabado": "translucido"}))


def test_el_grafo_del_cristal_refracta_el_fondo_SIN_atenuar():
    """La regla: «no hay que atenuarlas, solo el fondo».

    Se comprueba en la estructura del grafo: la banda que se desenfoca sale de la rama del
    fotograma ORIGINAL, y el velo se aplica en la otra rama, la que se ve alrededor.
    """
    aspecto = onda.aspecto_del_canal(_perfil(ASPECTO_CRISTAL))
    g = onda.grafo(aspecto, "24/1")
    assert "[0:v]split[entero_a][para_banda]" in g
    # el velo entra por la rama `entero_a` y la refraccion por `para_banda`
    assert "[entero_a]scale2ref" in g
    assert "[para_banda]crop" in g
    assert "gblur" in g


def test_el_grafo_del_cristal_lleva_el_filo_del_tono_fuerte():
    aspecto = onda.aspecto_del_canal(_perfil(ASPECTO_CRISTAL))
    g = onda.grafo(aspecto, "24/1")
    r, v, a = aspecto.rgb_del_filo
    assert f"color=c=0x{r:02X}{v:02X}{a:02X}" in g
    assert "erosion" in g, "el filo es la mascara menos su erosion"


def test_el_grafo_opaco_NO_arrastra_nada_del_cristal():
    """El control negativo: estrenar el cristal no puede cambiar lo que ya montaba el primer canal."""
    g = onda.grafo(onda.aspecto_del_canal(_perfil(ASPECTO)), "24/1")
    assert g == "[0:v][1:v]overlay=x=320:y=350:eof_action=pass[vid]"
    for palabra in ("gblur", "maskedmerge", "erosion", "scale2ref"):
        assert palabra not in g


def test_el_comando_del_cristal_pide_el_gradiente_y_manda_la_silueta():
    aspecto = onda.aspecto_del_canal(_perfil(ASPECTO_CRISTAL))
    args = onda.comando("e.mp4", "s.mp4", aspecto, "24/1", "reflejo.png")
    assert "gray" in args, "por la tuberia va la silueta, no la capa RGBA"
    assert "reflejo.png" in args
    # y sin el gradiente se para en vez de montar un cristal sin reflejo
    with pytest.raises(onda.OndaError, match="reflejo"):
        onda.comando("e.mp4", "s.mp4", aspecto, "24/1")


def test_la_silueta_dibuja_las_MISMAS_capsulas_que_la_capa_opaca():
    """El cristal cambia el color, no la forma: si divergieran, la onda saltaria al cambiar acabado."""
    valores = np.linspace(0.2, 1.0, CAPA.barras)
    opaca = np.asarray(onda.capa(valores, CAPA))[:, :, 3] > 0
    silueta = np.asarray(onda.mascara(valores, CAPA)) > 0
    assert (opaca == silueta).all()


def test_la_sonda_mide_la_PROPORCION_y_no_solo_el_tiempo(tmp_path):
    """El fallo del 05-09: un vídeo puede salir deformado sin cambiar ni un fotograma ni un segundo.

    El `scale2ref` del velo dejaba el `sample_aspect_ratio` en 9:16 —1920x1080 de píxeles mostrados
    como un cuadrado— y la guarda no saltó porque comparaba cadencia, fotogramas y duración, que
    estaban intactos. Lo tuvo que ver el usuario en el vídeo.
    """
    normal = tmp_path / "normal.mp4"
    deformado = tmp_path / "deformado.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
         "-i", "color=c=gray:s=320x180:d=1:r=24", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(normal)],
        check=True,
    )  # fmt: skip
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(normal),
         "-vf", "setsar=9/16", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(deformado)],
        check=True,
    )  # fmt: skip

    a, b = onda.sonda(normal), onda.sonda(deformado)
    # lo que la guarda vieja comparaba es IDENTICO en los dos
    for campo in ("cadencia", "fotogramas", "duracion_s", "tamano"):
        assert a[campo] == b[campo], f"{campo} deberia coincidir: {a[campo]} vs {b[campo]}"
    # y aun asi son videos distintos, y ahora se nota
    assert a["sar"] != b["sar"]
    assert b["sar"].replace("/", ":") == "9:16"


def test_el_grafo_del_cristal_fija_el_sar_despues_del_scale2ref():
    """Sin `setsar=1` el velo reescribe la proporcion del video entero."""
    aspecto = onda.aspecto_del_canal(_perfil(ASPECTO_CRISTAL))
    g = onda.grafo(aspecto, "24/1")
    assert "scale2ref" in g
    assert "setsar=1" in g
    assert g.index("scale2ref") < g.index("setsar=1"), "el setsar va DESPUES del scale2ref"


CAJA_CRISTAL = _onda(
    barras=16, ancho_px=400, alto_px=100, x_px=120, eje_y_px=200, grosor_px=12, radio_px=6,
    color="#5C829E", opacidad=1.0, acabado="cristal", color_del_filo="#274962",
    translucidez=0.45, desenfoque_px=6.0, velo_del_fondo=0.35,
)  # fmt: skip


def test_la_orden_FIJA_el_numero_de_fotogramas_de_salida():
    """La composición no puede cambiar el conteo del montaje, y `-frames:v` es el techo que lo impide.

    **De dónde sale** (06-09): al remontar el episodio de un canal, componer la onda pasó de **8.984
    fotogramas y 374,333 s a 8.985 y 374,375**, y la guarda de `aplica` tiró once minutos de render.

    **Va después de la ÚLTIMA `-i`**, y eso es lo que se afirma aquí y no «antes del nombre de
    salida»: colocado antes de una entrada, `-frames:v` limita esa entrada en vez de la salida. El
    riesgo vive en el acabado de cristal, que tiene tres entradas —vídeo, capa por tubería y el
    reflejo con `-loop 1`—, así que se comprueba sobre él.
    """
    for caja, etiqueta in ((CAJA, "opaco"), (CAJA_CRISTAL, "cristal")):
        reflejo = "r.png" if caja.es_cristal else None
        args = onda.comando("e.mp4", "s.mp4", caja, "24/1", reflejo, fotogramas=8984)
        assert "-frames:v" in args, etiqueta
        assert args[args.index("-frames:v") + 1] == "8984", etiqueta
        ultima_entrada = max(k for k, a in enumerate(args) if a == "-i")
        assert args.index("-frames:v") > ultima_entrada, (
            f"[{etiqueta}] antes de una `-i` limitaría esa ENTRADA, no la salida"
        )
    # Sin conteo la orden se queda como estaba: quien no lo sepa, no fuerza nada.
    assert "-frames:v" not in onda.comando("e.mp4", "s.mp4", CAJA, "24/1")


@pytest.mark.parametrize("pasada", range(6))
def test_componer_con_CRISTAL_no_alarga_el_video(tmp_path, pasada):
    """El control funcional, y **se repite porque el defecto es intermitente**.

    Esto es lo que se me escapó al escribir el arreglo: busqué el fallo variando el audio y el
    acabado, y lo que hacía falta era **repetir**. Medido por la auditoría sobre el mismo fichero y
    la misma orden: sin el flag, `cristal` da un fotograma de más **1 de cada 12 pasadas**; `opaco`,
    **0 de 12**; con el flag, **0 de 12**. Un caso único —que es lo que yo probé— acierta once de
    cada doce veces y no demuestra nada.

    Por eso la prueba afirma el lado seguro (con el flag, el conteo es exacto) y se ejecuta seis
    veces: no busca el fallo intermitente, comprueba que el techo lo hace imposible.
    """
    import subprocess

    entrada = tmp_path / "e.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=gray:s=640x360:r=24:d=5",
         "-f", "lavfi", "-i", "aevalsrc='sin(2*PI*300*t)':s=48000:d=5.1",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(entrada)],
        check=True, capture_output=True,
    )  # fmt: skip
    n = onda.sonda(entrada)["fotogramas"]
    valores = np.zeros((n, CAJA_CRISTAL.barras), dtype=np.float32) + 0.5

    onda.compone(entrada, tmp_path / "s.mp4", CAJA_CRISTAL, "24/1", fotogramas=n, valores=valores)
    assert onda.sonda(tmp_path / "s.mp4")["fotogramas"] == n, f"pasada {pasada}: el conteo cambió"
