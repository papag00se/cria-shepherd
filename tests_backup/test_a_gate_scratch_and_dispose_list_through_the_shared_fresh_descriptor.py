"""Gate scratch cleanup (`_gate_clear` / `_gate_aux_cleanup`) and transport disposal (`gate dispose`) list the
directories they own through the ONE shared fresh-descriptor owner, so an entry added after a descriptor was opened is
still seen, removed and reported.

Class (final full suite, btrfs): a directory descriptor answers from the moment it was opened; entries added later are
invisible to `os.listdir(fd)`. The batch queue lost its `.owner`/`rmdir` that way. The same stale read was reachable in
the gate's scratch cleanup (root and every nested directory) and in `dispose`: a stale answer left files behind, and the
final `rmdir` then failed (reported, but the scratch stayed). Both now call `ownedfiles._owned_listing`, which opens a
fresh descriptor relative to the authenticated one, checks its inode against the caller's already-verified identity and
closes it — no path, no prefix, no widened deletion.

The tests drive the program text the harness really runs. A late writer adds an entry right after the directory
descriptor is opened (what a still-running checker child or a concurrent allocator does); on btrfs that is the real
defect, and everywhere a SNAPSHOT-AT-OPEN model of the filesystem reproduces it deterministically: `os.listdir` of a
descriptor returns the directory as it was when THAT descriptor was opened, and a descriptor opened later sees more."""
import errno
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time

import pytest

from cria import editsequence, gatecleanup, ownedfiles

TOKEN = "tok" + "0123456789abcdef"

# The filesystem model: functions only (nothing is installed until a caller installs them).
MODEL = r'''
import os as _os
_real_open, _real_close, _real_listdir, _snap = _os.open, _os.close, _os.listdir, {}
def _model_open(path, flags, *args, **kwargs):
    fd = _real_open(path, flags, *args, **kwargs)
    if flags & _os.O_DIRECTORY:
        _snap[fd] = sorted(_real_listdir('/proc/self/fd/%d' % fd))     # what THIS descriptor will keep answering
    return fd
def _model_close(fd):
    _snap.pop(fd, None)
    return _real_close(fd)
def _model_listdir(target='.'):
    if isinstance(target, int) and target in _snap:
        return list(_snap[target])
    return _real_listdir(target)
'''
INSTALL_MODEL = MODEL + "\n_os.open, _os.close, _os.listdir = _model_open, _model_close, _model_listdir\n"
# A late writer: right AFTER a directory is opened relative to a descriptor, add one entry to it. ``WHEN`` decides which opens.
LATE = r'''
_inner_open = _os.open
def _late_open(path, flags, *args, **kwargs):
    fd = _inner_open(path, flags, *args, **kwargs)
    if kwargs.get('dir_fd') is not None and WHEN(path, flags):
        try: _real_close(_real_open('late-' + path, _os.O_WRONLY | _os.O_CREAT | _os.O_EXCL, 0o600, dir_fd=fd if flags & _os.O_DIRECTORY else kwargs['dir_fd']))
        except FileExistsError: pass
    return fd
_os.open = _late_open
'''


def prelude(model, when):
    """Program text that installs the filesystem model (optionally) and the late writer in a child process."""
    return (INSTALL_MODEL if model else "import os as _os\n_real_open,_real_close=_os.open,_os.close\n") + \
        "WHEN = lambda path, flags: %s\n" % when + LATE


class Fs:
    """Install the model and/or the late writer in THIS process for one test; ``monkeypatch.undo()`` removes them."""
    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch

    def install(self, *, model, late_names):
        namespace = {}
        exec(MODEL, namespace)
        if model:
            for name, attribute in (("open", "_model_open"), ("close", "_model_close"), ("listdir", "_model_listdir")):
                self.monkeypatch.setattr(os, name, namespace[attribute])
        inner, real_open, real_close = os.open, namespace["_real_open"], namespace["_real_close"]

        def late_open(path, flags, *args, **kwargs):
            fd = inner(path, flags, *args, **kwargs)
            if kwargs.get("dir_fd") is not None and path in late_names and flags & os.O_DIRECTORY:
                real_close(real_open("late-" + path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd))
            return fd
        self.monkeypatch.setattr(os, "open", late_open)


@pytest.fixture
def root():
    path = tempfile.mkdtemp(prefix="cria-gate-fresh-", dir="/var/tmp" if os.path.isdir("/var/tmp") else None)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def env_for(root):
    return {"PATH": os.environ["PATH"], "HOME": root, "OLDPWD": root, "XDG_CONFIG_HOME": root,
            "XDG_DATA_HOME": root, "XDG_STATE_HOME": root, "TMPDIR": root}


def _operations():
    namespace = {}
    exec(gatecleanup.OPERATIONS_PROGRAM, namespace)
    return namespace


def _scratch(ns, root):
    """A real gate namespace with its aux directory, exactly as launch/worker leave it."""
    parent = os.path.join(root, "parent")
    os.mkdir(parent, 0o700)
    context = ns["_gate_namespace"](TOKEN, parent, create=True)
    os.mkdir("aux", 0o700, dir_fd=context["fd"])
    context["aux_identity"] = ns["_owned_id"](os.stat("aux", dir_fd=context["fd"], follow_symlinks=False))
    return context, os.path.join(parent, context["name"])


def _populate(aux):
    os.makedirs(os.path.join(aux, "sub", "deeper"))
    for name in ("a.txt", "sub/b.txt", "sub/deeper/c.txt"):
        with open(os.path.join(aux, name), "w") as stream:
            stream.write(name)


# ---- gate scratch: root and nested directories ---------------------------------------------------------------
@pytest.mark.parametrize("model", [True, False], ids=["snapshot-at-open model", "this filesystem as it is"])
def test_scratch_cleanup_removes_entries_added_after_each_descriptor_was_opened(root, monkeypatch, model):
    ns = _operations()
    context, namespace = _scratch(ns, root)
    aux = os.path.join(namespace, "aux")
    _populate(aux)
    Fs(monkeypatch).install(model=model, late_names={"aux", "sub", "deeper"})
    report = ns["_gate_aux_cleanup"](context)
    ns["_owned_close"](context)
    monkeypatch.undo()
    assert report["failed"] == [], report
    assert sorted(report["removed"]) == sorted([
        "aux/a.txt", "aux/late-aux", "aux/sub/b.txt", "aux/sub/late-sub", "aux/sub/deeper/c.txt", "aux/sub/deeper/late-deeper",
        "aux/sub/deeper/", "aux/sub/", "aux/"]), report
    assert os.listdir(namespace) == [".owner"]                  # aux is gone; the certificate stays for the caller


def test_a_stale_scratch_listing_would_have_left_files_and_failed_the_final_rmdir(root, monkeypatch):
    """The failure the fresh listing removes, shown on the unchanged shape: the late file survives and the report says so."""
    ns = _operations()
    context, namespace = _scratch(ns, root)
    _populate(os.path.join(namespace, "aux"))
    Fs(monkeypatch).install(model=True, late_names={"aux"})
    listing = ns["_owned_listing"]
    stale = ns["os"].listdir                                      # the descriptor's own (snapshot) answer
    descriptor = os.open("aux", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=context["fd"])
    try:
        assert "late-aux" not in stale(descriptor)                # the owned descriptor does not see the late entry
        identity = ns["_owned_id"](os.fstat(descriptor))
        assert "late-aux" in listing(descriptor, identity, "aux/")   # the shared owner does
    finally:
        os.close(descriptor)
        ns["_owned_close"](context)
        monkeypatch.undo()


def test_scratch_cleanup_never_follows_a_symlink_and_leaves_foreign_files_alone(root, monkeypatch):
    ns = _operations()
    context, namespace = _scratch(ns, root)
    aux = os.path.join(namespace, "aux")
    foreign = os.path.join(root, "foreign")
    os.makedirs(foreign)
    with open(os.path.join(foreign, "keep.txt"), "w") as stream:
        stream.write("not ours")
    os.symlink(foreign, os.path.join(aux, "to-foreign-dir"))
    os.symlink(os.path.join(foreign, "keep.txt"), os.path.join(aux, "to-foreign-file"))
    os.makedirs(os.path.join(aux, "sub"))
    os.symlink(foreign, os.path.join(aux, "sub", "nested-link"))
    Fs(monkeypatch).install(model=True, late_names={"aux", "sub"})
    report = ns["_gate_aux_cleanup"](context)
    ns["_owned_close"](context)
    monkeypatch.undo()
    assert report["failed"] == [] and "aux/" in report["removed"]
    assert os.listdir(foreign) == ["keep.txt"] and open(os.path.join(foreign, "keep.txt")).read() == "not ours"


def test_scratch_cleanup_keeps_reporting_a_replaced_aux_directory_and_removes_nothing(root):
    ns = _operations()
    context, namespace = _scratch(ns, root)
    aux = os.path.join(namespace, "aux")
    _populate(aux)
    os.rename(aux, aux + "-moved")
    os.mkdir(aux, 0o700)                                          # a different directory under the same name
    with open(os.path.join(aux, "foreign.txt"), "w") as stream:
        stream.write("x")
    report = ns["_gate_aux_cleanup"](context)
    ns["_owned_close"](context)
    assert report["removed"] == [] and [item["error"] for item in report["failed"]] == ["directory_identity_changed"]
    assert os.listdir(aux) == ["foreign.txt"] and os.path.isdir(os.path.join(aux + "-moved", "sub"))


def test_the_nested_listing_is_checked_against_the_identity_the_caller_verified(root):
    ns = _operations()
    context, namespace = _scratch(ns, root)
    _populate(os.path.join(namespace, "aux"))
    descriptor = os.open("aux", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=context["fd"])
    try:
        wrong = [value + 1 for value in ns["_owned_id"](os.fstat(descriptor))]
        removed, failed = [], []
        with pytest.raises(OSError) as raised:                     # a descriptor for another inode is an error, not an answer
            ns["_gate_clear"](context, descriptor, wrong, "aux/", removed, failed)
        assert raised.value.errno == errno.ESTALE and removed == []   # nothing was removed
        assert sorted(os.listdir(os.path.join(namespace, "aux"))) == ["a.txt", "sub"]
    finally:
        os.close(descriptor)
        ns["_owned_close"](context)


# ---- dispose, through the real program text in a real process ----------------------------------------------
def _dispose(root, namespace, *, model, late):
    # the late entry is added when the certificate file `.owner` is opened relative to the namespace descriptor — the
    # line the program runs just before it lists the namespace — so it lands AFTER the listing descriptor was opened
    when = "path == '.owner'" if late else "False"
    code = prelude(model, when) + "\n" + gatecleanup.PROGRAM
    spool = os.path.join(namespace, ".cria-gate-" + TOKEN + ".spool")
    return subprocess.run([sys.executable, "-c", code, "dispose", TOKEN, spool], capture_output=True, text=True,
                          env=env_for(root), cwd=root)


def _transport(ns, root, *, extra=()):
    context, namespace = _scratch(ns, root)
    for name in (".cria-gate-" + TOKEN + ".spool", ".cria-gate-" + TOKEN + ".spool.done", "request.json", *extra):
        os.close(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=context["fd"]))
    os.rmdir(os.path.join(namespace, "aux"))                      # a finished gate has settled its scratch
    ns["_owned_close"](context)
    return namespace


@pytest.mark.parametrize("model", [True, False], ids=["snapshot-at-open model", "this filesystem as it is"])
def test_dispose_removes_a_file_added_after_its_descriptor_was_opened(root, model):
    ns = _operations()
    namespace = _transport(ns, root)
    result = _dispose(root, namespace, model=model, late=True)
    assert result.returncode == 0, result.stderr
    assert not os.path.exists(namespace) and os.listdir(os.path.dirname(namespace)) == []


def test_dispose_still_refuses_unsettled_scratch_and_a_changed_certificate(root):
    ns = _operations()
    namespace = _transport(ns, root)
    os.mkdir(os.path.join(namespace, "unsettled"))
    result = _dispose(root, namespace, model=True, late=False)
    assert result.returncode != 0 and "unsettled_private_scratch" in result.stderr
    assert os.path.isdir(os.path.join(namespace, "unsettled")) and os.path.exists(os.path.join(namespace, ".owner"))  # the directory and the certificate stay
    os.rmdir(os.path.join(namespace, "unsettled"))
    os.rename(os.path.join(namespace, ".owner"), os.path.join(namespace, ".owner-moved"))
    with open(os.path.join(namespace, ".owner"), "w") as stream:                                # a different marker, same name
        stream.write("forged")
    result = _dispose(root, namespace, model=True, late=False)
    assert result.returncode != 0 and ("namespace_identity_changed" in result.stderr or "Permission denied" in result.stderr)
    assert {".owner", ".owner-moved"} <= set(os.listdir(namespace))      # the certificate and its look-alike are untouched


def test_dispose_removes_a_private_symlink_not_its_target(root):
    ns = _operations()
    foreign = os.path.join(root, "foreign.txt")
    with open(foreign, "w") as stream:
        stream.write("not ours")
    namespace = _transport(ns, root)
    os.symlink(foreign, os.path.join(namespace, "link-to-foreign"))
    result = _dispose(root, namespace, model=True, late=False)
    assert result.returncode == 0, result.stderr
    assert not os.path.exists(namespace) and open(foreign).read() == "not ours"


# ---- one listing owner, everywhere ---------------------------------------------------------------------------
def test_there_is_exactly_one_directory_listing_in_every_owner_program():
    for name, program in (("DIRECTORY_PROGRAM", ownedfiles.DIRECTORY_PROGRAM), ("editsequence", editsequence.PROGRAM),
                          ("NAMESPACE", gatecleanup.NAMESPACE_PROGRAM), ("OPERATIONS", gatecleanup.OPERATIONS_PROGRAM),
                          ("gate PROGRAM", gatecleanup.PROGRAM)):
        assert program.count("os.listdir(") == 1, name            # inside `_owned_listing`, nowhere else
        assert program.count("def _owned_listing(") == 1, name
        assert "os.listdir(context['fd'])" not in program and "os.listdir(descriptor)" not in program, name
    assert "_owned_listing(descriptor,identity,prefix)" in gatecleanup.OPERATIONS_PROGRAM
    assert "_owned_names(context)" in gatecleanup.PROGRAM
