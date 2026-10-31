"""Actual Loop entry/selected initial-planning contracts; scripted replies only.

No live provider, executor, operator configuration or network is involved;
opt-in exists only in explicit synthetic test objects. Missing registration/API
failures are prerequisites, never behavioral before-witnesses.
"""
import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from cria import assistruntime, loop, planner
from cria.config import Config, LoggingConfig, PlannerConfig, Role, RoutingConfig


class Log:
    def __init__(self):
        self.events = []

    def emit(self, name, **fields):
        self.events.append((name, fields))


class PlanningProvider:
    """Reply to real planner wire requests, never replace its policy methods."""
    def __init__(self):
        self.calls = []

    def chat(self, body, log):
        self.calls.append(copy.deepcopy(body))
        names = {tool['function']['name'] for tool in body.get('tools', ())}
        system = body['messages'][0]['content']
        if 'submit_plan' in names:
            message = {'tool_calls': [{'id': 'submit', 'type': 'function', 'function': {
                'name': 'submit_plan', 'arguments': json.dumps({'steps': [
                    'Implement the requested report', 'Write meaningful report tests']})}}]}
        elif names:
            message = {'content': 'Ready to submit the plan.'}
        elif 'TEST_EXECUTION_PATH_READY' in system:
            message = {'content': 'TEST_EXECUTION_PATH_READY'}
        elif '"missing"' in system:
            message = {'content': '{"missing": []}'}
        elif '"lost"' in system:
            message = {'content': '{"lost": ""}'}
        else:
            message = {'content': 'NONE'}
        return json.dumps({'choices': [{'finish_reason': 'stop', 'message': message}]}).encode()


def make_driver(tmp_path, runtime, *, enabled=True, owner=None):
    provider = owner._provider if owner is not None else PlanningProvider()
    role = Role(name='reasoner', backend='local')
    owner = owner if owner is not None else planner.Planner(provider, role=role)
    offered = []

    def coder(body, log):
        offered.append(copy.deepcopy(body))
        return json.dumps({'choices': [{'finish_reason': 'tool_calls', 'message': {
            'role': 'assistant', 'tool_calls': [{'id': 'read-next', 'type': 'function',
                'function': {'name': 'read_file', 'arguments': '{"path":"report.txt"}'}}]}}]}).encode()

    # Explicit fake consent only; never inherit LoopContext's historical True.
    ctx = loop.LoopContext(owner, coder, None, reasoner_role=role, runs_dir='',
        workspace_root=str(tmp_path), planner_enabled=enabled, self_compact=False,
        focus_trim=False, pilot_runtime=runtime)
    store = loop.LoopStore()
    body = {'messages': [
        {'role': 'user', 'content': f'<environment_context><cwd>{tmp_path}</cwd></environment_context>'},
        {'role': 'user', 'content': 'Implement the report and its tests.'}],
        'tools': [{'type': 'function', 'function': {'name': 'shell', 'parameters': {
            'type': 'object', 'properties': {'command': {'type': 'string'}}}}},
            {'type': 'function', 'function': {'name': 'read_file', 'parameters': {
                'type': 'object', 'properties': {'path': {'type': 'string'}}}}}]}
    return loop.Loop(ctx, store), store, provider, offered, body


def test_actual_absent_initial_selection_cannot_fall_back_to_constructor_planning(tmp_path):
    # Reactive TASK review is a required Root foundation at L4/L5. Absence here
    # means no INITIAL planning definitions, not an invalid unguarded Root.
    runtime = assistruntime.AssistRuntime.select(level=5, registrations=(assistruntime.TASK_REVIEW,))
    driver, store, provider, offered, body = make_driver(tmp_path, runtime)
    before = copy.deepcopy(body)
    result = driver.drive(body, 'sid:empty-planning-root',
                          SimpleNamespace(task_type='coding', engagement='task'), Log())
    assert provider.calls == [], 'Empty selected root executed implicit constructor planning'
    assert body == before and result is not None
    session = store.get('sid:empty-planning-root')
    assert session is not None and session.synthetic and session.plan_off
    assert session.plan.task == 'Implement the report and its tests.'


def prime_retrying_owner():
    class Unanswered(PlanningProvider):
        def chat(self, body, log):
            self.calls.append(copy.deepcopy(body))
            if any(tool['function']['name'] == 'submit_plan' for tool in body.get('tools', ())):
                raise RuntimeError('scripted draft transport failure')
            return b'{"choices":[{"message":{"content":"Ready to submit the plan."}}]}'
    provider = Unanswered()
    owner = planner.Planner(provider, role=Role(name='reasoner', backend='local'))
    # Genuine prior Source call, not a manually fabricated Planner status.
    assert owner.plan_for([{'role': 'user', 'content': 'Prior unrelated task'}], Log(), session_key='sid:prior') is None
    assert owner._retriable_failure
    return owner, provider


def test_public_absent_gather_does_not_consume_a_previous_attempts_retry_status(tmp_path):
    owner, provider = prime_retrying_owner()
    prior_calls = copy.deepcopy(provider.calls)
    root = assistruntime.AssistRuntime.select(level=5, registrations=(assistruntime.TASK_REVIEW,))
    driver, store, _, _, body = make_driver(tmp_path, root, owner=owner)
    result = run(driver, body)
    assert provider.calls == prior_calls, 'Absent gather invoked a constructor-selected attempt'
    assert result is not None and store.get('sid:initial').synthetic
    assert store.get('sid:initial').plan_off and owner._retriable_failure


INITIAL_IDS = (
    'experimental-plan-gather', 'experimental-plan-coverage',
    'experimental-plan-readiness', 'experimental-plan-revision',
)


def selected_root(*, enabled, disabled=(), replacements=()):
    # Canonical Root registration is a prerequisite; never duplicate its catalog
    # or patch validation to manufacture a successful public before-witness.
    # These fixtures select INITIAL planning only. New lifecycle consumers must
    # not keep coverage required when this caller explicitly removes it.
    lifecycle_ids = ('experimental-living-plan', 'experimental-step-review',
                     'experimental-completed-work-briefing')
    disabled = (*disabled, *(definition.policy.id for definition in assistruntime.DEFINITIONS
                             if definition.policy.id in lifecycle_ids
                             and definition.policy.id not in disabled))
    root = assistruntime.AssistRuntime.select(level=5, experimental_planning=enabled, disabled=disabled)
    assert tuple(d.policy.id for d in planner.DEFINITIONS) == INITIAL_IDS
    assert all(any(registered is canonical for registered in root.registrations)
               for canonical in planner.DEFINITIONS)
    if replacements:
        by_id = {definition.policy.id: definition for definition in replacements}
        root = replace(root, ordered_stages=tuple(by_id.get(d.policy.id, d) for d in root.ordered_stages))
    return root


def run(driver, body, key='sid:initial'):
    return driver.drive(body, key, SimpleNamespace(task_type='coding', engagement='task'), Log())


def test_public_exact_four_stage_selection_is_task_bound_and_constructor_is_not_swapped(tmp_path):
    (tmp_path / 'package.json').write_text('{"scripts": {}}')
    seen = []
    constructor = planner.PlanningSelection()
    provider = PlanningProvider()
    owner = planner.Planner(provider, role=Role(name='reasoner', backend='local'), policies=constructor)
    def gather(instance, turns, log, prior, rewrite, outcome, session, *, policies):
        assert policies is root.initial_planning and instance is owner
        assert instance._policies is constructor
        seen.append(('gather', policies))
        return planner.GATHER.execute(instance, turns, log, prior, rewrite, outcome, session, policies=policies)
    def coverage(ask, task, steps):
        seen.append(('coverage', root.initial_planning))
        assert owner._policies is constructor
        return planner.COVERAGE.execute(ask, task, steps)
    def readiness(source):
        seen.append(('readiness', root.initial_planning))
        assert source.manifest() == '{"scripts": {}}'
        return planner.READINESS.execute(source)
    def revision(source):
        seen.append(('revision', root.initial_planning))
        assert source.coverage is coverage and owner._policies is constructor
        return planner.REVISION.execute(source)
    root = selected_root(enabled=True, replacements=(replace(planner.GATHER, execute=gather),
        replace(planner.COVERAGE, execute=coverage), replace(planner.READINESS, execute=readiness),
        replace(planner.REVISION, execute=revision)))
    driver, store, _, _, body = make_driver(tmp_path, root, owner=owner)
    assert run(driver, body) is not None
    assert [name for name, _ in seen] == ['gather', 'coverage', 'readiness', 'revision']
    assert all(selection is root.initial_planning for _, selection in seen)
    session = store.get('sid:initial')
    assert session.pilot_binding is root and session.pilot_binding.initial_planning is root.initial_planning
    assert [item.text for item in session.plan.items] == ['Implement the requested report', 'Write meaningful report tests']
    assert owner._policies is constructor and not constructor.enabled


def test_public_fork_gets_a_fresh_plan_without_changing_immutable_selection(tmp_path):
    root = selected_root(enabled=True)
    driver, store, provider, _, body = make_driver(tmp_path, root)
    assert run(driver, body, 'sid:parent') is not None
    parent = store.get('sid:parent')
    first_calls = len(provider.calls)
    assert run(driver, body, 'sid:fork') is not None
    fork = store.get('sid:fork')
    assert len(provider.calls) > first_calls
    assert fork.plan is not parent.plan and fork.plan.items is not parent.plan.items
    assert [item.text for item in fork.plan.items] == ['Implement the requested report', 'Write meaningful report tests']
    assert all(not item.done for item in fork.plan.items)
    assert parent.pilot_binding is fork.pilot_binding is root
    assert parent.pilot_binding.initial_planning is fork.pilot_binding.initial_planning is root.initial_planning


def test_public_active_task_rejects_selection_change_before_more_planning(tmp_path):
    root = selected_root(enabled=True)
    driver, store, provider, _, body = make_driver(tmp_path, root)
    assert run(driver, body) is not None
    session = store.get('sid:initial')
    constructor = driver._ctx.planner._policies
    calls = copy.deepcopy(provider.calls)
    driver._ctx.pilot_runtime = selected_root(enabled=True, disabled=(INITIAL_IDS[3],))
    with pytest.raises(ValueError, match='cannot change during an active task'):
        run(driver, body)
    assert provider.calls == calls and session.pilot_binding is root
    assert driver._ctx.planner._policies is constructor


@pytest.mark.parametrize('identity', INITIAL_IDS)
def test_public_each_exact_replacement_owns_its_stage(tmp_path, identity):
    (tmp_path / 'package.json').write_text('{"scripts": {}}')
    seen = []
    canonical = next(d for d in planner.DEFINITIONS if d.policy.id == identity)
    def gather(owner, turns, log, prior, rewrite, outcome, session, *, policies):
        seen.append(policies)
        return planner.Plan('selected-gather', 'Implement the report and its tests.', 'fixture', items=[
            planner.PlanItem('Selected gather report'), planner.PlanItem('Selected gather tests')])
    def coverage(ask, task, steps):
        seen.append((task, tuple(steps)))
        return []
    def readiness(source):
        seen.append((source.task, source.steps, source.manifest()))
        return planner.ReadinessResult('READY', True)
    def revision(source):
        seen.append((source.task, source.steps, source.coverage))
        return planner.RevisionResult(('Selected revision report', 'Selected revision tests'))
    execute = dict(zip(INITIAL_IDS, (gather, coverage, readiness, revision), strict=True))[identity]
    replacement = replace(canonical, execute=execute)
    root = selected_root(enabled=True, replacements=(replacement,))
    driver, store, provider, _, body = make_driver(tmp_path, root)
    assert run(driver, body) is not None and len(seen) == 1
    assert next(d for d in root.initial_planning.definitions if d.policy.id == identity) is replacement
    session = store.get('sid:initial')
    expected = (['Selected gather report', 'Selected gather tests'] if identity == INITIAL_IDS[0]
                else ['Selected revision report', 'Selected revision tests'] if identity == INITIAL_IDS[3]
                else ['Implement the requested report', 'Write meaningful report tests'])
    assert [item.text for item in session.plan.items] == expected
    systems = [call['messages'][0]['content'] for call in provider.calls]
    if identity == INITIAL_IDS[0]:
        assert seen == [root.initial_planning] and not provider.calls
    elif identity == INITIAL_IDS[1]:
        assert seen == [('Implement the report and its tests.', ('Implement the requested report', 'Write meaningful report tests'))]
        assert not any('"missing"' in system for system in systems)
    elif identity == INITIAL_IDS[2]:
        assert seen == [('Implement the report and its tests.', ('Implement the requested report', 'Write meaningful report tests'), '{"scripts": {}}')]
        assert not any('TEST_EXECUTION_PATH_READY' in system for system in systems)
    else:
        assert seen == [('Implement the report and its tests.', ('Implement the requested report', 'Write meaningful report tests'), planner.COVERAGE.execute)]
        assert not any('numbers of the steps to REMOVE' in system for system in systems)


@pytest.mark.parametrize('identity', INITIAL_IDS)
def test_public_each_stage_absence_respects_dependency_and_never_falls_back(tmp_path, identity, monkeypatch):
    from unittest.mock import Mock
    (tmp_path / 'package.json').write_text('{"scripts": {}}')
    # Revision genuinely requires coverage. Their joint removal is the valid
    # coverage-OFF case, not an invented independent unsafe configuration.
    disabled = (identity, INITIAL_IDS[3]) if identity == INITIAL_IDS[1] else (identity,)
    root = selected_root(enabled=True, disabled=disabled)
    probe = Mock(wraps=planner.package_manifest_without_test_script)
    monkeypatch.setattr(planner, 'package_manifest_without_test_script', probe)
    driver, store, provider, _, body = make_driver(tmp_path, root)
    assert run(driver, body) is not None
    assert not any(d.policy.id == identity for d in root.initial_planning.definitions)
    session = store.get('sid:initial')
    systems = [call['messages'][0]['content'] for call in provider.calls]
    if identity == INITIAL_IDS[0]:
        assert not provider.calls and not probe.called
        assert session.synthetic and session.plan_off
    else:
        assert [item.text for item in session.plan.items] == ['Implement the requested report', 'Write meaningful report tests']
    if identity == INITIAL_IDS[1]:
        assert not any('"missing"' in system or 'numbers of the steps to REMOVE' in system for system in systems)
    elif identity == INITIAL_IDS[2]:
        probe.assert_not_called()
        assert not any('TEST_EXECUTION_PATH_READY' in system for system in systems)
    elif identity == INITIAL_IDS[3]:
        assert not any('numbers of the steps to REMOVE' in system for system in systems)


@pytest.mark.parametrize('consent', [False, True])
def test_public_explicit_consent_is_separate_from_level_five(tmp_path, consent):
    root = selected_root(enabled=consent)
    cfg = Config(planner=PlannerConfig(enabled=consent))  # fake operator setting only
    driver, store, provider, _, body = make_driver(tmp_path, root, enabled=cfg.planner.enabled)
    assert run(driver, body) is not None
    assert bool(provider.calls) is consent
    assert bool(root.initial_planning.definitions) is consent
    assert store.get('sid:initial').plan_off is (not consent)


@pytest.mark.parametrize('verdict', ['UNDECIDABLE', 'NOT_APPLICABLE', 'MISSING'])
def test_public_typed_readiness_refusal_never_admits_a_plan(tmp_path, verdict):
    (tmp_path / 'package.json').write_text('{"scripts": {}}')
    seen = []
    def readiness(source):
        seen.append((source.task, source.steps, source.manifest()))
        return planner.ReadinessResult(verdict, True)
    root = selected_root(enabled=True, replacements=(replace(planner.READINESS, execute=readiness),))
    driver, store, _, _, body = make_driver(tmp_path, root)
    assert run(driver, body) is not None
    session = store.get('sid:initial')
    # MISSING gets the existing one-time draft handback in each gather;
    # unknown/not-applicable do not invent that corrective judgment.
    assert len(seen) == (4 if verdict == 'MISSING' else 2)
    assert all(item == ('Implement the report and its tests.',
        ('Implement the requested report', 'Write meaningful report tests'), '{"scripts": {}}') for item in seen)
    assert session.synthetic and session.plan_off and session.plan.status == 'in_progress'
    assert [item.text for item in session.plan.items] == ['Implement the report and its tests.']


@pytest.mark.parametrize('level', range(6))
@pytest.mark.parametrize('consent', [False, True])
def test_real_server_construction_only_projects_explicit_level_five_consent(tmp_path, monkeypatch, level, consent):
    from unittest.mock import Mock
    from cria.server import CriaServer, ThreadingHTTPServer
    # Replace only socket creation. The real constructor must select the real
    # canonical runtime; no planner/provider call or live config is involved.
    monkeypatch.setattr(ThreadingHTTPServer, '__init__', lambda *a, **k: None)
    cfg = Config(routing=RoutingConfig(engagement_level=level),
        planner=PlannerConfig(enabled=consent), logging=LoggingConfig(dir=str(tmp_path / 'server-log')))
    server = CriaServer(cfg, Mock(), Mock())
    expected = consent and cfg.routing.assists_enabled
    assert server.pilot_runtime.experimental_planning is expected
    assert bool(server.pilot_runtime.initial_planning.definitions) is expected
    assert cfg.planner.enabled is consent


def test_public_disabled_gather_ignores_prior_retry_even_when_other_stages_selected(tmp_path):
    owner, provider = prime_retrying_owner()
    calls = copy.deepcopy(provider.calls)
    root = selected_root(enabled=True, disabled=(INITIAL_IDS[0],))
    assert root.initial_planning.enabled and root.initial_planning.definitions
    driver, store, _, _, body = make_driver(tmp_path, root, owner=owner)
    result = run(driver, body)
    assert provider.calls == calls and result is not None
    assert store.get('sid:initial').synthetic and store.get('sid:initial').plan_off
    assert owner._retriable_failure  # bypass did not clear another attempt's state


def test_public_root_rejects_revision_without_coverage():
    with pytest.raises(ValueError):
        selected_root(enabled=True, disabled=(INITIAL_IDS[1],))


@pytest.mark.parametrize('enabled', [False, True])
def test_direct_reassess_coverage_uses_same_task_selection_not_canonical_fallback(enabled, monkeypatch):
    seen = []
    def coverage(ask, task, steps):
        seen.append((task, tuple(steps)))
        return ['guide']
    # This is an explicitly consented existing tail call. Only its shared
    # initial COVERAGE consumer is selected/absent; the tail is not migrated.
    root = selected_root(enabled=True,
        disabled=() if enabled else (INITIAL_IDS[1], INITIAL_IDS[3]),
        replacements=(replace(planner.COVERAGE, execute=coverage),) if enabled else ())
    calls = []
    def chat(body, log):
        calls.append(copy.deepcopy(body))
        text = '["Write report tests"]' if 'LIVING plan' in body['messages'][0]['content'] else 'NONE'
        return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': text}}]}).encode()
    missing, selections = [], []
    dispatch = planner.PlanningSelection.coverage
    def selected_coverage(self, ask, task, steps):
        selections.append(self)
        assert self is root.initial_planning
        return dispatch(self, ask, task, steps)
    monkeypatch.setattr(planner.PlanningSelection, 'coverage', selected_coverage)
    with assistruntime.bound(root):
        result = loop.reassess_remaining(chat, Role(name='reasoner', backend='local'),
            'Build report, tests, and guide', '- Build report', '- Write report tests',
            'EXACT TOOL EVIDENCE', Log(), uncovered=missing, policies=root.initial_planning)
    assert seen == ([('Build report, tests, and guide', ('Build report', 'Write report tests'))] if enabled else [])
    assert missing == (['guide'] if enabled else [])
    assert result == (None if enabled else ['Write report tests'])
    assert len(calls) == 2  # re-derivation + noise, never a fallback coverage question
    assert all(selection is root.initial_planning for selection in selections)
    if enabled:
        assert selections == [root.initial_planning]
