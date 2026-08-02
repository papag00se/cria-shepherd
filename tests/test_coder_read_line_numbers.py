"""The crew's read_file numbers lines; the coder's did not. Same tool name, two different views —
and only the model that has to EDIT by line number got the one without them.

Walked on ada-handles_mellum2_codex_poff_1785693138: the coder asked for lines 55-68 to see the line
a check flagged at 63, got the text naked, counted from the top of the block, and burned 8,234
reasoning tokens insisting a valid f-string was valid. Three more calls went to finding one line.
"""
import os
import subprocess
import tempfile
import unittest

from cria import verifytools, writeproxy


def _ws(n=20):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "x.py")
    open(p, "w").write("".join(f"line {i}\n" for i in range(1, n + 1)))
    return p


def _run(cmd):
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True).stdout


class RangedReadTests(unittest.TestCase):
    def test_a_ranged_read_is_numbered_from_the_real_line_number(self):
        out = _run(writeproxy._read_command({"path": _ws(), "start_line": 5, "end_line": 8}))
        self.assertEqual(out.splitlines(),
                         ["5: line 5", "6: line 6", "7: line 7", "8: line 8"])

    def test_a_single_line_read_names_that_line(self):
        out = _run(writeproxy._read_command({"path": _ws(), "start_line": 13, "end_line": 13}))
        self.assertEqual(out.strip(), "13: line 13")

    def test_an_open_ended_range_keeps_counting_correctly(self):
        out = _run(writeproxy._read_command({"path": _ws(6), "start_line": 4}))
        self.assertEqual(out.splitlines(), ["4: line 4", "5: line 5", "6: line 6"])

    def test_a_WHOLE_file_read_is_unchanged(self):
        # Only ranged reads are numbered — a whole-file read is content the model may copy.
        out = _run(writeproxy._read_command({"path": _ws(3)}))
        self.assertEqual(out.splitlines(), ["line 1", "line 2", "line 3"])

    def test_past_the_end_of_file_still_says_so(self):
        out = _run(writeproxy._read_command({"path": _ws(5), "start_line": 99, "end_line": 100}))
        self.assertIn("past the end of the file", out)

    def test_the_two_read_file_tools_now_agree(self):
        p = _ws()
        coder = _run(writeproxy._read_command({"path": p, "start_line": 5, "end_line": 8}))
        crew = verifytools._read_file({"path": p, "start_line": 5, "end_line": 8},
                                      os.path.dirname(p))
        self.assertEqual([l.strip() for l in coder.strip().splitlines()],
                         [l.strip() for l in crew.strip().splitlines()])


if __name__ == "__main__":
    unittest.main()
