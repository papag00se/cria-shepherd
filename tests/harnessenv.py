"""The environment a lowered command runs in when a test plays the HARNESS.

cria's lowered programs need `python3` and coreutils on the harness side, nothing else. The tests that execute them used to
hand the command the caller's own PATH, so a version-manager shim earlier on it (mise) ran instead of an interpreter. With
HOME pointed at the test workspace (as these tests do, so nothing reaches the real home), the shim walks up from the
command's cwd, finds the operator's own config as an untrusted project file, and writes a trust error to stderr — which the
harness envelope carries as output. Whether that happens depends on where the temp dir sits, so the same test passed in one
checkout and failed in another, judging cria's result on the shim's words.

The controlled environment: `python3` is THIS interpreter (an explicit symlink), then the system's /usr/bin and /bin.
"""
import os
import sys
import tempfile

_BIN: str | None = None


def harness_bin() -> str:
    """A directory holding only `python3` -> the interpreter running the tests (created once per process, in the session's
    own temp root, which conftest removes)."""
    global _BIN
    if _BIN is None or not os.path.isdir(_BIN):
        _BIN = tempfile.mkdtemp(prefix="harness-bin-")
        os.symlink(os.path.realpath(sys.executable), os.path.join(_BIN, "python3"))
    return _BIN


def harness_path() -> str:
    return f"{harness_bin()}:/usr/bin:/bin"


def harness_env(cwd) -> dict:
    return {"PATH": harness_path(), "HOME": str(cwd), "TMPDIR": str(cwd), "LC_ALL": "C"}
