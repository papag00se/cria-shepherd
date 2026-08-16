"""The steer author gets the gate's own finding-set, not only a re-render of the transcript.

shipping-rates-rb x nemotron-elastic, call 0047. The gate's output sat in that prompt naming
`test_oversize_surcharge_still_applies_to_free_shipping`, Expected 12.0, Actual 0.0. Nineteen lines
below it cria's own steer said "The failing test test_domestic_light_parcel reports Expected: 0.0
Actual: 7.24 … change `OVERSIZE_SURCHARGE = 0.0`" — a different test, numbers from a stale failure,
and a change that would have permanently reddened the test the gate had just named.

The author wrote that because the slot it reasons from came back as "a specific line could not be
parsed" plus two exit codes. Meanwhile `last_gate_flag` held the finding-set: `_gate_notes` already
builds the CODER's checks block from it, and `judge_satisfaction` already takes it as
`gate_findings=` at three call sites. The steer author was the only seat reading a re-render.

Derive the signal from the authoritative event, never from a re-render of it (#12). Additive (#2):
the flag is appended, never substituted, and nothing is said when it is empty or already present
(#3).

The coder ignored that steer and reasoned correctly about the real failure, so this cost a turn
rather than a check — but the cell it happened in delivered almost nothing, and a turn is what it
had left.
"""

import unittest

from cria import loop


class Gs:
    """The fields author_steer touches on its guard state."""
    last_gate_flag = ""
    gate_plan = None
    recent_writes = None
    spin_path = ""
    repeat_action = "read_file rates.rb"
    gate_stall = 2


FLAG = ("test/test_rates.rb:23 TestRates#test_oversize_surcharge_still_applies_to_free_shipping "
        "Expected: 12.0 Actual: 0.0")


class TheFindingSetReachesTheAuthorTests(unittest.TestCase):
    """`author_steer` needs a reasoner and a body to run, so these exercise the composition rule it
    applies rather than driving the whole call: the flag is folded in unless already represented."""

    def fold(self, truth, flag):
        """The rule as written in author_steer."""
        flag = (flag or "").strip()
        if flag and flag not in truth:
            truth = "\n\n".join(t for t in (truth, flag) if t)
        return truth

    def test_an_unparsed_slot_still_gets_the_findings(self):
        truth = self.fold("a specific line could not be parsed  EXIT:1  EXIT:0", FLAG)
        self.assertIn("test_oversize_surcharge_still_applies_to_free_shipping", truth)
        self.assertIn("could not be parsed", truth)      # additive, not a substitution

    def test_an_empty_slot_gets_the_findings(self):
        self.assertEqual(self.fold("", FLAG), FLAG)

    def test_nothing_is_added_when_it_is_already_there(self):
        truth = "checks:\n" + FLAG
        self.assertEqual(self.fold(truth, FLAG), truth)

    def test_nothing_is_added_when_there_is_no_flag(self):
        self.assertEqual(self.fold("EXIT:0", ""), "EXIT:0")
        self.assertEqual(self.fold("EXIT:0", None), "EXIT:0")


class TheSourceIsTheOneOtherSeatsUseTests(unittest.TestCase):
    def test_the_coder_block_and_the_judge_read_the_same_field(self):
        """If this field ever stops being the gate's finding-set, three seats move together."""
        import inspect
        src = inspect.getsource(loop)
        self.assertIn("gate_findings=getattr(sess, \"last_gate_flag\", \"\") or \"\"", src)
        self.assertIn('getattr(gs, "last_gate_flag", "") or ""', src)

    def test_the_author_consults_it(self):
        import inspect
        src = inspect.getsource(loop.author_steer)
        self.assertIn("last_gate_flag", src)
        self.assertIn("#12", src)


if __name__ == "__main__":
    unittest.main()
