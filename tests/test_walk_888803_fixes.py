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

from cria import config, editrecovery, focustrim, loop, prompts
from cria.writeproxy import translate_outbound
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


class ThePromptsExistTests(unittest.TestCase):
    def test_the_degenerate_notice_is_a_file_not_an_inline_string(self):
        self.assertTrue(prompts.load("rumination_guard_degenerate").strip())


if __name__ == "__main__":
    unittest.main()
