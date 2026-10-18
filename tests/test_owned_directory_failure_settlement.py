"""Failed shared allocation must settle only this attempt's exclusive resources."""
import errno
import os
import time

import pytest

from cria import ownedfiles


@pytest.mark.parametrize('failure', ['create', 'write', 'flush'])
@pytest.mark.parametrize('interference', ['none', 'descendant', 'marker', 'directory'])
def test_failed_certificate_allocation_settles_only_its_own_resources(tmp_path, monkeypatch, failure, interference):
    namespace = {}
    exec(ownedfiles.DIRECTORY_PROGRAM, namespace)
    root = tmp_path / '.cria-edits-token'
    moved = tmp_path / 'moved'
    original_open, original_fdopen = os.open, os.fdopen

    def fail():
        if interference == 'descendant':
            (root / 'notes').write_text('foreign work')
        elif interference == 'marker':
            marker = root / '.owner'
            if marker.exists():
                marker.rename(root / 'original-marker')
            marker.write_text('foreign marker')
        elif interference == 'directory':
            root.rename(moved)
            root.mkdir()
            (root / 'notes').write_text('replacement work')
        raise OSError(errno.ENOSPC if failure == 'write' else errno.EIO, 'injected certificate failure')

    def opening(path, flags, *args, **kwargs):
        if path == '.owner' and flags & os.O_CREAT and failure == 'create':
            fail()
        return original_open(path, flags, *args, **kwargs)

    class FaultStream:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            try:
                if args[0] is None:
                    self.flush()
            finally:
                self.stream.close()
            return False
        def fileno(self):
            return self.stream.fileno()
        def write(self, data):
            if failure == 'write':
                self.stream.write(data[:5])
                self.stream.flush()
                fail()
            return self.stream.write(data)
        def flush(self):
            self.stream.flush()
            if failure == 'flush':
                fail()

    def fdopen(fd, mode, *args, **kwargs):
        stream = original_fdopen(fd, mode, *args, **kwargs)
        return FaultStream(stream) if mode == 'wb' else stream

    with monkeypatch.context() as patch:
        patch.setattr(os, 'open', opening)
        patch.setattr(os, 'fdopen', fdopen)
        with pytest.raises(OSError, match='injected certificate failure'):
            namespace['_owned_open']('token', '.cria-edits-', [0, 1], time.monotonic(), parent_path=str(tmp_path))
    if interference == 'none':
        assert list(tmp_path.iterdir()) == []
        # A settled allocation can be retried and authenticated normally.
        context = namespace['_owned_open']('token', '.cria-edits-', [0, 1], time.monotonic(), parent_path=str(tmp_path))
        assert namespace['_owned_valid'](context)
        namespace['_owned_close'](context)
    elif interference == 'descendant':
        assert (root / 'notes').read_text() == 'foreign work'
        assert not (root / '.owner').exists()
    elif interference == 'marker':
        assert (root / '.owner').read_text() == 'foreign marker'
        if failure != 'create':
            assert (root / 'original-marker').exists()
    else:
        assert (root / 'notes').read_text() == 'replacement work'
        assert moved.is_dir()
        if failure != 'create':
            assert (moved / '.owner').exists()
    if interference != 'none':
        # Unknown resources stay unauthenticated; retries must not adopt them.
        with pytest.raises(PermissionError):
            namespace['_owned_open']('token', '.cria-edits-', [0, 1], time.monotonic(), parent_path=str(tmp_path))


def test_pre_authentication_observation_cannot_transfer_allocation_authority(tmp_path, monkeypatch):
    namespace = {}
    exec(ownedfiles.DIRECTORY_PROGRAM, namespace)
    root = tmp_path / '.cria-edits-token'
    original_open = os.open
    replaced = False

    def opening(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == '.owner' and not flags & os.O_CREAT and not replaced:
            replaced = True
            (root / '.owner').rename(root / 'original-marker')
            (root / '.owner').write_text('foreign replacement')
        return original_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, 'open', opening)
        with pytest.raises(PermissionError):
            namespace['_owned_open']('token', '.cria-edits-', [0, 1], time.monotonic(), parent_path=str(tmp_path))
    assert replaced
    assert (root / '.owner').read_text() == 'foreign replacement'
    assert (root / 'original-marker').is_file()
    with pytest.raises(PermissionError):
        namespace['_owned_open']('token', '.cria-edits-', [0, 1], time.monotonic(), parent_path=str(tmp_path))
    assert (root / '.owner').read_text() == 'foreign replacement'


def test_failed_authentication_never_settles_a_preexisting_directory(tmp_path):
    namespace = {}
    exec(ownedfiles.DIRECTORY_PROGRAM, namespace)
    root = tmp_path / '.cria-edits-token'
    root.mkdir()
    (root / '.owner').write_text('unrelated record')
    before = (root / '.owner').stat().st_ino
    with pytest.raises(PermissionError):
        namespace['_owned_open']('token', '.cria-edits-', [0, 1], time.monotonic(), parent_path=str(tmp_path))
    assert (root / '.owner').read_text() == 'unrelated record'
    assert (root / '.owner').stat().st_ino == before
