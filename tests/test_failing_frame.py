"""A check must point at a line the coder can actually edit.

parse_pytest took `locs[-1]` — the LAST traceback frame — and its docstring claimed that "gets the
real test-file location". It does not. When a test mocks something and the mock raises, the deepest
frame is inside the interpreter's own library.

MEASURED across every captured coder prompt carrying a check block (n=2,836): a stdlib or
site-packages file:line appears 7,888 times across 48 runs — mock.py alone 2,680 times. Live in run
20260802T003331 (mellum2, ada-handles, 3/4), the last steer of the run read:

    • /usr/lib/python3.12/unittest/mock.py:1193: Exception: 404
    • /usr/lib/python3.12/unittest/mock.py:1193: Exception: Network error
"""
import unittest

from cria import probeparse


class OwnCodeTests(unittest.TestCase):
    def test_workspace_files_are_the_coders_own(self):
        for p in ("test_resolve.py", "src/app.py", "/home/u/proj/tests/t.py", "./a/b.py"):
            with self.subTest(path=p):
                self.assertTrue(probeparse._own_code(p))

    def test_interpreter_and_package_files_are_not(self):
        for p in ("/usr/lib/python3.12/unittest/mock.py",
                  "/usr/lib64/python3.11/ast.py",
                  "/w/.venv/lib/python3.12/site-packages/_pytest/python.py",
                  "/usr/lib/python3/dist-packages/x.py",
                  "/w/venv/lib/python3.12/site-packages/pluggy/__init__.py"):
            with self.subTest(path=p):
                self.assertFalse(probeparse._own_code(p))


class FrameChoiceTests(unittest.TestCase):
    def test_the_measured_case_picks_the_test_file(self):
        locs = [("test_resolve.py", "28", "in test_resolve_404"),
                ("/usr/lib/python3.12/unittest/mock.py", "1193", "Exception: 404")]
        self.assertEqual(probeparse._failing_frame(locs)[0], "test_resolve.py")

    def test_the_DEEPEST_own_frame_wins_not_the_shallowest(self):
        locs = [("tests/conftest.py", "3", "in fixture"),
                ("tests/test_x.py", "40", "in test_x"),
                ("/usr/lib/python3.12/unittest/mock.py", "1193", "boom")]
        self.assertEqual(probeparse._failing_frame(locs)[:2], ("tests/test_x.py", "40"))

    def test_an_all_foreign_traceback_still_reports_something(self):
        # Honest fallback: the failure really is outside the workspace; saying so beats inventing.
        locs = [("/usr/lib/python3.12/unittest/mock.py", "1193", "boom")]
        self.assertEqual(probeparse._failing_frame(locs)[0], "/usr/lib/python3.12/unittest/mock.py")

    def test_an_ordinary_failure_is_unchanged(self):
        locs = [("test_x.py", "12", "in test_a")]
        self.assertEqual(probeparse._failing_frame(locs)[:2], ("test_x.py", "12"))


class EndToEndTests(unittest.TestCase):
    PYTEST_OUTPUT = """
=================================== FAILURES ===================================
__________________________ test_resolve_404_returns_na _________________________

    def test_resolve_404_returns_na(mock_get):
        mock_get.return_value.raise_for_status.side_effect = Exception("404")
>       result = resolve("goose")

test_resolve.py:28: in test_resolve_404_returns_na
    result = resolve("goose")
resolve_handle.py:14: in resolve
    response.raise_for_status()
/usr/lib/python3.12/unittest/mock.py:1193: Exception
E       Exception: 404
=========================== short test summary info ============================
FAILED test_resolve.py::test_resolve_404_returns_na - Exception: 404
"""

    def test_the_finding_names_a_file_the_coder_can_edit(self):
        findings = probeparse.parse_pytest(self.PYTEST_OUTPUT)
        self.assertTrue(findings, "the failure must still be reported")
        for f in findings:
            with self.subTest(file=f.file):
                self.assertTrue(probeparse._own_code(f.file),
                                f"pointed the coder at {f.file}, which it cannot edit")

    def test_the_error_message_still_arrives_whole(self):
        findings = probeparse.parse_pytest(self.PYTEST_OUTPUT)
        self.assertTrue(any("404" in (f.message or "") for f in findings))


class SummarizeOrderingTests(unittest.TestCase):
    """_failing_frame fixed parse_pytest only. Every other parser still reported whatever file:line
    it found, and the next run proved it: run 20260802T014434 showed the coder
    /usr/lib/python3.12/json/decoder.py:355, json/decoder.py:337 and json/__init__.py:346, thirteen
    times each, from a JSONDecodeError traceback parse_pytest never touches."""

    def _f(self, file, line, msg):
        return probeparse.Finding(file, line, None, msg)

    def test_the_coders_own_file_is_summarised_first(self):
        findings = [self._f("/usr/lib/python3.12/json/decoder.py", 355, "JSONDecodeError"),
                    self._f("resolve_handle.py", 22, "JSONDecodeError")]
        out = probeparse.summarize(findings, 1, "")
        self.assertTrue(out.startswith("resolve_handle.py:22"), out)

    def test_the_foreign_finding_is_NOT_deleted(self):
        findings = [self._f("/usr/lib/python3.12/json/decoder.py", 355, "JSONDecodeError"),
                    self._f("resolve_handle.py", 22, "boom")]
        self.assertEqual(len(probeparse.prefer_own_code(findings)), 2)

    def test_an_all_foreign_list_is_left_alone(self):
        findings = [self._f("/usr/lib/python3.12/json/decoder.py", 355, "JSONDecodeError")]
        self.assertEqual(probeparse.prefer_own_code(findings), findings)
        self.assertIn("decoder.py:355", probeparse.summarize(findings, 1, ""))

    def test_order_among_own_files_is_preserved(self):
        a, b = self._f("a.py", 1, "first"), self._f("b.py", 2, "second")
        self.assertEqual(probeparse.prefer_own_code([a, b]), [a, b])

    def test_an_empty_list_is_safe(self):
        self.assertEqual(probeparse.prefer_own_code([]), [])
