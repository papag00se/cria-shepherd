"""The private names an EARLIER release lowered with, and the one reader that needs them below `wsview`.

Assembled from parts so no source line, prompt or log of the present release spells the product's name. `privatenames` renames a replayed
history with these; `wsview` reads a survey that rode home COMPRESSED (a typed record, a packed block), whose markers sit inside bytes no
rename of the result's text can reach. A leaf module: both import it, neither imports the other's concerns."""
from __future__ import annotations

import re

_P, _p = "CR" + "IA", "cr" + "ia"

# (earlier spelling, current spelling). Order matters: a longer run of underscores is the same name with a longer prefix.
LEGACY: tuple[tuple[str, str], ...] = (
    ("___" + _P + "_", "___CTX_"), ("__" + _P + "_", "__CTX_"), ("__" + _p + "_", "__ctx_"),
    ("." + _p + "-", ".ctx-"), (".gate-private-", ".ctx-private-"), (_P + "_RM", "CTX_RM"),
)
EARLIER_SURVEY_OPEN = LEGACY[0][0] + "SURVEY___"
_SURVEY_MARKER_LINE = re.compile("^" + re.escape(LEGACY[0][0]) + r"(SURVEY(?:_END)?|SV_[A-Za-z]+)___$", re.M)


def upgrade_survey(text: str) -> tuple[str, bool]:
    """``(text, earlier)``: a survey's whole-line markers in the current spelling, and whether any was the earlier release's. Only a line that
    IS a marker is renamed (never a name inside a record), and an earlier survey's ``progs``/``outside`` sections held raw names, so the
    reader must not take them for the encoded ones (a name like ``fish`` is valid base64)."""
    out, n = _SURVEY_MARKER_LINE.subn(lambda m: "___CTX_" + m.group(1) + "___", text)
    return out, n > 0
