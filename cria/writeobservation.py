"""Shared authoritative forwarded-write bookkeeping, independent of interventions.

Call once during accepted-turn evidence assembly, before selecting any assist.
The returned snapshot can be read repeatedly without recording or recounting.
Path and unlanded-ID classification and result parsing remain shared services.

THE REGISTRY'S TWO FACTS (one owner, one writer). ``write_call_ids`` is the ORDERED list of write dispatches
this registry has OBSERVED: one entry per observed write dispatch, duplicates allowed, because a list position is
a dispatch and the gate reads "since that check" as a position. ``call_counts`` is the OBSERVED LOWER BOUND of the
multiplicity of every dispatch by call id, non-writes included. Neither derives from the other. A call id whose
observed count is not exactly one cannot say which dispatch a result or a refusal belongs to, so it is UNKNOWN:
:func:`unlanded_ids` and :func:`answered_ids` filter the raw (sticky) sets by that rule at the point of USE, so a
settlement stored before an observed collision is invalidated by the collision automatically, whichever tool the
second dispatch used.

WHAT "OBSERVED" MEANS, AND WHAT IT DOES NOT. A dispatch is recorded exactly once, by :func:`record`, when the
retained completion is forwarded. History is folded in (:func:`observe_history`) from the CANONICAL ACCEPTED history
— the incoming request body BEFORE focus/trim/compaction reshape what the model is shown — at the start of the
request and as the history that precedes a forwarded reply. :func:`reconcile` only raises counts to what that history
shows and appends the positive shortfall of write entries; it never decrements and repeating it adds nothing, so a
later window that has dropped an occurrence cannot make the id unique again. It does NOT recover lifetime counts:
an occurrence that was never in an accepted history and never forwarded through :func:`record` is unobserved, and a
late orphan result arriving after a fresh dispatch of the same id cannot be told from that dispatch's own result
without an origin bit this registry does not keep. Those limits are the documented residual, not a history fallback;
``write_tracking`` means only "a forwarded reply has been recorded", never "the whole conversation is covered".
"""
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class ForwardedCall:
    call_id: str | None
    write_path: str | None


class WriteLedger(Protocol):
    write_tracking: bool
    write_call_ids: list[str] | None
    call_counts: Counter | None
    refused_write_ids: set[str] | None


@dataclass(frozen=True)
class WriteSnapshot:
    calls: tuple[ForwardedCall, ...]
    unlanded_ids: frozenset[str]


@dataclass(frozen=True)
class WriteInput:
    calls: tuple[ForwardedCall, ...]
    messages: list[dict]
    unlanded_ids: frozenset[str]
    ledger: WriteLedger
    note_results: Callable[[WriteLedger, list[dict]], None]
    # Does this call (as the history shows it) change a file? Only the shortfall scan needs it.
    is_write: Callable[[dict], bool] | None = None


def _visible_calls(messages: list[dict]) -> list[dict]:
    return [tc for m in messages or [] if isinstance(m, dict) and m.get("role") == "assistant"
            for tc in m.get("tool_calls") or [] if isinstance(tc, dict) and tc.get("id")]


def reconcile(ledger: WriteLedger, messages: list[dict], is_write: Callable[[dict], bool] | None = None) -> None:
    """Bring the registry up to what the PRECEDING history shows. Counts are raised to the visible occurrences
    of each id (any tool); write entries are appended only for the positive shortfall of visible write
    occurrences over what the registry holds. Nothing is ever removed or lowered, so a rescan is idempotent and
    a dropped window cannot shrink a collision away."""
    if ledger.call_counts is None:
        ledger.call_counts = Counter()
    if ledger.write_call_ids is None:
        ledger.write_call_ids = []
    visible = _visible_calls(messages)
    for cid, n in Counter(tc["id"] for tc in visible).items():
        ledger.call_counts[cid] = max(ledger.call_counts[cid], n)
    if is_write is not None:
        held = Counter(ledger.write_call_ids)
        for cid, n in Counter(tc["id"] for tc in visible if is_write(tc)).items():
            ledger.write_call_ids.extend([cid] * max(0, n - held[cid]))


def settle_refusals(ledger: WriteLedger, unlanded_ids) -> None:
    """Remember what the history in hand PROVED unlanded. The raw set is sticky (compaction may drop the
    evidence); whether an id still counts is decided at use (:func:`unlanded_ids`)."""
    ledger.refused_write_ids = (ledger.refused_write_ids or set()) | set(unlanded_ids)


def unique_ids(ledger: WriteLedger) -> frozenset | None:
    """The ids that name exactly ONE dispatch — the only ones a refusal or an answer can be attributed to.
    ``None`` (nothing is attributable) when tracking is not live or no counts were ever kept: missing metadata
    is unknown, never unique."""
    counts = getattr(ledger, "call_counts", None)
    if not getattr(ledger, "write_tracking", False) or counts is None:
        return None
    return frozenset(cid for cid, n in counts.items() if n == 1)


def unlanded_ids(ledger: WriteLedger) -> frozenset:
    """Proven-unlanded write ids that are still attributable to a single dispatch."""
    unique = unique_ids(ledger)
    return frozenset() if unique is None else frozenset(getattr(ledger, "refused_write_ids", None) or ()) & unique


def answered_ids(ledger: WriteLedger, answered) -> frozenset:
    """Write ids whose result has come back that are still attributable to a single dispatch."""
    unique = unique_ids(ledger)
    return frozenset() if unique is None else frozenset(answered or ()) & unique


@dataclass(frozen=True)
class HistoryInput:
    """The accepted INCOMING history: what precedes any reply this request will produce."""
    messages: list[dict]
    unlanded_ids: frozenset[str]
    ledger: WriteLedger
    note_results: Callable[[WriteLedger, list[dict]], None]
    is_write: Callable[[dict], bool] | None = None


def observe_history(source: HistoryInput) -> None:
    """Fold the accepted incoming history into the registry: raise counts and append the write shortfall
    (:func:`reconcile`), remember what it proved unlanded, and note which results have come back. IDEMPOTENT and
    free of dispatches — it is how a refusal that arrives with THIS request is known before any assist or
    recovery of this request is selected, including when the reply is aborted and nothing is ever forwarded.
    :func:`record` calls it for the history that precedes a forwarded reply; the accepted-request owner calls it
    at the start of the request; the gate registrar calls it for the history it was handed."""
    reconcile(source.ledger, source.messages, source.is_write)
    settle_refusals(source.ledger, source.unlanded_ids)
    source.note_results(source.ledger, source.messages)


def record(source: WriteInput) -> WriteSnapshot:
    """Register one forwarded completion: observe the PRECEDING history first, then count each fresh dispatch
    once and append each fresh write once. Call exactly once per forwarded completion."""
    ledger = source.ledger
    observe_history(HistoryInput(source.messages, source.unlanded_ids, ledger, source.note_results, source.is_write))
    ledger.write_tracking = True
    for call in source.calls:
        if call.call_id:
            ledger.call_counts[call.call_id] += 1
            if call.write_path is not None:
                ledger.write_call_ids.append(call.call_id)
    return WriteSnapshot(source.calls, frozenset(source.unlanded_ids) & (unique_ids(ledger) or frozenset()))
