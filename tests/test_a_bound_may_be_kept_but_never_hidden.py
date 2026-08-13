"""cria bounded its own judges' evidence from the wrong end, and said nothing about the cut.

Bounding a prompt cria COMPOSES is allowed and deliberate — over-applying never-truncate to composed
prompts is itself a documented footgun (#5's counter-nuance, the useless-prompting sweep). None of
that is reverted here: the budgets are unchanged at 400 and 160 characters. What changes is which
half survives and whether the reader is told.

WRONG END. A test runner prints its banner first and its verdict last. One run rendered 140 of 140
pytest results to its judges as pure banner — seed line and dots. Another rendered three different
commands to one identical 164-character line and the steer said "You've run `time mvn exec:java`
three times with identical behavior".

SILENT. With no marker the reader takes the fragment for the whole. A judge shown
"-> result: ... Parallel workers are disabled - turning *" ordered the coder to change that line.
The real switch was a field named WORKERS_ENABLED, and the verifier reported "0 thread(s)".

AND THE TASK IS NOT EVIDENCE — it is the thing evidence is judged against, and cria holds no second
copy. ternary-bonsai/go was given a task ending "Stop using `float64` for mon" and ordered: "Delete
`go.mod`'s `require github.com/shopspring/decimal` line and remove its import from cart.go NOW". The
task said to ADD a third-party decimal module and not to write a custom type. Two runs lost.
"""

import unittest

from cria import selfcompact


LONG = "x" * 5000


def tool_msg(text):
    return {"role": "tool", "tool_call_id": "c1", "content": text}


def call_msg(name, args):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": name, "arguments": args}}]}


class BothEndsSurviveTests(unittest.TestCase):
    def test_a_runners_verdict_at_the_end_is_kept(self):
        run = "Run options: --seed 1\n" + ("." * 4000) + "\n2 failed, 7 passed in 0.05s"
        line = selfcompact._defanged_line(tool_msg(run))
        self.assertIn("2 failed, 7 passed", line)

    def test_the_head_is_kept_too(self):
        """A build that prints its error EARLY then a long teardown must also survive."""
        run = "error[E0432]: unresolved import `toml::Rows`\n" + ("-" * 4000) + "\ndone"
        line = selfcompact._defanged_line(tool_msg(run))
        self.assertIn("unresolved import", line)

    def test_short_output_is_untouched(self):
        line = selfcompact._defanged_line(tool_msg("Process exited with code 0\nOutput:\n7 passed"))
        self.assertEqual(line, "→ exit 0: 7 passed")

    def test_tool_arguments_keep_both_ends(self):
        args = '{"cmd": "' + "a" * 400 + "TAIL_MARKER" + '"}'
        line = selfcompact._defanged_line(call_msg("exec_command", args))
        self.assertIn("TAIL_MARKER", line)


class TheCutIsAlwaysDisclosedTests(unittest.TestCase):
    def test_a_cut_result_says_so(self):
        line = selfcompact._defanged_line(tool_msg(LONG))
        self.assertIn("elided", line)
        self.assertIn("re-read the source", line)

    def test_a_cut_argument_says_so(self):
        line = selfcompact._defanged_line(call_msg("write_file", '{"content": "' + LONG + '"}'))
        self.assertIn("elided", line)

    def test_the_marker_names_the_real_number(self):
        line = selfcompact._defanged_line(tool_msg("y" * 1000))
        self.assertIn("600 chars elided", line)

    def test_the_bound_is_not_lifted(self):
        """The composed-prompt bound stays — this is a reshape, not a never-truncate rollout."""
        line = selfcompact._defanged_line(tool_msg(LONG))
        self.assertLess(len(line), 600)

    def test_three_commands_differing_late_no_longer_collapse(self):
        """The measured java case: identical for 164 characters, different at the end."""
        base = "time mvn exec:java -Dexec.mainClass=com.example.Importer " + ("-D opt " * 30)
        lines = {selfcompact._defanged_line(call_msg("exec_command", '{"cmd": "%s%s"}' % (base, tail)))
                 for tail in ("2>&1", "> /tmp/importer_output.txt 2>&1", "> data/output.txt 2>&1")}
        self.assertEqual(len(lines), 3)


class TheRootTaskIsNeverCutTests(unittest.TestCase):
    def task(self):
        return ("Turn the cart into a billing library. Add a third-party Go decimal module and use "
                "it for every money value. " + ("Keep the CLI flags unchanged. " * 20) +
                "Stop using `float64` for money anywhere in the package.")

    def transcript(self):
        return [{"role": "user", "content": self.task()},
                call_msg("exec_command", '{"cmd": "go build ./..."}'),
                tool_msg("Process exited with code 0\nOutput:\n"),
                {"role": "user", "content": "y" * 5000}]

    def test_the_task_survives_whole(self):
        out = selfcompact.serialize(self.transcript(), defang=True)
        self.assertIn("Stop using `float64` for money anywhere in the package.", out)
        self.assertIn("Add a third-party Go decimal module", out)

    def test_only_the_first_user_turn_is_exempt(self):
        out = selfcompact.serialize(self.transcript(), defang=True)
        self.assertIn("elided", out)

    def test_a_transcript_with_no_user_turn_is_fine(self):
        out = selfcompact.serialize([tool_msg("ok")], defang=True)
        self.assertEqual(out, "→ result: ok")

    def test_the_undefanged_rendering_is_untouched(self):
        """serialize(defang=False) is the summarizer's path and keeps its verbatim contract."""
        out = selfcompact.serialize([{"role": "user", "content": "hello"}], defang=False)
        self.assertEqual(out, "user: hello")


class TheDefangingItselfStillHoldsTests(unittest.TestCase):
    """The reason this rendering exists: no syntax a weak model can copy. 717 reasoner calls showed
    imitation rising to 8% when shown 30-59 tool shapes. Disclosure must not reintroduce a template."""

    def test_no_copyable_call_syntax(self):
        line = selfcompact._defanged_line(call_msg("exec_command", '{"cmd": "pytest -q"}'))
        self.assertNotIn("exec_command(", line)
        self.assertIn("the coder called exec_command", line)

    def test_the_envelope_is_still_stripped(self):
        line = selfcompact._defanged_line(tool_msg("Chunk ID: abc\nWall time: 1s\nOutput:\nhi"))
        self.assertNotIn("Chunk ID", line)


if __name__ == "__main__":
    unittest.main()
