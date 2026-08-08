"""Doctrine 13: the completion path fails CLOSED. An undecidable judge means NOT done.

verify.txt used to end its list of not-done conditions with "Otherwise default to DONE" — a
fail-OPEN default sitting in the one path required to fail closed. It reads as "if none of the
listed failures apply, approve", so a judge holding no evidence at all falls through to approval.
Run 20260801T160104 call 0038 is the case that showed its work:

    {"done": true, "reason": "workspace has no files, so the claimed resolve_handle.py does not
     exist ... Since I cannot see the file and no tool output exists for the step, I default to
     DONE per instructions."}

Only 1 of 112 captured approvals quotes it, but that undercounts the defect: every approval reached
without positive evidence passes through the same default silently. That one merely narrated it.
"""
import re
import unittest

from cria import prompts


class VerifyDefaultTests(unittest.TestCase):
    TEXT = prompts.load("verify")

    def test_the_fail_open_default_is_gone(self):
        self.assertNotIn("Otherwise default to DONE", self.TEXT)
        self.assertNotIn("default to DONE", self.TEXT)

    # Substance pins, not exact wording — the operator rewrites these prompts for concision and an
    # exact-phrase assertion goes red on a rewrite that keeps every protection intact. What must
    # survive any rewrite is the RULE; the sentence carrying it may change.
    def test_done_now_requires_positive_evidence(self):
        low = self.TEXT.lower()
        self.assertIn("positively", low)
        self.assertTrue("done=true" in low or "done` only when" in low, self.TEXT)

    def test_undecidable_is_explicitly_NOT_done(self):
        low = self.TEXT.lower()
        self.assertTrue(any(w in low for w in ('"i cannot tell" is not done',
                                               "missing evidence means `done=false`",
                                               "missing evidence means done=false")), self.TEXT)

    def test_the_two_real_protections_survive(self):
        # The line existed to stop an over-strict judge wedging the plan. Both halves of that intent
        # are kept — only the fail-open default went.
        low = self.TEXT.lower()
        self.assertIn("do not invent requirements", low)
        self.assertTrue("unrelated to its goal" in low or "unrelated to this step" in low, self.TEXT)


class NoSiblingFailOpenTests(unittest.TestCase):
    """A fail-open default is a CLASS of bug, not one line. No completion-path prompt may resolve
    doubt toward approval."""

    JUDGES = ("verify", "verify_confirm", "done_summary")
    BAD = re.compile(r"default(?:s|ing)? to (?:done|true|satisfied|consistent|yes)", re.I)

    def test_no_completion_prompt_defaults_to_approval(self):
        for name in self.JUDGES:
            try:
                text = prompts.load(name)
            except Exception:
                try:
                    text = "\n".join(prompts.load_map(name).values())
                except Exception:
                    continue
            with self.subTest(prompt=name):
                self.assertIsNone(self.BAD.search(text),
                                  f"{name} resolves doubt toward approval; completion fails CLOSED")
