"""Offline contracts for source-owned memory stages; not full runtime acceptance.

Synthetic histories and injected callbacks only. Wire integration regressions
remain in their existing files; no fixture represents a model efficacy result.
"""
import copy
from dataclasses import replace
import json
from unittest.mock import patch

import pytest

from cria import bodykeys, focustrim, modelview, selfcompact
from cria.memoryeffects import Effect
from cria.memoryhandoff import HandoffResult


def pair(cid, name, args, output):
    return [{"role": "assistant", "content": "", "tool_calls": [{
        "id": cid, "type": "function", "function": {
            "name": name, "arguments": json.dumps(args)}}]},
        {"role": "tool", "tool_call_id": cid, "content": output}]


def history(n=16):
    return [{"role": "system", "content": "system"}] + [
        {"role": "assistant", "content": f"Observed {i}: " + "x" * 240}
        for i in range(n)]


def rolling_input(messages, writer, **kw):
    return selfcompact.RollingInput(messages, writer, trigger_tokens=100,
                                   keep_tail_tokens=100, recompact_tokens=100, **kw)


def test_rolling_definition_owns_algorithm_and_legacy_api_remains_identical():
    messages = history()
    before = copy.deepcopy(messages)
    requests = []
    def writer(mm):
        requests.append(copy.deepcopy(mm))
        return "Earlier work was observed."
    source = rolling_input(messages, writer, pinned_task="ORIGINAL TASK")
    result = selfcompact.DEFINITION.execute(source, selfcompact.CompactState())
    # Frozen model-facing outcome, not another route into the same engine.
    expected = [before[0], {
        "role": "user", "content":
        "⟦ctx:task⟧ Your ORIGINAL task for this session — keep it as your north star and do NOT "
        "drift onto tangential work; everything below serves THIS:\nORIGINAL TASK"}, {
        "role": "user", "content":
        "⟦ctx:rollup⟧ Summary of your earlier turns this session (older turns were elided to keep "
        "you focused). Use it as CONTEXT so you don't re-derive what you already worked out — but it "
        "is a summary, NOT a statement that the task is done: anything it describes as unfinished, "
        "failing, or blocked still needs doing. Where a real tool result or the files on disk "
        "disagree with it, those are the ground truth — read them rather than trusting this:\n"
        "Earlier work was observed."}, before[16]]
    assert result.messages == expected
    assert requests == [before[1:16]]
    assert result.state == selfcompact.CompactState("Earlier work was observed.", 16, 16)
    assert not result.force_pending and result.refold_effect is Effect.NO_OP
    # Adapter equality below is additional wiring coverage, not the semantic oracle.
    legacy = selfcompact.compact(messages, source.summarize, selfcompact.CompactState(),
                                 trigger_tokens=100, keep_tail_tokens=100,
                                 recompact_tokens=100, pinned_task="ORIGINAL TASK")
    assert result.effect is Effect.REDUCED
    assert legacy == (result.messages, result.state, True)
    assert messages == before
    assert "ORIGINAL TASK" in result.messages[1]["content"]
    assert result.state.covered == result.state.attempted > 0
    assert requests == [before[1:16], before[1:16]]


def test_legacy_rolling_entry_uses_the_replaced_definition_not_a_hidden_algorithm():
    messages = history()
    state = selfcompact.CompactState()
    received = []
    def replacement(source, current, *, enabled=True):
        received.append((source, current, enabled))
        return selfcompact.RollingResult(source.messages, current, Effect.WITHHELD)
    definition = replace(selfcompact.DEFINITION, execute=replacement)
    with patch.object(selfcompact, "DEFINITION", definition), patch.object(
            selfcompact, "_msg_tokens", side_effect=AssertionError("old algorithm bypassed replacement")):
        out, returned, applied = selfcompact.compact(messages, lambda mm: "unused", state,
                                                   pinned_task="original", force=True)
    assert out is messages and returned is state and not applied
    assert len(received) == 1 and received[0][0].pinned_task == "original"
    assert received[0][0].force and received[0][2]


def test_disabled_rolling_does_not_detect_call_or_consume_force():
    source = rolling_input(history(), lambda mm: pytest.fail("writer ran"), force=True)
    state = selfcompact.CompactState("prior", 3, 5)
    with patch.object(selfcompact, "_msg_tokens", side_effect=AssertionError("detection ran")):
        result = selfcompact.DEFINITION.execute(source, state, enabled=False)
    assert result.messages is source.messages and result.state is state
    assert result.effect is Effect.NO_OP and result.force_pending
    assert state == selfcompact.CompactState("prior", 3, 5)


def test_rejected_attempt_is_withheld_and_throttled_without_advancing_coverage():
    calls = []
    source = rolling_input(history(), lambda mm: calls.append(mm) or "")
    first = selfcompact.DEFINITION.execute(source, selfcompact.CompactState())
    assert first.effect is Effect.WITHHELD
    assert first.messages is source.messages
    assert first.state.attempted > 0 and first.state.covered == 0
    second = selfcompact.DEFINITION.execute(source, first.state)
    assert second.effect is Effect.NO_OP and len(calls) == 1
    grown = replace(source, messages=history(24))
    third = selfcompact.DEFINITION.execute(grown, second.state)
    assert third.effect is Effect.WITHHELD and len(calls) == 2
    assert third.state.attempted > first.state.attempted


def test_boundary_consumption_and_new_state_are_explicit_even_for_withheld_work():
    source = rolling_input(history(), lambda mm: "", force=True, pinned_task="original")
    rejected = selfcompact.DEFINITION.execute(source, selfcompact.CompactState())
    assert rejected.effect is Effect.WITHHELD and not rejected.force_pending
    fresh = selfcompact.CompactState()
    assert fresh.summary == "" and fresh.covered == fresh.attempted == 0
    # Reuse can be throttled in one task without contaminating a new one.
    calls = []
    fresh_result = selfcompact.DEFINITION.execute(
        replace(source, summarize=lambda mm: calls.append(mm) or "Completed earlier work."), fresh)
    assert fresh_result.effect is Effect.REDUCED and len(calls) == 1
    assert "original" in fresh_result.messages[1]["content"]


def test_refold_keeps_newer_grounding_separate_and_failed_refold_keeps_increment():
    messages = history()
    scopes = []
    def writer(mm, *, newer_messages):
        scopes.append((mm, newer_messages))
        return "Validated increment. " * 100
    def refold(text, *, newer_messages):
        scopes.append((text, newer_messages))
        return ""  # rejected refold must not erase accepted increment
    source = rolling_input(messages, writer, refold=refold, refold_tokens=1, with_grounding=True)
    result = selfcompact.DEFINITION.execute(source, selfcompact.CompactState())
    assert result.effect is Effect.REDUCED
    assert "Validated increment." in result.state.summary
    assert result.refold_effect is Effect.WITHHELD
    assert scopes[0][1] == scopes[1][1] == messages[result.state.covered:]
    assert result.messages[-1] == messages[-1]


def test_focus_order_selection_and_replacement_are_real_execution():
    seen = []
    def replacement(name):
        def run(messages):
            seen.append((name, [m["content"] for m in messages]))
            return messages + [{"role": "user", "content": name}], focustrim.TrimReport(squashed_runs=1)
        return run
    definitions = tuple(replace(d, execute=replacement(d.policy.id)) for d in focustrim.FOCUS_STAGE)
    result = focustrim.focus(focustrim.FocusInput([]), definitions)
    assert result.applied_ids == tuple(d.policy.id for d in definitions)
    assert seen[0][1] == []
    assert seen[1][1] == [definitions[0].policy.id]
    assert seen[2][1] == [definitions[0].policy.id, definitions[1].policy.id]
    seen.clear()
    selected = focustrim.focus(focustrim.FocusInput([]), (definitions[1],))
    assert len(seen) == 1 and selected.applied_ids == (definitions[1].policy.id,)


def test_disabled_focus_does_not_scan_history():
    class Unreadable(list):
        def __iter__(self):
            raise AssertionError("disabled detector ran")
    messages = Unreadable([{}])
    result = focustrim.focus(focustrim.FocusInput(messages), ())
    assert result.messages is messages and result.effect is Effect.NO_OP
    assert result.pending_settlement == ()
    assert focustrim.settle_focus(focustrim.FocusInput(messages), ()).messages is messages


def test_focus_legacy_repeat_notice_counter_is_not_silently_redefined():
    messages = pair("a", "read_file", {"path": "a"}, "answer")
    messages += pair("b", "read_file", {"path": "a"}, "answer")
    result = focustrim.focus(focustrim.FocusInput(messages))
    # The newest exact call/result survives, followed by truthful repeat advice.
    # trim() is now a source adapter, so its equality cannot prove this body.
    expected = pair("b", "read_file", {"path": "a"}, "answer") + [{
        "role": "user", "content":
        "[you have now made this exact call 2 times and it returned the exact same result every time "
        "— the earlier copies were folded away, so this is the only record of it. Tried: read_file(a). "
        "Repeating it again will return that same result: it has told you everything it can. "
        "Read what it already returned above, or take a DIFFERENT action.]"}]
    assert result.messages == expected
    assert result.report == focustrim.TrimReport(dropped_calls=1, dropped_msgs=1, squashed_runs=1)
    legacy, report = focustrim.trim(messages)
    assert legacy == result.messages
    assert result.report.squashed_runs == 1 and report.squashed_runs == 0
    assert dict(result.stage_reports)[focustrim.DUPLICATES.policy.id].squashed_runs == 1


def test_real_focus_keeps_different_outputs_mutations_and_hard_failures():
    messages = pair("a", "read_file", {"path": "a"}, "first")
    messages += pair("b", "read_file", {"path": "a"}, "second")
    messages += pair("c", "read_file", {"path": "a"}, "second")
    for i in range(5):
        messages += pair(f"fail{i}", "shell", {"command": f"check {i}"},
                         f"not found {i}\nProcess exited with code 1")
    messages += pair("write", "write_file", {"path": "a", "content": "fresh"}, "Wrote a")
    before = copy.deepcopy(messages)
    result = focustrim.focus(focustrim.FocusInput(messages))
    calls = {tc["id"] for m in result.messages for tc in m.get("tool_calls", [])}
    assert result.effect is Effect.REDUCED
    assert "a" in calls and "b" not in calls and "c" in calls and "write" in calls
    assert {f"fail{i}" for i in range(5)} <= calls
    assert messages == before
    legacy, report = focustrim.trim(messages)
    assert legacy == result.messages and report == result.report


def test_supersession_producer_and_final_settlement_have_one_definition():
    old, new = "old\n" * 500, "new\n" * 500
    messages = pair("old", "write_file", {"path": "/w/a", "content": old}, "Wrote /w/a")
    messages += pair("new", "write_file", {"path": "/w/a", "content": new}, "Wrote /w/a")
    result = focustrim.focus(focustrim.FocusInput(messages), (focustrim.SUPERSESSION,))
    assert result.effect is Effect.REDUCED and result.superseded_calls == 1
    assert len(result.pending_settlement) == 1
    assert modelview.superseded_writes_truth is focustrim.SUPERSESSION.settle
    intact = focustrim.settle_focus(focustrim.FocusInput(result.messages))
    assert intact.effect is Effect.NO_OP and intact.messages is result.messages
    # A later read is not the promised historical write. Qualify the claim only.
    missing = [m for m in result.messages if not m.get("tool_calls") and m.get("role") != "tool"]
    missing += pair("read", "read_file", {"path": "/w/a"}, new)
    settled = focustrim.settle_focus(focustrim.FocusInput(missing))
    assert settled.effect is Effect.SETTLED
    assert settled.messages[-1]["content"] == new
    assert settled.messages != missing
    assert "old\n" not in str(settled.messages)


def test_wire_stages_preserve_source_and_selection_without_gathering_on_bypass():
    payload = "precise observed evidence\n" * 100
    messages = pair("first", "read_file", {"path": "a"}, payload)
    messages += pair("last", "read_file", {"path": "a"}, payload)
    before = copy.deepcopy(messages)
    folded = modelview.fold_selected(modelview.WireInput(messages))
    assert folded.effect is Effect.REDUCED and folded.repeated_messages == 1
    assert folded.applied_ids == (modelview.REPEATED_PAYLOADS.policy.id,)
    assert folded.messages[-1]["content"] == payload
    assert folded.messages[1]["content"] != payload
    assert messages == before
    assert modelview.fold_evidence(messages) == folded.messages
    assert modelview.fold_selected(modelview.WireInput(messages), ()).messages is messages
    class Unreadable(list):
        def __iter__(self):
            raise AssertionError("disabled wire policy scanned evidence")
    bypass = Unreadable(messages)
    assert modelview.fold_selected(modelview.WireInput(bypass), ()).messages is bypass
    replacement = replace(modelview.REPEATED_CHECKS,
                          execute=lambda mm: mm + [{"role": "user", "content": "replacement"}])
    assert modelview.fold_selected(modelview.WireInput(messages), (replacement,)).messages[-1]["content"] == "replacement"


def test_wire_check_runs_fold_only_when_the_later_exact_source_survives():
    evidence = "".join(f"Observed diagnostic {i}: exact fact {i * 7919}.\n" for i in range(100))
    messages = [{"role": "user", "content": modelview.CONTINUATION + "\n" + evidence},
                {"role": "user", "content": "⟦ctx:steer⟧\n" + evidence}]
    folded = modelview.fold_selected(modelview.WireInput(messages), (modelview.REPEATED_CHECKS,))
    assert folded.effect is Effect.REDUCED
    assert folded.messages[-1] == messages[-1]
    assert len(folded.messages[0]["content"]) < len(messages[0]["content"])
    survivor = [messages[0]]  # emulate floor removing the later copy BEFORE final folding
    intact = modelview.fold_selected(modelview.WireInput(survivor), (modelview.REPEATED_CHECKS,))
    assert intact.effect is Effect.NO_OP and intact.messages is survivor


def test_delivery_never_turns_offer_or_stand_in_into_whole_read_credit():
    offered = {"a": "exact-body-hash"}
    block = {"role": "user", "content": "⟦ctx:current⟧\nactual bytes",
             bodykeys.RESTORED_FILES: modelview.restored_hint("⟦ctx:current⟧\nactual bytes", offered, ["a", "b"])}
    source = modelview.DeliveryInput([block], offered, ("b",))
    delivered = modelview.settle_delivery(source)
    assert delivered.effect is Effect.DELIVERED and delivered.delivered == offered
    assert delivered.pending_paths == ("b",)
    reduced = modelview.settle_delivery(replace(source, messages=[{
        "role": "user", "content": "⟦ctx:reduced⟧ current text not shown: a, b"}]))
    assert reduced.effect is Effect.REDUCED and reduced.delivered == {}
    pending = modelview.settle_delivery(modelview.DeliveryInput([], {}, ("b",)))
    assert pending.effect is Effect.PENDING and pending.delivered == {}
    assert modelview.settle_delivery(modelview.DeliveryInput([], {})).effect is Effect.NO_OP


def test_withheld_handoff_cannot_claim_accepted_prose():
    result = HandoffResult({"choices": []}, Effect.WITHHELD, ledger="Tool outcomes only")
    assert result.prose == "" and result.ledger
    with pytest.raises(ValueError, match="Withheld"):
        HandoffResult({}, Effect.WITHHELD, prose="unvalidated progress")
