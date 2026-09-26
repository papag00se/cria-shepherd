"""A test run must not leave its scratch in the machine's shared temp directory.

Found 2026-09-26: /tmp (a tmpfs capped at 1,048,576 inodes) was at 97% — 28,584 `tmpXXXXXXXX`
fixture directories (~956k inodes), 5,500 `.cria-gate-*` spools written by real gate shells through
`${TMPDIR:-/tmp}`, and ~690 `cria-context-retry-*` capture dirs. Every one came from this suite:
~61 full runs x ~470 `tempfile.mkdtemp()` fixtures that no test removed. Other sessions on the box
were starting to fail for want of inodes.

The fix is one place, not 470: `tests/conftest.py` gives the whole session a private temp root
(`tempfile.tempdir` for this process, `TMPDIR` for every subprocess and gate shell it starts) and
removes it when the session ends.
"""

import os
import subprocess
import tempfile
import unittest


class TheSuiteHasAPrivateTempRootTests(unittest.TestCase):
    def test_python_scratch_goes_to_the_session_root(self):
        root = tempfile.gettempdir()
        self.assertTrue(os.path.basename(root).startswith("suite-session-"), root)
        d = tempfile.mkdtemp()
        self.assertEqual(os.path.dirname(d), root)

    def test_a_subprocess_shell_writes_to_the_same_root(self):
        """Gate scripts spool to ${TMPDIR:-/tmp}; the shell must see the session root."""
        out = subprocess.run(["sh", "-c", 'printf %s "${TMPDIR:-/tmp}"'],
                             capture_output=True, text=True).stdout
        self.assertEqual(out, tempfile.gettempdir())


if __name__ == "__main__":
    unittest.main()
