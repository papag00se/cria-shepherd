"""Fresh live coder pre-frame instrumentation, without replaying Feed evidence."""
import hashlib
import json
import tempfile
from pathlib import Path

from cria import loop, upstream, wsview
from cria.plan import Plan, PlanItem
from tests.wsfixture import survey


class _Log:
    session = "instrumented-session"
    turn = "turn-1"
    phase = "coder-s2"

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def test_preframe_capture_preserves_observed_state_and_final_wire_identity():
    """The pre-frame receipt records facts, not a synthetic absence or altered body."""
    root = "/workspace"
    view = wsview.View(root, "instrumented-session")
    assert wsview.apply_survey(view, survey("F\t1\t7\tsrc/Main.java", root=root))
    token = wsview.bind(view)
    try:
        sess = loop.PlanSession(plan=Plan(id="p", task="Build it.", created="now", items=[
            PlanItem("inspect source", done=True), PlanItem("implement the change"),
        ]), workspace_root=root, drive_count=12, last_gate_red=True, gate_stall=2,
            completion_remediation_subject="", completion_remediation_reason="",
            last_gap_subject="REVIEW.md", last_gap_observation="survey-generation")
        rlog = _Log()
        loop.record_coder_preframe(rlog, sess, PlanItem("implement the change"), 2, 2,
                                   driver="plan_on")

        initial = dict(rlog.coder_preframe)
        assert initial["wsview"] == {
            "root": root, "surveyed": True, "complete": True,
            "observation_fingerprint": view.observation_fingerprint,
        }
        assert initial["remediation"] == {"armed": False, "subject": None, "reason": None}
        assert initial["absence_verdict"] == {
            "diagnosis_kind": "missing_file", "subject": "REVIEW.md",
            "workspace_observation_fingerprint": "survey-generation",
        }
        assert initial["cursor"] == {"index": 2, "total": 2, "text": "implement the change"}
        assert initial["gate"]["last_gate_red"] is True
        assert any(kind == "loop.coder_preframe" for kind, _ in rlog.events)

        body = {"model": "m", "stream": False,
                "messages": [{"role": "user", "content": "unchanged"}]}
        with tempfile.TemporaryDirectory() as tmp:
            up = upstream.Upstream("http://unused", capture_dir=tmp, context_window=49152)
            raw, _estimate, capture_path = up._prep(body, False, rlog)
            assert json.loads(raw) == body  # instrumentation never enters or changes the wire body
            rec = json.loads(Path(capture_path).read_text())
            receipt = rec["coder_preframe"]
            assert receipt["state"] == initial
            assert receipt["final_wire"] == {
                "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            }
            serialized = [fields for kind, fields in rlog.events
                          if kind == "loop.coder_preframe_serialized"]
            assert serialized == [{"state": initial, "final_wire": receipt["final_wire"],
                                   "capture_path": capture_path}]
    finally:
        wsview.unbind(token)
