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

CRIA = pathlib.Path(__file__).resolve().parent.parent / "cria"


def import_graph() -> dict:
    """`{module: {modules it imports}}` for every sibling under `cria/`, at any nesting depth."""
    g = {}
    for f in sorted(CRIA.glob("*.py")):
        edges = set()
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.ImportFrom) and n.level == 1:
                if n.module:                       # from .x import y
                    edges.add(n.module.split(".")[0])
                else:                              # from . import x, y
                    edges.update(a.name for a in n.names)
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
