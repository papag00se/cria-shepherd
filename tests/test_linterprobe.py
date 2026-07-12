"""The always-available syntax floor (cria.linterprobe) and the fresh-facts provider
(cria.groundtruth): ports of the unit tests from codex-local's linter_probe.rs and
ground_truth.rs (spec: linter-gate.md §1.5, §2.5), plus injected-runner tests for the
interpreter rules a real subprocess can't deterministically reach (absent binaries)."""
import os
import subprocess
import tempfile
import unittest

from cria.groundtruth import (DEFAULT_FILE_CAP, FileSnapshot, GroundTruth,
                              RepeatedAction, file_len, file_snapshot, lint_digest)
from cria.linterprobe import LinterReport, run_linter_probe


def local_runner(argv, cwd, timeout_s):
    """Test-only subprocess runner satisfying the injectable Runner protocol — cria
    itself never executes; whatever host owns the workspace does. FileNotFoundError
    (absent binary) propagates, per the protocol contract."""
    try:
        proc = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        return (None, (e.stdout or b"").decode("utf-8", "replace"),
                (e.stderr or b"").decode("utf-8", "replace"), True)
    return (proc.returncode, proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"), False)


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path


class _TmpDirTest(unittest.TestCase):
    def tmpdir(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return d.name


class TestLinterProbe(_TmpDirTest):
    def test_clean_python_passes(self):
        d = self.tmpdir()
        _write(d, "ok.py", "def f():\n    return 1\n")
        report = run_linter_probe(d, local_runner)
        self.assertTrue(report.is_clean())
        self.assertIsNone(report.nudge_text())

    def test_broken_python_syntax_is_caught_and_localized(self):
        d = self.tmpdir()
        _write(d, "bad.py", "def f():\n    x = 1\n   try:\n        pass\n")  # IndentationError
        report = run_linter_probe(d, local_runner)
        self.assertFalse(report.is_clean())
        nudge = report.nudge_text()
        self.assertIsNotNone(nudge)
        self.assertIn("bad.py", nudge)
        self.assertIn("line", nudge.lower())

    def test_vendor_dirs_are_skipped(self):
        d = self.tmpdir()
        _write(d, "ok.py", "x = 1\n")
        _write(d, os.path.join("node_modules", "broken.py"), "def (:\n")
        report = run_linter_probe(d, local_runner)
        self.assertTrue(report.is_clean())

    def test_empty_project_is_clean_and_silent(self):
        d = self.tmpdir()
        report = run_linter_probe(d, local_runner)
        self.assertTrue(report.is_clean())
        self.assertIsNone(report.nudge_text())

    def test_probe_digest_routes_the_reasoner_on_the_verdict(self):
        broken = self.tmpdir()
        _write(broken, "bad.py", "def f(:\n")
        digest = run_linter_probe(broken, local_runner).probe_digest()
        self.assertIn("bad.py", digest)
        self.assertIn("error", digest.lower())

        clean = self.tmpdir()
        _write(clean, "ok.py", "x = 1\n")
        digest = run_linter_probe(clean, local_runner).probe_digest()
        self.assertIn("not a syntax error", digest.lower())

        digest = LinterReport().probe_digest()
        self.assertIn("no signal", digest.lower())


class TestLinterProbeInjectedRunner(unittest.TestCase):
    """Interpreter rules behind the Runner seam that a live box can't deterministically
    exercise: absent binaries are abstentions ("skipped"), never failures."""

    def test_missing_python_binary_is_skipped_not_failed(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        _write(d.name, "ok.py", "x = 1\n")

        def no_binary(argv, cwd, timeout_s):
            raise FileNotFoundError(argv[0])

        report = run_linter_probe(d.name, no_binary)
        self.assertEqual(report.skipped, ["python"])
        self.assertEqual(report.findings, [])
        self.assertTrue(report.is_clean())  # abstention must not block completion

    def test_missing_node_binary_is_skipped_not_failed(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        _write(d.name, "app.js", "console.log(1)\n")

        def no_binary(argv, cwd, timeout_s):
            raise FileNotFoundError(argv[0])

        report = run_linter_probe(d.name, no_binary)
        self.assertEqual(report.skipped, ["javascript"])
        self.assertTrue(report.is_clean())

    def test_pyflakes_module_absent_is_not_a_fail(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        _write(d.name, "ok.py", "x = 1\n")

        def runner(argv, cwd, timeout_s):
            if "py_compile" in argv:
                return 0, "", "", False
            return 1, "", "/usr/bin/python3: No module named pyflakes\n", False

        report = run_linter_probe(d.name, runner)
        self.assertEqual([f.tool for f in report.findings], ["py_compile"])
        self.assertTrue(report.is_clean())

    def test_pyflakes_escalation_only_after_parse_passes(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        _write(d.name, "bad.py", "def f(:\n")
        calls = []

        def runner(argv, cwd, timeout_s):
            calls.append(argv)
            return 1, "", 'File "bad.py", line 1\nSyntaxError: invalid syntax\n', False

        report = run_linter_probe(d.name, runner)
        self.assertEqual(len(calls), 1)  # parse failed → no pyflakes noise on top
        self.assertIn("py_compile", calls[0])
        self.assertFalse(report.is_clean())

    def test_javascript_accumulates_per_file_failures(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        _write(d.name, "a.js", "x")
        _write(d.name, "b.js", "y")

        def runner(argv, cwd, timeout_s):
            f = argv[-1]
            if f.endswith("a.js"):
                return 1, "", f"{f}:1\nSyntaxError: Unexpected end of input\n", False
            return 0, "", "", False

        report = run_linter_probe(d.name, runner)
        self.assertFalse(report.is_clean())
        (finding,) = report.failing()
        self.assertEqual(finding.tool, "node --check")
        self.assertIn("a.js", finding.errors)
        self.assertNotIn("b.js", finding.errors)


class TestGroundTruth(_TmpDirTest):
    def test_snapshot_reads_live_file_and_reports_missing(self):
        d = self.tmpdir()
        _write(d, "a.py", "print('hi')\n")
        snaps = file_snapshot(d, ["a.py", "gone.py"], DEFAULT_FILE_CAP)
        self.assertEqual(snaps[0].path, "a.py")
        self.assertTrue(snaps[0].exists)
        self.assertEqual(snaps[0].content, "print('hi')\n")
        self.assertFalse(snaps[0].truncated)
        self.assertFalse(snaps[1].exists)

    def test_snapshot_is_bounded(self):
        d = self.tmpdir()
        _write(d, "big.txt", "x" * 10_000)
        (snap,) = file_snapshot(d, ["big.txt"], 100)
        self.assertTrue(snap.truncated)
        self.assertEqual(len(snap.content), 100)

    def test_absolute_path_resolves_regardless_of_root(self):
        d = self.tmpdir()
        abs_path = _write(d, "abs.txt", "ok")
        (snap,) = file_snapshot("/nonexistent-root", [abs_path], DEFAULT_FILE_CAP)
        self.assertTrue(snap.exists)
        self.assertEqual(snap.content, "ok")

    def test_has_signal_requires_a_repeated_action_or_dirty_lint_not_just_a_file(self):
        self.assertFalse(GroundTruth().has_signal())
        files_only = GroundTruth(files=[FileSnapshot("a.py", "x = 1\n", True, False)])
        self.assertFalse(files_only.has_signal())  # files alone are NEVER signal
        self.assertTrue(GroundTruth(
            repeated=RepeatedAction("cat /dir", "Is a directory", 9)).has_signal())
        self.assertTrue(GroundTruth(lint_digest="h.py:1: syntax error").has_signal())

    def test_render_leads_with_repeated_action_then_lint_then_files(self):
        gt = GroundTruth(
            files=[FileSnapshot("h.py", "def h(): pass", True, False)],
            lint_digest="h.py:1: syntax error",
            repeated=RepeatedAction("cat '/work'", "Is a directory", 9),
        )
        text = gt.render()
        self.assertLess(text.index("REPEATED ACTION"), text.index("LINT/SYNTAX"))
        self.assertLess(text.index("LINT/SYNTAX"), text.index("FILE h.py"))
        self.assertIn("9×", text)
        self.assertIn("Is a directory", text)

    def test_lint_digest_is_dirty_only(self):
        clean = self.tmpdir()
        _write(clean, "ok.py", "x = 1\n")
        self.assertIsNone(lint_digest(clean, local_runner))  # clean is NOT signal

        broken = self.tmpdir()
        _write(broken, "bad.py", "def f(:\n")
        digest = lint_digest(broken, local_runner)
        self.assertIsNotNone(digest)
        self.assertIn("bad.py", digest)

    def test_file_len_is_metadata_only(self):
        d = self.tmpdir()
        _write(d, "a.txt", "12345")
        self.assertEqual(file_len(d, "a.txt"), 5)
        self.assertIsNone(file_len(d, "gone.txt"))


if __name__ == "__main__":
    unittest.main()
