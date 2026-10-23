"""New-direction clearance for overlapping searches; repeat admission remains SEARCH.

This owner never judges an ordinary search's relevance or substitutes a fetch.
Visible research facts and the repeat owner's one-use clearance are not copied here.
"""
from __future__ import annotations

from collections import UserDict
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Callable, Protocol

from . import groundedaction, prompts, researchpolicies, toolargs, webfetch
from .assistcontract import Policy, Reference
from .jsontext import extract_json_object, strip_think
from .searchloop import normalize_search


class Log(Protocol):
    def emit(self, event: str, **fields) -> None: ...


@dataclass(frozen=True)
class QuestionFacts:
    task: str
    coder_tools: str = ""


@dataclass(frozen=True)
class Judge:
    summarize: groundedaction.Summarize
    chat: Callable
    role: object | None
    log: Log

    def rehunt(self, facts: QuestionFacts, query: str, prior: str) -> bool:
        if self.role is None or not (query.strip() and prior.strip()):
            return False
        text = self.summarize(self.chat, self.role, prompts.load("search_rehunt_judge"),
            prompts.render("search_rehunt_judge_user", task=facts.task, query=query, prior=prior),
            self.log, phase="reasoner", coder_tools=facts.coder_tools) or ""
        obj = extract_json_object(strip_think(text))
        return isinstance(obj, dict) and obj.get("new_direction") is True


class _RehuntCache(UserDict[str, bool]):
    """Reference-backed answers and unspent grants, never a second repeat owner.

    Historical positive answers have unknown spend and cannot invent fresh grants.
    """
    def __init__(self, records: MutableMapping[str, bool] | None = None):
        self.data = {} if records is None else records
        self.grantable: set[str] = set()

    @property
    def records(self) -> MutableMapping[str, bool]:
        return self.data


def _record_rehunt_grant(cache: MutableMapping[str, bool] | None, query: str) -> None:
    if isinstance(cache, _RehuntCache):
        cache.grantable.discard(query)


@dataclass
class RehuntState:
    verdicts: MutableMapping[str, bool] | None = None

    def reset(self) -> None:
        self.verdicts = None


@dataclass(frozen=True)
class SearchCall:
    query: str
    call: dict


def search_call(coder: dict) -> SearchCall | None:
    message = (coder.get("choices") or [{}])[0].get("message") or {}
    call = next((tc for tc in message.get("tool_calls") or []
                 if isinstance(tc, dict)
                 and ((tc.get("function") or tc).get("name") or "") == "web_search"), None)
    if call is None:
        return None
    query = str(toolargs.parse_args((call.get("function") or {}).get("arguments")).get("query", "")).strip()
    return SearchCall(query, call) if query else None


@dataclass(frozen=True)
class RehuntInput:
    coder: dict
    session: str | None
    facts: Callable[[], QuestionFacts]
    judge: Judge
    defer_clearance: bool = False


@dataclass(frozen=True)
class RehuntResult:
    query: str = ""
    prior: str | None = None
    new_direction: bool | None = None
    clearance_requested: bool = False


def rehunt(source: RehuntInput, state: RehuntState, *, enabled: bool = True) -> RehuntResult:
    if not enabled or researchpolicies.current().search is None:
        return RehuntResult()
    selected = search_call(source.coder)
    if selected is None:
        return RehuntResult()
    query = selected.query
    prior = webfetch.prior_matching_search(source.session, query)
    if prior and normalize_search(prior) == normalize_search(query):
        prior = None
    if not prior:
        return RehuntResult(query)
    if query in (state.verdicts or {}):
        fresh = state.verdicts[query]
        eligible = (source.defer_clearance and fresh is True
                    and isinstance(state.verdicts, _RehuntCache)
                    and query in state.verdicts.grantable)
        return RehuntResult(query, prior, fresh, eligible)
    if state.verdicts is None:
        state.verdicts = _RehuntCache()
    fresh = source.judge.rehunt(source.facts(), query, prior)
    if fresh and not isinstance(state.verdicts, _RehuntCache):
        state.verdicts = _RehuntCache(state.verdicts)
    state.verdicts[query] = fresh
    if fresh:
        state.verdicts.grantable.add(query)
    if fresh and not source.defer_clearance:
        webfetch.allow_search(source.session, query)
        _record_rehunt_grant(state.verdicts, query)
        source.judge.log.emit("loop.search_rehunt_cleared", query=query, prior=prior)
    return RehuntResult(query, prior, fresh, fresh)


def settle_rehunt(result: RehuntResult, coder: dict, session: str | None, log: Log) -> bool:
    current = search_call(coder)
    if (not result.clearance_requested or result.new_direction is not True or not result.prior
            or current is None or current.query != result.query):
        return False
    webfetch.allow_search(session, result.query)
    log.emit("loop.search_rehunt_cleared", query=result.query, prior=result.prior)
    return True


@dataclass(frozen=True)
class RehuntDefinition:
    policy: Policy
    execute: Callable[..., RehuntResult]
    settle: Callable[..., bool] = settle_rehunt


REHUNT = RehuntDefinition(Policy(
    "overlapping-search-new-direction", "outgoing-search-rehunt", 5, family_id="F51",
    prompts=("search_rehunt_judge", "search_rehunt_judge_user"),
    state="Reference-backed per-session bool answers; cache-owned unspent-grant metadata; canonical owner consumes one-use clearance",
    services=("selected-search-repeat-public-api", "shared-task-and-tool-facts", "summary-provider"),
    hooks=(Reference("cria/loop.py", "guard_search_query"), Reference("cria/loop.py", "Loop._coder_turn_impl"),
           Reference("cria/loop.py", "Loop.drive")),
    regressions=(Reference("tests/test_semantic_query_policy.py", "test_repeat_disabled_never_enters_detector_or_clearance"),
                 Reference("tests/test_semantic_query_production_binding.py", "test_public_exact_rehunt_replacement_defers_then_uses_canonical_public_admission"),
                 Reference("tests/test_search_relevance_is_removed.py", "test_new_direction_clearance_still_uses_rehunt_not_relevance"),
                 Reference("tests/test_semantic_query_production_binding.py", "test_public_discarded_positive_rehunt_earns_first_retained_grant_without_reasking"),
                 Reference("tests/test_semantic_query_production_binding.py", "test_public_historical_positive_unknown_spend_never_invents_a_grant"),
                 Reference("tests/test_semantic_query_production_binding.py", "test_public_rehunt_changed_call_id_cannot_settle_or_spend_first_grant")),
    migrated=False), rehunt)
DEFINITIONS = (REHUNT,)


class LiveState(Protocol):
    rehunt_verdicts: MutableMapping[str, bool] | None
    semantic_pending: PendingTurn | None


class _RehuntView(RehuntState):
    def __init__(self, owner: LiveState):
        self.owner = owner

    @property
    def verdicts(self):
        return self.owner.rehunt_verdicts

    @verdicts.setter
    def verdicts(self, value):
        self.owner.rehunt_verdicts = value


@dataclass(frozen=True)
class Selection:
    rehunt: RehuntDefinition | None = None


@dataclass(frozen=True)
class TurnInput:
    coder: dict
    session: str | None
    facts: Callable[[], QuestionFacts]
    judge: Judge


@dataclass(frozen=True)
class PendingTurn:
    """Only an exact retained search may earn the one-use public clearance."""
    coder: dict
    source: TurnInput
    selection: Selection
    rehunt_result: RehuntResult
    rehunt_call: tuple[str | None, str] | None


@dataclass(frozen=True)
class Settlement:
    rehunt: bool = False


def discard_turn(owner: LiveState) -> None:
    owner.semantic_pending = None


def reset_turn(owner: LiveState) -> None:
    discard_turn(owner)
    owner.rehunt_verdicts = None


def prepare_turn(source: TurnInput, owner: LiveState, selection: Selection) -> dict:
    discard_turn(owner)
    if selection.rehunt is not None:
        evaluated = search_call(source.coder)
        call = (evaluated.call.get("id"), evaluated.query) if evaluated is not None else None
        result = selection.rehunt.execute(RehuntInput(source.coder, source.session,
            source.facts, source.judge, defer_clearance=True), _RehuntView(owner))
        if not isinstance(result, RehuntResult):
            raise TypeError('Selected rehunt returned an invalid result')
        if result.clearance_requested:
            owner.semantic_pending = PendingTurn(source.coder, source, selection, result, call)
    return source.coder


def settle_turn(owner: LiveState, retained: dict | None) -> Settlement:
    pending = owner.semantic_pending
    owner.semantic_pending = None
    if pending is None or retained is not pending.coder:
        return Settlement()
    current = search_call(retained) if pending.rehunt_call is not None else None
    same_call = (current is not None and (current.call.get("id"), current.query) == pending.rehunt_call)
    granted = (pending.selection.rehunt.settle(pending.rehunt_result, retained,
        pending.source.session, pending.source.judge.log) if pending.selection.rehunt is not None and same_call else False)
    if type(granted) is not bool:
        raise TypeError('Selected semantic settlement must report a bool')
    if granted:
        _record_rehunt_grant(owner.rehunt_verdicts, pending.rehunt_result.query)
    return Settlement(granted)
