#!/usr/bin/env bash
# Where did llama.cpp ACTUALLY put the layers? The default server log hides this.
# Boots the fleet config once under -lv 5, prints the FINAL placement, kills it.
#
#   systemctl stop llama-qwen38
#   ./probe_fit.sh m192 -fitt 192
#   MODEL=ternary-bonsai ./probe_fit.sh base
#
# Expects the 18084 unit STOPPED — it starts its own instance.
set -u
MODEL="${MODEL:-qwen38}"
tag="${1:?usage: probe_fit.sh <tag> [extra llama-server args]}"; shift || true
out="${PROBE_DIR:-${TMPDIR:-/tmp}}/fit_${MODEL}_${tag}.log"

/home/jesse/bin/llama-fleet "$MODEL" -lv 5 "$@" > "$out" 2>&1 &
pid=$!
for _ in $(seq 1 60); do
  grep -q 'listening on\|compute buffer size' "$out" 2>/dev/null && break
  sleep 3
done
sleep 6
kill "$pid" 2>/dev/null
# kill the server by PID, not by a -f pattern: a pattern can match the caller's own shell.
for p in $(pgrep -f 'bin/llama-server'); do kill "$p" 2>/dev/null; done
sleep 4

echo "  log: $out"
python3 - "$out" <<'PY'
import re, sys
from collections import Counter
lines = open(sys.argv[1], errors="replace").read().split("\n")
# A load log holds SEVERAL trial fits. Only the LAST block is the one that ran.
idx = [i for i, l in enumerate(lines) if re.search(r'layer\s+0 assigned to device', l)]
if not idx:
    print("  (no placement lines — did it fail before load?)"); raise SystemExit
a = {}
for l in lines[idx[-1]:]:
    m = re.search(r'layer\s+(\d+) assigned to device (\w+)', l)
    if m: a[int(m.group(1))] = m.group(2)
    if 'model buffer size' in l: break
print("  placement:", ", ".join(f"{d}={n}" for d, n in sorted(Counter(a.values()).items())),
      f"(of {len(a)} entries — index 0 is the input embedding, not a block)")
runs, prev = [], None
for k in sorted(a):
    if prev and prev[0] == a[k] and prev[2] == k - 1: prev[2] = k
    else: prev = [a[k], k, k]; runs.append(prev)
print("  ranges:   ", ", ".join(f"{d} {x}-{y}" for d, x, y in runs))
tail = "\n".join(lines[idx[-1]:])
for pat in ('model buffer size', 'KV buffer size'):
    for l in re.findall(rf'.*{pat}.*', tail)[:5]:
        print("   ", re.sub(r'^[0-9.]+ [A-Z] +', '', l).strip())
for l in re.findall(r'.*out of memory.*|.*failed to allocate.*', tail)[:3]:
    print("   !!", l.strip()[:110])
PY
