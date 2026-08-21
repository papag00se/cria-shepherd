"""The block that says "these are the newest files" stepped over files without saying so.

`files_for_a_judge` heads its block with

    ⟦ctx:files⟧ THE CONTENTS OF THE {{COUNT}} MOST RECENTLY CHANGED FILES IN {{ROOT}} … Judge
    against these rather than asking for them again.

and the loop under it had two bare `continue`s: one for a file cria has never been handed the
contents of, one for a binary. Either could drop the NEWEST file — the one the coder had just
written, which is the whole reason a judge is looking — and then N was counted from what was left
and the judge was told not to ask. The oversize case was named for exactly this reason; these two
were not.

Named only where the claim reaches: `entries` is newest-first, so a drop before the last file shown
is one the sentence stepped over. A drop after it is an older file the block never claimed to carry,
and naming every one would print the workspace under a header about recent work.
"""

import os
import pathlib
import tempfile
import time
import unittest

from cria import groundtruth, prompts, wsview


def _workspace(files):
    """`files` newest LAST, so the mtimes are unambiguous."""
    ws = tempfile.mkdtemp()
    for i, (rel, body) in enumerate(files):
        p = pathlib.Path(ws, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body if isinstance(body, bytes) else body.encode())
        os.utime(p, (time.time() + i, time.time() + i))
    return ws


class ADroppedNewerFileIsNamedTests(unittest.TestCase):
    def test_a_binary_newer_than_the_shown_files_is_named(self):
        ws = _workspace([("rates.rb", "def total; 1; end\n"),
                         ("orders.db", b"SQLite format 3\x00" + os.urandom(512))])
        out = groundtruth.files_for_a_judge(ws)
        self.assertIn("rates.rb", out)
        self.assertIn("orders.db", out)                       # not silently gone
        self.assertIn("nothing to read", out)                 # ...and said to be unreadable
        self.assertNotIn("SQLite format", out)                # ...without its bytes

    def test_a_file_crias_view_has_no_contents_for_is_named(self):
        """The production case: the harness surveys the tree and hands back a few bodies. A file
        whose contents never arrived is not evidence of an empty file."""
        ws = _workspace([("rates.rb", "def total; 1; end\n"), ("shipping.rb", "module S; end\n")])

        class _Partial(wsview.DirectView):
            def read(self, path):
                return None if str(path).endswith("shipping.rb") else super().read(path)

        token = wsview.bind(_Partial())
        self.addCleanup(wsview.unbind, token)
        out = groundtruth.files_for_a_judge(ws)
        self.assertIn("shipping.rb", out)
        self.assertIn("Use read_file", out)                   # the judge is told how to get it
        self.assertIn("def total", out)                       # the readable one is still quoted

    def test_the_two_reasons_say_different_things(self):
        """read_file recovers one and cannot help with the other, so they are not one sentence."""
        labels = prompts.load_map("judge_files")
        self.assertIn("read_file", labels["not_quoted"])
        self.assertNotIn("read_file", labels["binary"])


class ItStillSaysNothingAboutOlderFilesTests(unittest.TestCase):
    def test_an_older_unquotable_file_is_not_listed(self):
        """It is in the workspace inventory beside this block. Under a header about recent work it
        would be noise, and the whole reason this block exists is that a judge stops reading."""
        ws = _workspace([("legacy.png", b"\x89PNG\r\n\x1a\n" + os.urandom(512)),
                         ("rates.rb", "def total; 1; end\n")])
        out = groundtruth.files_for_a_judge(ws)
        self.assertIn("rates.rb", out)
        self.assertNotIn("legacy.png", out)

    def test_an_empty_workspace_still_says_nothing_at_all(self):
        self.assertEqual(groundtruth.files_for_a_judge(tempfile.mkdtemp()), "")


if __name__ == "__main__":
    unittest.main()
