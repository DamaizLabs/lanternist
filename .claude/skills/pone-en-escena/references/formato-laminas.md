# El formato «láminas»: la lámina entera con cámara

Cómo se pone en escena un episodio de un canal cuyo perfil declara `escena.laminas`, como el canal de ejemplo
(Lantern Slides). Qué es el formato y qué se configura está en el catálogo, `docs/formats.md → laminas`. El ejemplo
resuelto es su episodio «How Does a Zip Work?», con tres láminas y 54 s:
`canales/example/datos/escenas/2026-10-15_115251_how-does-a-zip-work/escena.py`.

## Contenido

1. Qué es y qué no es
2. Qué pasos del flujo cambian
3. El guion de un episodio
4. Lo que ajusta el perfil
5. El CTA y los rótulos, si la capa del canal los tiene
6. Revisión antes de la parada 2

## 1. Qué es y qué no es

- **Cada lámina del run sale a pantalla completa**, y la cámara la recorre sin enseñar nunca su borde.
- **`lib/escena/laminas.py` parte cada lámina en tomas** de unos `toma_s` segundos. Cada toma lleva uno de los 13
  movimientos de su catálogo (`MOVIMIENTOS`: acercamientos, barridos, un descenso, alejamientos…) y entra con una
  transición: suave entre dos tomas de la misma lámina, de tinta entre dos láminas.
- **Encima va el karaoke de una línea.** Si la capa del canal los tiene, también van el nombre del canal y el título
  del episodio escritos a tinta, y el CTA sobre la última lámina (§5). El canal de ejemplo no los tiene.
- **Nada de la lámina se mueve por piezas, y no hay figuras.** Animar piezas de una lámina a tinta se probó y se
  descartó: el dibujo en perspectiva se deforma, y el hueco se ve aunque se rellene (`imagenes.md` §6). Si el usuario
  lo pide, explícale esto antes de intentarlo.
- **El montaje sale de dos claves de texto**: el título del vídeo (`slides.json → title`) y la descripción de cada
  lámina (`image_prompt`). Las mismas claves dan siempre el mismo montaje. Cambiar el título después de la parada 2
  cambia todos los planos, así que `render` se niega: la composición ya no es la que vio el usuario. Si el título
  cambia, se recompone y se le enseña la hoja otra vez.

## 2. Qué pasos del flujo cambian

| Paso del flujo de `SKILL.md` | En este formato |
|---|---|
| 0. Situarse | Igual: `images`, `tts` y `alinea` hechas. Con un solo narrador no hace falta `hablantes` |
| 1. El plan | No hay `plan.md`: el reparto de tomas es determinista y no se decide nada lámina a lámina |
| 2. Imágenes y parada 1 | Ninguna imagen nueva. `activos(ep)` amplía cada lámina ×2 con Real-ESRGAN (`obrero.fondo(..., del_episodio=True)`) para que la cámara se acerque sin perder trazo. Las ampliaciones son del episodio y no entran en la biblioteca del canal, porque no sirven a otro episodio. Si la capa del canal tiene CTA, de la biblioteca llegan su banner y su campana (§5). La parada 1 se pasa igual: se le dice al usuario que todo sale de las láminas del run y, si acaso, de la biblioteca |
| 3. En seco | Igual, con `scripts/en_seco.py`. El episodio de ejemplo da 6 planos, 0 actores y 0 defectos. Cuenta «0 transiciones» porque las de tinta son entradas de plano, no `g.transicion`. No hay rejilla que medir: nada toca nada |
| 4. Etapa `escena` | Los `MOMENTOS` los saca el guion (`_momentos` del ejemplo): los dos negros, el centro de la primera toma de cada lámina y la mitad de la primera vez que sale cada transición. Si la capa pone rótulos o CTA, añade un momento para cada uno |
| 5 a 7. Parada 2, render y correcciones | Igual. El episodio de ejemplo, de 54,5 s, se renderizó en 94,6 s; uno de 17 min con 102 planos tardó 21 min. Cada run deja su medida en `<run>/montaje.json → cronometraje` |
| 8. Cierre | Nada nuevo entra en la biblioteca ni en la capa del canal |

## 3. El guion de un episodio

El `escena.py` del ejemplo se copia a la carpeta del episodio nuevo (`canales/<id>/datos/escenas/<run>/escena.py`). En
un canal como el de ejemplo no hay que cambiar nada: todo sale del `slides.json`, del perfil y de la capa del canal.

Lo que hace `construye`, en orden:

1. registra un set por lámina, con el nombre de su imagen ampliada (`lamina_01`, `lamina_02`…);
2. `laminas.ajustes(ep.escena)` lee el bloque `escena.laminas` del perfil, y para si le falta algo;
3. `laminas.planifica(laminas.laminas_del_episodio(linea, slides), clave_del_video=titulo, fps=linea.fps,
   ajustes_=a)` reparte las tomas;
4. `laminas.pon_en_escena(g, tomas, sets, ajustes_=a)` escribe un plano por toma, con su entrada y su cámara;
5. pone el negro del principio y el del final como dos elementos de pantalla (la clase `negro` del CSS del canal): el
   primero se abre durante la pausa de entrada (`escena.pausas.intro_s`) y el último cae durante la cola
   (`escena.pausas.cola_s`), así que la última palabra se oye con la lámina todavía a la vista.

Si la capa del canal tiene rótulos, sus anclas sí cambian de un episodio a otro:

| Qué | Cómo se elige en cada episodio |
|---|---|
| El nombre del canal | desde el principio hasta poco antes del cue en que el relato empieza tras la bienvenida. Míralo en el guion por partes |
| El título del episodio | cuando el narrador nombra el tema, anclado a la palabra que lo nombra: `P(9, "zip") - 0.2` en el episodio de ejemplo («The zip turned…») |
| Los momentos de los rótulos | sácalos de las mismas anclas (`P(9, "zip") + 1.5`), no los escribas en segundos: así se recolocan si cambia la voz |

Si el título del vídeo lleva dos puntos, lo habitual es partirlo ahí: el tema en el rótulo grande y el resto en un
subtítulo.

## 4. Lo que ajusta el perfil: `escena.laminas`

Siete claves, ninguna con valor por defecto. `laminas.ajustes` para y dice qué escribir si falta una. Los valores del
canal de ejemplo están en `canales/example/perfil.json → escena.laminas`, y qué es cada clave, en
`lib/escena/laminas.py → AJUSTES`:

| Clave | Canal de ejemplo | Qué es |
|---|---|---|
| `zoom_base` | 1,06 | el zoom mínimo; mayor que 1 para dejar fuera de cuadro el margen de la propia lámina |
| `zoom_maximo` | 1,45 | el techo del zoom |
| `toma_s` | 10 | lo que dura una toma, en segundos |
| `toma_minima_s` | 5 | lo que dura como mínimo |
| `transicion_s` | 2,0 | lo que dura una transición |
| `transiciones_excluidas` | `["plate_reveal"]` | las del catálogo que el canal tacha, con los nombres de `laminas.TRANSICIONES` |
| `fuentes_de_los_rotulos` | Gelasio, redonda y cursiva | las fuentes de los rótulos a tinta, de `datos/escena/fuentes/`, cada una con su licencia |

Además, `escena.camara_en_mano` vale 0: el temblor acercaría el borde de la lámina al cuadro. Estas claves son
identidad del canal: cambiar una cambia todos sus episodios al recomponerlos, así que lo decide el usuario.

Las transiciones del catálogo, con los nombres que usa el perfil, y su entrada de plano (`laminas.TRANSICIONES`; la
sintaxis, en `lenguaje.md` §3):

| Nombre en el perfil | Entrada de plano |
|---|---|
| `dissolve` | `funde` |
| `ink_bleed` | `calado` |
| `ink_wipe_right`, `ink_wipe_left`, `ink_wipe_up` | `cortina`, con `dir` `derecha`, `izquierda` o `arriba` |
| `ink_streak_right`, `ink_streak_left` | `viento`, con `dir` `derecha` o `izquierda` |
| `ink_blot` | `mancha` |
| `paper_flash` | `papel` |
| `plate_reveal` | `barrido` con `dir=-1`. Es la única aproximada, y el canal de ejemplo la tacha |

Las curvas de cada movimiento se traducen así: `ease_in` pasa a `acelera`, `ease_out` a `frena`, `ease_in_out` a
`suave` y `linear` a `lineal`.

## 5. El CTA y los rótulos, si la capa del canal los tiene

El canal de ejemplo no los tiene: son decisiones de identidad que todavía no ha tomado. Un canal que los quiera los
añade en su capa (por ejemplo, en un `apertura.py` y un `cierre.py`), sobre dos mecanismos del motor. Añadirlos es
decisión del usuario.

- **El CTA**, `lib/escena/cta.py → pon`. El banner entra con un rebote y late. Su campana es una imagen aparte que se
  balancea, y suena la notificación cada 4,5 s desde que el narrador dice «bell». Un clic suena cuando dice
  «subscribe». Las dos palabras salen de la despedida, que es una plantilla del canal
  (`perfil.json → formato.despedida`): si la plantilla cambia, cambian las anclas.
  - El banner y la campana van en la biblioteca del canal (`cta_banner` y `cta_campana`, en
    `canales/<id>/escena/biblioteca/`), con su procedencia y su sha256.
  - El guion los pide en `activos(ep)` con `Lote.biblioteca`, y la etapa `activos` los copia al run con su registro
    para `assets.json` (`lib/escena/biblia.py → trae`).
  - Si el guion no los pide, `--stage escena` para con el nombre de la imagen que falta. En seco no se ve, porque
    `en_seco.py` junta la biblioteca y el run: pásalo con `--catalogo run` después de la etapa `activos`.
- **Los rótulos a tinta**, `lib/escena/tinta.py`: el trazo recorre el contorno de cada letra y la letra se rellena
  después.
  - Las fuentes son las de `escena.laminas.fuentes_de_los_rotulos`, de la biblioteca del motor
    (`datos/escena/fuentes/`). El CSS del canal tiene que declararlas con `@font-face`: así entran en el run y en
    `assets.json` con su licencia, y si falta la declaración el guion para (`tinta.fuente_de_la_biblioteca`). Los
    tamaños, la cadencia y el color son de la capa del canal.
  - Una letra que la fuente no tiene para el guion con su nombre.
  - Un rótulo que no acaba de escribirse antes de irse no se acorta, porque es el título del vídeo que el usuario
    aprobó con el guion: se le da más tiempo moviendo su final. Haz que la capa pare en ese caso, en vez de dejarlo a
    medias.

## 6. Revisión antes de la parada 2

`comprobaciones.json` casi no tiene qué medir en este formato, porque no hay actores. En los fotogramas, mira:

- **La cámara nunca enseña el borde de la lámina**, tampoco debajo de una transición: la hoja enseña la mitad de la
  primera vez que sale cada una.
- **Cada transición de tinta se ve entera**, sin un corte a medias.
- **El negro del principio se abre** con la voz, y el del final cae después de la última palabra.
- **Los rótulos, si los hay, se escriben enteros** y se quedan quietos antes de irse, sin pisar la franja del karaoke.
- **El CTA, si lo hay**: el banner entra sobre la última lámina, donde lo pone la capa, sin tapar lo que la voz
  explica, y la campana se balancea cuando el narrador dice «bell».
- **La declaración de IA** la pone sola la subida: con 0 actores dice «Still illustrations: AI-generated, shown with
  camera movement» (`lib/publicacion.py`). No hay que hacer nada.
