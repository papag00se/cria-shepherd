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
    issue_list_dir: Callable[[dict, dict], dict] | None = None   # (the model's call, its arguments) -> the harness call (cria.ops)
    safe_path: str = '/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin'   # [harness] safe_path: where `python3` is looked up
    issue_read: Callable[[dict, dict, dict | None], dict | None] | None = None   # (call, arguments, held-write facts) -> the harness call
    issue_mutations: Callable[[list], list] | None = None   # ([MutationRequest]) -> one harness call each, in order (cria.ops)
    issue_answer: Callable[[dict, dict, object], dict] | None = None   # (call, arguments, AnswerIntent) -> the harness call (cria.answerops)
    issue_search: Callable[[dict, dict], dict] | None = None   # (call, arguments) -> the harness call (cria.searchops)
    issue_probe: Callable[[str, list], dict] | None = None     # (path, the model's calls held until the file has answered) -> the harness call (cria.probeops)


@dataclass(frozen=True)
class OutboundCall:
    call: dict
    arguments: dict
    request: LoweringRequest
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


@dataclass(frozen=True)
class ReadIntent:
    """The call is answered with a read of its path, carried out through the harness's ``read`` primitive (cria.ops). ``fact`` is
    set when the call is a write held because its target was never read: the answer is the file, the write does not run."""
    fact: str | None = None


@dataclass(frozen=True)
class SaveIntent:
    """A file cria saves where the model can read and search it (the workspace's reference directory) before the answer is true: ``target`` is the
    workspace-relative path (``./tmp/reference/...``), ``content`` the whole text, ``operation`` the externalization offer it settles."""
    target: str
    content: str
    operation: str | None = None


@dataclass(frozen=True)
class AnswerIntent:
    """The call is answered with text cria already holds (a fetched page, a search's results): cria carries it out through the harness primitives
    (cria.answerops), saving ``save`` first when there is one. ``text`` is what the model is told once that is done, ``outcome`` how the call ended,
    ``rep`` the typed facts the readers of the history ask for (a fetch's facts), ``label`` what the harness transcript names the call."""
    tool: str
    label: str
    text: str
    outcome: str
    rep: dict | None = None
    save: SaveIntent | None = None


@dataclass(frozen=True)
class ProbeIntent:
    """The write or edit names a file nothing known settles whether it may be overwritten unread: cria asks the file first (cria.probeops), holding this call and the
    ones after it in the reply, and lowers them again with the answer in hand."""
    path: str


@dataclass(frozen=True)
class SearchIntent:
    """The call is a ``grep`` or a ``glob``: cria walks the tree with the harness's ``ls``, decides what is searched, searches with ``search`` and
    answers in its own words (cria.searchops)."""


@dataclass(frozen=True)
class ReviewTerms:
    """The candidate-safety policy is selected: every complete candidate is reviewed under these terms before it lands."""
    permission: str
    workspace_root: str | None


@dataclass(frozen=True)
class MutationPlan:
    """What the selected mutation policies decided about one file mutation, as facts: ``review`` the candidate-safety terms,
    ``shrink`` the measured whole-file shrink finding. Both are acted on by cria in-process, on the bytes cria holds."""
    review: ReviewTerms | None = None
    shrink: ShrinkFinding | None = None


@dataclass(frozen=True)
class MutateIntent:
    """The call is a file mutation (``write_file``, ``edit_file``) cleared by every guard: cria carries it out through the harness
    primitives, grouping the calls of one turn that name one file (cria.writeops). ``mutation`` is the validated arguments
    (``filecommands._FileMutation``); ``plan`` what the mutation policies decided."""
    mutation: object
    plan: MutationPlan


# None means not applicable, RewrittenCall continues, ShellCommand and ReadIntent terminate.
OutboundEffect = RewrittenCall | ShellCommand | ReadIntent | None   # an AnswerIntent or SearchIntent comes from the lowering of the research and search tools


@dataclass(frozen=True)
class OutboundDefinition:
    policy: Policy
    execute: Callable[[OutboundCall], OutboundEffect]


@dataclass(frozen=True)
class MutationDefinition:
    policy: Policy
    execute: Callable[[OutboundCall, MutationPlan], MutationPlan]


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
    window: int | None = None   # the coder's measured window; None = unknown (the reference budgets)
    ask: Callable[[str], str] | None = None   # one closed question to the reasoner -> its reply text; None = no reasoner


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
    execute: Callable[[dict, str, EventLog | None, bool], RejectedDraft]


ToolDefinition = CompletionDefinition | OutboundDefinition | MutationDefinition | ReturnedDefinition | HistoryDefinition | DraftDefinition
