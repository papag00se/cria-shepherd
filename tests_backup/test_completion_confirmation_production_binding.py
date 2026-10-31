"""F34 production selection, confirmation transport and fail-closed activation."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from cria import assistruntime, completionapproval, completiondiagnosis, completionconfirmation as policy, loop
from cria.config import Role
from tests.test_loop import _Rlog


def runtime(definition=policy.DEFINITION, *, level=5, disabled=()):
    registrations = tuple(d for d in assistruntime.DEFINITIONS if d.policy.id != definition.policy.id) + (definition,)
    return assistruntime.AssistRuntime.select(level=level, registrations=registrations, disabled=disabled)


def reply(text='CONSISTENT', rounds=1, **choice):
    return {'choices': [{'message': {'content': text}, **choice}], loop.ROUNDS_KEY: rounds}


@pytest.mark.parametrize('level', range(6))
def test_actual_root_canonical_selection(level):
    assert sum(d is policy.DEFINITION for d in assistruntime.DEFINITIONS) == 1
    assert assistruntime.AssistRuntime.select(level=level).completion_confirmation is (
        policy.DEFINITION if level >= 4 else None)


def test_real_compatibility_boundary_calls_exact_selected_executor():
    calls = []
    def execute(source, services):
        calls.append((source, services))
        return policy.Result(policy.Status.REJECTED, observed=True, reason='selected rejection', authority=source.authority)
    d = replace(policy.DEFINITION, execute=execute)
    with assistruntime.bound(runtime(d)):
        result = loop._confirm_completion('claim', 'reason', '/workspace', object(), None,
            _Rlog(), phase='satisfaction-confirm', original_task='retained root', cria_facts='literal 雪\nexit=0')
    assert len(calls) == 1 and calls[0][0].original_task == 'retained root'
    assert calls[0][0].measured_facts == 'literal 雪\nexit=0'
    assert isinstance(calls[0][1], policy.Services)
    assert result.status is policy.Status.REJECTED and tuple(result) == (False, 'selected rejection')


@pytest.mark.parametrize('incident', ['cut', 'pending', 'idless', 'uninspected', 'crossbranch'])
def test_actual_legacy_boundary_activates_source_safety(monkeypatch, incident):
    comp = reply()
    if incident == 'cut': comp['choices'][0]['finish_reason'] = 'length'
    if incident in ('pending', 'idless'):
        comp['choices'][0]['message']['tool_calls'] = [{'type': 'function', 'function': {
            'name': 'read_file', 'arguments': '{"path":"a.py"}'}, **({'id': 'pending'} if incident == 'pending' else {})}]
    responses = ([reply(rounds=0), reply('{"consistent":false,"why":"reason"}', 2), reply(rounds=0)]
                 if incident == 'crossbranch' else
                 [reply('{"consistent":false,"why":"reason"}', 2), reply(rounds=0)]
                 if incident == 'uninspected' else [comp, comp])
    calls = []
    def inspect(*args, **kwargs):
        calls.append((args, kwargs))
        return responses.pop(0)
    monkeypatch.setattr(loop.wsview, 'current', lambda root: SimpleNamespace(surveyed=True, listdir=lambda root: ['a.py']))
    monkeypatch.setattr(loop, '_judge_completion', inspect)
    with assistruntime.bound(runtime()):
        result = loop._confirm_completion('claim', 'reason', '/workspace', object(), None,
            _Rlog(), phase='satisfaction-confirm')
    assert not result.confirmed and result.observed
    assert result.status is policy.Status.UNVERIFIED
    assert len(calls) == (3 if incident == 'crossbranch' else 2 if incident == 'uninspected' else 1)


def test_task_production_order_and_original_measured_facts(monkeypatch):
    events = []
    def execute(source, services):
        events.append('confirmation')
        assert source.authority is policy.Authority.TASK and source.phase == 'satisfaction-confirm'
        assert source.original_task == source.claim == 'Original TASK'
        assert source.measured_facts == 'actual 雪\nexit=0'
        return policy.Result(policy.Status.CONFIRMED, True, True, authority=source.authority)
    d = replace(policy.DEFINITION, execute=execute)
    root = runtime(d)
    def approve(source):
        events.append(source.__class__.__name__)
        return completionapproval.ApprovalResult(completionapproval.ApprovalStatus.PERMITTED)
    root = replace(root, ordered_stages=tuple(replace(item, execute=approve)
        if item.policy.id in {p.policy.id for p in completionapproval.PRE_RELEASE} else item
        for item in root.ordered_stages))
    monkeypatch.setattr(loop, '_satisfaction_verdict', lambda *args, **kwargs: {'satisfied': True, 'reason': 'done'})
    monkeypatch.setattr(loop, '_cria_measured_facts', lambda sess: 'actual 雪\nexit=0')
    with assistruntime.bound(root):
        result = loop.judge_satisfaction('Original TASK', 'actual evidence', object(), None, _Rlog(), workspace_root='/w')
    assert result[0] and events == ['ParticipationInput', 'ExactFormInput', 'confirmation']


@pytest.mark.parametrize('level,consent,expected', [(4, True, False), (5, False, False),
    (5, 1, False), (5, 'true', False), (5, True, True)])
def test_actual_step_caller_requires_rung_and_explicit_planner_consent(monkeypatch, level, consent, expected):
    calls = []
    def execute(source, services):
        calls.append(source)
        return policy.Result(policy.Status.CONFIRMED, True, True, authority=source.authority)
    d = replace(policy.DEFINITION, execute=execute)
    # Private caller isolation: STEP is selected in the context; the outer runtime below
    # independently tests F34's original rung/strict-consent matrix. Public drive never mixes them.
    from cria import stepreview
    ctx = loop.LoopContext(None, None, None, runs_dir='', planner_enabled=consent)
    actual = ctx.pilot_runtime
    selected_ids = {item.policy.id for item in actual.ordered_stages}
    missing = tuple(item for item in actual.registrations
        if item.policy.id == stepreview.DEFINITION.policy.id and item.policy.id not in selected_ids)
    ctx.pilot_runtime = replace(actual, experimental_planning=True,
        ordered_stages=actual.ordered_stages + missing)
    driver = loop.Loop(ctx)
    monkeypatch.setattr(driver, '_verdict', lambda *args, **kwargs: ({'done': True, 'reason': 'done'}, 'raw'))
    monkeypatch.setattr(loop, '_confirm_applies', lambda *args, **kwargs: True)
    monkeypatch.setattr(loop.groundtruth, 'absent_step_literals', lambda *args: [])
    monkeypatch.setattr(loop, '_dump_verify', lambda *args, **kwargs: None)
    with assistruntime.bound(runtime(d, level=level)):
        result = driver._verify('generated STEP', 'claim', '', 'evidence', _Rlog(),
            workspace_root='/w', original_task='retained TASK', participation_facts='literal facts')
    assert result.done and bool(calls) is expected
    if expected:
        source = calls[0]
        assert source.authority is policy.Authority.STEP and source.phase == 'critic-confirm'
        assert source.claim == 'generated STEP' and source.original_task == 'retained TASK'
        assert source.measured_facts == 'literal facts' and result.confirmation.observed
    else:
        assert result.confirmation is None


@pytest.mark.parametrize('empty', [False, True])
def test_not_selected_precedes_services_and_measured_fact_factory(monkeypatch, empty):
    def poison(*args, **kwargs): raise AssertionError('unselected F34 work')
    root = (assistruntime.AssistRuntime(None, (), None, 0, (), ()) if empty else
            runtime(disabled=(policy.DEFINITION.policy.id,)))
    monkeypatch.setattr(loop, '_confirmation_services', poison)
    with assistruntime.bound(root):
        result = loop._confirm_completion('claim', 'reason', '/w', object(), object(), _Rlog(),
            phase='anything', cria_facts=poison)
    assert result.status is policy.Status.NOT_SELECTED and not result.confirmed and not result.observed


@pytest.mark.parametrize('bad', [None, True, loop.Confirmation(True, False), policy.Result('confirmed'),
    policy.Result(policy.Status.CONFIRMED, True, True, authority=policy.Authority.STEP),
    policy.Result(policy.Status.REJECTED, True, True),
    policy.Result(policy.Status.CONFIRMED, True, False),
    policy.Result(policy.Status.UNCHECKED, True, True),
    policy.Result(policy.Status.CONFIRMED, 'true', True),
    policy.Result(policy.Status.CONFIRMED, True, True, reason=42)])
def test_bad_replacement_fails_closed_after_actual_selected_call(bad):
    calls = []
    def execute(source, services):
        calls.append((source, services))
        return bad
    with assistruntime.bound(runtime(replace(policy.DEFINITION, execute=execute))), pytest.raises(ValueError):
        loop._confirm_completion('claim', 'reason', '/w', object(), None, _Rlog(), phase='actual')
    assert len(calls) == 1 and isinstance(calls[0][0], policy.Input)
    assert calls[0][0].authority is policy.Authority.TASK and isinstance(calls[0][1], policy.Services)


@pytest.mark.parametrize('status', [policy.Status.REJECTED, policy.Status.UNVERIFIED, policy.Status.ABSENT])
def test_selected_negative_result_can_withhold_without_claiming_observation(status):
    def execute(source, services):
        return policy.Result(status, False, False, 'withheld', authority=source.authority)
    with assistruntime.bound(runtime(replace(policy.DEFINITION, execute=execute))):
        result = loop._confirm_completion('claim', 'reason', '/w', object(), None, _Rlog(), phase='actual')
    assert result.status is status and not result.confirmed and not result.observed


def test_f36_independent_absence_no_diagnosis_factories(monkeypatch):
    def poison(*args, **kwargs): raise AssertionError('disabled F36 services')
    monkeypatch.setattr(loop, '_composed_closed_ask', poison)
    monkeypatch.setattr(loop, '_workspace_subject', poison)
    role = Role(name='reasoner', backend='local', reasoning='on')
    monkeypatch.setattr(loop.wsview, 'current', lambda root: SimpleNamespace(surveyed=True, listdir=lambda root: ['a.py']))
    monkeypatch.setattr(loop, '_judge_completion', lambda *args, **kwargs: reply('{"consistent":false,"why":"contradiction"}'))
    root = runtime(disabled=(completiondiagnosis.DEFINITION.policy.id,))
    with assistruntime.bound(root):
        result = loop._confirm_completion('claim', 'reason', '/w', object(), role, _Rlog(), phase='actual')
    assert result.status is policy.Status.REJECTED and not result.confirmed and result.reason == ''
    assert role.reasoning == 'on'


def test_f36_exact_execute_receives_request_and_raw_log(monkeypatch):
    calls = []
    log = _Rlog()
    def execute(source, services):
        calls.append((source, services))
        assert source.candidate() == {'consistent': False, 'why': 'contradiction'}
        assert services.log is log
        return completiondiagnosis.DiagnosisResult(completiondiagnosis.DiagnosisStatus.GROUNDED, 'selected evidence')
    root = runtime()
    diagnosis = replace(root.completion_diagnosis, execute=execute)
    root = replace(root, ordered_stages=tuple(diagnosis if item is root.completion_diagnosis else item
        for item in root.ordered_stages))
    monkeypatch.setattr(loop.wsview, 'current', lambda root: SimpleNamespace(surveyed=True, listdir=lambda root: ['a.py']))
    monkeypatch.setattr(loop, '_judge_completion', lambda *args, **kwargs: reply('{"consistent":false,"why":"contradiction"}'))
    with assistruntime.bound(root):
        result = loop._confirm_completion('STEP claim', 'reason', '/w', object(), None, log,
            phase='critic-confirm', original_task='retained TASK', cria_facts='checks 雪\n')
    assert result.reason == 'selected evidence' and not result.confirmed
    source = calls[0][0]
    assert (source.task, source.original_task, source.checks, source.phase) == (
        'STEP claim', 'retained TASK', 'checks 雪\n', 'critic-confirm-diagnosis')


def test_original_role_copy_transport_options_pending_ids_and_latest_rounds(monkeypatch):
    role = Role(name='reasoner', backend='local', reasoning='on')
    seen = []
    comp = reply()
    comp['choices'][0]['message']['tool_calls'] = [{'function': {'name': 'read_file'}}]
    def inspect(*args, **kwargs):
        seen.append((args, kwargs))
        return comp
    monkeypatch.setattr(loop, '_judge_completion', inspect)
    svc = loop._confirmation_services(object(), role, _Rlog(), None)
    request = policy.InspectionRequest('system', 'Unicode 雪\n', '/w', 'actual-phase')
    first = svc.inspect(request)
    comp[loop.ROUNDS_KEY] = 0
    second = svc.inspect(request)
    assert first.rounds == 1 and second.rounds == 0 and first.pending_ids == second.pending_ids == ('',)
    assert role.reasoning == 'on' and seen[0][0][1].reasoning == 'off'
    assert seen[0][0][1] is not seen[1][0][1]
    assert seen[0][0][2:4] == ('system', 'Unicode 雪\n')
    assert seen[0][1] == dict(phase='actual-phase', force_think_off=True, workspace_root='/w',
                            answer_now_simple=loop.verifytools.ANSWER_NOW_CONSISTENT)


def test_registration_contract_cannot_be_forged_or_duplicated():
    for definition in [replace(policy.DEFINITION, execute=None),
        replace(policy.DEFINITION, policy=replace(policy.DEFINITION.policy, stage='other')),
        replace(policy.DEFINITION, policy=replace(policy.DEFINITION.policy, id='forged')),
        replace(policy.DEFINITION, policy=replace(policy.DEFINITION.policy, migrated=True))]:
        with pytest.raises(ValueError): runtime(definition)
    with pytest.raises(ValueError):
        runtime(SimpleNamespace(policy=policy.DEFINITION.policy, execute=lambda *args: None))
    with pytest.raises(ValueError):
        assistruntime.AssistRuntime.select(registrations=(policy.DEFINITION, policy.DEFINITION))
    with pytest.raises(ValueError): runtime(disabled=('unknown-policy',))
    assert not policy.DEFINITION.policy.migrated and policy.DEFINITION.policy.default_level == 4
    root = runtime()
    assert root.task_review.policy.migrated is True
    assert root.completion_confirmation is policy.DEFINITION


def test_not_selected_actual_task_does_not_block_or_claim_confirmation(monkeypatch):
    def poison(*args, **kwargs): raise AssertionError('disabled confirmation work')
    monkeypatch.setattr(loop, '_satisfaction_verdict', lambda *args, **kwargs: {'satisfied': True, 'reason': 'done'})
    monkeypatch.setattr(loop, '_cria_measured_facts', poison)
    monkeypatch.setattr(loop, '_confirmation_services', poison)
    disabled = (policy.DEFINITION.policy.id,) + tuple(d.policy.id for d in completionapproval.PRE_RELEASE)
    log = _Rlog()
    with assistruntime.bound(runtime(disabled=disabled)):
        result = loop.judge_satisfaction('original TASK', 'actual evidence', object(), None, log, workspace_root='/w')
    assert result[0] and not any(name == 'loop.satisfaction_confirm' for name, fields in log.events)


def test_canonical_source_events_keep_separate_f34_and_f36_attribution(monkeypatch):
    responses = iter([reply(rounds=0), reply('{"consistent":false,"diagnosis_kind":"failed_check",'
        '"task_quote":"invented quote","evidence_source":"checks","why":"contradiction"}')])
    monkeypatch.setattr(loop.wsview, 'current', lambda root: SimpleNamespace(surveyed=True, listdir=lambda root: ['a.py']))
    monkeypatch.setattr(loop, '_judge_completion', lambda *args, **kwargs: next(responses))
    log = _Rlog()
    with assistruntime.bound(runtime()):
        result = loop._confirm_completion('original TASK', 'reason', '/w', object(), None, log,
            phase='satisfaction-confirm', cria_facts='actual checks')
    assert not result.confirmed and result.reason == ''
    f34 = [fields for name, fields in log.events if name == 'loop.confirm_without_looking']
    f36 = [fields for name, fields in log.events if name == 'loop.negative_diagnosis_suppressed']
    assert len(f34) == len(f36) == 1
    assert (f34[0]['assist_id'], f34[0]['family_id']) == (policy.DEFINITION.policy.id, 'F34')
    assert (f36[0]['assist_id'], f36[0]['family_id']) == (completiondiagnosis.DEFINITION.policy.id, 'F36')
    assert f36[0]['phase'] == 'satisfaction-confirm-diagnosis'


def test_confirmation_facts_are_current_not_cached_across_invocations(monkeypatch):
    names = ['a.py']
    monkeypatch.setattr(loop.wsview, 'current', lambda root: SimpleNamespace(surveyed=True, listdir=lambda root: list(names)))
    monkeypatch.setattr(loop, '_judge_completion', lambda *args, **kwargs: reply())
    with assistruntime.bound(runtime()):
        first = loop._confirm_completion('Write report.md', 'reason', '/w', object(), None, _Rlog(), phase='actual')
        names.clear()
        second = loop._confirm_completion('Write report.md', 'reason', '/w', object(), None, _Rlog(), phase='actual')
    assert first.confirmed and first.observed
    assert second.status is policy.Status.ABSENT and not second.confirmed


def test_diagnosis_uses_captured_definition_and_correct_off_role_phase(monkeypatch):
    role = Role(name='reasoner', backend='local', reasoning='on')
    log = _Rlog()
    seen = []
    ask = object()
    def factory(chat, copied_role, raw_log, *, phase):
        seen.append((chat, copied_role, raw_log, phase))
        return ask
    monkeypatch.setattr(loop, '_composed_closed_ask', factory)
    def execute(source, services):
        assert services.ask is ask and services.log is log
        return completiondiagnosis.DiagnosisResult(completiondiagnosis.DiagnosisStatus.GROUNDED, 'captured diagnosis')
    captured = replace(completiondiagnosis.DEFINITION, execute=execute)
    svc = loop._confirmation_services('chat', role, log, captured)
    request = policy.DiagnosisInput({'consistent': False}, 'claim', 'root', 'checks', '/w', 'critic-confirm-diagnosis')
    with assistruntime.bound(runtime(disabled=(completiondiagnosis.DEFINITION.policy.id,))):
        assert svc.diagnose(request) == 'captured diagnosis'
    assert len(seen) == 1 and seen[0][0] == 'chat' and seen[0][2] is log
    assert seen[0][1] is not role and seen[0][1].reasoning == 'off'
    assert seen[0][3] == request.phase and role.reasoning == 'on'


def test_required_empty_workspace_fact_adapter_remains_available_when_optional_off(monkeypatch):
    monkeypatch.setattr(loop.wsview, 'current', lambda root: SimpleNamespace(surveyed=True, listdir=lambda root: []))
    with assistruntime.bound(runtime(disabled=(policy.DEFINITION.policy.id,))):
        assert loop.step_names_absent_artifact('Write report.md', '/w') == 'report.md'
    assert loop._restates_the_verdict is policy.restates_claim
