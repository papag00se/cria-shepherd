"""Wave 9 coverage: what each ecosystem's runner output proves it reached, walked through `participation.observe`.

Legacy candidates (no ecosystem provenance) are recognised from argv; Rust/Go-less `Running`/`Compiling` lines name
test binaries, sources and build targets; JS prints PASS/FAIL file lines; Python/PHP/Ruby/JS argv lists enumerate
source files; Elixir and .NET carry compile counts and `proj -> dll` targets. A launch failure takes none of it.
"""
from pathlib import Path

import pytest
from cria import participation as pt, probediscovery as pd

E, K = pd.Ecosystem, pd.ProbeKind


def cand(command, kind=K.Test, eco=None, **extra):
    c = pd.ProbeCandidate(kind, command.split(), Path("/workspace"), 90, 90, pd.ProbeCost.Moderate, False, False, False,
                          "fixture", ecosystem=eco)
    for k, v in extra.items(): object.__setattr__(c, k, v)
    return c


@pytest.mark.parametrize("command,eco", [
    ("npx jest", E.JsTs), ("tsc --noEmit", E.JsTs), ("cargo build", E.Rust), ("rustc a.rs", E.Rust), ("go vet ./...", E.Go),
    ("./gradlew build", E.Jvm), ("dotnet build", E.DotNet), ("vendor/bin/phpunit", E.Php), ("composer test", E.Php),
    ("bundle exec rspec", E.Ruby), ("mix compile", E.Elixir), ("tox -e py", E.Python), ("python3 -m pyflakes a.py", E.Python),
    ("make check", None), ("python3 script.py", None), ("", None),
])
def test_a_legacy_candidate_is_placed_in_its_ecosystem_by_argv_and_unknown_tools_stay_unplaced(command, eco):
    assert pt.ecosystem_for(cand(command)) is eco


def phases(command, output, code, kind=K.Test, eco=None, **extra):
    e = pt.observe(cand(command, kind, eco, **extra), output, code)
    return e


def test_rust_names_test_binaries_sources_and_build_targets_it_actually_ran():
    out = ("   Compiling cart v0.1.0 (/w)\n     Running unittests src/lib.rs (target/debug/deps/cart-abc)\n"
           "     Running tests/billing.rs (target/debug/deps/billing-1)\n     Running target/debug/deps/other\n"
           "test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n")
    e = phases("cargo test", out, 0, eco=E.Rust)
    assert e.test.participants == ("tests/billing.rs",) and e.test.participated is True and e.test.passed is True
    assert e.source.participants == ("src/lib.rs",) and e.source.participant_kind == "file"
    assert e.build.participants == ("cart",) and e.build.participant_kind == "target"
    dead = phases("cargo test", out, 127, eco=E.Rust)                     # a launch failure borrows none of the plausible output
    assert dead.test.participants is None and dead.build.participants is None


def test_jest_pass_fail_file_lines_name_the_test_files_and_node_argv_names_sources():
    out = "PASS src/cart.test.ts\nFAIL src/io.spec.js\nTests: 1 failed, 1 passed, 2 total\n"
    e = phases("npx jest", out, 1, eco=E.JsTs)
    assert e.test.participants == ("src/cart.test.ts", "src/io.spec.js") and e.test.passed is False
    s = phases("node --check src/a.js src/b.mjs", "", 0, K.SyntaxCheck, E.JsTs)
    assert s.source.participants == ("src/a.js", "src/b.mjs") and s.source.participants_complete is True and s.source.passed is True


@pytest.mark.parametrize("eco,command,files", [
    (E.Python, "python3 -m py_compile a.py b.py", ("a.py", "b.py")), (E.Php, "php -l a.php", ("a.php",)),
    (E.Ruby, "ruby -c a.rb", ("a.rb",)),
])
def test_an_argv_that_lists_source_files_is_the_complete_input_list(eco, command, files):
    e = phases(command, "", 0, K.SyntaxCheck, eco)
    assert (e.source.participants, e.source.participants_complete, e.source.passed) == (files, True, True)


def test_compileall_inputs_are_only_the_ones_discovery_enumerated_and_may_be_incomplete():
    e = phases("python3 -m compileall -q .", "", 0, K.SyntaxCheck, E.Python,
               participation_inputs=("a.py",), participation_inputs_complete=False)
    assert (e.source.participants, e.source.participants_complete) == (("a.py",), False)
    assert phases("python3 -m compileall -q .", "", 0, K.SyntaxCheck, E.Python).source.participants is None


def test_elixir_compile_counts_and_dotnet_project_targets():
    ex = phases("mix compile", "Compiling 3 files (.ex)\nCompiling 2 files (.ex)\nGenerated cart app\n", 0, K.BuildCheck, E.Elixir)
    assert (ex.source.count, ex.source.participated, ex.source.passed) == (5, True, True)
    none = phases("mix compile", "Compiling 0 files (.ex)\n", 0, K.BuildCheck, E.Elixir)
    assert (none.source.participated, none.source.passed) == (False, None)
    dn = phases("dotnet build", "  Cart.csproj -> /w/bin/Cart.dll\n  Cart.Tests.csproj -> /w/bin/T.dll\nBuild succeeded.\n", 0, K.BuildCheck, E.DotNet)
    assert dn.build.participants == ("Cart.csproj", "Cart.Tests.csproj") and dn.build.participant_kind == "target"
    assert phases("dotnet build", "  Cart.csproj -> /w/bin/Cart.dll\n", 127, K.BuildCheck, E.DotNet).build.participants is None


def test_a_runner_tally_without_a_pass_count_and_a_named_skip_count_are_read_as_such():
    ok = phases("python3 -m unittest", "Ran 3 tests in 0.01s\n\nOK\n", 0, eco=E.Python)
    assert (ok.test.participated, ok.test.count) == (True, 3)
    sk = phases("python3 -m pytest -q", "2 passed, 3 skipped in 0.1s\n", 0, eco=E.Python)
    assert sk.test.skipped_count == 3
