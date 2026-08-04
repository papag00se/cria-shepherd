#!/usr/bin/env python3
"""Ground truth for the REGRESSION CAMPAIGN: do the models that passed the ladder still pass?

2026-08-03 changed a lot of cria in one day — the spill whole-read handover, the repeat-collapse
note, the noise-judge drop gate, the cria-voice scrub, the field caps, the reading step and its
check, and the plan-off routing that drives a 2-item plan through the real driver. Six of the seven
passing models passed PLANNER-OFF, which is exactly the path those last changes rewired. This
campaign re-runs every previously-passing model three times on current main and reports what still
holds.

Same doctrine as the ladder tool it imports from: the state is entirely on disk, and a goal that
judges its own progress from the assistant's narration inherits whatever the assistant says.

    python3 suite/regression_status.py           # human-readable
    python3 suite/regression_status.py --json    # machine-readable

Exit codes: 0 = campaign complete, 1 = work remains, 2 = a run is in flight.

Campaign rows are the results.jsonl rows whose note starts with REGRESSION1 — written by the --note
the NEXT line prints. The ladder's own rows filter on LADDER, so neither tool counts the other's
runs. A row marked aborted or superseded is evidence, not an attempt, exactly as in the ladder:
after a fix lands for a walked campaign failure, mark that model's FAILED campaign rows
{"superseded": "<why>"} so its three runs are three runs against the code that exists.
"""
import argparse
import json
import sys

from ladder_status import (BLOCKED_ON_TOOLING, LADDER, LANGUAGES, MILESTONE_MINUTES, PARKED,
                           RESULTS, _walk_sections, in_flight)

NOTE_PREFIX = "REGRESSION1"
RUNS_EACH = 3

# The campaign's models: every ladder model not parked and not blocked on tooling — i.e. the seven
# that passed. Derived, not copied, so parking a model in ladder_status is the ONE act that scopes
# both tools.
MODELS = [(name, planner) for name, _p, _a, _k, planner in LADDER
          if name not in PARKED and name not in BLOCKED_ON_TOOLING]


def campaign_rows(task):
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
        if r.get("aborted") or r.get("superseded"):
            continue
        if str(r.get("note", "")).startswith(NOTE_PREFIX) and r.get("task") == task:
            out.append(r)
    return out


def state_for(task):
    sections = _walk_sections()
    running = in_flight()
    by_model = {}
    for r in campaign_rows(task):
        by_model.setdefault(r["model"], []).append(r)

    cells = []
    for name, planner in MODELS:
        rs = sorted(by_model.get(name, []), key=lambda r: r.get("started") or 0)
        scores = [(r.get("score") or 0) for r in rs]
        passes = sum(1 for r in rs if (r.get("score") or 0) >= (r.get("max_score") or 4))
        unwalked = [r for r in rs if (r.get("score") or 0) < (r.get("max_score") or 4)
                    and r["run_id"] not in sections]
        cells.append({
            "model": name, "planner": planner, "runs": len(rs), "scores": scores,
            "passes": passes, "done": len(rs) >= RUNS_EACH and not unwalked,
            "needs_walk": bool(unwalked),
            "next_walk": unwalked[0]["run_id"] if unwalked else None,
            "next_walk_capture": unwalked[0].get("capture_dir") if unwalked else None,
            "running": running == name,
        })
    return cells, running


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--language", default=LANGUAGES[0][0])
    args = ap.parse_args()
    task = dict(LANGUAGES)[args.language]
    cells, running = state_for(task)

    # WALK BEFORE RUN, always — a scored failure already holds its evidence and walking costs no
    # GPU. Then ROUND-ROBIN, fewest campaign runs first, ladder order as the tiebreak: one early
    # look at every model beats three deep looks at one.
    to_walk = [c for c in cells if c["needs_walk"]]
    to_run = sorted((c for c in cells if c["runs"] < RUNS_EACH), key=lambda c: c["runs"])
    complete = not to_walk and not to_run
    action, target = "none", None
    if running:
        action = "wait"
    elif to_walk:
        action, target = "walk", to_walk[0]
    elif to_run:
        action, target = "run", to_run[0]

    if args.json:
        print(json.dumps({"language": args.language, "task": task, "complete": complete,
                          "running": running, "next_action": action, "target": target,
                          "cells": cells}, indent=1))
    else:
        print(f"REGRESSION CAMPAIGN — {args.language} ({task}), {RUNS_EACH} runs per model, "
              f"note prefix {NOTE_PREFIX}\n")
        print(f"{'model':18s} {'plan':5s} {'runs':>4s}  {'scores':16s} verdict")
        print("-" * 72)
        for c in cells:
            sc = " ".join(f"{s:.0f}" for s in c["scores"]) or "—"
            verdict = ("RUNNING" if c["running"] else
                       "needs walk" if c["needs_walk"] else
                       f"stable {c['passes']}/{RUNS_EACH}" if c["done"] and c["passes"] == RUNS_EACH else
                       f"NOT STABLE {c['passes']}/{c['runs']}" if c["done"] else
                       f"{c['runs']}/{RUNS_EACH} run")
            print(f"{c['model']:18s} {c['planner']:5s} {c['runs']:4d}  {sc:16s} {verdict}")
        print()
        if running:
            print(f"IN FLIGHT: {running} — do not start another run, and do not edit cria or its "
                  f"prompts (they load lazily; an edit changes the RUNNING system)")
        elif complete:
            bad = [c["model"] for c in cells if c["passes"] < RUNS_EACH]
            print("CAMPAIGN COMPLETE — all models stable" if not bad else
                  f"CAMPAIGN COMPLETE — NOT STABLE: {', '.join(bad)} (their failures are walked; "
                  f"read those sections in docs/audits/ladder-walk.md)")
        elif action == "walk":
            print(f"NEXT: WALK {target['next_walk']}")
            print(f"  read {target['next_walk_capture']} — EVERY call, start to finish, pairing "
                  f"NNNN-*.prompt.txt with NNNN-*.reasoning.txt")
            print("  A walk is READING, not searching. No grep, no sampling, no counting.")
            print(f"  then write '## {target['next_walk']}' into docs/audits/ladder-walk.md with a "
                  f"'cria fault: yes|none' line")
            print("  a cria fault gets FIXED (docs/principles.md, fail-before test, pytest green, "
                  "commit+push, restart cria.service), then mark this model's FAILED campaign rows "
                  "superseded so its three runs measure the current code")
        else:
            print(f"NEXT: RUN {target['model']} (campaign run {target['runs'] + 1} of {RUNS_EACH})")
            print(f"  python3 suite/run.py --task {task} --model {target['model']} "
                  f"--harness codex --planner {target['planner']} "
                  f"--milestone-minutes {MILESTONE_MINUTES} "
                  f'--note "{NOTE_PREFIX} {args.language} {target["model"]} $(git rev-parse --short HEAD)"')
            print("  then update docs/audits/regression-report.md with the row")

    sys.exit(2 if running else 0 if complete else 1)


if __name__ == "__main__":
    main()
