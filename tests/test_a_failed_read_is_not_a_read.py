"""A read that returned no bytes was recorded as a read of those bytes.

`read_file` lowered to a bare `cat <path>`. On a missing path the harness handed back bash's own
error — "/bin/bash: line 2: x: No such file or directory / cat: x: No such file or directory" — as
the tool RESULT. That text is non-empty and carries no denied mark, which are exactly the two things
`research.files_read` tests. So the ledger recorded:

    Importer.java — 261 chars read from disk

for a 6,783-byte file at a path holding only directories. A judge read the ledger, ruled the reading
step DONE, and the run continued without any call ever opening the code. Measured across both
battery arms: 4 distinct failed reads recorded as successful ones.

`files_read`'s docstring already had the rule right — *"An attempted read is not a read"*. Its input
was lying to it.

FIXED AT THE COMPOSING SITE, NOT IN THE LEDGER. cria writes this command, so cria states what
happened, in its own voice, once (#5b) — through the same refusal owner every other guard uses, so
the result carries the denied mark and a non-zero exit. `research.py` is not touched: the mark is
already what it tests, so the ledger becomes correct as a consequence rather than by a second check.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from cria import denial, research
from cria.writeproxy import _read_command


def _run(cmd: str, cwd: str) -> tuple[int, str]:
    p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, cwd=cwd)
    return p.returncode, p.stdout + p.stderr


def _tool_result(body: str) -> list:
    """The message pair the ledger reads: a read_file call and the result it came back with."""
    return [
        {"role": "assistant", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "read_file", "arguments": '{"path":"Importer.java"}'}}]},
        {"role": "tool", "tool_call_id": "c1", "content": body},
    ]


class AReadThatReturnedNothingIsRefusedTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        Path(self.ws, "real.txt").write_text("actual content\n")
        Path(self.ws, "adir").mkdir()

    def test_a_missing_file_is_marked_as_a_call_that_did_not_run(self):
        code, out = _run(_read_command({"path": "Importer.java"}), self.ws)
        self.assertNotEqual(code, 0, "a read that returned nothing must not report success")
        self.assertTrue(denial.is_denied(out), f"not marked as a refusal:\n{out}")
        self.assertNotIn("No such file or directory", out, "bash's raw error still leaks through")
        self.assertIn("is not there", out)

    def test_a_directory_says_so_and_names_the_tool_that_works(self):
        code, out = _run(_read_command({"path": "adir"}), self.ws)
        self.assertNotEqual(code, 0)
        self.assertTrue(denial.is_denied(out))
        self.assertIn("list_dir", out)

    def test_an_unreadable_file_is_refused_too(self):
        p = Path(self.ws, "locked.txt")
        p.write_text("secret")
        p.chmod(0o000)
        try:
            code, out = _run(_read_command({"path": "locked.txt"}), self.ws)
        finally:
            p.chmod(0o644)
        if code == 0:
            self.skipTest("running as a user that can read a 000 file")
        self.assertTrue(denial.is_denied(out))

    def test_a_real_read_is_completely_unchanged(self):
        code, out = _run(_read_command({"path": "real.txt"}), self.ws)
        self.assertEqual(code, 0)
        self.assertEqual(out, "actual content\n")
        self.assertFalse(denial.is_denied(out))

    def test_a_ranged_read_of_a_real_file_still_works(self):
        Path(self.ws, "many.txt").write_text("".join(f"line {i}\n" for i in range(1, 21)))
        code, out = _run(_read_command({"path": "many.txt", "start_line": 3, "end_line": 5}), self.ws)
        self.assertEqual(code, 0)
        self.assertIn("line 3", out)
        self.assertNotIn("line 9", out)


class TheLedgerIsCorrectedWithoutBeingTouchedTests(unittest.TestCase):
    """The point of composing-site repair: `research.py` needed no change."""

    def setUp(self):
        self.ws = tempfile.mkdtemp()

    def test_the_old_bash_error_was_counted_as_a_read(self):
        """The regression, stated as the ledger saw it. 261 chars, exactly as recorded in the run."""
        bash_error = ("/bin/bash: line 2: Importer.java: No such file or directory\n"
                      "cat: Importer.java: No such file or directory\n")
        self.assertEqual(research.files_read(_tool_result(bash_error)),
                         [("Importer.java", len(bash_error))])

    def test_what_cria_now_returns_is_not_counted(self):
        _, out = _run(_read_command({"path": "Importer.java"}), self.ws)
        self.assertEqual(research.files_read(_tool_result(out)), [],
                         "the ledger still counts a read that returned no bytes")

    def test_a_real_read_still_counts(self):
        Path(self.ws, "real.txt").write_text("actual content\n")
        _, out = _run(_read_command({"path": "real.txt"}), self.ws)
        self.assertEqual(research.files_read(
            [{"role": "assistant", "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "read_file", "arguments": '{"path":"real.txt"}'}}]},
             {"role": "tool", "tool_call_id": "c1", "content": out}]),
            [("real.txt", len(out))])


if __name__ == "__main__":
    unittest.main()
