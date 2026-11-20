"""Vocina per il web: la cartella da servire (index.html, JS, wasm, modello), a file separati.

    python vocina.py MODELLO.onnx USCITA/ [--pilota] [--fp32] [--stato "nota sul modello"]
    (in bancollm: python -m bancollm.voce.web.vocina …)

Accanto a MODELLO.onnx serve MODELLO.json (scritto da ``tiny_voca.export``). Il modello va in int8
dinamico (quantizza.py, serve onnxruntime), salvo --fp32, che lo copia così com'è.

onnxruntime-web (MIT) si prende da ``ORT_WEB`` se c'è la variabile, altrimenti da ``node_modules`` accanto
a questo file (``npm install`` nella cartella), altrimenti dalla copia già sulla macchina dello studio.

Tutto con percorsi relativi e nessun CDN, per essere servito da una sottocartella di un sito
(https://www.officinepixel.com/vocina/). Il browser mette in cache modello e wasm.

Lo stesso file gira in bancollm e nel repo di Vocina: i percorsi sono relativi a questo file, e la
disposizione delle cartelle è la stessa (``web/`` accanto a ``g2p_it/``).
"""

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

QUI = Path(__file__).resolve().parent
G2P = QUI.parent / "g2p_it"
SORGENTE = QUI / "vocina"


def _ort_web() -> Path:
    candidati = [Path(os.environ["ORT_WEB"])] if os.environ.get("ORT_WEB") else []
    candidati += [QUI / "node_modules" / "onnxruntime-web" / "dist",
                  Path.home() / "claude_sandbox" / "floanna" / "client" / "node_modules" / "onnxruntime-web" / "dist"]
    for c in candidati:
        if (c / "ort.wasm.bundle.min.mjs").exists():
            return c
    return candidati[0]


ORT_WEB = _ort_web()
# Python con onnxruntime per la quantizzazione: questo, se ce l'ha, altrimenti l'ambiente di tiny-voca.
VENV = Path.home() / "Modelli" / "runtime" / "tiny-voca" / ".venv" / "bin" / "python"

ESEMPI = {
    "Treno e importi": "Buongiorno! Il treno per Bassano del Grappa parte alle 14:35 dal binario 3. La Sig.ra Rossi ha "
                       "pagato 1.203,59 € con l'IVA: è scesa a Vicenza il 12/03/2025, con 13,2 °C e l'82% di umidità.",
    "Racconto": "Quella mattina la nebbia copriva i campi fino all'argine del Brenta. Giulia uscì presto, con la bicicletta "
                "e un thermos di caffè, e si fermò sul ponte a guardare l'acqua. Non si sentiva un rumore, solo le campane "
                "lontane di Cittadella. «Che pace», pensò. Poi il telefono vibrò: era Marco, che chiedeva se a pranzo "
                "c'erano anche i ragazzi.",
    "Numeri lunghi": "Il comune ha speso 123.456.789 euro in dieci anni. Vicenza ha 110.923 abitanti, Padova 206.496; "
                     "il contratto vale 250.300.017,80 euro.",
    "Domande": "Hai già sentito Nicola per l'assemblea di giovedì? Quanto costa un chilo di ciliegie di Marostica? "
               "Dodici euro e cinquanta! Che bella sorpresa.",
}

STATO = {
    True: "Questa è la versione di prova: un modello addestrato su 2,6 ore di parlato, con una sola voce. "
          "La versione completa, con due voci e più dati, è in addestramento.",
    False: "Il modello è addestrato su circa 18 ore di parlato, con due voci.",
}


def _python_con_onnxruntime() -> str:
    return sys.executable if importlib.util.find_spec("onnxruntime") else str(VENV)


def costruisci(modello: Path, uscita: Path, pilota: bool, int8: bool = True, stato: str | None = None) -> int:
    if uscita.exists():
        shutil.rmtree(uscita)
    (uscita / "ort").mkdir(parents=True)
    metadati = json.loads(modello.with_suffix(".json").read_text(encoding="utf-8"))
    if int8:  # vedi quantizza.py: 21,4 → 8,5 MB, all'ascolto indistinguibile
        with tempfile.TemporaryDirectory() as d:
            q = Path(d) / "model.onnx"
            subprocess.run([_python_con_onnxruntime(), str(QUI / "quantizza.py"), str(modello), str(q)], check=True,
                           capture_output=True)
            byte_modello = q.read_bytes()
    else:
        byte_modello = modello.read_bytes()
    versione = hashlib.sha256(byte_modello).hexdigest()[:12]
    (uscita / "model.onnx").write_bytes(byte_modello)
    (uscita / "model.json").write_text(json.dumps(
        {k: metadati[k] for k in ("sample_rate", "voices", "symbols", "max_tokens", "step")}, ensure_ascii=False), encoding="utf-8")
    shutil.copy(ORT_WEB / "ort.wasm.bundle.min.mjs", uscita / "ort" / "ort.wasm.bundle.min.js")  # .js: tipo MIME giusto ovunque
    # nginx del sito non comprime i .wasm: lo si consegna già compresso, e la pagina lo scompatta
    byte_wasm = (ORT_WEB / "ort-wasm-simd-threaded.wasm").read_bytes()
    (uscita / "ort" / "ort-wasm-simd-threaded.wasm.gz").write_bytes(gzip.compress(byte_wasm, 9, mtime=0))
    shutil.copy(G2P / "g2p_it.js", uscita / "g2p_it.js")
    shutil.copy(G2P / "dati.json", uscita / "dati.json")
    shutil.copy(G2P / "lessico_wikizionario.json", uscita / "lessico_wikizionario.json")  # CC BY-SA 4.0
    shutil.copy(QUI / "tinyvoca_web.js", uscita / "tinyvoca_web.js")
    for nome in ("LICENSE", "NOTICE", "LICENSE-onnxruntime-web", "vocina.css"):
        shutil.copy(SORGENTE / nome, uscita / nome)
    sost = {"{{MB}}": f"{len(byte_modello) / 1e6:.1f}".replace(".", ","), "{{STATO_MODELLO}}": stato or STATO[pilota],
            "{{ESEMPI}}": json.dumps(ESEMPI, ensure_ascii=False), "{{VERSIONE}}": versione,
            "{{VERSIONE_ORT}}": hashlib.sha256(byte_wasm).hexdigest()[:12]}
    for nome in ("index.html", "app.js"):
        t = (SORGENTE / nome).read_text(encoding="utf-8")
        for k, v in sost.items():
            t = t.replace(k, v)
        (uscita / nome).write_text(t, encoding="utf-8")
    _versiona(uscita)
    return sum(f.stat().st_size for f in uscita.rglob("*") if f.is_file())


def _versiona(uscita: Path) -> None:
    """Il server del sito fa tenere i file in cache due giorni: ogni riferimento interno porta ?v=<impronta
    della consegna>, così dopo una consegna nuova il browser riscarica tutto (tranne index.html, che è piccolo
    e si aggiorna con una ricarica)."""
    h = hashlib.sha256()
    for f in sorted(uscita.rglob("*")):
        if f.is_file():
            h.update(f.name.encode()); h.update(f.read_bytes())
    v = "?v=" + h.hexdigest()[:10]
    sost = {
        "index.html": [('href="vocina.css"', f'href="vocina.css{v}"'), ('src="app.js"', f'src="app.js{v}"')],
        "app.js": [('"./ort/ort.wasm.bundle.min.js"', f'"./ort/ort.wasm.bundle.min.js{v}"'),
                   ('"./tinyvoca_web.js"', f'"./tinyvoca_web.js{v}"'),
                   ('fetch("dati.json")', f'fetch("dati.json{v}")'), ('fetch("model.json")', f'fetch("model.json{v}")'),
                   ('fetch("lessico_wikizionario.json")', f'fetch("lessico_wikizionario.json{v}")')],
        "tinyvoca_web.js": [('"./g2p_it.js"', f'"./g2p_it.js{v}"')],
    }
    for nome, coppie in sost.items():
        f = uscita / nome
        t = f.read_text(encoding="utf-8")
        for a, b in coppie:
            if a not in t:
                raise RuntimeError(f"{nome}: non trovo {a}")
            t = t.replace(a, b)
        f.write_text(t, encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("modello", type=Path)
    p.add_argument("uscita", type=Path)
    p.add_argument("--pilota", action="store_true", help="la nota dice che è il modello di prova a una voce")
    p.add_argument("--fp32", action="store_true", help="il modello così com'è, senza int8")
    p.add_argument("--stato", help="la nota sul modello, al posto di quella predefinita (per un checkpoint intermedio)")
    a = p.parse_args()
    print(a.uscita, f"{costruisci(a.modello, a.uscita, a.pilota, not a.fp32, a.stato) / 1e6:.1f} MB")
