"""A gate's evidence is believed only when it arrived whole: a gate that is not done is pending, one that did not deliver is UNKNOWN, and neither is ever read as a pass.

(The paging, hashing, polling and lost-reply behaviours of the operation that carries the evidence are tests of the operation: tests/harness_primitives/test_gate_ops.py.)"""
import time

from cria import gateops, probegate
from gates_completion_helpers import gates_completion_view, new_plan, real_gate, sec, result_of  # noqa: F401  (autouse fixture)

RAW = sec(0, "x" * 70 + "\nsrc/a.py:9: boom", 1) + sec(1, "3 passed")


def test_a_gate_that_is_not_done_is_pending_and_is_never_read():
    plan = new_plan()
    out = probegate.interpret_gate(plan, None)
    assert out.transport_pending and not out.ran and not out.transport_unknown and plan.error == ""
    assert probegate.clean_gate_output(plan) is None and probegate.sections_of(plan) == {}


def test_a_complete_result_is_adopted_and_read():
    plan = new_plan()
    assert probegate.adopt(plan, result_of(RAW, plan.op)) == "complete" and plan.complete
    assert list(probegate.sections_of(plan)) == ["probe-0", "probe-1"]


def test_a_result_that_did_not_arrive_whole_is_unknown_never_clean_and_says_why():
    """Every way the evidence can fail ends here: UNKNOWN, no readable sections, the harness's own last line verbatim for the model's notice."""
    plan = new_plan()
    broken = gateops.GateResult(plan.op, "", "unknown", reason="the check output could not be read whole", reported="No space left on device")
    out = probegate.interpret_gate(plan, broken)
    assert out.transport_unknown and not out.ran and out.transport_reported == "No space left on device"
    assert probegate.sections_of(plan) == {} and probegate.clean_gate_output(plan) is None
    assert "No space left on device" in probegate.transport_unknown_text(out.transport_reported)
    again = probegate.interpret_gate(plan)                                       # asking again says the same: it cannot be revived by silence
    assert again.transport_unknown and not again.ran


def test_a_gate_the_harness_refused_is_unknown_and_carries_the_harness_words():
    plan = new_plan()
    refused = gateops.GateResult(plan.op, "", "unknown", reason="the harness declined to run the checks",
                                 refusal=gateops.refusal_reason('Rejected("rm -f style commands are not permitted")'))
    out = probegate.interpret_gate(plan, refused)
    assert out.transport_unknown and not out.ran and "not permitted" in out.refused


def test_a_gate_past_its_own_deadline_is_terminal_unknown():
    plan = new_plan(deadline_s=5.0, started=time.monotonic() - 60)
    out = probegate.interpret_gate(plan, None)
    assert out.transport_unknown and "exceeded" in plan.error


NOISE = ("import hashlib,sys\nfor i in range(900): print('noise-%04d-'%i+hashlib.sha256(str(i).encode()).hexdigest())\n"
         "print('src/middle.py:73: MIDDLE_FAILURE'); print('FINAL_TALLY: 1 failed'); sys.exit(1)")


def test_a_real_gate_run_with_output_over_many_frames_is_read_whole_and_its_findings_come_from_the_middle(tmp_path, monkeypatch):
    plan, outcome, result = real_gate(tmp_path, monkeypatch, NOISE)
    text, code = result.sections["probe-0"]
    assert outcome.ran and not outcome.transport_unknown and code == 1 and len(text.encode()) > 60_000
    assert "noise-0000" in text and "MIDDLE_FAILURE" in text and "FINAL_TALLY" in text
    assert any("middle.py" in f.file for f in outcome.report.results[0].findings)
