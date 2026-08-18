"""The note that names an unloadable dependency only watched cria's own probes.

`proberun.dependency_note` labels a failing gate probe whose output says a dependency will not load.
It never saw the model's own `ruby -Ilib …`, `node lookup.js`, `go run .` — which is where this
actually happens.

Measured on the p3 arm: nemotron-elastic's ruby run carried `cannot load such file` **39 times** and
the note appeared **zero** times. All five checks in that cell died on one unloadable gem.

Same mistake as the read guard the day before: the door cria watches was not the door the failure
comes through.

ONLY THE MOST RECENT occurrence is annotated. Putting the same paragraph in the window 39 times is
noise on a signal the model has already read (#3), and the latest one is the turn it can act on.

The opener these assertions quote changed on 2026-08-18, from "is installed nowhere ruby is looking"
to "did not load". The old one was a claim cria had not checked and that was measurably false in the
walked run — `minitest` was on the plain-ruby load path, 5.16.3, and missing only from the bundle.
What survives is what the checker's own output established: the require failed.
"""

import pathlib
import tempfile
import unittest

from cria import prompts, writeproxy
from cria.probegate import SECTION_PREFIX


def tool(content: str) -> dict:
    return {"role": "tool", "tool_call_id": "c1", "content": content}


RUBY = "exited 1: cannot load such file -- countries (LoadError)"
NODE = "Error: Cannot find module 'commander'"


class TheCodersOwnFailureIsLabelledTests(unittest.TestCase):
    def test_the_measured_case(self):
        out = writeproxy.represent_inbound([tool(RUBY)])
        self.assertIn("`countries` did not load", out[0]["content"])

    def test_the_checkers_own_line_is_kept(self):
        out = writeproxy.represent_inbound([tool(RUBY)])
        self.assertIn("cannot load such file -- countries (LoadError)", out[0]["content"])

    def test_every_ecosystem_reaches_it(self):
        for text, marker in ((RUBY, "load path"), (NODE, "node_modules")):
            with self.subTest(output=text[:30]):
                out = writeproxy.represent_inbound([tool(text)])
                self.assertIn(marker, out[0]["content"])

    def test_only_the_most_recent_is_annotated(self):
        msgs = [tool(RUBY), tool(RUBY), tool(RUBY)]
        out = writeproxy.represent_inbound(msgs)
        noted = [m for m in out if "did not load" in m["content"]]
        self.assertEqual(len(noted), 1)
        self.assertIs(noted[0], out[-1])

    def test_it_is_not_appended_twice(self):
        once = writeproxy.represent_inbound([tool(RUBY)])
        twice = writeproxy.represent_inbound(once)
        self.assertEqual(twice[0]["content"].count("did not load"), 1)


class WhereItStaysSilentTests(unittest.TestCase):
    def test_an_ordinary_failure_gets_nothing(self):
        out = writeproxy.represent_inbound([tool("exited 1: cart.go:12:2: undefined: foo")])
        self.assertNotIn("Note:", out[0]["content"])

    def test_a_gate_result_is_left_to_the_gate(self):
        """proberun.dependency_note already speaks for those — two notes on one result is noise."""
        out = writeproxy.represent_inbound([tool(f"{SECTION_PREFIX}probe-0___\n{RUBY}")])
        self.assertNotIn("installed nowhere", out[0]["content"])

    def test_the_projects_own_module_is_not_called_a_dependency(self):
        with tempfile.TemporaryDirectory() as ws:
            pathlib.Path(ws, "shipping").mkdir()
            out = writeproxy.represent_inbound(
                [tool("ModuleNotFoundError: No module named 'shipping'")], workspace_root=ws)
            self.assertNotIn("Note:", out[0]["content"])

    def test_a_third_party_name_still_gets_the_note_with_a_workspace(self):
        with tempfile.TemporaryDirectory() as ws:
            pathlib.Path(ws, "app.py").write_text("x = 1\n")
            out = writeproxy.represent_inbound(
                [tool("ModuleNotFoundError: No module named 'requests'")], workspace_root=ws)
            self.assertIn("Note:", out[0]["content"])

    def test_an_assistant_turn_is_never_touched(self):
        msgs = [{"role": "assistant", "content": RUBY}]
        self.assertEqual(writeproxy.represent_inbound(msgs)[0]["content"], RUBY)


class TheNotesHaveOneOwnerTests(unittest.TestCase):
    def test_both_paths_render_the_same_prompt_file(self):
        notes = prompts.load_map("dependency_note")
        out = writeproxy.represent_inbound([tool(RUBY)])[0]["content"]
        self.assertIn(notes["ruby"].split("{{NAME}}")[-1][:40], out)


if __name__ == "__main__":
    unittest.main()
