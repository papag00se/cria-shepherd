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
import inspect
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


class RefusalTests(unittest.TestCase):
    """The response is to REFUSE the re-derived tail, never to rewrite it — cria does not author
    plan steps. Returning None leaves the plan that was already correct in place."""

    def test_reassess_refuses_a_leaking_tail(self):
        src = inspect.getsource(loop.reassess_remaining)
        self.assertIn("urlgrounding.harness_tool_leaks", src)
        self.assertIn("loop.replan_tool_leak", src)
        i = src.index("leaked = urlgrounding.harness_tool_leaks")
        self.assertIn("return None", src[i:i + 300], "a leaking tail must be refused, not repaired")

    def test_it_does_not_rewrite_the_step(self):
        src = inspect.getsource(loop.reassess_remaining)
        i = src.index("leaked = urlgrounding.harness_tool_leaks")
        window = src[i:i + 300]
        for bad in (".replace(", "re.sub("):
            self.assertNotIn(bad, window, "cria must never author or edit a plan step")
