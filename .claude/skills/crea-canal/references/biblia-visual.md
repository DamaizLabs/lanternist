# La capa de escena de un canal

Qué necesita un canal para que el motor de escena ponga en pantalla sus episodios, quién decide cada cosa y cómo se
comprueba. El canal de ejemplo enseña la capa más pequeña que funciona, la de un canal en «láminas»
(`canales/example/escena/`). Un canal con personajes necesita mucho más, y Lanternist todavía no trae una capa de
partida para él.

## Contenido

1. Qué es y para qué sirve
2. Lo que se decide con el usuario
3. Lo que se construye
4. Lo que el motor todavía no hace
5. Cómo se comprueba

## 1. Qué es y para qué sirve

Un episodio del motor de escena se escribe con el lenguaje del motor (`lib/escena/`, contado en
`docs/scene-script.md`). Pero todo lo que lo hace de ESTE canal vive en el canal, y sin defecto:

- **la capa de escena**, `canales/<id>/escena/`: un paquete de Python que el motor carga como `escena_del_canal`. En
  «láminas» basta con su hoja de estilo. Con personajes lleva además los personajes, los sets, la disposición de lo
  que sale en pantalla, la apertura y el cierre;
- **la biblia**, solo con personajes: las hojas de personaje y los lienzos de referencia, de donde sale toda postura
  nueva, para que los personajes sean los mismos en todos los episodios;
- **la biblioteca**, solo con personajes: las imágenes ya recortadas que los episodios reutilizan, cada una con su
  procedencia. Puede nacer vacía: lo que genera cada episodio entra en ella al pasar su primera revisión;
- **el bloque `escena` del perfil**: el ritmo, las pausas, el troceo de la narración, el karaoke, el reparto y, en
  «láminas» o «pizarra», el bloque de su formato.

Sin el bloque, el pipeline no puede crear el episodio de un run de escena (`lib/escena/episodio.py` lo exige al
empezar). Sin la capa, la etapa `activos` para. **Esta skill no pone en escena ningún episodio**: eso es
`pone-en-escena`, dentro de `produce-semana`.

## 2. Lo que se decide con el usuario

Se anota en `canales/<id>/decisiones.md`, campo a campo, con una propuesta y su motivo. Son decisiones de identidad.

### En todos los formatos

- **El CSS del canal**: las tipografías (las de `datos/escena/fuentes/`, u otras con licencia de redistribución y el
  sí del usuario), el fondo y el color de cada hablante en el karaoke (`.w.h-<id>`). Nada remoto y nada de
  `mix-blend-mode`: `lib/escena/compone.py` para si los encuentra. **Una sola paleta de hablantes**: el color de cada
  uno en el CSS es el mismo que en `perfil.json → subtitulos.personajes`.
- **La apertura y el cierre**, si los quiere: el título de entrada y el CTA de suscripción con campana
  (`lib/escena/cta.py`). El canal de ejemplo no lleva ninguno de los dos, y es una decisión, no un olvido.
- **El bloque `escena` del perfil**, clave a clave, con su `_por_que_` (§3).

### En «láminas»

- **El bloque `escena.laminas`**: el zoom mínimo y máximo, lo que dura una toma, la transición, las transiciones que
  no quiere y las fuentes de los rótulos. La tabla, con los valores del canal de ejemplo, está en `docs/formats.md`;
  el significado de cada clave, en `lib/escena/laminas.py → AJUSTES`.
- `camara_en_mano: 0` en el bloque común: una cámara que tiembla mete en el cuadro el borde de la lámina.

### En «personajes» (en preparación)

- **¿Tiene personajes fijos?** Si los tiene: su id, su nombre en el guion, su descripción canónica en inglés (la
  misma siempre, sin sinónimos), su altura relativa a la del personaje de referencia y las vistas de su hoja (de
  frente y de perfil). Si no tiene, como un museo sin guía, no hay hojas: la biblia son sets y objetos.
- **Los sets**: los sitios que se repiten en el canal, con su suelo (dónde se puede pisar) y su escala (cuántos px
  mide en ese fondo la unidad de altura).
- **El estilo de las figuras** para Qwen-Image-Edit (`lib/escena/activos.py → Estilo`: su prefijo, la frase de «mismo
  estilo» y la de «conserva»). Sale del prefijo del workflow del paso 2b, sin nada del fondo ni de la escena.
- **La disposición de lo que sale en pantalla**: dónde van las tarjetas, los chips y los gritos.

### En «pizarra» (en preparación)

Los colores de la tiza y de la pizarra, la textura de la tiza, la letra y dónde van los títulos. Las claves de
`escena.pizarra` están en `lib/escena/pizarra.py → AJUSTES`, con su tabla en `docs/formats.md`. Su contrato de
prompt pide dibujos sin letras ni números: el texto lo escribe el código, y las cifras salen de las fuentes del
episodio o de una cuenta, nunca del modelo de imagen.

## 3. Lo que se construye

### La capa en «láminas»

La del canal de ejemplo, con los valores de este canal:

| Fichero | Qué lleva |
|---|---|
| `__init__.py` | exporta `CSS`, la ruta de `estilo.css` |
| `estilo.css` | la letra y el color del karaoke, el fondo, el negro de entrada y salida y el color del papel de la transición |
| `apertura.py`, `cierre.py` | opcionales: los rótulos a tinta (el nombre del canal y el título del episodio) y el CTA |

### La capa en «personajes» (en preparación)

**Hoy no viene hecha.** Construirla es programación: se propone al usuario y espera su go (§4). Esta es la forma que
tiene que tener, la del primer canal que produjo en este formato:

| Fichero | Qué lleva |
|---|---|
| `__init__.py` | exporta `CSS` (la ruta de `estilo.css`) y los módulos de la capa |
| `personajes.py` | las alturas, el `Estilo` y los `Personaje` del canal |
| `lugares.py` | los sets con su suelo y su escala, registrados con `Guion.fondo`, y los sitios medidos en ellos |
| `ayudas.py` | los envoltorios de los ayudantes del motor con la disposición y el sonido del canal |
| `apertura.py`, `cierre.py` | el título de entrada; las pausas, el cierre y el CTA |
| `macros.py` | los movimientos que se repiten; nace vacío o casi, y crece con los episodios |
| `estilo.css` | el estilo del canal |
| `canales/<id>/escena/biblia/` y `canales/<id>/escena/biblioteca/` | las hojas y los lienzos; las figuras recortadas de las hojas, con `catalogo.json`, `indice.json` y `procedencia.json` |

### El bloque `escena` del perfil

La lista exacta de claves la da `lib/escena/ajustes.py → CAMPOS`, y su docstring explica cada grupo. Tres se derivan
y no se eligen:

- `cues.max_palabras` y `cues.max_caracteres` son el troceo del `.srt` del canal: los cues del motor de escena son
  también las líneas de su `.srt`. `max_palabras` es su `subtitulos.max_palabras_por_linea`, y `max_caracteres` lo
  que `lib/subtitulos.py → caracteres_por_linea` le da con su cuerpo y sus márgenes.
- `karaoke.conjunciones` y `karaoke.no_cierran` dependen del idioma del canal.
- `franja_karaoke_y` depende del CSS: es dónde empieza el karaoke en pantalla.

Las magnitudes de `movimiento` (el balanceo al andar, el rebote al hablar, la respiración…) son un gusto del canal, y
cuentan sobre todo con personajes. Las del canal de ejemplo (`canales/example/perfil.json → escena.movimiento`) se
pueden proponer como punto de partida si el usuario quiere, y se dice así en su `_por_que_`.

## 4. Lo que el motor todavía no hace

- **No trae una capa de partida para «personajes» ni para «pizarra»** (`docs/formats.md`, «In preparation»). Un
  canal en uno de esos formatos no produce hasta tenerla. Construirla es programación: se propone al usuario, con lo
  que haría falta y sin prometer tiempos, y espera su go.
- **No hay orden que monte la biblia de un canal nuevo.** Las piezas existen en `lib/escena/activos.py` (`hoja`,
  `genera` y `prepara_lienzos`, con las carpetas como parámetro), y el obrero recorta (`lib/escena/obrero.py`).
  Escribir esa orden es parte de construir la capa.
- **No hay fábrica de fondos**: un set nuevo necesita su camino, y se decide con el usuario.

## 5. Cómo se comprueba

Sin producir nada:

```powershell
.venv\Scripts\python -c "import json,sys; sys.path.insert(0,'.'); from lib.escena import ajustes; ajustes.exige(json.load(open('canales/<id>/perfil.json', encoding='utf-8'))); print('bloque escena completo')"
.venv\Scripts\python -c "import sys; sys.path.insert(0,'.'); from pathlib import Path; from lib.escena.episodio import carga_canal; print(carga_canal(Path('canales/<id>')).CSS)"
.venv\Scripts\python -m pytest -q tests/test_capas.py tests/escena
```

La primera dice todo lo que le falta al bloque de una vez. La segunda carga la capa. La tercera comprueba que nada
del canal se ha colado en `lib/` y que el motor sigue en verde. La prueba de verdad de la capa es el primer episodio,
que pone en escena `pone-en-escena` dentro de `produce-semana`.
