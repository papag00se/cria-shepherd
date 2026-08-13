"""Where the CODER's commands find their programs — not where cria's own process does.

cria runs as a background service. systemd starts it with a bare `PATH`
(`/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/snap/bin`) because nothing loads a login
profile for it. The coder's commands run through the harness's shell, which does load one, so they
find every toolchain installed under the user's home. Measured on this box the two disagree for
cargo, rustc, node, npm, npx, pytest and pyflakes — present for the coder, absent for cria.

WHAT THAT COST. `shutil.which` answers for cria's process, and two call sites asked it a question
about the machine:

  * ``proberun.program_is_installed`` dropped every probe whose program cria could not see. Two Rust
    cells ran no Rust tool at all; a Node cell never executed the delivered program once. The gate
    then reported "the repo's own checks that ran reported no error-class problems" over a project
    with two hard compile errors, and the coder answered "Let's compile mentally ... That's fine."
    The project did not compile for the first 45 calls.

  * ``execcheck.run`` launched the live-execution probe with cria's own environment, so `node` was a
    FileNotFoundError and the ONE check built to catch a green gate over a broken program published
    "the delivered program was not run".

Both are #5b: a claim about cria's PATH stated as a fact about the world. The world is what the
coder's shell can run, so that is what cria asks.

HOW. One `command -v` sweep through the user's login shell, once per process, cached. Discovery
only — the programs themselves still launch the way they always did, by argv with no shell, so no
quoting or injection surface changes. When there is no login shell to ask, cria does not know, and
both callers already treat "do not know" as their safe direction (probes are KEPT, interpreters are
left alone). That is the documented UNSURE-MEANS-KEEP contract, not a fallback: cria never guesses a
path, it either learned one or it did not.
"""

from __future__ import annotations

import os
import shutil
import subprocess

# One login-shell invocation is enough to read the whole PATH; per-program `command -v` would pay
# the shell's startup cost once per probe. Kept short — a login shell that cannot answer in this
# long is not going to answer.
_PATH_PROBE_TIMEOUT_S = 10.0

_cached_path: str | None = None
_probed = False


def _login_shell_path() -> str | None:
    """The `PATH` a login shell exports, or None when cria cannot ask one."""
    shell = os.environ.get("SHELL")
    if not shell or not os.access(shell, os.X_OK):
        return None
    try:
        p = subprocess.run([shell, "-lc", "printf %s \"$PATH\""],
                           capture_output=True, text=True, timeout=_PATH_PROBE_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (p.stdout or "").strip()
    return out or None


def coder_path() -> str:
    """The search path the coder's commands actually use. cria's own when it cannot be learned.

    Cached for the life of the process: a login shell's PATH does not change under a running
    service, and re-probing would put a shell start-up on every probe-selection pass."""
    global _cached_path, _probed
    if not _probed:
        _probed = True
        _cached_path = _login_shell_path()
    return _cached_path if _cached_path is not None else (os.environ.get("PATH") or "")


def which(program: str) -> str | None:
    """`shutil.which` asked about the CODER's environment instead of cria's."""
    if not program:
        return None
    return shutil.which(program, path=coder_path())


def env() -> dict:
    """cria's environment with the coder's search path — for cria's own local subprocess runs.

    Only `PATH` is borrowed. A login shell also exports the user's editor, prompt and pager, none of
    which a probe should inherit, and copying the lot would make cria's probe runs depend on
    unrelated profile edits."""
    return {**os.environ, "PATH": coder_path()}


def reset_for_tests() -> None:
    global _cached_path, _probed
    _cached_path, _probed = None, False
