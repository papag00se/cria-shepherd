"""Automatic checks are evidence, not recent work chosen by the coder.

Ornith Java run1792297428/0055 credited the synthetic gate's successful Maven
check as the coder's latest progress, after refused API inspections. These tests
exercise real gate cleaning, common steer composition and final serialization;
scripted ON_TRACK answers test provenance, never semantic judgment quality.
"""
import base64
import copy
import hashlib
import json
from unittest.mock import patch

import pytest

from cria import groundedaction as ga, loop, probegate, selfcompact, upstream
from tests.gatefixture import bounds_field_for
from tests.gatefixture import gate_page
from stalled_work_fixtures import engine, _Log


def call(identity, command):
    return {'id': identity, 'type': 'function', 'function': {
        'name': 'exec_command', 'arguments': json.dumps({'cmd': command})}}


def result(identity, text):
    return {'role': 'tool', 'tool_call_id': identity, 'content': text}


@pytest.mark.parametrize('command', ['mvn -q compile', 'go test ./...', 'ruby -c worker.rb'])
@pytest.mark.parametrize('mixed', [False, True])
def test_steer_preserves_check_evidence_without_claiming_coder_progress(command, mixed):
    section = f'{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\nchecker exact evidence\nEXIT:0\n'
    gate = call('automatic', probegate._gate_sentinel([command]) + '\necho internal-plumbing')
    ordinary = call('ordinary', command)
    calls = [gate, ordinary] if mixed else [gate]
    messages = [
        {'role': 'user', 'content': 'Repair the processor.'},
        {'role': 'assistant', 'tool_calls': [call('refused', 'inspect dependency')]},
        result('refused', 'Not run: inspection was refused.'),
        {'role': 'assistant', 'tool_calls': calls},
        result('automatic', gate_page(probegate.GatePlan(''), section)),
    ]
    if mixed:
        messages.append(result('ordinary', 'The coder chosen check returned this exact output.'))
    original = copy.deepcopy(messages)
    sent = []
    wire = upstream.Upstream('http://offline.invalid', api_key='offline',
        context_window=65536, engagement_level=5)

    def chat(body, log):
        with patch('cria.upstream.urllib.request.urlopen', side_effect=AssertionError('no network')):
            data, _, _ = wire._prep(body, False, log)
        sent.append(json.loads(data))
        return json.dumps({'choices': [{'message': {'content': 'ON_TRACK'}, 'finish_reason': 'stop'}]}).encode()

    source = ga.AuthorInput(chat, None, None, ga.ActionEvidence(
        original_task='Repair the processor.', repeat_count=3, repeat_action='inspect dependency'),
        {'messages': messages}, _Log(), 'refusal')
    assert engine().author(source) is None
    assert messages == original
    assert len(sent) == 1
    assert all(m['role'] in ('system', 'user', 'assistant', 'tool') for m in sent[0]['messages'])
    text = '\n'.join(m.get('content', '') for m in sent[0]['messages'])
    historical = [m['content'] for m in sent[0]['messages']
                  if m.get('content', '').startswith('the coder called exec_command')]
    expected = [f'the coder called exec_command — cmd={command}'] if mixed else []
    assert [line for line in historical if line.endswith('cmd=' + command)] == expected
    assert 'Automatic check requested (not an action chosen by the coder):\n' + command in text
    assert 'Automatic check result (not an action chosen by the coder):' in text
    assert 'Not run: inspection was refused.' in text
    assert 'the coder called exec_command — cmd=inspect dependency' in text
    assert '___CRIA_GATE_' not in text
    assert 'internal-plumbing' not in text
    assert 'checker exact evidence' in text or 'no error-class problems' in text
    if mixed:
        assert 'The coder chosen check returned this exact output.' in text


def test_paged_gate_keeps_complete_checker_lines_and_unknown_stays_unknown():
    identity = '0123456789abcdef01234567'
    checker = 'module.txt:7: wrong value\n  expected: two  spaces\n\n  actual: other\n'
    raw = f'{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\n{checker}EXIT:1\n'
    data = raw.encode()
    page = '\n'.join([
        probegate._transport_marker(identity),
        'path\t' + base64.b64encode(f'/tmp/.cria-gate-{identity}.spool'.encode()).decode(),
        'offset\t0', f'total\t{len(data)}',
        'sha256\t' + hashlib.sha256(data).hexdigest(),
        *bounds_field_for(raw),
        'data\t' + base64.b64encode(data).decode(),
        probegate._transport_marker(identity, end=True),
    ])
    command = probegate._gate_sentinel(['runner check']) + '\nprivate transport program'
    messages = [{'role': 'assistant', 'tool_calls': [call('gate', command)]}, result('gate', page)]
    original = copy.deepcopy(messages)
    cleaned = probegate.clean_gate_results(messages)
    evidence = probegate.check_evidence_messages(messages)
    assert evidence[-1]['content'].endswith(cleaned[-1]['content'])
    assert checker.splitlines()[1] in selfcompact.serialize(evidence, defang=True)
    assert 'Automatic check result' in selfcompact.serialize(evidence, defang=True)
    assert messages == original

    # A pending request is not promoted to a successful execution or a green check.
    pending = probegate.check_evidence_messages(messages[:1])
    assert len(pending) == 1
    assert 'requested' in pending[0]['content']
    assert 'Automatic check result' not in selfcompact.serialize(pending, defang=True)
    broken = probegate.check_evidence_messages([messages[0], result('gate', page.replace('offset\t0', 'offset\t1'))])
    assert 'UNKNOWN' in selfcompact.serialize(broken, defang=True)
    assert 'no error-class problems' not in selfcompact.serialize(broken, defang=True)


def test_ordinary_identical_checks_and_marker_looking_results_are_not_relabelled():
    messages = [
        {'role': 'assistant', 'tool_calls': [call('own', 'runner check')]},
        result('own', 'Automatic check requested: quotation only\n' + probegate._gate_sentinel(['runner check'])),
    ]
    assert probegate.check_evidence_messages(messages) == probegate.clean_gate_results(messages)
    text = selfcompact.serialize(probegate.check_evidence_messages(messages), defang=True)
    assert 'the coder called exec_command — cmd=runner check' in text


def test_command_array_and_cleaning_are_identity_safe_for_evidence_only():
    script = probegate._gate_sentinel(['runner check']) + '\nprivate transport program'
    gate = {'id': 'gate', 'type': 'function', 'function': {'name': 'shell',
        'arguments': json.dumps({'command': ['bash', '-lc', script]})}}
    messages = [{'role': 'assistant', 'tool_calls': [gate]}, result('gate', 'check result')]
    original = copy.deepcopy(messages)
    coder_view = probegate.clean_gate_results(messages)
    evidence = probegate.check_evidence_messages(messages)
    assert 'runner check' in selfcompact.serialize(evidence, defang=True)
    assert 'the coder called shell' not in selfcompact.serialize(evidence, defang=True)
    assert probegate.check_evidence_messages(evidence) == evidence
    assert probegate.clean_gate_results(messages) == coder_view
    assert messages == original


@pytest.mark.parametrize('ending', ['  \n\n', '\t\r\n\r\n', '  '])
def test_complete_observation_payload_survives_serializer_and_final_author_wire(ending):
    checker = '\n  exact checker line with trailing whitespace' + ending
    messages = [{'role': 'assistant', 'tool_calls': [call('gate', probegate._gate_sentinel(['runner check']))]},
                result('gate', checker)]
    observation = probegate.check_evidence_messages(messages)[-1]
    payload = observation['content']
    assert payload.endswith(checker)
    sent = []
    wire = upstream.Upstream('http://offline.invalid', api_key='offline',
        context_window=65536, engagement_level=5)

    def chat(body, log):
        with patch('cria.upstream.urllib.request.urlopen', side_effect=AssertionError('no network')):
            data, _, _ = wire._prep(body, False, log)
        sent.append(json.loads(data))
        return json.dumps({'choices': [{'message': {'content': 'ON_TRACK'}, 'finish_reason': 'stop'}]}).encode()

    source = ga.AuthorInput(chat, None, None, ga.ActionEvidence(original_task='Repair the processor.'),
        {'messages': messages}, _Log(), 'refusal')
    assert engine().author(source) is None
    assert len(sent) == 1
    copies = [m['content'].encode() for m in sent[0]['messages'] if m.get('content') == payload]
    assert copies == [payload.encode()]
    assert selfcompact.serialize([observation], defang=True).encode() == payload.encode()
    assert loop._mark_own_notes(payload).encode() == payload.encode()
    assert ''.join(loop._evidence_blocks(payload, limit=17)).encode() == payload.encode()
    # The correction does not change the ordinary coder-speech rendering contract.
    assert selfcompact.serialize([{'role': 'assistant', 'content': '  ordinary text' + ending}],
                                 defang=True) == 'the coder said: ordinary text'


@pytest.mark.parametrize('ending', ['\n', '\r\n', '\n\n', ''])
def test_earlier_note_marking_retains_every_original_line_ending(ending):
    original = 'first line  \nprior ⟦ctx:steer⟧ note  ' + ending
    tag = '   [EARLIER NOTE FROM THIS SYSTEM — not evidence]'
    marked = loop._mark_own_notes(original)
    assert marked == 'first line  \nprior ⟦ctx:steer⟧ note  ' + tag + ending
    assert marked.replace(tag, '').encode() == original.encode()


def test_mixed_batch_preserves_coder_speech_calls_and_result_order():
    gate = call('gate', probegate._gate_sentinel(['runner check']))
    first, last = call('first', 'first command'), call('last', 'last command')
    messages = [{'role': 'assistant', 'content': 'The coder supplied this exact explanation.',
                 'tool_calls': [first, gate, last]},
                result('first', 'first result'), result('gate', 'check result'), result('last', 'last result')]
    evidence = probegate.check_evidence_messages(messages)
    assert evidence[0]['content'] == messages[0]['content']
    calls = [m['tool_calls'][0] for m in evidence if m.get('tool_calls')]
    assert calls == [first, last]
    text = selfcompact.serialize(evidence, defang=True)
    assert text.index('cmd=first command') < text.index('Automatic check requested') < text.index('cmd=last command')
    assert text.index('first result') < text.index('Automatic check result') < text.index('last result')
