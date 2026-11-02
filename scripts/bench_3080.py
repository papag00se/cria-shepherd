#!/usr/bin/env python3
"""Re-run the documented RTX3080 llama-bench configs and print old vs new.

Baselines are the numbers recorded in docs/model-settings.md and docs/model-history.md.
The binary, flags and models come from ~/.config/llama-fleet/models.toml.

The live model must not be holding the 3080. Pass --stop-live to stop
llama-*.service for the duration of the run; it is restarted afterward.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

FLEET = Path.home() / ".config/llama-fleet/models.toml"
GPU_3080 = "GPU-393d4998-707c-0ef0-a514-761015477256"

# (model, test kind, prompt/gen tokens, depth, old tok/s, source note)
CASES = [
    ("bonsai2", "pp", 2048, 8192, 1090.0, "model-settings 2026-09-18, PQ2_0 (non-MTP file)"),
    ("bonsai2", "tg", 128, 8192, 58.8, "model-settings 2026-09-18, PQ2_0 (non-MTP file)"),
    ("gemma4_12b", "tg", 64, 8192, 62.0, "model-settings 2026-07-28, pre-QAT file"),
    ("gemma4_12b", "tg", 64, 32768, 57.0, "model-settings 2026-07-28, pre-QAT file"),
    ("gemma4_12b", "tg", 64, 65536, 49.0, "model-settings 2026-07-28, pre-QAT file"),
    ("gemma4_12b", "tg", 64, 131072, 40.0, "model-settings 2026-07-28, pre-QAT file"),
    ("ornith1.5_9b", "tg", 64, 32768, 68.0, "model-history 2026-07-28 sweep (Ornith 1.0)"),
]

BENCH_BIN = {  # llama-bench lives next to llama-server in these runtimes
    "bonsai2": "bonsai-mtp-7dffb158",
}


def bench_path(model: dict, name: str) -> Path:
    rt = BENCH_BIN.get(name)
    if rt:
        return Path.home() / f".local/share/cria/fleet/runtimes/{rt}/bin/llama-bench"
    return Path(model["binary"]).with_name("llama-bench")


def run_case(name: str, model: dict, kind: str, n: int, depth: int, reps: int) -> float | None:
    argv = [
        str(bench_path(model, name)), "-m", model["model_path"],
        "-ngl", "99", "-fa", "1",
        "-ctk", model.get("cache_type_k", "q8_0"), "-ctv", model.get("cache_type_v", "q8_0"),
        "-d", str(depth), "-r", str(reps), "-o", "json",
        "-p", str(n if kind == "pp" else 0), "-n", str(n if kind == "tg" else 0),
    ]
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=GPU_3080,
               LD_LIBRARY_PATH=model.get("lib_dir", ""))
    proc = subprocess.run(argv, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(f"[{name} {kind}{n}@d{depth}] failed:\n{proc.stderr[-800:]}\n")
        return None
    rows = json.loads(proc.stdout)
    return rows[0]["avg_ts"] if rows else None


def live_units() -> list[str]:
    out = subprocess.run(
        ["systemctl", "list-units", "--type=service", "--state=active", "--plain", "--no-legend", "llama-*"],
        capture_output=True, text=True).stdout
    return [line.split()[0] for line in out.splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop-live", action="store_true", help="stop llama-*.service during the run")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--only", help="comma-separated model names")
    args = ap.parse_args()

    fleet = tomllib.loads(FLEET.read_text())["models"]
    only = set(args.only.split(",")) if args.only else None
    units = live_units()
    if units and not args.stop_live:
        sys.exit(f"live units hold the 3080: {units}; rerun with --stop-live")
    for u in units:
        subprocess.run(["sudo", "systemctl", "stop", u], check=True)
    try:
        print(f"{'model':<14} {'test':<16} {'old':>8} {'new':>8} {'delta':>8}  baseline source")
        for name, kind, n, depth, old, src in CASES:
            if only and name not in only:
                continue
            new = run_case(name, fleet[name], kind, n, depth, args.reps)
            test = f"{kind}{n}@d{depth}"
            if new is None:
                print(f"{name:<14} {test:<16} {old:>8.1f} {'FAIL':>8}")
                continue
            print(f"{name:<14} {test:<16} {old:>8.1f} {new:>8.1f} {100*(new/old-1):>+7.1f}%  {src}",
                  flush=True)
    finally:
        for u in units:
            subprocess.run(["sudo", "systemctl", "start", u])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
