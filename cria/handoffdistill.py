"""Chunked distillation of summary evidence that is too big for one request.

Ported from codex-local's compaction service (chunk -> extract per piece -> deterministic merge).
A summary writer (cria's own rolling self-compaction, or the harness's compaction request) is
asked to summarize history that is, by definition, large. Sent as one request, the context floor
had to DROP older evidence to fit, and the briefing could run out of window mid-sentence.

Here no request holds the whole history: older transcript blocks are cut into pieces that each
fit (measured in the floor's own currency: estimate x the learned SUMMARY density, with each
request's reply room reserved), one model call per piece extracts the facts as JSON, and the
pieces' facts are merged IN CODE. Recent blocks and appended authoritative facts (files on disk,
last checks, pinned task) stay verbatim.

Doctrine:
- The condensation is LABELLED (⟦ctx:extracted⟧) and floor-protected, so it is never the first
  thing the floor drops.
- Order is preserved: each run of consecutive extracted pieces becomes one labelled block in its
  original position; a piece whose extraction fails stays verbatim where it was.
- An extraction is accepted only if it is a JSON object with known keys of the right types and at
  least one non-empty fact. Anything else ({} / wrong keys / object-shaped entries / truncation)
  is a failure, and the piece stays verbatim: nothing is silently replaced by an empty block.
- Nothing runs unless the evidence exceeds the measured budget; small requests are unchanged.
- The floor remains the single last-resort reducer, with its own label.
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable

from . import bodykeys, jsontext, prompts, tokenratio
from .content_reduce import est_tokens

MARKER = "⟦ctx:extracted⟧"
LIST_KEYS = ("files_touched", "commands_run", "errors", "accepted_fixes", "rejected_ideas",
             "constraints", "environment", "pending", "test_status", "references")
KNOWN_KEYS = ("objective", "latest_plan") + LIST_KEYS
EXTRACT_REPLY_TOKENS = 4096     # each extraction call's own reply room
FRAME_TOKENS = 2560             # system instruction + intro + ask around a composed request (the
                                # self-compaction writer's frame measures ~1.9K)
MAX_PIECES = 24                 # bound on extra calls for one summary; the rest stays verbatim


@dataclass
class MergedState:
    objective: str = ""
    lists: dict = field(default_factory=lambda: {k: [] for k in LIST_KEYS})
    latest_plan: list = field(default_factory=list)
    chunks: int = 0


def valid_extraction(obj) -> dict | None:
    """The extraction contract, or None. Object-shaped or non-string entries reject the whole
    reply rather than being guessed at; an object with no non-empty known fact is a failure."""
    if not isinstance(obj, dict) or not any(k in obj for k in KNOWN_KEYS):
        return None
    out, facts = {}, 0
    for key in KNOWN_KEYS:
        value = obj.get(key, "" if key == "objective" else [])
        if key == "objective":
            if not isinstance(value, str):
                return None
            out[key] = value.strip()
            continue
        if isinstance(value, str):
            value = [value] if value.strip() else []
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return None
        out[key] = [v.strip() for v in value if v.strip()]
        if key != "latest_plan":         # a goal or plan alone is not evidence of what happened
            facts += len(out[key])
    return out if facts else None


def merge(extractions: list[dict]) -> MergedState:
    """Deterministic merge (codex-local merger): union in order, newest wording kept on duplicates,
    latest non-empty objective and plan."""
    state = MergedState(chunks=len(extractions))
    for e in extractions:
        if e.get("objective"):
            state.objective = e["objective"]
        if e.get("latest_plan"):
            state.latest_plan = list(e["latest_plan"])
    for key in LIST_KEYS:
        seen, merged = set(), []
        for e in reversed(extractions):
            for item in reversed(e.get(key) or []):
                k = " ".join(item.lower().split())
                if k not in seen:
                    seen.add(k)
                    merged.append(item)
        state.lists[key] = list(reversed(merged))
    return state


def render_state(state: MergedState, turns: int) -> str:
    labels = prompts.load_map("compaction_extracted_labels")
    sections = []
    if state.objective:
        sections.append(f"{labels['objective']}:\n- {state.objective}")
    for key in LIST_KEYS:
        if state.lists[key]:
            sections.append(f"{labels[key]}:\n" + "\n".join(f"- {i}" for i in state.lists[key]))
    if state.latest_plan:
        sections.append(f"{labels['latest_plan']}:\n" + "\n".join(f"- {i}" for i in state.latest_plan))
    return prompts.render("compaction_extracted_state", turns=turns, chunks=state.chunks,
                          state="\n\n".join(sections))


def chunk(blocks: list[str], budget: float, density: float) -> list[list[str]]:
    """Consecutive blocks grouped so each group fits ``budget`` real tokens at ``density``."""
    groups, current, size = [], [], 0.0
    for b in blocks:
        t = est_tokens(b) * density
        if current and size + t > budget:
            groups.append(current)
            current, size = [], 0.0
        current.append(b)
        size += t
    if current:
        groups.append(current)
    return groups


# Accepted extractions by exact piece text: a retried summary over the same older pieces (a
# rejected briefing, a pressure retry, the harness retry) pays nothing for pieces already read.
# Only accepted extractions are cached; a failed piece is asked again next time.
_CACHE: OrderedDict = OrderedDict()
_CACHE_MAX = 256
_cache_lock = threading.Lock()


def _piece_key(group: list[str]) -> str:
    return hashlib.sha256("\x00".join(group).encode("utf-8", "replace")).hexdigest()


def extract(group: list[str], chat_fn: Callable, apply_role: Callable[[dict], None], rlog) -> dict | None:
    key = _piece_key(group)
    with _cache_lock:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            rlog.emit("compaction.distill_cached", blocks=len(group))
            return _CACHE[key]
    got = _extract(group, chat_fn, apply_role, rlog)
    if got is not None:
        with _cache_lock:
            _CACHE[key] = got
            while len(_CACHE) > _CACHE_MAX:
                _CACHE.popitem(last=False)
    return got


def clear_cache() -> None:
    with _cache_lock:
        _CACHE.clear()


def _extract(group: list[str], chat_fn: Callable, apply_role: Callable[[dict], None], rlog) -> dict | None:
    # One message per block, so the floor can still reduce (and label) an outlier piece.
    body = {"stream": False, "max_tokens": EXTRACT_REPLY_TOKENS, bodykeys.DENSITY_KIND: "summary",
            "messages": [{"role": "system", "content": prompts.load("compaction_extract")},
                         {"role": "user", "content": prompts.load("composed_evidence_intro")},
                         *({"role": "user", "content": b} for b in group),
                         {"role": "user", "content": prompts.load("compaction_extract_ask")}]}
    apply_role(body)
    previous = getattr(rlog, "phase", None)
    try:
        try:
            rlog.phase = "compaction-extract"   # its own label in captures and density learning
        except AttributeError:
            pass
        reply = json.loads(chat_fn(body, rlog))
        choice = (reply.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            return None
        text = (choice.get("message") or {}).get("content") or ""
        return valid_extraction(jsontext.extract_json_object(jsontext.strip_think(text)))
    except Exception:  # noqa: BLE001 — a failed piece stays verbatim, never lost
        return None
    finally:
        try:
            rlog.phase = previous
        except AttributeError:
            pass


@dataclass(frozen=True)
class Budget:
    window: int            # the served context window, real tokens
    reply: int             # the final summary call's reply room, real tokens
    density: float         # learned summary density (real tokens per estimated token)

    def fits(self, blocks: list[str]) -> bool:
        return sum(est_tokens(b) for b in blocks) * self.density + FRAME_TOKENS + self.reply <= self.window


def distill(blocks: list[str], *, history_count: int, budget: Budget,
            chat_fn: Callable, apply_role: Callable[[dict], None], rlog) -> list[str]:
    """``blocks[:history_count]`` are transcript turns in order; the rest are authoritative facts
    kept verbatim. Returns ``blocks`` unchanged when the final request fits."""
    if budget.fits(blocks) or history_count < 2:
        return blocks
    history, facts = blocks[:history_count], blocks[history_count:]
    avail = budget.window - budget.reply - FRAME_TOKENS - sum(est_tokens(b) for b in facts) * budget.density
    # Keep the newest turns verbatim, up to a third of the final request's evidence room.
    cut, tail = len(history), 0.0
    while cut > 1 and tail + est_tokens(history[cut - 1]) * budget.density <= max(avail, 0) / 3:
        cut -= 1
        tail += est_tokens(history[cut]) * budget.density
    older, recent = history[:cut], history[cut:]
    piece = budget.window - EXTRACT_REPLY_TOKENS - 2 * FRAME_TOKENS
    groups = chunk(older, max(piece, 512), budget.density)
    out, run, extracted, failed = [], [], 0, 0
    run_turns = 0

    def close_run():
        nonlocal run, run_turns
        if run:
            out.append(render_state(merge(run), run_turns))
            run, run_turns = [], 0

    for i, group in enumerate(groups, 1):
        got = None
        if i <= MAX_PIECES:
            rlog.emit("compaction.distill_piece", piece=i, pieces=len(groups), blocks=len(group))
            got = extract(group, chat_fn, apply_role, rlog)
        if got is None:
            failed += 1
            close_run()
            out.extend(group)                      # verbatim, in its original position
        else:
            extracted += 1
            run.append(got)
            run_turns += len(group)
    close_run()
    rlog.emit("compaction.distilled", reshape="summary", turns=len(older), pieces=len(groups),
              extracted=extracted, kept_verbatim=failed, recent_verbatim=len(recent))
    if not extracted:
        return blocks
    return [*out, *recent, *facts]


def summary_density() -> float:
    """Learned density for summary requests on any model, conservative until measured."""
    return tokenratio.observed_kind("summary")


def binder(chat_fn: Callable, window: int | None, reply: int, apply_role: Callable[[dict], None], rlog):
    """A ``distill(blocks, history_count)`` bound to a live provider, or None without a real window."""
    if not window or window <= reply + 2 * FRAME_TOKENS + EXTRACT_REPLY_TOKENS:
        return None
    budget = Budget(window=window, reply=reply, density=summary_density())

    def bound(blocks, history_count):
        return distill(blocks, history_count=history_count, budget=budget,
                       chat_fn=chat_fn, apply_role=apply_role, rlog=rlog)
    return bound


def window_of(chat_fn, rlog) -> int | None:
    """The real window of the Upstream behind ``chat_fn`` (a bound ``Upstream.chat``), or None
    when unknown or only guessed: without a real budget nothing can be sized."""
    owner = getattr(chat_fn, "__self__", None) or getattr(chat_fn, "upstream", None)
    resolve = getattr(owner, "_resolve_window", None)
    if not callable(resolve):
        return None
    window = resolve(rlog)
    return None if getattr(owner, "_window_guessed", False) else window
