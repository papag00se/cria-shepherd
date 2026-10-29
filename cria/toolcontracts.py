"""Canonical tool-stage records and event attribution, without execution/default assembly."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, NotRequired, Protocol, TypedDict

from .assistcontract import Policy
from .shrinkcontracts import EventLog, ShrinkServices


@dataclass(frozen=True)
class _PolicyLog:
    target: EventLog
    policy: Policy

    def emit(self, kind: str, **fields) -> None:
        # Nested source-owned policies retain their own attribution.
        fields.setdefault('assist_id', self.policy.id)
        fields.setdefault('family_id', self.policy.family_id)
        self.target.emit(kind, **fields)


def policy_log(log: EventLog | None, policy: Policy) -> EventLog | None:
    return _PolicyLog(log, policy) if log is not None else None


class CompletionTransform(Protocol):
    def __call__(self, completion: dict, tools=None, rlog: EventLog | None = None) -> dict: ...


class CompletionRepair(Protocol):
    def __call__(self, completion: dict, rlog: EventLog | None = None) -> dict: ...


@dataclass(frozen=True)
class CompletionDefinition:
    policy: Policy
    execute: CompletionTransform | CompletionRepair
    needs_menu: bool = True
    stream_start: Callable[[str], int] | None = None


class ShrinkFinding(TypedDict):
    text: str
    bytes: bytes
    land: NotRequired[bool]


ShrinkCheck = Callable[[str, str, str], ShrinkFinding | None]
# Group credential, this call index, predecessors, ALL participants. Closure
# depends on observed completion, never an assumption that the last call ran last.
EditSequence = tuple[str, int, list[int], list[int]]


@dataclass(frozen=True)
class LoweringRequest:
    injected: frozenset[str]
    brave_key: str | None = None
    native_search: str | None = None
    session: str | None = None
    workspace_root: str | None = None
    external_dir_permission: str = 'write'
    unread_target: Callable[[str], str] | None = None
    shrink_check: ShrinkCheck | None = None
    pack: bool = False
    edit_echo: bool = False
    declared_roots: tuple[str, ...] = ()
    shrink_services: ShrinkServices | None = None
    externalization_owner: object | None = None
    externalization_definition: object | None = None
    observe_externalization: Callable | None = None
    document_guidance: object | None = None


@dataclass(frozen=True)
class OutboundCall:
    call: dict
    arguments: dict
    request: LoweringRequest
    sequence: EditSequence | None = None
    log: EventLog | None = None

    @property
    def function(self) -> dict:
        return self.call.get('function') or {}

    @property
    def name(self) -> str:
        return self.function.get('name') or ''


@dataclass(frozen=True)
class RewrittenCall:
    call: dict
    # Execution arguments may differ while the sentinel retains the original call.
    arguments: dict | None = None


@dataclass(frozen=True)
class ShellCommand:
    command: str
    read_in_place: bool = False
    # Producer-owned authorization facts; never inferred from shell text.
    multipart_kind: str = ''
    multipart_fact: str = ''


# None means not applicable, RewrittenCall continues, ShellCommand terminates.
OutboundEffect = RewrittenCall | ShellCommand | None


@dataclass(frozen=True)
class OutboundDefinition:
    policy: Policy
    execute: Callable[[OutboundCall], OutboundEffect]


@dataclass(frozen=True)
class MutationDefinition:
    policy: Policy
    execute: Callable[[OutboundCall, str], str]


@dataclass(frozen=True)
class ReturnedResult:
    message: dict
    content: str
    own_command: str
    prior: list[dict]
    log: EventLog | None = None
    mutation_failure: bool = False


@dataclass(frozen=True)
class ReturnedDefinition:
    policy: Policy
    execute: Callable[[ReturnedResult], dict | None]


@dataclass(frozen=True)
class ReturnedHistory:
    messages: list[dict]
    own_commands: dict[str, str]
    workspace_root: str | None
    session: str
    tools_present: bool
    log: EventLog | None = None


@dataclass(frozen=True)
class HistoryDefinition:
    policy: Policy
    execute: Callable[[ReturnedHistory], None]


@dataclass(frozen=True)
class RejectedDraft:
    call: dict
    note: str


@dataclass(frozen=True)
class DraftDefinition:
    policy: Policy
    execute: Callable[[dict, str, EventLog | None], RejectedDraft]


ToolDefinition = CompletionDefinition | OutboundDefinition | MutationDefinition | ReturnedDefinition | HistoryDefinition | DraftDefinition
