"""The pager is executable through Codex's real, machine-policy sandbox without a model."""
import json
import os
import shutil
import subprocess
import tomllib

import pytest

from cria import dirguard, initial_inventory
from suite import run


@pytest.mark.skipif(not shutil.which('codex'), reason='requires local Codex sandbox')
def test_inventory_pages_in_real_sandbox(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace with 'quote' ; metachar $cash `tick`"
    workspace.mkdir()
    installs = tmp_path / 'installs'
    installs.mkdir()
    monkeypatch.setattr(run, 'CELL_INSTALLS_DIR', installs)
    scratch = run._cell_install_root(workspace)
    scratch.mkdir()
    home = tmp_path / 'codex-home'
    home.mkdir()
    for i in range(60):
        (workspace / f'file-{i:03}.py').write_text('def okay(): pass\n')
    try:
        settings = run._codex_argv('unused', workspace)[2:-1]
    except ValueError as exc:
        pytest.skip(f'machine-local sandbox policy unavailable: {exc}')
    profile = tomllib.loads(next(a for a in settings if a.startswith('default_permissions=')))['default_permissions']
    command = initial_inventory.browse_command(str(workspace))
    assert dirguard.command_refusal(command + ' 0', 'none', str(workspace)) is None
    offset, pages = 0, []
    while True:
        result = subprocess.run(['codex', 'sandbox', '-P', profile, *settings, '-C', str(workspace),
                                 '--', 'sh', '-c', command + ' ' + str(offset)],
                                env={**os.environ, 'CODEX_HOME': str(home), 'TMPDIR': str(scratch)},
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert len(result.stdout) < 2048
        header, payload = result.stdout.split('\n', 1)
        tag, start, end, total = header.split()
        assert tag == 'current-inventory' and int(start) == offset
        payload = payload.removesuffix('\n')
        assert len(payload) == int(end) - offset
        pages.append(payload)
        offset = int(end)
        if offset == int(total):
            break
    data = json.loads(''.join(pages))
    assert len(pages) > 1 and len(data['files']) == 60 and not data['errors']
    assert len(list(workspace.iterdir())) == 60
