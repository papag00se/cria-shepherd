"""An authorized temporary device must reach both launch and PID guard, then revert by removal."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import types

import pytest

from suite import fleet_gpu

TOOLS = Path.home() / '.local/share/cria/fleet/tools'
OTHER = 'GPU-907a7f7a-b541-8208-2bce-e1361e3110d6'


def lease_file(tmp_path):
    path = tmp_path / 'gpu-lease.json'
    lease = dict(schema=1, authorized=True, model='ornith1.5_9b', gpu=OTHER,
                 profile_gpu=fleet_gpu.PROFILE_GPU, owner_pid=os.getpid(),
                 owner_start_ticks=fleet_gpu.process_start_ticks(os.getpid()), operation='a' * 32)
    path.write_text(json.dumps(lease)); path.chmod(0o600)
    return path, lease


def test_removal_restores_the_canonical_device_without_editing_profiles(tmp_path):
    path, _ = lease_file(tmp_path)
    assert fleet_gpu.execution_gpu('ornith1.5_9b', path=path) == OTHER
    path.unlink()
    assert fleet_gpu.execution_gpu('ornith1.5_9b', path=path) == fleet_gpu.PROFILE_GPU


@pytest.mark.parametrize('change', [dict(authorized=False), dict(owner_pid=True),
    dict(owner_start_ticks=1), dict(gpu='CUDA0'), dict(extra=True), dict(schema=True)])
def test_bad_or_stale_lease_refuses_instead_of_falling_back(tmp_path, change):
    path, lease = lease_file(tmp_path); lease.update(change); path.write_text(json.dumps(lease))
    with pytest.raises(ValueError): fleet_gpu.execution_gpu('ornith1.5_9b', path=path)


def test_a_lease_never_implicitly_moves_another_model(tmp_path):
    path, _ = lease_file(tmp_path)
    with pytest.raises(ValueError): fleet_gpu.execution_gpu('phi4', path=path)


def test_lease_permissions_and_symlinks_are_not_trusted(tmp_path):
    path, _ = lease_file(tmp_path); path.chmod(0o644)
    with pytest.raises(ValueError): fleet_gpu.read_lease(path)
    alias = tmp_path / 'alias'; alias.symlink_to(path)
    with pytest.raises(OSError): fleet_gpu.read_lease(alias)


def test_incomplete_publication_never_changes_the_active_device(tmp_path, monkeypatch):
    from scripts import temporary_fleet_gpu as manager
    path, lease = lease_file(tmp_path); path.unlink()
    def fail_write(*args): raise RuntimeError('interrupted writer')
    monkeypatch.setattr(manager.json, 'dump', fail_write)
    with pytest.raises(RuntimeError): manager.publish_lease(path, lease)
    assert not path.exists()
    assert fleet_gpu.execution_gpu('ornith1.5_9b', path=path) == fleet_gpu.PROFILE_GPU


def test_atomic_publication_does_not_overwrite_another_owner(tmp_path):
    from scripts.temporary_fleet_gpu import publish_lease
    path, lease = lease_file(tmp_path); original = path.read_bytes()
    with pytest.raises(FileExistsError): publish_lease(path, {**lease, 'operation': 'b' * 32})
    assert path.read_bytes() == original


def test_cleanup_stops_only_the_leased_model_and_restores_default_even_after_owner_death(tmp_path):
    from scripts.temporary_fleet_gpu import cleanup
    path, lease = lease_file(tmp_path)
    lease['owner_pid'] = 999999999
    path.write_text(json.dumps(lease))
    config = tmp_path / 'config.toml'; config.write_bytes(b'original configuration')
    (tmp_path / 'config-before.toml').write_bytes(config.read_bytes())
    roles = tmp_path / 'roles.json'; roles.write_text(json.dumps({'ornith1.5_9b': {}}))
    args = types.SimpleNamespace(receipt_dir=str(tmp_path), operation='a' * 32,
                                 model='ornith1.5_9b', gpu=OTHER, unit='llama-ornith-q6.service')
    calls = []
    cleanup(args, run=lambda argv, **kwargs: calls.append(argv), lease_path=path,
            config_path=config, roles_path=roles)
    assert calls == [['sudo', '-n', 'systemctl', 'stop', 'llama-ornith-q6.service'],
                     ['sudo', '-n', 'systemctl', 'restart', 'cria.service']]
    assert not path.exists()
    assert json.loads((tmp_path / 'restored.json').read_text())['default_gpu'] == fleet_gpu.PROFILE_GPU
    assert config.read_bytes() == b'original configuration'
    cleanup(args, run=lambda *a, **k: pytest.fail('idempotent cleanup must not stop twice'), lease_path=path)


def test_cleanup_retries_a_failed_restart_even_after_config_bytes_were_restored(tmp_path):
    from scripts.temporary_fleet_gpu import cleanup
    from suite.restored_roles import render
    import subprocess
    path, _ = lease_file(tmp_path)
    original = ''.join('[roles.' + r + ']\ntemperature = 0.1\n' for r in ('coder', 'reasoner', 'classifier', 'compactor')).encode()
    roles = {r: {'temperature': 0.6} for r in ('coder', 'reasoner', 'classifier', 'compactor')}
    config = tmp_path / 'config.toml'; config.write_bytes(render(original.decode(), roles).encode())
    (tmp_path / 'config-before.toml').write_bytes(original)
    role_path = tmp_path / 'roles.json'; role_path.write_text(json.dumps({'ornith1.5_9b': roles}))
    args = types.SimpleNamespace(receipt_dir=str(tmp_path), operation='a' * 32,
                                 model='ornith1.5_9b', gpu=OTHER, unit='llama-ornith-q6.service')
    calls = []
    def fail_restart(argv, **kwargs):
        calls.append(argv)
        if 'restart' in argv: raise subprocess.CalledProcessError(1, argv)
    with pytest.raises(subprocess.CalledProcessError):
        cleanup(args, run=fail_restart, lease_path=path, config_path=config, roles_path=role_path)
    assert path.exists(), 'failed restoration must retain its retryable ownership marker'
    assert config.read_bytes() == original
    cleanup(args, run=lambda argv, **kwargs: calls.append(argv), lease_path=path,
            config_path=config, roles_path=role_path)
    assert sum('restart' in call for call in calls) == 2
    assert not path.exists()
    assert (tmp_path / 'restored.json').is_file()


def test_cleanup_never_removes_a_different_operations_lease(tmp_path):
    from scripts.temporary_fleet_gpu import cleanup
    path, _ = lease_file(tmp_path)
    args = types.SimpleNamespace(receipt_dir=str(tmp_path), operation='b' * 32,
                                 model='ornith1.5_9b', gpu=OTHER, unit='llama-ornith-q6.service')
    with pytest.raises(ValueError):
        cleanup(args, run=lambda *a, **k: pytest.fail('must not stop another owner'), lease_path=path)
    assert path.exists()


def load_tool(name, monkeypatch):
    if not (TOOLS / (name + '.py')).is_file(): pytest.skip('machine-local fleet is not installed')
    monkeypatch.syspath_prepend(str(TOOLS))
    monkeypatch.setitem(sys.modules, 'fleet_gpu', fleet_gpu)
    spec = importlib.util.spec_from_file_location('gpu_test_' + name, TOOLS / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_real_fleet_plan_honors_the_lease_and_then_returns_to_3080(tmp_path, monkeypatch):
    path, _ = lease_file(tmp_path); monkeypatch.setattr(fleet_gpu, 'LEASE_PATH', path)
    cli = load_tool('fleet_cli', monkeypatch)
    record = cli.records()['ornith1.5_9b']
    plan = cli.make_plan(record)
    assert plan['env']['CUDA_VISIBLE_DEVICES'] == OTHER
    assert record['config']['cuda_device'] == fleet_gpu.PROFILE_GPU
    path.unlink()
    assert cli.make_plan(record)['env']['CUDA_VISIBLE_DEVICES'] == fleet_gpu.PROFILE_GPU


def test_real_frontend_checks_the_selected_device_not_the_profile_device(tmp_path, monkeypatch):
    path, _ = lease_file(tmp_path); monkeypatch.setattr(fleet_gpu, 'LEASE_PATH', path)
    frontend = load_tool('frontend_sync', monkeypatch)
    card = {'data': [{'id': 'ornith1.5_9b', 'context_length': 49152}]}
    def read(url):
        if url.endswith('/health'): return {'status': 'ok'}
        if url.endswith('/props'): return {'default_generation_settings': {'n_ctx': 49152}}
        return card
    def run(argv, **kwargs):
        assert argv[0] == 'nvidia-smi', 'no restart is needed for this matching card'
        return types.SimpleNamespace(returncode=0, stdout=f'{OTHER}, 123, 1000\n')
    result = frontend.sync_frontend('ornith1.5_9b', 49152, 123, read=read, run=run)
    assert result['GPU'] == OTHER
