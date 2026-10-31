"""cria's dictated-code guard was blind to Ruby, and a steer it could not see broke a passing test.

`shipping-rates-rb x ternary-bonsai` 1787111689. The `[REDIRECT]` steer shipped two paste-ready
lines:

    # Instead of: zone = zone_or_code.is_a?(String) && … ? zone_for(zone_or_code) : zone_or_code
    # Use this:   zone = ZONE_BASE.key?(zone_or_code) ? zone_or_code : zone_for(zone_or_code)

The model adopted the second one verbatim. Four calls later `test_unknown_zone_rejected` — a **repo**
test that had been green — went red and stayed red: `"moon"` is not a `ZONE_BASE` key, so it falls
through to `zone_for` and comes back `"international"` instead of raising `ArgumentError`. One of the
run's three final failures, authored by cria.

WHY NO GUARD FIRED. `_dictates_code` is gated on `_CODE_SHAPED`, and `_CODE_SHAPED` could not match
that text. Its inline-call alternative was `\\b\\w+(?:\\.\\w+)+\\(` — an identifier, dots, then an
immediate open paren. Ruby writes `ZONE_BASE.key?(x)` and `rec.save!(x)`; Rust writes
`println!("x")`. The `?` and `!` sit exactly where the paren was expected, so **the most common call
shape in a whole language was invisible** to a detector whose entire purpose is to be
language-agnostic (#20). `_strip_invented_code` never ran and `loop.steer_dictated_code` was never
emitted — the guard was silent because it could not see, which reads identically to nothing being
wrong.

The line-anchored alternatives could not help either: these are assignments, so they start with no
keyword, end with no brace, and carry no call at the head of the line.
"""

import unittest

from cria import loop

REAL_STEER = ("The tests fail because shipping_cost calls zone_for(\"eu\") for existing 2-character "
              "zone names. Read lib/shipping/rates.rb and update shipping_cost to check if the input "
              "is already a known zone before calling zone_for: # Instead of: zone = "
              "zone_or_code.is_a?(String) && zone_or_code.length == 2 ? zone_for(zone_or_code) : "
              "zone_or_code # Use this: zone = ZONE_BASE.key?(zone_or_code) ? zone_or_code : "
              "zone_for(zone_or_code) After this edit, run rake test again.")


class TheMeasuredSteerIsSeenTests(unittest.TestCase):
    def test_the_steer_that_broke_a_repo_test_is_code_shaped(self):
        self.assertTrue(loop._CODE_SHAPED.search(REAL_STEER))

    def test_it_is_seen_whether_or_not_the_lines_survived_flattening(self):
        """The steer reached the model as one long line. A detector that only works on well-formed
        multi-line text is a detector that works when it is not needed."""
        multi = REAL_STEER.replace("# Use this:", "\n# Use this:\n")
        for form, text in (("flattened", REAL_STEER), ("multi-line", multi)):
            with self.subTest(form=form):
                self.assertTrue(loop._CODE_SHAPED.search(text))


class ALanguageIsNotAnExceptionTests(unittest.TestCase):
    def test_ruby_predicate_and_bang_methods(self):
        for probe in ("zone = ZONE_BASE.key?(zone_or_code)", "rec.save!(true)",
                      "country.in_eu?()", "list.empty?(x)"):
            with self.subTest(probe=probe):
                self.assertTrue(loop._CODE_SHAPED.search(probe))

    def test_rust_macros_too(self):
        for probe in ('println!("hello")', 'vec![1, 2]'.replace("[", "(").replace("]", ")")):
            with self.subTest(probe=probe):
                self.assertTrue(loop._CODE_SHAPED.search(probe))

    def test_the_shapes_that_already_worked_still_do(self):
        for probe in ("obj.bar(1)", "df.head(5)", "def f():", "import os",
                      "```ruby", "mvn -q test", "x = compute();"):
            with self.subTest(probe=probe):
                self.assertTrue(loop._CODE_SHAPED.search(probe))


class ProseIsStillProseTests(unittest.TestCase):
    """It is a TRIGGER — over-firing costs one focused reasoner call, so it may be generous. It may
    not be so generous that ordinary sentences buy a call."""

    def test_plain_english_does_not_fire(self):
        for probe in ("The rate table lists every zone with its base rate and per-kilogram rate.",
                      "It ships free (surcharges still apply) once the threshold is reached.",
                      "Add a README section describing zone_for and what it returns.",
                      "The gem is installed but the require is failing."):
            with self.subTest(probe=probe):
                self.assertFalse(loop._CODE_SHAPED.search(probe), probe)


if __name__ == "__main__":
    unittest.main()
