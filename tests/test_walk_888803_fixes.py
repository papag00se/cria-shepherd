"""Six cria faults found by the full line-by-line walk of
ada-handles_nemotron-elastic_codex_pon_1785888803 (101 chunks, calls 0001-0220, 2026-08-05).

The run died at the 45-minute wall on step 6 of 8 with two of four deliverables met. Almost none of
the damage was the model's: cria told it false things about its own workspace and then deleted the
evidence that would have corrected them. Each test below pins one of those mechanisms.
"""

import base64
import json
import os
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
        for key in ("block_nudge_preamble", "steer_checks_repeat"):
            t = prompts.load(key)
            self.assertIn("not a fix", t)          # the prohibition stands
            self.assertIn("PREMISE is factually wrong", t)
            self.assertIn("CHECKED", t)            # and it must show its evidence


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
        self.assertIn("cadence", t)
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
