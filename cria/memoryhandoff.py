"""Harness-owned compaction lifecycle, pending server integration.

Unlike internal compaction this boundary cannot retain rejected history: the
harness has already chosen to replace it. Only re-derived appendices survive a
rejection. Services supply shared judgments/evidence, never another hardener.

Integration: _recognize_compaction -> recognize; _compaction_body (both stream
and buffered paths) -> frame; _harden_compaction_reply -> harden. Select this
whole lifecycle before recognition, not merely before its output transformation.
Write-result observation is shared evidence and remains unconditional at the
caller; the producer record is settled only for an actually hardened reply.
Final wire privacy and retained-result settlement remain Upstream foundations.

Hook adapter contract for the integration owner:
- Keep the marked() routing handshake when selection is off; never call the
  unmarked recognizer, frame or hardener through an alternate ungated path.
- Before hardening, run shared _note_write_results, then resolve SessionFacts
  with the caller's actual session key (_session_cwd, _session_gate_plan,
  _last_gate_flag, _gate_age, _last_checks_note, _history_root and authenticated
  _carried_ledger). Do not replace the latter with parsing a heading.
- Supply inventory as workspace_inventory(root, flavor="briefing"), shared
  _workspace_listing/_fetch_ground_truth/_briefing_disk_truth/_proxy_body and
  validate_compaction_briefing. Supply SUMMARIZE_MAX_TOKENS unchanged.
- execute receives provider.chat, compactor-or-reasoner role, and the retained
  definition.frame as frame_hook for its retry. settle reports the produced
  payload; the producer publishes _HandoffOrigin only after correlating the
  typed result with its actual returned output and original current session.
- Replace/remove the old server bodies together; the streaming path currently
  frames but does NOT harden. Do not introduce streaming retries/validation or
  change existing buffered no-tools/incomplete admission during migration.

This is one F49 lifecycle, not helper-sized policies. F67 protects task authority,
F70 owns internal reject-and-retain compaction, and F76 releases closing briefings;
none acquires a second implementation here. Selection and replacement must bind
all three callables together. migrated=False until the shared owner installs and
proves those bindings; these source tests cannot certify production bypass.
"""
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Protocol
import json

from . import bodykeys, indicators, massage, prompts, selfcompact
from .assistcontract import ExecutableDefinition, Policy, Reference
from .callsyntax import has_tool_call_leak, is_truncated
from .memoryeffects import Effect

LOCAL_COMPACT_MARKER = "<<<LOCAL_COMPACT>>>"


class Log(Protocol):
    def emit(self, kind: str, **fields) -> None: ...


class SamplingRole(Protocol):
    """Caller-owned dataclass role; annotation must not import Root configuration.

    The actual role supports dataclasses.replace(reasoning=...) and applies its
    existing sampling/framing. This boundary neither constructs nor copies its
    configuration and adds no runtime role adapter.
    """
    @property
    def reasoning(self) -> str: ...

    def apply(self, body: dict, *, internal: bool = False, rlog=None) -> None: ...


class Chat(Protocol):
    def __call__(self, body: dict, rlog: Log) -> str: ...


class ProducerSettlement(Protocol):
    """Report produced content; this callback does not attest retained delivery."""
    def __call__(self, reply: str, ledger: str, dropped: bool) -> None: ...


class BriefingValidator(Protocol):
    def __call__(self, chat_fn, role, briefing: str, *, files: str, checks: str,
                 transcript_blocks: list[str], rlog, task: str = "",
                 phase: str = "compaction-validate", messages: list | None = None) -> bool: ...


class ClosedQuestion(Protocol):
    def __call__(self, chat_fn, role, question: str, rlog, *, phase: str,
                 retry_off: bool) -> str: ...


@dataclass(frozen=True)
class EvidenceServices:
    # Full message preparation: drop harness frame, not tool calls/results.
    drop_harness_frame: Callable[[list[dict]], list[dict]]
    inventory: Callable[[str], str]
    listing: Callable[[str], str]
    fetch_facts: Callable[..., str]
    disk_truth: Callable[[str, str, Log], str]
    validate: BriefingValidator
    proxy_body: Callable[[dict], dict]
    summarize_max_tokens: int
    # Chunked distillation of an over-budget transcript (handoffdistill.distill bound to the live
    # provider/window by the caller). None keeps the single-request evidence unchanged.
    distill: Callable[[list[str], int], list[str]] | None = None


@dataclass(frozen=True)
class SessionFacts:
    """One session's facts, resolved by caller using its actual key, never guessed.

    carried_ledger must come from _carried_ledger with that session's producer
    record, not from scraping a heading. Original task comes from shared task
    authority; the caller preserves existing _history_root behavior on migration.
    """
    workspace_root: str = ""
    original_task: str = ""
    gate_plan: object = None
    gate_flag: str = ""
    gate_age: int = 0
    checks: str = ""
    carried_ledger: str = ""


@dataclass(frozen=True)
class HandoffResult:
    completion: dict
    effect: Effect
    prose: str = ""
    ledger: str = ""

    def __post_init__(self):
        if not isinstance(self.effect, Effect):
            raise ValueError("Invalid handoff effect")
        if self.effect is Effect.WITHHELD and self.prose:
            raise ValueError("Withheld handoff cannot carry accepted prose")


def text_of_message(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, list):
        return " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return content if isinstance(content, str) else ""


def latest_user_text(messages: list) -> str:
    for message in reversed(messages or []):
        if isinstance(message, dict) and message.get("role") == "user":
            return text_of_message(message)
    return ""


def marked(messages: list) -> bool:
    """Routing handshake; also usable below context-fix levels without inference."""
    return LOCAL_COMPACT_MARKER in latest_user_text(messages)


def recognize(body: dict, *, selected: bool, context_fixes: bool, chat_fn: Chat,
              role: SamplingRole | None, ask: ClosedQuestion, rlog: Log) -> bool:
    # Marker-only routing is a caller foundation when policy is disabled.
    if not selected:
        return False
    if marked(body.get("messages", [])):
        return True
    if body.get("tools") or not context_fixes:
        return False
    messages = body.get("messages", [])
    if not any(isinstance(m, dict) and m.get("role") in ("assistant", "tool") for m in messages):
        return False
    turn = latest_user_text(messages).strip()
    if not turn or role is None:
        return False
    answer = ask(chat_fn, role, prompts.render("recognize_compaction_request", turn=turn),
                 rlog, phase="compaction-recognize", retry_off=False).strip().upper()
    recognized = answer == "YES"
    rlog.emit("classify.compaction_recognized", by="judge", answer=answer or "(none)",
              recognized=recognized)
    return recognized


def _folded(messages: list) -> list[dict]:
    """The non-anchor history this compaction folds. The summarize ask is excluded by POSITION,
    including the unmarked case."""
    ask_index = next((i for i in range(len(messages) - 1, -1, -1)
                      if isinstance(messages[i], dict) and messages[i].get("role") == "user"), None)
    return [m for i, m in enumerate(messages) if i != ask_index
            and m.get("role") not in ("system", "developer") and not selfcompact.has_anchor(m)]


def evidence_messages(messages: list, services: EvidenceServices) -> list[dict]:
    # The writer reads each folded message as the rolling writer does: without the anchored note cria
    # appended to a tool result (``selfcompact.summarizable``). That note is carried verbatim instead
    # (:func:`carried_notes`), never summarized into the briefing as part of the tool's output.
    return services.drop_harness_frame([selfcompact.summarizable(m) for m in _folded(messages)])


def carried_notes(messages: list) -> str:
    """cria's anchored notes appended to tool results this compaction folds, verbatim, identical copies
    once (``selfcompact.appended_anchor``, the note rolling memory keeps when it folds the host).

    The harness keeps only the reply: a host it discards takes its note with it, and nothing re-derives
    the note afterwards (a dependency-source note answers one search, and that search result is gone).
    So the note rides in the reply beside the other facts cria re-derives from the record."""
    seen: list[str] = []
    for m in _folded(messages):
        note = selfcompact.appended_anchor(m)
        if note is not None and note["content"] not in seen:
            seen.append(note["content"])
    return "\n\n".join(seen)


def frame(body: dict, facts: SessionFacts, services: EvidenceServices, *, selected: bool) -> dict:
    if not selected:
        return body
    evidence = evidence_messages(body.get("messages", []), services)
    composed = selfcompact.compaction_request_messages(
        evidence, services.inventory(facts.workspace_root), facts.gate_plan,
        facts.gate_flag, facts.gate_age)
    if services.distill is not None:
        history_count = len(selfcompact.compaction_evidence_messages(evidence, facts.gate_plan))
        middle = services.distill([m["content"] for m in composed[1:-1]], history_count)
        composed = [composed[0], *(selfcompact.internal_evidence_message(p) for p in middle), composed[-1]]
    framed = {**body, "messages": [
        {"role": "system", "content": prompts.load("selfcompact_summary")}, *composed]}
    # The briefing's own room: without it the floor fills the window with evidence and the
    # default reserve cut long briefings off mid-sentence.
    if not isinstance(framed.get("max_tokens"), int):
        framed["max_tokens"] = services.summarize_max_tokens
    framed.setdefault(bodykeys.OUTPUT_RESERVE, framed["max_tokens"])
    framed[bodykeys.DENSITY_KIND] = "summary"
    return framed


class FramingStage(Protocol):
    def __call__(self, body: dict, facts: SessionFacts, services: EvidenceServices,
                 *, selected: bool) -> dict: ...


def completion_text(completion: dict) -> str:
    for choice in completion.get("choices") or []:
        text = (choice.get("message") or {}).get("content")
        if isinstance(text, str):
            return text
    return ""


def harden(completion: dict, body: dict, facts: SessionFacts, services: EvidenceServices,
           *, selected: bool, chat_fn: Chat, role: SamplingRole | None, rlog: Log,
           settle: ProducerSettlement, frame_hook: FramingStage = frame) -> HandoffResult:
    """One bounded retry, shared three-lens validation, then producer settlement.

    Root supplies the exact retained definition.frame as frame_hook, including on
    retries. The default preserves explicit standalone source calls only; it is
    not a way to recover an absent production selection.

    settle(reply, ledger, dropped) reports the produced payload, never authority
    reconstructed from model-supplied text. Shared write-result
    observation must precede resolving facts even when this policy is disabled.
    """
    if not selected:
        return HandoffResult(completion, Effect.NO_OP)
    comp = completion
    text = completion_text(comp).strip()
    truncated = is_truncated(comp)
    if not text or has_tool_call_leak(text) or truncated:
        pb = services.proxy_body(dict(body))
        pb = {**pb, "messages": [m for m in pb.get("messages", []) if m.get("role") != "system"]}
        pb = frame_hook(pb, facts, services, selected=True)
        if not isinstance(pb.get("max_tokens"), int):
            pb["max_tokens"] = services.summarize_max_tokens
        if role is not None:
            replace(role, reasoning="off").apply(pb, rlog=rlog)
        else:
            pb.setdefault("chat_template_kwargs", {})["enable_thinking"] = False
        rlog.emit("route.compaction_retry", level="info", had_leak=bool(text),
                  truncated=truncated, max_tokens=pb["max_tokens"])
        try:
            comp2 = massage.coerce_text_answer(
                massage.apply(json.loads(chat_fn(pb, rlog)), None, rlog), rlog)
            text2 = completion_text(comp2).strip()
            if text2 and not has_tool_call_leak(text2) and not is_truncated(comp2):
                comp, text = comp2, text2
            else:
                rlog.emit("route.compaction_no_briefing", level="warn", retry_leak=bool(text2))
                text = ""
        except Exception:  # same best-effort retry boundary as the existing server
            rlog.emit("route.compaction_retry_failed", level="warn")
            text = ""
    fetch = services.fetch_facts(body.get("messages", []), location=False)
    inventory = services.listing(facts.workspace_root)
    if text:
        writer_inventory = services.inventory(facts.workspace_root)
        transcript = selfcompact.compaction_request_parts(
            evidence_messages(body.get("messages", []), services), gate_plan=facts.gate_plan)
        if not services.validate(chat_fn, role, text, files=writer_inventory,
                                 checks=facts.checks, transcript_blocks=transcript,
                                 task=facts.original_task, rlog=rlog,
                                 phase="harness-compaction-validate",
                                 messages=body.get("messages", [])):
            text = ""
    if text and inventory:
        text = services.disk_truth(text, inventory, rlog)
    ledger = (selfcompact.work_ledger(evidence_messages(body.get("messages", []), services),
                                     carried=facts.carried_ledger, root=facts.workspace_root)
              if not text else "")
    notes = carried_notes(body.get("messages", []))
    appendices = "\n\n".join(t for t in (ledger, fetch, notes, inventory, facts.checks) if t)
    if appendices or text != completion_text(comp).strip():
        merged = (text + "\n\n" + appendices).strip()
        if not text and merged:
            merged = indicators.PROSE_DROPPED_MARKER + "\n" + merged
        choices = [dict(ch) for ch in comp.get("choices") or []]
        if choices:
            choices[0] = {**choices[0], "message": {**(choices[0].get("message") or {}), "content": merged}}
            comp = {**comp, "choices": choices}
    # Validation reads normalized working text, not delivery authority. With no
    # appendix the completion may be retained byte-for-byte (including leading
    # or trailing whitespace); with appendices, the merged payload above removes
    # only its outer leading whitespace from the prose prefix.
    retained_prose = (text.lstrip() if appendices else completion_text(comp)) if text else ""
    settle(completion_text(comp), ledger, not bool(text))
    return HandoffResult(comp, Effect.DELIVERED if text else Effect.WITHHELD, retained_prose, ledger)


POLICY = Policy(
    "harness-memory-handoff", "harness-memory", 3, family_id="F49",
    prompts=("recognize_compaction_request", "selfcompact_summary", "compaction_extract",
             "compaction_extract_ask", "compaction_extracted_state", "compaction_extracted_labels"),
    state="session producer record; shared write-result evidence observed before facts resolution",
    services=("original task", "workspace inventory", "gate evidence", "transcript",
              "three-lens validator", "provider", "authenticated carried ledger", "producer settlement"),
    hooks=(Reference("cria/server.py", "_recognize_compaction"),
           Reference("cria/server.py", "_compaction_body"),
           Reference("cria/server.py", "_harden_compaction_reply")),
    regressions=(Reference("tests_backup/test_harness_memory_source.py", "test_source_matches_server"),
                 Reference("tests_backup/test_harness_memory_source.py", "test_disabled_does_not_touch_evidence_judgment_or_state"),
                 Reference("tests_backup/test_harness_memory_boundaries.py", "test_producer_authentication_survives_real_continuation_and_final_wire")),
    migrated=False,
)


class HardeningStage(Protocol):
    def __call__(self, completion: dict, body: dict, facts: SessionFacts,
                 services: EvidenceServices, *, selected: bool, chat_fn: Chat,
                 role: SamplingRole | None, rlog: Log, settle: ProducerSettlement,
                 frame_hook: FramingStage = frame) -> HandoffResult: ...


class RecognitionStage(Protocol):
    def __call__(self, body: dict, *, selected: bool, context_fixes: bool,
                 chat_fn: Chat, role: SamplingRole | None, ask: ClosedQuestion, rlog: Log) -> bool: ...


@dataclass(frozen=True)
class HandoffDefinition:
    policy: Policy = POLICY
    execute: HardeningStage = harden
    recognize: RecognitionStage = recognize
    frame: FramingStage = frame


DEFINITION = HandoffDefinition()


def selected_definition(definitions: Iterable[ExecutableDefinition]) -> HandoffDefinition | None:
    """Project the exact immutable lifecycle, never a default for absent selection.

    The producer retains this object across recognition, framing and hardening.
    Required message evidence and write-result observations do not need this
    selection and must remain reachable when the projection is None.
    """
    selected = None
    for definition in definitions:
        if (not isinstance(definition, HandoffDefinition)
                and definition.policy.id != POLICY.id and definition.policy.stage != POLICY.stage):
            continue
        if selected is not None:
            raise ValueError("Duplicate harness memory handoff selection")
        if (not isinstance(definition, HandoffDefinition) or definition.policy != POLICY
                or any(not callable(getattr(definition, name)) for name in ("recognize", "frame", "execute"))):
            raise ValueError("Harness memory replacement must preserve its typed lifecycle contract")
        selected = definition
    return selected
