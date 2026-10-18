"""Real handler/producer boundaries, fake providers, no sockets or model calls."""
import copy
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace
import json
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cria import assistruntime, massage, outputpolicies, toolstages
from cria.config import Config, RoutingConfig
from cria.loop import LoopStore
from cria.indicators import Indicator
from cria.server import CriaHandler


MENU = [{'type': 'function', 'function': {'name': 'write_file', 'parameters': {
    'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}},
    'required': ['path', 'content']}}}]
LEAK = '<tool_call>{"name":"write_file","arguments":{"path":"x.txt","content":"bytes"}}</tool_call>'


def runtime(level, replacement=None):
    # Use the authoritative selector, not a second test-side selection algorithm.
    registered = {d.policy.id: d for d in assistruntime.DEFINITIONS}
    registered.update({d.policy.id: d for d in toolstages.defaults().definitions})
    selected = assistruntime.AssistRuntime.select(level=level, registrations=tuple(registered.values()))
    if replacement is not None:
        selected = replace(selected, ordered_stages=tuple(
            replacement if d.policy.id == replacement.policy.id else d for d in selected.ordered_stages))
    return selected


def handler(level, *, stream=False, replacement=None):
    cfg = Config(routing=RoutingConfig(engagement_level=level))
    selected = runtime(level, replacement)
    comp = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': LEAK}}]}
    provider = SimpleNamespace(chat=lambda body, log: json.dumps(comp).encode(),
        stream_chat=lambda body, log: iter([massage._sse({'content': LEAK}, 'fake'),
            massage._sse({}, 'fake', finish='stop'), b'data: [DONE]\n\n']))
    body = {'messages': [{'role': 'user', 'content': 'request'}], 'tools': MENU, 'model': 'fake'}
    log = Mock()
    output = []
    h = CriaHandler.__new__(CriaHandler)
    h.path, h.headers = '/v1/chat/completions', {}
    h.server = SimpleNamespace(cfg=cfg, loop=None, loop_store=LoopStore(),
                               pilot_runtime=selected, reasoner_role=None)
    h._classify = lambda *args: None
    h._engages_loop = lambda *args: False
    h._route = lambda *args: (provider, Indicator(False, False, 'fake'))
    h._apply_route_role = lambda body, *args: body
    h._focus_trim = lambda body, *args: (body, False)
    h._translate_out = lambda comp, *args: comp
    h._finalize = lambda comp, *args: comp
    def respond():
        if stream:
            output.extend(CriaHandler._produce_stream(h, copy.deepcopy(body), log))
        else:
            output.append(CriaHandler._produce_completion(h, copy.deepcopy(body), log, 'fake')[0])
    h._handle_chat = respond
    h._handle_responses = respond
    return h, output


def names(output, stream=False):
    if stream:
        return [tc['function']['name'] for raw in output if (choice := massage._choice(raw))
                for tc in (choice.get('delta') or {}).get('tool_calls', [])]
    return [tc['function']['name'] for comp in output for choice in comp['choices']
            for tc in (choice.get('message') or {}).get('tool_calls', [])]


@pytest.mark.parametrize('stream', [False, True])
def test_bound_handler_selection_overrides_legacy_library_gate(stream):
    def run():
        h, output = handler(5, stream=stream)
        massage.set_tool_call_fixes(False)
        # This isolates the owned-file hazard from primary's still-separate
        # authoritative handler-binding integration, tested below.
        with toolstages.bound(toolstages.ToolStages.from_definitions(h.server.pilot_runtime.definitions)):
            CriaHandler.do_POST(h)
        assert names(output, stream) == ['write_file']
    copy_context().run(run)
    massage.set_tool_call_fixes(True)


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('path', ['/v1/chat/completions', '/v1/responses'])
def test_real_handler_uses_its_authoritative_selection_not_server_creation_order(stream, path):
    def run():
        high, high_output = handler(5, stream=stream)
        low, low_output = handler(0, stream=stream)
        high.path = low.path = path
        # Simulate the retained legacy constructor call in the hostile order.
        massage.set_tool_call_fixes(False)
        CriaHandler.do_POST(high)
        massage.set_tool_call_fixes(True)
        CriaHandler.do_POST(low)
        assert names(high_output, stream) == ['write_file']
        assert names(low_output, stream) == []
    copy_context().run(run)
    massage.set_tool_call_fixes(True)


def test_overlapping_handler_contexts_use_the_selected_replacement():
    barrier = Barrier(2)
    def replacement(comp, tools=None, rlog=None):
        comp['choices'][0]['message']['content'] = 'selected replacement'
        return comp
    definition = replace(outputpolicies.RECOVERY[0], execute=replacement)
    def run(level):
        h, output = handler(level, replacement=definition if level == 5 else None)
        original = h._handle_chat
        def respond():
            barrier.wait(timeout=5)
            original()
        h._handle_chat = respond
        CriaHandler.do_POST(h)
        return output[0]['choices'][0]['message']['content']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, [5, 0])) == ['selected replacement', LEAK]


def test_legacy_unbound_library_default_is_context_local():
    barrier = Barrier(2)
    def run(enabled):
        massage.set_tool_call_fixes(enabled)
        barrier.wait(timeout=5)
        comp = {'choices': [{'finish_reason': 'stop', 'message': {'content': LEAK}}]}
        return bool(massage.apply(comp, MENU)['choices'][0]['message'].get('tool_calls'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, [True, False])) == [True, False]
    massage.set_tool_call_fixes(True)
