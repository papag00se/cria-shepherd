"""cria parsed the project's own run commands, then withheld them from the model it asked to name one.

`readme_commands` and `manifest_commands` read what the project DECLARES about itself. cria used them
one function later to VETO the probe author's answer — and never showed them to the probe author.

    nemotron-elastic/node. The probe's own reasoning: "we need to guess. However the instruction says
    "Be concrete and short." So we can say something like "handle: 0x123456"."
    It answered `node lookup.js --handle=somehandle --json`.
    The README on disk says `node lookup.js goose` — the command the verifier runs.

The live-execution check never ran the delivered program, and a green gate stood on nothing but the
coder's own word. 10 occurrences, four models.

AND THE VETO ITSELF ASKED AN UNANSWERABLE QUESTION. `program_token` resolves `cargo run`, `go test`,
`mvn exec:java` to the runner plus its subcommand, because for a project runner the target is the
whole project and any filename is an INPUT. `corroborate` then asked whether that token is a FILE on
disk, which for "cargo run" can only ever be no — while the manifest read three lines below is
exactly what makes `cargo run` a real thing to do. The head-first half landed without its caller
(#24's corollary).

    qwen35/rust, 3/3 on its own suite, 0139 -> 0140.
    cria:  "Live execution inconclusive — the delivered program was not run, because cargo run is
            not an entry point on disk."
    coder: "The context says tests are not running and cargo run is not an entry point. Let me check
            the actual state of the workspace" — after it had run both, successfully.
"""

# The live-execution seat this file tested was REMOVED on 2026-08-18 (operator: "drop the
# 'something needs to be ran' assertion altogether — it is more trouble than it is worth").
# The classes that exercised it are gone with it; what remains below tests mechanisms that
# outlived it. See docs/audits/finish-and-remeasure-progress.md for the reasoning.


import json
import os
import pathlib
import tempfile
import unittest

from cria import execcheck, prompts


class ws:
    def __init__(self, files):
        self.files = files

    def __enter__(self):
        self.d = tempfile.mkdtemp()
        for name, body in self.files.items():
            p = pathlib.Path(self.d, name)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        return self.d

    def __exit__(self, *a):
        import shutil
        shutil.rmtree(self.d, ignore_errors=True)


RUST = {"Cargo.toml": "[package]\nname = \"toml-cli\"\n",
        "src/main.rs": "fn main() { println!(\"hi\"); }\n"}
NODE = {"package.json": json.dumps({"scripts": {"start": "node lookup.js", "test": "node --test"}}),
        "lookup.js": "#!/usr/bin/env node\nconsole.log('x')\n",
        "README.md": "# lookup\n\nRun it:\n\n    node lookup.js goose\n"}


class TheOfflineSentenceClaimsOnlyWhatTheNamespaceProvesTests(unittest.TestCase):
    """`unshare -rn` removes the OUTSIDE network and the probe brings loopback back up. So "nothing
    in them reaches the real service" is false whenever the service under test is local — which is
    every server task in the battery."""

    def test_it_no_longer_claims_the_tests_reach_nothing(self):
        text = prompts.load("tests_pass_offline")
        self.assertNotIn("nothing in them reaches the real service", text)

    def test_it_names_loopback(self):
        text = prompts.load("tests_pass_offline")
        self.assertIn("loopback", text)
        self.assertIn("still reachable", text)

    def test_it_keeps_the_finding_it_exists_for(self):
        text = prompts.load("tests_pass_offline")
        self.assertIn("network switched off", text)
        self.assertIn("{{TALLY}}", text)

    def test_the_uncounted_variant_is_untouched(self):
        """It already avoided the over-claim, and its counted/uncounted distinction is load-bearing."""
        text = prompts.load("tests_pass_offline_uncounted")
        self.assertIn("command that ran did not ask", text)
        self.assertIn("none of them failed", text)
        self.assertNotIn("nothing in them reaches", text)


if __name__ == "__main__":
    unittest.main()
