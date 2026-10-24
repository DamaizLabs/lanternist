# La biblioteca del motor de escena: efectos de sonido y fuentes

Son del **estudio**: cualquier canal los puede usar. Qué efecto suena y cuándo lo decide el guion de escena de cada
episodio, y qué fuente se ve lo deciden el perfil y el CSS de cada canal (F4.9). Aquí solo están los ficheros y de
dónde salen.

| Carpeta | Qué hay | De dónde sale | Licencia |
|---|---|---|---|
| `sfx/` | 9 efectos (`chime`, `click-soft`, `notification`, `ping`, `pop`, `riser`, `sparkle`, `whoosh`, `whoosh-short`). **No viajan en el repositorio**: la licencia de Pixabay no deja distribuirlos sueltos (OC1.2). Se instalan con `scripts/instala_efectos.py` | Pixabay, en la copia que trae HyperFrames 0.8.78 (`dist/skills/media-use/audio/assets/sfx/`), que `cd motor; npm ci` deja en `motor/node_modules/hyperframes`. El script la copia si su sha256 es el de `sfx/CREDITOS.json`, comprobado el 29-09-2026, y niega uno distinto | Pixabay Content License: uso comercial sin atribución, en una obra; no sueltos |
| `fuentes/` | Baloo 2 Bold, Fredoka Regular y Fredoka Bold (`woff2`) | El repositorio de HyperFrames (`skills/embedded-captions`), según el `CREDITOS.md` de video_1. El autor y la licencia se leyeron de cada fichero. El texto de su licencia va al lado (`OFL-Baloo2.txt` y `OFL-Fredoka.txt`), bajado de Google Fonts el 14-10-2026 (OC1.2) | SIL Open Font License 1.1 |
| `fuentes/` | Patrick Hand SC Regular (`ttf`), la letra de tiza del formato «pizarra» (F7.10) | El repositorio de Google Fonts (`ofl/patrickhandsc`), bajada el 05-10-2026, con su licencia al lado (`OFL-PatrickHandSC.txt`) | SIL Open Font License 1.1 |
| `fuentes/` | Gelasio Regular y Gelasio Italic (`ttf` variables), la letra de los rótulos a tinta del canal de ejemplo en el formato «láminas» (OC1.2). Sustituye a Georgia, que es de Windows y no se puede redistribuir; Gelasio tiene sus métricas | El repositorio de Google Fonts (`ofl/gelasio`), bajada el 14-10-2026, con su licencia al lado (`OFL-Gelasio.txt`) | SIL Open Font License 1.1 |
| `fuentes/` | Anton Regular (`ttf`), la letra del texto de la miniatura y del banner del canal de ejemplo (OC1.4). Sustituye a Impact, que es de Windows y no se puede redistribuir | El repositorio de Google Fonts (`ofl/anton`), bajada el 15-10-2026, con su licencia al lado (`OFL-Anton.txt`) | SIL Open Font License 1.1 |

Los efectos, Baloo 2 y Fredoka llegaron desde el experimento video_1 (`canal/assets/`) en F6.2d.

## Cómo se usan

- **La procedencia de cada fichero está en `CREDITOS.json`** de su carpeta: fuente, licencia, url, autor y sha256. El
  motor de escena (`lib/escena/audio.py`) copia al run lo que usa un episodio (`<run>/biblioteca/`) y lo apunta en
  `assets.json` con esos datos (decisión 5).
- **Un fichero sin entrada, o con otro sha256, para el run.** Añadir un efecto o una fuente es dejar el fichero aquí y
  escribir su entrada en `CREDITOS.json` antes de usarlo.
- **Solo viaja en el repositorio lo que su licencia deja redistribuir** (OC1.2), y una fuente OFL lleva al lado el
  texto de su licencia (`texto_de_la_licencia` en su entrada). Lo que no se puede redistribuir, como los efectos de
  Pixabay, se instala desde su origen con su sha256 y su entrada queda aquí. `scripts/guarda_licencias.py` lo vigila.
- **La fuente de los rótulos a tinta sale de aquí**, nunca del sistema: el perfil del canal la nombra
  (`escena.laminas.fuentes_de_los_rotulos`, o `escena.pizarra.texto.fuente`) y su CSS la declara, que es lo que la
  lleva al run y a `assets.json` (`lib/escena/tinta.py → fuente_de_la_biblioteca`).
- **La del texto de la miniatura y la del banner, también** (OC1.4): el perfil las nombra
  (`imagen.fuente_de_la_miniatura` y `marca.banner.fuente`), y la etapa que dibuja el texto copia la fuente al run, o a
  la carpeta de la marca, con su registro (`lib/miniatura.py → fuente_declarada` y `copia_la_fuente`).
- Lo que decía el `CREDITOS.md` de video_1 sobre licencias, como referencia: valen la Pixabay Content License, CC0 y
  OFL; CC-BY solo con el crédito en la descripción; NC, ND si hay que editar y «solo uso personal», no.
