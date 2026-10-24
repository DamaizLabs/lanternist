// Sonda de tests/test_sin_red.py: intenta una conexión y dice si pasó o la cortaron.
//
// Uso: node [--require motor/sin-red.cjs] sonda.cjs <modo> <puerto>
//   tcp              socket a 127.0.0.2:<puerto>: local de verdad, pero la guarda no lo tiene por local,
//                    así que hace de «destino remoto» sin necesitar internet
//   fetch            fetch a http://127.0.0.2:<puerto>/
//   local            socket a 127.0.0.1:<puerto>: el servidor de HyperFrames va por aquí y debe pasar
//   hijo             lanza `node sonda.cjs tcp <puerto>` SIN --require, heredando el entorno
//   hijo-sin-opciones  lo mismo, pero quitándole NODE_OPTIONS al hijo (control: sin herencia, conecta)
"use strict";

const net = require("node:net");
const { spawnSync } = require("node:child_process");

const [modo, puerto] = process.argv.slice(2);

function informa(texto) {
  process.stdout.write(texto + "\n");
}

function socket(host) {
  const s = net.connect({ host, port: Number(puerto) });
  s.on("connect", () => { informa("CONECTA"); s.destroy(); });
  s.on("error", (e) => informa(String(e.message).includes("[sin-red]") ? "CORTADA" : `ERROR ${e.code}`));
}

if (modo === "tcp") socket("127.0.0.2");
else if (modo === "local") socket("127.0.0.1");
else if (modo === "fetch") {
  fetch(`http://127.0.0.2:${puerto}/`)
    .then(() => informa("CONECTA"))
    .catch((e) => informa(String(e.message).includes("[sin-red]") ? "CORTADA" : `ERROR ${e.cause?.code ?? e.message}`));
} else if (modo === "hijo" || modo === "hijo-sin-opciones") {
  const entorno = { ...process.env };
  if (modo === "hijo-sin-opciones") delete entorno.NODE_OPTIONS;
  const r = spawnSync(process.execPath, [__filename, "tcp", puerto], { env: entorno, encoding: "utf8" });
  process.stdout.write(r.stdout);
} else {
  informa(`modo desconocido: ${modo}`);
  process.exitCode = 2;
}
