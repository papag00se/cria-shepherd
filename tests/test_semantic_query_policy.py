"""Independent semantic-query oracles, canonical admission, and private-state lifecycle."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import Mock, call, patch
import uuid

import pytest

from cria import (assistruntime, bodykeys, loop, prompts, researchpolicies,
                  semanticquery as policy, webfetch)
from cria.config import Role

PRIOR = 'ADA Handle API resolve handle to address holder address total handles'
QUERY = 'ADA Handle API resolve handle holder'
TASK = 'resolve an Ada Handle via the API (api.handle.me)'

# Expected requests use fixed prompt seats and literal framing, never the old
# Root judge/guard as an oracle. Prompt prose remains owned by its template file.
QUERY_SYSTEM = prompts.load('search_query_judge')
REHUNT_SYSTEM = prompts.load('search_rehunt_judge')
TOOLS_PREAMBLE = ('YOU DO NOT HAVE WEB FETCH/SEARCH or SHELL EXEC TOOLS AVAILABLE TO YOU — the tool list below '
    'is NOT yours, and you must never claim to have performed any action from it. It is FOR REFERENCE '
    'ONLY: it names the tools THE CODER has, so any action you name for the coder is doable with one of '
    'these, BY THE NAME LISTED — e.g. to search a saved file tell it to run `grep -n "<term>" <file>` via '
    "its shell/exec tool; to see part of a file, the coder's file-reading tool with a line range "
    '(its real name is in the list below):\ntool menu')


def expected_query_user(query, tried):
    return (f'THE TASK:\n{TASK}\n\nTHE QUERY IT IS ABOUT TO SEARCH:\n{query}\n{tried}\n\n'
            'Is that query on-target for the task? Give on_target and a grounded recommendation. '
            'Reply with ONE JSON object only.')


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
    return policy.QueryInput(coder(text), Mock(return_value=policy.QuestionFacts(task, 'menu')),
        Mock(return_value='fetch facts including 404'), Mock(return_value='refused loader coordinate'),
        Mock(return_value='visible docs'), judge)


@pytest.mark.parametrize('text,verdict,cache,kind,recommendation', [
    ('cardano backend API', {'on_target': True}, (True, ''), 'none', ''),
    ('cardano backend API', {'on_target': False, 'recommendation': 'Ada handle API'},
     (False, 'Ada handle API'), 'noted', 'Ada handle API'),
    ('cardano backend API', {'on_target': True, 'recommendation': 'https://api.handle.me/openapi.json'},
     (True, 'https://api.handle.me/openapi.json'), 'fetch', 'https://api.handle.me/openapi.json'),
    ('cardano backend API', {'on_target': False, 'recommendation': 'https://invented.test/no.json'},
     (False, 'https://invented.test/no.json'), 'ungrounded', 'https://invented.test/no.json'),
    ('cardano backend API', {'on_target': False, 'recommendation': 'https://rubygems.org/gems/invented'},
     (False, 'https://rubygems.org/gems/invented'), 'ungrounded', 'https://rubygems.org/gems/invented'),
    ('cardano backend API', {'on_target': False, 'recommendation': '  CARDANO   BACKEND API '},
     (False, 'CARDANO   BACKEND API'), 'none', ''),
    ('cardano backend API', {'on_target': False, 'recommendation': 'Search "Ada Handle" or "Cardano"'},
     (False, 'Search "Ada Handle" or "Cardano"'), 'unusable', ''),
    ('cardano backend API', {'on_target': False, 'recommendation': "web_search('Ada Handle API')"},
     (False, "web_search('Ada Handle API')"), 'noted', 'Ada Handle API'),
    ('Search "one phrase" or "another phrase"', {'on_target': True, 'recommendation': 'Ada Handle API'},
     (True, 'Ada Handle API'), 'noted', 'Ada Handle API'),
    ('cardano backend API', 'not a verdict', (True, ''), 'none', ''),
    ('cardano backend API', {'on_target': 0, 'recommendation': ''}, (True, ''), 'none', ''),
])
def test_guard_source_parity(session, text, verdict, cache, kind, recommendation):
    """Keep the metadata-referenced name; expectations no longer call the old Root.

    Retain the grounded task-host URL, invented package-path refusal, ambiguous
    recommendations, wrapped queries and on-topic-but-unusable query incidents.
    """
    item = source(verdict, text)
    before = deepcopy(item.coder)
    state = policy.QueryState()
    result = policy.query(item, state)
    expected = deepcopy(before)
    if kind in ('noted', 'fetch'):
        action = policy.Action.NOTE if kind == 'noted' else policy.Action.FETCH
        assert result == policy.QueryResult(action, text, recommendation, cache[0], 's')
        assert state.pending is result
    else:
        assert result == policy.QueryResult()
        assert state.pending is None
    out = policy.deliver(policy.DeliveryInput(item.coder, result, session, item.judge.log), state)
    if kind == 'noted':
        expected[bodykeys.NOTES] = [f"'{text}' may be off-target for this task — '{recommendation}' would search "
            'for what the task actually needs. Your search runs either way; re-run it with that if you agree.']
        events = [('loop.search_query_judged', {'action': 'noted', 'query': text, 'rec': recommendation})]
    elif kind == 'fetch':
        expected['choices'][0]['message']['tool_calls'] = [{'id': 's', 'type': 'function',
            'function': {'name': 'web_fetch', 'arguments': '{"url": "https://api.handle.me/openapi.json"}'}}]
        expected[bodykeys.NOTES] = ['fetching https://api.handle.me/openapi.json — the source this task names, read it directly']
        events = [('loop.search_query_judged', {'action': 'fetch', 'query': text, 'rec': recommendation})]
        assert webfetch.was_substituted(session, 'https://api.handle.me/openapi.json')
    elif kind == 'ungrounded':
        events = [('loop.search_query_ungrounded', {'level': 'warn', 'query': text, 'rec': recommendation})]
    elif kind == 'unusable':
        events = [('loop.search_rec_unusable', {'level': 'warn', 'query': text})]
    else:
        events = []
    assert out is item.coder
    assert out == expected
    assert state.verdicts == {text: cache}
    assert item.judge.log.events == events
    item.judge.summarize.assert_called_once_with(item.judge.chat, item.judge.role, QUERY_SYSTEM,
        expected_query_user(text, 'fetch facts including 404\n\nrefused loader coordinate'),
        item.judge.log, phase='reasoner', coder_tools='menu')
    item.fetched.assert_called_once_with()
    item.refused.assert_called_once_with()
    if kind in ('fetch', 'ungrounded'):
        item.session_evidence.assert_called_once_with()
    else:
        item.session_evidence.assert_not_called()
    assert state.pending is None


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
        # Unrelated query relevance still runs while repeat admission is disabled.
        assert policy.query(item, policy.QueryState()).action is policy.Action.NOTE
    assert state.verdicts == {'saved': True}
    assert item.judge.summarize.call_count == 1
    assert webfetch.prior_matching_search(session, QUERY) == PRIOR.lower()


def test_disabled_semantics_leave_pending_caches_and_visibility_untouched(session):
    item = source({'on_target': False, 'recommendation': 'better topic'})
    query_state = policy.QueryState()
    pending = policy.query(item, query_state)
    snapshot = dict(query_state.verdicts)
    item.judge.summarize.reset_mock()
    item.facts.reset_mock()
    request = policy.RehuntInput(item.coder, session, item.facts, item.judge)
    webfetch.set_visible(session, [], [PRIOR])
    rehunt_state = policy.RehuntState({'saved': False})
    before = deepcopy(item.coder)
    with patch.object(webfetch, 'prior_matching_search', side_effect=AssertionError), \
         patch.object(webfetch, 'allow_search', side_effect=AssertionError):
        assert policy.query(item, query_state, enabled=False).action is policy.Action.NONE
        assert policy.rehunt(request, rehunt_state, enabled=False) == policy.RehuntResult()
        assert policy.deliver(policy.DeliveryInput(item.coder, pending, session, item.judge.log),
                              query_state, enabled=False) is item.coder
    assert query_state.pending is pending
    assert query_state.verdicts == snapshot
    assert rehunt_state.verdicts == {'saved': False}
    assert item.coder == before
    item.judge.summarize.assert_not_called()
    item.facts.assert_not_called()
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


def test_query_unknown_cache_and_fact_updates_do_not_create_new_questions():
    item = source('unreadable verdict')
    state = policy.QueryState()
    assert policy.query(item, state).action is policy.Action.NONE
    item.fetched.return_value = 'new success'
    item.refused.return_value = 'new refused dependency'
    assert policy.query(item, state).action is policy.Action.NONE
    item.judge.summarize.assert_called_once()
    item.fetched.assert_called_once()
    state.reset()
    policy.query(item, state)
    assert item.judge.summarize.call_count == 2
    assert 'new success\n\nnew refused dependency' in item.judge.summarize.call_args.args[3]


def test_pending_delivery_reset_replacement_and_session_isolation(session):
    item = source({'on_target': True, 'recommendation': 'https://api.handle.me/openapi.json'})
    first, other = policy.QueryState(), policy.QueryState({'elsewhere': (True, '')})
    result = policy.query(item, first)
    before = deepcopy(item.coder)
    assert not webfetch.was_substituted(session, result.recommendation)
    first.reset()
    assert policy.deliver(policy.DeliveryInput(item.coder, result, session, item.judge.log), first) == before
    result = policy.query(item, first)
    delivery = policy.DeliveryInput(item.coder, result, session, item.judge.log)
    assert policy.deliver(delivery, other) == before
    out = policy.deliver(delivery, first)
    assert out['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'web_fetch'
    assert webfetch.was_substituted(session, result.recommendation)
    notes = list(out[bodykeys.NOTES])
    assert policy.deliver(delivery, first)[bodykeys.NOTES] == notes
    assert other.verdicts == {'elsewhere': (True, '')}


def test_changed_call_cancels_pending_without_delivering_stale_recommendation(session):
    item = source({'on_target': False, 'recommendation': 'better topic'})
    state = policy.QueryState()
    result = policy.query(item, state)
    different = coder('different question')
    assert policy.deliver(policy.DeliveryInput(different, result, session, item.judge.log), state) is different
    assert bodykeys.NOTES not in different
    assert state.pending is None


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


def test_source_definitions_select_replace_and_disable_independently():
    selected = assistruntime.select_definitions(policy.DEFINITIONS, level=4)
    assert selected == ()
    assert assistruntime.select_definitions(policy.DEFINITIONS, level=5,
        disabled=(policy.REHUNT.policy.id,)) == (policy.QUERY,)
    replacement = Mock(return_value=policy.QueryResult())
    definitions = (policy.REHUNT, replace(policy.QUERY, execute=replacement))
    selected = assistruntime.select_definitions(definitions, level=5, disabled=(policy.REHUNT.policy.id,))
    assert selected[0].execute(None, None) == policy.QueryResult()
    replacement.assert_called_once_with(None, None)
    assert all(not d.policy.migrated for d in definitions)


@pytest.mark.parametrize('reply,expected_query', [
    ('not json', (True, '')),
    ('{"on_target":false,"recommendation":"new topic"}', (False, 'new topic'))])
def test_real_fake_provider_requests_and_outcomes_for_distinct_questions(reply, expected_query):
    captured, phases = [], []
    def provider(body, log):
        captured.append(deepcopy(body))
        phases.append(log.phase)
        return json.dumps({'choices': [{'message': {'content': reply}}]}).encode()
    role = Role(name='reasoner', backend='local')
    facts = policy.QuestionFacts(TASK, 'tool menu')
    judge = policy.Judge(loop.summarize, provider, role, Log())
    assert judge.query(facts, QUERY, 'tried') == expected_query
    assert judge.rehunt(facts, QUERY, PRIOR) is False
    # Direct Judge.rehunt preserves the supplied prior verbatim. The selected
    # repeat detector's lowercased prior is covered separately below.
    prior_user = (f'THE TASK BEING WORKED ON:\n{TASK}\n\n'
                  f'THE SEARCH ALREADY RUN (its results are in front of the coder):\n{PRIOR}\n\n'
                  f'THE SEARCH IT WANTS TO RUN NOW:\n{QUERY}')
    assert captured == [
        {'stream': False, 'max_tokens': 8192, 'messages': [
            {'role': 'system', 'content': QUERY_SYSTEM},
            {'role': 'user', 'content': TOOLS_PREAMBLE + '\n\n' + expected_query_user(QUERY, 'tried')}]},
        {'stream': False, 'max_tokens': 8192, 'messages': [
            {'role': 'system', 'content': REHUNT_SYSTEM},
            {'role': 'user', 'content': TOOLS_PREAMBLE + '\n\n' + prior_user}]}]
    assert phases == ['reasoner', 'reasoner']


@pytest.mark.parametrize('new_direction', [True, False, None])
def test_combined_guard_preserves_question_order_and_cached_retry(session, new_direction):
    response = json.dumps({'new_direction': new_direction, 'on_target': True})
    item = source(response)
    webfetch.set_visible(session, [], [PRIOR])
    qs, rs = policy.QueryState(), policy.RehuntState()
    request = policy.RehuntInput(item.coder, session, item.facts, item.judge)
    policy.rehunt(request, rs)
    result = policy.query(item, qs)
    out = policy.deliver(policy.DeliveryInput(item.coder, result, session, item.judge.log), qs)
    expected_calls = [
        call(item.judge.chat, item.judge.role, REHUNT_SYSTEM, REHUNT_USER,
             item.judge.log, phase='reasoner', coder_tools='menu'),
        call(item.judge.chat, item.judge.role, QUERY_SYSTEM,
             expected_query_user(QUERY, 'fetch facts including 404\n\nrefused loader coordinate'),
             item.judge.log, phase='reasoner', coder_tools='menu')]
    assert item.judge.summarize.call_args_list == expected_calls
    assert out is item.coder
    assert out == {'choices': [{'message': {'tool_calls': [{'id': 's', 'type': 'function',
        'function': {'name': 'web_search', 'arguments': '{"query": "ADA Handle API resolve handle holder"}'}}]}}]}
    assert result == policy.QueryResult()
    assert qs.pending is None
    assert qs.verdicts == {QUERY: (True, '')}
    assert rs.verdicts == {QUERY: new_direction is True}
    expected_events = ([('loop.search_rehunt_cleared', {'query': QUERY, 'prior': PRIOR.lower()})]
                       if new_direction is True else [])
    assert item.judge.log.events == expected_events
    admitted = webfetch.gate_search(session, QUERY)
    assert (admitted is None) is (new_direction is True)
    # The first gate consumes any one-use clearance; no second admission is minted.
    assert webfetch.gate_search(session, QUERY) is not None
    policy.rehunt(request, rs)
    policy.query(item, qs)
    assert item.judge.summarize.call_count == 2
    assert item.judge.summarize.call_args_list == expected_calls
    assert item.judge.log.events == expected_events
    assert webfetch.gate_search(session, QUERY) is not None


def test_cached_recommendation_is_regrounded_against_current_task_and_visible_docs():
    item = source({'on_target': False, 'recommendation': 'https://docs.example.test/api'},
                  task='Use the API described in the current research')
    state = policy.QueryState()
    item.session_evidence.return_value = 'Fetched https://docs.example.test/api successfully'
    assert policy.query(item, state).action is policy.Action.FETCH
    item.session_evidence.return_value = 'The earlier document is no longer visible'
    assert policy.query(item, state).action is policy.Action.NONE
    item.judge.summarize.assert_called_once()
    assert state.pending is None


def test_no_reasoner_or_missing_task_preserves_queries_and_caches_unknown(session):
    for facts, role in ((policy.QuestionFacts(''), object()), (policy.QuestionFacts(TASK), None)):
        item = source({'on_target': False, 'recommendation': 'invented alternative'})
        item = replace(item, facts=lambda: facts, judge=replace(item.judge, role=role))
        state = policy.QueryState()
        assert policy.query(item, state).action is policy.Action.NONE
        assert state.verdicts == {QUERY: (True, '')}
        item.judge.summarize.assert_not_called()
    webfetch.set_visible(session, [], [PRIOR])
    state = policy.RehuntState()
    assert not policy.rehunt(policy.RehuntInput(item.coder, session, item.facts, item.judge), state).clearance_requested
    assert state.verdicts == {QUERY: False}
    assert webfetch.gate_search(session, QUERY) is not None


def test_task_reset_does_not_destroy_shared_fetch_visibility_or_refusal_facts(session):
    webfetch.set_visible(session, [('https://api.handle.me/openapi.json', '', '')], [PRIOR])
    item = source({'on_target': True})
    state, rehunt_state = policy.QueryState(), policy.RehuntState({'old query': True})
    policy.query(item, state)
    state.reset()
    rehunt_state.reset()
    assert state.verdicts is None and state.pending is None and rehunt_state.verdicts is None
    assert webfetch.visible_urls(session) == {'https://api.handle.me/openapi.json'}
    assert webfetch.prior_matching_search(session, QUERY) == PRIOR.lower()
    assert item.fetched() == 'fetch facts including 404'
    assert item.refused() == 'refused loader coordinate'


def test_current_authoritative_fetch_and_refusal_ledger_reach_relevance_question(session):
    from cria import refusalledger
    def event(outcome, sequence):
        return refusalledger.RefusalEvent(ecosystem='rubygems', raw_coordinate='eu_countries',
            package='eu_countries', version='', outcome=outcome,
            evidence='cannot load such file -- iso3166', sequence=sequence)
    ledger = refusalledger.RefusalLedger([event(refusalledger.REFUSED, 1)])
    shared = SimpleNamespace(web_session=session,
        fetched_pages={'https://rubygems.org/gems/eu_countries': (200, '')}, refusal_events=ledger)
    item = source({'on_target': True})
    item = replace(item, fetched=lambda: loop._fetch_ground_truth([], shared),
                   refused=lambda: loop._unresolved_deps(shared))
    state = policy.QueryState()
    policy.query(item, state)
    question = item.judge.summarize.call_args.args[3]
    assert '200' in question and 'eu_countries' in question
    assert 'could not install or load' in question.lower()
    # Observed success supersedes the refusal in the authoritative shared ledger;
    # the policy does not mutate it or invent a second success/refusal detector.
    shared.refusal_events = refusalledger.RefusalLedger([
        event(refusalledger.REFUSED, 1), event(refusalledger.SUCCEEDED, 2)])
    state.reset()
    policy.query(item, state)
    assert 'could not install or load' not in item.judge.summarize.call_args.args[3].lower()
    assert '200' in item.judge.summarize.call_args.args[3]
    assert shared.fetched_pages == {'https://rubygems.org/gems/eu_countries': (200, '')}


def turn_input(item, session):
    return policy.TurnInput(item.coder, session, item.facts, item.fetched, item.refused,
                            item.session_evidence, item.judge)


def live_owner():
    owner = loop.GuardState()
    # The declared production bridge slot is transient; no new fake state DTO.
    owner.semantic_pending = None
    return owner


def test_production_stage_keeps_original_reply_and_live_cache_reference_until_retained(session):
    item = source({'on_target': True, 'recommendation': 'https://api.handle.me/openapi.json'})
    owner = live_owner()
    cache = {QUERY: (True, 'https://api.handle.me/openapi.json')}
    owner.query_verdicts = cache
    original = item.coder
    assert policy.prepare_turn(turn_input(item, session), owner, policy.Selection(query=policy.QUERY)) is original
    pending = owner.semantic_pending
    assert pending.coder is original and pending.selection.query is policy.QUERY
    assert pending.query_state.verdicts is cache and owner.query_verdicts is cache
    item.judge.summarize.assert_not_called()
    item.fetched.assert_not_called()
    item.refused.assert_not_called()
    assert item.judge.log.events == []
    assert not webfetch.was_substituted(session, 'https://api.handle.me/openapi.json')
    assert policy.settle_turn(owner, original) == policy.Settlement(True, False)
    assert owner.semantic_pending is None
    assert webfetch.was_substituted(session, 'https://api.handle.me/openapi.json')
    assert item.judge.log.events == [('loop.search_query_judged', {
        'action': 'fetch', 'query': QUERY, 'rec': 'https://api.handle.me/openapi.json'})]
    assert policy.settle_turn(owner, original) == policy.Settlement()
    assert len(item.judge.log.events) == 1


@pytest.mark.parametrize('outcome', ['equal-copy', 'changed-call', 'drop', 'explicit-discard'])
def test_production_pending_cannot_credit_nonretained_or_changed_effect(session, outcome):
    item = source({'on_target': True, 'recommendation': 'https://api.handle.me/openapi.json'})
    owner = live_owner()
    policy.prepare_turn(turn_input(item, session), owner, policy.Selection(query=policy.QUERY))
    candidate = item.coder
    if outcome == 'equal-copy':
        retained = deepcopy(candidate)
    elif outcome == 'changed-call':
        candidate['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = '{"url":"https://other.test/"}'
        retained = candidate
    elif outcome == 'explicit-discard':
        policy.discard_turn(owner)
        retained = candidate
    else:
        retained = None
    assert policy.settle_turn(owner, retained) == policy.Settlement()
    assert owner.semantic_pending is None
    assert item.judge.log.events == []
    assert not webfetch.was_substituted(session, 'https://api.handle.me/openapi.json')


def test_new_candidate_cancels_old_pending_without_mirroring_live_cache(session):
    owner = live_owner()
    first = source({'on_target': True, 'recommendation': 'https://api.handle.me/openapi.json'})
    policy.prepare_turn(turn_input(first, session), owner, policy.Selection(query=policy.QUERY))
    previous = owner.semantic_pending
    cache = owner.query_verdicts
    second = source({'on_target': True}, text='second independent query')
    policy.prepare_turn(turn_input(second, session), owner, policy.Selection(query=policy.QUERY))
    assert previous.query_state.pending is None
    assert owner.query_verdicts is cache
    assert owner.query_verdicts == {QUERY: (True, 'https://api.handle.me/openapi.json'),
                                   'second independent query': (True, '')}
    assert policy.settle_turn(owner, first.coder) == policy.Settlement()
    assert not webfetch.was_substituted(session, 'https://api.handle.me/openapi.json')
    assert first.judge.log.events == [] and second.judge.log.events == []


def test_deferred_rehunt_uses_public_owner_only_after_retained_search(session):
    webfetch.set_visible(session, [], [PRIOR])
    owner = live_owner()
    item = source({'new_direction': True})
    selection = policy.Selection(rehunt=policy.REHUNT)
    policy.prepare_turn(turn_input(item, session), owner, selection)
    assert owner.rehunt_verdicts == {QUERY: True}
    assert owner.query_verdicts is None
    assert webfetch.gate_search(session, QUERY) is not None
    assert item.judge.log.events == []
    assert policy.settle_turn(owner, item.coder) == policy.Settlement(False, True)
    assert webfetch.gate_search(session, QUERY) is None
    assert webfetch.gate_search(session, QUERY) is not None
    assert item.judge.log.events == [('loop.search_rehunt_cleared', {'query': QUERY, 'prior': PRIOR.lower()})]
    policy.prepare_turn(turn_input(item, session), owner, selection)
    assert policy.settle_turn(owner, item.coder) == policy.Settlement()
    item.judge.summarize.assert_called_once()
    assert webfetch.gate_search(session, QUERY) is not None


def test_production_absence_is_lazy_and_reset_keeps_public_research_facts(session):
    webfetch.set_visible(session, [('https://api.handle.me/', '', '')], [PRIOR])
    owner = live_owner()
    owner.query_verdicts, owner.rehunt_verdicts = {'saved': (False, '')}, {'saved': False}
    item = source({'on_target': False})
    bombs = replace(item, facts=Mock(side_effect=AssertionError), fetched=Mock(side_effect=AssertionError),
                    refused=Mock(side_effect=AssertionError), session_evidence=Mock(side_effect=AssertionError))
    assert policy.prepare_turn(turn_input(bombs, session), owner, policy.Selection()) is item.coder
    assert owner.query_verdicts == {'saved': (False, '')} and owner.rehunt_verdicts == {'saved': False}
    bombs.facts.assert_not_called()
    bombs.fetched.assert_not_called()
    bombs.refused.assert_not_called()
    bombs.session_evidence.assert_not_called()
    item.judge.summarize.assert_not_called()
    policy.reset_turn(owner)
    assert owner.query_verdicts is None and owner.rehunt_verdicts is None and owner.semantic_pending is None
    assert webfetch.visible_urls(session) == {'https://api.handle.me/'}
    assert webfetch.prior_matching_search(session, QUERY) == PRIOR.lower()


def test_selected_stage_must_not_clone_authenticated_completion(session):
    owner = live_owner()
    item = source({'on_target': False, 'recommendation': 'better query'})
    selected = replace(policy.QUERY, stage=lambda source, state: deepcopy(source.coder))
    with pytest.raises(ValueError, match='retain coder completion identity'):
        policy.prepare_turn(turn_input(item, session), owner, policy.Selection(query=selected))
    assert owner.semantic_pending is None
    assert item.judge.log.events == []
