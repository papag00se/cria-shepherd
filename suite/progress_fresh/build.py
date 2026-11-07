"""Build the fresh, author-labelled DONE / PARTIAL / NOT_STARTED test set for the System 1 ``progress`` family.

Each task in ``defs/`` is a small seed project plus requirements; every requirement has three hand-written
snapshots with KNOWN labels (not_started = seed or unrelated change only, partial, done). Rows use the same format
and the same diff renderer (``suite.progress_dataset.seed_diff``) as the training rows. Split by task:
DEV_TASKS -> dev.jsonl (exploratory probing), everything else -> test.jsonl (never used to tune).

    python -m suite.progress_fresh.build [--out ~/.cria/test-runs/outputs/research/progress-v1/fresh]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from suite.progress_dataset import seed_diff

HERE = Path(__file__).resolve().parent
OUT = Path.home() / ".cria" / "test-runs" / "outputs" / "research" / "progress-v1" / "fresh"
DEV_TASKS = ("recipes-rb", "weather-js", "wordtrim-lua", "backup-sh", "logparse-pl", "interval-clj", "ratelimit-py")


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def tasks() -> list[dict]:
    return [importlib.import_module(f"suite.progress_fresh.defs.{p.stem}").TASK
            for p in sorted((HERE / "defs").glob("*.py")) if p.stem != "__init__"]


def build(out: Path = OUT) -> dict:
    tasks_dir = out / "tasks"
    shutil.rmtree(tasks_dir, ignore_errors=True)
    rows: dict[str, list[dict]] = {"dev": [], "test": []}
    for t in tasks():
        seed_dir = tasks_dir / t["name"] / "seed"
        _write(seed_dir, t["seed"])
        for k, req in enumerate(t["reqs"]):
            snaps = {
                "NOT_STARTED": t.get("unrelated", {}) if k % 2 else {},
                "PARTIAL": req["partial"],
                "DONE": req["done"],
            }
            for label, overlay in snaps.items():
                if label == "NOT_STARTED" and not req.get("ns", not t.get("extension", False)):
                    continue  # extension tasks emit NOT_STARTED only as a small control (ns=True opts in)
                ws = tasks_dir / t["name"] / req["id"] / label.lower()
                _write(ws, {**t["seed"], **overlay})
                evidence = seed_diff(seed_dir, ws)
                split = "dev" if t["name"] in DEV_TASKS else "test"
                rows[split].append({
                    "id": f"{t['name']}/{req['id']}/{label}", "task": t["name"], "language": t["language"],
                    "split": split, "requirement": req["text"], "label": label,
                    "label_source": "author-known (not judged)", "evidence": evidence,
                })
    manifest: dict = {"labels_are": "author-known by construction, not model-judged; never add to any training set",
                      "splits": {}}
    for split, rs in rows.items():
        path = out / f"{split}.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs))
        by_task = defaultdict(Counter)
        for r in rs:
            by_task[r["task"]][r["label"]] += 1
        manifest["splits"][split] = {
            "rows": len(rs), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "by_label": dict(Counter(r["label"] for r in rs)),
            "by_language": dict(Counter(r["language"] for r in rs)),
            "by_task": {k: dict(v) for k, v in sorted(by_task.items())},
            "evidence_chars": {"min": min(len(r["evidence"]) for r in rs), "max": max(len(r["evidence"]) for r in rs)},
        }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    print(json.dumps(build(ap.parse_args().out), indent=2))
