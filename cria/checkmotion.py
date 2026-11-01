"""Did the repo's checks name DIFFERENT errors while the coder rewrote one file? A grounded fact, not a judgment.

The wheel-spin guard counts writes to one path. A compile-fix sequence rewrites one file five times
and every edit fixes the error the last run named: rustc reports E0573, the coder fixes it, the next
run reports E0308, and so on until green. Five writes, five different checker messages, no wheel.
Counting writes cannot tell that from the real spiral (the same fault reported after every edit), and
the reasoner asked to tell them apart answered ON_TRACK only after 165 s (Rust cell 1) or authored a
half-applied action over a sequence that was converging (Rust cell 2, `rust-toml-cli`).

What cria CAN gather is what each of the coder's own check runs said, parsed by the same owner the
gate uses (`probeparse`), keyed by what was wrong and where, never by the line number an edit shifts
or the digits a changed constant rewrites (`assert 7 == 8` -> `assert 9 == 8` is the SAME fault).
Pure text in, data out: no executor, no loop import. The caller supplies the shell runs.
"""
from __future__ import annotations

import re
from typing import Iterable

from . import probeclassify, probeparse

_DIGITS = re.compile(r"\d+")
_SPACE = re.compile(r"\s+")


def error_identities(command: str, result: str) -> frozenset[str]:
    """What one check run reported as wrong; empty for a command that is not a check or a clean/unparsed run."""
    if not probeclassify.classify_command(command).is_probe():
        return frozenset()
    tokens = [t for seg in probeclassify.split_chain(command) for t in probeclassify.tokenize(seg)]
    parsed = probeparse.parse_output(command, probeparse.family_of(tokens), None, result, "")
    return frozenset(f"{f.file}\0{_DIGITS.sub('#', _SPACE.sub(' ', f.message)).strip()}"
                     for f in parsed.findings)


def outputs(runs: Iterable[tuple[str, str]]) -> tuple[frozenset[str], ...]:
    """The error sets of the check runs that reported any, oldest first (a run with none says nothing)."""
    return tuple(found for found in (error_identities(cmd, res) for cmd, res in runs) if found)


def moving(sequence: tuple[frozenset[str], ...]) -> bool:
    """True when the runs show errors being FIXED and none coming back: a checker message that was reported
    earlier is gone from a later run, and no error returns after it left. Two or more runs are required.
    The same error in every run (a wheel), an error set that only grows, and A -> B -> A all stay False."""
    if len(sequence) < 2:
        return False
    gone: set[str] = set()
    previous = sequence[0]
    for current in sequence[1:]:
        if current & gone:
            return False
        gone |= previous - current
        previous = current
    return bool(gone)
