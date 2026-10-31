"""A coloured build log is TEXT. cria threw every Maven error away because it was coloured.

`looks_binary` counted any character below 32 outside tab/newline/CR. The terminal escape byte is
0x1b. Maven — like cargo, gradle, npm and pytest — colours its output, so `mvn compile -q` on a
broken project emits 713 bytes whose ONLY control character is 0x1b, 22 of them at 3.1% density,
clearing both of the detector's thresholds. The model was handed:

    [binary content: 3,295 bytes — not shown; binary data cannot be read as text]

in place of the compiler telling it exactly what was wrong. Measured across the six-language
battery: 212 of qwen35's 275 Java prompts and 86 of gemma4's 112. Both models ended their Java runs
with code that does not compile, unable to see a single error. It fired in the baseline arm too, so
it does not explain the assisted arm's Java loss — it is simply a bug, in the one language family
that cannot proceed without reading its compiler.
"""

import pathlib
import unittest

from cria import content_reduce
from cria.writeproxy import _debinarized


FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# Captured verbatim from `mvn` on the archived qwen35 Java workspace, colour codes and all. Kept as
# files rather than string literals so nobody "tidies" the escape bytes out of the reproduction.
#   maven_no_pom.ansi        645 bytes, 22 escapes, 3.4% — the real bytes cria discarded
#   maven_compile_error.ansi 505 bytes, 20 escapes, 4.0% — the same shape, carrying a real javac error
NO_POM = (FIXTURES / "maven_no_pom.ansi").read_text()
COMPILE_ERROR = (FIXTURES / "maven_compile_error.ansi").read_text()


class AColouredBuildLogIsNotBinaryTests(unittest.TestCase):
    def test_the_fixtures_actually_reproduce_the_bug(self):
        """Both thresholds must genuinely be cleared, or these tests prove nothing."""
        for name, log in (("no_pom", NO_POM), ("compile_error", COMPILE_ERROR)):
            with self.subTest(fixture=name):
                sample = log[:8192]
                bad = sum(1 for c in sample if ord(c) < 32 and c not in "\t\n\r")
                self.assertGreaterEqual(bad, 20, "fewer than 20 control chars — would never have tripped")
                self.assertGreater(bad / len(sample), 0.02, "under the density threshold")

    def test_maven_errors_are_text(self):
        self.assertFalse(content_reduce.looks_binary(NO_POM))
        self.assertFalse(content_reduce.looks_binary(COMPILE_ERROR))

    def test_the_escape_byte_was_the_only_thing_making_it_look_binary(self):
        """Proves the diagnosis rather than the symptom: nothing else in the log is a control char."""
        ctrl = {c for c in NO_POM + COMPILE_ERROR if ord(c) < 32 and c not in "\t\n\r"}
        self.assertEqual(ctrl, {"\x1b"})

    def test_the_model_is_shown_the_compiler_error_not_a_placeholder(self):
        out = _debinarized(COMPILE_ERROR)
        self.assertNotIn("binary content", out)
        self.assertIn("cannot be applied to given types", out)
        self.assertIn("Importer.java:[88,31]", out)

    def test_the_escapes_are_stripped_rather_than_forwarded(self):
        """A model can act on the words; the escape bytes are noise it pays tokens for."""
        out = _debinarized(COMPILE_ERROR)
        self.assertNotIn("\x1b", out)
        self.assertIn("[ERROR] COMPILATION ERROR", out)

    def test_other_tools_that_colour_by_default(self):
        for name, log in [
            ("cargo", "\x1b[1m\x1b[31merror[E0599]\x1b[0m: no method named `get_str`\n" * 4),
            ("pytest", "\x1b[31mFAILED\x1b[0m tests/test_api.py::test_orders - AssertionError\n" * 4),
            ("npm", "\x1b[91mnpm ERR!\x1b[0m code ELIFECYCLE\n" * 8),
        ]:
            with self.subTest(tool=name):
                self.assertFalse(content_reduce.looks_binary(log))
                self.assertNotIn("binary content", _debinarized(log))


class RealBinaryIsStillRefusedTests(unittest.TestCase):
    """The strip must not open the door the operator ruling closed."""

    def test_a_png_is_still_replaced_by_a_fact_line(self):
        blob = "\x89PNG\r\n\x1a\n" + "".join(chr(i % 32) for i in range(4000))
        self.assertTrue(content_reduce.looks_binary(blob))
        self.assertIn("binary content", _debinarized(blob))

    def test_replacement_characters_are_still_binary(self):
        self.assertTrue(content_reduce.looks_binary("�" * 100))

    def test_text_that_was_already_text_stays_text(self):
        self.assertFalse(content_reduce.looks_binary("完全なユニコードテキスト。" * 200))
        self.assertFalse(content_reduce.looks_binary("00000000  7f 45 4c 46  |.ELF|\n" * 50))

    def test_a_blob_wearing_colour_codes_is_still_a_blob(self):
        """Stripping the escapes must not let real binary through with them sprinkled in."""
        blob = "\x1b[31m" + "".join(chr(i % 31) for i in range(4000)) + "\x1b[0m"
        self.assertTrue(content_reduce.looks_binary(blob))


class StripAnsiTests(unittest.TestCase):
    def test_it_leaves_ordinary_text_untouched(self):
        for s in ("", "plain text", "a[1] = b[2]", "printf '%s\\n'", "\\x1b is a literal backslash"):
            self.assertEqual(content_reduce.strip_ansi(s), s)

    def test_it_removes_colour_cursor_and_osc_sequences(self):
        self.assertEqual(content_reduce.strip_ansi("\x1b[1;31mred\x1b[0m"), "red")
        self.assertEqual(content_reduce.strip_ansi("a\x1b[2Kb\x1b[1Gc"), "abc")
        self.assertEqual(content_reduce.strip_ansi("\x1b]0;title\x07done"), "done")


if __name__ == "__main__":
    unittest.main()
