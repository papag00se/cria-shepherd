"""Removing a search judge must not remove independent repeat admission or raw facts."""
from copy import deepcopy
import io
import json

import pytest

from cria import assistruntime, bodykeys, config, loop, prompts, webfetch
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog

TASK = 'Resolve an Ada Handle via api.handle.me'
QUERY = 'ADA Handle API resolve handle holder'
PRIOR = 'ADA Handle API resolve handle to address holder address total handles'
SESSION = 'driver-fixture'
URL = 'https://api.handle.me/openapi.json'


def search_completion(query=QUERY):
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
        'tool_calls': [{'id': 's', 'type': 'function', 'function': {
            'name': 'web_search', 'arguments': json.dumps({'query': query})}}]}}]}


def rig(monkeypatch, *, synthetic, answer, root=None, query=QUERY):
    driver, state, body = setup_driver()
    state.synthetic = state.plan_off = synthetic
    state.plan.task = state.plan.items[0].text = body['messages'][0]['content'] = TASK
    body['tools'] += [{'type': 'function', 'function': {'name': name,
        'parameters': {'type': 'object', 'properties': {arg: {'type': 'string'}}, 'required': [arg]}}}
        for name, arg in [('web_search', 'query'), ('web_fetch', 'url')]]
    driver._ctx.pilot_runtime = root or assistruntime.AssistRuntime.select(experimental_planning=not synthetic)
    driver._ctx.assists = True
    driver._ctx.reasoner_role = config.Role(name='reasoner', backend='local')
    questions = []
    def reasoner(frame, log):
        questions.append(deepcopy(frame))
        return json.dumps({'choices': [{'message': {'role': 'assistant', 'content': json.dumps(answer)}}]}).encode()
    driver._ctx.reasoner_chat = reasoner
    def transport(request, **options):
        if request.full_url.endswith('/v1/chat/completions'):
            return io.BytesIO(json.dumps(search_completion(query)).encode())
        if request.full_url.endswith('/tokenize'):
            return io.BytesIO(b'{"tokens":[1,2,3]}')
        return io.BytesIO(b'{"data":[]}')
    monkeypatch.setattr(driver._ctx.coder_chat.__self__, '_receive_open', transport)
    return driver, state, body, questions


@pytest.fixture(autouse=True)
def clear_research():
    webfetch.reset_session(SESSION)
    yield
    webfetch.reset_session(SESSION)


@pytest.mark.parametrize('synthetic', [False, True])
@pytest.mark.parametrize('on_target', [False, True])
def test_normal_search_reaches_public_return_unchanged_despite_url_recommendation(monkeypatch, synthetic, on_target):
    driver, state, body, questions = rig(monkeypatch, synthetic=synthetic,
        answer={'on_target': on_target, 'recommendation': URL})
    out = driver.drive(body, SESSION, None, _Rlog())
    assert out['choices'][0]['message']['tool_calls'] == search_completion()['choices'][0]['message']['tool_calls']
    assert bodykeys.NOTES not in out
    assert questions == []
    assert state.semantic_pending is None


@pytest.mark.parametrize('synthetic', [False, True])
def test_new_direction_clearance_still_uses_rehunt_not_relevance(monkeypatch, synthetic):
    webfetch.set_visible(SESSION, [], [PRIOR])
    driver, state, body, questions = rig(monkeypatch, synthetic=synthetic,
        answer={'new_direction': True, 'on_target': True, 'recommendation': URL})
    out = driver.drive(body, SESSION, None, _Rlog())
    assert out['choices'][0]['message']['tool_calls'] == search_completion()['choices'][0]['message']['tool_calls']
    assert len(questions) == 1
    assert questions[0]['messages'][0]['content'] == prompts.load('search_rehunt_judge')
    assert webfetch.gate_search(SESSION, QUERY) is None
    assert webfetch.gate_search(SESSION, QUERY) is not None
    assert state.rehunt_verdicts == {QUERY: True} and state.semantic_pending is None


def test_removed_relevance_id_is_rejected_by_config_not_silently_disabled(tmp_path):
    path = tmp_path/'removed.toml'
    path.write_text('[assists]\ndisabled = ["outgoing-search-relevance"]\n')
    with pytest.raises(ValueError, match='[Uu]nknown'):
        config.Config.load(path)
