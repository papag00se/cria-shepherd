#!/usr/bin/env python3
"""Ground truth for the ENGAGEMENT LADDER: what is built, what has run, what has been judged.

The ladder asks one question — what is each layer of cria worth? — by running the same tasks six
times, once per cumulative level, from a pure proxy up to the full driver. Its state lives entirely
on disk: a test file that either passes or does not, rows in `suite/results/results.jsonl`, and
usefulness verdicts in `~/.cria/suite/_usefulness`. Nothing here is read from a conversation. A goal
that judges its own progress from the assistant's narration inherits whatever the assistant says,
and this project has already paid for that twice in one day — a 24-cell campaign reported cell by
cell and never judged, and a judging pass announced three times and performed once.

    python3 suite/engagement_status.py            # human-readable
    python3 suite/engagement_status.py --json     # machine-readable

Exit codes: 0 = LADDER COMPLETE, 1 = work remains.

NOT `suite/ladder_status.py`: that name belongs to the LANGUAGE ladder and is another goal's truth.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SUITE = Path(__file__).resolve().parent
REPO = SUITE.parent
RESULTS = SUITE / "results" / "results.jsonl"
VERDICTS = Path.home() / ".cria" / "suite" / "_usefulness"
LEVEL_TEST = REPO / "tests" / "test_engagement_levels.py"

# The matrix the goal commits to: six cumulative levels over the battery's five models and six tasks.
# Kept here rather than derived from the rows, so a level nobody ran is MISSING rather than invisible.
LEVELS = (0, 1, 2, 3, 4, 5)
LEVEL_NAMES = {
    0: "pure proxy",
    1: "TOOL_CALL_FIXES",
    2: "SIMPLE_TOOLS",
    3: "CONTEXT_FIXES",
    4: "DONE_REFUSALS_ENABLED",
    5: "ASSISTS_ENABLED",
}
# 2026-09-27: nemotron-elastic, qwen35 and qwen38 left the battery (operator decision); K2-Horizon-7B,
# phi-4, Ling-3.0-tiny and Qwen3.8-9B-Distill joined, and defiant-fable entered. The report renders
# only this roster (plus gemma4's frozen row, the only gemma history); retired models are NAMED in
# the report and keep every row in results.jsonl / historical_ladder.json.
# Keys renamed 2026-09-27 (operator): ternary-bonsai-2 -> bonsai2, ornith15 -> ornith1.5,
# qwen38-distill -> qwen3.8_9b_distill, k2-horizon -> k2_horizon_7b. results.jsonl `model`
# fields were migrated with them; run_ids, archives and systemd units keep their names.
MODELS = ("gemma4-qat", "bonsai2", "defiant-fable", "ornith1.5",
          "k2_horizon_7b", "phi4", "ling3-tiny", "qwen3.8_9b_distill")
# CURRENT matrix only — a model here must be swappable and have canonical sampling.
# gemma4 (stock Q4_K_M) and ternary-bonsai (Bonsai 1) left on 2026-09-18 when their weights
# and units were deleted; like nemotron-elastic before them they stay VISIBLE in the reports
# through suite/historical_ladder.json, which is where their scores live. Retiring a model
# means dropping it from here, never deleting its history.
TASKS = ("shipping-rates-rb", "cart-billing-go", "orders-api-py",
         "feed-pipeline-java", "handles-cli-node", "rust-toml-cli")
TOTAL = len(LEVELS) * len(MODELS) * len(TASKS)


def rows() -> list[dict]:
    if not RESULTS.exists():
        return []
    out = []
    for line in RESULTS.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue          # a half-written row is not a reason to report zero progress
    return out


def ladder_rows(rs: list[dict]) -> dict[tuple[int, str, str], dict]:
    """The newest row per (level, model, task). A cell RE-RUN supersedes its earlier attempt; the
    older row stays in the file as evidence and is never counted twice."""
    best: dict[tuple[int, str, str], dict] = {}
    for r in sorted(rs, key=lambda x: x.get("started", 0)):
        lvl = r.get("level")
        # Superseded rows are evidence, not measurements — see ladder_cycle.done().
        if (lvl is None or r.get("superseded")
                or r.get("model") not in MODELS or r.get("task") not in TASKS):
            continue
        try:
            lvl = int(lvl)
        except (TypeError, ValueError):
            continue
        if lvl in LEVELS:
            best[(lvl, r["model"], r["task"])] = r
    return best


def judged(cells: dict) -> dict:
    """A cell is judged when its verdict file exists — the same rule `usefulness.py pending` uses,
    so the two can never disagree about what is left."""
    return {k: r for k, r in cells.items() if (VERDICTS / f"{r.get('run_id', '')}.json").exists()}


def build_state() -> tuple[str, str]:
    """(status, detail) for the level test. Absent is not the same as failing, and both are told
    apart from passing — a missing test file has, before now, been read as 'nothing to run, fine'."""
    if not LEVEL_TEST.exists():
        return "MISSING", f"{LEVEL_TEST.relative_to(REPO)} does not exist"
    proc = subprocess.run([sys.executable, "-m", "pytest", str(LEVEL_TEST), "-q"],
                          cwd=REPO, capture_output=True, text=True)
    if proc.returncode == 0:
        tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
        return "PASS", (tail[-1] if tail else "ok")
    fails = [ln for ln in proc.stdout.splitlines() if ln.startswith("FAILED")]
    return "FAIL", (fails[0] if fails else f"exit {proc.returncode}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rs = rows()
    cells = ladder_rows(rs)
    done = judged(cells)
    status, detail = build_state()
    complete = status == "PASS" and len(cells) == TOTAL and len(done) == TOTAL

    if args.json:
        print(json.dumps({
            "build": status, "build_detail": detail,
            "cells": len(cells), "judged": len(done), "total": TOTAL,
            "complete": complete,
            "per_level": {str(l): {
                "run": sum(1 for (lv, _, _) in cells if lv == l),
                "judged": sum(1 for (lv, _, _) in done if lv == l),
                "of": len(MODELS) * len(TASKS),
            } for l in LEVELS},
        }, indent=2))
        return 0 if complete else 1

    print(f"BUILD    tests/test_engagement_levels.py .......... {status}   {detail}")
    print(f"CELLS    {len(cells)}/{TOTAL} run")
    print(f"JUDGED   {len(done)}/{TOTAL} judged")
    print()
    for l in LEVELS:
        run = sum(1 for (lv, _, _) in cells if lv == l)
        jud = sum(1 for (lv, _, _) in done if lv == l)
        of = len(MODELS) * len(TASKS)
        bar = "#" * jud + "-" * (of - jud)
        print(f"  L{l} {LEVEL_NAMES[l]:<24s} run {run:2d}/{of}  judged {jud:2d}/{of}  [{bar}]")
    print()
    if complete:
        print("LADDER COMPLETE")
        return 0
    if status != "PASS":
        print(f"NEXT     make the level test pass ({status.lower()})")
    elif len(cells) < TOTAL:
        missing = [(l, m, t) for l in LEVELS for m in MODELS for t in TASKS
                   if (l, m, t) not in cells]
        l, m, t = missing[0]
        print(f"NEXT     run {len(missing)} more cell(s); first is L{l} {m} x {t}")
    else:
        left = [k for k in cells if k not in done]
        l, m, t = left[0]
        print(f"NEXT     judge {len(left)} more cell(s); first is L{l} {m} x {t}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
