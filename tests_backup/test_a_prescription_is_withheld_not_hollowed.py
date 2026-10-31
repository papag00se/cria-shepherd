"""A PRESCRIBED line is withheld whole — never hollowed, never restated.

Walked on `rust-toml-cli x ternary-bonsai`, 2026-08-19 call 0015. The steer author wrote three
numbered fixes, each naming code it had invented. `_strip_invented_code` replaced the code and
shipped the rest:

    **Line 12**: [code removed — written by this supervisor…] fails because TOML tables use
    `String` keys, not `&str`. Change to [code removed — written by this supervisor…].

"Change X to Y" with both X and Y deleted. And the strip kept the half that does the damage: the
cause — *"because TOML tables use `String` keys"* — is wrong, and by the steer prompt's own
measurement an unverified cause was wrong in twenty-four cases out of twenty-four.

THE DISTINCTION IS QUOTED vs PRESCRIBED, and the invented-span count measures it. Code the author
READ counts zero, which is the case the 2026-08-04 ruling protects and which carried the ladder
passes. Code the author INVENTED is what the count sees, and a sentence built around invented code
cannot survive losing it.

What replaced the strip on 2026-08-19 was a blind rewriter (`steer_restate`) that said the directive
again "without the code". Re-measured against removal on 2026-10-27 (principle 1): a rewriter that
cannot check anything still composes a new sentence around what the code was FOR, and 4 of the 5
delivered restatements in a 102-steer census invented a requirement or drifted the purpose (see
tests/test_a_dictated_steer_is_withheld_not_restated.py for the run07 incident). It was removed. A
prescription now ends where every other refused steer ends: withheld, with the caller's own floor.
"""

import unittest

from cria import loop
from tests.test_system1_integration import FakeSystem1


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


# The real directive, verbatim from call 0015.
PRESCRIPTION = (
    "Read lines 12, 84, 103, and 157 of `src/main.rs` and apply these three targeted fixes:\n\n"
    "1. **Line 12**: `map.get(key)` fails because TOML tables use `String` keys, not `&str`. "
    "Change to `map.get(&key.to_string())`.\n\n"
    "2. **Lines 84, 103, 157**: The `toml` crate v0.8 uses `I64`, not `Int`. "
    "Replace `toml::Value::Int(ref i)` with `toml::Value::I64(ref i)`.")
# What the compiler actually showed: the coder's own line, not the replacement.
OBSERVED = [{"role": "tool", "tool_call_id": "c1",
             "content": "src/main.rs:12: error[E0308]: mismatched types\n   map.get(key)"}]


class AnInventedPrescriptionIsWithheldWholeTests(unittest.TestCase):
    def test_legacy_reasoner_path_withholds_and_asks_nothing_else(self):
        asked = []

        def ask(system, user=""):
            asked.append(system)
            return "DICTATES"

        rlog = _Rlog()
        steer, why = loop._vet_steer(PRESCRIPTION, "evidence", rlog, ask, None, OBSERVED, None)
        self.assertEqual((steer, why), (None, "dictated_code"))
        self.assertEqual(len(asked), 1, "one ruling on the directive; no rewrite is requested")
        refused = [f for k, f in rlog.events if k == "loop.steer_dictated_code"]
        self.assertEqual(refused[-1]["delivered"], False)
        self.assertGreater(refused[-1]["invented"], 0)

    def test_native_classifier_path_withholds_and_asks_no_reasoner(self):
        asked = []
        fake = FakeSystem1(dictation="DICTATES")
        steer, why = loop._vet_steer(PRESCRIPTION, "evidence", _Rlog(),
                                     lambda s, u="": asked.append(s) or "unused", None, OBSERVED, None,
                                     system1=fake)
        self.assertEqual((steer, why), (None, "dictated_code"))
        self.assertEqual(asked, [])
        self.assertEqual(fake.texts("dictation"), [PRESCRIPTION])

    def test_nothing_hollowed_ever_reaches_the_coder(self):
        """The 0015 delivery, checked at the delivery seam: no marker debris, no half sentence."""
        out = loop._grounded_steer_or_none(PRESCRIPTION, "evidence", _Rlog(),
                                           ask=lambda s, u="": "DICTATES", messages=OBSERVED)
        self.assertIsNone(out)

    def test_no_reasoner_withholds_a_code_shaped_prescription_too(self):
        """With no judge the pre-filter's verdict stands, and invented code is still withheld."""
        steer, why = loop._vet_steer(PRESCRIPTION, "evidence", _Rlog(), None, None, OBSERVED, None)
        self.assertEqual((steer, why), (None, "dictated_code"))


class QuotedCodeStillSurvivesUntouchedTests(unittest.TestCase):
    """The 2026-08-04 ruling, unchanged on the legacy path: a steer quoting the coder's OWN failing
    line ships whole. That was 66 of the 100 dictated steers in the captures."""

    def test_a_quoted_line_counts_nothing_invented_and_ships(self):
        directive = "Your line `map.get(key)` is what the compiler rejects. Read src/main.rs:12."
        self.assertEqual(loop._invented_code_spans(directive, loop._observed_code(OBSERVED)), 0)
        out = loop._grounded_steer_or_none(directive, "evidence", _Rlog(),
                                           ask=lambda s, u="": "DICTATES", messages=OBSERVED)
        self.assertEqual(out, directive)

    def test_an_invented_line_is_counted(self):
        self.assertGreater(loop._invented_code_spans(
            "Change to `map.get(&key.to_string())`.", "map.get(key) fails here"), 0)


if __name__ == "__main__":
    unittest.main()
