"""Completion judges fail CLOSED: an unreadable, truncated or malformed answer is never a 'done'."""

import copy
import json
from types import SimpleNamespace

import pytest

from cria import assistruntime, completionconfirmation as confirmation, loop, verifytools
from cria.config import Role
from loop_rest_helpers import Rlog, loop_rest_local_view  # noqa: F401


def completion(content, *, finish="stop", reasoning=None, calls=None, rounds=0):
    message = {"role": "assistant", "content": content, **({"reasoning_content": reasoning} if reasoning is not None else {}),
               **({"tool_calls": calls} if calls else {})}
    return {"choices": [{"finish_reason": finish, "message": message}], loop.ROUNDS_KEY: rounds}


def scripted(replies):
    it, bodies = iter(replies), []

    def chat(body, log):
        bodies.append(copy.deepcopy(body))
        reply = next(it)
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(reply).encode()
    return chat, bodies


ROLE = Role(name="reasoner", backend="local", reasoning="on")


def invoke(flag, replies, reasoning_off=False):
    """Run the satisfaction critic ('satisfied') or the step critic ('done') on scripted replies."""
    chat, bodies, log = *scripted(replies), Rlog()
    if flag == "satisfied":
        return loop._satisfaction_verdict("judge", "task", chat, ROLE, log, reasoning_off=reasoning_off), bodies, log
    critic = loop.Loop.__new__(loop.Loop)
    critic._ctx = SimpleNamespace(reasoner_chat=chat, reasoner_role=ROLE)
    return critic._verdict("judge", "task", log, reasoning_off=reasoning_off)[0], bodies, log


NO_RULING = completion("no recoverable ruling")


@pytest.mark.parametrize("flag", ["satisfied", "done"])
def test_both_critics_read_the_public_answer_not_the_deliberation(flag):
    """An unopened-reasoning prefix is deliberation; protocol strings inside the reason are data; private doubts never override."""
    actual = {flag: False, "reason": "literal </think> text is missing"}
    prefix = json.dumps({flag: True, "reason": "discarded deliberation"})
    verdict, bodies, _ = invoke(flag, [completion(prefix + "</think>" + json.dumps(actual))], reasoning_off=True)
    assert verdict == actual and ROLE.reasoning == "on" and not any(b.get("tools") for b in bodies)
    fenced = {flag: True, "reason": "literal ```json data``` text"}
    assert invoke(flag, [completion("```json\n" + json.dumps(fenced) + "\n```")], reasoning_off=True)[0] == fenced
    ruling = {flag: True, "reason": "explicit ruling"}
    verdict, bodies, _ = invoke(flag, [completion(json.dumps(ruling), reasoning="still unsure")])
    assert verdict == ruling and len(bodies) == 1


@pytest.mark.parametrize("flag", ["satisfied", "done"])
def test_a_cut_off_unclosed_or_failed_answer_never_approves(flag):
    """A truncated approval is no approval; only a NEGATIVE ruling is recoverable from an unclosed tail; transport errors are unknown."""
    verdict, bodies, log = invoke(flag, [completion(json.dumps({flag: True}), finish="length")])
    assert verdict is None and len(bodies) == 1
    assert any(k in {"loop.satisfaction_truncated", "loop.verify_truncated"} for k, _ in log.events)
    assert invoke(flag, [completion(json.dumps({flag: False, "reason": "artifact absent"})[:-1])])[0][flag] is False
    for unclosed in ({flag: True, "reason": "claimed success"}, {flag: True, "example": {flag: False, "reason": "illustration"}}):
        assert invoke(flag, [completion(json.dumps(unclosed)[:-1]), NO_RULING])[0] is None
    verdict, _, log = invoke(flag, [RuntimeError("upstream unavailable")])
    assert verdict is None and any(f.get("error") == "upstream unavailable" for _, f in log.events)


def satisfy(replies):
    chat, bodies = scripted(replies)
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=3)):
        return loop.judge_satisfaction("Implement the feature", "action evidence", chat, ROLE, Rlog()), bodies


def test_a_non_boolean_flag_takes_the_careful_pass_and_a_positive_retry_cannot_approve():
    """A public flag that is not literally true/false is unreadable: re-asked once with thinking off, still not approved."""
    for value in ("false", 1, None, []):
        result, bodies = satisfy([completion(json.dumps({"satisfied": value, "reason": "malformed"})),
                                  completion('{"satisfied":true,"reason":"retry cannot approve"}')])
        assert result[0] is False and len(bodies) == 2 and bodies[1]["chat_template_kwargs"]["enable_thinking"] is False, value


def confirm(replies):
    it = iter(replies)

    def inspect(request):
        comp = next(it)
        return confirmation.InspectionReply(comp, loop.inspection_rounds(comp), ())
    readers = confirmation.Readers(loop._completion_text, ROLE.clean_content, loop._consistent_word, loop.verdict_from_unclosed)
    services = confirmation.Services(confirmation.Facts(lambda root: True, lambda root: ["implementation.py"]), inspect, readers,
                                     lambda request: "")
    return confirmation.confirm(confirmation.Input("Implement the feature", "the work is complete", "/workspace", Rlog(),
                                                   "satisfaction-confirm"), services)


def test_the_confirmer_needs_a_declared_first_line_token_from_a_finished_reply():
    """Only the declared token/JSON boolean, uncut, counts; anything near it leaves the work UNVERIFIED."""
    for text, finish, approved in [("CONSISTENT\nlooked at implementation", "stop", True), ("**INCONSISTENT**", "stop", False),
                                   ('{"consistent":false,"why":"implementation absent"}', "stop", False)]:
        assert confirm([completion(text, finish=finish, rounds=1)]).confirmed is approved, text
    for text, finish in [("INCONSISTENTLY", "stop"), ("CONSISTENT enough", "stop"), ("CONSISTENT", "length"),
                         ('{"consistent":"false"}', "stop")]:
        result = confirm([completion(text, finish=finish, rounds=1)])
        assert result.status is confirmation.Status.UNVERIFIED and result.attempts[0].verdict is None, text


def test_the_round_cap_asks_the_judges_own_question_and_says_why_looking_stopped(tmp_path):
    """maple-preview 1786228135: the cap sent the generic {"done"} closer to a judge that answers under another key."""
    n = verifytools.VERIFY_MAX_ROUNDS
    ls = completion("", calls=[{"id": "c", "type": "function",
                                "function": {"name": "list_dir", "arguments": '{"path": "."}'}}])
    chat, bodies = scripted([ls] * n + [completion("done inspecting")])
    loop._judge_completion(chat, None, "sys", "user", Rlog(), phase="t", workspace_root=str(tmp_path),
                           verdict_key="done", answer_now_simple="SIMPLE_CLOSER", answer_now="GENERIC_CLOSER")
    assert len(bodies) == n + 1
    cap = bodies[n]["messages"][-1]["content"]
    assert cap.endswith("SIMPLE_CLOSER") and str(n) in cap
    for key in ("done", "satisfied", "consistent"):  # each judge is asked for the key it declares
        assert f'"{key}"' in verifytools.answer_now(key)
    assert '"done"' not in verifytools.answer_now("satisfied")


def test_a_trailing_sentinel_is_a_decision_not_a_directive():
    """maple-preview 1786228135: praise/reasoning before ON_TRACK was delivered as a steer; a leading hedge still ships."""
    d = "You are stuck. Read resolve_handle.py, then run pytest -q."
    for text, steer in [("The coder has completed the task; tests pass.\n\nON_TRACK", None), ("You're making progress.\nON_TRACK", None),
                        ("ON_TRACK. You keep re-fetching; write it now.", "You keep re-fetching; write it now."),
                        ("NOT_STUCK", None), (d, d)]:
        assert loop._steer_or_none(text) == steer, text
