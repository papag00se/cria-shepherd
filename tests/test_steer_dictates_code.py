"""Whether a directive QUOTES the coder's failing line or DICTATES a fix is a judgment, and it was
being made by a regex. That regex was wrong in both directions:

  * it dropped whole steers on a leading `import ` — a quote of the file under discussion, which the
    author's own prompt explicitly permits;
  * it fired exactly TWICE in the whole capture history, while the directive telling the coder to add
    `pytest.register_pytest_mark("live")` — not a real function — sailed through, because that code
    sat inline in prose with no fence and no line-leading keyword (run 20260801T232511 call 0132).

Chasing inline code with more pattern is deterministic code doing a judgment's job. The pattern is
now a TRIGGER for one focused question.
"""
import unittest

from cria import loop


class _Rlog:
    def __init__(self): self.events = []
    def emit(self, kind, **kw): self.events.append((kind, kw))


# Verbatim from run 20260801T232511 call 0132 — the steer the coder actually received.
REAL_DICTATION = ("UNSTUCK You are stuck because pytest is warning about an unknown mark named live. "
                  "The fix is to register the mark so pytest knows it is valid. 1. Register the mark "
                  "in resolve_handle.py (both already have register_assert_rewrite, so just add one "
                  'more line): pytest.register_pytest_mark("live")')

REAL_QUOTE = ("Two bugs each named by the check: resolve_handles.py line 14 has data=response.json() "
              "where one mock's json is a dict, not callable; fix the mock so it matches how line 14 "
              "uses it, then re-run the failing test.")


class TriggerTests(unittest.TestCase):
    def test_inline_dotted_calls_now_trip_the_trigger(self):
        # The exact miss: no fence, no line-leading keyword, and it reached the coder.
        self.assertTrue(loop._CODE_SHAPED.search(REAL_DICTATION))

    def test_the_trigger_still_catches_what_it_always_did(self):
        for text in ("here:\n```python\nx = 1\n```", "\nimport os\n", "\n$ pytest -q\n"):
            with self.subTest(text=text[:20]):
                self.assertTrue(loop._CODE_SHAPED.search(text))

    def test_plain_prose_never_trips_it(self):
        self.assertIsNone(loop._CODE_SHAPED.search(
            "You keep rewriting the same file. Read it first, then change only the line the check names."))


class OneQuestionTests(unittest.TestCase):
    def test_a_DESCRIBES_verdict_keeps_a_steer_the_regex_would_have_eaten(self):
        asked = {}

        def ask(system, user):
            asked["system"] = system
            return "DESCRIBES"

        self.assertFalse(loop._dictates_code(REAL_QUOTE, ask))
        self.assertIn("DIRECTIVE:", asked["system"])
        self.assertIn("response.json()", asked["system"])

    def test_a_DICTATES_verdict_drops_it(self):
        self.assertTrue(loop._dictates_code(REAL_DICTATION, lambda s, u: "DICTATES"))

    def test_no_question_is_asked_when_nothing_is_code_shaped(self):
        calls = []

        def ask(system, user):
            calls.append(system)
            return "DESCRIBES"

        self.assertFalse(loop._dictates_code("Read the file before you rewrite it.", ask))
        self.assertEqual(calls, [])          # the pre-filter is what makes the call affordable

    def test_the_verdict_survives_a_models_decoration(self):
        for ans in ("DESCRIBES.", "  describes  ", "`DESCRIBES`", "DESCRIBES — it only quotes."):
            with self.subTest(ans=ans):
                self.assertFalse(loop._dictates_code(REAL_QUOTE, lambda s, u, a=ans: a))

    def test_an_unreadable_answer_leaves_the_pre_filters_verdict_STANDING(self):
        # The safe null is today's behaviour, so this change can only move steers from dropped to
        # delivered, never the other way.
        for ans in ("", "I think it depends", None, "MAYBE"):
            with self.subTest(ans=ans):
                self.assertTrue(loop._dictates_code(REAL_DICTATION, lambda s, u, a=ans: a))

    def test_no_reasoner_at_all_is_the_same_safe_null(self):
        self.assertTrue(loop._dictates_code(REAL_DICTATION, None))


def tool_result(text):
    return {"role": "tool", "tool_call_id": "c1", "content": text}


def wrote(path, content):
    import json as _json
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "write_file",
                                         "arguments": _json.dumps({"path": path, "content": content})}}]}


class WiringTests(unittest.TestCase):
    def test_the_gate_passes_its_reasoner_through(self):
        """Driven for real: the `ask` handed to `_grounded_steer_or_none` must be the one
        `_dictates_code` actually calls, carrying the SAME directive — proven with a marker only
        the real wiring could have carried into the question."""
        asked = {}

        def ask(system, user):
            asked["system"] = system
            return "DICTATES"

        directive = 'UNSTUCK UNIQUE_MARKER_ABC pytest.register_pytest_mark("live")'
        loop._grounded_steer_or_none(directive, "evidence", _Rlog(), ask=ask)
        self.assertIn("UNIQUE_MARKER_ABC", asked.get("system", ""))

    def test_author_steer_supplies_one_on_both_of_its_paths(self):
        """BOTH internal branches (tooled — a real workspace_root — and toolless) must hand
        `_grounded_steer_or_none` a REAL reasoner-backed ask, not None, so a code-shaped
        conclusion still gets the one-question check on either path. Proven by driving each
        branch end to end and watching the dictates-code question actually fire, carrying the
        directive's own marker — a call that could only happen with a live ask wired in."""
        import json as _json
        import tempfile

        def reasoner(diagnose_reply, seen):
            def chat(body, rlog):
                sysm = body["messages"][0].get("content", "")
                if "DIRECTIVE:" in sysm:
                    seen["dictates_check_ran"] = True
                    seen["marker_seen"] = "UNIQUE_MARKER_XYZ" in sysm
                    return _json.dumps({"choices": [{"message": {"content": "DESCRIBES"}}]}).encode()
                return _json.dumps({"choices": [{"message": {"content": diagnose_reply}}]}).encode()
            return chat

        gs = loop.GuardState()
        body = {"messages": [{"role": "user", "content": "build it"}], "tools": []}
        diagnose = 'UNSTUCK UNIQUE_MARKER_XYZ pytest.register_pytest_mark("live")'

        seen_toolless = {}
        loop.author_steer(reasoner(diagnose, seen_toolless), None, "", gs, body, _Rlog(),
                          condition="wheel_spin")
        self.assertTrue(seen_toolless.get("dictates_check_ran"), "toolless path never asked")
        self.assertTrue(seen_toolless.get("marker_seen"))

        seen_tooled = {}
        with tempfile.TemporaryDirectory() as ws:
            loop.author_steer(reasoner(diagnose, seen_tooled), None, ws, gs, body, _Rlog(),
                              condition="wheel_spin")
        self.assertTrue(seen_tooled.get("dictates_check_ran"), "tooled path never asked")
        self.assertTrue(seen_tooled.get("marker_seen"))

    def test_a_DICTATES_steer_is_still_delivered_not_dropped(self):
        """The operator's 2026-08-04 ruling stands: the steer SHIPS. The drop's harm evidence came
        from a BLIND author (since fixed) and the 08-01 dense passes were carried by sighted
        dictation."""
        rlog = _Rlog()
        out = loop._grounded_steer_or_none(REAL_DICTATION, "evidence", rlog,
                                           ask=lambda s, u: "DICTATES")
        self.assertTrue(out)                                   # delivered, never None
        self.assertIn("loop.steer_dictated_code", [k for k, _ in rlog.events])

    def test_the_prose_survives_and_the_invented_call_does_not(self):
        """The ruling's own reasoning, enforced. It turned on SIGHTED versus BLIND dictation, so the
        question is not "does this contain code" but "did the author read it or invent it" — and
        cria holds what it OBSERVED (tool results + bytes the coder wrote; see loop._observed_code,
        which is the haystack now — the composed prompt was carrying the coder's own prose).

        REAL_DICTATION is the measured example: `pytest.register_pytest_mark("live")` is not a real
        function, and it reached a coder because it sat inline in prose with no fence. The diagnosis
        around it is correct and worth keeping."""
        rlog = _Rlog()
        out = loop._grounded_steer_or_none(REAL_DICTATION, "evidence", rlog,
                                           ask=lambda s, u: "DICTATES",
                                           messages=[tool_result("PytestUnknownMarkWarning: live")])
        self.assertIn("unknown mark named live", out)          # the diagnosis survives
        self.assertNotIn("register_pytest_mark", out)          # the invention does not
        self.assertIn("code removed", out)                     # and the removal is disclosed

    def test_a_quote_of_something_cria_showed_the_author_survives(self):
        """The case the ladder passes were built on: a steer quoting the coder's own failing line.

        It lives in a TOOL RESULT — a compiler or test error — which is exactly why narrowing the
        haystack to what cria observed does not touch it."""
        rlog = _Rlog()
        directive = 'Your assertion cart.go:22: if got != 48.58 { is the line that fails. Fix the total.'
        out = loop._grounded_steer_or_none(directive, "unused", rlog,
                                           ask=lambda s, u: "DICTATES",
                                           messages=[tool_result("cart.go:22: if got != 48.58 {")])
        self.assertEqual(out, directive)

    def test_a_quote_of_what_the_coder_actually_WROTE_survives(self):
        """The other half of observation: bytes the coder put on disk are real code, whatever the
        coder believes about them. They live in the write_file arguments."""
        rlog = _Rlog()
        directive = 'You wrote self.assertEqual(total, 48.58) — change the expected value.'
        out = loop._grounded_steer_or_none(
            directive, "unused", rlog, ask=lambda s, u: "DICTATES",
            messages=[wrote("t.py", "self.assertEqual(total, 48.58)")])
        self.assertEqual(out, directive)

    def test_a_line_the_coder_only_TALKED_about_does_not_ground_it(self):
        """THE measured bug. nemotron-elastic/python 0197: the coder mused "return self._send(201,
        {...})? ... That seems odd" and cria's steer ordered exactly that. Prose is not observation."""
        rlog = _Rlog()
        directive = 'Replace the handler line with return self._send(201, {"error": "internal"})'
        out = loop._grounded_steer_or_none(
            directive, "unused", rlog, ask=lambda s, u: "DICTATES",
            messages=[tool_result("orders/app.py:54: 500 returned on exception"),
                      {"role": "assistant",
                       "content": 'return self._send(201, {"error": "internal"})? That seems odd.'}])
        self.assertNotIn("_send(201", out)
        self.assertIn("code removed", out)

    def test_with_nothing_observed_nothing_is_stripped(self):
        """cria cannot call code invented when it has nothing to check against."""
        rlog = _Rlog()
        out = loop._grounded_steer_or_none(REAL_DICTATION, "", rlog, ask=lambda s, u: "DICTATES")
        self.assertEqual(out, REAL_DICTATION)


class ACutReplyIsNotADirectiveTests(unittest.TestCase):
    """The tool-inspecting steer branch took `_completion_text(comp)` with no truncation check, while
    its toolless sibling `summarize()` has had one since the truncation guard landed and
    `live_execution_marker` says it outright: "a cut intent is not an intent".

    Walked on ada-handles_fabliq_codex_pon_1785721353 call 0139: the author returned
    finish_reason=length with 8,192 tokens of the coder's OWN pytest failures repeated about nine
    times, and cria delivered roughly 27,000 characters of that to the coder in cria's voice — under
    a prompt asking for "a SHORT directive (under 120 words)". The real directive was sitting in the
    discarded reasoning_content."""

    def test_the_tooled_author_path_drops_a_cut_reply_and_traces_it(self):
        """Driven end to end: a reply that hits finish_reason=length on the tooled branch must be
        dropped (never delivered as a directive) and the drop must be traced, never silent."""
        import json as _json
        import tempfile

        def chat(body, rlog):
            return _json.dumps({"choices": [{"message": {"content": "half a directive that never fin"},
                                            "finish_reason": "length"}]}).encode()

        gs = loop.GuardState()
        body = {"messages": [{"role": "user", "content": "build it"}], "tools": []}
        rlog = _Rlog()
        with tempfile.TemporaryDirectory() as ws:
            out = loop.author_steer(chat, None, ws, gs, body, rlog, condition="wheel_spin")
        self.assertIsNone(out)
        self.assertIn("loop.steer_truncated", [k for k, _ in rlog.events])

    def test_the_toolless_sibling_still_has_its_own_guard(self):
        """`summarize` — the primitive the toolless branch calls — refuses a reply cut at the
        output cap on its OWN, rather than depending on the tooled branch's check."""
        import json as _json

        def chat(body, rlog):
            return _json.dumps({"choices": [{"message": {"content": "partial nonsense"},
                                            "finish_reason": "length"}]}).encode()

        out = loop.summarize(chat, None, "sys", "user", _Rlog(), phase="x", retry_off=False)
        self.assertEqual(out, "")


class ARuminatingReplyIsNotADirectiveTests(unittest.TestCase):
    """The rumination guard is wired to the streaming coder path alone (classify.py says so
    outright); the steer author's calls are non-streamed, so a ruminating reply that STOPPED
    cleanly sailed through every guard. Walked on ada-handles_maple-preview_codex_poff_1785956867
    call 0055: the answer-NOW retry returned one first-person paragraph repeated ~45 times
    (finish=stop, not truncated), and cria injected the whole ~10KB blob verbatim as ⟦ctx:steer⟧
    at call 0056. Same run, call 0020, delivered a triple-duplicated ~21KB dictation. A reply
    whose tail is a periodic repetition of one block is the author looping, not directing —
    the same pure detector the stream watcher uses (rumination.degenerate_tail) decides, and
    the reply is dropped like a truncated one (a safe null, never delivered noise)."""

    _PARA = ("The tests are failing - 4 tests fail because of test/source mismatch (missing "
             "api_status key in simulated mode, overly strict hex validation). The tests don't "
             "represent real progress. I need to fix these issues so tests pass, then run live "
             "tests to verify the API integration works. After fixing these issues and running "
             "live tests, I need to create a README. ")

    def test_the_walked_blob_is_detected(self):
        self.assertTrue(loop._ruminating_reply(self._PARA * 30))

    def test_a_short_directive_is_not(self):
        self.assertFalse(loop._ruminating_reply(
            'You added api_status with the wrong value: the tests expect "simulated". '
            'Change it in resolve_adaptive_handle.py and rerun pytest.'))

    def test_a_long_but_varied_reply_is_not(self):
        varied = "\n".join(f"tests/test_x.py:{n}: AssertionError: value {n} mismatch "
                           f"in case {n * 7 % 13}" for n in range(80))
        self.assertFalse(loop._ruminating_reply(varied))

    def test_both_author_branches_drop_it_and_trace_it(self):
        """Both the tooled and toolless branches must run the SAME rumination check — a periodic
        repetition of one block dropped, and the drop traced — driven end to end on each branch
        rather than counted as mentions of the detector's name in the source."""
        import json as _json
        import tempfile

        def chat(body, rlog):
            return _json.dumps({"choices": [{"message": {"content": self._PARA * 30},
                                            "finish_reason": "stop"}]}).encode()

        gs = loop.GuardState()
        body = {"messages": [{"role": "user", "content": "build it"}], "tools": []}

        rlog_toolless = _Rlog()
        out_toolless = loop.author_steer(chat, None, "", gs, body, rlog_toolless, condition="wheel_spin")
        self.assertIsNone(out_toolless)
        self.assertIn("loop.steer_degenerate", [k for k, _ in rlog_toolless.events])

        rlog_tooled = _Rlog()
        with tempfile.TemporaryDirectory() as ws:
            out_tooled = loop.author_steer(chat, None, ws, gs, body, rlog_tooled, condition="wheel_spin")
        self.assertIsNone(out_tooled)
        self.assertIn("loop.steer_degenerate", [k for k, _ in rlog_tooled.events])


class TheTriggerIsNotSpelledInPythonTests(unittest.TestCase):
    """The dictation guard never ran on half the battery.

    _CODE_SHAPED decides whether one focused reasoner call is worth making. It listed `def `,
    `import `, `pip install`, `pytest`, `sudo`, `sed -i`, `cat ` — Python and POSIX. Java, Rust, Go
    and Node match none of that, so on those languages the guard did not exist.

    Scope, stated honestly: this trigger asks "is there code here to copy". It is not the guard for
    "the steer picked the implementation" — ternary-bonsai/java 0040's "drop the dependency entirely
    and handle CSV parsing inline in Importer.java" is pure prose and would not fire on any shape
    test; that one belongs to the steer_diagnose rule about choosing an implementation. What is fixed
    here is narrower and real: a directive that quotes or invents an actual Java, Rust, Go or Node
    line now reaches the reasoner, where before only Python and POSIX did.

    Over-firing is cheap by design — the reasoner still rules quote-versus-dictation — so the shapes
    are broad. What must not happen is firing on ordinary prose.
    """

    def fires(self, text):
        return bool(loop._CODE_SHAPED.search(text))

    def test_every_language_in_the_battery_is_reachable(self):
        for lang, line in (("java", "Set WORKERS_ENABLED = true;"),
                           ("rust", "let total: u32 = parse(s)?;"),
                           ("go", "if err != nil {"),
                           ("node", "const x = require('commander');"),
                           ("ruby", "Countries::Country.new('FR')"),
                           ("python", "def total(self):")):
            with self.subTest(lang=lang):
                self.assertTrue(self.fires(line))

    def test_a_shell_command_in_any_ecosystem_fires(self):
        # A flag is what separates a command from a sentence by shape. `npm run build` has none and
        # reads exactly like prose ("please run build"), so it does not fire — an accepted miss: the
        # cost is one reasoner call not made, never a wrong ruling.
        for cmd in ("mvn -q test", "cargo build --release", "go test -v ./...", "npm --prefix . ci"):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.fires(cmd))

    def test_ordinary_prose_does_not(self):
        for prose in (
                "Read the file and fix what the failing check names.",
                "The build failed because the module is missing from the manifest.",
                "Open cart.go - the error is on the line the compiler names.",
                "Run the tests again before editing anything else."):
            with self.subTest(prose=prose[:32]):
                self.assertFalse(self.fires(prose))

    def test_the_python_shapes_still_fire(self):
        """Kept — they cost nothing and still match first on Python."""
        for line in ("import os", "assert x == 1", "class Cart:"):
            with self.subTest(line=line):
                self.assertTrue(self.fires(line))


class ThePromptAndTheMatcherAgreeTests(unittest.TestCase):
    """The one word this mechanism turns on, asserted in both places it lives.

    The matcher fails CLOSED: anything that is not `DESCRIBES` is treated as a dictation and the
    steer is dropped. So if the prompt's wording moved — a rename, a translation, a tidy-up — the
    comparison would stop matching and EVERY steer would be delivered, silently, with no failure
    anywhere. A named constant on the other word (`DICTATES`, which the code never tests for) was a
    drift guard pointing away from the drift.

    This is structural on purpose: the prompt is a data file and the matcher is code, so no input
    exercises "these two agree"."""

    def test_the_matchers_sentinel_is_offered_by_the_prompt(self):
        from cria import prompts
        self.assertIn(loop._DESCRIBES, prompts.load("steer_dictates_code"))

    def test_the_other_verdict_is_offered_too(self):
        """Both words have to be on the menu, or the model is being asked a question with one answer."""
        from cria import prompts
        self.assertIn("DICTATES", prompts.load("steer_dictates_code"))

    def test_the_matcher_compares_against_the_named_constant(self):
        import inspect
        src = inspect.getsource(loop._dictates_code)
        self.assertIn("_DESCRIBES", src)
        self.assertNotIn('!= "DESCRIBES"', src)


if __name__ == "__main__":
    unittest.main()
