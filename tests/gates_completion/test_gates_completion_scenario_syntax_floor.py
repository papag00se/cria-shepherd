"""The syntax floor over a real tree: sources are found (generated trees are skipped, and NAMED in the clean verdict), the
interpreter's recorded complaint becomes the coder's nudge, and a missing tool is an abstention, never a failure."""
import pytest

from cria import linterprobe as lp
from gates_completion_helpers import gates_completion_view  # noqa: F401

PYC = ("  File \"app/cart.py\", line 3\n    def total(:\n              ^\nSyntaxError: invalid syntax\n")
JSC = "web/cart.js:7\n  const = 1;\n        ^\nSyntaxError: Unexpected token '='\n"


@pytest.fixture
def tree(tmp_path):
    for rel, body in {"app/cart.py": "def total(:\n", "app/util.py": "x = 1\n", "web/cart.js": "const = 1;\n", "web/ok.mjs": "export {}\n",
                      "venv/pyvenv.cfg": "home = /usr/bin\n", "venv/lib/site.py": "x=\n", "node_modules/.package-lock.json": "{}", "node_modules/dep/i.js": "(\n",
                      "README.md": "hi"}.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body)
    return tmp_path


def runner(py=(0, "", ""), flakes=(0, "", ""), node=(0, "", ""), seen=None):
    def run(argv, cwd, timeout):
        seen is not None and seen.append(argv)
        spec = {"py_compile": py, "pyflakes": flakes, "--check": node}[next(k for k in ("py_compile", "pyflakes", "--check") if k in argv)]
        if isinstance(spec, Exception):
            raise spec
        return spec[0], spec[1], spec[2], False
    return run


def test_the_floor_reads_only_real_sources_and_turns_the_interpreters_words_into_a_nudge(tree):
    seen = []
    report = lp.run_linter_probe(str(tree), runner(py=(1, "", PYC), node=(1, "", JSC), seen=seen))
    assert [a[:3] for a in seen if a[0] == "python3"] == [["python3", "-m", "py_compile"]] and "pyflakes" not in str(seen)   # a parse error is not escalated
    py = next(a for a in seen if a[0] == "python3")
    assert py[3:] == [str(tree / "app/cart.py"), str(tree / "app/util.py")]                                    # no venv, no node_modules
    assert sorted(a[2] for a in seen if a[0] == "node") == [str(tree / "web/cart.js"), str(tree / "web/ok.mjs")]
    assert not report.is_clean() and [f.language for f in report.failing()] == ["python", "javascript"]
    nudge = report.nudge_text()
    assert "SyntaxError: invalid syntax" in nudge and "Unexpected token '='" in nudge and nudge.index("python") < nudge.index("javascript")
    digest = report.probe_digest()
    assert "• python (py_compile):" in digest and "• javascript (node --check):" in digest
    assert [d.split()[0] for d in report.skipped_dirs] == ["node_modules", "venv"]


@pytest.mark.parametrize("kw,clean,words,skipped", [
    ({}, True, "venv", []),                                                                          # clean, and honest about what it never opened
    ({"flakes": (1, "", "app/util.py:1: undefined name 'y'\n")}, False, "undefined name 'y'", []),   # parse passes, pyflakes objects
    ({"flakes": (1, "", "/usr/bin/python3: No module named pyflakes\n")}, True, "", []),             # the linter is absent: abstain
    ({"py": FileNotFoundError("python3")}, True, "", ["python"]), ({"node": FileNotFoundError("node")}, True, "", ["javascript"]),
    ({"py": PermissionError("denied"), "node": OSError("boom")}, True, "", ["python"])])
def test_an_absent_or_broken_tool_abstains_and_only_a_real_diagnosis_blocks(tree, kw, clean, words, skipped):
    report = lp.run_linter_probe(str(tree), runner(**kw))
    assert report.is_clean() is clean and report.skipped == skipped and words in (report.probe_digest() if clean else report.nudge_text())


def test_an_empty_workspace_has_no_objection_and_says_so(tmp_path):
    report = lp.run_linter_probe(str(tmp_path), runner())
    assert report.is_clean() and report.nudge_text() is None and report.findings == [] and report.probe_digest()
    assert lp._text(b"caf\xc3\xa9\xff") == "caf\u00e9\ufffd" and lp._text(None) == ""
