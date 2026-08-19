"""A coder turn that PASTED the file is not a claim that the step is done.

Measured over every captured coder turn: gemma4 0.0% tool-call-less turns (n=3,955), qwopus 3.4%,
qwythos 4.5%, mellum2 29.4% (192 of 653). Run 20260801T160104 call 0012 is the complete resolver
typed into chat; call 0033 is a polished rewrite with the correct endpoint. Neither was ever written.
"""
import json
import pathlib
import unittest

from cria import loop, prompts


class UnexecutedWriteTests(unittest.TestCase):
    def test_the_measured_turns_are_recognised(self):
        """Real coder turns that pasted a file instead of writing it — VENDORED.

        This used to scan a capture directory under ~/.cria/calls. The run-evidence cleanup on
        2026-08-09 deleted it and the test began SKIPPING silently, which is worse than failing:
        a measurement-backed assertion that quietly stops running is indistinguishable from one
        that passes. The two turns below are the same shape, taken from captures that survived,
        and they now live in the repo so no cleanup can disarm this again."""
        here = pathlib.Path(__file__).parent / "fixtures"
        turns = sorted(here.glob("unexecuted_write_*.json"))
        self.assertGreaterEqual(len(turns), 2, "the vendored turns are missing")
        for t in turns:
            content = json.load(t.open())["content"]
            with self.subTest(turn=t.name):
                self.assertTrue(loop.unexecuted_write(content),
                                f"{t.name} is a pasted file and must be caught")

    def test_a_pasted_file_is_caught(self):
        body = "Here is the script:\n\n```python\n" + "\n".join(
            f"line_{i} = {i}" for i in range(20)) + "\n```\n"
        self.assertTrue(loop.unexecuted_write(body))

    def test_a_short_illustrative_snippet_is_NOT(self):
        self.assertFalse(loop.unexecuted_write(
            "The bug is here:\n\n```python\nx = 1\ny = 2\n```\n\nThat is all."))

    def test_plain_prose_is_NOT(self):
        for text in ("I have finished the step; the tests pass.",
                     "Done. resolve_handle.py is written and both tests pass.",
                     ""):
            with self.subTest(text=text[:24]):
                self.assertFalse(loop.unexecuted_write(text))

    def test_an_unclosed_fence_does_not_crash_or_fire(self):
        self.assertFalse(loop.unexecuted_write("```python\nx = 1\n"))

    def test_a_long_unclosed_fence_is_still_a_pasted_file(self):
        body = "```python\n" + "\n".join(f"a{i} = {i}" for i in range(30)) + "\n```"
        self.assertTrue(loop.unexecuted_write(body))


class BoundTests(unittest.TestCase):
    def test_it_is_bounded_so_it_can_never_wedge(self):
        self.assertEqual(loop.MAX_UNEXECUTED_NUDGES, 2)
        import dataclasses
        f = {x.name: x for x in dataclasses.fields(loop.PlanSession)}
        self.assertEqual(f["unexecuted_nudges"].default, 0)

    def test_the_nudge_names_no_harness_and_no_cria(self):
        text = prompts.load("unexecuted_write_nudge")
        self.assertNotIn("cria", text.lower())
        self.assertIn("write tool call", text)

    def test_the_counter_resets_when_a_step_advances(self):
        """Driven for real: a step that just advanced must not carry a stale nudge count into the
        next one."""
        from test_loop import _body, _ctx, _plan, _Recorder, _Rlog, _toolcall
        sess = loop.PlanSession(plan=_plan(2))
        sess.unexecuted_nudges = 2
        L = loop.Loop(_ctx(_Recorder([_toolcall()]), None, _plan(2)))
        L._advance(sess, "k", _body(), 1, 2, _Rlog())
        self.assertEqual(sess.unexecuted_nudges, 0)


class BothPathsTests(unittest.TestCase):
    """A coder-turn guard that lands in one driver half and misses the other is the divergence
    that killed the search-escape on the live path. Both halves, or neither — driven for real
    rather than grepped, so a rename or refactor of either half cannot silently disarm it."""

    PASTE = ("Here is the script:\n\n```python\n"
             + "\n".join(f"line_{i} = {i}" for i in range(20)) + "\n```\n")

    def _pasted_file_completion(self):
        return {"choices": [{"message": {"role": "assistant", "content": self.PASTE},
                             "finish_reason": "stop"}]}

    def test_the_multi_step_driver_catches_a_pasted_file(self):
        from test_loop import _body, _ctx, _plan, _Recorder, _Rlog
        rlog = _Rlog()
        L = loop.Loop(_ctx(_Recorder([self._pasted_file_completion()]), None, _plan(2)))
        L._store.put("k", loop.PlanSession(plan=_plan(2)))
        L.drive(_body(), "k", None, rlog)
        self.assertIn("loop.unexecuted_write", rlog.kinds())
        self.assertGreaterEqual(L._store.get("k").unexecuted_nudges, 1)

    def test_the_plan_off_driver_catches_a_pasted_file(self):
        from cria.loop import _plan_off_session, _synthetic_plan
        from test_loop import _body, _ctx, _Recorder, _Rlog
        rlog = _Rlog()
        L = loop.Loop(_ctx(_Recorder([self._pasted_file_completion()]), None))
        sess = _plan_off_session(_synthetic_plan("build an ada handle resolver"), "")
        L._store.put("sid:k", sess)
        L.drive(_body(), "sid:k", None, rlog)
        self.assertIn("loop.unexecuted_write", rlog.kinds())
        self.assertGreaterEqual(sess.unexecuted_nudges, 1)


class NestedFenceTests(unittest.TestCase):
    """A pasted README is a ```markdown block containing ```bash blocks.

    The original toggle read the inner CLOSING fence as opening a new block, so the run of lines
    never reached the threshold and the whole file slipped through. Measured on run 20260801T232511
    (mellum2, ada-handles, 3/4): of 12 tool-call-less turns carrying a fenced block, the toggle
    caught 7 and missed 5. Four of the five were the complete README WITH its `## Installation` /
    `pip install requests pytest` section — the one thing whose absence cost that run its fourth
    point. The coder wrote it three times and never called a write tool.
    """

    README = (
        "```markdown\n"
        "# Ada Handle Resolver\n\n"
        "Resolves handles to addresses.\n\n"
        "## Installation\n\n"
        "```bash\n"
        "pip install requests pytest\n"
        "```\n\n"
        "## Running Tests\n\n"
        "```bash\n"
        "python3 -m pytest\n"
        "```\n\n"
        "## Usage\n\n"
        "```python\n"
        "from resolve_handle import resolve_handle\n"
        "result = resolve_handle('goose')\n"
        "print(result['resolved_ada_address'])\n"
        "print(result['holder_address'])\n"
        "print(result['total_handles'])\n"
        "```\n\n"
        "## Notes\n\n"
        "The live test requires network access.\n"
        "Unit tests mock the API and need none.\n"
        "Exit code is non-zero when the handle does not resolve.\n"
        "```\n"
    )

    def test_a_nested_fence_document_is_caught(self):
        self.assertTrue(loop.unexecuted_write(self.README))

    def test_it_discriminates_across_a_whole_real_run(self):
        """Every fenced, tool-call-less coder turn of one real run — pastes AND diagnostics.

        The predecessor scanned a capture directory and asserted a RATE ("at most one missed").
        The 2026-08-09 cleanup deleted that directory and the test skipped silently. Rather than
        re-point a rate assertion at different data — which would be tuning the expectation to fit
        whatever survived — the turns are vendored with the verdict each one actually gets, so the
        test now measures DISCRIMINATION: the file pastes must fire, and the diagnostic replies
        that merely quote code must not. On this run that is a clean 4/5 split, which is a stronger
        claim than the rate it replaces."""
        here = pathlib.Path(__file__).parent / "fixtures" / "fenced_no_tool_turns.json"
        turns = json.load(here.open())["turns"]
        self.assertGreater(len(turns), 5, "the vendored run is missing")
        pastes = [t for t in turns if t["is_paste"]]
        prose = [t for t in turns if not t["is_paste"]]
        self.assertTrue(pastes and prose, "a fixture with only one class proves nothing")
        for t in pastes:
            with self.subTest(paste=t["call"]):
                self.assertTrue(loop.unexecuted_write(t["content"]))
        for t in prose:
            with self.subTest(diagnostic=t["call"]):
                self.assertFalse(loop.unexecuted_write(t["content"]),
                                 "a diagnostic that quotes code is not an unsaved file")

    def test_a_short_snippet_with_a_nested_fence_is_still_NOT_caught(self):
        self.assertFalse(loop.unexecuted_write("Try:\n\n```md\n## Hi\n\n```sh\nls\n```\n```\n"))

    def test_an_unclosed_pasted_file_is_caught(self):
        # A paste cut off by the token cap never emits its closing fence.
        body = "```python\n" + "\n".join(f"line_{i} = {i}" for i in range(20))
        self.assertTrue(loop.unexecuted_write(body))

    def test_a_bare_fence_opener_still_works(self):
        body = "```\n" + "\n".join(f"row {i}" for i in range(20)) + "\n```\n"
        self.assertTrue(loop.unexecuted_write(body))

    def test_prose_with_inline_backticks_is_not_a_paste(self):
        self.assertFalse(loop.unexecuted_write(
            "The `old_string` is not in `README.md`; re-read it and try `edit_file` again."))


class SelfQuoteExemptionTests(unittest.TestCase):
    """A fence the coder copied out of cria's own prompt is not an unsaved file.

    Walked on mellum2 1786196176 calls 0013/0020: two research summaries quoted the injected
    response-shape block, the nudge fired both times — "your last message contained the file's
    contents as text" (false both times) — and the coder tried to persist cria's own schema over
    the read-only spec spill. cria holds every string it injected; identity is a comparison."""

    SHAPE = ("GET /handles/{handle} (replace in the URL path: {handle} = The Handle name) returns:\n"
             "```ts\n{\n" + "\n".join(f"  field{i}?: string;" for i in range(20)) + "\n}\n```")

    def test_a_quoted_shape_block_does_not_fire(self):
        summary = "Step 1 complete. The endpoint returns these fields:\n\n" + self.SHAPE
        self.assertFalse(loop.unexecuted_write(summary, [self.SHAPE]))

    def test_a_real_pasted_file_still_fires(self):
        pasted = "```python\n" + "\n".join(f"x{i} = {i}" for i in range(20)) + "\n```"
        self.assertTrue(loop.unexecuted_write(pasted, [self.SHAPE]))

    def test_indentation_drift_in_the_quote_still_matches(self):
        # models re-indent when quoting; the comparison is whitespace-normalized
        requoted = "\n".join("   " + l.strip() for l in self.SHAPE.splitlines())
        self.assertFalse(loop.unexecuted_write(requoted, [self.SHAPE]))

    def test_a_tiny_overlap_cannot_exempt_a_real_file(self):
        pasted = "```python\nimport os\n" + "\n".join(f"y{i} = {i}" for i in range(20)) + "\n```"
        self.assertTrue(loop.unexecuted_write(pasted, ["import os"]))

    def test_mixed_message_fires_on_the_real_file_not_the_quote(self):
        both = (self.SHAPE + "\n\nAnd here is my implementation:\n\n```python\n"
                + "\n".join(f"z{i} = {i}" for i in range(20)) + "\n```")
        self.assertTrue(loop.unexecuted_write(both, [self.SHAPE]))

    def test_the_gather_reads_the_same_ledger_the_anchor_renders(self):
        class S: fetched_pages = {"u": ("HTTP 200", "/a, /b", "the shapes text", "")}
        self.assertEqual(loop._injected_fence_texts(S()), ["the shapes text"])
