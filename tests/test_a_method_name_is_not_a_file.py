"""cria must not invent filenames out of a judge's prose and print them as verified facts.

`_VETO_PATH` matches "a word, a dot, a short suffix" — which in any dotted language is also every
method reference and every abbreviation. Walked on shipping-rates-rb x ternary-bonsai 1787442206,
call 0024. The judge wrote:

    implement Shipping.zone_for for two-letter country codes using a third-party EU membership gem
    (e.g., eu_countries)

and cria printed, to the coder, under "That part is a verified fact about the workspace as it stands,
not one reader's opinion":

    - Shipping.zone: NOT on disk
    - Shipping.zone: NOT on disk
    - e.g: NOT on disk

`Shipping.zone` is `Shipping.zone_for` with its tail bitten off by the suffix bound; `e.g` is Latin."""
import os
import tempfile
import unittest
from pathlib import Path

from cria import loop, wsview


class _Ask:
    def __init__(self, answer="STANDS"):
        self.answer, self.prompts = answer, []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.answer


class NoFabricatedFilenamesTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(wsview.unbind, wsview.bind(wsview.DirectView()))
        self.ws = tempfile.mkdtemp()
        Path(self.ws, "lib").mkdir()
        Path(self.ws, "lib", "rates.rb").write_text("module Shipping\nend\n")

    def _facts(self, why):
        """The disk-fact lines cria would print — the reasoner is only consulted when something
        EXISTS to refute with, so the facts themselves are the return value."""
        _refuted, facts = loop._veto_refuted_by_disk(why, self.ws, ask=_Ask("STANDS"))
        return facts

    def test_a_dotted_method_reference_is_not_matched_at_all(self):
        self.assertNotIn("Shipping.zone",
                         loop._VETO_PATH.findall("implement Shipping.zone_for for two-letter codes"))

    def test_neither_reaches_the_disk_facts(self):
        facts = self._facts("Missing: implement Shipping.zone_for using a gem (e.g., eu_countries)")
        self.assertNotIn("Shipping.zone", facts)
        self.assertNotIn("e.g", facts)

    def test_a_real_missing_file_is_still_reported(self):
        self.assertIn("REVIEW.md: NOT on disk", self._facts("Missing REVIEW.md at the project root"))

    def test_a_real_present_file_is_still_reported(self):
        self.assertIn("lib/rates.rb: EXISTS on disk",
                      self._facts("Missing content in lib/rates.rb — it has no code"))

    def test_a_one_letter_stem_is_never_a_file(self):
        for tok in ("e.g", "i.e", "a.b"):
            self.assertLess(len(os.path.splitext(os.path.basename(tok))[0]), 2, tok)


if __name__ == "__main__":
    unittest.main()
