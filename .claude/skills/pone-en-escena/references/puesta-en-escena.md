# Puesta en escena: patrones, tiempos, defectos conocidos y revisión

Cómo se escribe un tramo, qué ya está resuelto, qué defectos salieron y cómo se revisa antes de la parada 2.

Casi todo es del formato «personajes», que está en preparación (`docs/formats.md`): Lanternist no trae todavía la capa
de escena de partida con personajes, sets y macros. Lo de aquí se aprendió poniendo en escena el primer episodio con
personajes, primero a mano y después con el motor, y sirve el día que un canal tenga su capa. El formato «láminas»
tiene su propia guía, `formato-laminas.md`.

## Contenido

1. Cómo se piensa un tramo
2. Reglas de tiempo
3. Patrones resueltos
4. Lo que no se sabe hacer bien todavía
5. Defectos que ya salieron, y cómo se evitan
6. Revisión antes de enseñar la parada 2

## 1. Cómo se piensa un tramo

Un tramo es una lámina de voz. Se escribe en este orden, porque cada paso depende del anterior:

1. **Los planos**: qué set y cuándo se corta. Un cambio de plano va donde cambia la idea de la narración.
2. **La cámara** de cada plano: dónde mira y cuándo se acerca. Menos movimiento se lee mejor.
3. **Los actores**: quién está, dónde nace (su z sale de ahí) y en qué postura.
4. **Los gestos**, cada uno anclado a la palabra que lo provoca con `P(cue, "palabra")`.
5. **Los elementos** de pantalla y los efectos de sonido.

Una escena que el espectador no entiende no se arregla con más movimiento: se simplifica. Menos gente en el plano y la
cámara más cerca de lo que importa.

## 2. Reglas de tiempo

- **Un gesto va de 0,1 a 0,3 s antes de su palabra.** Así se lee como causa, no como eco.
- **Un cambio de cámara va 0,2 s antes del cue que lo pide.**
- **El cambio de sentido (`flip`) va en su propia clave con `tr` 0**, en un instante distinto del desplazamiento. Con
  `tr` el `flip` se interpola y sale una media vuelta aplastada.
- **Quién tapa a quién se decide al nacer**: la z sale de la y con que se crea el actor. Para que alguien cruce por
  detrás de otro, dale la z al crearlo.
- **Dos claves del mismo actor en el mismo instante**: solo cuenta la transición de la última. El aviso sale en seco.
- **Un elemento de pantalla** dura al menos lo que se tarda en leerlo, y dos no comparten zona a la vez.

## 3. Patrones resueltos

Antes de escribirlo a mano, mira si ya existe: primero en la capa del canal, que es lo que se reutiliza; después en
los episodios anteriores del canal. Las funciones marcadas «capa» son las de la capa con que se probó el formato: una
capa nueva puede llamarlas de otra forma, pero la solución es la misma.

| Qué | Dónde vive y cómo |
|---|---|
| Alguien sale por la puerta de casa, y lo que empuja va con él | capa: `lugares.sale_puerta(actor, t, destino, extra=[(otro, dx, dy)])` y `entra_puerta`. Lo empujado se mueve con las mismas claves (defecto 2) |
| Una puerta que se abre y se cierra | capa: `lugares.Puerta(g, p).abre(t, cierra=t2)` |
| Andar hasta un sitio | capa: `macros.anda_hasta(actor, t, destino, dur)` |
| Llevar cosas en los puños, que alguien se las coja y dejarlas en un sitio | capa: `macros.lleva`, `macros.recibe` y `macros.deja`. El objeto va en el puño, como hijo de quien lo lleva (defecto 1) |
| Las manos de alguien en un mango o en un borde | episodio: el punto de la mano, medido en la rejilla de la postura, como constante con nombre (`MANOS_SENTADO`), y `punto_de_postura` para llevarlo a px del fondo (defecto 3) |
| Poner a alguien para que su mano caiga en un punto | episodio: la misma cuenta al revés, del punto de destino al apoyo del actor |
| Subirse a algo y bajarse | episodio: la figura va dentro de la imagen de ese algo, como otra postura suya, y el paso es de golpe con `fp=0` (defectos 12 y 16) |
| Un objeto por piezas que gira según lo que avanza (ruedas) | episodio: cada rueda es una pieza con el rasgo `rueda` |
| Un estado que se queda (manchas que aparecen al nombrarlas y no se van) | episodio: una variante de cada postura con la mancha (`activos.variante`), usada desde su cue |
| Un recuerdo en un bocadillo | episodio: un elemento con la clase `bocadillo` del CSS del canal |
| Un paseo con la cámara siguiendo a alguien | episodio: la cámara con `sigue=actor.id` |
| Corazones o vapor pegados a un actor | episodio: un elemento con `sigue=actor.id` |
| Gritos junto a quien grita | capa: `gritos.coloca`, llamado en `puesta(ep)` sobre el GUION ya corregido |
| Pausas, tablero final y «The End» | capa: `cierre.pausas`, `cierre.resumen` y `cierre.fin_texto` |
| El CTA: el banner que rebota y late, con su campana que se balancea y suena desde «bell» | motor: `lib/escena/cta.py → pon`. Cada canal lo envuelve en su capa (`cierre.cta`), con su banner, dónde va y cuándo sale |
| Título de entrada y reparto | capa: `apertura.titulo` y `apertura.reparto` |
| Rótulos escritos a tinta: el trazo recorre cada letra y después se rellena | motor: `lib/escena/tinta.py`. La capa pone el texto, la fuente y el sitio |
| Abrir desde negro y cerrar a negro | episodio: dos elementos de pantalla con la clase `negro`, como en el `escena.py` del canal de ejemplo |
| La cámara sobre láminas enteras, con sus tomas y sus transiciones de tinta | motor: `laminas.planifica` y `laminas.pon_en_escena` (`formato-laminas.md`) |

Un movimiento que escribes dos veces en un episodio es una macro de la capa del canal. Súbela al cerrar el episodio y
pasa en seco los episodios anteriores.

## 4. Lo que no se sabe hacer bien todavía

- **Recortes por geometría** (una bici por piezas, una cadena dibujada, una rueda pinchada): son código del episodio y
  usan OpenCV y scikit-image de `.venv-escena`. Son caros de escribir: plantéalos en el plan y en la parada 1, no a
  mitad de la puesta.
- **Un objeto en un estado anómalo** (algo del revés, algo desmontado): Qwen no lo dibuja bien. Se saca de cuadro o se
  hace por geometría.
- **Mover piezas de una lámina dibujada en perspectiva** (abrir, mecer o dar paralaje a lo que SAM recorta): se
  deforma, y el hueco se ve borroso aunque se rellene. En el formato «láminas» está descartado. Lo que se aprendió al
  intentarlo está en `imagenes.md` §6.
- **Las mallas** (una pierna que pedalea, un perro que corre) existen en el motor pero ningún episodio las usa
  (`lenguaje.md` §8).

## 5. Defectos que ya salieron, y cómo se evitan

Del 1 al 17 salieron al poner en escena a mano el primer episodio con personajes, y cada uno costó al menos una ronda
de render. Del 18 en adelante salieron al reproducir ese episodio con el motor.

1. **Lo que se lleva flota.** Todo objeto agarrado va en un puño cerrado, detrás de él e inclinado hacia fuera, como
   hijo de quien lo lleva. Con las palmas abiertas, los objetos flotaban entre las manos.
2. **Lo que se empuja parece moverse solo.** El objeto y quien lo empuja se mueven con las mismas claves (`extra=` en
   `sale_puerta`, o los mismos `t` y `tr`). La mano va en el mango, medida: a 330 px, el manillar iba por delante de las
   manos.
3. **Alguien sentado o apoyado flota.** Se coloca por el punto de contacto medido con `scripts/rejilla.py`, nunca a ojo:
   a ojo, un niño quedó 88 px por debajo del muro en que se sentaba.
4. **Un abrazo que no es.** Cuatro personajes juntos a un lado de algo, con los brazos hacia el centro, se leen como un
   abrazo. Van en parejas a cada lado del objeto, y cada mano en el objeto.
5. **Un beso que no es.** Dos caras que se cruzan de cerca y frente a frente se leen como un beso. Quien cruza lo hace
   por detrás (una z menor al nacer), de pie y mirando hacia donde va.
6. **Una postura que no llega.** Si la mano de una postura no alcanza el punto sin mover a la persona fuera de su sitio,
   hace falta otra postura con la mano a esa altura. Se añade al plan; no se fuerza.
7. **Un atasco al final de una escena.** Si todos acaban en el mismo sitio, se tapan. Cada uno tiene su salida, y quien
   va a pasar por delante de otro espera a que ese otro se ponga de pie.
8. **La cámara se abre sola.** `encuadre.corrige` abre una clave de cámara si en su tramo se corta una cabeza (alguien
   que se levanta). La clave del plano cerrado va después del cambio de postura. En seco dice cuáles abrió.
9. **El flip se interpola** (§2).
10. **Quién tapa a quién no cambia** después de nacer (§2).
11. **Dos claves en el mismo instante: solo cuenta la transición de la última** (§2).
12. **Dos imágenes iguales fundidas se transparentan.** El paso entre dos posturas que llevan lo mismo (la bici con y sin
    alguien encima) va con `fp=0`.
13. **Un texto tapa una cara.** `aparta_de_caras` mueve los textos `movible`, pero solo mira las cabezas del plano de
    encima. Las tarjetas van en las esquinas de arriba; los chips y las notas, en la franja justo encima del karaoke.
14. **Algo sale de la boca** (un diente de Qwen) **o hay algo transparente en lo negro** (el recorte): se ven en las
    imágenes de la parada 1, no en el guion. Se arreglan en la imagen antes de recortar.
15. **La escala de un objeto no cuadra.** Un objeto lleva su `alto` en unidades del set. Se compara en los fotogramas con
    la mano o la cintura de quien está al lado.
16. **Quien va encima de algo se despega.** Si alguien va montado en algo que se mueve, la figura va dentro de la imagen
    de ese algo, como otra postura suya, no como un actor aparte.
17. **Una escena que no se entiende** (§1).
18. **Una palabra del karaoke se enciende antes de decirse.** Donde whisper alucinó y volvió a transcribir, una palabra
    podía anclarse a una marca que empieza en silencio: «because» se encendía 1,5 s antes, y lo que se anclaba con
    `P()` a esa palabra se adelantaba igual. El motor ya lo corrige (`lib/escena/linea_tiempo.py →
    tiempos_de_palabras`, probado en `tests/escena/test_karaoke_en_silencio.py`). Aun así, mira el fotograma justo
    antes de cada palabra que sigue a un silencio largo.
19. **Un grito con una caja más ancha que su texto** da falsos «texto sobre cara». Una caja de 1.400 px dio 7 falsos de
    9 en la comprobación. La capa del canal ajusta la caja al texto (en la capa con que se probó, `gritos.ajusta_caja`,
    dentro de `gritos.coloca`); un canal con gritos necesita lo mismo.
20. **Una cabeza cortada al salir de plano.** La comprobación de cabezas marca a un personaje que se mete en casa y
    roza el borde de arriba mientras sale. Suele ser aceptable: se mira el fotograma y se decide, sin abrir la cámara
    de todo el plano.
21. **La escala de cabeza avisa en posturas de la biblioteca** con los brazos en alto o de perfil. Son medidas reales
    de posturas ya publicadas: no cambies la `k` de una imagen de la biblioteca desde un episodio, porque cambiaría
    todos los que la usan. En una postura nueva, la escala se corrige en la parada 1.
22. **La luz sin modo de fusión.** El motor no admite `mix-blend-mode`, porque obliga a HyperFrames a la captura lenta,
    y `compone` para si lo encuentra. Un velo de luz se consigue con opacidad y degradados en el CSS del canal, y se
    ve algo más apagado que con el modo de fusión.
23. **Un `P()` que no encuentra la palabra en su cue** la busca en los vecinos y deja un aviso. Casi siempre es un cue
    partido por otro sitio: corrige el número del cue para que el aviso desaparezca.
24. **Muchas correcciones de encuadre en un mismo plano** significan que la cámara que escribiste no es la que se verá.
    Reescribe la clave en vez de dejar que el encuadre la abra.
25. **Una imagen que el guion pide y no está en el run** para la etapa `escena`. Añádela a `Lote.biblioteca` o a
    `Lote.activos` y vuelve a pasar `activos`.
26. **Tocar la capa del canal cambia los episodios anteriores** al recomponerlos. Pasa en seco los anteriores después
    de tocarla.

## 6. Revisión antes de enseñar la parada 2

Con `comprobaciones.json` leído y los fotogramas de riesgo delante:

- **Nadie flota.** Los pies en el suelo, el culete en el asiento, las manos en lo que agarran.
- **Nada agarrado flota** ni atraviesa la mano, y cada objeto está a su escala.
- **Las proporciones son las del canal** (sus alturas, en la capa del canal).
- **No hay abrazos, besos ni caras montadas** que la historia no pida.
- **Ninguna cabeza cortada**, salvo un primer plano `libre` a propósito.
- **Ningún texto sobre una cara**, y nada importante por debajo de la franja del karaoke.
- **La continuidad cuadra** con el cue: manchas, prendas y objetos siguen donde se dejaron.
- **Lo didáctico se ve completo**, si el canal lo lleva (`didactica-a2.md`).
- **El título del episodio es el bueno**, y el CTA está entero.
- **Los avisos del guion** están resueltos o explicados.

En el formato «láminas», la lista es otra: `formato-laminas.md` §6.
