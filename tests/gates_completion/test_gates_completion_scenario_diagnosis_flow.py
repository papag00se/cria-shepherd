"""A missing required deliverable end to end: the scheduled observer finds REPORT.md absent on a real workspace, the
delivery arms a remediation and steers once, shell inspection does not retire it, only the correlated write does; the
terminal observer then stays silent. Plus the evidence-grounded (non-file) diagnosis kinds and the observer's refusals."""
import json
from types import SimpleNamespace

import pytest

from cria import completiondiagnosis as cd, loop
from gates_completion_helpers import Log, gates_completion_view  # noqa: F401

TASK = 'Implement the cart, then add `REPORT.md` describing remaining risks.'
G, R = cd.DiagnosisStatus, cd.RemediationStatus
SAYS_MISSING = json.dumps({"missing_file": True, "diagnosis_kind": "missing_file", "subject": "REPORT.md",
                           "task_quote": "add `REPORT.md` describing remaining risks.", "evidence_source": "workspace_absence"})
REQUIRED = json.dumps({"required_output": True, "subject": "REPORT.md", "task_quote": "add `REPORT.md` describing remaining risks."})


def fresh_state():
    return SimpleNamespace(completion_remediation_subject="", completion_remediation_reason="", completion_remediation_nonwrite_ids=(),
                           completion_remediation_nonwrite_seen=False, nudge_reason="", steer_source="", last_gap_named="",
                           last_gap_subject="", last_gap_observation=None, deliverable_observation_last_drive=-1)


class Flow:
    def __init__(self, root, judged=SAYS_MISSING):
        self.root, self.log, self.state, self.judged, self.fingerprint, self.judge_calls = root, Log(), fresh_state(), judged, "survey-1", 0
        self.asked = []

    def judge(self, system, user):
        self.judge_calls += 1
        if isinstance(self.judged, Exception):
            raise self.judged
        return self.judged

    def services(self):
        grounding = cd.GroundingServices(lambda s: loop._workspace_subject(str(self.root), s), loop._evidence_blocks, loop._fix_text,
                                         lambda *a: self.asked.append(a) or REQUIRED, self.log)
        observer = cd.ObservationServices(lambda: "inventory: src/cart.py", self.judge, lambda c: False, lambda c: c, lambda t: t,
                                          grounding, cd.DEFINITION.execute)
        delivery = cd.DeliveryServices(lambda: self.fingerprint, loop._clip, cd.DEFINITION.arm, self.log)
        return cd.ObservationLifecycleServices(observer, delivery, loop.periodic_check_due, cd.DEFINITION.observe, cd.DEFINITION.deliver)

    def scheduled(self, drive):
        return cd.observe_scheduled(cd.ScheduledObservationInput(TASK, drive, 4, 4, True), self.state, self.services())


def shell(ident, command, name="exec_command"):
    return {"id": ident, "function": {"name": name, "arguments": json.dumps({"cmd": command})}}


def test_a_missing_deliverable_is_observed_armed_survives_shell_inspection_and_settles_only_on_the_write(tmp_path):
    flow, svc = Flow(tmp_path), cd.RemediationServices(loop._write_path, lambda a, b: loop._same_workspace_path(a, b, str(tmp_path)),
                                                       loop._command_text, Flow(tmp_path).log)
    assert flow.scheduled(drive=3).diagnosis.status is G.NOT_APPLICABLE and flow.judge_calls == 0          # not yet due
    run = flow.scheduled(drive=4)
    assert run.diagnosis.status is G.GROUNDED and run.delivery.status is R.DELIVERED and flow.judge_calls == 1
    assert (flow.state.completion_remediation_subject, flow.state.steer_source) == ("REPORT.md", "deliverable observation")
    assert "REPORT.md" in flow.state.nudge_reason and flow.state.last_gap_subject == "REPORT.md"
    assert flow.scheduled(drive=9).diagnosis.status is G.NOT_APPLICABLE and flow.judge_calls == 1          # armed: observer stays out
    assert [n for n, _ in flow.log.events if n.startswith("loop.satisfaction")] == ["loop.satisfaction_gap_named"]

    coder = {"choices": [{"message": {"tool_calls": [shell("a", "ls -la && cat src/cart.py | head -5"), shell("b", "echo done > REPORT.md"),
                                                     shell("c", "ls && make build"), shell("d", "cd src && pwd"), shell("e", "cd /tmp")]}}]}
    assert cd.acknowledge_delivery(flow.state, coder, svc).status is R.ACKNOWLEDGED
    assert flow.state.completion_remediation_nonwrite_ids == ("a", "d")     # reads and inert prefixes only; a write or a build is not inspection
    flow.state.nudge_reason = "something else is steering"
    msgs = [{"role": "tool", "tool_call_id": "a", "content": "..."}]
    assert cd.follow_up_nonwrite(flow.state, msgs, svc).status is R.PENDING
    flow.state.nudge_reason = ""
    assert cd.follow_up_nonwrite(flow.state, msgs, svc).status is R.FOLLOW_UP and flow.state.steer_source.endswith("non-write follow-up")
    write = [{"role": "assistant", "tool_calls": [{"id": "w", "function": {"name": "write_file", "arguments": json.dumps({"path": "REPORT.md", "content": "x"})}}]},
             {"role": "tool", "tool_call_id": "w", "content": "Wrote REPORT.md"}]
    assert cd.settle_remediation(flow.state, write, svc).status is R.SETTLED
    assert flow.state.completion_remediation_subject == "" and cd.settle_remediation(flow.state, write, svc).status is R.NOT_APPLICABLE

    (tmp_path / "REPORT.md").write_text("risks\n")
    late = cd.observe_terminal(lambda: TASK, True, flow.services())                    # the file exists now: no gap is claimed
    assert (late.status, late.cause) == (G.WITHHELD, "file exists or workspace state is unknown")


def test_the_scheduled_observer_is_stamped_per_attempt_even_when_it_finds_nothing(tmp_path):
    flow = Flow(tmp_path, json.dumps({"missing_file": False}))
    assert [flow.scheduled(d).diagnosis.status for d in (4, 5, 7)] == [G.NOT_APPLICABLE] * 3 and flow.judge_calls == 1
    assert flow.scheduled(8).diagnosis.status is G.NOT_APPLICABLE and flow.judge_calls == 2          # next due drive, measured from the last attempt


@pytest.mark.parametrize("judged,present,status,cause", [
    (RuntimeError("boom"), False, G.WITHHELD, "observer unavailable"), ("not json", False, G.WITHHELD, "observer unreadable"),
    (json.dumps({"missing_file": False}), False, G.NOT_APPLICABLE, ""),
    (SAYS_MISSING, True, G.WITHHELD, "file exists or workspace state is unknown")])
def test_the_terminal_observer_is_silent_or_withheld_never_a_verdict(tmp_path, judged, present, status, cause):
    flow = Flow(tmp_path, judged)
    if present:
        (tmp_path / "REPORT.md").write_text("x")
    out = cd.observe_terminal(lambda: TASK, True, flow.services())
    assert (out.status, out.cause) == (status, cause) and flow.state.completion_remediation_subject == ""
    assert "loop.done_gap_observed" not in [n for n, _ in flow.log.events]


def test_a_found_absence_at_done_is_returned_with_its_event(tmp_path):
    flow = Flow(tmp_path)
    out = cd.observe_terminal(lambda: TASK, True, flow.services())
    assert out.status is G.GROUNDED and out.subject == "REPORT.md" and flow.state.nudge_reason == ""
    assert [e for e in flow.log.events if e[0] == "loop.done_gap_observed"][0][1]["subject"] == "REPORT.md"
    assert cd.observe_terminal(lambda: "", True, flow.services()).status is G.NOT_APPLICABLE


def test_a_scheduled_review_gap_repeats_only_when_a_fresh_survey_renewed_the_same_absence():
    state, log = fresh_state(), Log()
    svc = cd.DeliveryServices(lambda: obs[0], loop._clip, cd.DEFINITION.arm, log)
    gap = cd.DiagnosisResult(G.GROUNDED, "REPORT.md is missing", "write it", "missing_file", "REPORT.md")
    send = lambda: cd.deliver_gap(cd.DeliveryInput(gap, cd.DeliveryTrigger.SCHEDULED_REVIEW), state, svc).status
    obs = ["s1"]
    assert send() is R.DELIVERED
    state.nudge_reason = ""
    assert send() is R.NOT_APPLICABLE                                              # same words, same survey: no nagging
    obs[0] = "s2"
    assert send() is R.DELIVERED and [e[1]["rearmed"] for e in log.events if e[0] == "loop.satisfaction_gap_named"] == [False, True]
    state.nudge_reason = "parked"
    assert send() is R.NOT_APPLICABLE
    other = cd.DiagnosisResult(G.GROUNDED, "tests are weak", "", "other")
    assert cd.deliver_gap(cd.DeliveryInput(other, cd.DeliveryTrigger.DELIVERABLE_OBSERVATION), state, svc).status is R.NOT_APPLICABLE
    assert cd.deliver_gap(cd.DeliveryInput(cd.DiagnosisResult(G.WITHHELD), cd.DeliveryTrigger.SCHEDULED_REVIEW), state, svc).status is R.NOT_APPLICABLE


def grounded(obj, *, task=TASK, subject=("REPORT.md", False, None), answer="SUPPORTED.", log="ran pytest: FAILED test_cart", checks="1 failed"):
    base = {"diagnosis_kind": "failed_check", "subject": "", "task_quote": "Implement the cart", "evidence_source": "checks", "evidence_quote": "1 failed"}
    services = cd.GroundingServices(lambda s: subject, loop._evidence_blocks, loop._fix_text, (lambda *a: answer) if answer is not None else None, Log())
    return cd.ground_diagnosis(cd.DiagnosisInput(lambda: {**base, **obj}, task, log, checks, "no tests touched"), services)


@pytest.mark.parametrize("obj,kw,status,cause", [
    ({}, {}, G.GROUNDED, ""),
    ({"diagnosis_kind": "bogus"}, {}, G.WITHHELD, "unknown diagnosis kind"),
    ({"evidence_source": "vibes"}, {}, G.WITHHELD, "unknown evidence source"),
    ({"task_quote": "Implement the cart!!"}, {}, G.WITHHELD, "task quote is not exact"),
    ({"evidence_quote": "2 failed"}, {}, G.WITHHELD, "evidence quote is not exact"),
    ({}, {"answer": None}, G.WITHHELD, "semantic support unavailable"),
    ({}, {"answer": "unsupported, sorry"}, G.WITHHELD, "semantic support absent or undecidable"),
    ({"diagnosis_kind": "other", "evidence_source": "action_log", "evidence_quote": "FAILED test_cart"}, {}, G.GROUNDED, ""),
    ({"diagnosis_kind": "other", "evidence_source": "participation", "evidence_quote": "no tests touched"}, {}, G.GROUNDED, ""),
    ({"diagnosis_kind": "failed_check", "evidence_source": "action_log", "evidence_quote": "FAILED test_cart"}, {}, G.WITHHELD, "failed-check source contract"),
    ({"diagnosis_kind": "missing_content", "evidence_source": "checks", "subject": "src/cart.py"}, {}, G.WITHHELD, "missing-content source contract"),
    ({"diagnosis_kind": "missing_content", "evidence_source": "workspace_file", "subject": ""}, {}, G.WITHHELD, "missing-content has no workspace subject"),
    ({"diagnosis_kind": "missing_content", "evidence_source": "workspace_file", "subject": "src/cart.py", "evidence_quote": "def total"},
     {"subject": ("src/cart.py", True, "def total(): pass")}, G.GROUNDED, ""),
    ({"diagnosis_kind": "missing_content", "evidence_source": "workspace_file", "subject": "src/cart.py", "evidence_quote": "def total"},
     {"subject": ("src/cart.py", True, None)}, G.WITHHELD, "workspace file or complete content is unknown"),
    ({"diagnosis_kind": "other", "evidence_source": "workspace_absence", "subject": "REPORT.md", "task_quote": "add `REPORT.md` describing remaining risks."},
     {"subject": ("REPORT.md", False, None)}, G.GROUNDED, ""),                      # an absent, task-named file is re-typed to missing_file
    ({"diagnosis_kind": "missing_file", "evidence_source": "checks", "subject": "REPORT.md", "task_quote": "add `REPORT.md` describing remaining risks."},
     {}, G.WITHHELD, "missing-file source contract"),
    ({"diagnosis_kind": "missing_file", "evidence_source": "checks", "subject": "notes.txt", "task_quote": "Implement the cart"},
     {}, G.WITHHELD, "workspace subject is not task-named"),
    ({"diagnosis_kind": "other", "evidence_source": "workspace_absence", "subject": "x", "task_quote": "Implement the cart"}, {}, G.WITHHELD,
     "absence source is only valid for a missing file"),
], ids=lambda v: None)
def test_every_diagnosis_kind_is_grounded_in_its_own_source_or_withheld_with_a_reason(obj, kw, status, cause):
    out = grounded(obj, **kw)
    assert (out.status, out.cause) == (status, cause)
    assert bool(out.text) is (status is G.GROUNDED)


@pytest.mark.parametrize("quote,subject,ok", [
    ("add `REPORT.md` describing remaining risks.", "REPORT.md", True), ("add REPORT.md here", "REPORT.md", False),
    ('write "REPORT.md" now', "REPORT.md", False), ("Add REPORT.md.", "REPORT.md", False)])
def test_the_required_output_span_must_name_the_subject_as_the_task_wrote_it(quote, subject, ok):
    assert cd.required_output_span_names_subject(TASK, quote, subject) is ok
