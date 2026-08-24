#!/usr/bin/env python3
"""Suite runner — one cell of the test matrix per invocation.

Provisions a throwaway workspace, points the rig at the requested model + planner setting,
drives one harness run of the task prompt under a wall clock (operator's call: no call budget —
slow models surfacing as budget-kills is itself signal), then collects metrics from cria's own
capture/events, runs the task's deterministic verifier, and appends one JSON row to
suite/results/results.jsonl.

Two pacing modes:
  * flat (default) — one HARD 30-minute wall, scored once at the end.
  * `--milestone-minutes N` — N minutes per deliverable, with the workspace scored at every N-minute
    mark and a floor that climbs by one each time. A run that keeps delivering earns the whole
    budget; a stalled one is killed early instead of burning the full wall. Which deliverable lands
    first does not matter — only the count does. Scoring STARTS at the second mark (2N minutes,
    floor 2): the first interval carries everything a run does once, before any deliverable can be
    finished, so judging it there kills runs that are merely starting. See
    FIRST_MILESTONE_INTERVAL.

Kill mechanics follow the runctl scars: match the codex process list explicitly (ps + grep of
the exec pattern, excluding shells), never `pkill -f` (it matches the invoking shell).

Usage: run.py --task ada-handles --model ternary-bonsai --harness codex --planner off [--note x]
"""

import argparse
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
# The first milestone a run must clear. The floors are one deliverable per interval, and the FIRST
# interval is the one a run cannot pace: it holds everything that happens once — reading the task,
# listing the workspace, reading the files it names, the first build, the first failing test — before
# any deliverable can possibly be finished. Judged at one interval it reads as a stall; the same run
# judged at two is on pace. Operator, 2026-08-19: give the first two deliverables 30 minutes between
# them and skip the 15-minute wall entirely. The total budget is unchanged — one interval per
# deliverable — so nothing is bought here except not killing a run for its slow first step.
FIRST_MILESTONE_INTERVAL = 2
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


def collect_capture(session_dir: Path) -> dict:
    calls = sorted(session_dir.glob("*.response.json"))
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


def deliverable_count(task_dir: Path) -> int:
    """How many things this task must produce — the task's own meta.toml is the authority, so the
    milestone budget follows the task rather than a number hardcoded here."""
    meta = tomllib.loads((task_dir / "meta.toml").read_text())
    n = len(meta.get("deliverables") or [])
    if n < 1:
        raise RuntimeError(f"{task_dir.name}/meta.toml declares no deliverables — "
                           "milestone pacing has nothing to pace against")
    return n


def score_snapshot(ws: Path, task_dir: Path) -> tuple[float, float, dict]:
    """Score the workspace AS IT STANDS, without touching it.

    The verifier runs the deliverables — pytest, the CLI, the network-blocked live check — and
    those leave `__pycache__`, `.pytest_cache` and stray output behind. Running it against the live
    workspace would put cria's own artifacts in front of the coder's `ls` mid-run (principle 7), so
    a COPY is scored and thrown away.
    """
    snap = Path(tempfile.mkdtemp(prefix="milestone-snap-", dir=RUNS_DIR))
    try:
        sh("cp", "-r", str(ws), str(snap / "ws"), timeout=300)
        vr = sh(sys.executable, str(task_dir / "verify.py"), str(snap / "ws"), timeout=600)
        v = json.loads(vr.stdout)
        return float(v.get("score") or 0), float(v.get("max_score") or 0), v.get("parts") or {}
    except Exception:  # noqa: BLE001
        # An unreadable verdict must not read as "no progress" and kill a healthy run — the one
        # direction this check may fail is OPEN (principle 13: fail open only toward keep working).
        return -1.0, 0.0, {}
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

    env = dict(os.environ, PATH=f"{NODE_PATH}:{os.environ['PATH']}")
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
    milestones = []
    if milestone_s:
        # One interval per deliverable, so a run that earns every milestone gets the full budget.
        wall = milestone_s * deliverable_count(task_dir)
    next_check = milestone_s * FIRST_MILESTONE_INTERVAL   # the 1st interval is not judged; see above
    terminal = "exited"
    while proc.poll() is None:
        elapsed = time.time() - t0
        if milestone_s and elapsed >= next_check:
            due = int(round(next_check / milestone_s))       # 1 after the 1st interval, 2 after 2nd
            score, mx, parts = score_snapshot(ws, task_dir)
            ok = score < 0 or score >= due                   # score < 0 = unreadable -> fail open
            milestones.append({"at_minutes": round(next_check / 60), "floor": due,
                               "score": None if score < 0 else score, "ok": ok,
                               "parts": {k: v.get("ok") for k, v in parts.items()}})
            print(f"[milestone] {round(next_check/60)}min  score={score}/{mx}  floor={due}  "
                  f"{'ok' if ok else 'MISS'}", flush=True)
            if not ok:
                # Confirm before killing. The snapshot is taken while the coder is writing, so a
                # single sample can catch a half-written file and score a healthy run as stalled.
                # A second reading is cheap next to discarding a good run.
                time.sleep(20)
                score2, _, parts2 = score_snapshot(ws, task_dir)
                confirmed = not (score2 < 0 or score2 >= due)
                milestones[-1].update({"recheck_score": None if score2 < 0 else score2,
                                       "confirmed": confirmed})
                print(f"[milestone] recheck score={score2}  "
                      f"{'CONFIRMED MISS' if confirmed else 'recovered'}", flush=True)
                if confirmed:
                    terminal = f"milestone-miss-{round(next_check/60)}min"
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
    session_dir = max(new_sessions, key=lambda p: p.stat().st_mtime) if new_sessions else None
    capture = collect_capture(session_dir) if session_dir else \
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

    vr = sh(sys.executable, str(task_dir / "verify.py"), str(ws),
            *([str(session_dir)] if session_dir else []), timeout=600)
    try:
        verdict = json.loads(vr.stdout)
    except Exception:  # noqa: BLE001
        verdict = {"score": 0, "max_score": 0, "success": False,
                   "verifier_error": (vr.stdout + vr.stderr)[-400:]}
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
        "milestone_minutes": args.milestone_minutes or None, "milestones": milestones or None,
        "success": bool(verdict.get("success")), "score": verdict.get("score"),
        "max_score": verdict.get("max_score"), "verify": verdict.get("parts"),
        **capture,
        "assists": collect_assists(t0, t1),
        "workspace": str(ws),
        "archive": str(archive),
        "user_install_leak": sorted(user_install_listing() - installs_before),
        "capture_dir": str(session_dir) if session_dir else None,
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
