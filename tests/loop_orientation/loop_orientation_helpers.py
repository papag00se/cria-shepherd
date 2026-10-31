"""Shared fixtures for the loop_orientation shard: a real Loop driver, a recording log, a bound workspace view."""
import io
import json

import pytest

from cria import wsview
from cria.loop import Loop, LoopContext, PlanSession
from cria.plan import Plan, PlanItem
from cria.upstream import Upstream

KEY = "sid:k"
TASK = "Perform the requested action."
WRITE = {"type": "function", "function": {"name": "write_file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
    "required": ["path", "content"]}}}

@pytest.fixture(autouse=True)
def local_workspace_view():
    """No harness here: the workspace really is this machine's disk."""
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)

class Log:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))

    def kinds(self):
        return [kind for kind, _ in self.events]

def driver():
    """A real Loop over a fake-URL Upstream with one synthetic plan-off session stored at KEY."""
    up = Upstream("http://fixture", context_window=16384, capture_dir=None, capture_rendered=False)
    loop = Loop(LoopContext(planner=None, coder_chat=up.chat, planner_enabled=False, reasoner_chat=None, runs_dir="",
                            workspace_root="", self_compact=False, focus_trim=False, assists=False, satisfaction_check_start=0))
    session = PlanSession(plan=Plan(id="t", task=TASK, created="now", items=[PlanItem(TASK)]), synthetic=True, plan_off=True)
    loop._store.put(KEY, session)
    return loop, session, {"model": "fixture", "messages": [{"role": "user", "content": TASK}], "tools": [WRITE]}

def transport(replies):
    """Fake model server: /v1/chat/completions answers from `replies` (exceptions are raised); returns (send, posted)."""
    answers, posted = iter(replies), []

    def send(request, **_):
        if request.full_url.endswith("/v1/chat/completions"):
            posted.append(json.loads(request.data))
            reply = next(answers)
            if isinstance(reply, BaseException):
                raise reply
            return io.BytesIO(json.dumps(reply).encode())
        return io.BytesIO(b'{"tokens":[1,2,3]}' if request.full_url.endswith("/tokenize") else b'{"data":[]}')
    return send, posted

def tool_reply(cid):
    return {"choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": "read_file", "arguments": '{"path":"next.txt"}'}}]}}]}
