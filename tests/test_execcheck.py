"""Live execution check — corroborate three sources, run only on agreement, never block."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from cria import execcheck


def ws(**files) -> str:
    d = tempfile.mkdtemp()
    for name, body in files.items():
        p = Path(d) / name.replace("__", "/")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return d


PROGRAM = ('import sys\n'
           'def go(h): return "addr1" + h\n'
           'if __name__ == "__main__":\n'
           '    print(go(sys.argv[1]))\n')
LIBRARY = 'def go(h):\n    return "addr1" + h\n'
README = "# x\n\n## Run\n\n```bash\npython3 tool.py goose\n```\n"


class EntryPointTests(unittest.TestCase):
    def test_a_program_is_found(self):
        self.assertEqual(execcheck.entrypoints(ws(**{"tool.py": PROGRAM})), ["tool.py"])

    def test_a_library_is_not(self):
        self.assertEqual(execcheck.entrypoints(ws(**{"tool.py": LIBRARY})), [])

    def test_manifest_declared_targets_count(self):
        d = ws(**{"pyproject.toml": "[project.scripts]\ntool = 'tool:main'\n", "tool.py": LIBRARY})
        self.assertIn("pyproject.toml", execcheck.entrypoints(d))

    def test_other_languages(self):
        for name, body in (("main.go", "package main\nfunc main() {}\n"),
                           ("main.rs", "fn main() {}\n"),
                           ("App.java", "class App { public static void main(String[] a) {} }"),
                           ("cli.rb", "#!/usr/bin/env ruby\nputs 1\n")):
            with self.subTest(name=name):
                self.assertEqual(execcheck.entrypoints(ws(**{name: body})), [name])

    def test_vendored_trees_are_not_scanned(self):
        d = ws(**{"tool.py": LIBRARY, ".venv__lib__x.py": PROGRAM, "node_modules__y.py": PROGRAM})
        self.assertEqual(execcheck.entrypoints(d), [])


class CorroborationTests(unittest.TestCase):
    def test_all_three_agree(self):
        d = ws(**{"tool.py": PROGRAM, "README.md": README})
        ok, why = execcheck.corroborate("python3 tool.py goose",
                                        execcheck.readme_commands(d), execcheck.entrypoints(d))
        self.assertTrue(ok, why)

    def test_arguments_may_differ_between_readme_and_command(self):
        # The README's example and a live invocation almost never share arguments; matching on the
        # PROGRAM is the whole point of program_token.
        d = ws(**{"tool.py": PROGRAM, "README.md": README})
        ok, _ = execcheck.corroborate("python3 tool.py papagoose",
                                      execcheck.readme_commands(d), execcheck.entrypoints(d))
        self.assertTrue(ok)

    def test_no_entry_point_on_disk_blocks_the_run(self):
        d = ws(**{"tool.py": LIBRARY, "README.md": README})
        ok, why = execcheck.corroborate("python3 tool.py goose",
                                        execcheck.readme_commands(d), execcheck.entrypoints(d))
        self.assertFalse(ok)
        self.assertIn("entry point", why)

    def test_readme_silence_weakens_but_does_not_block(self):
        """It used to VETO. The docstring said why: "The task asked for a README explaining how to
        RUN it" — true of ada-handles and of nothing else. Measured on the six-language battery:
        "the README documents no command that runs tests/handle-lookup.test.js" refused a run in a
        workspace whose package.json declared the very script being run. A named deliverable of one
        task must not become a precondition for believing a program ran (#13, safe direction)."""
        d = ws(**{"tool.py": PROGRAM})
        ok, why = execcheck.corroborate("python3 tool.py goose",
                                        execcheck.readme_commands(d), execcheck.entrypoints(d))
        self.assertTrue(ok)
        self.assertIn("no README or manifest documents", why)

    def test_a_program_not_on_disk_is_still_refused(self):
        """The disk check is the one that carries weight and it is unchanged."""
        d = ws(**{"tool.py": PROGRAM})
        ok, why = execcheck.corroborate("python3 ghost.py", [], execcheck.entrypoints(d))
        self.assertFalse(ok)
        self.assertIn("not an entry point on disk", why)

    def test_a_manifest_script_corroborates_without_any_readme(self):
        d = ws(**{"tool.py": PROGRAM,
                  "package.json": '{"scripts": {"start": "node lookup.js"}}'})
        cmds = execcheck.manifest_commands(d)
        self.assertIn("npm start", cmds)
        self.assertIn("npm run start", cmds)

    def test_manifest_commands_reads_each_ecosystem(self):
        for name, body, want in (("Cargo.toml", "[package]\nname='x'\n", "cargo run"),
                                 ("pom.xml", "<project/>", "mvn test"),
                                 ("go.mod", "module x\n", "go test"),
                                 ("Rakefile", "task :test\n", "rake test")):
            with self.subTest(name=name):
                self.assertIn(want, execcheck.manifest_commands(ws(**{name: body})))

    def test_a_claim_with_no_command_is_not_corroborated(self):
        ok, why = execcheck.corroborate("", ["python3 tool.py x"], ["tool.py"])
        self.assertFalse(ok)


class RunSafetyTests(unittest.TestCase):
    def test_shell_pipelines_are_refused(self):
        code, why = execcheck.run(ws(), "python3 tool.py | head -1")
        self.assertIsNone(code)
        self.assertIn("pipeline", why)

    def test_unknown_runners_are_refused(self):
        code, why = execcheck.run(ws(), "rm -rf /")
        self.assertIsNone(code)
        self.assertIn("runner", why)

    def test_a_real_program_runs(self):
        d = ws(**{"tool.py": PROGRAM})
        code, out = execcheck.run(d, "python3 tool.py goose")
        self.assertEqual(code, 0)
        self.assertIn("addr1goose", out)


class EvaluateTests(unittest.TestCase):
    def intent(self, **kw):
        return {"runs": True, "command": "python3 tool.py goose", "success": "prints an address", **kw}

    def test_working_program_is_confirmed_and_says_nothing(self):
        d = ws(**{"tool.py": PROGRAM, "README.md": README})
        r = execcheck.evaluate(d, self.intent())
        self.assertEqual(r.verdict, execcheck.CONFIRMED)
        self.assertEqual(r.marker, "")          # principle 3: silence on a clean signal

    def test_a_program_that_prints_nothing_is_NOT_OBSERVED(self):
        # The mellum2 shape: exits 0, produces nothing.
        silent = 'import sys\nif __name__ == "__main__":\n    pass\n'
        d = ws(**{"tool.py": silent, "README.md": README})
        r = execcheck.evaluate(d, self.intent())
        self.assertEqual(r.verdict, execcheck.NOT_OBSERVED)
        self.assertIn("printed nothing", r.why)
        self.assertIn("live-execution", r.marker)

    def test_a_library_is_INCONCLUSIVE_not_a_failure(self):
        d = ws(**{"tool.py": LIBRARY, "README.md": README})
        r = execcheck.evaluate(d, self.intent())
        self.assertEqual(r.verdict, execcheck.INCONCLUSIVE)
        self.assertIn("inconclusive", r.marker.lower())

    def test_a_task_that_needs_no_run_says_nothing(self):
        d = ws(**{"lib.py": LIBRARY})
        r = execcheck.evaluate(d, {"runs": False})
        self.assertEqual(r.verdict, execcheck.NOT_APPLICABLE)
        self.assertEqual(r.marker, "")

    def test_an_unreadable_model_answer_never_guesses(self):
        d = ws(**{"tool.py": PROGRAM, "README.md": README})
        r = execcheck.evaluate(d, execcheck.parse_intent("I think maybe run it?"))
        self.assertEqual(r.verdict, execcheck.INCONCLUSIVE)

    def test_no_verdict_ever_blocks(self):
        # The contract that makes this shippable: nothing here returns a "refuse" state.
        self.assertNotIn("block", " ".join(v for v in vars(execcheck) if isinstance(v, str)))
        for verdict in (execcheck.CONFIRMED, execcheck.NOT_OBSERVED,
                        execcheck.INCONCLUSIVE, execcheck.NOT_APPLICABLE):
            self.assertIsInstance(execcheck.ExecResult(verdict).marker, str)


class ParseIntentTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertTrue(execcheck.parse_intent('{"runs": true, "command": "x"}')["runs"])

    def test_fenced_json(self):
        self.assertTrue(execcheck.parse_intent('```json\n{"runs": true}\n```')["runs"])

    def test_prose_is_a_safe_null(self):
        self.assertEqual(execcheck.parse_intent("no idea"), {})


class TestFilesAreNotProgramsTests(unittest.TestCase):
    """A test file carrying `if __name__ == "__main__": unittest.main()` is not the deliverable.

    Measured on mellum2 attempt 3: the workspace's ONLY entry point was in
    test_resolve_handle.py, the deliverable ended on a function definition, and
    `resolve_handle.py goose` printed nothing — yet the check reported an entry point present.
    """

    RUNNER = ('import unittest\n'
              'class T(unittest.TestCase):\n    def test_x(self): pass\n'
              'if __name__ == "__main__":\n    unittest.main()\n')

    def test_a_test_files_runner_block_does_not_count(self):
        for name in ("test_resolve.py", "resolve_test.py", "tests__test_x.py",
                     "AppTest.java", "thing.spec.js"):
            with self.subTest(name=name):
                self.assertEqual(execcheck.entrypoints(ws(**{name: self.RUNNER})), [])

    def test_the_real_program_is_still_found_beside_tests(self):
        d = ws(**{"tool.py": PROGRAM, "test_tool.py": self.RUNNER})
        self.assertEqual(execcheck.entrypoints(d), ["tool.py"])

    def test_the_mellum2_attempt3_shape_is_correctly_empty(self):
        d = ws(**{"resolve_handle.py": LIBRARY, "test_resolve_handle.py": self.RUNNER})
        self.assertEqual(execcheck.entrypoints(d), [])
        r = execcheck.evaluate(d, {"runs": True, "command": "python3 resolve_handle.py goose",
                                   "success": "prints an address"})
        self.assertEqual(r.verdict, execcheck.INCONCLUSIVE)
        self.assertIn("entry point", r.why)


if __name__ == "__main__":
    unittest.main()
