"""Extract a JSON object from a small local model's noisy output.

Local models routinely wrap JSON in ```` ```json ```` fences and emit ``<think>``
reasoning before it — both break a naive ``json.loads``. This is the one place
that noise is dealt with, so every JSON-consuming caller (classifier, later the
completion critic and planner) parses the same way.
"""

from __future__ import annotations

import json
import re
from bisect import bisect_left, bisect_right
from functools import lru_cache

_CLOSE_THINK = re.compile(r"</think(?:ing)?\s*>", re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*", re.IGNORECASE)
_QUOTE = re.compile('"')
_BRACE_OR_QUOTE = re.compile(r'["{}]')
_STRUCTURAL = re.compile(r'["{}\[\]]')


def _mask_json_objects(text: str) -> str:
    """Same-length framing view: parsed literal bytes are payload, never tags.

    Complete objects and tails validated by the existing missing-closers owner
    are protected. Repaired objects are NOT exposed by normal extraction. Reuse
    the balanced-object/first-nonempty parser below; masking ONLY locates wrappers
    and the returned answer always comes from the original bytes.
    """
    parts, end = [], 0
    for _, start, stop in _json_objects(text, include_repairable=True):
        parts.extend((text[end:start], "\0" * (stop - start)))
        end = stop
    parts.append(text[end:])
    return "".join(parts)


def _strip_fences(text: str) -> str:
    parts, end = [], 0
    for match in _FENCE.finditer(_mask_json_objects(text)):
        parts.append(text[end:match.start()])
        end = match.end()
    parts.append(text[end:])
    return "".join(parts)


def strip_reasoning_prefix(text: str) -> str:
    """Drop through the last real closing frame, never through a JSON value.

    A valid private object before an OUTSIDE closing marker is still discarded.
    No verdict is inferred or recovered here; this only recognizes framing.
    """
    end = 0
    for closing in _CLOSE_THINK.finditer(_mask_json_objects(text)):
        end = closing.end()
    return text[end:]


def strip_think(text: str) -> str:
    """Drop through the last real closing frame before selecting an answer.
    An earlier complete object is still private when an OUTSIDE closing marker
    follows it. Also drops a dangling unclosed ``<think>`` and everything after it —
    UNLESS a parseable JSON object follows the tag. A model that forgot to close
    its ``<think>`` before emitting the answer (``<think>deciding…\n{"x":1}``)
    still has a real object in the tail; blindly slicing from ``<think`` to the
    end would silently discard that answer, so we keep the tail when it parses.
    """
    text = strip_reasoning_prefix(text)
    lower = _mask_json_objects(text).lower()
    idx = lower.rfind("<think")
    if idx != -1 and "</think" not in lower[idx:]:
        if next(_json_objects(text[idx:], include_repairable=True), None) is None:
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


def extract_leading_object(text: str) -> dict | None:
    """The object ``text`` IS, not the first object found inside it.

    Like :func:`extract_json_object` — same fences, same ``<think>`` preamble, same trailing prose — with
    one added refusal: when the denoised text OPENS with ``{``, the answer is the object that opens
    there or nothing. A call cut off mid-value never closes its outer object, and a scan for "the first
    complete object" then lands on one nested inside it (a plan step, an ``env`` map) and hands that
    fragment on as the whole arguments. Measured by cutting 300 real argument strings at every byte
    offset (fuzz, wave 12): 1,198 of 63,665 cuts (1.9%) came back as a different, well-formed object.
    Text that opens with prose still yields its first object, as before."""
    if not text:
        return None
    cleaned = denoise(text).lstrip()
    if not cleaned.startswith("{"):
        return _scan_object(cleaned)
    span = _balanced_object(cleaned, 0)
    if span is None:
        return None               # the opening object never closed: nothing nested in it is the answer
    return _scan_object(cleaned)      # it closed: whatever the scan finds first, exactly as before


def denoise(text: str) -> str:
    """The reply with a model's habitual wrappers removed — ``<think>`` preambles and ```` ``` ````
    fences. The ONE place that preprocessing lives, so :func:`extract_json_object` and
    :func:`close_unclosed_object` never disagree about what "the text" is."""
    return _strip_fences(strip_think(text))


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
        obj = _repair_unclosed_object(cleaned, start)
        if obj is not None:
            return obj
        start = cleaned.find("{", start + 1)
    return None


def _repair_unclosed_object(s: str, start: int) -> dict | None:
    """The existing missing-closers check, without wrapper preprocessing/recursion."""
    closers = _unclosed_tail(s, start)
    if closers:
        try:
            obj = loads(s[start:] + closers)
        except json.JSONDecodeError:
            return None
        if isinstance(obj, dict):
            return obj
    return None


def _repairable_tail_span(s: str, start: int):
    """Original bytes whose only defect is missing closers, possibly outer fences.

    The real repair owner validates each candidate. A fence inside a value ends
    mid-string, so it cannot create a valid candidate or steal literal bytes.
    No repaired object is exposed by normal extraction; these spans protect data
    during framing only. Verdict callers still reject positive/mid-string/length
    recovery independently.
    """
    obj = _repair_unclosed_object(s, start)
    if obj is not None:
        return obj, len(s)
    for end in _scan(s).trailing_fence_starts(start):
        obj = _repair_unclosed_object(s[:end], start)
        if obj is not None:
            return obj, end
    return None


def _unclosed_tail(s: str, start: int) -> str:
    """The closers that would balance the object opening at ``start``, or ``""``.

    ``""`` means there is nothing to repair here — the span already closes (that is
    :func:`extract_json_object`'s job), or it ends inside a string, or ``start`` opens nothing."""
    if s[start:start + 1] != "{":
        return _unclosed_tail_from(s, start)
    return _scan(s).unclosed(start)


def _unclosed_tail_from(s: str, start: int) -> str:
    """The definition of :func:`_unclosed_tail`, one scan from ``start`` (what :class:`_Scan` memoizes)."""
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


def _json_objects(s: str, *, include_repairable: bool = False):
    """Object spans using the one parser; repairable tails are framing-only opt-in."""
    start = s.find("{")
    while start != -1:
        span = _balanced_object(s, start)
        if span is not None:
            try:
                obj = loads(span)
            except json.JSONDecodeError:
                obj = None
            if isinstance(obj, dict):
                stop = start + len(span)
                yield obj, start, stop
                start = s.find("{", stop)
                continue
        repaired = _repairable_tail_span(s, start)
        if repaired is not None:
            obj, stop = repaired
            if include_repairable:
                yield obj, start, stop
            # Normal extraction must skip the WHOLE repairable outer candidate,
            # not promote a nested example into a complete/positive answer.
            start = s.find("{", stop)
            continue
        start = s.find("{", start + 1)


def _scan_object(s: str) -> dict | None:
    """First brace-balanced span in ``s`` that parses to a ``dict``, else ``None``."""
    return next((obj for obj, _, _ in _json_objects(s)), None)


def _balanced_object(s: str, start: int) -> str | None:
    if s[start:start + 1] != "{":
        return _balanced_object_from(s, start)
    return _scan(s).balanced(start)


def _balanced_object_from(s: str, start: int) -> str | None:
    """The definition of :func:`_balanced_object`, one scan from ``start`` (what :class:`_Scan` memoizes)."""
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


@lru_cache(maxsize=4)
def _scan(s: str) -> "_Scan":
    return _Scan(s)


class _Scan:
    """What every ``{`` of ONE string answers, without rescanning the string for each ``{``.

    :func:`_json_objects` asks, for each ``{`` in turn, where its object closes and what closers its
    tail lacks. Each answer used to be its own scan to the end of the text, so a cut write_file with
    N unclosed braces cost N full scans: a 40,000-character cut argument took 11 seconds, a real
    157,000-character one 6.5 (wave 12 corpus walk), in the response path of every cut call. Both
    questions are decided by a string/escape machine that depends only on WHERE the scan starts, so
    one left-to-right run answers every ``{`` it sees outside a string — nesting is just a stack —
    and a ``{`` that run saw INSIDE a string (a different reading of the text) starts a run of its
    own. Each answer is exactly what the one-scan definitions (:func:`_balanced_object_from`,
    :func:`_unclosed_tail_from`) return; a randomized comparison in the tests holds them equal."""

    def __init__(self, s: str):
        self.s = s
        self._end: dict[int, int | None] = {}
        self._closers: dict[int, str] = {}
        self._closing: list[int] | None = None
        self._fences: list | None = None
        self._blank_tail_from: int | None = None

    def balanced(self, start: int) -> str | None:
        if start not in self._end:
            self._run_braces(start)
        end = self._end[start]
        return None if end is None else self.s[start:end + 1]

    def unclosed(self, start: int) -> str:
        if start not in self._closers:
            self._run_closers(start)
        return self._closers[start]

    def _string_end(self, quote: int) -> int:
        """Index of the quote that closes the string opened at ``quote``, or -1 when it never closes.

        Inside a string a backslash escapes the next character, so a quote closes the string exactly
        when an EVEN run of backslashes precedes it — a fact about the text, not about where the
        string opened. One pass finds them all; a lookup then jumps a whole string (a code file
        written as `\\"`-escaped text is one string to the end, however many braces it holds)."""
        if self._closing is None:
            s, closing = self.s, []
            for m in _QUOTE.finditer(s):
                j = k = m.start()
                while k and s[k - 1] == "\\":
                    k -= 1                      # each quote walks back over its OWN run of backslashes
                if (j - k) % 2 == 0:
                    closing.append(j)
            self._closing = closing
        k = bisect_right(self._closing, quote)
        return self._closing[k] if k < len(self._closing) else -1

    def _run_braces(self, start: int) -> None:
        s, ends, stack = self.s, self._end, []
        i = start
        while (m := _BRACE_OR_QUOTE.search(s, i)) is not None:
            j = m.start()
            c = s[j]
            if c == '"':
                j = self._string_end(j)
                if j < 0:
                    break
            elif c == "{":
                stack.append(j)
            elif stack:
                ends[stack.pop()] = j
            i = j + 1
        for pos in stack:
            ends[pos] = None

    def _run_closers(self, start: int) -> None:
        s, out, stack = self.s, self._closers, []
        i, in_str = start, False
        while (m := _STRUCTURAL.search(s, i)) is not None:
            j = m.start()
            c = s[j]
            if c == '"':
                j = self._string_end(j)
                if j < 0:
                    in_str = True
                    break
            elif c in "{[":
                stack.append((j, "}" if c == "{" else "]"))
            elif stack:
                if stack[-1][1] != c:      # mismatched nesting: every open object above is refused
                    for pos, _ in stack:
                        out[pos] = ""
                    stack = []
                else:
                    out[stack.pop()[0]] = ""   # it closed on its own
            i = j + 1
        closers = ""
        for pos, closer in reversed(stack):
            closers += closer
            out[pos] = "" if in_str else closers

    def trailing_fence_starts(self, start: int) -> list[int]:
        """Starts of the fences at/after ``start`` after which nothing but fences and whitespace remains."""
        if self._fences is None:
            self._fences = [m.start() for m in _FENCE.finditer(self.s)]
            k = len(self._fences)
            while k and not _FENCE.sub("", self.s[self._fences[k - 1]:]).strip():
                k -= 1
            self._blank_tail_from = k
        lo = max(bisect_left(self._fences, start), self._blank_tail_from)
        return self._fences[lo:]
