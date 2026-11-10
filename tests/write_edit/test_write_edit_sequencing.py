"""Calls of one turn on one file are applied by cria in the order SENT, however the harness schedules its calls, and cost ONE read and ONE write."""
import os

import pytest

from cria import denial
from write_edit_helpers import call, command_of, lower, run, run_batch, scratch_of, settle, shrink_services, write_edit_workspace_view  # noqa: F401


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
    """Start the LAST call first: the same bytes as in-order, every call landed, no litter in tree or TMPDIR. (cria applies the calls in
    order itself; the harness's own calls only carry the first one's read and keep the model's calls paired with results.)"""
    calls, before, after = BATCHES[label]
    tmp_path.joinpath("f.txt").write_text(before)
    msgs = run_batch(numbered(calls), tmp_path, list(reversed(range(len(calls)))))
    results = [m for m in msgs if m["role"] == "tool"]
    assert tmp_path.joinpath("f.txt").read_text() == after
    assert len(results) == len(calls) and all(denial.landed(m) for m in results)
    assert os.listdir(tmp_path) == ["f.txt"] and os.listdir(scratch_of(tmp_path)) == ["bin"]


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
