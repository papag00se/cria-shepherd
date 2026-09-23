"""Read-only tools for the planner's GATHER phase + the repeated-search guard.

Ported from codex-local's ``reasoned_guidance`` + ``local_web_search``. Before it
plans, the planner (a local model) is given a READ-ONLY tool subset so it can LOOK
first — fetch an API's docs, read existing files, inspect the workspace — then emit
a plan grounded in what it found instead of guessing (the stub problem). Read-only
BY CONSTRUCTION: a write/mutate shell command is refused; building is the coder's job.

The repeated-search guard is the "hard nudge": a web_search that essentially repeats
one already made this gather is refused as an **HTTP 400** — the native "bad request,
don't repeat" idiom an HTTP tool speaks — so a small model can't burn the whole gather
re-searching the same terms. Search results don't change turn to turn, so a repeat is
pure wasted inference. When the repeated query names a domain, the refusal steers it to
FETCH the domain directly instead.

Stdlib only: ``urllib`` for web_fetch + Brave search, ``subprocess`` for the read-only
shell.
"""

from __future__ import annotations

import json
import os

from . import content_reduce
import re
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import brave, prompts, webfetch, wsview
from .searchloop import first_domain_in, normalize_search, searches_match

# The READ-ONLY tools offered to the planner (inline schemas — local models are lenient). No
# write/patch/exec tools at all: planning is not building, and cria cannot run a command on the
# machine the workspace lives on (see the exec branch of execute_tool). The model-facing
# DESCRIPTIONS live in prompts/planner_tool_descs.txt (loaded at import; restart re-tunes); the
# schemas stay here.
_TD = prompts.load_map("planner_tool_descs")
PLANNER_TOOLS = [
    {"type": "function", "function": {"name": "list_dir", "description": _TD["list_dir"], "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "workspace-relative directory, default '.'"}}, "required": []}}},
    {"type": "function", "function": {"name": "grep_files", "description": _TD["grep_files"], "parameters": {"type": "object", "properties": {"pattern": {"type": "string", "description": "a regular expression"}, "path": {"type": "string", "description": "workspace-relative directory to search under, default '.'"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "read_file", "description": _TD["read_file"], "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "web_fetch", "description": _TD["web_fetch"], "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "web_search", "description": _TD["web_search"], "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]

# Match the coder-side cap (webfetch.MAX_BODY_BYTES). This path was left at the old 512 KiB and,
# unlike its sibling, never detected the cut: it read exactly the cap and decoded whatever came back,
# so a spec whose `paths` block sits past 512 KiB arrived as valid-looking front matter with the
# endpoints missing. Worse, the truncated bytes then went through `_record_fetch` → `_structure_of`,
# where broken JSON simply fails to parse, so the durable ledger handed the CODER a 2xx with no
# routes — indistinguishable from "this page isn't a spec".
_FETCH_MAX_BYTES = webfetch.MAX_BODY_BYTES
# Ask Brave for as many results as it will return (its API clamps to 20 in brave.query_url), so a
# planner's gather sees the fuller result set rather than an arbitrary 5. The count is disclosed in
# format_results so the model knows how many landed.
_SEARCH_COUNT = 20
# Above this, a result list goes to the scratchpad instead of the context. Titles+URLs
# still ride inline; it is the snippet bodies that carry the unrelated vocabulary.
_SEARCH_INLINE_CHARS = 1500

@dataclass(frozen=True)
class ToolResult:
    """One gather tool call: its visible text, whether it taught the planner, and whether a
    workspace-file answer is still pending.

    ``learned`` is stated by the code that ran the tool — it knows whether the command printed
    anything, whether the file opened, whether the fetch answered — so the caller never has to
    re-derive it by reading the text. That distinction is load-bearing: measured (run 0727-090143),
    an empty workspace answered `ls -la` and `find` with nothing, the gather counted two calls as
    having researched, and the planner drafted from memory and invented an endpoint the coder then
    built. A refusal, an error, and a command that printed nothing are all calls that taught it
    nothing.

    ``pending`` is narrower: only a workspace ``read_file`` whose bytes have not reached the view
    yet sets it. Its result is neither a file answer nor a repeatable refusal; the next harness
    survey may carry the requested bytes. An empty or missing file is answered even though it may
    not have taught the planner anything."""
    text: str
    learned: bool
    pending: bool = False


def _nothing(text: str) -> ToolResult:
    return ToolResult(text, False)


def execute_tool(name: str, args: dict, cwd: str, search_key: str, recent_searches: list, rlog,
                 scratch: str | None = None, facts: dict | None = None) -> ToolResult:
    """Run ONE planner tool call → the text for the gather loop to feed back, plus whether anything
    came back (:class:`ToolResult`). Reads anything; may WRITE only to a scratchpad (``scratch`` or
    /tmp), never the workspace, so the reasoner can persist and process fetched data.
    ``recent_searches`` is the per-gather list of normalized search word-sets the 400 guard uses
    (mutated in place). ``facts`` (mutated in place) collects what each successful fetch PROVED, so
    the gather's findings outlive the gather — see :func:`_record_fetch`."""
    if name in ("exec_command", "shell", "bash", "local_shell"):
        # NO SHELL. cria used to run `bash -lc` here, in the coder's workspace, with cria's own
        # process — which is a statement about the machine CRIA runs on, not the one the work
        # happens on. There is no way to route it: this loop is synchronous inside one request and
        # cria has no channel to the harness until it replies. So the capability is gone rather
        # than faked, and the planner is told which tools answer the same questions.
        return _nothing(prompts.fill(prompts.load_map("planner_steers")["no_shell"],
                                     cmd=str(args.get("cmd") or args.get("command") or "")[:200]))
    if name in ("list_dir", "ls"):
        return _list_dir(args, cwd)
    if name in ("grep_files", "grep", "search_files"):
        return _grep_files(args, cwd, scratch)
    if name in ("read_file", "cat_file"):
        return _read_file(args, cwd, scratch)
    if name == "web_fetch":
        return _web_fetch(args, facts, scratch)
    if name in ("web_search", "local_web_search"):
        return _web_search(args, search_key, recent_searches, facts, scratch)
    return _nothing(prompts.fill(prompts.load_map("planner_steers")["unknown_tool"], tool=name,
                                 tools=", ".join(t["function"]["name"] for t in PLANNER_TOOLS)))


# How much of a grep result the planner is handed. A gather that reads the whole repo back through
# one tool call is the 210K-prompt shape; the planner narrows and reads the file it wants.
# A HIT CAP THAT SAYS SO. The walk `break`s out of every loop when it fills, so files after that
# point are never opened — and `unread` (which this function does disclose) under-counts them too.
# A 60-hit result read exactly like an exhaustive search that found sixty things, which is the
# failure this function's own docstring names for the OTHER partiality it discloses.
_GREP_MAX_HITS = 60
# AND IT SAYS SO WHEN IT FILLS. The comment above has named this defect since the cap was written
# and the code never said it out loud: a 60-hit answer was indistinguishable from an exhaustive
# search that found sixty things, so the planner read a partial result as the whole truth (#5b).
_GREP_CAPPED = (f"[the search stopped at {_GREP_MAX_HITS} matches — this is NOT the complete set, "
                "and files after this point were never opened. Narrow the pattern or the path.]")


def _scratch_read(full: str, scratch: str | None) -> str | None:
    """The file's text when it is one CRIA ITSELF wrote to its own scratchpad, else None.

    This is not a hole in the harness rule. The gather's scratchpad is cria's own directory on
    cria's own machine — where a fetched spec is spilled so a 57K document does not ride in the
    prompt — and the planner is the one reader of it. The workspace, which belongs to the harness,
    is never reachable this way: the path must be inside the scratchpad cria created for this
    gather, and nothing else is read."""
    if not scratch:
        return None
    import os as _os
    root = _os.path.realpath(scratch)
    try:
        real = _os.path.realpath(full)
        if real != root and not real.startswith(root + _os.sep):
            return None
        with open(real, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _scratch_grep(full: str, rx, scratch: str | None) -> str | None:
    """:func:`_scratch_read`'s sibling for a pattern search over the gather's own scratchpad."""
    if not scratch:
        return None
    import os as _os
    root = _os.path.realpath(scratch)
    try:
        real = _os.path.realpath(full)
        if real != root and not real.startswith(root + _os.sep):
            return None
        targets = ([real] if _os.path.isfile(real)
                   else [_os.path.join(d, n) for d, _s, fs in _os.walk(real) for n in sorted(fs)])
    except OSError:
        return None
    hits: list[str] = []
    for t in targets:
        try:
            with open(t, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
        except OSError:
            continue
        for i, line in enumerate(body.splitlines(), 1):
            if rx.search(line):
                hits.append(f"{_os.path.relpath(t, root)}:{i}: {line.strip()}")
                if len(hits) >= _GREP_MAX_HITS:
                    return "\n".join(hits + [_GREP_CAPPED])
    return "\n".join(hits) if hits else "[no match]"


def _list_dir(args: dict, cwd: str) -> ToolResult:
    """What is in a workspace directory — the half of the retired shell the planner actually used."""
    import os
    path = str(args.get("path") or args.get("dir") or ".")
    full = path if os.path.isabs(path) else os.path.join(cwd or ".", path)
    view = wsview.current(cwd)
    entries = view.scandir(full)
    if entries is None:
        if view.isdir(full) is False:
            return _nothing(f"[list_dir: {path} is not a directory]")
        return _nothing(prompts.fill(prompts.load_map("planner_steers")["not_yet_known"], path=path))
    lines = [f"{e.name}/" if e.is_dir() else f"{e.name} ({e.size} B)" for e in entries]
    if lines:
        return ToolResult("\n".join(lines), True)
    # AN EMPTY LIST FROM A BOUNDED SURVEY IS NOT AN EMPTY DIRECTORY — see the sibling in
    # verifytools. `scandir` returns what cria KNOWS, and a root the survey folded to a count
    # answers `[]`. The not-yet-known wording above is the honest one and simply never reached it.
    if not view.listed_everything(full):
        return _nothing(prompts.fill(prompts.load_map("planner_steers")["not_yet_known"], path=path))
    return ToolResult(f"{path}: empty directory", False)


def _grep_files(args: dict, cwd: str, scratch: str | None = None) -> ToolResult:
    """Lines matching a pattern across the workspace — the other half of the retired shell.

    Only files whose bytes cria has actually been told are searched, and the answer SAYS how many
    it could not read. A silent partial search reads exactly like an exhaustive one that found
    nothing, and the planner would draft against the difference (#5b)."""
    import os
    import re as _re
    pattern = str(args.get("pattern") or args.get("query") or "")
    if not pattern:
        return _nothing("[grep_files error: no pattern]")
    try:
        rx = _re.compile(pattern)
    except _re.error as e:
        return _nothing(f"[grep_files error: bad pattern: {e}]")
    path = str(args.get("path") or ".")
    full = path if os.path.isabs(path) else os.path.join(cwd or ".", path)
    scratched = _scratch_grep(full, rx, scratch)
    if scratched is not None:
        return ToolResult(scratched, "no match" not in scratched)
    view = wsview.current(cwd)
    tree = view.walk(full, skip_hidden=True)
    if tree is None:
        return _nothing(prompts.fill(prompts.load_map("planner_steers")["not_yet_known"], path=path))
    hits: list[str] = []
    unread = 0
    for dirpath, _dirnames, filenames in tree:
        for name in sorted(filenames):
            fp = os.path.join(dirpath, name)
            body = view.read(fp)
            if body is None:
                unread += 1
                continue
            rel = os.path.relpath(fp, cwd or full)
            for i, line in enumerate(body.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{i}: {line.strip()}")
                    if len(hits) >= _GREP_MAX_HITS:
                        break
            if len(hits) >= _GREP_MAX_HITS:
                break
        if len(hits) >= _GREP_MAX_HITS:
            break
    out = "\n".join(hits) if hits else f"[no match for {pattern}]"
    if len(hits) >= _GREP_MAX_HITS:
        out += "\n" + _GREP_CAPPED
    if unread:
        out += f"\n[{unread} file(s) under {path} could not be read — this search is not exhaustive]"
    return ToolResult(out, bool(hits))


def _read_file(args: dict, cwd: str, scratch: str | None = None) -> ToolResult:
    path = args.get("path") or args.get("file_path") or ""
    if not path:
        return _nothing("[read_file error: no path]")
    import os
    full = path if os.path.isabs(path) else os.path.join(cwd or ".", path)
    scratched = _scratch_read(full, scratch)
    if scratched is not None:
        return ToolResult(scratched, bool(scratched.strip()))
    view = wsview.current(cwd)
    # Full file — the section the planner must modify may be past any fixed clip. The context floor
    # bounds the window losslessly-first if this file is large.
    raw = view.read_bytes(full)
    if raw is None:
        if view.isfile(full) is False:
            return _nothing(f"[read_file: {path} does not exist]")
        undeliverable = view.undeliverable_size(full)
        if undeliverable is not None:
            return _nothing(prompts.fill(prompts.load_map("planner_steers")["body_undeliverable"],
                                         path=path, size=str(undeliverable)))
        # Only a demand actually queued for the next survey is pending.  ``read_bytes`` also
        # returns None for a known-undeliverable body; deferring that answer would emit surveys
        # forever even though no future survey can supply its bytes at the same size.
        return ToolResult(prompts.fill(prompts.load_map("planner_steers")["not_yet_known"], path=path),
                          False, pending=view.body_pending(full))
    body = raw.decode("utf-8", errors="replace")
    if content_reduce.looks_binary(body) or content_reduce.binary_kind(raw[:16]):
        return ToolResult(content_reduce.binary_note(len(raw), content_reduce.binary_kind(raw[:16])), True)
    return ToolResult(body, bool(body.strip()))


# ------------------------------------------------------------------ web fetch / search

def _web_fetch(args: dict, facts: dict | None = None, scratch: str | None = None) -> ToolResult:
    """Fetch through the SHARED fetcher, reduce MIME-aware, and hand back something that FITS.

    This used to read the socket itself and return the whole decoded body, trusting a comment that
    said "the context floor reduces it if it's large for the window". The floor cannot: truncating
    model-read content is forbidden, so a single tool message larger than the window has no lossless
    reduction left and goes out whole. Measured (run 0727-123534): a 340,951-char page produced
    `msg_before=108954 msg_after=108954` against a 49,152 window, llama.cpp returned 400, and the
    planner spent all three retries on it and produced NO PLAN.

    So a doc bigger than one page takes the coder's route: written IN FULL to the planner's own
    scratchpad — never the workspace — with a pointer and an outline back. Nothing is truncated;
    it moves from the context to a file the gather can grep with the tools it already has."""
    url = str(args.get("url") or "").strip()
    if not url:
        return _nothing("[web_fetch error: no url]")
    try:
        r = webfetch.fetch(url)
    except Exception as e:  # network, TLS, bad scheme — surface the cause, don't crash the gather
        return _nothing(f"[web_fetch error: {e}]")
    reduced, parsed = webfetch.reduce_for_cache(r.body, r.content_type, r.final_url)
    webfetch._cache_put(r.final_url, r.status, r.content_type, reduced, parsed, r.truncated)
    _record_fetch(facts, r.final_url, r.status, reduced, r.content_type)
    note = (f"\n[TRUNCATED at {webfetch.MAX_BODY_BYTES // (1024 * 1024)} MB — this document is "
            f"longer than that and the rest was not read; anything defined past this point "
            f"is missing, so do not read this as the whole document]" if r.truncated else "")
    # The coder is told when a page yielded no endpoints (b862402); the PLANNER — the one still
    # LOOKING for the spec — was not: 0 of 16 planner prompts in run 0727-163703 carried it. Measured
    # across runs 0727-142536/-153326/-163703, the gather fetched a swagger UI SHELL, got a 200 and
    # readable text, and drafted a plan presupposing "the resolve endpoint"; a hardener downstream
    # then turned that phrase into a concrete 404-ing route. Additive (a true sentence, never an
    # action) and self-limiting: only while cria knows NO routes at all — once any spec has been read
    # it goes quiet, because then the planner has something real to plan against.
    note += _no_structure_note(facts, parsed)
    if len(reduced) > webfetch.OVERSIZE_CHARS:
        spilled = _spill_to_scratch(r, reduced, parsed, scratch)
        if spilled is not None:
            return ToolResult(spilled + note, True)
    return ToolResult(f"HTTP {r.status} \u00b7 {r.final_url}\n{reduced}{note}", True)


def _search_no_structure_note(facts: dict | None) -> str:
    """The search-result flavor of the no-routes disclosure — same condition, same silence rule as
    :func:`_no_structure_note`, worded for snippets (a search that answered is still not a SOURCE)."""
    if facts is None:
        return ""
    if any((e[1] if len(e) > 1 else "") for e in facts.values()):
        return ""
    return prompts.load_map("planner_steers")["search_no_structure"]


def _no_structure_note(facts: dict | None, parsed=None) -> str:
    """Disclose an unstructured page only when the shared fetcher established that fact."""
    if facts is None or parsed is not None:
        return ""
    if any((e[1] if len(e) > 1 else "") for e in facts.values()):
        return ""
    return prompts.load_map("planner_steers")["fetch_no_structure"]


def _spill_to_scratch(r, reduced: str, parsed, scratch: str | None) -> str | None:
    """Write a too-large doc to the gather's scratchpad and return the pointer message; None if it
    could not be written (then the caller inlines it — a fetch that reached the model as nothing at
    all would be worse than one that costs context)."""
    content = webfetch.spill_content(reduced, parsed, r.content_type)
    try:
        root = scratch or tempfile.mkdtemp(prefix="gather-docs-")
        os.makedirs(root, exist_ok=True)
        target = os.path.join(root, os.path.basename(webfetch._spill_name(r.final_url)))
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError:
        return None
    return prompts.fill(prompts.load_map("planner_steers")["fetch_spill"],
                        status=str(r.status), url=r.final_url, chars=f"{len(content):,}",
                        target=target, outline=webfetch.spill_outline(parsed, target),
                        remedy=spill_remedy(target))


def spill_remedy(target: str) -> str:
    """How to read a spilled file, in the names of the tools THIS SEAT HOLDS.

    The two spill notes used to say "exec_command: grep -n 'pattern' <file>" and "read_file it with a
    line range" — to a reader with no exec tool at all (this module's own `no_shell` refusal says so)
    and a read_file whose schema takes a path and nothing else. A remedy the reader cannot take is
    worse than none: it spends the model's turns proving cria wrong. So the clause is generated from
    PLANNER_TOOLS, and when the menu holds no way to read a file it says that instead (#R5)."""
    names = {t["function"]["name"] for t in PLANNER_TOOLS}
    m = prompts.load_map("planner_steers")
    if "read_file" not in names:
        return m["remedy_none"]
    key = "remedy_grep_read" if "grep_files" in names else "remedy_read"
    return prompts.fill(m[key], target=target)


def _record_fetch(facts: dict | None, url: str, status, body: str, content_type) -> None:
    """Keep what this fetch really PROVED, as ``url -> (status, routes, fields)``.

    The gather's findings used to die with the gather: the planner's transcript is thrown away once
    the plan is drafted, so a spec it had genuinely READ never reached the coder. Measured (run
    0726-221401): at gather call 4 the planner held the real spec — `/handles/{handle}` AND
    `/holders/{address}`, the exact two endpoints that task needs — the plan it then wrote named
    neither, and the coder, never shown them, invented `/handle/{handle}` and 404'd. cria had the
    ground truth in hand and dropped it on the floor.

    Same ``(status, routes, fields)`` tuple the coder-side durable ledger uses, so these merge
    straight into it. Routes/fields are SHAPE-detected by the shared extractors — empty for a doc
    that isn't spec-shaped, so nothing is invented for an ordinary page. Only a 2xx is recorded: a
    fetch that failed proved nothing (a 404 restated as a fact is how a hallucinated endpoint became
    'ground truth' once already)."""
    if facts is None or not str(status).startswith("2"):
        return
    parsed = webfetch._structure_of(body, content_type, url)
    routes = webfetch._endpoint_routes(parsed) if parsed is not None else []
    fields = webfetch._endpoint_response_fields(parsed) if parsed is not None else []
    # ONE shape per LINE — the same separator the coder-side producer uses. Both fill this field and
    # both merge into one ⟦ctx:facts⟧ anchor, and the reader's contract is line-based (`_shape_block`:
    # "entry lines are the ones carrying →"). Joined with "; " instead, five endpoint shapes reached
    # the coder as 1,534 unbroken characters under a heading telling it to use these EXACT names.
    facts[url] = (f"HTTP {status}", ", ".join(routes), "\n".join(fields))


def _web_search(args: dict, search_key: str, recent: list, facts: dict | None = None,
                scratch: str | None = None) -> ToolResult:
    query = str(args.get("query") or args.get("q") or "").strip()
    if not query:
        return _nothing("[web_search error: no query]")
    blocked = gate_search(recent, query)  # the 400 hard-nudge on a repeat
    if blocked is not None:
        return _nothing(blocked)          # a refusal of a repeat returns no NEW information
    if not (search_key or "").strip():
        return _nothing(prompts.load_map("planner_steers")["no_search_key"])
    try:
        # The no-routes disclosure rides SEARCH results too (run 0728-m11): a gather whose ONLY tool
        # was web_search never saw the note — it was attached to fetch results alone — so the planner
        # drafted a concrete invented route from snippets and the coder built a 404. Snippets are
        # pointers, not the source (the same sentence the coder-side doctrine already carries); the
        # note stays exactly while cria knows no routes and goes quiet the moment any spec is read.
        note = _search_no_structure_note(facts)
        body = format_results(query, brave_search(search_key, query, _SEARCH_COUNT))
        # SPILL, exactly as the fetch sibling does. Twenty results of titles+snippets is thousands of
        # characters of OTHER people's words, and a search is speculative by nature — the model asked
        # "what is out there", not "give me this document". Measured on run 20260801T225200: one
        # web_search for "README.md generation guide install run script tests" put 9,269 characters
        # into the planner's context — npm packages, Reddit threads, jest configs, valkey test docs —
        # none of it about the task. It then survived into the compaction note and was still there,
        # verbatim, at call 0004. The list stays reachable in full on disk; what rides in the context
        # is the pointer plus the titles.
        spilled = _spill_search(query, body, scratch)
        return ToolResult((spilled if spilled is not None else body) + note, True)
    except Exception as e:
        return _nothing(f"[web_search error: {e}]")


def _spill_search(query: str, body: str, scratch: str | None) -> str | None:
    """Save a search result list to the scratchpad and return the pointer + the titles, or None when
    it is small enough to inline. Same contract as :func:`_spill_to_scratch` for fetches."""
    if scratch is None or len(body) <= _SEARCH_INLINE_CHARS:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:60] or "search"
    target = os.path.join(scratch, f"search-{slug}.txt")
    try:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(body)
    except OSError:
        return None
    titles = "\n".join(ln for ln in body.splitlines()
                       if ln[:2].strip().rstrip(".").isdigit() or ln.startswith("Search results for:"))
    return prompts.fill(prompts.load_map("planner_steers")["search_spill"],
                        query=query, chars=f"{len(body):,}", target=target, titles=titles,
                        remedy=spill_remedy(target))


def brave_search(api_key: str, query: str, count: int = _SEARCH_COUNT) -> list[dict]:
    """One Brave Search GET. Returns a list of {title,url,description}. Endpoint/encoding/headers
    come from the shared `brave` module so the writeproxy's shell web_search can't diverge."""
    req = urllib.request.Request(brave.query_url(query, count), headers=brave.headers(api_key))
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    results = ((data.get("web") or {}).get("results")) or []
    return [{"title": x.get("title", ""), "url": x.get("url", ""), "description": x.get("description", "")}
            for x in results]


def format_results(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results for query: {query}"
    # Disclose the count so the model knows how many results landed (Brave caps a request at 20).
    out = f"Search results for: {query} ({len(results)} results)\n"
    for i, r in enumerate(results, 1):
        out += f"\n{i}. {r['title']}\n   {r['url']}\n   {(r['description'] or '').strip()}\n"
    return out


# ------------------------------------------------------------------ repeated-search 400 guard

def gate_search(recent: list, query: str) -> str | None:
    """Decide whether this search runs or is refused as a repeat of one already made
    this gather. ``recent`` is a list of normalized word-sets (mutated in place). Returns
    ``None`` to proceed (and records the query), or the HTTP-400 refusal text to block."""
    words = normalize_search(query)
    if not words:
        return None
    if any(searches_match(words, prev) for prev in recent):
        domain = first_domain_in(query)
        steer = (f"\nThis query names a domain — stop searching ABOUT it and FETCH it directly: "
                 f"web_fetch https://{domain} , then parse the response for what you need."
                 if domain else "")
        return (f'HTTP 400 Bad Request · web_search "{query}"\n'
                f"You've searched this before. Make a major change to your search, or try something else.{steer}")
    recent.append(words)
    if len(recent) > 64:  # bound memory on a pathologically search-heavy gather
        del recent[0:len(recent) - 64]
    return None


# normalize_search / searches_match / first_domain_in now live in cria/searchloop.py (imported
# above) — shared by this planner guard, the live webfetch.gate_search, and loop.py's fingerprinting.
