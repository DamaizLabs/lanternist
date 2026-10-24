# Writing an episode's `escena.py`

Every episode that Lanternist renders has a **scene script**: a small Python module that says which shots the video
has, what each shot shows and what the camera does, anchored to the words of the narration. The pipeline turns it
into an animated HTML composition (HyperFrames) and renders that to MP4.

In practice Claude Code writes this file for you, guided by the `pone-en-escena` skill. This page explains what the
file contains, so that you can read it, review it and fix it by hand.

## Where it lives

```
canales/<channel>/datos/escenas/<run_id>/escena.py
```

It sits next to your channel's data and is tracked by git: it is text, and it is the record of how the episode was
staged. The run itself (images, audio, composition, video) lives in `canales/<channel>/videos/<run_id>/`, which git
ignores.

The episode folder is loaded as a package, so a long script can be split into several files and imported with
`from . import part2`. Your channel's scene layer (`canales/<channel>/escena/`: its CSS, its sets, its helpers) is
always imported under the same name, whatever the channel: `from escena_del_canal import ...`.

## The contract

The contract is defined in `lib/escena/episodio.py`. The module defines up to two functions, and both receive the
`Episodio` (`ep`) that the pipeline builds for the run:

| Function | Required | Returns |
|---|---|---|
| `puesta(ep)` | yes | a `Puesta`: the `Guion` of the episode, the channel CSS and where the karaoke starts on screen |
| `activos(ep)` | no | a `Lote`: the new images the episode needs. Without it, the episode generates nothing |

What `ep` gives you:

| Attribute | What it is |
|---|---|
| `ep.linea()` | the timeline: the voice slides, their cues, every word with its time, the karaoke groups. Needs the `alinea` stage |
| `ep.catalogo()` | the images already in the run (after the `activos` stage) |
| `ep.escena` | the `escena` block of your channel profile, already validated |
| `ep.perfil` | the whole channel profile |
| `ep.idioma`, `ep.run_dir`, `ep.canal_dir` | the on-screen language, the run folder and the channel folder |

`Puesta(guion, css, franja_karaoke_y, momentos=None, assets={})`:

- `guion`: the `Guion` written on top of `ep.linea()`;
- `css`: the path of your channel's stylesheet (colours, fonts, labels);
- `franja_karaoke_y`: the screen row, in px, where the karaoke starts. It comes from your profile
  (`ep.escena["franja_karaoke_y"]`);
- `momentos`: `[(second, label)]`, the frames shown to you at the second review stop.

## The language

Everything below lives in `lib/escena/escena.py` (the `Guion` and its pieces) and `lib/escena/anclas.py` (the
anchors). A name the engine does not know stops the script with a clear message: a typo never reaches the video.

### The `Guion`

```python
g = Guion(titulo=..., idioma=ep.idioma, escena=ep.escena, catalogo=ep.catalogo(), iconos={}, linea=ep.linea())
```

### Sets and shots (`Plano`)

- **A set** is a background image from the catalogue, registered once: `g.fondo("street", img="street", suelo=None)`.
  `suelo` is the floor polygon in background px, or `None` if the set has no floor.
- **A shot** shows a set between two instants: `p = g.plano("street", t0, t1, entra="funde", d=0.5)`. `entra` is how it
  comes in: `corte`, `funde`, `barrido`, `iris`, or one of the ink entrances (`cortina`, `mancha`, `calado`, `viento`,
  `papel`). Some of them need a direction, `dir`.
- **The camera** moves inside the shot: `p.cam(t, cx, cy, z, tr, e="inout")`. `(cx, cy)` is the centre in background
  px, `z = 1` shows the whole background width, and `tr` is the number of seconds it takes to get there.

### Actors (`Actor`)

An actor is any cut-out figure that moves: a character, a vehicle, an object.

```python
ana = g.actor(p, ["ana_standing", "ana_arms_up"], x=700, y=1200, escala=1.2, pj="ana")
ana.clave(P(3, "look"), 0.6, x=1000)  # walks to x=1000 in 0.6 s, when the narrator says "look"
ana.clave(P(3, "look"), 0, post="ana_arms_up")  # and switches pose at the same instant
ana.ev("risa", P(4, "laughed"), 0.8)  # a passing movement on top of its track
```

- `(x, y)` is where its feet are, in background px.
- `clave(t, tr, e, **fields)` moves it to new values between `t` and `t + tr`. The fields are `x`, `y`, `s`, `r`, `op`,
  `flip`, `post`, `giro`, `ancho` and `dz`. Keys are a pure function of time: their order does not matter.
- `ev(type, t, d)` is a passing movement: `risa`, `tiembla`, `ladea`, `bote`, `asiente`, `bombea`, `estira`, `menea`
  or `salto` (which needs `h`). Its strength comes from your profile (`escena.movimiento.eventos`).

### Anchors: time comes from the narration

A scene script never writes a bare second if it can avoid it. It writes "when this word is said", so that everything
moves by itself if the voice is generated again or the pauses change. Call `anclas.usa(linea)` once, and then:

| Anchor | Returns |
|---|---|
| `C(n)`, `F(n)` | the instant cue `n` starts and ends |
| `P(n, "word", k=0)` | the instant `word` is said in cue `n` (its `k`-th appearance). If it is not there, it looks in the neighbouring cues and leaves a warning |
| `HUECO(k)` | the pause after voice slide `k`, as `(start, end)` |
| `cues_del_tramo(k)` | the cues of voice slide `k` |

The cue numbers are in `<run>/revision/guion-por-partes.md`, which the `alinea` stage writes.

### Elements, sound and transitions

- `g.el(layer, html, x, y, w, h, t0, t1, clase="", **anim)` puts a piece of HTML on screen (`layer="pantalla"`) or
  stuck to a shot. Your channel CSS styles it through its class. No `<script>`, no `on…` attributes and nothing
  remote: the composition refuses them.
- `g.sfx(name, t, volume)` plays an effect from the engine library (`datos/escena/sfx/`).
- `g.transicion(type, t, d, sonido=...)` is a full-screen wipe above every shot. `sonido` is required: `None`, or
  the effect that plays with it.
- The narration and the music bed are not written here: the `escena` stage adds them from the run and your profile.

## A minimal episode in the "láminas" format

In the "láminas" (plates) format, each illustration of the run fills the screen and the camera travels across it, the
way a documentary films a still. Your profile declares the format with an `escena.laminas` block (zoom, shot length,
transitions), and `lib/escena/laminas.py` does the camera work. The scene script only connects the pieces. This example is run by the test suite
(`tests/escena/test_guia_del_guion.py`), so it stays in step with the code:

```python
"""Scene script of one episode in the "láminas" format."""

import json

from escena_del_canal import CSS
from lib.escena import anclas, laminas, obrero
from lib.escena.episodio import Lote, Puesta
from lib.escena.escena import Guion


def _slides(ep) -> dict:
    return json.loads((ep.run_dir / "slides.json").read_text(encoding="utf-8"))


def _set(numero: int) -> str:
    return f"lamina_{numero:02d}"


def activos(ep) -> Lote:
    """No new image: each slide of the run is upscaled so that the camera can get close without losing detail."""
    numeros = [int(s["slide_number"]) for s in _slides(ep)["slides"]]
    ampliadas = [
        obrero.fondo(_set(n), ep.run_dir / "slides" / f"slide-{n:02d}.png", del_episodio=True) for n in numeros
    ]
    return Lote(activos=(), personajes={}, extra=ampliadas)


def puesta(ep) -> Puesta:
    linea = ep.linea()
    anclas.usa(linea)
    slides = _slides(ep)
    g = Guion(
        titulo=slides["title"], idioma=ep.idioma, escena=ep.escena, catalogo=ep.catalogo(), iconos={}, linea=linea
    )
    sets = {}
    for numero in linea.laminas:
        g.fondo(_set(numero), img=_set(numero), suelo=None)
        sets[numero] = _set(numero)
    ajustes = laminas.ajustes(ep.escena)
    tomas = laminas.planifica(
        laminas.laminas_del_episodio(linea, slides["slides"]),
        clave_del_video=slides["title"],
        fps=linea.fps,
        ajustes_=ajustes,
    )
    laminas.pon_en_escena(g, tomas, sets, ajustes_=ajustes)
    return Puesta(guion=g, css=CSS, franja_karaoke_y=ep.escena["franja_karaoke_y"])
```

What each part does:

1. `activos(ep)` asks the worker to upscale every slide of the run (`obrero.fondo(..., del_episodio=True)`). The
   upscaled images belong to this episode only and never enter your channel library.
2. `puesta(ep)` registers one set per slide, named after its upscaled image.
3. `laminas.planifica` splits each slide into shots of about `toma_s` seconds, each with a camera move and an entrance.
   The same title and the same slide descriptions always give the same edit.
4. `laminas.pon_en_escena` writes one shot per take, with its entrance and its camera.

On top of this, a real channel usually adds its own touches through its scene layer: the channel name and the episode
title written in ink (`lib/escena/tinta.py`, with the fonts your profile declares in
`escena.laminas.fuentes_de_los_rotulos`), and the subscribe call to action on the last slide (`lib/escena/cta.py`).

## Checking it without spending GPU time

Before the `escena` stage, the `pone-en-escena` skill builds the script "dry" with its `en_seco.py` script and runs
six checks (cut heads, text over faces, floating feet, scale, karaoke and length) in about a second. The `escena` stage then
composes the page and shows you a sheet of frames: that is the second review stop. Nothing is rendered until you
approve it, because every fix after the render costs another render.
