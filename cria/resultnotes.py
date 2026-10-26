"""Tool-result envelopes, payload boundaries and factual note plumbing.

Policy-specific rejection thresholds, note budgets and intervention events are
not owned here. Payload boundaries continue to use the canonical body hint.
"""
from __future__ import annotations

import hashlib
import re
from typing import NamedTuple

from . import bodykeys, payloadboundary, wsview
from .toolwire import SECTION_PREFIX

# ONE grammar, at stdout offset zero. No search for an Output/status phrase in a
# log or file. Optional fields have a fixed order; an unknown field/partial header
# leaves the entire result opaque. Status-less Chunk/Wall headers are historical
# framing, NOT evidence of completion. Case/horizontal spacing remain tolerated.
_EXEC_HEADER = re.compile(
    r"\A(?:Chunk[ \t]+ID:[ \t]*(?P<chunk>[^\s]+)[ \t]*\r?\n)?"
    r"(?:Wall[ \t]+time:[ \t]*(?P<wall>\d+(?:\.\d+)?[ \t]*(?:seconds|s))[ \t]*\r?\n)?"
    r"(?:Process[ \t]+(?:exited[ \t]+with[ \t]+code[ \t]+(?P<exit>\d+)"
    r"|running[ \t]+with[ \t]+session[ \t]+ID[ \t]+(?P<session>\d+))[ \t]*\r?\n)?"
    r"(?:Original[ \t]+token[ \t]+count:[ \t]*\d+[ \t]*\r?\n)?"
    r"Output:[ \t]*(?:\r?\n|\Z)", re.I)
_ENVELOPE_ADVISORY = re.compile(r"Total output lines: \d+[ \t]*")
_ENVELOPE_CUT_WARNING = re.compile(r"Warning: truncated output[^\r\n]*")


class ExecEnvelope(NamedTuple):
    """Character extents in the ORIGINAL result, never a rewritten body.

    payload_start keeps all output, including cut disclosures. record_start skips
    only the harness's immediate advisory prefix for the positional typed-record
    reader. Neither extent searches for a record, a later Output, or a status.
    """
    payload_start: int
    record_start: int
    exit_code: int | None
    running: bool
    cut_warning: str


def exec_envelope(content: str) -> ExecEnvelope | None:
    """Recognize a closed exec header at offset zero; unknown shapes are untouched.

    This recognizes framing only. Call/result correlation and producer declarations
    remain the callers' authority; a native command's payload never proves a lowering.
    """
    match = _EXEC_HEADER.match(content)
    if not match or not (match["exit"] is not None or match["session"] is not None
                         or (match["chunk"] and match["wall"])):
        return None
    pos = match.end()
    warnings = []
    while pos < len(content):
        nl = content.find("\n", pos)
        end = nl + 1 if nl >= 0 else len(content)
        line = content[pos:nl if nl >= 0 else end].removesuffix("\r")
        if _ENVELOPE_CUT_WARNING.fullmatch(line):
            warnings.append(content[pos:end])  # exact warning bytes/EOL, never an authored substitute
        elif not _ENVELOPE_ADVISORY.fullmatch(line):
            break
        pos = end
    return ExecEnvelope(match.end(), pos, int(match["exit"]) if match["exit"] is not None else None,
                        match["session"] is not None, "".join(warnings))


def _strip_exec_envelope(content: str, *, preserve_eof: bool = False) -> str:
    """Display a re-presented tool's payload; unknown/unframed results are untouched.

    ``preserve_eof`` is accepted for caller compatibility only: EOF is data for
    EVERY result, not just a whole read. Neither value authorizes byte deletion.
    """
    envelope = exec_envelope(content)
    if envelope is None:
        return content
    # A bare advisory can itself be literal output. Only a real leading cut
    # disclosure authorizes the display's advisory removal; raw transcript readers
    # use payload_start and retain the ENTIRE output regardless.
    body = (envelope.cut_warning + content[envelope.record_start:] if envelope.cut_warning
            else content[envelope.payload_start:])
    return body


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
