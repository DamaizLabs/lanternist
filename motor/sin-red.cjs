// Guarda de red del motor de escena (decisión 6: nada sale del PC salvo la subida a YouTube).
//
// Se carga con `node --require motor/sin-red.cjs` antes de la CLI de HyperFrames. Medido el 28-09-2026
// (addendum fila 199): la CLI 0.8.78 lanza en CADA orden una comprobación de actualizaciones de sus
// «skills» —`git ls-remote` a GitHub y un manifiesto de raw.githubusercontent.com— que ningún interruptor
// apaga, y además trae telemetría (PostHog) y un aviso de versiones (npm).
//
// Qué cubre, y qué no:
// - Toda conexión TCP de Node que no vaya al propio PC se corta antes de resolver el nombre, así que no
//   sale ni la consulta DNS (net, tls, http, https, http2, fetch, WebSocket: todos acaban en
//   net.Socket.connect). El servidor local con el que HyperFrames sirve la composición a Chrome va por
//   127.0.0.1 y pasa.
// - Los procesos Node HIJOS heredan la guarda: se añade a NODE_OPTIONS. La CLI arranca uno en cada render
//   (`runRenderSetupWorker`, sin `--require`), y sin esto quedaba fuera (auditoría de F6.0).
// - `git` sin transporte https (`GIT_ALLOW_PROTOCOL=file`), para el `ls-remote` de las skills.
// - NO cubre otros binarios que lance la CLI (ffmpeg, ffprobe) ni las URL remotas que cargue el propio
//   Chrome: por eso la composición solo referencia ficheros locales (se comprueba en F6.2) y el Chrome se
//   instala una vez, a propósito y con red, con `hyperframes browser ensure`.
"use strict";

const net = require("node:net");

const LOCALES = new Set(["localhost", "127.0.0.1", "::1", "[::1]", ""]);

function esLocal(host) {
  return LOCALES.has(String(host ?? "").toLowerCase());
}

function corta(destino) {
  const error = new Error(`[sin-red] conexión bloqueada a ${destino} (decisión 6: nada sale del PC)`);
  error.code = "ECONNREFUSED";
  return error;
}

// fetch también acaba en net.Socket.connect; se guarda aparte para cortar con un error claro antes de que
// undici intente nada.
const fetchOriginal = globalThis.fetch;
if (typeof fetchOriginal === "function") {
  globalThis.fetch = function fetchSinRed(entrada, opciones) {
    const url = new URL(typeof entrada === "string" || entrada instanceof URL ? entrada : entrada.url);
    if (!esLocal(url.hostname) && url.protocol !== "file:" && url.protocol !== "data:") {
      return Promise.reject(corta(url.host));
    }
    return fetchOriginal.call(this, entrada, opciones);
  };
}

const conectaOriginal = net.Socket.prototype.connect;
net.Socket.prototype.connect = function connectSinRed(...args) {
  const primero = args[0];
  const opciones = Array.isArray(primero) ? primero[0] : primero;
  const host = typeof opciones === "object" && opciones !== null ? opciones.host : typeof args[1] === "string" ? args[1] : "localhost";
  const esTubo = typeof opciones === "object" && opciones !== null && typeof opciones.path === "string";
  if (!esTubo && !esLocal(host)) {
    process.nextTick(() => this.destroy(corta(host)));
    return this;
  }
  return conectaOriginal.apply(this, args);
};

// Los hijos Node: la guarda viaja en NODE_OPTIONS (una sola vez, aunque se cargue en cadena).
// Con barras normales: entre comillas, NODE_OPTIONS toma «\» como escape y el hijo no encontraría el módulo.
const ruta = __filename.replace(/\\/g, "/");
const esta = ruta.includes(" ") ? `"${ruta}"` : ruta;
const opcionesNode = process.env.NODE_OPTIONS ?? "";
if (!opcionesNode.includes(ruta)) {
  process.env.NODE_OPTIONS = `${opcionesNode} --require ${esta}`.trim();
}
process.env.GIT_ALLOW_PROTOCOL = "file";
process.env.HYPERFRAMES_NO_TELEMETRY = "1";
process.env.HYPERFRAMES_NO_UPDATE_CHECK = "1";
process.env.HYPERFRAMES_NO_AUTO_INSTALL = "1";
