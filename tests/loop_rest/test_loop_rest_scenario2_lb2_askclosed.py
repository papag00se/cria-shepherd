"""The closed-question primitive every judge shares, driven through a fake upstream: the question rides in the user turn with reasoning off
and temperature 0, an unreadable pass is retried once with thinking forced off, a cut-off / leaked / ruminated / failed pass is never an answer,
and a wire that proves the retry identical is never asked twice."""
import json

import pytest

from cria import bodykeys, loop
from cria.config import Role
from cria.upstream import CallerContextRetryNoChange, ContextRefitNoChange, UpstreamError

ROLE = Role(name="reasoner", backend="fixture")


class Log:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


def reply(content="", finish="stop", **message):
    return json.dumps({"choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": content, **message}}]})


class Upstream:
    def __init__(self, *replies):
        self.replies, self.bodies = list(replies), []

    def __call__(self, body, rlog):
        self.bodies.append(body)
        item = self.replies[min(len(self.bodies) - 1, len(self.replies) - 1)]
        if isinstance(item, BaseException):
            raise item
        return item


TRUNC = reply("half an ans", finish="length")
LEAK = reply("<|tool_call>call:x{}<tool_call|>")
RUMINATED = reply("we need to think", finish="rumination")
REFIT = ContextRefitNoChange(UpstreamError("ctx"), b"wire")


@pytest.mark.parametrize("script,kwargs,answer,calls,events", [
    ([reply("YES")], {}, "YES", 1, []),
    ([reply(""), reply("NO")], {}, "NO", 2, []),                                         # thinking-off retry on an empty pass
    ([reply(""), reply("NO")], {"retry_off": False}, "", 1, []),                         # a caller that allows one judgment only
    ([TRUNC, reply("YES")], {}, "YES", 2, ["summarize.truncated"]),                     # half an answer is not an answer
    ([LEAK, reply("YES")], {}, "YES", 2, ["summarize.leaked_tool_call"]),
    ([RUMINATED, reply("YES")], {}, "YES", 2, ["summarize.ruminated"]),
    ([RuntimeError("down"), reply("YES")], {}, "YES", 2, ["summarize.error"]),
    ([RuntimeError("down")], {"retry_off": False}, "", 1, ["summarize.error"]),
    ([reply("  Yes.\n")], {}, "Yes.", 1, []),
])
def test_an_unreadable_pass_is_retried_once_and_never_returned_as_an_answer(script, kwargs, answer, calls, events):
    up, log = Upstream(*script), Log()
    assert loop.ask_closed(up, ROLE, "Is it done?", log, phase="judge", **kwargs) == answer
    assert len(up.bodies) == calls and [k for k in log.kinds() if k.startswith("summarize.")] == events


def test_the_question_is_the_system_turn_and_the_ask_is_the_user_turn_with_nothing_left_to_sampling():
    up = Upstream(reply(""), reply("YES"))
    loop.ask_closed(up, None, "Is it done?", Log(), phase="judge", max_tokens=64, evidence_blocks=["BLOCK-1", "BLOCK-2"])
    body = up.bodies[0]
    assert body["temperature"] == 0.0 and body["max_tokens"] == 64 and body["stream"] is False
    assert "chat_template_kwargs" not in body and up.bodies[1]["chat_template_kwargs"] == {"enable_thinking": False}   # no role: the retry turns thinking off at the template
    assert body["messages"][0] == {"role": "system", "content": "Is it done?"} and body["messages"][-1]["content"] == "Answer the question above."
    carried = json.dumps(body["messages"][1:-1])
    assert "BLOCK-1" in carried and "BLOCK-2" in carried and len(body["messages"]) == 5     # intro + two blocks between
    assert bodykeys.DENSITY_KIND not in body                                      # a judge never teaches the summary density
    summary = Upstream(reply("a briefing"))
    assert loop.summarize(summary, ROLE, "write", "go", Log(), phase="compactor", output_reserve=2048) == "a briefing"
    assert summary.bodies[0][bodykeys.DENSITY_KIND] == "summary" and summary.bodies[0][bodykeys.OUTPUT_RESERVE] == 2048


def test_a_wire_that_proves_the_retry_identical_is_not_asked_again_and_a_first_refit_marks_the_retry():
    up, log = Upstream(REFIT, reply("YES")), Log()
    assert loop.ask_closed(up, ROLE, "q", log, phase="judge") == "YES"
    assert bodykeys.CONTEXT_REFIT_NO_CHANGE not in up.bodies[0] and up.bodies[1][bodykeys.CONTEXT_REFIT_NO_CHANGE] is REFIT
    stuck, log = Upstream(REFIT, CallerContextRetryNoChange(REFIT, b"wire")), Log()
    assert loop.ask_closed(stuck, ROLE, "q", log, phase="judge") == "" and len(stuck.bodies) == 2
    assert log.kinds() == ["summarize.error", "summarize.context_retry_no_change"]
    once, log = Upstream(REFIT), Log()
    assert loop.ask_closed(once, ROLE, "q", log, phase="judge", retry_off=False) == "" and len(once.bodies) == 1


def test_a_composed_seat_carries_evidence_as_blocks_and_never_retries():
    up, log = Upstream(reply(""), reply("late")), Log()
    ask = loop._composed_closed_ask(up, ROLE, log, phase="negative-diagnosis")
    assert ask.composes_evidence is True and ask("Which?", ["E1"]) == "" and len(up.bodies) == 1
    assert "E1" in json.dumps(up.bodies[0]["messages"]) and up.bodies[0]["max_tokens"] == loop.JUDGE_MAX_TOKENS
    assert ask.evidence_blocks("short evidence") == ["short evidence"]
