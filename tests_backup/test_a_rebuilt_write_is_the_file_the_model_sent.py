"""The last-resort rebuild of a `write_file` call put the rest of the JSON object into the file.

`_recover_write_args` is what runs when a write's `content` has raw newlines or unescaped quotes and
`json.loads` refuses it. It found the end of the content value with `tail.rfind('"')` — the LAST
quote in the whole remainder — under a comment resting on the object being structurally complete.

Completeness says nothing about key ORDER, and models emit keys alphabetically, so `content` comes
before `path` far more often than after it:

    sent      {"content":"line1\\nline2","path":"x.py"}
    recovered content = 'line1\\nline2","path":"x.py'

A byte-exact write of that is a broken file that reports success.

The second defect is in the same four lines. The escapes were undone by chained `.replace()` calls
with `\\\\` LAST, so a literal backslash followed by `n` — a Windows path, a regex inside a file — had
its `\\n` turned into a real newline by an earlier pass, and the backslash that would have protected
it was collapsed afterwards.

Neither is observed firing: the structural-completeness gate above refuses first in all fourteen
reachable cases in this machine's captures. This is the last-resort path for a large `write_file`,
which is why it is worth being right.
"""

import unittest

from cria import massage


class TheContentValueEndsWhereTheModelEndedItTests(unittest.TestCase):
    def test_content_before_path_the_common_order(self):
        got = massage._recover_write_args('{"content":"line1\nline2","path":"x.py"}')
        self.assertEqual(got, {"path": "x.py", "content": "line1\nline2"})

    def test_content_after_path_still_works(self):
        got = massage._recover_write_args('{"path":"x.py","content":"line1\nline2"}')
        self.assertEqual(got, {"path": "x.py", "content": "line1\nline2"})

    def test_escaped_quotes_inside_the_content_do_not_end_it(self):
        got = massage._recover_write_args('{"content":"say \\"hi\\"\nbye","path":"a.txt"}')
        self.assertEqual(got["content"], 'say "hi"\nbye')

    def test_a_content_value_that_never_closes_is_refused(self):
        """A cut-off write must not be salvaged into a partial file — the rule this function already
        held, and the forward scan keeps it."""
        self.assertIsNone(massage._content_value_end('{"content":"unterminated', 12))


class EscapesAreUndoneInOnePassTests(unittest.TestCase):
    def test_a_literal_backslash_before_n_survives(self):
        got = massage._recover_write_args('{"content":"C:\\\\newfile","path":"x.py"}')
        self.assertEqual(got["content"], "C:\\newfile")
        self.assertNotIn("\n", got["content"], "the file gained a newline that was never in it")

    def test_a_regex_inside_a_file_survives(self):
        got = massage._recover_write_args('{"content":"re.split(r\'\\\\n\', s)","path":"a.py"}')
        self.assertIn("\\n", got["content"])
        self.assertEqual(got["content"].count("\n"), 0)

    def test_the_real_escapes_are_still_decoded(self):
        got = massage._recover_write_args('{"content":"a\\nb\\tc","path":"a"}')
        self.assertEqual(got["content"], "a\nb\tc")

    def test_a_decoded_character_is_never_re_read(self):
        """One left-to-right pass. `\\\\n` is a backslash then an `n`, never a newline."""
        self.assertEqual(massage._unescape_once("x\\\\ny"), "x\\ny")
        self.assertEqual(massage._unescape_once("x\\ny"), "x\ny")
        self.assertEqual(massage._unescape_once("\\\\\\\\"), "\\\\")


if __name__ == "__main__":
    unittest.main()
