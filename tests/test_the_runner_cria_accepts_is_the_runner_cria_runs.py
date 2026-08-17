"""Two sets answered "is this a program launcher", and they disagreed on five languages.

`corroborate` accepts a command as a project's real entry point when the project's own manifest
declares it — `_PROJECT_RUNNERS` is the table of launchers whose TARGET IS THE PROJECT rather than a
file named on the line. `_runnable` then decides whether cria will actually execute it, and it read
a DIFFERENT set:

    _RUNNERS = {python, python3, node, ruby, php, java, go, cargo, npm, pnpm, yarn,
                deno, bun, dotnet, mvn, ./gradlew}

so `rake test`, `make run`, `mix test`, `gradle test` and `bundle exec …` were accepted as the entry
point and then refused as unrunnable. The live-execution marker came back empty and the deliverable
was never observed — on Ruby, Elixir, Make-driven and plain-Gradle projects, which is to say on
whole languages at a time.

The refusal is `'rake' is not a recognized program runner`, 8 of them in the captures. It names
something the coder cannot change: its project's own runner (#5b).

WHAT BOUNDS THIS CHECK is not the length of cria's list. It is that `corroborate` requires the
project to have DECLARED the command before cria runs anything, plus `_SHELL_META` refusing any
composed line. `npm test` was already allowed and executes whatever package.json says; `rake test` is
no more arbitrary than that. #23: one owner for one question.
"""

import unittest

from cria import execcheck


class TheDeclaredRunnersAreRunnableTests(unittest.TestCase):
    def test_every_project_runner_is_accepted(self):
        """The invariant, stated as a relation between the two tables rather than a list: anything
        corroborate will accept as the entry point, _runnable must be willing to execute — with ONE
        deliberate exception, below."""
        for head, subs in execcheck._PROJECT_RUNNERS.items():
            non_test = [x for x in subs if x not in ("test", "check")] or [""]
            cmd = f"{head} {non_test[0]}".strip()
            if execcheck._is_a_test_command(cmd.split()):
                continue                     # the exception — see TheTestSuiteIsNotTheProgramTests
            with self.subTest(command=cmd):
                ok, why = execcheck._runnable(cmd)
                self.assertTrue(ok, why)

    def test_the_five_that_were_refused(self):
        """Non-test forms of the five whole languages that were accepted and then refused."""
        for cmd in ("rake build", "make run", "mix run", "gradle run", "bundle exec ruby app.rb"):
            with self.subTest(command=cmd):
                self.assertEqual(execcheck._runnable(cmd), (True, ""))

    def test_what_already_worked_still_does(self):
        for cmd in ("cargo run", "python3 app.py", "java -jar app.jar", "./gradlew run",
                    "node lookup.js goose", "npm start"):
            with self.subTest(command=cmd):
                self.assertTrue(execcheck._runnable(cmd)[0])


class TheTestSuiteIsNotTheProgramTests(unittest.TestCase):
    """The one deliberate exception to the invariant above, and why it is not the defect this file
    was written about.

    That defect was cria refusing a command NAMING SOMETHING THE CODER COULD NOT CHANGE — its
    project's own runner — and coming back with an empty live-execution marker as a result. This is
    different in kind: the command is perfectly runnable, and cria declines because `proberun`
    already runs it. Running it here means the suite executes a THIRD time in the live workspace
    between coder turns, on top of the gate's online run and its network-off comparison.

    Walked on cycle 4 cell 21 (`orders-api-py x nemotron-elastic`, 70% useful — the missing point is
    exactly this). The model's tests share one repo-relative `orders.db` that nothing deletes, so
    every extra run appends a row. Its own run reported `assert 22.5 < 0.01`, where `22.5 = abs(30.0
    - 7.5)` and `30.0` is four rows of `3 x 2.50`: one from the coder's run and three from cria's. It
    never saw the other three and spent the tail of the run theorising about pytest parameterisation.

    For a project with no program to run — a pure library — abstaining is the honest answer (#11b),
    not a loss."""

    def test_every_launcher_spelling_of_run_the_tests(self):
        for cmd in ("python3 -m pytest", "python3 -m pytest -q", "pytest", "npm test",
                    "go test ./...", "cargo test", "mvn test", "rake test", "node --test",
                    "npx jest", "bundle exec rspec", "./gradlew test", "./mvnw test"):
            with self.subTest(command=cmd):
                ok, why = execcheck._runnable(cmd)
                self.assertFalse(ok, cmd)
                self.assertIn("the repo's own checks already do", why)

    def test_a_program_whose_NAME_contains_test_is_not_a_test_command(self):
        """Matched on the subcommand or the runner, never on a filename — someone may legitimately
        have delivered `test_helper.py`."""
        for cmd in ("python3 test_helper.py", "node test-server.js", "./testrunner-app"):
            with self.subTest(command=cmd):
                self.assertTrue(execcheck._runnable(cmd)[0], cmd)

    def test_the_refusal_does_not_blame_the_coder(self):
        """The lesson of this file: a refusal must not name something the coder cannot change."""
        _, why = execcheck._runnable("npm test")
        self.assertNotIn("not a recognized program runner", why)


class WhatCriaStillWillNotRunTests(unittest.TestCase):
    """The point of the check is to observe a DELIVERED PROGRAM, never to give a weak model a way to
    have cria run what it likes. Widening the launcher set must not widen that."""

    def test_an_arbitrary_binary(self):
        for cmd in ("curl http://example.com", "rm -rf /", "sudo apt install x", "bash -c x"):
            with self.subTest(command=cmd):
                ok, why = execcheck._runnable(cmd)
                self.assertFalse(ok)
                self.assertIn("not a recognized program runner", why)

    def test_a_composed_shell_line(self):
        ok, why = execcheck._runnable("rake test | tee /tmp/out")
        self.assertFalse(ok)
        self.assertIn("shell pipeline", why)

    def test_an_unparseable_command(self):
        self.assertFalse(execcheck._runnable('rake "unterminated')[0])

    def test_an_empty_command(self):
        self.assertFalse(execcheck._runnable("")[0])


class TheRefusalNamesSomethingChangeableTests(unittest.TestCase):
    def test_a_refused_head_is_quoted_back(self):
        _, why = execcheck._runnable("curl http://x")
        self.assertIn("'curl'", why)

    def test_no_declared_runner_can_produce_that_refusal(self):
        """The measured incident, as an invariant: this message must be unreachable for any launcher
        the project itself could have declared."""
        for head in execcheck._PROJECT_RUNNERS:
            with self.subTest(head=head):
                _, why = execcheck._runnable(f"{head} test")
                self.assertNotIn("not a recognized program runner", why)


if __name__ == "__main__":
    unittest.main()
