"""A green tally must belong to the newest invocation of the carried check."""
import json

import pytest

from cria import loop, probegate
from test_checker_text_is_not_probe_ownership import pair


FINDING = "tests/test_required.py:44: AssertionError: required behavior"
CHECKS = "$ pytest -q\n" + FINDING
GREEN = "Process exited with code 0\nOutput:\n6 passed in 0.01s\n"
RED = "Process exited with code 1\nOutput:\n1 failed, 5 passed in 0.01s\n"


def gate(command="pytest -q"):
    return pair(probegate._gate_sentinel([command]) + "\n" + command,
                "___CRIA_GATE_probe-0___\n" + FINDING + "\nEXIT:1", "gate")


def superseded(later, checks=CHECKS):
    return loop._checks_superseded_by_coder_run(gate() + later, checks)


def test_a_saved_green_log_is_not_a_check_execution():
    messages = pair("ignored", GREEN)
    messages[0]["tool_calls"][0]["function"] = {
        "name": "read_file", "arguments": json.dumps({"path": "tmp/old-green.log"})}
    assert superseded(messages) == ""


@pytest.mark.parametrize("command", [
    "cat tmp/old-green.log", "pytest tests/test_other.py -q",
    "cd other-project && pytest -q", "pytest -q | tail -20",
    "printf '6 passed in 0.01s'", "pytest -q &", "echo pytest -q",
])
def test_an_unrelated_or_unattributable_run_cannot_clear_the_carried_check(command):
    assert superseded(pair(command, GREEN)) == ""


def test_the_newest_red_run_overrules_an_older_green_run():
    assert superseded(pair("pytest -q", GREEN, "green") + pair("pytest -q", RED, "red")) == ""


def test_a_newer_unknown_outcome_cannot_inherit_an_older_green():
    assert superseded(pair("pytest -q", GREEN, "green")
                      + pair("pytest -q", "Process exited with code 2\ninterrupted", "unknown")) == ""


def test_a_newer_pending_invocation_cannot_inherit_an_older_green():
    assert superseded(pair("pytest -q", GREEN, "green") + pair("pytest -q", "", "pending")[:1]) == ""


def test_results_arriving_out_of_order_do_not_make_the_older_invocation_newer():
    green, red = pair("pytest -q", GREEN, "green"), pair("pytest -q", RED, "red")
    assert superseded([green[0], red[0], red[1], green[1]]) == ""


def test_a_newer_green_same_scope_does_clear_the_old_red():
    assert superseded(pair("pytest -q", RED, "red") + pair("pytest -q", GREEN, "green")) == "0f/6p"


def test_unknown_carried_scope_is_silence_not_an_assumed_whole_suite():
    assert superseded(pair("pytest -q", GREEN), FINDING) == ""


def test_an_unpaired_tally_cannot_clear_anything():
    assert superseded([{"role": "tool", "tool_call_id": "missing", "content": GREEN}]) == ""


def test_all_carried_check_commands_need_newer_evidence():
    checks = "$ pytest -q\n" + FINDING + "\n$ pytest tests/test_extra.py -q\n" + FINDING
    assert superseded(pair("pytest -q", GREEN), checks) == ""
    assert superseded(pair("pytest -q", GREEN, "all")
                      + pair("pytest tests/test_extra.py -q", GREEN, "extra"), checks) == "0f/6p"


def test_a_nonzero_exit_cannot_be_overridden_by_a_green_tally():
    assert superseded(pair("pytest -q", GREEN.replace("code 0", "code 1"))) == ""


def test_no_gate_provenance_means_the_relative_age_is_unknown():
    assert loop._checks_superseded_by_coder_run(pair("pytest -q", GREEN), CHECKS) == ""


def test_an_explicit_other_workspace_is_not_the_same_check_scope():
    messages = pair("pytest -q", GREEN)
    messages[0]["tool_calls"][0]["function"]["arguments"] = json.dumps({
        "cmd": "pytest -q", "workdir": "/another/project"})
    assert superseded(messages) == ""


def test_a_later_narrow_failure_with_unknown_overlap_withdraws_the_old_green():
    assert superseded(pair("pytest -q", GREEN, "green")
                      + pair("pytest tests/test_required.py -q", RED, "red")) == ""


@pytest.mark.parametrize("later,cleared", [
    (pair("cat tmp/old-green.log", GREEN), False),
    (pair("pytest tests/test_other.py -q", GREEN), False),
    (pair("pytest -q", GREEN, "green") + pair("pytest -q", RED, "red"), False),
    (pair("pytest -q", GREEN), True),
])
def test_the_author_only_drops_the_carried_failure_for_verified_supersession(later, cleared):
    from test_loop import _Rlog

    def on_track(body, rlog):
        return json.dumps({"choices": [{"message": {"content": "ON_TRACK"}}]}).encode()

    guard = loop.GuardState()
    guard.steered_checks_text = CHECKS
    guard.same_checks_relooked = True
    rlog = _Rlog()
    loop.author_steer(on_track, None, None, guard,
                      {"messages": [{"role": "user", "content": "task"}] + gate() + later,
                       "tools": []}, rlog, condition="thrash", truth_text=CHECKS)
    events = [name for name, _ in rlog.events]
    assert ("loop.steer_checks_stale" in events) is cleared
    assert any(name in events for name in ("loop.steer_same_checks", "loop.steer_checks_reattached")) is (not cleared)
