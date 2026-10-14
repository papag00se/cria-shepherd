"""F37: the two critics obey the same answer-channel and fail-closed contract."""
import json
from types import SimpleNamespace

import pytest

from cria import loop, prompts
from cria.config import Role


class Log:
    phase = ""
    def __init__(self):
        self.events = []
    def emit(self, event, **fields):
        self.events.append((event, fields))


def invoke(flag, replies, *, reasoning_off=False):
    bodies = []
    def chat(body, rlog):
        bodies.append(body)
        reply = replies[min(len(bodies)-1, len(replies)-1)]
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(reply).encode()
    role = Role(name="reasoner", backend="local", reasoning="on")
    log = Log()
    if flag == "satisfied":
        verdict = loop._satisfaction_verdict("judge", "task", chat, role, log,
                                            reasoning_off=reasoning_off)
    else:
        critic = loop.Loop.__new__(loop.Loop)
        critic._ctx = SimpleNamespace(reasoner_chat=chat, reasoner_role=role)
        verdict, _ = critic._verdict("judge", "task", log, reasoning_off=reasoning_off)
    return verdict, bodies, log, role


def completion(content, *, finish="stop", reasoning=None):
    message = {"role":"assistant", "content":content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return {"choices":[{"finish_reason":finish, "message":message}]}


@pytest.mark.parametrize("flag", ["satisfied", "done"])
@pytest.mark.parametrize("answer", [True, False])
def test_off_retry_reads_actual_answer_not_unopened_reasoning_prefix(flag, answer):
    # Backend emits a closing delimiter without an opening delimiter. The first JSON
    # is deliberation, not an answer; a generic balanced-object parser cannot know that.
    prefix = json.dumps({flag: not answer, "reason":"discarded deliberation"})
    actual = {flag:answer, "reason":"actual ruling"}
    verdict, bodies, _, original_role = invoke(
        flag, [completion(prefix + "</think>" + json.dumps(actual))], reasoning_off=True)
    assert verdict == actual
    assert original_role.reasoning == "on"  # never mutate shared role configuration
    assert all(not b.get("tools") for b in bodies)
    assert prompts.load("judge_toolless_note") in bodies[0]["messages"][0]["content"]


@pytest.mark.parametrize("flag", ["satisfied", "done"])
@pytest.mark.parametrize("reason", ["literal </think> text", "literal <think>data</think> text", "literal ```json data``` text"])
@pytest.mark.parametrize("fenced", [False, True])
def test_protocol_strings_inside_public_json_are_data_not_framing(flag, reason, fenced):
    answer = {flag:True, "reason":reason}
    text = json.dumps(answer)
    if fenced:
        text = "```json\n" + text + "\n```"
    verdict, _, _, _ = invoke(flag, [completion(text)], reasoning_off=True)
    assert verdict == answer


@pytest.mark.parametrize("flag", ["satisfied", "done"])
@pytest.mark.parametrize("closing", ["</think>", "</thinking>", "</THINK >"])
def test_private_json_quoting_delimiters_still_loses_to_real_closing_marker(flag, closing):
    private = json.dumps({flag:True, "reason":"private </think> and <think>quoted</think>"})
    answer = {flag:False, "reason":"actual public negative"}
    verdict, _, _, _ = invoke(flag, [completion(private + closing + json.dumps(answer))], reasoning_off=True)
    assert verdict == answer


@pytest.mark.parametrize("flag", ["satisfied", "done"])
def test_readable_verdict_is_not_overridden_by_private_doubts(flag):
    answer = {flag:True,"reason":"explicit ruling"}
    verdict, bodies, _, _ = invoke(flag, [completion(json.dumps(answer), reasoning="still unsure")])
    assert verdict == answer and len(bodies) == 1


@pytest.mark.parametrize("flag", ["satisfied", "done"])
def test_truncated_closed_object_does_not_approve_or_trigger_salvage(flag):
    verdict, bodies, log, _ = invoke(flag, [completion(json.dumps({flag:True}), finish="length")])
    assert verdict is None and len(bodies) == 1
    assert any(event in {"loop.satisfaction_truncated", "loop.verify_truncated"}
               for event, _ in log.events)


@pytest.mark.parametrize("flag", ["satisfied", "done"])
def test_missing_closer_recovers_only_negative_ruling(flag):
    text = json.dumps({flag:False,"reason":"required artifact absent"})[:-1]
    verdict, _, _, _ = invoke(flag, [completion(text)])
    assert verdict[flag] is False and verdict["reason"] == "required artifact absent"
    positive = json.dumps({flag:True,"reason":"claimed success"})[:-1]
    verdict, _, _, _ = invoke(flag, [completion(positive), completion("no recoverable ruling")])
    assert verdict is None


@pytest.mark.parametrize("flag", ["satisfied", "done"])
def test_transport_exception_is_unknown_not_approval(flag):
    verdict, _, log, _ = invoke(flag, [RuntimeError("upstream unavailable")])
    assert verdict is None
    assert any(fields.get("error") == "upstream unavailable" for _, fields in log.events)
