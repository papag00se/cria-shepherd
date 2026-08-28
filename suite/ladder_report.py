#!/usr/bin/env python3
"""Write the ladder's follow-along report — GENERATED, never hand-written.

    python3 suite/ladder_report.py            # regenerate docs/audits/ladder-report.md
    python3 suite/ladder_report.py --score    # ...and measure the in-flight workspace right now

Every number in the report is read from disk or the process table at generation time: the results
rows, the walk file, `ps`, and — with `--score` — the live workspace scored by the real verifier on
a COPY. Nothing is carried over from anything anyone said.

That is the whole point. A progress report an assistant types is a progress report an assistant can
get wrong, and this one already has been: "Cell 5 running next" was written for a run that was never
started, and nothing contradicted it for hours. A generated report cannot make that claim.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SUITE = Path(__file__).resolve().parent
sys.path.insert(0, str(SUITE))
import ladder_status as L                                        # noqa: E402
from run import observe_snapshot                                  # noqa: E402

REPORT = SUITE.parent / "docs" / "audits" / "ladder-report.md"
TASK_DIR = SUITE / "tasks"


def live_workspace(task: str, model: str):
    """The in-flight run's workspace. run.py names it `suite-<run_id>-<random>`, and run_id leads
    with task_model, so the newest match is this run's."""
    hits = sorted(Path("/tmp").glob(f"suite-{task}_{model}_*"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def proc_start(model: str):
    """When the in-flight runner actually started — from the process, not from a memory of it."""
    try:
        out = subprocess.run(["ps", "-eo", "pid,etimes,args"], capture_output=True, text=True,
                             timeout=30).stdout
    except Exception:  # noqa: BLE001
        return None
    for line in out.splitlines():
        parts = line.split()
        # `ps -eo pid,etimes,args` -> [pid, etimes, interpreter, script, ...]. The script is at
        # index 3, not 2; reading 2 matched nothing and the report showed every run as "0 min
        # elapsed", which would have put the next checkpoint permanently 15 minutes away.
        if len(parts) >= 6 and parts[3].endswith("suite/run.py") and model in parts:
            return int(parts[1])
    return None


def fmt_score(s, mx=4):
    return "—" if s is None else f"{s:.0f}/{mx:.0f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", action="store_true",
                    help="score the in-flight workspace now (runs the verifier on a copy, ~30s)")
    ap.add_argument("--language", default=L.LANGUAGES[0][0])
    args = ap.parse_args()

    task = dict(L.LANGUAGES)[args.language]
    cells, running = L.state_for(task)
    rows = L.rows(task)
    now = datetime.now(timezone.utc).astimezone()

    out = []
    w = out.append
    w("# Language ladder — live report")
    w("")
    w(f"**Generated** {now:%Y-%m-%d %H:%M:%S %Z} by `python3 suite/ladder_report.py` · "
      f"**do not hand-edit** — every value here is read from disk or `ps` at generation time.")
    w("")
    w(f"Goal: **{args.language}** (`{task}`), {L.MILESTONE_MINUTES} minutes per deliverable. "
      f"A model repeats until it scores 4/4, then the next one starts.")
    w("")
    w("Authority: `python3 suite/ladder_status.py` — 0 = language complete, 1 = work remains, "
      "2 = a run is in flight.")
    w("")

    # ---- what is happening RIGHT NOW
    w("## Now")
    w("")
    if running:
        elapsed = proc_start(running)
        mins = (elapsed or 0) / 60
        due = int(mins // L.MILESTONE_MINUTES) + 1
        nxt = due * L.MILESTONE_MINUTES
        w(f"**RUNNING — {running}**, {mins:.0f} min elapsed.")
        w("")
        w(f"| next checkpoint | at | must hold |")
        w(f"|:--|--:|:--|")
        w(f"| milestone {due} | {nxt} min | {min(due, 4)}/4 |")
        w("")
        if args.score:
            ws = live_workspace(task, running)
            if ws:
                parts = observe_snapshot(ws, TASK_DIR / task)
                w("**Observed just now** — the verifier run against a copy of the live workspace. "
                  "Per-deliverable observations only: there is no aggregate score here, because an "
                  "all-or-nothing count of deliverables is not what this suite measures.")
                w("")
                if parts:
                    w("| deliverable | | detail |")
                    w("|:--|:--:|:--|")
                    for k, v in parts.items():
                        w(f"| {k} | {'🟢' if v.get('ok') else '🔴'} | {str(v.get('detail',''))[:90]} |")
                    w("")
            else:
                w("_Workspace not located — cannot measure._")
                w("")
    else:
        live = [c for c in cells if not c["passed"] and not c["blocked"]]
        to_walk = [c for c in cells if c["needs_walk"]]
        if not live:
            w("**Nothing running. The language is COMPLETE.**")
        elif to_walk:
            w(f"**Nothing running.** Next action: **walk** `{to_walk[0]['next_walk']}` "
              f"(capture `{to_walk[0]['next_walk_capture']}`), then write "
              f"`## {to_walk[0]['next_walk']}` into `docs/audits/ladder-walk.md`.")
        else:
            w(f"**Nothing running.** Next action: **run** `{live[0]['model']}` "
              f"(attempt {live[0]['attempts'] + 1}).")
        w("")

    # ---- the ladder
    w("## Ladder")
    w("")
    w("| # | model | params | architecture | kind | planner | tries | best | state |")
    w("|--:|:--|:--|:--|:--|:--|--:|:--:|:--|")
    for i, c in enumerate(cells, 1):
        st = ("🔵 RUNNING" if c["running"] else "🟢 PASSED" if c["passed"] else
              "⛔ BLOCKED" if c["blocked"] else "📖 needs walk" if c["needs_walk"] else
              "⬜ not started" if not c["attempts"] else "🔁 ready to rerun")
        w(f"| {i} | {c['model']} | {c['params']} | `{c['arch']}` | {c['kind']} | "
          f"{c['planner']} | {c['attempts']} | {fmt_score(c['best'])} | {st} |")
    w("")

    # ---- every attempt, with its milestone trail
    w("## Attempts")
    w("")
    if not rows:
        w("_No runs recorded yet._")
    else:
        w("| started | model | score | terminal | milestones | calls | tok/s | run id |")
        w("|:--|:--|:--:|:--|:--|--:|--:|:--|")
        for r in sorted(rows, key=lambda r: r.get("started") or 0):
            ms = r.get("milestones") or []
            trail = " ".join(
                f"{m['at_minutes']}m:{'' if m.get('score') is None else int(m['score'])}"
                f"{'✓' if m.get('ok') else '✗'}" for m in ms) or "—"
            started = time.strftime("%m-%d %H:%M", time.localtime(r.get("started") or 0))
            w(f"| {started} | {r['model']} | {fmt_score(r.get('score'), r.get('max_score') or 4)} | "
              f"{r.get('terminal','?')} | {trail} | {r.get('calls','—')} | "
              f"{r.get('avg_tok_s') or '—'} | `{r.get('run_id','')}` |")
    w("")

    # ---- what changed in cria while the ladder has been running
    # The regression campaign (REGRESSION1) supersedes the ladder as the live activity; the ladder
    # table above stays as the baseline record. This section is the campaign's own truth tool,
    # embedded verbatim — never a re-count.
    try:
        camp = subprocess.run([sys.executable, str(SUITE / "regression_status.py")],
                              capture_output=True, text=True, timeout=30).stdout.strip()
        if camp:
            w("## Regression campaign (REGRESSION1)")
            w("")
            w("```")
            w(camp)
            w("```")
            w("")
            w("Operator report: [`regression-report.md`](regression-report.md) · authority: "
              "`python3 suite/regression_status.py`.")
            w("")
    except Exception:  # noqa: BLE001
        pass

    w("## Fixes landed during the ladder")
    w("")
    try:
        log = subprocess.run(["git", "log", "--oneline", "-15", "--", "cria/", "suite/"],
                             capture_output=True, text=True, timeout=30,
                             cwd=str(SUITE.parent)).stdout.strip()
        w("```")
        w(log or "(none)")
        w("```")
    except Exception:  # noqa: BLE001
        w("_git log unavailable_")
    w("")
    w("---")
    w("")
    w("Walk records — one per failed run, with the four questions and the verdict — are in "
      "[`ladder-walk.md`](ladder-walk.md).")
    w("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(out))
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    main()
