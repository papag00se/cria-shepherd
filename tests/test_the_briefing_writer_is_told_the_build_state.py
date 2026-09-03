"""The compactor was asked to work out the build state by reading, and it guessed — both directions.

cria holds the last gate verdict exactly. It was appended to the briefing's OUTPUT
(`server._last_checks_note`, `loop._briefing_gate_ground_truth`) and never given to the writer as
INPUT, so the writer determined "does this compile" by reading a 66 KB transcript.

Walked on `feed-pipeline-java x qwen35` 1787249436 (0/5), which got it wrong in both directions in
one run:

- minute 26 — the briefing says `The build compiles successfully` while its own transcript carries
  `cannot find symbol / symbol: class Action` eight times and `exited with code 1` twice;
- minute 8 — the briefing reports a `ConcurrentModificationException` that had been fixed 99 seconds
  earlier and never re-run. The coder burned eight calls disproving it, saying so out loud:
  *"the summary says it fails with ConcurrentModificationException — but my test shows it works."*

Dropped and invented are ONE defect, not two. The writer was asked to derive a fact cria already
had (#8: deterministic code gathers, the reasoner judges).

THE OBVIOUS FIX WAS THE WRONG ONE. Vetoing a briefing sentence that contradicts the gate treats the
symptom and leaves the writer guessing on every sentence nobody thought to check. Given the verdict
up front it has no reason to guess (#4: fix upstream, not at the point of damage). This is the same
argument, one step on, that already put the workspace inventory in front of the writer — "a writer
shown no workspace invents one".
"""

import unittest
from types import SimpleNamespace

from cria import selfcompact
from cria import server as srv


MSGS = [{"role": "user", "content": "Fix the importer."},
        {"role": "assistant", "content": "done"}]
RED = "[ERROR] Importer.java:[235,51] cannot find symbol\n  symbol:   class Action"


class TheWriterIsGivenTheVerdictTests(unittest.TestCase):
    def test_the_verdict_is_in_the_request_not_only_in_the_answer(self):
        out = selfcompact.compaction_request(MSGS, "", None, RED)
        self.assertIn("class Action", out)
        self.assertIn("REPO'S OWN CHECKS", out)

    def test_it_is_told_not_to_derive_the_build_state_by_reading(self):
        out = selfcompact.compaction_request(MSGS, "", None, RED)
        self.assertIn("Do not work the current build state out by reading the transcript", out)
        # both directions named, because the run got it wrong both ways
        self.assertIn("may already be fixed", out)
        self.assertIn("may already be stale", out)

    def test_the_ask_still_comes_last(self):
        # A model obeys the last instruction it reads — the checks must not displace the ask.
        out = selfcompact.compaction_request(MSGS, "FILES ON DISK\n- a.java", None, RED)
        self.assertLess(out.index("REPO'S OWN CHECKS"), out.index("Write the briefing now"))
        self.assertLess(out.index("FILES ON DISK"), out.index("REPO'S OWN CHECKS"))

    def test_a_clean_or_silent_gate_renders_nothing(self):
        # Silence over noise (#3); never an empty or guessed verdict (#5b).
        for flag in ("", "   ", "\n"):
            out = selfcompact.compaction_request(MSGS, "", None, flag)
            self.assertNotIn("REPO'S OWN CHECKS", out)

    def test_the_raw_verdict_goes_in_and_the_framing_is_applied_once(self):
        # One owner renders, so the two compaction paths cannot disagree about whether their
        # argument arrives already framed.
        once = selfcompact.compaction_request(MSGS, "", None, RED)
        self.assertEqual(once.count("REPO'S OWN CHECKS"), 1)
        self.assertEqual(selfcompact.checks_input(""), "")


class BothCompactionPathsCarryItTests(unittest.TestCase):
    def test_the_harness_path_puts_the_verdict_in_the_body(self):
        body = srv._compaction_body({"messages": MSGS}, None, None, RED)
        text = "\n".join(m["content"] for m in body["messages"])
        self.assertIn("class Action", text)
        self.assertIn("REPO'S OWN CHECKS", text)

    def test_the_harness_path_without_a_verdict_is_unchanged(self):
        text = "\n".join(m["content"] for m in
                         srv._compaction_body({"messages": MSGS}, None, None, "")["messages"])
        self.assertNotIn("REPO'S OWN CHECKS", text)

    def test_one_lookup_serves_the_input_and_the_output_appendix(self):
        sess = SimpleNamespace(last_gate_flag=RED, gate_plan=None)

        class _S:
            loop = SimpleNamespace(_store=SimpleNamespace(get=lambda k: sess if k == "sid:x" else None))

        self.assertEqual(srv._last_gate_flag(_S(), "sid:x"), RED)
        self.assertIn("LATEST CHECK RESULTS", srv._last_checks_note(_S(), "sid:x"))
        self.assertEqual(srv._last_gate_flag(_S(), "sid:other"), "")
        self.assertEqual(srv._last_checks_note(_S(), "sid:other"), "")


if __name__ == "__main__":
    unittest.main()
