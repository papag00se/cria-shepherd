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
    regressions=(Reference("tests_backup/test_pasted_file_policy.py", "test_real_paste_recovers_exact_selected_file_not_fragment_or_trailing_claim"),
                 Reference("tests_backup/test_pasted_file_policy.py", "test_source_question_bytes_and_promoted_payload_match_actual_predecessor"),
                 Reference("tests_backup/test_pasted_file_policy.py", "test_only_actual_rulings_are_remembered_and_other_suppresses_unsaved_claim"),
                 Reference("tests_backup/test_pasted_file_policy.py", "test_byte_key_changes_reask_without_reusing_previous_other"),
                 Reference("tests_backup/test_pasted_file_policy.py", "test_unread_file_fact_is_consumed_once_and_nudge_carries_full_reply"),
                 Reference("tests_backup/test_pasted_file_policy.py", "test_no_success_before_real_correlated_result_and_no_double_settlement"),
                 Reference("tests_backup/test_pasted_file_policy.py", "test_late_result_still_belongs_to_earlier_recovered_bytes"),
                 Reference("tests_backup/test_pasted_file_policy.py", "test_lowered_refusal_never_becomes_a_forwarded_or_executed_write"),
                 Reference("tests_backup/test_pasted_file_policy.py", "test_disabled_whole_lifecycle_never_detects_asks_changes_state_or_spends_budget"),
                 Reference("tests_backup/test_pasted_file_policy.py", "test_semantic_definition_replacement_is_the_executed_source_not_a_legacy_loop_path"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_public_absent_pasted_policy_never_judges_or_promotes_the_recorded_draft"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_public_exact_recovery_replacement_sees_original_draft_and_owns_its_completion"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_public_selected_redrive_replacement_owns_result_and_live_budget"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_public_recovered_draft_is_forwarded_only_after_retained_server_output"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_public_redrive_uses_actual_shared_budget_and_full_carried_bytes"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_public_pending_nudge_is_retryable_without_credit_or_readmission"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_public_settlement_uses_only_correlated_authoritative_result_facts"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_public_late_result_remains_with_older_delivery_and_duplicate_does_not_settle_twice"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_public_final_lowering_not_offered_ids_decides_recovered_write_delivery"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_public_selected_delivery_replacement_has_no_canonical_fallback"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_step_cancel_preserves_memo_and_older_delivery_without_admitting_pending_offer"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_new_owner_does_not_inherit_prepared_nudge_or_delivery_and_restart_omits_transients"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_old_finalization_callback_cannot_erase_or_forward_a_new_prepared_draft"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_other_real_redrives_spend_same_budget_before_paste_admission"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_new_other_ruling_suppresses_older_pending_pasted_write_redrive"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_typed_other_revokes_authorization_without_credit_budget_or_unread_consumption"),
                 Reference("tests_backup/test_pasted_file_production_binding.py", "test_actual_old_consumption_does_not_clear_a_new_authorized_offer_or_its_unread_fact")),
    migrated=False), recover, redrive, forwarded, settle, nudge_delivered)
