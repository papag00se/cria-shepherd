"""A transport-size refusal must offer a range that actually works.

The former whole-read refusal offered grep or a line range without saying how many lines were in
an oversized file or offering a first window. That version was rendered 420 times; the coder's
opening guess was therefore blind. The 40% context guard was removed; the shared transport bound
now refuses unrepresentable output without clipping and suggests a range that must actually fit.
"""

import json
import pathlib
import subprocess
import tempfile
import unittest

from cria import denial, filecommands, writeproxy


def _read(path, **bounds):
    return subprocess.run(
        ["sh", "-c", writeproxy._read_command({"path": str(path), **bounds})],
        capture_output=True, text=True,
    )


def _numbered(lines, start=1):
    return "".join(f"{i}: {line}\n" for i, line in enumerate(lines, start))


def _pages(path, start, end):
    """Run each offered range, then continue from its actual end without gaps."""
    chunks = []
    while start <= end:
        result = _read(path, start_line=start, end_line=end)
        assert result.returncode == 0
        assert len(result.stdout.encode()) <= filecommands.READ_TRANSPORT_STDOUT_BYTES
        if not denial.is_denied(result.stdout):
            chunks.append(result.stdout)
            break
        assert 'No file content was returned' in result.stdout
        args = json.loads(result.stdout.split('Next read_file arguments: ', 1)[1])
        assert args['path'] == str(path) and args['start_line'] == start
        assert start <= args['end_line'] < end
        page = _read(path, start_line=start, end_line=args['end_line'])
        assert page.returncode == 0 and not denial.is_denied(page.stdout)
        assert len(page.stdout.encode()) <= filecommands.READ_TRANSPORT_STDOUT_BYTES
        chunks.append(page.stdout)
        start = args['end_line'] + 1
    return ''.join(chunks)


class LargeWholeAndRangeReadsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.big = pathlib.Path(self.directory.name, "big.py")
        self.lines = [f"x = {i}" for i in range(4000)]
        self.body = "\n".join(self.lines) + "\n"
        self.big.write_text(self.body)
        self.small = pathlib.Path(self.directory.name, "small.py")
        self.small.write_text("x = 1\n")

    def test_followup_ranges_include_the_last_line(self):
        result = _pages(self.big, 1, len(self.lines))
        self.assertEqual(result.splitlines()[-1], f'4000: {self.lines[-1]}')
        self.assertEqual(len(result.splitlines()), 4000)

    def test_oversized_whole_read_refuses_without_clipping(self):
        result = _read(self.big)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(denial.is_denied(result.stdout))
        self.assertIn('No file content was returned', result.stdout)
        self.assertNotIn(self.lines[-1], result.stdout)

    def test_first_range_is_usable(self):
        result = _read(self.big, start_line=1, end_line=200)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, _numbered(self.lines[:200]))

    def test_oversized_whole_read_is_marked_as_returning_no_content(self):
        result = _read(self.big)
        self.assertTrue(denial.is_denied(result.stdout))
        self.assertIn('No file content was returned', result.stdout)
        self.assertNotIn(self.lines[0], result.stdout)

    def test_no_placeholder_is_added_to_whole_read_refusal(self):
        result = _read(self.big)
        self.assertTrue(denial.is_denied(result.stdout))
        self.assertNotIn("{{", result.stdout)
        self.assertIn('Next read_file arguments:', result.stdout)

    def test_consecutive_pages_cover_the_file_without_gaps(self):
        first = _read(self.big, start_line=1, end_line=200)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(first.stdout + _pages(self.big, 201, 4000), _numbered(self.lines))

    def test_large_range_offers_replayable_pages(self):
        result = _read(self.big, start_line=1, end_line=4000)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(denial.is_denied(result.stdout))
        self.assertEqual(_pages(self.big, 1, 4000), _numbered(self.lines))

    def test_a_small_file_still_comes_back_whole(self):
        self.assertEqual(_read(self.small).stdout, "x = 1\n")


class LargeFileShapesTests(unittest.TestCase):
    """feed-pipeline-java x nemotron-elastic, calls 0041 and 0042.

    The former guard recommended a constant first window of 200 lines without measuring the
    file or the numbered output. For Importer.java that window exceeded its own size limit, so
    the suggested read was refused and the coder worked from tiny grep results for the next
    66 calls. Transport-bounded follow-up ranges must actually work for wide, narrow, ragged
    and unterminated lines, and reconstruct the requested content without gaps.
    """

    SHAPES = {
        "wide lines": ("x" * 60 + "\n") * 400,
        "narrow lines": "x = 1\n" * 4000,
        "ragged lines": "".join(("a" * (i % 200 + 1)) + "\n" for i in range(900)),
        "no trailing newline": "z" * 40 + "\n" + ("w" * 300 + "\n") * 40 + "tail",
    }

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = pathlib.Path(self.directory.name, "f.java")

    def test_first_200_lines_are_recoverable_for_each_shape(self):
        for name, body in self.SHAPES.items():
            with self.subTest(name=name):
                self.path.write_text(body)
                self.assertEqual(_pages(self.path, 1, 200), _numbered(body.splitlines()[:200]))

    def test_full_range_is_recovered_even_when_larger_than_old_window(self):
        for name, body in self.SHAPES.items():
            with self.subTest(name=name):
                self.path.write_text(body)
                lines = body.splitlines()
                self.assertEqual(_pages(self.path, 1, len(lines)), _numbered(lines))

    def test_whole_read_refusals_offer_working_ranges_for_different_shapes(self):
        for name in ("wide lines", "narrow lines"):
            with self.subTest(name=name):
                body = self.SHAPES[name]
                self.path.write_text(body)
                result = _read(self.path)
                self.assertTrue(denial.is_denied(result.stdout))
                args = json.loads(result.stdout.split('Next read_file arguments: ', 1)[1])
                page = _read(self.path, start_line=args['start_line'], end_line=args['end_line'])
                self.assertEqual(args['path'], str(self.path))
                self.assertEqual(args['start_line'], 1)
                self.assertEqual(page.stdout, _numbered(body.splitlines()[:args['end_line']]))

    def test_one_long_line_offers_byte_oriented_inspection(self):
        body = "y" * 20000
        self.path.write_text(body)
        result = _read(self.path)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(denial.is_denied(result.stdout))
        self.assertIn('byte-oriented shell command', result.stdout)
        self.assertNotIn('Next read_file arguments:', result.stdout)
        chunk = subprocess.run(['head', '-c', '1000', str(self.path)], capture_output=True, text=True, check=True)
        self.assertEqual(chunk.stdout, body[:1000])

    def test_no_placeholder_is_added_to_long_or_wide_refusal(self):
        for body in ("y" * 20000, self.SHAPES["wide lines"]):
            with self.subTest(length=len(body)):
                self.path.write_text(body)
                result = _read(self.path)
                self.assertTrue(denial.is_denied(result.stdout))
                self.assertIn('No file content was returned', result.stdout)
                self.assertNotIn("{{", result.stdout)


if __name__ == "__main__":
    unittest.main()
