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
    def test_the_two_measured_turns_are_recognised(self):
        d = pathlib.Path.home()/".cria"/"calls"/"20260801T160104-019fbf8f-40be-7f53-a1c0-881700caf8e7"
        if not d.is_dir():
            self.skipTest("captures not present on this machine")
        hits = 0
        for r in sorted(d.glob("*-coder-*.response.json")):
            try: msg = json.load(r.open())["choices"][0]["message"]
            except Exception: continue
            if msg.get("tool_calls"): continue
            if loop.unexecuted_write(msg.get("content") or ""): hits += 1
        self.assertGreaterEqual(hits, 2, "the two full-file paste turns must be caught")

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

    def test_the_counter_resets_each_step(self):
        import inspect
        src = inspect.getsource(loop.Loop)
        self.assertIn("sess.unexecuted_nudges = 0", src)


class BothPathsTests(unittest.TestCase):
    """A coder-turn guard that lands in one driver half and misses the other is the divergence
    that killed the search-escape on the live path. Both halves, or neither."""

    def test_the_check_is_in_BOTH_driver_halves(self):
        import inspect
        for fn in (loop.Loop._work_item, loop.Loop._gate_single_done):
            with self.subTest(fn=fn.__name__):
                src = inspect.getsource(fn)
                self.assertIn("unexecuted_write(", src)
                self.assertIn("MAX_UNEXECUTED_NUDGES", src)
