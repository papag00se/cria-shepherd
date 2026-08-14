"""The exec half of the read guard is GONE. The read half stays, and here is the line between them.

`read_file` and `list_dir` are commands **cria composes**: cria decides what they print, so a size
guard in them keeps cria from ever asking the shell for more than it can hand over. That is outbound
and it is coherent. Those tests are at the bottom of this file, unchanged, including the operator's
2026-08-12 ruling that a size refusal must still exit 0 or a weak model reads it as "no such file".

The other door was the coder's OWN command output, and cria bounded that too, at the same number.
It should not have.

  * WRONG SIDE OF THE WIRE. It ran in `represent_inbound`, on a result the harness had already run,
    already captured and already applied its own truncation policy to. cria does not write the
    harness's history, so refusing there cannot prevent a harness cut — only withhold from the model
    what the harness successfully delivered.
  * THE CUT WAS NOT HAPPENING. Zero harness truncation markers across all 50 captured sessions. The
    largest tool result cria has actually sent upstream is 160,447 bytes, intact — sixteen times the
    10,000-byte limit it supposedly could not exceed. The policy is real in the harness source; it is
    not observably operating on this path.
  * THE JOB WAS ALREADY OWNED. `content_reduce` opens "MIME-aware, lossless-first reduction of a
    single oversized tool output", and the context floor is the one place window-fitting may lose
    anything (#5). A second owner answering by DISCARD was the duplicate.

Cost while it stood, cycle 1 of the 100% campaign: 24% of 1,179 command results discarded (p75 of
real output is 8,424 bytes — the bound sat at the third quartile of NORMAL); the gate blinded in 7 of
24 cells, twice reporting "the repo's automated checks pass" over a red pytest; a model unable to
read its own 389-line file by any route; and the first link in the chain that cost
`cart-billing-go x nemotron-elastic` every check.
"""

import pathlib
import tempfile
import os
import unittest

from cria import content_reduce, writeproxy
from cria.writeproxy import READ_INLINE_MAX


def result(n_lines: int, prefix: str = "SKU", exit_code: int = 0) -> str:
    body = "\n".join(f"{prefix}-{i:05d}: 4326.28 processed ok" for i in range(n_lines))
    return f"Chunk ID: be2fc9\nWall time: 0.9s\nProcess exited with code {exit_code}\nOutput:\n{body}"


class TheCodersOwnOutputReachesTheModelWholeTests(unittest.TestCase):
    """Asserted through `represent_inbound`, the real entry point. The identity function these tests
    used to call was deleted: once the bound came off it was a 33-line docstring around
    `return content`, plus a caller branch that could never be taken and a log event that could never
    fire. Pinning an identity function proves nothing about the pipeline."""

    def inbound(self, body: str) -> str:
        msgs = [{"role": "tool", "tool_call_id": "t1", "content": body}]
        return writeproxy.represent_inbound(msgs, None)[0]["content"]

    def test_a_huge_result_passes_through_untouched(self):
        """900 lines is ~19,800 bytes and used to come back as a refusal."""
        big = result(900)
        self.assertEqual(self.inbound(big), big)

    def test_the_measured_case_passes_through(self):
        """`mvn -q compile` is 9,390 bytes on the java task -- every Maven run in one session was
        discarded, and the model saw its 18 compile errors once, by accident, via bare javac."""
        r = f"Process exited with code 1\nOutput:\n{'x' * 9390}"
        self.assertEqual(self.inbound(r), r)

    def test_nothing_is_written_to_the_workspace(self):
        """A spill helper added and removed the same day wrote into the workspace from cria's own
        process -- a third naming path beside `_spill_name` and `search_spill_name`, and the one
        thing the other two deliberately avoid (#7)."""
        self.assertFalse(hasattr(writeproxy, "_spill_exec_output"))
        self.assertFalse(hasattr(writeproxy, "_bounded_exec_result"))
        with tempfile.TemporaryDirectory() as ws:
            cwd = os.getcwd()
            try:
                os.chdir(ws)
                self.inbound(result(900))
                self.assertEqual(os.listdir("."), [])
            finally:
                os.chdir(cwd)

    def test_a_small_result_is_still_identical(self):
        small = result(5)
        self.assertEqual(self.inbound(small), small)


class TheOutboundUseOfTheNumberSurvivesTests(unittest.TestCase):
    """cria still caps what its OWN composed commands print. That is the coherent half."""

    def test_the_read_guard_still_shares_the_constant(self):
        self.assertEqual(READ_INLINE_MAX, content_reduce.INLINE_RESULT_MAX_BYTES)

    def test_the_probe_composer_still_bounds_what_it_asks_for(self):
        from cria import proberun
        self.assertGreater(proberun.PROBE_OUTPUT_CAP_BYTES, 0)
        self.assertLess(proberun.PROBE_OUTPUT_CAP_BYTES, content_reduce.INLINE_RESULT_MAX_BYTES)


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
