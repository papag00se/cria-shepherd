"""F75: generation consumption is not the next turn's model-visible occupancy.

Ornith Java 1792344838 call0008 returned 32467 native completion tokens,
mostly in a private channel, and one public environment-check action. The
existing producer appended all consumed tokens to its estimated input context,
triggering a harness compaction. No reasoning-token estimate is subtracted here.
"""
import copy
import json

import pytest
from cria import contextfloor, indicators, responses, server
from test_loop import _Rlog
from test_engagement_levels import _Harness
from test_model_visible_usage import _post_responses
from test_server import _FakeUpstream


NATIVE = {'prompt_tokens': 13734, 'completion_tokens': 32467, 'total_tokens': 46201,
          'prompt_tokens_details': {'cached_tokens': 13004},
          'completion_tokens_details': {'reasoning_tokens': 31000}}


def completion(public='A public action.', reasoning='Private deliberation.\n' * 8000):
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {
        'role': 'assistant', 'content': public, 'reasoning_content': reasoning,
        'tool_calls': [{'id': 'action', 'type': 'function', 'function': {
            'name': 'exec_command', 'arguments': '{"cmd":"echo acknowledged"}'}}]}}],
        'usage': copy.deepcopy(NATIVE)}


def projected_reply(value):
    # Canonical actual Responses output -> inbound projection, not a private-char tally.
    response = responses.to_responses_json(value, 'fixture', show_reasoning=True,
                                           reasoning_transcript=True)
    body = responses.to_chat_body({'model': 'fixture', 'input': response['output']})
    shown, _ = indicators.strip_history(body['messages'])
    return contextfloor.est_total(shown, None)


@pytest.mark.parametrize('reasoning', ['', 'Private deliberation.\n' * 8000],
                         ids=['without-private', 'large-private'])
def test_report_counts_projected_reply_and_keeps_native_consumption_separate(reasoning):
    value = completion(reasoning=reasoning)
    expected = projected_reply(value)
    original_message = copy.deepcopy(value['choices'])
    server._report_context_usage(value, 12673, _Rlog())
    assert value['usage']['completion_tokens'] == expected
    assert value['usage']['total_tokens'] == 12673 + expected
    assert value['usage']['native_usage'] == NATIVE
    assert value['usage']['context_estimate']['estimated'] is True
    assert value['choices'] == original_message  # No change to reasoning, output, or calls.
    # Native cached/reasoning details describe consumption, never this context estimate.
    assert 'completion_tokens_details' not in value['usage']
    assert 'prompt_tokens_details' not in value['usage']


def test_large_public_output_still_increases_continuing_context():
    value = completion(public='Substantive public answer.\n' * 8000)
    expected = projected_reply(value)
    assert expected > 40000
    server._report_context_usage(value, 12673, _Rlog())
    assert value['usage']['completion_tokens'] == expected
    assert value['usage']['total_tokens'] > 45000
    assert value['usage']['native_usage'] == NATIVE


@pytest.mark.parametrize('stream', [False, True])
def test_responses_dto_preserves_both_usage_contracts(stream):
    value = completion()
    server._report_context_usage(value, 12673, _Rlog())
    if stream:
        raw = b''.join(responses.body_events(value, 'resp-fixture', 'fixture',
            show_reasoning=True, reasoning_transcript=True))
        events = [json.loads(line[6:]) for line in raw.decode().splitlines() if line.startswith('data: ')]
        response = next(event['response'] for event in events if event['type'] == 'response.completed')
    else:
        response = responses.to_responses_json(value, 'fixture', show_reasoning=True,
                                               reasoning_transcript=True)
    usage = response['usage']
    assert usage['output_tokens'] == projected_reply(value)
    assert usage['native_usage'] == NATIVE
    assert usage['context_estimate']['estimated'] is True
    assert 'output_tokens_details' not in usage
    assert any(item['type'] == 'reasoning' for item in response['output'])
    assert any(item['type'] == 'function_call' for item in response['output'])


def test_l0_native_usage_mapping_is_not_reinterpreted():
    value = completion()
    response = responses.to_responses_json(value, 'fixture')
    assert response['usage'] == {
        'input_tokens': 13734, 'output_tokens': 32467, 'total_tokens': 46201,
        'input_tokens_details': {'cached_tokens': 13004},
        'output_tokens_details': {'reasoning_tokens': 31000}}


@pytest.mark.parametrize('level', [0, 1])
@pytest.mark.parametrize('api', ['chat', 'responses-json', 'responses-sse'])
def test_http_usage_separates_context_estimates_only_above_l0(monkeypatch, level, api):
    value = completion()
    def post(handler):
        handler.rfile.read(int(handler.headers['Content-Length']))
        handler._json(json.dumps(value).encode())
    monkeypatch.setattr(_FakeUpstream, 'do_POST', post)
    harness = _Harness(level, False)
    tool = {'name': 'exec_command', 'parameters': {'type': 'object',
            'properties': {'cmd': {'type': 'string'}}, 'required': ['cmd']}}
    try:
        if api == 'chat':
            result = json.loads(harness.post({'model': 'fixture', 'messages': [
                {'role': 'user', 'content': 'Perform the public action.'}],
                'tools': [{'type': 'function', 'function': tool}], 'stream': False}))
            output_key = 'completion_tokens'
        else:
            result = _post_responses(harness, {'model': 'fixture', 'input': [
                {'type': 'message', 'role': 'user', 'content': 'Perform the public action.'}],
                'tools': [{'type': 'function', **tool}]}, api == 'responses-sse')
            output_key = 'output_tokens'
        usage = result['usage']
        if level == 0:
            assert usage[output_key] == NATIVE['completion_tokens']
            assert 'context_estimate' not in usage and 'native_usage' not in usage
        else:
            assert usage[output_key] == projected_reply(value)
            assert usage['native_usage'] == NATIVE
            assert usage['context_estimate']['estimated'] is True
    finally:
        harness.close()
