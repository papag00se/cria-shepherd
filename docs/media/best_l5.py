"""Export best retained L5 usefulness judgments, not a new score or current campaign.

Search the working ledger and its retained Git-ref history, plus the frozen inference
ladder's history. Use the latest available final judgment per run before maximizing
across runs. Keep original artifact IDs and never import grades or checkpoints.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

MEDIA = Path(__file__).resolve().parent
# Presentation identity belongs to this reviewed checkout, including the owner's
# Defiant-Fable correction; do not edit the active campaign's executable keys.
sys.path.insert(0, str(MEDIA.parents[1]))
from suite.battery_status import TASKS, judged
from suite.model_names import canonical_name


PATHS = ("suite/results/results.jsonl", "suite/historical_ladder.json")


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True,
                          capture_output=True).stdout


def versions(root, relative):
    """Working bytes first, then each distinct retained Git blob, newest first."""
    content = (root / relative).read_bytes()
    seen = {hashlib.sha256(content).hexdigest()}
    yield content, {"path": relative, "revision": "working-tree", "sha256": next(iter(seen))}
    commits = git(root, "log", "--all", "--date-order", "--format=%H", "--", relative).decode().splitlines()
    for commit in commits:
        # Deletion commits have no blob; this is an absence, not an alternate score.
        entry = git(root, "ls-tree", commit, "--", relative).decode().strip()
        if not entry:
            continue
        blob = entry.split()[2]
        content = git(root, "cat-file", "blob", blob)
        digest = hashlib.sha256(content).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        yield content, {"path": relative, "revision": commit, "blob": blob, "sha256": digest}


def score_of(row):
    # `usefulness` is the documented predecessor of `usefulness_percent`, not a grade.
    key = "usefulness_percent" if row.get("usefulness_percent") is not None else "usefulness"
    score = row.get(key)
    if not judged({"usefulness_percent": score}) or type(score) is not int or not 0 <= score <= 100:
        return None
    return score, key


def collect(models, tasks, ledger_versions, frozen_versions):
    """Select valid final judgments; superseded runs remain historical observations."""
    winners = {}
    seen_runs = set()

    def consider(model, task, score, source):
        key = (model, task)
        if key not in winners or score > winners[key]["score"]:
            winners[key] = {"model": model, "task": task, "score": score, "source": source}

    for content, version in ledger_versions:
        rows = [json.loads(line) for line in content.decode().splitlines() if line.strip()]
        for row in reversed(rows):
            model = canonical_name(row.get("model", ""))
            if model not in models or row.get("task") not in tasks or row.get("level") != 5:
                continue
            value = score_of(row)
            if value is None:
                continue
            run_id = row["run_id"]
            if run_id in seen_runs:
                continue
            seen_runs.add(run_id)
            score, field = value
            source = {**version, "kind": "final-ledger-judgment", "run_id": run_id,
                      "original_model": row["model"], "score_field": field,
                      "code_revision": row.get("code_revision") or row.get("revision"),
                      "planner": row.get("planner"), "planner_enabled": row.get("planner_enabled"),
                      "started": row.get("started"), "note": row.get("note"),
                      "superseded_run": bool(row.get("superseded"))}
            consider(model, row["task"], score, source)

    for content, version in frozen_versions:
        frozen = json.loads(content)
        source_tasks = frozen["tasks"]
        for original, levels in frozen.get("frozen", {}).items():
            model = canonical_name(original)
            if model not in models or "5" not in levels:
                continue
            scores = levels["5"]["pct"]
            if len(scores) != len(source_tasks):
                raise ValueError("Frozen L5 scores do not align with their task labels")
            for task, score in zip(source_tasks, scores):
                if task not in tasks or type(score) is not int or not 0 <= score <= 100:
                    raise ValueError("Invalid frozen inferred-usefulness cell")
                consider(model, task, score, {**version, "kind": "frozen-inference-judgment",
                         "original_model": original, "level": 5, "task": task,
                         "run_id": None, "record": f"frozen.{original}.5.pct"})
    return winners


def apply_display_scope(data):
    """Temporarily hide roster members without deleting baseline scores or fleet data."""
    old_order = data["roster_model_order"] if "roster_model_order" in data else data["model_order"]
    roster = list(dict.fromkeys(canonical_name(m) for m in old_order
                  if canonical_name(m) == m or canonical_name(m) not in old_order))
    excluded = [canonical_name(m) for m in data.get("excluded_models", [])]
    if set(excluded) - set(roster):
        raise ValueError("Cannot hide a model outside the retained README roster")
    models = [m for m in roster if m not in excluded]
    if "standing_l0" not in data:
        data["standing_l0"] = data["levels"]["0"]
    original = data["standing_l0"]
    rows = [r for r in original["rows"] if r["model"] in models]
    values = [v for r in rows for v in r["cells"] if v is not None]
    if not values:
        raise ValueError("No observed L0 cells remain in this display scope")
    data["levels"]["0"] = {**original, "rows": rows, "overall": round(sum(values) / len(values)),
                           "selection": "standing-visible-roster", "excluded_models": excluded}
    data["roster_model_order"] = roster
    data["model_order"] = models
    return models


def export(root, output=MEDIA):
    data = json.loads((output / "battery-data.json").read_text())
    models = apply_display_scope(data)
    inputs = []

    def recorded_versions(relative):
        for content, source in versions(root, relative):
            inputs.append(source)
            yield content, source

    winners = collect(models, TASKS, recorded_versions(PATHS[0]), recorded_versions(PATHS[1]))
    rows = [{"model": model, "cells": [winners[(model, task)]["score"] if (model, task) in winners else None
                                      for task in TASKS]} for model in models]
    values = [v for row in rows for v in row["cells"] if v is not None]
    if not values:
        raise ValueError("No retained L5 usefulness judgments found")
    now = datetime.now().astimezone()
    best = {"selection": "best-recorded", "overall": round(sum(values) / len(values)),
            "rows": rows, "provenance": {"recorded_utc": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "report_date": now.strftime("%Y-%m-%d %H:%M"), "report_timezone": now.tzname(),
            "source_revision": git(root, "rev-parse", "HEAD").decode().strip(),
            "omitted_models": data.get("excluded_models", []),
            "identity_registry_sha256": hashlib.sha256((MEDIA.parents[1] / "suite/model_names.py").read_bytes()).hexdigest(),
            "selection": "Latest retained final judgment per run, then maximum per canonical model/task; "
                         "also include explicitly frozen inference-usefulness history. Superseded runs count; "
                         "grade/checkpoint fields do not. Working ledger takes priority over Git history.",
            "scope": "Existing README roster; Defiant-Fable merged into qwen3.8_9b_distill. "
                     "Retained working files and all Git refs only, not purged/absent observations. "
                     "Historical Nemotron L5 is best-ever evidence, not a fresh campaign result.",
            "limitations": "Selection-biased maxima across different dates, revisions, variants and planner settings; "
                           "not one run, not expected performance, not causal uplift. Some full captures are unavailable."},
            "cells": [winners[(model, task)] for model in models for task in TASKS if (model, task) in winners],
            "examined_sources": inputs}
    (output / "battery-l5-best.json").write_text(json.dumps(best, indent=2) + "\n")
    if "standing_l5" not in data:
        data["standing_l5"] = data["levels"]["5"]
    data["levels"]["5"] = {k: best[k] for k in ("selection", "overall", "rows", "provenance")}
    data["model_order"] = models
    (output / "battery-data.json").write_text(json.dumps(data, indent=2) + "\n")
    print("Saved historical L5 maxima with cell-level provenance; L0 scores retained.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    export(args.source_root.resolve())


if __name__ == "__main__":
    main()
