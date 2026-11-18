#!/usr/bin/env bash
# Addestramento notturno del pilota italiano di tiny-voca (compito _bacheca/2026-11-17-bancollm-tiny-voca-italiano.md).
#
# Gira fuori da QBert, quindi solo a GPU libera e mai in parallelo agli altri servizi:
# - parte dopo INIZIO e si ferma prima di FINE (file di scadenza di tiny-voca-train);
# - ogni 30 s guarda la coda di QBert: se arriva un lavoro GPU crea il file di stop, l'addestramento
#   salva al passo e esce, e si riprende (--resume) quando la coda è di nuovo vuota;
# - prima di ogni ripresa vuole anche almeno LIBERA_MIB di VRAM libera.
#
#   nohup notte/tiny-voca-pilota.sh > dati/tts/2026-11-17-tiny-voca/pilota/notte.log 2>&1 &
set -u
INIZIO=${INIZIO:-"23:30"}
FINE=${FINE:-"07:00"}
PASSI=${PASSI:-30000}
LIBERA_MIB=${LIBERA_MIB:-8000}

C=/home/hal5000/claude_sandbox/bancollm/dati/tts/2026-11-17-tiny-voca/pilota
OUT=$C/modello
STOP=$C/stop-addestramento
SCADENZA=$C/scadenza.json
PY=$HOME/Modelli/runtime/tiny-voca/.venv/bin
export TINY_VOCA_LINGUA=it

log() { echo "$(date '+%F %T') $*"; }

# QBert libero: nessun lavoro GPU in corso né in coda.
qbert_libero() {
    curl -s --max-time 5 http://127.0.0.1:1999/queue/status | python3 -c '
import json, sys
d = json.load(sys.stdin)
occupato = d["current"]["gpu"] is not None or any(q["count"] for q in d["queues"]["gpu"].values())
sys.exit(1 if occupato else 0)'
}
vram_libera() { nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1; }

inizio=$(date -d "$INIZIO" +%s)   # oggi; se è già passato (lanciato dopo mezzanotte) parte subito
fine=$(date -d "$FINE" +%s); [ "$fine" -le "$(date +%s)" ] && fine=$(date -d "tomorrow $FINE" +%s)
echo "{\"deadline\": $fine}" > "$SCADENZA"
log "attendo le $INIZIO; scadenza $(date -d @"$fine" '+%F %T'), $PASSI passi"
while [ "$(date +%s)" -lt "$inizio" ]; do sleep 60; done

while [ "$(date +%s)" -lt "$((fine - 600))" ]; do
    passo=$(python3 -c "import json;print(json.loads(open('$OUT/metrics.jsonl').readlines()[-1]).get('step',0))" 2>/dev/null || echo 0)
    if [ -f "$OUT/inference.pt" ] && [ "$passo" -ge "$PASSI" ]; then log "fatto: passo $passo"; break; fi
    if ! qbert_libero || [ "$(vram_libera)" -lt "$LIBERA_MIB" ]; then
        log "GPU occupata (coda QBert o VRAM libera $(vram_libera) MiB), aspetto"; sleep 120; continue
    fi
    rm -f "$STOP"
    ripresa=(); [ -f "$OUT/last.pt" ] && ripresa=(--resume "$OUT/last.pt")
    log "avvio (passo $passo) ${ripresa[*]}"
    "$PY/tiny-voca-train" --train "$C/ann/train.jsonl" --validation "$C/ann/validation.jsonl" --output "$OUT" \
        --config "$HOME/Modelli/tiny-voca/it/config.json" --device cuda --steps "$PASSI" \
        --max-seconds 3600 --deadline-file "$SCADENZA" --stop-file "$STOP" "${ripresa[@]}" &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        sleep 30
        if ! qbert_libero && [ ! -f "$STOP" ]; then log "lavoro GPU in QBert: fermo l'addestramento"; touch "$STOP"; fi
    done
    wait "$pid"; log "uscito con codice $?"
done
rm -f "$STOP"
log "fine della notte"
