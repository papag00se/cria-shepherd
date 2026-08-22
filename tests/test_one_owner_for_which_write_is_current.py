"""Three modules answered "which write is current", with three different tool-name lists.

`focustrim` had four names, `contextfloor` six, `selfcompact` two — so whether a call counted as a
write depended on which module was asked. And all three treated an `edit_file` as a version of a
file, which it is not: a 500-character edit deleted a 3,000-character `write_file` of the same path
while the note still read *"The newest version of each of those files is still here in full … Nothing
was lost."* Reproduced before the fix.

`toolargs.write_target` is the one owner. It answers two things, and the second is the one that
matters: does this call REPLACE the file, or change part of it?

Each caller asks the question it actually needs:
  * `focustrim` decides a DELETION, so it needs the strong form — only a whole-file write may
    supersede, and it supersedes everything before it.
  * `selfcompact` decides whether to fold a payload to a pointer, which is about being HISTORICAL —
    an older `edit_file` is just as historical as an older `write_file`.
  * `contextfloor` names files a dropped turn wrote, and now checks the write landed.
"""

import json
import unittest

from cria import contextfloor, denial, focustrim, selfcompact, toolargs


def call(cid, name, args):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def turn(cid, name, args):
    return {"role": "assistant", "tool_calls": [call(cid, name, args)]}


def wrote(cid, path="/w/app.py"):
    return {"role": "tool", "tool_call_id": cid, "content": f"⟦ctx:wrote⟧ Wrote {path}"}


class TheDistinctionItselfTests(unittest.TestCase):
    def test_a_whole_file_write_replaces_and_an_edit_does_not(self):
        for name in toolargs.WHOLE_FILE_WRITES:
            with self.subTest(tool=name):
                self.assertEqual(toolargs.write_target(call("x", name, {"path": "/w/a"})),
                                 ("/w/a", True))
        for name in toolargs.PARTIAL_WRITES:
            with self.subTest(tool=name):
                self.assertEqual(toolargs.write_target(call("x", name, {"path": "/w/a"})),
                                 ("/w/a", False))

    def test_a_read_is_not_a_write(self):
        self.assertEqual(toolargs.write_target(call("x", "read_file", {"path": "/w/a"})), ("", False))

    def test_all_three_modules_now_share_one_list(self):
        self.assertEqual(selfcompact._WRITE_TOOL_NAMES, toolargs.WRITE_TOOL_NAMES)
        self.assertEqual(contextfloor._WRITE_TOOL_NAMES, toolargs.WRITE_TOOL_NAMES)


class AnEditNeverDeletesAWriteTests(unittest.TestCase):
    """focustrim's rule decides a DELETION, so it takes the strong form."""

    def test_an_edit_after_a_write_leaves_the_write_alone(self):
        msgs = [turn("w1", "write_file", {"path": "/w/app.py", "content": "y" * 3000}), wrote("w1"),
                turn("e1", "edit_file", {"path": "/w/app.py",
                                         "old_string": "y" * 500, "new_string": "z" * 500}), wrote("e1")]
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 0)
        self.assertIn("y" * 3000, json.dumps(out), "the only full copy of the file was deleted")

    def test_a_write_after_a_write_still_supersedes(self):
        msgs = [turn("w1", "write_file", {"path": "/w/app.py", "content": "y" * 3000}), wrote("w1"),
                turn("w2", "write_file", {"path": "/w/app.py", "content": "z" * 3000}), wrote("w2")]
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 1)
        self.assertNotIn("y" * 3000, json.dumps(out))
        self.assertIn("z" * 3000, json.dumps(out))

    def test_a_write_supersedes_an_earlier_edit_too(self):
        """Everything before the last whole-file write is historical, edits included."""
        msgs = [turn("e1", "edit_file", {"path": "/w/app.py",
                                         "old_string": "q" * 500, "new_string": "r" * 500}), wrote("e1"),
                turn("w1", "write_file", {"path": "/w/app.py", "content": "z" * 3000}), wrote("w1")]
        _out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 1)

    def test_an_edit_after_the_last_write_is_the_newest_change_and_survives(self):
        msgs = [turn("w1", "write_file", {"path": "/w/app.py", "content": "z" * 3000}), wrote("w1"),
                turn("e1", "edit_file", {"path": "/w/app.py",
                                         "old_string": "z" * 500, "new_string": "k" * 500}), wrote("e1")]
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 0)
        self.assertIn("k" * 500, json.dumps(out))


class TheFloorDoesNotNameAFileThatWasRefusedTests(unittest.TestCase):
    """Its note says the files are "still on disk". Walked: a pom.xml write cria itself refused as
    malformed XML was named in that sentence."""

    def test_a_refused_write_is_not_named(self):
        msgs = [turn("w1", "write_file", {"path": "/w/pom.xml", "content": "<bad"}),
                {"role": "tool", "tool_call_id": "w1", "content": denial.mark("refused: malformed XML")},
                turn("w2", "write_file", {"path": "/w/App.java", "content": "class A{}"}), wrote("w2", "/w/App.java")]
        self.assertEqual(contextfloor._modified_files(msgs), ["/w/App.java"])

    def test_a_write_that_landed_still_is(self):
        msgs = [turn("w2", "write_file", {"path": "/w/App.java", "content": "class A{}"}),
                wrote("w2", "/w/App.java")]
        self.assertEqual(contextfloor._modified_files(msgs), ["/w/App.java"])


if __name__ == "__main__":
    unittest.main()
