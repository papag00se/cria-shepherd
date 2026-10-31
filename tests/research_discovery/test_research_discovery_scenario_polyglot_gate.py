"""The completion gate over a polyglot workspace (Maven + Gradle + npm/tsc + cargo + go + python + ruby, real manifests on
disk): discovery composes each ecosystem's checks, a fake process runner returns RECORDED checker output (the only fake),
and the report says what failed where, what did not run, and what never verified."""
import pathlib
from unittest import mock

import pytest

from cria import proberun, wsview
from cria.probediscovery import ProbeKind

FILES = {
    "api/pom.xml": "<project><modelVersion>4.0.0</modelVersion><artifactId>api</artifactId></project>",
    "api/src/main/java/pipeline/Importer.java": "package pipeline; public class Importer {}",
    "gr/build.gradle": "plugins { id 'java' }\n", "gr/src/main/java/G.java": "class G {}",
    "web/package.json": '{"name":"web","scripts":{"test":"node --test"}}', "web/tsconfig.json": "{}", "web/src/app.ts": "export const x: number = 'a';",
    "cli/Cargo.toml": '[package]\nname="cli"\nversion="0.1.0"\n', "cli/src/lib.rs": "pub fn add(a:i32,b:i32)->i32{a+b}\n",
    "svc/go.mod": "module svc\n\ngo 1.22\n", "svc/main.go": "package main\nfunc main(){}\n",
    "py/pyproject.toml": "[project]\nname='py'\n", "py/app.py": "def f(:\n", "py/tests/test_app.py": "def test_a(): pass\n",
    "rb/Gemfile": "source 'https://rubygems.org'\ngem 'minitest'\n", "rb/lib/r.rb": "module R; end\n", "rb/test/test_r.rb": "require 'minitest/autorun'\n"}
COMPILE_ERR = ("*** Error compiling './app.py'...\n  File \"./app.py\", line 1\n    def f(:\n          ^\nSyntaxError: invalid syntax\n")
MVN = ("[ERROR] COMPILATION ERROR : \n[ERROR] /w/api/src/main/java/pipeline/Importer.java:[5,19] cannot find symbol\n"
       "  symbol:   class CSVRecord\n[ERROR] -> [Help 1]\n")
RUSTC = "error[E0308]: mismatched types\n --> src/lib.rs:1:32\n  |\n1 | pub fn add(a:i32,b:i32)->i32{a+b}\n"
GO = "# svc\n./main.go:2:20: undefined: boot\n"
TSC = "src/app.ts(1,14): error TS2322: Type 'string' is not assignable to type 'number'.\n"
PYTEST_EMPTY = "no tests ran in 0.01s\n"
MINITEST_OK = "Finished in 0.001s, 100 runs/s.\n\n1 runs, 1 assertions, 0 failures, 0 errors, 0 skips\n"


def recorded(argv, cwd, timeout):
    """(exit, stdout, stderr, timed_out) a real machine printed for each composed command."""
    cmd = " ".join(argv)
    if "compileall" in cmd:
        return 1, COMPILE_ERR, "", False
    if argv[:2] == ["mvn", "-q"]:
        return 1, MVN, "", False
    if argv[:2] == ["cargo", "check"]:
        return 101, "", RUSTC, False
    if argv[:2] == ["go", "build"]:
        return 1, "", GO, False
    if argv[0] == "npm":
        return 2, TSC, "", False
    if argv[0] == "gradle":
        return 124, "> Task :compileJava\n", "", True            # killed at the deadline, no verdict
    if argv[:2] == ["cargo", "test"]:
        raise FileNotFoundError(2, "No such file or directory: 'cargo'")
    if argv[:3] == ["python3", "-m", "pytest"]:
        return 5, PYTEST_EMPTY, "", False
    if argv[0] == "ruby" and "-e" in argv:
        return 0, MINITEST_OK, "", False
    if argv[0] == "pyflakes":
        return 1, "py/app.py:3: 'os' imported but unused\n", "", False
    return 0, "", "", False


def run_gate(root, timeout_s=90):
    """The gate as production runs it: select the probes, take the harness shell tool's result for each composed
    command (exit code + merged output; 124 = killed by `timeout`, 127 = could not launch) and interpret it."""
    selected = proberun.select_completion_probes(root)
    results = []
    for c in selected:
        try:
            code, out, err, timed_out = recorded(list(c.command), str(c.working_dir), timeout_s)
        except OSError:
            code, out, err, timed_out = proberun.NOT_FOUND_EXIT_CODE, "", "", False
        results.append(proberun.interpret_probe_output(
            c, proberun.display_command(c.command), out + err, proberun.TIMEOUT_EXIT_CODE if timed_out else code, timeout_s))
    return proberun.ProbeReport(selected=selected, results=results)


@pytest.fixture
def workspace(tmp_path):
    for rel, body in FILES.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body)
    token = wsview.bind(wsview.DirectView())
    with mock.patch.object(proberun, "program_is_installed", lambda c: True):
        yield tmp_path
    wsview.unbind(token)


def test_every_ecosystem_is_checked_and_each_failure_is_located_in_the_checkers_own_words(workspace):
    report = run_gate(str(workspace))
    heads = {c.command[0] for c in report.selected}
    assert {"mvn", "gradle", "npm", "cargo", "go", "ruby", "pyflakes", "python3"} <= heads
    where = {(f.file.rsplit("/", 1)[-1], f.line) for r in report.results for f in r.findings}
    assert {("app.py", 1), ("Importer.java", 5), ("lib.rs", 1), ("main.go", 2), ("app.ts", 1)} <= where
    assert proberun.syntax_floor_clean(report) is False and proberun.gate_ran_tests(report)   # the ruby suite really ran

    nudge = proberun.completion_block_nudge(report)
    assert nudge.index("compileall") < nudge.index("mvn")                          # the syntax floor leads
    for words in ("SyntaxError: invalid syntax", "cannot find symbol", "mismatched types", "undefined: boot", "not assignable to type 'number'"):
        assert words in nudge
    assert "imported but unused" not in nudge                                      # an advisory lint line is not a block
    assert "$ gradle check — TIMEOUT after 90s" in nudge                           # ran, never finished: not clean

    unran = proberun.unran_probes(report)
    assert [u.split(" — ")[0] for u in unran] == ["$ gradle check (BuildCheck)", "$ cargo test --no-fail-fast (Test)"]
    assert "TIMEOUT after 90s" in unran[0] and proberun.PROXY_LAUNCH_DETAIL in unran[1]   # a timeout and a launch failure: both missing signal
    digest = proberun.completion_probe_digest(report, missing=["go vet ./..."]).splitlines()
    assert digest[0] == "SYNTAX FLOOR: parse/syntax issues found" and digest[1].endswith("go vet ./...")
    row = lambda head: next(ln for ln in digest if ln.startswith(head))
    assert "UNFINISHED" in row("$ gradle check") and "TIMEOUT after 90s" in row("$ gradle check") and "did NOT launch (tool missing?)" in row("$ cargo test")
    assert "no tests collected (nothing to run — not a failure)" in row("$ python3 -m pytest")
    assert "exit 0 (ran clean) — no problems reported — 0 structured finding(s)" in row("$ go build -mod") + row("$ go vet")
    assert [f.split(" — ")[0] for f in proberun.failed_unparsed_probes(report)] == []     # the unlocated non-pass (gradle) is unran, not failed: no exit code
    assert proberun.completion_block_nudge(proberun.ProbeReport()) is None and proberun.completion_probe_digest(proberun.ProbeReport()).endswith(proberun.DIGEST_NO_PROBES)


def test_a_launch_failure_and_an_empty_command_are_results_not_crashes(workspace):
    c = next(c for c in proberun.select_completion_probes(str(workspace)) if c.kind is ProbeKind.BuildCheck)
    joined = proberun.display_command(c.command)
    for code in proberun.LAUNCH_FAILURE_EXIT_CODES:     # 125/126/127: the shell could not launch the checker
        r = proberun.interpret_probe_output(c, joined, "sh: 1: nope: Permission denied\n", code, 5)
        assert r.exit_code is None and proberun.PROXY_LAUNCH_DETAIL in r.summary and r.findings == []
    gone = proberun.interpret_probe_output(c, joined, "sh: 1: cargo: command not found\n", None, 5)   # text only, no sentinel
    assert gone.exit_code is None and proberun.LAUNCH_FAILURE_MARKER in gone.summary
    empty = type(c)(**{**c.__dict__, "command": []})
    assert proberun.interpret_probe_output(empty, "", "", 0, 5).summary == proberun.EMPTY_COMMAND_SUMMARY
