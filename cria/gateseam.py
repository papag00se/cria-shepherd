"""Where the completion gate's policy reaches cria's operation engine (cria/gateops.py).

The loop decides WHEN a gate runs and what a result means; running it is an operation of the engine, which lives in the server. The loop's
guards are module functions reached from many places, so the engine is handed to them the way the assist runtime is: bound for the duration of
the loop's work on a request (``bound``), read where a gate is issued or its result asked for (``current``). Nothing is global: a request that
binds nothing (a unit test of a guard) can issue no gate, and says so.
"""
import contextlib
import contextvars
from dataclasses import dataclass
from typing import Callable

_current: contextvars.ContextVar = contextvars.ContextVar('cria_gate_seam', default=None)


@dataclass(frozen=True)
class Seam:
    issue: Callable        # (session, shell tool, plan) -> the gate's first harness call, or None when it cannot be issued; sets ``plan.op``
    result: Callable       # (session, operation) -> gateops.GateResult once the gate is done, else None
    resume: Callable       # (session, operation) -> the harness calls that carry an unfinished gate on (``[]``: nothing to carry on)


def current() -> Seam | None:
    return _current.get()


@contextlib.contextmanager
def bound(seam: Seam | None):
    token = _current.set(seam)
    try:
        yield seam
    finally:
        _current.reset(token)
