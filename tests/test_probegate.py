"""The completion gate's transport (unified tier-0 design): compose (plan_gate) →
harness runs → interpret (interpret_gate). All checks — parse floors included — are
first-class candidates; no privileged per-language floor."""
import os
import subprocess
import tempfile
import unittest

from cria import probegate
from cria.probediscovery import ProbeKind
from cria.probegate import interpret_gate, plan_gate, split_sections
from cria.proberun import completion_block_nudge, completion_probe_digest, syntax_floor_clean


def _ws(with_pytest=True, py_body="print(1)\n"):
    t = tempfile.mkdtemp()
    with open(os.path.join(t, "x.py"), "w") as f:
        f.write(py_body)
    if with_pytest:
        with open(os.path.join(t, "pyproject.toml"), "w") as f:
            f.write("[tool.pytest.ini_options]\n")
    return t


def _sec(i, body):
    return f"{probegate.SECTION_PREFIX}probe-{i}{probegate.SECTION_SUFFIX}\n{body}\n"


def _git(h="abc123"):
    return f"{probegate.SECTION_PREFIX}git{probegate.SECTION_SUFFIX}\n{h}\n"


class PlanTests(unittest.TestCase):
    def test_plan_selects_congruent_candidates(self):
        t = _ws()
        plan = plan_gate(t)
        kinds = [c.kind for c in plan.candidates]
        self.assertIn(ProbeKind.SyntaxCheck, kinds)      # tier-0 parse floor, as a candidate
        self.assertIn(ProbeKind.Test, kinds)             # the test probe always selected
        self.assertTrue(any("pyflakes" in " ".join(c.command) for c in plan.candidates))
        for i in range(len(plan.candidates)):
            self.assertIn(f"{probegate.SECTION_PREFIX}probe-{i}", plan.script)
        self.assertIn(probegate.SECTION_PREFIX + "git", plan.script)

    def test_multi_language_workspace_gets_each_floor(self):
        t = _ws()
        with open(os.path.join(t, "app.js"), "w") as f:
            f.write("const x = 1;\n")
        with open(os.path.join(t, "y.rb"), "w") as f:
            f.write("puts 1\n")
        cands = plan_gate(t).candidates
        cmds = [" ".join(c.command) for c in cands]
        self.assertTrue(any("compileall" in c for c in cmds))    # Python floor
        self.assertTrue(any(c.startswith("node --check") for c in cmds))  # JS floor
        self.assertTrue(any(c.startswith("ruby -c") for c in cmds))       # Ruby floor — CONGRUENT

    def test_empty_workspace_arg_composes_minimal_git_only_gate(self):
        plan = plan_gate("")
        self.assertEqual(plan.candidates, [])
        self.assertNotIn("cd ", plan.script)
        self.assertIn(probegate.SECTION_PREFIX + "git", plan.script)

    def test_split_sections_roundtrip(self):
        text = "banner noise\n___CRIA_GATE_a___\nline1\nline2\n___CRIA_GATE_b___\nEXIT:0"
        self.assertEqual(split_sections(text), {"a": "line1\nline2", "b": "EXIT:0"})
        self.assertEqual(split_sections("no markers at all"), {})


class InterpretTests(unittest.TestCase):
    def _plan(self):
        return plan_gate(_ws())

    def _i(self, plan, name_frag):
        for i, c in enumerate(plan.candidates):
            if name_frag in " ".join(c.command):
                return i
        raise AssertionError(f"no candidate matching {name_frag}")

    def test_no_markers_means_did_not_run(self):
        self.assertFalse(interpret_gate(plan_gate(""), "PROBE_EXIT=0 old-style").ran)

    def test_syntax_floor_failure_blocks_with_file_line(self):
        plan = self._plan()
        result = _sec(self._i(plan, "compileall"),
                      '*** Error compiling x.py\n  File "x.py", line 3\nSyntaxError: invalid syntax\nEXIT:1') + _git()
        out = interpret_gate(plan, result)
        self.assertTrue(out.ran)
        self.assertIs(syntax_floor_clean(out.report), False)
        nudge = completion_block_nudge(out.report)
        self.assertIsNotNone(nudge)
        self.assertIn("x.py:3", nudge)                     # exact file:line, like every other tool
        self.assertEqual(out.git_state, "abc123")

    def test_syntax_failure_blocks_even_when_output_defeats_parsers(self):
        # The congruence exception: a tier-0 check that RAN red is itself the diagnosis.
        plan = self._plan()
        result = _sec(self._i(plan, "compileall"), "some unparseable garbage output\nEXIT:1") + _git()
        out = interpret_gate(plan, result)
        self.assertIsNotNone(completion_block_nudge(out.report))

    def test_failing_test_probe_blocks_with_findings(self):
        plan = self._plan()
        result = (_sec(self._i(plan, "compileall"), "EXIT:0")
                  + _sec(self._i(plan, "pytest"),
                         "FAILED tests/test_x.py::test_a - AssertionError: boom\n1 failed\nEXIT:1")
                  + _git("def456"))
        out = interpret_gate(plan, result)
        nudge = completion_block_nudge(out.report)
        self.assertIsNotNone(nudge)
        self.assertIn("tests/test_x.py", nudge)
        self.assertIn("GROUND TRUTH", nudge)

    def test_clean_gate_produces_passing_digest(self):
        plan = self._plan()
        result = (_sec(self._i(plan, "compileall"), "EXIT:0")
                  + _sec(self._i(plan, "pyflakes"), "EXIT:0")
                  + _sec(self._i(plan, "pytest"), "3 passed in 0.1s\nEXIT:0")
                  + _git("feed99"))
        out = interpret_gate(plan, result)
        self.assertIsNone(completion_block_nudge(out.report))
        self.assertIs(syntax_floor_clean(out.report), True)
        digest = completion_probe_digest(out.report)
        self.assertIn("SYNTAX FLOOR: clean", digest)
        self.assertIn("exit 0 (ran clean)", digest)

    def test_missing_probe_section_never_blocks(self):
        plan = self._plan()
        result = _sec(self._i(plan, "compileall"), "EXIT:0") + _git()
        out = interpret_gate(plan, result)
        self.assertIsNone(completion_block_nudge(out.report))  # absent test section ≠ diagnosis

    def test_launch_failure_never_blocks_but_digest_tells(self):
        plan = self._plan()
        result = (_sec(self._i(plan, "compileall"), "EXIT:0")
                  + _sec(self._i(plan, "pytest"), "bash: pytest: command not found\nEXIT:127")
                  + _git())
        out = interpret_gate(plan, result)
        self.assertIsNone(completion_block_nudge(out.report))
        self.assertIn("did NOT launch", completion_probe_digest(out.report))


class BashRoundtripTests(unittest.TestCase):
    def test_real_bash_execution_roundtrips(self):
        t = _ws(with_pytest=False)
        plan = plan_gate(t)
        proc = subprocess.run(["bash", "-c", plan.script], capture_output=True, text=True, timeout=120)
        out = interpret_gate(plan, proc.stdout)
        self.assertTrue(out.ran)
        self.assertIsNone(completion_block_nudge(out.report))   # x.py parses clean
        self.assertIs(syntax_floor_clean(out.report), True)

    def test_real_bash_broken_python_blocks(self):
        t = _ws(with_pytest=False, py_body="def broken(\n")
        plan = plan_gate(t)
        proc = subprocess.run(["bash", "-c", plan.script], capture_output=True, text=True, timeout=120)
        out = interpret_gate(plan, proc.stdout)
        nudge = completion_block_nudge(out.report)
        self.assertIsNotNone(nudge)
        self.assertIn("x.py", nudge)


if __name__ == "__main__":
    unittest.main()


class LintTierTests(unittest.TestCase):
    def test_zero_config_linters_are_congruent(self):
        # Linting is a tier, not a Python special case: each language's zero-config
        # linter is guaranteed-selected alongside its parse floor.
        t = _ws(with_pytest=False)
        with open(os.path.join(t, "go.mod"), "w") as f:
            f.write("module x\n")
        with open(os.path.join(t, "Cargo.toml"), "w") as f:
            f.write('[package]\nname = "x"\n')
        cmds = [" ".join(c.command[:3]) for c in plan_gate(t).candidates]
        self.assertTrue(any("pyflakes" in c for c in cmds))       # Python lint
        self.assertTrue(any("go vet" in c for c in cmds))         # Go lint
        self.assertTrue(any("cargo clippy" in c for c in cmds))   # Rust lint
