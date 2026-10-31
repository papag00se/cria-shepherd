"""Which overwrite-evidence facts a lowered write/edit's own receipt makes attributable, run through the REAL programs.

A lowered write or edit prints, after the mutation, a typed `landed` / `unapplied` / `uncertain` record bound to its call
(`denial` / `resultpacket`). That record is the producer-issued fact "THIS invocation completed / did not run / may have
changed the file". Three classes of stale-evidence failure follow from it:

(a) already handled: a result that never arrived or arrived cut proves nothing, a reply that says "still running" is not
    completion, and a legitimate revert is an ordinary landed write that nothing blocks.
(b) fixable because completion IS attributable: calls of one turn that share a file ran CONCURRENTLY and in any order. Only edit
    after edit queued (a done-mark each program leaves at exit); a whole write ran wherever the scheduler put it, so
    `write f=A; write f=B` could leave A on disk while the ledger, the coder and every later fact said B, and
    `write f; edit f` edited the OLD file. Whole writes now queue behind the same-file calls sent ahead of them, and a call that
    ran early because a predecessor never finished says so in its record (`late`), which makes the path unestablished instead of
    stating the call's own bytes as the file.
(c) not attributable without a cooperating executor: a NATIVE shell writer (cria composed no record), and a lowered writer whose
    reply never arrived (still running and lost are the same input). See docs/check-evidence-custody.md.
"""
import json
import os
import subprocess
import tempfile
import threading
import time
from unittest import mock

import pytest

from cria import completionmeasure, denial, loop, writeproxy, wsview
from tests.harnessenv import harness_env
from tests.resultshape import genuine_call

SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}


def W(content, path="f.txt"):
    return "write_file", {"path": path, "content": content}


def E(old, new, path="f.txt"):
    return "edit_file", {"path": path, "old_string": old, "new_string": new}


def lower(calls, cwd):
    comp = {"choices": [{"message": {"tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
        for i, (n, a) in enumerate(calls)]}}]}
    writeproxy.translate_outbound(comp, SHELL, injected={"write_file", "edit_file"}, workspace_root=str(cwd))
    return comp["choices"][0]["message"]["tool_calls"]


def run_batch(calls, cwd, start_order, gap=0.12, skip=()):
    """The harness's side of ONE assistant turn: the real lowered commands, run as concurrent processes that START in
    ``start_order`` (a scheduler is free to pick any), the replies assembled in CALL order (what a harness hands back) and
    re-presented by the real `represent_inbound`. ``skip`` are calls that never run (their reply never arrives)."""
    tcs = lower(calls, cwd)
    done = {}

    def one(i):
        cmd = json.loads(tcs[i]["function"]["arguments"])["cmd"]
        done[i] = subprocess.run(["bash", "-c", cmd], cwd=str(cwd), env=harness_env(cwd), capture_output=True, text=True)

    threads = []
    for i in start_order:
        if i in skip:
            continue
        t = threading.Thread(target=one, args=(i,))
        t.start()
        threads.append(t)
        time.sleep(gap)
    for t in threads:
        t.join()
    msgs = [{"role": "assistant", "tool_calls": tcs}]
    for i, tc in enumerate(tcs):
        if i in done:
            p = done[i]
            raw = ("Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code %d\nOriginal token count: 9\nOutput:\n"
                   % p.returncode + p.stdout + p.stderr)
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": raw})
    token = wsview.bind(wsview.View(str(cwd), "uv"))
    try:
        return writeproxy.represent_inbound(msgs, workspace_root=str(cwd))
    finally:
        wsview.unbind(token)


@pytest.fixture
def ws():
    with tempfile.TemporaryDirectory() as d:
        yield d


def put(ws, text, name="f.txt"):
    path = os.path.join(ws, name)
    with open(path, "w") as f:
        f.write(text)
    return path


def disk(ws, name="f.txt"):
    with open(os.path.join(ws, name)) as f:
        return f.read()


def results(msgs):
    return [m for m in msgs if m.get("role") == "tool"]


def ledger_size(msgs):
    return loop._extract_writes(msgs).get("f.txt", (None,))[0]


# ----------------------------------------------------------------------------------------------------------- (a)

def test_a_write_whose_reply_says_still_running_is_not_a_landed_write(ws):
    msgs = genuine_call("write_file", {"path": "f.txt", "content": "A\n"}, "w1", ws, running=True)
    assert denial.landed_call_ids(msgs) == set()
    assert loop._extract_writes(msgs) == {}


def test_a_write_whose_record_arrived_cut_is_not_a_landed_write(ws):
    msgs = genuine_call("write_file", {"path": "f.txt", "content": "A\n"}, "w1", ws, cut_stdout=20)
    assert disk(ws) == "A\n"                       # it DID happen — and nothing received can prove it
    assert denial.landed_call_ids(msgs) == set()
    assert loop._extract_writes(msgs) == {}


def test_a_write_whose_reply_never_arrived_is_not_a_landed_write(ws):
    put(ws, "init\n")
    msgs = run_batch([W("A\n")], ws, [0], skip={0})
    assert results(msgs) == [] and loop._extract_writes(msgs) == {}


def test_a_legitimate_revert_lands_and_the_ledger_follows_it(ws):
    """File returns to an earlier content: three sequential turns, A, B, A. Nothing is held, and the final fact is A's."""
    history = []
    for n, body in enumerate(["AAAA\n", "BBBBBBBB\n", "AAAA\n"]):
        history += genuine_call("write_file", {"path": "f.txt", "content": body}, f"w{n}", ws)
    assert denial.landed_call_ids(history) == {"w0", "w1", "w2"}
    assert disk(ws) == "AAAA\n"
    assert ledger_size(history) == len("AAAA\n")


def test_a_native_shell_mutation_makes_the_file_state_unestablished(ws):
    """(c)'s conservative side: cria composed nothing for a native command, so no completion fact exists; the ledger claims no size."""
    history = genuine_call("write_file", {"path": "f.txt", "content": "AAAA\n"}, "w1", ws)
    history += [{"role": "assistant", "tool_calls": [{"id": "n1", "type": "function", "function": {
        "name": "exec_command", "arguments": json.dumps({"cmd": "printf BBBB > f.txt"})}}]},
        {"role": "tool", "tool_call_id": "n1",
         "content": "Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code 0\nOutput:\n"}]
    events = loop._file_events(history)
    assert [e[2] for e in events] == ["write", "shell"]


# ----------------------------------------------------------------------------------------------------------- (b)

@pytest.mark.parametrize("order", [[0, 1], [1, 0]], ids=["in-order", "reversed"])
def test_two_writes_of_one_turn_leave_the_last_call_on_disk_whatever_the_start_order(ws, order):
    put(ws, "init\n")
    msgs = run_batch([W("AAAA\n"), W("BBBBBBBB\n")], ws, order)
    assert disk(ws) == "BBBBBBBB\n"
    assert ledger_size(msgs) == len("BBBBBBBB\n")
    assert all(denial.landed(m) and not denial.report(m).get("late") for m in results(msgs))


@pytest.mark.parametrize("order", [[0, 1], [1, 0]], ids=["in-order", "reversed"])
def test_an_edit_sent_after_a_write_edits_the_written_file(ws, order):
    put(ws, "init\n")
    msgs = run_batch([W("AAAA\n"), E("AAAA", "XXXX")], ws, order)
    assert disk(ws) == "XXXX\n"
    assert [denial.proof(m) for m in results(msgs)] == ["landed", "landed"]


@pytest.mark.parametrize("order", [[0, 1], [1, 0]], ids=["in-order", "reversed"])
def test_a_write_sent_after_an_edit_replaces_what_the_edit_made(ws, order):
    put(ws, "init\n")
    msgs = run_batch([E("init", "XXXX"), W("AAAA\n")], ws, order)
    assert disk(ws) == "AAAA\n"
    assert [denial.proof(m) for m in results(msgs)] == ["landed", "landed"]


def test_a_mixed_run_of_three_applies_in_call_order(ws):
    put(ws, "init\n")
    msgs = run_batch([W("one two\n"), E("two", "2"), W("fresh\n")], ws, [2, 1, 0])
    assert disk(ws) == "fresh\n"
    assert [denial.proof(m) for m in results(msgs)] == ["landed"] * 3


def test_writes_to_other_files_are_not_queued(ws):
    tcs = lower([W("a\n", "a.txt"), W("b\n", "b.txt")], ws)
    assert all("_seq_open" not in json.loads(tc["function"]["arguments"])["cmd"] for tc in tcs)


def test_a_queued_batch_leaves_nothing_in_the_tree_or_the_scratch_dir(ws):
    put(ws, "init\n")
    run_batch([W("A\n"), W("B\n")], ws, [1, 0])
    assert sorted(os.listdir(ws)) == ["f.txt"]


def test_a_write_that_ran_before_a_predecessor_finished_says_so_and_claims_no_size(ws):
    """The predecessor never arrives inside the bound: the write applies (it is not held forever) and its record declares it ran
    early. What the file holds afterwards is not attributable to this write, so the ledger names no size for it."""
    put(ws, "init\n")
    with mock.patch.object(writeproxy, "EDIT_SEQ_WAIT_SECONDS", 0.3):
        msgs = run_batch([W("AAAA\n"), W("BBBBBBBB\n")], ws, [1, 0], skip={0})
    (reply,) = results(msgs)
    assert denial.landed(reply) and denial.report(reply).get("late") is True
    assert "ran before one or more calls you sent ahead of it" in reply["content"]
    assert [e[2] for e in loop._file_events(msgs)] == ["shell"]       # an unestablished touch, not a write of N bytes
    assert not any(e[2] == "write" for e in loop._file_events(msgs))


def test_a_late_whole_write_is_not_a_whole_file_fact_for_completion(ws):
    put(ws, "init\n")
    with mock.patch.object(writeproxy, "EDIT_SEQ_WAIT_SECONDS", 0.3):
        msgs = run_batch([W("AAAA\n"), W("BBBBBBBB\n")], ws, [1, 0], skip={0})
    services = completionmeasure.MeasurementServices(
        write_tools=frozenset({"write_file", "edit_file"}), whole_write_tools=frozenset({"write_file"}),
        edit_tools=frozenset({"edit_file"}), failed_ids=lambda m: set(), writes_something=lambda n, c: False,
        command=lambda a: "", arguments=lambda a: json.loads(a) if isinstance(a, str) else dict(a),
        path=lambda a, patch_ok=True: (json.loads(a) if isinstance(a, str) else dict(a)).get("path"),
        same_path=lambda a, b: a == b, view=lambda: None)
    assert completionmeasure.written_file_facts(msgs, services) == []


def test_a_held_write_releases_its_place_in_the_queue(ws):
    """The shrink-protection hold answers INSTEAD of the write program, so nothing marks the call done; its successor must not
    wait out the bound and then report running early."""
    from cria import shrinkprotection
    put(ws, "init\n")
    seen = {}
    original = writeproxy._edit_sequence

    def spy(*a):
        seen.update(original(*a))
        return seen
    with mock.patch.object(writeproxy, "_edit_sequence", side_effect=spy):
        first, second = lower([W("AAAA\n"), W("BBBB\n")], ws)
    held = shrinkprotection.wrap_finding(
        "f.txt", {"text": "held", "bytes": b"init\n"}, json.loads(first["function"]["arguments"])["cmd"],
        writeproxy._seq_release(seen[0]))
    out = {}
    thread = threading.Thread(target=lambda: out.update(first=subprocess.run(
        ["bash", "-c", held], cwd=ws, env=harness_env(ws), capture_output=True, text=True)))
    thread.start()
    started = time.monotonic()
    follow = subprocess.run(["bash", "-c", json.loads(second["function"]["arguments"])["cmd"]], cwd=ws,
                            env=harness_env(ws), capture_output=True, text=True)
    thread.join()
    assert disk(ws) == "BBBB\n" and '"late"' not in follow.stdout
    assert time.monotonic() - started < writeproxy.EDIT_SEQ_WAIT_SECONDS
