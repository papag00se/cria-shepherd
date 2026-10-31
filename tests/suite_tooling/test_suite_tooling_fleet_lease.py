"""Temporary GPU lease (suite/fleet_gpu.py + scripts/temporary_fleet_gpu.py): owner-bound, atomic,
refuses stale/malformed state instead of silently picking another GPU, cleanup is idempotent and scoped."""
import json
import os
import subprocess
import types

import pytest

from scripts.temporary_fleet_gpu import cleanup, publish_lease
from suite import fleet_gpu
from suite.restored_roles import render

OTHER = "GPU-907a7f7a-b541-8208-2bce-e1361e3110d6"
UNIT = "llama-ornith-q6.service"


def make(tmp_path, **change):
    path = tmp_path / "gpu-lease.json"
    lease = dict(schema=1, authorized=True, model="ornith1.5_9b", gpu=OTHER, profile_gpu=fleet_gpu.PROFILE_GPU,
                 owner_pid=os.getpid(), owner_start_ticks=fleet_gpu.process_start_ticks(os.getpid()),
                 operation="a" * 32)
    lease.update(change)
    path.write_text(json.dumps(lease))
    path.chmod(0o600)
    return path, lease


def args(tmp_path, operation="a" * 32):
    return types.SimpleNamespace(receipt_dir=str(tmp_path), operation=operation, model="ornith1.5_9b",
                                 gpu=OTHER, unit=UNIT)


def test_lease_moves_only_its_model_and_removal_restores_the_canonical_gpu(tmp_path):
    """A live lease selects its GPU for its model; deleting it returns to the profile GPU; another model refuses."""
    path, _ = make(tmp_path)
    assert fleet_gpu.execution_gpu("ornith1.5_9b", path=path) == OTHER
    with pytest.raises(ValueError):
        fleet_gpu.execution_gpu("phi4", path=path)
    path.unlink()
    assert fleet_gpu.execution_gpu("ornith1.5_9b", path=path) == fleet_gpu.PROFILE_GPU


@pytest.mark.parametrize("change", [dict(authorized=False), dict(owner_pid=True), dict(owner_start_ticks=1),
                                    dict(owner_pid=999999999), dict(gpu="CUDA0"), dict(gpu=fleet_gpu.PROFILE_GPU),
                                    dict(extra=True), dict(schema=True)])
def test_stale_or_malformed_lease_refuses_instead_of_falling_back(tmp_path, change):
    """Reused/dead owner PID, bool-as-int, unknown fields etc. raise; never silently the default GPU."""
    path, _ = make(tmp_path, **change)
    with pytest.raises(ValueError):
        fleet_gpu.execution_gpu("ornith1.5_9b", path=path)


def test_lease_file_with_loose_mode_or_symlink_is_not_trusted(tmp_path):
    """Only an operator-owned 0600 regular file counts; symlinked paths are not followed."""
    path, _ = make(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(path)
    with pytest.raises(OSError):
        fleet_gpu.read_lease(alias)
    path.chmod(0o644)
    with pytest.raises(ValueError):
        fleet_gpu.read_lease(path)


def test_publication_is_atomic_and_never_overwrites_another_owner(tmp_path, monkeypatch):
    """An interrupted writer leaves no active lease; a live lease from another operation is untouched."""
    path, lease = make(tmp_path)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        publish_lease(path, {**lease, "operation": "b" * 32})
    assert path.read_bytes() == original
    path.unlink()
    monkeypatch.setattr(json, "dump", lambda *a: (_ for _ in ()).throw(RuntimeError("interrupted")))
    with pytest.raises(RuntimeError):
        publish_lease(path, lease)
    assert not path.exists() and not list(tmp_path.glob("*.pending"))


def _original_and_roles():
    names = ("coder", "reasoner", "classifier", "compactor")
    original = "".join(f"[roles.{r}]\ntemperature = 0.1\n" for r in names)
    return original.encode(), {r: {"temperature": 0.6} for r in names}


def test_cleanup_stops_only_the_leased_unit_restores_config_and_is_idempotent(tmp_path):
    """Owner may be dead; cleanup stops exactly the leased unit, restores interrupted sampling bytes, once."""
    path, _ = make(tmp_path, owner_pid=999999999)
    original, roles = _original_and_roles()
    config = tmp_path / "config.toml"
    config.write_bytes(render(original.decode(), roles).encode())
    (tmp_path / "config-before.toml").write_bytes(original)
    role_path = tmp_path / "roles.json"
    role_path.write_text(json.dumps({"ornith1.5_9b": roles}))
    calls = []
    cleanup(args(tmp_path), run=lambda argv, **kw: calls.append(argv), lease_path=path, config_path=config,
            roles_path=role_path)
    assert calls == [["sudo", "-n", "systemctl", "stop", UNIT], ["sudo", "-n", "systemctl", "restart", "cria.service"]]
    assert not path.exists() and config.read_bytes() == original
    assert json.loads((tmp_path / "restored.json").read_text())["default_gpu"] == fleet_gpu.PROFILE_GPU
    cleanup(args(tmp_path), run=lambda *a, **k: pytest.fail("second cleanup must be a no-op"), lease_path=path)


def test_cleanup_keeps_ownership_until_the_restart_succeeds_and_refuses_other_operations(tmp_path):
    """A failed cria restart (config bytes already restored) keeps the lease so a retry still restarts;
    a different operation's lease is never removed."""
    path, _ = make(tmp_path)
    original, roles = _original_and_roles()
    config = tmp_path / "config.toml"
    config.write_bytes(render(original.decode(), roles).encode())
    (tmp_path / "config-before.toml").write_bytes(original)
    role_path = tmp_path / "roles.json"
    role_path.write_text(json.dumps({"ornith1.5_9b": roles}))
    calls = []

    def flaky(argv, **kw):
        calls.append(argv)
        if "restart" in argv:
            raise subprocess.CalledProcessError(1, argv)

    for foreign in (args(tmp_path, "b" * 32), types.SimpleNamespace(**{**vars(args(tmp_path)), "gpu": "GPU-other"})):
        with pytest.raises(ValueError):
            cleanup(foreign, run=lambda *a, **k: pytest.fail("foreign lease"), lease_path=path)
    with pytest.raises(subprocess.CalledProcessError):
        cleanup(args(tmp_path), run=flaky, lease_path=path, config_path=config, roles_path=role_path)
    assert path.exists() and config.read_bytes() == original
    cleanup(args(tmp_path), run=lambda argv, **kw: calls.append(argv), lease_path=path, config_path=config,
            roles_path=role_path)
    assert sum("restart" in c for c in calls) == 2 and not path.exists()
