---
name: instala-lanternist
description: Guía la primera sesión de quien acaba de clonar Lanternist en Windows con una NVIDIA, hasta dejarlo instalado y probado. Comprueba los requisitos, lanza instala.py paso a paso explicando qué baja cada paso y cuánto pesa, resuelve los errores típicos (Python, rutas largas, una descarga cortada, un ComfyUI que ya tenía), y acaba produciendo el episodio del canal de ejemplo de principio a fin como prueba de humo. Nunca pide claves en el chat. Úsala siempre que el usuario diga «acabo de clonar Lanternist», «instálalo», «configura el motor», «primera vez que lo uso», «no me arranca», «instala.py ha fallado», «ya tengo ComfyUI, ¿lo puedo usar?», o pegue un error de instala.py, aunque no nombre la skill. NO la uses para crear su canal (crea-canal), producir episodios (produce-semana) ni mirar un vídeo que quiere imitar (propone-formato).
---

# Instalar Lanternist en la primera sesión

Quien llega acaba de clonar el repositorio y quiere producir vídeos. Tu trabajo es dejarle el motor instalado y
probado, sin sorpresas: que sepa antes de cada paso qué va a bajar, cuánto pesa y cuánto tarda, y que nada se haga en
su PC sin su visto bueno. La instalación la hace `instala.py`; tú la lanzas, la explicas y resuelves lo que falle.

## 1. Los requisitos, antes de nada

Díselos y pregúntale si los cumple. Si no, para: el motor no funcionará, y es mejor saberlo antes de bajar 77 GB.

- **Windows 11 de 64 bits.** Un Mac no funciona, y Linux no está probado.
- **Una NVIDIA con 8 GB de VRAM o más** y su controlador al día. Todo corre en local: las imágenes, la voz, la música y
  el render.
- **32 GB de RAM** y **unos 95 GB libres en un SSD**: 77 GB de pesos y modelos, y el resto para los entornos.
- **Python 3.12, Git, Node.js y ffmpeg.** Si falta alguno, el primer paso lo dice con la orden de `winget` que lo
  instala; instalar programas en su PC lo decide él.
- **Una carpeta corta**, como `C:\lanternist`. Windows no carga una DLL si su ruta pasa de 260 caracteres, y ComfyUI
  tiene rutas muy largas por dentro.

El paso `requisitos` comprueba los programas y la carpeta, pero no mira la VRAM, la RAM ni el disco: eso pregúntaselo.
Y aunque el clon esté en otro disco, las cachés de Hugging Face y de torch (unos 2,5 GB) van siempre a `C:`.

Pregúntale también **si ya tiene ComfyUI o llama.cpp**. Si los tiene, se aprovechan, pero el orden importa:

1. lanza solo `--paso requisitos` y `--paso env`, que crea el `.env`;
2. con su visto bueno, escribe en el `.env` sus rutas: `COMFY_ROOT` (la carpeta que tiene `main.py` y `models\`),
   `LLAMA_SERVER` y `LLAMA_MODELO_GGUF`. Si su ComfyUI es el portable, también `COMFY_PYTHON`, con la ruta de su
   `python_embeded\python.exe`. Las rutas no son claves: puedes escribirlas tú;
3. y solo después sigue con el resto. Si lanza `py -3.12 instala.py` entero antes, el paso `comfyui` monta otro ComfyUI
   en `herramientas\` y `pesos` baja allí los 70 GB.

Con su ComfyUI, el instalador no lo reinstala ni toca lo que tiene, pero:

- le hace falta el nodo **ComfyUI-GGUF** en `custom_nodes\`. Si no lo tiene, el instalador para y dice cuál; lo
  instala él, porque el ComfyUI es suyo;
- **solo se ahorra los ficheros idénticos** a los de la lista fija: mismo nombre, misma subcarpeta de `models\` y
  mismo sha256. Otra cuantización es otro fichero, y lo que falte se baja a su ComfyUI, al lado de lo suyo;
- Lanternist está probado con ComfyUI 0.33.0. Con otra versión no está garantizado: díselo.

## 2. Ver qué falta

```powershell
py -3.12 instala.py --comprueba
```

No instala ni baja nada: dice paso a paso qué está y qué falta, y cuánto queda por bajar. Tarda alrededor de un minuto
si los pesos ya están, porque rehace su sha256; en un disco duro, varios. Enséñale la lista y el plan.

## 3. Instalar, paso a paso

Cada paso mira primero si ya está hecho, así que repetir una orden es seguro y retoma donde se cortó. Lánzalos de uno
en uno con `--paso`, y antes de cada uno dile qué va a pasar. **Lo que baje mucho, según lo que `--comprueba` dijo que
falta, pregúntaselo antes**: en una instalación de cero son sobre todo `entornos`, `pesos` y `voz`.

| Paso | Qué hace | Qué baja | Tiempo, medido en un PC con caché |
|---|---|---|---|
| `requisitos` | Git, Node, npm, ffmpeg, la NVIDIA y la carpeta corta | nada | segundos |
| `env` | el `.env`, desde `.env.example` | nada | segundos |
| `entornos` | `.venv`, `.venv-voz` y `.venv-escena`, con Python 3.12 | unos 10 GB de paquetes, con torch para CUDA | ~5 min |
| `comfyui` | ComfyUI y su nodo GGUF, en `herramientas/`, si no tenía uno | torch y 87 paquetes | ~2 min |
| `pesos` | los modelos de imagen, música y ampliación, en la carpeta de ComfyUI | **69,6 GB** | según su conexión |
| `voz` | llama.cpp, Orpheus, Kokoro y el alineador | 5,6 GB | según su conexión |
| `escena` | HyperFrames, los efectos de sonido, el Chrome con WebGPU y SAM | 1,1 GB | ~1 min |
| `marca` | los modelos de la marca de IA (Video Seal, AudioSeal y la señal TrustMark) | 0,4 GB | segundos |
| `voz-del-canal` | el clip de voz del canal de ejemplo, con Kokoro en la GPU | nada | ~20 s |
| `comprueba` | `pipeline.py --check` | nada | ~10 s |

```powershell
py -3.12 instala.py --paso <paso>     # uno solo: lo de serie en la primera sesión
py -3.12 instala.py                   # todos los que falten, en orden y sin parar a preguntar
```

Las descargas largas, lánzalas en segundo plano y avísale de cuánto queda. Si se corta la red, repetir la orden la
retoma: cada fichero se baja a un `.part`, y al acabar se comprueba su sha256 contra una lista fija
(`datos/descargas.json`). Lo que no cuadra se borra y no se usa.

## 4. Si algo falla

Cada error para el paso y dice qué hacer. Los típicos:

| Lo que dice | Qué hacer |
|---|---|
| `Lanternist usa Python 3.12, y esto es …` | `winget install -e --id Python.Python.3.12`, y otra vez `py -3.12 instala.py` |
| `falta algo del sistema…` | la orden de `winget` que da, y repetir |
| `…demasiado larga: Windows no carga una DLL…` | mover la carpeta a una ruta corta, como `C:\lanternist`. Encender las rutas largas no lo arregla: Windows no carga una DLL de más de 259 caracteres ni con ellas |
| `…rutas largas de Windows están apagadas…` | mover la carpeta a una ruta corta, o encender las rutas largas en una PowerShell de administrador (la orden va en el mensaje) |
| `la descarga de X se cortó…` | repetir: retoma |
| `X ha llegado con otro sha256…` | se borró; si se repite, la fuente cambió y no se usa |
| `estos ficheros ya están, pero no son los comprobados…` | hay un fichero ajeno con el mismo nombre: moverlo, o apuntar el `.env` a otra carpeta |
| `COMFY_ROOT=… no es un ComfyUI`, `…no tiene el nodo ComfyUI-GGUF`, `LLAMA_SERVER=… no existe` | una ruta de su `.env`: corregirla o borrarla para que se instale en `herramientas/` |
| `CHROME_WEBGPU_MANIFIESTO=… no es un Chrome con WebGPU completo` | una ruta de su `.env` a un Chrome a medias: borrar la línea y repetir `--paso escena`, que lo instala entero |
| `… ya existe y es de Python 3.x, y Lanternist lo crea con Python 3.12` | un entorno que no creó el instalador: que lo borre o lo renombre él, y repetir `--paso entornos` |
| `pip en .venv-… falló (código N)` | la causa está en la salida de pip, justo encima |

No arregles a mano lo que hace el instalador (copiar DLL, tocar entornos): si un paso falla de una forma que no está
aquí, enséñale el mensaje y propón qué mirar.

## 5. Las claves de YouTube, solo si las quiere

Para producir no hace falta ninguna: por defecto cada vídeo queda listo para subirlo a mano en YouTube Studio. Si
quiere que el motor suba solo, con `YOUTUBE_SUBIDA_API=1` en el `.env`, cada vídeo llega como **borrador privado**:
el motor nunca publica, lo publica él en Studio. Hacen falta tres valores de su propio proyecto de Google Cloud (el
Client ID, el Client secret y el *refresh token* de su canal), y cómo sacarlos está en `docs/youtube-upload.md`. Los
escribe él mismo:

```powershell
py -3.12 instala.py --claves
```

**Las claves no pasan nunca por el chat.** La orden las pide sin eco en su terminal y las guarda en su `.env`; tú no
puedes lanzarla por él, porque necesita un terminal suyo. Si pega una clave en la conversación, dile que la dé por
expuesta y la cambie en Google Cloud.

## 6. La prueba de humo: el episodio de ejemplo de principio a fin

Con `pipeline.py --check` en «Listo para producir.», propónle producir el episodio del canal de ejemplo, «How Does a
Zip Work?», y lánzalo cuando diga que sí: son unos 15 minutos, casi todos de GPU. Viaja con el repositorio su guion,
ya escrito (`slides.json`), y su guion de escena (`escena.py`). Las láminas se vuelven a generar a propósito, porque
así se prueba la GPU de imagen: tienen que salir iguales a las que viajan en `slides/`.

```powershell
.venv\Scripts\python pipeline.py --canal example --create --title "How Does a Zip Work?"
$run = '<el run_id que imprime --create>'
$ejemplo = '2026-10-15_115251_how-does-a-zip-work'
Copy-Item canales\example\videos\$ejemplo\slides.json canales\example\videos\$run\slides.json
New-Item -ItemType Directory -Force canales\example\datos\escenas\$run | Out-Null
Copy-Item canales\example\datos\escenas\$ejemplo\escena.py canales\example\datos\escenas\$run\escena.py
```

Las etapas de GPU se lanzan una a una, como proceso aparte, porque la tarjeta de 8 GB no se reparte:

```powershell
New-Item -ItemType Directory -Force logs | Out-Null
# una etapa del run de ejemplo (canales/example/videos/$run/); para las siguientes cambia los argumentos y el log
$p = Start-Process -FilePath .venv\Scripts\python.exe -ArgumentList "pipeline.py --canal example --run-id $run --run-all" -PassThru -WindowStyle Hidden -RedirectStandardOutput logs\humo-1.log -RedirectStandardError logs\humo-1.err; $p.WaitForExit()
```

1. **`--run-all`** hace las láminas, la voz, la alineación y los activos, y para en la **parada 1** (~8 min). Ábrele
   `revision\activos.html` del run: en «láminas» son las tres láminas ampliadas. Las paradas son suyas: sigue cuando
   lo diga.
2. **`--stage escena`** compone el episodio y su música, y para en la **parada 2** (~1 min). Ábrele
   `revision\fotogramas.html`.
3. **`--stage render`** hace el vídeo (~2 min): `subir-al-canal\final.mp4`, con la marca de IA.
4. **`--run-all`** otra vez hace la miniatura y `subir-al-canal\LEEME.html`, con los pasos para subirlo a mano. Dura
   segundos.

El resultado se lee en el log de cada etapa (`[PARADA n]`, `Done` o `COMPLETE`). Al final, comprueba la marca y ábrele
el vídeo:

```powershell
.venv\Scripts\python scripts\detecta_marca.py canales\example\videos\$run\subir-al-canal\final.mp4
```

Tiene que decir **MARKED**. Con eso, Lanternist está instalado y funciona en su PC.

## 7. Y después

El siguiente paso es su canal: la skill `crea-canal`. Si tiene delante un vídeo cuyo estilo quiere, puede pegar su
enlace y `propone-formato` le dice qué formato del catálogo (`docs/formats.md`) se le parece.
