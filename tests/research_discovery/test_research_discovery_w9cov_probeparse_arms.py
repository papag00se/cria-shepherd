"""Wave 9 coverage: the checker-output readers' less-travelled arms, each through its real public parser.

rustc `warning:`/`note:` spans (advisory kept advisory), a file-only `-->` span (cargo manifest errors), tsc/eslint
rows that must be skipped or labelled, pytest summary-only and conftest-import shapes, and `summarize` over
findings with no line, no file, or no findings at all (a pointer URL is never the explanation).
"""
import pytest

from cria import probeparse as pp


def pairs(findings): return [(f.file, f.line, f.col, f.message) for f in findings]


def test_rustc_keeps_advisory_words_and_file_only_spans():
    out = ("warning: this `if let` can be collapsed\n --> src/a.rs:3:5\nnote: required by a bound\n --> src/b.rs:9:1\n"
           "error: can't find bin `x` at path `src/main.rs`\n --> Cargo.toml\nerror[E0425]: cannot find value `y`\n --> src/c.rs:1:2\n"
           " --> src/d.rs:4:4\nerrors occurred\n")
    assert pairs(pp.parse_rustc(out)) == [
        ("src/a.rs", 3, 5, "warning: this `if let` can be collapsed"), ("src/b.rs", 9, 1, "note: required by a bound"),
        ("Cargo.toml", None, None, "can't find bin `x` at path `src/main.rs`"), ("src/c.rs", 1, 2, "cannot find value `y`"),
        ("src/d.rs", 4, 4, pp.DEFAULT_RUSTC_MESSAGE)]
    assert all(pp.is_advisory(f.message) for f in pp.parse_rustc(out)[:2]) and not pp.is_advisory("cannot find value `y`")


@pytest.mark.parametrize("text,expected", [
    ("no parens here\nsrc/a.ts(1,2) missing colon\n(1,2): error TS1: no file\nsrc/b.ts(x,y): error TS2: bad nums\n"
     "src/c.ts(3: error TS3: unclosed\nsrc/d.ts(4,5): error TS2322: Type 'a' is not assignable\n",
     [("src/d.ts", 4, 5, "error TS2322: Type 'a' is not assignable")]),
])
def test_tsc_skips_every_malformed_row(text, expected):
    assert pairs(pp.parse_tsc(text)) == expected


def test_eslint_labels_unknown_levels_and_drops_warnings():
    out = ("src/a.js\n  3:4  error  no-undef  'x' is not defined\n  5:1  warning  semi  Missing\n  7:2  info  odd  note\n"
           "  garbage row\n\n✖ 3 problems\n")
    assert pairs(pp.parse_eslint(out)) == [("src/a.js", 3, 4, "no-undef 'x' is not defined"),
                                           ("src/a.js", 7, 2, "info odd note")]


PYTEST_SUMMARY_ONLY = ("FAILED tests/test_cart.py::test_total - AssertionError: 4 != 5\nERROR tests/test_io.py::test_load\n"
                       "tests/test_io.py:12: in test_load\nE   KeyError: 'x'\nrandom noise line\n")


def test_pytest_summary_lines_are_enriched_from_traceback_frames_when_tb_is_off():
    got = pairs(pp.parse_pytest(PYTEST_SUMMARY_ONLY))
    assert got[0] == ("tests/test_cart.py", None, None, "AssertionError: 4 != 5")      # no frame for it: stays line-less
    assert got[1] == ("tests/test_io.py", 12, None, "KeyError: 'x'")                   # frame + last E row found


def test_pytest_import_failure_with_no_header_or_summary_reads_the_e_rows():
    with_frame = "ImportError while loading conftest '/r/conftest.py'.\nconftest.py:1: in <module>\nE   ModuleNotFoundError: No module named 'nope'\n"
    assert pairs(pp.parse_pytest(with_frame)) == [("conftest.py", 1, None, "ModuleNotFoundError: No module named 'nope'")]
    assert pairs(pp.parse_pytest("E   RuntimeError: boom\nE   more\n")) == [("", None, None, "RuntimeError: boom\nmore")]
    assert pp.parse_pytest("all fine\n") == []


def test_pytest_failing_frame_prefers_own_code_and_falls_back_to_the_last_outside_frame():
    own = "____ test_a ____\ntests/test_a.py:7: \n/usr/lib/python3.12/unittest/mock.py:1193: Exception\nE   Exception: 404\n"
    assert pairs(pp.parse_pytest(own)) == [("tests/test_a.py", 7, None, "Exception: 404")]
    outside = "____ test_a ____\n/usr/lib/python3.12/unittest/mock.py:1193: Exception\nE   Exception: 404\n"
    assert pp.parse_pytest(outside)[0].file.endswith("mock.py")


@pytest.mark.parametrize("findings,code,combined,expected", [
    ([pp.Finding("", None, None, "weird")], 1, "", f"{pp.UNKNOWN_LOCATION}: weird"),
    ([pp.Finding("Cargo.toml", None, None, "bad manifest")], 101, "", "Cargo.toml: bad manifest"),
    ([], 0, "anything", pp.CLEAN_SUMMARY), ([], None, "anything", pp.CLEAN_SUMMARY),
    ([], 1, "\n  \n", "exited 1 with no parseable diagnostics"),
    ([], 1, "[ERROR] Could not find artifact a:b:jar:5 in central\n[ERROR] [Help 1] http://cwiki.apache.org/x",
     "exited 1: [ERROR] Could not find artifact a:b:jar:5 in central"),
    ([], 1, "NoMethodError: undefined method `x' for nil\n7 runs, 4 assertions, 0 failures, 3 errors",
     "exited 1: NoMethodError: undefined method `x' for nil"),
    ([], 1, "[ERROR] http://only.a.pointer/failure", "exited 1: [ERROR] http://only.a.pointer/failure"),
])
def test_summarize_never_reports_a_pointer_or_a_tally_as_the_diagnosis(findings, code, combined, expected):
    assert pp.summarize(findings, code, combined) == expected


def test_pycompile_and_nodecheck_and_config_floors_localize_or_say_nothing():
    assert pp.parse_nodecheck("lib/a.js\nconst = 1;\nSyntaxError: Unexpected token '='\n")[0].line is None
    assert pp.parse_nodecheck("lib/a.js:4\nSyntaxError: x\n")[0].line == 4
    assert pp.parse_nodecheck("lib/a.js\nno syntax error line\n") == [] and pp.parse_nodecheck("SyntaxError: no file\n") == []
    assert pairs(pp.parse_config_syntax("pyproject.toml: Invalid value (at line 2, column 12)\nnot a path: line 3\n"
                                         "tsconfig.json: Expecting value: line 2 column 1\nx.json: no location here\n")) == [
        ("pyproject.toml", 2, 12, "Invalid value (at line 2, column 12)"),
        ("tsconfig.json", 2, 1, "Expecting value: line 2 column 1")]
    assert pairs(pp.parse_config_syntax("a.json: Expecting value: line 5\n")) == [("a.json", 5, None, "Expecting value: line 5")]


@pytest.mark.parametrize("text,expected", [
    ("--- PASS: TestA (0.00s)\nPASS\nok  x 0.1s\n", ("go", "0f/1p")),       # a Go run with only passing tests is still a Go tally
    ("--- FAIL: TestB (0.00s)\nFAIL\n", ("go", "1f/0p")),                    # ... and so is one with only failures
    ("--- PASS: A\n--- FAIL: B\n", ("go", "1f/1p")), ("nothing to see\n", ("", "")), (None, ("", ""))])
def test_the_runner_and_tally_is_named_from_whichever_go_rows_exist(text, expected):
    assert pp.runner_and_tally(text) == expected


@pytest.mark.parametrize("text,expected", [("4294967295", 4294967295), ("4294967296", None), ("+7", 7), ("007", 7), ("", None), ("-1", None), ("1_0", None)])
def test_a_rust_u32_is_up_to_exactly_u32_max(text, expected):
    assert pp.parse_u32(text) == expected
