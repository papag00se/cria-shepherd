#!/usr/bin/env python3
"""Battery campaign status using inferred usefulness percentages.

Checkpoint progress reports and final judgments always report usefulness as a percentage. The
percentage is inferred holistically by a reasoner, never assembled by deterministic task counting.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"
NOTE_PREFIX = "BATTERY2"
COUNTED_PREFIXES = (NOTE_PREFIX, "LOWSCORE", "RERANK")
MODELS = ("gemma4", "qwen35", "ternary-bonsai", "ornith15", "gigachat31")
TASKS = ("shipping-rates-rb", "cart-billing-go", "orders-api-py",
         "feed-pipeline-java", "handles-cli-node", "rust-toml-cli")
ARMS = ("BASE", "CRIA")


def rows() -> list[dict]:
    if not RESULTS.exists():
        return []
    out = []
    for line in RESULTS.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if str(row.get("note", "")).startswith(COUNTED_PREFIXES):
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
        if same_level and row.get("model") == model and row.get("task") == task:
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


def _stamp(rs: list[dict], now: float | None = None) -> str:
    fmt = "%Y-%m-%d %H:%M"
    written = time.strftime(fmt, time.localtime(now if now is not None else time.time()))
    latest = max((row for row in rs if row.get("started")),
                 key=lambda row: row["started"], default=None)
    if latest is None:
        return f"**Last updated {written}** — no completed rows yet."
    finished = time.strftime(fmt, time.localtime(
        latest["started"] + (latest.get("wall_seconds") or 0)))
    return f"**Last updated {written}** — newest row `{latest.get('run_id', '?')}`, finished {finished}."


def report(rs: list[dict], now: float | None = None) -> str:
    # Current matrices govern future runs, not historical visibility. Keep every model with a
    # recorded row in the report after the active models, so a fleet replacement never erases data.
    historical = tuple(dict.fromkeys(str(row.get("model")) for row in rs
                                     if row.get("model") and row.get("model") not in MODELS))
    report_models = MODELS + historical
    out = ["# Battery — usefulness status", "", _stamp(rs, now), "",
           "Every checkpoint progress report and final judgment is an inferred percentage of "
           "usefulness backed by inspected workspace evidence.", ""]
    levels = sorted({int(row["level"]) for row in rs
                     if row.get("level") is not None and not row.get("superseded")})
    for level in levels:
        out += [f"## Engagement configuration {level}", "",
                "| model | task | judgment |", "|---|---|---|"]
        for model in report_models:
            for task in TASKS:
                row = level_cell(rs, level, model, task)
                if row:
                    out.append(f"| {model} | {task} | {judgment_of(row)} |")
        out.append("")
    return "\n".join(out) + "\n"


def write_report(rs: list[dict]) -> Path:
    path = SUITE.parent / "docs" / "audits" / "battery-report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report(rs))
    return path


def main() -> int:
    rs = rows()
    if "--write" in sys.argv:
        print(f"wrote {write_report(rs)}")
        return 0

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
