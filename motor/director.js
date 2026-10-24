// Director de escena del estudio (F6.2a): aplica al HTML lo que calcula el motor (motor.js).
//
// Viene de canal/plantilla/director.js del experimento video_1, con cuatro cambios:
// - pinta las mallas con malla-webgpu.js (F6.1), que tiene la misma API que malla.js: Mallas.carga(rig) y
//   Mallas.pinta(M, t, aLaVista). Si la GPU falla, malla-webgpu.js marca <html data-mallas-error> y escribe
//   «[mallas] …» en la consola, y lib/escena/render.py para el render en vez de sacar un vídeo sin mallas;
// - crea window.__timelines si no existe, para que la composición también se pueda abrir sin el runtime de
//   HyperFrames (la sonda de motor/sonda.cjs lo hace así);
// - exige al GUION lo que necesita, sin defecto (el motor exige su parte en Motor.crea);
// - tras cada búsqueda de HyperFrames (evento hf-seek) deja al compositor de Chrome `espera_compositor_ms`
//   antes de la captura (lo pone compone.py desde lib/config.py; ver ESCENA_ESPERA_COMPOSITOR_MS).
//   Medido en F6.2a: sin esa espera, con WebGPU en la página, a veces se fotografiaba una capa de texto que
//   se escala antes de volver a rasterizarse, y dos renders del mismo GUION salían distintos. No se repinta
//   nada en el evento (F6.1 midió que repintar rompe el determinismo): solo se espera.
//
// Desde F6.8 pinta también las entradas de tinta de un plano (cortina, mancha, calado, viento y papel), que vienen de
// las transiciones del motor de láminas: ver pintaTinta.
//
// HyperFrames avanza una única interpolación GSAP (el patrón «proxy driver») y cada fotograma llama a pinta(t).
// Los planos son clips de HyperFrames, así que el runtime ya oculta los que están fuera de su ventana; aquí
// solo se pintan los visibles en t.
(function () {
  const G = window.GUION;
  const faltan = ["duracion", "elementos", "karaoke", "transiciones", "espera_compositor_ms"].filter((k) => G == null || G[k] == null);
  if (faltan.length) throw new Error("Director: el GUION no declara " + faltan.map((k) => `«${k}»`).join(", "));
  const M = window.Motor.crea(G);
  window.addEventListener("hf-seek", (e) => e.detail?.waitUntil?.(new Promise((ok) => setTimeout(ok, G.espera_compositor_ms))));
  const { lerp, clamp, busca, EASE } = window.Motor;
  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------ planos y actores
  // Las entradas de tinta (F6.8) se pintan con una máscara en el nodo del plano: la cortina con un degradado y las de
  // umbral con la máscara SVG que compone.py escribe para ese plano (#<plano>-m, con su feFuncA #<plano>-umbral). La de
  // papel, con el velo que compone.py mete en el plano (.papel). Si falta lo que compone tenía que escribir, para.
  const { ENTRADAS_DE_UMBRAL } = window.Motor;
  function deTinta(p) {
    const tipo = (p.entra || {}).tipo;
    const deUmbral = ENTRADAS_DE_UMBRAL.includes(tipo);
    const umbral = deUmbral ? $(p.id + "-umbral") : null;
    const velo = tipo === "papel" ? document.querySelector("#" + p.id + " > .papel") : null;
    if (deUmbral && !umbral) throw new Error(`Director: el plano «${p.id}» entra con «${tipo}» y no está su máscara (#${p.id}-umbral)`);
    if (tipo === "papel" && !velo) throw new Error(`Director: el plano «${p.id}» entra con «papel» y no está su velo (.papel)`);
    return { umbral, velo, enmascara: tipo === "cortina" || deUmbral };
  }
  const planos = G.planos.map((p) => ({
    p,
    ...deTinta(p),
    nodo: $(p.id),
    mundo: document.querySelector("#" + p.id + " > .mundo"),
    actores: p.actores.map((a) => ({
      a,
      nodo: $(a.id),
      // Cada postura es una imagen o, si lleva mallas, un envoltorio con su imagen y sus lienzos.
      imgs: Array.from(document.querySelectorAll("#" + a.id + " > .post")).map((im) => ({ im, post: im.dataset.post })),
    })),
  }));

  // La máscara del plano mientras entra con tinta, y ninguna cuando ya ha entrado. Solo se toca en los planos que entran
  // con una de ellas: los demás no cambian ni un estilo.
  function pintaTinta(P, e) {
    const n = P.nodo;
    if (P.enmascara) {
      let mascara = "none";
      if (e.cortina) {
        const c = e.cortina;
        mascara = `linear-gradient(to ${c.hacia}, black ${c.opaco.toFixed(3)}%, transparent ${c.transparente.toFixed(3)}%)`;
      } else if (e.umbral) {
        P.umbral.setAttribute("slope", e.umbral.pendiente.toFixed(5));
        P.umbral.setAttribute("intercept", e.umbral.corte.toFixed(5));
        mascara = `url(#${P.p.id}-m)`;
      }
      n.style.webkitMaskImage = n.style.maskImage = mascara;
    }
    if (P.velo) P.velo.style.opacity = e.papel.toFixed(3);
  }

  let aLaVista = new Set();   // actores pintados en este fotograma: solo sus mallas se dibujan
  function pintaPlano(P, t) {
    const e = M.entradaPlano(P.p, t);
    P.nodo.style.opacity = e.op.toFixed(3);
    P.nodo.style.transform = e.x ? `translateX(${e.x.toFixed(1)}px)` : "none";
    P.nodo.style.clipPath = e.iris == null ? "none" : `circle(${e.iris.toFixed(2)}% at 50% 50%)`;
    pintaTinta(P, e);
    const c = M.camara(P.p, t);
    P.mundo.style.transform = `translate(${c.tx.toFixed(2)}px, ${c.ty.toFixed(2)}px) scale(${c.s.toFixed(5)})`;
    for (const A of P.actores) {
      const k = M.actor(A.a.id, t);
      A.nodo.style.opacity = k.op.toFixed(3);
      if (k.op <= 0.001) continue;
      aLaVista.add(A.a.id);
      A.nodo.style.zIndex = String(A.a.z + k.dz);
      const esc = A.a.escala * k.s, sx = k.flip > 0.5 ? -1 : 1;
      const giro = k.r + (k.giro || 0);
      A.nodo.style.transform = `translate(${k.x.toFixed(2)}px, ${k.y.toFixed(2)}px) rotate(${giro.toFixed(3)}deg) ` +
        `scale(${(esc * sx * k.ancho).toFixed(5)}, ${(esc * k.resp).toFixed(5)})`;
      for (const I of A.imgs) {
        const o = I.post === k.post ? k.f : I.post === k.ant ? 1 - k.f : 0;
        I.im.style.opacity = o.toFixed(3);
      }
    }
  }

  // ------------------------------------------------------------ elementos
  const elementos = G.elementos.map((e) => {
    const nodo = document.querySelector("#" + e.id + " > .in");
    return {
      e, nodo,
      // Solo los que se borran llevan clip-path: a los demás no se les toca ni un estilo (F7.10).
      borra: e.sale === "borra",
      trazos: nodo ? Array.from(nodo.querySelectorAll(".trazo")) : [],
      fluyen: nodo ? Array.from(nodo.querySelectorAll(".fluye")) : [],
      aguja: nodo && nodo.querySelector(".aguja"),
      campana: nodo && nodo.querySelector(".campana"),
      cuenta: nodo && nodo.querySelector(".cuenta"),
      unidad: nodo && nodo.querySelector(".ud"),
      papelitos: nodo ? Array.from(nodo.querySelectorAll(".pz")) : [],
    };
  });
  function pintaElementos(t) {
    for (const x of elementos) {
      if (!x.nodo || t < x.e.t0 || t > x.e.t1) continue;
      const r = M.elemento(x.e, t);
      if (!r) continue;
      x.nodo.style.opacity = r.o.toFixed(3);
      // `sigue`: el elemento va pegado a un actor (su x, y son relativas al apoyo del actor).
      let sx = 0, sy = 0;
      if (x.e.sigue) { const m = M.mundo(x.e.sigue, t); sx = m.x; sy = m.y; }
      x.nodo.style.transform = `translate(${(r.x + sx).toFixed(2)}px, ${(r.y + sy).toFixed(2)}px) rotate(${r.r.toFixed(2)}deg) scale(${r.s.toFixed(4)})`;
      if (r.trazo != null) for (const tr of x.trazos) tr.style.strokeDashoffset = r.trazo.toFixed(1);
      if (r.fluye != null) for (const f of x.fluyen) f.style.strokeDashoffset = r.fluye.toFixed(1);
      // El borrador barre de izquierda a derecha: se recorta lo ya barrido desde el borde izquierdo. Cada letra de un
      // texto lleva la caja del bloque entero (lib/escena/pizarra.py), así que el frente cae en el mismo sitio en todas
      // sus líneas. Sin borrar, ningún clip: el render busca los fotogramas en cualquier orden y uno anterior no puede
      // heredar el recorte de otro posterior.
      if (x.borra) x.nodo.style.clipPath = r.borra == null ? "none" : `inset(0 0 0 ${(r.borra * 100).toFixed(2)}%)`;
      if (r.aguja != null && x.aguja) x.aguja.style.transform = `rotate(${r.aguja.toFixed(1)}deg)`;
      if (r.campana != null && x.campana) x.campana.style.transform = `rotate(${r.campana.toFixed(2)}deg)`;
      if (r.cuenta != null && x.cuenta) x.cuenta.textContent = String(r.cuenta);
      if (r.cuenta != null && x.unidad) x.unidad.textContent = r.cuenta === 1 ? x.unidad.dataset.uno : x.unidad.dataset.varios;
      for (const p of x.papelitos) {
        const v = +p.dataset.v, giro = +p.dataset.r, d = +p.dataset.d;
        p.style.transform = `translate(${(Math.sin(r.u * 2.2 + d) * 34).toFixed(1)}px, ${(r.u * v).toFixed(1)}px) rotate(${(giro * r.u).toFixed(1)}deg)`;
      }
    }
  }

  // ------------------------------------------------------------ karaoke
  const grupos = G.karaoke.map((g) => {
    const raiz = document.querySelector("#" + g.id + " > .kin");
    return { g, t: g.t, raiz, palabras: raiz ? Array.from(raiz.querySelectorAll(".w")) : [] };
  });
  function pintaKaraoke(t) {
    const i = busca(grupos, t);
    for (let j = Math.max(0, i - 1); j <= Math.min(grupos.length - 1, i + 1); j++) {
      const { g, raiz, palabras } = grupos[j];
      if (t < g.t || t > g.t1 || !raiz) continue;
      const a = M.grupo(g, t);
      raiz.style.opacity = a.o.toFixed(3);
      raiz.style.transform = `translateY(${a.y.toFixed(1)}px)`;
      palabras.forEach((w, n) => {
        const act = M.palabra(g, n, t);
        w.style.setProperty("--a", act.toFixed(3));
        w.style.transform = `translateY(${(-act * 5).toFixed(1)}px) scale(${(1 + act * 0.1).toFixed(3)})`;
      });
    }
  }

  // ------------------------------------------------------------ transiciones
  const transiciones = G.transiciones.map((x) => ({ ...x, nodo: $(x.id) }));
  function pintaTransiciones(t) {
    for (const x of transiciones) {
      if (t < x.t || t > x.t + x.d || !x.nodo) continue;
      const p = (t - x.t) / x.d, pico = Math.sin(Math.PI * p), n = x.nodo;
      if (x.tipo === "iris") {
        const r = p < 0.5 ? lerp(140, 0, p * 2) : lerp(0, 140, p * 2 - 1);
        n.style.webkitMaskImage = n.style.maskImage = `radial-gradient(circle at 50% 50%, transparent ${r.toFixed(2)}%, black ${(r + 0.6).toFixed(2)}%)`;
        n.style.opacity = "1";
      } else if (x.tipo === "luz") {
        n.style.opacity = pico.toFixed(3);
        n.style.transform = `translateX(${lerp(-60, 60, EASE.inout(p)).toFixed(2)}%)`;
      } else if (x.tipo === "destello") {
        n.style.opacity = Math.pow(pico, 1.6).toFixed(3);
      } else if (x.tipo === "papel") {
        n.style.transform = `translateX(${lerp(-130, 130, EASE.inout(p)).toFixed(2)}%) skewX(-14deg)`;
      } else if (x.tipo === "puntos") {
        n.querySelectorAll("circle").forEach((c, k) => {
          const lag = (k % 16) / 16 * 0.3;
          c.setAttribute("r", (clamp((pico - lag) / (1 - lag), 0, 1) * 78).toFixed(1));
        });
      } else if (x.tipo === "barras") {
        n.querySelectorAll(".barra").forEach((b, k) => {
          b.style.transform = `scaleY(${clamp(pico * 1.4 - k * 0.06, 0, 1).toFixed(3)})`;
        });
      }
    }
  }

  // ------------------------------------------------------------ fotograma
  function pinta(t) {
    aLaVista = new Set();
    for (const P of planos) if (t >= P.p.t0 && t <= P.p.t1) pintaPlano(P, t);
    if (window.Mallas) window.Mallas.pinta(M, t, aLaVista);
    pintaElementos(t);
    pintaKaraoke(t);
    pintaTransiciones(t);
  }

  const inicio = G.inicio || 0, duracion = G.duracion;
  const estado = { t: inicio };
  // La línea de tiempo se registra cuando las texturas de las mallas han cargado: así ningún fotograma sale
  // con un lienzo vacío. Si no cargan, malla-webgpu.js ya lo ha marcado (data-mallas-error y la consola) y la
  // línea se registra igual, porque sin ella el render se cuelga en vez de fallar: quien para es render.py.
  const listo = window.Mallas ? window.Mallas.carga(G.rig) : Promise.resolve();
  listo.catch(() => {}).then(() => {
    const tl = gsap.timeline({ paused: true });
    tl.fromTo(estado, { t: inicio }, { t: inicio + duracion, duration: duracion, ease: "none", onUpdate: () => pinta(estado.t) }, 0);
    pinta(inicio);
    window.__pinta = pinta; // para inspección desde la consola
    window.__timelines = window.__timelines || {};
    window.__timelines["main"] = tl;
  });
})();
