"""Selected semantic questions and retained public-driver delivery; scripted primitives only."""
from copy import deepcopy
from dataclasses import replace
import io
import json

import pytest

from cria import assistruntime, bodykeys, classify, config, loop, prompts, refusalledger, researchpolicies, semanticquery as policy, webfetch, wsview
from cria.plan import Plan, PlanItem
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog

TASK = 'resolve an Ada Handle via the API (api.handle.me)'
QUERY = 'ADA Handle API resolve handle holder'
PRIOR = 'ADA Handle API resolve handle to address holder address total handles'
SESSION = 'driver-fixture'
URL = 'https://api.handle.me/openapi.json'


def runtime(*, query=policy.QUERY, rehunt=policy.REHUNT, level=5, disabled=(), reverse=False, experimental_planning=False):
    owned = {d.policy.id for d in policy.DEFINITIONS}
    registrations = tuple(d for d in assistruntime.DEFINITIONS if d.policy.id not in owned) + (
        (query, rehunt) if reverse else (rehunt, query))
    return assistruntime.AssistRuntime.select(level=level, registrations=registrations, disabled=disabled,
                                             experimental_planning=experimental_planning)


def search_completion(query=QUERY):
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
        'tool_calls': [{'id': 's', 'type': 'function', 'function': {
            'name': 'web_search', 'arguments': json.dumps({'query': query})}}]}}]}


@pytest.fixture(autouse=True)
def isolated_public_research_session():
    webfetch.reset_session(SESSION)
    yield
    webfetch.reset_session(SESSION)


def rig(monkeypatch, root, *, synthetic=True, answer=None, coder_replies=None):
    driver, state, body = setup_driver()
    state.synthetic = synthetic
    state.plan_off = synthetic
    state.plan.task = TASK
    state.plan.items[0].text = TASK
    body['messages'][0]['content'] = TASK
    body['tools'] += [{'type': 'function', 'function': {'name': name,
        'parameters': {'type': 'object', 'properties': {arg: {'type': 'string'}}, 'required': [arg]}}}
        for name, arg in [('web_search', 'query'), ('web_fetch', 'url')]]
    driver._ctx.pilot_runtime = root
    driver._ctx.assists = True
    driver._ctx.reasoner_role = config.Role(name='reasoner', backend='local')
    questions, posted = [], []
    def reasoner(frame, log):
        questions.append(deepcopy(frame))
        verdict = ({'on_target': False, 'recommendation': 'Ada Handle API'} if answer is None else answer)
        return json.dumps({'choices': [{'message': {'role': 'assistant', 'content': json.dumps(verdict)}}]}).encode()
    driver._ctx.reasoner_chat = reasoner
    up = driver._ctx.coder_chat.__self__
    replies = iter(coder_replies) if coder_replies is not None else None
    def transport(request, **options):
        if request.full_url.endswith('/v1/chat/completions'):
            posted.append(json.loads(request.data))
            reply = search_completion() if replies is None else next(replies)
            return io.BytesIO(json.dumps(reply).encode())
        if request.full_url.endswith('/tokenize'):
            return io.BytesIO(b'{"tokens":[1,2,3]}')
        return io.BytesIO(b'{"data":[]}')
    monkeypatch.setattr(up, '_receive_open', transport)
    return driver, state, body, questions, posted


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('mode', ['both-disabled', 'below-level'])
def test_public_absence_runs_neither_question_or_optional_cache_work(monkeypatch, synthetic, mode):
    root = runtime(level=4 if mode == 'below-level' else 5,
        disabled=tuple(d.policy.id for d in policy.DEFINITIONS) if mode == 'both-disabled' else ())
    driver, state, body, questions, posted = rig(monkeypatch, root, synthetic=synthetic)
    out = driver.drive(body, SESSION, None, _Rlog())
    assert len(posted) == 1
    assert out['choices'][0]['message']['tool_calls'] == search_completion()['choices'][0]['message']['tool_calls']
    assert questions == []
    assert bodykeys.NOTES not in out
    assert state.query_verdicts is None and state.rehunt_verdicts is None


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_exact_selected_relevance_executes_stages_and_settles_on_same_reply(monkeypatch, synthetic):
    seen = []
    def execute(source, state):
        seen.append(('execute', source, state))
        return policy.QUERY.execute(source, state)
    def stage(source, state):
        seen.append(('stage', source, state))
        return policy.QUERY.stage(source, state)
    def settle(source, state):
        seen.append(('settle', source, state))
        return policy.QUERY.settle(source, state)
    chosen = replace(policy.QUERY, execute=execute, stage=stage, settle=settle)
    driver, state, body, questions, posted = rig(monkeypatch,
        runtime(query=chosen, disabled=(policy.REHUNT.policy.id,)), synthetic=synthetic)
    out = driver.drive(body, SESSION, None, _Rlog())
    assert len(posted) == 1 and len(questions) == 1
    assert [item[0] for item in seen] == ['execute', 'stage', 'settle']
    assert seen[0][2].verdicts is state.query_verdicts
    assert seen[1][1].coder is out and seen[2][1].coder is out
    assert seen[1][1].result is seen[2][1].result
    assert out[bodykeys.NOTES] == [f"'{QUERY}' may be off-target for this task — 'Ada Handle API' would search "
        'for what the task actually needs. Your search runs either way; re-run it with that if you agree.']
    assert state.query_verdicts == {QUERY: (False, 'Ada Handle API')}
    assert state.rehunt_verdicts is None


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_exact_rehunt_replacement_defers_then_uses_canonical_public_admission(monkeypatch, synthetic):
    webfetch.set_visible(SESSION, [], [PRIOR])
    seen = []
    def execute(source, state):
        assert isinstance(source, policy.RehuntInput) and isinstance(state, policy.RehuntState)
        assert source.defer_clearance is True
        seen.append(('execute', source, state))
        return policy.REHUNT.execute(source, state)
    def settle(result, coder, session, log):
        seen.append(('settle', result, coder))
        return policy.REHUNT.settle(result, coder, session, log)
    chosen = replace(policy.REHUNT, execute=execute, settle=settle)
    driver, state, body, questions, posted = rig(monkeypatch,
        runtime(rehunt=chosen, disabled=(policy.QUERY.policy.id,)), synthetic=synthetic,
        answer={'new_direction': True})
    out = driver.drive(body, SESSION, None, _Rlog())
    assert [item[0] for item in seen] == ['execute', 'settle']
    assert seen[0][2].verdicts is state.rehunt_verdicts
    assert seen[1][2] is out
    assert len(questions) == 1 and len(posted) == 1
    assert questions[0]['messages'][0]['content'] == prompts.load('search_rehunt_judge')
    assert webfetch.gate_search(SESSION, QUERY) is None
    assert webfetch.gate_search(SESSION, QUERY) is not None
    assert state.query_verdicts is None and state.semantic_pending is None


@pytest.mark.parametrize('level', range(6))
def test_canonical_two_independent_registrations_and_exact_frozen_projection(level):
    root = assistruntime.AssistRuntime.select(level=level)
    for definition, field in ((policy.QUERY, 'query'), (policy.REHUNT, 'rehunt')):
        assert sum(d is definition for d in assistruntime.DEFINITIONS) == 1
        assert getattr(root, field) is (definition if level == 5 else None)
        with pytest.raises(AttributeError):
            setattr(root, field, None)
        assert definition.policy.family_id == 'F51'
        assert definition.policy.migrated is False
    assert loop.GuardState().semantic_pending is None


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('disabled', [(), (policy.QUERY.policy.id,), (policy.REHUNT.policy.id,)])
def test_public_distinct_questions_independence_order_and_canonical_clearance(monkeypatch, synthetic, disabled):
    webfetch.set_visible(SESSION, [], [PRIOR])
    root = runtime(disabled=disabled)
    driver, state, body, questions, posted = rig(monkeypatch, root, synthetic=synthetic,
        answer={'new_direction': True, 'on_target': False, 'recommendation': 'Ada Handle API'})
    log = _Rlog()
    out = driver.drive(body, SESSION, None, log)
    query_on, rehunt_on = policy.QUERY.policy.id not in disabled, policy.REHUNT.policy.id not in disabled
    expected = ([prompts.load('search_rehunt_judge')] if rehunt_on else []) + ([prompts.load('search_query_judge')] if query_on else [])
    assert [q['messages'][0]['content'] for q in questions] == expected
    assert len(posted) == 1
    assert out['choices'][0]['message']['tool_calls'] == search_completion()['choices'][0]['message']['tool_calls']
    assert (bodykeys.NOTES in out) is query_on
    assert state.query_verdicts == ({QUERY: (False, 'Ada Handle API')} if query_on else None)
    assert state.rehunt_verdicts == ({QUERY: True} if rehunt_on else None)
    assert (webfetch.gate_search(SESSION, QUERY) is None) is rehunt_on
    assert webfetch.gate_search(SESSION, QUERY) is not None
    events = [(event, fields) for event, fields in log.events
              if event in ('loop.search_query_judged', 'loop.search_rehunt_cleared')]
    assert events == ([('loop.search_rehunt_cleared', {'query': QUERY, 'prior': PRIOR.lower()})] if rehunt_on else []) + (
        [('loop.search_query_judged', {'action': 'noted', 'query': QUERY, 'rec': 'Ada Handle API'})] if query_on else [])
    assert state.semantic_pending is None
    # Same task, same live state: cached true never grants another clearance.
    driver.drive(body, SESSION, None, _Rlog())
    assert [q['messages'][0]['content'] for q in questions] == expected
    assert webfetch.gate_search(SESSION, QUERY) is not None


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('late', ['retained', 'equal-copy', 'replacement', 'none', 'exception', 'changed-call', 'owner-replacement'])
def test_public_late_return_alone_commits_substituted_fetch(monkeypatch, synthetic, late):
    driver, state, body, questions, posted = rig(monkeypatch,
        runtime(disabled=(policy.REHUNT.policy.id,)), synthetic=synthetic,
        answer={'on_target': True, 'recommendation': URL})
    log = _Rlog()
    method = '_drive_single_item' if synthetic else '_work'
    original = getattr(driver, method)
    staged = []
    def decide_late(*args, **kwargs):
        candidate = original(*args, **kwargs)
        staged.append(candidate)
        assert state.semantic_pending is not None
        assert state.semantic_pending.coder is candidate
        assert not webfetch.was_substituted(SESSION, URL)
        assert not any(event == 'loop.search_query_judged' for event, _ in log.events)
        if late == 'equal-copy':
            return deepcopy(candidate)
        if late == 'replacement':
            return search_completion('replacement-owned search')
        if late == 'none':
            return None
        if late == 'exception':
            raise RuntimeError('late public return failed')
        if late == 'changed-call':
            candidate['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = '{"url":"https://other.test/"}'
        if late == 'owner-replacement':
            fresh = loop._session_from_dict(loop._session_to_dict(state))
            assert fresh is not None and fresh is not state
            driver._store.put(SESSION, fresh)
        return candidate
    monkeypatch.setattr(driver, method, decide_late)
    if late == 'exception':
        with pytest.raises(RuntimeError, match='late public return failed'):
            driver.drive(body, SESSION, None, log)
    else:
        out = driver.drive(body, SESSION, None, log)
        if late == 'retained':
            assert out is staged[0]
            assert out['choices'][0]['message']['tool_calls'] == [{'id': 's', 'type': 'function',
                'function': {'name': 'web_fetch', 'arguments': '{"url": "https://api.handle.me/openapi.json"}'}}]
        elif late == 'none':
            assert out is None
    assert len(posted) == 1 and len(questions) == 1
    assert webfetch.was_substituted(SESSION, URL) is (late == 'retained')
    assert [(event, fields) for event, fields in log.events if event == 'loop.search_query_judged'] == (
        [('loop.search_query_judged', {'action': 'fetch', 'query': QUERY, 'rec': URL})] if late == 'retained' else [])
    assert state.semantic_pending is None
    assert driver._store.get(SESSION).semantic_pending is None


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('cache_origin', ['born-empty', 'loaded-owner-manual-plain'])
def test_public_discarded_positive_rehunt_earns_first_retained_grant_without_reasking(monkeypatch, tmp_path, synthetic, cache_origin):
    webfetch.set_visible(SESSION, [], [PRIOR])
    views = []
    def execute(source, state):
        views.append(state)
        return policy.REHUNT.execute(source, state)
    chosen = replace(policy.REHUNT, execute=execute)
    driver, state, body, questions, posted = rig(monkeypatch,
        runtime(rehunt=chosen, disabled=(policy.QUERY.policy.id,)), synthetic=synthetic,
        answer={'new_direction': True})
    original_records = None
    if cache_origin == 'loaded-owner-manual-plain':
        path = tmp_path / 'existing-session.json'
        store = loop.LoopStore(str(path))
        store.put(SESSION, state)
        loaded = loop.LoopStore(str(path))
        state = loaded.get(SESSION)
        assert state is not None and state.rehunt_verdicts is None
        # Durable caches are intentionally absent. This is an explicit legacy
        # LIVE plain-cache installation on a genuinely reloaded owner, not a
        # claim that the JSON codec restored transient judgment/grant state.
        original_records = {'previous unrelated query': False}
        state.rehunt_verdicts = original_records
        assert loaded.get(SESSION).rehunt_verdicts is original_records
        driver._store = loaded
    method = '_drive_single_item' if synthetic else '_work'
    original = getattr(driver, method)
    candidates = []
    def discard_first(*args, **kwargs):
        candidate = original(*args, **kwargs)
        candidates.append(candidate)
        return None if len(candidates) == 1 else candidate
    monkeypatch.setattr(driver, method, discard_first)
    log = _Rlog()
    assert driver.drive(body, SESSION, None, log) is None
    assert state.semantic_pending is None
    expected_records = ({'previous unrelated query': False, QUERY: True}
                        if original_records is not None else {QUERY: True})
    assert state.rehunt_verdicts == expected_records
    cache = state.rehunt_verdicts
    assert len(questions) == 1 and len(posted) == 1
    assert webfetch.gate_search(SESSION, QUERY) is not None
    assert not any(event == 'loop.search_rehunt_cleared' for event, _ in log.events)

    retained = driver.drive(body, SESSION, None, log)
    assert retained is candidates[1]
    assert retained['choices'][0]['message']['tool_calls'] == search_completion()['choices'][0]['message']['tool_calls']
    assert state.rehunt_verdicts is cache and cache == expected_records
    assert state.semantic_pending is None
    assert len(questions) == 1 and len(posted) == 2
    # Knowledge survived the discarded turn, but no grant was spent there.
    assert webfetch.gate_search(SESSION, QUERY) is None
    assert webfetch.gate_search(SESSION, QUERY) is not None
    assert [(event, fields) for event, fields in log.events if event == 'loop.search_rehunt_cleared'] == [
        ('loop.search_rehunt_cleared', {'query': QUERY, 'prior': PRIOR.lower()})]

    driver.drive(body, SESSION, None, log)
    assert len(questions) == 1 and len(posted) == 3
    assert state.rehunt_verdicts is cache
    assert webfetch.gate_search(SESSION, QUERY) is not None
    assert sum(event == 'loop.search_rehunt_cleared' for event, _ in log.events) == 1
    assert all(view.verdicts is state.rehunt_verdicts for view in views)
    if original_records is not None:
        assert cache is not original_records
        assert cache.records is original_records
        assert original_records == expected_records
        original_records['alias write'] = False
        assert cache['alias write'] is False
        cache['facade write'] = False
        assert original_records['facade write'] is False
        assert views[-1].verdicts is cache


@pytest.mark.parametrize('synthetic', [False, True])
def test_public_rehunt_changed_call_id_cannot_settle_or_spend_first_grant(monkeypatch, synthetic):
    webfetch.set_visible(SESSION, [], [PRIOR])
    settlements = []
    def settle(result, coder, session, log):
        settlements.append((result, coder))
        return policy.REHUNT.settle(result, coder, session, log)
    chosen = replace(policy.REHUNT, settle=settle)
    driver, state, body, questions, posted = rig(monkeypatch,
        runtime(rehunt=chosen, disabled=(policy.QUERY.policy.id,)), synthetic=synthetic,
        answer={'new_direction': True})
    method = '_drive_single_item' if synthetic else '_work'
    original = getattr(driver, method)
    candidates = []
    def change_only_first_call_id(*args, **kwargs):
        candidate = original(*args, **kwargs)
        candidates.append(candidate)
        if len(candidates) < 3:
            assert state.semantic_pending is not None
            assert state.semantic_pending.rehunt_call == ('s', QUERY)
        else:
            assert state.semantic_pending is None
        if len(candidates) == 1:
            call = candidate['choices'][0]['message']['tool_calls'][0]
            assert call['id'] == 's'
            call['id'] = 'different-unjudged-call'
            assert state.semantic_pending.rehunt_call == ('s', QUERY)
        return candidate
    monkeypatch.setattr(driver, method, change_only_first_call_id)
    log = _Rlog()
    first = driver.drive(body, SESSION, None, log)
    assert first is candidates[0]
    assert first['choices'][0]['message']['tool_calls'] == [{'id': 'different-unjudged-call',
        'type': 'function', 'function': {'name': 'web_search', 'arguments': json.dumps({'query': QUERY})}}]
    assert settlements == []
    assert len(questions) == 1 and len(posted) == 1
    assert state.semantic_pending is None and state.rehunt_verdicts == {QUERY: True}
    cache = state.rehunt_verdicts
    assert webfetch.gate_search(SESSION, QUERY) is not None
    assert not any(event == 'loop.search_rehunt_cleared' for event, _ in log.events)

    retained = driver.drive(body, SESSION, None, log)
    assert retained is candidates[1]
    assert retained['choices'][0]['message']['tool_calls'] == search_completion()['choices'][0]['message']['tool_calls']
    assert len(settlements) == 1 and settlements[0][1] is retained
    assert settlements[0][0].clearance_requested is True
    assert state.rehunt_verdicts is cache and cache == {QUERY: True}
    assert state.semantic_pending is None
    assert len(questions) == 1 and len(posted) == 2
    assert webfetch.gate_search(SESSION, QUERY) is None
    assert webfetch.gate_search(SESSION, QUERY) is not None
    driver.drive(body, SESSION, None, log)
    assert len(questions) == 1 and len(posted) == 3
    assert len(settlements) == 1
    assert webfetch.gate_search(SESSION, QUERY) is not None
    assert [(event, fields) for event, fields in log.events if event == 'loop.search_rehunt_cleared'] == [
        ('loop.search_rehunt_cleared', {'query': QUERY, 'prior': PRIOR.lower()})]


@pytest.mark.parametrize('promote', [False, True])
def test_public_historical_positive_unknown_spend_never_invents_a_grant(monkeypatch, promote):
    webfetch.set_visible(SESSION, [], [PRIOR])
    fresh_query = QUERY + ' lookup'
    replies = ([search_completion(fresh_query)] if promote else []) + [search_completion()]
    driver, state, body, questions, posted = rig(monkeypatch,
        runtime(disabled=(policy.QUERY.policy.id,)), answer={'new_direction': True}, coder_replies=replies)
    records = {QUERY: True}
    state.rehunt_verdicts = records
    log = _Rlog()
    if promote:
        driver.drive(body, SESSION, None, log)
        facade = state.rehunt_verdicts
        assert facade is not records and facade.records is records
        assert records == {QUERY: True, fresh_query: True}
        assert webfetch.gate_search(SESSION, fresh_query) is None
        assert webfetch.gate_search(SESSION, fresh_query) is not None
    retained = driver.drive(body, SESSION, None, log)
    assert retained['choices'][0]['message']['tool_calls'] == search_completion()['choices'][0]['message']['tool_calls']
    assert len(questions) == (1 if promote else 0)
    assert len(posted) == (2 if promote else 1)
    assert webfetch.gate_search(SESSION, QUERY) is not None
    assert state.semantic_pending is None
    if not promote:
        assert state.rehunt_verdicts is records
        assert records == {QUERY: True}
    else:
        assert state.rehunt_verdicts is facade and facade.records is records
    assert [(event, fields) for event, fields in log.events if event == 'loop.search_rehunt_cleared'] == (
        [('loop.search_rehunt_cleared', {'query': fresh_query, 'prior': PRIOR.lower()})] if promote else [])


def test_public_cached_rehunt_respects_selected_execute_clearance_veto(monkeypatch):
    webfetch.set_visible(SESSION, [], [PRIOR])
    evaluated = []
    def execute(source, state):
        result = policy.REHUNT.execute(source, state)
        evaluated.append(result)
        return replace(result, clearance_requested=False)
    chosen = replace(policy.REHUNT, execute=execute)
    driver, state, body, questions, posted = rig(monkeypatch,
        runtime(rehunt=chosen, disabled=(policy.QUERY.policy.id,)), answer={'new_direction': True})
    log = _Rlog()
    for _ in range(2):
        driver.drive(body, SESSION, None, log)
        assert webfetch.gate_search(SESSION, QUERY) is not None
        assert state.semantic_pending is None
    assert [result.clearance_requested for result in evaluated] == [True, True]
    assert len(questions) == 1 and len(posted) == 2
    assert state.rehunt_verdicts == {QUERY: True}
    assert not any(event == 'loop.search_rehunt_cleared' for event, _ in log.events)


def test_public_rehunt_settlement_veto_does_not_spend_ungranted_eligibility(monkeypatch):
    webfetch.set_visible(SESSION, [], [PRIOR])
    settlements = []
    def settle(result, coder, session, log):
        settlements.append(result)
        if len(settlements) == 1:
            return False
        return policy.REHUNT.settle(result, coder, session, log)
    chosen = replace(policy.REHUNT, settle=settle)
    driver, state, body, questions, posted = rig(monkeypatch,
        runtime(rehunt=chosen, disabled=(policy.QUERY.policy.id,)), answer={'new_direction': True})
    log = _Rlog()
    driver.drive(body, SESSION, None, log)
    assert webfetch.gate_search(SESSION, QUERY) is not None
    driver.drive(body, SESSION, None, log)
    assert webfetch.gate_search(SESSION, QUERY) is None
    assert webfetch.gate_search(SESSION, QUERY) is not None
    driver.drive(body, SESSION, None, log)
    assert webfetch.gate_search(SESSION, QUERY) is not None
    assert len(questions) == 1 and len(posted) == 3
    assert len(settlements) == 2 and all(result.clearance_requested for result in settlements)
    assert state.semantic_pending is None
    assert state.rehunt_verdicts == {QUERY: True}
    assert sum(event == 'loop.search_rehunt_cleared' for event, _ in log.events) == 1


@pytest.mark.parametrize('reverse', [False, True])
def test_public_question_order_does_not_follow_registration_accident(monkeypatch, reverse):
    webfetch.set_visible(SESSION, [], [PRIOR])
    driver, state, body, questions, posted = rig(monkeypatch, runtime(reverse=reverse),
        answer={'new_direction': False, 'on_target': True})
    driver.drive(body, SESSION, None, _Rlog())
    assert len(posted) == 1
    assert [q['messages'][0]['content'] for q in questions] == [
        prompts.load('search_rehunt_judge'), prompts.load('search_query_judge')]
    assert state.rehunt_verdicts == {QUERY: False} and state.query_verdicts == {QUERY: (True, '')}
    assert webfetch.gate_search(SESSION, QUERY) is not None


def test_public_repeat_owner_none_leaves_relevance_independently_enabled(monkeypatch):
    webfetch.set_visible(SESSION, [], [PRIOR])
    driver, state, body, questions, posted = rig(monkeypatch,
        runtime(disabled=(researchpolicies.SEARCH.policy.id,)),
        answer={'new_direction': True, 'on_target': False, 'recommendation': 'Ada Handle API'})
    log = _Rlog()
    out = driver.drive(body, SESSION, None, log)
    assert len(posted) == 1
    assert [q['messages'][0]['content'] for q in questions] == [prompts.load('search_query_judge')]
    assert state.rehunt_verdicts is None and state.query_verdicts == {QUERY: (False, 'Ada Handle API')}
    assert bodykeys.NOTES in out
    assert not any(event == 'loop.search_rehunt_cleared' for event, _ in log.events)


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('late', ['retained', 'none', 'replacement', 'exception', 'equal-copy'])
def test_fresh_public_owner_settles_or_discards_with_existing_persistence_contract(monkeypatch, tmp_path, late, synthetic):
    driver, seeded, body, questions, posted = rig(monkeypatch,
        runtime(disabled=(policy.REHUNT.policy.id,), experimental_planning=not synthetic),
        answer={'on_target': True, 'recommendation': URL})
    # Use a genuinely empty real Store. No pre-seeded session participates in
    # creation, ownership discovery, retention or cancellation for this request.
    state_path = tmp_path / 'unstable-sessions.json'
    store = loop.LoopStore(str(state_path))
    driver._store = store
    key = loop.session_key({}, body['messages'])
    assert not loop._stable_session(key)
    assert store.get(key) is None
    webfetch.reset_session(key)
    classification = classify.Classification(engagement='task', task_type='coding',
        reason='Explicit synthetic coding classification for the real fresh-session creation path.')
    planner_calls = []
    class ScriptedPlanner:
        def plan_for(self, messages, log, **frame):
            planner_calls.append(deepcopy(messages))
            return Plan(id='fresh-step-owner', task=TASK, created='fixture',
                        items=[PlanItem('Read the current API documentation.')])
    if not synthetic:
        from test_loop import _SHELL
        driver._ctx.planner_enabled = True  # explicit opt-in for this STEP fixture only
        driver._ctx.planner = ScriptedPlanner()
        body['tools'].append(deepcopy(_SHELL))
    original = driver._drive_single_item if synthetic else driver._work
    owners, candidates = [], []
    log = _Rlog()
    def observe_fresh_owner(owner, *args, **kwargs):
        assert owner is not seeded
        if synthetic:
            assert store.get(key) is None
        else:
            assert store.get(key) is owner
            assert owner.plan.id == 'fresh-step-owner'
        owners.append(owner)
        candidate = original(owner, *args, **kwargs)
        candidates.append(candidate)
        assert owner.semantic_pending is not None
        assert owner.semantic_pending.coder is candidate
        assert not webfetch.was_substituted(key, URL)
        assert not any(event == 'loop.search_query_judged' for event, _ in log.events)
        if late == 'none':
            return None
        if late == 'replacement':
            return search_completion('replacement-owned search')
        if late == 'equal-copy':
            return deepcopy(candidate)
        if late == 'exception':
            raise RuntimeError('fresh ephemeral public return failed')
        return candidate
    monkeypatch.setattr(driver, '_drive_single_item' if synthetic else '_work', observe_fresh_owner)
    token = wsview.bind(wsview.View(None))
    try:
        if late == 'exception':
            with pytest.raises(RuntimeError, match='fresh ephemeral public return failed'):
                driver.drive(body, key, classification, log)
        else:
            out = driver.drive(body, key, classification, log)
            if late == 'retained':
                assert out is candidates[0]
                assert out['choices'][0]['message']['tool_calls'] == [{'id': 's', 'type': 'function',
                    'function': {'name': 'web_fetch', 'arguments': '{"url": "https://api.handle.me/openapi.json"}'}}]
            elif late == 'none':
                assert out is None
            elif late == 'equal-copy':
                assert out is not candidates[0]
                assert out['choices'] == candidates[0]['choices']
            else:
                assert out['choices'][0]['message']['tool_calls'] == search_completion('replacement-owned search')['choices'][0]['message']['tool_calls']
        assert len(owners) == 1 and len(candidates) == 1
        assert len(planner_calls) == (0 if synthetic else 1)
        assert len(posted) == 1 and len(questions) == 1
        assert owners[0].semantic_pending is None
        assert owners[0].query_verdicts == {QUERY: (True, URL)}
        assert webfetch.was_substituted(key, URL) is (late == 'retained')
        assert [(event, fields) for event, fields in log.events if event == 'loop.search_query_judged'] == (
            [('loop.search_query_judged', {'action': 'fetch', 'query': QUERY, 'rec': URL})] if late == 'retained' else [])
        if synthetic:
            assert store.get(key) is None
            assert not state_path.exists()
        else:
            assert store.get(key) is owners[0]
            assert state_path.exists()
            durable = json.loads(state_path.read_text())['sessions'][key]
            assert durable['plan']['id'] == 'fresh-step-owner'
            for transient in ('semantic_pending', 'query_verdicts', 'rehunt_verdicts'):
                assert transient not in durable
    finally:
        wsview.unbind(token)
        webfetch.reset_session(key)


@pytest.mark.parametrize('definition,field', [
    (policy.QUERY, 'execute'), (policy.QUERY, 'deliver'),
    (policy.QUERY, 'stage'), (policy.QUERY, 'settle'),
    (policy.REHUNT, 'execute'), (policy.REHUNT, 'settle')])
def test_registration_rejects_missing_selected_lifecycle_callback(definition, field):
    malformed = replace(definition, **{field: None})
    with pytest.raises(ValueError):
        if definition is policy.QUERY:
            runtime(query=malformed)
        else:
            runtime(rehunt=malformed)


def test_public_url_substitution_does_not_leave_unused_search_clearance(monkeypatch):
    webfetch.set_visible(SESSION, [], [PRIOR])
    driver, state, body, questions, posted = rig(monkeypatch, runtime(),
        answer={'new_direction': True, 'on_target': True, 'recommendation': URL})
    log = _Rlog()
    out = driver.drive(body, SESSION, None, log)
    assert out['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'web_fetch'
    assert len(questions) == 2 and len(posted) == 1
    assert webfetch.was_substituted(SESSION, URL)
    assert webfetch.gate_search(SESSION, QUERY) is not None
    assert not any(event == 'loop.search_rehunt_cleared' for event, _ in log.events)


def test_public_relevance_receives_real_fetch_and_loader_refusal_authority(monkeypatch):
    driver, state, body, questions, posted = rig(monkeypatch,
        runtime(disabled=(policy.REHUNT.policy.id,)), answer={'on_target': True})
    fetched = {'https://rubygems.org/gems/eu_countries': (200, '')}
    state.fetched_pages = fetched
    ledger = refusalledger.RefusalLedger([refusalledger.RefusalEvent(
        ecosystem='rubygems', raw_coordinate='eu_countries', package='eu_countries', version='',
        outcome=refusalledger.REFUSED, evidence='cannot load such file -- iso3166', sequence=1)])
    state.refusal_events = ledger
    out = driver.drive(body, SESSION, None, _Rlog())
    assert len(posted) == 1 and len(questions) == 1
    question = questions[0]['messages'][-1]['content']
    assert 'eu_countries' in question and '200' in question
    assert 'could not install or load' in question.lower()
    assert state.refusal_events is ledger
    assert state.fetched_pages == fetched
    assert bodykeys.NOTES not in out
    assert state.query_verdicts == {QUERY: (True, '')}


def test_public_new_task_owner_does_not_inherit_previous_query_cache(monkeypatch):
    driver, old, body, questions, posted = rig(monkeypatch,
        runtime(disabled=(policy.REHUNT.policy.id,)))
    driver.drive(body, SESSION, None, _Rlog())
    old_cache = old.query_verdicts
    next_task = 'Read the current API documentation at api.handle.me for the next task.'
    fresh = loop._plan_off_session(loop._synthetic_plan(next_task), '')
    assert fresh.query_verdicts is None and fresh.rehunt_verdicts is None
    driver._store.drop(SESSION)
    driver._store.put(SESSION, fresh)
    body['messages'] = [{'role': 'user', 'content': next_task}]
    driver.drive(body, SESSION, None, _Rlog())
    assert len(questions) == 2 and len(posted) == 2
    assert old.query_verdicts is old_cache
    assert fresh.query_verdicts == {QUERY: (False, 'Ada Handle API')}
    assert fresh.query_verdicts is not old_cache
    assert fresh.semantic_pending is None and old.semantic_pending is None


def test_live_cache_reference_reset_and_real_store_durable_cleanliness(monkeypatch, tmp_path):
    driver, state, body, questions, posted = rig(monkeypatch, runtime(),
        answer={'on_target': False, 'recommendation': 'Ada Handle API'})
    driver.drive(body, SESSION, None, _Rlog())
    cache = state.query_verdicts
    store = loop.LoopStore(str(tmp_path / 'sessions.json'))
    store.put(SESSION, state)
    store.persist(SESSION)
    assert store.get(SESSION) is state
    assert store.get(SESSION).query_verdicts is cache
    encoded = json.loads((tmp_path / 'sessions.json').read_text())
    for name in ('query_verdicts', 'rehunt_verdicts', 'semantic_pending'):
        assert name not in encoded['sessions'][SESSION]
    restored = loop.LoopStore(str(tmp_path / 'sessions.json')).get(SESSION)
    assert restored is not state
    assert restored.query_verdicts is None and restored.rehunt_verdicts is None and restored.semantic_pending is None
    state.fetched_pages = {'https://api.handle.me/': ('HTTP 200', '')}
    policy.reset_turn(state)
    assert state.query_verdicts is None and state.rehunt_verdicts is None and state.semantic_pending is None
    assert state.fetched_pages == {'https://api.handle.me/': ('HTTP 200', '')}
    driver.drive(body, SESSION, None, _Rlog())
    assert len(questions) == 2 and len(posted) == 2
    assert state.query_verdicts == {QUERY: (False, 'Ada Handle API')}
    store.drop(SESSION)
    store.put(SESSION, restored)
    assert store.get(SESSION).query_verdicts is None
