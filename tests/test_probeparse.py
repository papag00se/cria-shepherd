"""Probe-output parsing: raw diagnostic-command output -> targeted repair hints.

The seven upstream Rust tests port verbatim; the rest pin the port's exact
semantics (upstream quirks included) and the pure Runner seam. LocalRunner —
the only thing here that spawns a process — lives in THIS file only: cria's
own modules never execute anything.
"""
import subprocess
import unittest

from cria import probeparse
from cria.probeparse import (
    Finding,
    ProbeResult,
    dedup,
    err_result,
    family_of,
    looks_like_path,
    parse_output,
    parse_u32,
    run_candidate,
    split_diag,
    split_loc,
    split_line_col,
)


# ---------------------------------------------------------------------------
# The seven upstream tests, verbatim.
# ---------------------------------------------------------------------------

class TestUpstreamParseOutput(unittest.TestCase):
    def test_parses_rustc_cargo(self):
        r = parse_output(
            "cargo check", "cargo", 101,
            "error[E0063]: missing field `expected_value` in initializer of `ProbeCandidate`\n"
            "  --> src/probes.rs:42:5\n"
            "   |\n"
            "42 |     ProbeCandidate {\n",
            "")
        self.assertEqual(len(r.findings), 1)
        f = r.findings[0]
        self.assertEqual(f.file, "src/probes.rs")
        self.assertEqual(f.line, 42)
        self.assertIn("missing field", f.message)
        self.assertTrue(r.summary.startswith("src/probes.rs:42:"))

    def test_parses_tsc(self):
        r = parse_output(
            "tsc --noEmit", "tsc", 2,
            "src/app.ts(12,7): error TS2322: Type 'string' is not assignable to type 'number'.",
            "")
        self.assertEqual(len(r.findings), 1)
        f = r.findings[0]
        self.assertEqual(f.file, "src/app.ts")
        self.assertEqual(f.line, 12)
        self.assertEqual(f.col, 7)
        self.assertIn("not assignable", f.message)

    def test_parses_eslint_stylish(self):
        r = parse_output(
            "eslint .", "eslint", 1,
            "/repo/src/index.js\n"
            "  10:5  error  'x' is not defined  no-undef\n"
            "  12:1  error  Unexpected console statement  no-console\n"
            "\n"
            "✖ 2 problems",
            "")
        self.assertEqual(len(r.findings), 2)
        self.assertEqual(r.findings[0].file, "/repo/src/index.js")
        self.assertEqual(r.findings[0].line, 10)
        self.assertIn("not defined", r.findings[0].message)

    def test_parses_generic_ruff_mypy_go(self):
        # ruff (undefined-name — a real bug that survives the error-class filter, so
        # the parse geometry is what's under test, not the filter)
        r = parse_output("ruff check .", "ruff", 1,
                         "app/main.py:3:1: F821 undefined name `os`", "")
        f = r.findings[0]
        self.assertEqual(f.file, "app/main.py")
        self.assertEqual(f.line, 3)
        self.assertEqual(f.col, 1)
        self.assertIn("undefined name", f.message)
        # mypy (no "mypy" arm in parse_output — generic fallback; message keeps "error: ")
        r = parse_output("mypy .", "mypy", 1,
                         "src/x.py:7: error: Incompatible return value type", "")
        f = r.findings[0]
        self.assertEqual(f.file, "src/x.py")
        self.assertEqual(f.line, 7)
        self.assertIn("Incompatible", f.message)
        # go vet
        r = parse_output("go vet ./...", "go", 1, "./server.go:9:2: unreachable code", "")
        f = r.findings[0]
        self.assertEqual(f.file, "./server.go")
        self.assertEqual(f.line, 9)

    def test_parses_pytest_summary(self):
        r = parse_output(
            "pytest -q", "pytest", 1,
            "=== FAILURES ===\n"
            "FAILED tests/test_api.py::test_resolve - AssertionError: expected 200\n"
            "FAILED tests/test_api.py::test_holder - KeyError: 'holder'\n"
            "=== short test summary ===",
            "")
        self.assertGreaterEqual(len(r.findings), 2)
        self.assertEqual(r.findings[0].file, "tests/test_api.py")
        self.assertIn("AssertionError", r.findings[0].message)

    def test_pytest_collection_error_is_localized(self):
        # A collection ImportError prints "ERROR <file>" with no line/cause + a real traceback frame.
        # Lift the frame's file:line + the E-line so the model gets a location, not a bare "test failed"
        # with "go to the reported line" (which fed a stuck loop).
        r = parse_output(
            "python3 -m pytest -q", "pytest", 2,
            "==================================== ERRORS ====================================\n"
            "________________ ERROR collecting smoke_test.py ________________\n"
            "smoke_test.py:2: in <module>\n"
            "    from .resolve_handle import resolve_ada_handle\n"
            "E   ImportError: attempted relative import with no known parent package\n"
            "=========================== short test summary info ===========================\n"
            "ERROR smoke_test.py\n"
            "!!!!!!!! Interrupted: 1 error during collection !!!!!!!!",
            "")
        self.assertEqual(len(r.findings), 1)
        f = r.findings[0]
        self.assertEqual(f.file, "smoke_test.py")
        self.assertEqual(f.line, 2)
        self.assertIn("attempted relative import", f.message)
        self.assertEqual(r.summary, "smoke_test.py:2: ImportError: attempted relative import with no known parent package")

    def test_pytest_collection_error_without_a_frame_keeps_the_collectors_own_message(self):
        # THE FOOTGUN (live run 0726-145040, 132 red gates, ~700 coder calls on one step): an
        # import-file-mismatch collection error has NO `path:line:` frame and NO `E   ` rows, so the
        # traceback reader skipped the block, and the summary's bare `ERROR <nodeid>` fell through to
        # the literal "test failed". pytest had already said exactly what to do — two test files share
        # a basename, drop __pycache__ or rename — and cria replaced that with two words, so the coder
        # spent hundreds of calls editing test LOGIC while nothing could be collected at all. The
        # preamble promises "each problem below is the checker's OWN message"; it must be true.
        r = parse_output(
            "python3 -m pytest -q", "pytest", 2,
            "==================================== ERRORS ====================================\n"
            "________________ ERROR collecting tests/test_resolve_handles.py ________________\n"
            "import file mismatch:\n"
            "imported module 'test_resolve_handles' has this __file__ attribute:\n"
            "  /repo/test_resolve_handles.py\n"
            "which is not the same as the test file we want to collect:\n"
            "  /repo/tests/test_resolve_handles.py\n"
            "HINT: remove __pycache__ / .pyc files and/or use a unique basename for your test file modules\n"
            "=========================== short test summary info ===========================\n"
            "ERROR tests/test_resolve_handles.py\n"
            "!!!!!!!! Interrupted: 1 error during collection !!!!!!!!",
            "")
        self.assertEqual(len(r.findings), 1)
        msg = r.findings[0].message
        self.assertEqual(r.findings[0].file, "tests/test_resolve_handles.py")
        self.assertIn("import file mismatch", msg)          # the collector's real diagnostic...
        self.assertIn("unique basename", msg)               # ...including the HINT that fixes it
        self.assertNotIn("test failed", msg)                # ...not cria's two-word stand-in

    def test_collection_error_survives_alongside_an_ordinary_failure(self):
        # `if out: return out` used to run BEFORE the collect path, so one normal test failure hid an
        # entire uncollectable file — the shape run 0726-145040 actually had, which is why 96becb0
        # alone would not have rescued it. Both must be reported.
        r = parse_output(
            "python3 -m pytest -q", "pytest", 1,
            "=================================== FAILURES ===================================\n"
            "_______________________________ test_adds _______________________________\n"
            "tests/test_math.py:4: in test_adds\n"
            "    assert add(1,1) == 3\n"
            "E   assert 2 == 3\n"
            "==================================== ERRORS ====================================\n"
            "________________ ERROR collecting tests/test_dup.py ________________\n"
            "import file mismatch:\n"
            "HINT: remove __pycache__ / .pyc files and/or use a unique basename for your test file modules\n"
            "=========================== short test summary info ===========================\n"
            "FAILED tests/test_math.py::test_adds - assert 2 == 3\n"
            "ERROR tests/test_dup.py\n",
            "")
        files = {f.file for f in r.findings}
        self.assertIn("tests/test_math.py", files)      # the ordinary failure...
        self.assertIn("tests/test_dup.py", files)       # ...and the uncollectable file
        dup = next(f for f in r.findings if f.file == "tests/test_dup.py")
        self.assertIn("unique basename", dup.message)   # with the collector's own HINT

    def test_pytest_conftest_error_reports_the_EXCEPTION_not_the_stack_frame(self):
        # A broken conftest prints no block header and no FAILED/ERROR summary line, so nothing read
        # its `E   ` rows and the finding fell through to a generic file:line scrape — the model was
        # told "conftest.py:1: in <module>", the stack FRAME, while pytest's actual words
        # ("ModuleNotFoundError: No module named 'nosuchmodule'") were dropped. The E-rows ARE the
        # checker's own error text. Outermost frame = the user's file, not the library beneath it.
        r = parse_output(
            "python3 -m pytest -q", "pytest", 4,
            "ImportError while loading conftest '/repo/conftest.py'.\n"
            "conftest.py:1: in <module>\n"
            "    import nosuchmodule\n"
            "E   ModuleNotFoundError: No module named 'nosuchmodule'\n",
            "")
        self.assertEqual(len(r.findings), 1)
        f = r.findings[0]
        self.assertEqual((f.file, f.line), ("conftest.py", 1))
        self.assertIn("ModuleNotFoundError", f.message)
        self.assertNotIn("in <module>", f.message)      # the frame is not the error

    def test_pytest_normal_failure_keeps_no_line(self):
        # A plain assertion failure has no traceback :in <module>: frame — it stays line=None (unchanged).
        r = parse_output("pytest", "pytest", 1,
                         "FAILED tests/test_api.py::test_x - AssertionError: expected 200", "")
        self.assertIsNone(r.findings[0].line)
        self.assertIn("AssertionError", r.findings[0].message)

    def test_pytest_traceback_block_gives_full_message_and_real_line(self):
        # Read the failure BLOCK (full E-line + real test:line), NEVER pytest's width-clipped short-summary
        # (which arrives as `… - Asserti…` on an 80-col non-tty). This is the session-3 blindfold.
        out = ("=================================== FAILURES ===================================\n"
               "_______________________________ test_status _______________________________\n"
               ">       self.assertEqual(resp['statusCode'], 200)\n"
               "E       AssertionError: 400 != 200\n"
               "test_lambda.py:15: AssertionError\n"
               "=========================== short test summary info ============================\n"
               "FAILED test_lambda.py::TestX::test_status - Asserti...\n")
        fs = probeparse.parse_pytest(out)
        self.assertEqual(len(fs), 1)
        self.assertEqual(fs[0].file, "test_lambda.py")
        self.assertEqual(fs[0].line, 15)
        self.assertEqual(fs[0].message, "AssertionError: 400 != 200")   # FULL, from the block not the summary

    def test_pytest_multiline_assertion_is_joined_whole(self):
        # a dict-diff assertion spans several E-lines — keep the header AND the diff, drop nothing
        out = ("=================================== FAILURES ===================================\n"
               "____________________________________ test_d ____________________________________\n"
               "E       AssertionError: assert {'x': 1} == {'x': 2}\n"
               "E         Differing items:\n"
               "E         {'x': 1} != {'x': 2}\n"
               "test_d.py:9: AssertionError\n")
        msg = probeparse.parse_pytest(out)[0].message
        self.assertIn("AssertionError: assert {'x': 1} == {'x': 2}", msg)   # header kept
        self.assertIn("{'x': 1} != {'x': 2}", msg)                          # diff rows kept too

    def test_clean_run_has_no_findings(self):
        r = parse_output("cargo check", "cargo", 0, "    Finished dev [unoptimized]\n", "")
        self.assertEqual(r.findings, [])
        self.assertEqual(r.summary, "no problems reported")

    def test_nonzero_exit_without_structured_output_summarizes_last_error(self):
        r = parse_output("make check", "", 2, "building...\nfatal: something broke\n", "")
        self.assertEqual(r.findings, [])
        self.assertIn("something broke", r.summary)
        self.assertEqual(r.summary, "exited 2: fatal: something broke")

    def test_tomllib_prose_location_becomes_a_finding(self):
        # The tier-0 TOML floor prints `<file>: Invalid value (at line 2, column 12)` — prose, not
        # file:line:col. Without lifting it the model was told "go to the reported line" with no line.
        r = parse_output("python3 -c <toml-check> /x/pyproject.toml", "generic", 1,
                         "/x/pyproject.toml: Invalid value (at line 2, column 12)", "")
        self.assertEqual(len(r.findings), 1)
        f = r.findings[0]
        self.assertEqual(f.file, "/x/pyproject.toml")
        self.assertEqual(f.line, 2)
        self.assertEqual(f.col, 12)
        self.assertEqual(r.summary, "/x/pyproject.toml:2: Invalid value (at line 2, column 12)")

    def test_json_prose_location_becomes_a_finding(self):
        # json.load: `<file>: Expecting value: line 2 column 1 (char 5)` — different prose, still lifted.
        r = parse_output("python3 -c <json-check> /x/tsconfig.json", "generic", 1,
                         "/x/tsconfig.json: Expecting value: line 2 column 1 (char 5)", "")
        self.assertEqual(len(r.findings), 1)
        self.assertEqual(r.findings[0].file, "/x/tsconfig.json")
        self.assertEqual(r.findings[0].line, 2)

    def test_config_prose_needs_a_path_prefix_no_false_positive(self):
        # A benign log line mentioning "line 5" with no path prefix must NOT become a finding.
        r = parse_output("x", "", 1, "some log mentioning line 5 of the story", "")
        self.assertEqual(r.findings, [])

    def test_config_prose_does_not_shadow_a_real_file_line_col(self):
        # A tool that already localized the error keeps its parse_generic finding — the prose arm
        # only runs when nothing else matched.
        r = parse_output("ruff", "generic", 1, "/x/a.py:5:4: undefined name foo", "")
        self.assertEqual(r.findings[0].file, "/x/a.py")
        self.assertEqual(r.findings[0].line, 5)


# ---------------------------------------------------------------------------
# Port regressions recommended by the spec (exact semantics, not in Rust tests).
# ---------------------------------------------------------------------------

class TestPortRegressions(unittest.TestCase):
    def test_dedup_ignores_column(self):
        findings = [
            Finding("a.py", 1, 5, "boom"),
            Finding("a.py", 1, 9, "boom"),   # same (file, line, message), different col → dup
            Finding("a.py", 2, 5, "boom"),   # different line → kept
        ]
        dedup(findings)
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0].col, 5)  # first occurrence kept, order preserved
        self.assertEqual(findings[1].line, 2)

    def test_unknown_exit_with_no_findings_reads_clean(self):
        # CONTRACT HAZARD preserved: exit_code=None is treated as success.
        r = parse_output("mystery", "", None, "", "")
        self.assertEqual(r.summary, "no problems reported")
        self.assertEqual(r.findings, [])

    def test_multi_finding_summary_counts_more(self):
        r = parse_output("ruff check .", "ruff", 1,
                         "a.py:1:1: E1 first\nb.py:2:2: E2 second\n", "")
        self.assertEqual(len(r.findings), 2)
        self.assertIn(" (+1 more)", r.summary)
        self.assertTrue(r.summary.startswith("a.py:1: "))


# ---------------------------------------------------------------------------
# Upstream quirks and helper edge cases, preserved verbatim.
# ---------------------------------------------------------------------------

class TestQuirksAndHelpers(unittest.TestCase):
    def test_rustc_prefix_is_startswith_not_whole_word(self):
        # "errors occurred" startswith "error"; the [E..]-code strip eats the "s".
        r = parse_output("cargo check", "cargo", 101,
                         "errors occurred\n  --> src/a.rs:1:2\n", "")
        self.assertEqual(len(r.findings), 1)
        self.assertEqual(r.findings[0].message, "occurred")

    def test_rustc_bare_arrow_defaults_to_compile_error(self):
        r = parse_output("cargo check", "cargo", 101, "  --> src/a.rs:7:1\n", "")
        self.assertEqual(r.findings[0].message, "compile error")

    def test_rustc_message_consumed_once(self):
        # last_msg resets after use: a second --> without a fresh header defaults.
        out = probeparse.parse_rustc(
            "error: first\n  --> a.rs:1:1\n  --> b.rs:2:2\n")
        self.assertEqual([f.message for f in out], ["first", "compile error"])

    def test_split_loc_edge_cases(self):
        self.assertIsNone(split_loc("src/foo.rs:42:abc"))  # col fails, then line "abc" fails
        self.assertIsNone(split_loc("noloc"))
        self.assertEqual(split_loc("C:\\x\\f.rs:3:1"), ("C:\\x\\f.rs", 3, 1))
        self.assertEqual(split_loc("src/foo.rs:42"), ("src/foo.rs", 42, None))
        self.assertEqual(split_loc("src/foo.rs: 42 : 5 "), ("src/foo.rs", 42, 5))  # trims

    def test_split_diag_does_not_trim_numbers(self):
        # Asymmetry with split_loc: no trim before parse_u32 here.
        self.assertIsNone(split_diag("a.py:7 : boom"))              # "7 " fails strict parse
        self.assertEqual(split_loc("a.py:7 "), ("a.py", 7, None))   # split_loc trims → parses
        self.assertEqual(split_diag("a.py:7:2: boom"), ("a.py", 7, 2, "boom"))
        self.assertEqual(split_diag("a.py:7: boom"), ("a.py", 7, None, "boom"))
        self.assertIsNone(split_diag("no colon-space here"))

    def test_split_line_col_shapes(self):
        self.assertEqual(split_line_col("12,7"), (12, 7))
        self.assertEqual(split_line_col("12:7"), (12, 7))
        self.assertEqual(split_line_col("12"), (12, None))
        self.assertEqual(split_line_col("x:7"), (None, 7))  # callers gate on line
        self.assertEqual(split_line_col(""), (None, None))

    def test_parse_u32_is_strict(self):
        self.assertEqual(parse_u32("42"), 42)
        self.assertEqual(parse_u32("+42"), 42)
        self.assertEqual(parse_u32("4294967295"), 4294967295)
        self.assertIsNone(parse_u32("4294967296"))   # > u32::MAX
        self.assertIsNone(parse_u32("-1"))
        self.assertIsNone(parse_u32("1_0"))          # int() would take these; u32::parse won't
        self.assertIsNone(parse_u32(" 7"))
        self.assertIsNone(parse_u32("7.0"))
        self.assertIsNone(parse_u32("١٢"))  # unicode digits rejected
        self.assertIsNone(parse_u32(""))

    def test_looks_like_path(self):
        self.assertTrue(looks_like_path("src/x.py"))
        self.assertTrue(looks_like_path("x.py"))
        self.assertTrue(looks_like_path("a\\b"))
        self.assertFalse(looks_like_path(""))
        self.assertFalse(looks_like_path("has space.py"))
        self.assertFalse(looks_like_path("http://x.io/y"))
        self.assertFalse(looks_like_path("nodots"))

    def test_tsc_requires_paren_colon_space(self):
        self.assertEqual(probeparse.parse_tsc("foo(12,7) error no marker"), [])
        self.assertEqual(probeparse.parse_tsc("(12,7): headless"), [])  # empty file → skip
        out = probeparse.parse_tsc("a.ts(3): loose")
        self.assertEqual(out, [Finding("a.ts", 3, None, "loose")])

    def test_eslint_unknown_level_prepended_to_message(self):
        out = probeparse.parse_eslint("/repo/a.js\n  3:4  hint  something odd\n")
        self.assertEqual(out, [Finding("/repo/a.js", 3, 4, "hint something odd")])

    def test_eslint_file_state_survives_blank_lines(self):
        out = probeparse.parse_eslint("/repo/a.js\n\n  3:4  error  late row  r1\n")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].file, "/repo/a.js")

    def test_pytest_without_dash_suffix_defaults(self):
        out = probeparse.parse_pytest("FAILED tests/t.py::test_x\nERROR tests/u.py::test_y\n")
        self.assertEqual(out[0], Finding("tests/t.py", None, None, "test failed"))
        self.assertEqual(out[1], Finding("tests/u.py", None, None, "test failed"))

    def test_summary_last_errorish_line_wins_bottom_up(self):
        r = parse_output("make", "", 3, "error: early\nnoise\nFAILED late\n", "")
        self.assertEqual(r.summary, "exited 3: FAILED late")

    def test_no_errorish_line_yields_no_parseable_diagnostics(self):
        r = parse_output("make", "", 4, "just noise\n", "")
        self.assertEqual(r.summary, "exited 4 with no parseable diagnostics")

    def test_summary_unknown_location_placeholder(self):
        self.assertEqual(probeparse.summarize([Finding("", None, None, "m")], 1, ""),
                         "?: m")

    def test_unittest_family_uses_pytest_parser(self):
        r = parse_output("python3 -m unittest", "unittest", 1,
                         "FAILED tests/t.py::test_x - AssertionError\n", "")
        self.assertEqual(r.findings[0].file, "tests/t.py")


class TestFamilyOf(unittest.TestCase):
    def test_whole_token_equality(self):
        self.assertEqual(family_of(["cargo", "check"]), "cargo")
        self.assertEqual(family_of(["npx", "tsc", "--noEmit"]), "tsc")
        self.assertEqual(family_of(["npx", "vue-tsc"]), "tsc")
        self.assertEqual(family_of(["eslint", "."]), "eslint")
        self.assertEqual(family_of(["pytest", "-q"]), "pytest")
        self.assertEqual(family_of(["python3", "-m", "pytest"]), "pytest")
        self.assertEqual(family_of(["mypy", "."]), "mypy")
        self.assertEqual(family_of(["ruff", "check", "."]), "")
        self.assertEqual(family_of([]), "")
        # substring must NOT match
        self.assertEqual(family_of(["cargo-nextest"]), "")
        self.assertEqual(family_of(["not-eslint"]), "")

    def test_precedence_cargo_first(self):
        self.assertEqual(family_of(["cargo", "eslint"]), "cargo")


# ---------------------------------------------------------------------------
# The Runner seam — pure contract, exercised with a fake.
# ---------------------------------------------------------------------------

class _FakeRunner:
    def __init__(self, exit_code, stdout, stderr, timed_out=False, raises=None):
        self.result = (exit_code, stdout, stderr, timed_out)
        self.raises = raises
        self.calls = []

    def __call__(self, argv, cwd, timeout_s):
        self.calls.append((list(argv), cwd, timeout_s))
        if self.raises is not None:
            raise self.raises
        return self.result


class TestRunnerSeam(unittest.TestCase):
    def test_err_result_shape(self):
        r = err_result("cmd here", "boom")
        self.assertEqual((r.command, r.exit_code, r.summary, r.findings),
                         ("cmd here", None, "boom", []))

    def test_probe_result_is_not_comparable_by_value(self):
        # Upstream derives Clone+Debug but NOT Eq; the port keeps eq=False.
        self.assertNotEqual(ProbeResult("c", None, "s", []), ProbeResult("c", None, "s", []))
        self.assertEqual(Finding("f", 1, 2, "m"), Finding("f", 1, 2, "m"))  # Finding IS Eq

    def test_empty_command(self):
        r = run_candidate(_FakeRunner(0, "", ""), [], "/tmp", 5.0)
        self.assertEqual(r.summary, "empty command")
        self.assertIsNone(r.exit_code)
        self.assertEqual(r.findings, [])

    def test_launch_failure(self):
        runner = _FakeRunner(None, "", "", raises=FileNotFoundError("no such tool"))
        r = run_candidate(runner, ["missing-tool"], "/tmp", 5.0)
        self.assertIsNone(r.exit_code)
        self.assertIn("failed to launch", r.summary)
        self.assertIn("tool not installed?", r.summary)
        self.assertEqual(r.findings, [])

    def test_timeout_overwrites_summary_keeps_partial_findings(self):
        runner = _FakeRunner(None, "app/main.py:3:1: F821 undefined name `os`\n", "",
                             timed_out=True)
        r = run_candidate(runner, ["ruff", "check", "."], "/tmp", 20.0)
        self.assertEqual(
            r.summary,
            "TIMEOUT after 20s — probe did not finish (consider a narrower target)")
        self.assertEqual(len(r.findings), 1)  # findings from partial output kept
        self.assertEqual(r.findings[0].file, "app/main.py")

    def test_happy_path_uses_token_family_and_joined_command(self):
        runner = _FakeRunner(
            101, "error[E1]: boom\n  --> src/a.rs:1:2\n", "")
        r = run_candidate(runner, ["cargo", "check"], "/repo", 30.0)
        self.assertEqual(runner.calls, [(["cargo", "check"], "/repo", 30.0)])
        self.assertEqual(r.command, "cargo check")
        self.assertEqual(r.exit_code, 101)
        self.assertEqual(r.findings[0].file, "src/a.rs")


# ---------------------------------------------------------------------------
# LocalRunner: subprocess-based, defined HERE only (cria owns no executors).
# ---------------------------------------------------------------------------

def _text(v):
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


class LocalRunner:
    """Reference Runner for tests: subprocess.run with drain + kill-on-timeout."""

    def __call__(self, argv, cwd, timeout_s):
        try:
            proc = subprocess.run(
                list(argv), cwd=cwd, capture_output=True, text=True,
                timeout=timeout_s, stdin=subprocess.DEVNULL)
            return proc.returncode, proc.stdout, proc.stderr, False
        except subprocess.TimeoutExpired as e:
            return None, _text(e.stdout), _text(e.stderr), True


class TestLocalRunner(unittest.TestCase):
    def test_real_process_generic_diagnostic(self):
        code = "import sys; sys.stderr.write('app/main.py:3:1: F401 x unused\\n'); sys.exit(1)"
        r = run_candidate(LocalRunner(), ["python3", "-c", code], "/tmp", 30.0)
        self.assertEqual(r.exit_code, 1)
        self.assertEqual(len(r.findings), 1)
        self.assertEqual(r.findings[0], Finding("app/main.py", 3, 1, "F401 x unused"))
        self.assertTrue(r.summary.startswith("app/main.py:3: "))

    def test_real_clean_exit(self):
        r = run_candidate(LocalRunner(), ["python3", "-c", "print('ok')"], "/tmp", 30.0)
        self.assertEqual(r.exit_code, 0)
        self.assertEqual(r.summary, "no problems reported")

    def test_real_launch_failure(self):
        r = run_candidate(LocalRunner(),
                          ["definitely-not-a-real-binary-cria-xyz"], "/tmp", 5.0)
        self.assertIsNone(r.exit_code)
        self.assertIn("failed to launch", r.summary)
        self.assertIn("tool not installed?", r.summary)

    def test_real_timeout(self):
        r = run_candidate(LocalRunner(),
                          ["python3", "-c", "import time; time.sleep(30)"], "/tmp", 1.0)
        self.assertTrue(r.summary.startswith("TIMEOUT after 1s"))
        self.assertIsNone(r.exit_code)


if __name__ == "__main__":
    unittest.main()


class ErrorClassFilterTests(unittest.TestCase):
    """Operator filter (2026-07-11): probes gate on ERROR-CLASS issues only — style,
    notes, warnings, and advisory findings never block a step."""

    def test_mypy_notes_dropped_errors_kept(self):
        r = parse_output("mypy .", "", 1,
                         "x.py:7: note: See docs\nx.py:7: error: bad return\n", "")
        self.assertEqual([(f.line, f.message) for f in r.findings],
                         [(7, "error: bad return")])

    def test_style_codes_dropped_error_codes_kept(self):
        r = parse_output("ruff check .", "", 1,
                         "a.py:3:1: E501 line too long\n"       # style code → dropped
                         "a.py:4:1: W291 trailing whitespace\n"  # style code → dropped
                         "a.py:5:1: C0114 missing docstring\n"   # convention code → dropped
                         "a.py:6:1: F401 `os` imported but unused\n"  # unused → dropped by phrase
                         "a.py:7:1: F821 undefined name `foo`\n"      # real bug → kept
                         "a.py:9:1: E999 SyntaxError: bad\n", "")      # E9xx syntax → kept
        msgs = [f.message for f in r.findings]
        self.assertEqual(msgs, ["F821 undefined name `foo`", "E999 SyntaxError: bad"])

    def test_unused_advisories_never_gate_across_linters(self):
        # The unused/never-used family is cleanliness, not an error state, so it is
        # dropped tool-agnostically (by message) — leaving any REAL error underneath
        # to surface. This is the class the live session tripped on: pyflakes' bare
        # "imported but unused" buried a genuine "undefined name".
        r = parse_output("python3 -m pyflakes app tests", "", 1,
                         "tests/t.py:1:1: 'json' imported but unused\n"
                         "tests/t.py:7:18: undefined name 'resolver'\n", "")
        self.assertEqual([f.message for f in r.findings], ["undefined name 'resolver'"])
        # ruff attaches the SAME message to an F-code we otherwise keep → still dropped
        r = parse_output("ruff check .", "", 1, "a.py:2:1: F401 `os` imported but unused\n", "")
        self.assertEqual(r.findings, [])
        # eslint no-unused-vars promoted to error-severity → dropped
        r = parse_output("eslint .", "eslint", 1,
                         "/w/a.js\n  3:7  error  'x' is defined but never used  no-unused-vars\n", "")
        self.assertEqual(r.findings, [])
        # tsc TS6133 (noUnusedLocals) → dropped
        r = parse_output("tsc --noEmit", "tsc", 1,
                         "src/a.ts(3,7): error TS6133: 'x' is declared but its value is never read.\n", "")
        self.assertEqual(r.findings, [])
        # BUT Go's unused import is a hard COMPILE error, not a lint advisory → keeps gating
        r = parse_output("go build ./...", "", 1,
                         './main.go:5:2: "fmt" imported and not used\n', "")
        self.assertEqual(len(r.findings), 1)

    def test_compiler_warnings_dropped(self):
        r = parse_output("make", "", 1,
                         "main.c:4:2: warning: unused variable\nmain.c:9:2: error: expected ';'\n", "")
        self.assertEqual(len(r.findings), 1)
        self.assertIn("error:", r.findings[0].message)

    def test_eslint_warnings_never_gate(self):
        out = ("/w/a.js\n"
               "  10:5  warning  Unexpected console statement  no-console\n"
               "  12:1  error  'x' is not defined  no-undef\n")
        r = parse_output("eslint .", "eslint", 1, out, "")
        self.assertEqual([(f.line, "error" in f.message or "no-undef" in f.message)
                          for f in r.findings], [(12, True)])


class RunnerLocationTests(unittest.TestCase):
    """Test runners that print their location in a shape `file:line: message` does not cover.

    Verified against REAL failing runs on this box — a Rust crate, an rspec spec, a phpunit case —
    not reconstructions. Reconstructions are what made me report maven as a parser gap when its
    console output carries no location at all."""

    CARGO = ("running 1 test\ntest tests::it_adds ... FAILED\n\n"
             "---- tests::it_adds stdout ----\n\n"
             "thread 'tests::it_adds' (722421) panicked at src/lib.rs:7:20:\n"
             "assertion `left == right` failed\n  left: 4\n right: 5\n")
    RSPEC = ("Failures:\n\n  1) adder adds\n     Failure/Error: expect(2 + 2).to eq(5)\n\n"
             "       expected: 5\n            got: 4\n\n"
             "     # ./a_spec.rb:3:in `block (2 levels) in <top (required)>'\n")
    PHPUNIT = ("There was 1 failure:\n\n1) AppTest::testAdd\n"
               "Failed asserting that 4 is identical to 5.\n\n/w/tests/AppTest.php:14\n\nFAILURES!\n")
    MAVEN = ("Results :\n\nFailed tests:   testAdd(app.AdderTest): expected:<5> but was:<4>\n\n"
             "Tests run: 1, Failures: 1, Errors: 0, Skipped: 0\n")

    def test_cargo_panic_location(self):
        f = probeparse.parse_generic(self.CARGO)
        self.assertEqual((f[0].file, f[0].line), ("src/lib.rs", 7))
        self.assertIn("assertion", f[0].message)      # the assertion, not the panic line itself

    def test_rspec_backtrace_location(self):
        f = probeparse.parse_generic(self.RSPEC)
        self.assertEqual((f[0].file, f[0].line), ("./a_spec.rb", 3))

    def test_phpunit_bare_location_line(self):
        f = probeparse.parse_generic(self.PHPUNIT)
        self.assertEqual((f[0].file, f[0].line), ("/w/tests/AppTest.php", 14))
        self.assertIn("Failed asserting", f[0].message)

    def test_maven_prints_no_location_so_none_is_invented(self):
        # The file and line exist only in target/surefire-reports. Inventing one would be worse
        # than reporting none.
        self.assertEqual(probeparse.parse_generic(self.MAVEN), [])

    def test_a_compilers_own_diagnostics_are_never_crowded_out(self):
        # A panic further down must not displace real file:line: diagnostics above it.
        mixed = "src/main.rs:4:13: error: cannot find value `x`\n" + self.CARGO
        f = probeparse.parse_generic(mixed)
        self.assertEqual(f[0].line, 4)
        self.assertIn("cannot find value", f[0].message)


class SucceededCommandsHaveNoFailures(unittest.TestCase):
    """A shape scraper must never manufacture a failure out of the output of a command that
    exited 0. Captured live (run 20260728T000013, calls 0165-0205): the tests PASSED and cria
    told the coder "the repo's own checks fail" 40 times, pointing at a warning about a typo'd
    pytest mark. parse_pytest had correctly found nothing; parse_generic invented it."""

    PASSED_WITH_WARNING = (
        "============================= test session starts ==============================\n"
        "collected 1 item\n\n"
        "test_resolve_handle.py .                                                 [100%]\n\n"
        "=============================== warnings summary ===============================\n"
        "test_resolve_handle.py:95\n"
        "  /w/test_resolve_handle.py:95: PytestUnknownMarkWarning: Unknown pytest.mark.live"
        " - is this a typo?\n"
        "    @pytest.mark.live\n\n"
        "========================= 1 passed, 1 warning in 0.42s =========================\n"
    )

    def test_passing_pytest_run_with_a_warning_reports_nothing(self):
        r = probeparse.parse_output("python3 -m pytest -q", "pytest", 0,
                                    self.PASSED_WITH_WARNING, "")
        self.assertEqual(r.findings, [])
        self.assertNotIn("PytestUnknownMarkWarning", r.summary)

    def test_the_same_output_from_a_FAILING_command_is_still_read(self):
        # The guard is the exit code, not the text — a non-zero exit still scrapes.
        r = probeparse.parse_output("python3 -m pytest -q", "pytest", 1,
                                    self.PASSED_WITH_WARNING, "")
        self.assertTrue(r.findings)

    def test_unknown_exit_code_still_scrapes(self):
        # None means UNKNOWN, not zero. Refusing to look would hide a real failure.
        r = probeparse.parse_output("some-tool", "", None,
                                    "src/a.py:3: SyntaxError: bad\n", "")
        self.assertTrue(r.findings)

    def test_a_familys_own_parser_is_unaffected_by_the_guard(self):
        # The family parser knows its tool's contract; only the shape scrapers are gated.
        r = probeparse.parse_output("python3 -m pytest -q", "pytest", 1,
                                    "FAILED test_x.py::test_a - AssertionError: nope\n", "")
        self.assertTrue(r.findings)


class MockedFrameVisibilityTests(unittest.TestCase):
    """When a test's own mock supplies the exception, pytest prints the test's frame as
    `path:line:` with NOTHING after it. The pattern required a non-empty tail, so that frame was
    invisible to every consumer of _PYTEST_LOC_LINE — including the outermost-frame fallback, which
    then reported a library frame as the user's file."""

    def test_a_frame_line_with_no_tail_is_seen(self):
        self.assertEqual(probeparse._PYTEST_LOC_LINE.findall("resolve_handle_test.py:28: "),
                         [("resolve_handle_test.py", "28", "")])

    def test_a_frame_line_with_no_trailing_space_is_seen(self):
        self.assertEqual(probeparse._PYTEST_LOC_LINE.findall("t.py:9:"),
                         [("t.py", "9", "")])

    def test_the_normal_shape_is_unchanged(self):
        self.assertEqual(probeparse._PYTEST_LOC_LINE.findall("resolve_handle.py:19: in resolve_handle"),
                         [("resolve_handle.py", "19", "in resolve_handle")])

    def test_the_outermost_frame_fallback_now_names_the_TEST_file(self):
        # The conftest/no-block path takes locs[0]. With the test frame invisible it took a
        # deeper one; now the user's own entry point is first.
        s = ("resolve_handle_test.py:28: \n"
             "resolve_handle.py:19: in resolve_handle\n"
             "E   Exception: Network error\n")
        out = probeparse.parse_pytest(s)
        self.assertEqual(out[0].file, "resolve_handle_test.py")
        self.assertIn("Network error", out[0].message)


class UnusedNameWarningsNeverGateTests(unittest.TestCase):
    """The gate is ERROR-CLASS only: a cleanliness warning must never reach the model as
    "[GROUND TRUTH — the repo's own checks fail]". `redefinition of unused 'x' from line N` is the
    unused-import warning wearing different words, and it was missing from the list.

    Walked on ada-handles_mellum2_codex_poff_1785693138: for ~25 consecutive calls it was the ONLY
    thing the gate reported. The edit that cleared it deleted the module-level `import json`;
    pyflakes then reported nothing, and the delivered program crashes with
    `NameError: name 'json' is not defined`. The gate demanded a change that broke the program and
    certified the result clean."""

    def test_redefinition_of_unused_is_advisory(self):
        self.assertTrue(probeparse.is_advisory("redefinition of unused 'json' from line 14"))

    def test_it_never_reaches_the_model_as_a_failing_check(self):
        out = ("x.py:1:1: 'json' imported but unused\n"
               "x.py:5:5: redefinition of unused 'json' from line 1\n")
        r = probeparse.parse_output("python3 -m pyflakes .", "", 1, out, "")
        self.assertEqual(r.findings, [], f"a cleanliness warning still gates: {r.summary}")

    def test_an_f_string_with_no_placeholders_is_advisory(self):
        self.assertTrue(probeparse.is_advisory("f-string is missing placeholders"))

    def test_a_REAL_pyflakes_error_still_gates(self):
        # The whole point of the filter is that error-class findings survive it.
        for msg in ("undefined name '_test'",
                    "local variable 'x' referenced before assignment",
                    "dictionary key 'a' repeated with different values"):
            with self.subTest(msg=msg):
                self.assertFalse(probeparse.is_advisory(msg))
                r = probeparse.parse_output("python3 -m pyflakes .", "", 1, f"x.py:3:1: {msg}\n", "")
                self.assertTrue(r.findings, f"a real error was dropped: {msg}")


class F811ShadowDiscriminatorTests(unittest.TestCase):
    """F811 covers TWO different things under one message: an import bound twice (cleanliness,
    stays advisory — the mellum2 walk) and a def/class bound twice, where the second silently
    replaces the first at runtime (a real bug). Walked on
    ada-handles_maple-preview_codex_poff_1785956867: the coder wrote two `def resolve_handle`
    in one file — the second shadowed the /v1 network resolver, the "live" path recursed into
    its own simulator, and the whole run built a mock architecture around the confusion.
    pyflakes named the exact line; the advisory filter suppressed it, and no channel ever
    surfaced the duplicate. The discriminator the old KNOWN-COST comment called for: the
    flagged line's on-disk text, injected by callers that hold the file (the module stays pure —
    with no flagged_line the pure default is unchanged)."""

    _MSG = "redefinition of unused 'resolve_handle' from line 27"

    def test_pure_default_without_the_line_stays_advisory(self):
        self.assertTrue(probeparse.is_advisory(self._MSG))
        self.assertTrue(probeparse.is_advisory(self._MSG, None))

    def test_a_def_shadow_is_a_real_error(self):
        for line in ("def resolve_handle(handle, live_test=False):",
                     "    def resolve_handle(handle):",
                     "async def resolve_handle(handle):",
                     "class ResolveHandle:"):
            with self.subTest(line=line):
                self.assertFalse(probeparse.is_advisory(self._MSG, line))

    def test_an_import_rebinding_stays_advisory(self):
        for line in ("import json", "from x import resolve_handle", "    import json"):
            with self.subTest(line=line):
                self.assertTrue(probeparse.is_advisory(self._MSG, line))

    def test_the_line_only_refines_f811_not_other_advisories(self):
        # A def-shaped flagged line must not un-filter a genuinely advisory message.
        self.assertTrue(probeparse.is_advisory("'json' imported but unused", "def f():"))

    def test_parse_output_with_a_reader_keeps_the_def_shadow(self):
        out = "x.py:148:1: redefinition of unused 'resolve_handle' from line 27\n"
        r = probeparse.parse_output("python3 -m pyflakes x.py", "", 1, out, "",
                                    read_source_line=lambda p, n: "def resolve_handle(h, live_test=False):")
        self.assertEqual(len(r.findings), 1, f"the def shadow was dropped: {r.summary}")
        r = probeparse.parse_output("python3 -m pyflakes x.py", "", 1, out, "",
                                    read_source_line=lambda p, n: "import json")
        self.assertEqual(r.findings, [], "an import rebinding gated")

    def test_parse_output_without_a_reader_is_unchanged(self):
        out = "x.py:148:1: redefinition of unused 'resolve_handle' from line 27\n"
        r = probeparse.parse_output("python3 -m pyflakes x.py", "", 1, out, "")
        self.assertEqual(r.findings, [])
