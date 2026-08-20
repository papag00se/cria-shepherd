"""The note about removed writes names the files it removed, and never a file it did not touch.

`focustrim._drop_superseded_writes` removes an older whole-file write once a later write to the same
path replaces it, and leaves one ⟦ctx:facts⟧ note saying so. Two things in that note were wrong.

FIRST, it named the wrong files. `paths` was rendered from the map of every write TARGET in the
session, not from the calls actually dropped, so a note reporting ONE removal listed four files and
told the coder "what is on disk is what you last wrote" about three it had not removed anything for.

SECOND, a REFUSED write counted as the newest version. `last[path]` recorded every write-shaped call
including the ones cria denied, so a rejected write became the surviving copy and the real one before
it was dropped — leaving the model holding cria's rejection placeholder where the file's text should
be. `selfcompact` has drawn this distinction for its own span since the em-dash incident; this is the
same rule on the outbound trim path.

Walked on `feed-pipeline-java x nemotron-elastic` 20260820T103857 call 0054: the coder's `pom.xml`
write was refused as malformed XML ("not well-formed (invalid token): line 34"), and the note still
named `pom.xml` among the files whose on-disk state matched its last write.
"""

import json
import unittest

from cria import focustrim


BIG = focustrim._STUB_MIN_CHARS + 50
DENIED = "⟦ctx:denied⟧ write_file REFUSED (not written): this would replace a currently-valid pom.xml"


def write(i, path, ch, result=None):
    return [{"role": "assistant", "content": None,
             "tool_calls": [{"id": f"w{i}", "type": "function", "function": {
                 "name": "write_file", "arguments": json.dumps({"path": path, "content": ch * BIG})}}]},
            {"role": "tool", "tool_call_id": f"w{i}", "content": result or f"Wrote {path}"}]


def note_of(msgs):
    out, _ = focustrim._drop_superseded_writes(msgs)
    notes = [m["content"] for m in out
             if m.get("role") == "user" and "⟦ctx:facts⟧" in str(m.get("content") or "")]
    return notes[0] if notes else ""


class TheNoteNamesOnlyWhatItRemovedTests(unittest.TestCase):
    def test_a_file_written_once_is_not_named(self):
        note = note_of(write(1, "Importer.java", "x") + write(2, "REVIEW.md", "r")
                       + write(3, "Importer.java", "y"))
        self.assertIn("1 earlier write(s)", note)
        self.assertIn("Importer.java", note)
        self.assertNotIn("REVIEW.md", note,
                         "REVIEW.md was written once — nothing about it was removed")

    def test_the_count_and_the_path_list_agree(self):
        note = note_of(write(1, "a.py", "x") + write(2, "a.py", "y") + write(3, "a.py", "z"))
        self.assertIn("2 earlier write(s)", note)
        self.assertEqual(note.count("a.py"), 1)

    def test_every_path_named_really_lost_a_copy(self):
        msgs = (write(1, "a.py", "x") + write(2, "b.py", "b") + write(3, "a.py", "y")
                + write(4, "c.py", "c") + write(5, "b.py", "q"))
        note = note_of(msgs)
        self.assertIn("a.py", note)
        self.assertIn("b.py", note)
        self.assertNotIn("c.py", note)


class ARefusedWriteIsNotTheNewestVersionTests(unittest.TestCase):
    def test_a_refused_write_does_not_supersede_the_real_one(self):
        msgs = write(1, "pom.xml", "x") + write(2, "pom.xml", "y", result=DENIED)
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 0, "the landed write must survive a later refusal")
        self.assertIn("x" * 40, json.dumps(out),
                      "the content that is actually on disk is still in the history")

    def test_a_refused_write_is_never_named_in_the_note(self):
        msgs = (write(1, "Importer.java", "x") + write(2, "Importer.java", "y")
                + write(3, "pom.xml", "p", result=DENIED))
        note = note_of(msgs)
        self.assertIn("Importer.java", note)
        self.assertNotIn("pom.xml", note,
                         "nothing was written to pom.xml, so the on-disk claim cannot cover it")

    def test_a_landed_write_after_a_refusal_still_supersedes(self):
        """The guard must not swallow the real case it sits next to."""
        msgs = (write(1, "a.py", "x") + write(2, "a.py", "y", result=DENIED)
                + write(3, "a.py", "z"))
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 1)
        self.assertIn("z" * 40, json.dumps(out))
        self.assertNotIn("x" * 40, json.dumps(out))


if __name__ == "__main__":
    unittest.main()
