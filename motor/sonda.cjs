// Sonda de una composición del motor de escena (F6.2a): la abre en el Chrome con WebGPU ANTES de renderizar y
// dice si está lista para el render.
//
// Uso: node --require motor/sin-red.cjs motor/sonda.cjs <carpeta> --chrome <exe> [--timeout <ms>]
//      [--permite 127.x.x.x:<puerto>]...
//
// Qué hace:
// - sirve la carpeta en 127.0.0.1 con un servidor propio (como HyperFrames, que también la sirve por
//   loopback: abrirla como file:// haría que WebGPU rechazase las texturas por origen opaco);
// - abre index.html con el Chrome del manifiesto y las opciones de GPU que HyperFrames usa en Windows con
//   hardware (ANGLE sobre D3D11, rasterizado por GPU, WebGPU y sin lista negra);
// - intercepta TODA petición y deja pasar solo data:, blob:, file: y la de su propio servidor; el resto se
//   apunta y se aborta, así que no sale (decisión 6). Además, Chrome arranca con un proxy muerto en
//   127.0.0.1:9: si algo esquivara la intercepción (una petición del propio navegador, por ejemplo), iría a
//   ese proxy y fallaría, en vez de salir;
// - espera a que la composición registre window.__timelines.main (el director lo hace al terminar de cargar
//   las mallas);
// - devuelve un JSON por la salida estándar con las peticiones remotas, `data-mallas-error`, los errores de
//   consola, las imágenes que no decodifican, el adaptador WebGPU y si se registró la línea de tiempo.
//   Una imagen que existe pero no decodifica no deja error de consola: se mira aparte (auditoría de F6.2a).
// Código de salida: 0 si todo está limpio, 1 si encontró algún problema, 2 si no pudo ni probar.
//
// `--permite` añade otro origen de loopback (127.0.0.0/8) a lo que pasa. No existe para producción: es para
// el control negativo de la suite, que tiene que demostrar que su servidor de 127.0.0.2 SÍ recibe la
// petición cuando nadie la corta. Nada fuera de loopback se puede permitir.
"use strict";

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const puppeteer = require("puppeteer-core");

const TIPOS = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".cjs": "text/javascript",
  ".css": "text/css; charset=utf-8", ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml",
  ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".mp4": "video/mp4",
  ".webm": "video/webm", ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf",
};

// Las mismas que HyperFrames pone en win32 con GPU de hardware (getBrowserGpuArgs), más WebGPU.
const OPCIONES_GPU = [
  "--use-gl=angle", "--use-angle=d3d11", "--enable-gpu-rasterization", "--enable-unsafe-webgpu",
  "--ignore-gpu-blocklist", "--enable-webgl",
];
// Un proxy donde no escucha nadie: lo que no sea loopback y escape a la intercepción, no llega a salir.
const PROXY_MUERTO = "--proxy-server=http://127.0.0.1:9";

function argumentos(lista) {
  const r = { carpeta: null, chrome: null, timeout: 30000, permite: [] };
  for (let i = 0; i < lista.length; i++) {
    const a = lista[i];
    if (a === "--chrome") r.chrome = lista[++i];
    else if (a === "--timeout") r.timeout = Number(lista[++i]);
    else if (a === "--permite") r.permite.push(lista[++i]);
    else if (!r.carpeta) r.carpeta = a;
    else throw new Error(`argumento de más: ${a}`);
  }
  if (!r.carpeta || !r.chrome) throw new Error("uso: sonda.cjs <carpeta> --chrome <exe> [--timeout ms] [--permite 127.x.x.x:puerto]");
  for (const p of r.permite) {
    if (!/^127\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$/.test(p)) throw new Error(`--permite solo admite loopback (127.0.0.0/8) con puerto: ${p}`);
  }
  if (!(r.timeout > 0)) throw new Error("--timeout tiene que ser un número de ms positivo");
  return r;
}

function sirve(carpeta) {
  const raiz = path.resolve(carpeta);
  const servidor = http.createServer((pet, res) => {
    let ruta;
    try {
      const rel = decodeURIComponent(new URL(pet.url, "http://127.0.0.1").pathname).replace(/^\/+/, "");
      ruta = path.resolve(raiz, rel || "index.html");
    } catch {
      res.writeHead(400).end();
      return;
    }
    if (ruta !== raiz && !ruta.startsWith(raiz + path.sep)) {
      res.writeHead(403).end();
      return;
    }
    fs.readFile(ruta, (err, datos) => {
      if (err) {
        res.writeHead(404).end();
        return;
      }
      res.writeHead(200, { "Content-Type": TIPOS[path.extname(ruta).toLowerCase()] || "application/octet-stream" });
      res.end(datos);
    });
  });
  return new Promise((ok, mal) => {
    servidor.once("error", mal);
    servidor.listen(0, "127.0.0.1", () => ok(servidor));
  });
}

function marco(carpeta) {
  const texto = fs.readFileSync(path.join(carpeta, "index.html"), "utf8");
  const w = /data-width="(\d+)"/.exec(texto), h = /data-height="(\d+)"/.exec(texto);
  return { w: w ? Number(w[1]) : 1920, h: h ? Number(h[1]) : 1080 };
}

async function prueba(opc) {
  const informe = {
    composicion: path.resolve(opc.carpeta), chrome: opc.chrome, version: null, remotas: [], mallas_error: null,
    errores_consola: [], imagenes_rotas: [], adaptador: null, mallas: null, timeline: false, ok: false,
  };
  const { w, h } = marco(opc.carpeta);
  const servidor = await sirve(opc.carpeta);
  const origen = `127.0.0.1:${servidor.address().port}`;
  const permitidos = new Set([origen, ...opc.permite]);
  let navegador = null;
  try {
    navegador = await puppeteer.launch({
      executablePath: opc.chrome,
      headless: true,
      args: ["--no-sandbox", ...OPCIONES_GPU, PROXY_MUERTO, `--window-size=${w},${h}`],
    });
    informe.version = await navegador.version();
    const pagina = await navegador.newPage();
    await pagina.setViewport({ width: w, height: h });
    await pagina.setRequestInterception(true);
    pagina.on("request", (pet) => {
      let pasa = false;
      try {
        const url = new URL(pet.url());
        pasa = ["data:", "blob:", "file:"].includes(url.protocol) || (["http:", "https:", "ws:", "wss:"].includes(url.protocol) && permitidos.has(url.host));
      } catch {
        pasa = false;
      }
      if (pasa) pet.continue();
      else {
        informe.remotas.push(pet.url());
        pet.abort("blockedbyclient");
      }
    });
    pagina.on("console", (m) => {
      if (m.type() === "error") informe.errores_consola.push(m.text());
    });
    pagina.on("pageerror", (e) => informe.errores_consola.push(`[pageerror] ${e && e.message ? e.message : e}`));
    await pagina.goto(`http://${origen}/index.html`, { waitUntil: "load", timeout: opc.timeout });
    try {
      await pagina.waitForFunction(() => !!(window.__timelines && window.__timelines.main), { timeout: opc.timeout });
      informe.timeline = true;
    } catch {
      informe.errores_consola.push(`[sonda] la composición no registró window.__timelines.main en ${opc.timeout} ms`);
    }
    // Lo que la GPU avisa en diferido (device.lost, uncapturederror) llega después del primer pintado.
    await pagina.evaluate(() => new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(ok, 250)))));
    Object.assign(informe, await pagina.evaluate(async () => {
      let adaptador = null;
      if (navigator.gpu) {
        const a = await navigator.gpu.requestAdapter({ powerPreference: "high-performance" });
        if (a) {
          const i = a.info || {};
          adaptador = { vendor: i.vendor, architecture: i.architecture, description: i.description, fallback: !!(i.isFallbackAdapter ?? a.isFallbackAdapter) };
        }
      }
      const raiz = document.documentElement;
      const imagenes_rotas = Array.from(document.images)
        .filter((im) => (im.getAttribute("src") || "") && !im.src.startsWith("data:") && im.complete && im.naturalWidth === 0)
        .map((im) => im.getAttribute("src"));
      return {
        imagenes_rotas,
        mallas_error: raiz.hasAttribute("data-mallas-error") ? raiz.getAttribute("data-mallas-error") : null,
        mallas: window.Mallas ? { adaptador: window.Mallas.adaptador, errores: window.Mallas.errores } : null,
        adaptador,
      };
    }));
  } finally {
    if (navegador) await navegador.close().catch(() => {});
    servidor.close();
  }
  informe.ok = informe.timeline && !informe.remotas.length && !informe.mallas_error && !informe.errores_consola.length &&
    !informe.imagenes_rotas.length;
  return informe;
}

(async () => {
  let opc;
  try {
    opc = argumentos(process.argv.slice(2));
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, fallo: e.message }) + "\n");
    process.exitCode = 2;
    return;
  }
  try {
    const informe = await prueba(opc);
    process.stdout.write(JSON.stringify(informe) + "\n");
    process.exitCode = informe.ok ? 0 : 1;
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, fallo: `la sonda no pudo probar: ${e && e.message ? e.message : e}` }) + "\n");
    process.exitCode = 2;
  }
})();
