# Plantilla del `plan.md` de un episodio

El plan se escribe después de leer el guion por partes (`<run>/revision/guion-por-partes.md`) y de mirar las láminas
del run, y antes de pedir ninguna imagen. Vive junto al guion, en `canales/<id>/datos/escenas/<run>/plan.md`, y va en
git con él: es la lista de lo que hay que hacer y el porqué de cada decisión. Las imágenes que salen de él van a
`activos(ep)`, los planos a los tramos y, si el canal la lleva, las palabras a la capa didáctica del episodio. Al final
apunta lo que el usuario dijo en cada parada, con sus palabras.

Lo lleva el formato «personajes» (en preparación, `docs/formats.md`). En «láminas» no hay plan.

Se escribe en el idioma en que trabaja el usuario; las poses y los objetos que se piden a Qwen, en inglés.

```markdown
# «<Título>» · plan de la puesta en escena

## La historia en tres líneas
<qué pasa, el giro que da nombre al vídeo y cómo acaba>

## Continuidad
Lo que cambia y se queda, con el cue desde el que vale:
- <papá lleva harina en la camisa desde C57, y ya no se le quita>
- <las llaves aparecen en C230 y se quedan en la mano de mamá>
- <quién no cambia nunca, y por qué lo dice el cuento>

## Sets
| Set | De dónde sale | Sitios que medir con la rejilla |
|---|---|---|
| <acera> | la capa del canal (ya existe) | <el borde del muro, la puerta> |
| <salón> | nuevo: <cómo se consigue; ver imagenes.md §7> | <el sofá, la mesa baja> |

## Reparto por parte
| Parte | Cues | Planos (set, cámara) | Quién sale y qué hace |
|---|---|---|---|
| 1 · <título> | C4–C18 | <recibidor, de medio cuerpo; corte a…> | <mamá junto a la puerta (mama_seria)…> |

## Imágenes
Se reutilizan (de `biblioteca/indice.json` del canal): <nombres>

Nuevas (nombre · personaje · vista · forma · pose en inglés, solo el cuerpo · semillas):
- <papa_sofa · papa · perfil · ancho · «lying on his front on the floor, reaching forward with one arm stretched out» · 21, 33>

Variantes (nombre · de qué activo · cambio · semillas):
- <papa_sofa_h · papa_sofa · «add white flour on the front of his shirt» · 7>

Objetos (nombre · qué es · escala en unidades del set · en qué mano va y en qué cues):
- <o_llaves · «a small bunch of three silver keys on a red ring» · 0,05 · en el puño derecho de mamá desde C230>

## Movimientos que ya existen
<qué macros, sitios y patrones de la capa del canal o del episodio de ejemplo se usan, y dónde>

## Didáctica (solo si el canal la lleva)
<ver didactica-a2.md: tarjetas, pasados, notas, repasos y tablero, cada uno con su cue>

## Recursos de fuera
<lo que la historia pide y no está en datos/escena/: qué, para qué escena, dónde buscarlo. Se propone en la parada 1>

## Riesgos
- <lo difícil de poner en escena y qué defecto conocido evita (puesta-en-escena.md §5)>
- <lo que el motor no sabe hacer y cómo se rodea (imagenes.md §7, puesta-en-escena.md §4)>

## Paradas
- Parada 1 (<fecha>): <qué vio el usuario y qué dijo, con sus palabras>
- Parada 2 (<fecha>): <qué vio el usuario y qué dijo, con sus palabras>
```

Un plan está bien cuando cada imagen nueva tiene nombre y descripción, y cada interacción física dice qué punto de qué
imagen toca qué punto de qué otra: «la mano abierta de mamá sobre el pomo, medida en la rejilla».
