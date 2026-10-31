"""Source-owned research spill admission and delivery lifecycle (not yet bound).

Transport, shared extent/format facts, guarded storage and final context fitting
remain outside this optional policy. Services are captured per operation: replacing
selection while a harness result is outstanding cannot replace its settlement owner.
No executor, filesystem, clock, response parser or process-global ledger lives here.
"""
from dataclasses import dataclass, field
from enum import Enum
import os
import re
from typing import Callable

from . import prompts
from .assistcontract import Policy, Reference


# Complete producer stdout, before any harness envelope. A PTY can add one CR
# per LF. Embed the same byte measurement in harness-side producers.
STDOUT_MAX_BYTES = 10_000
STDOUT_SIZE_PY = '''def stdout_size(raw):
    return len(raw) + raw.count(b'\\n')
'''
_stdout_namespace: dict = {}
exec(STDOUT_SIZE_PY, _stdout_namespace)
stdout_size = _stdout_namespace['stdout_size']


@dataclass(frozen=True)
class Spill:
    target: str
    content: str
    pointer: str


@dataclass(frozen=True)
class SearchProgram:
    """Source choice embedded unchanged where actual parser locals exist.

    ``brief`` and ``pointer`` are parser-local strings. Provider text is data,
    never interpolated into this expression. This is code, not document content.
    """
    expression: str


@dataclass(frozen=True)
class SearchOffer:
    target: str
    program: SearchProgram


@dataclass(frozen=True)
class SearchStored:
    """Checked producer facts; Root still owns raw-call/result correlation.

    Digest/count cover exactly the UTF-8 count-header + full stored body, including
    the zero-results header. These are not inferred from exit code or pointer text.
    """
    target: str
    byte_count: int
    sha256: str

    def __post_init__(self) -> None:
        if (not isinstance(self.target, str) or not self.target
                or type(self.byte_count) is not int or self.byte_count < 0
                or not isinstance(self.sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None):
            raise ValueError("Invalid checked search storage facts")


@dataclass(frozen=True)
class Services:
    # Admission uses existing authoritative cache/filesystem observations.
    detect: Callable[[], Spill | SearchOffer | None]
    # Compose a coder command OR use the planner's existing scratch writer.
    # None means that storage could not be offered; caller retains inline bytes.
    offer: Callable[[Spill | SearchOffer], str | None]
    # Called only after actual storage and retained delivery are confirmed.
    record: Callable[[Spill | SearchOffer], None]


class Outcome(Enum):
    RETAINED = "retained"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Input:
    operation: str
    inline: str
    services: Services


@dataclass(frozen=True)
class Result:
    payload: str
    spill: Spill | SearchOffer | None = None


@dataclass
class _Pending:
    source: Input
    result: Result
    settled: bool = False
    running: bool = True
    error: Exception | None = None
    delivery: "Delivery | None" = None


@dataclass
class State:
    """One session/task, including its outstanding coder AND planner operations.

    An operation ID is the transport call identity, not a URL/query. A retry of
    that same call reuses its offered bytes without another write. A new task
    must reset, invalidating outstanding results; another task gets another State.
    """
    _operations: dict[str, _Pending] = field(default_factory=dict, repr=False)

    def reset(self) -> None:
        self._operations.clear()

    def cancel(self, result: Result) -> bool:
        return self.settle(result, Outcome.CANCELLED, stored=False)

    def settle(self, result: Result, outcome: Outcome, *, stored: bool | SearchStored) -> bool:
        """No exit-code/text guessing: transport supplies its actual observations.

        Unknown, failure and cancellation are terminal for this operation, not
        permission for an implicit retry. A stale/foreign/duplicate result is inert.
        """
        pending = next((p for p in self._operations.values() if p.result is result), None)
        if pending is None or pending.settled:
            return False
        confirmed = (isinstance(stored, SearchStored) and stored.target == result.spill.target
                     if isinstance(result.spill, SearchOffer) else stored is True)
        # Invalid/missing or foreign search facts cannot terminate this delivery's
        # authority. Storage may still be pending; retry keeps the exact offer.
        if outcome is Outcome.RETAINED and isinstance(result.spill, SearchOffer) and not confirmed:
            return False
        pending.settled = True
        if outcome is Outcome.RETAINED and confirmed and result.spill is not None:
            pending.source.services.record(result.spill)
            return True
        return False


def externalize(source: Input, state: State, *, enabled: bool = True) -> Result:
    """Absent selection is lazy identity, including no optional state allocation."""
    if not enabled:
        return Result(source.inline)
    prior = state._operations.get(source.operation)
    if prior is not None:
        if prior.source is not source:
            raise ValueError("operation identity reused with different input")
        if prior.running:
            raise RuntimeError("operation already being offered")
        if prior.error is not None:
            raise prior.error
        return prior.result
    pending = _Pending(source, Result(source.inline))
    state._operations[source.operation] = pending
    try:
        spill = source.services.detect()
        payload = source.services.offer(spill) if spill is not None else None
        pending.result = Result(source.inline if payload is None else payload,
                                spill if payload is not None else None)
    except Exception as error:
        # An unknown write outcome cannot safely be executed a second time.
        pending.error = error
        raise
    finally:
        pending.running = False
    return pending.result


@dataclass(frozen=True)
class FetchFacts:
    reduced_chars: int
    # Existing renderer supplies bytes, labelled extent and guarded target. It
    # must not hide admission; admission belongs to coder_fetch below.
    render: Callable[[], Spill]


@dataclass(frozen=True)
class FetchServices:
    oversize_chars: int
    cached: Callable[[str], FetchFacts | None]
    already_spilled: Callable[[], bool]


def coder_fetch(url: str, *, find: str | None, cursor: int | None,
                services: FetchServices) -> Spill | None:
    """Existing plain-fetch admission over injected cache and storage facts."""
    if find is not None or cursor is not None or services.already_spilled():
        return None
    found = services.cached(url)
    if found is None or found.reduced_chars <= services.oversize_chars:
        return None
    return found.render()


def search_program(inline_bytes: int) -> SearchProgram:
    """Own the existing inclusive UTF-8 choice inside the harness parser.

    Root supplies its existing budget, embeds this exact returned program, and
    retires its old conditional. Required response parsing/error/empty handling,
    checked storage and fact framing remain Root-owned. Absence has NO program:
    Root returns the complete count-header + full representation, without a spill.
    """
    if type(inline_bytes) is not int or inline_bytes < 0:
        raise ValueError("Search inline byte budget must be a nonnegative integer")
    return SearchProgram(f'brief if len(brief.encode("utf-8")) <= {inline_bytes} else pointer')


def coder_search(*, target: str, full: str, brief: str, pointer: str,
                 inline_bytes: int) -> Spill:
    """Compatibility-only pure helper, NOT the production coder search route.

    Select the existing parser's representations without re-parsing responses.

    The coder search parser owns API errors, empty results, API-name projection
    and raw provider bytes. It writes its full representation in BOTH branches;
    this policy only chooses what is printed, with the existing UTF-8 byte bound.
    The caller must handle API errors/empty results before this result choice.
    """
    return Spill(target, full, brief if len(brief.encode()) <= inline_bytes else pointer)


@dataclass(frozen=True)
class PlannerFetchServices:
    oversize_chars: int
    content: Callable[[str, object, str | None], str]
    name: Callable[[str], str]
    outline: Callable[[object, str], str]


def planner_fetch(*, status: int, url: str, reduced: str, parsed: object,
                  content_type: str | None, root: str,
                  remedy: Callable[[str], str],
                  services: PlannerFetchServices) -> Spill | None:
    """Caller supplies its existing scratch root; never create a new location."""
    if len(reduced) <= services.oversize_chars:
        return None
    content = services.content(reduced, parsed, content_type)
    target = os.path.join(root, os.path.basename(services.name(url)))
    pointer = prompts.fill(prompts.load_map("planner_steers")["fetch_spill"],
                           status=str(status), url=url, chars=f"{len(content):,}",
                           target=target, outline=services.outline(parsed, target),
                           remedy=remedy(target))
    return Spill(target, content, pointer)


def planner_search(query: str, body: str, *, scratch: str | None,
                   inline_chars: int, remedy: Callable[[str], str]) -> Spill | None:
    """Preserve planner's existing threshold, slug and title projection verbatim.

    inline_chars is the existing planner constant, not a new configurable policy.
    Coder search's distinct parser/inline projection stays with its transport.
    """
    if scratch is None or len(body) <= inline_chars:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:60] or "search"
    target = os.path.join(scratch, f"search-{slug}.txt")
    titles = "\n".join(ln for ln in body.splitlines()
                       if ln[:2].strip().rstrip(".").isdigit() or ln.startswith("Search results for:"))
    pointer = prompts.fill(prompts.load_map("planner_steers")["search_spill"],
                           query=query, chars=f"{len(body):,}", target=target,
                           titles=titles, remedy=remedy(target))
    return Spill(target, body, pointer)


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable[..., Result]
    settle: Callable[..., bool]
    cancel: Callable[[State, Result], bool]
    reset: Callable[[State], None]
    search_program: Callable[[int], SearchProgram] = search_program


@dataclass(frozen=True)
class Delivery:
    """Exact selected definition, not merely its services, owns all later callbacks.

    Primary retains this handle across asynchronous delivery. Never re-select at
    result time. An absent selection has neither owner nor lifecycle effects.
    """
    result: Result
    owner: Definition | None
    state: State

    def settle(self, outcome: Outcome, *, stored: bool | SearchStored) -> bool:
        if self.owner is None:
            return False
        return self.owner.settle(self.state, self.result, outcome, stored=stored)

    def cancel(self) -> bool:
        if self.owner is None:
            return False
        return self.owner.cancel(self.state, self.result)

    def reset(self) -> None:
        # A late reset from a previous task must not clear its successor's state.
        if self.owner is not None and any(p.result is self.result for p in self.state._operations.values()):
            self.owner.reset(self.state)


def selected_externalization(definition: Definition | None, source: Input, state: State) -> Delivery:
    if definition is None:
        return Delivery(Result(source.inline), None, state)
    prior = state._operations.get(source.operation)
    if prior is not None and prior.delivery is not None:
        if prior.source is not source:
            raise ValueError("operation identity reused with different input")
        return prior.delivery
    result = definition.execute(source, state)
    delivery = Delivery(result, definition, state)
    pending = state._operations.get(source.operation)
    if pending is not None and pending.result is result:
        pending.delivery = delivery
    return delivery


DEFINITION = Definition(Policy(
    "research-spill-admission", "research-externalization", 0, family_id="F63",
    prompts=("planner_steers", "webfetch_guards", "spill_cut", "search_inline_note"),
    state="session/task operations; reset invalidates pending delivery; exact owner settlement",
    services=("cached-document-facts", "guarded-spill-transport", "retained-delivery-observation"),
    hooks=(Reference("cria/externalization.py", "externalize"),),
    regressions=(Reference("tests_backup/test_externalization_policy.py", "test_retry_and_selected_owner"),),
    migrated=False), externalize, State.settle, State.cancel, State.reset)
