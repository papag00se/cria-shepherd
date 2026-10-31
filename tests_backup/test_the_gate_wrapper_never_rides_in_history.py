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

There is no matcher any more. The strip does not READ the wrapper, it reads the list of probe
commands `plan_gate` stamped into the script when it composed it — so a rename of cria's variables,
a new internal leg, or a wrapper that spans lines cannot turn this back off, because none of them is
ever consulted. That is what the four patched patterns were reaching for and never got.
"""

import unittest

from cria import probediscovery, probegate, proberun


def composed(command, wd="/tmp/ws", timeout_s=240):
    """The gate script for one probe, exactly as cria builds it: the stamp naming what the model may
    see, then the capture wrapper it may not."""
    return probegate._gate_sentinel([" ".join(command)]) + "\n" + wrapped(command, wd, timeout_s)


def wrapped(command, wd="/tmp/ws", timeout_s=240):
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
        self.assertGreater(len(wrapped(["python3", "-m", "pytest", "-q"])), 100)
        self.assertLess(len(out), 40)

    def test_nothing_about_the_wrapper_is_load_bearing(self):
        """A rename of cria's variables must not turn this off — that is how the leak survived. Now
        it cannot: rename them, add a leg, split it over lines; the strip never looked."""
        for mutate in (lambda r: r.replace("__cria_", "__p_"),
                       lambda r: r + "\n__cria_brand_new_leg=$(date)",
                       lambda r: r.replace("; ", ";\n")):
            with self.subTest(mutation=mutate(composed(["true"]))[:0] or "mutated"):
                raw = mutate(composed(["python3", "-m", "pytest", "-q"]))
                self.assertEqual(probegate._strip_gate_plumbing(raw), "python3 -m pytest -q")


class ItStillDropsWhatItAlwaysDroppedTests(unittest.TestCase):
    def test_the_coders_own_command_is_untouched(self):
        """At the caller, which is where it matters: a shell call the CODER made passes through
        byte-identical. (The strip itself is only ever handed a gate; asked about anything else it
        answers "not mine, nothing to show" — the safe direction, since the cost of guessing wrong
        is cria's own plumbing reaching the model as the coder's work.)"""
        import json
        mine = {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "exec_command", "arguments": json.dumps({"cmd": "pytest -q tests/test_cart.py"})}}]}
        out = probegate.clean_gate_results([mine])
        self.assertEqual(out, [mine])
        self.assertEqual(probegate._strip_gate_plumbing("pytest -q"), "")

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

class TheTestExitCodeAndTheOfflineLegNeverRideEitherTests(unittest.TestCase):
    """Two lines survived the strip for as long as it has existed, and a walked run measured what
    they cost: 340 copies of `__cria_test_ec=$__cria_ec` and 170 of the offline re-run across one
    run's coder prompts — 2.7% of every byte cria sent the model, and the longest single leak was
    3,969 characters in one prompt.

    Both are cria's own bookkeeping. The offline leg's single product is a SENTENCE for the judge
    ("these same tests also pass with the network gone"); it reaches the model through the checks
    summary, never as shell. This is the same harm the strip was built for — three models copied the
    wrapper back into their own commands, and the repetition detector's fingerprint drowned in the
    boilerplate."""

    def test_the_saved_test_exit_code_is_dropped(self):
        script = "\n".join([probegate._gate_sentinel(["bundle exec rspec"]),
                            f"{proberun.TEST_EC_VAR}=$__cria_ec", "bundle exec rspec"])
        self.assertEqual(probegate._strip_gate_plumbing(script).splitlines(), ["bundle exec rspec"])

    def test_the_offline_re_run_is_dropped(self):
        offline = (f"cd /ws && if [ \"${{{proberun.TEST_EC_VAR}:-1}}\" -eq 0 ] && "
                   "unshare -rnm -- sh -c 'mount --bind /ws /ws' >/dev/null 2>&1; then :; fi")
        script = "\n".join([probegate._gate_sentinel(["pytest -q"]), "pytest -q", offline])
        self.assertEqual(probegate._strip_gate_plumbing(script), "pytest -q")

    def test_a_real_composed_gate_keeps_only_the_probe_commands(self):
        """End to end on what plan_gate builds for a repo with a test probe — the case where both
        lines are actually emitted."""
        import pathlib
        import subprocess
        import tempfile
        ws = tempfile.mkdtemp()
        pathlib.Path(ws, "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n")
        pathlib.Path(ws, "test_a.py").write_text("def test_a():\n    assert True\n")
        subprocess.run(["git", "init", "-q", ws], check=True)
        from cria import wsview
        view = wsview.View(ws, "s-strip")
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)
        raw = subprocess.run(["bash", "-c", wsview.survey_command("s-strip")], cwd=ws,
                             capture_output=True, text=True).stdout
        wsview.apply_survey(view, wsview.strip_survey(raw)[1])
        out = probegate._strip_gate_plumbing(probegate.plan_gate(ws, "s-strip").script)
        self.assertNotIn("__cria_", out)
        self.assertNotIn("unshare", out)
        self.assertNotIn("cria", out.lower())



if __name__ == "__main__":
    unittest.main()
