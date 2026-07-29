#!/usr/bin/env python3
"""Suite runner — one cell of the test matrix per invocation.

Provisions a throwaway workspace, points the rig at the requested model + planner setting,
drives one harness run of the task prompt under a HARD 30-minute wall clock (operator's call:
no call budget — slow models surfacing as budget-kills is itself signal), then collects
metrics from cria's own capture/events, runs the task's deterministic verifier, and appends
one JSON row to suite/results/results.jsonl.

Kill mechanics follow the runctl scars: match the codex process list explicitly (ps + grep of
the exec pattern, excluding shells), never `pkill -f` (it matches the invoking shell).

Usage: run.py --task ada-handles --model ternary-bonsai --harness codex --planner off [--note x]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"
CALLS_DIR = Path.home() / ".cria" / "calls"
EVENTS_DIR = Path.home() / ".cria" / "logs"
CRIA_TOML = Path.home() / ".cria" / "cria.toml"
WALL_SECONDS = 30 * 60
KILL_GRACE = 20

# fleet model name -> systemd service (one model at a time on the 3080)
SERVICES = {
    "ternary-bonsai": "llama-ternary-bonsai",
    "qwythos": "llama-qwythos-q6",
    "qwopus": "llama-qwopus-q6",
    "ornith": "llama-ornith-q6",
    "gemma4": "llama-gemma4-q4km",
    "mellum2": "llama-mellum2-q4",
    "fabliq": "llama-fabliq-reasoning-q6",
    "lfm25": "llama-lfm25-q6",
    "nemotron-elastic": "llama-nemotron-elastic",
    "zaya1": "llama-zaya1",
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


def set_planner(enabled: bool) -> None:
    text = CRIA_TOML.read_text()
    new = re.sub(r"(\[planner\][^\[]*?enabled\s*=\s*)(true|false)",
                 lambda m: m.group(1) + ("true" if enabled else "false"), text, count=1)
    if new == text and f"= {'true' if enabled else 'false'}" not in text:
        raise RuntimeError("could not toggle [planner].enabled in cria.toml")
    CRIA_TOML.write_text(new)
    sh("sudo", "-n", "systemctl", "restart", "cria.service", timeout=60)
    if not wait_health("http://127.0.0.1:18085/health"):
        raise RuntimeError("cria never became healthy after planner toggle")


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
        except OSError:
            continue
    interesting = ("steer", "loop.replan", "plan.noise", "plan.missing", "searchloop",
                   "loop.truncated", "gate", "repetition", "wheel", "flail", "tunnel",
                   "editrecovery", "rumination", "loop.probe", "compact")
    # loop.compaction_reframed fires on every REQUEST that re-reads a compacted history (stateless
    # re-processing, by design) — counting it as an assist inflated one run by 85. Occurrences of
    # compaction itself are context.self_compact / route.compaction.
    kinds.pop("loop.compaction_reframed", None)
    return {k: v for k, v in kinds.items() if any(k.startswith(p) or p in k for p in interesting)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--model", required=True, choices=sorted(SERVICES))
    ap.add_argument("--harness", default="codex", choices=sorted(HARNESSES))
    ap.add_argument("--planner", required=True, choices=["on", "off"])
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    task_dir = SUITE / "tasks" / args.task
    prompt = (task_dir / "prompt.txt").read_text().strip()
    run_id = f"{args.task}_{args.model}_{args.harness}_p{args.planner}_{int(time.time())}"
    ws = Path(tempfile.mkdtemp(prefix=f"suite-{run_id}-", dir="/tmp"))
    log_path = SUITE / "results" / f"{run_id}.log"

    swap_model(args.model)
    set_planner(args.planner == "on")
    sh("git", "-C", str(ws), "init", "-q")
    before_sessions = set(p.name for p in CALLS_DIR.glob("2*"))

    env = dict(os.environ, PATH=f"{NODE_PATH}:{os.environ['PATH']}")
    t0 = time.time()
    with open(log_path, "w") as lf:
        proc = subprocess.Popen(HARNESSES[args.harness](prompt), cwd=ws,
                                stdout=lf, stderr=subprocess.STDOUT, env=env,
                                start_new_session=True)
    terminal = "exited"
    while proc.poll() is None:
        if time.time() - t0 > WALL_SECONDS:
            terminal = "budget-killed"
            for pid in codex_pids():
                sh("kill", "-INT", str(pid))
            time.sleep(KILL_GRACE)
            for pid in codex_pids():
                sh("kill", "-9", str(pid))
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
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

    vr = sh(sys.executable, str(task_dir / "verify.py"), str(ws), timeout=600)
    try:
        verdict = json.loads(vr.stdout)
    except Exception:  # noqa: BLE001
        verdict = {"score": 0, "max_score": 0, "success": False,
                   "verifier_error": (vr.stdout + vr.stderr)[-400:]}

    row = {
        "run_id": run_id, "task": args.task, "model": args.model, "harness": args.harness,
        "planner": args.planner, "note": args.note,
        "started": t0, "wall_seconds": round(t1 - t0, 1), "terminal": terminal,
        "success": bool(verdict.get("success")), "score": verdict.get("score"),
        "max_score": verdict.get("max_score"), "verify": verdict.get("parts"),
        **capture,
        "assists": collect_assists(t0, t1),
        "workspace": str(ws),
        "archive": str(archive),
        "capture_dir": str(session_dir) if session_dir else None,
        "harness_log": str(log_path),
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS, "a") as fh:
        fh.write(json.dumps(row) + "\n")
    print(json.dumps({k: row[k] for k in
                      ("run_id", "terminal", "success", "score", "wall_seconds",
                       "calls", "avg_tok_s")}, indent=1))


if __name__ == "__main__":
    main()
