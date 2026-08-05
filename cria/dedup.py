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
