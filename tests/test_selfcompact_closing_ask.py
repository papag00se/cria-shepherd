"""Two fixes from the full walk of ada-handles_mellum2_codex_pon_1785628543."""
import inspect
import unittest

from cria import loop, rumination


class SelfCompactionAskTests(unittest.TestCase):
    """cria's ask must go LAST on BOTH compaction paths.

    Without it the transcript handed to the compactor ends on the coder's own step — "Do ONLY this
    step (2 of 4), then stop: Write test_resolve_handle.py ..." — and the compactor obeys that
    instead of summarizing. Call 25 of that run emitted `write_file({"path": ...` and degenerated to
    `v5v5v5...` until the token cap; call 26 produced a whole unittest file. cria then presented it
    as "⟦ctx:rollup⟧ Summary of your earlier turns this session" — a file that had never been
    written and was not on disk. The coder believed it: "The user has given me a test suite."

    da35f4e fixed exactly this on the harness path and never reached the self-compaction sibling.
    """

    def test_BOTH_paths_append_the_closing_ask(self):
        from cria import server
        self.assertIn("compact_closing_ask", inspect.getsource(server))
        self.assertIn("compact_closing_ask", inspect.getsource(loop))

    def test_the_self_compaction_call_site_carries_it(self):
        src = inspect.getsource(loop.Loop._self_compact)
        self.assertIn("compact_closing_ask", src)
        self.assertIn("selfcompact.serialize", src)   # the evidence still comes first

    def test_the_ask_forbids_code_and_tool_calls(self):
        from cria import prompts
        ask = prompts.load("compact_closing_ask")
        self.assertIn("no tool call", ask.lower())
        self.assertIn("no code", ask.lower())


class DegenerateUnitTests(unittest.TestCase):
    """The backstop tested for a single repeated CHARACTER. The real streams were two characters
    wide — `y8y8y8...` for 40,759 tokens, five minutes of a fifteen-minute run, and `v5v5v5...`
    inside the compactor. Neither was caught."""

    W = rumination.DEGENERATE_RUN_CHARS

    def test_the_measured_two_char_streams_are_caught(self):
        for unit in ("y8", "v5"):
            with self.subTest(unit=unit):
                self.assertTrue(rumination.degenerate_tail(unit * self.W))

    def test_a_single_repeated_character_still_is(self):
        self.assertTrue(rumination.degenerate_tail("y" * (self.W + 10)))

    def test_units_up_to_the_bound(self):
        for size in range(2, rumination.MAX_DEGENERATE_UNIT + 1):
            unit = "".join(chr(97 + i) for i in range(size))
            with self.subTest(size=size):
                self.assertTrue(rumination.degenerate_tail(unit * self.W))

    def test_real_output_is_NOT_flagged(self):
        # Never block a run that is genuinely producing text.
        for text in ("the quick brown fox jumps over the lazy dog. " * 200,
                     "".join(f"line {i}: value = {i * 7}\n" for i in range(400)),
                     "".join(f"    self.assertEqual(result[{i}], {i})\n" for i in range(300))):
            with self.subTest(text=text[:30]):
                self.assertFalse(rumination.degenerate_tail(text))

    def test_short_input_is_never_flagged(self):
        self.assertFalse(rumination.degenerate_tail("y8" * 10))
