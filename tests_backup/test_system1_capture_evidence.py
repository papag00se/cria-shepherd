"""The CPU classifier's call records must be invisible to the suite's LLM-call evidence.

``System1Runtime`` writes one authoritative record per real classifier call (success AND failure) into
the same session folder the upstream model captures live in. The suite reads that folder to count
model calls (``suite.run.collect_capture``), to snapshot request/response evidence
(``suite.run.capture_manifest``) and to admit a campaign row (``suite.fresh_l5_campaign._valid_capture_evidence``,
which ``suite.l0_campaign.valid_row`` delegates to). A classifier record that looks like an upstream call
inflates the call/phase counts and — because it is not a chat completion — makes the whole row invalid, so
every cell run with capture on and ``[system1]`` enabled would be rejected.

The tests produce the records with the REAL runtime (fake ``onnxruntime``/``tokenizers`` engines, as in
``test_system1_runtime``; the last test runs the real engines and skips when they are absent) next to REAL
upstream captures made by ``callcapture.capture`` / ``capture_response``, then feed the folder to the
suite's own readers. Nothing here re-implements a reader.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from cria import callcapture, system1
from cria.system1 import FAMILIES, System1Error, System1Runtime
from suite import fresh_l5_campaign, l0_campaign
from suite.run import capture_manifest, collect_capture

# the fake engines are an autouse fixture: importing the names registers them in this module
from test_system1_runtime import (  # noqa: F401  (fixtures + helpers shared with the runtime tests)
    MAX_WINDOW_TOKENS, REAL_BUNDLE, FakeSession, FakeTokenizer, Rlog, _real_engines, bundle, brief, directive,
    fake_engines)

SESSION = "0199-evidence-session"
MODEL_PHASES = ["coder", "satisfaction"]


@pytest.fixture(autouse=True)
def _fresh_sequence_counters():
    """The capture counters are process-wide and keyed by session id; every test starts from none."""
    callcapture._seq.clear()
    yield
    callcapture._seq.clear()


# ---- helpers ----------------------------------------------------------------------------------

def _model_call(rlog, calls: Path, phase: str, text: str) -> None:
    """One upstream call exactly as ``Upstream`` captures it: chat request + chat completion."""
    body = {"model": "m", "messages": [{"role": "user", "content": text}], "temperature": 0.0}
    path = callcapture.capture(body, rlog, calls_dir=calls, phase=phase)
    assert path is not None
    callcapture.capture_response(path, {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}, rlog)


def _session_dir(calls: Path) -> Path:
    return calls / callcapture.session_dirname(SESSION)


def _json_nodes(value):
    """Every value, list and dict key inside a parsed JSON document (format-agnostic search)."""
    yield value
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _json_nodes(item)
    elif isinstance(value, list):
        for item in value:
            yield from _json_nodes(item)


def _record_nodes(path: str) -> list:
    return list(_json_nodes(json.loads(Path(path).read_text())))


def _row(session: Path, calls: int, phases: dict, *, snapshot: bool = True) -> dict:
    row = {"capture_dirs": [str(session)], "capture_dir": str(session), "calls": calls, "phases": phases,
           "started": time.time() - 30, "wall_seconds": 3600}
    if snapshot:
        row["capture_snapshot"] = capture_manifest([session])
    return row


def _rendered(rt_bundle: Path, family: str, state: dict) -> str:
    spec = FAMILIES[family]
    policy = (rt_bundle / "policy" / f"{family}.txt").read_text()
    return system1.render_input(spec.labels, policy, system1.render_state(state))


def _arm(outcome: str) -> None:
    if outcome == "nofit":
        FakeTokenizer.extra_tokens = MAX_WINDOW_TOKENS
    elif outcome == "nonfinite":
        FakeSession.behavior = staticmethod(lambda ids: [[float("nan"), 0.0]])
    elif outcome == "engine":
        FakeSession.behavior = staticmethod(lambda ids: RuntimeError("allocator refused the activations"))


def _disarm() -> None:
    FakeTokenizer.extra_tokens = 0
    FakeSession.behavior = staticmethod(lambda ids: [[2.0, -1.0]])


def _interleaved_session(rt, calls: Path, rlog, family: str, state: dict, outcome: str):
    """model call, classifier call (``outcome``), model call, a second good classifier call.

    Returns (the outcome's event, the session dir)."""
    _model_call(rlog, calls, MODEL_PHASES[0], "first")
    _arm(outcome)
    try:
        if outcome == "ok":
            rt.judge_detailed(family, state, rlog=rlog)
        else:
            with pytest.raises(System1Error):
                rt.judge_detailed(family, state, rlog=rlog)
    finally:
        _disarm()
    _model_call(rlog, calls, MODEL_PHASES[1], "second")
    rt.judge_detailed("dictation", directive("a later, good call"), rlog=rlog)
    kind = "system1.judgment" if outcome == "ok" else "system1.error"
    first = [kw for k, kw in rlog.events if k == kind][0]
    return first, _session_dir(calls)


OUTCOMES = ["ok", "nofit", "nonfinite", "engine"]


# ---- the suite's readers see only the LLM calls ----------------------------------------------------

@pytest.mark.parametrize("outcome", OUTCOMES)
def test_classifier_records_neither_inflate_the_llm_metrics_nor_invalidate_the_row(bundle, tmp_path, outcome):
    calls, rlog = tmp_path / "calls", Rlog(SESSION)
    rt = System1Runtime(bundle, capture_dir=calls)
    event, session = _interleaved_session(rt, calls, rlog, "retrospective", brief("the whole briefing"), outcome)
    assert event["capture"] and Path(event["capture"]).is_file()  # the records exist — and still do not leak

    phases = {phase: 1 for phase in MODEL_PHASES}
    snapshot = capture_manifest([session])
    assert [e["phase"] for e in snapshot["entries"]] == MODEL_PHASES and snapshot["complete"] is True
    for counted in (collect_capture([session]), collect_capture([session], snapshot)):
        assert counted["calls"] == 2 and counted["phases"] == phases
    for with_snapshot in (True, False):
        row = _row(session, 2, phases, snapshot=with_snapshot)
        assert fresh_l5_campaign._valid_capture_evidence(row) is True
        assert fresh_l5_campaign._valid_capture_evidence(row, allow_errors=True) is True


def test_a_folder_with_only_llm_captures_is_the_valid_control(tmp_path):
    """Guards the test itself: the upstream captures built here are admissible evidence on their own."""
    calls, rlog = tmp_path / "calls", Rlog(SESSION)
    for phase in MODEL_PHASES:
        _model_call(rlog, calls, phase, phase)
    session = _session_dir(calls)
    assert collect_capture([session])["calls"] == 2
    assert fresh_l5_campaign._valid_capture_evidence(_row(session, 2, {p: 1 for p in MODEL_PHASES})) is True
    assert fresh_l5_campaign._valid_capture_evidence(_row(session, 3, {p: 1 for p in MODEL_PHASES})) is False


def test_l0_row_admission_reaches_the_same_capture_judgment_and_it_passes(bundle, tmp_path, monkeypatch):
    """``l0_campaign.valid_row`` delegates capture evidence to ``_valid_capture_evidence``; spy on it."""
    calls, rlog = tmp_path / "calls", Rlog(SESSION)
    rt = System1Runtime(bundle, capture_dir=calls)
    _, session = _interleaved_session(rt, calls, rlog, "dictation", directive("do it"), "ok")
    archive = tmp_path / "archive"
    (archive / "workspace").mkdir(parents=True)
    log = tmp_path / "harness.log"
    log.write_text("x")
    model, task = l0_campaign.MODELS[0], l0_campaign.TASKS[0]
    manifest = {"campaign_id": "c", "revision": "r", "fleet_snapshot": {"f": 1}, "level": 0}
    row = {**_row(session, 2, {p: 1 for p in MODEL_PHASES}), "campaign_id": "c", "revision": "r",
           "code_revision": "r", "model": model, "task": task, "restored_fleet": True, "level": 0,
           "live_engagement_level": 0, "planner": "off", "planner_enabled": False, "planner_phase_count": 0,
           "pacing_policy": l0_campaign.POLICY, "fleet_snapshot": {"f": 1}, "archive": str(archive),
           "harness_log": str(log), "run_id": "run-1"}
    seen = []
    real = fresh_l5_campaign._valid_capture_evidence
    monkeypatch.setattr(fresh_l5_campaign, "_valid_capture_evidence",
                        lambda r, **kw: seen.append(real(r, **kw)) or seen[-1])
    try:
        l0_campaign.valid_row(row, manifest)
    except Exception:  # noqa: BLE001 — what the rest of the row check does is not this test's subject
        pass
    assert seen == [True]


# ---- the classifier's own records are complete, native and separate -------------------------------

@pytest.mark.parametrize("outcome", OUTCOMES)
def test_every_call_keeps_its_complete_native_input_and_output_without_a_fake_chat(bundle, tmp_path, outcome):
    calls, rlog = tmp_path / "calls", Rlog(SESSION)
    rt = System1Runtime(bundle, capture_dir=calls)
    state = brief("complete briefing text, nothing clipped")
    event, session = _interleaved_session(rt, calls, rlog, "retrospective", state, outcome)
    nodes = _record_nodes(event["capture"])
    rendered = _rendered(bundle, "retrospective", state)

    assert rendered in nodes and state in nodes                       # the complete input the model read
    assert {"messages", "choices", "body"}.isdisjoint(n for n in nodes if isinstance(n, str))  # no fake wire
    if outcome == "ok":
        judged = event
        assert judged["label"] in nodes and judged["logits"] in nodes  # the complete output
        assert list(rt.prepare("retrospective", state).input_ids) in nodes  # the exact token ids
    else:
        assert event["error"] in nodes and event["message"] in nodes   # the failure, verbatim
    # the path is the record's own, outside the upstream namespace the suite counts
    assert Path(event["capture"]).parent != session and Path(event["capture"]).parent.parent == session


def test_classifier_calls_emit_no_upstream_events_and_take_no_upstream_sequence_number(bundle, tmp_path):
    calls, rlog = tmp_path / "calls", Rlog(SESSION)
    rt = System1Runtime(bundle, capture_dir=calls)
    _interleaved_session(rt, calls, rlog, "retrospective", brief("x"), "ok")
    upstream = [(k, kw) for k, kw in rlog.events if k.startswith("upstream.")]
    assert [k for k, _ in upstream].count("upstream.dump") == 2          # the two LLM calls only
    assert [k for k, _ in upstream].count("upstream.response_dump") == 2
    assert not any("system1" in str(kw.get("path", "")) or "system1" in str(kw.get("phase", ""))
                   for _, kw in upstream)
    names = sorted(p.name for p in _session_dir(calls).glob("[0-9]*-*.json") if ".response." not in p.name)
    assert [re.match(r"\d+", n).group() for n in names] == ["0001", "0002"]   # no gap where a classifier call was


def test_a_restart_never_overwrites_an_upstream_or_classifier_record(bundle, tmp_path):
    calls, rlog = tmp_path / "calls", Rlog(SESSION)
    first = System1Runtime(bundle, capture_dir=calls)
    _, session = _interleaved_session(first, calls, rlog, "retrospective", brief("x"), "ok")
    before = {p: p.read_bytes() for p in session.rglob("*.json")}
    callcapture._seq.clear()  # a restarted process: in-memory counters are gone, the folder remains
    second = System1Runtime(bundle, capture_dir=calls)
    _interleaved_session(second, calls, Rlog(SESSION), "retrospective", brief("y"), "ok")
    assert all(p.read_bytes() == data for p, data in before.items())
    assert len(list(session.rglob("*.json"))) == 2 * len(before)


def test_capture_off_leaves_no_classifier_record_and_the_llm_evidence_stays_valid(bundle, tmp_path):
    calls, rlog = tmp_path / "calls", Rlog(SESSION)
    rt = System1Runtime(bundle)  # no capture_dir: [logging] capture_calls = false
    event, session = _interleaved_session(rt, calls, rlog, "dictation", directive("x"), "ok")
    assert event["capture"] is None
    assert not list(session.rglob("system1*")) and not list(session.glob("*/"))
    assert fresh_l5_campaign._valid_capture_evidence(_row(session, 2, {p: 1 for p in MODEL_PHASES})) is True


# ---- the real engines ---------------------------------------------------------------------------

@pytest.mark.skipif(not _real_engines(), reason="needs onnxruntime+tokenizers and the built System 1 bundle")
def test_real_cpu_calls_leave_the_suites_llm_evidence_intact(tmp_path):
    """Fresh process: the autouse fake engines of this module must not shadow the real modules."""
    code = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from cria import callcapture
from cria.system1 import System1Runtime
from suite import fresh_l5_campaign
from suite.run import capture_manifest, collect_capture
class R:
    session, turn = sys.argv[2], "t1"
    events = []
    def emit(self, kind, **kw): self.events.append((kind, kw))
def model(rlog, calls, phase):
    path = callcapture.capture({"messages": [{"role": "user", "content": phase}]}, rlog, calls_dir=calls, phase=phase)
    callcapture.capture_response(path, {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}, rlog)
calls, rlog = Path(sys.argv[1]), R()
rt = System1Runtime(sys.argv[4], capture_dir=calls)
model(rlog, calls, "coder")
judged = rt.judge_detailed("dictation", {"public_directive": "Run the failing test."}, rlog=rlog)
model(rlog, calls, "satisfaction")
session = calls / callcapture.session_dirname(sys.argv[2])
row = {"capture_dirs": [str(session)], "capture_dir": str(session), "calls": 2, "phases": {"coder": 1, "satisfaction": 1},
       "started": __import__("time").time() - 30, "wall_seconds": 3600, "capture_snapshot": capture_manifest([session])}
record = json.loads(Path(judged.capture_path).read_text())
print(json.dumps({"calls": collect_capture([session])["calls"], "valid": fresh_l5_campaign._valid_capture_evidence(row),
                  "input": judged.rendered_input == record["request"]["rendered_input"], "ids": list(judged.input_ids) == record["request"]["input_ids"],
                  "logits": list(judged.logits) == record["response"]["logits"]}))
"""
    import subprocess
    import sys
    repo = Path(__file__).resolve().parent.parent
    out = subprocess.run([sys.executable, "-c", code, str(tmp_path / "calls"), SESSION, str(repo), str(REAL_BUNDLE)],
                         cwd=repo, capture_output=True, text=True, check=True, timeout=300)
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {
        "calls": 2, "valid": True, "input": True, "ids": True, "logits": True}
