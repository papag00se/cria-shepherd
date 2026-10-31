"""The rumination steer names the checker's real finding only when that is observably still true.

"None of your edit/write tool calls has landed since that check, and a read covering line N was returned
to you" is a claim about the session. It is made only from cria's own bookkeeping, never from the disk.
ornith1.5_9b / Java B3 (capture 20261012T044734): 35 calls with no edit after a failing check, and the
steer still said "re-run the check" with the flagged source and the check both in the window.
"""
import json

import pytest

from cria import bodykeys, denial, loop
from loop_guards_helpers import Chat, Log, reply

REL = "src/main/java/pipeline/Importer.java"
ABS = "/w/" + REL
FLAG = ("[GROUND TRUTH — the repo's own checks fail] The failures:\n"
        f"$ mvn -q compile — {ABS}:203: cannot find symbol\n  • {ABS}:203: cannot find symbol")
LANDED = "Chunk ID: 1\nWall time: 0.0 seconds\nProcess exited with code 0\nOutput:\n"
FAILED = "Chunk ID: 2\nWall time: 0.0 seconds\nProcess exited with code 1\nOutput:\ncp: cannot stat 'x'\n"
DENIED = denial.mark("Process exited with code 1\nOutput:\nWriting outside the working directory is not permitted "
                     "here for this path: '/tmp/head.java' is outside the project directory (/w).")
REDIRECT = f"git show HEAD:{REL} > /tmp/head.java"


def call(cid, name, **args):
    return {"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {
        "name": name, "arguments": json.dumps(args)}}]}


def result(cid, text, outcome=None):
    return {"role": "tool", "tool_call_id": cid, "content": text, **({bodykeys.RESULT_OUTCOME: outcome} if outcome else {})}


def read(start=180, end=230, path=REL):
    return [call("r1", "read_file", path=path, start_line=start, end_line=end),
            result("r1", "\n".join(f"{i}: l{i}" for i in range(start, end + 1)))]


def sh(cid, cmd, text=LANDED, outcome=None):
    return [call(cid, "exec_command", cmd=cmd), result(cid, text, outcome)]


def session(msgs, flag=FLAG):
    """A session whose gate named Importer.java:203, each call in ``msgs`` forwarded after it through the
    real recorder, and the write registry then settled by observing the results in ``msgs``."""
    s = loop.PlanSession(plan=[])
    s.workspace_root = "/w"
    loop._record_dispatch(s, {"choices": [{"message": {"tool_calls": [
        {"id": "b0", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]}}]}, [])
    loop.track_gate_progress(s, flag, [])
    for i, m in enumerate(msgs):
        if m.get("tool_calls"):
            loop._record_dispatch(s, {"choices": [{"message": {"tool_calls": m["tool_calls"]}}]}, msgs[:i])
    loop._record_dispatch(s, {"choices": []}, msgs)
    return s


def step(msgs, flag=FLAG):
    return loop.grounded_rumination_step(session(msgs, flag), msgs)


GROUNDED = [
    ("read covers the line", read()),
    ("a read-only shell afterwards", read() + sh("s", f"grep -n foo {REL} | head -5")),
    # ornith1.5_9b / Java 1792961160: a refused redirect never ran, so it did not change the file
    ("a refused redirect afterwards", read() + sh("w1", REDIRECT, DENIED, denial.REFUSED)),
]
SILENT = [
    ("read window misses the line", read(1, 20)),
    ("an edit to another file since the check", read() + [call("w9", "write_file", path="other.txt", content="x"),
                                                           result("w9", LANDED)]),
    ("the read was of an unrelated file", read(path="src/main/java/pipeline/Unrelated.java")),
    ("a write to the path after the read", read() + [call("p", "apply_patch", input=f"*** Begin Patch\n*** Update File: o.java\n@@\n-a\n+b\n*** Update File: {REL}\n@@\n-a\n+b\n*** End Patch")]),
    ("a shell redirect to the path", read() + sh("s", f'echo hi > "{REL}"')),
    ("a shell write of unknown target", read() + sh("s", "git checkout -- .")),
    ("the same redirect that was NOT refused", read() + sh("w1", REDIRECT)),
    # a non-zero exit is a process failure, not "never ran": a shell may write before it fails
    ("a shell that failed but was not denied", read() + sh("w1", REDIRECT, FAILED)),
    ("a refusal without the proven hint", read() + sh("w1", REDIRECT, DENIED)),
    # id `w1` names two calls; which one the proven result answers is unknowable: withheld, never skipped
    ("a reused call id", read() + sh("w1", REDIRECT, DENIED, denial.REFUSED)
     + [call("w1", "write_file", path=REL, content="x"), result("w1", LANDED)]),
]


@pytest.mark.parametrize("name,msgs", GROUNDED, ids=[n for n, _ in GROUNDED])
def test_the_steer_quotes_the_checkers_own_line_when_nothing_could_have_changed_it(name, msgs):
    out = step(msgs)
    assert f"$ mvn -q compile — {ABS}:203: cannot find symbol" in out     # verbatim, never paraphrased
    assert f"`{REL}`" in out and "line 203" in out and "cria" not in out.lower()


@pytest.mark.parametrize("name,msgs", SILENT, ids=[n for n, _ in SILENT])
def test_the_steer_stays_silent_when_the_file_may_have_changed_or_was_never_shown(name, msgs):
    assert step(msgs) == ""


def test_no_grounded_step_without_a_file_line_or_with_a_green_check():
    assert step(read(1, 400), flag="[GROUND TRUTH] tests failed: 2 failed") == ""
    assert step(read(), flag="") == ""


@pytest.mark.parametrize("arm", ["second_guessing", "length"])
def test_the_aborted_turns_notice_swaps_only_the_clause_and_only_when_grounded(arm):
    """Same notice either way; the grounded text replaces the generic 'prefer reading' clause."""
    msgs = read()
    verdict = {"hits": 9, "reasoning_tokens": 8000, "arm": arm}

    def sent(gs, history):
        comp = reply("", finish="rumination")
        comp[bodykeys.RUMINATION] = verdict
        chat = Chat(reply("ok"))
        loop.guard_rumination(comp, {"messages": history, "tools": []}, chat, Log(), gs=gs)
        return chat.bodies[0]["messages"][-1]["content"]

    grounded = sent(session(msgs), msgs)
    assert "smallest grounded step is an edit" in grounded and f"{ABS}:203" in grounded
    for default in (sent(session(msgs), read(1, 3)), sent(None, msgs)):
        assert "smallest grounded step is an edit" not in default and "{{" not in default
        assert "Use the evidence already available" in default
