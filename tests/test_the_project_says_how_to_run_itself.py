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


class AProjectRunnerIsNotAFileTests(unittest.TestCase):
    def test_cargo_run_is_corroborated_by_the_manifest(self):
        with ws(RUST) as d:
            ok, why = execcheck.corroborate("cargo run", execcheck.readme_commands(d),
                                            execcheck.entrypoints(d), d)
        self.assertTrue(ok, why)
        self.assertEqual(why, "")

    def test_the_old_sentence_is_gone(self):
        with ws(RUST) as d:
            _, why = execcheck.corroborate("cargo run", execcheck.readme_commands(d),
                                           execcheck.entrypoints(d), d)
        self.assertNotIn("not an entry point on disk", why)

    def test_a_runner_no_manifest_declares_is_still_refused(self):
        """The veto is narrowed, not removed: no Cargo.toml means `cargo run` is not a thing here."""
        with ws(NODE) as d:
            ok, why = execcheck.corroborate("cargo run", execcheck.readme_commands(d),
                                            execcheck.entrypoints(d), d)
        self.assertFalse(ok)
        self.assertIn("declares", why)

    def test_a_plain_file_command_still_takes_the_on_disk_route(self):
        with ws(NODE) as d:
            ok, _ = execcheck.corroborate("node lookup.js goose", execcheck.readme_commands(d),
                                          execcheck.entrypoints(d), d)
            bad, why = execcheck.corroborate("node ghost.js", execcheck.readme_commands(d),
                                             execcheck.entrypoints(d), d)
        self.assertTrue(ok)
        self.assertFalse(bad)
        self.assertIn("not an entry point on disk", why)

    def test_an_undocumented_but_real_entry_point_still_passes_weakly(self):
        """Preserved: a missing README line is a documentation gap, not evidence of no run."""
        with ws({"app.py": "if __name__ == '__main__':\n    print(1)\n"}) as d:
            ok, why = execcheck.corroborate("python3 app.py", [], execcheck.entrypoints(d), d)
        self.assertTrue(ok)
        self.assertIn("no README or manifest documents", why)


class TheDeclaredCommandsReachTheProbeAuthorTests(unittest.TestCase):
    def test_the_readme_command_is_listed(self):
        with ws(NODE) as d:
            block = execcheck.declared_listing(d)
        self.assertIn("node lookup.js goose", block)

    def test_the_manifest_scripts_are_listed_EXCEPT_the_test_ones(self):
        """`npm test` is gone from this list on purpose, since 2026-08-18.

        The header calls these the commands the project "is run and tested with" and the prompt says
        to prefer them verbatim — while `_runnable` refuses any test command outright, because
        `proberun` owns that job and a third execution of the suite in the live workspace is what
        broke `orders-api-py x nemotron-elastic`. cria was offering an answer it had already decided
        to veto.

        MEASURED over every captured run: 361 exec-intent calls, 205 `inconclusive`, and **120 of
        those name a test runner** — one in three of every call this seat has ever made. A library
        project makes it certain rather than likely: its manifest declares a test task and nothing
        else, so the list held only commands cria would refuse."""
        with ws(NODE) as d:
            block = execcheck.declared_listing(d)
        self.assertIn("npm start", block)
        self.assertNotIn("npm test", block)

    def test_a_library_project_gets_no_declared_block_at_all(self):
        """Its manifest declares a test task and nothing else, so after the filter there is nothing
        to show — and the prompt already names "nothing runnable has been written yet" as a correct
        answer, so the question is still worth asking."""
        rakefile = 'require "rake/testtask"\nRake::TestTask.new(:test)\ntask default: :test\n'
        with ws({"Rakefile": rakefile}) as d:
            self.assertEqual(execcheck.declared_listing(d), "")

    def test_the_filter_and_the_refusal_are_the_same_predicate(self):
        """They disagreed once; one owner now (#23)."""
        import inspect
        self.assertIn("_is_a_test_command", inspect.getsource(execcheck.declared_listing))

    def test_a_project_that_declares_nothing_gets_no_section(self):
        with ws({"a.py": "x = 1\n"}) as d:
            self.assertEqual(execcheck.declared_listing(d), "")

    def test_the_block_reaches_the_prompt(self):
        with ws(NODE) as d:
            _, user = execcheck.intent_prompt("build a cli", files="lookup.js (10 B)",
                                              declared=execcheck.declared_listing(d))
        self.assertIn("node lookup.js goose", user)
        self.assertIn("COMMANDS THIS PROJECT DECLARES FOR ITSELF", user)
        self.assertNotIn("{{", user)

    def test_the_prompt_says_to_prefer_a_declared_command(self):
        _, user = execcheck.intent_prompt("t", files="a.py", declared="X")
        self.assertIn("prefer it verbatim", user)

    def test_no_declared_block_leaves_the_prompt_clean(self):
        _, user = execcheck.intent_prompt("t", files="a.py (1 B)")
        self.assertNotIn("{{", user)
        self.assertNotIn("COMMANDS THIS PROJECT DECLARES", user)

    def test_the_loop_passes_it(self):
        import inspect

        from cria import loop
        self.assertIn("declared=execcheck.declared_listing(root)",
                      inspect.getsource(loop))


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
