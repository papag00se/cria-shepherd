"""Literal argument recovery and protocol-byte facts, without policy or state."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re

from . import jsontext
from .callsyntax import _LEAK_DEBRIS

_FUSED_SENTINELS = _LEAK_DEBRIS + ("<|channel>", "<channel|>")


_PATH_RE = re.compile(r'"(?:path|file_path|file|filename)"\s*:\s*"([^"\n]*)"')


_CONTENT_RE = re.compile(r'"(?:content|contents|text|body)"\s*:\s*"')


def _json_structurally_complete(s: str) -> bool:
    """True iff ``s`` is a structurally closed JSON value: every `{`/`[` balanced by its `}`/`]`
    and no string left open. Tolerant scan — a backslash escapes the next char regardless of JSON
    validity, so an invalid `\\'` (the real cut-off write) is followed correctly and only an actual
    truncation ends inside a string or at depth > 0. NOT a validator: it decides completeness, not
    well-formedness, and can't resolve a genuinely unescaped `"` in a string value (unresolvable by
    any scan — the caller refuses on that ambiguity)."""
    depth = 0
    in_str = False
    esc = False
    saw = False
    for ch in s:
        if esc:
            esc = False
            continue
        if in_str:
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
            saw = True
        elif ch in "}]":
            depth -= 1
            if depth < 0:  # a stray closer → not a well-nested value
                return False
    return saw and depth == 0 and not in_str


def _recover_write_args(raw: str) -> dict | None:
    """Last-resort recovery of a write_file-style call whose `content` value has
    raw newlines / unescaped quotes that break JSON: pull the path, then take the
    content up to the closing quote before the final `}`.

    Recovers ONLY a structurally COMPLETE call. A call whose `content` string was cut
    off mid-value (the model self-truncated its own generation — a normal `tool_calls`
    finish, not `length`, so `is_truncated` never sees it) must NOT be salvaged: the
    recovered body would be a partial file, and lowering it to disk writes a broken file
    that reports success. Refuse (→ None) when the content value isn't properly closed;
    :func:`has_incomplete_tool_args` then flags it so the loop drops the partial write."""
    pm = _PATH_RE.search(raw)
    if not pm:
        return None
    # Structural completeness, not a string heuristic: `endswith("}")` proves nothing (a `}` can
    # close a NESTED object, or be literal content, while the outer object is still open). Scan the
    # raw as JSON — string state + backslash-escapes-next-char (so an invalid `\'` is handled) +
    # brace/bracket depth. A cut-off call ends inside a string or at depth > 0. The one case this
    # can't decide is a GENUINELY unescaped `"` in content (the same ambiguity that broke json.loads);
    # there the scan may read the wrong boundary, and refusing on the safe side is the right default.
    if not _json_structurally_complete(raw):
        return None
    args: dict[str, str] = {"path": pm.group(1)}
    cm = _CONTENT_RE.search(raw)
    if cm:
        end = _content_value_end(raw, cm.end())
        if end is None:
            return None
        args["content"] = _unescape_once(raw[cm.end():end])
    return args


def _content_value_end(raw: str, start: int) -> int | None:
    """Index of the closing quote of the `content` value, or None.

    IT USED TO BE `tail.rfind('"')` — the LAST quote in the whole remainder, with a comment resting
    on the object being known-complete. Completeness says nothing about key ORDER, and models emit
    keys alphabetically, so `content` comes before `path` far more often than after it. Reproduced:

        sent      {"content":"line1\nline2","path":"x.py"}
        recovered content = 'line1\nline2","path":"x.py'

    The rest of the JSON object was written into the file. Not observed firing — the completeness
    gate above refuses first in all fourteen reachable cases in the captures — but this is the
    last-resort path for a large `write_file`, and a byte-exact write of that is a broken file that
    reports success.

    Forward scan with the same string-state rule `_json_structurally_complete` already uses: a
    backslash escapes the next character, and the value ends at the first unescaped quote."""
    i = start
    while i < len(raw):
        c = raw[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            return i
        i += 1
    return None


def _unescape_once(body: str) -> str:
    """The escapes JSON applied, undone in ONE pass so a decoded character is never re-read.

    The chained `.replace()` calls ran `\\\\` LAST, so a literal backslash followed by `n` — `C:\\newfile`
    in a Windows path, `\\n` in a regex a file happens to contain — had its `\\n` turned into a real
    newline by an earlier pass, and the backslash that would have protected it was still there to be
    collapsed afterwards. One left-to-right pass cannot do that. `writeproxy._decode_backslash_escapes`
    already worked this way; this is the same rule, kept local to its one caller."""
    out, i, n = [], 0, len(body)
    while i < n:
        c = body[i]
        if c == "\\" and i + 1 < n:
            nxt = body[i + 1]
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, "\\" + nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


_MUTATION_TOOLS = ("write_file", "create_file", "edit_file", "str_replace", "apply_patch")


def _content_truncated(fn: dict) -> bool:
    """A ``write_file`` whose ARGS parse (valid JSON, normal `tool_calls` finish) but whose CONTENT is a
    provably-truncated source file — the model cut its own file off mid-string, so the JSON-level guard
    above misses it (observed live: a .py written as an opening ``\"\"\"`` docstring + 517 chars, then it
    STOPS — no closing ``\"\"\"``, no code; the syntax floor then flagged "unterminated triple-quoted
    string" 565× while the coder edit-thrashed a file it could never make parse). Signal = an ODD count of
    a triple-quote delimiter, CONFIRMED by the language's own parser failing, so a legit ``\"\"\"`` inside a
    string can't false-positive. Confirmable today for Python (`compile`); other languages fall through to
    the gate. Only a full-file ``write_file`` is checked — an ``edit_file`` new_string may be a partial."""
    if fn.get("name") not in ("write_file", "create_file"):
        return False
    try:
        args = jsontext.loads(fn.get("arguments") or "", strict=False)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(args, dict):
        return False
    content, path = args.get("content"), args.get("path") or ""
    if not isinstance(content, str) or not content.strip():
        return False
    if content.count('"""') % 2 == 0 and content.count("'''") % 2 == 0:
        return False  # balanced triple-quotes → no unterminated-docstring signal
    if str(path).endswith(".py"):
        try:
            compile(content, "<write>", "exec")
            return False  # odd count but it PARSES (a \"\"\" lived inside a string) → not truncated
        except SyntaxError:
            return True   # odd triple-quote AND won't parse → a cut-off write; refuse it
    return False


def has_incomplete_tool_args(completion: dict) -> bool:
    """ANY tool call the model cut off mid-arguments — so forwarding it lowers a broken call. Two cut-off
    shapes: (1) the `arguments` are STILL unparseable after repair (a mid-JSON cut — a normal `tool_calls`
    finish, not `length`; observed live: a self-truncated ``exec_command`` whose inline ``python3 -c "…``
    leaked the model's ``<|tool_call_end|>`` dialect token mid-string, so Codex rejected it with "failed
    to parse function arguments: EOF while parsing a string" 564× in one run); (2) for a content-bearing
    WRITE, the args PARSE but the CONTENT is a provably-truncated source file (:func:`_content_truncated`).
    The parse check is tool-AGNOSTIC (a write, an exec_command, anything) — a broken call must never reach
    the harness. The content check is write-only. The loop refuses either like a length-truncation."""
    for ch in completion.get("choices", []):
        for tc in (ch.get("message") or {}).get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw = fn.get("arguments")
            if not isinstance(raw, str):
                continue
            try:
                json.loads(raw, strict=False)
            except (json.JSONDecodeError, ValueError):
                return True  # repair could not close it → the call was cut off mid-arguments
            if fn.get("name") in _MUTATION_TOOLS and _content_truncated(fn):
                return True  # write args parse but the file content is cut off mid-string → refuse
    return False


_FUSED_TAIL_MAX_LINES = 40


_PROTOCOL_TAG_LINE = re.compile(
    r"^\s*(?:</?tool_call>"                       # <tool_call> / </tool_call>
    r"|<(?:function|parameter)=[^>\n]*>"           # the dialect's openers, which carry the `=`
    r"|</(?:function|parameter)>"                  # and their closers
    r"|</?think>|</?channel>"
    r"|<\|[^|>\n]+\|?>|<[a-z_]+\|>)\s*$")


def _protocol_debris(content: str) -> bool:
    """True when write content is a fused call's DEBRIS: at least one protocol-tag line, and every
    other non-empty line a bare single token (the path the next call carried). Real file content —
    even code that mentions these tags inside string literals with normal multi-word lines — never
    classifies: one real line of prose or code defeats it."""
    lines = [ln for ln in (content or "").splitlines() if ln.strip()]
    if not lines:
        return False
    tags = [ln for ln in lines if _PROTOCOL_TAG_LINE.match(ln)]
    if not tags:
        return False
    return all(len(ln.split()) == 1 for ln in lines if ln not in tags)


def trim_fused_tail(content: str) -> str:
    """Real file content with a fused call's debris stuck to its END, cut back to the real content.

    `_protocol_debris` answers the all-or-nothing case — content that is NOTHING but protocol tags —
    and correctly says no when a genuine file has the tags appended to it. That is the expensive
    case. Walked on cycle 4 cell 22 (`feed-pipeline-java x nemotron-elastic`, 5% useful): the model
    omitted `</parameter>` and opened a second call in the same turn, so every `pom.xml` it sent
    ended

        </project>
        </function>
        </tool_call>
        <tool_call>
        <function=write_file>
        <parameter=path>
        src/main/java/pipeline/Importer.java

    cria refused it eight times as malformed XML at "line 34, column 1" — which is exactly where the
    junk began — and the model, unable to re-read its own rejected payload, re-derived the identical
    file by hand and was refused again. It escaped only by switching to `edit_file`, which then put a
    `<dependency>` block outside `<dependencies>` and left the project unreadable by Maven.

    cria already knows these sentinels: `massage._LEAK_DEBRIS` lists them as tokens that NEVER appear
    in legitimate prose, and `massage._bounded_xml_params` cuts them out of arguments cria itself
    parses. This is the same knowledge applied where a SERVER-parsed tool call delivered them instead.

    ONLY A TAIL, and only one made entirely of tags and bare tokens: a file whose real lines merely
    MENTION a tag (a leak-detector's own source, say) has multi-word lines all the way down and is
    returned untouched, which is the same distinction `_protocol_debris` already draws."""
    lines = (content or "").splitlines()
    cut = len(lines)
    saw_tag = False
    for i in range(len(lines) - 1, -1, -1):
        ln = lines[i]
        if not ln.strip():
            continue
        # THE BOUND APPLIES ALWAYS, and it did not. It read `if not saw_tag and …`, so the moment one
        # tag was found the scan lost its limit and walked to the top of the file — the cut then
        # landing on the EARLIEST tag-shaped line anywhere, not on the start of the trailing junk.
        # The docstring says "ONLY A TAIL" and the comment below claims the bound "keeps it to an
        # argument's worth of lines rather than the whole file"; neither was true after the first
        # tag. A 205-line file with one tag-shaped line near the top came back as two lines.
        if (len(lines) - i) > _FUSED_TAIL_MAX_LINES:
            break
        if _PROTOCOL_TAG_LINE.match(ln):
            saw_tag, cut = True, i     # the cut may only ever land ON a tag
            continue
        # A VALUE LINE IS SCANNED PAST but never becomes the cut. Both ends of the debris need this
        # and for opposite reasons: it trails the tags (the next call's argument, met first going
        # backwards), and it also precedes them in ordinary markup (`</project>`, `}`), where cutting
        # at it would eat the file. Only a tag marks where the junk starts.
        #
        # ANY value, not just a bare token. The single-token rule fitted the walked case, where the
        # fused second call was a `write_file` and its `path` is one word — and missed the same
        # failure when the second call is an `exec_command`, because `mvn -q compile` is three words
        # and the scan broke on it before it ever met a tag. Verified against the four captured
        # payloads from feed-pipeline-java x nemotron-elastic 1787436645: all four returned unchanged,
        # cria refused its own write four times as malformed XML pointing at `line 34: </function>`,
        # and the model could not see the payload it had sent.
        #
        # This is safe because `_PROTOCOL_TAG_LINE` matches only tokens that never appear in real
        # content — `</function>`, `<tool_call>`, `<parameter=…>` — so a file with no fused call has
        # no tag to find and comes back untouched however far the scan walks. The bound keeps it to
        # an argument's worth of lines rather than the whole file.
        continue
    if not saw_tag or cut == 0:
        return content          # nothing to cut, or the whole thing is debris (that is _protocol_debris)
    return "\n".join(lines[:cut]).rstrip("\n") + "\n"


_TC_DEBRIS = ("<|tool_call>", "<tool_call|>", '<|"|>', "<|tool_call_start|>", "<|tool_call_end|>")


def _has_tc_debris(arguments) -> bool:
    """True when a tool call's raw arguments carry leaked tool-call special tokens — a fused/corrupt call
    whose command would reach bash as garbage. Cheap substring scan over the raw string."""
    s = arguments if isinstance(arguments, str) else ("" if arguments is None else str(arguments))
    return any(tok in s for tok in _TC_DEBRIS)


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "\\": "\\", "0": "\0"}


def _repair_double_escaped(content: str) -> str:
    if "\n" in content or "\\n" not in content:
        return content
    return _decode_backslash_escapes(content)


def _decode_backslash_escapes(s: str) -> str:
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if i + 1 >= n:
            out.append("\\")
            i += 1
            continue
        nxt = s[i + 1]
        out.append(_ESCAPES[nxt] if nxt in _ESCAPES else "\\" + nxt)
        i += 2
    return "".join(out)


@dataclass(frozen=True)
class FusedCall:
    """One parse's arguments and measured tail; None means no sentinel was found.

    A malformed head still has a measured tail. This does not retain cross-call
    state, emit an event, or change the legacy facade's dict-or-None API.
    """

    arguments: dict | None
    discarded_chars: int | None


def recover_fused_call(raw: str) -> FusedCall:
    """Read the first literal argument object and report its discarded suffix."""
    cut = min([i for i in (raw.find(t) for t in _FUSED_SENTINELS) if i >= 0], default=-1)
    if cut < 0:
        return FusedCall(None, None)
    head = raw[:cut].strip()
    discarded = len(raw) - cut
    for cand in (head, head.replace('\\"', '"').replace("\\'", "'")):
        try:
            obj = jsontext.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return FusedCall(obj, discarded)
    return FusedCall(None, discarded)
