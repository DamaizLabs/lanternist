"""Motor de escena del estudio (Loop 6, addendum filas 199-201).

Sustituye al montaje de láminas: el vídeo es una composición HTML de HyperFrames que el motor
(`motor/motor.js` y `motor/director.js`) anima como función pura del tiempo, y que Chrome fotografía
fotograma a fotograma.

- `ajustes.py`: el bloque `escena` del perfil del canal (su esquema y cómo se exige, sin defecto).
- `linea_tiempo.py`: de la narración del run a los tiempos del vídeo (láminas, palabras, cues, karaoke, habla).
- `anclas.py`: los tiempos del guion anclados a la narración (`C`, `F`, `P`, `HUECO`, `cues_del_tramo`).
- `escena.py`: el lenguaje con que se escribe un episodio (`Guion`, `Plano`, `Actor`) → el GUION.
- `ayudas.py`: los elementos didácticos (tarjeta, chip, verbo…) por clase, y las piezas que se mecen.
- `encuadre.py`: la geometría del motor en Python y las correcciones de encuadre.
- `comprobaciones.py`: lo que se mira en un GUION antes de renderizarlo.
- `compone.py` escribe la composición (`index.html`) a partir de un GUION, sus assets y el CSS del canal.
- `render.py` la valida (`lint` y la sonda de `motor/sonda.cjs`) y la renderiza con la guarda de red y
  el Chrome con WebGPU.
- `activos.py`: las imágenes con Qwen-Image-Edit (hojas de personaje, lienzos de referencia, posturas, variantes
  y objetos) a través de `lib/comfy_client.py`, con su procedencia.
- `obrero.py` + `obrero_worker.py`: el obrero de activos en `.venv-escena` (Real-ESRGAN, SAM 2.1): recorta cada
  figura con su punto de apoyo, separa piezas, iguala la escala de las cabezas y escribe el catálogo.
- `recorte.py`: el núcleo numérico del obrero, sin GPU (croma, figuras, apoyo, cabeza, borde de una máscara).
- `audio.py`: la narración con sus pausas, el lecho apartado bajo la voz, los efectos y las fuentes de la biblioteca
  del estudio (`datos/escena/`) con su procedencia.
- `episodio.py`: el guion de escena de un episodio (`canales/<id>/datos/escenas/<run>/escena.py`) y su contrato.
- `etapas.py`: las cuatro etapas del pipeline (`alinea`, `activos`, `escena`, `render`) sin el estado del run.
- `revision.py`: las páginas de las dos paradas del usuario y el guion por partes.

Este fichero no importa nada a propósito: el trabajador de `.venv-escena` importa `lib.escena.recorte`, y
cualquier importación aquí se cargaría también allí, donde `lib.config` no carga (le falta `python-dotenv`).

Aquí no vive ninguna decisión de canal (F4.9): lo del canal llega como parámetro.
"""
