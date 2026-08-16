"""cria's gate composed probes whose output cria then threw away.

Two budgets, set independently:

    proberun.PROBE_OUTPUT_CAP_BYTES      16,384   what a probe may print
    content_reduce.INLINE_RESULT_MAX_BYTES 9,000  what cria will hand back inline

Anything landing between them was replaced by the model-facing size refusal — "too much to return,
so nothing is shown". cria's own gate parser then read that refusal, found no findings, and recorded
the check as never having run. Nobody saw the failing tests: not the coder, not the judges, not the
gate.

    ternary-bonsai/python 0034. Tool result: "[10,104 bytes over 182 lines — too much to return, so
    nothing is shown...]". The steer built on that silence: "each new `bind()` fails with 'Address
    already in use.' The output was truncated, but that's the root cause."

Seven wrong turns, and twelve consecutive gates in one cell produced nothing at all.

The fix is arithmetic, not a new mechanism: the probe's budget is DERIVED from the bound that has to
accept it, so the refusal can never fire on cria's own instrument. No exemption is added — a gate
result that always fits needs none, and exempting it would risk the raw blob riding into the
model's window on any path that does not clean it.
"""

import unittest

from cria import content_reduce, proberun, prompts, writeproxy


class TheBudgetsCannotDisagreeTests(unittest.TestCase):
    def test_a_full_probe_result_fits_the_bound_that_accepts_it(self):
        self.assertLessEqual(
            proberun.PROBE_OUTPUT_CAP_BYTES + proberun.PROBE_ENVELOPE_RESERVE_BYTES,
            content_reduce.INLINE_RESULT_MAX_BYTES)

    def test_the_cap_is_derived_not_typed(self):
        """A literal here is how the two drifted apart in the first place."""
        import inspect
        src = inspect.getsource(proberun)
        line = next(ln for ln in src.splitlines() if ln.startswith("PROBE_OUTPUT_CAP_BYTES"))
        self.assertIn("INLINE_RESULT_MAX_BYTES", line)

    def test_the_reserve_covers_the_harness_envelope(self):
        envelope = ("Chunk ID: be2fc9\nWall time: 0.9s\nOriginal token count: 41\n"
                    "Process exited with code 1\nOutput:\n" + proberun.PROBE_EXIT_SENTINEL + "1\n")
        self.assertLess(len(envelope.encode()), proberun.PROBE_ENVELOPE_RESERVE_BYTES)


class AMaximalProbeResultSurvivesTests(unittest.TestCase):
    def envelope(self, payload: str) -> str:
        return (f"Chunk ID: be2fc9\nWall time: 0.9s\nProcess exited with code 1\nOutput:\n"
                f"{payload}\n{proberun.PROBE_EXIT_SENTINEL}1")

    def test_a_result_at_the_cap_reaches_the_model_whole(self):
        body = self.envelope("x" * proberun.PROBE_OUTPUT_CAP_BYTES)
        msgs = [{"role": "tool", "tool_call_id": "t1", "content": body}]
        self.assertEqual(writeproxy.represent_inbound(msgs, None)[0]["content"], body)

    def test_the_inbound_bound_is_gone(self):
        """A flood is the context floor's problem now -- the one place window-fitting may
        lose anything (#5) -- and `content_reduce` is the lossless-first owner above it."""
        self.assertFalse(hasattr(writeproxy, "_bounded_exec_result"))


class TheComposedProbeStillDisclosesItsOwnElisionTests(unittest.TestCase):
    """Halving the budget makes the head+tail path fire more often, so its marker matters more."""

    def test_the_composed_command_carries_the_cap_and_the_marker(self):
        import types
        c = types.SimpleNamespace(command=["pytest", "-q"], working_dir="/w")
        cmd = proberun.compose_probe_command(c, 120)
        self.assertIn(str(proberun.PROBE_OUTPUT_CAP_BYTES), cmd)
        self.assertIn("elided", cmd)
        self.assertIn("head -c", cmd)
        self.assertIn("tail -c", cmd)


class TheSurvivingRefusalKeepsTheLessonTests(unittest.TestCase):
    """The `exec` fragment this class used to read is deleted — its renderer went with the exec-output
    bound on 2026-08-14, leaving a model-facing string nothing rendered. `list` is the live member of
    the same family and carries the same rule, so the lesson is pinned where it can still fire.

    THE LESSON: a runner prints its verdict LAST, so `| head -50` hides exactly what was wanted, and a
    pipe replaces the program's exit status with the filter's — in the same sentence that tells the
    coder the status is accurate (#5b). Name a route that keeps the whole answer and the real status."""

    def setUp(self):
        self.text = prompts.load_map("oversize_refusal")["list"]

    def test_head_is_never_recommended(self):
        self.assertNotIn("head -50", self.text)

    def test_the_dead_fragments_are_gone_not_merely_unused(self):
        self.assertNotIn("exec", prompts.load_map("oversize_refusal"))
        self.assertNotIn("exec_spilled", prompts.load_map("oversize_refusal"))

    def test_every_surviving_fragment_has_a_renderer(self):
        """A model-facing string nothing renders is coverage that does not exist."""
        import glob
        src = "\n".join(open(f).read() for f in glob.glob("cria/*.py"))
        for key in prompts.load_map("oversize_refusal"):
            self.assertIn(f'"oversize_refusal")["{key}"]', src, f"{key} has no renderer")


if __name__ == "__main__":
    unittest.main()
