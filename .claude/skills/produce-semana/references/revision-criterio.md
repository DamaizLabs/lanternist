# Briefs de revisión de criterio

Dos revisiones que ningún script ve. Cada agente revisor recibe la ruta de este archivo y lee su sección; el refutador
de la etapa dos tumba los candidatos falsos con la misma lista delante.

## 1. Guion contra ficha (paso 6)

Lo que el revisor tiene que juzgar, y que ningún script ve:

1. ¿Cada `image_prompt` representa lo que dice **su** narración?
2. ¿Alguna escena cruza las líneas rojas del canal (`perfil.json → lineas_rojas`) o el campo `lineas_rojas` de la
   ficha? El guardián automático mide color, **no postura**.
3. ¿Algún mito de `mitos_asociados` se cuenta como un hecho?
4. ¿El periodo y el ámbito coinciden con la ficha?
5. ¿Hay afirmaciones que la ficha no sostenga, en las formas sutiles?
6. ¿El desmentido está en los primeros treinta segundos cuando la ficha lo pide?
7. **Si la ficha lleva `cifras`** (su nicho lo exige: el perfil de autoridades, `datos/autoridades/<nicho>.json`, lleva
   el bloque `cifras`): ¿cada cifra se cuenta con el año y el ámbito de la ficha, sin mezclar países ni años? ¿Un dato
   de ejemplo de una cuenta se dice como ejemplo y no como un hecho? ¿Se presenta como documentado algún porqué que la
   ficha no respalda? El gate 1 ya comprueba que cada cantidad esté en la ficha; lo que no ve es cómo se cuenta.

**En un canal que declara `nicho.sin_fuentes_verificadas`** en su perfil (el canal de ejemplo lo hace) no hay ficha:
las preguntas 3, 4, 5, 6 y 7 no aplican. La 1 y la 2 sí, porque las líneas rojas son del canal y no de la ficha. Y se
añade una: ¿el guion respeta el formato del canal (`perfil.json → formato`), que allí es la única vara?

## 2. Revisión visual tras el render (paso 8)

La mirada fina ya se hizo antes del render, en la parada 2. Esta es la última, sobre el vídeo montado. Lo que encuentres
**se clasifica**, no bloquea: si rompe el episodio, se regenera y se remonta; si es cosmético, se anota en el LEEME y
el usuario decide antes de publicar.

**Antes de las imágenes, el LEEME del run**: sus `incidencias_no_bloqueantes` dicen dónde entró un respaldo (voz por
silencio, mejor intento). Localiza cada una en el vídeo y juzga si cae sobre un dato clave o sobre relleno: la primera
rompe el episodio, la segunda se anota.

**Sobre el mosaico y la página de `revisa_laminas.py`:**

- **Por lámina**: ¿alguien que mire el dibujo sin oír nada sabría de qué habla la frase?
- **Sobre el mosaico**: ¿el personaje o el objeto mantiene su tamaño y su forma de una lámina a otra? ¿Hay dos láminas
  casi idénticas? ¿Alguna rompe el estilo del resto?
- **Escala**: ¿la pieza tiene el tamaño que le toca? Es el defecto que más ha costado: un objeto con el tamaño
  equivocado en 15 láminas pasó todas las comprobaciones automáticas.
- **Líneas rojas de postura**, que el color no ve.
- **La lámina de la miniatura** (`thumbnail_lamina`): ¿muestra la pieza del título? La miniatura se copia de ella, no se
  genera.

**Sobre el vídeo montado, que el mosaico no muestra:**

- Si el canal declara despedida, ¿la lámina de cierre (`"tipo": "cierre"`) está, y su ilustración es la de la última
  lámina del relato?
- ¿La descripción quedó **sin marcadores** `<<…>>` literales? Se mira en `subir-al-canal/LEEME.html`, o en el borrador
  si se subió por la API.
- Si el LEEME anota un respaldo de voz, ¿el silencio o el mejor intento se nota al oírlo en su sitio?
