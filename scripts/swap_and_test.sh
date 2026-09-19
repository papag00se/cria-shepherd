#!/usr/bin/env bash
# Swap the model on :18084 to $1 (a systemd service) and run the live Ada Handles
# harness against it. One model fits on the 3080 at a time, so we stop every llama
# service first, then start the target and wait for it to load.
#
#   scripts/swap_and_test.sh llama-qwopus-q6 qwopus [turns]
set -uo pipefail

SVC="$1"; LABEL="$2"; TURNS="${3:-4}"
# Every installed llama-*.service, discovered live — a hardcoded list goes stale the
# day a model is added, and the stale entry loses the port fight silently.
ALL=$(systemctl list-unit-files 'llama-*.service' --no-legend | awk '{print $1}')

echo "════════════════════════════════════════════════════════════════════════"
echo "  SWAP → $SVC   (label: $LABEL)"
echo "════════════════════════════════════════════════════════════════════════"

echo ">> stopping all llama services on :18084 …"
sudo -n systemctl stop $ALL 2>/dev/null

echo ">> starting $SVC …"
if ! sudo -n systemctl start "$SVC"; then
    echo "!! failed to start $SVC"; sudo -n systemctl status "$SVC" --no-pager | tail -15; exit 1
fi

echo ">> waiting for the model to load on :18084 (up to 120s) …"
ID=""
for i in $(seq 1 120); do
    ID=$(curl -s -m 3 http://127.0.0.1:18084/v1/models 2>/dev/null \
         | python3 -c "import sys,json; print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null)
    if [ -n "$ID" ]; then echo ">> ready after ${i}s — serving: $ID"; break; fi
    sleep 1
done
if [ -z "$ID" ]; then
    echo "!! $SVC did not become ready in 120s"; sudo -n systemctl status "$SVC" --no-pager | tail -20; exit 1
fi

# cria caches the loaded model id for the life of the process, so a swap needs a cria
# restart before its /v1/models (and the codex window sync) reflect the new model.
echo ">> restarting cria.service to pick up $ID …"
sudo -n systemctl restart cria.service
for i in $(seq 1 30); do
    curl -s -m 3 http://127.0.0.1:18085/v1/models 2>/dev/null | grep -q '"id"' && break
    sleep 1
done

cd /home/jesse/src/cria-shepherd
# Keep the isolated Codex config's model + context_window in lockstep with what cria
# serves. Without the real window Codex uses a 272K fallback and never auto-compacts;
# with it Codex compacts before the server's ceiling instead of 400-ing mid-turn.
python3 scripts/sync_codex_model.py || echo "!! codex model sync failed (codex window may be stale)"

python3 scripts/live_model.py --label "$LABEL" --turns "$TURNS"
