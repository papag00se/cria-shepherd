"""An image the user ATTACHED to the task reaches the satisfaction judge as its labelled observation.

gemma4_12b / image-only deliverable (loop engaged): the judge's evidence was the action log, which holds tool results and not
the task message the image arrived in, so the judge was told to check the coder's reply against 'the labelled image
observation in the actions above' that was not there and ruled 'no observation of an image' (2 of 3 verdicts)."""
import json

import pytest

from cria import imageworkflow, loop
from cria.config import Role
from test_read_multipart_image import TASK, completion, delivered, rig  # noqa: F401  (rig is the shared fixture)

VERDICT = {"satisfied": True, "reason": "ok", "proposed_fix": "", "diagnosis_kind": "", "subject": "", "task_quote": "",
           "evidence_source": "", "evidence_quote": ""}


class Log:
    def emit(self, *a, **k):
        pass


def judge(prepared, session, evidence="$ read_file {}\n  -> hi", claim=""):
    bodies = []

    def chat(body, rlog):
        bodies.append(json.dumps(body["messages"], ensure_ascii=False))
        return json.dumps({"choices": [{"message": {"role": "assistant", "content": json.dumps(VERDICT)},
                                        "finish_reason": "stop"}]}).encode()

    token = imageworkflow.current.set(imageworkflow.SourceImageContext(None, session, prepared, TASK))
    try:
        loop.judge_satisfaction(TASK, evidence, chat, Role(name="reasoner", backend="local"), Log(), closing_claim=claim)
    finally:
        imageworkflow.current.reset(token)
    return bodies


def test_an_observed_attachment_is_in_the_judges_evidence_before_the_closing_claim(rig):  # noqa: F811
    _, s, route, messages, prepared, ref, body, _ = rig
    attempt = s.begin(ref, TASK, route, body)
    s.complete(attempt, delivered(attempt, route))
    first = judge(prepared, s, claim="There are two buttons, Save and Cancel.")[0]
    assert "Save\\nCancel" in first and "Two adjacent buttons." in first and "data:image" not in first
    assert first.index("Two adjacent buttons.") < first.index("THE CODER'S CLOSING REPLY")
    assert "THE IMAGE THE USER ATTACHED" in first


def test_nothing_is_added_without_a_completed_observation_or_for_a_tool_result_packet(rig):  # noqa: F811
    _, s, route, messages, prepared, ref, body, _ = rig
    assert "THE IMAGE THE USER ATTACHED" not in judge(prepared, s, claim="x")[0]          # pixels only: no observation
    attempt = s.begin(ref, TASK, route, body)
    s.complete(attempt, delivered(attempt, route))
    tool_prepared = s.prepare([{"role": "user", "content": TASK}, {"role": "tool", "tool_call_id": "t", "content": messages[0]["content"][1:]}],
                              TASK, workspace_sources={(1, 0): "./a.png"})
    tool_ref = tool_prepared.bindings[0].ref
    tool_attempt = s.begin(tool_ref, TASK, route, body)
    s.complete(tool_attempt, delivered(tool_attempt, route))
    assert s.observed(tool_prepared) and s.attachment_observations(tool_prepared) == []   # observed, but already in the action log
