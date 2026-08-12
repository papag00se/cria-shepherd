#!/usr/bin/env python3
"""Collect the battery's task prompts into one readable document, generated from the files.

WHY THIS IS A GENERATOR AND NOT A HAND-WRITTEN DOC. The prompt a model receives is
``suite/tasks/<task>/prompt.txt`` — `run.py:274` reads exactly that file and nothing else. Reviewing
the wording used to mean opening six of them, so the text was pasted into `docs/task-battery.md`
instead. A pasted copy is a second source of truth that drifts the moment a prompt is edited, and
this project has already paid for two of those (`groundtruth.BUILD_ARTIFACT_DIRS`, which went out of
sync with its copy in `execcheck`, and the read ledger's docstring, which was right while its input
lied). So the document is derived, every time, from the files the runner reads.

Everything on the page is read, never restated: the deliverables and the wall clock come from
`meta.toml`, the scored checks are parsed out of `verify.py`, and the prompt is the file verbatim.
The task list itself is imported from `battery_status` rather than repeated here.

    python3 suite/prompt_digest.py            # print to stdout
    python3 suite/prompt_digest.py --write    # write docs/task-prompts.md
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from battery_status import SUITE, TASKS  # noqa: E402

DOC = SUITE.parent / "docs" / "task-prompts.md"

# Which language each task is the battery's single representative of. One kind of work per language
# is the battery's whole design (battery_status.TASKS carries the rationale), so the language is a
# fact about the matrix, not decoration.
LANGUAGE = {
    "shipping-rates-rb": "Ruby",
    "cart-billing-go": "Go",
    "orders-api-py": "Python",
    "feed-pipeline-java": "Java",
    "handles-cli-node": "Node",
    "rust-toml-cli": "Rust",
}

# How verify.py records a scored check. Parsed rather than duplicated: a check renamed in the
# verifier renames itself here, and a check added without a deliverable shows up as a count mismatch.
_CHECK = re.compile(r'r\["parts"\]\["(\w+)"\]')

# suite/run.py: `wall = milestone_s * deliverable_count(task_dir)`. Restated as a constant so the
# document says how long a task gets without importing the runner's argument parsing.
MINUTES_PER_DELIVERABLE = 15


def task_facts(task: str) -> dict:
    """Everything the document says about one task, all of it READ from that task's own files."""
    d = SUITE / "tasks" / task
    meta = tomllib.loads((d / "meta.toml").read_text())
    deliverables = list(meta.get("deliverables") or [])
    checks = list(dict.fromkeys(_CHECK.findall((d / "verify.py").read_text())))
    return {
        "task": task,
        "language": LANGUAGE.get(task, "?"),
        "prompt": (d / "prompt.txt").read_text().rstrip("\n"),
        "deliverables": deliverables,
        "checks": checks,
        "wall_minutes": MINUTES_PER_DELIVERABLE * len(deliverables),
    }


def render(facts: list[dict]) -> str:
    out = [
        "# The task prompts",
        "",
        "**Generated — do not edit.** `python3 suite/prompt_digest.py --write`",
        "",
        "This is the text a model actually receives. Each block is `suite/tasks/<task>/prompt.txt`",
        "verbatim, which is the file `suite/run.py` reads and the only source of truth. The",
        "deliverables and the clock come from that task's `meta.toml`; the scored checks are parsed",
        "out of its `verify.py`.",
        "",
        "One kind of work per language, so a fault that only shows up in one language is visible as",
        "such. Why these six and not others: `docs/task-battery.md`.",
        "",
        "A run's wall clock is 15 minutes per declared deliverable. The milestone FLOOR is separate",
        "and is one passing check per 15-minute interval, regardless of how many deliverables a task",
        "declares.",
        "",
        "| task | language | deliverables | checks | wall |",
        "|---|---|---:|---:|---:|",
    ]
    for f in facts:
        out.append(f"| [{f['task']}](#{f['task']}) | {f['language']} | {len(f['deliverables'])} "
                   f"| {len(f['checks'])} | {f['wall_minutes']} min |")
    for f in facts:
        gap = "" if len(f["deliverables"]) == len(f["checks"]) else (
            f"\n> **Count mismatch:** {len(f['deliverables'])} deliverables declared but "
            f"{len(f['checks'])} checks scored. The wall is paced on the deliverable count, so these "
            f"must agree.\n")
        out += [
            "",
            f"## {f['task']}",
            "",
            f"**{f['language']}** · {len(f['deliverables'])} deliverables · {f['wall_minutes']}-minute wall",
            "",
            "Deliverables: " + ", ".join(f"`{d}`" for d in f["deliverables"]),
            "",
            "Scored checks: " + ", ".join(f"`{c}`" for c in f["checks"]),
            gap,
            "```text",
            f["prompt"],
            "```",
        ]
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help=f"write {DOC.relative_to(SUITE.parent)}")
    args = ap.parse_args()
    text = render([task_facts(t) for t in TASKS])
    if args.write:
        DOC.write_text(text)
        print(f"wrote {DOC}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
