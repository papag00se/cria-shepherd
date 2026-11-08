"""Ordered compaction evidence with producer-owned identity, separate from model prose."""
from __future__ import annotations

import json
from dataclasses import dataclass

from . import bodykeys, prompts, resultnotes


@dataclass(frozen=True)
class Packet:
    task: str
    blocks: tuple[str, ...]
    action: str = ""
    latest_user: str = ""

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
        out.append(prompts.fill(labels["entry"], role=role, content=content))
    return tuple(out)
