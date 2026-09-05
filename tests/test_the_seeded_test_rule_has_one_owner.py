"""cria told coders "changing the test is not a fix" and never said which tests, in the only copy
that shipped.

The rule lived in THREE places: `prompts/block_nudge_preamble.txt`, `prompts/steer_checks_repeat.txt`,
and an inline literal in `probegate.py`. Commit 57c8520 added the scope sentence — *"This governs the
tests that were already in the repository when you started… A test YOU wrote earlier in this session
is yours"* — to the two prompt files. It could not add it to the third, because a string in code is
not where anyone looks for a prompt (#22).

**The third copy is the one that ships.** It appears in 3,254 captured coder prompts, far more than
either sibling. So for a whole cycle the coder was told not to weaken a test and never told the rule
was about the SEEDED ones.

Walked on cycle 4 cell 7, shipping-rates-rb x qwen35. The model reverted its own test edit once,
quoting the task prompt — then two calls later rewrote a seeded assertion, `test_eu_heavier_parcel`
`assert_equal 15.99` → `32.99`, on a test its own `rake test` had just reported PASSING. Its
reasoning: *"my calculation gives 32.99. The difference of 17.0 suggests the test expectations are
incorrect."*

One owner now (`prompts/seeded_test_rule.txt`), and the carriers include it.

AND A TOKEN EVERY CALLER MUST REMEMBER IS ONE SOMEONE WILL FORGET. The first cut made
`{{SEEDED_TEST_RULE}}` a parameter, and a caller that omitted it put the literal token in front of
the model — which is how this class of bug started. `prompts.render` now treats a leftover
`{{TOKEN}}` naming a prompt file as an include, so the fragment fills itself.
"""

import re
import unittest

from cria import proberun, prompts

CARRIERS = ("block_nudge_preamble", "steer_checks_repeat", "checks_error_class")
SCOPE = "already in the repository when you started"


class EveryCarrierSaysWhichTestsTests(unittest.TestCase):
    def test_all_three_carry_the_prohibition_and_its_scope(self):
        for name in CARRIERS:
            with self.subTest(prompt=name):
                out = prompts.render(name, findings="<f>", since="")
                self.assertIn("not a fix", out)
                self.assertIn(SCOPE, out)
                self.assertIn("A test YOU wrote earlier in this session is yours", out)
                self.assertIn("expected output", out)
                self.assertIn("user's requirement", out)

    def test_the_copy_that_ships_is_one_of_them(self):
        """`checks_error_class` is the gate's own findings block — 3,254 captured prompts, and the
        copy the scope sentence never reached."""
        out = prompts.render("checks_error_class", findings="cart.go:3: boom")
        self.assertIn("⟦ctx:checks⟧", out)
        self.assertIn("cart.go:3: boom", out)
        self.assertIn(SCOPE, out)

    def test_the_external_system_exception_survives_in_all_three(self):
        for name in CARRIERS:
            with self.subTest(prompt=name):
                out = prompts.render(name, findings="<f>", since="")
                self.assertIn("EXTERNAL system", out)
                self.assertIn("Quote the command you ran", out)
                self.assertIn("own failure message is not that evidence", out)


class ThereIsOnlyOneCopyTests(unittest.TestCase):
    def test_the_rule_is_not_typed_into_any_carrier(self):
        """Each carrier must INCLUDE the fragment, never restate it — restating is what let two
        copies drift from the third."""
        for name in CARRIERS:
            with self.subTest(prompt=name):
                self.assertNotIn(SCOPE, prompts.load(name))
                self.assertIn("{{SEEDED_TEST_RULE}}", prompts.load(name))

    def test_no_model_facing_copy_survives_in_code(self):
        import inspect

        from cria import probegate
        # CODE only — the comment at the return site quotes the clause on purpose, to record what
        # was there and why it moved.
        code = [ln for ln in inspect.getsource(probegate).splitlines()
                if not ln.lstrip().startswith("#")]
        self.assertFalse([ln for ln in code if "stops asking is not a fix" in ln])


class AForgottenTokenFillsItselfTests(unittest.TestCase):
    def test_render_includes_a_fragment_the_caller_did_not_pass(self):
        out = prompts.render("checks_error_class", findings="x")
        self.assertNotIn("{{SEEDED_TEST_RULE}}", out)
        self.assertIn(SCOPE, out)

    def test_an_explicit_value_still_wins(self):
        out = prompts.render("checks_error_class", findings="x", seeded_test_rule="OVERRIDDEN")
        self.assertIn("OVERRIDDEN", out)
        self.assertNotIn(SCOPE, out)

    def test_a_token_naming_no_prompt_file_is_left_alone(self):
        """An unfilled token must still fail `no placeholder reaches the model` — that guard is what
        caught this. Only a token that names a real fragment is an include."""
        self.assertIn("{{SINCE}}", prompts.render("steer_checks_repeat", findings="x"))

    def test_the_composed_block_nudge_has_no_tokens_left(self):
        self.assertEqual(re.findall(r"\{\{[A-Z_]+\}\}", proberun.BLOCK_NUDGE_PREAMBLE), [])
        self.assertIn(SCOPE, proberun.BLOCK_NUDGE_PREAMBLE)


if __name__ == "__main__":
    unittest.main()
