"""Source candidate only: fake harness/probes, real correlation/parser, no execution.

Historical parity names are retained for canonical references; their expectations
are independent literals. Shared factual readers/renderers are input services,
never executable old guard decisions used as expected truth.
"""
import base64
import copy
from collections import Counter
from dataclasses import replace
import hashlib
import json
from unittest.mock import patch

import pytest

from cria import loop, probegate, proberun, repositorychecks as checks, prompts
from tests.gatefixture import bounds_field_for
from cria import runnercontract, modulestate
from cria.probeparse import ProbeResult, parse_output
from cria.probediscovery import ProbeCandidate, ProbeKind, ProbeCost, Ecosystem
from pathlib import Path


class Log:
    def __init__(self):
        self.events = []
    def emit(self, name, **fields):
        self.events.append((name, fields))


def body(raw="", cid="probe", shell=True):
    tools = [{"type":"function", "function":{"name":"exec_command", "parameters":{
        "type":"object", "properties":{"cmd":{"type":"string"}, "yield_time_ms":{"type":"integer"}}}}}] if shell else []
    return {"tools":tools, "messages":[{"role":"user", "content":"Implement the complete task"},
        {"role":"tool", "tool_call_id":"unrelated", "content":"unrelated output"},
        {"role":"tool", "tool_call_id":cid, "content":raw}]}


def source(raw="", **kwargs):
    kwargs.setdefault("engagement",5)
    return checks.Input(body(raw), Log(), **kwargs)


def probes(plan=None):
    plan = plan or probegate.GatePlan("/workspace", surveyed_before=True, script="FAKE CHECK ONLY")
    return checks.ProbeServices(lambda messages:"/workspace", lambda *a,**kw:copy.deepcopy(plan), lambda:"call_fixed")


def canonical_resume_hooks():
    return checks.ResumeHooks(reissue=checks.DEFINITION.reissue,replan=checks.DEFINITION.replan)


def evidence(state, outcome=None, error=None):
    return checks.EvidenceServices(loop._read_tool_result,
        (lambda plan,raw,log:outcome) if outcome is not None else loop.read_gate,
        (lambda outcome:error) if error is not None else loop.gate_error_text,
        lambda findings,messages:loop.track_gate_progress(state,findings,messages))


def event(name, **fields):
    return name, {"assist_id":checks.DEFINITION.policy.id,
                  "family_id":checks.DEFINITION.policy.family_id, **fields}


def expected_call(command, ident="call_fixed"):
    return {"id":ident,"type":"function","function":{"name":"exec_command",
        "arguments":json.dumps({"cmd":command,"yield_time_ms":300000})}}


def marked_state(**kwargs):
    """Distinct prior progress makes accidental clearing or redating observable."""
    state = loop.GuardState(**kwargs)
    # Plan/session progress attributes also attach to the shared GuardState DTO.
    vars(state).update(action_seq=17,last_gate_seq=3,write_tracking=True,
        write_call_ids=["known-write"],call_counts=Counter({"known-write":1}),   # one dispatch, observed once
        write_result_ids={"known-write"},refused_write_ids=set(),
        gate_write_mark=0,gate_pending_write_ids={"known-write"},gate_sig="prior",
        stall_edit_marks=[0],last_gate_flag="prior")
    return state


def red_mark(finding):
    # Fixture data only: one new finding after one already-answered registered write.
    return {"last_gate_flag":finding,"last_gate_seq":17,"gate_write_mark":1,
            "gate_pending_write_ids":set(),"gate_sig":finding,"gate_stall":1,"stall_edit_marks":[1]}


GREEN_MARK = {"last_gate_flag":"","last_gate_seq":17,"gate_write_mark":1,
              "gate_pending_write_ids":set(),"gate_sig":"","gate_stall":0,"stall_edit_marks":[]}


def outcome(**kwargs):
    return probegate.GateOutcome(report=proberun.ProbeReport([],[],[]), **kwargs)


@pytest.mark.parametrize("turns,shell,status,clock", [
    (14,True,checks.Status.NOT_DUE,14),(15,True,checks.Status.PENDING,0),
    (16,True,checks.Status.PENDING,0),(15,False,checks.Status.UNAVAILABLE,0)])
def test_admission_matches_current_periodic_owner(turns,shell,status,clock):
    state = loop.GuardState(coder_turns=turns,periodic_replan_done=True)
    before = copy.deepcopy(vars(state))
    plan = probegate.GatePlan("/workspace",surveyed_before=True,script="FAKE CHECK ONLY")
    src = replace(source(),body=body(shell=shell))
    result = checks.admit(src,state,probes(plan))
    expected = {**before,"coder_turns":clock}
    events = []
    if status is checks.Status.PENDING:  # declared row outcome, not inferred admission logic
        expected.update(gate_plan=plan,gate_replan_required=False,awaiting_probe=True,periodic_probe=True,
                        periodic_replan_done=False,probe_call_id="call_fixed")
        assert result == checks.Result(checks.Status.PENDING,expected_call("FAKE CHECK ONLY"),
            note="periodic check-in — running the repo's checks",pending_kind=checks.PendingKind.CHECK)
        events = [event("loop.periodic_gate",steer="periodic-gate",plan_off=True)]
    else:
        assert result == checks.Result(status)
    assert vars(state) == expected
    assert src.log.events == events


@pytest.mark.parametrize("driver,steer,rewritten,engagement,due", [
    (checks.Driver.TASK,None,False,5,True), (checks.Driver.TASK,"",False,5,False),
    (checks.Driver.TASK,None,True,5,False), (checks.Driver.STEP,"",True,5,True),
    (checks.Driver.STEP,"parked",False,5,False), (checks.Driver.STEP,None,False,4,False),
])
def test_task_vs_step_scheduling(driver,steer,rewritten,engagement,due):
    state = loop.GuardState(coder_turns=15)
    out = checks.admit(source(driver=driver,steer=steer,rewritten=rewritten,engagement=engagement),state,probes())
    assert bool(out.call) is due
    assert state.coder_turns == (0 if due else 15)


def test_requested_probe_has_distinct_level_and_does_not_reset_periodic_clock():
    state = loop.GuardState(coder_turns=13)
    assert checks.admit(source(trigger=checks.Trigger.REQUESTED,engagement=3),state,probes()).status is checks.Status.NOT_SELECTED
    assert checks.admit(source(trigger=checks.Trigger.REQUESTED,engagement=4),state,probes()).call
    assert state.coder_turns == 13 and not state.periodic_probe


@pytest.mark.parametrize("root,extracted,expected", [(None,None,""),(".","/other",""),(None,"/workspace","/workspace"),("/root","/other","/root")])
def test_compose_uses_schema_root_session_and_real_plan_support(root,extracted,expected):
    seen = []
    state = loop.GuardState(gate_replan_required=True,gate_helpers_ready=True)
    state.web_session = "session-only"
    def plan(*args,**kwargs):
        seen.append((args,kwargs))
        return probegate.GatePlan(expected,script="literal 雪\n",surveyed_before=True)
    src = source(workspace_root=root)
    svc = checks.ProbeServices(lambda messages:extracted,plan,lambda:"fixed")
    out = checks.compose(src,state,svc)
    assert seen[0][0][:2] == (expected,"session-only")
    assert seen[0][1] == {"poll_wait_s":probegate.GATE_POLL_WAIT_LONG_S,"helpers_ready":True}
    assert json.loads(out["function"]["arguments"])["cmd"] == "literal 雪\n"
    assert not state.gate_replan_required


def test_plan_oserror_and_no_shell_have_existing_different_state_effects():
    state = loop.GuardState(coder_turns=15,gate_replan_required=True)
    state.gate_plan = probegate.GatePlan("/old")
    def failed(*args,**kwargs):
        raise OSError("unreadable")
    svc = replace(probes(),plan=failed)
    src = source()
    assert checks.admit(src,state,svc).status is checks.Status.UNAVAILABLE
    assert state.coder_turns == 0 and state.gate_plan is None and state.gate_replan_required
    assert src.log.events[0][0] == "loop.gate_error"
    state.coder_turns = 15
    state.gate_plan = probegate.GatePlan("/old")
    assert checks.admit(replace(src,body=body(shell=False)),state,svc).status is checks.Status.UNAVAILABLE
    assert state.gate_plan.workspace == "/old"


@pytest.mark.parametrize("ran,error,unknown,survey,partial,updates,events", [
    (True,"file.py:3 SyntaxError",False,False,False,
     {"last_gate_red":True,"gate_fresh":False,**red_mark("file.py:3 SyntaxError")},[]),
    (True,"",False,False,False,
     {"last_gate_red":False,"gate_fresh":True,"last_gate_testless":True,"last_gate_skipped":0,**GREEN_MARK},[]),
    (False,"",False,False,False,{"gate_fresh":True},[]),
    (False,"UNKNOWN",True,False,False,{"gate_fresh":False},[]),
    (False,"",False,True,False,{"gate_fresh":False},[("loop.gate_survey_only",{"level":"info"})]),
    (True,"",False,False,True,{"gate_fresh":True},
     [("loop.gate_partial",{"level":"warn","missing":1,"checks":["missing"]})]),
])
def test_shared_settlement_matches_current_owner(ran,error,unknown,survey,partial,updates,events):
    value = outcome(ran=ran,transport_unknown=unknown,replan_after_survey=survey,unran=["missing"] if partial else [])
    state = marked_state(last_gate_red=True,gate_stall=2)
    expected = copy.deepcopy(vars(state))
    expected.update(last_gate_ran=ran,last_gate_participation=None,gate_replan_required=survey,**updates)
    src = source()
    assert checks.record(src,state,value,error,evidence(state,value,error)) is None
    assert vars(state) == expected
    assert src.log.events == events  # these shared settlement events retain their untagged identity


@pytest.mark.parametrize("ran,error,unknown,survey,status,text,updates,events", [
    (True,"file.py:3 SyntaxError",False,False,checks.Status.OBSERVED,
     prompts.render("periodic_gate",truth="file.py:3 SyntaxError"),red_mark("file.py:3 SyntaxError"),
     [event("loop.periodic_gate_result",ran=True,spoke=True)]),
    (True,"",False,False,checks.Status.SILENT,None,
     {"last_gate_red":False,"last_gate_testless":True,"last_gate_skipped":0,**GREEN_MARK},
     [event("loop.periodic_gate_result",ran=True,spoke=False)]),
    (False,"",False,False,checks.Status.SILENT,None,{},
     [event("loop.periodic_gate_result",ran=False,spoke=False)]),
    (False,"UNKNOWN",True,False,checks.Status.OBSERVED,prompts.render("periodic_gate",truth="UNKNOWN"),{},
     [event("loop.periodic_gate_result",ran=False,spoke=True)]),
    (False,"",False,True,checks.Status.SILENT,None,{},
     [event("loop.periodic_gate_result",ran=False,spoke=False),("loop.gate_survey_only",{"level":"info"})]),
])
def test_periodic_result_matches_current_owner(ran,error,unknown,survey,status,text,updates,events):
    value = outcome(ran=ran,transport_unknown=unknown,replan_after_survey=survey)
    state = marked_state(periodic_probe=True,awaiting_probe=True,probe_call_id="probe",gate_fresh=False,last_gate_red=True)
    expected = copy.deepcopy(vars(state))
    expected.update(periodic_probe=False,awaiting_probe=False,last_gate_ran=ran,
                    last_gate_participation=None,gate_replan_required=survey,**updates)
    src = source("raw matched output")
    actual = checks.periodic_result(src,state,evidence(state,value,error),checks.JudgmentServices())
    assert actual == checks.Result(status,text=text,outcome=value) and actual.outcome is value
    assert vars(state) == expected and src.log.events == events
    assert not state.gate_fresh
    assert not state.periodic_probe and not state.awaiting_probe


@pytest.mark.parametrize("ran,error,unknown,survey,status,text,updates,events", [
    (True,"failed",False,False,checks.Status.OBSERVED,"failed",{"gate_fresh":False,**red_mark("failed")},[]),
    (True,"",False,False,checks.Status.SILENT,None,
     {"last_gate_red":False,"gate_fresh":True,"last_gate_testless":True,"last_gate_skipped":0,**GREEN_MARK},[]),
    (False,"",False,False,checks.Status.SILENT,None,{"gate_fresh":True},
     [event("loop.gate",plan_off=True,blocked=False,gate_ran=False,replan_after_survey=False)]),
    (False,"UNKNOWN",True,False,checks.Status.OBSERVED,prompts.load("probe_transport_unknown"),{"gate_fresh":False},[]),
    (False,"",False,True,checks.Status.SILENT,None,{"gate_fresh":False},
     [("loop.gate_survey_only",{"level":"info"}),event("loop.gate",plan_off=True,blocked=False,gate_ran=False,replan_after_survey=True)]),
])
def test_completion_evidence_is_not_task_or_step_approval(ran,error,unknown,survey,status,text,updates,events):
    value = outcome(ran=ran,transport_unknown=unknown,replan_after_survey=survey)
    state = marked_state(probe_call_id="probe",last_gate_red=True)
    expected = copy.deepcopy(vars(state))
    expected.update(last_gate_ran=ran,last_gate_participation=None,gate_replan_required=survey,**updates)
    src = source("raw")
    actual = checks.completion_result(src,state,evidence(state,value,error))
    assert actual == checks.Result(status,text=text,outcome=value) and actual.outcome is value
    assert vars(state) == expected and src.log.events == events
    assert not hasattr(actual,"approved")


def test_one_survey_replan_per_checkin_even_when_it_is_survey_only_again():
    state = loop.GuardState(coder_turns=15)
    src = source()
    checks.admit(src,state,probes())
    value = outcome(replan_after_survey=True)
    ev = evidence(state,value,"")
    first = checks.resume(src,state,probes(),ev,checks.JudgmentServices(),canonical_resume_hooks())
    assert first.call and state.periodic_probe and state.periodic_replan_done
    assert checks.resume(src,state,probes(),ev,checks.JudgmentServices(),canonical_resume_hooks()).call is None
    assert not state.periodic_probe
    state.coder_turns = 15
    checks.admit(src,state,probes())
    assert not state.periodic_replan_done


def test_replan_without_shell_consumes_obligation_without_looping():
    state = loop.GuardState(gate_replan_required=True)
    src = replace(source(),body=body(shell=False))
    assert checks.replan(src,state,probes(),periodic=True).status is checks.Status.UNAVAILABLE
    assert state.periodic_replan_done and not state.gate_replan_required
    assert checks.replan(src,state,probes(),periodic=True).status is checks.Status.NOT_DUE


def envelope(plan,fields):
    return probegate._transport_marker(plan.transport_id) + "\n" + "\n".join(k+"\t"+v for k,v in fields.items()) + "\n" + probegate._transport_marker(plan.transport_id,end=True)


def page(plan,payload,start,end):
    return envelope(plan,{"path":base64.b64encode(f"/tmp/.cria-gate-{plan.transport_id}.spool".encode()).decode(),
        "offset":str(start),"total":str(len(payload)),"sha256":hashlib.sha256(payload).hexdigest(),
        "bounds":bounds_field_for(payload.decode())[0].split("\t",1)[1],
        "data":base64.b64encode(payload[start:end]).decode()})


def test_pending_page_correlation_then_real_parser_settlement():
    plan = probegate.GatePlan("/workspace",surveyed_before=True,transport_required=True,script="FAKE",
        candidates=[candidate(["pytest"],Ecosystem.Python)])
    state = loop.GuardState(periodic_probe=True,awaiting_probe=True,probe_call_id="probe",gate_plan=plan)
    raw = f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\nf.py:7: error: broken\nEXIT:1\n".encode()
    split = len(raw)//2
    src = source(page(plan,raw,0,split))
    ev = evidence(state)
    read_calls = []
    def read(*args):
        read_calls.append(args)
        return loop.read_gate(*args)
    ev = replace(ev,read=read)
    first = checks.resume(src,state,probes(),ev,checks.JudgmentServices(),canonical_resume_hooks())
    assert first.call and state.periodic_probe and not read_calls
    assert state.probe_call_id == first.call["id"]
    second_src = replace(src,body=body(page(plan,raw,split,len(raw)),cid=state.probe_call_id))
    second = checks.resume(second_src,state,probes(),ev,checks.JudgmentServices(),canonical_resume_hooks())
    assert len(read_calls) == 1 and plan.transport_complete
    assert "f.py:7" in second.text and state.last_gate_red
    assert src.log.events[0][0] == "gate.transport_page"


@pytest.mark.parametrize("raw", ["permission denied", "cut arbitrary page"])
def test_refused_or_malformed_transport_is_never_green(raw):
    plan = probegate.GatePlan("/workspace",surveyed_before=True,transport_required=True)
    # A cut envelope, not an openerless running poll.
    if raw.startswith("cut"):
        raw = probegate._transport_marker(plan.transport_id) + "\ncut"
    state = loop.GuardState(periodic_probe=True,awaiting_probe=True,probe_call_id="probe",gate_plan=plan,last_gate_red=True)
    src = source(raw)
    out = checks.resume(src,state,probes(),evidence(state),checks.JudgmentServices(),canonical_resume_hooks())
    assert out.outcome.transport_unknown and out.text == prompts.render("periodic_gate",truth=prompts.load("probe_transport_unknown"))
    assert state.last_gate_red and not state.gate_fresh
    assert any(name == "gate.transport_unknown" for name,_ in src.log.events)


@pytest.mark.parametrize("driver,reissues", [(checks.Driver.TASK,1),(checks.Driver.STEP,0)])
def test_task_and_step_rewrite_order(driver,reissues):
    state = loop.GuardState(periodic_probe=True,awaiting_probe=True,probe_call_id="erased")
    src = source(driver=driver,rewritten=True)
    out = checks.resume(src,state,probes(),evidence(state,outcome(),""),checks.JudgmentServices(),canonical_resume_hooks())
    assert state.probe_reissues == reissues
    assert bool(out.call) == bool(reissues)


def test_rewrite_polls_existing_plan_before_bounded_new_gate_reissue():
    state = loop.GuardState(periodic_probe=True,awaiting_probe=True,probe_call_id="lost",
        gate_plan=probegate.GatePlan("/workspace",transport_required=True,script="FAKE"))
    src = source(rewritten=True)
    old_plan = state.gate_plan
    for count in (1,2):
        out = checks.reissue(src,state,probes(),evidence(state))
        assert out.call and state.gate_plan is old_plan
        assert state.probe_poll_reissues == count and state.probe_reissues == 0
    for count in (1,2):
        out = checks.reissue(src,state,probes(),evidence(state))
        assert out.call and state.probe_reissues == count
    assert checks.reissue(src,state,probes(),evidence(state)).call is None
    arrived = replace(src,body=body("real output",cid=state.probe_call_id))
    checks.reissue(arrived,state,probes(),evidence(state))
    assert state.probe_reissues == state.probe_poll_reissues == 0


def test_reader_exception_propagates_without_fabricating_evidence():
    state = loop.GuardState(periodic_probe=True,awaiting_probe=True,probe_call_id="probe",last_gate_red=True)
    ev = evidence(state)
    def failed(*args):
        raise ValueError("broken parser")
    with pytest.raises(ValueError,match="broken parser"):
        checks.periodic_result(source("output"),state,replace(ev,read=failed),checks.JudgmentServices())
    assert not state.periodic_probe and not state.awaiting_probe and state.last_gate_red


def candidate(command,eco,declared=False):
    return ProbeCandidate(ProbeKind.Test,command,Path("."),90,90,ProbeCost.Moderate,False,False,False,"fixture",
                          ecosystem=eco,declared_interface=declared)


def test_runner_then_go_use_their_real_separate_judgments_and_repeat_memory():
    js = candidate(["npm","test"],Ecosystem.JsTs,True)
    go = candidate(["go","test","-mod=readonly","./..."],Ecosystem.Go)
    value = outcome(ran=True)
    value.report = proberun.ProbeReport([], [js,go], [ProbeResult("npm test",1,"runner failed"),ProbeResult("go test -mod=readonly ./...",1,"go failed")])
    runner_state, module_state = runnercontract.RunnerState(), modulestate.ModuleState()
    asked = []
    log = Log()
    def runner(out):
        return runnercontract.DEFINITION.execute(runnercontract.RunnerInput(out,lambda:"checker bytes",lambda:None,
            lambda:("original task","session"),lambda question,**kw:asked.append("runner") or "RESET",log),runner_state).steer
    def module(out):
        return modulestate.DEFINITION.execute(modulestate.ModuleInput(out,lambda:"checker bytes",lambda:("original task","session"),
            lambda question:asked.append("go") or "REANCHOR",log),module_state).steer
    state = loop.GuardState(periodic_probe=True,probe_call_id="probe")
    first = checks.periodic_result(source(),state,evidence(state,value,"checker bytes"),checks.JudgmentServices(runner,module))
    assert first.text and asked == ["runner"] and not module_state.signature
    state.periodic_probe = True
    second = checks.periodic_result(source(),state,evidence(state,value,"checker bytes"),checks.JudgmentServices(runner,module))
    assert second.text and asked == ["runner","go"]
    assert runner_state.signature and module_state.signature


def test_passing_tallies_are_command_scoped_and_unknown_is_not_zero():
    state = loop.GuardState()
    shared = {"pytest":9}
    state.tests_passed_high = shared
    expected = copy.deepcopy(vars(state))
    expected["last_regression"] = ("pytest",9,7)
    report = proberun.ProbeReport([], [candidate(["pytest"],Ecosystem.Python)],
        [parse_output("pytest","pytest",0,"7 passed in 0.1s","")])
    assert checks.passing_test_regression(state,report) == prompts.render("tests_regressed",was="9",now="7")
    assert vars(state) == expected and state.tests_passed_high is not shared
    assert state.tests_passed_high == {"pytest":9}
    assert shared == {"pytest":9} and state.last_regression == ("pytest",9,7)
    other = proberun.ProbeReport([], [candidate(["go","test","./..."],Ecosystem.Go)],
        [parse_output("go","go test ./...",0,"ok example/project 0.1s","")])
    assert checks.passing_test_regression(state,other) == ""  # no runner tally is not zero tests
    assert vars(state) == expected
    before = copy.deepcopy(state)
    assert checks.passing_test_regression(state,proberun.ProbeReport([],[],[])) == ""
    assert vars(state) == vars(before)


def test_acting_turn_clock_and_fresh_sessions_do_not_share_state():
    a,b = loop.GuardState(),loop.GuardState()
    checks.observe_acting_turn(a,acting=False)
    checks.observe_acting_turn(a,acting=True)
    checks.observe_acting_turn(a,acting=True,selected=False)
    assert a.coder_turns == 1 and b.coder_turns == 0
    a.tests_passed_high = {"pytest":9}
    assert not getattr(b,"tests_passed_high",None)
    assert not b.periodic_probe


def test_disabled_and_replacement_do_not_touch_unselected_state():
    def forbidden(*args):
        raise AssertionError("unselected evidence or policy was called")
    state = loop.GuardState(coder_turns=20,periodic_probe=True)
    before = copy.deepcopy(state)
    selected = checks.Selected(None)
    assert selected.admit(forbidden,state,forbidden).status is checks.Status.NOT_SELECTED
    assert selected.resume(forbidden,state,forbidden,forbidden,forbidden).status is checks.Status.NOT_SELECTED
    assert selected.completion(forbidden,state,forbidden).status is checks.Status.NOT_SELECTED
    assert selected.replan(forbidden,state,forbidden).status is checks.Status.NOT_SELECTED
    assert selected.reissue(forbidden,state,forbidden,forbidden).status is checks.Status.NOT_SELECTED
    selected.observe(state,acting=True)
    assert vars(state) == vars(before)
    calls = []
    def replacement(src,st,svc):
        calls.append((src,st,svc))
        return checks.Result(checks.Status.SILENT,text="replacement-owned")
    definition = replace(checks.DEFINITION,execute=replacement)
    out = checks.Selected(definition).admit(source,state,probes)
    assert out.text == "replacement-owned" and len(calls) == 1 and vars(state) == vars(before)


def test_actual_construction_and_transport_match_original_support():
    state = loop.GuardState(gate_replan_required=True)
    expected = copy.deepcopy(vars(state))
    src = source(workspace_root="/workspace")
    plan = probegate.GatePlan("/workspace",surveyed_before=True,transport_required=True,script="FAKE")
    svc = replace(probes(plan),call_id=lambda:"call_0123456789abcdef")
    assert checks.compose(src,state,svc) == expected_call("FAKE","call_0123456789abcdef")
    expected.update(gate_plan=plan,gate_replan_required=False)
    assert vars(state) == expected and src.log.events == []
    state.probe_call_id = "probe"
    raw = b"complete raw bytes, preserved verbatim"
    src = replace(src,body=body(page(plan,raw,0,8)))
    declared = probegate.GatePlan("/workspace", transport_required=True, transport_id=plan.transport_id); probegate.ingest_transport(declared, page(declared,raw,0,8))
    expected_plan = replace(plan,helpers_ready=True,transport_path=f"/tmp/.cria-gate-{plan.transport_id}.spool",
        transport_total=len(raw),transport_sha256=hashlib.sha256(raw).hexdigest(),transport_data=bytearray(b"complete"),
        transport_bounds=declared.transport_bounds, transport_sections=declared.transport_sections)
    rendered = []
    render = probegate.continue_transport_command
    def continuation(actual):
        # Record the required renderer's actual output as an input fact. The policy must
        # forward it byte-for-byte; it does not own or duplicate this shell program.
        assert actual is state.gate_plan and actual == expected_plan
        rendered.append(render(actual))
        return rendered[-1]
    with patch.object(probegate,"continue_transport_command",side_effect=continuation):
        result = checks.transport(src,state,svc,evidence(state))
    assert len(rendered) == 1 and rendered[0]
    assert result == checks.Result(checks.Status.PENDING,
        expected_call(rendered[0],"call_0123456789abcdef"),pending_kind=checks.PendingKind.PAGE)
    expected.update(gate_plan=expected_plan,gate_helpers_ready=True,probe_call_id="call_0123456789abcdef")
    assert vars(state) == expected
    assert src.log.events == [("gate.transport_page",{"received":8,"total":len(raw)})]


@pytest.mark.parametrize("required,done,shell,status,updates,events", [
    (False,False,True,checks.Status.NOT_DUE,{},[]),
    (True,False,True,checks.Status.PENDING,
     {"gate_replan_required":False,"periodic_replan_done":True,"periodic_probe":True,"awaiting_probe":True,"probe_call_id":"call_fixed"},
     [event("loop.gate_replan_after_survey",available=True),event("loop.periodic_replan_after_survey",available=True)]),
    (True,True,True,checks.Status.NOT_DUE,{},[]),
    (True,False,False,checks.Status.UNAVAILABLE,{"gate_replan_required":False,"periodic_replan_done":True},
     [event("loop.gate_replan_after_survey",available=False),event("loop.periodic_replan_after_survey",available=False)]),
])
def test_periodic_survey_replan_matches_original(required,done,shell,status,updates,events):
    state = loop.GuardState(gate_replan_required=required,periodic_replan_done=done)
    expected = copy.deepcopy(vars(state))
    expected.update(updates)
    src = replace(source(),body=body(shell=shell))
    plan = probegate.GatePlan("/workspace",surveyed_before=True,script="FAKE CHECK ONLY")
    result = checks.replan(src,state,probes(plan),periodic=True)
    if status is checks.Status.PENDING:
        expected["gate_plan"] = plan
        assert result == checks.Result(checks.Status.PENDING,expected_call("FAKE CHECK ONLY"),
                                       pending_kind=checks.PendingKind.SURVEY_REPLAN)
    else:
        assert result == checks.Result(status)
    assert vars(state) == expected and src.log.events == events


def test_missing_shell_during_paging_fails_closed_not_as_a_clean_partial():
    plan = probegate.GatePlan("/workspace",transport_required=True)
    state = loop.GuardState(gate_plan=plan,probe_call_id="probe")
    src = replace(source(),body=body(page(plan,b"ten bytes here",0,3),shell=False))
    out = checks.transport(src,state,probes(),evidence(state))
    assert not out.call and plan.transport_error
    assert src.log.events[-1][0] == "gate.transport_unknown"
    assert len(plan.transport_data) == 3


def test_real_refusal_reader_keeps_harness_words_in_event_and_silence_to_coder():
    state = loop.GuardState(periodic_probe=True,probe_call_id="probe",
        gate_plan=probegate.GatePlan("/workspace",surveyed_before=True))
    raw = "Permission denied: sandbox policy refused this command"
    src = source(raw)
    out = checks.periodic_result(src,state,evidence(state),checks.JudgmentServices())
    assert out.text is None and not state.last_gate_ran
    refusals = [fields for name,fields in src.log.events if name == "loop.gate_refused"]
    assert len(refusals) == 1 and "Permission denied" in refusals[0]["reason"]


def test_periodic_regression_event_uses_the_runner_tally_and_preserves_review_clocks():
    report = proberun.ProbeReport([], [candidate(["pytest"],Ecosystem.Python)],
        [parse_output("pytest","pytest",0,"7 passed in 0.1s","")])
    value = outcome(ran=True)
    value.report = report
    state = loop.GuardState(periodic_probe=True,probe_call_id="probe",coder_turns=14,drive_count=90)
    state.tests_passed_high = {"pytest":9}
    src = source()
    out = checks.periodic_result(src,state,evidence(state,value,""),checks.JudgmentServices())
    assert out.text and state.coder_turns == 14 and state.drive_count == 90
    event = next(fields for name,fields in src.log.events if name == "loop.tests_regressed")
    assert (event["command"],event["high"],event["now"]) == ("pytest",9,7)
    assert event["assist_id"] == checks.DEFINITION.policy.id and event["family_id"] == "F40"
    result_event = next(fields for name,fields in src.log.events if name == "loop.periodic_gate_result")
    assert result_event["ran"] and not result_event["spoke"]  # existing event is checker error, not later regression


def test_replacements_own_every_optional_lifecycle_hook():
    calls = []
    def replacement(name):
        def hook(*args,**kwargs):
            calls.append(name)
            return checks.Result(checks.Status.SILENT)
        return hook
    definition = replace(checks.DEFINITION,execute=replacement("admit"),resume=replacement("resume"),
        completion=replacement("completion"),replan=replacement("replan"),reissue=replacement("reissue"),
        observe=lambda *a,**kw:calls.append("observe"))
    selected = checks.Selected(definition)
    state = loop.GuardState(coder_turns=20,periodic_probe=True)
    before = copy.deepcopy(state)
    selected.admit(source,state,probes)
    selected.resume(source,state,probes,lambda:evidence(state),checks.JudgmentServices)
    selected.completion(source,state,lambda:evidence(state))
    selected.replan(source,state,probes,periodic=True)
    selected.reissue(source,state,probes,lambda:evidence(state))
    selected.observe(state,acting=True)
    assert calls == ["admit","resume","completion","replan","reissue","observe"]
    assert vars(state) == vars(before)


def test_settled_periodic_result_cannot_be_consumed_twice_or_leak_to_another_session():
    first = loop.GuardState(periodic_probe=True,probe_call_id="probe")
    second = loop.GuardState()
    src = source("first session output")
    checks.periodic_result(src,first,evidence(first,outcome(ran=True),"exact error"),checks.JudgmentServices())
    snapshot = copy.deepcopy(first)
    events = list(src.log.events)
    def forbidden(*args):
        raise AssertionError("no pending periodic evidence may be read")
    ev = checks.EvidenceServices(forbidden,forbidden,forbidden,forbidden)
    assert checks.periodic_result(src,first,ev,checks.JudgmentServices(forbidden,forbidden)).status is checks.Status.NOT_DUE
    assert vars(first) == vars(snapshot) and src.log.events == events
    assert checks.periodic_result(src,second,ev,checks.JudgmentServices(forbidden,forbidden)).status is checks.Status.NOT_DUE
    assert not second.last_gate_red and not getattr(second,"last_gate_ran",False)


def test_wrong_tool_result_cannot_settle_or_green_the_pending_check():
    state = loop.GuardState(periodic_probe=True,probe_call_id="expected",last_gate_red=True,
        gate_plan=probegate.GatePlan("/workspace",surveyed_before=True,transport_required=True))
    payload = b"not current evidence"
    # A well-formed page belongs to another tool call, not the one awaiting a result.
    src = replace(source(),body=body(page(state.gate_plan,payload,0,len(payload)),cid="another-call"))
    out = checks.resume(src,state,probes(),evidence(state),checks.JudgmentServices(),canonical_resume_hooks())
    assert out.outcome.transport_unknown and state.last_gate_red
    assert not state.gate_plan.transport_data


@pytest.mark.parametrize("driver", [checks.Driver.TASK,checks.Driver.STEP])
def test_requested_reissue_preserves_driver_event_and_counter_settlement(driver):
    state = loop.GuardState(awaiting_probe=True,probe_call_id="missing",probe_poll_reissues=1)
    src = source(driver=driver,rewritten=True,step=2,trigger=checks.Trigger.REQUESTED)
    out = checks.reissue(src,state,probes(),evidence(state))
    assert out.call and out.pending_kind is checks.PendingKind.REISSUE
    event = src.log.events[-1][1]
    assert event["attempt"] == state.probe_reissues == 1
    assert event.get("step") == (2 if driver is checks.Driver.STEP else None)
    assert ("plan_off" in event) is (driver is checks.Driver.TASK)
    arrived = replace(src,body=body("real result",cid=state.probe_call_id))
    checks.reissue(arrived,state,probes(),evidence(state))
    assert state.probe_reissues == (0 if driver is checks.Driver.TASK else 1)
    assert state.probe_poll_reissues == (0 if driver is checks.Driver.TASK else 1)


def test_step_periodic_reissue_never_reads_history_or_spends_reissue_budget():
    def forbidden(*args):
        raise AssertionError("step-periodic does not enter rewrite reissue")
    state = loop.GuardState(periodic_probe=True,awaiting_probe=True,probe_reissues=1)
    before = copy.deepcopy(state)
    ev = checks.EvidenceServices(forbidden,forbidden,forbidden,forbidden)
    assert checks.reissue(source(driver=checks.Driver.STEP,rewritten=True),state,probes(),ev).status is checks.Status.NOT_DUE
    assert vars(state) == vars(before)


def test_selected_resume_invokes_exact_selected_reissue_with_actual_inputs():
    state = loop.GuardState(periodic_probe=True,awaiting_probe=True,probe_call_id="lost")
    src, svc = source(), probes()
    ev, judgments = evidence(state,outcome(),""), checks.JudgmentServices()
    seen = []
    pending = checks.Result(checks.Status.PENDING,expected_call("selected retry","selected-reissue"),
                            pending_kind=checks.PendingKind.REISSUE)
    def reissue(actual_source,actual_state,actual_services,actual_evidence):
        seen.append((actual_source,actual_state,actual_services,actual_evidence))
        return pending
    definition = replace(checks.DEFINITION,reissue=reissue)
    selected = checks.Selected(definition)
    before = copy.deepcopy(vars(state))
    result = selected.resume(lambda:src,state,lambda:svc,lambda:ev,lambda:judgments)
    assert len(seen) == 1  # before fix: canonical reissue silently bypassed this selected hook
    assert all(actual is expected for actual,expected in zip(seen[0],(src,state,svc,ev)))
    assert selected.definition is definition and definition.reissue is reissue
    assert result is pending and vars(state) == before and src.log.events == []


def test_selected_resume_invokes_exact_selected_replan_with_periodic_true():
    state = loop.GuardState(periodic_probe=True,awaiting_probe=True,probe_call_id="probe")
    src, svc = source("matched survey"), probes()
    value = outcome(replan_after_survey=True)
    ev, judgments = evidence(state,value,""), checks.JudgmentServices()
    seen = []
    def replan(actual_source,actual_state,actual_services,*,periodic=False):
        seen.append((actual_source,actual_state,actual_services,periodic))
        assert not actual_state.periodic_probe and actual_state.gate_replan_required
        return checks.Result(checks.Status.NOT_DUE)
    definition = replace(checks.DEFINITION,replan=replan)
    selected = checks.Selected(definition)
    result = selected.resume(lambda:src,state,lambda:svc,lambda:ev,lambda:judgments)
    assert len(seen) == 1  # before fix: canonical replan silently bypassed this selected hook
    assert all(actual is expected for actual,expected in zip(seen[0][:3],(src,state,svc)))
    assert seen[0][3] is True and selected.definition is definition and definition.replan is replan
    assert result == checks.Result(checks.Status.SILENT,outcome=value)
    assert not state.periodic_replan_done and state.gate_replan_required and state.gate_plan is None


def resume_fixture():
    state = loop.GuardState(periodic_probe=True,awaiting_probe=True,probe_call_id="probe")
    src, svc = source("matched survey"), probes()
    value = outcome(replan_after_survey=True)
    ev, judgments = evidence(state,value,""), checks.JudgmentServices()
    return state,src,svc,ev,judgments,value


@pytest.mark.parametrize("hook", ["reissue","replan"])
@pytest.mark.parametrize("returned,error", [
    (None,TypeError),({"status":"pending"},TypeError),
    (checks.Result("pending"),ValueError),(checks.Result(checks.Driver.TASK),ValueError),
    (checks.Result(checks.Status.SILENT),ValueError),(checks.Result(checks.Status.NOT_SELECTED),ValueError),
    (checks.Result(checks.Status.PENDING),ValueError),
    (checks.Result(checks.Status.PENDING,False),ValueError),
    (checks.Result(checks.Status.PENDING,{}),ValueError),
    (checks.Result(checks.Status.PENDING,["not a call"]),ValueError),
    (checks.Result(checks.Status.NOT_DUE,expected_call("smuggled")),ValueError),
    (checks.Result(checks.Status.UNAVAILABLE,{}),ValueError),
])
def test_selected_resume_validates_nested_results_after_exact_callback(hook,returned,error):
    state,src,svc,ev,judgments,_ = resume_fixture()
    seen, snapshots = [], []
    def invalid(*args,**kwargs):
        expected = (src,state,svc,ev) if hook == "reissue" else (src,state,svc)
        assert len(args) == len(expected) and all(actual is wanted for actual,wanted in zip(args,expected))
        assert kwargs == ({} if hook == "reissue" else {"periodic":True})
        seen.append(hook)
        snapshots.append(copy.deepcopy(vars(state)))
        return returned
    definition = replace(checks.DEFINITION,**{hook:invalid})
    selected = checks.Selected(definition)
    with pytest.raises(error):
        selected.resume(lambda:src,state,lambda:svc,lambda:ev,lambda:judgments)
    assert seen == [hook] and vars(state) == snapshots[0]
    assert not state.periodic_replan_done and state.gate_plan is None
    assert src.log.events == ([] if hook == "reissue" else [
        event("loop.periodic_gate_result",ran=False,spoke=False),("loop.gate_survey_only",{"level":"info"})])


@pytest.mark.parametrize("hook", ["reissue","replan"])
def test_selected_resume_accepts_pending_without_inventing_callback_state(hook):
    state,src,svc,ev,judgments,_ = resume_fixture()
    seen, snapshots = [], []
    call = expected_call("selected pending 雪\n","selected-pending")
    pending = checks.Result(checks.Status.PENDING,call,pending_kind=
                            checks.PendingKind.REISSUE if hook == "reissue" else checks.PendingKind.SURVEY_REPLAN)
    def replacement(*args,**kwargs):
        expected = (src,state,svc,ev) if hook == "reissue" else (src,state,svc)
        assert len(args) == len(expected) and all(actual is wanted for actual,wanted in zip(args,expected))
        assert kwargs == ({} if hook == "reissue" else {"periodic":True})
        seen.append(hook)
        snapshots.append(copy.deepcopy(vars(state)))
        return pending
    definition = replace(checks.DEFINITION,**{hook:replacement})
    selected = checks.Selected(definition)
    result = selected.resume(lambda:src,state,lambda:svc,lambda:ev,lambda:judgments)
    assert result is pending and result.call is call and seen == [hook]
    assert vars(state) == snapshots[0] and state.probe_call_id == "probe"
    assert state.periodic_probe is (hook == "reissue")  # only the callback may re-arm its own work


@pytest.mark.parametrize("reissue_status", [checks.Status.NOT_DUE,checks.Status.OBSERVED,checks.Status.UNAVAILABLE])
@pytest.mark.parametrize("replan_status", [checks.Status.NOT_DUE,checks.Status.UNAVAILABLE])
def test_selected_resume_declines_keep_transport_read_replan_order(reissue_status,replan_status):
    state,src,svc,ev,judgments,value = resume_fixture()
    before = copy.deepcopy(vars(state))
    order = []
    def reissue(*args):
        assert all(actual is wanted for actual,wanted in zip(args,(src,state,svc,ev)))
        order.append("reissue")
        return checks.Result(reissue_status)
    def replan(*args,**kwargs):
        assert all(actual is wanted for actual,wanted in zip(args,(src,state,svc))) and kwargs == {"periodic":True}
        order.append("replan")
        return checks.Result(replan_status)
    def raw(messages,cid):
        order.append("raw")
        assert messages is src.body["messages"] and cid == "probe"
        return loop._read_tool_result(messages,cid)
    def read(plan,text,log):
        order.append("read")
        assert plan is None and text == "matched survey" and log is src.log
        return value
    def error(actual):
        order.append("error")
        assert actual is value
        return ""
    ev = replace(ev,raw=raw,read=read,error=error)
    definition = replace(checks.DEFINITION,reissue=reissue,replan=replan)
    transport = checks.transport
    def page(*args):
        order.append("transport")
        return transport(*args)
    with patch.object(checks,"transport",side_effect=page):
        result = checks.Selected(definition).resume(lambda:src,state,lambda:svc,lambda:ev,lambda:judgments)
    assert order == ["reissue","transport","raw","read","error","replan"]
    assert result == checks.Result(checks.Status.SILENT,outcome=value)
    before.update(periodic_probe=False,awaiting_probe=False,gate_replan_required=True,
                  last_gate_ran=False,last_gate_participation=None)
    assert vars(state) == before


def test_selected_step_resume_skips_task_reissue_and_uses_selected_replan():
    state,src,svc,ev,judgments,value = resume_fixture()
    src = replace(src,driver=checks.Driver.STEP)
    seen = []
    def forbidden(*args):
        raise AssertionError("STEP periodic resume entered TASK reissue")
    def replan(*args,**kwargs):
        assert all(actual is wanted for actual,wanted in zip(args,(src,state,svc))) and kwargs == {"periodic":True}
        seen.append("replan")
        return checks.Result(checks.Status.NOT_DUE)
    definition = replace(checks.DEFINITION,reissue=forbidden,replan=replan)
    result = checks.Selected(definition).resume(lambda:src,state,lambda:svc,lambda:ev,lambda:judgments)
    assert seen == ["replan"] and result == checks.Result(checks.Status.SILENT,outcome=value)
    assert state.probe_reissues == 0 and not state.periodic_replan_done


def test_selected_resume_none_builds_no_hooks_or_factories():
    def forbidden(*args,**kwargs):
        raise AssertionError("unselected resume constructed hooks or gathered input")
    state = loop.GuardState(periodic_probe=True,awaiting_probe=True)
    before = copy.deepcopy(vars(state))
    with patch.object(checks,"ResumeHooks",side_effect=forbidden):
        result = checks.Selected(None).resume(forbidden,state,forbidden,forbidden,forbidden)
    assert result == checks.Result(checks.Status.NOT_SELECTED) and vars(state) == before


def test_resume_hooks_are_required_and_keep_exact_selected_member_identity():
    state,src,svc,ev,judgments,_ = resume_fixture()
    hooks = canonical_resume_hooks()
    assert hooks.reissue is checks.DEFINITION.reissue and hooks.replan is checks.DEFINITION.replan
    with pytest.raises(TypeError):
        checks.ResumeHooks(reissue=checks.DEFINITION.reissue)
    with pytest.raises(TypeError):
        checks.ResumeHooks(replan=checks.DEFINITION.replan)
    with pytest.raises(TypeError):
        checks.resume(src,state,svc,ev,judgments)
    seen = []
    def outer(actual_source,actual_state,actual_services,actual_evidence,actual_judgments,actual_hooks):
        assert all(actual is wanted for actual,wanted in zip(
            (actual_source,actual_state,actual_services,actual_evidence,actual_judgments),(src,state,svc,ev,judgments)))
        seen.append(actual_hooks)
        return checks.Result(checks.Status.NOT_DUE)
    def reissue(*args):
        raise AssertionError("replacement resume did not authorize nested execution")
    def replan(*args,periodic=False):
        raise AssertionError("replacement resume did not authorize nested execution")
    definition = replace(checks.DEFINITION,resume=outer,reissue=reissue,replan=replan)
    selected = checks.Selected(definition)
    assert selected.resume(lambda:src,state,lambda:svc,lambda:ev,lambda:judgments) == checks.Result(checks.Status.NOT_DUE)
    assert len(seen) == 1 and seen[0].reissue is reissue and seen[0].replan is replan
    assert selected.definition is definition


@pytest.mark.parametrize("hook,status,call", [
    ("replan",checks.Status.OBSERVED,None),
    ("reissue",checks.Status.OBSERVED,expected_call("smuggled")),
    ("replan",checks.Status.NOT_DUE,False),
])
def test_selected_resume_rejects_observed_replan_and_nonpending_calls(hook,status,call):
    state,src,svc,ev,judgments,_ = resume_fixture()
    seen = []
    def invalid(*args,**kwargs):
        assert args[0] is src and args[1] is state and args[2] is svc
        seen.append(copy.deepcopy(vars(state)))
        return checks.Result(status,call)
    definition = replace(checks.DEFINITION,**{hook:invalid})
    with pytest.raises(ValueError):
        checks.Selected(definition).resume(lambda:src,state,lambda:svc,lambda:ev,lambda:judgments)
    assert len(seen) == 1 and vars(state) == seen[0]


def test_canonical_nested_replan_stamps_once_before_plan_factory():
    state,src,svc,ev,judgments,_ = resume_fixture()
    plan = probegate.GatePlan("/workspace",surveyed_before=True,script="selected canonical plan")
    planned = []
    def build(*args,**kwargs):
        assert state.periodic_replan_done and state.gate_replan_required
        assert args == ("/workspace","",src.log)
        assert kwargs == {"poll_wait_s":probegate.GATE_POLL_WAIT_LONG_S,"helpers_ready":False}
        planned.append("plan")
        return copy.deepcopy(plan)
    svc = replace(svc,plan=build)
    selected = checks.Selected(checks.DEFINITION)
    first = selected.resume(lambda:src,state,lambda:svc,lambda:ev,lambda:judgments)
    assert first == checks.Result(checks.Status.PENDING,expected_call("selected canonical plan"),
                                  pending_kind=checks.PendingKind.SURVEY_REPLAN)
    assert planned == ["plan"] and state.periodic_probe and state.awaiting_probe
    second = selected.resume(lambda:src,state,lambda:svc,lambda:ev,lambda:judgments)
    assert second.status is checks.Status.SILENT and second.call is None
    assert planned == ["plan"] and state.periodic_replan_done and not state.periodic_probe


def test_selected_resume_keeps_spoken_findings_without_selected_replan():
    state,src,svc,_,judgments,_ = resume_fixture()
    value = outcome(ran=True)
    ev = evidence(state,value,"exact checker failure")
    seen = []
    def reissue(*args):
        assert all(actual is wanted for actual,wanted in zip(args,(src,state,svc,ev)))
        seen.append("reissue")
        return checks.Result(checks.Status.UNAVAILABLE)
    def forbidden(*args,**kwargs):
        raise AssertionError("spoken checker findings must not start a replan")
    definition = replace(checks.DEFINITION,reissue=reissue,replan=forbidden)
    out = checks.Selected(definition).resume(lambda:src,state,lambda:svc,lambda:ev,lambda:judgments)
    assert seen == ["reissue"]
    assert out == checks.Result(checks.Status.OBSERVED,
        text=prompts.render("periodic_gate",truth="exact checker failure"),outcome=value)
    assert state.last_gate_red and not state.periodic_probe and not state.periodic_replan_done


def test_selected_resume_without_pending_work_calls_no_nested_hook_or_reader():
    def forbidden(*args,**kwargs):
        raise AssertionError("idle resume invoked a hook or evidence reader")
    state = loop.GuardState()
    before = copy.deepcopy(vars(state))
    definition = replace(checks.DEFINITION,reissue=forbidden,replan=forbidden)
    ev = checks.EvidenceServices(forbidden,forbidden,forbidden,forbidden)
    out = checks.Selected(definition).resume(source,state,probes,lambda:ev,
                                             lambda:checks.JudgmentServices(forbidden,forbidden))
    assert out == checks.Result(checks.Status.NOT_DUE) and vars(state) == before

