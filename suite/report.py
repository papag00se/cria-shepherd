#!/usr/bin/env python3
"""Render suite/results/results.jsonl as a markdown matrix — raw metrics, no composite scores
(report what happened; let the reader weigh axes)."""

import json
import sys
from collections import defaultdict
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results" / "results.jsonl"


def fmt_cell(rows):
    n = len(rows)
    succ = sum(1 for r in rows if r["success"])
    score = sum(r.get("score") or 0 for r in rows) / n
    mins = sum(r["wall_seconds"] for r in rows) / n / 60
    toks = [r["avg_tok_s"] for r in rows if r.get("avg_tok_s")]
    tok = f"{sum(toks)/len(toks):.0f}t/s" if toks else "—"
    assists = sum(sum(r.get("assists", {}).values()) for r in rows) / n
    kills = sum(1 for r in rows if r["terminal"] == "budget-killed")
    extra = f" ⏱{kills}/{n}" if kills else ""
    return f"{succ}/{n} ✓ · {score:.1f}pt · {mins:.0f}m · {tok} · {assists:.0f}a{extra}"


def main() -> None:
    rows = [json.loads(l) for l in RESULTS.read_text().splitlines() if l.strip()]
    if len(sys.argv) > 1:  # optional filter, e.g. `report.py planner=on`
        for f in sys.argv[1:]:
            k, v = f.split("=", 1)
            rows = [r for r in rows if str(r.get(k)) == v]
    cells = defaultdict(list)
    for r in rows:
        cells[(r["model"], f'{r["task"]}/{r["harness"]}/p{r["planner"]}')].append(r)
    cols = sorted({c for _, c in cells})
    models = sorted({m for m, _ in cells})
    print("| model | " + " | ".join(cols) + " |")
    print("|" + "---|" * (len(cols) + 1))
    for m in models:
        line = [fmt_cell(cells[(m, c)]) if (m, c) in cells else "—" for c in cols]
        print(f"| {m} | " + " | ".join(line) + " |")
    print(f"\nlegend: successes/runs · avg score · avg minutes · avg output tok/s · "
          f"avg assist events · ⏱ = budget-killed runs. {len(rows)} runs total.")


if __name__ == "__main__":
    main()
