"""Three places acted in the workspace and each answered "is this path inside it" differently.

The code-health audit's structure lens found it, and the operator's ruling settled what the fix was:
the DOCS were wrong, not the code — cria does run tests, linting and probes, deliberately. So the
finding is not "cria should not execute". It is that "is this safe to act on here" had three
implementations that could not agree:

  writeproxy      dirguard.is_external      LEXICAL — normpath, no disk touch
  probegate       hand-rolled realpath      resolves symlinks, private to sweep_litter
  execcheck       nothing at all            runs the coder's program with cria's own PATH
  planner_tools   its own `_within`         a fourth copy of the primitive

The two that existed were BOTH RIGHT for their own caller, and that is the trap. `is_external` must
be lexical because it answers for a write target that does not exist yet. `sweep_litter` must resolve
symlinks because deleting through a link is how you delete somebody else's files. Two correct
answers, no name for the distinction — so the site that most needed one (`execcheck`, running a
program outside the harness's sandbox) picked neither and checked nothing.

`escapes_workspace` is the named companion: resolve symlinks, for a path cria is about to ACT on.
The parent is resolved rather than the leaf, because the leaf may be the symlink being removed.

A REGRESSION THIS FILE EXISTS TO PIN. Converging `planner_tools._within` onto the owner flipped
`_within(root, root)` from True to False — resolving only the parent asks "is my container inside the
base", which is false for the base itself — and the full 3,423-test suite stayed green. The base case
had no test anywhere.
"""

import os
import tempfile
import unittest

from cria import dirguard, execcheck, planner_tools


class WhereTheTwoAnswersDifferTests(unittest.TestCase):
    """One case, and it is the case that matters for deleting and executing."""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.out = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, "sub"), exist_ok=True)
        os.symlink(self.out, os.path.join(self.ws, "link"))

    def test_a_symlink_out_is_internal_lexically_and_external_really(self):
        self.assertFalse(dirguard.is_external("link/x", self.ws))
        self.assertTrue(dirguard.escapes_workspace("link/x", self.ws))

    def test_they_agree_everywhere_else(self):
        for path in ("sub/x.txt", "../x", "/etc/passwd"):
            with self.subTest(path=path):
                self.assertEqual(dirguard.is_external(path, self.ws),
                                 dirguard.escapes_workspace(path, self.ws))


class TheOwnersContractTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.ws, "sub"), exist_ok=True)

    def test_a_path_inside_does_not_escape(self):
        self.assertFalse(dirguard.escapes_workspace("sub/x.txt", self.ws))

    def test_the_directory_itself_is_inside_itself(self):
        """THE REGRESSION. Parent-only resolution answers this False, and nothing caught it."""
        self.assertFalse(dirguard.escapes_workspace(self.ws, self.ws))
        self.assertFalse(dirguard.escapes_workspace(".", self.ws))

    def test_dot_dot_cannot_escape(self):
        self.assertTrue(dirguard.escapes_workspace("../x", self.ws))

    def test_an_absolute_path_outside_escapes(self):
        self.assertTrue(dirguard.escapes_workspace("/etc/passwd", self.ws))

    def test_a_sibling_with_a_shared_prefix_is_not_inside(self):
        self.assertTrue(dirguard.escapes_workspace(self.ws + "-other/x", self.ws))

    def test_it_fails_closed_with_no_workspace(self):
        """A path cria cannot place is a path cria must not act on (#13)."""
        self.assertTrue(dirguard.escapes_workspace("x", None))
        self.assertTrue(dirguard.escapes_workspace("", self.ws))


class TheActingSitesUseItTests(unittest.TestCase):
    def test_execcheck_refuses_a_program_argument_outside_the_workspace(self):
        """It runs the coder's program in cria's own process, outside the harness sandbox, and until
        now validated nothing at all."""
        ws = tempfile.mkdtemp()
        code, out = execcheck.run(ws, "python3 /etc/passwd")
        self.assertIsNone(code)
        self.assertIn("outside the workspace", out)

    def test_execcheck_still_runs_an_ordinary_command(self):
        self.assertEqual(execcheck.run(tempfile.mkdtemp(), "python3 -c pass")[0], 0)

    def test_the_sweep_asks_the_owner(self):
        import inspect
        from cria import probegate
        self.assertIn("dirguard.escapes_workspace", inspect.getsource(probegate.sweep_litter))

    def test_the_gathers_containment_primitive_is_the_owners(self):
        """Its POLICY is deliberately the inverse — scratchpad only, never the workspace — so only
        the primitive converged."""
        import inspect
        self.assertIn("dirguard.escapes_workspace", inspect.getsource(planner_tools._within))
        self.assertTrue(planner_tools._within("/tmp/x/y", "/tmp/x"))
        self.assertTrue(planner_tools._within("/tmp/x", "/tmp/x"))
        self.assertFalse(planner_tools._within("/tmp/xy", "/tmp/x"))


if __name__ == "__main__":
    unittest.main()
