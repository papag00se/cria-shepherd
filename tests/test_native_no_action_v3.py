"""Framing whitespace and opt-out error identity, using matching CPU native code."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from test_localai_tool_template import TEMPLATE, assert_prefixes, calls, envelope, native_probe, request


def reasoning_template(prefill, preamble=''):
    text = TEMPLATE.read_text()
    if prefill:
        text = text.replace("'<|im_start|>assistant<|im_sep|>\\n' }}{%- endif %}",
                            json.dumps('<|im_start|>assistant<|im_sep|>\n' + preamble + '<Thought>') + ' }}{%- endif %}')
    return text


@pytest.mark.parametrize('prefill', [False, True])
@pytest.mark.parametrize('preamble', ['', '\n', ' \t\r\n', 'Literal preamble. '])
def test_framing_before_closed_reasoning_and_exact_answer(native_probe, prefill, preamble):
    message = ' \n\t雪 "quoted" \\ literal </Output>\n'
    raw = ('' if prefill else preamble + '<Thought>') + 'verified</Thought>' + envelope('answer', {'message': message})
    result = native_probe(raw, template_text=reasoning_template(prefill, preamble), prefixes=True)
    assert result['complete_parse']
    assert result['generation_prompt'].endswith('<Thought>') == prefill
    # With reasoning prefill the initial bytes are already inside the reasoning block.
    expected_preamble = preamble if not prefill and preamble.strip() else ''
    assert result['content'] == expected_preamble + message
    assert result['reasoning'] == 'verified'
    assert result['calls'] == [] and result['ids'] == []
    assert result['buffered_wire']['choices'][0]['message']['content'] == expected_preamble + message
    assert_prefixes(result, answer=True)
    for prefix in result['prefixes']:
        assert prefix['content'] in (expected_preamble[:len(prefix['content'])], expected_preamble + message)
    history = request()
    history['messages'].extend([{'role': 'assistant', 'content': result['content'],
                                'reasoning_content': result['reasoning']},
                               {'role': 'user', 'content': 'Continue.'}])
    rendered = native_probe(body=history)['prompt']
    assert '<Thought>verified</Thought>\n' + expected_preamble + message + '<|im_end|>' in rendered


@pytest.mark.parametrize('prefill', [False, True])
@pytest.mark.parametrize('preamble', ['', '\n', ' \t\r\n', 'Literal preamble. '])
@pytest.mark.parametrize('closing', ['', '</Tho', '</Thought'])
def test_truncated_reasoning_keeps_structural_rejection(native_probe, prefill, preamble, closing):
    raw = ('' if prefill else preamble + '<Thought>') + 'unfinished 雪' + closing
    result = native_probe(raw, template_text=reasoning_template(prefill, preamble), prefixes=True, stop_limit=True)
    assert not result['complete_parse']
    assert raw.encode().hex() in result['parse_error']
    assert raw.encode().hex() in result['stream_error']
    assert 'buffered_wire' not in result and 'streamed_final_wire' not in result
    expected_preamble = preamble if not prefill and preamble.strip() else ''
    for prefix in result['prefixes']:
        assert prefix['append_only'] and prefix['nondecreasing_calls']
        assert expected_preamble.startswith(prefix['content'])
        assert prefix['calls'] == [] and prefix['ids'] == []


@pytest.mark.parametrize('prefill', [False, True])
def test_disabled_framing_and_partial_reasoning_stay_upstream(native_probe, prefill):
    for complete in (False, True):
        raw = ('' if prefill else ' \n<Thought>') + 'verified' + ('</Thought>' if complete else '')
        result = native_probe(raw, template_text=reasoning_template(prefill), enabled=False, prefixes=True, stop_limit=True)
        assert result['complete_parse']
        assert result['content'] == ''
        assert result['reasoning'] == 'verified'
        assert result['buffered_wire']['choices'][0]['finish_reason'] == 'length'
        assert_prefixes(result, answer=True)


@pytest.mark.parametrize('prefill', [False, True])
def test_framing_before_real_call_never_becomes_content(native_probe, prefill):
    raw = ('' if prefill else ' \n<Thought>') + 'verified</Thought>' + envelope('read_file', {'path': 'notes.txt'})
    result = native_probe(raw, template_text=reasoning_template(prefill, ' \n'), prefixes=True)
    assert result['complete_parse'] and result['content'] == ''
    assert result['reasoning'] == 'verified'
    assert calls(result) == [{'name': 'read_file', 'arguments': {'path': 'notes.txt'}}]
    assert_prefixes(result)
    assert all(p['content'] == '' for p in result['prefixes'])
    assert result['buffered_wire']['choices'][0]['finish_reason'] == 'tool_calls'


def test_disabled_mapper_exception_class_and_message_are_unchanged(tmp_path):
    source = os.environ.get('LOCALAI_PROBE_SOURCE')
    library = os.environ.get('LOCALAI_PROBE_LIBRARY')
    if not source or not library:
        pytest.skip('requires matching private CPU source/library')
    source, library = Path(source), Path(library)
    binary = tmp_path / 'mapper-error-probe'
    command = ['c++', '-std=c++17', *['-I' + str(source / p) for p in ('common', 'include', 'ggml/include', 'vendor')],
               str(Path(__file__).parent / 'fixtures/localai_mapper_error_probe.cpp'),
               '-L' + str(library), '-Wl,-rpath,' + str(library), '-lllama-common',
               '-lllama', '-lggml', '-lggml-base', '-o', str(binary)]
    subprocess.run(command, capture_output=True, text=True, check=True)
    result = json.loads(subprocess.run([str(binary)], capture_output=True, text=True, check=True,
                        env={**os.environ, 'LD_LIBRARY_PATH': str(library)}).stdout)
    if os.environ.get('LOCALAI_PROBE_RECEIPTS'):
        Path(os.environ['LOCALAI_PROBE_RECEIPTS'], 'mapper-errors.json').write_text(json.dumps(result, indent=2))
    assert result['final_parse'] == result['ordinary_mapper']
    assert result['partial_parse'] == result['ordinary_mapper']


@pytest.mark.parametrize('format_id', [2, 3, 4])
def test_untrusted_private_tag_still_has_full_raw_security_evidence(native_probe, format_id):
    trusted = native_probe()
    raw = envelope('answer', {'message': '雪\nprivate bytes </Output>'})
    result = native_probe(raw, enabled=False, raw_endpoint=True, prefixes=True,
                          body={'prompt': 'CPU parser only', 'chat_format': format_id,
                                'chat_parser': trusted['parser'], 'generation_prompt': trusted['generation_prompt']})
    assert result['active_name'] == '' and not result['complete_parse']
    assert 'Untrusted no-action parser tag' in result['parse_error']
    assert raw.encode().hex() in result['parse_error']
    assert all(not p.get('content', '') and not p.get('calls', []) for p in result['prefixes'])
