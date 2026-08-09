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
    budget; a stalled one is killed after the first interval instead of burning the full wall. Which
    deliverable lands first does not matter — only the count does.

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
    "dolphin3": "llama-dolphin3",
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


def wait_health(url: str, tries=30, delay=10) -> bool:
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


def user_site_listing() -> set:
    """Top-level names in the user's site-packages — the leak tripwire. Runs under --yolo can
    pip-install into the REAL user site (measured: an editable install of a suite /tmp workspace via
    a .pth, a broken resolver.py shadowing `import resolver` for every later run AND the verifier —
    two weeks of cross-run poisoning found only by a capture walk). The delta is recorded per row so
    contamination is evidence, never a silent confound; nothing is prevented or cleaned here."""
    try:
        return set(os.listdir(site.getusersitepackages()))
    except OSError:
        return set()


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
    interesting = ("steer", "loop.replan", "plan.noise", "plan.missing", "searchloop",
                   "loop.truncated", "gate", "repetition", "wheel", "flail", "tunnel",
                   "editrecovery", "rumination", "loop.probe", "compact", "floor_over_budget")
    # loop.compaction_reframed fires on every REQUEST that re-reads a compacted history (stateless
    # re-processing, by design) — counting it as an assist inflated one run by 85. Occurrences of
    # compaction itself are context.self_compact / route.compaction.
    kinds.pop("loop.compaction_reframed", None)
    return {k: v for k, v in kinds.items() if any(k.startswith(p) or p in k for p in interesting)}


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
    snap = Path(tempfile.mkdtemp(prefix="milestone-snap-", dir="/tmp"))
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
    ws = Path(tempfile.mkdtemp(prefix=f"suite-{run_id}-", dir="/tmp"))
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
    site_before = user_site_listing()

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
    next_check = milestone_s
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

    vr = sh(sys.executable, str(task_dir / "verify.py"), str(ws),
            *([str(session_dir)] if session_dir else []), timeout=600)
    try:
        verdict = json.loads(vr.stdout)
    except Exception:  # noqa: BLE001
        verdict = {"score": 0, "max_score": 0, "success": False,
                   "verifier_error": (vr.stdout + vr.stderr)[-400:]}

    row = {
        "run_id": run_id, "task": args.task, "model": args.model, "harness": args.harness,
        "planner": args.planner, "note": args.note, "sampling": spec,
        "started": t0, "wall_seconds": round(t1 - t0, 1), "terminal": terminal,
        "milestone_minutes": args.milestone_minutes or None, "milestones": milestones or None,
        "success": bool(verdict.get("success")), "score": verdict.get("score"),
        "max_score": verdict.get("max_score"), "verify": verdict.get("parts"),
        **capture,
        "assists": collect_assists(t0, t1),
        "workspace": str(ws),
        "archive": str(archive),
        "site_packages_leak": sorted(user_site_listing() - site_before),
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


if __name__ == "__main__":
    main()
