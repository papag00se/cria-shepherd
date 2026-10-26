"""Offline source-stage contracts, not evidence of shared driver integration."""
import ast
import json
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch

import pytest

from cria import planner, planner_tools, researchpolicies, wsview
from cria.config import Role
from cria.experimentalplanning import PlanningSelection, ReadinessInput, ReadinessResult, RevisionInput


class Log:
    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))


class Provider:
    def __init__(self, *, unreadable=False):
        self.bodies = []
        self.unreadable = unreadable

    def chat(self, body, log):
        self.bodies.append(body)
        names = {t['function']['name'] for t in body.get('tools', ())}
        if self.unreadable:
            message = {'content': 'not a plan'}
        elif 'submit_plan' in names:
            message = {'tool_calls': [{'id': 'plan', 'type': 'function', 'function': {
                'name': 'submit_plan', 'arguments': json.dumps({'steps': ['Write the requested report']})}}]}
        elif names:
            message = {'content': 'ready to draft'}
        else:
            message = {'content': 'NONE'}
        return json.dumps({'choices': [{'message': message}]}).encode()


def messages(root=''):
    return ([{'role': 'user', 'content': f'<cwd>{root}</cwd>'}] if root else []) + [
        {'role': 'user', 'content': 'Write the requested report'}]


def test_planning_sources_have_no_reverse_public_facade_dependency():
    # Structural DAG invariant: import success alone misses a lazy method edge.
    from cria import livingplan, stepreview
    for module in (planner, planner_tools, livingplan, stepreview):
        tree = ast.parse(Path(module.__file__).read_text())
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names]
        assert not any(name and name.split('.')[-1] == 'experimentalplanning' for name in imports), module.__name__


def test_planning_public_contracts_are_same_object_canonical_reexports():
    from cria import experimentalplanning as public, livingplan, planningcontracts, stepreview
    from cria.plan import Plan, PlanItem
    assert planner.PlanOutcome is planningcontracts.PlanOutcome
    assert planner_tools.ToolResult is planningcontracts.ToolResult
    assert planner.EventLog is public.EventLog is livingplan.EventLog is stepreview.EventLog is planningcontracts.EventLog
    assert planner.Plan is Plan and planner.PlanItem is PlanItem
    for name in ('PlanningAttempt', 'Ask', 'GatherCall', 'GatherDefinition', 'CoverageDefinition',
                 'ReadinessInput', 'ReadinessResult', 'ReadinessDefinition', 'RevisionInput',
                 'RevisionResult', 'RevisionDefinition', 'PlanningDefinition', 'PlanningSelection'):
        assert getattr(public, name) is getattr(planner, name), name
    assert livingplan.CoverageDefinition is planner.CoverageDefinition
    # A facade defining a lookalike would still be a second owner even if its
    # constructor happened to agree; canonical classes must live by DEFINITIONS.
    for name in ('PlanningAttempt', 'GatherDefinition', 'CoverageDefinition', 'ReadinessInput',
                 'ReadinessResult', 'ReadinessDefinition', 'RevisionInput', 'RevisionResult',
                 'RevisionDefinition', 'PlanningSelection'):
        assert getattr(public, name).__module__ == 'cria.planner', name


@pytest.mark.parametrize('level', range(6))
def test_relocated_selection_preserves_default_off_and_standalone_opt_in(level):
    from cria.config import Config, RoutingConfig
    cfg = Config(routing=RoutingConfig(engagement_level=level))
    assert not cfg.planner.enabled and not PlanningSelection().enabled
    provider = Provider()
    standalone = planner.Planner(provider)
    assert standalone._policies == PlanningSelection.opt_in()
    explicit_off = PlanningSelection()
    assert planner.Planner(provider, policies=explicit_off)._policies is explicit_off
    assert provider.bodies == []


def test_standalone_gather_adapter_keeps_legacy_keyword_surface():
    owner = planner.Planner(Provider())
    seen = []
    def gather(task, cwd, log, prior_work='', rewrite_summary='', outcome=None):
        seen.append((task, cwd, prior_work, rewrite_summary, outcome))
        owner._retriable_failure = True
        return None
    outcome = planner.PlanOutcome()
    with patch.object(owner, '_gather_and_plan', side_effect=gather):
        assert owner.plan_for(messages(), Log(), outcome=outcome) is None
    assert seen == [('Write the requested report', None, '', '', outcome)]
    assert owner._retriable_failure and not owner._admission_exhaustions


def test_task_projection_is_lazy_off_and_preserves_actual_selected_objects():
    class Unreadable:
        def __iter__(self):
            raise AssertionError('OFF inspected registrations')
    assert PlanningSelection.from_definitions(Unreadable()) == PlanningSelection()
    for enabled in (None, 0, 1, 'true'):
        with pytest.raises(ValueError):
            PlanningSelection.from_definitions(Unreadable(), enabled=enabled)
    replacement = replace(planner.COVERAGE, execute=lambda *args: ['exact replacement'])
    definitions = tuple(replacement if d is planner.COVERAGE else d for d in planner.DEFINITIONS)
    selected = PlanningSelection.from_definitions((researchpolicies.SEARCH,) + definitions, enabled=True)
    assert all(actual is expected for actual, expected in zip(selected.definitions, definitions, strict=True))
    assert selected.coverage(lambda *_: 'unread', 'task', ['step']) == ['exact replacement']
    def forbidden(*args): raise AssertionError('absent coverage called')
    assert PlanningSelection().coverage(forbidden, 'task', ['step']) == []
    with pytest.raises(ValueError):
        PlanningSelection.from_definitions((planner.REVISION,), enabled=True)
    with pytest.raises(ValueError):
        PlanningSelection.from_definitions(tuple(reversed(planner.DEFINITIONS)), enabled=True)


def test_per_call_selection_reaches_all_stages_without_mutating_constructor(tmp_path):
    (tmp_path / 'package.json').write_text('{"scripts": {}}')
    provider = Provider()
    constructor = PlanningSelection()
    owner = planner.Planner(provider, role=Role(name='reasoner', backend='local'), policies=constructor)
    calls = []
    def gather(instance, turns, log, prior, rewrite, outcome, session, *, policies):
        assert policies is selected and instance._policies is constructor
        calls.append('gather')
        return planner.Planner._plan_for(instance, turns, log, prior, rewrite, outcome, session, policies=policies)
    def coverage(ask, task, steps):
        assert owner._policies is constructor
        calls.append('coverage')
        return []
    def readiness(source):
        calls.append('readiness')
        assert source.manifest() == '{"scripts": {}}'
        return ReadinessResult('READY', True)
    def revision(source):
        calls.append('revision')
        assert source.coverage is coverage
        return planner.RevisionResult(('Write the selected final report',))
    selected = PlanningSelection.opt_in(replacements=(
        replace(planner.GATHER, execute=gather), replace(planner.COVERAGE, execute=coverage),
        replace(planner.READINESS, execute=readiness), replace(planner.REVISION, execute=revision)))
    result = owner.plan_for(messages(str(tmp_path)), Log(), session_key='explicit', policies=selected)
    assert result is not None
    assert [item.text for item in result.items] == ['Write the selected final report']
    assert calls == ['gather', 'coverage', 'readiness', 'revision']
    assert owner._policies is constructor and not constructor.enabled


def test_concurrent_task_selections_do_not_cross_or_replace_constructor():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)
    constructor = PlanningSelection()
    owner = planner.Planner(Provider(), role=Role(name='reasoner', backend='local'), policies=constructor)
    selections, observed = {}, []
    def selection(label):
        def gather(instance, turns, log, prior, rewrite, outcome, session, *, policies):
            assert policies is selections[label] and instance._policies is constructor
            barrier.wait(timeout=5)
            return planner.Planner._plan_for(instance, turns, log, prior, rewrite, outcome, session, policies=policies)
        def coverage(ask, task, steps):
            observed.append(('coverage', label))
            return []
        def revision(source):
            assert source.coverage is coverage and owner._policies is constructor
            observed.append(('revision', label))
            return planner.RevisionResult((label + ' report',))
        return PlanningSelection.opt_in(disabled=(planner.READINESS.policy.id,), replacements=(
            replace(planner.GATHER, execute=gather), replace(planner.COVERAGE, execute=coverage),
            replace(planner.REVISION, execute=revision)))
    selections.update((label, selection(label)) for label in ('left', 'right'))
    def run(label):
        return owner.plan_for(messages(), Log(), session_key=label, policies=selections[label])
    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = list(pool.map(run, ('left', 'right')))
    assert left is not None and right is not None
    assert [item.text for item in left.items] == ['left report']
    assert [item.text for item in right.items] == ['right report']
    assert sorted(observed) == [('coverage', 'left'), ('coverage', 'right'), ('revision', 'left'), ('revision', 'right')]
    assert owner._policies is constructor


def test_per_call_failure_cache_retains_session_frame_fork_and_reset_boundaries():
    provider = Provider(unreadable=True)
    owner = planner.Planner(provider, policies=PlanningSelection())
    selected = PlanningSelection.opt_in()
    assert owner.plan_for(messages(), Log(), session_key='parent', policies=selected) is None
    first = len(provider.bodies)
    assert owner.plan_for(messages(), Log(), session_key='parent', policies=selected) is None
    assert len(provider.bodies) == first
    assert owner.plan_for(messages(), Log(), session_key='fork', policies=selected) is None
    fork_count = len(provider.bodies)
    assert fork_count > first
    assert owner.plan_for(messages(), Log(), prior_work='Prior completed work',
                          session_key='parent', policies=selected) is None
    continuation_count = len(provider.bodies)
    assert continuation_count > fork_count
    assert owner.plan_for(messages(), Log(), rewrite_summary='Harness retained scope',
                          session_key='parent', policies=selected) is None
    rewrite_count = len(provider.bodies)
    assert rewrite_count > continuation_count
    changed = messages() + [{'role': 'user', 'content': 'Write a different required report'}]
    assert owner.plan_for(changed, Log(), session_key='parent', policies=selected) is None
    assert len(provider.bodies) > rewrite_count
    owner.reset('parent')
    count = len(provider.bodies)
    assert owner.plan_for(messages(), Log(), session_key='fork', policies=selected) is None
    assert len(provider.bodies) == count
    assert owner.plan_for(messages(), Log(), session_key='parent', policies=selected) is None
    assert len(provider.bodies) > count and owner._policies == PlanningSelection()


@pytest.mark.parametrize('bad', [False, (), {}, object()])
def test_per_call_invalid_binding_never_becomes_standalone_defaults(bad):
    provider = Provider()
    owner = planner.Planner(provider)
    before = dict(owner.__dict__)
    with patch.object(planner, 'latest_user_text', side_effect=AssertionError('invalid binding detected task')):
        with pytest.raises(ValueError):
            owner.plan_for(messages(), Log(), policies=bad)
    assert owner.__dict__ == before and not provider.bodies


def test_per_call_disabled_gather_keeps_outcome_and_failure_memory_untouched():
    provider = Provider()
    owner = planner.Planner(provider)
    outcome = planner.PlanOutcome(survey_pending=True)
    before = dict(owner.__dict__)
    with patch.object(planner, 'latest_user_text', side_effect=AssertionError('detected while off')):
        assert owner.plan_for(messages(), Log(), outcome=outcome, policies=PlanningSelection()) is None
    assert owner.__dict__ == before and not provider.bodies and outcome.survey_pending


def test_off_bindings_never_detect_call_or_change_failure_memory():
    provider, log = Provider(), Log()
    owner = planner.Planner(provider, policies=PlanningSelection())
    outcome = planner.PlanOutcome(survey_pending=True)
    before = dict(owner.__dict__)
    with patch.object(planner, 'latest_user_text', side_effect=AssertionError('detected while off')):
        assert owner.plan_for(messages(), log, outcome=outcome) is None
    assert provider.bodies == [] and log.events == []
    assert owner.__dict__ == before and outcome.survey_pending
    assert not PlanningSelection().bindings('experimental-plan-gather')


def test_opt_in_uses_registered_gather_replacement_not_old_body():
    seen = []
    replacement_plan = planner.Plan(id='replacement', task='Write the requested report',
        created='fixture', items=[planner.PlanItem(text='Write the replacement report')])
    def gather(owner, turns, log, prior, rewrite, outcome, session):
        seen.append((turns, prior, rewrite, outcome, session))
        return replacement_plan
    selected = PlanningSelection.opt_in(replacements=(replace(planner.GATHER, execute=gather),))
    provider = Provider()
    owner = planner.Planner(provider, policies=selected)
    outcome = planner.PlanOutcome()
    assert owner.plan_for(messages(), Log(), 'prior', 'rewrite', outcome, 's') is replacement_plan
    assert seen == [(messages(), 'prior', 'rewrite', outcome, 's')]
    assert provider.bodies == []


def test_selected_real_gather_builds_plan_and_disabled_stage_performs_no_work(tmp_path):
    (tmp_path / 'package.json').write_text('{"scripts": {}}')
    selected = PlanningSelection.opt_in(disabled=(planner.COVERAGE.policy.id,
        planner.READINESS.policy.id, planner.REVISION.policy.id))
    provider = Provider()
    owner = planner.Planner(provider, role=Role(name='reasoner', backend='local'), policies=selected)
    with patch.object(planner, 'package_manifest_without_test_script', side_effect=AssertionError('read while off')):
        result = owner.plan_for(messages(str(tmp_path)), Log(), session_key='s')
    assert [i.text for i in result.items] == ['Write the requested report']
    assert all(body.get('tools') for body in provider.bodies)


def test_real_draft_routes_coverage_readiness_and_revision_replacements(tmp_path):
    (tmp_path / 'package.json').write_text('{"scripts": {}}')
    seen = []
    def coverage(ask, task, steps):
        seen.append(('coverage', tuple(steps)))
        return []
    def readiness(source):
        seen.append(('readiness', source.manifest()))
        return ReadinessResult('READY', True)
    def revision(source):
        seen.append(('revision', source.steps))
        return planner.RevisionResult(('Write a revised report',))
    selected = PlanningSelection.opt_in(replacements=(
        replace(planner.COVERAGE, execute=coverage), replace(planner.READINESS, execute=readiness),
        replace(planner.REVISION, execute=revision)))
    owner = planner.Planner(Provider(), role=Role(name='reasoner', backend='local'), policies=selected)
    result = owner.plan_for(messages(str(tmp_path)), Log(), session_key='s')
    assert [i.text for i in result.items] == ['Write a revised report']
    assert [s[0] for s in seen] == ['coverage', 'readiness', 'revision']
    assert seen[1][1] == '{"scripts": {}}'


@pytest.mark.parametrize('answer, expected', [
    ('TEST_EXECUTION_PATH_READY', 'READY'), ('MISSING_TEST_EXECUTION_PATH', 'MISSING'),
    ('NOT_APPLICABLE', 'NOT_APPLICABLE'), ('', 'UNDECIDABLE'), ('possibly ready', 'UNDECIDABLE')])
def test_readiness_honors_only_typed_judgments(answer, expected):
    calls = []
    def ask(system, user):
        calls.append(user)
        return answer
    result = planner.READINESS.execute(ReadinessInput(ask, 'add tests', ('Write tests',), lambda: '{}'))
    assert result == ReadinessResult(expected, True)
    assert 'Write tests' in calls[0] and '{}' in calls[0]


def test_readiness_unknown_manifest_and_withheld_judge_are_not_false_claims():
    def forbidden(*args):
        raise AssertionError('unknown evidence cannot trigger judgment')
    assert planner.READINESS.execute(ReadinessInput(forbidden, 'task', (), lambda: None)) == ReadinessResult('NOT_APPLICABLE')
    assert planner.READINESS.execute(ReadinessInput(None, 'task', (), lambda: '{}')) == ReadinessResult('UNDECIDABLE', True)


def test_revision_preserves_deliverable_on_unknown_deletion_judgment():
    replies = iter(['1', 'unreadable'])
    result = planner.REVISION.execute(RevisionInput('write report', ('Write report', 'Run checks'), '',
        lambda *_: next(replies), Log()))
    assert result.steps == ('Write report', 'Run checks') and not result.dropped
    assert result.withheld and result.refused == ((0, 'unreadable verdict'),)


def test_revision_settles_coverage_refusal_and_accepted_deletion():
    def run(missing):
        replies = iter(['1', '{"lost": ""}'])
        return planner.REVISION.execute(RevisionInput('write report', ('Set up env', 'Write report'), '',
            lambda *_: next(replies), Log(), lambda *_: missing))
    refused = run(['report'])
    assert refused.steps == ('Set up env', 'Write report') and refused.withheld
    accepted = run([])
    assert accepted.steps == ('Write report',) and accepted.dropped == frozenset({0})


def test_revision_without_reasoner_keeps_plan_and_reports_withheld():
    result = planner.REVISION.execute(RevisionInput('task', ('Write report',), '', None, Log()))
    assert result.steps == ('Write report',) and result.withheld


def test_negative_failure_cache_is_scoped_resettable_and_fork_safe():
    provider = Provider(unreadable=True)
    owner = planner.Planner(provider, policies=PlanningSelection.opt_in())
    assert owner.plan_for(messages(), Log(), session_key='a') is None
    first = len(provider.bodies)
    assert owner.plan_for(messages(), Log(), session_key='a') is None
    assert len(provider.bodies) == first
    assert owner.plan_for(messages(), Log(), session_key='fork') is None
    assert len(provider.bodies) > first
    fork_count = len(provider.bodies)
    owner._retriable_failure = True
    owner._gather_facts = {'fork': ('HTTP 200', (), (), (), '')}
    owner.reset('a')
    assert owner._retriable_failure and 'fork' in owner._gather_facts
    owner.plan_for(messages(), Log(), session_key='fork')
    assert len(provider.bodies) == fork_count
    owner.plan_for(messages(), Log(), session_key='a')
    assert len(provider.bodies) > fork_count
    owner.reset()
    assert owner._plans == {} and owner._admission_exhaustions == {}
    assert owner._gather_facts == {} and not owner._retriable_failure


@pytest.mark.parametrize('per_call', [False, True])
def test_pending_workspace_read_is_deferred_not_negatively_cached(per_call):
    class Reader(Provider):
        def chat(self, body, log):
            self.bodies.append(body)
            return json.dumps({'choices': [{'message': {'tool_calls': [{'id': 'r', 'type': 'function',
                'function': {'name': 'read_file', 'arguments': '{"path":"report.txt"}'}}]}}]}).encode()
    provider, log = Reader(), Log()
    selected = PlanningSelection.opt_in()
    owner = planner.Planner(provider, policies=PlanningSelection() if per_call else selected)
    kwargs = {'policies': selected} if per_call else {}
    outcome = planner.PlanOutcome()
    view = wsview.View('/workspace', 'experimental-planning-pending')
    # Synthetic harness listing: path exists, but no body has been delivered.
    view._ingest_tree('F\t1\t10\treport.txt\n')
    token = wsview.bind(view)
    try:
        assert owner.plan_for(messages('/workspace'), log, outcome=outcome, session_key='s', **kwargs) is None
        assert outcome.survey_pending and owner._plans == {}
        owner.plan_for(messages('/workspace'), log, outcome=outcome, session_key='s', **kwargs)
        assert len(provider.bodies) == 2
    finally:
        wsview.unbind(token)


@pytest.mark.parametrize('verdict', ['UNDECIDABLE', 'NOT_APPLICABLE', 'MISSING'])
def test_readiness_refusal_never_admits_a_draft_and_exhaustion_is_bounded(tmp_path, verdict):
    (tmp_path / 'package.json').write_text('{}')
    provider, log = Provider(), Log()
    selected = PlanningSelection.opt_in(disabled=(planner.COVERAGE.policy.id, planner.REVISION.policy.id),
        replacements=(replace(planner.READINESS, execute=lambda source: ReadinessResult(verdict, True)),))
    owner = planner.Planner(provider, policies=selected)
    assert owner.plan_for(messages(str(tmp_path)), log, session_key='s') is None
    assert not owner._retriable_failure
    assert any(event == 'plan.admission_given_up' for event, _ in log.events)
    assert not any(event == 'plan.submitted' for event, _ in log.events)
    assert owner._plans == {} and owner._admission_exhaustions == {}


def test_concurrent_exchanges_do_not_share_failure_direction_or_research_facts():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)
    observed = {}
    def gather(owner, turns, log, prior, rewrite, outcome, session):
        owner._gather_facts = {session: ('HTTP 200', (), (), (), '')}
        owner._retriable_failure = session == 'a'
        owner._admission_exhausted_check = session
        barrier.wait(timeout=5)
        observed[session] = (dict(owner._gather_facts), owner._retriable_failure,
                             owner._admission_exhausted_check)
        return None
    owner = planner.Planner(Provider(), policies=PlanningSelection.opt_in(
        replacements=(replace(planner.GATHER, execute=gather),)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(owner.plan_for, messages(), Log(), session_key='a')
        b = pool.submit(owner.plan_for, messages(), Log(), session_key='b')
        assert a.result() is None and b.result() is None
    assert observed == {'a': ({'a': ('HTTP 200', (), (), (), '')}, True, 'a'),
                        'b': ({'b': ('HTTP 200', (), (), (), '')}, False, 'b')}


def test_shared_research_search_binding_is_used_replaced_and_disabled():
    calls = []
    def refuse(source, state):
        calls.append(source.query)
        return researchpolicies.Admission(researchpolicies.Effect.REFUSED, 'shared refusal')
    selected = replace(researchpolicies.ResearchSelection(),
                       search=replace(researchpolicies.SEARCH, execute=refuse))
    recent = []
    with researchpolicies.bound(selected):
        assert planner_tools.gate_search(recent, 'find API docs') == (
            'HTTP 400 Bad Request · web_search "find API docs"\nshared refusal')
    assert calls == ['find API docs'] and recent == []
    with researchpolicies.bound(researchpolicies.ResearchSelection.select(disabled=(researchpolicies.SEARCH.policy.id,))):
        assert planner_tools.gate_search(recent, 'find API docs') is None
    assert recent == [] and calls == ['find API docs']


@pytest.mark.parametrize('build', [
    lambda: PlanningSelection(False, planner.DEFINITIONS),
    lambda: PlanningSelection.opt_in(disabled=('unknown',)),
    lambda: PlanningSelection.opt_in(disabled=(planner.COVERAGE.policy.id,)),
    lambda: PlanningSelection(True, (planner.GATHER, planner.GATHER)),
    lambda: PlanningSelection(True, tuple(reversed(planner.DEFINITIONS))),
    lambda: PlanningSelection.opt_in(replacements=(replace(planner.GATHER,
        policy=replace(planner.GATHER.policy, scope='runtime')),)),
])
def test_invalid_consent_or_binding_contract_is_rejected(build):
    with pytest.raises(ValueError):
        build()


def test_definitions_are_explicit_experimental_and_support_is_not_registered():
    assert tuple(d.policy.stage for d in planner.DEFINITIONS) == (
        'experimental-plan-gather', 'experimental-plan-coverage', 'experimental-plan-readiness',
        'experimental-plan-revision')
    assert all(d.policy.scope == 'experimental' and d.policy.family_id == 'F50' for d in planner.DEFINITIONS)
    assert all(d.policy.hooks and d.policy.regressions for d in planner.DEFINITIONS)
    assert not any(d.policy.migrated for d in planner.DEFINITIONS)  # shared integration is pending
    assert planner.GATHER.execute is planner.Planner._plan_for
    assert planner.COVERAGE.execute is planner.missing_deliverables
    assert planner.READINESS.execute is planner.plan_readiness
    assert planner.REVISION.execute is planner.revise_draft
