# Contrato de prompt de imagen — canal de ejemplo

> **Del canal, no del motor.** Lo que define cómo se pide una lámina a este canal vive aquí; otro canal tiene el
> suyo. Se completó en OC1.4 con lo que enseñaron las tres láminas del primer episodio.

## La regla, en una línea

Cada lámina describe **un objeto cotidiano entero, o su mecanismo**, en una sola escena y con un único centro de
interés. El estilo, un grabado de museo en sepia sobre papel envejecido, lo pone el workflow
`qwen-2512-lightning-tinta` (`perfil.json → imagen.modelo`): el prompt describe **qué hay**, no cómo se dibuja.

## Qué lleva un prompt

1. **El objeto y su tamaño**, nombrado con un sustantivo concreto: «a zip», «an open umbrella».
2. **Dónde está**: sobre una mesa, en una mano anónima, en corte para enseñar el mecanismo.
3. **El encuadre**: plano general o detalle, de frente. Sin perspectivas forzadas.

## Qué no lleva

- Personas reconocibles, marcas, logotipos ni texto legible: el modelo no escribe texto, lo imita
  (`perfil.json → lineas_rojas`).
- Adjetivos de superficie: el canal todavía no tiene lista negra medida (`perfil.json → imagen.adjetivos_prohibidos`
  está vacía); las tres láminas de OC1.4 no enseñaron ninguno que falle.

## Un mecanismo se describe por lo que se ve, no por su nombre

El modelo dibuja las palabras, no el mecanismo que nombran (OC1.4, lámina 2 de «How Does a Zip Work?»):

- «above the slider the two rows stand apart in a V, below they are locked together in one straight line» dibujó
  **dos cremalleras cruzadas**.
- «its channel shaped like a Y» dibujó **una pieza de metal en forma de Y** encima de una cremallera cerrada.
- «a single zip lying horizontally… half open: on the left its two strips spread apart in a wide sideways V…; in the
  centre, where the two strips meet, sits the slider; on the right… one closed strip» dibujó el mecanismo.

Así que: **un solo objeto, dicho en positivo** («a single zip… the only object»), su orientación, y cada parte por
su forma y su sitio en el cuadro. Lo mismo vale para lo que el objeto tiene: la lámina 1 pedía botones y salieron
cordones, y la narración se ajustó a la imagen («buttons, hooks or laces»).

Con este modelo, el prompt entero en español (escena y estilo) quitó el tirador duplicado de la lámina 3 donde el inglés y
dos ediciones con Qwen-Image-Edit no lo consiguieron, y solo con una de tres semillas (la 2027; `slides.json →
slides[2]`, que lleva su propio `prefijo_estilo`).

## La semilla

La de `perfil.json → imagen.seed`. Es parte del acabado: cambiarla cambia el estilo entre láminas. Para arreglar una
lámina, se cambia el texto de su prompt y se conserva la semilla: así la diferencia es del texto y no del azar.
