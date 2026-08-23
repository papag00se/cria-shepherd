"""cria printed true facts under a sentence saying they agreed with a claim they had nothing to do with.

`veto_disk_confirms` opens *"The filesystem was checked just now and AGREES with the report above"*
and closes *"That part is a verified fact about the workspace as it stands, not one reader's
opinion."* It was attached whenever ANY named token resolved on disk.

Walked at `20260822T174652/0454`: the report said *"The code compilation failed (mvn compile error
on InterruptedException)"* and the "agreement" underneath it was

    - REVIEW.md: EXISTS on disk

A true fact, presented as corroboration of a claim about a compiler.

A veto is triggered by `_VETO_MISSING` — the report says something is missing or empty — so what
agrees with it is a file that is NOT there, or one that is there and empty. Everything else is still
worth telling the coder (it is exact and freshly checked) under wording that says only what cria
did.

The second half of this file is the token the veto was willing to make that claim about. `_VETO_PATH`
is "a word, a dot, a short suffix", which is also a HOSTNAME and an abbreviation:

    - api.handle.me: NOT on disk    5 times — the task's own API host
    - e.g: NOT on disk              6 times — the judge's own prose

The suffix now has to be one a file actually uses, sourced from
`probediscovery.TEST_CONVENTIONS` — the same table every language claim is made from — plus the
config and document suffixes a workspace holds. Still a bound (#11b): `Node.js` survives it, because
`.js` is a real extension and a file may genuinely be called that. Measured at 1 occurrence against
the 11 this removes.
"""

import unittest

from cria import loop, prompts

MISSING = "- discounts.json: NOT on disk"
PRESENT = "- REVIEW.md: EXISTS on disk — 4,746 bytes, 90 lines, 80 non-comment code lines"
EMPTY = "- handlers.py: EXISTS on disk — 0 bytes, 0 lines, 0 non-comment code lines"
NO_CODE = "- handlers.py: EXISTS on disk — 120 bytes, 10 lines, 0 non-comment code lines"


class AgreementIsClaimedOnlyWhenTheFactsAgreeTests(unittest.TestCase):
    def test_a_file_that_is_not_there_agrees_with_a_missing_claim(self):
        self.assertTrue(loop._facts_agree_with_a_missing_claim(MISSING))

    def test_an_empty_file_agrees_with_an_emptiness_claim(self):
        self.assertTrue(loop._facts_agree_with_a_missing_claim(EMPTY))
        self.assertTrue(loop._facts_agree_with_a_missing_claim(NO_CODE))

    def test_a_file_that_is_simply_there_does_not(self):
        self.assertFalse(loop._facts_agree_with_a_missing_claim(PRESENT))

    def test_a_count_that_merely_contains_a_zero_is_not_a_zero(self):
        """`80 non-comment code lines` contains the characters `0 non-comment code lines`."""
        self.assertFalse(loop._facts_agree_with_a_missing_claim(PRESENT))

    def test_both_wordings_exist_and_only_one_claims_agreement(self):
        agrees = prompts.load("veto_disk_confirms")
        checked = prompts.load("veto_disk_checked")
        self.assertIn("agrees with the report", agrees)
        self.assertNotIn("agrees with the report", checked)
        for body in (agrees, checked):
            self.assertIn("not one reader's opinion", body)


class TheVetoOnlyClaimsAboutSomethingFileShapedTests(unittest.TestCase):
    def test_a_hostname_is_not_a_file(self):
        self.assertEqual(loop._veto_paths("check api.handle.me for the spec"), [])

    def test_an_abbreviation_is_not_a_file(self):
        self.assertEqual(loop._veto_paths("e.g. the resolver module"), [])

    def test_a_real_path_still_is(self):
        self.assertEqual(loop._veto_paths("edit lib/shipping/rates.rb now"), ["lib/shipping/rates.rb"])

    def test_every_language_cria_knows_is_covered(self):
        """Sourced from the same table the language claims are made from, so there is no second
        list to drift (#23)."""
        from cria import probediscovery
        for conv in probediscovery.TEST_CONVENTIONS:
            for ext in conv.exts:
                with self.subTest(ext=ext):
                    self.assertEqual(loop._veto_paths(f"open main.{ext} first"), [f"main.{ext}"])

    def test_manifests_and_documents_are_covered_too(self):
        for name in ("pom.xml", "package.json", "Cargo.toml", "README.md", "go.mod", "Gemfile.lock"):
            with self.subTest(name=name):
                self.assertEqual(loop._veto_paths(f"the {name} is wrong"), [name])


if __name__ == "__main__":
    unittest.main()
