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
import re
from html.parser import HTMLParser
from urllib.parse import urljoin


def est_tokens(s: str) -> int:
    """chars/4 token estimate (the same crude estimate the trimmer uses)."""
    return len(s) // 4


# THE ONE BOUND for any content cria composes and hands back INLINE as a tool result. An inline
# result outlives its turn: the harness re-renders it into every later prompt through its OWN
# middle-cut — codex-local ships a per-model history budget of 10,000 BYTES per tool output
# (protocol/openai_models.rs `TruncationPolicyConfig::bytes(10_000)`, applied in
# context_manager/history.rs ×1.2) — so anything cria emits above that is silently holed
# ("…N tokens truncated…") in EVERY subsequent turn, which no context floor on cria's side can see
# or repair. Measured 2026-08-04: 166 distinct harness cuts across the capture corpus; the openapi
# find slice of run 1785893473 (16,000 chars, sized by the old 4,000-token page cap) rode
# middle-cut through 84 of that run's prompts. 9,000 leaves headroom under the 10,000-byte budget
# for the harness's own framing lines (Chunk ID / Wall time / exit code / Output:). Bounding is
# done by PAGING and spill files, never by dropping content — principle 5 (never truncate) holds;
# this constant is what makes it hold on the far side of the harness too.
INLINE_RESULT_MAX_BYTES = 9000

# HOW MUCH OF A DOCUMENT ONE COMMAND CAN CARRY TO DISK. cria has no channel to the harness's
# filesystem except a command, and a command is one argv string, so a spill past this is CUT.
#
# Defined here rather than in `writeproxy` because the module that COMPOSES the spill message has to
# know it. It did not: `webfetch` said "it was saved IN FULL to <path>" while `writeproxy` appended
# "this saved copy holds the first 45,056 characters of a 186,444-character document" to the same
# tool result. Two sentences, one output, contradicting each other (#5b).
COMMAND_ARG_BUDGET = 64 * 1024
SPILL_CONTENT_MAX = (COMMAND_ARG_BUDGET - 4 * 1024) * 3 // 4


# Magic-byte signatures for the binary-content fact line — named so the note can say WHAT was
# omitted, not just that something was. Text-adjacent formats are absent on purpose.
_BINARY_KINDS = ((b"\x89PNG", "PNG image"), (b"\xff\xd8\xff", "JPEG image"), (b"GIF8", "GIF image"),
                 (b"PK\x03\x04", "ZIP archive"), (b"\x1f\x8b", "gzip data"), (b"%PDF", "PDF"),
                 (b"\x7fELF", "ELF binary"), (b"SQLite format 3", "SQLite database"))


def binary_kind(head: bytes) -> str | None:
    """The named kind for a leading magic-byte signature, or None."""
    for sig, name in _BINARY_KINDS:
        if head.startswith(sig):
            return name
    return None


# A terminal colour/cursor escape. Every build tool that detects a tty emits these, and several emit
# them even when piped: maven, cargo, npm, gradle, pytest, go test. They are DECORATION — the text is
# text — but the escape byte is 0x1b, a control character, so a naive count reads them as binary soup.
# Measured on the six-language battery: `mvn compile -q` emits 713 bytes of compiler errors whose ONLY
# control character is 0x1b, 22 of them at 3.1% density, clearing BOTH of looks_binary's thresholds.
# Every Maven error in the campaign was replaced with "binary data cannot be read as text" — 212 of
# qwen35's 275 prompts, 86 of gemma4's 112 — leaving the model to guess why its build failed, in the
# one language family that cannot proceed without knowing.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")


def strip_ansi(text: str) -> str:
    """Terminal colour and cursor escapes removed. The ONE owner: a model reads text, and an escape
    sequence carries nothing it can act on — only bytes that make the text look like a blob."""
    return _ANSI.sub("", text or "")


def looks_binary(text: str) -> bool:
    """True when decoded content is binary SOUP — replacement chars / raw control bytes — not text
    (operator ruling 07-30: blobs have no place in any model-facing prompt; a fact line replaces
    them). Deliberately strict: CJK, base64, a hexdump the model asked for, and a COLOURED BUILD LOG
    are all TEXT and never match."""
    sample = strip_ansi(text[:8192])
    bad = sum(1 for c in sample if c == "\ufffd" or (ord(c) < 32 and c not in "\t\n\r"))
    return bad >= 20 and bad / max(1, len(sample)) > 0.02


def binary_note(byte_len: int, kind: str | None) -> str:
    """The fact line that stands in for stripped binary content — true everywhere it is used."""
    k = f", {kind}" if kind else ""
    return f"[binary content: {byte_len:,} bytes{k} — not shown; binary data cannot be read as text]"


def digest_reduce(content: str, content_type: str | None, cap_tokens: int) -> str:
    """:func:`content_reduce` for text a model must READ AS INSTRUCTION, never as raw evidence.

    Identical for structured content, but for prose it returns the text UNCHANGED rather than running
    :func:`strip_prose_text`. The caller enforces the budget and discloses what would not fit — so the
    outcome is "kept whole" or "stated as not summarized", never "quietly reworded".

    An earlier version of this cut the prose to the cap and labelled the cut. The operator rejected
    that, correctly: it is a truncation, and shown a real example it was cutting mid-word
    ("...ithub.com/matiassi") out of search-result noise that should never have been in the context
    to begin with. Reaching for a size fix before removing the redundancy and the noise is treating
    the symptom. The real repairs were elsewhere — collapse identical digests (42% of one measured
    note) and spill search results the way fetches already spill. That stripper deletes function words, and its docstring's claim that
    they are "certain-junk" is wrong: `is`, `to`, `of`, `for`, `be` carry the grammatical relations
    that decide meaning. The result reads as fluent English and is not — which makes it a worse
    failure than truncation, because truncation is visible.

    Measured on run 20260801T225200 (zaya1). A compaction digest rewrote the user's own task —

        "I would like you to write a Python script that accepts an Ada Handle as input and
         resolves it to the Cardano address"
      → "I would like you write Python script that accepts Ada Handle input and resolves it
         Cardano address"

    — and cria's own planner instruction with it ("The request above **is** what the WORK **is**"
    → "The request above what WORK"). One line was not merely degraded but INVERTED: cria's note
    "no endpoints or field names could **be read from** it" became "could read it", turning a
    statement that nothing was learned into a claim that something was.

    Honest, labelled loss beats invisible corruption (principle 5: never destroy information the
    model reads; any reduction cria does make is LABELLED)."""
    if est_tokens(content) <= cap_tokens:
        return content
    ct = (content_type or "").lower()
    if "html" in ct or "xml" in ct:
        content, ct = html_to_text(content), ""
    elif "json" in ct:
        # LOSSLESS ONLY. Minification is free; the prose tier is the word-deleter this whole
        # function exists to avoid, and it was reachable from here. Verified before the fix: a JSON
        # body carrying "the request could not be read from the server because the token is not
        # valid" came back as "request could not read server because token not valid", silently, on
        # the compaction path, in text the model reads as fact.
        reduced = reduce_json(content, cap_tokens, strip_prose=False)
        if reduced is not None and est_tokens(reduced) <= cap_tokens:
            return reduced
        content = reduced if reduced is not None else content
    return content   # still over cap: KEEP IT WHOLE and let the caller disclose it


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


# ---------------------------------------------------------------------------
# JSON tier: parse -> minify (lossless) -> strip prose nodes (lossy) -> re-serialize
# ---------------------------------------------------------------------------

def reduce_json(content: str, cap_tokens: int, strip_prose: bool = True) -> str | None:
    """Minify; if that is not enough and ``strip_prose``, compress prose-named string values.

    ``strip_prose=False`` stops at the lossless tier. :func:`digest_reduce` passes it, because the
    whole reason that function exists is to keep the word-deleter away from text a model reads as
    instruction — and its JSON tier walked straight into it through this call. The fields
    `_PROSE_FIELDS` names — `message`, `text`, `body`, `details`, `note`, `description`, `summary` —
    are exactly where an API error, a test failure or a tool's own explanation lives."""
    try:
        v = json.loads(content)
    except (ValueError, TypeError):
        return None
    minified = _dump_json(v)
    if minified is None:
        return None
    if est_tokens(minified) <= cap_tokens or not strip_prose:
        return minified  # lossless was enough, or lossless is all this caller permits
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

def _is_function_word(w: str) -> bool:
    return w in _FUNCTION_WORDS


def _is_protected(w: str) -> bool:
    return w in _PROTECTED


def _is_prose_field(key: str) -> bool:
    return key.lower() in _PROSE_FIELDS


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
    if symbols * 100 // len(non_space) >= 12:
        return True
    # PER-LINE fallback: the AGGREGATE ratios above are fooled by a comment/docstring-DOMINANT source
    # file — a few code lines drowned in prose comments scores as prose, and the stripper then eats its
    # keywords (the confirmed corruption of a model-read file). A single line that structurally reads as
    # code protects the whole blob. Biased to protect: over-detecting code only skips a lossy reduction;
    # under-detecting corrupts the model's authoritative read (never-truncate).
    for ln in lines:
        t = ln.rstrip()
        if t.endswith(("{", "}", ";")):        # block terminators are ~never line-final in prose
            return True
        ns = [c for c in t if not c.isspace()]  # a symbol-dense single line, e.g. "def go(items):"
        if ns and sum(1 for c in ns if c in "{}()[]<>=;+*/\\|&%$#@`~") * 100 // len(ns) >= 12:
            return True
    return False


# THE ONLY SANCTIONED WAY TO SHORTEN MODEL-FACING TEXT. Six sites clipped a string with a bare slice
# and no marker: a runner's assertion message (which IS the diagnostic), the flagged source line
# quoted back inside backticks, two API descriptions cut mid-word, a grep match line cut at the
# column where a minified spec lives. `probeparse`'s own module comment says these were all removed —
# "summary/finding messages now flow WHOLE … (Former SUMMARY_*_LIMIT ceilings + truncate() removed as
# dead.)" — which stopped being true of that module.
#
# A shortened string a reader cannot detect is worse than a short one it can (#5).
def clip(s: str, n: int, marker: str = "…") -> str:
    """``s`` shortened to ``n`` characters, always with a visible marker when anything was cut."""
    s = s or ""
    return s if len(s) <= n else s[:max(n - len(marker), 0)] + marker
