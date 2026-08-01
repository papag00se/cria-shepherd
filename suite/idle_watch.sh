#!/bin/bash
# Shout when the ladder is IDLE — work remains and nothing is running.
#
# The goal's Stop hook blocks stopping; it does not make anything happen. Twice the ladder sat
# still for many minutes while questions were answered, because answering a question ends a turn
# legitimately and the hook has nothing to object to. Idle GPU is invisible unless something says
# so. This says so.
#
# Exit 1 from the oracle = work remains. No suite/run.py in the process table = nothing running.
# Both true at once is the state that must never last.
cd /home/jesse/src/cria-shepherd || exit 1
while true; do
  python3 suite/ladder_status.py >/dev/null 2>&1; code=$?
  running=$(ps -eo args | awk '$2 ~ /suite\/run\.py$/' | head -1)
  if [ "$code" = "1" ] && [ -z "$running" ]; then
    echo "IDLE — ladder has work remaining and NO run is in flight: $(python3 suite/ladder_status.py 2>/dev/null | tail -2 | head -1)"
  fi
  sleep 120
done
