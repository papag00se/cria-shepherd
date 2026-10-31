"""Composed writer/continuation contracts, not just the inventory's closing caveat.

All workspace facts come from a harness survey; all upstreams below are fake.
The shared-code dependency is separately exercised in test_compaction_newer_grounding.py.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cria import groundtruth, loop, prompts, selfcompact, server, wsview

ROOT = "/ws"
ERROR = "DebugRun.java:21: bad operand type int for unary operator '!'\nDebugRun.java:23: cannot find symbol"
FLAVORS = ("judge", "planner", "briefing", "coder")


def view(*, complete=True, folded=False, changed=False, empty=False):
    v = wsview.View(ROOT, "freshness-contract")
    tree = "D\t\n" if empty else "D\t\nF\t5\t100\tImporter.java\n"
    if folded:
        tree += "X\t400\tvendor\n"
    v._ingest_tree(tree, complete=complete)
    if changed:
        v.note_a_mutator_ran()
    return v


@pytest.mark.parametrize("flavor", FLAVORS)
@pytest.mark.parametrize("state", ("stale", "partial", "folded", "partial_stale"))
def test_uncertain_inventory_never_claims_freshness_even_in_its_header(flavor, state):
    v = view(complete=state not in ("partial", "partial_stale"),
             folded=state == "folded", changed=state in ("stale", "partial_stale"))
    token = wsview.bind(v)
    try:
        before = (v.complete, v.folded, v.may_have_changed)
        packet = server._compaction_body({"messages": [{"role": "user", "content": "task"}]}, ROOT)
        inventory = groundtruth.workspace_inventory(ROOT, flavor, compacted=True)
        assert (v.complete, v.folded, v.may_have_changed) == before
    finally:
        wsview.unbind(token)
    assert "Importer.java" in inventory
    # The shared system rule must defer to the survey's scope too. A caveat at the
    # end cannot undo an unconditional earlier claim that it was read 'just now'.
    text = inventory + "\n" + packet["messages"][0]["content"]
    for false_claim in ("RIGHT NOW", "right now", "just now", "at judging time",
                        "before any work has started", "and it is complete"):
        assert false_claim not in text
    labels = prompts.load_map("workspace_inventory")
    assert labels["complete"] not in inventory
    assert labels["stale" if state == "stale" else "partial"] in inventory
    if state == "partial_stale":
        assert labels["stale"] in inventory


@pytest.mark.parametrize("flavor", FLAVORS)
def test_fresh_complete_empty_partial_empty_and_unknown_remain_distinct(flavor):
    labels = prompts.load_map("workspace_inventory")
    for v, is_empty in ((view(), False), (view(empty=True), True)):
        token = wsview.bind(v)
        try:
            text = groundtruth.workspace_inventory(ROOT, flavor)
        finally:
            wsview.unbind(token)
        if is_empty:
            assert "none" in text
        else:
            assert "Importer.java" in text
            if flavor != "coder":
                assert labels["complete"] in text
            else:
                assert labels["coder_note"] in text
    for v in (wsview.View(ROOT, "unknown"), view(empty=True, complete=False),
              view(empty=True, changed=True)):
        token = wsview.bind(v)
        try:
            assert groundtruth.workspace_inventory(ROOT, flavor) == ""
        finally:
            wsview.unbind(token)


def session(*, age=8, unedited=False):
    return SimpleNamespace(last_gate_flag=ERROR, last_gate_red=True, last_gate_testless=False,
                           action_seq=10, last_gate_seq=10-age, gate_plan=None,
                           write_tracking=unedited, write_call_ids=[], gate_write_mark=0,
                           gate_pending_write_ids=set(), refused_write_ids=set())


def service(sess):
    return SimpleNamespace(cfg=SimpleNamespace(routing=SimpleNamespace(roles={})),
                           loop=SimpleNamespace(_store=SimpleNamespace(get=lambda key: sess)))


@pytest.mark.parametrize("testless", (False, True))
def test_rolling_check_observation_stays_true_when_carried_after_newer_success(testless):
    s = session()
    if testless:
        s.last_gate_red = False
        s.last_gate_flag = ""
        s.last_gate_testless = True
    frozen = loop._briefing_gate_ground_truth(s)
    s.action_seq += 3  # time moves on; frozen text cannot be rewritten
    assert "when this briefing was written" in frozen
    assert "later result" in frozen
    assert "currently FAIL" not in frozen
    assert "Trust this over any claim" not in frozen
    if testless:
        assert "NO tests" in frozen
    else:
        assert ERROR in frozen  # the actual errors survive verbatim, not paraphrased
    s.last_gate_red = s.last_gate_testless = False
    s.last_gate_flag = ""
    assert loop._briefing_gate_ground_truth(s) == ""


@pytest.mark.parametrize("age", (0, 1, 2, 8))
@pytest.mark.parametrize("unedited", (False, True))
def test_empty_harness_retry_has_the_same_age_and_precedence_as_first_request(age, unedited):
    s = session(age=age, unedited=unedited)
    svc = service(s)
    messages = [{"role": "user", "content": "Fix the importer."},
                {"role": "assistant", "content": "A real check follows."}]
    first = server._compaction_body({"messages": messages}, ROOT, None, ERROR, server._gate_age(svc, "s"))
    calls = []

    class Provider:
        @staticmethod
        def chat(body, rlog):
            calls.append(body)
            return json.dumps({"choices": [{"message": {"content": "Retrospective session observations."}}]})

    v = view(changed=True)
    token = wsview.bind(v)
    try:
        with patch.object(server, "_session_cwd", return_value=ROOT), \
             patch.object(server, "validate_compaction_briefing", return_value=True):
            server._harden_compaction_reply({"choices": [{"message": {"content": ""}}]},
                                           {"messages": messages}, Provider, svc,
                                           SimpleNamespace(emit=lambda *a, **k: None), "s")
    finally:
        wsview.unbind(token)
    assert len(calls) == 1
    # Compare the real rendered check block, not call-site source or a spy on kwargs.
    def check_block(body):
        return next(m["content"] for m in body["messages"] if "THE REPO'S OWN CHECKS" in m["content"])
    assert check_block(calls[0]) == check_block(first)
    assert ERROR in check_block(calls[0])
    if age >= selfcompact.CHECKS_STALE_AFTER:
        assert "later result" in check_block(calls[0]).lower() or "LATER command" in check_block(calls[0])
        assert ("none of the coder's file edit/write" in check_block(calls[0])) == unedited


@pytest.mark.parametrize("age", (0, 1, 2, 8))
def test_input_precedence_follows_real_result_order_even_before_stale_threshold(age):
    text = selfcompact.checks_input(ERROR, loop.GateAge(age))
    assert "later result" in text.lower()
    assert "If this section and the transcript disagree, this section is right." not in text
    assert ERROR in text


def test_harness_appendix_header_names_historical_observation_not_live_state():
    note = server._last_checks_note(service(session()), "s")
    assert "LATEST CHECK RESULTS" in note  # compatibility of the evidence carrier's title
    assert "AS OF THIS HANDOFF" in note
    assert "8 of your calls before this handoff was written" in note
    assert ERROR in note


def test_file_correction_preserves_negative_work_without_upgrading_survey_age():
    v = view(changed=True)
    token = wsview.bind(v)
    try:
        inventory = groundtruth.workspace_inventory(ROOT, "coder")
    finally:
        wsview.unbind(token)
    briefing = "Importer.java: the count increment has not been written."
    out = loop._briefing_disk_truth(briefing, inventory)
    assert out.startswith(briefing)
    assert "on disk right now" not in out
    assert "observed" in out and "Importer.java" in out[len(briefing):]
    assert "contents" in out and "does not establish" in out


def test_harness_file_appendix_never_promotes_an_old_survey_to_current():
    v = view(changed=True)
    token = wsview.bind(v)
    try:
        text = server._workspace_listing(ROOT)
    finally:
        wsview.unbind(token)
    assert "Importer.java" in text
    assert "on disk right now" not in text
    assert prompts.load_map("workspace_inventory")["stale"] in text
