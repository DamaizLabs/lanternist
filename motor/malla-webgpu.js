// Mallas deformables en WebGPU/WGSL (F6.1, addendum fila 199): el mismo skinning de dos huesos por vértice
// que malla.js (WebGL) de video_1, con tres cambios:
// - los huesos van en un storage buffer, así que no hay tope de 12;
// - un solo GPUDevice pinta directamente en el <canvas class="malla"> de cada pieza (un GPUCanvasContext
//   por lienzo), sin el lienzo oculto ni la copia a 2D que WebGL necesitaba por su límite de 16 contextos;
// - si la captura de HyperFrames emite su evento hf-seek, se le pasa con waitUntil la promesa del último trabajo
//   de la GPU. El orden entre ese evento y el onUpdate de GSAP no está medido; lo medido en F6.1 es el resultado:
//   72 fotogramas idénticos en dos renders.
//   Se probó REPINTAR dentro del evento y rompió el determinismo (0,0286 % de píxeles distintos entre dos
//   renders): el fotograma se pintaba dos veces y competía con la captura. No se hace.
// - un error de la GPU no pasa en silencio: queda en Mallas.errores, en console.error con «[mallas]» y en
//   <html data-mallas-error>, para que el render lo pare (F6.2) en lugar de sacar un vídeo sin mallas.
// Necesita el Chrome de scripts/instala_chrome_webgpu.ps1: el de HyperFrames no trae las librerías DXC.
// Misma API que malla.js: Mallas.carga(rig) → Promise y Mallas.pinta(M, t, aLaVista).
(function (raiz) {
  const WGSL = /* wgsl */ `
    struct Hueso { f0: vec4f, f1: vec4f };
    struct Pieza { origen: vec2f, tam: vec2f };
    @group(0) @binding(0) var<storage, read> huesos: array<Hueso>;
    @group(0) @binding(1) var<uniform> pieza: Pieza;
    @group(0) @binding(2) var muestreo: sampler;
    @group(0) @binding(3) var textura: texture_2d<f32>;
    struct Salida { @builtin(position) pos: vec4f, @location(0) uv: vec2f };
    fn mueve(i: u32, p: vec2f) -> vec2f {
      let q = vec3f(p, 1.0);
      let h = huesos[i];
      return vec2f(dot(h.f0.xyz, q), dot(h.f1.xyz, q));
    }
    @vertex fn vs(@location(0) pos: vec2f, @location(1) uv: vec2f, @location(2) hueso: vec2f, @location(3) peso: f32) -> Salida {
      let p = mueve(u32(hueso.x + 0.5), pos) * peso + mueve(u32(hueso.y + 0.5), pos) * (1.0 - peso);
      let c = (p - pieza.origen) / pieza.tam;
      var s: Salida;
      s.pos = vec4f(c.x * 2.0 - 1.0, 1.0 - c.y * 2.0, 0.0, 1.0);
      s.uv = uv;
      return s;
    }
    @fragment fn fs(e: Salida) -> @location(0) vec4f { return textureSample(textura, muestreo, e.uv); }`;

  const MUESTRAS = 4; // el antialias: true de WebGL, en MSAA 4×

  function cargaImagen(src) {
    return new Promise((ok, mal) => {
      const im = new Image();
      im.onload = () => ok(im);
      im.onerror = () => mal(new Error("no carga " + src));
      im.src = src;
    });
  }

  const IDENTIDAD = [1, 0, 0, 0, 1, 0];
  let G = null; // { device, pipeline, sampler, formato }
  const piezas = [];
  let ultimo = Promise.resolve();

  function bufer(device, datos, uso) {
    const b = device.createBuffer({ size: Math.ceil(datos.byteLength / 4) * 4, usage: uso | GPUBufferUsage.COPY_DST });
    device.queue.writeBuffer(b, 0, datos.buffer, datos.byteOffset, datos.byteLength);
    return b;
  }

  function geometria(p, imagen, lienzo) {
    const { device, pipeline, sampler, formato } = G;
    const n = p.cols * p.filas, pos = new Float32Array(n * 2), uv = new Float32Array(n * 2);
    const hueso = new Float32Array(n * 2), peso = new Float32Array(n);
    for (let f = 0, k = 0; f < p.filas; f++) {
      for (let c = 0; c < p.cols; c++, k++) {
        const x = p.x + (c / (p.cols - 1)) * p.w, y = p.y + (f / (p.filas - 1)) * p.h;
        pos[2 * k] = x; pos[2 * k + 1] = y;
        uv[2 * k] = (x - p.x) / p.w; uv[2 * k + 1] = (y - p.y) / p.h;
        hueso[2 * k] = p.i0[k]; hueso[2 * k + 1] = p.i1[k]; peso[k] = p.w0[k];
      }
    }
    const indices = new Uint16Array((p.cols - 1) * (p.filas - 1) * 6);
    for (let f = 0, k = 0; f < p.filas - 1; f++) {
      for (let c = 0; c < p.cols - 1; c++) {
        const a = f * p.cols + c, b = a + 1, d = a + p.cols, e = d + 1;
        indices.set([a, b, d, b, e, d], k);
        k += 6;
      }
    }
    const tex = device.createTexture({
      size: [imagen.naturalWidth, imagen.naturalHeight], format: "rgba8unorm",
      usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST | GPUTextureUsage.RENDER_ATTACHMENT,
    });
    // Alfa premultiplicado, como UNPACK_PREMULTIPLY_ALPHA_WEBGL en malla.js.
    device.queue.copyExternalImageToTexture({ source: imagen }, { texture: tex, premultipliedAlpha: true }, [imagen.naturalWidth, imagen.naturalHeight]);
    const nHuesos = Math.max(...p.i0, ...p.i1) + 1;
    const huesos = device.createBuffer({ size: nHuesos * 32, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST });
    const uni = bufer(device, new Float32Array([p.x, p.y, p.w, p.h]), GPUBufferUsage.UNIFORM);
    const grupo = device.createBindGroup({
      layout: pipeline.getBindGroupLayout(0),
      entries: [
        { binding: 0, resource: { buffer: huesos } },
        { binding: 1, resource: { buffer: uni } },
        { binding: 2, resource: sampler },
        { binding: 3, resource: tex.createView() },
      ],
    });
    const ctx = lienzo.getContext("webgpu");
    ctx.configure({ device, format: formato, alphaMode: "premultiplied" });
    const msaa = device.createTexture({ size: [lienzo.width, lienzo.height], sampleCount: MUESTRAS, format: formato, usage: GPUTextureUsage.RENDER_ATTACHMENT });
    return {
      pos: bufer(device, pos, GPUBufferUsage.VERTEX), uv: bufer(device, uv, GPUBufferUsage.VERTEX),
      hueso: bufer(device, hueso, GPUBufferUsage.VERTEX), peso: bufer(device, peso, GPUBufferUsage.VERTEX),
      ib: bufer(device, indices, GPUBufferUsage.INDEX), n: indices.length,
      huesos, nHuesos, grupo, ctx, msaa: msaa.createView(),
    };
  }

  raiz.Mallas = {
    adaptador: null,
    errores: [],
    falla(motivo) {
      const texto = "[mallas] " + motivo;
      this.errores.push(texto);
      console.error(texto);
      document.documentElement.dataset.mallasError = texto;
    },
    async carga(rig) {
      try {
        await this._carga(rig);
      } catch (e) {
        // Sin dispositivo (el caso de las librerías DXC que faltan) el vídeo saldría sin mallas: que se sepa.
        this.falla("no carga: " + e.message);
        throw e;
      }
    },
    async _carga(rig) {
      const lienzos = Array.from(document.querySelectorAll("canvas.malla"));
      if (!rig || !lienzos.length) return;
      if (!navigator.gpu) throw new Error("mallas: el navegador no da WebGPU");
      const adapter = await navigator.gpu.requestAdapter({ powerPreference: "high-performance" });
      if (!adapter) throw new Error("mallas: no hay adaptador WebGPU");
      const info = adapter.info || {};
      this.adaptador = { vendor: info.vendor, architecture: info.architecture, description: info.description, fallback: !!(info.isFallbackAdapter ?? adapter.isFallbackAdapter) };
      const device = await adapter.requestDevice();
      device.lost.then((info) => this.falla("dispositivo perdido: " + info.reason + " " + info.message));
      device.addEventListener("uncapturederror", (e) => this.falla("error de la GPU: " + e.error.message));
      const formato = navigator.gpu.getPreferredCanvasFormat();
      const modulo = device.createShaderModule({ code: WGSL });
      const mezcla = { srcFactor: "one", dstFactor: "one-minus-src-alpha", operation: "add" };
      const pipeline = device.createRenderPipeline({
        layout: "auto",
        vertex: {
          module: modulo, entryPoint: "vs",
          buffers: [
            { arrayStride: 8, attributes: [{ shaderLocation: 0, offset: 0, format: "float32x2" }] },
            { arrayStride: 8, attributes: [{ shaderLocation: 1, offset: 0, format: "float32x2" }] },
            { arrayStride: 8, attributes: [{ shaderLocation: 2, offset: 0, format: "float32x2" }] },
            { arrayStride: 4, attributes: [{ shaderLocation: 3, offset: 0, format: "float32" }] },
          ],
        },
        fragment: { module: modulo, entryPoint: "fs", targets: [{ format: formato, blend: { color: mezcla, alpha: mezcla } }] },
        primitive: { topology: "triangle-list" },
        multisample: { count: MUESTRAS },
      });
      const sampler = device.createSampler({ magFilter: "linear", minFilter: "linear", addressModeU: "clamp-to-edge", addressModeV: "clamp-to-edge" });
      G = { device, pipeline, sampler, formato };
      const nombres = Array.from(new Set(lienzos.map((l) => l.dataset.pieza)));
      const imagenes = Object.fromEntries(await Promise.all(nombres.map(async (n) => [n, await cargaImagen(rig.piezas[n].png)])));
      for (const l of lienzos) {
        const p = rig.piezas[l.dataset.pieza];
        piezas.push({ p, g: geometria(p, imagenes[l.dataset.pieza], l), actor: l.dataset.actor });
      }
      // Cada búsqueda de HyperFrames espera a que la GPU haya terminado el fotograma.
      window.addEventListener("hf-seek", (e) => e.detail?.waitUntil?.(ultimo));
    },
    pinta(M, t, aLaVista) {
      if (!G) return ultimo;
      const { device, pipeline } = G;
      const enc = device.createCommandEncoder();
      for (const pz of piezas) {
        if (!aLaVista.has(pz.actor)) continue;
        const { p, g } = pz;
        const hs = M.huesos(p, pz.actor, t);
        // Tantos huesos como usan los vértices: ni uno más (desbordaría) ni uno menos (colapsaría la malla).
        if (hs.length < g.nHuesos && !pz.avisada) {
          pz.avisada = true;
          this.falla(`${pz.actor}: el motor dio ${hs.length} huesos y la malla usa ${g.nHuesos}`);
        }
        const datos = new Float32Array(g.nHuesos * 8);
        for (let i = 0; i < g.nHuesos; i++) {
          const m = hs[i] ?? IDENTIDAD;
          datos.set([m[0], m[1], m[2], 0, m[3], m[4], m[5], 0], 8 * i);
        }
        device.queue.writeBuffer(g.huesos, 0, datos);
        const pase = enc.beginRenderPass({
          colorAttachments: [{ view: g.msaa, resolveTarget: g.ctx.getCurrentTexture().createView(), clearValue: [0, 0, 0, 0], loadOp: "clear", storeOp: "discard" }],
        });
        pase.setPipeline(pipeline);
        pase.setBindGroup(0, g.grupo);
        pase.setVertexBuffer(0, g.pos);
        pase.setVertexBuffer(1, g.uv);
        pase.setVertexBuffer(2, g.hueso);
        pase.setVertexBuffer(3, g.peso);
        pase.setIndexBuffer(g.ib, "uint16");
        pase.drawIndexed(g.n);
        pase.end();
      }
      device.queue.submit([enc.finish()]);
      ultimo = device.queue.onSubmittedWorkDone();
      return ultimo;
    },
  };
})(typeof self !== "undefined" ? self : this);
