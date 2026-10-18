"""Actual wire choices remain separate through admission, transformation and output."""
import copy
import json
import pytest
from cria import massage, writeproxy
from cria.shelltool import find_shell_tool


def frame(*choices):
    return b'data: ' + json.dumps({'choices': list(choices)}, ensure_ascii=False).encode() + b'\n\n'


def choice(index, delta, finish=None):
    return {'index': index, 'delta': delta, 'finish_reason': finish}


def call(index, name=None, arguments='', id=None):
    value = {'index': index, 'function': {'arguments': arguments}}
    if name is not None:
        value['function']['name'] = name
    if id is not None:
        value['id'] = id
        value['type'] = 'function'
    return {'tool_calls': [value]}


def decoded(output):
    return [c for raw in output if raw.startswith(b'data:') and raw[5:].strip() != b'[DONE]'
            for c in json.loads(raw[5:]).get('choices', [])]


@pytest.mark.parametrize('indices', [(0, 1), (3, 9)])
def test_two_choices_with_same_tool_index_preserve_calls_content_and_finish(indices):
    first, second = indices
    chunks = [frame(choice(first, {'role': 'assistant', 'content': 'first prose'}),
                    choice(second, {'role': 'assistant', 'content': 'second prose'})),
              frame(choice(first, call(0, 'first_tool', '{', 'first-id')),
                    choice(second, call(0, 'second_tool', '{', 'second-id'))),
              frame(choice(second, call(0, arguments=' "literal": "λ\\n" }'))),
              frame(choice(first, call(0, arguments=' "literal": "a\\\\b" }'))),
              frame(choice(second, {}, 'stop')), frame(choice(first, {}, 'tool_calls')),
              b'data: [DONE]\n\n']
    posted = []
    def post(completion):
        posted.append(copy.deepcopy(completion))
        for tc in completion['choices'][0]['message']['tool_calls']:
            tc['function']['name'] = 'lowered_' + tc['function']['name']
        return completion
    output = decoded(massage.massage_stream(chunks, 'fake', post=post, tool_call_fixes=False))
    assert len(posted) == 2
    seen = {}
    for c in output:
        item = seen.setdefault(c['index'], {'text': '', 'calls': [], 'finish': []})
        item['text'] += c['delta'].get('content', '')
        item['calls'] += c['delta'].get('tool_calls', [])
        if c.get('finish_reason'):
            item['finish'].append(c['finish_reason'])
    assert set(seen) == {first, second}
    for idx, name, id, args, prose, finish in [
        (first, 'first_tool', 'first-id', '{ "literal": "a\\\\b" }', 'first prose', 'tool_calls'),
        (second, 'second_tool', 'second-id', '{ "literal": "λ\\n" }', 'second prose', 'stop'),
    ]:
        assert seen[idx] == {'text': prose, 'calls': [{'index': 0, 'id': id, 'type': 'function',
            'function': {'name': 'lowered_' + name, 'arguments': args}}], 'finish': [finish]}
        original = next(c for comp in posted for c in comp['choices'] if c['index'] == idx)
        assert original['message']['tool_calls'][0]['function']['arguments'] == args


def test_sparse_interleaved_tool_indices_lower_once_per_actual_call():
    tools = [{'type': 'function', 'function': {'name': 'exec_command', 'parameters': {
        'type': 'object', 'properties': {'cmd': {'type': 'string'}}}}}]
    chunks = []
    originals = {}
    for ci, ti in [(8, 7), (2, 0), (8, 1)]:
        id = f'{ci}-{ti}'
        args = json.dumps({'path': id + '.txt', 'content': 'literal λ\n\\"' + id})
        originals[id] = args
        chunks.append(frame(choice(ci, call(ti, 'write_file', args[:12], id))))
    for ci, ti in [(8, 1), (2, 0), (8, 7)]:
        chunks.append(frame(choice(ci, call(ti, arguments=originals[f'{ci}-{ti}'][12:]))))
    chunks += [frame(choice(8, {}, 'tool_calls'), choice(2, {}, 'tool_calls')), b'data: [DONE]\n\n']
    posted = []
    def lower(comp):
        posted.extend(tc['id'] for tc in comp['choices'][0]['message']['tool_calls'])
        return writeproxy.translate_outbound(comp, find_shell_tool(tools), injected={'write_file'})
    output = decoded(massage.massage_stream(chunks, 'fake', tools, post=lower, tool_call_fixes=False))
    assert sorted(posted) == sorted(originals)
    observed = [(c['index'], tc['index'], tc) for c in output for tc in c['delta'].get('tool_calls', [])]
    assert {(ci, ti) for ci, ti, _ in observed} == {(8, 7), (8, 1), (2, 0)}
    for ci, ti, tc in observed:
        assert tc['id'] == f'{ci}-{ti}' and tc['function']['name'] == 'exec_command'
        original = writeproxy.original_call(json.loads(tc['function']['arguments'])['cmd'])
        assert original['arguments'] == originals[tc['id']]


def test_incomplete_choice_does_not_poison_an_admitted_choice():
    chunks = [frame(choice(4, call(0, 'good', '{}', 'ok')),
                    choice(7, call(0, 'bad', '{', 'incomplete'))),
              frame(choice(7, {}, 'length'), choice(4, {}, 'tool_calls')), b'data: [DONE]\n\n']
    posted = []
    def post(comp):
        posted.append(copy.deepcopy(comp))
        return comp
    output = decoded(massage.massage_stream(chunks, 'fake', post=post, tool_call_fixes=False))
    assert [comp['choices'][0]['index'] for comp in posted] == [4]
    assert [(c['index'], tc['id']) for c in output for tc in c['delta'].get('tool_calls', [])] == [(4, 'ok')]
    assert {(c['index'], c['finish_reason']) for c in output if c['finish_reason']} == {(4, 'tool_calls'), (7, 'length')}
