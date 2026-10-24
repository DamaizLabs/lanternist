# Contrato de miniatura — canal de ejemplo

> **Del canal, no del motor.** Lo que es del motor es que **exista** un contrato de miniatura; su contenido es de
> cada canal. Es **provisional** hasta OC1.4, cuando el canal de ejemplo tenga sus láminas.

## De dónde sale la miniatura

De **una lámina del run**, declarada en `slides.json → thumbnail_lamina`. No se genera una imagen aparte: la lámina
ya pasó por los ojos de quien produce en la revisión de láminas.

## Qué se le hace

- Se recorta al objeto, que tiene que leerse a 168 px de ancho.
- El texto, si lo lleva, lo compone el motor con tipografía real a partir de `thumbnail_text`: el modelo de imagen
  no escribe texto.

## Lo que promete

Lo mismo que el vídeo entrega: el objeto del episodio y la pregunta de cómo funciona. Nada que el vídeo no cuente.
