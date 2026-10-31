"""Public completion protocol regressions; scripted transport, no inference."""
import copy
import json
from types import SimpleNamespace

import pytest

from cria import assistruntime, completionconfirmation as confirmation, loop, verifytools
from cria.config import Role


class Log:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, name, **fields):
        self.events.append((name, fields))


def completion(text, *, finish="stop", calls=None, rounds=0):
    message = {"role": "assistant", "content": text}
    if calls:
        message["tool_calls"] = calls
    return {"choices": [{"message": message, "finish_reason": finish}], loop.ROUNDS_KEY: rounds}


def scripted(replies):
    replies = iter(replies)
    bodies = []

    def chat(body, log):
        bodies.append(copy.deepcopy(body))
        return json.dumps(next(replies)).encode()

    return chat, bodies


def satisfy(replies):
    chat, bodies = scripted(replies)
    role = Role(name="reasoner", backend="local", reasoning="on")
    # Isolate the public whole-task verdict protocol, not optional approval policies.
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=3)):
        result = loop.judge_satisfaction("Implement the requested feature", "actual action evidence",
                                         chat, role, Log())
    return result, bodies


@pytest.mark.parametrize("value", ["false", "true", "", 0, 1, None, [], [False], {}, {"value": False}])
def test_nonboolean_public_flag_is_unreadable_not_a_verdict(value):
    result, bodies = satisfy([
        completion(json.dumps({"satisfied": value, "reason": "public malformed flag"})),
        completion('{"satisfied":true,"reason":"retry cannot approve"}'),
    ])
    assert result[0] is False
    assert len(bodies) == 2  # malformed flag takes the existing unreadable careful-pass path
    assert bodies[1]["chat_template_kwargs"]["enable_thinking"] is False


@pytest.mark.parametrize("value", [True, False])
def test_literal_boolean_public_flag_keeps_single_careful_verdict(value):
    result, bodies = satisfy([completion(json.dumps({"satisfied": value, "reason": "public ruling"}))])
    assert result[0] is value
    assert len(bodies) == 1


@pytest.mark.parametrize("flag", ["satisfied", "done"])
def test_shared_normalizer_does_not_recover_over_an_explicit_invalid_flag(flag):
    typed = {"diagnosis_kind": "missing_file", "subject": "result.txt", "task_quote": "result.txt",
             "evidence_source": "workspace_absence", "evidence_quote": ""}
    log = Log()
    assert loop._fill_missing_verdict_flag({**typed, flag: "false"}, flag, log, "test") is None
    assert not log.events
    assert loop._fill_missing_verdict_flag(typed, flag, log, "test")[flag] is False
    assert loop._fill_missing_verdict_flag({"reason": "complete", "proposed_fix": ""}, flag, log, "test") is None


def confirm(replies):
    """Use the actual confirmation consumer and production public-text readers."""
    replies = iter(replies)
    inspected = []

    def inspect(request):
        inspected.append(request)
        comp = next(replies)
        return confirmation.InspectionReply(comp, loop.inspection_rounds(comp), ())

    role = Role(name="reasoner", backend="local", reasoning="on")
    services = confirmation.Services(
        confirmation.Facts(lambda root: True, lambda root: ["implementation.py", "optional.txt"]),
        inspect,
        confirmation.Readers(loop._completion_text, role.clean_content, loop._consistent_word,
                             loop.verdict_from_unclosed),
        lambda request: "")
    source = confirmation.Input("Implement the requested feature", "the work is complete", "/workspace",
                                Log(), "satisfaction-confirm")
    return confirmation.confirm(source, services), inspected


@pytest.mark.parametrize("text", ["CONSISTENTLY", "CONSISTENT_UNKNOWN", "CONSISTENT123",
                                   "CONSISTENT enough", "INCONSISTENTLY", "INCONSISTENT_UNKNOWN"])
def test_confirmation_requires_declared_first_line_token(text):
    result, inspected = confirm([completion(text + "\ninspection explanation", rounds=1)])
    assert result.status is confirmation.Status.UNVERIFIED
    assert result.attempts[0].verdict is None
    assert len(inspected) == 1


@pytest.mark.parametrize("text,approved", [
    ("CONSISTENT\nlooked at implementation", True), ("**CONSISTENT**", True),
    (" # `consistent` ", True), ('"CONSISTENT"', True),
    ("INCONSISTENT\nrequired implementation absent", False), ("**INCONSISTENT**", False),
    ('{"consistent":true,"why":"inspected implementation"}', True),
    ('{"consistent":false,"why":"required implementation absent"}', False),
])
def test_confirmation_preserves_formatting_and_literal_json(text, approved):
    result, inspected = confirm([completion(text, rounds=1)])
    assert result.confirmed is approved
    assert result.attempts[0].verdict is approved
    assert len(inspected) == 1


def test_unreadable_careful_and_positive_retry_cannot_approve():
    result, bodies = satisfy([completion('{"reason":"no flag"}'), completion('{"satisfied":true}')])
    assert result[0] is False and len(bodies) == 2


@pytest.mark.parametrize("text,finish,calls", [
    ('{"consistent":true', "stop", None),
    ("CONSISTENT", "length", None),
    ('{"consistent":true}', "stop", [{"function": {"name": "read_file", "arguments": "{}"}}]),
    ('{"consistent":"false"}', "stop", None),
])
def test_confirmation_integrity_barriers_remain(text, finish, calls):
    result, _ = confirm([completion(text, finish=finish, calls=calls, rounds=1)])
    assert result.status is confirmation.Status.UNVERIFIED


def test_latest_confirmation_attempt_cannot_borrow_inspection():
    result, inspected = confirm([
        completion('{"consistent":false,"why":"the work is complete"}', rounds=2),
        completion("CONSISTENT", rounds=0),
    ])
    assert result.status is confirmation.Status.UNVERIFIED and len(inspected) == 2
    assert [a.rounds for a in result.attempts] == [2, 0]


@pytest.mark.parametrize("text", ["CONSISTENT\ninspected implementation", '{"consistent":true}'])
def test_actual_inspection_round_cap_keeps_real_positive_and_optional_unread_file(monkeypatch, text):
    monkeypatch.setattr(verifytools, "VERIFY_MAX_ROUNDS", 1)
    monkeypatch.setattr(loop.wsview, "current", lambda root: SimpleNamespace(surveyed=True))
    executed = []
    monkeypatch.setattr(verifytools, "execute", lambda name, args, root: executed.append((name, args, root)) or "actual source")
    read = {"id": "read-implementation", "type": "function", "function": {
        "name": "read_file", "arguments": '{"path":"implementation.py"}'}}
    chat, bodies = scripted([completion("", calls=[read]), completion(text)])
    log = Log()
    role = Role(name="reasoner", backend="local", reasoning="on")
    production = loop._confirmation_services(chat, role, log, None)
    services = confirmation.Services(
        confirmation.Facts(lambda root: True, lambda root: ["implementation.py", "optional.txt"]),
        production.inspect, production.readers, lambda request: "")
    result = confirmation.confirm(confirmation.Input("Implement the requested feature", "complete", "/workspace",
                                                     log, "satisfaction-confirm"), services)
    assert result.confirmed and result.attempts[0].rounds == 1
    assert len(bodies) == 2 and not bodies[-1].get("tools")
    assert executed == [("read_file", {"path": "implementation.py"}, "/workspace")]
    assert verifytools.ANSWER_NOW_CONSISTENT in bodies[-1]["messages"][-1]["content"]
