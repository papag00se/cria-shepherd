"""The whole-task file confirmation cannot judge a statement about an image; its deliverable-type decision can.

A task whose deliverable is a statement about an observed image has no file component, so the file-checking
confirmation must not run on it (it refused every such turn until the completion-check bound). The decision keys
on the store's typed observation provenance, then asks the one deliverable-type question; a task that also asks
for a file, an image with no completed observation, and an unreadable answer all keep the full confirmation.
"""
import json
from types import SimpleNamespace

import pytest

from cria import loop, wsview
from cria.config import Role
from cria.imagestore import ImageStore
from cria.imageprotocol import CoderRoute
from cria.imageworkflow import SourceImageContext, current, has_observation
from test_workflow_judge_view import Log, history, observed_context
from test_workflow_store import TASK

STATEMENT = "Look at ./note.png and tell me what it says, then summarise it in one sentence."
WRITES = "Look at ./note.png, then write what it says into ./out.txt."
SATISFIED = {"satisfied": True, "reason": "The observation reports the note's text and the coder reported it.",
             "proposed_fix": "", "diagnosis_kind": "", "subject": "", "task_quote": "", "evidence_source": "",
             "evidence_quote": ""}


class Rig:
    """A fake provider answering by what is asked; every call it receives is recorded by kind."""

    def __init__(self, applies="NO", checker=None):
        self.applies, self.kinds = applies, []
        self.checker = checker or {"consistent": False, "why": "the image text cannot be verified on disk",
                                   "proposed_fix": "", "diagnosis_kind": "", "subject": "", "task_quote": "",
                                   "evidence_source": "", "evidence_quote": ""}

    def __call__(self, body, rlog):
        text = json.dumps(body["messages"])
        if "creating or changing files" in text:
            kind, content = "applies", self.applies
        elif "VERIFICATION CHECKER" in text:
            kind, content = "checker", json.dumps(self.checker)
        else:
            kind, content = "other", json.dumps(SATISFIED)
        self.kinds.append(kind)
        return json.dumps({"choices": [{"message": {"role": "assistant", "content": content},
                                        "finish_reason": "stop"}]}).encode()


def judge(task, rig, tmp_path, *, observed=True, pending=False):
    messages = history()
    messages[0] = {"role": "user", "content": task}
    view = wsview.View(str(tmp_path), "image-confirm")
    view._ingest_tree("D\t\nF\t72\t1\tnote.png", complete=True)
    view_token = wsview.bind(view)
    context = observed_context(tmp_path, messages) if observed or pending else None
    if pending:
        session = ImageStore(tmp_path / "pending", close_authority=object()).session("judge")
        route = CoderRoute(object(), "m", "sig", True)
        session.select_route(route)
        context = SourceImageContext(SimpleNamespace(), session,
                                     session.prepare(messages, TASK, workspace_sources={(2, 0): "./note.png"}), TASK)
    token = current.set(context)
    log = Log()
    try:
        result = loop.judge_satisfaction(task, "$ view_image {}", rig, Role(name="reasoner", backend="local"), log,
                                         workspace_root=str(tmp_path), messages=messages)
    finally:
        current.reset(token)
        wsview.unbind(view_token)
    return result, [name for name, _ in log.events]


def test_has_observation_is_the_stores_record_not_message_text(tmp_path):
    messages = history()
    token = current.set(observed_context(tmp_path, messages))
    try:
        assert has_observation() is True
    finally:
        current.reset(token)
    assert has_observation() is False
    # Pixels delivered but no completed observation: the same message text, no provenance.
    session = ImageStore(tmp_path / "p", close_authority=object()).session("judge")
    token = current.set(SourceImageContext(SimpleNamespace(), session, session.prepare(
        messages, TASK, workspace_sources={(2, 0): "./note.png"}), TASK))
    try:
        assert has_observation() is False
    finally:
        current.reset(token)


def test_statement_about_an_observed_image_is_not_refused_by_the_file_checker(tmp_path):
    rig = Rig(applies="NO")
    (satisfied, reason, _), events = judge(STATEMENT, rig, tmp_path)
    assert satisfied is True
    assert "checker" not in rig.kinds and rig.kinds.count("applies") == 1
    assert "loop.confirm_skipped_no_artifact" in events and "loop.satisfaction_confirm" not in events


@pytest.mark.parametrize("applies", ["YES", "yes.", "garbled", ""])
def test_a_file_component_or_an_unreadable_answer_keeps_the_full_confirmation(tmp_path, applies):
    rig = Rig(applies=applies)
    (satisfied, reason, _), events = judge(WRITES, rig, tmp_path)
    assert satisfied is False
    assert "checker" in rig.kinds and "loop.satisfaction_confirm" in events


def test_a_claim_about_an_image_with_no_observation_is_confirmed_as_before(tmp_path):
    rig = Rig(applies="NO")
    (satisfied, _, _), events = judge(STATEMENT, rig, tmp_path, observed=False)
    assert satisfied is False
    assert "applies" not in rig.kinds and "checker" in rig.kinds


def test_pixels_without_a_completed_observation_keep_the_confirmation(tmp_path):
    rig = Rig(applies="NO")
    (satisfied, _, _), _ = judge(STATEMENT, rig, tmp_path, observed=False, pending=True)
    assert satisfied is False
    assert "applies" not in rig.kinds and "checker" in rig.kinds


def test_no_reasoner_role_keeps_the_brake():
    assert loop._task_confirm_applies(STATEMENT, Rig(), None, Log()) is True


# ---- the coder's closing reply reaches the judge as a labelled claim, only where an observation can ground it ----

CLAIM = "The note says Meeting moved to Thursday 3pm and Bring laptop. Summary: the meeting is Thursday at 3pm."


def judged_bodies(task, rig, tmp_path, **kw):
    """Run the real judge with a recording provider; return (result, [every judge body as text])."""
    bodies = []

    def chat(body, rlog):
        bodies.append(json.dumps(body["messages"], ensure_ascii=False))
        return rig(body, rlog)

    messages = history()
    messages[0] = {"role": "user", "content": task}
    view = wsview.View(str(tmp_path), "image-claim")
    view._ingest_tree("D\t\nF\t72\t1\tnote.png", complete=True)
    view_token = wsview.bind(view)
    context = observed_context(tmp_path, messages) if kw.pop("observed", True) else None
    token = current.set(context)
    try:
        evidence = loop._satisfaction_evidence(messages[:3], rlog=Log())
        result = loop.judge_satisfaction(task, evidence, chat, Role(name="reasoner", backend="local"), Log(),
                                         workspace_root=str(tmp_path), messages=messages, **kw)
    finally:
        current.reset(token)
        wsview.unbind(view_token)
    return result, bodies


def test_closing_reply_reaches_the_judge_as_a_labelled_claim_beside_the_observation(tmp_path):
    (satisfied, _, _), bodies = judged_bodies(STATEMENT, Rig(), tmp_path, closing_claim=CLAIM)
    first = bodies[0]
    assert "THE CODER'S CLOSING REPLY" in first and "a claim made by the coder, not evidence" in first
    assert "Meeting moved to Thursday 3pm and Bring laptop. Summary" in first
    assert "Historical coder observation" in first       # the evidence it is checked against
    assert first.index("Historical coder observation") < first.index("THE CODER'S CLOSING REPLY")
    assert satisfied is True


def test_closing_reply_without_an_observation_never_reaches_any_judge(tmp_path):
    (satisfied, _, _), bodies = judged_bodies(STATEMENT, Rig(), tmp_path, closing_claim=CLAIM, observed=False)
    assert bodies and not any("THE CODER'S CLOSING REPLY" in b or "Bring laptop. Summary" in b for b in bodies)


def test_closing_reply_does_not_skip_the_file_check_of_an_image_plus_file_task(tmp_path):
    rig = Rig(applies="YES")
    (satisfied, _, _), bodies = judged_bodies(WRITES, rig, tmp_path, closing_claim="Saved it to out.txt.")
    assert satisfied is False and "checker" in rig.kinds
    assert any("Saved it to out.txt." in b for b in bodies[:1])   # a labelled claim, nothing more


def test_blank_closing_reply_adds_nothing(tmp_path):
    _, bodies = judged_bodies(STATEMENT, Rig(), tmp_path, closing_claim="  ")
    assert not any("THE CODER'S CLOSING REPLY" in b for b in bodies)


def _single(reasoner):
    from test_loop import _single_loop
    return _single_loop(lambda b, r: b"{}", reasoner_chat=reasoner, reasoner_role=Role(name="reasoner", backend="local"))


def test_plan_off_claim_site_holds_the_reply_and_the_whole_task_review_consumes_it_once(monkeypatch):
    from test_loop import _synth, _done, _SHELL
    seen = []
    monkeypatch.setattr(loop, "judge_satisfaction", lambda *a, **k: (seen.append(k.get("closing_claim")) or (True, "ok", "")))
    run = _single(lambda b, r: b"{}")
    sess = _synth()
    sess.action_seq = 1
    body = {"messages": [{"role": "user", "content": STATEMENT}], "tools": []}   # no shell: judged immediately
    run._gate_single_done(sess, _done(CLAIM), {"messages": []}, body, "k", Log())
    assert seen == [CLAIM] and sess.closing_claim == ""       # consumed once; a later claim holds its own reply
    run._done_critic_reason(sess, body, Log())
    assert seen == [CLAIM, ""]


def test_a_scheduled_review_never_carries_a_stale_closing_reply(monkeypatch):
    from test_loop import _synth
    from cria.completionreview import ReviewTrigger
    seen = []
    monkeypatch.setattr(loop, "judge_satisfaction", lambda *a, **k: (seen.append(k.get("closing_claim")) or (True, "ok", "")))
    run = _single(lambda b, r: b"{}")
    sess = _synth()
    sess.closing_claim = CLAIM
    body = {"messages": [{"role": "user", "content": STATEMENT}], "tools": []}
    run._review_task(sess, body, Log(), trigger=ReviewTrigger.SCHEDULED)
    assert seen == [""]
