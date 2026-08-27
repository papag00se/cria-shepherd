"""A compaction digest must not silently rewrite what the model reads.

Measured on run 20260801T225200 (zaya1, ada-handles, 0/4). The context floor's per-turn digest ran
the prose stripper over a dropped turn that held the user's TASK and cria's own planner instruction:

    task,  before : "I would like you to write a Python script that accepts an Ada Handle as input
                     and resolves it to the Cardano address"
    task,  as sent: "I would like you write Python script that accepts Ada Handle input and
                     resolves it Cardano address"

    cria's ask, before : "The request above is what the WORK is — it is not addressed to you"
    cria's ask, as sent: "The request above what WORK — it not addressed you"

And one line was INVERTED, not merely degraded: cria's own fetch note "no endpoints or field names
could BE READ FROM it" became "could read it" — a statement that nothing was learned, turned into a
claim that something was.

strip_prose_text calls those words "certain-junk". `is`, `to`, `of`, `for`, `be` are not junk; they
carry the grammatical relations. The result reads as fluent English and is not, which is a worse
failure than truncation because truncation is visible.
"""
import unittest

from cria import prompts
from cria.content_reduce import content_reduce, digest_reduce, strip_prose_text


class DigestTests(unittest.TestCase):
    ASK = prompts.load("plan_closing_ask")

    def test_the_measured_corruption_is_reproducible_with_the_old_path(self):
        # If this ever stops reproducing, the finding below needs re-deriving, not deleting.
        self.assertIn("The request above what WORK", strip_prose_text(self.ASK))

    def test_the_digest_never_produces_it(self):
        out = digest_reduce(self.ASK, None, 10)
        self.assertNotIn("The request above what WORK", out)
        self.assertNotIn("it not addressed you", out)

    def test_what_survives_is_VERBATIM(self):
        # Kept whole. The caller's budget check decides whether it is carried or disclosed as
        # not-summarized; either way the words are the model's own.
        self.assertEqual(digest_reduce(self.ASK, None, 10), self.ASK)

    def test_it_does_NOT_cut(self):
        # An earlier version cut to the cap and labelled the cut. That is a truncation, and shown a
        # real example it cut mid-word out of search-result noise that should not have been in the
        # context at all. Keep-or-disclose; the size problem is fixed by removing repeats and noise.
        out = digest_reduce(self.ASK, None, 10)
        self.assertNotIn("characters of this turn omitted", out)
        self.assertNotIn("…", out.replace("—", ""))

    def test_text_that_fits_is_returned_untouched(self):
        self.assertEqual(digest_reduce(self.ASK, None, 100_000), self.ASK)

    def test_the_meaning_inverting_line_survives_intact(self):
        line = "no endpoints or field names could be read from it"
        self.assertIn("could read it", strip_prose_text(line))          # the old corruption
        self.assertIn("could be read from it", digest_reduce(line, None, 10_000))

    def test_structured_content_still_reduces_structurally(self):
        big = '{"a": ' + '"' + "x" * 4000 + '"}'
        out = digest_reduce(big, "application/json", 50)
        self.assertLess(len(out), len(big))

    def test_evidence_prose_is_NO_LONGER_word_stripped(self):
        """REVERSED 2026-08-26. The pin here read "content_reduce still serves fetched pages/tool
        output, where the trade is defensible and the text is not instruction."

        It is not defensible, for the reason this file exists: the stripper INVERTS meaning, and an
        inverted sentence in EVIDENCE misleads exactly as well as one in an instruction — cria's own
        "could be read from it" became "could read it". Rule 5 names evidence in its first line, and
        rule 5b forbids cria stating a thing the world contradicts.

        It also cost nothing to remove: across the whole capture corpus the tier fired 6 times and
        produced 0 ⟦ctx:reduced⟧ prompts. Prose that will not fit now comes back whole and the floor
        drops a turn instead — a loss that is disclosed and names what it dropped."""
        prose = ("The quick brown fox is jumping over the lazy dog in the park. " * 200)
        self.assertEqual(content_reduce(prose, None, 20), prose)


class WiringTests(unittest.TestCase):
    def test_the_context_floor_digest_uses_it(self):
        """digest_reduce is lossless-first; content_reduce word-strips prose. Drive the real note
        builder with the SAME corruption-prone text DigestTests uses, diluted by enough other
        dropped content that the budget lets it survive whole (a lone short turn is capped to a
        share of its OWN size regardless of the overall budget — see _note_cost_bound), and check
        it does survive — not stripped."""
        from cria import contextfloor
        fillers = [{"role": "user", "content": "y" * 200} for _ in range(20)]
        msgs = fillers + [{"role": "user", "content": DigestTests.ASK}]
        note = contextfloor._compacted_note(msgs, len(msgs), 100_000)["content"]
        self.assertIn(DigestTests.ASK, note)                       # verbatim — digest_reduce's contract
        self.assertNotIn("The request above what WORK", note)      # content_reduce's corruption, absent


class RepeatCollapseTests(unittest.TestCase):
    """Repeating a byte-identical result N times is not a summary of anything.

    Measured on run 20260801T225200 (zaya1): one compaction note ran to 22,149 characters across 117
    bullets of which 25 were distinct. The single line
    `{"error":"route_not_found","message":"Route not found: /info", ...}` appeared 89 times, and
    repeated bullets were 42% of the note's characters. The model had emitted the same failing curl
    in a loop; cria replayed the identical failure back at it 89 times.
    """

    def test_the_measured_case_collapses_to_one_line(self):
        from cria.contextfloor import _collapse_repeats
        err = '{"error":"route_not_found","message":"Route not found: /info"}'
        out = _collapse_repeats([(i, err) for i in range(89)])
        self.assertEqual(len(out), 1)
        self.assertIn("89 times", out[0])

    def test_it_is_LOSSLESS(self):
        from cria.contextfloor import _collapse_repeats
        err = '{"error":"route_not_found"}'
        out = _collapse_repeats([(i, err) for i in range(89)])
        self.assertTrue(out[0].startswith(err), "the original text must survive verbatim")

    def test_a_single_occurrence_gets_no_count(self):
        from cria.contextfloor import _collapse_repeats
        self.assertEqual(_collapse_repeats([(0, "only once")]), ["only once"])

    def test_distinct_digests_are_all_kept(self):
        from cria.contextfloor import _collapse_repeats
        out = _collapse_repeats([(0, "a"), (1, "b"), (2, "c")])
        self.assertEqual(out, ["a", "b", "c"])

    def test_runs_are_collapsed_separately_not_globally(self):
        # a a b a a  ->  a x2, b, a x2. Order is information; do not dedupe across the timeline.
        from cria.contextfloor import _collapse_repeats
        out = _collapse_repeats([(0, "a"), (1, "a"), (2, "b"), (3, "a"), (4, "a")])
        self.assertEqual(len(out), 3)
        self.assertIn("2 times", out[0])
        self.assertEqual(out[1], "b")
        self.assertIn("2 times", out[2])


class SearchSpillTests(unittest.TestCase):
    """Search results ride in the context as a pointer plus titles, not 20 snippets.

    Measured on the same run: one web_search for "README.md generation guide install run script
    tests" put 9,269 characters into the planner's context — npm packages, Reddit threads, jest
    configs, valkey test docs — none of it about the task, and it survived into the compaction note.
    The fetch path has spilled to the scratchpad for a long time; the search path never did.
    """

    def test_a_large_result_list_is_spilled(self):
        import os
        import tempfile

        from cria import planner_tools
        d = tempfile.mkdtemp()
        body = planner_tools.format_results("q", [
            {"title": f"Result {i}", "url": f"https://example.com/{i}",
             "description": "x" * 300} for i in range(20)])
        out = planner_tools._spill_search("readme generation guide", body, d)
        self.assertIsNotNone(out)
        self.assertLess(len(out), len(body))
        target = next(f for f in os.listdir(d) if f.startswith("search-"))
        self.assertEqual(open(os.path.join(d, target)).read(), body)   # full list still on disk

    def test_the_titles_still_ride_inline(self):
        import tempfile

        from cria import planner_tools
        body = planner_tools.format_results("q", [
            {"title": f"Findable Title {i}", "url": f"https://example.com/{i}",
             "description": "y" * 300} for i in range(20)])
        out = planner_tools._spill_search("q", body, tempfile.mkdtemp())
        self.assertIn("Findable Title 0", out)
        self.assertNotIn("yyyyyyyy", out)          # the snippet bodies do not

    def test_a_small_result_list_is_left_inline(self):
        import tempfile

        from cria import planner_tools
        body = planner_tools.format_results("q", [
            {"title": "One", "url": "https://example.com/1", "description": "short"}])
        self.assertIsNone(planner_tools._spill_search("q", body, tempfile.mkdtemp()))

    def test_no_scratchpad_means_no_spill_and_no_crash(self):
        from cria import planner_tools
        self.assertIsNone(planner_tools._spill_search("q", "x" * 9000, None))

    def test_the_dispatch_passes_the_scratchpad_through(self):
        """execute_tool must hand its scratchpad through to _web_search, or a result list large
        enough to spill has nowhere to spill to and rides the context in full — the exact
        9,269-character contamination this file's own docstring measures. Drive the real dispatch
        with a mocked search backend and check the spill actually happens."""
        import tempfile
        import unittest.mock

        from cria import planner_tools
        results = [{"title": f"Findable Title {i}", "url": f"https://example.com/{i}",
                   "description": "z" * 300} for i in range(20)]
        d = tempfile.mkdtemp()
        with unittest.mock.patch.object(planner_tools, "brave_search", return_value=results):
            out = planner_tools.execute_tool("web_search", {"query": "q"}, "/tmp", "sk", [], None,
                                             scratch=d)
        self.assertIn("Findable Title 0", out.text)   # the titles still ride inline...
        self.assertNotIn("zzzzzzzz", out.text)          # ...the snippet bodies spilled to disk


class TheJsonTierIsLosslessNow(unittest.TestCase):
    """What replaced the word-deleting JSON tier, 2026-08-26.

    `_strip_prose_nodes` compressed `message`/`text`/`body`/`details`/`note`/`description`/`summary`
    — where an API error, a test failure or a tool's own explanation lives — by deleting function
    words. Folding identical adjacent elements is rule 5's own first allowance and shrinks the case
    that actually overruns (a list saying the same thing many times) by orders of magnitude."""

    def test_repeats_fold_to_one_copy_and_a_count(self):
        from cria.content_reduce import content_reduce, est_tokens
        body = '{"rows": [' + ",".join('{"m": "the same row said again"}' for _ in range(120)) + ']}'
        out = content_reduce(body, "application/json", 200)
        self.assertLess(est_tokens(out), est_tokens(body) // 10)
        self.assertIn("the same row said again", out, "one copy survives verbatim")
        self.assertIn("120", out, "and the count says how many there were")

    def test_order_is_kept_and_only_adjacent_runs_fold(self):
        from cria.content_reduce import _fold_repeated_elements
        self.assertEqual(_fold_repeated_elements(["a", "a", "b", "a"]),
                         ["a", {"__repeated__": 2, "of": "the element above"}, "b", "a"])

    def test_distinct_elements_are_untouched(self):
        from cria.content_reduce import _fold_repeated_elements
        self.assertEqual(_fold_repeated_elements([1, 2, 3]), [1, 2, 3])

    def test_a_prose_field_keeps_its_words(self):
        from cria.content_reduce import content_reduce
        body = '{"items": [' + ",".join(
            '{"message": "the request could not be read from the server"}' for _ in range(80)) + ']}'
        self.assertIn("could not be read from the server",
                      content_reduce(body, "application/json", 20))
