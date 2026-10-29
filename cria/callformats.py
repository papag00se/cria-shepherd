"""Deterministic call and patch format adapters; callers own policy and events."""
from __future__ import annotations

import re

from .callsyntax import _SHELL_ALIASES, _tool_names
from .callliterals import _decode_backslash_escapes
from .filecommands import _read_command as _wp_read_command

def _edit_to_patch(path: str, old: str, new: str) -> str:
    lines = ["*** Begin Patch", f"*** Update File: {path}"]
    lines += ["-" + l for l in old.split("\n")]
    lines += ["+" + l for l in new.split("\n")]
    lines.append("*** End Patch")
    return "\n".join(lines)


_SHELL_CMD_ALIASES = _SHELL_ALIASES  # same full command set (normalize_tool_calls + leaked-call aliasing)


_READ_NAMES = {"read_file", "cat_file", "view_file"}


_EXEC_NAMES = {"exec_command", "exec", "bash_command", "run_command"}


_BASH_HEADS = {"bash", "sh", "/bin/bash", "/bin/sh", "zsh"}


def _canon_key(name: str) -> str:
    """Fold case + separators only (EditFile / edit-file / Edit_File → 'editfile'). Deliberately NOT
    fuzzy — no edit-distance/plurals — so only a near-identical spelling collapses, never a different
    intent (bare `edit` stays `edit`)."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _canonical_name_map(tools) -> dict:
    """canon-key → the ONE advertised tool with that key; a key shared by ≥2 advertised tools is
    poisoned to None (ambiguous → never guess a rename)."""
    out: dict = {}
    for nm in _tool_names(tools):
        if not nm:
            continue
        k = _canon_key(nm)
        out[k] = None if k in out else nm
    return out


def _command_string(cmd):
    if isinstance(cmd, str):
        return cmd
    if isinstance(cmd, list):
        if len(cmd) == 1 and isinstance(cmd[0], list):
            cmd = cmd[0]  # double-wrapped [["bash","-lc",x]]
        if len(cmd) >= 3 and str(cmd[0]) in _BASH_HEADS and str(cmd[1]) in ("-lc", "-c"):
            return str(cmd[2])
        return " ".join(str(c) for c in cmd)
    return None


def _alias_command(name: str, args: dict) -> str:
    if "command" in args:
        return _command_string(args["command"]) or name
    parts = [name]
    for k in ("flags", "args", "arguments", "pattern", "query", "path", "file", "file_path", "dir"):
        v = args.get(k)
        if isinstance(v, str) and v:
            parts.append(v)
        elif isinstance(v, list):
            parts += [str(x) for x in v]
    return " ".join(parts)


def _normalize_read_args(args: dict) -> dict:
    """The shared canonical input to alias lowering and its private intent."""
    a = dict(args) if isinstance(args, dict) else {}
    for src, dst in (("start", "start_line"), ("end", "end_line")):
        if a.get(dst) is None and a.get(src) is not None:
            a[dst] = a[src]
    for k in ("start_line", "end_line"):   # writeproxy guards on int; coerce a stringy line number
        if a.get(k) is not None:
            try:
                a[k] = int(a[k])
            except (TypeError, ValueError):
                a.pop(k, None)
    return a


def _read_command(args: dict) -> str:
    """Lower aliases through the guarded filecommands owner."""
    return _wp_read_command(_normalize_read_args(args)) or ""


def _pure_add_file(body: str):
    path, content = None, []
    for line in body.splitlines():
        s = line.strip()
        if s in ("*** Begin Patch", "*** End Patch"):
            continue
        if s.startswith("*** Add File:"):
            if path is not None:
                return None  # more than one file — not a pure single add
            path = s[len("*** Add File:"):].strip()
        elif line.startswith("+"):
            content.append(line[1:])
        elif line.startswith("-") or s.startswith("@@") or s.startswith("*** "):
            return None  # a removal / hunk / other op → not a pure add
        else:
            content.append(line)  # bare content line
    return (path, "\n".join(content)) if path is not None else None


_HUNK = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@(.*)$")


def _normalize_patch_body(body: str) -> str:
    # Doubly-escaped newlines with no real ones → decode (the model escaped them). Use the SAME
    # byte-safe char decoder as the write_file path (only \n\t\r\\ and quotes): a `unicode_escape`
    # round-trip reinterprets UTF-8 as latin-1 → mojibake on any accented/CJK/emoji byte, and
    # over-decodes every other escape (\t, \\, \uXXXX) in the patch content.
    if "\\n" in body and "\n" not in body:
        body = _decode_backslash_escapes(body)
    body = _collapse_wrappers(body)  # one Begin/End around everything, not per-file
    body = _unified_to_native(body)  # `--- a/… / +++ b/…` → `*** Update/Add/Delete File:`
    body = _repair_hunk_headers(body)  # drop the miscounted `@@ -L,N +L,N @@` numbers
    body = _fix_hunk_lines(body)  # prefix bare content lines a model forgot to mark (any hunk)
    body = body.strip("\n")
    if "*** Begin Patch" not in body:
        body = "*** Begin Patch\n" + body
    if "*** End Patch" not in body:
        body = body.rstrip("\n") + "\n*** End Patch"
    return body


def _collapse_wrappers(body: str) -> str:
    return "\n".join(l for l in body.splitlines() if l.strip() not in ("*** Begin Patch", "*** End Patch"))


def _strip_ab(path: str) -> str:
    path = path.split("\t")[0].strip()
    return path[2:] if path[:2] in ("a/", "b/") else path


def _unified_to_native(body: str) -> str:
    lines = body.splitlines()
    # Native operations already identify their files. Header-looking +/- hunk
    # payload must not synthesize another operation (including a deletion).
    if any(line.startswith(("*** Update File:", "*** Add File:", "*** Delete File:"))
           for line in lines):
        return body
    out: list[str] = []
    remaining: list[int] | None = None
    i = 0
    while i < len(lines):
        line, nxt = lines[i], (lines[i + 1] if i + 1 < len(lines) else "")
        if remaining is not None:
            if line.startswith((" ", "-")):
                remaining[0] -= 1
            if line.startswith((" ", "+")):
                remaining[1] -= 1
            out.append(line)
            if remaining == [0, 0]:
                remaining = None
            i += 1
            continue
        hunk = re.match(r"^@@\s+-\d+(?:,(\d+))?\s+\+\d+(?:,(\d+))?\s+@@", line)
        if hunk:
            remaining = [int(value) if value is not None else 1 for value in hunk.groups()]
            if remaining == [0, 0]:
                remaining = None
        if line.startswith("--- ") and nxt.startswith("+++ "):
            old, new = line[4:].split("\t", 1)[0].strip(), nxt[4:].split("\t", 1)[0].strip()
            if old == "/dev/null":
                out.append(f"*** Add File: {_strip_ab(new)}")
            elif new == "/dev/null":
                out.append(f"*** Delete File: {_strip_ab(old)}")
            else:
                out.append(f"*** Update File: {_strip_ab(new)}")
            i += 2
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _repair_hunk_headers(body: str) -> str:
    out: list[str] = []
    for line in body.splitlines():
        m = _HUNK.match(line)
        if m:
            anchor = m.group(1).strip()
            if anchor:  # keep a useful context anchor, drop the line-number noise
                out.append(f"@@ {anchor}")
        else:
            out.append(line)
    return "\n".join(out)


def _fix_hunk_lines(body: str) -> str:
    """Prefix bare content lines a model forgot to mark. In an Add-File block every
    content line is an addition (context coerced, removals dropped); in an Update
    hunk only a truly bare line (not +/-/space, non-empty, not a `@@` header) becomes
    an addition — matching Codex Local's fix_apply_patch_body (bare → `+` in ANY hunk)."""
    out: list[str] = []
    mode = None  # None | "add" | "update"
    for line in body.splitlines():
        if line.startswith("*** Add File:"):
            mode = "add"
            out.append(line)
        elif line.startswith("*** Update File:"):
            mode = "update"
            out.append(line)
        elif line.startswith("*** "):  # Begin/End/Delete/End-of-File — not a content hunk
            mode = None
            out.append(line)
        elif line.startswith("@@"):  # a hunk header, never content
            out.append(line)
        elif mode == "add":
            if line.startswith("+"):
                out.append(line)  # already an addition
            elif line.startswith("-"):
                # A "removal" is impossible in a NEW file, so a bare '-' line is CONTENT the model forgot
                # to '+'-prefix (a YAML list item, a markdown bullet, CLI-help '-v') — keep it as an
                # addition, don't silently drop it (that destroyed the created file's content).
                out.append("+" + line)
            elif line.startswith(" "):
                out.append("+" + line[1:])  # context → addition
            else:
                out.append("+" + line)  # bare content → addition
        elif mode == "update":
            if line == "" or line.startswith(("+", "-", " ")):
                out.append(line)  # already prefixed / blank context line
            else:
                out.append("+" + line)  # bare content the model forgot to prefix → addition
        else:
            out.append(line)
    return "\n".join(out)
