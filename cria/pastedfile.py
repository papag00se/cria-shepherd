"""Pasted-file recovery and truthful call-less redrive, one session-local lifecycle.

Parsers, quoted evidence, workspace reads and native-call lowering are shared
foundations. This source owns admission, path choice, whole-file judgment,
prior-ruling use and unsaved-text nudges. Prepared/forwarded calls are NOT writes
that ran: settlement accepts only the transport's actual result facts.
"""
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import posixpath
from typing import Callable, Protocol

from . import callsyntax, generation, massage, prompts
from .assistcontract import Policy, Reference
from .wholefile import ClosedJudge, judge_whole_file

FILE_LINES = 12
MAX_NUDGES = 2


class Log(Protocol):
    def emit(self, kind: str, **fields) -> None: ...


class Workspace(Protocol):
    surveyed: bool
    complete: bool
    folded: bool
    def rel(self, path: str) -> str | None: ...
    def abs(self, path: str) -> str: ...
    def isdir(self, path: str) -> bool | None: ...
    def isfile(self, path: str) -> bool | None: ...
    def files(self) -> list: ...
    def read(self, path: str) -> str | None: ...
    def size(self, path: str) -> int | None: ...


class Budget(Protocol):
    # Shared with dropped/refused-call and generation-protocol redrives. Never
    # reconstruct this count from messages or reset it just for this intervention.
    unexecuted_nudges: int


class Status(Enum):
    DISABLED = "disabled"
    UNCHANGED = "unchanged"
    WITHHELD = "withheld"
    PREPARED = "prepared"
    NUDGE = "nudge"
    FORWARDED = "forwarded"
    SETTLED = "settled"


@dataclass(frozen=True)
class Prepared:
    path: str
    content: str
    call: dict
    completion: dict
    call_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Nudge:
    text: str
    # Full original reply or nothing if cut; never a shortened/invented file.
    carried_reply: str
    user_turn: dict
    # Production may retain this one-shot fact until the consuming frame succeeds.
    # None preserves the standalone admission-time consumption contract.
    unread_fact: str | None = None


@dataclass(frozen=True)
class Delivery:
    prepared: Prepared
    call_ids: tuple[str, ...]


@dataclass(frozen=True)
class Settlement:
    delivery: Delivery
    call_id: str
    ran: bool | None
    changed: bool | None


@dataclass
class State:
    judged: dict[tuple[str, str], str] = field(default_factory=dict)
    other: bool = False
    unread_fact: str = ""
    prepared: Prepared | None = None
    pending_nudge: Nudge | None = None
    delivered_nudge: Nudge | None = None
    delivery: Delivery | None = None
    deliveries: dict[str, Delivery] = field(default_factory=dict)
    settlements: dict[str, Settlement] = field(default_factory=dict)


class StateAccess(Protocol):
    """Live owner fields; adapters alias existing memo/flags, never copy them."""
    judged: dict[tuple[str, str], str]
    other: bool
    unread_fact: str
    prepared: Prepared | None
    pending_nudge: Nudge | None
    delivered_nudge: Nudge | None
    delivery: Delivery | None
    deliveries: dict[str, Delivery]
    settlements: dict[str, Settlement]


@dataclass(frozen=True)
class Evidence:
    completion_text: Callable[[dict], str]
    has_tool_calls: Callable[[dict], bool]
    injected_texts: Callable[[list[dict]], list[str]]
    workspace: Callable[[str], Workspace]
    root_from_messages: Callable[[list[dict]], str | None]
    task_from_messages: Callable[[list[dict]], str]
    exact_task_token: Callable[[str, str], bool]
    coder_has_seen: Callable[[Workspace, str, list[dict]], bool]
    unread_target_fact: Callable[[Workspace, str, list[dict]], str]


@dataclass(frozen=True)
class RecoveryInput:
    completion: dict
    tools: list[dict] | None
    messages: list[dict]
    task: str
    workspace_root: str | None
    reading_step: bool
    evidence: Evidence
    # None is the existing missing chat OR missing role policy, not a new ask.
    ask: ClosedJudge | None
    log: Log


@dataclass(frozen=True)
class Result:
    status: Status
    completion: dict | None = None
    reason: str = ""
    prepared: Prepared | None = None
    nudge: Nudge | None = None
    delivery: Delivery | None = None
    settlement: Settlement | None = None


def resolve_named_file(view: Workspace, name: str, task: str,
                       exact_task_token: Callable[[str, str], bool]):
    rel = view.rel(name)
    if rel is None or not rel:
        return "outside_workspace"
    if view.isdir(rel) is True:
        return "names_a_directory"
    if "/" in rel and view.isfile(rel) is True:
        return rel, True
    if not view.complete or view.folded:
        return "listing_incomplete"
    listed = [r for r in (view.rel(e.path) for e in (view.files() or [])) if r]
    hits = [r for r in listed if r == rel or r.endswith("/" + rel)]
    if len(hits) > 1:
        return "ambiguous_path"
    if len(hits) == 1:
        return hits[0], True
    if not exact_task_token(rel, task or ""):
        return "unnamed_new_file"
    parent = posixpath.dirname(rel)
    if parent and view.isdir(parent) is not True:
        return "unknown_parent"
    return rel, False


def self_quote(lines: list[str], injected_norm: list[str]) -> bool:
    blob = "".join("".join(line.split()) for line in lines)
    return len(blob) >= 80 and any(blob in text for text in injected_norm)


def unsaved_text(content: str, injected: list[str]) -> bool:
    normalized = ["".join(t.split()) for t in injected if t and t.strip()]
    depth, run, fence = 0, 0, []
    for line in (content or "").splitlines():
        token = line.lstrip()
        if token.startswith("```"):
            if token[3:].strip():
                depth += 1
            elif depth > 0:
                if depth == 1 and run >= FILE_LINES and not self_quote(fence, normalized):
                    return True
                depth -= 1
                if depth == 0:
                    run, fence = 0, []
            else:
                depth = 1
            continue
        if depth > 0:
            fence.append(line)
            if line.strip():
                run += 1
    return depth > 0 and run >= FILE_LINES and not self_quote(fence, normalized)


def pasted_paths(reply: str) -> list[str]:
    for block in callsyntax.fenced_file_blocks(reply or ""):
        if sum(1 for line in block["lines"] if line.strip()) >= FILE_LINES:
            return callsyntax.binding_paths(block["binding"]) if block["binding"] else []
    return []


def recover(source: RecoveryInput, state: StateAccess, *, enabled: bool = True) -> Result:
    comp = source.completion
    if not enabled:
        return Result(Status.DISABLED, comp)
    if not generation.may_recover(comp):
        return Result(Status.UNCHANGED, comp)
    state.other = False
    if source.ask is None:
        return Result(Status.UNCHANGED, comp)
    choice = (comp.get("choices") or [None])[0]
    msg = (choice or {}).get("message")
    if not isinstance(msg, dict) or msg.get("tool_calls") or choice.get("finish_reason") not in (None, "stop"):
        return Result(Status.UNCHANGED, comp)
    text = source.evidence.completion_text(comp)
    if "```" not in text or source.reading_step:
        return Result(Status.UNCHANGED, comp)
    if callsyntax.whole_file_write_call(source.tools, "x", "y") is None or callsyntax.has_call_envelope(text):
        return Result(Status.UNCHANGED, comp)
    block = next((b for b in callsyntax.fenced_file_blocks(text)
                  if b["closed"] and b["binding"]
                  and sum(1 for line in b["lines"] if line.strip()) >= FILE_LINES), None)
    if block is None:
        return Result(Status.UNCHANGED, comp)
    names = callsyntax.binding_paths(block["binding"])
    if len(names) != 1:
        return Result(Status.UNCHANGED, comp)

    def refuse(why, **fields):
        source.log.emit("loop.text_write_refused", reason=why, path=names[0], **fields)
        return Result(Status.WITHHELD, comp, why)

    root = source.workspace_root or source.evidence.root_from_messages(source.messages)
    view = source.evidence.workspace(root) if root else None
    if view is None or not view.surveyed:
        return refuse("workspace_unsurveyed")
    task = source.task or source.evidence.task_from_messages(source.messages)
    target = resolve_named_file(view, names[0], task, source.evidence.exact_task_token)
    if isinstance(target, str):
        return refuse(target)
    rel, exists = target
    lines = block["lines"]
    content = "\n".join(lines) + "\n"
    injected = ["".join(t.split()) for t in source.evidence.injected_texts(source.messages) if t.strip()]
    if self_quote(lines, injected):
        return refuse("quote_of_shown_text")
    current = view.read(rel) if exists else None
    if current is not None and "".join(current.split()) == "".join(content.split()):
        return refuse("unchanged")
    if exists and not source.evidence.coder_has_seen(view, rel, source.messages):
        state.unread_fact = source.evidence.unread_target_fact(view, rel, source.messages)
        return refuse("unread_existing_file")
    key = (rel, hashlib.sha1(content.encode("utf-8", "replace")).hexdigest())
    verdict = state.judged.get(key)
    if verdict is None:
        facts = prompts.load_map("text_write_facts")
        block_bytes = len(content.encode("utf-8", "replace"))
        size = view.size(rel) if exists else None
        fact = prompts.fill(facts["new_file"] if not exists else facts["exists_sized"] if size is not None
                            else facts["exists_unsized"], bytes=size, block_bytes=block_bytes)
        ordinal = 1 + next(i for i, b in enumerate(callsyntax.fenced_file_blocks(text))
                           if b["start"] == block["start"])
        question = prompts.load("text_write_judge") + "\n\n" + prompts.render(
            "text_write_judge_user", path=rel, fact=fact, ordinal=ordinal, lang=block["lang"] or "none",
            lines=sum(1 for line in lines if line.strip()), binding=block["binding"], reply=text)
        verdict = judge_whole_file(source.ask, question, phase="text-write")
        if verdict in ("WHOLE_FILE", "OTHER"):
            state.judged[key] = verdict
        source.log.emit("loop.text_write_judged", path=rel, verdict=verdict[:40], exists=exists)
    if verdict != "WHOLE_FILE":
        state.other = verdict == "OTHER"
        return refuse("judged_other" if verdict == "OTHER" else "judge_unanswered")
    call = callsyntax.whole_file_write_call(source.tools, view.abs(rel), content)
    keep = text[:block["start"]].rstrip()
    promoted = massage.promote_call(comp, call, keep, source.tools, source.log, path=rel, exists=exists,
                                    block_lines=len(lines), dropped_chars=len(text) - len(keep))
    prepared = state.prepared = Prepared(rel, content, call, promoted, _call_ids(promoted))
    return Result(Status.PREPARED, promoted, prepared=prepared)


@dataclass(frozen=True)
class NudgeInput:
    completion: dict
    messages: list[dict]
    evidence: Evidence
    budget: Budget
    log: Log
    # The multi-step seat excludes reading; the single-item seat has no such test.
    reading_step: bool = False
    step: int | None = None
    plan_off: bool = False
    defer_unread_consumption: bool = False
    # Exact offer present in this coder invocation, not a transport ACK. A new
    # call-less reply must earn a fresh admission against the shared budget.
    consumed: Nudge | None = None


def redrive(source: NudgeInput, state: StateAccess, *, enabled: bool = True) -> Result:
    if not enabled:
        return Result(Status.DISABLED, source.completion)
    if source.reading_step or source.evidence.has_tool_calls(source.completion):
        return Result(Status.UNCHANGED, source.completion)
    other, state.other = state.other, False
    if other:
        # An actual newer ruling revokes fresh admission, not a prior frame's
        # transport obligation. The caller retains that exact consumption fact.
        state.pending_nudge = None
        return Result(Status.UNCHANGED, source.completion)
    if (source.defer_unread_consumption and state.pending_nudge is not None
            and state.pending_nudge is not source.consumed):
        return Result(Status.NUDGE, source.completion, nudge=state.pending_nudge)
    reply = source.evidence.completion_text(source.completion)
    if not unsaved_text(reply, source.evidence.injected_texts(source.messages)):
        return Result(Status.UNCHANGED, source.completion)
    if source.budget.unexecuted_nudges >= MAX_NUDGES:
        return Result(Status.UNCHANGED, source.completion)
    source.budget.unexecuted_nudges += 1
    fields = ({"plan_off": True} if source.plan_off else {"step": source.step})
    source.log.emit("loop.unexecuted_write", attempt=source.budget.unexecuted_nudges, **fields)
    names = pasted_paths(reply)
    base = (prompts.fill(prompts.load("unexecuted_write_nudge_path"), path=f"`{names[0]}`")
            if len(names) == 1 else prompts.load("unexecuted_write_nudge"))
    fact = state.unread_fact
    if not source.defer_unread_consumption:
        state.unread_fact = ""
    text = f"{base}\n\n{fact}" if fact else base
    nudge = state.pending_nudge = Nudge(text, "" if callsyntax.is_truncated(source.completion) else reply,
        {"role": "user", "content": prompts.render("nudge", reason=text)},
        fact if source.defer_unread_consumption else None)
    return Result(Status.NUDGE, source.completion, nudge=nudge)


def nudge_delivered(state: StateAccess, nudge: Nudge, *, enabled: bool = True,
                    consumed: Nudge | None = None) -> Result:
    if not enabled:
        return Result(Status.DISABLED)
    if state.pending_nudge is not nudge and consumed is not nudge:
        return Result(Status.UNCHANGED)
    if nudge.unread_fact is not None and state.unread_fact == nudge.unread_fact:
        state.unread_fact = ""
    state.delivered_nudge = nudge
    if state.pending_nudge is nudge:
        state.pending_nudge = None
    return Result(Status.FORWARDED, nudge=nudge)


def _call_ids(completion: dict) -> tuple[str, ...]:
    # Structured first-choice wire facts, never a parser for calls inside text.
    calls = ((completion.get("choices") or [{}])[0].get("message") or {}).get("tool_calls") or []
    return tuple(call["id"] for call in calls if call.get("id"))


def forwarded(state: StateAccess, prepared: Prepared, actual_completion: dict, *, enabled: bool = True) -> Result:
    if not enabled:
        return Result(Status.DISABLED)
    if prepared is not state.prepared:
        return Result(Status.UNCHANGED)
    # Final frames may be copied. Correlate by native call IDs, not Python object
    # identity, and never attribute unrelated native calls to the recovered draft.
    actual_ids = _call_ids(actual_completion)
    ids = tuple(cid for cid in actual_ids if cid in prepared.call_ids)
    if actual_ids and not ids:
        return Result(Status.UNCHANGED, reason="unrelated_completion")
    state.prepared = None
    if not ids:
        return Result(Status.WITHHELD, reason="no_forwarded_call", prepared=prepared)
    delivery = state.delivery = Delivery(prepared, ids)
    for call_id in ids:
        state.deliveries[call_id] = delivery
    return Result(Status.FORWARDED, delivery=delivery)


def settle(state: StateAccess, delivery: Delivery, call_id: str, *, ran: bool | None,
           changed: bool | None, enabled: bool = True) -> Result:
    if not enabled:
        return Result(Status.DISABLED)
    if state.deliveries.get(call_id) is not delivery or call_id in state.settlements:
        return Result(Status.UNCHANGED)
    fact = state.settlements[call_id] = Settlement(delivery, call_id, ran, changed)
    del state.deliveries[call_id]
    return Result(Status.SETTLED, settlement=fact)


def cancel(state: StateAccess, *, enabled: bool = True) -> Result:
    """Cancel unconsumed offers, not admitted deliveries or shared step budget."""
    if not enabled:
        return Result(Status.DISABLED)
    state.prepared = state.pending_nudge = state.delivered_nudge = None
    return Result(Status.UNCHANGED)


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable[..., Result]
    redrive: Callable[..., Result]
    forwarded: Callable[..., Result]
    settle: Callable[..., Result]
    nudge_delivered: Callable[..., Result]
    cancel: Callable[..., Result] = cancel


DEFINITION = Definition(Policy(
    "pasted-file-recovery", "pasted-file-lifecycle", 2, family_id="F16",
    prompts=("text_write_judge", "text_write_judge_user", "text_write_facts",
             "unexecuted_write_nudge_path", "unexecuted_write_nudge", "nudge"),
    state="State per session/task; byte/path keyed rulings transient; shared redrive budget",
    services=("wholefile.judge_whole_file", "shared-completion-and-fence-parsers",
              "workspace-and-seen-file-evidence", "native-call-lowering", "forwarded-call-and-result-facts",
              "shared-redrive-budget", "retained-output-and-original-owner-facts"),
    hooks=(Reference("cria/loop.py", "Loop._coder_turn_impl"),
           Reference("cria/loop.py", "Loop._work_item"),
           Reference("cria/loop.py", "Loop._drive_single_item"),
           Reference("cria/loop.py", "Loop._recover_text_write"),
           Reference("cria/loop.py", "Loop._pasted_file_unsaved"),
           Reference("cria/loop.py", "Loop._unexecuted_nudge_text"),
           Reference("cria/loop.py", "Loop.drive"),
           Reference("cria/loop.py", "Loop._pasted_redrive"),
           Reference("cria/loop.py", "Loop._retain_pasted_reply"),
           Reference("cria/loop.py", "Loop._settle_pasted_results"),
           Reference("cria/loop.py", "Loop._advance"),
           Reference("cria/server.py", "CriaHandler._defer_pasted_delivery"),
           Reference("cria/server.py", "CriaHandler._translate_out"),
           Reference("cria/server.py", "CriaHandler._retain_pasted_output")),
    regressions=(Reference("tests/write_edit/test_write_edit_arca_pasted.py", "test_only_the_named_whole_file_block_of_a_mixed_reply_becomes_the_write_and_the_judge_sees_the_whole_reply"),
                 Reference("tests/write_edit/test_write_edit_arca_pasted.py", "test_only_an_actual_ruling_is_remembered_and_a_standing_other_suppresses_the_unsaved_claim_without_spending_budget"),
                 Reference("tests/write_edit/test_write_edit_arca_pasted.py", "test_a_changed_byte_key_is_asked_again_and_the_previous_other_is_not_reused"),
                 Reference("tests/write_edit/test_write_edit_arca_pasted.py", "test_an_unread_files_fact_is_consumed_once_and_the_nudge_carries_the_full_reply"),
                 Reference("tests/write_edit/test_write_edit_arca_pasted.py", "test_a_late_result_settles_the_earlier_delivery_it_belongs_to_and_never_twice"),
                 Reference("tests/write_edit/test_write_edit_arca_pasted.py", "test_a_newer_other_revokes_the_standing_offer_and_only_the_actual_offer_object_acknowledges_it"),
                 Reference("tests/write_edit/test_write_edit_arca_pasted.py", "test_a_step_cancel_drops_unconsumed_offers_but_keeps_the_rulings_and_the_deliveries_already_made"),
                 Reference("tests/write_edit/test_write_edit_cov_lifecycles.py", "test_a_prepared_write_is_settled_once_and_only_by_its_own_call_ids"),
                 Reference("tests/write_edit/test_write_edit_cov_lifecycles.py", "test_every_pastedfile_entry_is_inert_when_its_assist_is_off_and_nudge_bookkeeping_survives_a_newer_ruling"),
                 Reference("tests/loop_main/test_loop_main_scenario_pasted_file.py", "test_a_file_pasted_into_chat_becomes_that_files_write_and_its_result_settles_the_delivery"),
                 Reference("tests/loop_main/test_loop_main_scenario_pasted_file.py", "test_a_paste_the_judge_cannot_rule_on_is_redriven_with_its_own_words_and_the_file_named"),
                 Reference("tests/loop_main/test_loop_main_arca_pasted_lifecycle.py", "test_a_deliverys_settlement_carries_only_the_typed_facts_of_its_own_result"),
                 Reference("tests/loop_main/test_loop_main_arca_pasted_lifecycle.py", "test_a_late_result_stays_with_the_older_delivery_and_a_repeated_result_does_not_settle_twice"),
                 Reference("tests/loop_main/test_loop_main_arca_pasted_lifecycle.py", "test_a_write_the_transport_did_not_admit_is_never_delivered_and_a_stale_callback_cannot_touch_a_newer_draft"),
                 Reference("tests/loop_main/test_loop_main_arca_pasted_lifecycle.py", "test_a_competing_redrive_spends_the_same_budget_so_the_paste_is_not_nudged_past_the_bound"),
                 Reference("tests/loop_main/test_loop_main_arca_pasted_lifecycle.py", "test_an_offer_whose_reply_never_reached_the_coder_is_retried_without_a_second_spend_or_losing_its_fact"),
                 Reference("tests/loop_main/test_loop_main_arca_pasted_lifecycle.py", "test_a_restart_forgets_the_rulings_and_every_transient_of_the_paste"),
                 Reference("tests/loop_main/test_loop_main_arca_pasted_lifecycle.py", "test_a_deselected_assist_never_asks_the_judge_promotes_a_paste_or_nudges_for_it")),
    migrated=False), recover, redrive, forwarded, settle, nudge_delivered)
