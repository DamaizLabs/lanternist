// Prueba de determinismo de motor/motor.js en Node (F6.2a): el mismo t tiene que dar el mismo estado, se
// pregunte en el orden que se pregunte. Lo usa tests/escena/test_motor_determinista.py.
//
// Uso: node determinismo.cjs <guion.json> [--mutante]
//
// Recorre todos los fotogramas del GUION (0, 1/fps, 2/fps… duracion) con tres motores nuevos: en orden,
// al revés y barajado (con una semilla fija), y además vuelve a preguntar el primer recorrido entero al mismo
// motor. En cada t guarda el estado completo: planos (entrada y cámara), actores, huesos de cada pieza de
// malla, elementos y karaoke. Imprime un JSON con cuántos fotogramas salen distintos entre recorridos.
//
// --mutante es el CONTROL NEGATIVO: hace que Math.sin arrastre una deriva minúscula que crece con cada
// llamada, o sea, un motor cuyo resultado depende de lo que se calculó antes. Con él, los recorridos TIENEN
// que salir distintos; si no, la comparación no sabría fallar.
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const [ruta, ...resto] = process.argv.slice(2);
const mutante = resto.includes("--mutante");
if (mutante) {
  const seno = Math.sin;
  let llamadas = 0;
  Math.sin = (x) => seno(x) + (llamadas++) * 1e-12;
}
const Motor = require(path.resolve(__dirname, "..", "..", "motor", "motor.js"));
const G = JSON.parse(fs.readFileSync(ruta, "utf8"));

const n = Math.round(G.duracion * G.fps);
const tiempos = Array.from({ length: n + 1 }, (_, i) => i / G.fps);

// Qué actores llevan cada pieza de malla: los que tienen su postura (como hace compone.py con los lienzos).
const piezas = Object.entries((G.rig || {}).piezas || {});

function estado(M, t) {
  const r = { planos: {}, huesos: {} };
  for (const p of G.planos) {
    if (t < p.t0 || t > p.t1) continue;
    r.planos[p.id] = {
      entrada: M.entradaPlano(p, t),
      camara: M.camara(p, t),
      actores: Object.fromEntries(p.actores.map((a) => [a.id, M.actor(a.id, t)])),
    };
    for (const a of p.actores) {
      for (const [nombre, pz] of piezas) if (a.posturas[pz.post]) r.huesos[`${a.id}/${nombre}`] = M.huesos(pz, a.id, t);
    }
  }
  r.elementos = G.elementos.map((e) => M.elemento(e, t));
  r.karaoke = G.karaoke.map((g) => ({ grupo: M.grupo(g, t), palabras: g.w.map((_, i) => M.palabra(g, i, t)) }));
  return JSON.stringify(r);
}

function recorre(orden, M = Motor.crea(G)) {
  const out = new Map();
  for (const t of orden) out.set(t, estado(M, t));
  return out;
}

// Barajado con un generador congruencial de semilla fija: la prueba no puede depender del azar.
function barajado(lista) {
  const a = [...lista];
  let s = 2709;
  for (let i = a.length - 1; i > 0; i--) {
    s = (s * 1103515245 + 12345) % 2147483648;
    const j = s % (i + 1);
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

const M1 = Motor.crea(G);
const enOrden = recorre(tiempos, M1);
const alReves = recorre([...tiempos].reverse());
const alAzar = recorre(barajado(tiempos));
const otraVez = recorre(tiempos, M1);

const distintos = (b) => tiempos.filter((t) => enOrden.get(t) !== b.get(t)).length;
process.stdout.write(JSON.stringify({
  mutante,
  fotogramas: tiempos.length,
  distintos_al_reves: distintos(alReves),
  distintos_barajado: distintos(alAzar),
  distintos_mismo_motor_otra_vez: distintos(otraVez),
  estados_diferentes_en_el_tiempo: new Set(enOrden.values()).size,
}) + "\n");
