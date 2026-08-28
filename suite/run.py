#!/usr/bin/env python3
"""Suite runner — one cell of the test matrix per invocation.

Provisions a throwaway workspace, points the rig at the requested model + planner setting,
drives one harness run of the task prompt under a wall clock (operator's call: no call budget —
slow models surfacing as budget-kills is itself signal), then collects metrics from cria's own
capture/events, runs the task's deterministic verifier, and appends one JSON row to
suite/results/results.jsonl.

Two budgets:
  * flat (default) — one HARD 30-minute wall.
  * `--milestone-minutes N` — N minutes per deliverable, so the budget follows the size of the task.

NO MID-RUN SCORING. There used to be a floor at every N-minute mark, climbing by one deliverable each
time, that killed a run whose STRICT all-or-nothing count fell behind. That is the measure this suite
does not ask about (operator, 2026-08-27), and it killed runs whose deliverables were nearly done. A
run now gets its budget and is judged once, by inference, after it finishes.

Kill mechanics follow the runctl scars: match the codex process list explicitly (ps + grep of
the exec pattern, excluding shells), never `pkill -f` (it matches the invoking shell).

Usage: run.py --task ada-handles --model ternary-bonsai --harness codex --planner off [--note x]
"""

import argparse
import hashlib
import json
import pathlib
import os
import re
import site
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

import sampling

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"
# One stray 403 is a blip; a run peppered with them was throttled. Measured: the affected
# runs carried dozens, the healthy ones none.
THROTTLE_PROMPTS = 5
# NOT /tmp. A run's workspace IS its evidence — the archive, the verifier's input, and every walk
# that reads what the coder actually built — and this box runs cleaners over /tmp. One did, mid-run:
# `shipping-rates-rb x ternary-bonsai` 2026-08-17 17:14 lost its workspace between the 15-minute
# milestone (which scored it) and the archive twelve seconds later, so `cp -r` copied nothing,
# verify.py ran against a path that no longer existed, and the row landed 0/0 with no verifier error
# to explain it. The evidence-preservation rule one screen down — "Nothing under ~/.cria/suite is
# ever auto-cleaned" — was already the intent; the live tree just was not covered by it.
#
# NOT under ~/.cria either, and that is not a style choice: `writeproxy._targets_cria_home` REFUSES
# any absolute write that resolves into cria's own home, so a workspace there would have every write
# the model makes refused. This is the durable place that is neither.
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"   # gitignored; see .gitignore
RUNS_DIR.mkdir(parents=True, exist_ok=True)

CALLS_DIR = Path.home() / ".cria" / "calls"
EVENTS_DIR = Path.home() / ".cria" / "logs"
CRIA_TOML = Path.home() / ".cria" / "cria.toml"
WALL_SECONDS = int(os.environ.get("SUITE_WALL_MINUTES", "30")) * 60
KILL_GRACE = 20

# fleet model name -> systemd service (one model at a time on the 3080)
SERVICES = {
    "ternary-bonsai": "llama-ternary-bonsai",
    "qwythos": "llama-qwythos-q6",
    "qwopus": "llama-qwopus-q6",
    "qwen35": "llama-qwen35",
    "ornith": "llama-ornith-q6",
    "gemma4": "llama-gemma4",
    "maple-preview": "llama-maple-preview",  # DeepGrove ternary MoE 20B-A1B (stamsam prism fork)
    "mellum2": "llama-mellum2-q4",
    "nemotron-elastic": "llama-nemotron-elastic",
}

# Harness launchers: name -> argv builder (headless/exec mode only). Phase 0 ships codex;
# the other adapters land with their harness phases.
def _codex_argv(prompt: str):
    return ["codex", "exec", "--yolo", prompt]

HARNESSES = {"codex": _codex_argv}

NODE_PATH = "/home/jesse/.nvm/versions/node/v22.13.1/bin"


# How long a task's own verify.py may take. It runs the coder's program repeatedly — feed-pipeline
# -java's determinism check alone runs it eight times over a 1.2 MB fixture, and the program prints
# a line per SKU. MEASURED rather than guessed: that verifier took 1,250 s on the workspace whose
# row the old 600 s limit destroyed. 1,800 leaves headroom over the worst case observed without
# letting a genuinely wedged verifier hold a cell forever.
VERIFY_TIMEOUT_S = 1800


def sh(*cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def wait_health(url: str, tries=90, delay=10) -> bool:
    """Poll until the server answers. 15 minutes, not 5.

    A healthy model answers on the first poll, so the ceiling costs nothing when it is not needed —
    and when it IS needed the alternative is a false "never became healthy", which writes no result
    row at all. A campaign driver then re-queues the same cell forever, because an absent row is
    indistinguishable from a cell that has not been attempted. Observed 2026-08-10: ternary-bonsai
    (6.7 GB, PrismML fork) exceeded 5 minutes from a cold page cache after a large file cleanup, and
    the battery driver looped on it twice before anyone looked."""
    import urllib.request
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except Exception:  # noqa: BLE001
            time.sleep(delay)
    return False


def swap_model(model: str) -> None:
    target = SERVICES[model]
    for svc in SERVICES.values():
        if svc != target:
            sh("sudo", "-n", "systemctl", "stop", f"{svc}.service")
    sh("sudo", "-n", "systemctl", "start", f"{target}.service", timeout=60)
    if not wait_health("http://127.0.0.1:18084/health"):
        raise RuntimeError(f"model {model} ({target}) never became healthy")


def configure_cria(model: str, planner_enabled: bool) -> dict:
    """Write this model's sampling AND the planner setting, then restart cria once.

    Sampling used to be a manual step in the goal doc, and it was missed 26 consecutive times: every
    gemma4 run in results.jsonl was sent ternary-bonsai's numbers (coder 0.2/0.95/20) because the
    runner swapped the model and the planner and left `[roles.*]` alone. Those runs measured a model
    nobody was testing. A step that must be remembered before each run is a footgun, so the runner
    does it.
    """
    spec = sampling.apply(model, CRIA_TOML)
    text = CRIA_TOML.read_text()
    new = re.sub(r"(\[planner\][^\[]*?enabled\s*=\s*)(true|false)",
                 lambda m: m.group(1) + ("true" if planner_enabled else "false"), text, count=1)
    if new == text and f"= {'true' if planner_enabled else 'false'}" not in text:
        raise RuntimeError("could not toggle [planner].enabled in cria.toml")
    CRIA_TOML.write_text(new)
    sh("sudo", "-n", "systemctl", "restart", "cria.service", timeout=60)
    if not wait_health("http://127.0.0.1:18085/health"):
        raise RuntimeError("cria never became healthy after reconfiguration")
    return spec


# WHERE EVERY ECOSYSTEM INSTALLS WHEN NOBODY SAYS WHERE. A run under --yolo can install into the
# operator's real environment, and the resulting artefact outlives the run: the NEXT run finds a
# dependency it never installed and scores points for work it did not do.
#
# This watched Python only, and the cost is measured. `shipping-rates-rb` requires a third-party gem;
# `countries-8.1.0` has been in the user gem dir since 2026-08-10 12:37 (installed thirteen minutes
# before e19911b, whose subject is gem detection — the task author validating the reference solution
# and leaving it behind). Every ruby row since has reported `site_packages_leak: []` while four of
# them were scored against a gem no model installed: re-scored with the dir hidden, 5/5 → 1/5,
# 5/5 → 1/5, 4/5 → 1/5.
#
# So the tripwire is per-ECOSYSTEM, because the failure is. A rule keyed to one language's spelling
# is inert on the other five — the same shape the operator has flagged repeatedly.
def _user_install_roots() -> dict:
    """`{label: directory}` for each ecosystem's default user-level install location. Asked of the
    tool where the tool can answer, so a version bump or a custom GEM_HOME does not silently blind
    the tripwire; a fixed path only where there is no command to ask."""
    home = os.path.expanduser("~")
    roots = {}
    try:
        roots["py"] = site.getusersitepackages()
    except Exception:  # noqa: BLE001
        pass
    probes = {
        "gem": ("ruby", "-e", "print Gem.user_dir + '/gems'"),
        "npm": ("npm", "root", "-g"),
    }
    for label, argv in probes.items():
        try:
            out = subprocess.run(argv, capture_output=True, text=True, timeout=20).stdout.strip()
            if out:
                roots[label] = out
        except (OSError, subprocess.SubprocessError):
            pass
    for label, path in (("cargo", f"{home}/.cargo/registry/cache"),
                        ("go", f"{home}/go/pkg/mod/cache/download"),
                        ("maven", f"{home}/.m2/repository")):
        if os.path.isdir(path):
            roots[label] = path
    return roots


def _ruby_keep_path() -> list:
    """The gem directories a cell must still SEE: Ruby's own, and nothing anyone installed.

    GEM_PATH REPLACES THE SEARCH PATH, IT DOES NOT EXTEND IT. Pointed at an empty cell directory it
    hides `minitest` and `rake`, which ship with Ruby and live in `/usr/lib/ruby/gems`. Walked on
    shipping-rates-rb x nemotron-elastic the night isolation landed: the run spent 24 of its 60 calls
    trying five ways to load minitest, cria's check block carried `cannot load such file --
    minitest/autorun` in 51 of 61 prompts, and the one-character bug the task opens with was never
    touched. The cell scored 8 — a measurement of this bug, not of the model.

    Asked of Ruby, never spelled out here (#20): `Gem.default_path` is the system search path, and
    the two entries to drop are `Gem.default_dir` — where a plain `gem install` puts things, so the
    `countries` and `rspec` somebody installed by hand — and `Gem.user_dir`, the leaked user root.
    What is left is the distribution's own. Verified: minitest and rake visible, `countries`,
    `iso_country_codes`, `eu_countries` and `rspec` all hidden, and an install still lands in the
    cell.

    Empty when Ruby is not installed or cannot answer, which leaves GEM_PATH as the cell alone — the
    behaviour before this, and no worse for a box with no Ruby on it."""
    try:
        out = subprocess.run(
            ["ruby", "-e", "print (Gem.default_path - [Gem.default_dir, Gem.user_dir]).join(File::PATH_SEPARATOR)"],
            capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return []
    return [d for d in out.split(os.pathsep) if d]


def _isolated_installs(ws) -> dict:
    """Environment that keeps this cell's package installs INSIDE its own workspace.

    NO CELL MAY AFFECT ANOTHER CELL, and for five days they did. `user_install_listing` was built to
    make contamination visible rather than to prevent it — its own words: "Nothing is prevented or
    cleaned here — a leak that is visible can be reasoned about". That fails in one specific way: the
    row records the DELTA a run creates, so the run that installs is visible and every run that
    INHERITS is silent. Five rows in the whole campaign recorded a leak; every later cell on the box
    read those packages and reported nothing.

    Measured, and it decided cells. `gem:countries-8.1.0` has been on this box since 2026-08-22 and
    `gem:iso_country_codes-0.7.8` since 2026-08-24 13:30, left by one ruby cell ninety minutes before
    another ruby cell went looking. Walked: the first run searched for "country", found nothing,
    fell back to a hardcoded list and banked its other deliverables (85); the second searched for
    "countries", found an installed gem nobody in that run had installed, and spent 277 calls
    interrogating it (28). By the time the ternary-bonsai ruby cells ran, seven gems left by four
    earlier cells were discoverable by `gem list`.

    The direction is one-way — installs accumulate, so a later cell can find more than an earlier one
    and never less. That is why a batch comparison drifts one way and a repeat of a single cell does
    not.

    Every root here is one `user_install_listing` already probes, so the tripwire keeps working and
    now measures a run against its own empty slate. The shared DOWNLOAD caches are left alone
    deliberately: a cached artifact is not discoverable by name, and taking them away would make
    every run re-fetch the world inside a 30-minute budget, which changes what the suite measures
    for a reason unrelated to isolation."""
    root = Path(ws) / ".cell-installs"
    return {
        # THE USER-LEVEL ROOT ITSELF. `gem install --user-install` ignores GEM_HOME and writes to
        # `Gem.user_dir`, which is derived from XDG_DATA_HOME — and `--user-install` is exactly the
        # command that leaked `iso_country_codes` onto this box. Verified: with XDG_DATA_HOME set,
        # `Gem.user_dir` moves and `--user-install` lands inside the cell.
        "XDG_DATA_HOME": str(root / "xdg-data"),
        "XDG_CACHE_HOME": str(root / "xdg-cache"),
        # ruby: `gem install` and `bundle` honour these. GEM_PATH is not a prefix — it REPLACES the
        # search path — so it has to name Ruby's own gems too. See _ruby_keep_path.
        "GEM_HOME": str(root / "gem"),
        "GEM_PATH": os.pathsep.join([str(root / "gem"), *_ruby_keep_path()]),
        # python: `pip install --user` and `site.getusersitepackages()`.
        "PYTHONUSERBASE": str(root / "py"),
        # node: `npm install -g` and `npm root -g`.
        "npm_config_prefix": str(root / "npm"),
        # go and rust install binaries here; the module/registry caches stay shared.
        "GOBIN": str(root / "go" / "bin"),
        "CARGO_INSTALL_ROOT": str(root / "cargo"),
    }


def user_install_listing() -> set:
    """`{"<ecosystem>:<name>"}` for everything currently installed at user level, across ecosystems.

    The delta between two calls is recorded per row so contamination is EVIDENCE, never a silent
    confound. Nothing is prevented or cleaned here — a leak that is visible can be reasoned about;
    the two weeks of cross-run poisoning this was built after were invisible.

    (Measured first on Python: an editable install of a suite /tmp workspace via a .pth left a broken
    resolver.py shadowing `import resolver` for every later run AND the verifier.)"""
    out = set()
    for label, root in _user_install_roots().items():
        try:
            out.update(f"{label}:{n}" for n in os.listdir(root))
        except OSError:
            continue
    return out


def codex_pids():
    out = sh("ps", "-eo", "pid,args").stdout
    pids = []
    for line in out.splitlines():
        if "codex exec --yolo" in line and not any(x in line for x in ("/bin/bash", "snapshot", "run.py")):
            pids.append(int(line.split(None, 1)[0]))
    return pids


def collect_capture(session_dirs) -> dict:
    """Every call the run made, across ALL of its capture directories.

    cria opens a fresh capture directory per server session, and one cell can span several: the
    harness reconnects, or the run trails a short session after the main one. Reading only the
    newest directory reports that tail as the whole run. L2 cart-billing-go x ternary-bonsai
    recorded `calls: 2` against 93 real calls in the directory next to it, which reads in the
    report as a model that produced nothing in half an hour. Sum them.
    """
    calls = sorted(f for d in session_dirs for f in d.glob("*.response.json"))
    phases, tok_n, tok_ms = {}, 0, 0.0
    for f in calls:
        m = re.match(r"\d+-(.+?)(?:-s\d+.*)?\.response\.json$", f.name)
        phase = m.group(1) if m else "unknown"
        phases[phase] = phases.get(phase, 0) + 1
        try:
            t = json.loads(f.read_text()).get("timings") or {}
            if t.get("predicted_n"):
                tok_n += t["predicted_n"]
                tok_ms += t["predicted_ms"]
        except Exception:  # noqa: BLE001
            pass
    return {"calls": len(calls), "phases": phases,
            "avg_tok_s": round(tok_n / (tok_ms / 1000), 1) if tok_ms else None,
            "output_tokens_timed": tok_n}


def collect_assists(t0: float, t1: float) -> dict:
    """Count rlog event kinds in the run's window. Single-run-at-a-time makes the time window
    authoritative; refine to session-scoped when events grow a session field."""
    kinds = {}
    for day_file in sorted(EVENTS_DIR.glob("cria-*.jsonl")):
        try:
            with open(day_file, errors="replace") as fh:
                for line in fh:
                    try:
                        ev = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    if t0 <= ev.get("ts", 0) <= t1:
                        k = ev.get("kind", "?")
                        kinds[k] = kinds.get(k, 0) + 1
                        # the floor's own confession that a request may not fit even after every
                        # lever — fired 58x in one run (C1) with nothing counting it.
                        if k == "context.floor" and ev.get("over_budget"):
                            kinds["context.floor_over_budget"] = kinds.get("context.floor_over_budget", 0) + 1
        except OSError:
            continue
    # A DENYLIST, NOT AN ALLOWLIST. This was a list of substrings a kind had to MATCH to be counted,
    # so every intervention nobody thought to name was dropped in silence — and the dropped ones were
    # the interesting ones. Measured on rust-toml-cli x nemotron-elastic: `writeproxy.exec_output_bounded`
    # fired 80 times, the single most important number in that run, and the row recorded none of it;
    # six distinct steer texts and thirty gate-carrying prompts came out as 0 steers and 2 gates. Every
    # "cria intervened N times" this campaign has quoted from this field was a floor, not a count (#12).
    #
    # Inverted so it fails the safe way: a NEW intervention kind is counted by default, and only
    # transport and bookkeeping are named. Adding an assist can no longer make it invisible.
    plumbing = ("upstream.", "http.", "request.", "response.", "ctx.estimate", "usage.",
                "toolmenu.", "indicators.", "coder.reasoning", "route.classify",
                "writeproxy.advertised", "writeproxy.represented", "capture.", "log.")
    # loop.compaction_reframed fires on every REQUEST that re-reads a compacted history (stateless
    # re-processing, by design) — counting it as an assist inflated one run by 85. Occurrences of
    # compaction itself are context.self_compact / route.compaction.
    kinds.pop("loop.compaction_reframed", None)
    return {k: v for k, v in kinds.items() if not any(k.startswith(p) for p in plumbing)}


def deliverable_names(task_dir: Path) -> list:
    """The things this task must produce, in the task's own words — meta.toml is the authority.

    The gate asks the judge how many of THESE are complete, so the list a run is paced against and
    the list it is finally judged against are the same list, written by whoever wrote the task."""
    meta = tomllib.loads((task_dir / "meta.toml").read_text())
    names = [str(d) for d in (meta.get("deliverables") or [])]
    if not names:
        raise RuntimeError(f"{task_dir.name}/meta.toml declares no deliverables — "
                           "pacing has nothing to pace against")
    return names


def deliverable_count(task_dir: Path) -> int:
    """How many things this task must produce, so the budget follows the task."""
    return len(deliverable_names(task_dir))


# Where a mid-run gate asks its question and waits for the answer. One file per gate, named for the
# run and the minute, so a batch's pending questions are a directory listing and nothing is held in
# anyone's head — the same shape `usefulness.pending` uses for the end-of-run judgement.
GATE_DIR = SUITE / "results" / "gates"
# How long a gate waits for a verdict before giving up and letting the run continue. The judge is a
# person reading a packet, not a service: they may be asleep. A gate nobody answers must never be the
# reason a run dies (#13), so the timeout fails OPEN, says so on the row, and drops a marker the
# batch reads.
#
# SHORT, BECAUSE FAILING OPEN MAKES A LONG WAIT PURE COST. It was 900s: three unanswered gates added
# 45 minutes to a run nobody was gating, on top of the 45 minutes the missing gate itself cost. Two
# minutes is long enough for a judge who is already watching the directory and cheap enough for one
# who is not.
GATE_WAIT_S = 120


def ask_gate(run_id: str, minute: int, floor: int, ws: Path, task_dir: Path, prompt: str):
    """Ask the judge how many deliverables are complete, and wait. Returns an int, or None.

    THE JUDGE IS THE PERSON RUNNING THE CAMPAIGN, and always has been — every verdict in
    `results.jsonl` was written by one reading an evidence packet. The old gate asked `verify.py`'s
    all-or-nothing count instead, which says "not done" for work that is done and merely fails a
    check on something incidental: a complete, correct, working CLI one directory too deep scored 0.
    That count is gone; the question it asked is not.

    So the gate writes the same kind of packet `usefulness.emit` writes — the task's own deliverable
    list, the diff from the seed, and the verifier's per-deliverable observations as EVIDENCE rather
    than as the verdict — and waits for a file holding one integer.

    It does not pause the coder. The packet describes the workspace at the mark; the run carries on
    while the question is open, so a slow answer costs the run nothing.

    None when the answer does not arrive or does not parse, and None is the caller's cue to continue.
    A judge who is asleep may not end a run."""
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    q = GATE_DIR / f"{run_id}.{minute:03d}min.md"
    a = GATE_DIR / f"{run_id}.{minute:03d}min.verdict"
    snap = Path(tempfile.mkdtemp(prefix="gate-snap-", dir=RUNS_DIR))
    try:
        sh("cp", "-r", str(ws), str(snap / "ws"), timeout=300)
        parts = observe_snapshot(snap / "ws", task_dir)
        # STAGE FIRST, so a NEW file is in the diff. `git diff HEAD` shows tracked changes only, and
        # a run whose whole contribution is new files reads as having done nothing — which is a
        # judgement the gate would then make on an empty page. Caught on the first real gate: the
        # ruby run's diff was empty while a Gemfile and a vendor tree sat untracked beside it. Safe
        # because this is a throwaway copy; the coder's own index is never touched.
        sh("git", "-C", str(snap / "ws"), "add", "-A", timeout=120)
        diff = sh("git", "-C", str(snap / "ws"), "diff", "--cached", "HEAD", timeout=120).stdout
        names = deliverable_names(task_dir)
        q.write_text("\n".join([
            f"# GATE — {run_id} at {minute} minutes",
            "",
            f"**How many of these {len(names)} deliverables are COMPLETE?** Write the integer alone "
            f"into `{a.name}` in this directory. The run continues while you decide; it is stopped "
            f"only if your answer is below {floor}.",
            "",
            "Judge whether the work is DONE, not whether a check passes. A deliverable that works but "
            "trips a check on something incidental is complete. A deliverable that is written but "
            "cannot run is not.",
            "",
            "## The deliverables this task names",
            *[f"{i+1}. {n}" for i, n in enumerate(names)],
            "",
            "## The task, as the coder received it",
            prompt,
            "",
            "## What the repo's own verifier observes right now — EVIDENCE, not the verdict",
            *[f"- [{'met' if v.get('ok') else 'NOT met'}] {k}: {v.get('detail')}" for k, v in parts.items()],
            "",
            "## Everything the coder has changed since the seed",
            "```diff", diff, "```", ""]))
        print(f"[gate] {minute}min  asked -> {q}", flush=True)
        deadline = time.time() + GATE_WAIT_S
        while time.time() < deadline:
            if a.is_file():
                for tok in a.read_text().split():
                    if tok.strip().isdigit():
                        return int(tok.strip())
                return None
            time.sleep(5)
        # AN UNANSWERED GATE IS AN UNGATED RUN, and that is an instrument defect, not a hiccup. It
        # fails OPEN because silence must never end a run (#13) — but silence must not be silent
        # either: the row records `complete: null`, and this marker lets the batch stop instead of
        # spending the next cell the same way. Six gates went unanswered on 2026-08-27 and two cells
        # ran their full budget ungated before anyone noticed.
        with (GATE_DIR / "UNANSWERED").open("a") as fh:
            fh.write(f"{q.name}\n")
        print(f"[gate] {minute}min  NO VERDICT in {GATE_WAIT_S}s — the run continues UNGATED. "
              f"Answer it in {q} and the next cell will run gated.", flush=True)
        return None
    except Exception:  # noqa: BLE001
        return None
    finally:
        sh("rm", "-rf", str(snap), timeout=120)


def observe_snapshot(ws: Path, task_dir: Path) -> dict:
    """What the verifier OBSERVES about the workspace as it stands — per deliverable, no total.

    Read-only, and it runs against a COPY: the verifier executes the deliverables, which leaves
    `__pycache__`, `.pytest_cache` and stray output behind, and putting cria's artifacts in front of
    the coder's `ls` mid-run is principle 7.

    It returns `parts` and nothing else. The aggregate this used to return was the strict
    all-or-nothing count, which gated a mid-run kill and is the measure the suite does not ask about;
    the per-deliverable observations are the verifier's real output and remain the evidence a
    judgement is made from. `{}` on any failure — an unreadable verdict is not an observation."""
    snap = Path(tempfile.mkdtemp(prefix="observe-snap-", dir=RUNS_DIR))
    try:
        sh("cp", "-r", str(ws), str(snap / "ws"), timeout=300)
        vr = sh(sys.executable, str(task_dir / "verify.py"), str(snap / "ws"), timeout=600)
        return json.loads(vr.stdout).get("parts") or {}
    except Exception:  # noqa: BLE001
        return {}
    finally:
        sh("rm", "-rf", str(snap), timeout=120)


def throttled_mid_run(session_dir) -> str:
    """A 403/429 from the task's live service, seen in the run's own captures.

    Thirteen back-to-back ladder runs, each making dozens of live calls, got api.handle.me to start
    refusing us: run 1785675899's CLI reported `HTTP error 403 for .../handles/goose` while the same
    request from a shell seconds later returned 200. Counted across every capture at the time: 251
    coder prompts carrying a 403, in 3 runs.

    Such a run fails for a reason that is neither cria's nor the model's, and it is scored exactly
    like a real failure — which corrupts the ladder's evidence. It is annotated, not deleted, and the
    oracle skips it the way it skips any aborted row."""
    if not session_dir:
        return ""
    hits = 0
    for p in pathlib.Path(session_dir).glob("*coder*.prompt.txt"):
        try:
            body = p.read_text(errors="replace")
        except OSError:
            continue
        if "HTTP error 403" in body or "403 Client Error" in body or "429 Client Error" in body:
            hits += 1
    if hits < THROTTLE_PROMPTS:
        return ""
    return (f"the task's live service refused us mid-run — {hits} coder prompts carry a 403/429. "
            "Not the model's failure and not cria's; excluded from the ladder.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--model", required=True, choices=sorted(SERVICES))
    ap.add_argument("--harness", default="codex", choices=sorted(HARNESSES))
    ap.add_argument("--planner", required=True, choices=["on", "off"])
    ap.add_argument("--note", default="")
    # The engagement level this cell ran at, recorded as a FIELD rather than parsed back out of the
    # note. The note is prose and has been reformatted twice; a column that a status command counts
    # must not depend on a regex over prose surviving the next edit.
    ap.add_argument("--level", type=int, default=None)
    ap.add_argument("--milestone-minutes", type=int, default=0,
                    help="minutes allowed per deliverable. 0 (default) keeps the flat 30-minute "
                         "wall. When set, the run must hold score >= 1 after the first interval, "
                         ">= 2 after the second, and so on; it is killed the moment it does not. "
                         "A run that keeps delivering therefore EARNS more clock than the flat "
                         "wall gave it, and a stalled one is stopped in a quarter of the time.")
    args = ap.parse_args()

    task_dir = SUITE / "tasks" / args.task
    prompt = (task_dir / "prompt.txt").read_text().strip()
    run_id = f"{args.task}_{args.model}_{args.harness}_p{args.planner}_{int(time.time())}"
    ws = Path(tempfile.mkdtemp(prefix=f"suite-{run_id}-", dir=RUNS_DIR))
    log_path = SUITE / "results" / f"{run_id}.log"

    swap_model(args.model)
    spec = configure_cria(args.model, args.planner == "on")
    print(f"[sampling] {args.model}: "
          + "  ".join(f"{r}={dict(k)}" for r, k in spec.items()), flush=True)
    # SEEDED tasks start from existing code the model must read, not a blank directory. Every task
    # before this one was greenfield, which exercises research and creation and never touches the
    # machinery most of cria's measured footguns live in: reading a file it did not write, editing
    # it surgically, and reading its own gate output. The seed is committed so `git status` is clean
    # and the model's own diff is legible to it.
    seed = task_dir / "seed"
    if seed.is_dir():
        sh("cp", "-r", *[str(p) for p in seed.iterdir()], str(ws), timeout=120)
    sh("git", "-C", str(ws), "init", "-q")
    if seed.is_dir():
        sh("git", "-C", str(ws), "add", "-A")
        sh("git", "-C", str(ws), "-c", "user.email=suite@local", "-c", "user.name=suite",
           "commit", "-qm", "seed", timeout=120)
    before_sessions = set(p.name for p in CALLS_DIR.glob("2*"))
    installs_before = user_install_listing()

    env = dict(os.environ, PATH=f"{NODE_PATH}:{os.environ['PATH']}", **_isolated_installs(ws))
    t0 = time.time()
    with open(log_path, "w") as lf:
        # stdin MUST be closed explicitly: `codex exec` reads stdin to EOF as "additional input"
        # BEFORE starting the turn, and after an interrupted turn it returns to reading stdin.
        # An inherited never-closing stdin (a live socket from the launch environment) froze two
        # cells for their full 30-minute walls with zero work — pre-banner, zero API calls.
        proc = subprocess.Popen(HARNESSES[args.harness](prompt), cwd=ws,
                                stdin=subprocess.DEVNULL,
                                stdout=lf, stderr=subprocess.STDOUT, env=env,
                                start_new_session=True)
    def stop_run():
        for pid in codex_pids():
            sh("kill", "-INT", str(pid))
        time.sleep(KILL_GRACE)
        for pid in codex_pids():
            sh("kill", "-9", str(pid))
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()

    milestone_s = args.milestone_minutes * 60
    wall = WALL_SECONDS
    if milestone_s:
        # One interval per deliverable, so a run that earns every milestone gets the full budget.
        wall = milestone_s * deliverable_count(task_dir)
    terminal = "exited"
    # NOT A SCORE FLOOR — A STALL DETECTOR. The old gate ran verify.py every interval, took its
    # STRICT all-or-nothing count, and killed the run when that count fell below the deliverables
    # owed by then. A run with three deliverables nearly finished scores 0 that way, and was killed
    # at thirty minutes; all three cells on 2026-08-27 died exactly there. The strict measure is gone
    # (operator: "I don't care about the strict measure - at all").
    #
    # A run still has to stop when it is not getting anywhere, so the question changes from "how many
    # are DONE" to "did anything MOVE". Both halves come from the verifier's own per-deliverable
    # observations, which are what a judgement is made from anyway:
    #
    #   * a deliverable flipping to met is movement, and so is its DETAIL changing — `0/8 rate values`
    #     becoming `5/8` is exactly the progress the count threw away;
    #   * the workspace fingerprint moving is movement, so a run editing files between two verifier
    #     readings is never called stalled.
    #
    # Only a reading identical to the one before it — same deliverables met, byte-identical details,
    # untouched workspace — is a stall, and it is confirmed once before the run is stopped (the
    # snapshot is taken while the coder may be mid-write). Unreadable answers fail OPEN toward
    # keeping the run alive (#13). The FIRST interval is never judged: it holds everything a run does
    # once, before anything can have moved twice.
    next_check = milestone_s * 2 if milestone_s else 0
    gates = []
    while proc.poll() is None:
        if next_check and time.time() - t0 >= next_check:
            minute = round(next_check / 60)
            floor = int(round(next_check / milestone_s))      # 2 at the first look, then one more each
            done = ask_gate(run_id, minute, floor, ws, task_dir, prompt)
            gates.append({"at_minutes": minute, "floor": floor, "complete": done})
            print(f"[gate] {minute}min  floor={floor}  judged={done}", flush=True)
            if done is not None and done < floor:
                terminal = f"behind-{minute}min"
                stop_run()
                break
            next_check += milestone_s
        if time.time() - t0 > wall:
            terminal = "budget-killed"
            stop_run()
            break
        time.sleep(10)
    t1 = time.time()
    if terminal == "exited" and t1 - t0 < 60:
        terminal = "crashed-early"

    new_sessions = [CALLS_DIR / n for n in
                    set(p.name for p in CALLS_DIR.glob("2*")) - before_sessions]
    # The primary directory is the one that carries the work, not the one that finished last.
    session_dir = max(new_sessions, key=lambda p: len(list(p.glob("*.response.json"))),
                      default=None) if new_sessions else None
    capture = collect_capture(new_sessions) if new_sessions else \
        {"calls": 0, "phases": {}, "avg_tok_s": None, "output_tokens_timed": 0}

    # EVIDENCE PRESERVATION (operator directive 2026-07-29): every run's artifacts are evidence
    # for cria improvements and are kept until reviewed. The /tmp workspace is copied to a
    # durable archive; the capture dir and harness log paths ride in the row. Nothing under
    # ~/.cria/suite is ever auto-cleaned.
    archive = Path.home() / ".cria" / "suite" / run_id
    archive.mkdir(parents=True, exist_ok=True)
    sh("cp", "-r", str(ws), str(archive / "workspace"), timeout=300)
    # SAY SO WHEN THE EVIDENCE IS GONE. `sh` does not check, so a failed copy was silent and the row
    # that followed read 0/0 with no verifier_error — indistinguishable from a model that built
    # nothing. That is a false fact in the record, and the record is what the campaign is scored on.
    workspace_lost = not ws.is_dir() or not (archive / "workspace").is_dir()

    # A VERIFIER THAT TIMES OUT IS AN UNSCORED ROW, NOT A LOST ONE. `sh` lets TimeoutExpired
    # propagate, and this call site did not catch it — so the whole run.py died AFTER the cell had
    # spent its wall clock, and the row was never written at all. Walked on the sub-60 re-run of
    # feed-pipeline-java x ternary-bonsai: an hour of model time, an archived workspace, and no
    # record that any of it happened. A cell that produced no row is indistinguishable from a cell
    # that never ran, which is the one failure nobody can see from the outside (#12).
    try:
        vr = sh(sys.executable, str(task_dir / "verify.py"), str(ws),
                *([str(session_dir)] if session_dir else []), timeout=VERIFY_TIMEOUT_S)
        stdout, stderr = vr.stdout, vr.stderr
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) \
            else (exc.stdout or "")
        stderr = (f"VERIFIER TIMED OUT after {VERIFY_TIMEOUT_S}s — this row is NOT a score. "
                  + ((exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes)
                     else (exc.stderr or "")))
    try:
        verdict = json.loads(stdout)
    except Exception:  # noqa: BLE001
        verdict = {"score": 0, "max_score": 0, "success": False,
                   "verifier_error": (stdout + stderr)[-400:]}
    if workspace_lost:
        verdict["verifier_error"] = (
            f"WORKSPACE GONE before verification ({ws}) — this row is NOT a score. "
            + str(verdict.get("verifier_error") or ""))[:400]
        print(f"[archive] WORKSPACE MISSING: {ws} — the row is unscored, not zero", flush=True)

    row = {
        "run_id": run_id, "task": args.task, "model": args.model, "harness": args.harness,
        "planner": args.planner, "note": args.note, "sampling": spec,
        **({"level": args.level} if args.level is not None else {}),
        "started": t0, "wall_seconds": round(t1 - t0, 1), "terminal": terminal,
        "milestone_minutes": args.milestone_minutes or None, "gates": gates or None,
        "success": bool(verdict.get("success")), "score": verdict.get("score"),
        "max_score": verdict.get("max_score"), "verify": verdict.get("parts"),
        **capture,
        "assists": collect_assists(t0, t1),
        "workspace": str(ws),
        "archive": str(archive),
        "user_install_leak": sorted(user_install_listing() - installs_before),
        "capture_dir": str(session_dir) if session_dir else None,
        "capture_dirs": sorted(str(d) for d in new_sessions) or None,
        "harness_log": str(log_path),
    }
    throttled = throttled_mid_run(session_dir)
    if throttled:
        row["aborted"] = throttled
        print(f"[throttled] {throttled}")
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS, "a") as fh:
        fh.write(json.dumps(row) + "\n")
    print(json.dumps({k: row[k] for k in
                      ("run_id", "terminal", "success", "score", "wall_seconds",
                       "calls", "avg_tok_s")}, indent=1))
    _freeze_usefulness_evidence(row)
    _refresh_grid()


def _freeze_usefulness_evidence(row: dict) -> None:
    """Save the judge's evidence packet NOW, while the workspace still exists.

    The usefulness score — "was real work done?", the question the operator actually cares about —
    is judged from a packet built by walking the archived workspace. The workspace is the perishable
    half: of 503 recorded runs, 455 had no verdict and only 138 of those still had a workspace on
    disk, so the rest can never be judged at all. Every BASE row that could still be judged already
    had been; the other 57 are gone for good, which is why the arms cannot be compared on the number
    that matters.

    Nothing in `suite/` deletes an archive, so the loss came from outside — and a mechanism that
    depends on 3.4 GB of trees surviving indefinitely is one that will keep losing runs. A few KB of
    text per run does not. Judging can then happen whenever, on whatever is left.

    Best-effort by construction: a packet that cannot be written must never fail a run that
    finished, and the row is already on disk by the time this runs."""
    try:
        sys.path.insert(0, str(SUITE))
        import usefulness
        out = usefulness.save_packet(row)
        if out is not None:
            print(f"[usefulness] evidence frozen -> {out}", flush=True)
    except Exception as e:                       # noqa: BLE001 — never fail a finished run
        print(f"[usefulness] could not freeze evidence: {e}", flush=True)


def _refresh_grid() -> None:
    """Rewrite the operator grid from results.jsonl, here, where the row was just appended.

    The grid is THE operator view and the standing rule is to refresh it after every run — but it
    was a step a human had to remember, so it drifted: gemma4's canary was recorded and then
    qwen35's 4/4 and mellum2's 1/4 both landed unrecorded, leaving the board showing qwen with two
    runs when it had three. A rule that depends on remembering is not a rule (#4 — fix it where it
    belongs, not by trying harder).

    Best-effort and non-fatal: the run's RESULT is already durably on disk one line above, and a
    reporting step must never be able to fail a completed run."""
    try:
        sys.path.insert(0, str(SUITE))
        import regression_stats
        lines = [regression_stats.stat_line(r) for r in regression_stats.rows()]
        regression_stats.write_report(lines, regression_stats.model_summary(lines))
        print("[grid] refreshed docs/audits/regression-report.md")
    except Exception as e:  # noqa: BLE001 — reporting must not fail the run
        print(f"[grid] refresh skipped: {type(e).__name__}: {e}")
    # The campaign's own table, on the same rule and for the same reason. Silent when no BATTERY
    # rows exist, so an ordinary ladder run does not touch it.
    try:
        sys.path.insert(0, str(SUITE))
        import battery_status
        if rs := battery_status.rows():
            battery_status.write_report(rs)
            print("[battery] refreshed docs/audits/battery-report.md")
    except Exception as e:  # noqa: BLE001
        print(f"[battery] refresh skipped: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
