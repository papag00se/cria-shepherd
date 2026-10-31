"""What the model reads of a gate: the checker's own voice, states named from measured exit codes, and cria never speaks over a tool."""
import pathlib

import pytest

from cria import probediscovery, probegate
from cria.probediscovery import ProbeKind as K
from gates_completion_helpers import gates_completion_view, cand, clean, deliver, new_plan, sec  # noqa: F401

UNUSED = "a.py:1: 'os' imported but unused\na.py:2: 'sys' imported but unused"
ECHO = "t.py:9: in test_totals\n    unused_variable = compute()  # unused variable\nE   AssertionError: 3 != 4"


def test_a_clean_check_shows_its_exact_output_command_and_exit_never_an_authored_verdict():
    """Clean checks retain evidence, not a success verdict: whitespace and a 4000-line log survive, silence says 'no output'."""
    mvn = "[INFO] No tests to run.\n[INFO] BUILD SUCCESS\n  checker-specific detail  \n"
    big = "".join(f"  record {i}: evidence  \n" for i in range(4000))
    shown = clean(sec(0, mvn), new_plan(candidates=[cand(["mvn", "test"])]))
    assert mvn in shown and "mvn test" in shown and "exit 0" in shown and clean(sec(0, big)).count("record ") == 4000
    quiet = clean(sec(0, ""))
    assert "exit 0" in quiet and "no output" in quiet
    assert all("no error-class problems" not in s for s in (shown, quiet))


@pytest.mark.parametrize("kind,raw,code,present,absent", [
    (K.Test, UNUSED, 1, ["printed no parseable location"], []),                       # -Werror / deny(warnings): a failing TEST is a failure
    (K.Lint, UNUSED, 1, ["2 advisory line(s)"], ["printed no parseable location"]),    # ...a lint's unused names are advisory
    (K.Test, "..\ntest_x::polls_forever", 124, ["`pytest -q` did not finish (timed out)", "test_x::polls_forever"], ["error-class"]),
    (K.Test, "bash: pytest: command not found", 127, ["no usable result"], ["error-class", "FAILED"]),
    (K.Test, "no tests ran in 0.01s", 5, ["exit 5", "no tests ran"], ["error-class"]),
    (K.Test, ECHO, 1, ["unused_variable = compute()", "AssertionError: 3 != 4"], []),       # the code echo is not a diagnostic about code
], ids=["hard-test-fails", "lint-advisory", "timeout", "launch-failure", "no-tests-exit5", "source-echo-kept"])
def test_state_comes_from_the_measured_exit_code_and_only_the_checkers_own_lines_are_filtered(kind, raw, code, present, absent):
    """Test-kind non-zero exits are real failures whatever the text looks like (`_is_hard_failure` once never fired: -Werror
    builds read green); 124/127 are 'could not finish/run', never a fix demand; a traceback's source echo is not deleted for its words."""
    out = clean(sec(0, raw, code), new_plan(candidates=[cand(["pytest", "-q"], kind=kind)]))
    assert all(p in out for p in present) and not any(a in out for a in absent)


def test_the_offline_rerun_is_an_instrument_reading_never_a_finding():
    """The same suite with the network removed is SUPPOSED to fail on a live suite; scraping it told the coder to fix passing tests."""
    offline = f"{probegate.SECTION_PREFIX}offline{probegate.SECTION_SUFFIX}\nFAILED tests/t.py::test_live - ConnectionError\nEXIT:1\n"
    out = clean(sec(0, "3 passed in 0.1s") + offline, new_plan(candidates=[cand(["pytest", "-q"])]))
    assert "ConnectionError" not in out and "error-class" not in out and "exit 0" in out


def test_a_real_error_in_one_section_is_never_masked_by_a_launch_failure_or_a_passing_sibling():
    plan = new_plan(candidates=[cand(["a"]), cand(["pytest"])])
    for first in (sec(0, "bash: x: command not found", 127), sec(0, "3 passed in 0.1s")):
        out = clean(first + sec(1, "t.py:3: NameError: name 'q' is not defined", 1), new_plan(candidates=plan.candidates))
        assert "t.py:3: NameError" in out


def test_a_gate_that_lost_a_section_or_its_exit_is_a_gap_never_a_pass():
    """A truncated gate used to read clean: a selected check whose section never came back is `unran` and the gate partial;
    a header with no EXIT sentinel is 'did not finish'; no markers at all means nothing ran."""
    plan = new_plan(candidates=[cand(["pytest", "-q"]), cand(["pyflakes"])])
    out = probegate.interpret_gate(deliver(plan, sec(0, "3 passed")), "")
    assert out.ran and out.unran == ["pyflakes"] and probegate.gate_is_partial(out)
    assert "did not finish" in clean(f"{probegate.SECTION_PREFIX}probe-0{probegate.SECTION_SUFFIX}\nsome out\n")
    assert not probegate.interpret_gate(deliver(new_plan(), "PROBE_EXIT=0 old-style"), "").ran


def write(root, rel, text):
    path = pathlib.Path(root, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return str(path)


@pytest.mark.parametrize("finding,present,absent", [
    ("Importer.java:[154,43] cannot find symbol", "line 154: `while ((cols = r.next()) != null) {`", ""),         # maven's bracket coordinate
    ("main.go:4:2: not enough arguments in call to foo\n\thave (number)", "have (number)\n  the flagged line on disk — line 4: `foo(1)`", ""),                         # quote follows the whole diagnostic
    ("main.go:4: panic: runtime error: index out of range", "", "the flagged line on disk"),                    # a raise site is not a defect site
    ("main.go:4: AssertionError: 42.5 != 17.5", "", "the flagged line on disk"),
    ("nowhere.go:4: undefined: foo", "", "the flagged line on disk"),                                            # missing file: silence
    ("main.go:4:2: not enough arguments in call to foo `foo(1)`", "", "the flagged line on disk"),               # already quotes its line
], ids=["maven-coordinate", "continuation-stays-whole", "panic", "assertion", "missing-file", "already-quoted"])
def test_the_flagged_line_is_quoted_after_a_whole_diagnostic_only_where_the_line_is_the_defect(tmp_path, finding, present, absent):
    """feed-pipeline-java call 0161 / go: a linter's flagged line IS the defect (quote it, after the checker's whole message);
    a runtime failure's line is only where it stopped, so cria makes no pointer it cannot justify."""
    write(tmp_path, "Importer.java", "\n".join(["//"] * 153 + ["while ((cols = r.next()) != null) {"]) + "\n")
    write(tmp_path, "main.go", "package main\n\nfunc main() {\n\tfoo(1)\n}\n")
    out = clean(sec(0, finding, 1), new_plan(workspace=str(tmp_path), candidates=[cand(["go", "vet"])]))
    assert present in out and (not absent or absent not in out)


def test_a_green_gate_whose_checks_all_ran_in_a_subdirectory_says_so_and_stranded_tests_are_named(tmp_path):
    """rust-toml-cli x gemma4 cell 6: the project was built one level down, every probe ran there, the gate went green and the
    verifier at the root found no Cargo.toml (0 of 4): the plan's working_dir is told. maple run 2: exit-5 beside a stranded
    test file is named as AUTHORED metadata, not checker output."""
    write(tmp_path, "toml-cli/Cargo.toml", '[package]\nname="x"\nversion="0.1.0"\n')
    write(tmp_path, "toml-cli/src/main.rs", "fn main(){}\n")
    plan = probegate.plan_gate(str(tmp_path))
    assert plan.ran_in == "toml-cli"
    green = clean(sec(0, "ok"), new_plan(workspace=str(tmp_path), ran_in="toml-cli", candidates=[cand(["cargo", "check"])]))
    assert "inside `toml-cli`" in green and "cria" not in green.lower()
    assert "toml-cli" not in clean(sec(0, "ok"), new_plan(workspace=str(tmp_path), candidates=[cand(["cargo", "check"])]))
    write(tmp_path, "pytest_da_resolvers.py", "def test_resolve():\n    assert 1\n")
    write(tmp_path, "test_live.py", "def test_live():\n    assert 1\n")
    stranded = new_plan(workspace=str(tmp_path), candidates=[cand(["pytest", "-q"])], untested=probediscovery.undiscoverable_tests(str(tmp_path)))
    out = clean(sec(0, "no tests ran in 0.01s", 5), stranded)
    native, sep, observed = out.partition("Automatic discovery observations (authored metadata, not checker output):")
    assert sep and "pytest_da_resolvers.py" in observed and "pytest_da_resolvers.py" not in native
