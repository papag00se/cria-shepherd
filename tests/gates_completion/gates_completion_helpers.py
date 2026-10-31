"""Shared fixtures for the gates_completion shard: hand-built gate streams, delivered the way a real harness pages them."""
import base64
import hashlib
import json
import os
import subprocess
import sys

import pytest

from cria import probegate, proberun, wsview
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind

P, S = probegate.SECTION_PREFIX, probegate.SECTION_SUFFIX


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


def sec(i, body, code=0):
    return f"{P}probe-{i}{S}\n{body}\nEXIT:{code}\n"


def cand(argv, kind=ProbeKind.Test, wd="/ws"):
    return ProbeCandidate(kind=kind, command=argv, working_dir=wd, confidence=90, expected_value=80,
                          cost=ProbeCost.Cheap, mutates_code=False, may_hang=False, may_need_services=False, reason="t")


def _bounds(raw):
    data, sections, off = raw.encode(), {}, 0
    for line in data.splitlines(keepends=True):
        t = line.strip()
        if t.startswith(P.encode()) and t.endswith(S.encode()):
            sections[t[len(P):-len(S)].decode()] = off
        off += len(line)
    declared = dict(checker_end=len(data), report_end=len(data), total=len(data), sections=sections)
    return base64.b64encode(json.dumps(declared).encode()).decode()


def page(plan, raw, offset=0, size=None, **over):
    """The page a harness reader delivers for ``raw``; ``over`` replaces (or, with None, drops) fields."""
    data = raw.encode()
    chunk = data[offset:] if size is None else data[offset:offset + size]
    b64 = lambda raw_bytes: base64.b64encode(raw_bytes).decode()                                    # noqa: E731
    f = dict(path=b64(f"/tmp/.cria-gate-{plan.transport_id}.spool".encode()), offset=str(offset), total=str(len(data)),
             sha256=hashlib.sha256(data).hexdigest(), bounds=_bounds(raw), data=b64(chunk))
    f.update(over)
    body = [f"{k}\t{v}" for k, v in f.items() if v is not None]
    return "\n".join([probegate._transport_marker(plan.transport_id), *body, probegate._transport_marker(plan.transport_id, end=True)])


def real_page(plan, raw=None):
    """A page carrying the extents the real worker declared for a completed ``plan``."""
    raw = raw or plan.transport_data.decode()
    declared = dict(checker_end=plan.transport_bounds[0], report_end=plan.transport_bounds[1], total=len(raw.encode()),
                    sections=plan.transport_sections)
    return page(plan, raw, bounds=base64.b64encode(json.dumps(declared).encode()).decode())


def deliver(plan, raw):
    """``plan`` after ``raw`` arrived as a complete, verified transport (paged at the real chunk size)."""
    offset, size = 0, probegate.TRANSPORT_CHUNK_BYTES
    while probegate.ingest_transport(plan, page(plan, raw, offset, size)) == "pending":
        offset += size
    assert plan.transport_complete, plan.transport_error
    return plan


def new_plan(tid="a" * 24, **kw):
    return probegate.GatePlan(kw.pop("workspace", ""), transport_required=True, transport_id=tid, **kw)


def clean(raw, plan=None, **kw):
    return probegate.clean_gate_output(raw, deliver(plan or new_plan(), raw), **kw)


def gate_turn(call_id, raw, tid="a" * 24, probes=("pytest -q",), **over):
    plan = new_plan(tid)
    cmd = probegate._gate_sentinel(list(probes)) + "\n__cria_gate_file=/tmp/x\n" + probegate._transport_reader('"/tmp/x"', 0, tid)
    return [{"role": "assistant", "tool_calls": [{"id": call_id, "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"cmd": cmd})}}]},
            {"role": "tool", "tool_call_id": call_id, "content": page(plan, raw, **over)}]


def coder_call(call_id, cmd, result=None, name="exec_command", args=None):
    msgs = [{"role": "assistant", "tool_calls": [{"id": call_id, "type": "function", "function": {
        "name": name, "arguments": json.dumps(args or {"cmd": cmd})}}]}]
    return msgs + ([{"role": "tool", "tool_call_id": call_id, "content": result}] if result is not None else [])


def text_of(messages):
    return "\n".join(str(m.get("content") or "") for m in messages)


def harness_dir(tmp_path):
    path = tmp_path.parent / (tmp_path.name + "-harness")
    path.mkdir(exist_ok=True)
    return path


def run_in_harness(command, tmp_path, shell="bash"):
    env = {"PATH": os.environ["PATH"], "TMPDIR": str(harness_dir(tmp_path))}
    return subprocess.run([shell, "-c", command], cwd=tmp_path, env=env, capture_output=True, text=True).stdout


def real_gate(tmp_path, monkeypatch, program, *, wd=None):
    """Compose the real gate for one checker program, run it under sh as a harness would, page it home."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "source.txt").write_text("source\n")
    c = ProbeCandidate(ProbeKind.BuildCheck, [sys.executable, "-c", program], wd or tmp_path, 100, 100,
                       ProbeCost.Cheap, False, False, False, "fixture", composed_by_cria=True)
    monkeypatch.setattr(proberun, "select_completion_probes", lambda root: [c])
    plan = probegate.plan_gate(str(tmp_path))
    pages = [run_in_harness(plan.script, tmp_path, "sh")]
    outcome = probegate.interpret_gate(plan, pages[-1])
    while outcome.transport_pending:
        pages.append(run_in_harness(probegate.continue_transport_command(plan), tmp_path))
        outcome = probegate.interpret_gate(plan, pages[-1])
    return plan, outcome, pages
