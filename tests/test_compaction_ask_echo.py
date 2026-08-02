"""A briefing that quotes cria's own instruction back is not a briefing.

Measured, run 20260801T161949 (mellum2, ada-handles, 0/4). Compactor call 0062 returned cria's ask
quoted at itself; cria injected it whole. In the coder's prompt at 0063 — 68,914 chars, continuation
block 54,274 of them (79%) — "Do not emit a tool/function call" appears 145 times and "What you
should say instead" 47 times. Both are cria's words, from selfcompact_summary.txt.
"""
import unittest

from cria import prompts, selfcompact


class AskEchoTests(unittest.TestCase):
    ASK = prompts.load("selfcompact_summary")

    def test_the_measured_echo_is_dropped(self):
        line = ("You are writing a briefing, not doing the work. You have NO tools — do NOT write "
                "code, run commands, read or fetch anything, plan the next steps, and do NOT emit a "
                "tool/function call of any kind.")
        poisoned = "\n".join([line] * 145 + ["The coder fetched the spec and found GET /handles/{handle}."])
        out = selfcompact.strip_frame_echo(poisoned, self.ASK)
        self.assertNotIn("Do not emit a tool/function call", out)
        self.assertNotIn("do NOT emit a tool/function call", out)
        self.assertIn("GET /handles/{handle}", out)

    def test_an_all_echo_briefing_comes_back_empty_so_compact_fails_safe(self):
        for sentence in selfcompact._ask_sentences(self.ASK)[:3]:
            with self.subTest(sentence=sentence[:40]):
                self.assertEqual(selfcompact.strip_frame_echo(sentence, self.ASK), "")

    def test_a_real_briefing_survives_untouched(self):
        good = ("The coder resolved the handle via GET /handles/{handle} and got a 200.\n"
                "It wrote resolve_handle.py with three functions and two tests pass.\n"
                "Remaining: the live test and the README.")
        self.assertEqual(selfcompact.strip_frame_echo(good, self.ASK), good)

    def test_short_lines_are_never_dropped_on_a_coincidental_match(self):
        # A bare heading can collide with the ask by chance; a full sentence cannot.
        self.assertEqual(selfcompact.strip_frame_echo("You have NO tools", self.ASK), "You have NO tools")

    def test_frame_echo_still_works_with_no_ask_given(self):
        self.assertEqual(selfcompact.strip_frame_echo("user: hi\nreal content"), "real content")

    def test_the_refold_ask_is_covered_too(self):
        refold = prompts.load("selfcompact_refold")
        first = selfcompact._ask_sentences(refold)[0]
        self.assertEqual(selfcompact.strip_frame_echo(first, refold), "")


class WiringTests(unittest.TestCase):
    def test_both_call_sites_pass_their_own_ask(self):
        import inspect
        src = inspect.getsource(selfcompact.compact)
        self.assertIn('strip_frame_echo(summarize(summarizable), prompts.load("selfcompact_summary"))', src)
        self.assertIn('strip_frame_echo(refold(combined), prompts.load("selfcompact_refold"))', src)
