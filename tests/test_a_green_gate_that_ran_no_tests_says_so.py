"""A Node project with test files and no test script ran zero tests and reported no problems.

`undiscoverable_tests` answers "do these files match the language's naming convention". When they
DO, it correctly says nothing. That silence was the whole problem: matching a convention is not the
same as a runner having been SELECTED to apply it.

    package.json  {"name": "x"}          — no scripts.test, no jest/vitest config
    lookup.test.js                        — a real test file, matching the convention exactly

Ranked discovery for JS reads declared `scripts` and config-gated tools. This project declares
neither, so it yields ZERO test probes — and `undiscoverable_tests` stays quiet because the file
name is perfectly fine. The gate then reports

    ⟦ctx:checks⟧ the repo's own checks that ran reported no error-class problems.

with no qualifier at all: the vacuous green the qualifier exists to prevent, reached from the other
side. The g20 shape is "your tests are somewhere the runner cannot see"; this one is "your tests are
exactly where the runner would look, and no runner was brought".

NO RUNNER IS INVENTED. `node --test` is deliberately absent from the floor table — it cannot run
jest/vitest/mocha suites and would falsely FAIL them, which is the false-red class — and that
decision stands. What cria can say without guessing is what it found and what it did not compose.
#11b: a mechanism that could not reach the thing it was asked about must say so rather than answer
"nothing found".
"""

import json
import pathlib
import tempfile
import unittest

from cria import probediscovery, probegate


class _Project:
    def __init__(self, files):
        self.files = files

    def __enter__(self):
        self._d = tempfile.TemporaryDirectory()
        root = pathlib.Path(self._d.name)
        for name, body in self.files.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        return root

    def __exit__(self, *a):
        self._d.cleanup()
        return False


NODE_TEST = "const {test} = require('node:test');\ntest('x', () => {});\n"


def plan_for(files):
    with _Project(files) as root:
        plan = probegate.plan_gate(str(root))
        tests = [c for c in plan.candidates if c.kind is probediscovery.ProbeKind.Test]
        return tests, plan.untested


class TheGapThatWasSilentTests(unittest.TestCase):
    def test_test_files_and_no_runner_is_disclosed(self):
        tests, untested = plan_for({"package.json": json.dumps({"name": "x"}),
                                    "index.js": "console.log(1)\n",
                                    "lookup.test.js": NODE_TEST})
        self.assertEqual(tests, [], "the premise: no test probe is composed for this project")
        self.assertTrue(untested)
        note = " ".join(untested)
        self.assertIn("no command to run them", note)
        self.assertIn("nothing here has run them", note)

    def test_a_declared_test_script_says_nothing(self):
        """Silence over noise: a project that CAN run its tests gets no qualifier."""
        tests, untested = plan_for({"package.json": json.dumps(
                                        {"name": "x", "scripts": {"test": "node --test"}}),
                                    "index.js": "console.log(1)\n",
                                    "lookup.test.js": NODE_TEST})
        self.assertTrue(tests)
        self.assertEqual(untested, [])

    def test_no_test_files_keeps_the_older_wording(self):
        """The g20 sentence is a different fact and must not be replaced by this one."""
        _, untested = plan_for({"package.json": json.dumps({"name": "x"}),
                                "index.js": "console.log(1)\n"})
        note = " ".join(untested)
        self.assertIn("No jest/vitest tests were found", note)
        self.assertNotIn("no command to run them", note)

    def test_the_two_sentences_never_both_fire_for_one_language(self):
        for files in ({"package.json": json.dumps({"name": "x"}), "index.js": "1\n"},
                      {"package.json": json.dumps({"name": "x"}), "index.js": "1\n",
                       "lookup.test.js": NODE_TEST}):
            with self.subTest(files=sorted(files)):
                _, untested = plan_for(files)
                self.assertLessEqual(len([u for u in untested if "jest/vitest" in u]), 1)


class ItReachesTheCoderTests(unittest.TestCase):
    def test_the_qualifier_rides_the_clean_gate(self):
        """plan.untested is what the clean branch renders, so this lands in the same place the g20
        wording does — one qualifier, one seat."""
        from cria.probediscovery import ProbeCandidate, ProbeCost, ProbeKind
        plan = probegate.GatePlan(
            workspace=tempfile.gettempdir(),
            candidates=[ProbeCandidate(kind=ProbeKind.Lint, command=["x"],
                                       working_dir=tempfile.gettempdir(), confidence=90,
                                       expected_value=80, cost=ProbeCost.Cheap, mutates_code=False,
                                       may_hang=False, may_need_services=False, reason="t")],
            untested=["Test files for jest/vitest are present, but no command to run them was "
                      "found in this project — nothing here has run them."])
        out = probegate.clean_gate_output("___CRIA_GATE_probe-0___\nclean\nEXIT:0\n", plan)
        self.assertIn("no error-class problems", out)
        self.assertIn("no command to run them", out)


class NoRunnerIsInventedTests(unittest.TestCase):
    def test_node_test_is_still_not_a_floor(self):
        """It cannot run jest/vitest/mocha suites — different globals — so seeding it would falsely
        FAIL them. The exclusion is deliberate and this pins it."""
        for conv in probediscovery.TEST_CONVENTIONS:
            if "js" in conv.exts:
                with self.subTest(runner=conv.runner):
                    self.assertEqual(conv.floor, ())

    def test_no_test_probe_is_added_by_the_disclosure(self):
        tests, _ = plan_for({"package.json": json.dumps({"name": "x"}),
                             "index.js": "console.log(1)\n", "lookup.test.js": NODE_TEST})
        self.assertEqual(tests, [])

    def test_the_languages_with_a_real_floor_are_unaffected(self):
        """Python and Ruby need no manifest, so their floor supplies a runner and this never speaks
        for them."""
        with _Project({"app.py": "x = 1\n", "test_app.py": "def test_x():\n    assert True\n"}) as r:
            plan = probegate.plan_gate(str(r))
            self.assertTrue([c for c in plan.candidates if c.kind is probediscovery.ProbeKind.Test])
            self.assertNotIn("no command to run them", " ".join(plan.untested))


if __name__ == "__main__":
    unittest.main()
