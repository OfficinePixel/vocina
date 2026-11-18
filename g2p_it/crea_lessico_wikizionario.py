"""Il lessico del Wikizionario per il G2P: ``lessico_wikizionario.json`` (CC BY-SA 4.0) dalle trascrizioni di WikiPron.

    python crea_lessico_wikizionario.py ita_latn_broad.tsv [--commit HASH]

Per ogni parola del Wiktionary si cerca la grafia del lessico (accento con è ò é ó à ì ù, ż ź ṡ ś per s e z)
che fa dire al G2P la stessa pronuncia. Si scrive solo dove le regole sbagliano. Quello che si prende dal
Wiktionary:
- s e z sorde o sonore;
- dove c'è una ɛ o una ɔ (in italiano stanno solo in sillaba tonica), l'accento e la vocale aperta;
- dove non ce ne sono e le regole aprono la tonica, la vocale chiusa; ma non nei dittonghi ie e uo, dove il
  Wiktionary a volte non segna l'aperta (pensièri, vuòte).

Non si scrive niente se la parola:
- è già nel lessico a mano (che vince sempre), o è fra le atone;
- ha più pronunce che portano a grafie diverse (omografi come pèsca/pésca). Se le pronunce differiscono solo
  per s e z sorde o sonore (varianti regionali) si tiene l'accento comune e s e z restano alle regole;
- ha suoni che non si ottengono con queste correzioni (parole straniere, iato e dittongo, errori del
  Wiktionary): quelle si contano a parte.

Licenza: i dati vengono dal Wiktionary inglese (contributori del Wiktionary, CC BY-SA 4.0), estratti da
WikiPron (CUNY-CL/wikipron, Apache 2.0). Il file generato è un'opera derivata e resta CC BY-SA 4.0, a parte
dal resto del G2P (Apache 2.0).
"""

import argparse
import collections
import itertools
import json
import re
import unicodedata
from pathlib import Path

import g2p_it as G

QUI = Path(__file__).parent
USCITA = QUI / "lessico_wikizionario.json"
AFFRICATE = {"t͡ʃ": "tʃ", "d͡ʒ": "dʒ", "t͡s": "ts", "d͡z": "dz"}
LUNGHE = {("t", "tʃ"): "tʃ", ("d", "dʒ"): "dʒ", ("t", "ts"): "ts", ("d", "dz"): "dz"}
ITALIANI = set(G.CONSONANTI + G.VOCALI)
PAROLA = re.compile(r"^[A-Za-zàèéìíòóùú]+$")
TONICHE = {"a": "à", "e": ("è", "é"), "i": "ì", "o": ("ò", "ó"), "u": "ù"}


def wiki(trascrizione):
    """La trascrizione del Wiktionary nella notazione nostra: affricate lunghe «tʃ tʃ», ː come doppia."""
    out = []
    for p in trascrizione.split():
        lunga = p.endswith("ː")
        p = AFFRICATE.get(p.rstrip("ː"), p.rstrip("ː"))
        out += [p, p] if lunga else [p]
    return [LUNGHE.get((p, out[i + 1]), p) if i + 1 < len(out) else p for i, p in enumerate(out)]


def confrontabile(seq):
    """Senza le differenze di sola notazione: ŋ/n, j/i e w/u."""
    return [{"ŋ": "n", "j": "i", "w": "u"}.get(p, p) for p in seq]


def grafia_per(parola, w):
    """La grafia minima che fa dire ``w`` (fonemi del Wiktionary) al G2P; "" se basta la parola com'è, None se
    non si trova."""
    piana = re.sub("[̀-ͯ]", "", unicodedata.normalize("NFD", parola))
    obiettivo = confrontabile(w)
    aperte = [i for i, p in enumerate(w) if p in ("ɛ", "ɔ")]
    lettere = list(parola)
    # s e z: le lettere che si possono forzare (di una doppia, la seconda)
    sz = [i for i, c in enumerate(lettere) if c in "sz" and not (c == "s" and lettere[i + 1:i + 2] == ["c"])
          and not (i + 1 < len(lettere) and lettere[i + 1] == c)]
    if len(sz) > 4:
        return None
    vocali = [i for i, c in enumerate(lettere) if c in "aeiou"]
    scritto = any(c in "àèéìíòóùú" for c in lettere)

    def prova(gr):
        f = G.da_grafia(gr, parola, piana)
        return [p for p, _ in f], [a for _, a in f]

    foni_regole, acc_regole = prova(parola)
    # Il Wiktionary a volte non segna l'aperta nei dittonghi ie e uo (pensieri, vuote): lì restano le regole.
    t_reg = [i for i, a in enumerate(acc_regole) if a]
    if not aperte and t_reg and foni_regole[t_reg[0]] in ("ɛ", "ɔ") and t_reg[0] > 0 and foni_regole[t_reg[0] - 1] in ("j", "w"):
        return ""

    def giusta(foni, acc):
        if confrontabile([{"ɛ": "e", "ɔ": "o"}.get(p, p) for p in foni]) != \
                [{"ɛ": "e", "ɔ": "o"}.get(p, p) for p in obiettivo]:
            return False
        if len(aperte) == 1:
            return [i for i, a in enumerate(acc) if a] == aperte and foni[aperte[0]] == w[aperte[0]]
        if not aperte:  # l'accento non lo dice: resta quello delle regole, e la tonica non è aperta
            return acc == acc_regole and not any(p in ("ɛ", "ɔ") for p in foni)
        return False  # due aperte: parole composte, non le trattiamo

    # le varianti, dalla più semplice: prima nessuna correzione, poi solo s/z, poi l'accento, poi tutte e due
    scelte_sz = [[(i, None)] + [(i, {"s": "ś", "z": "ź"}[lettere[i]]), (i, {"s": "ṡ", "z": "ż"}[lettere[i]])] for i in sz]
    for n_sz in range(len(sz) + 1):
        for combo in itertools.product(*scelte_sz):
            if sum(1 for _, f in combo if f) != n_sz:
                continue
            base = lettere[:]
            for i, f in combo:
                if f:
                    base[i] = f
            accenti = [None] if scritto else [None] + [(i, v) for i in vocali for v in
                                                          (TONICHE[lettere[i]] if isinstance(TONICHE[lettere[i]], tuple)
                                                           else (TONICHE[lettere[i]],))]
            for a in accenti:
                gr = base[:]
                if a:
                    gr[a[0]] = a[1]
                gr = "".join(gr)
                if giusta(*prova(gr)):
                    return "" if gr == parola else gr
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tsv", type=Path)
    ap.add_argument("--commit", default="d282e848a211")
    a = ap.parse_args()
    pron = collections.defaultdict(list)
    for riga in a.tsv.read_text(encoding="utf-8").splitlines():
        parola, t = riga.split("\t")
        if PAROLA.match(parola) and set(wiki(t)) <= ITALIANI:
            pron[parola.lower()].append(wiki(t))
    voci, conti = {}, collections.Counter()
    for parola, ws in sorted(pron.items()):
        if parola in G.LESSICO or parola in G.ATONE:
            conti["già nel lessico o atona"] += 1
            continue
        grafie = {grafia_per(parola, w) for w in ws}
        if None not in grafie and len(grafie) > 1:
            # Varianti che differiscono solo per s e z (sorde toscane e sonore del nord, «presènta»): si
            # prende l'accento, comune a tutte, e s e z restano alle regole.
            ridotte = {re.sub("[śṡźż]", lambda m: {"ś": "s", "ṡ": "s", "ź": "z", "ż": "z"}[m[0]], g or parola) for g in grafie}
            if len(ridotte) == 1:
                g = ridotte.pop()
                grafie = {"" if g == parola else g}
                conti["varianti di s e z unite"] += 1
        if None in grafie:
            conti["non ottenibile"] += 1
        elif len(grafie) > 1:
            conti["pronunce diverse"] += 1
        elif grafie == {""}:
            conti["le regole bastano"] += 1
        else:
            voci[parola] = grafie.pop()
            conti["scritte"] += 1
    dati = {
        "licenza": "CC BY-SA 4.0",
        "attribuzione": "Trascrizioni dal Wiktionary inglese (https://en.wiktionary.org), contributori del Wiktionary, "
                        "CC BY-SA 4.0; estratte da WikiPron (https://github.com/CUNY-CL/wikipron, commit "
                        f"{a.commit}, data/scrape/tsv/ita_latn_broad.tsv). Convertite nella grafia del lessico di "
                        "g2p_it (accento, e/o aperte o chiuse, s e z sorde o sonore) da crea_lessico_wikizionario.py; "
                        "solo le parole che le regole del G2P sbagliano.",
        "conti": dict(conti),
        "voci": voci,
    }
    USCITA.write_text(json.dumps(dati, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(dict(conti), USCITA, f"{USCITA.stat().st_size / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
