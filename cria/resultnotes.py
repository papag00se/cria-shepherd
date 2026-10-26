"""Tool-result envelopes, payload boundaries and factual note plumbing.

Policy-specific rejection thresholds, note budgets and intervention events are
not owned here. Payload boundaries continue to use the canonical body hint.
"""
from __future__ import annotations

import hashlib
import re

from . import bodykeys, payloadboundary, wsview
from .toolwire import SECTION_PREFIX

_ENVELOPE_OUTPUT_LINE = re.compile(r"^Output:[ \t]*$", re.M)


_ENVELOPE_ADVISORY = re.compile(r"^Total output lines: \d+[ \t]*$")


_ENVELOPE_CUT_WARNING = re.compile(r"^Warning: truncated output.*$")


_EXIT_CODE = re.compile(r"Process exited with code (\d+)")


def _strip_exec_envelope(content: str, *, preserve_eof: bool = False) -> str:
    """The harness exec envelope around a re-presented synthetic-tool result → just the payload.
    Untouched when the envelope isn't present (a native path, an already-clean or non-exec result)."""
    if not content:
        return content
    m = _ENVELOPE_OUTPUT_LINE.search(content)
    if not m or "Process exited with code" not in content[:m.start()]:
        return content
    # The newline immediately after Output: belongs to framing; subsequent blank lines
    # in a whole-file payload belong to the file, just like its trailing newlines.
    lines = content[m.end():].removeprefix("\n").split("\n")
    kept_warning = ""
    while lines and (_ENVELOPE_ADVISORY.match(lines[0]) or (not preserve_eof and not lines[0].strip())
                     or _ENVELOPE_CUT_WARNING.match(lines[0])):
        line = lines.pop(0)
        if _ENVELOPE_CUT_WARNING.match(line):
            kept_warning = line.strip()      # the payload is a piece — say so above it
    body = "\n".join(lines)
    if not preserve_eof:
        body = body.rstrip("\n")
    return f"{kept_warning}\n{body}" if kept_warning else body


def _noted(m: dict, content: str, note: str) -> dict:
    out = dict(m)
    append_note(out, note, content)
    return out


_digest = payloadboundary.digest


def append_note(m: dict, note: str, content: str | None = None) -> None:
    """Append cria's ``note`` to tool message ``m`` and record WHERE THE PAYLOAD ENDED (length + digest of what
    the tool said), the first time only — a cria-internal hint (`bodykeys.PAYLOAD_BOUNDARY`) the wire strips.
    ``content`` is the payload when the caller already cleansed it. Every producer that appends cria text to
    a tool result goes through here, so a reader that counts the payload never has to guess from the text."""
    c = m.get("content") if content is None else content
    c = c if isinstance(c, str) else ""
    if bodykeys.PAYLOAD_BOUNDARY not in m:
        m[bodykeys.PAYLOAD_BOUNDARY] = (len(c), _digest(c))
    m["content"] = c + "\n\n" + note


payload_of = payloadboundary.payload_of


def _workspace_ecosystem(workspace_root) -> str:
    """The first ecosystem this workspace declares, by its own manifests — "" when none or unreadable.

    Reuses `probediscovery.detect_ecosystems`, whose enum values are already the keys of
    `_DEPENDENCY_SOURCE_ROOTS` ("jvm", "rust", …), so there is no second table to drift (#23)."""
    if not workspace_root:
        return ""
    try:
        from pathlib import Path
        from .probediscovery import ProjectDir, detect_ecosystems
        entries = wsview.current(workspace_root).scandir(workspace_root)
        if entries is None:
            return ""
        names = {e.name for e in entries if e.is_file()}
        found = detect_ecosystems(ProjectDir(Path(workspace_root), names))
        return found[0].value if found else ""
    except Exception:                     # noqa: BLE001 — a note must never break the reply
        return ""


def probegate_marker_in(text: str) -> bool:
    """A gate result — proberun.dependency_note already speaks for those."""
    return SECTION_PREFIX in text
