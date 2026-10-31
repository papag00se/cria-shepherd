"""Selected new-direction clearance and retained public-driver delivery; scripted primitives only."""
from copy import deepcopy
from dataclasses import replace
import io
import json
import pytest
from cria import assistruntime, bodykeys, classify, config, loop, prompts, semanticquery as policy, webfetch, wsview
from cria.plan import Plan, PlanItem
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog


TASK = 'resolve an Ada Handle via the API (api.handle.me)'


QUERY = 'ADA Handle API resolve handle holder'


PRIOR = 'ADA Handle API resolve handle to address holder address total handles'


SESSION = 'driver-fixture'


def runtime(*, rehunt=policy.REHUNT, level=5, disabled=(), experimental_planning=False):
    owned = {d.policy.id for d in policy.DEFINITIONS}
    registrations = tuple(d for d in assistruntime.DEFINITIONS if d.policy.id not in owned) + (rehunt,)
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
        verdict = ({'new_direction': False} if answer is None else answer)
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
@pytest.mark.parametrize('mode', ['disabled', 'below-level'])
def test_public_absence_runs_no_question_or_optional_cache_work(monkeypatch, synthetic, mode):
    root = runtime(level=4 if mode == 'below-level' else 5,
        disabled=tuple(d.policy.id for d in policy.DEFINITIONS) if mode == 'disabled' else ())
    driver, state, body, questions, posted = rig(monkeypatch, root, synthetic=synthetic)
    out = driver.drive(body, SESSION, None, _Rlog())
    assert len(posted) == 1
    assert out['choices'][0]['message']['tool_calls'] == search_completion()['choices'][0]['message']['tool_calls']
    assert questions == []
    assert bodykeys.NOTES not in out
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
        runtime(rehunt=chosen), synthetic=synthetic,
        answer={'new_direction': True})
    out = driver.drive(body, SESSION, None, _Rlog())
    assert [item[0] for item in seen] == ['execute', 'settle']
    assert seen[0][2].verdicts is state.rehunt_verdicts
    assert seen[1][2] is out
    assert len(questions) == 1 and len(posted) == 1
    assert questions[0]['messages'][0]['content'] == prompts.load('search_rehunt_judge')
    assert webfetch.gate_search(SESSION, QUERY) is None
    assert webfetch.gate_search(SESSION, QUERY) is not None
    assert state.semantic_pending is None


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
        runtime(rehunt=chosen), synthetic=synthetic,
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
        runtime(rehunt=chosen), synthetic=synthetic,
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
        runtime(), answer={'new_direction': True}, coder_replies=replies)
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
        runtime(rehunt=chosen), answer={'new_direction': True})
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
        runtime(rehunt=chosen), answer={'new_direction': True})
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



@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('late', ['retained', 'none', 'replacement', 'exception', 'equal-copy'])
def test_fresh_public_owner_settles_or_discards_with_existing_persistence_contract(monkeypatch, tmp_path, late, synthetic):
    driver, seeded, body, questions, posted = rig(monkeypatch,
        runtime(experimental_planning=not synthetic),
        answer={'new_direction': True})
    # Use a genuinely empty real Store. No pre-seeded session participates in
    # creation, ownership discovery, retention or cancellation for this request.
    state_path = tmp_path / 'unstable-sessions.json'
    store = loop.LoopStore(str(state_path))
    driver._store = store
    key = loop.session_key({}, body['messages'])
    assert not loop._stable_session(key)
    assert store.get(key) is None
    webfetch.set_visible(key, [], [PRIOR])
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
        assert webfetch.gate_search(key, QUERY) is not None
        assert not any(event == 'loop.search_rehunt_cleared' for event, _ in log.events)
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
                assert out['choices'][0]['message']['tool_calls'] == search_completion()['choices'][0]['message']['tool_calls']
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
        assert owners[0].rehunt_verdicts == {QUERY: True}
        assert (webfetch.gate_search(key, QUERY) is None) is (late == 'retained')
        assert webfetch.gate_search(key, QUERY) is not None
        assert [(event, fields) for event, fields in log.events if event == 'loop.search_rehunt_cleared'] == (
            [('loop.search_rehunt_cleared', {'query': QUERY, 'prior': PRIOR.lower()})] if late == 'retained' else [])
        if synthetic:
            assert store.get(key) is None
            assert not state_path.exists()
        else:
            assert store.get(key) is owners[0]
            assert state_path.exists()
            durable = json.loads(state_path.read_text())['sessions'][key]
            assert durable['plan']['id'] == 'fresh-step-owner'
            for transient in ('semantic_pending', 'rehunt_verdicts'):
                assert transient not in durable
    finally:
        wsview.unbind(token)
        webfetch.reset_session(key)
