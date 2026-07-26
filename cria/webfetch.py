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

The flow (cria's ``reduce_for_cache``, mirroring the Rust): fetch → lossless reduce (HTML→text, JSON
minify, YAML→structural) → cache by URL → then either PAGE (``cursor`` char-offset, "more remains" footer) or FIND
(``find_json``: subtree + ancestor spine + one-hop ``$ref`` inline; no-match → top-level keys).
A large single-line spec becomes navigable instead of truncated garbage.

**YAML is handled structurally with PyYAML** — the TODO ``content_reduce.rs:8`` handed the
Python port. Parsed YAML becomes the same Python dict/list the JSON path walks, so one set of
navigation code serves both. If PyYAML is absent the doc degrades to text paging, never an error.

Stdlib + PyYAML only. Reuses :mod:`cria.content_reduce` for the already-ported HTML/JSON/text
reducers and the token estimate.
"""
from __future__ import annotations

import difflib
import ipaddress
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

from . import brave, prompts
from .content_reduce import est_tokens, html_to_text
from .searchloop import first_domain_in, normalize_search, searches_match

try:  # structural YAML is best-effort — the Rust degrades YAML to text too when it can't parse
    import yaml as _yaml
except ImportError:  # pragma: no cover - environment without PyYAML
    _yaml = None

# --- constants (mirrored from web_fetch.rs / content_reduce.rs) ----------------------------
MAX_BODY_BYTES = 8 * 1024 * 1024     # raw-body read cap; raised well past real specs (was 512 KiB in web_fetch.rs). A rare doc beyond this is DISCLOSED as truncated (FetchResult.truncated → render_page/find), never silently cut.
CONTENT_CAP_TOKENS = 4000            # one page / one find response (WEB_FETCH_CONTENT_CAP_TOKENS)
REQUEST_TIMEOUT_S = 30               # per-request (REQUEST_TIMEOUT_SECS)
USER_AGENT = brave.USER_AGENT        # a real browser UA so ordinary sites don't 403 curl/8.x (curl_ua.rs)
DOC_CACHE_CAP = 32                   # per-URL reduced-doc cache bound (DOC_CACHE_CAP)
FIND_TOP_K = 3                       # best-N find matches returned (FIND_TOP_K)
GUESS_STREAK_THRESHOLD = 3           # consecutive non-2xx before the stop-guessing nudge

# cria-authored markers that lead a surfaced spec's real ROUTES / RESPONSE FIELDS. Emitted ONLY when a
# fetched doc parsed as a spec-shaped object (real endpoint paths found) — so their presence in an
# evidence log is GROUND TRUTH that the coder web_fetched a real API source and its actual endpoints +
# field names are now in a `->` result. loop._research_facts_obtained keys the research-step fast-path
# off these (a named constant, shared, so the two are never a magic string that drifts out of sync).
ROUTES_MARKER = "[API endpoints ("   # ...N): /a, /b, ...]
SHAPE_MARKER = "[response shape —"   # ...the fields each endpoint RETURNS: GET /x → f1, f2{a,b}, ...]

# Human-readable form of the body cap, for the truncation disclosure (so the model knows the
# fetched doc was cut at a real boundary and content remains beyond it — not a silent slice).
_BODY_CAP_LABEL = (f"{MAX_BODY_BYTES // (1024 * 1024)} MB" if MAX_BODY_BYTES >= 1024 * 1024
                   else f"{MAX_BODY_BYTES // 1024} KB")


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


def reduce_for_cache(body: str, content_type: Optional[str], url: str,
                     raw: bool = False) -> tuple[str, Optional[Any]]:
    """Lossless, content-aware reduction + the parsed structure (for structural find).
    Returns ``(reduced_text, parsed_or_None)``. HTML→text; XML/JSON/YAML kept structural; else passes
    through. ``raw=True`` returns the literal source untouched (the model asked to see the markup).

    JSON stays minified on purpose: it's valid as-is, page_from cuts cleanly at the char cap when
    there are no newlines (no data loss — the next page continues, and "More remains" discloses it),
    and minified fits MORE of the doc per page than indented would. `find=` pretty-prints the
    subtree it returns, so a section the model asks for is still legible."""
    ct = (content_type or "").lower()
    if raw:
        # The caller wants the literal source (front-end debugging, markup inspection), so REDUCE
        # nothing — but still learn the doc's STRUCTURE. `raw` is about the bytes the model reads; it
        # was also silently discarding `parsed`, and `parsed` is what every structural surface is built
        # from. With it None, an oversized spec spilled with NO outline: no route list, no response
        # fields, not even the top-level keys — just "saved 59,210 chars, go grep it". Observed live:
        # the coder fetched openapi.json with raw=true, got no map, grepped the file for its own
        # guess ("resolve", 2 useless hits) while /handles/{handle} sat at line 363, and shipped
        # https://api.handle.me/resolve-handle → 404. That is the exact gap _spill_outline exists to
        # close, reopened by a flag that has nothing to do with it.
        return body, _structure_of(body, content_type, url)
    if "html" in ct:  # incl. application/xhtml+xml — a rendered web page: flatten to readable text
        return html_to_text(body, url), None
    if "xml" in ct:   # RSS/Atom/SVG/SOAP/sitemap — STRUCTURED data; keep the tags, never prose-flatten it
        return body, None
    if "json" in ct:
        obj = _structure_of(body, content_type, url)
        if obj is None:
            return body, None
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False), obj
    if _is_yaml(content_type, url) and _yaml is not None:
        obj = _structure_of(body, content_type, url)
        if obj is not None:
            # canonical, LINE-BASED rendering so paging never cuts mid-line (the seed bug)
            return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False), obj
    return body, None


def _structure_of(body: str, content_type: Optional[str], url: str) -> Optional[Any]:
    """The doc's parsed structure (JSON or YAML) — None when it has none, or won't parse. Pure: it never
    rewrites the body, so it is safe to call on a ``raw`` fetch whose bytes must pass through untouched.
    ONE parser for both paths, so a structural surface can't exist for the reduced view and vanish for
    the raw one."""
    ct = (content_type or "").lower()
    if "json" in ct:
        try:
            return json.loads(body)
        except (ValueError, TypeError):
            return None
    if _is_yaml(content_type, url) and _yaml is not None:
        try:
            obj = _yaml.safe_load(body)
            return obj if isinstance(obj, (dict, list)) else None
        except Exception:  # noqa: BLE001 - any YAML parse error → no structure
            return None
    return None


# --- per-URL cache (web_fetch.rs DOC_CACHE) ------------------------------------------------

_DOC_CACHE: dict[str, tuple[int, Optional[str], str, Optional[Any], bool]] = {}


def _cache_put(url: str, status: int, ct: Optional[str], reduced: str, parsed: Optional[Any],
               truncated: bool) -> None:
    if len(_DOC_CACHE) >= DOC_CACHE_CAP and url not in _DOC_CACHE:
        _DOC_CACHE.clear()  # simple bound (Rust clears on overflow too)
    _DOC_CACHE[url] = (status, ct, reduced, parsed, truncated)


# --- coder-loop gate state (cria is a persistent server) -----------------------------------
# A repeat fetch/search is refused ONLY while its prior result is STILL VISIBLE in the conversation
# — because the gate's whole justification ("it can only return what you already have") is FALSE
# once self-compaction elides that result. So `_FETCH_SEEN`/`_SEARCH_SEEN` are not a forever-set;
# `set_visible()` REPLACES them each request with what's actually in the current history (fed from
# the sentinels of the web_fetch/web_search calls still present). This is the fix for the
# session-permanent gate that refused a legitimate re-read of a compacted-away OpenAPI spec (a live
# footgun). `_FETCH_STREAK` (the stop-guessing nudge) is genuinely consecutive, so it does persist.
# Internal/localhost URLs are never gated. Spirit of web_fetch.rs::gate_fetch (turn-scoped there).
_FETCH_SEEN: dict[str, set] = {}
_FETCH_STREAK: dict[str, int] = {}
_SEARCH_SEEN: dict[str, set] = {}
_GATE_CAP = 256


def clear_cache() -> None:
    _DOC_CACHE.clear()
    _FETCH_SEEN.clear()
    _FETCH_STREAK.clear()
    _SEARCH_SEEN.clear()


# --- OVERSIZED docs: spill to a file the model can grep, instead of a low-signal page-1 -------------
# A big doc paged in document order leads with its FRONT MATTER (an OpenAPI spec's info/license/contact
# block), NOT the endpoints/schemas the model needs — and a weak model, seeing only that, re-fetches or
# writes the fragment to disk (the live Ada-handle incident: it saved the 473-byte info block as its
# "openapi.json"). So a doc larger than one page is written IN FULL to ./tmp and the model is handed a
# short pointer + two lossless ways in: grep the file, or a filtered `find=` fetch (served from cache).
OVERSIZE_CHARS = CONTENT_CAP_TOKENS * 4  # bigger than one page → spill to a file rather than inline
# Spills land in a DEDICATED, read-only scratch dir — reference material, NOT a deliverable the model
# should read-whole (the harness truncates a big cat) or EDIT (observed: it tried identical no-op edits
# on the spilled spec, poisoning the reasoner with base64). writeproxy refuses mutations here. The dir
# name is model-facing, so it says what it is (read-only) and never leaks the "cria" marker.
SPILL_DIR = "./tmp/read-only"


def _spill_name(url: str) -> str:
    """A stable, filesystem-safe name under :data:`SPILL_DIR` for a URL's spilled doc — stable so a
    re-fetch of the same url points the model at the same file (no duplicate spills)."""
    import urllib.parse
    p = urllib.parse.urlparse(url)
    stem = (p.netloc + p.path).strip("/") or "page"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_") or "page"
    if "." not in stem.rsplit("_", 1)[-1]:
        stem += ".txt"
    return f"{SPILL_DIR}/{stem}"


def _looks_like_code(text: str) -> bool:
    """A minified body whose brace/semicolon density reads as CSS/JS (when the content-type is absent
    or lying) — worth breaking at structural points for grep. Conservative sample so plain text is safe."""
    sample = text[:4000]
    return sample.count("{") + sample.count("}") + sample.count(";") >= 8


def _is_minified(text: str) -> bool:
    """A body dominated by one very long line — ``grep`` would return that whole line, so break it up."""
    return len(text) > 2000 and max((len(ln) for ln in text.split("\n")[:400]), default=0) > 2000


def _break_tags(html: str) -> str:
    """Each tag boundary on its own line — whitespace inserted between ``>`` and ``<`` is insignificant
    in HTML/XML, so this only aids grepping and never changes meaning."""
    return re.sub(r">\s*<", ">\n<", html)


def _break_code(code: str) -> str:
    """Newline after each ``{ } ;`` — STRING-AWARE (never inside a ' " ` literal), so a URL or text with
    braces isn't split. Whitespace is insignificant in CSS/JS outside strings, so this is a grep aid, not
    a reformat that could change behaviour. Best-effort: regex/comment edge cases are rare and harmless."""
    out: list[str] = []
    quote = None
    prev = ""
    for ch in code:
        out.append(ch)
        if quote:
            if ch == quote and prev != "\\":
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch in "{};":
            out.append("\n")
        prev = ch
    return "".join(out)


def _greppable(reduced: str, parsed: Optional[Any], ct: Optional[str]) -> str:
    """The spilled file's content, formatted so ``grep -n`` is line-oriented. JSON/YAML → pretty JSON;
    a MINIFIED single-mega-line HTML/CSS/JS body → broken at safe structural points (whitespace is
    insignificant there); anything else (already multi-line, or unknown) → as-is. Always lossless."""
    if parsed is not None:
        try:
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass
    if not _is_minified(reduced):
        return reduced
    ct = (ct or "").lower()
    if "html" in ct or "xml" in ct or reduced.lstrip()[:1] == "<":
        return _break_tags(reduced)
    if any(t in ct for t in ("css", "javascript", "ecmascript", "typescript")) or _looks_like_code(reduced):
        return _break_code(reduced)
    return reduced


def search_spill_name(query: str) -> str:
    """A stable ``SPILL_DIR`` filename for a query's saved search results (same query → same file)."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", (query or "").strip().lower()).strip("_")[:60] or "query"
    return f"{SPILL_DIR}/search-{stem}.txt"


def search_spill(query: str) -> tuple[str, str]:
    """(``SPILL_DIR`` target, model pointer) for a search whose noisy results are saved to a read-only
    file instead of inlined — search snippets are mostly irrelevant, so they don't belong in context."""
    target = search_spill_name(query)
    return target, _guard_msg("search_spill", query=query, target=target)


def oversized_spill(url: str) -> Optional[tuple[int, str, str, str]]:
    """If ``url``'s cached doc is bigger than one page, return (status, ./tmp target, greppable full
    content, model message); else None. Content is line-oriented for grep (pretty JSON/YAML, or a
    minified HTML/CSS/JS body broken at safe structural points). Reads the cache a prior fetch populated."""
    cached = _DOC_CACHE.get(url)
    if not cached or len(cached[2]) <= OVERSIZE_CHARS:
        return None
    status, ct, reduced, parsed, _trunc = cached
    content = _greppable(reduced, parsed, ct)
    target = _spill_name(url)
    msg = _guard_msg("spill", status_label=status_label(status), url=url,
                     chars=f"{len(content):,}", target=target,
                     outline=_spill_outline(parsed, target))
    return status, target, content, msg


def _schema_field_summary(sch: Any, schemas: dict, max_fields: int, _depth: int = 0) -> list[str]:
    """Top-level property names of an OpenAPI object schema, dereferencing a ``$ref`` into
    ``components/schemas``. A nested object is expanded ONE level (``resolved_addresses{ada, eth, btc}``)
    so the model sees the real nesting it otherwise guesses; an array field is marked ``[]``."""
    if isinstance(sch, dict) and "$ref" in sch:
        sch = schemas.get(str(sch["$ref"]).rsplit("/", 1)[-1], {})
    if not isinstance(sch, dict):
        return []
    props = sch.get("properties")
    if not isinstance(props, dict):
        return []
    out = []
    for k, v in list(props.items())[:max_fields]:
        v = v if isinstance(v, dict) else {}
        if _depth == 0 and (v.get("type") == "object" or "properties" in v or "$ref" in v):
            sub = _schema_field_summary(v, schemas, 8, _depth + 1)
            out.append(f"{k}{{{', '.join(sub[:8])}}}" if sub else f"{k}(object)")
        elif v.get("type") == "array":
            out.append(f"{k}[]")
        else:
            out.append(str(k))
    return out


def _endpoint_response_fields(parsed: Any, max_endpoints: int = 12, max_fields: int = 30) -> list[str]:
    """For an OpenAPI-shaped spec: each endpoint's SUCCESS-response fields, dereferenced through the
    response schema's ``$ref`` into ``components/schemas`` — so a coder knows WHAT an endpoint returns
    (the exact field names to extract, plus one level of nesting), not just WHERE to call. The recurring
    last-mile bug is a coder that has the right endpoint but GUESSES the response shape (a ``{"handles":[…]}``
    wrapper, a singular ``resolved_address``, a ``holder.address`` that's really a bare ``holder``) because
    the response schema is a ``$ref`` it never followed. Shape-detected (needs ``paths``), bounded, and
    empty for a non-spec doc so nothing is invented. Lines like ``GET /handles/{handle} → holder,
    resolved_addresses{ada, eth, btc}, …``."""
    if not isinstance(parsed, dict):
        return []
    paths = parsed.get("paths")
    if not isinstance(paths, dict):
        return []
    schemas = (parsed.get("components") or {}).get("schemas") or {}
    if not isinstance(schemas, dict):
        schemas = {}
    lines: list[str] = []
    shaped: list[str] = []  # paths already given a shape — used to collapse a resource's own sub-paths
    for path, ops in paths.items():
        if len(lines) >= max_endpoints:
            break
        if not isinstance(ops, dict):
            continue
        # BREADTH over depth: a resource with a path PARAMETER (…/{id}) usually carries several sub-paths
        # (…/{id}/utxo, …/{id}/script). Shape the base resource, then SKIP its sub-paths — else many such
        # variants of ONE resource fill the endpoint budget in spec order and crowd out DISTINCT resources
        # the coder needs (a real run cut /holders/{address} this way, so the coder guessed the holder's
        # total). The routes list still shows every sub-path exists; only their shape is elided.
        if any("{" in sp and path.startswith(sp + "/") for sp in shaped):
            continue
        for method, op in ops.items():
            if not isinstance(op, dict):
                continue
            resp = op.get("responses") if isinstance(op.get("responses"), dict) else {}
            r = resp.get("200") or resp.get("201") or resp.get("default")
            content = r.get("content") if isinstance(r, dict) else None
            schema = None
            if isinstance(content, dict):
                for v in content.values():
                    if isinstance(v, dict):
                        schema = v.get("schema")
                        break
            fields = _schema_field_summary(schema, schemas, max_fields)
            if fields:
                lines.append(f"{str(method).upper()} {path} → {', '.join(fields)}")
                shaped.append(path)
                break  # one method per path is enough for the shape hint
    return lines


def _spill_outline(parsed: Any, target: str) -> str:
    """A navigation outline for a SPILLED structured doc (JSON or YAML — both parse to ``parsed``): the
    API routes when it's spec-shaped, else the top-level keys — so the model greps straight to what it
    needs instead of paging a huge file top-to-bottom. This is the exact gap that sank the Ada-handle
    run: the 2872-line spec spilled with no outline, so the coder read 800 lines linearly, never reached
    /holders or resolved_addresses, and gave up. Same shape-branch as render_page's inline outline,
    keyed off real bytes; the grep example uses a REAL route/key (no ``<placeholder>`` to echo). Ends
    with a newline when non-empty; "" when the doc has no walkable structure (an HTML/text spill)."""
    routes = _endpoint_routes(parsed)
    if routes:
        shapes = _endpoint_response_fields(parsed)
        shape_block = (f"{SHAPE_MARKER} the fields each endpoint RETURNS (extract these; don't guess "
                       "field names or nesting):\n" + "\n".join(f"  {s}" for s in shapes) + "]\n") if shapes else ""
        return (f'{ROUTES_MARKER}{len(routes)}): {", ".join(routes)}]\n'
                f'{shape_block}'
                f'[grep {target} for the endpoint you need FROM THAT LIST, or read_file it with a start_line/end_line range]\n')
    keys = [k for k in top_level_keys(parsed) if k != "[array]"]
    if keys:
        return (f'[top-level keys ({len(keys)}): {", ".join(keys)}]\n'
                f'[grep {target} for the key you need FROM THAT LIST, or read_file it with a start_line/end_line range]\n')
    return ""


def _pad4(k):
    """A fetch key as a 4-tuple (url, find, cursor, raw). Accepts a legacy 3-tuple (raw→False) so a
    caller that hasn't learned about ``raw`` still records a valid key."""
    return tuple(k) + (False,) if len(k) == 3 else tuple(k)


def set_visible(session: Optional[str], fetch_keys, search_queries) -> None:
    """Record what's CURRENTLY visible in the conversation, so the gate refuses a repeat only while
    the model still has that result. Called per request from the fetch/search results still in
    history. ``fetch_keys`` = iterable of (url, find, cursor[, raw]); ``search_queries`` = queries."""
    if not session:
        return
    # 4-tuple identity (…, raw): a raw-source fetch is distinct from the reduced view of the same URL,
    # so requesting the source after a reduced fetch (or vice versa) is never falsely refused as a repeat.
    # History web_fetch calls are the reduced view unless they carried raw=true.
    _FETCH_SEEN[session] = {(u, f or "", c or "", bool(rw))
                            for (u, f, c, rw) in (_pad4(k) for k in fetch_keys)}
    _SEARCH_SEEN[session] = {(q or "").strip().lower() for q in search_queries if (q or "").strip()}
    _bound(_FETCH_SEEN)
    _bound(_SEARCH_SEEN)


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


def _guard_msg(key: str, **tokens: object) -> str:
    """One loop-guard message from prompts/webfetch_guards.txt (re-read per call so it's tunable
    without a restart), with its {{TOKEN}}s filled."""
    return prompts.fill(prompts.load_map("webfetch_guards")[key], **tokens)


def gate_search(session: Optional[str], query: str) -> Optional[str]:
    """Refuse a repeat web_search ONLY while its results are still in the conversation
    (`set_visible`); else the model may re-run it. None → proceed.

    Matches on the normalized word-SET, not the exact string (the codex-local loop_detector
    ported in `searchloop`): a weak model ruminating on the same search tweaks the wording just
    enough to slip past an exact-string guard — the live path saw a model run ~30 near-identical
    searches by alternating "…API resolve…" / "…API endpoint resolve…". A genuine refinement or a
    new direction is NOT matched; only a re-hunt (see `searches_match`)."""
    q = (query or "").strip()
    if not session or not q:
        return None
    words = normalize_search(q)
    if not words:
        return None
    if any(searches_match(words, normalize_search(prev)) for prev in _SEARCH_SEEN.get(session, ())):
        domain = first_domain_in(query)
        steer = _guard_msg("domain_steer", domain=domain) if domain else ""
        return _guard_msg("search_repeat", query=query, domain_steer=steer)
    return None


# --- the entry point (web_fetch.rs::fetch_nav) ---------------------------------------------

def fetch_nav(url: str, *, find: Optional[str] = None, cursor: Optional[str] = None,
              cap_tokens: int = CONTENT_CAP_TOKENS, user_agent: Optional[str] = None,
              session: Optional[str] = None, raw: bool = False) -> str:
    """Plain fetch, ``find=`` selection, or ``cursor=`` pagination, backed by the URL cache.
    Always surfaces the real HTTP status AND the body (never suppresses content on a non-2xx).

    ``raw=True`` returns the literal source (the model wants the markup — front-end debugging, checking
    tags/attributes/selectors) instead of HTML→text, and is a distinct fetch identity from the reduced
    view of the same URL. It suppresses ``cursor`` (paging is a reduced-view concern) but HONORS
    ``find``: "show me the literal source of the part matching X" is a coherent, and common, ask.

    ``session`` enables the coder-loop gates: an exact repeat of an EXTERNAL fetch already made this
    session is refused (it can only return what the model has), and after GUESS_STREAK_THRESHOLD
    consecutive non-2xx external fetches a stop-guessing nudge is appended. Internal hosts never gate."""
    if raw:
        # `find` used to be nulled here alongside `cursor`, discarding the model's narrowing request
        # with NO notice — it asked one question and was answered another, undetectably. Observed live
        # (run 0726-134700): the coder sent find="resolve" with raw=true FIFTEEN times and got back the
        # same "saved 96,199 chars, go grep it" spill every time, never told its find was dropped, so it
        # kept re-asking. Worse, honoring it would have ended the run: "resolve" matches
        # `resolved_addresses` in that spec — the exact field the task needs.
        cursor = None
    external = not is_internal_url(url)
    seen_key = (url, find or "", cursor or "", bool(raw))
    # Refuse ONLY while the identical result is still in the conversation (set_visible); once
    # compaction elides it the model may legitimately re-read it — the footgun fix.
    if session and external and seen_key in _FETCH_SEEN.get(session, ()):
        return _guard_msg("fetch_repeat", url=url)
    out, status = _fetch_and_render(url, find, cursor, cap_tokens, user_agent, raw)
    if session and external and status is not None:
        out += guess_hint(status, _note_streak(session, status))
    return out


def _fetch_and_render(url, find, cursor, cap_tokens, user_agent, raw=False) -> tuple[str, Optional[int]]:
    """Fetch (or serve from cache) → reduce → render to the model-facing text. Returns
    ``(text, status)``; ``status`` is None on a transport error (no HTTP response). ``raw`` fetches
    always re-fetch (never navigate) so a stale reduced-cache entry is never served as source."""
    # A raw fetch NEVER serves the cache: that entry may hold the REDUCED text of an earlier ordinary
    # fetch, and handing that back as "source" is the stale-view lie this flag exists to avoid. It
    # re-fetches, then `find` (now honored under raw) applies to the freshly-read raw body.
    navigating = (bool(find) or bool(cursor)) and not raw
    cached = _DOC_CACHE.get(url) if navigating else None
    if cached is not None:
        status, ct, reduced, parsed, truncated = cached
    else:
        try:
            r = fetch(url, user_agent)
        except ValueError as e:
            return str(e), None
        except (urllib.error.URLError, OSError) as e:
            return f"web_fetch error fetching {url}: {e}", None
        reduced, parsed = reduce_for_cache(r.body, r.content_type, url, raw)
        status, ct, truncated = r.status, r.content_type, r.truncated
        _cache_put(url, status, ct, reduced, parsed, truncated)

    if not reduced.strip():
        return (f"{status_label(status)} · {url}\nContent-Type: {ct or '(none)'}\n"
                "The response body was EMPTY. Retrying this exact URL returns the same empty "
                "result — try a different source or path."), status
    if find:
        slice_ = find_in(reduced, parsed, find, cap_tokens)
        # A broad find (e.g. `paths` on a whole spec) can match a subtree far bigger than one page —
        # window it and tell the model to narrow, so a "filtered" fetch never dumps an unusable wall.
        if len(slice_) > OVERSIZE_CHARS:
            body, nxt, total = page_from(slice_, 0, cap_tokens)
            slice_ = body + _guard_msg("find_large", find=find, chars=f"{total:,}")
        # A find MISS on a truncated doc is the Ada-handle lie: the target may lie beyond the cut,
        # not be absent. Disclose so a miss isn't mistaken for "doesn't exist" (final-page parity).
        if truncated and ": no match" in slice_:
            slice_ += (f"\n\n⚠ This document exceeded the {_BODY_CAP_LABEL} fetch limit and was cut; "
                       "the term you searched may lie in the un-fetched remainder. Fetch a more "
                       "specific URL/path or an alternate source.")
        return (f"{status_label(status)} · {url}\nContent-Type: {ct or '(none)'}\n"
                f'find="{find.strip()}"\n\n---\n{slice_}'), status
    offset = _parse_cursor(cursor) if cursor else 0
    return render_page(url, status, ct, reduced, parsed, offset, cap_tokens, truncated), status


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
                offset: int, cap_tokens: int, truncated: bool = False) -> str:
    body, nxt, total = page_from(reduced, offset, cap_tokens)
    head = f"{status_label(status)} · {url}\nContent-Type: {ct or '(none)'}\n"
    # For a large structured doc, lead with the shape so the model can `find=` a key instead
    # of blindly paging a minified blob (the "summarize with top-level keys" ask).
    if offset == 0 and parsed is not None and nxt < total:
        keys = top_level_keys(parsed)
        if keys:
            head += (f"[structured doc — top-level keys: {', '.join(keys)}]\n"
                     f'[use find="<key>" to jump to a section]\n')
        # For an API spec, surface the actual ENDPOINT ROUTES up front — the single most useful thing
        # and the one a model reaching for "the endpoint" keeps missing (it drills into component
        # schemas and guesses the URL instead). Detected by SHAPE (a top-level object whose keys are
        # mostly `/`-paths), so it works for OpenAPI and any spec dialect, keyed off real bytes.
        routes = _endpoint_routes(parsed)
        if routes:  # uncapped, like top_level_keys — the route the model needs may be #61
            head += f"{ROUTES_MARKER}{len(routes)}): {', '.join(routes)}]\n"
            shapes = _endpoint_response_fields(parsed)
            if shapes:  # the response FIELDS (dereferenced) — so the model extracts real names, not guesses
                head += (f"{SHAPE_MARKER} the fields each endpoint RETURNS (extract these; don't guess "
                         "field names or nesting):\n" + "\n".join(f"  {s}" for s in shapes) + "]\n")
            head += '[web_fetch find="<path>" for one endpoint\'s full request/response detail]\n'
    out = f"{head}--- (chars {offset}–{nxt} of {total}) ---\n{body}\n"
    if nxt < total:
        out += (f'\n⚠ More remains ({total - nxt} of {total} chars left). Continue with the '
                f'SAME url and cursor="c{nxt}", or call find="<keyword>" to jump to a section.')
    elif truncated:
        # End of what we fetched, but the raw body hit the read cap — the ORIGINAL doc is longer.
        # Disclose so the paging end isn't mistaken for the real end-of-document (a silent slice).
        out += (f"\n⚠ This document exceeded the {_BODY_CAP_LABEL} fetch limit and was cut here; "
                "content remains beyond this point that was NOT fetched. If you need it, fetch a "
                "more specific URL/path or an alternate source.")
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


def _all_json_keys(node: Any, acc: set) -> None:
    """Every dict key name anywhere in the tree — the bounded, well-defined vocabulary a fuzzy
    'did you mean' can suggest from on a find miss."""
    if isinstance(node, dict):
        for k, v in node.items():
            acc.add(str(k))
            _all_json_keys(v, acc)
    elif isinstance(node, list):
        for v in node:
            _all_json_keys(v, acc)


def find_json(root: Any, query: str, cap_tokens: int) -> str:
    q = query.lower()
    matches: list[tuple[list, bool, bool]] = []  # (path, key_match, container)
    _collect_json_matches(root, q, [], matches)
    if not matches:
        msg = f'find "{query}": no match. Available top-level keys: {", ".join(top_level_keys(root))}.'
        # Miss-diagnosis (same shape as the edit_file miss assist): the substring search already
        # handles case, so a miss means the term differs from every real key. Point at the CLOSEST real
        # field name anywhere in the doc (typo / plural / snake-vs-camel) so the model re-finds with a
        # real key instead of re-fetching the same doc and re-quoting terms. Additive + degrades safely:
        # a conservative cutoff avoids a similarly-spelled-but-wrong suggestion, and no close key → the
        # root-key fallback is unchanged.
        by_lower: dict[str, str] = {}
        acc: set = set()
        _all_json_keys(root, acc)
        for k in acc:
            by_lower.setdefault(k.lower(), k)
        close = difflib.get_close_matches(q, list(by_lower), n=3, cutoff=0.7)
        if close:
            msg += f' Closest field names in the document: {", ".join(by_lower[c] for c in close)} — try find with one of those.'
        return msg
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


def _endpoint_routes(parsed: Any) -> list[str]:
    """The API's endpoint routes when the doc is a spec: the keys of a top-level object that are mostly
    URL paths (start with ``/``) — OpenAPI's ``paths``, but detected by SHAPE not by the key name, so it
    surfaces for any dialect. Empty when the doc isn't route-shaped (so nothing is invented)."""
    if not isinstance(parsed, dict):
        return []
    for v in parsed.values():
        if isinstance(v, dict) and len(v) >= 2:
            ks = [str(k) for k in v.keys()]
            slashed = [k for k in ks if k.startswith("/")]
            if len(slashed) >= max(2, int(len(ks) * 0.6)):  # mostly route-like → these are endpoints
                return slashed
    return []


def top_level_keys(root: Any) -> list[str]:
    # ALL keys, uncapped: this is the navigation vocabulary on a find MISS and the shape hint for a
    # structured doc — a cap would hide the very key the model needs (its target may be key #27).
    if isinstance(root, dict):
        return [str(k) for k in root.keys()]
    if isinstance(root, list):
        return ["[array]"]
    return []


def _no_text_match(content: str, query: str, cap_tokens: int) -> str:
    """A find that matched NOTHING must never be worse than not having used find at all.

    A missed narrowing used to return the four words `find "<q>": no match.` and throw the document
    away. Observed live (run 0726-133755): the coder fetched https://api.handle.me — a 705-char index
    page whose entire value is `<a href="/openapi.json">OpenAPI spec (JSON)</a>` and three sibling
    links — with find="resolve". "resolve" appears nowhere on it, so cria answered "no match" and
    nothing else. The page that names the spec was destroyed by a substring miss, and the coder went
    on to guess URLs. Never destroy content the model reads (principle #5): when the document fits a
    page, hand it back WITH the miss notice. When it doesn't, keep the heading outline it can
    re-target from — dumping an oversized doc here is the truncation this rule also forbids."""
    heads = [ln.strip() for ln in content.splitlines() if ln.lstrip().startswith("#")]
    notice = f'find "{query}": no match.'
    page, _next, total = page_from(content, 0, cap_tokens)
    if len(page) >= total:      # the WHOLE document fits — a miss costs the model nothing
        return f"{notice} The full document follows.\n\n{content}"
    if heads:
        return f"{notice} Sections:\n" + "\n".join(heads)
    return f"{notice} It is too large to return whole here — re-run find with a different term, or fetch without find to page it."


def find_text(content: str, query: str, cap_tokens: int) -> str:
    q = query.lower()
    lc = content.lower()
    per = max(256, (cap_tokens * 4) // max(1, FIND_TOP_K))
    # Collect ALL distinct match windows, then show the top FIND_TOP_K and DISCLOSE the residual —
    # a silent stop at FIND_TOP_K is a truncation the model can't detect (it may conclude the match
    # it wants doesn't exist when it was really the 4th hit). Mirrors find_json's disclosure.
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
    if not results:
        return _no_text_match(content, query, cap_tokens)
    shown = results[:FIND_TOP_K]
    body = "\n\n---\n\n".join(shown)
    if len(results) > len(shown):
        body += f"\n\n[{len(results) - len(shown)} more match(es); narrow your find]"
    return body


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
        return _guard_msg("guess_hint", streak=streak)
    return ""
