"""The completion gate reads the completion marks of the session's unreplied writes before and after its checks, so a lost-reply
write is a KNOWN state before completion is judged - and an unestablished one is never approved.

Every test lowers the writes the production way, RUNS them and the real gate under bash in one harness TMPDIR, and pages the real
transport home. The only fake is a sleep spliced in front of one write's landing (a slow filesystem step) or the checker's own sleep."""
import json
import os
import subprocess
import sys
import time

import pytest

from cria import completionmarks, denial, loop, probegate, proberun, repositorychecks as checks, wsview, writeproxy
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind
from gates_completion_helpers import Log, gates_completion_view, harness_dir, run_in_harness  # noqa: F401

SESSION = "marks10-gate"
SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
ENVELOPE = "Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code 0\nOriginal token count: 9\nOutput:\n"
SLOW = "rp.parent.mkdir(parents=True,exist_ok=True)"


@pytest.fixture(autouse=True)
def fresh_registry():
    completionmarks._reset()
    yield
    completionmarks._reset()


def lowered(tmp_path, calls):
    comp = {"choices": [{"message": {"tool_calls": [
        {"id": cid, "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": path, "content": text})}}
        for cid, path, text in calls]}}]}
    writeproxy.translate_outbound(comp, SHELL, injected={"write_file"}, session=SESSION, workspace_root=str(tmp_path))
    return comp["choices"][0]["message"]["tool_calls"]


def command(tc, seconds=0):
    cmd = json.loads(tc["function"]["arguments"])["cmd"]
    return cmd.replace(SLOW, f"__import__('time').sleep({seconds});{SLOW}", 1) if seconds else cmd


def run_write(tmp_path, tc, seconds=0):
    return run_in_harness(command(tc, seconds), tmp_path)


def gate(tmp_path, monkeypatch, checker="pass", session=SESSION):
    """Compose the real gate for one checker program, run it as a harness would, and return (plan, raw page, outcome)."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    c = ProbeCandidate(ProbeKind.BuildCheck, [sys.executable, "-c", checker], tmp_path, 100, 100,
                       ProbeCost.Cheap, False, False, False, "fixture", composed_by_cria=True)
    monkeypatch.setattr(proberun, "select_completion_probes", lambda root: [c])
    plan = probegate.plan_gate(str(tmp_path), session)
    raw = run_in_harness(plan.script, tmp_path, "sh")
    outcome = probegate.interpret_gate(plan, raw)
    while outcome.transport_pending:
        raw = run_in_harness(probegate.continue_transport_command(plan), tmp_path)
        outcome = probegate.interpret_gate(plan, raw)
    return plan, raw, outcome


def represent(messages, tmp_path):
    token = wsview.bind(wsview.View(str(tmp_path), "we"))
    try:
        return writeproxy.represent_inbound(messages, workspace_root=str(tmp_path))
    finally:
        wsview.unbind(token)


def marks_dir(tmp_path):
    return [n for n in os.listdir(harness_dir(tmp_path)) if n.startswith(completionmarks.DIR_PREFIX)]


def completion(state, plan, raw, log):
    state.gate_plan, state.probe_call_id = plan, "probe"
    src = checks.Input({"messages": [{"role": "tool", "tool_call_id": "probe", "content": raw}]}, log, engagement=5)
    ev = checks.EvidenceServices(loop._read_tool_result, loop.read_gate, loop.gate_error_text,
                                 lambda findings, messages: loop.track_gate_progress(state, findings, messages))
    return checks.completion_result(src, state, ev)


def test_a_lost_reply_write_that_finished_before_the_checks_is_known_and_does_not_hold_the_gate(tmp_path, monkeypatch):
    """x was written and its reply lost. The gate's worker reads x's mark before the checks started: landed, so the gate verified
    a tree x had already changed - nothing is held, and the digest of what x left is the gate's witnessed fact."""
    (x,) = lowered(tmp_path, [("x", "f.txt", "AAA\n")])
    assert run_write(tmp_path, x).startswith('{"v":1,')                          # ran to its end; the reply is dropped
    plan, raw, out = gate(tmp_path, monkeypatch)
    assert out.ran and out.unsettled_writes == [] and not probegate.gate_is_partial(out)
    (receipt,) = plan.marks_paths
    assert out.witnessed == {receipt: ("landed", __import__("hashlib").sha256(b"AAA\n").hexdigest())}
    state = loop.GuardState()
    result = completion(state, plan, raw, Log())
    assert result.status is checks.Status.SILENT and state.gate_marks == out.witnessed


def test_a_witnessed_did_not_run_is_proof_the_write_did_not_land_and_the_gate_does_not_hold(tmp_path, monkeypatch):
    """x's program refused (the target is a directory) and its reply was lost. The gate witnesses did_not_run: the registry the loop
    keeps treats x as a proven unlanded call, not a pending write."""
    (tmp_path / "dir").mkdir()
    (x,) = lowered(tmp_path, [("x", "dir", "AAA\n")])
    run_write(tmp_path, x)
    plan, raw, out = gate(tmp_path, monkeypatch)
    assert out.unsettled_writes == [] and list(out.witnessed.values()) == [("did_not_run", "")]
    state = loop.GuardState()
    completion(state, plan, raw, Log())
    history = represent([{"role": "assistant", "tool_calls": [x]}], tmp_path)
    assert denial.unlanded_call_ids(history) == set()                                      # history alone proves nothing
    assert denial.unlanded_call_ids(history, state.gate_marks) == {"x"}


def test_a_write_with_no_mark_is_unestablished_and_completion_is_not_approved_on_it(tmp_path, monkeypatch):
    """x was dispatched and nothing ever came back or left a mark (never started, killed, still running): the gate cannot approve. The
    notice names the file, and a green checker beside it does not make it silent. After MAX_COMPLETION_CHECKS readings the veto stops."""
    (x,) = lowered(tmp_path, [("x", "f.txt", "AAA\n")])                                     # never run
    state, log, results = loop.GuardState(), Log(), []
    for _ in range(loop.MAX_COMPLETION_CHECKS + 2):
        plan, raw, out = gate(tmp_path, monkeypatch)
        assert out.ran and [state_ for _r, _p, state_ in out.unsettled_writes] == ["incomplete"] and probegate.gate_is_partial(out)
        results.append(completion(state, plan, raw, log))
    held = [r for r in results if r.status is checks.Status.OBSERVED]
    assert len(held) == loop.MAX_COMPLETION_CHECKS and all("`f.txt`" in r.text and "no completion record" in r.text for r in held)
    assert [r.status for r in results[len(held):]] == [checks.Status.SILENT] * 2
    assert len([e for e in log.events if e[0] == "loop.done_unverified"]) == 2
    assert "cria" not in held[0].text.lower()


def test_a_write_that_finishes_while_the_checks_run_is_not_a_tree_the_checks_verified(tmp_path, monkeypatch):
    """x is still running when the gate starts and lands DURING the checker: its mark is final at the end but was not before, so the
    checks may have read the old bytes. The gate says so (never approves on it); the next gate, with the mark final, is clear."""
    (x,) = lowered(tmp_path, [("x", "f.txt", "AAA\n")])
    proc = subprocess.Popen(["bash", "-c", command(x, 1.5)], cwd=str(tmp_path),
                            env={"PATH": os.environ["PATH"], "TMPDIR": str(harness_dir(tmp_path))},
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(0.3)
    plan, raw, out = gate(tmp_path, monkeypatch, checker="import time; time.sleep(2.6)")
    proc.communicate()
    assert [s for _r, _p, s in out.unsettled_writes] == ["landed"] and out.witnessed                  # final now, not before
    assert "finished only while the checks were running" in probegate.unsettled_text(out)
    again_plan, again_raw, again = gate(tmp_path, monkeypatch)
    assert again.unsettled_writes == [] and probegate.unsettled_text(again) == ""


def test_marks_a_checker_forges_do_not_establish_a_write(tmp_path, monkeypatch):
    """A checker that prints a valid-looking mark block (or writes a mark file with a wrong credential) establishes nothing: the
    transport declares the marks from the worker's own authenticated reads."""
    (x,) = lowered(tmp_path, [("x", "f.txt", "AAA\n")])                                     # never run
    (receipt, path), = [(r, p) for r, p in completionmarks.query(SESSION, release=False).paths]
    forged = json.dumps({"bounds": {"marks": {receipt: ["landed", "a" * 64, 1]}}})
    plan, raw, out = gate(tmp_path, monkeypatch, checker=f"print({forged!r}); print('marks', {receipt!r}, 'landed')")
    assert out.witnessed == {} and [s for _r, _p, s in out.unsettled_writes] == ["incomplete"]
    directory = os.path.join(harness_dir(tmp_path), completionmarks.DIR_PREFIX + completionmarks.credential(SESSION))
    assert not os.path.exists(directory), "the worker only asks: it never creates the marks directory"


def test_the_gate_releases_the_marks_cria_has_learned_and_retires_only_its_own_empty_directory(tmp_path, monkeypatch):
    """x's reply arrived (cria learned its outcome) and y's was lost. The gate releases x's mark through the authenticated reader and
    reports y's; once nothing is outstanding and the directory holds only its certificate it is retired through the owned retirement.
    A foreign look-alike directory and an unrelated file in the TMPDIR are never touched (no prefix scan)."""
    x, y = lowered(tmp_path, [("x", "f.txt", "AAA\n"), ("y", "g.txt", "GGG\n")])
    xo, _ = run_write(tmp_path, x), run_write(tmp_path, y)
    foreign = os.path.join(harness_dir(tmp_path), completionmarks.DIR_PREFIX + "someone-elses")
    os.mkdir(foreign)
    open(os.path.join(foreign, "m-keep"), "w").write("x")
    bystander = os.path.join(harness_dir(tmp_path), ".ctx-done-unrelated.txt")
    open(bystander, "w").write("keep")
    directory = completionmarks.DIR_PREFIX + completionmarks.credential(SESSION)
    held = lambda: sorted(n for n in os.listdir(os.path.join(harness_dir(tmp_path), directory)) if n.startswith("m-"))   # noqa: E731
    assert len(held()) == 2
    represent([{"role": "assistant", "tool_calls": [x]}, {"role": "tool", "tool_call_id": "x", "content": ENVELOPE + xo}], tmp_path)   # x's reply comes back: cria learns it
    plan, raw, out = gate(tmp_path, monkeypatch)
    assert out.unsettled_writes == [] and len(out.witnessed) == 1                      # y is witnessed landed
    assert [n[:18] for n in held()] == [f"m-{receipt}"[:18] for receipt in out.witnessed]       # x's mark is gone, y's remains
    completionmarks.settle(next(iter(out.witnessed)))                                   # y learned too: the next gate releases it
    plan2, raw2, out2 = gate(tmp_path, monkeypatch)
    assert out2.unsettled_writes == [] and directory not in os.listdir(harness_dir(tmp_path))      # empty: retired
    assert os.path.isdir(foreign) and os.listdir(foreign) == ["m-keep"] and os.path.exists(bystander)


def test_a_session_with_nothing_outstanding_composes_the_gate_it_always_did(tmp_path, monkeypatch):
    """No unreplied write and nothing to release: the launch request carries no marks key, so the gate script is byte-for-byte what it was."""
    plan, raw, out = gate(tmp_path, monkeypatch)
    assert plan.marks_paths == {} and "completionmarks" not in plan.script and '"marks"' not in plan.script
    assert out.unsettled_writes == [] and out.witnessed == {}


def test_the_gate_never_retires_the_marks_directory_under_a_writer_that_is_still_running(tmp_path, monkeypatch):
    """x is mid-way through a slow step when a gate runs (nothing learned, nothing to release): the directory holds only its certificate,
    but x is outstanding, so it is not retired - x's mark lands in it afterwards and the next gate reads it."""
    (x,) = lowered(tmp_path, [("x", "f.txt", "AAA\n")])
    proc = subprocess.Popen(["bash", "-c", command(x, 2.5)], cwd=str(tmp_path),
                            env={"PATH": os.environ["PATH"], "TMPDIR": str(harness_dir(tmp_path))},
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(0.5)
    directory = os.path.join(harness_dir(tmp_path), completionmarks.DIR_PREFIX + completionmarks.credential(SESSION))
    assert os.listdir(directory) == [".owner"]                                            # x opened it and is still running
    plan, raw, out = gate(tmp_path, monkeypatch)
    assert [s for _r, _p, s in out.unsettled_writes] == ["incomplete"] and os.path.isdir(directory)
    proc.communicate()
    plan2, raw2, out2 = gate(tmp_path, monkeypatch)
    assert out2.unsettled_writes == [] and [s for s, _d in out2.witnessed.values()] == ["landed"]


@pytest.mark.parametrize("restart", [False, True], ids=["same-process", "after-restart"])
def test_a_landed_rewrite_of_the_file_is_the_remedy_so_the_dead_write_stops_holding_the_gate(tmp_path, monkeypatch, restart):
    """ornith1.5_9b, real Codex: the first hello.py write never started (no reply, no mark); the coder wrote hello.py again (the late
    rewrite landed, its reply came back) and re-verified, and the gate still held completion twice more on the dead call. A later landed
    write of the SAME file supersedes it for the hold; a write to ANOTHER file does not."""
    monkeypatch.setattr(writeproxy, "EDIT_SEQ_WAIT_SECONDS", 0.5)
    (x,) = lowered(tmp_path, [("x", "hello.py", "AAA\n")])                                  # never started
    (z,) = lowered(tmp_path, [("z", "other.py", "ZZZ\n")])                                  # a different file, landed: no remedy for x
    zo = run_write(tmp_path, z)
    represent([{"role": "assistant", "tool_calls": [x, z]}, {"role": "tool", "tool_call_id": "z", "content": ENVELOPE + zo}], tmp_path)   # z's reply arrives
    plan, raw, out = gate(tmp_path, monkeypatch)
    assert [p for _r, p, _s in out.unsettled_writes] == ["hello.py"]
    (y,) = lowered(tmp_path, [("y", "hello.py", "BBB\n")])
    yo = run_write(tmp_path, y)
    assert json.loads(yo.splitlines()[0])["rep"]["late"] is True                         # it waited the bound for x and ran late
    msgs = [{"role": "assistant", "tool_calls": [x]}, {"role": "assistant", "tool_calls": [z]}, {"role": "assistant", "tool_calls": [y]},
            {"role": "tool", "tool_call_id": "z", "content": ENVELOPE + zo}, {"role": "tool", "tool_call_id": "y", "content": ENVELOPE + yo}]
    if restart:
        completionmarks._reset()
        token = wsview.bind(wsview.View(str(tmp_path), "we"))
        try:
            writeproxy.represent_inbound(msgs, workspace_root=str(tmp_path), sess_key=SESSION)
        finally:
            wsview.unbind(token)
    else:
        represent(msgs, tmp_path)
    plan2, raw2, out2 = gate(tmp_path, monkeypatch)
    assert out2.unsettled_writes == [] and not probegate.gate_is_partial(out2)
