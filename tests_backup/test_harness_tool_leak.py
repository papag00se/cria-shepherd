"""A re-derived plan step must not name a CODER TOOL as code the deliverable calls or mocks.

Measured, run 20260802T001204 (mellum2, ada-handles, 0/4 — after two consecutive 3/4 runs).

The INITIAL plan was clean:
    "Write unit tests that mock the API call ..."

The living re-derivation at call 0064 rewrote it as:
    "Write unit tests for resolve_handle and total_handles_for_holder with fixtures for a known
     handle (mock web_fetch to return a successful response) ..."

`web_fetch` is one of cria's own tools. The coder built to it — resolve_handle.py shipped
`resp_text = web_fetch(url=url)` with no import and no such function; pyflakes reported "undefined
name 'web_fetch'"; every unit test mocked something that does not exist; 27 coder prompts carried
the resulting errors and the run scored 0/4.

The replanner's own system prompt already says "Any tool list you are shown belongs to the coder, so
the steps you write are things IT can do". A prompt is a request, not an enforcement.
"""
import unittest

from cria import loop, urlgrounding

TOOLS = ["web_fetch", "web_search", "read_file", "write_file", "edit_file", "exec_command"]


class LeakDetectionTests(unittest.TestCase):
    def test_the_measured_step_is_caught(self):
        step = ("Write unit tests for resolve_handle and total_handles_for_holder with fixtures for "
                "a known handle (mock web_fetch to return a successful response), a not-found handle "
                "(mock web_fetch to raise an exception)")
        self.assertEqual(urlgrounding.harness_tool_leaks(step, TOOLS), ["web_fetch"])

    def test_the_ORIGINAL_clean_step_is_not(self):
        self.assertEqual(urlgrounding.harness_tool_leaks(
            "Write unit tests that mock the API call and verify the fields", TOOLS), [])

    def test_telling_the_AGENT_to_use_its_tool_is_fine(self):
        for step in ("web_fetch the OpenAPI spec from the host the task names",
                     "Use web_search to find the library's documentation",
                     "read_file the config to learn its keys"):
            with self.subTest(step=step):
                self.assertEqual(urlgrounding.harness_tool_leaks(step, TOOLS), [])

    def test_other_library_framings_are_caught(self):
        for step in ("import web_fetch in the resolver",
                     "the script calls exec_command to run the query",
                     "patch read_file in the unit tests",
                     "stub write_file so nothing touches disk"):
            with self.subTest(step=step):
                self.assertTrue(urlgrounding.harness_tool_leaks(step, TOOLS), step)

    def test_a_real_library_with_a_similar_name_is_not_a_tool(self):
        self.assertEqual(urlgrounding.harness_tool_leaks("mock requests.get in the tests", TOOLS), [])

    def test_no_tools_and_no_text_are_safe(self):
        self.assertEqual(urlgrounding.harness_tool_leaks("mock web_fetch", []), [])
        self.assertEqual(urlgrounding.harness_tool_leaks("", TOOLS), [])

    def test_each_tool_reported_once(self):
        self.assertEqual(urlgrounding.harness_tool_leaks(
            "mock web_fetch, then patch web_fetch again, then import web_fetch", TOOLS), ["web_fetch"])


class ToolNameExtractionTests(unittest.TestCase):
    def test_names_come_out_of_the_summary_cria_renders(self):
        tools = [{"type": "function", "function": {"name": n, "description": "d"}}
                 for n in ("web_fetch", "write_file", "exec_command")]
        names = loop._tool_names(loop._coder_tools_summary(tools))
        for n in ("web_fetch", "write_file", "exec_command"):
            self.assertIn(n, names)


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))


class RefusalTests(unittest.TestCase):
    """The response is to REFUSE the re-derived tail, never to rewrite it — cria does not author
    plan steps. Returning None leaves the plan that was already correct in place.

    DRIVEN, not read. The first version searched a 300-character window of the source for
    `return None` and for the absence of `.replace(` / `re.sub(`. Both assertions slide the moment
    the function is edited above them, and neither can see what the function actually returns."""

    def _reassess(self, steps):
        """The real re-derivation, with a reasoner that proposes ``steps``."""
        import json as _json
        from cria.config import Role

        def reasoner(body, rlog):
            return _json.dumps({"choices": [{"message": {"content": _json.dumps(
                {"remaining": steps})}}]}).encode()

        tools = [{"type": "function", "function": {"name": n, "description": "d"}}
                 for n in ("web_fetch", "write_file", "exec_command")]
        return loop.reassess_remaining(
            reasoner, Role(name="reasoner", backend="local"),
            "build a handle resolver", "wrote resolve_handle.py", "write the README",
            "evidence", _Rlog(), coder_tools=loop._coder_tools_summary(tools))

    LEAKING = ("Write unit tests for resolve_handle with fixtures for a known handle "
               "(mock web_fetch to return a successful response)")   # run 20260802T001204, verbatim

    def test_a_leaking_tail_is_refused_whole(self):
        """Not repaired, not partially kept: None, so the plan already in place survives."""
        self.assertIsNone(self._reassess([self.LEAKING, "run the tests"]))

    def test_the_allowed_form_is_still_allowed(self):
        """"web_fetch the spec" is an INSTRUCTION TO THE AGENT and must survive; only a step
        treating the tool as the deliverable's own code leaks. Refusing both would quietly delete
        legitimate research steps, which is the more expensive mistake."""
        kept = self._reassess(["web_fetch the spec, then write the README"])
        self.assertEqual(kept, ["web_fetch the spec, then write the README"])

    def test_a_clean_tail_is_taken(self):
        """The control — without it, a refusal test passes on a function that refuses everything."""
        self.assertEqual(self._reassess(["write the README", "run the tests"]),
                         ["write the README", "run the tests"])

    def test_the_refusal_is_recorded_with_the_tool_that_leaked(self):
        import json as _json
        from cria.config import Role
        rlog = _Rlog()

        def reasoner(body, _rlog):
            return _json.dumps({"choices": [{"message": {"content": _json.dumps(
                {"remaining": [self.LEAKING]})}}]}).encode()

        tools = [{"type": "function", "function": {"name": "web_fetch", "description": "d"}}]
        loop.reassess_remaining(reasoner, Role(name="reasoner", backend="local"),
                                "build it", "done some", "write the README", "evidence", rlog,
                                coder_tools=loop._coder_tools_summary(tools))
        leaks = [kw for k, kw in rlog.events if k == "loop.replan_tool_leak"]
        self.assertEqual(len(leaks), 1)
        self.assertIn("web_fetch", leaks[0].get("tools", ""))

    def test_it_does_not_rewrite_the_step(self):
        """cria must never author or edit a plan step. Every step that survives is byte-identical to
        what the reasoner proposed — a repaired step would come back scrubbed instead of refused."""
        proposed = ["write the README exactly like this", "run the tests"]
        self.assertEqual(self._reassess(proposed), proposed)


class NoiseDropVisibilityTests(unittest.TestCase):
    """`loop.replan_noise` recorded counts, never WHICH steps went.

    Measured across every log day: it fired 156 times, dropped at least one step 75 times, and left
    ZERO steps kept 37 times. None of those events say what was deleted, so "did the noise judge
    delete a deliverable?" could not be answered from the logs.

    It has done exactly that twice in this ladder — run 1785625253 (unit tests, live test and README
    removed) and run 1785659842, which ended the session at 1/4 with "unit tests" and "live test"
    deleted from a plan the coverage judge had already approved. Both findings needed the raw
    captures to reconstruct.
    """

    # Asymmetric on purpose: a dropped/kept swap must be visible in the counts, not just coincide.
    STEPS = ["Write unit tests for the resolver", "grep -n 'resolved_addresses' out.txt",
             "pip install requests"]

    def _event(self):
        """Drive the real noise-drop path end to end and return the loop.replan_noise event's
        kwargs. Each reasoner call is answered by its own distinguishing SYSTEM prompt — the step
        re-derivation, the noise judgment (drop the bare grep command), and the per-drop
        deliverable-loss check (says nothing is lost, so the drop is not refused). Nothing here
        reads loop's source; a rename or reflow of the emit call can't touch it."""
        import json as _json
        from cria.config import Role

        def content(text):
            return _json.dumps({"choices": [{"message": {"content": text}}]}).encode()

        def reasoner(body, rlog):
            system = body["messages"][0]["content"]
            if "You maintain a LIVING plan" in system:
                return content(_json.dumps({"steps": self.STEPS}))
            if "the list of step numbers at the bottom" in system:
                return content("2, 3")   # drop steps 2 and 3 (1-based) — the bare shell commands
            if "the JSON verdict at the bottom" in system:
                return content(_json.dumps({"lost": ""}))
            return content("")        # coverage check etc: safe null

        rlog = _Rlog()
        loop.reassess_remaining(reasoner, Role(name="reasoner", backend="local"),
                                "build a handle resolver", "wrote resolve_handle.py",
                                "write the README", "evidence", rlog)
        return next(kw for k, kw in rlog.events if k == "loop.replan_noise")

    def test_the_event_now_carries_the_dropped_step_text(self):
        """Measured gap: 156 fires, 75 with a real drop, and none of them said WHICH step went."""
        self.assertIn("resolved_addresses", self._event()["dropped_steps"])

    def test_it_still_reports_the_counts(self):
        ev = self._event()
        self.assertEqual(ev["dropped"], 2)
        self.assertEqual(ev["kept"], 1)
