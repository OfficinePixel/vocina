# Vocina

Una voce sintetica italiana piccolissima: 4,5 milioni di parametri, 8,5 MB in int8, e gira tutta nel
browser, anche senza rete. Il testo non lascia il dispositivo.

*A tiny Italian text-to-speech model (4.5M parameters, 8.5 MB in int8) that runs entirely in the browser
with ONNX Runtime Web. Derived from [tiny-voca](https://github.com/n4ze3m/tiny-voca), with an Italian
phoneme inventory, our own Italian G2P (Python and JavaScript, no eSpeak), new synthetic voices and
weights trained from scratch. Apache 2.0.*

Demo: <https://www.officinepixel.com/vocina/>

## Cosa c'è

| Cartella | Cosa |
|---|---|
| `g2p_it/` | Il convertitore testo → fonemi per l'italiano, in Python (`g2p_it.py`, solo libreria standard) e in JavaScript (`g2p_it.js`), con gli stessi dati (`dati.json`) e i vettori di prova che li tengono uguali. |
| `web/` | Il lettore per il browser (`tinyvoca_web.js`), la pagina di prova (`vocina/`) e lo script che costruisce la cartella da servire (`vocina.py`), con la quantizzazione int8 (`quantizza.py`). |
| `tiny-voca/` | `italiano.patch`: le modifiche a tiny-voca per l'italiano (inventario, frontend con `g2p_it`, voci). |
| `addestramento/` | Gli script con cui abbiamo fatto dati e addestramento. Sono **di riferimento**: chiamano i servizi del nostro studio (Qwen3-TTS e Whisper dietro un gateway) e non girano così come sono altrove. |

I pesi sono nelle [Release](../../releases).

## Il G2P

Tre passi:
1. **Normalizzazione**: numeri fino ai miliardi, ore, date, importi in euro, percentuali, unità di misura,
   ordinali, abbreviazioni e sigle diventano parole («1.203,59 €» → «milleduecentotré euro e
   cinquantanove centesimi»).
2. **Fonemi** con le regole dell'ortografia italiana: c e g dolci e dure, gn, gli, sc, qu, s e z sorde o
   sonore, doppie, n velare.
3. **Accento** e **e/o aperte o chiuse**: dall'accento scritto, da un lessico di circa 760 voci scritto a
   mano, poi da un lessico di circa 15.000 voci ricavato dal Wiktionary (`lessico_wikizionario.json`, CC BY-SA
   4.0), da alcuni omografi decisi dalla parola prima («cerca di impórti» contro «cosa ti impòrti»), dai
   suffissi, e altrimenti sulla penultima.

Il lessico del Wiktionary contiene solo le parole che le regole sbagliano, e si rigenera con
`python g2p_it/crea_lessico_wikizionario.py ita_latn_broad.tsv` dal file italiano di
[WikiPron](https://github.com/CUNY-CL/wikipron). Sulle parole dei nostri testi, pesate per frequenza e
confrontate con il Wiktionary, le e e le o aperte giuste passano dal 69% al 99,9% (`confronta_wikipron.py`).
WikiPron però non riporta gli accenti, e la sillaba tonica si ricava solo dove c'è una ɛ o una ɔ: per le
altre parole l'accento resta quello delle regole (per esempio «ricévere» è ancora letto «ricevére»). Il
lessico va passato al G2P JS in `DATI.wikizionario`; quello Python lo legge da sé se il file c'è.

```python
import sys; sys.path.insert(0, "g2p_it")
import g2p_it
f = g2p_it.fonemi("Il treno parte alle 14:35.")   # {"symbols", "ids", "stress"}
print(g2p_it.leggibile(f))
# <bos> i l <sp> t r ˈe n o <sp> p ˈa r t e <sp> a l l e <sp> k w a t t ˈo r d i tʃ i <sp> e <sp> t r e n t a tʃ ˈi ŋ k w e . <eos>
```

```js
import { creaG2P } from "./g2p_it/g2p_it.js";
const g2p = creaG2P(await (await fetch("g2p_it/dati.json")).json());
console.log(g2p.fonemi("Il treno parte alle 14:35."));
```

Le due versioni devono dare gli stessi token. Dopo ogni modifica:

```bash
python g2p_it/g2p_it.py --vettori     # rigenera g2p_it/vettori.json
node g2p_it/prova_vettori.mjs         # la versione JS li confronta uno per uno
```

## La pagina web

```bash
cd web && npm install                 # onnxruntime-web 1.27.0
pip install onnxruntime               # solo per la quantizzazione int8
python vocina.py MODELLO.onnx uscita/ [--pilota] [--fp32]
```

Accanto a `MODELLO.onnx` serve `MODELLO.json`, come nelle Release. La cartella `uscita/` si serve così com'è
da un qualunque server statico, anche da una sottocartella. Non usa CDN. Il wasm è consegnato già compresso
e la pagina lo scompatta. I riferimenti interni portano `?v=<impronta>`, così una consegna nuova supera la
cache del browser.

Il lettore divide il testo in frasi, e le frasi lunghe in pezzi alle virgole. Suona ogni pezzo appena è
pronto, e ognuno parte solo quando il precedente è davvero finito. Dopo virgole, parentesi e due punti mette
le pause.

## Il modello

- **Pilota** (Release `v0.1-pilota`): una voce femminile, 2,6 ore di parlato, 30 000 passi. Le etichette
  dell'addestramento erano di eSpeak NG, con lo stesso inventario: nel browser lo guida il G2P nostro.
- **Tappa 3** (in addestramento): due voci, femminile e maschile, circa 18 ore, etichette dal G2P nostro. Il
  vocabolario ha 8 simboli riservati in coda, per insegnare più avanti suoni non verbali con un
  affinamento.

Le voci sono **sintetiche**: disegnate a parole con Qwen3-TTS VoiceDesign, non clonate da persone reali. Le
frasi lette vengono da Common Voice italiano (CC0) e da modelli di frase nostri. Ogni clip è stata
ritrascritta con Whisper e scartata se non coincideva col testo.

Quantizzazione: int8 dinamico sui soli MatMul, da 21,4 a 8,5 MB. Sul pilota Whisper ritrascrive giuste
12 frasi su 12, come con l'originale, e all'ascolto non si distingue. In Firefox va a circa 38 volte il
tempo reale.

### Addestrare con il G2P

```bash
git clone https://github.com/n4ze3m/tiny-voca.git && cd tiny-voca
git checkout 7241dfb && git am ../vocina/tiny-voca/italiano.patch
pip install -e .
export TINY_VOCA_LINGUA=it TINY_VOCA_FRONTEND=own TINY_VOCA_VOCI=I1,I2
export PYTHONPATH=$PWD/../vocina/g2p_it
# poi tiny_voca.prepare, annotate, train ed export come nel README di tiny-voca
```

## Limiti

- Accento ed e/o aperte o chiuse: le regole e il lessico coprono le parole comuni, quelle rare possono
  sbagliare. Gli omografi sono pochi e decisi solo dalla parola prima.
- Nomi stranieri e grafie insolite si leggono all'italiana.
- Una frase da sola non supera i 512 token (circa 32 s): il lettore spezza prima.
- Nessuna emozione, nessun suono non verbale (per ora).

## Licenze

Il codice e i pesi sono sotto **Apache 2.0** (`LICENSE`), tranne `g2p_it/lessico_wikizionario.json`, che
viene dal Wiktionary e resta sotto **CC BY-SA 4.0** (contributori del Wiktionary, estratto con WikiPron). Vocina deriva da tiny-voca di n4ze3m (Apache
2.0): le modifiche sono elencate in `NOTICE`. La cartella costruita include ONNX Runtime Web (© Microsoft,
MIT, `web/vocina/LICENSE-onnxruntime-web`). Dati: Common Voice italiano (CC0 1.0), voci generate con
Qwen3-TTS (Apache 2.0). eSpeak NG (GPL-3.0) è servito solo come programma esterno per le etichette del
pilota e non è incluso.
