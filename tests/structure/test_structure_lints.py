"""Ratchets over cria/: new ones fail until someone writes down why; dead allowlist entries fail too."""
import ast
import re
from functools import lru_cache
from pathlib import Path

CRIA = Path(__file__).resolve().parents[2] / "cria"

@lru_cache(maxsize=None)
def trees():
    return [(p.name, ast.parse(p.read_text(encoding="utf-8"))) for p in sorted(CRIA.rglob("*.py"))]

def check_ratchet(found, allowed, what):
    assert sorted(set(found) - set(allowed)) == [], f"new {what}: use windowcaps/clip, or add a written reason"
    assert sorted(set(allowed) - set(found)) == [], f"dead allowlist entries ({what}): delete them"

BENIGN_SLICES = {  # (file, expression) -> why it is not a silent cut: display tables, ids, parsing, both halves used
    ("retention.py", "name[:20]"), ("retention.py", "r[:6]"), ("livingplan.py", "cleaned[i][:160]"),
    ("completionconfirmation.py", "cleaned.strip().splitlines()[1:]"), ("loop.py", "_task_key(task)[:8]"),
    ("loop.py", "d[1:]"), ("plan.py", "lines[i + 1:]"), ("planner.py", "key[:8]"), ("externalization.py", "ln[:2]"),
    ("probegate.py", "ran[:-1]"), ("probegate.py", "text[max(0, i - 80):i + 160]"), ("probeparse.py", "toks[2:]"),
    ("proberun.py", "lines[:i]"), ("proberun.py", "lines[i + 1:]"), ("responses.py", "uuid.uuid4().hex[:24]"),
    ("webfetch.py", "d[:DESCRIPTION_CHARS - 1]"), ("webfetch.py", "s[:keep]"), ("webfetch.py", "s[-4:]"),
    ("dedup.py", "us[cur:]"), ("dedup.py", "us[cur:a]"), ("callliterals.py", "lines[:cut]"),
    ("writeproxy.py", "raw[i:i + width]"), ("outboundpolicies.py", "command.lstrip().splitlines()[:2]"),
}

def sliced_into_text():
    out = set()
    for name, tree in trees():
        for node in ast.walk(tree):
            roots = ([node] if isinstance(node, ast.JoinedStr) else
                     [node.args[0]] if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                     and node.func.attr == "join" and node.args else [])
            out |= {(name, ast.unparse(n)) for r in roots for n in ast.walk(r)
                    if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice)}
    return out

def test_no_new_unmarked_bound_reaches_model_or_operator_text():
    """A bound applied with a bare `[:N]` and no sentence saying so is a silent, undetectable lie to the reader."""
    check_ratchet(sliced_into_text(), BENIGN_SLICES, "bare slice into text")

SIZE = re.compile(r"(_TOKENS|_RESERVE|_CHARS|_BYTES|_BUDGET|_CAP|_LIMIT|_FLOOR|_MAX|_MIN|_STRIDE|_ENTRIES|_FILES|_DIRS|_SIZE"
                  r"|_MAX_[A-Z_]+|_MIN_[A-Z_]+)$|^(MAX|MIN)_")
# Reasons a size does not move with the window: transport (harness/OS cap), safety, one word, measured; else it must be a windowcaps.Cap.
FIXED_SIZES = {
    "content_reduce.py": "INLINE_RESULT_MAX_BYTES COMMAND_ARG_BUDGET", "externalization.py": "STDOUT_MAX_BYTES",
    "filecommands.py": "READ_TRANSPORT_STDOUT_BYTES", "multipart.py": "STDOUT_LIMIT", "writeproxy.py": "ECHO_MAX_BYTES",
    "probegate.py": "TRANSPORT_CHUNK_BYTES TRANSPORT_RAW_PAGE_MAX", "upstream.py": "_REASONING_FLUSH_BYTES",
    "toolwire.py": "_RIDE_ALONG_HOST_RESERVE _RIDE_ALONG_COMMAND_RESERVE",
    "wsview.py": "TREE_MAX_ENTRIES TREE_MAX_BYTES BLOB_BYTES_MAX _BODY_CACHE_MAX_BYTES",
    "depsurface.py": "MAX_FILE_BYTES MAX_ROOT_DIRS", "apidiscovery.py": "MAX_PROBE_BYTES", "webfetch.py": "MAX_BODY_BYTES",
    "groundtruth.py": "DEFAULT_FILE_CAP", "planner.py": "_GROUND_SCAN_MAX_BYTES", "probeparse.py": "U32_MAX",
    "probediscovery.py": "MAX_FLOOR_FILES_PER_LANG", "system1.py": "MAX_WINDOW_TOKENS WEIGHT_BUDGET_BYTES ARENA_BUDGET_BYTES "
    "_MIN_ARENA_BUDGET_BYTES", "filepresence.py": "MAX_TOKENS", "loop.py": "COMPACTION_VERDICT_RESERVE ask_closed(max_tokens=)",
    "dedup.py": "MIN_RUN_CHARS", "handoffdistill.py": "FRAME_TOKENS", "planner_tools.py": "_SEARCH_INLINE_CHARS",
    "generationguards.py": "DEFAULT_REASONING_BUDGET DEGENERATE_RUN_CHARS WIDE_RUN_CHARS WIDE_EVAL_STRIDE WIDE_MIN_CHARS",
}


def int_value(node):
    try:
        v = eval(compile(ast.fix_missing_locations(ast.Expression(node)), "", "eval"), {"__builtins__": {}})
    except Exception:  # noqa: BLE001 — not a constant expression
        return None
    return v if type(v) is int else None

def fixed_sizes():
    out = set()
    for name, tree in trees():
        for node in tree.body:   # module-level size-named constant >= 1000
            target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else getattr(node, "target", None)
            if isinstance(target, ast.Name) and SIZE.search(target.id) and (int_value(getattr(node, "value", None)) or 0) >= 1000:
                out.add((name, target.id))
        for node in ast.walk(tree):   # literal max_tokens / output_reserve: keyword, dict key, or parameter default
            if isinstance(node, ast.keyword) and node.arg in ("max_tokens", "output_reserve") and int_value(node.value):
                out.add((name, node.arg))
            elif isinstance(node, ast.Dict):
                out |= {(name, k.value) for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)
                        and k.value in ("max_tokens", "max_output_tokens") and int_value(v)}
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = node.args
                defaults = [None] * (len(a.args) - len(a.defaults)) + list(a.defaults) + list(a.kw_defaults)
                out |= {(name, f"{node.name}({x.arg}=)") for x, d in zip(a.args + a.kwonlyargs, defaults)
                        if x.arg in ("max_tokens", "output_reserve", "reserve") and d is not None and int_value(d)}
    return out

def test_no_new_fixed_size_stands_in_for_the_context_window():
    """Every size-like integer is a windowcaps.Cap (not a literal) or carries a reason it does not move with the window."""
    allowed = {(f, n) for f, names in FIXED_SIZES.items() for n in names.split()}
    check_ratchet(fixed_sizes(), allowed, "fixed size")

NOT_A_RESHAPE = {  # measurement or abstention: nothing was rewritten, so nothing for the operator's ledger
    "context.floor_skipped", "context.window", "context.overflow", "context.calibrated", "context.refit",
    "context.measured", "context.image_fit_unknown", "context.image_density_unknown",
    "context.briefing_symbols_unreachable"}

def emits():
    for name, tree in trees():
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and n.args and getattr(n.func, "attr", getattr(n.func, "id", "")) in ("emit", "_log"):
                for kind in [a.value for a in n.args[:2] if isinstance(a, ast.Constant) and isinstance(a.value, str)][:1]:
                    yield name, n.lineno, kind, {k.arg for k in n.keywords}

def test_every_context_event_declares_reshape_at_its_fire_site():
    """context.{ledger,repeat,anchor}_dedup and deorphaned rewrote model-visible content but never reached the operator's turn
    line (the label lived in a hand-kept map elsewhere): each context.* emit declares `reshape=` or is a measurement."""
    assert [f"{f}:{ln} {k}" for f, ln, k, kw in emits()
            if k.startswith("context.") and k not in NOT_A_RESHAPE and not kw & {"reshape", "steer"}] == []
