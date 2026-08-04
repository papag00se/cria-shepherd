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


# Assist families and their icons: 🧭 steers (a directive/redirect cria injected), 🔁 repetition
# breaks (same-call loops interrupted), 🧪 gates (the repo's own checks run on the coder's behalf),
# 🗜️ context work (self-compaction / window flooring). `*_result` keys are the same event's
# read-back and would double-count.
ASSIST_FAMILIES = (
    ("🧭", "steers", lambda k: "steer" in k or k == "loop.redirect"),
    ("🔁", "loops broken", lambda k: "repetition" in k or "wheel_spinning" in k),
    ("🧪", "check runs", lambda k: ("gate" in k or "probe" in k) and not k.endswith("_result")),
    ("🗜️", "context work", lambda k: "compact" in k or "floor" in k),
)


def assist_counts(a: dict) -> dict:
    out = {}
    for icon, _label, match in ASSIST_FAMILIES:
        out[icon] = sum(v for k, v in a.items() if match(k))
    return out


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
        "assists": assist_counts(a),
        "steers": sum(v for k, v in a.items() if "steer" in k or "redirect" in k),
        "gates": sum(v for k, v in a.items()
                     if ("gate" in k or "probe" in k) and not k.endswith("_result")),
        "terminal": r.get("terminal", ""),
        "run_id": r.get("run_id", ""),
    }


# Score glyphs: fractions of 4 everywhere (⁰⁄₄ and ⁴⁄₄ composed — unicode only mints ¼ ½ ¾).
_GLYPH = {0: "⁰⁄₄", 1: "¼", 2: "½", 3: "¾", 4: "⁴⁄₄"}


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
        assists = []
        for icon, _label, _match in ASSIST_FAMILIES:
            mean = sum(s["assists"][icon] for s in last3) / len(last3)
            if round(mean):
                assists.append(f"{icon} {round(mean)}")
        out.append({
            "model": m,
            "_avg": avg,
            "badge": _badge(avg),
            "trend": " ".join(_GLYPH[n] for n in scores),
            "tok_s": round(sum(s["tok_s"] for s in last3) / len(last3), 1),
            "assists": " · ".join(assists) or "—",
            "min": round(sum(s["min"] for s in last3) / len(last3)),
        })
    return sorted(out, key=lambda s: s["_avg"], reverse=True)


def main() -> int:
    md = "--md" in sys.argv
    lines = [stat_line(r) for r in rows()]
    models = model_summary(lines)
    legend = " · ".join(f"{icon} {label}" for icon, label, _m in ASSIST_FAMILIES)
    if md:
        print("### Model performance (each model's last 3 runs, any state)")
        print()
        print("| model | last 3 | avg tok/s | avg assists | avg min |")
        print("|---|---|---:|---|---:|")
        for s in models:
            print(f"| {s['badge']} {s['model']} | {s['trend']} | {s['tok_s']} | "
                  f"{s['assists']} | {s['min']} |")
        print()
        print(f"assists per run: {legend}")
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
        print(f"{'':<3}{'model':<17}{'last 3':<12}{'tok/s':>6} {'min':>4}  assists")
        for s in models:
            print(f"{s['badge']:<3}{s['model']:<17}{s['trend']:<12}"
                  f"{s['tok_s']:>6} {s['min']:>4}  {s['assists']}")
        print(f"\nassists per run: {legend}")
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
