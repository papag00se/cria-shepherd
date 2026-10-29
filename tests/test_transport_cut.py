"""Regression: a pinned Codex stdout cut must not expose a partial read receipt."""
import base64
import json
import random
import subprocess

from cria import denial, writeproxy


def test_synthetic_read_never_exposes_a_cut_receipt_as_file(tmp_path):
    original = base64.b64encode(random.Random(11).randbytes(12000)).decode()
    (tmp_path / 'source').write_text(original)
    completion = {'choices': [{'message': {'tool_calls': [{'id': 'r', 'type': 'function',
        'function': {'name': 'read_file', 'arguments': json.dumps({'path': 'source'})}}]}}]}
    shell = {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}}
    writeproxy.translate_outbound(completion, shell, injected={'read_file'}, workspace_root=str(tmp_path))
    call = completion['choices'][0]['message']['tool_calls'][0]
    cmd = json.loads(call['function']['arguments'])['cmd']
    result = subprocess.run(['bash', '-c', cmd], cwd=tmp_path, capture_output=True, check=True)
    raw = result.stdout.decode()
    assert len(result.stdout) + result.stdout.count(b'\n') <= 10000
    wrapped = 'Chunk ID: abcdef\nWall time: 0.1000 seconds\nProcess exited with code 0\nOutput:\n' + raw
    shown = writeproxy.represent_inbound([{'role': 'assistant', 'tool_calls': [call]},
        {'role': 'tool', 'tool_call_id': 'r', 'content': wrapped}], workspace_root=str(tmp_path))[1]
    assert denial.refused(shown)
    assert denial.read_payload(shown) is None
    assert 'No file content was returned' in shown['content']
    assert original not in shown['content']
