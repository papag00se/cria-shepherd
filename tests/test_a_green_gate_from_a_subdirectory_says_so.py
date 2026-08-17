"""cria ran every check inside `toml-cli/`, reported green, and never mentioned the folder.

Cycle 4 cell 6, rust-toml-cli x gemma4, a from-scratch task with no seed. The model ran
`cargo new toml-cli` and built a complete, working Rust project inside that subdirectory. cria's own
gate cd'd into it for four of its five probes — `cargo check`, `cargo clippy` twice, `cargo test` —
they all passed, the gate went GREEN, the completion critic approved, and the session exited
normally.

The verifier runs `cargo` at the working directory:

    error: could not find `Cargo.toml` in /tmp/suite-rust-toml-cli_… or any parent directory

**0 of 4, on a cell that had scored 4/4 for three cycles running.**

cria was holding the fact the entire time. `working_dir=toml-cli` is on every probe it composed; it
is in the plan, not inferred, not judged. It just never reached the coder — the green line says "the
repo's own checks that ran reported no error-class problems" and stops.

NOT A JUDGEMENT ABOUT LAYOUT. A monorepo puts manifests in subdirectories on purpose and is right
to. This fires only when NO real check could run at the root, which is exactly the case where the
directory the harness handed the model contains no buildable project at all. The syntax floor is
excluded because it walks the tree from the root by construction and would make the check
permanently silent.
"""

import os
import pathlib
import tempfile
import unittest

from cria import probegate
from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind


def cand(kind, cwd):
    return ProbeCandidate(kind=kind, command=["cargo", "check"], working_dir=cwd, confidence=90,
                          expected_value=90, cost=ProbeCost.Moderate, mutates_code=False,
                          may_hang=False, may_need_services=False, reason="t")


class TheFactIsReadOffThePlanTests(unittest.TestCase):
    def test_the_measured_layout(self):
        with tempfile.TemporaryDirectory() as d:
            sub = pathlib.Path(d) / "toml-cli"
            sub.mkdir()
            (sub / "Cargo.toml").write_text('[package]\nname = "toml-cli"\nversion = "0.1.0"\n')
            (sub / "src").mkdir()
            (sub / "src" / "main.rs").write_text("fn main() {}\n")
            plan = probegate.plan_gate(d)
            self.assertEqual(plan.ran_in, "toml-cli")

    def test_a_project_at_the_root_says_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
            (root / "src").mkdir()
            (root / "src" / "main.rs").write_text("fn main() {}\n")
            self.assertEqual(probegate.plan_gate(d).ran_in, "")

    def test_two_disagreeing_subdirectories_say_nothing(self):
        """A real monorepo. cria has nothing single to point at, so it points at nothing."""
        d = tempfile.gettempdir()
        self.assertEqual(probegate._checks_ran_elsewhere(
            d, [cand(ProbeKind.BuildCheck, os.path.join(d, "a")),
                cand(ProbeKind.Test, os.path.join(d, "b"))]), "")

    def test_the_syntax_floor_is_not_counted(self):
        """It walks from the root by construction, so counting it would silence this forever."""
        d = tempfile.gettempdir()
        self.assertEqual(probegate._checks_ran_elsewhere(
            d, [cand(ProbeKind.SyntaxCheck, d), cand(ProbeKind.BuildCheck, os.path.join(d, "sub"))]),
            "sub")

    def test_anything_running_at_the_root_says_nothing(self):
        d = tempfile.gettempdir()
        self.assertEqual(probegate._checks_ran_elsewhere(
            d, [cand(ProbeKind.Lint, d), cand(ProbeKind.BuildCheck, os.path.join(d, "sub"))]), "")

    def test_no_candidates_says_nothing(self):
        self.assertEqual(probegate._checks_ran_elsewhere(tempfile.gettempdir(), []), "")

    def test_no_workspace_says_nothing(self):
        self.assertEqual(probegate._checks_ran_elsewhere("", [cand(ProbeKind.Test, "/x")]), "")


class ItReachesTheCoderOnTheGreenBranchTests(unittest.TestCase):
    """The green gate is where it matters: a red one gives the coder work that will lead it to the
    layout anyway, and a green one is the most expensive green there is."""

    def _out(self, ran_in):
        plan = probegate.GatePlan(workspace=tempfile.gettempdir(),
                                  candidates=[cand(ProbeKind.Lint, tempfile.gettempdir())])
        plan.ran_in = ran_in
        return probegate.clean_gate_output("___CRIA_GATE_probe-0___\nclean\nEXIT:0\n", plan)

    def test_the_folder_is_named(self):
        out = self._out("toml-cli")
        self.assertIn("no error-class problems", out)
        self.assertIn("toml-cli", out)
        self.assertIn("working directory", out)

    def test_silence_when_there_is_nothing_to_say(self):
        self.assertNotIn("working directory you were given", self._out(""))

    def test_it_never_names_the_shim(self):
        import re
        self.assertIsNone(re.search(r"\bcria\b", self._out("toml-cli"), re.I))


if __name__ == "__main__":
    unittest.main()
