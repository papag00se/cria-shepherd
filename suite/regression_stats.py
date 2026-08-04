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


# Score glyphs for the model-summary table: unicode fractions of 4, a ring for zero, a check for
# full marks. Purely presentational — the numbers stay in the per-run table.
_GLYPH = {0: "⭕", 1: "¼", 2: "½", 3: "¾", 4: "✅"}


def _badge(avg: float) -> str:
    if avg >= 3.5:
        return "🟢"
    if avg >= 2.5:
        return "🟡"
    if avg >= 1.5:
        return "🟠"
    return "🔴"


def model_summary(lines):
    """Per-model rollup over that model's LAST 3 runs (any state — this is how the model has been
    performing lately, not the campaign scoreboard; regression_status.py owns counted-ness)."""
    order, by_model = [], {}
    for s in lines:
        by_model.setdefault(s["model"], []).append(s)
        if s["model"] not in order:
            order.append(s["model"])
    out = []
    for m in order:
        last3 = by_model[m][-3:]
        scores = [int(s["score"].split("/")[0]) for s in last3]
        avg = sum(scores) / len(scores)
        out.append({
            "model": m,
            "_avg": avg,
            "badge": _badge(avg),
            "trend": " ".join(_GLYPH[n] for n in scores),
            "avg": f"{avg:.1f}/4",
            "best": f"{_GLYPH[max(scores)]} {max(scores)}/4",
            "worst": f"{_GLYPH[min(scores)]} {min(scores)}/4",
            "tok_s": round(sum(s["tok_s"] for s in last3) / len(last3), 1),
            "min": round(sum(s["min"] for s in last3) / len(last3)),
            "coder": round(sum(s["coder"] for s in last3) / len(last3)),
        })
    return sorted(out, key=lambda s: s["_avg"], reverse=True)


def main() -> int:
    md = "--md" in sys.argv
    lines = [stat_line(r) for r in rows()]
    models = model_summary(lines)
    if md:
        print("### Model performance (each model's last 3 runs, any state)")
        print()
        print("| model | last 3 | avg | best | worst | tok/s | avg min | avg coder calls |")
        print("|---|---|---:|---|---|---:|---:|---:|")
        for s in models:
            print(f"| {s['badge']} {s['model']} | {s['trend']} | {s['avg']} | {s['best']} | "
                  f"{s['worst']} | {s['tok_s']} | {s['min']} | {s['coder']} |")
        print()
        print("### Per-run detail")
        print()
        print("| model | state | score | min | calls | coder | tok/s | steers | gates | terminal |")
        print("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
        for s in lines:
            print(f"| {s['model']} | {s['state']} | {s['score']} | {s['min']} | {s['calls']} | "
                  f"{s['coder']} | {s['tok_s']} | {s['steers']} | {s['gates']} | {s['terminal']} |")
    else:
        print("MODEL PERFORMANCE — each model's last 3 runs, any state")
        print(f"{'':<3}{'model':<17}{'last 3':<10}{'avg':<7}{'best':<7}{'worst':<7}"
              f"{'tok/s':>6} {'min':>4} {'coder':>6}")
        for s in models:
            print(f"{s['badge']:<3}{s['model']:<17}{s['trend']:<10}{s['avg']:<7}"
                  f"{s['best'].split()[1]:<7}{s['worst'].split()[1]:<7}"
                  f"{s['tok_s']:>6} {s['min']:>4} {s['coder']:>6}")
        print()
        print("PER-RUN DETAIL")
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
