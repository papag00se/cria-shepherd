"""Scenario: recorded checker output from every ecosystem walks through the real parse/run seam.

Flows: `run_candidate` (empty argv, launch failure, timeout salvage) -> `parse_output`; then the
dependency-missing diagnosis (`dependency_missing`, `dependency_source_root`, `install_*`) over a real
tree on disk, and over a harness view that has not answered yet (three-valued: unknown is not absent).
"""
import pytest

from cria import probeparse as pp, wsview
from research_discovery_helpers import disk_view, surveyed, write  # noqa: F401

GRADLE = ("> Task :compileJava FAILED\n/w/src/main/java/App.java:7: error: cannot find symbol\n"
          "        Util.go();\n        ^\n  symbol:   variable Util\n  location: class App\n1 error\n"
          "FAILURE: Build failed with an exception.\n")
DOTNET = ("/w/Cart.cs(12,20): error CS0103: The name 'total' does not exist in the current context [/w/Cart.csproj]\n"
          "Build FAILED.\n")
GOVET = "# example.com/cart\n./cart.go:14:2: undefined: Total\nvet: ./cart.go:14:2: undefined: Total\n"
RUBYSYN = "/w/lib/a.rb:3: syntax error, unexpected end-of-input\n"
RSPEC = ("Failures:\n\n  1) Cart totals\n     Failure/Error: expect(total).to eq(5)\n       expected: 5\n            got: 4\n"
         "     # ./spec/cart_spec.rb:9:in `block (2 levels)'\n\n2 examples, 1 failure\n")
PYCOMPILE = ("*** Error compiling './a.py'...\n  File \"./a.py\", line 3\n    raise ValueError(\"x\"\n"
             "                    ^\nSyntaxError: '(' was never closed\n*** Error compiling './b.py'...\n"
             "  File \"./b.py\", line 1\n    x =\n")
NODECHECK = "/w/lib/a.js:4\nconst = 1;\n      ^\nSyntaxError: Unexpected token '='\n"


@pytest.mark.parametrize("tokens,code,out,kinds,tally", [
    (["gradle", "build"], 1, GRADLE, [("/w/src/main/java/App.java", 7)], ""),
    (["dotnet", "build"], 1, DOTNET, [("/w/Cart.cs", 12)], ""),
    (["go", "vet", "./..."], 2, GOVET, [("./cart.go", 14)], ""),
    (["rspec"], 1, RSPEC, [("./spec/cart_spec.rb", 9)], "1f/1p"),
    (["python3", "-m", "compileall", "."], 1, PYCOMPILE, [("./a.py", 3), ("./b.py", 1)], ""),
    (["node", "--check", "a.js"], 1, NODECHECK, [("/w/lib/a.js", 4)], ""),
    (["php", "-l", "a.php"], 255, "PHP Parse error: syntax error, unexpected '}' in /w/a.php on line 9\n", [("/w/a.php", 9)], ""),
    (["mypy", "."], 1, "app.py:5: error: Incompatible types in assignment\n", [("app.py", 5)], ""),
    (["vue-tsc", "--noEmit"], 2, "src/A.vue(4,2): error TS2304: Cannot find name 'x'.\n", [("src/A.vue", 4)], ""),
    (["cargo", "test"], 0, "test result: ok. 3 passed; 0 failed; 0 ignored\ntest result: ok. 2 passed; 0 failed\n", [], "0f/5p"),
    (["mocha"], 1, "  3 passing (9ms)\n  1 failing\n\n  1) x:\n     AssertionError: boom\n      at /w/t.js:5:1\n", [], "1f/3p"),
])
def test_recorded_output_per_ecosystem_is_located_by_the_right_parser(tokens, code, out, kinds, tally):
    """argv -> family -> parser: each ecosystem's own output yields its located findings and tally."""
    seen = []

    def runner(argv, cwd, timeout_s):
        seen.append((list(argv), cwd, timeout_s))
        return code, out, "", False

    res = pp.run_candidate(runner, tokens, "/w", 30.0)
    assert seen == [(tokens, "/w", 30.0)]
    assert [(f.file, f.line) for f in res.findings] == kinds
    assert res.tally == tally and res.exit_code == code


def test_launch_failure_empty_argv_and_timeout_salvage():
    """A missing binary / empty argv give an executor-failure result; a timeout keeps the partial findings."""
    assert pp.run_candidate(lambda *a: None, [], "/w", 5).summary == pp.EMPTY_COMMAND_SUMMARY

    def missing(argv, cwd, t):
        raise FileNotFoundError("no such tool: cargo")

    gone = pp.run_candidate(missing, ["cargo", "check"], "/w", 5)
    assert gone.exit_code is None and gone.findings == [] and "no such tool: cargo" in gone.summary
    cut = pp.run_candidate(lambda *a: (None, "src/p.rs:3:1: error: boom\n", "", True), ["gcc", "p.c"], "/w", 20.0)
    assert cut.summary.startswith("TIMEOUT after 20s") and [f.line for f in cut.findings] == [3]
    assert pp.timeout_summary(2.5).startswith("TIMEOUT after 2.5s")


@pytest.mark.parametrize("text,runner,tally", [
    ("Tests run: 5, Failures: 1, Errors: 1\nTests run: 3, Failures: 0, Errors: 0\n", "junit", "2f/6p"),
    ("12 tests completed, 2 failed\n", "gradle", "2f/10p"),
    ("Failed:     1, Passed:    12, Skipped:     0\n", "dotnet", "1f/12p"),
    ("Tests: 4, Assertions: 9, Failures: 1\n", "phpunit", "1f/3p"),
    ("  5 passed (5)\n Tests  5 passed (5)\n", "pytest", "0f/5p"),
    ("9 runs, 9 assertions, 0 failures, 0 errors, 0 skips\n", "minitest", "0f/9p"),
    ("--- PASS: TestA (0.00s)\n--- FAIL: TestB (0.00s)\n--- PASS: TestC (0.00s)\n", "go", "1f/2p"),
    ("ok  \texample.com/cart\t0.004s\n", "", ""),
    ("Ran 4 tests in 0.002s\n\nOK\n", "unittest", "4ran/OK"),
    ("Ran 4 tests in 0.002s\n\nFAILED (failures=1)\n", "unittest", "4ran/FAIL"),
    ("compiling...\n", "", ""),
])
def test_each_runners_own_tally_line_names_its_runner(text, runner, tally):
    assert pp.runner_and_tally(text) == (runner, tally)
    assert pp.runner_tally(text) == tally


def test_tally_counts_the_row_by_its_reading_and_refuses_malformed_groups():
    assert pp._tally_counts(pp._TALLY_FAILED_PASSED_ERRORS, ("2", "7", "1")) == (3, 7)
    assert pp._tally_counts(pp._TALLY_PASSED_FAILED, ("7", "2")) == (2, 7)
    assert pp._tally_counts(pp._TALLY_TOTAL_FAILED, ("3", "5", "")) == (5, 0)
    assert pp._tally_counts(pp._TALLY_TOTAL_FAILED, ("3",)) == (0, 3)
    assert pp._tally_counts(pp._TALLY_PASSED_FAILED, ("7",)) is None
    assert pp._tally_counts("zz", ("1", "2")) is None


@pytest.mark.parametrize("s,want", [
    ("src/a.rs:42:7", ("src/a.rs", 42, 7)),
    ("src/a.rs:42", ("src/a.rs", 42, None)),
    ("src/a.rs:42:abc", None),
    ("src/a.rs", None),
])
def test_split_loc_reads_file_line_col(s, want):
    assert pp.split_loc(s) == want


@pytest.mark.parametrize("text,want", [
    ("ModuleNotFoundError: No module named 'requests'", ("python", "requests")),
    ("cannot load such file -- countries (LoadError)", ("ruby", "countries")),
    ("Error: Cannot find module 'commander'", ("node", "commander")),
    ("Error: Cannot find module '@scope/pkg/sub'", ("node", "@scope/pkg/sub")),
    # ornith1.5_9b / handles-cli-node, real Codex 2026-11-01: `docker run image goose` -> node ran the argument as the script
    ("Error: Cannot find module '/usr/src/app/goose'", None), ("Error: Cannot find module './lib/handle-lookup'", None),
    ("Error: Cannot find module '../x'", None), ("Error: Cannot find module 'C:\\app\\goose'", None),
    ("error[E0463]: can't find crate for `toml`", ("rust", "toml")),
    ("no required module provides package example.com/dec; to add it:", ("go", "example.com/dec")),
    ("Could not resolve dependencies for project a:b:jar:1: org.x:csv:jar:1.9 was not found", ("java", "org.x:csv:jar:1.9")),
    ("PHP Fatal error: Failed opening required 'vendor/autoload.php'", ("php", "vendor/autoload.php")),
    ("Class 'Acme\\Cart' not found", ("php", "Acme\\Cart")),
    ("all good", None),
])
def test_dependency_missing_names_the_ecosystem_and_the_tools_own_name(text, want):
    assert pp.dependency_missing(text) == want


def test_dependency_facts_come_from_the_tree_on_disk(tmp_path, monkeypatch, disk_view):
    """Source roots, install evidence, flavour and shadow files are read off the real directory."""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    ws = tmp_path / "ws"
    ws.mkdir()
    root = str(ws)
    assert pp.dependency_source_root("go", root) == ""                       # every candidate asked, none there
    assert pp.dependency_source_root("klingon", root) == ""
    (home / "go/pkg/mod").mkdir(parents=True)
    assert pp.dependency_source_root("go", root) == str(home / "go/pkg/mod")
    write(ws, "node_modules/x/index.js", "1")
    assert pp.dependency_source_root("javascript", root) == str(ws / "node_modules")
    # install evidence: an empty `mkdir -p vendor` tree is not an install; a lock file is
    (ws / "vendor/bundle/gems/eu").mkdir(parents=True)
    assert pp.install_landed("ruby", root) is False
    assert pp.install_landed("klingon", root) is None and pp.install_landed("ruby", "") is None
    assert pp.install_flavour("ruby", root) == "install_dir"
    other = tmp_path / "bundled"
    write(other, "app/Gemfile.lock", "x")                    # one directory down, like `cargo new sub`
    assert pp.install_landed("ruby", str(other)) is True and pp.install_flavour("ruby", str(other)) == "bundler"
    assert pp.install_flavour("node", root) == ""
    write(ws, "vendor/bundle/gems/eu/lib/eu.rb", "")
    assert pp.install_landed("ruby", root) is True
    # a project's own file named by an import name, never a vendored copy or a bin/ executable
    write(ws, "lib/europe.rb", "")
    write(ws, "vendor/cache/bin/minitest", "")
    assert pp.resolves_to_workspace_file("europe/version", root) == "lib/europe.rb"
    assert pp.resolves_to_workspace_file("minitest/autorun", root) == ""
    assert pp.resolves_to_workspace_file("", root) == "" and pp.resolves_to_workspace_file("./", root) == ""
    assert pp.names_a_workspace_file(str(ws / "t.test.js"), root) is True
    assert pp.names_a_workspace_file("europe.version", root) is True
    assert pp.names_a_workspace_file("commons.csv", root) is False
    assert pp.names_a_workspace_file("...", root) is False


def test_an_unsurveyed_workspace_is_unknown_never_a_confident_no():
    """Before the harness answers, cria abstains (None / '' / True) rather than state a false fact."""
    view = surveyed("/work", ["F\t0\t1\ta.rb", "D\tvendor", "D\tvendor/bundle", "F\t0\t3\tvendor/bundle/x"])
    token = wsview.bind(view)
    try:
        assert pp.dependency_source_root("rust", "/work") is None          # `~` candidate not yet asked
        assert pp.dependency_source_root("python", "/work") is None
        assert pp.install_flavour("klingon", "/work") == ""
        assert pp.names_a_workspace_file("whatever", "/work") in (True, False)
    finally:
        wsview.unbind(token)
    bare = wsview.View("/work", "")
    token = wsview.bind(bare)
    try:
        assert pp.install_landed("ruby", "/work") is None
        assert pp.install_flavour("ruby", "/work") == ""
        assert pp.names_a_workspace_file("lib", "/work") is True            # unlisted: the safe direction
        assert pp.resolves_to_workspace_file("lib", "/work") == ""
    finally:
        wsview.unbind(token)


@pytest.mark.parametrize("cmd,token", [
    ("find ~/.cargo/registry/src -name value.rs", ""),
    ("find /home/u/.cargo/registry/src -name value.rs", "/home/u/.cargo/registry/src"),
    ("ls 'node_modules/x'", "node_modules/x"),
    ("grep -r foo node_modules", ""),
    ("find ./vendor/bundle", "./vendor/bundle"),
    ("ls src", ""),
])
def test_a_search_of_a_package_cache_names_the_token_it_searched(cmd, token):
    got = pp.searched_for_dependency_source(cmd)
    assert got == token or (token == "" and got == "")
    assert pp.searched_under("/r/a/b", "/r/a") and not pp.searched_under("/r/ab", "/r/a") and not pp.searched_under("", "/r")
    assert pp.continues_previous("    have (int)", "x.go:1:1: bad") and not pp.continues_previous("", "x")
