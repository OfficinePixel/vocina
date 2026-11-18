"""Il lessico del Wikizionario per il G2P: ``lessico_wikizionario.json`` (CC BY-SA 4.0) dal Wiktionary (kaikki.org e WikiPron).

    python crea_lessico_wikizionario.py ita_latn_broad.tsv --kaikki kaikki.org-dictionary-Italian.jsonl.gz --kaikki-data AAAA-MM-GG

Per ogni parola del Wiktionary si cerca la grafia del lessico (accento con è ò é ó à ì ù, ż ź ṡ ś per s e z)
che fa dire al G2P la stessa pronuncia. Si scrive solo dove le regole sbagliano. Quello che si prende dal
Wiktionary:
- s e z sorde o sonore;
- dove c'è una ɛ o una ɔ (in italiano stanno solo in sillaba tonica), l'accento e la vocale aperta;
- dove non ce ne sono e le regole aprono la tonica, la vocale chiusa; ma non nei dittonghi ie e uo, dove il
  Wiktionary a volte non segna l'aperta (pensièri, vuòte).

Non si scrive niente se la parola:
- è già nel lessico a mano (che vince sempre), o è fra le atone;
- ha più pronunce che portano a grafie diverse (omografi come pèsca/pésca). Se le pronunce hanno lo stesso
  accento e differiscono solo per s e z sorde o sonore, o per la e/o aperta o chiusa (varianti regionali), si
  tiene l'accento comune, s e z restano alle regole e la vocale è quella della prima pronuncia;
- ha suoni che non si ottengono con queste correzioni (parole straniere, iato e dittongo, errori del
  Wiktionary): quelle si contano a parte.

Licenza: i dati vengono dal Wiktionary inglese (contributori del Wiktionary, CC BY-SA 4.0), estratti da
kaikki.org (wiktextract, Ylonen 2022) e da WikiPron (CUNY-CL/wikipron, Apache 2.0). Il file generato è un'opera derivata e resta CC BY-SA 4.0, a parte
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


VOCALI_IPA = frozenset("aeiouɛɔ")


def da_ipa(ipa):
    """Una trascrizione IPA del Wiktionary («/riˈt͡ʃe.ve.re/») in ``(fonemi, indice della tonica)``; la tonica è
    None se non è segnata (monosillabi). None se non è una parola sola o ha segni che non trattiamo."""
    s = ipa.strip().strip("/")
    if not s or any(c in s for c in " ‿()[]|-*~,"):
        return None
    s = s.replace(".", "").replace("ˌ", "")
    foni, tonica, segnata, i = [], None, False, 0
    while i < len(s):
        if s[i] == "ˈ":
            segnata = True
            i += 1
            continue
        if s[i] == "ː":
            if not foni:
                return None
            foni.append(foni[-1])
            i += 1
            continue
        p = s[i:i + 3] if s[i:i + 3] in AFFRICATE else s[i]
        i += len(p)
        p = AFFRICATE.get(p, p)
        if segnata and p in VOCALI_IPA:
            tonica, segnata = len(foni), False
        foni.append(p)
    if s.count("ˈ") > 1:
        return None
    foni = [LUNGHE.get((p, foni[k + 1]), p) if k + 1 < len(foni) else p for k, p in enumerate(foni)]
    return foni, tonica


def confrontabile(seq):
    """Senza le differenze di sola notazione: ŋ/n, j/i e w/u."""
    return [{"ŋ": "n", "j": "i", "w": "u"}.get(p, p) for p in seq]


def grafia_per(parola, w, tonica=None):
    """La grafia minima che fa dire ``w`` (fonemi del Wiktionary) al G2P, con l'accento su ``tonica`` (indice in
    ``w``) se il Wiktionary lo segna; "" se basta la parola com'è, None se non si trova."""
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
    if not aperte and (tonica is None or t_reg == [tonica]) and t_reg and foni_regole[t_reg[0]] in ("ɛ", "ɔ") and t_reg[0] > 0 and foni_regole[t_reg[0] - 1] in ("j", "w"):
        return ""

    def giusta(foni, acc):
        if tonica is not None:  # accento dal Wiktionary: posizione e qualità della tonica, tutto il resto uguale
            return confrontabile(foni) == obiettivo and [i for i, a in enumerate(acc) if a] == [tonica]
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
    ap.add_argument("--kaikki", type=Path, help="kaikki.org-dictionary-Italian.jsonl.gz: le trascrizioni con l'accento")
    ap.add_argument("--kaikki-data", default="", help="data dell'estratto (Last-Modified)")
    a = ap.parse_args()
    # Prima kaikki.org (Wiktionary con l'accento segnato); WikiPron (senza accenti) per le parole che mancano.
    pron = collections.defaultdict(list)
    if a.kaikki:
        import gzip
        for riga in gzip.open(a.kaikki, "rt", encoding="utf-8"):
            d = json.loads(riga)
            if not PAROLA.match(d.get("word", "")):
                continue
            for s in d.get("sounds", []):
                r = da_ipa(s["ipa"]) if "ipa" in s else None
                if r and set(r[0]) <= ITALIANI and r not in pron[d["word"].lower()]:
                    pron[d["word"].lower()].append(r)
    da_kaikki = set(pron)
    for riga in a.tsv.read_text(encoding="utf-8").splitlines():
        parola, t = riga.split("\t")
        if PAROLA.match(parola) and parola.lower() not in da_kaikki and set(wiki(t)) <= ITALIANI:
            pron[parola.lower()].append((wiki(t), None))
    voci, conti = {}, collections.Counter()
    for parola, ws in sorted(pron.items()):
        if parola in G.LESSICO or parola in G.ATONE:
            conti["già nel lessico o atona"] += 1
            continue
        lista = [grafia_per(parola, w, k) for w, k in ws]
        grafie = set(lista)
        if None not in grafie and len(grafie) > 1:
            # Varianti con lo stesso accento, che differiscono solo per s e z (sorde toscane e sonore del nord,
            # «presènta») o per la e/o aperta o chiusa (partècipa e partécipa): l'accento è comune; s e z
            # restano alle regole, e per la vocale vale la prima pronuncia, che il Wiktionary dà per principale.
            senza_sz = lambda g: re.sub("[śṡźż]", lambda m: {"ś": "s", "ṡ": "s", "ź": "z", "ż": "z"}[m[0]], g or parola)
            chiave = lambda g: senza_sz(g).replace("é", "è").replace("ó", "ò")
            if len({chiave(g) for g in grafie}) == 1:
                diverse_sz = len({re.sub("[éó]", "", chiave(g)) != re.sub("[éó]", "", g or parola) for g in grafie}) > 1 \
                    or len({tuple(re.findall("[śṡźż]", g or "")) for g in grafie}) > 1
                g = senza_sz(lista[0]) if diverse_sz else (lista[0] or parola)
                grafie = {"" if g == parola else g}
                conti["varianti unite"] += 1
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
                        "CC BY-SA 4.0; estratte da kaikki.org (wiktextract, https://kaikki.org/dictionary/Italian/, "
                        f"estratto del {a.kaikki_data}) e, per le parole che lì mancano, da WikiPron "
                        f"(https://github.com/CUNY-CL/wikipron, commit {a.commit}, data/scrape/tsv/ita_latn_broad.tsv). Convertite nella grafia del lessico di "
                        "g2p_it (accento, e/o aperte o chiuse, s e z sorde o sonore) da crea_lessico_wikizionario.py; "
                        "solo le parole che le regole del G2P sbagliano.",
        "conti": dict(conti),
        "voci": voci,
    }
    USCITA.write_text(json.dumps(dati, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(dict(conti), USCITA, f"{USCITA.stat().st_size / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
