#!/usr/bin/env python3
"""Replay captured runs through cria's DETERMINISTIC logic — no model calls, no GPU.

Every guard shipped this cycle has two halves: a deterministic part that decides WHEN it speaks, and
(sometimes) a model call that decides WHAT it says. The deterministic half is the part that can be
wrong in a way nobody notices, and it can be settled entirely from `~/.cria/calls` — the exact bytes
cria sent, already on disk.

That matters because the alternative is a 15-to-60-minute GPU run per question, and because two of
this cycle's fixes shipped without anyone checking they would ever fire. One did not (the
checks-reattach path never triggered in the run it was built for); one fired in 85% of prompts and
changed the failure mode rather than the outcome. Both facts were available offline.

    python3 suite/replay_logic.py                 # every check, every captured run
    python3 suite/replay_logic.py --check oscillation
    python3 suite/replay_logic.py --detail        # per-run rows, not just the base rate

This answers "would it have fired, and how often", never "would it have helped" — that still needs
a real run. Knowing a guard is silent is worth a GPU hour on its own.
"""
import argparse
import json
import pathlib
import re
import sys

SUITE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SUITE.parent))

from cria import execcheck, loop  # noqa: E402

RESULTS = SUITE / "results" / "results.jsonl"
STEER_RE = re.compile(r"⟦ctx:steer⟧|GROUND TRUTH — the repo's own checks fail")
BULLET_RE = re.compile(r"•\s*(.+)")


def runs():
    """(row, capture_dir, workspace) for every recorded run whose evidence still exists."""
    if not RESULTS.exists():
        return []
    out = []
    for line in RESULTS.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        cap = pathlib.Path(str(r.get("capture_dir") or ""))
        ws = pathlib.Path(str(r.get("archive") or "")) / "workspace"
        if cap.is_dir():
            out.append((r, cap, ws if ws.is_dir() else None))
    return out


def _signatures(cap):
    """The gate finding-states a run went through, in order, deduped consecutively."""
    states = []
    for f in sorted(cap.glob("*coder*.prompt.txt")):
        try:
            t = f.read_text(errors="replace")
        except OSError:
            continue
        bullets = BULLET_RE.findall(t)
        if not bullets:
            continue
        sig = tuple(sorted({b.strip()[:70] for b in bullets[-6:]}))
        if not states or states[-1] != sig:
            states.append(sig)
    return states


def check_oscillation(row, cap, ws):
    """Would loop's A-B-A detector have fired? Mirrors its exact condition."""
    prior, fires = [], 0
    for sig in _signatures(cap):
        if sig in prior and prior[-1] != sig:
            fires += 1
        if not prior or prior[-1] != sig:
            prior.append(sig)
            del prior[:-loop.GATE_SIGNATURE_WINDOW]
    return fires, f"{len(set(_signatures(cap)))} distinct finding-states"


def check_reattach(row, cap, ws):
    """How often the reattach fix would ACTUALLY fire — not how big its pool is.

    The first version of this check counted prompts carrying no correction, which is the population,
    not the trigger, and reported 97% for a fix whose real rate is far lower. The trigger is BOTH
    conditions together: the gate's findings are UNCHANGED since the last steer (so the old guard
    would have suppressed), AND the checker's own first line is absent from the request (so nothing
    else is carrying it). Mirrors loop._checks_already_visible exactly.
    """
    fires = 0
    last_steered = None
    for f in sorted(cap.glob("*coder*.prompt.txt")):
        try:
            t = f.read_text(errors="replace")
        except OSError:
            continue
        bullets = BULLET_RE.findall(t)
        if not bullets:
            continue
        checks = "\n".join(b.strip() for b in bullets[-6:])
        if checks == last_steered:                      # the old guard would suppress here
            first = bullets[-len(bullets)].strip().lstrip("•").strip()[:80]
            body_wo_steer = STEER_RE.split(t)[0]        # what the prompt carries APART from the steer
            if first and first not in body_wo_steer:    # ...and nothing else carries the finding
                fires += 1
        last_steered = checks
    return fires, "findings unchanged AND not otherwise visible"


def check_step_reframe(row, cap, ws):
    """How many prompts would have carried the 'it already exists, repair it' note.

    Deterministic on two facts cria already holds: the step names a file that is on disk, and the
    gate is red. Replayed here against the FINAL workspace, so it is an upper bound for a run whose
    files appeared late — stated rather than hidden.
    """
    if ws is None:
        return 0, "no archived workspace"
    fires = 0
    for f in sorted(cap.glob("*coder*.prompt.txt")):
        try:
            t = f.read_text(errors="replace")
        except OSError:
            continue
        m = re.search(r"Do ONLY this step \(\d+ of \d+\), then stop:\s*\n\s*(.+?)\n", t, re.S)
        if not m:
            continue
        if loop.step_artifacts_on_disk(m.group(1), str(ws)) and STEER_RE.search(t):
            fires += 1
    return fires, "step named an existing file while the gate was red"


def check_satisfaction_due(row, cap, ws):
    """How many periodic 'is the task done?' checks were DUE — and how many actually ran.

    The gap is the bug this cycle found: the check existed, was configured, and lived on the wrong
    driver, so a planner-ON run could sit finished for its whole budget.
    """
    drives = len(list(cap.glob("*coder*.response.json")))
    due = sum(1 for n in range(1, drives + 1) if loop.satisfaction_check_due(n, 80, 20))
    ran = len(list(cap.glob("*satisfaction*.response.json")))
    return max(due - ran, 0), f"{due} due, {ran} ran, over {drives} coder turns"


def check_execcheck(row, cap, ws):
    """What the live-execution check would have concluded from the workspace alone."""
    if ws is None:
        return 0, "no archived workspace"
    eps = execcheck.entrypoints(str(ws))
    rc = execcheck.readme_commands(str(ws))
    if not eps:
        return 1, "NO entry point — would report inconclusive"
    if not rc:
        return 1, f"entry point {eps[0]} but README documents no run command"
    return 0, f"corroborated: {eps[0]}"


CHECKS = {
    "oscillation": check_oscillation,
    "reattach": check_reattach,
    "step-reframe": check_step_reframe,
    "satisfaction": check_satisfaction_due,
    "execcheck": check_execcheck,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", choices=sorted(CHECKS), action="append")
    ap.add_argument("--detail", action="store_true")
    args = ap.parse_args()
    wanted = args.check or sorted(CHECKS)

    data = runs()
    print(f"replaying {len(data)} captured runs through cria's deterministic logic "
          f"— no model calls\n")
    for name in wanted:
        fn = CHECKS[name]
        fired = 0
        rows = []
        for row, cap, ws in data:
            try:
                n, why = fn(row, cap, ws)
            except Exception as e:  # noqa: BLE001
                n, why = 0, f"replay error: {type(e).__name__}"
            if n:
                fired += 1
            rows.append((row.get("model", "?"), row.get("score"), n, why))
        pct = 100 * fired / max(len(data), 1)
        print(f"── {name}: would fire on {fired}/{len(data)} runs ({pct:.0f}%)")
        if args.detail:
            for model, score, n, why in rows:
                if n:
                    sc = f"{score:.0f}/4" if score is not None else "—"
                    print(f"     {model:17s} {sc:>5s}  x{n:<3d} {why}")
        print()


if __name__ == "__main__":
    main()
