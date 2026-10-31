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


STATEMENT = "Look at ./note.png and tell me what it says, then summarise it in one sentence."
CLAIM = "The note says Save and Cancel. Summary: two buttons."
APPLIES = "creating or changing files"        # the one deliverable-type question the confirmation asks


def judged(rig, task, *, observed, applies="NO", claim=""):
    """Run the real whole-task judge with a recording provider while the image context is bound; returns (satisfied, kinds, bodies)."""
    import types
    from cria import loop, wsview
    from cria.config import Role
    from cria.imageworkflow import SourceImageContext, current
    _, s, route, messages, prepared, ref, body, tmp = rig
    if observed:
        attempt = s.begin(ref, TASK, route, body)
        s.complete(attempt, delivered(attempt, route))
    kinds, bodies = [], []

    def provider(request, rlog):
        text = json.dumps(request["messages"], ensure_ascii=False)
        bodies.append(text)
        kind, content = (("applies", applies) if APPLIES in text else ("checker", json.dumps({"consistent": False, "why": "not on disk"}))
                         if "VERIFICATION CHECKER" in text else ("judge", json.dumps({"satisfied": True, "reason": "the observation supports it"})))
        kinds.append(kind)
        return json.dumps({"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}).encode()

    class Log:
        def emit(self, *a, **k):
            pass
    view = wsview.View(str(tmp), "image-judge")
    view._ingest_tree("D\t\nF\t72\t1\tnote.png", complete=True)
    tokens = wsview.bind(view), current.set(SourceImageContext(types.SimpleNamespace(), s, prepared, TASK))
    try:
        result = loop.judge_satisfaction(task, "$ view_image {}", provider, Role(name="reasoner", backend="local"), Log(),
                                         workspace_root=str(tmp), messages=messages, closing_claim=claim)
    finally:
        current.reset(tokens[1])
        wsview.unbind(tokens[0])
    return result[0], kinds, bodies


def test_a_statement_about_an_observed_image_skips_the_file_check_and_its_closing_reply_reaches_the_judge_as_a_labelled_claim(rig):
    """The whole-task file confirmation refused every 'tell me what the image says' turn until the completion-check bound (16/16 replays,
    ornith1.5_9b) because nothing on disk can confirm it (3be0f879); the closing reply is that task's deliverable and the action log
    never holds it, so it rides as a LABELLED claim checked against the observation, only where an observation exists (d2387d9a)."""
    satisfied, kinds, bodies = judged(rig, STATEMENT, observed=True, claim=CLAIM)
    assert satisfied is True and "checker" not in kinds and kinds.count("applies") == 1
    first = bodies[0]
    assert "a claim made by the coder, not evidence" in first and "Summary: two buttons." in first


def test_an_unobserved_image_or_a_task_that_writes_a_file_keeps_the_full_confirmation_and_no_closing_claim(rig, tmp_path):
    """No completed observation: nothing can ground the claim and the brake stays; a task that also writes a file answers YES (or
    unreadably) and keeps the file check."""
    satisfied, kinds, bodies = judged(rig, STATEMENT, observed=False, claim=CLAIM)
    assert satisfied is False and "checker" in kinds and "applies" not in kinds
    assert not any("THE CODER'S CLOSING REPLY" in b or "Summary: two buttons." in b for b in bodies)
    for applies in ("YES", "garbled"):
        satisfied, kinds, _ = judged(rig, "Look at ./note.png, then write what it says into ./out.txt.", observed=True, applies=applies)
        assert satisfied is False and "checker" in kinds
