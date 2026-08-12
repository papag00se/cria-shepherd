"""cria pointed the coder at the line where the program STOPPED, not the line that was wrong.

Every `path:LINE` finding got "the flagged line on disk — line N: `...`" appended, under a header
ordering the coder to "resolve exactly what it names". That is correct for a LINTER, where the
flagged line IS the defect. For a runtime exception it is the raise site: the assertion that failed,
the line that dereferenced the nil. The cause is upstream, in the value that reached it.

Measured on the six-language battery: the coder rewrote the assertion line repeatedly while the bad
value came from a default argument three functions away. cria cannot justify the pointer, so it does
not make it — silence over noise (#3), and no claim it cannot support (#5b).

Matched on the shapes runtimes actually print, not on one language's phrasing.
"""
import unittest

from cria.probegate import _EXCEPTION_FINDING as E


class ExceptionsAreTheOnesWeDoNotAnnotateTests(unittest.TestCase):
    EXCEPTIONS = ("tests/test_db.py:12: AssertionError: 42.5 != 17.5",
                  "cart.go:22: panic: runtime error: index out of range",
                  "Importer.java:31: java.lang.NullPointerException",
                  "lib/rates.rb:4: NoMethodError: undefined method",
                  "src/main.rs:9: thread 'main' panicked at 'boom'",
                  "Traceback (most recent call last):")
    LINTS = ("app.py:3: undefined name 'x'",
             "src/main.rs:9: unused variable: `y`",
             "lib.rb:8: warning: assigned but unused variable",
             "cart.go:6: \"log\" imported and not used")

    def test_a_runtime_failure_is_recognised_in_every_language(self):
        for f in self.EXCEPTIONS:
            with self.subTest(f=f[:40]):
                self.assertTrue(E.search(f))

    def test_a_linter_finding_is_not(self):
        """The annotation stays where it is right — the lint case is why it exists."""
        for f in self.LINTS:
            with self.subTest(f=f[:40]):
                self.assertFalse(E.search(f))


if __name__ == "__main__":
    unittest.main()
