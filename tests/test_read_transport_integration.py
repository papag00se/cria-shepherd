import json
import random
import subprocess
from pathlib import Path

import pytest
from cria import denial, writeproxy, outboundpolicies
from cria import filecommands as f


def test_real_lowering_and_representation_keep_refusal_proven(tmp_path, monkeypatch):
    monkeypatch.setattr(writeproxy, '_read_command', f._read_command)
    data = b''.join(random.Random(i).randbytes(100).hex().encode() + b'\n' for i in range(500))
    (tmp_path / 'input').write_bytes(data)
    completion = {'choices': [{'message': {'tool_calls': [{'id': 'r', 'type': 'function', 'function': {'name': 'read_file', 'arguments': json.dumps({'path': 'input'})}}]}}]}
    shell = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
    writeproxy.translate_outbound(completion, shell, injected={'read_file'}, workspace_root=str(tmp_path))
    call = completion['choices'][0]['message']['tool_calls'][0]
    p = subprocess.run(['bash', '-c', json.loads(call['function']['arguments'])['cmd']], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert len(p.stdout.encode()) <= 10000
    envelope = 'Chunk ID: abcdef\nWall time: 0.1000 seconds\nProcess exited with code 0\nOriginal token count: 100\nOutput:\n' + p.stdout
    history = [{'role': 'assistant', 'tool_calls': [call]}, {'role': 'tool', 'tool_call_id': 'r', 'content': envelope}]
    shown = writeproxy.represent_inbound(history, workspace_root=str(tmp_path))
    assert denial.refused(shown[1])
    assert denial.read_payload(shown[1]) is None
    assert 'No file content was returned' in shown[1]['content']
    assert 'Next read_file arguments:' in shown[1]['content']


def test_read_instead_proven_unlanded_and_does_not_claim_file(tmp_path, monkeypatch):
    monkeypatch.setattr(outboundpolicies, '_read_in_place_of_write', f._read_in_place_of_write)
    (tmp_path / 'input').write_bytes(random.Random(8).randbytes(18000).hex().encode())
    completion = {'choices': [{'message': {'tool_calls': [{'id': 'w', 'type': 'function', 'function': {'name': 'write_file', 'arguments': json.dumps({'path': 'input', 'content': 'replacement'})}}]}}]}
    shell = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
    writeproxy.translate_outbound(completion, shell, injected={'write_file'}, workspace_root=str(tmp_path), unread_target=lambda p: 'input exists.')
    call = completion['choices'][0]['message']['tool_calls'][0]
    p = subprocess.run(['bash', '-c', json.loads(call['function']['arguments'])['cmd']], cwd=tmp_path, capture_output=True, text=True, check=True)
    shown = writeproxy.represent_inbound([{'role':'assistant','tool_calls':[call]}, {'role':'tool','tool_call_id':'w','content':p.stdout}], workspace_root=str(tmp_path))
    assert denial.refused(shown[1]) and denial.read_payload(shown[1]) is None
    assert 'This write_file call was not run' in shown[1]['content']
    assert '⟦ctx:read-instead⟧' not in shown[1]['content']
    assert (tmp_path / 'input').read_bytes() != b'replacement'


def test_spill_and_read_instead_route_to_same_producer(tmp_path, monkeypatch):
    monkeypatch.setattr(outboundpolicies, '_format_spill_read', f._spill_read_command)
    (tmp_path / 'input').write_bytes(random.Random(4).randbytes(30000).hex().encode())
    with denial.receipt_scope('a' * 16):
        cmd = outboundpolicies._spill_read_command('input')
    result = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True, check=True)
    assert len(result.stdout) <= 10000
    assert b'No file content was returned' in result.stdout
