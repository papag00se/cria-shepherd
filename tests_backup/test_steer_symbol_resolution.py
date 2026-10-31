"""A steer that names a symbol in a file where it does not exist.

The steer author names an identifier, a file or an absence without resolving it against disk — and
cria HAS disk. A weak model believes cria's assertion over its own reading: told a function lives in
a file where it does not exist, it invents a plausible one, and every later step builds on that.

Same enforcement class as `_phantom_system_path` and `_false_line_citation` beside it: cria can
settle this against the world, so a steer contradicting the world is refused rather than reworded
(#5b, and #13 — the safe direction is to withhold).

Deliberately narrow. Only a file that EXISTS inside the workspace is checkable; an unresolvable name
passes in silence (#3), and so does a short word that would make ordinary prose trip.
"""
import tempfile
import unittest
from pathlib import Path

from cria.loop import _symbol_not_in_the_file as check


def _ws(**files):
    d = tempfile.mkdtemp()
    for name, body in files.items():
        Path(d, name).write_text(body)
    return d


class ASymbolMustBeInTheFileTests(unittest.TestCase):
    APP = "def serve(port=8080):\n    pass\n\nclass Handler:\n    pass\n"

    def test_a_symbol_that_is_really_there_passes(self):
        self.assertIsNone(check("Call `serve` in app.py to start it.", _ws(**{"app.py": self.APP})))
        self.assertIsNone(check("Call serve() in app.py to start it.", _ws(**{"app.py": self.APP})))

    def test_a_symbol_that_is_not_there_is_caught(self):
        got = check("The handler lives in `start_server` in app.py.", _ws(**{"app.py": self.APP}))
        self.assertEqual(got, "start_server in app.py")

    def test_both_code_markings_are_read(self):
        """A steer names a function either in backticks or as a call. Those two, and only those —
        bare prose must never trip a guard that DROPS the steer."""
        ws = _ws(**{"db.py": "def init():\n    pass\n"})
        for phrasing in ("`migrate` in db.py", "migrate() inside db.py", "`migrate` from db.py"):
            with self.subTest(p=phrasing):
                self.assertTrue(check(f"Fix {phrasing} now.", ws))


class ItStaysSilentWhereItCannotKnowTests(unittest.TestCase):
    def test_a_file_that_does_not_exist_is_not_a_finding(self):
        """That claim belongs to the phantom-path guard, not this one."""
        self.assertIsNone(check("look at `resolve` in ghost.py", _ws(**{"app.py": "x = 1\n"})))

    def test_no_workspace_means_no_opinion(self):
        self.assertIsNone(check("`serve` in app.py", None))

    def test_ordinary_prose_does_not_trip_it(self):
        """The expensive direction: this guard DROPS the steer, so a false positive costs a
        legitimate directive."""
        ws = _ws(**{"app.py": "x = 1\n"})
        for prose in ("the change in app.py is small", "do all of it in app.py",
                      "the migration in app.py is missing", "look at the imports in app.py"):
            with self.subTest(prose=prose):
                self.assertIsNone(check(prose, ws))

    def test_a_path_outside_the_workspace_is_ignored(self):
        ws = _ws(**{"app.py": "x = 1\n"})
        self.assertIsNone(check("check `parse` in ../../etc/passwd.py", ws))


if __name__ == "__main__":
    unittest.main()
