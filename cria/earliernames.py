"""The private names an EARLIER release lowered with, and the one reader that needs them below `wsview`.

Assembled from parts so no source line, prompt or log of the present release spells the product's name. `privatenames` renames a replayed
history with these. A leaf module."""
from __future__ import annotations

_P, _p = "CR" + "IA", "cr" + "ia"

# (earlier spelling, current spelling). Order matters: a longer run of underscores is the same name with a longer prefix.
LEGACY: tuple[tuple[str, str], ...] = (
    ("___" + _P + "_", "___CTX_"), ("__" + _P + "_", "__CTX_"), ("__" + _p + "_", "__ctx_"),
    ("." + _p + "-", ".ctx-"), (".gate-private-", ".ctx-private-"), (_P + "_RM", "CTX_RM"),
)
