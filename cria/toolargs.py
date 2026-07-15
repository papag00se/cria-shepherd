"""One place to parse tool-call arguments and pull the target path out of them.

Both operations were reimplemented across ~7 modules with divergent rules (some passed
`strict=False`, some didn't; the path alias list and its order drifted). These are the
canonical versions; callers delegate here so the rules can't diverge again.
"""

from __future__ import annotations

import json

# The file-path aliases a tool call may use, in preference order. Shared so the plain-dict
# extraction (`tool_path`) and the raw-regex extractors (for truncated JSON, in loop/massage)
# agree on the set.
PATH_KEYS = ("path", "file_path", "file", "filename")


def parse_args(args) -> dict:
    """Tool-call arguments → dict. A dict passes through; a JSON string is parsed LENIENTLY
    (`strict=False` tolerates the raw control chars a small model leaks into string values);
    anything unparseable or non-dict → ``{}``. Never raises."""
    if isinstance(args, dict):
        return args
    if not isinstance(args, str):
        try:
            return dict(args or {})
        except (TypeError, ValueError):
            return {}
    try:
        d = json.loads(args, strict=False)
    except (json.JSONDecodeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def tool_path(args) -> str | None:
    """The file path a tool call targets, from the standard aliases; None if absent/empty."""
    d = args if isinstance(args, dict) else parse_args(args)
    for k in PATH_KEYS:
        v = d.get(k)
        if v:
            return str(v)
    return None
