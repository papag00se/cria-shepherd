"""The gate states which of its own bytes the model may see, instead of being recognised later.

Nine regexes used to answer "is this cria's own text?" by reading it. They were patched three times
in one day — for a wrapper that spans lines, then for cria's own inline programs, then for the litter
heredoc — each time because cria had grown a new kind of self-authored text no pattern had heard of.
Every patch was correct and none was the fix: a reader cannot recognise text an author has not
written yet (#4, #12).

`plan_gate` knows. It has the candidate list in front of it, with discovery's own word on which argv
came off the project and which cria composed. It stamps that list into the script, the way
`writeproxy` has stamped every lowered tool call since it was written — in the command, so it
survives a restart, a compaction, and any re-render of the history.

These tests are about the stamp itself. What it protects — the wrapper, the parse floor, the litter
leg, the offline re-run — is measured in the files named for those incidents.
"""

import pathlib
import tempfile
import unittest

from cria import probegate


class TheStampSaysItTests(unittest.TestCase):
    def test_a_gate_declares_exactly_the_probes_the_coder_could_retype(self):
        ws = tempfile.mkdtemp()
        pathlib.Path(ws, "go.mod").write_text("module x\n\ngo 1.21\n")
        pathlib.Path(ws, "main.go").write_text("package main\nfunc main(){}\n")
        plan = probegate.plan_gate(ws)
        shown = probegate.gate_probes_of(plan.script)
        self.assertEqual(shown, [" ".join(c.command) for c in plan.candidates
                                 if not c.composed_by_cria])
        self.assertIn("go test -count=1 -v ./...", shown)

    def test_it_is_the_first_line_so_a_cut_command_still_carries_it(self):
        ws = tempfile.mkdtemp()
        pathlib.Path(ws, "Cargo.toml").write_text('[package]\nname="x"\nversion="0.1.0"\n')
        pathlib.Path(ws, "src", "lib.rs").parent.mkdir()
        pathlib.Path(ws, "src", "lib.rs").write_text("pub fn f() {}\n")
        script = probegate.plan_gate(ws).script
        self.assertTrue(script.splitlines()[0].startswith("# " + probegate.GATE_SENTINEL))

    def test_argv_that_would_break_a_pattern_survives_the_round_trip(self):
        """Quotes, newlines, a regex, an em dash — it is base64 of JSON, not text to be re-read."""
        probes = ["pytest -q -k 'not slow'", 'go test -run "^Test(A|B)$"',
                  "sh -c 'echo \"a\nb\"'", "cargo test — vérifié"]
        self.assertEqual(probegate.gate_probes_of(probegate._gate_sentinel(probes)), probes)


class WhenThereIsNoStampTests(unittest.TestCase):
    """Unknown must fail toward silence. The cost of guessing "this is the coder's" wrongly is cria's
    own plumbing reaching the model as the coder's own work — the harm every one of these files was
    written for. The cost of guessing the other way is one gate the model does not see the argv of,
    while its findings arrive exactly as before."""

    def test_an_unstamped_command_shows_nothing(self):
        self.assertIsNone(probegate.gate_probes_of("cd /ws && pytest -q\necho done"))
        self.assertEqual(probegate._strip_gate_plumbing("cd /ws && pytest -q"), "")

    def test_a_stamp_cut_in_transit_shows_nothing(self):
        good = probegate._gate_sentinel(["pytest -q"])
        self.assertIsNone(probegate.gate_probes_of(good[:len(good) - 6]))

    def test_a_stamp_that_is_not_a_list_shows_nothing(self):
        import base64
        import json
        bad = "# " + probegate.GATE_SENTINEL + base64.b64encode(
            json.dumps({"cmd": "pytest -q"}).encode()).decode()
        self.assertIsNone(probegate.gate_probes_of(bad))


if __name__ == "__main__":
    unittest.main()
