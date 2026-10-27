"""The production author must not ship a structurally invalid blind rewrite.

Scripted judgments exercise control flow, not semantic classifier accuracy.
"""
import json
import tempfile
import types

import pytest

from cria import loop, prompts, wsview
from cria.config import Role


class Log:
    def __init__(self):
        self.events = []

    def emit(self, name, **fields):
        self.events.append((name, fields))


class Dictation:
    def __init__(self):
        self.calls = []

    def judge(self, family, state, *, rlog=None):
        self.calls.append(next(iter(state.values())))
        return "DICTATES" if len(self.calls) == 1 else "DESCRIBES"


ORIGINAL = "Replace the failing call with parser.parse_all(rows) and verify the build."
# Original run03 0079 public rewrite; a native DESCRIBES is deliberately scripted.
MULTI = ("Make line 253 stop calling mergeAll and instead fold each entry of rightTask.local into local "
         "with BigDecimal addition, matching line 198. Run mvn -q compile to confirm it passes before "
         "writing REVIEW.md.")
SINGLE = "Inspect the parser and make the current build check pass."


@pytest.mark.parametrize("tooled", [False, True])
@pytest.mark.parametrize("rewrite,expected", [
    (MULTI, None),
    (SINGLE, SINGLE),
    ("Inspect the parser signatures before choosing an approach.",
     "Inspect the parser signatures before choosing an approach."),
    ("Compare repeated results for the same feed against the baseline.",
     "Compare repeated results for the same feed against the baseline."),
    ("Implement the task's required malformed-row reporting.",
     "Implement the task's required malformed-row reporting."),
])
def test_author_readmits_actual_rewrite_shape(tooled, rewrite, expected):
    calls = []
    log = Log()
    runtime = Dictation()

    def chat(body, rlog):
        system = body["messages"][0]["content"]
        calls.append((rlog.phase, system))
        text = rewrite if system == prompts.load("steer_restate") else ORIGINAL
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": text}}]}).encode()

    state = types.SimpleNamespace(gate_stall=3, recent_writes=[], spin_path="",
                                  steered_checks_text="", fetched_pages={}, last_gate_flag="",
                                  refused_names=[])
    body = {"messages": [{"role": "user", "content": "Repair the importer."}], "tools": []}
    with tempfile.TemporaryDirectory() as root:
        token = None
        if tooled:
            view = wsview.View(root)
            view._ingest_tree("F\t0\t0\tImporter.java", complete=True)
            token = wsview.bind(view)
        try:
            result = loop.author_steer(chat, Role(name="reasoner", backend="local"),
                                       root if tooled else "", state, body, log,
                                       condition="thrash", system1=runtime)
        finally:
            if token is not None:
                wsview.unbind(token)
    assert result == expected
    assert [phase for phase, _ in calls] == ["reasoner", "steer-code"]
    assert runtime.calls == [ORIGINAL, rewrite]
    assert not any(name in ("loop.steer_answer_contradicted", "loop.steer_from_reasoning")
                   for name, _ in log.events)
    if expected is None:
        assert any(name == "loop.steer_multiple_actions" for name, _ in log.events)
