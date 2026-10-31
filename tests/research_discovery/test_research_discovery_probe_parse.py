"""Checker output reaches the coder located and in the checker's own words (probeparse)."""
import pytest

from cria import probeparse
from cria.probeparse import parse_output

PYTEST_HINT = ("HINT: remove __pycache__ / .pyc files and/or use a unique basename for your test file modules\n")
MINITEST = ("Finished in 0.011386s, 614.8036 runs/s, 614.8036 assertions/s.\n\n  1) Failure:\n"
            "TestRates#test_oversize_surcharge [/w/test/test_rates.rb:23]:\nExpected: 12.0\n  Actual: 0.0\n\n"
            "7 runs, 7 assertions, 1 failures, 0 errors, 0 skips\n")
MINITEST_ERR = ("Finished in 0.011s, 636.0 runs/s.\n\n  1) Error:\nTestRates#test_free:\n"
                "NameError: undefined local variable or method `surcharge' for Shipping:Module\n"
                "    /w/lib/shipping/rates.rb:19:in `shipping_cost'\n    /w/test/test_rates.rb:15:in `t'\n\n"
                "7 runs, 4 assertions, 0 failures, 3 errors, 0 skips\n")
NODE_TAP = ("not ok 1 - adds\n  ---\n  location: '/w/lib/cart.test.js:12:3'\n  failureType: 'testCodeFailure'\n  error: |-\n"
            "    Expected values to be strictly equal:\n    5 !== 6\n  code: 'ERR_ASSERTION'\n  ...\n# fail 1\n")
JUNIT = ("[ERROR] adds(pipeline.ImporterTest)  <<< FAILURE!\njava.lang.AssertionError: expected:<2> but was:<3>\n"
         "\tat org.junit.Assert.fail(Assert.java:88)\n\tat org.junit.Assert.failNotEquals(Assert.java:834)\n"
         "\tat pipeline.ImporterTest.adds(ImporterTest.java:14)\n")
MVN = ("[ERROR] COMPILATION ERROR : \n[ERROR] /w/src/Importer.java:[5,19] cannot find symbol\n"
       "  symbol:   class CSVRecord\n[ERROR] -> [Help 1]\n"
       "[ERROR] [Help 1] http://cwiki.apache.org/confluence/display/MAVEN/MojoFailureException\n")
CARGO = ("---- tests::it_adds stdout ----\n\nthread 'tests::it_adds' (7) panicked at src/lib.rs:7:20:\n"
         "assertion `left == right` failed\n  left: 4\n right: 5\n")
COLLECT = ("________________ ERROR collecting smoke_test.py ________________\n"
           "smoke_test.py:2: in <module>\n    from .x import y\n"
           "E   ImportError: attempted relative import with no known parent package\n"
           "ERROR smoke_test.py\n")
MISMATCH = ("________________ ERROR collecting tests/test_dup.py ________________\n"
            "import file mismatch:\n" + PYTEST_HINT + "ERROR tests/test_dup.py\n")

@pytest.mark.parametrize("cmd,family,code,out,loc,words,summary", [
    ("cargo check", "cargo", 101, "error[E0063]: missing field `x`\n  --> src/p.rs:42:5\n", ("src/p.rs", 42, None), "missing field", None),
    ("tsc", "tsc", 2, "src/app.ts(12,7): error TS2322: Type 'string' is not assignable", ("src/app.ts", 12, 7), "not assignable", None),
    ("eslint .", "eslint", 1, "/r/index.js\n  10:5  error  'x' is not defined  no-undef\n", ("/r/index.js", 10, 5), "not defined", None),
    ("pytest", "pytest", 2, COLLECT, ("smoke_test.py", 2, None), "attempted relative import",
     "smoke_test.py:2: ImportError: attempted relative import with no known parent package"),
    # live run 0726-145040: a collection error with no frame and no E-rows read "test failed" for ~700 calls
    ("pytest", "pytest", 2, MISMATCH, ("tests/test_dup.py", None, None), "unique basename", None),
    ("pytest", "pytest", 4, "ImportError while loading conftest\nconftest.py:1: in <module>\n    import nosuch\n"
     "E   ModuleNotFoundError: No module named 'nosuch'\n", ("conftest.py", 1, None), "ModuleNotFoundError", None),
    ("pytest", "pytest", 1, "____ test_d ____\nE       AssertionError: assert {'x': 1} == {'x': 2}\nE         Differing items:\n"
     "E         {'x': 1} != {'x': 2}\ntest_d.py:9: AssertionError\n", ("test_d.py", 9, None), "{'x': 1} != {'x': 2}", None),
    ("python3 -c <toml-check> /x/pyproject.toml", "generic", 1, "/x/pyproject.toml: Invalid value (at line 2, column 12)",
     ("/x/pyproject.toml", 2, 12), "Invalid value", "/x/pyproject.toml:2: Invalid value (at line 2, column 12)"),
    ("cargo test", "cargo", 101, CARGO, ("src/lib.rs", 7, None), "assertion", None),
    ("rspec", "", 1, "Failures:\n  1) adder adds\n     Failure/Error: expect(2).to eq(5)\n     # ./a_spec.rb:3:in `block'\n",
     ("./a_spec.rb", 3, None), "", None),
    ("phpunit", "", 1, "1) AppTest::testAdd\nFailed asserting that 4 is identical to 5.\n\n/w/tests/AppTest.php:14\n\nFAILURES!\n",
     ("/w/tests/AppTest.php", 14, None), "Failed asserting", None),
    # feed-pipeline-java run 20260820: every line tagged `[ERROR] ` hid the location; summary quoted the Help URL
    ("mvn -q compile", "maven", 1, MVN, ("/w/src/Importer.java", 5, 19), "cannot find symbol", "Importer.java:5"),
    # shipping-rates-rb: the timing banner (contains "assertions") beat `Expected:` as the failure message
    ("rake test", "", 1, MINITEST, ("/w/test/test_rates.rb", 23, None), "Expected: 12.0",
     "/w/test/test_rates.rb:23: Expected: 12.0 / Actual: 0.0"),
    # node --test: TAP-YAML location, and the assertion rather than `failureType: 'testCodeFailure'`; JUnit: the test's own frame, not Assert.java
    ("node --test", "", 1, NODE_TAP, ("/w/lib/cart.test.js", 12, None), "strictly equal", None),
    ("mvn -q test", "", 1, JUNIT, ("ImporterTest.java", 14, None), "expected:<2> but was:<3>", None),
    ("rake test", "", 1, MINITEST_ERR, ("/w/lib/shipping/rates.rb", 19, None), "NameError", None),
])
def test_first_finding_is_located_and_quotes_the_checker(cmd, family, code, out, loc, words, summary):
    """The first finding carries file/line/col and the checker's own message; the summary quotes it."""
    r = parse_output(cmd, family, code, out, "")
    f = r.findings[0]
    assert (f.file, f.line) == loc[:2] and (loc[2] is None or f.col == loc[2])
    assert words in f.message
    if summary:
        assert summary in r.summary
    assert "Help 1" not in r.summary and "runs/s" not in r.summary and "1) Error" not in r.summary

def test_collection_error_is_not_hidden_by_an_ordinary_failure():
    """`if out: return out` ran before the collect path, so one failure hid an uncollectable file."""
    out = ("____ test_adds ____\ntests/test_math.py:4: in test_adds\n    assert add(1,1) == 3\nE   assert 2 == 3\n"
           + MISMATCH + "FAILED tests/test_math.py::test_adds - assert 2 == 3\n")
    files = {f.file for f in parse_output("pytest", "pytest", 1, out, "").findings}
    assert {"tests/test_math.py", "tests/test_dup.py"} <= files

def test_diagnostic_detail_is_whole_and_ends_at_the_next_diagnostic():
    """javac's symbol/location lines follow a candidate list; a count cap cut them (structure ends it)."""
    body = "A.java:4: error: cannot find symbol\n  symbol:   class CSVRecord\n" + "".join(
        f"  note: candidate {i}\n" for i in range(8)) + "  location: package com.opencsv\nA.java:9: error: second\n"
    first, second = probeparse.parse_generic(body)
    assert "symbol:   class CSVRecord" in first.message and "location: package com.opencsv" in first.message
    assert "second" not in first.message and second.line == 9
    trace = "app.py:10: error: boom\n  its detail\n  frame.py:22: in inner\n  more.py:33: in outer\n"
    msg = probeparse.parse_generic(trace)[0].message
    assert "its detail" in msg and "more.py:33" not in msg

@pytest.mark.parametrize("cmd,out,kept", [
    ("ruff check .", "a.py:3:1: E501 long\na.py:4:1: W291 ws\na.py:5:1: C0114 doc\na.py:6:1: F401 `os` imported but unused\n"
     "a.py:7:1: F821 undefined name `foo`\na.py:9:1: E999 SyntaxError: bad\n", ["F821 undefined name `foo`", "E999 SyntaxError: bad"]),
    # pyflakes' bare "imported but unused" buried a genuine "undefined name"
    ("python3 -m pyflakes .", "t.py:1:1: 'json' imported but unused\nt.py:5:5: redefinition of unused 'json' from line 1\n"
     "t.py:7:18: undefined name 'resolver'\n", ["undefined name 'resolver'"]),
    ("eslint .", "/w/a.js\n  10:5  warning  Unexpected console  no-console\n  3:7  error  'x' is defined but never used  no-unused-vars\n"
     "  12:1  error  'y' is not defined  no-undef\n", ["'y' is not defined no-undef"]),
    ("tsc --noEmit", "src/a.ts(3,7): error TS6133: 'x' is declared but its value is never read.\n", []),
    ("make", "main.c:4:2: warning: unused variable\nmain.c:9:2: error: expected ';'\n", ["error: expected ';'"]),
    # Go's unused import is a hard compile error, not a lint advisory
    ("go build ./...", './main.go:5:2: "fmt" imported and not used\n', ['"fmt" imported and not used']),
    ("mypy .", "a.py:1: note: See docs\na.py:7: error: bad return\n", ["error: bad return"]),
])
def test_only_error_class_findings_gate(cmd, out, kept):
    """Advisories (style, unused, warnings, notes) never reach the coder as a failing check."""
    family = probeparse.family_of(cmd.split())
    assert [f.message for f in parse_output(cmd, family, 1, out, "").findings] == kept

def test_redefinition_gates_only_when_the_flagged_line_is_a_def():
    """maple-preview run: two `def resolve_handle` shadowed the network resolver; an import rebinding is advisory."""
    out = "x.py:148:1: redefinition of unused 'resolve_handle' from line 27\n"
    run = lambda line: parse_output("pyflakes x.py", "", 1, out, "",
                                    read_source_line=(lambda p, n: line) if line else None).findings
    assert len(run("    def resolve_handle(h):")) == 1 and len(run("class ResolveHandle:")) == 1
    assert run("import json") == [] and run(None) == []

def test_a_command_that_exited_zero_has_no_failures_but_unknown_exit_still_scrapes():
    """A passing pytest run with a warning once produced 'the repo's own checks fail' 40 times."""
    warn = ("collected 1 item\ntest_x.py .  [100%]\n=== warnings summary ===\ntest_x.py:95\n"
            "  /w/test_x.py:95: PytestUnknownMarkWarning: Unknown pytest.mark.live - typo?\n=== 1 passed, 1 warning ===\n")
    assert parse_output("pytest", "pytest", 0, warn, "").findings == []
    assert parse_output("pytest", "pytest", 1, warn, "").findings
    assert parse_output("tool", "", None, "src/a.py:3: SyntaxError: bad\n", "").findings

def test_nothing_is_invented_when_the_checker_printed_no_location():
    """Maven's console has no location (it is in surefire-reports); the Help footer is not one; clean says clean."""
    assert probeparse.parse_generic("Failed tests:   testAdd(app.AdderTest): expected:<5> but was:<4>\n"
                                    "Tests run: 1, Failures: 1, Errors: 0, Skipped: 0\n") == []
    assert probeparse.parse_generic("[ERROR] [Help 1] http://cwiki.apache.org/x/MojoFailureException") == []
    clean = parse_output("cargo check", "cargo", 0, "    Finished dev\n", "")
    assert (clean.findings, clean.summary) == ([], "no problems reported")
    r = parse_output("make check", "", 2, "building...\nfatal: something broke\n", "")
    assert (r.findings, r.summary) == ([], "exited 2: fatal: something broke")
    prefer = parse_output("rake test", "", 1, "NoMethodError: undefined method `zone_for'\n\n"
                          "7 runs, 4 assertions, 0 failures, 3 errors, 0 skips\n", "")
    assert "NoMethodError" in prefer.summary and "7 runs" not in prefer.summary

