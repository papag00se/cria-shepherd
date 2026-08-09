#!/usr/bin/env python3
"""Per-run stats for the REGRESSION1 campaign — the numbers behind the scoreboard.

`regression_status.py` decides what happens next; this prints how each run actually went:
wall minutes, total/coder calls, decode speed, and how often cria spoke (steers/redirects)
or ran the repo's checks (gates/probes). Reads the same results.jsonl rows, computes nothing
new — every figure is already in the row the runner wrote.

Usage: python3 suite/regression_stats.py [--md] [--write]
  --md     print the tables as markdown
  --write  regenerate the "## Run stats" section of docs/audits/regression-report.md in place
           (the model-performance grid is the operator's primary view — refresh it after EVERY run)
"""
import json
import re as _re
import sys
from pathlib import Path

RESULTS = Path(__file__).parent / "results" / "results.jsonl"
REPORT = Path(__file__).parent.parent / "docs" / "audits" / "regression-report.md"

SECTION_HEADER = (
    "## Run stats\n\n"
    "Regenerate any time with `python3 suite/regression_stats.py` (`--write` refreshes this\n"
    "section in place). The model-performance grid covers each model's last 3 STANDING runs —\n"
    "voided/superseded rows are cria evidence, not model form — ranked by completion rate, then\n"
    "shortest time, then least assists. Per-run: steers = directives/redirects cria injected;\n"
    "gates = check runs it triggered.\n\n"
)


def rows():
    out = []
    for line in RESULTS.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        # Scope widened 2026-08-05 (operator: report brought current): the campaign closed and
        # the lanes moved on — a grid keyed to the REGRESSION1 note prefix showed nemotron on
        # its retired planner-on lane and omitted gemma4 entirely. The grid is THE
        # operator view, so it now covers every ada-handles row; superseded/voided rows are
        # still excluded downstream by state().
        # RETIRED models never render: fabliq/zaya1 (operator call 2026-08-04) and the gemma4
        # finetune (operator call 2026-08-05, "replace the finetune in all places"). Their rows
        # stay in results.jsonl as evidence; the grid is a living surface.
        if r.get("task") == "ada-handles" and r.get("model") not in ("fabliq", "zaya1", "gemma4-finetune"):
            out.append(r)
    return out


def state(r):
    sup = str(r.get("superseded", ""))
    if not sup:
        return "counted"
    return "voided" if "void" in sup.lower() else "superseded"



# HOW EACH MODEL IS NAMED IN THE GRID: (display name, size + quant), keyed by fleet alias. Grounded
# in the served model names the runs actually logged (⟦cria⟧ coder · <name> lines) and the
# llama-fleet service definitions in suite/run.py — e.g. `maple_preview_20b_a1b_tq2_0` is a 20B
# ternary-quantised MoE with ~1B active.
#
# THE DISPLAY NAME LIVES HERE, not just the spec, because the grid is regenerated in place by
# `--write` and anything hand-edited into the file is destroyed on the next run. The operator
# corrected two of these rows by hand on 2026-08-06 and the very next refresh would have reverted
# them. A generated file cannot be the place a human records a fact; the generator has to hold it.
MODEL_SPECS = {
    "ternary-bonsai":   ("ternary-bonsai", "27B q2_0"),
    "gemma4-finetune":  ("gemma4-finetune", "12B q4km (retired finetune)"),
    "gemma4":           ("gemma4", "12B q4km"),
    "qwen35":           ("qwen3.5", "9B q6"),
    "r1-llama":         ("r1-distill (llama)", "8B q6"),
    "qwythos":          ("qwythos", "9B q6"),
    "qwopus":           ("qwopus", "9B q6"),
    "ornith":           ("ornith", "9B q6"),
    "mellum2":          ("mellum2", "12B-A2.5B q4"),
    "nemotron-elastic": ("nemotron-elastic", "12B-A2B q4km"),
    "maple-preview":    ("maple (ternary)", "20B-A1B q2"),
}


def grid_name(alias: str) -> str:
    """The model's name as the grid prints it. An unknown alias shows its own name and `?` for the
    spec — visible as a gap to fill, never silently wrong."""
    label, spec = MODEL_SPECS.get(alias, (alias, "?"))
    return f"{label} · {spec}"

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


# Score glyphs: EXPLICIT fractions of 4, all composed — the reduced ½ hid a 2/4 from the operator
# ("what about the 2/4 run?"), so every value now reads as x-of-4 with no arithmetic.
_GLYPH = {0: "⁰⁄₄", 1: "¹⁄₄", 2: "²⁄₄", 3: "³⁄₄", 4: "⁴⁄₄"}


def _badge(avg: float) -> str:
    if avg >= 3.5:
        return "🟢"
    if avg >= 2.5:
        return "🟡"
    if avg >= 1.5:
        return "🟠"
    return "🔴"


def model_summary(lines):
    """Per-model rollup over that model's last 3 COUNTED runs. Voided/superseded rows are evidence
    about cria (an operator-thrown-out routing bug, a since-fixed fault), not about the model —
    including them held ornith's voided 0/4 against a model that has never failed on standing
    code (operator, 2026-08-04). A model with no counted runs yet falls back to its last 3 rows
    of any state so it never vanishes from the grid."""
    order, by_model = [], {}
    for s in lines:
        by_model.setdefault(s["model"], []).append(s)
        if s["model"] not in order:
            order.append(s["model"])
    out = []
    for m in order:
        counted = [s for s in by_model[m] if s["state"] == "counted"]
        last3 = (counted or by_model[m])[-3:]
        scores = [int(s["score"].split("/")[0]) for s in last3]
        avg = sum(scores) / len(scores)
        # One column per assist family (the single joined cell could never line up).
        fam = {icon: round(sum(s["assists"][icon] for s in last3) / len(last3))
               for icon, _label, _match in ASSIST_FAMILIES}
        out.append({
            "model": m,
            "_avg": avg,
            "_assists": sum(fam.values()),
            "badge": _badge(avg),
            "trend": " ".join(_GLYPH[n] for n in scores),
            "tok_s": round(sum(s["tok_s"] for s in last3) / len(last3), 1),
            "fam": fam,
            "min": round(sum(s["min"] for s in last3) / len(last3)),
            "calls": round(sum(s["calls"] for s in last3) / len(last3)),
        })
    # Operator's ranking: highest completion rate, then shortest time, then least assists.
    return sorted(out, key=lambda s: (-s["_avg"], s["min"], s["_assists"]))


def markdown(lines, models) -> str:
    legend = " · ".join(f"{icon} {label}" for icon, label, _m in ASSIST_FAMILIES)
    icons = [icon for icon, _l, _m in ASSIST_FAMILIES]
    out = ["### Model performance (each model's last 3 STANDING runs — voided/superseded excluded)", ""]
    out += ["| model | last 3 | avg tok/s | avg min | avg calls | " + " | ".join(icons) + " |",
            "|---|---|---:|---:|---:|" + "---:|" * len(icons)]
    out += [f"| {s['badge']} {grid_name(s['model'])} | {s['trend']} | {s['tok_s']} | {s['min']} | {s['calls']} | "
            + " | ".join(str(s['fam'][i]) for i in icons) + " |"
            for s in models]
    out += ["", f"assists per run: {legend}", "", "### Per-run detail", ""]
    out += ["| model | state | score | min | calls | coder | tok/s | steers | gates | terminal |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    out += [f"| {s['model']} | {s['state']} | {s['score']} | {s['min']} | {s['calls']} | "
            f"{s['coder']} | {s['tok_s']} | {s['steers']} | {s['gates']} | {s['terminal']} |"
            for s in lines]
    counted = [s for s in lines if s["state"] == "counted"]
    if counted:
        out += ["", f"counted runs: {len(counted)} · avg wall "
                    f"{sum(s['min'] for s in counted)/len(counted):.0f} min · avg coder calls "
                    f"{sum(s['coder'] for s in counted)/len(counted):.0f} · full-pass rate "
                    f"{sum(1 for s in counted if s['score'] == '4/4')}/{len(counted)}"]
    return "\n".join(out)


def write_report(lines, models) -> None:
    """Replace the report's '## Run stats' section in place — loud failure, never a silent no-op."""
    text = REPORT.read_text()
    section = SECTION_HEADER + markdown(lines, models) + "\n\n"
    new, n = _re.subn(r"## Run stats\n.*?(?=^## (?!#)|\Z)", section, text, count=1,
                      flags=_re.S | _re.M)
    if n != 1:
        raise SystemExit("report has no '## Run stats' section to replace")
    REPORT.write_text(new)
    print(f"refreshed {REPORT}")


def main() -> int:
    lines = [stat_line(r) for r in rows()]
    models = model_summary(lines)
    legend = " · ".join(f"{icon} {label}" for icon, label, _m in ASSIST_FAMILIES)
    if "--write" in sys.argv:
        write_report(lines, models)
        return 0
    if "--md" in sys.argv:
        print(markdown(lines, models))
    else:
        icons = [icon for icon, _l, _m in ASSIST_FAMILIES]
        print("MODEL PERFORMANCE — each model's last 3 STANDING runs (voided/superseded excluded)")
        print(f"{'':<3}{'model':<17}{'last 3':<12}{'tok/s':>6} {'min':>4} {'calls':>6}  "
              + " ".join(f"{i:>4}" for i in icons))
        for s in models:
            print(f"{s['badge']:<3}{s['model']:<17}{s['trend']:<12}"
                  f"{s['tok_s']:>6} {s['min']:>4} {s['calls']:>6}  "
                  + " ".join(f"{s['fam'][i]:>4}" for i in icons))
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
