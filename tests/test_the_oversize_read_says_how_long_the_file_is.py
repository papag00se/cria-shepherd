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
import subprocess
import tempfile
import unittest

from cria import writeproxy


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


if __name__ == "__main__":
    unittest.main()
