"""Behavioral migration coverage; production selection/bypass remains primary-owned."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from cria import completiondiagnosis as policy, loop, prompts, wsview
from tests.test_negative_diagnosis_provenance import _diagnosis


class Log:
    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))


class Ask:
    def __init__(self, answer, composed=False):
        self.answer = answer
        self.calls = []
        self.composes_evidence = composed

    def __call__(self, *args):
        self.calls.append(args)
        return self.answer


def grounding(subject, ask, log):
    return policy.GroundingServices(subject, loop._evidence_blocks, loop._fix_text, ask, log)


TASK = "Add REPORT.md describing remaining risks."
ABSENT = ("REPORT.md", False, None)
REQUIRED = json.dumps({"required_output": True, "subject": "REPORT.md", "task_quote": TASK})


def event(name, **fields):
    return name, {"assist_id":"negative-completion-diagnosis", "family_id":"F36", **fields}


@pytest.mark.parametrize("kind,origin,quote,body,answer,expected,cause,question_kind,target_kind", [
    ("missing_file", "workspace_absence", "", ABSENT, REQUIRED, policy.DiagnosisStatus.GROUNDED, "", "requirement", "missing_file"),
    ("missing_file", "workspace_absence", "", ("REPORT.md", True, "risk"), REQUIRED, policy.DiagnosisStatus.WITHHELD, "file exists or workspace state is unknown", "none", ""),
    ("missing_file", "workspace_absence", "", ("", None, None), REQUIRED, policy.DiagnosisStatus.WITHHELD, "file exists or workspace state is unknown", "none", ""),
    ("missing_file", "workspace_absence", "", ABSENT, "SUPPORTED", policy.DiagnosisStatus.WITHHELD, "required-output grounding unsupported", "requirement", ""),
    ("missing_content", "workspace_file", "risk", ("REPORT.md", True, "risk"), "SUPPORTED", policy.DiagnosisStatus.GROUNDED, "", "support-file", ""),
    ("missing_content", "workspace_file", "risk", ("REPORT.md", True, "risk"), "UNSUPPORTED", policy.DiagnosisStatus.WITHHELD, "semantic support absent or undecidable", "support-file", ""),
    ("missing_content", "workspace_file", "risk", ("REPORT.md", True, None), "SUPPORTED", policy.DiagnosisStatus.WITHHELD, "workspace file or complete content is unknown", "none", ""),
    ("missing_content", "action_log", "risk", ABSENT, "SUPPORTED", policy.DiagnosisStatus.WITHHELD, "missing-content source contract", "none", ""),
    ("other", "participation", "risk", ABSENT, "SUPPORTED", policy.DiagnosisStatus.GROUNDED, "", "support", ""),
    ("failed_check", "checks", "risk", ABSENT, "SUPPORTED", policy.DiagnosisStatus.GROUNDED, "", "support", ""),
    ("other", "action_log", "risk", ABSENT, "UNDECIDABLE", policy.DiagnosisStatus.WITHHELD, "semantic support absent or undecidable", "support", ""),
    ("other", "action_log", "invented", ABSENT, "SUPPORTED", policy.DiagnosisStatus.WITHHELD, "evidence quote is not exact", "none", ""),
    ("other", "workspace_absence", "", ABSENT, "unused", policy.DiagnosisStatus.GROUNDED, "", "none", "absent_named_file"),
    ("invalid", "checks", "risk", ABSENT, "unused", policy.DiagnosisStatus.WITHHELD, "unknown diagnosis kind", "none", ""),
])
def test_grounding_matches_current_owner(kind, origin, quote, body, answer, expected,cause,question_kind,target_kind):
    # Keep the canonical regression symbol, not its former executable oracle.
    obj = _diagnosis(kind, task_quote=TASK, subject="REPORT.md", source=origin, evidence_quote=quote)
    question, log = Ask(answer, composed=True), Log()
    result = policy.DEFINITION.execute(
        policy.DiagnosisInput(lambda: obj, TASK, "risk", "risk", "risk", phase="test"),
        grounding(lambda subject: body, question, log))
    assert result.status is expected and result.cause == cause
    evidence = action = ""
    if expected is policy.DiagnosisStatus.GROUNDED:
        evidence = prompts.render("negative_diagnosis", task_quote=TASK, source=origin,
            evidence=prompts.render("negative_diagnosis_missing_file",subject="REPORT.md") if target_kind else "risk").strip()
        action = TASK
    assert (result.evidence,result.action,result.diagnosis_kind,result.subject) == (
        evidence,action,target_kind,"REPORT.md" if target_kind else "")
    assert result.text == (evidence + "\n" + prompts.render("verdict_nudge_action",action=TASK) if action else "")
    expected_calls = []
    if question_kind == "requirement":
        expected_calls = [(prompts.render("missing_output_requirement",task=TASK,subject="REPORT.md"),)]
    elif question_kind in ("support", "support-file"):
        expected_calls = [(prompts.render("negative_diagnosis_support",diagnosis_kind=kind,subject="REPORT.md",
            task_quote=TASK,evidence_source=origin,evidence_quote=quote,
            diagnosis="the provider's untrusted diagnosis",proposed_fix="the provider's untrusted fix",
            workspace_facts=prompts.render("negative_diagnosis_existing_file",subject="REPORT.md") if question_kind == "support-file" else "(none available)",
            checks="risk",participation="risk",action_log=prompts.load("negative_diagnosis_log_above")),["risk"])]
    assert question.calls == expected_calls
    events = []
    if target_kind == "absent_named_file":
        events.append(event("loop.negative_diagnosis_canonicalised",level="info",phase="test",
                            was="other",now="missing_file",subject="REPORT.md"))
    events.append(event("loop.negative_diagnosis_supported",level="info",phase="test",
                        diagnosis_kind="missing_file" if target_kind == "absent_named_file" else kind,evidence_source=origin)
                  if expected is policy.DiagnosisStatus.GROUNDED else
                  event("loop.negative_diagnosis_suppressed",level="info",phase="test",cause=cause,diagnosis_kind=kind))
    assert log.events == events


@pytest.mark.parametrize("complete", [True, False])
def test_remote_workspace_unknown_is_not_an_absence(complete):
    from tests.wsfixture import survey
    root = "/remote/diagnosis"
    view = wsview.View(root, "diagnosis-source")
    assert wsview.apply_survey(view, survey("F\t1\t1\tREADME.md", root=root, complete=complete))
    token = wsview.bind(view)
    try:
        question = Ask(REQUIRED)
        services = grounding(lambda subject: loop._workspace_subject(root, subject), question, None)
        source = policy.DiagnosisInput(lambda: _diagnosis("missing_file", task_quote=TASK, subject="REPORT.md", source="workspace_absence"), TASK)
        out = policy.DEFINITION.execute(source, services)
        assert out.status is (policy.DiagnosisStatus.GROUNDED if complete else policy.DiagnosisStatus.WITHHELD)
        assert len(question.calls) == int(complete)
        assert out.subject == ("REPORT.md" if complete else "")
    finally:
        wsview.unbind(token)


def test_required_output_rechecks_identity_after_question():
    replies = iter([ABSENT, ("other/REPORT.md", False, None)])
    question = Ask(REQUIRED)
    result = policy.ground_diagnosis(
        policy.DiagnosisInput(lambda: _diagnosis("missing_file", task_quote=TASK, subject="REPORT.md", source="workspace_absence"), TASK),
        grounding(lambda subject: next(replies), question, None))
    assert result.status is policy.DiagnosisStatus.WITHHELD
    assert len(question.calls) == 1
    assert not result.text


@pytest.mark.parametrize("authority", ["Read REPORT.md as input.", "", "Add REPORT.md.bak."])
def test_generated_step_cannot_replace_original_requirement(authority):
    question = Ask(REQUIRED)
    result = policy.ground_diagnosis(
        policy.DiagnosisInput(lambda: _diagnosis("missing_file", task_quote=TASK, subject="REPORT.md", source="workspace_absence"),
                              TASK, original_task=authority), grounding(lambda subject: ABSENT, question, None))
    assert result.status is policy.DiagnosisStatus.WITHHELD
    if authority:
        assert authority in question.calls[0][0]
    else:
        assert not question.calls


@pytest.mark.parametrize("task,quote,subject,expected", [
    ("Add `REPORT.md`.", "Add `REPORT.md`.", "REPORT.md", True),
    ("Add REPORT.md.bak.", "Add REPORT.md", "REPORT.md", False),
    ("Add `REPORT.md.bak`.", "Add `REPORT.md", "REPORT.md", False),
    ("Add 'space report.md'.", "Add 'space report.md'.", "space report.md", True),
    ("Read `REPORT.md` and add result.", "Read `REPORT.md`", "REPORT.md", True),
])
def test_source_literal_boundary_matches_existing_parser(task, quote, subject, expected):
    assert policy.required_output_span_names_subject(task, quote, subject) is expected


def state():
    return SimpleNamespace(completion_remediation_subject="", completion_remediation_reason="",
                           completion_remediation_nonwrite_ids=(), completion_remediation_nonwrite_seen=False,
                           nudge_reason="", steer_source="", workspace_root="/workspace")


def remediation(log=None):
    return policy.RemediationServices(loop._write_path, lambda a,b: loop._same_workspace_path(a,b,"/workspace"),
                                      loop._command_text, log)


def call(ident, name="write_file", **args):
    return {"id":ident, "function":{"name":name, "arguments":json.dumps(args)}}


def result(ident, text="ok"):
    return {"role":"tool", "tool_call_id":ident, "content":text}


def test_remediation_lifecycle_matches_current_owner():
    # Independent snapshots preserve durable vs transient state semantics.
    new, log = state(), Log()
    new.completion_remediation_nonwrite_ids = ("previous-ack",)
    new.completion_remediation_nonwrite_seen = True
    services = remediation(log)
    outcome = policy.DEFINITION.arm(new, "REPORT.md", "grounded task quote")
    assert outcome == policy.RemediationResult(policy.RemediationStatus.PENDING,"REPORT.md","grounded task quote")
    snapshot = {"completion_remediation_subject":"REPORT.md", "completion_remediation_reason":"grounded task quote",
                "completion_remediation_nonwrite_ids":(), "completion_remediation_nonwrite_seen":False,
                "nudge_reason":"", "steer_source":"", "workspace_root":"/workspace"}
    assert vars(new) == snapshot and log.events == []
    coder = {"choices":[{"message":{"tool_calls":[call("read", "read_file", path="README.md"),
                                                      call("unknown", "python", path="other"),
                                                      call("write", path="REPORT.md", content="text")]}}]}
    assert policy.DEFINITION.acknowledge(new,coder,services) == policy.RemediationResult(
        policy.RemediationStatus.ACKNOWLEDGED,"REPORT.md","grounded task quote")
    snapshot["completion_remediation_nonwrite_ids"] = ("read",)
    assert vars(new) == snapshot and log.events == []
    pending = policy.RemediationResult(policy.RemediationStatus.PENDING,"REPORT.md","grounded task quote")
    assert policy.DEFINITION.follow_up(new,[result("unrelated")],services) == pending
    assert vars(new) == snapshot and log.events == []
    follow_up = prompts.load("completion_remediation_nonwrite")
    assert policy.DEFINITION.follow_up(new,[result("read")],services) == policy.RemediationResult(
        policy.RemediationStatus.FOLLOW_UP,"REPORT.md",follow_up)
    snapshot.update(completion_remediation_nonwrite_seen=True,nudge_reason=follow_up,
                    steer_source="completion remediation non-write follow-up")
    events = [event("loop.completion_remediation_nonwrite",subject="REPORT.md")]
    assert vars(new) == snapshot and log.events == events
    assert policy.DEFINITION.follow_up(new,[result("read")],services) == pending
    assert vars(new) == snapshot and log.events == events  # exactly one follow-up, never settlement
    messages = [{"role":"assistant", "tool_calls":[call("w", path="./REPORT.md", content="text")]}]
    for tail in ([], [result("w", "permission denied")], [result("different", "Wrote ./REPORT.md")]):
        assert policy.DEFINITION.settle(new,messages+tail,services) == pending
        assert vars(new) == snapshot and log.events == events
    outcome = policy.DEFINITION.settle(new,messages+[result("w","Wrote ./REPORT.md")],services)
    assert outcome == policy.RemediationResult(policy.RemediationStatus.SETTLED,"REPORT.md")
    snapshot.update(completion_remediation_subject="",completion_remediation_reason="",
                    completion_remediation_nonwrite_ids=(),completion_remediation_nonwrite_seen=False)
    assert vars(new) == snapshot  # settlement does not erase the current steer/nudge
    assert log.events == events + [event("loop.completion_remediation_written",subject="REPORT.md")]


@pytest.mark.parametrize("name,path,reply_id,text,status", [
    ("write_file","REPORT.md","w","permission denied","PENDING"),
    ("write_file","REPORT.md","w","[write refused]","PENDING"),
    ("write_file","REPORT.md","w","ok","PENDING"),
    ("write_file","REPORT.md","other","Wrote REPORT.md","PENDING"),
    ("write_file","OTHER.md","w","Wrote OTHER.md","PENDING"),
    ("read_file","REPORT.md","w","Wrote REPORT.md","PENDING"),
    ("write_file","./REPORT.md","w","Wrote ./REPORT.md","SETTLED"),
])
def test_only_correlated_same_subject_successful_write_settles(name,path,reply_id,text,status):
    pending, log = state(), Log()
    policy.DEFINITION.arm(pending,"REPORT.md","grounded task quote")
    before = vars(pending).copy()
    messages = [{"role":"assistant","tool_calls":[call("w",name,path=path,content="text")]},result(reply_id,text)]
    outcome = policy.DEFINITION.settle(pending,messages,remediation(log))
    assert outcome == policy.RemediationResult(policy.RemediationStatus[status],"REPORT.md",
                                              "" if status == "SETTLED" else "grounded task quote")
    if status == "SETTLED":
        before.update(completion_remediation_subject="",completion_remediation_reason="")
    assert vars(pending) == before
    assert log.events == ([event("loop.completion_remediation_written",subject="REPORT.md")] if status == "SETTLED" else [])


@pytest.mark.parametrize("name,args,expected", [
    ("read_file", {"path":"x"}, True),
    ("read_file_and_write", {}, False),
    ("read_mcp_resource", {}, False),
    ("exec_command", {"cmd":"cd /workspace && ls -la && head -20 README.md"}, True),
    ("exec_command", {"cmd":"rm -f REPORT.md"}, False),
    ("exec_command", {"cmd":"python helper.py"}, False),
    ("exec_command", {"cmd":"echo nothing"}, False),
])
def test_supported_inspection_matches_current_boundary(name, args, expected):
    function = call("i", name, **args)["function"]
    assert policy.supported_inspection(function, remediation()) is expected
    # Literal allow/deny rows above are the oracle; no old policy is executed.


@pytest.mark.parametrize("answer,status", [(False, policy.DiagnosisStatus.NOT_APPLICABLE),
                                          (True, policy.DiagnosisStatus.GROUNDED),
                                          (None, policy.DiagnosisStatus.WITHHELD)])
def test_observer_composes_real_inventory_and_reuses_grounding(answer, status):
    obj = _diagnosis("missing_file", task_quote=TASK, subject="REPORT.md", source="workspace_absence")
    obj["missing_file"] = answer
    raw = "not JSON" if answer is None else json.dumps(obj)
    question = Ask(REQUIRED)
    observed = []
    services = policy.ObservationServices(
        lambda: "complete inventory: README.md", lambda system,user: observed.append((system,user)) or raw,
        lambda completion: False, lambda completion: completion, lambda text: text,
        grounding(lambda subject: ABSENT, question, Log()),execute=policy.DEFINITION.execute)
    out = policy.DEFINITION.observe(policy.ObservationInput(TASK, True), services)
    assert out.status is status
    assert len(observed) == 1
    assert "complete inventory: README.md" in observed[0][1]
    assert len(question.calls) == (1 if answer else 0)
    if answer:
        assert out.subject == "REPORT.md"
        assert out.action == TASK
        assert obj["proposed_fix"] not in out.text


def test_observer_truncation_and_failure_never_deliver_or_ask_requirement():
    question = Ask(REQUIRED)
    log = Log()
    services = policy.ObservationServices(
        lambda: "complete inventory", lambda system,user: "cut", lambda completion: True,
        lambda completion: pytest.fail("truncated answer was read"), lambda text:text,
        grounding(lambda subject: ABSENT, question, log),execute=policy.DEFINITION.execute)
    assert policy.observe_missing_file(policy.ObservationInput(TASK, True), services).status is policy.DiagnosisStatus.WITHHELD
    def failed(*args):
        raise RuntimeError("critic unavailable")
    assert policy.observe_missing_file(policy.ObservationInput(TASK, True), replace(services, judge=failed)).status is policy.DiagnosisStatus.WITHHELD
    assert not question.calls
    assert [name for name,_ in log.events] == ["loop.deliverable_observation_truncated", "loop.deliverable_observation_error"]


def gap_state():
    session = state()
    session.last_gap_named = session.last_gap_subject = session.last_gap_observation = ""
    return session


def grounded_gap(kind="missing_file"):
    return policy.DiagnosisResult(policy.DiagnosisStatus.GROUNDED, "exact quote and measured absence", TASK, kind, "REPORT.md")


def test_scheduled_delivery_repeats_only_on_renewed_complete_observation():
    session = gap_state()
    log = Log()
    services = policy.DeliveryServices(lambda: "generation-1", lambda value,limit: value[:limit],arm=policy.DEFINITION.arm,log=log)
    source = policy.DeliveryInput(grounded_gap(), policy.DeliveryTrigger.SCHEDULED_REVIEW)
    assert policy.DEFINITION.deliver(source, session, services).status is policy.RemediationStatus.DELIVERED
    assert session.completion_remediation_subject == "REPORT.md"
    assert TASK in session.completion_remediation_reason
    assert "Create REPORT.md now." in session.nudge_reason
    session.nudge_reason = ""
    assert policy.deliver_gap(source, session, services).status is policy.RemediationStatus.NOT_APPLICABLE
    assert policy.deliver_gap(source, session, replace(services, observation=lambda: None)).status is policy.RemediationStatus.NOT_APPLICABLE
    assert policy.deliver_gap(source, session, replace(services, observation=lambda: "generation-2")).status is policy.RemediationStatus.DELIVERED
    assert log.events[-1][1]["rearmed"] is True
    assert len(log.events) == 2


def test_observed_output_can_replace_ordinary_steer_but_retyped_input_cannot_arm():
    session = gap_state()
    session.nudge_reason = "ordinary steer"
    services = policy.DeliveryServices(lambda: "generation-1", lambda value,limit: value[:limit],arm=policy.DEFINITION.arm)
    source = policy.DeliveryInput(grounded_gap("absent_named_file"), policy.DeliveryTrigger.DELIVERABLE_OBSERVATION)
    assert policy.deliver_gap(source, session, services).status is policy.RemediationStatus.NOT_APPLICABLE
    assert session.nudge_reason == "ordinary steer"
    source = replace(source, diagnosis=grounded_gap())
    assert policy.deliver_gap(source, session, services).status is policy.RemediationStatus.DELIVERED
    assert session.steer_source == "deliverable observation"
    assert session.completion_remediation_subject == "REPORT.md"
    session = gap_state()
    source = replace(source, trigger=policy.DeliveryTrigger.SCHEDULED_REVIEW, plan_off=True)
    assert policy.deliver_gap(source, session, services).status is policy.RemediationStatus.DELIVERED
    assert not session.completion_remediation_subject


def test_withheld_diagnosis_does_not_measure_or_modify_pending_state():
    session = gap_state()
    before = dict(vars(session))
    def forbidden(*args):
        raise AssertionError("withheld diagnosis cannot gather")
    services = policy.DeliveryServices(forbidden, forbidden,arm=policy.DEFINITION.arm)
    source = policy.DeliveryInput(policy.DiagnosisResult(policy.DiagnosisStatus.WITHHELD), policy.DeliveryTrigger.SCHEDULED_REVIEW)
    assert policy.deliver_gap(source, session, services).status is policy.RemediationStatus.NOT_APPLICABLE
    assert vars(session) == before


def test_withheld_guidance_cannot_approve_a_held_task_review():
    from cria.completionreview import ReviewInput, ReviewTrigger, review_task
    session = SimpleNamespace(latest_satisfaction=None, latest_satisfaction_evidence="",
                              pending_done="old success", pending_done_parts=("old success",))
    guidance = policy.ground_diagnosis(
        policy.DiagnosisInput(lambda: {}, TASK), grounding(lambda subject: ABSENT, Ask("unused"), None))
    assert guidance.status is policy.DiagnosisStatus.NOT_APPLICABLE
    out = review_task(ReviewInput(ReviewTrigger.CLAIM, TASK, lambda: "history", lambda: "checks",
                                  lambda task,evidence: (False, guidance.text, guidance.action), lambda: "", Log()), session)
    assert not out.approved
    assert session.latest_satisfaction is False
    assert not session.pending_done
    assert not session.pending_done_parts


def test_unavailable_observer_does_not_gather_inventory():
    def forbidden(*args):
        raise AssertionError("observer unavailable")
    services = policy.ObservationServices(forbidden, forbidden, forbidden, forbidden, forbidden,
                                           grounding(forbidden, None, None),execute=policy.DEFINITION.execute)
    assert policy.observe_missing_file(policy.ObservationInput(TASK, False), services).status is policy.DiagnosisStatus.NOT_APPLICABLE
    assert policy.observe_missing_file(policy.ObservationInput("", True), services).status is policy.DiagnosisStatus.NOT_APPLICABLE


def lifecycle(session, *, fingerprint="generation-1", due=True, root=TASK):
    obj = _diagnosis("missing_file", task_quote=root, subject="REPORT.md", source="workspace_absence")
    obj["missing_file"] = True
    question = Ask(json.dumps({"required_output":True, "subject":"REPORT.md", "task_quote":root}))
    log = Log()
    calls = []
    observer = policy.ObservationServices(
        lambda: "complete inventory", lambda system,user: calls.append((session.deliverable_observation_last_drive, user)) or json.dumps(obj),
        lambda value:False, lambda value:value, lambda value:value, grounding(lambda subject:ABSENT, question, log),
        execute=policy.DEFINITION.execute)
    delivery = policy.DeliveryServices(lambda:fingerprint, lambda value,limit:value[:limit],arm=policy.DEFINITION.arm,log=log)
    return policy.ObservationLifecycleServices(observer, delivery, lambda *args:due,
        observe=policy.DEFINITION.observe,deliver=policy.DEFINITION.deliver), calls, question


def test_scheduled_observer_owns_stamp_before_question_and_target_delivery():
    session = gap_state()
    session.deliverable_observation_last_drive = 0
    services, calls, question = lifecycle(session)
    out = policy.DEFINITION.observe_scheduled(policy.ScheduledObservationInput(TASK, 40, 1, 1, True), session, services)
    assert out.diagnosis.status is policy.DiagnosisStatus.GROUNDED
    assert out.delivery.status is policy.RemediationStatus.DELIVERED
    assert calls[0][0] == 40
    assert len(calls) == len(question.calls) == 1
    assert session.completion_remediation_subject == "REPORT.md"
    assert not hasattr(session, "latest_satisfaction")


@pytest.mark.parametrize("pending,due,fingerprint", [(True, True, "current"), (False, False, "current"), (False, True, None)])
def test_scheduled_observer_pending_and_unknown_survey_are_silent(pending, due, fingerprint):
    session = gap_state()
    session.deliverable_observation_last_drive = 0
    if pending:
        policy.arm_remediation(session, "REPORT.md", "already pending")
    services, calls, question = lifecycle(session, due=due, fingerprint=fingerprint)
    before = dict(vars(session))
    out = policy.observe_scheduled(policy.ScheduledObservationInput(TASK, 40, 1, 1, True), session, services)
    assert out.diagnosis.status is policy.DiagnosisStatus.NOT_APPLICABLE
    assert vars(session) == before
    assert not calls and not question.calls


def test_terminal_observer_uses_only_retained_root_and_does_not_arm_or_stamp():
    session = gap_state()
    session.deliverable_observation_last_drive = 7
    services, calls, question = lifecycle(session)
    before = dict(vars(session))
    out = policy.DEFINITION.observe_terminal(lambda:TASK, True, services)
    assert out.diagnosis_kind == "missing_file"
    assert out.subject == "REPORT.md"
    assert vars(session) == before
    assert len(calls) == len(question.calls) == 1
    assert TASK in calls[0][1]
    assert services.observer.grounding.log.events[-1][0] == "loop.done_gap_observed"
    services, calls, question = lifecycle(session, root="")
    assert policy.observe_terminal(lambda:"", True, services).status is policy.DiagnosisStatus.NOT_APPLICABLE
    assert not calls and not question.calls


def test_unarmed_state_does_not_detect_calls_or_settle():
    def forbidden(*args):
        raise AssertionError("no active remediation")
    services = policy.RemediationServices(forbidden, forbidden, forbidden)
    session = state()
    assert policy.acknowledge_delivery(session, {"choices":[{"message":{"tool_calls":[call("x")]}}]}, services).status is policy.RemediationStatus.NOT_APPLICABLE
    assert policy.follow_up_nonwrite(session, [result("x")], services).status is policy.RemediationStatus.NOT_APPLICABLE
    assert policy.settle_remediation(session, [], services).status is policy.RemediationStatus.NOT_APPLICABLE
    assert vars(session) == vars(state())


def composed_services(session, definition):
    """Structural witness works before the required constructor fields exist."""
    base, calls, question = lifecycle(session)
    observer = SimpleNamespace(**{**vars(base.observer), "execute":definition.execute})
    delivery = SimpleNamespace(**{**vars(base.delivery), "arm":definition.arm})
    services = SimpleNamespace(observer=observer,delivery=delivery,due=base.due,
                               observe=definition.observe,deliver=definition.deliver)
    assert services.observer.execute is definition.execute
    assert services.delivery.arm is definition.arm
    assert services.observe is definition.observe and services.deliver is definition.deliver
    return services,calls,question


@pytest.mark.parametrize("edge", ["observe-execute","deliver-arm","scheduled-observe","scheduled-deliver","terminal-observe"])
def test_nested_composition_uses_exact_partial_replacement(edge):
    session = gap_state()
    session.deliverable_observation_last_drive = 7
    seen = []
    withheld = policy.DiagnosisResult(policy.DiagnosisStatus.WITHHELD,"misleading",TASK,"missing_file","REPORT.md")
    declined = policy.RemediationResult(policy.RemediationStatus.NOT_APPLICABLE)
    def replacement(*args):
        seen.append(args)
        return declined if edge in ("deliver-arm","scheduled-deliver") else withheld
    hook = {"observe-execute":"execute","deliver-arm":"arm","scheduled-observe":"observe",
            "scheduled-deliver":"deliver","terminal-observe":"observe"}[edge]
    definition = replace(policy.DEFINITION,**{hook:replacement})
    services,calls,question = composed_services(session,definition)
    before = vars(session).copy()
    if edge == "observe-execute":
        out = definition.observe(policy.ObservationInput(TASK,True),services.observer)
        assert out is withheld
    elif edge == "deliver-arm":
        out = definition.deliver(policy.DeliveryInput(grounded_gap(),policy.DeliveryTrigger.SCHEDULED_REVIEW),session,services.delivery)
        assert out is declined
    elif edge.startswith("scheduled"):
        out = definition.observe_scheduled(policy.ScheduledObservationInput(TASK,40,1,1,True),session,services)
        assert out.delivery.status is policy.RemediationStatus.NOT_APPLICABLE
        before["deliverable_observation_last_drive"] = 40
    else:
        out = definition.observe_terminal(lambda:TASK,True,services)
        assert out.status is policy.DiagnosisStatus.WITHHELD and not out.text
    assert len(seen) == 1
    assert vars(session) == before
    assert not any(name in ("loop.satisfaction_gap_named","loop.done_gap_observed")
                   for name,_ in services.observer.grounding.log.events)


EDGES = ("observe-execute","deliver-arm","scheduled-observe","scheduled-deliver","terminal-observe")


def invoke_nested(edge,session,definition,services):
    if edge == "observe-execute":
        return definition.observe(policy.ObservationInput(TASK,True),services.observer)
    if edge == "deliver-arm":
        return definition.deliver(policy.DeliveryInput(grounded_gap(),policy.DeliveryTrigger.SCHEDULED_REVIEW),session,services.delivery)
    if edge.startswith("scheduled"):
        return definition.observe_scheduled(policy.ScheduledObservationInput(TASK,40,1,1,True),session,services)
    return definition.observe_terminal(lambda:TASK,True,services)


@pytest.mark.parametrize("edge", EDGES)
@pytest.mark.parametrize("fault", ["none","mapping","wrong-result","string-status","foreign-status"])
def test_nested_results_are_validated_before_consumption(edge,fault):
    diagnosis_edge = edge in ("observe-execute","scheduled-observe","terminal-observe")
    cls = policy.DiagnosisResult if diagnosis_edge else policy.RemediationResult
    wrong_cls = policy.RemediationResult if diagnosis_edge else policy.DiagnosisResult
    wrong_status = policy.RemediationStatus.PENDING if diagnosis_edge else policy.DiagnosisStatus.GROUNDED
    values = {"none":None,"mapping":{"status":"grounded"},"wrong-result":wrong_cls(wrong_status),
              "string-status":cls("grounded"),"foreign-status":cls(wrong_status)}
    seen = []
    def replacement(*args):
        seen.append(args)
        return values[fault]
    definition = replace(policy.DEFINITION,**{edge.rsplit("-",1)[1]:replacement})
    session = gap_state()
    session.deliverable_observation_last_drive = 7
    services,calls,question = composed_services(session,definition)
    before = vars(session).copy()
    if edge.startswith("scheduled"):
        before["deliverable_observation_last_drive"] = 40
    with pytest.raises(ValueError if fault.endswith("status") else TypeError):
        invoke_nested(edge,session,definition,services)
    assert len(seen) == 1 and vars(session) == before
    assert not any(name in ("loop.satisfaction_gap_named","loop.done_gap_observed")
                   for name,_ in services.observer.grounding.log.events)


@pytest.mark.parametrize("edge,status", [
    ("deliver-arm",policy.RemediationStatus.ACKNOWLEDGED),("deliver-arm",policy.RemediationStatus.FOLLOW_UP),
    ("deliver-arm",policy.RemediationStatus.SETTLED),("deliver-arm",policy.RemediationStatus.DELIVERED),
    ("scheduled-deliver",policy.RemediationStatus.PENDING),("scheduled-deliver",policy.RemediationStatus.ACKNOWLEDGED),
    ("scheduled-deliver",policy.RemediationStatus.FOLLOW_UP),("scheduled-deliver",policy.RemediationStatus.SETTLED),
])
def test_nested_remediation_rejects_wrong_stage_status(edge,status):
    definition = replace(policy.DEFINITION,**{edge.rsplit("-",1)[1]:lambda *args:policy.RemediationResult(status)})
    session = gap_state()
    session.deliverable_observation_last_drive = 7
    services,_,_ = composed_services(session,definition)
    before = vars(session).copy()
    if edge.startswith("scheduled"):
        before["deliverable_observation_last_drive"] = 40
    with pytest.raises(ValueError,match="invalid status"):
        invoke_nested(edge,session,definition,services)
    assert vars(session) == before


@pytest.mark.parametrize("status", [policy.DiagnosisStatus.WITHHELD,policy.DiagnosisStatus.NOT_APPLICABLE])
@pytest.mark.parametrize("edge", ["observe-execute","scheduled-observe","terminal-observe"])
def test_non_grounded_nested_payload_cannot_promote_or_deliver(edge,status):
    gap = policy.DiagnosisResult(status,"misleading positive",TASK,"missing_file","REPORT.md")
    def forbidden(*args):
        raise AssertionError("non-grounded payload reached delivery")
    definition = replace(policy.DEFINITION,**{edge.rsplit("-",1)[1]:lambda *args:gap},deliver=forbidden)
    session = gap_state()
    session.deliverable_observation_last_drive = 7
    services,_,_ = composed_services(session,definition)
    before = vars(session).copy()
    out = invoke_nested(edge,session,definition,services)
    if edge == "scheduled-observe":
        assert out.diagnosis is gap and out.delivery.status is policy.RemediationStatus.NOT_APPLICABLE
        before["deliverable_observation_last_drive"] = 40
    else:
        assert out.status is status
    assert vars(session) == before
    assert services.observer.grounding.log.events == []


@pytest.mark.parametrize("trigger", list(policy.DeliveryTrigger))
@pytest.mark.parametrize("arm_status", [policy.RemediationStatus.PENDING,policy.RemediationStatus.NOT_APPLICABLE])
def test_arm_precedes_delivery_state_commit_and_decline_leaves_no_delivery(trigger,arm_status):
    session = gap_state()
    session.last_gap_named = "previous gap"
    session.last_gap_subject = "OTHER.md"
    session.last_gap_observation = "generation-0"
    session.steer_source = "previous steer"
    if trigger is policy.DeliveryTrigger.DELIVERABLE_OBSERVATION:
        session.nudge_reason = "ordinary steer"
    before = vars(session).copy()
    seen = []
    def arm(actual,subject,reason):
        assert actual is session and vars(actual) == before
        seen.append((subject,reason))
        return policy.RemediationResult(arm_status,subject,reason)
    definition = replace(policy.DEFINITION,arm=arm)
    services,_,_ = composed_services(session,definition)
    out = definition.deliver(policy.DeliveryInput(grounded_gap(),trigger),session,services.delivery)
    text = "exact quote and measured absence\n" + prompts.render("verdict_nudge_action",action=TASK)
    nudge = prompts.render("periodic_missing_file_gap",reason=text,subject="REPORT.md")
    assert seen == [("REPORT.md",nudge)]
    assert out.status is (policy.RemediationStatus.DELIVERED if arm_status is policy.RemediationStatus.PENDING else policy.RemediationStatus.NOT_APPLICABLE)
    if arm_status is policy.RemediationStatus.NOT_APPLICABLE:
        assert vars(session) == before and services.delivery.log.events == []
    else:
        assert session.last_gap_named == text and session.nudge_reason == nudge
        assert not session.completion_remediation_subject  # custom arm owns its own state writes
        assert len(services.delivery.log.events) == 1


def test_scheduled_declined_arm_consumes_attempt_cadence_only():
    seen = []
    def decline(session,subject,reason):
        seen.append((session.deliverable_observation_last_drive,subject))
        return policy.RemediationResult(policy.RemediationStatus.NOT_APPLICABLE)
    definition = replace(policy.DEFINITION,arm=decline)
    session = gap_state()
    session.deliverable_observation_last_drive = 7
    services,calls,question = composed_services(session,definition)
    before = vars(session).copy()
    out = invoke_nested("scheduled-observe",session,definition,services)
    before["deliverable_observation_last_drive"] = 40
    assert vars(session) == before and seen == [(40,"REPORT.md")]
    assert out.diagnosis.status is policy.DiagnosisStatus.GROUNDED
    assert out.delivery.status is policy.RemediationStatus.NOT_APPLICABLE
    assert len(calls) == len(question.calls) == 1 and calls[0][0] == 40
    assert services.delivery.log.events == [event("loop.negative_diagnosis_supported",level="info",
        phase="deliverable-observation",diagnosis_kind="missing_file",evidence_source="workspace_absence")]


@pytest.mark.parametrize("gate", ["pending","not-due","unknown","unavailable","empty-task"])
def test_nested_scheduled_gates_do_not_invoke_selected_hooks(gate):
    def forbidden(*args):
        raise AssertionError("inapplicable lifecycle invoked policy hook")
    definition = replace(policy.DEFINITION,execute=forbidden,arm=forbidden,observe=forbidden,deliver=forbidden)
    session = gap_state()
    session.deliverable_observation_last_drive = 7
    if gate == "pending":
        session.completion_remediation_subject = "REPORT.md"
    services,_,_ = composed_services(session,definition)
    services.due = (lambda *args:False) if gate == "not-due" else (lambda *args:True)
    services.delivery.observation = (lambda:None) if gate == "unknown" else (lambda:"generation-1")
    if gate in ("pending","not-due"):
        services.delivery.observation = forbidden
    before = vars(session).copy()
    out = definition.observe_scheduled(policy.ScheduledObservationInput(
        "" if gate == "empty-task" else TASK,40,1,1,gate != "unavailable"),session,services)
    if gate in ("unavailable","empty-task"):
        before["deliverable_observation_last_drive"] = 40
    assert vars(session) == before
    assert out.diagnosis.status is policy.DiagnosisStatus.NOT_APPLICABLE
    assert out.delivery.status is policy.RemediationStatus.NOT_APPLICABLE


@pytest.mark.parametrize("edge", EDGES)
def test_nested_default_preserves_literal_questions_events_and_state(edge):
    session = gap_state()
    session.deliverable_observation_last_drive = 7
    definition = policy.DEFINITION
    services,calls,question = composed_services(session,definition)
    before = vars(session).copy()
    judge_calls = []
    judge = services.observer.judge
    def recording_judge(system,user):
        judge_calls.append((system,user))
        return judge(system,user)
    services.observer.judge = recording_judge
    out = invoke_nested(edge,session,definition,services)
    evidence = prompts.render("negative_diagnosis",task_quote=TASK,source="workspace_absence",
        evidence=prompts.render("negative_diagnosis_missing_file",subject="REPORT.md")).strip()
    text = ("exact quote and measured absence" if edge == "deliver-arm" else evidence) + "\n" + prompts.render("verdict_nudge_action",action=TASK)
    nudge = prompts.render("periodic_missing_file_gap",reason=text,subject="REPORT.md")
    events = [] if edge == "deliver-arm" else [event("loop.negative_diagnosis_supported",level="info",
        phase="deliverable-observation",diagnosis_kind="missing_file",evidence_source="workspace_absence")]
    if edge in ("deliver-arm","scheduled-observe","scheduled-deliver"):
        delivery = out.delivery if edge.startswith("scheduled") else out
        assert delivery == policy.RemediationResult(policy.RemediationStatus.DELIVERED,"REPORT.md",nudge)
        before.update(completion_remediation_subject="REPORT.md",completion_remediation_reason=nudge,
            last_gap_named=text,last_gap_subject="REPORT.md",last_gap_observation="generation-1",nudge_reason=nudge,
            steer_source="completion check (deliverable not found)" if edge == "deliver-arm" else "deliverable observation")
        events.append(event("loop.satisfaction_gap_named",level="info",head=text[:120],subject="REPORT.md",rearmed=False))
    if edge.startswith("scheduled"):
        before["deliverable_observation_last_drive"] = 40
    if edge != "deliver-arm":
        gap = out.diagnosis if edge.startswith("scheduled") else out
        assert gap == policy.DiagnosisResult(policy.DiagnosisStatus.GROUNDED,evidence,TASK,"missing_file","REPORT.md")
        assert gap.text == text
        assert judge_calls == [(prompts.load("deliverable_observation"),prompts.render("deliverable_observation_user",
            task=TASK,inventory="complete inventory\n\n"))]
        assert calls == [(40 if edge.startswith("scheduled") else 7,judge_calls[0][1])]
        assert question.calls == [(prompts.render("missing_output_requirement",task=TASK,subject="REPORT.md"),)]
    else:
        assert calls == question.calls == judge_calls == []
    if edge == "terminal-observe":
        events.append(event("loop.done_gap_observed",level="info",subject="REPORT.md",plan_off=True))
    assert services.delivery.log.events == events
    assert vars(session) == before


@pytest.mark.parametrize("member", ["execute","arm","observe","deliver"])
def test_composition_constructor_requires_explicit_policy_hook(member):
    session = gap_state()
    base,_,_ = lifecycle(session)
    record = base.observer if member == "execute" else base.delivery if member == "arm" else base
    arguments = vars(record).copy()
    del arguments[member]
    with pytest.raises(TypeError,match=member):
        type(record)(**arguments)


@pytest.mark.parametrize("edge", EDGES)
@pytest.mark.parametrize("invalid", [None,"unknown-hook"])
def test_invalid_selected_callback_never_falls_back(edge,invalid):
    definition = replace(policy.DEFINITION,**{edge.rsplit("-",1)[1]:invalid})
    session = gap_state()
    session.deliverable_observation_last_drive = 7
    services,_,_ = composed_services(session,definition)
    before = vars(session).copy()
    if edge.startswith("scheduled"):
        before["deliverable_observation_last_drive"] = 40
    with pytest.raises(TypeError):
        invoke_nested(edge,session,definition,services)
    assert vars(session) == before


@pytest.mark.parametrize("status", [policy.DiagnosisStatus.WITHHELD,policy.DiagnosisStatus.NOT_APPLICABLE])
def test_direct_delivery_ignores_misleading_non_grounded_payload(status):
    def forbidden(*args):
        raise AssertionError("non-grounded delivery gathered facts or called arming")
    session = gap_state()
    before = vars(session).copy()
    services = policy.DeliveryServices(forbidden,forbidden,arm=forbidden)
    gap = policy.DiagnosisResult(status,"positive-looking",TASK,"missing_file","REPORT.md")
    out = policy.DEFINITION.deliver(policy.DeliveryInput(gap,policy.DeliveryTrigger.DELIVERABLE_OBSERVATION),session,services)
    assert out == policy.RemediationResult(policy.RemediationStatus.NOT_APPLICABLE)
    assert vars(session) == before


@pytest.mark.parametrize("task", [None,""," \t\r\n","\u2003\u00a0\u3000"])
def test_terminal_blank_root_cannot_reach_poison_selected_observer(task):
    # A replacement must not bypass the canonical observer's meaningful-task gate.
    def poison(*args):
        raise AssertionError("blank retained task reached selected observer")
    definition = replace(policy.DEFINITION,observe=poison,arm=poison)
    session = gap_state()
    session.deliverable_observation_last_drive = 7
    services,calls,question = composed_services(session,definition)
    root_calls, fingerprints = [], []
    def root():
        root_calls.append(task)
        return task
    def fingerprint():
        fingerprints.append("generation-1")
        return "generation-1"
    services.delivery.observation = fingerprint
    before = vars(session).copy()
    out = definition.observe_terminal(root,True,services)
    assert out == policy.DiagnosisResult(policy.DiagnosisStatus.NOT_APPLICABLE)
    assert root_calls == [task] and fingerprints == ["generation-1"]
    assert calls == question.calls == services.delivery.log.events == []
    assert vars(session) == before


def test_terminal_nonblank_root_preserves_surrounding_whitespace_bytes():
    task = " \t\u2003" + TASK + "\n\u3000 "
    gap = grounded_gap()
    seen = []
    def observe(source,services):
        seen.append((source,services))
        return gap
    def forbidden(*args):
        raise AssertionError("terminal observation must not arm")
    definition = replace(policy.DEFINITION,observe=observe,arm=forbidden)
    session = gap_state()
    session.deliverable_observation_last_drive = 7
    services,calls,question = composed_services(session,definition)
    before = vars(session).copy()
    out = definition.observe_terminal(lambda:task,True,services)
    assert out is gap
    assert seen == [(policy.ObservationInput(task,True),services.observer)]
    assert seen[0][0].task == task
    assert calls == question.calls == []
    assert services.delivery.log.events == [event("loop.done_gap_observed",level="info",subject="REPORT.md",plan_off=True)]
    assert vars(session) == before

