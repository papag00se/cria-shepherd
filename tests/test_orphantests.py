"""Tests the runner cannot SEE are worse than no tests: the suite reads green-ish ("no tests
ran" — benign by design for genuinely testless projects) while a fat test file sits on disk.

Measured on maple run 2 (ada-handles_maple-preview_codex_poff_1785973706): the model wrote a
19KB pytest file named `pytest_da_resolvers.py` — pytest only collects `test_*.py` /
`*_test.py`, so 0 tests ran for the last 30 minutes of the run, the gate stayed silent (the
exit-5-benign rule), and the run lost the unit-test point with real tests on disk.

The discriminator is the same shape as the F811 fix: the benign rule stays for the genuinely
testless case; when the runner collected NOTHING and a scan finds files that CONTAIN test
functions under a name the runner's pattern cannot match, that is a stated, checkable fact —
error-class, so the coder is told to rename. cria never renames the file itself: the model's
context holds the old name, and a behind-the-back rename makes every later edit target a
phantom (the stale-context class), besides breaking the no-workspace-writes rule."""

import os
import tempfile
import unittest

from cria import orphantests


def _ws(files: dict) -> str:
    d = tempfile.mkdtemp()
    for name, content in files.items():
        path = os.path.join(d, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(content)
    return d


_PY_TESTS = "import unittest\n\ndef test_resolve():\n    assert 1\n\ndef test_holder():\n    assert 2\n"


class PythonOrphanTests(unittest.TestCase):

    def test_a_misnamed_pytest_file_is_found_with_its_count(self):
        ws = _ws({"pytest_da_resolvers.py": _PY_TESTS})
        found = orphantests.orphan_test_files(ws)
        self.assertEqual(len(found), 1)
        o = found[0]
        self.assertEqual(o.path, "pytest_da_resolvers.py")
        self.assertEqual(o.n_tests, 2)
        self.assertIn("test_*.py", o.pattern)

    def test_unittest_class_files_count_too(self):
        ws = _ws({"resolver_suite.py": "import unittest\nclass TestResolver(unittest.TestCase):\n    def test_a(self):\n        pass\n"})
        found = orphantests.orphan_test_files(ws)
        self.assertEqual([o.path for o in found], ["resolver_suite.py"])

    def test_correctly_named_files_are_not_orphans(self):
        ws = _ws({"test_resolver.py": _PY_TESTS, "resolver_test.py": _PY_TESTS})
        self.assertEqual(orphantests.orphan_test_files(ws), [])

    def test_conftest_and_files_without_tests_are_not_orphans(self):
        ws = _ws({"conftest.py": "import pytest\n", "app.py": "def resolve():\n    return 1\n"})
        self.assertEqual(orphantests.orphan_test_files(ws), [])

    def test_ignored_trees_are_never_scanned(self):
        ws = _ws({".venv/lib/pytest_helpers.py": _PY_TESTS,
                  "node_modules/x/pytest_x.py": _PY_TESTS})
        self.assertEqual(orphantests.orphan_test_files(ws), [])


class GoAndJsOrphanTests(unittest.TestCase):

    def test_a_go_test_func_outside_a_test_file_is_found(self):
        ws = _ws({"resolver_tests.go": 'package main\n\nimport "testing"\n\nfunc TestResolve(t *testing.T) {\n}\n'})
        found = orphantests.orphan_test_files(ws)
        self.assertEqual([o.path for o in found], ["resolver_tests.go"])
        self.assertIn("_test.go", found[0].pattern)

    def test_a_proper_go_test_file_is_not(self):
        ws = _ws({"resolver_test.go": 'package main\n\nimport "testing"\n\nfunc TestResolve(t *testing.T) {\n}\n'})
        self.assertEqual(orphantests.orphan_test_files(ws), [])

    def test_a_misnamed_jest_suite_is_found(self):
        ws = _ws({"resolver-checks.js": "describe('resolver', () => {\n  it('resolves', () => {});\n});\n"})
        found = orphantests.orphan_test_files(ws)
        self.assertEqual([o.path for o in found], ["resolver-checks.js"])

    def test_spec_and_test_named_js_are_not(self):
        js = "describe('x', () => { it('y', () => {}); });\n"
        ws = _ws({"resolver.test.js": js, "resolver.spec.ts": js, "__tests__/resolver.js": js})
        self.assertEqual(orphantests.orphan_test_files(ws), [])


class GateWiringTests(unittest.TestCase):
    """clean_gate_output: the exit-5-benign rule stays for testless projects; with orphans on
    disk the same signal becomes an error-class finding naming the file, the count, and the
    runner's pattern."""

    def _raw(self, body):
        import tests.test_probegate as tp
        return "Chunk ID: 7f3\n" + tp._sec(0, "EXIT:0") + tp._sec(1, body) + tp._git() + "\n"

    def test_exit5_with_an_orphan_becomes_a_finding(self):
        from cria import probegate
        from cria.probegate import GatePlan
        ws = _ws({"pytest_da_resolvers.py": _PY_TESTS})
        raw = self._raw("no tests ran in 0.01s\nEXIT:5")
        out = probegate.clean_gate_output(raw, GatePlan(workspace=ws))
        self.assertIn("pytest_da_resolvers.py", out)
        self.assertIn("cannot collect", out)
        self.assertIn("test_*.py", out)

    def test_exit5_without_orphans_stays_benign(self):
        from cria import probegate
        from cria.probegate import GatePlan
        ws = _ws({"app.py": "def resolve():\n    return 1\n"})
        raw = self._raw("no tests ran in 0.01s\nEXIT:5")
        out = probegate.clean_gate_output(raw, GatePlan(workspace=ws))
        self.assertIn("no error-class", out.lower())

    def test_a_green_go_run_with_no_test_files_and_an_orphan_is_flagged(self):
        from cria import probegate
        from cria.probegate import GatePlan
        ws = _ws({"resolver_tests.go": 'package main\n\nimport "testing"\n\nfunc TestResolve(t *testing.T) {\n}\n'})
        raw = self._raw("?   \texample.com/x\t[no test files]\nEXIT:0")
        out = probegate.clean_gate_output(raw, GatePlan(workspace=ws))
        self.assertIn("resolver_tests.go", out)
        self.assertIn("_test.go", out)


if __name__ == "__main__":
    unittest.main()
