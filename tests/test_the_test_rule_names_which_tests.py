"""cria forbade the coder from fixing a test the coder had written five calls earlier.

Attached to every failing check, in two prompts:

    If a TEST is what failed, fix what the test caught; changing the test so it stops asking is not
    a fix.

It says "a test". In nemotron's Ruby run the failing test was one the model had written itself,
minutes before, with a bug in the test's own setup. It read the rule as binding on that test too:

    However, the instruction says "Don't change what the tests assert; they describe the behaviour
    our customers were promised." So we must adjust code to meet the test expectation.

and bent working code to satisfy its own broken fixture.

The rule is not wrong and is not removed — it exists because models talk themselves into weakening
real assertions, and the walk confirmed that class is live. It was aimed at the wrong set of files.
It now names the set: the tests that were in the repository at the start.

WHY THE SENTENCE AND NOT A CRIA-SIDE DECISION. Attaching it conditionally needs cria to know which
test files predate the session, and cria keeps no creation ledger — it sees writes, not what existed
before the first one. The party that does know is the model: it wrote the test. So the scope is
stated, not inferred. If a creation ledger ever exists, this becomes a cria-side decision and the
sentence can go.

TWO COPIES, ONE RULE. `prompts.load` has no include mechanism, so the clause lives in both prompts
that carry the rule. This test is what stops them drifting.
"""

import re
import unittest

from cria import prompts


CARRIERS = ("block_nudge_preamble", "steer_checks_repeat")

# The scope sentence, as one string, so the two copies cannot say subtly different things.
SCOPE = ("This governs the tests that were already in the repository when you started — they "
         "describe behaviour someone else depends on. A test YOU wrote earlier in this session is "
         "yours: if its own setup or fixture is wrong, correct the test.")


class EveryCarrierOfTheRuleNamesItsScopeTests(unittest.TestCase):
    def test_both_prompts_carry_the_rule(self):
        for name in CARRIERS:
            with self.subTest(prompt=name):
                self.assertRegex(prompts.load(name), r"stops asking is not a fix",
                                 "the rule itself must not be deleted")

    def test_both_prompts_carry_the_same_scope_sentence(self):
        for name in CARRIERS:
            with self.subTest(prompt=name):
                self.assertIn(SCOPE, prompts.load(name))

    def test_the_scope_comes_immediately_after_the_rule(self):
        """A qualifier three paragraphs later is a qualifier a weak model reads too late."""
        for name in CARRIERS:
            with self.subTest(prompt=name):
                body = prompts.load(name)
                rule_end = body.index("stops asking is not a fix")
                self.assertLess(body.index(SCOPE) - rule_end, 60,
                                "the scope must follow the rule, not trail it")

    def test_the_external_system_exception_still_stands(self):
        """The narrower escape hatch, added because a test asserted a false world-fact and the
        coder talked itself out of the only correct repair three times. Untouched."""
        for name in CARRIERS:
            with self.subTest(prompt=name):
                body = prompts.load(name)
                self.assertIn("EXTERNAL system", body)
                self.assertIn("never qualifies", body)

    def test_it_still_forbids_weakening_a_repository_test(self):
        for name in CARRIERS:
            with self.subTest(prompt=name):
                self.assertRegex(prompts.load(name),
                                 r"(?:Weakening or deleting an assertion|stops asking is not a fix)")


class TheScopeIsStatedNotNumberedTests(unittest.TestCase):
    def test_it_refers_to_the_session_never_to_a_call_index(self):
        """"this session" is something the model can locate. "call 41" is cria's private numbering."""
        for name in CARRIERS:
            with self.subTest(prompt=name):
                body = prompts.load(name)
                self.assertIn("this session", body)
                self.assertNotRegex(body, r"\b(?:call|turn)\s+\d+")


if __name__ == "__main__":
    unittest.main()
