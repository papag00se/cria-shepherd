"""Six cria faults found by the full line-by-line walk of
ada-handles_nemotron-elastic_codex_pon_1785888803 (101 chunks, calls 0001-0220, 2026-08-05).

The run died at the 45-minute wall on step 6 of 8 with two of four deliverables met. Almost none of
the damage was the model's: cria told it false things about its own workspace and then deleted the
evidence that would have corrected them. Each test below pins one of those mechanisms.
"""

import base64
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

from cria import config, editrecovery, focustrim, loop, probegate, prompts
from cria.writeproxy import translate_outbound
import tests.test_probegate as tp
import tests.test_writeproxy as tw


def _off_role(**kw):
    return config.Role(name="reasoner", backend="local", think_protocol="chat_template",
                       reasoning="off", **kw)


class ALookingJudgeIsNotToldToAnswerDirectlyTests(unittest.TestCase):
    """The confirm judge holds list_dir/read_file and its prompt says "look, then answer" — while
    cria appended "Do not think out loud or narrate your reasoning. Respond directly." to it,
    because the role's reasoning is off. Measured box-wide: 142 of 168 confirm VETOES were emitted
    without one inspection call (85%), against 50 of 156 passes."""

    def test_a_tool_bearing_body_keeps_its_looking_instruction(self):
        body = {"messages": [{"role": "system", "content": "look, then answer"}],
                "tools": [{"type": "function", "function": {"name": "read_file"}}]}
        _off_role().apply(body, internal=True)
        self.assertNotIn("Respond directly", body["messages"][0]["content"])

    def test_a_toolless_body_still_gets_the_directive(self):
        body = {"messages": [{"role": "system", "content": "answer in one word"}]}
        _off_role().apply(body, internal=True)
        self.assertIn("Respond directly", body["messages"][0]["content"])

    def test_reasoning_is_still_forced_off_on_the_tool_bearing_body(self):
        body = {"messages": [{"role": "system", "content": "look"}], "tools": [{"x": 1}]}
        _off_role().apply(body, internal=True)
        self.assertFalse(body.get("chat_template_kwargs", {}).get("enable_thinking", True))


class AFilePayloadIsNotADeadEndLookupTests(unittest.TestCase):
    """focustrim matched `\\bnot found\\b` against tool CONTENT, so every read of a file whose source
    raises ValueError("Handle not found") was squashed into a "returned nothing usable … don't
    repeat these" note. The sibling test file, lacking the phrase, was never folded."""

    _SRC = ('def resolve_handle(h):\n    if r.status_code == 404:\n'
            '        raise ValueError(f"Handle \'{h}\' not found")\n')

    def test_reading_a_file_whose_source_says_not_found_is_a_success(self):
        self.assertFalse(focustrim._is_failure(self._SRC, "read_file"))

    def test_a_real_shell_dead_end_is_still_a_failure(self):
        self.assertTrue(focustrim._is_failure("grep: pattern.py: command not found", "exec_command"))

    def test_a_missing_file_report_from_the_shell_is_still_a_failure(self):
        self.assertTrue(focustrim._is_failure("cat: x.py: No such file or directory", "exec_command"))

    def test_a_hard_failure_from_a_file_tool_is_still_hard(self):
        self.assertTrue(focustrim._is_failure("Process exited with code 1", "read_file"))

    def test_the_squash_leaves_the_resolver_reads_alone(self):
        msgs = []
        for i in range(6):
            msgs.append({"role": "assistant", "tool_calls": [
                {"id": f"c{i}", "type": "function",
                 "function": {"name": "read_file", "arguments": '{"path": "resolver.py"}'}}]})
            msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": self._SRC})
        out, report = focustrim._squash_failures(msgs)
        self.assertEqual(report.squashed_runs, 0)
        self.assertEqual(len(out), len(msgs))


class AnIdenticalEditIsDiagnosedBeforeTheEscalationClockTests(unittest.TestCase):
    """old_string == new_string is complete information: the model needs to be told its two
    arguments are the same string, not handed the file's bytes. Ordering the escalation branch first
    meant five consecutive identical-string edits were answered "you cannot pin its exact current
    text. STOP editing it." — so the coder spent five turns trying harder to pin the text."""

    def _compose(self, mode, prior):
        return editrecovery.compose({"path": "r.py", "mode": mode,
                                     "current": "FULL FILE BYTES"}, prior)

    def test_identical_says_identical_even_past_the_escalation_threshold(self):
        out = self._compose("identical", editrecovery.ESCALATE_AFTER + 3)
        self.assertIn("identical", out)
        self.assertNotIn("FULL FILE BYTES", out)

    def test_a_real_stale_copy_still_escalates(self):
        out = self._compose("no_anchor", editrecovery.ESCALATE_AFTER)
        self.assertIn("FULL FILE BYTES", out)

    def test_identical_is_unchanged_on_a_clean_clock(self):
        self.assertIn("identical", self._compose("identical", 0))


class TheEditAnchorShowsWhereTheCopyIsWrongTests(unittest.TestCase):
    """The 6-line window was centred on the FIRST line of old_string — the part that already
    matched — so a long old_string that diverges further down got back text it already had, under
    "The file actually reads". It now centres on the first line that actually differs."""

    FILE = ("def resolve(h):\n"
            "    url = f'{BASE}/handles/{h}'\n"
            "    resp = requests.get(url)\n"
            "    resp.raise_for_status()\n"
            "    data = resp.json()\n"
            "    holder = data.get('holder')\n"
            "    THE_REAL_LINE = 1\n"
            "    return holder\n")

    def _run_edit(self, old, new):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "r.py"), "w") as fh:
                fh.write(self.FILE)
            comp = tw._call("edit_file", {"path": "r.py", "old_string": old, "new_string": new})
            translate_outbound(comp, tw._CMD_SHELL, injected={"edit_file"})
            cmd = tw._lowered_cmd(comp)
            r = subprocess.run(["bash", "-lc", cmd], cwd=d, capture_output=True, text=True,
                               timeout=120)
            out = r.stdout + r.stderr   # the fact-report is emitted on stderr
        for line in out.splitlines():
            if editrecovery.EDITFAIL in line:
                blob = line.split(editrecovery.EDITFAIL, 1)[1].strip()
                return json.loads(base64.b64decode(blob).decode())
        self.fail(f"no editfail report in:\n{out}")

    def test_the_window_covers_the_line_that_differs(self):
        # Six correct lines, then one the model misremembers.
        stale = ("    url = f'{BASE}/handles/{h}'\n"
                 "    resp = requests.get(url)\n"
                 "    resp.raise_for_status()\n"
                 "    data = resp.json()\n"
                 "    holder = data.get('holder')\n"
                 "    THE_WRONG_LINE = 1\n")
        fail = self._run_edit(stale, stale.replace("THE_WRONG_LINE", "PATCHED"))
        self.assertEqual(fail.get("mode"), "anchor")
        self.assertIn("THE_REAL_LINE", fail.get("anchor", ""))

    def test_an_identical_edit_is_still_reported_as_identical(self):
        same = "    data = resp.json()\n"
        self.assertEqual(self._run_edit(same, same).get("mode"), "identical")


class TheRuminationNoticeStatesItsRealTriggerTests(unittest.TestCase):
    """Two detectors abort a turn. The phrase watcher counts second-guessing; the degenerate-tail
    backstop catches a stream repeating one passage and counts NEITHER phrases nor tokens. Rendering
    the phrase notice for it produced "hit 0 second-guessing phrases … after ~2048 reasoning
    tokens" — a self-refuting cause and a character count relabelled as tokens."""

    def _guard(self, marker):
        seen = []

        def chat(body, rlog):
            seen.append(body)
            return json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}).encode()

        coder = {"choices": [{"message": {"content": ""}, "finish_reason": "rumination"}],
                 "cria_rumination": marker}
        loop.guard_rumination(coder, {"messages": [{"role": "user", "content": "go"}]},
                              chat, _Rlog(), phase="coder")
        return seen[0]["messages"][-1]["content"]

    def test_a_repeating_stream_is_not_called_second_guessing(self):
        text = self._guard({"degenerate": True, "chars": 2048})
        self.assertNotIn("second-guessing", text)
        self.assertNotIn("0", text.split("]")[0])
        self.assertIn("repeating", text.lower())

    def test_the_phrase_watcher_keeps_its_own_notice(self):
        text = self._guard({"hits": 27, "reasoning_tokens": 8245})
        self.assertIn("second-guessing", text)
        self.assertIn("27", text)

    def test_the_degenerate_marker_carries_no_invented_counts(self):
        self.assertNotIn("hits", {"degenerate": True, "chars": 2048})


class AOneWordVerdictRunsAtTemperatureZeroTests(unittest.TestCase):
    """Four guards answer a CLOSED question with one word from a fixed set, and were running at the
    reasoner role's temperature 0.6 because summarize() never pinned one. Replaying the captured
    steer-code prompts 8× each: 7/8 and 6/8 correct at 0.6, correct every time at 0."""

    def _temp(self, **kw):
        seen = []

        def chat(body, rlog):
            seen.append(body)
            return json.dumps({"choices": [{"message": {"content": "STANDS"}, "finish_reason": "stop"}]}).encode()

        loop.summarize(chat, _off_role(temperature=0.6), "sys", "", _Rlog(), phase="t", **kw)
        return seen[0].get("temperature")

    def test_a_pinned_zero_beats_the_role_sampling(self):
        self.assertEqual(self._temp(temperature=0.0), 0.0)

    def test_prose_callers_keep_the_role_temperature(self):
        self.assertEqual(self._temp(), 0.6)


class _Rlog:
    phase = ""
    live_chars = 0
    live_t0 = None

    def emit(self, *a, **kw):
        pass


class TheSteerAuthorIsNeverToldTheWorkspaceIsEmptyTests(unittest.TestCase):
    """When a harness compaction removes the turns carrying the write tool_calls, _touched_paths
    recovers nothing and the on-disk section rendered "(no files touched yet)" — under a header that
    says to trust it over the transcript. Walked three times across two runs; every judge so blinded
    then ruled against reality. The disk itself is the answer."""

    def test_a_lost_write_history_falls_back_to_the_real_inventory(self):
        from cria import groundtruth
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "resolve_handle.py"), "w") as fh:
                fh.write("x = 1\n")
            # No recoverable writes: this is exactly the post-compaction state.
            self.assertEqual(loop._fresh_disk_facts(d, [], ""), "")
            inv = groundtruth.workspace_inventory(d)
            self.assertIn("resolve_handle.py", inv)

    def test_a_genuinely_empty_workspace_says_so_rather_than_nothing(self):
        from cria import groundtruth
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("none", groundtruth.workspace_inventory(d).lower())


class TwoFailuresThatShareALineAreTwoFactsTests(unittest.TestCase):
    """clean_gate_output deduped finding lines GLOBALLY, so a line identical to one already printed
    for an earlier failure was deleted from the later one. Walked twice, independently, on
    1785360304 calls 0145/0147/0148/0152/0153/0155: pytest reported two failing tests whose bodies
    share `self.assertIsNotNone(...)` and `E AssertionError: unexpectedly None`; both lines were
    printed for the first test and DELETED from the second, so the coder was handed
    `test_resolve_handle.py:24: AssertionError` with no assertion and no reason — under a header
    that promises "each is the checker's OWN message"."""

    def _pytest_output(self):
        block = ("_____ TestResolveHandle.test_{name} _____\n"
                 "    def test_{name}(self):\n"
                 "        result = resolve_handle(\"{name}\")\n"
                 ">       self.assertIsNotNone(result[\"holder_address\"])\n"
                 "E       AssertionError: unexpectedly None\n"
                 "test_resolve_handle.py:24: AssertionError\n")
        return block.format(name="goose") + block.format(name="papagoose") + "2 failed in 0.5s\nEXIT:1"

    def test_the_second_failure_keeps_its_assertion_and_its_reason(self):
        from cria.probegate import GatePlan
        raw = "Chunk ID: 7f3\n" + tp._sec(0, "EXIT:0") + tp._sec(1, self._pytest_output()) + tp._git() + "\n"
        out = probegate.clean_gate_output(raw, GatePlan(workspace=""))
        self.assertEqual(out.count("E       AssertionError: unexpectedly None"), 2, out)
        self.assertEqual(out.count(">       self.assertIsNotNone(result[\"holder_address\"])"), 2, out)

    def test_a_line_repeated_back_to_back_still_collapses(self):
        from cria.probegate import GatePlan
        spam = "app.py:1:1: E999 SyntaxError: bad\n" * 5 + "EXIT:1"
        raw = "Chunk ID: 7f3\n" + tp._sec(0, "EXIT:0") + tp._sec(1, spam) + tp._git() + "\n"
        out = probegate.clean_gate_output(raw, GatePlan(workspace=""))
        self.assertEqual(out.count("E999 SyntaxError: bad"), 1, out)


class AReRunCommandIsStillARepeatTests(unittest.TestCase):
    """The harness exec envelope stamps a fresh `Chunk ID` on every result, so keying a duplicate
    group on the raw result text meant two byte-identical re-runs of one command never shared a key
    — duplicate collapse could not fire for exec_command at all, and the repetition notice built on
    it stayed silent through ~40 identical greps in one walked run."""

    def _msgs(self, chunk_ids):
        out = []
        for i, cid_hex in enumerate(chunk_ids):
            out.append({"role": "assistant", "tool_calls": [
                {"id": f"c{i}", "type": "function",
                 "function": {"name": "exec_command",
                              "arguments": '{"cmd": "sed -n \'607,680p\' spec.yml"}'}}]})
            out.append({"role": "tool", "tool_call_id": f"c{i}",
                        "content": f"Chunk ID: {cid_hex}\nWall time: 0.0{i} seconds\n"
                                   f"Original token count: 259\nOutput:\n\"/handles/{{handle}}\": {{\n"})
        return out

    def test_identical_reruns_collapse_despite_a_fresh_chunk_id(self):
        msgs, report = focustrim._collapse_duplicates(self._msgs(["aa11", "bb22", "cc33"]))
        self.assertGreater(report.dropped_calls, 0)

    def test_genuinely_different_output_is_not_collapsed(self):
        m = self._msgs(["aa11", "bb22"])
        m[3]["content"] = "Chunk ID: bb22\nWall time: 0.1 seconds\nOutput:\nsomething else entirely\n"
        _out, report = focustrim._collapse_duplicates(m)
        self.assertEqual(report.dropped_calls, 0)


class ThePromptsExistTests(unittest.TestCase):
    def test_the_degenerate_notice_is_a_file_not_an_inline_string(self):
        self.assertTrue(prompts.load("rumination_guard_degenerate").strip())


if __name__ == "__main__":
    unittest.main()


class APlanStepIsAnOutcomeAtAUsablePathTests(unittest.TestCase):
    """Two exact facts about a drafted step, both walked as run-killers on
    ada-handles_nemotron-elastic_codex_pon_1785360304: a path the coder cannot use, and a step that
    prescribes a tool instead of naming an outcome."""

    def setUp(self):
        from cria import planner
        self.planner = planner
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, "tmp/read-only"))
        with open(os.path.join(self.d, "tmp/read-only/spec.yml"), "w") as fh:
            fh.write("{}")

    def test_an_ellipsis_path_is_repointed_at_the_real_file(self):
        step, note = self.planner.repoint_unusable_paths("Read /tmp/.../spec.yml and note the fields", self.d)
        self.assertEqual(step, "Read tmp/read-only/spec.yml and note the fields")
        self.assertIn("->", note)

    def test_a_path_in_crias_own_gather_dir_is_repointed(self):
        step, _ = self.planner.repoint_unusable_paths("Read /tmp/cria-gather-abc/spec.yml now", self.d)
        self.assertEqual(step, "Read tmp/read-only/spec.yml now")

    def test_an_unresolvable_path_is_removed_not_guessed(self):
        step, note = self.planner.repoint_unusable_paths("Read /etc/nope/missing.yml and do it", self.d)
        self.assertNotIn("/etc/nope", step)
        self.assertIn("removed", note)

    def test_a_real_in_workspace_path_is_left_alone(self):
        real = os.path.join(self.d, "tmp/read-only/spec.yml")
        step, note = self.planner.repoint_unusable_paths(f"Read {real} and note the fields", self.d)
        self.assertIn(real, step)
        self.assertEqual(note, "")

    def test_a_step_with_no_path_is_untouched(self):
        s = "Write a Python script that resolves an Ada Handle"
        self.assertEqual(self.planner.repoint_unusable_paths(s, self.d), (s, ""))

    def test_the_walked_killer_step_is_flagged_as_tool_prescribing(self):
        self.assertEqual(
            self.planner.step_names_tool("use exec_command to locate the GET /handles/{handle} definition"),
            "exec_command")
        self.assertEqual(
            self.planner.step_names_tool("edit_file at /tmp/x/test_r.py to add TestInvalidHandle"),
            "edit_file")

    def test_an_outcome_step_is_not_flagged(self):
        self.assertEqual(self.planner.step_names_tool(
            "Write a Python script that resolves an Ada Handle and prints the holder address"), "")


class GuardsThatCouldOnlyFailOneWayTests(unittest.TestCase):
    """Three cria texts that were true in one direction and false in the other."""

    def test_a_steer_that_is_a_bare_argument_object_is_withheld(self):
        self.assertTrue(loop._is_argument_blob(
            '{ "path": "/tmp/x/ada_handles_resolver.py", "start_line": 1, "end_line": 1 }'))
        self.assertTrue(loop._is_argument_blob('[{"line_number": 1, "text": "paths"}]'))

    def test_a_real_directive_is_not_mistaken_for_one(self):
        self.assertFalse(loop._is_argument_blob(
            "You are stuck on the failing test. Read the file, then make one targeted edit."))
        self.assertFalse(loop._is_argument_blob(
            "The step requires a README at README.md; write one describing installation."))

    def test_the_summary_hedge_doubts_both_directions(self):
        t = prompts.load("compaction_reframe")
        self.assertIn("EITHER", t)
        self.assertIn("still failing", t)
        self.assertIn("do NOT redo work", t)

    def test_the_checks_rule_allows_a_test_whose_premise_is_false(self):
        """The exception is still here, and it is still needed: 888803's test asserted
        `doesnotexist` is an unknown handle (it is registered, HTTP 200) and 360304's asserted a
        field the API does not return. The coder reached "so the test is wrong" three times and
        talked itself out of it because cria had forbidden the only correct repair.

        What changed is its PRECONDITION. "something about the outside world that you have CHECKED"
        is self-certified, and the six-language battery measured a weak model reading the failing
        assertion dump itself as the check — the one sentence in the block that authorises weakening
        a test, resting on a claim cria cannot verify. It is now scoped to an EXTERNAL system, the
        evidence must be a command run this session with its output quoted, and the test's own
        failure message is explicitly disqualified."""
        for key in ("block_nudge_preamble", "steer_checks_repeat"):
            t = prompts.load(key)
            self.assertIn("not a fix", t)                       # the prohibition stands
            self.assertIn("EXTERNAL system", t)                 # scoped to the case that motivated it
            self.assertIn("Quote the command you ran", t)       # evidence, not self-certification
            self.assertIn("own failure message is not that evidence", t)
            self.assertIn("own behaviour never qualifies", t)   # the code-under-test case is out


class AStepCannotOutliveTheRunTests(unittest.TestCase):
    """A step advanced only when the CODER volunteered "done" — so a coder that never stops calling
    tools kept the step alive forever. 1785360304 held step 1 for 107 injections with zero critic
    calls in its last 46 turns. Measured box-wide: 74% of all coder calls sit in a stretch of 30+
    turns with no critic call at all."""

    def test_the_cadence_sits_far_above_the_median_stretch(self):
        self.assertGreater(loop.STEP_CHECK_EVERY, 5)     # median stretch is 5 — ordinary work is untouched
        self.assertLess(loop.STEP_CHECK_EVERY, 30)       # the pathological tail starts well below 30

    def test_the_claim_it_sends_is_honest_about_there_being_none(self):
        t = prompts.load("periodic_step_claim")
        self.assertIn("No completion claim", t)
        # It must say WHY it is asking — a scheduled check, not a suspicion that the step is done.
        # Asserted by meaning, not by one word: the wording changed when the prompt stopped naming
        # cria to the model (rule 17), and the substance is what this test is for.
        self.assertIn("routine check", t)
        self.assertIn("open for many turns", t)
        self.assertNotIn("done", t.split(".")[0])        # it asserts nothing about the outcome

    def test_the_session_carries_its_own_once_per_tick_guard(self):
        sess = loop.PlanSession.__new__(loop.PlanSession)
        self.assertEqual(loop.PlanSession.__dataclass_fields__["step_checked_turn"].default, -1)
        self.assertIn("research_checked_turn", loop.PlanSession.__dataclass_fields__)
        del sess


class TheToolTestIsGroundedInTheUserAndTheCodeTests(unittest.TestCase):
    """Operator, 2026-08-05: those tool names are not unique words. If the user asked for one, or the
    workspace already has one, the step is describing the work — not prescribing cria's mechanics."""

    def setUp(self):
        from cria import planner
        self.planner = planner
        self.d = tempfile.mkdtemp()
        with open(os.path.join(self.d, "app.py"), "w") as fh:
            fh.write("def read_file(p):\n    return open(p).read()\n")

    def test_an_ungrounded_prescription_still_trips(self):
        self.assertEqual(self.planner.step_names_tool(
            "use exec_command to locate the GET /handles/{handle} definition", "", self.d),
            "exec_command")

    def test_a_word_the_user_asked_for_is_the_users(self):
        task = "Write a resolver. Also add a write_file helper that saves the result."
        self.assertEqual(self.planner.step_names_tool(
            "Add a write_file helper that saves the result to disk", task, self.d), "")

    def test_a_word_the_code_already_defines_is_the_codes(self):
        self.assertEqual(self.planner.step_names_tool(
            "Refactor read_file in app.py to stream instead of slurping", "", self.d), "")

    def test_a_matching_filename_grounds_it_too(self):
        with open(os.path.join(self.d, "edit_file.py"), "w") as fh:
            fh.write("x = 1\n")
        self.assertEqual(self.planner.step_names_tool("Finish edit_file.py", "", self.d), "")


class ThePeriodicStepCheckIsObserveOnlyTests(unittest.TestCase):
    """It asks and records; it does not move the plan. New authority over when a plan advances, whose
    documented predecessor turned a 1.0 into a 0.0, and which has never run live."""

    def test_the_method_records_rather_than_advances(self):
        import inspect
        src = inspect.getsource(loop.Loop._periodic_step_check)
        self.assertIn("observe_only=True", src)
        self.assertIn("OBSERVE-ONLY", src)
        # No advance in the CODE. The one mention left is the note saying what would flip it.
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotIn("self._advance(", code)

    def test_it_still_says_what_it_saw(self):
        import inspect
        src = inspect.getsource(loop.Loop._periodic_step_check)
        self.assertIn("loop.periodic_step_check", src)


class TheLiveExecutionCheckRunsOnThisMachineTests(unittest.TestCase):
    """The one check built to catch a green gate over a broken program reported "the delivered
    program was not run, because FileNotFoundError: 'python'" — because the model said `python` and
    this box, like most, ships only `python3`. The satisfaction judge read that as no evidence and
    passed a run that verify scores 1/4."""

    def setUp(self):
        from cria import execcheck
        self.execcheck = execcheck

    def test_the_ordinary_spelling_resolves_to_the_installed_one(self):
        self.assertEqual(self.execcheck.resolve_interpreter(["python", "resolve_handle.py", "goose"]),
                         ["python3", "resolve_handle.py", "goose"])

    def test_an_already_correct_command_is_untouched(self):
        self.assertEqual(self.execcheck.resolve_interpreter(["python3", "x.py"]), ["python3", "x.py"])

    def test_a_non_interpreter_program_is_never_rewritten(self):
        for argv in (["./resolver", "goose"], ["node", "x.js"], ["cargo", "run"]):
            self.assertEqual(self.execcheck.resolve_interpreter(list(argv)), argv)

    def test_the_delivered_program_actually_runs_now(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "hi.py"), "w") as fh:
                fh.write("print('resolved addr1xyz')\n")
            code, out = self.execcheck.run(d, "python hi.py")
            self.assertEqual(code, 0)
            self.assertIn("addr1xyz", out)


class AStaleFindingIsNotStampedWithTodaysLineTests(unittest.TestCase):
    """clean_gate_results re-renders EVERY gate result in the history on every prompt build, and the
    disk quote was read at render time — so a finding from five calls ago got whatever that line says
    now. Walked three times on maple-preview 1785994846: one finding, three different "flagged line
    on disk" quotes across calls 0027/0031/0032, with byte-identical MagicMock ids proving the checks
    never re-ran. The coder un-fixed a correct assertion because cria told it the fix had not landed."""

    def _raw(self, body):
        return "Chunk ID: 7f3\n" + tp._sec(0, "EXIT:0") + tp._sec(1, body) + tp._git() + "\n"

    def _ws(self, text):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "t.py"), "w") as fh:
            fh.write(text)
        return d

    def test_the_newest_gate_result_is_still_annotated(self):
        from cria.probegate import GatePlan
        ws = self._ws("import os\nx = 1\nTHE_REAL_LINE = 2\n")
        raw = self._raw("t.py:3:1: undefined name 'zzz'\nEXIT:1")
        out = probegate.clean_gate_results([{"role": "tool", "content": raw}], GatePlan(workspace=ws))
        self.assertIn("THE_REAL_LINE", out[0]["content"])

    def test_an_older_gate_result_is_not_annotated_from_todays_file(self):
        from cria.probegate import GatePlan
        ws = self._ws("import os\nx = 1\nTHE_REAL_LINE = 2\n")
        stale = self._raw("t.py:3:1: undefined name 'zzz'\nEXIT:1")
        fresh = self._raw("t.py:2:1: undefined name 'qqq'\nEXIT:1")
        out = probegate.clean_gate_results(
            [{"role": "tool", "content": stale}, {"role": "tool", "content": fresh}],
            GatePlan(workspace=ws))
        self.assertNotIn("THE_REAL_LINE", out[0]["content"])   # the stale one keeps its own words
        self.assertIn("x = 1", out[1]["content"])              # the newest still gets the quote

    def test_a_stdlib_frame_is_never_quoted_as_a_repo_finding(self):
        from cria.probegate import GatePlan
        ws = self._ws("x = 1\n")
        raw = self._raw("/usr/lib/python3.12/unittest/mock.py:1: in assert_called_once_with\nEXIT:1")
        out = probegate.clean_gate_output(raw, GatePlan(workspace=ws))
        self.assertNotIn("the flagged line on disk", out or "")


class AFindScopedFetchStillNamesTheRoutesTests(unittest.TestCase):
    """mellum2 1785996352 fetched the OpenAPI spec with find="paths" raw=true — the one combination
    that disabled BOTH the route outline and the API probe. `_extract_fetches` harvests routes only
    from the `[API endpoints (N): …]` marker, so the ledger told the model in EVERY prompt of the run
    that nothing read so far DEFINES the API's routes, with the route table twenty lines above it. It
    built the whole deliverable against the MCP tool names."""

    def setUp(self):
        from cria import webfetch
        self.wf = webfetch
        self.spec = json.dumps({"openapi": "3.0.0", "paths": {
            "/handles/{handle}": {"get": {"summary": "x" * 9000}},
            "/holders/{address}": {"get": {"summary": "y" * 9000}},
            "/mcp": {"post": {"summary": "z" * 9000}}}})

    def _fetch(self, **kw):
        self.wf._DOC_CACHE.clear()
        orig, body = self.wf.fetch, self.spec
        self.wf.fetch = lambda url, ua=None: self.wf.FetchResult(
            200, url, "application/json", body, False)
        try:
            return self.wf.fetch_nav("https://api.example.test/openapi.json", **kw)
        finally:
            self.wf.fetch = orig

    def test_the_route_marker_the_ledger_reads_survives_a_find(self):
        from cria import loop
        out = self._fetch(find="paths")
        self.assertTrue(loop._FETCH_ROUTES_RE.search(out),
                        f"no [API endpoints] marker for the ledger to harvest:\n{out[:400]}")
        self.assertIn("/handles/{handle}", out)

    def test_it_does_not_name_a_spill_file_this_branch_never_wrote(self):
        self.assertNotIn("[grep ", self._fetch(find="paths"))


class AnEmptinessClaimIsRefutableByDiskTests(unittest.TestCase):
    """mellum2 1785996352 call 0060: the confirm judge called list_dir, never read_file, then said
    resolve_handle.py "is a 1.8 KB file with no imports, no function definitions, no API calls". The
    file had all three. `_VETO_MISSING` matched none of that wording, so the disk refuter never ran
    and cria forwarded the falsehood to the coder as its own steer. It read the file, saw cria was
    wrong, and quit."""

    WHY = ("the verdict claims the script resolves handles, but the workspace has no evidence that "
           "resolve_handle.py actually contains any code — it is a 1.8 KB file with no imports, no "
           "function definitions, no API calls, and no evidence of any Ada Handles integration.")

    def test_the_walked_wording_now_trips_the_refuter(self):
        self.assertTrue(loop._VETO_MISSING.search(self.WHY))

    def test_a_plural_absence_claim_trips_it_too(self):
        self.assertTrue(loop._VETO_MISSING.search("no such files are present in the workspace"))

    def test_a_real_contradiction_still_does_not_trip_it(self):
        self.assertIsNone(loop._VETO_MISSING.search(
            "the reason says the README still needs a usage section, which contradicts a completion"))

    def test_the_facts_it_gathers_can_settle_emptiness(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "resolve_handle.py"), "w") as fh:
            fh.write("import json\nimport urllib.request\n\n\ndef resolve_handle(h):\n    return 1\n")
        seen = {}

        def ask(prompt):
            seen["prompt"] = prompt
            return "REFUTED"

        out = loop._veto_refuted_by_disk(self.WHY, d, ask=ask)
        self.assertEqual(out, "resolve_handle.py")
        self.assertIn("EXISTS on disk", seen["prompt"])
        self.assertIn("code lines", seen["prompt"])   # the fact an emptiness claim turns on


class TheSupervisorIsWatchedTooTests(unittest.TestCase):
    """The degenerate-run backstop lives in chat_watched and fires even with watch=None. The coder
    had it; the reasoner did not. maple-preview 1785994846 call 0052: the steer author repeated one
    ~250-word paragraph ~15 times, ran to finish_reason=length at 34,766 bytes, and burned 2m16s of a
    5.5-minute endgame producing nothing."""

    def test_the_reasoner_endpoint_is_wired_to_the_watched_call(self):
        src = pathlib.Path("cria/server.py").read_text()
        self.assertIn('reasoner_chat=_ep("reasoner").chat_watched,', src)
        self.assertNotIn('reasoner_chat=_ep("reasoner").chat,', src)

    def test_the_backstop_does_not_need_a_watcher_to_fire(self):
        import inspect
        from cria import upstream
        src = inspect.getsource(upstream.Upstream.chat_watched)
        i = src.index("degenerate_tail")
        # the backstop must not sit inside the `if watch is not None` arm
        self.assertNotIn("if watch is not None", src[:i].rsplit("\n", 6)[-1])
        self.assertIn("aborted is None and rumination.degenerate_tail", src)

    def test_a_degenerate_tail_is_still_what_it_detects(self):
        from cria import rumination
        self.assertTrue(rumination.degenerate_tail("Let me look at it again. " * 200))
        self.assertFalse(rumination.degenerate_tail(
            "The test fails because the mock raises a bare Exception while the code catches "
            "requests.RequestException. Fix the side_effect to raise requests.HTTPError instead."))


class ExitZeroIsNotTheSameAsWorkingTests(unittest.TestCase):
    """cria collected the model's own statement of what success looks like and never compared it.
    Exit 0 with any output was CONFIRMED, and CONFIRMED says nothing — so mellum2 1785996352's CLI,
    which exits 0 printing {"error": "HTTP Error 403: Forbidden"}, was stamped clean and the
    satisfaction judge was told nothing. verify scored that deliverable 0."""

    def setUp(self):
        from cria import execcheck
        self.execcheck = execcheck
        self.d = tempfile.mkdtemp()
        with open(os.path.join(self.d, "resolve_handle.py"), "w") as fh:
            fh.write("def main():\n    print('{\"error\": \"HTTP Error 403: Forbidden\"}')\n\n\n"
                     "if __name__ == \"__main__\":\n    main()\n")
        with open(os.path.join(self.d, "README.md"), "w") as fh:
            fh.write("Run it:\n\n```\npython3 resolve_handle.py goose\n```\n")

    def _eval(self, answer):
        intent = {"runs": True, "command": "python3 resolve_handle.py goose",
                  "success": "the resolved address, the holder address, and the total handles"}
        return self.execcheck.evaluate(self.d, intent, ask=(lambda _p: answer) if answer else None)

    def test_a_no_becomes_evidence_the_judge_can_see(self):
        r = self._eval("NO")
        self.assertEqual(r.verdict, self.execcheck.NOT_OBSERVED)
        self.assertIn("live-execution", r.marker)
        self.assertIn("not that result", r.marker)

    def test_a_yes_is_still_confirmed_and_still_silent(self):
        r = self._eval("YES")
        self.assertEqual(r.verdict, self.execcheck.CONFIRMED)
        self.assertEqual(r.marker, "")          # Rule 3 untouched

    def test_no_reasoner_keeps_todays_behaviour(self):
        r = self._eval(None)
        self.assertEqual(r.verdict, self.execcheck.CONFIRMED)
        self.assertEqual(r.marker, "")

    def test_an_unreadable_answer_keeps_todays_behaviour(self):
        r = self._eval("I am not sure, it depends")
        self.assertEqual(r.verdict, self.execcheck.CONFIRMED)
        self.assertEqual(r.marker, "")

    def test_the_question_it_asks_is_neutral(self):
        # the 4/10 version enumerated only failure modes; the 10/10 version does not
        t = prompts.load("exec_output_matches")
        self.assertIn("Answer YES if", t)
        self.assertIn("Answer NO if", t)
        self.assertNotIn("placeholder", t)


class TestsThatPassWithTheNetworkOffTests(unittest.TestCase):
    """The false-green shape: a suite that mocks the thing it tests passes whether or not the service
    exists. mellum2 1786047222 shipped five tests patching requests.get and asserting the fixture the
    test itself supplied; the gate said "no error-class problems" and the satisfaction judge — which
    had read all three files and cannot run anything — passed a run verify scores 2/4. Running the
    suite twice settles it: same discriminator verify.py uses."""

    def setUp(self):
        from cria import proberun, probediscovery
        self.proberun, self.probediscovery = proberun, probediscovery

    def _cand(self, kind, argv):
        import pathlib as _pl
        from cria.probediscovery import ProbeCandidate, ProbeCost
        return ProbeCandidate(kind=kind, command=argv, working_dir=_pl.Path("/tmp"),
                              confidence=1, expected_value=1, cost=ProbeCost.Cheap,
                              mutates_code=False, may_hang=False, may_need_services=False,
                              reason="test")

    def _plan(self, argv=("python3", "-m", "pytest", "-q")):
        """A plan whose probe-0 IS the test — the index _offline_fact reads instead of guessing."""
        return probegate.GatePlan(
            workspace="", candidates=[self._cand(self.probediscovery.ProbeKind.Test, list(argv))])

    def _sections(self, online, offline):
        return {"probe-0": online, "offline": offline}

    def _fact(self, online, offline, plan=None):
        return probegate._offline_fact(self._sections(online, offline), plan or self._plan())

    def test_a_green_suite_that_is_identical_offline_is_reported(self):
        fact = self._fact("2 passed in 0.1s\nEXIT:0", "2 passed in 0.1s\nEXIT:0")
        self.assertIn("network switched off", fact)
        self.assertIn("2", fact)

    def test_a_suite_failing_both_ways_says_nothing(self):
        # the footgun found end-to-end: on a box with no outbound network everything matches
        self.assertEqual(self._fact("1 failed, 1 passed in 0.1s\nEXIT:1",
                                    "1 failed, 1 passed in 0.1s\nEXIT:1"), "")

    def test_a_suite_that_really_needs_the_network_says_nothing(self):
        self.assertEqual(self._fact("2 passed in 0.4s\nEXIT:0",
                                    "1 failed, 1 passed in 0.1s\nEXIT:1"), "")

    def test_no_offline_section_says_nothing(self):
        self.assertEqual(probegate._offline_fact({"probe-0": "2 passed in 0.1s"}, self._plan()), "")

    def test_unittest_output_is_read_too(self):
        self.assertIn("network switched off",
                      self._fact("Ran 3 tests in 0.01s\n\nOK\nEXIT:0",
                                 "Ran 3 tests in 0.01s\n\nOK\nEXIT:0"))

    def test_a_lint_probe_is_never_re_run_offline(self):
        lint = self._cand(self.probediscovery.ProbeKind.Lint,
                          ["python3", "-m", "pyflakes", "x.py"])
        self.assertEqual(self.proberun.offline_probe_command(lint, 60), "")

    def test_a_test_that_SKIPS_when_the_service_is_gone_says_nothing(self):
        """Exit codes alone cannot carry the claim. Reproduced against a real gate: a live test
        wrapped in try/except that calls pytest.skip leaves BOTH runs at exit 0, and the sentence
        asserted no test reaches the service while one of them was hitting example.com."""
        self.assertEqual(self._fact("6 passed in 0.10s\nEXIT:0",
                                    "5 passed, 1 skipped in 0.02s\nEXIT:0"), "")

    def test_the_sentence_quotes_the_count_both_runs_agreed_on(self):
        fact = self._fact("6 passed in 0.10s\nEXIT:0", "6 passed in 0.02s\nEXIT:0")
        self.assertIn("(0f/6p)", fact)

    def test_a_runner_with_no_readable_count_claims_only_the_exit_code(self):
        # `go test` prints "ok <pkg> 0.01s" and no per-test tally — the weaker, true sentence
        fact = self._fact("ok  \thandles-resolver/handles\t0.01s\nEXIT:0",
                          "ok  \thandles-resolver/handles\t0.01s\nEXIT:0")
        self.assertIn("still succeeds with the network switched off", fact)
        self.assertNotIn("nothing in them reaches", fact)

    def test_cargos_ignored_count_is_read_as_a_skip(self):
        online = ("test result: ok. 4 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n"
                  "EXIT:0")
        offline = ("test result: ok. 3 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out\n"
                   "EXIT:0")
        self.assertEqual(self._fact(online, offline), "")
        self.assertIn("(0f/4p)", self._fact(online, online))

    def test_cargo_sums_every_test_binary_not_just_the_first(self):
        two = ("test result: ok. 2 passed; 0 failed; 0 ignored\n"
               "test result: ok. 3 passed; 1 failed; 0 ignored\n")
        self.assertEqual(probegate.runner_tally(two), "1f/5p")


class OfflineBlockIsLanguageAgnosticTests(unittest.TestCase):
    """The block is a kernel network namespace, so it is not CPython's to grant.

    The first cut wrote a sitecustomize on PYTHONPATH and skipped every non-python runner. Measured
    over the preserved suite that abstained on 3 of the 5 task families: `go test -count=1 ./...`
    (handles-go), `cargo test --no-fail-fast` (handles-rust, rust-toml-cli). A static Go binary
    ignores LD_PRELOAD and every interpreter-level patch alike; an empty netns stops it dead."""

    def setUp(self):
        from cria import proberun, probediscovery
        self.proberun, self.probediscovery = proberun, probediscovery

    def _test_cand(self, argv):
        import pathlib as _pl
        from cria.probediscovery import ProbeCandidate, ProbeCost
        return ProbeCandidate(kind=self.probediscovery.ProbeKind.Test, command=argv,
                              working_dir=_pl.Path("/tmp"), confidence=1, expected_value=1,
                              cost=ProbeCost.Cheap, mutates_code=False, may_hang=False,
                              may_need_services=False, reason="test")

    def test_go_and_cargo_suites_are_re_run_offline_too(self):
        for argv in (["go", "test", "-count=1", "./..."], ["cargo", "test", "--no-fail-fast"]):
            cmd = self.proberun.offline_probe_command(self._test_cand(argv), 60)
            self.assertIn("unshare -rn", cmd, argv[0])
            self.assertIn(argv[0], cmd)

    def test_loopback_comes_back_up_so_a_mock_server_still_passes(self):
        # a test that stands up its own server on 127.0.0.1 is exactly what this check must SEE pass
        cmd = self.proberun.offline_probe_command(
            self._test_cand(["python3", "-m", "pytest", "-q"]), 60)
        self.assertIn("ip link set lo up", cmd)

    def test_a_box_without_namespaces_prints_nothing_at_all(self):
        cmd = self.proberun.offline_probe_command(
            self._test_cand(["python3", "-m", "pytest", "-q"]), 60)
        self.assertIn("if unshare -rn -- true", cmd)   # guarded, never assumed
        self.assertTrue(cmd.rstrip().endswith("fi"))   # nothing printed outside the guard

    def test_the_block_really_stops_a_non_python_process(self):
        """Not a shape assertion — the composed command is RUN against curl."""
        import subprocess
        if subprocess.run(["unshare", "-rn", "--", "true"],
                          capture_output=True).returncode != 0:
            self.skipTest("this kernel does not grant unprivileged network namespaces")
        cmd = self.proberun.offline_probe_command(
            self._test_cand(["curl", "-s", "-m", "5", "-o", "/dev/null", "https://1.1.1.1"]), 30)
        out = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=120).stdout
        self.assertIn("EXIT:", out)
        self.assertNotIn("EXIT:0", out)   # curl could not reach the outside world

    def test_a_loopback_server_still_reaches_itself_under_the_block(self):
        import subprocess
        if subprocess.run(["unshare", "-rn", "--", "true"],
                          capture_output=True).returncode != 0:
            self.skipTest("this kernel does not grant unprivileged network namespaces")
        script = ("import socket;s=socket.socket();s.bind(('127.0.0.1',0));s.listen(1);"
                  "socket.create_connection(s.getsockname(),timeout=4).close()")
        cmd = self.proberun.offline_probe_command(
            self._test_cand(["python3", "-c", script]), 30)
        out = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=120).stdout
        self.assertIn("EXIT:0", out)


class OfflineSectionIsNeverScrapedAsAFindingTests(unittest.TestCase):
    """The offline re-run is an instrument reading, not a check.

    On a genuinely LIVE suite the offline leg is supposed to fail. clean_gate_output iterated every
    section and skipped only `git`, so those failures were harvested as error-class findings and
    handed to the coder as work — cria telling it to fix tests that pass. The false-red class,
    produced by the leg built to expose a false green."""

    P, S = probegate.SECTION_PREFIX, probegate.SECTION_SUFFIX

    def _plan(self):
        from cria import probediscovery
        from cria.probediscovery import ProbeCandidate, ProbeCost
        import pathlib as _pl
        return probegate.GatePlan(workspace="", candidates=[ProbeCandidate(
            kind=probediscovery.ProbeKind.Test, command=["python3", "-m", "pytest", "-q"],
            working_dir=_pl.Path("/tmp"), confidence=1, expected_value=1, cost=ProbeCost.Cheap,
            mutates_code=False, may_hang=False, may_need_services=False, reason="t")])

    def test_a_live_suites_offline_failure_is_not_reported_as_a_problem(self):
        raw = (f"{self.P}probe-0{self.S}\n2 passed in 0.4s\nEXIT:0\n"
               f"{self.P}offline{self.S}\n"
               "test_resolve.py:31: in test_live\n"
               "    r = requests.get(URL)\n"
               "E   OSError: [Errno 101] Network is unreachable\n"
               "1 failed, 1 passed in 0.1s\nEXIT:1\n"
               f"{self.P}git{self.S}\nabc123\n")
        out = probegate.clean_gate_output(raw, self._plan()) or ""
        self.assertNotIn("Network is unreachable", out)
        self.assertNotIn("test_resolve.py:31", out)
        self.assertIn("no error-class problems", out)

    def test_an_empty_offline_section_does_not_wedge_the_gate(self):
        # the kernel refused the namespace: the leg prints nothing, and that is not "could not run"
        raw = (f"{self.P}probe-0{self.S}\n2 passed in 0.4s\nEXIT:0\n"
               f"{self.P}offline{self.S}\n"
               f"{self.P}git{self.S}\nabc123\n")
        out = probegate.clean_gate_output(raw, self._plan()) or ""
        self.assertIn("no error-class problems", out)
        self.assertNotIn("could not", out.lower())
        self.assertNotIn("network switched off", out)
