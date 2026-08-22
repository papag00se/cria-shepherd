"""A workspace answer of "I could not see it" is never read as "it is not there".

`wsview` answers three ways on purpose — True, False, and None for "cria has not been told". The
first root of the elision sweep was seven places that collapsed the third into the second and then
told the model, as a fact, that a file did not exist. `if not view.isfile(p)` is that collapse
written down: None is falsy, so an unreadable file and an absent one take the same branch.

This is the half that stops the next one. It permits `os.path.*` (a real two-valued question about
cria's own disk) and requires everything else to compare explicitly — `is False`, `is None`,
`is not None`."""
import ast
import pathlib
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent / "cria"

# Methods whose answer carries a third value. Named by ATTRIBUTE, so a caller holding a view under
# any local name is covered.
_THREE_VALUED = {"isfile", "isdir", "read", "size", "scandir", "walk"}


def _is_os_path(call: ast.Call) -> bool:
    """`os.path.isfile(...)` — a two-valued question about cria's own filesystem."""
    fn = call.func
    return (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Attribute)
            and fn.value.attr == "path")


# Sites where the third value is deliberately folded into a DEFAULT, with the reason. Keyed by the
# expression, not the line — line numbers move. Each one has to answer: what does the reader end up
# being told, and is that a false fact?
_ALLOWED = {
    "view.size(path) or 0": "arithmetic against a byte budget; an unknown size spends nothing, and "
                            "no sentence about the file's size reaches anyone",
    "view.read(f) or ''": "the contract is 'the text, or nothing to quote' — an unquotable file "
                           "produces silence, never a claim that it is absent",
    "wsview.current(workspace_root).read(Path(workspace_root) / rel.lstrip('./')) or ''":
        "feeds the citation check, whose caller already refuses to corroborate from a miss",
    "wsview.current().read(Path(project_dir) / 'package.json') or ''":
        "a script LOOKUP whose None already means 'cria does not know', and which makes no "
        "model-facing claim either way",
    "wsview.current().walk(path) or ()":
        "deliberate, and documented at the site: an unreadable tree must NOT read as evidence that "
        "an install happened. Erring toward 'not installed' prescribes a re-install; erring the "
        "other way tells the model a package is there when it is not",
}


def _bare_truth_tests():
    out = []
    for path in sorted(_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            calls = []
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
                calls = [node.operand]
            elif isinstance(node, ast.If):
                calls = [node.test]
            elif isinstance(node, ast.BoolOp):
                calls = list(node.values)
            for c in calls:
                if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                        and c.func.attr in _THREE_VALUED and not _is_os_path(c)):
                    if isinstance(node, ast.BoolOp) and ast.unparse(node) in _ALLOWED:
                        continue
                    out.append(f"{path.name}:{c.lineno} {ast.unparse(c)}")
    return out


class UnknownIsItsOwnAnswerTests(unittest.TestCase):
    def test_no_workspace_answer_is_tested_for_bare_truthiness(self):
        self.assertEqual(_bare_truth_tests(), [],
                         "None means 'could not look', and it is falsy — so this branch treats an "
                         "unreadable file exactly like an absent one. Compare explicitly: `is False` "
                         "when you mean absent, `is None` when you mean unknown")

    def test_the_view_really_does_answer_three_ways(self):
        # If this ever becomes two-valued the test above is guarding nothing.
        from cria import wsview
        v = wsview.View(".")
        self.assertIsNone(v.isfile("never/heard/of/it.py"))
        self.assertIsNone(v.read("never/heard/of/it.py"))


if __name__ == "__main__":
    unittest.main()
