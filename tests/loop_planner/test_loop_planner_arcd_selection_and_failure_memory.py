"""Planner selection and failure memory through the real entry (Planner.plan_for). Planning is OFF by policy: every
Planner here is opted in explicitly (PlanningSelection.opt_in) or explicitly OFF; nothing is enabled by default.

Contracts re-expressed from the pre-reset suite: OFF does no detection/calls/state change; a selected replacement
runs INSTEAD of the stock stage; an unusable outcome is remembered per session/frame (and forgotten on reset), never
for a read that has not been delivered yet; concurrent exchanges share nothing."""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from unittest.mock import patch

import pytest

from cria import planner, wsview
from cria.config import Role
from cria.planner import PlanningSelection, ReadinessInput, ReadinessResult, RevisionInput

from loop_planner_helpers import Rlog

TASK = "Write the requested report"
REASONER = Role(name="reasoner", backend="local")


@pytest.fixture(autouse=True)
def local_view():
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)


def turns(root=""):
    return ([{"role": "user", "content": f"<cwd>{root}</cwd>"}] if root else []) + [{"role": "user", "content": TASK}]


class Provider:
    """submit_plan -> one step; other tools -> 'ready'; no tools -> NONE. `unreadable` answers every call 'not a plan'."""
    def __init__(self, unreadable=False):
        self.bodies, self.unreadable = [], unreadable

    def chat(self, body, log):
        self.bodies.append(body)
        names = {t["function"]["name"] for t in body.get("tools", ())}
        if self.unreadable:
            message = {"content": "not a plan"}
        elif "submit_plan" in names:
            message = {"tool_calls": [{"id": "p", "type": "function", "function": {
                "name": "submit_plan", "arguments": json.dumps({"steps": [TASK]})}}]}
        else:
            message = {"content": "ready to draft" if names else "NONE"}
        return json.dumps({"choices": [{"message": message}]}).encode()


@pytest.mark.parametrize("per_call", [False, True])
def test_an_off_selection_never_detects_calls_the_model_or_touches_failure_memory(per_call):
    provider, log = Provider(), Rlog()
    owner = planner.Planner(provider, policies=PlanningSelection.opt_in() if per_call else PlanningSelection())
    kwargs = {"policies": PlanningSelection()} if per_call else {}
    outcome, before = planner.PlanOutcome(survey_pending=True), dict(owner.__dict__)
    with patch.object(planner, "latest_user_text", side_effect=AssertionError("detected while off")):
        assert owner.plan_for(turns(), log, outcome=outcome, **kwargs) is None
    assert provider.bodies == [] and log.events == [] and owner.__dict__ == before and outcome.survey_pending
    assert not PlanningSelection().bindings("experimental-plan-gather")


def test_selected_replacements_run_instead_of_the_stock_stages_in_order_and_never_rewire_the_constructor(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {}}')
    seen, constructor = [], PlanningSelection()

    def coverage(ask, task, steps):
        seen.append(("coverage", tuple(steps)))
        return []

    def readiness(source):
        seen.append(("readiness", source.manifest()))
        return ReadinessResult("READY", True)

    def revision(source):
        seen.append(("revision", source.steps))
        assert source.coverage is coverage
        return planner.RevisionResult(("Write a revised report",))
    selected = PlanningSelection.opt_in(replacements=(
        replace(planner.COVERAGE, execute=coverage), replace(planner.READINESS, execute=readiness),
        replace(planner.REVISION, execute=revision)))
    owner = planner.Planner(Provider(), role=REASONER, policies=constructor)
    result = owner.plan_for(turns(str(tmp_path)), Rlog(), session_key="s", policies=selected)
    assert [i.text for i in result.items] == ["Write a revised report"]
    assert seen == [("coverage", (TASK,)), ("readiness", '{"scripts": {}}'), ("revision", (TASK,))]
    assert owner._policies is constructor and not constructor.enabled


def test_a_replaced_gather_is_the_only_gather_and_a_disabled_stage_does_no_work(tmp_path):
    plan = planner.Plan(id="r", task=TASK, created="fixture", items=[planner.PlanItem(text="Replacement step")])
    seen, provider = [], Provider()
    gather = lambda owner, turns_, log, prior, rewrite, outcome, session: seen.append((prior, rewrite, session)) or plan
    owner = planner.Planner(provider, policies=PlanningSelection.opt_in(replacements=(replace(planner.GATHER, execute=gather),)))
    assert owner.plan_for(turns(), Rlog(), "prior", "rewrite", planner.PlanOutcome(), "s") is plan
    assert seen == [("prior", "rewrite", "s")] and provider.bodies == []
    (tmp_path / "package.json").write_text('{"scripts": {}}')
    only_gather = PlanningSelection.opt_in(disabled=tuple(d.policy.id for d in (planner.COVERAGE, planner.READINESS, planner.REVISION)))
    owner = planner.Planner(provider, role=REASONER, policies=only_gather)
    with patch.object(planner, "package_manifest_without_test_script", side_effect=AssertionError("read while off")):
        assert [i.text for i in owner.plan_for(turns(str(tmp_path)), Rlog(), session_key="s").items] == [TASK]


def test_an_unusable_outcome_is_remembered_per_session_and_frame_and_forgotten_on_reset():
    provider = Provider(unreadable=True)
    owner = planner.Planner(provider, policies=PlanningSelection.opt_in())

    def calls(**kw):
        before = len(provider.bodies)
        assert owner.plan_for(kw.pop("msgs", turns()), Rlog(), **kw) is None
        return len(provider.bodies) - before
    assert calls(session_key="a") > 0 and calls(session_key="a") == 0       # the same ask is not re-drafted
    assert calls(session_key="fork") > 0                                      # a fork has its own memory
    assert calls(session_key="a", prior_work="Prior completed work") > 0      # a continuation frame is a different key
    assert calls(session_key="a", rewrite_summary="Harness retained scope") > 0
    assert calls(session_key="a", msgs=turns() + [{"role": "user", "content": "A different required report"}]) > 0
    owner.reset("a")
    assert calls(session_key="fork") == 0 and calls(session_key="a") > 0       # reset is scoped to the session
    owner.reset()
    assert owner._plans == {} and owner._admission_exhaustions == {} and not owner._retriable_failure


@pytest.mark.parametrize("per_call", [False, True])
def test_a_workspace_read_that_has_not_been_delivered_is_deferred_not_negatively_cached(per_call):
    class Reader(Provider):
        def chat(self, body, log):
            self.bodies.append(body)
            return json.dumps({"choices": [{"message": {"tool_calls": [{"id": "r", "type": "function", "function": {
                "name": "read_file", "arguments": '{"path":"report.txt"}'}}]}}]}).encode()
    provider, selected = Reader(), PlanningSelection.opt_in()
    owner = planner.Planner(provider, policies=PlanningSelection() if per_call else selected)
    kwargs, outcome = ({"policies": selected} if per_call else {}), planner.PlanOutcome()
    view = wsview.View("/workspace", "arcd-pending")
    view._ingest_tree("F\t1\t10\treport.txt\n")      # listed by the harness, body never delivered
    token = wsview.bind(view)
    try:
        assert owner.plan_for(turns("/workspace"), Rlog(), outcome=outcome, session_key="s", **kwargs) is None
        assert outcome.survey_pending and owner._plans == {}
        owner.plan_for(turns("/workspace"), Rlog(), outcome=outcome, session_key="s", **kwargs)
        assert len(provider.bodies) == 2            # asked again: nothing was cached against the missing body
    finally:
        wsview.unbind(token)


def test_a_drafter_that_keeps_calling_tools_is_retriable_and_never_poisons_the_cache(tmp_path):
    (tmp_path / "report.txt").write_text("hello\n")

    class Wanderer(Provider):
        def chat(self, body, log):
            self.bodies.append(body)
            return json.dumps({"choices": [{"message": {"tool_calls": [{"id": "r", "type": "function", "function": {
                "name": "read_file", "arguments": '{"path":"report.txt"}'}}]}}]}).encode()
    provider = Wanderer()
    owner = planner.Planner(provider, role=REASONER, max_gather_rounds=1, policies=PlanningSelection.opt_in())
    assert owner.plan_for(turns(str(tmp_path)), Rlog(), session_key="s") is None
    asked = len(provider.bodies)
    assert owner._retriable_failure and owner._plans == {} and asked > 0
    assert owner.plan_for(turns(str(tmp_path)), Rlog(), session_key="s") is None and len(provider.bodies) > asked


def test_concurrent_exchanges_do_not_share_failure_direction_or_research_facts():
    barrier, observed = Barrier(2), {}

    def gather(owner, turns_, log, prior, rewrite, outcome, session):
        owner._gather_facts = {session: ("HTTP 200", (), (), (), "")}
        owner._retriable_failure = session == "a"
        barrier.wait(timeout=5)
        observed[session] = (dict(owner._gather_facts), owner._retriable_failure)
        return None
    owner = planner.Planner(Provider(), policies=PlanningSelection.opt_in(replacements=(replace(planner.GATHER, execute=gather),)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = (pool.submit(owner.plan_for, turns(), Rlog(), session_key=k) for k in "ab")
        assert a.result() is None and b.result() is None
    assert observed == {"a": ({"a": ("HTTP 200", (), (), (), "")}, True), "b": ({"b": ("HTTP 200", (), (), (), "")}, False)}


@pytest.mark.parametrize("answer,verdict", [
    ("TEST_EXECUTION_PATH_READY", "READY"), ("MISSING_TEST_EXECUTION_PATH", "MISSING"), ("NOT_APPLICABLE", "NOT_APPLICABLE"),
    ("", "UNDECIDABLE"), ("possibly ready", "UNDECIDABLE")])
def test_readiness_honors_only_typed_judgments_and_unknown_evidence_is_never_judged(answer, verdict):
    asked = []
    result = planner.READINESS.execute(ReadinessInput(lambda s, u: asked.append(u) or answer, "add tests", ("Write tests",), lambda: "{}"))
    assert result == ReadinessResult(verdict, True) and "Write tests" in asked[0] and "{}" in asked[0]

    def forbidden(*_):
        raise AssertionError("unknown evidence cannot trigger a judgment")
    assert planner.READINESS.execute(ReadinessInput(forbidden, "t", (), lambda: None)) == ReadinessResult("NOT_APPLICABLE")
    assert planner.READINESS.execute(ReadinessInput(None, "t", (), lambda: "{}")) == ReadinessResult("UNDECIDABLE", True)


def test_a_revision_without_a_reasoner_keeps_the_plan_and_says_the_judgment_was_withheld():
    result = planner.REVISION.execute(RevisionInput("task", ("Write report",), "", None, Rlog()))
    assert result.steps == ("Write report",) and result.withheld and not result.dropped
