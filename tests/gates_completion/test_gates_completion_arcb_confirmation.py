"""The independent look at the workspace that backs a completion claim: what it may confirm, when it asks again, and the
integrity of the reply it reads (a cut, unclosed or unanswered reply never confirms)."""
import copy
from dataclasses import replace

import pytest

from cria import completionconfirmation as cc, loop, prompts, verifytools
from cria.config import Role
from gates_completion_helpers import Log, gates_completion_view  # noqa: F401

UNVERIFIED = prompts.load("unverified_step")
S = cc.Status

def completion(text, rounds=0, finish="stop", calls=None):
    message = {"role": "assistant", "content": text, **({"tool_calls": calls} if calls else {})}
    return {"choices": [{"message": message, "finish_reason": finish}], loop.ROUNDS_KEY: rounds}

def source(**kw):
    log = Log()
    log.phase = ""
    defaults = dict(claim="Write the implementation", reason="the work is complete", workspace_root="/workspace",
                    phase="satisfaction-confirm", log=log, measured_facts="CHECKER: literal 雪\nexit=0", original_task="original full task")
    return cc.Input(**(defaults | kw))

def services(replies, *, surveyed=True, top=("a.py",), diagnosis=lambda request: ""):
    replies, sent = iter(copy.deepcopy(replies)), []
    role = Role(name="reasoner", backend="local", reasoning="on")

    def inspect(request):
        sent.append(request)
        comp = next(replies)
        pending = tuple(c.get("id", "") for ch in comp.get("choices", []) for c in (ch.get("message") or {}).get("tool_calls") or [])
        return cc.InspectionReply(comp, loop.inspection_rounds(comp), pending)
    facts = cc.Facts(lambda root: surveyed, lambda root: list(top) if top is not None else None)
    return cc.Services(facts, inspect, cc.Readers(loop._completion_text, role.clean_content, loop._consistent_word, loop.verdict_from_unclosed),
                       diagnosis), sent

def event(name, **fields):
    return name, {"assist_id": "approval-inspection-confirmation", "family_id": "F34", "phase": "satisfaction-confirm", **fields}

UNPARSED = event("loop.confirm_unparsed", level="warn")
NO_LOOK = event("loop.confirm_without_looking", level="warn")
RESTATE = event("loop.confirm_restated_claim", level="warn", head="the work is complete")
SAME = completion('{"consistent":false,"why":"the work is complete"}')

@pytest.mark.parametrize("replies,status,reason,attempts,events", [
    ([completion('{"consistent":true,"why":"inspected"}', 1)], S.CONFIRMED, "inspected", [(1, True, "inspected")], []),
    ([completion("CONSISTENT\nlooked", 2)], S.CONFIRMED, "looked", [(2, True, "looked")], []),
    ([completion("INCONSISTENT\nunsupported prose")], S.REJECTED, "", [(0, False, "unsupported prose")], []),
    ([completion('{"consistent":false,"why":"a specific contradiction"}')], S.REJECTED, "", [(0, False, "a specific contradiction")], []),
    ([completion("unreadable")], S.UNVERIFIED, UNVERIFIED, [(0, None, "")], [UNPARSED]),
    ([completion('{"consistent":"true"}')], S.UNVERIFIED, UNVERIFIED, [(0, None, "")], [UNPARSED]),
    ([completion('{"consistent":false,"why":"cut quote"')], S.REJECTED, "", [(0, False, "cut quote")],
     [("loop.verdict_from_unclosed", {"level": "info", "phase": "satisfaction-confirm", "flag": "consistent", "reason": "cut quote"})]),
    ([completion('{"consistent":true,"why":"cut quote"')], S.UNVERIFIED, UNVERIFIED, [(0, None, "")], [UNPARSED]),    # only a NEGATIVE survives a cut
    ([completion('{"consistent":false,"why":"cut quote"', finish="length")], S.UNVERIFIED, UNVERIFIED, [(0, None, "")], [UNPARSED]),
    ([completion("CONSISTENT"), completion("CONSISTENT", 1)], S.CONFIRMED, "", [(0, True, ""), (1, True, "")], [NO_LOOK]),
    ([completion("CONSISTENT"), completion("CONSISTENT")], S.UNVERIFIED, UNVERIFIED, [(0, True, ""), (0, True, "")],
     [NO_LOOK, event("loop.confirm_without_looking_twice", level="warn")]),
    ([SAME, completion("CONSISTENT", 1)], S.CONFIRMED, "", [(0, False, "the work is complete"), (1, True, "")], [RESTATE]),
    ([SAME, SAME], S.UNVERIFIED, UNVERIFIED, [(0, False, "the work is complete")] * 2, [RESTATE, event("loop.confirm_restated_twice", level="warn")]),
    ([completion("CONSISTENT"), SAME, completion("unreadable")], S.UNVERIFIED, UNVERIFIED,
     [(0, True, ""), (0, False, "the work is complete"), (0, None, "")], [NO_LOOK, RESTATE, UNPARSED]),
    ([completion('{"consistent":false,"why":"the work is complete"}', 2), completion("CONSISTENT", 0)], S.UNVERIFIED, UNVERIFIED,
     [(2, False, "the work is complete"), (0, True, "")], [RESTATE, NO_LOOK]),        # a re-ask never borrows the previous answer's look
])
def test_the_confirmer_confirms_only_after_looking_and_a_restated_or_unlooked_answer_is_asked_again_once(replies, status, reason, attempts, events):
    """A bare CONSISTENT with no inspection, or a rejection that merely restates the claim, is not an answer: one escalated re-ask,
    then UNVERIFIED. Unreadable or cut replies never confirm; the verdict is read from the LATEST attempt's own rounds."""
    request = source()
    svc, sent = services(replies)
    result = cc.confirm(request, svc)
    assert result.status is status and (result.confirmed, result.observed, result.reason) == (status is S.CONFIRMED, True, reason)
    assert result.authority is cc.Authority.TASK and tuple(result) == (status is S.CONFIRMED, reason)
    assert result.attempts == tuple(cc.Attempt(i, rounds, verdict, why) for i, (rounds, verdict, why) in enumerate(attempts, 1))
    assert len(sent) == len(attempts) and request.log.events == events
    labels = prompts.load_map("verify_confirm")
    for number, ask in enumerate(sent):
        assert (labels["restate"] in ask.user) is (number > 0) and "CHECKER: literal 雪" in ask.user      # measured bytes ride every ask
        assert request.claim in ask.user and ask.workspace_root == "/workspace" and ask.force_think_off and ask.answer_now_simple == verifytools.ANSWER_NOW_CONSISTENT

@pytest.mark.parametrize("cut,pending", [(True, False), (False, True), (False, "missing-id")], ids=["cut", "unanswered-call", "call-without-id"])
def test_a_balanced_positive_in_a_cut_or_unanswered_reply_never_confirms(cut, pending):
    """Balanced public bytes once approved a reply that was cut off or still holding an unanswered tool call."""
    calls = ([{**({"id": "still-reading"} if pending is True else {}), "type": "function",
               "function": {"name": "read_file", "arguments": '{"path":"a.py"}'}}] if pending else None)
    reply = completion('{"consistent":true,"why":"balanced bytes"}', 1, finish="length" if cut else "stop", calls=calls)
    request = source()
    svc, sent = services([reply])
    result = cc.confirm(request, svc)
    ids = ("still-reading",) if pending is True else ("",) if pending else ()
    assert not result.confirmed and result.observed and len(sent) == 1 and result.status is S.UNVERIFIED and result.reason == UNVERIFIED
    assert result.attempts == (cc.Attempt(1, 1, None, "", ids),) and request.log.events == [UNPARSED]

@pytest.mark.parametrize("root,surveyed,top,status,count", [
    ("", True, (), S.UNCHECKED, 0), ("/workspace", False, (), S.UNCHECKED, 0),         # nothing can be inspected: said so, not confirmed
    ("/workspace", True, (), S.ABSENT, 0), ("/workspace", True, (".git",), S.ABSENT, 0),   # an empty workspace names the artifact absent
    ("/workspace", True, None, S.CONFIRMED, 1), ("/workspace", True, ("file.txt",), S.CONFIRMED, 1),
])
def test_a_claimed_artifact_in_an_empty_workspace_is_absent_without_asking_and_an_unsurveyed_one_is_unchecked(root, surveyed, top, status, count):
    request = source(claim="Write `report.md`", workspace_root=root)
    svc, sent = services([completion("CONSISTENT", 1)], surveyed=surveyed, top=top)
    result = cc.confirm(request, svc)
    assert result.status is status and len(sent) == count and result.observed is (status is not S.UNCHECKED)
    assert result.confirmed is (status in (S.CONFIRMED, S.UNCHECKED))
    if status is S.ABSENT:
        assert result.reason == prompts.render("confirm_absent_artifact", artifact="report.md")

def test_no_private_reasoning_or_diagnosis_rescues_an_unreadable_confirmation():
    comp = completion("garbage")
    comp["choices"][0]["message"]["reasoning_content"] = '{"consistent":true}'
    svc, sent = services([comp], diagnosis=lambda *a: pytest.fail("an unknown confirmation consulted a diagnosis"))
    result = cc.confirm(source(), svc)
    assert not result.confirmed and len(sent) == 1 and result.status is S.UNVERIFIED

@pytest.mark.parametrize("selection,authority,runs", [
    (cc.Selection(None, 5, True), cc.Authority.TASK, False), (cc.Selection(cc.DEFINITION, 3, True), cc.Authority.TASK, False),
    (cc.Selection(cc.DEFINITION, 4, True), cc.Authority.TASK, True),                       # the whole-task confirmation is a level-4 behaviour
    (cc.Selection(cc.DEFINITION, 5, False), cc.Authority.STEP, False),                     # step authority needs explicit planning consent...
    (cc.Selection(cc.DEFINITION, 4, True), cc.Authority.STEP, False),                      # ...and level 5
    (cc.Selection(cc.DEFINITION, 5, "false"), cc.Authority.STEP, False), (cc.Selection(cc.DEFINITION, 5, 1), cc.Authority.STEP, False),
    (cc.Selection(cc.DEFINITION, 5, True), cc.Authority.STEP, True),
])
def test_confirmation_runs_at_its_level_and_step_authority_needs_explicit_consent(selection, authority, runs):
    """An unselected confirmation answers NOT_SELECTED before gathering any fact or calling any provider; consent is never inferred
    from a truthy value, a high rung or a prior approval, and a caller's authority must match the request it builds."""
    ran = []
    svc, _ = services([completion("CONSISTENT", 1)])

    def build():
        ran.append("source")
        return source(authority=authority)
    result = selection.run(authority, build, lambda: svc)
    assert bool(ran) is runs and (result.status is S.NOT_SELECTED) is (not runs)
    if not runs:
        assert not result.confirmed and not result.observed
    other = cc.Authority.STEP if authority is cc.Authority.TASK else cc.Authority.TASK
    if runs:
        with pytest.raises(ValueError, match="authority"):
            selection.run(authority, lambda: source(authority=other), lambda: svc)
    with pytest.raises(ValueError, match="authority"):
        selection.run("step", lambda: source(), lambda: svc)

@pytest.mark.parametrize("claim,root,top,absent", [
    ("Write `report.md`", "/workspace", [], "report.md"),
    (None, "/workspace", [], ""),                       # a step with no text names no artifact (and must not crash the reader)
    ("Write `report.md`", "", [], ""),                  # no root: nothing to look at, whatever the inventory says
    ("Write `report.md`", "/workspace", None, ""),      # unknown inventory is not emptiness
    ("Write `report.md`", "/workspace", ["src"], ""),   # a nonempty workspace is never judged here
])
def test_an_artifact_is_absent_only_from_a_known_empty_workspace_and_a_missing_claim_or_root_names_nothing(claim, root, top, absent):
    assert cc.absent_artifact(claim, root, cc.Facts(lambda r: True, lambda r: top)) == absent

@pytest.mark.parametrize("length,clipped", [(120, False), (121, True)])
def test_the_restated_claim_event_carries_at_most_the_first_120_characters_and_marks_a_cut(length, clipped):
    why = "x" * (length - 1) + "y"
    request = source(reason=why)
    svc, _sent = services([completion(f'{{"consistent":false,"why":"{why}"}}')] * 2)
    assert cc.confirm(request, svc).status is S.UNVERIFIED
    head = next(f["head"] for name, f in request.log.events if name == "loop.confirm_restated_claim")
    assert head == (why[:120] + "…" if clipped else why) and ("y" in head) is (not clipped)
