"""Focus stages (cria.focustrim) through their public entry: the selected stages act in their one order over the real history,
an absent selection scans nothing, and a coder never sees a promise the final wire cannot keep (measured through the real Upstream._prep)."""
import copy
import json
from unittest.mock import patch

import pytest

from cria import bodykeys, config, contextfloor, denial, focustrim, upstream
from cria.memoryeffects import Effect
from context_wire_b_helpers import Rlog

PATH = "/w/src/source.txt"
NEWLINE_BODY = "".join(f"item_{i}: value={i * 7919}; description=original entry {i}\n" for i in range(160))
SECOND_BODY = NEWLINE_BODY.replace("original entry 77", "revised entry 77")


def turn(cid, name, args, result, outcome=None):
    return [{"role": "assistant", "content": "", "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
            {"role": "tool", "tool_call_id": cid, "content": result, **({bodykeys.RESULT_OUTCOME: outcome} if outcome else {})}]


def write(cid, text):
    return turn(cid, "write_file", {"path": PATH, "content": text}, f"Wrote {PATH}", denial.LANDED)


def ids(messages):
    return [tc["id"] for m in messages for tc in m.get("tool_calls") or []]


HISTORY = ([{"role": "user", "content": "keep the results"}] + turn("r1", "read_file", {"path": "spec.md"}, "the spec") + turn("r2", "read_file", {"path": "spec.md"}, "the spec")
           + write("old", NEWLINE_BODY) + write("new", SECOND_BODY)
           + turn("f1", "exec_command", {"cmd": "pytest"}, "FAILED a\nProcess exited with code 1") + turn("f2", "exec_command", {"cmd": "pytest -x"}, "FAILED b\nProcess exited with code 1"))


@pytest.mark.parametrize("selected,kept,applied", [
    ((focustrim.DUPLICATES, focustrim.FAILURES, focustrim.SUPERSESSION), ["r2", "new", "f1", "f2"], [focustrim.DUPLICATES, focustrim.SUPERSESSION]),
    ((focustrim.SUPERSESSION,), ["r1", "r2", "new", "f1", "f2"], [focustrim.SUPERSESSION]),
    ((focustrim.DUPLICATES, focustrim.FAILURES), ["r2", "old", "new", "f1", "f2"], [focustrim.DUPLICATES]),
    ((focustrim.FAILURES,), ["r1", "r2", "old", "new", "f1", "f2"], [])])
def test_only_the_selected_focus_stages_act_on_the_real_history_and_hard_failures_are_never_folded(selected, kept, applied):
    before = copy.deepcopy(HISTORY)
    out = focustrim.focus(focustrim.FocusInput(HISTORY), selected)
    assert ids(out.messages) == kept and out.applied_ids == tuple(d.policy.id for d in applied) and HISTORY == before
    assert (out.effect is Effect.REDUCED) is bool(applied) and {m["tool_call_id"] for m in out.messages if m["role"] == "tool"} == set(kept)


def test_an_absent_selection_returns_the_very_history_without_reading_it():
    class Unreadable(list):
        def __iter__(self):
            raise AssertionError("an unselected focus stage scanned the history")
    history = Unreadable([{}])
    out = focustrim.focus(focustrim.FocusInput(history), ())
    assert out.messages is history and out.effect is Effect.NO_OP and out.pending_settlement == ()
    assert focustrim.settle_focus(focustrim.FocusInput(history), ()).messages is history


PROMISE = "The whole-file write that replaced each removed call remains above in full. Nothing was lost."


def tail_history():
    """0059-shaped: two whole writes of one path, a later read and edit that do not discharge the promise, then six probe results."""
    messages = [{"role": "system", "content": "Work from returned facts."}, {"role": "user", "content": "Keep the existing results."}]
    messages += write("old", NEWLINE_BODY) + write("new", SECOND_BODY)
    messages += turn("read", "read_file", {"path": PATH}, SECOND_BODY) + turn("edit", "edit_file", {"path": PATH, "old_string": "value=0", "new_string": "value=1"}, "Wrote source.txt; replacement at line 1.", denial.LANDED)
    for i in range(6):
        messages += turn(f"p{i}", "read_file", {"path": f"/w/evidence{i}"}, "".join(f"observation {i}/{j}: returned detail {j * 29}\n" for j in range(70)))
    return messages + [{"role": "user", "content": "⟦ctx:facts⟧ Use the returned facts for this task."}]


@pytest.mark.parametrize("window", [4500, 6000, 8000, 100_000])
def test_a_promise_to_keep_the_newest_write_is_qualified_when_the_floor_removes_it_and_kept_when_nothing_is_removed(window):
    """feed-pipeline c21: the floor dropped the promised write but the notice still said it remained above. The body that is SENT decides the wording; the
    later read (a different, surviving source) is never what gets qualified."""
    focused = focustrim.focus(focustrim.FocusInput(tail_history())).messages
    up = upstream.Upstream("http://unused", context_window=window, engagement_level=config.MAX_ENGAGEMENT_LEVEL)
    request = {"model": "fixture", "messages": focused, bodykeys.PINNED_TASK: "Keep the existing results.", bodykeys.OUTPUT_RESERVE: int(contextfloor.DEFAULT_GEN_RESERVE)}
    with patch("cria.upstream.urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
        raw, _, _ = up._prep(request, False, Rlog(), safety_override=1)
    sent = json.loads(raw)["messages"]
    notice = next(m["content"] for m in sent if "earlier write(s) in this conversation" in str(m.get("content", "")))
    dropped = "new" not in ids(sent)
    assert dropped is (window < 100_000) and (PROMISE in notice) is (not dropped)
    if dropped:
        assert "historical" in notice and "To be sure, read the file" in notice and "current file is absent" not in notice
    assert not any(key.startswith("cria_") for m in sent for key in m) and b"cria_superseded" not in raw
    survivors = {tc["id"]: tc for m in focused for tc in m.get("tool_calls") or []}
    assert all(tc == survivors[tc["id"]] for m in sent for tc in m.get("tool_calls") or [])             # whatever survives keeps its exact arguments
