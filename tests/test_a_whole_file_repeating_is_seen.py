"""The model wrote a 4-of-5 answer, then repeated one block 22 times, and cria threw all of it away.

Cycle 4 cell 4, `feed-pipeline-java × gemma4`, strict 0/5. Inside the first 8% of a single generation
the model composed a complete, correct commons-csv rewrite — 169 lines, later extracted from the
capture and run against the task's own verifier: **4 of 5**, a 34.3× speedup, 4 worker threads, 8
runs giving 1 distinct result, clean `mvn compile`. It then emitted the same 6,664-character
`old_string` block twenty-two more times.

`degenerate_tail` reads a 2,048-character window and needs three whole repeats inside it, so the
largest unit it can see is **682** characters. Inside any 2,048-character window this stream is not
periodic, so it correctly returned False for all 40,389 frames, and the only guard left was window
exhaustion — which fired 721 seconds later, 74% of the cell's wall clock, and discarded the whole
generation including the correct answer.

This is the same bound being raised for the same reason a second time: the module's own docstring
records raising it from 8 characters to 682 after a 260-character period was measured. A 6.7 KB unit
is a whole Java file being re-emitted.

TWO THINGS MAKE IT WORK where a wider `degenerate_tail` would not:

- **Anchored at the end.** `_smallest_period` asks "is this WHOLE string periodic", so the real answer
  the model wrote first — still sitting in the window, which is the entire point — makes it say no.
  Instead the last 512 characters are used as a probe, its previous occurrence gives the candidate
  period, and that period is then verified across three whole repeats.
- **Strided.** KMP over 32 KB on every one of 40,000 frames is not affordable; once per 2,048 new
  characters is ~76 evaluations for that stream. The cheap per-chunk check is untouched.

The notice changed too. `rumination_guard_window.txt` asserted *"That almost always means one write
was too big for a single turn"* — false here: the aborted call was `edit_file`, its payload was an
ordinary 6.3 KB and it had already finished. The model's next ten calls switched from one whole-file
write to six piecemeal edits reconstructed from memory, and that is where the fabricated
`setSkipInitialNewline` / `getHeader()` / `newNode()` came from. A notice that cannot know which call
was too big must not say (#5b), the same rule as `anchor_noline` beside it.
"""

import json
import random
import unittest
from unittest import mock

from cria import prompts, rumination
from cria.upstream import Upstream


def _nonrepeating(n: int, seed: int = 11) -> str:
    r = random.Random(seed)
    words = ["".join(r.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(r.randint(3, 10)))
             for _ in range(4000)]
    return " ".join(r.choice(words) for _ in range(n // 4))[:n]


UNIT = _nonrepeating(6664, seed=3)          # the measured repeating block, to the character
ANSWER = _nonrepeating(13000, seed=99)      # the correct answer the model wrote before it locked up


class TheMeasuredStreamIsCaughtTests(unittest.TestCase):
    def test_three_repeats_fire_and_two_do_not(self):
        for n, want in ((1, False), (2, False), (3, True), (4, True), (10, True)):
            with self.subTest(repeats=n):
                self.assertEqual(rumination.degenerate_wide(ANSWER + UNIT * n), want)

    def test_the_real_answer_in_the_window_does_not_hide_it(self):
        """THE REGRESSION a wider `degenerate_tail` would still have. 13 KB of genuine output sits in
        front of the repeats — that is what makes the case worth catching at all."""
        self.assertTrue(rumination.degenerate_wide(ANSWER + UNIT * 3))

    def test_the_cheap_check_still_cannot_see_it(self):
        """Stated as a fact about the bound, so the reason this exists stays legible."""
        self.assertFalse(rumination.degenerate_tail((ANSWER + UNIT * 22)[-2048:]))
        self.assertGreater(len(UNIT),
                           rumination.DEGENERATE_RUN_CHARS // rumination.MIN_DEGENERATE_REPEATS)

    def test_it_fires_far_earlier_than_the_window_backstop(self):
        """Three repeats is ~33 KB of stream against the 157 KB that actually ran."""
        fired_at = next(n for n in range(1, 25) if rumination.degenerate_wide(ANSWER + UNIT * n))
        self.assertLessEqual(len(ANSWER + UNIT * fired_at), 40_000)


class RealOutPutIsLeftAloneTests(unittest.TestCase):
    def test_a_large_genuine_write(self):
        self.assertFalse(rumination.degenerate_wide(_nonrepeating(40_000)))

    def test_a_real_source_file_of_similar_lines(self):
        """Source code repeats its own shape constantly; that is not a stuck stream."""
        java = "\n".join(f'    private final String field{i} = "value{i}";  // column {i}'
                         for i in range(600))
        self.assertFalse(rumination.degenerate_wide(java))

    def test_a_short_stream_is_never_judged(self):
        for n in (0, 100, rumination.WIDE_MIN_CHARS - 1):
            with self.subTest(chars=n):
                self.assertFalse(rumination.degenerate_wide("ab" * (n // 2)))

    def test_two_identical_copies_are_not_enough(self):
        """The three-whole-repeats rule is what keeps a legitimate large write safe, and it is not
        weakened by widening the window."""
        self.assertFalse(rumination.degenerate_wide(ANSWER + UNIT * 2))


class ItIsAffordableTests(unittest.TestCase):
    def test_the_stride_is_declared(self):
        self.assertGreaterEqual(rumination.WIDE_EVAL_STRIDE, 1024)

    def test_it_runs_on_a_stride_not_per_chunk(self):
        """Drive the REAL streaming reader over thousands of small frames and count how many times
        the (expensive) wide check actually runs — a source-text grep for the stride constant's
        name cannot tell "wired to the stride" from "wired to fire every frame anyway"."""
        text = _nonrepeating(60_000, seed=41)
        frag_len = 12
        frames = [{"choices": [{"index": 0, "delta": {"content": text[i:i + frag_len]}}]}
                 for i in range(0, len(text), frag_len)]
        lines = [b"data: " + json.dumps(f).encode() + b"\n" for f in frames] + [b"data: [DONE]\n"]

        class _Resp:
            def __iter__(self): return iter(lines)
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def close(self): pass

        calls = []
        real = rumination.degenerate_wide
        def counting(s):
            calls.append(len(s))
            return real(s)

        class _Rlog:
            phase = "coder"
            live_chars = 0
            def emit(self, *a, **k): pass

        up = Upstream("http://x", context_window=10_000_000)
        with mock.patch.object(rumination, "degenerate_wide", counting), \
             mock.patch("urllib.request.urlopen", return_value=_Resp()):
            out = up.chat_watched({"messages": [{"role": "user", "content": "hi"}], "model": "m"}, _Rlog())
        self.assertEqual(json.loads(out)["choices"][0]["message"]["content"], text)   # nothing lost
        self.assertGreater(len(calls), 0, "the wide check never ran at all")
        self.assertLess(len(calls) * 20, len(frames),
                        f"{len(calls)} evaluations over {len(frames)} frames is not a stride")

    def test_one_evaluation_is_cheap(self):
        import time
        big = _nonrepeating(rumination.WIDE_RUN_CHARS)
        t = time.time()
        for _ in range(100):
            rumination.degenerate_wide(big)
        self.assertLess(time.time() - t, 2.0)


class TheNoticeDoesNotGuessTests(unittest.TestCase):
    BODY = prompts.load("rumination_guard_window")

    def test_it_no_longer_asserts_a_write_was_too_big(self):
        """The aborted call was an `edit_file` whose payload was 6.3 KB and already finished."""
        self.assertNotIn("almost always means one write was too big", self.BODY)

    def test_it_states_who_stopped_the_turn_and_at_what_bound(self):
        """It used to say the turn "used up the whole of the space" and that "nothing it produced
        COULD have been kept" — both untrue. The abort fires at WINDOW_EXHAUSTED_FRACTION on a
        frame-count proxy, so roughly a twelfth of the room was still there and the discard was a
        choice made here (#5b, #14)."""
        self.assertIn("{{PERCENT}}%", self.BODY)
        self.assertIn("on this side of the model", self.BODY)
        self.assertNotIn("used up the whole of the space", self.BODY)
        self.assertNotIn("could have been kept", self.BODY)
        self.assertIn("discarded, not truncated and saved", self.BODY)

    def test_it_gives_a_next_action(self):
        self.assertIn("single tool call", self.BODY)

    def test_the_degenerate_notice_is_a_different_one(self):
        """Three detectors, three notices — the rule already written into the selection site."""
        self.assertNotEqual(self.BODY, prompts.load("rumination_guard_degenerate"))


if __name__ == "__main__":
    unittest.main()
