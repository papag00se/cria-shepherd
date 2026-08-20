"""cria answered questions about the coder's files by looking at its own filesystem.

Seventy-four call sites across fourteen modules took the workspace path the harness announces — a
path on the HARNESS's filesystem — and handed it to `os.path.isdir` / `os.walk` / `open`, which
answer for the machine CRIA runs on. The two are the same machine only by accident; the likely
deployment is cria beside the model server while the harness runs on someone's workstation. When
they differ every one of those calls answers "nothing there", every mechanism built on them
abstains, and cria degrades to almost nothing while reporting no problem at all.

WHY IT COULD NOT SIMPLY ASK. cria is an HTTP server; the harness drives. cria only speaks when it is
asked something and has no outbound channel — it can put a command in the reply it is already
sending and read the answer on the NEXT request, and that is all. So a predicate needed while
composing this reply cannot get a fresh answer now. It reads what an earlier turn gathered.

What that gathering looks like is the subject of this file: one bounded `python3` program that rides
along on commands cria is already sending, whose output is stripped back out before the model sees
it, and whose absence produces "unknown" rather than "no".
"""

import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from cria import probegate, wsview, writeproxy
from wsfixture import survey


def _survey(root, sess=""):
    """Run the real survey program, exactly as the harness would, and return its raw output."""
    cmd = wsview.survey_command(sess)
    return subprocess.run(["bash", "-c", cmd], cwd=str(root),
                          capture_output=True, text=True).stdout


def _ws(**files):
    d = Path(tempfile.mkdtemp())
    for rel, body in files.items():
        p = d / rel.replace("__", "/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return d


class TheSurveyReportsWhatIsReallyThereTests(unittest.TestCase):
    def setUp(self):
        self.ws = _ws(**{"README.md": "# proj\n", "src__app.py": "def main():\n    pass\n"})
        self.view = wsview.View(str(self.ws), "s")
        self.assertTrue(wsview.apply_survey(self.view, wsview.strip_survey(_survey(self.ws))[1]))

    def test_files_and_directories(self):
        self.assertIs(self.view.isfile("README.md"), True)
        self.assertIs(self.view.isdir("src"), True)
        self.assertIs(self.view.isfile("src/app.py"), True)
        self.assertIs(self.view.isfile("nope.py"), False)

    def test_sizes_and_a_listing(self):
        self.assertEqual(self.view.size("README.md"), len("# proj\n"))
        self.assertEqual(self.view.listdir("."), ["README.md", "src"])
        self.assertEqual(self.view.listdir("src"), ["app.py"])

    def test_a_walk_matches_the_tree(self):
        got = {d: (subs, files) for d, subs, files in self.view.walk(str(self.ws))}
        self.assertEqual(got[str(self.ws)], (["src"], ["README.md"]))
        self.assertEqual(got[f"{self.ws}/src"], ([], ["app.py"]))

    def test_an_absolute_path_and_a_relative_one_are_the_same_question(self):
        self.assertIs(self.view.isfile(str(self.ws / "README.md")), True)

    def test_a_path_outside_the_workspace_is_never_answered_from_it(self):
        self.assertIsNone(self.view.isfile("/etc/passwd"))
        self.assertIsNone(self.view.read("/etc/passwd"))


class AskingForABodyTakesTwoTurnsTests(unittest.TestCase):
    """The turn-based contract, stated as a test: cria cannot fetch a file mid-decision. It records
    that it wanted one, and the NEXT survey carries it."""

    def test_the_first_ask_is_unknown_and_the_second_answers(self):
        ws = _ws(**{"notes.md": "GET /handles/{handle}\n"})
        view = wsview.View(str(ws), "sess-body")
        wsview.apply_survey(view, wsview.strip_survey(_survey(ws, "sess-body"))[1])

        self.assertIsNone(view.read("notes.md"))                     # turn 1: not known yet
        bodies, _p, _o = wsview.pending("sess-body")
        self.assertIn("notes.md", bodies)                            # ...but the question is kept

        wsview.apply_survey(view, wsview.strip_survey(_survey(ws, "sess-body"))[1])
        self.assertEqual(view.read("notes.md"), "GET /handles/{handle}\n")   # turn 2: answered

    def test_a_program_lookup_works_the_same_way(self):
        ws = _ws()
        view = wsview.View(str(ws), "sess-prog")
        self.assertIsNone(view.program("bash"))
        _b, progs, _o = wsview.pending("sess-prog")
        self.assertIn("bash", progs)
        wsview.apply_survey(view, wsview.strip_survey(_survey(ws, "sess-prog"))[1])
        self.assertEqual(view.program("bash"), "bash")

    def test_a_path_outside_the_workspace_is_asked_by_name(self):
        """A dependency cache (`~/.m2/repository`) has no listing and must not get one — cria names
        the exact path it wants tested and the harness answers about its own home."""
        ws = _ws()
        view = wsview.View(str(ws), "sess-out")
        self.assertIsNone(view.outside_kind("~"))
        _b, _p, outside = wsview.pending("sess-out")
        self.assertIn("~", outside)
        wsview.apply_survey(view, wsview.strip_survey(_survey(ws, "sess-out"))[1])
        self.assertEqual(view.outside_kind("~"), "d")

    def test_bytes_survive_the_round_trip(self):
        """A judge asked about a PNG must be told it is a PNG. A decode with errors='replace'
        destroys exactly the leading bytes that answer that, so bodies travel as bytes."""
        d = Path(tempfile.mkdtemp())
        (d / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
        view = wsview.View(str(d), "sess-bin")
        wsview.apply_survey(view, wsview.strip_survey(_survey(d, "sess-bin"))[1])
        view.read_bytes("chart.png")                                  # records the miss
        wsview.apply_survey(view, wsview.strip_survey(_survey(d, "sess-bin"))[1])
        self.assertTrue(view.read_bytes("chart.png").startswith(b"\x89PNG"))


class UnknownIsNeverRenderedAsNoTests(unittest.TestCase):
    """The whole point. A silent degradation is the one failure shape nobody can see from outside."""

    def setUp(self):
        self.view = wsview.View("/ws", "s-unknown")

    def test_every_predicate_answers_None_before_anything_is_gathered(self):
        for call in (lambda: self.view.isfile("a.py"), lambda: self.view.isdir("src"),
                     lambda: self.view.exists("a.py"), lambda: self.view.read("a.py"),
                     lambda: self.view.listdir("."), lambda: self.view.walk("."),
                     lambda: self.view.size("a.py"), lambda: self.view.program("cargo")):
            self.assertIsNone(call())

    def test_a_folded_directory_answers_unknown_rather_than_absent(self):
        """A tree too big to list in one result is folded to a count. Questions inside it have not
        been answered, and must not read as answered."""
        wsview.apply_survey(self.view, survey("X\t9000\tnode_modules"))
        self.assertIs(self.view.isdir("node_modules"), True)
        self.assertIsNone(self.view.isfile("node_modules/express/index.js"))
        self.assertIsNone(self.view.listdir("node_modules"))
        self.assertEqual(self.view.folded, ["node_modules"])

    def test_a_listing_that_did_arrive_does_answer_no(self):
        wsview.apply_survey(self.view, survey("F\t0\t3\ta.py"))
        self.assertIs(self.view.isfile("b.py"), False)


class TheSurveyRidesOnACommandCriaWasAlreadySendingTests(unittest.TestCase):
    """No extra turn, and nothing the model can see. cria has no outbound channel, so the only way
    to ask is to attach the question to a reply it is already sending."""

    def _lower(self, name, args, session="s-ride"):
        comp = {"choices": [{"message": {"tool_calls": [
            {"id": "t1", "type": "function",
             "function": {"name": name, "arguments": json.dumps(args)}}]}}]}
        writeproxy.translate_outbound(comp, {"name": "shell", "parameters": {}},
                                      injected={name}, session=session,
                                      workspace_root="/ws")
        fn = comp["choices"][0]["message"]["tool_calls"][0]["function"]
        return json.loads(fn["arguments"])["command"]

    def setUp(self):
        self.addCleanup(wsview.unbind, wsview.bind(wsview.View("/ws", "s-ride")))

    def test_a_lowered_write_carries_the_survey(self):
        self.assertIn(wsview.SURVEY_CMD_OPEN, self._lower("write_file", {"path": "a.py",
                                                                         "content": "x = 1\n"}))

    def test_a_lowered_READ_does_not(self):
        """A read's own result is already large. Pushing one past the harness's output cap would cut
        the CODER's content to pay for cria's instrumentation."""
        self.assertNotIn(wsview.SURVEY_CMD_OPEN, self._lower("read_file", {"path": "a.py"}))

    def test_the_survey_leaves_the_commands_exit_status_alone(self):
        cmd = self._lower("write_file", {"path": "a.py", "content": "x\n"})
        script = "false\n" + wsview.survey_command("s-ride")
        self.assertEqual(subprocess.run(["bash", "-c", script], capture_output=True).returncode, 1)
        self.assertIn("__cria_sv_ec", cmd)

    def test_the_gate_carries_it_too(self):
        """The one place guaranteed to happen even on a harness where cria lowers nothing."""
        self.assertIn(wsview.SURVEY_CMD_OPEN, probegate.plan_gate("/ws").script)


class TheModelNeverSeesItTests(unittest.TestCase):
    def test_the_result_is_stripped_before_anything_downstream_looks(self):
        raw = "the real output\n" + _survey(_ws(**{"a.py": "x\n"}))
        visible, survey = wsview.strip_survey(raw)
        self.assertEqual(visible, "the real output")
        self.assertIn("___CRIA_SV_tree___", survey)

    def test_the_command_is_stripped_out_of_the_gate_the_model_reads(self):
        script = probegate.plan_gate("/ws").script
        self.assertNotIn("cria", probegate._strip_gate_plumbing(script).lower())

    def test_a_result_with_no_survey_is_returned_byte_for_byte(self):
        self.assertEqual(wsview.strip_survey("plain output\n"), ("plain output\n", ""))


class TheConversationIsEvidenceTooTests(unittest.TestCase):
    """Every synthetic file tool cria lowered is in the history with its path and its bytes. A write
    proves content; an EDIT proves the content changed and is therefore no longer known."""

    def _history(self, name, args, result):
        sentinel = writeproxy._sentinel(name, json.dumps(args))
        return [
            {"role": "assistant", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "shell",
                              "arguments": json.dumps({"command": sentinel + "\ncmd"})}}]},
            {"role": "tool", "tool_call_id": "c1", "content": result},
        ]

    def _run(self, msgs, root="/ws"):
        view = wsview.View(root, "s-conv")
        token = wsview.bind(view)
        self.addCleanup(wsview.unbind, token)
        writeproxy.represent_inbound(msgs, None, workspace_root=root)
        return view

    def test_a_successful_write_proves_the_file_and_its_bytes(self):
        view = self._run(self._history("write_file", {"path": "a.py", "content": "x = 1\n"},
                                       writeproxy._WROTE))
        self.assertEqual(view.read("/ws/a.py"), "x = 1\n")
        self.assertIs(view.isfile("/ws/a.py"), True)

    def test_an_edit_proves_the_file_changed_and_NOT_what_it_now_holds(self):
        msgs = self._history("write_file", {"path": "a.py", "content": "x = 1\n"},
                             writeproxy._WROTE)
        msgs += self._history("edit_file", {"path": "a.py", "old_string": "1", "new_string": "2"},
                              writeproxy._WROTE)
        msgs[2]["tool_calls"][0]["id"] = msgs[3]["tool_call_id"] = "c2"
        view = self._run(msgs)
        self.assertIsNone(view.read("/ws/a.py"))          # cria does not know the new bytes
        self.assertIs(view.isfile("/ws/a.py"), True)      # it does still know the file is there

    def test_a_survey_in_the_history_is_folded_in_and_taken_out(self):
        ws = _ws(**{"real.py": "print(1)\n"})
        msgs = self._history("write_file", {"path": "a.py", "content": "x\n"},
                             writeproxy._WROTE + "\n" + _survey(ws))
        out = self._run(msgs, root=str(ws))
        self.assertIs(out.isfile("real.py"), True)
        self.assertNotIn("___CRIA_SV_", json.dumps(
            writeproxy.represent_inbound(msgs, None, workspace_root=str(ws))))

    def test_a_RANGED_read_is_not_recorded_as_the_file(self):
        """A `sed -n 20,40p` slice is not the file's bytes, and recording it as such would be the
        exact false fact this whole area exists to stop."""
        view = self._run(self._history("read_file", {"path": "a.py", "start_line": 20,
                                                     "end_line": 40}, "some lines"))
        self.assertIsNone(view.read("/ws/a.py"))


class AFreshListingRetiresAStaleBodyTests(unittest.TestCase):
    def test_a_body_the_new_listing_contradicts_is_forgotten(self):
        view = wsview.View("/ws", "s-stale")
        view.note_written("/ws/a.py", "x = 1\n")
        self.assertEqual(view.read("/ws/a.py"), "x = 1\n")
        wsview.apply_survey(view, survey("F\t0\t99\ta.py"))   # 99 bytes, not 6
        self.assertIsNone(view.read("/ws/a.py"))

    def test_a_body_the_new_listing_confirms_survives(self):
        view = wsview.View("/ws", "s-fresh")
        view.note_written("/ws/a.py", "x = 1\n")
        wsview.apply_survey(view, survey("F\t0\t6\ta.py"))
        self.assertEqual(view.read("/ws/a.py"), "x = 1\n")

    def test_a_file_the_new_listing_does_not_name_is_forgotten(self):
        view = wsview.View("/ws", "s-gone")
        view.note_written("/ws/a.py", "x = 1\n")
        wsview.apply_survey(view, survey("F\t0\t3\tb.py"))
        self.assertIsNone(view.read("/ws/a.py"))
        self.assertIs(view.isfile("/ws/a.py"), False)


class ASurveyOfAnotherTreeIsRefusedTests(unittest.TestCase):
    def test_a_mismatched_root_is_not_folded_in(self):
        ws = _ws(**{"a.py": "x\n"})
        view = wsview.View("/some/other/repo", "s")
        self.assertFalse(wsview.apply_survey(view, wsview.strip_survey(_survey(ws))[1]))
        self.assertIsNone(view.isfile("a.py"))

    def test_a_view_with_no_root_adopts_the_one_the_survey_reports(self):
        ws = _ws(**{"a.py": "x\n"})
        view = wsview.View(None, "s")
        self.assertTrue(wsview.apply_survey(view, wsview.strip_survey(_survey(ws))[1]))
        self.assertEqual(view.root, str(ws))

    def test_a_survey_with_no_tree_does_not_empty_what_is_known(self):
        view = wsview.View("/ws", "s")
        wsview.apply_survey(view, survey("F\t0\t3\ta.py"))
        self.assertFalse(wsview.apply_survey(view, "___CRIA_SV_meta___\nroot\t/ws\n"))
        self.assertIs(view.isfile("a.py"), True)

    def test_a_listing_CUT_IN_TRANSIT_is_refused_outright(self):
        """The harness caps its own output. A cut listing is indistinguishable from a listing of a
        smaller repo, so every file past the cut would read as deleted — under a heading saying what
        exists. The survey states its record count and closes with a marker; either one missing, or a
        count that does not match, means what came back is not the answer to anything."""
        whole = survey("F\t0\t3\ta.py\nF\t0\t3\tb.py")
        view = wsview.View("/ws", "s")
        self.assertFalse(wsview.apply_survey(view, whole[:whole.index("___CRIA_SV_done___")]))
        self.assertFalse(view.surveyed)
        self.assertFalse(wsview.apply_survey(view, whole.replace("entries\t2", "entries\t9")))
        self.assertFalse(wsview.apply_survey(view, whole.replace(wsview.SURVEY_CLOSE, "")))
        self.assertTrue(wsview.apply_survey(view, whole))

    def test_a_listing_that_hit_its_own_bound_stops_answering_no(self):
        """What it DID list is real, and what it did not is unknown — never absent."""
        view = wsview.View("/ws", "s")
        wsview.apply_survey(view, survey("F\t0\t3\ta.py", complete=False))
        self.assertIs(view.isfile("a.py"), True)
        self.assertIsNone(view.isfile("b.py"))
        self.assertFalse(view.complete)


class EachCallerPicksItsOwnSafeDirectionTests(unittest.TestCase):
    """`None` is a third answer, and the direction that is safe for it is NOT the same everywhere.
    Collapsing it into `False` for convenience is exactly how a question becomes a false fact, and
    each of these four was one line away from doing that."""

    def setUp(self):
        self.addCleanup(wsview.unbind, wsview.bind(wsview.View("/ws", "s-dir")))

    def test_a_probe_is_KEPT_when_the_coders_PATH_is_unanswered(self):
        """A dropped check reads exactly like a check that passed. Two Rust cells once ran no Rust
        tool at any gate and the empty result published as "no error-class problems"."""
        import types

        from cria import proberun
        self.assertTrue(proberun.program_is_installed(
            types.SimpleNamespace(command="cargo test", working_dir="")))

    def test_a_piece_of_ADVICE_is_WITHHELD_when_it_is_unanswered(self):
        """The opposite direction, for the opposite reason: this names a command the coder will
        TYPE, and naming one that may not exist is the false fact the whole route-selection is for."""
        from cria import dirguard
        self.assertFalse(dirguard._tool_present("bundle"))

    def test_a_file_nobody_looked_at_is_not_reported_to_a_reasoner_as_absent(self):
        """`file_snapshot` feeds a reasoner as ground truth. "does NOT exist on disk" about a file
        nobody looked at is the strongest false fact cria can state."""
        from cria import groundtruth
        snap = groundtruth.file_snapshot("/ws", ["handler.py"])[0]
        self.assertFalse(snap.exists)
        self.assertTrue(snap.unknown)
        self.assertNotIn("does NOT exist",
                         groundtruth.GroundTruth(files=[snap], lint_digest="x").render())

    def test_an_unlisted_workspace_does_not_call_the_projects_own_module_a_dependency(self):
        """`names_a_workspace_file` documents that a false YES is its safe direction: yes means cria
        stays quiet, no means it tells the coder its own module is a missing dependency."""
        from cria import probeparse
        self.assertTrue(probeparse.names_a_workspace_file("shipping", "/ws"))

    def test_an_unlisted_workspace_does_not_rewrite_a_plan_step(self):
        """`_token_is_grounded` false is the ACTING direction — the caller flags the step. A
        workspace nobody has listed cannot show a word is absent from the code."""
        from cria import planner
        self.assertEqual(planner.step_names_tool("Use web_search to find the spec",
                                                 task="build it", root="/ws"), "")


class NothingProductionAnswersFromCriasOwnDiskTests(unittest.TestCase):
    def test_the_direct_view_is_never_constructed_by_the_package(self):
        """`DirectView` answers from this process's filesystem and exists for tests. If production
        could reach it, the whole repair would be one wrong setting away from undone."""
        import pathlib
        pkg = pathlib.Path(wsview.__file__).parent
        users = [p.name for p in pkg.glob("*.py")
                 if "DirectView(" in p.read_text() and p.name != "wsview.py"]
        self.assertEqual(users, [])

    def test_an_unbound_request_gets_an_empty_view_not_the_local_disk(self):
        wsview.bind(None)
        v = wsview.current("/tmp")
        self.assertIsNone(v.listdir("/tmp"))
        self.assertFalse(v.surveyed)


if __name__ == "__main__":
    unittest.main()
