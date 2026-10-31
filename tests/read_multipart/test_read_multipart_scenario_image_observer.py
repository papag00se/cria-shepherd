"""Image observation receipts and workspace read provenance: only the actual dispatch that carried the exact occurrence, and only the
harness result of cria's own issued read, can mint an observation; every deviation is an explicit ImageUnavailable."""
import copy
import json
from types import SimpleNamespace
import pytest
from cria.imageobserver import ObservationCallbacks
from cria.imageprotocol import ImageUnavailable
from cria.imageworkspace import ImageWorkspace, WorkspaceImageTool
from test_read_multipart_image import IMAGE, TASK, completion, delivered, rig  # noqa: F401  (rig is the shared fixture)


def receipt_for(cb, attempt, route, **change):
    wire = change.pop('final_wire', json.dumps(attempt.request).encode())
    return SimpleNamespace(**{'owner_token': cb.owner_token, 'dispatch_token': object(), 'provider': route.provider, 'model': route.model,
                              'role_signature': route.role_signature, 'final_wire': wire, **change})

@pytest.mark.parametrize('fault', ['owner', 'token', 'provider', 'model', 'bytes', 'json', 'image-lost', 'task-lost', 'stale', 'cancelled', 'reused'])
def test_a_dispatch_receipt_must_be_the_producers_actual_wire_for_this_exact_attempt(rig, fault):  # noqa: F811
    """started() refuses a receipt from another owner/token/provider/model, a non-bytes or non-JSON wire, a wire that lost the image or
    the governing task, a superseded attempt, a cancelled observer or a reused dispatch token; the honest receipt completes."""
    _, s, route, _, _, ref, body, _ = rig
    attempt = s.begin(ref, TASK, route, body); cb = ObservationCallbacks(s, attempt); wire = copy.deepcopy(attempt.request)
    change = {'owner': {'owner_token': object()}, 'token': {'dispatch_token': 1}, 'provider': {'provider': object()}, 'model': {'model': 'alias'},
              'bytes': {'final_wire': 'text'}, 'json': {'final_wire': b'{'}}.get(fault, {})
    if fault == 'image-lost': wire['messages'][1]['content'] = wire['messages'][1]['content'][:1]
    if fault == 'task-lost': wire['messages'][0]['content'] = 'something else'
    if fault in ('image-lost', 'task-lost'): change = {'final_wire': json.dumps(wire).encode()}
    receipt = receipt_for(cb, attempt, route, **change)
    if fault == 'stale': s.begin(ref, TASK, route, body)
    if fault == 'cancelled': cb.cancel()
    if fault == 'reused': cb.started(receipt)
    with pytest.raises(ImageUnavailable): cb.started(receipt)
    with pytest.raises(ImageUnavailable): cb.result()
    assert s.reinspect(ref) == IMAGE and 'data:image' in json.dumps(s.render(rig[4]))


@pytest.mark.parametrize('end', ['complete', 'incomplete', 'foreign-receipt', 'twice', 'bad-answer', 'nothing'])
def test_a_terminal_event_completes_only_the_active_dispatch_once_and_only_when_complete(rig, end):  # noqa: F811
    """The observation lands on a complete terminal event of the active dispatch; an unfinished stream, another receipt, a replayed
    terminal or an unviewable answer leaves the original pending and reports why; no event at all is also explicit."""
    _, s, route, _, prepared, ref, body, _ = rig
    attempt = s.begin(ref, TASK, route, body); cb = ObservationCallbacks(s, attempt); receipt = receipt_for(cb, attempt, route)
    if end != 'nothing': cb.started(receipt)
    answer = completion(viewed=False) if end == 'bad-answer' else completion()
    if end == 'foreign-receipt':
        with pytest.raises(ImageUnavailable): cb.completed(receipt_for(cb, attempt, route), answer, True)
    elif end == 'bad-answer':
        with pytest.raises(ImageUnavailable): cb.completed(receipt, answer, True)
    elif end != 'nothing':
        cb.completed(receipt, answer, end != 'incomplete')
    if end == 'twice':
        with pytest.raises(ImageUnavailable): cb.completed(receipt, answer, True)
    if end == 'complete' or end == 'twice': assert cb.result().extracted_text == 'Save\nCancel' and s.observed(prepared)
    else:
        with pytest.raises(ImageUnavailable): cb.result()
        assert not s.observed(prepared)
    cb.cancel(); cb.cancel()


def workspace(rig, tools=None):  # noqa: F811
    ws = ImageWorkspace(WorkspaceImageTool('view_image', 'path'))
    schema = {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}
    return ws, tools or [{'type': 'function', 'function': {'name': 'view_image', 'parameters': schema}}]

def issued(call_id, args):
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': call_id, 'type': 'function', 'function': {'name': 'view_image', 'arguments': args if isinstance(args, str) else json.dumps(args)}}]}}]}

@pytest.mark.parametrize('fault', ['ambiguous-tool', 'schema', 'unfinished', 'bad-json', 'extra-arg', 'empty-path'])
def test_workspace_image_reads_are_only_issued_for_an_unambiguous_path_only_harness_tool(rig, fault):  # noqa: F811
    """A tool contract is required (empty name refused); two same-named tools or a schema that cannot take a bare path make the read unavailable; an unfinished
    action or arguments that are not exactly {path: non-empty str} are refused; a good read is persisted under cria's own id."""
    s = rig[1]; ws, tools = workspace(rig); reply = issued('orig', {'path': '/w/a.png'})
    with pytest.raises(ValueError): ImageWorkspace(WorkspaceImageTool('', 'path'))
    if fault == 'ambiguous-tool': tools = tools * 2
    if fault == 'schema': tools = [{'type': 'function', 'function': {'name': 'view_image', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path', 'mode']}}}]
    if fault == 'unfinished': reply['choices'][0]['finish_reason'] = 'stop'
    if fault == 'bad-json': reply = issued('orig', '{nope')
    if fault == 'extra-arg': reply = issued('orig', {'path': '/w/a.png', 'zoom': 2})
    if fault == 'empty-path': reply = issued('orig', {'path': ''})
    assert ws.supports(tools) is (fault not in ('ambiguous-tool', 'schema'))
    with pytest.raises(ImageUnavailable): ws.register(s, reply, tools)
    out = ws.register(s, issued('orig', {'path': '/w/a.png'}), workspace(rig)[1])
    assert out['choices'][0]['message']['tool_calls'][0]['id'].startswith('imgread_')


@pytest.mark.parametrize('fault', ['late-issuer', 'changed-call', 'changed-result', 'unregistered'])
def test_a_harness_image_result_binds_only_to_the_exact_read_cria_issued(rig, fault):  # noqa: F811
    """The result must come after exactly one unchanged issuing call and stay byte-identical on replay; an image tool result with no
    registered read is refused, while the harness's own text (a refusal) passes through untouched."""
    s = rig[1]; ws, tools = workspace(rig); out = ws.register(s, issued('orig', {'path': '/w/a.png'}), tools)
    call = out['choices'][0]['message']['tool_calls'][0]; img = {'role': 'tool', 'tool_call_id': call['id'], 'content': [IMAGE]}
    chat = [{'role': 'user', 'content': 'x'}, {'role': 'assistant', 'content': None, 'tool_calls': [call]}, img]
    assert ws.resolve(s, chat) == {(2, 0): '/w/a.png'}
    assert ws.resolve(s, chat[:2] + [{**img, 'content': 'no such file'}]) == {}
    bad = {'late-issuer': [chat[0], img, chat[1]], 'changed-call': [chat[0], {**chat[1], 'tool_calls': [{**call, 'function': {**call['function'], 'arguments': '{"path": "/x"}'}}]}, img],
           'changed-result': chat[:2] + [{**img, 'content': [{**IMAGE, 'image_url': {'url': 'data:image/png;base64,ZZZZ'}}]}],
           'unregistered': [chat[0], {**img, 'tool_call_id': 'someone-elses'}]}[fault]
    with pytest.raises(ImageUnavailable): ws.resolve(s, bad)


def test_auxiliary_readers_see_the_labelled_observation_never_pixels(rig):  # noqa: F811
    """A judge/critic/summariser view carries the account of an observed image; with no image context, or when the projection cannot
    be made, the messages come back untouched and the failure is logged."""
    from cria import imageworkflow
    _, s, route, messages, prepared, ref, body, _ = rig
    seen = []; log = SimpleNamespace(emit=lambda kind, **k: seen.append(kind))
    assert imageworkflow.review_view(messages) is messages and not imageworkflow.has_observation()
    attempt = s.begin(ref, TASK, route, body); s.complete(attempt, delivered(attempt, route))
    token = imageworkflow.current.set(imageworkflow.SourceImageContext(None, s, prepared, TASK))
    try:
        view = imageworkflow.review_view(messages)
        assert 'data:image' not in str(view) and 'Save\\nCancel' in str(view) and imageworkflow.has_observation()
        assert imageworkflow.review_view([{'role': 'user', 'content': 'no image here'}], log) == [{'role': 'user', 'content': 'no image here'}] and seen == ['image.review_projection_unavailable']
    finally:
        imageworkflow.current.reset(token)
