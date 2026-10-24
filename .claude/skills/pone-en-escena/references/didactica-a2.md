# La capa didáctica A2 (canales con capa didáctica)

Es lo que convierte la historia en una clase de inglés de nivel A2 (básico). Va con el formato «personajes», que está
en preparación (`docs/formats.md`): ningún canal de Lanternist la trae todavía, y esta guía sirve el día que una capa
de canal la tenga. Un canal sin capa didáctica no lee esto.

Las reglas que el código hace cumplir **viven en la capa del canal**, no aquí: los mínimos y la revisión en su
`escena/didactica.py`, los envoltorios con su disposición en su `escena/ayudas.py`, y el color de cada hablante en su
`estilo.css`. Esto es **cómo se escribe** la capa de un episodio para que pase esa revisión a la primera. Las
llamadas de abajo son las de la capa con que se probó: una capa nueva puede nombrarlas de otra forma.

## Contenido

1. Lo que no puede faltar
2. Dónde se escribe
3. Las piezas
4. Cómo se eligen las palabras
5. Las pausas y el tablero final
6. El karaoke

## 1. Lo que no puede faltar

Va **completa en cada episodio**: una clase a medias no enseña. Tiene cuatro piezas:

1. las tarjetas de palabra nueva;
2. los chips de tiempos verbales;
3. las pausas con el título de la parte y el repaso de las palabras que se oyeron en ella;
4. el tablero final con las palabras del episodio.

`didactica.revisa(g)` de la capa cuenta tarjetas, pasados y notas por parte y avisa por debajo de sus mínimos. Sus
líneas salen en seco y en la parada 2. **Un aviso didáctico no se deja sin resolver ni sin explicar**: si una parte se
queda por debajo, díselo al usuario en la parada 2 con el motivo.

## 2. Dónde se escribe

Así se organizó el primer episodio con capa didáctica (cópialo como forma, no como contenido):

- el `didactica.py` del episodio tiene una función por parte (`parte1(g)` …), `todo(g)` que las llama, y los datos
  del cierre: `PARTES`, `REPASOS`, `primera()` y `RESUMEN`;
- los rótulos con flecha van en los tramos, porque apuntan a sitios de cada plano;
- `escena.py` llama a `didactica.todo(g)`, `cierre.recorta_en_pausas(g)` y `cierre.pausas(g, PARTES, REPASOS,
  primera())`; el último tramo pone el tablero con `cierre.resumen(g, RESUMEN, t0, t1)`;
- `puesta(ep)` añade a los avisos lo que devuelve `didactica.revisa(g)` de la capa.

Todo se ancla a la palabra de la narración con `P(cue, "palabra")`, así que aparece cuando se oye.

## 3. Las piezas

Con los envoltorios de la capa del canal, que ya ponen sitio, tamaño, animación y sonido:

| Pieza | Llamada | Dónde sale | Cuándo |
|---|---|---|---|
| Tarjeta de palabra nueva | `tarjeta(g, "tyre", "bici_rueda", P(16, "tyre"), lado="der", articulo="a")` | esquina de arriba, izquierda o derecha | cada sustantivo concreto de la historia la primera vez que importa; `etiqueta="NEW VERB"` para un verbo clave |
| Pasado simple | `verbo(g, "sat", "sit", P(11, "sat"))` | encima del karaoke, a la derecha | la primera vez que suena cada verbo irregular, y los *phrasal verbs* en pasado |
| Nota de gramática | `nota(g, "HAS TO", "The wheel has to come off.", P(61, "has"))` | encima del karaoke, a la izquierda | donde el cuento da un buen ejemplo: *has to*, *this/that*, ordinales, imperativo, comparativo |
| Número | `numero(g, "2 seconds", P(22, "two"))` | arriba a la derecha | un número que se dice |
| Contador | `contador(g, 1, 6, P(45, "six") - 0.2, 3.4, unidad="tools")` | arriba a la derecha | cuando el cuento cuenta; en el 1 la unidad va en singular |
| Chip de frase | `chip(g, "no air", P(24, "air"), 3.0, x=…, y=…, w=…, h=…, icono="sin_aire")` | arriba, donde no haya cara | una frase corta que conviene leer |
| Onomatopeya | `chip(g, "Pssss...", t, 2.2, …, clase="chip onomato")` | arriba | los sonidos del cuento |
| Grito | `grito(g, "Dad!", P(20, "dad"), 1.8)` | junto a la cabeza de quien grita (lo coloca `gritos.coloca`) | las frases que se gritan |
| Rótulo con flecha | `etiqueta(g, p, "kerb", x, y, t0, t1, sube=320)` | sobre la escena, apuntando al sitio | un sitio o una parte de algo; va en el tramo |
| Lupa, efecto | `lupa(g, dibujo, t0, t1)`, `efecto(g, capa, "pregunta", x, y, t0)` | según la escena | lo pequeño que hay que ver, una emoción |

Los dibujos de las tarjetas son imágenes del catálogo o iconos de la capa (`dibujos.iconos()`); los efectos, los de
`dibujos.EFECTOS`.

## 4. Cómo se eligen las palabras

- **Solo lo que se oye.** Una tarjeta enseña la palabra que dice el narrador en ese momento, en la forma en que la dice.
  «inner tube» no vale si el cuento dice «rubber tube»: la revisión lo caza.
- **Primero lo que se puede dibujar**: los objetos de la propia historia. Después, los adjetivos con su contrario en la
  historia (*flat / round*, *dirty / clean*) y los verbos clave. Las palabras del título y del giro van siempre.
- **El dibujo sale de la propia historia**: el recorte del objeto, de una postura o de un fondo; si no hay, un icono de
  la capa. Un objeto que se enseña en tarjeta es un objeto que el plan tiene que tener.
- **El artículo va aparte** (`articulo="a"`): la palabra es la que se aprende.
- **No se amontonan.** Dos tarjetas seguidas van en esquinas distintas, nada dura menos de lo que se tarda en leerlo, y
  `cierre.recorta_en_pausas` corta al empezar la pausa lo que venía de la parte.

## 5. Las pausas y el tablero final

- **`PARTES`**: el título de la parte que empieza tras cada pausa. Salen de los capítulos del `slides.json` del run y
  se acortan para que quepan en una línea grande. La última es `("The End", "Story Review")`.
- **`REPASOS`**: en cada pausa, de 4 a 5 palabras de la parte que acaba, con el mismo dibujo que tuvieron en su tarjeta.
  Cada una tiene que haberse oído en esa parte y haber salido antes en pantalla. El repaso repasa, no enseña.
- **`primera()`**: el chip «Part 1 · <título>», que sale al empezar la historia.
- **`RESUMEN`**: una mini tarjeta por cosa que nombra el repaso final del narrador, en su orden:
  `(palabra con su artículo, dibujo, cue, palabra que la dispara)`. El tablero tiene un tope de mini tarjetas
  (`cierre.MAX_RESUMEN` de la capa): se eligen las que más se enseñaron, con el mismo dibujo que en su tarjeta. Se
  quedan hasta el CTA.

## 6. El karaoke

Va solo, palabra a palabra, con el color de quien habla (`.w.h-<id>` del CSS del canal). Quién habla sale de
`slides.json → hablantes` y del `reparto` del perfil. En la parada 2, mira que las frases de cada personaje salen con su
color; si un color se equivoca, el fallo está en los `hablantes` del run, no en el guion de escena.
