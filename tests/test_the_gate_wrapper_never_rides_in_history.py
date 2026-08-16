"""cria's capture wrapper is reduced to the command inside it before the model re-reads it.

`_strip_gate_plumbing` promised to keep "only the real probe commands the model might care about".
It dropped whole LINES matching four scaffolding patterns — but the capture wrapper is ONE line with
the real command inside it, so every probe line rode through complete.

Measured on one day of real prompts: **131,946 occurrences** of cria's own variable names across
1,433 coder prompts — 6.1% of every byte cria sent the coder, 31.6% of the worst single prompt.

Three harms, one cause:
  * three different models COPIED the wrapper into their own commands (21 responses, 5 sessions; one
    reproduced the entire four-probe gate script including the offline leg), and a copy always exits
    0 because its last statement is a `printf` — so a failed command reports success;
  * the repetition detector's fingerprint drowned — the boilerplate contributes ~35 shared words
    against a real command's 1–4, so `cat main.go` matched `mv cart.go .`, three live fires;
  * the steer author's transcript, defanged precisely so there is "nothing a model can COPY",
    carried 557 characters of runnable shell per call.

The matcher is anchored on the wrapper's SHAPE, not on cria's variable names, so renaming them
cannot silently turn this back off.
"""

import unittest

from cria import probediscovery, probegate, proberun


def composed(command, wd="/tmp/ws", timeout_s=240):
    c = probediscovery.ProbeCandidate(
        kind=probediscovery.ProbeKind.Test, command=command, working_dir=wd, confidence=1,
        expected_value=1, cost=probediscovery.ProbeCost.Cheap, mutates_code=False,
        may_hang=False, may_need_services=False, reason="t")
    return proberun.compose_probe_command(c, timeout_s)


class TheRealCommandSurvivesAndNothingElseTests(unittest.TestCase):
    CASES = [
        (["python3", "-m", "pytest", "-q"], "python3 -m pytest -q"),
        (["go", "test", "-count=1", "./..."], "go test -count=1 ./..."),
        (["cargo", "test", "--no-fail-fast"], "cargo test --no-fail-fast"),
        (["npm", "test"], "npm test"),
        (["mvn", "-q", "test"], "mvn -q test"),
    ]

    def test_each_language_keeps_its_command_and_drops_the_wrapper(self):
        for argv, want in self.CASES:
            with self.subTest(cmd=want):
                out = probegate._strip_gate_plumbing(composed(argv))
                self.assertEqual(out, want)

    def test_the_token_is_gone_in_every_case(self):
        for argv, _ in self.CASES:
            self.assertNotIn("cria", probegate._strip_gate_plumbing(composed(argv)).lower())

    def test_it_is_the_bulk_of_the_bytes(self):
        raw = composed(["python3", "-m", "pytest", "-q"])
        out = probegate._strip_gate_plumbing(raw)
        self.assertGreater(len(raw), 400)
        self.assertLess(len(out), 40)

    def test_the_shape_not_the_name_is_what_is_matched(self):
        """A rename of cria's variables must not turn this off — that is how the leak survived."""
        raw = composed(["python3", "-m", "pytest", "-q"]).replace("__cria_", "__p_")
        self.assertEqual(probegate._strip_gate_plumbing(raw), "python3 -m pytest -q")


class ItStillDropsWhatItAlwaysDroppedTests(unittest.TestCase):
    def test_a_plain_command_is_untouched(self):
        self.assertEqual(probegate._strip_gate_plumbing("pytest -q"), "pytest -q")

    def test_scaffolding_only_reduces_to_nothing(self):
        from cria.probegate import SECTION_PREFIX, SECTION_SUFFIX
        only = f"echo {SECTION_PREFIX}probe-0{SECTION_SUFFIX}"
        self.assertEqual(probegate._strip_gate_plumbing(only), "")

    def test_a_real_composed_gate_keeps_only_its_probe_commands(self):
        """End to end on what plan_gate actually builds, not a hand-written line."""
        script = probegate.plan_gate("").script
        out = probegate._strip_gate_plumbing(script)
        self.assertNotIn("cria", out.lower())
        self.assertNotIn("</dev/null", out)

    def test_the_litter_bookkeeping_is_still_removed(self):
        out = probegate._strip_gate_plumbing(composed(["pytest", "-q"]))
        for var in ("__cria_pre", "__cria_post", "__cria_new", "__cria_out", "__cria_ec"):
            self.assertNotIn(var, out)


if __name__ == "__main__":
    unittest.main()
