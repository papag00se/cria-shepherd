"""A ratchet: no NEW fixed number that stands in for "how much fits in the window".

``cria/windowcaps.py`` owns every such bound (a ``Cap``: today's value at the 49,152-token window,
a share of the window elsewhere). This lint finds the shape such a number takes — a module-level
integer constant named like a size (``*_TOKENS``, ``*_CHARS``, ``*_BYTES``, ``*_BUDGET``, ``*_RESERVE``,
``*_CAP``, ``*_LIMIT``, ``*_MAX``…, value >= 1000) and a literal ``max_tokens`` default/argument — and
requires each one either to BE a ``windowcaps`` Cap (then it is not an integer literal and is not
found here) or to carry a written reason it does not move with the window. A new constant fails until
someone decides which.

The reasons fall in four groups, and a context-sized bound is none of them:
  transport  — a harness/OS result limit the harness enforces whatever the model's window is
  safety     — a time/resource/parse bound that protects cria or the machine
  one word   — the reply is ONE word; scaling the room only wastes window
  measured   — the size of a thing (a prompt frame, a detector pattern) not of the window
"""
import ast
import pathlib
import re
import unittest

from cria import windowcaps

_ROOT = pathlib.Path(__file__).resolve().parent.parent / "cria"

_SIZE = re.compile(r"(MAX_TOKENS|_TOKENS|_RESERVE|_CHARS|_BYTES|_BUDGET|_CAP|_LIMIT|_FLOOR|_MAX|_MIN|_STRIDE"
                   r"|_ENTRIES|_FILES|_DIRS|_SIZE|_MAX_[A-Z_]+|_MIN_[A-Z_]+)$|^(MAX|MIN)_")
_THRESHOLD = 1000

_ALLOWED = {
    # --- transport: a result limit the harness / OS enforces, independent of the model's window
    ("content_reduce.py", "INLINE_RESULT_MAX_BYTES"): "transport: the harness's own tool-result cap (measured 9,292-10,223 retained bytes)",
    ("externalization.py", "STDOUT_MAX_BYTES"): "transport: the harness's stdout cap",
    ("filecommands.py", "READ_TRANSPORT_STDOUT_BYTES"): "transport: the harness's stdout cap for a read",
    ("multipart.py", "STDOUT_LIMIT"): "transport: the harness's stdout cap",
    ("probegate.py", "TRANSPORT_CHUNK_BYTES"): "transport: one result's worth of the gate's packed pages",
    ("probegate.py", "TRANSPORT_RAW_PAGE_MAX"): "transport: the gate's raw page bound",
    ("toolwire.py", "_RIDE_ALONG_HOST_RESERVE"): "transport: bytes the host command needs beside a ride-along",
    ("toolwire.py", "_RIDE_ALONG_COMMAND_RESERVE"): "transport: bytes the command needs beside a ride-along",
    ("wsview.py", "TREE_MAX_ENTRIES"): "transport: the survey rides home inside ONE harness tool result (see the wsview comment: 48,000 was 4.7x that cap)",
    ("wsview.py", "TREE_MAX_BYTES"): "transport: the survey rides home inside ONE harness tool result",
    ("wsview.py", "BLOB_BYTES_MAX"): "transport: the survey's bodies ride home inside the same harness result",
    ("writeproxy.py", "ECHO_MAX_BYTES"): "transport: an echo inside a tool result, itself bounded by ECHO_WIRE_MAX_BYTES = INLINE_RESULT_MAX_BYTES",
    ("upstream.py", "_REASONING_FLUSH_BYTES"): "transport: stream flush batching",
    # --- safety / time / resource: protects cria or the machine
    ("depsurface.py", "MAX_FILE_BYTES"): "safety: a file cria parses for a dependency surface",
    ("depsurface.py", "MAX_ROOT_DIRS"): "safety: directories walked",
    ("groundtruth.py", "DEFAULT_FILE_CAP"): "safety: a file-read bound on redirect files (real ones sit far below it)",
    ("planner.py", "_GROUND_SCAN_MAX_BYTES"): "safety: a bounded sweep",
    ("probediscovery.py", "MAX_FLOOR_FILES_PER_LANG"): "safety: files walked per language",
    ("probeparse.py", "U32_MAX"): "arithmetic: a u32 ceiling",
    ("system1.py", "MAX_WINDOW_TOKENS"): "the trained classifier's OWN fixed input window, not the served model's",
    ("system1.py", "WEIGHT_BUDGET_BYTES"): "safety: classifier artifact size",
    ("wsview.py", "_BODY_CACHE_MAX_BYTES"): "safety: a per-session cache bound",
    ("dedup.py", "MIN_RUN_CHARS"): "measured: what counts as a repeated run of evidence, a property of the text",
    # --- one word: the answer is one word; scaling the reply room wastes window
    ("filepresence.py", "MAX_TOKENS"): "one word: a one-word verdict's reply room",
    ("loop.py", "COMPACTION_VERDICT_RESERVE"): "one word: the lens answers ONE word (commit 40747fda); the cap itself is a Cap",
    # --- measured: the size of a thing, not of the window
    ("handoffdistill.py", "FRAME_TOKENS"): "measured: the fixed prompt frame (instruction + intro + ask) around a composed request, ~1.9K tokens whatever the window",
    ("generationguards.py", "DEFAULT_REASONING_BUDGET"): "behavioural: how long a thought may run before it reads as rumination, used only when the role names no output_reserve (an operator value); the window-exhaustion abort is its own fraction (WINDOW_EXHAUSTED_FRACTION)",
    ("generationguards.py", "DEGENERATE_RUN_CHARS"): "measured: the size of a repeating run in reasoning text",
    ("generationguards.py", "WIDE_RUN_CHARS"): "measured: the size of a repeating run in reasoning text",
    ("generationguards.py", "WIDE_EVAL_STRIDE"): "measured: detector evaluation stride",
    ("generationguards.py", "WIDE_MIN_CHARS"): "measured: detector minimum text",
    ("planner_tools.py", "_SEARCH_INLINE_CHARS"): "planner research seat's inline search preview; the planner is OFF unless explicitly requested (experiments only)",
    # --- a literal max_tokens default
    ("loop.py", "ask_closed(max_tokens=)"): "one word: the default reply room of a closed question when the caller names none (38/38 answered at 1,024 with reasoning off, classify.py)",
}


def _int_value(node):
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.BinOp):
        a, b = _int_value(node.left), _int_value(node.right)
        if a is None or b is None:
            return None
        try:
            return eval(compile(ast.Expression(ast.BinOp(ast.Constant(a), node.op, ast.Constant(b))), "", "eval"))
        except Exception:  # noqa: BLE001 — not a constant expression
            return None
    return None


def _found():
    """(file, key, line, how) for each fixed size-like integer."""
    out = []
    for path in sorted(_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in tree.body:
            name = value = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                name, value = node.target.id, node.value
            if name and _SIZE.search(name):
                n = _int_value(value)
                if n is not None and n >= _THRESHOLD:
                    out.append((path.name, name, node.lineno, f"{name} = {n}"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value in ("max_tokens", "max_output_tokens") \
                            and _int_value(v) is not None:
                        out.append((path.name, f"{k.value}", v.lineno, f"a literal {k.value} {_int_value(v)}"))
            elif isinstance(node, ast.keyword) and node.arg in ("max_tokens", "output_reserve") \
                    and _int_value(node.value) is not None:
                out.append((path.name, node.arg, node.value.lineno, f"a literal {node.arg}= {_int_value(node.value)}"))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = node.args
                names = [x.arg for x in a.args] + [x.arg for x in a.kwonlyargs]
                defaults = [None] * (len(a.args) - len(a.defaults)) + list(a.defaults) + list(a.kw_defaults)
                for nm, d in zip(names, defaults):
                    if nm in ("max_tokens", "output_reserve", "reserve") and d is not None and _int_value(d) is not None:
                        out.append((path.name, f"{node.name}({nm}=)", d.lineno, f"{node.name}({nm}={_int_value(d)})"))
    return out


class TheRatchetTests(unittest.TestCase):
    def test_every_fixed_size_is_a_window_cap_or_has_a_written_reason(self):
        unexplained = [f"{f}:{ln} {how}" for f, key, ln, how in _found() if (f, key) not in _ALLOWED]
        self.assertEqual(unexplained, [],
                         "a fixed number that looks like a share of the window. If it stands in for 'how much "
                         "fits', make it a windowcaps.Cap (one row in windowcaps._SPECS, resolved at the wire or "
                         "with the measured window); otherwise add it to _ALLOWED with the reason it does not "
                         "move with the window (transport / safety / one word / measured)")

    def test_the_allowlist_has_no_dead_entries(self):
        live = {(f, key) for f, key, _ln, _how in _found()}
        dead = [k for k in _ALLOWED if k not in live]
        self.assertEqual(dead, [], "these are gone from the code; delete them from the allowlist")

    def test_every_reason_is_a_sentence(self):
        for key, reason in _ALLOWED.items():
            self.assertGreater(len(reason.split()), 2, key)

    def test_every_window_cap_has_a_user(self):
        """A row in the table that nothing reads is a bound that was never wired (or one that was removed)."""
        sources = {p: p.read_text(encoding="utf-8") for p in _ROOT.rglob("*.py") if p.name != "windowcaps.py"}
        for const in ("JUDGE_REPLY", "SUMMARY_REPLY", "CRITIC_REPLY", "PLAN_REPLY", "EXTRACT_REPLY", "GEN_RESERVE",
                      "SELFCOMPACT_KEEP_TAIL", "SELFCOMPACT_RECOMPACT", "DEPENDENCY_SURFACE", "DEPENDENCY_NOTES",
                      "SELFCOMPACT_REFOLD", "EVIDENCE_BLOCK"):
            with self.subTest(const):
                self.assertTrue(any(f"windowcaps.{const}" in text for text in sources.values()), const)
        self.assertEqual(len(windowcaps.NAMES), 12)


if __name__ == "__main__":
    unittest.main()
