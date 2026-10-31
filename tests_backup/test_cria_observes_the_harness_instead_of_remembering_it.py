"""cria carried a hardcoded copy of one harness's constant for three months and never checked it.

`content_reduce.INLINE_RESULT_MAX_BYTES = 9000` exists to stay under Codex's
`TruncationPolicyConfig::bytes(10_000)` — a number copied out of the retired fork's Rust source, in a
project whose rule 18 says cria never depends on one harness's config and that fork is "a read-only
spec, never a fix target".

It was measured once, on 2026-08-04, against 166 observed cuts. Asked for a CURRENT example there was
none:

  * zero truncation markers across all 50 captured sessions, both unit spellings
  * the largest tool result cria had actually sent upstream was 160,447 bytes, intact — sixteen times
    the limit it supposedly could not exceed
  * the run cited as the original evidence had been deleted in housekeeping

The belief outlived its evidence, grew a second life on the inbound path where it could not possibly
prevent a harness cut, and cost 24% of every command result across a 24-cell campaign before anyone
re-checked it.

A remembered number is a claim about cria. The marker on the wire is a claim about the world (#5b).
This asks the world — and it does it for whatever harness is connected, with no survey of anyone's
source and nothing to go stale, which is what rule 18 actually asks for.

OBSERVE, NEVER ACT. Nothing is altered and nothing reaches the model (#3). If a harness really is
cutting cria's content, the log will say so, in that harness's own numbers.
"""

import unittest

from cria import writeproxy


class Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


def tool(text: str) -> dict:
    return {"role": "tool", "tool_call_id": "t1", "content": text}


class ItCountsWhatTheHarnessCutTests(unittest.TestCase):
    def test_the_token_spelling_is_seen(self):
        r = Rlog()
        self.assertEqual(writeproxy.note_harness_cuts([tool("ex…3 tokens truncated…ut")], r), 1)
        self.assertEqual(r.events[0][1]["unit"], "tokens")

    def test_the_char_spelling_is_seen(self):
        r = Rlog()
        writeproxy.note_harness_cuts([tool("this is an exam…30 chars truncated…ld be truncated")], r)
        self.assertEqual(r.events[0][1], {"level": "warn", "amount": "30", "unit": "chars"})

    def test_the_amount_survives_its_thousands_separator(self):
        r = Rlog()
        writeproxy.note_harness_cuts([tool("head…1,599 tokens truncated…tail")], r)
        self.assertEqual(r.events[0][1]["amount"], "1,599")

    def test_several_cuts_in_one_body_all_count(self):
        r = Rlog()
        n = writeproxy.note_harness_cuts([tool("a…5 chars truncated…b…7 chars truncated…c")], r)
        self.assertEqual((n, len(r.events)), (2, 2))


class WhatItMustNotDoTests(unittest.TestCase):
    def test_a_clean_result_is_silent(self):
        """#3 — nothing to say on a clean signal."""
        r = Rlog()
        self.assertEqual(writeproxy.note_harness_cuts([tool("5 passed in 0.02s")], r), 0)
        self.assertEqual(r.events, [])

    def test_only_tool_results_are_read(self):
        """A model WRITING about truncation is not the harness truncating."""
        r = Rlog()
        msgs = [{"role": "assistant", "content": "the output said …9 chars truncated… there"}]
        self.assertEqual(writeproxy.note_harness_cuts(msgs, r), 0)

    def test_it_changes_nothing(self):
        before = [tool("x…9 tokens truncated…y")]
        after = writeproxy.represent_inbound([dict(m) for m in before], Rlog())
        self.assertEqual(after[0]["content"], before[0]["content"])

    def test_no_rlog_is_not_a_crash(self):
        self.assertEqual(writeproxy.note_harness_cuts([tool("x…9 chars truncated…y")], None), 1)

    def test_empty_input_is_fine(self):
        self.assertEqual(writeproxy.note_harness_cuts([], Rlog()), 0)
        self.assertEqual(writeproxy.note_harness_cuts(None, Rlog()), 0)


class TheCorpusItWasBuiltAgainstTests(unittest.TestCase):
    def test_the_shape_the_harness_actually_writes(self):
        """Taken from codex-rs/utils/output-truncation/src/truncate_tests.rs, so cria is matching the
        harness's real output rather than a guess at it."""
        for real in ("Total output lines: 1\n\n…13 chars truncated…t",
                     "Total output lines: 1\n\nex…3 tokens truncated…ut",
                     "Total output lines: 1\n\nthis is an…10 tokens truncated… truncated",
                     "Total output lines: 1\n\nthis is an exam…30 chars truncated…ld be truncated"):
            with self.subTest(real=real[-30:]):
                self.assertEqual(writeproxy.note_harness_cuts([tool(real)], Rlog()), 1)


if __name__ == "__main__":
    unittest.main()
