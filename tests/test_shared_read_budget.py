import json
import subprocess

import pytest

from cria import denial, filecommands


def call(path, **kw):
    return {'function': {'name': 'read_file', 'arguments': json.dumps({'path': path, **kw})}}


def test_ranges_share_budget():
    assert filecommands.whole_read_rooms([call('a'), call('b', start_line=1)], 1000) == {0: 500, 1: 500}


def test_known_reads_cannot_overbook():
    rooms = filecommands.whole_read_rooms([call('a'), call('b')], 1000, lambda _: 800)
    assert sum(rooms.values()) <= 1000


@pytest.mark.parametrize('ranged', [False, True])
@pytest.mark.parametrize('text,room,accepted', [('x' * 12000, 16000, True), ('x' * 2000, 1000, False), ('界' * 3000, 4000, True), ('x' * 12000, None, True), ('x', 0, False)], ids=['large', 'small-over-budget', 'utf8', 'unknown', 'zero'])
def test_executed_read_uses_only_text_budget(tmp_path, text, room, accepted, ranged):
    (tmp_path / 'input').write_text(text)
    args = {'path': 'input', **({'start_line': 1, 'end_line': 1} if ranged else {})}
    with denial.receipt_scope('receipt', {}), filecommands.read_room_scope(room):
        command = filecommands._read_command(args)
    result = subprocess.run(['bash', '-c', command], cwd=tmp_path, capture_output=True, text=True)
    records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    assert any('b' in record for record in records) == accepted


def test_density_and_reply_cost_reduce_allowance():
    assert filecommands.read_budget(10000, 2000, 1000, 1000, 1) == 9600
    assert filecommands.read_budget(10000, 2000, 1000, 1000, 2) == 4800
    assert filecommands.read_budget(10000, 2000, 9000, 1000, 1) == 0


def test_several_executed_calls_cannot_each_spend_the_entire_budget(tmp_path):
    from cria import content_reduce
    for name in ['a', 'b']:
        (tmp_path / name).write_text('界' * 400)
    calls = [call('a'), call('b', start_line=1, end_line=1)]
    rooms = filecommands.whole_read_rooms(calls, 1000)
    spent = 0
    for i, tc in enumerate(calls):
        with filecommands.read_room_scope(rooms[i]):
            command = filecommands._read_command(json.loads(tc['function']['arguments']))
        result = subprocess.run(['bash', '-c', command], cwd=tmp_path, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert not denial.is_denied(result.stdout)
        spent += content_reduce.est_tokens(result.stdout)
    assert spent <= 1000 // 4


def test_unknown_context_does_not_set_a_fake_harness_parameter(tmp_path):
    from cria import writeproxy
    completion = {'choices': [{'message': {'tool_calls': [{'id': 'r', **call('a')}]}}]}
    shell = {'name': 'shell', 'schema': {'properties': {'command': {'type': 'string'}}}}
    writeproxy.translate_outbound(completion, shell, injected={'read_file'}, read_budget=None)
    args = json.loads(completion['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    assert set(args) == {'command'}


@pytest.mark.parametrize('ranged', [False, True])
def test_missing_python_never_returns_error_prose_as_file_content(tmp_path, ranged):
    (tmp_path / 'input').write_text('source bytes')
    args = {'path': 'input', **({'start_line': 1, 'end_line': 1} if ranged else {})}
    with denial.receipt_scope('receipt', {}), filecommands.read_room_scope(1000):
        command = filecommands._read_command(args)
    result = subprocess.run(['/bin/bash', '-c', command], cwd=tmp_path, env={'PATH': str(tmp_path)}, capture_output=True, text=True)
    assert result.returncode != 0
    assert denial.is_denied(result.stdout)
    assert not result.stderr
    assert 'source bytes' not in result.stdout


def _dense_estimator(s: str) -> int:
    return len(s)


@pytest.mark.parametrize('ranged', [False, True])
def test_the_actual_estimator_is_used_even_when_it_diverges_from_chars_over_four(tmp_path, monkeypatch, ranged):
    from cria import content_reduce
    monkeypatch.setattr(content_reduce, 'est_tokens', _dense_estimator)
    (tmp_path / 'input').write_text('x' * 400)
    args = {'path': 'input', **({'start_line': 1, 'end_line': 1} if ranged else {})}
    with denial.receipt_scope('receipt', {}), filecommands.read_room_scope(800):
        command = filecommands._read_command(args)
    result = subprocess.run(['bash', '-c', command], cwd=tmp_path, capture_output=True, text=True)
    assert denial.is_denied(result.stdout)
    assert not any('b' in json.loads(line) for line in result.stdout.splitlines() if line.startswith('{'))


def test_different_utf8_sizes_and_unknown_ranges_share_a_conservative_total(tmp_path):
    from cria import content_reduce
    texts = {'ascii': 'a' * 400, 'utf8': '界' * 400, 'unknown': 'z' * 50, 'range': '界' * 40 + '\n'}
    for name, text in texts.items():
        (tmp_path / name).write_text(text)
    sizes = {name: len(text.encode()) for name, text in texts.items() if name in ('ascii', 'utf8')}
    calls = [call('ascii'), call('utf8'), call('unknown'), call('range', start_line=1, end_line=1)]
    rooms = filecommands.whole_read_rooms(calls, 2400, sizes.get)
    assert rooms == {0: 400, 1: 1200, 2: 400, 3: 400}
    total = 0
    for i, tc in enumerate(calls):
        with filecommands.read_room_scope(rooms[i]):
            command = filecommands._read_command(json.loads(tc['function']['arguments']))
        result = subprocess.run(['bash', '-c', command], cwd=tmp_path, capture_output=True, text=True)
        assert result.returncode == 0 and not denial.is_denied(result.stdout)
        total += content_reduce.est_tokens(result.stdout)
    assert total <= 2400 // 4


def test_oversized_first_line_offers_no_impossible_window(tmp_path):
    (tmp_path / 'input').write_text('界' * 2000 + '\nshort\n')
    with denial.receipt_scope('receipt', {}), filecommands.read_room_scope(400):
        command = filecommands._read_command({'path': 'input'})
    result = subprocess.run(['bash', '-c', command], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0 and denial.is_denied(result.stdout)
    assert 'larger than can be returned' in result.stdout
    assert 'end_line=' not in result.stdout
    assert '界' not in result.stdout


def test_loop_budget_uses_explicit_prompt_usage_and_this_requests_reserve(monkeypatch):
    from cria import bodykeys, modelview, tokenratio
    from cria.config import Role
    from tests.test_a_whole_read_is_sized_to_the_remaining_context import _coder_loop, _Log, _read
    from dataclasses import replace
    owner = _coder_loop(20000)
    owner._ctx = replace(owner._ctx, coder_role=Role(name='coder', backend='local', output_reserve=5000))
    monkeypatch.setattr(tokenratio, 'observed', lambda _: 2.0)
    completion = _read('input')
    completion['usage'] = {'prompt_tokens': 3000, 'completion_tokens': 999999, 'total_tokens': 9999999}
    log = _Log()
    monkeypatch.setattr(owner, '_coder_turn_impl', lambda *args, **kwargs: completion)
    frame = {bodykeys.OUTPUT_RESERVE: 7000, 'max_tokens': 123}
    returned = owner._coder_turn(None, frame, {}, step=1, rlog=log)
    expected = filecommands.read_budget(20000, 7000, 3000, modelview.reply_tokens(returned) * 2, 2)
    assert owner.read_budget_bytes(returned, log) == expected
    # Another request's reserve is never borrowed for an unrelated completion.
    other = json.loads(json.dumps(completion))
    assert owner.read_budget_bytes(other, log) == filecommands.read_budget(20000, 5000, 3000, modelview.reply_tokens(other) * 2, 2)
    for usage in ({}, {'prompt_tokens': None}, {'prompt_tokens': True}, {'prompt_tokens': -1}):
        other['usage'] = usage
        assert owner.read_budget_bytes(other, log) is None


def test_recommended_window_counts_crlf_exactly_like_the_range_reader(tmp_path):
    import re
    (tmp_path / 'input').write_bytes((b'abcd\r\n' * 200))
    with filecommands.read_room_scope(400):
        command = filecommands._read_command({'path': 'input'})
    result = subprocess.run(['bash', '-c', command], cwd=tmp_path, capture_output=True, text=True)
    end = int(re.search(r'end_line=(\d+)', result.stdout)[1])
    for extra, denied in [(0, False), (1, True)]:
        with filecommands.read_room_scope(400):
            command = filecommands._read_command({'path': 'input', 'start_line': 1, 'end_line': end + extra})
        result = subprocess.run(['bash', '-c', command], cwd=tmp_path, capture_output=True, text=True)
        assert denial.is_denied(result.stdout) == denied


def test_missing_python_in_read_instead_of_write_cannot_claim_a_read(tmp_path):
    (tmp_path / 'input').write_text('source bytes')
    with denial.receipt_scope('receipt', {}), filecommands.read_room_scope(1000):
        command = filecommands._read_in_place_of_write('input', 'input already exists on disk.')
    result = subprocess.run(['/bin/bash', '-c', command], cwd=tmp_path, env={'PATH': str(tmp_path)}, capture_output=True, text=True)
    assert result.returncode != 0 and denial.is_denied(result.stdout)
    assert not result.stderr and 'source bytes' not in result.stdout
    assert not any('b' in json.loads(line) for line in result.stdout.splitlines() if line.startswith('{'))


def test_reserve_follows_the_retained_retry_not_an_auxiliary_call():
    from cria import bodykeys
    from cria.loop import _CoderReplyReceipts
    from types import SimpleNamespace
    receipts = _CoderReplyReceipts(lambda body, log: b'{}')
    first, retry = {}, {'choices': []}
    log = SimpleNamespace()
    receipts.chat({bodykeys.OUTPUT_RESERVE: 5000}, log)
    receipts.record(first)
    receipts.chat({'max_tokens': 7000}, log)
    receipts.record(retry)
    receipts.chat({bodykeys.OUTPUT_RESERVE: 9000}, log)
    assert receipts.reserve_receipt(first) == 5000
    assert receipts.reserve_receipt(retry) == 7000
    assert receipts.reserve_receipt({'choices': []}) is None


@pytest.mark.parametrize('budget,accepted', [(1000, False), (4000, True)])
def test_early_read_aliases_share_the_allowance_with_reads_and_do_not_block_writes(tmp_path, budget, accepted):
    from copy import deepcopy
    from cria import loop, massage, writeproxy
    from tests.harnessenv import harness_env
    for name in ('one', 'two'):
        (tmp_path / name).write_text(name * 300)
    shell = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
    menu = [{'type': 'function', 'function': {'name': shell['name'], 'parameters': shell['schema']}}]
    alias = {'choices': [{'message': {'tool_calls': [{'id': 'alias', 'type': 'function', **call('one')}]}}]}
    alias = massage.apply(alias, menu)['choices'][0]['message']['tool_calls'][0]
    assert alias['function']['name'] == 'exec_command'
    native = {'id': 'read', 'type': 'function', **call('two')}
    write = {'id': 'write', 'type': 'function', 'function': {'name': 'write_file',
             'arguments': json.dumps({'path': 'made.txt', 'content': 'landed\n'})}}
    comp = {'choices': [{'message': {'tool_calls': [alias, native, write]}}]}
    before = deepcopy(comp)
    writeproxy.translate_outbound(comp, shell, injected={'read_file', 'write_file'},
                                  workspace_root=str(tmp_path), read_budget=budget)
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
        assert denial.refused(message) != accepted
        if accepted:
            assert message['content'] == (('one' if message['tool_call_id'] == 'alias' else 'two') * 300)
    assert (tmp_path / 'made.txt').read_text() == 'landed\n'
    if not accepted:
        assert not loop._extract_reads(shown)
    assert before['choices'][0]['message']['tool_calls'][0]['function']['name'] == 'exec_command'
