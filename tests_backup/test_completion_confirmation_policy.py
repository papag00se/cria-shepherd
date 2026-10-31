"""Shared confirmation source cohort; scripted inspection, no filesystem/model.

Legacy-named cases retain their incident coverage with independent expected
outcomes. No old confirmation policy executes as a semantic oracle.
"""
import copy
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cria import completionconfirmation as confirmation, loop, prompts, verifytools
from cria.config import Role


class Log:
    phase = ""
    def __init__(self):
        self.events = []
    def emit(self, name, **fields):
        self.events.append((name,fields))


def completion(text, rounds=0, finish="stop", calls=None):
    message = {"role":"assistant","content":text}
    if calls:
        message["tool_calls"] = calls
    return {"choices":[{"message":message,"finish_reason":finish}],loop.ROUNDS_KEY:rounds}


def readers(role=None):
    return confirmation.Readers(loop._completion_text,role.clean_content if role else lambda text:text,
                                loop._consistent_word,loop.verdict_from_unclosed)


def facts(top=("a.py",),surveyed=True):
    return confirmation.Facts(lambda root:surveyed,lambda root:list(top) if top is not None else None)


def source(**kwargs):
    defaults = dict(claim="Write the implementation",reason="the work is complete",workspace_root="/workspace",
                    phase="satisfaction-confirm",log=Log(),measured_facts="CHECKER: literal 雪\nexit=0",original_task="original full task")
    defaults.update(kwargs)
    return confirmation.Input(**defaults)


def services(replies, *, role=None, workspace=None, diagnosis=lambda request:""):
    replies = iter(copy.deepcopy(replies))
    calls = []
    def inspect(request):
        calls.append(request)
        comp = next(replies)
        pending = tuple(call.get("id","") for choice in comp.get("choices",[])
                        for call in (choice.get("message") or {}).get("tool_calls") or [])
        return confirmation.InspectionReply(comp,loop.inspection_rounds(comp),pending)
    return confirmation.Services(workspace or facts(),inspect,readers(role),diagnosis),calls


def event(name, **fields):
    return name, {"assist_id":"approval-inspection-confirmation", "family_id":"F34",
                  "phase":"satisfaction-confirm", **fields}


UNVERIFIED = prompts.load("unverified_step")
UNPARSED = event("loop.confirm_unparsed", level="warn")
NO_LOOK = event("loop.confirm_without_looking", level="warn")
RESTATE = event("loop.confirm_restated_claim", level="warn", head="the work is complete")


def assert_requests(request, sent, escalated):
    labels = prompts.load_map("verify_confirm")
    user = prompts.fill(labels["user"], step=request.claim, reason=request.reason or "(none stated)")
    if request.measured_facts:
        user += prompts.fill(prompts.load("confirm_cria_facts"), facts=request.measured_facts)
    assert sent == [confirmation.InspectionRequest(
        labels["system"], user + ("\n\n" + labels["restate"] if extra else ""),
        request.workspace_root, request.phase, True, verifytools.ANSWER_NOW_CONSISTENT) for extra in escalated]


@pytest.mark.parametrize("replies,status,reason,attempts,events", [
    ([completion('{"consistent":true,"why":"inspected"}',1)], "CONFIRMED", "inspected", [(1,True,"inspected")], []),
    ([completion("CONSISTENT\nlooked",2)], "CONFIRMED", "looked", [(2,True,"looked")], []),
    ([completion("INCONSISTENT\nunsupported prose")], "REJECTED", "", [(0,False,"unsupported prose")], []),
    ([completion('{"consistent":false,"why":"a specific contradiction"}')], "REJECTED", "", [(0,False,"a specific contradiction")], []),
    ([completion("unreadable")], "UNVERIFIED", UNVERIFIED, [(0,None,"")], [UNPARSED]),
    ([completion('{"consistent":"true"}')], "UNVERIFIED", UNVERIFIED, [(0,None,"")], [UNPARSED]),
    ([completion('{"consistent":false,"why":"cut quote"')], "REJECTED", "", [(0,False,"cut quote")],
     [("loop.verdict_from_unclosed", {"level":"info","phase":"satisfaction-confirm","flag":"consistent","reason":"cut quote"})]),
    ([completion('{"consistent":true,"why":"cut quote"')], "UNVERIFIED", UNVERIFIED, [(0,None,"")], [UNPARSED]),
    ([completion('{"consistent":false,"why":"cut quote"',finish="length")], "UNVERIFIED", UNVERIFIED, [(0,None,"")], [UNPARSED]),
    ([completion("CONSISTENT"),completion("CONSISTENT",1)], "CONFIRMED", "", [(0,True,""),(1,True,"")], [NO_LOOK]),
    ([completion("CONSISTENT"),completion("CONSISTENT")], "UNVERIFIED", UNVERIFIED, [(0,True,""),(0,True,"")],
     [NO_LOOK,event("loop.confirm_without_looking_twice",level="warn")]),
    ([completion('{"consistent":false,"why":"the work is complete"}'),completion("CONSISTENT",1)],
     "CONFIRMED", "", [(0,False,"the work is complete"),(1,True,"")], [RESTATE]),
    ([completion('{"consistent":false,"why":"the work is complete"}')]*2, "UNVERIFIED", UNVERIFIED,
     [(0,False,"the work is complete"),(0,False,"the work is complete")],
     [RESTATE,event("loop.confirm_restated_twice",level="warn")]),
    ([completion("CONSISTENT"),completion('{"consistent":false,"why":"the work is complete"}'),completion("unreadable")],
     "UNVERIFIED", UNVERIFIED, [(0,True,""),(0,False,"the work is complete"),(0,None,"")], [NO_LOOK,RESTATE,UNPARSED]),
])
def test_confirmation_matches_original_questions_results_and_counts(replies,status,reason,attempts,events):
    # Keep the canonical regression symbol; the old-body oracle is retired.
    role = Role(name="reasoner",backend="local",reasoning="on")
    request = source()
    svc,calls = services(replies,role=role)
    actual = confirmation.confirm(request,svc)
    assert actual.status is confirmation.Status[status]
    assert (actual.confirmed,actual.observed,actual.reason) == (status == "CONFIRMED",True,reason)
    assert actual.authority is confirmation.Authority.TASK
    assert actual.attempts == tuple(confirmation.Attempt(i,rounds,verdict,why)
                                   for i,(rounds,verdict,why) in enumerate(attempts,1))
    assert len(calls) == len(attempts)
    assert_requests(request,calls,[False] + [True] * (len(attempts)-1))
    assert role.reasoning == "on"  # transport adapter owns the OFF copy, never this caller's role
    assert request.log.events == events
    assert tuple(actual) == (status == "CONFIRMED",reason)


@pytest.mark.parametrize("root,surveyed,top,status,confirmed,observed,reason,count,events", [
    ("",True,(),"UNCHECKED",True,False,"",0,
     [event("loop.confirm_unchecked",level="warn",why="no workspace root")]),
    ("/workspace",False,(),"UNCHECKED",True,False,"",0,
     [event("loop.confirm_unchecked",level="warn",why="workspace not surveyed")]),
    ("/workspace",True,(),"ABSENT",False,True,prompts.render("confirm_absent_artifact",artifact="report.md"),0,
     [event("loop.confirm_absent_artifact",level="info",artifact="report.md")]),
    ("/workspace",True,(".git",),"ABSENT",False,True,prompts.render("confirm_absent_artifact",artifact="report.md"),0,
     [event("loop.confirm_absent_artifact",level="info",artifact="report.md")]),
    ("/workspace",True,None,"CONFIRMED",True,True,"",1,[]),
    ("/workspace",True,("file.txt",),"CONFIRMED",True,True,"",1,[]),
])
def test_literal_detector_and_unchecked_exception_match_original(root,surveyed,top,status,confirmed,observed,reason,count,events):
    request = source(claim="Write `report.md`",workspace_root=root)
    svc,calls = services([completion("CONSISTENT",1)],workspace=facts(top,surveyed))
    actual = confirmation.confirm(request,svc)
    assert (actual.status,actual.confirmed,actual.observed,actual.reason) == (
        confirmation.Status[status],confirmed,observed,reason)
    assert actual.attempts == ((confirmation.Attempt(1,1,True,""),) if count else ())
    assert len(calls) == count
    assert_requests(request,calls,[False] if count else [])
    assert request.log.events == events


@pytest.mark.parametrize("claim,expected", [("Inspect https://api.handle.me/report.md",""),
    ("Read api.handle.me",""),("Write x.py","x.py"),("Read config.json","config.json")])
def test_empty_workspace_literal_and_domain_support_parity(claim,expected):
    assert confirmation.absent_artifact(claim,"/workspace",facts(())) == expected


def test_latest_attempt_rounds_do_not_carry_between_reasks():
    request = source()
    replies = [completion('{"consistent":false,"why":"the work is complete"}',2),completion("CONSISTENT",0)]
    # Incident: a restatement re-ask once borrowed the previous answer's look.
    svc,calls = services(replies)
    actual = confirmation.confirm(request,svc)
    assert not actual.confirmed and actual.observed
    assert actual.reason == UNVERIFIED
    assert actual.status is confirmation.Status.UNVERIFIED
    assert len(calls) == 2
    assert actual.attempts == (confirmation.Attempt(1,2,False,"the work is complete"),
                               confirmation.Attempt(2,0,True,""))
    assert_requests(request,calls,[False,True])
    assert request.log.events == [RESTATE,NO_LOOK]


@pytest.mark.parametrize("cut,pending", [(True,False),(False,True),(False,"missing-id")])
def test_readable_cut_and_pending_reply_necessarily_diverges_from_current_owner(cut,pending):
    # Incident: balanced public bytes once approved a cut or unanswered call.
    # Preserve the corrected result, never execute the unsafe baseline.
    calls = [{**({"id":"still-reading"} if pending is True else {}),"type":"function","function":{"name":"read_file","arguments":'{"path":"a.py"}'}}] if pending else None
    reply = completion('{"consistent":true,"why":"balanced bytes"}',1,finish="length" if cut else "stop",calls=calls)
    request = source()
    before = copy.deepcopy(reply)
    svc,sent = services([reply])
    inspected = []
    raw_inspect = svc.inspect
    def inspect(query):
        response = raw_inspect(query)
        inspected.append(response.completion)
        return response
    result = confirmation.confirm(request,replace(svc,inspect=inspect))
    assert not result.confirmed and result.observed and len(sent) == 1
    assert result.status is confirmation.Status.UNVERIFIED and result.reason == UNVERIFIED
    ids = ("still-reading",) if pending is True else ("",) if pending else ()
    assert result.attempts == (confirmation.Attempt(1,1,None,"",ids),)
    assert inspected == [before]
    assert_requests(request,sent,[False])
    assert request.log.events == [UNPARSED]


def test_no_private_approval_or_diagnosis_can_rescue_unknown():
    comp = completion("garbage")
    comp["choices"][0]["message"]["reasoning_content"] = '{"consistent":true}'
    def forbidden(*args):
        raise AssertionError("unknown confirmation must not call diagnosis or another judge")
    svc,sent = services([comp],diagnosis=forbidden)
    result = confirmation.confirm(source(),svc)
    assert not result.confirmed and len(sent) == 1


def test_rejected_diagnosis_receives_original_task_and_cannot_approve():
    seen = []
    verdict = {"consistent":False,"why":"contradiction","diagnosis_kind":"missing_content"}
    def diagnose(request):
        seen.append(request)
        return ""  # withheld by F36; negative confirmation must remain negative
    request = source()
    svc,_ = services([completion(json.dumps(verdict))],diagnosis=diagnose)
    result = confirmation.confirm(request,svc)
    assert not result.confirmed and result.reason == "" and result.status is confirmation.Status.REJECTED
    assert seen == [confirmation.DiagnosisInput(verdict,request.claim,request.original_task,request.measured_facts,
                                               request.workspace_root,request.phase+"-diagnosis")]


def test_latest_workspace_and_claim_are_read_again_without_approval_cache():
    top = ["a.py"]
    current = confirmation.Facts(lambda root:True,lambda root:list(top))
    svc,sent = services([completion("CONSISTENT",1)],workspace=current)
    first = confirmation.confirm(source(),svc)
    assert first.confirmed
    top.clear()
    second = confirmation.confirm(source(claim="Write new.md"),svc)
    assert not second.confirmed and second.status is confirmation.Status.ABSENT
    assert first.confirmed and len(sent) == 1 and not second.attempts
    other,other_sent = services([completion("unreadable")])
    reset = confirmation.confirm(source(),other)
    assert not reset.confirmed and len(reset.attempts) == len(other_sent) == 1


def test_unchecked_is_explicit_not_an_observed_positive_or_workspace_absence():
    def forbidden(*args):
        raise AssertionError("unreachable workspace cannot inspect or manufacture an absence")
    svc = confirmation.Services(confirmation.Facts(lambda root:False,forbidden),forbidden,
                                confirmation.Readers(forbidden,forbidden,forbidden,forbidden),forbidden)
    out = confirmation.confirm(source(),svc)
    assert out.status is confirmation.Status.UNCHECKED and out.confirmed and not out.observed
    assert not out.attempts


def test_measured_facts_and_reasks_keep_exact_bytes_and_never_add_coder_narrative():
    request = source(reason="",measured_facts="test literal 雪\n"+"checker line\n"*100)
    svc,sent = services([completion("CONSISTENT"),completion("CONSISTENT",1)])
    confirmation.confirm(request,svc)
    labels = prompts.load_map("verify_confirm")
    expected = prompts.fill(labels["user"],step=request.claim,reason="(none stated)")
    expected += prompts.fill(prompts.load("confirm_cria_facts"),facts=request.measured_facts)
    assert sent[0].user == expected and sent[1].user == expected+"\n\n"+labels["restate"]
    assert sent[0].force_think_off and sent[0].answer_now_simple == verifytools.ANSWER_NOW_CONSISTENT
    assert sent[0].system == labels["system"]
    assert request.original_task not in sent[0].user


def test_inspection_exception_propagates_without_settlement_or_fallback():
    def failed(request):
        raise RuntimeError("fake provider error")
    svc,_ = services([])
    with pytest.raises(RuntimeError,match="fake provider error"):
        confirmation.confirm(source(),replace(svc,inspect=failed))
    fresh,sent = services([completion("CONSISTENT",1)])
    assert confirmation.confirm(source(),fresh).confirmed and len(sent) == 1


def test_disabled_replacement_and_explicit_step_consent():
    def forbidden(*args):
        raise AssertionError("disabled confirmation gathered facts or called a provider")
    for binding,authority in [(confirmation.Selection(None,5,True),confirmation.Authority.TASK),
        (confirmation.Selection(confirmation.DEFINITION,3,True),confirmation.Authority.TASK),
        (confirmation.Selection(confirmation.DEFINITION,5,False),confirmation.Authority.STEP),
        (confirmation.Selection(confirmation.DEFINITION,4,True),confirmation.Authority.STEP),
        (confirmation.Selection(confirmation.DEFINITION,5,"false"),confirmation.Authority.STEP),
        (confirmation.Selection(confirmation.DEFINITION,5,1),confirmation.Authority.STEP)]:
        result = binding.run(authority,forbidden,forbidden)
        assert result.status is confirmation.Status.NOT_SELECTED and not result.confirmed and not result.observed
    with pytest.raises(ValueError,match="authority"):
        confirmation.Selection(confirmation.DEFINITION,5,True).run("step",forbidden,forbidden)
    called = []
    def replacement(request,svc):
        called.append(request)
        return confirmation.Result(confirmation.Status.REJECTED,authority=request.authority)
    definition = replace(confirmation.DEFINITION,execute=replacement)
    binding = confirmation.Selection(definition,5,True)
    binding.run(confirmation.Authority.STEP,lambda:source(authority=confirmation.Authority.STEP),lambda:None)
    assert len(called) == 1
    with pytest.raises(ValueError,match="authority"):
        binding.run(confirmation.Authority.STEP,source,forbidden)


def test_real_shared_inspection_pairs_tool_ids_and_counts_only_its_own_rounds():
    log = Log()
    role = Role(name="reasoner",backend="local",reasoning="on")
    bodies = []
    replies = [completion("",calls=[{"id":"read-unique","type":"function","function":{
        "name":"read_file","arguments":'{"path":"a.py"}'}}]),completion("CONSISTENT\nchecked literal",1)]
    replies = iter(replies)
    def chat(body,rlog):
        bodies.append(copy.deepcopy(body))
        return json.dumps(next(replies)).encode()
    def inspect(request):
        comp = loop._judge_completion(chat,replace(role,reasoning="off"),request.system,request.user,log,
            phase=request.phase,workspace_root=request.workspace_root,force_think_off=request.force_think_off,
            answer_now_simple=request.answer_now_simple)
        pending = tuple(tc.get("id","") for choice in comp.get("choices",[])
                        for tc in (choice.get("message") or {}).get("tool_calls") or [])
        return confirmation.InspectionReply(comp,loop.inspection_rounds(comp),pending)
    svc = confirmation.Services(facts(),inspect,readers(role),lambda request:"")
    view = SimpleNamespace(surveyed=True)
    with patch.object(loop.wsview,"current",return_value=view), \
         patch.object(verifytools,"execute",return_value="literal a.py source") as execute:
        out = confirmation.confirm(source(log=log),svc)
    assert out.confirmed and out.attempts[0].rounds == 1 and len(bodies) == 2
    execute.assert_called_once_with("read_file",{"path":"a.py"},"/workspace")
    paired = [message for message in bodies[1]["messages"] if message.get("role") == "tool"]
    assert paired == [{"role":"tool","tool_call_id":"read-unique","content":"literal a.py source"}]
    event = next(fields for name,fields in log.events if name == "loop.verify_inspect")
    assert event == {"round":1,"calls":1}
    assert role.reasoning == "on" and not out.attempts[0].pending_ids
    assert bodies[0]["chat_template_kwargs"]["enable_thinking"] is False


@pytest.mark.parametrize("surveyed,rounds,scheduled,expected", [
    (True,1,False,"APPROVED"),(True,0,False,"REJECTED"),(False,0,True,"UNOBSERVED"),
])
def test_real_step_owner_uses_shared_confirmation_without_task_release(surveyed,rounds,scheduled,expected):
    from cria import stepreview
    from tests.test_optional_step_policy import make
    request,_,_,_,_,_ = make([{"done":True,"reason":"the work is complete"}],workspace_root="/workspace")
    svc,sent = services([completion("CONSISTENT",rounds)]*2,workspace=facts(surveyed=surveyed))
    binding = confirmation.Selection(confirmation.DEFINITION,5,planning_enabled=True)
    def confirm_step(item):
        return binding.run(confirmation.Authority.STEP,
            lambda:source(claim=item.step,reason=item.reason,workspace_root=item.workspace_root,
                original_task=item.original_task,measured_facts=item.participation_facts,
                phase=item.phase,authority=confirmation.Authority.STEP),lambda:svc)
    request = replace(request,services=replace(request.services,confirm=confirm_step),
        trigger=stepreview.StepTrigger.SCHEDULED if scheduled else stepreview.StepTrigger.CLAIM)
    result = stepreview.StepSelection.opt_in().run(request)
    assert result.status.name == expected
    assert result.confirmation.authority is confirmation.Authority.STEP
    assert not hasattr(result,"task_complete")
    if not surveyed:
        assert not sent and not result.confirmation.observed
        assert result.effect.action is stepreview.StepAction.OBSERVE_WORKSPACE
    else:
        assert len(sent) == (1 if rounds else 2)


def test_cross_branch_reasks_preserve_original_order_and_three_call_bound():
    request = source()
    replies = [completion("CONSISTENT"),completion('{"consistent":false,"why":"the work is complete"}',2),
               completion("CONSISTENT")]
    svc,sent = services(replies)
    actual = confirmation.confirm(request,svc)
    # Incident: the third answer cannot borrow the second answer's look.
    assert not actual.confirmed and actual.observed
    assert actual.status is confirmation.Status.UNVERIFIED and actual.reason == UNVERIFIED
    assert len(sent) == 3
    assert actual.attempts == (confirmation.Attempt(1,0,True,""),
        confirmation.Attempt(2,2,False,"the work is complete"),confirmation.Attempt(3,0,True,""))
    assert_requests(request,sent,[False,True,True])
    assert request.log.events == [NO_LOOK,RESTATE,NO_LOOK]


@pytest.mark.parametrize("stage", [1,2,3])
@pytest.mark.parametrize("invalid", ["cut-json","cut-word","call-missing-id","pending-only"])
def test_every_reask_checks_integrity_before_reading_a_positive(stage,invalid):
    prefix = [] if stage == 1 else [completion("CONSISTENT")] if stage == 2 else [
        completion("CONSISTENT"),completion('{"consistent":false,"why":"the work is complete"}',2)]
    calls = [{"type":"function","function":{"name":"read_file","arguments":'{"path":"a.py"}'}}] if invalid == "call-missing-id" else None
    bad = completion("CONSISTENT" if invalid == "cut-word" else '{"consistent":true}',1,
        finish="length" if invalid.startswith("cut-") else "stop",calls=calls)
    request = source()
    # The unsafe baseline read balanced positive bytes before checking integrity.
    # Each attempt position must instead withhold before any public verdict read.
    svc,sent = services(prefix+[bad])
    raw_inspect = svc.inspect
    def inspect(query):
        reply = raw_inspect(query)
        # Simulate an adapter that omits IDs even on a call-bearing reply. The
        # final call itself must still block; IDs alone also independently block.
        return replace(reply,pending_ids=("unanswered",) if invalid == "pending-only" and len(sent) == stage else ())
    reads = []
    def read(comp):
        reads.append(comp)
        return loop._completion_text(comp)
    def forbidden(*args):
        raise AssertionError("invalid positive must not recover or diagnose")
    svc = replace(svc,inspect=inspect,readers=replace(svc.readers,public_text=read,recover_negative=forbidden),diagnose=forbidden)
    result = confirmation.confirm(request,svc)
    assert not result.confirmed and result.status is confirmation.Status.UNVERIFIED
    assert result.reason == prompts.load("unverified_step")
    assert len(sent) == stage and len(reads) == len(prefix)
    expected_prefix = [confirmation.Attempt(1,0,True,"")] if stage == 2 else [
        confirmation.Attempt(1,0,True,""),confirmation.Attempt(2,2,False,"the work is complete")] if stage == 3 else []
    ids = ("unanswered",) if invalid == "pending-only" else ()
    assert result.attempts == tuple(expected_prefix + [confirmation.Attempt(stage,1,None,"",ids)])
    assert result.observed
    assert_requests(request,sent,[False] + [True] * (stage-1))
    expected_events = [UNPARSED] if stage == 1 else [NO_LOOK,UNPARSED] if stage == 2 else [NO_LOOK,RESTATE,UNPARSED]
    assert request.log.events == expected_events


@pytest.mark.parametrize("evidence,error", [({"incomplete":True},None),({"content_is_non_action":True},None),
    ({},{"type":"invalid_model_output_error"}),({},{"type":"incomplete_stream_error"})])
def test_shared_generation_validity_cannot_be_bypassed_by_balanced_public_bytes(evidence,error):
    from cria import generation
    bad = completion('{"consistent":true}',1)
    bad[generation.EVIDENCE] = evidence
    if error:
        bad["error"] = error
    svc,sent = services([bad])
    def forbidden(*args):
        raise AssertionError("unusable reply reached verdict readers")
    svc = replace(svc,readers=confirmation.Readers(forbidden,forbidden,forbidden,forbidden),diagnose=forbidden)
    out = confirmation.confirm(source(),svc)
    assert not out.confirmed and out.status is confirmation.Status.UNVERIFIED and len(sent) == 1
