"""F40 real Root binding and explicitly corrected lifecycle boundaries (offline)."""
from dataclasses import replace
from types import SimpleNamespace
import json
import time

import pytest

from cria import assistruntime, loop, repositorychecks as policy, probegate, planner, massage, bodykeys
from tests.test_executable_assist_pilots import rig, Log, TOOLS


def runtime(definition=policy.DEFINITION, *, level=5, disabled=(), experimental_planning=False):
    registrations = tuple(d for d in assistruntime.DEFINITIONS if d.policy.id != definition.policy.id) + (definition,)
    return assistruntime.AssistRuntime.select(level=level, registrations=registrations, disabled=disabled,
                                            experimental_planning=experimental_planning)


def call(label='selected'):
    return {'id': label, 'type': 'function', 'function': {'name': 'exec_command', 'arguments': json.dumps({'cmd': label})}}


BODY = {'messages': [{'role': 'user', 'content': 'Implement the feature.'}], 'tools': TOOLS}


@pytest.mark.parametrize('level', range(6))
def test_registration_and_immutable_exact_projection(level):
    root = assistruntime.AssistRuntime.select(level=level)
    assert sum(d is policy.DEFINITION for d in assistruntime.DEFINITIONS) == 1
    assert root.repository_checks is (policy.DEFINITION if level >= 4 else None)
    with pytest.raises(AttributeError): root.repository_checks = None
    assert not policy.DEFINITION.policy.migrated and assistruntime.TASK_REVIEW.policy.migrated


@pytest.mark.parametrize('hook', ['execute', 'completion', 'replan', 'reissue'])
def test_actual_private_entry_uses_exact_selected_hook(monkeypatch, hook):
    received = []
    def selected(source, state, *services, **options):
        received.append((source, state, services, options))
        assert isinstance(source, policy.Input)
        if hook == 'completion':
            return policy.Result(policy.Status.OBSERVED, text='selected findings', outcome=probegate.GateOutcome(ran=False))
        return policy.Result(policy.Status.PENDING, call(), pending_kind=policy.PendingKind.CHECK)
    gs = loop.GuardState(coder_turns=15, awaiting_probe=True, gate_replan_required=True)
    monkeypatch.setattr(probegate, 'plan_gate', lambda *a, **k: probegate.GatePlan(workspace='', script='canonical'))
    root = runtime(replace(policy.DEFINITION, **{hook: selected}))
    with assistruntime.bound(root):
        if hook == 'execute': result = loop.guard_periodic_gate(gs, BODY, Log())
        elif hook == 'completion': result = loop.guard_gate_verdict(gs, BODY, Log())
        elif hook == 'replan': result = loop.guard_gate_replan_after_survey(gs, BODY, Log())
        else: result = loop.guard_probe_reissue(gs, BODY, Log(), rewritten=True)
    assert len(received) == 1 and received[0][1] is gs
    if hook in ('execute', 'reissue'):
        assert result['choices'][0]['message']['tool_calls'] == [call()]
    else:
        assert result == ('selected findings' if hook == 'completion' else call())


@pytest.mark.parametrize('synthetic', [False, True])
def test_real_driver_resume_and_observe_share_selected_definition(synthetic):
    seen = []
    def reissue(source, state, services, evidence):
        seen.append(('reissue', source.driver))
        return policy.reissue(source, state, services, evidence)
    def replan(source, state, services, **options):
        seen.append(('replan', source.driver))
        return policy.replan(source, state, services, **options)
    def resume(source, state, services, evidence, judgments, hooks):
        seen.append(('resume', source.driver))
        assert hooks.reissue is reissue and hooks.replan is replan
        return policy.resume(source, state, services, evidence, judgments, hooks)
    def observe(state, *, acting):
        seen.append(('observe', acting))
        policy.observe_acting_turn(state, acting=acting)
    root = runtime(replace(policy.DEFINITION, resume=resume, reissue=reissue, replan=replan, observe=observe))
    driver, state, body, frames = rig(synthetic, root, periodic=True)
    assert driver.drive(body, 'sid:pilot', None, Log()) is not None
    assert ('resume', policy.Driver.TASK if synthetic else policy.Driver.STEP) in seen
    assert seen.count(('observe', True)) == 1 and state.coder_turns == 1
    assert state.last_gate_ran and state.last_gate_red and not state.gate_fresh
    assert 'missing go.sum entry' in json.dumps(frames)


@pytest.mark.parametrize('different_executor', [False, True])
def test_bootstrap_mismatch_rejected_before_work_and_finally_overwrite(monkeypatch, different_executor):
    original = runtime()
    changed = runtime(replace(policy.DEFINITION, observe=lambda *a, **k: None)) if different_executor else runtime(disabled=(policy.DEFINITION.policy.id,))
    driver, _, _, _ = rig(True, changed)
    driver._store.drop('sid:pilot')
    bootstrap = loop.SurveyBootstrap(pilot_selection=original.selected, pilot_binding=original, probe_call_id='original')
    driver._store.put_bootstrap('sid:pilot', bootstrap)
    work = []
    monkeypatch.setattr(driver, '_drive_locked', lambda *a: work.append(True))
    with pytest.raises(ValueError, match='Pilot assist selection cannot change'):
        driver.drive(BODY, 'sid:pilot', None, Log())
    assert work == [] and bootstrap.pilot_binding is original and bootstrap.probe_call_id == 'original'


@pytest.mark.parametrize('disabled', [False, True])
def test_deferred_bootstrap_is_pinned_before_first_gate_work(monkeypatch, disabled):
    root = runtime(disabled=(policy.DEFINITION.policy.id,) if disabled else ())
    driver, _, _, _ = rig(True, root)
    driver._store.drop('sid:pilot')
    outcome = planner.PlanOutcome()
    outcome.survey_pending = True
    seen = []
    def compose(state, *a, **k):
        seen.append(state)
        assert state.pilot_binding is root and state.pilot_selection == root.selected
        return call('survey')
    monkeypatch.setattr(loop, 'guard_gate_op', compose)
    monkeypatch.setattr(driver, '_drive_locked', lambda body, key, classification, log, **kwargs:
        driver._defer_planner_survey(outcome, body['messages'], body, key, log))
    result = driver.drive(BODY, 'sid:pilot', None, Log())
    assert result['choices'][0]['message']['tool_calls'] == [call('survey')]
    assert driver._store.get_bootstrap('sid:pilot') is seen[0]


def test_unbound_unknown_origin_pending_rejects_optional_policy_without_default(monkeypatch):
    assert not assistruntime.is_bound()
    state = loop.GuardState(awaiting_probe=True, probe_call_id='pending')
    seen = []
    monkeypatch.setattr(probegate, 'plan_gate', lambda *a, **k: seen.append(True) or probegate.GatePlan(workspace='', script='unexpected'))
    with pytest.raises(ValueError, match='explicit.*bound|Explicit.*bound'):
        loop.guard_probe_reissue(state, BODY, Log(), rewritten=True)
    assert seen == [] and state.pilot_selection is None and state.pilot_binding is None


def test_bound_empty_pending_adopts_current_library_use_without_optional_work():
    root = assistruntime.AssistRuntime(None, (), None, 0, (), ())
    state = loop.GuardState(awaiting_probe=True, probe_call_id='pending')
    with assistruntime.bound(root):
        assert loop.guard_probe_reissue(state, BODY, Log(), rewritten=True) is None
    assert state.pilot_binding is root and state.pilot_selection == ()
    assert state.awaiting_probe and state.probe_call_id == 'pending'


def acting(label):
    return {'choices': [{'message': {'role': 'assistant', 'content': '', 'tool_calls': [call(label)]}, 'finish_reason': 'tool_calls'}]}


@pytest.mark.parametrize('retry', ['lost', 'refused', 'pasted', 'leg0'])
def test_actual_main_to_done_helper_counts_retained_reask_once(monkeypatch, retry):
    driver, state, body, _ = rig(True, runtime())
    initial = {'choices': [{'message': {'role': 'assistant', 'content': 'pasted' if retry == 'pasted' else 'done'}}]}
    if retry == 'lost': initial[massage.LOST_CALL_KEY] = {'tried': ['absent'], 'menu': ['exec_command']}
    if retry == 'refused': initial[bodykeys.FENCED_REFUSED] = {'reason': 'not run', 'tool': 'exec_command'}
    retained = acting('retained')
    replies = iter([initial, retained])
    monkeypatch.setattr(driver, '_coder_turn', lambda *a, **k: next(replies))
    monkeypatch.setattr(driver, '_pasted_file_unsaved', lambda sess, text, body: text == 'pasted')
    monkeypatch.setattr(driver, '_unexecuted_nudge_text', lambda *a: 'emit the actual write')
    result = driver.drive(body, 'sid:pilot', None, Log())
    assert result is retained and state.coder_turns == 1
    assert not state.gate_fresh


def test_actual_thrash_redrive_counts_only_retained_nested_reply(monkeypatch):
    driver, state, body, _ = rig(False, runtime())
    discarded, retained = acting('discarded'), acting('retained')
    replies = iter([discarded, retained])
    monkeypatch.setattr(driver, '_coder_turn', lambda *a, **k: next(replies))
    attempts = []
    def thrash(sess, key, body, idx, log):
        attempts.append(True)
        if len(attempts) == 1:
            return driver._work_item(sess, key, body, log, sess.plan.current(), idx)
        return None
    monkeypatch.setattr(driver, '_replan_if_thrashing', thrash)
    assert driver.drive(body, 'sid:pilot', None, Log()) is retained
    assert len(attempts) == 2 and state.coder_turns == 1
    assert state.step_tool_calls == 2


@pytest.mark.parametrize('entry', ['task', 'step', 'named'])
@pytest.mark.parametrize('condition', ['open', 'poll-cap', 'terminal', 'new-cap'])
def test_real_pending_recovery_selected_hook_owns_same_plan_poll_and_budgets(monkeypatch, entry, condition):
    from tests.test_gate_outlives_the_harness_yield import _plan, _running_envelope
    received, composed = [], []
    def selected(source, state, services, evidence):
        received.append((source, state, state.probe_call_id))
        assert evidence.raw is loop._read_tool_result and evidence.read is loop.read_gate
        return policy.reissue(source, state, services, evidence)
    root = runtime(replace(policy.DEFINITION, reissue=selected))
    driver, state, body, frames = rig(entry == 'task', root)
    plan = _plan()
    plan.transport_started = time.monotonic()
    plan.script = 'original launch'
    assert probegate.ingest_transport(plan, _running_envelope(plan)) == 'running'
    state.gate_plan = plan
    state.coder_turns = 7
    state.probe_call_id = 'owned'
    state.awaiting_probe = entry != 'named'
    state.redirect_probe = entry == 'task'
    if entry == 'named':
        state.completion_probe_id = 'named-owned'
        state.probe_call_id = 'unrelated'
        state.plan.items[0].done = True
    if condition in ('poll-cap', 'new-cap'): state.probe_poll_reissues = policy.MAX_PROBE_REISSUES
    if condition == 'new-cap': state.probe_reissues = policy.MAX_PROBE_REISSUES
    if condition == 'terminal': probegate.fail_transport(plan, 'known terminal')
    fresh = probegate.GatePlan(workspace='/offline', script='fresh launch')
    monkeypatch.setattr(probegate, 'plan_gate', lambda *a, **k: composed.append((a, k)) or fresh)
    # Exhausted rewrite recovery with genuinely missing output is terminal UNKNOWN:
    # the required reader must not invent a running page or clean gate.
    with assistruntime.bound(root):
        if entry == 'task': result = driver._drive_single_item(state, body, 'sid:pilot', Log(), rewritten=True)
        elif entry == 'step': result = driver._verify_after_probe(state, 'sid:pilot', body, Log(), rewritten=True)
        else: result = driver._work(state, 'sid:pilot', body, Log(), rewritten=True)
    assert len(received) == 1
    source, observed, owned = received[0]
    assert source.driver is (policy.Driver.STEP if entry == 'step' else policy.Driver.TASK)
    assert owned == ('named-owned' if entry == 'named' else 'owned')
    emitted = result['choices'][0]['message']['tool_calls'][0]
    if condition == 'new-cap':
        assert composed == [] and state.gate_plan is plan and plan.transport_error
        assert not state.last_gate_ran and not state.gate_fresh
        assert state.probe_reissues <= policy.MAX_PROBE_REISSUES
        assert state.coder_turns == 8 and len(frames) == 1
        return
    assert emitted['id'] == (state.completion_probe_id if entry == 'named' else state.probe_call_id)
    if condition == 'open':
        assert composed == [] and state.gate_plan is plan
        assert state.probe_reissues == 0
        assert plan.transport_id in emitted['function']['arguments']
        assert state.probe_poll_reissues == 1
    else:
        assert len(composed) == 1 and state.gate_plan is fresh
        assert state.probe_reissues == 1 and 'fresh launch' in emitted['function']['arguments']
    assert state.coder_turns == 7 and frames == []


@pytest.mark.parametrize('entry', ['task', 'step', 'named'])
def test_real_recovery_replacement_controls_actual_correlated_call(entry):
    received = []
    def selected(source, state, services, evidence):
        received.append((source, state.probe_call_id))
        state.probe_call_id = 'replacement-owned'
        return policy.Result(policy.Status.PENDING, call('replacement-owned'),
            pending_kind=policy.PendingKind.REWRITE_POLL)
    root = runtime(replace(policy.DEFINITION, reissue=selected))
    driver, state, body, frames = rig(entry == 'task', root)
    state.probe_call_id = 'ordinary'
    state.awaiting_probe = entry != 'named'
    if entry == 'named':
        state.completion_probe_id = 'named'
        state.plan.items[0].done = True
    with assistruntime.bound(root):
        if entry == 'task': result = driver._drive_single_item(state, body, 'sid:pilot', Log(), rewritten=True)
        elif entry == 'step': result = driver._verify_after_probe(state, 'sid:pilot', body, Log(), rewritten=True)
        else: result = driver._work(state, 'sid:pilot', body, Log(), rewritten=True)
    assert len(received) == 1 and received[0][1] == ('named' if entry == 'named' else 'ordinary')
    assert result['choices'][0]['message']['tool_calls'] == [call('replacement-owned')]
    assert state.probe_call_id == 'replacement-owned'
    if entry == 'named': assert state.completion_probe_id == 'replacement-owned'
    assert frames == [] and state.coder_turns == 0


@pytest.mark.parametrize('hook', ['execute', 'resume', 'observe', 'completion', 'replan', 'reissue'])
def test_every_binding_callable_is_required(hook):
    with pytest.raises(ValueError): runtime(replace(policy.DEFINITION, **{hook: None}))


@pytest.mark.parametrize('field', ['id', 'stage', 'both'])
def test_canonical_class_cannot_escape_contract_by_relabelling(field):
    change = {}
    if field in ('id', 'both'): change['id'] = 'forged-repository-id'
    if field in ('stage', 'both'): change['stage'] = 'forged-repository-stage'
    with pytest.raises(ValueError): runtime(replace(policy.DEFINITION, policy=replace(policy.DEFINITION.policy, **change)))


@pytest.mark.parametrize('mode', ['disabled', 'empty', 'all-off', 'low-rung'])
def test_optional_none_skips_all_hook_factories_and_clock(monkeypatch, mode):
    root = (assistruntime.AssistRuntime(None, (), None, 0, (), ()) if mode == 'empty' else
            runtime(level=0, disabled=tuple(d.policy.id for d in assistruntime.DEFINITIONS)) if mode == 'all-off' else
            runtime(level=0) if mode == 'low-rung' else runtime(disabled=(policy.DEFINITION.policy.id,)))
    def poison(*a, **k): raise AssertionError('optional factory executed')
    state = loop.GuardState(coder_turns=15, awaiting_probe=True, gate_replan_required=True)
    monkeypatch.setattr(loop, '_repository_input', poison)
    monkeypatch.setattr(loop, '_repository_probes', poison)
    monkeypatch.setattr(loop, '_repository_evidence', poison)
    with assistruntime.bound(root):
        assert loop.guard_periodic_gate(state, BODY, Log()) is None
        assert loop.guard_gate_replan_after_survey(state, BODY, Log()) is None
        assert loop.guard_probe_reissue(state, BODY, Log(), rewritten=True) is None
        retained = acting('real-coder')
        assert loop._forward_acting_coder(state, retained) is retained
    assert state.coder_turns == 15 and state.gate_replan_required and not state.gate_fresh


def test_disabled_policy_still_records_required_real_failure_and_skips_judgments(monkeypatch):
    root = runtime(disabled=(policy.DEFINITION.policy.id,))
    driver, state, body, frames = rig(True, root, periodic=True)
    def poison(*a, **k): raise AssertionError('optional judgment executed')
    monkeypatch.setattr(loop, '_repository_judgments', poison)
    assert driver.drive(body, 'sid:pilot', None, Log()) is not None
    assert state.last_gate_ran and state.last_gate_red and not state.gate_fresh
    assert not state.periodic_probe and not state.awaiting_probe and state.coder_turns == 0
    assert state.last_gate_flag and 'missing go.sum entry' in state.last_gate_flag


def test_actual_store_restore_resets_only_transient_repository_lifecycle(tmp_path):
    root = runtime()
    state = loop._plan_off_session(loop._synthetic_plan('task'), '')
    state.pilot_selection, state.pilot_binding = root.selected, root
    state.periodic_probe = state.awaiting_probe = state.done_probe = True
    state.probe_call_id, state.completion_probe_id = 'in-flight', 'named-in-flight'
    state.coder_turns, state.probe_reissues, state.probe_poll_reissues = 14, 1, 2
    state.gate_plan = probegate.GatePlan(workspace='/offline', script='not durable')
    store = loop.LoopStore(str(tmp_path / 'state.json'))
    store.put('sid:first', state)
    bootstrap = loop.SurveyBootstrap(pilot_selection=root.selected, pilot_binding=root)
    store.put_bootstrap('sid:bootstrap', bootstrap)
    store.persist('sid:first')
    assert store.get('sid:first') is state and store.get_bootstrap('sid:bootstrap') is bootstrap
    restored = loop.LoopStore(str(tmp_path / 'state.json'))
    fresh = restored.get('sid:first')
    assert fresh.pilot_selection == root.selected and fresh.pilot_binding is None
    assert fresh.gate_plan is None and not fresh.periodic_probe and not fresh.awaiting_probe and not fresh.done_probe
    assert fresh.probe_call_id == fresh.completion_probe_id == ''
    assert fresh.coder_turns == fresh.probe_reissues == fresh.probe_poll_reissues == 0
    assert restored.get_bootstrap('sid:bootstrap') is None
    store.drop('sid:first')
    other = loop._plan_off_session(loop._synthetic_plan('other task'), '')
    store.put('sid:other', other)
    assert other.gate_plan is None and other.pilot_binding is None and other.coder_turns == 0


@pytest.mark.parametrize('bad', [
    policy.Result(policy.Status.SILENT, outcome=probegate.GateOutcome(ran='false')),
    policy.Result(policy.Status.SILENT, outcome=probegate.GateOutcome(transport_pending=True)),
    policy.Result(policy.Status.NOT_SELECTED),
    policy.Result(policy.Status.PENDING, call('ignored-page'), pending_kind=policy.PendingKind.PAGE),
])
def test_completion_rejects_malformed_consumed_outcome_after_actual_selected_call(bad):
    seen = []
    def selected(source, state, evidence):
        seen.append((source, state, evidence))
        return bad
    state = loop.GuardState(done_probe=True, probe_call_id='actual')
    with assistruntime.bound(runtime(replace(policy.DEFINITION, completion=selected))):
        with pytest.raises(ValueError): loop.guard_gate_verdict(state, BODY, Log())
    assert len(seen) == 1 and isinstance(seen[0][0], policy.Input)
    assert seen[0][1] is state and seen[0][2].raw is loop._read_tool_result


@pytest.mark.parametrize('disabled', [False, True])
def test_initial_bootstrap_birth_pins_before_required_gate_even_without_f40(monkeypatch, disabled):
    root = runtime(disabled=(policy.DEFINITION.policy.id,) if disabled else (), experimental_planning=True)
    driver, _, body, _ = rig(False, root)
    driver._store.drop('sid:pilot')
    view = SimpleNamespace(root='/offline', surveyed=False)
    monkeypatch.setattr(loop.wsview, 'current', lambda *a, **k: view)
    seen = []
    def compose(state, *a, **k):
        seen.append(state)
        assert state.pilot_binding is root and state.pilot_selection == root.selected
        return call('initial-survey')
    monkeypatch.setattr(loop, 'guard_gate_op', compose)
    def poison(*a, **k): raise AssertionError('optional admission used for required bootstrap')
    monkeypatch.setattr(loop, '_requested_repository_probe', poison)
    classification = SimpleNamespace(engagement='task', task_type='coding')
    result = driver.drive(body, 'sid:pilot', classification, Log())
    assert result['choices'][0]['message']['tool_calls'] == [call('initial-survey')]
    assert driver._store.get_bootstrap('sid:pilot') is seen[0]


def test_bootstrap_promotion_transfers_same_references_before_put_and_drop(monkeypatch):
    original = runtime()
    current = replace(original)
    assert current == original and current is not original
    driver, _, body, _ = rig(True, current)
    driver._store.drop('sid:pilot')
    bootstrap = loop.SurveyBootstrap(pilot_selection=original.selected, pilot_binding=original,
        probe_call_id='survey', gate_plan=probegate.GatePlan(workspace='', script='survey'))
    driver._store.put_bootstrap('sid:pilot', bootstrap)
    body['messages'] += [{'role': 'tool', 'tool_call_id': 'survey', 'content': 'survey completed'}]
    events = []
    read, put, drop = loop.read_gate, driver._store.put, driver._store.drop_bootstrap
    def reading(plan, raw, log):
        assert driver._store.get_bootstrap('sid:pilot') is bootstrap
        events.append('fact-read')
        return read(plan, raw, log)
    def publish(key, successor):
        assert successor.pilot_selection is bootstrap.pilot_selection
        assert successor.pilot_binding is bootstrap.pilot_binding
        assert driver._store.get_bootstrap(key) is bootstrap
        events.append('put')
        return put(key, successor)
    def consume(key):
        successor = driver._store.get(key)
        assert successor is not None and successor.pilot_binding is original
        assert successor.pilot_selection is bootstrap.pilot_selection
        events.append('drop')
        return drop(key)
    def coder(successor, *a, **k):
        assert successor.pilot_binding is original and driver._store.get_bootstrap('sid:pilot') is None
        events.append('coder')
        return acting('new-task-action')
    monkeypatch.setattr(loop, 'read_gate', reading)
    monkeypatch.setattr(driver._store, 'put', publish)
    monkeypatch.setattr(driver._store, 'drop_bootstrap', consume)
    monkeypatch.setattr(driver, '_coder_turn', coder)
    result = driver.drive(body, 'sid:pilot', SimpleNamespace(task_type='coding'), Log())
    assert result['choices'][0]['message']['tool_calls'] == [call('new-task-action')]
    assert events == ['fact-read', 'put', 'drop', 'coder']
    assert driver._store.get('sid:pilot').pilot_binding is original


def test_exception_finally_never_overwrites_equal_existing_bootstrap_pin(monkeypatch):
    original = runtime()
    driver, _, _, _ = rig(True, replace(original))
    driver._store.drop('sid:pilot')
    bootstrap = loop.SurveyBootstrap(pilot_selection=original.selected, pilot_binding=original)
    ids = bootstrap.pilot_selection
    driver._store.put_bootstrap('sid:pilot', bootstrap)
    def fail(*a, **kwargs): raise RuntimeError('intentional failure after entry validation')
    monkeypatch.setattr(driver, '_drive_locked', fail)
    with pytest.raises(RuntimeError, match='intentional failure'):
        driver.drive(BODY, 'sid:pilot', None, Log())
    assert bootstrap.pilot_binding is original and bootstrap.pilot_selection is ids


@pytest.mark.parametrize('returned', [False, 'invalid observe return'])
def test_observe_return_contract_is_checked_after_actual_forward_callback(returned):
    seen = []
    def observe(state, *, acting):
        seen.append((state, acting))
        return returned
    root = runtime(replace(policy.DEFINITION, observe=observe))
    driver, state, body, _ = rig(True, root)
    with pytest.raises(ValueError, match='observe.*None'):
        driver.drive(body, 'sid:pilot', None, Log())
    assert seen == [(state, True)]


def test_explicit_empty_selection_never_reads_optional_pending_or_clock_state():
    class NoOptionalReads(loop.GuardState):
        def __getattribute__(self, name):
            if name in ('periodic_probe', 'awaiting_probe', 'done_probe', 'coder_turns', 'gate_plan'):
                raise AssertionError('optional state detection: ' + name)
            return super().__getattribute__(name)
    state = NoOptionalReads()
    empty = assistruntime.AssistRuntime(None, (), None, 0, (), ())
    with assistruntime.bound(empty):
        assert loop.guard_periodic_gate(state, BODY, Log()) is None
        assert loop.guard_probe_reissue(state, BODY, Log(), rewritten=True) is None
    assert state.pilot_binding is empty and state.pilot_selection == ()


def test_public_drive_preserves_real_step_pending_state_through_independent_recovery_caps(monkeypatch):
    from tests.test_gate_outlives_the_harness_yield import _plan
    seen, composed = [], []
    def recovery(source, state, services, evidence):
        seen.append((source, state.awaiting_probe, state.gate_plan))
        return policy.reissue(source, state, services, evidence)
    root = runtime(replace(policy.DEFINITION, reissue=recovery))
    driver, state, body, frames = rig(False, root)
    def fresh_plan(*a, **k):
        plan = _plan()
        plan.transport_started = time.monotonic()
        plan.script = 'real pending launch'
        composed.append(plan)
        return plan
    original = fresh_plan()
    state.gate_plan, state.awaiting_probe, state.probe_call_id = original, True, 'original'
    driver._store.observe_shape('sid:pilot', 'prior-root', 5)
    monkeypatch.setattr(probegate, 'plan_gate', fresh_plan)
    monkeypatch.setattr(driver, '_verify', lambda *a, **k: (False, 'checks remain unknown'))
    events = []
    for number in range(2 * policy.MAX_PROBE_REISSUES + 1):
        request = {**body, 'messages': [{'role': 'user', 'content': f'Compacted continuation {number}'}]}
        log = Log()
        result = driver.drive(request, 'sid:pilot', None, log)
        events.extend(log.events)
        assert seen[-1][1] is True  # the actual public caller must not erase pending ownership
        assert seen[-1][0].driver is policy.Driver.STEP and seen[-1][0].rewritten
        if number < policy.MAX_PROBE_REISSUES:
            assert state.gate_plan is original and len(composed) == 1
            assert state.probe_reissues == 0 and state.probe_poll_reissues == number + 1
        elif number < 2 * policy.MAX_PROBE_REISSUES:
            assert state.probe_reissues == number - policy.MAX_PROBE_REISSUES + 1
            assert len(composed) == number - policy.MAX_PROBE_REISSUES + 2
        if number < 2 * policy.MAX_PROBE_REISSUES:
            emitted = result['choices'][0]['message']['tool_calls'][0]
            assert emitted['id'] == state.probe_call_id and state.awaiting_probe
            assert frames == [] and state.coder_turns == 0
    names = [name for name, fields in events]
    assert names.count('gate.transport_poll_after_rewrite') == policy.MAX_PROBE_REISSUES
    assert names.count('loop.probe_reissued') == policy.MAX_PROBE_REISSUES
    assert state.gate_plan.transport_error and not state.gate_fresh and not state.last_gate_ran
    assert not state.awaiting_probe and not state.plan.items[0].done
    assert len(frames) == 1 and state.coder_turns == 1
    readings = [fields for name, fields in events if name == 'loop.probe']
    assert readings and readings[-1]['transport_unknown'] and not readings[-1]['passed']


@pytest.mark.parametrize('disposition', ['terminal', 'survey-deferred', 'retry', 'exception'])
@pytest.mark.parametrize('raw', [None, 'sandbox refused command'])
def test_public_bootstrap_decline_cleanup_waits_for_actual_planning_disposition(monkeypatch, disposition, raw):
    from tests.test_gate_outlives_the_harness_yield import _plan
    root = runtime(experimental_planning=True)
    driver, _, body, frames = rig(False, root)
    driver._store.drop('sid:pilot')
    driver._ctx.planner = SimpleNamespace(_retriable_failure=disposition == 'retry')
    bootstrap = loop.SurveyBootstrap(pilot_selection=root.selected, pilot_binding=root,
        gate_plan=_plan(), probe_call_id='survey')
    driver._store.put_bootstrap('sid:pilot', bootstrap)
    bootstrap.gate_plan.script = probegate._gate_sentinel([])
    emitted = call('survey')
    emitted['function']['arguments'] = json.dumps({'cmd': bootstrap.gate_plan.script})
    body['messages'].append({'role': 'assistant', 'tool_calls': [emitted]})
    if raw is not None:
        body['messages'].append({'role': 'tool', 'tool_call_id': 'survey', 'content': raw})
    planning = []
    def plan(messages, log, **options):
        assert driver._store.get_bootstrap('sid:pilot') is bootstrap
        assert bootstrap.gate_plan.transport_error  # real read already established UNKNOWN
        assert not any(m.get('role') == 'tool' for m in messages)
        planning.append(True)
        if disposition == 'exception': raise RuntimeError('planner interrupted')
        outcome = planner.PlanOutcome()
        outcome.survey_pending = disposition == 'survey-deferred'
        return None, outcome
    monkeypatch.setattr(driver, '_plan_for', plan)
    monkeypatch.setattr(loop, 'guard_gate_op', lambda *a, **k: call('replacement-survey'))
    classification = SimpleNamespace(engagement='task', task_type='other')
    log = Log()
    if disposition == 'exception':
        with pytest.raises(RuntimeError, match='planner interrupted'):
            driver.drive(body, 'sid:pilot', classification, log)
    else:
        result = driver.drive(body, 'sid:pilot', classification, log)
        assert (result is not None) is (disposition == 'survey-deferred')
    assert planning == [True] and frames == [] and driver._store.get('sid:pilot') is None
    active = driver._store.get_bootstrap('sid:pilot')
    if disposition == 'terminal':
        assert active is None
    elif disposition == 'survey-deferred':
        assert active is not bootstrap and active.probe_call_id == 'replacement-survey'
        assert active.pilot_binding is bootstrap.pilot_binding and active.pilot_selection is bootstrap.pilot_selection
    else:
        assert active is bootstrap and active.pilot_binding is root
    assert 'loop.survey_bootstrap_finished' in [name for name, fields in log.events]
