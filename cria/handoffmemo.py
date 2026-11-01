"""One briefing per identical harness-compaction request.

Codex retries a request that failed or timed out up to three times, and each retry used to re-run the whole
handoff: the briefing writer, every validator lens, the listing reads, for one identical history. That is
wasted inference on a shared server, and it let the same history be accepted on one attempt and refused on the
next (three briefings, one accepted and one refused, in a single Node cell).

The memo is keyed by the request's exact identity — the SESSION plus a digest of the whole inbound body (the
compaction history, the task, the tools) — and each entry carries a digest of the EVIDENCE the handoff reads
besides the body (the session's gate facts, the workspace listing the writer is shown). A retry reuses the entry
only when both match, so a request whose evidence changed is answered afresh, never from a verdict made on other
evidence. A refusal that rested on no decided answer (the judge could not be reached, an empty verdict) is not
remembered at all: it records an outage, not a finding about the briefing. A reuse returns the stored reply
byte for byte, and a retry that arrives while the first is still being produced waits for it instead of
starting a second writer.

The memo is PROCESS MEMORY: a restart forgets it, and a retry that crosses a restart is produced afresh exactly
as it was before this module existed. It is bounded per session and in the number of sessions, and entries of
one session are never visible to another.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections import OrderedDict

PER_SESSION = 4
SESSIONS = 32


def digest(*parts) -> str:
    """A stable digest of JSON-able parts (an unserializable leaf is stringified, never skipped)."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def undecided(fields: dict) -> bool:
    """True when a validation event records NO verdict about the briefing: the judge was unavailable, or a lens
    came back empty / unjudged. Such a refusal is fail-closed but says nothing about the history."""
    if fields.get("lens") == "unavailable":
        return True
    answers = fields.get("answers")
    return isinstance(answers, dict) and any(str(v).strip() in ("", "UNJUDGED") for v in answers.values())


class VerdictWatch:
    """The request log, seen by the validator: forwards everything and notes whether a refusal was undecided."""

    def __init__(self, rlog) -> None:
        object.__setattr__(self, "_rlog", rlog)
        object.__setattr__(self, "undecided", False)

    def emit(self, kind: str, **fields) -> None:
        if kind == "context.compaction_validation" and fields.get("accepted") is False and undecided(fields):
            object.__setattr__(self, "undecided", True)
        self._rlog.emit(kind, **fields)

    def __getattr__(self, name):
        return getattr(self._rlog, name)

    def __setattr__(self, name, value) -> None:
        setattr(self._rlog, name, value)


class Claim:
    """One request's turn at its identity: held while it is produced, so a concurrent retry waits for it."""

    def __init__(self, memo: "HandoffMemo", session: str, identity: str, gate: threading.Lock) -> None:
        self._memo, self._key, self._gate = memo, (session, identity), gate

    def __enter__(self) -> "Claim":
        self._gate.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self._gate.release()
        self._memo._release(self._key)

    def recall(self, evidence):
        """The stored reply for this identity when its evidence still matches, else None. ``evidence`` is a
        callable, run only when an entry exists (it may read the disk)."""
        return self._memo._recall(self._key, evidence)

    def remember(self, evidence: str, reply) -> None:
        self._memo._store(self._key, evidence, reply)


class HandoffMemo:
    def __init__(self, per_session: int = PER_SESSION, sessions: int = SESSIONS) -> None:
        self._per_session, self._sessions = per_session, sessions
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, OrderedDict[str, tuple[str, object]]] = OrderedDict()
        self._gates: dict[tuple[str, str], list] = {}

    def claim(self, session: str, identity: str) -> Claim:
        with self._lock:
            slot = self._gates.setdefault((session, identity), [threading.Lock(), 0])
            slot[1] += 1
        return Claim(self, session, identity, slot[0])

    def _release(self, key) -> None:
        with self._lock:
            slot = self._gates.get(key)
            if slot is not None:
                slot[1] -= 1
                if slot[1] <= 0:
                    del self._gates[key]

    def _recall(self, key, evidence):
        session, identity = key
        with self._lock:
            entry = self._entries.get(session, {}).get(identity)
        if entry is None or entry[0] != evidence():
            return None
        return copy.deepcopy(entry[1])

    def _store(self, key, evidence: str, reply) -> None:
        session, identity = key
        with self._lock:
            mine = self._entries.setdefault(session, OrderedDict())
            self._entries.move_to_end(session)
            mine[identity] = (evidence, copy.deepcopy(reply))
            mine.move_to_end(identity)
            while len(mine) > self._per_session:
                mine.popitem(last=False)
            while len(self._entries) > self._sessions:
                self._entries.popitem(last=False)

    def size(self, session: str) -> int:
        with self._lock:
            return len(self._entries.get(session, ()))


_BOUND = threading.Lock()


def of(server) -> HandoffMemo:
    """The server's memo (created on first use, so a bare server object works too)."""
    memo = getattr(server, "handoff_memo", None)
    if memo is None:
        with _BOUND:
            memo = getattr(server, "handoff_memo", None)
            if memo is None:
                memo = HandoffMemo()
                server.handoff_memo = memo
    return memo
