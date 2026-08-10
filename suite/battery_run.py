#!/usr/bin/env python3
"""Run one battery cell: set the arm, restart cria, run the task, restore the flag.

The arm IS the experiment, so setting it by hand is how a whole phase silently measures the wrong
thing. `[engagement] drive = false` makes cria a plain proxy — no planner, no steers, no gates, no
critics, no completion judging — while keeping the plumbing a local model needs to be reachable at
all. `true` is the full driver. One flag, flipped here, recorded in the run's note, and put back
afterwards so an interrupted campaign cannot leave the live config in the baseline arm.

Usage:  python3 suite/battery_run.py --arm BASE --model gemma4 --task shipping-rates-py
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SUITE = Path(__file__).resolve().parent
TOML = Path("~/.cria/cria.toml").expanduser()

# ONE definition, imported — not restated. Copying it here meant bumping the campaign to BATTERY2
# in the status tool left the runner still stamping BATTERY1, and the first finished run of the new
# matrix was invisible to the scoreboard that is supposed to be the only source of truth.
sys.path.insert(0, str(SUITE))
from battery_status import NOTE_PREFIX  # noqa: E402


def read_drive(text: str) -> str | None:
    m = re.search(r"(?m)^\s*drive\s*=\s*(true|false)", text)
    return m.group(1) if m else None


def set_drive(want: str) -> str | None:
    """Write `[engagement] drive = <want>`; return the previous value for restoration.

    Edits the LIVE config, which is the same file the operator reads, so the write is minimal and
    idempotent: an existing key is rewritten in place, a missing one is inserted under the section
    it belongs to. Nothing else in the file is touched."""
    text = TOML.read_text()
    before = read_drive(text)
    if before is not None:
        text = re.sub(r"(?m)^(\s*drive\s*=\s*)(?:true|false)", rf"\g<1>{want}", text, count=1)
    elif "[engagement]" in text:
        text = text.replace("[engagement]\n", f"[engagement]\ndrive = {want}\n", 1)
    else:
        text += f"\n[engagement]\ndrive = {want}\n"
    TOML.write_text(text)
    return before


def sh(*cmd: str, timeout: int = 120) -> int:
    return subprocess.run(cmd, timeout=timeout).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=("BASE", "CRIA"))
    ap.add_argument("--model", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--milestone-minutes", type=int, default=15)
    args = ap.parse_args()

    if not TOML.exists():
        print(f"no config at {TOML}", file=sys.stderr)
        return 2
    want = "false" if args.arm == "BASE" else "true"
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                         text=True, cwd=SUITE.parent).stdout.strip() or "?"
    before = set_drive(want)
    print(f"[arm] [engagement] drive = {want}  (was {before})")
    try:
        # cria reads its config at startup, so the arm only takes effect after a restart. suite/run.py
        # restarts cria again for the model swap; this one guarantees the flag is live even if the
        # model is already loaded and that restart is a no-op.
        if sh("sudo", "-n", "systemctl", "restart", "cria.service") != 0:
            print("could not restart cria.service", file=sys.stderr)
            return 2
        return sh(sys.executable, str(SUITE / "run.py"), "--task", args.task, "--model", args.model,
                  "--planner", "off", "--milestone-minutes", str(args.milestone_minutes),
                  "--note", f"{NOTE_PREFIX} {args.arm} {args.model} {sha}", timeout=7200)
    finally:
        # Restore, always. An interrupted campaign must not leave the live config in the baseline
        # arm — every later run would silently measure a plain proxy and look like a collapse.
        if before is not None and before != want:
            set_drive(before)
            sh("sudo", "-n", "systemctl", "restart", "cria.service")
            print(f"[arm] restored drive = {before}")


if __name__ == "__main__":
    raise SystemExit(main())
