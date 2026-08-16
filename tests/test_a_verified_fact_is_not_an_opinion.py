"""When the disk AGREES with a veto, the coder is told so — cria stops discarding its own check.

`_veto_refuted_by_disk` stats every path a NOT-consistent verdict names. It had only one return
path that used those facts: REFUTED, when a file the veto called missing is really there. When the
filesystem CORROBORATED the veto, the facts were computed exactly and thrown away, and the report
reached the coder under `done_incomplete`'s framing — "one reader's opinion of your work, not a
verified fact".

cart-billing-go x gemma4: the coder deleted `discounts.json` to prove its fallback and never put it
back. The confirm judge said the file was missing. cria stat'ed it, found it genuinely absent,
dropped that, and handed the true report over as an opinion. The coder then declared done twice,
claiming it had created a file its own `list_dir` showed was absent. It recovered on the third pass,
so this cost two false completions and about five minutes rather than a check — but a verified fact
labelled an opinion is #5b either way, and telling the coder more about the real state is the
additive direction (#2).
"""

import os
import tempfile
import unittest

from cria import prompts
from cria.loop import _veto_refuted_by_disk


class _Ask:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def __call__(self, _system):
        self.calls += 1
        return self.reply


class TheDiskFactsSurviveBothDirectionsTests(unittest.TestCase):
    def test_a_veto_the_disk_confirms_carries_the_facts(self):
        with tempfile.TemporaryDirectory() as ws:
            refuted, facts = _veto_refuted_by_disk(
                "Missing discounts.json in the project root", ws, ask=_Ask("STANDS"))
            self.assertEqual(refuted, "")
            self.assertIn("discounts.json", facts)
            self.assertIn("NOT on disk", facts)

    def test_it_costs_no_reasoner_call_when_the_disk_already_settles_it(self):
        """Nothing exists to refute with, so there is nothing to ask (#9's bound, #3)."""
        with tempfile.TemporaryDirectory() as ws:
            ask = _Ask("STANDS")
            _veto_refuted_by_disk("Missing discounts.json in the project root", ws, ask=ask)
            self.assertEqual(ask.calls, 0)

    def test_a_refuted_veto_still_overturns_and_still_reports_the_facts(self):
        with tempfile.TemporaryDirectory() as ws:
            p = os.path.join(ws, "discounts.json")
            open(p, "w").write("{}\n")
            refuted, facts = _veto_refuted_by_disk(
                f"Missing discounts.json file at {p}", ws, ask=_Ask("REFUTED"))
            self.assertIn("discounts.json", refuted)   # the token as the veto wrote it
            self.assertIn("EXISTS on disk", facts)

    def test_a_veto_naming_no_path_says_nothing(self):
        with tempfile.TemporaryDirectory() as ws:
            self.assertEqual(_veto_refuted_by_disk("the rounding is wrong", ws, ask=_Ask("STANDS")),
                             ("", ""))

    def test_no_reasoner_still_says_nothing(self):
        with tempfile.TemporaryDirectory() as ws:
            self.assertEqual(_veto_refuted_by_disk("Missing x.json", ws, ask=None), ("", ""))


class TheNoteIsAFactNotAnOpinionTests(unittest.TestCase):
    def test_it_names_the_check_and_the_moment(self):
        note = prompts.render("veto_disk_confirms", facts="- discounts.json: NOT on disk")
        low = note.lower()
        self.assertIn("filesystem was checked just now", low)
        self.assertIn("verified fact", low)
        self.assertIn("discounts.json", note)

    def test_it_never_names_cria(self):
        self.assertNotIn("cria", prompts.render("veto_disk_confirms", facts="- a: NOT on disk").lower())


if __name__ == "__main__":
    unittest.main()
