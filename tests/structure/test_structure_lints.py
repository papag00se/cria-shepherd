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
    found = sliced_into_text()
    check_ratchet(found, BENIGN_SLICES, "bare slice into text")
    # a second use of an allowed (file, expression) is a new cut: the set check alone would absorb it silently
    assert sorted(k for k in found if found.count(k) > 1) == [], "an allowed bare slice is used again: give it its own reason"

SIZE = re.compile(r"(_TOKENS|_RESERVE|_CHARS|_BYTES|_BUDGET|_CAP|_LIMIT|_FLOOR|_MAX|_MIN|_STRIDE|_ENTRIES|_FILES|_DIRS|_SIZE"
                  r"|_MAX_[A-Z_]+|_MIN_[A-Z_]+)$|^(MAX|MIN)_")
# (file, name) -> why the size does not move with the context window; else it must be a windowcaps.Cap. Each reason is a
# transport / safety / one-word / measured fact read from the constant's own comment and history, not a category label.
FIXED_SIZES = {
    ("content_reduce.py", "INLINE_RESULT_MAX_BYTES"): "transport: the harness middle-cuts a result near 10,000 bytes (run 1785893473, 84 prompts); 9,000 leaves its framing room",
    ("content_reduce.py", "COMMAND_ARG_BUDGET"): "transport: a spill reaches the harness disk as ONE command argv string, so a document past this is cut",
    ("externalization.py", "STDOUT_MAX_BYTES"): "transport: complete producer stdout before the harness envelope, same ~10 KB result bound",
    ("filecommands.py", "READ_TRANSPORT_STDOUT_BYTES"): "transport: the harness stdout bound a multipart read must fit in",
    ("multipart.py", "STDOUT_LIMIT"): "transport: the harness stdout bound for one multipart record line",
    ("writeproxy.py", "ECHO_MAX_BYTES"): "measured: one byte bound on a write's echoed window and its report; over it the window shrinks, never cut mid-way",
    ("probegate.py", "TRANSPORT_CHUNK_BYTES"): "transport: 6,000 raw bytes encode to 8,000 chars under the harness's ~9-10 KiB result bound",
    ("probegate.py", "TRANSPORT_RAW_PAGE_MAX"): "safety: caps what one hostile/garbled compressed page may decompress to in memory",
    ("upstream.py", "_REASONING_FLUSH_BYTES"): "measured: a kill loses at most this much reasoning; larger would be a write per token",
    ("toolwire.py", "_RIDE_ALONG_HOST_RESERVE"): "transport: room under the inline bound for the harness's own framing lines",
    ("toolwire.py", "_RIDE_ALONG_COMMAND_RESERVE"): "transport: room under the inline bound for the command text a result rides home on",
    ("wsview.py", "TREE_MAX_ENTRIES"): "transport: survey tree held to the inline result bound less the survey's other sections; a fold is named, a cut is not",
    ("wsview.py", "TREE_MAX_BYTES"): "transport: same inline-bound budget as TREE_MAX_ENTRIES",
    ("wsview.py", "BLOB_BYTES_MAX"): "measured: per-survey body budget bounding a real demand (a 40 KB source file is ordinary)",
    ("wsview.py", "_BODY_CACHE_MAX_BYTES"): "safety: memory bound on the per-(session, root) manifest body cache",
    ("depsurface.py", "MAX_FILE_BYTES"): "safety: bounded read-only scan of a dependency source file, never a full-tree crawl",
    ("depsurface.py", "MAX_ROOT_DIRS"): "safety: bounded directory walk under a declared dependency root (feed-pipeline-java opencsv case)",
    ("apidiscovery.py", "MAX_PROBE_BYTES"): "safety: read far enough that a real schema parses (a 2 MB cut made a real MCP/GraphQL server look empty); a hit is disclosed",
    ("ratelimit.py", "MAX_WAIT_MS"): "safety: the longest a request holds a turn waiting out a stated rate limit; a longer wait is reported, not slept",
    ("ratelimit.py", "_BODY_PROBE_BYTES"): "safety: a refusal body is read this far for a stated delay (the caller still gets the whole body)",
    ("server.py", "MAX_BODY_BYTES"): "safety: the largest request body the HTTP edge reads (real harness requests are under 4 MiB); a larger Content-Length is refused with 413 before any allocation",
    ("webfetch.py", "MAX_BODY_BYTES"): "safety: raw-body read cap raised well past real specs (was 512 KiB); a body beyond it is disclosed as truncated",
    ("groundtruth.py", "DEFAULT_FILE_CAP"): "safety: last-resort valve for a pathologically huge file; the context floor is the window-aware bound",
    ("planner.py", "_GROUND_SCAN_MAX_BYTES"): "safety: bounded sweep; a token this common is found long before",
    ("probeparse.py", "U32_MAX"): "external: Rust u32::MAX, parse_u32 mirrors str::parse::<u32>()",
    ("probediscovery.py", "MAX_FLOOR_FILES_PER_LANG"): "safety: pathological-tree / ARG_MAX ceiling, far above any real source tree (the old 40-file clip let syntax errors escape)",
    ("system1.py", "MAX_WINDOW_TOKENS"): "external: the frozen classifier model's own input window",
    ("system1.py", "WEIGHT_BUDGET_BYTES"): "measured: bundle graph + weights must stay under this on the actual files",
    ("system1.py", "ARENA_BUDGET_BYTES"): "safety: quadratic attention could ask for a 32 GiB buffer; the allocator refuses, the caller declines",
    ("system1.py", "_MIN_ARENA_BUDGET_BYTES"): "safety: floor for the configurable arena budget",
    ("filepresence.py", "MAX_TOKENS"): "one-word: a claim list is a line per file name; a few hundred tokens covers any briefing",
    ("loop.py", "COMPACTION_VERDICT_RESERVE"): "measured: a lens answers ONE word; 16,384 held back starved 12 of 33 judge-shaped floor reductions (ornith-java captures 2026-10-26..28)",
    ("loop.py", "ask_closed(max_tokens=)"): "one-word: a closed question's single-verdict reply",
    ("dedup.py", "MIN_RUN_CHARS"): "measured: a fold pointer costs ~30 tokens; a shorter run is not worth folding",
    ("handoffdistill.py", "FRAME_TOKENS"): "measured: instruction + intro + ask frame around a composed request (~1.9K measured)",
    ("planner_tools.py", "_SEARCH_INLINE_CHARS"): "measured: above this a result list spills to the scratchpad; titles and URLs still ride inline",
    ("generationguards.py", "DEFAULT_REASONING_BUDGET"): "detector tuning, no recorded measurement: reasoning tokens before a ruminating stream is steered; a width on the stream's own text, not a share of the prompt window",
    ("generationguards.py", "DEGENERATE_RUN_CHARS"): "detector tuning, no recorded measurement: smallest repeated run read as degeneration; a width on the stream's own text, not a share of the prompt window",
    ("generationguards.py", "WIDE_RUN_CHARS"): "detector tuning, no recorded measurement: wide-period repetition detector window; a width on the stream's own text, not a share of the prompt window",
    ("generationguards.py", "WIDE_EVAL_STRIDE"): "detector tuning, no recorded measurement: how often the wide detector is evaluated; a width on the stream's own text, not a share of the prompt window",
    ("generationguards.py", "WIDE_MIN_CHARS"): "detector tuning, no recorded measurement: least text before the wide detector may judge; a width on the stream's own text, not a share of the prompt window",
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
    assert all(FIXED_SIZES.values()), "every fixed size names its reason"
    check_ratchet(fixed_sizes(), FIXED_SIZES, "fixed size")

NOT_A_RESHAPE = {  # measurement or abstention: nothing was rewritten, so nothing for the operator's ledger. Each entry says which.
    "context.floor_skipped": "abstention: the window is a guess, so the floor declines to run",
    "context.window": "measurement: the window discovered from the server's /props (or why it could not be)",
    "context.calibrated": "measurement: the real/estimated token ratio learned from an accepted prompt",
    "context.refit": "measurement: the server's own rejection of the prompt, with its stated window and the real and estimated counts",
    "context.measured": "measurement: the real prompt token count against the window",
    "context.image_fit_unknown": "abstention: an image's cost is not measured by the text tokenizer, so no fit is claimed",
    "context.image_density_unknown": "abstention: image tokens are not text density, so no ratio is learned"}

def emits():
    for name, tree in trees():
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and n.args and getattr(n.func, "attr", getattr(n.func, "id", "")) in ("emit", "_log"):
                for kind in [a.value for a in n.args[:2] if isinstance(a, ast.Constant) and isinstance(a.value, str)][:1]:
                    yield name, n.lineno, kind, {k.arg for k in n.keywords}

def test_every_context_event_declares_reshape_at_its_fire_site():
    """context.{ledger,repeat,anchor}_dedup and deorphaned rewrote model-visible content but never reached the operator's turn
    line (the label lived in a hand-kept map elsewhere): each context.* emit declares `reshape=` or is a measurement."""
    assert all(NOT_A_RESHAPE.values()) and NOT_A_RESHAPE.keys() <= {k for _, _, k, _ in emits()}, "NOT_A_RESHAPE: every entry needs a reason and a fire site"
    assert [f"{f}:{ln} {k}" for f, ln, k, kw in emits()
            if k.startswith("context.") and k not in NOT_A_RESHAPE and not kw & {"reshape", "steer"}] == []

def test_every_literal_log_level_is_a_severity_the_log_knows():
    """22 fire sites spelled the level "warning" (the table's key is "warn") and one passed a permission setting as the level: 828 records
    in 12 days were scored as info. A literal `level=` at a fire site must name a severity, never a config value."""
    from cria import events
    seen = [(name, kw.value.lineno, kw.value.value) for name, tree in trees() for n in ast.walk(tree) if isinstance(n, ast.Call)
            for kw in n.keywords if kw.arg == "level" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)]
    assert seen, "the scan found no level= literals: the scan is broken, not the code"
    assert [f"{f}:{ln} level={v!r}" for f, ln, v in seen if v not in events._LEVELS] == []
    assert events._UNKNOWN_LEVEL == max(events._LEVELS.values())
