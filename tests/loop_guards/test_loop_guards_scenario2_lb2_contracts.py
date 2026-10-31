"""Contracts at the seams of the guards: a replaced repository-check owner may only hand back a well-formed Result, the repeat steer
counts only what cria itself refused, and a call's command text is decoded the same way whatever shape the harness sent."""
import pytest

from cria import loop, probegate, repositorychecks as rc

S = rc.Status
CALL = {"id": "c1", "type": "function", "function": {"name": "exec_command", "arguments": "{}"}}
PENDING = dict(status=S.PENDING, call=CALL, pending_kind=rc.PendingKind.CHECK)


@pytest.mark.parametrize("kwargs,consumed,allow_pending,why", [
    (dict(status="observed"), False, True, "Invalid repository check Result"),
    (dict(status=S.OBSERVED, text=5), False, True, "Invalid repository check Result"),
    (dict(status=S.OBSERVED, outcome=object()), False, True, "Invalid repository check Result"),
    (dict(status=S.OBSERVED, outcome=probegate.GateOutcome(ran=True, transport_pending=True)), False, True, "actual settled GateOutcome"),
    (dict(status=S.OBSERVED, outcome=probegate.GateOutcome(unran="x")), False, True, "actual settled GateOutcome"),
    (dict(status=S.OBSERVED, outcome=probegate.GateOutcome(transport_pending=True)), True, True, "actual settled GateOutcome"),
    (dict(PENDING), False, False, "cannot discard a pending call"),
    (dict(PENDING, call={"id": "", "type": "function"}), False, True, "requires an actual call and pending kind"),
    (dict(PENDING, pending_kind=None), False, True, "requires an actual call and pending kind"),
    (dict(status=S.SILENT, call=CALL), False, True, "cannot carry a call or pending kind"),
    (dict(status=S.SILENT, pending_kind=rc.PendingKind.PAGE), False, True, "cannot carry a call or pending kind"),
    (dict(status=S.SILENT), True, True, "requires an actual GateOutcome"),
])
def test_a_malformed_repository_check_result_is_refused_before_it_can_steer_anything(kwargs, consumed, allow_pending, why):
    with pytest.raises(ValueError, match=why):
        loop._repository_result(rc.Result(**kwargs), consumed=consumed, allow_pending=allow_pending)


def test_well_formed_results_pass_through_and_a_foreign_object_is_not_a_result():
    for ok in (rc.Result(**PENDING), rc.Result(S.SILENT, outcome=probegate.GateOutcome(ran=True))):
        assert loop._repository_result(ok, consumed=ok.status is S.SILENT) is ok
    with pytest.raises(ValueError, match="must return Result"):
        loop._repository_result({"status": S.SILENT})
    assert loop._repository_completion(rc.Result(S.SILENT)) is None
    assert loop._repository_completion(rc.Result(**PENDING)) is not None


@pytest.mark.parametrize("count,observed", [(0, "you are not getting a new outcome from these actions"), (1, "your last call was refused, so it did not run"),
                                            (3, "3 of your recent calls were refused, so none of them ran")])
def test_the_repeat_steer_says_only_the_number_of_refusals_cria_counted(count, observed):
    state = loop.GuardState()
    state.repeat_count, state.repeat_action = count, "read_file x"
    assert loop._repeat_observation(state) == {"observed": observed, "repeat_action": "read_file x"}


@pytest.mark.parametrize("args,command", [
    ('{"cmd": "ls -la", "justification": "why"}', "ls -la"), ('{"command": ["bash", "-lc", "pytest -q"]}', "bash -lc pytest -q"),
    ({"script": "make"}, "make"), ('{"justification": "only prose"}', ""), ("null", ""), ('["python", "-m", "x"]', "python -m x"),
    ('{"cmd": "tail -f', None), ('{\n "cmd": "x', None), ("[ -f x ] && echo y", "[ -f x ] && echo y"), (None, ""), (["a", ["b"]], "a b")])
def test_a_calls_command_text_is_decoded_alike_from_any_shape_and_a_cut_off_fragment_is_unknown(args, command):
    assert loop._command_text(args) == command
