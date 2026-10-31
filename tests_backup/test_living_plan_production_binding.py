"""Public living-tail dispatch; scripted providers never execute harness calls."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from cria import assistruntime, livingplan as lp
from cria.config import Role
from cria.loop import Loop, LoopContext, LoopStore, PlanSession
from cria.plan import Plan, PlanItem


class Log:
    def __init__(self):
        self.events = []
    def emit(self, name, **fields):
        self.events.append((name, fields))


def fixture(*, enabled=True, definition=None, coverage=None, fail_coder_call=None, state_path=None,
            review=False, review_done=False):
    runtime = assistruntime.AssistRuntime.select(level=5, experimental_planning=True)
    stages = tuple(item for item in runtime.ordered_stages
                   if item.policy.id not in ('experimental-living-plan',
                                             'experimental-step-review',
                                             'experimental-completed-work-briefing')
                   or (review and item.policy.id == 'experimental-step-review'))
    if review:
        # Existing planned STEP consumer, not initial planning. Keep its actual
        # selected coverage dependency without arming GATHER's shell admission.
        stages = tuple(item for item in stages if item.policy.id not in (
            'experimental-plan-gather', 'experimental-plan-readiness',
            'experimental-plan-revision'))
    if coverage is not None:
        stages = tuple(coverage if item.policy.id == coverage.policy.id else item for item in stages)
    if definition is not None:
        stages += (definition,)
    runtime = replace(runtime, ordered_stages=stages, experimental_planning=enabled)
    reads, coders = [], []
    def reasoner(body, log):
        reads.append(body)
        text = json.dumps(body)
        if 'You maintain a LIVING plan' in text:
            answer = '{"steps": ["Write precise tests"]}'
        elif 'does this plan, carried out to the end' in text:
            answer = '{"missing": []}'
        elif review:
            answer = json.dumps({'done': review_done, 'reason': 'tests checked'})
        else:
            answer = 'NONE'
        return json.dumps({'choices': [{'message': {'content': answer}}]}).encode()
    def coder(body, log):
        coders.append(body)
        if len(coders) == fail_coder_call:
            raise RuntimeError('scripted coder did not deliver')
        if review and len(coders) == 1:
            return json.dumps({'choices': [{'message': {'role': 'assistant',
                'content': 'The tests are complete.'}}]}).encode()
        if review:
            return json.dumps({'choices': [{'message': {'role': 'assistant', 'content': None,
                'tool_calls': [{'id': 'coder-' + str(len(coders)), 'type': 'function',
                    'function': {'name': 'read_file', 'arguments': '{"path": "guide.txt"}'}}]}}]}).encode()
        return json.dumps({'choices': [{'message': {'role': 'assistant', 'content': None,
            'tool_calls': [{'id': 'coder-' + str(len(coders)), 'type': 'function',
                'function': {'name': 'shell', 'arguments': json.dumps({
                    'command': ['sh', '-c', 'printf fixture']})}}]}}]}).encode()
    store = LoopStore(state_path)
    session = PlanSession(plan=Plan('living-public', 'Build CLI and tests', 'fixture', items=[
        PlanItem('Build CLI', True, 'verified'), PlanItem('Write tests')]),
        step_tool_calls=lp.STEP_THRASH_REPLAN - 1)
    key = 'sid:living-public'
    store.put(key, session)
    driver = Loop(LoopContext(planner=None, planner_enabled=True, pilot_runtime=runtime,
        coder_chat=coder, reasoner_chat=reasoner,
        reasoner_role=Role(name='reasoner', backend='local'), runs_dir=''), store)
    body = {'messages': [{'role': 'user', 'content': 'Build CLI and tests'}],
        'tools': [{'type': 'function', 'function': {'name': 'shell', 'parameters': {
            'type': 'object', 'properties': {'command': {'type': 'array'}}}}}]}
    if review:
        session.step_tool_calls = 1
        body['tools'] = [{'type': 'function', 'function': {'name': 'read_file', 'parameters': {
            'type': 'object', 'properties': {'path': {'type': 'string'}}}}}]
    return driver, session, key, body, runtime, reads, coders


@pytest.mark.parametrize('enabled,selected', [(False, True), (True, False)])
def test_public_thrashing_without_selected_consent_bypasses_all_living_work(enabled, selected):
    driver, session, key, body, runtime, reads, coders = fixture(
        enabled=enabled, definition=lp.DEFINITION if selected else None)
    assert runtime.living_plan.definition is None
    result = driver.drive(body, key, SimpleNamespace(engagement='task', task_type='coding'), Log())
    assert result['choices'][0]['message']['tool_calls'][0]['id'] == 'coder-1'
    assert not reads
    assert len(coders) == 1
    assert [(item.text, item.done, item.note) for item in session.plan.items] == [
        ('Build CLI', True, 'verified'), ('Write tests', False, None)]
    assert not session.thrash_replanned
    assert driver._store.get(key) is session


def test_public_thrashing_dispatches_exact_selected_replacement_and_coverage():
    seen = []
    def execute(source, state):
        seen.append((source, state))
        return lp.TailResult(lp.TailStatus.UNCHANGED)
    definition = replace(lp.DEFINITION, execute=execute)
    driver, session, key, body, runtime, reads, coders = fixture(definition=definition)
    assert runtime.living_plan.definition is definition
    coverage = runtime.living_plan.coverage
    assert any(item is coverage for item in runtime.definitions)
    result = driver.drive(body, key, SimpleNamespace(engagement='task', task_type='coding'), Log())
    assert len(seen) == 1
    assert seen[0][0].plan is session.plan
    assert seen[0][0].services.coverage is coverage
    assert seen[0][0].trigger is lp.Trigger.TOOL_THRASH
    assert result['choices'][0]['message']['tool_calls'][0]['id'] == 'coder-1'
    assert not reads and len(coders) == 1
    assert [item.text for item in session.plan.items] == ['Build CLI', 'Write tests']
    assert session.plan.status == 'in_progress'


@pytest.mark.parametrize('approved,trigger', [
    (True, lp.Trigger.ADVANCE), (False, lp.Trigger.CRITIC_STALLED),
])
def test_public_step_transition_dispatches_selected_tail_with_distinct_authority(approved, trigger):
    seen = []
    def execute(source, state):
        seen.append((source, state))
        return lp.TailResult(lp.TailStatus.UNCHANGED)
    definition = replace(lp.DEFINITION, execute=execute)
    driver, session, key, body, runtime, reads, coders = fixture(
        definition=definition, review=True, review_done=approved)
    session.plan.items.append(PlanItem('Write guide'))
    session.critic_fails = lp.STUCK_STEP_REPLAN - 1
    log = Log()
    result = driver.drive(body, key, SimpleNamespace(engagement='task', task_type='coding'), log)
    assert [source.trigger for source, _ in seen] == [trigger, lp.Trigger.TOOL_THRASH]
    assert seen[1][0].acting_calls == (1 if approved else 2)
    assert all(source.services.coverage is runtime.living_plan.coverage for source, _ in seen)
    assert all(source.plan is session.plan for source, _ in seen)
    assert session.plan.items[1].done is approved
    assert session.plan.items[2].done is False
    assert result['choices'][0]['message']['tool_calls'][0]['id'] == 'coder-2'
    assert len(coders) == 2 and session.plan.status == 'in_progress'
    assert driver._store.get(key) is session
    assert 'loop.done' not in [name for name, _ in log.events]


def test_public_selected_coverage_refusal_preserves_raw_task_and_retained_delivery():
    from cria import planner
    seen = []
    def coverage(ask, task, steps):
        seen.append((task, tuple(steps)))
        return ['tests']
    dependency = replace(planner.COVERAGE, execute=coverage)
    driver, session, key, body, runtime, reads, coders = fixture(
        definition=lp.DEFINITION, coverage=dependency)
    assert runtime.living_plan.coverage is dependency
    log = Log()
    result = driver.drive(body, key, SimpleNamespace(engagement='task', task_type='coding'), log)
    assert seen == [('Build CLI and tests', ('Build CLI', 'Write precise tests'))]
    assert session.synthetic and session.plan_off
    assert [(item.text, item.done) for item in session.plan.items] == [('Build CLI and tests', False)]
    assert session.replan_uncovered == ('tests',) and not session.replan_uncovered_pending
    assert result['choices'][0]['message']['tool_calls'][0]['id'] == 'coder-2'
    assert len(coders) == 2
    assert [name for name, _ in log.events].count('loop.replan_uncovered_delivered') == 1
    assert 'loop.done' not in [name for name, _ in log.events]
    assert session.plan.status == 'in_progress' and driver._store.get(key) is session


def test_public_uncovered_effects_wait_for_retained_callback_and_reject_cancelled_offer():
    from cria import planner
    dependency = replace(planner.COVERAGE, execute=lambda *_: ['tests'])
    driver, session, key, body, runtime, reads, coders = fixture(
        definition=lp.DEFINITION, coverage=dependency)
    session.verify_fails, session.critic_fails = 3, 2
    callbacks = []
    log = Log()
    offered = driver.drive(body, key, SimpleNamespace(engagement='task', task_type='coding'),
                           log, pasted_delivery=callbacks.append)
    assert offered['choices'][0]['message']['tool_calls'][0]['id'] == 'coder-2'
    assert len(callbacks) == 1
    assert session.synthetic and session.plan_off and session.replan_uncovered_pending
    assert (session.verify_fails, session.critic_fails) == (3, 2)
    callbacks[0](None)
    assert session.replan_uncovered_pending
    assert (session.verify_fails, session.critic_fails) == (3, 2)
    retained = driver.drive(body, key, SimpleNamespace(engagement='task', task_type='coding'),
                            log, pasted_delivery=callbacks.append)
    assert len(callbacks) == 2 and session.replan_uncovered_pending
    callbacks[0](offered)  # cancelled invocation cannot acknowledge a later offered frame
    assert session.replan_uncovered_pending
    callbacks[1](retained)
    assert not session.replan_uncovered_pending
    assert (session.verify_fails, session.critic_fails, session.step_tool_calls) == (0, 0, 0)
    assert [name for name, _ in log.events].count('loop.replan_uncovered_delivered') == 1
    assert session.plan.status == 'in_progress' and driver._store.get(key) is session


def test_public_new_gate_fact_without_retained_action_invalidates_empty_tail_confirmation():
    from cria.probegate import GatePlan
    settled = []
    def settle(source, state, token, approved):
        result = lp.settle_empty(source, state, token, approved)
        settled.append((source.evidence_epoch, result.status))
        return result
    definition = replace(lp.DEFINITION, settle=settle)
    driver, session, key, body, runtime, reads, coders = fixture(definition=definition)
    session.gate_plan = GatePlan(workspace='', transport_id='fixture-gate-before')
    start_action = session.action_seq
    def question(body, log):
        reads.append(body)
        if 'You maintain a LIVING plan' in json.dumps(body):
            # An independent receiver can settle gate facts during a question;
            # no action was retained and no tool/build is executed by this fixture.
            session.gate_plan = GatePlan(workspace='', transport_id='fixture-gate-after')
            session.last_gate_flag = 'new gate observation'
            return json.dumps({'choices': [{'message': {'content': '[]'}}]}).encode()
        return json.dumps({'choices': [{'message': {'content':
            '{"satisfied": false, "reason": "guide still missing"}'}}]}).encode()
    driver._ctx.reasoner_chat = question
    result = driver.drive(body, key, SimpleNamespace(engagement='task', task_type='coding'), Log())
    assert len(settled) == 1 and settled[0][1] is lp.TailStatus.STALE
    assert [item.text for item in session.plan.items] == ['Build CLI', 'Write tests']
    assert session.plan.items[1].done is False and session.plan.status == 'in_progress'
    assert result['choices'][0]['message']['tool_calls'][0]['id'] == 'coder-1'
    assert session.action_seq == start_action + 1
    assert len(coders) == 1


def test_public_late_reply_for_replaced_owner_cannot_credit_rescue_or_uncovered_delivery():
    from cria import planner
    dependency = replace(planner.COVERAGE, execute=lambda *_: ['tests'])
    driver, original, key, body, runtime, reads, coders = fixture(
        definition=lp.DEFINITION, coverage=dependency)
    original.verify_fails, original.critic_fails = 3, 2
    callbacks, log = [], Log()
    offered = driver.drive(body, key, SimpleNamespace(engagement='task', task_type='coding'),
                           log, pasted_delivery=callbacks.append)
    assert original.replan_uncovered_pending and len(callbacks) == 1
    successor = PlanSession(plan=Plan('successor', 'A different task', 'fixture', items=[
        PlanItem('Successor work')]), verify_fails=7, critic_fails=8)
    driver._store.put(key, successor)
    callbacks[0](offered)
    assert original.replan_uncovered_pending
    assert (original.verify_fails, original.critic_fails) == (3, 2)
    assert (successor.verify_fails, successor.critic_fails) == (7, 8)
    assert driver._store.get(key) is successor and not successor.replan_uncovered_pending
    assert 'loop.replan_uncovered_delivered' not in [name for name, _ in log.events]


def test_public_replaced_owner_cannot_settle_original_empty_tail_question():
    settled, states = [], []
    def execute(source, state):
        states.append(state)
        return lp.rederive_tail(source, state)
    def settle(source, state, token, approved):
        settled.append(token)
        return lp.settle_empty(source, state, token, approved)
    definition = replace(lp.DEFINITION, execute=execute, settle=settle)
    driver, original, key, body, runtime, reads, coders = fixture(definition=definition)
    successor = PlanSession(plan=Plan('successor', 'Build CLI and tests', 'fixture', items=[
        PlanItem('Successor work')]))
    def question(body, log):
        reads.append(body)
        if 'You maintain a LIVING plan' in json.dumps(body):
            driver._store.put(key, successor)
            return json.dumps({'choices': [{'message': {'content': '[]'}}]}).encode()
        return json.dumps({'choices': [{'message': {'content':
            '{"satisfied": false, "reason": "tests missing"}'}}]}).encode()
    driver._ctx.reasoner_chat = question
    driver.drive(body, key, SimpleNamespace(engagement='task', task_type='coding'), Log())
    assert not settled
    assert states and states[0].pending is None
    assert driver._store.get(key) is successor
    assert [(item.text, item.done) for item in original.plan.items] == [
        ('Build CLI', True), ('Write tests', False)]
    assert [(item.text, item.done) for item in successor.plan.items] == [('Successor work', False)]
    assert original.plan.status == successor.plan.status == 'in_progress'


def test_public_failed_uncovered_delivery_survives_store_resume_until_retained_reply(tmp_path):
    from cria import planner
    dependency = replace(planner.COVERAGE, execute=lambda *_: ['tests'])
    path = str(tmp_path / 'owned-session.json')
    driver, session, key, body, runtime, reads, coders = fixture(
        definition=lp.DEFINITION, coverage=dependency, fail_coder_call=2, state_path=path)
    with pytest.raises(RuntimeError, match='scripted coder did not deliver'):
        driver.drive(body, key, SimpleNamespace(engagement='task', task_type='coding'), Log())
    assert session.replan_uncovered_pending and session.replan_uncovered == ('tests',)
    assert session.synthetic and session.plan_off and len(coders) == 2
    resumed_store = LoopStore(path)
    resumed = resumed_store.get(key)
    assert resumed is not session and resumed.plan is not session.plan
    assert resumed.replan_uncovered_pending and resumed.replan_uncovered == ('tests',)
    assert not resumed.verify_replanned and not resumed.thrash_replanned
    continued = Loop(driver._ctx, resumed_store)
    log = Log()
    result = continued.drive(body, key, SimpleNamespace(engagement='task', task_type='coding'), log)
    assert result['choices'][0]['message']['tool_calls'][0]['id'] == 'coder-3'
    assert resumed.synthetic and resumed.plan_off and not resumed.replan_uncovered_pending
    assert [name for name, _ in log.events].count('loop.replan_uncovered_delivered') == 1
    assert 'tests' in json.dumps(coders[-1])
    assert 'loop.done' not in [name for name, _ in log.events]
    assert resumed.plan.status == 'in_progress'
    after_retention = LoopStore(path).get(key)
    assert after_retention.replan_uncovered == ('tests',)
    assert not after_retention.replan_uncovered_pending
