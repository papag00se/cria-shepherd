"""Cargo configuration and cache roots must be inside the cell's writable sandbox."""
import os
import shutil
import subprocess

import pytest

from suite import run


@pytest.mark.skipif(not shutil.which('cargo'), reason='real Cargo isolation regression')
@pytest.mark.parametrize('ambient', [False, True])
def test_cargo_uses_cell_home_and_its_config(tmp_path, monkeypatch, ambient):
    root = tmp_path / 'installs'
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    host_home = tmp_path / 'read-only-host-cargo'
    host_home.mkdir()
    (host_home / 'config.toml').write_text('[build]\nrustc = "nonexistent-host-rustc"\n')
    if ambient:
        monkeypatch.setenv('CARGO_HOME', str(host_home))
    else:
        monkeypatch.delenv('CARGO_HOME', raising=False)
    monkeypatch.setattr(run, '_cell_install_root', lambda ws: root)
    monkeypatch.setattr(run, '_ruby_keep_path', lambda: [])
    monkeypatch.setattr(run, '_ruby_cell_install_dirs', lambda root: [])
    monkeypatch.setattr(run, '_cell_install_bin_dirs', lambda root: [])
    env = {**os.environ, **run._isolated_installs(workspace)}
    # Fail before running Cargo against any inherited host directory.
    home = env.get('CARGO_HOME', str(run.Path.home() / '.cargo'))
    assert home == str(root / 'cargo')
    cargo_home = root / 'cargo'
    cargo_home.mkdir(parents=True)
    target = root / 'cargo-build'
    (cargo_home / 'config.toml').write_text('[build]\ntarget-dir = ' + repr(str(target)).replace("'", '"') + '\n')
    (workspace / 'Cargo.toml').write_text('[package]\nname="cargo-home-probe"\nversion="0.1.0"\nedition="2021"\n')
    (workspace / 'src').mkdir()
    (workspace / 'src/main.rs').write_text('fn main() { println!("cell-home"); }\n')
    before = (host_home / 'config.toml').read_bytes()
    result = subprocess.run(['bash', '-lc', 'cargo build --offline'], cwd=workspace,
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    binary = target / 'debug/cargo-home-probe'
    assert subprocess.check_output([str(binary)], text=True).strip() == 'cell-home'
    assert (host_home / 'config.toml').read_bytes() == before
    assert not (workspace / 'target').exists()
