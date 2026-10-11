"""The carried `LATEST CHECK RESULTS` block says when the coder has RE-RUN its checks since.

phi4 / feed-pipeline-java A4 CALLs 0092/0104/0230: the block carried `package com.opencsv does not
exist` after the coder's own `mvn -q compile` had shown three different errors, then BUILD SUCCESS. It
was stamped "gathered N calls ago", but nothing said a NEWER run of the very same command existed, and
that run's output had been compacted away — so the briefing writer and the orient step copied the
superseded failure as the present state (#5b). cria now remembers the coder's own re-runs of the
gate's commands and names the newest one."""
import json

from cria import loop, server

FLAG = ("[GROUND TRUTH — the repo's own checks fail] ...\n"
        "$ mvn -q compile — Importer.java:1: package com.opencsv does not exist\n"
        "$ mvn test — Importer.java:1: package com.opencsv does not exist")


class _Sess:
    def __init__(self):
        self.action_seq = 5
        self.last_gate_seq = 5
        self.last_gate_flag = FLAG


class _Store:
    def __init__(self, s):
        self.s = s

    def get(self, k):
        return self.s


class _Loop:
    def __init__(self, s):
        self._store = _Store(s)


class _Server:
    def __init__(self, s):
        self.loop = _Loop(s)


def _run(tid, cmd, out):
    return [{"role": "assistant", "tool_calls": [{"id": tid, "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"cmd": cmd})}}]},
            {"role": "tool", "tool_call_id": tid, "content": out}]


def test_a_later_own_run_of_the_gates_command_is_named_in_the_note():
    s = _Sess()
    s.action_seq = 7
    loop._track_own_checks(s, _run("t1", "mvn -q compile\nmvn test", "Process exited with code 0\nOutput:\n"))
    s.action_seq = 8
    note = server._last_checks_note(_Server(s), "k")
    assert "`mvn -q compile`" in note and "`mvn test`" in note
    assert "NEWER than this block" in note and "exited with code 0" in note
    assert "1 of your calls ago" in note


def test_each_run_is_folded_once_and_a_run_from_before_the_gate_is_not_newer():
    s = _Sess()
    s.action_seq = 4
    s.last_gate_seq = 0
    loop._track_own_checks(s, _run("old", "mvn test", "Process exited with code 1"))
    s.last_gate_seq = 4
    s.action_seq = 6
    loop._track_own_checks(s, _run("old", "mvn test", "Process exited with code 1"))   # same history re-seen
    assert loop.newer_own_run(s) == ""


def test_cria_own_replay_and_an_unrelated_command_are_not_the_coders_rerun():
    s = _Sess()
    s.action_seq = 7
    loop._track_own_checks(s, _run("r", "mvn -q compile", "⟦ctx:checks⟧ the repo's own checks report"))
    loop._track_own_checks(s, _run("x", "ls -la", "total 0"))
    assert loop.newer_own_run(s) == ""


def test_no_exit_code_in_the_result_says_no_exit_code():
    s = _Sess()
    s.action_seq = 7
    loop._track_own_checks(s, _run("t", "mvn test", "BUILD SUCCESS"))
    out = loop.newer_own_run(s)
    assert "`mvn test`" in out and "exited with code" not in out
