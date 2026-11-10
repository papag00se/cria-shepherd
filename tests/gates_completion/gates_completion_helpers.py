"""Shared fixtures for the gates_completion shard: hand-built gate results, delivered the way cria's own gate operation delivers them."""
import json
import os
import sys

import pytest

from cria import probegate, proberun, wsview
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind
from gate_fixtures import P, S, facts_of, gate_turn, lost_result, result_of, sec  # noqa: F401  (shared with the other shards)


@pytest.fixture(autouse=True)
def gates_completion_view():
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)


class Log:
    def __init__(self):
        self.events = []

    def emit(self, name, **fields):
        self.events.append((name, fields))


def cand(argv, kind=ProbeKind.Test, wd="/ws"):
    return ProbeCandidate(kind=kind, command=argv, working_dir=wd, confidence=90, expected_value=80,
                          cost=ProbeCost.Cheap, mutates_code=False, may_hang=False, may_need_services=False, reason="t")


def new_plan(tid="a" * 12, **kw):
    return probegate.GatePlan(kw.pop("workspace", ""), op=tid, **kw)


def deliver(plan, raw):
    """``plan`` after its gate finished with the hand-written stream ``raw``."""
    plan.result = result_of(raw, plan.op, plan.workspace, facts_of(plan.candidates))
    return plan


def clean(raw, plan=None, **kw):
    return probegate.clean_gate_output(deliver(plan or new_plan(), raw), **kw)


def coder_call(call_id, cmd, result=None, name="exec_command", args=None):
    msgs = [{"role": "assistant", "tool_calls": [{"id": call_id, "type": "function", "function": {
        "name": name, "arguments": json.dumps(args or {"cmd": cmd})}}]}]
    return msgs + ([{"role": "tool", "tool_call_id": call_id, "content": result}] if result is not None else [])


def text_of(messages):
    return "\n".join(str(m.get("content") or "") for m in messages)


def real_gate(tmp_path, monkeypatch, program, *, wd=None):
    """Compose the real gate for one checker program, run it through cria's own gate operation with the real stubs where the files are, and read it."""
    import subprocess
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from survey_fixtures import gate_of_disk
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "source.txt").write_text("source\n")
    c = ProbeCandidate(ProbeKind.BuildCheck, [sys.executable, "-c", program], wd or tmp_path, 100, 100,
                       ProbeCost.Cheap, False, False, False, "fixture", composed_by_cria=True)
    monkeypatch.setattr(proberun, "select_completion_probes", lambda root: [c])
    plan = probegate.plan_gate(str(tmp_path))
    result = gate_of_disk(tmp_path, script=plan.script, sections=plan.sections, scope=plan.scope,
                          candidates=plan.candidates, timeout=120, deadline=150, wait=2.0)
    outcome = probegate.interpret_gate(plan, result)
    return plan, outcome, result


def run_plan(plan, root, **kw):
    """The gate of ``plan`` run for real: its operation is issued and every call it asks for is run with bash where the files are, with the real stubs."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from survey_fixtures import gate_of_disk
    result = gate_of_disk(root, script=plan.script, sections=plan.sections, scope=plan.scope, candidates=plan.candidates,
                          timeout=kw.pop("timeout", 240), deadline=kw.pop("deadline", 300), wait=kw.pop("wait", 2.0), **kw)
    return result


class GateRig:
    """cria's own gate operation with a real harness behind it: a real engine (a private ledger), the real stubs and real bash where the files are.
    `seam` is what the loop's guards reach the engine through; `drive` plays the part of the server for one gate call: it runs what the harness is
    handed and hands the results back until the engine has nothing more to ask (the model is not consulted in between)."""

    def __init__(self, root, session="gate-rig"):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from cria import gateseam
        from cria.ops import Ops
        self.root, self.session, self.ops = str(root), session, Ops()
        self.seam = gateseam.Seam(issue=lambda sess, tool, plan: probegate.issue(self.ops, sess, tool, plan),
                                  result=lambda sess, op: self.ops.gate_of(sess, op),
                                  resume=lambda sess, op: self.ops.resume_gate(sess, op))

    def run_command(self, command):
        import subprocess
        from survey_fixtures import harness_env
        done = subprocess.run(["/bin/bash", "-c", command], cwd=self.root, env=harness_env(self.root), capture_output=True, text=True, timeout=300)
        return done.stdout + done.stderr

    def drive(self, messages, call, *, answer=True, session=None):
        """``call`` and, when ``answer``, every call the engine asks for after it, run and answered in ``messages`` (the harness's own history)."""
        session = self.session if session is None else session
        messages.append({"role": "assistant", "tool_calls": [call]})
        calls = [call] if answer else []
        while calls:
            for c in calls:
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": self.run_command(json.loads(c["function"]["arguments"])["cmd"])})
            calls = self.ops.incoming(session, messages).calls
            if calls:
                messages.append({"role": "assistant", "tool_calls": calls})
