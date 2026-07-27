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
# Output budget for cria's own short-verdict model calls (classifier, planner judges). A REASONING
# model spends this budget THINKING before it writes a character, so a tight cap does not buy a short
# answer — it buys NO answer, and an empty verdict is indistinguishable from "nothing to report".
# Measured on a judge at 2000: finish_reason=length, 8,865 chars of reasoning, ZERO content.
JUDGE_MAX_TOKENS = 8192
_CACHE_CAP = 256
_ESCALATE_AFTER = 3  # consecutive classify failures before the fallback escalates to an error log

# The classifier prompt lives in cria/prompts/classify.txt (edit it there).


@dataclass(frozen=True)
class Classification:
    engagement: str  # question | simple | task
    task_type: str  # coding | reasoning | question
    reason: str
    cached: bool = False


class Classifier:
    def __init__(self, provider, bias: str = "task", role=None) -> None:
        self._provider = provider  # an Upstream-like with .chat(body, rlog)
        # No model: the classify body carries no `model`, so the upstream fills the server's loaded
        # model (the single-loaded-model posture — cria never pins an alias).
        self._bias = bias if bias in _ENGAGEMENTS else "task"
        self._role = role  # Role | None — this role's per-request sampling/reasoning
        self._cache: dict[str, Classification] = {}
        self._lock = threading.Lock()
        self._consec_fail = 0  # consecutive classify failures → escalate (a broken classifier
        #                        otherwise hides behind the engage-biased fallback, silently)

    def classify(self, messages: list[dict], rlog) -> Classification:
        task = latest_user_text(messages)
        if is_title_request(task):
            # Codex's UI title-generation aux request EMBEDS the real task ("provide a short title
            # for a task… <the coding task>"), so the LLM classifier mistakes it for a coding task
            # and cria plans it — the title instruction then leaks into every planner prompt.
            # Route it to a plain answer (proxy), never the plan loop.
            rlog.emit("route.classify", aux="title", engagement="question")
            return Classification("question", "question", "Codex title-generation aux request")
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
            # NEVER cache a fallback. It is not a classification — it is the record of one that
            # failed (a cut-off verdict, a parse miss), and caching it applied that failure to every
            # later turn of the same task instead of letting the next call succeed.
            if not result.reason.startswith("fallback:"):
                self._cache[key] = result
        return result

    def _call(self, task: str, rlog) -> Classification:
        if not task.strip():
            return self._fallback("no user text to classify", rlog)
        body = {
            "stream": False,
            "temperature": 0,  # default; the role's config (cria.toml) overrides below
            # The cap is a RUNAWAY GUARD, not a size hint: the verdict is a short JSON, but a
            # reasoning model spends the budget THINKING before it writes a character, so a tight cap
            # buys no answer rather than a short one. Measured on the sibling judge at 2000:
            # finish_reason=length, 8,865 chars of reasoning, ZERO content. This was the last cap left
            # from the generation the 2026-07-17 truncation audit raised to 8192 everywhere else.
            "max_tokens": JUDGE_MAX_TOKENS,
            "messages": [
                {"role": "system", "content": prompts.load("classify")},
                {"role": "user", "content": task},
            ],
        }
        if self._role is not None:
            self._role.apply(body, internal=True, rlog=rlog)
        try:
            rlog.phase = "classifier"
            raw = self._provider.chat(body, rlog)
        except Exception as e:  # upstream unreachable, timeout, etc.
            rlog.emit("route.classify_error", level="warn", error=str(e))
            return self._fallback("classifier call failed", rlog)

        text = completion_text(raw)
        if self._role is not None:
            text = self._role.clean_content(text)  # drop leaked reasoning when reasoning is off
        obj = extract_json_object(text)
        if not obj:
            rlog.emit("route.classify_unparsed", level="warn")
            return self._fallback("unparseable classifier output", rlog)

        engagement = _one_of(obj.get("engagement"), _ENGAGEMENTS, self._bias)
        task_type = _one_of(obj.get("task_type"), _TASK_TYPES, _default_task_type(engagement))
        reason = str(obj.get("reason", ""))[:200]
        rlog.decide("engagement", engagement, reason or "classified", task_type=task_type)
        with self._lock:
            self._consec_fail = 0  # a clean classify resolves the streak
        return Classification(engagement, task_type, reason)

    def _fallback(self, why: str, rlog=None) -> Classification:
        eng = self._bias  # bias toward engaging — under-engaging a task is the costly error
        with self._lock:
            self._consec_fail += 1
            streak = self._consec_fail
        # The bias keeps routing alive, but a PERSISTENT failure (a broken/parse-failing classifier —
        # usually the fenced-JSON/reasoning-leak bug) must not stay invisible: escalate past a few.
        if rlog is not None and streak >= _ESCALATE_AFTER:
            rlog.emit("route.classify_degraded", level="error", consecutive=streak, why=why)
        return Classification(engagement=eng, task_type=_default_task_type(eng), reason=f"fallback: {why}")


# ------------------------------------------------------------------ helpers


# Codex's fixed UI title-generation instruction (a harness aux prompt, not user content nor model
# output — stable text, safe to match). It embeds the real task, so it must be recognized BEFORE
# the LLM classifier is fooled into calling it a coding task.
_TITLE_MARKERS = ("provide a short title for a task", "generate a concise ui title",
                  "structured title field")


def is_title_request(task: str) -> bool:
    t = (task or "").lower()
    return any(m in t for m in _TITLE_MARKERS)


# cria's OWN injected user-role messages — a continuation reframe (⟦ctx:continuation⟧), a
# rollup/briefing/task/checks banner (⟦ctx:…⟧), or a focustrim squash note ([cria removed …]). They
# are cria scaffolding, NOT the user's task. Classifying THEM as the task is a real footgun: a
# continuation briefing ("Earlier in THIS session you worked… produced the summary below") reads as
# task_type=reasoning, which routes the reasoning-ONLY chain — so after a harness compaction the whole
# rest of a CODING session ran on the reasoner (temp 0.6, no coder output-reserve). Skip them and
# classify the genuine user task underneath.
_CRIA_INJECTION_MARKERS = ("⟦ctx:", "[removed")


def latest_user_text(messages: list[dict]) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            text = _content_text(msg.get("content"))
            if any(mk in text for mk in _CRIA_INJECTION_MARKERS):
                continue   # cria's own scaffolding — keep looking for the genuine user task
            return text
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
