"""Offline remaining-tail source lifecycle; production hookup is deliberately pending."""
from copy import deepcopy
from dataclasses import replace

import pytest

from cria import livingplan as lp, planner
from cria.plan import Plan, PlanItem


# Frozen request text, not a call through the old Loop policy or production
# prompt renderer. The substitutions below are explicit synthetic fixture data.
REPLAN_SYSTEM = """You maintain a LIVING plan for a coding task. A step just finished and was verified. Re-derive the REMAINING steps from what has ACTUALLY been done, so the plan reflects reality instead of the original guess. You only produce the step list — you have NO tools of your own, you do NOT write code or run anything, and you emit NO tool/function call. Any tool list you are shown belongs to the coder, so the steps you write are things IT can do.

You are given: the task, the steps already COMPLETED, the coder's REAL tool actions and their output (ground truth), and the CURRENT remaining steps. Return the REFINED remaining steps — the ones NOT yet done, in order.

- DON'T CODIFY A GUESS: never bake into a step a concrete external detail the coder has NOT confirmed from the real source — an endpoint/URL it called that 404'd or returned the wrong content (e.g. an HTML landing page instead of JSON), a field name a search MISSED, a value it invented. The evidence shows you which attempts FAILED; do NOT harden a failed attempt into the plan. Keep such a step pointed at the SOURCE instead ("call the endpoint the fetched spec defines", "read the field names the spec actually lists", "use the paths the spec you fetched actually lists") — the coder obeys the plan verbatim, so a guessed endpoint or field baked here becomes a shipped bug. A concrete external value is safe to bake ONLY when the evidence shows the coder READ it from the real source.
- A STEP THAT LEARNS AN EXTERNAL FACT MUST READ THE REAL SOURCE, never search for it: word it as reading the thing itself — web_fetch the named domain's own spec/docs, read the file, run the tool's `--help`, open the schema. A web_search returns pointers (titles, URLs, snippets), not the source, so a step worded as "search for X to obtain Y" can never be satisfied and the coder loops on it forever. When the evidence shows exactly that — repeated searches, no read of the real thing — REWRITE that step to name the fetch/read it must do.
- RESEARCH INFORMS THE CODE, it is NOT part of the deliverable: a step that reads a spec/docs is how the CODER learns the real endpoint or field names WHILE building, and the deliverable then uses those concrete values directly. NEVER re-derive a step into one that makes the shipped program ITSELF fetch or parse the spec/docs at RUNTIME to "discover" an endpoint (unless the task EXPLICITLY asked for dynamic discovery) — "read the route from the source" means the coder reads it now, not that the program looks it up every time it runs.
- Keep the plan aimed at the WHOLE task: every deliverable the user asked for that is NOT yet finished in the evidence must still be covered by a step. Never drop a deliverable that isn't actually done.
- REMOVE a remaining step when the evidence shows its work is ALREADY DONE — the coder did it while doing an earlier step. A superfluous step left in place makes the coder redo or UNDO real work; that is the whole point of this pass.
- Reword, reorder, split, or merge the remaining steps to match how the work actually went. Add a step only when the real work has surfaced a genuinely necessary one the plan is missing.
- Do NOT invent requirements the task didn't ask for, and do NOT re-add already-completed work. When unsure whether a step is still needed, KEEP it.
- Steps are concrete, short OUTCOMES in the order they should happen — what to ACHIEVE, NOT the raw shell command that pursues it NOR the literal file content that satisfies it. Example: write "add unit tests for the success case (mock the API)", never "create test.py with content 'import ...'". A literal command or a baked code snippet is not a step — the coder chooses its own commands and writes its own code.

Return ONLY JSON: {"steps": ["<next step>", "<the step after>", ...]} — the full refined remaining list, in order. Return [] ONLY when the evidence shows every remaining deliverable is already done."""
REPLAN_USER = """TASK:
Build the CLI, tests, and guide

STEPS ALREADY COMPLETED (verified — do not repeat or re-add these):
- Build the CLI

THE CODER'S REAL TOOL ACTIONS AND THEIR OUTPUT SO FAR (ground truth — trust this over any claim):
CURRENT CHECKER OUTPUT

CURRENT REMAINING STEPS (refine THESE — the ones not yet done):
- Write tests"""
NOISE_SYSTEM = """You are a JUDGE, not the coder. You have NO tools — do NOT write code, run commands, read or fetch anything, and do NOT emit a tool/function call of any kind. Your ONLY output is the list of step numbers at the bottom.

You are given a coding TASK and a numbered PLAN. Judge each step. A GOOD step is a real, doable piece of the deliverable stated as an OUTCOME: it produces code, tests or docs, or it has the CODER read the real external source while building (fetching the API's spec/docs itself, so the code can then use what was found — the finished program must never look such a thing up when it runs).

BEFORE ANYTHING ELSE — the one thing you must never do: if removing a step would leave something the TASK ASKED FOR with no step that produces it, that step STAYS, whatever else it looks like. Read the task, list what it asks to be produced, and check your removals against that list before you answer. A plan that is missing a thing the task named is worse than a plan with an untidy step in it: the work simply never happens and nothing later notices.

Mark a step for REMOVAL only when it matches one of the cases below; a step that matches none of them stays:
- FABRICATED or SPECULATIVE: it bakes in a concrete external detail the task never gave and the coder can't know yet — a guessed API endpoint/path, a guessed field name, a made-up value, or an invented FILENAME the request never mentioned (say what the file must DO and let the coder name it; a name the request did not give becomes a requirement the coder must match, and it will build a second copy of work it has already finished under its own name) — that the coder should instead learn from the real source; or it's a vague, non-actionable note.
- a RAW SHELL COMMAND or tool invocation rather than a goal (e.g. "grep -n x file.json", "run pytest") — the coder chooses its own commands; a step states the OUTCOME, not the command.
- DICTATING LITERAL CODE: it spells out the literal file content / code the coder should write (e.g. "create test.py with content 'import ...'") instead of describing what the file should DO — the coder writes its own code.
- ENVIRONMENT or PROJECT SETUP that writes no real code/tests/docs: creating a virtualenv/venv, installing or adding dependencies (pip/npm/apt install, adding a package or a `requirements` entry), scaffolding a "project skeleton"/boilerplate, or configuring tooling. The interpreter and test runner are already available, and dependency installation may well be blocked here, so such a step usually stalls rather than producing anything. Judge by the step's REAL action, not a tidy leading verb: "Create a project skeleton — initialise a venv, add requests" and "Create a virtual environment and install requests and pytest" are BOTH setup and must be removed, even though they start with "Create".
- A HUMAN'S WORKFLOW rather than an outcome: "open X in an editor or viewer", "inspect", "review", "look at" — the coder has no editor and no screen. Reading a file with its own tools IS how it reads a file, so a step whose whole action is "open" or "view" can never be satisfied and will be re-judged forever. Measured: one such step was rejected six times in a row and drove the coder to run `nano` on a JSON file, which returned binary.

Reply with ONLY the numbers of the steps to REMOVE, comma-separated (e.g. `1, 3`), or the single word NONE. No other text."""
DROP_SYSTEM = """You are a JUDGE, not the coder. You have NO tools — do NOT write code, design an implementation, choose libraries, name files, or plan next steps, and do NOT emit a tool/function call of any kind. Do not think about HOW any of this would be built. Your ONLY output is the JSON verdict at the bottom.

ONE step is about to be DELETED from the plan. You are checking ONE thing: is there something the REQUEST asks for that this step produces, and that none of the remaining steps produces?

Whoever builds this plan works through the remaining steps and then STOPS. So if this step was the only one that made a thing the request asked for, deleting it means that thing never gets made.

Read the request. Read the step being deleted. Read the steps that would remain. Answer only about things the REQUEST ITSELF asks to be produced — a script, tests, a live test, documentation, a file it names. Do NOT count anything the request never asked for: setting up an environment, installing dependencies, creating a virtualenv, running the checks, tidying, or any best practice it never mentioned. Those are not deliverables, and a step that only does those is safe to delete.

Beware of one trap in particular: a step can DESCRIBE installing or configuring while its actual action is producing a deliverable. "Add a README explaining how to install and run it" produces documentation the request asked for — the installing is the README's SUBJECT, not the step's action.
Judge what the step PRODUCES, not what it talks about.

Output ONLY this JSON, nothing else:
{"lost": "<the thing the request asked for that only this step produces>"}

When nothing the request asked for would be lost, output exactly:
{"lost": ""}"""
COVERAGE_SYSTEM = """You are a JUDGE, not the coder. You have NO tools — do NOT write code, design an implementation, choose libraries, name files, or plan next steps, and do NOT emit a tool/function call of any kind. Do not think about HOW any of this would be built. Your ONLY output is the JSON verdict at the bottom.

You are checking ONE thing: does this plan, carried out to the end, produce everything the request asked for? Whoever builds this plan works through its steps and then STOPS, so anything the request asked for that no step produces never gets made.

Go through the request and take each thing it asks to be produced in turn. For each one, find the step that produces it. If there is no such step, it is missing.

Judge ONLY against what the request itself asks for. Do NOT add anything it did not ask for — no error handling, no logging, no packaging, no CI, no extra tests, no best practice it never mentioned. Ordering, wording and level of detail are not your concern; only whether each requested thing is produced by some step.

An end-to-end test for a CLI or tool must invoke that CLI or tool and check its output or exit status. A step that calls the tool's upstream API directly does NOT produce that requested end-to-end test; it may be an oracle alongside the invocation, but never a substitute. If that invocation is absent, report the request's end-to-end test as missing.

Output ONLY this JSON, nothing else:
{"missing": ["<the requested thing no step produces>", "..."]}

Use the request's own words for each item. When the plan covers everything asked for, output exactly:
{"missing": []}"""


class Log:
    def __init__(self): self.events = []
    def emit(self, name, **fields): self.events.append((name, fields))


class Questions:
    def __init__(self, replies): self.replies, self.calls = list(replies), []
    def __call__(self, system, user, **kwargs):
        self.calls.append((system, user, kwargs))
        return self.replies.pop(0)


def make(replies, *, completed=('Build the CLI',), remaining=('Write tests',), trigger=lp.Trigger.ADVANCE):
    plan = Plan('p', 'Build the CLI, tests, and guide', 'fixture', items=[
        *(PlanItem(s, True, 'verified') for s in completed), *(PlanItem(s) for s in remaining)])
    questions, mirrors, facts_calls = Questions(replies), [], []
    def facts():
        facts_calls.append(True)
        return lp.TailFacts('CURRENT CHECKER OUTPUT', 'REAL RESEARCH FACTS', 'known routes')
    services = lp.TailServices(questions, facts, lambda p: mirrors.append(p.to_markdown()), planner.COVERAGE)
    source = lp.TailInput(plan, 'task:step2', 7, trigger, services, Log(),
                          coder_tools='  - shell: command', tool_names=('shell',), step_index=2)
    return source, lp.TailState(), questions, mirrors, facts_calls


def test_absent_empty_and_replaced_are_distinct():
    absent, state, q, mirrors, _ = make(['not JSON'])
    assert lp.LivingSelection.opt_in().run(absent, state).status is lp.TailStatus.ABSENT
    assert len(q.calls) == 1 and not mirrors and absent.plan.remaining() == 1
    empty, state, q, mirrors, _ = make(['[]'])
    result = lp.LivingSelection.opt_in().run(empty, state)
    assert result.status is lp.TailStatus.EMPTY_PENDING and result.steps == ()
    assert result.confirmation.evidence == 'CURRENT CHECKER OUTPUT'
    assert len(q.calls) == 1 and empty.plan.remaining() == 1 and not mirrors
    assert lp.LivingSelection.opt_in().settle(empty, state, result.confirmation.token, True).status is lp.TailStatus.EMPTY_CONFIRMED
    assert empty.plan.remaining() == 0 and empty.plan.status == 'in_progress' and len(mirrors) == 1
    changed, state, q, mirrors, _ = make(['["Write tests", "Write guide"]', 'NONE', '{"missing": []}'])
    done = changed.plan.items[0]
    result = lp.LivingSelection.opt_in().run(changed, state)
    assert result.status is lp.TailStatus.REPLACED and result.steps == ('Write tests', 'Write guide')
    assert changed.plan.items[0] is done and done.note == 'verified'
    assert len(q.calls) == 3 and len(mirrors) == 1 and changed.plan.status == 'in_progress'


def test_coverage_includes_completed_and_raw_task_is_persisted():
    source, state, questions, mirrors, _ = make(['["Write tests"]', 'NONE', '{"missing": ["guide"]}'])
    result = lp.LivingSelection.opt_in().run(source, state)
    assert result.status is lp.TailStatus.RAW_TASK and result.reset_to_raw_task
    assert result.missing == ('guide',)
    assert [it.text for it in source.plan.items] == [source.plan.task]
    assert not source.plan.items[0].done and source.plan.status == 'in_progress'
    assert len(mirrors) == 1 and source.plan.task in mirrors[0]
    assert 'Build the CLI' in questions.calls[2][1] and 'Write tests' in questions.calls[2][1]
    assert 'REAL RESEARCH FACTS' in questions.calls[1][1]
    assert not result.reset_failure_counts and not result.clear_nudge


def test_coverage_preserves_the_complete_authoritative_completed_item():
    completed = 'Build the CLI\nRETAIN THIS EXACT COMPLETED DETAIL'
    source, state, questions, _, _ = make(['["Write guide"]', 'NONE', '{"missing": []}'], completed=(completed,))
    assert lp.LivingSelection.opt_in().run(source, state).status is lp.TailStatus.REPLACED
    assert completed in questions.calls[2][1]
    assert source.plan.items[0].text == completed and source.plan.items[0].done


def test_rescue_thresholds_one_shots_reset_and_fork():
    source, state, questions, mirrors, facts = make(['garbage'] * 5, trigger=lp.Trigger.CRITIC_STALLED)
    selected = lp.LivingSelection.opt_in()
    assert selected.run(replace(source, critic_fails=3), state).status is lp.TailStatus.NOT_APPLICABLE
    assert not questions.calls and not facts and not state.critic_rescue_used
    source = replace(source, critic_fails=4)
    assert selected.run(source, state).status is lp.TailStatus.ABSENT
    assert state.critic_rescue_used and len(questions.calls) == 1
    assert 'No step was just verified' in questions.calls[0][0]
    assert selected.run(source, state).status is lp.TailStatus.NOT_APPLICABLE
    thrash = replace(source, trigger=lp.Trigger.TOOL_THRASH, acting_calls=11)
    assert selected.run(thrash, state).status is lp.TailStatus.NOT_APPLICABLE
    assert selected.run(replace(thrash, acting_calls=12), state).status is lp.TailStatus.ABSENT
    assert state.thrash_rescue_used and len(questions.calls) == 2
    assert selected.run(replace(thrash, acting_calls=12), state).status is lp.TailStatus.NOT_APPLICABLE
    fork = state.fork()
    assert not fork.critic_rescue_used and fork.pending is None
    assert selected.run(source, fork).status is lp.TailStatus.ABSENT
    state.reset()
    assert selected.run(source, state).status is lp.TailStatus.ABSENT
    assert not mirrors


def test_changed_rescue_returns_exact_counter_and_nudge_effects():
    for trigger in (lp.Trigger.CRITIC_STALLED, lp.Trigger.TOOL_THRASH):
        source, state, _, mirrors, _ = make(['["Write guide"]', 'NONE', '{"missing": []}'], trigger=trigger)
        source = replace(source, critic_fails=4, acting_calls=12)
        result = lp.LivingSelection.opt_in().run(source, state)
        assert result.status is lp.TailStatus.REPLACED and result.reset_failure_counts and result.clear_nudge
        assert result.reset_acting_calls == (trigger is lp.Trigger.TOOL_THRASH)
        assert len(mirrors) == 1
        event = next(fields for name, fields in source.log.events if name == 'loop.stuck_replan')
        assert event == dict(step=2, before=1, after=1, trigger='verify' if trigger is lp.Trigger.CRITIC_STALLED else 'thrash')


def test_unchanged_rescue_is_still_spent_without_persistence():
    source, state, questions, mirrors, _ = make(['["Write tests"]', 'NONE', '{"missing": []}'], trigger=lp.Trigger.CRITIC_STALLED)
    source = replace(source, critic_fails=4)
    result = lp.LivingSelection.opt_in().run(source, state)
    assert result.status is lp.TailStatus.UNCHANGED and not result.reset_failure_counts
    assert lp.LivingSelection.opt_in().run(source, state).status is lp.TailStatus.NOT_APPLICABLE
    assert len(questions.calls) == 3 and not mirrors


@pytest.mark.parametrize('approval', [None, False])
def test_empty_settlement_rejects_stale_or_unknown_confirmation(approval):
    source, state, q, mirrors, _ = make(['[]'])
    selected = lp.LivingSelection.opt_in()
    pending = selected.run(source, state)
    token = pending.confirmation.token
    assert selected.run(source, state) == pending and len(q.calls) == 1
    assert selected.settle(source, state, token, approval).status is lp.TailStatus.EMPTY_DECLINED
    assert source.plan.remaining() == 1 and state.pending is None and not mirrors
    assert selected.settle(source, state, token, True).status is lp.TailStatus.STALE


@pytest.mark.parametrize('change', ['evidence', 'plan', 'reset', 'fork', 'trigger'])
def test_pending_empty_cannot_be_released_after_change(change):
    source, state, _, mirrors, _ = make(['[]'])
    selected = lp.LivingSelection.opt_in()
    token = selected.run(source, state).confirmation.token
    if change == 'evidence': source = replace(source, evidence_epoch=8)
    elif change == 'plan': source.plan.items[-1].text = 'new requirement'
    elif change == 'reset': state.reset()
    elif change == 'fork': state = state.fork()
    else: source = replace(source, trigger=lp.Trigger.CRITIC_STALLED)
    assert selected.settle(source, state, token, True).status is lp.TailStatus.STALE
    assert source.plan.remaining() == 1 and not mirrors


def test_parent_confirmation_token_cannot_confirm_a_forks_own_pending_question():
    source, state, _, mirrors, _ = make(['[]', '[]'])
    selected = lp.LivingSelection.opt_in()
    parent_token = selected.run(source, state).confirmation.token
    fork = state.fork()
    fork_source = replace(source, plan=deepcopy(source.plan))
    child_token = selected.run(fork_source, fork).confirmation.token
    assert child_token != parent_token
    assert selected.settle(fork_source, fork, parent_token, True).status is lp.TailStatus.STALE
    assert fork.pending is not None and not mirrors
    assert selected.settle(fork_source, fork, child_token, True).status is lp.TailStatus.EMPTY_CONFIRMED
    assert source.plan.remaining() == 1


def test_disabled_and_replaced_stages_do_no_old_detection_or_state_effects():
    source, state, q, mirrors, facts = make([])
    before = deepcopy(state)
    assert lp.LivingSelection().run(source, state).status is lp.TailStatus.NOT_SELECTED
    assert state == before and not q.calls and not facts and not mirrors
    seen = []
    def execute(source, state):
        seen.append(source.step_key)
        return lp.TailResult(lp.TailStatus.UNCHANGED, ('replacement',))
    replacement = replace(lp.DEFINITION, execute=execute)
    assert lp.LivingSelection.opt_in(replacement).run(source, state).steps == ('replacement',)
    assert seen == ['task:step2'] and state == before and not q.calls and not facts
    assert lp.LivingSelection.opt_in(None).settle(source, state, lp.PendingToken(0), True).status is lp.TailStatus.NOT_SELECTED


def test_disabled_settlement_cannot_consume_or_release_an_owned_pending_question():
    source, state, questions, mirrors, _ = make(['[]'])
    selected = lp.LivingSelection.opt_in()
    token = selected.run(source, state).confirmation.token
    pending = state.pending
    disabled = lp.LivingSelection()
    assert disabled.run(source, state).status is lp.TailStatus.NOT_SELECTED
    assert disabled.settle(source, state, token, True).status is lp.TailStatus.NOT_SELECTED
    assert state.pending is pending and source.plan.remaining() == 1 and not mirrors
    assert len(questions.calls) == 1
    state.reset()  # explicit task cancellation, not a disabled-stage side effect
    assert selected.settle(source, state, token, True).status is lp.TailStatus.STALE


@pytest.mark.parametrize('condition', ['no-question', 'synthetic', 'off', 'no-tail'])
def test_not_applicable_never_reads_evidence_or_changes_state(condition):
    source, state, q, mirrors, facts = make([])
    if condition == 'no-question': source = replace(source, services=replace(source.services, question=None))
    elif condition == 'synthetic': source = replace(source, synthetic=True)
    elif condition == 'off': source = replace(source, plan_off=True)
    else: source.plan.items[-1].done = True
    assert lp.LivingSelection.opt_in().run(source, state).status is lp.TailStatus.NOT_APPLICABLE
    assert not q.calls and not facts and not mirrors and state == lp.TailState()


def test_noise_deletion_keeps_unreadable_deliverable_and_coverage_runs_afterward():
    source, state, q, mirrors, _ = make(['["Write guide", "Write tests"]', '1', 'unreadable', '{"missing": []}'])
    result = lp.LivingSelection.opt_in().run(source, state)
    assert result.steps == ('Write guide', 'Write tests') and len(q.calls) == 4 and len(mirrors) == 1
    assert 'Write guide' in q.calls[-1][1]
    assert any(name == 'loop.replan_noise_refused' for name, _ in source.log.events)


def test_all_noise_is_absent_guidance_not_empty_completion():
    source, state, q, mirrors, _ = make(['["Set up environment"]', '1', '{"lost": ""}'])
    result = lp.LivingSelection.opt_in().run(source, state)
    assert result.status is lp.TailStatus.ALL_NOISE and state.pending is None
    assert len(q.calls) == 3 and not mirrors and source.plan.remaining() == 1


def test_tool_leak_refuses_after_coverage_without_rewriting():
    source, state, q, mirrors, _ = make(['["Implement a function that calls web_fetch(url)"]', 'NONE', '{"missing": []}'])
    source = replace(source, tool_names=('web_fetch',))
    assert lp.LivingSelection.opt_in().run(source, state).status is lp.TailStatus.TOOL_LEAK
    assert source.plan.items[-1].text == 'Write tests' and not mirrors and len(q.calls) == 3


@pytest.mark.parametrize('replies', [
    ['not JSON'], ['[]'], ['["Write tests"]', 'NONE', '{"missing": []}'],
    ['["Write guide", "Write tests"]', '1', '{"lost": "guide"}', '{"missing": []}'],
    ['["Write tests"]', 'NONE', '{"missing": ["guide"]}'],
])
def test_source_reuses_legacy_questions_parsers_and_exact_reask_counts(replies):
    """Historical metadata name; frozen requests/state replace the old policy oracle."""
    # Retain every old parity scenario, but never ask the retiring Loop body
    # to compute the expected requests, mutation, effects or missing work.
    source, state, questions, mirrors, facts = make(replies)
    result = lp.LivingSelection.opt_in().run(source, state)
    calls = [(REPLAN_SYSTEM, REPLAN_USER, {'coder_tools': '  - shell: command'})]
    refused = len(replies) == 4
    if len(replies) > 1:
        numbered = '1. Write guide\n2. Write tests' if refused else '1. Write tests'
        calls.append((NOISE_SYSTEM, 'REAL RESEARCH FACTS\n\nTASK:\nBuild the CLI, tests, and guide\n\nPLAN:\n' + numbered, {}))
        if refused:
            calls.append((DROP_SYSTEM, 'REQUEST:\nBuild the CLI, tests, and guide\n\nTHE STEP ABOUT TO BE DELETED:\nWrite guide\n\nTHE STEPS THAT WOULD REMAIN:\n- Write tests', {}))
        plan_text = '1. Build the CLI\n2. Write guide\n3. Write tests' if refused else '1. Build the CLI\n2. Write tests'
        calls.append((COVERAGE_SYSTEM, 'REQUEST:\nBuild the CLI, tests, and guide\n\nPLAN:\n' + plan_text, {}))
    assert full_calls(questions.calls) == calls and not questions.replies and facts == [True]
    expected = {
        'not JSON': (lp.TailStatus.ABSENT, None, (), [('Build the CLI', True, 'verified'), ('Write tests', False, None)]),
        '[]': (lp.TailStatus.EMPTY_PENDING, (), (), [('Build the CLI', True, 'verified'), ('Write tests', False, None)]),
    }
    if len(replies) == 1:
        status, steps, missing, items = expected[replies[0]]
    elif refused:
        status, steps, missing = lp.TailStatus.REPLACED, ('Write guide', 'Write tests'), ()
        items = [('Build the CLI', True, 'verified'), ('Write guide', False, None), ('Write tests', False, None)]
    elif replies[-1] == '{"missing": ["guide"]}':
        status, steps, missing = lp.TailStatus.RAW_TASK, ('Build the CLI, tests, and guide',), ('guide',)
        items = [('Build the CLI, tests, and guide', False, None)]
    else:
        status, steps, missing = lp.TailStatus.UNCHANGED, ('Write tests',), ()
        items = [('Build the CLI', True, 'verified'), ('Write tests', False, None)]
    assert (result.status, result.steps, result.missing) == (status, steps, missing)
    assert [(item.text, item.done, item.note) for item in source.plan.items] == items
    assert source.plan.status == 'in_progress'
    assert (state.step_key, state.plan_id, state.task, state.critic_rescue_used,
            state.thrash_rescue_used, state.sequence) == (
        'task:step2', 'p', 'Build the CLI, tests, and guide', False, False,
        2 if status is lp.TailStatus.EMPTY_PENDING else 1)
    events = []
    if status is lp.TailStatus.ABSENT:
        events = [('loop.replan_noop', {'step': 2, 'result': 'declined', 'remaining': 1})]
    elif status is not lp.TailStatus.EMPTY_PENDING:
        if refused:
            events.append(('loop.replan_noise_refused', {'level': 'warn', 'lost': 'guide', 'step': 'Write guide'}))
        events.append(('loop.replan_noise', {'dropped': 0, 'kept': 2 if refused else 1,
                                           'dropped_steps': '', 'level': 'info'}))
        if status is lp.TailStatus.UNCHANGED:
            events.append(('loop.replan_noop', {'step': 2, 'result': 'unchanged', 'remaining': 1}))
        elif status is lp.TailStatus.RAW_TASK:
            events.extend([('loop.replan_uncovered', {'level': 'warn', 'missing': 'guide'}),
                           ('loop.replan_reset', {'level': 'warn', 'step': 2, 'state': 'raw_task', 'missing': 'guide'})])
        else:
            events.append(('loop.replan', {'step': 2, 'before': 1, 'after': 2}))
    assert source.log.events == events
    assert result.reset_to_raw_task is (status is lp.TailStatus.RAW_TASK)
    assert not result.reset_failure_counts and not result.clear_nudge and not result.reset_acting_calls
    if status in (lp.TailStatus.REPLACED, lp.TailStatus.RAW_TASK):
        checklist = ('- [x] Build the CLI\n  > verified\n- [ ] Write guide\n- [ ] Write tests' if refused
                     else '- [ ] Build the CLI, tests, and guide')
        assert mirrors == ['---\nid: p\ncreated: fixture\nstatus: in_progress\ntask: Build the CLI, tests, and guide\n---\n\n# Plan\n\n' + checklist + '\n']
    else:
        assert mirrors == []
    if status is lp.TailStatus.EMPTY_PENDING:
        assert state.pending.request is result.confirmation
        assert (result.confirmation.task, result.confirmation.evidence, result.confirmation.plan_id) == (
            'Build the CLI, tests, and guide', 'CURRENT CHECKER OUTPUT', 'p')
    else:
        assert state.pending is None


def test_resume_discards_transient_questions_and_rescue_flags_without_releasing_tail():
    from cria import loop
    source, state, questions, mirrors, _ = make(['[]'], trigger=lp.Trigger.CRITIC_STALLED)
    source = replace(source, critic_fails=4)
    selected = lp.LivingSelection.opt_in()
    token = selected.run(source, state).confirmation.token
    session = loop.PlanSession(plan=source.plan, verify_replanned=True, thrash_replanned=True, critic_fails=4)
    resumed = loop._session_from_dict(loop._session_to_dict(session))
    assert not resumed.verify_replanned and not resumed.thrash_replanned and resumed.critic_fails == 0
    fresh = lp.TailState()  # same transient reset contract; never serialize an approval token
    resumed_source = replace(source, plan=resumed.plan, critic_fails=resumed.critic_fails)
    assert selected.settle(resumed_source, fresh, token, True).status is lp.TailStatus.STALE
    assert selected.run(resumed_source, fresh).status is lp.TailStatus.NOT_APPLICABLE
    assert resumed.plan.remaining() == 1 and len(questions.calls) == 1 and not mirrors


def test_selected_coverage_replacement_is_used_not_canonical_judgment():
    source, state, questions, mirrors, _ = make(['["Write tests"]', 'NONE'])
    seen = []
    def coverage(ask, task, steps):
        seen.append((task, steps))
        return ['guide']
    selected = replace(planner.COVERAGE, execute=coverage)
    source = replace(source, services=replace(source.services, coverage=selected))
    result = lp.LivingSelection.opt_in().run(source, state)
    assert result.status is lp.TailStatus.RAW_TASK and len(questions.calls) == 2
    assert seen == [(source.plan.task, ['Build the CLI', 'Write tests'])] and len(mirrors) == 1


def test_persistence_failure_keeps_the_authoritative_plan():
    source, state, _, _, _ = make(['["Write guide"]', 'NONE', '{"missing": []}'])
    def fail(plan): raise OSError('owned directory unavailable')
    source = replace(source, services=replace(source.services, persist=fail))
    assert lp.LivingSelection.opt_in().run(source, state).status is lp.TailStatus.REPLACED
    assert source.plan.items[-1].text == 'Write guide'
    assert any(event == 'loop.plan_persist_error' for event, _ in source.log.events)


def test_unsupported_dependency_consent_and_replacement_are_errors():
    with pytest.raises(ValueError): lp.LivingSelection(False, lp.DEFINITION)
    with pytest.raises(ValueError): lp.LivingSelection.opt_in(replace(lp.DEFINITION, policy=replace(lp.DEFINITION.policy, scope='runtime')))
    source, state, q, mirrors, facts = make([])
    source = replace(source, services=replace(source.services, coverage=None))
    with pytest.raises(ValueError): lp.LivingSelection.opt_in().run(source, state)
    assert not q.calls and not mirrors and not facts and state == lp.TailState()
    assert lp.DEFINITION.policy.scope == 'experimental' and lp.DEFINITION.policy.family_id == 'F50'
    assert lp.DEFINITION.policy.hooks and lp.DEFINITION.policy.regressions and not lp.DEFINITION.policy.migrated


def test_production_projection_requires_consent_and_actual_membership_without_reading_off():
    def forbidden():
        raise AssertionError('OFF selection must not enumerate definitions')
        yield
    assert lp.LivingSelection.from_definitions(forbidden()) == lp.LivingSelection()
    selected = lp.LivingSelection.from_definitions((planner.COVERAGE,), enabled=True)
    assert selected.enabled and selected.definition is None and selected.coverage is None
    source, state, questions, mirrors, facts = make([])
    assert selected.run(source, state).status is lp.TailStatus.NOT_SELECTED
    assert not questions.calls and not mirrors and not facts and state == lp.TailState()


def test_production_projection_pins_exact_replacement_execute_and_settle_objects():
    calls = []
    coverage = replace(planner.COVERAGE, execute=lambda *_: ['guide'])
    def run(source, state):
        calls.append(('run', source.services.coverage, state))
        return lp.TailResult(lp.TailStatus.UNCHANGED)
    def settle(source, state, token, approved):
        calls.append(('settle', source.services.coverage, state, token, approved))
        return lp.TailResult(lp.TailStatus.EMPTY_DECLINED)
    definition = replace(lp.DEFINITION, execute=run, settle=settle)
    selected = lp.LivingSelection.from_definitions((coverage, definition), enabled=True)
    assert selected.definition is definition and selected.coverage is coverage
    source, state, questions, mirrors, facts = make([])
    source = replace(source, services=replace(source.services, coverage=coverage))
    token = lp.PendingToken(9)
    assert selected.run(source, state).status is lp.TailStatus.UNCHANGED
    assert selected.settle(source, state, token, None).status is lp.TailStatus.EMPTY_DECLINED
    assert calls == [('run', coverage, state), ('settle', coverage, state, token, None)]
    assert calls[0][1] is coverage and calls[1][1] is coverage
    assert not questions.calls and not mirrors and not facts


@pytest.mark.parametrize('settle', [False, True])
def test_bound_projection_rejects_equal_but_different_coverage_before_work(settle):
    selected = lp.LivingSelection.from_definitions((planner.COVERAGE, lp.DEFINITION), enabled=True)
    source, state, questions, mirrors, facts = make([])
    other = replace(planner.COVERAGE)
    assert other == planner.COVERAGE and other is not planner.COVERAGE
    source = replace(source, services=replace(source.services, coverage=other))
    with pytest.raises(ValueError, match='same selected coverage object'):
        if settle:
            selected.settle(source, state, lp.PendingToken(1), True)
        else:
            selected.run(source, state)
    assert not questions.calls and not mirrors and not facts and state == lp.TailState()


@pytest.mark.parametrize('definitions', [
    (lp.DEFINITION,),
    (lp.DEFINITION, planner.COVERAGE),
    (planner.COVERAGE, lp.DEFINITION, lp.DEFINITION),
    (planner.COVERAGE, planner.COVERAGE, lp.DEFINITION),
    (replace(planner.COVERAGE, execute=None), lp.DEFINITION),
    (planner.COVERAGE, replace(lp.DEFINITION, execute=None)),
])
def test_production_projection_rejects_missing_duplicate_or_invalid_dependencies(definitions):
    with pytest.raises(ValueError):
        lp.LivingSelection.from_definitions(definitions, enabled=True)


@pytest.mark.parametrize('enabled', [1, 'true', None])
def test_production_projection_consent_is_an_actual_boolean(enabled):
    with pytest.raises(ValueError):
        lp.LivingSelection.from_definitions((), enabled=enabled)


def test_empty_confirmation_binds_actual_fact_token_not_a_source_counter():
    source, state, questions, mirrors, _ = make(['[]'])
    source = replace(source, evidence_epoch=('tool-result-id', 'gate-observation-digest'))
    selected = lp.LivingSelection.from_definitions((planner.COVERAGE, lp.DEFINITION), enabled=True)
    result = selected.run(source, state)
    assert result.status is lp.TailStatus.EMPTY_PENDING
    changed = replace(source, evidence_epoch=('later-tool-result-id', 'gate-observation-digest'))
    assert selected.settle(changed, state, result.confirmation.token, True).status is lp.TailStatus.STALE
    assert len(source.plan.items) == 2 and not mirrors and len(questions.calls) == 1


def full_calls(calls):
    from cria import prompts
    result=[]
    for system,user,kwargs in calls:
        kwargs=dict(kwargs)
        blocks=kwargs.pop('evidence_blocks',None)
        if blocks is not None:
            user=user.replace(prompts.load('composed_evidence_intro'), ''.join(blocks))
        result.append((system,user,kwargs))
    return result
