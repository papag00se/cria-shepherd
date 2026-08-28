#!/usr/bin/env python3
"""Score a finished cell on USEFULNESS — "was real work done?" — instead of only on perfection.

THE QUESTION CHANGED, at the operator's direction. The strict verifier answers "did the coder get
everything absolutely right, with a little room?" and returns a binary per deliverable. That is not
the question this campaign is trying to answer. The question is **can a cria model be useful in
getting real work done** — and someone who receives a complete, correct, working Rust CLI sitting one
directory below where they asked for it is grateful, not disappointed.

    cycle 4 cell 6, rust-toml-cli x gemma4:  strict 0/4.
    Move the folder up one level, change nothing else:  4/4.

Zero is a false account of that run. Ninety-five is a true one.

## What this is NOT

It is not the verifier being softened, and it does not replace execution with an opinion. The
verifier still BUILDS the thing and RUNS it, and every fact this judge is shown was produced by
running something (#10). The judge never gets to assert that a check passed — it is handed what the
probes observed and asked what that is worth to someone who wanted the work done.

That split is the doctrine's, not an invention here: deterministic code gathers the facts, a
reasoner decides what they mean (#8). The strict score is KEPT on every row beside the new one, and
nothing is overwritten — a question asked later needs both numbers.

## Reaching what the strict probes could not

A verifier that runs `cargo` at the workspace root and finds no `Cargo.toml` has observed one thing:
its own command failed. It has NOT observed whether the project works. So before judging, this
re-probes from the manifest's real directory when the root has none, and reports BOTH results —
"builds and passes in `toml-cli/`, which is not the working directory you were given". The judge then
scores a real fact instead of an absence, and the misplacement is a deduction rather than an
annihilation. #11b: a mechanism that could not reach the thing it was asked about must not answer as
if it had.

## Who judges

The operator's answer, and the right one: the agent running the campaign, with its full toolset —
the same one that can copy an archive, move a directory, re-run the verifier and read the model's own
reasoning. A 9B pointed at the busy GPU produced empty completions, answered in the wrong schema, and
silently changed identity between cells (gemma4 graded cell 1, qwen35 graded cell 8). A grader should
be more reliable than the thing it grades.

So this file stopped trying to be the judge. It does the half that must be mechanical — assemble the
evidence, and RE-PROBE from the project's real directory when the working directory has no manifest —
and then gets out of the way. `--emit` writes the packet; `--record` takes the verdict back.

THE CONFLICT, stated rather than hidden: the agent grading these cells is the same one fixing cria,
and that is a real objection. Three things hold it honest — the rubric is written down and fixed
before the evidence is read (`suite/prompts/usefulness_judge.txt`), every verdict must cite what was
OBSERVED and is stored with its evidence. The strict all-or-nothing score is GONE (operator,
2026-08-27): it was never the question this suite asks, it gated a mid-run kill that ended runs whose
deliverables were nearly finished, and closing the evidence packet with it handed the judge an answer
before it had read anything. The verifier is untouched — its per-deliverable observations are the
evidence every judgement is made from.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


SUITE = Path(__file__).resolve().parent
ROOT = SUITE.parent
RESULTS = SUITE / "results" / "results.jsonl"
CACHE = Path.home() / ".cria" / "suite" / "_usefulness_cache"

# The manifests that mean "a project lives in this directory", by ecosystem. Used only to find where
# a project ACTUALLY is when the workspace root has none — never to judge layout.
MANIFESTS = ("Cargo.toml", "go.mod", "package.json", "pom.xml", "build.gradle", "pyproject.toml",
             "setup.py", "Gemfile", "composer.json", "mix.exs", "build.sbt", "Makefile")

SKIP_DIRS = {".git", "target", "node_modules", "vendor", "__pycache__", ".venv", "venv",
             "build", "dist", "tmp", ".mvn"}


SYSTEM = SUITE / "prompts" / "usefulness_judge.txt"

# The stop-looking line, in THIS judge's schema. See the call site.
ANSWER_NOW = ('You have inspected enough. Answer NOW with ONLY the JSON object: '
              '{"usefulness": <0-100>, "reason": "<two sentences>", '
              '"deductions": [{"points": <n>, "for": "<what cost it>"}]}')


def _tree(ws: Path, limit: int = 400) -> str:
    """Every file the coder produced, with sizes — the disk, not the transcript's idea of it."""
    out = []
    for dirpath, dirnames, filenames in os.walk(ws):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            try:
                out.append(f"  {p.relative_to(ws)} ({p.stat().st_size} B)")
            except OSError:
                continue
            if len(out) >= limit:
                return "\n".join(out) + f"\n  … listing stopped at {limit} entries"
    return "\n".join(out) or "  (empty)"


def project_dirs(ws: Path) -> list[Path]:
    """Directories holding a manifest, nearest first. `[ws]` when the root has one."""
    if any((ws / m).exists() for m in MANIFESTS):
        return [ws]
    found = []
    for dirpath, dirnames, filenames in os.walk(ws):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        if any(m in filenames for m in MANIFESTS):
            found.append(Path(dirpath))
    return sorted(found, key=lambda p: len(p.parts))


def reprobe_elsewhere(ws: Path, task_dir: Path) -> dict | None:
    """Run the task's OWN verifier against the real project directory when the root has no manifest.

    This is the difference between "cria could not build it" and "it builds, one directory down" —
    and only one of those two is a fact about the delivered work. The verifier is unchanged and
    unaware; it is simply pointed at the directory the project is in, in a COPY, so nothing is
    written back into the archive."""
    dirs = project_dirs(ws)
    if not dirs or dirs[0] == ws:
        return None
    where = dirs[0]
    tmp = Path(CACHE) / ("reprobe-" + hashlib.sha1(str(ws).encode()).hexdigest()[:12])
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(where, tmp / "workspace", symlinks=True)
    try:
        r = subprocess.run([sys.executable, str(task_dir / "verify.py"), str(tmp / "workspace")],
                           capture_output=True, text=True, timeout=900)
        verdict = json.loads(r.stdout)
    except Exception:  # noqa: BLE001 — a re-probe that fails tells us nothing; say nothing
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"where": str(where.relative_to(ws)), "verdict": verdict}


def packet_path(run_id: str) -> Path:
    return PACKETS / f"{run_id}.txt"


def save_packet(row: dict) -> Path | None:
    """Freeze this row's evidence packet to disk while the workspace still exists — or None.

    THE WORKSPACE IS THE PERISHABLE PART AND THE PACKET IS NOT. `evidence()` reads the archived
    workspace: it walks the file tree and, when the working directory has no manifest, re-runs the
    verifier from where the project actually is. Once that directory is gone the packet cannot be
    built, and the run can never be judged — the strict score is all that survives it.

    Measured when the operator asked why the inferred score was missing: of 503 recorded runs, 455
    had no usefulness verdict and only 138 of those still had a workspace on disk. **Every one of the
    81 BASE rows that could still be judged had already been judged; the other 57 were unrecoverable.**
    Nothing in `suite/` deletes an archive, so the loss came from outside — which is exactly why this
    cannot depend on the archive surviving. 3.4 GB of workspaces against a few KB of text per run.

    Called at the END of a cell, when the workspace is warm and the verifier has just run. Costs one
    file walk. Best-effort: a packet that cannot be written must never fail a run that finished."""
    try:
        text, _digest = evidence(row, _saved=False)
    except Exception:                                   # noqa: BLE001 — never fail a finished run
        return None
    PACKETS.mkdir(parents=True, exist_ok=True)
    out = packet_path(row["run_id"])
    out.write_text(text)
    return out


def evidence(row: dict, _saved: bool = True) -> tuple[str, str]:
    """`(evidence_text, digest)` — everything the judge is allowed to see, and its fingerprint.

    Prefers the packet frozen at run time (`save_packet`) when the archived workspace is gone, so a
    reaped workspace costs the run its judgeability only if nothing was saved. The digest is always
    recomputed against the CURRENT rubric, so a reworded rubric still invalidates old verdicts."""
    saved = packet_path(row.get("run_id", ""))
    ws_gone = not (Path(row.get("archive") or "") / "workspace").is_dir()
    if _saved and ws_gone and saved.is_file():
        text = saved.read_text(errors="replace")
        stamp = text + "\n\n---RUBRIC---\n" + SYSTEM.read_text()
        return text, hashlib.sha1(stamp.encode("utf-8", "replace")).hexdigest()[:16]
    task_dir = SUITE / "tasks" / row["task"]
    ws = Path(row.get("archive") or "") / "workspace"
    prompt = (task_dir / "prompt.txt").read_text(errors="replace").strip()
    meta = (task_dir / "meta.toml").read_text(errors="replace").strip()
    parts = row.get("verify") or {}

    lines = [f"THE TASK THE CODER WAS GIVEN:\n{prompt}", "", f"TASK METADATA:\n{meta}", ""]
    lines.append("WHAT THE REPO'S OWN VERIFIER OBSERVED, by running things in the working directory:")
    for name, p in parts.items():
        lines.append(f"  [{'met' if p.get('ok') else 'NOT met'}] {name}: {p.get('detail')}")
    if not parts:
        lines.append("  (the verifier produced no parts — it errored or the run left nothing)")

    lines += ["", f"EVERY FILE THE CODER PRODUCED (on disk, with sizes):\n{_tree(ws)}"]

    extra = reprobe_elsewhere(ws, task_dir) if ws.is_dir() else None
    if extra:
        v = extra["verdict"]
        lines += ["", f"THE WORKING DIRECTORY HAS NO PROJECT MANIFEST. There is one in "
                      f"`{extra['where']}/`, so the same verifier was run again from THERE, and "
                      f"observed:"]
        for name, p in (v.get("parts") or {}).items():
            lines.append(f"  [{'met' if p.get('ok') else 'NOT met'}] {name}: {p.get('detail')}")
        lines.append("  The work is real; it is not where the task said to put it.")

    # NO STRICT SCORE IN THE PACKET. It used to close every evidence packet with the all-or-nothing
    # count, which is an anchor the judge cannot help reading as an answer — and it is the measure
    # this suite does not ask about (operator, 2026-08-27). The verifier's per-deliverable
    # observations are above; they are the evidence, and they are all of it.
    lines += ["", f"HOW THE SESSION ENDED: {row.get('terminal')} after {row.get('calls')} model "
                  f"calls and {round((row.get('wall_seconds') or 0) / 60, 1)} minutes."]
    text = "\n".join(lines)
    # The digest covers the RUBRIC as well as the evidence. Keying on evidence alone meant a reworded
    # prompt silently reused every verdict written under the old one — a cache that hides the change
    # it was supposed to make.
    stamp = text + "\n\n---RUBRIC---\n" + SYSTEM.read_text()
    return text, hashlib.sha1(stamp.encode("utf-8", "replace")).hexdigest()[:16]






def parse(text: str) -> dict | None:
    """The judge's JSON, however it wrapped it. None when there is no usable verdict — which is NOT
    scored as zero, it is left unscored, because an unreadable judge is cria's problem and not the
    coder's (#13 fails closed on completion; here it fails to SILENCE)."""
    t = (text or "").strip()
    if "```" in t:
        t = t.split("```")[1].lstrip("json").strip() if len(t.split("```")) > 1 else t
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        d = json.loads(t[i:j + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or "usefulness" not in d:
        return None
    try:
        u = float(d["usefulness"])
    except (TypeError, ValueError):
        return None
    return {"usefulness": max(0.0, min(100.0, u)), "reason": str(d.get("reason") or "").strip(),
            "deductions": d.get("deductions") or []}


VERDICTS = Path.home() / ".cria" / "suite" / "_usefulness"
# The evidence packet, saved AT RUN TIME. See save_packet.
PACKETS = Path.home() / ".cria" / "suite" / "_usefulness_evidence"


def verdict_path(run_id: str) -> Path:
    return VERDICTS / f"{run_id}.json"


def _needs_judging(row: dict) -> bool:
    """True when this row has no verdict, or has one written against DIFFERENT evidence or a
    DIFFERENT rubric.

    THE DIGEST EXISTED AND NOTHING READ IT. `record` stamps every verdict with a hash of the evidence
    AND the rubric text, and its own comment says why: "Keying on evidence alone meant a reworded
    prompt silently reused every verdict written under the old one — a cache that hides the change it
    was supposed to make." But the worklist asked only whether a verdict FILE exists, so a rewritten
    rubric changed nothing — every stale verdict stayed on its row, and the grid went on reporting
    numbers earned under a scale that no longer exists (#11b: a mechanism must reach what it judges).

    Found when the operator replaced the global 0-100 band with per-deliverable scoring, which
    invalidates every verdict in the file. A verdict with no stored digest is treated as stale: it
    predates the stamp, so nothing can vouch for what it was written against."""
    p = verdict_path(row["run_id"])
    if not p.exists():
        return True
    try:
        stored = json.loads(p.read_text()).get("evidence_digest")
    except (OSError, ValueError):
        return True
    return stored != evidence(row)[1]


def pending(rows: list[dict]) -> list[dict]:
    """Cells with an archive and no verdict — the worklist, computed from disk every time.

    THIS IS THE MEMORY. Not a note in a message and not something to hold in mind across 24 cells
    and a compaction: a cell is judged when its verdict file exists, and unjudged otherwise. A run
    that is interrupted, resumed, or picked up by a different session recomputes the same list."""
    return [r for r in rows
            # A SUPERSEDED row measured a rung that was not the one running; the cell re-runs and the
            # replacement is what gets judged. Judging the old one would spend the effort and then
            # attach a verdict to a measurement the grid already ignores.
            if not r.get("superseded")
            and (r.get("archive") or packet_path(r.get("run_id", "")).is_file())
            and _needs_judging(r)
            # …and only when the evidence can still be built: an archive on disk, or a packet frozen
            # at run time. A row with neither is unjudgeable for good and must not sit in the
            # worklist forever pretending otherwise (#5b).
            and ((Path(r.get("archive") or "") / "workspace").is_dir()
                 or packet_path(r.get("run_id", "")).is_file())]


def record(run_id: str, verdict: dict) -> dict:
    """Store a verdict and write its number onto the row."""
    v = dict(verdict)
    v.setdefault("judged_by", "campaign agent, full toolset")
    rows = [json.loads(l) for l in RESULTS.read_text().splitlines() if l.strip()]
    row = next((r for r in rows if r.get("run_id") == run_id), None)
    if row is None:
        raise SystemExit(f"no row for {run_id}")
    v["evidence_digest"] = evidence(row)[1]
    VERDICTS.mkdir(parents=True, exist_ok=True)
    verdict_path(run_id).write_text(json.dumps(v, indent=1))
    out = []
    for r in rows:
        if r.get("run_id") == run_id:
            r = {**r, "usefulness": float(v["usefulness"]),
                 "usefulness_reason": v.get("reason", ""),
                 "usefulness_model": v["judged_by"]}
        out.append(json.dumps(r))
    RESULTS.write_text("\n".join(out) + "\n")
    return v


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("pending", help="cells with an archive and no verdict — the worklist")
    q.add_argument("--since", type=float, default=0.0)
    q.add_argument("--arm")

    e = sub.add_parser("emit", help="print the evidence packet for one cell, then judge it yourself")
    e.add_argument("run_id")

    r = sub.add_parser("record", help="store a verdict (JSON on stdin) and write it onto the row")
    r.add_argument("run_id")

    s_ = sub.add_parser("show", help="the grid, strict beside useful")
    s_.add_argument("--since", type=float, default=0.0)

    args = ap.parse_args()
    rows = [json.loads(l) for l in RESULTS.read_text().splitlines() if l.strip()]

    if args.cmd == "pending":
        want = [r for r in pending(rows)
                if r.get("started", 0) >= args.since
                and (not args.arm or f" {args.arm} " in f" {r.get('note', '')} ")]
        for r in want:
            print(f"{r['run_id']}\t{r['task']}\t{r['model']}\t"
                  f"{r.get('terminal') or ''}")
        if not want:
            print("(nothing pending)")
        return 0

    if args.cmd == "emit":
        row = next((x for x in rows if x.get("run_id") == args.run_id), None)
        if row is None:
            raise SystemExit(f"no row for {args.run_id}")
        print("=" * 78)
        print(SYSTEM.read_text().strip())
        print("=" * 78)
        print(evidence(row)[0])
        return 0

    if args.cmd == "record":
        v = record(args.run_id, json.loads(sys.stdin.read()))
        print(f"{args.run_id}: usefulness {v['usefulness']}")
        return 0

    want = [r for r in rows if r.get("started", 0) >= args.since and "usefulness" in r]
    print(f"{'task':22} {'model':17} {'delivered':>10}")
    for r in want:
        print(f"{r['task']:22} {r['model']:17} {r['usefulness']:9.0f}%")
    if want:
        print(f"{'':22} {'':17} {sum(r['usefulness'] for r in want) / len(want):9.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
