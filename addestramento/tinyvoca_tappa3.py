"""tiny-voca italiano, tappa 3: dati per due voci, letti dai testi già normalizzati dal G2P nostro.

Compito `_bacheca/2026-11-17-bancollm-tiny-voca-italiano.md`. Una cartella per voce sotto
``dati/tts/2026-11-17-tiny-voca/completo/``, con la stessa forma del pilota, così ``genera`` e ``filtra`` di
``tinyvoca_it`` funzionano uguali:

- ``I1`` (femminile, la voce del pilota): le clip del pilota restano (collegamenti all'audio), più frasi nuove;
- ``I2`` (maschile): tutto nuovo, con la candidata scelta dall'utente in ``I2/voce/voce.json``.

Il testo letto da qwen-tts è ``g2p_it.normalizza`` della frase scritta (in ``text_cifre`` quella con le cifre):
numeri, ore, date, importi, unità e sigle arrivano già in parole, e le etichette del G2P sono le stesse parole.

    python -m bancollm.voce.tinyvoca_tappa3 testi
    python -m bancollm.voce.tinyvoca_it genera --cartella dati/tts/2026-11-17-tiny-voca/completo/I1 --ore 9
"""

import argparse
import json
import os
import random
import shutil
from pathlib import Path

from . import tinyvoca_it as P
from .g2p_it import g2p_it as G2P

COMPLETO = P.RADICE / "dati" / "tts" / "2026-11-17-tiny-voca" / "completo"
SEME = 20261118

SIGLE = ["IVA", "INPS", "PDF", "USB", "GPS", "ASL", "SMS", "RAI", "ONU", "UE", "TV", "DNA", "CAP", "IMU", "PIN"]
UNITA = [("km", 1, 400), ("cm", 1, 250), ("kg", 1, 90), ("m", 1, 900), ("l", 1, 60), ("mm", 1, 120),
         ("m²", 10, 400), ("°C", -10, 38), ("km/h", 10, 130), ("kWh", 50, 4000), ("min", 2, 55), ("h", 2, 72)]
TITOLI = ["Sig.", "Sig.ra", "Dott.", "Dott.ssa", "Prof.", "Prof.ssa", "Ing.", "Avv.", "Arch."]


def _modelli_nuovi(rng, quante):
    """Le forme che il G2P ora sa leggere e il pilota non aveva: sigle, unità, ordinali, date con le barre,
    numeri lunghi, telefoni, abbreviazioni, ore col punto."""
    persona = lambda: f"{rng.choice(P.NOMI)} {rng.choice(P.COGNOMI)}"
    luogo = lambda: rng.choice(P.LUOGHI)

    def unita():
        s, a, b = rng.choice(UNITA)
        n = rng.randint(a, b)
        if rng.random() < 0.3 and s not in ("min", "h"):
            return f"{n},{rng.randint(1, 9)} {s}"
        return f"{n} {s}"

    def lungo():
        return f"{rng.randint(1, 999_999_999):,}".replace(",", ".")

    schemi = [
        ("sigle", lambda: f"Per la pratica servono il codice {rng.choice(['IBAN', 'CAP', 'PIN'])} e la ricevuta in {rng.choice(['PDF', 'formato PDF'])}."),
        ("sigle", lambda: f"Ho chiamato l'{rng.choice(['INPS', 'ASL', 'ULSS'])} e mi hanno mandato un SMS."),
        ("sigle", lambda: f"Il prezzo è di {rng.randint(2, 900)} euro più IVA, consegna con la chiavetta USB."),
        ("sigle", lambda: f"Stasera alla TV c'è un servizio sulla {rng.choice(['RAI', 'UE', 'ONU'])}."),
        ("unita", lambda: f"Da qui a {luogo()} sono {unita()}, ma con il traffico ci vuole di più."),
        ("unita", lambda: f"Il pacco pesa {rng.randint(2, 40)} kg e misura {rng.randint(20, 120)} cm di lato."),
        ("unita", lambda: f"Stamattina c'erano {rng.randint(-8, 12)} °C e alle 15:00 siamo arrivati a {rng.randint(10, 34)},{rng.randint(1, 9)} °C."),
        ("unita", lambda: f"La bolletta segna {rng.randint(80, 3500)} kWh in {rng.randint(2, 12)} mesi."),
        ("unita", lambda: f"Il limite su quella strada è di {rng.choice([30, 50, 70, 90, 110, 130])} km/h."),
        ("unita", lambda: f"L'appartamento ha {rng.randint(40, 180)} m² e un giardino di {rng.randint(50, 900)} m²."),
        ("ordinali", lambda: f"È arrivato {rng.randint(2, 40)}° nella gara di {luogo()}, la {rng.randint(2, 9)}ª volta che partecipa."),
        ("ordinali", lambda: f"La festa è il 1° {rng.choice(P.MESI)}, al {rng.randint(2, 6)}° piano del municipio."),
        ("date", lambda: f"La scadenza è il {rng.randint(1, 28)}/{rng.randint(1, 12):02d}/{rng.randint(2024, 2031)}, non oltre."),
        ("date", lambda: f"Nato a {luogo()} il {rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(1940, 2015)}."),
        ("numeri", lambda: f"Il bilancio prevede {lungo()} euro di entrate e {lungo()} di uscite."),
        ("numeri", lambda: f"La regione conta {lungo()} abitanti e {rng.randint(100, 900)} comuni."),
        ("numeri", lambda: f"Il contratto vale {lungo()},{rng.randint(0, 99):02d} euro."),
        ("numeri", lambda: f"La quota è salita dello {rng.randint(0, 9)},{rng.randint(1, 9)}% e poi scesa del {rng.randint(1, 30)}%."),
        ("numeri", lambda: f"Il codice cliente è 0{rng.randint(1000, 99999)}, il numero di telefono 0{rng.randint(400, 499)} {rng.randint(100000, 999999)}."),
        ("titoli", lambda: f"La {rng.choice(['Sig.ra', 'Dott.ssa', 'Prof.ssa'])} {rng.choice(P.COGNOMI)} riceve il martedì alle {rng.randint(8, 18)}.{rng.choice(['00', '15', '30', '45'])}."),
        ("titoli", lambda: f"Il {rng.choice(['Sig.', 'Dott.', 'Prof.', 'Ing.', 'Avv.'])} {rng.choice(P.COGNOMI)} ha firmato, ecc."),
        ("ore", lambda: f"Il negozio è aperto dalle {rng.randint(7, 10)}.{rng.choice(['00', '30'])} alle {rng.randint(12, 20)}.{rng.choice(['00', '30'])}."),
        ("ore", lambda: f"La riunione inizia alle {rng.randint(8, 19)}:{rng.choice(['05', '10', '20', '25', '35', '40', '50', '55'])} in sala {rng.randint(1, 9)}."),
        ("importi", lambda: f"Costa € {rng.randint(1, 999)},{rng.randint(0, 99):02d} in negozio e {rng.randint(1, 999)} € online."),
        ("nomi", lambda: f"{persona()} e {persona()} lavorano {P._a(luogo())} dal {rng.randint(1975, 2024)}."),
    ]
    visti, out = set(), []
    while len(out) < quante:
        cat, f = rng.choice(schemi)
        t = f()
        if t not in visti:
            visti.add(t)
            out.append((cat, t))
    return out


def _riga(prefisso, n, testo_scritto, split, cat, origine, licenza, url, voce):
    letto = G2P.normalizza(testo_scritto)
    r = {"id": f"{prefisso}{n:05d}", "text": letto, "split": split, "category": cat, "origin": origine,
         "source_license": licenza, "source_url": url, "voice_id": voce}
    if letto != testo_scritto:
        r["text_cifre"] = testo_scritto
    return r


def testi(frasi_i1=7400, frasi_i2=10100, quota_modelli=0.16):
    """Frasi nuove per le due voci, senza ripetere quelle del pilota; validazione e prova solo per I2 (I1 tiene
    quelle del pilota). Le clip del pilota entrano in I1 come collegamenti."""
    rng = random.Random(SEME)
    pilota = P.CARTELLA
    righe_pilota = [json.loads(l) for l in (pilota / "testi.jsonl").read_text(encoding="utf-8").splitlines()]
    gia = {r.get("text_cifre", r["text"]) for r in righe_pilota}
    commit = (P.TESTI_CV / "COMMIT").read_text().strip()
    url_cv = P.CV_URL.format(commit=commit)
    cv = {nome: [t for t in frasi if t not in gia] for nome, frasi in P._frasi_cv(rng).items()}
    serve = frasi_i1 + frasi_i2 + 80
    n_mod = int(serve * quota_modelli)
    modelli = P._modelli(rng, n_mod // 2) + _modelli_nuovi(rng, n_mod - n_mod // 2)
    modelli = [(c, t) for c, t in modelli if t not in gia]
    resto = serve - len(modelli)
    disp = {k: len(v) for k, v in cv.items()}
    quote = {"frasi.txt": min(disp["frasi.txt"], int(resto * 0.40)),
             "sentence-collector.txt": min(disp["sentence-collector.txt"], int(resto * 0.12))}
    quote["wiki.it.rerun-2021-10.txt"] = min(disp["wiki.it.rerun-2021-10.txt"], resto - sum(quote.values()))
    tutte = [(c, t, "bancollm_modelli", "project-own", "") for c, t in modelli]
    for nome, q in quote.items():
        cat = "conversazione" if nome == "frasi.txt" else "lettura"
        tutte += [(cat, t, P.CV_FILE[nome], "cc0-1.0", url_cv) for t in cv[nome][:q]]
    rng.shuffle(tutte)
    # I2: validazione e prova (metà conversazione, metà modelli), poi addestramento; I1: solo addestramento.
    conv = [x for x in tutte if x[0] == "conversazione"]
    mod = [x for x in tutte if x[2] == "bancollm_modelli"]
    fisse = conv[:40] + mod[:40]
    resto = [x for x in tutte if x not in set(fisse)]
    i2, n = [], 0
    for split, blocco in (("validation", fisse[:20] + fisse[40:60]), ("test", fisse[20:40] + fisse[60:80])):
        for cat, t, o, l, u in blocco:
            i2.append(_riga("m", n, t, split, cat, o, l, u, "I2")); n += 1
    for cat, t, o, l, u in resto[:frasi_i2]:
        i2.append(_riga("m", n, t, "train", cat, o, l, u, "I2")); n += 1
    i1 = [dict(r, voice_id="I1") for r in righe_pilota]
    for k, (cat, t, o, l, u) in enumerate(resto[frasi_i2:frasi_i2 + frasi_i1]):
        i1.append(_riga("f", k, t, "train", cat, o, l, u, "I1"))
    for voce, righe in (("I1", i1), ("I2", i2)):
        d = COMPLETO / voce
        d.mkdir(parents=True, exist_ok=True)
        (d / "testi.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in righe), encoding="utf-8")
    _collega_pilota()
    return i1, i2


def _collega_pilota():
    """I1 riusa la voce, l'audio e le trascrizioni già fatte del pilota."""
    d = COMPLETO / "I1"
    (d / "audio").mkdir(parents=True, exist_ok=True)
    if not (d / "voce").exists():
        shutil.copytree(P.CARTELLA / "voce", d / "voce")
    for wav in (P.CARTELLA / "audio").glob("*.wav"):
        dest = d / "audio" / wav.name
        if not dest.exists():
            os.symlink(wav, dest)
    cache = P.CARTELLA / "trascrizioni.json"
    if cache.exists() and not (d / "trascrizioni.json").exists():
        shutil.copy(cache, d / "trascrizioni.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("passo", choices=["testi"])
    a = ap.parse_args()
    i1, i2 = testi()
    for voce, righe in (("I1", i1), ("I2", i2)):
        conta = {}
        for r in righe:
            conta[r["split"]] = conta.get(r["split"], 0) + 1
        print(voce, conta, "modelli", sum(r["origin"] == "bancollm_modelli" for r in righe))


if __name__ == "__main__":
    main()
