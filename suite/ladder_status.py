#!/usr/bin/env python3
"""Ground truth for the LANGUAGE LADDER: which model is up, what it scored, what happens next.

The ladder's rule is simple and its state is entirely on disk: one language, one model at a time,
that model repeats until it scores full marks, then the next model starts. Nothing here is read from
a conversation — a goal that judges its own progress from the assistant's narration inherits whatever
the assistant says, and that has already cost a day: "Cell 5 running next" was written for a run that
was never started, and nothing contradicted it for hours.

    python3 suite/ladder_status.py           # human-readable
    python3 suite/ladder_status.py --json     # machine-readable

Exit codes: 0 = the language is complete, 1 = work remains, 2 = a run is in flight, 3 = blocked.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"
WALK = SUITE.parent / "docs" / "audits" / "ladder-walk.md"

NOTE_PREFIX = "LADDER"
MILESTONE_MINUTES = 15

# The ladder's order, and the ONE place it is defined. Dense first, largest first — a proven-capable
# model failing means cria is at fault, which is the cheaper thing to debug; a 760M-active model
# failing tells you almost nothing until the big ones pass. Flip `reverse=` in your head by editing
# this list; nothing else reads an ordering.
#
# `planner` was the OPERATOR'S HYPOTHESIS: dense models cope with the planner off, MoEs need it on.
# It is recorded here so the ladder GENERATES the evidence rather than assuming it — every row carries
# the setting it ran under. THE EVIDENCE IS NOW TWO MoEs AGAINST IT. mellum2 spent sixteen planner-on
# runs peaking at 3/4 and passed 4/4 with the planner off; zaya1 never reached the coder once in four
# planner-on attempts. nemotron-elastic passed 4/4 planner-ON at the first try, so this is not
# "the planner is bad" — it is that driving a plan is itself a capability, and the smallest models
# spend the whole budget on it instead of on the work.
# dense/MoE is read from each GGUF's own header (general.architecture + <arch>.expert_count /
# expert_used_count), NOT from a model card or a name. fabliq was on the dense list until the header
# was actually read: `lfm2moe`, 32 experts, 4 active — an LFM2.5-8B-A1B. docs/model-settings.md had
# labelled the other three MoEs and left fabliq unlabelled, which reads as dense by omission.
LADDER = [
    # name,              params,        arch/experts,        kind,    planner
    ("ternary-bonsai",   "27B",         "qwen35",            "dense", "off"),
    ("gemma4",           "12B",         "gemma4",            "dense", "off"),
    ("qwythos",          "9B",          "qwen35",            "dense", "off"),
    ("qwopus",           "9B",          "qwen35",            "dense", "off"),
    ("ornith",           "9B",          "qwen35",            "dense", "off"),
    ("mellum2",          "12B/A2.5B",   "mellum 64/8",       "moe",   "off"),  # flipped 2026-08-02 — see docs/audits/ladder-walk.md (16 planner-on runs peaked at 3/4 over 27-60 min; the first planner-off run reached the same score in 3.9 min and 53 calls, with none of the plan-side faults)
    ("nemotron-elastic", "12B/A2B",     "nemotron_h_moe 128/6", "moe", "on"),
    ("zaya1",            "8.4B/A760M",  "zaya 16/1",         "moe",   "off"),  # flipped 2026-08-02 — four planner-on attempts, the coder reached ZERO times. 20260801T211548 spent all fifteen minutes in the planner inventing `/workspace/dumps/workspace` and re-reading files under it, 140+ tool calls in one response, three rounds each cut off at the token cap. 20260801T221447 produced 27,089 characters of planner reasoning with zero tool calls, saying "we can simulate in our mind" — word counts in it: script 86, readme 35, plan 4. The fourth (20260802T181318) had made 14 calls in 13 minutes, every one planner or classifier, none coder. A 760M-active model cannot drive this planner; that is the evidence the column exists to generate, and it is now two models against the hypothesis
    ("fabliq",           "8B/A1B",      "lfm2moe 32/4",      "moe",   "on"),
]
# lfm25 is deliberately absent: the systemd unit exists but the model has no entry in
# ~/.config/llama-fleet/models.toml, so starting it cannot work. Add it back when that is fixed.

LANGUAGES = [("python", "ada-handles")]     # the ladder walks ONE language at a time, in this order

# A model walked this many times with no new cria fault found is recorded BLOCKED and the ladder
# moves on. It does NOT count as a pass and the language does not complete — the point is that a
# wedged model must not silently eat days of a long-running goal.
BLOCKED_AFTER = 5


def rows(task):
    if not RESULTS.exists():
        return []
    out = []
    for line in RESULTS.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        # An ABORTED run is evidence, not an attempt. A row killed by hand — to ship a fix, to free
        # the GPU, to correct a sequencing mistake — says nothing about the model and must not count
        # toward BLOCKED_AFTER. The row is KEPT (deleting evidence is worse than annotating it) and
        # skipped here.
        if r.get("aborted"):
            continue
        # A row whose code state no longer exists is evidence, not an attempt. When a batch of cria
        # fixes lands that directly targets how a model was failing, its earlier rows describe a
        # system that is gone — counting them toward BLOCKED would retire a model for cria's old
        # bugs. The row is KEPT on disk with the reason written into it (deleting evidence is worse
        # than annotating it) and skipped here, exactly as an aborted row is.
        if r.get("superseded"):
            continue
        if str(r.get("note", "")).startswith(NOTE_PREFIX) and r.get("task") == task:
            out.append(r)
    return out


def in_flight():
    """A suite run executing RIGHT NOW — the process table, not a claim about it."""
    try:
        ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True,
                            timeout=30).stdout
    except Exception:  # noqa: BLE001
        return None
    for line in ps.splitlines():
        parts = line.split()
        # argv[1] must BE the runner. Matching "suite/run.py" anywhere in the line also matches the
        # shell asking the question, and this file while it is being edited — `ladder_status.py` then reports
        # a phantom run forever and blocks every action. Same self-match that makes `pkill -f` kill
        # its own caller.
        if len(parts) >= 4 and parts[1].endswith("suite/run.py") and "--model" in parts:
            return parts[parts.index("--model") + 1]
    return None


# A walk section must DECLARE what it found, in one machine-readable line, so the block rule can be
# the rule the goal doc actually states. Written by the walker, in the run's own section.
FAULT_YES = "cria fault: yes"
FAULT_NONE = "cria fault: none"


def _walk_sections():
    """{run_id: section text} for every walk written down. A walk that exists only in a chat message
    is not a walk anyone can check later, and is exactly what a compaction deletes."""
    if not WALK.exists():
        return {}
    out, cur, buf = {}, None, []
    for line in WALK.read_text().splitlines():
        if line.startswith("## "):
            if cur:
                out[cur] = "\n".join(buf)
            cur, buf = line.split("## ", 1)[1].strip(), []
        elif cur:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf)
    return out


def walked_runs():
    return set(_walk_sections())


def strikes(rs, sections):
    """Failures that count toward BLOCKED: the ones whose walk found NO new cria fault.

    The goal doc's rule has always been "5 walked failures WITH NO NEW CRIA FAULT FOUND", and the
    constant's own comment says so — but the code counted every failure. That blocks whichever model
    is teaching us the most, which is precisely backwards: it marked mellum2 BLOCKED after five walks
    that between them produced the compaction ordering fix, the find=/spill divergence, the API-probe
    gate, the multi-character degeneracy guard and the empty-workspace completion gate.

    A failure whose walk found a cria fault is EVIDENCE, and cria has changed since. A failure whose
    walk found none is a strike. A walk that declares neither is treated as a strike, so the bound
    still holds and the walker is pushed to say which it was."""
    n = 0
    for r in rs:
        if (r.get("score") or 0) >= (r.get("max_score") or 4):
            continue
        if FAULT_YES not in sections.get(r["run_id"], "").lower():
            n += 1
    return n


def state_for(task):
    sections = _walk_sections()
    walked = set(sections)
    running = in_flight()
    by_model = {}
    for r in rows(task):
        by_model.setdefault(r["model"], []).append(r)

    out = []
    for name, params, arch, kind, planner in LADDER:
        rs = sorted(by_model.get(name, []), key=lambda r: r.get("started") or 0)
        passed = any((r.get("score") or 0) >= (r.get("max_score") or 4) for r in rs)
        last = rs[-1] if rs else None
        unwalked = [r for r in rs if r["run_id"] not in walked
                    and (r.get("score") or 0) < (r.get("max_score") or 4)]
        out.append({
            "model": name, "params": params, "arch": arch, "kind": kind, "planner": planner,
            "attempts": len(rs),
            "best": max([(r.get("score") or 0) for r in rs], default=None),
            "last_score": (last or {}).get("score"),
            "last_run_id": (last or {}).get("run_id"),
            "last_terminal": (last or {}).get("terminal"),
            "passed": passed,
            "needs_walk": bool(unwalked) and not passed,
            "next_walk": unwalked[0]["run_id"] if unwalked else None,
            "next_walk_capture": (unwalked[0].get("capture_dir") if unwalked else None),
            "strikes": strikes(rs, sections),
            "blocked": (not passed) and strikes(rs, sections) >= BLOCKED_AFTER and not unwalked,
            "running": running == name,
        })
    return out, running


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--language", default=LANGUAGES[0][0])
    args = ap.parse_args()

    task = dict(LANGUAGES)[args.language]
    cells, running = state_for(task)

    # WALK BEFORE RUN, always: a scored run already holds its evidence and walking costs no GPU,
    # while starting another run buries that capture under a newer one.
    to_walk = [c for c in cells if c["needs_walk"]]
    live = [c for c in cells if not c["passed"] and not c["blocked"]]
    complete = not live
    action, target = "none", None
    if running:
        action = "wait"
    elif to_walk:
        action, target = "walk", to_walk[0]
    elif live:
        action, target = "run", live[0]

    if args.json:
        print(json.dumps({"language": args.language, "task": task, "complete": complete,
                          "running": running, "next_action": action,
                          "target": target, "cells": cells}, indent=1))
    else:
        print(f"LANGUAGE LADDER — {args.language} ({task}), {MILESTONE_MINUTES} min per deliverable\n")
        print(f"{'model':18s} {'params':12s} {'architecture':22s} {'kind':6s} {'plan':5s} "
              f"{'tries':>5s} {'best':>5s}  state")
        print("-" * 96)
        for c in cells:
            st = ("RUNNING" if c["running"] else "PASSED 4/4" if c["passed"] else
                  "BLOCKED" if c["blocked"] else "needs walk" if c["needs_walk"] else
                  "not started" if not c["attempts"] else "ready to rerun")
            best = f"{c['best']:.0f}" if c["best"] is not None else "—"
            print(f"{c['model']:18s} {c['params']:12s} {c['arch']:22s} {c['kind']:6s} "
                  f"{c['planner']:5s} {c['attempts']:5d} {best:>5s}  {st}")
        print()
        if running:
            print(f"IN FLIGHT: {running} — do not start another run, and do not edit cria or its "
                  f"prompts (they load lazily; an edit changes the RUNNING system)")
        elif complete:
            blocked = [c["model"] for c in cells if c["blocked"]]
            print(f"{args.language.upper()} COMPLETE" if not blocked else
                  f"{args.language.upper()} DONE EXCEPT BLOCKED: {', '.join(blocked)} — "
                  f"not a pass, and the language is NOT finished")
        elif action == "walk":
            print(f"NEXT: WALK {target['next_walk']}")
            print(f"  read {target['next_walk_capture']} — EVERY call, start to finish, pairing "
                  f"NNNN-*.prompt.txt (what was sent) with NNNN-*.reasoning.txt (what it made of it)")
            print("  A walk is READING, not searching. No grep, no sampling, no counting over the "
                  "files — those have all produced confident wrong answers here.")
            print(f"  then write '## {target['next_walk']}' into docs/audits/ladder-walk.md")
            print("  RUN any code a steer contains. A diagnosis that reads correct can still ship "
                  "a fix that cannot execute — that is how C1 was cleared wrongly.")
        else:
            print(f"NEXT: RUN {target['model']} ({target['params']} {target['kind']}, "
                  f"attempt {target['attempts'] + 1})")
            print(f"  python3 suite/run.py --task {task} --model {target['model']} "
                  f"--harness codex --planner {target['planner']} "
                  f"--milestone-minutes {MILESTONE_MINUTES} "
                  f'--note "{NOTE_PREFIX} {args.language} {target["model"]} $(git rev-parse --short HEAD)"')

    sys.exit(2 if running else 0 if complete else 1)


if __name__ == "__main__":
    main()
