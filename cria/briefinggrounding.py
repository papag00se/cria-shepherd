"""A briefing's concrete figures, checked by lookup in the evidence the briefing was written from.

The whole-briefing fidelity verdict (one word over a transcript-sized prompt) carried no claim-level
signal: replayed on real briefings it passed a correct briefing and a briefing with a fabricated
claim at nearly the same rate (docs/open-threads.md, 2026-11-02). The typed lenses (`filepresence`)
settle file presence, file changes, exact sizes of listed files and build state; this one settles the
rest of the NUMERIC claims the same way, with no model in it at all (principle 1: deterministic code
gathers, only a judgment is asked of a model, and none is needed here).

Code gathers the figures the briefing states — a number with a measure unit ("4,812 B", "47 tests",
"0.341s"), a three-part version ("1.11.0"), a URL host or ``host:port`` — and looks each one up,
literally, in the transcript / survey / check evidence / task text the writer was given. A figure
that occurs nowhere in all of it was not read from anything: it is refused.

It abstains (says nothing, never refuses) wherever a figure may legitimately not appear verbatim:
approximated, bounded or ranged ("~0.37 s", "at least 4x", "0.18-0.25 s", "< 73 ms"), a
target or requirement, arithmetic over other figures ("40000 + 1"), a unit it does not know, and a
rounded decimal whose longer form is in the evidence. It never reads a figure the briefing words as
a derived unit (KB/MB/GB, %, a multiplier). A figure that exists in the evidence but belongs to
something else ("REVIEW.md (235 B)" where 235 B was another file's) is the size lens's question
against the survey, not this one's: this lens speaks only about figures with no source at all.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Measures a figure is a concrete OBSERVATION in. KB/MB/%/multipliers are deliberately absent: they are
# derived from the observation (1211931 B -> "1.2 MB"), so the literal never has to occur.
_UNIT = (r"(?:B|bytes?|ms|s|secs?|seconds?|rows?|lines?|tests?|files?|records?|columns?|fields?|errors?|"
         r"failures?|warnings?|passed|failed|threads?)")
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_QUANTITY = re.compile(rf"(?<![\w.,])({_NUM})\s*({_UNIT})(?![\w-])")
_VERSION = re.compile(r"(?<![\w.])(\d+\.\d+\.\d+)(?![\w]|\.\w)")
_HOST = re.compile(r"(?<![\w.])(?:https?://([A-Za-z0-9.-]+\.[A-Za-z]{2,}|localhost|\d{1,3}(?:\.\d{1,3}){3})(?::\d+)?"
                   r"|(localhost:\d+|\d{1,3}(?:\.\d{1,3}){3}:\d+))")
# A figure the briefing hedges, bounds, ranges, targets or derives is not a literal observation.
_HEDGE = re.compile(
    r"(?:[~≈<>≤≥+=]|[0-9]\s*[-–—])\s*$|\b(?:about|roughly|approx\w*|around|nearly|almost|over|under|more than|"
    r"less than|at least|at most|up to|some|estimated|target\w*|need\w*|require\w*|within|below|above|plus|"
    r"minus|vs\.?|versus)\s+$", re.I)
_DERIVED_AFTER = re.compile(r"\s*(?:(?:[-–—+×]|\bplus\b|\bminus\b)\s*\d|\([^)]{0,40}\+\s*\d)")

_EVIDENCE_NUMBER = re.compile(rf"(?<![A-Za-z_\d.])(?:{_NUM})|(?<=m)(?:{_NUM})")


def _dec(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", "")).normalize()
    except InvalidOperation:  # pragma: no cover - the patterns only hand over digits
        return None


def _evidence_numbers(text: str) -> tuple[set[Decimal], list[str]]:
    """Every number the evidence states (as a value), and its decimals as written (for rounded matches)."""
    values: set[Decimal] = set()
    decimals: list[str] = []
    for m in _EVIDENCE_NUMBER.finditer(text):
        raw = m.group(0).replace(",", "")
        value = _dec(raw)
        if value is not None:
            values.add(value)
        if "." in raw:
            decimals.append(raw)
    return values, decimals


def _grounded_number(raw: str, unit: str, values: set[Decimal], decimals: list[str]) -> bool:
    value = _dec(raw)
    if value is None or value in values:
        return True
    if "." in raw:
        # A rounded or truncated figure: some evidence decimal reads the same to the briefing's precision.
        places = len(raw.replace(",", "").split(".")[1])
        for longer in decimals:
            head, _, tail = longer.partition(".")
            if len(tail) > places and (longer[:len(head) + 1 + places] == raw.replace(",", "")
                                       or _dec(longer).quantize(Decimal(1).scaleb(-places)) == value):
                return True
    if re.fullmatch(r"(?:ms|s|secs?|seconds?)", unit):
        # The same duration in the other unit: 291 ms and 0.291 s are one observation.
        return (value / 1000 in values or value * 1000 in values or
                any(_dec(d) is not None and _dec(d).scaleb(3) == value for d in decimals))
    return False


def _hedged(briefing: str, m: re.Match) -> bool:
    before = briefing[max(0, m.start() - 24):m.start()]
    return bool(_HEDGE.search(before) or _DERIVED_AFTER.match(briefing, m.end()))


def ungrounded(briefing: str, evidence: list[str]) -> list[str]:
    """Figures ``briefing`` states literally that occur nowhere in ``evidence``, as the briefing words them.

    Empty when the briefing states no such figure OR when there is no evidence to look in (no evidence
    settles nothing: a lens may only speak about what it reached)."""
    haystack = "\n".join(evidence)
    if not haystack.strip():
        return []
    values, decimals = _evidence_numbers(haystack)
    lowered = haystack.lower()
    found: list[str] = []
    for m in _QUANTITY.finditer(briefing):
        if not _hedged(briefing, m) and not _grounded_number(m.group(1), m.group(2).lower(), values, decimals):
            found.append(m.group(0))
    for m in _VERSION.finditer(briefing):
        if m.group(1).lower() not in lowered and not _hedged(briefing, m):
            found.append(m.group(1))
    for m in _HOST.finditer(briefing):
        host = (m.group(1) or m.group(2) or "").lower()
        if host and host not in lowered:
            found.append(host)
    return list(dict.fromkeys(found))
