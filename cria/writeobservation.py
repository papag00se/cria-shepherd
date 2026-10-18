"""Shared authoritative forwarded-write bookkeeping, independent of interventions.

Call once during accepted-turn evidence assembly, before selecting any assist.
The returned snapshot can be read repeatedly without recording or recounting.
Path and unlanded-ID classification and result parsing remain shared services.
"""
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class ForwardedCall:
    call_id: str | None
    write_path: str | None


class WriteLedger(Protocol):
    write_tracking: bool
    write_call_ids: list[str] | None
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


def record(source: WriteInput) -> WriteSnapshot:
    ledger = source.ledger
    if ledger.write_call_ids is None:
        ledger.write_call_ids = []
    ledger.write_tracking = True
    seen = set(ledger.write_call_ids)
    for call in source.calls:
        if call.call_id and call.call_id not in seen and call.write_path is not None:
            ledger.write_call_ids.append(call.call_id)
            seen.add(call.call_id)
    ledger.refused_write_ids = (ledger.refused_write_ids or set()) | set(source.unlanded_ids)
    source.note_results(ledger, source.messages)
    return WriteSnapshot(source.calls, source.unlanded_ids)
