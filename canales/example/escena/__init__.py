"""La capa de canal de Lantern Slides, el canal de ejemplo, en el motor de escena (OC1.4).

Todo lo que es igual en cada episodio del canal y no es del motor (F4.9). El canal no tiene personajes: su formato es
«láminas», y la cámara recorre cada lámina entera con el planificador del motor (`lib/escena/laminas.py`) y los ajustes
de `perfil.json → escena.laminas`.

Es la capa más pequeña que funciona: solo su hoja de estilo, `estilo.css` (la letra y el color del karaoke, el fondo,
el negro de entrada y salida y el color del papel de la transición `papel`). Sin rótulos a tinta ni CTA: son decisiones
de identidad que el canal de ejemplo todavía no ha tomado. Un canal que los quiera añade aquí sus módulos (`apertura`,
`cierre`), como cuenta `docs/scene-script.md`.

El motor la carga como el paquete `escena_del_canal` (`lib/escena/episodio.py`), y el guion de cada episodio la importa
con `from escena_del_canal import CSS`.
"""

from __future__ import annotations

from pathlib import Path

CSS = Path(__file__).with_name("estilo.css")

__all__ = ["CSS"]
