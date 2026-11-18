// Confronta la versione JS del G2P con le uscite della Python (vettori.json).   node prova_vettori.mjs
import { readFileSync } from "node:fs";
import { creaG2P, VERSIONE } from "./g2p_it.js";

const qui = new URL(".", import.meta.url);
const dati = JSON.parse(readFileSync(new URL("dati.json", qui), "utf8"));
const { versione, vettori } = JSON.parse(readFileSync(new URL("vettori.json", qui), "utf8"));
const g2p = creaG2P(dati);
let errori = 0;
if (versione !== VERSIONE) { console.log(`versione diversa: Python ${versione}, JS ${VERSIONE}`); errori++; }
const uguale = (a, b) => JSON.stringify(a) === JSON.stringify(b);
for (const v of vettori) {
  const norm = g2p.normalizza(v.testo);
  const fr = g2p.frasi(v.testo);
  const f = g2p.fonemi(v.testo);
  const diversi = [];
  if (norm !== v.normalizzato) diversi.push(`normalizzato\n  py: ${v.normalizzato}\n  js: ${norm}`);
  if (!uguale(fr, v.frasi)) diversi.push(`frasi\n  py: ${JSON.stringify(v.frasi)}\n  js: ${JSON.stringify(fr)}`);
  if (!uguale(f.symbols, v.symbols)) diversi.push(`simboli\n  py: ${v.symbols.join(" ")}\n  js: ${f.symbols.join(" ")}`);
  else if (!uguale(f.stress, v.stress)) diversi.push(`accento\n  py: ${v.stress.join("")}\n  js: ${f.stress.join("")}`);
  else if (!uguale(f.ids, v.ids)) diversi.push("id");
  if (diversi.length) {
    errori++;
    if (errori <= 10) console.log(`✗ ${v.testo}\n${diversi.join("\n")}\n`);
  }
}
console.log(`${vettori.length - errori} su ${vettori.length} uguali`);
process.exit(errori ? 1 : 0);
