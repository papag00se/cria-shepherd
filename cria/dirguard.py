"""External-directory permission — a cria-side bound on what the driven model's file tools may touch
OUTSIDE the workspace, enforced independently of the harness's own sandbox. So a harness run with its
approvals/sandbox turned OFF (``--yolo``/``danger-full-access``) is still restricted when it fronts a
fledgling, untrusted model.

Levels (config ``[safety] external_dir_permission``, default ``none``):
  * ``none``  — no reads or writes outside the workspace.
  * ``read``  — external reads allowed; external writes refused.
  * ``write`` — no external-directory restriction (the harness's own sandbox, if any, still applies).

Enforced at the tool-call chokepoint (``writeproxy.translate_outbound``): a violating synthetic file
tool or raw shell command is replaced with a refusal the model reads and self-corrects from. It is
ROBUST for the explicit paths of the synthetic file tools (write_file/edit_file/read_file/list_dir),
and BEST-EFFORT for raw shell — a heuristic path/verb scan that a determined model could obfuscate,
so it is a backstop for a WEAK model, not a security sandbox. The harness sandbox stays the real
boundary; this restricts a model the operator hasn't yet learned to trust.
"""

from __future__ import annotations

import os
import re

LEVELS = ("none", "read", "write")

# Absolute or ~-anchored FILE path tokens in a shell command. The lookbehind rejects a `/` that
# follows a word char, dot, COLON, or SLASH — so RELATIVE paths (`a/b`, `./x`, `.venv/bin`) AND URLs
# (`https://host/path`, `//host`) are NOT matched; only a rooted single-`/...` or `~/...`. This guard
# governs the FILESYSTEM, never the network — a `curl https://…`/`wget` must never be mistaken for an
# external file access. The token ends at whitespace or a shell metacharacter.
_PATH_TOKEN = re.compile(r"(?<![\w.:/])(?:~/|/(?!/))[^\s'\";|&><()`$*]*")
# Does the command WRITE (create/modify/delete a file) rather than only read? Heuristic: a write verb,
# or a `>`/`>>` redirection to a file (but not `>&`, an fd dup like `2>&1`).
_WRITE_VERB = re.compile(
    r"(?:^|[\s;&|(])(?:rm|mv|cp|dd|tee|mkdir|rmdir|touch|truncate|ln|chmod|chown|install|rsync)\b"
    r"|\bsed\s+-i\b|>>?(?![&\s]*&)", re.IGNORECASE)


def normalize_level(value: str | None) -> str:
    v = (value or "none").strip().lower()
    return v if v in LEVELS else "none"


def is_external(path: str, workspace: str | None) -> bool:
    """True when ``path`` resolves OUTSIDE ``workspace``. Lexical (normpath, no disk touch) so it
    works on a not-yet-existing path and ``..`` cannot escape the check. A relative path resolves
    against the workspace → internal; an absolute/``~`` path is internal only if it IS, or is under,
    the workspace. With no known workspace, any rooted path is treated as external."""
    if not path or not path.strip():
        return False
    p = os.path.expanduser(path.strip())
    if not workspace:
        return os.path.isabs(p) or path.strip().startswith("~")
    ws = os.path.normpath(os.path.expanduser(workspace))
    full = os.path.normpath(p if os.path.isabs(p) else os.path.join(ws, p))
    return full != ws and not full.startswith(ws + os.sep)


# System I/O plumbing — NOT external data. `2>/dev/null`, `> /dev/stderr`, `/dev/fd/…` etc. are
# ordinary shell redirection targets and device files; never treat them as an external file access.
# /proc and /sys are read-only kernel views a coder legitimately inspects. This guard is about the
# model reaching into another PROJECT's files, not the OS's plumbing.
_EXEMPT_PREFIXES = ("/dev/", "/proc/", "/sys/")
_EXEMPT_EXACT = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/stdin", "/dev/tty"}


def _exempt(path: str) -> bool:
    """A system path the guard must always allow (device/plumbing), even under ``none``."""
    p = os.path.normpath(os.path.expanduser(path.strip()))
    return p in _EXEMPT_EXACT or any(p == pre.rstrip("/") or p.startswith(pre) for pre in _EXEMPT_PREFIXES)


def _refusal(verb: str, path: str) -> str:
    return (f"{verb} outside the working directory is not permitted here — keep every file you read or "
            f"write inside the project directory. The path {path!r} is outside it; use a path within the "
            f"project instead.")


def path_refusal(path: str, is_write: bool, level: str, workspace: str | None) -> str | None:
    """The refusal for a synthetic file tool's EXPLICIT path, or None when allowed. read_file/list_dir
    are reads; write_file/edit_file are writes."""
    if level == "write" or _exempt(path) or not is_external(path, workspace):
        return None
    if level == "read" and not is_write:
        return None
    return _refusal("Writing" if is_write else "Reading", path)


def command_refusal(command: str, level: str, workspace: str | None) -> str | None:
    """The refusal for a RAW shell command, or None when allowed — heuristic: refuse when the command
    names an external absolute/``~`` path, weighed against whether it looks like a write. Under
    ``none`` any external path is refused; under ``read`` only an external WRITE is."""
    if level == "write" or not command:
        return None
    external = next((m.group(0) for m in _PATH_TOKEN.finditer(command)
                     if is_external(m.group(0), workspace) and not _exempt(m.group(0))), None)
    if external is None:
        return None
    if level == "read" and not _WRITE_VERB.search(command):
        return None
    return _refusal("Writing/reading" if level == "none" else "Writing", external)
