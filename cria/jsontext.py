"""Extract a JSON object from a small local model's noisy output.

Local models routinely wrap JSON in ```` ```json ```` fences and emit ``<think>``
reasoning before it — both break a naive ``json.loads``. This is the one place
that noise is dealt with, so every JSON-consuming caller (classifier, later the
completion critic and planner) parses the same way.
"""

from __future__ import annotations

import json
import re

_THINK = re.compile(r"<think(?:ing)?\b[^>]*>.*?</think(?:ing)?\s*>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*", re.IGNORECASE)


def strip_think(text: str) -> str:
    """Remove ``<think>…</think>`` blocks (reasoning models emit these before the
    answer). Also drops a dangling unclosed ``<think>`` and everything after it —
    UNLESS a parseable JSON object follows the tag. A model that forgot to close
    its ``<think>`` before emitting the answer (``<think>deciding…\n{"x":1}``)
    still has a real object in the tail; blindly slicing from ``<think`` to the
    end would silently discard that answer, so we keep the tail when it parses.
    """
    text = _THINK.sub("", text)
    lower = text.lower()
    idx = lower.rfind("<think")
    if idx != -1 and "</think" not in lower[idx:]:
        if _scan_object(text[idx:]) is None:
            text = text[:idx]
    return text


def extract_json_object(text: str) -> dict | None:
    """Return the first balanced ``{…}`` JSON object in ``text``, or ``None``.

    Tolerates ```` ```json ```` fences, ``<think>`` preambles, and trailing prose.
    Scans for a brace-balanced span (respecting strings/escapes) so a JSON object
    that itself contains braces in string values still parses.
    """
    if not text:
        return None
    return _scan_object(denoise(text))


def denoise(text: str) -> str:
    """The reply with a model's habitual wrappers removed — ``<think>`` preambles and ```` ``` ````
    fences. The ONE place that preprocessing lives, so :func:`extract_json_object` and
    :func:`close_unclosed_object` never disagree about what "the text" is."""
    return _FENCE.sub("", strip_think(text)).replace("```", "")


def close_unclosed_object(text: str) -> dict | None:
    """A JSON object whose only defect is its MISSING CLOSING BRACE(S), parsed — else ``None``.

    NOT a lenient parser and deliberately not wired into :func:`extract_json_object`. It supplies
    closers — ``}`` and ``]``, in the nesting order the text itself opened them — and nothing else.
    Every byte of key and value is the model's own; if the object needs anything but closers to
    parse (a value, a comma removed, a closing quote) this returns ``None``. That is the whole line
    between reshaping what the model wrote and authoring what it did not (principle 5b/#2).

    Measured 2026-08-02 over 18,655 captured final replies: 14 complete verdicts and re-derivations
    were lost to exactly one absent ``}``, all of them ``finish_reason: stop`` — the model stopped
    on its own, mid-punctuation, with the answer already written. Example (run 20260728T000013, call
    0469-critic, 763 chars): ``{"done": false, "reason": "…no read_file, edit_file, or write_file on
    README.md appears in the evidence.", "proposed_fix": "Check if README.md exists via list_dir…"``
    — read as NO verdict at all.

    TWO refusals are structural, not tuning:

    * A text that ends INSIDE a string is refused. Closing braces around a half-written value would
      hand on a sentence that stops mid-word — the truncation lie rule #5 exists to prevent.
    * A ``finish_reason: length`` reply is refused by the CALLERS, which is where the finish reason
      is visible at all — this function is given only text. Each verdict call site runs
      ``massage.is_truncated`` before reaching here. A cut generation is not a finished answer no
      matter how well the bytes happen to close.

    This says nothing about WHICH way a recovered object rules. That is the caller's to decide, and
    for a verdict it is one-directional — see :func:`cria.loop.verdict_from_unclosed`.
    """
    if not text:
        return None
    cleaned = denoise(text)
    start = cleaned.find("{")
    while start != -1:
        closers = _unclosed_tail(cleaned, start)
        if closers:
            try:
                obj = loads(cleaned[start:] + closers)
            except json.JSONDecodeError:
                obj = None
            if isinstance(obj, dict):
                return obj
        start = cleaned.find("{", start + 1)
    return None


def _unclosed_tail(s: str, start: int) -> str:
    """The closers that would balance the object opening at ``start``, or ``""``.

    ``""`` means there is nothing to repair here — the span already closes (that is
    :func:`extract_json_object`'s job), or it ends inside a string, or ``start`` opens nothing."""
    stack: list[str] = []
    in_str = escaped = False
    for c in s[start:]:
        if in_str:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if not stack or stack[-1] != c:
                return ""          # mismatched nesting — not a missing-closer defect
            stack.pop()
            if not stack:
                return ""          # it closed on its own
    if in_str:
        return ""                  # ends mid-string: closing it would ship a half-written value
    return "".join(reversed(stack))


def _is_empty(v) -> bool:
    """Does this value carry no answer? ``null``, an empty string, an empty container — nothing else.

    ``False`` and ``0`` are ANSWERS, and the distinction is the whole of :func:`_first_wins`. Python
    truthiness conflates them: ``not False`` and ``not []`` are both true, so a first ``"done": false``
    counted as "nothing was said" and a later ``"done": true`` overwrote it. That is the entire verdict
    protocol — every judge cria has answers under a boolean — read by the truthiness of its own answer."""
    return v is None or (isinstance(v, (str, bytes, list, tuple, dict, set)) and not v)


def _first_wins(pairs):
    """Resolve a REPEATED key to its first non-empty value, not its last.

    `json.loads` keeps the LAST occurrence, which is arbitrary and — for model output — usually the
    wrong one: a small model that repeats a key emits its real answer first and a degenerate echo
    after. Measured (run 0727-121457) a planner emitted `{"steps":[<five real steps>],"steps":[1,2,3,4,5]}`
    and stdlib semantics threw the plan away, handing the coder steps named "1", "2", "3".
    Empty-first is skipped so `{"missing":[], "missing":["the tests"]}` still reports the tests.

    EMPTY IS A SHAPE, NOT A TRUTHINESS (fixed 2026-08-03). "Empty" used to be Python falsiness, so a
    JSON ``false`` was treated as nothing-said and the next occurrence replaced it. Measured over
    24,196 captured payloads: 73 repeated keys, 4 of them with a falsy-but-real first value, and
    exactly ONE that cria acts on — run 20260803T112245 call 0157-critic, a step critic that wrote

        {"done": false, "reason": "…", "proposed_fix": "…", "done": true}

    and was read as ``done: true``. cria ADVANCED the step on the later of two contradictory answers.
    A judge that says both has not decided, and an undecided judge means NOT done (#13); reading the
    first is also simply what this function's own name and docstring have always promised. The other
    three occurrences are keys no cria code reads (``has_datum`` ×2, both ``false`` either way, and
    one ``briefing_complete`` inside a model's own summary JSON), so the measured blast radius across
    all 22 callers of :func:`loads` is that single verdict."""
    out = {}
    for k, v in pairs:
        if k in out and (not _is_empty(out[k]) or _is_empty(v)):
            continue          # keep the earlier value unless it was empty and this one is not
        out[k] = v
    return out


def loads(text: str, *, strict: bool = True):
    """THE parser for JSON a MODEL produced. Every such payload — a judge's verdict, a tool call's
    arguments, a submitted plan — goes through here rather than `json.loads`, so a quirk only has to
    be handled once. Currently: repeated keys resolve first-non-empty (see :func:`_first_wins`).
    Raises like `json.loads`; callers that want a soft failure catch it."""
    return json.loads(text, object_pairs_hook=_first_wins, strict=strict)


def _scan_object(s: str) -> dict | None:
    """First brace-balanced span in ``s`` that parses to a ``dict``, else ``None``."""
    start = s.find("{")
    while start != -1:
        span = _balanced_object(s, start)
        if span is not None:
            try:
                obj = loads(span)
            except json.JSONDecodeError:
                obj = None
            if isinstance(obj, dict):
                return obj
        start = s.find("{", start + 1)
    return None


def _balanced_object(s: str, start: int) -> str | None:
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None
