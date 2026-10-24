"""Generador de voz — el ÚNICO archivo que se ejecuta con el intérprete de `.venv-voz`.

Existe para resolver un cruce de entornos que no tiene atajo: el pipeline vive en `.venv`
(torch 2.13) y los motores de voz pinean torch 2.6.0+cu126 con `setuptools<81`. En vez de
degradar el venv del pipeline, `lib/voice_client.py` lanza este archivo como **subproceso**
con `.venv-voz\\Scripts\\python.exe`, le pasa un trabajo en JSON y recoge el resultado en otro.

**Tres motores, misma interfaz** (F2.16, 25-08; Orpheus entra el 07-09). La receta declara
`motor` y aquí se instancia la clase correspondiente; el resto del archivo no sabe cuál usa:

- `kokoro` — voz nativa, sin referencia. **Sigue siendo el ORIGEN de la voz de todo canal**: es
  donde se elige el timbre, y de ahí sale el clip que los motores de clonado imitan (decisión 13).
- `orpheus` — el motor de clonado del estudio desde el 07-09. Un LLM de 3B que entona solo y
  obedece etiquetas emocionales. **Divaga**, y por eso existe `RecortadorPorTexto`.
**Chatterbox fue el motor de clonado hasta el 07-09 y ya NO ESTÁ**, ni aquí ni en el venv. Se
descartó tras comparar los dos («los resultados son mucho mejores con Orpheus… podemos eliminar
completamente chatterbox porque no lo vamos a usar más») y se borró con su consecuencia encima de
la mesa —el vídeo aprobado de un canal se produjo con él—: «en ese canal la voz la fabricamos con
chatterbox, pero la volveremos a fabricar con Orpheus… si tenemos algún problema ya lo
rescataremos de algún commit». **Lo que SÍ se conserva en este archivo es lo que Chatterbox
enseñó**: media docena de guardas nacieron midiendo sus defectos, y su historia es la razón de que
existan. Un comentario que lo nombre está contando de dónde salió un umbral, no ofreciendo un motor.

**Un motor que divaga no lo caza ninguna guarda de energía ni de ritmo.** Kokoro, al quedarse sin
texto, murmura flojo — eso lo calla `quita_colas_sin_habla`. Orpheus habla alto y articula frases
inventadas, y 48 palabras en 42,4 s son 68 wpm, dentro de la banda plausible. La única forma de
saber dónde acaba el texto es **leer lo que dice el audio**, y eso hace `RecortadorPorTexto`.

Contrato (deliberadamente tonto: aquí no se decide nada):

- **No importa nada del repositorio** —ni `lib.config`, que necesita `python-dotenv`, ausente
  en `.venv-voz`— ni lee el `.env` ni la receta. Todos los valores llegan en el trabajo.
- **Genera EN SERIE**: un segmento a la vez (invariante de los 8 GB de la 3060 Ti). El motor
  se carga UNA vez para todo el lote.
- **Sin red y sin reintentos**: si un segmento falla, el proceso muere con código distinto de 0
  y el adaptador lo propaga. Un fallo del runtime local es un dato, no algo que se disimule
  repitiendo la llamada.
- **NINGÚN motor marca ya el audio como sintético.** Chatterbox traía `perth` y se fue con él;
  ni Kokoro ni Orpheus marcan nada. Quien cumple la decisión cerrada 7 es la declaración de
  contenido de IA de la subida (flag Art. 50), que por eso **se queda sin red de seguridad técnica
  y no es opcional en ninguna subida**.

Uso (lo invoca el adaptador, no una persona):

    .venv-voz\\Scripts\\python.exe lib/voice_worker.py --trabajo <job.json> --resultado <res.json>

Formato del trabajo, motor `kokoro`:

    {
      "motor": "kokoro",
      "modelo": {"repo_id": "hexgrad/Kokoro-82M", "lang_code": "b", "device": "cuda"},
      "voz": {"id": "mix_onyx_lewis", "tipo": "mezcla", "componentes": ["am_onyx", "bm_lewis"]},
      "parametros": {"speed": 0.66},
      "seed": 1234,
      "silencio_entre_frases_ms": 250,
      "items": [{"salida": "<ruta wav>", "segmentos": ["frase 1", "frase 2"]}]
    }

Formato del trabajo, motor `orpheus`: igual, con

    "modelo": {"repo_id": "audo/orpheus-3b-0.1-ft", "decodificador": "hubertsiuzdak/snac_24khz"},
    "parametros": {"temperature": 0.6, "top_p": 0.95, "repetition_penalty": 1.1,
                   "wpm_esperado": 124.0, "holgura_de_generacion": 1.6},
    "referencia": "<ruta del clip>", "referencia_texto": "<lo que dice el clip>",
    "segundos_de_referencia": 16,
    "recorte_por_texto": {"modelo": "openai/whisper-small", "margen_s": 0.15}

**`referencia_texto` no es opcional cuando hay referencia**: Orpheus clona con un EJEMPLO de habla
(texto + audio), no con un fichero suelto. Y `recorte_por_texto` puede ir a `null` —Kokoro lo pone
así— pero la clave tiene que estar: ausente es un olvido, `null` es una decisión (F4.9).
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time

# `urllib` de la biblioteca estándar y no `requests`: este worker corre en `.venv-voz`, que se
# reconstruye desde `spikes/requirements-voz.txt`, y meterle una dependencia nueva solo para hacer
# un POST a 127.0.0.1 sería pagar 12 GB de venv por cuatro líneas.
import urllib.request
import wave
from pathlib import Path


def _sin_red() -> None:
    """Prohíbe la descarga silenciosa de pesos.

    La caché de HuggingFace ya está poblada (vive en C:\\, documentada en CLAUDE.md) y
    `from_pretrained` saldría a huggingface.co si faltara algo. No es un servicio de pago,
    pero la decisión cerrada 6 dice que nada sale de este PC salvo la subida, y una descarga
    a mitad de un run es además un fallo intermitente. Con esto, si falta un peso el error es
    explícito en vez de una descarga inesperada.
    """
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def _exige_cuda(device: str) -> None:
    import torch

    if device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("[FAIL] torch.cuda.is_available() == False en .venv-voz (trampa conocida de Windows)")


class MotorKokoro:
    """Voz nativa de Kokoro-82M (Apache-2.0), con soporte de mezcla de voces.

    La mezcla se delega a `KPipeline.load_voice`, que acepta varios identificadores separados
    por coma y devuelve `torch.mean(torch.stack(packs), dim=0)`. Se comprobó leyendo su código
    que es **el mismo promedio** que produjo la muestra del spike F2.15 que se escuchó y
    aprobó, así que delegar no cambia la voz: evita reimplementar aquí una media que la
    librería ya hace.
    """

    nombre = "kokoro"
    # Fijo del modelo, no configurable: Kokoro-82M sintetiza a 24 kHz.
    sr = 24000

    def __init__(self, job: dict):
        from kokoro import KPipeline

        spec = job["modelo"]
        device = spec.get("device", "cuda")
        _exige_cuda(device)
        _sin_red()

        started = time.perf_counter()
        self._pipe = KPipeline(lang_code=spec["lang_code"], repo_id=spec["repo_id"], device=device)
        voz = job["voz"]
        componentes = voz.get("componentes") or [voz["id"]]
        # Un solo string: `load_voice` promedia los componentes separados por coma
        self._voz = ",".join(componentes)
        self._pipe.load_voice(self._voz)  # falla YA si un componente no está en la caché
        self._speed = float(job["parametros"]["speed"])
        self.load_seconds = round(time.perf_counter() - started, 1)
        self.descripcion = f"{voz['id']} ({'+'.join(componentes)}) speed {self._speed}"

    def generate(self, texto: str):
        """Devuelve el segmento como tensor (1, N), la misma forma que los demás motores."""
        import torch

        trozos = [audio for _, _, audio in self._pipe(texto, voice=self._voz, speed=self._speed)]
        if not trozos:
            raise SystemExit(f"[FAIL] Kokoro no produjo audio para el segmento: {texto[:60]!r}")
        plano = torch.cat([t if t.dim() == 1 else t.squeeze(0) for t in trozos])
        return plano.unsqueeze(0).cpu()


class MotorOrpheus:
    """Voz clonada con Orpheus TTS 3B: un modelo de lenguaje que habla.

    **Su licencia es la Llama 3.2 Community License, no Apache-2.0** (OC1.2). Su ficha en Hugging Face dice
    `apache-2.0`, pero el modelo es un derivado de Llama 3.2 (`base_model: meta-llama/Llama-3.2-3B-Instruct`, en
    `canopylabs/orpheus-3b-0.1-ft` y en el GGUF de `unsloth`, leído el 14-10-2026), y esa licencia manda sobre sus
    derivados: pide mostrar «Built with Llama» y cumplir su política de uso aceptable. Lo declara
    `THIRD_PARTY_NOTICES.md`. Lo que llega a `assets.json` es el `modelo.licencia` de la receta de voz del canal, así
    que una receta de Orpheus tiene que nombrar esta licencia.

    **Qué lo hace distinto de Kokoro.** Kokoro es un sintetizador: recibe texto y devuelve la onda.
    Orpheus es un LLM de 3.000 millones de parámetros que predice **tokens de audio**, y un
    decodificador aparte —SNAC, 24 kHz— los convierte en sonido. De ahí salen sus dos
    virtudes y sus dos defectos, y conviene tenerlos los cuatro presentes.

    - Entona solo, porque entiende la frase. Es lo que se buscaba y ni Kokoro ni el fork emocional
      daban.
    - Obedece **etiquetas** como `<gasp>` o `<groan>` incrustadas en el texto: las convierte en
      sonido en vez de leerlas. Medido el 07-09 con la voz ya clonada.
    - **Divaga.** Termina el texto y sigue hablando: inventa frases y continúa la referencia que se
      le dio de ejemplo. Medido: 42,4 s de audio para 18,8 s de texto. Lo arregla `recorta_por_texto`.
    - **Cuesta.** 3,85× tiempo real en la 3060 Ti, y sobre el audio útil sube a ~9,7×. Se
      aceptó por escrito: «no me importa lo que tarde, lo que quiero es calidad».

    **Cómo se le da la voz del canal, que no es un fichero suelto.** El clonado no recibe un WAV:
    recibe **un ejemplo completo de habla**. Se antepone al prompt el par (texto de la referencia,
    audio de la referencia convertido en tokens) y detrás el texto nuevo; el modelo continúa
    imitando lo que acaba de «oír». Por eso la receta declara el clip **y su texto exacto**: sin el
    texto, el ejemplo está cojo y el modelo no sabe qué parte del sonido corresponde a qué palabra.

    **El entrelazado de los siete códigos por frame es la operación inversa** de la que decodifica:
    los mismos desplazamientos, en el mismo orden, sumando en vez de restando. Equivocarse ahí no da
    error, da ruido — el modelo recibiría ruido como ejemplo de voz y clonaría ruido.

    **Advertencia del propio fabricante**, que hay que conocer antes de culpar al prompt: la lista de
    tareas de Canopy Labs incluye «Fix voice cloning Colab notebook implementation», y del modelo
    preentrenado dicen que «no ha sido entrenado explícitamente» para clonar. El clonado que se midió
    aquí es **parcial**: 107-131 Hz de tono mediano contra 91,3 de la referencia de Kokoro y 134 de
    la voz de stock. Coge parte del timbre, no todo.
    """

    nombre = "orpheus"
    # Fijo del modelo, no configurable: el decodificador SNAC de Orpheus sintetiza a 24 kHz.
    sr = 24000

    # Protocolo de tokens de Orpheus. Van aquí y no en la receta porque **no son una decisión de
    # canal**: son el formato del modelo, como los 24 kHz. Los emite su propio tokenizador.
    INICIO_HUMANO, FIN_TEXTO, FIN_HUMANO = 128259, 128009, 128260
    INICIO_AUDIO, FIN_AUDIO, OFFSET_AUDIO = 128257, 128258, 128266
    CODIGOS_POR_FRAME = 7
    # Medido el 07-09: 1.316 tokens de audio para 16,0 s de referencia. Sirve para calcular cuántos
    # tokens como mucho puede necesitar un segmento, que es lo que frena la divagación por coste.
    TOKENS_POR_SEGUNDO = 82.25

    def __init__(self, job: dict):
        from snac import SNAC
        from transformers import AutoTokenizer

        spec = job["modelo"]
        _sin_red()

        started = time.perf_counter()
        # **El tokenizador sigue siendo el de Hugging Face aunque el motor sea llama.cpp**, y no es
        # un resto: al servidor se le pasan IDs de tokens YA tokenizados, porque el clonado antepone
        # un ejemplo (texto de la referencia + su audio tokenizado) que **no tiene representación
        # textual**. Medido: el servidor consume exactamente los IDs que se le dan sin re-tokenizar
        # ni añadir BOS pese a que el GGUF declara `add_bos_token = True`.
        self._tok = AutoTokenizer.from_pretrained(spec["repo_id"])
        # **El decodificador se queda en CPU a propósito.** Con llama.cpp el 3B ya no vive en este
        # proceso, así que el motivo original —el 3B ocupaba 6,6 GB de los 8 de la 3060 Ti— ya no
        # aplica; pero SNAC son 80 MB y decodifica un segmento en décimas, y en la tarjeta ahora
        # manda el servidor. Dejarlo en CPU mantiene el reparto simple y libre de sorpresas.
        self._dec = SNAC.from_pretrained(spec["decodificador"]).eval()
        # De dónde se pide la generación. La URL la arma el ADAPTADOR y la manda en el job: este
        # worker corre en `.venv-voz` como subproceso y **no puede importar nada del repo** (no
        # tiene `python-dotenv`), así que no puede leer `lib/config.py` ni el `.env`.
        self._url = f"{spec['servidor'].rstrip('/')}/completion"
        self.load_seconds = round(time.perf_counter() - started, 1)

        params = {k: v for k, v in (job.get("parametros") or {}).items() if not k.startswith("_")}
        self._temperature = float(params["temperature"])
        self._top_p = float(params["top_p"])
        self._repetition_penalty = float(params["repetition_penalty"])
        # Techo de generación por segmento, derivado del ritmo que la receta espera. Existe para que
        # la divagación cueste poco: sin él, el modelo genera hasta su tope y se tira la mitad.
        self._wpm_esperado = float(params["wpm_esperado"])
        self._holgura = float(params["holgura_de_generacion"])
        self._seed = job["seed"]

        # Modo de voz: o se clona una referencia, o se usa una voz de catálogo. Nunca se adivina.
        self._referencia = job.get("referencia")
        self._voz_de_catalogo = (job.get("voz") or {}).get("id")
        if self._referencia:
            self._ejemplo = self._tokeniza_referencia(job)
            self.descripcion = f"clon de {Path(self._referencia).name} ({len(self._ejemplo)} tokens)"
        elif self._voz_de_catalogo:
            self._ejemplo = []
            self.descripcion = f"voz de catálogo {self._voz_de_catalogo}"
        else:
            raise SystemExit(
                "[FAIL] la receta de Orpheus no declara ni 'referencia' (clonado) ni 'voz.id' "
                "(catálogo). El adaptador no elige por su cuenta cuál es la voz del canal."
            )

    def _tokeniza_referencia(self, job: dict) -> list[int]:
        """Convierte el clip de referencia en el ejemplo de habla que se antepone al prompt."""
        import numpy as np
        import torch

        ruta = Path(self._referencia)
        if not ruta.exists():
            raise SystemExit(f"[FAIL] el clip de referencia no existe: {ruta}")
        texto = job.get("referencia_texto")
        if not texto:
            raise SystemExit(
                "[FAIL] la receta declara 'referencia' pero no 'referencia_texto'. Orpheus clona con "
                "un EJEMPLO (texto + audio), no con un fichero suelto: sin el texto no puede alinear "
                "qué sonido corresponde a qué palabra."
            )
        with wave.open(str(ruta)) as w:
            sr, n, canales = w.getframerate(), w.getnframes(), w.getnchannels()
            audio = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
        if canales > 1:
            audio = audio.reshape(-1, canales).mean(axis=1)
        if sr != self.sr:
            raise SystemExit(
                f"[FAIL] la referencia está a {sr} Hz y el decodificador de Orpheus trabaja a "
                f"{self.sr} Hz. Regenera el clip con esa tasa en vez de remuestrear aquí."
            )

        # **Recorte de la referencia: cada segundo son ~82 tokens de contexto ANTES de generar.**
        # La referencia entera del primer canal son 31,9 s, o sea ~2.700 tokens que se pagan en cada segmento.
        segundos = job.get("segundos_de_referencia")
        if segundos:
            tope = int(sr * float(segundos))
            if len(audio) > tope:
                # El texto se recorta en la MISMA proporción: un ejemplo cuyo texto sobra al audio
                # le enseña al modelo palabras que no llegó a oír.
                palabras = texto.split()
                texto = " ".join(palabras[: max(1, int(len(palabras) * tope / len(audio)))])
                audio = audio[:tope]

        onda = torch.from_numpy(audio).unsqueeze(0).unsqueeze(0)
        with torch.no_grad():
            codigos = self._dec.encode(onda)
        c1, c2, c3 = (c.squeeze(0).tolist() for c in codigos)
        tokens: list[int] = []
        for i in range(len(c1)):
            # El MISMO orden y los MISMOS desplazamientos que usa el decodificador, sumando
            tokens += [
                c1[i] + self.OFFSET_AUDIO,
                c2[2 * i] + self.OFFSET_AUDIO + 4096,
                c3[4 * i] + self.OFFSET_AUDIO + 2 * 4096,
                c3[4 * i + 1] + self.OFFSET_AUDIO + 3 * 4096,
                c2[2 * i + 1] + self.OFFSET_AUDIO + 4 * 4096,
                c3[4 * i + 2] + self.OFFSET_AUDIO + 5 * 4096,
                c3[4 * i + 3] + self.OFFSET_AUDIO + 6 * 4096,
            ]
        return self._bloque_texto(texto) + [self.INICIO_AUDIO] + tokens + [self.FIN_AUDIO]

    def _bloque_texto(self, texto: str) -> list[int]:
        ids = self._tok(texto, return_tensors="pt").input_ids[0].tolist()
        return [self.INICIO_HUMANO] + ids + [self.FIN_TEXTO, self.FIN_HUMANO]

    def _capas(self, codigos: list[int]):
        """Deshace el entrelazado y descarta los frames que caen fuera del diccionario de SNAC.

        Cada uno de los siete códigos de un frame vive en su propio bloque de 4.096. Un token que se
        salga del suyo no es audio, y pasárselo a SNAC revienta con «index out of range». **El filtro
        mira el valor YA restado**, no el token en bruto: una versión anterior exigía además que cada
        token estuviera en su bloque de origen y descartaba TODOS los frames, dejando la prueba sin
        audio y aparentando un fallo del modelo.
        """
        import torch

        c1, c2, c3, descartados = [], [], [], 0
        for i in range(len(codigos) // self.CODIGOS_POR_FRAME):
            m = codigos[i * self.CODIGOS_POR_FRAME : (i + 1) * self.CODIGOS_POR_FRAME]
            v = [
                m[0],
                m[1] - 4096,
                m[2] - 2 * 4096,
                m[3] - 3 * 4096,
                m[4] - 4 * 4096,
                m[5] - 5 * 4096,
                m[6] - 6 * 4096,
            ]
            if any(not (0 <= x < 4096) for x in v):
                descartados += 1
                continue
            c1.append(v[0])
            c2.extend([v[1], v[4]])
            c3.extend([v[2], v[3], v[5], v[6]])
        if descartados:
            print(f"      ({descartados} frame(s) fuera del diccionario de SNAC, descartados)", flush=True)
        if not c1:
            return None
        return [torch.tensor(c, dtype=torch.long).unsqueeze(0) for c in (c1, c2, c3)]

    def _pide(self, entrada: list[int], techo: int) -> list[int]:
        """Pide la generación al servidor y devuelve los IDs generados, solo los generados.

        **Tres cosas de este cuerpo están medidas y son las que sostienen el diseño.**

        `prompt` va como **lista de enteros**: el ejemplo del clonado son 2.704 IDs sin texto
        equivalente, y el servidor los consume tal cual —se comprobó que el prompt evaluado son
        2.704 + los 16 del bloque de texto, o sea que no re-tokeniza ni añade BOS—.

        `cache_prompt` hace el ejemplo casi gratis, y esto es lo que vuelve viable el episodio: la
        primera petición evalúa 2.728 tokens en 865 ms y la siguiente **1 token en 15 ms**,
        reutilizando el resto. **Consecuencia dura: no se paraleliza.** El servidor elige ranura por
        parecido de prefijo, así que con peticiones intercaladas el prefijo se recomputa y se pierde
        justo lo que lo hacía barato. El worker ya genera en serie por el invariante de los 8 GB.

        **No se manda ningún token de parada, y es a propósito.** El servidor para en el que declara
        el fichero (`tokenizer.ggml.eos_token_id = 128009`) y se detiene solo muy por debajo del
        techo: 645-937 tokens de un techo de 1.146 en 30 pasadas, **cero en el techo**. La versión de
        `transformers` pedía parar en `128258`, que el modelo puede no emitir nunca, y por eso llegaba
        al techo en 4 de 4 pasadas gastando un 65 % más de tokens (addendum fila 117).
        """
        cuerpo = json.dumps(
            {
                "prompt": entrada,
                "n_predict": techo,
                "temperature": self._temperature,
                "top_p": self._top_p,
                "repeat_penalty": self._repetition_penalty,
                # La semilla va en la petición: el muestreo lo hace el servidor, así que
                # `torch.manual_seed` ya no pinta nada. Sin ella dos ejecuciones del mismo guion no
                # se parecerían ni serían reintentables, que es lo que exige la guarda de ritmo.
                "seed": self._seed,
                "return_tokens": True,
                "cache_prompt": True,
                "stop": [],
            }
        ).encode("utf-8")
        peticion = urllib.request.Request(self._url, data=cuerpo, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(peticion, timeout=1800) as respuesta:
                datos = json.load(respuesta)
        except OSError as e:
            raise SystemExit(
                f"[FAIL] el motor de voz no responde en {self._url}: {e}. Lo arranca el adaptador "
                "antes de lanzar este worker; si lo estás corriendo a mano, arranca llama-server."
            ) from None
        return datos.get("tokens") or []

    def generate(self, texto: str):
        """Devuelve el segmento como tensor (1, N), la misma forma que el otro motor."""
        import torch

        pedido = texto if self._referencia else f"{self._voz_de_catalogo}: {texto}"
        entrada = self._ejemplo + self._bloque_texto(pedido)
        # Cuántos tokens como mucho puede necesitar este segmento, con la holgura de la receta.
        segundos_previstos = len(texto.split()) / self._wpm_esperado * 60
        techo = int(segundos_previstos * self.TOKENS_POR_SEGUNDO * self._holgura)
        nuevos = self._pide(entrada, max(64, techo))
        if self.INICIO_AUDIO in nuevos:
            nuevos = nuevos[nuevos.index(self.INICIO_AUDIO) + 1 :]
        codigos = [t - self.OFFSET_AUDIO for t in nuevos if t >= self.OFFSET_AUDIO]
        codigos = codigos[: (len(codigos) // self.CODIGOS_POR_FRAME) * self.CODIGOS_POR_FRAME]
        capas = self._capas(codigos)
        if capas is None:
            raise SystemExit(f"[FAIL] Orpheus no produjo audio para el segmento: {texto[:60]!r}")
        with torch.no_grad():
            onda = self._dec.decode(capas)
        return onda.detach().squeeze().unsqueeze(0).cpu().float()


def _compuestos(decenas: dict[str, int], unidades: dict[str, int]) -> dict[str, int]:
    """Las decenas con su unidad pegada, como quedan al normalizar «ninety-seven»: {«ninetyseven»: 97}."""
    return {d + u: vd + vu for d, vd in decenas.items() for u, vu in unidades.items()}


class RecortadorPorTexto:
    """Corta lo que el motor dice DESPUÉS de terminar el texto, localizando la última palabra.

    **Por qué no basta ninguna guarda de las que ya hay.** `quita_colas_sin_habla` calla lo que suena
    flojo y no dice nada, que es como divaga Kokoro. Orpheus divaga distinto: **habla alto y
    articula**, con frases inventadas y continuaciones de la referencia que se le dio de ejemplo. Y
    la guarda de ritmo tampoco lo caza: 48 palabras en 42,4 s son 68 wpm, dentro de la banda
    plausible. Un audio que suena perfecto y dice lo que no toca no lo detecta ningún umbral de
    energía ni de velocidad — hay que leer lo que dice.

    **Cómo corta.** Se transcribe el segmento con marcas por palabra, se emparejan con las palabras
    del texto pedido (`_empareja`, que tolera los errores del reconocedor) y **el final de la última
    palabra pedida es el corte**.

    **Si la última palabra no casa, NO se corta y se avisa**, para que el reintento con otra semilla
    haga su trabajo. Cortar sin haber llegado al final del texto se comería el resto de la frase, que
    es peor que dejar la divagación: lo segundo se oye, lo primero se cuela.

    **Cuánto recorta de verdad, y es menos de lo que parecía.** Medido el 08-09 sobre los 191
    segmentos del episodio 1 generados con `llama-server`, que para donde declara el GGUF: el recorte
    quita **1,8 s de 886,8 s de audio, el 0,20 %**, y solo 3 de 186 segmentos tienen más de 0,3 s que
    quitar —dos de ellos porque su texto pedido acaba a media frase y el modelo la completó, que no
    es divagación—.

    **Lo que ese 0,20 % NO demuestra**, y lo dice una auditoría que me corrigió la conclusión: que la
    divagación de la fila 112 fuera el token de parada equivocado de la fila 117. Es una media de UN
    run y **una media no acota una cola** — que es exactamente la forma que tenía la evidencia de la
    fila 112, un caso de 42,4 s de audio para 18,8 s de texto. Para atribuirlo haría falta el mismo
    guion generado por los dos caminos y comparar sus colas. Así que de momento: sobre este run la
    divagación es despreciable, la causa está sin establecer, y esta guarda se queda — es la única
    que lee lo que el audio DICE en vez de medir su energía o su velocidad.

    El alineador es **el mismo whisper que ya usa el karaoke**, no una pieza nueva, y va en CPU: el
    3B de Orpheus deja la tarjeta sin sitio.
    """

    # Cuántas palabras del guion se puede saltar el emparejador cuando el reconocedor las destroza.
    # **4 y no más, y el número está medido**: con 6 aparece un falso positivo en el control negativo
    # —recorta un segmento con el texto de otro—, y eso es peor que no recortar.
    VENTANA = 4
    # Cuántas palabras del guion pueden casar contra UN trozo: «thirteen hundreds» -> «1300s».
    PALABRAS_POR_TROZO = 3
    # Cuántos trozos pueden casar contra UNA palabra: «waxwork» -> «wax» + «work».
    TROZOS_POR_PALABRA = 2
    # Los números que forman siglos en este catálogo. No es una tabla de números: es la lista mínima
    # que hace falta para el patrón `<numero> hundred(s)`, que es el único que aparece.
    NUMEROS = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
        "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
        "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
        "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
        "ninety": 90,
    }  # fmt: skip
    # Los ORDINALES van en su propio espacio (el sufijo «o» de `_canon`) y no es un detalle: sin
    # separarlos, «one» y «first» acabarían valiendo lo mismo y el emparejador casaría cosas que no
    # son iguales — que es el único modo de fallo que este canonizador puede introducir.
    ORDINALES = {
        "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
        "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13,
        "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
        "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
    }  # fmt: skip
    _ORDINAL_EN_DIGITOS = re.compile(r"(\d+)(?:st|nd|rd|th)$")
    # **Las cifras compuestas** (F7.10, fila 262). Un explicador de economía dice cantidades: «one hundred
    # ninety-seven dollars», «seven percent», «three thousand two hundred». Whisper las escribe en
    # dígitos —«$197», «7%», «3,200»— y el canonizador de siglos no las casaba: los segmentos con
    # cifras de la cata de un explicador de economía quedaron SIN recortar la divagación (4 de 15, fila 261). Lo que
    # sigue es la gramática de los números en inglés hasta los miles, y nada más:
    #   - una decena y una unidad, con guion («ninety-seven», que se normaliza a «ninetyseven») o sin
    #     él («ninety seven»), son UN número;
    #   - `<número> hundred [and] <menos de cien>` y `<número> thousand [and] <menos de mil>`, y «a
    #     hundred», «a thousand»;
    #   - «dollar(s)» detrás de un número es la moneda (`usd`) y «percent» o «per cent», el porcentaje
    #     (`pct`): «$197» y «one hundred ninety-seven dollars» valen «197usd», y «7%» y «seven percent»,
    #     «7pct». Un porcentaje no casa nunca con una cantidad de dinero;
    #   - un ordinal sigue en su espacio (sufijo «o»), también el compuesto («twenty-first» → «21o») y
    #     el de las centenas («one hundredth» → «100o»).
    # Lo que la gramática no admite no se junta: «nineteen fifty» siguen siendo dos números, «19» y «50»,
    # como hasta ahora (y por eso sigue casando con «1950»).
    UNIDADES = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
    DECENAS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
               "ninety": 90}  # fmt: skip
    ORDINALES_DE_UNIDAD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
                           "eighth": 8, "ninth": 9}  # fmt: skip
    COMPUESTOS = _compuestos(DECENAS, UNIDADES)  # «ninetyseven» → 97
    COMPUESTOS_ORDINALES = _compuestos(DECENAS, ORDINALES_DE_UNIDAD)  # «twentyfirst» → 21
    MONEDA = {"dollar": "usd", "dollars": "usd"}
    # Lo que puede ir dentro de una cifra dicha con palabras: con estas, `_empareja` deja que una cifra
    # larga case contra un solo trozo («one hundred ninety-seven dollars» → «$197»), y solo con estas.
    PALABRAS_DE_CIFRA = (
        set(NUMEROS) | set(ORDINALES) | set(COMPUESTOS) | set(COMPUESTOS_ORDINALES) | set(MONEDA)
        | {"a", "and", "hundred", "hundreds", "hundredth", "thousand", "thousands", "thousandth"}
        | {"percent", "per", "cent"}
    )  # fmt: skip
    # Cuántas palabras del guion puede ocupar una cifra que casa contra un trozo: «three thousand two
    # hundred and forty-five dollars» son 7. Solo vale para tramos hechos de PALABRAS_DE_CIFRA.
    PALABRAS_POR_CIFRA = 8
    _DIGITOS = re.compile(r"(\d+(?:p\d+)?)(usd|pct)?$")

    def __init__(self, cfg: dict):
        self._modelo = cfg["modelo"]
        self._margen_s = float(cfg["margen_s"])
        self._asr = None
        # Vocabulario del NICHO que el reconocedor no conoce y parte o confunde. Es del CANAL
        # (F4.9): «assize» y «gibbet» son de un museo de la justicia inglesa y no de un estudio.
        self._vocabulario = tuple(cfg.get("vocabulario") or ())
        self._prompt_ids = None

    def _pipeline(self):
        if self._asr is None:
            from transformers import pipeline

            started = time.perf_counter()
            self._asr = pipeline("automatic-speech-recognition", model=self._modelo, device=-1, chunk_length_s=30)
            print(f"      [recorte] {self._modelo} en CPU, cargado en {time.perf_counter() - started:.1f}s", flush=True)
        return self._asr

    def _sesgo_de_vocabulario(self) -> dict:
        """`prompt_ids` con el vocabulario del nicho, o nada si el canal no declara ninguno.

        **Qué problema resuelve, medido el 12-09.** El run del episodio 2 murió DOS veces, y las dos
        en una frase con una palabra del nicho que el reconocedor no conoce: «A fanlight over a
        panelled door» (`fanlight` sale como «fan light») y «In a workshop, somewhere near the assize
        town» (`assize`). Quedaban por delante `gibbet` ×4, `swivel` ×4, `anvil` ×4 y `hoops` ×3: el
        run habría seguido cayendo. Cuando una de estas queda sin localizar en mitad de la frase, la
        última palabra se vuelve inalcanzable —a la última no se le salta— y la etapa entera muere.

        **Por qué un GLOSARIO y nunca el texto esperado.** Pasarle a whisper la frase que espera oír
        sesga muchísimo mejor, y es justo lo que no se puede hacer aquí: está documentado que el
        prompt se cuela en la transcripción, y entonces el emparejador casaría palabras que el motor
        no dijo y el corte se comería habla real sin que nada lo detecte — el peor fallo posible de
        esta pieza, y el que su control negativo persigue. Un glosario de términos sueltos no puede
        completar una frase. **Medido**: con un prompt de once términos sobre nueve audios del
        episodio, **cero** palabras del prompt aparecieron en transcripciones que no las decían.

        Los términos van al final porque solo entran los últimos ~224 tokens y los de cola pesan más.
        """
        if not self._vocabulario:
            return {}
        if self._prompt_ids is None:
            texto = "Terms used in this recording: " + ", ".join(self._vocabulario) + "."
            self._prompt_ids = self._asr.tokenizer.get_prompt_ids(texto, return_tensors="pt")
        return {"generate_kwargs": {"prompt_ids": self._prompt_ids}}

    # Iguala el inglés BRITÁNICO del guion con el AMERICANO que whisper tiende a escribir por
    # defecto cuando no hay indicios en el audio.
    #
    # **HONESTIDAD SOBRE POR QUÉ SE AÑADIÓ: no está demostrado que arreglara el fallo que lo
    # motivó.** El 12-09 el run murió en «A fanlight over a panelled door» (4/6 localizadas) y se
    # dio por hecho que la culpable era `panelled`. **Medido después, es falso**: whisper transcribe
    # `panelled` en británico correctamente, con prompt de sesgo y sin él, en las tres ventanas de
    # audio donde aparece. La que sí parte es `fanlight`, que sale como «fan light» — y eso ya lo
    # tolera `TROZOS_POR_PALABRA`. La causa real del 4/6 **queda sin determinar**: el segmento pasó
    # al relanzar, y el motor divaga distinto en cada pasada, así que pudo ser el azar de la semilla.
    #
    # Esto se queda porque cubre una divergencia real y posible —el guion trae `travelled` y
    # `labour`, y whisper escribe americano por defecto sin contexto— y porque su control negativo
    # demuestra que no casa palabras distintas. Pero **no se le atribuye un arreglo que no hizo**.
    #
    # Se tratan los dos patrones que aparecen de verdad en el guion, y no más:
    #   - `-ll` + sufijo -> `-l` + sufijo (panelled/paneled, travelled/traveled, cancelled/canceled)
    #   - `-our` final -> `-or` (labour/labor, honour/honor, neighbour/neighbor)
    # Se deja en la doble **ele** a propósito: es donde vive casi toda la divergencia, y ampliarlo a
    # cualquier consonante doble haría casar «latter» con «later», que son dos palabras distintas y
    # las dos plausibles en un canal de historia. Casar de más es peor que casar de menos: cortaría
    # el audio por donde no toca.
    _LL_ANTE_SUFIJO = re.compile(r"ll(ed|ing|er|est)\b")
    _OUR_FINAL = re.compile(r"our\b")

    @classmethod
    def _ortografia_comun(cls, t: str) -> str:
        """La palabra en una forma que no distingue el inglés británico del americano."""
        return cls._OUR_FINAL.sub("or", cls._LL_ANTE_SUFIJO.sub(r"l\1", t))

    _DINERO = re.compile(r"\$\s*(\d)")
    _PORCENTAJE = re.compile(r"(\d)\s*%")
    _DECIMAL = re.compile(r"(\d)\.(\d)")

    @classmethod
    def _normaliza(cls, t: str) -> str:
        """La palabra en minúsculas y sin puntuación, con el dinero y el porcentaje de whisper con nombre.

        «$197,» → «197usd», «7%» → «7pct» y «7.5» → «7p5»: el signo se quitaba con la puntuación y con
        él lo que decía (F7.10). El punto decimal queda como «p» para que «7.5%» no case con «seventy-five
        percent», que es lo que daría quitarlo.
        """
        s = cls._ortografia_comun(t.lower())
        sufijo = "usd" if cls._DINERO.search(s) else "pct" if cls._PORCENTAJE.search(s) else ""
        s = cls._DECIMAL.sub(r"\1p\2", s)
        s = "".join(c for c in s if c.isalnum())
        return s + sufijo if sufijo and s[-1:].isdigit() else s

    @classmethod
    def _bajo_cien(cls, p: list[str], i: int) -> tuple[int, int, bool] | None:
        """(valor, siguiente, es_ordinal) de un número de 1 a 99 que empieza en p[i], o None."""
        w = p[i] if i < len(p) else ""
        sig = p[i + 1] if i + 1 < len(p) else ""
        if w in cls.COMPUESTOS:
            return cls.COMPUESTOS[w], i + 1, False
        if w in cls.COMPUESTOS_ORDINALES:
            return cls.COMPUESTOS_ORDINALES[w], i + 1, True
        if w in cls.DECENAS:
            if sig in cls.UNIDADES:
                return cls.DECENAS[w] + cls.UNIDADES[sig], i + 2, False
            if sig in cls.ORDINALES_DE_UNIDAD:
                return cls.DECENAS[w] + cls.ORDINALES_DE_UNIDAD[sig], i + 2, True
            return cls.DECENAS[w], i + 1, False
        if w in cls.NUMEROS:
            return cls.NUMEROS[w], i + 1, False
        if w in cls.ORDINALES:
            return cls.ORDINALES[w], i + 1, True
        return None

    @classmethod
    def _bajo_mil(cls, p: list[str], i: int) -> tuple[int, int, bool, bool] | None:
        """(valor, siguiente, es_ordinal, es_plural) de un número de 1 a 999 que empieza en p[i], o None.

        `es_plural` es el siglo («seventeen hundreds»): acaba la cifra, como acababa con el canonizador
        de siglos.
        """
        sig = p[i + 1] if i + 1 < len(p) else ""
        if i < len(p) and p[i] == "a" and sig in ("hundred", "hundredth", "thousand", "thousandth"):
            valor, j, ordinal = 1, i + 1, False
        else:
            base = cls._bajo_cien(p, i)
            if base is None:
                return None
            valor, j, ordinal = base
            if ordinal:
                return valor, j, True, False
        centena = p[j] if j < len(p) else ""
        if centena in ("hundred", "hundreds", "hundredth") and valor < 100:
            if centena != "hundred":
                return valor * 100, j + 1, centena == "hundredth", centena == "hundreds"
            valor, j = valor * 100, j + 1
            k = j + 1 if j < len(p) and p[j] == "and" else j
            resto = cls._bajo_cien(p, k)
            if resto is not None:
                return valor + resto[0], resto[1], resto[2], False
        return valor, j, False, False

    @classmethod
    def _cifra(cls, p: list[str], i: int) -> tuple[str, int] | None:
        """(forma canónica, siguiente) de la cifra dicha con palabras que empieza en p[i], o None."""
        r = cls._bajo_mil(p, i)
        if r is None:
            return None
        valor, j, ordinal, plural = r
        millar = p[j] if j < len(p) else ""
        if not (ordinal or plural) and millar in ("thousand", "thousands", "thousandth") and valor < 1000:
            valor, j = valor * 1000, j + 1
            ordinal, plural = millar == "thousandth", millar == "thousands"
            if millar == "thousand":
                k = j + 1 if j < len(p) and p[j] == "and" else j
                resto = cls._bajo_mil(p, k)
                if resto is not None and not resto[3]:
                    valor, j, ordinal = valor + resto[0], resto[1], resto[2]
        return cls._con_unidad(str(valor) + ("o" if ordinal else ""), p, j, puede=not ordinal)

    @classmethod
    def _con_unidad(cls, cifra: str, p: list[str], j: int, *, puede: bool) -> tuple[str, int]:
        """La cifra con su moneda o su porcentaje si la palabra siguiente lo dice («dollars», «percent»)."""
        sig = p[j] if j < len(p) else ""
        if puede and sig in cls.MONEDA:
            return cifra + cls.MONEDA[sig], j + 1
        if puede and sig == "percent":
            return cifra + "pct", j + 1
        if puede and sig == "per" and j + 1 < len(p) and p[j + 1] == "cent":
            return cifra + "pct", j + 2
        return cifra, j

    @classmethod
    def _canon(cls, palabras: list[str]) -> str:
        """Forma canónica de una secuencia de palabras, con las CIFRAS llevadas a dígitos.

        **De dónde sale, en tres pasos.** Primero los siglos —«the seventeen hundreds», que el
        reconocedor devuelve como «the 1700s»—: de los 7 segmentos del episodio 1 que seguían sin
        emparejar tras tolerar los errores del medio, **6 eran este patrón**. Después el número suelto
        («the first 30 seconds», que mató un run) y los ordinales («the 18th century», otro). Y desde
        F7.10 (fila 262), las cifras compuestas, el dinero y el porcentaje de un explicador de economía
        (ver `UNIDADES`): sin ellas, los 4 segmentos con cifras de esa cata quedaban sin recortar.

        **No es un traductor de números, y es a propósito**: solo la gramática de los números en inglés
        hasta los miles. Un canonizador ambicioso empieza a casar cosas que no son iguales, y aquí casar
        de más es peor que casar de menos — cortaría el audio por un sitio que no corresponde. Por eso
        cada forma va en su espacio: «197» no es «179» ni «1097», «7pct» no es «7usd», «7» no es «7o» y
        «100» no es «100o». Lo que la gramática no junta («nineteen fifty») sigue saliendo número a número,
        pegado, como antes.
        """
        fuera, i = [], 0
        while i < len(palabras):
            w = palabras[i]
            cifra = cls._cifra(palabras, i)
            if cifra is not None:
                fuera.append(cifra[0])
                i = cifra[1]
                continue
            en_digitos = cls._ORDINAL_EN_DIGITOS.fullmatch(w)
            if en_digitos:
                fuera.append(f"{int(en_digitos.group(1))}o")
                i += 1
                continue
            # «1300s» -> «1300»: el plural que añade el reconocedor no es parte del número
            if len(w) > 1 and w[-1] == "s" and w[:-1].isdigit():
                w = w[:-1]
            digitos = cls._DIGITOS.fullmatch(w)
            if digitos and not digitos.group(2):
                # «197» seguido de «dollars» es lo mismo que «$197»: el reconocedor escribe una u otra.
                texto, i = cls._con_unidad(w, palabras, i + 1, puede="p" not in w)
                fuera.append(texto)
                continue
            fuera.append(w)
            i += 1
        return "".join(fuera)

    _SOLO_CIFRA = re.compile(r"\d+(?:p\d+)?")

    @classmethod
    def _casan(cls, pedido: str, oido: str, detras: str) -> bool:
        """¿Dice lo mismo el tramo del guion (`pedido`) que lo oído (`oido`), los dos ya canónicos?

        Iguales, o **la misma cifra con el «$» que whisper pone por su cuenta**: en la cata de economía el guion
        decía «about seven hundred sixty-one», sin «dollars», y whisper escribió «about $761» porque la
        frase habla de dinero (F7.10). El «$» no es una palabra dicha: es lo que whisper deduce. El «%» sí
        lo es («percent»), así que el porcentaje no tiene esta holgura, y al revés tampoco: un guion que
        dice «dollars» no casa con una cifra sin ellos.

        `detras` es la palabra del guion que sigue al tramo. Si es la moneda («one hundred ninety-seven» y
        luego «dollars»), la holgura no vale: el tramo bueno es el que la incluye, y casar sin ella dejaría
        «dollars» fuera, que puede ser la última palabra pedida.
        """
        if pedido == oido:
            return True
        return (
            oido.endswith("usd")
            and detras not in cls.MONEDA
            and cls._SOLO_CIFRA.fullmatch(pedido) is not None
            and oido[:-3] == pedido
        )

    # **Las cantidades en dígitos que whisper escribe con la unidad aparte** (canal de economía, 06-10-2026).
    # El guion escribe «92.3%» y «$8.1 billion», y whisper oye lo mismo pero lo escribe «92.3 percent» y «8.1
    # billion dollars». `_canon` no las junta: el decimal no se une a su unidad (`_con_unidad` con `puede` en
    # falso) y el emparejador no casa varias palabras contra varios trozos, así que «billion» y «dollars» quedaban
    # fuera de sitio. En el episodio 1 de ese canal, 8 de sus 10 incidencias eran esto, y una de ellas recortó por
    # silencio y se comió «$10.4 billion», el dato de la frase.
    ESCALAS = {"million", "millions", "billion", "billions", "trillion", "trillions"}

    @classmethod
    def _une_cantidades(cls, fichas: list[tuple[str, tuple | None]]) -> list[tuple[str, tuple | None]]:
        """Junta en una ficha cada cantidad cuya unidad va en la palabra de al lado, con las palabras ya normalizadas.

        `fichas` son pares (palabra normalizada, marca de tiempo o `None`). Se aplica igual a lo pedido y a lo oído,
        antes de emparejar, para que las dos formas acaben iguales:
          - «92p3» + «percent» (o «per cent») → «92p3pct», como «92.3%»;
          - «8p1» + «dollars» → «8p1usd», como «$8.1»;
          - «8p1» + «billion» + «dollars» → «8p1usd» + «billion», como «$8.1 billion». La marca de «billion» acaba
            donde acababa «dollars», para que el corte caiga detrás de la última palabra dicha.
        Solo junta un número suelto con la unidad que lo sigue. No cambia el número ni la unidad, así que no hace
        casar dos cantidades distintas: «7p5» sigue sin ser «75», y un porcentaje sigue sin ser dinero.
        """

        def une(a: tuple | None, b: tuple | None) -> tuple | None:
            return None if a is None or b is None else (a[0], b[1])

        fuera, i = [], 0
        while i < len(fichas):
            palabra, marca = fichas[i]
            sig = fichas[i + 1][0] if i + 1 < len(fichas) else ""
            sig2 = fichas[i + 2][0] if i + 2 < len(fichas) else ""
            if cls._SOLO_CIFRA.fullmatch(palabra):
                if sig == "percent":
                    fuera.append((palabra + "pct", une(marca, fichas[i + 1][1])))
                    i += 2
                    continue
                if sig == "per" and sig2 == "cent":
                    fuera.append((palabra + "pct", une(marca, fichas[i + 2][1])))
                    i += 3
                    continue
                if sig in cls.MONEDA:
                    fuera.append((palabra + "usd", une(marca, fichas[i + 1][1])))
                    i += 2
                    continue
                if sig in cls.ESCALAS and sig2 in cls.MONEDA:
                    fuera.append((palabra + "usd", marca))
                    fuera.append((sig, une(fichas[i + 1][1], fichas[i + 2][1])))
                    i += 3
                    continue
            fuera.append((palabra, marca))
            i += 1
        return fuera

    @classmethod
    def _prepara(cls, texto: str, chunks: list[dict]) -> tuple[list[str], list[dict]]:
        """Lo pedido y lo oído, normalizados y con las cantidades unidas (`_une_cantidades`), listos para emparejar.

        Las etiquetas emocionales (`<gasp>`) son sonido, no palabras: no se buscan en la transcripción y por eso se
        quitan del texto antes de emparejar.
        """
        pedidas = [cls._normaliza(p) for p in texto.split() if not p.startswith("<")]
        pedidas = [p for p, _ in cls._une_cantidades([(p, None) for p in pedidas if p])]
        # **Un trozo que empieza sin espacio continúa la palabra del anterior** (episodio 2, 07-10). Con
        # marcas palabra a palabra, whisper parte «38.4%.» en « 38» y «.4%.»: la frase completa sale bien escrita,
        # pero el emparejador veía «38» y «4pct» y no casaba la cifra, que era la última palabra de 7 incidencias.
        # Cada palabra nueva de whisper empieza por un espacio; lo que no lo lleva es el resto de la misma.
        crudos: list[tuple[str, tuple]] = []
        for t in chunks:
            if not t.get("timestamp") or t["timestamp"][1] is None:
                continue
            texto_trozo = t["text"]
            if crudos and texto_trozo and not texto_trozo[0].isspace():
                anterior, marca = crudos[-1]
                crudos[-1] = (anterior + texto_trozo, (marca[0], t["timestamp"][1]))
            else:
                crudos.append((texto_trozo, t["timestamp"]))
        oidas = [(cls._normaliza(t), marca) for t, marca in crudos if cls._normaliza(t)]
        trozos = [{"text": p, "timestamp": marca} for p, marca in cls._une_cantidades(oidas)]
        return pedidas, trozos

    @classmethod
    def _cabe_en_una_cifra(cls, palabras: list[str]) -> bool:
        """¿Son todas palabras de una cifra (o dígitos), con al menos un número? Solo esos tramos pasan de
        PALABRAS_POR_TROZO al casar contra un trozo."""
        return any(cls._cifra(palabras, k) for k in range(len(palabras))) and all(
            w in cls.PALABRAS_DE_CIFRA or cls._DIGITOS.fullmatch(w) for w in palabras
        )

    def _empareja(self, pedidas: list[str], trozos: list[dict]) -> list[float | None]:
        """Marca de fin de cada palabra pedida, tolerando los errores del reconocedor.

        **De dónde sale este emparejador y qué sustituye** (medido el 08-09 sobre los 191 segmentos
        del episodio 1, addendum fila 114). El anterior exigía que **todas** las palabras casaran
        exactas y en orden, y solo avanzaba al acertar: un único error de transcripción en MEDIO de
        la frase lo dejaba atascado ahí y perdía todo lo de detrás. De ahí los «2/17». Resultado:
        **155 de 191**, y los 36 restantes matan el run.

        Tres tolerancias, cada una contra un fallo observado:

        - **Saltarse palabras del guion** (`VENTANA`): si el trozo casa con alguna de las siguientes
          esperadas, se avanza hasta ahí. Arregla el error en medio. 155 -> 184.
        - **Casar 1-3 palabras contra 1 trozo**: el reconocedor une «thirteen hundreds» en «1300s».
          Con `_canon`, 184 -> 189. Una cifra dicha con palabras puede ocupar hasta `PALABRAS_POR_CIFRA`
          («one hundred ninety-seven dollars» → «$197», F7.10), y solo una cifra.
        - **Casar 1 palabra contra 2 trozos**: parte «waxwork» en «wax work». 189 -> 190.

        **Lo que NO se relaja, y son DOS cosas.** Una: la última palabra pedida tiene que casar, y
        eso lo comprueba `corta`. Dos, y la aprendí de una auditoría que bloqueó la primera versión
        de este método: **a la última palabra tampoco se le salta**. Con la tolerancia alcanzando el
        final, un trozo que normalice igual que la palabra final la casaba antes de tiempo y el corte
        se comía el resto del habla — 178 de 179 veces en el control que lo reproduce. Así que la
        tolerancia va al medio de la frase y **de verdad** nunca al final, que cuesta 4 segmentos de
        recall (190 -> 186 de 191) y los paga con gusto.

        **El residual que queda abierto, dicho porque no es cero.** Con DOS artefactos ordenados a la
        vez —el bigrama de cola repetido temprano— todavía se puede adelantar el corte: 188 de 191 si
        se inyecta a propósito. No se cierra por dos motivos: exige dos alucinaciones del reconocedor
        en vez de una, y en su causa física más probable —que el motor repita la cola de la frase—
        cortar en la primera ocurrencia **es lo correcto**, porque la segunda ya es divagación.

        **El control negativo que lo demuestra.** Se emparejó cada segmento contra el texto de OTRO
        segmento **de su misma lámina** —el caso difícil: comparten vocabulario y estilo— y el
        criterio tiene que NEGARSE a cortar en los 191. Con estas tres tolerancias: **0 falsos**. Sin
        la exigencia de la última palabra: **88 falsos de 191**, o sea que recortaba audio con el
        texto de otro casi la mitad de las veces. Y con `VENTANA = 6` aparece 1 falso, que es por qué
        vale 4 y no más.
        """
        marcas: list[float | None] = [None] * len(pedidas)
        i = j = 0
        while j < len(trozos) and i < len(pedidas):
            casado = False
            for salto in range(min(self.VENTANA, len(pedidas) - i)):
                for n_ped in range(1, min(self.PALABRAS_POR_CIFRA, len(pedidas) - i - salto) + 1):
                    # Más de PALABRAS_POR_TROZO solo una cifra dicha con palabras contra un trozo en dígitos
                    # («one hundred ninety-seven dollars» → «$197», F7.10). Cualquier otro tramo, como antes.
                    if n_ped > self.PALABRAS_POR_TROZO and not self._cabe_en_una_cifra(
                        pedidas[i + salto : i + salto + n_ped]
                    ):
                        break
                    for n_tro in range(1, min(self.TROZOS_POR_PALABRA, len(trozos) - j) + 1):
                        if n_ped > 1 and n_tro > 1:
                            continue  # muchos-a-muchos no: solo une un lado o el otro
                        # **A la ULTIMA palabra no se salta: tiene que ser la siguiente esperada.**
                        # Sin esta linea la tolerancia alcanza el final de la frase, y entonces un
                        # trozo que normalice igual que la palabra final la casa ANTES DE TIEMPO: el
                        # corte se clava ahi y **se come el resto del habla**, con `recortado: True`
                        # y sin que la banda de ritmo lo note, porque el audio queda mas corto y no
                        # mas largo. Es un fallo que no se oye hasta que el video esta montado.
                        # Medido con el control que lo reproduce a proposito —se inserta la palabra
                        # final como trozo espurio donde el emparejador la va a mirar—: sin esta
                        # linea corta antes en **178 de 179** casos; con ella, en **0**. Y la auditoria
                        # lo confirmo con un control PROPIO y distinto del mio: 557 de 557 cortes
                        # tempranos insertando la palabra final y 536 de 537 sustituyendola, contra
                        # **0** en los dos con la guarda puesta. Cuesta 4 segmentos de recall
                        # (190 -> 186 de 191) y se paga: no recortar es inocuo —dispara otra
                        # semilla— y recortar de mas se cuela hasta el video.
                        if salto > 0 and i + salto + n_ped - 1 >= len(pedidas) - 1:
                            continue
                        izq = pedidas[i + salto : i + salto + n_ped]
                        der = [self._normaliza(t["text"]) for t in trozos[j : j + n_tro]]
                        detras = pedidas[i + salto + n_ped] if i + salto + n_ped < len(pedidas) else ""
                        if not self._casan(self._canon(izq), self._canon(der), detras):
                            continue
                        for k in range(n_ped):
                            marcas[i + salto + k] = float(trozos[j + n_tro - 1]["timestamp"][1])
                        i, j, casado = i + salto + n_ped, j + n_tro, True
                        break
                    if casado:
                        break
                if casado:
                    break
            if not casado:
                j += 1  # un trozo que no es del guion —un ruido, una palabra inventada— se ignora
        return marcas

    def corta(self, wav, sr: int, texto: str):
        """Devuelve (wav_recortado, informe). El informe va a la procedencia, no se pierde."""
        import numpy as np

        plano = wav[0] if wav.dim() > 1 else wav
        entero = plano.shape[-1] / sr
        salida = self._pipeline()(
            {"raw": plano.numpy().astype(np.float32), "sampling_rate": sr},
            return_timestamps="word",
            **self._sesgo_de_vocabulario(),
        )
        pedidas, trozos = self._prepara(texto, salida.get("chunks", []))
        marcas = self._empareja(pedidas, trozos)
        casadas = sum(1 for m in marcas if m is not None)
        # **La última palabra pedida tiene que casar, y esto es el corazón del criterio.** Es lo que
        # separa «sé dónde acaba el texto» de «he encontrado unas cuantas palabras por ahí». Sin esta
        # línea, el emparejador tolerante recorta 190 de los 191 segmentos del episodio 1 pero
        # **falsifica 88**: corta el audio de un segmento usando el texto de otro. Con ella y con la
        # guarda de la cola de `_empareja`, **186 de 191 y cero falsos** — y el recall que se pierde
        # es el precio de las dos, no de esta línea sola.
        fin = marcas[-1] if marcas and marcas[-1] is not None else None
        # **Lo que el segmento DIJO, no solo dónde acaba** (F5.9). Hasta el 18-09 este informe solo
        # servía para recortar la divagación, y `casadas/pedidas` iba como texto: nadie lo comparaba
        # con nada. El 15-09 el motor se comió «No. Sit.» de «Nora said, "¡Biscuit! ¡No! ¡Sit!"» y el
        # audio se montó igual —ese segmento está en la procedencia con **3/5**, el mínimo de los
        # 2.325 medidos—. Con los tres campos de abajo, `_genera_con_plausibilidad` puede decidir si
        # reintentar, que es lo que separa «sé dónde acaba» de «ha dicho lo que se le pidió».
        informe = {
            "palabras": f"{casadas}/{len(pedidas)}",
            "casadas": casadas,
            "pedidas": len(pedidas),
            "fraccion_casada": round(casadas / len(pedidas), 3) if pedidas else 1.0,
            "sin_casar_seguidas": _racha_sin_casar(marcas),
            "segundos_generados": round(entero, 2),
        }
        # Dónde acabó la última palabra que SÍ casó y cuántas pedidas quedan detrás: el respaldo por silencio no
        # puede cortar antes de que esas hayan tenido tiempo de decirse (`_corta_por_silencio`).
        casadas_en = [k for k, m in enumerate(marcas) if m is not None]
        if casadas_en:
            informe["ultima_casada_s"] = round(float(marcas[casadas_en[-1]]), 2)
            informe["pedidas_detras"] = len(pedidas) - 1 - casadas_en[-1]
        if fin is None:
            informe["recortado"] = False
            print(
                f"      [recorte] no casa la última palabra ({casadas}/{len(pedidas)} localizadas): NO se recorta",
                flush=True,
            )
            return wav, informe
        corte = min(entero, fin + self._margen_s)
        informe["recortado"] = True
        informe["segundos_utiles"] = round(corte, 2)
        informe["divagacion_s"] = round(entero - corte, 2)
        return plano[: int(corte * sr)].unsqueeze(0), informe


def huella_de_la_referencia(job: dict) -> dict | None:
    """Identifica el clip que el motor de clonado imita: su nombre y su CONTENIDO.

    Va en la firma del audio crudo, y hace falta el contenido y no solo la ruta por un motivo
    medido el 07-09-2026: **la referencia se regenera y no sale byte a byte igual**. Kokoro no es
    determinista —dos pasadas del mismo texto con la misma voz y la misma velocidad dan sha256
    distintos, también en CPU—, así que un clip regenerado conserva el nombre y cambia el fichero.
    Comparar solo la ruta daría por bueno un crudo hecho con otra voz.

    Devuelve `None` con Kokoro, que no clona nada: ahí la voz la identifica `job["voz"]`.
    """
    referencia = job.get("referencia")
    if not referencia:
        return None
    ruta = Path(referencia)
    if not ruta.exists():
        return {"archivo": ruta.name, "sha256": "(ausente)"}
    return {"archivo": ruta.name, "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest()[:16]}


MOTORES = {"kokoro": MotorKokoro, "orpheus": MotorOrpheus}

# El recortador carga whisper, que tarda unos segundos: se construye UNA vez por proceso y no una
# vez por lamina. La clave es la propia configuracion, asi que un trabajo que la cambiara a mitad
# tendria su propio recortador en vez de reutilizar en silencio el anterior.
_RECORTADORES: dict = {}


def _recortador_de(job: dict):
    """Devuelve el recortador que declare el trabajo, o None si el canal no lo pide.

    **None es una respuesta valida y frecuente** (F4.9): Kokoro no divaga, asi que su receta declara
    `recorte_por_texto: null` y aqui no se inventa uno. Lo que no se admite es la ausencia de la
    clave, y eso lo comprueba el adaptador antes de llegar hasta aqui.
    """
    cfg = job.get("recorte_por_texto")
    if not cfg:
        return None
    clave = json.dumps(cfg, sort_keys=True)
    if clave not in _RECORTADORES:
        _RECORTADORES[clave] = RecortadorPorTexto(cfg)
    return _RECORTADORES[clave]


def load_engine(job: dict):
    """Instancia el motor que declara el trabajo. Sin motor no se adivina: se falla."""
    motor = job.get("motor")
    if motor not in MOTORES:
        raise SystemExit(
            f"[FAIL] 'motor' del trabajo es {motor!r}; admitidos: {sorted(MOTORES)}. "
            "Lo declara la receta de voz del canal, y el adaptador no elige por su cuenta."
        )
    return MOTORES[motor](job)


def _recorta_bordes(wav, sr: int, umbral_db: float, margen_ms: int):
    """Quita el silencio de cabeza y cola de un segmento, dejando un margen de seguridad.

    Motivo medido (F2.16): la receta trocea la narración frase a frase, y cada llamada al
    motor devuelve su propio margen de silencio en los bordes. Al concatenar, esos márgenes se
    suman a la pausa de 250 ms que ya se añade a propósito. En una lámina de 3 frases eran
    **2,6 s de silencio de más** (6,48 s frente a los 3,86 s del mismo texto en una sola
    llamada); en un long-form de 40 láminas, más de un minuto de relleno.

    Lo que se recorta es SOLO el borde: las pausas dentro de la frase —la respiración que hace
    que la narración suene humana— se quedan. El margen evita comerse una `s` inicial o una
    oclusiva final, que es el riesgo real de recortar por energía.
    """
    import torch

    plano = wav[0] if wav.dim() > 1 else wav
    pico = plano.abs().max()
    if pico <= 0:
        return wav
    umbral = pico * (10 ** (umbral_db / 20))
    sonoro = (plano.abs() > umbral).nonzero()
    if sonoro.numel() == 0:  # segmento entero por debajo del umbral: se deja tal cual
        return wav
    margen = int(sr * margen_ms / 1000)
    ini = max(0, int(sonoro[0]) - margen)
    fin = min(plano.numel(), int(sonoro[-1]) + margen + 1)
    return torch.as_tensor(plano[ini:fin]).unsqueeze(0)


# Banda de ritmo plausible para UN segmento, en palabras por minuto de audio.
# No es una decision de canal ni de estilo: es el rango dentro del cual un segmento puede estar bien.
# Fuera de el no hay ritmo que ajustar, hay un fallo del motor.
WPM_MINIMO, WPM_MAXIMO = 40.0, 320.0
REINTENTOS_MAXIMOS = 3

# --- Cuándo se da por hecho que el segmento SE COMIÓ texto (F5.9, 18-09-2026) --------------------
#
# El 15-09, oyendo el episodio de un canal: el motor dijo «Biscuit.» donde el guion pedía
# «Biscuit! No! Sit!», el gate de narración dio VERDE y lo cazó el oído. Las guardas que ya había
# miden el TIEMPO —ritmo implausible, saturación— y el recorte mide dónde ACABA el texto; ninguna
# mira si lo dijo entero.
#
# **Los dos números salen de medir, no de elegir.** Sobre los **2.325 segmentos** con cobertura
# registrada en la procedencia de los 12 episodios ya producidos (`*/audio/generacion-voz.json`):
# mediana 100 %, p10 94,1 %, p5 88,9 %, p1 80 %, mínimo 60 % — y ese mínimo **es el caso del «Biscuit»**,
# 3 de 5 palabras en ese mismo run. Contadas las candidatas de cada regla:
#
#     faltan>=2 y fracción<0,90  ->  54 segmentos (2,3 %)  ·  4,5 por episodio
#     faltan>=2 y fracción<0,80  ->  19            (0,8 %) ·  1,6
#     faltan>=2 y fracción<0,75  ->   9            (0,4 %) ·  0,8   <- la elegida
#     faltan>=3, sin fracción    ->   8            (0,3 %) ·  0,7   <- NO caza el caso del «Biscuit»
#
# **Qué añade cada condición, dicho con exactitud** (lo apuntó la auditoría de F5.9, porque el
# comentario que había aquí lo contaba al revés): para un segmento de 5 palabras o más, `frac<0,75`
# ya implica que faltan 2, así que **`PALABRAS_QUE_FALTAN_MINIMO` solo decide en segmentos de 4
# palabras o menos** — ahí calla a los que perderían una sola palabra (3/4 no dispara). Hoy el
# corpus **no tiene ninguno**: el segmento más corto de los 2.325 pide 5 palabras, porque el troceo
# funde los fragmentos por debajo de ese mínimo. Se conserva como guarda del caso que el troceo
# deje pasar mañana, no como la condición que hace el trabajo. Con la regla entera se reintenta
# **menos de una vez por episodio** (9 en 12) y el caso que originó la feature se caza.
PALABRAS_QUE_FALTAN_MINIMO = 2
FRACCION_CASADA_MINIMA = 0.75


def _racha_sin_casar(marcas: list) -> int:
    """La racha más larga de palabras pedidas que no aparecen en la transcripción (F5.9).

    Es la firma de una FRASE perdida, frente a las palabras sueltas que el reconocedor falla con un
    nombre propio: cuatro fallos repartidos son ruido suyo, cuatro seguidos son texto que no se dijo.
    **Hoy solo se publica** en la procedencia y ninguna decisión depende de ella, porque no hay
    datos históricos con los que calibrar un umbral — y es justo el dato que hace falta para poder
    calibrarlo mañana.

    Una `marca` a `None` es una palabra pedida que no se localizó.
    """
    racha = mayor = 0
    for marca in marcas:
        racha = racha + 1 if marca is None else 0
        mayor = max(mayor, racha)
    return mayor


def _se_comio_texto(informe: dict) -> bool:
    """¿Este segmento dejó fuera parte de lo que se le pidió decir? (F5.9)

    Trabaja sobre el informe que `RecortadorPorTexto.corta` acaba de devolver, así que **no
    transcribe nada nuevo**: la transcripción ya se pagó para saber dónde recortar.

    **Lo que no se puede medir no se reintenta**, porque inventar un motivo gastaría GPU sin saber si
    hay algo que arreglar. Son tres los caminos que no se pueden medir, y el tercero lo destapó la
    auditoría de F5.9 midiendo en vez de leer el docstring:

    1. **Un canal sin `recorte_por_texto`**: no hay informe, así que no hay campos.
    2. **El recorte que no casó**: manda `sin_recortar`, que ya reintenta por su cuenta.
    3. **El respaldo por silencio**: aquí el informe **sí trae** `casadas`/`pedidas`, porque esa rama
       los arrastra con `{**informe, ...}` — pero son los del emparejamiento que **falló**, así que
       miden al reconocedor y no al motor. Sin esta salida, un 3/10 que no casó volvería a gastar
       cuatro generaciones por un número que no dice lo que parece. En los 2.325 segmentos medidos
       hay **2** con respaldo, los dos 4/5, así que hoy no cambia ninguna salida: se cierra porque
       el diseño lo decía y el código no lo hacía.
    """
    if not informe.get("recortado") or informe.get("respaldo"):
        return False
    pedidas, casadas = informe.get("pedidas"), informe.get("casadas")
    if not isinstance(pedidas, int) or not isinstance(casadas, int) or pedidas <= 0:
        return False
    faltan = pedidas - casadas
    return faltan >= PALABRAS_QUE_FALTAN_MINIMO and (casadas / pedidas) < FRACCION_CASADA_MINIMA


# Cuantas muestras seguidas pegadas al techo hacen falta para llamarlo saturacion y no una cresta.
# A 24 kHz, 24 muestras son 1 ms: una consonante fuerte puede tocar el techo un instante, un
# artefacto se queda ahi.
MUESTRAS_SATURADAS_SEGUIDAS = 12


def racha_saturada(wav) -> int:
    """La racha mas larga de muestras pegadas al techo. Cero si el segmento respira.

    **De donde sale** (05-09, repaso del episodio 1 de un canal): «en el minuto 2.55 se escuchan
    ruidos tipo artefactos que danan el audio». Medido: en 2:55,7-2:56,4 el pico salta de 13.500 al
    techo absoluto —32.768— durante 1,2 s con 41 muestras saturadas, y despues silencio. No es habla
    alta: es el motor reventando al final de un trozo. `_recorta_bordes` no lo quita porque recorta
    lo que esta por DEBAJO del umbral, y esto esta por encima de todo.

    **Se mide contra el techo del FORMATO, no contra el pico del trozo**, y la diferencia no es
    teorica: la primera version comparaba con el maximo del propio segmento, asi que TODO segmento
    tenia por definicion su pico «al techo» y el artefacto de 2:55 daba 1 muestra, exactamente lo
    mismo que dos segundos de habla limpia. La medicion no distinguia nada. Saturar es tocar el
    limite del formato, que en un tensor de audio en coma flotante es 1,0.
    """
    plano = wav[0] if wav.dim() > 1 else wav
    if plano.numel() == 0:
        return 0
    techo = 0.999 if plano.is_floating_point() else 32767 * 0.999
    al_techo = (plano.abs() >= techo).tolist()
    mejor = actual = 0
    for x in al_techo:
        actual = actual + 1 if x else 0
        mejor = max(mejor, actual)
    return mejor


def _pausas(plano, umbral: float, desde: int) -> list[tuple[int, int]]:
    """Los tramos INTERIORES que estan por debajo del umbral, en (inicio, fin) de muestra.

    Interiores quiere decir que no tocan ningun borde del segmento: el borde ya lo trata
    `_recorta_bordes`, y entre frases se anade el silencio que declara la receta. Tocarlo aqui
    tambien lo contaria dos veces — el defecto que F2.16 midio en 2,6 s de relleno por lamina.
    """
    callado = (plano.abs() <= umbral).tolist()
    salida, inicio = [], None
    for i, mudo in enumerate(callado + [False]):
        if mudo and inicio is None:
            inicio = i
        elif not mudo and inicio is not None:
            if i - inicio >= desde and inicio > 0 and i < len(callado):
                salida.append((inicio, i))
            inicio = None
    return salida


def quita_colas_sin_habla(wav, sr: int, colas: dict | None):
    """Calla lo que el motor genera cuando ya no le queda texto: suena flojo, dura mucho y no dice nada.

    **De donde sale** (06-09). Con las pausas ya calladas a -78 dB, se seguia oyendo ruido, con
    dos ejemplos: «en el minuto 3.12 del video tienes un ejemplo de ruido» y «en el minuto 3.44 hay
    otro ruido». Medido en el 3:12: **1,25 s de sonido a -35/-19 dB** pegado al silencio. No es el
    suelo de ruido —eso estaba a -50 dB y ya se quito— ni un chasquido —los que parecian clics
    resultaron ser el ataque normal de una palabra, con su rampa de -100 a -20 dB—: es una **cola de
    segmento**, lo que un motor sigue generando despues de decir la ultima palabra (se midio con
    Chatterbox, que ya no esta en el proyecto; la guarda se conserva porque el defecto no es suyo
    en exclusiva y Kokoro tambien murmura al quedarse sin texto).

    **Que lo separa del habla.** No la planitud: el tramo de 3:12 sube 16 dB, asi que un detector de
    monotonia no lo cazaba. Lo que lo delata es que **suena mucho rato sin acercarse nunca al nivel
    de la voz**: el habla de este audio llega a -6 dB y esto no pasa de -19. Y ademas **muere contra
    un silencio**, que es lo que lo hace especifico de una cola y no de un susurro en mitad de una
    frase — por eso se exige que toque uno de los silencios que dejo `limpia_pausas`.

    `colas` lo declara la receta del canal, y `None` significa «este canal no las quita».
    """
    import torch

    if not colas:
        return wav
    plano = wav[0] if wav.dim() > 1 else wav
    pico = float(plano.abs().max())
    if pico <= 0:
        return wav

    techo = pico * (10 ** (float(colas["techo_db"]) / 20))
    minimo = int(sr * int(colas["minimo_ms"]) / 1000)
    rampa = int(sr * int(colas["rampa_ms"]) / 1000)
    v = int(sr * 0.02)
    picos = [float(plano[i : i + v].abs().max()) for i in range(0, plano.numel() - v, v)]
    mudo = [x == 0.0 for x in picos]

    paso = torch.linspace(0.0, 1.0, rampa, dtype=plano.dtype)
    baja = 0.5 * (1 + torch.cos(torch.pi * paso))
    sube = 0.5 * (1 - torch.cos(torch.pi * paso))

    trozos, cursor, i = [], 0, 0
    while i < len(picos):
        if mudo[i] or picos[i] > techo:
            i += 1
            continue
        j = i
        while j < len(picos) and not mudo[j] and picos[j] <= techo:
            j += 1
        toca_silencio = (i > 0 and mudo[i - 1]) or (j < len(picos) and mudo[j])
        if (j - i) * v >= minimo and toca_silencio:
            ini, fin = i * v, j * v
            if fin - ini > 2 * rampa:
                trozos += [
                    plano[cursor:ini],
                    plano[ini : ini + rampa] * baja,
                    torch.zeros(fin - ini - 2 * rampa, dtype=plano.dtype),
                    plano[fin - rampa : fin] * sube,
                ]
                cursor = fin
        i = j
    if not trozos:
        return wav
    trozos.append(plano[cursor:])
    return torch.cat(trozos).unsqueeze(0)


def limpia_pausas(wav, sr: int, respiracion: dict | None):
    """Calla el ruido de las pausas de VERDAD y les da aire. **Dentro de una frase no toca nada.**

    Dos peticiones del 05 y 06-09 sobre el mismo sitio del audio:

    - «en las pausas que usa el narrador, durante el silencio hay momentos que se escuchan ruidos y
      eso es lo que dana al video completo». Medido: de las 388 pausas de >=120 ms del episodio 1,
      **ninguna** estaba muda — todas llevaban un suelo de Chatterbox entre -44 y -52 dB.
    - «se podria hacer que fuera mas pausada la narracion, **no quiero decir que se baje la velocidad
      de habla** sino mas pausado que no corra tanto entre palabra y palabra». Cada palabra se queda
      como el motor la dijo; el aire entra solo en los huecos que ya existen.

    **Todo depende de `pausa_desde_ms`, y ese numero costo dos regresiones.** Estuvo en 70 ms, y
    70 ms no es una pausa: es el hueco que hay DENTRO de una frase, entre «Mum's» y «birthday».
    Tratarlo —alargarlo, y luego ademas callarlo— entrecorta la palabra. Se oyo las dos veces,
    la segunda como «habla como si tartamudeara la narradora», y la primera ya le sonaba raro
    aunque menos. En 300 ms solo entran las pausas de respirar y las de entre frases, que es donde
    el ruido se oye y donde el aire hace falta.

    Se hace sobre el archivo YA CONCATENADO: una pausa larga del narrador es cola de un segmento +
    el silencio que se anade entre frases + cabeza del siguiente, asi que trozo a trozo no se ve
    entera — y el umbral de un trozo flojo deja pasar tramos de habla que sobre el archivo no pasan.

    `respiracion` lo declara la receta del canal, y `None` significa «este canal no toca sus
    pausas». Es una respuesta, no un olvido (F4.9).
    """
    import torch

    if not respiracion:
        return wav
    plano = wav[0] if wav.dim() > 1 else wav
    pico = float(plano.abs().max())
    if pico <= 0:
        return wav

    umbral = pico * (10 ** (float(respiracion["umbral_db"]) / 20))
    desde = int(sr * int(respiracion["pausa_desde_ms"]) / 1000)
    minimo = int(sr * int(respiracion["pausa_minima_ms"]) / 1000)
    factor = float(respiracion["factor"])
    maximo = int(sr * int(respiracion["pausa_maxima_ms"]) / 1000)

    # **El fundido va ANTES de la pausa, sobre la cola de la palabra, no dentro del silencio.**
    #
    # Con la rampa dentro de la pausa, la cola de la ultima palabra —lo que queda por encima del
    # umbral y por tanto fuera de la pausa— se quedaba sonando entre el silencio de antes y el de
    # despues. Eso es una **isla**: 150-800 ms a -22/-49 dB flotando, y es exactamente lo que se
    # seguia oyendo como ruido despues de seis vueltas («00.32, 00.47, 01.06, 01.16, 01.26, 01.38»).
    # Lo que suena mal no es la cola sino el corte en seco contra el silencio digital.
    #
    # Con el fundido hacia atras, la cola decae hasta cero y la isla desaparece **sin quitar un
    # fonema**: la curva es cuadratica, asi que los primeros milisegundos apenas bajan y solo el
    # final —que ya venia decayendo solo— se apaga del todo.
    fundido = int(sr * int(respiracion["fundido_ms"]) / 1000)
    cae = torch.linspace(1.0, 0.0, fundido, dtype=plano.dtype) ** 2 if fundido else None
    alza = torch.linspace(0.0, 1.0, fundido, dtype=plano.dtype) ** 2 if fundido else None

    trozos, cursor = [], 0
    for inicio, fin in _pausas(plano, umbral, desde):
        # **La pausa se estira en PROPORCION, no a un valor fijo.** Un suelo suelto igualaria la
        # coma y el punto y aparte, y el guion los distingue: `factor` respeta esa estructura y
        # `pausa_minima_ms` es el suelo para que la mas corta tambien se note.
        # El techo evita que una pausa ya larga se dispare: una de 2 s por 1,6 son 3,3 s, y eso
        # es un hueco en pantalla sin subtitulo, no una pausa. Lo cazaba el auditor del karaoke quemado
        # (retirado en F6.7) como «mas de 3 s sin subtitulo», y en el episodio 1 le paso a 9 de las 135.
        mudo = min(max(int((fin - inicio) * factor), minimo), maximo)
        # **El fundido va DENTRO de la pausa, nunca sobre el habla de los lados.**
        #
        # Estuvo fuera —150 ms antes y 150 despues— para apagar la cola que quedaba flotando, y
        # funciono para eso y rompio otra cosa: el fundido de salida cae sobre la PRIMERA PALABRA de
        # la frase siguiente y el de entrada sobre la ultima. Se oyo enseguida: «cuando
        # comienza una frase la primera palabra la empieza en un volumen bajo y sube de forma
        # repentina... y al final de la frase, en la ultima palabra pasa lo mismo».
        #
        # Las colas se apagan donde SE PUEDE saber que son colas: `limpia_worker.apaga_colas` mira el
        # pico de la propia palabra y `apaga_islas` mira lo que queda flotando entre silencios. Las
        # dos usan las marcas del alineador. Aqui, sin esa informacion, cualquier fundido sobre el
        # habla es a ciegas — y a ciegas se come el principio de las frases.
        largo = min(fundido, mudo // 3)
        trozos.append(plano[cursor:inicio])
        if largo:
            trozos.append(plano[inicio : inicio + largo] * cae[-largo:])
        trozos.append(torch.zeros(mudo - 2 * largo, dtype=plano.dtype))
        if largo:
            trozos.append(plano[max(inicio, fin - largo) : fin][:largo] * alza[:largo])
        cursor = fin
    if not trozos:
        return wav
    trozos.append(plano[cursor:])
    return torch.cat(trozos).unsqueeze(0)


# Ritmo al que Orpheus narra el estilo dramatico del primer canal: **2,44 palabras/s**, medido sobre el
# episodio 1 tal como se publico (addendum fila 121). Es lo que permite estimar cuanto DEBERIA durar
# un segmento, y por tanto a partir de donde lo que suena ya no es texto sino divagacion.
RITMO_ESPERADO_PALABRAS_S = 2.44
# Un silencio de esta duracion dentro de un segmento no es una coma: es donde el motor ha terminado
# la frase y toma aire antes de inventar. Las pausas dentro de una frase leida miden 100-250 ms.
SILENCIO_DE_CIERRE_MS = 300
# Antes de esta fraccion de la duracion esperada el texto no puede haber acabado: un silencio ahi es
# una pausa dramatica, no un cierre. 0,75 deja margen a un narrador que vaya rapido.
FRACCION_MINIMA_DEL_TEXTO = 0.75


def _corta_por_silencio(
    wav,
    sr: int,
    palabras: int,
    umbral_db: float = -40.0,
    *,
    ultima_casada_s: float | None = None,
    pedidas_detras: int = 0,
):
    """Corte de RESPALDO cuando la transcripcion no sabe donde acaba el texto: el primer silencio
    largo despues de la duracion esperada del texto. Devuelve (wav_cortado, segundos) o None.

    **Por que existe** (12-09). El recorte por texto depende de que whisper localice la ultima
    palabra, y falla de forma sistematica con el vocabulario del nicho: `fanlight`, `assize`, los
    homofonos. Cuatro pasadas de la voz del episodio 2 murieron por eso, y un fallo en el 0,2 % del
    audio no puede costar el episodio. Este corte no lee nada: mide.

    **En que se apoya, y esta medido.** Orpheus divaga DESPUES de terminar la frase, tras una pausa
    —es como inventa: toma aire y sigue—, y el texto tiene una duracion predecible, 2,44 palabras/s.
    Asi que el primer silencio de >= 300 ms que aparezca pasado el 75 % de la duracion esperada es,
    con mucha probabilidad, el cierre de la frase. Todo lo que viene detras no se monta.

    **Lo que NO puede hacer y por eso es respaldo y no sustituto**: distinguir una pausa dramatica
    larga de un cierre, si cae pasado el 75 %. Cortaria antes de tiempo. Por eso va DESPUES del
    recorte por texto y solo cuando este no puede, y por eso se anota en la procedencia: un audio
    cortado por silencio se escucha en la revision final.

    **La guarda de la ultima palabra casada** (07-10-2026). En la primera semana de un canal de economía este
    corte se comio dos veces la cifra de la frase: «…fiscal year, $10.4 billion.» y «…to about 255...
    a rise of about 38.4%.». El texto de ese canal tiene pausas a proposito (la coma, los puntos
    suspensivos) justo antes del dato, y una cifra en digitos cuenta como una palabra aunque se digan
    cinco, asi que el 75 % de la duracion esperada caia antes de esa pausa. Con `ultima_casada_s` y
    `pedidas_detras` (del informe del recorte por texto), el silencio tampoco puede empezar antes de
    que las palabras que faltan tras la ultima casada hayan tenido tiempo de decirse.
    """
    import torch

    plano = wav[0] if wav.dim() > 1 else wav
    pico = float(plano.abs().max())
    if pico <= 0 or palabras <= 0:
        return None
    esperado_s = palabras / RITMO_ESPERADO_PALABRAS_S
    desde_s = esperado_s * FRACCION_MINIMA_DEL_TEXTO
    if ultima_casada_s is not None and pedidas_detras > 0:
        faltan_s = pedidas_detras / RITMO_ESPERADO_PALABRAS_S * FRACCION_MINIMA_DEL_TEXTO
        desde_s = max(desde_s, ultima_casada_s + faltan_s)
    ventana = int(sr * 0.02)
    umbral = pico * (10 ** (umbral_db / 20))
    picos = torch.tensor(
        [float(plano[i : i + ventana].abs().max()) for i in range(0, plano.numel() - ventana, ventana)]
    )
    callado = picos < umbral
    minimo_ventanas = max(1, int(SILENCIO_DE_CIERRE_MS / 20))
    desde_ventana = int(desde_s / 0.02)
    racha = 0
    for k in range(len(callado)):
        racha = racha + 1 if bool(callado[k]) else 0
        if racha >= minimo_ventanas and k - racha + 1 >= desde_ventana:
            # Si detras de este silencio ya no vuelve a sonar nada, es el final natural de la
            # frase y no hay divagacion que cortar. Solo hay corte si DESPUES del silencio hay habla.
            if not bool((~callado[k + 1 :]).any()):
                return None
            inicio_silencio = (k - racha + 1) * ventana
            # se corta al ARRANCAR el silencio, mas 100 ms para no comerse la ultima oclusiva
            corte = min(plano.numel(), inicio_silencio + int(sr * 0.1))
            return plano[:corte].unsqueeze(0), corte / sr
    return None


def _genera_con_plausibilidad(engine, segmento: str, recorte, numero: int, total: int, recortador=None):
    """Genera un segmento, **comprueba que dura lo que puede durar**, y **nunca para el run**.

    **De donde sale la guarda** (05-09, piloto de un canal): Chatterbox genero **377,9 s de habla para 63
    palabras** —10 palabras por minuto— en la primera lamina del episodio. No era silencio: el motor
    se desboco y siguio hablando. Un motor estocastico hace eso de vez en cuando, y sin esta guarda
    el fallo viaja hasta el video montado: seis minutos de galimatias dentro de uno de doce.

    **Por que aqui SI se reintenta**, cuando el proyecto prohibe los reintentos automaticos: aquella
    regla es para la API de YouTube —externa, con cuota y con efectos— y esto es una generacion local
    y determinista por semilla. Reintentar con otra semilla es la unica forma de salir de un
    muestreo malo, **y no se esconde**: los reintentos se cuentan y se publican en la procedencia.

    **Lo que cambio el 12-09, y por que: el pipeline SIEMPRE termina.** Hasta entonces, agotar los
    reintentos era `SystemExit` y el episodio moria. Cuatro pasadas de la voz del episodio 2 murieron
    asi, las cuatro porque el recorte por texto no localizaba una palabra del nicho —`fanlight`,
    `assize`— que el reintento con otra semilla no puede arreglar porque no es azar del muestreo. Un
    defecto en el 0,2 % del audio no puede costar el episodio entero. Ahora:

    - **Si el recorte por texto no casa**, se reintenta UNA vez —contra el azar— y si sigue sin
      casar se corta POR SILENCIO (`_corta_por_silencio`). Si tampoco hay silencio donde cortar, el
      audio se queda entero y se anota `respaldo: "sin_recorte"`.
    - **Si el ritmo o la saturacion siguen fuera de banda** tras `REINTENTOS_MAXIMOS`, se queda el
      MEJOR intento —el de ritmo mas cercano a la banda— y se anota `implausible` con el motivo.

    Nada de esto se esconde: cada caso va a la procedencia y se imprime como `[INCIDENCIA]`, que es lo
    que el informe de fin de episodio recoge para que el usuario decida en la revision final, sobre el
    video montado, y no etapa a etapa.
    """
    palabras = len(segmento.split())
    base = getattr(engine, "_seed", None)
    mejor = None  # (distancia a la banda, wav, intento, informe, motivo)
    motivo = ""
    for intento in range(REINTENTOS_MAXIMOS + 1):
        if intento and base is not None:
            # **La semilla se cambia EN EL MOTOR, no con `torch.manual_seed` aquí.** Un motor que
            # refija la semilla dentro de su propio `generate()` —lo hacían Chatterbox y lo hace
            # Orpheus— ignora lo que se siembre por fuera: las cuatro salidas serían idénticas y el
            # reintento, teatro.
            # Derivada del original para que el mismo trabajo dé los mismos reintentos.
            engine._seed = base + 1000 * intento + numero
        wav = engine.generate(segmento)
        # **El recorte por texto va ANTES que todo lo demás, y el orden importa.** Un motor que
        # divaga produce audio de sobra: medir su ritmo o su saturación sin cortar sería juzgar
        # un trozo que no se va a montar. Con el corte hecho, las dos guardas siguientes miden
        # exactamente lo que acabará en el vídeo.
        informe = None
        if recortador is not None:
            wav, informe = recortador.corta(wav, engine.sr, segmento)
        sin_recortar = informe is not None and not informe["recortado"]
        if sin_recortar and intento >= 1:
            # Segundo intento sin casar: ya no es azar. Respaldo por silencio, y se sigue.
            cortado = _corta_por_silencio(
                wav,
                engine.sr,
                palabras,
                ultima_casada_s=informe.get("ultima_casada_s"),
                pedidas_detras=informe.get("pedidas_detras", 0),
            )
            if cortado is not None:
                wav, segundos_utiles = cortado
                informe = {
                    **informe,
                    "recortado": True,
                    "respaldo": "silencio",
                    "segundos_utiles": round(segundos_utiles, 2),
                }
                print(
                    f"      [INCIDENCIA] segmento {numero}/{total}: recortado por SILENCIO, "
                    "la transcripcion no localizo el final",
                    flush=True,
                )
            else:
                informe = {**informe, "respaldo": "sin_recorte"}
                print(
                    f"      [INCIDENCIA] segmento {numero}/{total}: SIN RECORTAR, "
                    "ni la transcripcion ni el silencio dan un corte",
                    flush=True,
                )
            sin_recortar = False
        if recorte:
            wav = _recorta_bordes(wav, engine.sr, recorte["umbral_db"], recorte["margen_ms"])
        segundos = wav.shape[-1] / engine.sr
        wpm = palabras / segundos * 60 if segundos else 0.0
        racha = racha_saturada(wav)
        # **¿Dijo lo que se le pidió?** (F5.9). Las dos guardas de abajo miran el TIEMPO y el recorte
        # mira dónde ACABA el texto; esta es la única que mira si falta texto por el medio. Solo actúa
        # cuando el recorte SÍ casó —si no casó, manda `sin_recortar`, que ya reintenta— y usa el
        # informe que el recortador acaba de calcular: cero transcripciones nuevas, cero GPU.
        se_comio_texto = bool(informe) and _se_comio_texto(informe)
        if (
            WPM_MINIMO <= wpm <= WPM_MAXIMO
            and racha < MUESTRAS_SATURADAS_SEGUIDAS
            and not sin_recortar
            and not se_comio_texto
        ):
            if base is not None:
                engine._seed = base
            return wav, intento, informe
        motivo = (
            f"no se localizan todas sus palabras en el audio ({informe['palabras']}), "
            "así que no se sabe dónde acaba el texto y empieza la divagación"
            if sin_recortar
            else f"faltan {informe['pedidas'] - informe['casadas']} palabras de las pedidas "
            f"({informe['palabras']}, {informe['fraccion_casada']:.0%} localizado): el motor se comió texto"
            if se_comio_texto
            else f"{racha} muestras seguidas al techo (>= {MUESTRAS_SATURADAS_SEGUIDAS} es saturacion)"
            if racha >= MUESTRAS_SATURADAS_SEGUIDAS
            else f"{palabras} palabras en {segundos:.1f} s = {wpm:.0f} wpm, "
            f"fuera de [{WPM_MINIMO:.0f}, {WPM_MAXIMO:.0f}]"
        )
        distancia = 0.0 if WPM_MINIMO <= wpm <= WPM_MAXIMO else min(abs(wpm - WPM_MINIMO), abs(wpm - WPM_MAXIMO))
        distancia += 1000.0 if racha >= MUESTRAS_SATURADAS_SEGUIDAS else 0.0  # la saturacion es peor que el ritmo
        # **Cada palabra que falta pesa 100** (F5.9): entre dos intentos con el ritmo en banda, el
        # mejor es el que MÁS dijo. Sin esto, `distancia` valía 0 en los cuatro y `mejor` se quedaba
        # con el primero por orden de llegada, que es el que ya sabíamos que se había comido texto.
        # 100 por palabra queda por debajo de la saturación (1.000), que sigue siendo lo peor: un
        # audio saturado no se arregla oyéndolo entero.
        if informe:
            distancia += 100.0 * max(0, informe.get("pedidas", 0) - informe.get("casadas", 0))
        if mejor is None or distancia < mejor[0]:
            mejor = (distancia, wav, intento, informe, motivo)
        print(f"      segmento {numero}/{total}: {motivo} — se repite con otra semilla", flush=True)
    if base is not None:
        engine._seed = base
    _, wav, intento, informe, motivo = mejor
    informe = {**(informe or {}), "implausible": motivo}
    print(
        f"      [INCIDENCIA] segmento {numero}/{total}: se monta el mejor de {REINTENTOS_MAXIMOS + 1} "
        f"intentos aunque {motivo}",
        flush=True,
    )
    return wav, intento, informe


# Techo del audio que se guarda. Por debajo de 1,0 a proposito: el WAV va en coma flotante y aguanta
# picos mayores, pero el AAC del montaje NO — ahi se recorta y el recorte suena a chasquido.
TECHO_DE_SALIDA = 0.99


def _bajo_el_techo(audio):
    """Baja el volumen del archivo entero si su pico se sale del techo. Devuelve (audio, factor).

    **Medido en el episodio 1 de un canal**: dos laminas se guardaron con picos de **1,063 y 1,092**, y
    ahi habia 25 y 40 muestras por encima de 1,0 — 1 y 1,7 ms. Parece poco y no lo es: un recorte a
    plena escala dura lo que dura un chasquido, que es exactamente lo que se oye.

    **Se escala el archivo entero y no solo el pico** porque recortar la punta deforma la onda —eso
    ES el chasquido— mientras que bajar todo un 7 % conserva la forma y no se nota. La alternativa,
    normalizar cada segmento por su cuenta, haria que el volumen saltase de una frase a otra.

    `racha_saturada` no lo caza y no es su trabajo: mide por SEGMENTO y busca doce muestras seguidas
    al techo, que es la firma de un motor que revienta. Esto es otra cosa — un pico legitimo que no
    cabe— y se resuelve con ganancia, no repitiendo la generacion.
    """
    pico = float(audio.abs().max())
    if pico <= TECHO_DE_SALIDA:
        return audio, 1.0
    factor = TECHO_DE_SALIDA / pico
    return audio * factor, factor


def synthesize(engine, job: dict, item: dict) -> dict:
    """Genera un archivo de audio concatenando sus segmentos EN SERIE."""
    import torch
    import torchaudio

    silence_samples = int(engine.sr * job.get("silencio_entre_frases_ms", 0) / 1000)
    recorte = job.get("recorte_bordes")
    out = Path(item["salida"])
    out.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()

    # **El audio CRUDO se guarda y se reutiliza.** Lo que sale del motor solo depende del texto, la
    # semilla y los parametros; todo lo demas —el aire de las pausas, la limpieza por marcas, el
    # techo— es post-proceso determinista que no necesita GPU. Sin esto, cambiar un umbral obligaba a
    # repetir diez minutos de Chatterbox: el 06-09 se regenero la voz **seis veces** por ajustes que
    # no tocaban el motor, y se noto («veo que estas tardando mucho en hacer cada uno de los
    # procesos»). Con el crudo en disco, esa vuelta baja a segundos.
    # En la RAIZ del run y no bajo `audio/`: `provenance.WORK_DIRS` mira el primer tramo de la
    # ruta, asi que un intermedio colgado de otra carpeta contaria como asset sin procedencia.
    crudo = out.parent.parent / "crudo" / out.name
    # **Y el crudo lleva al lado LO QUE LO GENERO.** Sin esa firma, cambiar el guion y reutilizar el
    # crudo daria el audio del guion viejo con los subtitulos del nuevo: un fallo silencioso y de los
    # peores, porque el video sale entero y suena bien. La firma es el texto de los segmentos mas lo
    # que decide como suena el motor.
    firma = crudo.with_suffix(".json")
    ahora = {
        "segmentos": item["segmentos"],
        "motor": job.get("motor"),
        # **La VOZ y la REFERENCIA entran en la firma desde el 07-09-2026, y faltaban.** El
        # comentario de arriba dice que la firma es «el texto de los segmentos mas lo que decide
        # como suena el motor», y estas dos son exactamente eso: sin ellas, cambiar la voz de un
        # canal o regenerar su clip de referencia y reutilizar un run daba **la voz vieja en
        # silencio**, con el video entero y sonando bien. Es el mismo fallo silencioso que el
        # parrafo de arriba describe para el guion, por la otra puerta. Lo encontro el refactor
        # que paso la referencia a mecanismo del estudio (`scripts/referencia_voz.py`), justo
        # cuando cambiar de voz dejo de ser hipotetico.
        "voz": job.get("voz"),
        "referencia": huella_de_la_referencia(job),
        "parametros": job.get("parametros"),
        "seed": job.get("seed"),
        "silencio_entre_frases_ms": job.get("silencio_entre_frases_ms"),
        "recorte_bordes": recorte,
        # **El crudo se guarda YA recortado**, asi que el recorte forma parte de lo que hay en el
        # fichero y tiene que estar en la firma. Sin esto, cambiar el margen del corte reutilizaria
        # un crudo cortado con el margen viejo y el cambio no se veria por ningun lado.
        "recorte_por_texto": job.get("recorte_por_texto"),
    }
    if crudo.exists() and crudo.stat().st_size > 0 and firma.exists():
        if json.loads(firma.read_text(encoding="utf-8")) == ahora:
            wav_crudo, sr_crudo = torchaudio.load(str(crudo))
            print(f"      {crudo.name}: se reutiliza el audio crudo, solo post-proceso", flush=True)
            return _post_proceso(wav_crudo, sr_crudo, out, job, started, len(item["segmentos"]), [], [], [])
        print(f"      {crudo.name}: el guion o la receta cambiaron, se vuelve a generar", flush=True)

    chunks = []
    reintentos = []
    recortes = []
    incidencias = []
    recortador = _recortador_de(job)
    for numero, segment in enumerate(item["segmentos"], start=1):
        wav, veces, corte = _genera_con_plausibilidad(
            engine, segment, recorte, numero, len(item["segmentos"]), recortador
        )
        if veces:
            reintentos.append({"segmento": numero, "reintentos": veces, "texto": segment[:60]})
        if corte and corte.get("recortado"):
            recortes.append({"segmento": numero, **corte})
        # Lo que antes del 12-09 mataba el run y ahora se monta y se ANOTA: recorte por silencio,
        # sin recorte, o el mejor de varios intentos implausibles. Va a la procedencia y al informe
        # de fin de episodio, que es donde el usuario lo revisa sobre el video montado.
        if corte and (corte.get("respaldo") or corte.get("implausible")):
            incidencias.append(
                {
                    "segmento": numero,
                    "texto": segment[:80],
                    "respaldo": corte.get("respaldo"),
                    "implausible": corte.get("implausible"),
                }
            )
        if chunks and silence_samples:
            chunks.append(torch.zeros(1, silence_samples))  # silencio ENTRE frases, no al final
        chunks.append(wav)
        print(f"      segmento {numero}/{len(item['segmentos'])} listo", flush=True)
    crudo.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(crudo), torch.cat(chunks, dim=-1), engine.sr)
    firma.write_text(json.dumps(ahora, indent=2, ensure_ascii=False), encoding="utf-8")
    return _post_proceso(
        torch.cat(chunks, dim=-1),
        engine.sr,
        out,
        job,
        started,
        len(item["segmentos"]),
        reintentos,
        recortes,
        incidencias,
    )


def _post_proceso(
    audio,
    sr: int,
    out: Path,
    job: dict,
    started: float,
    segmentos: int,
    reintentos: list,
    recortes: list,
    incidencias: list | None = None,
) -> dict:
    """Todo lo que se le hace al audio DESPUES del motor. Determinista y sin GPU.

    Va aparte para que se pueda repetir sobre el crudo sin volver a generar: es la diferencia entre
    diez minutos y unos segundos cuando lo que cambia es un umbral.
    """
    import torchaudio

    # La respiracion se aplica al archivo YA CONCATENADO, no segmento a segmento: una pausa larga del
    # narrador es cola de un trozo + el silencio entre frases + cabeza del siguiente, asi que trozo a
    # trozo no se ve entera.
    audio = limpia_pausas(audio, sr, job.get("respiracion"))
    audio, atenuacion = _bajo_el_techo(audio)
    out.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(out), audio, sr)

    elapsed = round(time.perf_counter() - started, 1)
    audio_seconds = audio.shape[-1] / sr
    return {
        "file": str(out),
        "segmentos": segmentos,
        "reintentos_por_ritmo_implausible": reintentos,
        # Cuanto audio genero el motor de mas y se tiro. Va a la procedencia porque es la
        # medida del coste real de un motor que divaga, y porque un segmento SIN recorte
        # aqui es un segmento que se monto con lo que el motor invento.
        "recortes_por_divagacion": recortes,
        # Segmentos que se montaron con un respaldo o siendo el mejor de varios intentos
        # implausibles. Antes del 12-09 cada uno de estos mataba el run; ahora se monta y se
        # deja aqui para que la revision final lo escuche. Una lista vacia es la normalidad.
        "incidencias_no_bloqueantes": incidencias or [],
        "atenuacion_para_no_recortar": round(atenuacion, 4),
        "seconds": elapsed,
        "audio_seconds": round(audio_seconds, 1),
        "rtf": round(elapsed / audio_seconds, 2) if audio_seconds else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generador de voz local (se ejecuta en .venv-voz)")
    parser.add_argument("--trabajo", required=True, help="JSON con el trabajo preparado por lib/voice_client.py")
    parser.add_argument("--resultado", required=True, help="JSON donde escribir tiempos y VRAM")
    args = parser.parse_args()

    job = json.loads(Path(args.trabajo).read_text(encoding="utf-8"))

    import torch

    engine = load_engine(job)
    result = {
        "motor": engine.nombre,
        "voz": engine.descripcion,
        "dispositivo": job["modelo"].get("device", "cuda"),
        "sample_rate": engine.sr,
        "load_seconds": engine.load_seconds,
        "modo": "en serie",
        "items": [],
    }
    result_path = Path(args.resultado)
    result_path.parent.mkdir(parents=True, exist_ok=True)

    for numero, item in enumerate(job["items"], start=1):
        print(f"  [{numero}/{len(job['items'])}] {Path(item['salida']).name}", flush=True)
        entry = synthesize(engine, job, item)
        result["items"].append(entry)
        print(f"      {entry['seconds']}s para {entry['audio_seconds']}s de audio (rtf {entry['rtf']})", flush=True)
        # Se vuelca en cada vuelta: si el proceso muere, lo ya generado queda contabilizado
        if torch.cuda.is_available():
            result["peak_vram_mb"] = round(torch.cuda.max_memory_reserved() / 1024**2)
        result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
