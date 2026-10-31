"""The one reasoner text primitive (`summarize`) never adopts a reply that is not an answer, and retries once with reasoning off.

Every shared summariser (briefing, steer author, judge helpers) consumes this text, so a half answer, a plan disguised as prose, a
stream cria itself killed or a transport error must come back as "" (and be traced), and only the forced-off retry may supply the text.
"""
import json

import pytest

from cria import bodykeys, loop
from cria.config import Role
from cria.upstream import CallerContextRetryNoChange, ContextRefitNoChange, UpstreamError
from loop_rest_helpers import Rlog, loop_rest_local_view  # noqa: F401

ROLE = Role(name="reasoner", backend="local", reasoning="on")
CALL = [{"id": "c", "type": "function", "function": {"name": "shell", "arguments": "{}"}}]


def reply(content, finish="stop", **extra):
    return {"choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": content, **extra}}]}


REFIT = ContextRefitNoChange(UpstreamError("context exceeded", None), b"the-final-wire")
def served(item):
    if isinstance(item, BaseException):
        raise item
    return json.dumps(item).encode()


ROWS = [
    ("tool-call answer is a plan, not a summary", reply("Plan: 1. start", tool_calls=CALL), "summarize.tool_call_answer"),
    ("cut off mid-answer", reply("half an ans", finish="length"), "summarize.truncated"),
    ("a stream cria killed", {**reply("corpse of the reasoning"), bodykeys.RUMINATION: {"why": "loop"}}, "summarize.ruminated"),
    ("transport error", RuntimeError("upstream down"), "summarize.error"),
    ("identical refit after a context error", REFIT, "summarize.error"),
]


@pytest.mark.parametrize("name,first,event", ROWS, ids=[r[0] for r in ROWS])
def test_a_bad_first_pass_is_traced_and_only_the_reasoning_off_retry_supplies_the_text(name, first, event):
    bodies, script = [], [first, reply("the whole answer")]

    def chat(body, rlog):
        bodies.append(json.loads(json.dumps(body, default=str)))
        return served(script[len(bodies) - 1])
    log = Rlog()
    assert loop.summarize(chat, ROLE, "sys", "user", log, phase="judge") == "the whole answer"
    assert len(bodies) == 2 and event in log.kinds()
    assert bodies[0]["chat_template_kwargs"]["enable_thinking"] is True and bodies[1]["chat_template_kwargs"]["enable_thinking"] is False
    assert (bodykeys.CONTEXT_REFIT_NO_CHANGE in bodies[1]) is (first is REFIT)         # the retry is told the first wire was rejected
    single = Rlog()
    assert loop.summarize(lambda b, r: served(first), ROLE, "sys", "user", single, retry_off=False) == ""   # no retry: nothing is invented


def test_a_retry_the_wire_proves_identical_is_not_sent_and_says_so():
    """The wire owner, not an error string, decides this: the second attempt raises CallerContextRetryNoChange and the answer is ''."""
    calls = []

    def chat(body, rlog):
        calls.append(body)
        raise REFIT if len(calls) == 1 else CallerContextRetryNoChange(REFIT, b"the-final-wire")
    log = Rlog()
    assert loop.summarize(chat, ROLE, "sys", "user", log) == "" and len(calls) == 2
    assert [f["bytes"] for k, f in log.events if k == "summarize.context_retry_no_change"] == [len(b"the-final-wire")]
