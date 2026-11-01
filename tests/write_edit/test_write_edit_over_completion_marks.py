"""Executor-side completion marks: a lost reply, a killed writer and an earlier turn's slow writer become KNOWN states.

Every test lowers the production way and RUNS the real programs in bash (a harness TMPDIR beside the workspace). The only fake is
a slow filesystem step: a sleep spliced in front of the landing of ONE program's bytes so a writer is visibly still running."""
import hashlib
import json
import os
import subprocess
import sys
import time
from unittest import mock

import pytest

from cria import completionmarks, denial, loop, writeproxy
from write_edit_helpers import (ENVELOPE, call, command_of, harness_env, lower, run, scratch_of,  # noqa: F401
                                write_edit_workspace_view)

SESSION = "over-session"
SLOW = "rp.parent.mkdir(parents=True,exist_ok=True)"      # the step just BEFORE a whole write takes the directory lock and lands its bytes


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def W(path, content, cid):
    return call("write_file", {"path": path, "content": content}, cid)


def E(path, old, new, cid):
    return call("edit_file", {"path": path, "old_string": old, "new_string": new}, cid)


def turn(calls, **kw):
    """One assistant turn lowered in the session (each call a lowered shell call)."""
    return lower(calls, session=SESSION, **kw)


def slow(tc, seconds):
    """The same lowered program with a slow filesystem step before it takes the directory lock (which already serializes writers that
    reached it: the race is the writer that is slow to GET there)."""
    args = json.loads(tc["function"]["arguments"])
    cmd = args["cmd"]
    assert SLOW in cmd
    return {**tc, "function": {**tc["function"], "arguments": json.dumps({**args, "cmd": cmd.replace(SLOW, f"__import__('time').sleep({seconds});{SLOW}", 1)})}}


def die_before(tc, anchor):
    """The same lowered program that ends WITHOUT its exit handlers (`os._exit`: what a kill leaves, with no signal) just before ``anchor``."""
    args = json.loads(tc["function"]["arguments"])
    assert anchor in args["cmd"]
    return {**tc, "function": {**tc["function"], "arguments": json.dumps({**args, "cmd": args["cmd"].replace(anchor, f"__import__('os')._exit(3);{anchor}", 1)})}}


def start(tc, cwd):
    return subprocess.Popen(["bash", "-c", command_of(tc)], cwd=str(cwd), env=harness_env(cwd),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)


def reply(tc, out, rc=0):
    return {"role": "tool", "tool_call_id": tc["id"], "content": ENVELOPE.format(rc=rc) + out}


def history(cwd, *items):
    """The re-presented history of ``items``: ('call', [tcs]) assistant turns and ('reply', tc, stdout) tool results, in order."""
    from write_edit_helpers import represent  # noqa: F401
    from cria import wsview
    msgs = [{"role": "assistant", "tool_calls": x[1]} if x[0] == "call" else reply(x[1], x[2]) for x in items]
    token = wsview.bind(wsview.View(str(cwd), "we"))
    try:
        return writeproxy.represent_inbound(msgs, workspace_root=str(cwd))
    finally:
        wsview.unbind(token)


def record(out):
    return json.loads(out.split("\n", 1)[0])


def marks_dir(cwd):
    (name,) = [n for n in os.listdir(scratch_of(cwd)) if n.startswith(completionmarks.DIR_PREFIX)]
    return os.path.join(scratch_of(cwd), name)


def marks(cwd):
    return sorted(n for n in os.listdir(marks_dir(cwd)) if n.startswith("m-"))


@pytest.mark.parametrize("kind", ["whole write", "edit"])
def test_a_lost_reply_of_a_write_that_completed_becomes_a_known_landed_state(tmp_path, kind):
    """The harness ran X to the end and its reply was lost. The NEXT lowered program of the session reads X's mark back: X is a
    witnessed `landed` with the digest of the bytes it left, and it is not claimed before a witness exists."""
    (tmp_path / "f.txt").write_text("old\n")
    (x,) = turn([W("f.txt", "AAA\n", "x") if kind == "whole write" else E("f.txt", "old", "AAA", "x")])
    assert start(x, tmp_path).communicate()[0].startswith('{"v":1,')                      # ran to the end; the reply is dropped
    alone = history(tmp_path, ("call", [x]))
    assert denial.witnessed_completions(alone) == {}                                      # nothing witnesses it yet: unknown
    (y,) = turn([W("g.txt", "G\n", "y")])
    out = start(y, tmp_path).communicate()[0]
    msgs = history(tmp_path, ("call", [x]), ("call", [y]), ("reply", y, out))
    on_disk = (tmp_path / "f.txt").read_text()
    assert on_disk == "AAA\n" == ("AAA\n" if kind == "edit" else on_disk)
    assert denial.witnessed_completions(msgs) == {"x": ("landed", sha("AAA\n"))}
    assert denial.landed_call_ids(msgs) == {"y"} and "x" in denial.witnessed_completed_ids(msgs)   # only a reply proves a landing claim


def test_a_lost_reply_of_a_write_that_never_ran_is_known_not_to_have_run(tmp_path):
    """X's program refused (the target is a directory) and its reply was lost: its mark says it did not run, so it is a proven
    unlanded call. A call that never STARTED has no mark: that is `incomplete` - known not complete, never claimed 'did not run'."""
    (tmp_path / "dir").mkdir()
    refused, never = turn([W("dir", "x\n", "refused"), W("h.txt", "H\n", "never")])
    assert start(refused, tmp_path).communicate()[0] != ""                                  # refused: a statement, the reply is dropped
    (y,) = turn([W("g.txt", "G\n", "y")])
    out = start(y, tmp_path).communicate()[0]
    msgs = history(tmp_path, ("call", [refused, never]), ("call", [y]), ("reply", y, out))
    assert denial.witnessed_completions(msgs) == {"refused": ("did_not_run", ""), "never": ("incomplete", "")}
    assert denial.unlanded_call_ids(msgs) == {"refused"} and denial.witnessed_completed_ids(msgs) == {"refused"}
    assert not (tmp_path / "h.txt").exists()


def test_a_witness_never_overrides_a_calls_own_reply_and_needs_an_unambiguous_call(tmp_path):
    """X's own refusal record outranks anything a witness says; a reused id (two calls named x) is not witnessed at all."""
    (tmp_path / "dir").mkdir()
    (x,) = turn([W("dir", "x\n", "x")])
    xo = start(x, tmp_path).communicate()[0]
    (y,) = turn([W("g.txt", "G\n", "y")])
    yo = start(y, tmp_path).communicate()[0]
    answered = history(tmp_path, ("call", [x]), ("reply", x, xo), ("call", [y]), ("reply", y, yo))
    assert denial.witnessed_completions(answered) == {} and denial.unlanded_call_ids(answered) == {"x"}
    twice = history(tmp_path, ("call", [x]), ("call", [x]), ("call", [y]), ("reply", y, yo))
    assert denial.witnessed_completions(twice) == {}
    (lost,) = turn([W("h.txt", "H\n", "lost")])
    start(lost, tmp_path).communicate()
    (z,) = turn([W("i.txt", "I\n", "z")])
    zo = start(z, tmp_path).communicate()[0]
    assert denial.witnessed_completions(history(tmp_path, ("call", [lost]), ("call", [z]), ("reply", z, zo))) == {"lost": ("landed", sha("H\n"))}
    assert denial.witnessed_completions(history(tmp_path, ("call", [z]), ("reply", z, zo), ("call", [lost]))) == {}   # a witness cannot precede the call it names
    (w,) = turn([W("j.txt", "J\n", "w")])
    wo = start(w, tmp_path).communicate()[0]
    liar = ('{"v":1,"r":"%s","k":"landed","rep":{"pm":{"%s":["did_not_run",""]}}}\n' % (record(wo)["r"], record(zo)["rep"]["pm"].popitem()[0]))
    conflict = history(tmp_path, ("call", [lost]), ("call", [z]), ("reply", z, zo), ("call", [w]), ("reply", w, liar))
    assert "lost" not in denial.witnessed_completions(conflict) and "lost" not in denial.unlanded_call_ids(conflict)


def test_an_earlier_turns_slow_writer_is_waited_for_not_overwritten(tmp_path):
    """Turn 1 writes f=A but is still running (a slow filesystem step); its reply has not arrived. Turn 2 writes f=B. Without
    the marks the later write lands first and the slow one then overwrites it (A on disk, B in every later fact); with them the later
    write waits for the earlier one's mark and B is what remains, with no `late`."""
    results = {}
    for label, session in (("without a session", None), ("with marks", SESSION)):
        completionmarks._reset()
        path = tmp_path / label.replace(" ", "_")
        path.mkdir()
        (path / "f.txt").write_text("init\n")
        (x,) = lower([W("f.txt", "AAAA\n", "x")], session=session)
        slow_x = start(slow(x, 1.5), path)
        time.sleep(0.4)                                                 # x is inside its slow step, has not landed
        assert (path / "f.txt").read_text() == "init\n"
        (y,) = lower([W("f.txt", "BBBB\n", "y")], session=session)
        yo = start(y, path).communicate()[0]
        slow_x.communicate()
        results[label] = ((path / "f.txt").read_text(), record(yo).get("rep", {}).get("late"))
    assert results["without a session"][0] == "AAAA\n"                    # the defect: the earlier turn's writer lands LAST
    assert results["with marks"] == ("BBBB\n", None)


def test_a_writer_that_outlasts_the_bound_is_not_waited_for_forever_and_says_late(tmp_path):
    """The earlier turn's writer is still running when the bound passes: the later write runs anyway (never held forever), its
    record says `late`, and the loop reads that as an unestablished touch rather than the file's bytes."""
    (tmp_path / "f.txt").write_text("init\n")
    (x,) = turn([W("f.txt", "AAAA\n", "x")])
    slow_x = start(slow(x, 1.5), tmp_path)
    time.sleep(0.4)
    with mock.patch.object(writeproxy, "EDIT_SEQ_WAIT_SECONDS", 0.3):
        (y,) = turn([W("f.txt", "BBBB\n", "y")])
    yo = start(y, tmp_path).communicate()[0]
    slow_x.communicate()
    assert record(yo)["rep"]["late"] is True and record(yo)["k"] == "landed"
    assert record(yo)["rep"]["pm"], "the late record still reports what it saw of the unfinished writer"
    assert [e[2] for e in loop._file_events(history(tmp_path, ("call", [y]), ("reply", y, yo)))] == ["shell"]


def test_a_legitimate_revert_a_b_a_is_never_blocked_and_leaves_one_mark_per_unreleased_call(tmp_path):
    """A, then B, then A again, each a later turn whose predecessor's reply was lost: all three land on time, nothing waits, and the
    marks name three distinct invocations with their own digests (the revert is an ordinary landed write)."""
    (tmp_path / "f.txt").write_text("init\n")
    turns = [turn([W("f.txt", text, f"w{i}")])[0] for i, text in enumerate(["AAA\n", "BBB\n", "AAA\n"])]
    started = time.monotonic()
    outs = [start(tc, tmp_path).communicate()[0] for tc in turns]            # every reply is lost until the end
    assert time.monotonic() - started < completionmarks.OPEN_WAIT_SECONDS
    assert [record(o)["k"] for o in outs] == ["landed"] * 3 and not any("late" in record(o).get("rep", {}) for o in outs)
    assert (tmp_path / "f.txt").read_text() == "AAA\n"
    msgs = history(tmp_path, *[("call", [t]) for t in turns], ("reply", turns[2], outs[2]))
    assert denial.witnessed_completions(msgs) == {"w0": ("landed", sha("AAA\n")), "w1": ("landed", sha("BBB\n"))}


def test_the_marks_of_calls_whose_outcome_is_known_are_removed_by_the_next_program(tmp_path):
    """Learning an outcome (its reply, or a witness) releases the mark; the next program removes exactly those, and the one it leaves is its own."""
    (x,) = turn([W("f.txt", "A\n", "x")])
    xo = start(x, tmp_path).communicate()[0]
    assert len(marks(tmp_path)) == 1
    history(tmp_path, ("call", [x]), ("reply", x, xo))                          # the reply arrives: cria learns x's outcome
    (y,) = turn([W("g.txt", "G\n", "y")])
    yo = start(y, tmp_path).communicate()[0]
    assert len(marks(tmp_path)) == 1 and marks(tmp_path)[0].startswith("m-" + record(yo)["r"])


# --- forged and stale marks ---------------------------------------------------------------------------------------------------

READER = completionmarks.directory_program() + r'''
import sys
context=_cm_open(%r,time.monotonic()+2)
print(json.dumps(_cm_read(context,%r,%r)))
'''


def read_back(cwd, receipt, nonce, credential):
    done = subprocess.run([sys.executable, "-"], input=READER % (credential, receipt, nonce), cwd=str(cwd),
                          env={**harness_env(cwd)}, capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def forged_cases(tmp_path):
    """name -> (receipt, nonce used to read, mutate(directory, filename))"""
    def rewrite(**changes):
        def go(directory, name):
            path = os.path.join(directory, name)
            value = json.loads(open(path).read())
            value.update(changes)
            open(path, "w").write(json.dumps(value))
        return go

    def symlink(directory, name):
        path = os.path.join(directory, name)
        os.rename(path, path + ".real")
        os.symlink(path + ".real", path)

    def loose(directory, name):
        os.chmod(os.path.join(directory, name), 0o644)

    def hardlinked(directory, name):
        os.link(os.path.join(directory, name), os.path.join(directory, "other"))

    def garbage(directory, name):
        open(os.path.join(directory, name), "w").write("landed")

    return {"another credential": rewrite(c="0" * 24), "another receipt": rewrite(r="f" * 16), "another invocation's nonce": rewrite(n="stale"),
            "an unknown state": rewrite(k="running", h=""), "landed without a digest": rewrite(h=""), "did_not_run carrying a digest": rewrite(k="did_not_run"),
            "a symlink": symlink, "a loose mode": loose, "a second hard link": hardlinked, "not json": garbage}


@pytest.mark.parametrize("label", sorted(forged_cases(None)))
def test_a_forged_or_stale_mark_is_not_a_mark(tmp_path, label):
    """The reader accepts exactly what the writer made; each corruption of it - and a mark of an earlier attempt of the same call - reads as absent."""
    (tmp_path / "f.txt").write_text("init\n")
    (x,) = turn([W("f.txt", "A\n", "x")])
    out = start(x, tmp_path).communicate()[0]
    receipt = record(out)["r"]
    (name,) = marks(tmp_path)
    nonce = name.split("-", 2)[2]
    credential = completionmarks.credential(SESSION)
    assert read_back(tmp_path, receipt, nonce, credential) == ["landed", sha("A\n")]          # the control: the genuine mark reads
    forged_cases(tmp_path)[label](marks_dir(tmp_path), name)
    assert read_back(tmp_path, receipt, nonce, credential) is None


def test_a_mark_in_an_uncertified_directory_or_of_another_session_is_not_read(tmp_path):
    """A look-alike directory with no certificate never authorizes anything (a late opener times out), and another session's credential names another directory."""
    (tmp_path / "f.txt").write_text("init\n")
    (x,) = turn([W("f.txt", "A\n", "x")])
    out = start(x, tmp_path).communicate()[0]
    receipt, directory = record(out)["r"], marks_dir(tmp_path)
    nonce = marks(tmp_path)[0].split("-", 2)[2]
    os.unlink(os.path.join(directory, ".owner"))                                           # the certificate is gone: the directory is foreign now
    done = subprocess.run([sys.executable, "-"], input=READER % (completionmarks.credential(SESSION), receipt, nonce), cwd=str(tmp_path),
                          env=harness_env(tmp_path), capture_output=True, text=True, timeout=30)
    assert done.returncode != 0 and "PermissionError" in done.stderr
    assert marks(tmp_path) == [f"m-{receipt}-{nonce}"]                                      # and nothing was adopted, removed or rewritten
    assert completionmarks.credential(SESSION) != completionmarks.credential("another-session")


def test_a_program_that_ends_without_its_exit_handler_leaves_no_mark_and_is_a_witnessed_dead_writer(tmp_path):
    """The writer ends by itself WITHOUT running its exit handlers (`os._exit`, the same state a SIGKILL leaves): no mark. Its own start
    record and /proc say its process is gone, so a later program reports `dead` - a witnessed end with no final mark, never
    `did_not_run` (it is not proof the file is untouched). And with no session the lowered command carries nothing of this."""
    (tmp_path / "f.txt").write_text("init\n")
    (x,) = turn([W("f.txt", "A\n", "x")])
    dying = start(die_before(x, SLOW), tmp_path)
    dying.communicate()
    assert marks(tmp_path) == [] and (tmp_path / "f.txt").read_text() == "init\n"
    (y,) = turn([W("g.txt", "G\n", "y")])
    yo = start(y, tmp_path).communicate()[0]
    msgs = history(tmp_path, ("call", [x]), ("call", [y]), ("reply", y, yo))
    assert denial.witnessed_completions(msgs) == {"x": ("dead", "")} and denial.unlanded_call_ids(msgs) == set()
    assert denial.witnessed_completed_ids(msgs) == set()
    assert completionmarks.DIR_PREFIX not in command_of(lower([W("f.txt", "A\n", "z")])[0])


WRITER = completionmarks.directory_program() + r'''
context=_cm_open(%r,time.monotonic()+2)
_cm_write(context,'a'*16,'n1','landed','0'*64)
_cm_write(context,'a'*16,'n1','did_not_run','')
print(json.dumps(_cm_read(context,'a'*16,'n1')))
'''


def test_a_second_mark_for_one_invocation_never_replaces_the_first(tmp_path):
    """First mark wins: a duplicate writer (a re-run of the same composition) cannot change what an earlier, already-read mark said."""
    scratch = scratch_of(tmp_path)
    os.makedirs(scratch, exist_ok=True)
    done = subprocess.run([sys.executable, "-"], input=WRITER % completionmarks.credential(SESSION), cwd=str(tmp_path),
                          env=harness_env(tmp_path), capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == ["landed", "0" * 64]
    assert [n for n in os.listdir(marks_dir(tmp_path)) if n.startswith(".t-")] == []


BAD_PM = {
    "a receipt that is not 16 hex": {"XYZ": ["landed", "a" * 64]},
    "an unknown state": {"a" * 16: ["stopped", ""]},
    "landed without a digest": {"a" * 16: ["landed", ""]},
    "did_not_run with a digest": {"a" * 16: ["did_not_run", "a" * 64]},
    "a non-list entry": {"a" * 16: "landed"},
    "an empty map": {},
    "more than 64 calls": {format(i, "016x"): ["incomplete", ""] for i in range(65)},
}


@pytest.mark.parametrize("label", sorted(BAD_PM))
def test_a_malformed_completion_report_is_not_a_record(label):
    """The typed `pm` report is exactly {receipt: [state, digest]}; anything else makes the whole record unreadable (unknown, bytes kept)."""
    from cria import resultpacket
    good = '{"v":1,"r":"%s","k":"landed","rep":{"pm":%s}}\n'
    receipt = "0123456789abcdef"
    assert resultpacket.read_record(good % (receipt, json.dumps({"a" * 16: ["landed", "a" * 64], "b" * 16: ["incomplete", ""], "c" * 16: ["running", ""], "d" * 16: ["dead", ""]})), 0, receipt) is not None
    assert resultpacket.read_record(good % (receipt, json.dumps(BAD_PM[label])), 0, receipt) is None
