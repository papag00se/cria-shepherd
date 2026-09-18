"""A backticked command ending in a dot is one action, not two.

`_authored_action` enforces the steer author's contract — one imperative sentence — by counting
sentence boundaries. It counted them on the text AFTER `_steer_or_none` had removed markdown
scaffolding, and that removal replaces every backtick with a SPACE. So a directive containing
``go build ./...`` arrives at the check as ``go build ./...  passes``, the dot-then-space reads as a
boundary, and one action is counted as two.

Two units means STRUCTURAL_REFUSAL: the directive is withheld entirely and the caller falls back to
`redirect_canned` — "Choose a DIFFERENT next action and take it now via a tool call."

Measured on cart-billing-go x ternary-bonsai-2 (session 01a0b6aa, turn 6277f59b, 22:57:03). The
reasoner had authored exactly the grounded, specific steer a stalled coder needed:

    Choose one Go decimal package that provides a Decimal type with correct rounding, add it to
    go.mod via `go get`, and confirm `go build ./...` passes before you change cart.go or
    cart_test.go.

It was discarded, and the coder — which had written nothing for twenty minutes — was told to pick
something different. Live log: `loop.steer_multiple_actions units=2` then `loop.redirect`.

The fix masks code spans before the shape check rather than teaching the splitter about dotted runs,
because the defect is destroyed information: any code span ending in a mark hits it, not just
``./...``. These tests pin the real case, the general class, and the behaviour that must NOT change —
a genuinely multi-sentence reply is still refused.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cria.loop import _AuthoredActionState, _authored_action  # noqa: E402

# Verbatim from walkdata/cell2-cart-billing-go/0017-reasoner.response.json.
THE_DISCARDED_STEER = (
    "Choose one Go decimal package that provides a Decimal type with correct rounding, add it to "
    "go.mod via `go get`, and confirm `go build ./...` passes before you change cart.go or "
    "cart_test.go."
)


def test_the_steer_that_was_thrown_away_survives():
    """THE REGRESSION, byte-for-byte. Fails before the fix (STRUCTURAL_REFUSAL), passes after."""
    got = _authored_action(THE_DISCARDED_STEER)
    assert got.state is _AuthoredActionState.ACCEPTED, (
        f"the reasoner's one grounded directive was withheld as {got.state}; the coder would receive "
        f"the canned 'choose a DIFFERENT next action' instead"
    )
    assert got.action and "decimal package" in got.action


def test_any_code_span_ending_in_a_mark_is_one_action():
    """The class, not the instance — `./...` was just the one that got caught."""
    for directive in (
        "Run `pytest tests/.` and report the first failure.",
        "Run `npm run build.` before touching the config.",
        "Check that `go build ./...` passes and then stop.",
        "Execute `rake test` and fix what it names.",
        "Open `lib/shipping/rates.rb` and change the comparison.",
    ):
        got = _authored_action(directive)
        assert got.state is _AuthoredActionState.ACCEPTED, f"withheld as {got.state}: {directive!r}"


def test_a_genuinely_multi_sentence_reply_is_still_refused():
    """The guard must keep doing its job — this is what it exists for."""
    for directive in (
        "Stop. Do that now.",
        "Read the file first. Then rewrite the handler. Then run the tests.",
        "Fix the threshold comparison. Add the express service.",
    ):
        got = _authored_action(directive)
        assert got.state is _AuthoredActionState.STRUCTURAL_REFUSAL, (
            f"accepted a multi-action reply as one unit: {directive!r}"
        )


def test_an_explicit_list_is_still_refused():
    """The list arm reads the RAW text and must be unaffected by the masking."""
    got = _authored_action("Do these:\n- add the gem\n- run the tests\n- update the README")
    assert got.state is _AuthoredActionState.STRUCTURAL_REFUSAL


def test_masking_does_not_leak_into_the_delivered_directive():
    """The mask exists only to COUNT. What reaches the coder keeps the author's words."""
    got = _authored_action(THE_DISCARDED_STEER)
    assert "CODE" not in (got.action or ""), got.action
    assert "go build" in (got.action or "")
