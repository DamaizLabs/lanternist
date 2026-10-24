# El lenguaje de escena del motor

Referencia para escribir `puesta(ep)`, los tramos y `activos(ep)`. Todo sale del código de `lib/escena/`. La guía
pública, más corta y en inglés, es `docs/scene-script.md`. **Si algo de aquí no cuadra con el código, manda el
código**: las listas cerradas viven en `lib/escena/compone.py` y `lib/escena/escena.py`, y el guion para con un mensaje
claro si usas un nombre que no existe.

## Contenido

1. El contrato del guion
2. Tiempos: las anclas
3. Sets, planos y cámara
4. Actores, claves y eventos
5. Elementos y ayudantes
6. Sonido y transiciones
7. Lo que la etapa `escena` hace sola, y lo que no
8. Mallas
9. Las listas cerradas

## 1. El contrato del guion

El guion vive en `canales/<id>/datos/escenas/<run>/escena.py` (contrato completo en `lib/escena/episodio.py`). Define:

- **`puesta(ep) -> Puesta`**, obligatoria. `Puesta(guion, css, franja_karaoke_y, momentos=None, assets={})`:
  - `guion`: el `Guion` escrito sobre `ep.linea()`;
  - `css`: el CSS del canal (`escena_del_canal.CSS`);
  - `franja_karaoke_y`: dónde empieza el karaoke en pantalla; sale del perfil, `ep.escena["franja_karaoke_y"]`;
  - `momentos`: `[(segundo, etiqueta)]`, los fotogramas de la parada 2;
  - `assets`: lo que pida el CSS o el guion y no esté en el catálogo, con su procedencia en el run.
- **`activos(ep) -> Lote`**, opcional. `Lote(activos, personajes, elegidas={}, extra=(), biblioteca=())`. Sin esta
  función el episodio no genera nada ni trae nada de la biblioteca.

Lo que da el `Episodio`:

| Qué | Para qué |
|---|---|
| `ep.linea()` | la línea de tiempo: láminas de voz, cues, palabras con su tiempo, grupos de karaoke. Necesita la etapa `alinea` |
| `ep.catalogo()` | las imágenes que ya están en el run (tras `activos`) |
| `ep.biblioteca()` | el catálogo de la biblioteca del canal, solo para leer |
| `ep.escena` | el bloque `escena` del perfil, ya validado |
| `ep.perfil` | el perfil entero, para lo que el guion lee fuera de `escena`: el nombre del canal, su CTA (`formato.composicion`) |
| `ep.idioma`, `ep.run_dir`, `ep.canal()` | el idioma del texto en pantalla, el run y la capa del canal |

La carpeta del episodio se carga como un paquete, así que el guion se parte en ficheros con `from . import tramos`. La
capa del canal se importa siempre con el mismo nombre, sea cual sea el canal: `from escena_del_canal import lugares`.

Esqueleto de un episodio con personajes (el de «láminas» es el `escena.py` del canal de ejemplo,
`canales/example/datos/escenas/2026-10-15_115251_how-does-a-zip-work/escena.py`):

```python
from escena_del_canal import CSS, cierre, dibujos, lugares
from lib.escena import anclas
from lib.escena.episodio import Episodio, Lote, Puesta
from lib.escena.escena import Guion

from . import tramos

MOMENTOS = [(2.0, "Título de entrada"), (97.0, "Pausa: capítulo 2 y repaso")]
REUTILIZA = ("fondo_calle", "fondo_acera", "nora_frente", "papa_explica")  # del plan


def construye(ep: Episodio, catalogo: dict) -> Guion:
    linea = ep.linea()
    marcas = anclas.usa(linea)  # desde aquí valen C(), F() y P() sueltas
    g = Guion(
        titulo=tramos.TITULO,
        idioma=ep.idioma,
        escena=ep.escena,
        catalogo=catalogo,
        iconos=dibujos.iconos(),
        linea=linea,
    )
    lugares.registra(g)  # los sets del canal
    for n in range(1, len(linea.laminas) + 1):
        getattr(tramos, f"tramo{n}")(g)
    g.avisos.extend(marcas.avisos)  # los avisos de P() llegan así a la parada 2
    return g


def puesta(ep: Episodio) -> Puesta:
    g = construye(ep, ep.catalogo())
    return Puesta(guion=g, css=CSS, franja_karaoke_y=ep.escena["franja_karaoke_y"], momentos=sorted(MOMENTOS))


def activos(ep: Episodio) -> Lote:
    return Lote(activos=(), personajes={}, biblioteca=REUTILIZA)
```

## 2. Tiempos: las anclas

Un guion no escribe segundos: escribe «cuando se dice esta palabra». Si cambian las pausas o se regenera la voz, todo se
recoloca solo. El guion por partes (`<run>/revision/guion-por-partes.md`) da el número de cada cue.

| Ancla | Qué da |
|---|---|
| `C(n)`, `F(n)` | el instante del vídeo en que empieza y acaba el cue n |
| `P(n, "palabra", k=0)` | el instante en que se dice esa palabra en el cue n (su aparición k). Si no está, la busca en los cues vecinos y deja un aviso |
| `HUECO(k)` | la pausa tras la lámina de voz k (de 0 a N−2), como `(inicio, fin)` |
| `cues_del_tramo(k)` | los cues de la lámina de voz k |
| `cue_con("texto")` | el último cue que contiene ese texto (el cierre del narrador, igual en todos los episodios) |

Se importan de `lib/escena/anclas.py` y solo funcionan tras `anclas.usa(linea)`.

## 3. Sets, planos y cámara

- **Un set** se registra una vez: `g.fondo(nombre, img=, suelo=, px_u=, decora=)`. `suelo` es un polígono en px del
  fondo, o `None` si no tiene suelo; `px_u` es cuántos px mide la unidad de altura del canal en ese fondo. Normalmente
  lo hace la capa del canal (`lugares.registra(g)`), no el episodio.
- **Un plano**: `g.plano(set, t0, t1, entra="corte", d=0.0, desenfoque=0.0, dir=None)`. Un plano que entra con
  transición se monta sobre el anterior, que sigue a la vista hasta que termina de entrar. `p.extra` es HTML fijo del
  plano (un velo de luz del CSS del canal).
  - **Las entradas de tinta** son las transiciones del formato «láminas» hechas entradas de plano. `cortina`
    descubre el plano con un degradado que avanza. `mancha`, `calado` y `viento` lo descubren donde un campo de gris
    pasa un umbral que sube (los campos, en `lib/escena/campos.py`). `papel` es un destello: un velo sube y baja
    mientras cambia el plano.
  - **`dir`** dice hacia dónde avanza el frente, y no tiene defecto. `cortina` pide `"derecha"`, `"izquierda"` o
    `"arriba"`; `viento`, `"derecha"` o `"izquierda"`; el `barrido` admite `1`, `-1` o nada. Las demás entradas no
    llevan `dir`, y el guion para si se lo das.
  - **`papel` necesita** que el CSS del canal dé `background` a `.plano > .papel` (el canal de ejemplo le da el color
    del papel de sus láminas en `canales/example/escena/estilo.css`); sin eso la composición para. No es la transición
    de pantalla `papel` de `g.transicion` (`.tr.papel`), aunque se llamen igual.
- **La cámara**: `p.cam(t, cx, cy, z, tr, e="inout", sigue=None, libre=False)`.
  - `z = 1` es el fondo entero a lo ancho; `tr` (los segundos para llegar) es obligatorio.
  - `sigue=actor.id` centra la cámara en ese actor, y entonces `cx, cy` son el desplazamiento.
  - `libre=True` es un primer plano que corta una cabeza a propósito: el encuadre no lo abre y la comprobación de
    cabezas no lo cuenta.

## 4. Actores, claves y eventos

- **Un actor**: `g.actor(plano, posturas, x, y, escala=… o alto=…, pj=None, s=1.0, flip=0, z=None, padre=None, op=1.0,
  **rasgos)`.
  - `(x, y)` es su punto de apoyo (los pies) en px del fondo.
  - Su tamaño va por `escala` o por `alto` en unidades del set, uno de los dos. Un personaje se crea con el envoltorio
    de la capa del canal (en la capa con que se probó el formato, `persona(...)`), que calcula su escala con las
    alturas del canal.
  - Sin `z`, la profundidad sale de la y con que nace: `100 + y/8`. Quien pisa más abajo tapa a quien está detrás.
  - `padre=otro`: va pegado a otro actor. Lo que se lleva en la mano y lo que va montado en algo son hijos.
- **Una clave**: `a.clave(t, tr=0.0, e="inout", **campos)`. Los campos llegan a su valor entre `t` y `t + tr`. Los que
  no se tocan siguen como estaban.
  - `post` cambia de postura con el fundido del perfil (`escena.fundido`); `fp` da otro fundido para esa clave, y
    `fp=0` es un cambio de golpe.
  - Todo es función pura del tiempo: el orden en que se escriben las claves da igual.
  - Dos claves en el mismo instante: solo cuenta la transición de la última, y queda un aviso.
- **Un evento**: `a.ev(tipo, t, d, **kw)` es un movimiento pasajero encima de la pista. Sus magnitudes, si no se dan,
  salen del perfil (`escena.movimiento.eventos`). `salto` exige `h`.

## 5. Elementos y ayudantes

- **Un elemento**: `g.el(capa, html, x, y, w, h, t0, t1, clase="", z=0, movible=False, tapa_caras=False, grito=False,
  **anim)`.
  - Va centrado en `(x, y)`. `capa` es `"pantalla"` (px de pantalla) o el id de un plano (px de su fondo).
  - `anim`: `entra`, `sale`, `bucle` y su `amp`, y `sigue=actor.id` para pegarlo a un actor (el vapor del café).
    `trazo=True`, con `trazo_t` y `trazo_d`, dibuja los `<path class="trazo">` de su SVG de principio a fin: así se
    escriben las letras a tinta. `campana=True`, con `campana_t` y `campana_p`, balancea la `.campana` que lleva
    dentro: así se mueve la del CTA. La lista completa está en §9.
  - El estilo va por clase y lo pinta el CSS del canal. El HTML no puede llevar `<script>` ni atributos `on…`, y nada
    remoto: la composición para.
  - `movible=True` deja que el encuadre lo aparte de una cara; `tapa_caras=True` es un elemento que tapa caras a
    propósito (el tablero final).
- **Los ayudantes del motor** (`lib/escena/ayudas.py`: `tarjeta`, `chip`, `numero`, `verbo`, `nota`, `contador`,
  `capitulo`, `repaso`, `etiqueta`, `efecto`, `grito`, `lupa`, `tablero`) ponen la estructura y exigen toda la
  disposición: sitio, tamaño, animación y sonido. **En un episodio se usan los envoltorios de la capa del canal**, que
  ponen su disposición (`escena_del_canal.ayudas.tarjeta(g, "bike", "bici_entera", P(8, "bike"), articulo="a")`).
- **Tres mecanismos del motor que el canal llama con sus datos**:
  - **el CTA con campana**, `lib/escena/cta.py → pon`: el rebote, el latido, la campana desde «bell», sus campanadas y
    el clic. En un episodio se llama por el envoltorio de la capa del canal (por ejemplo, `cierre.cta`), que pone el
    banner, dónde va y cuándo sale;
  - **las letras a tinta**, `lib/escena/tinta.py`: saca el contorno de cada letra de una fuente de la biblioteca del
    motor (`datos/escena/fuentes/`), para que `trazo` lo dibuje y después se rellene. El CSS del canal tiene que
    declarar esa fuente con `@font-face`: así entra en el run con su licencia. Lo usan los rótulos que la capa del
    canal tenga;
  - **la cámara sobre láminas enteras**, `lib/escena/laminas.py`: el formato «láminas», en `formato-laminas.md`.
- `punto_de_postura(escala, postura, punto, s=, flip=)` lleva un punto medido en la rejilla de una postura a px del
  fondo, respecto al apoyo del actor. Una capa con personajes suele envolverlo para no repetir la escala de cada
  personaje (en la capa con que se probó el formato, `punto_de_postura(g, px_u, pj, postura, punto)`).

## 6. Sonido y transiciones

- `g.sfx(nombre, t, volumen, dur=None)`: un efecto de la biblioteca del motor (`datos/escena/sfx/`, con su
  licencia). `dur` lo corta antes de que acabe.
- `g.suena({"nombre", "volumen", "desfase_s"}, t)`: lo mismo, con los sonidos que declara la capa del canal.
- `g.transicion(tipo, t, d, sonido=…)`: una cortina de pantalla completa, por encima de todos los planos. `sonido` es
  obligatorio: `None` o uno. Las entradas de tinta de §3 no son esto: van en el plano que entra, y `en_seco` no las
  cuenta como transiciones.
- La narración y el lecho de música **no se escriben**: los pone la etapa `escena` desde la voz del run y el perfil.

## 7. Lo que la etapa `escena` hace sola, y lo que no

Hace sola, en este orden: `encuadre.corrige` (abre las claves de cámara que cortarían una cabeza con la cámara quieta),
`encuadre.aparta_de_caras` (mueve los textos `movible` que tapan una cara, sin pisar la franja del karaoke), el
sonido, las seis comprobaciones, la composición (que para ante un nombre desconocido, una referencia remota o código
en el HTML) y un fotograma por momento.

No hace, y lo pone la capa del canal desde `puesta(ep)` si el canal lo tiene:

- colocar cada grito junto a la cabeza de quien lo dice (en la capa con que se probó «personajes», `gritos.coloca`,
  que se llama sobre el GUION ya corregido);
- revisar la capa didáctica y dejar sus avisos (allí, `didactica.revisa(g)`);
- recortar lo de pantalla al empezar cada pausa (allí, `cierre.recorta_en_pausas`).

## 8. Mallas

El motor sabe deformar tres tipos de malla en WebGPU (`pierna`, `cadena`, `cuadrupedo`) si el guion lleva un `rig`
(`Guion(rig=…)`). **Ningún episodio las usa todavía**: la animación es rígida, con recortes que se mueven enteros y
piezas que se mecen aparte, que es lo que se eligió en el primer episodio con personajes. Usarlas en un episodio se
plantea antes al usuario.

## 9. Las listas cerradas

| Qué | Valores |
|---|---|
| Curvas (`e`) | `lineal`, `suave`, `inout`, `sale`, `entra`, `rebote`, `elastico`, `acelera` (p²: arranca despacio) y `frena` (1 − (1 − p)²: llega despacio). Las dos últimas son `ease_in` y `ease_out` de los movimientos del formato «láminas» |
| Campos de una clave | `x`, `y`, `s`, `r`, `op`, `flip`, `post`, `giro`, `ancho`, `dz`, y `fp` de esa clave |
| Rasgos de un actor | `anda`, `v_anda`, `paso`, `bote`, `charla`, `respira`, `fase`, `rueda`, `gira`, `hereda`, `pieza`, `pisa` |
| Eventos | `salto` (con `h`), `risa`, `tiembla`, `ladea`, `bote`, `asiente`, `bombea`, `estira`, `menea` |
| Entrada de un plano | `corte`, `funde`, `barrido`, `iris`, `cortina`, `mancha`, `calado`, `viento`, `papel` |
| `dir` de una entrada de plano | `cortina`: `derecha`, `izquierda`, `arriba`; `viento`: `derecha`, `izquierda`; `barrido`: `1`, `-1` o nada; las demás, ninguno |
| Entrada de un elemento | `pop`, `sube`, `cae`, `mancha`, `crece`, `nada`, `fade` |
| Salida de un elemento | `pop`, `baja`, `nada`, `fade` |
| Bucle de un elemento | `late`, `flota`, `tiembla`, `gira`, `balancea`, `deriva`, `vuela` |
| Animación de un elemento (`anim`) | `entra`, `sale`, `bucle`, `amp`, `di`, `ds`, `trazo`, `trazo_t`, `trazo_d`, `contador`, `aguja`, `aguja_v`, `campana`, `campana_t`, `campana_p`, `sigue` |
| Transiciones | `iris`, `luz`, `destello`, `papel`, `puntos`, `barras` |
| Efectos de sonido del motor | los ficheros de `datos/escena/sfx/`: `chime`, `click-soft`, `notification`, `ping`, `pop`, `riser`, `sparkle`, `whoosh`, `whoosh-short` |
