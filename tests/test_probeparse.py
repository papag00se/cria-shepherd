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
    truncate,
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

    def test_clean_run_has_no_findings(self):
        r = parse_output("cargo check", "cargo", 0, "    Finished dev [unoptimized]\n", "")
        self.assertEqual(r.findings, [])
        self.assertEqual(r.summary, "no problems reported")

    def test_nonzero_exit_without_structured_output_summarizes_last_error(self):
        r = parse_output("make check", "", 2, "building...\nfatal: something broke\n", "")
        self.assertEqual(r.findings, [])
        self.assertIn("something broke", r.summary)
        self.assertEqual(r.summary, "exited 2: fatal: something broke")


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

    def test_truncate_boundary(self):
        self.assertEqual(truncate("x" * 100, 100), "x" * 100)          # exactly at limit: untouched
        self.assertEqual(truncate("x" * 101, 100), "x" * 100 + "…")   # one over: capped + ellipsis
        self.assertEqual(truncate("  padded  ", 100), "padded")        # strips first

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
