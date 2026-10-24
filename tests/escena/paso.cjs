// Prueba de que el paso de integración del motor sale de G.fps (F6.2a). Lo usa test_motor_determinista.py.
//
// Uso: node paso.cjs <guion.json> <fps> [--salto-fijo]
//
// Pone al actor raíz del primer plano (a1) a avanzar en línea recta a 1500 px/s entre t=0,3 y t=0,8 y
// devuelve cuánto ha girado su rueda (a2) al acabar. La rueda gira según lo rodado, que el motor integra a
// pasos de 1/fps y en el que descarta los avances «de golpe» por encima de un umbral.
//
// --salto-fijo es el CONTROL NEGATIVO: carga el motor con el umbral de video_1 escrito a mano (100 px por
// paso, calibrado a 24 fps) en vez de derivarlo de los fps. A 12 fps cada paso avanza 125 px, así que ese
// motor toma la carrera por saltos y la rueda casi no gira.
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const [ruta, fps, ...resto] = process.argv.slice(2);
let codigo = fs.readFileSync(path.resolve(__dirname, "..", "..", "motor", "motor.js"), "utf8");
if (resto.includes("--salto-fijo")) {
  const original = "const SALTO = 2400 * PASO;";
  if (!codigo.includes(original)) throw new Error("motor.js ya no calcula SALTO como se esperaba: revisa la prueba");
  codigo = codigo.replace(original, "const SALTO = 100;");
}
const modulo = { exports: {} };
new Function("module", "exports", codigo)(modulo, modulo.exports);
const Motor = modulo.exports;

const G = JSON.parse(fs.readFileSync(ruta, "utf8"));
G.fps = Number(fps);
const a1 = G.planos[0].actores.find((a) => a.id === "a1");
a1.pista[1] = { ...a1.pista[1], x: a1.pista[0].x + 750, tr: 0.5, e: "lineal" };
const M = Motor.crea(G);
process.stdout.write(JSON.stringify({ fps: G.fps, giro: M.actor("a2", 0.85).giro }) + "\n");
