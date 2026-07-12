"""Request classifier — the front of routing.

One cheap call to the local classifier model tags the incoming request on two
axes at once:

* **engagement** — ``question`` (answer it) / ``simple`` (a small change, no plan)
  / ``task`` (a multi-step job worth the plan loop). This gates *how much cria*
  engages; the plan loop itself lands in phases 5–6.
* **task_type** — ``coding`` / ``reasoning`` / ``question``, which selects the
  failover chain the router walks.

Cached per task (keyed by the latest user message) so the agent's many follow-up
turns within one task don't each pay a classification call. When the model's
output can't be parsed, we fall back to the configured **bias** — deliberately the
*heavier* path, because under-engaging a real task is the costly mistake.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, replace

from . import prompts
from .jsontext import extract_json_object

_ENGAGEMENTS = ("question", "simple", "task")
_TASK_TYPES = ("coding", "reasoning", "question")
_CACHE_CAP = 256

# The classifier prompt lives in cria/prompts/classify.txt (edit it there).


@dataclass(frozen=True)
class Classification:
    engagement: str  # question | simple | task
    task_type: str  # coding | reasoning | question
    reason: str
    cached: bool = False


class Classifier:
    def __init__(self, provider, model: str, bias: str = "task", role=None) -> None:
        self._provider = provider  # an Upstream-like with .chat(body, rlog)
        self._model = model
        self._bias = bias if bias in _ENGAGEMENTS else "task"
        self._role = role  # LocalRole | None — this role's per-request sampling/reasoning
        self._cache: dict[str, Classification] = {}
        self._lock = threading.Lock()

    def classify(self, messages: list[dict], rlog) -> Classification:
        task = latest_user_text(messages)
        key = _task_key(task)
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            rlog.emit("route.classify", cached=True, engagement=hit.engagement, task_type=hit.task_type)
            return replace(hit, cached=True)

        result = self._call(task, rlog)
        with self._lock:
            if len(self._cache) >= _CACHE_CAP:
                self._cache.clear()
            self._cache[key] = result
        return result

    def _call(self, task: str, rlog) -> Classification:
        if not task.strip():
            return self._fallback("no user text to classify")
        body = {
            "model": self._model,
            "stream": False,
            "temperature": 0,  # default; the role's config (cria.toml) overrides below
            # The classification is a short JSON. Cap the output so a reasoning model that
            # fails to stop can't run away to context-length and hang the request.
            "max_tokens": 1024,
            "messages": [
                {"role": "system", "content": prompts.load("classify")},
                {"role": "user", "content": task},
            ],
        }
        if self._role is not None:
            self._role.apply(body)
        try:
            rlog.phase = "classifier"
            raw = self._provider.chat(body, rlog)
        except Exception as e:  # upstream unreachable, timeout, etc.
            rlog.emit("route.classify_error", level="warn", error=str(e))
            return self._fallback("classifier call failed")

        text = completion_text(raw)
        if self._role is not None:
            text = self._role.clean_content(text)  # drop leaked reasoning when reasoning is off
        obj = extract_json_object(text)
        if not obj:
            rlog.emit("route.classify_unparsed", level="warn")
            return self._fallback("unparseable classifier output")

        engagement = _one_of(obj.get("engagement"), _ENGAGEMENTS, self._bias)
        task_type = _one_of(obj.get("task_type"), _TASK_TYPES, _default_task_type(engagement))
        reason = str(obj.get("reason", ""))[:200]
        rlog.decide("engagement", engagement, reason or "classified", task_type=task_type)
        return Classification(engagement, task_type, reason)

    def _fallback(self, why: str) -> Classification:
        eng = self._bias  # bias toward engaging — under-engaging a task is the costly error
        rlog_reason = f"fallback: {why}"
        return Classification(engagement=eng, task_type=_default_task_type(eng), reason=rlog_reason)


# ------------------------------------------------------------------ helpers


def latest_user_text(messages: list[dict]) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            return _content_text(msg.get("content"))
    return ""


def completion_text(raw: bytes) -> str:
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ""
    choices = obj.get("choices") if isinstance(obj, dict) else None
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    return _content_text(msg.get("content"))


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # multimodal content parts
        return " ".join(
            part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _task_key(task: str) -> str:
    return hashlib.sha1(" ".join(task.split()).encode("utf-8")).hexdigest()


def _one_of(value, allowed: tuple[str, ...], default: str) -> str:
    v = str(value).lower().strip() if value is not None else ""
    return v if v in allowed else default


def _default_task_type(engagement: str) -> str:
    return "question" if engagement == "question" else "coding"
