// Vocina: la pagina. Carica G2P, modello e onnxruntime-web dalla stessa cartella e legge frase per frase.
import * as ort from "./ort/ort.wasm.bundle.min.js";  // .js e non .mjs: molti server danno ai .mjs il tipo text/plain, e il browser rifiuta il modulo
import { caricaVoce, wav } from "./tinyvoca_web.js";

const $ = (id) => document.getElementById(id);
const stato = (t) => { $("stato").textContent = t; };
const NOMI_VOCI = { I1: "Femminile", I2: "Maschile" };
const ESEMPI = {{ESEMPI}};
let voce, contesto, fermato = false;

for (const [nome, testo] of Object.entries(ESEMPI)) {
  const b = document.createElement("button");
  b.className = "secondario";
  b.textContent = nome;
  b.onclick = () => { $("testo").value = testo; };
  $("esempi").append(b);
}
$("velocita").oninput = () => { $("vel").textContent = Number($("velocita").value).toFixed(2).replace(".", ","); };

// Scarica con l'avanzamento nella barra (il browser poi lo tiene in cache).
async function scarica(url, quota, base) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  const totale = Number(r.headers.get("content-length")) || 0;
  if (!r.body || !totale) return new Uint8Array(await r.arrayBuffer());
  const lettore = r.body.getReader();
  const pezzi = [];
  let ricevuti = 0;
  for (;;) {
    const { done, value } = await lettore.read();
    if (done) break;
    pezzi.push(value);
    ricevuti += value.length;
    $("riempi").style.width = `${Math.round((base + quota * ricevuti / totale) * 100)}%`;
  }
  const dati = new Uint8Array(ricevuti);
  let o = 0;
  for (const p of pezzi) { dati.set(p, o); o += p.length; }
  return dati;
}

// Coda di riproduzione: un pezzo parte quando il precedente ha davvero finito (evento «ended»), non a un orario
// calcolato: in Firefox l'orologio dell'audio corre prima che l'uscita sia pronta. La pausa è silenzio nel buffer.
let coda = [], inCorso = null;

function suona(campioni, frequenza, pausa = 0) {
  const buffer = contesto.createBuffer(1, campioni.length + Math.round(pausa * frequenza), frequenza);
  buffer.copyToChannel(campioni, 0);
  coda.push(buffer);
  if (!inCorso) prossimoPezzo();
}

function prossimoPezzo() {
  const buffer = coda.shift();
  if (!buffer) { inCorso = null; return; }
  const s = contesto.createBufferSource();
  s.buffer = buffer;
  s.connect(contesto.destination);
  s.onended = () => { if (inCorso === s) prossimoPezzo(); };
  inCorso = s;
  s.start();
}

function ferma() {
  fermato = true;
  coda = [];
  const s = inCorso;
  inCorso = null;
  if (s) { try { s.stop(); } catch (e) { /* già finito */ } }
  $("ferma").disabled = true;
}
$("ferma").onclick = ferma;
setInterval(() => { if (!inCorso && !coda.length && !$("leggi").disabled) $("ferma").disabled = true; }, 300);

$("leggi").onclick = async () => {
  $("leggi").disabled = true;
  ferma();
  contesto ??= new AudioContext();
  await contesto.resume();
  fermato = false;
  $("ferma").disabled = false;
  $("scarica").hidden = true;
  $("frasi").innerHTML = "";
  let calcolo = 0, secondi = 0;
  try {
    const audio = await voce.leggi($("testo").value, {
      voce: Number($("voce").value || 0),
      velocita: Number($("velocita").value),
      suFrase: ({ indice, totale, testo, fonemi, audio, ms, pausa }) => {
        if (fermato) return;
        calcolo += ms;
        secondi += audio.length / voce.frequenza;
        suona(audio, voce.frequenza, pausa);
        const li = document.createElement("li");
        li.innerHTML = `<div></div><div class="fonemi"></div>`;
        li.children[0].textContent = testo;
        li.children[1].textContent = fonemi;
        $("frasi").append(li);
        stato(`Frase ${indice + 1} di ${totale}…`);
      },
    });
    if (!fermato && audio.length) {
      $("scarica").href = URL.createObjectURL(wav(audio, voce.frequenza));
      $("scarica").hidden = false;
      stato(`${secondi.toFixed(1)} s di voce in ${(calcolo / 1000).toFixed(2)} s di calcolo: ${Math.max(1, Math.round(secondi * 1000 / calcolo))} volte più veloce del tempo reale.`);
    }
    window.esito = { secondi, calcolo, frasi: $("frasi").children.length };
  } catch (e) {
    stato("Errore: " + e.message);
    window.esito = { errore: String(e && e.stack || e) };
  } finally {
    $("leggi").disabled = false;
  }
};

try {
  const t0 = performance.now();
  $("barra").hidden = false;
  stato("Scarico il modello (solo la prima volta)…");
  const [dati, metadati] = await Promise.all([fetch("dati.json").then((r) => r.json()), fetch("model.json").then((r) => r.json())]);
  const modello = await scarica("model.onnx?v={{VERSIONE}}", 0.8, 0);
  // Il wasm arriva compresso (il server non comprime): si scompatta qui. Se il browser l'ha già scompattato
  // (server che aggiunge Content-Encoding sui .gz) manca la firma gzip, e si usa così com'è.
  let wasm = await scarica("ort/ort-wasm-simd-threaded.wasm.gz?v={{VERSIONE_ORT}}", 0.2, 0.8);
  if (wasm[0] === 0x1f && wasm[1] === 0x8b) {
    wasm = new Uint8Array(await new Response(new Blob([wasm]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer());
  }
  stato("Avvio…");
  voce = await caricaVoce({ ort, dati, modello, metadati, wasm });
  $("barra").hidden = true;
  if (voce.voci.length > 1) {
    voce.voci.forEach((v, i) => $("voce").append(new Option(NOMI_VOCI[v] ?? v, i)));
    $("scelta-voce").hidden = false;
  }
  stato(`Pronta in ${((performance.now() - t0) / 1000).toFixed(1)} s. Scrivi un testo e premi «Leggi».`);
  $("leggi").textContent = "Leggi";
  $("leggi").disabled = false;
  window.pronto = true;
} catch (e) {
  stato("Errore all'avvio: " + e.message + " (serve un browser recente)");
  window.esito = { errore: String(e && e.stack || e) };
}
