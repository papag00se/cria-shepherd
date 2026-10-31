"""F36 is one selected production lifecycle, including its nested policy hooks."""
from dataclasses import fields, replace
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from cria import assistruntime, bodykeys, completiondiagnosis as policy, loop, prompts, wsview
from cria.plan import Plan, PlanItem
from tests.test_a_required_test_unknown_cannot_complete import _capture_view
from tests.test_completion_approval_policies import action
from test_loop import _Rlog


def runtime(definition=policy.DEFINITION, *, disabled=False, level=5):
    registry = tuple(d for d in assistruntime.DEFINITIONS if d.policy.id != policy.DEFINITION.policy.id) + (definition,)
    return assistruntime.AssistRuntime.select(level=level, registrations=registry,
        disabled=(definition.policy.id,) if disabled else ())


@pytest.mark.parametrize('level', range(6))
def test_default_registration_level_and_actual_source_identity(level):
    assert sum(d is policy.DEFINITION for d in assistruntime.DEFINITIONS) == 1
    assert policy.DEFINITION.policy.default_level == 4 and not policy.DEFINITION.policy.migrated
    assert assistruntime.AssistRuntime.select(level=level).completion_diagnosis is (
        policy.DEFINITION if level >= 4 else None)


@pytest.mark.parametrize('hook', [f.name for f in fields(policy.DiagnosisDefinition) if f.name != 'policy'])
def test_every_required_hook_is_callable(hook):
    with pytest.raises(ValueError):
        runtime(replace(policy.DEFINITION, **{hook: None}))


def test_stage_relabel_cannot_evade_canonical_contract():
    with pytest.raises(ValueError, match='Invalid completion diagnosis binding'):
        runtime(replace(policy.DEFINITION, policy=replace(policy.DEFINITION.policy, stage='other')))


def test_real_negative_verdict_calls_exact_replacement_and_preserves_root_authority():
    calls = []
    def execute(source, services):
        calls.append((source, services))
        assert source.candidate() == {'reason': 'candidate'}
        return policy.DiagnosisResult(policy.DiagnosisStatus.GROUNDED, 'selected evidence', 'selected action',
                                      'missing_file', 'out.txt')
    d = replace(policy.DEFINITION, execute=execute)
    with assistruntime.bound(runtime(d)):
        result = loop._verdict_nudge({'reason': 'candidate'}, False, task='generated STEP',
            original_task='original TASK', action_log='actual log', checks='shared checks',
            participation_facts='shared participation', rlog=_Rlog())
        assert assistruntime.current().completion_diagnosis is d
    assert len(calls) == 1
    source = calls[0][0]
    assert (source.task, source.original_task, source.action_log, source.checks, source.participation_facts) == (
        'generated STEP', 'original TASK', 'actual log', 'shared checks', 'shared participation')
    assert result.evidence == 'selected evidence' and result.action == 'selected action'
    assert result.subject == 'out.txt' and result.diagnosis_kind == 'missing_file'


@pytest.mark.parametrize('empty', [False, True])
def test_absent_selection_does_no_optional_workspace_or_question_work(monkeypatch, empty):
    def poison(*args, **kwargs):
        raise AssertionError('disabled optional work')
    monkeypatch.setattr(loop, '_workspace_subject', poison)
    monkeypatch.setattr(loop, 'workspace_inventory', poison)
    monkeypatch.setattr(loop, '_judge_completion', poison)
    selected = assistruntime.AssistRuntime(None, (), None, 0, (), ()) if empty else runtime(disabled=True)
    with assistruntime.bound(selected):
        assert selected.completion_diagnosis is None
        result = loop._negative_diagnosis_nudge({'diagnosis_kind': 'missing_file', 'subject': 'out.txt',
            'evidence_source': 'workspace_absence'}, task='create out.txt', workspace_root='/workspace', ask=poison)
        observed = loop.observe_task_missing_file('create out.txt', workspace_root='/workspace',
            reasoner_chat=poison, reasoner_role=None, rlog=_Rlog())
    assert not result and not observed


def test_real_observer_boundary_invokes_selected_observe_without_canonical_transport():
    calls = []
    def observe(source, services):
        calls.append((source, services))
        return policy.DiagnosisResult(policy.DiagnosisStatus.GROUNDED, 'actual replacement', '', 'missing_file', 'out.txt')
    d = replace(policy.DEFINITION, observe=observe)
    with assistruntime.bound(runtime(d)):
        result = loop.observe_task_missing_file('create out.txt', workspace_root='/workspace',
            reasoner_chat=lambda *args: b'{}', reasoner_role=None, rlog=_Rlog())
    assert len(calls) == 1 and calls[0][1].execute is d.execute
    assert result.subject == 'out.txt'


def driver_state(*, assists=False, coder=None):
    context = loop.LoopContext(planner=None, coder_chat=coder or (lambda *args: b'{}'),
        reasoner_chat=lambda *args: b'{}', runs_dir='', self_compact=False, focus_trim=False,
        assists=assists, satisfaction_check_start=1, satisfaction_check_every=1)
    driver = loop.Loop(context)
    session = loop.PlanSession(plan=Plan(id='diagnosis', task='  Original TASK create out.txt.\n',
        created='now', items=[PlanItem('unrelated STEP')]), workspace_root='/workspace')
    body = {'messages': [{'role': 'user', 'content': session.plan.task}], 'tools': [
        {'type': 'function', 'function': {'name': 'read_file', 'parameters': {'type': 'object',
            'properties': {'path': {'type': 'string'}}}}}]}
    return driver, session, body


def grounded():
    return policy.DiagnosisResult(policy.DiagnosisStatus.GROUNDED, 'measured absence',
                                   'create out.txt.', 'missing_file', 'out.txt')


@pytest.mark.parametrize('status', [policy.DiagnosisStatus.WITHHELD, policy.DiagnosisStatus.NOT_APPLICABLE])
def test_payload_in_non_grounded_replacement_cannot_become_action(status):
    d = replace(policy.DEFINITION, execute=lambda *args: replace(grounded(), status=status))
    with assistruntime.bound(runtime(d)):
        result = loop._negative_diagnosis_nudge({}, task='original')
    assert not result and not result.subject and not result.action
    assert result.diagnosis_result.status is status


@pytest.mark.parametrize('invalid,error', [(None, TypeError), (True, TypeError),
                                         (replace(grounded(), status='grounded'), ValueError)])
def test_direct_execute_invalid_result_is_not_guidance(invalid, error):
    calls = []
    def execute(source, services):
        calls.append((source, services))
        return invalid
    d = replace(policy.DEFINITION, execute=execute)
    with assistruntime.bound(runtime(d)), pytest.raises(error):
        loop._negative_diagnosis_nudge({}, task='original')
    assert len(calls) == 1 and isinstance(calls[0][0], policy.DiagnosisInput)
    assert calls[0][0].task == 'original' and isinstance(calls[0][1], policy.GroundingServices)


def test_all_nested_callbacks_are_same_selected_object_and_not_canonical_globals(monkeypatch):
    driver, session, _body = driver_state()
    calls = []
    def execute(source, services):
        calls.append(('execute', source.original_task))
        return grounded()
    def observe(source, services):
        calls.append(('observe', source.task))
        assert services.execute is d.execute
        return policy.DEFINITION.observe(source, services)
    def arm(state, subject, reason):
        calls.append(('arm', subject))
        return policy.DEFINITION.arm(state, subject, reason)
    def deliver(source, state, services):
        calls.append(('deliver', source.trigger))
        assert services.arm is d.arm
        return policy.DEFINITION.deliver(source, state, services)
    d = replace(policy.DEFINITION, execute=execute, observe=observe, arm=arm, deliver=deliver)
    view = _capture_view('/workspace', {}, session='nested-hook')
    monkeypatch.setattr(loop.wsview, 'current', lambda root: view)
    monkeypatch.setattr(loop, '_judge_completion', lambda *args, **kwargs:
        {'choices': [{'message': {'content': '{"missing_file":true}'}}]})
    def poison(*args, **kwargs):
        raise AssertionError('canonical nested hook bypass')
    for name in ('ground_diagnosis', 'observe_missing_file', 'arm_remediation', 'deliver_gap'):
        monkeypatch.setattr(policy, name, poison)
    with assistruntime.bound(runtime(d)):
        services = loop._diagnosis_lifecycle_services(d, '/workspace', driver._ctx.reasoner_chat, None, _Rlog())
        assert services.observe is d.observe and services.deliver is d.deliver
        result = d.observe_scheduled(policy.ScheduledObservationInput(session.plan.task, 1, 1, 1, True), session, services)
    assert result.delivery.status is policy.RemediationStatus.DELIVERED
    assert [entry[0] for entry in calls] == ['observe', 'execute', 'deliver', 'arm']
    assert calls[0][1] == calls[1][1] == session.plan.task
    assert session.completion_remediation_subject == 'out.txt'
    assert session.deliverable_observation_last_drive == 1


@pytest.mark.parametrize('plan_off', [False, True])
def test_actual_periodic_route_uses_selected_delivery_and_plan_off_never_arms(monkeypatch, plan_off):
    driver, session, body = driver_state()
    calls = []
    def deliver(source, state, services):
        calls.append((source, services))
        return policy.DEFINITION.deliver(source, state, services)
    d = replace(policy.DEFINITION, deliver=deliver)
    monkeypatch.setattr(driver, '_review_task', lambda *args, **kwargs:
        SimpleNamespace(approved=False, reason=loop._diagnosis_nudge(grounded())))
    session.drive_count = 1
    with assistruntime.bound(runtime(d)):
        assert driver._periodic_satisfaction(session, body, _Rlog(), plan_off=plan_off, blocked=False) is None
    assert len(calls) == 1 and calls[0][0].trigger is policy.DeliveryTrigger.SCHEDULED_REVIEW
    assert calls[0][1].arm is d.arm and calls[0][0].plan_off is plan_off
    assert bool(session.completion_remediation_subject) is (not plan_off)


@pytest.mark.parametrize('invalid,error', [(None, TypeError),
    (policy.RemediationResult('delivered'), ValueError),
    (policy.RemediationResult(policy.RemediationStatus.PENDING), ValueError)])
def test_periodic_invalid_delivery_is_rejected_after_actual_selected_call(monkeypatch, invalid, error):
    driver, session, body = driver_state()
    calls = []
    def deliver(source, state, services):
        calls.append((source, state, services))
        return invalid
    d = replace(policy.DEFINITION, deliver=deliver)
    monkeypatch.setattr(driver, '_review_task', lambda *args, **kwargs:
        SimpleNamespace(approved=False, reason=loop._diagnosis_nudge(grounded())))
    session.drive_count = 1
    with assistruntime.bound(runtime(d)), pytest.raises(error):
        driver._periodic_satisfaction(session, body, _Rlog(), plan_off=False, blocked=False)
    assert len(calls) == 1 and calls[0][1] is session
    assert isinstance(calls[0][0], policy.DeliveryInput) and calls[0][0].diagnosis == grounded()
    assert isinstance(calls[0][2], policy.DeliveryServices) and calls[0][2].arm is d.arm


def test_actual_terminal_uses_selected_hook_and_retained_root_without_arming(monkeypatch):
    driver, session, body = driver_state()
    received = []
    def terminal(root, available, services):
        received.append((root(), available, services))
        return policy.DEFINITION.observe_terminal(root, available, services)
    def observe(source, services):
        assert source.task == session.plan.task
        return grounded()
    d = replace(policy.DEFINITION, observe_terminal=terminal, observe=observe)
    view = _capture_view('/workspace', {}, session='terminal-root')
    monkeypatch.setattr(loop.wsview, 'current', lambda root: view)
    before = loop._session_to_dict(session)
    with assistruntime.bound(runtime(d)):
        result = driver._observe_missing_file_on_done(session, body, 'generated continuation', _Rlog())
    assert result.subject == 'out.txt' and received[0][0] == session.plan.task
    assert received[0][2].observe is d.observe
    assert loop._session_to_dict(session) == before
    assert session.deliverable_observation_last_drive == -1


@pytest.mark.parametrize('task', ['', ' \n\t '])
def test_terminal_original_task_precondition_does_not_borrow_generated_continuation(monkeypatch, task):
    driver, session, body = driver_state()
    session.plan.task = task
    def poison(*args): raise AssertionError('blank retained task reached replacement observer')
    d = replace(policy.DEFINITION, observe=poison)
    view = _capture_view('/workspace', {}, session='terminal-blank')
    monkeypatch.setattr(loop.wsview, 'current', lambda root: view)
    with assistruntime.bound(runtime(d)):
        result = driver._observe_missing_file_on_done(session, body, 'Create generated.txt now.', _Rlog())
    assert not result and not session.completion_remediation_subject
    assert session.deliverable_observation_last_drive == -1


def test_actual_scheduled_route_arm_decline_preserves_slots_but_stamps_attempt(monkeypatch):
    driver, session, body = driver_state(assists=True)
    calls = []
    def observe(source, services):
        calls.append(session.deliverable_observation_last_drive)
        return grounded()
    def arm(state, subject, reason):
        return policy.RemediationResult(policy.RemediationStatus.NOT_APPLICABLE)
    scheduled_calls = []
    def scheduled(source, state, services):
        scheduled_calls.append((source, state, services))
        assert services.observe is d.observe and services.deliver is d.deliver
        return policy.DEFINITION.observe_scheduled(source, state, services)
    d = replace(policy.DEFINITION, observe=observe, arm=arm, observe_scheduled=scheduled)
    view = _capture_view('/workspace', {}, session='arm-decline')
    monkeypatch.setattr(loop.wsview, 'current', lambda root: view)
    monkeypatch.setattr(loop, 'guard_intervene', lambda *args, **kwargs: None)
    monkeypatch.setattr(loop, 'guard_periodic_gate', lambda *args, **kwargs: None)
    monkeypatch.setattr(driver, '_periodic_step_check', lambda *args, **kwargs: None)
    monkeypatch.setattr(driver, '_periodic_satisfaction', lambda *args, **kwargs: None)
    class StopAfterObservation(Exception): pass
    monkeypatch.setattr(driver, '_prepare_coder_context', lambda *args, **kwargs: (_ for _ in ()).throw(StopAfterObservation()))
    with assistruntime.bound(runtime(d)), pytest.raises(StopAfterObservation):
        driver._work_item(session, 'key', body, _Rlog(), session.plan.items[0], 1)
    assert calls == [1] and session.deliverable_observation_last_drive == 1
    assert len(scheduled_calls) == 1 and scheduled_calls[0][1] is session
    assert scheduled_calls[0][0].task == session.plan.task
    assert not session.last_gap_named and not session.nudge_reason and not session.steer_source
    assert not session.completion_remediation_subject


@pytest.mark.parametrize('invalid,error', [(None, TypeError),
    (policy.ObservationRun(replace(grounded(), status='grounded'),
        policy.RemediationResult(policy.RemediationStatus.NOT_APPLICABLE)), ValueError),
    (policy.ObservationRun(grounded(), policy.RemediationResult('delivered')), ValueError)])
def test_scheduled_invalid_replacement_is_rejected_after_actual_selected_call(monkeypatch, invalid, error):
    driver, session, body = driver_state(assists=True)
    calls = []
    def scheduled(source, state, services):
        calls.append((source, state, services))
        return invalid
    d = replace(policy.DEFINITION, observe_scheduled=scheduled)
    monkeypatch.setattr(loop, 'guard_intervene', lambda *args, **kwargs: None)
    monkeypatch.setattr(loop, 'guard_periodic_gate', lambda *args, **kwargs: None)
    with assistruntime.bound(runtime(d)), pytest.raises(error):
        driver._work_item(session, 'key', body, _Rlog(), session.plan.items[0], 1)
    assert len(calls) == 1 and calls[0][1] is session
    assert calls[0][0] == policy.ScheduledObservationInput(session.plan.task, 1, 1, 1, True)
    assert isinstance(calls[0][2], policy.ObservationLifecycleServices)
    assert calls[0][2].observe is d.observe and calls[0][2].deliver is d.deliver


def test_real_settle_followup_and_ack_adapters_use_exact_selected_hooks():
    driver, session, body = driver_state()
    events = []
    def callback(name, status):
        def call(*args):
            events.append((name, args))
            return policy.RemediationResult(status)
        return call
    d = replace(policy.DEFINITION, arm=callback('arm', policy.RemediationStatus.PENDING),
        settle=callback('settle', policy.RemediationStatus.PENDING),
        follow_up=callback('follow_up', policy.RemediationStatus.PENDING),
        acknowledge=callback('acknowledge', policy.RemediationStatus.ACKNOWLEDGED))
    reply = {'choices': []}
    with assistruntime.bound(runtime(d)):
        loop._arm_completion_remediation(session, 'out.txt', 'evidence')
        loop._settle_completion_remediation(session, body['messages'], _Rlog())
        loop._nudge_after_remediation_nonwrite(session, body['messages'], _Rlog())
        loop._record_remediation_delivery(session, reply)
    assert [name for name, _ in events] == ['arm', 'settle', 'follow_up', 'acknowledge']
    assert all(args[0] is session for _, args in events)
    assert events[-1][1][1] is reply


@pytest.mark.parametrize('tail,settled', [([], False),
    (action('read_file', {'path': 'out.txt'}, 'r'), False),
    (action('write_file', {'path': 'other.txt', 'content': 'x'}, 'x'), False),
    (action('write_file', {'path': 'out.txt', 'content': 'x'}, 'w')[:1], False),
    (action('write_file', {'path': 'out.txt', 'content': 'x'}, 'w'), False),
    ([*action('write_file', {'path': 'out.txt', 'content': 'x'}, 'w')[:1],
      {'role': 'tool', 'tool_call_id': 'w', 'content': 'Wrote out.txt'}], True)])
def test_durable_roundtrip_same_subject_success_only_and_one_inspection_followup(tail, settled):
    driver, session, body = driver_state()
    with assistruntime.bound(runtime()):
        loop._arm_completion_remediation(session, 'out.txt', 'current evidence')
        reply = {'choices': [{'message': {'tool_calls': [{'id': 'read', 'function': {
            'name': 'read_file', 'arguments': '{"path":"out.txt"}'}}]}}]}
        loop._record_remediation_delivery(session, reply)
        restored = loop._session_from_dict(loop._session_to_dict(session))
        assert restored.completion_remediation_nonwrite_ids == ('read',)
        loop._nudge_after_remediation_nonwrite(restored, [{'role': 'tool', 'tool_call_id': 'read', 'content': 'absent'}], _Rlog())
        assert restored.completion_remediation_nonwrite_seen and restored.completion_remediation_subject == 'out.txt'
        first = restored.nudge_reason
        restored.nudge_reason = ''
        loop._nudge_after_remediation_nonwrite(restored, [{'role': 'tool', 'tool_call_id': 'read', 'content': 'absent'}], _Rlog())
        assert not restored.nudge_reason and first
        loop._settle_completion_remediation(restored, tail, _Rlog())
    assert bool(restored.completion_remediation_subject) is (not settled)


def test_reply_receipts_are_identity_bound_and_failed_calls_do_not_reuse_subject():
    bodies = iter([b'{}', RuntimeError('interrupted')])
    def chat(body, log):
        result = next(bodies)
        if isinstance(result, Exception): raise result
        return result
    tracker = loop._CoderReplyReceipts(chat)
    log = _Rlog()
    tracker.chat({bodykeys.COMPLETION_REMEDIATION: 'out.txt'}, log)
    actual = {'choices': []}
    tracker.record(actual)
    assert tracker.remediation_receipt(actual) == 'out.txt'
    assert tracker.remediation_receipt(deepcopy(actual)) == ''
    with pytest.raises(RuntimeError): tracker.chat({}, log)
    other = {'choices': []}
    tracker.record(other)
    assert tracker.remediation_receipt(other) == ''


@pytest.mark.parametrize('hook,args', [
    ('arm', ('out.txt', 'evidence')), ('acknowledge', ({'choices': []},)),
    ('follow_up', ([], None)), ('settle', ([], None))])
@pytest.mark.parametrize('bad,error', [(None, TypeError),
    (policy.RemediationResult('pending'), ValueError),
    (policy.RemediationResult(policy.RemediationStatus.DELIVERED), ValueError)])
def test_remediation_adapter_rejects_wrong_dto_status_and_cross_hook_status(hook, args, bad, error):
    # DELIVERED belongs to delivery only, never these four state transitions.
    calls = []
    def selected(*actual):
        calls.append(actual)
        return bad
    d = replace(policy.DEFINITION, **{hook: selected})
    adapter = {'arm': loop._arm_completion_remediation,
               'acknowledge': loop._record_remediation_delivery,
               'follow_up': loop._nudge_after_remediation_nonwrite,
               'settle': loop._settle_completion_remediation}[hook]
    state = object()
    with assistruntime.bound(runtime(d)), pytest.raises(error):
        adapter(state, *args)
    assert len(calls) == 1 and calls[0][0] is state
    if hook == 'arm':
        assert calls[0][1:] == ('out.txt', 'evidence')
    else:
        assert calls[0][1] is args[0]
        assert isinstance(calls[0][2], policy.RemediationServices)


def test_absent_binding_skips_every_service_and_remediation_state_access(monkeypatch):
    def poison(*args, **kwargs): raise AssertionError('optional work while unbound')
    for name in ('_diagnosis_observation_services', '_diagnosis_delivery_services',
                 '_diagnosis_lifecycle_services', '_diagnosis_remediation_services',
                 '_composed_closed_ask'):
        monkeypatch.setattr(loop, name, poison)
    driver, _session, body = driver_state()
    class NoState:
        def __getattribute__(self, name): return poison()
    state = NoState()
    with assistruntime.bound(assistruntime.AssistRuntime(None, (), None, 0, (), ())):
        assert not loop._negative_diagnosis_nudge({}, task='original')
        assert not loop.observe_task_missing_file('original', workspace_root='/workspace',
            reasoner_chat=object(), reasoner_role=None, rlog=_Rlog())
        assert not driver._observe_missing_file_on_done(state, body, 'continuation', _Rlog())
        loop._arm_completion_remediation(state, 'out.txt', 'evidence')
        loop._record_remediation_delivery(state, {})
        loop._nudge_after_remediation_nonwrite(state, [], _Rlog())
        loop._settle_completion_remediation(state, [], _Rlog())


def test_observer_protocol_transport_and_seed_identity_are_unchanged(monkeypatch):
    captured = []
    completion = {'choices': [{'message': {'content': '{"missing_file":false}'}}]}
    def judge(*args, **kwargs):
        captured.append((args, kwargs))
        return completion
    monkeypatch.setattr(loop, '_judge_completion', judge)
    role = SimpleNamespace(clean_content=lambda text: text)
    services = loop._diagnosis_observation_services(policy.DEFINITION, '/workspace', 'chat', role, 'log')
    assert services.judge('system bytes', 'user bytes') is completion
    args, kwargs = captured[0]
    assert args == ('chat', role, 'system bytes', 'user bytes', 'log')
    assert kwargs == dict(phase='deliverable-observation', workspace_root='/workspace',
                         verdict_key='missing_file', verdict_schema='observation', seed_files=True)


@pytest.mark.parametrize('invalid,error', [(None, TypeError),
    (replace(grounded(), status='grounded'), ValueError)])
def test_terminal_invalid_replacement_fails_closed(invalid, error):
    driver, session, body = driver_state()
    calls = []
    def terminal(root, available, services):
        calls.append((root(), available, services))
        return invalid
    d = replace(policy.DEFINITION, observe_terminal=terminal)
    with assistruntime.bound(runtime(d)), pytest.raises(error):
        driver._observe_missing_file_on_done(session, body, 'continuation', _Rlog())
    assert len(calls) == 1 and calls[0][0] == session.plan.task and calls[0][1] is True
    assert isinstance(calls[0][2], policy.ObservationLifecycleServices)


@pytest.mark.parametrize('invalid,error', [(None, TypeError),
    (replace(grounded(), status='grounded'), ValueError)])
def test_observer_invalid_replacement_is_rejected_after_actual_selected_call(invalid, error):
    calls = []
    def observe(source, services):
        calls.append((source, services))
        return invalid
    d = replace(policy.DEFINITION, observe=observe)
    with assistruntime.bound(runtime(d)), pytest.raises(error):
        loop.observe_task_missing_file('Original task', workspace_root='/workspace',
            reasoner_chat=object(), reasoner_role=None, rlog=_Rlog())
    assert len(calls) == 1 and calls[0][0] == policy.ObservationInput('Original task', True)
    assert isinstance(calls[0][1], policy.ObservationServices) and calls[0][1].execute is d.execute


def test_policy_relabel_wrong_type_and_duplicate_registration_rejected():
    with pytest.raises(ValueError):
        runtime(replace(policy.DEFINITION, policy=replace(policy.DEFINITION.policy, default_level=3)))
    impostor = SimpleNamespace(policy=policy.DEFINITION.policy, **{f.name: getattr(policy.DEFINITION, f.name)
        for f in fields(policy.DiagnosisDefinition) if f.name != 'policy'})
    with pytest.raises(ValueError): runtime(impostor)
    with pytest.raises(ValueError): assistruntime.AssistRuntime.select(registrations=(policy.DEFINITION, policy.DEFINITION))
    assert policy.DEFINITION.policy.migrated is False and policy.DEFINITION.policy.default_level == 4


@pytest.mark.parametrize('outcome', ['retained', 'redirected', 'failed', 'cloned'])
def test_actual_work_driver_acknowledges_only_successful_retained_same_delivery(monkeypatch, outcome):
    calls = []
    def coder(frame, log):
        assert frame[bodykeys.COMPLETION_REMEDIATION] == 'out.txt'
        assert prompts.load('completion_remediation') in str(frame['messages'])
        if outcome == 'failed': raise loop.UpstreamProtocolError('interrupted coder')
        return json.dumps({'choices': [{'message': {'role': 'assistant', 'tool_calls': [
            {'id': 'inspection', 'type': 'function', 'function': {'name': 'read_file',
                'arguments': '{"path":"out.txt"}'}}]}}]}).encode()
    driver, session, body = driver_state(coder=coder, assists=outcome == 'cloned')
    transitions = []
    def settle(state, messages, services):
        assert state is session and messages is body['messages']
        transitions.append('settle')
        return policy.DEFINITION.settle(state, messages, services)
    def follow_up(state, messages, services):
        assert state is session and messages is body['messages']
        transitions.append('follow_up')
        return policy.DEFINITION.follow_up(state, messages, services)
    def acknowledge(state, reply, services):
        transitions.append('acknowledge')
        calls.append(reply)
        return policy.DEFINITION.acknowledge(state, reply, services)
    d = replace(policy.DEFINITION, acknowledge=acknowledge, settle=settle, follow_up=follow_up)
    view = _capture_view('/workspace', {}, session='retained-actual')
    monkeypatch.setattr(loop.wsview, 'current', lambda root: view)
    monkeypatch.setattr(loop, 'guard_intervene', lambda *args, **kwargs: None)
    monkeypatch.setattr(loop, 'guard_periodic_gate', lambda *args, **kwargs: None)
    monkeypatch.setattr(driver, '_periodic_step_check', lambda *args, **kwargs: None)
    monkeypatch.setattr(driver, '_periodic_satisfaction', lambda *args, **kwargs: None)
    redirect = {'choices': [{'message': {'role': 'assistant', 'content': 'redirected'}}]}
    monkeypatch.setattr(driver, '_replan_if_thrashing', lambda *args, **kwargs:
                        redirect if outcome == 'redirected' else None)
    if outcome == 'cloned':
        monkeypatch.setattr(loop, 'guard_search_query', lambda state, reply, *args, **kwargs: deepcopy(reply))
    with assistruntime.bound(runtime(d)):
        loop._arm_completion_remediation(session, 'out.txt', 'measured evidence')
        if outcome == 'failed':
            with pytest.raises(loop.UpstreamProtocolError):
                driver._work_item(session, 'key', body, _Rlog(), session.plan.items[0], 1)
        else:
            result = driver._work_item(session, 'key', body, _Rlog(), session.plan.items[0], 1)
    assert transitions == ['settle', 'follow_up'] + (['acknowledge'] if outcome == 'retained' else [])
    if outcome == 'retained':
        assert len(calls) == 1 and calls[0] is result
        assert session.completion_remediation_nonwrite_ids == ('inspection',)
    else:
        assert calls == [] and session.completion_remediation_nonwrite_ids == ()
