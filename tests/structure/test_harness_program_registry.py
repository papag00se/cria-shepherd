"""The end-state registry of harness-side program text (docs/harness-programs.md §9) is enforced, not hoped for.

Anything cria composes for the harness to run must be one of the registered classes; a program text found in a module that is not registered, or a
registered module grown past its budget, fails here. The scan reads the source of every ``cria/*.py`` (prose docstrings excepted) for the shapes a
harness-side program takes: a Python launch, a heredoc, an ``import`` line or ``def`` inside a string, shell control flow, ``trap`` / ``exit``."""
import ast
import pathlib
import re

import pytest

from cria import harnessprims

ROOT = pathlib.Path(__file__).resolve().parents[2]
CRIA = ROOT / 'cria'
DOC = (ROOT / 'docs' / 'harness-programs.md').read_text()

# module -> (what it is, byte budget of its program-text constants). Every row is in docs/harness-programs.md §9.
REGISTRY = {
    'harnessprims.py': ('the seven stubs: read, write, put, ls, rm, run, search', 10_400),
    'gatescript.py': ('the gate supervisor: the shell text `run` executes for the project\'s own checks', 400),
    'inventoryops.py': ('the ctags shell text', 400),
    'syntaxcheck.py': ('the checker shell text', 150),
    'surveyops.py': ('the survey\'s probe script (command lookup and path kind)', 450),
    'probediscovery.py': ('the three parse-floor one-liners (TOML, JSON, XML)', 800),
}

PROGRAM = re.compile(
    r"(?:^|[\s;|&{(`'\"])python3?\s+(?:-[ISc]\b|-\s|<<)"          # a Python launch
    r"|<<-?\s*['\"]?[A-Z][A-Z_0-9]{3,}['\"]?\s*(?:\n|$)"                # a heredoc
    r"|^\s*(?:import|from)\s+\w[\w.]*(?:\s+import\b|\s*,|\s*$)"     # a Python import line
    r"|^\s*def \w+\("                                  # a Python function
    r"|;\s*then\b|;\s*do\b|^\s*(?:if \[|for \w+ in |while |case )|\btrap '|\bexit 127\b|\bcommand -p\b|\bunshare -",
    re.M)


def _program_constants():
    found = {}
    for path in sorted(CRIA.glob('*.py')):
        tree = ast.parse(path.read_text())
        prose = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose and PROGRAM.search(node.value):
                found.setdefault(path.name, []).append((node.lineno, len(node.value.encode())))
    return found


def test_no_harness_program_text_exists_outside_the_registry():
    unregistered = {name: hits for name, hits in _program_constants().items() if name not in REGISTRY}
    assert unregistered == {}, (
        'program text bound for the harness is only the registered kinds (docs/harness-programs.md §9). If one of these is a harness-side '
        'program, STOP: the standing order forbids adding one without a registry entry (reason it cannot live in cria, size budget). '
        f'Found in: {unregistered}')


@pytest.mark.parametrize('module', sorted(REGISTRY))
def test_a_registered_module_stays_within_its_budget_and_is_in_the_docs(module):
    _, budget = REGISTRY[module]
    used = sum(size for _, size in _program_constants().get(module, ()))
    assert 0 < used <= budget, f'{module}: {used} B of program text against a budget of {budget} B (raise it in docs §9 and here, together, with the reason)'
    assert f'`{module}`' in DOC.split('## 9. The end-state registry', 1)[1], f'{module} is not in docs/harness-programs.md §9'


def test_the_seven_stubs_are_exactly_the_registered_ones():
    assert sorted(harnessprims.STUBS) == ['ls', 'put', 'read', 'rm', 'run', 'search', 'write']
    assert sum(len(text) for text in harnessprims.STUBS.values()) <= 14_500
