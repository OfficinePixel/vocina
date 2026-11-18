// G2P italiano di bancollm per tiny-voca, versione per il browser: gemella di g2p_it.py.
// Le due versioni leggono gli stessi dati (dati.json) e devono dare gli stessi token: prova_vettori.mjs
// confronta questa con le uscite della Python (vettori.json). Una modifica alla logica va fatta in tutte e due.
//
//   const g2p = creaG2P(dati);   // dati = il contenuto di dati.json
//   g2p.frasi(testo)             // le frasi normalizzate
//   g2p.fonemi(frase)            // {symbols, ids, stress}

export const VERSIONE = 1;

export function creaG2P(DATI) {
  const PAD = "<pad>", BOS = "<bos>", EOS = "<eos>", SP = "<sp>", UNK = "<unk>";
  const PUNTEGGIATURA = [",", ".", "?", "!", ";", ":", '"', "'", "(", ")", "—", "…"];
  const CONSONANTI = ["p", "b", "t", "d", "k", "ɡ", "f", "v", "s", "z", "ʃ", "m", "n", "ɲ", "ŋ",
    "l", "ʎ", "r", "ɾ", "j", "w", "ts", "dz", "tʃ", "dʒ"];
  const VOCALI = ["a", "e", "ɛ", "i", "o", "ɔ", "u"];
  // Riservati in coda, mai prodotti dal G2P: vedi g2p_it.py.
  const RISERVATI = Array.from({ length: 8 }, (_, i) => `<riservato${i + 1}>`);
  const SYMBOLS = [PAD, BOS, EOS, SP, UNK, ...PUNTEGGIATURA, ...CONSONANTI, ...VOCALI, ...RISERVATI];
  const ID = Object.fromEntries(SYMBOLS.map((s, i) => [s, i]));
  const FONI = new Set([...CONSONANTI, ...VOCALI]);

  const LETTERE = "A-Za-zÀ-ÖØ-öø-ÿ";
  const ATONE = new Set(DATI.atone);
  const LESSICO = DATI.lessico;
  // Lessico dal Wikizionario (CC BY-SA 4.0, lessico_wikizionario.json, campo «voci»): chi usa il G2P lo mette
  // in DATI.wikizionario. Se manca, solo regole.
  const WIKIZIONARIO = DATI.wikizionario ?? {};
  const OMOGRAFI = DATI.omografi;
  const perLunghezza = (a, b) => b[0].length - a[0].length;
  const SUFFISSI = [...DATI.suffissi_accento].sort(perLunghezza);
  const SUFFISSI_REGEX = DATI.suffissi_regex.map(([r, k]) => [new RegExp(r), k]);
  const SUFFISSI_TONICI = [...DATI.suffissi_tonici].sort(perLunghezza);
  const SUFFISSI_VOCALE = [...DATI.suffissi_vocale].sort(perLunghezza);
  const GL_DURO = DATI.gl_duro;
  const ZZ_SONORA = DATI.zz_sonora.map((r) => new RegExp(r));
  const LETTERE_STRANIERE = DATI.lettere_straniere;
  const NOMI_LETTERE = DATI.lettere_nomi;
  const MESI = DATI.mesi;

  const ACCENTATE = { "à": ["a", null], "è": ["e", "ɛ"], "é": ["e", "e"], "ì": ["i", null], "í": ["i", null],
    "ò": ["o", "ɔ"], "ó": ["o", "o"], "ù": ["u", null], "ú": ["u", null] };
  const FORZATE = { "ż": ["z", "dz"], "ź": ["z", "ts"], "ṡ": ["s", "z"], "ś": ["s", "s"] };
  const VOCALI_LETTERE = new Set("aeiouy");
  const SONORE = new Set("bdglmnrv");
  const LUNGHE = new Set(["ɲ", "ʎ", "ʃ", "ts", "dz"]);
  const VOCALI_FONI = new Set(VOCALI);

  // re.sub di Python: la funzione riceve [intero, gruppo1, …] con null per i gruppi assenti.
  const sub = (pattern, fn, t) => t.replace(new RegExp(pattern, "g"), (...a) => {
    const fine = a.findIndex((x) => typeof x === "number");
    return fn(a.slice(0, fine).map((x) => (x === undefined ? null : x)));
  });

  // ---------------------------------------------------------------- numeri in lettere

  const UNITA = ["zero", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove", "dieci", "undici",
    "dodici", "tredici", "quattordici", "quindici", "sedici", "diciassette", "diciotto", "diciannove"];
  const DECINE = ["", "", "venti", "trenta", "quaranta", "cinquanta", "sessanta", "settanta", "ottanta", "novanta"];

  function sottoCento(n) {
    if (n < 20) return UNITA[n];
    const d = Math.floor(n / 10), u = n % 10;
    let t = DECINE[d];
    if (u === 1 || u === 8) t = t.slice(0, -1);
    return t + (u ? UNITA[u] : "");
  }

  function sottoMille(n) {
    const c = Math.floor(n / 100), r = n % 100;
    let testa = c === 0 ? "" : (c === 1 ? "cento" : UNITA[c] + "cento");
    const coda = r ? sottoCento(r) : "";
    if (testa && coda.startsWith("ottant")) testa = testa.slice(0, -1);
    return testa + coda;
  }

  function sottoMilione(n) {
    const m = Math.floor(n / 1000), r = n % 1000;
    const testa = m === 0 ? "" : (m === 1 ? "mille" : sottoMille(m) + "mila");
    let s = testa + (r ? sottoMille(r) : "");
    if (n % 10 === 3 && n % 100 !== 13 && n > 10) s = s.slice(0, -1) + "é";
    return s;
  }

  function lettere(n) {
    if (n === 0) return "zero";
    const parti = [];
    for (const [valore, uno, molti] of [[1e9, "un miliardo", "miliardi"], [1e6, "un milione", "milioni"]]) {
      const q = Math.floor(n / valore);
      n = n % valore;
      if (q) {
        let testa = sottoMilione(q);
        if (q > 1 && testa.endsWith("uno")) testa = testa.slice(0, -1).replace("centoun", "centun");
        parti.push(q === 1 ? uno : testa + " " + molti);
      }
    }
    if (n) parti.push(sottoMilione(n));
    return parti.join(" ");
  }

  const cifre = (s) => [...s].map((c) => UNITA[Number(c)]).join(" ");

  function intero(s) {
    s = s.replaceAll(".", "");
    if ((s.length > 1 && s[0] === "0") || s.length > 12) return cifre(s);
    return lettere(Number(s));
  }

  function numero(i, fraz) {
    if (!fraz) return intero(i);
    const dopo = fraz[0] === "0" || fraz.length > 3 ? cifre(fraz) : lettere(Number(fraz));
    return intero(i) + " virgola " + dopo;
  }

  function euro(i, cent) {
    const n = Number(i.replaceAll(".", "")), c = Number(cent || "0");
    let s = (n === 1 ? "un" : lettere(n)) + (n && n % 1000000 === 0 ? " di euro" : " euro");
    if (c) s += " e " + (c === 1 ? "un centesimo" : lettere(c) + " centesimi");
    return s;
  }

  function ora(h, m) {
    const s = Number(h) === 1 ? "l'una" : lettere(Number(h));
    if (m === "00") return s;
    return s + ({ "15": " e un quarto", "30": " e mezza" }[m] ?? " e " + lettere(Number(m)));
  }

  function ordinale(n, femminile) {
    const base = ["", "primo", "secondo", "terzo", "quarto", "quinto", "sesto", "settimo", "ottavo", "nono", "decimo"];
    let s;
    if (n <= 10) s = base[n];
    else {
      s = lettere(n).replaceAll(" ", "");
      if (s.endsWith("tré")) s = s.slice(0, -1) + "e";
      else if (!s.endsWith("sei")) s = s.slice(0, -1);
      s += "esimo";
    }
    return femminile ? s.slice(0, -1) + "a" : s;
  }

  // ---------------------------------------------------------------- normalizzazione

  const NUM = "[0-9]{1,3}(?:\\.[0-9]{3})+|[0-9]+";
  const ELISO = { il: "l'", Il: "L'", del: "dell'", Del: "Dell'", dal: "dall'", Dal: "Dall'", al: "all'",
    Al: "All'", nel: "nell'", Nel: "Nell'", sul: "sull'", Sul: "Sull'" };
  const QUOTES = { "‘": "'", "’": "'", "‚": "'", "‛": "'", "`": "'", "´": "'", "“": '"', "”": '"', "„": '"',
    "‟": '"', "«": '"', "»": '"', "–": "—", "―": "—", "[": "(", "{": "(", "]": ")", "}": ")" };

  const escape = (s) => s.replace(/([.*+?^${}()|\[\]\\/])/g, "\\$1");
  const conArticolo = (art, s) => (!art ? s : ("aeiou".includes(s[0]) ? ELISO[art] + s : art + " " + s));

  function pronunciabile(sigla) {
    const s = sigla.toLowerCase();
    return /[aeiou]/.test(s) && !/[^aeiou]{3}/.test(s) && !/[^aeiou]{2}$/.test(s);
  }

  const compita = (l) => [...l.toLowerCase()].filter((c) => c in NOMI_LETTERE).map((c) => NOMI_LETTERE[c]).join(" ");

  function normalizza(testo) {
    let t = sub("(?<![0-9])([0-9]{1,4})(°|º|ª)(?!C)", (m) => ordinale(Number(m[1]), m[2] === "ª"), testo);
    t = [...t.normalize("NFKC")].map((c) => QUOTES[c] ?? c).join("");
    t = t.replace(/\.{3,}/g, "…");
    t = t.replace(/-{2,}|\s-\s/g, " — ");
    for (const [abbr, intera] of DATI.abbreviazioni) {
      for (const [forma, piena] of [[abbr, intera], [abbr[0].toUpperCase() + abbr.slice(1), intera[0].toUpperCase() + intera.slice(1)]]) {
        t = t.replace(new RegExp("(?<![" + LETTERE + "])" + escape(forma), "g"), piena);
      }
    }
    // valute
    t = sub("€\\s?(" + NUM + ")(?:,([0-9]{2}))?", (m) => m[1] + (m[2] ? "," + m[2] : "") + " euro", t);
    t = t.replace(/(?<=[0-9])\s?€/g, " euro");
    t = t.replaceAll("€", " euro ");
    t = t.replace(new RegExp("\\$\\s?(" + NUM + ")", "g"), "$1 dollari");
    // date
    const data = (m) => {
      const g = Number(m[1]), me = Number(m[2]), a = m[3];
      if (!(g >= 1 && g <= 31 && me >= 1 && me <= 12)) return m[0];
      return (g === 1 ? "primo" : lettere(g)) + " " + MESI[me - 1] + (a ? " " + lettere(Number(a)) : "");
    };
    t = sub("(?<![0-9])([0-9]{1,2})[/.]([0-9]{1,2})(?:[/.]([0-9]{4}|[0-9]{2}))?(?![0-9])",
      (m) => (m[3] || m[0].includes("/") ? data(m) : m[0]), t);
    t = t.replace(new RegExp("(?<![0-9])1 (" + MESI.join("|") + ")", "g"), "primo $1");
    // ore
    t = sub("(?<![0-9])([01]?[0-9]|2[0-4]):([0-5][0-9])(?![0-9])", (m) => ora(m[1], m[2]), t);
    t = sub("(?<![0-9.,])([01]?[0-9]|2[0-4])\\.([0-5][0-9])(?![0-9]|[.,][0-9])", (m) => ora(m[1], m[2]), t);
    // unità di misura dopo un numero
    for (const [sigla, una, molte] of DATI.unita) {
      t = sub("(?:(?<![" + LETTERE + "])(il|Il|del|dal|Dal|al|nel|sul) )?(?:(?<![0-9" + LETTERE + "])(-|−))?(" + NUM + ")(?:,([0-9]+))?\\s?"
        + escape(sigla) + "(?![" + LETTERE + "0-9²³])", (m) => {
        const art = m[1], meno = m[2], i = m[3], fraz = m[4] || "";
        const singolare = !fraz && i === "1" && !meno;
        if (singolare) return conArticolo(art, ("aeiou".includes(una[0]) ? "un'" : "un ") + una);
        return conArticolo(art, (meno ? "meno " : "") + numero(i, fraz) + " " + molte);
      }, t);
    }
    // importi, percentuali, numeri
    t = t.replace(/(?<=[0-9])x(?=[0-9])/g, " per ");
    t = sub("(?<![" + LETTERE + "])([A-Z])(?=[0-9])", (m) => NOMI_LETTERE[m[1].toLowerCase()] + " ", t);
    t = t.replace(new RegExp("([" + LETTERE + "])(?=[0-9])", "g"), "$1 ");
    t = t.replace(new RegExp("(?<=[0-9])(?=[" + LETTERE + "])", "g"), " ");
    t = sub("(?:(?<![" + LETTERE + "])(il|Il|del|Del|dal|Dal|al|Al|nel|Nel|sul|Sul) )?"
      + "(?:(" + NUM + "),([0-9]{2}) euro"
      + "|(?:(?<![0-9" + LETTERE + "])(-|−))?(" + NUM + ")(?:,([0-9]+))?(\\s?%)?)", (m) => {
      let s;
      if (m[2]) s = euro(m[2], m[3]);
      else {
        s = (m[4] ? "meno " : "") + numero(m[5], m[6] || "");
        if (m[7]) s += " per cento";
      }
      return conArticolo(m[1], s);
    }, t);
    for (const [simbolo, parola] of DATI.simboli) t = t.replaceAll(simbolo, parola);
    t = t.replaceAll("%", " per cento ");
    // sigle
    const maiuscole = t.match(new RegExp("(?<![" + LETTERE + "])[A-ZÀ-ÖØ-Þ]{4,}(?![" + LETTERE + "])", "g")) || [];
    const tuttoMaiuscolo = maiuscole.length >= 2;
    t = sub("(?<![" + LETTERE + "])[A-ZÀ-ÖØ-Þ]{2,}(?![" + LETTERE + "])", (m) => {
      const s = m[0];
      if (s in DATI.sigle) return DATI.sigle[s];
      if (tuttoMaiuscolo || (s.length >= 4 && pronunciabile(s))) return s.toLowerCase();
      return compita(s);
    }, t);
    t = sub("(?<![" + LETTERE + "'])([B-DF-HJ-NP-TV-Z])(?![" + LETTERE + "'.])", (m) => NOMI_LETTERE[m[1].toLowerCase()], t);
    t = sub("(?<![" + LETTERE + "])([A-Z])\\.(?= [A-Z])", (m) => NOMI_LETTERE[m[1].toLowerCase()], t);
    t = t.replace(new RegExp("(?<=[" + LETTERE + "])-(?=[" + LETTERE + "])", "g"), " ");
    return t.replace(/\s+/g, " ").trim();
  }

  // ---------------------------------------------------------------- frasi

  function frasi(testo) {
    const t = normalizza(testo);
    const uscita = [];
    for (let p of t.split(/(?<=[.!?…])\s+/)) {
      p = p.trim();
      if (!p || !new RegExp("[" + LETTERE + "]").test(p)) continue;
      if (!/[.!?…,;:]["')]*$/.test(p)) p += ".";
      uscita.push(p);
    }
    return uscita;
  }

  // ---------------------------------------------------------------- parole in fonemi

  function lettereDi(parola) {
    const base = [], acc = [], qual = [], forza = [];
    for (const c of parola) {
      if (c in ACCENTATE) { base.push(ACCENTATE[c][0]); acc.push(true); qual.push(ACCENTATE[c][1]); forza.push(null); }
      else if (c in FORZATE) { base.push(FORZATE[c][0]); acc.push(false); qual.push(null); forza.push(FORZATE[c][1]); }
      else { base.push(c); acc.push(false); qual.push(null); forza.push(null); }
    }
    return [base, acc, qual, forza];
  }

  const vocale = (c) => VOCALI_LETTERE.has(c);

  function fonemiParola(parola, precedente = "") {
    let w = [...parola.toLowerCase()].map((c) => LETTERE_STRANIERE[c] ?? c).join("");
    w = w.replace(/[^a-zàèéìíòóùú]/g, "");
    if (!w) return [];
    if (!/[aeiouyàèéìíòóùú]/.test(w)) {
      const uscita = [];
      for (const c of w) for (const nome of NOMI_LETTERE[c].split(" ")) uscita.push(...fonemiParola(nome));
      return uscita;
    }
    const piana = w.normalize("NFD").replace(/[̀-ͯ]/g, "");
    // Senza accenti si cerca solo se il testo non ne ha: «pensò» non è «penso».
    let r = LESSICO[w] || WIKIZIONARIO[w] || w;  // prima il lessico a mano, poi il Wikizionario
    for (const [regola, grafia] of OMOGRAFI[piana] ?? []) {
      if (new RegExp(regola).test(precedente)) { r = grafia; break; }
    }
    const [base, acc, qual, forza] = lettereDi(r);
    const n = base.length;
    const atona = ATONE.has(w) && !acc.some(Boolean);
    const glDuro = GL_DURO.some((g) => piana.includes(g));
    if (!acc.some(Boolean) && !atona && base.filter(vocale).length >= 4) {
      for (const [s, daFine] of SUFFISSI_TONICI) {
        if (piana.endsWith(s) && n === piana.length) { acc[n - daFine] = true; break; }
      }
    }
    const muta = new Array(n).fill(false);
    const semivU = new Array(n).fill(false);
    for (let i = 0; i < n; i++) {
      const c = base[i];
      if (c === "h") muta[i] = true;
      if (c === "i" && !acc[i] && i > 0 && i < n - 1 && vocale(base[i + 1]) && base[i + 1] !== "i") {
        const p = base[i - 1];
        if (p === "c" || p === "g" || (p === "l" && i >= 2 && base[i - 2] === "g" && !glDuro)) muta[i] = true;
      }
      if (c === "u" && !acc[i] && i > 0 && (base[i - 1] === "q" || base[i - 1] === "g") && i < n - 1 && vocale(base[i + 1])) semivU[i] = true;
    }
    const ruolo = new Array(n).fill(null);
    let i = 0;
    while (i < n) {
      if (!vocale(base[i]) || muta[i] || semivU[i]) { i++; continue; }
      let j = i;
      while (j < n && vocale(base[j]) && !muta[j] && !semivU[j]) j++;
      const seq = [];
      for (let k = i; k < j; k++) seq.push(k);
      const forte = seq.map((k) => acc[k] || "aeo".includes(base[k]));
      if (forte.some(Boolean)) {
        seq.forEach((k, a) => {
          if (forte[a]) ruolo[k] = "nucleo";
          else if (a + 1 < seq.length && forte[a + 1]) ruolo[k] = "attacco";
          else if (a > 0 && forte[a - 1]) ruolo[k] = "coda";
          else ruolo[k] = "nucleo";
        });
      } else if (seq.length === 2 && base[seq[0]] === "i" && base[seq[1]] === "u") {
        ruolo[seq[0]] = "attacco"; ruolo[seq[1]] = "nucleo";
      } else if (seq.length === 2 && base[seq[0]] === "u" && base[seq[1]] === "i") {
        ruolo[seq[0]] = "nucleo"; ruolo[seq[1]] = "coda";
      } else {
        for (const k of seq) ruolo[k] = "nucleo";
      }
      i = j;
    }
    const nuclei = [];
    for (let k = 0; k < n; k++) if (ruolo[k] === "nucleo") nuclei.push(k);
    let tonica = null;
    const accentati = nuclei.filter((k) => acc[k]);
    if (accentati.length) tonica = accentati[accentati.length - 1];
    else if (atona || !nuclei.length) tonica = null;
    else if (nuclei.length === 1) tonica = nuclei[0];
    else {
      let k = 2;
      if (ruolo[n - 1] === "coda" && base[n - 1] === "i") k = 1;
      else {
        let trovato = false;
        if (nuclei.length >= DATI.suffissi_min_nuclei) {
          for (const [s, kk] of SUFFISSI) if (piana.endsWith(s)) { k = kk; trovato = true; break; }
        }
        if (!trovato) for (const [re, kk] of SUFFISSI_REGEX) if (re.test(piana)) { k = kk; break; }
      }
      tonica = nuclei[nuclei.length - Math.min(k, nuclei.length)];
    }
    let vocaleTonica = null;
    if (tonica !== null && (base[tonica] === "e" || base[tonica] === "o")) {
      if (qual[tonica]) vocaleTonica = qual[tonica];
      else {
        const dittongo = (base[tonica] === "e" && tonica > 0 && base[tonica - 1] === "i" && (ruolo[tonica - 1] === "attacco" || muta[tonica - 1]))
          || (base[tonica] === "o" && tonica > 0 && base[tonica - 1] === "u" && ruolo[tonica - 1] === "attacco");
        if (dittongo) vocaleTonica = base[tonica] === "e" ? "ɛ" : "ɔ";
        else {
          const ammesse = base[tonica] === "e" ? ["e", "ɛ"] : ["o", "ɔ"];
          for (const [s, v] of SUFFISSI_VOCALE) {
            if (piana.endsWith(s) && tonica >= n - s.length && ammesse.includes(v)) { vocaleTonica = v; break; }
          }
          if (vocaleTonica === null) vocaleTonica = base[tonica];
        }
      }
    }
    const out = [];
    const dopo = (k) => (k + 1 < n ? base[k + 1] : "");
    let k = 0;
    while (k < n) {
      const c = base[k];
      if (vocale(c)) {
        if (muta[k]) { /* solo grafica */ }
        else if (semivU[k]) out.push(["w", 0]);
        else if (ruolo[k] === "attacco") out.push([c === "i" || c === "y" ? "j" : "w", 0]);
        else if (ruolo[k] === "coda") out.push([c === "i" || c === "y" ? "i" : "u", 0]);
        else {
          let v = c === "y" ? "i" : c;
          if (k === tonica && (c === "e" || c === "o")) v = vocaleTonica;
          out.push([v, k === tonica ? 1 : 0]);
        }
        k++;
        continue;
      }
      let n1 = dopo(k);
      let n2 = k + 2 < n ? base[k + 2] : "";
      const doppia = n1 === c && c !== "h";
      if (doppia) {
        k++;
        n1 = dopo(k);
        n2 = k + 2 < n ? base[k + 2] : "";
      }
      let fono = null, salta = 0;
      if (c === "h") { k++; continue; }
      if (c === "c") fono = n1 === "e" || n1 === "i" ? "tʃ" : "k";
      else if (c === "g") {
        if (n1 === "e" || n1 === "i") fono = "dʒ";
        else if (n1 === "n") { fono = "ɲ"; salta = 1; }
        else if (n1 === "l" && n2 === "i" && !glDuro) { fono = "ʎ"; salta = 1; }
        else fono = "ɡ";
      } else if (c === "s") {
        if (n1 === "c" && (n2 === "e" || n2 === "i")) { fono = "ʃ"; salta = 1; }
        else if (forza[k]) fono = forza[k];
        else if (doppia) fono = "s";
        else if (SONORE.has(n1)) fono = "z";
        else if (k > 0 && vocale(base[k - 1]) && vocale(n1)) fono = "z";
        else fono = "s";
      } else if (c === "z") {
        if (forza[k]) fono = forza[k];
        else if (doppia) fono = ZZ_SONORA.some((z) => z.test(piana)) ? "dz" : "ts";
        else if (k === 0) fono = "dz";
        else fono = "ts";
      } else if (c === "n") {
        const dura = (n1 === "c" && n2 !== "e" && n2 !== "i") || (n1 === "g" && !["e", "i", "n", "l"].includes(n2)) || n1 === "q" || n1 === "k";
        fono = dura ? "ŋ" : "n";
      } else if (c === "q") fono = "k";
      else if (c === "x") { out.push(["k", 0]); fono = "s"; }
      else if (c === "j") fono = "j";
      else if (c === "w") fono = "w";
      else if ("bdfklmprtv".includes(c)) fono = c;
      else { k++; continue; }
      if (doppia) out.push([fono, 0]);
      out.push([fono, 0]);
      k += 1 + salta;
    }
    let q = 1;
    while (q < out.length - 1) {
      const f = out[q][0];
      if (LUNGHE.has(f) && VOCALI_FONI.has(out[q - 1][0]) && out[q - 1][0] !== f && out[q + 1][0] !== f
          && (VOCALI_FONI.has(out[q + 1][0]) || out[q + 1][0] === "j" || out[q + 1][0] === "w")) {
        out.splice(q, 0, [f, 0]);
        q++;
      }
      q++;
    }
    return out;
  }

  // ---------------------------------------------------------------- testo in token

  const PEZZO = new RegExp("[" + LETTERE + "]+(?:'[" + LETTERE + "]+)*'?|[" + escape(PUNTEGGIATURA.join("")) + "]", "g");

  // Segni assenti dai dati di addestramento: si leggono come quelli che il modello conosce (vedi g2p_it.py).
  const SEGNI = { "(": ",", ")": ",", "—": ",", "…": ".", '"': "", "'": "" };

  function proclitica(parte, seguente) {
    if (/[aeiouyàèéìíòóùú]/.test(parte.toLowerCase()) || !seguente) return [];
    const uscita = [];
    const p = parte.toLowerCase();
    for (let i = 0; i < p.length; i++) {
      const c = p[i];
      const prossima = i + 1 < p.length ? p[i + 1] : seguente[0].toLowerCase();
      if (c === "c") uscita.push(["eiéèì".includes(prossima) ? "tʃ" : "k", 0]);
      else if (c === "g") uscita.push(["eiéèì".includes(prossima) ? "dʒ" : "ɡ", 0]);
      else if ("bdfklmnprstvz".includes(c)) uscita.push([{ k: "k", z: "dz" }[c] ?? c, 0]);
    }
    return uscita;
  }

  function pezzi(testo) {
    const uscita = [];
    let precedente = "";
    for (const m of normalizza(testo).matchAll(PEZZO)) {
      const s = m[0];
      if (PUNTEGGIATURA.includes(s)) {
        const segno = SEGNI[s] ?? s;
        if (segno && uscita.length) uscita.push([true, segno]);
        if (segno) precedente = "";
        continue;
      }
      let parola = [];
      const parti = s.split("'").filter((p) => p);
      parti.forEach((parte, i) => {
        let f = proclitica(parte, i + 1 < parti.length ? parti[i + 1] : "");
        if (!f.length) f = fonemiParola(parte, precedente);
        precedente = parte.toLowerCase();
        if (i + 1 < parti.length) f = f.map(([x]) => [x, 0]);
        parola = parola.concat(f);
      });
      if (parola.length) {
        if (uscita.length && !uscita[uscita.length - 1][0]) uscita[uscita.length - 1][1].push(parola);
        else uscita.push([false, [parola]]);
      }
    }
    return uscita;
  }

  function fonemi(testo) {
    const simboli = [BOS], accento = [0];
    for (const [punt, valore] of pezzi(testo)) {
      if (punt) {
        if (simboli[simboli.length - 1] !== valore) { simboli.push(valore); accento.push(0); }
        continue;
      }
      for (const parola of valore) {
        if (FONI.has(simboli[simboli.length - 1])) { simboli.push(SP); accento.push(0); }
        for (const [f, a] of parola) { simboli.push(f); accento.push(a); }
      }
    }
    simboli.push(EOS);
    accento.push(0);
    return { symbols: simboli, ids: simboli.map((s) => ID[s]), stress: accento };
  }

  return { normalizza, frasi, fonemi, fonemiParola, SYMBOLS };
}
