"""validate-before-lower could only see Python, JSON and TOML.

The guard's contract is regression-only: refuse a write that would replace a file that CURRENTLY
PARSES with content that does not. `_v` dispatched on `.py`/`.pyi`, `.json` and `.toml` and fell off
the end for everything else, returning None — and both call sites read None as "nothing to refuse".

So on a `.rb`, `.go`, `.js`, `.php` or `.xml` file the refusal branch was UNREACHABLE. cria would
replace a parsing Ruby file with one that does not parse and say nothing, and the edit path's
`would_break` check was likewise always False. Measured across the six-language battery, where
cria's own write path corrupted a pom.xml and nothing detected it.

Per-extension entries are correct here — every language gets its equivalent check. The defect was
the missing rows. `_v` runs INSIDE the lowered heredoc, so it uses Python's own parsers in-process
and shells out for the rest; a missing tool, a timeout or an unknown extension all return None,
which means "cannot judge" and never refuses.
"""
import shutil
import unittest

from cria import writeproxy


def _v():
    ns = {}
    exec(writeproxy._VALIDATE_FN, ns)          # noqa: S102 — the function under test IS this source
    return ns["_v"]


class EveryLanguageCriaCanParseIsCheckedTests(unittest.TestCase):
    GOOD = {"a.py": "x = 1\n", "a.json": '{"a": 1}', "a.toml": "a = 1\n",
            "pom.xml": "<project><a/></project>",
            "a.rb": "def x\n  1\nend\n", "a.js": "const x = 1;\n"}
    BAD = {"a.py": "def (:\n", "a.json": "{nope}", "a.toml": "a = = 1\n",
           "pom.xml": "<project><unclosed>",
           "a.rb": "def x\n  1\n", "a.js": "const x = ;\n"}
    NEEDS = {"a.rb": "ruby", "a.js": "node"}

    def setUp(self):
        self.v = _v()

    def test_valid_content_is_accepted(self):
        for path, body in self.GOOD.items():
            if self.NEEDS.get(path) and not shutil.which(self.NEEDS[path]):
                continue
            with self.subTest(path=path):
                self.assertIsNone(self.v(path, body))

    def test_broken_content_is_reported(self):
        for path, body in self.BAD.items():
            if self.NEEDS.get(path) and not shutil.which(self.NEEDS[path]):
                continue
            with self.subTest(path=path):
                self.assertTrue(self.v(path, body), f"{path} was waved through")

    def test_the_message_names_the_real_path_not_the_temp_file(self):
        if not shutil.which("ruby"):
            self.skipTest("ruby absent")
        msg = self.v("lib/shipping/rates.rb", "def x\n  1\n")
        self.assertIn("rates.rb", msg)
        self.assertNotIn("/tmp/", msg)


class UnknownStaysSafeTests(unittest.TestCase):
    def setUp(self):
        self.v = _v()

    def test_an_extension_with_no_parser_is_no_opinion(self):
        self.assertIsNone(self.v("a.zzz", "anything at all"))

    def test_a_language_whose_tool_is_absent_is_no_opinion(self):
        """A missing checker must never become a refusal — the guard is regression-only (#2)."""
        ns = {}
        exec(writeproxy._VALIDATE_FN.replace("'ruby', '-c'", "'definitely-not-installed', '-c'"), ns)
        self.assertIsNone(ns["_v"]("a.rb", "def x\n  1\n"))

    def test_undecodable_bytes_are_no_opinion(self):
        self.assertIsNone(self.v("a.py", b"\xff\xfe\x00"))


if __name__ == "__main__":
    unittest.main()


class TheValidatorSourceMustSurviveTemplatingTests(unittest.TestCase):
    """_VALIDATE_FN is prepended to the write/edit heredocs, which are .format()ed with the path and
    content. A literal brace in this source reads as a format placeholder and takes the whole write
    path down — a dict literal here raised KeyError: "'" on every lowered write."""

    def test_the_validator_source_carries_no_literal_braces(self):
        self.assertNotIn("{", writeproxy._VALIDATE_FN)
        self.assertNotIn("}", writeproxy._VALIDATE_FN)

    def test_a_real_lowered_write_still_builds(self):
        """The end-to-end guard: the brace bug took down every write, and this is the call that
        raised KeyError on all 41 of them."""
        cmd = writeproxy._write_command("lib/shipping/rates.rb", "def x\n  1\nend\n")
        self.assertIn("def _v(", cmd)
        self.assertIn("_EXT_CMD", cmd)
