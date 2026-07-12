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
import re
import subprocess
import urllib.parse
import urllib.request

# The four READ-ONLY tools offered to the planner (inline schemas — local models are
# lenient). No write/patch/exec-mutate tools: planning is not building.
PLANNER_TOOLS = [
    {"type": "function", "function": {"name": "exec_command", "description": "Run a READ-ONLY shell command to inspect the project (ls, cat, head, tail, grep, find, wc, git status/log/diff, …). Writes/mutations are refused — you are planning, not building.", "parameters": {"type": "object", "properties": {"cmd": {"type": "string", "description": "the command line"}}, "required": ["cmd"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a file's full contents to understand existing code/config/conventions.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "web_fetch", "description": "Fetch a URL (docs, an OpenAPI/JSON schema, a reference page) and return its text.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "web_search", "description": "Search the web for documentation, APIs, or references the task implies.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]

# Matches Brave Browser on Linux desktop (it identifies as Chrome on purpose).
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_FETCH_MAX_BYTES = 512 * 1024


def execute_tool(name: str, args: dict, cwd: str, search_key: str, recent_searches: list, rlog) -> str:
    """Run ONE planner tool call, READ-ONLY, and return human-readable text for the
    gather loop to feed back. ``recent_searches`` is the per-gather list of normalized
    search word-sets the 400 guard uses (mutated in place)."""
    if name in ("exec_command", "shell", "bash", "local_shell"):
        return _exec_command(args, cwd)
    if name in ("read_file", "cat_file"):
        return _read_file(args, cwd)
    if name == "web_fetch":
        return _web_fetch(args)
    if name in ("web_search", "local_web_search"):
        return _web_search(args, search_key, recent_searches)
    return f"[planner has no `{name}` tool — you are read-only: exec_command (read), read_file, web_fetch, web_search]"


# ------------------------------------------------------------------ shell / files

def _exec_command(args: dict, cwd: str) -> str:
    cmd = args.get("cmd") or args.get("command") or ""
    if isinstance(cmd, list):
        cmd = " ".join(str(c) for c in cmd)
    cmd = str(cmd).strip()
    if not cmd:
        return "[no command given]"
    if not is_read_only_command(cmd):
        return (f"[refused: planning is READ-ONLY — `{cmd[:100]}` would write or mutate. "
                "Don't run it; just plan for the coder to do it.]")
    try:
        out = subprocess.run(["bash", "-lc", cmd], cwd=(cwd or "."), stdin=subprocess.DEVNULL,
                             capture_output=True, text=True, timeout=20)
        return _truncate((out.stdout + out.stderr).strip() or "[no output]", 8000)
    except subprocess.TimeoutExpired:
        return "[exec timed out after 20s]"
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
            return _truncate(fh.read(), 8000)
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


def is_read_only_command(cmd: str) -> bool:
    """Conservative read-only gate. Any redirect writes a file; each pipeline segment's
    head must be a known read command (git/curl/wget/sed restricted to read-only uses).
    Erring toward refusal is correct — a refused inspect costs a retry, a slipped mutation
    corrupts the workspace."""
    if ">" in cmd:
        return False
    for seg in re.split(r"[|;&\n]", cmd):
        seg = seg.strip()
        if not seg:
            continue
        parts = seg.split()
        base = parts[0].rsplit("/", 1)[-1]
        sub = parts[1] if len(parts) > 1 else ""
        if base == "git":
            if sub not in _GIT_READ:
                return False
        elif base == "sed":
            if "-i" in seg:
                return False
        elif base in ("curl", "wget"):
            if "-o" in parts or "-O" in parts:
                return False
        elif base not in _READ_ONLY:
            return False
    return True


# ------------------------------------------------------------------ web fetch / search

def _web_fetch(args: dict) -> str:
    url = str(args.get("url") or "").strip()
    if not url:
        return "[web_fetch error: no url]"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read(_FETCH_MAX_BYTES)
            body = raw.decode("utf-8", "replace")
            return f"HTTP {getattr(r, 'status', '?')} · {r.geturl()}\n{_truncate(body, 6000)}"
    except Exception as e:  # network, TLS, decode — surface the cause, don't crash the gather
        return f"[web_fetch error: {e}]"


def _web_search(args: dict, search_key: str, recent: list) -> str:
    query = str(args.get("query") or args.get("q") or "").strip()
    if not query:
        return "[web_search error: no query]"
    blocked = gate_search(recent, query)  # the 400 hard-nudge on a repeat
    if blocked is not None:
        return blocked
    if not (search_key or "").strip():
        return "[web_search error: no search API key configured — set planner.search_api_key_env]"
    try:
        return format_results(query, brave_search(search_key, query, 5))
    except Exception as e:
        return f"[web_search error: {e}]"


def brave_search(api_key: str, query: str, count: int = 5) -> list[dict]:
    """One Brave Search GET. Returns a list of {title,url,description}."""
    count = max(1, min(20, count))
    url = _BRAVE_ENDPOINT + "?" + urllib.parse.urlencode({"q": query, "count": count})
    req = urllib.request.Request(url, headers={
        "X-Subscription-Token": api_key, "Accept": "application/json", "User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    results = ((data.get("web") or {}).get("results")) or []
    return [{"title": x.get("title", ""), "url": x.get("url", ""), "description": x.get("description", "")}
            for x in results]


def format_results(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results for query: {query}"
    out = f"Search results for: {query}\n"
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
    if any(_searches_match(words, prev) for prev in recent):
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


# Reused stopwords + naive stemmer from codex-local's loop_detector.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for", "with", "is", "are",
    "was", "were", "be", "been", "i", "ill", "im", "let", "me", "now", "next", "then", "this",
    "that", "it", "its", "so", "will", "would", "can", "need", "needs", "going", "go", "lets",
    "have", "has", "do", "does", "my", "we", "us",
}


def _stem(t: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(t) > len(suf) + 2 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def normalize_search(query: str) -> list[str]:
    """A deduped, sorted set of content words: lowercase, drop apostrophes, split on
    non-word chars but KEEP ``. _ -`` inside tokens so ``api.handle.me`` / ``get_handle``
    stay whole, drop stopwords, light-stem."""
    q = query.lower().replace("'", "").replace("’", "")
    words = {_stem(t) for t in re.split(r"[^a-z0-9._\-]+", q) if t and t not in _STOPWORDS}
    return sorted(words)


def _searches_match(new_q: list[str], prior: list[str]) -> bool:
    """Is ``new_q`` essentially a re-hunt of ``prior`` (rumination) rather than a genuine
    new direction or refinement? Refinement (longer, keeps all but ≤1 prior word) → no;
    exact set → yes; Jaccard ≥ 0.5 with ≥2 shared, or ≥5 shared outright → yes."""
    sn, sp = set(new_q), set(prior)
    if len(sn) > len(sp):
        dropped = sum(1 for w in sp if w not in sn)
        if dropped <= 1:
            return False  # a real narrowing of the same hunt, not a re-hunt
    if sn == sp:
        return True
    overlap = sum(1 for w in sn if w in sp)
    if overlap >= 5:
        return True
    union = len(sn) + len(sp) - overlap
    return overlap >= 2 and union > 0 and (overlap / union) >= 0.5


_FILE_EXTS = {
    "py", "rs", "js", "ts", "jsx", "tsx", "json", "md", "txt", "toml", "yaml", "yml", "go",
    "java", "cpp", "hpp", "sh", "rb", "php", "html", "css", "xml", "csv", "lock", "cfg", "ini",
    "env", "log", "sql",
}


def first_domain_in(query: str) -> str | None:
    """The first bare domain in a query (e.g. ``api.handle.me``), else None — used to
    steer a search-looping model toward fetching the domain. A dotted token whose final
    label is an alphabetic TLD (≥2 chars) that isn't a source-file extension."""
    for tok in re.split(r"[^A-Za-z0-9._\-]+", query):
        tok = tok.strip("._-")
        if _looks_like_domain(tok):
            return tok
    return None


def _looks_like_domain(tok: str) -> bool:
    labels = tok.split(".")
    if len(labels) < 2:
        return False
    tld = labels[-1].lower()
    if len(tld) < 2 or not tld.isalpha() or tld in _FILE_EXTS:
        return False
    return all(lbl and all(c.isalnum() or c == "-" for c in lbl) for lbl in labels)


def _truncate(s: str, cap: int) -> str:
    s = s.strip()
    return s if len(s) <= cap else s[:cap] + f"\n…[truncated at {cap} chars]"
