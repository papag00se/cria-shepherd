#!/usr/bin/env python3
"""The battery campaign's ONE source of truth — what has run, and what runs next.

Reads `suite/results/results.jsonl` and nothing else. Not a conversation, not a memory, not a
report someone typed. Whatever it prints under `NEXT:` is the next action; when a chat message and
this tool disagree, this tool is right. `docs/goals/battery-goal.md` is the campaign it drives.

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
import time
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


def prompt_rev(r: dict | None) -> str:
    """The task-prompt revision a row was earned against — the last `pN` token in its note."""
    if not r:
        return ""
    toks = [w for w in str(r.get("note", "")).split() if len(w) > 1 and w[0] == "p" and w[1:].isdigit()]
    return toks[-1] if toks else ""


def prior_cell(rs: list[dict], arm: str, model: str, task: str, current: dict | None) -> dict | None:
    """The PREVIOUS standing row for this cell — simply the run before the one being shown.

    Not keyed on the prompt revision. It was, and the operator's call is that the distinction is too
    pedantic to carry in the grid: a run is a run, and the question the grid answers is "did this
    cell get better or worse than last time". Where wording changed, the note on the row still
    records the revision for anyone who needs it."""
    seen = [r for r in rs
            if r.get("model") == model and r.get("task") == task
            and f" {arm} " in f" {str(r.get('note', ''))} " and not r.get("superseded")]
    if current is not None and seen and seen[-1] is current:
        seen = seen[:-1]
    return seen[-1] if seen else None


def delta_of(now: dict | None, before: dict | None) -> str:
    """`(+20)` / `(-40)` / `(0)` in PERCENTAGE POINTS, or "" with nothing to compare against.

    Points, not checks: the cell already reads as a percentage, and the two units side by side
    ("80% (+1)") invite the reader to do arithmetic that does not work — tasks carry different check
    counts, so one check is 20 points on a five-check task and 25 on a four-check one."""
    if not now or not before:
        return ""
    a, b = pct(now), pct(before)
    if a is None or b is None:
        return ""
    d = a - b
    return " (0)" if abs(d) < 0.5 else f" ({d:+.0f})"


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


def pct(r: dict | None) -> float | None:
    """A task's result as a PERCENTAGE of its own checks.

    Fractions forced every task to carry exactly four checks, which meant splitting work that was
    really three deliverables or merging work that was really six. A percentage frees a task to
    carry as many checks as its work honestly needs; the constraint that remains is the one that
    was actually meant — every check WITHIN a task should cost roughly the same effort."""
    if not r:
        return None
    mx = float(r.get("max_score") or 0)
    return 100.0 * float(r.get("score") or 0) / mx if mx else None


def score_of(r: dict | None) -> str:
    v = pct(r)
    return "—" if v is None else f"{v:.0f}%"


def _n(r: dict | None, key: str) -> str:
    if not r:
        return "—"
    v = r.get(key)
    return "—" if v is None else (f"{v/60:.0f}" if key == "wall_seconds" else str(v))


NOTES_MARKER = "<!-- NOTES — hand-written, preserved across regeneration -->"


def _badge(avg_pct: float) -> str:
    """Banded on the percentage, so the bands mean the same thing whatever a task's
    check count is."""
    return ("🟢" if avg_pct >= 87.5 else "🟡" if avg_pct >= 62.5
            else "🟠" if avg_pct >= 37.5 else "🔴")


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


def _overall_pct(cs: list[dict]) -> float | None:
    """Checks passed over checks attempted, across a set of cells. The same weighting the headline
    uses, factored out so the total and its delta cannot compute it two different ways (#12)."""
    total = sum(float(c.get("max_score") or 0) for c in cs)
    return 100.0 * sum(float(c.get("score") or 0) for c in cs) / total if total else None


def _overall_delta(rs: list[dict], arm: str, model: str, cells: list[dict | None]) -> str:
    """The total's movement since the previous run, in percentage points.

    ON THE SAME CELLS, BOTH SIDES. Part-way through a cycle a model has current rows for the
    languages that have run and prior rows for all six; comparing today's three against last time's
    six is two different questions subtracted. A cell counts only when it has BOTH rows.
    """
    pairs = [(c, prior_cell(rs, arm, model, tk, c)) for c, tk in zip(cells, TASKS) if c]
    pairs = [(c, p) for c, p in pairs if p]
    if not pairs:
        return ""
    now, before = _overall_pct([c for c, _ in pairs]), _overall_pct([p for _, p in pairs])
    if now is None or before is None:
        return ""
    d = now - before
    return " (0)" if abs(d) < 0.5 else f" ({d:+.0f})"


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
        # OVERALL is checks-passed over checks-attempted, not the mean of the percentages. A task
        # carrying six checks should weigh more in the headline than one carrying three — that is
        # the point of letting check counts differ.
        overall = _overall_pct(have) or 0.0
        ranked.append((overall, -sum(float(c.get("wall_seconds") or 0) for c in have),
                       m, cells, have))
    for overall, _t, m, cells, have in sorted(ranked, key=lambda x: (-x[0], -x[1])):
        # …WITH THE MOVEMENT SINCE THE PREVIOUS RUN OF THIS CELL, in percentage points, matching the
        # unit the cell is already written in.
        def _with_delta(c, tk):
            if not c:
                return "·"
            return score_of(c) + delta_of(c, prior_cell(rs, arm, m, tk, c))
        got = " | ".join(_with_delta(c, tk) for c, tk in zip(cells, TASKS))
        tok = [c["avg_tok_s"] for c in have if c.get("avg_tok_s")]
        rate = f"{sum(tok) / len(tok):.1f}" if tok else "—"
        out.append(f"| {_badge(overall)} {m} | {got} | **{overall:.0f}%**"
                   f"{_overall_delta(rs, arm, m, cells)} | {rate} "
                   f"| {_avg(have, 'wall_seconds', 1 / 60)} | {_avg(have, 'calls')} |")
    if len(out) == 2:
        out.append("| _no runs yet_ |" + " |" * (len(TASKS) + 3))
    return out


def _stamp(rs: list[dict], now: float | None = None) -> str:
    """`Last updated` — the time this file was WRITTEN, and the newest row it was written FROM.

    Both, because either alone misleads. A regeneration time says the writer ran, not that anything
    happened: the report rewrites itself after every cell, so a fresh timestamp over an unchanged
    grid reads as progress that did not occur. The newest row's time says when the data last moved,
    which is the question someone glancing at the file is actually asking — a long cell can leave an
    hour between them, and that gap is information, not an error.
    """
    fmt = "%Y-%m-%d %H:%M"
    written = time.strftime(fmt, time.localtime(now if now is not None else time.time()))
    latest = max((r for r in rs if r.get("started")), key=lambda r: r["started"], default=None)
    if latest is None:
        return f"**Last updated {written}** — no scored rows yet."
    scored = time.strftime(fmt, time.localtime(latest["started"] + (latest.get("wall_seconds") or 0)))
    return (f"**Last updated {written}** — newest row `{latest.get('run_id', '?')}`, "
            f"scored {scored}.")


def report(rs: list[dict], now: float | None = None) -> str:
    """Render the campaign tables. Numbers come from results.jsonl every time; the prose below
    NOTES_MARKER is carried over untouched, because a finding is not derivable from a score."""
    out = ["# Battery campaign — what the assists are worth, across six languages", "",
           _stamp(rs, now), "",
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
    out += ["",
            "Every number carries its movement since that cell's previous run, in percentage points.",
            "The **total** is checks passed over checks attempted across the row — a six-check task",
            "weighs more than a three-check one — and its delta is computed only over cells that have",
            "both a current and a previous run, so a part-finished cycle compares like with like."]

    pairs = [(t, m, cell(rs, "BASE", m, t), cell(rs, "CRIA", m, t)) for t in TASKS for m in MODELS]
    pairs = [(t, m, b, c) for t, m, b, c in pairs if b and c]
    if pairs:
        out += ["", "## What the assists were worth", "",
                "Δ is in percentage POINTS. Read it next to the calls and minutes columns — a gain",
                "bought with 15× the calls is not the same result as one bought with fewer",
                "(`docs/goals/battery-goal.md`).", "",
                "| task | language | model | BASE | CRIA | Δ | calls B→C | min B→C |",
                "|---|---|---|---|---|---|---|---|"]
        for t, m, b, c in pairs:
            d = (pct(c) or 0) - (pct(b) or 0)
            out.append(f"| {t} | {language(t)} | {m} | {score_of(b).strip()} | "
                       f"{score_of(c).strip()} | {f'**{d:+.0f}**' if round(d) else '0'} | "
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
    print(f"{'task':<20}{'model':<19}{'BASE':>7}{'CRIA':>7}{'Δ':>6}")
    print("-" * 59)
    todo: list[tuple[str, str, str]] = []
    filled = 0
    for task in TASKS:
        for model in MODELS:
            b, c = cell(rs, "BASE", model, task), cell(rs, "CRIA", model, task)
            delta = ""
            if b and c:
                delta = f"{(pct(c) or 0) - (pct(b) or 0):+.0f}"
            print(f"{task:<20}{model:<19}{score_of(b):>7}{score_of(c):>7}{delta:>6}")
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
        if len(have) >= 2 and all((pct(b) or 0) == 0 for b in have):
            print(f"\nNEXT: VALIDATE {task}   "
                  f"({len(have)} baseline runs, every one 0/4 — prove the verifier is satisfiable)")
            print(f"      read suite/tasks/{task}/verify.py against suite/tasks/{task}/prompt.txt,")
            print(f"      then solve it by hand in a copy of the seed and score that. See the")
            print(f"      'largely unproven' section of docs/goals/battery-goal.md.")
            return 1

    # A CRIA run that LOST to its BASE twin is the campaign's whole point; walk it before running more.
    for task in TASKS:
        for model in MODELS:
            b, c = cell(rs, "BASE", model, task), cell(rs, "CRIA", model, task)
            if b and c and (pct(c) or 0) < (pct(b) or 0) and not walked(str(c.get("run_id"))):
                print(f"\nNEXT: WALK {c.get('run_id')}   "
                      f"(CRIA {score_of(c)} lost to BASE {score_of(b)} — cria made it worse)")
                print(f"      python3 suite/walk.py {str(c.get('capture_dir','')).split('/')[-1]} "
                      f"--out /tmp/walk-{model}-{task}")
                print(f"      python3 suite/reasoner_audit.py "
                      f"{str(c.get('capture_dir','')).split('/')[-1]} --bad")
                return 1

    if not todo:
        print("\nNEXT: NOTHING — campaign complete. Write the closing summary per docs/goals/battery-goal.md.")
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
