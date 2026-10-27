"""Explicit empty argument objects: real selected recovery, fake transport, no execution."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cria import (assistruntime, bodykeys, callsyntax, generation, loop, massage,
                  outputpolicies, planner_tools, responses, upstream, verifytools)
from cria.config import Config, RoutingConfig
from cria.indicators import Indicator
from cria.server import CriaHandler


XML = '<function=list_dir>{}</function>'
THINKING = 'Inspect the workspace.\n' + XML
MENUS = [planner_tools.PLANNER_TOOLS, verifytools.VERIFY_TOOLS]
RECOVERY = next(d for d in outputpolicies.RECOVERY
                if d.policy.id == 'reasoning-call-recovery')


class Log:
    phase = 'synthetic'
    live_chars = 0

    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))


def reply(text=THINKING, channel='reasoning_content', finish='stop'):
    return {'choices': [{'index': 0, 'finish_reason': finish, 'message': {
        'role': 'assistant', 'content': None, channel: text}}]}


def calls(completion):
    return [tc['function'] for choice in completion['choices']
            for tc in choice['message'].get('tool_calls', [])]


def apply(completion, menu=MENUS[0], *, level=1, disabled=()):
    log = Log()
    runtime = assistruntime.AssistRuntime.select(level=level, disabled=disabled)
    with assistruntime.bound(runtime):
        result = massage.apply(completion, menu, log)
    return result, log


def events(log, name):
    return [fields for event, fields in log.events if event == name]


def assert_empty_call(result):
    assert calls(result) == [{'name': 'list_dir', 'arguments': '{}'}]
    assert result['choices'][0]['finish_reason'] == 'tool_calls'


def assert_recovery(log, text=THINKING):
    assert events(log, 'massage.reasoning_call_recovered') == [{
        'assist_id': RECOVERY.policy.id, 'family_id': RECOVERY.policy.family_id,
        'dialect': 'xml-function', 'calls': ['list_dir'],
        'at': text.index('<function='), 'reasoning_chars': len(text)}]


@pytest.mark.parametrize('menu', MENUS, ids=['planner-schema', 'verification-schema'])
@pytest.mark.parametrize('channel', ['reasoning_content', 'reasoning'])
def test_explicit_empty_object_through_bound_public_consumer(menu, channel):
    result, log = apply(reply(channel=channel), menu)
    assert_empty_call(result)
    assert result['choices'][0]['message'][channel] == THINKING
    assert_recovery(log)
    again, second_log = apply(copy.deepcopy(result), menu)
    assert again == result
    assert not events(second_log, 'massage.reasoning_call_recovered')


@pytest.mark.parametrize('body', ['', '  \n', 'not arguments', '{bad}'])
def test_absent_or_invalid_body_is_none_not_invented_arguments(body):
    assert callsyntax._xml_args(body) is None
    result, log = apply(reply('<function=list_dir>' + body + '</function>'))
    assert not calls(result)
    assert not events(log, 'massage.reasoning_call_recovered')


@pytest.mark.parametrize('text', ['<function=list_dir>{}', '<function=list_dir>{}</wrong>'])
def test_incomplete_xml_envelope_is_not_recovered(text):
    result, log = apply(reply(text))
    assert not calls(result)
    assert result['choices'][0]['message']['reasoning_content'] == text
    assert not events(log, 'massage.reasoning_call_recovered')


@pytest.mark.parametrize('tool', [planner_tools.PLANNER_TOOLS[2], loop._completion_tool()],
                         ids=['read-file-path', 'task-complete-summary'])
@pytest.mark.parametrize('null_required', [False, True])
def test_empty_or_null_required_arguments_reach_existing_schema_refusal(tool, null_required):
    fn = tool['function']
    required = fn['parameters']['required'][0]
    args = {required: None} if null_required else {}
    text = '<function=' + fn['name'] + '>' + json.dumps(args) + '</function>'
    result, log = apply(reply(text), [tool])
    assert not calls(result)
    assert result['choices'][0]['message']['reasoning_content'] == text
    assert len(events(log, 'massage.reasoning_call_off_menu')) == 1
    assert result[bodykeys.LOST_CALL]['tried'] == [fn['name']]


@pytest.mark.parametrize('name,args', [('read_file', {'path': 'a.txt'}),
                                     ('task_complete', {'summary': 'Finished synthetic work.'})])
def test_supplied_required_values_are_preserved(name, args):
    menu = [planner_tools.PLANNER_TOOLS[2], loop._completion_tool()]
    text = '<function=' + name + '>' + json.dumps(args) + '</function>'
    result, _ = apply(reply(text), menu)
    assert [(tc['name'], json.loads(tc['arguments'])) for tc in calls(result)] == [(name, args)]


@pytest.mark.parametrize('menu', [None, [], [planner_tools.PLANNER_TOOLS[2]]],
                         ids=['absent', 'empty', 'off-menu'])
def test_no_advertised_matching_tool_means_no_action(menu):
    result, log = apply(reply(), menu)
    assert not calls(result)
    assert not events(log, 'massage.reasoning_call_recovered')
    if menu:
        assert len(events(log, 'massage.reasoning_call_off_menu')) == 1


@pytest.mark.parametrize('level,disabled', [(0, ()), (1, ('reasoning-call-recovery',))])
def test_selection_still_withholds_optional_recovery(level, disabled):
    result, log = apply(reply(), level=level, disabled=disabled)
    assert not calls(result)
    assert not events(log, 'massage.reasoning_call_recovered')


@pytest.mark.parametrize('kind', ['fence', 'trailing-prose', 'content', 'existing-call',
                                  'length', 'abort', 'incomplete', 'non-action'])
def test_intent_and_generation_gates_remain_authoritative(kind):
    comp = reply()
    message = comp['choices'][0]['message']
    if kind == 'fence':
        message['reasoning_content'] = '```\n' + XML + '\n```'
    elif kind == 'trailing-prose':
        message['reasoning_content'] += '\nContinue deliberating.'
    elif kind == 'content':
        message['content'] = 'A visible ordinary answer.'
    elif kind == 'existing-call':
        message['tool_calls'] = [{'id': 'native', 'type': 'function', 'function': {
            'name': 'list_dir', 'arguments': '{"path":"existing"}'}}]
    elif kind == 'length':
        comp['choices'][0]['finish_reason'] = 'length'
    elif kind == 'abort':
        comp[bodykeys.RUMINATION] = {'dead_stream': True, 'chunks': 400}
    else:
        comp[generation.EVIDENCE] = {
            'incomplete' if kind == 'incomplete' else 'content_is_non_action': True}
    original = copy.deepcopy(comp)
    result, log = apply(comp)
    assert calls(result) == (calls(original) if kind == 'existing-call' else [])
    assert result['choices'][0]['message']['reasoning_content'] == original['choices'][0]['message']['reasoning_content']
    assert not events(log, 'massage.reasoning_call_recovered')
    if kind == 'content':
        assert result['choices'][0]['message']['content'] == 'A visible ordinary answer.'
    if kind in ('length', 'abort', 'incomplete'):
        assert generation.incomplete(result)
        assert result[generation.EVIDENCE]['withheld_choices'] == original['choices']


@pytest.mark.parametrize('text', [
    '<tool_call>{"name":"list_dir","arguments":{}}</tool_call>',
    '<|tool_call_start|>[list_dir()]<|tool_call_end|>',
    '<function=list_dir><parameter=path>.</parameter></function>',
    '<function=list_dir>{"path":"."}</function>'])
def test_existing_dialects_and_nonempty_xml_keep_literal_values(text):
    result, _ = apply(reply(text))
    expected = {'path': '.'} if 'path' in text else {}
    assert [(tc['name'], json.loads(tc['arguments'])) for tc in calls(result)] == [('list_dir', expected)]
    assert result['choices'][0]['message']['reasoning_content'] == text


def test_property_free_advertised_tool_and_adjacent_terminal_batch():
    zero = {'type': 'function', 'function': {'name': 'heartbeat', 'parameters': {
        'type': 'object', 'properties': {}, 'required': []}}}
    text = '<function=heartbeat>{}</function>\n' + XML
    result, log = apply(reply(text), [zero, MENUS[0][0]])
    assert calls(result) == [{'name': 'heartbeat', 'arguments': '{}'},
                             {'name': 'list_dir', 'arguments': '{}'}]
    assert events(log, 'massage.reasoning_call_recovered')[0]['calls'] == ['heartbeat', 'list_dir']
    assert result['choices'][0]['message']['reasoning_content'] == text


def handler_result(level, disabled=()):
    runtime = assistruntime.AssistRuntime.select(level=level, disabled=disabled)
    cfg = Config(routing=RoutingConfig(engagement_level=level))
    assert not cfg.planner.enabled
    comp = reply()
    provider = SimpleNamespace(chat=lambda body, log: json.dumps(comp).encode())
    h = CriaHandler.__new__(CriaHandler)
    h.path, h.headers = '/v1/chat/completions', {}
    h.server = SimpleNamespace(cfg=cfg, loop=None, loop_store=loop.LoopStore(),
                               pilot_runtime=runtime, reasoner_role=None)
    h._classify = lambda *args: None
    h._engages_loop = lambda *args: False
    h._route = lambda *args: (provider, Indicator(False, False, 'fake'))
    h._apply_route_role = lambda body, *args: body
    h._focus_trim = lambda body, *args: (body, False)
    h._translate_out = lambda completion, *args: completion
    h._finalize = lambda completion, *args: completion
    body = {'messages': [{'role': 'user', 'content': 'Synthetic request.'}],
            'tools': MENUS[0], 'model': 'fake'}
    output, log = [], Log()
    h._handle_chat = lambda: output.append(CriaHandler._produce_completion(h, body, log, 'fake')[0])
    CriaHandler.do_POST(h)
    return output[0], log


@pytest.mark.parametrize('level,disabled,expected', [(0, (), False), (1, (), True),
    (5, (), True), (1, ('reasoning-call-recovery',), False)])
def test_actual_buffered_handler_binding_and_responses_serialization(level, disabled, expected):
    result, log = handler_result(level, disabled)
    wire = responses.to_responses_json(result, 'fake')
    emitted = [item for item in wire['output'] if item['type'] == 'function_call']
    assert result['choices'][0]['message']['reasoning_content'] == THINKING
    if expected:
        assert_empty_call(result)
        assert_recovery(log)
        assert [(item['name'], item['arguments']) for item in emitted] == [('list_dir', '{}')]
    else:
        assert not calls(result) and not emitted
        assert not events(log, 'massage.reasoning_call_recovered')


class Response:
    def __init__(self, frames):
        self.frames, self.closed = frames, False

    def __iter__(self):
        for frame in self.frames:
            yield b'data: ' + json.dumps(frame).encode() + b'\n\n'

    def close(self):
        self.closed = True


def sse_frames(channel, text):
    # Single-character splits cross every delimiter and both braces; no parser is stubbed.
    for char in text:
        yield {'choices': [{'index': 0, 'delta': {channel: char}}]}
        yield {'choices': [{'index': 0, 'delta': {}}]}
        yield {'choices': [], 'usage': {'completion_tokens': 1}}
    yield {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}


@pytest.mark.parametrize('channel', ['reasoning_content', 'reasoning'])
@pytest.mark.parametrize('window', [None, 1000000])
def test_actual_collector_then_bound_public_consumer(channel, window):
    response, log = Response(list(sse_frames(channel, THINKING))), Log()
    up = upstream.Upstream('http://not-used', context_window=window, capture_dir=None)
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=4)), \
         patch.object(up, '_open_with_refit', return_value=(response, 10, None)), \
         patch.object(up, '_resolve_window', return_value=window):
        collected = json.loads(up.chat_watched({'model': 'fake', 'messages': []}, log, watch=None))
        assert response.closed
        assert collected['choices'][0]['message']['reasoning_content'] == THINKING
        assert bodykeys.RUMINATION not in collected
        result = massage.apply(collected, MENUS[0], log)
    assert_empty_call(result)
    assert result['choices'][0]['message']['reasoning_content'] == THINKING
    assert_recovery(log)
    assert not events(log, 'rumination.abort')
    assert events(log, 'upstream.done')[0]['aborted'] is False


@pytest.mark.parametrize('channel,text,expected', [
    ('reasoning_content', XML, False),
    ('reasoning_content', '<tool_call>{"name":"list_dir","arguments":{}}</tool_call>', False),
    ('content', XML, True)])
def test_passthrough_stream_keeps_its_existing_channel_boundary(channel, text, expected):
    source = [massage._sse({channel: text}, 'fake'), massage._sse({}, 'fake', finish='stop')]
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=1)):
        raw = list(massage.massage_stream(iter(source), 'fake', MENUS[0], Log()))
    objects = [json.loads(frame[5:]) for frame in raw
               if frame.startswith(b'data:') and frame[5:].strip() != b'[DONE]']
    choices = [choice for obj in objects for choice in obj.get('choices', [])]
    emitted = [tc['function'] for choice in choices
               for tc in (choice.get('delta') or {}).get('tool_calls', [])]
    assert emitted == ([{'name': 'list_dir', 'arguments': '{}'}] if expected else [])
    if not expected:
        assert ''.join((choice.get('delta') or {}).get(channel, '') for choice in choices) == text
    assert choices[-1]['finish_reason'] == ('tool_calls' if expected else 'stop')
