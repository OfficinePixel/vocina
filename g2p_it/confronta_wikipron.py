"""Il G2P contro le trascrizioni del Wikizionario inglese estratte da WikiPron (italiano, «broad»).

    python confronta_wikipron.py ita_latn_broad.tsv TESTI.jsonl ... --uscita CARTELLA

WikiPron (CUNY-CL/wikipron, data/scrape/tsv/ita_latn_broad.tsv; codice Apache 2.0, dati del Wiktionary
CC BY-SA) toglie i segni d'accento. Resta però la qualità delle vocali: in italiano ɛ e ɔ stanno solo in
sillaba tonica, quindi una parola con ɛ o ɔ dice anche dov'è l'accento. Si misura:

- **segmenti**: la sequenza dei fonemi senza le differenze di sola notazione (vedi ``piatta``);
- **accento**, solo dove il Wiktionary ha ɛ o ɔ: la vocale tonica nostra è quella?
- **e/o**: dove l'accento coincide, aperta o chiusa come il Wiktionary; e, nelle parole senza ɛ/ɔ, quante
  volte noi apriamo una e o una o tonica che il Wiktionary scrive chiusa.

Fuori: nomi propri (maiuscola), più parole, fonemi non italiani (parole straniere). Una parola con più
pronunce vale giusta se una coincide. ``TESTI.jsonl`` (campo text) dà le frequenze: le misure si ripetono
sulle parole che compaiono nei nostri testi, pesate per occorrenze.
"""

import argparse
import collections
import json
import re
from pathlib import Path

import g2p_it as G

AFFRICATE = {"t͡ʃ": "tʃ", "d͡ʒ": "dʒ", "t͡s": "ts", "d͡z": "dz"}
ITALIANI = set(G.CONSONANTI + G.VOCALI)
LETTERE = re.compile(r"^[a-zàèéìíòóùú]+$")


def wiki(trascrizione):
    out = []
    for p in trascrizione.split():
        p = AFFRICATE.get(p, p)
        if p.endswith("ː"):
            p = AFFRICATE.get(p[:-1], p[:-1])
            out.append(p)
        out.append(p)
    return out


def nostra(parola):
    coppie = G.fonemi_parola(parola)
    return [p for p, _ in coppie], [a for _, a in coppie]


_LUNGHE = {("t", "tʃ"): "tʃ", ("d", "dʒ"): "dʒ", ("t", "ts"): "ts", ("d", "dz"): "dz"}


def piatta(seq):
    """Per i segmenti, senza le differenze di sola notazione: e/ɛ, o/ɔ, ŋ/n, j/i e w/u (dittongo o iato
    scritti in modi diversi), affricate lunghe scritte «t tʃ» dal Wiktionary e «tʃ tʃ» da noi."""
    seq = [{"ɛ": "e", "ɔ": "o", "ŋ": "n", "j": "i", "w": "u"}.get(p, p) for p in seq]
    return [_LUNGHE.get((p, seq[i + 1]), p) if i + 1 < len(seq) else p for i, p in enumerate(seq)]


def giudica(parola, pron):
    """Per una pronuncia del Wiktionary: dict con segmenti, accento ed e/o (None dove non si può dire)."""
    w = wiki(pron)
    n, acc = nostra(parola)
    r = {"segmenti": piatta(w) == piatta(n), "accento": None, "eo": None, "apriamo_noi": None,
         "w": " ".join(w), "n": " ".join(("ˈ" if a else "") + p for p, a in zip(n, acc))}
    if not r["segmenti"]:
        return r
    aperte = [i for i, p in enumerate(w) if p in ("ɛ", "ɔ")]
    tonica = [i for i, a in enumerate(acc) if a]
    if len(aperte) == 1:
        r["accento"] = tonica == aperte
        if r["accento"]:
            r["eo"] = n[aperte[0]] == w[aperte[0]]
    elif not aperte and tonica and n[tonica[0]] in ("ɛ", "ɔ"):
        r["apriamo_noi"] = True
    elif not aperte and tonica and n[tonica[0]] in ("e", "o"):
        r["apriamo_noi"] = False
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tsv", type=Path)
    ap.add_argument("testi", type=Path, nargs="*")
    ap.add_argument("--uscita", type=Path, required=True)
    a = ap.parse_args()

    pron = collections.defaultdict(list)
    for riga in a.tsv.read_text(encoding="utf-8").splitlines():
        parola, t = riga.split("\t")
        if LETTERE.match(parola) and set(wiki(t)) <= ITALIANI:
            pron[parola].append(t)

    freq = collections.Counter()
    for f in a.testi:
        for riga in f.read_text(encoding="utf-8").splitlines():
            for w in re.findall(r"[a-zàèéìíòóùú]+", json.loads(riga)["text"].lower()):
                freq[w] += 1

    esiti = {}
    for parola, ts in pron.items():
        giudizi = [giudica(parola, t) for t in ts]
        # la pronuncia più favorevole: segmenti, poi accento, poi e/o
        esiti[parola] = max(giudizi, key=lambda g: (g["segmenti"], g["accento"] is not False, g["eo"] is not False,
                                                     g["apriamo_noi"] is not True))

    def conta(parole, peso):
        c = collections.Counter()
        for p in parole:
            e, k = esiti[p], peso(p)
            c["parole"] += k
            c["segmenti_ok"] += k * e["segmenti"]
            if e["accento"] is not None:
                c["accento_misurabile"] += k
                c["accento_ok"] += k * e["accento"]
            if e["eo"] is not None:
                c["eo_misurabile"] += k
                c["eo_ok"] += k * e["eo"]
            if e["apriamo_noi"] is not None:
                c["chiuse_wiki"] += k
                c["aperte_noi"] += k * e["apriamo_noi"]
        return c

    tutte = sorted(esiti)
    nostre = [p for p in tutte if freq[p]]
    righe = {
        "tutto il Wiktionary (per parola)": conta(tutte, lambda p: 1),
        "parole dei nostri testi (per parola)": conta(nostre, lambda p: 1),
        "parole dei nostri testi (per occorrenza)": conta(nostre, lambda p: freq[p]),
    }
    a.uscita.mkdir(parents=True, exist_ok=True)
    with open(a.uscita / "riepilogo.txt", "w", encoding="utf-8") as f:
        for nome, c in righe.items():
            pct = lambda x, y: f"{c[x]}/{c[y]} ({100 * c[x] / max(1, c[y]):.1f}%)"
            testo = (f"{nome}: parole {c['parole']}\n"
                     f"  segmenti uguali      {pct('segmenti_ok', 'parole')}\n"
                     f"  accento giusto       {pct('accento_ok', 'accento_misurabile')}   (dove il Wiktionary ha ɛ/ɔ)\n"
                     f"  e/o giusta           {pct('eo_ok', 'eo_misurabile')}   (accento giusto, Wiktionary aperta)\n"
                     f"  noi aperta, W chiusa {pct('aperte_noi', 'chiuse_wiki')}   (tonica e/o, Wiktionary senza ɛ/ɔ)\n")
            print(testo)
            f.write(testo + "\n")
    with open(a.uscita / "differenze.tsv", "w", encoding="utf-8") as f:
        f.write("tipo\tparola\tfreq\twiktionary\tnoi\n")
        for p in sorted(tutte, key=lambda p: -freq[p]):
            e = esiti[p]
            tipo = ("segmenti" if not e["segmenti"] else "accento" if e["accento"] is False else
                    "eo" if e["eo"] is False else "aperta_noi" if e["apriamo_noi"] else None)
            if tipo:
                f.write(f"{tipo}\t{p}\t{freq[p]}\t{e['w']}\t{e['n']}\n")


if __name__ == "__main__":
    main()
