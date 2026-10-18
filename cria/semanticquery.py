"""Outgoing semantic research guidance; repeat admission remains researchpolicies.SEARCH.

Two questions with separate caches: relevance to the task, and whether an
otherwise-refused overlapping query is a new direction. Shared visible research
facts and the repeat owner's one-use clearance are never copied into these states.
"""
from __future__ import annotations

from collections import UserDict
from collections.abc import MutableMapping
from dataclasses import dataclass
from enum import Enum, auto
import json
import re
from typing import Callable, Protocol
import uuid

from . import bodykeys, groundedaction, prompts, researchpolicies, toolargs, urlgrounding, webfetch
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

    def query(self, facts: QuestionFacts, query: str, tried: str = "") -> tuple[bool, str]:
        if self.role is None or not (facts.task.strip() and query.strip()):
            return True, ""
        text = self.summarize(self.chat, self.role, prompts.load("search_query_judge"),
            prompts.render("search_query_judge_user", task=facts.task, query=query, tried=tried),
            self.log, phase="reasoner", coder_tools=facts.coder_tools) or ""
        obj = extract_json_object(strip_think(text))
        if not isinstance(obj, dict):
            return True, ""
        return obj.get("on_target") is not False, str(obj.get("recommendation") or "").strip()

    def rehunt(self, facts: QuestionFacts, query: str, prior: str) -> bool:
        if self.role is None or not (query.strip() and prior.strip()):
            return False
        text = self.summarize(self.chat, self.role, prompts.load("search_rehunt_judge"),
            prompts.render("search_rehunt_judge_user", task=facts.task, query=query, prior=prior),
            self.log, phase="reasoner", coder_tools=facts.coder_tools) or ""
        obj = extract_json_object(strip_think(text))
        return isinstance(obj, dict) and obj.get("new_direction") is True


@dataclass
class QueryState:
    verdicts: dict[str, tuple[bool, str]] | None = None
    pending: QueryResult | None = None

    def reset(self) -> None:
        self.verdicts = None
        self.pending = None


class _RehuntCache(UserDict[str, bool]):
    """One reference-backed answer mapping with unspent-grant metadata, not a mirror.

    Promotion changes the outer cache identity, never the record dictionary:
    existing record aliases and dynamic Root/Source views see the same updates.
    Only an actual fresh positive judgment creates eligibility; seeded historical
    True entries keep their unknown spend closed. Both records and metadata are
    transient, and reset/drop with this existing cache.
    """
    def __init__(self, records: MutableMapping[str, bool] | None = None):
        # UserDict's normal constructor copies; this facade must borrow instead.
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
    # Production evaluates now, but only the retained returned search earns clearance.
    defer_clearance: bool = False


@dataclass(frozen=True)
class RehuntResult:
    query: str = ""
    prior: str | None = None
    new_direction: bool | None = None
    clearance_requested: bool = False


def rehunt(source: RehuntInput, state: RehuntState, *, enabled: bool = True) -> RehuntResult:
    # Selection precedes even extracting the query. In particular never directly
    # call searchloop's matcher or touch SEARCH's allowed set from this policy.
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
        # Standalone callers retain their immediate admission contract. Production
        # defers this same public-owner operation until the reply is retained.
        webfetch.allow_search(source.session, query)
        _record_rehunt_grant(state.verdicts, query)
        source.judge.log.emit("loop.search_rehunt_cleared", query=query, prior=prior)
    return RehuntResult(query, prior, fresh, fresh)


_CALL_WRAPPED = re.compile(r"\s*\w+\s*\(\s*(['\"])(.+?)\1\s*\)\s*\Z", re.S)
_QUOTED_SPAN = re.compile(r"(['\"])([^'\"]{2,})\1")
_URL_LIKE = re.compile(r"^(https?://\S+|(?:[a-z0-9-]+\.)+[a-z]{2,}/\S*)$", re.I)


def usable_query(rec: str) -> str:
    rec = (rec or "").strip()
    if not rec:
        return ""
    wrapped = _CALL_WRAPPED.fullmatch(rec)
    if wrapped:
        return wrapped.group(2).strip()
    spans = _QUOTED_SPAN.findall(rec)
    if len(spans) > 1:
        return ""
    if len(spans) == 1:
        return spans[0][1].strip()
    return rec


def same_query(a: str, b: str) -> bool:
    return " ".join((a or "").lower().split()) == " ".join((b or "").lower().split())


def looks_like_url(text: str) -> bool:
    return bool(_URL_LIKE.match((text or "").strip()))


class Action(Enum):
    NONE = auto()
    NOTE = auto()
    FETCH = auto()


@dataclass(frozen=True)
class QueryInput:
    coder: dict
    facts: Callable[[], QuestionFacts]
    # Existing fetch renderer + current unresolved refusal ledger, not HTTP-only
    # guesses, session refused-name keyword checks, or a new evidence cache.
    fetched: Callable[[], str]
    refused: Callable[[], str]
    # The existing reasoner-session serializer; used only for URL grounding.
    session_evidence: Callable[[], str]
    judge: Judge


@dataclass(frozen=True)
class QueryResult:
    action: Action = Action.NONE
    query: str = ""
    recommendation: str = ""
    on_target: bool = True
    call_id: str | None = None


def query(source: QueryInput, state: QueryState, *, enabled: bool = True) -> QueryResult:
    if not enabled:
        return QueryResult()
    state.pending = None
    selected = search_call(source.coder)
    if selected is None:
        return QueryResult()
    text = selected.query
    if state.verdicts is None:
        state.verdicts = {}
    facts = source.facts()
    if text in state.verdicts:
        on_target, rec = state.verdicts[text]
    else:
        tried, refused = source.fetched(), source.refused()
        on_target, rec = source.judge.query(facts, text, f"{tried}\n\n{refused}" if refused else tried)
        state.verdicts[text] = on_target, rec
    if not rec or (on_target and usable_query(text) and not looks_like_url(usable_query(rec) or "")):
        return QueryResult()
    rec = usable_query(rec)
    if not rec:
        source.judge.log.emit("loop.search_rec_unusable", level="warn", query=text)
        return QueryResult()
    if same_query(rec, text):
        return QueryResult()
    if looks_like_url(rec):
        url = rec if rec.lower().startswith("http") else "https://" + rec
        # Preserve the original gather order, including serialization when the
        # task host alone suffices. This does not admit repeat searches.
        evidence = facts.task + "\n" + source.session_evidence()
        if not (urlgrounding.host_is_grounded(url, facts.task)
                or urlgrounding.url_is_grounded(url, evidence)):
            source.judge.log.emit("loop.search_query_ungrounded", level="warn", query=text, rec=url)
            return QueryResult()
        state.pending = QueryResult(Action.FETCH, text, url, on_target, selected.call.get("id"))
    else:
        state.pending = QueryResult(Action.NOTE, text, rec, on_target, selected.call.get("id"))
    return state.pending


@dataclass(frozen=True)
class DeliveryInput:
    coder: dict
    result: QueryResult
    session: str | None
    log: Log


def _delivery_note(result: QueryResult) -> str:
    if result.action is Action.FETCH:
        return (f"fetching {result.recommendation} — the source this task names, read it directly"
                if result.on_target else
                f"'{result.query}' looked off-target for this task — fetching {result.recommendation} instead")
    return (f"'{result.query}' may be off-target for this task — '{result.recommendation}' would search for what the "
            "task actually needs. Your search runs either way; re-run it with that if you agree.")


def stage_delivery(source: DeliveryInput, state: QueryState, *, enabled: bool = True) -> dict:
    """Stage bytes on the original completion; no event, clearance or provenance credit."""
    result, coder = source.result, source.coder
    if not enabled or result.action is Action.NONE or state.pending is not result:
        return coder
    current = search_call(coder)
    if current is None or current.query != result.query or current.call.get("id") != result.call_id:
        state.pending = None
        return coder
    if result.action is Action.FETCH:
        coder["choices"][0]["message"]["tool_calls"] = [{
            "id": result.call_id or ("call_" + uuid.uuid4().hex[:16]), "type": "function",
            "function": {"name": "web_fetch", "arguments": json.dumps({"url": result.recommendation})}}]
    coder.setdefault(bodykeys.NOTES, []).append(_delivery_note(result))
    return coder


def settle_delivery(source: DeliveryInput, state: QueryState) -> bool:
    """Commit only a still-present staged effect; public retention is the caller's authority."""
    result, coder = source.result, source.coder
    if state.pending is not result or result.action is Action.NONE:
        return False
    state.pending = None
    if _delivery_note(result) not in (coder.get(bodykeys.NOTES) or []):
        return False
    if result.action is Action.FETCH:
        message = (coder.get("choices") or [{}])[0].get("message") or {}
        calls = message.get("tool_calls") or []
        if len(calls) != 1:
            return False
        call = calls[0]
        function = call.get("function") or {}
        if (function.get("name") != "web_fetch"
                or (result.call_id is not None and call.get("id") != result.call_id)
                or toolargs.parse_args(function.get("arguments")) != {"url": result.recommendation}):
            return False
        source.log.emit("loop.search_query_judged", action="fetch", query=result.query, rec=result.recommendation)
        webfetch.note_substituted(source.session or "", result.recommendation)
    else:
        current = search_call(coder)
        if current is None or current.query != result.query or current.call.get("id") != result.call_id:
            return False
        source.log.emit("loop.search_query_judged", action="noted", query=result.query, rec=result.recommendation)
    return True


def deliver(source: DeliveryInput, state: QueryState, *, enabled: bool = True) -> dict:
    """Settle an evaluated effect only at the selected outgoing stage.

    Evaluation and delivery belong to one coder response. Only the identical
    pending result can settle, once; task reset cancels it without altering facts.
    """
    coder = stage_delivery(source, state, enabled=enabled)
    if enabled:
        settle_delivery(source, state)
    return coder


@dataclass(frozen=True)
class QueryDefinition:
    policy: Policy
    execute: Callable[..., QueryResult]
    deliver: Callable[..., dict]
    stage: Callable[..., dict] = stage_delivery
    settle: Callable[..., bool] = settle_delivery


def settle_rehunt(result: RehuntResult, coder: dict, session: str | None, log: Log) -> bool:
    """Publish clearance after PendingTurn has validated the evaluated call's correlation."""
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


QUERY = QueryDefinition(Policy(
    "outgoing-search-relevance", "outgoing-search-relevance", 5, family_id="F51",
    prompts=("search_query_judge", "search_query_judge_user"),
    state="QueryState per task/session; exact-query cache including unknown; once-only pending effect; task reset cancels both",
    services=("shared-task-and-tool-facts", "visible-fetch-ledger", "unresolved-refusal-ledger", "summary-provider", "substituted-fetch-provenance"),
    hooks=(Reference("cria/loop.py", "guard_search_query"), Reference("cria/loop.py", "Loop._coder_turn_impl"),
           Reference("cria/loop.py", "Loop.drive")),
    regressions=(Reference("tests/test_semantic_query_policy.py", "test_guard_source_parity"),
                 Reference("tests/test_semantic_query_production_binding.py", "test_public_exact_selected_relevance_executes_stages_and_settles_on_same_reply"),
                 Reference("tests/test_semantic_query_production_binding.py", "test_public_late_return_alone_commits_substituted_fetch"),
                 Reference("tests/test_semantic_query_production_binding.py", "test_fresh_public_owner_settles_or_discards_with_existing_persistence_contract"),
                 Reference("tests/test_semantic_query_production_binding.py", "test_live_cache_reference_reset_and_real_store_durable_cleanliness")),
    migrated=False), query, deliver)
REHUNT = RehuntDefinition(Policy(
    "overlapping-search-new-direction", "outgoing-search-rehunt", 5, family_id="F51",
    prompts=("search_rehunt_judge", "search_rehunt_judge_user"),
    state="Reference-backed per-session bool answers; cache-owned unspent-grant metadata; canonical owner consumes one-use clearance",
    services=("selected-search-repeat-public-api", "shared-task-and-tool-facts", "summary-provider"),
    hooks=(Reference("cria/loop.py", "guard_search_query"), Reference("cria/loop.py", "Loop._coder_turn_impl"),
           Reference("cria/loop.py", "Loop.drive")),
    regressions=(Reference("tests/test_semantic_query_policy.py", "test_repeat_disabled_never_enters_detector_or_clearance"),
                 Reference("tests/test_semantic_query_production_binding.py", "test_public_exact_rehunt_replacement_defers_then_uses_canonical_public_admission"),
                 Reference("tests/test_semantic_query_production_binding.py", "test_public_url_substitution_does_not_leave_unused_search_clearance"),
                 Reference("tests/test_semantic_query_production_binding.py", "test_public_distinct_questions_independence_order_and_canonical_clearance"),
                 Reference("tests/test_semantic_query_production_binding.py", "test_public_discarded_positive_rehunt_earns_first_retained_grant_without_reasking"),
                 Reference("tests/test_semantic_query_production_binding.py", "test_public_historical_positive_unknown_spend_never_invents_a_grant"),
                 Reference("tests/test_semantic_query_production_binding.py", "test_public_rehunt_changed_call_id_cannot_settle_or_spend_first_grant")),
    migrated=False), rehunt)
DEFINITIONS = (REHUNT, QUERY)


class LiveState(Protocol):
    """Existing live cache slots plus one transient, non-durable effect obligation."""
    query_verdicts: dict | None
    rehunt_verdicts: MutableMapping[str, bool] | None
    semantic_pending: PendingTurn | None


class _QueryView(QueryState):
    def __init__(self, owner: LiveState):
        self.owner = owner
        self.pending: QueryResult | None = None

    @property
    def verdicts(self):
        return self.owner.query_verdicts

    @verdicts.setter
    def verdicts(self, value):
        self.owner.query_verdicts = value


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
    query: QueryDefinition | None = None


@dataclass(frozen=True)
class TurnInput:
    coder: dict
    session: str | None
    facts: Callable[[], QuestionFacts]
    fetched: Callable[[], str]
    refused: Callable[[], str]
    session_evidence: Callable[[], str]
    judge: Judge


@dataclass(frozen=True)
class PendingTurn:
    """Uncommitted effects, not a receipt or a second evidence/cache authority."""
    coder: dict
    source: TurnInput
    selection: Selection
    query_state: _QueryView
    query_result: QueryResult
    rehunt_result: RehuntResult
    # Immutable factual correlation from the actual evaluated search, not a receipt.
    rehunt_call: tuple[str | None, str] | None


@dataclass(frozen=True)
class Settlement:
    relevance: bool = False
    rehunt: bool = False


def discard_turn(owner: LiveState) -> None:
    pending = owner.semantic_pending
    owner.semantic_pending = None
    if pending is not None:
        pending.query_state.pending = None


def reset_turn(owner: LiveState) -> None:
    """Explicit task reset; never clear public research facts or visibility."""
    discard_turn(owner)
    owner.query_verdicts = None
    owner.rehunt_verdicts = None


def prepare_turn(source: TurnInput, owner: LiveState, selection: Selection) -> dict:
    """Evaluate selected questions, stage bytes in place, retain only effect obligations.

    The returned object is always the original coder completion: existing authenticated
    generation/restoration/remediation correlations must remain valid. Root owns final
    return selection and calls settle_turn only there (discard on failure/replacement).
    """
    discard_turn(owner)
    qs = _QueryView(owner)
    rr = RehuntResult()
    rehunt_call = None
    if selection.rehunt is not None:
        evaluated = search_call(source.coder)
        if evaluated is not None:
            rehunt_call = (evaluated.call.get("id"), evaluated.query)
        rr = selection.rehunt.execute(RehuntInput(source.coder, source.session,
            source.facts, source.judge, defer_clearance=True), _RehuntView(owner))
        if not isinstance(rr, RehuntResult):
            raise TypeError('Selected rehunt returned an invalid result')
    qr = QueryResult()
    if selection.query is not None:
        qr = selection.query.execute(QueryInput(source.coder, source.facts, source.fetched,
            source.refused, source.session_evidence, source.judge), qs)
        if not isinstance(qr, QueryResult):
            raise TypeError('Selected query returned an invalid result')
        staged = selection.query.stage(DeliveryInput(source.coder, qr, source.session, source.judge.log), qs)
        if staged is not source.coder:
            qs.pending = None
            raise ValueError('Selected semantic stage must retain coder completion identity')
    if qs.pending is qr or rr.clearance_requested:
        owner.semantic_pending = PendingTurn(source.coder, source, selection, qs, qr, rr, rehunt_call)
    return source.coder


def settle_turn(owner: LiveState, retained: dict | None) -> Settlement:
    """Only the exact returned reply may commit; equal copies and changed calls cannot."""
    pending = owner.semantic_pending
    owner.semantic_pending = None
    if pending is None:
        return Settlement()
    if retained is not pending.coder:
        pending.query_state.pending = None
        return Settlement()
    source, selected = pending.source, pending.selection
    current = search_call(retained) if pending.rehunt_call is not None else None
    same_rehunt_call = (current is not None
                        and (current.call.get("id"), current.query) == pending.rehunt_call)
    rehunt = (selected.rehunt.settle(pending.rehunt_result, retained, source.session, source.judge.log)
              if selected.rehunt is not None and same_rehunt_call else False)
    if rehunt is True:
        _record_rehunt_grant(owner.rehunt_verdicts, pending.rehunt_result.query)
    relevance = (selected.query.settle(DeliveryInput(retained, pending.query_result,
        source.session, source.judge.log), pending.query_state) if selected.query is not None else False)
    pending.query_state.pending = None
    if type(relevance) is not bool or type(rehunt) is not bool:
        raise TypeError('Selected semantic settlement must report a bool')
    return Settlement(relevance, rehunt)
