"""The completion gate's transport (unified tier-0 design): compose (plan_gate) →
harness runs → interpret (interpret_gate). All checks — parse floors included — are
first-class candidates; no privileged per-language floor."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cria import probediscovery, probegate, proberun
from cria.probediscovery import ProbeKind
from cria.probegate import GatePlan, interpret_gate, plan_gate, split_sections
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
        with _fake_pyflakes_on_path():
            plan = plan_gate(t)
        kinds = [c.kind for c in plan.candidates]
        self.assertIn(ProbeKind.SyntaxCheck, kinds)      # tier-0 parse floor, as a candidate
        self.assertIn(ProbeKind.Test, kinds)             # the test probe always selected
        self.assertTrue(any("pyflakes" in " ".join(c.command) for c in plan.candidates))
        for i in range(len(plan.candidates)):
            self.assertIn(f"{probegate.SECTION_PREFIX}probe-{i}", plan.script)
        # The litter listing is what the gate still has to bring home besides the probes — cria
        # removes what its own checks created. The `git` sha1sum section that used to sit beside it
        # is gone: it ran on every gate and was read by nothing (see plan_gate).
        self.assertIn(probegate.SECTION_PREFIX + probegate.LITTER_SECTION, plan.script)
        self.assertNotIn(probegate.SECTION_PREFIX + "git" + probegate.SECTION_SUFFIX, plan.script)

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

    def test_empty_workspace_arg_composes_a_gate_that_asks_for_nothing_it_cannot_reach(self):
        """No workspace → no probes, no `cd`, and no bookkeeping sections either. What still rides
        is the workspace survey, which is how a rootless session ever learns anything at all."""
        plan = plan_gate("")
        self.assertEqual(plan.candidates, [])
        self.assertNotIn("cd ", plan.script)
        self.assertNotIn(probegate.SECTION_PREFIX + "git" + probegate.SECTION_SUFFIX, plan.script)
        self.assertIn("___CRIA_SURVEY_CMD___", plan.script)

    def test_split_sections_roundtrip(self):
        text = "banner noise\n___CRIA_GATE_a___\nline1\nline2\n___CRIA_GATE_b___\nEXIT:0"
        self.assertEqual(split_sections(text), {"a": "line1\nline2", "b": "EXIT:0"})
        self.assertEqual(split_sections("no markers at all"), {})


class InterpretTests(unittest.TestCase):
    def _plan(self):
        with _fake_pyflakes_on_path():
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


import contextlib


@contextlib.contextmanager
def _fake_pyflakes_on_path(script_body="import sys\nsys.exit(0)\n"):
    """A fake `pyflakes` EXECUTABLE prepended to THIS PROCESS's PATH, standing in for a real
    installed pyflakes console-script \u2014 deterministic regardless of whether this machine actually
    has pyflakes. Mutates ``os.environ['PATH']`` (restored on exit) because `program_is_installed`
    resolves against the coder's PATH at CANDIDATE-SELECTION time (`plan_gate`, in-process), not
    merely at the subprocess-execution env a caller might pass \u2014 a bare `env=` dict never reaches
    that check."""
    bin_dir = tempfile.mkdtemp()
    exe = Path(bin_dir) / "pyflakes"
    exe.write_text("#!/usr/bin/env python3\n" + script_body)
    exe.chmod(0o755)
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = bin_dir + os.pathsep + old_path
    try:
        yield bin_dir
    finally:
        os.environ["PATH"] = old_path


class PyflakesDroppedWhenAbsentTests(unittest.TestCase):
    """C39 re-review reset: the fix for the false pyflakes-absence red lives at COMPOSITION time,
    not in clean_gate_output. pyflakes is composed as the bare `pyflakes` console-script binary (like
    eslint/clippy/go-vet), so proberun.program_is_installed -- the SAME mechanism that already drops
    a confirmed-absent binary for every other zero-config tool -- drops it before it is ever composed
    into a gate script, the moment the coder's own PATH is confirmed to lack it. This machine
    genuinely has no pyflakes installed, so plan_gate()'s own real candidate list is the proof, no
    stubbing required."""

    def test_absent_pyflakes_never_becomes_a_candidate(self):
        self.assertIsNone(__import__("shutil").which("pyflakes"),
                          "this test requires a machine with no pyflakes on PATH")
        t = _ws(with_pytest=False, py_body="import os\nx = 1\n")
        plan = plan_gate(t)
        self.assertFalse(any("pyflakes" in " ".join(c.command) for c in plan.candidates))

    def test_real_composed_gate_is_clean_with_no_pyflakes_section_at_all(self):
        """The exact live coder-facing path (real bash, real plan, clean_gate_output -- the one that
        built the false-red p27 Orders prompts) with pyflakes genuinely absent from this machine:
        there is no launch-failure section to misclassify, because there is no pyflakes section."""
        t = _ws(with_pytest=False, py_body="import os\nx = 1\n")
        plan = plan_gate(t)
        proc = subprocess.run(["bash", "-c", plan.script], capture_output=True, text=True, timeout=120)
        out = interpret_gate(plan, proc.stdout)
        self.assertTrue(out.ran)
        raw = probegate.transported_result(plan) or proc.stdout
        checks = probegate.clean_gate_output(raw, plan=plan)
        self.assertIsNotNone(checks)
        self.assertNotIn("pyflakes", checks)
        self.assertIn("no error-class problems", checks.lower())

    def test_present_and_failing_pyflakes_is_still_reported(self):
        # A fake `pyflakes` EXECUTABLE prepended to PATH stands in for a REAL, installed-and-failing
        # pyflakes: composing it as a bare binary must not change what a genuine finding looks like.
        # `program_is_installed` must see it present at PLAN time too (in-process PATH), which is why
        # `plan_gate` itself runs inside the context manager, not just the subprocess.
        t = _ws(with_pytest=False, py_body="import os\nx = 1\n")
        body = ("import sys\n"
                "for f in sys.argv[1:]:\n"
                "    print(f\"{f}:1:1: undefined name 'bogus'\")\n"
                "sys.exit(1)\n")
        with _fake_pyflakes_on_path(body):
            plan = plan_gate(t)
            self.assertTrue(any("pyflakes" in " ".join(c.command) for c in plan.candidates))
            proc = subprocess.run(["bash", "-c", plan.script], capture_output=True, text=True,
                                  timeout=120)
        out = interpret_gate(plan, proc.stdout)
        nudge = completion_block_nudge(out.report)
        self.assertIsNotNone(nudge)
        self.assertIn("undefined name", nudge)
        raw = probegate.transported_result(plan) or proc.stdout
        checks = probegate.clean_gate_output(raw, plan=plan)
        self.assertIsNotNone(checks)
        self.assertIn("undefined name", checks)
        self.assertIn("report these error-class problems", checks)

    def test_the_one_gate_unsure_warmup_window_abstains_like_any_other_absent_tool(self):
        """Before the coder's PATH has ever been asked about (`toolpath.resolved` answers None,
        "unsure"), `program_is_installed` KEEPS the candidate rather than guess -- so the very first
        gate of a session can still compose a genuinely-absent pyflakes and see a real launch
        failure. This is the SAME shape ANY other zero-config tool's absence takes (bundler, cargo,
        ...) -- not a pyflakes special case -- and clean_gate_output reads it exactly like it always
        has: real exit 127, "command not found", never a repo-error claim."""
        t = tempfile.mkdtemp()
        c = probediscovery.cand(ProbeKind.Lint, ["pyflakes", "x.py"], t, 60, 80,
                                probediscovery.ProbeCost.Cheap, "test", composed_by_cria=True)
        script = proberun.compose_probe_command(c, 3.0)
        proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=15)
        self.assertIn("EXIT:127", proc.stdout)
        raw = _sec(0, proc.stdout) + _git()
        out = probegate.clean_gate_output(raw)
        self.assertIn("no usable result", out.lower())
        self.assertNotIn("report these error-class problems", out)


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


class LintTierTests(unittest.TestCase):
    def test_zero_config_linters_are_congruent(self):
        # Linting is a tier, not a Python special case: each language's zero-config
        # linter is guaranteed-selected alongside its parse floor.
        t = _ws(with_pytest=False)
        with open(os.path.join(t, "go.mod"), "w") as f:
            f.write("module x\n")
        with open(os.path.join(t, "Cargo.toml"), "w") as f:
            f.write('[package]\nname = "x"\n')
        with _fake_pyflakes_on_path():
            cmds = [" ".join(c.command[:3]) for c in plan_gate(t).candidates]
        self.assertTrue(any("pyflakes" in c for c in cmds))       # Python lint
        self.assertTrue(any("go vet" in c for c in cmds))         # Go lint
        self.assertTrue(any("cargo clippy" in c for c in cmds))   # Rust lint


class CleanGateOutputTests(unittest.TestCase):
    """The gate RESULT the model reads must be error-class only — no ``___CRIA_GATE_`` plumbing,
    no ``EXIT:`` sentinels, no git-hash section, no advisory lint (footguns #1/#2/#5)."""

    def _raw(self, probe1_body):
        # exec-wrapper preamble (ignored) + a clean tier-0 probe-0 + probe-1 + git section + trailer
        return (
            "Chunk ID: 7f3\n"
            + _sec(0, "EXIT:0")
            + _sec(1, probe1_body)
            + _git("deadbeef")
            + "Process exited with code 1\n"
        )

    def _raw_solo(self, probe0_body):
        # The SAME wrapper, but with only ONE probe section \u2014 no sibling clean check exists to
        # carry a real verdict. Used to test "nothing in this gate ever produced a verdict", which
        # must stay distinct from "one probe abstained/timed out while a SIBLING check ran clean"
        # (C39 repair: those two used to collapse to the same "no usable result" answer).
        return (
            "Chunk ID: 7f3\n"
            + _sec(0, probe0_body)
            + _git("deadbeef")
            + "Process exited with code 1\n"
        )

    def test_strips_plumbing_and_advisory_keeps_error(self):
        raw = self._raw("x.py:1:1 'os' imported but unused\nx.py:5:4 undefined name 'foo'\nEXIT:1")
        out = probegate.clean_gate_output(raw)
        self.assertIsNotNone(out)
        self.assertIn("x.py:5:4 undefined name 'foo'", out)   # the real error survives
        self.assertNotIn("imported but unused", out)          # advisory dropped
        self.assertNotIn(probegate.SECTION_PREFIX, out)       # no section markers
        self.assertNotIn("EXIT:", out)                        # no exit sentinels
        self.assertNotIn("deadbeef", out)                     # git hash dropped
        self.assertNotIn("Chunk ID", out)                     # exec wrapper dropped

    def test_clean_is_reported_as_a_plain_fact_no_doubt_hedge(self):
        raw = self._raw("x.py:1:1 'os' imported but unused\nEXIT:0")
        out = probegate.clean_gate_output(raw)
        self.assertIsNotNone(out)
        self.assertIn("no error-class", out.lower())
        self.assertNotIn("imported but unused", out)         # advisory still filtered
        self.assertNotIn("all pass", out.lower())            # not a false "done"/verified claim
        # and NO unactionable "but this might still be wrong / doesn't mean done" hedge (operator dir.)
        self.assertNotIn("does not verify", out.lower())
        self.assertNotIn("mean the task is done", out.lower())
        self.assertNotIn("still wrong", out.lower())

    def test_bare_style_code_after_location_is_advisory(self):
        # E501 sits AFTER the file:line:col prefix — is_advisory's anchored code check only fires
        # once clean_gate_output strips that prefix.
        raw = self._raw("x.py:80:1: E501 line too long (99 > 88 characters)\nEXIT:0")
        out = probegate.clean_gate_output(raw)
        self.assertIn("no error-class", out.lower())
        self.assertNotIn("E501", out)

    def test_solo_launch_failure_is_neutral_not_an_error_to_fix_nor_a_pass(self):
        # A probe that couldn't launch (`python` absent) with NOTHING else in the gate is cria's OWN
        # setup gap and there is no other check's verdict to fall back on. The model sees a neutral
        # non-actionable note — never an error to "fix", never a pass/clean claim.
        raw = self._raw_solo("timeout: failed to run command 'python': No such file or directory\nEXIT:127")
        out = probegate.clean_gate_output(raw)
        self.assertIn("no usable result", out.lower())
        self.assertNotIn("fix", out.lower())            # not framed as a fixable code error
        self.assertNotIn("pass", out.lower())           # not a pass/clean claim
        self.assertNotIn("no error-class problems. that", out.lower())  # not the clean message either
        self.assertNotIn("python", out.lower())         # doesn't leak the raw launch-failure line

    def test_launch_failure_is_neutral_not_an_error_to_fix_nor_a_pass(self):
        # Restored, UNCHANGED shape (re-review of 8bf62f13): a probe that couldn't launch, next to a
        # clean sibling, with NO PLAN (`clean_gate_output(raw)` — no `plan=`). Without a plan cria
        # cannot positively confirm this was cria's own OPTIONAL composed check (see
        # `_may_abstain_on_launch_failure`), so it fails CLOSED exactly like the pre-C39 default: the
        # whole gate stays unverified, never a bare pass built on a check cria could not even name.
        raw = self._raw("timeout: failed to run command 'python': No such file or directory\nEXIT:127")
        out = probegate.clean_gate_output(raw)
        self.assertIn("no usable result", out.lower())
        self.assertNotIn("fix", out.lower())            # not framed as a fixable code error
        self.assertNotIn("pass", out.lower())           # not a pass/clean claim
        self.assertNotIn("no error-class problems. that", out.lower())  # not the clean message either
        self.assertNotIn("python", out.lower())         # doesn't leak the raw launch-failure line

    def test_c39_absent_pyflakes_module_abstains_not_reported_as_repo_error(self):
        # C39 (row p27 Orders, chunk107): a box with no pyflakes installed made "python3 -m
        # pyflakes" exit 1 with "No module named pyflakes" on stderr -- cria's OWN absent tool,
        # misread as a real repo defect, because python3 itself always launches fine while the
        # MODULE import failed inside it. The C39 re-review reset moved the actual fix UPSTREAM of
        # this function: probediscovery.lint_floor_candidates composes pyflakes as the bare
        # `pyflakes` console-script binary (see PyflakesDroppedWhenAbsentTests), so a genuinely
        # absent pyflakes now either never reaches the gate at all (program_is_installed drops it)
        # or, in the one-gate "unsure" warmup window, produces a REAL shell launch failure -- exit
        # 127, "command not found" -- landing in the SAME generic couldn't-run bucket as every
        # other absent tool, with no pyflakes-specific handling in this function at all.
        raw = self._raw_solo("bash: pyflakes: command not found\nEXIT:127")
        out = probegate.clean_gate_output(raw)
        self.assertIn("no usable result", out.lower())         # abstain: neutral, not an error to fix
        self.assertNotIn("pyflakes", out)                      # the absent tool's own name never ships
        self.assertNotIn("report these error-class problems", out)  # never framed as the repo's own defect

    def test_c39_old_shaped_history_is_out_of_this_functions_scope(self):
        # The ORIGINAL bug shape (python3 -m pyflakes's own exit 1, "No module named pyflakes") is
        # NOT fixed by anything in clean_gate_output -- it never was fixable there (exit 1 carries
        # no reliable "didn't launch" signal by itself, which is exactly why C39 kept reopening at
        # this layer across three rounds). The fix is that no NEW gate can ever produce this shape
        # again (pyflakes is composed as a bare binary now). A transport captured before that
        # shipped could still carry it, and this function reads it exactly as base always did --
        # documented here so a future reader does not mistake this for a still-open gap here.
        raw = self._raw_solo("/usr/bin/python3: No module named pyflakes\nEXIT:1")
        out = probegate.clean_gate_output(raw)
        self.assertIn("report these error-class problems", out)


    def test_c39_present_and_failing_pyflakes_still_reported(self):
        # The other half of C39: a REAL pyflakes finding (present, installed, and failing) must still
        # surface exactly as before — the fix only changes what happens when the module is ABSENT.
        raw = self._raw("orders/app.py:12:1: undefined name 'db'\nEXIT:1")
        out = probegate.clean_gate_output(raw)
        self.assertIsNotNone(out)
        self.assertIn("orders/app.py:12:1: undefined name 'db'", out)
        self.assertIn("error-class problems", out)

    def test_real_error_wins_over_launch_failure(self):
        # If something both failed to launch AND a real error was reported, surface the real error.
        raw = self._raw("timeout: failed to run command 'python': No such file or directory\n"
                        "x.py:5:4 undefined name 'foo'\nEXIT:1")
        out = probegate.clean_gate_output(raw)
        self.assertIn("undefined name 'foo'", out)
        self.assertIn("checker's own message", out.lower())

    def test_real_error_mentioning_no_such_file_is_not_couldnt_run(self):
        # THE _INFRA_FAILURE false-positive: a genuine test failure whose message contains "No such
        # file or directory" (FileNotFoundError, missing #include) must surface as an ERROR, keyed on
        # the section's non-zero EXIT — not be hidden as "couldn't run" by a substring.
        raw = self._raw("FAILED tests/t.py::test_reads - FileNotFoundError: "
                        "[Errno 2] No such file or directory: 'data.csv'\nEXIT:1")
        out = probegate.clean_gate_output(raw)
        self.assertIn("No such file or directory", out)     # surfaced, not swallowed
        self.assertIn("checker's own message", out.lower())
        self.assertNotIn("no usable result", out.lower())   # NOT the couldn't-run message

    def test_timeout_exit_is_couldnt_run(self):
        # A timeout is never a pass and never a "fix this" — but it is also not nothing: the command
        # RAN, so whatever it printed before being stopped is kept as CONTEXT (it used to be discarded
        # wholesale). Its lines must NOT become error-class findings, though — post-timeout output is
        # mostly noise, which is the false-red class.
        raw = self._raw("(killed mid-run)\nEXIT:124")
        out = probegate.clean_gate_output(raw)
        self.assertIn("no verdict either way", out.lower())   # not a pass, not a verdict
        self.assertNotIn("fix", out.lower())
        self.assertNotIn("checker's own message", out.lower())  # NOT reported as error-class findings
        self.assertIn("killed mid-run", out)                    # ...but what it printed survives

    def test_timeout_with_no_output_still_names_the_timeout_not_no_usable_result(self):
        # C39 repair: naming the timeout is required EVEN when it printed nothing (reviewer
        # directive) \u2014 and since `_raw`'s probe-0 genuinely ran clean, the message must say so
        # too rather than collapsing to the generic (and here false) "no usable result".
        raw = self._raw("EXIT:124")
        out = probegate.clean_gate_output(raw)
        self.assertIn("no verdict either way", out.lower())
        self.assertNotIn("no usable result", out.lower())
        self.assertNotIn("fix", out.lower())

    def test_solo_timeout_with_no_output_is_still_named_not_generic_no_usable_result(self):
        # The TRUE solo case (nothing else in the gate at all): still named, per the reviewer's
        # directive that a 124 section is ALWAYS stated as a timeout, even printing nothing.
        raw = self._raw_solo("EXIT:124")
        out = probegate.clean_gate_output(raw)
        self.assertIn("no verdict either way", out.lower())
        self.assertNotIn("fix", out.lower())

    def test_nonzero_exit_empty_output_is_a_failure(self):
        raw = self._raw("EXIT:1")   # exited non-zero, printed nothing usable
        out = probegate.clean_gate_output(raw)
        self.assertIn("failed", out.lower())
        self.assertIn("run it yourself", out.lower())
        self.assertNotIn("no error-class problems. that", out.lower())  # not the clean message

    def test_pytest_no_tests_collected_exit5_is_benign_not_a_failure(self):
        # A fresh/testless project: pytest ran and collected nothing (exit 5). Its "no tests ran" line
        # must NOT scrape as an error-class finding, and — with probe-0 clean — the gate must read as
        # clean-ish ("no error-class problems"), NEVER "one of the checks FAILED".
        raw = self._raw("no tests ran in 0.01s\nEXIT:5")
        out = probegate.clean_gate_output(raw)
        self.assertIn("no error-class", out.lower())
        self.assertNotIn("no tests ran", out.lower())      # benign line not surfaced as a finding
        self.assertNotIn("failed", out.lower())            # not the failure message
        self.assertNotIn("run it yourself", out.lower())

    def test_pytest_no_tests_collected_alone_is_not_a_failure(self):
        # Even when the ONLY non-git probe is pytest-no-tests (a bare python project the model just
        # started), the gate must not read as a failure or "no usable result".
        raw = ("Chunk ID: 7f3\n" + _sec(0, "no tests ran in 0.01s\nEXIT:5")
               + _git("deadbeef") + "Process exited with code 1\n")
        out = probegate.clean_gate_output(raw)
        self.assertNotIn("failed", out.lower())
        self.assertNotIn("no usable result", out.lower())

    def test_passing_pytest_is_not_scraped_as_error_class_findings(self):
        # THE false-red: a GREEN pytest run (exit 0, "…. [100%]\nN passed") must NOT be harvested into
        # "the repo's own checks report these error-class problems ...": 4
        # passed". A passing check's stdout is not a finding.
        raw = self._raw("....                                    [100%]\n4 passed in 0.06s\nEXIT:0")
        out = probegate.clean_gate_output(raw)
        self.assertIn("no error-class", out.lower())          # reads clean-ish, not red
        self.assertNotIn("4 passed", out)                     # the passing summary is not a finding
        self.assertNotIn("checker's own message", out.lower())
        self.assertNotIn("[100%]", out)

    def test_passing_section_does_not_mask_a_failing_one(self):
        # A passing pytest section is skipped, but a REAL failing section still surfaces.
        raw = ("Chunk ID: 7f3\n"
               + _sec(0, "....  [100%]\n4 passed in 0.06s\nEXIT:0")           # green — skipped
               + _sec(1, "x.py:5:4 undefined name 'foo'\nEXIT:1")            # red — surfaced
               + _git("deadbeef") + "Process exited with code 1\n")
        out = probegate.clean_gate_output(raw)
        self.assertIn("undefined name 'foo'", out)
        self.assertNotIn("4 passed", out)


    def test_nonzero_exit_advisory_only_is_clean_not_a_failure(self):
        # ruff/tsc-style: exited non-zero but every line is advisory (unused import). Must read as
        # advisory-clean, NEVER "a check failed" — that's the footgun the user cares about.
        raw = self._raw("x.py:1:1 'os' imported but unused\nEXIT:1")
        out = probegate.clean_gate_output(raw)
        self.assertIn("no error-class", out.lower())
        self.assertNotIn("failed", out.lower())
        self.assertNotIn("imported but unused", out)

    def test_all_error_class_findings_shown_no_40_line_clip(self):
        # A 40-line clip once hid findings 41+, so the model "fixed" the visible ones and claimed done
        # while real errors below the fold stayed invisible. Every error-class finding must appear.
        lines = [f"x.py:{i}:4 undefined name 'v{i}'" for i in range(1, 51)]   # 50 distinct real errors
        raw = self._raw("\n".join(lines) + "\nEXIT:1")
        out = probegate.clean_gate_output(raw)
        self.assertIn("x.py:1:4 undefined name 'v1'", out)
        self.assertIn("x.py:50:4 undefined name 'v50'", out)   # the 50th survives — no 40-line clip
        self.assertEqual(sum(1 for l in out.splitlines() if "undefined name" in l), 50)

    def test_non_gate_text_untouched(self):
        self.assertIsNone(probegate.clean_gate_output("just some tool output, no markers"))
        self.assertIsNone(probegate.clean_gate_output(""))

    def test_clean_gate_results_rewrites_tool_and_fco_messages(self):
        raw = self._raw("x.py:5:4 undefined name 'foo'\nEXIT:1")
        msgs = [
            {"role": "user", "content": "go"},
            {"role": "tool", "content": raw},                                  # chat-style tool result
            {"type": "function_call_output", "output": raw},                   # responses-style result
            {"role": "tool", "content": "unrelated tool output"},              # non-gate — untouched
        ]
        out = probegate.clean_gate_results(msgs)
        self.assertEqual(out[0], msgs[0])                                       # user passes through
        self.assertIn("⟦ctx:checks⟧", out[1]["content"])
        self.assertNotIn(probegate.SECTION_PREFIX, out[1]["content"])
        self.assertIn("⟦ctx:checks⟧", out[2]["output"])                       # rewrote the `output` key
        self.assertEqual(out[3], msgs[3])                                       # non-gate untouched

    def test_idempotent(self):
        raw = self._raw("x.py:5:4 undefined name 'foo'\nEXIT:1")
        msgs = [{"role": "tool", "content": raw}]
        once = probegate.clean_gate_results(msgs)
        twice = probegate.clean_gate_results(once)
        self.assertEqual(once, twice)

    def _gate_cmd(self):
        import json
        cmd = (probegate._gate_sentinel(["pytest -q"]) + "\n"
               + "cd /ws || exit 97\necho " + probegate.SECTION_PREFIX + "probe-0___\npytest -q\necho "
               + probegate.SECTION_PREFIX + "git___\ngit status --porcelain 2>/dev/null | sha1sum 2>/dev/null | cut -d' ' -f1")
        return {"role": "assistant", "tool_calls": [{"id": "g1", "type": "function",
                "function": {"name": "exec_command", "arguments": json.dumps({"cmd": cmd})}}]}

    def test_strips_gate_command_plumbing_keeps_probe(self):
        # The model never authored the gate scaffolding — strip the markers/git-sha/cd-guard from the
        # command, leaving only the real probe (pytest). The result is still cleaned to ⟦ctx:checks⟧.
        import json
        msgs = [self._gate_cmd(),
                {"role": "tool", "tool_call_id": "g1", "content": self._raw("x.py:5:4 undefined name 'foo'\nEXIT:1")}]
        out = probegate.clean_gate_results(msgs)
        cmd = json.loads(out[0]["tool_calls"][0]["function"]["arguments"])["cmd"]
        self.assertEqual(cmd, "pytest -q")                        # scaffolding gone
        self.assertNotIn("sha1sum", cmd)
        self.assertNotIn(probegate.SECTION_PREFIX, cmd)
        self.assertIn("⟦ctx:checks⟧", out[1]["content"])          # the finding survives

    def test_no_signal_gate_turn_is_dropped_whole(self):
        # A "no usable result this turn" check is pure noise → drop the result AND its command call, so
        # nothing orphans and the model isn't told a check ran that said nothing.
        import json
        no_probe = "Chunk ID: 1\n" + probegate.SECTION_PREFIX + "git___\ndeadbeef\n"  # git only → no signal
        msgs = [{"role": "user", "content": "go"}, self._gate_cmd(),
                {"role": "tool", "tool_call_id": "g1", "content": no_probe}]
        out = probegate.clean_gate_results(msgs)
        self.assertEqual([m.get("role") for m in out], ["user"])   # both the call and result are gone

    def test_paged_transport_collapses_to_one_clean_wire_valid_result(self):
        import json
        from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind
        candidate = ProbeCandidate(
            kind=ProbeKind.Test, command=["pytest", "-q"], working_dir="/ws",
            confidence=90, expected_value=80, cost=ProbeCost.Cheap, mutates_code=False,
            may_hang=False, may_need_services=False, reason="test")
        raw = self._raw("x.py:5:4 undefined name 'foo'\nEXIT:1")
        plan = probegate.GatePlan(workspace="/ws", candidates=[candidate], transport_required=True)
        plan.transport_data = bytearray(raw.encode())
        plan.transport_total = len(plan.transport_data)
        plan.transport_complete = True
        marker = probegate._transport_marker(plan.transport_id)
        first_command = probegate._gate_sentinel(["pytest -q"]) + "\ninternal transport"
        next_command = probegate._gate_sentinel([]) + "\ninternal next page"
        messages = [
            {"role": "assistant", "tool_calls": [{"id": "p0", "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"cmd": first_command})}}]},
            {"role": "tool", "tool_call_id": "p0", "content": marker + "\npage zero"},
            {"role": "assistant", "tool_calls": [{"id": "p1", "type": "function", "function": {
                "name": "exec_command", "arguments": json.dumps({"cmd": next_command})}}]},
            {"role": "tool", "tool_call_id": "p1", "content": marker + "\npage one"},
        ]
        out = probegate.clean_gate_results(messages, plan)
        self.assertEqual([m.get("role") for m in out], ["assistant", "tool"])
        self.assertEqual(json.loads(out[0]["tool_calls"][0]["function"]["arguments"])["cmd"],
                         "pytest -q")
        self.assertIn("undefined name 'foo'", out[1]["content"])
        self.assertNotIn(probegate.TRANSPORT_PREFIX, str(out))
        self.assertNotIn("internal next page", str(out))

    def test_incomplete_transport_history_says_unknown(self):
        plan = probegate.GatePlan(workspace="/ws", transport_required=True)
        marker = probegate._transport_marker(plan.transport_id)
        out = probegate.clean_gate_results(
            [{"role": "tool", "tool_call_id": "p0", "content": marker + "\ncut"}], plan)
        self.assertIn("UNKNOWN", out[0]["content"])
        self.assertNotIn(probegate.TRANSPORT_PREFIX, out[0]["content"])

    def test_a_complete_older_transport_is_reverified_not_replaced_with_unknown(self):
        import base64
        import hashlib

        old = probegate.GatePlan(workspace="/ws", transport_required=True)
        raw = ("Chunk ID: old\n"
               + _sec(0, "runner chatter\n" + "x" * 7000 + "\nEXIT:0")
               + _sec(1, "old.py:9:2 undefined name 'kept'\nEXIT:1")
               + _git("deadbeef"))
        raw_bytes = raw.encode()
        digest = hashlib.sha256(raw_bytes).hexdigest()
        path = f"/tmp/.cria-gate-{old.transport_id}.history"
        pages = []
        for offset in range(0, len(raw_bytes), probegate.TRANSPORT_CHUNK_BYTES):
            chunk = raw_bytes[offset:offset + probegate.TRANSPORT_CHUNK_BYTES]
            pages.append("\n".join([
                probegate._transport_marker(old.transport_id),
                "path\t" + base64.b64encode(path.encode()).decode(),
                f"offset\t{offset}",
                f"total\t{len(raw_bytes)}",
                f"sha256\t{digest}",
                "data\t" + base64.b64encode(chunk).decode(),
                probegate._transport_marker(old.transport_id, end=True),
            ]))

        current = probegate.GatePlan(workspace="/ws", transport_required=True)
        messages = [
            {"role": "tool", "tool_call_id": f"old-{i}", "content": page}
            for i, page in enumerate(pages)
        ] + [{"role": "tool", "tool_call_id": "current",
              "content": probegate._transport_marker(current.transport_id) + "\ncut"}]

        out = probegate.clean_gate_results(messages, current)
        rendered = "\n".join(m["content"] for m in out)
        self.assertIn("old.py:9:2 undefined name 'kept'", rendered)
        self.assertEqual(rendered.count("UNKNOWN"), 1)  # only the genuinely incomplete current gate
        self.assertNotIn(probegate.TRANSPORT_PREFIX, rendered)


class CleanGateResultsRepeatPreservationTests(unittest.TestCase):
    """Unstamped ⟦ctx:checks⟧ results are model-visible tool ground truth, not gate provenance.
    Every result must remain intact even if its payload repeats."""

    def _checks(self, text):
        return {"role": "tool", "content": probegate.CHECKS_MARKER + " " + text}

    def test_identical_checks_remain_verbatim(self):
        msgs = [self._checks("smoke_test.py:2: ImportError foo"),
                {"role": "user", "content": "edit"},
                self._checks("smoke_test.py:2: ImportError foo"),
                self._checks("smoke_test.py:2: ImportError foo")]
        out = probegate.clean_gate_results(msgs)
        self.assertEqual(out, msgs)

    def test_distinct_checks_are_untouched(self):
        msgs = [self._checks("finding A"), self._checks("finding B")]
        out = probegate.clean_gate_results(msgs)
        self.assertIn("finding A", out[0]["content"])
        self.assertIn("finding B", out[1]["content"])


class GitOnlyGateTests(unittest.TestCase):
    """An empty/no-code repo yields zero probe candidates, so plan_gate composes a git-ONLY script.
    That must NOT read as 'checks pass' — no check actually ran (calls 12-34 of the empty-repo session
    got a false '⟦ctx:checks⟧ no error-class problems' on a git-only gate)."""

    def test_interpret_git_only_gate_is_not_ran(self):
        from cria.probegate import GatePlan, interpret_gate, SECTION_PREFIX as P, SECTION_SUFFIX as S
        out = interpret_gate(GatePlan(workspace="/tmp", candidates=[]), f"{P}git{S}\nabc123\n")
        self.assertFalse(out.ran)          # only a git snapshot came back → no check ran → not clean

    def test_clean_gate_output_git_only_is_not_a_pass(self):
        from cria.probegate import clean_gate_output, SECTION_PREFIX as P, SECTION_SUFFIX as S
        out = clean_gate_output(f"pre\n{P}git{S}\nabc123\n")
        self.assertIn("no usable result", out.lower())     # the neutral no-signal branch...
        self.assertNotIn("no error-class", out.lower())    # ...NOT the clean/pass message


class CutShortGateTests(unittest.TestCase):
    """A harness exec that YIELDS before the composed gate finishes (observed live: Codex's 10s
    window cut the script mid-pytest — "Process running with session ID …") leaves the tail
    section headered but EXIT-less. That must read as UNFINISHED/unknown — never as a pass (the
    old behavior let a lint-green gate read CLEAN with tests still running) and never as "tool
    missing" (a false fact: a missing tool still prints EXIT:127)."""

    def _plan(self):
        t = _ws(with_pytest=True)
        with _fake_pyflakes_on_path():
            return plan_gate(t)

    def _i(self, plan, name_frag):
        for i, c in enumerate(plan.candidates):
            if name_frag in " ".join(c.command):
                return i
        raise AssertionError(f"no candidate matching {name_frag}")

    def test_cut_short_section_is_not_a_pass_and_digest_says_unfinished(self):
        plan = self._plan()
        raw = (_sec(self._i(plan, "compileall"), "EXIT:0")
               + _sec(self._i(plan, "pyflakes"), "EXIT:0")
               + _sec(self._i(plan, "pytest"), ""))                    # header came back, then the cut
        out = interpret_gate(plan, raw)
        self.assertIsNone(completion_block_nudge(out.report))          # unknown ≠ a failure to fix
        digest = completion_probe_digest(out.report)
        self.assertIn("UNFINISHED", digest)
        self.assertNotIn("tool missing", digest)                       # the old false fact
        from cria.probegate import clean_gate_output
        nudge = clean_gate_output(raw, plan)
        self.assertNotIn("no problems reported", nudge or "")          # and never reads clean


class GateTimeBudgetTests(unittest.TestCase):
    """The gate call asks the harness for the composed script's real time budget via whatever
    ms-unit field the tool's own schema declares — nothing invented for tools that declare none."""

    def test_codex_shaped_tool_gets_yield_time(self):
        from cria.shelltool import GATE_TIME_BUDGET_MS, with_time_budget
        tool = {"name": "exec_command",
                "schema": {"properties": {"cmd": {"type": "string"},
                                          "yield_time_ms": {"type": "number"}}}}
        args = with_time_budget(tool, {"cmd": "echo hi"})
        self.assertEqual(args["yield_time_ms"], GATE_TIME_BUDGET_MS)

    def test_plain_tool_unchanged(self):
        from cria.shelltool import with_time_budget
        tool = {"name": "shell", "schema": {"properties": {"command": {"type": "string"},
                                                           "timeout": {"type": "number"}}}}
        self.assertEqual(with_time_budget(tool, {"command": "x"}), {"command": "x"})  # bare
        # "timeout" is unit-ambiguous across harnesses — never set

    def test_gate_op_carries_the_budget(self):
        import json as _json
        from cria.loop import GuardState, guard_gate_op
        t = _ws(with_pytest=True)
        gs = GuardState()
        body = {"tools": [{"type": "function",
                           "function": {"name": "exec_command",
                                        "parameters": {"properties": {"cmd": {"type": "string"},
                                                                      "yield_time_ms": {"type": "number"}}}}}],
                "messages": []}
        tc = guard_gate_op(gs, body, _RlogStub(), workspace_root=t)
        self.assertIsNotNone(tc)
        args = _json.loads(tc["function"]["arguments"])
        self.assertIn("yield_time_ms", args)


class _RlogStub:
    phase = "coder"
    def emit(self, *a, **k):
        pass


class DelimiterFactTests(unittest.TestCase):
    """Unmatched-delimiter findings get ONE counted fact — the line's on-disk bytes + opener/closer
    counts. Code counts, the model applies; the fact prescribes nothing (delete-vs-add is the
    model's call), and a balanced flagged line gets silence (the imbalance is elsewhere)."""

    def test_imbalanced_line_gets_a_counted_fact(self):
        import tempfile, os
        from cria.probegate import GatePlan, _with_delimiter_facts
        with tempfile.TemporaryDirectory() as ws:
            os.makedirs(os.path.join(ws, "tests"))
            with open(os.path.join(ws, "tests", "t.py"), "w") as fh:
                fh.write("import x\n" * 53 + 'with patch("a", side_effect=ValueError("x (503)"))):\n')
            out = _with_delimiter_facts(
                [f"tests/t.py:54:52: unmatched ')'"], GatePlan(workspace=ws))
            self.assertEqual(len(out), 2)
            self.assertIn("counted fact", out[1])
            self.assertIn("3 '('", out[1])
            self.assertIn("4 ')'", out[1])
            self.assertNotIn("delete", out[1].lower())          # never prescribes
            self.assertNotIn("add", out[1].lower())

    def test_balanced_line_stays_silent(self):
        import tempfile, os
        from cria.probegate import GatePlan, _with_delimiter_facts
        with tempfile.TemporaryDirectory() as ws:
            with open(os.path.join(ws, "t.py"), "w") as fh:
                fh.write("x = (1)\n")
            out = _with_delimiter_facts(["t.py:1:1: unmatched ')'"], GatePlan(workspace=ws))
            self.assertEqual(out, ["t.py:1:1: unmatched ')'"])   # fact withheld — imbalance elsewhere

    def test_non_delimiter_findings_untouched(self):
        from cria.probegate import GatePlan, _with_delimiter_facts
        f = ["a.py:3:1: undefined name 'requests'"]
        self.assertEqual(_with_delimiter_facts(f, GatePlan(workspace="/tmp")), f)


class NoTestsFoundNoteTests(unittest.TestCase):
    """g20 (gemma4, ada-handles): the coder put its unittest classes INSIDE resolve_handle.py. No file
    matched the naming convention, so no test probe was ever selected, and the gate answered "the repo's
    own checks that ran reported no error-class problems" FIFTY-FOUR times over a project whose tests
    could not run at all — then the completion judge approved on it. The clean line was true and half a
    sentence."""

    CLEAN = "___CRIA_GATE_probe-0___\nEXIT:0\n___CRIA_GATE_git___\nabc\n"

    def _ws(self, tmp, **files):
        for name, body in files.items():
            p = Path(tmp, name.replace("|", "/"))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        return tmp

    def test_the_clean_line_says_no_tests_ran_and_names_the_convention(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._ws(tmp, **{"resolve_handle.py":
                                  "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): pass\n"})
            plan = probegate.plan_gate(ws)
            out = probegate.clean_gate_output(self.CLEAN, plan)
        self.assertIn("no error-class problems", out)      # the original fact is unchanged...
        self.assertIn("no test command was composed", out)            # ...and no longer half a sentence
        self.assertIn("test_*.py or *_test.py", out)       # the convention cria SEARCHED by
        self.assertNotIn("required", out)                  # cria cannot know whether this task wants tests

    def test_it_stops_the_moment_a_discoverable_test_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._ws(tmp, **{"resolve_handle.py": "x = 1\n",
                                  "tests|test_resolve.py": "def test_ok():\n    assert True\n"})
            out = probegate.clean_gate_output(self.CLEAN, probegate.plan_gate(ws))
        self.assertNotIn("No tests ran", out)
        self.assertEqual(out, "⟦ctx:checks⟧ the repo's own checks that ran reported no error-class problems.")

    def test_a_decoration_language_is_silent_when_its_tests_exist(self):
        # Rust puts tests in #[cfg(test)] modules INSIDE the source file — no test FILE exists even
        # when there are plenty of tests, and `cargo test` runs them wherever they are.
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._ws(tmp, **{"src|lib.rs": "fn a(){}\n#[cfg(test)]\nmod t {\n #[test]\n fn x(){}\n}\n",
                                  "Cargo.toml": "[package]\nname='x'\n"})
            self.assertNotIn("no test command was composed", probegate.clean_gate_output(self.CLEAN,
                                                                             probegate.plan_gate(ws)))

    def test_a_decoration_language_with_no_tests_is_told_the_decoration(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._ws(tmp, **{"src|lib.rs": "fn a(){}\n", "Cargo.toml": "[package]\nname='x'\n"})
            out = probegate.clean_gate_output(self.CLEAN, probegate.plan_gate(ws))
        # `cargo test` IS composed for a Cargo project, so the lead sentence may not claim none was.
        self.assertNotIn("no test command was composed", out)
        self.assertIn("does not establish that this project's tests pass", out)
        self.assertIn("#[test]", out)          # the DECORATION, not a filename

    def test_stranded_test_code_is_named_in_the_gate(self):
        # g20 end to end: real tests, in a file pytest will never collect.
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._ws(tmp, **{"resolve_handle.py":
                                  "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): pass\n"})
            out = probegate.clean_gate_output(self.CLEAN, probegate.plan_gate(ws))
        self.assertIn("Test code in resolve_handle.py will not run", out)

    def test_go_with_a_manifest_and_no_test_file_is_covered_too(self):
        # `go test ./...` IS selected here and exits 0 printing "no test files", so the gate reads
        # clean — the same vacuous green as g20's Python, reached the other way round. Keyed on the
        # FILES, so it needs no parsing of a runner output cria has no toolchain to verify against.
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._ws(tmp, **{"main.go": "package main\n", "go.mod": "module x\ngo 1.21\n"})
            out = probegate.clean_gate_output(self.CLEAN, probegate.plan_gate(ws))
        # `go test ./...` IS composed here, so the lead sentence may not say none was — that claim
        # went out over a gate script containing `mvn test` on cycle 4 cell 16. What it says instead
        # is the fact that still holds: the green does not establish the tests pass.
        self.assertNotIn("no test command was composed", out)
        self.assertIn("does not establish that this project's tests pass", out)
        self.assertIn("*_test.go", out)

    def test_a_venv_full_of_test_files_does_not_mask_a_testless_project(self):
        # The vendored .gitignore templates (cria/ignore.py) are the signal for where NOT to look:
        # pytest's and pip's own suites live under site-packages and are not this project's tests.
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._ws(tmp, **{"resolve.py": "x = 1\n",
                                  ".venv|lib|python3.12|site-packages|_pytest|test_main.py": "def test_x(): pass\n",
                                  ".venv|lib|python3.12|site-packages|_pytest|test_cfg.py": "def test_y(): pass\n"})
            self.assertIn("no test command was composed", probegate.clean_gate_output(self.CLEAN,
                                                                          probegate.plan_gate(ws)))

    def test_findings_are_never_buried_under_the_note(self):
        # Where a real error-class finding exists the coder has concrete work; a naming note on top of
        # it is noise. Only the CLEAN branch carries the qualifier.
        failing = "___CRIA_GATE_probe-0___\napp.py:3: undefined name 'x'\nEXIT:1\n___CRIA_GATE_git___\nabc\n"
        with tempfile.TemporaryDirectory() as tmp:
            ws = self._ws(tmp, **{"app.py": "import unittest\n"})
            out = probegate.clean_gate_output(failing, probegate.plan_gate(ws))
        self.assertIn("undefined name", out)
        self.assertNotIn("No tests ran", out)


class VerbatimMeansVerbatimTests(unittest.TestCase):
    """cria ships this block under "each is the checker's OWN message". It was shipping a STRIPPED,
    globally DE-DUPLICATED copy — which destroys a traceback's source echo, because a `}` or `)` on
    its own line is both indentation-bearing and a repeat of one seen earlier, so it was deleted
    twice over.

    Walked on ada-handles_fabliq_codex_pon_1785721353. A reader fed real pytest output through
    cria's own clean_gate_output() and reproduced its exact call-0185 bytes, closing brace missing.
    The file parsed cleanly and `compileall` exited 0 in that same gate. cria manufactured
    "handle_resolver.py has a syntax error — missing a closing parenthesis", restated it in every
    prompt for 45 straight calls, and the coder copied the de-indented text into edit_file
    old_strings that could never match. Two earlier walks named this their top fix."""

    SRC = ("$ python3 -m pytest -q\n"
           "    def resolve(h):\n"
           "        return {\n"
           "            'a': 1,\n"
           "            'b': 2\n"
           "        }\n"
           "    except RequestException as e:\n"
           "E   AttributeError: 'str' object has no attribute 'get'\n")

    def _clean(self, body):
        from cria import proberun
        raw = (f"{probegate.SECTION_PREFIX}probe-1{probegate.SECTION_SUFFIX}\n"
               f"{body}{proberun.PROBE_EXIT_SENTINEL}1\n")
        return probegate.clean_gate_output(raw, None) or ""

    def test_the_closing_brace_is_not_deleted(self):
        self.assertIn("}", self._clean(self.SRC))

    def test_indentation_survives(self):
        out = self._clean(self.SRC).splitlines()
        self.assertTrue(any(l.startswith("            'a': 1") for l in out),
                        "the checker's own indentation was stripped")

    def test_the_error_line_still_reaches_the_coder(self):
        self.assertIn("'str' object has no attribute 'get'", self._clean(self.SRC))

    def test_a_repeated_line_is_still_deduped_once(self):
        # Dedupe on the stripped form is still right — it just must not change what is EMITTED.
        body = "$ x\n    a = 1\n    a = 1\n        a = 1\nE   Boom\n"
        out = self._clean(body)
        self.assertEqual(out.count("a = 1"), 1)

    def test_advisory_lines_are_still_filtered(self):
        body = "$ x\nfoo.py:1:1: 'os' imported but unused\nE   Boom\n"
        out = self._clean(body)
        self.assertNotIn("imported but unused", out)
        self.assertIn("Boom", out)


class F811ShadowInGateOutputTests(unittest.TestCase):
    """The model-facing gate result must surface a def/class F811 shadow (a real bug: the second
    binding silently wins) while still dropping the import-rebinding form (cleanliness). Walked on
    ada-handles_maple-preview_codex_poff_1785956867 — the duplicate `def resolve_handle` was the
    structural root of the failed run and the suppressed pyflakes line was the only checker output
    that named it."""

    def _ws(self, content):
        import tempfile
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "x.py"), "w") as fh:
            fh.write(content)
        return d

    def _raw(self, body):
        return "Chunk ID: 7f3\n" + _sec(0, "EXIT:0") + _sec(1, body) + _git() + "\n"

    def test_a_def_shadow_survives_to_the_model(self):
        ws = self._ws("import json\n" + "\n" * 3 + "def resolve_handle(h, live_test=False):\n    pass\n")
        raw = self._raw("x.py:5:1: redefinition of unused 'resolve_handle' from line 2\nEXIT:1")
        out = probegate.clean_gate_output(raw, GatePlan(workspace=ws))
        self.assertIn("redefinition of unused 'resolve_handle'", out)
        self.assertIn("def resolve_handle(h, live_test=False):", out)   # flagged-line fact rides along

    def test_an_import_rebinding_is_still_filtered(self):
        ws = self._ws("import json\nimport os\nimport json\n")
        raw = self._raw("x.py:3:1: redefinition of unused 'json' from line 1\nEXIT:1")
        out = probegate.clean_gate_output(raw, GatePlan(workspace=ws))
        self.assertNotIn("redefinition", out)

    def test_no_workspace_keeps_the_old_advisory_default(self):
        raw = self._raw("x.py:5:1: redefinition of unused 'resolve_handle' from line 2\nEXIT:1")
        out = probegate.clean_gate_output(raw)
        self.assertNotIn("redefinition", out)


class FlaggedLineFactTests(unittest.TestCase):
    """Walked on ada-handles_gemma4_codex_poff_1785904860 (~call 0045): the checker said
    `pyproject.toml: Invalid value (at line 20, column 9)` — position, no text — and the model
    GUESSED the line said `build-backend = "python3"` (never true, never shown anywhere) and
    burned an edit-miss on the phantom. The cure is the delimiter-fact contract, generalized:
    when a finding names file:line without quoting the line, append the line's on-disk bytes.
    State the fact or be silent; prescribe nothing."""

    def _ws(self, name, content):
        import tempfile, os
        d = tempfile.mkdtemp()
        with open(os.path.join(d, name), "w") as fh:
            fh.write(content)
        return d

    def test_a_colon_line_finding_gains_the_flagged_line(self):
        from cria.probegate import GatePlan, _with_delimiter_facts
        ws = self._ws("client.py", "import os\nresp = requests.get(url)\n")
        out = _with_delimiter_facts(["client.py:2:8: undefined name 'requests'"],
                                    GatePlan(workspace=ws))
        self.assertEqual(len(out), 2)
        self.assertIn("resp = requests.get(url)", out[1])
        self.assertIn("line 2", out[1])

    def test_an_AT_LINE_style_finding_gains_the_flagged_line(self):
        # The exact tomllib shape from the walked run.
        from cria.probegate import GatePlan, _with_delimiter_facts
        ws = self._ws("pyproject.toml",
                      "\n" * 19 + 'build-backend = "setuptools.build"\n')
        out = _with_delimiter_facts(
            ["pyproject.toml: Invalid value (at line 20, column 9)"], GatePlan(workspace=ws))
        self.assertEqual(len(out), 2)
        self.assertIn('build-backend = "setuptools.build"', out[1])

    def test_a_finding_already_quoting_its_line_stays_bare(self):
        # compileall's SyntaxError echo already shows the line — no duplicate fact.
        from cria.probegate import GatePlan, _with_delimiter_facts
        ws = self._ws("t.py", "assert x == 1\n")
        f = ["t.py:1: SyntaxError near `assert x == 1`"]
        self.assertEqual(_with_delimiter_facts(f, GatePlan(workspace=ws)), f)

    def test_missing_file_or_line_stays_silent(self):
        from cria.probegate import GatePlan, _with_delimiter_facts
        f = ["gone.py:9:1: undefined name 'x'"]
        self.assertEqual(_with_delimiter_facts(f, GatePlan(workspace="/nonexistent-ws")), f)

    def test_the_fact_prescribes_nothing(self):
        from cria.probegate import GatePlan, _with_delimiter_facts
        ws = self._ws("a.py", "y = foo(\n")
        out = _with_delimiter_facts(["a.py:1:5: undefined name 'foo'"], GatePlan(workspace=ws))
        joined = " ".join(out).lower()
        self.assertNotIn("fix", joined)
        self.assertNotIn("should", joined)


class GateRepeatPreservationTests(unittest.TestCase):
    """Unstamped checker results are preserved even when only volatile run details differ."""

    M = probegate.CHECKS_MARKER

    def _checks(self, addr, secs, tid):
        return {"role": "tool", "tool_call_id": tid,
                "content": (f"{self.M} the repo's own checks report these error-class problems:\n"
                            f"x.py:92:10: undefined name 'pytest'\n"
                            f"url = <urllib.request.Request object at {addr}>, args = ()\n"
                            f"3 failed, 1 passed in {secs}")}

    def test_three_renderings_of_one_finding_remain_verbatim(self):
        msgs = [self._checks("0x7cd31c34ac60", "0.36s", "a"),
                self._checks("0x740a465deed0", "0.28s", "b"),
                self._checks("0x7b2ed94635f0", "0.31s", "c")]
        self.assertEqual(probegate.clean_gate_results(msgs, None), msgs)

    def test_a_genuinely_different_finding_is_never_collapsed(self):
        a = self._checks("0x1111111111", "0.10s", "a")
        b = dict(a, tool_call_id="b", content=a["content"].replace("undefined name 'pytest'",
                                                                   "undefined name 'json'"))
        out = probegate.clean_gate_results([a, b], None)
        self.assertEqual(sum(probegate.CHECKS_REPEAT_NOTE[:40] in m["content"] for m in out), 0)




class C19ProxyCheckerPreservationTests(unittest.TestCase):
    """C14 CALL0028/CALL0392 repeatedly ran the real Go checker, but the model received only
    ``CHECKS_REPEAT_NOTE`` until its final run. Non-stamped proxy history has no provenance that
    permits replacing any actual checker result."""

    def test_c14_proxy_checker_results_remain_verbatim(self):
        def command(call_id):
            return {"role": "assistant", "tool_calls": [{"id": call_id, "type": "function",
                    "function": {"name": "exec_command", "arguments":
                        '{"cmd":"go vet -mod=readonly ./...\\ngo build -mod=readonly ./...\\ngo test -mod=readonly -count=1 -v ./..."}'}}]}

        first = (probegate.CHECKS_MARKER + " the repo's own checks report these error-class problems:\n"
                 "./cart.go:21:5: undefined: decimal\nFAIL\tcartsvc [build failed] in 0.01s")
        second = first.replace("0.01s", "0.02s")
        third = (probegate.CHECKS_MARKER + " the repo's own checks report these error-class problems:\n"
                 "./cart_test.go:14:2: missing regression test\nFAIL\tcartsvc [build failed] in 0.03s")
        messages = [command("proxy-check-0028"),
                    {"role": "tool", "tool_call_id": "proxy-check-0028", "content": first},
                    command("proxy-check-0392"),
                    {"role": "tool", "tool_call_id": "proxy-check-0392", "content": second},
                    command("proxy-check-final"),
                    {"role": "tool", "tool_call_id": "proxy-check-final", "content": third}]

        out = probegate.clean_gate_results(messages)

        self.assertEqual([m["content"] for m in out if m.get("role") == "tool"],
                         [first, second, third])

    def test_stamped_gate_repeat_and_ordinary_marker_shaped_result_keep_their_boundaries(self):
        import json

        def stamped(call_id):
            return {"role": "assistant", "tool_calls": [{"id": call_id, "type": "function",
                    "function": {"name": "exec_command", "arguments": json.dumps({"cmd":
                        probegate._gate_sentinel(["pytest -q"])})}}]}

        gate = probegate.CHECKS_MARKER + " gate.py:4: ImportError: kept by C6"
        ordinary = probegate.CHECKS_MARKER + " ordinary.py:7: marker-shaped tool output"
        out = probegate.clean_gate_results([
            stamped("gate-first"), {"role": "tool", "tool_call_id": "gate-first", "content": gate},
            stamped("gate-last"), {"role": "tool", "tool_call_id": "gate-last", "content": gate},
            {"role": "tool", "tool_call_id": "ordinary", "content": ordinary},
        ], linked_only=True)
        results = [m["content"] for m in out if m.get("role") == "tool"]
        self.assertEqual(results, [probegate.CHECKS_REPEAT_NOTE, gate, ordinary])


class TheNoteStatesCriasCoverageNotAVerdictTests(unittest.TestCase):
    """The clean-gate note used to end "If the task calls for tests, that is not done yet."

    That is a verdict about the task, delivered in cria's own voice, from a discovery MISS. cria
    cannot know whether a task wants tests, and on the six-language battery the same sentence was
    emitted 49 times per run over a Ruby suite that was green — the miss was cria's convention table,
    not the repo's tests. A discovery miss is a gap in cria's coverage and must be reported as one
    (#5b, and #8: state the fact, let the judge rule)."""

    def test_it_reports_criA_own_coverage(self):
        from cria import prompts
        note = prompts.render("no_tests_found", findings="")
        self.assertIn("no test command was composed", note)

    def test_it_does_not_rule_on_the_task(self):
        from cria import prompts
        note = prompts.load("no_tests_found").lower()
        self.assertNotIn("not done yet", note)
        self.assertNotIn("if the task", note)


if __name__ == "__main__":
    unittest.main()
