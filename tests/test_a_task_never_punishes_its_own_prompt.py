"""A task must not require a change its own verifier fails you for.

cart-billing-go's seed is `func (c *Cart) Subtotal() float64`, and its seeded test reads

    if got := c.Subtotal(); got != 15.00 {

The prompt says "Stop using `float64` for money arithmetic". Under the natural reading —
`Subtotal()` returns a decimal — that seeded line NO LONGER COMPILES, so the model has to edit it.
And `suite_green_plus_regression_test` fails the run for editing a seeded test.

**7 of 19 attempts lost that check to exactly this**, across three models and both arms, recorded as
"seeded test TestSubtotal was modified" or "was deleted".

The verifier's intent was always decimal INSIDE and float64 at the boundary — the hidden test proves
it, comparing `c.Total()` against the literal `48.58` — but the prompt never said so, and the hidden
test is invisible during the run by design. So the model could not have known.

Fixed in the prompt, which is where the information was missing. The work is untouched: the module
still has to be added, the arithmetic still has to move to decimal, and the rounding bug still has
to be found. Naming the boundary removes a trap, it does not remove a task — the opposite of making
a task easier to pass.

The general rule this file enforces: where a verifier constrains a signature, the prompt has to say
so. A constraint only the hidden test knows is a coin flip.
"""

import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
TASKS = REPO / "suite" / "tasks"


def prompt(task: str) -> str:
    return (TASKS / task / "prompt.txt").read_text()


class TheGoTaskNamesTheBoundaryItsVerifierEnforcesTests(unittest.TestCase):
    def test_the_prompt_does_NOT_pin_the_signatures(self):
        """Reverted 2026-08-12 on operator instruction. The pin was added because the seeded test
        does `got != 15.00` and will not compile against a decimal return, so 7 of 19 attempts lost
        suite_green_plus_regression_test for editing a seeded test. The trap is still open; the
        operator's call is that the prompt is not where it gets closed."""
        body = prompt("cart-billing-go")
        self.assertNotRegex(body, r"`Subtotal\(\)`.{0,80}returning")

    def test_it_still_demands_decimal_arithmetic(self):
        """The constraint must not have swallowed the requirement."""
        body = prompt("cart-billing-go")
        self.assertIn("Stop using `float64` for money arithmetic", body)
        self.assertIn("third-party Go decimal module", body)
        self.assertIn("Do not create a custom decimal type", body)

    def test_it_still_demands_the_item_types_stay(self):
        self.assertIn("`Item` struct field types unchanged", prompt("cart-billing-go"))

    def test_the_seeded_test_compiles_against_the_signature_the_prompt_now_promises(self):
        """The whole point: with Subtotal() returning float64, `got != 15.00` still builds, so the
        model never has to touch the seeded test to make the project compile."""
        seed = (TASKS / "cart-billing-go" / "seed" / "cart.go").read_text()
        test = (TASKS / "cart-billing-go" / "seed" / "cart_test.go").read_text()
        self.assertIn("func (c *Cart) Subtotal() float64", seed)
        self.assertIn("got != 15.00", test)

    def test_the_hidden_test_compares_against_a_float_literal(self):
        """The evidence that float64-at-the-boundary was always the intent."""
        hidden = (TASKS / "cart-billing-go" / "hidden" / "hidden_cart_test.go").read_text()
        self.assertIn("got != 48.58", hidden)


class NoTaskAsksForSomethingItsSeededTestsForbidTests(unittest.TestCase):
    """The general case, checked cheaply: a task that tells the model to stop using a type must say
    what happens at any boundary its own seeded tests assert against."""

    def test_a_prompt_banning_a_type_names_the_boundary(self):
        banned = re.compile(r"stop using `(\w+)`|do not (?:keep )?us(?:e|ing) `(\w+)`", re.I)
        for task_dir in sorted(TASKS.iterdir()):
            p = task_dir / "prompt.txt"
            if not p.is_file():
                continue
            body = p.read_text()
            m = banned.search(body)
            if not m:
                continue
            with self.subTest(task=task_dir.name):
                kept = re.search(r"keep\s+.{0,80}(returning|unchanged|as they are)", body, re.I | re.S)
                self.assertIsNotNone(
                    kept,
                    f"{task_dir.name} tells the model to stop using a type but never says which "
                    f"signatures or fields must survive — the verifier will decide silently")


if __name__ == "__main__":
    unittest.main()
