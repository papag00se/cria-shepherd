"""Selected pre-release approval executes only at the whole-task careful-positive boundary."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from cria import assistruntime, completionapproval as policy, completionconfirmation, filefacts, loop, participation, prompts
from test_loop import _Rlog
from tests.test_a_required_test_unknown_cannot_complete import _capture_view, _candidate
from cria import probediscovery
from tests.test_completion_approval_policies import action


def runtime(*, participation=None, exact=None, disabled=(), level=5):
    replacements = {d.policy.id: d for d in (participation, exact) if d is not None}
    ids = {d.policy.id for d in policy.PRE_RELEASE}
    registry = tuple(d for d in assistruntime.DEFINITIONS if d.policy.id not in ids) + tuple(
        replacements.get(d.policy.id, d) for d in policy.PRE_RELEASE)
    return assistruntime.AssistRuntime.select(level=level, disabled=disabled, registrations=registry)


def broad_verdict(monkeypatch, events, *, satisfied=True):
    def verdict(*args, **kwargs):
        events.append('careful' if not kwargs.get('reasoning_off') else 'retry')
        return {'satisfied': satisfied, 'reason': 'actual broad verdict'}
    monkeypatch.setattr(loop, '_satisfaction_verdict', verdict)
    monkeypatch.setattr(loop, '_verdict_nudge', lambda *args, **kwargs: SimpleNamespace(action=''))


@pytest.mark.parametrize('level', range(6))
def test_canonical_pair_is_registered_once_with_original_level_and_source_identity(level):
    selected = assistruntime.AssistRuntime.select(level=level)
    for definition in policy.PRE_RELEASE:
        assert sum(d is definition for d in assistruntime.DEFINITIONS) == 1
        assert definition.policy.default_level == 4 and definition.policy.migrated is False
    assert selected.pre_release == (policy.PRE_RELEASE if level >= 4 else ())


@pytest.mark.parametrize('block_at', [None, 'participation', 'exact'])
def test_actual_task_positive_routes_exact_replacements_in_order_before_confirmation(monkeypatch, block_at):
    events = []
    broad_verdict(monkeypatch, events)
    def participation(source):
        events.append('participation')
        assert source.task == 'Whole original task'
        return policy.ApprovalResult(policy.ApprovalStatus.WITHHELD if block_at == 'participation'
                                     else policy.ApprovalStatus.PERMITTED)
    def exact(source):
        events.append('exact')
        assert source.evidence() == 'Original action evidence'
        return policy.ApprovalResult(policy.ApprovalStatus.CONTRADICTED if block_at == 'exact'
                                     else policy.ApprovalStatus.NO_CONSTRAINT, 'exact measured block')
    def confirmation(*args, **kwargs):
        events.append('confirmation')
        return completionconfirmation.Result(completionconfirmation.Status.CONFIRMED,
            confirmed=True,observed=True,reason='',authority=completionconfirmation.Authority.TASK)
    monkeypatch.setattr(loop, '_confirm_completion', confirmation)
    selected = runtime(participation=replace(policy.PARTICIPATION, execute=participation),
                       exact=replace(policy.EXACT_FORM, execute=exact))
    with assistruntime.bound(selected):
        result = loop.judge_satisfaction('Whole original task', 'Original action evidence',
            lambda *args: '', None, _Rlog(), workspace_root='/fixture')
    assert result[0] is (block_at is None)
    assert events == (['careful', 'participation'] if block_at == 'participation' else
                      ['careful', 'participation', 'exact'] if block_at == 'exact' else
                      ['careful', 'participation', 'exact', 'confirmation'])
    if block_at == 'exact':
        assert result[1] == 'exact measured block'


def test_absent_pair_does_not_run_optional_detection_or_measurement(monkeypatch):
    events = []
    broad_verdict(monkeypatch, events)
    def poison(*args, **kwargs):
        raise AssertionError('disabled approval work')
    selected = runtime(participation=replace(policy.PARTICIPATION, execute=poison),
                       exact=replace(policy.EXACT_FORM, execute=poison, measure=poison),
                       disabled=tuple(d.policy.id for d in policy.PRE_RELEASE))
    monkeypatch.setattr(loop, 'ask_closed', poison)
    monkeypatch.setattr(loop, '_work_log', lambda *args, **kwargs: 'required action facts')
    monkeypatch.setattr(loop, '_dedup_evidence', lambda text, **kwargs: text)
    with assistruntime.bound(selected):
        assert loop.judge_satisfaction('task', 'evidence', poison, None, _Rlog())[0] is True
        assert loop._satisfaction_evidence([], workspace_root='/fixture') == 'required action facts'
    assert events == ['careful']


def test_satisfaction_evidence_uses_exact_selected_measurement_without_approval_execution(monkeypatch):
    calls = []
    messages = [{'role': 'user', 'content': 'original'}]
    def measure(received, services):
        calls.append((received, services))
        return [filefacts.FileFact('selected.txt', b'exact bytes\n', True)]
    def poison(*args, **kwargs):
        raise AssertionError('approval cannot run while gathering evidence')
    selected = runtime(exact=replace(policy.EXACT_FORM, execute=poison, measure=measure))
    monkeypatch.setattr(loop, '_work_log', lambda *args, **kwargs: 'required action facts')
    monkeypatch.setattr(loop, '_dedup_evidence', lambda text, **kwargs: kwargs['_consume'](text))
    with assistruntime.bound(selected):
        text = loop._satisfaction_evidence(messages)
    assert len(calls) == 1 and calls[0][0] is messages
    assert 'selected.txt' in text and 'required action facts' in text
    assert filefacts.parse(text) == [('selected.txt', len(b'exact bytes\n'), True)]


def test_careful_negative_does_not_invoke_selected_approval(monkeypatch):
    events = []
    broad_verdict(monkeypatch, events, satisfied=False)
    def poison(*args, **kwargs):
        raise AssertionError('approval on negative verdict')
    selected = runtime(participation=replace(policy.PARTICIPATION, execute=poison),
                       exact=replace(policy.EXACT_FORM, execute=poison))
    with assistruntime.bound(selected):
        assert loop.judge_satisfaction('task', 'evidence', poison, None, _Rlog())[0] is False
    assert events == ['careful']


@pytest.mark.parametrize('status', list(policy.ApprovalStatus))
def test_typed_status_not_text_controls_whole_task_release(monkeypatch, status):
    events = []
    broad_verdict(monkeypatch, events)
    selected = runtime(exact=replace(policy.EXACT_FORM, execute=lambda source:
                       policy.ApprovalResult(status, 'literal selected result')),
                       disabled=(policy.PARTICIPATION.policy.id,))
    with assistruntime.bound(selected):
        result = loop.judge_satisfaction('task', 'facts', lambda *args: '', None, _Rlog())
    assert result[0] is (status in (policy.ApprovalStatus.NO_CONSTRAINT, policy.ApprovalStatus.PERMITTED))
    if status in (policy.ApprovalStatus.WITHHELD, policy.ApprovalStatus.CONTRADICTED):
        assert result[1] == 'literal selected result'


@pytest.mark.parametrize('invalid', [None, True, policy.ApprovalResult('permitted')])
def test_invalid_replacement_result_cannot_release_task(monkeypatch, invalid):
    events = []
    broad_verdict(monkeypatch, events)
    selected = runtime(exact=replace(policy.EXACT_FORM, execute=lambda source: invalid),
                       disabled=(policy.PARTICIPATION.policy.id,))
    with assistruntime.bound(selected), pytest.raises(ValueError, match='must return ApprovalResult'):
        loop.judge_satisfaction('task', 'facts', lambda *args: '', None, _Rlog())


@pytest.mark.parametrize('invalid', [replace(policy.EXACT_FORM, measure=None),
    SimpleNamespace(policy=policy.EXACT_FORM.policy, execute=lambda source: None)])
def test_wrong_typed_or_noncallable_measure_binding_is_rejected(invalid):
    with pytest.raises(ValueError, match='Invalid completion approval binding'):
        runtime(exact=invalid)


@pytest.mark.parametrize('canonical', policy.PRE_RELEASE)
def test_canonical_source_contract_cannot_be_bypassed_by_relabeling_its_stage(canonical):
    invalid = replace(canonical, policy=replace(canonical.policy, stage='other-stage'))
    changes = {'participation': invalid} if canonical is policy.PARTICIPATION else {'exact': invalid}
    with pytest.raises(ValueError, match='Invalid completion approval binding'):
        runtime(**changes)


def test_bound_literal_empty_runtime_never_resurrects_standalone_defaults(monkeypatch):
    events = []
    broad_verdict(monkeypatch, events)
    selected = assistruntime.AssistRuntime(None, (), None, 0, (), ())
    def poison(*args, **kwargs):
        raise AssertionError('unselected question or workspace access')
    monkeypatch.setattr(loop, 'ask_closed', poison)
    monkeypatch.setattr(loop.wsview, 'current', poison)
    monkeypatch.setattr(loop, '_work_log', lambda *args, **kwargs: 'shared facts')
    monkeypatch.setattr(loop, '_dedup_evidence', lambda text, **kwargs: text)
    with assistruntime.bound(selected):
        assert selected.pre_release == ()
        assert loop._satisfaction_evidence([], workspace_root='/fixture') == 'shared facts'
        assert loop.judge_satisfaction('task', 'facts', poison, None, _Rlog())[0] is True


def test_unreadable_careful_pass_then_positive_retry_cannot_run_approvals(monkeypatch):
    calls = []
    def verdict(*args, **kwargs):
        calls.append(kwargs['reasoning_off'])
        return {'satisfied': True, 'reason': 'retry only'} if kwargs['reasoning_off'] else None
    monkeypatch.setattr(loop, '_satisfaction_verdict', verdict)
    def poison(*args, **kwargs):
        raise AssertionError('retry cannot approve')
    selected = runtime(participation=replace(policy.PARTICIPATION, execute=poison),
                       exact=replace(policy.EXACT_FORM, execute=poison))
    with assistruntime.bound(selected):
        result = loop.judge_satisfaction('task', 'facts', poison, None, _Rlog())
    assert result[0] is False and calls == [False, True]


def test_real_exact_source_keeps_closed_retry_role_cleanup_reader_and_phase_contract(monkeypatch):
    events, requests, cleaned, parsed = [], [], [], []
    broad_verdict(monkeypatch, events)
    reader = loop.extract_json_object
    def closed(chat, role, prompt, log, **kwargs):
        requests.append((chat, role, prompt, log, kwargs))
        return 'wrapped unreadable'
    monkeypatch.setattr(loop, 'ask_closed', closed)
    def clean(raw):
        cleaned.append(raw)
        return raw.removeprefix('wrapped ')
    def object_reader(raw):
        parsed.append(raw)
        return reader(raw)
    monkeypatch.setattr(loop, 'extract_json_object', object_reader)
    role, log, chat = SimpleNamespace(clean_content=clean), _Rlog(), object()
    evidence = filefacts.render([filefacts.FileFact('out.txt', b'abc', False)])
    selected = runtime(disabled=(policy.PARTICIPATION.policy.id,))
    with assistruntime.bound(selected):
        result = loop.judge_satisfaction('task', evidence, chat, role, log)
    assert result[:2] == (False, prompts.load('unverified_step'))
    assert len(requests) == 2
    assert all(request[:2] == (chat, role) and request[3] is log for request in requests)
    assert [request[4] for request in requests] == [dict(phase='exact-form-requirement', retry_off=False)] * 2
    assert [request[2] for request in requests] == [prompts.render('exact_form_requirement', task='task', facts=evidence)] * 2
    assert cleaned == ['wrapped unreadable'] * 2 and parsed == ['unreadable'] * 2
    assert any(event == 'loop.exact_form_requirement' and fields['contradicted'] == 'unknown'
               for event, fields in log.events)


def test_real_participation_source_keeps_inspecting_transport_and_events(monkeypatch):
    events, inspections = [], []
    broad_verdict(monkeypatch, events)
    event = participation.observe(_candidate(probediscovery.ProbeKind.Test, 'npm test'), 'Tests: 1 passed', 0)
    event = replace(event, test_sources=(participation.TestSourceEvidence('test/cli.js', 'assert actual CLI'),))
    report = participation.report([event])
    session = SimpleNamespace(last_gate_participation=report, gate_fresh=True)
    log, role, chat = _Rlog(), SimpleNamespace(clean_content=lambda raw: raw), object()
    def closed(got_chat, got_role, prompt, got_log, **kwargs):
        assert (got_chat, got_role, got_log) == (chat, role, log)
        assert kwargs == dict(phase='test-e2e-requirement', retry_off=False)
        assert prompt == prompts.render('test_e2e_requirement', task='whole task')
        return 'E2E_REQUIRED'
    def inspect(*args, **kwargs):
        inspections.append((args, kwargs))
        return {'choices': [{'message': {'content': 'UNVERIFIED'}}]}
    monkeypatch.setattr(loop, 'ask_closed', closed)
    monkeypatch.setattr(loop, '_judge_completion', inspect)
    selected = runtime(disabled=(policy.EXACT_FORM.policy.id,))
    with assistruntime.bound(selected):
        result = loop.judge_satisfaction('whole task', '', chat, role, log, workspace_root='/workspace', sess=session)
    assert result[:2] == (False, prompts.load('required_test_unverified'))
    assert len(inspections) == 1
    args, kwargs = inspections[0]
    assert args == (chat, role, prompts.load('test_e2e_participation'),
                    prompts.render('test_e2e_participation', task='whole task',
                                   participation=participation.render_for_judge(report)), log)
    assert kwargs == dict(phase='test-e2e-participation', workspace_root='/workspace',
                          max_tokens=loop.JUDGE_MAX_TOKENS, force_think_off=True)
    assert ('loop.test_e2e_participation', {'verdict': 'UNVERIFIED'}) in log.events


def test_disabled_participation_preserves_foundation_facts_without_optional_lazy_access(monkeypatch):
    report = participation.report([participation.observe(
        _candidate(probediscovery.ProbeKind.SyntaxCheck, 'node --check a.js'), 'ok', 0)])
    expected = participation.render_for_judge(report, fresh=True)
    accesses, received, diagnosis = [], [], []
    class Session:
        gate_fresh = True
        @property
        def last_gate_participation(self):
            accesses.append('report')
            return report
    def verdict(*args, **kwargs):
        received.append(kwargs['evidence_blocks'])
        return {'satisfied': True, 'reason': 'shared gate evidence'}
    def nudge(*args, **kwargs):
        diagnosis.append(kwargs['participation_facts'])
        return SimpleNamespace(action='')
    def poison(*args, **kwargs):
        raise AssertionError('disabled source participation decision')
    monkeypatch.setattr(loop, '_satisfaction_verdict', verdict)
    monkeypatch.setattr(loop, '_verdict_nudge', nudge)
    monkeypatch.setattr(loop, 'ask_closed', poison)
    selected = runtime(participation=replace(policy.PARTICIPATION, execute=poison),
                       disabled=tuple(d.policy.id for d in policy.PRE_RELEASE))
    with assistruntime.bound(selected):
        assert loop.judge_satisfaction('task', 'original actions', poison, None, _Rlog(), sess=Session())[0]
    assert accesses == ['report']  # Existing broad funnel only; no optional source callback.
    assert '\n\n'.join(received[0]) == 'original actions\n\n' + expected
    assert diagnosis == [expected]


def test_selected_measurement_is_fresh_and_later_native_mutation_silences_current_bytes(monkeypatch):
    root = '/workspace'
    views = [_capture_view(root, {'out.txt': '雪\r\n'}, session='production-first')]
    monkeypatch.setattr(loop.wsview, 'current', lambda got_root: views[0] if got_root == root else None)
    monkeypatch.setattr(loop, '_work_log', lambda *args, **kwargs: 'shared actions')
    monkeypatch.setattr(loop, '_dedup_evidence', lambda text, **kwargs: kwargs['_consume'](text))
    messages = action('write_file', {'path': 'out.txt', 'content': 'historical'}, 'w')
    measured = []
    def measure(history, services):
        result = policy.EXACT_FORM.measure(history, services)
        measured.append(result)
        return result
    selected_exact = replace(policy.EXACT_FORM, measure=measure)
    selected = runtime(exact=selected_exact)
    with assistruntime.bound(selected):
        assert selected.pre_release[-1] is selected_exact
        first = loop._satisfaction_evidence(messages, workspace_root=root)
        assert filefacts.parse(first) == [('out.txt', 5, True)]
        assert measured[-1][0].raw == '雪\r\n'.encode()
        views[0] = _capture_view(root, {'out.txt': 'fresh'}, session='production-second')
        second = loop._satisfaction_evidence(messages, workspace_root=root)
        assert filefacts.parse(second) == [('out.txt', 5, False)]
        assert measured[-1][0].raw == b'fresh'
        views[0].note_a_mutator_ran()
        stale = loop._satisfaction_evidence(messages, workspace_root=root)
        assert measured[-1] == [filefacts.FileFact('out.txt', b'historical', False)]
        assert 'as last written' in stale
        messages += action('edit_file', {'path': 'out.txt', 'old_string': 'fresh', 'new_string': 'new'}, 'native')
        assert filefacts.extract(loop._satisfaction_evidence(messages, workspace_root=root)) == ''
        assert measured[-1] == []
    assert len(measured) == 4


@pytest.mark.parametrize('support,expected', [
    ('unknown', policy.ApprovalStatus.WITHHELD),
    ('absent', policy.ApprovalStatus.CONTRADICTED),
    ('failed', policy.ApprovalStatus.CONTRADICTED),
])
def test_actual_task_routing_preserves_unknown_vs_measured_nonparticipation(monkeypatch, support, expected):
    if support == 'unknown':
        report = participation.report([participation.observe(
            _candidate(probediscovery.ProbeKind.SyntaxCheck, 'node --check a.js'), 'ok', 0)])
    else:
        phase = (participation.PhaseParticipation(participated=False) if support == 'absent'
                 else participation.PhaseParticipation(passed=False))
        report = participation.ParticipationReport((participation.ProbeParticipation(None, ('test',), 0, True, test=phase),))
    events, statuses, accesses, requests = [], [], [], []
    broad_verdict(monkeypatch, events)
    class Session:
        gate_fresh = True
        @property
        def last_gate_participation(self):
            accesses.append('report')
            return report
    def execute(source):
        result = policy.PARTICIPATION.execute(source)
        statuses.append(result.status)
        return result
    def closed(*args, **kwargs):
        requests.append(kwargs)
        return 'REQUIRED'
    def poison(*args, **kwargs):
        raise AssertionError('no participation report recomputation')
    monkeypatch.setattr(loop, 'ask_closed', closed)
    monkeypatch.setattr(participation, 'report', poison)
    selected = runtime(participation=replace(policy.PARTICIPATION, execute=execute),
                       disabled=(policy.EXACT_FORM.policy.id,))
    with assistruntime.bound(selected):
        result = loop.judge_satisfaction('task', '', poison, None, _Rlog(), sess=Session())
    assert result[:2] == (False, prompts.load('required_test_unverified'))
    assert statuses == [expected] and accesses == ['report', 'report']
    assert requests == [dict(phase='test-participation-requirement', retry_off=False)]


def test_step_verification_positive_is_not_a_whole_task_approval(monkeypatch):
    def poison(*args, **kwargs):
        raise AssertionError('whole-task approval entered from STEP verification')
    selected = runtime(participation=replace(policy.PARTICIPATION, execute=poison),
                       exact=replace(policy.EXACT_FORM, execute=poison, measure=poison))
    from cria import stepreview
    from test_loop import _select_test_planning
    context = _select_test_planning(loop.LoopContext(
        planner=None, coder_chat=poison, reasoner_chat=poison, runs_dir=''), stepreview.DEFINITION)
    driver = loop.Loop(context)
    monkeypatch.setattr(driver, '_verdict', lambda *args, **kwargs: ({'done': True, 'reason': 'step only'}, '{}'))
    monkeypatch.setattr(loop, '_verdict_nudge', lambda *args, **kwargs: loop.VerdictNudge('step only'))
    with assistruntime.bound(selected):
        result = driver._verify('one STEP', 'step work', '', 'tool evidence', _Rlog(), original_task='whole TASK')
    assert result.done is True
