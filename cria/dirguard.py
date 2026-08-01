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

from . import prompts

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
# A MUTATING command verb (write via the verb's operands) — _WRITE_VERB WITHOUT the `>>?` redirect. A
# redirect writes to ITS target, checked per-token by _is_write_target; only the verb form needs a
# whole-command scan (a `rm /external` mutates the external path). Splitting them stops a plain
# `grep /etc/hosts > local.txt` — whose only write verb is the redirect to a LOCAL file — from being
# false-refused as an external "write" (the redirect target is local; the external path is only read).
_MUTATING_VERB = re.compile(
    r"(?:^|[\s;&|(])(?:rm|mv|cp|dd|tee|mkdir|rmdir|touch|truncate|ln|chmod|chown|install|rsync)\b"
    r"|\bsed\s+-i\b", re.IGNORECASE)

# A command that makes a NETWORK request — a network URL scheme (even one built across a variable, the
# literal scheme still appears in the command text) or a known HTTP client. In such a command the
# rooted path-shaped tokens are almost always URL PATH fragments (`f'{BASE}/handles/goose'` → the regex
# sees `/handles/goose` after the `}`), NOT filesystem paths. This guard governs the FILESYSTEM, so it
# must never refuse a network call — the recurring footgun where a `requests.get(...)` read as an
# "external file" derailed the model into a false "no network from shell" theory.
_NETWORK_CMD = re.compile(
    r"\b(?:https?|ftps?|wss?)://|\b(?:curl|wget|requests|urllib3?|httpx|aiohttp|http\.client|socket)\b",
    re.IGNORECASE)
# The one external FILE access that survives the network-command exemption: an explicit write TARGET —
# the path is preceded by a `>`/`>>` redirect or a `-o`/`-O`/`--output`/`tee` (so `curl … -o /etc/x` and
# `curl … > /tmp/y` are still caught, but a URL path in the request is not).
_WRITE_TARGET_BEFORE = re.compile(r"(?:>>?|(?:^|\s)-[oO]|(?:^|\s)--output|(?:^|\s)tee)\s*$")

# A text-SEARCH / stream-edit tool whose QUOTED argument is a PATTERN or script, never a file path — so a
# rooted-looking quoted term (`grep "/handles/{handle}"`, `sed "s#/api/v1#X#"`) is the search expression,
# not an external file access. Files these tools touch are given as bare (unquoted) path args, which the
# scan still catches. Keyed off the command verb (generic shell knowledge, not model/harness-specific).
_TEXT_SEARCH_LEAD = re.compile(r"(?:^|[\s;&|(])(?:e?grep|fgrep|rg|ag|ack|sed|awk|gawk)\b", re.IGNORECASE)


# --- Installs: an external write whose destination the command never NAMES -------------------
#
# Every rule above reasons about a path token IN the command. A package manager takes its
# destination from the environment, so `pip install -e .` writes into the user's real
# site-packages while naming nothing outside the workspace — and the path scan finds nothing to
# refuse. Measured 2026-08-01: a run's `pip install -e .` left an `__editable__…pth` in the user's
# site-packages pointing at that run's /tmp workspace; two days later it was still on sys.path for
# every Python process on the box, shadowing `import handle_resolver` for later runs AND for the
# suite's own verifier.
#
# Matched here are only invocations whose destination is SHARED by default. A manager that
# installs into the project by default is absent on purpose: `npm install` (./node_modules),
# `composer require` (./vendor), `bundle install`, `cargo add`, `go get` are ordinary
# workspace-local work and must pass untouched. Their global FORMS are matched.
_GLOBAL_INSTALL = re.compile(
    r"(?:^|[\s;&|(])(?:"
    r"(?:pip|pip3|python3?\s+-m\s+pip)\s+install"          # user/system site-packages
    r"|(?:npm|pnpm|yarn)\s+(?:install|add|i)\b(?=[^;&|]*(?:\s-g\b|\s--global\b))"
    r"|(?:gem|cargo|go)\s+install"                          # ~/.gem, ~/.cargo/bin, GOPATH/bin
    r"|composer\s+global\b"
    r"|(?:apt|apt-get|dnf|yum|pacman|apk|brew)\s+(?:install|add)\b"
    r")", re.IGNORECASE)

# The same command made workspace-local. Any ONE of these means the install lands inside the
# project, so it is ordinary work: an interpreter/pip run from a RELATIVE path (`./.venv/bin/pip`),
# an explicit destination flag, or a venv activated in the same command line.
_LOCAL_INSTALL_SCOPE = re.compile(
    r"(?:^|[\s;&|(])\.{0,2}/?[\w.-]*(?:venv|env|virtualenv)[\w.-]*/bin/"   # ./.venv/bin/pip …
    r"|--target(?:=|\s)|--prefix(?:=|\s)|--root(?:=|\s)"
    r"|(?:^|[\s;&|(])(?:source|\.)\s+\.{0,2}/?[\w.-]*(?:venv|env)[\w.-]*/bin/activate",
    re.IGNORECASE)


def install_refusal(command: str, level: str, workspace: str | None) -> str | None:
    """The refusal for an install whose destination is SHARED, or None when allowed.

    Deliberately NOT a security control — the same best-effort posture as the rest of raw-shell
    handling. It closes the one hole that is invisible to a path scan by construction: the
    destination is decided by the environment, so there is no token to find.

    Allowed at ``write``, since that level means "no external-directory restriction" and an
    operator who set it has accepted exactly this. Refused at ``read`` too: ``read`` permits
    external READS, and an install is a write.
    """
    if level == "write" or not command:
        return None
    if not _GLOBAL_INSTALL.search(command):
        return None
    if _LOCAL_INSTALL_SCOPE.search(command):
        return None
    return prompts.fill(prompts.load("external_install_refusal"),
                        root=f" ({workspace})" if workspace else "")


def _is_write_target(command: str, start: int) -> bool:
    """True when the path token at ``start`` is the target of a file WRITE (a redirect or an output
    flag) — the only external file access still refused inside a network command."""
    return bool(_WRITE_TARGET_BEFORE.search(command[:start]))


def _quoted_spans(command: str) -> list[tuple[int, int]]:
    """(start, end) CONTENT ranges of single/double-quoted strings in the command. Used to skip a rooted
    path token that sits INSIDE a quote as a non-initial word — a search PATTERN, not a file: `grep -n
    "GET /handles" file` names no `/handles` FILE; the `/handles` is the grep term. Without this the guard
    refused the coder's own grep (the exact action cria's spill outline tells it to run), citing a path it
    never touched. A quote that OPENS with the path (`cat "/etc/my file"`) is still a real path — only a
    token that starts AFTER the quote's content-start is treated as a pattern. Best-effort: an unbalanced
    quote runs its span to end-of-string (degrades safe — over-skips, never over-refuses)."""
    spans: list[tuple[int, int]] = []
    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if c in "\"'":
            j = command.find(c, i + 1)
            if j == -1:
                spans.append((i + 1, n)); break
            spans.append((i + 1, j)); i = j + 1
        else:
            i += 1
    return spans


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


def _refusal(verb: str, path: str, workspace: str | None = None) -> str:
    # prompts/external_path_refusal.txt — {{PATH}} takes the quoted repr, matching the old f"{path!r}".
    # {{ROOT}} names the ACTUAL project directory when known: the anonymous "the project directory"
    # left a blocked model inventing roots (/tmp/src, /tmp/project) for whole runs — the refusal is
    # the one place cria can state the real one.
    root = f" ({workspace})" if workspace else ""
    return prompts.fill(prompts.load("external_path_refusal"), verb=verb, path=repr(path), root=root)


def path_refusal(path: str, is_write: bool, level: str, workspace: str | None) -> str | None:
    """The refusal for a synthetic file tool's EXPLICIT path, or None when allowed. read_file/list_dir
    are reads; write_file/edit_file are writes."""
    if level == "write" or _exempt(path) or not is_external(path, workspace):
        return None
    if level == "read" and not is_write:
        return None
    return _refusal("Writing" if is_write else "Reading", path, workspace)


def command_refusal(command: str, level: str, workspace: str | None) -> str | None:
    """The refusal for a RAW shell command, or None when allowed — heuristic: refuse when the command
    names an external absolute/``~`` path, weighed against whether it looks like a write. Under
    ``none`` any external path is refused; under ``read`` only an external WRITE is."""
    if level == "write" or not command:
        return None
    # An install writes outside the workspace WITHOUT naming a path, so it must be judged before
    # the path scan — which by construction finds nothing to refuse in it.
    installing = install_refusal(command, level, workspace)
    if installing:
        return installing
    network = bool(_NETWORK_CMD.search(command))
    search_cmd = bool(_TEXT_SEARCH_LEAD.search(command))
    spans = _quoted_spans(command)
    external = None
    ext_is_write = False
    for m in _PATH_TOKEN.finditer(command):
        tok = m.group(0)
        # A rooted token INSIDE a quoted string is a search PATTERN / literal, not a filesystem path,
        # when EITHER it does not open the quote (a mid-quote term like "GET /handles") OR the command is a
        # text-search/stream-edit tool whose quoted args are patterns ("/handles/{handle}" to grep is the
        # search term, not a file). A quoted path that opens the quote for a FILE command (`cat "/etc/x"`)
        # is still checked. Files for grep/sed are bare path args, which the scan still catches.
        inside = next((s for s, e in spans if s <= m.start() < e), None)
        if inside is not None and (m.start() != inside or search_cmd):
            continue
        if not is_external(tok, workspace) or _exempt(tok):
            continue
        # In a network request, a rooted path token is a URL fragment, not a file access — exempt it
        # unless it is an explicit write TARGET (curl -o /etc/x, > /tmp/y), which is a real external write.
        is_write = _is_write_target(command, m.start())
        if network and not is_write:
            continue
        external = tok
        ext_is_write = is_write
        break
    if external is None:
        return None
    # Under `read` level an external READ is allowed; refuse only when the EXTERNAL TOKEN ITSELF is a
    # write target — NOT when any write verb appears elsewhere (`grep /etc/hosts > local.txt` reads the
    # external file but writes LOCALLY, and must pass; the old whole-command _WRITE_VERB scan false-refused
    # it as "Writing", also misnaming the action).
    if level == "read" and not (ext_is_write or _MUTATING_VERB.search(command)):
        return None
    return _refusal("Writing/reading" if level == "none" else "Writing", external, workspace)
