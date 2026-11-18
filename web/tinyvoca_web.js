// Runtime di tiny-voca italiano per il browser: G2P nostro (g2p_it.js) + modello ONNX con onnxruntime-web.
// Legge frase per frase e suona ogni frase appena è pronta. Tutto nel thread principale: il modello è
// piccolo, e fra una frase e l'altra si lascia respirare la pagina.
//
//   const voce = await caricaVoce({ ort, dati, modello, metadati });  // modello: Uint8Array dell'ONNX
//   await voce.leggi(testo, { velocita, suFrase })

import { creaG2P } from "./g2p_it.js";

const PICCO = 0.99;

function limitaPicco(campioni) {
  let max = 0;
  for (let i = 0; i < campioni.length; i++) max = Math.max(max, Math.abs(campioni[i]));
  if (max > PICCO) for (let i = 0; i < campioni.length; i++) campioni[i] *= PICCO / max;
}

export async function caricaVoce({ ort, dati, modello, metadati, wasm }) {
  const g2p = creaG2P(dati);
  // Il modello può avere meno simboli riservati in coda (il pilota non ne ha): conta che i suoi coincidano
  // e che ci siano tutti quelli che il G2P produce.
  const base = g2p.SYMBOLS.findIndex((s) => s.startsWith("<riservato"));
  const n = metadati.symbols.length;
  if (n < base || JSON.stringify(g2p.SYMBOLS.slice(0, n)) !== JSON.stringify(metadati.symbols)) {
    throw new Error("L'inventario dei fonemi del G2P non è quello del modello");
  }
  ort.env.wasm.numThreads = 1;
  ort.env.wasm.proxy = false;
  if (wasm) ort.env.wasm.wasmBinary = wasm;
  const sessione = await ort.InferenceSession.create(modello, { executionProviders: ["wasm"] });
  const limite = metadati.max_tokens - 12;

  // Il modello è addestrato su clip di pochi secondi (al massimo 9 s): una frase lunga si legge a pezzi di
  // circa 12 s al massimo, unendo i tratti fra le virgole finché ci stanno; un tratto troppo lungo da solo si
  // divide a metà delle parole. Ogni pezzo porta la pausa da lasciare dopo.
  const PEZZO = Math.min(limite, 200);
  // In fondo a un'emissione il modello non fa pausa sull'ultimo segno: la si aggiunge qui, lunga quanto quella
  // che fa dentro la frase (misurata sul pilota: virgola e parentesi ~0,35 s, due punti ~0,25 s).
  const PAUSA_FRASE = 0.3;
  const pausaDopo = (pezzo) => {
    const fine = pezzo.trim().slice(-2);
    if (/[,;)—]/.test(fine)) return 0.35;
    if (/:/.test(fine)) return 0.28;
    return 0.06;  // spezzata a metà delle parole
  };

  function tratti(frase) {
    const f = g2p.fonemi(frase);
    if (f.symbols.length <= 2) return [];
    if (f.ids.length <= PEZZO) return [frase];
    const parole = frase.split(" ");
    if (parole.length < 2) return [frase];
    const meta = Math.ceil(parole.length / 2);
    return [...tratti(parole.slice(0, meta).join(" ")), ...tratti(parole.slice(meta).join(" "))];
  }

  function adatta(frase) {
    const intera = g2p.fonemi(frase);
    if (intera.symbols.length <= 2) return [];
    if (intera.ids.length <= PEZZO) return [{ f: intera, pausa: PAUSA_FRASE }];
    const pezzi = [];
    let corrente = "";
    for (const t of frase.split(/(?<=[,;:—])\s+/).flatMap(tratti)) {
      const unito = corrente ? corrente + " " + t : t;
      if (corrente && g2p.fonemi(unito).ids.length > PEZZO) { pezzi.push(corrente); corrente = t; }
      else corrente = unito;
    }
    if (corrente) pezzi.push(corrente);
    return pezzi.map((p, i) => ({ f: g2p.fonemi(p), pausa: i + 1 < pezzi.length ? pausaDopo(p) : PAUSA_FRASE }));
  }

  async function sintetizza(f, voce, velocita) {
    const n = f.ids.length;
    const interi = (v) => new ort.Tensor("int64", BigInt64Array.from(v.map(BigInt)), [1, n]);
    const scalare = (v) => new ort.Tensor("float32", Float32Array.from([v]), [1]);
    const out = await sessione.run({
      tokens: interi(f.ids), stress: interi(f.stress),
      voice: new ort.Tensor("int64", BigInt64Array.from([BigInt(voce)]), [1]),
      speed: scalare(velocita), pitch_shift: scalare(0), pitch_range: scalare(1),
    });
    return out.audio.data;
  }

  // suFrase({indice, totale, testo, fonemi, audio, ms}) per ogni frase pronta; ritorna l'audio intero.
  async function leggi(testo, { voce = 0, velocita = 1, suFrase = () => {} } = {}) {
    const frasi = g2p.frasi(testo);
    const pezzi = [];
    for (let i = 0; i < frasi.length; i++) {
      for (const { f, pausa } of adatta(frasi[i])) {
        const t0 = performance.now();
        const audio = await sintetizza(f, voce, velocita);
        const ms = performance.now() - t0;
        const copia = audio.slice();
        limitaPicco(copia);
        pezzi.push(audio, new Float32Array(Math.round(pausa * metadati.sample_rate)));
        suFrase({ indice: i, totale: frasi.length, testo: frasi[i], fonemi: leggibile(f), audio: copia, ms, pausa });
        await new Promise((r) => setTimeout(r, 0));
      }
    }
    const lunghezza = pezzi.reduce((s, p) => s + p.length, 0);
    const tutto = new Float32Array(lunghezza);
    let o = 0;
    for (const p of pezzi) { tutto.set(p, o); o += p.length; }
    limitaPicco(tutto);
    return tutto;
  }

  return { leggi, g2p, frequenza: metadati.sample_rate, voci: metadati.voices };
}

export function leggibile(f) {
  return f.symbols.slice(1, -1).map((s, i) => (f.stress[i + 1] ? "ˈ" : "") + (s === "<sp>" ? " " : s)).join("")
    .replace(/ +/g, " ");
}

// WAV a 16 bit di un Float32Array.
export function wav(campioni, frequenza) {
  const b = new ArrayBuffer(44 + campioni.length * 2);
  const v = new DataView(b);
  const s = (o, t) => [...t].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  s(0, "RIFF"); v.setUint32(4, 36 + campioni.length * 2, true); s(8, "WAVE"); s(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, frequenza, true);
  v.setUint32(28, frequenza * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); s(36, "data");
  v.setUint32(40, campioni.length * 2, true);
  for (let i = 0; i < campioni.length; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, campioni[i])) * 32767, true);
  return new Blob([b], { type: "audio/wav" });
}
