# El formato «pizarra»: la pizarra que se construye

Cómo se pone en escena un episodio de un canal cuyo perfil declara `escena.pizarra`. Qué es el formato y qué se
configura está en el catálogo, `docs/formats.md → pizarra`.

**El formato está en preparación.** El motor lo sabe hacer (`lib/escena/pizarra.py`), pero Lanternist no trae todavía
la capa de escena de partida que necesita un canal nuevo: su CSS de tiza, sus títulos y su cierre. Esta guía sirve el
día que un canal tenga la suya. Si el canal del usuario está en este formato y no la tiene, díselo antes de empezar:
montar la capa es programación, no parte de un episodio.

Lo que sigue se aprendió con la muestra con que se probó el formato: un episodio de 65,8 s con sus títulos, sus cifras
y su CTA. Las llamadas de la capa que aparecen abajo (`guion`, `lote`, `pizarra_de`, `Titulos`, `cierre`) son las de
aquella capa: una capa nueva puede llamarlas igual o de otra forma, siempre sobre `Pizarra` de `lib/escena/pizarra.py`.

## Contenido

1. Qué es y qué no es
2. Qué pasos del flujo cambian
3. El guion de un episodio
4. Lo que ajusta el perfil
5. Los títulos, las cifras y el CTA
6. Revisión antes de la parada 2

## 1. Qué es y qué no es

- **Cada lámina del run es una pizarra** que se llena por partes al ritmo de la voz. La etapa `activos` separa su tiza
  de la pizarra (`lib/escena/pizarra.py`): queda una pizarra limpia, con sus borrones, y unas **piezas** de tiza, una
  por cada dibujo suelto. Cada pieza entra cuando la voz dice la palabra que la nombra, de golpe o con un fundido
  corto, sin mano.
- **Todo el texto y toda cifra los escribe la tinta**, trazo a trazo (`lib/escena/tinta.py`). Qwen no dibuja ni una
  letra: el contrato de prompt del canal se lo prohíbe, porque una cifra del prompt acaba dibujada y mal.
- **La cámara está casi fija.** En una pizarra densa se acerca despacio (`Pizarra.acerca`). Entre dos pizarras hay
  corte seco, o un fundido corto si cambia el tema.
- **No hay karaoke**: el guion lo quita, porque la pizarra ya está llena de texto, y solo queda el `.srt`.
- **No hay figuras, ni actores, ni SAM**: las piezas se separan por luminosidad, sin GPU.

## 2. Qué pasos del flujo cambian

| Paso del flujo de `SKILL.md` | En este formato |
|---|---|
| 0. Situarse | Igual: `images`, `tts` y `alinea` hechas. Un solo narrador |
| 1. El plan | No hay `plan.md`. El plan es el docstring del `escena.py`: qué piezas tiene cada pizarra y con qué palabra entra cada una |
| 2. Imágenes y parada 1 | Ninguna imagen nueva. `activos(ep)` amplía cada lámina ×2 con Real-ESRGAN, la separa en tiza y piezas, y trae de la biblioteca el banner y la campana del CTA. **La parada 1 son las hojas numeradas** (`<run>/revision/pizarra-pizarra_NN.png`): el usuario ve cada pizarra con sus piezas numeradas. Si rechaza un dibujo, se reescribe su prompt con el contrato del canal y se rehace esa lámina; después se repite `activos` |
| 3. En seco | Igual, con `scripts/en_seco.py`. La rejilla no hace falta: no hay contactos. Las comprobaciones de `Pizarra` y de los títulos paran el guion si algo no cuadra (§3) |
| 4. Etapa `escena` | Los `momentos` los saca el guion: el título escribiéndose, el borrador a mitad, cada capítulo, las piezas clave, el cambio de tema, la entrada del CTA y la campana |
| 5 a 7. Parada 2, render y correcciones | Igual. La muestra, de 65,8 s, se renderizó en 80,7 s (1,23 veces su duración). Un episodio largo está sin medir: cada letra son dos elementos, así que mide el render del primero |
| 8. Cierre | Nada entra en la biblioteca: las pizarras y sus piezas son del episodio |

## 3. El guion de un episodio

Lo que hace `construye`, en orden:

1. Lee el `slides.json` y arma `titulos = Titulos(slides)`, `linea = ep.linea()`, `marcas = anclas.usa(linea)`,
   `T = marcas.T` y `g = guion(ep, slides["title"], catalogo)`.
2. Abre cada pizarra en su tramo de la línea de tiempo: `pz = pizarra_de(g, ep, n)` y
   `pz.abre(t0, t1, cambio_de_tema=..., de_entrada=[...])`. La pausa entre dos láminas es ya de la pizarra siguiente:
   en la muestra, `cambio = linea.inicio[1] - linea.pausa`.
3. En la pizarra 1, el nombre del canal con la bienvenida y el título del episodio (§5). Todo lo demás de esa pizarra
   empieza en `libre`, cuando el borrador ha pasado.
4. En la primera pizarra de cada capítulo, `titulos.capitulo(pz, n, t)`, donde n es su `slide_inicial`.
5. Lo de cada pizarra, cada cosa anclada a su palabra:
   - `pz.pieza(k, T("palabra", desde), funde=True)`: la pieza k de la hoja numerada;
   - `pz.texto(texto, x, y, t, tam=..., clase="tiza" | "acento", alinea="izquierda" | "centro")`;
   - `pz.flecha([p0, p1], t, clase=...)` recta, o con tres puntos curva;
   - `pz.grafica(valores, caja=..., tiempos=..., cifras=..., etiquetas=..., ...)`: cada barra mide su valor;
   - `pz.acerca(t, hacia=(x, y))`, una vez por pizarra densa.
6. `pz.comprueba()` al cerrar cada pizarra, `titulos.comprueba()` al final y `cierre.cta(g)`.

Tres cosas que se aprendieron escribiendo la muestra:

- **`T(palabra, desde)` es la primera vez que se dice la palabra desde `desde`.** Pasa siempre el principio de la
  pizarra (o algo posterior) como `desde`: una palabra común se dice muchas veces, y sin él se ancla a la de otra
  pizarra. Si la palabra no se dice después, `T` para.
- **Las posiciones van en px de la pizarra ampliada**, 2688 × 1536, las de la hoja numerada. A zoom 1 se ve la pizarra
  entera: 1 px de pantalla son 1,4 px de pizarra.
- **Cada pieza de la hoja tiene un destino**: entra con `pieza` o está desde el principio con `de_entrada`.
  `comprueba()` para si una se queda sin ninguno, porque no saldría nunca y nadie lo vería.

Lo que para el guion, para que no te sorprenda: un ajuste que falta en el perfil, un texto que se borraría antes de
quedar escrito, algo que entra en la pizarra mientras el título está reservado, un capítulo que no se escribe o se
escribe dos veces, y un capítulo de más de dos líneas.

## 4. Lo que ajusta el perfil: `escena.pizarra`

Ninguna clave tiene valor por defecto, y `pizarra.ajustes` para y dice cuál falta. La lista completa, con lo que
significa cada valor, está en `lib/escena/pizarra.py → AJUSTES`:

| Grupo | Claves | Qué fija |
|---|---|---|
| `separa` | `nucleo_px`, `umbral`, `tiza_plena`, `agrupa_px`, `umbral_oscuro`, `masa_minima_px` | cómo se separa la tiza y se parte en piezas |
| `pieza` | `funde_s` | el fundido corto de una pieza |
| `camara` | `zoom`, `acercamiento`, `acercamiento_s` | la cámara fija y su acercamiento lento |
| `transicion` | `cambio_de_tema_s` | el fundido entre pizarras de temas distintos |
| `texto` | `fuente`, `letra_s`, `relleno_tras`, `relleno_s`, `paso_s`, `espaciado`, `interlineado`, `borra_s`, `tamanos` | la tinta, el borrador y los tamaños `titulo`, `etiqueta`, `cifra` y `nota` |
| `flecha` | `velocidad_px_s`, `punta_px` | los guiones que fluyen y la punta |
| `grafica` | `hueco`, `trazo_s`, `rayado_px` | las barras y su rayado de tiza |

Los colores no van en el perfil: son las clases `tiza` y `acento` del CSS del canal. Estas claves son identidad del
canal, así que cambiarlas lo decide el usuario.

## 5. Los títulos, las cifras y el CTA

- **El título del episodio** se escribe en el centro de la pizarra 1, vacía, cuando la bienvenida lo dice
  («Today's question... {titulo}»), y lo barre el borrador (la salida `borra` del motor):

  ```python
  t_titulo = T(slides["title"].split()[0], T("question"))
  t_siguiente = T("Here", t_titulo)  # la primera palabra de la frase que sigue a la bienvenida
  borra = max(t_siguiente - pz.borra_s, titulos.primer_borrado(pz, t_titulo))
  libre = titulos.episodio(pz, t_titulo, borra)
  ```

  - Mientras está, la pizarra es suya (`Pizarra.reserva`): nada entra y ninguna pieza puede estar ya puesta. Un texto
    escrito antes sí vale, como el nombre del canal.
  - Con la tinta de la muestra, el título acababa de escribirse cuando la voz ya había empezado la frase siguiente,
    así que el borrador pasa sobre ella. Se aceptó así; enséñaselo al usuario en la parada 2.
- **Cada capítulo** es el título de su primera pizarra: arriba, centrado y con la letra del título. Sale de
  `slides.json → capitulos`, los mismos de la descripción. Si ocupa más de dos líneas, `capitulo` para: se acorta en
  `slides.json`, y así cambia también en la descripción. Deja libre la franja de arriba de esa pizarra.
- **Las cifras** salen de las fichas del episodio o de un cálculo. Ponlas en un `cifras.py` junto al `escena.py`, y la
  tinta las escribe con dígitos.
  - **La narración también las escribe con dígitos** («$5.3 billion», «92.3%»). Dichas con palabras, el recorte de la
    voz no casa un decimal ni un «billion», y la comprobación de cifras lee mal «zero point…».
  - El `cifras.py` de un episodio busca cada cifra en la narración tal como la escribe el `slides.json`.
- **El CTA** lo pone `cierre.cta(g)`, sobre `lib/escena/cta.py`. En la muestra entraba 4 s antes de «subscribe» y se
  quedaba hasta el final, centrado. La campana suena con «bell». Las dos palabras salen de la despedida del canal. El
  banner y la campana llegan de la biblioteca porque `lote()` los pide siempre: con `en_seco.py --catalogo run` antes
  de `activos`, el cierre para con el nombre de la imagen que falta.

## 6. Revisión antes de la parada 2

En los fotogramas, mira:

- **Cada pieza entra cuando la voz la nombra**, ni antes ni sin motivo.
- **Ningún texto pisa un dibujo** ni se sale de la pizarra.
- **El acercamiento no corta el título de arriba.** En la muestra, los dos acercamientos apuntan 100 px más arriba
  por eso.
- **El título del episodio se escribe entero** antes de que pase el borrador, y la pizarra queda vacía tras él.
- **Los capítulos coinciden con los de la descripción.**
- **El CTA no tapa lo que la voz está explicando** en sus últimos segundos.
- **La declaración de IA** de este formato la escribe la subida sola, con la línea `imagen_pizarra` de
  `lib/publicacion.py`, cuando el montaje dice que el formato es «pizarra». No hay que hacer nada.
