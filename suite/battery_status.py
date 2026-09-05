#!/usr/bin/env python3
"""The battery campaign's ONE source of truth — what has run, and what runs next.

Reads `suite/results/results.jsonl` and nothing else. Not a conversation, not a memory, not a
report someone typed. Whatever it prints under `NEXT:` is the next action; when a chat message and
this tool disagree, this tool is right. `docs/goals/battery-goal.md` is the campaign it drives.

THE QUESTION: for four models across six tasks, how useful is the same model with cria DRIVING
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
NOTE_PREFIX = "BATTERY2"          # what a NEW campaign run is stamped with (battery_run.py imports it)

# EVERY RUN OF A CELL COUNTS, WHATEVER PROMPTED IT. A rerun launched after a weak judgment is still a
# measurement of the same task, model and arm, and `prior_cell` below already states the rule the
# operator settled on: "a run is a run". Reading only the campaign prefix meant the grid ignored the
# reruns launched to improve it — four cells re-run on 08-20 never entered the ranking they were run
# for, and one of them was the best ruby result on record (qwen35, 4/5). The grid is the operator
# view; a measurement it cannot see is a measurement nobody acts on.
COUNTED_PREFIXES = (NOTE_PREFIX, "LOWSCORE", "RERANK")

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
        if str(r.get("note", "")).startswith(COUNTED_PREFIXES):
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
    if not judged(now) or not judged(before):
        return ""
    a, b = pct(now), pct(before)
    if a is None or b is None:
        return ""
    d = a - b
    if abs(d) < 0.5:
        return " (0)"
    # A `~` MEANS THE MOVEMENT IS INSIDE THE NOISE. Measured 2026-08-17 across every repeat in
    # results.jsonl: re-running a cell AT IDENTICAL CODE moves it a median of 25 points, and across
    # all code states the median within-cell spread is 75 of 100. One check flips between runs of
    # the same binary, routinely. So a one-check delta is not evidence of anything, and printing a
    # bare `(+20)` for it states a movement that was never measured (#5b).
    #
    # This cost real work before it was written down: five cells were read as "cria broke a 100%
    # cell", a rust cell as "restored 0 -> 100", and a whole campaign conclusion (60% unassisted vs
    # 54% under cria) rested on one run per cell against a floor bigger than the difference. The
    # mechanism findings from the walks survived that; every score comparison did not.
    #
    # NOT PRINTED IN THE CELL (operator, 2026-08-21). The floor used to prefix a `~` to a delta it
    # covered; the mark is gone from the number because it does not matter to the reader. The
    # measurement it stands on is not gone — `within_noise` below is the same test, and the grid
    # still refuses to BOLD a movement smaller than one check, so a one-check flip does not shout.
    return f" ({d:+.0f})"


MIN_MEANINGFUL_DELTA = 10.0


def within_noise(now: dict | None, before: dict | None) -> bool:
    """Whether two independent usefulness judgments are too close to distinguish confidently."""
    if not now or not before or not judged(now) or not judged(before):
        return False
    a, b = pct(now), pct(before)
    return a is not None and b is not None and abs(a - b) <= MIN_MEANINGFUL_DELTA


def noise_floor(*_rows: dict | None) -> float:
    """Conservative uncertainty band for comparing independent usefulness judgments."""
    return MIN_MEANINGFUL_DELTA


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


def judged(r: dict | None) -> bool:
    """Has this cell received an independent usefulness judgment?"""
    return bool(r) and r.get("usefulness") is not None


def pct(r: dict | None) -> float | None:
    """A cell's number: the USEFULNESS judgement, or None when it has not been judged.

    An unjudged cell has no numeric value; the grid never substitutes another measure."""
    if not r:
        return None
    u = r.get("usefulness")
    return float(u) if u is not None else None


def score_of(r: dict | None) -> str:
    """The cell, badged. `·` when it has not been judged — see :func:`pct`.

    THE BADGE IS ON THE CELL, NOT THE ROW. A row badge colours a model's six-task average, and the
    average is the one number in this grid that never describes anything that happened: this suite's
    per-cell spread runs 1 to 100 for one model on one task across rungs, so the mean sits in a band
    no cell occupied. Reading down a column for a task, or across for a model, is what these grids
    are for — and that reading wants the colour where the evidence is."""
    v = pct(r)
    if v is not None:
        return f"{_badge(v)} {v:.0f}%"
    # UNKNOWN IS NOT ABSENT (#11b). `·` used to mean both "never ran" and "ran, not yet judged", and
    # the second is a cell with a workspace, a capture and evidence on disk — the only thing missing
    # is me. Reading it as empty also let the row average quietly skip it: three unjudged cells took
    # nemotron's level-5 total from 46% to 77%, upward, by removing its worst three.
    return "?" if r else "·"


def _n(r: dict | None, key: str) -> str:
    if not r:
        return "—"
    v = r.get(key)
    return "—" if v is None else (f"{v/60:.0f}" if key == "wall_seconds" else str(v))


NOTES_MARKER = "<!-- NOTES — hand-written, preserved across regeneration -->"


def _badge(avg_pct: float) -> str:
    """Banded on the percentage, so the bands mean the same thing whatever a task's check count is.

    The four bands are quarters, read off the midpoints: 🟢 at or above 87.5, 🟡 62.5, 🟠 37.5,
    🔴 below. On a CELL that reads as: everything the task asked for; most of it, with a real piece
    missing; some of it, worth keeping; and nothing that runs."""
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
    """A set of cells as one number, factored out so the total and its delta cannot compute it two
    different ways (#12).

    Two weightings, because there are two measures. Strict cells are checks-passed over
    checks-attempted, so a task carrying six checks weighs more than one carrying three — that is
    the point of letting check counts differ. A JUDGED cell is a 0-100 verdict on the whole cell, so
    those get one vote each."""
    vals = [v for v in (pct(c) for c in cs) if v is not None]
    return sum(vals) / len(vals) if vals else None


def _pending(cs: list[dict]) -> int:
    """Cells here that RAN and have no verdict yet. The average cannot speak for them."""
    return sum(1 for c in cs if c and pct(c) is None)


def _pct_str(cs: list[dict]) -> str:
    """A set of cells as one number — with the count it is actually over, when that is not all of them.

    AN AVERAGE OVER PART OF A ROW MAY NOT WEAR THE ROW'S NAME. Judging lags running, so a row is
    routinely part-judged, and averaging only what is judged moves the number by whichever cells
    happen to be done. Measured the night the strict fallback was removed: three unjudged cells took
    nemotron's level-5 total from 46% to 77% and the rung's heading from 79% to 88%, upward, purely
    by dropping its three worst. `77% (3/6)` says what it is; `77%` is a false fact (#5b)."""
    v = _overall_pct(cs)
    if v is None:
        return "—"
    ran = [c for c in cs if c]
    got = len(ran) - _pending(ran)
    return f"{v:.0f}%" if got == len(ran) else f"{v:.0f}% ({got}/{len(ran)})"


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
    if abs(d) < 0.5:
        return " (0)"
    # The mark is not printed here either (operator, 2026-08-21) — same reason as :func:`delta_of`.
    # The pooled floor it stood on is kept in the comment because it is the reason a total may be
    # read as more sensitive than any cell in it: the total pools every cell that moved and
    # independent flips partly cancel, so `grain/sqrt(n)` — one check still flipping in each of six
    # cells lands near 8 points, not 20 — is the amount of a total that is not a trend.
    return f" ({d:+.0f})"


def cycle_start(rs: list[dict], arm: str) -> float:
    """When the run currently in the grid began.

    `cycle_run.py` walks the matrix task-major from the top, so the newest run of the FIRST cell —
    `TASKS[0]` x `MODELS[0]` — is the moment this pass started. Everything scored at or after it is
    fresh; everything before it is a row carried over from an earlier pass, which is most of the grid
    for most of a cycle. A restart re-runs that first cell, so the boundary moves with it, which is
    the behaviour you want: after a restart the earlier cells of the abandoned pass ARE stale again.

    Returns 0.0 when the first cell has never run, so nothing is marked fresh rather than everything.
    """
    first = [r for r in rs
             if r.get("model") == MODELS[0] and r.get("task") == TASKS[0]
             and f" {arm} " in f" {str(r.get('note', ''))} " and not r.get("superseded")
             and r.get("started")]
    return float(first[-1]["started"]) if first else 0.0


LEVEL_NAMES = {
    0: "pure proxy — wire translation only",
    1: "TOOL_CALL_FIXES — dialect and template repair",
    2: "SIMPLE_TOOLS — cria's tool menu, lowered to shell",
    3: "CONTEXT_FIXES — floor, trims, dedups, compaction reframing",
    4: "DONE_REFUSALS_ENABLED — refusing a completion CLAIM",
    5: "ASSISTS_ENABLED — steers, periodic gates, detectors, planner",
}


def level_cell(rs: list[dict], level: int, model: str, task: str) -> dict | None:
    """The STANDING row for one ladder cell. Superseded rows are evidence, not results — a cell that
    ran with a higher rung leaking into it measured something other than the rung it claims."""
    for r in reversed(rs):
        if r.get("superseded") or r.get("level") is None:
            continue
        try:
            lvl = int(r["level"])
        except (TypeError, ValueError):
            continue
        if lvl == level and r.get("model") == model and r.get("task") == task:
            return r
    return None


def _level_pct(rs: list[dict], level: int) -> str | None:
    """The rung's own headline: every cell it ran, pooled.

    Checks-passed over checks-attempted across the whole grid, the same measure `total` uses per
    model — NOT the mean of the four model totals. A rung where one model ran six cells and another
    ran one would otherwise weigh those equally. Returns None while the rung has no cells, so the
    heading can stay silent rather than print 0%."""
    have = [c for m in MODELS for t in TASKS if (c := level_cell(rs, level, m, t))]
    return _pct_str(have) if have else None


def _level_grid(rs: list[dict], level: int) -> list[str]:
    """One row per model, one column per language, for a single rung of the ladder.

    NO DELTA COLUMN, deliberately. An arm grid compares a cell against its own previous run, which
    is the same question asked twice. A rung is not a re-run of the rung below it: levels 0 and 1
    scored 91 and 41 for gemma4 while five of six cells ran a byte-identical code path, because the
    mechanism level 1 adds fired exactly once. Printing that as a -50 delta would assert a rung
    difference the data does not contain. The rungs are laid out to be read against each other by
    eye, with the per-cell noise stated once, below."""
    langs = [language(t) for t in TASKS]
    out = [f"| model | " + " | ".join(langs) + " | total | avg min | avg calls |",
           "|---|" + "---|" * len(TASKS) + "---:|---:|---:|"]
    # ALWAYS IN `MODELS` ORDER, never ranked. Six of these tables sit one under another and the
    # question they exist to answer is "what did THIS model do as the rung changed" — which means
    # reading straight down a column. Sorting each table by its own score moves a model between
    # rows from one rung to the next, and the column stops being one model's story. A model with no
    # cells yet keeps its row, so the rows line up before the grid is full.
    for m in MODELS:
        cells = [level_cell(rs, level, m, t) for t in TASKS]
        have = [c for c in cells if c]
        got = " | ".join(score_of(c) if c else "·" for c in cells)
        if not have:
            out.append(f"| {m} | {got} | · | — | — |")
            continue
        out.append(f"| {m} | {got} | {_pct_str(have)} "
                   f"| {_avg(have, 'wall_seconds', 1 / 60)} | {_avg(have, 'calls')} |")
    return out


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
                       m, cells, have))  # rank by what IS judged; the cell prints its own state
    started_at = cycle_start(rs, arm)
    for _rank, _t, m, cells, have in sorted(ranked, key=lambda x: (-x[0], -x[1])):
        # …WITH THE MOVEMENT SINCE THE PREVIOUS RUN OF THIS CELL, in percentage points, matching the
        # unit the cell is already written in.
        #
        # BOLD MEANS FRESH. A cycle takes hours and the grid is read throughout it, so at any moment
        # some cells are from the run in progress and the rest are carried from the last one. Without
        # the distinction a stale cell and a re-measured one look identical, and the report gets read
        # as if the whole grid moved. The TOTAL is never bold: it mixes fresh and carried cells by
        # construction, so emphasis there would claim a freshness it does not have.
        def _with_delta(c, tk):
            if not c:
                return "·"
            text = score_of(c) + delta_of(c, prior_cell(rs, arm, m, tk, c))
            fresh = started_at and float(c.get("started") or 0) >= started_at
            return f"**{text}**" if fresh else text
        got = " | ".join(_with_delta(c, tk) for c, tk in zip(cells, TASKS))
        tok = [c["avg_tok_s"] for c in have if c.get("avg_tok_s")]
        rate = f"{sum(tok) / len(tok):.1f}" if tok else "—"
        out.append(f"| {m} | {got} | {_pct_str(have)}"
                   f"{_overall_delta(rs, arm, m, cells)} | {rate} "
                   f"| {_avg(have, 'wall_seconds', 1 / 60)} | {_avg(have, 'calls')} |")
    if len(out) == 2:
        out.append("| _no runs yet_ |" + " |" * (len(TASKS) + 3))
    return out


def repeat_evidence(rs: list[dict]) -> str:
    """One sentence stating how far a cell moves when NOTHING changes — computed from the rows, so
    the claim behind every `~` in this report is checkable and stays current (#12).

    A group is the same cell, same arm, same commit, run more than once. That is the only comparison
    in which a difference can be attributed to the run rather than to the code."""
    import collections
    import statistics
    groups = collections.defaultdict(list)
    for r in rs:
        note = str(r.get("note", ""))
        if r.get("usefulness") is None:
            continue
        tok = [w for w in note.split()
               if len(w) == 7 and all(ch in "0123456789abcdef" for ch in w)]
        if not tok:
            continue
        arm = "BASE" if " BASE " in f" {note} " else "CRIA"
        groups[(r.get("task"), r.get("model"), arm, tok[-1])].append(float(r["usefulness"]))
    spreads = [max(v) - min(v) for v in groups.values() if len(v) > 1]
    if not spreads:
        return ""
    n = len(spreads)
    return (f"Measured on this data: {n} cell{'' if n == 1 else 's'} "
            f"{'was' if n == 1 else 'were'} run more than once AT IDENTICAL CODE, and the median "
            f"spread between those runs is {statistics.median(spreads):.0f} points "
            f"(largest {max(spreads):.0f}). ")


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
        return f"**Last updated {written}** — no completed rows yet."
    finished = time.strftime(fmt, time.localtime(latest["started"] + (latest.get("wall_seconds") or 0)))
    return (f"**Last updated {written}** — newest row `{latest.get('run_id', '?')}`, "
            f"finished {finished}.")


def _ladder_banner(rs: list[dict]) -> list[str]:
    """A standing notice, written by the GENERATOR so it survives every regeneration, that the two
    arms below have been superseded by the engagement ladder.

    The BASE arm was never assists-off. Counting events inside its own 24 run windows: tool-menu
    curation 1,011, write-proxy translation 980, indicator stripping 991, reasoning-call repair 333,
    context focus-trim 514, harness-compaction reframing 136, and the DROP-OLDEST context floor 54.
    All of it ran in both arms, so every Δ in this file measures the loop layer alone and says
    nothing about the other five sixths of cria. A reader who does not know that will read these
    tables as "what cria is worth", which is the one thing they cannot tell them.
    """
    lad = [r for r in rs if r.get("level") is not None and not r.get("superseded")]
    if not lad:
        return []
    levels = sorted({int(r["level"]) for r in lad})
    return [
        "> **THE TWO-ARM COMPARISON IS RETIRED.** `[engagement] drive` on/off governed only the LOOP —",
        "> planner, steers, gates, critics, completion judging. Tool-menu curation, write-proxy",
        "> translation, template repair and the drop-oldest context floor ran in BOTH arms, so the arm",
        "> called \"assists OFF\" never was. Counted inside its own 24 run windows: tool menu 1,011",
        "> fires, write proxy 980, reasoning-call repair 333, focus-trim 514, context floor 54. Those",
        "> deltas measured one sixth of cria and were read as all of it.",
        ">",
        f"> The ladder below replaces it: six cumulative levels, 0 (pure proxy) to 5 (everything),",
        f"> **{len(lad)} cells in across levels {levels[0]}-{levels[-1]}**. Per-cell findings:",
        "> Status: `python3 suite/engagement_status.py`.",
        ">",
        "> The old arm rows stay in `results.jsonl` and in *Every run* below. The six-language history",
        "> further down is what the ladder is built to price — gemma4 drops finishing work, qwen35",
        "> leaves work unfinished, ternary-bonsai cannot satisfy a compiler, nemotron-elastic quits.",
        "",
    ]


def report(rs: list[dict], now: float | None = None) -> str:
    """Render the campaign tables. Numbers come from results.jsonl every time; the prose below
    NOTES_MARKER is carried over untouched, because a finding is not derivable from a score."""
    out = ["# Battery — the engagement ladder", "",
           _stamp(rs, now), "",
           "Tables only. Status: `python3 suite/engagement_status.py`.", "",
           "`[engagement] level = 0..5`, each rung implying every rung below it. "
           "`·` = not run. Superseded cells are excluded and re-run.", ""]
    for _lvl in range(0, 6):
        _pct = _level_pct(rs, _lvl)
        _hd = f"### Level {_lvl} — {LEVEL_NAMES[_lvl]}"
        out += [f"{_hd} — {_pct}" if _pct else _hd, ""]
        out += _level_grid(rs, _lvl)
        out += [""]
    out += ["",
            "Every number is a judgement of how much of the task was actually delivered. `?` = the "
            "cell RAN and is waiting on a verdict; `·` = it never ran. A total reading `77% (3/6)` "
            "is an average over the judged cells only and cannot speak for the rest of the row.", ""]
    # TABLES ONLY (operator, 2026-08-24): "I really don't need that document to have anything
    # else in it but the tables. I look at nothing else."
    return "\n".join(out) + "\n"


def write_report(rs: list[dict]) -> Path:
    path = SUITE.parent / "docs" / "audits" / "battery-report.md"
    body = report(rs)
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
            # THROUGH delta_of, not subtracted here. This line had its own subtraction and so
            # skipped both guards the one owner carries: the cross-measure block (strict minus
            # judged is not movement in anything) and the `~` noise mark. Two copies of an
            # arithmetic is two places for it to be wrong, and this copy was.
            delta = delta_of(c, b).strip().strip("()")
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

    # A CRIA run that LOST to its BASE twin is the campaign's whole point; walk it before running
    # more — BUT ONLY BY MORE THAN THE NOISE FLOOR. A one-check gap between two single runs is not
    # a loss, and this line used to send the walker after one: it named
    # `shipping-rates-rb x gemma4` as "CRIA 25% lost to BASE 80%" on a cell whose own fifteen
    # standing runs range 0-100 with a mean of 47. A day of walking noise is a day not spent on the
    # cells where the gap is real, so the selector now has to clear the same bar the grid does.
    for task in TASKS:
        for model in MODELS:
            b, c = cell(rs, "BASE", model, task), cell(rs, "CRIA", model, task)
            gap = (pct(b) or 0) - (pct(c) or 0) if (b and c) else 0.0
            if b and c and gap > noise_floor(c, b) and not walked(str(c.get("run_id"))):
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
