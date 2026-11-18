// Prova la pagina in Firefox senza schermo (WebDriver BiDi): avvia, legge un testo, riporta la coda dell'audio.
//   node prova_firefox.mjs PAGINA.html "testo"
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { resolve } from "node:path";

const pagina = /^https?:/.test(process.argv[2]) ? process.argv[2] : "file://" + resolve(process.argv[2]);
const testo = process.argv[3];
const porta = 9900 + Math.floor(Math.random() * 90);
const profilo = mkdtempSync("/tmp/claude-1000/firefox-prova-");
const ff = spawn("firefox", ["--headless", "--remote-debugging-port", String(porta), "--profile", profilo, "--no-remote"], { stdio: "ignore" });
const attendi = (ms) => new Promise((r) => setTimeout(r, ms));
let ws;
try {
  for (let i = 0; i < 60 && !ws; i++) {
    await attendi(500);
    try {
      const w = new WebSocket(`ws://127.0.0.1:${porta}/session`);
      await new Promise((ok, no) => { w.onopen = ok; w.onerror = no; });
      ws = w;
    } catch (e) { /* non ancora pronto */ }
  }
  let id = 0;
  const attese = new Map();
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && attese.has(m.id)) { attese.get(m.id)(m); attese.delete(m.id); }
    if (m.method === "log.entryAdded") console.log("log:", m.params.text);
  };
  const bidi = (method, params = {}) => new Promise((r) => { const i = ++id; attese.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  await bidi("session.new", { capabilities: { alwaysMatch: { "moz:firefoxOptions": { prefs: { "media.autoplay.default": 0, "media.autoplay.blocking_policy": 0 } } } } });
  await bidi("session.subscribe", { events: ["log.entryAdded"] });
  const albero = await bidi("browsingContext.getTree", {});
  const contesto = albero.result.contexts[0].context;
  await bidi("browsingContext.navigate", { context: contesto, url: pagina, wait: "complete" });
  const valuta = async (espr) => {
    const r = await bidi("script.evaluate", { expression: espr, target: { context: contesto }, awaitPromise: true, serializationOptions: { maxObjectDepth: 4 } });
    if (r.result?.type === "exception") return "ECCEZIONE " + JSON.stringify(r.result.exceptionDetails?.text);
    return r.result?.result;
  };
  const valore = (v) => (v?.type === "string" || v?.type === "number" || v?.type === "boolean" ? v.value : v);
  let pronto = false;
  for (let i = 0; i < 300 && !pronto; i++) { await attendi(300); pronto = valore(await valuta("window.pronto === true || !!window.esito")); }
  console.log("stato:", valore(await valuta("document.getElementById('stato').textContent")));
  if (testo) await valuta(`document.getElementById('testo').value = ${JSON.stringify(testo)}`);
  const r = JSON.parse(valore(await valuta("JSON.stringify(document.getElementById('leggi').getBoundingClientRect())")));
  await bidi("input.performActions", { context: contesto, actions: [{ type: "pointer", id: "mouse", actions: [
    { type: "pointerMove", x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) },
    { type: "pointerDown", button: 0 }, { type: "pointerUp", button: 0 }] }] });
  let fatto = false;
  for (let i = 0; i < 300 && !fatto; i++) { await attendi(300); fatto = valore(await valuta("!!window.esito")); }
  await attendi(25000);
  console.log("stato:", valore(await valuta("document.getElementById('stato').textContent")));
  console.log("programma:", valore(await valuta("JSON.stringify((window.programma||[]).map(p => [p.inizio.toFixed(3), p.durata.toFixed(3), p.ora.toFixed(3)]))")));
  console.log("menu voce:", valore(await valuta("getComputedStyle(document.getElementById('scelta-voce') || document.body).display")));
} finally {
  ws?.close();
  ff.kill();
}
