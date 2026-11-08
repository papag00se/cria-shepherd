"""Harness compaction recognition, evidence framing and authenticated settlement.

The harness may replace its history with the reply, so the reply carries the original
user task and ordered historical evidence rather than an unverified model briefing.
An optional next action is published only after a complete-response topic judgment.
The server settles and authenticates the produced packet for later expansion; both
buffered and streaming requests pass through the same hardening boundary.
"""
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Protocol

from . import bodykeys, compactionaction, compactionpacket, prompts, selfcompact
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
    topic_judge: object = None


@dataclass(frozen=True)
class SessionFacts:
    """One session's facts, resolved by caller using its actual key, never guessed.

    carried_ledger must come from _carried_ledger with that session's producer
    record, not from scraping a heading. Original task comes from shared task
    authority; the caller preserves existing _history_root behavior on migration.
    """
    workspace_root: str = ""
    original_task: str = ""
    prior_handoffs: tuple[str, ...] = ()  # authenticated anchors, historical evidence, never task authority
    prior_packet: compactionpacket.Packet | None = None
    task_rides_reply: bool = False    # the harness may replace the whole history with the reply, so the reply carries the task
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
    packet: compactionpacket.Packet | None = None

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


def _packet(body: dict, facts: SessionFacts) -> compactionpacket.Packet:
    messages = body.get("messages", [])
    ask_index = next((i for i in range(len(messages) - 1, -1, -1)
                      if isinstance(messages[i], dict) and messages[i].get("role") == "user"), None)
    history = [m for i, m in enumerate(messages) if i != ask_index and isinstance(m, dict)]
    history_blocks = compactionpacket.blocks(history, prior_handoffs=facts.prior_handoffs,
                                             prior_packet=facts.prior_packet)
    # Session-owned checker evidence may no longer exist in the harness's transcript. It is a
    # dated observation, not model prose, and must travel even after the harness replaces history.
    checks = facts.checks or selfcompact.checks_input(facts.gate_flag, facts.gate_age)
    return compactionpacket.Packet(facts.original_task, (*history_blocks, *((checks,) if checks else ())),
        latest_user=compactionpacket.latest_user(history, prior_handoffs=facts.prior_handoffs,
                                                  prior_packet=facts.prior_packet))


def frame(body: dict, facts: SessionFacts, services: EvidenceServices, *, selected: bool) -> dict:
    if not selected:
        return body
    packet = _packet(body, facts)
    framed = {**body, "messages": compactionaction.request_messages(packet.task, packet.blocks, latest_user=packet.latest_user)}
    for key in ("tools", "tool_choice", "parallel_tool_calls"):
        framed.pop(key, None)
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
    """Publish authentic evidence and, if judged on topic, the optional next action."""
    if not selected:
        return HandoffResult(completion, Effect.NO_OP)
    packet = _packet(body, facts)
    initial = completion_text(completion)
    choice = (completion.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    if is_truncated(completion) or has_tool_call_leak(initial) or message.get("tool_calls"):
        initial = ""

    def author(task, evidence, prior):
        if prior is None:
            return initial
        return compactionaction.generate(chat_fn, role, task, evidence, prior, rlog, latest_user=packet.latest_user)

    action = compactionaction.next_action(packet.task, packet.blocks, author, services.topic_judge, rlog)
    packet = replace(packet, action=action)
    text = packet.render()
    choices = [dict(ch) for ch in completion.get("choices") or []]
    if not choices:
        choices = [{"index": 0}]
    choices[0] = {**choices[0], "finish_reason": "stop", "message": {"role": "assistant", "content": text}}
    result = {**completion, "choices": choices}
    settle(text, "", False)
    return HandoffResult(result, Effect.DELIVERED, text, "", packet)


POLICY = Policy(
    "harness-memory-handoff", "harness-memory", 3, family_id="F49",
    prompts=("recognize_compaction_request", "compaction_evidence_packet", "compaction_next_action_system",
             "compaction_next_action_task", "compaction_next_action_ask", "compaction_next_action_followup",
             "compaction_next_action_retry", "compaction_topic_policy"),
    state="session producer record; shared write-result evidence observed before facts resolution",
    services=("original task", "gate evidence", "transcript", "topic classifier", "reasoner", "producer settlement"),
    hooks=(Reference("cria/server.py", "_recognize_compaction"),
           Reference("cria/server.py", "_compaction_body"),
           Reference("cria/server.py", "_harden_compaction_reply")),
    regressions=(Reference("tests/compaction_handoff/test_compaction_handoff_evidence.py", "test_harness_handoff_preserves_tool_evidence_instead_of_invented_briefing"),
                 ),
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
