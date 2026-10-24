# Lo que solo puede hacer el usuario en YouTube

El código no puede dar ninguno de estos pasos. Crear cuentas o credenciales y aceptar términos lo hace siempre el
usuario, nunca Claude: son actos en su nombre. Tú preparas los pasos, le abres la página con los enlaces
(`scripts/comprueba_canal.py --canal <id> --pagina`) y compruebas el resultado.

Ninguno hace falta para **producir** un vídeo: el motor produce en local sin ninguna cuenta. Hacen falta para
**publicarlo** en su canal.

## 1. Crear el canal

- En [YouTube Studio](https://studio.youtube.com), con la cuenta de Google que va a ser dueña del canal: «Crear un
  canal», con el **nombre y el handle que decidió en el paso 2a**. La API de YouTube no tiene ninguna orden para crear
  canales.
- Comprueba que el nombre que sale en YouTube es el del perfil (`nombre`). Si no coincide, uno de los dos se corrige
  ahora, antes de generar el banner, que lleva el nombre escrito.
- Después, el id del canal: empieza por `UC` y es la última parte de la dirección de Studio,
  `https://studio.youtube.com/channel/<id del canal>`. Apunta en el perfil `publicacion.canal_id`, `handle` y
  `canal_youtube` (la dirección pública del canal).

## 2. Verificarlo por teléfono

- En [youtube.com/verify](https://www.youtube.com/verify), con el canal correcto elegido arriba a la derecha. Sin la
  verificación, YouTube no acepta miniaturas propias ni vídeos de más de 15 minutos.
- **Es por canal, no por cuenta**: un canal verificado no verifica otro de la misma cuenta.
- **Un número vale para 2 canales al año**, según la ayuda de YouTube. Pregúntale si ya usó su número con otros
  canales este año antes de mandarle a verificar.
- Cuando esté hecho, escribe `"verificado_por_telefono": true` en el bloque `publicacion` del perfil.

El paso a paso, con lo que hacer si el SMS no llega, está en `docs/youtube-upload.md`, «Verify the channel by phone».

## 3. La subida: a mano, o por la API con su OAuth

**Por defecto la subida va a mano en Studio**, y no pide ninguna clave de Google. Cada run deja en
`canales/<id>/videos/<run>/subir-al-canal/` el vídeo, la miniatura, los subtítulos y un `LEEME.html` que se abre solo,
con el título y la descripción para copiar y los pasos de Studio: el vídeo en privado primero, «sí» a la pregunta de
contenido alterado o sintético, la audiencia y la categoría del perfil, la miniatura y los `.srt`.

**Por la API, solo si el usuario lo quiere.** OAuth es el permiso que Google da a una aplicación para actuar en su
canal. Para que el motor suba por él necesita:

- `YOUTUBE_SUBIDA_API=1` en su `.env`. Vacía, la subida va a mano; cualquier otro valor para el run;
- **su propio proyecto de Google Cloud** y su cliente OAuth. Lanternist no trae credenciales: las políticas de YouTube
  piden un proyecto por usuario y prohíben incrustarlas en un proyecto de código abierto;
- **un token por canal**, en la variable del `.env` que nombra su perfil en `publicacion.refresh_token_env` (el canal
  de ejemplo usa `YOUTUBE_REFRESH_TOKEN`; un segundo canal declara otra, como `YOUTUBE_REFRESH_TOKEN_2`). El token de
  un canal da `403` en otro. El usuario lo pega en su `.env`: nunca en el chat ni en un commit.

Todo el proceso, con las trampas por error, está en `docs/youtube-upload.md`. Aun por la API, el motor sube un
**borrador privado** con la declaración de IA: publicar lo decide el usuario, vídeo a vídeo, en Studio.

Comprobación: `pipeline.py --check` dice si la subida está a mano o por la API, y si a la API le falta alguna clave.

## 4. La identidad en Studio

Después de `canal.py --generar` (paso 3 de la skill), la página de identidad
(`canales/<id>/marca/identidad-del-canal.html`) tiene el banner, el avatar, la marca de agua, la descripción y las
palabras clave, listos para copiar:

- **A mano en Studio**, que es lo de serie: el avatar, el banner, la marca de agua, la descripción y las palabras
  clave. El avatar y los textos van siempre a mano: la API no los cambia con los permisos que pide el motor.
- **Con su OAuth**, el usuario puede lanzar él `canal.py --subir-marca-de-agua --confirmo` y
  `canal.py --subir-banner --confirmo`. Tú no los lanzas nunca: un banner o una marca de agua se ven en el canal en
  cuanto la API responde, y no tienen borrador privado. El banner subido así puede pedir aplicarlo a mano en Studio;
  la orden lo dice.
- Que mire el banner en el móvil: el área segura, la franja que se ve en todas las pantallas, la marca
  `lib/canal_marca.py`.
