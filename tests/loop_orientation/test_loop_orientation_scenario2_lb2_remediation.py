"""A task-named missing file is remediated in three observable steps — armed with its subject, the coder's reply is acknowledged by the inspection it
asked for, and a non-write result earns one non-completion follow-up — and none of it exists when the diagnosis assist is off."""
import json

import pytest

from cria import assistruntime, bodykeys, denial, loop


def call(cid, name, **args):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def result(cid, text, outcome=None):
    m = {"role": "tool", "tool_call_id": cid, "content": text}
    if outcome:
        m[bodykeys.RESULT_OUTCOME] = outcome
    return m


class Log:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append(kind)


def remediation_fields(gs):
    return (gs.completion_remediation_subject, gs.completion_remediation_reason, gs.completion_remediation_nonwrite_ids)


def test_a_remediation_is_armed_acknowledged_by_an_inspection_and_followed_up_once_after_its_result():
    inspect = call("i", "exec_command", cmd="ls")
    log, gs = Log(), loop.GuardState()
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        loop._arm_completion_remediation(gs, "REVIEW.md", "missing file")
        assert remediation_fields(gs) == ("REVIEW.md", "missing file", ())
        loop._record_remediation_delivery(gs, {"choices": [{"message": {"role": "assistant", "tool_calls": inspect["tool_calls"]}}]})
        assert remediation_fields(gs)[2] == ("i",)                                                # the inspection call is remembered, nothing else
        loop._nudge_after_remediation_nonwrite(gs, [inspect, result("i", "a.py")], log)
    assert log.events == ["loop.completion_remediation_nonwrite"] and gs.completion_remediation_nonwrite_seen is True
    assert "inspection alone is not completion" in gs.nudge_reason and gs.completion_remediation_subject == "REVIEW.md"   # open until its own write lands


def test_the_same_calls_do_nothing_when_the_diagnosis_assist_is_off():
    gs, log = loop.GuardState(), Log()
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=0)):
        loop._arm_completion_remediation(gs, "REVIEW.md", "missing file")
        loop._record_remediation_delivery(gs, {"choices": [{"message": {"tool_calls": call("i", "exec_command", cmd="ls")["tool_calls"]}}]})
        loop._nudge_after_remediation_nonwrite(gs, [call("i", "exec_command", cmd="ls"), result("i", "a.py")], log)
        loop._settle_completion_remediation(gs, [], log)
    assert remediation_fields(gs) == ("", "", ()) and log.events == [] and not getattr(gs, "nudge_reason", "")


@pytest.mark.parametrize("messages,landed", [
    ([call("w", "write_file", path="/w/REVIEW.md", content="x"), result("w", "Wrote /w/REVIEW.md", denial.LANDED)], True),
    ([call("w", "write_file", path="/w/REVIEW.md", content="x")], False),                                            # intent is not a landed write
    ([call("w", "write_file", path="/w/OTHER.md", content="x"), result("w", "Wrote /w/OTHER.md", denial.LANDED)], False),
    ([call("w", "write_file", path="/w/REVIEW.md", content="x"), result("w", "refused", denial.REFUSED)], False),
])
def test_only_a_paired_landed_write_to_the_named_file_counts_as_the_remediation(messages, landed):
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        assert loop._observed_successful_write(messages, "REVIEW.md", "/w") is landed
