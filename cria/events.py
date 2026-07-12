"""Structured event log — cria's single observability primitive.

Everything cria does emits an ``Event`` through here. There are two sinks:

* a **JSONL file** — the complete, machine-readable record, never level-filtered.
  It is the troubleshooting source of truth: after any run you should be able to
  reconstruct *exactly why* cria made each decision from the JSONL alone, without
  re-running or guessing.
* an optional **console line** (stderr) — a human-readable view, filtered by level.

This is baked in at the base so every later subsystem (routing, planner, the
per-item loop, the assists) emits through the *same* primitive, instead of the
inconsistent ad-hoc prints the Rust tail script had to reconcile.

Convention
----------
* ``kind`` is ``"<subsystem>.<event>"`` — e.g. ``"request.recv"``,
  ``"upstream.first_token"``, ``"route.decide"``. Keep it dotted and stable.
* A **decision** — a place where cria chose between options — uses ``decide()``,
  which records the choice AND the reason. Reasons are not optional; a decision
  without a reason is a future debugging session spent guessing.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}


class EventLog:
    def __init__(
        self,
        *,
        level: str = "info",
        dir: str | Path | None = None,
        console: bool = True,
        jsonl: bool = True,
    ) -> None:
        self._console = console
        self._console_level = _LEVELS.get(level, 20)
        self._lock = threading.Lock()
        self._fh = None
        self.path: Path | None = None
        if jsonl and dir is not None:
            dpath = Path(dir).expanduser()
            dpath.mkdir(parents=True, exist_ok=True)
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            self.path = dpath / f"cria-{day}.jsonl"
            # line-buffered so a crash still leaves a complete tail on disk.
            self._fh = open(self.path, "a", buffering=1, encoding="utf-8")

    def emit(
        self,
        kind: str,
        *,
        level: str = "info",
        session: str | None = None,
        turn: str | None = None,
        msg: str | None = None,
        **fields: object,
    ) -> None:
        now = time.time()
        rec: dict[str, object] = {
            "ts": round(now, 3),
            "iso": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="milliseconds"),
            "level": level,
            "kind": kind,
        }
        if session is not None:
            rec["session"] = session
        if turn is not None:
            rec["turn"] = turn
        if msg is not None:
            rec["msg"] = msg
        rec.update(fields)
        line = json.dumps(rec, ensure_ascii=False, default=str)
        with self._lock:
            if self._fh is not None:
                self._fh.write(line + "\n")
            if self._console and _LEVELS.get(level, 20) >= self._console_level:
                sys.stderr.write(_console_line(rec) + "\n")
                sys.stderr.flush()

    def decide(
        self,
        name: str,
        choice: object,
        reason: str,
        *,
        session: str | None = None,
        turn: str | None = None,
        **fields: object,
    ) -> None:
        """Record a decision: WHAT cria chose and WHY. The backbone of 'know
        exactly why cria decided what it did'."""
        self.emit(
            "decision",
            level="info",
            session=session,
            turn=turn,
            decision=name,
            choice=choice,
            reason=reason,
            **fields,
        )

    def bind(self, *, session: str | None = None, turn: str | None = None) -> "BoundLog":
        """A per-request logger that carries the session/turn ids so callers don't
        repeat them on every emit."""
        return BoundLog(self, session, turn)

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None


class BoundLog:
    """An ``EventLog`` view with ``session``/``turn`` pre-bound."""

    def __init__(self, log: EventLog, session: str | None, turn: str | None) -> None:
        self._log = log
        self._session = session
        self._turn = turn
        # The tok/s of the most recent model generation this turn (from `upstream.done`),
        # so the response banner can show how fast the local model actually ran. Fresh per
        # request (a new BoundLog per turn), so it never shows a stale rate.
        self.last_tok_per_s: float | None = None
        # The role/phase of the NEXT upstream call (coder / critic / classifier / planner /
        # proxy) — set by the calling subsystem right before it calls the model, read by the
        # call-capture so each dump is labeled with what it is. None until set.
        self.phase: str | None = None

    @property
    def session(self) -> str | None:
        return self._session

    def emit(self, kind: str, **kw: object) -> None:
        if kind == "upstream.done":
            tps = kw.get("tok_per_s")
            if isinstance(tps, (int, float)):
                self.last_tok_per_s = float(tps)
        self._log.emit(kind, session=self._session, turn=self._turn, **kw)

    def decide(self, name: str, choice: object, reason: str, **kw: object) -> None:
        self._log.decide(name, choice, reason, session=self._session, turn=self._turn, **kw)


# Fields already shown in the console header — don't repeat them in the key=val tail.
_HEADER_FIELDS = {"ts", "iso", "level", "kind", "session", "turn", "msg"}


def _console_line(rec: dict) -> str:
    clock = str(rec["iso"])[11:23]  # HH:MM:SS.mmm
    level = str(rec["level"]).upper()[:4]
    turn = rec.get("turn", "-")
    parts = [f"{clock} {level:<4} [{turn}] {rec['kind']}"]
    if rec.get("msg"):
        parts.append(str(rec["msg"]))
    tail = " ".join(
        f"{k}={_fmt(v)}" for k, v in rec.items() if k not in _HEADER_FIELDS
    )
    if tail:
        parts.append(tail)
    return "  ".join(parts)


def _fmt(v: object) -> str:
    if isinstance(v, float):
        return f"{v:.1f}"
    if isinstance(v, str):
        return v if v and " " not in v else json.dumps(v)
    return json.dumps(v, default=str)
