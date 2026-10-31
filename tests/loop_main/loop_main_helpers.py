"""Shared fixtures for the loop_main shard: a bound workspace view, a recording log, scripted model boundaries,
and a fetch result built the way the real producer prints it. Only the model server and the HTTP GET are faked."""
import json
import os
import subprocess
import sys
import tempfile
from unittest import mock

import pytest

from cria import fetchfacts, wsview, writeproxy
from cria.loop import Loop, LoopContext, LoopStore, PlanSession
from cria.plan import Plan, PlanItem

SHELL = {"type": "function", "function": {"name": "shell", "parameters": {
    "type": "object", "properties": {"command": {"type": "array"}}}}}


@pytest.fixture(autouse=True)
def loop_main_local_view():
    """No harness here: the workspace really is this machine's disk."""
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)


class Rlog:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


class Chat:
    """A model boundary: answers the scripted completions in order (the last repeats) and records every body."""

    def __init__(self, *replies):
        self.replies, self.bodies = list(replies), []

    def __call__(self, body, rlog):
        self.bodies.append(body)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return json.dumps(reply).encode()


def completion(content=None, *calls):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = [{"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                             for i, (n, a) in enumerate(calls)]
    return {"choices": [{"message": msg, "finish_reason": "stop"}]}


def acting():
    return completion(None, ("shell", {"command": ["sh", "-c", "true"]}))


def plan_off_loop(coder, *, store=None, reasoner=None, **ctx):
    """A Loop wired the way production wires plan-off (planner_enabled left at its default)."""
    return Loop(LoopContext(planner=None, coder_chat=coder, reasoner_chat=reasoner or coder, runs_dir="", **ctx),
                store or LoopStore())


def synthetic(task="build it", pages=None):
    return PlanSession(plan=Plan(id="p", task=task, created="c", items=[PlanItem(task)]), synthetic=True, fetched_pages=pages)


def body(task="build an ada handle resolver", tools=(SHELL,)):
    return {"messages": [{"role": "user", "content": task}], "tools": list(tools), "stream": True}


_FETCHES = [0]


def fetch_pair(url, *, status=200, routes=(), shapes=(), content="page"):
    """``[assistant web_fetch call, tool result]`` as the harness delivers it: the REAL lowering composes the
    program, it is really run, and the real inbound pass lifts its typed record. Only the HTTP fetch is replaced."""
    _FETCHES[0] += 1
    cid = f"fetch-{_FETCHES[0]}"
    facts = {"url": url, "status": f"HTTP {status}", "routes": list(routes),
             "shapes": [fetchfacts.report(s) for s in shapes], "catalog": [], "observed": ""}
    comp = {"choices": [{"message": {"tool_calls": [{"id": cid, "type": "function", "function": {
        "name": "web_fetch", "arguments": json.dumps({"url": url})}}]}}]}
    with mock.patch.object(writeproxy.webfetch, "fetch_nav_result", return_value=(content, False, status, facts)):
        writeproxy.translate_outbound(comp, {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}},
                                      injected={"web_fetch"}, workspace_root="/w")
    tc = comp["choices"][0]["message"]["tool_calls"][0]
    py = os.path.join(tempfile.mkdtemp(prefix="harness-bin-"), "python3")      # the harness has python3 and coreutils only
    os.symlink(os.path.realpath(sys.executable), py)
    with tempfile.TemporaryDirectory() as cwd:
        env = {"PATH": f"{os.path.dirname(py)}:/usr/bin:/bin", "HOME": cwd, "TMPDIR": cwd, "LC_ALL": "C"}
        run = subprocess.run(["bash", "-c", json.loads(tc["function"]["arguments"])["cmd"]], cwd=cwd, env=env,
                             capture_output=True, text=True)
        raw = "Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code 0\nOriginal token count: 9\nOutput:\n" + run.stdout + run.stderr
        token = wsview.bind(wsview.View(cwd, "uv"))
        try:
            return writeproxy.represent_inbound(
                [{"role": "assistant", "tool_calls": [tc]}, {"role": "tool", "tool_call_id": cid, "content": raw}],
                workspace_root=cwd)
        finally:
            wsview.unbind(token)
