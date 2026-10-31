"""Read batches remain complete and independently attributable after the read guard's removal."""
import json
import subprocess

import pytest

from cria import denial, filecommands, resultpacket, writeproxy


def call(path, **kw):
    return {'function': {'name': 'read_file', 'arguments': json.dumps({'path': path, **kw})}}


def execute(tmp_path, args):
    with denial.receipt_scope('receipt', {}):
        command = filecommands._read_command(args)
    result = subprocess.run(['bash', '-c', command], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    record = resultpacket.read_record(result.stdout, 0, 'receipt')
    assert record is not None and record.kind == resultpacket.RAN
    return record


def test_whole_and_ranged_reads_in_a_batch_keep_their_contents(tmp_path):
    (tmp_path / 'a').write_text('first\nsecond\n')
    (tmp_path / 'b').write_text('third\nfourth\n')
    assert execute(tmp_path, {'path': 'a'}).body == b'first\nsecond\n'
    assert execute(tmp_path, {'path': 'b', 'start_line': 1, 'end_line': 1}).body == b'1: third\n'


def test_multiple_large_reads_are_not_refused(tmp_path):
    for name in ('a', 'b'):
        (tmp_path / name).write_text(name * 12000)
    for name in ('a', 'b'):
        assert execute(tmp_path, {'path': name}).body == (name * 12000).encode()


@pytest.mark.parametrize('ranged', [False, True])
@pytest.mark.parametrize('text', ['x' * 12000, 'x' * 2000, '界' * 3000, 'x'], ids=['large', 'small', 'utf8', 'single'])
def test_executed_read_preserves_requested_text(tmp_path, text, ranged):
    (tmp_path / 'input').write_text(text)
    args = {'path': 'input', **({'start_line': 1, 'end_line': 1} if ranged else {})}
    record = execute(tmp_path, args)
    assert record.observe == ('range' if ranged else 'whole')
    assert record.body == (('1: ' + text + '\n') if ranged else text).encode()


def test_read_guard_budget_api_is_removed():
    assert not hasattr(filecommands, 'read_budget')
    assert not hasattr(filecommands, 'whole_read_rooms')
    assert not hasattr(filecommands, 'read_room_scope')
    import inspect
    assert 'read_budget' not in inspect.signature(writeproxy.translate_outbound).parameters


def test_several_executed_calls_return_each_complete_body(tmp_path):
    for name in ['a', 'b']:
        (tmp_path / name).write_text('界' * 400)
    assert execute(tmp_path, {'path': 'a'}).body == ('界' * 400).encode()
    assert execute(tmp_path, {'path': 'b', 'start_line': 1, 'end_line': 1}).body == ('1: ' + '界' * 400 + '\n').encode()


def test_unknown_context_does_not_set_a_fake_harness_parameter(tmp_path):
    completion = {'choices': [{'message': {'tool_calls': [{'id': 'r', **call('a')}]}}]}
    shell = {'name': 'shell', 'schema': {'properties': {'command': {'type': 'string'}}}}
    writeproxy.translate_outbound(completion, shell, injected={'read_file'})
    args = json.loads(completion['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    assert set(args) == {'command'}


@pytest.mark.parametrize('ranged', [False, True])
def test_missing_python_never_returns_error_prose_as_file_content(tmp_path, ranged):
    (tmp_path / 'input').write_text('source bytes')
    args = {'path': 'input', **({'start_line': 1, 'end_line': 1} if ranged else {})}
    with denial.receipt_scope('receipt', {}):
        command = filecommands._read_command(args)
    result = subprocess.run(['/bin/bash', '-c', command], cwd=tmp_path, env={'PATH': str(tmp_path)}, capture_output=True, text=True)
    assert result.returncode != 0
    assert denial.is_denied(result.stdout)
    assert not result.stderr
    assert 'source bytes' not in result.stdout


@pytest.mark.parametrize('ranged', [False, True])
def test_token_estimator_does_not_silently_refuse_a_read(tmp_path, monkeypatch, ranged):
    from cria import content_reduce
    monkeypatch.setattr(content_reduce, 'est_tokens', lambda s: len(s))
    (tmp_path / 'input').write_text('x' * 400)
    args = {'path': 'input', **({'start_line': 1, 'end_line': 1} if ranged else {})}
    assert execute(tmp_path, args).body == (('1: ' if ranged else '') + 'x' * 400 + ('\n' if ranged else '')).encode()


def test_different_utf8_sizes_and_ranges_preserve_each_body(tmp_path):
    texts = {'ascii': 'a' * 400, 'utf8': '界' * 400, 'unknown': 'z' * 50, 'range': '界' * 40 + '\n'}
    for name, text in texts.items():
        (tmp_path / name).write_text(text)
    for name in ('ascii', 'utf8', 'unknown'):
        assert execute(tmp_path, {'path': name}).body == texts[name].encode()
    assert execute(tmp_path, {'path': 'range', 'start_line': 1, 'end_line': 1}).body == ('1: ' + texts['range']).encode()


def test_oversized_first_line_is_returned_whole(tmp_path):
    text = '界' * 2000 + '\nshort\n'
    (tmp_path / 'input').write_text(text)
    assert execute(tmp_path, {'path': 'input'}).body == text.encode()
    assert execute(tmp_path, {'path': 'input', 'start_line': 1, 'end_line': 1}).body == ('1: ' + '界' * 2000 + '\n').encode()


def test_prompt_usage_does_not_change_read_results(tmp_path):
    from tests.test_a_whole_read_is_sized_to_the_remaining_context import _lower, _read, _represented
    (tmp_path / 'input').write_text('evidence' * 2000)
    for usage in ({}, {'prompt_tokens': None}, {'prompt_tokens': 19000}, {'prompt_tokens': -1}):
        completion = _read('input')
        completion['usage'] = usage
        out, _ = _represented(_lower(completion, tmp_path), tmp_path)
        assert out[1]['content'] == 'evidence' * 2000
        assert not denial.refused(out[1])


def test_range_reader_preserves_crlf_bytes(tmp_path):
    (tmp_path / 'input').write_bytes(b'abcd\r\n' * 200)
    record = execute(tmp_path, {'path': 'input', 'start_line': 2, 'end_line': 3})
    assert record.body == b'2: abcd\r\n3: abcd\r\n'


def test_missing_python_in_read_instead_of_write_cannot_claim_a_read(tmp_path):
    (tmp_path / 'input').write_text('source bytes')
    with denial.receipt_scope('receipt', {}):
        command = filecommands._read_in_place_of_write('input', 'input already exists on disk.')
    result = subprocess.run(['/bin/bash', '-c', command], cwd=tmp_path, env={'PATH': str(tmp_path)}, capture_output=True, text=True)
    assert result.returncode != 0 and denial.is_denied(result.stdout)
    assert not result.stderr and 'source bytes' not in result.stdout
    assert not any('b' in json.loads(line) for line in result.stdout.splitlines() if line.startswith('{'))


def test_wire_receipt_follows_the_retained_retry_not_an_auxiliary_call():
    from cria.loop import _CoderReplyReceipts
    from types import SimpleNamespace
    def chat(body, log):
        log.restored_on_wire = {'file': body['file']}
        return b'{}'
    receipts = _CoderReplyReceipts(chat)
    first, retry = {}, {'choices': []}
    log = SimpleNamespace()
    receipts.chat({'file': 'first'}, log)
    receipts.record(first)
    receipts.chat({'file': 'retry'}, log)
    receipts.record(retry)
    receipts.chat({'file': 'auxiliary'}, log)
    assert receipts.receipt(first) == {'file': 'first'}
    assert receipts.receipt(retry) == {'file': 'retry'}
    assert receipts.receipt({'choices': []}) == {}


@pytest.mark.parametrize('repetitions', [300, 3000])
def test_early_read_aliases_and_native_reads_do_not_block_writes(tmp_path, repetitions):
    from cria import massage
    from tests.harnessenv import harness_env
    for name in ('one', 'two'):
        (tmp_path / name).write_text(name * repetitions)
    shell = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
    menu = [{'type': 'function', 'function': {'name': shell['name'], 'parameters': shell['schema']}}]
    alias = {'choices': [{'message': {'tool_calls': [{'id': 'alias', 'type': 'function', **call('one')}]}}]}
    alias = massage.apply(alias, menu)['choices'][0]['message']['tool_calls'][0]
    assert alias['function']['name'] == 'exec_command'
    native = {'id': 'read', 'type': 'function', **call('two')}
    write = {'id': 'write', 'type': 'function', 'function': {'name': 'write_file',
             'arguments': json.dumps({'path': 'made.txt', 'content': 'landed\n'})}}
    comp = {'choices': [{'message': {'tool_calls': [alias, native, write]}}]}
    writeproxy.translate_outbound(comp, shell, injected={'read_file', 'write_file'}, workspace_root=str(tmp_path))
    calls = comp['choices'][0]['message']['tool_calls']
    history = [{'role': 'assistant', 'tool_calls': calls}]
    for tc in calls:
        command = json.loads(tc['function']['arguments'])['cmd']
        result = subprocess.run(['bash', '-c', command], cwd=tmp_path, env=harness_env(tmp_path), capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        history.append({'role': 'tool', 'tool_call_id': tc['id'], 'content':
                        f'Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code 0\nOriginal token count: 9\nOutput:\n{result.stdout}{result.stderr}'})
    shown = writeproxy.represent_inbound(history, workspace_root=str(tmp_path))
    for message in shown[1:3]:
        assert not denial.refused(message)
        assert message['content'] == (('one' if message['tool_call_id'] == 'alias' else 'two') * repetitions)
    assert (tmp_path / 'made.txt').read_text() == 'landed\n'
