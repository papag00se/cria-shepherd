"""A ratchet: no NEW bare slice reaches text a reader will see.

Three roots of the elision sweep share one shape — a bound applied with a bare `[:N]` and no sentence
saying a bound was applied. `prompts.named_list` exists for a list (it names the remainder) and
`content_reduce.clip` for a string (it appends the marker). This test does not try to judge intent:
it lists every bare slice that reaches an f-string or a `", ".join(...)` under cria/, and every one
of them has to be here with a reason. A new one fails until someone writes down why it is not a
silent cut — which is the point.
"""
import ast
import pathlib
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent / "cria"

# file:line is deliberately NOT the key — line numbers move. The key is the expression, per file.
_ALLOWED = {
    ("loop.py", "cleaned[i][:160]"): "an EVENT field for the operator's jsonl, not model-facing text",
    ("loop.py", "cleaned.strip().splitlines()[1:]"): "parsing: drops a header line, keeps the rest",
    ("loop.py", "_task_key(task)[:8]"): "a short id for a filename/log, not prose",
    ("loop.py", "d[1:]"): "strips one leading character",
    ("plan.py", "lines[i + 1:]"): "parsing: the remainder of a block",
    ("planner.py", "key[:8]"): "a short id, not prose",
    ("planner_tools.py", "ln[:2]"): "reads the first two characters to classify a line",
    ("probegate.py", "ran[:-1]"): "grammar: 'a, b and c' — every item is printed",
    ("probegate.py", "text[max(0, i - 80):i + 160]"): "a search WINDOW over text cria reads itself",
    ("probeparse.py", "toks[2:]"): "parsing: argv tail",
    ("proberun.py", "lines[:i]"): "splits a record at a marker; both halves are used",
    ("proberun.py", "lines[i + 1:]"): "splits a record at a marker; both halves are used",
    ("proberun.py", "lines[1:]"): "peel_probe_cmd_echo: strips cria's own self-describing marker line, the remainder is returned whole",
    ("responses.py", "uuid.uuid4().hex[:24]"): "an id",
    ("webfetch.py", "d[:DESCRIPTION_CHARS - 1]"): "the branch appends the ellipsis itself",
    ("webfetch.py", "s[:keep]"): "head…tail form: the marker is in the f-string",
    ("webfetch.py", "s[-4:]"): "head…tail form: the marker is in the f-string",
    ("writeproxy.py", "lines[:cut]"): "the caller states the cut in the same result",
    ("writeproxy.py", "raw[i:i + width]"): "chunking for a hexdump — every byte is emitted",
    ("writeproxy.py", "command.lstrip().splitlines()[:2]"): "a label for cria's own log line",
}


def _sliced_into_text():
    out = []
    for path in sorted(_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.JoinedStr):
                targets = [node]
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "join" and node.args):
                targets = [node.args[0]]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice):
                        out.append((path.name, ast.unparse(n), n.lineno))
    return out


class TheRatchetTests(unittest.TestCase):
    def test_every_bare_slice_in_text_has_a_written_reason(self):
        unexplained = [f"{f}:{ln} {expr}" for f, expr, ln in _sliced_into_text()
                       if (f, expr) not in _ALLOWED]
        self.assertEqual(unexplained, [],
                         "a bound with no sentence saying a bound was applied. Use "
                         "prompts.named_list for a list or content_reduce.clip for a string — or "
                         "add it to _ALLOWED with the reason it is not a silent cut")

    def test_the_allowlist_has_no_dead_entries(self):
        live = {(f, expr) for f, expr, _ln in _sliced_into_text()}
        self.assertEqual([k for k in _ALLOWED if k not in live], [],
                         "these are gone from the code; delete them from the allowlist")


if __name__ == "__main__":
    unittest.main()
