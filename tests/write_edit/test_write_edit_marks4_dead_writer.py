"""A writer that is dead and one that is merely slow are told apart WITHOUT any signal: the program records its own pid and process start
time when it starts, and a reader decides liveness from /proc. Alive means running (wait); gone with no final mark means `dead` - a
witnessed end that is NOT proof the write did not land. A forged, stale or recycled-pid start record is never believed.

Every writer here is the real lowered program run in bash. Deaths are self-inflicted (`os._exit` skips the exit handlers, which is
exactly what a SIGKILL leaves; `sys.exit` and an uncaught error run them). The only process a test ever stops is one it started."""
import json
import os
import subprocess
import sys
import time
from unittest import mock

import pytest

from cria import completionmarks, denial, writeproxy
from test_write_edit_marks_read_carrier_and_restart import lowered_read, under_pty
from test_write_edit_over_completion_marks import SESSION, W, die_before, history, marks_dir, record, reply, sha, slow, start, turn
from write_edit_helpers import command_of, harness_env, run, scratch_of, write_edit_workspace_view  # noqa: F401

SLOW = "rp.parent.mkdir(parents=True,exist_ok=True)"
LANDED = "sys.stdout.write(_rec('landed'"


def pm_of(cwd, name="read_file"):
    """What a lowered read says right now about every outstanding writer (its record 2): {receipt: [state, digest]}."""
    r = lowered_read(name, "r")
    return json.loads(run(r, cwd).stdout.splitlines()[1])["rep"]["pm"]


def states(cwd):
    return sorted(state for state, _digest in pm_of(cwd).values())


def test_a_running_writer_is_running_and_the_same_writer_finished_is_its_mark(tmp_path):
    """x is inside a slow step: its start record says its process is alive -> `running`. After it exits normally its mark outranks that."""
    (tmp_path / "f.txt").write_text("old\n")
    (x,) = turn([W("f.txt", "AAA\n", "x")])
    proc = start(slow(x, 2.0), tmp_path)
    time.sleep(0.6)
    assert states(tmp_path) == ["running"]
    proc.communicate()
    assert list(pm_of(tmp_path).values()) == [["landed", sha("AAA\n")]]


@pytest.mark.parametrize("dies_at, on_disk", [(SLOW, "old\n"), (LANDED, "AAA\n")], ids=["before-landing", "after-landing"])
def test_a_writer_that_dies_without_its_handlers_is_dead_and_that_is_not_proof_it_did_not_land(tmp_path, dies_at, on_disk):
    """The program ends before (or just after) it lands its bytes, with no exit handler: no final mark either way. `dead` is all that is
    witnessed - the file may or may not hold the bytes - so it is not a proven unlanded call, and it is not claimed finished."""
    (tmp_path / "f.txt").write_text("old\n")
    (x,) = turn([W("f.txt", "AAA\n", "x")])
    start(die_before(x, dies_at), tmp_path).communicate()
    assert (tmp_path / "f.txt").read_text() == on_disk and marks_names(tmp_path) == []
    r = lowered_read("read_file", "r")
    out = run(r, tmp_path).stdout
    msgs = history(tmp_path, ("call", [x]), ("call", [r]), ("reply", r, out))
    assert denial.witnessed_completions(msgs) == {"x": ("dead", "")}
    assert denial.unlanded_call_ids(msgs) == set() and denial.landed_call_ids(msgs) == set() == denial.witnessed_completed_ids(msgs)


def marks_names(cwd):
    return sorted(n for n in os.listdir(marks_dir(cwd)) if n.startswith("m-"))


@pytest.mark.parametrize("statement, final", [("sys.exit(1)", "did_not_run"), ("1/0", "uncertain")], ids=["self-inflicted-exit-1", "uncaught-error"])
def test_a_writer_that_exits_by_itself_runs_its_handlers_and_leaves_a_final_mark_not_a_dead_state(tmp_path, statement, final):
    """`exit 1` and an uncaught error run the exit handlers: the mark says what the program knew, and a mark outranks the dead verdict."""
    (tmp_path / "f.txt").write_text("old\n")
    (x,) = turn([W("f.txt", "AAA\n", "x")])
    start(with_statement(x, statement), tmp_path).communicate()
    assert states(tmp_path) == [final]


def with_statement(tc, statement):
    args = json.loads(tc["function"]["arguments"])
    assert SLOW in args["cmd"]
    return {**tc, "function": {**tc["function"], "arguments": json.dumps({**args, "cmd": args["cmd"].replace(SLOW, f"{statement};{SLOW}", 1)})}}


def test_a_writer_that_never_started_is_incomplete_not_dead(tmp_path):
    """No start record means nobody can say (never started, or not yet): `incomplete`. Only a record of a process that was alive makes `dead`."""
    (y,) = turn([W("g.txt", "G\n", "y")])
    start(y, tmp_path).communicate()                                      # opens the directory; y leaves a mark
    (never,) = turn([W("h.txt", "H\n", "never")])
    assert states(tmp_path) == ["incomplete", "landed"]


def test_a_dead_writer_is_reported_through_a_terminal_too(tmp_path):
    """The same facts on a real pseudo-terminal (every line CRLF): the writer dies under it, the read run on it reports `dead`."""
    (tmp_path / "f.txt").write_text("old\n")
    (x,) = turn([W("f.txt", "AAA\n", "x")])
    under_pty(die_before(x, SLOW), tmp_path)
    r = lowered_read("read_file", "r")
    out = under_pty(r, tmp_path)
    assert "\r\n" in out
    msgs = history(tmp_path, ("call", [x]), ("call", [r]), ("reply", r, out))
    assert denial.witnessed_completions(msgs) == {"x": ("dead", "")}


def test_a_later_write_does_not_wait_the_bound_for_a_dead_predecessor_and_is_not_late(tmp_path):
    """An earlier turn's writer of the same file is dead. The later write used to wait the whole bound for a mark that can never come
    and then run `late`; it now sees the process is gone, runs at once, and its bytes are the file's (nothing can land after it)."""
    (tmp_path / "f.txt").write_text("old\n")
    (x,) = turn([W("f.txt", "AAAA\n", "x")])
    start(die_before(x, SLOW), tmp_path).communicate()
    with mock.patch.object(writeproxy, "EDIT_SEQ_WAIT_SECONDS", 25):
        (y,) = turn([W("f.txt", "BBBB\n", "y")])
    began = time.monotonic()
    out = start(y, tmp_path).communicate()[0]
    assert time.monotonic() - began < 10
    assert record(out)["k"] == "landed" and "late" not in record(out).get("rep", {})
    assert (tmp_path / "f.txt").read_text() == "BBBB\n"
    assert list(record(out)["rep"]["pm"].values()) == [["dead", ""]]


# --- forged, stale and recycled start records ------------------------------------------------------------------------------------

READER = completionmarks.directory_program() + r'''
import sys
context=_cm_open(%%CREDENTIAL%%,time.monotonic()+2)
print(json.dumps([_cm_liveness(context,%%RECEIPT%%,%%NONCE%%),_cm_state(context,%%RECEIPT%%,%%NONCE%%)]))
'''


def read_back(cwd, receipt, nonce):
    program = (READER.replace("%%CREDENTIAL%%", repr(completionmarks.credential(SESSION))).replace("%%RECEIPT%%", repr(receipt))
               .replace("%%NONCE%%", repr(nonce)))
    done = subprocess.run([sys.executable, "-"], input=program, cwd=str(cwd), env=harness_env(cwd), capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def ticks_of(pid):
    """The process's start time as /proc says it, parsed independently of the program under test (field 22 after the command name)."""
    return int(open(f"/proc/{pid}/stat").read().rpartition(")")[2].split()[19])


def start_record(cwd, receipt, nonce, pid, ticks, **changes):
    """Write a start record by hand into the session's certified directory (what a writer's program would have left)."""
    value = dict(c=completionmarks.credential(SESSION), r=receipt, n=nonce, p=pid, t=ticks,
                 b=open("/proc/sys/kernel/random/boot_id").read().strip(), s=os.readlink("/proc/self/ns/pid"))
    value.update(changes)
    path = os.path.join(marks_dir(cwd), f"s-{receipt}-{nonce}")
    if os.path.lexists(path):
        os.unlink(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(json.dumps(value))
    return path


@pytest.fixture
def certified(tmp_path):
    """A workspace whose session already has a certified marks directory (a genuine writer made it)."""
    (y,) = turn([W("g.txt", "G\n", "y")])
    start(y, tmp_path).communicate()
    return tmp_path


RECEIPT, NONCE = "ab" * 8, "n1"


@pytest.fixture
def child():
    """A process of the test's own that lives until its stdin is closed and then ends BY ITSELF (no signal is ever sent)."""
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE)
    yield proc
    if proc.stdin and not proc.stdin.closed:
        proc.stdin.close()
    proc.wait(timeout=10)


def finish(proc):
    """Let the child end by itself and reap it: its pid is then free for reuse."""
    proc.stdin.close()
    proc.wait(timeout=10)


def test_a_recycled_pid_is_not_mistaken_for_the_writer_and_a_real_one_is_running(certified, child):
    """A start record names a real process of the test's own. With its true start time the process is `running`; with any other start
    time the pid belongs to someone else now, so the writer is `dead`. Once the process has really ended it is `dead`."""
    true = ticks_of(child.pid)
    start_record(certified, RECEIPT, NONCE, child.pid, true)
    assert read_back(certified, RECEIPT, NONCE) == ["running", ["running", ""]]
    start_record(certified, RECEIPT, NONCE, child.pid, true - 1)
    assert read_back(certified, RECEIPT, NONCE) == ["dead", ["dead", ""]]
    start_record(certified, RECEIPT, NONCE, child.pid, true)
    finish(child)
    assert read_back(certified, RECEIPT, NONCE) == ["dead", ["dead", ""]]


def test_an_ended_but_unreaped_writer_is_dead(certified):
    """A process that has exited and not yet been reaped is a zombie: its pid still exists, its program is over."""
    zombie = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and open(f"/proc/{zombie.pid}/stat").read().rpartition(")")[2].split()[0] != "Z":
            time.sleep(0.05)
        start_record(certified, RECEIPT, NONCE, zombie.pid, ticks_of(zombie.pid))
        assert read_back(certified, RECEIPT, NONCE)[0] == "dead"
    finally:
        zombie.wait(timeout=10)


FORGED = {
    "another credential": dict(c="0" * 24),
    "another receipt": dict(r="f" * 16),
    "another invocation's nonce": dict(n="stale"),
    "another boot": dict(b="00000000-0000-0000-0000-000000000000"),
    "another pid namespace": dict(s="pid:[1]"),
    "pid 1": dict(p=1),
    "pid 0": dict(p=0),
    "a negative pid": dict(p=-5),
    "a string pid": dict(p="123"),
    "a boolean pid": dict(p=True),
    "no start time": dict(t=None),
    "a negative start time": dict(t=-1),
}


@pytest.mark.parametrize("label", sorted(FORGED))
def test_a_forged_start_record_never_makes_a_writer_dead(certified, child, label):
    """Each corruption of a genuine record reads as 'cannot say' (`incomplete`): never a `dead` claim, and never a `running` one."""
    true = ticks_of(child.pid)
    start_record(certified, RECEIPT, NONCE, child.pid, true)
    assert read_back(certified, RECEIPT, NONCE)[0] == "running"                     # the control: the genuine record reads
    start_record(certified, RECEIPT, NONCE, child.pid, true, **FORGED[label])
    assert read_back(certified, RECEIPT, NONCE) == [None, ["incomplete", ""]]


@pytest.mark.parametrize("how", ["a symlink", "a loose mode", "a second hard link", "not json", "bigger than the bound"])
def test_a_start_record_that_is_not_a_private_regular_file_is_not_read(certified, child, how):
    path = start_record(certified, RECEIPT, NONCE, child.pid, ticks_of(child.pid))
    if how == "a symlink":
        os.rename(path, path + ".real")
        os.symlink(path + ".real", path)
    elif how == "a loose mode":
        os.chmod(path, 0o644)
    elif how == "a second hard link":
        os.link(path, path + ".other")
    elif how == "not json":
        open(path, "w").write("running")
    else:
        open(path, "w").write(" " * 5000)
    assert read_back(certified, RECEIPT, NONCE) == [None, ["incomplete", ""]]


def test_a_final_mark_outranks_a_dead_start_record_and_both_files_are_released_once_the_outcome_is_known(tmp_path):
    """A writer that finished has both files and its process is gone: its mark wins (never `dead`). Once cria has learned its outcome
    the next program removes BOTH files, and only that call's."""
    (x,) = turn([W("f.txt", "A\n", "x")])
    xo = start(x, tmp_path).communicate()[0]
    names = lambda: sorted(n for n in os.listdir(marks_dir(tmp_path)) if n[0] in "ms")   # noqa: E731
    assert [n[:2] for n in names()] == ["m-", "s-"]
    nonce = names()[0].split("-", 2)[2]
    assert read_back(tmp_path, record(xo)["r"], nonce) == ["dead", ["landed", sha("A\n")]]      # liveness alone says dead; the mark outranks it
    history(tmp_path, ("call", [x]), ("reply", x, xo))
    (y,) = turn([W("g.txt", "G\n", "y")])
    yo = start(y, tmp_path).communicate()[0]
    assert [n[:2] for n in names()] == ["m-", "s-"] and all(record(yo)["r"] in n for n in names())


def test_a_dead_report_does_not_settle_the_call_so_the_gate_keeps_asking_about_it(tmp_path):
    """A read reports x `dead`: that is a witnessed end with no final mark, not a learned outcome. x stays outstanding (the gate will hold and
    say so); a final mark (`landed`) in the same position DOES settle it."""
    (x,) = turn([W("f.txt", "AAA\n", "x")])
    start(die_before(x, SLOW), tmp_path).communicate()
    r = lowered_read("read_file", "r")
    out = run(r, tmp_path).stdout
    history(tmp_path, ("call", [x]), ("call", [r]), ("reply", r, out))
    assert json.loads(out.splitlines()[1])["rep"]["pm"].popitem()[1] == ["dead", ""]
    query = completionmarks.query(SESSION, release=False)
    assert query is not None and len(query.watch) == 1 and query.release == ()
    (z,) = turn([W("g.txt", "G\n", "z")])
    start(z, tmp_path).communicate()
    r2 = lowered_read("read_file", "r2")
    out2 = run(r2, tmp_path).stdout
    history(tmp_path, ("call", [x]), ("call", [z]), ("call", [r2]), ("reply", r2, out2))
    assert len(completionmarks.query(SESSION, release=False).watch) == 1 and sorted(s for s, _d in json.loads(out2.splitlines()[1])["rep"]["pm"].values()) == ["dead", "landed"]


LOOK_THEN_FINISH = READER.replace("print(json.dumps([", """_looks=[0]
_real=_cm_read
def _cm_read(context,receipt,nonce):
    # The writer finishes between the first look at its mark and the look at its process: the FIRST look sees no mark yet.
    _looks[0]+=1
    return None if _looks[0]==1 else _real(context,receipt,nonce)
print(json.dumps([""")


def test_a_writer_that_finishes_between_the_two_looks_is_its_mark_not_dead(tmp_path):
    """The mark is looked at, then the process: a writer that exits (mark written, process gone) in between must not be reported dead.
    The reader looks at the mark again after a dead verdict; here the first look is made to miss a genuinely finished writer."""
    (x,) = turn([W("f.txt", "A\n", "x")])
    xo = start(x, tmp_path).communicate()[0]
    nonce = next(n for n in os.listdir(marks_dir(tmp_path)) if n.startswith("m-")).split("-", 2)[2]
    program = (LOOK_THEN_FINISH.replace("%%CREDENTIAL%%", repr(completionmarks.credential(SESSION))).replace("%%RECEIPT%%", repr(record(xo)["r"]))
               .replace("%%NONCE%%", repr(nonce)))
    done = subprocess.run([sys.executable, "-"], input=program, cwd=str(tmp_path), env=harness_env(tmp_path), capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == ["dead", ["landed", sha("A\n")]]
