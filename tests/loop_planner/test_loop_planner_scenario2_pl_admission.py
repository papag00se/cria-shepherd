"""Planner-ON plan admission through the real entry point, Planner.plan_for (planning is opted into explicitly in each Planner).

Flow: the drafter submits steps; cria's checks (deliverable coverage, a package without a test script, the drafter's own tool
slips) either admit them, hand them back ONCE with a steer and re-draft, or give up with a named exhaustion. Only the model
boundary is scripted."""
import json

import pytest

from cria import planner, wsview
from cria.config import Role

from loop_planner_helpers import Rlog

TASK = "Write report.js and tests for it."
BASE = ["Write report.js", "Write report.test.js"]
RUN = BASE + ["Run node --test report.test.js"]


@pytest.fixture(autouse=True)
def local_view():
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)


def reply(message):
    return json.dumps({"choices": [{"finish_reason": "stop", "message": message}]}).encode()


def submit(*steps):
    return {"tool_calls": [{"id": "s", "type": "function", "function": {
        "name": "submit_plan", "arguments": json.dumps({"steps": list(steps)})}}]}


class Drafter:
    """`drafts` are the drafter's successive messages; `coverage` / `readiness` the focused judges' successive answers."""
    def __init__(self, drafts, coverage=("[]",), readiness=()):
        self.drafts, self.coverage, self.readiness, self.steers = list(drafts), list(coverage), list(readiness), []

    def chat(self, body, log):
        names = {t["function"]["name"] for t in body.get("tools") or ()}
        system = body["messages"][0]["content"]
        if names == {"submit_plan"}:
            self.steers.append(str(body["messages"][-1]["content"]))
            return reply(self.drafts.pop(0) if len(self.drafts) > 1 else self.drafts[0])
        if names:
            return reply({"content": "Ready to submit the plan."})
        if "TEST_EXECUTION_PATH_READY" in system:
            return reply({"content": self.readiness.pop(0) if len(self.readiness) > 1 else self.readiness[0]})
        if '"missing"' in system:
            return reply({"content": json.dumps({"missing": json.loads(self.coverage.pop(0) if len(self.coverage) > 1 else self.coverage[0])})})
        return reply({"content": '{"lost": ""}' if '"lost"' in system else "NONE"})


def admit(tmp_path, drafter, manifest=None):
    if manifest is not None:
        (tmp_path / "package.json").write_text(manifest)
    owner = planner.Planner(drafter, role=Role(name="reasoner", backend="local"), max_gather_rounds=1,
                            policies=planner.PlanningSelection.opt_in())
    rlog = Rlog()
    messages = [{"role": "user", "content": f"<environment_context><cwd>{tmp_path}</cwd></environment_context>"},
                {"role": "user", "content": TASK}]
    plan = owner.plan_for(messages, rlog, session_key="sid:adm")
    return plan, rlog, owner


def facts(rlog, kind):
    return [kw for k, kw in rlog.events if k == kind]


def test_a_draft_that_omits_a_deliverable_is_handed_back_once_and_the_redraft_is_admitted(tmp_path):
    drafter = Drafter([submit("Write report.js"), submit(*BASE)], coverage=['["tests"]', "[]"])
    plan, rlog, _ = admit(tmp_path, drafter)
    assert [i.text for i in plan.items] == BASE
    assert [(e["missing"], e["handed_back"]) for e in facts(rlog, "plan.missing_deliverables")] == [("tests", True)]
    assert "tests" in drafter.steers[-1] and facts(rlog, "plan.submitted")[-1]["steps"] == 2


def test_a_redraft_that_still_omits_the_same_deliverable_is_refused_and_named_not_silently_adopted(tmp_path):
    plan, rlog, _ = admit(tmp_path, Drafter([submit("Write report.js")], coverage=['["tests"]']))
    assert plan is None and not facts(rlog, "plan.submitted")
    assert [e["handed_back"] for e in facts(rlog, "plan.missing_deliverables")] == [True, False] * 2     # handed back once per gather, twice gathered
    assert [e["check"] for e in facts(rlog, "plan.rejected_exhausted")] == ["coverage"] * 2
    assert [(e["check"], e["count"]) for e in facts(rlog, "plan.admission_given_up")] == [("coverage", 2)]


@pytest.mark.parametrize("manifest,verdicts,given_up,steps", [
    ('{"scripts": {}}', ["MISSING_TEST_EXECUTION_PATH", "TEST_EXECUTION_PATH_READY"], None, RUN),    # handed back, redrafted with a path
    ('{"scripts": {}}', ["MISSING_TEST_EXECUTION_PATH"], "test-execution", None),                   # the redraft still has none
    ('{"scripts": {}}', ["gibberish"], "test-execution-undecidable", None),                            # an unreadable judge is not 'ready'
    ('{"scripts": {}}', ["NOT_APPLICABLE"], "test-execution-not-applicable", None),
    ('{"scripts": {"test": "node --test"}}', ["MISSING_TEST_EXECUTION_PATH"], None, BASE),             # a runnable script: the judge is never asked
])
def test_a_package_without_a_test_script_needs_a_stated_execution_path_or_the_plan_is_not_admitted(tmp_path, manifest, verdicts, given_up, steps):
    drafter = Drafter([submit(*BASE), submit(*BASE, "Run node --test report.test.js")], readiness=verdicts)
    plan, rlog, _ = admit(tmp_path, drafter, manifest)
    assert [e["check"] for e in facts(rlog, "plan.admission_given_up")] == ([given_up] if given_up else [])
    assert (steps is None and plan is None) or [i.text for i in plan.items] == steps


def test_a_drafter_that_slips_into_another_tool_is_retried_in_place_and_one_that_answers_in_prose_is_not_retriable(tmp_path):
    slip = {"tool_calls": [{"id": "x", "type": "function", "function": {"name": "CreateNewProject", "arguments": "{}"}}]}
    plan, rlog, _ = admit(tmp_path, Drafter([slip, submit(*BASE)]))
    assert [i.text for i in plan.items] == BASE
    assert facts(rlog, "plan.final_retry") == [{"attempt": 1, "called": ["CreateNewProject"]}] and facts(rlog, "plan.final_recovered")
    plan, rlog, owner = admit(tmp_path, Drafter([{"content": "I think you should just write the code."}]))
    assert plan is None and not owner._retriable_failure and not facts(rlog, "plan.final_retry")


@pytest.mark.parametrize("step,task,files,named", [
    ("Use list_dir to see the layout", "", {}, "list_dir"),                                  # cria's tool menu, in nobody's ask or code
    ("Use list_dir to see the layout", "add a list_dir helper", {}, ""),                     # the user's own word
    ("Use list_dir to see the layout", "", {"util.py": "def list_dir(): pass\n"}, ""),       # the repo's own identifier
    ("Use list_dir to see the layout", "", {"list_dir.py": "x = 1\n"}, ""),                  # ... or file name
    ("Use list_dir to see the layout", "", {"a.py": "x = 1\n", "node_modules": None}, "list_dir"),   # an ignored tree grounds nothing
    ("Write the handler", "", {}, ""),                                                       # no tool named
])
def test_a_step_prescribing_a_tool_name_is_flagged_only_when_neither_the_ask_nor_the_workspace_uses_the_word(tmp_path, step, task, files, named):
    for name, body in files.items():
        (tmp_path / name).mkdir() if body is None else (tmp_path / name).write_text(body)
    assert planner.step_names_tool(step, task, str(tmp_path)) == named


def test_a_workspace_file_cria_holds_no_bytes_for_cannot_show_a_word_absent_and_a_cut_off_call_fragment_is_detected(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("x = 1\n")
    assert planner.step_names_tool("Use list_dir first", "", str(tmp_path)) == "list_dir"
    monkeypatch.setattr(wsview.DirectView, "read", lambda self, path: None)
    assert planner.step_names_tool("Use list_dir first", "", str(tmp_path)) == ""      # unknown is grounded, never a rewritten step
    call = lambda args: {"tool_calls": [{"function": {"arguments": args}}]}
    assert [planner._last_call_truncated(m) for m in (call('{"steps": ["a'), call('{"steps": ["a"]}'), call("{}"), call({}), {})] == \
        [True, False, False, False, False]
