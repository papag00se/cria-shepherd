"""A bare slice into model- or operator-facing text is a silent clip (principle: never blindly clip)."""
import ast
from functools import lru_cache
from pathlib import Path

CRIA = Path(__file__).resolve().parents[2] / "cria"

@lru_cache(maxsize=None)
def trees():
    return [(p.name, ast.parse(p.read_text(encoding="utf-8"))) for p in sorted(CRIA.rglob("*.py"))]

BENIGN_SLICES = {  # (file, expression): display tables, ids, parsing, both halves used
    ("retention.py", "name[:20]"), ("retention.py", "r[:6]"), ("livingplan.py", "cleaned[i][:160]"),
    ("completionconfirmation.py", "cleaned.strip().splitlines()[1:]"), ("loop.py", "_task_key(task)[:8]"),
    ("loop.py", "d[1:]"), ("plan.py", "lines[i + 1:]"), ("planner.py", "key[:8]"), ("externalization.py", "ln[:2]"),
    ("probegate.py", "ran[:-1]"), ("probegate.py", "text[max(0, i - 80):i + 160]"), ("probeparse.py", "toks[2:]"),
    ("proberun.py", "lines[:i]"), ("proberun.py", "lines[i + 1:]"), ("responses.py", "uuid.uuid4().hex[:24]"),
    ("webfetch.py", "d[:DESCRIPTION_CHARS - 1]"), ("webfetch.py", "s[:keep]"), ("webfetch.py", "s[-4:]"),
    ("dedup.py", "us[cur:]"), ("dedup.py", "us[cur:a]"), ("callliterals.py", "lines[:cut]"),
    ("writeproxy.py", "raw[i:i + width]"), ("outboundpolicies.py", "command.lstrip().splitlines()[:2]"),
    ("contextfloor.py", "text[tail_start:]"),   # the newest part of a user message, beside the label stating what was omitted
    ("editapply.py", "lines[max(0, d - 2):d + 4]"),   # the edit-miss window: the lines around the divergence, which the directive names as exactly that
    ("splice.py", "self.base[p[1]:p[2]]"),            # the bytes of a file (joined as bytes), not text a reader is shown
    ("writeops.py", "callauth.group(op.op)[:16]"),    # an id: the name of the staging file the `put` stub derives from the same 32 hex digits
    ("writeops.py", "callauth.nonce(op.op, write.s)[:16]"),   # an id: the name of the temporary file the `write` stub derives from its own nonce
}

def sliced_into_text():
    out = []
    for name, tree in trees():
        seen = set()   # an f-string nested in an f-string walks its slices twice
        for node in ast.walk(tree):
            roots = ([node] if isinstance(node, ast.JoinedStr) else
                     [node.args[0]] if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                     and node.func.attr == "join" and node.args else [])
            cuts = [n for r in roots for n in ast.walk(r) if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice)]
            out += [(name, ast.unparse(n)) for n in cuts if id(n) not in seen]
            seen.update(id(n) for n in cuts)
    return out

def test_no_new_unmarked_bound_reaches_model_or_operator_text():
    """A bound applied with a bare `[:N]` and no sentence saying so is a silent, undetectable lie to the reader."""
    assert sorted(set(sliced_into_text()) - BENIGN_SLICES) == [], "new bare slice into text: use windowcaps/clip"
