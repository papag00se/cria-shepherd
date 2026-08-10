#!/usr/bin/env python3
"""The battery campaign's ONE source of truth — what has run, and what runs next.

Reads `suite/results/results.jsonl` and nothing else. Not a conversation, not a memory, not a
report someone typed. Whatever it prints under `NEXT:` is the next action; when a chat message and
this tool disagree, this tool is right. `docs/battery-goal.md` is the campaign it drives.

THE QUESTION: for four models across six tasks, what does the same model score with cria DRIVING
versus with cria only PLUMBING? Nothing in this project has ever measured what the assists are
worth, because there has never been a control.

ORDER IS PART OF THE DESIGN. The whole BASE arm completes before the first CRIA run is offered. A
phase then runs on one code state end to end; pair-by-pair invites a fix landing between the halves
of a pair, which voids the only comparison the campaign exists to make.

Exit codes: 0 campaign complete · 1 work remains · 2 a run is in flight.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"
WALK = SUITE.parent / "docs" / "audits" / "battery-walk.md"
NOTE_PREFIX = "BATTERY2"

MODELS = ("gemma4", "qwen35", "ternary-bonsai", "nemotron-elastic")
# ONE KIND OF WORK PER LANGUAGE. BATTERY1 ran six tasks that were five-sixths Python, because the
# selection dropped the Go and JavaScript members of the original five and substituted Python ones.
# A result that only ever appears in Python cannot tell a cria defect from a Python defect.
#
#   shipping-rates-rb    ruby        fix failing tests · feature from spec · write tests · docs
#   cart-billing-go      go          bug from a report · logging · config · refactor
#   orders-api-py        python      API endpoint · schema change · integration tests · security
#   feed-pipeline-java   java        data transform · optimise · concurrency · code review
#   handles-cli-node     javascript  external service · CLI · dependency migration · containerise
#   rust-toml-cli        rust        discover and use a third-party dependency
#
# BATTERY1's rows stay on disk under their own prefix — they are evidence, and this is a different
# question. See docs/task-battery.md.
TASKS = ("shipping-rates-rb", "cart-billing-go", "orders-api-py",
         "feed-pipeline-java", "handles-cli-node", "rust-toml-cli")
ARMS = ("BASE", "CRIA")          # order matters: the whole BASE arm first


def rows() -> list[dict]:
    if not RESULTS.exists():
        return []
    out = []
    for line in RESULTS.read_text().splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if str(r.get("note", "")).startswith(NOTE_PREFIX):
            out.append(r)
    return out


def cell(rs: list[dict], arm: str, model: str, task: str) -> dict | None:
    """The STANDING row for one matrix cell — superseded rows are evidence, not results."""
    for r in reversed(rs):
        if r.get("superseded"):
            continue
        note = str(r.get("note", ""))
        if r.get("model") == model and r.get("task") == task and f" {arm} " in f" {note} ":
            return r
    return None


def in_flight() -> str | None:
    """A live `suite/run.py`, found by reading /proc rather than pgrep — a pattern that matches this
    tool's own command line reports itself as the run it is looking for, which has happened."""
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            argv = [a for a in Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0") if a]
        except OSError:
            continue
        if argv and argv[0].endswith("python3") and any(a.endswith("suite/run.py") for a in argv):
            return " ".join(argv)
    return None


def walked(run_id: str) -> bool:
    return WALK.exists() and f"## {run_id}" in WALK.read_text()


def sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, cwd=SUITE.parent).stdout.strip() or "?"
    except OSError:
        return "?"


def score_of(r: dict | None) -> str:
    if not r:
        return "  — "
    return f"{int(r.get('score') or 0)}/{int(r.get('max_score') or 4)}"


def _n(r: dict | None, key: str) -> str:
    if not r:
        return "—"
    v = r.get(key)
    return "—" if v is None else (f"{v/60:.0f}" if key == "wall_seconds" else str(v))


NOTES_MARKER = "<!-- NOTES — hand-written, preserved across regeneration -->"
GLYPH = {0: "⁰⁄₄", 1: "¹⁄₄", 2: "²⁄₄", 3: "³⁄₄", 4: "⁴⁄₄"}


def _badge(avg: float) -> str:
    return "🟢" if avg >= 3.5 else "🟡" if avg >= 2.5 else "🟠" if avg >= 1.5 else "🔴"


def language(task: str) -> str:
    """The task's language, read from its own meta.toml — the matrix is one language per task, so
    the header is derived rather than restated here where the two could drift apart."""
    meta = SUITE / "tasks" / task / "meta.toml"
    if meta.exists():
        for line in meta.read_text().splitlines():
            if line.strip().startswith("language"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "?"


def _avg(rows: list[dict], key: str, scale: float = 1.0) -> str:
    vals = [r.get(key) for r in rows if r.get(key) is not None]
    return f"{sum(vals) / len(vals) * scale:.0f}" if vals else "—"


def _arm_grid(rs: list[dict], arm: str) -> list[str]:
    """One row per model, one column per language. The shape the operator reads first."""
    langs = [language(t) for t in TASKS]
    out = [f"| model | " + " | ".join(langs) + " | total | avg tok/s | avg min | avg calls |",
           "|---|" + "---|" * len(TASKS) + "---:|---:|---:|---:|"]
    ranked = []
    for m in MODELS:
        cells = [cell(rs, arm, m, t) for t in TASKS]
        have = [c for c in cells if c]
        if not have:
            continue
        scores = [int(c.get("score") or 0) for c in have]
        ranked.append((sum(scores) / len(scores), -sum(
            float(c.get("wall_seconds") or 0) for c in have), m, cells, have, scores))
    for avg, _t, m, cells, have, scores in sorted(ranked, key=lambda x: (-x[0], -x[1])):
        got = " | ".join(GLYPH[int(c.get("score") or 0)] if c else "·" for c in cells)
        tok = [c["avg_tok_s"] for c in have if c.get("avg_tok_s")]
        rate = f"{sum(tok) / len(tok):.1f}" if tok else "—"
        out.append(f"| {_badge(avg)} {m} | {got} | **{sum(scores)}/{4 * len(have)}** | {rate} "
                   f"| {_avg(have, 'wall_seconds', 1 / 60)} | {_avg(have, 'calls')} |")
    if len(out) == 2:
        out.append("| _no runs yet_ |" + " |" * (len(TASKS) + 3))
    return out


def report(rs: list[dict]) -> str:
    """Render the campaign tables. Numbers come from results.jsonl every time; the prose below
    NOTES_MARKER is carried over untouched, because a finding is not derivable from a score."""
    out = ["# Battery campaign — what the assists are worth, across six languages", "",
           "Regenerated by `python3 suite/battery_status.py --write` after every run. Every table",
           "is derived from `suite/results/results.jsonl`; the notes below are written by hand.", "",
           "One kind of work per language, so a finding that only shows up in one language is",
           "visible as such. Task-to-language mapping: `docs/task-battery.md`.", "",
           "## Baseline — assists OFF", "",
           "cria translating only: no planner, no steers, no gates, no critics, no completion",
           "judging. What each model does on its own.", ""]
    out += _arm_grid(rs, "BASE")
    out += ["", "## Assisted — assists ON", ""]
    out += _arm_grid(rs, "CRIA")

    pairs = [(t, m, cell(rs, "BASE", m, t), cell(rs, "CRIA", m, t)) for t in TASKS for m in MODELS]
    pairs = [(t, m, b, c) for t, m, b, c in pairs if b and c]
    if pairs:
        out += ["", "## What the assists were worth", "",
                "Read Δ next to the calls and minutes columns — a +1 bought with 15× the calls is",
                "not the same result as a +1 bought with fewer (`docs/battery-goal.md`).", "",
                "| task | language | model | BASE | CRIA | Δ | calls B→C | min B→C |",
                "|---|---|---|---|---|---|---|---|"]
        for t, m, b, c in pairs:
            d = int(c.get("score") or 0) - int(b.get("score") or 0)
            out.append(f"| {t} | {language(t)} | {m} | {score_of(b).strip()} | "
                       f"{score_of(c).strip()} | {f'**{d:+d}**' if d else '0'} | "
                       f"{_n(b,'calls')}→{_n(c,'calls')} | "
                       f"{_n(b,'wall_seconds')}→{_n(c,'wall_seconds')} |")

    out += ["", "## Every run", "",
            "| task | language | model | arm | score | min | calls | tok/s | terminal |",
            "|---|---|---|---|---:|---:|---:|---:|---|"]
    for task in TASKS:
        for model in MODELS:
            for arm in ARMS:
                c = cell(rs, arm, model, task)
                if not c:
                    continue
                tok = c.get("avg_tok_s")
                out.append(f"| {task} | {language(task)} | {model} | {arm} | "
                           f"{score_of(c).strip()} | {_n(c,'wall_seconds')} | {_n(c,'calls')} | "
                           f"{f'{tok:.1f}' if tok else '—'} | {c.get('terminal','')} |")
    return "\n".join(out) + "\n\n" + NOTES_MARKER + "\n"


def write_report(rs: list[dict]) -> Path:
    path = SUITE.parent / "docs" / "audits" / "battery-report.md"
    body = report(rs)
    if path.exists() and NOTES_MARKER in (old := path.read_text()):
        body += old.split(NOTES_MARKER, 1)[1].lstrip("\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def main() -> int:
    rs = rows()
    if "--write" in sys.argv:
        print(f"wrote {write_report(rs)}")
        return 0
    print(f"BATTERY CAMPAIGN — {len(MODELS)} models × {len(TASKS)} tasks × 2 arms "
          f"= {len(MODELS)*len(TASKS)*2} runs   (note prefix {NOTE_PREFIX})\n")
    print(f"{'task':<20}{'model':<19}{'BASE':>6}{'CRIA':>7}{'Δ':>5}")
    print("-" * 57)
    todo: list[tuple[str, str, str]] = []
    filled = 0
    for task in TASKS:
        for model in MODELS:
            b, c = cell(rs, "BASE", model, task), cell(rs, "CRIA", model, task)
            delta = ""
            if b and c:
                d = int(c.get("score") or 0) - int(b.get("score") or 0)
                delta = f"{d:+d}"
            print(f"{task:<20}{model:<19}{score_of(b):>6}{score_of(c):>7}{delta:>5}")
            filled += bool(b) + bool(c)
            # ONE entry per cell-pair: the next thing to run for this pair. Counting cells off
            # `todo` would report an empty campaign as half finished (24 of 48), which is why the
            # filled tally is counted directly instead of inferred.
            if not b:
                todo.append(("BASE", model, task))
            elif not c:
                todo.append(("CRIA", model, task))
    total = len(MODELS) * len(TASKS) * 2
    base_done = sum(1 for t in TASKS for m in MODELS if cell(rs, "BASE", m, t))
    print(f"\n{filled} of {total} cells filled   "
          f"(BASE arm {base_done}/{len(MODELS)*len(TASKS)})")

    live = in_flight()
    if live:
        print(f"\nIN FLIGHT: {live[:120]}")
        print("NEXT: WAIT — one run at a time, and do not edit cria/ or cria/prompts/ while it runs.")
        return 2

    # A task whose finished BASE cells are ALL ZERO is a suspect verifier, not four failures. Five of
    # the six tasks have never had a correct solution scored against them, so an unsatisfiable
    # verifier is a live possibility and would waste the other half of the campaign. Stop and prove
    # the task before spending more GPU on it.
    for task in TASKS:
        base = [cell(rs, "BASE", m, task) for m in MODELS]
        have = [b for b in base if b]
        if len(have) >= 2 and all(int(b.get("score") or 0) == 0 for b in have):
            print(f"\nNEXT: VALIDATE {task}   "
                  f"({len(have)} baseline runs, every one 0/4 — prove the verifier is satisfiable)")
            print(f"      read suite/tasks/{task}/verify.py against suite/tasks/{task}/prompt.txt,")
            print(f"      then solve it by hand in a copy of the seed and score that. See the")
            print(f"      'largely unproven' section of docs/battery-goal.md.")
            return 1

    # A CRIA run that LOST to its BASE twin is the campaign's whole point; walk it before running more.
    for task in TASKS:
        for model in MODELS:
            b, c = cell(rs, "BASE", model, task), cell(rs, "CRIA", model, task)
            if b and c and int(c.get("score") or 0) < int(b.get("score") or 0) \
                    and not walked(str(c.get("run_id"))):
                print(f"\nNEXT: WALK {c.get('run_id')}   "
                      f"(CRIA {score_of(c)} lost to BASE {score_of(b)} — cria made it worse)")
                print(f"      python3 suite/walk.py {str(c.get('capture_dir','')).split('/')[-1]} "
                      f"--out /tmp/walk-{model}-{task}")
                print(f"      python3 suite/reasoner_audit.py "
                      f"{str(c.get('capture_dir','')).split('/')[-1]} --bad")
                return 1

    if not todo:
        print("\nNEXT: NOTHING — campaign complete. Write the closing summary per docs/battery-goal.md.")
        return 0

    # BASE arm first, entirely. `todo` is built task-major, so sort by arm to enforce the phase.
    arm, model, task = sorted(todo, key=lambda t: ARMS.index(t[0]))[0]
    drive = "false" if arm == "BASE" else "true"
    remaining = sum(1 for t in todo if t[0] == arm)
    print(f"\nNEXT: RUN {arm} {model} {task}   ({remaining} left in the {arm} arm)")
    print(f"      python3 suite/battery_run.py --arm {arm} --model {model} --task {task}")
    print(f"      (sets [engagement] drive = {drive}, restarts cria, then runs — "
          f"note \"{NOTE_PREFIX} {arm} {model} {sha()}\")")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
