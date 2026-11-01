"""The completion gate tells a dead writer from a slow one by the writer's own start record, and says so: a writer whose process is
gone and that left no final mark is `dead` (the coder is told that write was killed and to write it again, at the first gate), a live
one is `running`, one nobody can say anything about is `incomplete`. None of the three is ever approved on - the doctrine is unchanged:
a dead writer may have landed its bytes before it died, so the gate holds exactly as long as it held an unknown one (bounded)."""
import json

import pytest

from cria import completionmarks, loop, probegate, prompts, repositorychecks as checks
from gates_completion_helpers import Log, harness_dir, run_in_harness  # noqa: F401
from test_gates_completion_marks_gate_carrier import (ENVELOPE, SESSION, completion, fresh_registry, gate, lowered,  # noqa: F401
                                                      represent, run_write)

SLOW = "rp.parent.mkdir(parents=True,exist_ok=True)"
LANDED = "sys.stdout.write(_rec('landed'"


def dying(tc, anchor):
    """The same lowered program ending WITHOUT its exit handlers (`os._exit`: the state a kill leaves) just before ``anchor``; no signal is sent."""
    cmd = json.loads(tc["function"]["arguments"])["cmd"]
    assert anchor in cmd
    return cmd.replace(anchor, f"__import__('os')._exit(3);{anchor}", 1)


def test_a_dead_writer_is_held_with_its_own_notice_and_bounded_like_an_unknown_one(tmp_path, monkeypatch):
    """x died before landing (no mark), y never started. Both hold the gate; x's notice says the process is gone, y's says nothing can be
    known - the two differ - and after MAX_COMPLETION_CHECKS readings the veto stops (said, not silent), exactly as for an unknown write."""
    x, y = lowered(tmp_path, [("x", "dead.txt", "AAA\n"), ("y", "never.txt", "NNN\n")])
    run_in_harness(dying(x, SLOW), tmp_path)
    states = {}
    state, log, results = loop.GuardState(), Log(), []
    for _ in range(loop.MAX_COMPLETION_CHECKS + 1):
        plan, raw, out = gate(tmp_path, monkeypatch)
        states = {p: s for _r, p, s in out.unsettled_writes}
        assert states == {"dead.txt": "dead", "never.txt": "incomplete"} and probegate.gate_is_partial(out) and out.witnessed == {}
        results.append(completion(state, plan, raw, log))
    held = [r for r in results if r.status is checks.Status.OBSERVED]
    assert len(held) == loop.MAX_COMPLETION_CHECKS and "`dead.txt`" in held[0].text and "`never.txt`" in held[0].text
    assert results[-1].status is checks.Status.SILENT and [e[0] for e in log.events].count("loop.done_unverified") == 1
    only_dead = probegate.GateOutcome(ran=True, unsettled_writes=[("r", "dead.txt", "dead")])
    only_unknown = probegate.GateOutcome(ran=True, unsettled_writes=[("r", "dead.txt", "incomplete")])
    only_running = probegate.GateOutcome(ran=True, unsettled_writes=[("r", "dead.txt", "running")])
    fills = prompts.load_map("gate_unsettled_writes")
    for outcome, own in ((only_dead, "dead"), (only_unknown, "unknown"), (only_running, "running")):
        text = probegate.unsettled_text(outcome)
        assert "`dead.txt`" in text and fills[own] in text, own                 # each state says its own sentence ...
        assert not [other for other in ("dead", "unknown", "running", "overlapped") if other != own and fills[other] in text], own   # ... and no other
        assert "cria" not in text.lower()


def test_a_writer_that_died_after_landing_is_still_dead_and_still_held(tmp_path, monkeypatch):
    """The bytes are on disk but the program died before its mark: the gate witnesses only a dead process, never a landing, and does not approve."""
    (x,) = lowered(tmp_path, [("x", "f.txt", "AAA\n")])
    run_in_harness(dying(x, LANDED), tmp_path)
    assert (tmp_path / "f.txt").read_text() == "AAA\n"
    plan, raw, out = gate(tmp_path, monkeypatch)
    assert [s for _r, _p, s in out.unsettled_writes] == ["dead"] and out.witnessed == {} and probegate.gate_is_partial(out)


def test_a_dead_writer_a_later_landed_rewrite_supersedes_stops_holding_the_gate(tmp_path, monkeypatch):
    """The notice asks for the write again; a landed rewrite of the same file IS that remedy (its reply arrived), so the dead call holds no more."""
    (x,) = lowered(tmp_path, [("x", "hello.py", "AAA\n")])
    run_in_harness(dying(x, SLOW), tmp_path)
    plan, raw, out = gate(tmp_path, monkeypatch)
    assert [(p, s) for _r, p, s in out.unsettled_writes] == [("hello.py", "dead")]
    (y,) = lowered(tmp_path, [("y", "hello.py", "BBB\n")])                      # the coder's rewrite, a later turn
    yo = run_write(tmp_path, y)
    assert json.loads(yo.splitlines()[0])["k"] == "landed" and "late" not in json.loads(yo.splitlines()[0]).get("rep", {})
    represent([{"role": "assistant", "tool_calls": [x, y]}, {"role": "tool", "tool_call_id": "y", "content": ENVELOPE + yo}], tmp_path)
    plan2, raw2, out2 = gate(tmp_path, monkeypatch)
    assert out2.unsettled_writes == [] and not probegate.gate_is_partial(out2)
