"""The seam between the optional trained CPU classifier (``cria.system1``) and the guards that ask it.

Two closed questions — a briefing's PLAN/RETROSPECTIVE and a directive's DICTATES/DESCRIBES — can be
answered by the trained artifact instead of a reasoner call. This module owns the three things every
caller must do identically and no caller should re-derive:

* **Build once, at startup, or refuse.** :func:`build` constructs the one immutable runtime a service
  shares. A broken bundle or a missing dependency raises :class:`StartupError`; cria never starts
  "without the classifier" after the operator enabled it (#4 — no fallback).
* **Ask with the TRAINED keys.** The artifact was fitted on one state key per family — the whole slot
  text, nothing around it. The runtime's own ``FAMILIES`` table is the single owner of those keys and
  of each family's labels; :func:`classify` reads it and keeps no second copy.
* **An answer that cannot be trusted is no answer.** Any runtime error — typed (a no-fit input, never
  truncated; a non-finite output) or an ordinary unexpected exception — and any unexpected label
  raises :class:`Unjudged`, with the real error class and message logged. The caller then
  takes its EXISTING fail-closed exit (a withheld optional steer; a rejected briefing). There is no
  lexical substitute and no reasoner fallback here, by design (#4).

Nothing in this module imports ``cria.system1`` at import time: the default core stays free of the
runtime and its third-party dependencies until a service actually enables it.
"""
from __future__ import annotations

from typing import Protocol

class Log(Protocol):
    def emit(self, kind: str, **fields: object) -> None: ...


class Judge(Protocol):
    """What the guards need from the runtime: the exact label, or a raised error."""
    def judge(self, family: str, state: dict[str, str], *, rlog: Log | None = None) -> str: ...


class StartupError(RuntimeError):
    """``[system1] enabled`` but the classifier cannot be brought up. The service must not start."""


class Unjudged(Exception):
    """The classifier gave no usable answer. The caller declines its optional action."""

    def __init__(self, family: str, reason: str):
        super().__init__(f"{family}: {reason}")
        self.family, self.reason = family, reason


def build(cfg, log: Log | None = None, *, capture_dir=None):
    """The service's one runtime, or ``None`` when ``[system1]`` is disabled.

    ``cfg`` is the :class:`cria.config.System1Config`. ``capture_dir`` is the per-call capture root
    (``None`` when call capture is off) so the runtime records its own authoritative inputs/outputs
    beside the model captures. Every failure to load is a :class:`StartupError`."""
    if not cfg.enabled:
        return None
    bundle = cfg.bundle_path
    if not bundle.is_dir():
        raise StartupError(f"[system1] bundle_dir is not a directory: {bundle}")
    try:
        from .system1 import System1Runtime
    except ImportError as exc:
        raise StartupError(f"[system1] enabled but the runtime dependencies are unavailable: {exc}") from exc
    try:
        runtime = System1Runtime(bundle, cfg.threads, capture_dir=capture_dir)
    except Exception as exc:  # noqa: BLE001 — whatever stops the artifact loading stops the service
        raise StartupError(f"[system1] bundle {bundle} cannot be loaded: {type(exc).__name__}: {exc}") from exc
    if log is not None:
        log.emit("system1.loaded", bundle_dir=str(bundle), threads=cfg.threads,
                 capture=capture_dir is not None, bundle_id=runtime.bundle_id,
                 manifest_sha256=runtime.manifest_sha256)
    return runtime


def classify(runtime: Judge, family: str, text: str, rlog: Log | None, *, seat: str) -> str:
    """The trained label for ``text`` — exactly one of the family's two words, or :class:`Unjudged`.

    ``seat`` names the caller for the log. The runtime records the call itself; this logs only what
    the CALLER does about a failure, with the real error class and message. The runtime's contract is
    typed errors (``System1Error``), but a guard must decline rather than 500 on any ordinary
    ``Exception`` a runtime raises, so all of them decline; ``BaseException`` (interrupts, exit) is
    never swallowed. Declining is the whole response: no lexical shape and no reasoner stands in."""
    from .system1 import FAMILIES
    spec = FAMILIES[family]
    try:
        label = runtime.judge(family, {spec.state_key: text}, rlog=rlog)
    except Exception as exc:  # noqa: BLE001 — see the docstring: typed or not, no answer is no answer
        _declined(rlog, family, seat, type(exc).__name__, str(exc))
        raise Unjudged(family, f"{type(exc).__name__}: {exc}") from exc
    if label not in spec.labels:
        _declined(rlog, family, seat, "UnexpectedLabel", repr(label))
        raise Unjudged(family, f"unexpected label {label!r}")
    return label


def _declined(rlog: Log | None, family: str, seat: str, error: str, detail: str) -> None:
    if rlog is not None:
        rlog.emit("system1.declined", level="warn", family=family, seat=seat, error=error, detail=detail)
