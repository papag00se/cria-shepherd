"""The exact-match edit, decided in cria on bytes cria holds (docs/harness-primitives.md 8.1). Pure: no I/O.

This is the program the harness used to run, ported without a change of behaviour (the incidents behind each rule are kept where
the rule is). The file's bytes are decoded as UTF-8 with ``surrogateescape`` and re-encoded the same way, so a byte that is not
UTF-8 survives as itself; a file that is CRLF throughout is edited with the LF text the coder sends; an exact single match wins,
else the non-whitespace tokens of ``old`` are matched across any whitespace; 0 or several matches never write. A miss is not
prose: it is the *facts* (:class:`Failure`), which :mod:`cria.editrecovery` turns into the one directive keyed on the file's
failure history. A landed edit reports the window of the file it wrote (``echo``), read off the bytes, never authored.
"""
import base64
import difflib
import json
import re
import zlib
from dataclasses import dataclass, field

from . import content_reduce as content_reduce_mod, prompts

ECHO_CONTEXT = 3
# ONE byte bound on the whole echo: the lines shown (span + context), and - separately - the report that carries them. Over it the
# window is dropped to the two context windows around the span, and over it again to the header alone, which says so. A window is
# never cut mid-way.
ECHO_MAX_BYTES = 3000
ECHO_WIRE_MAX_BYTES = content_reduce_mod.INLINE_RESULT_MAX_BYTES
FACTS_CAP = content_reduce_mod.INLINE_RESULT_MAX_BYTES
EDITFAIL_LEN = len("⟦ctx:editfail⟧")        # the size of the old report's marker, which the cap below was measured with (kept: what the coder is shown must not move)
PACKED_PREFIX = "z."
# The modes whose directive can quote the file (the escalation): the others never read `current`, so it is not kept for them.
QUOTES_FILE = ("anchor", "close", "no_anchor")


@dataclass(frozen=True)
class Applied:
    """The edit applied: the whole file after it, the character span of the file it replaced (``a``..``b``), what stands there now
    (``new``, after the CRLF rule), and whether it matched only after whitespace was ignored."""
    text: str
    a: int
    b: int
    new: str
    old: str
    flex: bool


@dataclass(frozen=True)
class Failure:
    """The edit did not apply: ``mode`` and the facts the directive is composed from. ``facts`` has no ``path`` and no ``current``:
    :func:`report` adds them."""
    mode: str
    facts: dict = field(default_factory=dict)


def shown(text: str) -> str:
    """What the coder is TOLD about a file: never a lone surrogate."""
    return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def _b64json(value: dict) -> str:
    return base64.b64encode(json.dumps(value).encode()).decode()


def report(failure: "Failure | str", name: str, current: str, **more) -> dict:
    """The fact report of a failed edit of the file ``name`` whose text was ``current``: ``mode``, ``path`` (the basename) and the
    facts, plus the file's text unless the report would then be larger than one result may be (the coder is then told to read the
    file instead: a directive that quotes a file it cannot hold whole is worth less than one that points at it)."""
    mode, facts = (failure.mode, dict(failure.facts)) if isinstance(failure, Failure) else (failure, {})
    facts.update(more)
    facts["mode"], facts["path"], facts["current"] = mode, name, current
    facts = {k: (shown(v) if isinstance(v, str) else v) for k, v in facts.items()}
    if EDITFAIL_LEN + len(_b64json(facts)) > FACTS_CAP or mode not in QUOTES_FILE:
        facts.pop("current")
    return facts


def apply_edit(text: str, old: str, new: str, echo: bool = False) -> "tuple[Applied | Failure, dict | None]":
    """``(Applied | Failure, window report)`` for one edit of ``text`` (a file decoded as UTF-8 with surrogateescape). The window
    report is only made for an applied edit and only when ``echo`` is set."""
    s = text
    if "\r\n" in s and s.count("\n") == s.count("\r\n") and "\r" not in old + new:
        # a file that is CRLF throughout: the LF text the coder sends spells that file's line ending (before this, the matching was done on a normalised copy)
        old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
    if old == new:
        return Failure("identical"), None
    n = s.count(old)
    if n == 1:
        a = s.find(old)
        return _applied(s, a, a + len(old), new, old, False, echo)
    if n > 1:
        return Failure("multi", {"n": n}), None
    toks = old.split()
    if toks:
        ms = list(re.compile(r"\s+".join(map(re.escape, toks))).finditer(s))
        if len(ms) == 1:
            # The token match starts at the first NON-WHITESPACE character, so the file's leading indent sits in the prefix. When old_string
            # starts flush (coder gave bare statements), that is the point: the file's indent survives and a bare new_string lands after it.
            # But when old_string CARRIES its own leading indent, new_string carries the same indent - and splicing after the file's indent
            # doubles it. Walked on mellum2 1786196176 call 0190: a correct side_effect fix (12-space old, 12-space new, off-disk only by a
            # blank line the flexible match forgives) became a 24-space line, the syntax guard caught the flexible match's own wreckage, and
            # the report told the coder to "Fix new_string" - for an edit that was right. The same fix, resubmitted with a one-line
            # old_string, applied verbatim at 0215, 120 calls later. So: old_string indented -> consume the file's indent back to line start
            # and let new_string supply its own.
            # ...and only when new_string carries indentation of its OWN to replace it with. Gating on old_string alone regressed the sloppy
            # case the flexible matcher exists for: indented old + FLUSH new used to land after the file's indent (valid) and would now land
            # at column 0 (broken, then refused as would_break). Both sides indented is the 0190 shape and the only one where the file's
            # indent is redundant.
            m = ms[0]
            a = m.start()
            if old[:1] in " \t" and new[:1] in " \t":
                ls = s.rfind("\n", 0, a) + 1
                if not s[ls:a].strip():
                    a = ls
            return _applied(s, a, m.end(), new, old, True, echo)
        if len(ms) > 1:
            return Failure("multi_flex", {"n": len(ms)}), None
    oldl = old.split("\n")
    o0 = next((j for j, line in enumerate(oldl) if line.strip()), 0)
    key = oldl[o0].strip() if oldl else ""
    new_first = next((line.strip() for line in new.split("\n") if line.strip()), "")
    lines = s.split("\n")
    ctx = close = ""
    dline = 0
    if key:
        for i, line in enumerate(lines):
            if key[:40] in line:
                # Window the DIVERGENCE, not the head. Anchoring on the first line of old_string put the 6-line window over the text that
                # already MATCHED - so a 10-line old_string that differs at line 7 got back six lines it had verbatim, under "The file
                # actually reads", and the coder resubmitted the same wrong old_string. Walk forward to the first line that actually
                # differs and centre there.
                d = i
                for k in range(o0, len(oldl)):
                    fi = i + k - o0
                    if fi >= len(lines) or lines[fi] != oldl[k]:
                        d = min(fi, len(lines) - 1)
                        break
                ctx = "\n".join(lines[max(0, d - 2):d + 4])
                dline = d + 1
                break
        if not ctx:    # no substring anchor - find the file line the old_string is CLOSEST to (a near-miss)
            cm = difflib.get_close_matches(key, [line.strip() for line in lines if line.strip()], n=1, cutoff=0.75)
            if cm:
                close = cm[0]
    if ctx:
        return Failure("anchor", {"anchor": ctx, "line": dline}), None
    if close and new_first and len([line for line in new.split("\n") if line.strip()]) == 1 and " ".join(new_first.split()) == " ".join(close.split()):
        # "Already done" is a fact only when the complete proposed replacement equals the complete current line. Substring containment made
        # `require x` equal `require x "v1.5.0"` and falsely ordered the coder not to remove the rejected version.
        return Failure("phantom", {"anchor": close}), None      # already-correct line the model misremembers
    if close:
        return Failure("close", {"anchor": close}), None       # near-miss: a mistyped token
    return Failure("no_anchor"), None


def _applied(s: str, a: int, b: int, new: str, old: str, flex: bool, echo: bool) -> "tuple[Applied, dict | None]":
    result = s[:a] + new + s[b:]
    applied = Applied(result, a, b, new, old, flex)
    return applied, (window(applied) if echo else None)


def encoded_len(value: dict) -> int:
    """The length of the report as it used to travel (base64, or zlib then base64 when that is shorter): the measure the window
    selection below was always made against, kept so what the coder is shown does not move."""
    plain = _b64json(value)
    packed = PACKED_PREFIX + base64.b64encode(zlib.compress(json.dumps(value).encode(), 9)).decode()
    return min(len(plain), len(packed))


def window(applied: Applied) -> dict:
    """The window of the file an applied edit wrote (``first``/``last`` lines of the replacement, ``total`` lines, the ``segs`` shown and
    whether anything around them was ``omitted``), as the file now reads. A span too large to repeat is shown as the two context
    windows around it, each lossless for the lines it names."""
    res = shown(applied.text)
    a0, a1 = applied.a, applied.a + len(applied.new)
    new, old, flex = applied.new, applied.old, applied.flex
    lines = res.split("\n")
    if res.endswith("\n") or not res:
        lines.pop()
    total = len(lines)
    nl = lambda i: res.count("\n", 0, i) + 1
    first = nl(a0)
    last = nl(max(a0, a1 - 1)) if a1 > a0 else first
    first = min(max(first, 1), max(total, 1))
    last = min(max(last, first), max(total, 1))
    lo = max(1, first - ECHO_CONTEXT)
    hi = min(total, last + ECHO_CONTEXT)
    join = "\n".join
    cands = [[[lo, join(lines[lo - 1:hi])]]]
    if a1 > a0:
        cands.append([x for x in ([[lo, join(lines[lo - 1:first - 1])]] if first > lo else []) + ([[last + 1, join(lines[last:hi])]] if hi > last else [])])
    cands.append([])
    if total == 0:
        cands = [[]]
    # THE LINES THAT NOW FOLLOW THE REPLACEMENT, MEASURED AGAINST IT. An old_string that anchors only the head of a member (its signature
    # line) while new_string carries the WHOLE member replaces that head and nothing else: the old body is still in the file, directly
    # under the new one. Counted, not judged: the first lines after the span (blank ones skipped) that read the same, whitespace
    # collapsed, as one unbroken stretch of the replacement. Only a replacement longer than what it replaced can leave such a remainder,
    # and a stretch of one line (or one repeated line) is no signal.
    dup = None
    new_lines = new.split("\n")
    if new_lines and new_lines[-1] == "":
        new_lines.pop()
    old_lines = old.split("\n")
    if old_lines and old_lines[-1] == "":
        old_lines.pop()
    if len(new_lines) > len(old_lines) and a1 > a0:
        norm = lambda line: " ".join(line.split())
        N = [(first + j, norm(line)) for j, line in enumerate(new_lines) if line.strip()]
        F = [(last + 1 + k, norm(line)) for k, line in enumerate(lines[last:last + len(new_lines)]) if line.strip()]
        best = bj = 0
        for j in range(len(N)):
            m = 0
            while m < len(F) and j + m < len(N) and N[j + m][1] == F[m][1]:
                m += 1
            if m > best:
                best, bj = m, j
        if best >= 2 and len(set(t for _, t in F[:best])) >= 2 and any(c.isalnum() for _, t in F[:best] for c in t):
            dup = [F[0][0], F[best - 1][0], N[bj][0], N[bj + best - 1][0], len(old_lines), len(new_lines)]
    for i, segs in enumerate(cands):
        omitted = (not segs) and (lo < first or hi > last)
        if sum(len(t.encode()) for _, t in segs) > ECHO_MAX_BYTES and i < len(cands) - 1:
            continue
        rep = dict(first=first, last=last, total=total, flex=flex, empty=a1 <= a0, segs=segs, omitted=omitted)
        if dup:
            rep["dup"] = dup
        if encoded_len(rep) > ECHO_WIRE_MAX_BYTES and i < len(cands) - 1:
            continue
        return rep
    raise AssertionError("the last candidate is always taken")


def render_landed(path: str, ev: "dict | None" = None, rm: str = "") -> str:
    """What the coder is told of a landed write or edit: the confirmation, then (for an edit, when the coder is engaged) the window of
    the file it wrote - the replaced span plus context lines either side, with the file's line count - and (for a whole write) the
    measured removal facts. A window, never a claim about the whole file; read off the bytes, not authored."""
    confirm = prompts.render("write_confirm", path=path)
    text = confirm
    if ev:
        first, last, total = int(ev["first"]), int(ev["last"]), int(ev["total"])
        segs = [(int(n), str(t)) for n, t in ev["segs"]]
        if ev.get("empty"):
            head = prompts.render("edit_echo_removed", path=path, total=total, a=first)
        elif segs and (len(segs) == 1 and segs[0][0] <= first and segs[0][0] + segs[0][1].count("\n") >= last):
            head = prompts.render("edit_echo", path=path, total=total, a=first, b=last)
        else:
            head = prompts.render("edit_echo_span_omitted", path=path, total=total, a=first, b=last)
        parts = [confirm, head]
        dup = ev.get("dup")
        if dup:
            a, b, x, y, nold, nnew = (int(v) for v in dup)
            parts.append(prompts.render("edit_echo_repeat", a=a, b=b, x=x, y=y, old=nold, new=nnew))
        if ev.get("flex"):
            parts.append(prompts.load("edit_echo_flexible"))
        if ev.get("omitted"):
            parts.append(prompts.load("edit_echo_omitted"))
        for n, t in segs:
            rows = t.split("\n")
            parts.append(prompts.render("edit_echo_window", first=n, last=n + len(rows) - 1))
            parts.append("\n".join(f"{n + i}: {r}" for i, r in enumerate(rows)))
        text = "\n".join(parts)
    facts = (rm or "").strip()
    return f"{text}\n{facts}" if facts else text
