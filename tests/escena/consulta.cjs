// Pregunta a motor/motor.js por el estado de un GUION en unos instantes (F6.2b). Lo usa test_extremo_a_extremo.py
// para comparar lo que calcula el motor con lo que calcula Python (lib/escena/encuadre.py) y para ver qué palabra
// del karaoke brilla en cada instante.
//
// Uso: node consulta.cjs <guion.json> <consultas.json>
// Cada consulta es {tipo, t, …}: «mundo» e «actor» (id), «camara» (plano) o «karaoke» (todos los grupos).
// Imprime un JSON con una respuesta por consulta, en el mismo orden.
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const [rutaGuion, rutaConsultas] = process.argv.slice(2);
const Motor = require(path.resolve(__dirname, "..", "..", "motor", "motor.js"));
const G = JSON.parse(fs.readFileSync(rutaGuion, "utf8"));
const consultas = JSON.parse(fs.readFileSync(rutaConsultas, "utf8"));
const M = Motor.crea(G);

const respuestas = consultas.map((q) => {
  if (q.tipo === "mundo") return M.mundo(q.id, q.t);
  if (q.tipo === "actor") return M.actor(q.id, q.t);
  if (q.tipo === "camara") return M.camara(M.planos[q.plano], q.t);
  if (q.tipo === "karaoke") {
    return G.karaoke.map((g) => ({
      id: g.id,
      visible: q.t >= g.t && q.t <= g.t1 ? M.grupo(g, q.t).o : 0,
      brillo: g.w.map((_, n) => M.palabra(g, n, q.t)),
    }));
  }
  throw new Error(`consulta desconocida: ${q.tipo}`);
});
process.stdout.write(JSON.stringify(respuestas) + "\n");
