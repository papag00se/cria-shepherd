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
try:  # importable as suite.battery_run and executable as suite/battery_run.py
    from .battery_status import NOTE_PREFIX  # noqa: E402
    from . import run_guard  # noqa: E402
except ImportError:
    from battery_status import NOTE_PREFIX  # noqa: E402
    import run_guard  # noqa: E402

# Which revision of the TASK PROMPTS a row was earned against. The six prompts were rewritten
# on 2026-08-12 twice: p2 removed idiom and undefined words, and p3 is the operator's own
# rewrite into short numbered imperatives. Three tasks also had their time budgets corrected,
# which moves their wall clock. Rows from different revisions are not the same
# measurement, and the note is where that stays visible instead of being folded silently
# into a delta. BUMP THIS whenever a task's wording changes materially.
#
# p4 (2026-08-13): two prompts named a requirement the task did not state.
#   * handles-cli-node now asks for the RESOLVED address as well as the holder's. api.handle.me
#     returns two different addresses and the checker required both; the prompt named one, so a tool
#     that printed the holder address and the count — exactly what was asked — lost two checks.
#   * feed-pipeline-java no longer lists duplicate SKUs as bad data. Its speed check compares row
#     counts against the seed on a feed of 120,000 rows over 25,000 SKUs, so a model that skipped
#     repeats as instructed could never match and lost the point however fast and correct it was.
PROMPT_REV = "p4"


def read_level(text: str) -> str | None:
    """The live `[engagement] level`, or the legacy `drive` mapped onto the ladder's two ends."""
    m = re.search(r"(?m)^\s*level\s*=\s*(\d+)", text)
    if m:
        return m.group(1)
    m = re.search(r"(?m)^\s*drive\s*=\s*(true|false)", text)
    if m:
        return "5" if m.group(1) == "true" else "0"
    return None


def set_level(want: str) -> str | None:
    """Write `[engagement] level = <want>`; return the previous value for restoration.

    THE LEVEL *IS* THE EXPERIMENT, so setting it by hand is how a whole phase silently measures the
    wrong thing. Edits the LIVE config, which is the same file the operator reads, so the write is
    minimal and idempotent: an existing key is rewritten in place, a missing one is inserted under
    the section it belongs to. Nothing else in the file is touched.

    A legacy `drive = true|false` line is REPLACED rather than left beside a level — two keys for
    one question is how a config comes to disagree with itself, and `_engagement_level` prefers
    `level`, so a stale `drive` would sit there reading as if it still decided something."""
    text = TOML.read_text()
    before = read_level(text)
    text = re.sub(r"(?m)^\s*drive\s*=\s*(?:true|false)\n", "", text)
    if re.search(r"(?m)^\s*level\s*=\s*\d+", text):
        text = re.sub(r"(?m)^(\s*level\s*=\s*)\d+", rf"\g<1>{want}", text, count=1)
    elif "[engagement]" in text:
        text = text.replace("[engagement]\n", f"[engagement]\nlevel = {want}\n", 1)
    else:
        text += f"\n[engagement]\nlevel = {want}\n"
    TOML.write_text(text)
    return before


def sh(*cmd: str, timeout: int | None = 120) -> int:
    return subprocess.run(cmd, timeout=timeout).returncode


def cell_timeout(fresh_l5: bool) -> int | None:
    """Fresh campaign cells may pause indefinitely for independent judgments."""
    return None if fresh_l5 else 7200


def main() -> int:
    ap = argparse.ArgumentParser()
    # --level IS the experiment. --arm survives as the two ends it always named, so the older
    # cycle scripts keep working and mean exactly what they did: BASE = the plain proxy, CRIA = the
    # full driver. It was never a control for anything in between, which is the whole point of the
    # ladder (see cria/config.py RoutingConfig.engagement_level).
    ap.add_argument("--level", type=int, choices=range(0, 6))
    ap.add_argument("--arm", choices=("BASE", "CRIA"))
    ap.add_argument("--model", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--planner", choices=("on", "off"), default="off",
                    help="experimental planner; off unless explicitly requested")
    ap.add_argument("--fresh-l5", action="store_true",
                    help="record one cell in the revision-pinned fresh L5 cohort")
    ap.add_argument("--campaign-revision", default=None,
                    help="immutable full git revision pinned for the fresh L5 cohort")
    ap.add_argument("--milestone-minutes", type=int, choices=[15], default=15,
                    help="fixed 15-minute pacing; the first inference judgment is at minute 30")
    args = ap.parse_args()

    other_runs = run_guard.other_suite_runners()
    if other_runs:
        print("another suite/run.py is active (possibly paused for a judgment); leaving it untouched: "
              + "; ".join(f"pid {pid}" for pid, _ in other_runs), file=sys.stderr)
        return 3
    if not TOML.exists():
        print(f"no config at {TOML}", file=sys.stderr)
        return 2
    if args.level is None and args.arm is None:
        ap.error("one of --level or --arm is required")
    level = args.level if args.level is not None else (0 if args.arm == "BASE" else 5)
    if args.fresh_l5 and (level != 5 or args.planner != "off" or not args.campaign_revision):
        ap.error("--fresh-l5 requires L5, --planner off, and --campaign-revision")
    if args.campaign_revision and any(c.isspace() for c in args.campaign_revision):
        ap.error("--campaign-revision must be one immutable revision token")
    if args.fresh_l5:
        from fresh_l5_campaign import MODELS, TASKS
        if args.model not in MODELS or args.task not in TASKS:
            ap.error("--fresh-l5 model and task must belong to its fixed 9×6 cohort")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=SUITE.parent,
                              capture_output=True, text=True, check=True).stdout.strip()
        if args.campaign_revision != head:
            ap.error(f"fresh L5 revision must equal current HEAD {head}")
    want = str(level)
    tag = f"L{level}"
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                         text=True, cwd=SUITE.parent).stdout.strip() or "?"
    before = set_level(want)
    print(f"[arm] [engagement] level = {want}  (was {before})")
    try:
        # cria reads its config at startup, so the arm only takes effect after a restart. suite/run.py
        # restarts cria again for the model swap; this one guarantees the flag is live even if the
        # model is already loaded and that restart is a no-op.
        if sh("sudo", "-n", "systemctl", "restart", "cria.service") != 0:
            print("could not restart cria.service", file=sys.stderr)
            return 2
        command = [sys.executable, str(SUITE / "run.py"), "--task", args.task, "--model", args.model,
                   "--planner", args.planner, "--milestone-minutes", str(args.milestone_minutes),
                   "--note", f"{NOTE_PREFIX} {tag} {args.model} {sha} {PROMPT_REV}",
                   "--level", str(level)]
        if args.fresh_l5:
            command += ["--fresh-l5", "--campaign-revision", args.campaign_revision]
        return sh(*command, timeout=cell_timeout(args.fresh_l5))
    finally:
        # Restore, always. An interrupted campaign must not leave the live config in the baseline
        # arm — every later run would silently measure a plain proxy and look like a collapse.
        if before is not None and before != want:
            set_level(before)
            sh("sudo", "-n", "systemctl", "restart", "cria.service")
            print(f"[arm] restored level = {before}")


if __name__ == "__main__":
    raise SystemExit(main())
