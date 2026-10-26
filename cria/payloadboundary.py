"""Where the TOOL'S OWN payload ends in a result cria has since annotated (`bodykeys.PAYLOAD_BOUNDARY`).

Producers that append cria text to a tool result stamp the payload's length and digest (`resultnotes.append_note`); every
reader that must count, cache or quote only the tool's bytes asks here. A leaf module (no cria imports beyond `bodykeys`)
so the protocol owners (`denial`, `resultnotes`) can both depend on it without a cycle."""
from __future__ import annotations

import hashlib

from . import bodykeys


def digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


def payload_of(m: dict, content: str) -> str | None:
    """The tool's own payload within ``content``. No boundary ever stamped: the whole content (nothing was
    appended). A boundary still true of these bytes (length AND digest): the content cut there. A boundary
    that no longer verifies: None — the payload is UNKNOWN and a reader must abstain, never count the
    annotated carrier and never guess from marker text."""
    if bodykeys.PAYLOAD_BOUNDARY not in m:
        return content
    b = m[bodykeys.PAYLOAD_BOUNDARY]
    if isinstance(b, (tuple, list)) and len(b) == 2 and isinstance(b[0], int) \
            and 0 <= b[0] <= len(content) and digest(content[:b[0]]) == b[1]:
        return content[:b[0]]
    return None
