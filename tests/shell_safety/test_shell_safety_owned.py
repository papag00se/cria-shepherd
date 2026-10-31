"""Owned (certified) directories, real files in tmp; only os.rmdir/os.open faults are injected."""
import errno
import os
import time

import pytest

from cria import gatecleanup, ownedfiles

PREFIX, REAL_OPEN = ".cria-edits-", os.open


def opened(parent, create=True):
    ns = {}
    exec(ownedfiles.DIRECTORY_PROGRAM, ns)
    return ns, ns["_owned_open"]("turn", PREFIX, [0], time.monotonic() + 5, parent_path=str(parent), create=create)


@pytest.mark.parametrize("late_writer", [False, True], ids=["EBUSY", "late writer"])
def test_a_directory_that_cannot_be_removed_keeps_its_certificate_and_facts_as_the_same_inodes(tmp_path, monkeypatch, late_writer):
    """S8/S9: unlink('.owner') THEN rmdir left an uncertified directory when a writer landed in between; now the original
    error returns unchanged, certificate and facts come back as the same inodes, and a retry succeeds."""
    ns, context = opened(tmp_path)
    root = tmp_path / (PREFIX + "turn")
    (root / "done").write_text("fact")
    inodes = {n: (root / n).stat().st_ino for n in (".owner", "done")}
    facts = {"done": ns["_owned_id"](os.stat(root / "done"))}
    code = errno.ENOTEMPTY if late_writer else errno.EBUSY

    def fail(*args, **kwargs):
        if late_writer:
            (root / "late").write_text("late")
        raise OSError(code, "cannot remove", str(root))
    monkeypatch.setattr(os, "rmdir", fail)
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context, facts)
    monkeypatch.undo()
    assert type(raised.value) is OSError and raised.value.errno == code
    assert os.listdir(tmp_path) == [root.name] and {n: (root / n).stat().st_ino for n in inodes} == inodes   # no `.retiring*`
    (root / "late").unlink(missing_ok=True)
    ns["_owned_retire"](opened(tmp_path, create=False)[1], facts)
    assert os.listdir(tmp_path) == []


def test_nothing_foreign_is_replaced_adopted_or_removed_when_the_removal_is_refused_or_fails(tmp_path, monkeypatch):
    """A wrong fact, a taken or replaced `.retiring` name, a replaced root: reported, left exactly as found."""
    ns, context = opened(tmp_path)
    root, retiring = tmp_path / (PREFIX + "turn"), tmp_path / (PREFIX + "turn.retiring")
    (root / "done").write_text("fact")
    with pytest.raises(OSError, match="_identity_changed"):
        ns["_owned_retire"](context, {"done": ns["_owned_id"](os.stat(root))})
    retiring.write_text("foreign")
    with pytest.raises(FileExistsError):
        ns["_owned_retire"](context)
    assert retiring.read_text() == "foreign" and sorted(os.listdir(root)) == [".owner", "done"]

    def replace_then_fail(*args, **kwargs):
        os.unlink(retiring)
        retiring.write_text("foreign certificate")
        raise OSError(errno.ENOTEMPTY, "Directory not empty", str(root))
    monkeypatch.setattr(os, "rmdir", replace_then_fail)
    retiring.unlink()
    with pytest.raises(OSError, match="no longer has any name.*Directory not empty"):
        ns["_owned_retire"](context)
    monkeypatch.undo()
    assert retiring.read_text() == "foreign certificate" and not (root / ".owner").exists()
    os.rename(root, tmp_path / "moved")
    root.mkdir(mode=0o700)
    with pytest.raises(OSError, match="namespace_identity_changed"):
        ns["_owned_retire"](context)
    assert os.listdir(root) == []


def test_gate_scratch_cleanup_sees_entries_added_after_each_descriptor_was_opened(tmp_path, monkeypatch):
    """Class (btrfs): a descriptor answers from when it was opened, so a stale listdir(fd) left files behind and the final
    rmdir failed. Model: snapshot-at-open plus a late writer; a symlink is removed, never followed."""
    snaps, real_listdir = {}, os.listdir

    def opening(path, flags, *args, **kwargs):
        fd = REAL_OPEN(path, flags, *args, **kwargs)
        if flags & os.O_DIRECTORY and kwargs.get("dir_fd") is not None and path != ".":   # "." is the fresh probe
            snaps[fd] = sorted(real_listdir(fd))
            os.close(REAL_OPEN("late-" + path, os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=fd))
        return fd
    ns = {}
    exec(gatecleanup.OPERATIONS_PROGRAM, ns)
    context = ns["_gate_namespace"]("tok0123456789abcdef", str(tmp_path), create=True)
    os.mkdir("aux", 0o700, dir_fd=context["fd"])
    aux = tmp_path / context["name"] / "aux"
    (aux / "sub" / "deeper").mkdir(parents=True)
    (tmp_path / "target").write_text("must survive")
    (aux / "link").symlink_to(tmp_path / "target")
    context["aux_identity"] = ns["_owned_id"](os.stat(aux))
    monkeypatch.setattr(os, "open", opening)
    monkeypatch.setattr(os, "listdir", lambda t=".": list(snaps[t]) if isinstance(t, int) and t in snaps else real_listdir(t))
    result = ns["_gate_aux_cleanup"](context)
    assert result["failed"] == [] and not aux.exists() and (tmp_path / "target").read_text() == "must survive"
    assert {"aux/late-aux", "aux/sub/late-sub", "aux/sub/deeper/late-deeper", "aux/link"} <= set(result["removed"])
