#!/usr/bin/env python3
"""Battery campaign status using inferred usefulness percentages.

Checkpoint progress reports and final judgments always report usefulness as a percentage. The
percentage is inferred holistically by a reasoner, never assembled by deterministic task counting.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from fractions import Fraction

try:
    from .model_names import canonical_name
    from .report_labels import TASK_LANGUAGES
    from .lanes import wall_minutes as _wall_minutes
except ImportError:  # direct suite/battery_status.py invocation
    from model_names import canonical_name
    from report_labels import TASK_LANGUAGES
    from lanes import wall_minutes as _wall_minutes

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"
try:  # the one locked reader/writer of results.jsonl
    from . import results_store as _rs
except ImportError:
    import results_store as _rs

NOTE_PREFIX = "BATTERY2"
COUNTED_PREFIXES = (NOTE_PREFIX, "LOWSCORE", "RERANK")
# Current roster: Nemotron Elastic restored 2026-09-30; eight models entered on 2026-09-27.
# Retired models remain named in reports and keep their rows in results.jsonl / historical_ladder.json.
# Keys renamed 2026-09-27 (operator): ternary-bonsai-2 -> bonsai2, ornith15 -> ornith1.5,
# qwen38-distill -> qwen3.8_9b_distill, k2-horizon -> k2_horizon_7b. results.jsonl `model`
# fields were migrated with them; run_ids, archives and systemd units keep their names.
MODELS = ("gemma4-qat", "bonsai2", "defiant-fable", "ornith1.5",
          "k2_horizon_7b", "phi4", "ling3-tiny", "qwen3.8_9b_distill", "nemotron-elastic")
# CURRENT matrix only — a model here must be swappable and have canonical sampling.
# gemma4 (stock Q4_K_M) and ternary-bonsai (Bonsai 1) left on 2026-09-18 when their weights
# and units were deleted; they stay VISIBLE in the reports through suite/historical_ladder.json,
# which is where their scores live. Retiring a model means dropping it from here, never deleting
# its history — the ONE exception is an operator-ordered purge of a failed trial (2026-09-27, see
# docs/model-history.md), where only a mean/best line survives.
# Logical display names come from the one official-name registry. Executable keys stay intact.
DISPLAY = tuple(dict.fromkeys(canonical_name(model) for model in MODELS))
TASKS = ("shipping-rates-rb", "cart-billing-go", "orders-api-py",
         "feed-pipeline-java", "handles-cli-node", "rust-toml-cli")
ARMS = ("BASE", "CRIA")


def rows(*, all_rows: bool = False) -> list[dict]:
    if not RESULTS.exists():
        return []
    out = []
    for line in _rs.read_text(RESULTS).splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if all_rows or str(row.get("note", "")).startswith(COUNTED_PREFIXES):
            out.append(row)
    return out


def cell(rs: list[dict], arm: str, model: str, task: str) -> dict | None:
    for row in reversed(rs):
        if row.get("superseded"):
            continue
        note = str(row.get("note", ""))
        if row.get("model") == model and row.get("task") == task and f" {arm} " in f" {note} ":
            return row
    return None


def level_cell(rs: list[dict], level: int, model: str, task: str) -> dict | None:
    """Standing row for one configured engagement rung; the rung is not a grade."""
    for row in reversed(rs):
        if row.get("superseded") or row.get("level") is None:
            continue
        try:
            same_level = int(row["level"]) == level
        except (TypeError, ValueError):
            continue
        if same_level and canonical_name(row.get("model", "")) == canonical_name(model) and row.get("task") == task:
            return row
    return None


def judged(row: dict | None) -> bool:
    return bool(row and isinstance(row.get("usefulness_percent"), int))


def judgment_of(row: dict | None) -> str:
    if not row:
        return "not run"
    if isinstance(row.get("usefulness_percent"), int):
        return f"{row['usefulness_percent']}% useful"
    return "awaiting judgment"


def in_flight() -> str | None:
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            argv = [part for part in Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0")
                    if part]
        except OSError:
            continue
        if argv and argv[0].endswith(("python", "python3")) \
                and any(arg.endswith("suite/run.py") for arg in argv):
            return " ".join(argv)
    return None


def sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, cwd=SUITE.parent).stdout.strip() or "?"
    except OSError:
        return "?"


_HIST_PATH = SUITE / "historical_ladder.json"
REPORT_PATH = SUITE.parent / "docs" / "battery-report.md"
LEGEND = ("Legend: \U0001F7E2 \u226588% \u00b7 \U0001F7E1 \u226563% \u00b7 \U0001F7E0 \u226538% \u00b7 \U0001F534 <38%; blank = pending/unjudged. "
          "Usefulness: share of requested work delivered as useful code. Percentages are independently judged "
          "usefulness; averages include judged zeros, exclude failed/unjudged attempts, and use known metrics only. "
          "Average minutes are wall time (including judge waits); partially filled rows have partial coverage. "
          "Avg tok/s is the mean of known per-task all-phase generation rates, not wall-time throughput; "
          "`\u00b7` = unknown timing. Ruby/Go/Python/Java/Node/Rust are the six task columns.")


def _historical() -> dict:
    """Recorded inference-usefulness data for models whose per-cell scores no longer survive in results.jsonl
    (see suite/historical_ladder.json); empty when the file is missing."""
    try:
        return json.loads(_HIST_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _badge(pct: float) -> str:
    """Quarter bands off the midpoints: green at/above 87.5, yellow 62.5, orange 37.5, red below."""
    return ("\U0001F7E2" if pct >= 87.5 else "\U0001F7E1" if pct >= 62.5
            else "\U0001F7E0" if pct >= 37.5 else "\U0001F534")


def _dot(pct) -> str:
    return f"{_badge(pct)} {round(pct)}%" if pct is not None else "\u00b7"


def _measurement(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _mean(values, *, digits: int | None = None):
    if not values:
        return None
    mean = sum(values) / len(values)
    return round(mean, digits) if digits is not None else round(mean)


def _table(rs: list[dict], hist: dict, tasks, level: int) -> dict:
    """model -> (six cell percentages, avg minutes, avg calls, avg tok/s) at one level.

    A cell is the latest judged, non-aborted row of the cell; a recorded (frozen) cell is replaced by a
    live judgment of the same cell."""
    frozen = {}
    for name, levels in hist.get("frozen", {}).items():
        frozen.setdefault(canonical_name(name), {}).update(levels)
    eligible = [r for r in rs if judged(r) and not r.get("aborted") and r.get("terminal") != "harness-error"]
    models = [m for m in DISPLAY if m in frozen or any(canonical_name(r.get("model", "")) == m for r in eligible)]
    out = {}
    for model in models:
        old = frozen.get(model, {}).get(str(level)) or {}
        live = [level_cell(eligible, level, model, task) for task in tasks]
        recorded = list(old.get("pct", [])) + [None] * len(tasks)
        cells = [r["usefulness_percent"] if r else recorded[i] for i, r in enumerate(live)]
        if all(c is None for c in cells):
            continue
        rows = [r for r in live if r]
        minutes = _mean([_wall_minutes(r) for r in rows if _measurement(r.get("wall_seconds"))])
        calls = _mean([r["calls"] for r in rows if _measurement(r.get("calls"))])
        rate = _mean([r["avg_tok_s"] for r in rows if _measurement(r.get("avg_tok_s"))], digits=1)
        out[model] = (cells, old.get("min") if minutes is None else minutes,
                      old.get("calls") if calls is None else calls, rate)
    return out


def report(rs: list[dict], now: float | None = None) -> str:
    """The standing scorecard: an `Updated:` line, then one table per engagement level L0-L5 (a colored-dot
    cell per task, the cell an inferred usefulness percentage), then the legend. Every table lists its models in
    the order of their exact L5 mean usefulness (highest first, ties by model name, models without an L5 score
    last)."""
    hist = _historical()
    tasks = hist.get("tasks", list(TASKS))
    labels = hist.get("levels", {})
    tables = [_table(rs, hist, tasks, level) for level in range(6)]
    l5 = {model: [p for p in cells if p is not None] for model, (cells, *_rest) in tables[5].items()}
    rank = lambda model: (not l5.get(model), -Fraction(sum(l5[model]), len(l5[model])) if l5.get(model) else 0, model)
    updated = time.strftime("%Y-%m-%d %H:%M %Z", time.localtime(now if now is not None else time.time()))
    out = ["# Battery report", "", f"Updated: {updated}", ""]
    for level, table in enumerate(tables):
        scores = [p for cells, *_rest in table.values() for p in cells if p is not None]
        out += [f"## L{level} \u2014 {labels.get(str(level), '')} \u2014 {_mean(scores) or 0}%", "",
                "| model | " + " | ".join(TASK_LANGUAGES[t].lower() for t in TASKS)
                + " | avg pct | avg min | avg calls | avg tok/s |",
                "|---|" + "---|" * len(TASKS) + "---:|---:|---:|---:|"]
        for model in sorted(table, key=rank):
            cells, minutes, calls, rate = table[model]
            known = [p for p in cells if p is not None]
            out.append("| " + " | ".join([model, *map(_dot, cells), f"{_mean(known)}%",
                       *("\u00b7" if v is None else str(v) for v in (minutes, calls, rate))]) + " |")
        out.append("")
    return "\n".join(out) + "\n" + LEGEND + "\n"


def write_report(rs: list[dict], now: float | None = None) -> Path:
    """Write docs/battery-report.md from the result rows."""
    text = report(rs, now)
    temp = REPORT_PATH.with_name(f".{REPORT_PATH.name}.{os.getpid()}.tmp")
    temp.write_text(text)
    temp.replace(REPORT_PATH)
    return REPORT_PATH


def main() -> int:
    if "--write" in sys.argv:
        print(f"wrote {write_report(rows(all_rows=True))}")
        return 0
    rs = rows()

    print("BATTERY CAMPAIGN — inferred usefulness percentages\n")
    for task in TASKS:
        for model in MODELS:
            base = cell(rs, "BASE", model, task)
            driven = cell(rs, "CRIA", model, task)
            print(f"{task:<20} {model:<19} BASE={judgment_of(base)}; CRIA={judgment_of(driven)}")

    live = in_flight()
    if live:
        print(f"\nIN FLIGHT: {live[:120]}")
        return 2

    for arm in ARMS:
        for model in MODELS:
            for task in TASKS:
                if cell(rs, arm, model, task) is None:
                    print(f"\nNEXT: RUN {arm} {model} {task}")
                    print(f"      python3 suite/battery_run.py --arm {arm} --model {model} --task {task}")
                    return 1
    print("\nNEXT: NOTHING — campaign complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
