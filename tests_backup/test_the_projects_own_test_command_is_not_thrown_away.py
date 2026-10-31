"""Node is the only ecosystem whose declared test command cria discarded.

`build_js` walks `GOOD_SCRIPTS` — an allowlist of package.json script NAMES — and dropped any whose
BODY the classifier could not recognise:

    if vet.kind is probeclassify.ProbeKind.UNKNOWN:
        continue  # Only recognized probe scripts become candidates.

`probeclassify` knows `node --test` and nothing else node-shaped, so `node cli.test.js`,
`node test/lookup.test.js`, `node test.test.js` and `node test/run-tests.js` all classify UNKNOWN.
Measured across the 9 archived `handles-cli-node` workspaces: **7 declare `scripts.test`, 0 of those
7 reach the gate, and 8 of 9 get ZERO test probes** — the only such workspaces in the archive.

Every other ecosystem is treated far more generously. `build_php` composes `vendor/bin/phpunit` on a
bare `composer.json` with no evidence at all; `build_elixir` composes `mix test` on `mix.exs` alone.

npm's own convention is that `test` runs the tests, and `map_kind` already had an UNKNOWN arm
falling back to `name_kind` — under a docstring calling itself *"unreachable from build_js (Unknown
scripts are skipped)"*. The mechanism existed and could not fire.

The safety vet is unchanged: a body that installs, mutates or brings up a service is still refused
when nothing recognises it. The lower confidence records that the classifier did not endorse it.
"""

import json
import pathlib
import tempfile
import unittest

from cria import probediscovery, wsview


def _project(scripts, extra=None):
    d = tempfile.mkdtemp()
    pathlib.Path(d, "package.json").write_text(json.dumps({"name": "x", "scripts": scripts}))
    pathlib.Path(d, "cli.js").write_text("console.log(1)\n")
    pathlib.Path(d, "test").mkdir(exist_ok=True)
    pathlib.Path(d, "test", "lookup.test.js").write_text("import test from 'node:test'\n")
    for name, body in (extra or {}).items():
        pathlib.Path(d, name).write_text(body)
    return d


def _probes(scripts, extra=None):
    d = _project(scripts, extra)
    tok = wsview.bind(wsview.DirectView(d))
    try:
        return probediscovery.discover(pathlib.Path(d))
    finally:
        wsview.unbind(tok)


def _kinds(cands):
    return [c.kind for c in cands]


class AnUnrecognisedRunnerStillRunsTests(unittest.TestCase):
    UNRECOGNISED = ("node test/lookup.test.js", "node cli.test.js", "node test/run-tests.js",
                    "node --experimental-vm-modules test.js")

    def test_every_shape_the_classifier_misses_still_becomes_a_test_probe(self):
        for body in self.UNRECOGNISED:
            with self.subTest(body=body):
                cands = _probes({"test": body})
                self.assertIn(probediscovery.ProbeKind.Test, _kinds(cands), body)

    def test_the_probe_runs_the_project_s_own_command(self):
        cand = next(c for c in _probes({"test": "node test/lookup.test.js"})
                    if c.kind is probediscovery.ProbeKind.Test)
        self.assertEqual(cand.command[-2:], ["run", "test"])

    def test_it_says_the_runner_was_not_recognised(self):
        cand = next(c for c in _probes({"test": "node test/lookup.test.js"})
                    if c.kind is probediscovery.ProbeKind.Test)
        self.assertIn("not recognised", cand.reason)

    def test_it_is_less_confident_than_a_recognised_one(self):
        unknown = next(c for c in _probes({"test": "node test/lookup.test.js"})
                       if c.kind is probediscovery.ProbeKind.Test)
        known = next(c for c in _probes({"test": "node --test"})
                     if c.kind is probediscovery.ProbeKind.Test)
        self.assertLess(unknown.confidence, known.confidence)


class TheSafetyVetIsUnchangedTests(unittest.TestCase):
    def test_an_unrecognised_body_that_installs_is_still_refused(self):
        cands = _probes({"test": "npm install && node weird-runner.js"})
        self.assertNotIn(probediscovery.ProbeKind.Test, _kinds(cands))

    def test_an_unrecognised_body_that_starts_a_server_is_still_refused(self):
        cands = _probes({"test": "node server.js & node t.js"})
        safe = [c for c in cands if c.kind is probediscovery.ProbeKind.Test
                and c.cost is not probediscovery.ProbeCost.Risky]
        self.assertEqual(safe, [])


class ARecognisedRunnerIsUnaffectedTests(unittest.TestCase):
    def test_node_test_is_still_a_test_probe(self):
        self.assertIn(probediscovery.ProbeKind.Test, _kinds(_probes({"test": "node --test"})))

    def test_a_lint_script_is_still_a_lint_probe(self):
        cands = _probes({"lint": "eslint ."})
        self.assertIn(probediscovery.ProbeKind.Lint, _kinds(cands))


if __name__ == "__main__":
    unittest.main()
