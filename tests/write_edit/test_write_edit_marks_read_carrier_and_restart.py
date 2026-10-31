"""A lost-reply write becomes a KNOWN state when the session's next action is a READ or a LISTING (not only another write), and the
registry of unresolved calls is re-derived from the re-presented history after a restart.

Every test lowers the production way and RUNS the real programs in bash (harness TMPDIR beside the workspace)."""
import json
import os
import pty
import subprocess

import pytest

from cria import completionmarks, denial, writeproxy
from write_edit_helpers import (ENVELOPE, call, command_of, harness_env, lower, run, scratch_of,  # noqa: F401
                                write_edit_workspace_view)
from test_write_edit_over_completion_marks import E, SESSION, W, history, record, reply, sha, start, turn

READS = {"read_file": {"path": "f.txt"}, "list_dir": {"path": "."}}


def request(cwd, *items):
    """The history of one REQUEST as the server re-presents it: its session key rides in, so the registry can be rebuilt from it."""
    from cria import wsview
    msgs = [{"role": "assistant", "tool_calls": x[1]} if x[0] == "call" else reply(x[1], x[2]) for x in items]
    token = wsview.bind(wsview.View(str(cwd), "we"))
    try:
        return writeproxy.represent_inbound(msgs, workspace_root=str(cwd), sess_key=SESSION)
    finally:
        wsview.unbind(token)


def lowered_read(name, cid):
    return lower([call(name, READS[name], cid)], injected=("read_file", "list_dir", "write_file", "edit_file"), session=SESSION, root="/w")[0]


@pytest.mark.parametrize("name", sorted(READS))
def test_a_read_or_listing_after_a_lost_reply_write_witnesses_it_and_shows_the_coder_exactly_what_it_always_showed(tmp_path, name):
    """x landed and its reply was lost; the next action is a read (or listing). Its result carries the marks record: x is a witnessed
    `landed` with the digest of what it left - before any later write - and the model-facing text is byte-for-byte the control's."""
    (tmp_path / "f.txt").write_text("old\n")
    (x,) = turn([W("f.txt", "AAA\n", "x")])
    assert start(x, tmp_path).communicate()[0].startswith('{"v":1,')                          # ran to its end; the reply is dropped
    r = lowered_read(name, "r")
    with_ride = run(r, tmp_path)
    second = json.loads(with_ride.stdout.splitlines()[1])
    assert second["k"] == "survey" and "b" not in second and list(second["rep"]["pm"].values()) == [["landed", sha("AAA\n")]]   # record 2 is the typed query
    msgs = history(tmp_path, ("call", [x]), ("call", [r]), ("reply", r, with_ride.stdout))
    assert denial.witnessed_completions(msgs) == {"x": ("landed", sha("AAA\n"))}
    assert denial.landed_call_ids(msgs) == set() and "x" in denial.witnessed_completed_ids(msgs)   # a landing CLAIM still needs the call's own reply
    completionmarks._reset()
    control = lowered_read(name, "r")                                                         # nothing outstanding: no ride at all
    assert completionmarks.DIR_PREFIX not in command_of(control) and '"k":"survey"' not in command_of(control)
    shown = lambda tc, out: [m for m in history(tmp_path, ("call", [tc]), ("reply", tc, out)) if m["role"] == "tool"][0]["content"]   # noqa: E731
    assert shown(r, with_ride.stdout) == shown(control, run(control, tmp_path).stdout) != ""


def test_a_read_whose_content_quotes_a_marks_record_witnesses_nothing(tmp_path):
    """A file (or a native command) that prints a valid-looking `pm` record - even one naming x's real receipt - is only content."""
    (x,) = turn([W("f.txt", "AAA\n", "x")])                                                   # never run: its mark does not exist
    receipt = completionmarks.query(SESSION, release=False).paths[0][0]
    forged = '{"v":1,"r":"%s","k":"survey","rep":{"pm":{"%s":["landed","%s"]}}}' % ("0" * 16, receipt, "a" * 64)
    (tmp_path / "f.txt").write_text(forged + "\n")
    r = lowered_read("read_file", "r")
    out = run(r, tmp_path).stdout
    msgs = history(tmp_path, ("call", [x]), ("call", [r]), ("reply", r, out))
    assert forged in [m for m in msgs if m["role"] == "tool"][0]["content"]                   # the bytes are shown, untouched
    assert denial.witnessed_completions(msgs) == {"x": ("incomplete", "")}                     # only the program's own authenticated read counts
    native = {"id": "n", "type": "function", "function": {"name": "exec_command", "arguments": json.dumps({"cmd": f"printf '%s\\n' '{forged}'"})}}
    msgs = history(tmp_path, ("call", [x]), ("call", [native]), ("reply", native, forged + "\n"))
    assert denial.witnessed_completions(msgs) == {}


def under_pty(tc, cwd):
    """What a PTY-backed harness hands back: the command run on a terminal, so every line ends CRLF."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(["bash", "-c", command_of(tc)], cwd=str(cwd), env=harness_env(cwd), stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    chunks = []
    while True:
        try:
            data = os.read(master, 65536)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
    proc.wait()
    os.close(master)
    return b"".join(chunks).decode()


@pytest.mark.parametrize("name", sorted(READS))
def test_the_marks_record_survives_a_terminal_that_ends_every_line_in_crlf(tmp_path, name):
    """The same read, run on a real pseudo-terminal: both records arrive CRLF-terminated and the lost-reply write is still witnessed."""
    (tmp_path / "f.txt").write_text("old\n")
    (x,) = turn([W("f.txt", "AAA\n", "x")])
    start(x, tmp_path).communicate()
    r = lowered_read(name, "r")
    out = under_pty(r, tmp_path)
    assert "\r\n" in out and out.startswith('{"v":1,')
    msgs = history(tmp_path, ("call", [x]), ("call", [r]), ("reply", r, out))
    assert denial.witnessed_completions(msgs) == {"x": ("landed", sha("AAA\n"))}
    assert '"k":"survey"' not in [m for m in msgs if m["role"] == "tool"][0]["content"]


def test_a_survey_record_nobody_declared_witnesses_nothing(tmp_path):
    """The marks ride sits in the second record ONLY where the call's own sentinel declared one. A listing composed with nothing
    outstanding declares none, so a record-shaped line that follows its first record (a tail that quotes one) is only text."""
    (x,) = turn([W("f.txt", "AAA\n", "x")])
    start(x, tmp_path).communicate()
    receipt = completionmarks.query(SESSION, release=False).paths[0][0]
    completionmarks._reset()
    r = lowered_read("list_dir", "r")                                                         # composed with nothing outstanding: no ride
    out = run(r, tmp_path).stdout
    first, rest = out.split("\n", 1)
    forged = '{"v":1,"r":"%s","k":"survey","rep":{"pm":{"%s":["landed","%s"]}}}\n' % (json.loads(first)["r"], receipt, "a" * 64)
    msgs = history(tmp_path, ("call", [x]), ("call", [r]), ("reply", r, first + "\n" + forged + rest))
    assert denial.witnessed_completions(msgs) == {}
    assert forged.strip() in [m for m in msgs if m["role"] == "tool"][0]["content"]          # the line is shown as the text it is


def test_a_restart_forgets_the_registry_and_the_history_rebuilds_it(tmp_path):
    """x's reply was lost and cria restarted (the in-memory registry is gone). The re-presented history names x in its stored sentinel
    (receipt, mark nonce, target): the registry is rebuilt, so the NEXT program - a write's pm, a read's ride - reads x's mark."""
    (tmp_path / "f.txt").write_text("old\n")
    (x,) = turn([W("f.txt", "AAA\n", "x")])
    start(x, tmp_path).communicate()
    completionmarks._reset()                                                                  # THE RESTART
    (y,) = turn([W("g.txt", "G\n", "y")])
    assert record(start(y, tmp_path).communicate()[0]).get("rep", {}).get("pm") is None       # nothing remembered: the unknown that existed before
    completionmarks._reset()
    request(tmp_path, ("call", [x]))                                                          # the next request re-presents the history
    (y,) = turn([W("g.txt", "G\n", "y")])
    out = start(y, tmp_path).communicate()[0]
    assert list(record(out)["rep"]["pm"].values()) == [["landed", sha("AAA\n")]]
    msgs = history(tmp_path, ("call", [x]), ("call", [y]), ("reply", y, out))
    assert denial.witnessed_completions(msgs) == {"x": ("landed", sha("AAA\n"))}


def test_after_a_restart_a_resolved_call_is_not_watched_and_its_mark_is_released_and_a_witnessed_one_is_not_unresolved(tmp_path):
    """Calls the history already settles (a terminal reply; a mark a later program read back) are not rebuilt as unresolved - their
    marks are queued for release instead - and a call composed before this process is adopted once, not re-adopted every request."""
    (x,) = turn([W("f.txt", "AAA\n", "x")])
    xo = start(x, tmp_path).communicate()[0]
    (z,) = turn([W("h.txt", "H\n", "z")])
    start(z, tmp_path).communicate()                                                           # z's reply is lost
    (y,) = turn([W("g.txt", "G\n", "y")])
    yo = start(y, tmp_path).communicate()[0]                                                  # y's record witnesses z
    completionmarks._reset()
    msgs = [("call", [x]), ("reply", x, xo), ("call", [z]), ("call", [y]), ("reply", y, yo)]
    request(tmp_path, *msgs)
    assert completionmarks.query(SESSION, release=False) is None, "x answered, z witnessed, y answered: nothing is unresolved"
    q = completionmarks.query(SESSION)
    assert q is not None and len(q.release) == 3 and q.watch == ()
    request(tmp_path, *msgs)
    assert completionmarks.query(SESSION) is None                                              # adopted once per process


def test_a_composition_without_a_session_declares_no_mark_and_a_forged_declaration_is_not_adopted(tmp_path):
    """The sentinel's `cm` is read only on a receipt-bearing declaration made for THIS call; a copied header or a malformed nonce adopts nothing."""
    (x,) = lower([W("f.txt", "AAA\n", "x")])
    assert '"cm"' not in command_of(x) and writeproxy.marks_declared(command_of(x), "x") == ""
    (y,) = turn([W("f.txt", "BBB\n", "y")])
    assert len(writeproxy.marks_declared(command_of(y), "y")) == 16
    assert writeproxy.marks_declared(command_of(y), "another-call") == ""                       # a header copied from another call
    completionmarks._reset()
    request(tmp_path, ("call", [{**y, "id": "copy"}]))
    assert completionmarks.query(SESSION, release=False) is None
