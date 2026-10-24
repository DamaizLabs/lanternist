"""Los tiempos del guion de escena, anclados a la narración (F6.2b).

Un guion de escena no escribe segundos: escribe «cuando se dice esta palabra». Así, si cambian las pausas o se
regenera la voz, todo se recoloca solo. Viene de las funciones de `canal/scripts/ayudas.py` de video_1:

- `C(n)`: el instante en el vídeo en que empieza el cue n; `F(n)`: en el que acaba.
- `P(n, "palabra", k=0)`: el instante en que se dice `palabra` en el cue n (su aparición k). Si no está en ese
  cue, la busca en los vecinos (n+1, n−1, n+2) y lo apunta en `avisos`: casi siempre es un cue que el troceo
  partió por otro sitio, y el guion sigue valiendo.
- `HUECO(k)`: la pausa que sigue a la lámina de voz k (0 … N−2), como (inicio, fin).
- `cues_del_tramo(k)`: los cues que se dicen en la lámina de voz k.
- `cue_con(texto)`: el último cue que contiene ese texto (el cierre del narrador, que es el mismo en todos los
  episodios).
- `T(palabra, desde)`: el instante de la primera vez que se dice `palabra` desde el segundo `desde`, sin contar cues
  (F7.10). Es el ancla de un guion corto que sigue la narración palabra a palabra, como una pizarra que se construye.
  Si la palabra no se dice después, para: un ancla a una palabra que no está no se cuela.

Los cues y las láminas son los de una `LineaDeTiempo` (`linea_tiempo.py`). Se usan de dos formas:

- ligadas a una línea: `a = Anclas(linea)` y `a.P(3, "bike")`;
- como funciones sueltas, que es como se escriben los tramos de un episodio: `usa(linea)` una vez y luego
  `P(3, "bike")`. Sin `usa`, paran y lo dicen: no hay una línea por omisión.
"""

from __future__ import annotations

from lib.alineacion import _normaliza
from lib.escena.linea_tiempo import ErrorDeLinea, LineaDeTiempo


class Anclas:
    def __init__(self, linea: LineaDeTiempo) -> None:
        self.linea = linea
        self.avisos: list[str] = []

    def C(self, n: int) -> float:
        return self.linea.cue(n).ini

    def F(self, n: int) -> float:
        return self.linea.cue(n).fin

    def P(self, n: int, palabra: str, k: int = 0) -> float:
        """Instante (vídeo) en que se dice `palabra` en el cue n (su aparición k); si no está, en los vecinos."""
        objetivo = _normaliza(palabra)
        for m in (n, n + 1, n - 1, n + 2):
            if not 1 <= m <= len(self.linea.cues):
                continue
            halladas = [p for p in self.linea.cue(m).palabras if _normaliza(p.texto) == objetivo]
            if len(halladas) > k:
                if m != n:
                    self.avisos.append(f"P({n}, '{palabra}') está en el cue {m}")
                return halladas[k].ini
        raise ErrorDeLinea(f"«{palabra}» no está en el cue {n} ni en sus vecinos: {self.linea.cue(n).texto}")

    def HUECO(self, k: int) -> tuple[float, float]:
        return self.linea.hueco(k)

    def cues_del_tramo(self, k: int) -> list[int]:
        return [c.n for c in self.linea.cues if c.lamina == k]

    def T(self, palabra: str, desde: float = 0.0) -> float:
        """Instante (vídeo) de la primera vez que se dice `palabra` desde el segundo `desde`."""
        objetivo = _normaliza(palabra)
        for p in self.linea.palabras:
            if p.ini >= desde - 1e-6 and _normaliza(p.texto) == objetivo:
                return p.ini
        raise ErrorDeLinea(f"«{palabra}» no se dice en la narración desde el segundo {desde:.2f}")

    def cue_con(self, texto: str) -> int:
        buscado = texto.lower()
        for c in reversed(self.linea.cues):
            if buscado in c.texto.lower():
                return c.n
        raise ErrorDeLinea(f"ningún cue contiene «{texto}»")


_ACTIVAS: list[Anclas] = []


def usa(linea: LineaDeTiempo) -> Anclas:
    """Liga las funciones sueltas de este módulo a `linea`. Devuelve las anclas (con sus `avisos`)."""
    _ACTIVAS[:] = [Anclas(linea)]
    return _ACTIVAS[0]


def _activas() -> Anclas:
    if not _ACTIVAS:
        raise ErrorDeLinea("las anclas no tienen línea de tiempo: llama antes a anclas.usa(linea)")
    return _ACTIVAS[0]


def C(n: int) -> float:
    return _activas().C(n)


def F(n: int) -> float:
    return _activas().F(n)


def P(n: int, palabra: str, k: int = 0) -> float:
    return _activas().P(n, palabra, k)


def HUECO(k: int) -> tuple[float, float]:
    return _activas().HUECO(k)


def cues_del_tramo(k: int) -> list[int]:
    return _activas().cues_del_tramo(k)


def cue_con(texto: str) -> int:
    return _activas().cue_con(texto)


def T(palabra: str, desde: float = 0.0) -> float:
    return _activas().T(palabra, desde)
