#!/usr/bin/env python3
"""Live end-to-end smoke test for cria — proves the assists actually fire over
real HTTP, without touching the real model on :18084.

It stands up two real servers on ephemeral ports:

  * a FAKE upstream that returns *deliberately malformed* completions on demand
    (Hermes-wrapped tool calls, fenced args, a write_file the harness can't run,
    truncated output, an SSE stream), keyed off the request's ``model`` field;
  * a real ``CriaServer`` pointed at that fake.

Then it fires real HTTP requests at cria and asserts each response came back
*repaired* — i.e. the massage / writeproxy / indicator / heartbeat / cheat-sheet
assists ran end-to-end through the actual handler pipeline, not a unit-test stub.

Run:  python scripts/smoke_live.py        (exit 0 = all green)

This is a plumbing/assist check, NOT a full agentic session — routing, the
classifier, and the plan loop are intentionally left off so the fake can be
driven deterministically by ``model``. Nothing here contacts :18084.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Import cria from the repo without installing it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cria.config import (  # noqa: E402
    Config,
    IndicatorsConfig,
    LoggingConfig,
    PlannerConfig,
    RoutingConfig,
    ServerConfig,
    ToolsConfig,
    UpstreamConfig,
)
from cria.events import EventLog  # noqa: E402
from cria.server import CriaServer  # noqa: E402
from cria.upstream import Upstream  # noqa: E402

SHELL_TOOL = {
    "type": "function",
    "function": {
        "name": "shell",
        "description": "run a shell command",
        "parameters": {"type": "object", "properties": {"command": {"type": "array"}}},
    },
}
WRITE_TOOL = {"type": "function", "function": {"name": "write_file"}}
PATCH_TOOL = {"type": "function", "function": {"name": "apply_patch"}}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --------------------------------------------------------------------------- fake

def _completion(model: str, message: dict, finish: str = "stop") -> dict:
    return {
        "id": "cmpl-smoke",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
    }


def _canned(model: str) -> dict:
    """The malformed / raw completions the fake upstream emits, by model name."""
    if model == "smoke-pass":
        return _completion(model, {"role": "assistant", "content": "Hello from upstream."})
    if model == "smoke-hermes":
        # Tool call leaked into content as a Hermes <tool_call> block.
        content = 'Sure, listing.\n<tool_call>\n{"name": "shell", "arguments": {"command": ["ls", "-la"]}}\n</tool_call>'
        return _completion(model, {"role": "assistant", "content": content})
    if model == "smoke-fenced":
        # A real tool_call, but arguments wrapped in a ```json fence (invalid JSON string).
        return _completion(model, {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "shell", "arguments": '```json\n{"command": ["echo", "hi"]}\n```'},
            }],
        })
    if model == "smoke-writefile":
        # write_file — which the harness (shell-only) cannot run; cria must lower it.
        return _completion(model, {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_2", "type": "function",
                "function": {"name": "write_file", "arguments": json.dumps({"path": "foo.py", "content": "print(1)\n"})},
            }],
        })
    if model == "smoke-trunc":
        return _completion(model, {"role": "assistant", "content": "def foo():\n    x = "}, finish="length")
    # default
    return _completion(model, {"role": "assistant", "content": "ok"})


def _sse_stream() -> bytes:
    """A streamed response with an initial idle gap (so the heartbeat must fire)."""
    def chunk(delta: dict, finish=None) -> bytes:
        obj = {"id": "c", "object": "chat.completion.chunk",
               "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        return b"data: " + json.dumps(obj).encode() + b"\n\n"
    parts = [chunk({"role": "assistant"})]
    for tok in ["Hello", " ", "world", "!"]:
        parts.append(chunk({"content": tok}))
    parts.append(chunk({}, finish="stop"))
    parts.append(b"data: [DONE]\n\n")
    return b"".join(parts)


class FakeUpstream(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    last_request: dict | None = None


class FakeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silence
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = json.loads(self.rfile.read(length)) if length else {}
        self.server.last_request = body
        model = body.get("model", "")
        if body.get("stream"):
            time.sleep(0.35)  # idle gap → forces at least one cria heartbeat
            payload = _sse_stream()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            payload = json.dumps(_canned(model)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)


# --------------------------------------------------------------------------- client

def post(cria_url: str, body: dict) -> tuple[int, bytes]:
    req = urllib.request.Request(cria_url + "/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def first_message(raw: bytes) -> dict:
    return json.loads(raw)["choices"][0]["message"]


# --------------------------------------------------------------------------- scenarios

def run_scenarios(cria_url: str, fake: FakeUpstream) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    # 1. health
    st, _ = get(cria_url + "/health")
    check("health endpoint 200", st == 200, f"status={st}")

    # 2. buffered passthrough + indicator decoration
    st, raw = post(cria_url, {"model": "smoke-pass", "messages": [{"role": "user", "content": "hi"}]})
    txt = first_message(raw).get("content", "")
    check("buffered passthrough", st == 200 and "Hello from upstream." in txt, repr(txt)[:60])

    # 3. Hermes leaked tool call → structured tool_calls
    st, raw = post(cria_url, {"model": "smoke-hermes", "tools": [SHELL_TOOL],
                              "messages": [{"role": "user", "content": "list files"}]})
    msg = first_message(raw)
    tc = msg.get("tool_calls") or []
    name = tc[0]["function"]["name"] if tc else None
    check("massage: Hermes leak → tool_calls", name == "shell", f"tool_calls={len(tc)} name={name}")

    # 4. fenced JSON args → valid JSON arguments
    st, raw = post(cria_url, {"model": "smoke-fenced", "tools": [SHELL_TOOL],
                              "messages": [{"role": "user", "content": "echo"}]})
    tc = first_message(raw).get("tool_calls") or []
    ok, parsed = False, None
    if tc:
        try:
            # The fence must be gone: arguments now parse as valid JSON. (The command
            # itself may also be canonicalized to `bash -lc …` by shell normalization.)
            parsed = json.loads(tc[0]["function"]["arguments"])
            ok = "echo" in json.dumps(parsed) and "hi" in json.dumps(parsed)
        except json.JSONDecodeError:
            ok = False
    check("massage: fenced args repaired", ok, f"args={parsed}")

    # 5. write_file (shell-only advertised) → lowered to a base64 shell command
    st, raw = post(cria_url, {"model": "smoke-writefile", "tools": [SHELL_TOOL],
                              "messages": [{"role": "user", "content": "write foo.py"}]})
    tc = first_message(raw).get("tool_calls") or []
    cmd = ""
    if tc:
        fn = tc[0]["function"]
        args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"]
        c = args.get("command")
        cmd = " ".join(c) if isinstance(c, list) else str(c)
    lowered = bool(tc) and tc[0]["function"]["name"] == "shell" and "base64" in cmd and "foo.py" in cmd
    check("writeproxy: write_file → shell/base64", lowered, cmd[:70])

    # 6. cheat-sheet reached the model (inspect what the fake received)
    lr = fake.last_request or {}
    sys_msgs = [m for m in lr.get("messages", []) if m.get("role") == "system"]
    joined = " ".join(m.get("content", "") for m in sys_msgs)
    check("toolmenu: cheat-sheet injected to model", "write_file(path" in joined,
          f"system_msgs={len(sys_msgs)}")

    # 7. truncation guard surfaces a note
    st, raw = post(cria_url, {"model": "smoke-trunc", "messages": [{"role": "user", "content": "go"}]})
    txt = first_message(raw).get("content", "")
    check("guard: output-truncation noted", "truncated" in txt.lower(), repr(txt)[-60:])

    # 8. streaming passthrough + heartbeat during the idle gap
    st, raw = post(cria_url, {"model": "smoke-stream", "stream": True,
                              "messages": [{"role": "user", "content": "stream"}]})
    text = raw.decode("utf-8", "replace")
    assembled = ""
    for line in text.splitlines():
        if line.startswith("data: ") and "[DONE]" not in line:
            try:
                delta = json.loads(line[6:])["choices"][0].get("delta", {})
                assembled += delta.get("content", "")
            except (json.JSONDecodeError, KeyError, IndexError):
                pass
    heartbeat = text.startswith(":") or "\n:" in text  # SSE comment lines
    check("stream: content + [DONE]", "Hello world!" in assembled and "[DONE]" in text, repr(assembled)[:40])
    check("stream: heartbeat covered idle gap", heartbeat, "no ':' comment seen" if not heartbeat else "")

    return results


# --------------------------------------------------------------------------- main

def main() -> int:
    fake_port, cria_port = free_port(), free_port()
    fake = FakeUpstream(("127.0.0.1", fake_port), FakeHandler)
    threading.Thread(target=fake.serve_forever, daemon=True).start()

    log = EventLog(level="warn", dir=None, console=False, jsonl=False)
    cfg = Config(
        server=ServerConfig(host="127.0.0.1", port=cria_port, heartbeat_seconds=0.15),
        upstream=UpstreamConfig(base_url=f"http://127.0.0.1:{fake_port}", timeout_seconds=30),
        logging=LoggingConfig(level="warn", console=False, jsonl=False),
        routing=RoutingConfig(),          # no models/failover → classifier + router + loop stay OFF
        indicators=IndicatorsConfig(enabled=True, metrics=True),
        tools=ToolsConfig(cheatsheet=True),
        planner=PlannerConfig(enabled=True),  # no reasoner/coder model → loop stays OFF anyway
    )
    upstream = Upstream(cfg.upstream.base_url, cfg.upstream.timeout_seconds)
    cria = CriaServer(cfg, log, upstream)
    threading.Thread(target=cria.serve_forever, daemon=True).start()

    cria_url = f"http://127.0.0.1:{cria_port}"
    # wait for readiness
    for _ in range(50):
        try:
            if get(cria_url + "/health")[0] == 200:
                break
        except OSError:
            time.sleep(0.05)

    try:
        results = run_scenarios(cria_url, fake)
    finally:
        cria.shutdown(); cria.server_close()
        fake.shutdown(); fake.server_close()
        log.close()

    print("\n  cria live smoke — assists over real HTTP (fake upstream, no :18084)\n")
    passed = 0
    for name, ok, detail in results:
        mark = "\033[32mPASS\033[0m" if ok else "\033[31mFAIL\033[0m"
        line = f"  [{mark}] {name}"
        if detail and not ok:
            line += f"   -> {detail}"
        print(line)
        passed += ok
    total = len(results)
    print(f"\n  {passed}/{total} green\n")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
