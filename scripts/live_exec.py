#!/usr/bin/env python3
"""Run the Ada Handles prompt live against the served model through cria with REAL execution in a throwaway
git workspace — the 'run the prompt live' the goal loop needs (live_model.py fakes results; this
one runs them). Each cria-lowered `shell` command is executed for real in the workspace, its real
output fed back, ~N turns. cria's command_safety + dirguard (workspace bounded to the throwaway
<cwd>) are the safety layer; network fetches are read-only; single-slot :18084.

    python scripts/live_exec.py --turns 40
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dataclasses import replace  # noqa: E402

from cria import brave  # noqa: E402
from cria.config import Config  # noqa: E402
from cria.envfile import load_env_file  # noqa: E402
from cria.events import EventLog  # noqa: E402
from cria.server import CriaServer  # noqa: E402
from cria.upstream import Upstream  # noqa: E402
from live_model import TOOLS, clip, detect_model, free_port, get, post, summarize_response  # noqa: E402

# The GOAL's exact target prompt — a plain Python SCRIPT (NOT live_model.py's "Lambda handler",
# which derails the planner into AWS deployment).
PROMPT = ("I would like you to write a Python script that accepts an Ada Handle as input and resolves "
          "it to the Cardano address using the Ada Handles API (api.handle.me). The response should "
          "include the resolved address, the holder address, and the total Handles the holder possesses. "
          "Unit tests are required. Separately, create a live test that resolves the handle `goose` or "
          "`papagoose`. When you're done, add a README that explains how to install and run the script "
          "and the tests.")

SYSTEM = ("You are a coding agent working in a repo. You have a `shell` tool and an `apply_patch` "
          "tool. Use tools to inspect, fetch, and edit files. Complete the user's task fully.")


def exec_shell(cmd, workdir: str, timeout: int = 120) -> str:
    if isinstance(cmd, str):
        cmd = ["bash", "-lc", cmd]
    if not isinstance(cmd, list) or not cmd:
        return "exec error: empty command\nProcess exited with code 1"
    try:
        r = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        return f"{out}\nProcess exited with code {r.returncode}"
    except subprocess.TimeoutExpired:
        return "Process exited with code 124 (timeout)"
    except Exception as e:  # noqa: BLE001
        return f"exec error: {e}\nProcess exited with code 1"


def tool_result(tc: dict, workdir: str) -> str:
    fn = tc.get("function", {})
    name = fn.get("name")
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {}
    if name == "shell":
        return exec_shell(args.get("command"), args.get("workdir") or workdir)
    if name == "apply_patch":
        return "apply_patch NOT executed by this harness — write files via the shell heredoc instead."
    return "(exit 0)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://127.0.0.1:18084")
    ap.add_argument("--turns", type=int, default=40)
    ap.add_argument("--timeout", type=float, default=600)
    args = ap.parse_args()
    model = detect_model(args.endpoint)
    if not model:
        print(f"could not detect a model at {args.endpoint} (is the server up?)", file=sys.stderr)
        return 2

    ws = tempfile.mkdtemp(prefix="cria-ada-")
    subprocess.run(["git", "init", "-q"], cwd=ws)
    print(f"workspace: {ws}   model: {model}")

    port = free_port()
    logdir = Path(tempfile.mkdtemp(prefix="cria-ada-log-"))
    # Use the REAL config (~/.cria/cria.toml) so the run matches production exactly; only
    # override the port (avoid the live :18085) and route logs/captures to our own dir.
    cfg = Config.load()
    _cap = os.environ.get("LIVE_EXEC_CAP")  # set to capture every per-call body for debugging
    cfg = replace(cfg, server=replace(cfg.server, port=port),
                  logging=replace(cfg.logging, level="info", console=False, dir=str(logdir),
                                  capture_calls=bool(_cap), capture_dir=(_cap or str(logdir))))
    if cfg.env_file:  # load the Brave key so web_search works
        allow = {brave.API_KEY_ENV} | {b.api_key_env for b in cfg.routing.backends.values() if b.api_key_env}
        load_env_file(cfg.env_file, allow)
    log = EventLog(level="info", dir=str(logdir), console=False, jsonl=True)
    upstream = Upstream(cfg.upstream.base_url, cfg.upstream.timeout_seconds,
                        capture_dir=Path(_cap) if _cap else None)
    cria = CriaServer(cfg, log, upstream)
    threading.Thread(target=cria.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        if get(url + "/health") == 200:
            break
        time.sleep(0.05)

    env_ctx = (f"# AGENTS.md instructions\n<INSTRUCTIONS>Complete the task; do not guess API endpoints — "
               f"fetch the real docs.</INSTRUCTIONS>\n<environment_context><cwd>{ws}</cwd><shell>bash</shell>"
               f"</environment_context>")
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": env_ctx},
                {"role": "user", "content": PROMPT}]
    sid = "live-exec"
    no_tool_streak = 0
    try:
        for t in range(1, args.turns + 1):
            status, raw = post(url, {"model": model, "messages": messages, "tools": TOOLS, "stream": False}, sid, args.timeout)
            if status != 200:
                print(f"turn {t}: HTTP {status} -> {raw.decode('utf-8','replace')[:160]}")
                break
            finish, tool_calls, content = summarize_response(raw)
            names = [(tc.get('function') or {}).get('name') for tc in tool_calls]
            print(f"turn {t:2d}: finish={finish} tools={names} " + (f"content={clip(content,90)}" if content else ""), flush=True)
            messages = messages + [{"role": "assistant", "content": content or None, "tool_calls": tool_calls or None}]
            if not tool_calls:
                no_tool_streak += 1
                if no_tool_streak >= 3:
                    print("   (3 no-tool turns — ending)")
                    break
                messages.append({"role": "user", "content": "Continue. Take the next concrete action now via the shell tool (fetch docs, write a file, or run tests)."})
                continue
            no_tool_streak = 0
            for tc in tool_calls:
                res = tool_result(tc, ws)
                messages.append({"role": "tool", "tool_call_id": tc.get("id"), "content": res})
    finally:
        cria.shutdown(); cria.server_close(); log.close()

    # --- outcome report ---
    print(f"\n{'='*60}\nWORKSPACE {ws}\n{'='*60}")
    subprocess.run(["ls", "-la", ws])
    print("\n--- py files parse? + endpoint used? ---")
    for p in Path(ws).rglob("*.py"):
        if "/.git/" in str(p):
            continue
        src = p.read_text(errors="replace")
        ok = subprocess.run([sys.executable, "-m", "py_compile", str(p)], capture_output=True).returncode == 0
        ep = "/handles/" in src
        print(f"  {p.relative_to(ws)}: parses={ok} uses_/handles/={ep}")
    print(f"\nlog dir: {logdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
