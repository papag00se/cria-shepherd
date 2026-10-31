"""Literal fake-service contract for the existing optional act-first policy."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cria import completionredrive as policy

STEP = "you used no tools and changed nothing this step — do the step's work with tool calls first, then report"
TASK = "you used no tools and changed nothing — do the actual work with tool calls first, then report when it is genuinely done"


class Log:
    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))


def test_step_exact_effect_and_once_per_step():
    state = SimpleNamespace(leg0_nudged=False, verify_fails=3, step_tool_calls=0, action_seq=12)
    log = Log()
    request = policy.Input(policy.Authority.STEP, state.step_tool_calls, state, log, step=7)
    result = policy.DEFINITION.execute(request)
    assert result == policy.Result(STEP, None)
    assert vars(state) == dict(leg0_nudged=True, verify_fails=4, step_tool_calls=0, action_seq=12)
    assert log.events == [("loop.step_incomplete", dict(step=7, reason="no tools used", attempt=4))]
    assert policy.DEFINITION.execute(request) is None
    assert len(log.events) == 1
    # The real driver resets the original flag at step transition, not a mirror.
    state.leg0_nudged = False
    assert policy.DEFINITION.execute(request) == policy.Result(STEP, None)
    assert state.verify_fails == 5


def test_task_exact_wrapped_prompt_and_task_cadence():
    # TASK does not read or require the STEP-only verification counter.
    state = SimpleNamespace(leg0_nudged=False, action_seq=0)
    log = Log()
    request = policy.Input(policy.Authority.TASK, state.action_seq, state, log)
    assert policy.DEFINITION.execute(request) == policy.Result(
        TASK, {"role": "user", "content": "⟦ctx:steer⟧ " + TASK})
    assert vars(state) == dict(leg0_nudged=True, action_seq=0)
    assert policy.DEFINITION.execute(request) is None
    assert log.events == [("loop.step_incomplete", dict(plan_off=True, reason="no tools used"))]


@pytest.mark.parametrize("authority", list(policy.Authority))
@pytest.mark.parametrize("activity,spent", [(1, False), (20, False), (0, True), (1, True)])
def test_ineligible_is_silent_without_prompt_services(authority, activity, spent):
    state = SimpleNamespace(leg0_nudged=spent, verify_fails=9)
    log = Log()
    with patch.object(policy.prompts, "load", side_effect=AssertionError("no optional prompt")), patch.object(
        policy.prompts, "render", side_effect=AssertionError("no optional framing")
    ):
        assert policy.DEFINITION.execute(policy.Input(authority, activity, state, log)) is None
    assert vars(state) == dict(leg0_nudged=spent, verify_fails=9)
    assert log.events == []


@pytest.mark.parametrize("authority", list(policy.Authority))
def test_spent_before_prompt_failure_no_reask(authority):
    state = SimpleNamespace(leg0_nudged=False, verify_fails=0)
    log = Log()
    request = policy.Input(authority, 0, state, log, step=2)
    failure = RuntimeError("prompt unavailable")
    with patch.object(policy.prompts, "load", side_effect=failure):
        with pytest.raises(RuntimeError) as caught:
            policy.DEFINITION.execute(request)
        assert caught.value is failure
        assert policy.DEFINITION.execute(request) is None
    assert state.leg0_nudged is True
    assert state.verify_fails == (1 if authority is policy.Authority.STEP else 0)
    assert len(log.events) == 1


@pytest.mark.parametrize("authority", list(policy.Authority))
def test_log_failure_spends_once_without_loading_prompt(authority):
    state = SimpleNamespace(leg0_nudged=False, verify_fails=6)
    log = Log()
    request = policy.Input(authority, 0, state, log, step=4)
    failure = RuntimeError("event sink failed")
    with patch.object(log, "emit", side_effect=failure), patch.object(policy.prompts, "load") as load:
        with pytest.raises(RuntimeError) as caught:
            policy.DEFINITION.execute(request)
        assert caught.value is failure
        assert policy.DEFINITION.execute(request) is None
        load.assert_not_called()
    assert state.leg0_nudged is True
    assert state.verify_fails == (7 if authority is policy.Authority.STEP else 6)


def test_step_does_not_wrap_before_real_renudge():
    state = SimpleNamespace(leg0_nudged=False, verify_fails=0)
    log = Log()
    with patch.object(policy.prompts, "render", side_effect=AssertionError("STEP wraps in real driver")):
        assert policy.DEFINITION.execute(policy.Input(policy.Authority.STEP, 0, state, log)) == policy.Result(STEP, None)


def test_sessions_are_independent_and_default_is_runtime():
    a = SimpleNamespace(leg0_nudged=False)
    b = SimpleNamespace(leg0_nudged=False)
    log = Log()
    assert policy.DEFINITION.execute(policy.Input(policy.Authority.TASK, 0, a, log)) is not None
    assert b.leg0_nudged is False
    assert policy.DEFINITION.execute(policy.Input(policy.Authority.TASK, 0, b, log)) is not None
    assert policy.DEFINITION.policy.scope == "runtime"
    assert policy.DEFINITION.policy.default_level == 4
    assert policy.DEFINITION.policy.migrated is False
