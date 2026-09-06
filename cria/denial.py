"""A tool call cria REFUSED — marked where the refusal is AUTHORED, and rendered so a judge can
tell the CALL did not happen.

THE DEFECT THIS EXISTS FOR. cria lowers a refused synthetic tool call to a ``printf`` of its own
refusal text, so the harness hands that text back as the tool's result. ``loop._work_log`` then
renders it as ``  -> <refusal text>``, byte-identical to a real result, and ``prompts/verify.txt``
tells the step critic in cria's own words that "each ``-> ...`` line is what it returned". So the
judge is told cria's sentence is the coder's tool's answer — cria stating a false fact about the
world in its own voice (principle 5b). Measured 2026-08-03 over the 127 captured sessions: 216 of
537 step-critic prompts carrying an action log render at least one refusal that way, and 140
of 370 satisfaction prompts (38%).

WHERE THE MARK GOES, AND WHY IT IS NOT A MATCHER. The mark is applied at the site that DECIDES to
refuse — ``writeproxy._refusal_command`` (the one owner of a lowered refusal), the two read-size
guards, ``webfetch._guard_msg`` for its repeat-gate keys, and the search-read denial in
``loop._judge_search_reads``. Nothing downstream ever asks what a result SAYS. A wording matcher
would be the same class of mistake this fixes: it would fire on a page that quotes the refusal and
miss the next refusal anyone writes. The sibling ``⟦ctx:search⟧`` marker did exactly this and said
why; this generalizes it, and that marker is gone (one owner, not two).

WHAT THE LABEL MAY SAY — the whole rule, learned by getting it wrong. The label names the CALL and
nothing else: *this call did not run*. It must say NOTHING about whether the text beneath it is
real. A first attempt labelled the body "not content the tool returned" and landed on top of a
spilled document's REAL endpoint list and response field names — the ``[API endpoints (33): …]``
block ``selfcompact`` anchors verbatim precisely because it IS the API's real answer, carried by
the ``fetch_repeat_spilled`` refusal. That told the judge to discard its only real evidence: a
bigger false fact than the one being fixed. Everything under a refusal may be genuine ground truth
and often is — a repeat-fetch refusal carries the document's outline, a spill-read steer carries
the file's real routes. cria may say the call did not run, because it knows that; it may not say
what the words below are worth.

DIRECTION (#13). A label is disclosure only. It adds a fact to a judge's evidence and removes
nothing, so no step can advance and no task can be approved that would not have been before; the
only ruling it can move is from "the tool proved this" toward "the tool never ran", which is the
safe direction. Nothing here parses, gates, or drops anything.
"""

from __future__ import annotations

# ⟦ctx:…⟧ namespace, never the proper noun (#17). It rides in the refusal text the coder reads —
# the same channel and the same shape as every other context marker in that stream.
DENIED_MARKER = "⟦ctx:denied⟧"


def mark(text: str) -> str:
    """``text`` prefixed with :data:`DENIED_MARKER` — idempotent, so a refusal that is composed of
    two already-marked fragments, or re-marked on a later pass, still carries exactly one.

    Empty text is left empty: a refusal with nothing to say is not a refusal, and a bare marker
    would be a claim with no content behind it."""
    if not text or DENIED_MARKER in text:
        return text
    return f"{DENIED_MARKER} {text}"


def is_denied(text: str) -> bool:
    """True when this tool result is cria's answer to a call that never ran."""
    return bool(text) and DENIED_MARKER in text
