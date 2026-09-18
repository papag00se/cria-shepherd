"""`on_target` answers one question; cria was using it to settle two.

The search supervisor is asked whether a query hunts the right THING. That verdict was also deciding
whether the query was a usable search STRING — a different question nobody asked. A spiral fragment
can be on-target and unusable at the same time, which is exactly what happened.

Walked on cart-billing-go x ternary-bonsai-2 (session 01a0b6aa, call 0005). A rumination abort had
just fired; the coder regenerated the spiral into its search argument and sent, verbatim:

    go.mod decimal module golang.org/x/exp math/bits? no — "github.com/bsb" or
    "github.com/joelschaefer"? Actually: which Go library provides a Decimal type for money, e.g.
    github.com/shopspring/supercharge? Let me search properly.

The judge saw that text, ruled `on_target: true` — correctly; the topic IS right — and handed back
"Go third-party Decimal type for money calculations go.mod". cria dropped it, because an on-target
query is never rewritten. The spiral went to the network, returned no results, and the empty result
then fed the re-hunt guard and the phantom spill file.

`_usable_query` already rejects the sent query and accepts the dropped recommendation. cria owned the
test that tells the two questions apart and only ever pointed it at the judge's answer, never at the
coder's own query.

NARROW BY CONSTRUCTION. Rewriting on-target queries in general is a known footgun — 47% of all
searches were being rewritten, into `web_search('…')` wrappers and instruction sentences used
verbatim — which is why the URL-only rule exists. These tests pin BOTH sides: an unusable query is
replaced, and a usable on-target query is still left completely alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json  # noqa: E402

from cria import bodykeys, loop  # noqa: E402
from cria.loop import _usable_query  # noqa: E402

# Verbatim from walkdata/cell2-cart-billing-go/0005-coder-s1-focus1.response.json.
THE_SPIRAL_QUERY = (
    'go.mod decimal module golang.org/x/exp math/bits? no — "github.com/bsb" or '
    '"github.com/joelschaefer"? Actually: which Go library provides a Decimal type for money, '
    'e.g. github.com/shopspring/supercharge? Let me search properly.'
)
# Verbatim from walkdata/cell2-cart-billing-go/0006-reasoner.response.json.
THE_DROPPED_RECOMMENDATION = "Go third-party Decimal type for money calculations go.mod"


def test_the_spiral_query_does_not_pass_crias_own_shape_test():
    """The premise of the fix: cria can already tell this is not a query."""
    assert not _usable_query(THE_SPIRAL_QUERY), (
        "if this ever starts passing, the gate below silently stops firing"
    )


def test_the_recommendation_cria_dropped_was_usable():
    """The other half: there WAS something better to use."""
    assert _usable_query(THE_DROPPED_RECOMMENDATION) == THE_DROPPED_RECOMMENDATION


def test_an_ordinary_query_is_still_usable_and_so_is_left_alone():
    """The footgun guard. These must keep passing the shape test, because a query that passes is
    never rewritten — that is what keeps the 47%-rewrite regression from coming back."""
    for q in (
        "Go decimal library for money",
        "ruby gem eu membership country",
        "shopspring/decimal Round half up",
        "api.handle.me openapi.json",
        "python requests retry backoff",
    ):
        assert _usable_query(q) == q, f"an ordinary query stopped being usable: {q!r}"


def _coder_turn(query: str) -> dict:
    return {"choices": [{"message": {"tool_calls": [{
        "id": "c1", "type": "function",
        "function": {"name": "web_search", "arguments": json.dumps({"query": query})},
    }]}}]}


def _query_of(turn: dict) -> str:
    tc = ((turn.get("choices") or [{}])[0].get("message") or {}).get("tool_calls") or []
    return json.loads(tc[0]["function"]["arguments"])["query"] if tc else ""


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, *a, **k):
        self.events.append(k)


def _run(query: str, on_target: bool, rec: str):
    """Drive the REAL `guard_search_query` with a pre-cached verdict, rather than re-implementing its
    condition in the test. A mirrored condition passes whatever the code does, including nothing — my
    first version of this file did exactly that and hid the fact that the gate's non-URL branch
    SURFACES rather than substitutes."""
    sess = loop.GuardState()
    sess.query_verdicts = {query: (on_target, rec)}   # pre-cached: no reasoner call is made
    body = {"messages": [{"role": "user", "content": "fix the rounding bug in cart.go"}], "tools": []}
    rlog = _Rlog()
    return loop.guard_search_query(sess, _coder_turn(query), body, None, None, rlog), rlog


def test_the_walked_case_the_better_query_reaches_the_coder_as_a_note():
    """THE REGRESSION, through the real gate. Before the change this returned the coder's turn with
    nothing attached, because `on_target` was true — so the judge's usable recommendation was
    computed and discarded.

    SURFACED, NOT SUBSTITUTED. The non-URL branch deliberately notes rather than rewrites: "cria
    never SUBSTITUTES its own action for the coder's: surface the fact, steer, and let the coder
    act" (doctrine #2's corollary, measured on nemotron-elastic/rust 0006). The coder's own search
    still runs — this only stops cria from silently throwing away the better string it already had.
    """
    out, rlog = _run(THE_SPIRAL_QUERY, on_target=True, rec=THE_DROPPED_RECOMMENDATION)
    notes = out.get(bodykeys.NOTES) or []
    assert notes, "the judge's usable recommendation was dropped again"
    assert THE_DROPPED_RECOMMENDATION in notes[0]
    assert any(e.get("action") == "noted" for e in rlog.events), rlog.events
    # the coder's own query is untouched on the wire
    assert _query_of(out) == THE_SPIRAL_QUERY


def test_an_ordinary_on_target_query_gets_no_note_at_all():
    """The footgun guard, through the real gate: a query that passes the shape test is left alone,
    silently. This is what keeps the 47%-rewrite regression from coming back, and what keeps the
    'silence over noise' rule for the overwhelmingly common case."""
    out, rlog = _run("Go decimal library for money", on_target=True, rec=THE_DROPPED_RECOMMENDATION)
    assert not (out.get(bodykeys.NOTES) or []), out.get(bodykeys.NOTES)
    assert not rlog.events


def test_an_unusable_query_with_no_recommendation_is_left_alone():
    """cria speaks only when it has something real to offer."""
    out, rlog = _run(THE_SPIRAL_QUERY, on_target=True, rec="")
    assert not (out.get(bodykeys.NOTES) or [])
    assert _query_of(out) == THE_SPIRAL_QUERY
