"""Go's real defaults must resolve inside the roots the suite permits writing."""
import json
import os
import shutil
import subprocess

import pytest

from suite import run


@pytest.fixture
def cell_env(tmp_path, monkeypatch):
    root = tmp_path / 'installs'
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    monkeypatch.setattr(run, '_cell_install_root', lambda ws: root)
    monkeypatch.setattr(run, '_ruby_keep_path', lambda: [])
    monkeypatch.setattr(run, '_ruby_cell_install_dirs', lambda root: [])
    monkeypatch.setattr(run, '_cell_install_bin_dirs', lambda root: [])
    return workspace, root


@pytest.mark.skipif(not shutil.which('go'), reason='real Go environment regression')
@pytest.mark.parametrize('ambient', [False, True])
def test_real_go_cache_paths_stay_in_writable_cell_root(cell_env, monkeypatch, ambient):
    workspace, root = cell_env
    for key in ('GOPATH', 'GOMODCACHE', 'GOCACHE'):
        if ambient:
            monkeypatch.setenv(key, '/host/read-only/' + key.lower())
        else:
            monkeypatch.delenv(key, raising=False)
    env = {**os.environ, **run._isolated_installs(workspace)}
    result = subprocess.run(['bash', '-lc', 'go env -json GOPATH GOMODCACHE GOCACHE'],
                            cwd=workspace, env=env, text=True, capture_output=True, check=True)
    actual = json.loads(result.stdout)
    assert actual == {'GOPATH': str(root / 'go'),
                      'GOMODCACHE': str(root / 'gomodcache'),
                      'GOCACHE': str(root / 'xdg-cache' / 'go-build')}


@pytest.mark.skipif(not shutil.which('go'), reason='real Go cache-write regression')
def test_real_offline_go_build_writes_only_cell_caches(cell_env):
    workspace, root = cell_env
    env = {**os.environ, **run._isolated_installs(workspace), 'GOPROXY': 'off',
           'GOSUMDB': 'off', 'GOTOOLCHAIN': 'local'}
    paths = json.loads(subprocess.check_output(
        ['go', 'env', '-json', 'GOPATH', 'GOMODCACHE', 'GOCACHE'], cwd=workspace,
        env=env, text=True))
    # Fail before any Go command could write an inherited/shared host cache.
    assert all(os.path.commonpath([value, str(root)]) == str(root) for value in paths.values())
    (workspace / 'go.mod').write_text('module cacheprobe\n\ngo 1.22\n')
    (workspace / 'main.go').write_text('package main\nfunc main() {}\n')
    subprocess.run(['go', 'build', '-o', str(workspace / 'probe'), '.'], cwd=workspace,
                   env=env, check=True, capture_output=True, timeout=90)
    assert (workspace / 'probe').is_file()
    assert any((root / 'xdg-cache' / 'go-build').rglob('*'))
    assert paths['GOPATH'] == str(root / 'go')  # sumdb state also belongs to this GOPATH
