"""One place to parse tool-call arguments and pull the target path out of them.

Both operations were reimplemented across ~7 modules with divergent rules (some passed
`strict=False`, some didn't; the path alias list and its order drifted). These are the
canonical versions; callers delegate here so the rules can't diverge again.
"""

from __future__ import annotations

import json

from . import jsontext

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
        d = jsontext.loads(args, strict=False)   # THE model-JSON parser (repeated keys → first non-empty)
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


# WHICH WRITE IS CURRENT — one owner, because there were three and they disagreed.
#
# `focustrim._drop_superseded_writes` deleted a whole `write_file` because a later `edit_file`
# touched the same path, and told the coder "The newest version of each of those files is still here
# in full. Nothing was lost." Reproduced: a 3,000-character write followed by a 500-character edit
# leaves only the edit's `new_string` fragment in the view, under that sentence. An edit is not a
# version of a file; it is a change to one.
#
# The three lists also differed — focustrim had four names, contextfloor six, selfcompact two — so
# whether a call counted as a write depended on which module was asked.
#
# WHOLE_FILE_WRITES replace a file's contents outright, so a later one makes an earlier one
# historical. PARTIAL_WRITES change part of a file: they never supersede anything, and the file's
# current contents can only be had by reading it.
WHOLE_FILE_WRITES = ("write_file", "create_file", "text_editor")
PARTIAL_WRITES = ("edit_file", "apply_patch", "str_replace_editor")
WRITE_TOOL_NAMES = WHOLE_FILE_WRITES + PARTIAL_WRITES


def write_target(tc: dict) -> tuple[str, bool]:
    """``(path, replaces_whole_file)`` for a write-ish tool call, or ``("", False)``.

    The second value is the one that matters to any caller deciding whether a LATER call makes an
    earlier one redundant: only a whole-file write does."""
    fn = (tc or {}).get("function") or {}
    name = fn.get("name")
    if name not in WRITE_TOOL_NAMES:
        return "", False
    path = tool_path(parse_args(fn.get("arguments"))) or ""
    return path, name in WHOLE_FILE_WRITES


def write_path(tc: dict) -> str:
    """The path a write-ish tool call targets, or "" — whole-file or partial alike."""
    return write_target(tc)[0]
