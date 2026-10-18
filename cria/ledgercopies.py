"""Ledger-copy policy: retain the authoritative facts anchor, point duplicates at it."""
from dataclasses import dataclass
from typing import Callable, Protocol

from . import dedup, prompts, selfcompact
from .assistcontract import Policy, Reference


class Log(Protocol):
    def emit(self, event: str, **fields) -> None: ...


@dataclass(frozen=True)
class LedgerCopyInput:
    messages: list[dict]
    # Existing authoritative fetch renderer, called with an empty visible history
    # and header='PAGES YOU HAVE ALREADY FETCHED', as in the original policy.
    ledger: Callable[[], str]
    log: Log | None = None


@dataclass(frozen=True)
class LedgerCopyResult:
    messages: list[dict]
    excised: int = 0


def elide(source: LedgerCopyInput, *, enabled: bool = True) -> LedgerCopyResult:
    if not enabled:
        return LedgerCopyResult(source.messages)
    ledger = source.ledger()
    units = dedup.ledger_units(ledger)
    # A pointer is permitted only for bytes that remain in an actual owner.
    # The normal driver always supplies that anchor. This also makes replacement
    # stages safe when an earlier selected producer supplied no facts this turn.
    owners = [m.get("content") for m in source.messages
              if isinstance(m.get("content"), str)
              and m["content"].lstrip().startswith(selfcompact.FACTS_MARKER)]
    units = [u for u in units if any(u in owner for owner in owners)]
    messages, count = dedup.elide_from_messages(
        source.messages, units, prompts.load("ledger_dedup_note"),
        skip_prefix=selfcompact.FACTS_MARKER)
    if count and source.log is not None:
        source.log.emit("context.ledger_dedup", reshape="dedup", excised=count)
    return LedgerCopyResult(messages, count)


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable[..., LedgerCopyResult]


DEFINITION = Definition(Policy(
    "ledger-copy-pointers", "coder-ledger-copy-elision", 4, family_id="F69",
    prompts=("ledger_dedup_note",), services=("authoritative-fetch-ledger", "byte-exact-dedup"),
    hooks=(Reference("cria/loop.py", "Loop._prepare_coder_context"),
           Reference("cria/loop.py", "_elide_ledger_copies"),
           Reference("cria/loop.py", "Loop._work_item"),
           Reference("cria/loop.py", "Loop._drive_single_item")),
    regressions=(Reference("tests/test_ledger_copy_policy.py", "test_source_parity_and_anchor_survival"),
                 Reference("tests/test_common_context_preparation.py", "test_absent_context_selection_never_runs_optional_leaf_detection")),
    migrated=False), elide)
