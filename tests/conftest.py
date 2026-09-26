"""Bind a workspace view for every test.

cria answers questions about the coder's workspace through :mod:`cria.wsview`, which in production
is filled by a survey the HARNESS runs — the workspace is on the harness's filesystem, not cria's.
A test that builds a real directory and calls the code that inspects it has no harness, and the
workspace really is on this machine, so it binds :class:`cria.wsview.DirectView`: the same reader
API, answered from this process's own disk.

Autouse, so the several hundred tests written before the view existed keep exercising exactly what
they always did. A test about the view's OWN behaviour — the survey wire format, what "unknown"
does — binds its own view and overrides this.
"""

import os
import shutil
import tempfile

import pytest

from cria import wsview


# One private temp root per test session, removed when the session ends. Several hundred tests call
# `tempfile.mkdtemp()` without cleanup, and real gate shells spool through `${TMPDIR:-/tmp}`; left
# pointing at the shared /tmp tmpfs, ~61 runs filled 97% of its inodes (2026-09-26). Redirecting
# both here contains every one of them — see tests/test_the_suite_leaves_no_temp_litter.py.
def pytest_configure(config):
    root = tempfile.mkdtemp(prefix="suite-session-")
    config._cria_temp = (root, tempfile.tempdir, os.environ.get("TMPDIR"))
    tempfile.tempdir = root
    os.environ["TMPDIR"] = root


def pytest_unconfigure(config):
    saved = getattr(config, "_cria_temp", None)
    if saved is None:
        return
    root, previous_tempdir, previous_env = saved
    tempfile.tempdir = previous_tempdir
    if previous_env is None:
        os.environ.pop("TMPDIR", None)
    else:
        os.environ["TMPDIR"] = previous_env
    # Some fixtures chmod their files read-only; make them removable before deleting.
    for d, dirs, _files in os.walk(root):
        for name in dirs:
            try:
                os.chmod(os.path.join(d, name), 0o700)
            except OSError:
                pass
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(autouse=True)
def _local_workspace_view():
    token = wsview.bind(wsview.DirectView())
    yield
    wsview.unbind(token)
