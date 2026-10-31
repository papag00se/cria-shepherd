"""Structural invariants of the code layout: import graph, facades, collection, installable wheel."""
import ast
import importlib.util
import os
import subprocess
import sys
import types
import zipfile
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

import pytest

from cria import (callformats, callliterals, callsyntax, filecommands, massage, outboundpolicies,
                  outputpolicies, probegate, resultnotes, toolwire, writeproxy)

ROOT = Path(__file__).resolve().parents[2]
CRIA = ROOT / "cria"

def import_graph(root=CRIA):
    graph = {}
    for f in sorted(root.glob("*.py")):
        edges = set()
        for n in ast.walk(ast.parse(f.read_text())):
            mod = getattr(n, "module", None) or ""
            if isinstance(n, ast.ImportFrom) and (n.level == 1 and not mod or mod == "cria"):
                edges.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom) and (n.level == 1 or mod.startswith("cria.")):
                edges.add(mod.split(".")[0 if n.level else 1])
            elif isinstance(n, ast.Import):
                edges.update(a.name.split(".")[1] for a in n.names if a.name.startswith("cria."))
        graph[f.stem] = edges
    return graph

def cycle(graph):
    try:
        TopologicalSorter(graph).prepare()
    except CycleError as e:
        return e.args[1]

def test_import_graph_is_acyclic():
    """groundtruth once imported the 8,000-line loop driver for one regex, from inside a function body."""
    assert cycle(import_graph()) is None

def test_edge_collector_sees_every_import_spelling_at_any_depth_without_inventing_cycles(tmp_path):
    for stmt in ["from cria import b as x", "from cria.b.deep import v", "import cria.b as x", "from . import b", "from .b import v",
                 "def f():\n    from cria import b", "if TYPE_CHECKING:\n    from cria.b import v"]:
        (tmp_path / "a.py").write_text(stmt + "\n")
        (tmp_path / "b.py").write_text("from . import a\n")
        assert import_graph(tmp_path) == {"a": {"b"}, "b": {"a"}} and cycle(import_graph(tmp_path)), stmt
    (tmp_path / "a.py").write_text("import cria\nimport external.b\nfrom cria_extra.b import v\n")
    assert cycle(import_graph(tmp_path)) is None and cycle({"a": {"b", "c"}, "b": {"d"}, "c": {"d"}, "d": set()}) is None
    assert cycle({"a": {"a"}})

FACADES = {massage: (callsyntax, callformats, callliterals, outputpolicies),
           writeproxy: (callliterals, filecommands, toolwire, resultnotes, outboundpolicies), probegate: (toolwire,)}
ADAPTERS = {"promote_call", "_under_spill_dir", "_spill_relpath", "_respill_command", "_spill_read_command"}  # wrap, by design

def test_tool_helper_facades_re_export_their_owners_objects():
    """Pure helpers have ONE owner: a facade name shared with an owner is that very object, never a redeclared copy."""
    for facade, owners in FACADES.items():
        shared = 0
        for owner in owners:
            for name, value in vars(owner).items():
                if not name.startswith("__") and not isinstance(value, types.ModuleType) and name not in ADAPTERS \
                        and hasattr(facade, name):
                    shared += 1
                    assert getattr(facade, name) is value, f"{facade.__name__}.{name} vs {owner.__name__}"
        assert shared >= {massage: 100, writeproxy: 60, probegate: 2}[facade]   # the check is not vacuous

def test_every_test_file_actually_runs():
    """Every module defining tests matches pytest's collection name, and basenames are unique (no stale-bytecode collisions)."""
    files = [f for f in sorted((ROOT / "tests").rglob("*.py")) if f.name not in ("__init__.py", "conftest.py")]   # an uncollected module reads as green
    skipped = [f.name for f in files if not f.name.startswith("test_") and any(
        isinstance(n, ast.FunctionDef) and n.name.startswith("test_") for n in ast.parse(f.read_text()).body)]
    assert not skipped and len({f.name for f in files}) == len(files)

def test_built_wheel_ships_runtime_and_prompts_not_suite_data_and_loads_installed(tmp_path):
    """The deployable wheel has cria and every prompt, none of suite/tests/runs, and prompts load outside the checkout."""
    if not all(importlib.util.find_spec(m) for m in ("setuptools", "wheel")):
        pytest.skip("distribution build tools are not installed")
    (tmp_path / "meta").mkdir()
    cfg = {"--global-option": ["egg_info", "--egg-base", str(tmp_path / "meta"), "build", "--build-base", str(tmp_path / "b")]}
    built = subprocess.run([sys.executable, "-c", f"import setuptools.build_meta as b; b.build_wheel({str(tmp_path)!r}, "
                            f"config_settings={cfg!r})"], cwd=ROOT, capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    wheel, = tmp_path.glob("*.whl")
    with zipfile.ZipFile(wheel) as z:
        names = set(z.namelist())
        z.extractall(tmp_path / "installed")
    assert not any(n.startswith(("suite/", "tests/", "runs/", "walkdata/")) for n in names)
    assert {p.relative_to(ROOT).as_posix() for p in (CRIA / "prompts").glob("*.txt")} <= names
    probe = ("import sys; from cria import prompts; from cria.config import Config; "
             "assert prompts.load('compaction_validate_retrospective') and not Config().system1.enabled; "
             "assert 'onnxruntime' not in sys.modules")
    run = subprocess.run([sys.executable, "-c", probe], cwd=tmp_path / "installed", capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(tmp_path / "installed")})
    assert run.returncode == 0, run.stdout + run.stderr
