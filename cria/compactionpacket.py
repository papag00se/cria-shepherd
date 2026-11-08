"""Ordered compaction evidence with producer-owned identity, separate from model prose."""
from __future__ import annotations

import json
from dataclasses import dataclass

from . import bodykeys, prompts, resultnotes


@dataclass(frozen=True)
class ToolEvidence:
    """Producer-held original call and its uniquely matched tool payload."""
    call_id: str
    name: str
    arguments: str
    result: str


def tool_evidence(messages: list[dict]) -> tuple[ToolEvidence, ...]:
    calls, results = {}, {}
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        for call in (message.get("tool_calls") or []) if message.get("role") == "assistant" else ():
            if not isinstance(call, dict):
                continue
            cid = call.get("id")
            if isinstance(cid, str) and cid:
                calls.setdefault(cid, []).append((index, call))
        cid = message.get("tool_call_id")
        if message.get("role") == "tool" and isinstance(cid, str) and cid:
            results.setdefault(cid, []).append((index, message))
    evidence = []
    for cid, occurrences in results.items():
        if len(occurrences) != 1 or len(calls.get(cid, ())) != 1:
            continue
        index, result = occurrences[0]
        call_index, call = calls[cid][0]
        content = result.get("content")
        payload = resultnotes.payload_of(result, content) if isinstance(content, str) else None
        fn = call.get("function")
        if not isinstance(fn, dict):
            continue
        name, args = fn.get("name"), fn.get("arguments")
        if call_index < index and isinstance(name, str) and isinstance(args, str) and payload is not None:
            evidence.append((index, ToolEvidence(cid, name, args, payload)))
    return tuple(item for _, item in sorted(evidence, key=lambda item: item[0]))


@dataclass(frozen=True)
class Packet:
    task: str
    blocks: tuple[str, ...]
    action: str = ""
    latest_user: str = ""
    sources: tuple[ToolEvidence, ...] = ()
    selected: tuple[str, ...] = ()

    def render(self) -> str:
        labels = prompts.load_map("compaction_evidence_packet")
        pieces = ([prompts.fill(labels["task"], task=self.task)] if self.task else []) + [labels["header"], *self.blocks]
        if self.latest_user:
            pieces.append(prompts.render("compaction_next_action_followup", followup=self.latest_user))
        if self.action:
            pieces.append(prompts.fill(labels["action"], action=self.action))
        return "\n\n".join(pieces)


def movable_action(messages: list[dict]) -> bodykeys.ActionOrigin | None:
    """Identify the newest suggestion only if nothing later has independent authority.

    Decide before fitting: dropping a later user request cannot make stale advice current.
    """
    indexes = [i for i, message in enumerate(messages)
               if isinstance(message.get(bodykeys.ACTION_ORIGIN), bodykeys.ActionOrigin)]
    if not indexes:
        return None
    index = indexes[-1]
    allowed = (bodykeys.AnnotationSource.INTERNAL_EVIDENCE, bodykeys.AnnotationSource.WORKSPACE_LISTING)
    if any(message.get("role") != "user" or not any(
            message.get(bodykeys.ANNOTATION_SOURCE) is source for source in allowed)
            for message in messages[index + 1:]):
        return None
    return messages[index][bodykeys.ACTION_ORIGIN]


def place_current_action(messages: list[dict], origin: bodykeys.ActionOrigin | None) -> list[dict]:
    """Move that exact surviving suggestion after observations, never revive a dropped one."""
    if origin is None or movable_action(messages) is not origin:
        return messages
    index = next(i for i, message in enumerate(messages) if message.get(bodykeys.ACTION_ORIGIN) is origin)
    return [*messages[:index], *messages[index + 1:], messages[index]]


def latest_user(messages: list[dict], *, prior_handoffs: tuple[str, ...] = (),
                prior_packet: Packet | None = None) -> str:
    """Most recent genuine user request after work began; producer annotations are not users."""
    saw_work, latest = False, ""
    for message in messages:
        role = message.get("role")
        if role == "user" and message.get("content") in prior_handoffs:
            saw_work = True
            if prior_packet is not None and prior_packet.latest_user:
                latest = prior_packet.latest_user
            continue
        if role in ("assistant", "tool"):
            saw_work = True
        elif saw_work and role == "user" and not isinstance(message.get(bodykeys.ANNOTATION_SOURCE), bodykeys.AnnotationSource):
            content = message.get("content")
            if isinstance(content, str) and content and content not in prior_handoffs:
                latest = content
    return latest


def blocks(messages: list[dict], *, prior_handoffs: tuple[str, ...] = (),
           prior_packet: Packet | None = None) -> tuple[str, ...]:
    """Represent each original turn in order; tool content itself is never rewritten."""
    labels = prompts.load_map("compaction_evidence_packet")
    out = []
    skip = 0
    for index, message in enumerate(messages):
        if skip:
            skip -= 1
            continue
        role = message.get("role")
        if role not in ("user", "assistant", "tool"):
            continue
        content = message.get("content")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False) if content is not None else ""
        if role == "user" and content in prior_handoffs:
            if prior_packet is not None:
                carried = list(prior_packet.blocks)
                if prior_packet.action:
                    carried.append(prompts.fill(labels["action"], action=prior_packet.action))
                out.extend(carried)
                # reframe_compaction may already have expanded this exact producer-owned packet.
                # Consume that expansion once, but never suppress client-supplied lookalikes.
                following = messages[index + 1:index + 1 + len(carried)]
                if len(following) == len(carried) and all(
                    m.get(bodykeys.ANNOTATION_SOURCE) is bodykeys.AnnotationSource.INTERNAL_EVIDENCE
                    and m.get("content") == block for m, block in zip(following, carried)
                ):
                    skip = len(carried)
            else:
                out.append(prompts.fill(prompts.load_map("compaction_grounding")["prior"], turn=content))
            continue
        if role == "tool" and isinstance(message.get("content"), str):
            payload = resultnotes.payload_of(message, content)
            if payload is None:
                out.append(prompts.fill(labels["entry"], role="tool result with unverified attribution", content=content))
                continue
            if payload != content:
                tool_role = f"tool (call id {message['tool_call_id']})" if message.get("tool_call_id") else "tool"
                out.append(prompts.fill(labels["entry"], role=tool_role, content=payload))
                out.append(prompts.fill(labels["entry"], role="producer annotation on tool result", content=content[len(payload):]))
                continue
        calls = message.get("tool_calls")
        if calls:
            content += ("\n" if content else "") + json.dumps(calls, ensure_ascii=False)
        if role == "tool" and message.get("tool_call_id"):
            role = f"tool (call id {message['tool_call_id']})"
        elif role == "user" and message.get(bodykeys.ANNOTATION_SOURCE) is bodykeys.AnnotationSource.INTERNAL_EVIDENCE:
            role = "producer-owned historical evidence"
        out.append(prompts.fill(labels["entry"], role=role, content=content))
    return tuple(out)
