"""A file the coder wrote by relative path and by absolute path is ONE file to the fold.

`_drop_superseded_writes` removes every write to a path except the newest, because only the newest
is what is on disk. It keyed on the path STRING the tool call carried, and a coder is free to spell
the same file either way — the tool resolves both against its own cwd and they land on the same
inode.

Walked on `feed-pipeline-java x nemotron-elastic` 20260820T103857. The coder wrote `Importer.java`
seven times by absolute path and once, at call 0043, as `src/main/java/pipeline/Importer.java`. Two
spellings, two dict keys, so neither run of writes ever superseded the other: the single largest
payload in the session went unfolded, and cria's own note listed the same file twice in one sentence
— which reads as two different files that both changed (#5b).

cria cannot resolve the relative spelling by path: the working directory belongs to the HARNESS, so
`abspath` here would anchor to cria's own cwd and name a file that does not exist. It is resolved by
SHAPE instead — a component-wise suffix match against the absolute paths the same session wrote —
and an ambiguous suffix does not fold at all, because the cost of folding wrongly is deleting a
file's only copy while the cost of not folding is a duplicate the model can still read.
"""

import json
import unittest

from cria import focustrim


BIG = focustrim._STUB_MIN_CHARS + 50
ABS = "/w/repo/src/main/java/pipeline/Importer.java"
REL = "src/main/java/pipeline/Importer.java"


def write(i, path, ch):
    return [{"role": "assistant", "tool_calls": [{"id": f"w{i}", "type": "function", "function": {
                "name": "write_file", "arguments": json.dumps({"path": path, "content": ch * BIG})}}]},
            {"role": "tool", "tool_call_id": f"w{i}", "content": f"Wrote {path}"}]


def note_of(msgs):
    return next((m["content"] for m in msgs if m.get("role") == "user"), "")


class TheTwoSpellingsFoldTests(unittest.TestCase):
    def test_a_relative_write_is_superseded_by_a_later_absolute_write(self):
        msgs = write(0, ABS, "a") + write(1, REL, "b") + write(2, ABS, "c")
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 2)                  # was 0 for the relative one
        bodies = json.dumps(out)
        self.assertIn("c" * 40, bodies)               # the newest survives whole
        self.assertNotIn("b" * 40, bodies)

    def test_the_note_names_the_file_once_not_once_per_spelling(self):
        msgs = write(0, ABS, "a") + write(1, REL, "b") + write(2, ABS, "c")
        out, _ = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(note_of(out).count("Importer.java"), 1)

    def test_the_absolute_spelling_is_the_one_reported(self):
        # The relative form is meaningless without the harness's cwd; the note must not print it.
        msgs = write(0, REL, "a") + write(1, ABS, "b")
        out, _ = focustrim._drop_superseded_writes(msgs)
        self.assertIn(ABS, note_of(out))


class AmbiguityIsLeftAloneTests(unittest.TestCase):
    def test_a_suffix_matching_two_absolute_paths_does_not_fold(self):
        # `a/x.java` sits under both roots. Folding would drop a real file's only copy.
        one, two, rel = "/w/one/a/x.java", "/w/two/a/x.java", "a/x.java"
        msgs = write(0, one, "a") + write(1, two, "b") + write(2, rel, "c")
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 0)
        self.assertIn("c" * 40, json.dumps(out))

    def test_two_genuinely_different_files_never_fold(self):
        msgs = write(0, "/w/a/x.java", "a") + write(1, "/w/b/y.java", "b")
        _out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 0)


class TheOldBehaviourIsUnchangedTests(unittest.TestCase):
    def test_repeated_absolute_writes_still_fold(self):
        msgs = write(0, ABS, "a") + write(1, ABS, "b") + write(2, ABS, "c")
        _out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 2)

    def test_a_single_write_is_untouched(self):
        msgs = write(0, ABS, "a")
        out, dropped = focustrim._drop_superseded_writes(msgs)
        self.assertEqual(dropped, 0)
        self.assertIs(out, msgs)


if __name__ == "__main__":
    unittest.main()
