"""Real offline Maven must use cell-local repository and JVM temporary state."""
import json
import os
import shutil
import subprocess

import pytest

from suite import run


@pytest.mark.skipif(not shutil.which('mvn'), reason='real Maven isolation regression')
@pytest.mark.parametrize('ambient', [False, True])
def test_maven_repository_and_java_temp_are_cell_local(tmp_path, monkeypatch, ambient):
    root = tmp_path / 'cell installs'
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    host = tmp_path / 'host'
    host.mkdir()
    poison_repo = host / 'not-a-directory'
    poison_repo.write_text('untouched host sentinel')
    poison_tmp = host / 'nonexistent-temp'
    if ambient:
        monkeypatch.setenv('JAVA_TOOL_OPTIONS',
                           f'-Dprobe.preserved=yes -Dmaven.repo.local={poison_repo} '
                           f'-Djava.io.tmpdir={poison_tmp}')
    else:
        monkeypatch.delenv('JAVA_TOOL_OPTIONS', raising=False)
    monkeypatch.delenv('MAVEN_OPTS', raising=False)
    monkeypatch.delenv('MAVEN_ARGS', raising=False)
    monkeypatch.setattr(run, '_cell_install_root', lambda ws: root)
    monkeypatch.setattr(run, '_ruby_keep_path', lambda: [])
    monkeypatch.setattr(run, '_ruby_cell_install_dirs', lambda root: [])
    monkeypatch.setattr(run, '_cell_install_bin_dirs', lambda root: [])
    env = {**os.environ, **run._isolated_installs(workspace)}
    # This fails before invoking Java against any inherited host location.
    assert json.dumps('-Dmaven.repo.local=' + str(root / 'm2' / 'repository')) in env.get('JAVA_TOOL_OPTIONS', '')
    assert json.dumps('-Djava.io.tmpdir=' + str(root / 'java-tmp')) in env['JAVA_TOOL_OPTIONS']
    if ambient:
        assert '-Dprobe.preserved=yes' in env['JAVA_TOOL_OPTIONS']
    (workspace / 'pom.xml').write_text(
        '<project><modelVersion>4.0.0</modelVersion><groupId>probe</groupId>'
        '<artifactId>isolation</artifactId><version>1</version><packaging>pom</packaging></project>')
    before = {p.relative_to(host): p.read_bytes() for p in host.rglob('*') if p.is_file()}
    result = subprocess.run(['bash', '-lc', 'mvn --offline --batch-mode validate && java -XshowSettings:properties -version'],
                            cwd=workspace, env=env, capture_output=True, text=True, timeout=90)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert 'maven.repo.local = ' + str(root / 'm2' / 'repository') in output
    assert 'java.io.tmpdir = ' + str(root / 'java-tmp') in output
    if ambient:
        assert 'probe.preserved = yes' in output
    assert (root / 'm2' / 'repository').is_dir()
    assert (root / 'java-tmp').is_dir()
    assert {p.relative_to(host): p.read_bytes() for p in host.rglob('*') if p.is_file()} == before
    assert not poison_tmp.exists()
    assert not (workspace / 'target').exists()
