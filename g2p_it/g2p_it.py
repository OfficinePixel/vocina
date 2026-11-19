"""G2P italiano di bancollm per tiny-voca: testo → fonemi con l'accento, senza eSpeak.

Ha una gemella in JavaScript (``g2p_it.js``) per il browser: le due versioni leggono gli stessi dati
(``dati.json``) e devono dare gli stessi token. ``vettori.json`` sono le uscite di questa versione su un
insieme di frasi, e il test della versione JS le confronta una a una (``node prova_vettori.mjs``). Se si
cambia la logica qui va cambiata anche là, poi si rigenerano i vettori (``python g2p_it.py --vettori``).

Tre passi:
1. ``normalizza``: numeri, ore, date, importi, percentuali, unità, abbreviazioni, sigle e simboli in parole.
2. Le parole in fonemi con regole ortografiche: c/g dolci e dure, gn, gli, sc, qu, s sonora fra vocali e
   davanti a consonante sonora, z sorda o sonora, doppie come due fonemi uguali, consonanti lunghe per
   natura (ɲ ʎ ʃ ts dz) doppie fra vocali, n velare.
3. L'accento: lettera accentata, poi il lessico scritto a mano, poi suffissi, poi la penultima sillaba. Le
   e e le o toniche aperte o chiuse: lessico, dittonghi ie/uo, suffissi, poi chiuse.

Solo libreria standard.
"""

import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

VERSIONE = 1
DATI = json.loads((Path(__file__).with_name("dati.json")).read_text(encoding="utf-8"))

# L'inventario del fork italiano di tiny-voca, nello stesso ordine (vedi bancollm/voce/tinyvoca/italiano.patch).
PAD, BOS, EOS, SP, UNK = "<pad>", "<bos>", "<eos>", "<sp>", "<unk>"
PUNTEGGIATURA = (",", ".", "?", "!", ";", ":", '"', "'", "(", ")", "—", "…")
CONSONANTI = ("p", "b", "t", "d", "k", "ɡ", "f", "v", "s", "z", "ʃ", "m", "n", "ɲ", "ŋ",
              "l", "ʎ", "r", "ɾ", "j", "w", "ts", "dz", "tʃ", "dʒ")
VOCALI = ("a", "e", "ɛ", "i", "o", "ɔ", "u")
# Riservati (2026-11-18): in coda, mai prodotti dal G2P. Servono per insegnare più avanti, con un breve
# affinamento, suoni non verbali (respiro, risata…) senza cambiare la forma del modello.
RISERVATI = tuple(f"<riservato{i}>" for i in range(1, 9))
SYMBOLS = (PAD, BOS, EOS, SP, UNK) + PUNTEGGIATURA + CONSONANTI + VOCALI + RISERVATI
ID = {s: i for i, s in enumerate(SYMBOLS)}
FONI = frozenset(CONSONANTI + VOCALI)

LETTERE = "A-Za-zÀ-ÖØ-öø-ÿ"
ATONE = frozenset(DATI["atone"])
LESSICO = DATI["lessico"]
# Lessico dal Wikizionario (CC BY-SA 4.0, file a parte: vedi crea_lessico_wikizionario.py). Se manca, solo regole.
_WIKI = Path(__file__).with_name("lessico_wikizionario.json")
WIKIZIONARIO = json.loads(_WIKI.read_text(encoding="utf-8"))["voci"] if _WIKI.exists() else {}
OMOGRAFI = DATI["omografi"]
VARIANTI = DATI["varianti"]  # letture facoltative per nome, spente se non chieste: {"richard": …}
SUFFISSI = sorted(DATI["suffissi_accento"], key=lambda s: -len(s[0]))
SUFFISSI_REGEX = [(re.compile(r), k) for r, k in DATI["suffissi_regex"]]
SUFFISSI_TONICI = sorted(DATI["suffissi_tonici"], key=lambda s: -len(s[0]))
SUFFISSI_VOCALE = sorted(DATI["suffissi_vocale"], key=lambda s: -len(s[0]))
GL_DURO = DATI["gl_duro"]
ZZ_SONORA = DATI["zz_sonora"]
LETTERE_STRANIERE = DATI["lettere_straniere"]
NOMI_LETTERE = DATI["lettere_nomi"]
MESI = DATI["mesi"]

_ACCENTATE = {"à": ("a", None), "è": ("e", "ɛ"), "é": ("e", "e"), "ì": ("i", None), "í": ("i", None),
              "ò": ("o", "ɔ"), "ó": ("o", "o"), "ù": ("u", None), "ú": ("u", None)}
_FORZATE = {"ż": ("z", "dz"), "ź": ("z", "ts"), "ṡ": ("s", "z"), "ś": ("s", "s")}
_VOCALI_LETTERE = frozenset("aeiouy")
_SONORE = frozenset("bdglmnrv")
_LUNGHE = frozenset(("ɲ", "ʎ", "ʃ", "ts", "dz"))
_VOCALI_FONI = frozenset(VOCALI)


# ---------------------------------------------------------------- numeri in lettere

_UNITA = ["zero", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove", "dieci", "undici",
          "dodici", "tredici", "quattordici", "quindici", "sedici", "diciassette", "diciotto", "diciannove"]
_DECINE = ["", "", "venti", "trenta", "quaranta", "cinquanta", "sessanta", "settanta", "ottanta", "novanta"]


def _sotto_cento(n):
    if n < 20:
        return _UNITA[n]
    d, u = divmod(n, 10)
    t = _DECINE[d]
    if u in (1, 8):  # ventuno, ventotto
        t = t[:-1]
    return t + (_UNITA[u] if u else "")


def _sotto_mille(n):
    c, r = divmod(n, 100)
    testa = "" if c == 0 else ("cento" if c == 1 else _UNITA[c] + "cento")
    coda = _sotto_cento(r) if r else ""
    if testa and coda.startswith("ottant"):  # centottanta
        testa = testa[:-1]
    return testa + coda


def _sotto_milione(n):
    m, r = divmod(n, 1000)
    testa = "" if m == 0 else ("mille" if m == 1 else _sotto_mille(m) + "mila")
    s = testa + (_sotto_mille(r) if r else "")
    if n % 10 == 3 and n % 100 != 13 and n > 10:  # ventitré, centotré
        s = s[:-1] + "é"
    return s


def lettere(n):
    """Un intero da 0 a 999 999 999 999 in lettere; milioni e miliardi restano parole staccate."""
    if n == 0:
        return "zero"
    parti = []
    for valore, uno, molti in ((10 ** 9, "un miliardo", "miliardi"), (10 ** 6, "un milione", "milioni")):
        q, n = divmod(n, valore)
        if q:
            testa = _sotto_milione(q)
            if q > 1 and testa.endswith("uno"):  # ventun milioni
                testa = testa[:-1].replace("centoun", "centun")
            parti.append(uno if q == 1 else testa + " " + molti)
    if n:
        parti.append(_sotto_milione(n))
    return " ".join(parti)


def _cifre(s):
    return " ".join(_UNITA[int(c)] for c in s)


def _intero(s):
    """Un intero scritto con o senza i punti delle migliaia; gli zeri in testa si leggono cifra per cifra."""
    s = s.replace(".", "")
    if len(s) > 1 and s[0] == "0" or len(s) > 12:
        return _cifre(s)
    return lettere(int(s))


def _numero(intero, fraz=""):
    if not fraz:
        return _intero(intero)
    dopo = _cifre(fraz) if fraz[0] == "0" or len(fraz) > 3 else lettere(int(fraz))
    return _intero(intero) + " virgola " + dopo


def _euro(intero, cent):
    n, c = int(intero.replace(".", "")), int(cent or "0")
    s = ("un" if n == 1 else lettere(n)) + (" di euro" if n and n % 1000000 == 0 else " euro")
    if c:
        s += " e " + ("un centesimo" if c == 1 else lettere(c) + " centesimi")
    return s


def _ora(h, m):
    s = "l'una" if int(h) == 1 else lettere(int(h))
    if m == "00":
        return s
    return s + {"15": " e un quarto", "30": " e mezza"}.get(m, " e " + lettere(int(m)))


def _ordinale(n, femminile):
    base = ["", "primo", "secondo", "terzo", "quarto", "quinto", "sesto", "settimo", "ottavo", "nono", "decimo"]
    if n <= 10:
        s = base[n]
    else:
        s = lettere(n).replace(" ", "")
        if s.endswith("tré"):
            s = s[:-1] + "e"  # ventitreesimo
        elif not s.endswith("sei"):
            s = s[:-1]  # undicesimo, ventesimo, centesimo
        s += "esimo"
    return s[:-1] + "a" if femminile else s


# ---------------------------------------------------------------- normalizzazione

_NUM = r"[0-9]{1,3}(?:\.[0-9]{3})+|[0-9]+"
_ELISO = {"il": "l'", "Il": "L'", "del": "dell'", "Del": "Dell'", "dal": "dall'", "Dal": "Dall'", "al": "all'",
          "Al": "All'", "nel": "nell'", "Nel": "Nell'", "sul": "sull'", "Sul": "Sull'"}
_QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "`": "'", "´": "'", "“": '"', "”": '"', "„": '"',
                         "‟": '"', "«": '"', "»": '"', "–": "—", "―": "—", "[": "(", "{": "(", "]": ")", "}": ")"})


def _escape(s):
    return re.sub(r"([.*+?^${}()|\[\]\\/])", r"\\\1", s)


def _con_articolo(art, s):
    if not art:
        return s
    return _ELISO[art] + s if s[0] in "aeiou" else art + " " + s


def _sub(pattern, funzione, testo):
    return re.sub(pattern, funzione, testo)


def _pronunciabile(sigla):
    s = sigla.lower()
    return (re.search(r"[aeiou]", s) is not None and re.search(r"[^aeiou]{3}", s) is None
            and re.search(r"[^aeiou]{2}$", s) is None)


def _compita(lettere_):
    return " ".join(NOMI_LETTERE[c] for c in lettere_.lower() if c in NOMI_LETTERE)


def normalizza(testo):
    """Il testo con numeri, unità, abbreviazioni, sigle e simboli scritti in parole."""
    t = re.sub(r"(?<![0-9])([0-9]{1,4})(°|º|ª)(?!C)", lambda m: _ordinale(int(m[1]), m[2] == "ª"), testo)
    t = unicodedata.normalize("NFKC", t).translate(_QUOTES)
    t = re.sub(r"\.{3,}", "…", t)
    t = re.sub(r"-{2,}|\s-\s", " — ", t)
    for abbr, intera in DATI["abbreviazioni"]:
        for forma, piena in ((abbr, intera), (abbr[0].upper() + abbr[1:], intera[0].upper() + intera[1:])):
            t = re.sub("(?<![" + LETTERE + "])" + _escape(forma), piena, t)
    # valute
    t = re.sub(r"€\s?(" + _NUM + r")(?:,([0-9]{2}))?", lambda m: m[1] + ("," + m[2] if m[2] else "") + " euro", t)
    t = re.sub(r"(?<=[0-9])\s?€", " euro", t)
    t = t.replace("€", " euro ")
    t = re.sub(r"\$\s?(" + _NUM + r")", r"\1 dollari", t)
    # date: 12/03/2025, 12.03.2025
    def data(m):
        g, me, a = int(m[1]), int(m[2]), m[3]
        if not (1 <= g <= 31 and 1 <= me <= 12):
            return m[0]
        return ("primo" if g == 1 else lettere(g)) + " " + MESI[me - 1] + (" " + lettere(int(a)) if a else "")
    t = re.sub(r"(?<![0-9])([0-9]{1,2})[/.]([0-9]{1,2})(?:[/.]([0-9]{4}|[0-9]{2}))?(?![0-9])",
               lambda m: data(m) if m[3] or "/" in m[0] else m[0], t)
    t = re.sub(r"(?<![0-9])1 (" + "|".join(MESI) + ")", r"primo \1", t)
    # ore
    t = re.sub(r"(?<![0-9])([01]?[0-9]|2[0-4]):([0-5][0-9])(?![0-9])", lambda m: _ora(m[1], m[2]), t)
    t = re.sub(r"(?<![0-9.,])([01]?[0-9]|2[0-4])\.([0-5][0-9])(?![0-9]|[.,][0-9])", lambda m: _ora(m[1], m[2]), t)
    # unità di misura dopo un numero
    for sigla, una, molte in DATI["unita"]:
        def unita(m, una=una, molte=molte):
            art, meno, intero, fraz = m[1], m[2], m[3], m[4] or ""
            singolare = not fraz and intero == "1" and not meno
            if singolare:
                return _con_articolo(art, ("un'" if una[0] in "aeiou" else "un ") + una)
            return _con_articolo(art, ("meno " if meno else "") + _numero(intero, fraz) + " " + molte)
        t = re.sub(r"(?:(?<![" + LETTERE + r"])(il|Il|del|dal|Dal|al|nel|sul) )?(?:(?<![0-9" + LETTERE + r"])(-|−))?(" + _NUM + r")(?:,([0-9]+))?\s?"
                   + _escape(sigla) + r"(?![" + LETTERE + r"0-9²³])", unita, t)
    # importi, percentuali, numeri
    def numero(m):
        art = m[1]
        if m[2]:
            s = _euro(m[2], m[3])
        else:
            s = ("meno " if m[4] else "") + _numero(m[5], m[6] or "")
            if m[7]:
                s += " per cento"
        return _con_articolo(art, s)
    # sigla e numero attaccati: A4, COVID19
    t = re.sub(r"(?<=[0-9])x(?=[0-9])", " per ", t)
    t = re.sub(r"(?<![" + LETTERE + r"])([A-Z])(?=[0-9])", lambda m: NOMI_LETTERE[m[1].lower()] + " ", t)
    t = re.sub(r"([" + LETTERE + r"])(?=[0-9])", r"\1 ", t)
    t = re.sub(r"(?<=[0-9])(?=[" + LETTERE + r"])", " ", t)
    t = re.sub(r"(?:(?<![" + LETTERE + r"])(il|Il|del|Del|dal|Dal|al|Al|nel|Nel|sul|Sul) )?"
               r"(?:(" + _NUM + r"),([0-9]{2}) euro"
               r"|(?:(?<![0-9" + LETTERE + r"])(-|−))?(" + _NUM + r")(?:,([0-9]+))?(\s?%)?)", numero, t)
    for simbolo, parola in DATI["simboli"]:
        t = t.replace(simbolo, parola)
    t = t.replace("%", " per cento ")
    # sigle
    maiuscole = re.findall(r"(?<![" + LETTERE + r"])[A-ZÀ-ÖØ-Þ]{4,}(?![" + LETTERE + r"])", t)
    tutto_maiuscolo = len(maiuscole) >= 2
    def sigla(m):
        s = m[0]
        if s in DATI["sigle"]:
            return DATI["sigle"][s]
        if tutto_maiuscolo or (len(s) >= 4 and _pronunciabile(s)):
            return s.lower()
        return _compita(s)
    t = re.sub(r"(?<![" + LETTERE + r"])[A-ZÀ-ÖØ-Þ]{2,}(?![" + LETTERE + r"])", sigla, t)
    # una consonante maiuscola da sola si compita: «G2P» → «gi due pi»
    t = re.sub(r"(?<![" + LETTERE + r"'])([B-DF-HJ-NP-TV-Z])(?![" + LETTERE + r"'.])", lambda m: NOMI_LETTERE[m[1].lower()], t)
    # iniziali: «G. Verdi»
    t = re.sub(r"(?<![" + LETTERE + r"])([A-Z])\.(?= [A-Z])", lambda m: NOMI_LETTERE[m[1].lower()], t)
    t = re.sub(r"(?<=[" + LETTERE + r"])-(?=[" + LETTERE + r"])", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------- frasi

def frasi(testo):
    """Le frasi del testo normalizzato, con il punto finale quando manca."""
    t = normalizza(testo)
    parti = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", t) if p.strip()]
    uscita = []
    for p in parti:
        if not re.search("[" + LETTERE + "]", p):
            continue
        if not re.search(r"[.!?…,;:][\"')]*$", p):
            p += "."
        uscita.append(p)
    return uscita


# ---------------------------------------------------------------- parole in fonemi

def _lettere_di(parola):
    """Le lettere della grafia (dal lessico o dal testo), con accento, qualità e sonorità forzate."""
    base, acc, qual, forza = [], [], [], []
    for c in parola:
        if c in _ACCENTATE:
            b, q = _ACCENTATE[c]
            base.append(b); acc.append(True); qual.append(q); forza.append(None)
        elif c in _FORZATE:
            b, f = _FORZATE[c]
            base.append(b); acc.append(False); qual.append(None); forza.append(f)
        else:
            base.append(c); acc.append(False); qual.append(None); forza.append(None)
    return base, acc, qual, forza


def _vocale(c):
    return c in _VOCALI_LETTERE


def _sostituzioni(varianti):
    """Le parole da leggere con un'altra grafia per le varianti chieste (nomi in ``VARIANTI``)."""
    sost = {}
    for nome in varianti:
        if nome not in VARIANTI:
            raise ValueError(f"variante sconosciuta: {nome}")
        sost.update(VARIANTI[nome]["parole"])
    return sost


def fonemi_parola(parola, precedente="", varianti=()):
    """Una parola (solo lettere) in ``[(fono, accento)]``; accento 1 sulla vocale tonica. ``precedente`` è la
    parola prima (minuscola), per gli omografi: «cerca di impórti», «ti impòrti». ``varianti``: nomi in
    ``VARIANTI`` («richard»: «euro» → «iuro»), che vengono prima di ogni lessico."""
    w = "".join(LETTERE_STRANIERE.get(c, c) for c in parola.lower())
    w = re.sub("[^a-zàèéìíòóùú]", "", w)
    if not w:
        return []
    if not re.search("[aeiouyàèéìíòóùú]", w):
        uscita = []
        for c in w:
            for nome in NOMI_LETTERE[c].split():
                uscita += fonemi_parola(nome)
        return uscita
    piana = unicodedata.normalize("NFD", w)
    piana = re.sub("[̀-ͯ]", "", piana)
    # La parola com'è scritta (con gli accenti del testo): «pensò» non è «penso». Prima il lessico scritto a
    # mano, poi quello del Wikizionario.
    r = _sostituzioni(varianti).get(w) or LESSICO.get(w) or WIKIZIONARIO.get(w) or w
    for regola, grafia in OMOGRAFI.get(piana, []):
        if re.search(regola, precedente):
            r = grafia
            break
    return da_grafia(r, w, piana)


def da_grafia(r, w, piana):
    """I fonemi di una grafia del lessico (accenti, qualità e ż ź ṡ ś), per la parola ``w`` (minuscola, con gli
    accenti del testo) e ``piana`` (senza)."""
    base, acc, qual, forza = _lettere_di(r)
    n = len(base)
    atona = w in ATONE and not any(acc)
    gl_duro = any(g in piana for g in GL_DURO)
    # vocale tonica fissata dal suffisso (farmacìa, pizzerìa, ventidùe, ebràica), se nessun accento è scritto
    if not any(acc) and not atona and sum(_vocale(c) for c in base) >= 4:
        for s, da_fine in SUFFISSI_TONICI:
            if piana.endswith(s) and n == len(piana):
                acc[n - da_fine] = True
                break
    # i solo grafica (ci, gi, sci, gli davanti a vocale) e u semivocale dopo q e g
    muta = [False] * n
    semiv_u = [False] * n
    for i, c in enumerate(base):
        if c == "h":
            muta[i] = True
        if c == "i" and not acc[i] and 0 < i < n - 1 and _vocale(base[i + 1]) and base[i + 1] != "i":
            p = base[i - 1]
            if p in "cg" or (p == "l" and i >= 2 and base[i - 2] == "g" and not gl_duro):
                muta[i] = True
        if c == "u" and not acc[i] and i > 0 and base[i - 1] in "qg" and i < n - 1 and _vocale(base[i + 1]):
            semiv_u[i] = True
    # nuclei: vocali sonore raggruppate in sequenze
    ruolo = [None] * n  # "nucleo", "attacco" (j w), "coda" (i u dopo vocale)
    i = 0
    while i < n:
        if not _vocale(base[i]) or muta[i] or semiv_u[i]:
            i += 1
            continue
        j = i
        while j < n and _vocale(base[j]) and not muta[j] and not semiv_u[j]:
            j += 1
        seq = list(range(i, j))
        forte = [acc[k] or base[k] in "aeo" for k in seq]
        if any(forte):
            for a, k in enumerate(seq):
                if forte[a]:
                    ruolo[k] = "nucleo"
                elif a + 1 < len(seq) and forte[a + 1]:
                    ruolo[k] = "attacco"
                elif a > 0 and forte[a - 1]:
                    ruolo[k] = "coda"
                else:
                    ruolo[k] = "nucleo"
        elif len(seq) == 2 and base[seq[0]] == "i" and base[seq[1]] == "u":
            ruolo[seq[0]], ruolo[seq[1]] = "attacco", "nucleo"
        elif len(seq) == 2 and base[seq[0]] == "u" and base[seq[1]] == "i":
            ruolo[seq[0]], ruolo[seq[1]] = "nucleo", "coda"
        else:
            for k in seq:
                ruolo[k] = "nucleo"
        i = j
    nuclei = [k for k in range(n) if ruolo[k] == "nucleo"]
    # accento
    tonica = None
    accentati = [k for k in nuclei if acc[k]]
    if accentati:
        tonica = accentati[-1]
    elif atona or not nuclei:
        tonica = None
    elif len(nuclei) == 1:
        tonica = nuclei[0]
    else:
        k = 2
        if ruolo[n - 1] == "coda" and base[n - 1] == "i":  # farai, potrei
            k = 1
        else:
            trovato = False
            if len(nuclei) >= DATI["suffissi_min_nuclei"]:
                for s, kk in SUFFISSI:
                    if piana.endswith(s):
                        k, trovato = kk, True
                        break
            if not trovato:
                for r_, kk in SUFFISSI_REGEX:
                    if r_.search(piana):
                        k = kk
                        break
        tonica = nuclei[len(nuclei) - min(k, len(nuclei))]
    # qualità della e e della o toniche
    vocale_tonica = None
    if tonica is not None and base[tonica] in "eo":
        if qual[tonica]:
            vocale_tonica = qual[tonica]
        else:
            dittongo = (base[tonica] == "e" and tonica > 0 and base[tonica - 1] == "i" and (ruolo[tonica - 1] == "attacco" or muta[tonica - 1])) or \
                       (base[tonica] == "o" and tonica > 0 and base[tonica - 1] == "u" and ruolo[tonica - 1] == "attacco")
            if dittongo:
                vocale_tonica = "ɛ" if base[tonica] == "e" else "ɔ"
            else:
                for s, v in SUFFISSI_VOCALE:
                    if piana.endswith(s) and tonica >= n - len(s) and v in (("e", "ɛ") if base[tonica] == "e" else ("o", "ɔ")):
                        vocale_tonica = v
                        break
                if vocale_tonica is None:
                    vocale_tonica = base[tonica]
    # fonemi
    out = []  # [fono, accento]

    def dopo(k):
        """La prima lettera dopo k che si pronuncia o che conta per la grafia (h compresa)."""
        return base[k + 1] if k + 1 < n else ""

    k = 0
    while k < n:
        c = base[k]
        if _vocale(c):
            if muta[k]:
                pass
            elif semiv_u[k]:
                out.append(["w", 0])
            elif ruolo[k] == "attacco":
                out.append(["j" if c in "iy" else "w", 0])
            elif ruolo[k] == "coda":
                out.append(["i" if c in "iy" else "u", 0])
            else:
                v = "i" if c == "y" else c
                if k == tonica and c in "eo":
                    v = vocale_tonica
                out.append([v, 1 if k == tonica else 0])
            k += 1
            continue
        n1 = dopo(k)
        n2 = base[k + 2] if k + 2 < n else ""
        doppia = n1 == c and c not in "h"
        if doppia:
            k += 1  # la seconda lettera dà il suono, e si ripete
            n1 = dopo(k)
            n2 = base[k + 2] if k + 2 < n else ""
        fono = None
        salta = 0
        if c == "h":
            k += 1
            continue
        if c == "c":
            fono = "tʃ" if n1 in ("e", "i") else "k"
        elif c == "g":
            if n1 in ("e", "i"):
                fono = "dʒ"
            elif n1 == "n":
                fono, salta = "ɲ", 1
            elif n1 == "l" and n2 == "i" and not gl_duro:
                fono, salta = "ʎ", 1
            else:
                fono = "ɡ"
        elif c == "s":
            if n1 == "c" and n2 in ("e", "i"):
                fono, salta = "ʃ", 1
            elif forza[k]:
                fono = forza[k]
            elif doppia:
                fono = "s"
            elif n1 in _SONORE:
                fono = "z"
            elif k > 0 and _vocale(base[k - 1]) and _vocale(n1):
                fono = "z"
            else:
                fono = "s"
        elif c == "z":
            if forza[k]:
                fono = forza[k]
            elif doppia:
                fono = "dz" if any(re.search(z, piana) for z in ZZ_SONORA) else "ts"
            elif k == 0:
                fono = "dz"
            else:
                fono = "ts"
        elif c == "n":
            prossima_dura = (n1 == "c" and n2 not in ("e", "i")) or (n1 == "g" and n2 not in ("e", "i", "n", "l")) or n1 in ("q", "k")
            fono = "ŋ" if prossima_dura else "n"
        elif c == "q":
            fono = "k"
        elif c == "x":
            out.append(["k", 0])
            fono = "s"
        elif c == "j":
            fono = "j"
        elif c == "w":
            fono = "w"
        elif c in "bdfklmprtv":
            fono = c
        else:
            k += 1
            continue
        if doppia:
            out.append([fono, 0])
        out.append([fono, 0])
        k += 1 + salta
    # consonanti lunghe per natura fra vocali: ɲ ʎ ʃ ts dz
    i = 1
    while i < len(out) - 1:
        f = out[i][0]
        if f in _LUNGHE and out[i - 1][0] in _VOCALI_FONI and out[i - 1][0] != f and out[i + 1][0] != f \
                and (out[i + 1][0] in _VOCALI_FONI or out[i + 1][0] in ("j", "w")):
            out.insert(i, [f, 0])
            i += 1
        i += 1
    return [(f, a) for f, a in out]


# ---------------------------------------------------------------- testo in token

_PEZZO = re.compile(r"[" + LETTERE + r"]+(?:'[" + LETTERE + r"]+)*'?|[" + _escape("".join(PUNTEGGIATURA)) + r"]")


# Segni che nei dati di addestramento non ci sono (il filtro dei testi li esclude): si leggono come quelli
# che il modello conosce. Parentesi e lineetta fanno la pausa della virgola; virgolette e apostrofo isolato no.
SEGNI = {"(": ",", ")": ",", "—": ",", "…": ".", '"': "", "'": ""}


def _proclitica(parte, seguente):
    """Le parti senza vocale prima dell'apostrofo (l', c', d', m', s'…) sono solo consonanti."""
    if re.search("[aeiouyàèéìíòóùú]", parte.lower()) or not seguente:
        return []
    uscita = []
    for i, c in enumerate(parte.lower()):
        prossima = parte[i + 1].lower() if i + 1 < len(parte) else seguente[0].lower()
        if c == "c":
            uscita.append(("tʃ" if prossima in "eiéèì" else "k", 0))
        elif c == "g":
            uscita.append(("dʒ" if prossima in "eiéèì" else "ɡ", 0))
        elif c in "bdfklmnprstvz":
            uscita.append(({"k": "k", "z": "dz"}.get(c, c), 0))
    return uscita


def pezzi(testo, varianti=()):
    """``[(è_punteggiatura, valore)]`` come li vuole ``tiny_voca.text.tokenize``: per il testo una lista di
    parole, ognuna ``[(fono, accento)]``. Le parti unite dall'apostrofo fanno una parola sola."""
    _sostituzioni(varianti)  # un nome sconosciuto è un errore anche se il testo non lo tocca
    uscita = []
    precedente = ""
    for m in _PEZZO.finditer(normalizza(testo)):
        s = m[0]
        if s in PUNTEGGIATURA:
            s = SEGNI.get(s, s)
            if s and uscita:  # nessun segno in testa all'emissione
                uscita.append((True, s))
            if s:
                precedente = ""
            continue
        parola = []
        parti = [p for p in s.split("'") if p]
        for i, parte in enumerate(parti):
            f = _proclitica(parte, parti[i + 1] if i + 1 < len(parti) else "") or fonemi_parola(parte, precedente, varianti)
            precedente = parte.lower()
            if i + 1 < len(parti):  # la parte elisa è atona: dell', quest', sant'
                f = [(x, 0) for x, _ in f]
            parola += f
        if parola:
            if uscita and not uscita[-1][0]:
                uscita[-1][1].append(parola)
            else:
                uscita.append((False, [parola]))
    return uscita


def fonemi(testo, varianti=()):
    """Token del testo: ``{"symbols", "ids", "stress"}``, con le stesse regole di ``tiny_voca.text.tokenize``.
    ``varianti``: letture facoltative per nome (``VARIANTI``), per esempio ``["richard"]``: «10 €» → «dieci iuro»."""
    simboli, accento = [BOS], [0]
    for punt, valore in pezzi(testo, varianti):
        if punt:
            if simboli[-1] != valore:
                simboli.append(valore)
                accento.append(0)
            continue
        for parola in valore:
            if simboli[-1] in FONI:
                simboli.append(SP)
                accento.append(0)
            for f, a in parola:
                simboli.append(f)
                accento.append(a)
    simboli.append(EOS)
    accento.append(0)
    return {"symbols": simboli, "ids": [ID[s] for s in simboli], "stress": accento}


def impronta():
    """sha256 di versione, inventario e dati: le etichette e il modello registrano questa."""
    h = hashlib.sha256()
    h.update(json.dumps({"versione": VERSIONE, "simboli": SYMBOLS}, ensure_ascii=False).encode())
    h.update((Path(__file__).with_name("dati.json")).read_bytes())
    if _WIKI.exists():
        h.update(_WIKI.read_bytes())
    return h.hexdigest()


def leggibile(f):
    """I token in una riga leggibile, con ˈ davanti alla vocale tonica."""
    return " ".join(("ˈ" if a else "") + s for s, a in zip(f["symbols"], f["stress"]))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--vettori"]:
        frasi_prova = Path(__file__).with_name("frasi_prova.txt").read_text(encoding="utf-8").splitlines()
        vettori = []
        for t in frasi_prova:
            if not t.strip() or t.startswith("#"):
                continue
            # «[richard] 10 €»: la frase con le varianti fra quadre
            varianti = t[1:t.index("]")].split(",") if t.startswith("[") else []
            t = t[t.index("]") + 1:].strip() if varianti else t
            vettori.append({"testo": t, **({"varianti": varianti} if varianti else {}), "normalizzato": normalizza(t),
                            "frasi": frasi(t), **fonemi(t, varianti)})
        Path(__file__).with_name("vettori.json").write_text(
            json.dumps({"versione": VERSIONE, "impronta": impronta(), "vettori": vettori}, ensure_ascii=False, indent=0),
            encoding="utf-8")
        print(len(vettori), "vettori")
    else:
        for t in sys.argv[1:] or sys.stdin.read().splitlines():
            print(normalizza(t))
            print("  ", leggibile(fonemi(t)))
