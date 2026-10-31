"""The carried-check ledger: cria may only call a failure cleared (or re-run) on proof from the coder's own newer run."""

import json

import pytest

from cria import loop
from loop_rest_checks_fixture import CHECKS, FINDING, GREEN, RED, gate, pair, refused
from loop_rest_helpers import Rlog, loop_rest_local_view  # noqa: F401

WRITE = ("write_file", {"path": "tests/test_required.py", "content": "x = 1\n"})
OK0 = "Process exited with code 0\nOutput:\n"


def cases():
    green, red = pair("pytest -q", GREEN, "g"), pair("pytest -q", RED, "r")
    mut, mv = pair(None, "landed", "w", *WRITE), pair("mv a.py tests/test_required.py", OK0, "mv")
    return [
        ("newer green of the same scope", green, "0f/6p"),
        ("newest red overrules an older green", green + red, ""),
        ("a newer green clears the old red", red + green, "0f/6p"),
        ("results arriving out of order do not age the older call", [green[0], red[0], red[1], green[1]], ""),
        ("a saved green log is not an execution", pair("x", GREEN, "log", "read_file", {"path": "old.log"}), ""),
        ("another scope's run", pair("pytest tests/test_other.py -q", GREEN), ""),
        ("a piped run hides the exit status", pair("pytest -q | tail -20", GREEN), ""),
        ("a green tally under a nonzero exit", pair("pytest -q", GREEN.replace("code 0", "code 1")), ""),
        ("a write landed after the green may have broken it", green + mut, ""),
        ("a write whose result lands after the green", [mut[0]] + green + [mut[1]], ""),
        ("a write settled BEFORE the check", mut + green, "0f/6p"),
        ("a write still outstanding before the check", [mut[0]] + green, ""),
        ("a write cria refused never ran", green + refused(*WRITE), "0f/6p"),
        ("an overlapping uncertain shell mutation", [mv[0]] + green + [mv[1]], ""),
    ]


@pytest.mark.parametrize("label, later, expected", cases(), ids=[c[0] for c in cases()])
def test_a_green_run_supersedes_the_carried_failure_only_when_it_is_the_newest_proof(label, later, expected):
    """Each row is a distinct way a coder transcript could, or could not, prove the cached failure stale."""
    assert loop._checks_superseded_by_coder_run(gate() + later, CHECKS) == expected


def test_supersession_needs_provenance_scope_every_carried_command_and_a_runner_that_can_speak():
    """No gate in history = age unknown; unknown scope abstains; two carried commands need two greens; a pytest green says nothing of lint."""
    green = pair("pytest -q", GREEN)
    assert loop._checks_superseded_by_coder_run(green, CHECKS) == ""
    assert loop._checks_superseded_by_coder_run(gate() + green, FINDING) == ""
    two = "$ pytest -q\n" + FINDING + "\n$ pytest tests/test_extra.py -q\n" + FINDING
    assert loop._checks_superseded_by_coder_run(gate() + green, two) == ""
    assert loop._checks_superseded_by_coder_run(gate() + pair("pytest tests/test_extra.py -q", GREEN, "x"), two) == ""
    assert loop._checks_superseded_by_coder_run(gate() + green + pair("pytest tests/test_extra.py -q", GREEN, "x"), two) == "0f/6p"
    lint = "$ pytest -q\nresolve_handle.py:15:1: 'typing.Optional' imported but unused"
    assert loop._checks_superseded_by_coder_run(gate() + green, lint) == ""
    said = gate() + [{"role": "assistant", "content": "I ran them and 6 passed in 0.01s"}]
    assert loop._checks_superseded_by_coder_run(said, CHECKS) == ""


@pytest.mark.parametrize("later, cleared", [(pair("pytest -q", GREEN), True), (pair("pytest -q", RED), False)])
def test_the_author_drops_the_you_have_not_cleared_them_repeat_only_on_verified_supersession(later, cleared):
    """1786053138 call 0142 repeated 'you have not cleared them' four calls after the coder's own pytest passed."""
    reasoner = lambda b, r: json.dumps({"choices": [{"message": {"content": "ON_TRACK"}}]}).encode()  # noqa: E731
    guard = loop.GuardState()
    guard.steered_checks_text, guard.same_checks_relooked = CHECKS, True
    rlog = Rlog()
    loop.author_steer(reasoner, None, None, guard, {"messages": [{"role": "user", "content": "t"}] + gate() + later, "tools": []},
                      rlog, condition="thrash", truth_text=CHECKS)
    assert ("loop.steer_checks_stale" in rlog.kinds()) is cleared
    assert any(k in rlog.kinds() for k in ("loop.steer_same_checks", "loop.steer_checks_reattached")) is (not cleared)


class Sess:
    """The session fields the ledger reads: gate flag/seq and the action clock."""

    def __init__(self):
        self.action_seq, self.last_gate_seq = 7, 5
        self.last_gate_flag = "$ mvn test — Importer.java:1: package com.opencsv does not exist"


def own_run(cmd, out=OK0):
    s = Sess()
    loop._track_own_checks(s, pair(cmd, out, "t"))
    return loop.newer_own_run(s)


def test_a_newer_run_of_the_gates_command_is_named_and_its_exit_stated_only_when_it_is_the_checks():
    """phi4 / feed-pipeline-java A4: the carried block copied a superseded failure; a filter's exit status is not Maven's."""
    for cmd, out, exit_stated in [("mvn test", OK0, True), ("cd x && mvn test", OK0, True), ("mvn test && echo done", OK0, False),
                                  ("mvn test 2>&1 | tail -30", OK0 + "[ERROR] type error\n", False), ("mvn test", "BUILD SUCCESS", False)]:
        note = own_run(cmd, out)
        assert "`mvn test`" in note and ("exited with code 0" in note) is exit_stated, cmd
    issued = own_run("false && mvn test", "Process exited with code 1\nOutput:\nsetup failed\n")   # may not have started
    assert "issued `mvn test`" in issued and "does not establish that a check actually ran or passed" in issued


def test_text_that_merely_mentions_the_check_is_not_a_rerun():
    """Quoted, saved, array-body or wrapper-consumed text is not an invocation of the gate's command."""
    for cmd in ("ls -la", 'printf "%s\\n" "notes;mvn test;done"', "cat > tmp/s <<'END'\nmvn test\nEND\n",
                "args=(mvn test)", "env -u mvn test", "mvn test 2 > output.log"):
        assert own_run(cmd) == "", cmd


def test_a_run_before_the_gate_is_not_newer_even_when_the_same_history_is_seen_again():
    """Each run is folded once, stamped with its clock: the old run never becomes newer information."""
    old = Sess()
    old.action_seq, old.last_gate_seq = 4, 0
    for _ in range(2):
        loop._track_own_checks(old, pair("mvn test", "Process exited with code 1", "old"))
        old.last_gate_seq, old.action_seq = 4, 6
    assert loop.newer_own_run(old) == ""
