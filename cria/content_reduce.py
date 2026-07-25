"""MIME-aware, lossless-first reduction of a single oversized tool output.

Port of codex-local's `content_reduce.rs` (authoritative design:
`docs/spec/content-reduce.md`). Bounds ONE oversized tool result — a giant `web_fetch`
page or file read — so a single output can't blow the local model's context window in one
turn. Deterministic, stdlib-only, no LLM.

Escalation (per the spec): lossless transforms first (HTML->text, JSON minify); the lossy
guarded prose-stripper only runs when a tier left the output over the cap.

**Stateless by design.** The Rust version's pagination / `find` navigation (`page_from`,
`find_in`) is intentionally NOT ported: it needs a per-URL document cache a stateless proxy
does not own. cria bounds the output here; the harness re-issues the tool call to see more.
"""
from __future__ import annotations

import json
from html.parser import HTMLParser
from urllib.parse import urljoin


def est_tokens(s: str) -> int:
    """chars/4 token estimate (the same crude estimate the trimmer uses)."""
    return len(s) // 4


def content_reduce(content: str, content_type: str | None, cap_tokens: int) -> str:
    """Reduce `content` toward roughly `cap_tokens`, dispatching on `content_type`.
    Returns the input unchanged when it already fits."""
    if est_tokens(content) <= cap_tokens:
        return content
    ct = (content_type or "").lower()
    if "html" in ct or "xml" in ct:
        text = html_to_text(content)
        return strip_prose_text(text) if est_tokens(text) > cap_tokens else text
    if "json" in ct:
        reduced = reduce_json(content, cap_tokens)
        return reduced if reduced is not None else content
    # text/*, yaml, unknown -> guarded prose strip (only ran because over cap). Gate it: the
    # stripper removes bare keywords (for/in/is/as/from/with), so running it on SOURCE CODE — which
    # sniffs as "unknown" too — silently corrupts the file the model is about to edit. Strip only
    # when the blob reads as natural language AND does not read as code.
    if _looks_like_prose(content) and not _looks_like_code(content):
        return strip_prose_text(content)
    return content


def reduce_lossless(content: str, content_type: str | None) -> str:
    """Lossless-only reduction (HTML->text, JSON minify) — no prose stripping, no size gate."""
    ct = (content_type or "").lower()
    if "html" in ct or "xml" in ct:
        return html_to_text(content)
    if "json" in ct:
        try:
            return json.dumps(json.loads(content), separators=(",", ":"), ensure_ascii=False)
        except (ValueError, TypeError):
            return content
    return content


# ---------------------------------------------------------------------------
# JSON tier: parse -> minify (lossless) -> strip prose nodes (lossy) -> re-serialize
# ---------------------------------------------------------------------------

def reduce_json(content: str, cap_tokens: int) -> str | None:
    try:
        v = json.loads(content)
    except (ValueError, TypeError):
        return None
    minified = _dump_json(v)
    if minified is None:
        return None
    if est_tokens(minified) <= cap_tokens:
        return minified  # lossless was enough
    v = _strip_prose_nodes(v, None)
    return _dump_json(v)


def _dump_json(v) -> str | None:
    try:
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    except (ValueError, TypeError):
        return None


def _strip_prose_nodes(v, key: str | None):
    """Walk the tree; compress only string values that are (Signal 1) under a prose-named key
    AND (Signal 2) sniff as natural language. Rebuilding the value (not mutating strings in
    place) means structure cannot break. Array elements inherit the parent key, like the Rust."""
    if isinstance(v, dict):
        return {k: _strip_prose_nodes(val, k) for k, val in v.items()}
    if isinstance(v, list):
        return [_strip_prose_nodes(val, key) for val in v]
    if isinstance(v, str):
        if key is not None and _is_prose_field(key) and _looks_like_prose(v):
            return strip_prose_text(v)
        return v
    return v


# ---------------------------------------------------------------------------
# HTML tier: strip script/style/template/noscript + comments + tags, decode entities, ws
# ---------------------------------------------------------------------------

def _clean_href(href: str | None, base: str | None) -> str:
    """A followable link target, or "" to drop. Resolves relative hrefs against `base`
    (the page URL) so the model gets a directly-fetchable absolute URL, not a bare `/path`
    it has to guess the host for. Drops in-page fragments and non-navigational schemes."""
    if not href:
        return ""
    h = href.strip()
    if not h or h[0] == "#":
        return ""
    if h.lower().startswith(("javascript:", "data:", "vbscript:")):
        return ""
    if base:
        try:
            h = urljoin(base, h)  # already-absolute h passes through unchanged
        except ValueError:
            pass
    return h


class _HTMLTextExtractor(HTMLParser):
    _SKIP = {"script", "style", "template", "noscript"}

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(convert_charrefs=True)  # entities decoded into data automatically
        self._parts: list[str] = []
        self._skip = 0  # depth of open skip-tags; data suppressed while > 0
        self._base = base_url
        self._hrefs: list[str] = []  # open-<a> href stack (balanced with </a>)

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        if tag == "a":
            self._hrefs.append(_clean_href(dict(attrs).get("href"), self._base))
        self._parts.append(" ")  # tag boundary -> a space so words don't fuse

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip > 0:
            self._skip -= 1
        if tag == "a" and self._hrefs:
            href = self._hrefs.pop()
            if href and self._skip == 0:
                self._parts.append(f" ({href})")  # keep the link's target with its text
        self._parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        self._parts.append(" ")

    def handle_data(self, data):
        if self._skip == 0:
            self._parts.append(data)

    def handle_comment(self, data):
        pass  # drop comments

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str, base_url: str | None = None) -> str:
    p = _HTMLTextExtractor(base_url)
    p.feed(html)
    p.close()
    return _collapse_ws(p.text())


def _collapse_ws(s: str) -> str:
    """Collapse whitespace runs, preserving paragraph breaks: a run containing a newline
    becomes one '\\n', an inline run becomes one ' '."""
    out: list[str] = []
    blanks = 0  # 0=none, 1=space, 2=newline-run
    for c in s:
        if c in "\n\r":
            blanks = max(blanks, 2)
        elif c.isspace():
            blanks = max(blanks, 1)
        else:
            if blanks == 2:
                out.append("\n")
            elif blanks == 1:
                out.append(" ")
            blanks = 0
            out.append(c)
    return "".join(out).strip()


# ---------------------------------------------------------------------------
# The one guarded stripper (shared by plain text and prose JSON/YAML nodes)
# ---------------------------------------------------------------------------

def strip_prose_text(text: str) -> str:
    """Strip only certain-junk function words; preserve any token that could carry meaning
    (digit/uppercase/underscore/symbol) and every negation/logic word."""
    out: list[str] = []
    for piece in _split_keep_ws(text):
        if piece and piece.isspace():
            out.append(piece)
            continue
        lead, core, trail = _peel(piece)
        if core and _is_strippable(core):
            out.append(lead)
            out.append(trail)  # drop the word, keep attached punctuation
        else:
            out.append(piece)
    return _collapse_inline_spaces("".join(out))


def _is_strippable(tok: str) -> bool:
    """Strippable only if all-lowercase-alphabetic, a function word, and not protected.
    Anything with a digit, uppercase, `_`, or punctuation fails isalpha/islower and is kept."""
    if not (tok.isalpha() and tok.islower()):
        return False
    return not _is_protected(tok) and _is_function_word(tok)


def _split_keep_ws(s: str) -> list[str]:
    """Split into alternating whitespace / non-whitespace runs, preserving every character."""
    out: list[str] = []
    start = 0
    in_ws: bool | None = None
    for idx, c in enumerate(s):
        ws = c.isspace()
        if in_ws is None:
            in_ws = ws
        elif in_ws != ws:
            out.append(s[start:idx])
            start = idx
            in_ws = ws
    if start < len(s):
        out.append(s[start:])
    return out


def _peel(tok: str) -> tuple[str, str, str]:
    """Split a token into (leading punctuation, core, trailing punctuation)."""
    lead_end = len(tok)
    for i, c in enumerate(tok):
        if c.isalnum():
            lead_end = i
            break
    trail_start = lead_end
    for i in range(len(tok) - 1, -1, -1):
        if tok[i].isalnum():
            trail_start = i + 1
            break
    return tok[:lead_end], tok[lead_end:trail_start], tok[trail_start:]


def _collapse_inline_spaces(s: str) -> str:
    out: list[str] = []
    pending_space = False
    for c in s:
        if c in " \t":
            pending_space = True
        else:
            if pending_space and out and out[-1] != "\n":
                # drop a space that sits right before punctuation a stripped word left
                if c not in ",.;:)]":
                    out.append(" ")
            pending_space = False
            out.append(c)
    return "".join(out).strip()


# ---------------------------------------------------------------------------
# Word lists (mirror docs/spec/content-reduce.md)
# ---------------------------------------------------------------------------

_FUNCTION_WORDS = frozenset({
    # articles
    "a", "an", "the",
    # possessive determiners
    "its", "his", "her", "their", "our", "your", "my",
    # prepositions
    "of", "to", "in", "on", "at", "for", "with", "from", "by", "as",
    "into", "onto", "over", "under", "via",
    # auxiliaries
    "is", "are", "was", "were", "be", "been", "being", "am",
    "do", "does", "did", "has", "have", "had",
    # interjections / fillers
    "oh", "ah", "um", "uh", "well",
})

# Never stripped even though alphabetic+lowercase: negations and logic words.
_PROTECTED = frozenset({
    "not", "no", "never", "none", "neither", "nor", "cannot",
    "or", "and", "if", "when", "unless", "else", "then",
})

_PROSE_FIELDS = frozenset({
    "description", "summary", "title", "comment", "doc", "documentation",
    "details", "note", "notes", "overview", "abstract", "help", "message",
    "text", "body", "longdescription",
})

_PROSE_FIELDS_EXCLUDE = frozenset({
    "pattern", "format", "enum", "example", "default", "const", "$ref", "ref",
    "url", "uri", "href", "path", "cmd", "command", "code", "id", "name", "key",
    "type", "value", "version", "operationid",
})


def _is_function_word(w: str) -> bool:
    return w in _FUNCTION_WORDS


def _is_protected(w: str) -> bool:
    return w in _PROTECTED


def _is_prose_field(key: str) -> bool:
    k = key.lower()
    return k in _PROSE_FIELDS and k not in _PROSE_FIELDS_EXCLUDE


def _looks_like_prose(s: str) -> bool:
    """Signal 2: dominantly letters+spaces, several words, sentence-shaped. Embedded
    identifiers/numbers don't disqualify — only dominance by non-prose."""
    if len(s.split()) < 4:
        return False
    total = max(len(s), 1)
    proseish = sum(1 for c in s if c.isalpha() or c.isspace())
    return proseish * 100 // total >= 75


def _looks_like_code(s: str) -> bool:
    """Conservative code sniff for the plain-text reduction gate. `_looks_like_prose` alone is
    fooled by indented source — indentation inflates the whitespace ratio, so a block of Python
    scores >75% "prose-ish" and the stripper then eats its `for`/`in`/`is`/`as`/`from`/`with`
    keywords. Uses only STRUCTURAL signals (no per-language keyword list) so it generalizes:
    (1) a high share of lines ending in a block opener / statement terminator, or (2) a high
    density of structural symbols among the non-whitespace characters."""
    lines = [ln for ln in s.splitlines() if ln.strip()]
    if not lines:
        return False
    enders = sum(1 for ln in lines if ln.rstrip().endswith((":", "{", "}", ";")))
    if enders * 100 // len(lines) >= 40:
        return True
    non_space = [c for c in s if not c.isspace()]
    if not non_space:
        return False
    symbols = sum(1 for c in non_space if c in "{}()[]<>=;+*/\\|&%$#@`~")
    return symbols * 100 // len(non_space) >= 12
