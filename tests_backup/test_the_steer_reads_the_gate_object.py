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

import json
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
    """"If this field ever stops being the gate's finding-set, three seats move together" — driven
    below on ONE session object, rather than grepped, so a rename that breaks the sync shows up as
    a failed read instead of a surviving substring somewhere else in a 9,000-line module."""

    FLAG = ("test/test_rates.rb:23 TestRates#test_oversize_surcharge_still_applies_to_free_shipping "
            "Expected: 12.0 Actual: 0.0")

    def test_the_coder_block_reads_it(self):
        """`_gate_notes` builds the judge-facing checks block from the gate's own finding-set on a
        RED gate — the exact case the walked incident was about."""
        class _Sess:
            last_gate_red = True
            last_gate_flag = self.FLAG
            last_gate_testless = False
            last_gate_skipped = 0
            last_gate_ran = False
            gate_fresh = False

        self.assertIn(self.FLAG, loop._gate_notes(_Sess()))

    def test_the_judge_reads_it(self):
        """`judge_satisfaction` takes it as `gate_findings=` and folds it into the fail-closed
        (unparseable-verdict) reason — the fallback every one of its three call sites in loop.py
        relies on to still name something concrete when the judge itself produced nothing."""
        def unparseable(body, rlog):
            return json.dumps({"choices": [{"message": {"content": "not a verdict"}}]}).encode()

        satisfied, reason, _fix = loop.judge_satisfaction("do the thing", "evidence", unparseable, None,
                                                          _Rlog(), gate_findings=self.FLAG)
        self.assertFalse(satisfied)
        self.assertIn(self.FLAG, reason)

    def test_the_author_consults_it(self):
        """Drive the real `author_steer`: with NO computed truth text and `gs.last_gate_flag` set,
        the flag must reach the reasoner's own prompt — the actual bug (a re-render standing in for
        this), not just the identifier `last_gate_flag` appearing somewhere in the function body."""
        from cria.loop import GuardState, author_steer

        seen = {}

        def chat(body, rlog):
            seen["user"] = body["messages"][1]["content"]
            return json.dumps({"choices": [{"message": {"content": "ON_TRACK"}}]}).encode()

        gs = GuardState(probe_call_id="p1", spin_path="x.py", repeat_action="write_file x.py",
                        gate_stall=3)
        gs.recent_writes = []
        gs.last_gate_flag = self.FLAG
        author_steer(chat, None, None, gs, {"messages": []}, _Rlog(), condition="thrash")
        self.assertIn(self.FLAG, seen["user"])


class _Rlog:
    def emit(self, *a, **k):
        pass


if __name__ == "__main__":
    unittest.main()
