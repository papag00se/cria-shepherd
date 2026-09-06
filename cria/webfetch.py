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
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

from . import apidiscovery, brave, denial, prompts
from .content_reduce import (COMMAND_ARG_BUDGET, INLINE_RESULT_MAX_BYTES,  # noqa: F401
                             SPILL_CONTENT_MAX, clip, est_tokens, html_to_text)
from .searchloop import first_domain_in, normalize_search, searches_match
from . import content_reduce

try:  # structural YAML is best-effort — the Rust degrades YAML to text too when it can't parse
    import yaml as _yaml
except ImportError:  # pragma: no cover - environment without PyYAML
    _yaml = None

# --- constants (mirrored from web_fetch.rs / content_reduce.rs) ----------------------------
MAX_BODY_BYTES = 8 * 1024 * 1024     # raw-body read cap; raised well past real specs (was 512 KiB in web_fetch.rs). A rare doc beyond this is DISCLOSED as truncated (FetchResult.truncated → render_page/find), never silently cut.
# One page / one find response (WEB_FETCH_CONTENT_CAP_TOKENS was 4000 → 16,000 chars, which the
# harness's 10,000-byte history budget middle-cut in every later prompt — see INLINE_RESULT_MAX_BYTES).
# Derived from the one inline bound so a page can never outgrow what survives the harness.
CONTENT_CAP_TOKENS = INLINE_RESULT_MAX_BYTES // 4
REQUEST_TIMEOUT_S = 30               # per-request (REQUEST_TIMEOUT_SECS)
USER_AGENT = brave.USER_AGENT        # a real browser UA so ordinary sites don't 403 curl/8.x (curl_ua.rs)
DOC_CACHE_CAP = 32                   # per-URL reduced-doc cache bound (DOC_CACHE_CAP)
FIND_TOP_K = 3                       # best-N find matches returned (FIND_TOP_K)
GUESS_STREAK_THRESHOLD = 3           # consecutive non-2xx before the stop-guessing nudge

# cria-authored markers that lead a surfaced spec's real ROUTES / RESPONSE FIELDS. Emitted ONLY when a
# fetched doc parsed as a spec-shaped object (real endpoint paths found) — so their presence in an
# evidence log is GROUND TRUTH that the coder web_fetched a real API source and its actual endpoints +
# field names are now in a `->` result. research.sources_read reads them, so judges and steers are
# told what was really read (named constants, shared, so the two never drift out of sync).
ROUTES_MARKER = "[API endpoints ("   # ...N): /a, /b, ...]
SHAPE_MARKER = "[response shape —"   # ...the fields each endpoint RETURNS: GET /x → f1, f2{a,b}, ...]
# ...and where an API's machine-readable DESCRIPTION lives, when the fetched doc is a catalogue of
# other documents rather than a spec itself (RFC 9727 .well-known/api-catalog, carried as an RFC 9264
# linkset). Its whole value is the hrefs, which a top-level-keys outline throws away.
CATALOG_MARKER = "[API descriptions ("   # ...N): <anchor> → service-desc: <url>; ...]

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
        raise ValueError(f"web_fetch: unsupported scheme "
                         f"'{scheme or content_reduce.clip(trimmed, 12)}': only http/https")
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
        # NAME A ROUTE, OR DO NOT CLAIM IT IS UNREADABLE. This replaced the whole document with a
        # byte count on a closed content-type allowlist — so a spec served as
        # `application/octet-stream`, `application/x-ndjson`, or under a mistyped header was
        # destroyed before anything parsed it, with no alternative offered. The header is the thing
        # that was wrong, so sniff the BYTES: text that decodes and reads as text is text (#5b).
        text = slice_.decode("utf-8", "replace")
        if not content_reduce.looks_binary(text):
            body = text
        else:
            body = (f"[non-text response: {len(raw)} bytes, content-type={content_type or '(none)'} "
                    f"— the bytes are not text. Ask for a specific part with find=, or fetch a "
                    f"different representation of this resource.]")
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
# Queries whose results cria ITSELF spilled to a file, `{lowered: as the model typed it}`. Only the
# synthetic Brave path writes that file; a harness-native search never does. The repeat refusal used
# to name the spill path unconditionally, sending the model to grep a file that was never written.
#
# The ORIGINAL spelling is kept because the read-judge is asked to rule a saved file's results on- or
# off-target and must be handed the query that produced them. It used to recover that query by
# regexing cria's own pointer sentence out of the conversation, and when the sentence changed shape
# the match missed and the judge was told the query was "(none)" — it ruled off-target on that and
# cria PERMANENTLY DELETED the file (shipping-rates-rb x nemotron-elastic 1787294328, holding
# `ISO3166::Country#in_eu?`, the exact predicate the task needed; 0/5). cria wrote that file and knew
# that query; there was never anything to recover (#12).
_SEARCH_SPILLED: dict[str, dict] = {}
# Queries a reasoner has judged a genuinely NEW direction rather than a re-hunt (`allow_search`), so
# the word-overlap trigger does not refuse them.
_SEARCH_ALLOWED: dict[str, set] = {}
# Urls whose document cria WROTE to a file in the workspace. That file outlives the conversation, so
# a plain re-fetch of the url is answered with the file's name rather than the document again.
_FETCH_SPILLED: dict[str, dict] = {}
_GATE_CAP = 256


def clear_cache() -> None:
    _DOC_CACHE.clear()
    _FETCH_SEEN.clear()
    _FETCH_STREAK.clear()
    _SEARCH_SEEN.clear()
    _SEARCH_SPILLED.clear()
    _SUBSTITUTED.clear()
    _SEARCH_ALLOWED.clear()
    _FETCH_SPILLED.clear()


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
# ONE WORD, BECAUSE A SEPARATOR IS A COIN FLIP. This was `./tmp/read-only` and the hyphen cost a
# whole cell. Walked on shipping-rates-rb x gemma4 (2026-08-17): cria refused a near-duplicate
# web_search and, in the same breath, told the coder where the earlier results were —
# `grep -n "<keyword>" ./tmp/read-only/search-….txt`. The coder retyped it into a shell string as
# `./tmp/read_only/…`, got "No such file or directory", found nothing, and searched again; cria
# refused again with the same pointer. That loop ran for roughly twenty of the run's 148 calls.
#
# MEASURED over every captured call on this box: the model spells the path perfectly when it is a
# TOOL ARGUMENT — read_file 68/68, list_dir 1/1 — and gets it wrong 9 of 59 times (15%) when it has
# to retype it inside `exec_command`. The filenames, which cria also generates and which are far
# longer, came back byte-exact every time. It was never the length; it was the hyphen, in a name
# every other path around it writes with an underscore.
#
# So the fix is not a corrector for the typo, it is not spelling the ambiguity in the first place:
# cria owns this directory's name and had no reason to put a separator in it. The word `reference`
# also says what the directory holds, which `read-only` did not; nothing ever depended on the name
# to keep the coder from writing here (`writeproxy.is_spill_path` enforces that).
SPILL_DIR = "./tmp/reference"


def _spill_name(url: str) -> str:
    """A stable, filesystem-safe name under :data:`SPILL_DIR` for a URL's spilled doc — stable so a
    re-fetch of the same url points the model at the same file (no duplicate spills)."""
    import urllib.parse
    p = urllib.parse.urlparse(url)
    stem = (p.netloc + p.path).strip("/") or "page"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_") or "page"
    # ALWAYS `.txt`, never the URL's own extension. This used to append `.txt` only when the last
    # segment had no dot, so a fetch of `…/decimal.go` was written into the workspace as a `.go`
    # file — and `go build ./...` compiled cria's own 90 KB copy of somebody else's library.
    # Proven by ablation on the archived run: with `tmp/` present the verifier says
    # `FAIL [build failed]`; after `rm -rf tmp` it says `ok`. Every check in that cell, gone.
    #
    # The kernel is not Go's: a spill is a TEXT TRANSCRIPT of a fetch, not a source file, and any
    # toolchain that globs by extension — go, cargo, javac, tsc, a pytest collector — will pick up
    # whatever cria leaves lying in the tree. So the name states what the file is. The original
    # extension survives inside the name (`…_decimal.go.txt`), which keeps the stable-name property
    # this function exists for.
    if not stem.endswith(".txt"):
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
    """A stable ``SPILL_DIR`` filename for a query's saved search results (same query → same file).

    ONE QUERY, ONE FILE — AND TWO QUERIES, TWO FILES. The readable stem is cut at 60 characters, so
    two different searches whose first 60 slug characters agree used to map to one path. The writer
    is `open(T, "w")`, which truncates: the earlier results were destroyed on disk while
    `_SEARCH_SPILLED` still recorded both queries, and the repeat refusal then pointed the model at
    that file saying its earlier results were in it. Verified: two queries differing only in their
    last word collided.

    The suffix is a digest of the WHOLE query, so the stem stays readable (the model greps this path
    by name) and distinct queries cannot share a file (#5b)."""
    q = (query or "").strip()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", q.lower()).strip("_")[:60] or "query"
    tag = hashlib.sha1(q.encode("utf-8", "replace")).hexdigest()[:8]
    return f"{SPILL_DIR}/search-{stem}-{tag}.txt"


def search_spill(query: str) -> tuple[str, str]:
    """(``SPILL_DIR`` target, model pointer) for a search whose noisy results are saved to a read-only
    file instead of inlined — search snippets are mostly irrelevant, so they don't belong in context."""
    target = search_spill_name(query)
    return target, _guard_msg("search_spill", query=query, target=target)


def spill_content(reduced: str, parsed: Optional[Any], content_type: Optional[str]) -> str:
    """The lossless, grep-oriented form of a doc being spilled to a file. Public so the PLANNER's
    gather spills identically to the coder's fetch — one implementation, one shape on disk."""
    return _greppable(reduced, parsed, content_type)


def spill_outline(parsed: Optional[Any], target: str) -> str:
    """The navigation outline that rides with a spilled doc (routes when spec-shaped, else top-level
    keys). Public for the same reason as :func:`spill_content`."""
    return _spill_outline(parsed, target)


def outline_for_url(url: str) -> str:
    """The outline cria ALREADY HOLDS for ``url``'s spilled document — rebuilt from the parsed doc in
    the per-URL cache — or ``""`` when nothing is cached for it.

    This exists so a REFUSAL can be an ANSWER. A spill refusal and the spill-file read steer both
    say "that document is on disk, go grep it" and name nothing the document contains, which is a
    riddle when the coder does not yet know what to grep FOR (measured: it copied the literal
    ``<keyword>`` placeholder into ``find=`` — run 0802-184308 call 0270). cria fetched and parsed
    the doc, so it can say what is in it, and the outline it built at spill time is exactly that.

    MEASURED over the 124 captured sessions, and re-measurable at any time with
    ``suite/replay_logic.py --check spill-outline``: 2,102 coder calls carried the spill refusal or
    the spill-file read steer, and 840 of them had NO outline anywhere in the prompt — the
    initial spill's outline had been compacted away while the durable refusal kept firing. (An
    earlier reading of this said 981 of 2,074; the population is confirmed, the no-outline count
    was over-stated. The refusal ALONE accounts for 1,438 of those calls, 695 without an outline.)
    In run 0802-184308 the outline vanished at
    the first compaction (call 0075) and never came back, so 139 of the remaining 141 coder calls
    were told to read a file cria described only by its filename. The plan never left step 1 of 6.

    ``""`` on a cache miss is not a fallback, it is rule 5b: cria states no fact it cannot back with
    the real document. The refusal's own read instructions stand on their own without it."""
    cached = _DOC_CACHE.get(url)
    if not cached:
        return ""
    return _spill_outline(cached[3], _spill_name(url))


def outline_for_spill_path(path: str) -> str:
    """:func:`outline_for_url`'s twin, keyed by the SPILL FILE instead of the url — for the read side
    of the same closed door, where cria only ever sees the path the coder typed.

    :func:`_spill_name` is a pure function of the url and cria controls the whole spill dir, so the
    basename identifies the document exactly; matching on it (not the full string) means ``./tmp/…``,
    ``tmp/…`` and a root-absolute form all resolve to the same doc."""
    base = os.path.basename(os.path.normpath((path or "").strip()))
    if not base:
        return ""
    for url in _DOC_CACHE:
        if os.path.basename(_spill_name(url)) == base:
            return outline_for_url(url)
    return ""


def _doc_format(content: str) -> str:
    """What the spilled bytes ACTUALLY are — "JSON", "HTML", or "" when cria cannot say.

    The spill FILENAME comes from the url (:func:`_spill_name`, stable on purpose so a re-fetch maps
    to the same file), so a `.../swagger.yml` url whose server answers with JSON is stored — and
    announced — as `.yml`. Walked on ada-handles_nemotron-elastic_codex_pon_1785360304: cria told the
    coder to grep `api.handle.me_swagger_swagger.yml`, never saying it was JSON, and the coder spent
    the run on patterns that cannot match a pretty-printed JSON document — `grep -n "paths.*/handles"`
    six times for exit 1, `grep -A 20 "properties:"` (the file has `"properties": {`), and a hand-built
    YAML tree in its reasoning. Renaming the file would break the url→path identity three call sites
    depend on; saying what it is costs nothing and is the fact the model was missing.

    THE YAML ANSWER WAS A GUESS OVER PROSE AND IS GONE. Its test matched any line of the form
    ``Word:`` — which documentation prose is made of. Walked on shipping-rates-rb x ternary-bonsai: the spilled RubyDoc page for `ISO3166::Country`
    begins `RubyDoc.info:`, and cria announced "It is YAML." about flattened HTML. That page carries
    `in_eu?` from the gem that works; the model went to a different gem on the next call.

    IT WAS ALSO UNANSWERABLE, WHICH IS THE REAL POINT. Whatever the source was, a doc that PARSED is
    written to the spill file by :func:`_greppable` as pretty JSON — so "YAML" was never true of the
    bytes cria is describing, even for a genuine YAML document. The two answers left are read off
    what cria established rather than sniffed: `parsed` is the parse that actually happened, and a
    leading tag is a tag. Everything else is silence (#3), which is what the caller renders when this
    returns "".

    The `HTML` answer survives for the one case that reaches the file with tags in it — a MINIFIED
    body, which `_greppable` breaks at structural points rather than flattening. An ordinary HTML
    page is reduced to text long before here, and text is not HTML.

    AND IT READS THE BYTES, NOT THE PARSE. The first cut of this took `parsed is not None` as proof
    of JSON, on the reasoning that `_greppable` pretty-prints every parsed doc. It does not always:
    `json.dumps` raises on a `datetime`, and PyYAML turns a bare `2026-08-18` into one — so a YAML
    document with a date scalar falls back to its raw text and was then announced as JSON. Same rule
    as the one this function exists to serve (#5b): cria holds the authoritative object — the bytes
    it is about to write — so it reads those. `json.dumps` output always opens with `{` or `[`, which
    makes the parse redundant as well as unsafe."""
    head = (content or "").lstrip()[:200]
    if head.startswith(("{", "[")):
        return "JSON"
    if head.lower().startswith(("<!doctype", "<html", "<?xml")):
        return "HTML"
    return ""


def spill_reading_hint(path: str, limit: int) -> str:
    """"It is N lines; start_line=1 end_line=M fits in one read." — or "" when cria has no such doc.

    THE REFUSAL WAS UNACTIONABLE FOR EXACTLY THE DOCUMENTS THAT NEED READING. It says "grep the file
    for what you need, or read a specific line range", and for a doc with no parsed structure the
    outline slot beside it is empty — so the coder is told to grep with nothing to grep FOR, and to
    pick a range with no idea how many lines exist or how big a range would fit.

    Walked on `shipping-rates-rb x ternary-bonsai` 1787111689 and again on the run before it: the
    coder asked for the spilled rubydoc page ONCE, got "nothing is shown", and never touched the file
    again in either run. The page defines `in_eu?`; the coder guessed `eu_member?`, which does not
    exist, and that guess is the whole `country_zone_mapping` failure.

    Both numbers are facts cria already holds — the document is in `_DOC_CACHE`, which is where the
    format and the outline beside this sentence come from. Nothing is measured on the filesystem and
    nothing is guessed: no cached doc, no sentence (#5b)."""
    for url, cached in _DOC_CACHE.items():
        if os.path.basename(_spill_name(url)) != os.path.basename(os.path.normpath((path or "").strip())):
            continue
        # MEASURE THE ARTIFACT THE SENTENCE IS ABOUT. The cached body is the WHOLE document; the file
        # this sentence names is the spill, which stops at SPILL_CONTENT_MAX. Counting the first and
        # naming the second told a coder "It is 2,414 lines" about a 1,656-line file and invited it to
        # page past the end (cart-billing-go x nemotron-elastic 1787434778). The docstring above says
        # nothing is measured on the filesystem, which is exactly why it has to measure the bytes that
        # were WRITTEN rather than the ones that were fetched (#5b, #11b).
        body = _greppable(cached[2], cached[3], cached[1])
        raw = body.encode("utf-8", "replace")
        if len(raw) > SPILL_CONTENT_MAX:
            body = raw[:SPILL_CONTENT_MAX].decode("utf-8", "ignore")
        lines = body.count("\n") + 1
        if lines < 2 or not body:
            return ""
        # EXACT, NOT PROPORTIONAL — the same contract 467da62 gave the file-path sibling. The
        # proportional estimate (lines * limit / len(body)) overshot whenever the EARLY lines ran
        # wider than average: walked on feed-pipeline-java x nemotron-elastic 1788232218, where
        # this sentence said "end_line=205 fits in one read" about the spilled opencsv POM — the
        # one document naming the correct groupId — and `_ranged_read` then refused the coder's
        # SMALLER 1-200 request, in every prompt of the run, because the promise was made about
        # average bytes and checked against real ones (#12, #5b). cria holds the spilled bytes
        # right here, so it can name the largest prefix that provably fits instead of estimating.
        fits = _numbered_prefix_fits(body, limit)
        if fits < 1:
            return ""      # even line 1 alone is over the limit — no honest window to offer (#11b)
        if fits >= lines:
            return ""      # the whole thing would fit; the refusal is not about size then
        return prompts.fill(prompts.load_map("webfetch_guards")["spill_extent"],
                            lines=f"{lines:,}", fits=str(fits))
    return ""


def _numbered_prefix_fits(body: str, limit: int) -> int:
    """Largest N such that lines 1..N — AS `_ranged_read` RETURNS them, numbered ``n: line\\n`` —
    total at most ``limit`` bytes. 0 when even line 1 alone is over.

    The promise `spill_extent` makes is checked by `_ranged_read` against its NUMBERED output, so
    the promise must be computed over the same artifact: line-number digits, the ``: `` separator
    and the newline all count (#12). Per line that is ``len(str(n)) + 2 + len(utf-8 bytes) + 1``."""
    total, fits = 0, 0
    for n, line in enumerate(body.split("\n"), 1):
        total += len(str(n)) + 2 + len(line.encode("utf-8", "replace")) + 1
        if total > limit:
            break
        fits = n
    return fits


# A URL PATH THAT NAMES A SOURCE FILE. A forge's `/blob/` view serves the HTML page ABOUT a file
# under a url that ends in the file's own name, so the spill lands as `…_decimal.go.txt` holding
# stylesheets. Walked on cart-billing-go x nemotron-elastic 1787434778: 46,389 bytes of GitHub chrome
# — 39 `<link rel="stylesheet">` tags, zero occurrences of `func NewFromString` — saved under that
# name, described as the document, and grepped five times for an API that could never be in it.
_CODE_URL = re.compile(r"\.(?:go|py|rb|rs|java|js|ts|c|h|cpp|cs|php|kt|swift|scala|ex|erl|lua|pl|sh)"
                       r"(?:[?#].*)?$", re.I)


def html_page_about_a_file(url: str, content: str) -> bool:
    """The fetch returned a WEB PAGE while the url named a source file — so what was saved is the
    page, not the file. Both halves are facts cria holds: the url it asked for, and the bytes that
    came back."""
    return bool(url) and bool(_CODE_URL.search(url)) and _doc_format(content or "") == "HTML"


def page_not_file_for_spill_path(path: str) -> bool:
    """Is the spill at ``path`` a WEB PAGE saved under a source file's name?

    The read-refusal for that file says "grep it for what you need". Without this the reader greps a
    page's stylesheets for the code and reads the absence as the library's — five empty greps on
    cart-billing-go x nemotron-elastic 1787434778, on the question the whole run turned on."""
    base = os.path.basename(os.path.normpath((path or "").strip()))
    if not base:
        return False
    for url, cached in _DOC_CACHE.items():
        if os.path.basename(_spill_name(url)) == base:
            return html_page_about_a_file(url, _greppable(cached[2], cached[3], cached[1]))
    return False


def format_for_spill_path(path: str) -> str:
    """The sniffed format of the spilled doc at ``path`` — "" when it is not cached (rule 5b: cria
    states the format it has actually seen, never a guess from the file extension)."""
    base = os.path.basename(os.path.normpath((path or "").strip()))
    if not base:
        return ""
    for url, cached in _DOC_CACHE.items():
        if os.path.basename(_spill_name(url)) == base:
            return _doc_format(_greppable(cached[2], cached[3], cached[1]))
    return ""


def spill_path_for(url: str) -> str:
    """The spill file this url's document was written to, or "" when it was small enough to inline.

    Asked so a ledger line can say WHERE the content is instead of assuming it is in the
    conversation. The fetch record used to end "whatever it returned is in the transcript", which is
    false for exactly the documents that most need reading — an oversized one is spilled here and the
    read of that file is then refused, so the only place cria pointed at was the only place the
    content was not. Same cache, same name function, same threshold as :func:`oversized_spill`, so
    the two can never disagree about whether a spill happened (#23)."""
    cached = _DOC_CACHE.get(url)
    if not cached or len(cached[2]) <= OVERSIZE_CHARS:
        return ""
    return _spill_name(url)


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
    fmt = _doc_format(content)
    # SAY WHAT ACTUALLY LANDS. `writeproxy._spill_command` cuts anything past SPILL_CONTENT_MAX and
    # appends its own honest note — so this message claiming "saved IN FULL" put a flat
    # contradiction in the same tool result. The composer holds both numbers; it picks the sentence.
    whole = len(content.encode("utf-8", "replace")) <= SPILL_CONTENT_MAX
    fmt_clause = f" It is {fmt}." if fmt else ""
    if html_page_about_a_file(url, content):
        # SAY WHAT WAS SAVED. The next message tells the reader to grep this file; without this it
        # greps a page's markup for the file's own code and reads the absence as the library's.
        fmt_clause += " " + _guard_msg("spill_is_the_page_not_the_file")
    msg = _guard_msg("spill", status_label=status_label(status), url=url,
                     chars=f"{len(content):,}", target=target,
                     extent=_guard_msg("spill_extent_full" if whole else "spill_extent_cut"),
                     format=fmt_clause,
                     outline=_spill_outline(parsed, target))
    return status, target, content, msg


def spill_extent_of(url: str) -> str:
    """The clause naming HOW MUCH of ``url`` is in its spill file — the same question the first spill
    message answers, asked again by every later refusal that names that file.

    `spill` branches on the byte count; `fetch_repeat_spilled` hardcoded "IN FULL", so cria said both
    things about one file in one conversation. Walked twice: cart-billing-go x nemotron-elastic
    1787434778 at call 0058 ("holds the first 46,080 characters of a 67,564-character document") and
    at 0062 ("saved IN FULL"), and shipping-rates-rb x nemotron-elastic 1787432916 on a file holding
    14% of its document. The coder then grepped the part cria kept and read the absence as the
    library's, not the file's (#5b)."""
    cached = _DOC_CACHE.get(url)
    if cached is None:
        return _guard_msg("spill_extent_unknown")
    content = _greppable(cached[2], cached[3], cached[1])
    whole = len(content.encode("utf-8", "replace")) <= SPILL_CONTENT_MAX
    return _guard_msg("spill_extent_full" if whole else "spill_extent_cut")


def _ref_map(parsed: Any) -> dict:
    """Everything a ``$ref`` can point at, keyed by its FINAL path segment — merged across the dialects'
    containers: OpenAPI 3's ``components/*``, Swagger 2's top-level ``definitions`` / ``parameters`` /
    ``responses``, and JSON Schema's ``$defs``. :func:`_deref` resolves by last segment, so one flat map
    is exactly what it wants.

    Only ``components/schemas`` was consulted before, so for a SWAGGER 2 spec every response
    ``$ref: #/definitions/X`` resolved to nothing and the endpoint outline carried NO response fields at
    all — the same "has the endpoint, guesses the response shape" failure that cost runs g15-g18, but
    total instead of partial. Components merge LAST, and schemas last within them, so the richest
    dialect wins a name collision."""
    out: dict = {}
    if not isinstance(parsed, dict):
        return out
    for key in ("responses", "parameters", "$defs", "definitions"):
        sub = parsed.get(key)
        if isinstance(sub, dict):
            out.update({str(k): v for k, v in sub.items() if isinstance(v, dict)})
    comp = parsed.get("components")
    if isinstance(comp, dict):
        for key in ("securitySchemes", "headers", "examples", "requestBodies", "responses",
                    "parameters", "schemas"):
            sub = comp.get(key)
            if isinstance(sub, dict):
                out.update({str(k): v for k, v in sub.items() if isinstance(v, dict)})
    return out


def _base_path(parsed: Any) -> str:
    """The path prefix the spec says its routes hang off — Swagger 2's ``basePath``, or the path
    component of OpenAPI 3's first ``servers[].url``. Empty when the spec declares none.

    A spec's ``paths`` keys are RELATIVE to this. Listing them bare told the model that
    ``/handles/{handle}`` is the route when the real one is ``/v2/handles/{handle}`` — cria stating a
    false fact about how to call the API, which is the exact class of error the g18 walk found the
    steer author making in prose (four steers arguing about a ``/v1/`` prefix)."""
    if not isinstance(parsed, dict):
        return ""
    base = parsed.get("basePath")
    if not isinstance(base, str):
        servers = parsed.get("servers")
        first = servers[0] if isinstance(servers, list) and servers else None
        url = first.get("url") if isinstance(first, dict) else None
        if not isinstance(url, str):
            return ""
        # A server url may be absolute (https://host/v2) or already just a path (/v2).
        base = urllib.parse.urlsplit(url).path if "//" in url else url
    base = (base or "").strip().rstrip("/")
    return base if base.startswith("/") and base != "/" else ""


def _deref(sch: Any, schemas: dict) -> dict:
    """Follow ``$ref`` into ``components/schemas`` until a real schema is reached (bounded, so a
    self-referential spec can't spin). A ``$ref`` is a POINTER, not a shape: resolving it before
    classifying is the difference between "this field is an object" and the truth."""
    hops = 0
    while isinstance(sch, dict) and "$ref" in sch and hops < 8:
        sch = schemas.get(str(sch["$ref"]).rsplit("/", 1)[-1], {})
        hops += 1
    return sch if isinstance(sch, dict) else {}


# How much of a field's declared example rides along, when the example is what gets shown. Long
# enough to carry a distinguishing PREFIX (`stake1u…` vs `addr1…`, `ipfs://…`).
EXAMPLE_CHARS = 32

# THE DESCRIPTION WINS WHERE THERE IS ONE (operator ruling, 2026-08-07: "I would prefer description
# over example. It is much more helpful"). This reverses an earlier measured call that left
# descriptions out because they "mostly restate the field name" and cost 4.4×. What that measurement
# missed is the case where the example is not merely redundant but WRONG-SIGNALLING: in the Ada
# Handles `Handle` schema, `resolved_addresses.ada` and `original_address` declare the SAME example,
# `addr1e00000000000000000000000000000000000001`, and cria printed them adjacent with nothing else
# to tell them apart. maple-preview 1786081695 read them as one thing, made `original_address`
# mandatory, and its CLI exited 1 on every handle. The description cria was holding says exactly
# what the example could not: "If enabled by the root Handle owner, this will show the address that
# the SubHandles was originally sent to on mint".
#
# Cost, measured on that spec (37 leaf fields, 32 with a description): examples ~573 chars,
# descriptions uncapped ~3,523 (6.1x). Capped at 96 it is ~1,960 (3.4x) — the cap is what makes the
# preference affordable, and it is generous enough to carry a full sentence. The two 407-character
# outliers (`characters`, `sub_characters`) are prose with embedded <br /> markup; they truncate.
DESCRIPTION_CHARS = 96


# A "placeholder" example — one character repeated. `stake1uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`,
# `addr1e00000000000000000000000000000000000001`. 20 of the Ada Handles spec's 74 examples are this
# shape, including every address field the task needs.
#
# THESE MUST NOT BE SHOWN. A small model copies them, and a run of one character is the classic seed
# for a degenerate generation. This was walked once before and answered by eliding the MIDDLE
# (`addr1e000000000…0001`), which was not enough: on mellum2 1786137318 the coder was writing a
# README example, expanded cria's placeholder back into a full zero-run, and hit the generation cap
# — `[finish: rumination]`, one whole call lost. The recovered README still carries
# `addr1e00000000000000000000000000000000000000000000000` as both the holder and the resolved
# address, and cria's other example `my.handle` came back as `my.handle.handle.me`. The README was
# that run's ONE failing deliverable and it is largely made of cria's placeholder strings.
#
# A placeholder carries no information the type does not already carry — `addr1e000…0001` says
# "string" and nothing else. Dropping it costs the coder nothing and stops handing it a loop seed.
_PLACEHOLDER_RUN = re.compile(r"(.)\1{5,}")


def _example_hint(v: dict) -> str:
    """`, e.g. <value>` from a field's declared example, or "" when the spec gives none.

    THE fix for the biggest measured cluster in the mellum2 walks. A type alone cannot distinguish
    two string fields, and the whole task turned on which one held a STAKE address: the spec says
    `holder` is `stake1uxxxx…` and `resolved_addresses.ada` is `addr1e00…`, and cria rendered both as
    `(string)`. Run after run chained the payment address into `/holders/{address}` and got a 404 —
    with the answer sitting in a document cria had fetched, parsed, and dropped this line from.
    25 of that spec's 34 response fields carry one."""
    # THE DESCRIPTION FIRST. It says what the field IS; an example only ever hints at it, and when
    # two fields share one example it hints wrong. See DESCRIPTION_CHARS.
    d = " ".join(str(v.get("description") or "").split())
    d = re.sub(r"<[^>]{1,20}>", " ", d)        # specs embed <br /> and friends in prose
    d = " ".join(d.split())
    if d:
        return f" ({d[:DESCRIPTION_CHARS - 1]}…)" if len(d) > DESCRIPTION_CHARS else f" ({d})"
    ex = v.get("example")
    if ex is None or isinstance(ex, (dict, list)):
        return ""    # a structural example is the shape again, not a discriminating value
    s = " ".join(str(ex).split())     # one line: a multi-line example would break the field list
    if not s or _PLACEHOLDER_RUN.search(s):
        return ""    # a run of one character is a loop seed, not an example — see above
    if len(s) <= EXAMPLE_CHARS:
        return f" (e.g. {s})"
    # ELIDE THE MIDDLE, never the tail. A head-only cut ending in `…` reads as "and it continues",
    # and spec placeholders are mostly a long run of one character: the Ada Handles spec's `ada`
    # example is `addr1e00000000000000000000000000000000000001`, which TERMINATES, and cutting it at
    # 32 produced `addr1e00000000000000000000000000…`. Walked on
    # ada-handles_mellum2_codex_poff_1785714194 call 0015: the model copied that and could not stop —
    # it emitted exactly 2,048 zeros before a guard caught it. Keeping both ends shows the shape and
    # the terminator, cannot be read as open-ended, and is shorter than the head-only form was.
    keep = max(4, (EXAMPLE_CHARS - 1) // 2)
    return f" (e.g. {s[:keep]}…{s[-4:]})"


def _schema_field_summary(sch: Any, schemas: dict, max_fields: int, _depth: int = 0) -> list[str]:
    """Top-level property names of an OpenAPI object schema, dereferencing a ``$ref`` into
    ``components/schemas``. A nested object is expanded ONE level (``resolved_addresses{ada, eth, btc}``)
    so the model sees the real nesting it otherwise guesses; an array field is marked ``[]``; every
    other field carries its declared scalar type (``holder(string)``, ``length(integer)``).

    Both halves of that are load-bearing, and both were wrong. A field was called an object whenever it
    merely CARRIED a ``$ref`` — which in the Ada Handles spec mislabels 19 of 241 response fields, 8 of
    them (``handle_type``, ``holder_type``, ``rarity``, ``characters`` …) on the one endpoint the task
    needs; they are all plain strings. And scalars carried no type at all, so the one field that mattered
    read as unknown shape sitting in a crowd of "(object)". The coder's own words, three runs running:
    "gives resolved_addresses.ada … and a holder OBJECT; then I need to call GET /holders/{holder.address}".
    ``holder`` is a string — the holder's stake address — so ``holder.address`` was None, the model
    substituted the payment address it did have, and every second lookup 404'd."""
    sch = _deref(sch, schemas)
    if not sch:
        return []
    props = sch.get("properties")
    if not isinstance(props, dict):
        return []
    out = []
    items = list(props.items())
    for k, v in items[:max_fields]:
        v = _deref(v if isinstance(v, dict) else {}, schemas)
        if _depth == 0 and (v.get("type") == "object" or "properties" in v):
            # A NESTED FIELD IS NAMED BY ITS ACCESS PATH — `resolved_addresses.ada`, not
            # `resolved_addresses{ada}`. The brace form asks the coder to infer that `{}` means
            # nesting, and it infers wrong: walked verbatim, a coder read `holder(string)` as an
            # object and went looking for `holder.address` on a field the spec declares a plain
            # string, 404ing every second lookup. The dotted path IS what it must type.
            # NB: pass the WHOLE `sub` through. It already ends with its own "…+N more field(s)"
            # marker when the nested object was capped, and slicing it here threw that marker away —
            # a nested field past the cap then read as "the API does not return it", under a prompt
            # that says "use these EXACT names … do not guess". Never a silent slice.
            sub = _schema_field_summary(v, schemas, max_fields, _depth + 1)
            if not sub:
                out.append(f"{k}: object")
            else:
                # The cap disclosure is a NOTE, not a field — `nested.…+5 more field(s)` reads as a
                # field literally named `…`. It keeps the parent, with a separator that says so.
                out.extend(f"{k}: {s}" if s.startswith("…") else f"{k}.{s}" for s in sub)
        elif v.get("type") == "array":
            out.append(f"{k}: array")
        elif v.get("type"):
            out.append(f"{k}: {v['type']}{_example_hint(v)}")
        else:
            out.append(str(k))   # the spec itself declares no type — say nothing rather than guess
    # DISCLOSE the cap. A silently-cut field list reads as the complete set, so a coder looking for a
    # field that exists but sits past the cap concludes the API doesn't return it — and guesses. Same
    # rule as the endpoint list and the find residual: never a silent slice.
    if len(items) > max_fields:
        out.append(f"…+{len(items) - max_fields} more field(s)")
    return out


# The per-endpoint TOP-LEVEL field cap. MEASURED across the whole capture corpus 2026-08-03, and
# re-derived independently at review: a capped list appears in 12,599 prompt captures, 33,537
# occurrences in all, and the number of fields hidden is only ever **4 or 6** — those are the only
# two values that occur. So the old cap of 30 was paying "the coder cannot tell whether this field
# exists" to save at most six field names. The comment above states that cost in its own words: "a
# coder looking for a field that exists but sits past the cap concludes the API doesn't return it —
# and guesses."
#
# WHAT THIS CONSTANT ACTUALLY CLEARS, stated exactly, because the first draft of this comment
# claimed the whole 12,599 and that is false. The two hidden counts have two different sources:
#   * `+4` — 16,588 occurrences — is THIS cap, on `GET /handles/{handle}` (34 fields). Raising it
#     to 40 clears it, and that is the endpoint whose missing tail cost a run.
#   * `+6` — 16,949 occurrences — is the NESTED cap, the literal `8` in the `_depth == 0` recursion
#     above, on `stats{…}` inside `GET /health`. This constant does not touch it.
# THE NESTED CAP IS NOW THIS SAME CONSTANT, and the `8` is gone. Measured first: across every
# capture dir exactly ONE object is ever nested-capped — `stats` inside `GET /health`, 14 fields, 6
# hidden — and the six are node-sync internals (`current_block_hash`, `tip_block_hash`,
# `utxo_schema_version`, `index_schema_version`, `lock_lambdas`, `estimated_sync_time`) that no
# deliverable in the corpus has needed. That measurement was used, wrongly, to leave the `8` alone.
# "No task has needed these particular fields" is a judgement about ONE api and ONE task family,
# and cria is meant to be agnostic to both; the rule stated two paragraphs up says nothing about
# whether a hidden field is interesting — a field that exists must never read as absent. One cap,
# one rule, both levels. Cost on the document that cost a run: 137 characters, and it is the last
# elision in it — that spec now renders with no `…+N more field(s)` at either level.
#
# It has a second cost: it blinds cria's OWN checks. Absence from a TRUNCATED list is not evidence a
# field is missing, so any ledger-contradiction check must abstain on every capped endpoint — which
# is why such a check has to re-read the parsed document instead of trusting the ledger.
#
# 40 clears both captured versions of the one observed spec, but not with much room: the newer
# swagger.yml renders 36 fields, four short of the cap, and grew by two between the two captures.
# Cost of the raise, measured: +80 chars on the older document, +149 on the newer, worst case 4.7%
# of a single 34,838-char prompt and 0.378% corpus-wide. The cap and its disclosure stay: a
# pathological spec must still be bounded, and a SILENT slice is the thing that is actually forbidden.
FIELD_CAP = 40


def _schema_json_shape(sch: Any, schemas: dict, max_fields: int, _depth: int = 0) -> dict:
    """The response schema as a JSON OBJECT — the form every API doc on the internet uses.

    THE NOTATION HAD NO TRAINING DATA BEHIND IT. cria invented `hex(string), name(string, e.g.
    my.handle), resolved_addresses{ada(string)}` and then, when that was shown to bury the nested
    field, invented `resolved_addresses.ada: string (e.g. …)`. Both are cria dialects. No model was
    ever trained on either, and the operator called it: pick something common in real languages.

    A JSON object is what the coder is actually holding — `json.load()` returns this shape — so
    there is no translation step between what it reads and what it must type. `"resolved_addresses":
    {"ada": …}` and `data["resolved_addresses"]["ada"]` are the same structure twice.


    OPTIONAL FIELDS CARRY `?`, the TypeScript convention. The spec says which: the Ada Handles
    `Handle` schema declares `required: ["name"]` — ONE of its 34 properties — and the live
    `/handles/goose` response returns 30 keys with `original_address` absent. cria had that array
    parsed and threw it away, rendering all 34 identically under a header promising "the fields each
    endpoint RETURNS". maple-preview 1786081695 read that as a contract and wrote
    `required_fields = ["resolved_addresses", "holder", "original_address"]`, so its CLI exited 1 on
    every handle — `Error: Missing required field: original_address` — before it ever reached the
    address extraction it had, for once, got right. Two independent walkers reached the same cause.

    Types go where the VALUE goes, which is how a schema block is written in practically every API
    reference: `"length": "integer"`. The declared example rides in the same string, because a type
    alone cannot tell two string fields apart and the whole task turned on which one held a stake
    address (see :func:`_example_hint`). Costs 8% more characters than the flat line it replaces."""
    sch = _deref(sch, schemas)
    props = (sch or {}).get("properties")
    if not isinstance(props, dict):
        return {}
    req = {str(r) for r in ((sch or {}).get("required") or []) if isinstance(r, (str, int))}
    out: dict = {}
    items = list(props.items())
    for k, v in items[:max_fields]:
        # A schema with NO `required` array declares nothing mandatory — every key is then optional
        # and every key gets the marker. Saying "all optional" is the spec's own answer; assuming
        # the opposite is what shipped a CLI that dies on a field the API omits.
        k = k if k in req else f"{k}?"
        v = _deref(v if isinstance(v, dict) else {}, schemas)
        if _depth == 0 and (v.get("type") == "object" or "properties" in v):
            out[k] = _schema_json_shape(v, schemas, max_fields, _depth + 1) or ("object", "")
        elif v.get("type") == "array":
            out[k] = ("array", "")
        else:
            # (type, example) — kept APART so the example can be a comment rather than being
            # crammed into the value, where it read as part of the type.
            out[k] = (str(v.get("type") or "?"), _example_hint(v).strip().lstrip("(").rstrip(")"))
    # DISCLOSE the cap — a silently-cut list reads as the complete set, and a coder looking for a
    # field that sits past it concludes the API does not return it, under a header saying "do not
    # guess". Same rule as the endpoint list and the find residual: never a silent slice.
    if len(items) > max_fields:
        out[f"…+{len(items) - max_fields} more field(s)"] = ("", "")
    return out


# A key TypeScript can write bare. Anything else gets quoted, which TS also accepts.
_TS_IDENT = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
# OpenAPI's type names -> TypeScript's. `?` means the spec declared none; `unknown` is TS's word
# for exactly that, and it is honest where `any` would be a shrug.
_TS_TYPES = {"integer": "number", "number": "number", "string": "string", "boolean": "boolean",
             "array": "unknown[]", "object": "object", "null": "null", "?": "unknown"}


def _ts_rows(shape: dict, indent: int) -> list[tuple[str, str]]:
    """(code, comment) per line, so the comment column can be aligned once over the whole block."""
    pad = " " * indent
    rows: list[tuple[str, str]] = []
    for k in shape:
        v = shape[k]
        opt = k.endswith("?")
        name = k[:-1] if opt else k
        if name.startswith("…"):                       # the cap disclosure is a note, not a field
            rows.append((f"{pad}// {name}", ""))
            continue
        key = (name if _TS_IDENT.match(name) else f'"{name}"') + ("?" if opt else "")
        if isinstance(v, dict):
            rows.append((f"{pad}{key}: {{", ""))
            rows.extend(_ts_rows(v, indent + 2))
            rows.append((f"{pad}}};", ""))
        else:
            typ, note = v if isinstance(v, tuple) else (str(v), "")
            rows.append((f"{pad}{key}: {_TS_TYPES.get(typ, typ)};", note))
    return rows


def render_jsonc(shape: dict) -> str:
    """The shape as a fenced TypeScript object type — `{ field?: type; }`, no interface name.

    THE `?` HAS TO LIVE OUTSIDE THE KEY. The version before this marked optionality inside a JSON
    key — `"holder?": "string"` — which in JSON means the key is literally `holder?`. It is valid
    JSON and completely wrong, and maple-preview 1786129064 read it exactly as written:

        resolved_address = data.get('hex?')
        holder_address = data.get('holder?')      # "field is 'holder?', not 'holder'"

    Every lookup returned None and the CLI raised `Handle not found` on every handle. I had borrowed
    TypeScript's `field?: type` and then written it in a notation where that convention does not
    exist. Operator's call: use TypeScript itself, where the `?` sits outside the key by
    construction and cannot be pasted into a lookup.

    Per-field marking is also the only general answer. A one-line header ("only `name` is
    guaranteed") happens to be short for this spec; a spec with twenty required fields would need a
    paragraph. TS marks each field where it stands.

    No `interface Foo` wrapper (operator: "just start with the open curly brace") — cria would have
    to invent a name per endpoint, and an invented name is one more thing that can be believed."""
    rows = _ts_rows(shape, 2)
    width = max((len(c) for c, m in rows if m), default=0)
    body = "\n".join(c + (f"{' ' * (width - len(c) + 2)}// {m}" if m else "") for c, m in rows)
    return "```ts\n{\n" + body + "\n}\n```"


def _endpoint_response_fields(parsed: Any, max_endpoints: int = 12, max_fields: int = FIELD_CAP) -> list[str]:
    """For an OpenAPI/Swagger-shaped spec: each endpoint's SUCCESS-response fields, dereferenced through
    the response schema's ``$ref`` (see :func:`_ref_map`) — so a coder knows WHAT an endpoint returns
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
    schemas = _ref_map(parsed)
    base = _base_path(parsed)
    lines: list[str] = []
    shaped: list[str] = []  # paths already given a shape — used to collapse a resource's own sub-paths
    capped = False
    for path, ops in paths.items():
        if len(lines) >= max_endpoints:
            capped = True   # DISCLOSED below — a silent cut reads as "these are all the endpoints"
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
            r = _deref(r, schemas) if isinstance(r, dict) else None   # responses may themselves be $refs
            content = r.get("content") if isinstance(r, dict) else None
            schema = None
            if isinstance(content, dict):
                for v in content.values():
                    if isinstance(v, dict):
                        schema = v.get("schema")
                        break
            if schema is None and isinstance(r, dict):
                schema = r.get("schema")   # Swagger 2.0 hangs the schema straight off the response
            shape = _schema_json_shape(schema, schemas, max_fields)
            if shape:
                # PATH PARAMETERS carry the other half of "how do I call this": what to PUT IN. Across
                # 13 measured runs the outline listed /holders/{address}'s OUTPUT fields but never that
                # {address} means "The stake/enterprise/script/other address of the Holder" — so the
                # model chained the payment address it had just resolved into it and got a 404, in
                # every single run. Outputs without inputs is half a spec.
                params = _path_param_notes(op, ops, schemas)
                head = f"{str(method).upper()} {base}{path}"
                if params:
                    # WORDING IS LOAD-BEARING: the first cut said "(takes {address} = …)" and the
                    # model read "takes" as "accepts an argument" — it turned BOTH path parameters
                    # into query strings (?handle=…, ?address=…) and got 400/404 on every call,
                    # where every earlier run had built the path form correctly. Say plainly that
                    # the placeholder is part of the URL and must be replaced in place.
                    head += f" (replace in the URL path: {'; '.join(params)})"
                # The JSON body is INDENTED under its endpoint line. The caller prefixes each
                # entry with two spaces, so an unindented body would make every `{`, every field
                # and every `}` look like a new endpoint to anything reading the block by line.
                lines.append(f"{head} returns:\n" + render_jsonc(shape))
                shaped.append(path)
                # EVERY METHOD, not the first one that happens to have a schema. `break` here meant
                # a path whose GET was shaped never showed its POST — and a coder writing the POST
                # body is exactly who needs that shape. The skip was undisclosed, so the block read
                # as the complete set of shapes for that path.
    if capped:
        lines.append(f"…+more endpoints have shapes not shown here — web_fetch find=\"<path>\" for one")
    return lines


def _path_param_notes(op: dict, ops: dict, schemas: dict, max_len: int = 90) -> list[str]:
    """``{name}: <description>`` for each PATH parameter of an operation — the spec's own words for
    what the caller must supply. Reads the operation's parameters and the path-level ones (both are
    legal OpenAPI), resolves a $ref into components, and falls back to the example when a parameter
    carries no description. Empty when the spec says nothing — cria never invents the meaning."""
    out: list[str] = []
    seen: set[str] = set()
    raw = list(op.get("parameters") or []) + list(ops.get("parameters") or [])
    for prm in raw:
        if not isinstance(prm, dict):
            continue
        if "$ref" in prm:
            ref = str(prm["$ref"]).rsplit("/", 1)[-1]
            prm = ((schemas or {}).get(ref) if isinstance(schemas, dict) else None) or {}
            if not isinstance(prm, dict):
                continue
        if prm.get("in") != "path":
            continue
        name = str(prm.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        note = str(prm.get("description") or "").strip().replace("\n", " ")
        if not note:
            ex = prm.get("example") or (prm.get("schema") or {}).get("example")
            note = f"e.g. {ex}" if ex else ""
        if note:
            out.append(f"{{{name}}} = {clip(note, max_len)}")
    return out


def _shape_block(shapes) -> str:
    """The response-shape section, from ONE owner (#23).

    THE WORDING IS THE POINT, AND IT DRIFTED. Three sites rendered this header and two of them were
    corrected on 2026-08-06 to say the fields MAY come back; the third went on promising "the fields
    each call RETURNS (extract these...)" until the test audit of 2026-08-19 opened it. The
    change-detector that was supposed to catch that searched the module for the exact old sentence
    with the word "endpoint" in it — and the survivor said "call", so it passed. Three copies of a
    sentence is how a corrected fact stays wrong in one place; one owner is the fix, and the test
    now asserts the RENDERED block rather than the source.

    `?` marks a field the spec does not guarantee, which is why the promise had to soften: telling a
    coder a field comes back when the spec says it may is a false fact (#5b), and it is the kind
    that shows up as a KeyError in the deliverable."""
    if not shapes:
        return ""
    return (f"{SHAPE_MARKER} the fields each endpoint MAY return — `?` marks a field the spec does "
            "NOT guarantee, so read it defensively; use these EXACT names and nesting, and do not "
            "guess:\n" + "\n".join(f"  {s}" for s in shapes) + "]\n")


def _spill_outline(parsed: Any, target: str) -> str:
    """A navigation outline for a SPILLED structured doc (JSON or YAML — both parse to ``parsed``): the
    API routes when it's spec-shaped, else the top-level keys — so the model greps straight to what it
    needs instead of paging a huge file top-to-bottom. This is the exact gap that sank the Ada-handle
    run: the 2872-line spec spilled with no outline, so the coder read 800 lines linearly, never reached
    /holders or resolved_addresses, and gave up. Same shape-branch as render_page's inline outline,
    keyed off real bytes; the grep example uses a REAL route/key (no ``<placeholder>`` to echo). Ends
    with a newline when non-empty; "" when the doc has no walkable structure (an HTML/text spill)."""
    catalog = _catalog_links(parsed)
    if catalog:
        # Same treatment a catalogue gets inline. A catalogue big enough to SPILL would otherwise be
        # written to a file with an outline that never mentioned the one thing it contains — hrefs.
        return (f"{CATALOG_MARKER}{len(catalog)}): where each API's spec and docs live — fetch one "
                "of these urls]\n" + "\n".join(f"  {c}" for c in catalog) + "\n")
    routes = _endpoint_routes(parsed)
    if routes:
        shapes = _endpoint_response_fields(parsed)
        shape_block = _shape_block(shapes)
        # The grep example is a REAL route as a FIXED string — and it must be the PATH alone.
        # Walked twice, on two different model families (finetune run 1785893473 call 0019, stock
        # run 1785948232 call 0005): the shape lines above read "GET /handles/{handle} → …", both
        # coders grepped the file for that exact label, and the spec stores the method as a KEY
        # INSIDE the route's object — zero hits, and each read the empty result as "the file is
        # wrong/missing". cria's own rendering taught the ungreppable string; the hint now hands
        # over a command that provably matches (JSON quotes the path, YAML doesn't; -F on the bare
        # path matches both).
        # The example route must itself be a USEFUL grep target: an earlier seeded example used
        # routes[0] blindly, a real spec's routes[0] was "/", and the degenerate `grep "/"` sent
        # the coder crawling the meta-path aliases. Prefer a parameterized route (the kind the
        # task actually needs), else the first non-trivial one; none → the plain list phrasing.
        example = next((r for r in routes if "{" in r), next((r for r in routes if len(r) > 1), None))
        hint = (f"[grep for a route as a FIXED string, e.g.: grep -n -F '{example}' {target} — "
                f"the METHOD (GET/POST) is a key INSIDE the route's section, so grepping "
                f"'GET /path' matches nothing]\n") if example else \
               (f'[grep {target} for the endpoint you need FROM THAT LIST, or read_file it with a start_line/end_line range]\n')
        return (f'{ROUTES_MARKER}{len(routes)}): {", ".join(routes)}]\n'
                f'{shape_block}' + hint)
    keys = [k for k in top_level_keys(parsed) if k != "[array]"]
    if keys:
        return (f'[top-level keys ({len(keys)}): {", ".join(keys)}]\n'
                f"[grep for a key as a FIXED string, e.g.: grep -n -F '{keys[0]}' {target}, "
                f'or read_file it with a start_line/end_line range]\n')
    return ""


def _pad4(k):
    """A fetch key as a 4-tuple (url, find, cursor, raw). Accepts a legacy 3-tuple (raw→False) so a
    caller that hasn't learned about ``raw`` still records a valid key."""
    return tuple(k) + (False,) if len(k) == 3 else tuple(k)


def note_fetch_spill(session: Optional[str], url: str, path: Optional[str] = None) -> None:
    """Record that cria WROTE this url's document to a file, and WHERE.

    Recorded by the caller that actually issues the spill, so this is a fact about what cria did, not
    an inference from the cache being large. The path matters because the refusal built on this
    ledger names it to the model — and a session key is not always unique to a workspace: with no
    session id from the harness, `session_key` falls back to a hash of the first user message, so two
    runs of the SAME prompt share one key. MEASURED (run 0727-131647): the second run's very first
    web_fetch was refused with "already fetched … saved to ./tmp/read-only/api.handle.me_openapi.json"
    — a path that existed only in the PREVIOUS run's workspace. It never saw the spec at all."""
    if session and (url or "").strip():
        _FETCH_SPILLED.setdefault(session, {})[url.strip()] = path or ""


def already_spilled(session: Optional[str], url: str, workspace_root: Optional[str] = None) -> bool:
    """Did cria write this url's document to a file THIS run can read? The ledger remembers; the
    FILESYSTEM decides — so a spill from another workspace (or one the model deleted) is not claimed."""
    if not session:
        return False
    path = _FETCH_SPILLED.get(session, {}).get((url or "").strip())
    if path is None:
        return False
    if not path:            # recorded before the path was known — nothing to verify against
        return True
    if workspace_root and not os.path.abspath(path).startswith(os.path.abspath(workspace_root) + os.sep):
        return False
    # THE RECORD IS NOT EVIDENCE. It is written at COMPOSE time, one line before the command is even
    # returned — so it says cria INTENDED to write the file, never that the harness wrote it. When the
    # exec is refused (an oversized spill, a sandbox rejection) nothing lands, and a claim built on
    # that record is a false fact cria then defends.
    #
    # Walked on handles-cli-node x nemotron-elastic 1787273429: the spill exec was refused, and for
    # twenty-six turns cria told the model "that file is still there" in one paragraph while its own
    # read guard answered "is not there — nothing was read" in the next. The model re-fetched the
    # same 111 KB document seven times.
    #
    # So this needs the FILESYSTEM to say yes, not merely to fail to say no. Unknown re-allows a
    # fetch, which costs a turn; the other direction cost twenty-six. (This line said `is not False`
    # for a day — the reasoning was that withdrawing a claim on an unanswered question would send the
    # model to re-fetch a doc it has. That is right for a claim cria VERIFIED and wrong for one it
    # only intended.)
    from . import wsview
    return wsview.current().exists(path) is True


def note_search_spill(session: Optional[str], query: str, target: Optional[str] = None) -> None:
    """Record that cria SPILLED this query's results, AND THE PATH IT WROTE — the only warrant for
    later telling the model to go read that file. Set by the synthetic Brave path; a harness-native
    search never sets it.

    THE PATH IS REMEMBERED, NOT RECOMPUTED. The repeat refusal used to derive the filename again from
    the earlier query's text, and `search_spill_name` digests that text — so two spellings of one
    search ("...detect EU membership" / "...detect eu membership") name two different files while
    only one was ever written. Live on shipping-rates-rb x nemotron-elastic 1787431835: cria sent the
    coder to `search-ruby_gem_detect_eu_membership-2d34dace.txt`, the coder read it, and cria answered
    "is not there — nothing was read" about its own suggestion, which then rode in 26 later prompts
    (#5b, and #R5 — a remedy the reader cannot take). A name derived twice from two inputs is two
    names; the write knows which one it made."""
    if session and (query or "").strip():
        q = query.strip()
        _SEARCH_SPILLED.setdefault(session, {})[q.lower()] = (q, target or search_spill_name(q))


def spilled_path(session: Optional[str], query: str) -> str:
    """The file cria wrote for this query, as cria wrote it. Empty when it spilled no such file."""
    rec = (_SEARCH_SPILLED.get(session) or {}).get((query or "").strip().lower())
    return rec[1] if rec else ""


def spilled_search_files(session: Optional[str]) -> dict:
    """``{spill file: the query that produced it}`` for this session — cria's own record of what it
    wrote, and the only warrant for judging one of those files.

    A file cria did not spill is simply absent, and the judge is skipped rather than asked to rule on
    a query nobody knows. That is also what happens across a restart, which is the right direction:
    the verdict is destructive, so an unremembered file costs the model nothing (#13)."""
    return {path: orig for orig, path in (_SEARCH_SPILLED.get(session) or {}).values()}


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


# The guard keys that REFUSE a call — the fetch or the search did not run, and this text stands in
# its place. Named by KEY, at the one place a guard message is rendered, so the mark is a property of
# the decision cria made and never of the words it chose (:mod:`cria.denial`).
#
# The rest of the map is deliberately absent, and the distinction is the whole point of listing them:
# `spill` / `search_spill` are the results of a fetch that DID run (an oversized document really was
# retrieved and saved), and `domain_steer` / `guess_hint` / `find_large` are fragments appended to a
# real result. Marking those would tell a judge a successful fetch never happened.
_REFUSAL_KEYS = frozenset({
    "search_repeat", "search_repeat_inline",
    "fetch_repeat", "fetch_repeat_failed", "fetch_repeat_spilled",
})


def _guard_msg(key: str, **tokens: object) -> str:
    """One loop-guard message from prompts/webfetch_guards.txt (re-read per call so it's tunable
    without a restart), with its {{TOKEN}}s filled — marked as a call that did not run when this key
    is one of the repeat gates (:data:`_REFUSAL_KEYS`).

    A repeat-gate refusal often CARRIES real ground truth: `fetch_repeat_spilled` embeds the
    document's own route and response-shape outline. The mark says only that the call did not run;
    what it says about the body is nothing at all, deliberately."""
    text = prompts.fill(prompts.load_map("webfetch_guards")[key], **tokens)
    return denial.mark(text) if key in _REFUSAL_KEYS else text


def prior_matching_search(session: Optional[str], query: str) -> Optional[str]:
    """The earlier visible search this one would be refused as a repeat of, or None.

    Exported so a caller that CAN reason (the loop, which has the reasoner) asks its question about
    exactly the pair :func:`gate_search` would act on. Same code, one verdict — a second matcher
    would drift from this one and the reasoner would be asked about the wrong prior."""
    q = (query or "").strip()
    if not session or not q:
        return None
    words = normalize_search(q)
    if not words:
        return None
    return next((prev for prev in _SEARCH_SEEN.get(session, ())
                 if searches_match(words, normalize_search(prev))), None)


def allow_search(session: Optional[str], query: str) -> None:
    """Record that this query has been judged a genuinely NEW direction, not a re-hunt — so
    :func:`gate_search` lets it run ONCE.

    The overlap test is four hand-tuned constants deciding whether to REFUSE the model's own tool
    call, and cria has already removed a sibling threshold rule for over-firing ("0.6 core-overlap
    binds distinct searches"). The constants stay as the cheap trigger; when a reasoner has actually
    looked at the pair and says these are different hunts, that judgement wins.

    The clearance is CONSUMED by the run it permits (see :func:`gate_search`). "This is a new
    direction" licenses running it, never re-running it: measured (run 0727-103922) a standing
    clearance let the coder issue the identical search three times, which is the exact loop this
    gate exists to stop."""
    if session and (query or "").strip():
        _SEARCH_ALLOWED.setdefault(session, set()).add(query.strip().lower())


def gate_search(session: Optional[str], query: str) -> Optional[str]:
    """Refuse a repeat web_search ONLY while its results are still in the conversation
    (`set_visible`); else the model may re-run it. None → proceed.

    Matches on the normalized word-SET, not the exact string (the codex-local loop_detector
    ported in `searchloop`): a weak model ruminating on the same search tweaks the wording just
    enough to slip past an exact-string guard — the live path saw a model run ~30 near-identical
    searches by alternating "…API resolve…" / "…API endpoint resolve…". A genuine refinement or a
    new direction is NOT matched; only a re-hunt (see `searches_match`) — and a query a reasoner has
    cleared as a new direction (:func:`allow_search`) is never refused."""
    q = (query or "").strip()
    if not session or not q:
        return None
    if q.lower() in _SEARCH_ALLOWED.get(session, ()):
        _SEARCH_ALLOWED[session].discard(q.lower())   # consumed: it permitted this run, not the next
        return None
    prior = prior_matching_search(session, q)
    if prior is not None:
        # Only claim the results are in a FILE when cria itself wrote one. gate_search runs before the
        # routing split, so a harness-native search reaches here too — and it never spills. Naming the
        # derived path unconditionally sent the model to grep a file that was never created.
        domain0 = first_domain_in(query)
        steer0 = _guard_msg("domain_steer", domain=domain0) if domain0 else ""
        if prior.strip().lower() not in _SEARCH_SPILLED.get(session, ()):
            return _guard_msg("search_repeat_inline", query=query, prior=prior, domain_steer=steer0)
        # Name WHERE the earlier results actually are. The refusal used to say "its results are still
        # above — use them", which is false: cria spills search results to a file and tells the model in
        # the same breath that they are NOT inlined. So the coder was sent to look above at nothing and,
        # finding nothing, searched again. Observed live (run 0726-135324): 8 refusals in one run, each
        # pointing at content that was never there, while the coder never opened the file that held it.
        domain = first_domain_in(query)
        steer = _guard_msg("domain_steer", domain=domain) if domain else ""
        # The path cria WROTE for that query, not a name derived from it a second time.
        return _guard_msg("search_repeat", query=query, prior=prior,
                          target=spilled_path(session, prior), domain_steer=steer)
    return None


# --- the entry point (web_fetch.rs::fetch_nav) ---------------------------------------------

def fetch_nav(url: str, *, find: Optional[str] = None, cursor: Optional[str] = None,
              cap_tokens: int = CONTENT_CAP_TOKENS, user_agent: Optional[str] = None,
              session: Optional[str] = None, raw: bool = False,
              workspace_root: Optional[str] = None) -> str:
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
    # A SPILLED doc is durable, so visibility is the wrong gate for it. The rule below refuses only
    # while the earlier result is still in the conversation — right for an ordinary fetch, since a
    # compacted-away result is genuinely gone. But when the doc was too big to inline, cria wrote it
    # to a FILE and told the model so ("saved it IN FULL to … do NOT re-fetch the whole url"). That
    # file survives the compaction. Measured (run 0727-104845): the coder fetched a 154KB docs page,
    # the harness compacted the result away, the guard fell silent, and it re-fetched the same url
    # NINETEEN times. Only a whole-doc re-fetch is refused — a `find=` is navigation into the doc and
    # is answered normally, which is the whole point of having spilled it.
    if session and external and not find and not cursor and already_spilled(session, url, workspace_root):
        # The refusal CARRIES the outline (:func:`outline_for_url`). Refusing a re-fetch while cria is
        # itself holding the parsed document, and answering with nothing but a filename, is what made
        # step 1 unclosable in run 0802-184308 — 981 of 2,074 refusal-carrying calls across the corpus
        # had no outline in the prompt at all.
        return _guard_msg("fetch_repeat_spilled", url=url, target=_spill_name(url),
                          extent=spill_extent_of(url), outline=outline_for_url(url))
    # Refuse ONLY while the identical result is still in the conversation (set_visible); once
    # compaction elides it the model may legitimately re-read it — the footgun fix.
    if session and external and seen_key in _FETCH_SEEN.get(session, ()):
        # Status- and spill-aware. The refusal used to assert "this is the SAME result you got before,
        # still above; use it" for EVERY repeat — computed from the model's own tool calls, never from
        # what came back. So a URL that 404'd was refused with "use it", and an oversized doc that cria
        # had spilled to a FILE was described as sitting above. Both facts are already in the cache.
        cached = _DOC_CACHE.get(url)
        if cached is not None:
            c_status, _ct, c_reduced, _parsed, _trunc = cached
            if not (isinstance(c_status, int) and 200 <= c_status < 300):
                return _guard_msg("fetch_repeat_failed", url=url, status=status_label(c_status))
            if len(c_reduced) > OVERSIZE_CHARS and already_spilled(session, url, workspace_root):
                # THE FILE HAS TO BE THERE. This wording says "and that file is still there", and
                # this return site — unlike its twin thirty lines up — asserted it from the DOC
                # CACHE alone. `already_spilled`'s own docstring records what that costs: "the spill
                # exec was refused, and for twenty-six turns cria told the model 'that file is still
                # there' in one paragraph while its own read guard answered 'is not there — nothing
                # was read' in the next." The check is the same one, at the site that did not have
                # it (#23). Without the file, the honest answer is the plain repeat refusal below,
                # which claims nothing about a spill.
                return _guard_msg("fetch_repeat_spilled", url=url, target=_spill_name(url),
                                  extent=spill_extent_of(url), outline=outline_for_url(url))
        return _guard_msg("fetch_repeat", url=url)
    out, status, discovered = _fetch_and_render(url, find, cursor, cap_tokens, user_agent, raw,
                                               ours=was_substituted(session, url))
    if session and external and status is not None:
        # A PROTOCOL endpoint answers a GET with 405/400 by design, and cria just came back with its
        # full callable surface. Counting that as another failed URL guess would push the model over
        # the streak and append "you keep guessing URLs, stop" underneath the answer it asked for —
        # cria contradicting itself in one message. The probe succeeded: score it as a success.
        out += guess_hint(200 if discovered else status, _note_streak(session, 200 if discovered else status))
    return out


def _render_discovery(url: str, status: int, ct: Optional[str], found) -> str:
    """A probed protocol endpoint, rendered through the SAME markers a fetched spec uses.

    That is deliberate and load-bearing: loop's durable fetch ledger rebuilds session facts by parsing
    these markers out of rendered tool results, so a bespoke marker here would produce a fact that
    vanishes at the first compaction — exactly the half-built mechanism this file exists to avoid."""
    if found.unread:
        # A BOUND CRIA HIT IS NOT A SURFACE THE ENDPOINT DOES NOT HAVE. Rendering the routes marker
        # here would file "routes(0)" into the durable fetch ledger — a false fact that outlives the
        # turn — so the disclosure goes out on its own and no route claim is made.
        return (f"{status_label(status)} · {url}\nContent-Type: {ct or '(none)'}\n{found.unread}")
    head = (f"{status_label(status)} · {url}\nContent-Type: {ct or '(none)'}\n"
            f"{found.note}\n"
            # INLINE on the marker line, like a spec's routes: loop._extract_fetches reads the
            # routes from INSIDE the brackets, so entries on following lines rendered perfectly and
            # were captured as the header phrase — a fact that looks delivered and is gone by the
            # first compaction. Separated by "; " because an entry carries its own commas.
            f"{ROUTES_MARKER}{len(found.routes)}): {'; '.join(found.routes)}]\n")
    if found.shapes:
        head += _shape_block(found.shapes)
    return head


def _fetch_and_render(url, find, cursor, cap_tokens, user_agent,
                      raw=False, ours: bool = False) -> tuple[str, Optional[int], bool]:
    """Fetch (or serve from cache) → reduce → render to the model-facing text. Returns
    ``(text, status, discovered)``; ``status`` is None on a transport error (no HTTP response) and
    ``discovered`` is True when the text came from a protocol probe rather than the document. ``raw``
    fetches always re-fetch (never navigate) so a stale reduced-cache entry is never served as source."""
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
            return str(e), None, False
        except (urllib.error.URLError, OSError) as e:
            return f"web_fetch error fetching {url}: {e}", None, False
        reduced, parsed = reduce_for_cache(r.body, r.content_type, url, raw)
        status, ct, truncated = r.status, r.content_type, r.truncated
        _cache_put(url, status, ct, reduced, parsed, truncated)

    # An MCP or GraphQL endpoint has no document to read — a GET of it answers 405, or 400, or a
    # playground shell. Ask it what it offers instead of handing the model a dead end (api.handle.me
    # advertises an MCP endpoint; it sat in cria's route list and taught the model nothing). Probed
    # only for a URL the model itself asked for, only when it answers like one of those protocols, and
    # only with the two fixed read-only payloads in cria.apidiscovery.
    # The probe used to be gated on `not find and not cursor` — switched OFF exactly when the model
    # is digging hardest at an endpoint. Measured on ada-handles_mellum2_codex_poff_1785626379: every
    # /mcp fetch from call 19 to 34 carried find= or raw=, so the JSON-RPC contract ("method
    # tools/call, params {name, arguments}") that the run needed was never probed. It finally
    # surfaced at call 209, sixteen calls before the kill, from a plain fetch. `raw` still opts out —
    # that is the model explicitly asking for untouched bytes.
    # `raw` no longer opts out. It means "give me the untouched bytes", which is a request about the
    # BODY cria returns — it was never a request to learn nothing about the API. mellum2 1785996352
    # fetched the spec with find="paths" AND raw=true, the one combination that disabled both the
    # route outline above and this probe, and cria then reported the document defines nothing.
    # Discovery only REPLACES the body when it finds a real protocol contract; on a plain document it
    # returns nothing and the raw bytes fall through exactly as before.
    found = apidiscovery.discover(url, status, reduced, ct)
    if found:
        return _render_discovery(url, status, ct, found), status, True
    if not reduced.strip():
        return (f"{status_label(status)} · {url}\nContent-Type: {ct or '(none)'}\n"
                "The response body was EMPTY. Retrying this exact URL returns the same empty "
                "result — try a different source or path."), status, False
    # A `find` NARROWS. When the whole document already fits, there is nothing to narrow — narrowing
    # can then only DELETE. Walked on ada-handles_mellum2_codex_poff_1785714194 call 0019: the coder
    # fetched /handles/goose with find="resolved_addresses"; the document is 1,546 characters against
    # a 16,000-character budget, and cria returned 139 of them. What it dropped was
    # `holder: stake1u85prp8…` — the exact argument that makes /holders/ return total_handles: 15.
    # That value appears in ZERO of the run's 34 prompts. The same narrowing replaced a 404's
    # 89-character body, `{"error":"holder_not_found","message":"Holder not found",…}`, with
    # "no match. Available top-level keys: error, message, docs" — while cria told the model
    # elsewhere "you have no content from them". It had the content and threw it away. (That second
    # claim is gone from every model-facing prompt as of 2026-08-08 — a 404 body is often the
    # diagnosis, and api.handle.me's names the wrong route outright. See
    # tests/test_failed_fetch_has_no_content_claim.py, which keeps it gone.)
    #
    # Principle 5: cria never truncates what the model reads. A find on a document that fits was
    # truncation wearing a search's clothes.
    # (`truncated` = the TRANSPORT cut the body at the fetch limit. Then the document does not fit by
    # definition, and a find-miss must still disclose that content exists beyond the cut.)
    if find and (truncated or est_tokens(reduced) > cap_tokens):
        slice_ = find_in(reduced, parsed, find, cap_tokens)
        # A broad find (e.g. `paths` on a whole spec) can match a subtree far bigger than one page —
        # window it and tell the model to narrow, so a "filtered" fetch never dumps an unusable wall.
        if len(slice_) > OVERSIZE_CHARS:
            # Window it UNDER the inline bound with room for the find-header line and the
            # find_large guard appended below — the un-reserved page was exactly the slice the
            # harness middle-cut in 84 prompts of run 1785893473 (see INLINE_RESULT_MAX_BYTES).
            # Reserve for the find-header, the find_large guard AND the route outline appended
            # below — the outline is the half this branch used to drop, and it must not push the
            # result back over the bound the harness middle-cuts at.
            reserve = 800 + len(outline_for_url(url))   # upper bound; the grep line is dropped below
            body, nxt, total = page_from(slice_, 0, max(50, (INLINE_RESULT_MAX_BYTES - reserve) // 4))
            # The message tells the model to "grep the saved ./tmp file". On this branch nothing was
            # ever saved — the spill lives on the no-find path — so cria was naming a file that did
            # not exist (principle 5b). Worse, the same branch skipped the route outline the plain
            # fetch emits: on ada-handles_mellum2_codex_poff_1785626379 a find="paths" against a
            # 186,444-char OpenAPI spec returned 2 of 33 endpoints — "/" and "/mcp" — and the model
            # built a JSON-RPC client because those were the only routes it had ever been shown. The
            # real GET /handles/{handle} did not reach it until call 152 of 225.
            spill = oversized_spill(url)
            target = spill[1] if spill else "the saved ./tmp file"
            slice_ = body + _guard_msg("find_large", find=find, chars=f"{total:,}", target=target)
        # A find MISS on a truncated doc is the Ada-handle lie: the target may lie beyond the cut,
        # not be absent. Disclose so a miss isn't mistaken for "doesn't exist" (final-page parity).
        if truncated and ": no match" in slice_:
            slice_ += (f"\n\n⚠ This document exceeded the {_BODY_CAP_LABEL} fetch limit and was cut; "
                       "the term you searched may lie in the un-fetched remainder. Fetch a more "
                       "specific URL/path or an alternate source.")
        # THE ROUTE OUTLINE RIDES ALONG. Without it this branch returns a sub-section carrying no
        # `[API endpoints (N): …]` marker — and `loop._extract_fetches` harvests routes ONLY from
        # that marker, so the fetch ledger then tells the model, in EVERY later prompt, "no endpoint
        # definitions were found in it … nothing read so far DEFINES the API's routes". Walked on
        # mellum2 1785996352: a `find="paths"` fetch of the OpenAPI spec produced exactly that
        # sentence for the whole run, with the route table twenty lines above it, and the model built
        # its entire deliverable against the MCP JSON-RPC tool names because /mcp was the one route
        # it had ever been shown a full contract for. The comment above this block already records
        # the same failure on 1785626379; the spill-name half was fixed then and this half was not.
        # cria has the parsed document in hand, so the outline costs nothing to say.
        # The ROUTE/SHAPE blocks only — never the `[grep <file>]` pointer. On this branch nothing was
        # spilled (the write is gated on find is None and cursor is None), so naming that file would
        # be the very 5b violation the 08-01 fix was written for. The route list is true either way.
        outline = "\n".join(ln for ln in outline_for_url(url).splitlines()
                            if not ln.lstrip().startswith("[grep ")).strip()
        head = (f"{status_label(status)} · {url}\nContent-Type: {ct or '(none)'}\n"
                f'find="{find.strip()}"\n\n---\n{slice_}')
        # Only when it FITS. A pathological outline (hundreds of routes) must not push this past the
        # inline bound — that is the wall the harness middle-cuts, and the slice is the payload.
        if outline and len((head + "\n\n" + outline).encode()) <= INLINE_RESULT_MAX_BYTES:
            head += "\n\n" + outline
        return head, status, False
    offset = _parse_cursor(cursor) if cursor else 0
    return render_page(url, status, ct, reduced, parsed, offset, cap_tokens, truncated,
                       ours=ours), status, False


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


# A 4xx says the request was WRONG, and a model reads a status line as a fact about the world rather
# than a fact about what it typed. Walked on rust-toml-cli x ternary-bonsai (2026-08-19): the coder
# asked for `docs.rs/toml/v0.8.23/...` — the version segment carries no `v` — got 400, and what it was
# shown underneath was 830 characters of the docs.rs NAV MENU flattened into prose, framed as
# `(chars 0-830 of 830)` like a document worth reading. It never retried, never searched, and spent
# the next twenty calls guessing TOML table syntax from memory and getting it wrong three times.
#
# The body stays exactly as rendered — an error page sometimes carries the one line that says how the
# URL should be formed (docs.rs's own answer, "Shorthand URLs", was in that menu). What is added is
# one line saying WHOSE fault it is and what to do instead. 5xx is deliberately excluded: the server
# failing is not the model's to fix, and telling it to correct the URL would be a false lead.
# Urls cria itself put in the coder's mouth — see `substituted()` below.
_SUBSTITUTED: dict[str, set] = {}


def note_substituted(session: Optional[str], url: str) -> None:
    """Record that CRIA chose this url, not the coder. The coder asked to SEARCH; cria replaced that
    call with a fetch of a url a reasoner recommended."""
    if session and (url or "").strip():
        _SUBSTITUTED.setdefault(session, set()).add(url.strip())
        _bound(_SUBSTITUTED)


def was_substituted(session: Optional[str], url: str) -> bool:
    return (url or "").strip() in (_SUBSTITUTED.get(session) or ())


# The 4xx codes that are the server DECLINING rather than the address being wrong: credentials
# wanted, permission withheld, a proxy in the way, a rate limit, a legal block. On these the page may
# well exist and be exactly right. Everything else in 4xx — a malformed request, a path that is not
# there, a method the route does not take — is the coder's URL to correct, and keeps the original
# wording.
_REFUSAL_STATUSES = (401, 403, 407, 429, 451)


def client_error_note(status: int, body: str, ours: bool = False) -> str:
    """The line appended under a 4xx result — "" for anything else.

    THREE wordings, not two. The original said "the URL, the path, or the version segment in it was
    wrong, not the service" for every 4xx. That is true of a 400 or a 404 — a malformed request, or
    nothing at that path — and false of a refusal: a 401 wants credentials, a 429 wants a wait, and a
    403 is very often a bot wall in front of a page that exists. Walked on the sub-40 pass, feed-pipeline-java x nemotron-elastic — a 403 carrying
    Cloudflare's "Enable JavaScript and cookies to continue" was reported to the coder as a wrong
    address, over the one page holding the class list the run was failing to guess.

    Two wordings, because "read the server's text" is a footgun when there is no text: it sends the
    model back to re-read a page that says nothing (#5b — never point at content cria knows is not
    there). The split is on what actually came back, not on the status.

    ``ours`` — CRIA CHOSE THIS URL, so the coder is not told the mistake is its own. The default text
    says "the failure is on your side (the URL, the path… was wrong)". Walked on shipping-rates-rb x
    nemotron-elastic 1787344941: the coder ran a web_search, cria substituted a fetch of
    `rubygems.org/gems/eu-membership` — a package that does not exist, invented by cria's own
    reasoner — the transcript showed the fetch as the coder's own action, and this sentence then told
    it the 404 was its fault. Twice in one run. Blaming the coder for a request cria authored is a
    false fact in cria's own voice (#5b), and the coder cannot act on it: it never typed that url."""
    code = int(status or 0)
    if not (400 <= code < 500):
        return ""
    lines = prompts.load_map("fetch_client_error")
    if ours:
        return "\n\n" + lines["ours"]
    has_body = bool((body or "").strip())
    if code in _REFUSAL_STATUSES:
        key = "refused" if has_body else "refused_no_body"
        return "\n\n" + prompts.fill(lines[key], status=str(code))
    return "\n\n" + lines["with_body" if has_body else "no_body"]


def render_page(url: str, status: int, ct: Optional[str], reduced: str, parsed: Optional[Any],
                offset: int, cap_tokens: int, truncated: bool = False, ours: bool = False) -> str:
    body, nxt, total = page_from(reduced, offset, cap_tokens)

    def _head(nxt_: int, total_: int) -> str:
        head = f"{status_label(status)} · {url}\nContent-Type: {ct or '(none)'}\n"
        # A CATALOGUE names where other documents live, and is short enough to fit one page — so it is
        # surfaced regardless of size, unlike the spec blocks below (which exist to navigate a doc too
        # big to read). Without this its hrefs reached the model only as raw JSON body text.
        if offset == 0 and parsed is not None:
            catalog = _catalog_links(parsed)
            if catalog:
                # Relation-agnostic wording: the live api.handle.me catalogue files its openapi.json
                # under `service-doc`, not `service-desc`, so naming one relation sent the model
                # looking for a link that wasn't there.
                head += (f"{CATALOG_MARKER}{len(catalog)}): where each API's spec and docs live — fetch one "
                         "of these urls]\n" + "\n".join(f"  {c}" for c in catalog) + "\n")
        # For a large structured doc, lead with the shape so the model can `find=` a key instead
        # of blindly paging a minified blob (the "summarize with top-level keys" ask).
        if offset == 0 and parsed is not None and nxt_ < total_:
            keys = top_level_keys(parsed)
            if keys:
                head += (f"[structured doc — top-level keys: {', '.join(keys)}]\n"
                         f'[use find="<key>" to jump to a section]\n')
            # For an API spec, surface the actual ENDPOINT ROUTES up front — the single most useful
            # thing and the one a model reaching for "the endpoint" keeps missing (it drills into
            # component schemas and guesses the URL instead). Detected by SHAPE (a top-level object
            # whose keys are mostly `/`-paths), so it works for OpenAPI and any spec dialect.
            routes = _endpoint_routes(parsed)
            if routes:  # uncapped, like top_level_keys — the route the model needs may be #61
                head += f"{ROUTES_MARKER}{len(routes)}): {', '.join(routes)}]\n"
                shapes = _endpoint_response_fields(parsed)
                head += _shape_block(shapes)  # the response FIELDS (dereferenced), real names
                head += '[web_fetch find="<path>" for one endpoint\'s full request/response detail]\n'
        return head

    # THE WHOLE RENDERED RESULT must fit the inline bound, not just the body window: the head
    # (routes/shapes outline) is data too, and head + body above INLINE_RESULT_MAX_BYTES is exactly
    # what the harness middle-cuts out of every later prompt (see content_reduce). Shrink the BODY
    # window until the sum fits — content is never dropped, the page boundary just moves earlier
    # and the "More remains" cursor picks it up. Two passes suffice (the head has two states:
    # with and without the paged-doc outline), plus one for the trailer reserve.
    _TRAILER_RESERVE = 300  # the "--- (chars …) ---" line and the ⚠ More-remains / fetch-cut trailer
    head = _head(nxt, total)
    # page_from budgets in CHARS (tokens×4); the bound is BYTES, so multibyte content can need a
    # second shrink — the divisor walk terminates instead of stalling on a same-size re-page.
    for divisor in (4, 6, 8, 12, 16):
        room = INLINE_RESULT_MAX_BYTES - len(head.encode()) - _TRAILER_RESERVE
        if len(body.encode()) <= room:
            break
        body, nxt, total = page_from(reduced, offset, max(50, room // divisor))
        head = _head(nxt, total)
    out = f"{head}--- (chars {offset}–{nxt} of {total}) ---\n{body}\n"
    out += client_error_note(status, body, ours=ours)
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

# A model asking for several things at once writes them the way every grep-shaped tool accepts:
# `a|b`, `a, b`, `a OR b`. Matched as ONE literal string those answer "no match" about a document
# that contains every term — a wrong FACT about ground truth, which a weak model cannot tell apart
# from a weak answer. MEASURED (run 0727-124354): `holder_address|total_handles` against a 96 KB
# swagger holding both, answered no match; the coder then permuted the phrasing ~10 times and spent
# 98 calls on one step without writing a file.
_FIND_ALTERNATION = re.compile(r"\s*(?:\||,|\bOR\b)\s*")
# cria's OWN response-shape ledger renders endpoints as `GET /handles/{handle} → f1, f2`, so the
# model learns that spelling from cria and then meets a find= that rejects it: a spec names the PATH,
# with the method as a key inside it.
_HTTP_VERB = re.compile(r"^(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(?=/)", re.I)


def _find_terms(query: str) -> list[str]:
    """The separate things this query asks for. One term unless the query really is a list — a
    separator inside a single real key (``weird|key``) leaves it whole, because the split only
    applies when every resulting part is non-empty."""
    parts = [p.strip() for p in _FIND_ALTERNATION.split(query) if p.strip()]
    return parts if len(parts) > 1 else [query]


def _find_hits(reduced: str, parsed: Optional[Any], term: str) -> bool:
    """Does this term appear at all? Asked the same way the finders ask it, so it can never disagree
    with them (never inferred from their rendered text)."""
    if parsed is not None:
        matches: list = []
        _collect_json_matches(parsed, term.lower(), [], matches)
        return bool(matches)
    return term.lower() in (reduced or "").lower()


def find_in(reduced: str, parsed: Optional[Any], query: str, cap_tokens: int) -> str:
    """MIME-aware targeted retrieval: a JSON/YAML subtree + ancestor spine + one-hop ``$ref``,
    else a text section. Strips surrounding quotes the model adds for emphasis (the Rust cure
    for the 'a model looped a dozen fetches re-quoting terms' bug).

    A query that MATCHES is answered exactly as asked — splitting must never change the answer to a
    question that already had one, and `,` is a separator in `a, b` but ordinary punctuation in
    `Hello, world`. Only a MISS is re-read: first as a list of terms, then with a leading HTTP verb
    stripped. Both re-reads are answered from ground truth (the same lookup the finders do) and both
    say what was actually searched."""
    q = (query or "").strip().strip("\"'`").strip()
    if _find_hits(reduced, parsed, q):
        return _find_one(reduced, parsed, q, cap_tokens)
    terms = _find_terms(q)
    if len(terms) > 1:
        found = [t for t in terms if _find_hits(reduced, parsed, t)]
        if found:
            per = max(200, cap_tokens // len(found))
            body = "\n\n".join(f'# find "{t}"\n{_find_one(reduced, parsed, t, per)}' for t in found)
            missing = [t for t in terms if t not in found]
            if missing:
                body += f'\n\n[no match in this document for: {", ".join(missing)}]'
            return body
        return (f'find "{q}": no match for any of: {", ".join(terms)} (each was searched separately).\n'
                + _find_one(reduced, parsed, terms[0], cap_tokens))
    bare = _HTTP_VERB.sub("", q)
    if bare != q and _find_hits(reduced, parsed, bare):
        return (f'[find "{q}" — searched for "{bare}": a spec names the path, with the method as a '
                f'key inside it]\n\n' + _find_one(reduced, parsed, bare, cap_tokens))
    return _find_one(reduced, parsed, q, cap_tokens)


def _find_one(reduced: str, parsed: Optional[Any], term: str, cap_tokens: int) -> str:
    if parsed is not None:
        return find_json(parsed, term, cap_tokens)
    return find_text(reduced, term, cap_tokens)


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
    surfaces for any dialect. Empty when the doc isn't route-shaped (so nothing is invented).

    Prefixed with the spec's declared base path (:func:`_base_path`) so the list is the route the coder
    must actually CALL. A spec's ``paths`` keys are relative to ``basePath``/``servers[0].url``, and
    listing them bare said ``/handles/{handle}`` where the real route was ``/v2/handles/{handle}``."""
    if not isinstance(parsed, dict):
        return []
    base = _base_path(parsed)
    for v in parsed.values():
        if isinstance(v, dict) and len(v) >= 2:
            ks = [str(k) for k in v.keys()]
            slashed = [k for k in ks if k.startswith("/")]
            if len(slashed) >= max(2, int(len(ks) * 0.6)):  # mostly route-like → these are endpoints
                return [base + k for k in slashed]
    return []


# Link relations in an api-catalog that point at something worth FETCHING NEXT. `service-desc` is the
# machine-readable description (an OpenAPI document); `service-doc` is the human one; `service-meta` and
# `status` carry metadata. Anything else in the linkset is left alone rather than guessed at.
_CATALOG_RELS = ("service-desc", "service-doc", "service-meta", "status")


def _catalog_links(parsed: Any, max_entries: int = 20) -> list[str]:
    """``<anchor> → service-desc: <url>; service-doc: <url>`` per API in an RFC 9727 api-catalog
    (carried as an RFC 9264 JSON linkset). Empty for any other doc, so nothing is invented.

    A catalogue's entire value is its hrefs: it exists to say "the OpenAPI document for this API lives
    HERE". Rendered as a structured doc it produced ``top-level keys: linkset`` — one word — and the
    model went back to guessing spec URLs. Shape-detected (a ``linkset`` array of objects carrying link
    relations), so it works whether or not the server sent the ``application/linkset+json`` type."""
    if not isinstance(parsed, dict):
        return []
    linkset = parsed.get("linkset")
    if not isinstance(linkset, list):
        return []
    out: list[str] = []
    for entry in linkset:
        if not isinstance(entry, dict):
            continue
        if len(out) >= max_entries:
            # DISCLOSE the cap, as every other list here does: a silent cut reads as "these are all
            # the APIs in this catalogue".
            out.append(f"…+{len(linkset) - max_entries} more catalogued API(s) not shown")
            break
        anchor = str(entry.get("anchor") or "").strip()
        parts: list[str] = []
        for rel in _CATALOG_RELS:
            links = entry.get(rel)
            if not isinstance(links, list):
                continue
            hrefs = [str(l.get("href")).strip() for l in links
                     if isinstance(l, dict) and str(l.get("href") or "").strip()]
            if hrefs:
                parts.append(f"{rel}: {', '.join(hrefs)}")
        if anchor and parts:
            out.append(f"{anchor} → {'; '.join(parts)}")
    return out


def top_level_keys(root: Any) -> list[str]:
    # ALL keys, uncapped: this is the navigation vocabulary on a find MISS and the shape hint for a
    # structured doc — a cap would hide the very key the model needs (its target may be key #27).
    if isinstance(root, dict):
        return [str(k) for k in root.keys()]
    if isinstance(root, list):
        return ["[array]"]
    return []


_LINK_IN_TEXT = re.compile(r"\((https?://[^\s)]+)\)")


def _no_text_match(content: str, query: str, cap_tokens: int) -> str:
    """A find that matched nothing answers with WHAT IS THERE — never with the document.

    The model asked for one section; the honest answer is "that isn't here", plus the means to
    re-target. It must not become "your search for X gives you Y": handing back the body under a
    "no match" header answers a question the model did not ask, and invites a weak model to read the
    wall of text as the match. This mirrors the JSON path, which has always answered a miss with
    ``Available top-level keys: …`` and never the doc.

    The aid is whatever the doc really offers: its headings, else the links it contains (html_to_text
    keeps hrefs inline, so a page whose whole value IS its link list still yields one). Observed live
    (run 0726-133755): find="resolve" on the 705-char api.handle.me index returned four words, and the
    coder — never told the page listed /openapi.json — went on to guess URLs. It now gets those links
    by name, which is more use than the markup ever was."""
    notice = f'find "{query}": no match.'
    heads = [ln.strip() for ln in content.splitlines() if ln.lstrip().startswith("#")]
    if heads:
        return f"{notice} Sections:\n" + "\n".join(heads)
    links = list(dict.fromkeys(_LINK_IN_TEXT.findall(content)))
    if links:
        return f"{notice} Links on this page:\n" + "\n".join(links)
    return (f"{notice} Re-run find with a different term, or fetch this url without find= "
            "to read it page by page.")


def find_text(content: str, query: str, cap_tokens: int) -> str:
    q = query.lower()
    lc = content.lower()
    # EVERY WHOLE MATCH THAT FITS, not a fixed best-three. `FIND_TOP_K = 3` decided how many windows
    # a reader got regardless of how much room it had, and the residual line said "narrow your find"
    # about matches the caller's own budget could have carried — one measured result disclosed 1,700
    # of them. The budget is the bound now, each window is a whole paragraph, and the residual names
    # the saved copy so the rest are one grep away rather than gone (#5: no arbitrary cap; where a
    # bound is real, refuse and route).
    per = max(256, cap_tokens * 4)
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
    budget = cap_tokens * 4
    shown, spent = [], 0
    for r in results:
        if shown and spent + len(r) > budget:
            break                       # whole windows only — never half a paragraph
        shown.append(r)
        spent += len(r)
    body = "\n\n---\n\n".join(shown)
    if len(results) > len(shown):
        body += "\n\n" + prompts.fill(prompts.load("find_more_matches"),
                                       rest=str(len(results) - len(shown)),
                                       shown=str(len(shown)), total=str(len(results)))
    return body


def _extract_around(content: str, at: int, budget: int) -> str:
    """The whole paragraph the match sits in.

    ``budget`` used to re-cut that paragraph around the hit when it was large, with no marker at
    all — so a match inside a long block came back as a mid-sentence slice the reader could not tell
    from the block itself. The paragraph break is the author's own boundary and is the only bound
    here now; the CALLER decides how many whole paragraphs it can afford."""
    p = content.rfind("\n\n", 0, at)
    lo = p + 2 if p != -1 else 0
    p2 = content.find("\n\n", at)
    hi = p2 if p2 != -1 else len(content)
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
