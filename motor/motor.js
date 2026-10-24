// Motor de escena del estudio (F6.2a, addendum fila 199): toda la matemática del vídeo como funciones puras
// del tiempo t, sin tocar el DOM. Lo usa director.js para pintar cada fotograma, y corre igual en Node
// (tests/escena/determinismo.cjs), que es como se prueba que es determinista.
//
// Viene de canal/plantilla/motor.js del experimento video_1, generalizado para el estudio:
// - el paso de integración sale de G.fps, no de un 1/24 fijo;
// - no lleva nada de ningún canal: ni personajes, ni colores, ni textos. Lo que cambia de un canal a otro
//   llega en el GUION (lib/escena/compone.py lo escribe), y lo que el GUION debe declarar se exige sin
//   defecto (F4.9): si falta, crea() lanza y dice qué escribir.
// - desde F6.2b tampoco lleva las MAGNITUDES del movimiento (lo que rebota quien habla, la respiración, el
//   balanceo al andar, la amplitud de cada evento, lo que tarda en entrar un rótulo): salían de calibrar a
//   los personajes de video_1 y eran la decisión de un canal heredada en silencio (auditoría de F6.2a,
//   recomendación 5). Las declara el GUION en `movimiento` (ver MOVIMIENTO), y cada actor o evento las
//   puede sobrescribir con sus rasgos o sus campos. Lo que sigue aquí es la FORMA de cada movimiento (la
//   risa es un rebote a 2,6 Hz que se apaga, el temblor va a 9 Hz): eso define la palabra, no un estilo.
//
// Un vídeo son planos (un fondo con su cámara) que se encadenan con transiciones. En cada plano, los actores
// siguen su pista de claves y cambian de postura; el motor les añade el movimiento secundario que haría un
// animador: respiración, balanceo al andar, rebote al hablar cuando suena su frase, y ruedas que giran según
// lo que avanza el actor que las lleva.
(function (raiz, fabrica) {
  if (typeof module === "object" && module.exports) module.exports = fabrica();
  else raiz.Motor = fabrica();
})(typeof self !== "undefined" ? self : this, function () {
  const TAU = Math.PI * 2;
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const lerp = (a, b, p) => a + (b - a) * p;

  const EASE = {
    lineal: (p) => p,
    suave: (p) => p * p * (3 - 2 * p),
    inout: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
    sale: (p) => 1 - Math.pow(1 - p, 3),
    entra: (p) => p * p * p,
    rebote: (p) => {
      const c1 = 1.70158, c3 = c1 + 1;
      return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2);
    },
    elastico: (p) => (p === 0 || p === 1 ? p : Math.pow(2, -10 * p) * Math.sin((p * 10 - 0.75) * (TAU / 3)) + 1),
    // Las del motor de láminas (lib/motion.py → _easing_expr, F6.8): su «ease_in» y su «ease_out», cuadráticas. Su
    // «ease_in_out» es el smoothstep, que aquí ya es «suave».
    acelera: (p) => p * p,
    frena: (p) => 1 - (1 - p) * (1 - p),
  };

  function busca(claves, t) {
    let lo = 0, hi = claves.length - 1, r = -1;
    while (lo <= hi) {
      const m = (lo + hi) >> 1;
      if (claves[m].t <= t) { r = m; lo = m + 1; } else hi = m - 1;
    }
    return r;
  }

  // Cada clave lleva sus campos desde el valor de la clave anterior hasta el suyo durante [t, t + tr].
  // Quien escribe el GUION arrastra los campos que una clave no cambia, así que todas las claves están
  // completas. De dos claves en el mismo instante solo cuenta la transición de la última (la primera salta).
  function pista(claves, t, campos) {
    const i = busca(claves, t);
    const k = claves[Math.max(0, i)];
    const out = {};
    if (i <= 0) { for (const c of campos) out[c] = k[c]; return out; }
    const a = claves[i - 1];
    const p = k.tr > 0 ? clamp((t - k.t) / k.tr, 0, 1) : 1;
    const e = EASE[k.e || "inout"](p);
    for (const c of campos) out[c] = lerp(a[c], k[c], e);
    return out;
  }

  const CAMPOS = ["x", "y", "s", "r", "op", "flip", "ancho", "dz"];

  // Lo que el GUION tiene que declarar, sin defecto (F4.9). La cámara en mano es estilo, así que la decide
  // quien escribe el GUION: 0 la apaga y 1 es la amplitud con la que se calibró el motor.
  const OBLIGATORIOS = {
    fps: "fotogramas por segundo del render (p. ej. 24): el paso de integración sale de aquí",
    marco: "tamaño del fotograma, {w, h} en px",
    fundido: "segundos del fundido entre dos posturas de un actor",
    camara_en_mano: "amplitud de la cámara en mano (0 la apaga, 1 es la calibrada)",
    movimiento: "las magnitudes del movimiento secundario y de los eventos (ver Motor.MOVIMIENTO)",
    planos: "la lista de planos",
  };

  // Lo que el GUION declara en `movimiento`, ruta → qué es (F6.2b). Todas son números y ninguna tiene
  // defecto: un canal que no las declare no hereda las de otro, para (F4.9). Un actor puede sobrescribir
  // las suyas con sus rasgos (v_anda, paso, bote, charla, respira) y un evento con sus campos (a, r, h, n, f).
  const MOVIMIENTO = {
    "anda.v": "px/s a los que el balanceo de andar llega al máximo; también es «ir corriendo» para las mallas",
    "anda.paso": "pasos por segundo al andar (Hz)",
    "anda.bote": "px que sube y baja al andar",
    "anda.balanceo": "grados que se balancea al andar",
    "habla.rebote": "px que rebota quien habla mientras suena su frase",
    "habla.frecuencia": "rebotes por segundo al hablar (Hz)",
    "habla.cabeceo": "grados que cabecea quien habla",
    "habla.cabeceo_frecuencia": "cabeceos por segundo al hablar (Hz)",
    "habla.sube": "s que tarda en empezar a rebotar cuando empieza su frase",
    "habla.baja": "s que tarda en pararse cuando acaba su frase",
    "respira.amplitud": "fracción de escala vertical con que respira un personaje (actor con pj)",
    "respira.periodo": "s de una respiración",
    "eventos.risa.a": "px del rebote de una risa",
    "eventos.tiembla.a": "px del temblor",
    "eventos.ladea.r": "grados que se ladea",
    "eventos.bote.h": "px de alto de cada bote",
    "eventos.bote.n": "botes de un evento «bote»",
    "eventos.asiente.a": "px que baja la cabeza al asentir",
    "eventos.bombea.a": "px que baja al bombear",
    "eventos.bombea.f": "bombeos por segundo (Hz)",
    "eventos.estira.a": "fracción de escala que se estira",
    "eventos.menea.a": "grados que se menea una pieza",
    "eventos.menea.f": "meneos por segundo (Hz)",
    "elementos.entra": "s que tarda en entrar un elemento (su «di»)",
    "elementos.sale": "s que tarda en salir un elemento (su «ds»)",
    "elementos.trazo": "s que tarda en dibujarse un trazo (su «trazo_d»)",
    "elementos.campana": "s entre dos sacudidas de una campana (su «campana_p»)",
  };
  // Las que DIVIDEN (un tiempo de subida, un periodo, una velocidad de referencia): con 0 el motor daría NaN, y
  // `clamp` no filtra NaN, así que la figura o el rótulo desaparecerían sin error (auditoría de F6.2b, rec. 1).
  // Tienen que ser > 0. «elementos.sale» no está: con 0 la salida no llega a calcularse (t > t1 − 0 es t > t1,
  // y ahí el elemento ya no se pinta).
  const DIVISORES = ["anda.v", "habla.sube", "habla.baja", "respira.periodo", "elementos.entra", "elementos.trazo",
    "elementos.campana"];
  // Y lo mismo para lo que un actor o un elemento sobrescribe de ellas.
  const RASGOS_DIVISORES = ["v_anda"];
  const CAMPOS_DIVISORES_DE_ELEMENTO = ["di", "trazo_d", "campana_p"];
  function enRuta(obj, ruta) {
    return ruta.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
  }

  // Los tipos que el motor sabe mover. Uno que no esté aquí no se ignora: crea() para (auditoría de F6.2a).
  // Antes, una pieza de un tipo desconocido salía sin deformar y un evento desconocido no hacía nada, sin
  // que nadie se enterase: un rig con el nombre viejo «perro» habría salido rígido.
  const TIPOS_DE_MALLA = ["pierna", "cadena", "cuadrupedo"];
  const TIPOS_DE_EVENTO = ["salto", "risa", "tiembla", "ladea", "bote", "asiente", "bombea", "estira", "menea"];
  // Lo mismo para las entradas, salidas y bucles de los elementos y la entrada de los planos (F6.2b): un
  // nombre mal escrito caía en el caso por omisión (un fundido, o quieto) sin que nadie lo viera. «fade»
  // es el fundido, el caso por omisión con nombre.
  const ENTRADAS = ["pop", "sube", "cae", "mancha", "crece", "nada", "fade"];
  // «borra» (F7.10, fila 264) es el borrador que barre la tiza de izquierda a derecha: el elemento no se desvanece,
  // se recorta desde su borde izquierdo (`elemento(...).borra`, que el director pinta como un clip-path).
  const SALIDAS = ["pop", "baja", "nada", "fade", "borra"];
  const BUCLES = ["late", "flota", "tiembla", "gira", "balancea", "deriva", "vuela"];
  // Las cinco últimas son las transiciones de tinta del motor de láminas (lib/motion.py → TRANSITIONS, F6.8), que allí
  // hacía el `xfade` de FFmpeg: `cortina` es su smoothright/left/up, `mancha` su ink_blot, `calado` su dissolve,
  // `viento` su hrwind/hlwind y `papel` su fadewhite.
  const ENTRADAS_DE_PLANO = ["corte", "funde", "barrido", "iris", "cortina", "mancha", "calado", "viento", "papel"];
  // Hacia dónde avanza el frente de las entradas que lo piden. Sin defecto: un plano que entra con una de ellas y no
  // dice hacia dónde, para. «derecha» es que el frente va de izquierda a derecha.
  const DIRECCIONES_DE_ENTRADA = { cortina: ["derecha", "izquierda", "arriba"], viento: ["derecha", "izquierda"] };
  // Las que se hacen con un umbral sobre un campo de gris (una máscara SVG del plano; el campo lo dibuja
  // lib/escena/campos.py y compone.py lo copia en la composición).
  const ENTRADAS_DE_UMBRAL = ["mancha", "calado", "viento"];
  // La forma de cada umbral: alfa = clamp(pendiente·F + corte, 0, 1), con F ∈ [0, 1] el gris del campo y u el progreso
  // LINEAL de la entrada (como el de xfade). Es la forma que define cada palabra, no un estilo:
  // - mancha: la expresión de ink_blot (lib/motion.py → _INK_BLOT_EXPR), (1,2·u − 0,1 − F)/0,18 + 0,5;
  // - calado: el dissolve de xfade, un borde duro de margen 0,025 sobre ruido uniforme, (u·(1 + 2m) − m − F)/m;
  // - viento: el de hrwind y hlwind, (1,2·u − F)/0,2.
  // En u = 0 las tres dan alfa ≤ 0 en todo el campo (se ve el plano saliente) y en u = 1, alfa ≥ 1 (el entrante).
  const MARGEN_CALADO = 0.025;
  const UMBRALES = {
    mancha: (u) => ({ pendiente: -1 / 0.18, corte: (u * 1.2 - 0.1) / 0.18 + 0.5 }),
    calado: (u) => ({
      pendiente: -1 / MARGEN_CALADO,
      corte: (u * (1 + 2 * MARGEN_CALADO) - MARGEN_CALADO) / MARGEN_CALADO,
    }),
    viento: (u) => ({ pendiente: -1 / 0.2, corte: (u * 1.2) / 0.2 }),
  };
  // El sentido del degradado CSS de la cortina: «to right» pone el 0 % a la izquierda, que es donde empieza el frente.
  const HACIA = { derecha: "right", izquierda: "left", arriba: "top" };

  // La dirección de la entrada de un plano: la que piden las que la llevan, ±1 en el barrido (su sentido, como hasta
  // ahora) y ninguna en las demás. Una dirección que no vale no se ignora: caería en el caso por omisión sin que nadie
  // lo viera.
  function validaDireccion(p) {
    const e = p.entra, dirs = DIRECCIONES_DE_ENTRADA[e.tipo];
    if (dirs) {
      if (!dirs.includes(e.dir)) {
        throw new Error(`Motor: el plano «${p.id}» entra con «${e.tipo}» y dir ${JSON.stringify(e.dir)}: tiene que decir hacia dónde (${dirs.join(", ")})`);
      }
    } else if (e.tipo === "barrido") {
      if (e.dir != null && e.dir !== 1 && e.dir !== -1) {
        throw new Error(`Motor: el plano «${p.id}» entra con «barrido» y dir ${JSON.stringify(e.dir)}: su dir es 1 o -1 (el sentido)`);
      }
    } else if (e.dir != null) {
      throw new Error(`Motor: el plano «${p.id}» entra con «${e.tipo}», que no lleva dirección, y trae dir ${JSON.stringify(e.dir)}`);
    }
  }

  function valida(G) {
    const faltan = Object.keys(OBLIGATORIOS).filter((k) => G == null || G[k] == null);
    if (faltan.length) {
      throw new Error("Motor: el GUION no declara " + faltan.map((k) => `«${k}» (${OBLIGATORIOS[k]})`).join(", "));
    }
    if (!(G.fps > 0)) throw new Error(`Motor: fps tiene que ser un número positivo, no ${JSON.stringify(G.fps)}`);
    if (!(G.marco.w > 0 && G.marco.h > 0)) throw new Error("Motor: marco necesita w y h positivos");
    const sinMovimiento = Object.keys(MOVIMIENTO).filter((r) => typeof enRuta(G.movimiento, r) !== "number");
    if (sinMovimiento.length) {
      throw new Error("Motor: el GUION no declara en «movimiento» " +
        sinMovimiento.map((r) => `«${r}» (${MOVIMIENTO[r]})`).join(", ") + ". Sin defecto a propósito (F4.9)");
    }
    const nulos = DIVISORES.filter((r) => !(enRuta(G.movimiento, r) > 0));
    if (nulos.length) {
      throw new Error("Motor: en «movimiento» tienen que ser mayores que 0 " + nulos.map((r) => `«${r}»`).join(", ") +
        ": el motor divide por ellas y con 0 daría NaN");
    }
    for (const [nombre, pz] of Object.entries((G.rig && G.rig.piezas) || {})) {
      if (!TIPOS_DE_MALLA.includes(pz.tipo)) {
        throw new Error(`Motor: la pieza de malla «${nombre}» es de tipo «${pz.tipo}», que el motor no sabe mover (${TIPOS_DE_MALLA.join(", ")})`);
      }
      if (pz.tipo === "cuadrupedo" && !(typeof pz.cola_amp === "number" && typeof pz.cola_freq === "number")) {
        throw new Error(`Motor: la pieza cuadrúpeda «${nombre}» no declara cola_amp y cola_freq (grados y Hz del meneo de la cola)`);
      }
    }
    for (const p of G.planos) {
      if (p.entra && !ENTRADAS_DE_PLANO.includes(p.entra.tipo)) {
        throw new Error(`Motor: el plano «${p.id}» entra con «${p.entra.tipo}», que el motor no sabe hacer (${ENTRADAS_DE_PLANO.join(", ")})`);
      }
      if (p.entra) validaDireccion(p);
      for (const a of p.actores || []) {
        for (const r of RASGOS_DIVISORES) {
          if (a.rasgos && a.rasgos[r] != null && !(a.rasgos[r] > 0)) {
            throw new Error(`Motor: el actor «${a.id}» lleva el rasgo ${r} = ${a.rasgos[r]}, y tiene que ser mayor que 0 (el motor divide por él)`);
          }
        }
        for (const ev of a.eventos || []) {
          if (!TIPOS_DE_EVENTO.includes(ev.tipo)) {
            throw new Error(`Motor: el actor «${a.id}» lleva un evento «${ev.tipo}», que el motor no sabe hacer (${TIPOS_DE_EVENTO.join(", ")})`);
          }
        }
      }
    }
    for (const e of G.elementos || []) {
      for (const c of CAMPOS_DIVISORES_DE_ELEMENTO) {
        if (e[c] != null && !(e[c] > 0)) {
          throw new Error(`Motor: el elemento «${e.id}» lleva ${c} = ${e[c]}, y tiene que ser mayor que 0 (el motor divide por él)`);
        }
      }
      for (const [campo, lista] of [["entra", ENTRADAS], ["sale", SALIDAS], ["bucle", BUCLES]]) {
        if (e[campo] != null && !lista.includes(e[campo])) {
          throw new Error(`Motor: el elemento «${e.id}» lleva ${campo} «${e[campo]}», que el motor no sabe hacer (${lista.join(", ")})`);
        }
      }
      // `fluye` (F7.10) es una velocidad en px por segundo: un texto o un NaN dejarían los guiones quietos sin aviso.
      if (e.fluye != null && !(typeof e.fluye === "number" && Number.isFinite(e.fluye))) {
        throw new Error(`Motor: el elemento «${e.id}» lleva fluye = ${e.fluye}, y tiene que ser una velocidad en px/s`);
      }
    }
  }

  function crea(G) {
    valida(G);
    const MW = G.marco.w, MH = G.marco.h;
    const MANO = G.camara_en_mano;
    const MV = G.movimiento;   // las magnitudes del movimiento, que declara el GUION (MOVIMIENTO)
    const planos = {}, actores = {};
    for (const p of G.planos) {
      planos[p.id] = p;
      for (const a of p.actores) actores[a.id] = { ...a, plano: p };
    }

    // ------------------------------------------------------------ posición
    // Posición en el fondo, con la del padre sumada: su volteo, su escala y su giro se aplican al
    // desplazamiento del hijo (una rueda gira con su cuadro cuando el cuadro se pone del revés).
    function mundo(id, t) {
      const a = actores[id];
      const k = pista(a.pista, t, CAMPOS);
      if (!a.padre) return { x: k.x, y: k.y, s: k.s, r: k.r, op: k.op, flip: k.flip, ancho: k.ancho };
      const p = mundo(a.padre, t);
      const sx = p.flip > 0.5 ? -1 : 1;
      // El ancho del padre (una puerta que se abre) estrecha también al hijo (lo que va pintado en ella).
      const ox = sx * k.x * p.s * p.ancho, oy = k.y * p.s, g = p.r * Math.PI / 180;
      const c = Math.cos(g), s = Math.sin(g);
      return { x: p.x + ox * c - oy * s, y: p.y + ox * s + oy * c, s: k.s * p.s, r: k.r + p.r, op: k.op * p.op,
               flip: Math.abs(k.flip - p.flip), ancho: k.ancho * p.ancho };
    }

    // Distancia recorrida y giro libre, acumulados a G.fps dentro de la ventana de su plano: las ruedas giran
    // según lo que se avanza, sea cual sea el orden en que se pinten los fotogramas. Lo rodado es lo que
    // avanza en horizontal el apoyo del actor raíz: así cabecear o voltear el cuadro, que mueve la rueda en
    // arco, no cuenta como camino.
    const PASO = 1 / G.fps;
    const acumulado = {};
    // Un avance por encima de esta velocidad es un cambio de sitio de golpe (tr 0), no carrera. En video_1 se
    // calibró como 100 px por paso a 24 fps (el paso más largo andaba por 54 px y los saltos de apoyo, de 195
    // en adelante); en velocidad, 2400 px/s, que vale para cualquier fps.
    const SALTO = 2400 * PASO;
    function raiz(id) {
      let r = id;
      while (actores[r].padre) r = actores[r].padre;
      return r;
    }
    function acumula(id) {
      if (acumulado[id]) return acumulado[id];
      const a = actores[id], p = a.plano, base = raiz(id);
      const n = Math.ceil((p.t1 - p.t0) / PASO) + 2;
      const d = new Float64Array(n), g = new Float64Array(n);
      let ant = mundo(base, p.t0), visible = mundo(id, p.t0).op > 0;
      for (let i = 1; i < n; i++) {
        const t = p.t0 + i * PASO, m = mundo(base, t);
        // Avanzar es ir hacia donde mira: hacia la izquierda (flip) la rueda gira al revés.
        const avance = m.flip > 0.5 ? ant.x - m.x : m.x - ant.x;
        d[i] = d[i - 1] + (visible && Math.abs(avance) < SALTO ? avance : 0);
        g[i] = g[i - 1] + pista(a.pista, t, ["giro"]).giro * PASO;
        ant = m;
        visible = mundo(id, t).op > 0;
      }
      return (acumulado[id] = { d, g, t0: p.t0 });
    }
    // Giro propio de una rueda: lo rodado más el giro libre, o solo el libre (una rueda que no rueda).
    function giroPropio(id, t) {
      const a = actores[id], R = a.rasgos || {};
      if (!R.rueda && !R.gira) return 0;
      const ac = acumula(id);
      const rodado = R.rueda ? (lee(ac.d, ac, t) / (R.rueda * a.escala * mundo(id, t).s)) * 180 / Math.PI : 0;
      return rodado + lee(ac.g, ac, t);
    }
    function lee(serie, ac, t) {
      const x = clamp((t - ac.t0) / PASO, 0, serie.length - 1.001), i = Math.floor(x);
      return lerp(serie[i], serie[i + 1], x - i);
    }

    // ------------------------------------------------------------ huesos (mallas, malla-webgpu.js)
    // Cada pieza del rig es una rejilla sobre la imagen de una postura; sus huesos son matrices afines 2x3
    // [a, b, tx, c, d, ty] en px de esa imagen, p' = (a·x + b·y + tx, c·x + d·y + ty), calculadas aquí como
    // función del tiempo.
    const IDENT = [1, 0, 0, 0, 1, 0];
    const GRADO = Math.PI / 180;
    function giroEn(px, py, ang) {
      const c = Math.cos(ang), s = Math.sin(ang);
      return [c, -s, px - c * px + s * py, s, c, py - s * px - c * py];
    }
    function compone(m, n) {
      return [m[0] * n[0] + m[1] * n[3], m[0] * n[1] + m[1] * n[4], m[0] * n[2] + m[1] * n[5] + m[2],
        m[3] * n[0] + m[4] * n[3], m[3] * n[1] + m[4] * n[4], m[3] * n[2] + m[4] * n[5] + m[5]];
    }
    // Lleva el punto `desde` a `hasta` girando `ang` a su alrededor.
    function lleva(desde, hasta, ang) {
      const c = Math.cos(ang), s = Math.sin(ang);
      return [c, -s, hasta[0] - c * desde[0] + s * desde[1], s, c, hasta[1] - s * desde[0] - c * desde[1]];
    }
    const angulo = (a, b) => Math.atan2(b[1] - a[1], b[0] - a[0]);
    // Lo que ha avanzado el actor y lo deprisa que va (0 quieto, 1 corriendo). «Corriendo» es la misma
    // velocidad a la que su balanceo de andar llega al máximo: la suya (rasgo v_anda) o la del GUION.
    function rodado(id, t) { const ac = acumula(id); return lee(ac.d, ac, t); }
    function rapidez(id, t) {
      const R = actores[id].rasgos || {};
      return clamp(Math.abs(rodado(id, t + 0.1) - rodado(id, t - 0.1)) / 0.2 / (R.v_anda ?? MV.anda.v), 0, 1);
    }

    // Pierna que pedalea: el tobillo sigue al pedal, que da vueltas en torno a la biela según lo que avanza
    // el actor, y la rodilla sale de la cinemática inversa de dos huesos (cadera-rodilla y rodilla-tobillo),
    // doblando hacia el mismo lado que en la imagen. `fase` adelanta el pedal (la pierna de lejos va media
    // vuelta por delante). `px_vuelta` es lo que se avanza por vuelta de pedal, en px de la imagen y no del
    // fondo: así pedalea igual sobre fondos de otra escala.
    function pierna(p, id, t) {
      const H = p.cadera, K0 = p.rodilla, A0 = p.tobillo, B = p.biela;
      const L1 = Math.hypot(K0[0] - H[0], K0[1] - H[1]), L2 = Math.hypot(A0[0] - K0[0], A0[1] - K0[1]);
      const radio = Math.hypot(A0[0] - B[0], A0[1] - B[1]);
      const a = actores[id], k = (a.posturas[p.post] || {}).k || 1;   // el mismo k con que compone.py reduce la postura
      const enImagen = rodado(id, t) * k / (a.escala * mundo(id, t).s);
      const fase = angulo(B, A0) + (p.fase || 0) + enImagen / p.px_vuelta * 2 * Math.PI;
      const A = [B[0] + radio * Math.cos(fase), B[1] + radio * Math.sin(fase)];
      const d = clamp(Math.hypot(A[0] - H[0], A[1] - H[1]), Math.abs(L1 - L2) + 1, L1 + L2 - 1);
      const base = angulo(H, A), abre = Math.acos(clamp((L1 * L1 + d * d - L2 * L2) / (2 * L1 * d), -1, 1));
      const base0 = angulo(H, A0), d0 = Math.hypot(A0[0] - H[0], A0[1] - H[1]);
      const abre0 = Math.acos(clamp((L1 * L1 + d0 * d0 - L2 * L2) / (2 * L1 * d0), -1, 1));
      const lado = Math.abs(base0 + abre0 - angulo(H, K0)) < Math.abs(base0 - abre0 - angulo(H, K0)) ? 1 : -1;
      const K = [H[0] + L1 * Math.cos(base + lado * abre), H[1] + L1 * Math.sin(base + lado * abre)];
      const muslo = giroEn(H[0], H[1], angulo(H, K) - angulo(H, K0));
      const espinilla = lleva(K0, K, angulo(K, A) - angulo(K0, A0));
      const pie = lleva(A0, A, 0);   // el pie va plano sobre el pedal
      return [muslo, espinilla, pie];
    }

    // Cadena (una cola, una rama): una onda que recorre los huesos de la raíz a la punta, más amplia cuanto más
    // deprisa va quien la lleva.
    function cadenaHuesos(arts, t, amp, freq, fase, extra) {
      const out = [];
      let m = IDENT;
      for (let k = 0; k < arts.length - 1; k++) {
        const a = amp * (1 + extra) * Math.sin(t * TAU * freq + fase - 0.7 * k) * GRADO;
        m = compone(m, giroEn(arts[k][0], arts[k][1], a));
        out.push(m);
      }
      return out;
    }

    // Matrices de los huesos de la pieza `p` del actor `id` en el instante t.
    function huesos(p, id, t) {
      if (p.tipo === "pierna") return pierna(p, id, t);
      if (p.tipo === "cadena") return cadenaHuesos(p.arts, t, p.amp, p.freq, p.fase || 0, 0.8 * rapidez(id, t));
      if (p.tipo === "cuadrupedo") {
        // Hueso 0, el cuerpo quieto; luego una por pata, que gira sobre su hombro o su cadera al ritmo de la
        // zancada (una cada `px_zancada` de avance); y la cola al final, con el meneo que declara la pieza.
        const v = rapidez(id, t), zancada = TAU * Math.abs(rodado(id, t)) / p.px_zancada;
        const patas = p.patas.map((pa) => giroEn(pa.art[0], pa.art[1], p.amp_pata * v * Math.sin(zancada + pa.fase) * GRADO));
        return [IDENT, ...patas, ...cadenaHuesos(p.cola, t, p.cola_amp, p.cola_freq, 0, v)];
      }
      // valida() ya lo impide en el GUION; esto cubre una pieza que llegue por otro camino.
      throw new Error(`Motor: tipo de malla «${p.tipo}» desconocido`);
    }

    // ------------------------------------------------------------ habla
    const habla = G.habla || {};
    function hablando(pj, t) {
      const lista = habla[pj];
      if (!lista) return 0;
      const i = busca(lista, t);
      if (i < 0) return 0;
      const [a, b] = [lista[i].t, lista[i].t1];
      return t <= b ? Math.min(clamp((t - a) / MV.habla.sube, 0, 1), clamp((b - t) / MV.habla.baja, 0, 1)) : 0;
    }

    // Cada evento con sus campos o, si no los trae, con las magnitudes del GUION (MV.eventos).
    function eventos(lista, t) {
      const E = MV.eventos;
      let y = 0, x = 0, r = 0, s = 1;
      for (const ev of lista || []) {
        if (t < ev.t || t > ev.t + ev.d) continue;
        const p = (t - ev.t) / ev.d, u = t - ev.t;
        if (ev.tipo === "salto") y -= ev.h * 4 * p * (1 - p);
        else if (ev.tipo === "risa") { y -= Math.abs(Math.sin(u * TAU * 2.6)) * (ev.a ?? E.risa.a) * (1 - p * 0.3); r += Math.sin(u * TAU * 2.6) * 1.5; }
        else if (ev.tipo === "tiembla") x += Math.sin(u * TAU * 9) * (ev.a ?? E.tiembla.a) * (1 - p);
        else if (ev.tipo === "ladea") r += (ev.r ?? E.ladea.r) * Math.sin(Math.PI * p);
        else if (ev.tipo === "bote") y -= Math.abs(Math.sin(Math.PI * p * (ev.n ?? E.bote.n))) * (ev.h ?? E.bote.h) * (1 - p);
        else if (ev.tipo === "asiente") y += Math.sin(u * TAU * 2) * (ev.a ?? E.asiente.a) * (1 - p);
        else if (ev.tipo === "bombea") y += Math.abs(Math.sin(u * TAU * (ev.f ?? E.bombea.f))) * (ev.a ?? E.bombea.a);
        else if (ev.tipo === "estira") s *= 1 + (ev.a ?? E.estira.a) * Math.sin(Math.PI * p);
        // Oscilación sobre el pivote de la pieza (colas, ramas): con entrada y salida suaves.
        else if (ev.tipo === "menea") r += (ev.a ?? E.menea.a) * Math.sin(u * TAU * (ev.f ?? E.menea.f) + (ev.fase || 0)) * Math.min(1, u / 0.3, (ev.d - u) / 0.3);
      }
      return { x, y, r, s };
    }

    // Estado de un actor: posición final, escala, giro, opacidad de cada postura.
    function actor(id, t) {
      const a = actores[id], R = a.rasgos || {};
      const m = mundo(id, t);
      const i = busca(a.pista, t), k = a.pista[Math.max(0, i)];
      const ant = i > 0 ? a.pista[i - 1].post : k.post;
      // fp 0 es un corte; sin fp, el fundido que declara el GUION.
      const fp = k.fp != null ? k.fp : G.fundido;
      const f = ant !== k.post && fp > 0 ? clamp((t - k.t) / fp, 0, 1) : 1;
      // Balanceo al andar, por la velocidad (diferencias finitas). Las magnitudes, las del actor (sus
      // rasgos) o las del GUION (MV).
      const m0 = mundo(id, t - 0.06), m1 = mundo(id, t + 0.06);
      const v = Math.hypot(m1.x - m0.x, m1.y - m0.y) / 0.12;
      const anda = R.anda ? clamp(v / (R.v_anda ?? MV.anda.v), 0, 1) : 0;
      const fase = t * TAU * (R.paso ?? MV.anda.paso);
      const bob = -Math.abs(Math.sin(fase)) * (R.bote ?? MV.anda.bote) * anda;
      const ev = eventos(a.eventos, t);
      const h = a.pj ? hablando(a.pj, t) : 0;
      const charla = h * (Math.sin(t * TAU * MV.habla.frecuencia) * 0.5 + 0.5) * (R.charla ?? MV.habla.rebote);
      // Respira quien es un personaje (pj); un objeto no, salvo que su rasgo «respira» diga otra cosa.
      const respira = R.respira != null ? R.respira : a.pj ? MV.respira.amplitud : 0;
      const resp = 1 + respira * Math.sin(t * TAU / MV.respira.periodo + (R.fase || 0));
      const out = {
        x: m.x + ev.x, y: m.y + bob + ev.y - charla, s: m.s * ev.s, op: m.op, flip: m.flip, ancho: m.ancho,
        dz: Math.round(pista(a.pista, t, ["dz"]).dz),
        r: m.r + ev.r + Math.sin(fase) * MV.anda.balanceo * anda +
          h * Math.sin(t * TAU * MV.habla.cabeceo_frecuencia) * MV.habla.cabeceo,
        resp, post: k.post, ant, f,
      };
      // «hereda» [id, t]: una rueda que sustituye a otra (la que se suelta del cuadro) empieza con el giro que
      // aquella llevaba en ese instante.
      if (R.rueda || R.gira || R.hereda) out.giro = giroPropio(id, t) + (R.hereda ? giroPropio(R.hereda[0], R.hereda[1]) : 0);
      // Una pieza del mismo dibujo va pegada a lo que se ve del padre: su rebote al hablar, su balanceo y su
      // respiración, que mundo() no incluye.
      if (R.pieza && a.padre) {
        const P = actor(a.padre, t), M = mundo(a.padre, t);
        const g = (P.r - M.r) * Math.PI / 180, c = Math.cos(g), sn = Math.sin(g);
        const ox = out.x - M.x, oy = (out.y - M.y) * P.resp;
        out.x = P.x + ox * c - oy * sn;
        out.y = P.y + ox * sn + oy * c;
        out.r += P.r - M.r;
        out.dz += P.dz;   // si el padre pasa por delante de otro (dz), su pieza pasa con él
      }
      return out;
    }

    // ------------------------------------------------------------ cámara
    function centro(k, t) {
      let x = k.cx, y = k.cy;
      if (k.sigue) { const p = mundo(k.sigue, t); x += p.x; y += p.y; }
      return [x, y];
    }
    function camara(p, t) {
      const W = p.fondo.w, H = p.fondo.h, BASE = MW / W, cl = p.camara;
      const i = Math.max(0, busca(cl, t));
      const k = cl[i];
      let [x, y] = centro(k, t), z = k.z;
      if (i > 0 && k.tr > 0 && t < k.t + k.tr) {
        const a = cl[i - 1];
        const e = EASE[k.e || "inout"](clamp((t - k.t) / k.tr, 0, 1));
        const [ax, ay] = centro(a, t);
        x = lerp(ax, x, e); y = lerp(ay, y, e);
        z = Math.exp(lerp(Math.log(a.z), Math.log(k.z), e));
      }
      // Cámara en mano muy suave, para que ningún plano parezca congelado; su amplitud la declara el GUION.
      x += MANO * ((14 / z) * Math.sin(t * 0.13) + (7 / z) * Math.sin(t * 0.31 + 1));
      y += MANO * (9 / z) * Math.sin(t * 0.17 + 2);
      z *= 1 + MANO * 0.006 * Math.sin(t * 0.11);
      const s = BASE * Math.max(z, MH / H / BASE);
      const vw = MW / s, vh = MH / s;
      x = clamp(x, vw / 2, W - vw / 2);
      y = clamp(y, vh / 2, H - vh / 2);
      return { tx: MW / 2 - x * s, ty: MH / 2 - y * s, s };
    }

    // Entrada de un plano sobre el anterior. Lo que el director aplica al nodo del plano:
    // - op, x (barrido) e iris (un círculo de clip-path, en %);
    // - cortina: el degradado de su máscara, {hacia, opaco, transparente} (% del lado), o null cuando ha entrado;
    // - umbral: {pendiente, corte} del feFuncA de su máscara SVG (mancha, calado, viento), o null cuando ha entrado;
    // - papel: la opacidad del velo del plano (su color lo pone el canal), o null si no entra con papel.
    // Con u < 0,5 el plano sube con su velo opaco encima (se ve el blanco sobre el saliente); luego el velo baja.
    function entradaPlano(p, t) {
      const e = p.entra || { tipo: "corte", d: 0 };
      const u = e.d > 0 ? clamp((t - p.t0) / e.d, 0, 1) : 1;
      const q = EASE.inout(u);
      const r = { op: 1, x: 0, iris: null, cortina: null, umbral: null, papel: null };
      if (e.tipo === "funde") r.op = q;
      else if (e.tipo === "barrido") r.x = (1 - q) * MW * (e.dir || 1);
      else if (e.tipo === "iris") r.iris = u < 1 ? q * 120 : null;
      else if (e.tipo === "cortina") {
        r.cortina = u < 1 ? { hacia: HACIA[e.dir], opaco: (2 * u - 1) * 100, transparente: 2 * u * 100 } : null;
      } else if (UMBRALES[e.tipo]) r.umbral = u < 1 ? UMBRALES[e.tipo](u) : null;
      else if (e.tipo === "papel") {
        r.op = u < 0.5 ? EASE.suave(u / 0.5) : 1;
        r.papel = u < 0.5 ? 1 : 1 - EASE.suave((u - 0.5) / 0.5);
      }
      return r;
    }

    // ------------------------------------------------------------ elementos
    function entrada(e, u) {
      const p = clamp(u / (e.di ?? MV.elementos.entra), 0, 1);
      switch (e.entra) {
        case "pop": return { s: EASE.rebote(p), o: clamp(p * 3, 0, 1), y: 0 };
        case "sube": return { s: 1, o: EASE.sale(p), y: (1 - EASE.sale(p)) * 60 };
        case "cae": return { s: 1, o: clamp(p * 4, 0, 1), y: -(1 - EASE.rebote(p)) * 220 };
        case "mancha": return { s: p < 0.6 ? EASE.sale(p / 0.6) * 1.18 : lerp(1.18, 1, (p - 0.6) / 0.4), o: 1, y: 0 };
        case "crece": return { s: EASE.sale(p), o: 1, y: 0 };
        case "nada": return { s: 1, o: 1, y: 0 };
        default: return { s: 1, o: EASE.suave(p), y: 0 };
      }
    }
    function salida(e, u) {
      const p = clamp(u / (e.ds ?? MV.elementos.sale), 0, 1);
      switch (e.sale) {
        case "pop": return { s: 1 - EASE.entra(p), o: 1 - p, y: 0 };
        case "baja": return { s: 1, o: 1 - p, y: p * 60 };
        case "nada": return { s: 1, o: 1, y: 0 };
        // El borrador: la parte del elemento ya barrida, de 0 a 1 desde su borde izquierdo, con una curva suave.
        case "borra": return { s: 1, o: 1, y: 0, borra: EASE.suave(p) };
        default: return { s: 1, o: 1 - EASE.suave(p), y: 0 };
      }
    }
    function bucle(e, u) {
      const a = e.amp || 1;
      switch (e.bucle) {
        case "late": return { s: 1 + 0.05 * a * Math.sin(u * TAU * 1.3), r: 0, y: 0, x: 0 };
        case "flota": return { s: 1, r: Math.sin(u * TAU * 0.4) * 2 * a, y: Math.sin(u * TAU * 0.5) * 10 * a, x: 0 };
        case "tiembla": return { s: 1, r: Math.sin(u * TAU * 7) * 3 * a, y: 0, x: 0 };
        case "gira": return { s: 1, r: u * 90 * a, y: 0, x: 0 };
        case "balancea": return { s: 1, r: Math.sin(u * TAU * 0.8) * 8 * a, y: 0, x: 0 };
        case "deriva": return { s: 1, r: 0, y: Math.sin(u * TAU * 0.07) * 6 * a, x: u * 14 * a };
        case "vuela": return { s: 1, r: Math.sin(u * TAU * 3) * 6, y: Math.sin(u * TAU * 0.3) * 40 * a, x: u * 220 * a };
        default: return { s: 1, r: 0, y: 0, x: 0 };
      }
    }
    function elemento(e, t) {
      if (t < e.t0 || t > e.t1) return null;
      const u = t - e.t0, ds = e.ds ?? MV.elementos.sale;
      const i = entrada(e, u);
      const o = t > e.t1 - ds && e.sale !== "nada" ? salida(e, t - (e.t1 - ds)) : { s: 1, o: 1, y: 0 };
      const b = bucle(e, u);
      const r = { u, o: i.o * o.o, x: b.x, y: i.y + o.y + b.y, r: b.r, s: i.s * o.s * b.s, trazo: null, cuenta: null, campana: null, aguja: null, fluye: null, borra: null };
      // Lo barrido por el borrador (F7.10): null mientras no se borra, así el director quita el clip en cualquier orden.
      if (o.borra != null) r.borra = o.borra;
      if (e.trazo) r.trazo = (1 - EASE.inout(clamp((u - (e.trazo_t || 0)) / (e.trazo_d ?? MV.elementos.trazo), 0, 1))) * 1000;
      // Los guiones de una flecha que fluye (F7.10): su desfase avanza `fluye` px por segundo desde que el elemento
      // entra, en el sentido del trazo. El dibujo de los guiones (`stroke-dasharray`) es del CSS del canal, y como el
      // patrón se repite, el bucle no tiene costura.
      if (e.fluye != null) r.fluye = -u * e.fluye;
      if (e.contador) r.cuenta = Math.round(lerp(e.contador.de, e.contador.a, clamp((u - e.contador.t) / e.contador.d, 0, 1)));
      if (e.aguja) r.aguja = e.aguja_v ? u * e.aguja_v : Math.floor(u * 2) * 30;
      if (e.campana) r.campana = campana(e, t);
      return r;
    }
    function campana(e, t) {
      const uu = t - (e.campana_t != null ? e.campana_t : e.t0);
      if (uu < 0) return 0;
      const fase = uu % (e.campana_p ?? MV.elementos.campana);
      const env = fase < 1.2 ? Math.sin(Math.PI * fase / 1.2) : 0;
      return Math.sin(uu * TAU * 4.5) * 16 * env;
    }

    // ------------------------------------------------------------ karaoke
    function grupo(g, t) {
      const pin = clamp((t - g.t) / 0.22, 0, 1), pout = clamp((g.t1 - t) / 0.18, 0, 1);
      return { o: Math.min(EASE.sale(pin), pout), y: (1 - EASE.sale(pin)) * 18 };
    }
    // Solo brilla la palabra que se pronuncia: se enciende en 60 ms y se apaga en 100 ms al empezar la
    // siguiente (o 0,25 s después si luego hay pausa). g.w[n] es [inicio, fin, …]; lo que sigue a los dos
    // tiempos (el texto y quién habla) es para el DOM y el motor no lo lee.
    function palabra(g, n, t) {
      const [a, b] = g.w[n];
      const siguiente = n + 1 < g.w.length ? g.w[n + 1][0] : b + 0.25;
      const fin = Math.max(a + 0.12, Math.min(siguiente, b + 0.25));
      if (t < a || t > fin) return 0;
      return Math.min(clamp((t - a) / 0.06, 0, 1), clamp((fin - t) / 0.1, 0, 1));
    }

    return { actor, mundo, camara, entradaPlano, elemento, grupo, palabra, planos, actores, huesos };
  }

  return {
    crea, valida, OBLIGATORIOS, MOVIMIENTO, DIVISORES, RASGOS_DIVISORES, CAMPOS_DIVISORES_DE_ELEMENTO,
    TIPOS_DE_MALLA, TIPOS_DE_EVENTO, ENTRADAS, SALIDAS, BUCLES,
    ENTRADAS_DE_PLANO, DIRECCIONES_DE_ENTRADA, ENTRADAS_DE_UMBRAL, EASE, clamp, lerp, busca, pista,
  };
});
