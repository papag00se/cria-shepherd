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

    def test_exactly_ONE_place_composes_the_request(self):
        # Fixing the sibling by copying the two lines would leave a third place to forget. It was
        # the duplication that let the two paths drift apart in the first place.
        from cria import selfcompact, server
        owners = [m for m in (server, loop, selfcompact)
                  if "compact_closing_ask" in inspect.getsource(m)]
        self.assertEqual(owners, [selfcompact], "only selfcompact may name the ask")

    def test_both_paths_go_through_that_one_place(self):
        from cria import server
        self.assertIn("selfcompact.compaction_request(", inspect.getsource(server))
        self.assertIn("selfcompact.compaction_request(", inspect.getsource(loop.Loop._self_compact))

    def test_the_evidence_comes_first_and_the_ask_last(self):
        from cria import prompts, selfcompact
        out = selfcompact.compaction_request(
            [{"role": "user", "content": "do ONLY this step, then stop: write the file"}])
        ask = prompts.load("compact_closing_ask")
        self.assertTrue(out.endswith(ask), "nothing may out-recency cria's ask")
        self.assertLess(out.index("write the file"), out.index(ask))

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

    def test_any_repeating_period_is_caught_not_just_a_short_one(self):
        """The bound used to be an 8-character unit. Walked on run 1785714194 call 0014: a repeating
        run with a period of 260 burned 40,138 tokens over 255 seconds — 66% of all model time in an
        eight-minute run — and the guard returned False the whole way. It ran inside a write_file
        ARGUMENT, which the rumination watcher excludes on purpose, so nothing else could see it."""
        for size in (2, 3, 8, 64, 255, 260):
            unit = "".join(chr(97 + (i % 26)) for i in range(size))
            with self.subTest(period=size):
                self.assertTrue(rumination.degenerate_tail(unit * (self.W * 2 // size)))

    def test_a_period_needing_fewer_than_three_repeats_is_left_alone(self):
        unit = "x" + "".join(chr(97 + (i % 26)) for i in range(900))
        self.assertFalse(rumination.degenerate_tail(unit * 3))

    def test_real_output_is_NOT_flagged(self):
        # Never block a run that is genuinely producing text.
        for text in ("".join(f"the {i} quick brown foxes jumped over {i * 3} lazy dogs. "
                             for i in range(200)),
                     "".join(f"line {i}: value = {i * 7}\n" for i in range(400)),
                     "".join(f"    self.assertEqual(result[{i}], {i})\n" for i in range(300))):
            with self.subTest(text=text[:30]):
                self.assertFalse(rumination.degenerate_tail(text))

    def test_short_input_is_never_flagged(self):
        self.assertFalse(rumination.degenerate_tail("y8" * 10))


class NoHandComposedTranscriptTests(unittest.TestCase):
    """There were THREE compaction paths, not two. The third — plan-off's _summarize_single — was
    found only because the other two were unified, and it shipped no closing ask at all.
    Every path must go through the one composer."""

    def test_no_caller_composes_the_transcript_by_hand(self):
        from cria import selfcompact, server
        for mod in (loop, server):
            src = inspect.getsource(mod)
            with self.subTest(module=mod.__name__):
                self.assertNotIn("selfcompact.serialize(probegate.clean_gate_results(", src,
                                 "compose via selfcompact.compaction_request, not by hand")
        # the composer itself is the one legitimate site
        self.assertIn("probegate.clean_gate_results(messages, gate_plan)",
                      inspect.getsource(selfcompact.compaction_request))

    def test_the_summarizer_input_stubs_superseded_write_bodies(self):
        """compact() already stubs the transcript it EMITS; the summarizer's INPUT did not, so the
        model writing the briefing read every old version of every file and put them in it — and the
        briefing is prompt-leading content in the next turn. Measured on nemotron orders-api-py
        0049, where the prompt opens with a full superseded orders/db.py body and the model then
        described two different versions as "current"."""
        from cria import selfcompact
        self.assertIn("stub_old_write_args",
                      inspect.getsource(selfcompact.compaction_request))

    def test_the_plan_off_fold_goes_through_it(self):
        # `_summarize_single` is gone. The plan-off driver had a whole second copy of the compaction —
        # its own summarizer, its own refold, its own pinned task — and the two copies had each drifted
        # to hold something the other needed. There is ONE now, and the plan-off adapter delegates to
        # it, so "does the plan-off fold use the composer" is answered by there being only one fold.
        self.assertFalse(hasattr(loop.Loop, "_summarize_single"))
        self.assertIn("self._self_compact(", inspect.getsource(loop.Loop._self_compact_single))
        # (The call is multi-line now — it also passes the on-disk file list — so match the
        # composer, not the whole one-line spelling. The claim under test is unchanged: there is
        # exactly one composer and this fold goes through it.)
        self.assertIn("selfcompact.compaction_request(",
                      inspect.getsource(loop.Loop._self_compact))

    def test_the_one_fold_uses_the_compactor_ENDPOINT_not_just_its_role(self):
        # The plan-ON copy selected the compactor ROLE and then sent the call to `reasoner_chat`, so a
        # configured compactor endpoint was ignored on that path. The plan-OFF copy had this right.
        src = inspect.getsource(loop.Loop._self_compact)
        self.assertIn("self._ctx.compactor_chat or self._ctx.reasoner_chat", src)
        self.assertNotIn("summarize(self._ctx.reasoner_chat,", src)

    def test_the_one_fold_keeps_the_gate_ground_truth_override(self):
        # The plan-OFF copy never appended this — the override that stops a rollup laundering an
        # unverified "the tests pass" past cria's real last check state.
        self.assertIn("_briefing_gate_ground_truth(sess)",
                      inspect.getsource(loop.Loop._self_compact))
