"""Calls of one turn on one file run in the order SENT, however the harness schedules them; an early call claims no bytes."""
import os
from unittest import mock

import pytest

from cria import denial, loop, writeproxy
from write_edit_helpers import call, run_batch, scratch_of, shrink_services, write_edit_workspace_view  # noqa: F401


def W(content):
    return call("write_file", {"path": "f.txt", "content": content}, "w")


def E(old, new, cid="e"):
    return call("edit_file", {"path": "f.txt", "old_string": old, "new_string": new}, cid)


def numbered(calls):
    return [{**c, "id": f"c{i}"} for i, c in enumerate(calls)]


CHAIN = [E(f"v{i}", f"v{i + 1}") for i in range(6)]          # each edit is anchored on text the previous one produced
BATCHES = {
    # phi4 / Java A11 call 0024: eleven edits of one file, run concurrently; arrival order made different bytes
    "chain of edits": (CHAIN, "v0\n", "v6\n"),
    "write then write": ([W("AAAA\n"), W("BBBB\n")], "init\n", "BBBB\n"),
    "write then edit edits the written file": ([W("AAAA\n"), E("AAAA", "XXXX")], "init\n", "XXXX\n"),
    "edit then write replaces what the edit made": ([E("init", "XXXX"), W("AAAA\n")], "init\n", "AAAA\n"),
}


@pytest.mark.parametrize("label", BATCHES)
def test_a_reversed_concurrent_batch_equals_the_call_order_result_and_leaves_nothing(tmp_path, label):
    """Start the LAST call first: the same bytes as in-order, every call landed on time (no `late`), no queue litter in tree or TMPDIR."""
    calls, before, after = BATCHES[label]
    tmp_path.joinpath("f.txt").write_text(before)
    msgs = run_batch(numbered(calls), tmp_path, list(reversed(range(len(calls)))))
    results = [m for m in msgs if m["role"] == "tool"]
    assert tmp_path.joinpath("f.txt").read_text() == after
    assert len(results) == len(calls) and all(denial.landed(m) and not denial.report(m).get("late") for m in results)
    assert os.listdir(tmp_path) == ["f.txt"] and os.listdir(scratch_of(tmp_path)) == ["bin"]


def test_a_resent_identical_batch_does_not_inherit_the_first_batchs_marks(tmp_path):
    """Two lowerings of the same two edits get distinct queues: the first batch's finished call must not satisfy the retry's predecessor."""
    tmp_path.joinpath("f.txt").write_text("a")
    edits = numbered([E("a", "b"), E("b", "c")])
    with mock.patch.object(writeproxy, "EDIT_SEQ_WAIT_SECONDS", 0.3):
        first = run_batch(edits, tmp_path, [0], skip={1})               # batch 1: only call 0 ever runs
        second = run_batch(edits, tmp_path, [1], skip={0})              # the retry sends both again; only call 1 runs
    assert tmp_path.joinpath("f.txt").read_text() == "c"
    assert denial.report(second[1]).get("late") is True and not denial.report(first[1]).get("late")


def test_a_call_that_ran_before_its_predecessor_finished_says_so_and_claims_no_bytes(tmp_path):
    """The predecessor never arrives: the write applies (never held forever), its record says `late`, the coder is told, and the
    file-event ledger records an unestablished touch — not 'N bytes written' (what is on disk is not attributable to this call)."""
    tmp_path.joinpath("f.txt").write_text("init\n")
    with mock.patch.object(writeproxy, "EDIT_SEQ_WAIT_SECONDS", 0.3):
        msgs = run_batch(numbered([W("AAAA\n"), W("BBBBBBBB\n")]), tmp_path, [1, 0], skip={0})
    (reply,) = [m for m in msgs if m["role"] == "tool"]
    assert denial.landed(reply) and denial.report(reply).get("late") is True
    assert "ran before one or more calls you sent ahead of it" in reply["content"]
    assert [e[2] for e in loop._file_events(msgs)] == ["shell"]


@pytest.mark.parametrize("first", ["refused edit", "held write"])
def test_a_predecessor_that_did_not_run_releases_its_successors_place(tmp_path, first):
    """A refused (missing new_string) or shrink-held predecessor answers INSTEAD of the program that marks the call done; its
    successor must run on time rather than wait out the bound and report `late`."""
    current = "".join(f"line {i}\n" for i in range(20))
    tmp_path.joinpath("f.txt").write_text(current)
    head = (E("line 1", None, "c0") if first == "refused edit" else W("tiny\n"))
    tail = W(current + "more\n")
    msgs = run_batch(numbered([head, tail]), tmp_path, [1, 0],
                     shrink_services=shrink_services(current, "OTHER"))
    first_reply, second_reply = [m for m in msgs if m["role"] == "tool"]
    assert denial.unlanded(first_reply)
    assert denial.landed(second_reply) and not denial.report(second_reply).get("late")
    assert tmp_path.joinpath("f.txt").read_text() == current + "more\n"
