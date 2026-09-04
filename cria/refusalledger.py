"""A session-scoped ledger of dependency coordinates/packages the coder's OWN toolchain REFUSED.

WHY THIS EXISTS. A resolver's "this does not resolve" is the strongest ground truth cria can hold
about a name — the coder ran the tool and the tool refused (#10). But that fact does not survive:
walked on cart-billing-go x nemotron-elastic 1788241229 call 0095, the compactor folded the history
and every `unknown revision v0.5.0` / `Repository not found` line vanished, so at 0096 the
satisfaction seat ruled "No further modifications are needed" over the very pin the tools had
refused. And walked on feed-pipeline-java x nemotron-elastic 1788243086 (0071→0073), cria's own
steer ordered `import com.opencsv.exception.CSVParseException` while `package com.opencsv.exception
does not exist` sat in the seat's prompt. The existing prescribes-guard cannot catch either: its
`_shared_symbols` SKIPS any token with a `/` ("a path is not a symbol") so a module coordinate is
invisible to it, and it strips `*Exception` names as "what a checker reports, not rejects".

So cria REMEMBERS the refused coordinate the turn it is observed, in a set that persists across
compaction exactly like `fetched_pages` does, and a steer that PRESCRIBES a remembered-refused
coordinate is withheld (the caller runs the same reasoned prescribe-vs-quote question the symbol
guard uses — a "remove X" or "supply the missing X" steer is fine; "add/use the refused X" is not).

SCOPE — COORDINATES, PACKAGES, MODULES; never bare symbols or exception classes (those are the
symbol guard's job, and an exception name is ambiguous — a checker rejecting it and a program
throwing it read alike). A coordinate is unambiguous: the resolver could not fetch it.

#20, stated rather than hidden: the patterns below are one resolver's refusal wording per ecosystem
— the analog of `probeparse.split_diag`'s handful of compiler location formats, and bounded the same
way. A shape this list misses simply does not enter the ledger (the guard then does not fire — it
fails toward delivering the steer, today's behaviour), and a shape it over-captures becomes a
TRIGGER for one reasoner question, never a withhold on its own. Neither direction states a false
fact: a ledger entry means only "this session ran a tool and the tool refused this name", which is
true whatever the cause (a real 404, a typo'd coordinate, or a transient/offline miss).
"""
from __future__ import annotations

import re

# Each pattern captures the REFUSED coordinate/package/module. Grouped by ecosystem, and every one
# is a resolver/compiler saying it could not provide the named thing.
# Go's manifest parser reports an invalid requirement as two separated fields rather than the
# ordinary contiguous ``module@version`` coordinate.  Join those exact fields when gathering the
# fact; the ledger still stores the coordinate the resolver actually refused, never a bare-module
# inference.
_GO_INVALID_VERSION = re.compile(
    r'require ([\w./\-]+): version "([^"]+)" invalid:[^\n]*?unknown revision')

_REFUSAL = (
    # Go
    re.compile(r"no required module provides package ([^\s;)]+)"),
    re.compile(r"cannot find module providing package ([^\s;)]+)"),
    re.compile(r"repository '([^']+)' not found"),
    re.compile(r"([\w./\-]+@v?[\w.\-]+):[^\n]*?unknown revision"),   # module@version
    # Maven / Gradle / javac
    re.compile(r"Could not find artifact ([\w.\-]+:[\w.\-:]+)"),
    re.compile(r"([\w.\-]+:[\w.\-]+:(?:jar|pom|aar):[\w.\-]+) was not found"),
    re.compile(r"package ([\w.]+) does not exist"),
    # npm / yarn
    re.compile(r"404 Not Found[^\n]*?['\"]([@\w./\-]+)['\"]"),
    re.compile(r"No matching version found for ([@\w./\-]+)"),
    # cargo
    re.compile(r"no matching package (?:named )?`([^`]+)`"),
    re.compile(r"failed to select a version for `([^`]+)`"),
    # pip
    re.compile(r"No matching distribution found for ([\w.\-\[\]]+)"),
    re.compile(r"Could not find a version that satisfies the requirement ([\w.\-\[\]]+)"),
    # gem
    re.compile(r"Could not find gem '([^']+)'"),
)

# A captured token is kept only if it LOOKS like a coordinate/package/module — carries a `.`, `/`,
# `:` or `@` — and is specific enough (>4 chars) that a directive naming it is naming that thing and
# not colliding with an ordinary word. A bare version like `v0.5.0` qualifies (it has dots) and is
# useful, but only ever as a trigger for the reasoned question the caller asks.
def _coordinate_like(tok: str) -> bool:
    return len(tok) > 4 and bool(re.search(r"[./:@]", tok))


def _normalize(tok: str) -> str:
    """A refusal may name a coordinate as a URL — Go prints `repository
    'https://github.com/arborize/decimal/' not found` — while a steer that re-blesses it names the
    bare host/path (`github.com/arborize/decimal`). Walked on cart-billing-go x nemotron-elastic
    1788413612 (steers 0049/0058/0070/0082/0083/0107): the URL-form ledger entry never matched the
    bare-path steer under substring compare, so every re-bless of the twice-refused module shipped.
    Strip a URL scheme, a trailing slash, and a trailing `.git` so the two forms compare equal.
    Non-URL coordinates (maven `g:a:v`, npm `@scope/x`, `module@version`) carry no scheme and pass
    through byte-identical."""
    tok = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", tok)   # scheme://
    tok = tok.rstrip("/")
    if tok.endswith(".git"):
        tok = tok[:-4]
    return tok


def refused_names(text: str) -> set[str]:
    """Every coordinate/package/module the given tool-output text shows a resolver REFUSING."""
    out: set[str] = set()
    for m in _GO_INVALID_VERSION.finditer(text or ""):
        tok = _normalize(f"{m.group(1)}@{m.group(2)}")
        if _coordinate_like(tok):
            out.add(tok)
    for pat in _REFUSAL:
        for m in pat.finditer(text or ""):
            tok = _normalize((m.group(1) or "").strip().strip("'\"`.,;:"))
            if _coordinate_like(tok):
                out.add(tok)
    return out


def scan_messages(messages) -> set[str]:
    """Refused coordinates across all TOOL results in a message list — ground truth only (#10): the
    coder's own executed commands, never the model's prose or cria's own injections."""
    found: set[str] = set()
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        if m.get("role") != "tool" and m.get("type") != "function_call_output":
            continue
        body = m.get("content") if m.get("content") is not None else m.get("output")
        if isinstance(body, str):
            found |= refused_names(body)
    return found


def prescribed(directive: str, ledger) -> str | None:
    """The longest remembered-refused coordinate the directive NAMES (substring), or None. Longest
    first so a specific `com.opencsv.exception` is reported over a bare version it contains. Only a
    TRIGGER — the caller decides prescribe-vs-quote with a reasoner."""
    if not directive or not ledger:
        return None
    for tok in sorted(ledger, key=len, reverse=True):
        if tok in directive:
            return tok
    return None
