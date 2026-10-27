"""Source-owned research admission lifecycles; document facts remain shared.

No transport, cache, workspace reads or semantic keyword rules live here. Lazy
facts are gathered only by selected policies. The task owner resets each state
on a new task/fork; no pending harness operation belongs to these policies.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Collection, Iterable

from .assistcontract import ExecutableDefinition, Policy, Reference
from .searchloop import first_domain_in, normalize_search, searches_match


class Effect(Enum):
    NO_OP = "no-op"
    ALLOWED = "allowed"
    REFUSED = "refused"
    WITHHELD = "withheld"
    NOTED = "noted"
    OBSERVED = "observed"
    POISONED = "poisoned"


@dataclass(frozen=True)
class Admission:
    effect: Effect = Effect.NO_OP
    note: str | None = None
    prior: str | None = None

    def __post_init__(self):
        if not isinstance(self.effect, Effect):
            raise ValueError("Unknown research effect")
        if self.effect in (Effect.REFUSED, Effect.NOTED):
            if not isinstance(self.note, str) or not self.note:
                raise ValueError("A research refusal/note requires its concrete text")
        elif self.note is not None:
            raise ValueError("A silent research effect cannot carry a note")


class SearchAction(Enum):
    PRIOR = "prior"
    CLEAR = "clear"
    ADMIT = "admit"


@dataclass(frozen=True)
class SearchInput:
    session: str | None
    query: str
    action: SearchAction
    visible: Callable[[], Iterable[str]]
    spill_path: Callable[[str], str]
    domain_note: Callable[[str], str]
    render: Callable[..., str]


@dataclass
class SearchState:
    allowed: dict[str, set[str]] = field(default_factory=dict)


def search_admission(source: SearchInput, state: SearchState) -> Admission:
    q = (source.query or "").strip()
    if not isinstance(source.action, SearchAction):
        raise ValueError("Unknown research search action")
    if not source.session or not q:
        return Admission()
    key = q.lower()
    if source.action is SearchAction.CLEAR:
        state.allowed.setdefault(source.session, set()).add(key)
        return Admission(Effect.ALLOWED)
    if source.action is SearchAction.ADMIT and key in state.allowed.get(source.session, ()):
        state.allowed[source.session].discard(key)
        return Admission(Effect.ALLOWED)
    words = normalize_search(q)
    if not words:
        return Admission()
    prior = next((prev for prev in source.visible()
                  if searches_match(words, normalize_search(prev))), None)
    if prior is None:
        return Admission()
    if source.action is SearchAction.PRIOR:
        return Admission(prior=prior)
    if source.action is not SearchAction.ADMIT:
        raise ValueError("Unknown research search action")
    target = source.spill_path(prior)
    steer = source.domain_note(source.query)
    note = (source.render("search_repeat", query=source.query, prior=prior,
                          target=target, domain_steer=steer) if target else
            source.render("search_repeat_inline", query=source.query, prior=prior, domain_steer=steer))
    return Admission(Effect.REFUSED, note, prior)


def domain_advice(query: str, render: Callable[..., str]) -> str:
    domain = first_domain_in(query)
    return render("domain_steer", domain=domain) if domain else ""


class FetchReceipt(Enum):
    UNKNOWN = "unknown"
    NO_RESPONSE = "no-response"
    RESPONSE = "response"


@dataclass(frozen=True)
class VisibleFetch:
    """One visible identity and its producer's receipt, independent of cache retention.

    An inline lowered fetch's authenticated RAN record carries fx for every HTTP
    response, including empty and non-2xx bodies. RAN without fx or a stored-body
    receipt is an attempted fetch with no HTTP response, not a refusal. Stored
    documents and native/unproven history must not become failed attempts.
    """
    key: tuple[str, str, str, bool]
    receipt: FetchReceipt = FetchReceipt.UNKNOWN
    status: str | None = None
    document_visible: bool | None = None

    @classmethod
    def from_report(cls, key, *, ran: bool, facts: dict | None, stored: bool = False):
        if not ran:
            return cls(key)
        if facts is not None:
            return cls(key, FetchReceipt.RESPONSE, facts["status"], True)
        return cls(key, FetchReceipt.RESPONSE if stored else FetchReceipt.NO_RESPONSE,
                   document_visible=stored)


@dataclass(frozen=True)
class FetchInput:
    session: str | None
    url: str
    find: str | None
    cursor: str | None
    raw: bool
    internal: Callable[[str], bool]
    visible: Callable[[], Collection[tuple[str, str, str, bool]]]
    spilled: Callable[[], bool]
    cached: Callable[[], tuple[int, str | None, str, object, bool] | None]
    spill_size: int
    spill_note: Callable[[], str]
    status_label: Callable[[int], str]
    render: Callable[..., str]
    observation: Callable[[], VisibleFetch | None] = lambda: None


def fetch_admission(source: FetchInput) -> Admission:
    if not source.session or source.internal(source.url):
        return Admission()
    if not source.find and not source.cursor and source.spilled():
        return Admission(Effect.REFUSED, source.spill_note())
    key = (source.url, source.find or "", source.cursor or "", bool(source.raw))
    if key not in source.visible():
        return Admission()
    observed = source.observation()
    if observed is not None and observed.receipt is FetchReceipt.NO_RESPONSE:
        return Admission(Effect.REFUSED, source.render("fetch_repeat_no_response", url=source.url))
    cached = source.cached()
    if cached is not None:
        status, _ct, body, _parsed, _truncated = cached
        if not (isinstance(status, int) and 200 <= status < 300):
            return Admission(Effect.REFUSED, source.render(
                "fetch_repeat_failed", url=source.url, status=source.status_label(status)))
        if len(body) > source.spill_size and source.spilled():
            return Admission(Effect.REFUSED, source.spill_note())
    elif observed is not None and observed.receipt is FetchReceipt.RESPONSE and observed.status is not None:
        return Admission(Effect.REFUSED, source.render(
            "fetch_repeat_response", url=source.url, status=observed.status))
    return Admission(Effect.REFUSED, source.render("fetch_repeat", url=source.url))


@dataclass
class FailureState:
    streaks: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class FailureInput:
    session: str | None
    url: str
    status: int | None
    discovered: bool
    internal: Callable[[str], bool]
    bound: Callable[[dict], None]
    note: Callable[[int, int], str]


def failure_observation(source: FailureInput, state: FailureState) -> Admission:
    if not source.session or source.status is None or source.internal(source.url):
        return Admission()
    status = 200 if source.discovered else source.status
    if 200 <= status < 300:
        state.streaks[source.session] = 0
        return Admission(Effect.OBSERVED)
    streak = state.streaks.get(source.session, 0) + 1
    state.streaks[source.session] = streak
    source.bound(state.streaks)
    note = source.note(status, streak)
    return Admission(Effect.NOTED if note else Effect.OBSERVED, note or None)


@dataclass
class SpillState:
    judged: set[str] = field(default_factory=set)
    poisoned: set[str] = field(default_factory=set)
    recommendation: str = ""


@dataclass(frozen=True)
class SpillVerdict:
    on_target: bool | None
    recommendation: str = ""

    def __post_init__(self):
        if self.on_target is not None and not isinstance(self.on_target, bool):
            raise ValueError("A spill verdict must be true, false or unknown")
        if not isinstance(self.recommendation, str):
            raise ValueError("A spill recommendation must be text")


@dataclass(frozen=True)
class SpillInput:
    key: str  # caller's existing canonical path, not a new pathname matcher
    query: Callable[[], str]  # exact original query from the spill producer
    results: Callable[[], str]
    task: Callable[[], str]
    judge: Callable[[str, str, str], SpillVerdict]
    protected: Callable[[str, str], bool]  # existing task-host deletion veto


@dataclass(frozen=True)
class SpillResult:
    effect: Effect = Effect.NO_OP
    recommendation: str = ""
    reason: str = ""

    def __post_init__(self):
        if self.effect not in (Effect.NO_OP, Effect.WITHHELD, Effect.POISONED):
            raise ValueError("Unknown spill settlement effect")
        if not isinstance(self.recommendation, str) or not isinstance(self.reason, str):
            raise ValueError("Spill settlement must carry text fields")


def spill_read_judgment(source: SpillInput, state: SpillState) -> SpillResult:
    if source.key in state.poisoned:
        return SpillResult(Effect.POISONED, state.recommendation)
    if source.key in state.judged:
        return SpillResult()
    # Existing one-shot behavior: even unavailable query/results settle the attempt.
    state.judged.add(source.key)
    results = source.results()
    query = source.query()
    if not query:
        return SpillResult(Effect.WITHHELD, reason="no query")
    task = source.task()
    if not task.strip() or not results.strip():
        return SpillResult(Effect.WITHHELD, reason="unavailable evidence")
    verdict = source.judge(task, query, results)
    if verdict.on_target is None:
        return SpillResult(Effect.WITHHELD, reason="unknown verdict")
    if verdict.on_target or source.protected(task, results):
        return SpillResult()
    state.poisoned.add(source.key)
    state.recommendation = verdict.recommendation
    return SpillResult(Effect.POISONED, verdict.recommendation)


@dataclass(frozen=True)
class SearchDefinition:
    policy: Policy
    execute: Callable[[SearchInput, SearchState], Admission]


@dataclass(frozen=True)
class DomainDefinition:
    policy: Policy
    execute: Callable[[str, Callable[..., str]], str]


@dataclass(frozen=True)
class FetchDefinition:
    policy: Policy
    execute: Callable[[FetchInput], Admission]


@dataclass(frozen=True)
class FailureDefinition:
    policy: Policy
    execute: Callable[[FailureInput, FailureState], Admission]


@dataclass(frozen=True)
class SpillDefinition:
    policy: Policy
    execute: Callable[[SpillInput, SpillState], SpillResult]


SEARCH = SearchDefinition(Policy(
    "search-repeat-admission", "research-search-admission", 2, family_id="F51",
    prompts=("webfetch_guards",), state="task-local one-use semantic clearances; reset on task/fork",
    services=("visible-search-queries", "search-spill-provenance", "semantic-clearance"),
    hooks=(Reference("cria/webfetch.py", "prior_matching_search"),
           Reference("cria/webfetch.py", "allow_search"),
           Reference("cria/webfetch.py", "gate_search"),
           Reference("cria/loop.py", "guard_search_query"),
           Reference("cria/planner_tools.py", "gate_search")),
    regressions=(Reference("tests/test_research_policy_lifecycles.py", "test_one_use_semantic_clearance_and_session_isolation"),
                 Reference("tests/test_research_policy_lifecycles.py", "test_disabled_search_skips_detector_and_clearance_settlement_but_keeps_facts"),
                 Reference("tests/test_research_policy_lifecycles.py", "test_replaced_search_owns_prior_clearance_and_admission"),
                 Reference("tests/test_research_policy_lifecycles.py", "test_projected_disabled_canonical_search_leaves_other_stages_selected"),
                 Reference("tests/test_research_policy_lifecycles.py", "test_projected_empty_selection_stops_coder_planner_detection_and_state")),
    migrated=False), search_admission)
DOMAIN = DomainDefinition(Policy(
    "search-domain-advice", "research-domain-advice", 2, family_id="F51",
    prompts=("webfetch_guards",), services=("original-search-query",),
    hooks=(Reference("cria/webfetch.py", "_search_input"),
           Reference("cria/planner_tools.py", "gate_search")),
    regressions=(Reference("tests/test_research_policy_lifecycles.py", "test_domain_advice_is_independently_selected_and_does_not_change_admission"),
                 Reference("tests/test_research_policy_lifecycles.py", "test_domain_replacement_controls_advice_without_changing_repeat_state")),
    migrated=False), domain_advice)
FETCH = FetchDefinition(Policy(
    "fetch-repeat-admission", "research-fetch-admission", 2, family_id="F51",
    prompts=("webfetch_guards",), services=("visible-fetch-identities", "document-cache", "verified-spill"),
    hooks=(Reference("cria/webfetch.py", "fetch_nav"),),
    regressions=(Reference("tests/test_research_policy_lifecycles.py", "test_fetch_identity_preserves_find_cursor_and_raw"),
                 Reference("tests/test_research_policy_lifecycles.py", "test_disabled_fetch_retains_document_cache_visibility_and_exact_transport_bytes"),
                 Reference("tests/test_research_policy_lifecycles.py", "test_fetch_replacement_runs_instead_of_old_detector")),
    migrated=False), fetch_admission)
FAILURE = FailureDefinition(Policy(
    "fetch-failure-streak", "research-fetch-observation", 2, family_id="F51",
    prompts=("webfetch_guards",), state="task-local consecutive external failures; reset on success/task/fork",
    services=("fetch-status", "protocol-discovery-status"),
    hooks=(Reference("cria/webfetch.py", "fetch_nav"),
           Reference("cria/webfetch.py", "reset_session")),
    regressions=(Reference("tests/test_research_policy_lifecycles.py", "test_failure_lifecycle_threshold_success_discovery_unknown_and_disabled"),
                 Reference("tests/test_research_policy_lifecycles.py", "test_failure_replacement_owns_observation_without_original_history_updates"),
                 Reference("tests/test_research_policy_lifecycles.py", "test_internal_hosts_never_refuse_or_update_failure_streak")),
    migrated=False), failure_observation)
SPILL = SpillDefinition(Policy(
    "search-spill-read-judgment", "research-spill-read", 5, family_id="F51",
    prompts=("search_read_denied",), state="task-local judged/poisoned paths and recommendation; reset on task/fork",
    services=("original-spill-query", "current-spill-bytes", "task", "search-judge", "task-host-veto"),
    hooks=(Reference("cria/researchpolicies.py", "ResearchSelection.spill_read"),
           Reference("cria/loop.py", "Loop._judge_search_reads")),
    regressions=(Reference("tests/test_research_policy_lifecycles.py", "test_spill_poisoning_owns_judgment_repeat_and_recommendation"),
                 Reference("tests/test_research_policy_lifecycles.py", "test_spill_task_host_veto_preserves_results"),
                 Reference("tests/test_research_policy_lifecycles.py", "test_disabled_and_replaced_spill_own_all_detection_and_settlement")),
    migrated=False), spill_read_judgment)
DEFINITIONS = (SEARCH, DOMAIN, FETCH, FAILURE, SPILL)


@dataclass(frozen=True)
class ResearchSelection:
    search: SearchDefinition | None = SEARCH
    domain: DomainDefinition | None = DOMAIN
    fetch: FetchDefinition | None = FETCH
    failure: FailureDefinition | None = FAILURE
    spill: SpillDefinition | None = SPILL

    def __post_init__(self):
        for selected, canonical in zip((self.search, self.domain, self.fetch, self.failure, self.spill), DEFINITIONS):
            if selected is not None and (not isinstance(selected, type(canonical))
                    or selected.policy != canonical.policy or not callable(selected.execute)):
                raise ValueError("Research replacement must preserve its typed policy contract")

    def spill_read(self, source: SpillInput, state: SpillState) -> SpillResult:
        """The reserved loop's integration seat; disabled means no attempt/state/judge."""
        if self.spill is None:
            return SpillResult()
        return self.spill.execute(source, state)

    @classmethod
    def from_definitions(cls, definitions: Iterable[ExecutableDefinition]) -> ResearchSelection:
        """Project the authoritative selected definitions, never fill absent stages.

        Other stages belong to other source owners. Recognized research IDs must
        retain their concrete definition type/contract, including replacements;
        a same-ID adapter record is not the canonical research lifecycle.
        """
        selected = {}
        known = {definition.policy.id for definition in DEFINITIONS}
        for definition in definitions:
            identity = definition.policy.id
            if identity not in known:
                continue
            if identity in selected:
                raise ValueError("Duplicate research policy selection: " + identity)
            selected[identity] = definition
        return cls(*(selected.get(definition.policy.id) for definition in DEFINITIONS))

    @classmethod
    def select(cls, disabled=()):
        known = {d.policy.id for d in DEFINITIONS}
        if len(set(disabled)) != len(disabled) or set(disabled) - known:
            raise ValueError("Unknown or duplicate research policy selection")
        return cls(*(None if d.policy.id in disabled else d for d in DEFINITIONS))


_UNBOUND = object()
_DEFAULT = ResearchSelection()
_CURRENT = ContextVar("research_policy_selection", default=_UNBOUND)


def is_bound() -> bool:
    """Whether this context has an explicit binding, even an empty selection."""
    return _CURRENT.get() is not _UNBOUND


def current() -> ResearchSelection:
    selection = _CURRENT.get()
    return _DEFAULT if selection is _UNBOUND else selection


@contextmanager
def bound(selection: ResearchSelection):
    token = _CURRENT.set(selection)
    try:
        yield selection
    finally:
        _CURRENT.reset(token)
