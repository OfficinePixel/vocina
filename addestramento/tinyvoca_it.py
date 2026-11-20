"""Dati per tiny-voca in italiano: testi, voce disegnata, generazione e filtro, tutto via QBert.

Compito `_bacheca/2026-11-17-bancollm-tiny-voca-italiano.md`, tappa 2 (pilota). È la ricetta del modello
inglese (voce disegnata con Qwen3-TTS VoiceDesign, poi tutte le frasi lette da Qwen3-TTS Base con quella
voce come riferimento, filtro con Whisper), rifatta per l'italiano e per i servizi dello studio:

1. ``testi``: frasi di Common Voice italiano (CC0) e modelli di frase nostri (numeri, date, ore, importi,
   percentuali, nomi, domande), con origine e licenza per riga. Validazione e test sono frasi fisse.
2. ``voce``: tre candidati da ``/voice-design`` di qwen-tts con la stessa descrizione; si sceglie quello che
   Whisper ritrascrive meglio. Nessuna voce clonata da persone reali.
3. ``genera``: ogni frase letta da ``/voice-clone`` con il candidato scelto come riferimento, 24 kHz.
   Riprendibile: una frase già su disco non si rifà.
4. ``filtra``: tutto ritrascritto da fast-whisper large-v3-turbo in italiano (dopo la generazione, per non
   alternare i due modelli sulla GPU) e confrontato **sui fonemi** di eSpeak NG, così le cifre del testo e
   quelle di Whisper si confrontano letti allo stesso modo. Scartati oltre il 15% di errore sui fonemi, con anche
   una sola parola diversa dal testo (lettera per lettera, accenti e spazi a parte), e le
   durate o velocità implausibili; poi il manifest JSONL per ``tiny-voca-prepare``.

    ~/Modelli/runtime/tiny-voca/.venv/bin/python -m bancollm.voce.tinyvoca_it testi|voce|genera|filtra [--ore 2.5]

Serve un Python con numpy e soundfile: il Python di sistema non li ha, quello di tiny-voca sì.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import time
import unicodedata
from pathlib import Path

import numpy as np
import soundfile as sf

from .g2p_it import g2p_it as G2P

RADICE = Path(__file__).resolve().parents[2]
CARTELLA = RADICE / "dati" / "tts" / "2026-11-17-tiny-voca" / "pilota"
TESTI_CV = Path.home() / "Modelli" / "tiny-voca" / "testi-it"
SEME = 20261117

DESCRIZIONE = ("Una donna italiana adulta, sui trentacinque anni, con una voce chiara di timbro medio. "
               "Italiano standard senza inflessioni regionali, tono calmo, neutro e cordiale, "
               "dizione nitida e ritmo moderato, come una buona lettrice di audiolibri.")
DESCRIZIONE_MASCHILE = ("Un uomo italiano adulto, sui quarant'anni, con una voce chiara di timbro medio-grave. "
                        "Italiano standard senza inflessioni regionali, tono calmo, neutro e cordiale, "
                        "dizione nitida e ritmo moderato, come un buon lettore di audiolibri.")
TESTO_VOCE = ("Buongiorno. Oggi vi racconto com'è andata la settimana: lunedì ha piovuto, ma da mercoledì "
              "è tornato il sole. Vi aspetto sabato mattina alle dieci e mezza, in piazza. Va bene per tutti?")

CV_FILE = {"frasi.txt": "cv_frasi", "sentence-collector.txt": "cv_sentence_collector",
           "wiki.it.rerun-2021-10.txt": "cv_wiki"}
CV_URL = "https://github.com/common-voice/common-voice/tree/{commit}/server/data/it"
_ITALIANO = re.compile(r"^[A-Za-zÀÈÉÌÍÒÓÙÚàèéìíòóùú' ,.;:!?\-]+$")


# ---------------------------------------------------------------- testi

def _frasi_cv(rng: random.Random) -> dict[str, list[str]]:
    out = {}
    for nome in CV_FILE:
        righe = []
        for r in (TESTI_CV / nome).read_text(encoding="utf-8").splitlines():
            r = unicodedata.normalize("NFC", r.strip())
            if not 25 <= len(r) <= 150 or not _ITALIANO.match(r) or r[-1] not in ".!?":
                continue
            parole = r.split()
            # Troppe maiuscole dentro la frase = nomi propri, spesso stranieri.
            if sum(p[0].isupper() for p in parole[1:]) > max(1, len(parole) // 6):
                continue
            righe.append(r)
        righe = sorted(set(righe))
        rng.shuffle(righe)
        out[nome] = righe
    return out


MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
        "ottobre", "novembre", "dicembre"]
NOMI = ["Giulia", "Marco", "Francesca", "Luca", "Chiara", "Matteo", "Elena", "Davide", "Sara", "Andrea",
        "Martina", "Alessandro", "Valentina", "Lorenzo", "Federica", "Giovanni", "Silvia", "Paolo", "Anna",
        "Stefano", "Roberta", "Nicola", "Ilaria", "Tommaso", "Beatrice", "Riccardo"]
COGNOMI = ["Rossi", "Bianchi", "Ferrari", "Esposito", "Romano", "Colombo", "Ricci", "Marino", "Greco",
           "Bruno", "Gallo", "Conti", "De Luca", "Mancini", "Costa", "Giordano", "Rizzo", "Lombardi",
           "Moretti", "Zanetti", "Bortolin", "Pozzobon", "Dal Molin", "Zanella", "Scarpa", "Furlan"]
LUOGHI = ["Vicenza", "Padova", "Treviso", "Verona", "Bassano del Grappa", "Schio", "Thiene", "Dueville",
          "Castelfranco Veneto", "Montebelluna", "Valdobbiadene", "Asiago", "Arzignano", "Cittadella",
          "Feltre", "Belluno", "Chioggia", "Rovigo", "Este", "Marostica", "Recoaro Terme", "Valdagno"]
COSE = ["la riunione", "la consegna", "il controllo", "la visita", "l'appuntamento", "il corso",
        "la prova", "il sopralluogo", "la partenza", "l'assemblea"]
FEMMINILI = {"Giulia", "Francesca", "Chiara", "Elena", "Sara", "Martina", "Valentina", "Federica", "Silvia",
             "Anna", "Roberta", "Ilaria", "Beatrice", "l'assemblea"}


def _accorda(cosa: str, radice: str) -> str:
    """«la riunione è fissata», «il controllo è fissato»."""
    return radice + ("a" if cosa.startswith("la ") or cosa in FEMMINILI else "o")


def _ed(testo: str) -> str:
    """«Anna ed Elena»."""
    return re.sub(r" e (?=[AEIOU])", " ed ", testo)


def _a(luogo: str) -> str:
    """«a Vicenza», «ad Arzignano»."""
    return ("ad " if luogo[0] in "AEIOU" else "a ") + luogo


# ---------------------------------------------------------------- numeri in lettere
# qwen-tts legge male le cifre (sentito dall'utente il 2026-11-17): i modelli di frase si scrivono in
# lettere, e il testo di addestramento è quello letto. La forma in cifre resta in ``text_cifre``, per
# provare poi il normalizzatore del G2P nostro.

_UNITA = ["zero", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove", "dieci", "undici",
          "dodici", "tredici", "quattordici", "quindici", "sedici", "diciassette", "diciotto", "diciannove"]
_DECINE = ["", "", "venti", "trenta", "quaranta", "cinquanta", "sessanta", "settanta", "ottanta", "novanta"]


def _sotto_cento(n: int) -> str:
    if n < 20:
        return _UNITA[n]
    d, u = divmod(n, 10)
    t = _DECINE[d]
    if u in (1, 8):  # ventuno, ventotto
        t = t[:-1]
    return t + (_UNITA[u] if u else "")


def _sotto_mille(n: int) -> str:
    c, r = divmod(n, 100)
    testa = "" if c == 0 else ("cento" if c == 1 else _UNITA[c] + "cento")
    coda = _sotto_cento(r) if r else ""
    if testa and coda.startswith("ottant"):  # centottanta
        testa = testa[:-1]
    return testa + coda


def lettere(n: int) -> str:
    """Un intero da 0 a 999 999 999 999 in lettere: 1863 → «milleottocentosessantatré»,
    2 300 015 → «due milioni trecentomilaquindici». Milioni e miliardi restano parole staccate."""
    if n == 0:
        return "zero"
    if n >= 10 ** 12:
        raise ValueError(f"numero troppo grande: {n}")
    parti = []
    for valore, uno, molti in ((10 ** 9, "un miliardo", "miliardi"), (10 ** 6, "un milione", "milioni")):
        q, n = divmod(n, valore)
        if q:
            testa = _sotto_milione(q)
            if q > 1 and testa.endswith("uno"):  # ventun milioni, centun milioni
                testa = testa[:-1].replace("centoun", "centun")
            parti.append(uno if q == 1 else f"{testa} {molti}")
    if n:
        parti.append(_sotto_milione(n))
    return " ".join(parti)


def _sotto_milione(n: int) -> str:
    m, r = divmod(n, 1000)
    testa = "" if m == 0 else ("mille" if m == 1 else _sotto_mille(m) + "mila")
    s = testa + (_sotto_mille(r) if r else "")
    if n % 10 == 3 and n % 100 != 13 and n > 10:  # ventitré, centotré
        s = s[:-1] + "é"
    return s


def _decimale(intero: str, fraz: str) -> str:
    dopo = " ".join(_UNITA[int(c)] for c in fraz) if fraz.startswith("0") else lettere(int(fraz))
    return f"{lettere(int(intero.replace('.', '')))} virgola {dopo}"


def _euro(intero: str, cent: str) -> str:
    n, c = int(intero.replace(".", "")), int(cent or 0)
    s = ("un" if n == 1 else lettere(n)) + (" di euro" if n and n % 10 ** 6 == 0 else " euro")  # un milione di euro
    if c:
        s += " e " + ("un centesimo" if c == 1 else lettere(c) + " centesimi")
    return s


def _ora(h: str, m: str) -> str:
    s = lettere(int(h))
    return s + {"00": "", "15": " e un quarto", "30": " e mezza"}.get(m, f" e {lettere(int(m))}")


_ELISO = {"il": "l'", "Il": "L'", "del": "dell'", "dal": "dall'", "Dal": "Dall'", "al": "all'", "nel": "nell'"}
_NUMERO = re.compile(
    r"(?:\b(?P<art>il|Il|del|dal|Dal|al|nel) )?"
    r"(?:(?P<h>\d{1,2}):(?P<m>\d{2})"
    r"|(?P<ei>\d{1,3}(?:\.\d{3})*),(?P<ec>\d{2}) euro"
    r"|(?P<i>\d{1,3}(?:\.\d{3})+|\d+)(?:,(?P<f>\d+))?(?P<pc>%)?)")


def in_lettere(testo: str) -> str:
    """Cifre, ore, importi e percentuali in lettere, con l'articolo eliso davanti a vocale."""
    def sost(mt):
        if mt["h"]:
            s = _ora(mt["h"], mt["m"])
        elif mt["ei"]:
            s = _euro(mt["ei"], mt["ec"])
        else:
            s = _decimale(mt["i"], mt["f"]) if mt["f"] else lettere(int(mt["i"].replace(".", "")))
            if mt["pc"]:
                s += " per cento"
        art = mt["art"]
        if not art:
            return s
        return _ELISO[art] + s if s[0] in "aeiou" else f"{art} {s}"
    return _NUMERO.sub(sost, testo)


def _numero(rng: random.Random) -> str:
    tipo = rng.randrange(4)
    if tipo == 0:
        return str(rng.randint(0, 999))
    if tipo == 1:
        return f"{rng.randint(1000, 99999):,}".replace(",", ".")
    if tipo == 2:
        return f"{rng.randint(0, 999)},{rng.randint(1, 99)}"
    return str(rng.randint(1, 20))


def _modelli(rng: random.Random, quante: int) -> list[tuple[str, str]]:
    """Frasi con cifre, date, ore, importi, nomi e domande, nelle forme che eSpeak NG legge bene
    (niente date con le barre, niente «km» o «1°»: eSpeak li legge male, li sistemerà il G2P nostro)."""
    def data():
        return f"{rng.randint(2, 28)} {rng.choice(MESI)} {rng.randint(1950, 2030)}"  # «1 maggio» eSpeak lo legge «uno»

    def ora():
        return f"{rng.randint(7, 22)}:{rng.choice(['00', '05', '10', '15', '20', '30', '40', '45', '50'])}"

    def persona():
        return f"{rng.choice(NOMI)} {rng.choice(COGNOMI)}"

    def chiamata():
        nome, cognome = rng.choice(NOMI), rng.choice(COGNOMI)
        return f"Ha chiamato {nome} {cognome}: richiama{'la' if nome in FEMMINILI else 'lo'} appena puoi."

    def cosa_data(modello):
        cosa = rng.choice(COSE)
        return modello.format(cosa=cosa, cosa_m=cosa.capitalize(), fissat=_accorda(cosa, "fissat"),
                              spostat=_accorda(cosa, "spostat"),
                              stat=_accorda(cosa, "stat"), data=data())

    def importo():
        return f"{rng.randint(1, 4999):,}".replace(",", ".") + f",{rng.randint(0, 99):02d} euro"

    schemi = [
        ("numeri", lambda: f"Nel magazzino ci sono {_numero(rng)} scatole e {_numero(rng)} bancali."),
        ("numeri", lambda: f"La temperatura è scesa a {rng.randint(0, 15)},{rng.randint(1, 9)} gradi, "
                           f"con il {rng.randint(40, 99)}% di umidità."),
        ("numeri", lambda: f"Il livello del fiume è salito di {rng.randint(2, 180)} centimetri in "
                           f"{rng.randint(2, 48)} ore."),
        ("date", lambda: cosa_data("{cosa_m} è {fissat} per il {data}.")),
        ("date", lambda: f"Ci siamo conosciuti il {data()}, {_a(rng.choice(LUOGHI))}."),
        ("date", lambda: f"Dal {rng.randint(2, 15)} al {rng.randint(16, 30)} {rng.choice(MESI)} "
                         f"l'ufficio resta chiuso."),
        ("ore", lambda: f"Il treno per {rng.choice(LUOGHI)} parte alle {ora()} dal binario {rng.randint(1, 12)}."),
        ("ore", lambda: f"Ci vediamo alle {ora()}, non più tardi."),
        ("importi", lambda: f"Il totale della fattura è di {importo()}, IVA compresa."),
        ("importi", lambda: f"Ho speso {importo()} per la spesa e {importo()} per la benzina."),
        ("percentuali", lambda: f"Le vendite sono cresciute del {rng.randint(1, 60)}% rispetto al "
                                f"{rng.randint(1990, 2025)}."),
        ("nomi", lambda: f"{persona()} abita {_a(rng.choice(LUOGHI))} da {rng.randint(2, 40)} anni."),
        ("nomi", chiamata),
        ("nomi", lambda: _ed(f"Domani {rng.choice(NOMI)} e {rng.choice(NOMI)} vanno {_a(rng.choice(LUOGHI))}.")),
        ("domande", lambda: f"Scusi, a che ora chiude la farmacia di {rng.choice(LUOGHI)}?"),
        ("domande", lambda: f"Hai già sentito {persona()} per {rng.choice(COSE)}?"),
        ("domande", lambda: f"Quanto costa il biglietto per {rng.choice(LUOGHI)}?"),
        ("domande", lambda: cosa_data("Perché {cosa} è {stat} {spostat} al {data}?")),
        ("domande", lambda: f"Mi sai dire dove si trova {rng.choice(['la stazione', 'il municipio', 'la posta', 'l''ospedale', 'la biblioteca'])}?"),
        ("esclamazioni", lambda: f"Che bella notizia, {rng.choice(NOMI)}! Sono proprio contenta."),
        ("esclamazioni", lambda: f"Accidenti, abbiamo perso il treno delle {ora()}!"),
    ]
    visti, out = set(), []
    while len(out) < quante:
        categoria, f = rng.choice(schemi)
        t = f()
        if t not in visti:
            visti.add(t)
            out.append((categoria, t))
    return out


def testi(cartella: Path, modelli: int = 450, validazione: int = 40, prova: int = 40) -> list[dict]:
    rng = random.Random(SEME)
    commit = (TESTI_CV / "COMMIT").read_text().strip()
    cv = _frasi_cv(rng)
    righe = []

    def aggiungi(testo, split, categoria, origine, licenza, url):
        r = {"id": f"it{len(righe):05d}", "text": testo, "split": split, "category": categoria,
             "origin": origine, "source_license": licenza, "source_url": url}
        if origine == "bancollm_modelli":
            r["text"], r["text_cifre"] = in_lettere(testo), testo
        righe.append(r)

    url_cv = CV_URL.format(commit=commit)
    # Validazione e prova: metà conversazione, metà modelli, fisse per sempre (stesso seme).
    for split, n in (("validation", validazione), ("test", prova)):
        for t in cv["frasi.txt"][:n // 2]:
            aggiungi(t, split, "conversazione", CV_FILE["frasi.txt"], "cc0-1.0", url_cv)
        cv["frasi.txt"] = cv["frasi.txt"][n // 2:]
        for cat, t in _modelli(rng, n - n // 2):
            aggiungi(t, split, cat, "bancollm_modelli", "project-own", "")
    # Addestramento: modelli e Common Voice, mescolati, nell'ordine in cui si generano.
    treno = [(c, t, "bancollm_modelli", "project-own", "") for c, t in _modelli(rng, modelli)]
    for nome, quota in (("frasi.txt", 0.55), ("sentence-collector.txt", 0.15), ("wiki.it.rerun-2021-10.txt", 0.30)):
        cat = "conversazione" if nome == "frasi.txt" else "lettura"
        treno += [(cat, t, CV_FILE[nome], "cc0-1.0", url_cv) for t in cv[nome][:int(3000 * quota)]]
    rng.shuffle(treno)
    gia = {r.get("text_cifre", r["text"]) for r in righe}
    for cat, t, origine, licenza, url in treno:
        if t not in gia:
            gia.add(t)
            aggiungi(t, "train", cat, origine, licenza, url)
    cartella.mkdir(parents=True, exist_ok=True)
    (cartella / "testi.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in righe),
                                         encoding="utf-8")
    return righe


# ---------------------------------------------------------------- QBert

def _qbert():
    from ..backend.qbert_client import QBert
    return QBert("http://127.0.0.1:1999", app_name="bancollm", timeout=40.0)


def _risposta(qb, tk, attesa_max=1800):
    if tk.done:
        return tk.response
    from .tts import _attendi
    return _attendi(qb, tk.id)


def trascrivi(qb, wav: Path) -> str:
    from .tts import a_wav16
    w16 = a_wav16(wav, wav.with_suffix(".16k.wav"))
    try:
        with open(w16, "rb") as f:
            tk = qb.submit("fast-whisper", "/transcribe?language=it&model_name=large-v3-turbo", priority="lazy",
                           note=f"tiny-voca-it {wav.stem}", files={"file": (w16.name, f, "audio/wav")})
        r = _risposta(qb, tk)
    finally:
        w16.unlink(missing_ok=True)
    if r is None or r.status_code != 200:
        raise RuntimeError(f"trascrizione fallita: {wav}")
    return r.json().get("text", "").strip()


# ---------------------------------------------------------------- fonemi e confronto

def fonemi(testo: str) -> list[str]:
    """Fonemi del G2P nostro, senza accento e senza doppie: per confrontare testo e trascrizione.
    (Fino alla tappa 2 erano quelli di eSpeak NG.)"""
    out = []
    for s_ in G2P.fonemi(testo)["symbols"]:
        if s_ in G2P.FONI and not (out and out[-1] == s_):
            out.append(s_)
    return out


def distanza(a: list, b: list) -> int:
    riga = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prec, riga[0] = riga[0], i
        for j, y in enumerate(b, 1):
            prec, riga[j] = riga[j], min(riga[j] + 1, riga[j - 1] + 1, prec + (x != y))
    return riga[-1]


def errore_fonemi(testo: str, trascritto: str) -> float:
    a, b = fonemi(testo), fonemi(trascritto or "…")
    return distanza(a, b) / max(1, len(a))


# ---------------------------------------------------------------- voce

def voce(cartella: Path, candidati: int = 3, descrizione: str = DESCRIZIONE, stampa=print) -> dict:
    qb = _qbert()
    d = cartella / "voce"
    d.mkdir(parents=True, exist_ok=True)
    esiti = []
    for i in range(1, candidati + 1):
        wav = d / f"candidato-{i}.wav"
        if not wav.exists():
            tk = qb.submit("qwen-tts", "/voice-design", priority="lazy", note=f"tiny-voca-it voce {i}",
                           json={"text": TESTO_VOCE, "instruct": descrizione, "language": "italian", "format": "wav"})
            r = _risposta(qb, tk)
            if r is None or r.status_code != 200:
                raise RuntimeError(f"voice-design fallita: {getattr(r, 'status_code', None)}")
            wav.write_bytes(r.content)
        x, sr = sf.read(wav)
        esiti.append({"candidato": i, "file": wav.name, "secondi": round(len(x) / sr, 2), "sr": sr})
    for e in esiti:
        e["trascritto"] = trascrivi(qb, d / e["file"])
        e["errore_fonemi"] = round(errore_fonemi(TESTO_VOCE, e["trascritto"]), 4)
        stampa(f"candidato {e['candidato']}: {e['secondi']} s, errore {e['errore_fonemi']:.3f}  {e['trascritto']}")
    scelto = min(esiti, key=lambda e: (e["errore_fonemi"], abs(e["secondi"] - 12)))
    info = {"descrizione": descrizione, "testo": TESTO_VOCE, "modello": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
            "servizio": "qwen-tts via QBert (/voice-design)", "candidati": esiti, "scelto": scelto["candidato"],
            "criterio": "errore sui fonemi più basso, poi durata più vicina a 12 s"}
    (d / "voce.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    stampa(f"scelto il candidato {scelto['candidato']}")
    return info


# ---------------------------------------------------------------- generazione

def genera(cartella: Path, ore: float, stampa=print) -> None:
    qb = _qbert()
    info = json.loads((cartella / "voce" / "voce.json").read_text())
    rif = cartella / "voce" / f"candidato-{info['scelto']}.wav"
    righe = [json.loads(r) for r in (cartella / "testi.jsonl").read_text(encoding="utf-8").splitlines()]
    audio = cartella / "audio"
    audio.mkdir(exist_ok=True)
    registro = cartella / "generazione.jsonl"
    secondi_treno = 0.0
    for r in righe:
        wav = audio / f"{r['id']}.wav"
        if wav.exists():
            if r["split"] == "train":
                secondi_treno += sf.info(wav).duration
            continue
        if r["split"] == "train" and secondi_treno >= ore * 3600 * 1.1:  # 10% in più per gli scarti
            break
        inizio = time.time()
        with open(rif, "rb") as f:
            tk = qb.submit("qwen-tts", "/voice-clone", priority="lazy", note=f"tiny-voca-it {r['id']}",
                           data={"text": r["text"], "ref_text": info["testo"], "language": "italian",
                                 "format": "wav"},
                           files={"file": (rif.name, f, "audio/wav")})
        rr = _risposta(qb, tk)
        if rr is None or rr.status_code != 200:
            stampa(f"{r['id']}: generazione fallita ({getattr(rr, 'status_code', None)})")
            continue
        wav.write_bytes(rr.content)
        durata = sf.info(wav).duration
        if r["split"] == "train":
            secondi_treno += durata
        with registro.open("a", encoding="utf-8") as g:
            g.write(json.dumps({"id": r["id"], "secondi": round(durata, 3), "parete": round(time.time() - inizio, 2),
                                "quando": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")
        if int(r["id"][2:]) % 50 == 0:
            stampa(f"{r['id']}: addestramento {secondi_treno / 3600:.2f} h")
    stampa(f"fine: addestramento {secondi_treno / 3600:.2f} h generate")


# ---------------------------------------------------------------- filtro e manifest

def da_whisper(testo: str) -> str:
    """La trascrizione di Whisper con cifre, ore, «cm» ed «€» in parole, come il testo letto."""
    return G2P.normalizza(testo)


def _lettere_sole(testo: str) -> str:
    t = unicodedata.normalize("NFD", G2P.normalizza(testo).lower())
    return "".join(c for c in t if "a" <= c <= "z")


def filtra(cartella: Path, soglia: float = 0.15, stampa=print) -> None:
    qb = _qbert()
    righe = [json.loads(r) for r in (cartella / "testi.jsonl").read_text(encoding="utf-8").splitlines()]
    cache_f = cartella / "trascrizioni.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    accettate, scartate = [], []
    for n, r in enumerate(righe):
        wav = cartella / "audio" / f"{r['id']}.wav"
        if not wav.exists():
            continue
        if r["id"] not in cache:
            cache[r["id"]] = trascrivi(qb, wav)
            if n % 25 == 0:
                cache_f.write_text(json.dumps(cache, ensure_ascii=False, indent=0))
        x, sr = sf.read(wav, dtype="float32")
        durata, motivi = len(x) / sr, []
        if sr != 24000:
            motivi.append(f"frequenza {sr}")
        if not 0.5 <= durata <= 35:
            motivi.append("durata")
        parole = len(r["text"].split())
        if durata and not 0.5 <= parole / durata <= 7:
            motivi.append("velocità")
        if float(np.mean(np.abs(x) < 1e-4)) > 0.8:
            motivi.append("silenzio")
        sentito = da_whisper(cache[r["id"]])
        err = errore_fonemi(r["text"], sentito)
        if err > soglia:
            motivi.append("trascrizione")
        elif _lettere_sole(r["text"]) != _lettere_sole(sentito):
            motivi.append("parola")  # una parola letta male («monarcia») sta sotto la soglia sulla frase
        picco = float(np.max(np.abs(x))) or 1.0
        voce_rif = {**r, "voice_id": r.get("voice_id", "I1"), "audio": f"audio/{r['id']}.wav", "duration_seconds": round(durata, 3),
                    "teacher_model": "Qwen/Qwen3-TTS-12Hz-1.7B-Base", "asr_transcript": cache[r["id"]],
                    "phoneme_error": round(err, 4), "review_reasons": motivi}
        if motivi:
            scartate.append(voce_rif)
            continue
        if abs(picco - 0.95) > 0.01:  # come l'inglese: picco normalizzato a 0,95
            sf.write(wav, x * (0.95 / picco), sr, subtype="PCM_16")
        accettate.append(voce_rif)
    cache_f.write_text(json.dumps(cache, ensure_ascii=False, indent=0))
    for split in ("train", "validation", "test"):
        sel = [r for r in accettate if r["split"] == split]
        (cartella / f"{split}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in sel),
                                               encoding="utf-8")
        stampa(f"{split}: {len(sel)} clip, {sum(r['duration_seconds'] for r in sel) / 3600:.2f} h")
    (cartella / "scartate.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in scartate),
                                            encoding="utf-8")
    stampa(f"scartate {len(scartate)}: " + ", ".join(
        f"{m} {sum(m in r['review_reasons'] for r in scartate)}"
        for m in ("trascrizione", "parola", "durata", "velocità", "silenzio")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("passo", choices=["testi", "voce", "genera", "filtra"])
    ap.add_argument("--cartella", type=Path, default=CARTELLA)
    ap.add_argument("--ore", type=float, default=2.5, help="ore di addestramento da generare")
    ap.add_argument("--maschile", action="store_true", help="voce: la descrizione maschile (tappa 3)")
    a = ap.parse_args()
    if a.passo == "testi":
        r = testi(a.cartella)
        for s in ("train", "validation", "test"):
            print(s, sum(x["split"] == s for x in r))
    elif a.passo == "voce":
        voce(a.cartella, descrizione=DESCRIZIONE_MASCHILE if a.maschile else DESCRIZIONE)
    elif a.passo == "genera":
        genera(a.cartella, a.ore)
    else:
        filtra(a.cartella)


if __name__ == "__main__":
    main()
