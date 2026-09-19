"""A rule that only says what is forbidden leaves a cautious model with no legal move.

`seeded_test_rule` is injected with every `⟦ctx:checks⟧` block. It correctly scopes what is binding —
the repo's own assertions, and "an exact input, expected output, or acceptance condition NAMED BY THE
USER'S TASK". It said nothing about the complement, and a 9B coder read the silence as coverage.

Walked on shipping-rates-rb x ternary-bonsai-2 (session 01a0b68a, call 0026). The task names `GB`,
EU members, and "all others" for `zone_for`; it says nothing about an INVALID code. The coder spent
29,651 characters deciding between two defensible behaviours for `zone_for("XX")` — "Option A is
cleaner… But wait, the task says 'all others returns international'… Let me reconsider… Actually, you
know what, let me reconsider once more" — and shipped neither. By the rule's own scoping that case
was never binding.

Replayed with the added sentence, same captured body otherwise: reasoning 29,651 → 13,642 characters
and the reconsider cycle absent. ONE sample; the drop may be variance, and it did not by itself
produce a write (the coder went on to legitimate environment work). It is landed for the waste it
removes on a question that has no answer to find, not as a fix for the run.

These tests pin the CONTRACT — the rule must state both halves — not the wording.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cria import prompts  # noqa: E402

RULE = prompts.load("seeded_test_rule")


def test_the_rule_still_forbids_weakening_a_seeded_assertion():
    """The half that prevents the documented real failure is untouched."""
    assert "not yours to change so the implementation passes" in RULE
    assert "Weakening or deleting an assertion for any other reason is not a fix." in RULE


def test_the_rule_also_states_what_the_coder_MAY_decide():
    """The missing complement. Fails before the addition."""
    assert re.search(r"does NOT name is yours to decide", RULE), (
        "the rule lists obligations with no statement of what is free; a case the task leaves "
        "unspecified reads as possibly-binding and the coder stalls on it"
    )


def test_the_permission_is_scoped_to_UNNAMED_cases_only():
    """It must not read as licence to change something the task DID name — that would reopen the
    failure the first half exists to prevent."""
    sentence = next(s for s in RULE.split(". ") if "yours to decide" in s)
    assert "does NOT name" in sentence, sentence
    # and it must not promise anything about how the work will be scored (#5b: cria would be
    # asserting a fact about the evaluation regime it cannot back)
    for forbidden in ("will not be penalised", "no hidden test", "won't be marked", "grader"):
        assert forbidden not in RULE.lower()


def test_the_permission_names_a_tiebreak_rather_than_a_coin_flip():
    """'Decide' without a criterion is its own deadlock."""
    assert "most consistent with what it does say" in RULE
