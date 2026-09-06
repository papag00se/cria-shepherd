#!/usr/bin/env python3
"""Live end-to-end run against a REAL model — drive cria's plan loop with the Ada
Handles prompt and watch the pipeline (classify → plan → coder → massage) actually
run, without caring whether the task completes.

Unlike scripts/smoke_live.py (deterministic fake upstream), this points cria at a
real llama.cpp endpoint and plays the HARNESS side: it sends the prompt, and for
whatever tool calls cria returns it fabricates plausible tool results and loops
back — a few turns, enough to see each stage exercise the real model's real output
and confirm the assists survive it. Nothing is actually executed on disk.

    python scripts/live_model.py --endpoint http://127.0.0.1:18084 --model fabliq_8b_reasoning_q6
    python scripts/live_model.py --turns 4 --label qwopus     # after swapping 18084

SINGLE-SLOT WARNING: the target serves one request at a time. Do not run this while
another session is using the same endpoint.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cria.config import (  # noqa: E402
    Backend, Config, IndicatorsConfig, LoggingConfig, PlannerConfig, Role,
    RoutingConfig, ServerConfig, ToolsConfig, UpstreamConfig,
)
from cria.events import EventLog  # noqa: E402
from cria.server import CriaServer  # noqa: E402
from cria.upstream import Upstream  # noqa: E402
from suite import sampling  # noqa: E402

PROMPT = (
    "I would like you to write a Python Lambda handler that accepts an Ada Handle as input "
    "and resolves it to the Cardano address using the Ada Handles API (api.handle.me). The "
    "response should include the resolved address, the holder address, and the total Handles "
    "the holder possesses. Unit tests are required. Separately, create a live test that "
    "resolves the handle `goose` or `papagoose`. When you're done, add a README."
)

SYSTEM = (
    "You are a coding agent working in a repo. You have a `shell` tool and an `apply_patch` "
    "tool. Use tools to inspect and edit files. Complete the user's task."
)

SHELL_TOOL = {
    "type": "function",
    "function": {
        "name": "shell",
        "description": "Run a shell command in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "array", "items": {"type": "string"}},
                "workdir": {"type": "string"},
            },
            "required": ["command"],
        },
    },
}
APPLY_PATCH_TOOL = {
    "type": "function",
    "function": {
        "name": "apply_patch",
        "description": "Create or edit files with a patch envelope.",
        "parameters": {"type": "object", "properties": {"input": {"type": "string"}}, "required": ["input"]},
    },
}
TOOLS = [SHELL_TOOL, APPLY_PATCH_TOOL]

INTERESTING = {
    "request.recv", "response.sent", "response.error", "response.truncated",
    "decision", "route.classify", "route.classify_error", "route.classify_unparsed",
    "loop.start", "loop.item", "loop.step_done", "loop.step_incomplete", "loop.truncated",
    "loop.done", "loop.verify_error", "loop.no_shell_tool",
    "upstream.request", "upstream.first_token", "upstream.done", "upstream.error",
    "plan.drafted", "plan.error", "plan.unparsed",
}
INTERESTING_PREFIX = ("massage", "writeproxy", "indicators", "toolmenu")


def free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def post(url: str, body: dict, sid: str, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Cria-Session-Id": sid},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def get(url: str, timeout: float = 5) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except OSError:
        return 0


def detect_model(endpoint: str) -> str | None:
    """Ask the endpoint what model it currently serves (so a swap needs no --model)."""
    try:
        with urllib.request.urlopen(endpoint.rstrip("/") + "/v1/models", timeout=5) as r:
            data = json.loads(r.read()).get("data") or []
            return data[0].get("id") if data else None
    except (OSError, json.JSONDecodeError, KeyError, IndexError):
        return None


def clip(s: str, n: int = 140) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n] + "…"


def fake_tool_result(tc: dict) -> str:
    """Plausible result for a tool call so the loop keeps moving (nothing runs)."""
    fn = tc.get("function", {})
    name = fn.get("name")
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {}
    if name == "apply_patch":
        return "(patch applied)"
    cmd = args.get("command")
    cmd_s = " ".join(cmd) if isinstance(cmd, list) else str(cmd or "")
    if "base64 -d" in cmd_s and ".cria/" in cmd_s:
        return ""  # plan-file write: silent success
    return "(exit 0)"


def summarize_response(raw: bytes) -> tuple[str, list[dict], str]:
    """-> (finish_reason, tool_calls, content)"""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return "?", [], raw.decode("utf-8", "replace")[:200]
    ch = (obj.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    return ch.get("finish_reason", "?"), msg.get("tool_calls") or [], msg.get("content") or ""


def run(endpoint: str, model: str, turns: int, timeout: float, label: str) -> int:
    port = free_port()
    logdir = Path("/tmp/claude-1000/-home-jesse-src-codex-local/9b0db794-ff29-470c-9934-90172df66967/scratchpad") / f"cria-live-{label}"
    logdir.mkdir(parents=True, exist_ok=True)
    for stale in logdir.glob("cria-*.jsonl"):  # fresh log per run — don't mix traces
        stale.unlink()
    log = EventLog(level="warn", dir=str(logdir), console=False, jsonl=True)
    logpath = log.path

    try:
        role_sampling = sampling.render(label)
    except KeyError:
        role_sampling = {}

    cfg = Config(
        server=ServerConfig(host="127.0.0.1", port=port, heartbeat_seconds=5.0),
        upstream=UpstreamConfig(base_url=endpoint.rstrip("/"), timeout_seconds=int(timeout)),
        logging=LoggingConfig(level="warn", console=False, jsonl=True),
        routing=RoutingConfig(
            backends={"local": Backend(name="local", transport="http", base_url=endpoint.rstrip("/"))},
            roles={name: Role(name=name, backend="local", reasoning="on",
                              **role_sampling.get(name, {}))
                   for name in ("classifier", "reasoner", "coder", "compactor")},
            failover={"coding": ("coder",), "reasoning": ("reasoner",)},
            engagement_bias="task",
            defaults_base_url=endpoint.rstrip("/"),
        ),
        indicators=IndicatorsConfig(enabled=True, metrics=True),
        tools=ToolsConfig(cheatsheet=True),
        planner=PlannerConfig(enabled=True),
    )
    upstream = Upstream(cfg.upstream.base_url, cfg.upstream.timeout_seconds)
    cria = CriaServer(cfg, log, upstream)
    threading.Thread(target=cria.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(40):
        if get(url + "/health") == 200:
            break
        time.sleep(0.05)

    sid = f"live-{label}"
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": PROMPT}]

    print(f"\n{'='*72}\n  LIVE RUN — {label}   model={model}   endpoint={endpoint}\n{'='*72}")
    errors: list[str] = []
    try:
        for t in range(1, turns + 1):
            print(f"\n── turn {t} ── sending {len(messages)} messages …", flush=True)
            t0 = time.time()
            status, raw = post(url, {"model": model, "messages": messages, "tools": TOOLS, "stream": False}, sid, timeout)
            dt = time.time() - t0
            if status != 200:
                print(f"   HTTP {status} after {dt:.1f}s  -> {raw.decode('utf-8','replace')[:200]}")
                errors.append(f"turn {t}: HTTP {status}")
                break
            finish, tool_calls, content = summarize_response(raw)
            print(f"   HTTP 200 in {dt:.1f}s   finish={finish}   tool_calls={len(tool_calls)}")
            if content:
                print(f"   content: {clip(content, 200)}")
            for tc in tool_calls:
                fn = tc.get("function", {})
                print(f"   → tool: {fn.get('name')}  args={clip(fn.get('arguments',''), 120)}")
            if not tool_calls:
                print("   (no tool calls — loop returned a bare answer or fell through to plain routing; ending)")
                break
            # play the harness: append the assistant turn + a fabricated result per tool call
            messages = messages + [{"role": "assistant", "content": content or None, "tool_calls": tool_calls}]
            for tc in tool_calls:
                messages.append({"role": "tool", "tool_call_id": tc.get("id"), "content": fake_tool_result(tc)})
    finally:
        cria.shutdown(); cria.server_close(); log.close()

    _print_event_digest(logpath, errors)
    return 1 if errors else 0


def _print_event_digest(logpath, errors: list[str]) -> None:
    print(f"\n── cria event trace ({logpath}) ──")
    if not logpath or not Path(logpath).is_file():
        print("   (no log file)")
        return
    warn_err = 0
    for line in Path(logpath).read_text().splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = ev.get("kind", "")
        lvl = ev.get("level", "info")
        interesting = kind in INTERESTING or any(kind.startswith(p) for p in INTERESTING_PREFIX)
        if lvl in ("warn", "error"):
            warn_err += 1
            interesting = True
        if not interesting:
            continue
        turn = (ev.get("turn") or "")[:6]
        extra = {k: v for k, v in ev.items()
                 if k not in ("kind", "level", "ts", "time", "turn", "session", "msg")}
        mark = "!" if lvl in ("warn", "error") else " "
        print(f"  {mark}[{turn:<6}] {kind:<24} {clip(json.dumps(extra, ensure_ascii=False), 150)}")
    print(f"\n  {'FAIL' if errors else 'OK'} — "
          f"{'errors: ' + '; '.join(errors) if errors else 'ran without cria errors'}"
          f"   ({warn_err} warn/error events)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://127.0.0.1:18084")
    ap.add_argument("--model", default=None, help="served model id; auto-detected from /v1/models if omitted")
    ap.add_argument("--turns", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--label", default=None)
    args = ap.parse_args()
    model = args.model or detect_model(args.endpoint)
    if not model:
        print(f"cria: could not detect a model at {args.endpoint} (is the server up?)", file=sys.stderr)
        return 2
    label = args.label or model.split("_")[0]
    return run(args.endpoint, model, args.turns, args.timeout, label)


if __name__ == "__main__":
    raise SystemExit(main())
