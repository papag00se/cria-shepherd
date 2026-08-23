"""One copy of cria's own injected ground truth per outbound view — byte-exact, aggregate-lossless.

THE PROBLEM, measured on the maple full walk (ada-handles_maple-preview_codex_poff_1785956867):
the rendered fetch ledger — the ~2.4KB "GET /handles/{handle} → hex(string), name(string)…" field
block — rode up to THREE times in a single coder prompt: once in the per-call ⟦ctx:facts⟧ anchor
(the copy that is SUPPOSED to be there), once byte-identically inside the compaction summary the
harness stores as the session root (server._harden_compaction_reply's deliberate appendix — right
at compaction time, redundant every call after, because the anchor re-injects the same ledger
fresh), and once as the identical field lines inside the original fetched-page tool result still
in-window. Steer/judge prompts doubled it again: the serialized session carried the same lines the
labeled fetch-record block re-stated. None of these copies added a fact; each cost kilobytes of a
small model's window every single call.

THE RULE. This is NOT compression, summarization, or relevance pruning — the never-truncate
doctrine stands: the model always reads the full real content. This removes byte-identical
DUPLICATES of blocks cria itself rendered, leaving exactly one authoritative copy (the anchor /
labeled block) and a one-line pointer where each duplicate sat. Byte-exact matching only, a
conservative size floor, copy-on-write, and identity when there is nothing to do. Precedents:
repeated identical calls are already folded to a marker, stale ⟦ctx:files⟧ lists are already
filtered, superseded write payloads are already stubbed — this is the same doctrine applied to
cria's own ledger renderings.

Pure module: no I/O, no imports from the loop. The caller supplies the ledger text, the pointer
note (a prompts/ template — model-facing strings live in files), and the marker prefix of the
owner block that must never be touched.
"""

from __future__ import annotations

import re

# A unit shorter than this is not worth a pointer, and short strings ("HTTP 200") legitimately
# recur in unrelated content — the floor keeps matching to blocks that cannot collide by accident.
MIN_UNIT_CHARS = 200

_BLANK_RUN = re.compile(r"\n{3,}")


def ledger_units(ledger: str) -> list[str]:
    """The excisable units of a rendered fetch ledger.

    Two granularities, both byte-exact:
    * per-URL ENTRY BLOCKS — a ``- <url> → <status>…`` line plus its indented continuation lines.
      This matches the compaction summary's appendix, which was rendered by the same formatter.
    * individual LONG LINES — the field-shape lines also appear verbatim inside the original
      fetched-page representation under a different wrapper, where the block form can't match.

    The ledger's header line is never a unit: a pointer must not replace the block's own label.
    Units below MIN_UNIT_CHARS are dropped."""
    if not ledger:
        return []
    lines = ledger.splitlines()
    units: list[str] = []
    block: list[str] = []
    for ln in lines:
        if ln.startswith("- "):
            if block:
                units.append("\n".join(block))
            block = [ln]
        elif block and (ln.startswith(" ") or ln.startswith("\t")):
            block.append(ln)
        else:
            if block:
                units.append("\n".join(block))
            block = []
    if block:
        units.append("\n".join(block))
    units.extend(ln for ln in lines if not ln.startswith("- "))
    # longest first, so an entry block is excised whole before its own lines could match the
    # remainder; the size floor drops headers, short entries, and blank lines.
    out = [u for u in units if len(u) >= MIN_UNIT_CHARS]
    out.sort(key=len, reverse=True)
    return out


def elide_text(text: str, units: list[str], note: str) -> tuple[str, int]:
    """Excise byte-identical occurrences of ``units`` from ``text``. The FIRST excision in this
    text becomes ``note`` (one pointer per message, not one per unit); the rest vanish. Blank runs
    left behind are collapsed. Returns ``(new_text, n_excised)`` — ``(text, 0)`` untouched when
    nothing matched."""
    n = 0
    for u in units:
        while u in text:
            text = text.replace(u, note if n == 0 else "", 1)
            n += 1
    if n:
        text = _BLANK_RUN.sub("\n\n", text)
    return text, n


def elide_from_messages(msgs: list[dict], units: list[str], note: str, *,
                        skip_prefix: str) -> tuple[list[dict], int]:
    """Copy-on-write elision over an outbound message list.

    Only ``user`` and ``tool`` messages with plain-string content are candidates: system messages
    are cria's frame, assistant turns are the model's own words (never rewritten), and the owner
    block — any message whose content starts with ``skip_prefix`` (the ⟦ctx:facts⟧ anchor) — keeps
    the full copy by definition. Returns ``(msgs, 0)`` (the SAME list) when nothing matched."""
    if not units:
        return msgs, 0
    out: list[dict] = []
    total = 0
    for m in msgs:
        c = m.get("content")
        if (m.get("role") in ("user", "tool") and isinstance(c, str)
                and not c.lstrip().startswith(skip_prefix)):
            new, n = elide_text(c, units, note)
            if n:
                out.append({**m, "content": new})
                total += n
                continue
        out.append(m)
    return (out, total) if total else (msgs, 0)


def fold_repeated_messages(msgs: list[dict], note: str, *, protect: "tuple[str, ...]" = (),
                           min_chars: int = MIN_UNIT_CHARS) -> tuple[list[dict], int]:
    """Keep ONE copy of each byte-identical ``user``/``tool`` payload — the NEWEST — and point the
    earlier ones at it. Rule 5's first exception, applied to whole messages.

    MEASURED, over 6,614 captured coder prompts: 885 of them (13%) carried a block of 200 characters
    or more repeated VERBATIM inside a single prompt, 2.2 MB of duplicate bytes in total. The largest
    groups were cria's own refusal (352 prompts carrying the identical ⟦ctx:denied⟧ twice), the same
    source file read twice, cria's own edit-failure directive, and one fetched page delivered twice.
    Existing dedup covers the FETCH LEDGER only, so none of those were reachable by it.

    NEWEST WINS, for the reason `stub_old_write_args` and `clean_gate_results` already give: the last
    copy is the one that describes the world now, and an older copy of a file the coder has since
    rewritten is the exact shape that made a model describe two versions of one file as "current".
    Byte-identical here, so nothing is lost either way — but the rule must be the same rule.

    NEVER an ``assistant`` turn (the model's own words are never rewritten), never a ``system``
    message (cria's frame), and never a message carrying one of ``protect`` — an anchor block is the
    designated single copy of its content and must not be folded into a pointer at a later duplicate.

    Aggregate-lossless: n pointers plus one full copy, so the coder can still SEE it happened n+1
    times, which is itself signal when the repeat is a refusal it kept re-earning."""
    if not msgs:
        return msgs, 0
    keep: dict[str, int] = {}
    for i, m in enumerate(msgs):
        c = m.get("content")
        if (m.get("role") in ("user", "tool") and isinstance(c, str)
                and len(c.strip()) >= min_chars
                and not any(mark in c for mark in protect)):
            keep[c.strip()] = i          # last write wins → the newest copy is the keeper
    if len(keep) == len([1 for m in msgs
                         if isinstance(m.get("content"), str)
                         and m.get("role") in ("user", "tool")
                         and len(m["content"].strip()) >= min_chars
                         and not any(mark in m["content"] for mark in protect)]):
        return msgs, 0                   # every candidate was unique — same list, no copy
    out, folded = [], 0
    for i, m in enumerate(msgs):
        c = m.get("content")
        # THE ROLE FILTER GATES THE WRITE. It guarded only the index build above, so any message —
        # including an `assistant` turn and a `system` message — whose content matched a later
        # user/tool payload had its content replaced by cria's third-person pointer. Reproduced both
        # ways. The docstring says the opposite: "NEVER an assistant turn (the model's own words are
        # never rewritten), never a system message (cria's frame)."
        if (m.get("role") in ("user", "tool") and isinstance(c, str)
                and keep.get(c.strip(), i) != i):
            out.append({**m, "content": note})
            folded += 1
            continue
        out.append(m)
    return (out, folded) if folded else (msgs, 0)


# ── Per-run noise ────────────────────────────────────────────────────────────────────────────────
# Two payloads that differ ONLY here are the same payload. Everything in this table was MEASURED as
# the sole difference between near-identical payloads across captured sessions — nothing is here on
# suspicion, because a wrong entry silently merges two genuinely different findings.
#
# WHO IT HIT. mellum2 1786051505 carried the same gate finding THREE times in one coder prompt
# (`resolve_handle_and_test.py:92: undefined name 'pytest'`, on a file the coder had since cut to 7
# lines). The repeat-collapse keys on the payload text and never fired: the three copies differed by
# a `<urllib.request.Request object at 0x…>` address and `in 0.36s` vs `in 0.28s`. Scanned across the
# 12 most recent sessions, 10 near-identical gate-payload pairs turned up in 2 of them and EVERY
# difference was one of these two shapes.
#
# WRITTEN BY SHAPE, NOT BY LANGUAGE. The first cut matched pytest's exact `in 0.36s` phrasing, which
# is a python rule wearing a general name — `go test` prints `ok\ttick\t0.003s` with no "in", and two
# runs of one passing Go suite differ by exactly that (measured: 0.003s then 0.002s), so the identical
# bug stays live on every non-python family in the suite. Operator caught it. What is actually noise
# is an ADDRESS and a DURATION, in whatever way a runner spells them.
#
# A MISS IS SAFER THAN A FALSE MERGE, and the two costs are not symmetric: a miss shows the coder one
# finding twice (duplicated information), a false merge replaces a DIFFERENT finding with a
# back-reference (information destroyed). Every pattern below is therefore anchored tightly enough
# that it cannot fire on content, and each entry names the runtimes whose real output it was checked
# against — printed from this box, not recalled.
#
# Verified not to over-merge: applied to 777 distinct payloads across 20 captured sessions, the table
# merges nothing the narrow python-only version did not.
_VOLATILE = (
    # the harness exec envelope's per-run fields (whole lines)
    (re.compile(r"(?im)^\s*(?:Chunk ID:|Wall time:|Original token count:)\s*\S.*$\n?"), ""),

    # ── an object's identity, in each spelling the suite's runtimes actually use ──
    # `0x…` — python `<Request object at 0x729803290080>`, ruby `#<Foo:0x000070a6e6366980>`,
    # go `0xc000124010`, rust `0x61d3af242d60`, c `0x7ffd01400414`
    (re.compile(r"0x[0-9a-fA-F]{6,}"), ""),
    # the JVM's `Type@hash` — `java.lang.Object@2a139a55`, `[I@14ae5a5`,
    # `java.util.HashMap$KeyIterator@7f31245a`, `[Ljava.lang.String;@6d06d69c`.
    # The type must look like a JVM type (an array descriptor, a dotted package, or a Capitalized
    # class) and the hash must not be followed by a dot. Without that, `user@abcdef.com` is 6 hex
    # digits ending on a word boundary and an email address becomes `user.com`.
    (re.compile(r"((?:\[+[A-Z][\w$;./]*|(?:[\w$]+\.)*[A-Z][\w$]*(?:\$[\w$]+)*)@)[0-9a-fA-F]{4,}\b(?!\.)"),
     r"\1"),
    # python's mock prints a DECIMAL identity, no `0x` — `<MagicMock id='125997213614208'>`. The most
    # common address in these suites, since every mocked test that fails prints one. Anchored to the
    # `id=` key: a bare long number is content (a lovelace amount, an epoch) and must survive.
    (re.compile(r"(\bid=['\"]?)\d{6,}"), r"\1"),

    # ── a runner's elapsed time, in each spelling ──
    # pytest `in 0.36s`, cargo `finished in 0.00s`, go `ok\ttick\t0.003s`,
    # JUnit `Time elapsed: 0.031 s`, RSpec `Finished in 0.0123 seconds`, jest `Time: 1.234 s`.
    # The decimal point is load-bearing: it keeps `expected 30s` in a finding out of the table.
    (re.compile(r"\b\d+\.\d+\s?(?:s|secs?|seconds?)\b"), ""),
    # …and sub-second units, where runners drop the decimal — mocha `(123ms)`
    (re.compile(r"\b\d+(?:\.\d+)?\s?(?:ns|µs|us|ms)\b"), ""),

    # ── a runner's THROUGHPUT, which is elapsed time wearing a different unit ──
    # minitest `614.8036 runs/s, 614.8036 assertions/s`, and the same shape wherever a runner divides
    # its count by its clock. The elapsed-time rule above cannot see it: `\s?s` does not match ` runs/s`.
    (re.compile(r"\b\d+(?:\.\d+)?\s*(?:runs?|tests?|assertions?|examples?|specs?)/s\b"), ""),
    # ── and a randomised run ORDER, which changes nothing about what happened ──
    # minitest `Run options: --seed 33602`, rspec `--seed 1234`, `go test -shuffle=on` echoes one,
    # pytest-randomly prints `Using --randomly-seed=…`. Two runs of one suite differ only here.
    (re.compile(r"(?i)(--?(?:randomly-)?seed[= ])\d+"), r"\1"),
)


def volatile_key(content) -> str:
    """A payload's identity for duplicate detection — per-run noise removed.

    ONE owner. Both the tool-result duplicate groups (focustrim) and the gate's repeat-collapse
    (probegate) key on this, so "is this the same thing again?" has a single answer across cria.
    Not a normalizer for DISPLAY — the text the model reads is always the original bytes.

    WHAT A RUN VARIES IS NOT WHAT A RUN SAID. This scrubbed wall-clock and object identities but not
    a runner's SEED or its throughput banner, so two byte-equivalent `rake test` runs keyed
    differently and the repeat guard never fired. Walked on shipping-rates-rb x nemotron-elastic
    1787432916: four identical green runs — `7 runs, 7 assertions, 0 failures` every time — each got
    its own group, and the coder was never told it had already run this. Generalises to RSpec,
    `go test -shuffle` and pytest-randomly, which all print one."""
    if not isinstance(content, str):
        return ""
    for pat, repl in _VOLATILE:
        content = pat.sub(repl, content)
    return content.strip()


# One line where an identical earlier action block sat. Model-facing (#22), so the text lives in
# prompts/; this is only the key.
REPEAT_NOTE_KEY = "work_log_repeat"


def fold_repeated_actions(log: str, note: str) -> tuple[str, int]:
    """The work log with byte-identical repeated ACTION BLOCKS folded to one copy plus ``note``.

    An action block is a ``$ call`` line and the ``  -> result`` lines under it — the unit
    :func:`cria.loop._work_log` emits. Two blocks that are byte-identical carry one fact between
    them, so the second and later copies are redundancy, not information: this is de-duplication,
    the first of #5's two exceptions, and the aggregate content is unchanged.

    THIS REPLACED A TAIL CLIP. `_bound_evidence` used to keep the last 24,000 characters of the log
    and discard the head, on the old counter-nuance that a prompt cria composes may be bounded. The
    incident that justified the budget is itself the argument for folding instead: one step's log
    grew 34KB -> 106KB -> 223KB across re-nudges, which is the SAME actions re-rendered. Folding
    removes exactly that and keeps every distinct action; the clip removed whichever ones happened
    to be oldest, including the write that started the trouble.

    Order is preserved and the FIRST copy of a block always survives whole. Returns
    ``(text, folded_count)``; identity when there is nothing to fold.
    """
    if not log:
        return log, 0
    blocks, cur = [], []
    for line in log.split("\n"):
        if line.startswith("$ ") and cur:
            blocks.append(cur)
            cur = [line]
        else:
            cur.append(line)
    if cur:
        blocks.append(cur)

    out, seen, folded = [], set(), 0
    pending = None                       # (note_index, times) for a RUN of identical blocks
    for b in blocks:
        body = "\n".join(b)
        # A block below the floor is too small to be worth a pointer, and short results ("-> exit 0")
        # legitimately recur under DIFFERENT calls — the `$` line is part of the key, so identical
        # here means the same call returning the same thing, but the floor keeps the noise down.
        if len(body) < MIN_UNIT_CHARS or body not in seen:
            seen.add(body)
            out.append(body)
            pending = None
            continue
        folded += 1
        if pending is not None:          # a RUN: one note carrying the count, not N notes
            i, times = pending
            pending = (i, times + 1)
            out[i] = note.replace("{{N}}", str(times + 1))
            continue
        out.append(note.replace("{{N}}", "1"))
        pending = (len(out) - 1, 1)
    return ("\n".join(out), folded) if folded else (log, 0)
