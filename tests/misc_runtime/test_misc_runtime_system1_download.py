"""First-start System 1 delivery uses private staging and preserves custom bundles."""
import io
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from cria import system1download, system1wiring
from cria.config import System1Config


def archive(names):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tf:
        for name in names:
            content = name.encode()
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            tf.addfile(entry, io.BytesIO(content))
    return data.getvalue()


class Response(io.BytesIO):
    status = 200


def test_install_validates_complete_bundle_before_atomic_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(system1download.ratelimit, "open_response", lambda *a, **kw: Response(archive(system1download.FILES)))
    destination = tmp_path / "models" / "system1"
    observed = []
    def validate(path):
        assert not destination.exists()
        observed.append({p.relative_to(path).as_posix() for p in path.rglob('*') if p.is_file()})
    system1download.install(destination, validate)
    assert observed == [system1download.FILES]
    assert (destination / "model.onnx").read_text() == "model.onnx"


def test_failed_download_and_unexpected_archive_leave_no_bundle(tmp_path, monkeypatch):
    dest = tmp_path / "model"
    monkeypatch.setattr(system1download.ratelimit, "open_response", lambda *a, **kw: Response(archive(["../bad"])))
    with pytest.raises(ValueError, match="unexpected members"):
        system1download.install(dest, lambda path: None)
    assert not dest.exists() and not (tmp_path / "bad").exists()
    monkeypatch.setattr(system1download.ratelimit, "open_response", lambda *a, **kw: Response(archive(system1download.FILES)))
    def reject(path):
        raise ValueError("invalid model")
    with pytest.raises(ValueError, match="invalid model"):
        system1download.install(dest, reject)
    assert not dest.exists()


def test_default_startup_loads_the_bundled_model_without_downloading(monkeypatch):
    from cria import system1
    monkeypatch.setattr(system1download, "install", lambda *a, **kw: pytest.fail("startup must not download"))
    seen = []
    class Runtime:
        def __init__(self, root, threads, *, capture_dir):
            seen.append(root)
            assert (root / "model.onnx").is_file()
    monkeypatch.setattr(system1, "System1Runtime", Runtime)
    cfg = System1Config()
    assert isinstance(system1wiring.build(cfg), Runtime)
    assert seen == [cfg.bundle_path] and cfg.bundle_path.is_dir()


def test_custom_missing_bundle_never_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(system1download, "install", lambda *a, **kw: pytest.fail("custom bundles must not be replaced"))
    with pytest.raises(system1wiring.StartupError, match="not a directory"):
        system1wiring.build(System1Config(bundle_dir=str(tmp_path / 'custom')))
