"""The floor under pressure with a protected current result: the producer-named call/result pair survives even when everything older is
shed, an unprovable protection is a loud error (never a silent drop), and degenerate inputs pass through unchanged."""
from copy import deepcopy

import pytest

from cria import bodykeys, contextfloor

call = lambda cid: {"role": "assistant", "content": "", "tool_calls": [{"id": cid, "function": {"name": "read_file", "arguments": "{}"}}]}   # noqa: E731
result = lambda cid, text: {"role": "tool", "tool_call_id": cid, "content": text}                                                      # noqa: E731
BIG = "line of tool output\n" * 400
HISTORY = [{"role": "system", "content": "perm"}, {"role": "user", "content": "root task"}, call("c1"), result("c1", BIG), call("c2"), result("c2", BIG + "fresh"),
           {"role": "user", "content": "now what"}]


def fit(protected, **kw):
    return contextfloor.fit(deepcopy(HISTORY), None, window=1500, reserve=200, safety=1.0, pinned_task="root task", protected_call_ids=protected, **kw)


def tools_of(messages):
    return [m["tool_call_id"] for m in messages if m["role"] == "tool"]


def test_the_named_result_and_its_call_survive_when_everything_older_is_shed():
    out, _, report = fit(("c2",))
    assert tools_of(out) == ["c2"] and any("fresh" in m["content"] for m in out if m["role"] == "tool") and out[-1]["content"] == "now what"
    assert report.turns_dropped == 2 and report.protected_dropped == 0 and report.over_budget          # the protected pair alone exceeds this window
    assert any(m.get("tool_calls", [{}])[0].get("id") == "c2" for m in out if m["role"] == "assistant")    # never an orphan result
    out, _, report = fit(())
    assert tools_of(out) == [] and report.turns_dropped == 4 and not report.over_budget                  # unprotected, the same pair is dropped
    out, _, report = fit(("c1", "c2"))
    assert tools_of(out) == ["c1", "c2"] and report.turns_dropped == 0                                  # both named: both stay whole


@pytest.mark.parametrize("ids,why", [(("c1", "c1"), "unique nonempty"), (("",), "unique nonempty"), (["c2"], "unique nonempty"), (("nope",), "earlier paired call")])
def test_protection_the_producer_cannot_prove_is_an_error_not_a_silent_drop(ids, why):
    with pytest.raises(ValueError, match=why):
        fit(ids)
    reordered = [HISTORY[0], HISTORY[1], result("c2", "r"), call("c2"), HISTORY[-1]]
    with pytest.raises(ValueError, match="earlier paired call"):
        contextfloor.fit(reordered, None, window=1500, reserve=200, protected_call_ids=("c2",))


def test_an_empty_body_or_no_window_passes_through_and_still_measures_the_menu():
    menu = [{"type": "function", "function": {"name": "x", "description": "d"}}]
    out, tools, report = contextfloor.fit([], menu, window=1000, reserve=100)
    assert out == [] and tools is menu and report.tool_tokens == report.tool_tokens_before > 0 and not report.applied
    msgs = [{"role": "user", "content": "x" * 10000}]
    out, _, report = contextfloor.fit(msgs, None, window=0, reserve=100)
    assert out is msgs and report.window == 0 and not report.applied


def test_preferred_headroom_drops_stale_turns_but_never_current_work_the_hard_budget_still_holds():
    """Headroom is a preference: with it the oldest stale turns go first, and the moment what remains fits the HARD budget the live tail (the newest eight messages and their calls) stops being dropped even though the
    preferred budget is not reached; without that hard budget everything droppable goes."""
    stale = [m for i in range(3) for m in (call(f"s{i}"), result(f"s{i}", "y " * 800))]
    live = [m for i in range(4) for m in (call(f"l{i}"), result(f"l{i}", "z " * 800))]
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "task"}, *stale, *live, {"role": "user", "content": "go"}]
    hard = contextfloor._msgs_tokens([m for m in messages if m not in stale]) + 300         # what remains once only the stale turns are gone, plus room for their one note
    kept, dropped = contextfloor._drop_oldest(messages, 100, "task", sacrifice_budget=hard)
    assert tools_of(kept) == ["l0", "l1", "l2", "l3"] and dropped == 6 and kept[0]["role"] == "system" and kept[-1]["content"] == "go"
    assert "s0" not in [tc["id"] for m in kept for tc in m.get("tool_calls") or []]
    kept, dropped = contextfloor._drop_oldest(messages, 100, "task")
    assert tools_of(kept) == [] and dropped == 14


def test_a_cria_anchor_and_its_pair_stay_protected_and_a_relocated_annotation_never_becomes_a_request():
    """The drop mask: an annotation cria relocated after the request is history (droppable), never promoted to the active turn; a call carrying cria's briefing keeps its own result (else the call
    dangles); a call whose result never arrived is simply droppable."""
    tc = lambda cid: [{"id": cid, "function": {"name": "read_file", "arguments": "{}"}}]      # noqa: E731
    annotation = {"role": "user", "content": "⟦ctx:inventory⟧ files", bodykeys.ANNOTATION_SOURCE: bodykeys.AnnotationSource.INVENTORY}
    system, task, go = {"role": "system", "content": "s"}, {"role": "user", "content": "task"}, {"role": "user", "content": "go"}
    assert contextfloor._protected_mask([system, task, go, annotation], "task") == [True, True, True, False]
    briefing_call = {"role": "assistant", "content": "⟦ctx:briefing⟧ earlier work", "tool_calls": tc("k")}
    messages = [system, task, briefing_call, result("k", "r"), {"role": "assistant", "content": "", "tool_calls": tc("dangling")}, go]
    assert contextfloor._protected_mask(messages, "task") == [True, True, True, True, False, True]


def test_a_result_that_arrives_without_its_call_stays_whole_as_user_text_when_it_fits_alone_and_is_withheld_with_a_label_when_it_cannot():
    """Self-compaction can fold a call and leave its result: that result is evidence, never silently deleted. Beside the frame it still fits, it is the same text as a user turn; one that cannot fit even alone
    is replaced by a labelled not-delivered note (also recorded for the fit's report)."""
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "task"}, result("gone", "small file text"), result("gone2", "BIG line\n" * 3000), {"role": "user", "content": "go"}]
    notes = []
    out = contextfloor._stand_in_arriving_orphans(messages, None, window=2000, reserve=200, safety=1.0, overhead=0, notes=notes)
    assert [m["role"] for m in out] == ["system", "user", "user", "user", "user"] and out[2]["content"] == "small file text"
    assert out[3]["content"].startswith("⟦ctx:result-not-delivered⟧") and "3,000 line(s)" in out[3]["content"] and notes == [out[3]]
