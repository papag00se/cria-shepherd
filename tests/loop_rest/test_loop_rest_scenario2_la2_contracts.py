"""Scenario2 (LA2): the loop trusts a selected assist's typed answer only when it is the typed contract - an evidence-summary or completion-
confirmation replacement that answers wrongly stops the turn loudly instead of being believed. Real loop functions under a real runtime
whose one definition is swapped for a scripted double; the unselected arms (no definition) pass the text through untouched."""
import json
from types import SimpleNamespace

import pytest

from cria import assistruntime, completionconfirmation as cc, evidencesummary as es, loop
from loop_rest_helpers import Rlog, loop_rest_local_view  # noqa: F401
from test_loop_rest_judge_protocol import ROLE, completion, scripted

LOG = "step 1: wrote app.py\nstep 2: ran pytest\n"


def runtime(**swapped):
    rt = assistruntime.AssistRuntime.select(level=5)
    for name, value in swapped.items():
        object.__setattr__(rt, name, value)
    return rt


def summarised(rt, **kw):
    with assistruntime.bound(rt):
        return loop._summarised_evidence(LOG, None, None, Rlog(), **kw)


def result(**kw):
    fields = dict(raw=LOG, folded=LOG, selected="CHOSEN", selection=es.Selection.RAW)
    return es.Result(**{**fields, **kw})


def definition(res, settled):
    return SimpleNamespace(execute=lambda source: res, settle=lambda r, slot: settled(r, slot))


def test_with_no_evidence_policy_selected_the_log_reaches_its_consumer_untouched():
    rt = runtime(evidence_summary=None)
    assert summarised(rt) == LOG and summarised(rt, _consume=lambda text: text.upper()) == LOG.upper()


def test_a_valid_evidence_selection_is_consumed_and_settled_with_exactly_what_was_delivered():
    seen = []
    ok = definition(result(), lambda r, slot: seen.append(slot) or es.Settlement(r, slot, True))
    assert summarised(runtime(evidence_summary=ok), _consume=lambda text: "consumed:" + text) == "consumed:CHOSEN" and seen == ["CHOSEN"]
    disabled = definition(result(selection=es.Selection.DISABLED), lambda r, slot: None)
    assert summarised(runtime(evidence_summary=disabled), _consume=lambda text: "consumed:" + text) == "consumed:CHOSEN"


@pytest.mark.parametrize("res,settled", [
    ("not a result", None), (result(raw="other log"), None), (result(selected=None), None), (result(selection="raw"), None),
    (result(folded_actions=-1), None), (result(folded_actions=True), None), (result(summary=5), None),
    (result(), lambda r, slot: None), (result(), lambda r, slot: es.Settlement(result(), slot, True)),
    (result(), lambda r, slot: es.Settlement(r, "different", False)), (result(), lambda r, slot: es.Settlement(r, slot, False))])
def test_an_evidence_replacement_that_breaks_the_typed_contract_stops_the_turn(res, settled):
    with pytest.raises(ValueError, match="Evidence summary replacement must return matching"):
        summarised(runtime(evidence_summary=definition(res, settled or (lambda r, slot: es.Settlement(r, slot, True)))))


def confirm(answer):
    rt = runtime(completion_confirmation=SimpleNamespace(execute=lambda request, services: answer))
    with assistruntime.bound(rt):
        return loop._confirm_completion("claim", "reason", "/w", None, None, Rlog(), phase="t")


def test_a_confirmation_answer_is_accepted_only_when_status_flag_authority_and_observation_agree():
    good = cc.Result(cc.Status.CONFIRMED, confirmed=True, observed=True)
    assert confirm(good) is good and confirm(cc.Result(cc.Status.REJECTED, reason="no README")).reason == "no README"
    for wrong in ["confirmed", cc.Result("confirmed"), cc.Result(cc.Status.CONFIRMED, confirmed=True, observed=False),
                  cc.Result(cc.Status.CONFIRMED, confirmed=False, observed=True), cc.Result(cc.Status.REJECTED, confirmed=True),
                  cc.Result(cc.Status.UNCHECKED, confirmed=True, observed=True), cc.Result(cc.Status.UNCHECKED, confirmed=True),
                  cc.Result(cc.Status.NOT_SELECTED, observed=True),
                  cc.Result(cc.Status.REJECTED, reason=3), cc.Result(cc.Status.REJECTED, authority=cc.Authority.STEP),
                  cc.Result(cc.Status.REJECTED, observed=1)]:
        with pytest.raises(ValueError, match="Completion confirmation replacement"):
            confirm(wrong)


@pytest.mark.parametrize("reply,asked", [('{"missing_file": false}', 1), ("garbage", 1), ("", 1)])
def test_the_task_deliverable_observer_stays_silent_unless_the_observer_affirms(reply, asked, tmp_path):
    """Not-missing, unreadable and empty observer answers are silence; with no reasoner nobody is even asked; with the policy unselected
    the observer is never reached."""
    questions = []

    def chat(body, log):
        questions.append(log.phase)
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": reply}}]}).encode()
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        seen = loop.observe_task_missing_file("create app.py with main", workspace_root=str(tmp_path), reasoner_chat=chat,
                                              reasoner_role=ROLE, rlog=Rlog())
        offline = loop.observe_task_missing_file("create app.py", workspace_root=str(tmp_path), reasoner_chat=None,
                                                 reasoner_role=ROLE, rlog=Rlog())
    with assistruntime.bound(runtime(completion_diagnosis=None)):
        unselected = loop.observe_task_missing_file("create app.py", workspace_root=str(tmp_path), reasoner_chat=chat,
                                                    reasoner_role=ROLE, rlog=Rlog())
    assert seen == offline == unselected == loop.VerdictNudge() and not seen.action
    assert questions == ["deliverable-observation"] * asked


@pytest.mark.parametrize("reply,query,prior,new", [
    ('{"new_direction": true}', "eu vat rates", "gem search", True), ("```json\n{\"new_direction\": true}\n```", "q", "p", True),
    ('{"new_direction": "yes"}', "q", "p", False), ('{"new_direction": false}', "q", "p", False), ("same hunt", "q", "p", False),
    ('{"new_direction": true}', "  ", "p", False), ('{"new_direction": true}', "q", "", False)])
def test_the_rehunt_judge_grants_a_repeat_search_only_on_a_literal_new_direction(reply, query, prior, new):
    chat, bodies = scripted([completion(reply)])
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        assert loop.judge_rehunt(chat, ROLE, "charge EU VAT", query, prior, Rlog()) is new
        assert loop.judge_rehunt(chat, None, "charge EU VAT", query, prior, Rlog()) is False
    assert len(bodies) == (1 if query.strip() and prior else 0)


def test_the_critic_results_unpack_as_the_historic_two_value_pair_without_losing_the_confirmation_flag():
    ok, why = loop.Verification(True, "all checked", loop.Confirmation(True, False, "unobserved"))
    confirmed, reason = loop.Confirmation(False, True, "README absent")
    assert (ok, why, confirmed, reason) == (True, "all checked", False, "README absent")
    assert loop.Verification(True, "x", loop.Confirmation(True, False)).confirmation.observed is False
