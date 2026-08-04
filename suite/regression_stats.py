#!/usr/bin/env python3
"""Per-run stats for the REGRESSION1 campaign — the numbers behind the scoreboard.

`regression_status.py` decides what happens next; this prints how each run actually went:
wall minutes, total/coder calls, decode speed, and how often cria spoke (steers/redirects)
or ran the repo's checks (gates/probes). Reads the same results.jsonl rows, computes nothing
new — every figure is already in the row the runner wrote.

Usage: python3 suite/regression_stats.py [--md]
"""
import json
import sys
from pathlib import Path

RESULTS = Path(__file__).parent / "results" / "results.jsonl"


def rows():
    out = []
    for line in RESULTS.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if str(r.get("note", "")).startswith("REGRESSION1"):
            out.append(r)
    return out


def state(r):
    sup = str(r.get("superseded", ""))
    if not sup:
        return "counted"
    return "voided" if "void" in sup.lower() else "superseded"


def stat_line(r):
    a = r.get("assists", {})
    return {
        "model": r["model"],
        "state": state(r),
        "score": f"{int(r.get('score', 0))}/{int(r.get('max_score', 4))}",
        "min": round(r.get("wall_seconds", 0) / 60),
        "calls": r.get("calls", 0),
        "coder": r.get("phases", {}).get("coder", 0),
        "tok_s": round(r.get("avg_tok_s") or 0, 1),
        "steers": sum(v for k, v in a.items() if "steer" in k or "redirect" in k),
        "gates": sum(v for k, v in a.items() if "gate" in k or "probe" in k),
        "terminal": r.get("terminal", ""),
        "run_id": r.get("run_id", ""),
    }


def main() -> int:
    md = "--md" in sys.argv
    lines = [stat_line(r) for r in rows()]
    if md:
        print("| model | state | score | min | calls | coder | tok/s | steers | gates | terminal |")
        print("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
        for s in lines:
            print(f"| {s['model']} | {s['state']} | {s['score']} | {s['min']} | {s['calls']} | "
                  f"{s['coder']} | {s['tok_s']} | {s['steers']} | {s['gates']} | {s['terminal']} |")
    else:
        print(f"{'model':<17}{'state':<11}{'score':<6}{'min':>4} {'calls':>5} {'coder':>5} "
              f"{'tok/s':>6} {'steers':>6} {'gates':>5}  terminal")
        for s in lines:
            print(f"{s['model']:<17}{s['state']:<11}{s['score']:<6}{s['min']:>4} {s['calls']:>5} "
                  f"{s['coder']:>5} {s['tok_s']:>6} {s['steers']:>6} {s['gates']:>5}  {s['terminal']}")
    counted = [s for s in lines if s["state"] == "counted"]
    if counted:
        print()
        print(f"counted runs: {len(counted)} · avg wall {sum(s['min'] for s in counted)/len(counted):.0f} min "
              f"· avg coder calls {sum(s['coder'] for s in counted)/len(counted):.0f} "
              f"· full-pass rate {sum(1 for s in counted if s['score'] == '4/4')}/{len(counted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
