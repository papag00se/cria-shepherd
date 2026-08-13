"""cria refuses a 9,001-byte file read and let a command print 302,983 tokens.

`read_file` over `READ_INLINE_MAX` (9,000 bytes) is refused, with the coder told to grep or read a
line range instead. The coder's own `exec_command` had no bound at all — the guard was built for
cria's synthetic tools and the harness's shell was never on the same table.

Measured across the battery: **71 of 538 command results (13%) are larger than the limit cria
enforces on a file read**, and the harness had ALREADY blind-clipped 10 of them, stamping
"Warning: truncated output" — the silent truncation principle 5 exists to prevent, arriving through
a door cria was not watching.

The measured harm, gemma4's Java run: the coder wanted to know whether its importer crashed, ran it
over the 120,000-row feed with per-item printing, and got 879 lines back. That pushed the session
over the compaction trigger, which destroyed the notes of the step it had just finished. It then ran
the identical command six calls later.

NO ELISION AND NO TRUNCATION, ON ANY PATH (operator ruling). The first cut of this kept a head and
a tail and stated the loss. That is still a partial view the model reasons over as if it held the
relevant part, and stating the size of a clip does not make it actionable. read_file has
refused-and-redirected all along; this puts the coder's own shell, and the directory listing, on the
same footing.

The exit status survives because it is the harness's envelope, not a slice of the output — a
distinct fact about the run, and usually the real answer to the question that produced the flood.
"""

import unittest

from cria import prompts, writeproxy
from cria.writeproxy import READ_INLINE_MAX, _bounded_exec_result


def result(n_lines: int, prefix: str = "SKU", exit_code: int = 0) -> str:
    body = "\n".join(f"{prefix}-{i:05d} imported ok" for i in range(n_lines))
    return f"Chunk ID: be2fc9\nWall time: 0.9s\nProcess exited with code {exit_code}\nOutput:\n{body}"


class AnOversizedResultIsBoundedTests(unittest.TestCase):
    def test_the_measured_case_shrinks(self):
        out = _bounded_exec_result(result(879))
        self.assertLess(len(out), READ_INLINE_MAX)

    def test_the_exit_code_survives(self):
        """The most load-bearing line in any command result."""
        out = _bounded_exec_result(result(900, exit_code=1))
        self.assertIn("Process exited with code 1", out)

    def test_NO_output_survives_not_even_the_ends(self):
        """The ruling: refuse, do not elide. A head and tail is still a partial view."""
        out = _bounded_exec_result(result(900))
        self.assertNotIn("SKU-00000", out)
        self.assertNotIn("SKU-00450", out)
        self.assertNotIn("SKU-00899", out)

    def test_it_says_nothing_was_cut(self):
        """The distinction that makes it honest: discarded whole, not clipped."""
        out = _bounded_exec_result(result(900))
        self.assertIn("Nothing was truncated", out)
        self.assertIn("discarded, not cut", out)

    def test_the_size_is_stated(self):
        out = _bounded_exec_result(result(900))
        self.assertRegex(out, r"[\d,]+ bytes over [\d,]+ lines")

    def test_it_names_the_next_action(self):
        """A refusal with no route is how the read guard would have failed too."""
        out = _bounded_exec_result(result(900))
        for route in ("grep", "head -50", "> out.txt"):
            with self.subTest(route=route):
                self.assertIn(route, out)

    def test_it_offers_counting_as_well_as_filtering(self):
        """Often the question was "how many", which needs no output at all."""
        self.assertIn("wc -l", _bounded_exec_result(result(900)))


class WhatMustPassThroughUntouchedTests(unittest.TestCase):
    def test_a_small_result_is_identical(self):
        small = result(5)
        self.assertEqual(_bounded_exec_result(small), small)

    def test_a_result_at_the_limit_is_identical(self):
        """Same constant as the read guard — one owner for 'too big to hand over'."""
        body = "x" * (READ_INLINE_MAX - 100)
        r = f"Process exited with code 0\nOutput:\n{body}"
        self.assertEqual(_bounded_exec_result(r), r)

    def test_a_few_very_long_lines_are_refused_too(self):
        """Shape does not matter once it is over the limit — there is no clip to get wrong."""
        r = "Process exited with code 0\nOutput:\n" + "\n".join(["y" * 5000] * 4)
        out = _bounded_exec_result(r)
        self.assertNotIn("yyyy", out)
        self.assertIn("too much to return", out)

    def test_an_empty_result_is_untouched(self):
        self.assertEqual(_bounded_exec_result(""), "")

    def test_output_with_no_envelope_is_still_refused(self):
        out = _bounded_exec_result("\n".join(f"line {i}" for i in range(2000)))
        self.assertLess(len(out), READ_INLINE_MAX)
        self.assertIn("too much to return", out)
        self.assertNotIn("line 1000", out)


class ItUsesTheSameLimitAsTheReadGuardTests(unittest.TestCase):
    def test_one_owner_for_the_size(self):
        from cria import content_reduce
        self.assertEqual(READ_INLINE_MAX, content_reduce.INLINE_RESULT_MAX_BYTES)

    def test_the_refusals_live_in_a_prompt_file(self):
        m = prompts.load_map("oversize_refusal")
        for key in ("exec", "list"):
            with self.subTest(route=key):
                self.assertTrue(m.get(key, "").strip())

    def test_neither_refusal_names_the_program(self):
        for key, text in prompts.load_map("oversize_refusal").items():
            with self.subTest(route=key):
                self.assertNotIn("cria", text.lower())

    def test_no_read_path_elides_any_more(self):
        """The ruling applies to every path, so no composed read command may clip."""
        import inspect
        from cria import writeproxy as w
        for fn in (w._list_command, w._read_command, w._ranged_read):
            with self.subTest(fn=fn.__name__):
                src = inspect.getsource(fn)
                self.assertNotIn("head -c", src)
                self.assertNotIn("tail -c", src)


class ASizeRefusalExitsZeroTests(unittest.TestCase):
    """A non-zero exit on a read means one thing to a small model: the path is not there.

    Operator ruling, 2026-08-12: *"You must still use an exit code of 0 or the weak model will
    assume something like the file doesn't exist."* The call did not fail — cria declined to hand
    over the bytes — so nothing may claim it failed. That is a lie about the WORLD, which is worse
    than the success-stamp the blocked-call owner exists to prevent, which is a lie about the CALL.
    """

    def _run(self, cmd, cwd):
        import subprocess
        return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, cwd=cwd)

    def setUp(self):
        import tempfile, pathlib
        self.ws = tempfile.mkdtemp()
        pathlib.Path(self.ws, "big.txt").write_text("x" * (READ_INLINE_MAX * 3))
        pathlib.Path(self.ws, "small.txt").write_text("hello\n")
        for i in range(600):
            pathlib.Path(self.ws, f"f{i}.txt").write_text("y")

    def test_an_oversized_read_exits_zero(self):
        r = self._run(writeproxy._read_command({"path": "big.txt"}), self.ws)
        self.assertEqual(r.returncode, 0)

    def test_an_oversized_listing_exits_zero(self):
        r = self._run(writeproxy._list_command({"path": "."}), self.ws)
        self.assertEqual(r.returncode, 0)

    def test_both_still_carry_the_denied_mark(self):
        """Exit 0 is for the model. cria's own readers must still know no content came back."""
        from cria import denial
        for cmd in (writeproxy._read_command({"path": "big.txt"}),
                    writeproxy._list_command({"path": "."})):
            with self.subTest(cmd=cmd[:40]):
                self.assertTrue(denial.is_denied(self._run(cmd, self.ws).stdout))

    def test_a_file_that_really_is_missing_still_exits_non_zero(self):
        """The distinction: the world is wrong here, not just the size."""
        r = self._run(writeproxy._read_command({"path": "nope.txt"}), self.ws)
        self.assertNotEqual(r.returncode, 0)

    def test_a_normal_read_is_unaffected(self):
        r = self._run(writeproxy._read_command({"path": "small.txt"}), self.ws)
        self.assertEqual((r.returncode, r.stdout), (0, "hello\n"))


if __name__ == "__main__":
    unittest.main()
