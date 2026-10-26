"""A finished edit batch removes its queue directory on EVERY filesystem; a descriptor does not decide what a
directory holds.

Incident (final full suite, test_edit_batch_order, TMPDIR on btrfs): the last finisher of a batch listed the queue
directory through the descriptor it had opened while the directory was still empty. On btrfs that descriptor keeps
answering from that moment (`[]` although `.owner` and the marks are there), so the `.owner` unlink and the `rmdir`
were skipped and `.cria-edits-*` stayed in $TMPDIR. tmpfs answers correctly, which is why it only showed up where the
suite's TMPDIR was not tmpfs.

The owner program (`ownedfiles.DIRECTORY_PROGRAM`, shared by the edit queue) now lists through a FRESH descriptor
opened relative to the owned one and checked against the certificate's directory identity — never a path, never a
prefix. These tests drive the program the harness really runs (the text is exec'd, nothing is re-implemented), on a
real non-tmpfs directory where the machine has one and, everywhere, with the stale listing simulated exactly where
btrfs produces it. Descriptor identity and credential scope are pinned: a foreign entry, a sibling queue, a replaced
directory and a wrong certificate each leave everything alone."""
import errno
import os
import shutil
import stat
import tempfile
import threading
import time

import pytest

from cria import editsequence, ownedfiles

PREFIX = ".cria-edits-"


def _non_tmpfs_parent():
    """A private directory on the machine's root filesystem when /var/tmp exists (btrfs on the machine that showed
    the defect), else the ordinary temp dir; the caller removes it."""
    base = "/var/tmp" if os.path.isdir("/var/tmp") and os.access("/var/tmp", os.W_OK) else None
    return tempfile.mkdtemp(prefix="cria-owned-", dir=base)


@pytest.fixture(params=["default-temp", "var-tmp"])
def parent(request, monkeypatch):
    path = tempfile.mkdtemp(prefix="cria-owned-") if request.param == "default-temp" else _non_tmpfs_parent()
    monkeypatch.setenv("TMPDIR", path)                  # the program's own default parent
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _program(source=None):
    namespace = {}
    exec(source or editsequence.PROGRAM, namespace)      # the very text the harness is sent
    return namespace


def _open(ns, credential, scope):
    return ns["_seq_open"](credential, PREFIX, list(scope), time.monotonic() + 5)


def _names(parent, credential="batch"):
    return sorted(os.listdir(os.path.join(parent, PREFIX + credential)))


# ---- the defect, through the real program on a real directory -------------------------------------------------
def test_the_last_finisher_removes_the_queue_even_though_it_opened_the_directory_while_empty(parent):
    """The creator opens the directory empty, the other participants add their marks through their own descriptors,
    and the creator finishes LAST. Fails before on btrfs (residue); on tmpfs it is the regression guard."""
    ns = _program()
    creator = _open(ns, "batch", [0, 1, 2])
    for index in (0, 1):                                 # other processes: their own contexts, their own marks
        other = _open(ns, "batch", [0, 1, 2])
        ns["_seq_done"](other, index)
    assert sorted(_names(parent)) == [".owner", "0", "1"]
    ns["_seq_done"](creator, 2)
    assert os.listdir(parent) == [], "the completed batch left its queue directory behind"


def test_a_batch_finished_in_call_order_also_leaves_nothing(parent):
    ns = _program()
    contexts = [_open(ns, "batch", [0, 1, 2]) for _ in range(3)]    # every participant opened while only `.owner` existed
    for index, context in enumerate(contexts):
        ns["_seq_done"](context, index)
    assert os.listdir(parent) == []


# ---- the same defect, deterministically on any filesystem -----------------------------------------------------
def _stale_for(descriptor, answer):
    """os.listdir that answers ``answer`` for ONE descriptor number (the owned one, as btrfs does) and truthfully for
    every other descriptor and for paths."""
    real = os.listdir

    def listing(target="."):
        if isinstance(target, int) and target == descriptor:
            return list(answer)
        return real(target)
    return listing


def test_a_stale_listing_on_the_owned_descriptor_does_not_keep_a_finished_queue(parent, monkeypatch):
    ns = _program()
    creator = _open(ns, "batch", [0, 1])
    other = _open(ns, "batch", [0, 1])
    ns["_seq_done"](other, 0)
    monkeypatch.setattr(os, "listdir", _stale_for(creator["fd"], []))      # what btrfs returned at the last finisher
    ns["_seq_done"](creator, 1)
    assert os.listdir(parent) == []


def test_an_abandoned_allocation_is_settled_through_a_fresh_listing_too(parent, monkeypatch):
    """`_owned_abandon` asked the same stale descriptor whether the directory was empty after its own `.owner` was
    removed; a stale non-empty answer kept the directory."""
    ns = _program()
    context = _open(ns, "batch", [0])
    allocated_owner = tuple(context["owner"])
    monkeypatch.setattr(os, "listdir", _stale_for(context["fd"], [".owner"]))
    ns["_owned_abandon"](context, allocated_owner)
    ns["_owned_close"](context)
    assert os.listdir(parent) == []


# ---- descriptor identity, credential scope and ownership are preserved --------------------------------------
def test_a_foreign_entry_keeps_the_directory_and_the_certificate(parent):
    ns = _program()
    creator = _open(ns, "batch", [0, 1])
    other = _open(ns, "batch", [0, 1])
    with open(os.path.join(parent, PREFIX + "batch", "notes"), "w") as stream:
        stream.write("someone else's work")
    ns["_seq_done"](other, 0)
    ns["_seq_done"](creator, 1)
    assert _names(parent) == [".owner", "notes"]          # marks of the scope are gone, the foreign file and the certificate stay


def test_a_sibling_queue_is_never_touched_there_is_no_prefix_cleanup(parent):
    ns = _program()
    sibling = _open(ns, "other-batch", [0, 1])           # a live queue of another credential, same prefix
    ns["_seq_done"](sibling, 0)
    creator = _open(ns, "batch", [0])
    ns["_seq_done"](creator, 0)
    assert os.listdir(parent) == [PREFIX + "other-batch"]
    assert _names(parent, "other-batch") == [".owner", "0"]


def test_a_replaced_directory_is_neither_listed_nor_removed(parent):
    ns = _program()
    context = _open(ns, "batch", [0])
    root = os.path.join(parent, PREFIX + "batch")
    os.rename(root, root + "-moved")
    os.mkdir(root, 0o700)                                 # a different directory under the same name
    with open(os.path.join(root, "foreign"), "w") as stream:
        stream.write("x")
    ns["_seq_done"](context, 0)
    assert sorted(os.listdir(parent)) == [PREFIX + "batch", PREFIX + "batch-moved"]
    assert os.listdir(root) == ["foreign"]                   # the replacement is not ours: not listed, not removed
    assert os.listdir(root + "-moved") == [".owner"]         # nothing was marked, nothing was removed in the original


def test_the_fresh_listing_is_checked_against_the_certificates_directory_identity(parent):
    ns = _program()
    context = _open(ns, "batch", [0])
    assert sorted(ns["_owned_names"](context)) == [".owner"]
    open(os.path.join(parent, PREFIX + "batch", "late"), "w").close()      # entries added after the open are seen
    assert sorted(ns["_owned_names"](context)) == [".owner", "late"]
    forged = dict(context, root=[context["root"][0], context["root"][1] + 1])
    with pytest.raises(OSError) as raised:                # a descriptor for another inode is an error, not an answer
        ns["_owned_names"](forged)
    assert raised.value.errno == errno.ESTALE
    ns["_owned_close"](context)


def test_the_fresh_descriptor_is_closed_and_nothing_is_widened(parent):
    ns = _program()
    context = _open(ns, "batch", [0])
    before = set(os.listdir("/proc/self/fd"))
    for _ in range(50):
        ns["_owned_names"](context)
    assert set(os.listdir("/proc/self/fd")) == before        # no descriptor leaked
    mode = stat.S_IMODE(os.stat(os.path.join(parent, PREFIX + "batch")).st_mode)
    assert mode == 0o700                                      # the directory's permissions were not touched
    ns["_owned_close"](context)


def test_the_shared_program_carries_the_listing_once_and_nothing_lists_the_owned_descriptor_directly():
    shared = ownedfiles.DIRECTORY_PROGRAM
    assert shared.count("def _owned_names(") == 1
    assert "os.listdir(context['fd'])" not in shared and "os.listdir(context['fd'])" not in editsequence.PROGRAM
    assert "_owned_names(context)" in editsequence.PROGRAM and "_owned_names(context)" in shared


# ---- the whole batch, the way the harness runs it, on a real non-tmpfs directory ---------------------------
def test_a_reversed_concurrent_batch_leaves_no_queue_directory_where_the_temp_dir_is_not_tmpfs(monkeypatch):
    from tests import test_edit_batch_order as batch      # the existing scenario, unchanged (its assertions are not edited)
    cmds = batch._lower(batch._FX["edits"])
    workspace, target = batch._workspace(batch._FX["base"])
    reference_tmp = _non_tmpfs_parent()
    queue_tmp = _non_tmpfs_parent()
    try:
        for command in cmds:                              # the reference: one at a time, in call order
            batch._run(command, workspace, reference_tmp)
        expected = target.read_text()
        workspace2, target2 = batch._workspace(batch._FX["base"])
        threads = []
        for index in reversed(range(len(cmds))):          # the LAST call starts first
            thread = threading.Thread(target=batch._run, args=(cmds[index], workspace2, queue_tmp))
            thread.start()
            threads.append(thread)
            time.sleep(0.05)
        [thread.join() for thread in threads]
        assert target2.read_text() == expected
        assert os.listdir(queue_tmp) == [], "the batch's queue directory outlived the batch"
    finally:
        shutil.rmtree(reference_tmp, ignore_errors=True)
        shutil.rmtree(queue_tmp, ignore_errors=True)
