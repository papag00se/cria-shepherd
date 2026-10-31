"""An authenticated directory keeps its certificate until it is really removed, and gets the SAME certificate back when
it cannot be.

Finding (independent review of the fresh-listing repair, S8/S9): both removals did `unlink('.owner')` THEN `rmdir`. A
writer that lands after the last listing makes `rmdir` fail after the only certificate is gone — the directory is left
uncertified, a second `gate dispose` answers PermissionError, and the batch queue silently leaves it that way.

`ownedfiles._owned_retire` is now the one removal: the certificate becomes a second name (`<name>.retiring`, exclusive)
in the parent for the instant of removal, and is linked back as the same inode if the directory cannot be removed; the
original error is re-raised unchanged. Every step revalidates what it is about to touch (descriptor, root, name, parent,
certificate identity, the retiring name's identity) and uses descriptor-relative operations. Anything that no longer
matches is left in place and reported together with the original error — never overwritten, adopted or retried.
NOT claimed: that the completion fact is the SAME inode across `dispose` attempts (each attempt re-observes the regular
`.spool.done` that is there; only the attempt itself is bound), and durability across a crash between the link and the end of the function (a killed process leaves
`<name>.retiring` and a certificate-less directory, the same window the old order had) and no recovery exists for it.

The tests drive the exec'd text of the real owner programs. The late writer is injected at the exact point between the
fresh listing and the removal, so every case is deterministic on any filesystem; they run on the default temp dir and on
a private dir under /var/tmp (btrfs on the machine that showed the stale-listing defect)."""
import errno
import os
import shutil
import subprocess
import sys
import tempfile
import time

import pytest

from cria import editsequence, gatecleanup, ownedfiles

PREFIX = ".cria-edits-"
TOKEN = "tok0123456789abcdef"
REAL = dict(listdir=os.listdir, rmdir=os.rmdir, unlink=os.unlink, link=os.link, rename=os.rename, stat=os.stat)


@pytest.fixture(params=["default-temp", "var-tmp"])
def parent(request, monkeypatch):
    base = "/var/tmp" if request.param == "var-tmp" and os.path.isdir("/var/tmp") else None
    path = tempfile.mkdtemp(prefix="cria-retire-", dir=base)
    monkeypatch.setenv("TMPDIR", path)
    yield path
    monkeypatch.undo()                       # a failed test must not leave its patched os.rmdir/unlink in the cleanup
    shutil.rmtree(path, ignore_errors=True)


def program(source):
    namespace = {}
    exec(source, namespace)
    return namespace


def queue():
    return program(editsequence.PROGRAM)


def open_context(ns, credential="turn", scope=(0,)):
    return ns["_seq_open"](credential, PREFIX, list(scope), time.monotonic() + 5)


def root_of(parent, credential="turn"):
    return os.path.join(parent, PREFIX + credential)


def inode(path):
    return REAL["stat"](path, follow_symlinks=False).st_ino


def fds():
    return set(os.listdir("/proc/self/fd"))


def after_fresh_listing(monkeypatch, action, shapes=([".owner"], ["scratch1", ".owner"], [".owner", "scratch1"])):
    """The late writer: runs once, right after the fresh probe listing of the owned directory returned."""
    fired = []
    def listing(target="."):
        result = REAL["listdir"](target)
        if isinstance(target, int) and not fired and sorted(result) in [sorted(shape) for shape in shapes]:
            fired.append(True)
            action()
        return result
    monkeypatch.setattr(os, "listdir", listing)
    return fired


def late_file(path):
    def add():
        with open(path, "w") as stream:
            stream.write("late")
    return add


# ---- the finding: a writer after the last listing -----------------------------------------------------------------
def test_queue_with_a_late_writer_keeps_a_certified_directory_and_the_original_certificate(parent, monkeypatch):
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    certificate = inode(root + "/.owner")
    after_fresh_listing(monkeypatch, late_file(root + "/late"))
    ns["_seq_done"](context, 0)                                         # best effort: nothing is raised, nothing claimed
    monkeypatch.undo()
    assert sorted(os.listdir(root)) == [".owner", "late"] and inode(root + "/.owner") == certificate
    assert os.listdir(parent) == [PREFIX + "turn"]                       # no `.retiring` left behind
    again = ns["_owned_open"]("turn", PREFIX, [0], time.monotonic() + 1, parent_path=parent, create=False)   # it authenticates again
    os.unlink(root + "/late")
    ns["_owned_retire"](again)                                           # and a retry by its owner now succeeds
    ns["_owned_close"](again)
    assert os.listdir(parent) == []


def run_dispose(parent, *, hook):
    namespace = os.path.join(parent, ".gate-private-" + TOKEN)
    prelude = ""
    if hook:
        prelude = ("import os\n_l=os.listdir; _n={'x':0}\n"
                   "def listdir(t='.'):\n r=_l(t)\n"
                   " if isinstance(t,int) and not _n['x']:\n"
                   "  _n['x']=1; open(%r+str(os.getpid()),'w').write('late')\n return r\nos.listdir=listdir\n") % (namespace + "/late-")
    code = prelude + "\n" + gatecleanup.PROGRAM
    spool = namespace + "/.cria-gate-" + TOKEN + ".spool"
    env = {"PATH": os.environ["PATH"], "HOME": parent, "OLDPWD": parent, "TMPDIR": parent}
    return subprocess.run([sys.executable, "-c", code, "dispose", TOKEN, spool], capture_output=True, text=True, env=env, cwd=parent)


def gate_namespace(parent):
    ns = program(gatecleanup.OPERATIONS_PROGRAM)
    context = ns["_gate_namespace"](TOKEN, parent, create=True)
    for name in (".cria-gate-" + TOKEN + ".spool.done", "scratch1"):
        os.close(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=context["fd"]))
    root = os.path.join(parent, context["name"])
    ns["_owned_close"](context)
    return root


def test_a_failed_dispose_keeps_the_completion_fact_and_the_second_real_dispose_succeeds(parent):
    root = gate_namespace(parent)
    certificate, done = inode(root + "/.owner"), inode(root + "/.cria-gate-" + TOKEN + ".spool.done")
    first = run_dispose(parent, hook=True)
    assert first.returncode != 0 and "Directory not empty" in first.stderr, first.stderr
    assert sorted(name if not name.startswith("late-") else "<late>" for name in os.listdir(root)) == \
        [".cria-gate-" + TOKEN + ".spool.done", ".owner", "<late>"]
    assert inode(root + "/.owner") == certificate and inode(root + "/.cria-gate-" + TOKEN + ".spool.done") == done   # the SAME facts
    assert os.listdir(parent) == [os.path.basename(root)]                                # no `.retiring*` left
    second = run_dispose(parent, hook=False)                                             # the real program, again
    assert second.returncode == 0, second.stderr
    assert os.listdir(parent) == []                                                      # directory, late file, facts: all gone


def test_dispose_repeated_after_a_late_writer_fails_again_while_the_writer_keeps_writing(parent):
    root = gate_namespace(parent)
    for _ in range(3):
        result = run_dispose(parent, hook=True)
        assert result.returncode != 0 and "Directory not empty" in result.stderr, result.stderr
        assert os.listdir(parent) == [os.path.basename(root)] and ".owner" in os.listdir(root)
    assert run_dispose(parent, hook=False).returncode == 0 and os.listdir(parent) == []


def test_dispose_still_refuses_an_active_transport_and_foreign_state_without_touching_anything(parent):
    root = gate_namespace(parent)
    os.unlink(root + "/.cria-gate-" + TOKEN + ".spool.done")                            # the producer has not finished
    before = sorted(os.listdir(root))
    active = run_dispose(parent, hook=False)
    assert active.returncode != 0 and "transport_still_active" in active.stderr
    assert sorted(os.listdir(root)) == before and os.listdir(parent) == [os.path.basename(root)]
    os.close(os.open(root + "/.cria-gate-" + TOKEN + ".spool.done", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    os.mkdir(root + "/sub")                                                              # private scratch that was not settled
    unsettled = run_dispose(parent, hook=False)
    assert unsettled.returncode != 0 and "unsettled_private_scratch" in unsettled.stderr
    # the scratch DIRECTORY, the completion fact and the certificate are all still there (files listed before the
    # directory may already have been settled, as before this change); nothing was retired
    assert {".owner", ".cria-gate-" + TOKEN + ".spool.done", "sub"} <= set(os.listdir(root))
    assert os.listdir(parent) == [os.path.basename(root)]


def test_retire_refuses_a_fact_whose_identity_is_not_the_one_the_caller_verified_for_this_attempt(parent):
    """Contract of `_owned_retire(context, facts)` only: the identity the CALLER hands in is what is held and removed;
    a different inode under that name is refused before anything changes. It does NOT say the completion fact is the
    same one across attempts — `dispose` re-observes whichever regular `.spool.done` is there on every run and passes
    that identity in; nothing carries the first attempt's fact to the second (a limitation, deliberately not pinned)."""
    root = gate_namespace(parent)
    done = root + "/.cria-gate-" + TOKEN + ".spool.done"
    ns = program(gatecleanup.OPERATIONS_PROGRAM)
    context = ns["_gate_namespace"](TOKEN, parent)
    wrong = [REAL["stat"](root).st_dev, inode(root)]                                     # not the done marker's identity
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context, {os.path.basename(done): wrong})
    assert "_identity_changed" in str(raised.value)
    assert os.path.exists(done) and os.path.exists(root + "/.owner") and os.listdir(parent) == [os.path.basename(root)]
    ns["_owned_close"](context)


# ---- every other way the removal can fail, and every thing that must not be touched ---------------------------------
def test_an_other_removal_failure_restores_the_certificate_and_raises_the_original_error_unchanged(parent, monkeypatch):
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    certificate = inode(root + "/.owner")
    def busy(*args, **kwargs):
        raise OSError(errno.EBUSY, "device busy", root)
    monkeypatch.setattr(os, "rmdir", busy)
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context)
    monkeypatch.undo()
    assert raised.value.errno == errno.EBUSY and type(raised.value) is OSError          # not masked, not wrapped
    assert os.listdir(root) == [".owner"] and inode(root + "/.owner") == certificate
    assert os.listdir(parent) == [PREFIX + "turn"]
    ns["_owned_close"](context)


def test_an_existing_retiring_name_is_never_replaced_or_adopted(parent):
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    certificate = inode(root + "/.owner")
    with open(root + ".retiring", "w") as stream:
        stream.write("foreign")
    with pytest.raises(FileExistsError):
        ns["_owned_retire"](context)                                                     # nothing had been changed yet
    assert open(root + ".retiring").read() == "foreign" and inode(root + "/.owner") == certificate
    assert os.listdir(root) == [".owner"]
    ns["_owned_close"](context)


def test_a_retiring_name_replaced_before_restore_is_left_in_place_and_reported_with_the_original_error(parent, monkeypatch):
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    def replace_then_fail(*args, **kwargs):
        with open(parent + "/foreign-held", "w") as stream:
            stream.write("foreign certificate")
        REAL["rename"](parent + "/foreign-held", root + ".retiring")                     # an atomic replacement of the name
        raise OSError(errno.ENOTEMPTY, "Directory not empty", root)
    monkeypatch.setattr(os, "rmdir", replace_then_fail)
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context)
    monkeypatch.undo()
    message = str(raised.value)
    assert "no longer has any name" in message and ".retiring" in message and "Directory not empty" in message
    assert open(root + ".retiring").read() == "foreign certificate"                      # not unlinked, not adopted
    assert ".owner" not in os.listdir(root)                                              # and nothing was restored from it
    ns["_owned_close"](context)


def test_a_blocked_restore_reports_both_artifacts_and_overwrites_nothing(parent, monkeypatch):
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    certificate = REAL["stat"](root + "/.owner").st_ino
    def block_then_fail(*args, **kwargs):
        with open(root + "/.owner", "w") as stream:
            stream.write("someone else's marker")
        raise OSError(errno.ENOTEMPTY, "Directory not empty", root)
    monkeypatch.setattr(os, "rmdir", block_then_fail)
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context)
    monkeypatch.undo()
    message = str(raised.value)
    assert "not_restored" in message and ".retiring" in message and "Directory not empty" in message
    assert open(root + "/.owner").read() == "someone else's marker"                      # never overwritten
    assert inode(root + ".retiring") == certificate                                      # the original is still held, intact
    ns["_owned_close"](context)


def test_a_retiring_name_swapped_after_it_was_verified_is_never_linked_in_as_the_certificate(parent, monkeypatch):
    """The window between "this is the certificate" and the link: the link is made from the descriptor that was
    verified, not from the name, so a foreign file swapped in at that instant cannot become `.owner`."""
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    def busy(*args, **kwargs):
        raise OSError(errno.EBUSY, "device busy", root)
    real_link = os.link
    def swap_then_link(src, dst, *args, **kwargs):
        if isinstance(src, str) and src.startswith("/proc/self/fd/"):
            with open(parent + "/foreign-held", "w") as stream:
                stream.write("foreign certificate")
            REAL["rename"](parent + "/foreign-held", root + ".retiring")
        return real_link(src, dst, *args, **kwargs)
    monkeypatch.setattr(os, "rmdir", busy)
    monkeypatch.setattr(os, "link", swap_then_link)
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context)
    monkeypatch.undo()
    # the original inode was unlinked by the replacement (nothing else names it), so it cannot be linked back: reported,
    # and the foreign file is NOT installed in its place
    assert "not_restored" in str(raised.value) and "device busy" in str(raised.value)
    assert ".owner" not in os.listdir(root)
    assert open(root + ".retiring").read() == "foreign certificate"                      # left exactly as found
    ns["_owned_close"](context)


def test_a_retiring_name_replaced_by_a_symlink_is_not_followed_and_is_reported(parent, monkeypatch):
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    with open(parent + "/elsewhere", "w") as stream:
        stream.write("target")
    def swap_then_fail(*args, **kwargs):
        REAL["unlink"](root + ".retiring")
        os.symlink(parent + "/elsewhere", root + ".retiring")
        raise OSError(errno.ENOTEMPTY, "Directory not empty", root)
    monkeypatch.setattr(os, "rmdir", swap_then_fail)
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context)
    monkeypatch.undo()
    assert "not_restored" in str(raised.value) and "Directory not empty" in str(raised.value)
    assert os.path.islink(root + ".retiring") and open(parent + "/elsewhere").read() == "target"
    assert ".owner" not in os.listdir(root)
    ns["_owned_close"](context)


def facts_context(parent):
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    with open(root + "/.fact", "w") as stream:
        stream.write("producer finished")
    return ns, context, root, [REAL["stat"](root + "/.fact").st_dev, inode(root + "/.fact")]


def test_facts_and_certificate_all_return_as_the_same_inodes_when_the_directory_cannot_be_removed(parent, monkeypatch):
    ns, context, root, identity = facts_context(parent)
    certificate, fact = inode(root + "/.owner"), inode(root + "/.fact")
    def busy(*args, **kwargs):
        raise OSError(errno.ENOTEMPTY, "Directory not empty", root)
    monkeypatch.setattr(os, "rmdir", busy)
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context, {".fact": identity})
    monkeypatch.undo()
    assert raised.value.errno == errno.ENOTEMPTY and type(raised.value) is OSError
    assert sorted(os.listdir(root)) == [".fact", ".owner"] and inode(root + "/.owner") == certificate and inode(root + "/.fact") == fact
    assert os.listdir(parent) == [PREFIX + "turn"]
    ns["_owned_retire"](context, {".fact": identity})                                    # and the repeat removes it all
    assert os.listdir(parent) == []
    ns["_owned_close"](context)


def test_an_existing_retiring_name_for_a_fact_rolls_the_certificate_hold_back(parent):
    ns, context, root, identity = facts_context(parent)
    with open(root + ".retiring.fact", "w") as stream:
        stream.write("foreign")
    with pytest.raises(FileExistsError):
        ns["_owned_retire"](context, {".fact": identity})
    assert open(root + ".retiring.fact").read() == "foreign"
    assert sorted(os.listdir(parent)) == [PREFIX + "turn", PREFIX + "turn.retiring.fact"]   # no `.retiring` for the certificate
    assert sorted(os.listdir(root)) == [".fact", ".owner"]
    ns["_owned_close"](context)


def test_a_fact_that_is_not_the_verified_inode_is_refused_and_only_our_own_name_is_removed(parent):
    ns, context, root, identity = facts_context(parent)
    wrong = [identity[0], identity[1] + 1_000_000]
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context, {".fact": wrong})
    assert ".fact_identity_changed" in str(raised.value)
    assert open(root + "/.fact").read() == "producer finished" and ".owner" in os.listdir(root)
    assert os.listdir(parent) == [PREFIX + "turn"]
    ns["_owned_close"](context)


def swap_after_hold(monkeypatch, root, parent, source, how, how_target=None):
    """After `source` was linked to its retiring name, give the name in the directory to something else."""
    real_link = os.link
    def link_then_swap(src, dst, *args, **kwargs):
        result = real_link(src, dst, *args, **kwargs)
        if src == source:
            if how == "replace":
                with open(parent + "/foreign", "w") as stream:
                    stream.write("foreign " + source)
                REAL["rename"](parent + "/foreign", root + "/" + source)
            elif how == "symlink":                      # the name now points AT the held original (by absolute path)
                REAL["unlink"](root + "/" + source)
                os.symlink(how_target, root + "/" + source)
            else:
                os.unlink(root + "/" + source)
        return result
    monkeypatch.setattr(os, "link", link_then_swap)


def test_a_fact_replaced_after_it_was_held_keeps_the_original_inode_under_its_held_name(parent, monkeypatch):
    ns, context, root, identity = facts_context(parent)
    original = inode(root + "/.fact")
    before = fds()
    swap_after_hold(monkeypatch, root, parent, ".fact", "replace")
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context, {".fact": identity})
    monkeypatch.undo()
    message = str(raised.value)
    assert ".fact_identity_changed" in message and "not_restored" in message
    assert ".fact in the directory is no longer the original (left untouched)" in message
    assert "the original inode is kept as " + PREFIX + "turn.retiring.fact" in message       # the exact surviving artifact
    assert open(root + "/.fact").read() == "foreign .fact"                                  # the foreign file: not unlinked, not adopted
    assert open(root + ".retiring.fact").read() == "producer finished"                      # the ORIGINAL inode survives
    assert inode(root + ".retiring.fact") == original and ".owner" in os.listdir(root)
    assert sorted(os.listdir(parent)) == [PREFIX + "turn", PREFIX + "turn.retiring.fact"]   # the certificate's extra name is gone
    assert fds() == before
    ns["_owned_close"](context)


def test_a_certificate_replaced_after_it_was_held_keeps_it_and_the_fact_still_returns(parent, monkeypatch):
    ns, context, root, identity = facts_context(parent)
    certificate, fact = inode(root + "/.owner"), inode(root + "/.fact")
    before = fds()
    swap_after_hold(monkeypatch, root, parent, ".owner", "replace")
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context, {".fact": identity})
    monkeypatch.undo()
    message = str(raised.value)
    assert ".owner_identity_changed" in message and "the original inode is kept as " + PREFIX + "turn.retiring" in message
    assert open(root + "/.owner").read() == "foreign .owner"                                # never overwritten, never adopted
    assert inode(root + ".retiring") == certificate                                         # the original certificate survives
    assert inode(root + "/.fact") == fact                                                   # the fact was unlinked and linked back
    assert sorted(os.listdir(parent)) == [PREFIX + "turn", PREFIX + "turn.retiring"]
    assert fds() == before
    ns["_owned_close"](context)


def test_a_fact_that_vanished_after_it_was_held_keeps_the_original_and_reports_the_original_error(parent, monkeypatch):
    ns, context, root, identity = facts_context(parent)
    original = inode(root + "/.fact")
    swap_after_hold(monkeypatch, root, parent, ".fact", "remove")
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context, {".fact": identity})
    monkeypatch.undo()
    assert "the original inode is kept as " + PREFIX + "turn.retiring.fact" in str(raised.value) and "FileNotFoundError" in str(raised.value)
    assert inode(root + ".retiring.fact") == original and not os.path.exists(root + "/.fact")
    ns["_owned_close"](context)


@pytest.mark.parametrize("source,held_suffix", [(".owner", ""), (".fact", ".fact")])
def test_a_symlink_to_the_held_original_does_not_count_as_the_original_still_being_named(parent, monkeypatch, source, held_suffix):
    """The restore must look at the name WITHOUT following it. A symlink at `.owner`/`.fact` whose target is the held
    original resolves (if followed) to the original's own identity, which would pass for "still named" and let the
    only real name be dropped — leaving a dangling link. The original stays; the symlink is left exactly as found."""
    ns, context, root, identity = facts_context(parent)
    original = inode(root + "/" + source)
    held = root + ".retiring" + held_suffix
    swap_after_hold(monkeypatch, root, parent, source, "symlink", how_target=held)
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context, {".fact": identity})
    monkeypatch.undo()
    message = str(raised.value)
    assert source + "_identity_changed" in message and source + " in the directory is no longer the original (left untouched)" in message
    assert "the original inode is kept as " + os.path.basename(held) in message
    assert os.path.islink(root + "/" + source) and os.readlink(root + "/" + source) == held     # the symlink: unchanged
    assert inode(held) == original and os.path.isfile(held)                                    # the original: still named, not dropped
    assert os.path.exists(root + "/" + source)                                                 # so the link is not dangling
    ns["_owned_close"](context)


def test_a_name_that_cannot_be_read_is_not_assumed_to_still_be_the_original(parent, monkeypatch):
    ns, context, root, identity = facts_context(parent)
    original = inode(root + "/.fact")
    real_stat = os.stat
    def refuse(path, *args, **kwargs):
        if path == ".fact":
            raise PermissionError(errno.EACCES, "denied", path)
        return real_stat(path, *args, **kwargs)
    monkeypatch.setattr(os, "stat", refuse)
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context, {".fact": identity})
    monkeypatch.undo()
    assert ".fact in the directory is unreadable" in str(raised.value) and "PermissionError" in str(raised.value)
    assert inode(root + ".retiring.fact") == original and inode(root + "/.fact") == original
    ns["_owned_close"](context)


def test_a_kept_original_is_never_adopted_a_later_retire_refuses_while_it_is_there(parent, monkeypatch):
    ns, context, root, identity = facts_context(parent)
    swap_after_hold(monkeypatch, root, parent, ".fact", "replace")
    with pytest.raises(OSError):
        ns["_owned_retire"](context, {".fact": identity})
    monkeypatch.undo()
    kept = open(root + ".retiring.fact").read()
    with pytest.raises(FileExistsError):                                                    # exclusive: nothing is taken over
        ns["_owned_retire"](context, {".fact": [REAL["stat"](root + "/.fact").st_dev, inode(root + "/.fact")]})
    assert open(root + ".retiring.fact").read() == kept and open(root + "/.fact").read() == "foreign .fact"
    assert sorted(os.listdir(parent)) == [PREFIX + "turn", PREFIX + "turn.retiring.fact"]
    ns["_owned_close"](context)


def test_a_replaced_held_name_is_reported_with_both_artifacts_and_the_fact_still_comes_back(parent, monkeypatch):
    """The held DESCRIPTOR outlives the held name: the certificate whose retiring name was replaced has no name left
    (nothing can link it back without privileges) and is said so; the fact beside it is unaffected and returns."""
    ns, context, root, identity = facts_context(parent)
    fact = inode(root + "/.fact")
    def replace_certificate_name_then_fail(*args, **kwargs):
        with open(parent + "/foreign", "w") as stream:
            stream.write("foreign")
        REAL["rename"](parent + "/foreign", root + ".retiring")
        raise OSError(errno.ENOTEMPTY, "Directory not empty", root)
    monkeypatch.setattr(os, "rmdir", replace_certificate_name_then_fail)
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context, {".fact": identity})
    monkeypatch.undo()
    message = str(raised.value)
    assert ".owner was not restored" in message and "no longer has any name" in message and "Directory not empty" in message
    assert os.listdir(root) == [".fact"] and inode(root + "/.fact") == fact              # the fact is back, same inode
    assert open(root + ".retiring").read() == "foreign" and sorted(os.listdir(parent)) == [PREFIX + "turn", PREFIX + "turn.retiring"]
    ns["_owned_close"](context)


def test_a_replaced_root_is_not_touched_and_nothing_is_linked_into_it(parent, monkeypatch):
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    certificate = inode(root + "/.owner")
    real_unlink = os.unlink
    def swap_after_unlink(path, *args, **kwargs):
        real_unlink(path, *args, **kwargs)
        if path == ".owner":
            REAL["rename"](root, root + "-moved")
            os.mkdir(root, 0o700)
            with open(root + "/foreign", "w") as stream:
                stream.write("replacement")
    monkeypatch.setattr(os, "unlink", swap_after_unlink)
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context)
    monkeypatch.undo()
    assert "namespace_identity_changed" in str(raised.value)
    assert os.listdir(root) == ["foreign"]                                               # the replacement never got a certificate
    assert os.listdir(root + "-moved") == [".owner"] and inode(root + "-moved/.owner") == certificate   # it went back to ITS directory
    assert sorted(os.listdir(parent)) == [PREFIX + "turn", PREFIX + "turn-moved"]        # no `.retiring`
    ns["_owned_close"](context)


def test_a_root_replaced_before_the_call_and_a_forged_certificate_are_refused_before_any_change(parent):
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    forged = root + "/.owner"
    REAL["rename"](forged, root + "/.owner-original")
    with open(forged, "w") as stream:
        stream.write("same bytes? no — a different file")
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context)
    assert "namespace_identity_changed" in str(raised.value)
    assert os.path.exists(root + "/.owner-original") and open(forged).read().startswith("same bytes")
    assert os.listdir(parent) == [PREFIX + "turn"]
    ns["_owned_close"](context)


def test_a_certificate_swapped_between_validation_and_linking_is_never_installed_or_removed(parent, monkeypatch):
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    real_link = os.link
    def swap_then_link(src, dst, *args, **kwargs):
        if src == ".owner":
            with open(parent + "/foreign-cert", "w") as stream:
                stream.write("foreign certificate")
            REAL["rename"](parent + "/foreign-cert", root + "/.owner")
        return real_link(src, dst, *args, **kwargs)
    monkeypatch.setattr(os, "link", swap_then_link)
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context)
    monkeypatch.undo()
    assert ".owner_identity_changed" in str(raised.value)
    assert open(root + "/.owner").read() == "foreign certificate"                        # the replacement stays exactly as found
    assert os.listdir(parent) == [PREFIX + "turn"]                                       # our own extra name was removed
    ns["_owned_close"](context)


def test_a_failed_certificate_unlink_removes_only_the_extra_name_and_raises_the_original_error(parent, monkeypatch):
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    certificate = inode(root + "/.owner")
    real_unlink = os.unlink
    def refuse(path, *args, **kwargs):
        if path == ".owner":
            raise PermissionError(errno.EPERM, "not permitted", path)
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(os, "unlink", refuse)
    with pytest.raises(PermissionError):
        ns["_owned_retire"](context)
    monkeypatch.undo()
    assert os.listdir(root) == [".owner"] and inode(root + "/.owner") == certificate and os.listdir(parent) == [PREFIX + "turn"]
    ns["_owned_close"](context)


def test_a_retiring_name_replaced_after_a_successful_removal_is_left_and_the_error_is_not_swallowed(parent, monkeypatch):
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    real_rmdir = os.rmdir
    def remove_then_replace(*args, **kwargs):
        real_rmdir(*args, **kwargs)
        with open(parent + "/foreign-held", "w") as stream:
            stream.write("foreign")
        REAL["rename"](parent + "/foreign-held", root + ".retiring")
    monkeypatch.setattr(os, "rmdir", remove_then_replace)
    with pytest.raises(OSError) as raised:
        ns["_owned_retire"](context)
    monkeypatch.undo()
    assert "directory removed" in str(raised.value) and open(root + ".retiring").read() == "foreign"
    assert not os.path.exists(root)
    ns["_owned_close"](context)


# ---- the success path, and what must stay as it was ---------------------------------------------------------------
def test_the_success_path_leaves_nothing_and_leaks_no_descriptor(parent):
    ns = queue()
    sibling = ns["_owned_open"]("sibling", PREFIX, [0], time.monotonic() + 5)           # a live queue of another credential
    context = open_context(ns)
    before = fds()
    ns["_owned_retire"](context)
    assert fds() == before
    assert sorted(os.listdir(parent)) == [PREFIX + "sibling"]
    assert os.listdir(root_of(parent, "sibling")) == [".owner"]
    ns["_owned_close"](context)
    ns["_owned_close"](sibling)


def test_no_failure_path_leaks_a_descriptor(parent, monkeypatch):
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    before = fds()
    def busy(*args, **kwargs):
        raise OSError(errno.EBUSY, "device busy")
    monkeypatch.setattr(os, "rmdir", busy)
    for _ in range(20):                                                                  # restored every time
        with pytest.raises(OSError) as raised:
            ns["_owned_retire"](context)
        assert raised.value.errno == errno.EBUSY
    assert fds() == before
    def block_then_fail(*args, **kwargs):                                                # the restore itself fails
        with open(root + "/.owner", "w") as stream:
            stream.write("marker")
        raise OSError(errno.EBUSY, "device busy")
    monkeypatch.setattr(os, "rmdir", block_then_fail)
    with pytest.raises(OSError):
        ns["_owned_retire"](context)
    monkeypatch.undo()
    assert fds() == before
    ns["_owned_close"](context)


def test_a_foreign_entry_still_keeps_the_queue_directory_and_nothing_else_deletes_a_certificate(parent):
    ns = queue()
    first = open_context(ns, scope=(0, 1))
    second = open_context(ns, scope=(0, 1))
    with open(root_of(parent) + "/notes", "w") as stream:
        stream.write("foreign work")
    ns["_seq_done"](second, 1)
    ns["_seq_done"](first, 0)
    assert sorted(os.listdir(root_of(parent))) == [".owner", "notes"] and os.listdir(parent) == [PREFIX + "turn"]


# ---- the allocation-failure path (`_owned_abandon`) is NOT changed: shown, with the reason ---------------------------
def test_abandon_keeps_its_own_order_a_failed_allocations_incomplete_certificate_is_not_resurrected(parent, monkeypatch):
    """The same unlink-then-rmdir order IS reachable here (a late writer after the listing leaves the directory without
    the failed allocation's certificate and keeps the writer's file), but the certificate being settled is the failed
    allocation's own incomplete record: restoring it would resurrect a record no participant can authenticate. The
    unchanged behaviour is pinned: the late file survives, nothing is renamed or linked, no `.retiring` appears."""
    ns = queue()
    context = open_context(ns)
    root = root_of(parent)
    after_fresh_listing(monkeypatch, late_file(root + "/late"), shapes=([],))     # the listing AFTER its own unlink
    ns["_owned_abandon"](context, tuple(context["owner"]))
    monkeypatch.undo()
    assert os.listdir(root) == ["late"] and os.listdir(parent) == [PREFIX + "turn"]
    ns["_owned_close"](context)


def test_the_programs_remove_a_certified_directory_only_through_the_shared_retire():
    shared = ownedfiles.DIRECTORY_PROGRAM
    assert shared.count("def _owned_retire(") == 1
    for name, body in (("editsequence", editsequence.PROGRAM[len(shared):]),
                       ("gate", gatecleanup.PROGRAM[len(gatecleanup.OPERATIONS_PROGRAM):])):
        assert "os.unlink('.owner'" not in body and "os.rmdir(context['name']" not in body, name
    assert "_owned_retire(context)" in editsequence.PROGRAM and "_owned_retire(context,{done:observed})" in gatecleanup.PROGRAM
