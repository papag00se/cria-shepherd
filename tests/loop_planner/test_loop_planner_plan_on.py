"""Planner-ON behaviour (live code only under explicit opt-in): parsing, framing, review, replan, admission."""
import json
from dataclasses import replace

import pytest

from cria import assistruntime, livingplan as lp, loop, planner, stepreview as sr, wsview
from cria.classify import Classification
from cria.config import Role
from cria.plan import Plan, PlanItem

from loop_planner_helpers import SHELL, Rlog, text_reply, tool_call_reply

# --- plan artifact + step parsing ------------------------------------------------------------------------


def test_plan_markdown_roundtrips_checkboxes_notes_and_colons_in_the_task():
    plan = Plan(id="20260707T004512-3f9a1c2b", task="Write a handler: resolve an Ada Handle", created="c", items=[
        PlanItem("Confirm the api shape"), PlanItem("Write handler.py", done=True, note="wrote handler.py"),
        PlanItem("Write unit tests")])
    back = Plan.from_markdown(plan.to_markdown())
    assert (back.id, back.task, back.status) == (plan.id, plan.task, "in_progress")
    assert [(i.text, i.done, i.note) for i in back.items] == [(i.text, i.done, i.note) for i in plan.items]
    assert back.current().text == "Confirm the api shape" and back.remaining() == 2
    for item in back.items:
        item.done = True
    assert back.current() is None


@pytest.mark.parametrize("raw,want", [
    # ada-handles_mellum2 pon_1785625253 turn 0023: the step carried its own number and cria framed it
    # 'Do ONLY this step (2 of 6)'; the coder spent the turn adjudicating the contradiction.
    ("**Step 1: Resolve a handle to its Cardano address.**", "Resolve a handle to its Cardano address."),
    ("step 3 - write the tests", "write the tests"), ("Step 10. Add the README", "Add the README"),
    ("**Step 7:** ship it", "ship it"), ("1. Write resolve_handle.py", "Write resolve_handle.py"),
    ("2) Add tests", "Add tests"),
    # only a LEADING self-number goes: a step that merely mentions one is content
    ("Write a step counter that prints Step 1: done", "Write a step counter that prints Step 1: done"),
    ("Handle the <message> element", "Handle the <message> element"),
    ("Do the thing<|channel|>analysis leaked thought", "Do the thing"),   # leaked dialect marker is cut
])
def test_clean_step_strips_leading_self_numbering_and_dialect_debris_only(raw, want):
    assert planner._clean_step(raw) == want


@pytest.mark.parametrize("reply,want", [
    ('[{"step": "Write resolve.py"}, {"step": "Write the README"}]', ["Write resolve.py", "Write the README"]),
    ('{"steps": ["a", "b"]}', ["a", "b"]),
    # run 0727-135408 / 0727-143340: an object carrying both outcome and a shell command must read as the OUTCOME
    ('[{"command": "pytest -q", "outcome": "Run unit tests"}]', ["Run unit tests"]),
    ('{"remaining_steps": ["x", "y"]}', ["x", "y"]),                    # a synonym key still answers
    ('{"a": ["x"], "b": ["y"]}', None),                                  # two candidate lists: ambiguous -> miss
    ('{"steps": [], "remaining_steps": ["a"]}', ["a"]),                  # empty primary is the LAST resort
    ('{"steps": []}', []), ("[]", []),                                    # [] is a real answer ("nothing remains")
    ("[1, 2, 3]", None), ("[null]", None),                               # not steps: must not read as "done"
    # run 20260801T232511 call 0067: the reply was a pytest FILE whose first bracket is an array subscript
    ('def test():\n    assert result["resolved_ada_address"]\n', None),
    ("```json\n<think>x</think>[\"a\"]\n```", ["a"]),
])
def test_json_steps_reads_only_what_the_reply_is(reply, want):
    assert planner.json_steps(reply) == want


def test_parse_steps_prose_fallbacks():
    """A numbered plan folds indented sub-bullets into their step (7 steps once exploded to 11 phantom ones);
    a bare bullet list works; an empty JSON list is a failed DRAFT here, so it falls through to prose."""
    numbered = planner.parse_steps("1. Read the spec\n   - note a\n2. Write code\n   - detail")
    assert len(numbered) == 2 and "note a" in numbered[0] and numbered[1].startswith("Write code")
    assert planner.parse_steps("- one\n- two") == ["one", "two"]
    assert planner.parse_steps("[]\n- fallback step") == ["fallback step"]


def test_submit_plan_with_a_repeated_steps_key_keeps_the_real_plan():
    """run 0727-121457: `{"steps":[five real steps],"steps":[1,2,3,4,5]}` made the ordinals the plan."""
    args = '{"steps":["Write the resolver","Write tests"],"steps":[1,2]}'
    msg = {"tool_calls": [{"function": {"name": "submit_plan", "arguments": args}}]}
    assert planner._steps_from_submit(msg) == ["Write the resolver", "Write tests"]


# --- step framing ------------------------------------------------------------------------------------------

# Verbatim from ada-handles_mellum2 pon_1785625253 step 4 of 7: sent unchanged in 33 consecutive prompts while
# the file it names sat on disk failing two assertions.
MELLUM_STEP = "Write unit tests in `test_resolve_handle.py` that mock the API responses."


@pytest.fixture(autouse=True)
def local_workspace_view():
    """Production fills wsview from a harness survey; these tests' workspaces really are on local disk."""
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)


@pytest.fixture
def workspace(tmp_path):
    def make(**files):
        for name, text in files.items():
            (tmp_path / name).write_text(text)
        return str(tmp_path)
    return make


@pytest.mark.parametrize("files,red,speaks", [
    ({"test_resolve_handle.py": "assert False\n"}, True, True),    # authored, failing: reframe as a repair
    ({"test_resolve_handle.py": "x = 1\n"}, False, False),         # green: silent
    ({}, True, False),                                             # not written yet: authoring stays authoring
])
def test_a_step_naming_an_existing_failing_file_is_reframed_as_repair_otherwise_untouched(workspace, files, red, speaks):
    root = workspace(**files)
    prompt = loop._item_prompt(MELLUM_STEP, "", 4, 7, root, red)
    assert MELLUM_STEP in prompt and "Prioritize this step (4 of 7)" in prompt     # step text never altered
    assert ("smallest change" in prompt) is speaks
    if not speaks:
        assert prompt == loop._item_prompt(MELLUM_STEP, "", 4, 7)


def test_the_repair_note_is_ground_truth_that_overrides_a_contradicting_step_and_reads_in_every_arity(tmp_path):
    """Live run 20260801T232511 call 0097: a critic essay claimed the files 'are not in the workspace' while
    cria listed them as present. 'them are already written' also shipped in 145 captured prompts."""
    root = str(tmp_path)
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text("x")
    step = "the task is NOT satisfied because: `a.py` and `b.py` are not in the workspace"
    assert "GROUND TRUTH" in loop._repair_note(step, root, True)
    for names in (["a.py"], ["a.py", "b.py"], ["a.py", "b.py", "c.py"]):
        note = loop._repair_note(" ".join(f"`{n}`" for n in names), root, True)
        assert not any(bad in note for bad in ("them are", "it are", "them is"))
    assert "The file named in this step already exists" in loop._repair_note("Write `a.py`", root, True)


# --- noise judge: never delete a deliverable ---------------------------------------------------------------

README_TASK = ("Write a script that resolves an Ada Handle. Unit tests are required. When you're done, add a "
               "README that explains how to install and run the script and the tests.")
README_STEP = "Add a README.md explaining how to install dependencies (`pip install requests pytest`) and run it."
VENV_STEP = "Set up a Python environment with the `requests` library installed."


def test_noise_verdict_must_be_a_bare_number_list():
    """A model that wraps its verdict in reasoning must not have every number it mentions read as a deletion."""
    steps = ["a", "b", "c"]
    ask = lambda reply: (lambda system, user: reply)
    assert planner.reasoned_noise_indices(ask("2"), "t", steps) == {1}
    assert planner.reasoned_noise_indices(ask("1, 3."), "t", steps) == {0, 2}
    for reply in ("NONE", "steps 1 and 2 look fine; step 3 is plumbing", "9", ""):
        assert planner.reasoned_noise_indices(ask(reply), "t", steps) == set()


def test_a_deletion_that_loses_a_deliverable_is_refused_per_step_and_fails_closed():
    """ada-handles_fabliq pon_1785801960: the noise judge dropped the venv step (right) and the README step
    (a named deliverable: 'pip install' in its text read as setup); the open coverage check then passed the
    survivors. The venv deletion must still land, the README must stay, and each step is judged against the
    steps that SURVIVE (not the other doomed one)."""
    steps = [VENV_STEP, README_STEP, "Write resolver", "Write tests"]
    asked, answers = [], iter(['{"lost": ""}', '{"lost": "a README explaining how to install and run it"}'])

    def ask(system, user):
        asked.append(user)
        return next(answers)
    kept, refused = planner.surviving_noise_drops(ask, README_TASK, steps, {0, 1})
    assert kept == {0} and list(refused) == [1] and "README" in refused[1]
    assert README_STEP not in asked[0] and VENV_STEP not in asked[1]
    for unreadable in ("", "fine", "{}", '{"lost": null}', None):    # deletion is the dangerous direction
        assert planner.deliverable_lost_by_drop(lambda s, u, a=unreadable: a, README_TASK, README_STEP, steps)
    with pytest.raises(RuntimeError):                                # a dead reasoner is not read as 'delete it'
        planner.deliverable_lost_by_drop(lambda s, u: (_ for _ in ()).throw(RuntimeError()), README_TASK, VENV_STEP, steps)


# --- living plan: replan outcomes and bounds ---------------------------------------------------------------

class Questions:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, system, user, **kw):
        self.calls.append((system, user))
        return self.replies.pop(0)


def tail(replies, *, completed=("Scaffold repo layout",), remaining=("Write tests",), trigger=lp.Trigger.ADVANCE, **kw):
    plan = Plan("p", "Build the CLI, tests, and guide", "c", items=[
        *(PlanItem(s, True, "verified") for s in completed), *(PlanItem(s) for s in remaining)])
    q, mirrors, rlog = Questions(replies), [], Rlog()
    services = lp.TailServices(q, lambda: lp.TailFacts("CHECKER OUTPUT", "RESEARCH FACTS", "routes"),
                               lambda p: mirrors.append(p.to_markdown()), planner.COVERAGE)
    source = lp.TailInput(plan, "task:step2", 7, trigger, services, rlog, coder_tools="  - shell", tool_names=("shell",),
                          step_index=2, **kw)
    return source, lp.TailState(), q, mirrors


def run_tail(source, state):
    return lp.LivingSelection.opt_in().run(source, state)


@pytest.mark.parametrize("replies,status,items", [
    (["not JSON"], lp.TailStatus.ABSENT, ["Write tests"]),                         # a miss keeps the old tail
    (['["Write tests"]', "NONE", '{"missing": []}'], lp.TailStatus.UNCHANGED, ["Write tests"]),
    (['["Write guide", "Write tests"]', "NONE", '{"missing": []}'], lp.TailStatus.REPLACED, ["Write guide", "Write tests"]),
    (['["Set up environment"]', "1", '{"lost": ""}'], lp.TailStatus.ALL_NOISE, ["Write tests"]),   # not "done"
    # ada-handles_ternary-bonsai REGRESSION1: a tail that drops a deliverable resets to the RAW task, persisted
    (['["Write tests"]', "NONE", '{"missing": ["guide"]}'], lp.TailStatus.RAW_TASK, ["Build the CLI, tests, and guide"]),
])
def test_tail_rederivation_outcomes_and_what_they_do_to_the_plan(replies, status, items):
    source, state, q, mirrors = tail(replies)
    result = run_tail(source, state)
    assert result.status is status
    assert [i.text for i in source.plan.items if not i.done] == items
    assert source.plan.items[0].done or status is lp.TailStatus.RAW_TASK     # completed work is never rewritten
    assert len(mirrors) == (status in (lp.TailStatus.REPLACED, lp.TailStatus.RAW_TASK))
    if status is lp.TailStatus.RAW_TASK:
        assert result.reset_to_raw_task and result.missing == ("guide",)
        assert "Scaffold repo layout" in q.calls[2][1]       # coverage is asked over completed + remaining


def test_an_unreadable_noise_drop_keeps_the_step_and_a_tool_name_leak_is_refused():
    source, state, q, _ = tail(['["Write guide", "Write tests"]', "1", "unreadable", '{"missing": []}'])
    assert run_tail(source, state).steps == ("Write guide", "Write tests")
    assert "loop.replan_noise_refused" in source.log.kinds()
    source, state, q, mirrors = tail(['["Implement a function that calls web_fetch(url)"]', "NONE", '{"missing": []}'],
                                     )
    source = replace(source, tool_names=("web_fetch",))
    assert run_tail(source, state).status is lp.TailStatus.TOOL_LEAK and not mirrors


def test_rescue_replans_fire_only_past_their_threshold_and_once_per_step():
    """Stuck-step rescue: 4 critic failures / 12 acting calls; each trigger is one-shot per step; fork/reset re-arm."""
    source, state, q, _ = tail(["garbage"] * 6, trigger=lp.Trigger.CRITIC_STALLED)
    n = lambda: len(q.calls)
    assert run_tail(replace(source, critic_fails=3), state).status is lp.TailStatus.NOT_APPLICABLE and n() == 0
    stalled = replace(source, critic_fails=4)
    assert run_tail(stalled, state).status is lp.TailStatus.ABSENT and n() == 1
    assert run_tail(stalled, state).status is lp.TailStatus.NOT_APPLICABLE and n() == 1     # spent even if declined
    thrash = replace(stalled, trigger=lp.Trigger.TOOL_THRASH, acting_calls=11)
    assert run_tail(thrash, state).status is lp.TailStatus.NOT_APPLICABLE
    assert run_tail(replace(thrash, acting_calls=12), state).status is lp.TailStatus.ABSENT and n() == 2
    assert run_tail(replace(thrash, acting_calls=12), state).status is lp.TailStatus.NOT_APPLICABLE
    assert run_tail(stalled, state.fork()).status is lp.TailStatus.ABSENT and n() == 3


@pytest.mark.parametrize("approval,status", [(True, lp.TailStatus.EMPTY_CONFIRMED), (None, lp.TailStatus.EMPTY_DECLINED),
                                             (False, lp.TailStatus.EMPTY_DECLINED)])
def test_an_empty_tail_is_a_question_and_only_a_confirmed_one_prunes_without_releasing_the_task(approval, status):
    source, state, q, mirrors = tail(["[]"])
    pending = run_tail(source, state)
    assert pending.status is lp.TailStatus.EMPTY_PENDING and source.plan.remaining() == 1 and not mirrors
    token = pending.confirmation.token
    assert run_tail(source, state) == pending and len(q.calls) == 1        # asked once
    assert lp.LivingSelection.opt_in().settle(source, state, token, approval).status is status
    assert source.plan.remaining() == (0 if approval is True else 1) and source.plan.status == "in_progress"
    assert lp.LivingSelection.opt_in().settle(source, state, token, True).status is lp.TailStatus.STALE


@pytest.mark.parametrize("change", ["plan", "evidence", "reset"])
def test_a_pending_empty_confirmation_goes_stale_when_the_work_moves_on(change):
    source, state, _, _ = tail(["[]"])
    token = run_tail(source, state).confirmation.token
    if change == "plan":
        source.plan.items[-1].text = "a new requirement"
    elif change == "evidence":
        source = replace(source, evidence_epoch=8)
    else:
        state.reset()
    assert lp.LivingSelection.opt_in().settle(source, state, token, True).status is lp.TailStatus.STALE
    assert source.plan.remaining() == 1


@pytest.mark.parametrize("condition", ["synthetic", "plan_off", "no_question", "no_tail"])
def test_replanning_never_applies_to_plan_off_or_a_finished_plan(condition):
    source, state, q, mirrors = tail([])
    if condition == "no_question":
        source = replace(source, services=replace(source.services, question=None))
    elif condition == "no_tail":
        source.plan.items[-1].done = True
    else:
        source = replace(source, **{condition: True})
    assert run_tail(source, state).status is lp.TailStatus.NOT_APPLICABLE
    assert not q.calls and not mirrors and state == lp.TailState()
    assert lp.LivingSelection().run(source, state).status is lp.TailStatus.NOT_SELECTED   # no consent: nothing runs


# --- step review verdicts ----------------------------------------------------------------------------------

class Confirmed:
    def __init__(self, confirmed=True, observed=True, reason=""):
        self.confirmed, self.observed, self.reason = confirmed, observed, reason


def review(verdicts, *, trigger=sr.StepTrigger.CLAIM, probe=None, confirm=None, workspace_root="", step="Write report.md"):
    reads, persisted = [], []
    queue = list(verdicts)

    def read(request):
        reads.append(request.reasoning_off)
        v = queue.pop(0)
        return sr.StepAnswer(v, "raw")
    services = sr.StepServices(read, lambda v, flag, phase: v, lambda c: confirm, lambda d: d.verdict.get("reason", ""),
                               persisted.append, lambda r: "CONFIRM: " + r, lambda red: "")
    source = sr.StepInput(step, "I finished", "evidence", probe or sr.ProbeEvidence(), services, Rlog(),
                          workspace_root=workspace_root, original_task="task", trigger=trigger)
    return sr.review_step(source), reads, persisted


DONE, NOT_DONE = {"done": True, "reason": "ok"}, {"done": False, "reason": "no tests yet"}
RED = sr.ProbeEvidence(ran=True, blocked=True, red_findings="a.py:3: boom", repair_text="fix a.py:3")


def test_a_claim_is_approved_or_rejected_by_the_step_critic_and_rejection_renudges():
    result, reads, persisted = review([DONE])
    assert result.status is sr.StepStatus.APPROVED and result.effect.action is sr.StepAction.ADVANCE and reads == [False]
    result, _, persisted = review([NOT_DONE])
    assert result.status is sr.StepStatus.REJECTED and result.effect.action is sr.StepAction.RENUDGE
    assert (result.effect.verify_failures, result.effect.critic_failures) == (1, 1) and result.effect.consider_critic_rescue
    assert persisted and persisted[0].done is False


def test_a_red_repo_gate_renudges_with_the_checker_text_and_is_not_counted_as_a_critic_stall():
    """red_gate_is_evidence_not_a_veto: a repo-wide RED gate must not stall a step the critic is judging."""
    result, _, _ = review([NOT_DONE], probe=RED)
    assert result.effect.nudge == "fix a.py:3" and result.effect.critic_failures == 0 and not result.effect.consider_critic_rescue
    approved, _, _ = review([DONE], probe=RED)
    assert approved.effect.red_gate_advance and approved.effect.action is sr.StepAction.ADVANCE


def test_an_unreadable_verdict_gets_one_reasoning_off_retry_and_a_positive_retry_fails_closed():
    result, reads, _ = review([None, NOT_DONE])
    assert result.status is sr.StepStatus.REJECTED and reads == [False, True]
    result, reads, _ = review([None, None])
    assert result.status is sr.StepStatus.UNKNOWN and not result.readable and reads == [False, True]
    result, _, _ = review([None, DONE])        # a 'done' that only appeared on the retry is never trusted
    assert result.status is sr.StepStatus.UNKNOWN and result.effect.action is sr.StepAction.RENUDGE


@pytest.mark.parametrize("confirm,status,action", [
    (Confirmed(True, True), sr.StepStatus.APPROVED, sr.StepAction.ADVANCE),
    (Confirmed(True, False), sr.StepStatus.UNOBSERVED, sr.StepAction.OBSERVE_WORKSPACE),   # confirmed unseen: survey first
    (None, sr.StepStatus.UNOBSERVED, sr.StepAction.KEEP_WORKING)])
def test_a_scheduled_positive_never_advances_without_its_own_observed_confirmation(confirm, status, action):
    result, _, _ = review([DONE], trigger=sr.StepTrigger.SCHEDULED, confirm=confirm, workspace_root="/w")
    assert result.status is status and result.effect.action is action and result.review_done
    assert (result.status is sr.StepStatus.APPROVED) == (result.effect.action is sr.StepAction.ADVANCE)


def test_a_disk_confirmation_that_refuses_a_claimed_step_rejects_it():
    result, _, _ = review([DONE], confirm=Confirmed(False, True, "report.md is empty"), workspace_root="/w")
    assert result.status is sr.StepStatus.REJECTED and result.effect.nudge == "CONFIRM: report.md is empty"


@pytest.mark.parametrize("probe", [sr.ProbeEvidence(pending=True), sr.ProbeEvidence(periodic=True)])
def test_a_pending_or_periodic_probe_never_reaches_the_critic(probe):
    result, reads, _ = review([DONE], probe=probe)
    assert reads == [] and result.status in (sr.StepStatus.PENDING_PROBE, sr.StepStatus.PERIODIC)
    assert not result.done


def test_step_review_is_not_selected_without_consent_and_a_malformed_replacement_cannot_advance():
    calls = []
    source = sr.StepInput("s", "c", "e", sr.ProbeEvidence(), None, Rlog())
    off = sr.StepSelection().run(lambda: calls.append(1))
    assert off.status is sr.StepStatus.NOT_SELECTED and off.effect.action is sr.StepAction.CONTINUE_UNREVIEWED and not calls
    bad = replace(sr.DEFINITION, execute=lambda s: {"done": True})
    with pytest.raises(TypeError):
        sr.StepSelection.opt_in(bad).run(source)


# --- admission give-up: bounded, falls back to the guarded single-item drive -------------------------------

CART_TASK = "In the Go cart service, add a promo discount rule to discounts.json and update go.mod."


class HostLoopProvider:
    """Cart P18's shape: the host judge forever names the task's own files as unread hosts."""

    def __init__(self):
        self.calls = 0

    def chat(self, body, rlog):
        self.calls += 1
        names = {(t.get("function") or {}).get("name") for t in body.get("tools") or []}
        if "submit_plan" in names:
            args = {"steps": ["Add the promo discount rule to discounts.json", "Update go.mod"]}
            reply = {"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"id": f"c{self.calls}", "type": "function", "function": {"name": "submit_plan", "arguments": json.dumps(args)}}]}}]}
        elif names:
            reply = {"choices": [{"message": {"role": "assistant", "tool_calls": [
                {"id": f"c{self.calls}", "type": "function", "function": {"name": "exec_command", "arguments": '{"cmd": "echo"}'}}]}}]}
        else:
            reply = text_reply("discounts.json,go.mod")
        return json.dumps(reply).encode()


def test_an_admission_guard_that_keeps_rejecting_gives_up_and_the_loop_drives_the_raw_task_guarded():
    """Cart P18 (session 01a0d284): six `plan.rejected_exhausted check=host` over 35 minutes, 775 planner calls,
    ZERO coder calls, no loop.start - an exhausted guard was 'retriable' so the loop never took its fallback."""
    provider, rlog, coder_calls = HostLoopProvider(), Rlog(), []
    owner = planner.Planner(provider, role=Role(name="reasoner", backend="local"), max_gather_rounds=1)
    ctx = loop.LoopContext(owner, lambda b, r: coder_calls.append(b) or json.dumps(tool_call_reply()).encode(),
                           lambda *_: b"", runs_dir="", planner_enabled=True,
                           pilot_runtime=assistruntime.AssistRuntime.select(experimental_planning=True))
    driver = loop.Loop(ctx)
    out = driver.drive({"messages": [{"role": "user", "content": CART_TASK}], "tools": [SHELL]}, "sid:p18",
                       Classification("task", "coding", "fixture"), rlog)
    kinds = rlog.kinds()
    given_up = [kw for k, kw in rlog.events if k == "plan.admission_given_up"]
    assert given_up and given_up[-1]["count"] == planner.ADMISSION_EXHAUSTION_GIVEUP
    assert kinds.count("plan.rejected_exhausted") == planner.ADMISSION_EXHAUSTION_GIVEUP and "plan.retriable" not in kinds
    start = [kw for k, kw in rlog.events if k == "loop.start"]
    assert len(start) == 1 and start[0]["synthetic"] and start[0]["planner_fallback"]
    assert out is not None and len(coder_calls) == 1 and driver.has_session("sid:p18")


def test_a_url_route_with_parentheses_is_never_cut_by_filesystem_path_repair(tmp_path):
    """94cecf88: the URL matcher stopped at `(`/`)`, so `https://host/openapi/(v1)/x/routes.json` was truncated at `(v1)` and its tail
    `/x/routes.json` scrubbed as an 'external path'. Prose delimiters around the URL stay; a real external path beside it is still removed."""
    url = "https://api.handle.me/openapi/(v1)/x/routes.json"
    assert planner.repoint_unusable_paths(f"Read {url} now", str(tmp_path)) == (f"Read {url} now", "")
    fixed, note = planner.repoint_unusable_paths(f"Read ({url}), then inspect /etc/nope/missing.yml", str(tmp_path))
    assert fixed == f"Read ({url}), then inspect" and note == "/etc/nope/missing.yml removed"


def test_a_confirmed_step_cannot_cross_a_current_negative_whole_task_verdict(monkeypatch):
    """24e556ed (C8): a per-step 'consistent' confirmation has step provenance, not task-satisfaction provenance; marking the item done
    would let the tail replan discard the repair the whole-task judge kept open. The item and its tail stay, the coder gets the
    evidence, and only a LATER satisfaction pass may release it."""
    from unittest import mock
    evidence = "CHECK RESULT: required behavior remains unmet"
    driver = loop.Loop(loop.LoopContext(planner=None, coder_chat=lambda b, r: json.dumps(tool_call_reply()).encode(),
                                        reasoner_chat=lambda *_: b"{}", runs_dir="", planner_enabled=True,
                                        pilot_runtime=assistruntime.AssistRuntime.select(experimental_planning=True)))
    sess = loop.PlanSession(plan=Plan(id="boundary", task="deliver the requested behavior", created="now",
                                      items=[PlanItem("implement the active behavior"), PlanItem("verify the remaining behavior")]))
    loop._record_satisfaction(sess, False, evidence)
    approval = loop.Verification(True, "consistent with the inspected workspace", loop.Confirmation(True, True, "confirmed"))
    rlog, replans = Rlog(), mock.Mock(wraps=driver._replan_tail)
    with assistruntime.bound(driver._ctx.pilot_runtime), mock.patch.object(driver, "_verify", return_value=approval), \
            mock.patch.object(driver, "_replan_tail", replans):
        out = driver._periodic_step_check(sess, "k", {"messages": [{"role": "user", "content": "go"}], "tools": [SHELL]}, 1, 2, rlog, force=True)
    assert out["choices"][0]["message"].get("tool_calls") and not sess.plan.items[0].done
    assert not [c for c in replans.call_args_list if c.kwargs.get("trigger", lp.Trigger.ADVANCE) is lp.Trigger.ADVANCE]
    assert "loop.step_held_satisfaction" in rlog.kinds() and "loop.step_done" not in rlog.kinds()
