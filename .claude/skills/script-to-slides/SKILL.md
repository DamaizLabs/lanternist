---
name: script-to-slides
description: Convierte el guion de un episodio en el slides.json que consume pipeline.py, que es lo que el usuario lee y aprueba en el gate del guion antes de gastar GPU, en el IDIOMA DE SU CANAL y con la estructura narrativa faceless que retiene (gancho, bloques con giro, cierre). Un slide es UNA LÁMINA, y lo constante es cuánta narración lleva cada una —la banda que scripts/verifica_guion.py deriva del perfil.json del canal—, no cuántas hay. El ritmo visual lo da la cámara sobre la lámina en el formato «láminas», y en «personajes» y «pizarra», los dos en preparación, la puesta en escena o las piezas que aparecen. Escribe también los capítulos como frases SEO, la miniatura (una lámina del vídeo), las fuentes y los títulos traducidos. Úsala siempre que haya un guion que pasar a slides.json, o haya que partir, contar o retocar las láminas de un guion, aunque no nombre la skill. NO la uses para escribir ni reescribir el guion, para el guion de escena (pone-en-escena) ni para la semana entera (produce-semana, que la llama).
---

# Guion → slides.json

Conviertes un guion de narración en el `slides.json` que consume `pipeline.py`. Quien usa el motor aprueba el guion
en el gate del guion (el gate 1) **leyendo este `slides.json`**, en la página de `scripts/gate1_pagina.py`, antes de
gastar GPU en él. Tú no escribes ni reescribes el guion: lo partes en láminas. Y una vez aprobado, no se cambia una
palabra sin volver a pasar por su gate.

El ejemplo de referencia es el canal `example`, en el formato «láminas», con su episodio «How Does a Zip Work?»:
`canales/example/videos/2026-10-15_115251_how-does-a-zip-work/slides.json`.

## Lo primero: de dónde salen el idioma y el estilo

**Esta skill no tiene idioma por defecto.** Todo sale del canal activo (`CANAL_ACTIVO` en el `.env`):

- **El idioma de la narración**: `canales/<id>/perfil.json → idioma.narracion`, que `lib/config.py` expone como
  `NARRATION_LANG` (el `.env` puede anularlo con `IDIOMA_NARRACION`). El canal `example` narra en inglés.
- **El estilo visual**: `perfil.json → formato.estilo_visual`.
- **El contrato de prompt de imagen del canal** (el fichero que nombra `perfil.json → formato.contrato_de_prompt`,
  en `canales/<id>/`) manda sobre cualquier regla de estilo de esta skill. El del canal `example`, por ejemplo,
  pide describir un mecanismo por lo que se ve y no por su nombre: «its channel shaped like a Y» dibujó una pieza
  de metal en forma de Y, no el interior del cursor.
- **Las líneas rojas** (`perfil.json → lineas_rojas`) no son un consejo de estilo. Las del canal `example`: ni
  personas reconocibles, ni marcas, ni texto legible. Un prompt que las cruce lo para `lib/lineas_rojas.py`
  después, pero no debe llegar hasta ahí.

Si el guion viene en un idioma distinto al del perfil, **para y dilo**: puede ser un guion equivocado o un canal mal
configurado, y las dos cosas se arreglan antes de producir, no después.

## La estructura narrativa

Es la estructura de los vídeos faceless que retienen, no una preferencia estética. Comprueba que el guion la
respeta y **avisa de lo que falte**. No la impongas reescribiendo: el guion ya está aprobado.

| Tramo | Longitud | Qué hace |
|---|---|---|
| Gancho | ~15 s | Abre con la pregunta o el hecho que sostiene el vídeo |
| Contexto | ~30 s | Sitúa lo justo para que el resto se entienda |
| Bloques | ~90 s cada uno | Cada bloque cierra con un giro («lo que nadie esperaba…») |
| Cierre | — | El dato final, que es el que se recuerda |

En un vídeo largo con capítulos (la duración la declara `perfil.json → formato.duracion_objetivo_min`), eso son del
orden de **8-14 bloques**. Un vídeo de un minuto, como los del canal `example`, no tiene bloques: gancho, una idea
con su giro y el cierre. Si al guion le faltan los giros, dilo en tu respuesta: es la diferencia entre un vídeo
que retiene y uno que no.

> **Un aviso que NO debes dar.** Si el guion abre desmintiendo un mito, o avisando de que la pieza que enseña es
> una falsificación, eso ocupa el tramo del gancho y es deliberado: la honestidad del canal no es un defecto de
> ritmo. **No lo señales como gancho ausente.**

## Segmentación en slides: un slide es UNA LÁMINA

**Esto es lo primero que hay que entender, y confundirlo cuesta horas de GPU.** Cada slide genera **una
ilustración** (`pipeline.py`, etapa `images`: un prompt por slide), y las ilustraciones se generan una detrás de
otra en la GPU. Así que la pregunta «cuántos segundos dura un slide» es en realidad «cuántas láminas tiene el vídeo».

**Lo constante es cuánta narración lleva una lámina, no cuántas láminas hay**, y se cuenta en **segundos**. Las
palabras son una banda derivada de esos segundos con el ritmo medido de la voz del canal. `scripts/verifica_guion.py`
la deriva así, y tú haces la misma cuenta:

1. **Segundos por lámina** = la duración objetivo media (`perfil.json → formato.duracion_objetivo_min`, en minutos)
   ÷ las láminas estimadas (`perfil.json → formato.laminas_por_video_estimadas`).
2. **El centro de la banda**, en palabras = esos segundos × el ritmo de la voz (`perfil.json →
   voz.palabras_por_segundo`).
3. **La banda objetivo** es el centro × 0,86-1,17, y **el límite duro**, el centro × 0,55-1,40
   (`scripts/verifica_guion.py → FRACCION_OBJETIVO` y `FRACCION_DURA`).
4. **El número de láminas**: las estimadas, ±25 % (`scripts/verifica_guion.py → TOLERANCIA_LAMINAS`).

En el canal `example` (`perfil.json`): [0,75, 1] min dan 52,5 s de media, ÷ 3 láminas son 17,5 s por lámina, y
× 3,073 palabras/s, unas 54 palabras de centro. La banda objetivo del canal `example` sale de 46 a 63 palabras,
el límite duro de 29 a 75, y el vídeo lleva de 2 a 4 láminas (`perfil.json → formato`). Su episodio tiene tres
láminas de 48, 51 y 53 palabras (`slides.json → slides`).

**Al cambiar de motor o de receta de voz, se vuelve a medir el ritmo** (`scripts/cata_ritmo.py`, o sobre un
episodio ya producido) **y las palabras se re-derivan desde los segundos**, que son lo que no cambia. Con un ritmo
viejo, el verificador estima mal la duración y da por bueno un vídeo más corto que el suelo del canal, con todas las
comprobaciones automáticas en verde. Y la cuenta va siempre en este sentido: fijar el número de láminas y repartir
la duración entre ellas da una banda de palabras equivocada.

- Se corta **solo en frontera de frase**, y mejor donde cambia la idea: cada lámina es una imagen, así que el
  corte natural es el cambio de sujeto visual.
- Un slide por encima del límite duro se parte. Uno por debajo se junta con el vecino si comparten sujeto visual.

> ### El ritmo visual no lo dan láminas nuevas
>
> **Esta sección es del formato «láminas».** En `personajes` el ritmo lo dan los planos, la cámara y los actores, y
> en `pizarra`, las piezas y la tinta que aparecen al ritmo de la voz (ver «Para qué sirve cada lámina»).
>
> **Confundir «cambio de plano» con «lámina» es el error que esta sección existe para evitar.** Los análisis de
> retención de vídeos faceless piden a menudo un cambio visual cada 4-6 s. A 4-6 s por lámina, un vídeo de 20 min
> pediría **200-300 ilustraciones**, horas de GPU en serie, y además anularía el reparto en tomas: con slides tan
> cortos, la cámara no tiene nada que partir.
>
> Lo que **sí** da el ritmo es `lib/escena/laminas.py`, que parte cada lámina en tomas con acercamientos, barridos
> y descensos. Lo que dura una toma lo declara el canal (`perfil.json → escena.laminas.toma_s` y `toma_minima_s`),
> y la mínima es un **mínimo**, no un objetivo: una lámina de unos 30 s rinde dos o tres tomas, no seis.
>
> Si el ritmo no basta, se acorta la toma en el perfil, nunca se añaden ilustraciones. Eso cambia todos los
> episodios del canal, así que lo decide quien usa el motor. **No escribas slides más cortos para simularlo.**

## Para qué sirve cada lámina, según el formato del canal

El motor de escena lee este `slides.json` igual en todos los formatos: la misma segmentación, la misma banda de
palabras, el mismo contrato de prompt y la misma miniatura. Lo que cambia es **para qué sirve cada lámina**, y
depende del formato del canal. El catálogo, con lo que es cada formato y su estado, está en `docs/formats.md`.

**Hoy solo `laminas` se produce.** `personajes` y `pizarra` están **en preparación**: el motor ya los ha hecho, pero
Lanternist todavía no trae la capa de escena que un canal nuevo necesita para empezar en ellos. Lo que dice esta
skill de esos dos formatos sirve el día que un canal tenga la suya.

- **En el formato `laminas`** (el del canal `example`), **la lámina ES la imagen del vídeo**: la cámara la recorre
  entera. Su `image_prompt` es además la clave del sorteo de sus movimientos.
- **En el formato `personajes`** (en preparación), **la lámina no sale en el vídeo.** La etapa `images` la sigue
  generando, pero es el **guion gráfico** del episodio: `pone-en-escena` lee su `image_prompt` en el guion por
  partes y la mira para planear la escena.
- **En el formato `pizarra`** (en preparación), **cada lámina ES una pizarra**, y en el vídeo se llena por partes.
  La etapa `activos` la separa en piezas de tiza, y cada pieza aparece cuando la voz la nombra. El modelo de imagen
  la dibuja sin una letra ni una cifra y deja vacía la zona donde escribirá la tinta: lo manda el contrato del
  canal, porque una cifra del prompt acaba dibujada y mal. Todo el texto y todas las cifras los escribe la tinta,
  en el guion de escena, así que no van en el `image_prompt`.
- En los tres, **la miniatura sale de una lámina** (`thumbnail_lamina`), así que el prompt sigue teniendo que
  representar lo que dice su narración.
- **Cada slide es una «lámina de voz»**: un audio y un tramo de la línea de tiempo (en `personajes`, también un
  `tramoN` del guion de escena), con la pausa del canal entre una y otra (`perfil.json → escena.pausas`). Cortar en
  frontera de frase y donde cambia la idea importa igual: la escena puede cambiar de plano dentro de un tramo, pero
  un tramo que mezcla dos historias es más difícil de poner en escena.
- **El ritmo visual es de la cámara, de la puesta en escena o de las piezas que aparecen**, nunca de más láminas. No
  partas slides para dar ritmo.
- **Los capítulos del `slides.json` son para la descripción** (sección `capitulos`, más abajo). El formato
  `laminas` no los rotula en el vídeo, y en `personajes` los títulos de parte los escribe su guion de escena. **En
  `pizarra` sí se rotulan**: el título de cada capítulo se escribe a tiza en la primera pizarra del capítulo, y
  tiene que caber (ver «`capitulos`»). El guion por partes los usa, además, como encabezado de cada lámina.
- **Si el canal tiene diálogos, el run necesita `slides.json → hablantes`**: quién dice cada tramo. De ahí salen
  el color del karaoke y quién rebota al hablar. No es de esta skill: los propone `scripts/hablantes.py` antes de
  la etapa `alinea`, dentro de `produce-semana`.

## El prompt de imagen

**La regla número uno: la imagen tiene que representar lo que la narración está diciendo.** No una escena
decorativa del mismo tema: lo que dice esa frase.

Proceso por slide: lee la narración → identifica el **sujeto visual**, el objeto o la acción de la que habla →
construye el prompt alrededor de ESE sujeto → comprueba que alguien que mire la imagen podría adivinar qué se está
narrando.

Todo lo demás (prefijo de estilo, paleta, acento de color, semilla, qué se enumera y qué no) sale del **contrato
de prompt del canal**. Esta skill no lleva catálogo de estilos: el estilo vive en un solo sitio, y tenerlo en dos es
la forma habitual de que se desincronicen.

## `fuentes`: con qué fichas se escribió el guion

**Obligatorio en un canal con fichas**, que es el que no declara `perfil.json → nicho.sin_fuentes_verificadas`. El
canal `example` lo declara (su vídeo de un minuto enseña a producir, no afirma hechos), así que su `slides.json` no
lleva `fuentes`.

Es la lista de ids de ficha del canal en las que se apoya el vídeo: el nombre del fichero de
`canales/<id>/datos/fuentes/` sin la extensión, por ejemplo `["historia-de-la-cremallera"]`. De ahí sale la
**bibliografía de la descripción**: la compone la etapa de subida con `fuentes.py --bibliografia`, que las lee de
las fichas verificadas.

**No se deduce ni se teclea la bibliografía a mano.** Es el principio del módulo de fuentes: una cita que no
resuelve no existe. Y quien sabe con qué fichas se escribió el guion es quien lo escribió: deducirlo en el pipeline
sería publicar citas que nadie eligió. `scripts/verifica_guion.py` comprueba que el campo esté y que cada ficha
exista en disco.

**En un nicho con cifras, las fichas mandan también sobre las cantidades.** Lo decide el bloque `cifras` del perfil
de autoridades del nicho, en `datos/autoridades/` (lo lleva el de ejemplo, `datos/autoridades/ejemplo-con-cifras.json`).
Cada cantidad de dinero, porcentaje o «million/billion» de la narración tiene que ser el valor de una cifra
confirmada, su redondeo declarado (`se_dice`) o salir de una cuenta de las fichas de `fuentes`, escrita como se dirá
y sin abreviar («45bn» da FAIL). El resultado de una cuenta va en la misma lámina que sus datos.
`scripts/verifica_guion.py` lo comprueba y da FAIL si una ficha no está en `cifras_confirmadas`. Los años y los
números pequeños solo dan aviso: decide tú si son cifras que la ficha tiene que respaldar.

## `capitulos`: las frases con las que se buscaría el vídeo

Van solo si el canal los lleva: `perfil.json → formato.capitulos` a `true`. Míralo en el perfil, no lo supongas
(el canal `example` no los lleva: sus vídeos duran un minuto). Cada capítulo dice en qué slide empieza y cómo se
titula:

```json
"capitulos": [
  {"slide_inicial": 1, "titulo": "How Does a Zip Work?"},
  {"slide_inicial": 5, "titulo": "What Did People Use Before Zippers?"}
]
```

**El minutaje no lo escribes tú.** La etapa de subida lo saca de `montaje.json` y compone el bloque donde dejaste
`<<CAPITULOS>>` (`scripts/compone_descripcion.py`). El primer capítulo sale siempre en 00:00, porque YouTube
descarta la lista entera si no.

**Lo que comprueba la máquina**: `scripts/verifica_guion.py` falla si hay menos de 3 capítulos, si el primero no
empieza en el slide 1, si no van en orden creciente, si dos empiezan en el mismo slide o si uno empieza después del
último. En la subida, `scripts/compone_descripcion.py` avisa si dos capítulos quedan a menos de 10 s, porque YouTube
no los activaría.

**El título es una frase SEO**: lo que el público escribiría en el buscador para encontrar ese tramo. El título del
tramo del guion («Inside the Slider») no lo escribe nadie en un buscador. Cada título:

- **es lo que alguien escribiría en el buscador de YouTube** para encontrar lo que cuenta ese tramo: una pregunta
  («Who Invented the Zipper?») o un tema con sus palabras clave («History of the Zipper»);
- **nombra el tema por su nombre**: el objeto, el lugar, la época. Una metáfora o un pronombre no se buscan;
- **es fiel a su tramo**: promete lo que ese tramo cuenta, y nada que el vídeo no sostenga. Un título de capítulo es
  una afirmación más del guion, así que le alcanzan las mismas reglas: con una ficha `solo_citas_verificadas`,
  tampoco presenta como documentado lo que la ficha no da;
- **busca otra cosa que el anterior**: cada capítulo es otra puerta de entrada al vídeo, y nueve preguntas con la
  misma plantilla se leen como relleno;
- **también el primero**: «Introduction» no lo busca nadie;
- va **en el idioma del canal**, como todo el `slides.json`.

Un ejemplo, para un vídeo largo sobre la cremallera:

| Slide | Título del tramo (no sirve) | Frase SEO (sí) |
|---|---|---|
| 1 | Introduction | How Does a Zip Work? |
| 5 | Before the Zip | What Did People Use Before Zippers? |
| 11 | The Hookless Fastener | Who Invented the Zipper? |
| 18 | Inside the Slider | Why Does a Zipper Split Open? |

La prueba es siempre la misma, con el público del canal (`perfil.json → nicho.descripcion`): ¿alguien de ese
público lo escribiría en el buscador?, ¿lo cuenta ese tramo?

**En el formato `pizarra` (en preparación), el título también sale en el vídeo**: se escribe a tiza en la franja de
arriba de la primera pizarra de su capítulo. Así que cumple además dos cosas:

- **cabe en dos líneas de pizarra**, unos 60 caracteres. Medido el 06-10-2026 con una fuente de tiza, uno de 64
  caracteres cabe y uno de 75 no. Las letras anchas ocupan más, así que no apures el límite. Si no cabe, la etapa
  `escena` para y pide acortarlo, cuando la voz y las láminas ya están hechas;
- **es un título de pizarra**: se lee junto a los dibujos, así que nombra lo que esa pizarra explica: «What Is
  Compound Interest?», «How Does $100 Grow in 30 Years?».

## Miniatura: `thumbnail_lamina` es OBLIGATORIO y no es un prompt

**La miniatura sale SIEMPRE de una lámina del propio vídeo.** `thumbnail_lamina` es su número, y con él la
miniatura **no se genera**: se copia esa lámina y el pipeline le aplica lo de siempre (recorte al objeto, texto con
tipografía real, la comprobación de legibilidad a 168 px y las líneas rojas). **Sin este campo la etapa
`thumbnail` para el run**, y `scripts/verifica_guion.py` lo caza antes, cuando cuesta un renglón y no media hora
de GPU.

Elige la lámina que **muestre el objeto del título**, normalmente una de las primeras, y da su número. El episodio
del canal `example` usa la lámina 2, la del cursor de la cremallera (`thumbnail_lamina` en su `slides.json`).

**Por qué es obligatorio.** Una miniatura generada aparte es la única imagen del vídeo que no parte de una
referencia real, así que el modelo devuelve su arquetipo del tema. Y es la única que nadie ha mirado antes: las
láminas pasan por los ojos de quien usa el motor en la revisión de láminas. Una miniatura generada así salió una
vez con una jaula de pájaro y un cuerpo decapitado dentro, y **pasó la comprobación automática**: `lineas_rojas`
mide manchas de color, y una figura en tinta sepia no tiene color que medir.

**`thumbnail_prompt`** ya NO se usa para producir: la etapa lo ignora, y solo sirve para comparar candidatas a mano
fuera del pipeline. Si lo escribes, describe la escena, con un único foco y contraste alto. **No pidas el título
incrustado**: el modelo de imagen **no escribe texto**, escribe garabatos que lo imitan, aunque el prompt diga
`no text, no letters`. El pipeline añade esa prohibición y **compone el texto después con tipografía real**, que es
lo que permite exigirle un tamaño mínimo en vez de estimarlo.

**`thumbnail_text`** es el texto que se compondrá encima. **Es obligatorio**: sin él la etapa `thumbnail` para el
run antes de gastar GPU. Las reglas:

- **Hasta 5 palabras, y no hay mínimo.** `MYTH?` es un gancho de una sola palabra y vale: contar palabras no dice si
  el texto hace una promesa.
- **NO repite el título**, que va al lado en la lista de sugeridos: repetirlo desperdicia el único espacio que hay.
- **En el idioma del canal** (`perfil.json → idioma`), como todo lo demás del `slides.json`.
- **Lo tiene que sostener el vídeo**, y **el resto lo dice el contrato de miniatura del canal**
  (`canales/<id>/contrato-miniatura.md`), que es donde vive el criterio de identidad. Un canal cuya función es
  desmentir, por ejemplo, no promete atrocidades en la miniatura. Léelo antes de escribir el campo, en vez de
  deducirlo de aquí.

**Que se LEA no depende del número de palabras sino del ancho del texto al pintarlo**, y de eso se encarga el
pipeline: compone el texto del mayor cuerpo que quepa y **para el run** si la altura de mayúscula no llega a 9 px al
reducir a 168 × 94. Un texto de 5 palabras muy largas se rechaza; uno de 6 cortas sería legible, pero el límite de
5 lo prohíbe igual.

**YouTube no deja poner una miniatura propia si el canal no está verificado por teléfono.** A mano, Studio no lo
permite hasta verificarlo; por la API, da un 403 `forbidden`. Es una causa que no está en el prompt: se verifica
el canal y, si subió por la API, se pone con `pipeline.py --run-id <id> --set-thumbnail`.

## Salida

Escribe `slides.json` en el directorio del run:

```json
{
  "title": "...",
  "description": "... <<CAPITULOS>> ... <<BIBLIOGRAFIA>>",
  "tags": ["...", "..."],
  "fuentes": ["id-de-ficha"],
  "capitulos": [{"slide_inicial": 1, "titulo": "Frase que se buscaría"}],
  "thumbnail_lamina": 1,
  "thumbnail_text": "HASTA CINCO PALABRAS",
  "slides": [
    {"slide_number": 1, "narration": "...", "image_prompt": "..."}
  ]
}
```

`fuentes`, `capitulos` y cada marcador van solo si el canal lleva esa cosa (ver abajo). El `slides.json` del
episodio del canal `example` no lleva ninguno de los tres.

`duration` **no va en el ejemplo a propósito**: no lo lee ninguna etapa, y la duración efectiva de cada lámina la
fija su audio. No lo escribas.

`style` y `design_system`, solo si el estilo del canal los usa. El prefijo y la paleta ya viven en el contrato del
canal, y duplicarlos aquí es la forma habitual de que se desincronicen.

**La descripción no se escribe entera**: los capítulos y la bibliografía van como marcadores, y los sustituye la
etapa de subida (`scripts/compone_descripcion.py`). La declaración de IA la añade `lib/publicacion.py`.

- **`<<CAPITULOS>>`**, si `perfil.json → formato.capitulos` es `true`: se convierte en el índice con el minutaje
  real, a partir de `capitulos` (sección de arriba).
- **`<<BIBLIOGRAFIA>>`**, si el canal tiene fichas, o sea si no declara `nicho.sin_fuentes_verificadas`: se
  convierte en la bibliografía que `fuentes.py --bibliografia` construye con las fichas de `fuentes`, así que no
  puede citar nada sin comprobar.
- **Un marcador que el canal no usa sale literal en el vídeo publicado.** No lo pongas.

**El título y la descripción traducidos, si el canal los declara** en `perfil.json →
publicacion.metadatos_traducidos` (por ejemplo, `["es"]`). Por cada idioma declarado, el `slides.json` lleva
`title_<idioma>`, `description_<idioma>` y un `titulo_<idioma>` en cada capítulo (`title_es`, `description_es`,
`capitulos[].titulo_es`). La subida los compone igual que los originales, y el `LEEME.html` de `subir-al-canal/`
los enseña para pegarlos en Studio. **Si falta alguno, la subida para.**

- Son la versión **SEO** en ese idioma, no una traducción palabra a palabra: lo que escribiría en el buscador
  alguien que habla ese idioma. El título sigue el molde del canal en ese idioma, y su cifra sale de la ficha con la
  convención del idioma («270.000 millones», «38,4 %»).
- `description_<idioma>` lleva los mismos marcadores que la original, en el mismo sitio. La declaración de IA en
  ese idioma la añade el código, así que no se escribe.
- Si el vídeo se narra en otro idioma, la descripción traducida lo dice, para no engañar a quien llega por el título
  traducido.

## Comprobaciones antes de dar la salida por buena

1. **Las narraciones concatenadas son EXACTAMENTE el guion de partida**, sin una palabra añadida ni perdida. Es la
   comprobación que protege lo que el usuario va a aprobar, o ya aprobó.
2. El idioma de toda la narración es el del perfil del canal.
3. Cada slide, dentro de la **banda objetivo** de palabras del canal, y **nunca fuera del límite duro**; el total de
   slides, dentro de las láminas estimadas ±25 % (la cuenta, en «Segmentación»). En el canal `example`, 46-63
   palabras, nunca fuera de 29-75, y de 2 a 4 láminas (`perfil.json → formato` y `voz.palabras_por_segundo`).
4. Cada `image_prompt` representa lo que dice SU narración: repásalos uno por uno.
5. Los prompts cumplen el contrato del canal y no cruzan sus líneas rojas.
6. Si el guion no trae gancho, giros por bloque o dato de cierre, **está dicho en tu respuesta**, no en el JSON, que
   es lo que consume el pipeline.
7. Si el canal lleva capítulos, cada título es una frase que su público escribiría en el buscador, fiel a lo que
   cuenta su tramo, y el primero no es «Introduction».
8. `.venv\Scripts\python scripts/verifica_guion.py <ruta al slides.json>` da 0 fallos. No es el gate del guion:
   mide lo que se puede medir, y el criterio lo sigue leyendo y aprobando quien usa el motor.
