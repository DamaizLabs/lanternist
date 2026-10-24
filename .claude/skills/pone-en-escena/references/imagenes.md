# Las imágenes de un episodio: qué se reutiliza, qué se pide y cómo se elige

Cómo decide Claude qué imágenes nuevas pide a la etapa `activos`, cómo las pide con `lib/escena/activos.py`, qué semilla
elige y qué le enseña al usuario en la parada 1. El porqué de cada regla de prompt está en el docstring de ese módulo.

Casi todo es del formato «personajes», que está en preparación (`docs/formats.md`): sirve el día que un canal tenga su
capa con personajes. En «láminas» no se pide ninguna imagen nueva; la §6 sí vale para cualquier lámina.

## Contenido

1. Lo que ya existe
2. Las fábricas
3. Cómo se escribe lo que se pide
4. Elegir la semilla
5. La parada 1
6. Editar una lámina con Qwen y rellenar huecos
7. Lo que el motor todavía no hace

## 1. Lo que ya existe

La biblioteca del canal (`canales/<id>/escena/biblioteca/`) guarda cada imagen ya recortada con su procedencia. Su
`indice.json` dice qué es cada una: `tipo` (hoja, postura, variante, objeto, fondo, pieza…), `pj`, `vista`, `de_pie` y
`que`. Búscalas ahí antes de pedir nada:

```powershell
.venv\Scripts\python -c "import json; d=json.load(open('canales/<id>/escena/biblioteca/indice.json', encoding='utf-8'))['imagenes']; print([n for n, v in d.items() if v.get('pj') == '<personaje>'])"
```

**Una imagen que existe no se genera otra vez.** Regenerarla da un personaje un poco distinto. Se pide por su nombre en
`Lote.biblioteca`, y la etapa `activos` la copia al run con sus piezas y su registro. Si la pides en `Lote.activos`, la
etapa para antes de la GPU y dice de qué episodio sale. Si de verdad hace falta otra versión, dale otro nombre.

**La biblioteca crece con cada episodio**: lo que un episodio generó entra en ella al pasar su parada 1, con
`episodio` en su ficha de `procedencia.json` y en su entrada de `indice.json`. Así que el índice de hoy puede tener lo
que ayer se generó en otro episodio: míralo siempre, no lo recuerdes.

## 2. Las fábricas

El estilo y los personajes salen de la capa del canal (en una capa con personajes, `personajes.ESTILO` y
`personajes.PERSONAJES`). Los lienzos de referencia de cada personaje están en `canales/<id>/escena/biblia/ref/`.

| Qué | Fábrica | Notas |
|---|---|---|
| Una pose nueva de un personaje | `activos.postura(nombre, personaje, estilo, vista=, forma=, pose=, de_pie=, lienzos=, semillas=)` | `vista`: `frente` o `perfil` (el perfil mira a la derecha y el motor lo refleja con `flip=1`). `forma`: `alto` de pie, `ancho` si se arrodilla, se sienta, se tumba o corre |
| La misma imagen con un cambio en su sitio (una mancha, otro gesto) | `activos.variante(nombre, de, estilo, cambio=, semillas=)` | `de` es otro activo del mismo lote. Así pasar de una a otra es un fundido y no se mueve nada más |
| Uno o varios objetos sueltos | `activos.objeto(nombre, estilo, que=, en=, quien=, semillas=)` y `activos.objetos(nombre, estilo, lista=, piezas=, en=, quien=, semillas=)` | Sustituyen a alguien de una hoja (`quien`, p. ej. «both girls») por el objeto: salen planos y sobre croma. Pedidos solo con texto salían como juguetes en 3D |
| La hoja de un personaje nuevo | `activos.hoja(personaje, estilo, referencia=, semillas=)` | Es trabajo de la biblia del canal (`crea-canal`), no de un episodio |

En `Lote.personajes` van los personajes de las posturas que se generan: la escala de cabezas los necesita. En
`Lote.extra` van las operaciones del obrero que no salen de un activo: ampliar un fondo (`obrero.fondo`) o separar con
SAM una pieza que se mece (`obrero.separa`). Con `del_episodio=True`, `obrero.fondo` toma una lámina del propio run:
ni ella ni lo que se separe de ella entra en la biblioteca del canal, porque no sirve a otro episodio.

## 3. Cómo se escribe lo que se pide

- **Qwen dibuja lo que se nombra**, aunque el prompt diga que no. La pose describe **solo el cuerpo**, en inglés, con la
  dirección, las manos y la cara: «standing in side view facing right, looking down at the ground in front of her feet,
  worried, hands at her sides».
- **Lo que se agarra se pide aparte.** La postura lleva los puños cerrados («both hands held up in front of his chest and
  closed in fists») y el objeto es otra imagen, que va detrás del puño. Con las palmas abiertas, los objetos flotaban.
- **Un objeto solo se nombra en una postura si forma parte de ella para siempre** (la taza de un personaje que siempre
  la lleva).
- **Las descripciones de los personajes son las canónicas de la capa del canal.** Las fábricas ya las ponen: no se
  reescriben con sinónimos.
- **Un cambio que se repite es una constante**, escrita una vez y usada en todas sus variantes, para que la mancha salga
  igual en cada postura.
- **Pide dos o tres semillas** de lo que tenga riesgo (una pose difícil, un objeto raro) y una de lo sencillo.

## 4. Elegir la semilla

Mira cada imagen en crudo (`<run>/activos/crudo/<nombre>-<semilla>.png`) con Read, una a una. Descarta la semilla que:

- dibuja algo que no se pidió: otro personaje, un objeto, suelo o sombra;
- cambia la cara, el pelo, la ropa o sus colores respecto a la hoja;
- rompe el estilo del canal: contornos, 3D o texturas que el canal no usa;
- sale a otra escala o recortada por el borde;
- pierde la pose pedida, sobre todo en las manos y la dirección, que es donde la coreografía la va a necesitar.

Apunta la elegida en `Lote.elegidas` (`{"papa_sofa": 21}`) y vuelve a lanzar `--stage activos`: solo recorta. Una imagen
con una sola semilla no necesita apuntarse.

## 5. La parada 1

La página (`<run>/revision/activos.html`) enseña lo traído de la biblioteca, cada imagen en crudo con la elegida
marcada, los recortes sobre un damero para ver la transparencia, lo que falta por elegir y la escala de cabezas. Dile
al usuario:

- qué se ha generado y qué se reutiliza;
- por qué elegiste las semillas dudosas;
- qué recursos de fuera propones, si alguno: un sonido que no está en `datos/escena/sfx/`, una fuente que no está en
  `datos/escena/fuentes/`. Con su ficha, su licencia (que permita el uso comercial: nada con la cláusula NC, no
  comercial) y su tamaño. Nada se descarga sin su sí, y lo que entra lleva su línea en el `CREDITOS.json` de su
  carpeta.

Y espera su visto bueno: la parada es suya, y la skill no la da por pasada. Si pide cambios, se regenera y se le vuelve
a enseñar la página. Con su visto bueno, las imágenes nuevas que usa el guion de escena entrarán en la biblioteca del
canal en cuanto se siga con `--stage escena`, para este episodio y para los siguientes. Una que rechace y no se rehaga
se quita del guion: la que el guion no usa no entra, y la página de la parada 2 la lista como «no la usa».

Si el mismo episodio rehace después una imagen suya (el usuario pide otra semilla en la parada 2), vuelve a pasar la
parada 1 y su versión de la biblioteca se actualiza. Una imagen de otro episodio con el mismo nombre, en cambio, no se
pisa: la tuya se queda solo en este run, y la página de la parada 2 lo dice.

## 6. Editar una lámina con Qwen y rellenar huecos

Se aprendió editando láminas a tinta con Qwen-Image-Edit. Cada edición cuesta unos 2 min de GPU: 8 imágenes tardaron
986,5 s.

**Cómo se pide una edición:**

- **Lo que se quita se pide como una orden de quitar**: «Remove the metal instrument from the table completely». Pedir
  lo que debe quedar no quita nada: con «leave only the bare wooden table», Qwen dejó el objeto intacto en las dos
  semillas.
- **La instrucción tiene tres partes**: qué se quita o se cambia; qué queda en su sitio, descrito con el estilo del
  canal («Where it was, continue the bare wooden table with its faint vertical grain, in the same pen and ink
  hatching»); y «Keep everything else exactly the same: …», con la lista de lo que no se toca (encuadre, tamaño, luz).
  Acaba con «No text, no watermark».
- **Un objeto dibujado en perspectiva que cambia de estado** (algo que se cierra, una puerta que se abre) se pide a
  Qwen ya cambiado y en su sitio («close the instrument»), y en la escena una imagen se funde con la otra. Girar o
  deformar un recorte de la lámina no funciona: el objeto salía deforme, con el mecanismo por fuera.
- **Lo que queda medio tapado junto a una pieza se lee como parte de ella.** Un nudo de la madera pegado al objeto
  cerrado salió como una «aleta» gris. Mira los bordes de lo que cambió, no solo el objeto.

**El hueco de una pieza separada.** Cuando `obrero.separa` saca con SAM una pieza que se va a mover, la imagen se queda
con un hueco detrás. Hay tres formas de rellenarlo, y cada una salió bien en un caso distinto:

| Opción | Qué hace | Cuándo |
|---|---|---|
| `rellena_base=True` | pinta el hueco con lo que lo rodea (Telea, de OpenCV) | huecos pequeños que no se destapan. En una cortina que se mecía asomaba como una sombra borrosa |
| `relleno=<imagen>` | toma el hueco de la misma lámina sin la pieza: una edición de Qwen ampliada con `obrero.fondo`, del mismo tamaño | lo que deja ver el fondo al moverse. Es lo que arregló la cortina |
| `relleno_desplazado=(dx, dy)` | copia el hueco de la misma imagen a esa distancia, como el tampón de clonar | una textura que se repite al lado. Quitó un nudo de la madera copiando la mesa a 180 px a su derecha; a 110 px copiaba otra marca de tinta |

**Lo que se mueve se separa entero**: la parte de la cortina que SAM no cogió se quedó quieta mientras el resto se
mecía.

**En el formato «láminas», mover piezas está descartado.** El dibujo en perspectiva se deforma, y el hueco se ve
aunque se rellene. Estas herramientas siguen en el motor para otros formatos; en «láminas» no se plantean sin que el
usuario lo pida sabiendo esto.

## 7. Lo que el motor todavía no hace

Díselo al usuario cuando el plan lo necesite, en vez de rodearlo:

- **No hay fábrica de fondos.** Un fondo derivado de otro se pide con un `Activo` escrito a mano (referencia y lienzo
  aparte); uno de texto necesita otro workflow. Un plano cercano de un sitio que ya existe se saca recortando el fondo
  grande por geometría.
- **Una variante de una postura de la biblioteca** no tiene fábrica: `variante` parte de un activo del mismo lote, y los
  crudos de la biblioteca no están en el repositorio (su `procedencia.json` dice dónde están).
- **Los tiempos**, para planear el lote: una hoja, 146 s; una postura, 103 s; un recorte, de 4 a 10 s; una separación
  con SAM, 7 s. Todo en serie, con la GPU sola.
