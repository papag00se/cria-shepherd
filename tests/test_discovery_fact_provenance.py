"""Discovery is a default naming observation, never a native checker diagnosis."""
import os
import subprocess
import sys

import pytest

from cria import probediscovery as pd, probegate as pg, wsview
from tests.gatefixture import completed


def tree(tmp_path, files):
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return tmp_path


def render(plan, *sections, **kwargs):
    raw = "".join(f"{pg.SECTION_PREFIX}probe-{i}{pg.SECTION_SUFFIX}\n{body}\n"
                  + (f"EXIT:{code}\n" if code is not None else "")
                  for i, (body, code) in enumerate(sections))
    return pg.clean_gate_output(raw, completed(plan, raw), **kwargs)


@pytest.mark.parametrize("neighbor", [False, True])
def test_default_naming_observation_does_not_deny_explicit_execution(tmp_path, neighbor):
    files = {"checks.py": "def test_works():\n    assert True\n"}
    if neighbor:
        files["test_neighbor.py"] = "def test_neighbor():\n    assert True\n"
    root = tree(tmp_path, files)
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "checks.py"],
                            cwd=root, capture_output=True, text=True,
                            env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    automatic = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                               cwd=root, capture_output=True, text=True,
                               env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
    assert automatic.returncode == (0 if neighbor else 5), automatic.stdout + automatic.stderr
    assert ("1 passed" if neighbor else "no tests ran") in automatic.stdout
    for observations in (pd.stranded_test_sentences(root), pd.undiscoverable_tests(root)):
        assert len(observations) == 1
        assert "checks.py" in observations[0]
        assert "default" in observations[0].lower()
        assert "only runs" not in observations[0]
        assert "will not run:" not in observations[0]
    plan = pg.plan_gate(str(root))
    # A successful explicit invocation cannot be turned into a native failure by cached naming facts.
    out = render(plan, (result.stdout, 0))
    assert result.stdout.strip() in out
    assert "report these error-class problems" not in out


@pytest.mark.parametrize("zero,code", [("no tests ran in 0.01s", 5),
                                       ("?   example.com/x [no test files]", 0)])
@pytest.mark.parametrize("sibling", [None, ("broken.py:3: SyntaxError: invalid syntax", 1),
                                      ("", 1), ("still running", 124), ("", 127),
                                      ("partial checker output", None)])
def test_zero_native_evidence_and_authored_metadata_keep_separate_channels(tmp_path, zero, code, sibling):
    root = tree(tmp_path, {"checks.py": "def test_ok():\n    assert True\n"})
    plan = pg.plan_gate(str(root))
    sections = [(zero, code)] + ([sibling] if sibling else [])
    out = render(plan, *sections)
    assert zero in out  # native zero collection survives every return priority
    assert "checks.py" in out
    assert "authored metadata, not checker output" in out
    native = out.partition("Native checker diagnostics:\n")[2].split("Automatic discovery observations", 1)[0]
    assert "checks.py" not in native
    if sibling and sibling[1] == 1 and sibling[0]:
        assert sibling[0] in native
    else:
        assert "report these error-class problems" not in out


def test_no_default_matches_is_not_a_universal_execution_requirement(tmp_path):
    root = tree(tmp_path, {"app.py": "value = 1\n"})
    observation, = pd.undiscoverable_tests(root)
    assert "default" in observation.lower()
    assert "must" not in observation
    out = render(pg.plan_gate(str(root)), ("no tests ran in 0.01s", 5))
    assert "no tests ran in 0.01s" in out
    assert "app.py" not in " ".join(pd.stranded_test_sentences(root))


def test_unknown_body_and_conftest_do_not_invent_stranded_tests(tmp_path):
    root = tree(tmp_path, {"app.py": "value = 1\n", "conftest.py": "import pytest\n"})
    assert pd.stranded_test_sentences(root) == []
    view = wsview.current()
    original = view.read
    # The same production reader's unknown state is not evidence of test code.
    from unittest.mock import patch
    with patch.object(view, "read", side_effect=lambda p: None if str(p).endswith("app.py") else original(p)):
        assert pd.stranded_test_sentences(root) == []


def test_configured_discovery_is_not_overruled(tmp_path):
    root = tree(tmp_path, {"checks.py": "def test_ok():\n    assert True\n",
                           "pytest.ini": "[pytest]\npython_files = checks.py\n"})
    assert pd.stranded_test_sentences(root) == []
    assert pd.undiscoverable_tests(root) == []
    out = render(pg.plan_gate(str(root)), ("no tests ran in 0.01s", 5))
    assert "no tests ran in 0.01s" in out
    assert "checks.py" not in out


def test_changed_or_different_file_success_does_not_erase_zero_evidence(tmp_path):
    root = tree(tmp_path, {"checks.py": "def test_ok():\n    assert True\n",
                           "test_neighbor.py": "def test_neighbor():\n    assert True\n"})
    plan = pg.plan_gate(str(root))
    out = render(plan, ("no tests ran in 0.01s", 5), ("1 passed in 0.01s", 0),
                 changed_paths=frozenset({"checks.py"}), checks_reran=True)
    assert "no tests ran in 0.01s" in out
    assert "1 passed in 0.01s" in out
    assert "default" in out.lower()


@pytest.mark.parametrize("config_state", ["unread", "unknown"])
@pytest.mark.parametrize("sibling", [("native.py:3: SyntaxError: broken", 1), ("waiting", 124), ("", 127)])
def test_unknown_config_keeps_zero_native_evidence_without_naming_claim(tmp_path, monkeypatch, config_state, sibling):
    root = tree(tmp_path, {"checks.py": "def test_ok():\n    assert True\n", "pytest.ini": "[pytest]\n"})
    view = wsview.current()
    original_read, original_exists = view.read, view.exists
    monkeypatch.setattr(view, "read", lambda p: None if str(p).endswith("pytest.ini") else original_read(p))
    if config_state == "unknown":
        monkeypatch.setattr(view, "exists", lambda p: None if str(p).endswith("pytest.ini") else original_exists(p))
    assert pd.stranded_test_sentences(root) == []
    out = render(pg.plan_gate(str(root)), ("no tests ran in 0.01s", 5), sibling)
    assert "no tests ran in 0.01s" in out
    assert "checks.py" not in out
    assert "outside default" not in out


def test_non_python_scope_and_raw_diagnostic_indentation(tmp_path):
    root = tree(tmp_path, {"resolver_tests.go": "package main\nfunc TestResolve() {}\n"})
    observation, = pd.stranded_test_sentences(root)
    assert "default" in observation.lower()
    assert "*_test.go" in observation
    diagnostic = "resolver.go:4: undefined: missing\n    missing()"
    out = render(pg.plan_gate(str(root)), ("? example.com/x [no test files]", 0), (diagnostic, 1))
    assert diagnostic in out
    assert "[no test files]" in out
    assert "resolver_tests.go" in out
    assert "authored metadata, not checker output" in out
