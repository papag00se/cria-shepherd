"""Candidate code is inert data: tests execute only file plumbing or refusal printf.

Fixture: recovered orders-api-py test_http.py, session
01a0f776-6370-7912-a47a-b050238406f5, inbound-03a9ae51-responses.json input[119].
The source reuses a temp database path for /-prefixed routes before rmtree(dirname(path)).
Never import this fixture or run its tests. Fake judge replies exercise the safety
pipeline; these tests do not establish a live reasoner's accuracy.
"""
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from cria import cleanupsafety, writeproxy

INCIDENT = (Path(__file__).parent / 'fixtures/incident_parent_cleanup.py.txt').read_text()
EVIDENCE = 'shutil.rmtree(os.path.dirname(path), ignore_errors=True)'


def unsafe(evidence=EVIDENCE, target='/'):
    return json.dumps(dict(verdict='UNSAFE', evidence=evidence,
                           reason='The parent of the reused route variable can be the filesystem root.', target=target))


def lower(name, args, ask, previous=None):
    completion = {'choices': [{'message': {'tool_calls': [
        {'id': 'one', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}}]}
    view = SimpleNamespace(read_bytes=lambda path: previous.encode() if previous is not None else None)
    with patch.object(writeproxy.wsview, 'current', return_value=view), \
            patch.object(writeproxy, '_survey_due', return_value=False), \
            patch.object(writeproxy, '_litter_leg', return_value=''):
        writeproxy.translate_outbound(completion, {'name': 'exec_command', 'schema': {'properties': {'cmd': {'type': 'string'}}}},
                                      injected={'write_file', 'edit_file'}, workspace_root='/remote/project',
                                      cleanup_ask=ask)
    return json.loads(completion['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['cmd']


def test_exact_recovered_candidate_never_lands(tmp_path):
    assert hashlib.sha256(INCIDENT.encode()).hexdigest() == 'c79913cdf0fc195be9d9a1d7159d80275f01264f960da19e4f0c42c09ea78f74'
    ask = Mock(return_value=unsafe())
    target = tmp_path / 'test_http.py'
    cmd = lower('write_file', {'path': str(target), 'content': INCIDENT}, ask)
    result = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True)
    assert result.returncode != 0
    assert not target.exists()
    assert INCIDENT in ask.call_args.args[0]  # complete candidate, no clipping
    assert 'withheld' in result.stdout


@pytest.mark.parametrize('source,evidence', [
    ('fs.rmSync(path.dirname(route), {recursive: true});', 'fs.rmSync(path.dirname(route), {recursive: true})'),
    ('std::fs::remove_dir_all(route.parent().unwrap())?;', 'std::fs::remove_dir_all(route.parent().unwrap())'),
    ('os.RemoveAll(filepath.Dir(route))', 'os.RemoveAll(filepath.Dir(route))'),
    ('FileUtils.deleteDirectory(route.getParentFile());', 'FileUtils.deleteDirectory(route.getParentFile())'),
    ('rm -rf "$parent"', 'rm -rf "$parent"'),
])
def test_operation_tripwire_is_not_python_or_extension_bound(source, evidence):
    ask = Mock(return_value=unsafe(evidence))
    assert cleanupsafety.review('arbitrary.filename', source, None, '/project', ask)
    ask.assert_called_once()


@pytest.mark.parametrize('source', [
    'value = 123',
    '# shutil.rmtree(os.path.dirname(path))',
    '// fs.rmSync(path.dirname(route), {recursive: true})',
    '/* os.RemoveAll(filepath.Dir(route)) */',
    'example = "shutil.rmtree(os.path.dirname(path))"',
    'route = "/orders"',
])
def test_ordinary_edits_and_inert_examples_make_zero_calls(source):
    ask = Mock(side_effect=AssertionError('must not call'))
    assert cleanupsafety.review('file', source, None, '/project', ask) is None
    ask.assert_not_called()


def test_unchanged_candidate_does_not_repeat_review():
    ask = Mock()
    assert cleanupsafety.review('file', INCIDENT, INCIDENT, '/project', ask) is None
    ask.assert_not_called()


@pytest.mark.parametrize('answer', ['{"verdict":"SAFE"}', '{"verdict":"UNKNOWN"}', 'garbage',
                                  unsafe('invented operation'), unsafe('import os')])
def test_safe_unknown_and_ungrounded_findings_do_not_refuse(answer):
    assert cleanupsafety.review('file', INCIDENT, None, '/project', lambda _: answer) is None


def test_reasoner_failure_is_silent_not_safety_approval():
    log = Mock()
    assert cleanupsafety.review('file', INCIDENT, None, '/project', Mock(side_effect=OSError()), log) is None
    assert log.emit.call_args.kwargs['verdict'] == 'UNKNOWN'


def test_safe_owned_cleanup_passes_unchanged():
    source = 'fs.rmSync(ownedTemporaryDirectory, {recursive: true});'
    assert cleanupsafety.review('file', source, None, '/project', lambda _: '{"verdict":"SAFE"}') is None


def test_edit_reviews_complete_candidate_and_preserves_disk(tmp_path):
    target = tmp_path / 'candidate.txt'
    previous = INCIDENT.replace(EVIDENCE, 'pass')
    target.write_text(previous)
    ask = Mock(return_value=unsafe())
    cmd = lower('edit_file', dict(path=str(target), old_string=previous, new_string=INCIDENT), ask, previous)
    result = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True)
    assert result.returncode != 0
    assert target.read_text() == previous
    assert INCIDENT in ask.call_args.args[0]


def test_stale_source_cannot_bypass_a_known_unsafe_finding(tmp_path):
    target = tmp_path / 'candidate.txt'
    previous = INCIDENT.replace(EVIDENCE, 'pass')
    # The exact old text still matches, so executing the normal edit would succeed.
    on_disk = previous + '\n# changed elsewhere\n'
    target.write_text(on_disk)
    cmd = lower('edit_file', dict(path=str(target), old_string=previous, new_string=INCIDENT),
                Mock(return_value=unsafe()), previous)
    result = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True)
    assert result.returncode != 0
    assert target.read_text() == on_disk
    assert 'Read the current file' in result.stdout


def test_literal_boundary_checks_are_only_for_operation_arguments():
    source = 'route = "/orders"\nfs.rmSync("/outside", {recursive:true});'
    ask = Mock(return_value='{"verdict":"UNKNOWN"}')
    assert cleanupsafety.review('file', source, None, '/project', ask) is None
    assert '{"target": "/outside", "external": true}' in ask.call_args.args[0]
    assert '{"target": "/orders"' not in ask.call_args.args[0]


def test_missing_edit_source_abstains_without_guessing():
    ask = Mock()
    lower('edit_file', dict(path='remote', old_string='pass', new_string=EVIDENCE), ask)
    ask.assert_not_called()


def test_repair_removing_operation_does_not_need_judge(tmp_path):
    ask = Mock()
    target = tmp_path / 'candidate.txt'
    target.write_text('before '+EVIDENCE)
    cmd = lower('edit_file', dict(path=str(target), old_string=EVIDENCE, new_string='safe'), ask, target.read_text())
    result = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True)
    assert result.returncode == 0
    assert target.read_text() == 'before safe'
    ask.assert_not_called()
