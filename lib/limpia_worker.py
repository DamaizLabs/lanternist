"""Calla lo que suena FUERA de las palabras — se ejecuta con el intérprete de `.venv-voz` (06-09).

Mismo patrón que `lib/voice_worker.py` y `lib/alineador_worker.py`, y por el mismo motivo:
`torchaudio` vive en `.venv-voz`, no en el `.venv` del pipeline. `lib/limpia_voz.py` lanza este
archivo como subproceso, le pasa un trabajo en JSON y recoge el resultado en otro.

**De dónde sale.** Tras cuatro vueltas de audio: «siguen habiendo ruidos en las pausas entre
frases». Lo que suena ahí es lo que Chatterbox genera cuando ya no le queda texto que decir —una
cola de segmento—, y **por nivel no se puede distinguir del final de una palabra**: los dos son
flojos, los dos duran un par de décimas y los dos mueren contra el silencio. Un filtro por
decibelios se comió la «nt» de «important» y se oyó al momento (addendum, fila 90).

Lo que sí los separa es saber **dónde hay palabras**, y eso ya lo tenemos: las marcas por palabra de
`whisper-small` que el pipeline calcula en cada run para el karaoke. Es el mismo mecanismo que usa
`video-use` con ElevenLabs Scribe, con el reconocedor que ya está aquí — en local, sin clave y sin
que salga nada del PC (decisión 6).

**Hay DOS señales, y la segunda es la que resolvió el caso.**

La primera es por nivel, y es conservadora: se calla lo que queda fuera de toda palabra reconocida,
por debajo del techo y más largo que el mínimo. Las tres a la vez, y es deliberado — un reconocedor
falla, y falló en este mismo episodio (nueve palabras colapsadas en un instante, addendum fila 83).

La segunda es por TEXTO: una marca que el alineador oyó y **el guion no tiene** es una muletilla que
el motor se inventó. Esa se calla sin mirar el nivel ni la duración, y hace falta porque el «Um…» de
la lámina 4 sonaba a **-0,8 dB** —casi a plena voz— durante 1,82 s. Ningún filtro por decibelios lo
habría cazado jamás; de hecho la medición demostró que los tramos flojos que parecían ruido eran los
finales de las últimas palabras de cada frase («know.», «eggs.», «pyjamas.»), y por eso el filtro
anterior se comió la «nt» de «important».

Uso (lo invoca el adaptador, no una persona):

    .venv-voz\\Scripts\\python.exe lib/limpia_worker.py --trabajo <job.json> --resultado <res.json>

Formato del trabajo:

    {
      "ajustes": {"margen_ms": 120, "techo_db": -18, "minimo_ms": 250, ...},
      "items": [{"audio": "<ruta wav>", "marcas": [{"desde": 0.0, "hasta": 0.18}, ...]}]
    }
"""

import argparse
import json
import sys
import time
from pathlib import Path


def voz(marcas: list[dict], margen: float, hasta_el_final: float) -> list[tuple[float, float]]:
    """Los tramos donde HAY palabra, ensanchados con `margen` y fundidos si se tocan.

    El margen no es un detalle: las marcas de whisper son aproximadas y recortan por donde la
    energía baja, así que el borde real de una palabra —la «s» que se apaga, la oclusiva que
    arranca— cae fuera de la marca. Con margen, esos bordes quedan dentro de la zona protegida.
    """
    tramos = []
    for marca in sorted(marcas, key=lambda m: float(m["desde"])):
        ini = max(0.0, float(marca["desde"]) - margen)
        fin = min(hasta_el_final, float(marca["hasta"]) + margen)
        if tramos and ini <= tramos[-1][1]:
            tramos[-1] = (tramos[-1][0], max(tramos[-1][1], fin))
        else:
            tramos.append((ini, fin))
    return tramos


def fuera_de_la_voz(tramos: list[tuple[float, float]], total: float) -> list[tuple[float, float]]:
    """El complemento: lo que queda entre palabra y palabra, y en los dos extremos."""
    huecos, cursor = [], 0.0
    for ini, fin in tramos:
        if ini > cursor:
            huecos.append((cursor, ini))
        cursor = max(cursor, fin)
    if cursor < total:
        huecos.append((cursor, total))
    return huecos


def apaga_colas(salida, plano, sr: int, marcas: list[dict], ajustes: dict) -> list[dict]:
    """Funde la cola que el motor deja DENTRO de la marca de una palabra. Devuelve lo que toco.

    **Es el ruido que sobrevivio a todo lo demas** (06-09). La revisión dio seis minutos —00:32, 00:47,
    01:06, 01:16, 01:26, 01:38— y ahi el audio dice, por ejemplo: «Mum.» hasta el segundo 4,86 y
    despues **1,44 s de murmullo a -27/-50 dB** antes de la frase siguiente. Whisper mete esa cola
    DENTRO de la marca de la palabra (4,52-5,68), asi que ninguna regla que mire el guion la toca:
    para el pipeline, ahi hay una palabra que el guion pide.

    **Y la CABEZA es el mismo defecto al reves**: el motor genera relleno antes de arrancar. Fue el
    ultimo ruido del episodio —«en el minuto 5:04 se escucha el unico ruido de todo el
    video»—, 580 ms a -31/-47 dB entre el silencio y la primera palabra. El filtro solo miraba el
    final, asi que no lo veia.

    **Como se separa de un fonema**, que es lo que hizo fracasar dos filtros anteriores: no por su
    nivel absoluto sino por su caida respecto al **pico de su propia palabra**, y por lo que dura.
    Medido sobre el episodio: la «nt» de «important» cae 20 dB durante **220 ms**
    y la de «quiet.» durante 400; las colas de verdad duran de **520 a 1860 ms**. Con el corte en
    500 ms, los fonemas quedan a salvo con margen y caen 25 colas — 16,8 s de murmullo.

    Se FUNDE en vez de cortarse, por lo aprendido dos veces: un corte en seco contra el silencio
    deja la cola flotando como una isla, y eso se oye mas que la propia cola.
    """
    import torch

    caida = float(ajustes["cola_caida_db"])
    minimo = int(ajustes["cola_minima_ms"])
    v = int(sr * 0.02)
    tocadas = []
    for marca in marcas:
        a, b = int(float(marca["desde"]) * sr), int(float(marca["hasta"]) * sr)
        trozo = plano[a:b]
        if trozo.numel() < v * 3:
            continue
        picos = [float(trozo[i : i + v].abs().max()) for i in range(0, trozo.numel() - v, v)]
        limite = max(picos) * 10 ** (-caida / 20)
        # La COLA: desde el final hacia atras
        n = 0
        while n < len(picos) and picos[len(picos) - 1 - n] <= limite:
            n += 1
        if n * 20 >= minimo:
            desde = b - n * v
            curva = torch.linspace(1.0, 0.0, b - desde, dtype=plano.dtype) ** 2
            salida[desde:b] = plano[desde:b] * curva
            tocadas.append({"desde": round(desde / sr, 3), "hasta": round(b / sr, 3), "ms": n * 20})

        # La CABEZA: lo mismo al reves. Chatterbox genera relleno ANTES de arrancar igual que
        # despues de acabar, y ese fue el ultimo ruido del episodio — «en el minuto 5:04 se
        # escucha el unico ruido de todo el video», y ahi hay 580 ms a -31/-47 dB entre el silencio y
        # la palabra. El filtro solo miraba el final, asi que no lo veia.
        m = 0
        while m < len(picos) and picos[m] <= limite:
            m += 1
        if m * 20 >= int(ajustes["cabeza_minima_ms"]):
            hasta = a + m * v
            curva = torch.linspace(0.0, 1.0, hasta - a, dtype=plano.dtype) ** 2
            salida[a:hasta] = plano[a:hasta] * curva
            tocadas.append({"desde": round(a / sr, 3), "hasta": round(hasta / sr, 3), "ms": m * 20, "cabeza": True})
    return tocadas


def apaga_islas(salida, plano, sr: int, ajustes: dict, marcas: list[dict]) -> list[dict]:
    """Apaga el sonido TENUE que queda atrapado entre dos silencios. Es el remate de la limpieza.

    **De donde sale.** La revisión dio seis minutos concretos —00:32, 00:47, 01:06, 01:16, 01:26, 01:38— y
    al mirar el perfil del audio ahi aparece siempre la misma forma: habla, silencio absoluto,
    300-900 ms de algo a -25/-45 dB, silencio absoluto, habla. Un resto flotando entre dos silencios
    digitales, que destaca justo por el contraste con ellos.

    **Por que es seguro apagarlo**, cuando por nivel solo no lo era: los silencios que lo rodean **no
    estaban en el audio del motor, los puso este pipeline** —al callar una pausa o un hueco sin
    narracion—, y solo se ponen donde el guion no pide nada o donde hay una pausa de verdad. El habla
    es continua: una palabra no acaba aislada entre dos silencios absolutos. Lo que queda ahi es
    residuo de lo que ya se decidio callar.

    Se pasa la ULTIMA, cuando los silencios ya estan puestos.
    """

    techo_db = float(ajustes["isla_techo_db"])
    minimo = int(ajustes["isla_minima_ms"])
    pico = float(salida.abs().max())
    if pico <= 0:
        return []
    techo = pico * 10 ** (techo_db / 20)
    v = int(sr * 0.01)
    picos = [float(salida[i : i + v].abs().max()) for i in range(0, salida.numel() - v, v)]
    mudo = [x == 0.0 for x in picos]

    apagadas, i = [], 0
    while i < len(picos):
        if mudo[i]:
            i += 1
            continue
        j = i
        while j < len(picos) and not mudo[j]:
            j += 1
        # **Basta con que venga DESPUES de un silencio.** Exigir silencio a los dos lados dejaba
        # fuera el caso que se señalo como el ultimo ruido del video —«en el minuto 5:04»—: 590 ms
        # a -31 dB que arrancan tras un silencio y dan paso directamente al habla. Es la cabeza de un
        # segmento cuando el alineador no le pone marca, asi que ninguna otra regla la ve.
        # **El principio del archivo cuenta como silencio.** Un wav que arranca viene de la nada, y
        # al concatenarse detras hay el silencio de la lamina anterior: los seis tramos que se
        # seguia oyendo estaban justo ahi, en la primera ventana de su lamina, y la condicion `i > 0`
        # los dejaba pasar todos.
        tras_silencio = i == 0 or mudo[i - 1]
        # **Y no puede haber una palabra ENTERA dentro**, que es el cinturón que faltaba. El
        # argumento de esta regla —«el habla es continua, una palabra no queda aislada entre dos
        # silencios»— tiene un hueco: los silencios los pone este pipeline en los bordes de los
        # trozos de habla, así que una frase corta entre dos pausas calladas también encaja en la
        # definición de isla, y solo `isla_techo_db` la separa. Con esto, lo único que se apaga son
        # solapes PARCIALES —la cola que asoma al final de la marca de una palabra—, que es lo que
        # esta regla vino a quitar. Medido sobre el episodio: las 7 islas apagadas pisan la marca de
        # una palabra («Mum.», «garden.», «table.») y **ninguna contiene una entera**, así que el
        # cinturón no apaga el filtro; exigir que no pisen ninguna marca sí lo habría apagado.
        entera_dentro = any(float(m["desde"]) >= i * v / sr and float(m["hasta"]) <= j * v / sr for m in marcas)
        if tras_silencio and not entera_dentro and (j - i) * 10 >= minimo and max(picos[i:j]) <= techo:
            # **Entera a cero, sin rampa, y aqui SI es seguro**: la isla esta rodeada de silencio
            # absoluto por los dos lados, asi que pasar de 0 a 0 no puede meter ningun chasquido —
            # que es lo unico que obligaba a fundir en todos los demas casos. Con rampa quedaba el
            # primer instante intacto y la isla seguia oyendose: la ultima medio quedo en -48,6 dB.
            a, b = i * v, j * v
            # **Sin rampa de salida, y no por descuido.** Aqui habia una que subia los ultimos 40 ms
            # «si lo que viene detras es habla», y era codigo muerto: el bucle de arriba sale
            # justamente cuando `mudo[j]`, asi que esa condicion no podia cumplirse nunca. La isla
            # termina siempre contra silencio o contra el final del fichero, que es lo que hace
            # seguro apagarla entera.
            salida[a:b] = 0.0
            apagadas.append({"desde": round(a / sr, 3), "hasta": round(b / sr, 3), "isla": True})
        i = j
    return apagadas


def limpia(plano, sr: int, marcas: list[dict], ajustes: dict, sobrantes: list[dict] | None = None):
    """Devuelve (audio limpio, tramos callados). No cambia la duración: solo silencia.

    `marcas` son las palabras del guion que el alineador reconoció — la zona protegida. `sobrantes`
    son las que oyó y el guion NO tiene: ahí la evidencia no es el nivel sino el texto, así que se
    callan **aunque suenen fuerte**. Y hace falta: el «Um…» de la lámina 4 sonaba a **-0,8 dB**,
    casi a plena voz, y ningún filtro por decibelios lo habría cazado jamás.

    **El margen se funde en vez de respetarse tal cual**, y esa fue la última pieza. Un margen
    intacto deja la cola de la última palabra sonando entre dos silencios: 18 islas de 150-800 ms a
    -22/-49 dB que se oían como ruido, y **todas dentro de una palabra del guion**. Lo que suena
    mal no es la cola sino el corte en seco contra el silencio digital, así que se funde hacia cero
    con una curva cuadrática — sin quitar un fonema, porque empieza donde el alineador dice que la
    palabra ya terminó.
    """
    import torch

    pico = float(plano.abs().max())
    if pico <= 0 or not marcas:
        return plano, []

    margen = float(ajustes["margen_ms"]) / 1000
    techo = pico * (10 ** (float(ajustes["techo_db"]) / 20))
    minimo = float(ajustes["minimo_ms"]) / 1000
    total = plano.numel() / sr

    salida = plano.clone()
    # Primero las colas DENTRO de las palabras, y despues los huecos entre ellas: si se hiciera al
    # reves, el fundido de la cola volveria a poner sonido donde el hueco ya habia callado.
    colas = apaga_colas(salida, plano, sr, marcas, ajustes)

    callados = []
    for ini, fin in fuera_de_la_voz(voz(marcas, margen, total), total):
        # Una marca que el guion NO tiene es una muletilla del motor: se calla sin mirar ni su
        # duración ni su nivel, porque ahí la evidencia es el texto y no los decibelios.
        solapan = [s for s in (sobrantes or []) if float(s["hasta"]) > ini and float(s["desde"]) < fin]
        es_sobrante = bool(solapan)
        if es_sobrante and all(s.get("tipo") == "muletilla" for s in solapan):
            # **Y se calla SOLO lo que la muletilla ocupa.** Lo que se apaga aquí es el hueco entero
            # entre las dos palabras protegidas vecinas, con el chequeo de nivel desactivado — que es
            # justo la válvula que protege «aquí el reconocedor se perdió». Para un hueco sin guion o
            # para la cola del final eso es inofensivo: el guion demuestra que en TODO el tramo no
            # falta narración. Para una muletilla no llega tan lejos, y el ensanchamiento se midió:
            # una marca sobrante de 0,40 s entre dos palabras separadas 2 s silenciaba **1,76 s**.
            ini = max(ini, min(float(s["desde"]) for s in solapan) - margen)
            fin = min(fin, max(float(s["hasta"]) for s in solapan) + margen)
        if fin - ini < minimo and not es_sobrante:
            continue
        a, b = int(ini * sr), int(fin * sr)
        trozo = plano[a:b]
        if trozo.numel() == 0:
            continue
        alto = float(trozo.abs().max())
        if alto > techo and not es_sobrante:
            # Suena fuerte y está fuera de toda palabra: lo más probable es que el reconocedor se
            # haya perdido ahí, así que NO se toca. Se anota para poder mirarlo.
            callados.append({"desde": round(ini, 3), "hasta": round(fin, 3), "callado": False})
            continue
        # **El margen se FUNDE, no se deja intacto.** Un margen que se respeta tal cual deja la cola
        # de la ultima palabra sonando entre dos silencios, y eso es justo lo que se oia como
        # ruido: 18 islas de 150-800 ms a -22/-49 dB, y **todas caian dentro de una palabra del
        # guion** — «room.», «birthday.», «know.», finales de frase que quedaban flotando. Lo que
        # suena mal no es la cola: es la cola CORTADA en seco contra el silencio digital. Fundirla
        # hacia cero la hace desaparecer sin quitar ni un fonema, porque la rampa empieza donde el
        # alineador dice que la palabra ya termino.
        fundido = min(int(margen * sr), a)
        if fundido > 0:
            curva = torch.linspace(1.0, 0.0, fundido, dtype=plano.dtype) ** 2
            salida[a - fundido : a] = plano[a - fundido : a] * curva
        salida[a:b] = 0.0
        subida = min(int(margen * sr), plano.numel() - b)
        if subida > 0:
            curva = torch.linspace(0.0, 1.0, subida, dtype=plano.dtype) ** 2
            salida[b : b + subida] = plano[b : b + subida] * curva
        callados.append({"desde": round(ini, 3), "hasta": round(fin, 3), "callado": True, "por_texto": es_sobrante})
    # La ultima pasada: lo que haya quedado flotando entre los silencios que acaban de ponerse.
    islas = apaga_islas(salida, plano, sr, ajustes, marcas)
    return salida, callados + [dict(c, callado=True, cola=True) for c in colas] + [dict(x, callado=True) for x in islas]


def _de_que_regla(tramo: dict) -> str:
    """De cuál de las cuatro reglas viene un tramo callado. Lo publica el informe."""
    if tramo.get("cabeza"):
        return "cabeza de segmento"
    if tramo.get("cola"):
        return "cola dentro de la palabra"
    if tramo.get("isla"):
        return "isla entre dos silencios"
    # Por TEXTO son las dos señales que no miran el nivel: la muletilla que el guion no dice en
    # ninguna parte y lo que suena tras la última palabra. Verlas separadas es lo que permite saber
    # si esa señal está viva, y el 06-09 llevaba apagada sin que ningún informe lo dijera.
    return "fuera de toda palabra (por texto)" if tramo.get("por_texto") else "fuera de toda palabra (por nivel)"


def main() -> int:
    import torchaudio

    parser = argparse.ArgumentParser()
    parser.add_argument("--trabajo", required=True)
    parser.add_argument("--resultado", required=True)
    args = parser.parse_args()

    job = json.loads(Path(args.trabajo).read_text(encoding="utf-8"))
    ajustes = job["ajustes"]
    salida = {"items": []}
    empezado = time.perf_counter()

    for item in job["items"]:
        ruta = Path(item["audio"])
        wav, sr = torchaudio.load(str(ruta))
        plano = wav[0] if wav.dim() > 1 else wav
        limpio, callados = limpia(plano, sr, item["marcas"], ajustes, item.get("sobrantes"))
        torchaudio.save(str(ruta), limpio.unsqueeze(0), sr)
        segundos = sum(c["hasta"] - c["desde"] for c in callados if c["callado"])
        salida["items"].append(
            {
                "audio": str(ruta),
                "tramos_callados": sum(1 for c in callados if c["callado"]),
                "segundos_callados": round(segundos, 2),
                # **Qué se calló, no solo cuánto.** El informe publicaba dos conteos, y con eso no se
                # puede comprobar nada: la auditoría del 06-09 tuvo que reproducir el filtro entero
                # para descubrir que la señal por texto no callaba nada. Cada tramo dice de qué
                # regla viene, que es lo que convierte una cifra en algo verificable con un comando.
                "callados": [dict(c, regla=_de_que_regla(c)) for c in callados if c["callado"]],
                "sonaban_fuerte_y_se_respetan": [c for c in callados if not c["callado"]],
            }
        )
        print(
            f"      {ruta.name}: {salida['items'][-1]['tramos_callados']} tramos, {segundos:.2f}s callados",
            flush=True,
        )

    salida["seconds"] = round(time.perf_counter() - empezado, 1)
    Path(args.resultado).write_text(json.dumps(salida, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
