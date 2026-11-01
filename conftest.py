# Presence of this file makes the repo root the pytest rootdir and puts it on
# sys.path, so tests can `import cria` without an editable install.

# Test scratch never lives in /tmp (RAM-backed: a full tmpfs plus parallel suites has crashed the desktop session) and never
# outlives the session: every run gets its own directory under the caller's TMPDIR (or /var/tmp when TMPDIR is unset or in
# /tmp), pytest's tmp_path/basetemp and every tempfile call inside the tests land there, and the whole directory is removed
# when the session ends. A run that was killed leaves its directory behind; the next run removes stale ones.
import os
import shutil
import tempfile
import time

_STALE_AFTER_SECONDS = 6 * 3600


def _scratch_base() -> str:
    base = tempfile.gettempdir()
    return "/var/tmp" if base == "/tmp" or base.startswith("/tmp/") else base


def pytest_configure(config):
    base = _scratch_base()
    for name in os.listdir(base):
        path = os.path.join(base, name)
        if name.startswith("pytest-session-") and time.time() - os.path.getmtime(path) > _STALE_AFTER_SECONDS:
            shutil.rmtree(path, ignore_errors=True)
    scratch = tempfile.mkdtemp(prefix="pytest-session-", dir=base)
    os.environ["TMPDIR"] = scratch
    tempfile.tempdir = scratch
    config._session_scratch = scratch


def pytest_unconfigure(config):
    scratch = getattr(config, "_session_scratch", None)
    if scratch:
        shutil.rmtree(scratch, ignore_errors=True)
