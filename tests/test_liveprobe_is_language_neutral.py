"""The suite's own scorer carried three single-language assumptions.

It is not cria, but it decides every score in the battery, so an assumption here is indistinguishable
from a model failing.

1. `live_file_check` collected `*.py` and `*.sh` only — while its docstring claimed these were "the
   two wrapper shapes any language's workspace can carry". `live_test.rb` and `live_test.js` were
   invisible and scored zero. The NAME is the signal; the extension should choose the RUNNER.
2. `session_live_evidence` gated the operator's 2026-08-05 in-session credit on
   `"pytest" not in cmd` — one tool's name standing in for "is this the coder running its own test
   suite?". A Go, Rust, Ruby, Java or Node suite could never earn it. The allowlist one block up in
   the same function is already generalised across seven runtimes, which is what shows the shape was
   known.
3. The README probe's prompt told the model "Use python3, never bare python" on every task in every
   language — an environment caveat about one interpreter, read as a hint about what answer is
   wanted.
"""
import re
import unittest

import sys
sys.path.insert(0, "suite/tasks")
import _liveprobe as lp  # noqa: E402


class TheNameIsTheSignalTheExtensionPicksTheRunnerTests(unittest.TestCase):
    def test_every_battery_language_can_carry_a_live_test(self):
        for ext in (".py", ".sh", ".rb", ".js", ".go", ".rs", ".php"):
            with self.subTest(ext=ext):
                self.assertIn(ext, lp._LIVE_RUNNERS)

    def test_each_extension_maps_to_a_runner(self):
        self.assertEqual(lp._LIVE_RUNNERS[".rb"], ["ruby"])
        self.assertEqual(lp._LIVE_RUNNERS[".js"], ["node"])
        self.assertIsNone(lp._LIVE_RUNNERS[".py"])      # None → the suite's own interpreter


class ATestSuiteRunIsNotJustPytestTests(unittest.TestCase):
    RUNS = ("pytest -q", "python3 -m unittest", "go test ./...", "cargo test",
            "rake test", "bundle exec rspec", "npm test", "node --test",
            "mvn test", "./gradlew test", "phpunit", "dotnet test")

    def test_every_ecosystem_test_command_is_recognised(self):
        for cmd in self.RUNS:
            with self.subTest(cmd=cmd):
                self.assertTrue(lp._TEST_SUITE_RUN.search(cmd))

    def test_reading_a_file_is_not_running_a_suite(self):
        for cmd in ("grep goose goose.json", "cat results.txt", "curl https://x/y"):
            with self.subTest(cmd=cmd):
                self.assertFalse(lp._TEST_SUITE_RUN.search(cmd))


class TheProbePromptNamesNoOneLanguageTests(unittest.TestCase):
    def test_the_python_caveat_is_gone(self):
        self.assertNotIn("never bare python", lp.PROMPT if hasattr(lp, "PROMPT") else
                         open("suite/tasks/_liveprobe.py").read())

    def test_it_still_asks_for_the_projects_own_invocation(self):
        src = open("suite/tasks/_liveprobe.py").read()
        self.assertIn("exactly as this project invokes it", src)


if __name__ == "__main__":
    unittest.main()
