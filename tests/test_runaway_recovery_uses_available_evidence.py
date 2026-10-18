"""Recovery packet contracts, not a scripted claim of semantic model improvement.

The Java incident retried an already inspected source/API with a blanket preference
for another read. Native comparisons remain in canonical call captures; these fake
providers prove the notice boundary and preserve legitimate reads and caller tools.
"""
import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cria import bodykeys, generationguards, loop, upstream


class Log:
    phase = 'coder'

    def emit(self, *_args, **_kwargs):
        pass


@pytest.mark.parametrize('arm', ['second_guessing', 'length'])
@pytest.mark.parametrize('current', [True, False])
@pytest.mark.parametrize('action', ['read_file', 'edit_file'])
def test_recovery_does_not_prefer_reinspection_or_force_a_write(arm, current, action):
    task = 'Repair the existing processor; inspect any external facts you need.'
    evidence = ('Current processor and dependency signatures: exact public bytes.' if current
                else 'The previous inspection predates a later change; current bytes unknown.')
    tools = [{'type': 'function', 'function': {'name': name, 'parameters': {
        'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']}}}
        for name in ('read_file', 'edit_file')]
    body = {'model': 'offline', 'messages': [
        {'role': 'user', 'content': task},
        {'role': 'assistant', 'tool_calls': [{'id': 'inspection', 'type': 'function',
            'function': {'name': 'read_file', 'arguments': '{"path":"processor.txt"}'}}]},
        {'role': 'tool', 'tool_call_id': 'inspection', 'content': evidence},
    ], 'tools': tools}
    original = copy.deepcopy(body)
    private = 'PRIVATE discarded design; replace the whole file with this invented implementation.'
    aborted = {'choices': [{'finish_reason': 'rumination', 'message': {
        'role': 'assistant', 'content': '', 'reasoning_content': private}}],
        bodykeys.RUMINATION: {'hits': 85, 'reasoning_tokens': 8449, 'arm': arm}}
    reply = {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
        'tool_calls': [{'id': 'next', 'type': 'function', 'function': {
            'name': action, 'arguments': '{"path":"processor.txt"}'}}]}}]}
    sent = []
    wire = upstream.Upstream('http://offline.invalid', api_key='offline',
        context_window=49152, engagement_level=5)

    def chat(packet, log):
        with patch('cria.upstream.urllib.request.urlopen', side_effect=AssertionError('no network')):
            serialized, _, _ = wire._prep(packet, False, log)
        sent.append(json.loads(serialized))
        return json.dumps(reply).encode()

    services = generationguards.RetryServices(chat, loop._parse_completion, loop._add_note,
        Log(), SimpleNamespace(reasoning='on', think_protocol='chat_template'))
    result = generationguards.recover_runaway(
        generationguards.RecoveryInput(aborted, body), services)
    assert result.status is generationguards.RecoveryStatus.RECOVERED
    assert result.attempts == 1
    assert len(sent) == 1
    packet = sent[0]
    assert packet['messages'][:-1] == original['messages']
    assert packet['tools'] == tools
    assert packet.get('tool_choice') != 'required'
    assert packet['chat_template_kwargs']['enable_thinking'] is False
    assert body == original
    assert private not in json.dumps(packet)
    notice = packet['messages'][-1]['content']
    # This is the harmful user-visible policy, not a source-text/change detector:
    # recovery must not prefer a read irrespective of the available evidence.
    assert 'Prefer reading the current file or rerunning the exact failing check' not in notice
    external_condition = ('If the missing fact concerns an external library or service' if arm == 'length'
                          else 'If what you are circling is an unread external fact')
    assert external_condition + ', obtain it with a tool before proposing a change.' in notice
    assert result.completion['choices'][0]['message']['tool_calls'] == reply['choices'][0]['message']['tool_calls']
