"""Fake-only string adapter contracts; no Plan reconstruction or completion authority."""
import pytest

from cria import livingplan as lp, planner
from test_living_plan_policy import (REPLAN_SYSTEM, REPLAN_USER, NOISE_SYSTEM,
                                    COVERAGE_SYSTEM, Log, Questions, make)


def invoke(replies, **changes):
    question, log = Questions(replies), Log()
    kwargs = dict(question=question, task='Build the CLI, tests, and guide',
                  completed='- Build the CLI', remaining='- Write tests',
                  evidence='CURRENT CHECKER OUTPUT', log=log,
                  coder_tools='  - shell: command',
                  trigger='A step just finished and was verified.',
                  research='REAL RESEARCH FACTS', tool_names=('shell',),
                  coverage=planner.COVERAGE.execute)
    kwargs.update(changes)
    return lp.reassess_compatibility(**kwargs), question, log


def test_literal_requests_and_string_only_result():
    result, q, log = invoke(['["Write tests", "Write guide"]', 'NONE', '{"missing": []}'])
    assert result == ['Write tests', 'Write guide']
    assert full_calls(q.calls) == [
        (REPLAN_SYSTEM, REPLAN_USER, {'coder_tools': '  - shell: command'}),
        (NOISE_SYSTEM, 'REAL RESEARCH FACTS\n\nTASK:\nBuild the CLI, tests, and guide\n\nPLAN:\n1. Write tests\n2. Write guide', {}),
        (COVERAGE_SYSTEM, 'REQUEST:\nBuild the CLI, tests, and guide\n\nPLAN:\n1. Build the CLI\n2. Write tests\n3. Write guide', {})]
    assert log.events == [('loop.replan_noise', dict(dropped=0, kept=2, dropped_steps='', level='info'))]
    assert q.replies == []


@pytest.mark.parametrize('reply, expected', [('not JSON', None), ('[]', [])])
def test_absent_and_empty_are_distinct_without_confirmation(reply, expected):
    result, q, log = invoke([reply])
    assert result == expected and len(q.calls) == 1 and log.events == []


@pytest.mark.parametrize('changes', [dict(question=None), dict(remaining=' \n\t')])
def test_inapplicable_is_lazy(changes):
    def forbidden(*args, **kwargs):
        raise AssertionError('no proposal services on absent role or blank tail')
    result, q, log = invoke([], coverage=forbidden, **changes)
    assert result is None and q.calls == [] and log.events == []


def test_selected_coverage_preserves_legacy_projection_and_uncovered_append():
    seen, uncovered = [], ['prior']
    def coverage(ask, task, steps):
        seen.append((task, steps))
        return ['guide']
    result, q, log = invoke(['["Write tests"]', 'NONE'],
                           completed='- Build the CLI\n  continuation\n- Other completed',
                           coverage=coverage, uncovered=uncovered)
    assert result is None
    assert seen == [('Build the CLI, tests, and guide', ['Build the CLI', 'Other completed', 'Write tests'])]
    assert uncovered == ['prior', 'guide'] and len(q.calls) == 2
    assert log.events[-1] == ('loop.replan_uncovered', dict(level='warn', missing='guide'))


def test_lifecycle_uses_same_stateless_authority_without_display_projection(monkeypatch):
    seen = []
    def proposal(**kwargs):
        seen.append(kwargs)
        return lp.Proposal(lp.TailStatus.REPLACED, ('Write guide',))
    monkeypatch.setattr(lp, 'propose_tail', proposal)
    source, state, questions, mirrors, facts = make([], completed=('Build the CLI\nEXACT continuation',))
    result = lp.LivingSelection.opt_in().run(source, state)
    assert result.status is lp.TailStatus.REPLACED
    assert seen[0]['completed_steps'] == ('Build the CLI\nEXACT continuation',)
    assert seen[0]['completed'] == '- Build the CLI\nEXACT continuation'
    assert seen[0]['coverage'] is source.services.coverage.execute
    assert questions.calls == [] and facts == [True] and len(mirrors) == 1
    result, q, log = invoke([])
    assert result == ['Write guide'] and q.calls == []
    assert seen[1]['completed_steps'] == ('Build the CLI',)


def public_invoke(monkeypatch, replies, **changes):
    from cria import loop
    question, log = Questions(replies), Log()
    chat, role = object(), object()
    def summarize(actual_chat, actual_role, system, user, actual_log, **kwargs):
        assert actual_chat is chat and actual_role is role and actual_log is log
        assert kwargs.pop('phase') == 'reasoner'
        return question(system, user, **kwargs)
    monkeypatch.setattr(loop, 'summarize', summarize)
    kwargs = dict(reasoner_chat=chat, reasoner_role=role,
                  task='Build the CLI, tests, and guide', completed='- Build the CLI',
                  remaining='- Write tests', evidence='CURRENT CHECKER OUTPUT', rlog=log,
                  coder_tools='  - shell: command', facts='REAL RESEARCH FACTS')
    kwargs.update(changes)
    return loop.reassess_remaining(**kwargs), question, log


def test_public_helper_literal_requests_and_roles(monkeypatch):
    result, q, log = public_invoke(monkeypatch, ['["Write tests", "Write guide"]', 'NONE', '{"missing": []}'])
    assert result == ['Write tests', 'Write guide']
    assert full_calls(q.calls) == [
        (REPLAN_SYSTEM, REPLAN_USER, {'coder_tools': '  - shell: command'}),
        (NOISE_SYSTEM, 'REAL RESEARCH FACTS\n\nTASK:\nBuild the CLI, tests, and guide\n\nPLAN:\n1. Write tests\n2. Write guide', {}),
        (COVERAGE_SYSTEM, 'REQUEST:\nBuild the CLI, tests, and guide\n\nPLAN:\n1. Build the CLI\n2. Write tests\n3. Write guide', {})]
    assert log.events == [('loop.replan_noise', dict(dropped=0, kept=2, dropped_steps='', level='info'))]
    assert q.replies == []


@pytest.mark.parametrize('reply, expected', [('not JSON', None), ('[]', [])])
def test_public_helper_absent_empty_literals(monkeypatch, reply, expected):
    result, q, log = public_invoke(monkeypatch, [reply])
    assert result == expected
    assert full_calls(q.calls) == [(REPLAN_SYSTEM, REPLAN_USER, {'coder_tools': '  - shell: command'})]
    assert q.replies == [] and log.events == []


@pytest.mark.parametrize('steps', [None, (), ('Source-owned replacement',)])
def test_public_helper_obeys_actual_source_proposal_authority(monkeypatch, steps):
    seen = []
    def proposal(**kwargs):
        seen.append(kwargs)
        return lp.Proposal(lp.TailStatus.ABSENT if steps is None else
                           lp.TailStatus.EMPTY_PENDING if not steps else lp.TailStatus.REPLACED,
                           steps)
    monkeypatch.setattr(lp, 'propose_tail', proposal)
    # Valid replies let the obsolete body complete normally, not fail in setup.
    result, q, log = public_invoke(monkeypatch, ['["Write tests"]', 'NONE', '{"missing": []}'])
    assert result == (None if steps is None else list(steps))
    assert len(seen) == 1
    assert seen[0]['completed_steps'] == ('Build the CLI',)
    assert seen[0]['tool_names'] == ('shell',)
    assert full_calls(q.calls) == [] and log.events == []


@pytest.mark.parametrize('changes', [dict(reasoner_role=None), dict(remaining=' \n\t')])
def test_public_helper_inapplicable_never_calls_services(monkeypatch, changes):
    result, q, log = public_invoke(monkeypatch, [], **changes)
    assert result is None and q.calls == [] and log.events == []


def test_public_helper_selected_coverage_and_uncovered_append(monkeypatch):
    seen, uncovered = [], ['prior']
    class Policies:
        def coverage(self, ask, task, steps):
            seen.append((task, steps))
            return ['guide']
    result, q, log = public_invoke(monkeypatch, ['["Write tests"]', 'NONE'],
                                  completed='- Build the CLI\n  continuation\n- Other completed',
                                  policies=Policies(), uncovered=uncovered)
    assert result is None
    assert seen == [('Build the CLI, tests, and guide', ['Build the CLI', 'Other completed', 'Write tests'])]
    assert uncovered == ['prior', 'guide'] and len(q.calls) == 2 and q.replies == []
    assert log.events == [('loop.replan_noise', dict(dropped=0, kept=1, dropped_steps='', level='info')),
                          ('loop.replan_uncovered', dict(level='warn', missing='guide'))]


def test_public_helper_uses_exact_source_adapter_and_live_services(monkeypatch):
    from cria import loop
    seen, coverage_calls, uncovered = [], [], ['prior']
    def coverage(ask, task, steps):
        coverage_calls.append((task, steps))
        assert ask('coverage question', 'coverage evidence') == 'coverage reply'
        return ['guide']
    class Policies:
        pass
    policies = Policies()
    policies.coverage = coverage
    def adapter(**kwargs):
        seen.append(kwargs)
        assert kwargs['coverage'] is coverage
        assert kwargs['question']('proposal question', 'proposal evidence', coder_tools=kwargs['coder_tools']) == 'proposal reply'
        assert kwargs['question']('noise question', 'noise evidence') == 'noise reply'
        missing = kwargs['coverage'](lambda system, user: kwargs['question'](system, user), kwargs['task'], ['complete', 'tail'])
        kwargs['uncovered'].extend(missing)
        return ['Authority replacement']
    monkeypatch.setattr(lp, 'reassess_compatibility', adapter)
    result, q, log = public_invoke(monkeypatch, ['proposal reply', 'noise reply', 'coverage reply'],
                                  policies=policies, uncovered=uncovered)
    assert result == ['Authority replacement']
    assert len(seen) == 1 and seen[0]['uncovered'] is uncovered
    assert seen[0]['task'] == 'Build the CLI, tests, and guide'
    assert seen[0]['completed'] == '- Build the CLI'
    assert seen[0]['remaining'] == '- Write tests'
    assert seen[0]['evidence'] == 'CURRENT CHECKER OUTPUT'
    assert seen[0]['research'] == 'REAL RESEARCH FACTS'
    assert seen[0]['trigger'] == loop.REPLAN_TRIGGER_ADVANCE
    assert seen[0]['tool_names'] == ('shell',)
    assert coverage_calls == [('Build the CLI, tests, and guide', ['complete', 'tail'])]
    assert uncovered == ['prior', 'guide']
    assert full_calls(q.calls) == [('proposal question', 'proposal evidence', {'coder_tools': '  - shell: command'}),
                       ('noise question', 'noise evidence', {}),
                       ('coverage question', 'coverage evidence', {})]
    assert q.replies == [] and log.events == []

from test_living_plan_policy import full_calls
