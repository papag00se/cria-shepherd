"""Which programs the CODER's shell can launch — asked of the coder's machine, not of cria's.

cria runs as a background service. systemd starts it with a bare `PATH`
(`/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/snap/bin`) because nothing loads a login
profile for it. The coder's commands run through the harness's shell, which does load one, so they
find every toolchain installed under the user's home. Measured on one box the two disagree for
cargo, rustc, node, npm, npx, pytest and pyflakes — present for the coder, absent for cria.

WHAT THAT COST. `shutil.which` answers for cria's process, and two call sites asked it a question
about the machine:

  * ``proberun.program_is_installed`` dropped every probe whose program cria could not see. Two Rust
    cells ran no Rust tool at all; a Node cell never executed the delivered program once. The gate
    then reported "the repo's own checks that ran reported no error-class problems" over a project
    with two hard compile errors, and the coder answered "Let's compile mentally ... That's fine."

  * ``dirguard`` composes a sentence telling the coder which command to type. A route through a tool
    cria could not see read as "there is no project-local route", and the tool was on PATH all along.

Both are #5b: a claim about cria's PATH stated as a fact about the world.

HOW IT IS ASKED NOW. Through the harness, like every other question about the coder's machine. The
workspace survey (:mod:`cria.wsview`) carries a `command -v`-equivalent sweep for exactly the
program names cria has asked about, plus the versioned variants distros ship (`bundle3.2`,
`python3.12`), and the answer comes back on the next request. A name nobody has asked about yet
answers **None**, which is a third state and not a "no" — every caller here picks its own safe
direction for it, and they are not the same direction:

  * a PROBE is kept when cria is unsure (dropping a real check is worse than running one that
    abstains), and
  * a piece of ADVICE is withheld when cria is unsure (naming a command that may not exist is the
    false fact this module was written to stop).

The previous implementation asked the user's login shell directly, through `subprocess`, from
cria's own process. That is the same co-location assumption in a different costume: it answers for
whatever machine cria happens to be on. It is gone.
"""

from __future__ import annotations

from . import wsview


def resolved(program: str) -> str | None:
    """The name the coder must actually TYPE to launch ``program`` — the plain name when their shell
    resolves it, a versioned variant (`bundle3.2`) when that is what exists, "" when their shell
    resolves nothing, and **None** when nobody has asked yet.

    Three states, deliberately. Collapsing "not asked" into "not there" is what turns a question
    into a false fact."""
    if not program:
        return ""
    return wsview.current().program(program)
