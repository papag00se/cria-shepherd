"""The refusal told the coder to read a line range and would not say how many lines there are.

`large_read_steer` refuses a whole read of an oversized file and offers two routes: grep, or
`read_file start_line/end_line`. It named neither a length nor a first window, so the coder's
opening guess is blind — while its own sibling for a spilled document says exactly that:

    spill_extent = It is {{LINES}} lines — read_file with start_line=1 end_line={{FITS}} fits in
                   one read, and you can page on from there.

420 renderings of the version without it.

The shell that runs the lowered read knows the number — `_list_command` already fills its entry
count the same way — so cria states it rather than making the coder discover it by paging.
"""

import pathlib
import re
import subprocess
import tempfile
import unittest

from cria import denial, writeproxy


def _read(path):
    return subprocess.run(["sh", "-c", writeproxy._read_command({"path": str(path)})],
                          capture_output=True, text=True).stdout


class AnOversizeRefusalNamesTheLengthTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.big = pathlib.Path(d, "big.py")
        self.big.write_text("x = 1\n" * 4000)
        self.small = pathlib.Path(d, "small.py")
        self.small.write_text("x = 1\n")

    def test_it_says_how_many_lines(self):
        self.assertIn("is 4000 lines", _read(self.big))

    def test_it_still_refuses_and_says_so(self):
        out = _read(self.big)
        self.assertIn("larger than can be returned in one read", out)
        self.assertIn("nothing is shown", out)

    def test_it_offers_a_first_window_the_coder_can_use(self):
        out = _read(self.big)
        self.assertIn("start_line=1", out)

    def test_it_is_marked_as_a_call_that_returned_nothing(self):
        from cria import denial
        self.assertTrue(denial.is_denied(_read(self.big)))

    def test_no_placeholder_survives(self):
        self.assertNotIn("{{", _read(self.big))

    def test_a_small_file_still_comes_back_whole(self):
        self.assertEqual(_read(self.small), "x = 1\n")


class TheWindowItNamesIsOneItWillHonourTests(unittest.TestCase):
    """feed-pipeline-java x nemotron-elastic, calls 0041 and 0042 — cria refusing its own advice.

    The first window was the literal `end_line=200`, a constant with no relationship to the file it
    was said about. cria refuses a RANGE over the same byte limit, so on a file with wide lines it
    recommended a read it then denied: lines 1-200 of Importer.java are 9,457 bytes. The coder sent
    exactly the window it was given, was refused, and never asked for a large window again — it
    worked from 5-line grep results for the next 66 calls, on the file it had just been told to
    rewrite whole.

    Two things have to be true for the promise to hold, and the constant broke both: the window has
    to be measured against THIS file, and against the bytes cria will RETURN — which are numbered,
    so every line costs its own line number too."""

    def _window(self, body):
        d = pathlib.Path(tempfile.mkdtemp(), "f.java")
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_text(body)
        out = _read(d)
        m = re.search(r"end_line=(\d+)", out)
        return d, (int(m.group(1)) if m else None), out

    def _range(self, path, end):
        return subprocess.run(
            ["sh", "-c", writeproxy._read_command(
                {"path": str(path), "start_line": 1, "end_line": end})],
            capture_output=True, text=True).stdout

    SHAPES = {
        "wide lines": ("x" * 60 + "\n") * 400,
        "narrow lines": "x = 1\n" * 4000,
        "ragged lines": "".join(("a" * (i % 200 + 1)) + "\n" for i in range(900)),
        "no trailing newline": "z" * 40 + "\n" + ("w" * 300 + "\n") * 40 + "tail",
    }

    def test_the_window_is_never_refused(self):
        for name, body in self.SHAPES.items():
            with self.subTest(name):
                path, end, _ = self._window(body)
                self.assertIsNotNone(end)
                self.assertFalse(denial.is_denied(self._range(path, end)))

    def test_the_window_is_as_large_as_it_can_be(self):
        """Not merely safe — maximal. A conservative guess would pass the test above and still
        leave the coder paging a file in slivers, which is the behaviour being fixed."""
        for name, body in self.SHAPES.items():
            with self.subTest(name):
                path, end, _ = self._window(body)
                self.assertTrue(denial.is_denied(self._range(path, end + 1)))

    def test_it_is_measured_against_the_file_it_names(self):
        """The old constant said 200 about every file. Two shapes, two answers."""
        _, wide, _ = self._window(self.SHAPES["wide lines"])
        _, narrow, _ = self._window(self.SHAPES["narrow lines"])
        self.assertNotEqual(wide, narrow)

    def test_a_file_with_no_window_to_offer_says_nothing_about_one(self):
        """One line, over the limit by itself — the grep route beside it is still true (#11b)."""
        path, end, out = self._window("y" * 20000)
        self.assertIsNone(end)
        self.assertNotIn("start_line=1 end_line", out)
        self.assertIn("grep -n", out)
        self.assertTrue(denial.is_denied(out))

    def test_no_placeholder_survives_either_way(self):
        for body in ("y" * 20000, self.SHAPES["wide lines"]):
            self.assertNotIn("{{", self._window(body)[2])


if __name__ == "__main__":
    unittest.main()
