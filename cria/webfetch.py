"""In-process web_fetch for the coder — fetch, MIME-aware reduce, cache, navigate.

Faithful port of codex-local's ``routing/src/web_fetch.rs`` + the navigation half of
``content_reduce.rs`` (``page_from`` / ``find_in`` / ``find_json`` / ``top_level_keys`` /
``resolve_refs`` / ``find_text``) that the earlier ``content_reduce.py`` port deliberately
dropped as "stateless by design".

That de-scope was wrong: **cria runs as a persistent server with memory and file access**,
so it owns the per-URL document cache and executes the fetch ITSELF (``urllib``) instead of
lowering ``web_fetch`` to a harness ``curl`` — which the harness truncates to an unusable
prefix *before* cria can reduce it (the Ada-handle openapi.json incident: a real HTTP 200,
57 KB single-line JSON, cut mid-line, the model rationalised a "404" and looped).

The flow, per the Rust: fetch → ``reduce_lossless`` (HTML→text, JSON minify, YAML→structural)
→ cache by URL → then either PAGE (``cursor`` char-offset, "more remains" footer) or FIND
(``find_json``: subtree + ancestor spine + one-hop ``$ref`` inline; no-match → top-level keys).
A large single-line spec becomes navigable instead of truncated garbage.

**YAML is handled structurally with PyYAML** — the TODO ``content_reduce.rs:8`` handed the
Python port. Parsed YAML becomes the same Python dict/list the JSON path walks, so one set of
navigation code serves both. If PyYAML is absent the doc degrades to text paging, never an error.

Stdlib + PyYAML only. Reuses :mod:`cria.content_reduce` for the already-ported HTML/JSON/text
reducers and the token estimate.
"""
from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

from . import brave
from .content_reduce import est_tokens, html_to_text

try:  # structural YAML is best-effort — the Rust degrades YAML to text too when it can't parse
    import yaml as _yaml
except ImportError:  # pragma: no cover - environment without PyYAML
    _yaml = None

# --- constants (mirrored from web_fetch.rs / content_reduce.rs) ----------------------------
MAX_BODY_BYTES = 512 * 1024          # cap the raw body read (web_fetch.rs MAX_BODY_BYTES)
CONTENT_CAP_TOKENS = 4000            # one page / one find response (WEB_FETCH_CONTENT_CAP_TOKENS)
REQUEST_TIMEOUT_S = 30               # per-request (REQUEST_TIMEOUT_SECS)
USER_AGENT = brave.USER_AGENT        # a real browser UA so ordinary sites don't 403 curl/8.x (curl_ua.rs)
DOC_CACHE_CAP = 32                   # per-URL reduced-doc cache bound (DOC_CACHE_CAP)
FIND_TOP_K = 3                       # best-N find matches returned (FIND_TOP_K)
GUESS_STREAK_THRESHOLD = 3           # consecutive non-2xx before the stop-guessing nudge


@dataclass
class FetchResult:
    status: int
    final_url: str
    content_type: Optional[str]
    body: str
    truncated: bool


# --- the fetch (web_fetch.rs::fetch) -------------------------------------------------------

def fetch(url: str, user_agent: Optional[str] = None) -> FetchResult:
    """One GET with a browser UA, size cap, timeout. http/https only (the Rust rejects other
    schemes; here it also closes urllib's ``file://`` handler). Raises ``ValueError`` on a bad
    URL/scheme, ``OSError``/``urllib.error.URLError`` on a transport failure."""
    trimmed = (url or "").strip()
    if not trimmed:
        raise ValueError("web_fetch: url must not be empty")
    scheme = trimmed.split("://", 1)[0].lower() if "://" in trimmed else ""
    if scheme not in ("http", "https"):
        raise ValueError(f"web_fetch: unsupported scheme '{scheme or trimmed[:12]}': only http/https")
    req = urllib.request.Request(trimmed, headers={
        "User-Agent": user_agent or USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
    })
    # Non-2xx must still yield the body (api.handle.me serves real docs on its 404) — HTTPError
    # IS a response object, so catch it and read it exactly like a 200.
    try:
        resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S)  # noqa: S310 (scheme guarded above)
    except urllib.error.HTTPError as e:
        resp = e
    with resp:
        status = int(getattr(resp, "status", 0) or getattr(resp, "code", 0) or 0)
        final_url = resp.geturl()
        content_type = resp.headers.get("Content-Type")
        raw = resp.read(MAX_BODY_BYTES + 1)
    truncated = len(raw) > MAX_BODY_BYTES
    slice_ = raw[:MAX_BODY_BYTES] if truncated else raw
    if _is_text_content_type(content_type):
        body = slice_.decode("utf-8", "replace")
    else:
        body = f"[non-text response: {len(raw)} bytes, content-type={content_type or '(none)'}]"
    return FetchResult(status, final_url, content_type, body, truncated)


def _is_text_content_type(ct: Optional[str]) -> bool:
    if ct is None:
        return True  # no header → optimistically decode as text (Rust is_text_content_type)
    ct = ct.split(";", 1)[0].strip().lower()
    return (ct.startswith("text/") or ct in ("application/json", "application/xml",
            "application/xhtml+xml", "application/javascript", "application/x-yaml", "text/yaml")
            or ct.endswith("+json") or ct.endswith("+xml") or ct.endswith("yaml"))


# --- MIME-aware lossless reduce (content_reduce.rs::reduce_lossless + YAML) -----------------

def _is_yaml(ct: Optional[str], url: str) -> bool:
    c = (ct or "").lower()
    return "yaml" in c or url.lower().rsplit("?", 1)[0].endswith((".yaml", ".yml"))


def reduce_for_cache(body: str, content_type: Optional[str], url: str) -> tuple[str, Optional[Any]]:
    """Lossless, content-aware reduction + the parsed structure (for structural find).
    Returns ``(reduced_text, parsed_or_None)``. HTML→text; JSON/YAML→minified canonical text
    plus the parsed dict/list (so find/outline can walk it); anything else passes through."""
    ct = (content_type or "").lower()
    if "html" in ct or "xml" in ct:
        return html_to_text(body), None
    if "json" in ct:
        try:
            obj = json.loads(body)
            return json.dumps(obj, separators=(",", ":"), ensure_ascii=False), obj
        except (ValueError, TypeError):
            return body, None
    if _is_yaml(content_type, url) and _yaml is not None:
        try:
            obj = _yaml.safe_load(body)
            if isinstance(obj, (dict, list)):
                # canonical, LINE-BASED rendering so paging never cuts mid-line (the seed bug)
                return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False), obj
        except Exception:  # noqa: BLE001 - any YAML parse error → fall through to text
            pass
    return body, None


# --- per-URL cache (web_fetch.rs DOC_CACHE) ------------------------------------------------

_DOC_CACHE: dict[str, tuple[int, Optional[str], str, Optional[Any]]] = {}


def _cache_put(url: str, status: int, ct: Optional[str], reduced: str, parsed: Optional[Any]) -> None:
    if len(_DOC_CACHE) >= DOC_CACHE_CAP and url not in _DOC_CACHE:
        _DOC_CACHE.clear()  # simple bound (Rust clears on overflow too)
    _DOC_CACHE[url] = (status, ct, reduced, parsed)


# --- coder-loop gate state (cria is a persistent server) -----------------------------------
# Exact external fetches/searches already made THIS SESSION (an identical repeat can only return
# what the model has), and the consecutive-failure streak (the stop-guessing nudge). Bounded so a
# long-lived server can't grow unboundedly. Internal/localhost URLs are never gated (a dev server
# the model may be polling). Ports web_fetch.rs::gate_fetch + note_fetch_outcome + local_web_search
# gate_search, adapted to cria's own session state instead of Rust's SessionTurnStore.
_FETCH_SEEN: dict[str, set] = {}
_FETCH_STREAK: dict[str, int] = {}
_SEARCH_SEEN: dict[str, set] = {}
_GATE_CAP = 256


def clear_cache() -> None:
    _DOC_CACHE.clear()
    _FETCH_SEEN.clear()
    _FETCH_STREAK.clear()
    _SEARCH_SEEN.clear()


def _bound(store: dict) -> None:
    if len(store) > _GATE_CAP:
        store.clear()


def _note_streak(session: str, status: int) -> int:
    """Consecutive non-2xx fetches this session; a 2xx resets it. Returns the current streak."""
    if 200 <= status < 300:
        _FETCH_STREAK[session] = 0
        return 0
    n = _FETCH_STREAK.get(session, 0) + 1
    _FETCH_STREAK[session] = n
    _bound(_FETCH_STREAK)
    return n


def gate_search(session: Optional[str], query: str) -> Optional[str]:
    """Refuse an exact-repeat web_search this session (results don't change turn to turn): returns
    the HTTP-400 refusal text, or None to proceed (recording the query). No session → always proceed."""
    q = (query or "").strip().lower()
    if not session or not q:
        return None
    seen = _SEARCH_SEEN.setdefault(session, set())
    if q in seen:
        return (f'HTTP 400 Bad Request · web_search "{query}"\n'
                "You already ran this search this session — the results won't differ. Use them, "
                "search something different, or web_fetch a specific URL.")
    seen.add(q)
    _bound(_SEARCH_SEEN)
    return None


# --- the entry point (web_fetch.rs::fetch_nav) ---------------------------------------------

def fetch_nav(url: str, *, find: Optional[str] = None, cursor: Optional[str] = None,
              cap_tokens: int = CONTENT_CAP_TOKENS, user_agent: Optional[str] = None,
              session: Optional[str] = None) -> str:
    """Plain fetch, ``find=`` selection, or ``cursor=`` pagination, backed by the URL cache.
    Always surfaces the real HTTP status AND the body (never suppresses content on a non-2xx).

    ``session`` enables the coder-loop gates: an exact repeat of an EXTERNAL fetch already made this
    session is refused (it can only return what the model has), and after GUESS_STREAK_THRESHOLD
    consecutive non-2xx external fetches a stop-guessing nudge is appended. Internal hosts never gate."""
    external = not is_internal_url(url)
    seen_key = (url, find or "", cursor or "")
    if session and external and seen_key in _FETCH_SEEN.get(session, ()):
        return (f"HTTP 400 Bad Request · web_fetch {url}\n"
                "You already fetched this exact request (same url, find, cursor) this session — the "
                "result won't differ. Use what you already have, or fetch something different.")
    out, status = _fetch_and_render(url, find, cursor, cap_tokens, user_agent)
    if session and external and status is not None:
        _FETCH_SEEN.setdefault(session, set()).add(seen_key)
        _bound(_FETCH_SEEN)
        out += guess_hint(status, _note_streak(session, status))
    return out


def _fetch_and_render(url, find, cursor, cap_tokens, user_agent) -> tuple[str, Optional[int]]:
    """Fetch (or serve from cache) → reduce → render to the model-facing text. Returns
    ``(text, status)``; ``status`` is None on a transport error (no HTTP response)."""
    navigating = bool(find) or bool(cursor)
    cached = _DOC_CACHE.get(url) if navigating else None
    if cached is not None:
        status, ct, reduced, parsed = cached
    else:
        try:
            r = fetch(url, user_agent)
        except ValueError as e:
            return str(e), None
        except (urllib.error.URLError, OSError) as e:
            return f"web_fetch error fetching {url}: {e}", None
        reduced, parsed = reduce_for_cache(r.body, r.content_type, url)
        status, ct = r.status, r.content_type
        _cache_put(url, status, ct, reduced, parsed)

    if not reduced.strip():
        return (f"{status_label(status)} · {url}\nContent-Type: {ct or '(none)'}\n"
                "The response body was EMPTY. Retrying this exact URL returns the same empty "
                "result — try a different source or path."), status
    if find:
        slice_ = find_in(reduced, parsed, find, cap_tokens)
        return (f"{status_label(status)} · {url}\nContent-Type: {ct or '(none)'}\n"
                f'find="{find.strip()}"\n\n---\n{slice_}'), status
    offset = _parse_cursor(cursor) if cursor else 0
    return render_page(url, status, ct, reduced, parsed, offset, cap_tokens), status


# --- paging (content_reduce.rs::page_from + render_page) ------------------------------------

def _parse_cursor(c: str) -> int:
    c = (c or "").strip()
    if c.startswith("c"):
        c = c[1:]
    try:
        return max(0, int(c))
    except (ValueError, TypeError):
        return 0


def page_from(content: str, offset: int, cap_tokens: int) -> tuple[str, int, int]:
    """A ``~cap_tokens``-sized window from ``offset``, snapped back to a newline when possible.
    Returns ``(page, next_offset, total)``. Offsets are code-point indices (Python str slicing)."""
    total = len(content)
    start = min(offset, total)
    page_chars = max(1, cap_tokens * 4)
    end = min(start + page_chars, total)
    if end < total:
        nl = content.rfind("\n", start, end)
        if nl > start:
            end = nl + 1
    if end <= start:
        end = min(start + page_chars, total)
    return content[start:end], end, total


def render_page(url: str, status: int, ct: Optional[str], reduced: str, parsed: Optional[Any],
                offset: int, cap_tokens: int) -> str:
    body, nxt, total = page_from(reduced, offset, cap_tokens)
    head = f"{status_label(status)} · {url}\nContent-Type: {ct or '(none)'}\n"
    # For a large structured doc, lead with the shape so the model can `find=` a key instead
    # of blindly paging a minified blob (the "summarize with top-level keys" ask).
    if offset == 0 and parsed is not None and nxt < total:
        keys = top_level_keys(parsed)
        if keys:
            head += (f"[structured doc — top-level keys: {', '.join(keys)}]\n"
                     f'[use find="<key>" to jump to a section]\n')
    out = f"{head}--- (chars {offset}–{nxt} of {total}) ---\n{body}\n"
    if nxt < total:
        out += (f'\n⚠ More remains ({total - nxt} of {total} chars left). Continue with the '
                f'SAME url and cursor="c{nxt}", or call find="<keyword>" to jump to a section.')
    return out


# --- find (content_reduce.rs::find_in / find_json / find_text) ------------------------------

def find_in(reduced: str, parsed: Optional[Any], query: str, cap_tokens: int) -> str:
    """MIME-aware targeted retrieval: a JSON/YAML subtree + ancestor spine + one-hop ``$ref``,
    else a text section. Strips surrounding quotes the model adds for emphasis (the Rust cure
    for the 'a model looped a dozen fetches re-quoting terms' bug)."""
    q = (query or "").strip().strip("\"'`").strip()
    if parsed is not None:
        return find_json(parsed, q, cap_tokens)
    return find_text(reduced, q, cap_tokens)


def find_json(root: Any, query: str, cap_tokens: int) -> str:
    q = query.lower()
    matches: list[tuple[list, bool, bool]] = []  # (path, key_match, container)
    _collect_json_matches(root, q, [], matches)
    if not matches:
        keys = top_level_keys(root)
        return f'find "{query}": no match. Available top-level keys: {", ".join(keys)}.'
    # rank: key match first, container over leaf, shallower path first
    matches.sort(key=lambda m: (not m[1], not m[2], len(m[0])))
    out, shown, used = [], 0, 0
    for path, _km, _c in matches:
        if shown >= FIND_TOP_K:
            break
        rendered = _render_json_match(root, path)
        t = est_tokens(rendered)
        if shown > 0 and used + t > cap_tokens:
            break
        out.append(rendered)
        used += t
        shown += 1
    tail = f"\n\n[{len(matches) - shown} more match(es); narrow your find]" if len(matches) > shown else ""
    return "\n\n".join(out) + tail


def _collect_json_matches(node: Any, q: str, path: list, out: list) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            container = isinstance(v, (dict, list))
            if q in str(k).lower():
                out.append((path + [k], True, container))
            elif isinstance(v, str) and q in v.lower():
                out.append((path + [k], False, False))
            _collect_json_matches(v, q, path + [k], out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _collect_json_matches(v, q, path + [i], out)


def _render_json_match(root: Any, path: list) -> str:
    header = " > ".join(f"[{s}]" if isinstance(s, int) else str(s) for s in path)
    sub = _get_at(root, path)
    sub = _resolve_refs(sub, root, 1)
    return f"# {header}\n{json.dumps(sub, indent=2, ensure_ascii=False)}"


def _get_at(root: Any, path: list) -> Any:
    cur = root
    for seg in path:
        try:
            cur = cur[seg]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def _resolve_refs(node: Any, root: Any, depth: int) -> Any:
    """Inline ``$ref`` targets up to ``depth`` hops (cycle-safe by depth). Returns a NEW
    structure (does not mutate ``root``)."""
    if depth <= 0:
        return node
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            target = _resolve_ref_path(root, ref)
            if target is not None:
                return _resolve_refs(target, root, depth - 1)
        return {k: _resolve_refs(v, root, depth) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_refs(v, root, depth) for v in node]
    return node


def _resolve_ref_path(root: Any, ref: str) -> Any:
    if not ref.startswith("#/"):
        return None
    cur = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")  # JSON-pointer unescape
        try:
            cur = cur[part]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def top_level_keys(root: Any) -> list[str]:
    if isinstance(root, dict):
        return [str(k) for k in list(root.keys())[:20]]
    if isinstance(root, list):
        return ["[array]"]
    return []


def find_text(content: str, query: str, cap_tokens: int) -> str:
    q = query.lower()
    lc = content.lower()
    per = max(256, (cap_tokens * 4) // max(1, FIND_TOP_K))
    results: list[str] = []
    frm = 0
    while True:
        rel = lc.find(q, frm)
        if rel == -1:
            break
        slice_ = _extract_around(content, rel, per)
        if not any(slice_ in r or r in slice_ for r in results):
            results.append(slice_)
        frm = rel + max(1, len(q))
        if len(results) >= FIND_TOP_K:
            break
    if not results:
        heads = [ln.strip() for ln in content.splitlines() if ln.lstrip().startswith("#")][:15]
        if not heads:
            return f'find "{query}": no match.'
        return f'find "{query}": no match. Sections:\n' + "\n".join(heads)
    return "\n\n---\n\n".join(results)


def _extract_around(content: str, at: int, budget: int) -> str:
    p = content.rfind("\n\n", 0, at)
    lo = p + 2 if p != -1 else 0
    p2 = content.find("\n\n", at)
    hi = p2 if p2 != -1 else len(content)
    if hi - lo > budget:
        lo = max(lo, at - budget // 2)
        hi = min(hi, at + budget // 2)
    return content[lo:max(hi, lo)].strip()


# --- status + guess gate (web_fetch.rs status/gate helpers) --------------------------------

_STATUS_REASON = {
    200: "OK", 201: "Created", 202: "Accepted", 204: "No Content", 301: "Moved Permanently",
    302: "Found", 303: "See Other", 304: "Not Modified", 307: "Temporary Redirect",
    308: "Permanent Redirect", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
    404: "Not Found", 405: "Method Not Allowed", 406: "Not Acceptable", 408: "Request Timeout",
    410: "Gone", 429: "Too Many Requests", 500: "Internal Server Error", 501: "Not Implemented",
    502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout",
}


def status_label(status: int) -> str:
    reason = _STATUS_REASON.get(status, "")
    return f"HTTP {status} {reason}".rstrip() if reason else f"HTTP {status}"


def is_internal_url(url: str) -> bool:
    """localhost / loopback / RFC-1918 / .local — a dev server the model may be polling; never
    guarded (no repeat-block, no guess-nudge)."""
    after = url.split("://", 1)[1] if "://" in url else url
    authority = after.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    hostport = authority.rsplit("@", 1)[-1]
    if hostport.startswith("["):
        host = hostport[1:].split("]", 1)[0]
    else:
        host = hostport.rsplit(":", 1)[0] if ":" in hostport and hostport.count(":") == 1 else hostport.split(":")[0]
    host = host.lower()
    if host in ("localhost", "::1", "0.0.0.0") or host.endswith((".local", ".localhost")):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip.is_private
    except ValueError:
        return False


def guess_hint(status: int, streak: int) -> str:
    """After GUESS_STREAK_THRESHOLD consecutive non-2xx external fetches, tell the model to stop
    guessing URLs. Below that, a single bad URL stands on its own."""
    if not (200 <= status < 300) and streak >= GUESS_STREAK_THRESHOLD:
        return (f"\n\n⚠ {streak} fetches in a row failed (non-2xx). If you're guessing URLs, "
                "stop — find the right one via search, or take a different step.")
    return ""
