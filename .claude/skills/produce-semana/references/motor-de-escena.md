# Producir un episodio con el motor de escena

El motor de escena es el que hace los vídeos de Lanternist. El vídeo sale de una **puesta en escena** (planos, cámara,
figuras que se mueven y elementos en pantalla) escrita como código y renderizada con HyperFrames. Cómo se escribe ese
guion de escena: `docs/scene-script.md` y la skill `pone-en-escena`.

**Cada canal produce en un formato del catálogo** (`docs/formats.md`), y el formato cambia la mitad del trabajo:

- `laminas`, **listo para producir** (el canal de ejemplo): la cámara recorre cada lámina entera, con transiciones de
  tinta, karaoke y rótulos escritos a tinta. El canal lo declara en `perfil.json → escena.laminas`;
- `personajes`, **en preparación**: personajes recortados que andan, hablan y cogen cosas dentro de sus sets;
- `pizarra`, **en preparación**: una pizarra que se llena por partes al ritmo de la voz, sin karaoke. Sus subtítulos van
  solo en los `.srt`. El canal lo declara en `perfil.json → escena.pizarra`.

«En preparación» quiere decir que el motor ya los ha producido, pero no trae la capa de escena de partida que necesita
un canal nuevo. Lo que este documento dice de ellos sirve cuando un canal tenga la suya.

## Contenido

1. Qué hace cada etapa
2. La secuencia de un episodio
3. Las dos paradas en una semana de varios episodios
4. Al entregar
5. Rehacer algo después del render
6. Lo que cuesta cada etapa

## 1. Qué hace cada etapa

- **Las láminas se generan en los tres formatos**, y la miniatura sale de una de ellas. En `laminas` son la imagen del
  vídeo; en `personajes`, el guion gráfico de la puesta en escena; en `pizarra`, cada una es una pizarra que `activos`
  separa en piezas.
- **`alinea`, `activos`, `escena` y `render` hacen el vídeo.** El estado del run guarda también la etapa `assembly`,
  porque ahí deja `render` la ruta del vídeo final, y de ahí la leen la subida y el panel.
- **El usuario para el episodio dos veces**: tras `activos`, para ver las imágenes nuevas (parada 1), y tras `escena`,
  para ver la hoja de fotogramas antes del render (parada 2).
- **La biblioteca del canal crece sola.** Al pasar la parada 1, las imágenes nuevas que el usuario aprobó y que usa el
  guion entran en `canales/<id>/escena/biblioteca/` con su procedencia, y el episodio siguiente las trae en vez de
  generarlas. En `laminas` y en `pizarra` no crece: lo que sale de las láminas (las ampliaciones y, en `pizarra`, sus
  piezas) es de cada episodio, y de la biblioteca solo llegan el banner y la campana del aviso de suscripción.
- **La puesta en escena la escribe Claude** con la skill `pone-en-escena`, y su guion vive en git, en
  `canales/<id>/datos/escenas/<run>/`.
- **`--run-all` reanuda**: salta las etapas ya hechas y se detiene en la siguiente parada.

## 2. La secuencia de un episodio

```
images → tts → alinea → [traducción del .srt] → activos ⏸ parada 1 → escena ⏸ parada 2 → render → thumbnail → upload
```

La traducción va entre corchetes porque no es una etapa del pipeline: la hace Claude con un script, y solo en los
canales que la declaran (paso 3b).

1. **Crear el run** y copiar su `slides.json`. La orden imprime la ruta donde irá su guion de escena:
   ```powershell
   .venv\Scripts\python pipeline.py --canal <id> --create --title "<título>"
   ```
2. **Los hablantes**, si el canal tiene diálogos. `slides.json → hablantes` dice quién dice cada tramo, y de ahí salen el
   color del karaoke y quién rebota al hablar. `scripts/hablantes.py <run>` los propone (con `$env:CANAL_ACTIVO='<id>'`
   en el proceso), y los que deja sin atribuir se resuelven mirando el guion.
3. **Láminas, voz y alineación**, una etapa cada vez y cada una como proceso independiente, porque usan la GPU:
   `--stage images`, `--stage tts` y `--stage alinea`. No lances `--run-all` todavía: llegaría a `activos` y pararía,
   porque el guion de escena no existe.

   **3b. La traducción del `.srt`, solo si el canal la declara** en `perfil.json → subtitulos.traducciones` (por
   ejemplo, `["es"]`; el canal de ejemplo no traduce). La hace Claude, en esta sesión: el guion ya lo escribe Claude,
   así que no sale nada nuevo del PC. No usa la GPU. Son dos órdenes, con el canal del run en el entorno del proceso,
   como en el paso 2:
   ```powershell
   $env:CANAL_ACTIVO='<id>'
   .venv\Scripts\python scripts/traduce_srt.py saca --run-id <run>
   #   Claude traduce canales/<id>/videos/<run>/subtitulos/cues.<origen>.json y lo guarda como cues.<idioma>.json
   .venv\Scripts\python scripts/traduce_srt.py escribe --run-id <run> --idioma <idioma> --traduccion canales/<id>/videos/<run>/subtitulos/cues.<idioma>.json
   ```
   - **Qué se traduce**: solo el `texto` de cada cue. `n`, `inicio`, `fin` y `origen` no se tocan, porque la traducción
     usa los tiempos del `.srt` de origen. Una línea más larga que `max_caracteres_por_linea` se parte en dos con `\n`,
     y un cue lleva dos líneas como mucho. El propio JSON lo recuerda en `_que_hacer`.
   - **Cómo**: cada cue se ve mientras suena su trozo de voz, así que su traducción dice lo de ese trozo, aunque la frase
     siga en el cue siguiente. Lee los cues de alrededor para entender la frase, pero no pases palabras de un cue a otro.
   - **Si `escribe` falla**, no escribe nada y lista todos los fallos a la vez: corrige el JSON entero y vuelve a
     lanzarlo.
   - **La subida lo exige antes de preparar nada** (`lib/traduccion.exige_al_dia`). Para si falta una traducción
     declarada, si el `.srt` de origen cambió después de traducirlo o si la traducción se tocó después de escribirla.
     Así que **si se repite `alinea`, se repite la traducción**.
   - La declaración de IA añade sola su línea, y el LEEME de `subir-al-canal/` lista un `.srt` por idioma, que el
     usuario adjunta a mano en Studio.
4. **Parada 1**, con `pone-en-escena`: el plan, las imágenes nuevas (`activos(ep)`), `--stage activos`, la elección de
   semillas y la página para el usuario.
   - **En `laminas` no hay plan ni imágenes nuevas**: `--stage activos` amplía las láminas del run y trae el aviso de
     suscripción de la biblioteca, y la parada 1 se pasa igual (`pone-en-escena`, `references/formato-laminas.md`).
   - **En `pizarra` tampoco**: `--stage activos` amplía cada lámina ×2, la separa en tiza y piezas y trae el aviso de
     suscripción. La parada 1 son las hojas numeradas (`<run>/revision/pizarra-pizarra_NN.png`), con cada pizarra y sus
     piezas. Si el usuario rechaza un dibujo, se reescribe su prompt con el contrato del canal, se rehace esa lámina y
     se repite `activos` (`pone-en-escena`, `references/formato-pizarra.md`).
5. **Parada 2**, con `pone-en-escena`: la puesta en escena en seco, `--stage escena`, su revisión propia y la hoja de
   fotogramas para el usuario. En cuanto construye la puesta, `--stage escena` mete en la biblioteca del canal las
   imágenes nuevas de la parada 1 que usa el guion. Lo dice su salida («Biblioteca del canal: N imagen(es) nueva(s)…»)
   y la página de la parada 2, que lista también las que no entraron y por qué.
6. **Render**, con el visto bueno del usuario: `--stage render`, con la GPU sola. Lo que tarda en cada formato está en
   el §6.
7. **Miniatura y subida**: `--run-all`, que reanuda tras el render. Deja el vídeo listo para subir a mano en
   `subir-al-canal/`, o el borrador privado si la subida por la API está encendida (`docs/youtube-upload.md`).

Cómo se lanza una etapa de GPU como proceso independiente de Windows:

```powershell
$p = Start-Process -FilePath .venv\Scripts\python.exe -ArgumentList 'pipeline.py','--canal','<id>','--run-id','<run>','--stage','escena' -PassThru -WindowStyle Hidden -RedirectStandardOutput logs\escena.log -RedirectStandardError logs\escena.err
$p.WaitForExit()
```

El porqué: con ComfyUI cargando el modelo, la RAM libre baja, y el vigilante de tareas del agente mata una tarea de fondo
aunque sobre memoria. Un proceso de Windows no depende del agente. Se espera mirando el log y el PID.

Al parar, el pipeline deja `status: en_parada` en el estado del run y abre la página de revisión. `--run-all` nunca
pasa una parada: solo recuerda dónde está y vuelve a abrir la página.

## 3. Las dos paradas en una semana de varios episodios

- **Cada parada es del usuario y no se salta.** Se sigue con `--stage escena` o `--stage render` solo con su visto bueno.
- **Una parada por episodio.** Cada episodio llega a su parada, se le enseña al usuario y se espera su visto bueno antes
  de seguir con ese episodio. Mientras un episodio espera no ocupa la GPU, así que el siguiente puede avanzar por sus
  etapas, pero cada uno se enseña cuando llega a la suya.
- **No se juntan las paradas de la semana** en una sola llamada con todas las páginas: cada visto bueno es sobre un
  episodio concreto. No lo ofrezcas, tampoco «por esta semana».
- **Lo que se renderiza es lo que vio.** `render` se niega si el guion o la composición cambiaron tras la parada 2. Si
  algo cambia después de su visto bueno, se vuelve a pasar por `--stage escena` y se le enseña lo que cambió.
- **Una corrección tras el render cuesta otro render** y otra mirada suya: por eso la mirada va antes.

## 4. Al entregar

El material pesado de un run entregado se puede sacar del repositorio, a mano. Son las carpetas del run
`<run>/slides/`, `<run>/audio/`, `<run>/activos/`, `<run>/activos-trabajo/`, `<run>/biblioteca/`,
`<run>/composicion/`, `<run>/sonido/`, `<run>/revision/` y `<run>/subir-al-canal/`. En el repositorio se queda el
expediente: `assets.json`, `montaje.json`, `slides.json`, los `generacion-*.json` y los `.srt`. El guion de escena ya
está en git. **Un run en curso no se mueve**: quitarle `slides/` le quita las láminas al render.

**Las imágenes nuevas del episodio no se pierden al archivar**: entraron en la biblioteca del canal al pasar la
parada 1 (`lib/escena/biblia.py → incorpora`), y la biblioteca está en git. Antes de archivar, comprueba dos cosas:

- **que la biblioteca va en el commit del episodio**, junto a su guion de escena:
  `git status canales/<id>/escena/biblioteca/` enseña las imágenes y los tres JSON que cambiaron;
- **lo que no entró**, si algo. La salida de `--stage escena` y la página de la parada 2 lo listan con su motivo: otra
  imagen con el mismo nombre de otro episodio, o una procedencia incompleta. Eso se queda solo en el run: si el
  siguiente episodio lo necesita, díselo al usuario al entregar.

El crudo de cada imagen (`<run>/activos/crudo/`) se archiva con el run: la ficha de la biblioteca guarda su sha256, su
prompt y su semilla, y dice dónde estaba.

**En `laminas` y en `pizarra` no hay imágenes nuevas que guardar**: las ampliaciones y las piezas son del episodio, se
archivan con el run y se rehacen desde sus láminas.

## 5. Rehacer algo después del render

Solo se rehace lo que rompe el episodio (`SKILL.md`, paso 8). Lo cosmético se anota en el LEEME.

**Cómo se regenera una lámina.** Arregla el prompt y regenera **solo esa**: borra su PNG y relanza `--stage images`, que
salta las que existen. Después se relanza lo que falta: si cambia la composición, se vuelve a pasar por la parada 2
(§3). Para saber qué prompt
cambió, compara el de escena, el del `slides.json`: `slides/generacion-imagenes.json` lo guarda con el prefijo de estilo
del workflow, y comparar en bruto dice que cambiaron todas.

**Si una lámina sigue mal tras dos regeneraciones**, el defecto ya no está en el prompt, sino en lo que el modelo sabe
dibujar. Márcala en el LEEME y que decida el usuario.

**Con la subida por la API, un remontado deja dos borradores.** La subida es idempotente a propósito, así que subir el
remontado pide `--forzar-subida`. El borrador viejo no se puede borrar por la API: `videos.delete` exige el permiso
`youtube.force-ssl`, que da escritura total sobre la cuenta, y Lanternist no lo pide (`docs/youtube-upload.md`,
«Permissions»). Dile al usuario los dos identificadores y cuál es el bueno, para que borre el otro en Studio. No
propongas ampliar el permiso. Con la subida a mano no hay nada que hacer: el usuario sube el vídeo nuevo.

## 6. Lo que cuesta cada etapa

**En el canal de ejemplo**: un episodio de 54 s, con tres láminas, en `laminas`.

| Etapa | Coste | Dirección |
|---|---|---|
| Una lámina en ComfyUI | 94,8 · 97,7 · 90,8 s | `canales/example/datos/assets/<run>.json → assets[slides/slide-0N.png].detalle.segundos` |
| El vídeo final | 54,458 s | `canales/example/datos/assets/<run>.json → assets[subir-al-canal/final.mp4].detalle.duracion_s` |
| El render | 94,6 s, 1,74 veces lo que dura el vídeo | `canales/example/videos/<run>/montaje.json → cronometraje`, que escribe cada render |

**En episodios largos**, medido al construir el motor con una GPU de 8 GB. Sustitúyelas por las de los runs del usuario
en cuanto las haya:

| Etapa | Coste |
|---|---|
| La voz (Orpheus) | 36,4 min de reloj para 13,9 min de audio, en serie |
| La alineación de subtítulos | de 3 a 5 min por episodio, sin medir con cuidado: mídela antes de planificar con ella |
| La música (ACE-Step) | unos 10 min por episodio |
| La miniatura | unos 70 s |
| El render en `personajes` | 18 min para un episodio de 16 min |
| El render en `laminas` | 21 min para un episodio de 17 min |
| El render en `pizarra` | solo una muestra: 65,8 s de vídeo en 80,7 s. Un episodio entero está sin medir, y cada letra de la tiza son dos elementos: mídelo en el primero |
| Los tokens, y el tiempo de Claude y del usuario por episodio | sin medir todavía |
