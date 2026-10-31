"""What the rollup writer and the coder's compacted view say about odd-shaped history: a write payload is stubbed only to what later
evidence proves (edited / refused-later / overlapping / unreadable arguments), the root task is found with and without an exact pin,
an edit-recovery note keeps its headline but never its promise of a body, and a call with unreadable arguments is still narrated."""
import json

import pytest

from cria import denial, selfcompact as sc
from compaction_handoff_helpers import asst, call, result

BODY = "x = 1\n" * 200
L = denial.LANDED
u = lambda t: {"role": "user", "content": t}                                                  # noqa: E731


def tool_call(cid, name, args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}


def turn(*calls):
    return {"role": "assistant", "tool_calls": list(calls)}


def write(cid, path="a.py"):
    return tool_call(cid, "write_file", {"path": path, "content": BODY})


def stubbed(msgs):
    """The first message's write arguments (key list or raw text) and the prose note beside them, after a trailing gate probe."""
    out = sc.stub_old_write_args(msgs + [call("g", "exec_command", cmd="pytest"), result("g")])
    first = out[0]["tool_calls"][0]["function"]["arguments"]
    try:
        keys = json.loads(first)
        keys = sorted(keys) if isinstance(keys, dict) else keys
    except ValueError:
        keys = first
    return keys, out[0].get("content") or ""


EDIT = tool_call("e1", "edit_file", {"path": "a.py", "old_string": "x = 1\n" * 50, "new_string": "y = 2\n" * 50})
# (history, first write's arguments afterwards, what its note says)
FATES = [
    ([turn(write("w1")), result("w1", "Wrote", L), turn(EDIT), result("e1", "Edited", L)], ["path"], "since changed by a later edit"),
    ([turn(write("w1")), result("w1", "Wrote", L), turn(write("w2")), result("w2", "no", denial.REFUSED)], ["path"], "this exact content is on disk at a.py"),
    ([turn(write("w1"), write("w2")), result("w1", "Wrote", L), result("w2", "Wrote", L)], ["content", "path"], ""),      # same turn: unordered, kept whole
    ([turn(tool_call("w1", "write_file", "{bad")), result("w1", "Wrote", L), turn(write("w2")), result("w2", "Wrote", L)], "{bad", ""),
    ([turn(tool_call("w1", "write_file", [1, 2])), result("w1", "Wrote", L)], [1, 2], ""),                              # arguments that are not an object
    ([turn(tool_call("w1", "write_file", {"content": BODY})), result("w1", "Wrote", L)], ["content"], ""),             # no path: no claim about a file
]


@pytest.mark.parametrize("history,args,note", FATES)
def test_a_write_payload_is_stubbed_only_to_what_later_evidence_proves(history, args, note):
    keys, prose = stubbed(history)
    assert keys == args and (note in prose if note else "[elided" not in prose)


def test_the_root_task_is_the_pinned_message_or_all_initial_user_context():
    msgs = [u("banner"), u("the task"), asst(5), result("c", "r"), u("later follow-up")]
    assert sc.root_user_indices(msgs, "the task") == (1,)                 # an exact pin wins
    assert sc.root_user_indices(msgs, "no such text") == sc.root_user_indices(msgs) == (0, 1)      # an unmatched pin never discards instructions
    assert sc.root_user_indices([asst(2), u("x")]) == () and sc.root_text([asst(2)]) is None and sc.root_text(msgs) == "banner\n\nthe task"


def test_an_edit_note_keeps_its_headline_but_never_the_promise_of_a_body_it_does_not_carry():
    promise = "⟦ctx:edit⟧ a.py — Your edit did not apply. Here is its EXACT current content on disk:\nline1\nline2"
    kept = sc.edit_note_headline(promise)
    assert kept.startswith("⟦ctx:edit⟧ a.py — Your edit did not apply. [the file text") and "EXACT current content" not in kept and "line1" not in kept
    assert sc.edit_note_headline("⟦ctx:edit⟧ a.py — The edit did not apply, nothing else.\nmore") == "⟦ctx:edit⟧ a.py — The edit did not apply, nothing else."
    assert sc.edit_note_headline("  \n ") == ""


def test_calls_with_unreadable_arguments_are_still_narrated_and_blank_turns_are_not():
    calls = turn(tool_call("a", "write_file", "{bad"), tool_call("b", "read_file", "{}"), tool_call("c", "edit", [1]))
    assert sc.serialize_blocks([calls, u("  "), u("hi   there")], defang=True) == [
        "the coder called write_file / the coder called read_file / the coder called edit — [1]", "the task/context said: hi there"]
