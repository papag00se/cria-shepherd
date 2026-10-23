"""New-direction judgment, canonical repeat admission and private-state lifecycle."""
from dataclasses import replace
import json
from unittest.mock import Mock, patch
import uuid

import pytest

from cria import loop, prompts, researchpolicies, semanticquery as policy, webfetch


PRIOR = 'ADA Handle API resolve handle to address holder address total handles'


QUERY = 'ADA Handle API resolve handle holder'


TASK = 'resolve an Ada Handle via the API (api.handle.me)'


REHUNT_SYSTEM = prompts.load('search_rehunt_judge')


REHUNT_USER = (f'THE TASK BEING WORKED ON:\n{TASK}\n\n'
               f'THE SEARCH ALREADY RUN (its results are in front of the coder):\n{PRIOR.lower()}\n\n'
               f'THE SEARCH IT WANTS TO RUN NOW:\n{QUERY}')


class Log:
    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))


@pytest.fixture
def session():
    key = 'semantic-query-' + uuid.uuid4().hex
    yield key
    webfetch.reset_session(key)


def coder(text=QUERY):
    return {'choices': [{'message': {'tool_calls': [{'id': 's', 'type': 'function',
            'function': {'name': 'web_search', 'arguments': json.dumps({'query': text})}}]}}]}


def source(response, text=QUERY, task=TASK, log=None):
    provider = Mock(return_value=json.dumps(response) if not isinstance(response, str) else response)
    log = log or Log()
    judge = policy.Judge(provider, Mock(side_effect=AssertionError), object(), log)
    return policy.RehuntInput(coder(text), None, Mock(return_value=policy.QuestionFacts(task, 'menu')), judge)


@pytest.mark.parametrize('reply', ['garbage', '{}', '{"new_direction":false}', '{"new_direction":true}'])
def test_rehunt_parity_cache_and_one_use_clearance(session, reply):
    webfetch.set_visible(session, [], [PRIOR])
    item = source({'on_target': True})
    provider = Mock(return_value=reply)
    judge = replace(item.judge, summarize=provider)
    request = policy.RehuntInput(item.coder, session, item.facts, judge)
    state = policy.RehuntState()
    out = policy.rehunt(request, state)
    expected_fresh = reply == '{"new_direction":true}'
    assert out.clearance_requested is expected_fresh
    assert out == policy.RehuntResult(QUERY, PRIOR.lower(), expected_fresh, expected_fresh)
    provider.assert_called_once_with(judge.chat, judge.role, REHUNT_SYSTEM, REHUNT_USER,
                                     judge.log, phase='reasoner', coder_tools='menu')
    assert state.verdicts == {QUERY: expected_fresh}
    assert (webfetch.gate_search(session, QUERY) is None) is expected_fresh
    assert webfetch.gate_search(session, QUERY) is not None
    # A cached true is not a standing allowance; never mint a second clearance.
    assert not policy.rehunt(request, state).clearance_requested
    provider.assert_called_once()
    assert webfetch.gate_search(session, QUERY) is not None
    state.reset()
    assert policy.rehunt(request, state).clearance_requested is expected_fresh
    assert provider.call_count == 2


def test_repeat_disabled_never_enters_detector_or_clearance(session):
    item = source({'on_target': False, 'recommendation': 'better topic'})
    webfetch.set_visible(session, [], [PRIOR])
    state = policy.RehuntState({'saved': True})
    request = policy.RehuntInput(item.coder, session, item.facts, item.judge)
    with researchpolicies.bound(researchpolicies.ResearchSelection(search=None)), \
         patch.object(webfetch, 'prior_matching_search', side_effect=AssertionError), \
         patch.object(webfetch, 'allow_search', side_effect=AssertionError):
        assert policy.rehunt(request, state) == policy.RehuntResult()
    assert state.verdicts == {'saved': True}
    item.judge.summarize.assert_not_called()
    assert webfetch.prior_matching_search(session, QUERY) == PRIOR.lower()


@pytest.mark.parametrize('visible', [[], [QUERY], ['entirely unrelated prior']])
def test_no_prior_or_identical_query_has_no_rehunt_question(session, visible):
    webfetch.set_visible(session, [], visible)
    item = source({'new_direction': True})
    state = policy.RehuntState()
    assert not policy.rehunt(policy.RehuntInput(item.coder, session, item.facts, item.judge), state).clearance_requested
    assert state.verdicts is None
    item.facts.assert_not_called()
    item.judge.summarize.assert_not_called()


def test_repeat_replacement_owns_prior_and_clearance_without_canonical_detector(session):
    item = source({'new_direction': True})
    calls = []
    def replaced(source, state):
        calls.append(source.action)
        return researchpolicies.Admission(prior='a different visible pair')
    selected = replace(researchpolicies.SEARCH, execute=replaced)
    with researchpolicies.bound(researchpolicies.ResearchSelection(search=selected)), \
         patch('cria.researchpolicies.searches_match', side_effect=AssertionError):
        result = policy.rehunt(policy.RehuntInput(item.coder, session, item.facts, item.judge), policy.RehuntState())
    assert result.clearance_requested
    assert calls == [researchpolicies.SearchAction.PRIOR, researchpolicies.SearchAction.CLEAR]


def turn_input(item, session):
    return policy.TurnInput(item.coder, session, item.facts, item.judge)


def live_owner():
    owner = loop.GuardState()
    # The declared production bridge slot is transient; no new fake state DTO.
    owner.semantic_pending = None
    return owner


def test_deferred_rehunt_uses_public_owner_only_after_retained_search(session):
    webfetch.set_visible(session, [], [PRIOR])
    owner = live_owner()
    item = source({'new_direction': True})
    selection = policy.Selection(rehunt=policy.REHUNT)
    policy.prepare_turn(turn_input(item, session), owner, selection)
    assert owner.rehunt_verdicts == {QUERY: True}
    assert webfetch.gate_search(session, QUERY) is not None
    assert item.judge.log.events == []
    assert policy.settle_turn(owner, item.coder) == policy.Settlement(True)
    assert webfetch.gate_search(session, QUERY) is None
    assert webfetch.gate_search(session, QUERY) is not None
    assert item.judge.log.events == [('loop.search_rehunt_cleared', {'query': QUERY, 'prior': PRIOR.lower()})]
    policy.prepare_turn(turn_input(item, session), owner, selection)
    assert policy.settle_turn(owner, item.coder) == policy.Settlement()
    item.judge.summarize.assert_called_once()
    assert webfetch.gate_search(session, QUERY) is not None
