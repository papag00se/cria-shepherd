"""Real local filesystem closure behavior; no inference or source-text assertions."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture
def area(tmp_path):
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    unit = scratch / 'closed'
    unit.mkdir()
    (unit / 'output').write_bytes(b'old check output')
    repo = tmp_path / 'repo'
    (repo / 'tests').mkdir(parents=True)
    record = dict(unit='walk-1', owner='owner-1', closure='operator final fix dispositions',
                  closed=True, fixes=[dict(id='fix-1', disposition='ACCEPTED', changes=[])],
                  scratch=[str(unit)], protected_paths=[], call_logs=[])
    return scratch, unit, repo, record


def owner():
    from suite import close_walk
    return close_walk


def invoke(area, tmp_path, status, dry=False, stdin=False):
    scratch, unit, repo, record = area
    # CLI's real default boundary: HOME/.cria/validation, never arbitrary extra flags.
    home = tmp_path / 'home'
    target = home / '.cria/validation/closed'
    target.mkdir(parents=True)
    (target / 'output').write_text('old result')
    record['scratch'] = [str(target)]
    record['fixes'][0]['disposition'] = status
    manifest = tmp_path / 'closure.json'
    if not stdin:
        manifest.write_text(json.dumps(record))
    module_root = Path(os.environ.get('RETENTION_MODULE_ROOT', Path(__file__).resolve().parents[1]))
    command = [sys.executable, '-B', str(module_root / 'suite/close_walk.py'),
               '-' if stdin else str(manifest)]
    if dry:
        command.append('--dry-run')
    guard = os.environ.get('RETENTION_GUARD_RUN')
    if guard:
        command.insert(0, guard)
    env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run(command, capture_output=True, env=env, text=True,
                          input=json.dumps(record) if stdin else None), target


@pytest.mark.parametrize('status', ['ACCEPTED', 'REJECTED'])
def test_cli_removes_closed_scratch(area, tmp_path, status):
    result, target = invoke(area, tmp_path, status)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['removed'] == [str(target)]
    assert not target.exists()


@pytest.mark.parametrize('status,dry', [('ACCEPTED', False), ('REJECTED', False),
                                      ('ACCEPTED', True)])
def test_cli_closes_from_stdin_without_creating_a_receipt(area, tmp_path, status, dry):
    result, target = invoke(area, tmp_path, status, dry=dry, stdin=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'eligible' if dry else 'removed': [str(target)]}
    assert target.exists() is dry
    assert not (tmp_path / 'closure.json').exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ['home', 'repo', 'scratch']


def test_cli_dry_run_keeps_files(area, tmp_path):
    result, target = invoke(area, tmp_path, 'ACCEPTED', dry=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['eligible'] == [str(target)]
    assert (target / 'output').read_text() == 'old result'


def test_readonly_closed_directories_remove_without_chmodding_linked_original(area):
    scratch, unit, repo, record = area
    original = repo / 'frozen-file'
    original.write_bytes(b'frozen outside bytes')
    original.chmod(0o444)
    cache = unit / 'gomodcache'
    package = cache / 'module'
    package.mkdir(parents=True)
    os.link(original, package / 'linked-copy')
    for p in (package, cache, unit):
        p.chmod(0o555)
    try:
        owner().close(record, repo=repo, scratch_roots=[scratch])
        assert not unit.exists()
        assert original.read_bytes() == b'frozen outside bytes'
        assert original.stat().st_mode & 0o777 == 0o444
    finally:
        for p in (unit, cache, package):
            if p.exists():
                p.chmod(0o755)


def test_unreadable_directory_denies_before_deleting_other_targets(area):
    scratch, unit, repo, record = area
    unreadable = scratch / 'uninspectable'
    unreadable.mkdir()
    (unreadable / 'unknown').write_bytes(b'must not assume absent')
    unreadable.chmod(0o000)
    record['scratch'].append(str(unreadable))
    try:
        with pytest.raises((ValueError, OSError)):
            owner().close(record, repo=repo, scratch_roots=[scratch])
        assert (unit / 'output').read_bytes() == b'old check output'
    finally:
        unreadable.chmod(0o755)


def test_mixed_settled_fixes_and_sibling_targets_preserve_active_neighbor(area):
    scratch, unit, repo, record = area
    sibling = scratch / 'closed-more'
    sibling.mkdir()
    (sibling / 'output').write_bytes(b'other closed output')
    active = scratch / 'closed-pending'
    active.mkdir()
    (active / 'call-log').write_bytes(b'keep active bytes')
    record['fixes'].append(dict(id='rejected-alternative', disposition='REJECTED', changes=[]))
    record['scratch'].append(str(sibling))
    record['protected_paths'] = [str(active)]
    assert owner().close(record, repo=repo, scratch_roots=[scratch]) == [str(unit), str(sibling)]
    assert not unit.exists() and not sibling.exists()
    assert (active / 'call-log').read_bytes() == b'keep active bytes'


def test_secured_unique_source_and_behavioral_test_survive(area):
    scratch, unit, repo, record = area
    for name, body in [('fix.py', b'def add(a,b): return a+b\n'),
                       ('test_fix.py', b'def test_sum(): assert add(1,2)==3\n')]:
        source = unit / name
        source.write_bytes(body)
        dest = repo / 'tests' / name
        dest.write_bytes(body)
        record['fixes'][0]['changes'].append(dict(source=str(source), worktree=str(dest)))
    assert owner().close(record, repo=repo, scratch_roots=[scratch]) == [str(unit)]
    assert not unit.exists()
    assert (repo / 'tests/fix.py').read_bytes() == b'def add(a,b): return a+b\n'
    assert (repo / 'tests/test_fix.py').is_file()


@pytest.mark.parametrize('kind', ['missing', 'different', 'outside', 'symlink'])
def test_unsecured_unique_change_denies_whole_batch(area, kind):
    scratch, unit, repo, record = area
    source = unit / 'regression.py'
    source.write_bytes(b'necessary regression')
    target = repo / 'tests/regression.py'
    if kind == 'different':
        target.write_bytes(b'wrong revision')
    elif kind == 'outside':
        target = scratch / 'copy.py'
        target.write_bytes(source.read_bytes())
    elif kind == 'symlink':
        target.symlink_to(source)
    record['fixes'][0]['changes'] = [dict(source=str(source), worktree=str(target))]
    with pytest.raises(ValueError):
        owner().close(record, repo=repo, scratch_roots=[scratch])
    assert source.read_bytes() == b'necessary regression'


@pytest.mark.parametrize('status', ['UNKNOWN', 'UNRESOLVED', 'PENDING', '', None, True])
def test_unsettled_fix_denies(area, status):
    scratch, unit, repo, record = area
    record['fixes'].append(dict(id='other', disposition=status, changes=[]))
    with pytest.raises(ValueError):
        owner().close(record, repo=repo, scratch_roots=[scratch])
    assert (unit / 'output').is_file()


@pytest.mark.parametrize('bad', [None, {}, [], {'closed': True}, {'owner': 'a'}, 'ACCEPTED'])
def test_malformed_empty_closure_denies(area, bad):
    scratch, unit, repo, record = area
    with pytest.raises(ValueError):
        owner().close(bad, repo=repo, scratch_roots=[scratch])
    assert (unit / 'output').is_file()


@pytest.mark.parametrize('key,value', [('fixes', []), ('scratch', []), ('scratch', ['']),
    ('scratch', ['/']), ('scratch', ['relative']), ('closed', False), ('closed', 'true'),
    ('owner', ''), ('unit', ''), ('closure', ''), ('call_logs', None), ('protected_paths', None)])
def test_invalid_fields_deny(area, key, value):
    scratch, unit, repo, record = area
    record[key] = value
    with pytest.raises(ValueError):
        owner().close(record, repo=repo, scratch_roots=[scratch])
    assert (unit / 'output').is_file()


def test_explicit_closed_no_findings_walk(area):
    scratch, unit, repo, record = area
    record.update(fixes=[], no_findings=True)
    owner().close(record, repo=repo, scratch_roots=[scratch])
    assert not unit.exists()


@pytest.mark.parametrize('protected_kind', ['call', 'active', 'repo', 'outside', 'root', 'parent'])
def test_protected_path_denies_before_any_delete(area, protected_kind):
    scratch, unit, repo, record = area
    if protected_kind in ('call', 'active'):
        file = unit / 'keep'
        file.write_text('must survive')
        record['call_logs' if protected_kind == 'call' else 'protected_paths'] = [str(file)]
    else:
        path = {'repo': repo, 'outside': scratch.parent / 'unrelated', 'root': scratch,
                'parent': scratch.parent}[protected_kind]
        if protected_kind == 'outside':
            path.mkdir()
            (path / 'keep').write_text('unrelated')
        record['scratch'].append(str(path))
    with pytest.raises(ValueError):
        owner().close(record, repo=repo, scratch_roots=[scratch])
    assert (unit / 'output').is_file()


@pytest.mark.parametrize('kind', ['root', 'parent', 'nested'])
def test_symlink_alias_cannot_delete_call_log(area, kind):
    scratch, unit, repo, record = area
    calls = scratch.parent / 'actual-calls'
    calls.mkdir()
    log = calls / 'response.json'
    log.write_bytes(b'actual call bytes')
    if kind == 'root':
        link = scratch / 'alias'
        link.symlink_to(calls, target_is_directory=True)
        record['scratch'] = [str(link)]
    elif kind == 'parent':
        link = scratch / 'alias'
        link.symlink_to(calls, target_is_directory=True)
        record['scratch'] = [str(link / log.name)]
    else:
        (unit / 'link').symlink_to(calls, target_is_directory=True)
    with pytest.raises(ValueError):
        owner().close(record, repo=repo, scratch_roots=[scratch])
    assert log.read_bytes() == b'actual call bytes'
    assert (unit / 'output').is_file()


def test_malformed_escape_and_duplicate_paths(area):
    scratch, unit, repo, record = area
    for paths in ([str(unit), str(unit)], [str(unit), str(unit / 'output')],
                  [str(scratch / '..' / 'repo')]):
        record['scratch'] = paths
        with pytest.raises(ValueError):
            owner().close(record, repo=repo, scratch_roots=[scratch])
        assert (unit / 'output').is_file()


def test_absent_path_is_not_successful_cleanup(area):
    scratch, unit, repo, record = area
    record['scratch'].append(str(scratch / 'absent'))
    with pytest.raises(FileNotFoundError):
        owner().close(record, repo=repo, scratch_roots=[scratch])
    assert (unit / 'output').is_file()


def test_default_roots_protect_canonical_calls_logs_documents_and_repo(area, monkeypatch):
    scratch, unit, repo, record = area
    home = scratch.parent / 'home'
    monkeypatch.setenv('HOME', str(home))
    for relative in ('.cria/calls', '.cria/logs', 'Documents'):
        path = home / relative
        path.mkdir(parents=True)
        (path / 'keep').write_text('protected')
        record['scratch'] = [str(path)]
        with pytest.raises(ValueError):
            owner().close(record, repo=repo, scratch_roots=[home])
        assert (path / 'keep').read_text() == 'protected'
    record['scratch'] = [str(owner().REPOSITORY)]
    with pytest.raises(ValueError):
        owner().close(record, repo=repo, scratch_roots=[owner().REPOSITORY.parent])


def test_cleanup_file_only_does_not_delete_neighbor(area):
    scratch, unit, repo, record = area
    file = unit / 'output'
    neighbor = unit / 'call-log'
    neighbor.write_bytes(b'preserve')
    record['scratch'] = [str(file)]
    record['call_logs'] = [str(neighbor)]
    owner().close(record, repo=repo, scratch_roots=[scratch])
    assert not file.exists()
    assert neighbor.read_bytes() == b'preserve'
