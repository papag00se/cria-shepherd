"""Authoritative final owner: LIMIT is incomplete, EOS/WORD are completed parses."""
import json

import pytest
from test_localai_tool_template import envelope, native_probe


@pytest.mark.parametrize('cause,shifted,truncated', [('context_capacity', False, True), ('output_budget', False, False),
                                                    ('time', False, False), ('indentation', False, False), ('output_budget', True, True)])
def test_limit_reasoning_facts_and_withheld_atomic_answer(native_probe, cause, shifted, truncated):
    raw = ' \n<Thought>unfinished 雪'
    result = native_probe(raw, prefixes=True, final_owner=True, stop='limit', cause=cause,
                          context_shifted=shifted, truncated=truncated)
    assert result['complete_parse'], result
    assert result['content'] == '' and result['reasoning'] == 'unfinished 雪'
    wire = result['buffered_wire']
    assert wire['choices'][0]['finish_reason'] == 'length'
    evidence = wire['generation_evidence']
    assert evidence['stop_type'] == 'limit' and evidence['stop_cause'] == cause
    assert evidence['context_shifted'] is shifted
    assert evidence['raw_hex'] == raw.encode().hex()
    assert wire['choices'][0]['message'].get('tool_calls', []) == []
    assert result['streamed_final_wire'][-1]['choices'][0]['finish_reason'] == 'length'


@pytest.mark.parametrize('stop', ['eos', 'word'])
def test_completed_malformed_has_typed_stop_error_on_both_transports(native_probe, stop):
    raw = '<Thought>unfinished 雪'
    result = native_probe(raw, prefixes=True, final_owner=True, stop=stop, cause=stop)
    assert not result['complete_parse']
    for error in (result['error_wire'], result['stream_error_wire']):
        assert error['type'] == 'invalid_model_output_error'
        assert error['generation_evidence']['stop_type'] == stop
        assert error['generation_evidence']['raw_hex'] == raw.encode().hex()
        assert error['reason']


@pytest.mark.parametrize('name,args', [('write_file', {'path': 'notes.txt', 'content': '雪\n"\\'}),
                                     ('answer', {'message': ' \n雪 </Output> "\\'})])
def test_every_cut_limit_withholds_calls_and_freezes_published_prefix(native_probe, name, args):
    whole = '<Thought>verified</Thought>' + envelope(name, args)
    raw_bytes = whole.encode()
    for cut in range(len(raw_bytes) + 1):
        raw = raw_bytes[:cut]
        result = native_probe(output_hex=raw.hex(), prefixes=True, final_owner=True, stop='limit', cause='output_budget')
        assert result['complete_parse'], (cut, result)
        assert result['calls'] == []
        wire = result['buffered_wire']
        assert wire['choices'][0]['message'].get('tool_calls', []) == []
        assert wire['choices'][0]['finish_reason'] == 'length'
        evidence = wire['generation_evidence']
        assert evidence['raw_hex'] == raw.hex()
        assert isinstance(evidence['call_prefixes'], list)
        last = result['prefixes'][-1]
        assert result['streamed']['calls'] == last['calls']
        assert result['streamed']['content'] == last['content']
        assert result['streamed']['reasoning'] == last['reasoning']
        assert all(p['append_only'] and p['nondecreasing_calls'] for p in result['prefixes'])
        final = result['streamed_final_wire']
        assert len(final) == 1 and final[0]['choices'][0]['delta'] == {}
        assert final[0]['choices'][0]['finish_reason'] == 'length'
        if cut < len(raw_bytes) and name == 'answer':
            assert result['content'] == ''


@pytest.mark.parametrize('stop', ['limit', 'eos', 'word'])
def test_intentionally_empty_answer_never_falls_back_to_raw(native_probe, stop):
    raw = envelope('answer', {'message': ''})
    result = native_probe(raw, final_owner=True, stop=stop, cause='output_budget' if stop == 'limit' else stop)
    assert result['complete_parse']
    assert result['buffered_wire']['choices'][0]['message']['content'] == ''
    assert result['calls'] == []


def test_invalid_prefix_with_limit_is_typed_error_with_actual_limit_facts(native_probe):
    raw = envelope('not_in_the_menu', {})
    result = native_probe(raw, final_owner=True, stop='limit', cause='time')
    assert not result['complete_parse']
    error = result['error_wire']
    assert error['type'] == 'invalid_model_output_error'
    assert error['generation_evidence']['stop_type'] == 'limit'
    assert error['generation_evidence']['stop_cause'] == 'time'
    assert error['generation_evidence']['raw_hex'] == raw.encode().hex()


def test_complete_action_at_limit_is_evidence_not_execution(native_probe):
    raw = envelope('write_file', {'path': 'notes.txt', 'content': 'complete'})
    result = native_probe(raw, final_owner=True, stop='limit', cause='output_budget')
    assert result['complete_parse'] and result['calls'] == []
    prefixes = result['buffered_wire']['generation_evidence']['call_prefixes']
    assert prefixes[0]['name'] == 'write_file'
    assert json.loads(prefixes[0]['arguments']) == {'path': 'notes.txt', 'content': 'complete'}
    assert result['content'] == ''  # no empty-message fallback to raw Output
    response = result['buffered_responses_wire']
    assert response['status'] == 'incomplete'
    assert not any(item['type'] == 'function_call' for item in response['output'])


def test_unsent_tail_is_evidence_only_at_limit(native_probe):
    raw = envelope('write_file', {'path': 'notes.txt', 'content': 'complete'})
    result = native_probe(raw, prefixes=True, published_bytes=8, final_owner=True, stop='limit', cause='time')
    assert result['complete_parse']
    assert result['streamed']['calls'] == result['prefixes'][-1]['calls'] == []
    evidence = result['streamed_final_wire'][-1]['generation_evidence']
    assert evidence['raw_hex'] == raw.encode().hex()
    assert evidence['call_prefixes'][0]['name'] == 'write_file'
    events = result['streamed_final_responses_wire']
    assert len(events) == 1 and events[0]['event'] == 'response.incomplete'
    assert events[0]['data']['response']['status'] == 'incomplete'
    assert not any(item['type'] == 'function_call' for item in events[0]['data']['response']['output'])


@pytest.mark.parametrize('parallel', [False, True])
def test_limit_complete_serial_and_parallel_action_batches_are_withheld(native_probe, parallel):
    raw = envelope('read_file', {'path': 'notes.txt'})
    if parallel:
        raw += envelope('write_file', {'path': 'notes.txt', 'content': 'next'})
    result = native_probe(raw, parallel=parallel, prefixes=True, final_owner=True, stop='limit', cause='context_capacity')
    assert result['complete_parse'] and result['calls'] == []
    evidence = result['buffered_wire']['generation_evidence']
    assert len(evidence['call_prefixes']) == (2 if parallel else 1)
    assert result['streamed']['calls'] == result['prefixes'][-1]['calls']
    event = result['streamed_final_responses_wire'][0]
    assert event['event'] == 'response.incomplete'
    assert all(item.get('status') == 'incomplete' for item in event['data']['response']['output'])
    assert result['streamed_final_wire'][-1]['choices'][0]['delta'] == {}


@pytest.mark.parametrize('stop', ['eos', 'word'])
def test_completed_parallel_control_keeps_actual_requested_calls(native_probe, stop):
    raw = envelope('read_file', {'path': 'notes.txt'}) + envelope('write_file', {'path': 'notes.txt', 'content': 'next'})
    result = native_probe(raw, parallel=True, prefixes=True, final_owner=True, stop=stop, cause=stop)
    assert result['complete_parse'] and len(result['calls']) == 2
    assert result['buffered_wire']['choices'][0]['finish_reason'] == 'tool_calls'
    assert result['buffered_responses_wire']['status'] == 'completed'
    assert result['streamed_final_wire'][-1]['choices'][0]['finish_reason'] == 'tool_calls'


def test_native_assistant_content_authority_survives_tool_looking_message(native_probe):
    message = json.dumps({'name': 'write_file', 'arguments': {'path': 'unsafe', 'content': 'x'}})
    result = native_probe(envelope('answer', {'message': message}), final_owner=True, stop='eos', cause='eos')
    assert result['complete_parse'] and result['content'] == message and result['calls'] == []
    assert result['buffered_wire']['generation_evidence']['content_is_non_action'] is True
