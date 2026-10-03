"""Recovered source is inert data. Only safe lowering/refusal plumbing is executed.

Original capture: 01a0f776-6370-7912-a47a-b050238406f5,
inbound-03a9ae51-responses.json input[119]. Never import/run the fixture.
Former fake-judge tests now assert actual static findings and file outcomes.
"""
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from cria import cleanupsafety, writeproxy

INCIDENT = (Path(__file__).parent / 'fixtures/incident_parent_cleanup.py.txt').read_text()
EVIDENCE = 'shutil.rmtree(os.path.dirname(path), ignore_errors=True)'


def lower(name, args, previous=None):
    completion = {'choices': [{'message': {'tool_calls': [
        {'id': 'one', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}}]}
    view = SimpleNamespace(read_bytes=lambda path: previous.encode() if previous is not None else None)
    with patch.object(writeproxy.wsview, 'current', return_value=view), \
            patch.object(writeproxy, '_survey_due', return_value=False), \
            patch.object(writeproxy, '_litter_leg', return_value=''):
        writeproxy.translate_outbound(completion, {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}},
                                      injected={'write_file', 'edit_file'}, workspace_root='/remote/project')
    return json.loads(completion['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['cmd']


def test_exact_recovered_candidate_never_lands(tmp_path):
    assert hashlib.sha256(INCIDENT.encode()).hexdigest() == 'c79913cdf0fc195be9d9a1d7159d80275f01264f960da19e4f0c42c09ea78f74'
    target = tmp_path / 'test_http.py'
    cmd = lower('write_file', {'path': str(target), 'content': INCIDENT})
    result = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True)
    assert result.returncode != 0
    assert not target.exists()
    assert 'withheld' in result.stdout
    report = cleanupsafety.analyze('test_http.py', INCIDENT, '/remote/project')
    assert any(f.rule == 'temp_parent' and f.confidence == 'PROVEN' for f in report.findings)
    assert any('/' in f.targets and f.confidence == 'PROVEN' for f in report.findings)


@pytest.mark.parametrize('source', [
    'value = 123', '# shutil.rmtree(os.path.dirname(path))',
    'example = "shutil.rmtree(os.path.dirname(path))"', 'route = "/orders"',
    'import shutil, tempfile\np=tempfile.mkdtemp()\nshutil.rmtree(p)',
    'import os, tempfile\nfd,p=tempfile.mkstemp()\nos.unlink(p)',
    'from tempfile import TemporaryDirectory\nimport shutil, os\nwith TemporaryDirectory() as d:\n p=os.path.join(d,"owned")\n shutil.rmtree(p)',
    'import shutil\ndef f(shutil):\n shutil.rmtree("/")',
    'import shutil\nshutil=custom()\nshutil.rmtree("/")',
    'import shutil\nif False:\n shutil.rmtree("/")',
    'def f():\n return\n import shutil\n shutil.rmtree("/")',
    'class Thing:\n def unlink(self): pass\nx=Thing()\nx.unlink()',
    'open("/etc/hosts", "r")',
    'import os\nx="/external"\nx=unknown()\nos.remove(x)',
    'import os\np="/external"\n(p:="/project/owned")\nos.unlink(p)',
    'import os\np="/external"\nif (p:="/project/owned"):\n pass\nos.unlink(p)',
    'import os\np="/external"\nexec("p = unknown()")\nos.unlink(p)',
    'import shutil\ns=shutil\nshutil.rmtree=custom\ns.rmtree("/")',
    'import shutil\ndef f():\n from . import shutil\n shutil.rmtree("/")',
    'import shutil\nfor x in []:\n shutil.rmtree("/")',
    'import shutil\nwhile False:\n shutil.rmtree("/")',
    'import tempfile,shutil\nwith tempfile.TemporaryDirectory() as d:\n shutil.rmtree(d)',
])
def test_legitimate_inert_shadowed_and_unresolved_code_is_not_blocked(source):
    assert cleanupsafety.review('file.py', source, None, '/project') is None


@pytest.mark.parametrize('source', [
    'import shutil as s\ns.rmtree("/")',
    'from shutil import rmtree as erase\nerase("/external")',
    'import os\np="/external/file"\nos.unlink(p)',
    'import os\np=os.path.join("/external", "file")\nos.remove(p)',
    'from pathlib import Path\np=Path("/external") / "file"\np.write_text("x")',
    'from pathlib import Path\nPath("/external/file").parent.rmdir()',
    'open("/external/file", "w")',
    'import io\nio.open("/external/file", mode="a")',
    'import shutil\nclass C:\n def cleanup(self):\n  shutil.rmtree("/")',
    'import tempfile,os,shutil\nf=tempfile.NamedTemporaryFile()\nshutil.rmtree(os.path.dirname(f.name))',
    'import tempfile,os,shutil\nd=tempfile.TemporaryDirectory()\nshutil.rmtree(os.path.dirname(d.name))',
])
def test_resolved_mutations_block_at_restricted_boundary(source):
    assert cleanupsafety.analyze('file.py', source, '/project').blocked


def test_mixed_control_flow_is_possible_not_proven():
    source = 'import shutil\nif condition:\n p="/"\nelse:\n p="/project/owned"\nshutil.rmtree(p)'
    result = cleanupsafety.analyze('file.py', source, '/project')
    assert not result.blocked
    assert any(f.confidence == 'POSSIBLE' for f in result.findings)


def test_external_permission_is_respected_but_shared_temp_cleanup_still_blocks():
    assert not cleanupsafety.analyze('f.py', 'import os\nos.unlink("/external/file")', '/project', 'write').blocked
    assert cleanupsafety.analyze('f.py', 'import os,shutil,tempfile\nfd,p=tempfile.mkstemp()\nshutil.rmtree(os.path.dirname(p))', '/project', 'write').blocked


def test_owned_temp_parent_is_not_shared_parent():
    source='import os,shutil,tempfile\nd=tempfile.mkdtemp()\nfd,p=tempfile.mkstemp(dir=d)\nshutil.rmtree(os.path.dirname(p))'
    assert not cleanupsafety.analyze('f.py', source, '/project').blocked


def test_universal_lead_survives_when_python_cannot_resolve_the_api():
    report = cleanupsafety.analyze('f.py', 'custom.deleteTree("/external")', '/project')
    assert not report.blocked
    assert any(f.confidence == 'UNKNOWN' for f in report.findings)


def test_invalid_source_is_unknown():
    assert cleanupsafety.analyze('f.py', 'import (', '/project').coverage == 'invalid-source'


def test_edit_reviews_complete_candidate_and_preserves_disk(tmp_path):
    target = tmp_path / 'candidate.py'
    previous = INCIDENT.replace(EVIDENCE, 'pass')
    target.write_text(previous)
    cmd = lower('edit_file', dict(path=str(target), old_string=previous, new_string=INCIDENT), previous)
    result = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True)
    assert result.returncode != 0
    assert target.read_text() == previous


def test_stale_source_cannot_bypass_a_known_unsafe_finding(tmp_path):
    target = tmp_path / 'candidate.py'
    previous = INCIDENT.replace(EVIDENCE, 'pass')
    on_disk = previous + '\n# changed elsewhere\n'
    target.write_text(on_disk)
    cmd = lower('edit_file', dict(path=str(target), old_string=previous, new_string=INCIDENT), previous)
    result = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True)
    assert result.returncode != 0
    assert target.read_text() == on_disk
    assert 'Read the current file' in result.stdout


def test_missing_edit_source_abstains_without_guessing():
    cmd=lower('edit_file', dict(path='remote.py', old_string='pass', new_string=EVIDENCE))
    assert 'withheld' not in cmd


def test_repair_removing_operation_passes(tmp_path):
    target = tmp_path / 'candidate.py'
    previous='import shutil\nshutil.rmtree("/")\n'
    target.write_text(previous)
    cmd=lower('edit_file', dict(path=str(target), old_string=previous, new_string='value=1\n'), previous)
    result=subprocess.run(['bash','-c',cmd], capture_output=True, text=True)
    assert result.returncode == 0
    assert target.read_text() == 'value=1\n'
