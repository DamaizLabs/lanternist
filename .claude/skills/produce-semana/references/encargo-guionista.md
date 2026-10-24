# Encargo del guionista: el brief invariable

Eres el guionista de **un** episodio. Este brief es la parte del encargo que no cambia entre episodios. Lo variable (la
ficha, el título, el acento, el número de láminas, la semana y el episodio, el nivel de respaldo y el disclaimer) te
llega en el encargo mismo. Cúmplelo entero: cada punto existe por un defecto que ya ocurrió.

## Contenido

1. Fuentes y respaldo
2. Imagen
3. Duración
4. Cómo se escribe para Orpheus
5. Bienvenida y despedida
6. Campos obligatorios del `slides.json`
7. Tu informe: el del gate 1

## 1. Fuentes y respaldo

- **Tu ficha es la vara de medir de toda afirmación factual.** Lo que la ficha no sostiene, el guion no lo afirma.
- **Lee antes de escribir**: `canales/<id>/contrato-prompt-imagen.md`, `canales/<id>/contrato-miniatura.md`,
  `.claude/skills/script-to-slides/SKILL.md` y la lista del gate 1 (§7 de este brief).
- **Si el nivel de respaldo es `solo_citas_verificadas`**, las fuentes existen y tratan del tema, pero nadie las ha
  leído. El guion **no puede presentar nada como documentado**, tampoco en las formas sutiles además de las obvias:
  «we know that», «most examples», «commonly», «usually», «very often», cifras, porcentajes, plazos y nombres que la
  ficha no dé. Es el defecto más repetido: en una primera tanda de cuatro guiones fueron **26 de los 43 hallazgos**.
- **El disclaimer**, si la ficha lo tiene, va en los primeros treinta segundos.
- **Si tu ficha lleva `cifras`** (su nicho declara el bloque `cifras`), las cantidades del guion salen solo de ahí:
  - cada cantidad de dinero, porcentaje o «million/billion» que digas tiene que ser el `valor` de una cifra confirmada,
    su `se_dice` (el redondeo que declara la ficha) o salir de una de las `cuentas` de la ficha. Escríbela sin abreviar
    («$5.3 billion», nunca «5.3bn»). No inventes otro redondeo: si la ficha dice «$5,323 million» con `se_dice`
    «$5.3 billion», «about $5 billion» da FAIL. Si te hace falta otro, pídelo en tu informe: se añade a la ficha y lo
    comprueba el código;
  - **escribe con dígitos las cantidades de dinero y los porcentajes** («$5.3 billion», «92.3%», «$65»); los años y los
    recuentos pueden ir con palabras. Con palabras, el recorte de la voz no casa un decimal ni un «billion» con lo que
    escribe whisper, y el gate lee mal «zero point…». Al pasar a dígitos baja el recuento de palabras del verificador:
    mantén cada lámina dentro de su banda;
  - **la cifra del título también pasa por el gate 1**, porque la bienvenida dice el título en la lámina 1. Tiene que
    casar con la ficha tal cual («38%» no casa con un 38,4 %), y si es el resultado de una cuenta, la lámina 1 dice
    también sus datos;
  - di el año y el ámbito de cada cifra, como la ficha los da: una cifra de un país no es la del mundo, ni la de hace
    cinco años la de hoy;
  - el resultado de una cuenta va **en la misma lámina** que sus datos: así la cuenta queda escrita en el guion;
  - un dato `ejemplo` se dice como ejemplo («imagine», «say you put»), nunca como un hecho;
  - `cifras_confirmadas` deja dar las cifras como hechos, y nada más. El porqué del tema no se presenta como documentado
    si la ficha no lo respalda.
- **El guion es tuyo.** La ficha puede citar vídeos de otros canales en `inspiracion`: son el mapa del tema, no un texto
  que rehacer. No recibes sus transcripciones y no las busques: el guion no copia a ningún canal.
- **Si el canal declara `nicho.sin_fuentes_verificadas`** (el canal de ejemplo lo hace), no hay ficha que sirva de vara:
  la vara es el formato del canal en `perfil.json`, y el guion no lleva `<<BIBLIOGRAFIA>>` ni `fuentes`. Eso es
  correcto, no una carencia.

## 2. Imagen

- **La segunda regla del contrato de imagen: el sustantivo trae el tamaño.** La tabla de tamaños de las piezas del canal
  está en su contrato de prompt; úsala en cada `image_prompt`.

### 2.0. El prompt se construye a partir del guion. No es el guion

Es la regla que ordena todo lo demás: **los prompts que generan las imágenes tienen que salir del guion; el guion no
tiene que ser el prompt.**

Son dos trabajos distintos y se hacen en dos pasos:

1. **Escribes la narración.** Qué se cuenta, en qué orden, con qué palabras se oye.
2. **Después construyes la imagen que la acompaña**, preguntándote qué tiene que ver el espectador mientras oye eso. El
   prompt no traduce la frase: describe una escena.

El defecto que esto corrige es escribir el `image_prompt` como una paráfrasis de la narración («una vista de la picota
mientras se explica su altura»). Entonces hereda su nivel de detalle, que es el de la prosa hablada, y deja sin
especificar todo lo que una imagen necesita y una frase no: el encuadre, la luz, el fondo, la ropa, la postura, por
dónde pasa cada parte del cuerpo.

**La forma que funciona**, sacada de un prompt que salió a la primera después de cuatro intentos fallidos, en este
orden:

| Bloque | Qué lleva |
|---|---|
| **Encuadre y luz** | el plano (medio, entero, cenital), desde dónde se mira, qué luz y qué fondo |
| **Sujeto y su relación con el objeto** | pieza a pieza, sin dejar nada a la interpretación (§2.2) |
| **Materiales** | de qué es cada cosa y en qué estado: madera envejecida con vetas, hierro con marcas de uso |
| **Vestuario y figura** | prenda, tejido, color, calzado, pelo, expresión |
| **Postura** | qué hace el cuerpo y por qué: inclinado hacia delante por la tabla, piernas visibles debajo |
| **Estilo del canal** | el acabado, el acento de color y su contrato: lo único que NO sale del guion |

Un prompt así ocupa entre 900 y 1.300 caracteres. Los que fallaban rondaban los 600 y gastaban la mitad en el objeto.

### 2.1. Nombrar algo lo dibuja, aunque lo estés negando o midiendo

Cuatro casos medidos en una sola semana de producción, todos con el mismo mecanismo:

| Lo que decía el prompt | Lo que salió |
|---|---|
| «an **empty** pillory… nothing inside it» | una persona metida dentro |
| «the sheet, **the size of two hands**» y «a small drawn **hand** in the margin» (la manícula, un símbolo) | dos manos de carne sujetando el papel |
| «two posts set far enough apart **for a person to stand between them**» | un hombre de pie entre los postes |
| «a view across an **empty** square» | un hombre de espaldas en medio |

**La regla**: en un prompt no hay palabras inertes. Una negación es una mención, y una medida expresada con un cuerpo es
una mención. Así que:

- **Describe lo que SÍ hay.** En vez de «una picota vacía», «el pavimento de la plaza se ve a través de los tres
  agujeros, un círculo ancho de luz en cada uno». Eso deja el marco vacío sin decir «vacío».
- **Mide en cifras, nunca con partes del cuerpo.** «un metro y medio entre los postes», no «lo bastante para que quepa
  una persona». «treinta centímetros de alto», no «del tamaño de dos manos».
- **Llama a las cosas por su nombre técnico** cuando el nombre común nombra un cuerpo: el símbolo del margen es una
  `manicule`, no «una manita que señala».

### 2.2. La figura humana se describe con la misma minucia que el objeto

El contrato de cada canal manda enumerar las partes del objeto, y eso se cumple. **Lo que hace falta además es la regla
equivalente para la persona.** Sin ella, las figuras salían en una línea («a single figure standing upright inside a
pillory, arms out to each side») y el modelo improvisaba el resto: brazos atravesando los agujeros, un torso sin brazos,
dos cabezas en la misma figura.

El patrón que funciona salió a la primera después de cuatro intentos fallidos. Tiene tres partes y las tres hacen falta:

1. **La relación cuerpo-objeto, pieza a pieza.** No «dentro de la picota», sino «la cara por la abertura del medio, y
   cada **muñeca** por una abertura lateral, de modo que la madera cierra sobre la parte estrecha de la muñeca y la mano
   entera queda al otro lado de la tabla; los antebrazos y los codos, detrás». Si no dices por dónde pasa cada parte, el
   modelo lo decide, y lo decide mal.
2. **Viste a la figura**: prenda, tejido, color, calzado, pelo y expresión. «Túnica larga de tela burda en gris oscuro,
   manga larga, calzas del mismo paño, botas de cuero hasta la rodilla con cordones, pelo largo y suelto cayendo hacia
   delante, expresión serena mirando al frente.» Eso ancla la figura en una época y le quita al modelo el margen para
   inventarla.
3. **Repite la posición.** Decirlo una vez es competir con las otras cuarenta cosas del prompt; decirlo dos veces pesa.
   No es redundancia descuidada: es énfasis.

**Vale en cualquier canal.** En uno donde casi todas las láminas son el objeto solo, la figura es la excepción; en uno
con personajes en todas las láminas, la regla se aplica más, no menos.

### 2.3. Cuándo el texto no basta: la edición por instrucción

Si el modelo dibuja **otro objeto** (sustituye el que no conoce por el arquetipo que sí: una jaula de exposición salía
jaula de pájaro, un instrumento raro salía una hélice de cuatro aspas), no se insiste con el prompt. Se parte de una
foto real y se replica con `Qwen-Image-Edit`, con `scripts/reune_referencias.py` y `scripts/edita_laminas.py`.

**Pero la edición no sirve para todo**, y se midió en un mismo episodio:

| Caso | Qué funciona |
|---|---|
| un objeto que el modelo no conoce | **la edición** sobre una foto real |
| un objeto conocido, sin figura | la edición o el texto: las dos valen |
| **una persona en una pose concreta** | **el texto detallado** (§2.2) |

El motivo del tercer caso: la edición conserva la estructura de la foto, y con ella su anatomía, su ropa y su encuadre.
Una litografía antigua no es un molde limpio del que sacar una figura.

## 3. Duración: dentro de la banda del formato, y la banda es de tu canal

**No hay una cifra universal y este brief no te la va a dar.** Las tres que necesitas salen del perfil del canal que te
toca, y el verificador las deriva de ahí:

| Qué | De dónde sale |
|---|---|
| la banda de minutos | `perfil.json → formato.duracion_objetivo_min` |
| cuántas láminas | `perfil.json → formato.laminas_por_video_estimadas` (±25 %) |
| a qué ritmo narra **este** canal | `perfil.json → voz.palabras_por_segundo` |

Multiplica: `minutos × 60 × palabras_por_segundo` son las palabras del guion entero, y repartidas entre las láminas te
dan el centro de cada una. **Pero no lo calcules a mano**: escribe un borrador y pásalo por el verificador, que te dice
la banda exacta y **cuántas palabras faltan**.

```bash
.venv\Scripts\python scripts/verifica_guion.py <ruta al slides.json>
```

`scripts/verifica_guion.py` **falla** (no avisa) si el total se sale de la banda de minutos o si una lámina se sale de
su límite duro.

**Las cifras cambian mucho de un canal a otro.** El canal de ejemplo narra a 3,073 palabras/s en tres láminas de unos
17 s (`canales/example/perfil.json → voz.palabras_por_segundo`); un canal de vídeos largos puede narrar a unas 2,4 en
láminas de 30 s, y uno de ficción para estudiantes, a unas 1,9 en láminas de 95 s. **Las cifras exactas no se copian de
aquí**: salen del perfil de tu canal. Un guion escrito con las cifras de otro canal puede salir cinco veces más largo de
lo que cabe.

**Por qué se insiste, dos veces ya:**

- Un episodio salió a **13:54**, por debajo del suelo de 15 min de su canal, con todas las comprobaciones automáticas en
  verde. Sus láminas se calcularon con el ritmo del motor de voz anterior. No falló el guion: falló la cifra con la que
  se dimensionó.
- El ritmo de un canal estuvo escrito dentro del verificador, que medía los guiones de otro canal con un ritmo ajeno y
  no cazaba nada.

## 4. Cómo se escribe para Orpheus: lo que hace que el vídeo no aburra

Orpheus, el motor de voz, entona **por cómo está escrito el texto**, no por un mando. Un texto plano lo lee plano. Un
primer episodio escrito así (cero etiquetas, cero puntos suspensivos, 160 frases perfectas) salió plano, y se rechazó al
oírlo. Las reglas que lo corrigieron son estas, y `scripts/verifica_guion.py` **falla** un guion con cero etiquetas y
cero puntos suspensivos:

- **Puntuación que respira.** Nada de mayúsculas automáticas ni de puntuación perfecta de escuela: separa las ideas con
  comas o con puntos suspensivos. Una pausa antes del dato que importa, una idea partida en dos donde la voz tiene que
  caer. Puntos suspensivos donde quieres que el narrador se detenga… y suelte.
- **Etiquetas emocionales, solo las que declara la receta de voz del canal**: el fichero de `perfil.json → voz.receta`,
  en `canales/<id>/datos/`, en su `etiquetas_emocionales.permitidas`. **La lista se lee de la receta, no de aquí**:
  copiada en un brief se desactualiza, y el verificador también la lee de allí.
  - Van dentro del texto, donde el sonido encaja: antes de la frase que sorprende, después de la que pesa.
  - **Cualquier otra etiqueta se pronuncia en el vídeo**, y el run se para.
  - Dosifica: son el acento, no la frase. El texto es la palanca principal y las etiquetas, la secundaria. Sobre el
    modelo cuantizado a 8 bits (Q8), `<groan>` suena en 4 de 6 pasadas y `<sigh>` en 1 de 6.
  - `<gasp>` se retiró de un canal después de oírla leída en voz alta en el vídeo. Estaba medida como floja (0 de 6
    sobre una frase de 48 palabras, 2 de 6 sobre una de 18) y se declaró con la advertencia «úsese en frase corta», que
    nadie respetó. **Una etiqueta que solo funciona si alguien recuerda una condición no es una etiqueta permitida: es
    una trampa.**
- **Las exclamaciones van con la convención española, «¡…!», también escribiendo en inglés.** Se eligió oyendo las dos,
  y está medido: sobre la misma frase, «¡…!» sube el tono medio 12 Hz y la energía 2,4 dB respecto al punto, y en una
  orden de diálogo sube el tono **4,5 semitonos** sobre el narrador, contra 2,4 con «!» solo. Es un recurso de
  **énfasis**, no de decorado: una exclamación en cada frase deja de significar nada. Dos cuidados:
  - el troceo parte en «!» igual que en «.», así que una exclamación a mitad de párrafo crea su propio segmento y
    necesita 5 palabras como cualquier frase;
  - «!!» no añade nada medible sobre «!».
- **El tono lo decide el usuario para su canal, y se aplica en el guion, no en la receta.** Un canal de historia puede
  pedir dramático; uno para estudiantes de idiomas, cálido y cercano, porque ahí el drama juega en contra de entender.
- **Las onomatopeyas sueltas no existen para el motor: las lee.** «¡Poof!», «Bang!» o «Splash!» salen pronunciadas como
  palabras y suenan fatal, y `scripts/verifica_guion.py` las **falla**. Cuenta el sonido con la acción: en vez de
  «¡Poof! The kitchen disappeared», «The bag burst, and the kitchen disappeared». Usadas como verbo o sustantivo no
  pasa nada: «the door banged» se lee bien, y el verificador solo caza la que forma una frase entera.
- **En el diálogo, escribe la atribución pegada a la cita.** «Sam shouted, "¡Mia, wake up!"», y no la cita suelta.
  Medido sobre una línea así: con la atribución, el grito sube a **240,0 Hz**; sin ella, se queda en **208,7**. El verbo
  le dice al motor cómo decirlo. **Y no hace falta gritar por escrito**: la variante con mayúsculas y signos de más dio
  el mismo tono y se descartó por robótica. Lo que hace que un personaje suene a personaje es el troceo, que su línea
  llegue sola al motor, y de eso se encarga el pipeline, no tú.
- **No escribas «whispered», «murmured» ni «in a low voice»: Orpheus no susurra.** La palabra no cambia el audio (el
  motor la lee como narración normal), así que solo consigue prometerle al espectador algo que no va a oír. Y hay un
  daño peor, medido: un guion decía «Mia whispered, "Rex. No. Sit."» cuando el personaje **le está gritando al perro**, y
  el motor se comió dos de las tres palabras. Si el personaje manda, grita o se asusta, **se escribe con
  exclamaciones** («Mia said, "¡Rex! ¡No! ¡Sit!"»), que es lo único que el motor sí obedece. Para lo bajito, cuenta el
  efecto en la acción: «Mia said it very quietly, and Rex stopped».
- **Las etiquetas no cuentan como palabras**, ni para la banda de tu canal ni para la duración, y los subtítulos las
  quitan solos: una etiqueta permitida no aparece en pantalla.

## 5. Bienvenida y despedida, si tu canal las declara

Las plantillas están en `perfil.json → formato.bienvenida` y `formato.despedida`. Si el perfil no las declara, el guion
no las lleva: el canal de ejemplo, con episodios de un minuto, no las tiene. Si las declara, el verificador las exige, y
tú las adaptas al episodio rellenando sus marcadores (`{titulo}`, `{tema}`, `{lo_visto}`). Sin ellas, un vídeo largo
queda seco.

- La **bienvenida** va **delante** de la narración de la lámina 1 y no puede retrasar el desmentido más allá de los
  30 s.
- La **despedida** es una **lámina final propia** (`"tipo": "cierre"`), que reutiliza la ilustración de la última lámina
  del relato, sin animación, y dura **una lámina de tu canal**: la misma banda que las demás, la que el verificador
  deriva de su `perfil.json`. Dice qué se ha visto sin afirmar nada nuevo, pide suscribirse y activar la campana, e
  **invita al siguiente vídeo sin nombrarlo**.
- **No se nombra el episodio siguiente.** No se sabe cuál será, y un título concreto **promete un vídeo que igual no
  existe**. Una plantilla genérica («so the next story finds you») vale para todos los episodios y no caduca. Ya falló
  dos veces: una vez hubo que dejar el hueco vacío a mano porque el siguiente episodio se había apartado de la
  producción, y otra el guion se inventó un «Next time…» que su plantilla no pedía. Las dos veces se parcheó el guion en
  vez de la regla.
- Las dos van en un tono alto y cercano, que rompe a propósito la sobriedad del relato. **Llevan etiquetas de alegría**
  (`<laugh>`, `<chuckle>`, medidas sobre Q8: 0 de 6 pronunciadas, 4 de 6 con sonido) **solo si la receta de tu canal las
  declara** en `etiquetas_emocionales.permitidas`. Una etiqueta que no está en la lista para el run: le pasó a un canal
  cuyo perfil escribía `<chuckle>` en la bienvenida con la lista vacía.
- **Un canal puede no declarar ninguna etiqueta, y a propósito**: el de ejemplo no lleva
  (`canales/example/datos/voz-example-en.json → etiquetas_emocionales._por_que_ninguna`). Ahí el tono lo dan la
  escritura, las exclamaciones y los puntos suspensivos. Y sin etiquetas, los puntos suspensivos son lo único que salva
  el guion del fallo de «puntuación de escuela» del §4.
- El aviso de suscripción (el banner con la campana) lo pone la puesta en escena, con `lib/escena/cta.py`, no tú.

## 6. Campos obligatorios del `slides.json`

- **Los marcadores `<<CAPITULOS>>` y `<<BIBLIOGRAFIA>>` van en `description` solo si tu canal lleva esa cosa.** Los
  rellena **la etapa de subida**, con el minutaje real de `montaje.json` y las citas de las fichas. No los sustituyas tú
  y no los quites.
  - `<<CAPITULOS>>`, si `perfil.json → formato.capitulos` es `true`;
  - `<<BIBLIOGRAFIA>>`, si el canal tiene fichas, o sea, si **no** declara `nicho.sin_fuentes_verificadas`.

  **Míralo en el perfil, no en un ejemplo**: un ejemplo escrito en un brief se queda viejo en cuanto el usuario cambia su
  perfil. Un marcador que el canal no usa se queda **literal en la descripción del vídeo publicado**.
- **`capitulos`, si tu canal los lleva**: en qué lámina empieza cada uno y su título. El título es una **frase SEO**: la
  que su público escribiría en el buscador, fiel a lo que cuenta ese tramo, y no el título del tramo. Las reglas y un
  ejemplo están en `script-to-slides`, sección «`capitulos`». **En el formato `pizarra` (en preparación)**, el título se
  escribe además a tiza en la primera pizarra del capítulo y tiene que caber en dos líneas, unos 60 caracteres: la regla
  está en la misma sección.
- **`thumbnail_lamina` es obligatorio**: el número de la lámina de este vídeo que sirve de miniatura. La miniatura **no
  se genera**: se copia de una lámina. Sin este campo, la etapa `thumbnail` para el run, y `verifica_guion.py` lo caza
  antes. Elige la que muestre la pieza del título, normalmente una de las primeras. Nació de que una miniatura generada
  dibujaba otra pieza dos episodios seguidos.
- **`fuentes` es obligatorio donde haya bibliografía**: la lista de ids de las fichas con las que escribes, que son el
  nombre del fichero de `canales/<id>/datos/fuentes/` sin la extensión. De ahí sale `<<BIBLIOGRAFIA>>`. **No se deduce
  en el pipeline**, porque publicaría citas que nadie eligió.
- **El título y la descripción traducidos, si tu canal los declara** en `perfil.json → publicacion.metadatos_traducidos`
  (por ejemplo, `["es"]`): `title_es`, `description_es` (con los mismos marcadores que `description`) y `titulo_es` en
  cada capítulo. Son la versión SEO en ese idioma, con la cifra de la ficha en su convención («38,4 %»). La declaración
  de IA no se escribe: la añade el código. Sin ellos, la subida para. Las reglas están en `script-to-slides`, sección
  «Salida».

## 7. Tu informe: el del gate 1

Escribe tu informe en `canales/<id>/calendario/gate1_<semana ISO>_ep<NN>.md` (por ejemplo, `gate1_2026-W44_ep01.md`).
Recorre la lista de abajo punto por punto, con la evidencia de cada uno, y termina con una casilla `## APROBADO`
**vacía**: el gate 1 lo firma el usuario, no tú.

**La semana va en el nombre porque sin ella el fichero colisiona, y ya pasó.** Con un nombre sin semana, «ep01» nombraba
el primer episodio de todas las semanas, y un guionista escribió encima del informe de otra semana, que llevaba dentro
la aprobación del usuario. Se recuperó con git, pero lo que se estaba pisando era **la evidencia de una aprobación
humana**, de lo poco que no se puede regenerar. **Antes de escribir, comprueba que tu fichero no existe.** Si existe, no
lo abras para escribir: para y dilo.

### La lista del gate 1

**A. Contenido y fuentes.** En un canal `sin_fuentes_verificadas`, este bloque se cambia por una sola pregunta: ¿el
guion respeta el formato del canal (`perfil.json → formato`)?

- [ ] Cada afirmación factual del guion tiene ficha (`fuentes.py --fichas` lista las del canal).
- [ ] Ninguna ficha usada tiene fuentes sin resolver: el listado lo marca con `<- TIENE FUENTES SIN RESOLVER`.
- [ ] El periodo y el ámbito del guion son los de la ficha.
- [ ] El `disclaimer` de la ficha, si lo tiene, está **dentro del vídeo** y en los primeros treinta segundos, no solo en
      la descripción.
- [ ] Ningún mito de `mitos_asociados` se cuenta como hecho, y Wikipedia no se cita de viva voz como fuente: es el
      índice con que se encuentran las fuentes, no una de ellas.
- [ ] Con fichas en `solo_citas_verificadas`, nada se presenta como documentado (§1).
- [ ] En un nicho con cifras, cada ficha del guion está en `cifras_confirmadas`, y cada cantidad sale de ella (§1).

**B. Líneas rojas.**

- [ ] Ninguna escena cruza las líneas rojas del canal (`perfil.json → lineas_rojas`) ni las de la ficha. El guardián
      automático mira las láminas por color, pero no lee el guion: la postura y lo que describe el texto se miran aquí.

**C. Forma.**

- [ ] 0 fallos en `scripts/verifica_guion.py`.
- [ ] Los capítulos, si el canal los lleva.
- [ ] El idioma de la narración es el del canal (`perfil.json → idioma.narracion`).
- [ ] El guion no nombra ni imita a un canal identificable.

**D. Lo que se prepara para la subida.**

- [ ] `thumbnail_lamina` y, si hay bibliografía, `fuentes` (§6).
- [ ] En `description`, solo los marcadores que el canal usa (§6). La declaración de IA no se escribe: la añade el
      código.
