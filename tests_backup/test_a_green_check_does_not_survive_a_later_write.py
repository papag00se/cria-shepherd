"""Supersession needs a check after mutations settle, not merely after the gate."""
import json

import pytest

from cria import bodykeys, denial, loop, proberun
from cria.probeparse import Finding, ProbeResult
from test_checker_text_is_not_probe_ownership import pair
from test_only_a_newer_run_of_the_same_check_clears_it import CHECKS, GREEN, gate
from test_loop import _Rlog


def native_call(name, arguments, result="landed", call_id="native-mutation", outcome=None):
    """``outcome`` is the PROVEN hint `represent_inbound` attaches to cria's own refusal; wording proves nothing."""
    messages = [
        {"role": "assistant", "tool_calls": [{"id": call_id, "type": "function",
         "function": {"name": name, "arguments": json.dumps(arguments)}}]},
    ]
    if result is not None:
        messages.append({"role": "tool", "tool_call_id": call_id, "content": result,
                         **({bodykeys.RESULT_OUTCOME: outcome} if outcome else {})})
    return messages


def assert_supersession(later, cleared, checks=CHECKS, before_gate=()):
    messages = [{"role": "user", "content": "Fix the required test"}] + list(before_gate) + gate() + later
    superseded = bool(loop._checks_superseded_by_coder_run(messages, checks))

    def on_track(body, rlog):
        return json.dumps({"choices": [{"message": {"content": "ON_TRACK"}}]}).encode()

    guard = loop.GuardState()
    guard.steered_checks_text = checks
    guard.same_checks_relooked = True
    rlog = _Rlog()
    loop.author_steer(on_track, None, None, guard, {"messages": messages, "tools": []}, rlog,
                      condition="thrash", truth_text=checks)
    events = [name for name, _ in rlog.events]
    assert ("loop.steer_checks_stale" in events) is cleared
    assert any(name in events for name in ("loop.steer_same_checks", "loop.steer_checks_reattached")) is (not cleared)
    assert superseded is cleared


MUTATIONS = [
    ("write_file", {"path": "tests/test_required.py", "content": "def test_required(): assert False\n"}),
    ("edit_file", {"path": "tests/test_required.py", "old_string": "assert True", "new_string": "assert False"}),
]


@pytest.mark.parametrize("name,args", MUTATIONS)
@pytest.mark.parametrize("result", ["landed", None], ids=["confirmed", "pending"])
def test_newer_native_mutation_withdraws_the_green_in_the_production_author(name, args, result):
    assert_supersession(pair("pytest -q", GREEN) + native_call(name, args, result), False)


@pytest.mark.parametrize("name,args", MUTATIONS)
def test_a_check_after_a_settled_mutation_can_supersede_again(name, args):
    assert_supersession(native_call(name, args) + pair("pytest -q", GREEN), True)


@pytest.mark.parametrize("name,args", MUTATIONS)
def test_an_outstanding_earlier_write_can_still_land_after_the_green(name, args):
    assert_supersession(native_call(name, args, None) + pair("pytest -q", GREEN), False)


@pytest.mark.parametrize("name,args", MUTATIONS)
def test_a_late_mutation_result_does_not_leave_the_overlapping_check_green(name, args):
    mutation = native_call(name, args)
    assert_supersession([mutation[0]] + pair("pytest -q", GREEN) + [mutation[1]], False)


@pytest.mark.parametrize("name,args", MUTATIONS)
def test_a_producer_refused_mutation_does_not_invalidate_the_green(name, args):
    assert_supersession(pair("pytest -q", GREEN)
                        + native_call(name, args, denial.mark("This call did not run"), outcome=denial.REFUSED), True)


@pytest.mark.parametrize("name,args", MUTATIONS)
@pytest.mark.parametrize("settled", [False, True], ids=["still-pending", "late-result"])
def test_an_outstanding_write_from_before_the_gate_still_blocks_supersession(name, args, settled):
    mutation = native_call(name, args)
    after = pair("pytest -q", GREEN) + ([mutation[1]] if settled else [])
    assert_supersession(after, False, before_gate=[mutation[0]])


@pytest.mark.parametrize("name,args", MUTATIONS)
def test_a_mutation_settled_before_the_gate_does_not_block_a_later_green(name, args):
    assert_supersession(pair("pytest -q", GREEN), True, before_gate=native_call(name, args))


def test_a_nonmutating_native_read_does_not_invalidate_the_green():
    assert_supersession(pair("pytest -q", GREEN) + native_call(
        "read_file", {"path": "tests/test_required.py"}, "def test_required(): assert True\n"), True)


@pytest.mark.parametrize("settled", [False, True], ids=["still-pending", "late-result"])
def test_an_overlapping_uncertain_shell_withdraws_the_green(settled):
    mutation = pair("mv tests/replacement.py tests/test_required.py",
                    "Process exited with code 0\nOutput:\n", "shell-mutation")
    messages = [mutation[0]] + pair("pytest -q", GREEN) + ([mutation[1]] if settled else [])
    assert_supersession(messages, False)


def test_an_uncertain_shell_settled_before_the_check_allows_a_new_green():
    mutation = pair("mv tests/replacement.py tests/test_required.py",
                    "Process exited with code 0\nOutput:\n", "shell-mutation")
    assert_supersession(mutation + pair("pytest -q", GREEN), True)


def test_duplicate_rendered_command_heads_do_not_prove_both_scopes_were_checked():
    # The real renderer carries display commands and findings, not a scope identity on each head.
    # Two observations can therefore have the same head: one coder receipt cannot cover both.
    report = proberun.ProbeReport(results=[
        ProbeResult(command="pytest -q", exit_code=1, summary="1 failed", findings=[
            Finding(file=scope + "/tests/test_required.py", line=44, message="AssertionError")])
        for scope in ("scope-a", "scope-b")
    ])
    checks = proberun.block_findings(report)
    assert loop._gate_commands(checks) == ["pytest -q", "pytest -q"]
    assert_supersession(pair("pytest -q", GREEN), False, checks)
