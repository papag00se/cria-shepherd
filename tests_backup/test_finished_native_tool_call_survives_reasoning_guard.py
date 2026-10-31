"""A finished native call is not unfinished reasoning, even on the threshold frame."""
import json
from unittest.mock import patch

import pytest

from cria import assistruntime, bodykeys, generationguards as guards, upstream


class Log:
    phase = 'coder'
    live_chars = 0

    def emit(self, *args, **kwargs):
        pass


class Response:
    def __init__(self, frames):
        self.frames = frames

    def __iter__(self):
        for frame in self.frames:
            yield b'data: ' + json.dumps(frame).encode() + b'\n\n'

    def close(self):
        pass


def run(frames):
    up = upstream.Upstream('http://unused.invalid', context_window=1_000_000)
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)), \
         patch.object(up, '_open_with_refit', return_value=(Response(frames), 10, None)), \
         patch.object(up, '_resolve_window', return_value=1_000_000):
        return json.loads(up.chat_watched({'model': 'fake', 'messages': []}, Log(),
                                          watch=guards.Detector(1000).check))


def test_finished_single_choice_call_crossing_watch_is_not_aborted():
    args = json.dumps({'path': 'result.txt', 'content': 'complete'})
    call = {'index': 0, 'id': 'call-1', 'type': 'function',
            'function': {'name': 'write_file', 'arguments': args}}
    frame = {'choices': [{'index': 0, 'delta': {'reasoning_content': 'Actually wait. ' * 160,
                                                'tool_calls': [call]}, 'finish_reason': 'tool_calls'}]}
    result = run([frame, {'choices': [], 'usage': {'completion_tokens': 1234}}])
    assert bodykeys.RUMINATION not in result
    assert result['choices'][0]['message']['tool_calls'][0]['function']['arguments'] == args
    assert result['usage']['completion_tokens'] == 1234


def test_late_unfinished_choice_does_not_release_early_completed_action():
    call = {'index': 0, 'id': 'call-1', 'type': 'function',
            'function': {'name': 'write_file', 'arguments': '{}'}}
    frames = [{'choices': [{'index': 0, 'delta': {'reasoning_content': 'Actually wait. ' * 160,
                                                  'tool_calls': [call]}, 'finish_reason': 'tool_calls'}]},
              {'choices': [{'index': 1, 'delta': {'content': 'unfinished'}, 'finish_reason': None}]}]
    result = run(frames)
    assert bodykeys.RUMINATION in result
    assert not result['choices'][0]['message'].get('tool_calls')


def test_incomplete_call_on_terminal_frame_does_not_bypass_watch():
    call = {'index': 0, 'id': 'call-1', 'type': 'function',
            'function': {'name': 'write_file', 'arguments': '{'}}
    frame = {'choices': [{'index': 0, 'delta': {'reasoning_content': 'Actually wait. ' * 160,
                                                'tool_calls': [call]}, 'finish_reason': 'tool_calls'}]}
    result = run([frame])
    assert bodykeys.RUMINATION in result
    assert not result['choices'][0]['message'].get('tool_calls')


@pytest.mark.parametrize('variant', ['length', 'unknown', 'duplicate-id', 'multiple-choices', 'incomplete-evidence',
                                     'changed-id', 'earlier-incomplete', 'earlier-stop'])
def test_unsettled_or_ambiguous_action_never_bypasses_watch(variant):
    call = {'index': 0, 'id': 'call-1', 'type': 'function',
            'function': {'name': 'write_file', 'arguments': '{}'}}
    calls = [call]
    if variant == 'duplicate-id':
        calls.append({**call, 'index': 1})
    frame = {'choices': [{'index': 0, 'delta': {'reasoning_content': 'Actually wait. ' * 160,
                                                'tool_calls': calls},
                          'finish_reason': variant if variant in ('length', 'unknown') else 'tool_calls'}]}
    if variant == 'multiple-choices':
        frame['choices'].append({'index': 1, 'delta': {}, 'finish_reason': None})
    if variant == 'incomplete-evidence':
        frame['generation_evidence'] = {'incomplete': True}
    preceding = []
    if variant == 'earlier-incomplete':
        preceding.append({'choices': [], 'generation_evidence': {'incomplete': True}})
        frame['generation_evidence'] = {'incomplete': False}
    elif variant == 'earlier-stop':
        preceding.append({'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})
    elif variant == 'changed-id':
        preceding.append({'choices': [{'index': 0, 'delta': {'tool_calls': [
            {'index': 0, 'id': 'different', 'type': 'function', 'function': {'name': 'write_file'}}]},
            'finish_reason': None}]})
    result = run([*preceding, frame])
    assert bodykeys.RUMINATION in result
    assert not result['choices'][0]['message'].get('tool_calls')
