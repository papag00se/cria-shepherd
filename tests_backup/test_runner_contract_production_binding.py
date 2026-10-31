"""F47 selected production executor, lazy facts and existing transient state."""
from dataclasses import replace
from types import SimpleNamespace
import json

import pytest

from cria import assistruntime, loop, runnercontract as policy, probediscovery
from cria.config import Role
from cria.modulestate import ModuleResult, Judgment
from tests.test_runner_contract_policy import outcome, Log, BODY
from tests.test_executable_assist_pilots import rig


def runtime(definition=policy.DEFINITION, *, level=5, disabled=()):
    registrations = tuple(d for d in assistruntime.DEFINITIONS if d.policy.id != definition.policy.id) + (definition,)
    return assistruntime.AssistRuntime.select(level=level, registrations=registrations, disabled=disabled)


def invoke(state, *, root=None, chat=None, role=None, body=BODY, result=None):
    with assistruntime.bound(runtime() if root is None else root):
        return loop.runner_reset_steer(state, outcome() if result is None else result, body, Log(),
            reasoner_chat=chat, reasoner_role=role, workspace_root='/offline')


@pytest.mark.parametrize('level', range(6))
def test_canonical_registration_and_immutable_projection(level):
    root = assistruntime.AssistRuntime.select(level=level)
    assert sum(d is policy.DEFINITION for d in assistruntime.DEFINITIONS) == 1
    assert root.runner_contract is (policy.DEFINITION if level == 5 else None)
    with pytest.raises(AttributeError): root.runner_contract = None
    assert not policy.DEFINITION.policy.migrated
    assert assistruntime.TASK_REVIEW.policy.migrated


@pytest.mark.parametrize('synthetic', [False, True])
def test_exact_replacement_reaches_both_real_periodic_drivers(synthetic):
    received = []
    def execute(source, state):
        received.append((source, state))
        assert isinstance(source, policy.RunnerInput)
        assert source.outcome.report.results[0].exit_code == 1
        state.signature = 'selected-stamp'
        return policy.RunnerResult(policy.RunnerStatus.STEER, 'Exact selected runner guidance.')
    definition = replace(policy.DEFINITION, execute=execute)
    root = runtime(definition)
    assert root.runner_contract is definition
    driver, session, body, frames = rig(synthetic, root, periodic=True)
    result = driver.drive(body, 'sid:pilot', None, Log())
    assert result is not None and len(received) == 1
    assert session.runner_reset_signature == 'selected-stamp'
    assert received[0][1].signature == session.runner_reset_signature
    assert 'Exact selected runner guidance.' in json.dumps(frames, ensure_ascii=False)
    assert not session.periodic_probe and not session.awaiting_probe and not session.gate_fresh
    assert session.pilot_binding is root


@pytest.mark.parametrize('mode', ['disabled', 'empty', 'all-off', 'low-rung'])
def test_unselected_never_detects_gathers_or_observes_state(monkeypatch, mode):
    def poison(*args, **kwargs): raise AssertionError('unselected runner work')
    class NoReads:
        @property
        def runner_reset_signature(self): return poison()
    root = (assistruntime.AssistRuntime(None, (), None, 0, (), ()) if mode == 'empty' else
            runtime(level=0) if mode == 'low-rung' else
            runtime(level=0, disabled=tuple(d.policy.id for d in assistruntime.DEFINITIONS)) if mode == 'all-off' else
            runtime(disabled=(policy.DEFINITION.policy.id,)))
    monkeypatch.setattr(loop, '_runner_contract_input', poison)
    monkeypatch.setattr(policy, 'failed_declared_runner', poison)
    monkeypatch.setattr(loop, 'gate_error_text', poison)
    monkeypatch.setattr(loop, '_history_root', poison)
    monkeypatch.setattr(loop.wsview, 'current', poison)
    assert invoke(NoReads(), root=root, chat=object(), role=object()) is None


@pytest.mark.parametrize('status', [s for s in policy.RunnerStatus if s is not policy.RunnerStatus.STEER])
def test_every_silent_runner_result_preserves_module_authority(monkeypatch, status):
    events = []
    def execute(source, state):
        events.append('runner')
        return policy.RunnerResult(status)
    def module(source, state):
        events.append('module')
        assert source.outcome is result
        return ModuleResult(Judgment.STEER, 'Module authority retained.')
    root = runtime(replace(policy.DEFINITION, execute=execute))
    root = replace(root, periodic_judgments=(replace(assistruntime.MODULE, execute=module),))
    result = outcome()
    monkeypatch.setattr(loop, 'read_gate', lambda *a: result)
    gs = loop.GuardState(periodic_probe=True)
    with assistruntime.bound(root):
        steer = loop.guard_periodic_result(gs, BODY, Log())
    assert steer == 'Module authority retained.' and events == ['runner', 'module']


def test_facade_is_original_state_and_stamp_precedes_delivery(monkeypatch):
    gs = loop.GuardState()
    def execute(source, state):
        assert state.signature == ''
        gs.runner_reset_signature = 'external-change'
        assert state.signature == 'external-change'
        state.signature = 'before-return'
        assert gs.runner_reset_signature == 'before-return'
        return policy.RunnerResult(policy.RunnerStatus.STEER, 'not yet delivered')
    assert invoke(gs, root=runtime(replace(policy.DEFINITION, execute=execute))) == 'not yet delivered'
    assert gs.runner_reset_signature == 'before-return'


def test_canonical_signature_retains_same_object_but_not_real_store_reconstruction(tmp_path):
    def chat(body, log):
        return json.dumps({'choices': [{'message': {'content': 'ON_TRACK'}}]}).encode()
    role = Role(name='reasoner', backend='local')
    state = loop._plan_off_session(loop._synthetic_plan('task'), '')
    store = loop.LoopStore(str(tmp_path / 'state.json'))
    store.put('sid:original', state)
    invoke(state, chat=chat, role=role)
    signature = state.runner_reset_signature
    assert signature
    store.persist('sid:original')
    assert store.get('sid:original') is state
    assert store.get('sid:original').runner_reset_signature == signature
    encoded = json.loads((tmp_path / 'state.json').read_text())
    assert 'runner_reset_signature' not in encoded['sessions']['sid:original']
    assert 'runner_reset_signature' not in loop._session_to_dict(state)
    restored = loop.LoopStore(str(tmp_path / 'state.json')).get('sid:original')
    assert restored is not state and restored.runner_reset_signature == ''
    direct = loop._session_from_dict(loop._session_to_dict(state))
    assert direct.runner_reset_signature == ''
    fork_key = loop.session_key({'X-Cria-Session-Id': 'fork'}, BODY['messages'])
    fresh = loop._plan_off_session(loop._synthetic_plan('task'), '')
    store.put(fork_key, fresh)
    assert fresh.runner_reset_signature == '' and state.runner_reset_signature == signature
    store.drop('sid:original')
    replacement = loop._plan_off_session(loop._synthetic_plan('next task'), '')
    store.put('sid:original', replacement)
    assert store.get('sid:original') is replacement and replacement.runner_reset_signature == ''


@pytest.mark.parametrize('bad', [None, True, ('steer', 'invented')])
def test_bad_replacement_result_fails_after_actual_typed_call(bad):
    received = []
    def execute(source, state):
        received.append((source, state))
        return bad
    with pytest.raises(ValueError, match='RunnerResult'):
        invoke(loop.GuardState(), root=runtime(replace(policy.DEFINITION, execute=execute)))
    assert len(received) == 1 and isinstance(received[0][0], policy.RunnerInput)


def test_no_legacy_detector_or_policy_fallback(monkeypatch):
    def poison(*args, **kwargs): raise AssertionError('canonical executor resurrected')
    monkeypatch.setattr(policy, 'failed_declared_runner', poison)
    received = []
    def execute(source, state):
        received.append(source)
        return policy.RunnerResult(policy.RunnerStatus.STEER, 'replacement only')
    assert invoke(loop.GuardState(), root=runtime(replace(policy.DEFINITION, execute=execute))) == 'replacement only'
    assert len(received) == 1


@pytest.mark.parametrize('synthetic', [False, True])
def test_canonical_runner_reaches_both_drivers_with_real_parsed_js_failure(synthetic):
    driver, state, body, frames = rig(synthetic, runtime(), periodic=True)
    state.gate_plan.candidates = [replace(state.gate_plan.candidates[0],
        command=['npm', 'run', 'test'], ecosystem=probediscovery.Ecosystem.JsTs, declared_interface=True)]
    questions = []
    def chat(body, log):
        questions.append(body)
        return json.dumps({'choices': [{'message': {'content': 'RESET'}}]}).encode()
    driver._ctx.reasoner_chat = chat
    log = Log()
    assert driver.drive(body, 'sid:pilot', None, log) is not None
    assert len(questions) == 1 and questions[0]['max_tokens'] == loop.JUDGE_MAX_TOKENS
    assert 'npm run test' in state.runner_reset_signature
    assert not state.module_state.signature and not state.gate_fresh
    assert 'configured project test runner' in json.dumps(frames, ensure_ascii=False)
    events = [fields for name, fields in log.events if name == 'loop.runner_reset']
    assert len(events) == 1 and events[0]['assist_id'] == policy.DEFINITION.policy.id
    assert events[0]['family_id'] == 'F47' and events[0]['applied']


@pytest.mark.parametrize('node', [True, False, None])
def test_actual_input_services_keep_full_clean_evidence_raw_log_and_closed_options(monkeypatch, node):
    from tests.test_c35_judge_gate_plumbing_scrub import _capture_shaped_body
    body = _capture_shaped_body()
    literal = '雪 literal coder evidence\n' * 10000
    body['messages'].append({'role': 'assistant', 'content': literal})
    gs = loop.GuardState()
    result, log = outcome(), Log()
    role = Role(name='reasoner', backend='local', reasoning='on')
    chat = object()
    reads, closed, received = [], [], []
    monkeypatch.setattr(loop.wsview, 'current', lambda root: reads.append(root) or
        SimpleNamespace(isdir=lambda name: reads.append(name) or node))
    def ask(actual_chat, actual_role, question, actual_log, **options):
        closed.append((actual_chat, actual_role, question, actual_log, options))
        return 'ON_TRACK'
    monkeypatch.setattr(loop, 'ask_closed', ask)
    def execute(source, state):
        received.append(source)
        assert source.outcome is result and source.log is log
        assert source.checks() == loop.gate_error_text(result)
        assert source.node_modules() is node
        task, session = source.evidence()
        assert task == 'Implement the cart billing endpoint. No node_modules.'
        assert literal in session and 'decimal rounding helper' in session and 'missing go.sum entry' in session
        for hidden in ('___CRIA_GATE_TRANSPORT_', '/tmp/.cria-gate-', 'apply_patch', 'update_plan', 'Codex CLI', 'cria'):
            assert hidden not in session
        assert source.ask('exact question 雪\n', phase='runner-reset',
            max_tokens=loop.JUDGE_MAX_TOKENS, retry_off=False) == 'ON_TRACK'
        return policy.RunnerResult(policy.RunnerStatus.ON_TRACK)
    with assistruntime.bound(runtime(replace(policy.DEFINITION, execute=execute))):
        assert loop.runner_reset_steer(gs, result, body, log,
            reasoner_chat=chat, reasoner_role=role, workspace_root='/offline') is None
    assert len(received) == 1 and reads == ['/offline', 'node_modules']
    assert closed == [(chat, role, 'exact question 雪\n', log,
        dict(phase='runner-reset', max_tokens=loop.JUDGE_MAX_TOKENS, retry_off=False))]
    assert role.reasoning == 'on'


def test_evidence_adapter_preserves_current_cleaning_order_and_gate_plan(monkeypatch):
    trace = []
    gs = loop.GuardState(gate_plan=object())
    raw = BODY['messages']
    scrubbed, cleaned, dropped = [], [], []
    def history(messages):
        assert messages is raw
        trace.append('history')
        return 'pinned task', 'fingerprint'
    def scrub(messages):
        assert messages is raw
        trace.append('scrub')
        return scrubbed
    def clean(messages, plan):
        assert messages is scrubbed and plan is gs.gate_plan
        trace.append('gate')
        return cleaned
    def drop(messages):
        assert messages is cleaned
        trace.append('harness')
        return dropped
    def serialize(messages):
        assert messages is dropped
        trace.append('serialize')
        return 'whole session'
    monkeypatch.setattr(loop, '_history_root', history)
    monkeypatch.setattr(loop, '_reasoner_session', scrub)
    monkeypatch.setattr(loop.probegate, 'clean_gate_results', clean)
    monkeypatch.setattr(loop, '_drop_harness_frame', drop)
    monkeypatch.setattr(loop.selfcompact, 'serialize', serialize)
    def execute(source, state):
        assert source.evidence() == ('pinned task', 'whole session')
        return policy.RunnerResult(policy.RunnerStatus.ON_TRACK)
    invoke(gs, root=runtime(replace(policy.DEFINITION, execute=execute)))
    assert trace == ['history', 'scrub', 'gate', 'harness', 'serialize']


@pytest.mark.parametrize('answer', ['RESET', 'ON_TRACK'])
def test_canonical_cache_settles_before_log_and_repeats_before_context(monkeypatch, answer):
    state = loop.GuardState()
    checks, events, questions = [], [], []
    result = outcome()
    def error(actual):
        assert actual is result
        checks.append('checks')
        return 'complete checks 雪\n'
    monkeypatch.setattr(loop, 'gate_error_text', error)
    monkeypatch.setattr(loop.wsview, 'current', lambda root: SimpleNamespace(isdir=lambda name: None))
    def ask(*args, **kwargs):
        questions.append(kwargs)
        return answer
    monkeypatch.setattr(loop, 'ask_closed', ask)
    class StampedLog:
        def emit(self, name, **fields):
            assert state.runner_reset_signature == 'npm run test\ncomplete checks 雪\n'
            events.append((name, fields))
    with assistruntime.bound(runtime()):
        first = loop.runner_reset_steer(state, result, BODY, StampedLog(),
            reasoner_chat=object(), reasoner_role=object(), workspace_root='/offline')
        assert bool(first) is (answer == 'RESET')
        def forbidden(*args, **kwargs): raise AssertionError('repeat re-read context')
        monkeypatch.setattr(loop, '_periodic_judgment_evidence', forbidden)
        monkeypatch.setattr(loop.wsview, 'current', forbidden)
        again = loop.runner_reset_steer(state, result, BODY, StampedLog(),
            reasoner_chat=object(), reasoner_role=object(), workspace_root='/changed')
    assert again is None and len(events) == len(questions) == 1 and checks == ['checks', 'checks']
    assert questions == [dict(phase='runner-reset', max_tokens=loop.JUDGE_MAX_TOKENS, retry_off=False)]


def test_unknown_changed_checks_and_exceptions_do_not_settle_new_signature(monkeypatch):
    state = loop.GuardState(runner_reset_signature='old definitive signature')
    answers = iter(['?', '', RuntimeError('question unavailable'), 'ON_TRACK', 'RESET'])
    asked = []
    def ask(*args, **kwargs):
        asked.append(args)
        answer = next(answers)
        if isinstance(answer, Exception): raise answer
        return answer
    monkeypatch.setattr(loop, 'ask_closed', ask)
    monkeypatch.setattr(loop.wsview, 'current', lambda root: SimpleNamespace(isdir=lambda name: None))
    for _ in range(2):
        assert invoke(state, chat=object(), role=object()) is None
        assert state.runner_reset_signature == 'old definitive signature'
    with pytest.raises(RuntimeError, match='question unavailable'):
        invoke(state, chat=object(), role=object())
    assert state.runner_reset_signature == 'old definitive signature'
    assert invoke(state, chat=object(), role=object()) is None
    previous = state.runner_reset_signature
    changed = outcome()
    changed.report.selected[0].command = ['npm', 'run', 'unit']
    changed.report.results[0].command = 'npm run unit'
    assert invoke(state, chat=object(), role=object(), result=changed)
    assert len(asked) == 5 and state.runner_reset_signature != previous
    assert state.runner_reset_signature.startswith('npm run unit\n')


@pytest.mark.parametrize('definition', [
    replace(policy.DEFINITION, execute=None),
    replace(policy.DEFINITION, policy=replace(policy.DEFINITION.policy, stage='forged')),
    replace(policy.DEFINITION, policy=replace(policy.DEFINITION.policy, id='forged')),
    replace(policy.DEFINITION, policy=replace(policy.DEFINITION.policy, id='forged', stage='forged')),
    replace(policy.DEFINITION, policy=replace(policy.DEFINITION.policy, migrated=True)),
    SimpleNamespace(policy=policy.DEFINITION.policy, execute=lambda *a: None)])
def test_registration_rejects_forged_contract_type_or_callable(definition):
    with pytest.raises(ValueError): runtime(definition)


def test_duplicate_unknown_disable_and_fact_alias_keep_existing_contracts():
    with pytest.raises(ValueError):
        assistruntime.AssistRuntime.select(registrations=(policy.DEFINITION, policy.DEFINITION))
    with pytest.raises(ValueError): runtime(disabled=('unknown-assist',))
    assert loop._configured_js_test_failure is policy.failed_declared_runner
    assert not policy.DEFINITION.policy.dependencies


@pytest.mark.parametrize('level', range(5))
def test_all_lower_rungs_skip_input_factory_and_state(monkeypatch, level):
    def forbidden(*args, **kwargs): raise AssertionError('lower-rung runner work')
    monkeypatch.setattr(loop, '_runner_contract_input', forbidden)
    class NoState:
        @property
        def runner_reset_signature(self): return forbidden()
    assert invoke(NoState(), root=runtime(level=level)) is None


def test_changed_exact_checks_rejudge_without_resetting_previous_state(monkeypatch):
    state = loop.GuardState()
    checks, calls = ['first full checks'], []
    monkeypatch.setattr(loop, 'gate_error_text', lambda result: checks[0])
    monkeypatch.setattr(loop.wsview, 'current', lambda root: SimpleNamespace(isdir=lambda name: None))
    def ask(*args, **kwargs):
        calls.append(state.runner_reset_signature)
        return 'ON_TRACK'
    monkeypatch.setattr(loop, 'ask_closed', ask)
    invoke(state, chat=object(), role=object())
    checks[0] = 'changed full checks 雪\n'
    invoke(state, chat=object(), role=object())
    assert calls == ['', 'npm run test\nfirst full checks']
    assert state.runner_reset_signature == 'npm run test\nchanged full checks 雪\n'


@pytest.mark.parametrize('field', ['checks', 'workspace', 'evidence'])
def test_fact_adapter_exceptions_propagate_without_settling(monkeypatch, field):
    state = loop.GuardState(runner_reset_signature='retain old signature')
    seen = []
    def failed(*args, **kwargs):
        seen.append(field)
        raise RuntimeError('actual fact adapter failed')
    if field == 'workspace':
        monkeypatch.setattr(loop.wsview, 'current', failed)
    else:
        monkeypatch.setattr(loop, {'checks':'gate_error_text', 'evidence':'_periodic_judgment_evidence'}[field], failed)
    if field == 'evidence':
        monkeypatch.setattr(loop.wsview, 'current', lambda root: SimpleNamespace(isdir=lambda name: None))
    with pytest.raises(RuntimeError, match='actual fact adapter failed'):
        invoke(state, chat=object(), role=object())
    assert seen == [field] and state.runner_reset_signature == 'retain old signature'


def test_absent_root_is_unknown_without_workspace_lookup(monkeypatch):
    seen = []
    def forbidden(*args, **kwargs): raise AssertionError('rootless workspace read')
    monkeypatch.setattr(loop.wsview, 'current', forbidden)
    def execute(source, state):
        seen.append(source.node_modules())
        assert source.ask is None
        return policy.RunnerResult(policy.RunnerStatus.NOT_APPLICABLE)
    with assistruntime.bound(runtime(replace(policy.DEFINITION, execute=execute))):
        assert loop.runner_reset_steer(loop.GuardState(), outcome(), BODY, Log(),
            reasoner_chat=None, reasoner_role=None, workspace_root=None) is None
    assert seen == [None]


@pytest.mark.parametrize('synthetic', [False, True])
def test_disabled_runner_keeps_required_facts_and_module_in_both_drivers(monkeypatch, synthetic):
    received = []
    def execute(source, state):
        received.append(source)
        assert 'missing go.sum entry' in source.checks()
        state.signature = 'module-stamp'
        return ModuleResult(Judgment.STEER, 'Selected module still owns this failure.')
    root = runtime(disabled=(policy.DEFINITION.policy.id,))
    root = replace(root, periodic_judgments=(replace(assistruntime.MODULE, execute=execute),))
    def forbidden(*args, **kwargs): raise AssertionError('disabled runner built its input')
    monkeypatch.setattr(loop, '_runner_contract_input', forbidden)
    driver, state, body, frames = rig(synthetic, root, periodic=True)
    assert driver.drive(body, 'sid:pilot', None, Log()) is not None
    assert len(received) == 1 and state.module_state.signature == 'module-stamp'
    assert state.runner_reset_signature == '' and state.last_gate_red and not state.gate_fresh
    assert 'Selected module still owns this failure.' in json.dumps(frames)


def test_required_runner_fact_alias_is_available_with_optional_judgment_disabled():
    with assistruntime.bound(runtime(disabled=(policy.DEFINITION.policy.id,))):
        assert loop._configured_js_test_failure(outcome()) == 'npm run test'
        assert loop._configured_js_test_failure(outcome(exit_code=0)) == ''
