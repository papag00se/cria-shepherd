"""A test class defined AFTER `unittest.main()` does not run when the file is run directly.

37 of this repo's test modules had the `if __name__ == "__main__": unittest.main()` guard somewhere
in the middle, with one or more classes below it. Under pytest every class is collected, so the
suite was honest — but the failure mode is the one this session has been chasing all day: a check
that silently does not run, and is indistinguishable from one that runs and passes.

`test_research_check_wiring.py` was the worst of them. Its guard sat two thirds of the way down, and
the two classes below it — the ones covering the reading fact reaching the critic, and evidence
rather than a clock deciding when to look — would simply not have executed for anyone running that
file on its own to check their change.

Nothing about pytest collection changed; what changed is that the two ways of running a file now
agree. This test is the guard, so it cannot drift back.
"""

import pathlib
import re
import unittest

TESTS = pathlib.Path(__file__).parent
GUARD = re.compile(r'^if __name__ == "__main__":\n(?:[ \t]+.*\n)+', re.M)
DEFN = re.compile(r"^(class|def) ", re.M)


class TheGuardIsLastTests(unittest.TestCase):
    def test_no_definition_hides_below_the_main_guard(self):
        for f in sorted(TESTS.glob("test_*.py")):
            src = f.read_text()
            m = GUARD.search(src)
            if not m:
                continue                      # no guard at all is fine — pytest is the runner
            with self.subTest(module=f.name):
                self.assertIsNone(DEFN.search(src[m.end():]),
                                  "a class or function is defined after unittest.main(); running "
                                  "this file directly would skip it")

    def test_there_is_at_most_one_guard_per_file(self):
        for f in sorted(TESTS.glob("test_*.py")):
            with self.subTest(module=f.name):
                self.assertLessEqual(len(GUARD.findall(f.read_text())), 1)

    def test_the_suite_is_not_empty(self):
        """The guard above is vacuous if the glob stops matching."""
        self.assertGreater(len(list(TESTS.glob("test_*.py"))), 100)


if __name__ == "__main__":
    unittest.main()
