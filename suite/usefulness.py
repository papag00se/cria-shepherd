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

## Determinism

A model judge drifts. Every score is written with the model that produced it, the evidence digest it
saw, and its reasoning, so a number can always be traced and re-derived. Re-scoring an unchanged
archive with an unchanged prompt is a cache hit, not a fresh opinion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
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


def evidence(row: dict) -> tuple[str, str]:
    """`(evidence_text, digest)` — everything the judge is allowed to see, and its fingerprint."""
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
        lines.append(f"  (strict score from that directory: {v.get('score')}/{v.get('max_score')})")
        lines.append("  The work is real; it is not where the task said to put it.")

    lines += ["", f"HOW THE SESSION ENDED: {row.get('terminal')} after {row.get('calls')} model "
                  f"calls and {round((row.get('wall_seconds') or 0) / 60, 1)} minutes.",
              f"STRICT SCORE (all-or-nothing per deliverable): "
              f"{row.get('score')}/{row.get('max_score')}"]
    text = "\n".join(lines)
    # The digest covers the RUBRIC as well as the evidence. Keying on evidence alone meant a reworded
    # prompt silently reused every verdict written under the old one — a cache that hides the change
    # it was supposed to make.
    stamp = text + "\n\n---RUBRIC---\n" + SYSTEM.read_text()
    return text, hashlib.sha1(stamp.encode("utf-8", "replace")).hexdigest()[:16]


def ask(system: str, user: str, base_url: str, model: str, timeout: int = 900) -> str:
    body = json.dumps({"model": model, "temperature": 0.0, "stream": False, "max_tokens": 2048,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    key = os.environ.get("USEFULNESS_API_KEY")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


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


def score_row(row: dict, base_url: str, model: str, *, refresh: bool = False) -> dict | None:
    ev, digest = evidence(row)
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{row['run_id']}.{digest}.json"
    if cached.exists() and not refresh:
        return json.loads(cached.read_text())
    verdict = parse(ask(SYSTEM.read_text(), ev, base_url, model))
    if verdict is None:
        return None
    verdict.update({"model": model, "evidence_digest": digest})
    cached.write_text(json.dumps(verdict, indent=1))
    return verdict


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-url", default=os.environ.get("USEFULNESS_BASE_URL",
                                                         "http://127.0.0.1:18084"))
    ap.add_argument("--model", default=os.environ.get("USEFULNESS_MODEL", "cria"))
    ap.add_argument("--run-id", action="append", help="score only these run_ids")
    ap.add_argument("--since", type=float, default=0.0, help="rows started at/after this epoch")
    ap.add_argument("--arm", help="only rows whose note carries this arm (BASE / CRIA)")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache")
    ap.add_argument("--dry-run", action="store_true", help="print the evidence and stop")
    args = ap.parse_args()

    rows = [json.loads(l) for l in RESULTS.read_text().splitlines() if l.strip()]
    want = [r for r in rows
            if (not args.run_id or r.get("run_id") in args.run_id)
            and (r.get("started", 0) >= args.since)
            and (not args.arm or f" {args.arm} " in f" {r.get('note', '')} ")
            and r.get("archive")]
    if not want:
        print("no rows matched", file=sys.stderr)
        return 1

    if args.dry_run:
        print(evidence(want[-1])[0])
        return 0

    scored = {}
    for r in want:
        v = score_row(r, args.base_url, args.model, refresh=args.refresh)
        if v is None:
            print(f"  {r['run_id']}: judge produced no usable verdict — left unscored")
            continue
        scored[r["run_id"]] = v
        strict = f"{r.get('score')}/{r.get('max_score')}"
        print(f"  {r['task']:20} {r['model']:17} strict {strict:>7}  →  useful "
              f"{v['usefulness']:5.1f}%  {v['reason'][:90]}")

    # Written back onto the row, BESIDE the strict score. Nothing is overwritten: a question asked
    # later needs both numbers, and run evidence is never deleted.
    if scored:
        out = []
        for r in rows:
            if r.get("run_id") in scored:
                r = {**r, "usefulness": scored[r["run_id"]]["usefulness"],
                     "usefulness_reason": scored[r["run_id"]]["reason"],
                     "usefulness_model": scored[r["run_id"]]["model"]}
            out.append(json.dumps(r))
        RESULTS.write_text("\n".join(out) + "\n")
        print(f"\nwrote usefulness onto {len(scored)} row(s); strict scores untouched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
