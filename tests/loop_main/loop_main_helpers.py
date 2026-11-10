"""Shared fixtures for the loop_main shard: a bound workspace view, a recording log, scripted model boundaries,
and a fetch result built the way the real producer prints it. Only the model server and the HTTP GET are faked."""
import json
from unittest import mock

import pytest

from cria import fetchfacts, wsview, writeproxy
from cria.answerops import LedgerAnswer
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


@pytest.fixture(autouse=True)
def loop_main_private_home(tmp_path, monkeypatch):
    """cria's key and operation ledger live under CRIA_HOME: every test gets its own, beside the workspace and never in it."""
    from cria import privatepaths
    home = tmp_path.parent / (tmp_path.name + ".home")
    home.mkdir()
    monkeypatch.setattr(privatepaths, "CRIA_HOME", home / ".cria")


def plan_off_loop(coder, *, store=None, reasoner=None, **ctx):
    """A Loop wired the way production wires plan-off (planner_enabled left at its default), with cria's operation engine behind its
    inventory (the server's `Ops`): `drive_with_ops` plays the server's part of answering the engine's own calls."""
    from cria.ops import Ops
    ops = Ops()
    ctx.setdefault("issue_inventory", ops.issue_inventory)
    ctx.setdefault("inventory_result", ops.inventory_of)
    return Loop(LoopContext(planner=None, coder_chat=coder, reasoner_chat=reasoner or coder,
                            reasoner_buffered_chat=reasoner or coder, runs_dir="", **ctx),
                store or LoopStore())


from survey_fixtures import command_text, drive_with_ops, run_call  # noqa: E402,F401  (the server's part, shared with the orientation shard)


def drive_after_initial_inventory(loop, request, key, classification, rlog, *, pasted_delivery=None):
    """Run cria's own inventory turns before an unrelated driver scenario."""
    deliveries = []
    result, _ = drive_with_ops(loop, request, request["messages"], key, classification, rlog, before_drive=deliveries.clear,
                               pasted_delivery=deliveries.append if pasted_delivery else None)
    if pasted_delivery is not None:
        for deliver in deliveries:
            pasted_delivery(deliver)
    return result


def synthetic(task="build it", pages=None):
    return PlanSession(plan=Plan(id="p", task=task, created="c", items=[PlanItem(task)]), synthetic=True, fetched_pages=pages)


def body(task="build an ada handle resolver", tools=(SHELL,)):
    return {"messages": [{"role": "user", "content": task}], "tools": list(tools), "stream": True}


_FETCHES = [0]


def fetch_pair(url, *, status=200, routes=(), shapes=(), content="page"):
    """``[assistant web_fetch call, tool result]`` as the history readers get them: the REAL lowering composes the answer (what the model is told and the
    typed facts of the fetch), the engine's final for it is what that answer is (:class:`answerops.LedgerAnswer`), and the real inbound pass lifts the typed
    fact. Only the HTTP fetch is replaced."""
    _FETCHES[0] += 1
    cid = f"fetch-{_FETCHES[0]}"
    facts = {"url": url, "status": f"HTTP {status}", "routes": list(routes),
             "shapes": [fetchfacts.report(s) for s in shapes], "catalog": [], "observed": ""}
    arguments = json.dumps({"url": url})
    comp = {"choices": [{"message": {"tool_calls": [{"id": cid, "type": "function", "function": {"name": "web_fetch", "arguments": arguments}}]}}]}
    told = []

    def issue_answer(call, args, answer):
        told.append(answer)
        return {"id": "ctx_x", "type": "function", "function": {"name": "exec_command", "arguments": json.dumps({"cmd": "true"})}}
    with mock.patch.object(writeproxy.webfetch, "fetch_nav_result", return_value=(content, False, status, facts)):
        writeproxy.translate_outbound(comp, {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}},
                                      injected={"web_fetch"}, workspace_root="/w", issue_answer=issue_answer)
    answer = told[0]
    token = wsview.bind(wsview.View("/w", "uv"))
    try:
        return writeproxy.represent_inbound(
            [{"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {"name": "web_fetch", "arguments": arguments}}]},
             {"role": "tool", "tool_call_id": cid, "content": answer.text}],
            workspace_root="/w", ledger_outcomes={cid: answer.outcome},
            ledger_answers={cid: LedgerAnswer("web_fetch", arguments, answer.outcome, answer.text, answer.rep)})
    finally:
        wsview.unbind(token)
