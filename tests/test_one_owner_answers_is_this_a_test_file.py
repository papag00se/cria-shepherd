"""Two functions answered "is this a test file", and the private one was narrower.

`probediscovery.TEST_CONVENTIONS` is the table that knows every language's test-file shapes, and
`loop._looks_like_a_test_path` read it. `execcheck` kept its own regex instead:

    _TEST_NAME = re.compile(r"(^test[_.]|[_.]test\\.|_test$|(?:^|[_.])spec[_.]|Test\\.|Tests\\.)")

in which `Test` and `Tests` must END the stem. So JUnit's PREFIX convention `TestImporter.java`,
its `*TestCase.java` form, and jest's `__tests__/` directory all read as ORDINARY SOURCE there —
while the table three modules away already listed all three by name.

What that decides in execcheck: whether a workspace has a program at all. A test file routinely
carries its own runner block, so counting one meant a project whose only entry point sat inside a
test read as "this project has a program", and the completion judge was told so. Measured on
mellum2 attempt 3, whose deliverable ends on a function definition and prints nothing.

The private regex had exactly one behaviour worth keeping, and it came the other way round:
`conftest.py` matched `^test[_.]`… no it did not — it matched nothing of the sort, it matched
because pytest scaffolding is not a test and the convention globs correctly do not claim it. That
divergence is now resolved in the table's favour: conftest.py is not a test file.

#23: one owner. `feedback_matchers_by_shape`: a rule keyed to one language's spelling is inert on
every other, and this one was.
"""

import unittest

from cria import execcheck, loop, probediscovery

WAS_MISSED = [
    "TestImporter.java",                          # JUnit prefix convention
    "src/main/java/pipeline/TestImporter.java",
    "ImporterTestCase.java",                      # *TestCase.java, surefire default
    "__tests__/lookup.js",                        # jest directory convention
]

ALWAYS_MATCHED = [
    "ImporterTest.java", "SomeTests.java", "cart_test.go", "tests/test_db.py",
    "test_x.rb", "x_spec.rb", "lookup.test.js", "lookup.spec.ts", "spec/rates_spec.rb",
]

NOT_TESTS = ["orders/db.py", "lib/handler.rb", "src/main.rs", "Rakefile", "go.mod",
             "conftest.py"]


class TheTableAnswersForEveryoneTests(unittest.TestCase):
    def test_the_shapes_execchecks_regex_missed(self):
        for p in WAS_MISSED:
            with self.subTest(path=p):
                self.assertTrue(probediscovery.looks_like_a_test_path(p))
                self.assertTrue(execcheck._is_test_file(p))

    def test_what_already_worked_still_does(self):
        for p in ALWAYS_MATCHED:
            with self.subTest(path=p):
                self.assertTrue(execcheck._is_test_file(p))

    def test_ordinary_source_is_not_a_test(self):
        for p in NOT_TESTS:
            with self.subTest(path=p):
                self.assertFalse(execcheck._is_test_file(p))

    def test_conftest_is_scaffolding_not_a_test(self):
        """The one place the old private regex differed in the other direction. pytest's conftest.py
        collects no tests, and no convention glob claims it."""
        self.assertFalse(probediscovery.looks_like_a_test_path("conftest.py"))

    def test_both_callers_agree_by_construction(self):
        for p in WAS_MISSED + ALWAYS_MATCHED + NOT_TESTS:
            with self.subTest(path=p):
                self.assertEqual(execcheck._is_test_file(p), loop._looks_like_a_test_path(p))

    def test_windows_separators_are_handled(self):
        self.assertTrue(probediscovery.looks_like_a_test_path(r"src\\test\\java\\Foo.java"))


class ThereIsOnlyOneOfThemTests(unittest.TestCase):
    def test_execcheck_holds_no_private_regex(self):
        """Structural: the retired `_TEST_NAME` regex must not come back as a second owner. A
        namespace check rather than a source-text search — it survives a rename or reorganisation
        of the module, and can't be fooled by the name surviving in a comment."""
        self.assertFalse(hasattr(execcheck, "_TEST_NAME"))

    def test_loop_delegates_to_the_real_table(self):
        """Behavioural: a local re-implementation would get the JUnit/jest shapes wrong, exactly
        as execcheck's old private regex did — WAS_MISSED is precisely the set that only the
        table's convention list classifies correctly."""
        for p in WAS_MISSED:
            with self.subTest(path=p):
                self.assertTrue(loop._looks_like_a_test_path(p))
        for p in NOT_TESTS:
            with self.subTest(path=p):
                self.assertFalse(loop._looks_like_a_test_path(p))

    def test_loop_holds_no_second_copy_of_the_table(self):
        """Structural: the convention table has one owner (probediscovery.TEST_CONVENTIONS). A
        namespace check beats a source-text search for the same reason as above."""
        self.assertFalse(hasattr(loop, "TEST_CONVENTIONS"))

    def test_every_convention_row_is_reachable_through_it(self):
        """A row added to the table must take effect everywhere without a second edit."""
        for conv in probediscovery.TEST_CONVENTIONS:
            for glob in conv.globs:
                with self.subTest(glob=glob):
                    self.assertTrue(
                        probediscovery.looks_like_a_test_path(glob.replace("*", "Sample")))


if __name__ == "__main__":
    unittest.main()
