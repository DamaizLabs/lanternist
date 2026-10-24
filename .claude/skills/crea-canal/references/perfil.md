# El perfil de un canal, bloque a bloque

Qué lleva `canales/<id>/perfil.json`, quién decide cada valor y quién lo exige. Para la **forma** del JSON, el ejemplo
es el perfil del canal de ejemplo, `canales/example/perfil.json`: declara todo lo que el motor exige y cada valor
lleva su `_por_que`. Para los **valores**, este documento dice de dónde sale cada uno: ninguno se copia de otro canal
sin que el usuario lo decida.

`canal.py --nuevo` escribe solo las decisiones obligatorias (`lib/config.py → DECISIONES_OBLIGATORIAS` e
`INTERRUPTORES`) y el formato. El resto lo añade la skill, bloque a bloque, desde lo que decidió el usuario.

Leyenda de «lo exige»:
- **config**: `lib/config.py`. Si falta, el canal queda en error y **ningún run arranca**.
- **etapa**: la etapa que lo usa para, con un error que dice qué escribir.
- **verificador**: `scripts/verifica_guion.py` da FALLO sin él, y «0 fallos» es la condición de entrega de
  `produce-semana`.
- **skill**: solo lo leen las skills; si falta, el guionista escribe a ciegas.

`scripts/comprueba_canal.py --canal <id>` revisa todo esto de una vez.

## Cabecera

| Clave | Qué | Quién decide |
|---|---|---|
| `id` | El slug del canal (`everyday-inventions`): minúsculas, cifras y guiones sueltos. Es el nombre de su carpeta | mecánico, desde el nombre |
| `nombre` | El nombre del canal en YouTube | el usuario |
| `estado`, `creado` | Texto libre y fecha ISO | mecánico |

## `nicho`

| Clave | Lo exige | Nota |
|---|---|---|
| `id`, `descripcion` | skill | Qué cuenta el canal y para quién. La lee el guionista |
| `fichas_verificadas` **o** `sin_fuentes_verificadas` | verificador (exactamente una de las dos) | Con fichas, el tema necesita su perfil de autoridades, `datos/autoridades/<nicho.id>.json`: qué cuenta como fuente fiable en ese tema. Si el tema vive de cifras, ese perfil lleva el bloque `cifras` (`exige_frase_confirmada`, los mínimos del `mapa` y `redondeo.error_maximo_pct`), sin defecto. Sin fichas, `sin_fuentes_verificadas` dice por qué, como en el canal de ejemplo |
| `personajes`, `molde_de_titulo`, `regla_de_titulo`, `marco_temporal` | skill | Solo si el formato los tiene. En un canal con personajes fijos, son la mitad del formato |

## `formato`

| Clave | Lo exige | Nota |
|---|---|---|
| `duracion_objetivo_min` | verificador | `[mín, máx]` en minutos **de narración**. El usuario. El ejemplo, `[0.75, 1]`, para un episodio de un minuto |
| `laminas_por_video_estimadas` | verificador | Con la duración y el ritmo salen las palabras por lámina. Un valor que no cuadra con los vídeos reales hace que el episodio incumpla la banda sin que nadie lo vea |
| `capitulos` | verificador | true/false |
| `composicion.onda_de_ecualizador` | `lib/onda.py` | **Guardada**: hoy ningún paso del motor de escena la aplica. No se ofrece. Si un canal la declara, completa |
| `bienvenida`, `despedida` | verificador, si se declaran | Opcionales: el usuario decide si su canal las lleva (el de ejemplo, no). Si el perfil las declara, `scripts/verifica_guion.py` las exige en cada guion |
| `estilo_visual`, `contrato_de_prompt` | skill | Qué se ve y dónde está el contrato de prompt del canal. Los lee la skill |

Este bloque no lleva el CTA de suscripción ni las transiciones. El CTA con campana es del motor (`lib/escena/cta.py`),
y dónde y cuándo sale lo pone la capa de escena del canal. Las transiciones que tacha un canal del formato «láminas»
van en `escena.laminas.transiciones_excluidas`.

## `imagen`

| Clave | Lo exige | Nota |
|---|---|---|
| `modelo` | config | El id del workflow del estilo, que se crea en el paso 2b (`workflows/<id>.json`) |
| `seed` | config | La que el usuario elige viendo el avatar y el banner (paso 3), no la de otro canal: lo que dibuja el modelo depende de ella. Hasta entonces, una provisional que lo diga en su `_por_que` |
| `adjetivos_prohibidos` | verificador | Adjetivos de material que el modelo dibuja mal con ESTE estilo. El motor ya trae su lista común; aquí van los del canal. `[]` es una respuesta |
| `fuente_de_la_miniatura` | `scripts/comprueba_canal.py` | La letra del texto de la miniatura, de `datos/escena/fuentes/`, con su licencia. Tiene que leerse reducida a 168 px |
| `miniatura_clausulas` | — | Cláusulas que la miniatura añade al prompt; `[]` si ninguna |
| `acento_de_color` | — (defecto false) | Si la miniatura se recorta al objeto por su color |

## `voz`

| Clave | Lo exige | Nota |
|---|---|---|
| `receta` | config | El nombre del fichero en `canales/<id>/datos/`. El paso 2b escribe solo el nombre, porque sin él no arranca ninguna herramienta; el fichero lo crea el paso 4 |
| `palabras_por_segundo` | verificador | **Se mide**, no se decide: la cata del paso 4, y `produce-semana` lo remide sobre el primer episodio. Lleva `_palabras_por_segundo_por_que` con la medición y de dónde sale |

Ninguna clave de motor: el motor de voz es del motor (`lib/config.py → MOTOR_DE_VOZ`), y las pruebas fallan si un
perfil lo declara.

### La receta de voz (`canales/<id>/datos/voz-orpheus-<id>.json`)

La escribe el paso 4 de la skill, con la voz que elige el usuario. La **estructura** es la de la receta del canal de
ejemplo, `canales/example/datos/voz-example-en.json`; cada **valor** se decide para este canal, dentro de lo que
exige Orpheus (`lib/voice_client.py`):

- `referencia_a_generar`, solo si la referencia es una voz de Kokoro: `componentes` (la voz que eligió el usuario; se
  pueden mezclar dos), `speed`, `lang_code` (a = inglés americano, b = británico, e = español…), `sample_rate_hz` y
  `texto`, con al menos 20 palabras, 25 s de audio y sin `<>`. Lo lee `scripts/referencia_voz.py`.
- `referencia_de_voz`: `variable_entorno` (la variable del `.env` con la ruta del clip, como `RUTA_VOZ_EXAMPLE`),
  `idioma_de_la_referencia`, que es la lengua en que habla el clip, y `clip_entero`, con el texto exacto del clip y su
  duración medida. Con una grabación propia del usuario, este bloque apunta a su grabación y no hay
  `referencia_a_generar`.
- `recorte_por_texto`, en la segmentación: Orpheus lo necesita porque divaga y sigue hablando al acabar la frase.
  Además, `seed`, el resto de la segmentación y los perfiles tonales.
- `etiquetas_emocionales.permitidas`: **solo las medidas**. Lo que Orpheus no reconoce lo lee en voz alta, así que una
  lista vacía con un `<chuckle>` en la bienvenida para el run. `gasp` solo funciona en frase corta.
- El motor que declara la receta tiene que ser el del motor (`orpheus`), o el run se para.

## `idioma`

`narracion` y `subtitulos` (config), en ISO 639-1. El idioma es del canal. La voz clonada habla bien solo en la
lengua de su referencia (`referencia_de_voz.idioma_de_la_referencia`): clonarla en otra lengua inventa sonidos que
nunca oyó. `pipeline.py --check` avisa si no coinciden. Kokoro tiene voces de varios idiomas; las que hay en local las
da `scripts/muestras_voz.py --listar`.

## `subtitulos`

Sin defecto. `activos` (true/false) siempre. Si es true, además las claves de `lib/subtitulos.py → DEL_CANAL`
(`srt`, `fuente`, `cuerpo`, `max_palabras_por_linea`, `margen_inferior_px`, `margen_lateral_px`…). Van también
`personajes`: `{}` si no hay diálogos, o cada personaje con `color` `#RRGGBB` y `pronombre` he/she/they.
`modelo_alineacion` es del motor, y un perfil que lo declara para.

En el motor de escena, el karaoke lo pintan el CSS del canal y `escena.karaoke`, y el `.srt` sale de los cues
(`escena.cues`). La letra, el cuerpo y los márgenes de este bloque son la referencia de ese CSS: el del canal de
ejemplo los cita (`canales/example/escena/estilo.css`).

## `musica`

Sin defecto. `activa` (true/false) siempre. Si es true, además las claves de `lib/musica.py → DEL_CANAL` (la
`escena` del lecho, el volumen, los tramos, el ducking y la semilla). `semilla_base` y `sonoridad_por_tramo` pueden
ser `null`. `workflow`, `objetivo_lufs` y `pico_max_dbtp` son del motor.

## `lineas_rojas`

| Clave | Lo exige | Nota |
|---|---|---|
| `guardianes_de_color` | etapa (después de generar las láminas) | `[]` es una respuesta válida. Cada guardián, con sus campos y `palabras_del_prompt`. Se decide para este tema: un guardián de sangre pensado para otro canal marcó como sangre las orejas de un perro |
| `sin_fuego` | verificador, opcional | Para temas donde «torch» se dibujaría como fuego |
| `resumen`, `si`, `no`, `frontera` | skill | Lo que el canal enseña y lo que no |

## `publicacion`

| Clave | Lo exige | Nota |
|---|---|---|
| `refresh_token_env` | config | El **nombre** de la variable del `.env` con el token de ESTE canal, como `YOUTUBE_REFRESH_TOKEN`. El token solo hace falta para subir por la API (`docs/youtube-upload.md`); a mano no se pide |
| `hecho_para_ninos` | config y `--check` | Booleano, decisión del usuario |
| `categoria_youtube` | config y `--check` | El id como texto (`"27"` Education, `"22"` People & Blogs…). Los válidos, en `lib/youtube_client.py → CATEGORY_NAMES` |
| `canal_id`, `handle`, `canal_youtube` | `canal.py` | Se rellenan cuando el usuario crea el canal (`references/pasos-del-usuario.md`) |
| `eslogan`, `formula_de_titulo` | skill y `canal.py` | |
| `verificado_por_telefono` | `scripts/comprueba_canal.py` | Se anota cuando el usuario lo verifica |
| `afiliacion` | — | `null` salvo que el usuario quiera un enlace de afiliado al pie de cada descripción |

## `ideas`

`minimo_disponibles` y `acepta_externas` (`lib/ideas.py`, sin defecto). El canal de ejemplo lleva 1 y true; para
otro canal lo decide el usuario.

## `escena`

Lo exige `lib/escena/ajustes.py → exige` al crear el episodio de un run de escena. Sin defecto, y para con todo lo
que falta a la vez. Su forma dice el formato: un bloque `laminas` es «láminas», uno `pizarra` es «pizarra», y sin
ninguno es «personajes» (`canal.py --nuevo --formato` lo deja escrito). La lista exacta de claves comunes es
`ajustes.CAMPOS`, con el porqué de cada grupo en su docstring: `fps`, `marco`, `fundido`, `camara_en_mano`, las
magnitudes de `movimiento`, `pausas`, `cues`, `karaoke`, `habla`, `reparto`, `narrador` y `franja_karaoke_y`. Las del
formato: `lib/escena/laminas.py → AJUSTES` y `lib/escena/pizarra.py → AJUSTES`, con su tabla en `docs/formats.md`.
Cuáles se derivan en vez de elegirse (el troceo de `cues`, las palabras del idioma del karaoke, la franja) está en
`biblia-visual.md` §3. El bloque completo del canal de ejemplo es el modelo de forma
(`canales/example/perfil.json → escena`).

## `marca`

`banner`, `avatar`, `marca_de_agua`, `descripcion` y `palabras_clave`, con la forma que lee `canal.py` (el bloque del
canal de ejemplo es el modelo). El banner lleva su `fuente` (de `datos/escena/fuentes/`) y si incluye el eslogan; si
el canal tiene personajes, el banner los enumera uno a uno con su canon. La descripción tiene como mucho 1000
caracteres y las palabras clave 500.
