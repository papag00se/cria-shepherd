"""Optional, experimentally classified next action for a compaction handoff.

The topic classifier is out of distribution for its trained bundle. An ON_TASK result is not a
truth, grounding, safety, or sentence-shape guarantee. Unavailable or undecidable means silence.
The caller owns the exact original task and evidence and supplies generation from those same bytes.
"""
from __future__ import annotations

import json
from typing import Callable, Protocol

from . import bodykeys, callsyntax, prompts, selfcompact


class TopicJudge(Protocol):
    def judge_compaction_topic(self, task: str, response: str, *, rlog=None) -> str: ...


def next_action(task: str, evidence: tuple[str, ...], generate: Callable[[str, tuple[str, ...], str | None], str],
                judge: TopicJudge | None, rlog=None) -> str:
    """Ask once, retry only an explicit OFF_TOPIC, and never send an unjudged answer.

    The complete first response is passed to the one corrective retry; neither task nor evidence is
    changed. No prefix extraction, fallback classifier, or partial classification is performed.
    """
    def emit(outcome, **fields):
        if rlog is not None:
            rlog.emit("context.compaction_action", outcome=outcome, **fields)

    if judge is None or not task.strip():
        emit("withheld", reason="classifier-unavailable" if judge is None else "task-unavailable")
        return ""
    prior = None
    for attempt in range(2):
        try:
            response = generate(task, evidence, prior)
            if not isinstance(response, str) or not response.strip():
                emit("withheld", reason="empty-or-incomplete", attempt=attempt + 1)
                return ""
            verdict = judge.judge_compaction_topic(task, response, rlog=rlog)
        except Exception as exc:
            emit("withheld", reason="unavailable", error=type(exc).__name__, attempt=attempt + 1)
            return ""
        if verdict == "ON_TASK":
            emit("accepted", attempt=attempt + 1)
            return response
        if verdict != "OFF_TOPIC":
            emit("withheld", reason="undetermined", attempt=attempt + 1)
            return ""
        emit("off-topic", attempt=attempt + 1)
        prior = response
    emit("withheld", reason="retry-off-topic")
    return ""


def request_messages(task: str, evidence: tuple[str, ...], prior: str | None = None,
                     latest_user: str = "") -> list[dict]:
    """Frame the same task and evidence for either the first attempt or its corrective retry."""
    messages = [{"role": "system", "content": prompts.load("compaction_next_action_system")},
                selfcompact.internal_evidence_message(prompts.load("composed_evidence_intro"))]
    messages.extend(selfcompact.internal_evidence_message(block) for block in evidence)
    if prior is not None:
        messages.append({"role": "assistant", "content": prior})
    question = prompts.render("compaction_next_action_task", task=task)
    if latest_user:
        question += "\n\n" + prompts.render("compaction_next_action_followup", followup=latest_user)
    question += "\n\n" + prompts.load("compaction_next_action_retry" if prior is not None else "compaction_next_action_ask")
    messages.append({"role": "user", "content": question})
    return messages


def generate(chat_fn, role, task: str, evidence: tuple[str, ...], prior: str | None, rlog,
             *, latest_user: str = "") -> str:
    """Generate with the complete task and independently reducible historical evidence."""
    body = {"stream": False, "messages": request_messages(task, evidence, prior, latest_user), bodykeys.DENSITY_KIND: "summary"}
    if role is not None:
        role.apply(body, internal=True, rlog=rlog)
    old_phase = getattr(rlog, "phase", None)
    try:
        rlog.phase = "compaction-next-action-retry" if prior is not None else "compaction-next-action"
        completion = json.loads(chat_fn(body, rlog))
    finally:
        rlog.phase = old_phase
    if callsyntax.is_truncated(completion):
        return ""
    choices = completion.get("choices") or []
    message = (choices[0].get("message") or {}) if choices else {}
    content = message.get("content")
    if message.get("tool_calls") or not isinstance(content, str) or callsyntax.has_tool_call_leak(content):
        return ""
    return content
