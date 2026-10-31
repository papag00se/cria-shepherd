"""A regex was the reason an 8,000-line driver was a dependency of the fact-gatherer beneath it.

`cria/groundtruth.py` reached UP into `cria/loop.py` for one compiled pattern, from inside a function
body. A deferred import like that is the classic tell for a cycle somebody worked around instead of
breaking: `loop` imports `groundtruth` at module level, so the two were mutually dependent and
neither could be imported, tested or reasoned about alone.

Found by the code-health audit's structure lens, which is the pass a per-file reviewer cannot do —
each file was individually fine.

The fix was to move the pattern DOWN a level, next to the sibling pattern that reads the other kind
of token out of the same string. Both answer "what does this step name?", so they belong together on
their own merits; killing the cycle came free.

This test walks the real import graph, INCLUDING imports inside function bodies, because those are
exactly the ones a module-level scan misses and exactly the ones that hide a cycle.
"""

import ast
import pathlib
import unittest

import pytest

CRIA = pathlib.Path(__file__).resolve().parent.parent / "cria"


def import_graph(root=CRIA) -> dict:
    """Sibling edges from relative/absolute package imports, including deferred/type bodies."""
    g = {}
    for f in sorted(root.glob("*.py")):
        edges = set()
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.ImportFrom) and n.level == 1:
                if n.module:                       # from .x import y
                    edges.add(n.module.split(".")[0])
                else:                              # from . import x, y
                    edges.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.level == 0:
                if n.module == 'cria':              # from cria import x [as alias]
                    edges.update(a.name.split('.')[0] for a in n.names)
                elif (n.module or '').startswith('cria.'):
                    edges.add(n.module.split('.')[1])  # from cria.x[.y] import value
            elif isinstance(n, ast.Import):
                edges.update(a.name.split('.')[1] for a in n.names
                             if a.name.startswith('cria.'))  # import cria.x [as alias]
        g[f.stem] = edges
    return g


def cycles(g: dict) -> list:
    """Every simple cycle, as a list of module names. Iterative DFS with an explicit stack, so a
    deep graph cannot blow the recursion limit and quietly report 'no cycles'."""
    found, colour = [], {}

    def walk(start):
        stack = [(start, iter(sorted(g.get(start, ()))))]
        path = [start]
        colour[start] = 1
        while stack:
            node, it = stack[-1]
            for nxt in it:
                if nxt not in g:
                    continue
                if colour.get(nxt) == 1:           # back-edge → cycle
                    found.append(path[path.index(nxt):] + [nxt])
                elif colour.get(nxt) is None:
                    colour[nxt] = 1
                    path.append(nxt)
                    stack.append((nxt, iter(sorted(g.get(nxt, ())))))
                    break
            else:
                colour[node] = 2
                stack.pop()
                path.pop()

    for m in sorted(g):
        if colour.get(m) is None:
            walk(m)
    return found


class TheGraphIsAcyclicTests(unittest.TestCase):
    def test_no_module_under_cria_imports_in_a_circle(self):
        found = cycles(import_graph())
        self.assertEqual(found, [], "import cycle(s): " + " · ".join(" → ".join(c) for c in found))

    def test_the_gatherer_does_not_depend_on_the_driver(self):
        """The specific edge that was there: groundtruth → loop, for one regex."""
        self.assertNotIn("loop", import_graph()["groundtruth"])

    def test_the_pattern_lives_where_its_sibling_does(self):
        from cria import groundtruth, loop
        self.assertIs(loop._STEP_ARTIFACT, groundtruth._STEP_ARTIFACT)
        self.assertTrue(groundtruth._STEP_LITERAL.pattern)   # the sibling it now sits beside


@pytest.mark.parametrize('statement', [
    'from cria import b',
    'from cria import b as alias',
    'from cria.b import value',
    'from cria.b.deep import value',
    'import cria.b',
    'import cria.b as alias',
    'import cria.b.deep as alias',
    'from . import b',
    'from .b import value',
    'def deferred():\n    from cria import b',
    'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from cria.b import value',
    'class Outer:\n    def deferred(self):\n        import cria.b as alias',
])
def test_collector_detects_real_package_edges_in_literal_source(tmp_path, statement):
    (tmp_path / 'a.py').write_text(statement + '\n')
    (tmp_path / 'b.py').write_text('from . import a\n')
    graph = import_graph(root=tmp_path)
    assert graph == {'a': {'b'}, 'b': {'a'}}
    assert cycles(graph) == [['a', 'b', 'a']]


def test_external_and_package_only_imports_do_not_invent_sibling_cycles(tmp_path):
    (tmp_path / 'a.py').write_text('''import cria
import external.b as b
from external import b
from cria_extra.b import value
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import outside.a
from . import b
''')
    (tmp_path / 'b.py').write_text('from external.a import value\n')
    graph = import_graph(root=tmp_path)
    assert graph == {'a': {'b'}, 'b': set()}
    assert cycles(graph) == []


class TheDetectorItselfWorksTests(unittest.TestCase):
    """A cycle test that cannot see a cycle is worse than none — it certifies the thing it missed.
    My first attempt at this had exactly that bug: it checked 'already visited' before 'is this the
    target', so it returned before ever closing a loop and reported a clean graph."""

    def test_it_finds_a_two_module_cycle(self):
        self.assertTrue(cycles({"a": {"b"}, "b": {"a"}}))

    def test_it_finds_a_three_module_cycle(self):
        self.assertTrue(cycles({"a": {"b"}, "b": {"c"}, "c": {"a"}}))

    def test_it_does_not_invent_one_on_a_diamond(self):
        """a→b→d and a→c→d share a node without being a cycle."""
        self.assertEqual(cycles({"a": {"b", "c"}, "b": {"d"}, "c": {"d"}, "d": set()}), [])

    def test_a_self_import_counts(self):
        self.assertTrue(cycles({"a": {"a"}}))


if __name__ == "__main__":
    unittest.main()
