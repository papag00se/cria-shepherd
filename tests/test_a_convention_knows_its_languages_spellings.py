"""Three languages wrote their tests the ordinary way and cria said they had none.

A `TestConvention.marker` decides two sentences: *"No <runner> tests were found — to be run they
must be <label>"* and *"Test code in <file> will not run"*. A marker that misses a language's normal
spelling makes cria assert the first one over a file full of tests.

    php    `extends\\s+TestCase\\b`   missed `extends \\PHPUnit\\Framework\\TestCase`, the form a
                                    file with no `use` line writes, and PHPUnit 10's `#[Test]`
                                    attribute, which marks a test without naming it.
    java   `^\\s*@Test\\b`            missed `@ParameterizedTest` and `@RepeatedTest` — JUnit 5's
                                    other two test annotations. A class using only those held
                                    tests and read as holding none.
    js     `^\\s*describe\\s*\\(`       missed `node:test`, which writes `test('name', ...)` with no
                                    `describe` — and `node --test` is the runner CRIA ITSELF
                                    composes for a bare node project. A `tests/resolver.js`
                                    written that way was neither discoverable NOR stranded, so
                                    cria said nothing about it at all.

The same file records why this matters, from the Ruby row: "A convention table that knows one
framework per language states a falsehood in every project using the other one." That was rspec vs
minitest; these are the same shape.
"""

import re
import unittest

from cria import probediscovery


def _marker(ext):
    return next(c for c in probediscovery.TEST_CONVENTIONS if ext in c.exts).marker


def _holds_tests(ext, body):
    return bool(re.search(_marker(ext), body, re.M))


class PhpWritesItsBaseClassTwoWaysTests(unittest.TestCase):
    def test_the_short_form_still_matches(self):
        self.assertTrue(_holds_tests("php", "class ImporterTest extends TestCase {}"))

    def test_the_fully_qualified_form_matches(self):
        self.assertTrue(_holds_tests("php", r"class T extends \PHPUnit\Framework\TestCase {}"))

    def test_the_attribute_form_matches(self):
        self.assertTrue(_holds_tests("php", "  #[Test]\n  public function itAdds() {}"))

    def test_ordinary_php_does_not(self):
        self.assertFalse(_holds_tests("php", "class Resolver {\n  public function run() {}\n}"))


class JunitHasThreeTestAnnotationsTests(unittest.TestCase):
    def test_every_one_of_them_counts(self):
        for ann in ("@Test", "@ParameterizedTest", "@RepeatedTest(3)"):
            with self.subTest(annotation=ann):
                self.assertTrue(_holds_tests("java", f"  {ann}\n  void adds() {{}}"))

    def test_ordinary_java_does_not(self):
        self.assertFalse(_holds_tests("java", "  void helper() {}\n  int total;"))


class NodesOwnRunnerNeedsNoDescribeTests(unittest.TestCase):
    def test_a_bare_test_call_counts(self):
        self.assertTrue(_holds_tests("js", "test('resolves a handle', () => {})"))

    def test_it_counts_the_bdd_spellings_too(self):
        for body in ("describe('x', () => {})", "it('adds', () => {})"):
            with self.subTest(body=body):
                self.assertTrue(_holds_tests("js", body))

    def test_ordinary_js_does_not(self):
        self.assertFalse(_holds_tests("js", "export function resolve(h) { return h; }"))

    def test_the_runner_cria_composes_is_the_one_that_was_missed(self):
        """`node --test` is what cria seeds for a bare node project, and `node:test` is its API."""
        conv = next(c for c in probediscovery.TEST_CONVENTIONS if "js" in c.exts)
        self.assertIn("jest", conv.runner)
        self.assertTrue(_holds_tests("js", "import test from 'node:test'\ntest('a', () => {})"))


if __name__ == "__main__":
    unittest.main()
