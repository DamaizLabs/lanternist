"""El lenguaje de la puesta en escena (F6.2b): planos, actores, cámara, elementos, sonidos y transiciones.

Viene de `canal/scripts/escena.py` del experimento video_1, generalizado para el estudio. Lo que se
escribe con él (los «tramos» de un episodio) se convierte en el GUION que leen `motor/motor.js` y
`lib/escena/compone.py`, con `Guion.datos()`.

Las piezas:

- Un **plano** es una lámina: un set (su fondo), su cámara y los actores que hay en él, visible durante
  [t0, t1]. Los planos se encadenan con una entrada (corte, fundido, barrido o iris) o, desde F6.8, con una de las
  de tinta del motor de láminas (cortina, mancha, calado, viento y papel).
- Un **actor** es cualquier figura recortada que se mueve: un personaje, un vehículo, un objeto. Tiene varias
  imágenes («posturas») y una pista de claves:
    - `x`, `y`: su punto de apoyo (los pies) en px del fondo;
    - `s`: escala extra sobre la suya (1 = su tamaño); `r`: giro en grados; `op`: opacidad;
    - `flip`: 0 mira a la derecha y 1 a la izquierda; `ancho`: escala solo horizontal (una puerta que se abre);
    - `dz`: cambio de profundidad; `post`: la postura visible (cambia con un fundido corto, `fp` en la clave);
    - `giro`: giro libre en grados por segundo (una rueda al aire).
  Un actor puede ir pegado a otro (`padre`): lo que se monta en algo, lo que se lleva en la mano.
- Un **elemento** es lo que va en pantalla o pegado a un plano (rótulos, tarjetas, efectos): un trozo de HTML
  con clases, cuyo estilo pone el CSS del canal.

**Lo que NO está aquí, y estaba en video_1**: las alturas de los personajes, sus sets, su catálogo global,
las sustituciones de borrador y la biblioteca del canal. Todo eso es del canal (F6.3) y llega como parámetro:
el catálogo de imágenes, los iconos, el bloque `escena` de su perfil (`lib/escena/ajustes.py`) y la escala de
cada actor.

**Sin valores de estilo por omisión.** Los argumentos con valor por omisión son los neutros (opacidad 1,
escala 1, sin giro, la curva «inout»); lo que es un gusto —cuánto tarda la cámara en moverse, a qué volumen
suena un efecto, cuánto dura una transición— se escribe en cada llamada o lo pone el envoltorio del canal.

Todo lo que el motor no sabe hacer (un evento, una curva, una entrada, un rasgo o un campo desconocido) para
aquí, al escribirlo, con el nombre de lo que falla: el motor lo ignoraría en silencio o lo pararía mucho más
tarde, en el navegador.
"""

from __future__ import annotations

import copy
import html
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from lib.escena import ajustes, compone


class ErrorDeEscena(ValueError):
    """Algo del guion de escena no se puede escribir así: el mensaje dice qué y dónde."""


# Las curvas que conoce `Motor.EASE`. `acelera` y `frena` son el «ease_in» y el «ease_out» del motor de láminas
# (su `_easing_expr`, traído en F6.8; aquel motor se retiró en F6.7); su «ease_in_out» es `suave`.
CURVAS = ("lineal", "suave", "inout", "sale", "entra", "rebote", "elastico", "acelera", "frena")
# Lo que puede llevar una clave de la pista de un actor (`fp` es solo de esa clave: su fundido de postura).
CAMPOS_DE_CLAVE = ("x", "y", "s", "r", "op", "flip", "post", "giro", "ancho", "dz")
# Los rasgos que el motor lee de un actor, más `pisa`, que solo usa `lib/escena/comprobaciones.py` (¿se apoya
# en el suelo del set? Por omisión, si es un personaje).
RASGOS = ("anda", "v_anda", "paso", "bote", "charla", "respira", "fase", "rueda", "gira", "hereda", "pieza", "pisa")
# Lo que puede animar un elemento (`Motor.elemento` y el director).
CLAVES_DE_ANIMACION = (
    "entra",
    "sale",
    "bucle",
    "amp",
    "di",
    "ds",
    "trazo",
    "trazo_t",
    "trazo_d",
    "contador",
    "aguja",
    "aguja_v",
    "campana",
    "campana_t",
    "campana_p",
    "sigue",
    "fluye",  # F7.10: px/s a los que corren los guiones de los trazos `.fluye` (una flecha que fluye)
)
# Lo que el motor exige a cada evento que no puede tomar del GUION.
CAMPOS_OBLIGADOS_DE_EVENTO = {"salto": ("h",)}


def _redondea(t: float) -> float:
    return round(float(t), 3)


@dataclass
class Actor:
    id: str
    plano: str
    posturas: list[str]
    escala: float  # px del fondo por px de la imagen, con s = 1
    claves: list[dict] = field(default_factory=list)
    padre: str | None = None
    z: int = 0
    pj: str | None = None  # el personaje: su habla (G.habla[pj]) y su respiración
    rasgos: dict = field(default_factory=dict)
    eventos: list[dict] = field(default_factory=list)

    def clave(self, t: float, tr: float = 0.0, e: str = "inout", **campos) -> Actor:
        """Una clave de la pista: los campos llegan a su valor entre `t` y `t + tr`, con la curva `e`."""
        desconocidos = sorted(set(campos) - set(CAMPOS_DE_CLAVE) - {"fp"})
        if desconocidos:
            raise ErrorDeEscena(
                f"el actor {self.id} lleva en su clave de t={t} campos que el motor no conoce: {desconocidos} "
                f"(valen {', '.join(CAMPOS_DE_CLAVE)} y fp)"
            )
        if e not in CURVAS:
            raise ErrorDeEscena(f"el actor {self.id}: la curva «{e}» no existe ({', '.join(CURVAS)})")
        self.claves.append({"t": _redondea(t), "tr": tr, "e": e, **campos})
        return self

    def ev(self, tipo: str, t: float, d: float, **kw) -> Actor:
        """Un movimiento pasajero (`compone.TIPOS_DE_EVENTO`). Sus magnitudes, las suyas o las del GUION."""
        if tipo not in compone.TIPOS_DE_EVENTO:
            raise ErrorDeEscena(
                f"el actor {self.id} lleva un evento «{tipo}», que el motor no sabe hacer "
                f"({', '.join(compone.TIPOS_DE_EVENTO)})"
            )
        faltan = [c for c in CAMPOS_OBLIGADOS_DE_EVENTO.get(tipo, ()) if c not in kw]
        if faltan:
            raise ErrorDeEscena(f"el evento «{tipo}» del actor {self.id} necesita {faltan}")
        self.eventos.append({"tipo": tipo, "t": _redondea(t), "d": d, **kw})
        return self


@dataclass
class Elemento:
    id: str
    capa: str  # «pantalla» o el id de un plano (entonces x, y son px de su fondo)
    x: float  # esquina superior izquierda
    y: float
    w: float
    h: float
    html: str
    t0: float
    t1: float
    anim: dict = field(default_factory=dict)
    clase: str = ""
    z: int = 0
    movible: bool = False  # `encuadre.aparta_de_caras` lo puede cambiar de sitio si tapa una cara
    tapa_caras: bool = False  # tapa caras a propósito (un tablero): las comprobaciones no lo cuentan
    grito: bool = False  # un grito de un personaje, que va junto a su cabeza


@dataclass
class Fondo:
    """Un set: su imagen del catálogo, su escala y dónde está su suelo."""

    img: str
    suelo: list[tuple[float, float]] | None  # polígono en px del fondo; None = este set no tiene suelo
    px_u: float | None = None  # px del fondo por unidad de altura (la unidad la define el canal)
    decora: Callable | None = None  # decora(g, plano, t0, t1): lo que se pone en cada plano de este set


@dataclass
class Plano:
    id: str
    fondo: str  # el nombre del set
    t0: float
    t1: float
    px_u: float | None
    camara: list[dict] = field(default_factory=list)
    entra: dict = field(default_factory=lambda: {"tipo": "corte", "d": 0.0})
    actores: list[Actor] = field(default_factory=list)
    extra: str = ""  # HTML fijo del plano (luces, velos)
    desenfoque: float = 0.0  # px de desenfoque del fondo (primeros planos)

    def cam(
        self,
        t: float,
        cx: float,
        cy: float,
        z: float,
        tr: float,
        e: str = "inout",
        sigue: str | None = None,
        libre: bool = False,
    ) -> Plano:
        """Encuadre centrado en (cx, cy) con zoom z (1 = el fondo entero a lo ancho), al que se llega en `tr` s.

        `sigue` centra en ese actor más (cx, cy). `libre` saca la clave de `encuadre.corrige` y de la comprobación
        de cabezas: un primer plano que corta una cabeza a propósito.
        """
        if e not in CURVAS:
            raise ErrorDeEscena(f"la cámara del plano {self.id}: la curva «{e}» no existe ({', '.join(CURVAS)})")
        if not z > 0:
            raise ErrorDeEscena(f"la cámara del plano {self.id}: el zoom tiene que ser positivo, no {z}")
        self.camara.append(
            {"t": _redondea(t), "tr": tr, "e": e, "cx": cx, "cy": cy, "z": z, "sigue": sigue, "libre": libre}
        )
        return self


class Guion:
    """Un guion de escena: lo que se escribe para un episodio y sale como GUION con `datos()`.

    - `titulo` e `idioma`: los de la página (el idioma es el de su texto en pantalla).
    - `escena`: el bloque `escena` del perfil del canal (`lib/escena/ajustes.py`), sin defecto.
    - `catalogo`: {nombre: imagen} con `src`, `w`, `h`, `ax`, `ay` y, si hace falta, `k`, `cabeza`,
      `cabeza_px`, `jinete`, `off`… Es el catálogo del canal y del episodio.
    - `iconos`: {nombre: html} de los dibujos del canal que no son imágenes (puede ir vacío).
    - `linea`: la línea de tiempo del episodio (`lib/escena/linea_tiempo.py`): da la duración, el karaoke y
      los tramos de habla. Sin ella, `datos()` pide la duración y sale sin karaoke.
    - `rig`: las mallas del episodio ({"piezas": …}), si las hay.
    """

    def __init__(
        self,
        *,
        titulo: str,
        idioma: str,
        escena: Mapping,
        catalogo: Mapping[str, Mapping],
        iconos: Mapping[str, str],
        linea=None,
        rig: Mapping | None = None,
    ) -> None:
        self.titulo = titulo
        self.idioma = idioma
        self.escena = ajustes.valida_bloque(escena)
        self.catalogo = catalogo
        self.iconos = iconos
        self.linea = linea
        self.rig = rig
        self.fondos: dict[str, Fondo] = {}
        self.planos: list[Plano] = []
        self.elementos: list[Elemento] = []
        self.sonidos: list[dict] = []
        self.transiciones: list[dict] = []
        self.avisos: list[str] = []
        # Las imágenes del catálogo que el guion ha pedido, en orden: lo que un episodio tiene que traer de la
        # biblioteca de su canal (`lib/escena/biblia.py`) si escribe el guion contra ella.
        self.usadas: dict[str, None] = {}
        self._n = 0
        self._sin_karaoke = False

    def sin_karaoke(self) -> None:
        """El vídeo no lleva karaoke en pantalla: el GUION sale sin grupos de karaoke (F7.10).

        Lo pide un canal que lo decidió así (fila 257: su pizarra ya está llena de texto). Solo quita lo que se
        pinta: los cues, sus anclas y el `.srt` de la etapa `alinea` siguen saliendo de la misma línea de tiempo.
        """
        self._sin_karaoke = True

    def _id(self, prefijo: str) -> str:
        self._n += 1
        return f"{prefijo}{self._n}"

    # ---------------------------------------------------------- catálogo
    def imagen(self, nombre: str) -> dict:
        """Los datos de una imagen del catálogo. Si no está, para: aquí no hay sustitutas de borrador."""
        if nombre not in self.catalogo:
            raise ErrorDeEscena(f"la imagen «{nombre}» no está en el catálogo del episodio")
        self.usadas[nombre] = None
        return dict(self.catalogo[nombre])

    def dibujo(self, nombre: str) -> str:
        """El HTML de un dibujo: un icono del canal o, si no lo es, su imagen del catálogo."""
        if nombre in self.iconos:
            return self.iconos[nombre]
        return f'<img class="obj" src="{html.escape(self.imagen(nombre)["src"], quote=True)}" alt="">'

    # ---------------------------------------------------------- sets, planos y actores
    def fondo(
        self,
        nombre: str,
        *,
        img: str,
        suelo: list[tuple[float, float]] | None,
        px_u: float | None = None,
        decora: Callable | None = None,
    ) -> Fondo:
        """Registra un set. `suelo` es obligatorio: un polígono en px del fondo, o None si el set no tiene suelo."""
        self.imagen(img)
        if suelo is not None and len(suelo) < 3:
            raise ErrorDeEscena(f"el suelo del set «{nombre}» necesita al menos tres vértices")
        f = Fondo(img=img, suelo=[tuple(v) for v in suelo] if suelo is not None else None, px_u=px_u, decora=decora)
        self.fondos[nombre] = f
        return f

    def plano(
        self,
        fondo: str,
        t0: float,
        t1: float,
        *,
        entra: str = "corte",
        d: float = 0.0,
        desenfoque: float = 0.0,
        dir: str | int | None = None,
    ):
        """Un plano de ese set, visible en [t0, t1]; entra con `entra` durante `d` s.

        `dir` es hacia dónde avanza el frente de las entradas que lo piden (`compone.DIRECCIONES_DE_ENTRADA`: la
        `cortina`, «derecha», «izquierda» o «arriba», y el `viento`, «derecha» o «izquierda»), sin defecto; en el
        `barrido`, su sentido (1 o -1). Las demás entradas no llevan.
        """
        if fondo not in self.fondos:
            raise ErrorDeEscena(f"el set «{fondo}» no está registrado: regístralo con Guion.fondo(...)")
        if entra not in compone.ENTRADAS_DE_PLANO:
            raise ErrorDeEscena(f"un plano no puede entrar con «{entra}» ({', '.join(compone.ENTRADAS_DE_PLANO)})")
        problema = compone.problema_de_direccion(entra, dir)
        if problema:
            raise ErrorDeEscena(f"un plano de «{fondo}» {problema}")
        if not t1 > t0:
            raise ErrorDeEscena(f"un plano de «{fondo}» acaba ({t1}) antes de empezar ({t0})")
        f = self.fondos[fondo]
        # Sin dirección, la entrada sale como antes ({tipo, d}): un guion que no la usa no cambia.
        entrada = {"tipo": entra, "d": d, **({"dir": dir} if dir is not None else {})}
        p = Plano(self._id("p"), fondo, _redondea(t0), _redondea(t1), f.px_u, entra=entrada)
        p.desenfoque = desenfoque
        self.planos.append(p)
        if f.decora:
            f.decora(self, p, t0, t1)  # con los tiempos sin redondear, como se escribieron
        return p

    def actor(
        self,
        plano: Plano,
        posturas: list[str] | str,
        x: float,
        y: float,
        *,
        escala: float | None = None,
        alto: float | None = None,
        pj: str | None = None,
        s: float = 1.0,
        flip: float = 0,
        z: int | None = None,
        padre: Actor | None = None,
        op: float = 1.0,
        **rasgos,
    ) -> Actor:
        """Añade un actor con su apoyo en (x, y) del fondo.

        Su tamaño, de una de dos formas: `escala` (px del fondo por px de la imagen), o `alto` en unidades del
        set (necesita que el set declare `px_u`). Las alturas de los personajes son del canal, que calcula la
        escala o el alto antes de llamar aquí.

        Sin `z`, quien pisa más abajo tapa a quien está detrás (`100 + y/8`), que es la regla de profundidad de un
        plano en perspectiva, no un gusto.
        """
        posturas = [posturas] if isinstance(posturas, str) else list(posturas)
        if not posturas:
            raise ErrorDeEscena("un actor necesita al menos una postura")
        desconocidos = sorted(set(rasgos) - set(RASGOS))
        if desconocidos:
            raise ErrorDeEscena(f"rasgos que el motor no conoce: {desconocidos} (valen {', '.join(RASGOS)})")
        d = self.imagen(posturas[0])
        if (escala is None) == (alto is None):
            raise ErrorDeEscena(f"el actor de «{posturas[0]}» necesita su tamaño: `escala` o `alto`, uno de los dos")
        if escala is None:
            if not plano.px_u:
                raise ErrorDeEscena(f"`alto` necesita que el set «{plano.fondo}» declare px_u")
            escala = plano.px_u * alto / (d["h"] / d.get("k", 1))
        if z is None:
            z = 100 + round(y / 8)
        a = Actor(
            self._id("a"), plano.id, posturas, escala, padre=padre.id if padre else None, z=z, pj=pj, rasgos=rasgos
        )
        a.clave(0, x=x, y=y, s=s, r=0, op=op, flip=flip, post=posturas[0], giro=0, ancho=1.0, dz=0)
        plano.actores.append(a)
        return a

    # ---------------------------------------------------------- elementos, sonidos y transiciones
    def el(
        self,
        capa: str,
        contenido: str,
        x: float,
        y: float,
        w: float,
        h: float,
        t0: float,
        t1: float,
        *,
        clase: str = "",
        z: int = 0,
        movible: bool = False,
        tapa_caras: bool = False,
        grito: bool = False,
        **anim,
    ) -> Elemento:
        """Un elemento centrado en (x, y), de w × h, visible en [t0, t1]. `anim`: lo que lee `Motor.elemento`."""
        desconocidas = sorted(set(anim) - set(CLAVES_DE_ANIMACION))
        if desconocidas:
            raise ErrorDeEscena(
                f"el elemento de t={t0} lleva {desconocidas}, que el motor no conoce "
                f"(valen {', '.join(CLAVES_DE_ANIMACION)})"
            )
        for campo, lista in (("entra", compone.ENTRADAS), ("sale", compone.SALIDAS), ("bucle", compone.BUCLES)):
            if anim.get(campo) is not None and anim[campo] not in lista:
                raise ErrorDeEscena(f"el elemento de t={t0}: {campo} «{anim[campo]}» no existe ({', '.join(lista)})")
        if not t1 > t0:
            raise ErrorDeEscena(f"un elemento acaba ({t1}) antes de empezar ({t0})")
        e = Elemento(
            self._id("e"),
            capa,
            x - w / 2,
            y - h / 2,
            w,
            h,
            contenido,
            _redondea(t0),
            _redondea(t1),
            dict(anim),
            clase,
            z,
            movible=movible,
            tapa_caras=tapa_caras,
            grito=grito,
        )
        self.elementos.append(e)
        return e

    def sfx(self, nombre: str, t: float, volumen: float, dur: float | None = None) -> None:
        """Un efecto de sonido en t. `dur` lo corta antes de que acabe. El fichero y su licencia son de F6.2d."""
        self.sonidos.append(
            {"nombre": nombre, "t": _redondea(t), "vol": volumen, **({"dur": _redondea(dur)} if dur else {})}
        )

    def suena(self, sonido: Mapping | None, t: float) -> None:
        """Hace sonar `sonido` ({nombre, volumen, desfase_s opcional}) en t + desfase; None es «sin sonido»."""
        if sonido is None:
            return
        faltan = [k for k in ("nombre", "volumen") if k not in sonido]
        if faltan:
            raise ErrorDeEscena(f"un sonido necesita {faltan}: {dict(sonido)}")
        self.sfx(sonido["nombre"], t + sonido.get("desfase_s", 0.0), sonido["volumen"])

    def transicion(self, tipo: str, t: float, d: float, *, sonido: Mapping | None) -> dict:
        """Cortina de pantalla completa (`compone.TIPOS_DE_TRANSICION`) de `d` s desde t. `sonido`: None o uno."""
        if tipo not in compone.TIPOS_DE_TRANSICION:
            raise ErrorDeEscena(f"la transición «{tipo}» no existe ({', '.join(compone.TIPOS_DE_TRANSICION)})")
        x = {"id": f"tr{len(self.transiciones)}", "tipo": tipo, "t": _redondea(t), "d": d}
        self.transiciones.append(x)
        self.suena(sonido, t)
        return x

    # ---------------------------------------------------------- salida
    def _completa(self, claves: list[dict], quien: str) -> list[dict]:
        """La pista con cada clave COMPLETA: arrastra los campos que una clave no cambia (el motor lo espera)."""
        claves = sorted(claves, key=lambda k: k["t"])
        for a, b in zip(claves, claves[1:]):
            if a["t"] == b["t"] and a.get("tr", 0) > 0:
                self.avisos.append(
                    f"{quien} t={a['t']}: dos claves a la vez, y la transición de {a.get('tr')} s de la primera se "
                    "pierde (el motor solo hace la de la última)"
                )
        actual: dict = {}
        salida = []
        for k in claves:
            # tr, e y fp (el fundido de postura) son de esa clave: no pasan a las siguientes.
            actual.update({c: v for c, v in k.items() if c not in ("t", "tr", "e", "fp")})
            propia = {"fp": k["fp"]} if "fp" in k else {}
            salida.append({"t": k["t"], "tr": k.get("tr", 0), "e": k.get("e", "inout"), **actual, **propia})
        return salida

    def datos(self, *, duracion: float | None = None) -> dict:
        """El GUION: lo que leen `lib/escena/compone.py` y `motor/motor.js`.

        La duración, el karaoke y la habla salen de la línea de tiempo si el guion la tiene; sin ella, la duración
        se da aquí y el vídeo va sin karaoke. Los efectos de sonido (`self.sonidos`) no van dentro: los convierte
        en audios de la composición la etapa de audio (F6.2d), que mide su duración y trae su licencia.
        """
        if self.linea is not None:
            if duracion is not None:
                raise ErrorDeEscena("con línea de tiempo la duración es la suya: no la pases a mano")
            if self.linea.fps != self.escena["fps"]:
                raise ErrorDeEscena(
                    f"la línea de tiempo va a {self.linea.fps} fps y el guion a {self.escena['fps']}: sus tiempos "
                    "están redondeados a otros fotogramas. Arma las dos con el mismo bloque `escena`."
                )
            duracion, karaoke, habla = self.linea.total, self.linea.karaoke(), self.linea.habla()
            if self._sin_karaoke:
                karaoke = []
        else:
            if duracion is None:
                raise ErrorDeEscena("sin línea de tiempo hay que dar la duración: datos(duracion=...)")
            karaoke, habla = [], {}
        ids_de_plano = {p.id for p in self.planos}
        planos = []
        for p in sorted(self.planos, key=lambda p: p.t0):
            if not p.camara:
                raise ErrorDeEscena(
                    f"el plano {p.id} ({p.fondo}) no tiene ninguna clave de cámara: ponle una con cam()"
                )
            f = self.fondos[p.fondo]
            actores = []
            for a in p.actores:
                usadas = list(dict.fromkeys(a.posturas + [k["post"] for k in a.claves if "post" in k]))
                actores.append(
                    {
                        "id": a.id,
                        "escala": a.escala,
                        "padre": a.padre,
                        "z": a.z,
                        "pj": a.pj,
                        "rasgos": a.rasgos,
                        "posturas": {n: self.imagen(n) for n in usadas},
                        "pista": self._completa(a.claves, f"{p.id}/{a.id} ({a.posturas[0]})"),
                        "eventos": sorted(a.eventos, key=lambda e: e["t"]),
                    }
                )
            planos.append(
                {
                    "id": p.id,
                    "t0": p.t0,
                    "t1": p.t1,
                    "entra": p.entra,
                    "fondo": {**self.imagen(f.img), "suelo": f.suelo},
                    "extra": p.extra,
                    "desenfoque": p.desenfoque,
                    "camara": sorted(p.camara, key=lambda k: k["t"]),
                    "actores": actores,
                }
            )
        elementos = []
        for e in self.elementos:
            if e.capa != "pantalla" and e.capa not in ids_de_plano:
                raise ErrorDeEscena(f"el elemento {e.id} va en la capa «{e.capa}», que no es un plano de este guion")
            elementos.append(
                {
                    "id": e.id,
                    "t0": e.t0,
                    "t1": e.t1,
                    "capa": e.capa,
                    "clase": e.clase,
                    "html": e.html,
                    "x": e.x,
                    "y": e.y,
                    "w": e.w,
                    "h": e.h,
                    "z": e.z,
                    "movible": e.movible,
                    "tapa_caras": e.tapa_caras,
                    "grito": e.grito,
                    **e.anim,
                }
            )
        esc = self.escena
        guion = {
            "titulo": self.titulo,
            "idioma": self.idioma,
            "fps": esc["fps"],
            "marco": dict(esc["marco"]),
            "fundido": esc["fundido"],
            "camara_en_mano": esc["camara_en_mano"],
            "movimiento": esc["movimiento"],
            "duracion": duracion,
            "planos": planos,
            "elementos": elementos,
            "karaoke": karaoke,
            "habla": habla,
            "transiciones": sorted(self.transiciones, key=lambda x: x["t"]),
        }
        if self.rig is not None:
            guion["rig"] = self.rig
        if self._sin_karaoke:
            # Solo en el GUION que lo pide: el de un canal con karaoke sale igual que antes de F7.10.
            guion["sin_karaoke"] = True
        # Una copia: quien corrija el GUION después (`encuadre.corrige`) no toca el guion ni el perfil del canal.
        return copy.deepcopy(guion)
