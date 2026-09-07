"""A judge whose read misses one file must not conclude read_file is dead and rule blind.

Walked on ornith15 x shipping-rates-rb 2026-09-07 (session …be7420b58e1f, satisfaction turns
0031–0038, 0064–0068). The satisfaction judge is fed its files through the harness workspace view;
the deliverables' bytes had not reached that view, so the up-front block named them "not reached this
seat" and read_file returned the "could not be read" miss. The judge read both as a capability
statement — "read_file blocked (read-only harness restriction)", in its own words — stopped reading
EVERY file (including the ones it COULD read), and ruled on file-size heuristics and a stale log that
showed the ORIGINAL, unmodified deliverables.

The miss is real and, by design (aee15aa: a body miss is served by the next survey, which rides a
harness command a judge's back-to-back rounds never send), it cannot clear inside the check — so the
judge must not RETRY it. But the failure is about ONE file's bytes, not the tool: read_file still
serves every file whose bytes arrived. The messages now say so, and drop the invite→refuse
contradiction (the block used to say "Use read_file if you need one of them" for the very files the
read then refused).
"""

import unittest

from cria import prompts


class TheReadMissScopesToTheFileTests(unittest.TestCase):
    def test_the_unknown_read_affirms_the_tool_still_works(self):
        msg = prompts.load_map("verify_tools")["unknown"]
        # It must not read as "the tool is off": it names read_file as still working on other files.
        self.assertIn("read_file still returns", msg)
        self.assertIn("keep using it on the others", msg)

    def test_the_unknown_read_still_forbids_retrying_this_file(self):
        """aee15aa's intent is preserved: this one file cannot clear inside the check, so do not
        spend another round asking for it."""
        msg = prompts.load_map("verify_tools")["unknown"]
        self.assertIn("do not ask for it again", msg)

    def test_the_unknown_read_stays_fail_closed(self):
        msg = prompts.load_map("verify_tools")["unknown"]
        self.assertIn("NOT evidence the file is absent", msg)
        self.assertIn("do not call the work done", msg)

    def test_the_named_but_unshown_block_does_not_invite_a_read_that_fails(self):
        """The block used to say "Use read_file if you need one of them" about files whose bytes the
        same view had not delivered — so the very next read_file was refused. That invite→refuse pair
        is what taught the judge reads do not work; it is gone."""
        msg = prompts.load_map("judge_files")["not_quoted"]
        self.assertNotIn("Use read_file if you need one of them", msg)
        self.assertIn("read_file cannot return these inside this check", msg)
        # …but the tool is still affirmed for the files that ARE available.
        self.assertIn("still works on any file that IS available", msg)

    def test_neither_message_shows_the_model_the_shims_name(self):
        for key, m in (("verify_tools", "unknown"), ("judge_files", "not_quoted")):
            self.assertNotIn("cria", prompts.load_map(key)[m].lower())


if __name__ == "__main__":
    unittest.main()
