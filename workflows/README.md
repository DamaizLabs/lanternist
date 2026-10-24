# Workflows de imagen (ComfyUI local)

Un archivo JSON por **modelo × estilo**, versionado en git y parametrizado. Los ejecuta
`lib/comfy_client.py`, el adaptador de imagen del pipeline (F2.1). Cada workflow lleva el estilo
del canal que lo usa, firmado en su gate 0: tinta, plano o pizarra.

## Runtime

| Pieza | Valor verificado el 24-08-2026 | Notas |
|---|---|---|
| Instalación | `COMFY_ROOT` del `.env` (puede ser **compartida** con otros proyectos) | El adaptador arranca el servidor **solo si no está vivo** y lo apaga **solo si lo arrancó él** |
| Versión | ComfyUI **0.33.0**, commit `de6b062fb5ed1c9b471a3ebcd614705d93d67560` | `comfyui_version.py` + `git log` de esa carpeta |
| Endpoint | `http://127.0.0.1:8188` | `COMFY_HOST`/`COMFY_PORT` del `.env`; nunca una URL remota |
| Python del servidor | `<COMFY_ROOT>\.venv\Scripts\python.exe`, 3.12.10, torch 2.13.0+cu130 | Es el venv de ComfyUI, **no** el `.venv` del repo |
| GPU | RTX 3060 Ti, 8 GB, `DynamicVRAM` + `comfy-aimdo` 0.4.13 activos | Los lotes se generan **en serie**; `batch_size` distinto de 1 aborta el lote |

## Lista blanca de nodos

`ALLOWED_NODES` en `lib/comfy_client.py` es la lista blanca efectiva: cualquier
`class_type` fuera de ella aborta el lote antes de tocar la red. Contiene solo nodos base
de ComfyUI 0.33.0 y los de **un** paquete de terceros:

| Paquete de terceros | Commit fijado | Nodos usados | Para qué |
|---|---|---|---|
| [`city96/ComfyUI-GGUF`](https://github.com/city96/ComfyUI-GGUF) | `6ea2651e7df66d7585f6ffee804b20e92fb38b8a` (2026-01-12) | `UnetLoaderGGUF` | Cargar los UNet cuantizados en GGUF (Qwen-Image) que caben en 8 GB |

Es el **único** paquete de `custom_nodes/` de esa instalación. Añadir un nodo a la lista
blanca es una decisión consciente: se audita el paquete, se anota su commit en esta tabla
y se justifica en el informe de la feature que lo necesita.

**La lista lleva solo lo que se usa.** El 01-10-2026 salieron 14 nodos que solo pedían los workflows
retirados de Flux, Flux 2, Ideogram y SDXL (fila 223), y 4 más con `wan-i2v-lamina` (fila 226). Un nodo nuevo entra cuando un workflow vivo lo
necesita, y sale cuando sale el último workflow que lo usaba.

### Prohibido: los *API nodes* de pago

El servidor registra ~863 clases de nodo, entre ellas las de `comfy_api_nodes`
(ByteDance, Minimax/Hailuo, Krea, Luma, Vidu, Grok, Ideogram Cloud…). Son **servicios de
pago que envían el prompt fuera del PC** y violan las decisiones cerradas 4 (nada de
pago) y 6 (nada sale del PC). Que ComfyUI las traiga de fábrica no las hace locales: la
lista blanca las rechaza y ninguna de ellas puede entrar.

## Formato de un workflow

```jsonc
{
  "id": "qwen-2512-lightning-tinta",    // = nombre del archivo, y valor válido de MODELO_IMAGEN
  "estilo": "tinta",                    // estilo firmado en el gate 0
  "nota": "...",                        // contexto para quien lo lea dentro de seis meses
  "modelo": {
    "nombre": "Qwen-Image-2512 GGUF Q6_K + LoRA Lightning 8 pasos",  // va al registro de procedencia (assets.json, F2.4)
    "pesos": ["unet/...", "vae/..."],   // rutas relativas a <COMFY_ROOT>\models
    "licencia": "...",                  // condición previa del addendum fila 6
    "local": true
  },
  "prefijo_estilo": "pen and ink ...",  // lo antepone el adaptador al prompt de la escena
  "parametros": { "steps": 8, "cfg": 1.0, "shift": 3.0, "prompt_negativo": "..." },
  "inyeccion": {                        // parámetro lógico -> "<id_nodo>:<input>"
    "prompt": "4:text",
    "seed": "8:seed",
    "width": ["7:width", "8:width"],    // una lista si el mismo valor va a varios nodos
    "height": "6:height"
  },
  "nodo_salida": "10",                  // el SaveImage: el adaptador le inyecta el prefijo
  "grafo": { "1": { "class_type": "...", "inputs": { ... } } }   // formato API de ComfyUI
}
```

`inyeccion` es lo que mantiene estable el contrato del adaptador: el pipeline pide
«prompt, tamaño y seed» y cada workflow declara dónde van, así que **el pipeline no
conoce modelos** (decisión cerrada 10). Un parámetro sin punto de inyección declarado
simplemente se ignora.

## Modelos de imagen

`MODELO_IMAGEN` (`perfil.json → imagen.modelo`) solo resuelve los workflows de esta carpeta. El 01-10-2026
salieron del repositorio los que ningún canal usaba (filas 221, 223 y 226): los dos de Z-Image, los tres que el
zoo-test del 24-08 no eligió (`flux-schnell-tinta`, `sdxl-tinta` e `ideogram4-tinta`), que vivían en
`workflows/archivo/`, y `qwen-lightning-tinta` y `wan-i2v-lamina`. El registro de aquel zoo-test, con sus tiempos y veredictos, sigue en
`progress/impl_F2.1.md`. Un workflow retirado se borra, no se archiva: el manifiesto (A-24) falla si
`workflows/archivo/` vuelve a existir.

Inventario comprobado contra `<COMFY_ROOT>\models` el 01-10-2026: todos los pesos de esta tabla están.

| Workflow | Lo usa | Pesos | Licencia |
|---|---|---|---|
| `qwen-2512-lightning-tinta` | el formato «láminas» en tinta | `qwen-image-2512-Q6_K.gguf` + LoRA `Qwen-Image-Lightning-8steps` + `qwen_2.5_vl_7b_fp8_scaled` + `qwen_image_vae` | **Apache-2.0**, uso comercial permitido |
| `qwen-lightning-plano` | ilustración plana y cálida | `qwen-image-Q6_K.gguf` + LoRA `Qwen-Image-Lightning-8steps` + `qwen_2.5_vl_7b_fp8_scaled` + `qwen_image_vae` | **Apache-2.0**, uso comercial permitido |
| `qwen-2512-lightning-pizarra` | el formato «pizarra» | los mismos que `qwen-2512-lightning-tinta` | **Apache-2.0**, uso comercial permitido |
| `qwen-edit-tinta` | la edición por instrucción de piezas que el modelo no conoce (fila 147) | `qwen-image-edit-2511-Q6_K.gguf` + LoRA + `qwen_2.5_vl_7b_fp8_scaled` + `qwen_image_vae` | **Apache-2.0**, uso comercial permitido |
| `qwen-edit-lienzo` | el motor de escena (`lib/escena/activos.py`) | los mismos que `qwen-edit-tinta` | **Apache-2.0**, uso comercial permitido |

### Pesos de la instalación que no usa ningún workflow

**Solo Ideogram 4** (28 GB): `ideogram4_int8_convrot`, `ideogram4_unconditional_int8_convrot`,
`qwen3vl_8b_fp8_scaled` y `flux2-vae`. Se quedan por decisión del 01-10 (fila 226). El 01-10-2026 se borraron los de Z-Image, lo que quedaba de Flux, los de
Wan 2.2 (TI2V 5B y Fun 5B) y `RealESRGAN_x4plus`: 26,72 GB en `C:`.

## Audio: el lecho musical (F2.12)

| Workflow | Pesos | Licencia |
|---|---|---|
| `ace-step-lecho` | `checkpoints/ace_step_v1_3.5b.safetensors` (7,17 GiB) | **Apache-2.0**, uso comercial permitido |

**La licencia está verificada, no recordada**: consultada el 24-08-2026 contra la API de
HuggingFace (`api/models/Comfy-Org/ACE-Step_ComfyUI_repackaged`, campo `cardData.license`).
El repo oficial `ACE-Step/ACE-Step-v1-3.5B` declara la misma.

**Descargado por el agente** a la instalación compartida `<COMFY_ROOT>\models\checkpoints\`
con luz verde explícita («aplica las descargas que necesites», 24-08). Es el único
peso que este proyecto ha añadido a esa instalación.

### Por qué se genera la música y no se descarga

Se propuso música Creative Commons de biblioteca. Se descartó por una razón que pesa más
que la calidad: **CC no protege de Content ID**. Muchas pistas CC están registradas por
distribuidoras, y un reclamo de Content ID es **parada total del sistema** por precedencia de
paradas (`CLAUDE.md`). La música generada en local es original: no hay nada que reclamar. De
paso, CC-BY habría obligado a atribución en cada descripción.

### Siete nodos nuevos en la lista blanca

`TextEncodeAceStepAudio`, `EmptyAceStepLatentAudio`, `ModelSamplingSD3`,
`LatentOperationTonemapReinhard`, `LatentApplyOperationCFG`, `VAEDecodeAudio`, `SaveAudioMP3`.

Los siete son de **ComfyUI core** (`comfy_extras`), auditados uno a uno contra la plantilla
oficial `audio_ace_step_1_t2a_instrumentals.json` de la instalación. **Ninguno es API node de
pago**, que es lo que la lista blanca existe para impedir.

### Rendimiento medido

**45 s de música en 22 s de GPU** (50 pasos, 3,5B). Para un vídeo de 18 minutos son unos 9
minutos de generación, encadenando tramos con solape — un lecho corto en bucle se delata.

## Edición por instrucción para el motor de escena: `qwen-edit-lienzo` (F6.2c)

| Workflow | Pesos | Licencia |
|---|---|---|
| `qwen-edit-lienzo` | `qwen-image-edit-2511-Q6_K.gguf` + LoRA `Qwen-Image-Lightning-8steps` + `qwen_2.5_vl_7b_fp8_scaled` + `qwen_image_vae` | **Apache-2.0**, uso comercial permitido (la misma fila que `qwen-edit-tinta`) |

Con él genera `lib/escena/activos.py` las hojas de personaje, las posturas, sus variantes y los objetos. Es
**hermano de `qwen-edit-tinta`** y tiene los mismos nodos (ninguno nuevo en la lista blanca), con **una
diferencia que es la razón de que exista**:

- En `qwen-edit-tinta`, el latente de partida sale de la **propia referencia**: `VAEEncode` cuelga de la misma
  `LoadImage` (nodo 5). Así la salida tiene siempre el tamaño y el encuadre de la referencia.
- En `qwen-edit-lienzo`, el latente sale de un **lienzo aparte** (nodo 20, punto de inyección `lienzo`) y la
  referencia solo condiciona la instrucción (nodo 5, `referencia`). Una hoja de personaje se pide sobre un lienzo
  de croma liso de 1664×928 con una lámina del canal de referencia, y eso con el de tinta no se puede.

Cuando la referencia ES el lienzo (una postura sobre su lienzo de referencia, una variante en su sitio, un objeto
en una hoja), `activos.py` inyecta el mismo nombre en los dos. Es el grafo `grafo_edita` con que video_1 generó sus
124 imágenes, y lo reproduce: la hoja pedida con su mismo estilo, descripción y semilla sale **idéntica** a la de
video_1 (`experimentos/motor-escena/f62c-qwen/qwen.json → hoja_frente_a_video_1.dif_media = 0.0`).

- **Sin `prefijo_estilo`**: el estilo es del canal y va dentro de la instrucción (`activos.Estilo`).
- **`modelo.url`** es un campo nuevo: la página del modelo, que pasa al registro de procedencia de cada imagen
  (decisión 5: fuente, licencia y URL). Desde F6.2d lleva las tres de lo que se ejecuta, unidas con « · »: el modelo
  base, el GGUF Q6_K (`unsloth/Qwen-Image-Edit-2511-GGUF`) y el LoRA Lightning (`lightx2v/Qwen-Image-Lightning`).
  La del LoRA sale del nombre de su fichero y no se comprobó contra la red (decisión 6): lo dice `modelo.url_nota`.
- **La referencia y el lienzo se suben** a `input/lanternist/` de ComfyUI por su propia API
  (`comfy_client.sube_imagen`) y se borran al acabar el lote (`borra_subidas`), también si algo falla: la
  instalación compartida queda como estaba (medido en `experimentos/motor-escena/f62c-comfy/cambios.json`).
- **Tiempo medido**: una hoja de 1664×928, 145,7 s; una postura de 704×960, 102,9 s, las dos con el modelo ya
  cargado o cargándose en la misma sesión (`experimentos/motor-escena/f62c-qwen/qwen.json → qwen_segundos`).
