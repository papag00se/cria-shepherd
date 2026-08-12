"""The completion gate's transport (unified tier-0 design): compose (plan_gate) →
harness runs → interpret (interpret_gate). All checks — parse floors included — are
first-class candidates; no privileged per-language floor."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cria import probegate
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

    def test_launch_failure_is_neutral_not_an_error_to_fix_nor_a_pass(self):
        # THE regression: a probe that couldn't launch (`python` absent) is cria's OWN setup gap. The
        # model sees a neutral non-actionable note — never an error to "fix", never a pass/clean claim.
        raw = self._raw("timeout: failed to run command 'python': No such file or directory\nEXIT:127")
        out = probegate.clean_gate_output(raw)
        self.assertIn("no usable result", out.lower())
        self.assertNotIn("fix", out.lower())            # not framed as a fixable code error
        self.assertNotIn("pass", out.lower())           # not a pass/clean claim
        self.assertNotIn("no error-class problems. that", out.lower())  # not the clean message either
        self.assertNotIn("python", out.lower())         # doesn't leak the raw launch-failure line

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

    def test_timeout_with_no_output_stays_a_bare_no_signal(self):
        raw = self._raw("EXIT:124")
        out = probegate.clean_gate_output(raw)
        self.assertIn("no usable result", out.lower())
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
        cmd = ("cd /ws || exit 97\necho " + probegate.SECTION_PREFIX + "probe-0___\npytest -q\necho "
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


class CleanGateResultsDedupTests(unittest.TestCase):
    """Repeated identical ⟦ctx:checks⟧ results (a finding that recurs unchanged across turns) pile up
    in the model's view and reinforce a fixation — collapse the earlier copies to a back-reference,
    keeping the most recent full one, without dropping any message (tool/response pairing intact)."""

    def _checks(self, text):
        return {"role": "tool", "content": probegate.CHECKS_MARKER + " " + text}

    def test_identical_checks_are_collapsed_keeping_the_last(self):
        msgs = [self._checks("smoke_test.py:2: ImportError foo"),
                {"role": "user", "content": "edit"},
                self._checks("smoke_test.py:2: ImportError foo"),   # dup → back-reference
                self._checks("smoke_test.py:2: ImportError foo")]   # LAST → full
        out = probegate.clean_gate_results(msgs)
        tools = [m for m in out if m.get("role") == "tool"]
        self.assertEqual(len(tools), 3)                              # nothing dropped
        self.assertIn("omitted", tools[0]["content"])               # earlier copy collapsed
        self.assertIn("omitted", tools[1]["content"])
        self.assertIn("ImportError foo", tools[2]["content"])        # last kept in full
        self.assertNotIn("omitted", tools[2]["content"])

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
        self.assertIn("no test command was composed", out)
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
        self.assertIn("no test command was composed", out)
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


class GateRepeatCollapseIgnoresPerRunNoiseTests(unittest.TestCase):
    """A finding the coder has already read three times is not three findings.

    mellum2 1786051505 carried `resolve_handle_and_test.py:92: undefined name 'pytest'` THREE times
    in one coder prompt — on a file it had since cut to 7 lines, so it was hunting a line that no
    longer existed. The collapse keys on the payload and never fired: the three copies differed only
    by a `<urllib.request.Request object at 0x…>` address and `in 0.36s` vs `in 0.28s`."""

    M = probegate.CHECKS_MARKER

    def _checks(self, addr, secs, tid):
        return {"role": "tool", "tool_call_id": tid,
                "content": (f"{self.M} the repo's own checks report these error-class problems:\n"
                            f"x.py:92:10: undefined name 'pytest'\n"
                            f"url = <urllib.request.Request object at {addr}>, args = ()\n"
                            f"3 failed, 1 passed in {secs}")}

    def test_three_renderings_of_one_finding_collapse_to_one(self):
        msgs = [self._checks("0x7cd31c34ac60", "0.36s", "a"),
                self._checks("0x740a465deed0", "0.28s", "b"),
                self._checks("0x7b2ed94635f0", "0.31s", "c")]
        out = probegate.clean_gate_results(msgs, None)
        notes = [m for m in out if probegate.CHECKS_REPEAT_NOTE[:40] in m["content"]]
        full = [m for m in out if probegate.CHECKS_REPEAT_NOTE[:40] not in m["content"]]
        self.assertEqual(len(notes), 2)
        self.assertEqual(len(full), 1)
        self.assertIs(out[-1]["content"], msgs[-1]["content"])   # the NEWEST copy is the kept one

    def test_a_genuinely_different_finding_is_never_collapsed(self):
        a = self._checks("0x1111111111", "0.10s", "a")
        b = dict(a, tool_call_id="b", content=a["content"].replace("undefined name 'pytest'",
                                                                   "undefined name 'json'"))
        out = probegate.clean_gate_results([a, b], None)
        self.assertEqual(sum(probegate.CHECKS_REPEAT_NOTE[:40] in m["content"] for m in out), 0)




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
