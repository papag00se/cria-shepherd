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
import re
import subprocess
import urllib.parse
import urllib.request

from . import brave, prompts, webfetch
from .searchloop import first_domain_in, normalize_search, searches_match

# The four READ-ONLY tools offered to the planner (inline schemas — local models are lenient). No
# write/patch/exec-mutate tools: planning is not building. The model-facing DESCRIPTIONS live in
# prompts/planner_tool_descs.txt (loaded at import; restart re-tunes); the schemas stay here.
_TD = prompts.load_map("planner_tool_descs")
PLANNER_TOOLS = [
    {"type": "function", "function": {"name": "exec_command", "description": _TD["exec_command"], "parameters": {"type": "object", "properties": {"cmd": {"type": "string", "description": "the command line"}}, "required": ["cmd"]}}},
    {"type": "function", "function": {"name": "read_file", "description": _TD["read_file"], "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "web_fetch", "description": _TD["web_fetch"], "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "web_search", "description": _TD["web_search"], "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]

_FETCH_MAX_BYTES = 512 * 1024
# Ask Brave for as many results as it will return (its API clamps to 20 in brave.query_url), so a
# planner's gather sees the fuller result set rather than an arbitrary 5. The count is disclosed in
# format_results so the model knows how many landed.
_SEARCH_COUNT = 20


def execute_tool(name: str, args: dict, cwd: str, search_key: str, recent_searches: list, rlog,
                 scratch: str | None = None, facts: dict | None = None) -> str:
    """Run ONE planner tool call and return human-readable text for the gather loop to feed
    back. Reads anything; may WRITE only to a scratchpad (``scratch`` or /tmp), never the
    workspace, so the reasoner can persist and process fetched data. ``recent_searches`` is the
    per-gather list of normalized search word-sets the 400 guard uses (mutated in place). ``facts``
    (mutated in place) collects what each successful fetch PROVED, so the gather's findings outlive
    the gather — see :func:`_record_fetch`."""
    if name in ("exec_command", "shell", "bash", "local_shell"):
        return _exec_command(args, cwd, scratch)
    if name in ("read_file", "cat_file"):
        return _read_file(args, cwd)
    if name == "web_fetch":
        return _web_fetch(args, facts)
    if name in ("web_search", "local_web_search"):
        return _web_search(args, search_key, recent_searches)
    return prompts.fill(prompts.load_map("planner_steers")["unknown_tool"], tool=name)


# ------------------------------------------------------------------ shell / files

def _exec_command(args: dict, cwd: str, scratch: str | None = None) -> str:
    cmd = args.get("cmd") or args.get("command") or ""
    if isinstance(cmd, list):
        cmd = " ".join(str(c) for c in cmd)
    cmd = str(cmd).strip()
    if not cmd:
        return "[no command given]"
    ok, why = is_gather_safe_command(cmd, scratch, workspace=cwd)
    if not ok:
        return prompts.fill(prompts.load_map("planner_steers")["refused_command"], cmd=cmd, why=why)
    # cwd stays the WORKSPACE so reads (ls/grep/find the codebase) resolve there; writes are
    # confined to the scratchpad by the gate above. TMPDIR points tempfile-using tools at scratch.
    env = dict(os.environ)
    if scratch:
        env["TMPDIR"] = scratch
    # A workspace that doesn't exist (a fresh build — no repo dir yet) is not a valid cwd, so
    # subprocess can't even launch and EVERY command dies with "failed to launch". Fall back to
    # the scratchpad and tell the planner the workspace is empty — so it plans to CREATE files
    # rather than inspect a repo that isn't there. An UNKNOWN cwd (harness advertised none) falls back
    # the SAME way — NEVER to "." (cria's OWN source tree): a gather ls/grep against cria's repo would
    # feed the planner cria's files as if they were the user's project.
    fresh = not cwd or not os.path.isdir(cwd)
    run_cwd = (scratch or ".") if fresh else cwd
    try:
        out = subprocess.run(["bash", "-lc", cmd], cwd=run_cwd, stdin=subprocess.DEVNULL,
                             capture_output=True, text=True, timeout=20, env=env)
        # Full stdout+stderr — the failing assertion / the one grep match the planner needs may be
        # past any fixed clip. The context floor (upstream._prep) bounds the window losslessly-first
        # if this is large; a blind byte-cut here would be a lie the reasoner can't detect.
        text = (out.stdout + out.stderr).strip() or "[no output]"
        if fresh:
            text += "\n" + prompts.fill(prompts.load_map("planner_steers")["fresh_note"], cwd=cwd)
        if "No such file" in text and re.search(r"/tmp/|" + re.escape(scratch or "\0"), cmd):
            text += "\n" + prompts.load_map("planner_steers")["scratch_note"]
        return text
    except subprocess.TimeoutExpired as e:
        # Keep whatever the command DID print before the clock ran out — a test that printed its
        # failing assertion and then hung, or a build that logged its error before stalling, has already
        # said the useful thing. Returning the bare notice threw that away, contradicting the never-clip
        # rule three lines above. (TimeoutExpired carries bytes or str depending on text=; normalize.)
        def _txt(v):
            if not v:
                return ""
            return v if isinstance(v, str) else v.decode("utf-8", "replace")
        partial = (_txt(e.stdout) + _txt(e.stderr)).strip()
        note = f"[exec timed out after {int(e.timeout)}s]"
        return f"{note}\n{partial}" if partial else note
    except OSError as e:
        return f"[exec failed to launch: {e}]"


def _read_file(args: dict, cwd: str) -> str:
    path = args.get("path") or args.get("file_path") or ""
    if not path:
        return "[read_file error: no path]"
    import os
    full = path if os.path.isabs(path) else os.path.join(cwd or ".", path)
    try:
        with open(full, encoding="utf-8", errors="replace") as fh:
            # Full file — the section the planner must modify may be past any fixed clip. The
            # context floor bounds the window losslessly-first if this file is large.
            return fh.read()
    except OSError as e:
        return f"[read_file error: {e}]"


# A conservative ALLOW-LIST for the planner's read-only shell (reject anything else).
_READ_ONLY = {
    "ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "find", "fd", "tree",
    "file", "stat", "du", "pwd", "echo", "printf", "which", "type", "env", "date", "whoami",
    "uname", "basename", "dirname", "realpath", "readlink", "cut", "sort", "uniq", "tr", "nl",
    "tac", "rev", "column", "diff", "cmp", "comm", "od", "xxd", "strings", "jq", "yq", "cd",
    "true", "test", "[",
}
_GIT_READ = {"status", "log", "diff", "show", "ls-files", "branch", "rev-parse", "cat-file",
             "blame", "describe", "remote", "config", "grep"}

# Where the gather MAY write — a scratchpad for processing fetched data. Never the workspace.
_WRITE_ROOTS_BASE = ("/tmp/", "/var/tmp/", "/dev/null", "/dev/stdout", "/dev/stderr")
# Catastrophic ops refused no matter the target — cria runs this shell itself, so its blast
# radius must be bounded (the workspace-wipe lesson: a --yolo model once ran `find . -delete`).
_CATASTROPHIC = re.compile(
    r"(^|[\s|;&(])rm\s+[^|;&]*(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|-rf|-fr)\b[^|;&]*\s(/|~|\$HOME|\.)(\s|/|$)"
    r"|(^|[\s|;&(])find\b[^|;&]*\s-delete\b"
    r"|\bmkfs\b|\bdd\b[^|;&]*\bof=/dev/|:\s*\(\s*\)\s*\{|>\s*/dev/(sd|nvme|mapper)|\bshred\b",
    re.I,
)
# The write operators / mutating bases whose TARGETS must land in the scratchpad. A processor
# with no shell write (python3 -c, jq, awk without redirect) is a read as far as the shell sees.
_REDIR_RE = re.compile(r"(?<![0-9<>&])>>?\s*(?!&)([^\s|;&<>]+)")  # `> f` / `>> f`, not `2>&1`
_MUTATORS = {"rm", "rmdir", "mv", "cp", "mkdir", "touch", "dd", "truncate", "install", "ln",
             "chmod", "chown", "shred", "tee", "rsync"}
# curl/wget flags that name an OUTPUT FILE (value is the NEXT token). Bare `-O` (curl) writes the
# remote filename to the cwd = workspace, so it's always a workspace write.
_NET_OUT_FLAGS = {"-o", "--output", "--output-document", "-P", "--directory-prefix"}


def _net_write_targets(parts: list[str]) -> tuple[list[str], bool]:
    """(output targets, has_bare_curl_O) for a curl/wget segment — only the token AFTER an
    output flag is a target; the URL is not."""
    targets, bare_O = [], False
    for i, p in enumerate(parts):
        if p in _NET_OUT_FLAGS and i + 1 < len(parts):
            targets.append(parts[i + 1])
        elif p == "-O":
            bare_O = True
    return targets, bare_O


def _within(path: str, root: str) -> bool:
    root = os.path.normpath(root)
    return path == root or path.startswith(root.rstrip("/") + "/")


def _under_write_roots(target: str, scratch: str | None, workspace: str | None) -> bool:
    """Is a write target inside the allowed scratchpad (scratch dir or /tmp) AND not inside the
    workspace? The workspace exclusion matters because cria's scratch — and a workspace — can
    both live under /tmp; the invariant is 'scratchpad, never the workspace', not 'under /tmp'."""
    t = target.strip().strip('"\'')
    if t in ("/dev/null", "/dev/stdout", "/dev/stderr"):
        return True
    if not os.path.isabs(t):  # relative → resolves in the WORKSPACE cwd → never allowed
        return False
    ap = os.path.normpath(t)
    if workspace and _within(ap, os.path.abspath(workspace)):  # a /tmp workspace is still off-limits
        return False
    roots = list(_WRITE_ROOTS_BASE)
    if scratch:
        roots.append(os.path.normpath(scratch) + "/")
    return any(_within(ap, r) for r in roots)


def is_gather_safe_command(cmd: str, scratch: str | None = None, workspace: str | None = None) -> tuple[bool, str]:
    """The gather may READ anything but WRITE only to the scratchpad (``scratch`` or /tmp), never
    the ``workspace`` — so a small reasoner can persist and process what it fetched without ever
    touching the user's code. Returns ``(ok, reason)``; the reason names the violation for the
    refusal message. Conservative by construction: an unrecognizable mutation is refused (a
    refused command costs a retry; a slipped workspace write corrupts the user's code)."""
    if _CATASTROPHIC.search(cmd):
        return False, "is a destructive operation"
    for target in _REDIR_RE.findall(cmd):  # every redirect target must be in the scratchpad
        if not _under_write_roots(target, scratch, workspace):
            return False, "would write outside the /tmp scratchpad (into the workspace)"
    for seg in re.split(r"[|;&\n]", cmd):
        parts = seg.strip().split()
        if not parts:
            continue
        base = parts[0].rsplit("/", 1)[-1]
        pathargs = [p for p in parts[1:] if not p.startswith("-")]
        if base == "git" and (parts[1:] and parts[1] not in _GIT_READ):
            return False, "mutates the git repository"
        if base == "sed" and "-i" in seg:
            return False, "edits a file in place"
        if base in ("curl", "wget"):
            targets, bare_O = _net_write_targets(parts)
            if bare_O or not all(_under_write_roots(t, scratch, workspace) for t in targets):
                return False, "would download a file outside the /tmp scratchpad"
        elif base in _MUTATORS:
            # every path this mutator touches must be in the scratchpad (dd uses of=… not argv)
            targets = pathargs + [p.split("=", 1)[1] for p in parts if p.startswith("of=")]
            if not targets or not all(_under_write_roots(t, scratch, workspace) for t in targets):
                return False, "would create/modify a file outside the /tmp scratchpad"
    return True, ""


# ------------------------------------------------------------------ web fetch / search

def _web_fetch(args: dict, facts: dict | None = None) -> str:
    url = str(args.get("url") or "").strip()
    if not url:
        return "[web_fetch error: no url]"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": brave.USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read(_FETCH_MAX_BYTES)
            body = raw.decode("utf-8", "replace")
            status, final = getattr(r, "status", "?"), r.geturl()
            hdrs = getattr(r, "headers", None)
            _record_fetch(facts, final, status, body, hdrs.get("Content-Type") if hdrs else None)
            # Full decoded body (already bounded by the 512KB socket read above) — the endpoint /
            # signature the planner needs may be past any fixed char clip. The context floor
            # reduces it MIME-aware + losslessly-first if it's large for the window.
            return f"HTTP {status} · {final}\n{body}"
    except Exception as e:  # network, TLS, decode — surface the cause, don't crash the gather
        return f"[web_fetch error: {e}]"


# The no-content results this module itself emits. Kept here, next to the code that produces them, so
# the check below is a module recognising its OWN output rather than keyword-matching free text.
NO_CONTENT_PREFIXES = ("[no output]", "[no command given]", "[web_fetch error", "[read_file error",
                       "[web_search error")


def result_is_substantive(text: str) -> bool:
    """Did this tool call actually return anything to LEARN from?

    Measured (run 0727-090143): in an empty workspace the planner ran `ls -la` and `find` — both
    returned nothing — and that counted as having researched, so it drafted from memory and invented
    `/resolve?handle={handle}`. Two calls that returned no bytes are not research. Judged against the
    no-content strings this module emits, never by reading the content itself."""
    t = (text or "").strip()
    return bool(t) and not t.startswith(NO_CONTENT_PREFIXES)


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
    facts[url] = (f"HTTP {status}", ", ".join(routes), "; ".join(fields))


def _web_search(args: dict, search_key: str, recent: list) -> str:
    query = str(args.get("query") or args.get("q") or "").strip()
    if not query:
        return "[web_search error: no query]"
    blocked = gate_search(recent, query)  # the 400 hard-nudge on a repeat
    if blocked is not None:
        return blocked
    if not (search_key or "").strip():
        return prompts.load_map("planner_steers")["no_search_key"]
    try:
        return format_results(query, brave_search(search_key, query, _SEARCH_COUNT))
    except Exception as e:
        return f"[web_search error: {e}]"


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
