"""Seven roots from walking four nemotron runs on 2026-08-21, each with the run that measured it.

The four runs are shipping-rates-rb 1787344941 (4/100), feed-pipeline-java 1787346816 (22/100),
handles-cli-node 1787348728 (34/100) and cart-billing-go 1787349058 (19/100). Two of them share one
cause: cria threw away the part of an error that says what is wrong, and then told the coder nothing
could be parsed while the answer sat in the same prompt.
"""

import json
import pathlib
import tempfile
import unittest

from cria import loop, probediscovery, probegate, probeparse, webfetch, writeproxy, wsview

JAVAC = """[INFO] BUILD FAILURE
[ERROR] /w/src/main/java/pipeline/Importer.java:[13,30] cannot find symbol
  symbol:   class CSVParserBuilder
  location: package org.apache.commons.csv
[ERROR] [Help 1] http://cwiki.apache.org/confluence/display/MAVEN/MojoFailureException"""

MAVEN_DEP = """[INFO] BUILD FAILURE
[ERROR] Failed to execute goal on project pipeline: Could not resolve dependencies
[ERROR] Could not find artifact org.opencsv:opencsv:jar:5.9 in central (https://repo.maven.apache.org/maven2)
[ERROR] -> [Help 1]
[ERROR] [Help 1] http://cwiki.apache.org/confluence/display/MAVEN/DependencyResolutionException"""

MINITEST = """  1) Failure:
TestRates#test_oversize_surcharge_still_applies_to_free_shipping [/w/test/test_rates.rb:23]:
Expected: 12.0
  Actual: 0.0

7 runs, 7 assertions, 1 failures, 0 errors, 0 skips"""


class A1_ADiagnosticIsABlockNotALine(unittest.TestCase):
    """javac names the symbol and the package on the lines UNDER the location. Read one line at a
    time, `cannot find symbol` reaches the coder with its subject deleted — 44 prompts of it on the
    java run, which concluded an import was missing and never compiled in 89 calls."""

    def test_the_symbol_and_the_package_survive(self):
        f = probeparse.parse_generic(JAVAC)[0]
        self.assertIn("cannot find symbol", f.message)
        self.assertIn("class CSVParserBuilder", f.message)
        self.assertIn("package org.apache.commons.csv", f.message)

    def test_a_one_line_tool_is_untouched(self):
        fs = probeparse.parse_generic("src/x.py:7: error: Incompatible types\n"
                                      "src/y.py:2: error: Name 'q' is not defined")
        self.assertEqual([f.message for f in fs],
                         ["error: Incompatible types", "error: Name 'q' is not defined"])

    def test_a_following_diagnostic_does_not_get_swallowed(self):
        two = ("/w/A.java:[1,1] cannot find symbol\n"
               "  symbol: class Foo\n"
               "/w/B.java:[9,2] incompatible types\n")
        fs = probeparse.parse_generic(two)
        self.assertEqual(len(fs), 2)
        self.assertNotIn("B.java", fs[0].message)


class A2_EmptyFindingsIsNotNothingToSay(unittest.TestCase):
    """A dependency failure carries no file:line, so cria quoted the LAST error-ish line — Maven's
    help URL — while the line naming the missing artifact sat three above it. That line is the whole
    answer and it was in hand at call 17 of 89."""

    def test_the_line_that_names_the_failure_is_chosen(self):
        got = probeparse.summarize([], 1, MAVEN_DEP)
        self.assertIn("Could not find artifact org.opencsv:opencsv:jar:5.9", got)
        self.assertNotIn("cwiki.apache.org", got)

    def test_a_traceback_still_reads_bottom_up(self):
        self.assertIn("ValueError: bad thing", probeparse.summarize(
            [], 1, 'Traceback\n  File "a.py", line 3\nValueError: bad thing'))

    def test_when_every_line_is_a_pointer_the_last_one_still_ships(self):
        self.assertIn("http://x/y", probeparse.summarize([], 1, "[ERROR] [Help 1] http://x/y"))

    def test_minitest_failures_carry_their_location(self):
        """cria identified the framework and the tally and lost the located line, so five steers on
        the ruby run said "a specific line could not be parsed" with the line in the same prompt."""
        self.assertEqual(probeparse.runner_and_tally(MINITEST)[0], "minitest")
        f = probeparse.parse_generic(MINITEST)[0]
        self.assertEqual((f.file, f.line), ("/w/test/test_rates.rb", 23))


class A3_CriaDoesNotBlameTheCoderForItsOwnRequest(unittest.TestCase):
    """cria replaced a coder's search with a fetch of `rubygems.org/gems/eu-membership`, a gem that
    does not exist, and the 404 came back under "the failure is on your side"."""

    def setUp(self):
        webfetch.clear_cache()

    def test_a_url_cria_chose_is_not_the_coders_mistake(self):
        webfetch.note_substituted("s", "https://rubygems.org/gems/eu-membership")
        note = webfetch.client_error_note(404, "", ours=True)
        self.assertNotIn("on your side", note)
        self.assertIn("not yours", note)

    def test_a_url_the_coder_typed_still_is(self):
        self.assertIn("on your side", webfetch.client_error_note(404, ""))

    def test_a_host_the_task_names_may_still_be_routed_to(self):
        from cria import urlgrounding
        task = "resolve an Ada Handle via api.handle.me"
        self.assertTrue(urlgrounding.host_is_grounded("https://api.handle.me/swagger/", task))

    def test_an_invented_path_on_a_seen_host_is_not(self):
        from cria import urlgrounding
        evidence = "results from rubygems.org — https://rubygems.org/gems/countries"
        self.assertFalse(urlgrounding.url_is_grounded(
            "https://rubygems.org/gems/eu-membership", evidence))
        self.assertTrue(urlgrounding.url_is_grounded(
            "https://rubygems.org/gems/countries", evidence))


class A4_AnApprovalFromAJudgeThatNeverLookedIsNotAnApproval(unittest.TestCase):
    """The brake's justification is that "a judge that must look cannot rubber-stamp a narrative".
    On the node run it answered `{"consistent": true}` in fifteen tokens with no tool call, over a
    CLI that dies before reading its first argument."""

    def _role(self):
        from cria.config import Role
        return Role(name="reasoner", backend="local")

    def _ws(self):
        ws = tempfile.mkdtemp()
        pathlib.Path(ws, "a.py").write_text("x\n")
        return ws

    def test_an_outright_yes_does_not_confirm(self):
        def chat(body, rlog):
            return json.dumps({"choices": [{"message": {"content": json.dumps(
                {"consistent": True, "why": ""})}}]}).encode()

        ok, _ = loop._confirm_completion("Write a.py", "written", self._ws(), chat,
                                         self._role(), _Rlog(), phase="critic-confirm")
        self.assertFalse(ok)

    def test_a_yes_after_looking_does_confirm(self):
        calls = {"n": 0}

        def chat(body, rlog):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"choices": [{"message": {"content": "", "tool_calls": [
                    {"id": "l1", "type": "function", "function": {
                        "name": "list_dir", "arguments": json.dumps({"path": "."})}}]}}]}).encode()
            return json.dumps({"choices": [{"message": {"content": json.dumps(
                {"consistent": True, "why": ""})}}]}).encode()

        ok, _ = loop._confirm_completion("Write a.py", "written", self._ws(), chat,
                                         self._role(), _Rlog(), phase="critic-confirm")
        self.assertTrue(ok)

    def test_a_veto_needs_no_look(self):
        """Only the APPROVE direction is gated — refusing costs a work turn, approving ends the run."""
        def chat(body, rlog):
            return json.dumps({"choices": [{"message": {"content": json.dumps(
                {"consistent": False, "why": "there is no test file"})}}]}).encode()

        ok, why = loop._confirm_completion("Write tests", "written", self._ws(), chat,
                                           self._role(), _Rlog(), phase="critic-confirm")
        self.assertFalse(ok)
        self.assertEqual(why, "")  # no task-named path or evidence quote: prose is unsupported


class A5_EveryLanguagesFloorAnswersTheSameQuestion(unittest.TestCase):
    """Python's floor is two rungs — parse, then catch undefined names. JavaScript's was one, and
    `json = false` on an undeclared name is legal syntax that fails only when the module runs."""

    def test_javascript_gets_an_undefined_name_rung(self):
        ws = tempfile.mkdtemp()
        pathlib.Path(ws, "lookup.js").write_text("const a = 1;\n")
        cmds = [" ".join(c.command) for c in
                probediscovery.lint_floor_candidates(pathlib.Path(ws))]
        self.assertTrue(any("eslint" in c and "no-undef" in c for c in cmds), cmds)

    def test_that_rung_is_crias_own_and_is_not_shown_to_the_coder(self):
        ws = tempfile.mkdtemp()
        pathlib.Path(ws, "lookup.js").write_text("const a = 1;\n")
        for c in probediscovery.lint_floor_candidates(pathlib.Path(ws)):
            if "eslint" in c.command:
                self.assertTrue(c.composed_by_cria)

    def test_the_clean_sentence_names_what_actually_ran(self):
        """It said "syntax and lint only" whatever the plan held, so on a JS project with no linter
        composed cria claimed a lint pass that never happened."""
        from cria import prompts
        words = prompts.load_map("no_tests_found")
        self.assertIn("{{COVERED}}", words["no_command"])
        self.assertNotIn("syntax and lint only", words["no_command"])


class A6_ARedThatIsNotMovingDoesNotHoldTheCheckBack(unittest.TestCase):
    """"fix the failing repository tests" starts red by construction, so the latch closed on the
    first gate and never opened: 76 skips on the ruby run, 68 of them gate-red, and nothing ever
    asked why three of five deliverables were untouched."""

    def _blocked(self, stall):
        return loop._satisfaction_blocker(steer="", rewritten=False, done_probe=False,
                                          gate_red=True, gate_stall=stall)

    def test_a_fresh_red_still_holds(self):
        self.assertEqual(self._blocked(1), "gate-red")

    def test_the_same_red_twice_over_stops_holding(self):
        self.assertEqual(self._blocked(loop.RED_HOLDS_SATISFACTION_FOR), "")

    def test_the_other_blockers_are_untouched(self):
        self.assertEqual(loop._satisfaction_blocker(steer="fix it", rewritten=False,
                                                    done_probe=False, gate_red=False), "steer")


class A7_CriaDoesNotReadItsOwnLoweringAsTheCodersWork(unittest.TestCase):
    """The survey program contains `if len(files) > FOLD_AT:`. The redirect matcher read that `>` as
    one and cria told the model `FILE FOLD_AT — does NOT exist on disk`, naming its own constant."""

    def setUp(self):
        self.token = wsview.bind(wsview.DirectView())
        self.addCleanup(wsview.unbind, self.token)

    def test_a_lowered_write_reports_the_file_the_coder_named(self):
        lowered = (writeproxy._sentinel("write_file",
                                        json.dumps({"path": "lib/a.rb", "content": "x"}))
                   + "\npython3 - <<'EOF'\nif len(files) > FOLD_AT:\n    pass\nEOF")
        got = loop._write_path({"name": "exec_command",
                                "arguments": json.dumps({"cmd": lowered})})
        self.assertEqual(got, "lib/a.rb")

    def test_a_shell_redirect_the_coder_really_wrote_is_still_read(self):
        got = loop._write_path({"name": "exec_command",
                                "arguments": json.dumps({"cmd": "echo hi > out.txt"})})
        self.assertEqual(got, "out.txt")

    def test_a_plain_write_is_unchanged(self):
        got = loop._write_path({"name": "write_file",
                                "arguments": json.dumps({"path": "a/b.py", "content": "x"})})
        self.assertEqual(got, "a/b.py")


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


if __name__ == "__main__":
    unittest.main()
