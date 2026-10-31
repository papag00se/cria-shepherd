"""Stranded test files — apparent test code outside default automatic discovery conventions — have ONE
owner: probediscovery's convention table (the g20 mechanism). This file pins the two gaps the
maple-run-2 walk exposed in it, and the walk-found duplicate it replaced (a second scanner,
cria/orphantests.py, briefly existed on 2026-08-05 and was deleted the same day — one owner).

Gap 1 (the silencer): `undiscoverable_tests` skipped a language entirely once ANY discoverable
test file existed — so test_live_handle.py silenced the warning about a stranded 19KB
pytest_da_resolvers.py for the run's final 30 minutes. The stranded sentence is now emitted
regardless of what else is discoverable.

Gap 2 (the benign zero-collected gate): pytest exit-5 / go's "[no test files]" read as benign
even when stranded test code sat on disk. Historically, these observations became "error-class
findings" and displaced the native zero-collected evidence. clean_gate_output now preserves that
native evidence and surfaces default-discovery observations as separately authored metadata; an
explicit-file invocation or configured runner may still execute these files."""

import os
import tempfile
import unittest

from cria import probediscovery, probegate
from tests.gatefixture import gate_page, completed
from cria.probegate import GatePlan
import tests.test_probegate as tp


def _ws(files: dict) -> str:
    d = tempfile.mkdtemp()
    for name, content in files.items():
        path = os.path.join(d, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(content)
    return d


_PY_TESTS = "import unittest\n\ndef test_resolve():\n    assert 1\n\ndef test_holder():\n    assert 2\n"
_GO_TESTS = 'package main\n\nimport "testing"\n\nfunc TestResolve(t *testing.T) {\n}\n'


class StrandedSentenceTests(unittest.TestCase):

    def test_the_maple_case_a_discoverable_file_no_longer_silences_the_stranded_one(self):
        ws = _ws({"pytest_da_resolvers.py": _PY_TESTS,
                  "test_live_handle.py": "def test_live():\n    assert 1\n"})
        out = probediscovery.stranded_test_sentences(ws)
        self.assertEqual(len(out), 1)
        self.assertIn("pytest_da_resolvers.py", out[0])
        self.assertIn("test_*.py", out[0])
        # ...and undiscoverable_tests carries the same sentence now
        self.assertTrue(any("pytest_da_resolvers.py" in s
                            for s in probediscovery.undiscoverable_tests(ws)))

    def test_conftest_is_pytest_plumbing_never_stranded(self):
        ws = _ws({"conftest.py": "import pytest\n", "test_x.py": "def test_a():\n    assert 1\n"})
        self.assertEqual(probediscovery.stranded_test_sentences(ws), [])

    def test_a_repointed_runner_silences_cria(self):
        ws = _ws({"pytest.ini": "[pytest]\npython_files = check_*.py\n",
                  "pytest_da_resolvers.py": _PY_TESTS})
        self.assertEqual(probediscovery.stranded_test_sentences(ws), [])

    def test_no_test_code_no_sentence(self):
        ws = _ws({"app.py": "def resolve():\n    return 1\n"})
        self.assertEqual(probediscovery.stranded_test_sentences(ws), [])

    def test_go_test_funcs_outside_test_files_are_stranded(self):
        ws = _ws({"resolver_tests.go": _GO_TESTS})
        out = probediscovery.stranded_test_sentences(ws)
        self.assertEqual(len(out), 1)
        self.assertIn("resolver_tests.go", out[0])
        self.assertIn("_test.go", out[0])


class GateWiringTests(unittest.TestCase):
    """Zero collection remains native evidence, alongside separately authored naming observations
    from the ONE discovery owner, not a universal prohibition on executing the files."""

    def _raw(self, body):
        return "Chunk ID: 7f3\n" + tp._sec(0, "EXIT:0") + tp._sec(1, body) + tp._git() + "\n"

    def test_exit5_with_a_stranded_suite_becomes_a_finding(self):
        ws = _ws({"pytest_da_resolvers.py": _PY_TESTS,
                  "test_live_handle.py": "def test_live():\n    assert 1\n"})
        raw = self._raw("no tests ran in 0.01s\nEXIT:5")
        out = probegate.clean_gate_output(raw, completed(GatePlan(workspace=ws), raw))
        self.assertIn("pytest_da_resolvers.py", out)
        self.assertIn("outside default automatic discovery conventions for pytest", out)
        self.assertIn("test_*.py or *_test.py", out)
        self.assertIn("explicit-file invocation or a configured runner", out)
        self.assertIn("exit 5\nno tests ran in 0.01s", out)
        native, separator, metadata = out.partition(
            "Automatic discovery observations (authored metadata, not checker output):")
        self.assertTrue(separator)
        self.assertNotIn("pytest_da_resolvers.py", native)
        self.assertIn("pytest_da_resolvers.py", metadata)
        self.assertNotIn("report these error-class problems", out)
        self.assertNotIn("will not run", out)

    def test_exit5_without_stranded_files_stays_benign(self):
        ws = _ws({"app.py": "def resolve():\n    return 1\n"})
        raw = self._raw("no tests ran in 0.01s\nEXIT:5")
        out = probegate.clean_gate_output(raw, completed(GatePlan(workspace=ws), raw))
        self.assertIn("exit 5\nno tests ran in 0.01s", out)
        self.assertNotIn("report these error-class problems", out)

    def test_a_green_go_run_with_no_test_files_and_a_stranded_suite_is_flagged(self):
        ws = _ws({"resolver_tests.go": _GO_TESTS})
        raw = self._raw("?   \texample.com/x\t[no test files]\nEXIT:0")
        out = probegate.clean_gate_output(raw, completed(GatePlan(workspace=ws), raw))
        self.assertIn("resolver_tests.go", out)
        self.assertIn("_test.go", out)

    def test_the_duplicate_module_stays_dead(self):
        with self.assertRaises(ImportError):
            import cria.orphantests  # noqa: F401


if __name__ == "__main__":
    unittest.main()
