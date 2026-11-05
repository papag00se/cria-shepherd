"""Build and execute training fixtures. No model, network, or test split access.

python -m suite.progress_correctness.build
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
from pathlib import Path
import subprocess
import statistics
import sys
import tempfile
import uuid
from collections import Counter, defaultdict

from cria import prompts
from suite.gliclass_probe import render_state as render_text
from suite.progress_dataset import LABELS, render_state
from suite.progress_correctness.cases import CASES
from suite.progress_correctness.more_cases import CASES as MORE_CASES
from suite.progress_correctness import numeric_cases, storage_cases, integration_cases, polyglot_cases  # populate TRAIN families
from suite.progress_correctness.rationales import RATIONALES

CASES = CASES + MORE_CASES

OUT = Path.home() / ".cria/training/progress-correctness-v2"


def diff(seed: dict[str, str], snapshot: dict[str, str]) -> str:
    blocks = []
    for name in sorted(seed.keys() | snapshot.keys()):
        before, after = seed.get(name), snapshot.get(name)
        if before == after:
            continue
        # Every line of both versions is included, not just the default hunk context.
        blocks.extend(difflib.unified_diff(
            (before or "").splitlines(), (after or "").splitlines(),
            fromfile=f"a/{name}" if before is not None else "/dev/null",
            tofile=f"b/{name}" if after is not None else "/dev/null",
            n=max(len((before or "").splitlines()), len((after or "").splitlines())) + 1,
            lineterm=""))
    return "\n".join(blocks)


def execute(files: dict[str, str], checks: dict[str, str], language: str) -> dict:
    results = {}
    root = os.environ.get("TMPDIR") or "/var/tmp"
    with tempfile.TemporaryDirectory(prefix="progress-fixture-", dir=root) as directory:
        path = Path(directory)
        for name, content in files.items():
            dest = path / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        for name, program in checks.items():
            try:
                commands = {"Python": [sys.executable, "-c"], "JavaScript": ["node", "-e"], "Ruby": ["ruby", "-e"]}
                p = subprocess.run([*commands[language], program], cwd=directory,
                                   env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "HOME": directory},
                                   text=True, capture_output=True, timeout=10, check=False)
                results[name] = {"returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
            except FileNotFoundError as exc:
                results[name] = {"returncode": None, "unavailable": str(exc), "stdout": "", "stderr": ""}
            except subprocess.TimeoutExpired as exc:
                results[name] = {"returncode": None, "timeout": True,
                                 "stdout": (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or "",
                                 "stderr": (exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""}
    return results


def build(out: Path = OUT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rows, review, evidence = [], [], []
    previous = out / "train.jsonl"
    prior_ids = {}
    if previous.exists():
        for line in previous.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            prior_ids[(row.get("group", row["family"]), row["label"])] = row["id"]
    occurrences = defaultdict(list)
    for case in CASES:
        seed = case.get("seed_files", {case["path"]: case["seed"]} if case.get("seed") else {})
        states = {
            "DONE": {**seed, **case.get("complete_files", {case["path"]: case["complete"]} if "complete" in case else {}), **case.get("done_distractors", {})},
            "PARTIAL": {**seed, **case.get("partial_files", {case["path"]: case["partial"]} if "partial" in case else {}), **case.get("partial_distractors", {})},
            "NOT_STARTED": {**seed, **case["unrelated"]},
        }
        for label, snapshot in states.items():
            identifier = prior_ids.get((case.get("group", case["family"]), label)) or uuid.uuid4().hex
            changes = diff(seed, snapshot)
            state = render_state(case["requirement"], changes)
            rendered = render_text(state)
            results = execute(snapshot, case["checks"], case["language"])
            row = {"id": identifier, "split": "train", "family": case["family"], "group": case.get("group", case["family"]),
                   "language": case["language"], "defect": case["defect"],
                   "source": "synthetic-hand-authored", "label": label,
                   "requirement": case["requirement"], "evidence": changes}
            rows.append(row)
            review.append({"id": identifier, "policy": prompts.load("offline_onejev_progress") + "\n",
                           "state": state, "rendered_state": rendered,
                           "options": list(LABELS)})
            evidence.append({"id": identifier, "label": label, "family": case["family"], "group": case.get("group", case["family"]),
                             "rationale": RATIONALES.get(case.get("group", ""), case["rationale"]), "verifier_programs": case["checks"],
                             "checks": results})
            occurrences[rendered].append({"id": identifier, "label": label})
    # Shuffle the blind packet independently of case, family and label ordering.
    import random
    random.SystemRandom().shuffle(review)
    for filename, records in [("train.jsonl", rows), ("pilot-review-blind.jsonl", review), ("verification.jsonl", evidence)]:
        with (out / filename).open("w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    duplicates = [v for v in occurrences.values() if len(v) > 1]
    lengths = defaultdict(list)
    for r in rows:
        lengths[r["label"]].append(len(render_text(render_state(r["requirement"], r["evidence"]))))
    similarities = []
    for i, left in enumerate(rows):
        candidates = [(difflib.SequenceMatcher(None, left["requirement"] + "\n" + left["evidence"],
                                                right["requirement"] + "\n" + right["evidence"], autojunk=False).ratio(), right)
                      for right in rows[i + 1:] if right["family"] != left["family"]]
        if candidates:
            score, right = max(candidates, key=lambda pair: pair[0])
            similarities.append({"left": left["id"], "right": right["id"], "ratio": score})
    by_group = defaultdict(dict)
    for r in rows:
        by_group[r["group"]][r["label"]] = len(r["evidence"])
    comparisons = Counter('DONE longer' if values['DONE'] > values['PARTIAL'] else
                          'PARTIAL longer' if values['PARTIAL'] > values['DONE'] else 'equal'
                          for values in by_group.values())
    outcomes = Counter(f"{r['label']}:{name}:{result['returncode']}" for r in evidence
                       for name, result in r['checks'].items())
    report = {"rows": len(rows), "groups": len(CASES), "families": len({c["family"] for c in CASES}),
              "labels": dict(Counter(r["label"] for r in rows)),
              "splits": dict(Counter(r["split"] for r in rows)),
              "families_by_label": {family: dict(Counter(r["label"] for r in rows if r["family"] == family)) for family in sorted({c["family"] for c in CASES})},
              "languages": dict(Counter(r["language"] for r in rows)),
              "defects": dict(Counter(r["defect"] for r in rows)),
              "sources": dict(Counter(r["source"] for r in rows)),
              "rendered_character_lengths": dict(lengths),
              "rendered_character_median_by_class": {label: statistics.median(values) for label, values in lengths.items()},
              "matched_diff_length_order": dict(comparisons), "fixture_outcomes": dict(outcomes),
              "no_change_not_started": sum(not r['evidence'] for r in rows if r['label'] == 'NOT_STARTED'),
              "exact_duplicates": duplicates,
              "near_duplicate_candidates": similarities,
              "similarity_note": "Top other-family candidate per row, for semantic review only; siblings share their family.",
              "excluded": [], "review_status": "unreviewed author proposals; not human gold"}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=OUT)
    print(json.dumps(build(parser.parse_args().out), indent=2))
