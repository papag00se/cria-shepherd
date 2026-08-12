"""The program a command runs is decided by the runner's grammar, not by position.

`program_token` scanned forward for the first argument containing a dot or a slash — the
`python script.py arg` shape — which cannot tell an executable from an input datum. Run against real
commands from the six-language battery:

    cargo run --quiet -- config.toml server.port  ->  'config.toml'
    java -cp target/classes App in.csv            ->  'target/classes'
    go run . goose                                ->  '.'

That produced "the delivered program was not run, because config.toml is not an entry point on disk"
for a Rust CLI that ran correctly and printed the right answer.

Resolution is now head-first: a build tool's target is the PROJECT, `--` ends the runner's own flags,
`-cp` takes a value that is configuration, `-m` takes a value that IS the program, and a JVM main
class is a bare name with no extension for the old test to find.
"""
import unittest

from cria.execcheck import program_token as pt


class TheRunnersGrammarDecidesTests(unittest.TestCase):
    CASES = {
        # build tools: the project is the target, the filenames after are arguments
        "cargo run --quiet -- config.toml server.port": "cargo run",
        "go run . goose": "go run",
        "mvn test": "mvn test",
        "./gradlew test": "gradlew test",
        "rake test": "rake test",
        "npm start": "npm start",
        # interpreters: the file IS the program
        "python3 resolve_handle.py goose": "resolve_handle.py",
        "node lookup.js goose": "lookup.js",
        "ruby lib/shipping.rb": "lib/shipping.rb",
        # flags whose value is configuration vs flags whose value is the program
        "java -cp target/classes App in.csv": "App",
        "java -jar build/app.jar": "build/app.jar",
        "python3 -m orders.app 8080": "orders.app",
    }

    def test_each_command_resolves_to_what_it_actually_runs(self):
        for cmd, want in self.CASES.items():
            with self.subTest(cmd=cmd):
                self.assertEqual(pt(cmd), want)

    def test_an_input_file_after_a_double_dash_is_never_the_program(self):
        self.assertNotIn("config.toml", pt("cargo run -- config.toml key"))

    def test_a_classpath_is_never_the_program(self):
        self.assertNotEqual(pt("java -cp target/classes App"), "target/classes")

    def test_the_same_program_from_two_phrasings_compares_equal(self):
        """The whole point: a README example and a live invocation differ in their ARGUMENTS."""
        self.assertEqual(pt("cargo run -- a.toml x"), pt("cargo run --quiet -- b.toml y"))
        self.assertEqual(pt("python3 tool.py goose"), pt("python3 tool.py papagoose"))

    def test_empty_is_empty(self):
        self.assertEqual(pt(""), "")


if __name__ == "__main__":
    unittest.main()
