"""The serialized transcript cria composes for its judges and steer authors is NEVER clipped.

Renamed from `test_a_bound_may_be_kept_but_never_hidden.py`, whose premise the operator retired on
2026-08-16. The old #5 said never-truncate governed the CODER's reads and that bounding a prompt
cria composes for a judge or steer "breaks no rule"; this module kept 200 characters of head and 200
of tail per line under that licence, and disclosed the cut. The rule now reads: **cria never
truncates, for any reader**, with exactly two exceptions — de-duplication, and a model-made summary
or selection. A head+tail character bound is neither, so the bound is gone and these tests pin its
absence.

Every incident the old bound was tuned around is still a reason it was wrong, not a reason to keep it:

WRONG END. A test runner prints its banner first and its verdict last. One run rendered 140 of 140
pytest results to its judges as pure banner — seed line and dots. Another rendered three different
commands to one identical 164-character line and the steer said "You've run `time mvn exec:java`
three times with identical behavior".

THE FAILING TEST'S NAME. Cycle 3, cell 4: a 1,157-character gate result reached the steer author with
749 characters elided, and because cria's own ⟦ctx:checks⟧ preamble is 307 characters the entire
200-character head was cria talking. `test_oversize_surcharge_still_applies_to_free_shipping` landed
in the elided middle, and the steer named `test_domestic_light_parcel` instead and prescribed setting
the constant the real failing test asserts is 12.0 to 0.0.

THE VERSION NUMBERS. Cycle 3, cell 7: a search result lost 1,812 middle characters — every version
number in it — and cria ordered the coder to use `v1.32.0`, which does not exist.

FLATTENING IS ITS OWN LIE. The renderer also collapsed newlines before bounding. A compiler and a
test runner are line-oriented; cycle 3 cell 8 shows a reasoner reading `cart.go` as one line and
concluding "That's invalid syntax", then ordering a fix for a problem that did not exist.

AND THE TASK IS NOT EVIDENCE — it is the thing evidence is judged against. ternary-bonsai/go was
given a task ending "Stop using `float64` for mon" and ordered: "Delete `go.mod`'s `require
github.com/shopspring/decimal` line and remove its import from cart.go NOW". The task said to ADD a
third-party decimal module. Two runs lost.

What still shrinks this view is the two allowed exceptions, applied elsewhere: superseded write
payloads are STUBBED to their on-disk reference by `stub_old_write_args` (de-duplication), and window
fit belongs to the context floor, which is lossless-first by construction.
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


class NothingIsClippedTests(unittest.TestCase):
    def test_a_long_result_rides_whole(self):
        line = selfcompact._defanged_line(tool_msg(LONG))
        self.assertIn(LONG, line)
        self.assertNotIn("elided", line)

    def test_a_long_argument_rides_whole(self):
        line = selfcompact._defanged_line(call_msg("write_file", '{"content": "' + LONG + '"}'))
        self.assertIn(LONG, line)
        self.assertNotIn("elided", line)

    def test_a_long_user_turn_rides_whole(self):
        out = selfcompact.serialize([{"role": "user", "content": "a"},
                                     {"role": "user", "content": LONG}], defang=True)
        self.assertIn(LONG, out)

    def test_the_module_holds_no_clip_helper(self):
        """THE REGRESSION GUARD. `_bounded` was the one place a character budget could be
        reintroduced without anyone noticing; its absence is the invariant."""
        self.assertFalse(hasattr(selfcompact, "_bounded"))
        self.assertFalse(hasattr(selfcompact, "_ELIDED_FMT"))


class TheCycleThreeIncidentsTests(unittest.TestCase):
    def test_the_failing_tests_name_survives_a_real_gate_result(self):
        """Cell 4's exact shape: cria's own preamble, then the failure, then the tally. Under the
        old head+tail bound the NAME was the part that died."""
        gate = ("⟦ctx:checks⟧ the repo's own checks report these error-class problems — each is the "
                "checker's OWN message and the line it flagged; resolve what each one names with the "
                "smallest change that makes it act as the task requires, and do not edit a test that "
                "came with the repo to make it pass.\n\n" + ("- note\n" * 40) +
                "TestRates#test_oversize_surcharge_still_applies_to_free_shipping "
                "[/tmp/ws/test/test_rates.rb:23]:\nExpected: 12.0\n  Actual: 0.0\n\n"
                "7 runs, 7 assertions, 1 failures, 0 errors")
        line = selfcompact._defanged_line(tool_msg(gate))
        self.assertIn("test_oversize_surcharge_still_applies_to_free_shipping", line)
        self.assertIn("test/test_rates.rb:23", line)

    def test_version_numbers_in_the_middle_survive(self):
        body = "results:\n" + ("filler line\n" * 200) + "shopspring/decimal v1.4.0 (latest)\n" \
               + ("more filler\n" * 200)
        line = selfcompact._defanged_line(tool_msg(body))
        self.assertIn("v1.4.0", line)

    def test_newlines_survive_so_source_is_not_read_as_one_line(self):
        src = "package cartsvc\n\nimport (\n\t\"fmt\"\n)\n\nfunc Total() {}\n"
        line = selfcompact._defanged_line(tool_msg(src))
        self.assertIn("import (\n", line)
        self.assertGreater(line.count("\n"), 3)


class BothEndsSurviveTests(unittest.TestCase):
    def test_a_runners_verdict_at_the_end_is_kept(self):
        run = "Run options: --seed 1\n" + ("." * 4000) + "\n2 failed, 7 passed in 0.05s"
        line = selfcompact._defanged_line(tool_msg(run))
        self.assertIn("2 failed, 7 passed", line)

    def test_the_head_is_kept_too(self):
        run = "error[E0432]: unresolved import `toml::Rows`\n" + ("-" * 4000) + "\ndone"
        line = selfcompact._defanged_line(tool_msg(run))
        self.assertIn("unresolved import", line)

    def test_short_output_is_untouched(self):
        line = selfcompact._defanged_line(tool_msg("Process exited with code 0\nOutput:\n7 passed"))
        self.assertEqual(line, "→ exit 0: 7 passed")

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

    def test_the_root_task_keeps_its_role_prefix_off(self):
        """`whole` no longer means "uncut" — everything is uncut. It still marks the root turn."""
        out = selfcompact.serialize(self.transcript(), defang=True)
        self.assertTrue(out.startswith("the task/context said: Turn the cart"))

    def test_a_transcript_with_no_user_turn_is_fine(self):
        out = selfcompact.serialize([tool_msg("ok")], defang=True)
        self.assertEqual(out, "→ result: ok")

    def test_the_undefanged_rendering_is_untouched(self):
        """serialize(defang=False) is the summarizer's path and keeps its verbatim contract."""
        out = selfcompact.serialize([{"role": "user", "content": "hello"}], defang=False)
        self.assertEqual(out, "user: hello")


class TheDefangingItselfStillHoldsTests(unittest.TestCase):
    """The reason this rendering exists: no syntax a weak model can copy. 717 reasoner calls showed
    imitation rising to 8% when shown 30-59 tool shapes. Removing the bound must not reintroduce a
    copyable template."""

    def test_no_copyable_call_syntax(self):
        line = selfcompact._defanged_line(call_msg("exec_command", '{"cmd": "pytest -q"}'))
        self.assertNotIn("exec_command(", line)
        self.assertIn("the coder called exec_command", line)

    def test_the_envelope_is_still_stripped(self):
        line = selfcompact._defanged_line(tool_msg("Chunk ID: abc\nWall time: 1s\nOutput:\nhi"))
        self.assertNotIn("Chunk ID", line)


if __name__ == "__main__":
    unittest.main()
