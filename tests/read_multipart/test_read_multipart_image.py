"""Images: the original stays private until a COMPLETED observation by the actual coder route correlates with the exact occurrence; later
context carries a labelled, fallible account plus a reinspection reference; unknown capability fails explicitly."""
import copy
import json
from dataclasses import replace
import pytest
from cria import bodykeys
from cria.imageprotocol import CoderRoute, Delivery, ImageUnavailable, parse_observation
from cria.imagestore import ImageStore

IMAGE = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA', 'detail': 'high'}}
TASK = 'Read the button labels and reproduce the layout.'
OBS = {'viewed': True, 'extracted_text': 'Save\nCancel', 'description': 'Two adjacent buttons.', 'uncertainty': 'Colors may vary.'}

def completion(**changes): return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps({**OBS, **changes})}}]}

def delivered(attempt, route, answer=None, terminal=True):
    return Delivery.from_wire(attempt.nonce, route.provider, route.role_signature, attempt.request, answer or completion(), terminal_complete=terminal)

@pytest.fixture
def rig(tmp_path):
    store = ImageStore(tmp_path / 'private', close_authority=object()); s = store.session('one')
    route = CoderRoute(object(), 'actual-vision', 'role-sig', True); s.select_route(route)
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': TASK}, copy.deepcopy(IMAGE)]}]
    prepared = s.prepare(messages, TASK)
    return store, s, route, messages, prepared, prepared.bindings[0].ref, {'model': route.model, 'temperature': 0.3, 'tools': [{}], bodykeys.PINNED_TASK: 'x'}, tmp_path

def test_original_is_kept_until_a_completed_observation_then_later_context_carries_a_labelled_account(rig):
    """Pixels stay in context while only the attempt is pending; after completion the later view has the observation, labelled
    historical, with a reinspection ref and no pixels; the same image at another occurrence/session or a remote URL is not cached/over-claimed;
    no/unknown vision fails explicitly and keeps the image."""
    store, s, route, messages, prepared, ref, body, _ = rig
    attempt = s.begin(ref, TASK, route, body)
    assert 'tools' not in attempt.request and bodykeys.PINNED_TASK not in attempt.request and attempt.request['temperature'] == 0.3 and s.render(prepared) == messages
    s.complete(attempt, delivered(attempt, route)); later = s.render(prepared)
    text = later[0]['content'][1]['text']
    assert 'Save\nCancel' in text and 'Historical coder observation' in text and ref in text and 'data:image' not in str(later) and s.reinspect(ref) == IMAGE
    view = s.prepare(messages + [{'role': 'assistant', 'content': 'Earlier.'}, copy.deepcopy(messages[0])], TASK)
    assert view.bindings[1].ref != ref and s.render(view)[2]['content'][1] == IMAGE
    with pytest.raises(ImageUnavailable): store.session('another').reinspect(ref)
    remote = {'type': 'image_url', 'image_url': {'url': 'https://example.test/a.png?sig=secret'}}
    rp = s.prepare([{'role': 'user', 'content': [{'type': 'text', 'text': TASK}, remote]}], TASK); att = s.begin(rp.bindings[0].ref, TASK, route, body)
    s.complete(att, delivered(att, route)); t = s.render(rp)[0]['content'][1]['text']
    assert 'remote URL reference' in t and 'was not fetched' in t and 'secret' not in t and 'retained privately' not in t
    for cap in (False, None):
        s.select_route(replace(route, vision=cap))
        with pytest.raises(ImageUnavailable, match='capability'): s.begin(ref, TASK, replace(route, vision=cap), body)

@pytest.mark.parametrize('failure', ['incomplete', 'length', 'not-viewed', 'malformed', 'extra-key', 'duplicate-key', 'tool-call'])
def test_a_bad_or_incomplete_observation_never_substitutes_the_original(rig, failure):
    """An unfinished/truncated/refusing/non-JSON/extra-key/duplicate-key answer raises and leaves the pixels and reinspection intact."""
    _, s, route, messages, prepared, ref, body, _ = rig
    attempt = s.begin(ref, TASK, route, body); answer = completion(viewed=False) if failure == 'not-viewed' else completion(extra='x') if failure == 'extra-key' else completion()
    msg = answer['choices'][0]['message']
    if failure == 'length': answer['choices'][0]['finish_reason'] = 'length'
    if failure == 'tool-call': msg['tool_calls'] = [{'id': 'u'}]
    if failure == 'malformed': msg['content'] = 'I think it looks blue'
    if failure == 'duplicate-key': msg['content'] = json.dumps(OBS)[:-1] + ', "viewed": true}'
    with pytest.raises(ImageUnavailable): s.complete(attempt, delivered(attempt, route, answer, terminal=failure != 'incomplete'))
    assert s.render(prepared) == messages and s.reinspect(ref) == IMAGE
    fenced = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '```json\n' + json.dumps(OBS) + '\n```'}}]}
    assert parse_observation(fenced, terminal_complete=True).extracted_text == 'Save\nCancel'     # gemma4_12b answered in a fence

@pytest.mark.parametrize('fault', ['provider', 'model', 'role', 'image', 'nonce', 'route-changed', 'task-changed', 'superseded'])
def test_an_observation_only_counts_when_provider_role_model_image_attempt_and_task_all_correlate(rig, fault):
    """A receipt from another provider/model/role/image/attempt, a changed route or task, or an older concurrent attempt cannot mint an observation."""
    _, s, route, messages, prepared, ref, body, _ = rig
    attempt = s.begin(ref, TASK, route, body); receipt = delivered(attempt, route)
    if fault == 'provider': receipt = replace(receipt, provider=object())
    if fault == 'model': receipt = replace(receipt, model='harness-alias')
    if fault == 'role': receipt = replace(receipt, role_signature='other')
    if fault == 'image': receipt = replace(receipt, image_digest='wrong')
    if fault == 'nonce': receipt = replace(receipt, attempt='stale')
    if fault == 'route-changed': s.select_route(replace(route, provider=object()))
    if fault == 'task-changed': newer = s.prepare(messages, 'Inspect the fine print instead.')
    if fault == 'superseded': s.begin(ref, TASK, route, body)
    with pytest.raises(ImageUnavailable): s.complete(attempt, receipt)
    if fault == 'task-changed':
        with pytest.raises(ImageUnavailable): s.render(prepared)                                               # the older preparation is stale
    assert s.render(newer if fault == 'task-changed' else prepared) == messages
