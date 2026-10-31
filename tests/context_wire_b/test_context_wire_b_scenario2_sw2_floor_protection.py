"""The floor under pressure with a protected current result: the producer-named call/result pair survives even when everything older is
shed, an unprovable protection is a loud error (never a silent drop), and degenerate inputs pass through unchanged."""
from copy import deepcopy

import pytest

from cria import contextfloor

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
